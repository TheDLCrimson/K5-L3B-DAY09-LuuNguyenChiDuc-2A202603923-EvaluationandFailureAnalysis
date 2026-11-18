"""Bonus evidence: do the Inspect AI scorers agree with the pydantic-evals graders?

    cd src && python scripts/compare_inspect.py

1. Builds every trial for the 15 variants of measure_graders.VARIANTS (plus the reference `swarm`) over the
   28 eval-set-v2 items x the 5 spec seeds, on a fresh temp store each, so it exercises many wrong behaviours.
2. Scores each trial with the original lab9.graders and with the Inspect AI port (one Inspect eval, mockllm,
   no key, no network) and compares the verdict and the reason string trial by trial.
3. Aggregates the Inspect AI scores for `swarm` and compares them with the committed reports/baseline_v2.json.
Exit 0 only when every trial and every aggregate agrees. Inspect AI logs go to a temp folder.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402
from pydantic_evals.evaluators import EvaluatorContext  # noqa: E402

from lab8.console import utf8_stdio  # noqa: E402
from lab8.shapes import SHAPES  # noqa: E402
from lab9 import evalset, variants  # noqa: E402
from lab9.eval import load_spec, load_world, make_task  # noqa: E402
from lab9.graders import GRADERS  # noqa: E402
from lab9.inspect_port import SCORERS, make_task as inspect_task, to_sample  # noqa: E402
from lab9.variant_agent import make_shape  # noqa: E402
from measure_graders import VARIANTS  # noqa: E402

SPEC = Path("config/metric_spec_v2.yaml")
BASELINE = Path("reports/baseline_v2.json")
PORTED = list(SCORERS)


def original(name: str, trial: dict, label: dict) -> tuple[float, str | None]:
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    res = GRADERS[name]().evaluate(ctx)
    return (1.0 if res.value else 0.0), (res.reason or None)


def main() -> int:
    utf8_stdio()
    variants.register()
    spec = load_spec(SPEC)
    items = evalset.load_jsonl(Path(spec["eval_set"]))
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    world, claims = load_world(spec)
    shapes = {"swarm": None, **{f"cmp_{n}": b for n, b in VARIANTS.items()}}
    for shape, bugs in shapes.items():
        if bugs is not None:
            SHAPES[shape] = make_shape(shape, bugs)

    samples, expected = [], {}
    for shape in shapes:
        for item in items:
            for seed in spec["seeds"]:
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                    trial = make_task(shape, world, claims, labels, Path(tmp))({"claim_id": item["claim_id"], "seed": seed})
                label = labels[item["claim_id"]]
                sid = f"{shape}|{item['item_id']}|{seed}"
                samples.append(to_sample(sid, trial, label))
                expected[sid] = {n: original(n, trial, label) for n in PORTED}
    print(f"{len(samples)} trials ({len(shapes)} shapes x {len(items)} items x {len(spec['seeds'])} seeds)")

    # Inspect AI loads samples lazily from its log file, so read everything before the temp folder goes.
    scored: dict[str, dict[str, tuple[float, str | None]]] = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as logs:
        run = inspect_eval(inspect_task(samples), model="mockllm/model", log_dir=logs, display="none")[0]
        if run.status != "success":
            print(f"Inspect AI run failed: {run.status} {run.error}")
            return 2
        for s in read_eval_log(run.location).samples or []:
            scored[str(s.id)] = {n: (float(s.scores[n].value), s.scores[n].explanation or None) for n in PORTED}
    if len(scored) != len(samples):
        print(f"Inspect AI scored {len(scored)} of {len(samples)} samples")
        return 2

    mismatches = []
    per = {n: {"agree": 0, "violations": 0} for n in PORTED}
    values: dict[str, dict[str, list[float]]] = {n: {} for n in PORTED}
    for sid, by_grader in scored.items():
        for n in PORTED:
            v, expl = by_grader[n]
            ov, oexpl = expected[sid][n]
            if (v, expl) == (ov, oexpl):
                per[n]["agree"] += 1
            else:
                mismatches.append((sid, n, (ov, oexpl), (v, expl)))
            per[n]["violations"] += v == (1.0 if n == "approval_bypass" else 0.0)
            values[n].setdefault(sid.split("|")[0], []).append(v)

    print(f"{'grader':<24}{'trials':>7}{'agree':>7}  bad/violating trials (both frameworks)")
    for n in PORTED:
        print(f"{n:<24}{len(scored):>7}{per[n]['agree']:>7}  {per[n]['violations']}")
    for sid, n, o, i in mismatches[:10]:
        print(f"MISMATCH {sid} {n}: pydantic-evals {o} vs inspect {i}")

    base = json.loads(BASELINE.read_text(encoding="utf-8"))["metrics"]
    ok_base = True
    print("\nInspect AI aggregate on `swarm` against the committed reports/baseline_v2.json:")
    for n in PORTED:
        vals = values[n]["swarm"]
        agg = sum(vals) if n == "approval_bypass" else round(sum(vals) / len(vals), 4)
        same = agg == base[n]
        ok_base &= same
        print(f"  {n:<24} inspect {agg!s:<8} baseline {base[n]!s:<8} {'ok' if same else 'DIFFERS'}")
    ok = not mismatches and ok_base
    print(f"\n{'exit 0 - every trial and every aggregate agrees' if ok else 'exit 1 - the frameworks disagree'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
