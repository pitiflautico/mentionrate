"""Páginas que cita el asistente: descarga con caché y presencia de una marca en ellas."""
from __future__ import annotations

import hashlib
import html
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from .detect import Brand, detect_normalized, host_of, owns

CACHE = Path(__file__).resolve().parent.parent / "registro" / "paginas"
TAG_RE = re.compile(r"(?is)<(script|style|noscript|svg)\b.*?</\1>")
MIN_TEXT = 500  # por debajo, la página no se pudo leer (bloqueo, error o contenido cargado por script)


def page_text(url: str) -> str:
    """Texto visible de una página, con caché en disco. Cadena vacía si no se pudo descargar."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".html")
    if not path.exists():
        got = subprocess.run(
            ["curl", "-sL", "-m", "25", "-A", "Mozilla/5.0 (compatible; research-bot)", "-o", str(path), url],
            capture_output=True,
        )
        if got.returncode != 0 or not path.exists():
            path.write_bytes(b"")
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", TAG_RE.sub(" ", raw))))


def most_cited(runs: list[dict], top: int) -> list[tuple[str, int]]:
    """Las ``top`` direcciones citadas en más respuestas; los empates, por dirección."""
    cited = Counter(url for r in runs for url in set(r["citations"]))
    return sorted(cited.items(), key=lambda kv: (-kv[1], kv[0]))[:top]


def cited_pages(runs: list[dict], brand: Brand, top: int, fetch: Callable[[str], str] = page_text) -> list[dict]:
    """Para un informe: cada página muy citada, cuántas respuestas la citan y si nombra a la marca."""
    rows = []
    for url, k in most_cited(runs, top):
        text = fetch(url)
        if len(text) < MIN_TEXT:
            continue
        rows.append({
            "url": url,
            "cited": k,
            "own": any(owns(d, host_of(url)) for d in brand.domains),
            "present": detect_normalized(brand, text, []).mentioned,
        })  # fmt: skip
    return rows
