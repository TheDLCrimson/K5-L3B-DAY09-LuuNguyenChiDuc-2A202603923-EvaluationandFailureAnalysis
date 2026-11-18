"""M5 slice gate: extra cases beyond the instructor's public vector (tests/test_lab9_advanced.py)."""
import copy

import pytest

pytestmark = pytest.mark.student


def rows(fail=()):
    """8 items x 2 seeds; items 0-3 are money_movement, 4-7 denial. `fail` = (item index, seed) pairs that fail."""
    return [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": (i, s) not in fail,
             "slices": ["money_movement"] if i < 4 else ["denial"]} for i in range(8) for s in (1, 2)]


def report(r):
    mean = sum(x["pass_rate"] for x in r) / len(r)
    return {"manifest": {"eval_set_sha": "x", "items": 8, "seeds": [1, 2]}, "rows": r,
            "metrics": {"pass_rate": mean}, "evaluator_failures": []}


SPEC = {"eval_set_version": "v2", "metrics": [], "bootstrap": {"n_resamples": 200, "rng": 1},
        "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.9, "blocking": True},
                   {"name": "denial", "metric": "pass_rate", "min": 0.9, "blocking": False}]}


def test_clean_report_passes_every_slice():
    from lab9 import gate

    base = report(rows())
    assert gate.slice_check(base, base, SPEC)[0] == []


def test_overall_average_hides_a_slice_but_the_slice_gate_does_not():
    from lab9 import gate

    base = report(rows())
    pr = report(rows(fail={(0, 1), (1, 1), (2, 1), (3, 1)}))   # 4 of 16 trials fail, all in money_movement
    assert pr["metrics"]["pass_rate"] == 0.75           # overall still looks acceptable
    blocked, lines = gate.slice_check(pr, base, SPEC)
    assert blocked == ["slice:money_movement/pass_rate"]
    assert any("BLOCK" in line for line in lines)


def test_non_blocking_slice_warns_without_blocking():
    from lab9 import gate

    base = report(rows())
    pr = report(rows(fail={(4, 1), (5, 1), (6, 1), (7, 1)}))   # denial slice at 0.75 but blocking is False
    blocked, lines = gate.slice_check(pr, base, SPEC)
    assert blocked == []
    assert any("warn" in line for line in lines)


def test_significant_drop_blocks_even_above_the_floor():
    from lab9 import gate

    spec = copy.deepcopy(SPEC)
    spec["slices"] = [{"name": "money_movement", "metric": "pass_rate", "min": 0.5,
                       "no_significant_drop": True, "blocking": True}]
    base = report(rows())
    pr = report(rows(fail={(0, 1), (1, 1), (2, 1), (3, 1)}))   # 0.5 per item: at the floor, but a clear drop
    assert gate.slice_check(pr, base, spec)[0] == ["slice:money_movement/pass_rate"]


def test_emptied_slice_is_blocked_not_ignored():
    from lab9 import gate

    base = report(rows())
    emptied = [r for r in rows() if "money_movement" not in r["slices"]]
    blocked, lines = gate.slice_check(report(emptied), base, SPEC)
    assert blocked == ["slice:money_movement/pass_rate"]
    assert any("MISSING" in line for line in lines)
