"""Evaluador determinista: el veredicto sale del criterio sellado y de los datos.

No hay ninguna llamada a un modelo aquí. Si el criterio no estaba en el diseño
sellado, no se puede evaluar.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .detect import STRATEGIES, Brand
from .registry import Registry
from .stats import f1, rate_diff


def _detector_f1(design: dict, runs: list[dict]) -> tuple[str, dict]:
    numbers: dict = {"arms": {}}
    for arm in (design["candidate"], design["baseline"]):
        tp = fp = fn = tn = cited_ok = total = 0
        misses = []
        for run in (r for r in runs if r["arm"] == arm):
            truth, pred = json.loads(run["item"]), json.loads(run["answer"])
            total += 1
            cited_ok += truth["cited"] == pred["cited"]
            if truth["mentioned"] and pred["mentioned"]:
                tp += 1
            elif pred["mentioned"]:
                fp += 1
            elif truth["mentioned"]:
                fn += 1
            else:
                tn += 1
            if truth["mentioned"] != pred["mentioned"] or truth["cited"] != pred["cited"]:
                misses.append(run["item_id"])
        precision, recall, score = f1(tp, fp, fn)
        numbers["arms"][arm] = {
            "cases": total, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(score, 4),
            "cited_accuracy": round(cited_ok / total, 4) if total else 0.0,
            "wrong_cases": misses,
        }  # fmt: skip
    cand, base = numbers["arms"][design["candidate"]], numbers["arms"][design["baseline"]]
    numbers["gap"] = round(cand["f1"] - base["f1"], 4)
    ok = cand["cases"] == design["cases"] and cand["f1"] >= design["min_f1"] and numbers["gap"] >= design["min_gap"]
    return ("SUCCESS" if ok else "FAIL", numbers)


def _mention_rate_diff(design: dict, runs: list[dict]) -> tuple[str, dict]:
    brand = Brand.from_dict(design["brand"])
    detect = STRATEGIES[design["detector"]]
    counts = {}
    for arm in (design["control"], design["treatment"]):
        valid = [r for r in runs if r["arm"] == arm and not r["error"]]
        counts[arm] = (sum(detect(brand, r["answer"], r["citations"]).mentioned for r in valid), len(valid))
    (k1, n1), (k2, n2) = counts[design["control"]], counts[design["treatment"]]
    diff, low, high = rate_diff(k1, n1, k2, n2)
    numbers = {
        "control": {"mentions": k1, "answers": n1},
        "treatment": {"mentions": k2, "answers": n2},
        "diff": round(diff, 4), "low": round(low, 4), "high": round(high, 4),
        "min_effect": design["min_effect"], "min_answers_per_arm": design["min_answers_per_arm"],
    }  # fmt: skip
    if min(n1, n2) < design["min_answers_per_arm"]:
        return ("INCONCLUSIVE", numbers)
    if low > design["min_effect"]:
        return ("SUCCESS", numbers)
    if high <= design["min_effect"]:
        return ("FAIL", numbers)
    return ("INCONCLUSIVE", numbers)


METRICS = {"detector_f1": _detector_f1, "mention_rate_diff": _mention_rate_diff}


def evaluate(registry: Registry, exp_id: str) -> tuple[str, dict]:
    exp = registry.experiment(exp_id)
    if exp["kind"] != "experiment":
        raise ValueError(f"{exp_id} es una medición descriptiva: no tiene veredicto")
    if not registry.seal_is_intact(exp_id):
        raise ValueError(f"el sello de {exp_id} no coincide con su contenido")
    verdict, numbers = METRICS[exp["metric"]](exp["design"], registry.runs(exp_id))
    registry.add_verdict(exp_id, verdict, numbers)
    return verdict, numbers


def run_detector_bench(registry: Registry, bench_path: str | Path, brands_path: str | Path) -> str:
    """EXP de arranque: ¿el detector normalizado mide mejor que buscar el nombre a pelo?"""
    bench_bytes = Path(bench_path).read_bytes()
    cases = [json.loads(line) for line in bench_bytes.decode("utf-8").splitlines() if line.strip()]
    brands = {k: Brand.from_dict(v) for k, v in json.loads(Path(brands_path).read_text(encoding="utf-8")).items()}
    exp_id = registry.preregister(
        "experiment",
        hypothesis="El detector normalizado acierta las menciones con F1 >= 0,95 y supera en al menos 0,10 al de subcadena.",
        metric="detector_f1",
        design={
            "candidate": "normalized",
            "baseline": "naive",
            "min_f1": 0.95,
            "min_gap": 0.10,
            "cases": len(cases),
            "bench_sha256": hashlib.sha256(bench_bytes).hexdigest(),
        },
    )
    for arm in ("normalized", "naive"):
        for case in cases:
            found = STRATEGIES[arm](brands[case["brand"]], case["answer"], case["citations"])
            registry.add_run(
                exp_id,
                arm=arm,
                engine="detector",
                model=arm,
                item_id=case["id"],
                item=json.dumps({"mentioned": case["mentioned"], "cited": case["cited"]}),
                sample=0,
                answer=json.dumps({"mentioned": found.mentioned, "cited": found.cited}),
                citations=case["citations"],
            )
    return exp_id
