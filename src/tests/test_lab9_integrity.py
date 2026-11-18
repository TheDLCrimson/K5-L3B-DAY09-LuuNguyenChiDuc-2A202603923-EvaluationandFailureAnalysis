"""M7: one test per integrity rule and per ratchet rule (beyond the public vector in test_lab9_advanced.py)."""
import copy
import math

import pytest

pytestmark = pytest.mark.student

SEEDS = (1, 2)


def make_rows():
    return [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "refund_amount_correct": True,
             "cost": 1.0, "slices": ["denial"] if i < 2 else []} for i in range(4) for s in SEEDS]


def report(rows=None, **over):
    rows = copy.deepcopy(rows if rows is not None else make_rows())
    rep = {"manifest": {"eval_set_sha": "x", "labels_sha": "L1", "items": 4, "seeds": list(SEEDS)},
           "rows": rows, "evaluator_failures": [],
           "metrics": {"pass_rate": 1.0, "refund_amount_correct": 1.0, "pass_5": 1.0, "cost_per_success": 1.0}}
    rep.update(over)
    return rep


SPEC = {"eval_set_version": "v2", "bootstrap": {"confidence": 0.95},
        "metrics": [
            {"id": "pass_rate", "kind": "capability", "blocking": True,
             "threshold": {"min": 0.8, "no_significant_drop": True}},
            {"id": "refund_amount_correct", "kind": "capability", "blocking": True, "threshold": {"min": 0.9}},
            {"id": "cost_per_success", "kind": "system", "threshold": {"max_increase": 0.1}}],
        "slices": [{"name": "denial", "metric": "pass_rate", "min": 0.9, "no_significant_drop": True,
                    "blocking": True}]}


@pytest.fixture(scope="module")
def check():
    from lab9 import gate

    return gate.integrity_check


def test_a_clean_report_is_trusted(check):
    base = report()
    assert check(base, base, SPEC, SPEC) == []


def test_inf_in_a_metric_or_a_row(check):
    base = report()
    assert check(report(metrics={**base["metrics"], "pass_rate": math.inf}), base, SPEC)
    rows = make_rows()
    rows[0]["cost"] = float("nan")
    assert check(report(rows), base, SPEC)


def test_duplicate_rows_that_hide_a_dropped_row(check):
    base = report()
    rows = make_rows()
    rows[-1] = copy.deepcopy(rows[0])          # same row count, but one (item, seed) is now twice and one is gone
    problems = check(report(rows), base, SPEC)
    assert any("duplicate" in p for p in problems) and any("differs from the baseline" in p for p in problems)


def test_evaluator_failures_on_an_otherwise_green_run(check):
    base = report()
    assert any("evaluator failure" in p for p in check(report(evaluator_failures=["E-001@1:Grader:boom"]), base, SPEC))


def test_a_row_with_a_missing_grader_value(check):
    base = report()
    rows = make_rows()
    rows[3]["refund_amount_correct"] = None
    del rows[4]["pass_rate"]
    problems = check(report(rows), base, SPEC)
    assert any("refund_amount_correct" in p for p in problems) and any("pass_rate" in p for p in problems)


def test_metrics_edited_by_hand_do_not_match_the_rows(check):
    base = report()
    rows = make_rows()
    rows[0]["pass_rate"] = False               # the rows say 7 of 8 pass ...
    problems = check(report(rows), base, SPEC)   # ... but the stored metric still says 1.0
    assert any("pass_rate is 1.0 but its rows add up to" in p for p in problems)


def test_an_item_moved_out_of_a_slice(check):
    base = report()
    rows = make_rows()
    for r in rows:
        if r["item_id"] == "E-000":
            r["slices"] = []
    assert any("slice tags changed" in p for p in check(report(rows), base, SPEC))


def test_labels_changed_without_a_new_baseline(check):
    base = report()
    rep = report()
    rep["manifest"]["labels_sha"] = "L2"
    assert any("labels_sha" in p for p in check(rep, base, SPEC))


def test_manifest_seeds_or_items_changed(check):
    base = report()
    rep = report()
    rep["manifest"]["seeds"] = [1]
    assert check(rep, base, SPEC)


def test_all_failing_run_is_not_an_integrity_problem(check):
    """cost_per_success is None when nothing succeeds; that is a regression for the gate, not a doctored report."""
    base = report()
    rows = make_rows()
    for r in rows:
        r["pass_rate"] = r["refund_amount_correct"] = False
    rep = report(rows)
    rep["metrics"].update(pass_rate=0.0, refund_amount_correct=0.0, pass_5=0.0, cost_per_success=None)
    assert check(rep, base, SPEC) == []


@pytest.mark.parametrize("edit,needle", [
    (lambda s: s["metrics"][0]["threshold"].update(min=0.5), "min lowered"),
    (lambda s: s["metrics"][0]["threshold"].pop("no_significant_drop"), "no_significant_drop dropped"),
    (lambda s: s["metrics"][0].update(blocking=False), "no longer blocking"),
    (lambda s: s["metrics"][0].update(kind="system"), "kind changed"),
    (lambda s: s["metrics"].pop(1), "removed"),
    (lambda s: s["metrics"][2]["threshold"].update(max_increase=0.5), "max_increase raised"),
    (lambda s: s["metrics"][1]["threshold"].pop("min"), "removed"),
    (lambda s: s["slices"][0].update(min=0.5), "min lowered"),
    (lambda s: s["slices"][0].update(blocking=False), "no longer blocking"),
    (lambda s: s["slices"][0].pop("no_significant_drop"), "no_significant_drop dropped"),
    (lambda s: s["slices"].clear(), "slice denial: removed"),
    (lambda s: s["bootstrap"].update(confidence=0.99), "confidence raised"),
])
def test_ratchet_rejects_every_loosening(check, edit, needle):
    base = report()
    loose = copy.deepcopy(SPEC)
    edit(loose)
    assert any(needle in p for p in check(base, base, loose, SPEC)), needle


def test_ratchet_allows_tightening_and_new_metrics(check):
    base = report()
    tight = copy.deepcopy(SPEC)
    tight["metrics"][0]["threshold"]["min"] = 0.95
    tight["metrics"].append({"id": "new_metric", "kind": "capability", "blocking": True, "threshold": {"min": 0.9}})
    tight["slices"][0]["min"] = 0.95
    assert check(base, base, tight, SPEC) == []


def test_ratchet_is_skipped_for_a_new_eval_set_version(check):
    base = report()
    new_version = copy.deepcopy(SPEC)
    new_version["eval_set_version"] = "v3"
    new_version["metrics"][0]["threshold"]["min"] = 0.1
    assert check(base, base, new_version, SPEC) == []
