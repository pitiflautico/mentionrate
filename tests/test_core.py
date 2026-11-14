import json
import sqlite3
from pathlib import Path

import pytest

from genesis.detect import STRATEGIES, Brand, detect_naive, detect_normalized
from genesis.registry import Registry
from genesis.stats import f1, rate_diff, wilson

ROOT = Path(__file__).resolve().parent.parent
BRANDS = {k: Brand.from_dict(v) for k, v in json.loads((ROOT / "data/detector_brands.json").read_text()).items()}
CASES = [json.loads(line) for line in (ROOT / "data/detector_bench.jsonl").read_text().splitlines() if line.strip()]


# --- estadística -----------------------------------------------------------
def test_wilson_matches_known_values():
    low, high = wilson(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4)
    assert high == pytest.approx(0.7634, abs=1e-4)
    assert wilson(0, 10)[0] == pytest.approx(0.0, abs=1e-12)
    assert wilson(10, 10)[1] == pytest.approx(1.0, abs=1e-12)
    assert wilson(0, 0) == (0.0, 1.0)


def test_rate_diff_sign_and_bounds():
    diff, low, high = rate_diff(2, 40, 28, 40)
    assert diff == pytest.approx(0.65)
    assert 0 < low < diff < high <= 1
    same = rate_diff(10, 40, 10, 40)
    assert same[0] == 0 and same[1] < 0 < same[2]
    assert rate_diff(1, 0, 1, 5) == (0.0, -1.0, 1.0)


def test_f1_handles_empty():
    assert f1(0, 0, 0) == (0.0, 0.0, 0.0)
    assert f1(8, 2, 2) == pytest.approx((0.8, 0.8, 0.8))


# --- detector --------------------------------------------------------------
def test_bench_is_well_formed():
    assert len({c["id"] for c in CASES}) == len(CASES) >= 30
    assert all(c["brand"] in BRANDS for c in CASES)
    assert any(c["mentioned"] for c in CASES) and any(not c["mentioned"] for c in CASES)


@pytest.mark.parametrize("case", [c for c in CASES if c["id"] != "p04"], ids=lambda c: c["id"])
def test_normalized_detector_on_bench(case):
    found = detect_normalized(BRANDS[case["brand"]], case["answer"], case["citations"])
    assert (found.mentioned, found.cited) == (case["mentioned"], case["cited"]), case["note"]


def test_known_limit_is_still_a_limit():
    """p04 documenta lo que ninguna regla distingue; si un día pasa, hay que revisar el banco."""
    case = next(c for c in CASES if c["id"] == "p04")
    assert detect_normalized(BRANDS["pastel"], case["answer"], case["citations"]).mentioned is True


def test_naive_detector_is_worse_where_expected():
    loom, bugherd = BRANDS["loom"], BRANDS["bugherd"]
    assert detect_naive(loom, "Problems bloom here", []).mentioned is True
    assert detect_normalized(loom, "Problems bloom here", []).mentioned is False
    assert detect_naive(bugherd, "", ["https://notbugherd.com/"]).cited is True
    assert detect_normalized(bugherd, "", ["https://notbugherd.com/"]).cited is False


def test_position_orders_brands_and_survives_urls():
    text = "See https://example.com/x then BugHerd, later Boolu."
    a = detect_normalized(BRANDS["bugherd"], text, [])
    b = detect_normalized(BRANDS["boolu"], text, [])
    assert text[a.position :].startswith("BugHerd") and text[b.position :].startswith("Boolu")
    assert a.position < b.position


def test_strategies_share_signature():
    for fn in STRATEGIES.values():
        d = fn(BRANDS["boolu"], "Boolu", [])
        assert d.mentioned is True and d.cited is False


# --- registro --------------------------------------------------------------
@pytest.fixture
def reg():
    r = Registry(":memory:")
    yield r
    r.close()


def test_registry_is_append_only(reg):
    exp = reg.preregister("experiment", "h", "detector_f1", {"a": 1})
    reg.add_run(exp, arm="x", engine="e", model="m", item_id="i", item="t", sample=0, answer="r", citations=[])
    reg.add_verdict(exp, "FAIL", {"n": 1})
    for sql in (
        "UPDATE experiments SET hypothesis = 'otra'",
        "DELETE FROM experiments",
        "UPDATE runs SET answer = 'x'",
        "DELETE FROM runs",
        "UPDATE verdicts SET verdict = 'SUCCESS'",
        "DELETE FROM verdicts",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="solo-añadir"):
            reg.db.execute(sql)
    assert reg.seal_is_intact(exp)
    assert reg.runs(exp)[0]["answer"] == "r"


def test_runs_need_a_sealed_experiment(reg):
    with pytest.raises(sqlite3.IntegrityError):
        reg.add_run("EXP-9999", arm="x", engine="e", model="m", item_id="i", item="t", sample=0, answer="", citations=[])


def test_ids_are_sequential_per_kind(reg):
    assert reg.preregister("experiment", "h", "m", {}) == "EXP-0001"
    assert reg.preregister("measurement", "h", "m", {}) == "MED-0001"
    assert reg.preregister("experiment", "h", "m", {}) == "EXP-0002"
    with pytest.raises(sqlite3.IntegrityError):
        reg.preregister("otra-cosa", "h", "m", {})


def test_knowledge_needs_evidence_and_can_be_superseded(reg):
    with pytest.raises(KeyError):
        reg.add_knowledge("regla", "cond", ["EXP-0001"])
    exp = reg.preregister("experiment", "h", "m", {})
    first = reg.add_knowledge("regla vieja", "cond", [exp])
    second = reg.add_knowledge("regla nueva", "cond", [exp], supersedes=first)
    assert [k["id"] for k in reg.knowledge()] == [second]


def test_registry_persists_on_disk(tmp_path):
    path = tmp_path / "sub" / "g.db"
    r = Registry(path)
    exp = r.preregister("measurement", "h", "mention_rate", {"k": "ñ"})
    r.close()
    again = Registry(path)
    assert again.experiment(exp)["design"] == {"k": "ñ"}
    again.close()


def test_spearman_of_the_presence_model():
    from modelo import ranks, spearman

    assert ranks([10, 30, 20, 20]) == [1, 4, 2.5, 2.5]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0
