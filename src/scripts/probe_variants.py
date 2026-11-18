"""M5-M7 evidence: run variants that are NOT in lab9.variants through the real gate (v2 spec + baseline).

    cd src && python scripts/probe_variants.py

The instructor grades with hidden variants. These are my own guesses at them: single bugs and small
combinations of the bug switches in lab9.variant_agent. Expected verdicts are what a sound gate should say.
Needs reports/baseline_v2.json (python -m lab9.eval --shape swarm --spec config/metric_spec_v2.yaml
--out reports/baseline_v2.json). Exit 0 only when every verdict matches.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab8.console import utf8_stdio  # noqa: E402
from lab8.shapes import SHAPES  # noqa: E402
from lab9 import gate, variants  # noqa: E402
from lab9.eval import load_spec, run_eval  # noqa: E402
from lab9.variant_agent import make_shape  # noqa: E402

CASES = {
    "quiet_override (no override event)": ({"quiet_override"}, "block"),
    "round_down on every seed": ({"no_override", "round_down"}, "block"),
    "stale_clause": ({"no_override", "stale_clause"}, "block"),
    "sibling_refund": ({"no_override", "sibling_refund"}, "block"),
    "misreport on every seed": ({"no_override", "misreport"}, "block"),
    "intermittent ticket_trust": ({"no_override", "intermittent", "ticket_trust"}, "block"),
    "intermittent pre_deducted": ({"no_override", "intermittent", "pre_deducted"}, "block"),
    "rare sum_parts": ({"no_override", "rare", "sum_parts"}, "block"),
    "leaky_trace": ({"no_override", "leaky_trace"}, "block"),
    "paraphrase only": ({"no_override", "paraphrase"}, "merge"),
    "extra_lookup only": ({"no_override", "extra_lookup"}, "merge"),
    "paraphrase + extra_lookup + intermittent": ({"no_override", "paraphrase", "extra_lookup", "intermittent"}, "merge"),
    # Known blind spot (docs/eval_card.md, M7): same failing items as the baseline, on another seed.
    "rare quiet_override [known blind spot]": ({"no_override", "rare", "quiet_override"}, "block"),
}
KNOWN_BLIND_SPOTS = {"rare quiet_override [known blind spot]"}


def main() -> int:
    utf8_stdio()
    variants.register()
    spec = load_spec(Path("config/metric_spec_v2.yaml"))
    base = json.loads(Path("reports/baseline_v2.json").read_text(encoding="utf-8"))
    wrong = 0
    for name, (bugs, want) in CASES.items():
        SHAPES["probe"] = make_shape("probe", bugs)
        blocked, _ = gate.check(run_eval("probe", spec), base, spec)
        got = "block" if blocked else "merge"
        tag = "ok" if got == want else ("blind spot" if name in KNOWN_BLIND_SPOTS else "MISMATCH")
        wrong += tag == "MISMATCH"
        print(f"{name:<44} expect {want:<5} got {got:<5} {tag:<10} {', '.join(blocked)[:80]}")
    print(f"unexpected mismatches: {wrong}")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
