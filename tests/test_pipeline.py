import json
import stat
from pathlib import Path

import pytest

from genesis.__main__ import main
from genesis.audit import (
    collect,
    finish_before_after,
    highlighted_names,
    load_profile,
    ranked,
    run_measurement,
    start_before_after,
    summarize,
)
from genesis.engines import Answer, ClaudeCliEngine, FakeEngine, split_sources
from genesis.evaluator import evaluate, run_detector_bench
from genesis.registry import Registry
from genesis.report import render
from genesis.site import render_landing

ROOT = Path(__file__).resolve().parent.parent

PROFILE = {
    "id": "prueba",
    "language": "es",
    "brand": {"name": "Acme", "aliases": [], "domains": ["acme.test"]},
    "competitors": [{"name": "Rival", "aliases": [], "domains": ["rival.test"]}],
    "prompts": [{"id": f"q{i}", "text": f"pregunta {i}"} for i in range(10)],
}


@pytest.fixture
def reg():
    r = Registry(":memory:")
    yield r
    r.close()


# --- banco de detectores ---------------------------------------------------
def test_detector_bench_experiment_end_to_end(reg):
    exp = run_detector_bench(reg, ROOT / "data/detector_bench.jsonl", ROOT / "data/detector_brands.json")
    verdict, numbers = evaluate(reg, exp)
    arms = numbers["arms"]
    assert verdict == "SUCCESS"
    assert arms["normalized"]["wrong_cases"] == ["p04"]
    assert arms["normalized"]["f1"] > arms["naive"]["f1"]
    assert reg.verdicts(exp)[0]["verdict"] == "SUCCESS"
    assert len(reg.runs(exp)) == 2 * arms["normalized"]["cases"]


# --- experimento de dos brazos con motor falso ------------------------------
def two_arm(reg, p_control, p_treatment, samples, min_answers=20):
    exp = reg.preregister(
        "experiment",
        "El tratamiento aumenta la frecuencia de mención.",
        "mention_rate_diff",
        {
            "brand": PROFILE["brand"], "detector": "normalized", "control": "antes", "treatment": "despues",
            "min_effect": 0.0, "min_answers_per_arm": min_answers,
        },  # fmt: skip
    )
    collect(reg, exp, "antes", FakeEngine({"Acme": p_control}, seed=1), PROFILE["prompts"], samples)
    collect(reg, exp, "despues", FakeEngine({"Acme": p_treatment}, seed=2), PROFILE["prompts"], samples)
    return evaluate(reg, exp)


def test_real_effect_is_detected(reg):
    verdict, numbers = two_arm(reg, 0.15, 0.75, samples=4)
    assert verdict == "SUCCESS" and numbers["low"] > 0


def test_no_effect_is_not_a_success(reg):
    verdict, numbers = two_arm(reg, 0.4, 0.4, samples=4)
    assert verdict == "INCONCLUSIVE" and numbers["low"] < 0 < numbers["high"]


def test_harmful_treatment_fails(reg):
    verdict, _ = two_arm(reg, 0.8, 0.1, samples=4)
    assert verdict == "FAIL"


def test_too_few_answers_is_inconclusive(reg):
    verdict, _ = two_arm(reg, 0.0, 1.0, samples=1, min_answers=20)
    assert verdict == "INCONCLUSIVE"


def test_fake_engine_is_reproducible():
    a, b = FakeEngine({"Acme": 0.5}, seed=7), FakeEngine({"Acme": 0.5}, seed=7)
    assert [a.ask("p", s).text for s in range(20)] == [b.ask("p", s).text for s in range(20)]


# --- medición e informe ----------------------------------------------------
class ScriptedEngine:
    name, model = "guion", "v1"

    def ask(self, prompt, sample):
        if prompt == "pregunta 0":
            return Answer(text="", error="caída", cost_usd=0.01)
        if prompt in ("pregunta 1", "pregunta 2"):
            return Answer(text="Primero Rival y después Acme.", citations=["https://www.acme.test/a", "https://dir.test/x"], cost_usd=0.02)
        return Answer(text="Te recomiendo Rival.", citations=["https://dir.test/y"], cost_usd=0.02)


def test_measurement_summary_counts(reg):
    exp = run_measurement(reg, PROFILE, ScriptedEngine(), samples=2)
    s = summarize(reg, exp)
    assert (s["answers"], s["errors"]) == (18, 2)
    assert (s["target"]["mentions"], s["target"]["cited"], s["prompts_covered"]) == (4, 4, 2)
    rival = next(b for b in s["brands"] if b["name"] == "Rival")
    assert rival["mentions"] == 18 and rival["mean_rank"] == 1.0
    assert s["target"]["mean_rank"] == 2.0
    assert dict(s["sources"]) == {"dir.test": 18, "acme.test": 4}
    assert s["cost_usd"] == pytest.approx(0.38)
    with pytest.raises(ValueError, match="descriptiva"):
        evaluate(reg, exp)


