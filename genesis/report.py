"""Informe HTML de una medición. Solo presenta números ya calculados en ``audit.summarize``."""
from __future__ import annotations

from html import escape

from .detect import owns

CSS = """
:root { --bg:#fbfaf7; --ink:#1d1c1a; --soft:#6b6861; --line:#e3dfd6; --card:#ffffff; --accent:#0f5e4a; --warn:#9a3b1f; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151614; --ink:#ecebe6; --soft:#a3a096; --line:#2e302c; --card:#1d1f1c; --accent:#6fd3b3; --warn:#f0a184; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:860px; margin:0 auto; padding:40px 16px 64px; }
h1 { font-size:1.7rem; line-height:1.2; margin:0 0 6px; }
h2 { font-size:1.1rem; margin:36px 0 10px; }
.sub { color:var(--soft); margin:0 0 28px; }
.big { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:22px; }
.big strong { font-size:2.4rem; color:var(--accent); display:block; line-height:1.1; }
.big span { color:var(--soft); }
.wrap { overflow-x:auto; border:1px solid var(--line); border-radius:12px; background:var(--card); }
table { border-collapse:collapse; width:100%; font-size:.93rem; }
th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--soft); font-weight:600; white-space:nowrap; }
tr:last-child td { border-bottom:0; }
td.n { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
tr.me td { font-weight:700; }
.miss { color:var(--warn); font-weight:600; }
.own { color:var(--accent); font-weight:600; }
ul { padding-left:20px; } li { margin:4px 0; }
.meta { color:var(--soft); font-size:.88rem; }
"""


TEXT = {
    "es": {
        "pct": "{:.0f} %", "of": "de", "lang": "es",
        "title": "Visibilidad de {name} en asistentes de IA",
        "h1": "¿Recomiendan los asistentes de IA a {name}?",
        "sub": "Medición",
        "big": "{k} de {n} respuestas",
        "big_text": "nombran a {name}: {rate}, con un intervalo del 95 % entre {low} y {high}. Aparece al menos una vez en {covered} de las {prompts} preguntas.",
        "h_brands": "Quién aparece cuando un cliente pregunta",
        "th_brands": ["Marca", "Respuestas", "Frecuencia", "Intervalo 95 %", "Posición media", "Citada como fuente"],
        "h_prompts": "Pregunta a pregunta",
        "th_prompts": ["Pregunta", "Marcas nombradas (veces)"],
        "none_named": "ninguna de las marcas seguidas",
        "h_others": "Otros nombres que el asistente destaca",
        "others_note": "Nombres en negrita que no están en la lista seguida y salen en dos o más respuestas. Es una pista para ampliar la lista, no una medición: puede incluir títulos de sección.",
        "th_others": ["Nombre", "Respuestas"],
        "no_others": "Ninguno aparece en dos o más respuestas.",
        "h_sources": "De dónde saca el asistente la información",
        "th_sources": ["Sitio citado", "Respuestas que lo citan"],
        "no_sources": "El asistente no citó ninguna fuente.",
        "h_limits": "Qué mide esto y qué no",
        "limits": [
            "Cada pregunta se hizo {samples} veces porque los asistentes no responden siempre igual. Con {n} respuestas el intervalo es ancho: es una foto, no una tendencia.",
            "Solo se cuentan las marcas de la lista seguida; si el asistente recomienda otra, no sale en la tabla.",
            "La medición usa un único asistente por su interfaz de programación, que puede no coincidir con lo que ve una persona en la aplicación.",
            "Una marca cuenta como nombrada aunque se la mencione para desaconsejarla.",
            "Las respuestas repetidas de una misma pregunta no son independientes entre sí, así que el intervalo real es algo más ancho que el mostrado.",
        ],
        "meta": "Respuestas con error: {errors} · Coste equivalente: {cost:.2f} $ · Tiempo de consulta sumado: {seconds:.0f} s · Versión del código: {versions}",
    },
    "en": {
        "pct": "{:.0f}%", "of": "of", "lang": "en",
        "title": "{name} in AI assistant answers",
        "h1": "Do AI assistants recommend {name}?",
        "sub": "Measurement",
        "big": "{k} of {n} answers",
        "big_text": "name {name}: {rate}, with a 95% interval from {low} to {high}. It is named at least once in {covered} of the {prompts} questions.",
        "h_brands": "Who gets named when a buyer asks",
        "th_brands": ["Product", "Answers", "Share", "95% interval", "Average position", "Cited as a source"],
        "h_prompts": "Question by question",
        "th_prompts": ["Question", "Products named (times)"],
        "none_named": "none of the tracked products",
        "h_others": "Other names the assistant highlights",
        "others_note": "Names in bold that are not on the tracked list and appear in two or more answers. A lead for widening the list, not a measurement: it can include section headings.",
        "th_others": ["Name", "Answers"],
        "no_others": "None appears in two or more answers.",
        "h_sources": "Where the assistant gets its information",
        "th_sources": ["Site cited", "Answers that cite it"],
        "no_sources": "The assistant cited no sources.",
        "h_limits": "What this measures and what it does not",
        "limits": [
            "Each question was asked {samples} times because assistants do not answer the same way twice. With {n} answers the interval is wide: this is a snapshot, not a trend.",
            "Only the tracked products are counted; if the assistant recommends another one, it is not in the table.",
            "The measurement uses one assistant through its programming interface, which can differ from what a person sees in the app.",
            "A product counts as named even when it is mentioned unfavourably.",
            "Repeated answers to the same question are not independent, so the true interval is somewhat wider than shown.",
        ],
        "meta": "Answers with errors: {errors} · Equivalent cost: ${cost:.2f} · Total query time: {seconds:.0f} s · Code version: {versions}",
    },
}


