"""Medición de visibilidad: preguntar a un motor y contar, sin interpretar."""
from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .detect import STRATEGIES, Brand, host_of
from .engines import Engine
from .registry import Registry
from .stats import wilson

DETECTOR = "normalized"
# Los asistentes suelen poner en negrita lo que recomiendan: **Nombre** o **[Nombre](enlace)**.
BOLD_RE = re.compile(r"\*\*\[?([^*\]\n]{2,40})\]?(?:\([^)\n]*\))?\*\*")


def highlighted_names(text: str) -> set[str]:
    """Nombres que el asistente destaca en negrita. Es una pista, no una medición."""
    names = set()
    for raw in BOLD_RE.findall(text):
        name = raw.strip(" :.,")
        if 2 <= len(name) <= 40 and len(name.split()) <= 4 and not name.endswith("?"):
            names.add(name)
    return names


def load_profile(path: str | Path) -> dict:
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("id", "brand", "competitors", "prompts"):
        if key not in profile:
            raise ValueError(f"al perfil {path} le falta '{key}'")
    if not profile["prompts"]:
        raise ValueError(f"el perfil {path} no tiene preguntas")
    ids = [p["id"] for p in profile["prompts"]]
    if len(set(ids)) != len(ids):
        raise ValueError(f"el perfil {path} repite identificadores de pregunta")
    Brand.from_dict(profile["brand"])
    for c in profile["competitors"]:
        Brand.from_dict(c)
    return profile


