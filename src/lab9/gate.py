"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    man, bman = pr.get("manifest", {}), base.get("manifest", {})
    rows = pr.get("rows") or []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. values that cannot be trusted: NaN or inf anywhere
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN or inf compares False against every threshold)")
    bad_cells = sum(isinstance(v, float) and not math.isfinite(v) for r in rows for v in r.values())
    if bad_cells:
        problems.append(f"{bad_cells} row value(s) are NaN or inf")

    # 2. rows: count, duplicates, and the (item, seed) set
    want = man.get("items", 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows but the manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        problems.append(f"{dup} duplicate (item, seed) row(s)")
    bkeys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if bkeys and set(keys) != bkeys:
        problems.append(f"(item, seed) set differs from the baseline's: {len(bkeys - set(keys))} missing, "
                        f"{len(set(keys) - bkeys)} extra (cherry-picked items or seeds)")
    if bman:
        if man.get("items") != bman.get("items"):
            problems.append(f"manifest items {man.get('items')} != baseline {bman.get('items')}")
        if sorted(man.get("seeds") or []) != sorted(bman.get("seeds") or []):
            problems.append(f"manifest seeds {man.get('seeds')} != baseline {bman.get('seeds')}")
        if bman.get("labels_sha") and man.get("labels_sha") != bman.get("labels_sha"):
            problems.append(f"labels_sha {man.get('labels_sha')} != baseline {bman.get('labels_sha')} "
                            "(the expected answers changed without a new baseline)")

    # 3. graders that crashed: a missing value silently drops out of the mean
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    for m in graded:
        empty = sum(r.get(m) is None for r in rows)
        if empty:
            problems.append(f"{empty} row(s) have no value for graded metric {m} (grader crashed or row edited)")
    # Only graded metrics: derived ones such as cost_per_success are legitimately None when nothing succeeded.
    for m in graded:
        if (base.get("metrics") or {}).get(m) is not None and (pr.get("metrics") or {}).get(m) is None:
            problems.append(f"metric {m} is missing from the report but present in the baseline")

    # 4. metrics must be what the rows add up to (a hand-edited number over honest rows)
    if rows and all("cost" in r for r in rows) and all(m in r for r in rows for m in graded):
        try:
            again = aggregate(rows, graded, k_values=spec.get("pass_k", []))
        except (KeyError, TypeError, ZeroDivisionError):
            again = {}
        for k, v in again.items():
            have = (pr.get("metrics") or {}).get(k)
            if isinstance(v, (int, float)) and isinstance(have, (int, float)) and math.isfinite(have) \
                    and abs(v - have) > 1e-9:
                problems.append(f"metric {k} is {have} but its rows add up to {v}")

    # 5. slice tags: moving an item out of a slice hides its regression from the slice gate
    def tags(rep: dict) -> dict:
        return {r.get("item_id"): frozenset(r.get("slices") or []) for r in rep.get("rows") or []}
    mine, theirs = tags(pr), tags(base)
    moved = sorted(i for i in mine.keys() & theirs.keys() if mine[i] != theirs[i])
    if moved:
        problems.append(f"slice tags changed for {len(moved)} item(s) (e.g. {moved[0]}): relabelled out of a slice")

    # 6. ratchet: on the same eval-set version a threshold may only get stricter
    if base_spec is not None and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += _ratchet(spec, base_spec)
    return problems


def _loosened(new: dict, old: dict, what: str) -> list[str]:
    """Changes that make `new` easier to pass than `old`."""
    out = []
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"{what}: no longer blocking")
    if old.get("kind") and new.get("kind") != old.get("kind"):
        out.append(f"{what}: kind changed from {old['kind']} to {new.get('kind')}")
    nt, ot = new.get("threshold") or {}, old.get("threshold") or {}
    for key, value in ot.items():
        if key == "no_significant_drop":
            if value and not nt.get(key):
                out.append(f"{what}: no_significant_drop dropped")
        elif key not in nt:
            out.append(f"{what}: threshold {key} removed")
        elif key == "min" and nt[key] < value:
            out.append(f"{what}: min lowered {value} -> {nt[key]}")
        elif key in ("max", "max_increase") and nt[key] > value:
            out.append(f"{what}: {key} raised {value} -> {nt[key]}")
    # slices keep min / no_significant_drop at the top level instead of under "threshold"
    if "min" in old:
        if "min" not in new:
            out.append(f"{what}: min removed")
        elif new["min"] < old["min"]:
            out.append(f"{what}: min lowered {old['min']} -> {new['min']}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"{what}: no_significant_drop dropped")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    out: list[str] = []
    now = {m["id"]: m for m in spec.get("metrics", [])}
    for old in base_spec.get("metrics", []):
        if old["id"] not in now:
            out.append(f"metric {old['id']}: removed")
        else:
            out += _loosened(now[old["id"]], old, f"metric {old['id']}")
    now_sl = {s["name"]: s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        if old["name"] not in now_sl:
            out.append(f"slice {old['name']}: removed")
        else:
            new = now_sl[old["name"]]
            if new.get("metric") != old.get("metric"):
                out.append(f"slice {old['name']}: metric changed from {old.get('metric')} to {new.get('metric')}")
            out += _loosened(new, old, f"slice {old['name']}")
    old_c = (base_spec.get("bootstrap") or {}).get("confidence")
    new_c = (spec.get("bootstrap") or {}).get("confidence")
    if old_c is not None and new_c is not None and new_c > old_c:
        out.append(f"bootstrap confidence raised {old_c} -> {new_c} (a wider CI blocks less)")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            # No scored item in this slice: a PR must not hide a regression by emptying the slice.
            verdict, note = "missing", "no scored item in this slice"
        else:
            val = sum(a.values()) / len(a)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                   confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        shown = "-" if val is None else f"{val:.4f}"
        floor = json.dumps({"min": sl["min"]}) if "min" in sl else "{}"
        lines.append(f"  {sid:<34} {shown:<8} {floor:<14} n={len(a):<3} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
