"""Página de venta. Los números de ejemplo salen de una medición real del registro."""
from __future__ import annotations

from html import escape

from .report import pct

CSS = """
:root { --bg:#fbfaf7; --ink:#1d1c1a; --soft:#6b6861; --line:#e3dfd6; --card:#ffffff; --accent:#0f5e4a; --bar:#cfe6dd; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151614; --ink:#ecebe6; --soft:#a3a096; --line:#2e302c; --card:#1d1f1c; --accent:#6fd3b3; --bar:#24443a; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:17px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:760px; margin:0 auto; padding:56px 16px 72px; }
.brand { font-weight:700; letter-spacing:.02em; color:var(--accent); margin:0 0 40px; }
h1 { font-size:clamp(2rem,6vw,3rem); line-height:1.08; margin:0 0 16px; text-wrap:balance; }
h2 { font-size:1.25rem; margin:52px 0 12px; }
.lead { font-size:1.15rem; color:var(--soft); margin:0 0 28px; }
.cta { display:inline-block; background:var(--accent); color:var(--bg); font-weight:700; padding:13px 22px; border-radius:10px; text-decoration:none; }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; }
.row { display:grid; grid-template-columns:8.5rem 1fr 3.2rem; gap:10px; align-items:center; margin:7px 0; font-size:.95rem; }
.track { height:12px; border-radius:6px; background:var(--bar); overflow:hidden; }
.fill { height:100%; background:var(--accent); border-radius:6px; }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.note { color:var(--soft); font-size:.9rem; margin:14px 0 0; }
table { width:100%; border-collapse:collapse; font-size:.95rem; } th, td { text-align:left; padding:7px 6px; border-bottom:1px solid var(--line); }
th { color:var(--soft); font-weight:600; } th.num, td.num { text-align:right; }
a { color:var(--accent); } .cta { color:var(--bg); }
ol, ul { padding-left:22px; } li { margin:6px 0; }
.plans { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }
.plans .card strong { display:block; font-size:1.5rem; margin:4px 0 8px; }
.plans .card span { color:var(--soft); font-size:.95rem; }
footer { margin-top:56px; color:var(--soft); font-size:.88rem; }
"""


def render_landing(
    summary: dict,
    brand: str,
    contact: str,
    shown: int = 8,
    category: str = "",
    more: str = "",
    categories: list[tuple[str, str]] | None = None,
    finding: list[tuple[str, str, float]] | None = None,
) -> str:
    """``contact`` es un correo o una URL donde pedir el informe; ``more`` enlaza la medición completa.

    ``categories`` son (nombre, enlace) de las demás mediciones publicadas; ``finding`` son
    (categoría, papel, correlación) de la prueba de qué predice las menciones.
    """
    other_html = ""
    if categories:
        links = "".join(f"<li><a href='{escape(href)}'>{escape(label.capitalize())}</a></li>" for label, href in categories)
        other_html = f"<h2>More categories measured</h2>\n<ul>{links}</ul>"
    finding_html = ""
    if finding:
        rows = "".join(
            f"<tr><td>{escape(label.capitalize())}</td><td>{escape(role)}</td><td class='num'>{rho:.2f}</td></tr>"
            for label, role, rho in finding
        )
        finding_html = f"""<h2>What predicts being named</h2>
<p>The pages an assistant cites most predict which products it names. We chose the rule on some categories and sealed the prediction before testing it on others.</p>
<div class="card"><table><thead><tr><th>Category</th><th>Used for</th><th class="num">Rank correlation</th></tr></thead><tbody>{rows}</tbody></table>
<p class="note">Spearman correlation between a product's presence on the 20 most cited pages and how often it is named. It is a correlation: well-known products are both written about and named, and some products appear on cited pages without ever being named.</p></div>"""
    category = category or summary["profile_id"].replace("-", " ")
    more_link = f" <a href='{escape(more)}'>See every question, answer and source.</a>" if more else ""
    in_question = [
        b["name"] for b in summary["brands"] if any(b["name"].lower() in p["text"].lower() for p in summary["prompts"])
    ]
    bias = f" {escape(', '.join(in_question))} appears in the wording of a question, which raises its count." if in_question else ""
    n = summary["answers"]
    top = summary["brands"][:shown]
    low = sum(1 for b in summary["brands"] if b["rate"] < 0.25)
    never = sum(1 for b in summary["brands"] if b["mentions"] == 0)
    rows = "".join(
        f"<div class='row'><span>{escape(b['name'])}</span>"
        f"<div class='track'><div class='fill' style='width:{100 * b['rate']:.0f}%'></div></div>"
        f"<span class='num'>{pct(b['rate'], 'en')}</span></div>"
        for b in top
    )
    is_url = contact.startswith(("http://", "https://"))
    mailto = escape(contact) if is_url else f"mailto:{escape(contact)}?subject=Free%20AI%20visibility%20report"
    email = "Request a report" if is_url else contact
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(brand)}: do AI assistants recommend your product?</title><style>{CSS}</style></head><body><main>
<p class="brand">{escape(brand)}</p>
<h1>Do AI assistants recommend your product?</h1>
<p class="lead">We ask an assistant the questions your buyers ask, dozens of times, and count who gets named. You get the numbers, the products named instead of yours, and the pages the assistant relied on.</p>
<a class="cta" href="{mailto}">Get a free report for your product</a>

<h2>A real example: {escape(category)}</h2>
<div class="card">{rows}
<p class="note">Share of {n} answers that name each product. {len(summary['prompts'])} buyer questions, each asked {summary['samples']} times to Claude ({escape(summary['model'])}) with web search, on {escape(summary['created_at'][:10])}. Of the {len(summary['brands'])} products tracked, {low} were named in fewer than a quarter of the answers, {never} of them never.{bias} A product counts as named even when the answer advises against it, and products outside the tracked list are not counted.{more_link}</p></div>

{other_html}

{finding_html}

<h2>How it works</h2>
<ol>
<li>You tell us your product and two competitors. We write the questions a buyer in your category would ask.</li>
<li>We ask each question several times, because assistants do not answer the same way twice, and store every answer.</li>
<li>A fixed counting rule decides who was named and who was cited. No model grades the answers.</li>
</ol>

<h2>Pricing</h2>
<div class="plans">
<div class="card">Sample<strong>Free</strong><span>8 questions, one assistant, your product against its category.</span></div>
<div class="card">Audit<strong>€49</strong><span>20 questions, a wider competitor list, and a list of the pages worth getting onto.</span></div>
<div class="card">Tracking<strong>€149/mo</strong><span>Monthly measurement plus one before/after experiment on a change you make.</span></div>
</div>

<h2>What we do not promise</h2>
<ul>
<li>We measure. Whether a given change gets you named more often is an open question in this field, so we test it: the success rule is written down before the change, and the report says so when nothing moved.</li>
<li>The numbers come from one assistant through its programming interface, which can differ from what a person sees in the app.</li>
<li>With a few dozen answers the margins are wide. Every report shows them.</li>
</ul>

<footer>{escape(brand)} · <a href="{mailto}" style="color:inherit">{escape(email)}</a></footer>
</main></body></html>
"""
