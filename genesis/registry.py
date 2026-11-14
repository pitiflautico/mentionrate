"""Registro de experimentos: SQLite de solo-añadir.

Reglas que el propio esquema impone (no dependen de que el código se porte bien):

- Un experimento se sella (hipótesis, métrica, criterio y diseño) antes de que
  exista ninguna ejecución suya, y después no se puede modificar ni borrar.
- Las ejecuciones, los veredictos y el conocimiento tampoco se modifican ni se
  borran: una corrección es una fila nueva.
"""
from __future__ import annotations

import functools
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('experiment', 'measurement')),
    created_at  TEXT NOT NULL,
    hypothesis  TEXT NOT NULL,
    metric      TEXT NOT NULL,
    design      TEXT NOT NULL,
    seal        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    created_at    TEXT NOT NULL,
    arm           TEXT NOT NULL,
    engine        TEXT NOT NULL,
    model         TEXT NOT NULL,
    item_id       TEXT NOT NULL,
    item          TEXT NOT NULL,
    sample        INTEGER NOT NULL,
    answer        TEXT NOT NULL,
    citations     TEXT NOT NULL,
    cost_usd      REAL NOT NULL,
    seconds       REAL NOT NULL,
    error         TEXT,
    code_version  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdicts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    created_at    TEXT NOT NULL,
    verdict       TEXT NOT NULL CHECK (verdict IN ('SUCCESS', 'FAIL', 'INCONCLUSIVE')),
    numbers       TEXT NOT NULL,
    code_version  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    rule        TEXT NOT NULL,
    conditions  TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    supersedes  INTEGER REFERENCES knowledge(id)
);
"""

APPEND_ONLY = ("experiments", "runs", "verdicts", "knowledge")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@functools.lru_cache(maxsize=1)
def code_version() -> str:
    """Huella del código que mide: cambia si cambia cualquier fichero del paquete."""
    digest = hashlib.sha256()
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def seal_of(kind: str, hypothesis: str, metric: str, design: dict) -> str:
    canonical = json.dumps([kind, hypothesis, metric, design], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Registry:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        for table in APPEND_ONLY:
            for action in ("UPDATE", "DELETE"):
                self.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} es de solo-añadir'); END"
                )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # --- sellado -----------------------------------------------------------
    def preregister(self, kind: str, hypothesis: str, metric: str, design: dict) -> str:
        prefix = "EXP" if kind == "experiment" else "MED"
        count = self.db.execute("SELECT COUNT(*) FROM experiments WHERE kind = ?", (kind,)).fetchone()[0]
        exp_id = f"{prefix}-{count + 1:04d}"
        self.db.execute(
            "INSERT INTO experiments (id, kind, created_at, hypothesis, metric, design, seal) VALUES (?,?,?,?,?,?,?)",
            (
                exp_id,
                kind,
                _now(),
                hypothesis,
                metric,
                json.dumps(design, sort_keys=True, ensure_ascii=False),
                seal_of(kind, hypothesis, metric, design),
            ),
        )
        self.db.commit()
        return exp_id

    def experiment(self, exp_id: str) -> dict:
        row = self.db.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        if row is None:
            raise KeyError(f"no existe {exp_id}")
        out = dict(row)
        out["design"] = json.loads(out["design"])
        return out

    def seal_is_intact(self, exp_id: str) -> bool:
        e = self.experiment(exp_id)
        return e["seal"] == seal_of(e["kind"], e["hypothesis"], e["metric"], e["design"])

    def experiments(self) -> list[dict]:
        ids = [r[0] for r in self.db.execute("SELECT id FROM experiments ORDER BY created_at, id")]
        return [self.experiment(i) for i in ids]

    # --- ejecuciones -------------------------------------------------------
    def add_run(
        self,
        exp_id: str,
        *,
        arm: str,
        engine: str,
        model: str,
        item_id: str,
        item: str,
        sample: int,
        answer: str,
        citations: list[str],
        cost_usd: float = 0.0,
        seconds: float = 0.0,
        error: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO runs (experiment_id, created_at, arm, engine, model, item_id, item, sample, answer,"
            " citations, cost_usd, seconds, error, code_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                exp_id,
                _now(),
                arm,
                engine,
                model,
                item_id,
                item,
                sample,
                answer,
                json.dumps(citations, ensure_ascii=False),
                cost_usd,
                seconds,
                error,
                code_version(),
            ),
        )
        self.db.commit()

    def runs(self, exp_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM runs WHERE experiment_id = ? ORDER BY id", (exp_id,)).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["citations"] = json.loads(d["citations"])
            out.append(d)
        return out

    # --- veredictos y conocimiento ----------------------------------------
    def add_verdict(self, exp_id: str, verdict: str, numbers: dict) -> None:
        self.db.execute(
            "INSERT INTO verdicts (experiment_id, created_at, verdict, numbers, code_version) VALUES (?,?,?,?,?)",
            (exp_id, _now(), verdict, json.dumps(numbers, sort_keys=True, ensure_ascii=False), code_version()),
        )
        self.db.commit()

    def verdicts(self, exp_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM verdicts WHERE experiment_id = ? ORDER BY id", (exp_id,)).fetchall()
        return [{**dict(r), "numbers": json.loads(r["numbers"])} for r in rows]

    def add_knowledge(self, rule: str, conditions: str, evidence: list[str], supersedes: int | None = None) -> int:
        for exp_id in evidence:
            self.experiment(exp_id)  # no se admite conocimiento sin experimento que lo respalde
        cur = self.db.execute(
            "INSERT INTO knowledge (created_at, rule, conditions, evidence, supersedes) VALUES (?,?,?,?,?)",
            (_now(), rule, conditions, json.dumps(evidence), supersedes),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def knowledge(self) -> list[dict]:
        """Conocimiento vigente: se omite lo que una fila posterior ha sustituido."""
        rows = [dict(r) for r in self.db.execute("SELECT * FROM knowledge ORDER BY id")]
        replaced = {r["supersedes"] for r in rows if r["supersedes"] is not None}
        return [{**r, "evidence": json.loads(r["evidence"])} for r in rows if r["id"] not in replaced]

    # --- costes ------------------------------------------------------------
    def ledger(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT experiment_id, engine, model, COUNT(*) AS runs, SUM(error IS NOT NULL) AS errors,"
            " ROUND(SUM(cost_usd), 4) AS cost_usd, ROUND(SUM(seconds), 1) AS seconds"
            " FROM runs GROUP BY experiment_id, engine, model ORDER BY experiment_id"
        ).fetchall()
        return [dict(r) for r in rows]