def test_report_renders_numbers_and_escapes(reg):
    profile = {**PROFILE, "brand": {"name": "A<b>cme", "aliases": ["Acme"], "domains": ["acme.test"]}}
    s = summarize(reg, run_measurement(reg, profile, ScriptedEngine(), samples=1))
    html = render(s)
    assert "A&lt;b&gt;cme" in html and "A<b>cme" not in html
    assert "2 de 9 respuestas" in html
    assert "class='own'>acme.test" in html


def test_profile_validation(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps({**PROFILE, "prompts": [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]}))
    with pytest.raises(ValueError, match="repite"):
        load_profile(bad)
    bad.write_text(json.dumps({"id": "x"}))
    with pytest.raises(ValueError, match="falta"):
        load_profile(bad)


def test_split_sources():
    body, urls = split_sources("Usa Acme (https://acme.test/a).\n\nSources:\n- https://dir.test/x.\n- https://acme.test/a")
    assert body == "Usa Acme (https://acme.test/a)."
    assert urls == ["https://acme.test/a", "https://dir.test/x"]
    assert split_sources("Sin fuentes") == ("Sin fuentes", [])


# --- conector real, con un binario de mentira -------------------------------
def fake_binary(tmp_path, stdout):
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{stdout}\nEOF\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_cli_engine_parses_success(tmp_path):
    payload = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.05,
               "result": "Prueba Acme.\n\nSources:\n- https://acme.test/"}  # fmt: skip
    answer = ClaudeCliEngine(binary=fake_binary(tmp_path, json.dumps(payload))).ask("p", 0)
    assert (answer.text, answer.citations, answer.cost_usd, answer.error) == ("Prueba Acme.", ["https://acme.test/"], 0.05, None)


def test_cli_engine_reports_errors(tmp_path):
    failed = {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "límite", "total_cost_usd": 0.01}
    answer = ClaudeCliEngine(binary=fake_binary(tmp_path, json.dumps(failed))).ask("p", 0)
    assert answer.text == "" and answer.error == "límite" and answer.cost_usd == 0.01
    garbage = ClaudeCliEngine(binary=fake_binary(tmp_path, "no soy json")).ask("p", 0)
    assert garbage.error.startswith("JSONDecodeError")
    missing = ClaudeCliEngine(binary=str(tmp_path / "no-existe")).ask("p", 0)
    assert missing.error.startswith("FileNotFoundError")


def test_cli_engine_isolates_the_call():
    cmd = ClaudeCliEngine(model="sonnet").command("hola")
    assert cmd[:3] == ["claude", "-p", "hola"]
    for flag in ("--strict-mcp-config", "--no-session-persistence"):
        assert flag in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--tools") + 1] == "WebSearch"


# --- línea de órdenes ------------------------------------------------------
def test_cli_bench_ledger_and_report(tmp_path, capsys):
    db = str(tmp_path / "g.db")
    assert main(["--db", db, "bench"]) == 0
    assert main(["--db", db, "learn", "regla", "--conditions", "cond", "--evidence", "EXP-0001"]) == 0
    assert main(["--db", db, "ledger"]) == 0
    out = capsys.readouterr().out
    assert "EXP-0001: SUCCESS" in out and "sabido #1 [EXP-0001]: regla" in out
    assert main(["--db", db, "report", "MED-0001"]) == 2
    assert "no existe MED-0001" in capsys.readouterr().err


# --- nombres destacados que no están en la lista ----------------------------
def test_highlighted_names_extracts_bold_and_links():
    text = "- **[Pointa](https://www.pointa.dev/)** va bien.\n- **Vibe Annotations**: gratis.\n**¿Cuál elegir?**\n**Esto es una frase demasiado larga para ser un nombre de producto**"
    assert highlighted_names(text) == {"Pointa", "Vibe Annotations"}


class OthersEngine:
    name, model = "guion", "v1"

    def ask(self, prompt, sample):
        return Answer(text="Mira **Otro Producto**, **Rival** y **[Acme](https://acme.test)**. **Solo Una Vez** no." if prompt == "pregunta 1" else "Mira **Otro Producto**.")


def test_summary_lists_untracked_names_seen_twice(reg):
    s = summarize(reg, run_measurement(reg, PROFILE, OthersEngine(), samples=1))
    assert s["others"] == [("Otro Producto", 10)]
    assert "Otro Producto" in render(s)


# --- experimento antes/después sellado --------------------------------------
def test_before_after_seals_then_closes_once(reg):
    before = FakeEngine({"Acme": 0.1}, seed=3)
    exp = start_before_after(reg, PROFILE, before, samples=4, treatment="publicar la ficha")
    design = reg.experiment(exp)["design"]
    assert design["min_answers_per_arm"] == 36 and {r["arm"] for r in reg.runs(exp)} == {"antes"}
    with pytest.raises(ValueError, match="otro motor"):
        finish_before_after(reg, exp, FakeEngine({"Acme": 0.9}, model="otro"))
    verdict, numbers = finish_before_after(reg, exp, FakeEngine({"Acme": 0.9}, seed=4))
    assert verdict == "SUCCESS" and numbers["treatment"]["answers"] == 40
    with pytest.raises(ValueError, match="ya tiene medido"):
        finish_before_after(reg, exp, FakeEngine({"Acme": 0.9}, seed=5))


