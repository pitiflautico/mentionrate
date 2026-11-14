"""¿Predice la presencia en las páginas que cita el asistente a quién nombra?

Para cada medición de categoría parte las respuestas en dos mitades por número de muestra:
- mitad «fuentes» (muestras pares): de ahí salen las páginas más citadas, que se descargan una vez;
- mitad «objetivo» (muestras impares): de ahí sale la cuota de menciones de cada marca.
La puntuación de una marca es la parte del peso de esas páginas en las que aparece su nombre.
No usa ningún modelo de lenguaje: descarga, cuenta y correlaciona.

Uso: python3 modelo.py MED-0003 MED-0004 ...   [--top 12] [--con-propias]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from genesis.detect import Brand, detect_normalized, host_of, owns
from genesis.pages import MIN_TEXT, most_cited, page_text
from genesis.registry import Registry

ROOT = Path(__file__).resolve().parent


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def analyse(reg: Registry, exp_id: str, top: int, with_own: bool) -> dict:
    profile = reg.experiment(exp_id)["design"]["profile"]
    brands = [Brand.from_dict(b) for b in (profile["brand"], *profile["competitors"])]
    runs = [r for r in reg.runs(exp_id) if not r["error"]]
    source_half = [r for r in runs if r["sample"] % 2 == 0]
    target_half = [r for r in runs if r["sample"] % 2 == 1]

    pages = most_cited(source_half, top)
    texts = {url: page_text(url) for url, _ in pages}
    readable = [(url, w) for url, w in pages if len(texts[url]) >= MIN_TEXT]
    total = sum(w for _, w in readable) or 1

    rows = []
    for b in brands:
        weight = 0
        for url, w in readable:
            own = any(owns(d, host_of(url)) for d in b.domains)
            if own and not with_own:
                continue
            if detect_normalized(b, texts[url], []).mentioned:
                weight += w
        named = sum(1 for r in target_half if detect_normalized(b, r["answer"], r["citations"]).mentioned)
        rows.append({"name": b.name, "score": weight / total, "share": named / len(target_half)})
    on = [r for r in rows if r["score"] > 0]
    off = [r for r in rows if r["score"] == 0]
    return {
        "id": exp_id,
        "profile": profile["id"],
        "pages": len(pages),
        "readable": len(readable),
        "rho": spearman([r["score"] for r in rows], [r["share"] for r in rows]),
        "named_if_on": sum(1 for r in on if r["share"] > 0) / len(on) if on else None,
        "named_if_off": sum(1 for r in off if r["share"] > 0) / len(off) if off else None,
        "n_on": len(on),
        "n_off": len(off),
        "rows": sorted(rows, key=lambda r: (-r["score"], r["name"])),
        "top_pages": readable,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--top", type=int, default=12, help="cuántas páginas citadas se leen por categoría")
    ap.add_argument("--con-propias", action="store_true", help="cuenta también las páginas del dominio de la marca")
    ap.add_argument("--detalle", action="store_true")
    args = ap.parse_args()
    reg = Registry(ROOT / "registro" / "genesis.db")
    rhos = []
    for exp_id in args.ids:
        a = analyse(reg, exp_id, args.top, args.con_propias)
        rhos.append(a["rho"])
        fmt = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
        print(f"{a['id']} {a['profile']:20s} páginas {a['readable']}/{a['pages']}  rho {a['rho']:+.2f}  "
              f"nombradas si están en alguna página {fmt(a['named_if_on'])} (n={a['n_on']})  si en ninguna {fmt(a['named_if_off'])} (n={a['n_off']})")  # fmt: skip
        if args.detalle:
            for r in a["rows"]:
                print(f"    {r['name']:26s} presencia {r['score']:.2f}  cuota {r['share']:.2f}")
    print(f"mediana de rho: {sorted(rhos)[len(rhos) // 2]:+.2f}  mínimo: {min(rhos):+.2f}")


if __name__ == "__main__":
    main()
