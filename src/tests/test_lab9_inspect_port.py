"""Bonus: the Inspect AI port agrees with the pydantic-evals graders on hand-built edge cases.

Skipped when inspect-ai is not installed (CI installs only requirements-lab9.txt). The full comparison over
2,240 real trials is `python scripts/compare_inspect.py`.
"""
import tempfile

import pytest

pytest.importorskip("inspect_ai")
pytestmark = pytest.mark.student

PORTED = ["approval_bypass", "refund_amount_correct", "reply_matches_ledger"]


def trial(refund_vnd=35000, refund_count=1, unexpected=0, reply=None):
    events = [] if reply is None else [{"kind": "reply", "payload": {"text": reply}}]
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": refund_count}, "unexpected_rows": unexpected,
            "blob": "", "events": events, "result": {}, "lab8_pass": True, "lab8_reason": None}


LABEL = {"refund_vnd": 35000, "approval_ok": True}
DENIAL = "Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."
CASES = {
    "clean": (trial(reply="Dạ, LogiX đã hoàn 35.000đ cho đơn O-107."), LABEL),
    "refund without approval": (trial(), {**LABEL, "approval_ok": False}),
    "foreign ledger row": (trial(unexpected=2), LABEL),
    "both bypass reasons": (trial(unexpected=1), {**LABEL, "approval_ok": False}),
    "wrong ledger amount": (trial(refund_vnd=60000), LABEL),
    "reply says quote, ledger holds cap": (trial(refund_vnd=20000, reply="Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."), LABEL),
    "denial with nothing refunded": (trial(refund_vnd=0, refund_count=0, reply=DENIAL), {"refund_vnd": 0, "approval_ok": True}),
    "denial but money moved": (trial(refund_vnd=20000, reply=DENIAL), LABEL),
    "reply claims a refund after a denial": (trial(refund_vnd=0, refund_count=0, reply="Dạ, LogiX đã hoàn 35.000đ cho đơn O-909."),
                                             {"refund_vnd": 0, "approval_ok": True}),
    "two amounts in one reply": (trial(reply="Đã hoàn 35.000đ, phí 5.000đ."), LABEL),
    "no reply event": (trial(), LABEL),
}


def original(name, t, label):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.graders import GRADERS

    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=t,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    res = GRADERS[name]().evaluate(ctx)
    return (1.0 if res.value else 0.0), (res.reason or None)


@pytest.fixture(scope="module")
def inspect_scores():
    from inspect_ai import eval as inspect_eval
    from inspect_ai.log import read_eval_log

    from lab9.inspect_port import make_task, to_sample

    samples = [to_sample(name, t, label) for name, (t, label) in CASES.items()]
    out = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as logs:
        run = inspect_eval(make_task(samples), model="mockllm/model", log_dir=logs, display="none")[0]
        assert run.status == "success"
        for s in read_eval_log(run.location).samples:
            out[str(s.id)] = {n: (float(s.scores[n].value), s.scores[n].explanation or None) for n in PORTED}
    return out


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("grader", PORTED)
def test_port_agrees_with_the_original(inspect_scores, case, grader):
    t, label = CASES[case]
    assert inspect_scores[case][grader] == original(grader, t, label)


def test_port_is_not_trivially_constant(inspect_scores):
    """The agreement above would mean nothing if every scorer returned the same thing for every case."""
    for grader in PORTED:
        assert len({v[grader][0] for v in inspect_scores.values()}) == 2


def test_ported_ids_are_the_metric_ids_in_the_spec():
    from lab9.graders import GRADERS
    from lab9.inspect_port import SCORERS

    assert set(SCORERS) == set(PORTED) and set(PORTED) <= set(GRADERS)
