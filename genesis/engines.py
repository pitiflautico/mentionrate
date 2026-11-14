"""Motores: a quién se le hace la pregunta.

``FakeEngine`` es determinista y sirve para probar todo el circuito sin gastar.
``ClaudeCliEngine`` pregunta de verdad a Claude con búsqueda web a través del
programa ``claude`` instalado, aislado de la configuración personal del equipo.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Protocol

from .detect import URL_RE

SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question in the language it is asked in. "
    "Use web search when it helps. End with a 'Sources:' list of the URLs you relied on, one per line."
)


@dataclass
class Answer:
    text: str
    citations: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: str | None = None


class Engine(Protocol):
    name: str
    model: str

    def ask(self, prompt: str, sample: int) -> Answer: ...


def split_sources(text: str) -> tuple[str, list[str]]:
    """Separa el cuerpo de la respuesta de su lista final de fuentes.

    Los enlaces del bloque final son citas, no menciones; los del cuerpo se quedan
    en el cuerpo y también cuentan como citas.
    """
    lowered = text.lower()
    cut = -1
    for marker in ("\nsources:", "\n**sources:**", "\n**sources**", "\nfuentes:", "\n**fuentes:**", "\n## sources", "\n## fuentes"):
        cut = max(cut, lowered.rfind(marker))
    body, tail = (text[:cut], text[cut:]) if cut >= 0 else (text, "")
    urls = [u.rstrip(".,;") for u in URL_RE.findall(body) + URL_RE.findall(tail)]
    return body.strip(), list(dict.fromkeys(urls))


class FakeEngine:
    """Responde nombrando marcas con una probabilidad fija por marca.

    El resultado depende solo de (semilla, pregunta, muestra): repetir da lo mismo.
    """

    name = "fake"

    def __init__(self, mention_probability: dict[str, float], seed: int = 0, model: str = "fake-1"):
        self.mention_probability = mention_probability
        self.seed = seed
        self.model = model

    def ask(self, prompt: str, sample: int) -> Answer:
        named = []
        for brand, p in sorted(self.mention_probability.items()):
            digest = hashlib.sha256(f"{self.seed}|{prompt}|{sample}|{brand}".encode()).digest()
            if int.from_bytes(digest[:8], "big") / 2**64 < p:
                named.append(brand)
        text = "Opciones recomendadas: " + ", ".join(named) + "." if named else "No tengo una recomendación clara."
        return Answer(text=text)


class ClaudeCliEngine:
    name = "claude-cli"

    def __init__(self, model: str = "sonnet", timeout: int = 240, binary: str = "claude"):
        self.model = model
        self.timeout = timeout
        self.binary = binary

    def command(self, prompt: str) -> list[str]:
        return [
            self.binary, "-p", prompt,
            "--output-format", "json",
            "--model", self.model,
            "--tools", "WebSearch",
            "--allowedTools", "WebSearch",
            "--system-prompt", SYSTEM_PROMPT,
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
        ]  # fmt: skip

    def ask(self, prompt: str, sample: int) -> Answer:
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as empty:  # sin CLAUDE.md ni proyecto alrededor
                proc = subprocess.run(
                    self.command(prompt), cwd=empty, capture_output=True, text=True,
                    timeout=self.timeout, stdin=subprocess.DEVNULL,
                )  # fmt: skip
            elapsed = time.monotonic() - started
            payload = json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            return Answer(text="", seconds=time.monotonic() - started, error=f"sin respuesta en {self.timeout}s")
        except (json.JSONDecodeError, OSError) as exc:
            return Answer(text="", seconds=time.monotonic() - started, error=f"{type(exc).__name__}: {exc}")
        cost = float(payload.get("total_cost_usd") or 0.0)
        if payload.get("is_error") or payload.get("subtype") != "success":
            reason = str(payload.get("result") or payload.get("subtype") or "error")[:300]
            return Answer(text="", cost_usd=cost, seconds=elapsed, error=reason)
        body, urls = split_sources(str(payload.get("result") or ""))
        return Answer(text=body, citations=urls, cost_usd=cost, seconds=elapsed)


def build_engine(name: str, model: str | None = None) -> Engine:
    if name == "claude-cli":
        return ClaudeCliEngine(model=model or "sonnet")
    raise ValueError(f"motor desconocido: {name}")