def pct(x: float, lang: str = "es") -> str:
    return TEXT.get(lang, TEXT["es"])["pct"].format(100 * x)


def _head(cells: list[str]) -> str:
    return "<thead><tr>" + "".join(f"<th>{escape(c)}</th>" for c in cells) + "</tr></thead>"


def render(summary: dict, noindex: bool = False) -> str:
    """``noindex`` pide a los buscadores que no indexen la página (informes dirigidos a una marca)."""
    lang = summary.get("language", "es") if summary.get("language") in TEXT else "es"
    tx = TEXT[lang]
    t = summary["target"]
    n = summary["answers"]
    name = escape(t["name"])
    of = tx["of"]
    brand_rows = "".join(
        f"<tr class='{'me' if b['is_target'] else ''}'><td>{escape(b['name'])}</td>"
        f"<td class='n'>{b['mentions']} {of} {n}</td><td class='n'>{pct(b['rate'], lang)}</td>"
        f"<td class='n'>{pct(b['low'], lang)}–{pct(b['high'], lang)}</td>"
        f"<td class='n'>{'—' if b['mean_rank'] is None else f'{b['mean_rank']:.1f}'}</td>"
        f"<td class='n'>{b['cited']}</td></tr>"
        for b in summary["brands"]
    )
    prompt_rows = "".join(
        f"<tr><td>{escape(p['text'])}</td>"
        f"<td class='n {'' if p['target'] else 'miss'}'>{p['target']} {of} {p['answers']}</td>"
        f"<td>{escape(', '.join(f'{who} ({k})' for who, k in p['named']) or tx['none_named'])}</td></tr>"
        for p in summary["prompts"]
    )
    source_rows = "".join(
        f"<tr><td class='{'own' if any(owns(d, host) for d in summary['own_domains']) else ''}'>{escape(host)}</td>"
        f"<td class='n'>{k} {of} {n}</td></tr>"
        for host, k in summary["sources"]
    ) or f"<tr><td colspan='2'>{tx['no_sources']}</td></tr>"
    other_rows = "".join(
        f"<tr><td>{escape(who)}</td><td class='n'>{k} {of} {n}</td></tr>" for who, k in summary["others"]
    ) or f"<tr><td colspan='2'>{tx['no_others']}</td></tr>"
    big_text = tx["big_text"].format(
        name=name, rate=pct(t["rate"], lang), low=pct(t["low"], lang), high=pct(t["high"], lang),
        covered=summary["prompts_covered"], prompts=len(summary["prompts"]),
    )  # fmt: skip
    limits = "".join(f"<li>{line.format(samples=summary['samples'], n=n)}</li>" for line in tx["limits"])
    meta = tx["meta"].format(
        errors=summary["errors"], cost=summary["cost_usd"], seconds=summary["seconds"],
        versions=escape(", ".join(summary["code_versions"])),
    )  # fmt: skip
    prompt_head = [tx["th_prompts"][0], t["name"], tx["th_prompts"][1]]
    return f"""<!doctype html>
<html lang="{tx['lang']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{'<meta name="robots" content="noindex">' if noindex else ''}<title>{tx['title'].format(name=name)}</title><style>{CSS}</style></head><body><main>
<h1>{tx['h1'].format(name=name)}</h1>
<p class="sub">{tx['sub']} {escape(summary['id'])} · {escape(summary['engine'])} ({escape(summary['model'])}) · {escape(summary['created_at'][:10])}</p>

<div class="big"><strong>{tx['big'].format(k=t['mentions'], n=n)}</strong>
<span>{big_text}</span></div>

<h2>{tx['h_brands']}</h2>
<div class="wrap"><table>{_head(tx['th_brands'])}
<tbody>{brand_rows}</tbody></table></div>

<h2>{tx['h_prompts']}</h2>
<div class="wrap"><table>{_head(prompt_head)}
<tbody>{prompt_rows}</tbody></table></div>

<h2>{tx['h_others']}</h2>
<p class="meta">{tx['others_note']}</p>
<div class="wrap"><table>{_head(tx['th_others'])}
<tbody>{other_rows}</tbody></table></div>

<h2>{tx['h_sources']}</h2>
<div class="wrap"><table>{_head(tx['th_sources'])}
<tbody>{source_rows}</tbody></table></div>

<h2>{tx['h_limits']}</h2>
<ul>{limits}</ul>
<p class="meta">{meta}</p>
</main></body></html>
"""
