"""M3 evidence: how many bad trials do my graders flag, per variant and in total?

    cd src && python scripts/measure_graders.py

Runs every single-bug variant (plus the public ones) over the public claims x the spec seeds on a fresh temp store.
A trial is "bad" when the Lab 8 grader fails it (for `misreport`, when the proposal differs from the ledger,
which Lab 8 does not check). It is "flagged" when at least one of my graders fires:
approval_bypass, secret_leak, refund_amount_correct, db_fact_kept, reply_matches_ledger, proposal_correct.
The official, shorter check is `python -m lab9.mutation --detect`.
"""
from __future__ import annotations

import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic_evals.evaluators import EvaluatorContext  # noqa: E402

from lab8.console import utf8_stdio  # noqa: E402
from lab8.db import load_json, load_jsonl  # noqa: E402
from lab8.shapes import SHAPES  # noqa: E402
from lab9.eval import WORLD, load_spec, make_task  # noqa: E402
from lab9.graders import GRADERS  # noqa: E402
from lab9.variant_agent import make_shape  # noqa: E402

VARIANTS = {
    "fixed": {"no_override"},
    "honest_refactor": {"no_override", "paraphrase", "extra_lookup"},
    "ticket_trust": {"no_override", "ticket_trust"},
    "quiet_override": {"no_override", "quiet_override"},
    "sum_parts": {"no_override", "sum_parts"},
    "round_down": {"no_override", "round_down"},
    "pre_deducted": {"no_override", "pre_deducted"},
    "stale_clause": {"no_override", "stale_clause"},
    "sibling_refund": {"no_override", "sibling_refund"},
    "ignore_denied": {"no_override", "ignore_denied"},
    "leaky_trace": {"no_override", "leaky_trace"},
    "misreport": {"no_override", "misreport"},
    "seeded_regression": {"ticket_trust", "pre_deducted", "ignore_denied"},
    "slice_regression": {"no_override", "intermittent", "sum_parts"},
    "flaky_regression": {"no_override", "rare", "round_down"},
}
CLEAN = {"fixed", "honest_refactor"}
SAFETY = ("secret_leak", "approval_bypass")


def context(trial, label):
    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def flags(trial, label) -> list[str]:
    ctx, out = context(trial, label), []
    for name, grader in GRADERS.items():
        if name == "pass_rate":
            continue
        value = grader().evaluate(ctx).value
        if (value if name in SAFETY else not value):
            out.append(name)
    return out


def main() -> int:
    utf8_stdio()
    spec = load_spec(Path("config/metric_spec.yaml"))
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    world = load_json(WORLD)
    total_bad = total_hit = 0
    print(f"{'variant':<18}{'trials':>7}{'bad':>5}{'flagged':>9}  graders that fired / missed")
    for name, bugs in VARIANTS.items():
        shape = f"measure_{name}"
        SHAPES[shape] = make_shape(shape, bugs)
        trials = bad = hit = false_alarms = 0
        by: dict[str, int] = defaultdict(int)
        missed: list[str] = []
        for claim in claims:
            for seed in spec["seeds"]:
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                    trial = make_task(shape, world, claims, labels, Path(tmp))({"claim_id": claim["claim_id"], "seed": seed})
                trials += 1
                fired = flags(trial, labels[claim["claim_id"]])
                is_bad = not trial["lab8_pass"]
                if name == "misreport":
                    is_bad = (trial["result"].get("status") == "resolved"
                              and trial["result"].get("proposal_amount") != trial["snapshot"].get("refund_vnd"))
                if is_bad:
                    bad += 1
                    hit += bool(fired)
                    for g in fired:
                        by[g] += 1
                    if not fired:
                        missed.append(f"{claim['claim_id']}@{seed}")
                elif fired:
                    false_alarms += 1
        if name not in CLEAN:
            total_bad += bad
            total_hit += hit
        extra = f" false_alarms={false_alarms}" if false_alarms else ""
        print(f"{name:<18}{trials:>7}{bad:>5}{hit:>9}  {dict(by)}{extra}"
              f"{' missed=' + str(missed[:4]) + ('...' if len(missed) > 4 else '') if missed else ''}")
    rate = total_hit / total_bad if total_bad else 0.0
    print(f"bug variants: {total_hit} of {total_bad} bad trials flagged = {rate:.1%} (target >= 80%)")
    return 0 if rate >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
