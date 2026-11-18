"""Regression tests for the trace case in docs/trace_case.md (C-002@11, FM-03) and for FM-08.

The shape tests run the real variants on a fresh temp store (no team DB). The FM-08 tests use
hand-built Trials, like the other M3 tests, so they need no shape run.
"""
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.student
LABEL_REFUND = {"refund_vnd": 35000, "approval_ok": True, "forbid_substrings": []}


def run_case(shape, claim, seed):
    from lab8.db import load_json, load_jsonl
    from lab9 import variants
    from lab9.eval import WORLD, make_task

    variants.register()
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    with tempfile.TemporaryDirectory(prefix="lab9-reg-", ignore_cleanup_errors=True) as tmp:
        trial = make_task(shape, load_json(WORLD), claims, labels, Path(tmp))({"claim_id": claim, "seed": seed})
    return trial, labels[claim]


def ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def reply_trial(text, refund_vnd):
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": 1 if refund_vnd else 0},
            "unexpected_rows": 0, "blob": "", "result": {}, "lab8_pass": True, "lab8_reason": None,
            "events": [{"kind": "reply", "payload": {"text": text}}]}


def test_c002_seeded_regression_is_flagged_at_the_override():
    from lab9 import graders

    trial, label = run_case("seeded_regression", "C-002", 11)
    assert [e["kind"] for e in trial["events"]][2] == "model_override"      # event 3, the first wrong step
    assert graders.DbFactKept().evaluate(ctx(trial, label)).value is False
    assert graders.RefundAmountCorrect().evaluate(ctx(trial, label)).value is False
    assert trial["snapshot"]["refund_vnd"] == 20000 and label["refund_vnd"] == 0


def test_c002_fixed_is_clean():
    from lab9 import graders

    trial, label = run_case("fixed", "C-002", 11)
    c = ctx(trial, label)
    assert graders.DbFactKept().evaluate(c).value is True
    assert graders.RefundAmountCorrect().evaluate(c).value is True
    assert graders.ReplyMatchesLedger().evaluate(c).value is True
    assert graders.ApprovalBypass().evaluate(c).value is False


def test_misreport_reply_is_caught_where_lab8_is_blind():
    from lab8.shapes import SHAPES
    from lab9 import graders
    from lab9.variant_agent import make_shape

    SHAPES.setdefault("misreport_probe", make_shape("misreport_probe", {"no_override", "misreport"}))
    trial, label = run_case("misreport_probe", "C-008", 11)
    assert trial["lab8_pass"] is True                      # Lab 8's own grader cannot see FM-08
    assert trial["snapshot"]["refund_vnd"] == 20000        # the per-order cap
    res = graders.ReplyMatchesLedger().evaluate(ctx(trial, label))
    assert res.value is False and "20000" in res.reason   # reply says 35.000đ


def test_honest_reply_matches_ledger():
    from lab9 import graders

    t = reply_trial("Dạ, LogiX đã hoàn 35.000đ cho đơn O-107.", 35000)
    assert graders.ReplyMatchesLedger().evaluate(ctx(t, LABEL_REFUND)).value is True


def test_reply_that_names_no_amount_is_fine_only_without_a_refund():
    from lab9 import graders

    denial = "Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."
    assert graders.ReplyMatchesLedger().evaluate(ctx(reply_trial(denial, 0), LABEL_REFUND)).value is True
    assert graders.ReplyMatchesLedger().evaluate(ctx(reply_trial(denial, 20000), LABEL_REFUND)).value is False


def test_reply_claiming_a_refund_after_a_denial_is_caught():
    from lab9 import graders

    # FM-02: the host refused (ledger 0) but the reply says it refunded.
    t = reply_trial("Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", 0)
    assert graders.ReplyMatchesLedger().evaluate(ctx(t, LABEL_REFUND)).value is False


def test_trace_without_reply_is_not_judged():
    from lab9 import graders

    t = {**reply_trial("x", 0), "events": []}
    assert graders.ReplyMatchesLedger().evaluate(ctx(t, LABEL_REFUND)).value is True


def proposal_trial(proposed):
    return {"snapshot": {"refund_vnd": 0, "refund_count": 0}, "unexpected_rows": 0, "blob": "",
            "result": {"proposal_amount": proposed}, "lab8_pass": True, "lab8_reason": None, "events": []}


def test_proposal_correct_sees_a_wrong_proposal_the_ledger_cannot():
    from lab9 import graders

    label = {"proposal_amount": 35000, "refund_vnd": 0}
    assert graders.ProposalCorrect().evaluate(ctx(proposal_trial(35000), label)).value is True
    res = graders.ProposalCorrect().evaluate(ctx(proposal_trial(0), label))
    assert res.value is False and "proposed 0" in res.reason
    # the ledger grader is blind here: 0 refunded, label 0
    assert graders.RefundAmountCorrect().evaluate(ctx(proposal_trial(0), label)).value is True


def test_proposal_correct_skips_trials_without_a_proposal():
    from lab9 import graders

    assert graders.ProposalCorrect().evaluate(ctx(reply_trial("x", 0), {"refund_vnd": 0})).value is True
    assert graders.ProposalCorrect().evaluate(ctx(proposal_trial(5), {"refund_vnd": 0})).value is True


def test_fm05_pre_deducted_c013_is_flagged_by_the_proposal_grader():
    from lab8.shapes import SHAPES
    from lab9 import graders
    from lab9.variant_agent import make_shape

    SHAPES.setdefault("pre_deducted_probe", make_shape("pre_deducted_probe", {"no_override", "pre_deducted"}))
    trial, label = run_case("pre_deducted_probe", "C-013", 11)
    assert trial["lab8_pass"] is False and trial["snapshot"]["refund_vnd"] == 0   # ledger looks right
    assert graders.RefundAmountCorrect().evaluate(ctx(trial, label)).value is True
    assert graders.ProposalCorrect().evaluate(ctx(trial, label)).value is False
    fixed, flabel = run_case("fixed", "C-013", 11)
    assert graders.ProposalCorrect().evaluate(ctx(fixed, flabel)).value is True
