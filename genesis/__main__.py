"""Línea de órdenes: ``python3 -m genesis <orden>``."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .audit import finish_before_after, load_profile, run_measurement, start_before_after, summarize
from .engines import build_engine
from .evaluator import evaluate, run_detector_bench
from .registry import Registry
from .report import pct, render
from .site import render_landing

ROOT = Path(__file__).resolve().parent.parent


def cmd_bench(args: argparse.Namespace, reg: Registry) -> int:
    exp_id = run_detector_bench(reg, ROOT / "data/detector_bench.jsonl", ROOT / "data/detector_brands.json")
    verdict, numbers = evaluate(reg, exp_id)
    print(f"{exp_id}: {verdict}  (diferencia de F1: {numbers['gap']:+.3f})")
    for arm, a in numbers["arms"].items():
        print(
            f"  {arm:11s} casos={a['cases']} precisión={a['precision']:.3f} exhaustividad={a['recall']:.3f}"
            f" F1={a['f1']:.3f} citas_ok={a['cited_accuracy']:.3f} fallos={','.join(a['wrong_cases']) or '-'}"
        )
    return 0 if verdict == "SUCCESS" else 1


def cmd_audit(args: argparse.Namespace, reg: Registry) -> int:
    profile = load_profile(args.profile)
    engine = build_engine(args.engine, args.model)
    total = len(profile["prompts"]) * args.samples
    print(f"{total} consultas a {engine.name} ({engine.model})…", flush=True)
    exp_id = run_measurement(
        reg, profile, engine, args.samples, args.workers,
        progress=lambda done, n: print(f"  {done}/{n}", flush=True),
    )  # fmt: skip
    print_summary(summarize(reg, exp_id))
    return 0


def cmd_exp_start(args: argparse.Namespace, reg: Registry) -> int:
    profile = load_profile(args.profile)
    engine = build_engine(args.engine, args.model)
    print(f"Sellando y midiendo el «antes»: {len(profile['prompts']) * args.samples} consultas a {engine.name} ({engine.model})…", flush=True)
    exp_id = start_before_after(
        reg, profile, engine, args.samples, args.treatment, workers=args.workers,
        progress=lambda done, n: print(f"  {done}/{n}", flush=True),
    )  # fmt: skip
    print(f"{exp_id} sellado. Cuando el cambio esté hecho: python3 -m genesis exp-close {exp_id}")
    return 0


def cmd_exp_close(args: argparse.Namespace, reg: Registry) -> int:
    design = reg.experiment(args.id)["design"]
    engine = build_engine(design.get("engine", ""), design.get("model"))
    verdict, numbers = finish_before_after(
        reg, args.id, engine, workers=args.workers,
        progress=lambda done, n: print(f"  {done}/{n}", flush=True),
    )  # fmt: skip
    c, t = numbers["control"], numbers["treatment"]
    print(f"{args.id}: {verdict}  antes {c['mentions']}/{c['answers']} · después {t['mentions']}/{t['answers']}"
          f" · diferencia {numbers['diff']:+.2f} (IC95 {numbers['low']:+.2f} a {numbers['high']:+.2f})")  # fmt: skip
    return 0


def print_summary(s: dict) -> None:
    t = s["target"]
    print(f"{s['id']} · {s['engine']} ({s['model']}) · {s['answers']} respuestas, {s['errors']} con error · {s['cost_usd']:.2f} $")
    print(f"{t['name']}: {t['mentions']} de {s['answers']} ({pct(t['rate'])}, IC95 {pct(t['low'])}–{pct(t['high'])});"
          f" en {s['prompts_covered']} de {len(s['prompts'])} preguntas")  # fmt: skip
    for b in s["brands"]:
        print(f"  {b['name']:28s} {b['mentions']:3d}  {pct(b['rate']):>5s}  citada {b['cited']}")


def cmd_report(args: argparse.Namespace, reg: Registry) -> int:
    summary = summarize(reg, args.id, args.target)
    out = Path(args.out or ROOT / "informes" / f"{slug_of(summary['target']['name'])}-{args.id}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(summary), encoding="utf-8")
    print_summary(summary)
    print(out)
    return 0


def slug_of(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def cmd_prospects(args: argparse.Namespace, reg: Registry) -> int:
    """De una medición de categoría saca un informe por cada marca poco visible con web propia."""
    base = summarize(reg, args.id)
    out_dir = Path(args.out or ROOT / "prospectos" / f"{base['profile_id']}-{args.id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for brand in base["brands"]:
        s = summarize(reg, args.id, brand["name"])
        if brand["rate"] > args.max_rate or not s["own_domains"]:
            continue
        report = out_dir / f"{slug_of(brand['name'])}.html"
        report.write_text(render(s, noindex=True), encoding="utf-8")
        t = s["target"]
        rows.append([t["name"], s["own_domains"][0], t["mentions"], s["answers"], f"{t['rate']:.3f}",
                     f"{t['low']:.3f}", f"{t['high']:.3f}", s["prompts_covered"], len(s["prompts"]), report.name])  # fmt: skip
    with open(out_dir / "prospectos.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["marca", "dominio", "menciones", "respuestas", "frecuencia", "ic95_bajo", "ic95_alto",
                         "preguntas_con_mencion", "preguntas", "informe"])  # fmt: skip
        writer.writerows(rows)
    print(f"{len(rows)} prospectos con informe en {out_dir}")
    return 0


def cmd_landing(args: argparse.Namespace, reg: Registry) -> int:
    out = Path(args.out or ROOT / "web" / "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    html = render_landing(summarize(reg, args.id), args.brand, args.contact, args.shown, args.category, args.more)
    out.write_text(html, encoding="utf-8")
    print(out)
    return 0


def cmd_ledger(args: argparse.Namespace, reg: Registry) -> int:
    for exp in reg.experiments():
        verdicts = reg.verdicts(exp["id"])
        state = verdicts[-1]["verdict"] if verdicts else ("—" if exp["kind"] == "measurement" else "SIN EVALUAR")
        print(f"{exp['id']}  {exp['created_at']}  {state:12s} {exp['hypothesis']}")
    for row in reg.ledger():
        print(f"  coste {row['experiment_id']} {row['engine']}/{row['model']}: {row['runs']} ejecuciones,"
              f" {row['errors']} errores, {row['cost_usd']} $, {row['seconds']} s")  # fmt: skip
    for k in reg.knowledge():
        print(f"  sabido #{k['id']} [{', '.join(k['evidence'])}]: {k['rule']} — {k['conditions']}")
    return 0


def cmd_learn(args: argparse.Namespace, reg: Registry) -> int:
    new_id = reg.add_knowledge(args.rule, args.conditions, args.evidence, args.supersedes)
    print(f"sabido #{new_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="genesis", description="Motor de medición y experimentos de visibilidad en asistentes de IA.")
    parser.add_argument("--db", default=str(ROOT / "registro" / "genesis.db"), help="fichero del registro")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("bench", help="compara los dos detectores sobre el banco etiquetado").set_defaults(fn=cmd_bench)

    a = sub.add_parser("audit", help="mide la visibilidad de una marca con un motor real")
    a.add_argument("profile")
    a.add_argument("--engine", default="claude-cli")
    a.add_argument("--model", default=None)
    a.add_argument("--samples", type=int, default=2)
    a.add_argument("--workers", type=int, default=4)
    a.set_defaults(fn=cmd_audit)

    e = sub.add_parser("exp-start", help="sella un experimento antes/después y mide el «antes»")
    e.add_argument("profile")
    e.add_argument("--treatment", required=True, help="el cambio que se va a hacer, en una frase")
    e.add_argument("--engine", default="claude-cli")
    e.add_argument("--model", default=None)
    e.add_argument("--samples", type=int, default=6)
    e.add_argument("--workers", type=int, default=4)
    e.set_defaults(fn=cmd_exp_start)

    c = sub.add_parser("exp-close", help="mide el «después» de un experimento sellado y da el veredicto")
    c.add_argument("id")
    c.add_argument("--workers", type=int, default=4)
    c.set_defaults(fn=cmd_exp_close)

    r = sub.add_parser("report", help="genera el informe HTML de una medición")
    r.add_argument("id")
    r.add_argument("--target", help="marca de la medición a la que se dirige el informe")
    r.add_argument("-o", "--out")
    r.set_defaults(fn=cmd_report)

    pr = sub.add_parser("prospects", help="informes y lista de las marcas poco visibles de una medición de categoría")
    pr.add_argument("id")
    pr.add_argument("--max-rate", type=float, default=0.25, help="frecuencia máxima para considerarla prospecto")
    pr.add_argument("-o", "--out")
    pr.set_defaults(fn=cmd_prospects)

    la = sub.add_parser("landing", help="página de venta con el ejemplo real de una medición")
    la.add_argument("id")
    la.add_argument("--brand", required=True)
    la.add_argument("--contact", required=True, help="correo o URL donde pedir el informe")
    la.add_argument("--shown", type=int, default=8, help="cuántas marcas enseña el ejemplo")
    la.add_argument("--category", default="", help="nombre de la categoría en el titular del ejemplo")
    la.add_argument("--more", default="", help="URL de la medición completa")
    la.add_argument("-o", "--out")
    la.set_defaults(fn=cmd_landing)

    sub.add_parser("ledger", help="lista experimentos, veredictos, costes y conocimiento").set_defaults(fn=cmd_ledger)

    k = sub.add_parser("learn", help="anota una regla respaldada por experimentos del registro")
    k.add_argument("rule")
    k.add_argument("--conditions", required=True)
    k.add_argument("--evidence", nargs="+", required=True)
    k.add_argument("--supersedes", type=int)
    k.set_defaults(fn=cmd_learn)

    args = parser.parse_args(argv)
    reg = Registry(args.db)
    try:
        return args.fn(args, reg)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        reg.close()


if __name__ == "__main__":
    sys.exit(main())