def collect(
    registry: Registry,
    exp_id: str,
    arm: str,
    engine: Engine,
    prompts: list[dict],
    samples: int,
    workers: int = 4,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Hace cada pregunta ``samples`` veces y guarda cada respuesta tal cual llega."""
    jobs = [(p, s) for p in prompts for s in range(samples)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        answers = pool.map(lambda job: engine.ask(job[0]["text"], job[1]), jobs)
        for done, ((prompt, sample), answer) in enumerate(zip(jobs, answers), start=1):
            registry.add_run(
                exp_id,
                arm=arm,
                engine=engine.name,
                model=engine.model,
                item_id=prompt["id"],
                item=prompt["text"],
                sample=sample,
                answer=answer.text,
                citations=answer.citations,
                cost_usd=answer.cost_usd,
                seconds=answer.seconds,
                error=answer.error,
            )
            if progress:
                progress(done, len(jobs))


def run_measurement(
    registry: Registry,
    profile: dict,
    engine: Engine,
    samples: int,
    workers: int = 4,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    brand = profile["brand"]["name"]
    exp_id = registry.preregister(
        "measurement",
        hypothesis=f"Medición descriptiva: con qué frecuencia nombra {engine.name} a {brand} en las preguntas del perfil.",
        metric="mention_rate",
        design={
            "profile": profile,
            "engine": engine.name,
            "model": engine.model,
            "samples": samples,
            "detector": DETECTOR,
        },
    )
    collect(registry, exp_id, "medicion", engine, profile["prompts"], samples, workers, progress)
    return exp_id


def summarize(registry: Registry, exp_id: str, target_name: str | None = None) -> dict:
    """Resumen calculado solo a partir de las respuestas guardadas.

    Una medición de una categoría sirve para cualquiera de sus marcas:
    ``target_name`` elige a cuál se dirige el informe.
    """
    exp = registry.experiment(exp_id)
    if exp["kind"] != "measurement":
        raise ValueError(f"{exp_id} no es una medición")
    design = exp["design"]
    profile = design["profile"]
    detect = STRATEGIES[design["detector"]]
    brands = [Brand.from_dict(profile["brand"])] + [Brand.from_dict(c) for c in profile["competitors"]]
    wanted = (target_name or profile["brand"]["name"]).lower()
    target = next((b for b in brands if b.name.lower() == wanted), None)
    if target is None:
        raise ValueError(f"«{target_name}» no está entre las marcas de {exp_id}")

    runs = registry.runs(exp_id)
    valid = [r for r in runs if not r["error"]]
    n = len(valid)

    mentions: Counter[str] = Counter()
    cites: Counter[str] = Counter()
    rank_sum: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    others: Counter[str] = Counter()
    per_prompt: dict[str, dict] = {
        p["id"]: {"id": p["id"], "text": p["text"], "answers": 0, "target": 0, "named": Counter()}
        for p in profile["prompts"]
    }
    for run in valid:
        found = {b.name: detect(b, run["answer"], run["citations"]) for b in brands}
        order = sorted((d.position, name) for name, d in found.items() if d.mentioned)
        for rank, (_, name) in enumerate(order, start=1):
            rank_sum[name] += rank
        row = per_prompt[run["item_id"]]
        row["answers"] += 1
        for name, d in found.items():
            mentions[name] += d.mentioned
            cites[name] += d.cited
            if d.mentioned:
                row["named"][name] += 1
        row["target"] += found[target.name].mentioned
        for host in {host_of(u) for u in run["citations"]} - {""}:
            sources[host] += 1
        for name in highlighted_names(run["answer"]):
            if not any(detect(b, name, []).mentioned for b in brands):
                others[name] += 1

    def brand_row(b: Brand) -> dict:
        k = mentions[b.name]
        low, high = wilson(k, n)
        return {
            "name": b.name,
            "is_target": b.name == target.name,
            "mentions": k,
            "rate": k / n if n else 0.0,
            "low": low,
            "high": high,
            "cited": cites[b.name],
            "mean_rank": rank_sum[b.name] / k if k else None,
        }

    table = sorted((brand_row(b) for b in brands), key=lambda r: (-r["mentions"], r["name"]))
    prompts = [
        {**row, "named": row["named"].most_common()} for row in per_prompt.values()
    ]
    return {
        "id": exp_id,
        "created_at": exp["created_at"],
        "engine": design["engine"],
        "model": design["model"],
        "samples": design["samples"],
        "profile_id": profile["id"],
        "language": profile.get("language", "es"),
        "target": next(r for r in table if r["is_target"]),
        "brands": table,
        "prompts": prompts,
        "prompts_covered": sum(1 for p in prompts if p["target"] > 0),
        "answers": n,
        "errors": len(runs) - n,
        "sources": sources.most_common(15),
        "others": [(name, k) for name, k in others.most_common(12) if k >= 2],
        "own_domains": list(target.domains),
        "cost_usd": round(sum(r["cost_usd"] for r in runs), 4),
        "seconds": round(sum(r["seconds"] for r in runs), 1),
        "code_versions": sorted({r["code_version"] for r in runs}),
    }


def start_before_after(
    registry: Registry,
    profile: dict,
    engine: Engine,
    samples: int,
    treatment: str,
    min_effect: float = 0.0,
    workers: int = 4,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    """Sella un experimento antes/después y recoge ya el brazo «antes».

    El criterio queda fijado aquí: cuando se mida el «después» no se puede tocar.
    """
    planned = len(profile["prompts"]) * samples
    exp_id = registry.preregister(
        "experiment",
        hypothesis=f"Después de «{treatment}», {engine.name} nombra a {profile['brand']['name']} con más frecuencia que antes.",
        metric="mention_rate_diff",
        design={
            "brand": profile["brand"],
            "detector": DETECTOR,
            "control": "antes",
            "treatment": "despues",
            "treatment_description": treatment,
            "min_effect": min_effect,
            "min_answers_per_arm": int(0.9 * planned),
            "prompts": profile["prompts"],
            "engine": engine.name,
            "model": engine.model,
            "samples": samples,
        },
    )
    collect(registry, exp_id, "antes", engine, profile["prompts"], samples, workers, progress)
    return exp_id


def finish_before_after(
    registry: Registry,
    exp_id: str,
    engine: Engine,
    workers: int = 4,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[str, dict]:
    """Recoge el brazo «después» con las mismas preguntas y motor, y evalúa."""
    from .evaluator import evaluate

    exp = registry.experiment(exp_id)
    design = exp["design"]
    if exp["metric"] != "mention_rate_diff":
        raise ValueError(f"{exp_id} no es un experimento antes/después")
    if (engine.name, engine.model) != (design["engine"], design["model"]):
        raise ValueError(f"{exp_id} se selló con {design['engine']}/{design['model']}; no se puede cerrar con otro motor")
    if any(r["arm"] == design["treatment"] for r in registry.runs(exp_id)):
        raise ValueError(f"{exp_id} ya tiene medido el «después»")
    collect(registry, exp_id, design["treatment"], engine, design["prompts"], design["samples"], workers, progress)
    return evaluate(registry, exp_id)
