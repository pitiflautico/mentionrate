"""Detección determinista de marcas en la respuesta de un asistente.

Dos estrategias con la misma firma, para poder compararlas en el banco de pruebas:

- ``naive``: la que se le ocurre a cualquiera (buscar el nombre como subcadena).
- ``normalized``: compara palabras completas sin tildes, respeta mayúsculas cuando
  la marca es una palabra común, y solo da por citado un dominio propio.

Ninguna usa un modelo de lenguaje: una medición no puede depender de una opinión.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit

URL_RE = re.compile(r"https?://[^\s)\]>\"'`]+")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class Brand:
    name: str
    aliases: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    case_sensitive: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Brand":
        return cls(
            name=d["name"],
            aliases=tuple(d.get("aliases", ())),
            domains=tuple(x.lower().removeprefix("www.") for x in d.get("domains", ())),
            case_sensitive=bool(d.get("case_sensitive", False)),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "domains": list(self.domains),
            "case_sensitive": self.case_sensitive,
        }


@dataclass(frozen=True)
class Detection:
    mentioned: bool
    cited: bool
    position: int | None = None  # índice del primer carácter de la mención en el texto
    evidence: tuple[str, ...] = field(default_factory=tuple)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def owns(domain: str, host: str) -> bool:
    """True si ``host`` es el dominio de la marca o uno de sus subdominios."""
    return host == domain or host.endswith("." + domain)


def _tokens(text: str) -> list[tuple[str, int]]:
    return [(m.group(), m.start()) for m in TOKEN_RE.finditer(strip_accents(text))]


def _find_sequence(haystack: list[tuple[str, int]], needle: list[str], exact_case: bool) -> int | None:
    if not needle:
        return None
    norm = (lambda s: s) if exact_case else str.lower
    target = [norm(t) for t in needle]
    words = [norm(t) for t, _ in haystack]
    for i in range(len(words) - len(target) + 1):
        if words[i : i + len(target)] == target:
            return haystack[i][1]
    return None


def detect_normalized(brand: Brand, text: str, citations: list[str]) -> Detection:
    body_urls = URL_RE.findall(text)
    prose = URL_RE.sub(lambda m: " " * len(m.group()), text)  # mismo largo: las posiciones no se mueven
    tokens = _tokens(prose)

    hits: list[tuple[int, str]] = []
    for alias in (brand.name, *brand.aliases):
        pos = _find_sequence(tokens, [t for t, _ in _tokens(alias)], brand.case_sensitive)
        if pos is not None:
            hits.append((pos, f"nombre:{alias}"))
    for domain in brand.domains:
        pos = _find_sequence(tokens, [t for t, _ in _tokens(domain)], exact_case=False)
        if pos is not None:
            hits.append((pos, f"dominio en texto:{domain}"))
    for m in URL_RE.finditer(text):
        if any(owns(d, host_of(m.group())) for d in brand.domains):
            hits.append((m.start(), f"enlace propio:{m.group()}"))

    cited_by = [u for u in (*body_urls, *citations) if any(owns(d, host_of(u)) for d in brand.domains)]
    hits.sort()
    return Detection(
        mentioned=bool(hits),
        cited=bool(cited_by),
        position=hits[0][0] if hits else None,
        evidence=tuple(h[1] for h in hits) + tuple(f"fuente:{u}" for u in cited_by),
    )


def detect_naive(brand: Brand, text: str, citations: list[str]) -> Detection:
    pos = text.lower().find(brand.name.lower())
    cited = any(d in u.lower() for u in citations for d in brand.domains)
    return Detection(mentioned=pos >= 0, cited=cited, position=pos if pos >= 0 else None)


STRATEGIES = {"naive": detect_naive, "normalized": detect_normalized}