def test_cli_exp_start_and_close(tmp_path, capsys, monkeypatch):
    profile = tmp_path / "p.json"
    profile.write_text(json.dumps(PROFILE))
    engines = iter([FakeEngine({"Acme": 0.1}, seed=1), FakeEngine({"Acme": 0.1}, seed=2)])
    monkeypatch.setattr("genesis.__main__.build_engine", lambda name, model: next(engines))
    db = str(tmp_path / "g.db")
    assert main(["--db", db, "exp-start", str(profile), "--treatment", "nada", "--samples", "3"]) == 0
    assert main(["--db", db, "exp-close", "EXP-0001"]) == 0
    out = capsys.readouterr().out
    assert "EXP-0001 sellado" in out and "EXP-0001: INCONCLUSIVE" in out


# --- una medición de categoría sirve para cualquiera de sus marcas ----------
def test_report_can_target_any_brand_of_the_measurement(reg, tmp_path, capsys):
    exp = run_measurement(reg, PROFILE, ScriptedEngine(), samples=2)
    s = summarize(reg, exp, "rival")
    assert s["target"]["name"] == "Rival" and s["target"]["mentions"] == 18 and s["prompts_covered"] == 9
    assert s["own_domains"] == ["rival.test"]
    with pytest.raises(ValueError, match="no está entre las marcas"):
        summarize(reg, exp, "Desconocida")
    two_arm_id = reg.preregister("experiment", "h", "mention_rate_diff", {})
    with pytest.raises(ValueError, match="no es una medición"):
        summarize(reg, two_arm_id)


def test_cli_prospects_writes_reports_and_csv(tmp_path, capsys, monkeypatch):
    profile = tmp_path / "p.json"
    profile.write_text(json.dumps({**PROFILE, "competitors": PROFILE["competitors"] + [{"name": "SinWeb", "aliases": [], "domains": []}]}))
    monkeypatch.setattr("genesis.__main__.build_engine", lambda name, model: ScriptedEngine())
    db, out = str(tmp_path / "g.db"), tmp_path / "out"
    assert main(["--db", db, "audit", str(profile), "--samples", "2"]) == 0
    assert main(["--db", db, "prospects", "MED-0001", "--max-rate", "0.5", "-o", str(out)]) == 0
    lines = (out / "prospectos.csv").read_text().splitlines()
    assert lines[1] == "Acme,acme.test,4,18,0.222,0.090,0.452,2,10,acme.html"
    assert len(lines) == 2  # Rival sale siempre y SinWeb no tiene dominio: ninguno es prospecto
    assert "4 de 18 respuestas" in (out / "acme.html").read_text()


def test_landing_uses_measured_numbers(reg):
    s = summarize(reg, run_measurement(reg, PROFILE, ScriptedEngine(), samples=2))
    html = render_landing(s, "Marca <x>", "hola@ejemplo.test")
    assert "Marca &lt;x&gt;" in html and "mailto:hola@ejemplo.test" in html
    assert "Share of 18 answers" in html and "width:100%" in html and "22%" in html
    by_url = render_landing(s, "M", "https://example.test/new")
    assert 'href="https://example.test/new"' in by_url and "mailto:" not in by_url
    assert "A real example: prueba</h2>" in by_url and "See every question" not in by_url
    assert "appears in the wording of a question" not in by_url
    asked = {**s, "prompts": [{**s["prompts"][0], "text": "An alternative to Acme?"}]}
    assert "Acme appears in the wording of a question" in render_landing(asked, "M", "https://example.test/new")
    full = render_landing(s, "M", "https://example.test/new", category="widgets", more="report.html")
    assert "A real example: widgets</h2>" in full and "href='report.html'" in full
    assert "Of the 2 products tracked, 1 were named in fewer than a quarter of the answers, 0 of them never." in html


def test_report_in_english_when_the_profile_says_so(reg):
    s = summarize(reg, run_measurement(reg, {**PROFILE, "language": "en"}, ScriptedEngine(), samples=1))
    html = render(s)
    assert '<html lang="en">' in html and "Do AI assistants recommend Acme?" in html
    assert "2 of 9 answers" in html and "22%" in html and " de 9" not in html
    assert "noindex" not in html and 'content="noindex"' in render(s, noindex=True)


def test_ties_are_ordered_by_name_so_reports_are_reproducible():
    from collections import Counter

    assert ranked(Counter({"b.test": 2, "c.test": 5, "a.test": 2})) == [("c.test", 5), ("a.test", 2), ("b.test", 2)]
