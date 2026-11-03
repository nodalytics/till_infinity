"""Read the level-bounce panel and print the tables the write-up carries.

Reads `panel.jsonl`, `effgrid.jsonl` and `power.jsonl` from `BOUNCE_OUT`.

Three things decide and they are printed in this order:

1. **mean R per kind per feed**, real against the hardest arm, with each arm's
   per-trade sd and the sample its own mean and sd imply. A hit rate is printed
   beside them as description and is never the verdict.
2. **the grade's R difference** - high-grade minus low-grade mean R, which is
   the claim. Per feed and per kind, never only pooled:
   `pooled-medians-invert-subgroups` is a pooled median that agreed with a
   claim every subgroup refuted.
3. **the kind-against-pivots column**, because if the Kalman book does not beat
   a parameter-free pivot set the swing detection is not earning its
   complexity, and nothing on this desk had checked.

Benjamini-Hochberg runs over every cell and the deflated Sharpe is computed
against the **full trial count**, both from `node/multiple.py` and
`node/metrics.py` rather than from a local copy.
"""

from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

from till_infinity.node.metrics import expected_max_sharpe, trial_variance
from till_infinity.node.multiple import benjamini_hochberg

OUT = Path(os.environ.get("BOUNCE_OUT") or "bounce-out")

#: Arms that are nulls. `real` is the only arm that is not one.
NULLS = ("placebo", "garch-bars", "walk-geometry", "bar-shuffle")

#: The reward-to-risk the headline is read at. Pre-registered as 2.0 - a 2:1 is
#: the shape most of this desk's strategies are built in, and the walk pays
#: exactly zero there as at every other target.
HEAD = "2.0"


def load(name: str) -> list[dict]:
    path = OUT / name
    if not path.exists():
        return []
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _p_two_sided(t: float) -> float:
    return 2.0 * (1.0 - _phi(abs(t)))


def _key(row: dict) -> tuple[str, str, str]:
    return row["feed"], row["interval"], row["kind"]


def _grouped(rows: list[dict]) -> dict:
    """`{(feed, interval, kind): {arm: [rows]}}`."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for row in rows:
        out[_key(row)][row["arm"]].append(row)
    return out


def _mean_of(rows: list[dict], path: list) -> list[float]:
    """Every finite value at `path` across `rows`, for averaging over draws."""
    got = []
    for row in rows:
        here = row
        for step in path:
            if here is None:
                break
            here = here.get(step) if isinstance(here, dict) else None
        if isinstance(here, (int, float)):
            got.append(float(here))
    return got


def part_one(rows: list[dict]) -> list[dict]:
    """Mean R at the headline target, real against the hardest null arm."""
    out = []
    for (feed, interval, kind), arms in sorted(_grouped(rows).items()):
        real = _mean_of(arms.get("real", []), ["r", HEAD, "mean"])
        if not real:
            continue
        sd = _mean_of(arms.get("real", []), ["r", HEAD, "sd"])
        se = _mean_of(arms.get("real", []), ["r", HEAD, "se"])
        need = _mean_of(arms.get("real", []), ["r", HEAD, "needed"])
        hold = _mean_of(arms.get("real", []), ["hold", "value"])
        best = None
        for arm in NULLS:
            vals = _mean_of(arms.get(arm, []), ["r", HEAD, "mean"])
            if not vals:
                continue
            top = max(vals)
            if best is None or top > best[1]:
                best = (arm, top, st.pstdev(vals) if len(vals) > 1 else 0.0)
        out.append(
            {
                "feed": feed,
                "interval": interval,
                "kind": kind,
                "n": int(_mean_of(arms.get("real", []), ["r", HEAD, "n"])[0]),
                "mean": real[0],
                "se": se[0] if se else 0.0,
                "sd": sd[0] if sd else 0.0,
                "needed": need[0] if need else None,
                "hold": hold[0] if hold else None,
                "hardest": best[0] if best else None,
                "hardest_mean": best[1] if best else None,
                "excess": real[0] - best[1] if best else None,
            }
        )
    return out


def part_two(rows: list[dict], grade: str) -> list[dict]:
    """The grade's R difference, real against the hardest null arm."""
    path = ["grades", grade, "r", HEAD, "diff"]
    out = []
    for (feed, interval, kind), arms in sorted(_grouped(rows).items()):
        real = _mean_of(arms.get("real", []), [*path, "mean"])
        if not real:
            continue
        se = _mean_of(arms.get("real", []), [*path, "se"])
        sd = _mean_of(arms.get("real", []), [*path, "sd"])
        need = _mean_of(arms.get("real", []), [*path, "needed"])
        auc = _mean_of(arms.get("real", []), ["grades", grade, "auc", "value"])
        best = None
        for arm in NULLS:
            vals = _mean_of(arms.get(arm, []), [*path, "mean"])
            if not vals:
                continue
            top = max(vals)
            if best is None or top > best[1]:
                best = (arm, top)
        t = real[0] / se[0] if se and se[0] > 0 else 0.0
        out.append(
            {
                "feed": feed,
                "interval": interval,
                "kind": kind,
                "grade": grade,
                "n": int(_mean_of(arms.get("real", []), [*path, "n"])[0]),
                "diff": real[0],
                "se": se[0] if se else 0.0,
                "sd": sd[0] if sd else 0.0,
                "t": t,
                "p": _p_two_sided(t),
                "needed": need[0] if need else None,
                "auc": auc[0] if auc else None,
                "hardest": best[0] if best else None,
                "hardest_diff": best[1] if best else None,
                "excess": real[0] - best[1] if best else None,
            }
        )
    return out


def deflated(cells: list[dict]) -> dict:
    """The Sharpe the best of these cells would show if every one were nothing.

    `expected_max_sharpe` over the cells' own spread, from `node/metrics.py`.
    A per-trade Sharpe is `mean / sd`, so each cell contributes
    `diff / sd` and the comparison is against the expected maximum of that
    many draws - which is the whole content of "picking the best of 43
    instruments gives a winner every time".
    """
    sharpes = [c["diff"] / c["sd"] for c in cells if c["sd"] > 0]
    if len(sharpes) < 2:
        return {}
    variance = trial_variance(sharpes)
    threshold = expected_max_sharpe(variance, len(sharpes))
    best = max(sharpes)
    return {
        "trials": len(sharpes),
        "best_sharpe": best,
        "threshold": threshold,
        "clears": best > threshold,
    }


def _fmt(x, width=8, places=4):
    return " " * width if x is None else f"{x:+{width}.{places}f}"


def main() -> None:
    rows = load("panel.jsonl")
    if not rows:
        print(f"no panel at {OUT / 'panel.jsonl'}", file=sys.stderr)
        return
    print(f"{len(rows)} panel rows from {OUT}\n")

    print("=== shape shares, real arm, averaged over feeds ===")
    by_kind: dict = defaultdict(list)
    for row in rows:
        if row["arm"] == "real":
            by_kind[(row["interval"], row["kind"])].append(row["shares"])
    print(f"{'interval':9s} {'kind':9s} {'n':>8s} " + " ".join(f"{k:>9s}" for k in
          ("reject", "spike", "leg", "run", "drift", "through", "stall", "sharp")))
    for (interval, kind), got in sorted(by_kind.items()):
        total = sum(s["n"] for s in got)
        print(
            f"{interval:9s} {kind:9s} {total:8.0f} "
            + " ".join(
                f"{sum(s[k] * s['n'] for s in got) / max(1.0, total):9.3f}"
                for k in ("reject", "spike", "leg", "run", "drift", "through", "stall", "sharp")
            )
        )

    print(f"\n=== part 1: mean R at {HEAD}R, real against the hardest null arm ===")
    cells = part_one(rows)
    print(
        f"{'feed':9s} {'iv':4s} {'kind':9s} {'n':>6s} {'meanR':>9s} {'se':>8s} "
        f"{'sd':>6s} {'needed':>9s} {'hold':>6s} {'hardest':>14s} {'theirs':>9s} {'excess':>9s}"
    )
    for c in cells:
        need = "" if c["needed"] is None else f"{min(c['needed'], 9.9e8):9.0f}"
        print(
            f"{c['feed']:9s} {c['interval']:4s} {c['kind']:9s} {c['n']:6d} "
            f"{_fmt(c['mean'], 9)} {c['se']:8.4f} {c['sd']:6.3f} {need:>9s} "
            f"{(c['hold'] or 0):6.3f} {(c['hardest'] or ''):>14s} "
            f"{_fmt(c['hardest_mean'], 9)} {_fmt(c['excess'], 9)}"
        )

    for grade in ("sharp_share", "run_share", "bar_share", "hold_share", "hold_dev"):
        got = part_two(rows, grade)
        if not got:
            continue
        print(f"\n=== part 2: {grade}, R difference at {HEAD}R ===")
        print(
            f"{'feed':9s} {'iv':4s} {'kind':9s} {'n':>6s} {'diffR':>9s} {'se':>8s} "
            f"{'t':>6s} {'needed':>9s} {'auc':>6s} {'hardest':>14s} {'theirs':>9s} {'excess':>9s}"
        )
        for c in got:
            need = "" if c["needed"] is None else f"{min(c['needed'], 9.9e8):9.0f}"
            print(
                f"{c['feed']:9s} {c['interval']:4s} {c['kind']:9s} {c['n']:6d} "
                f"{_fmt(c['diff'], 9)} {c['se']:8.4f} {c['t']:+6.2f} {need:>9s} "
                f"{(c['auc'] or 0):6.3f} {(c['hardest'] or ''):>14s} "
                f"{_fmt(c['hardest_diff'], 9)} {_fmt(c['excess'], 9)}"
            )
        beats = [c for c in got if c["excess"] is not None and c["excess"] > 0]
        qs = benjamini_hochberg([c["p"] for c in got])
        survivors = [c for c, q in zip(got, qs, strict=True) if q < 0.05]
        print(
            f"  cells {len(got)}; beating their hardest null {len(beats)}; "
            f"BH survivors {len(survivors)}; "
            f"positive {sum(1 for c in got if c['diff'] > 0)}"
        )
        print(f"  deflated: {deflated(got)}")

    print("\n=== kinds against pivots, mean R excess over own nulls, per feed ===")
    best: dict = defaultdict(dict)
    for c in part_one(rows):
        if c["excess"] is not None:
            best[(c["feed"], c["interval"])][c["kind"]] = c["excess"]
    print(f"{'feed':9s} {'iv':4s} " + " ".join(f"{k:>11s}" for k in
          ("levels", "bjorgum", "pips", "pivots")) + "   levels-pivots")
    wins = 0
    seen = 0
    for (feed, interval), got in sorted(best.items()):
        row = " ".join(_fmt(got.get(k), 11) for k in ("levels", "bjorgum", "pips", "pivots"))
        gap = (
            got["levels"] - got["pivots"]
            if "levels" in got and "pivots" in got
            else None
        )
        if gap is not None:
            seen += 1
            wins += gap > 0
        print(f"{feed:9s} {interval:4s} {row}   {_fmt(gap, 11)}")
    if seen:
        print(f"  levels beats pivots on {wins} of {seen} feed-intervals")

    grid = load("effgrid.jsonl")
    if grid:
        print("\n=== RUN_EFF grid, real arm, reported on the mean ===")
        print(f"{'feed':9s} {'eff':>5s} {'run share':>10s} {'meanR':>9s} {'sharp diffR':>12s}")
        for row in grid:
            diff = row["grades"]["run_share"]["r"].get(HEAD) or {}
            print(
                f"{row['feed']:9s} {row['run_eff']:5.2f} {row['shares']['run']:10.3f} "
                f"{_fmt((row['r'][HEAD] or {}).get('mean'), 9)} "
                f"{_fmt((diff.get('diff') or {}).get('mean'), 12)}"
            )

    power = load("power.jsonl")
    if power:
        print("\n=== power: planted bounce, and planted grading ===")
        print(
            "  uniform: the control that must read nothing on the grade, because\n"
            "  every level is the same. graded: the alternative, where levels differ\n"
            "  and a level's own past is informative. Blind point is where |t| < 2.\n"
        )
        print(
            f"{'feed':9s} {'sweep':8s} {'level':>6s} {'eps':>6s} {'hold':>7s} "
            f"{'sharp':>7s} {'meanR':>9s} {'gradeR':>9s} {'se':>8s} {'t':>6s} {'auc':>6s}"
        )
        agg: dict = defaultdict(list)
        for row in power:
            agg[(row["feed"], row["sweep"], row["level"])].append(row)

        def avg(xs):
            return sum(xs) / len(xs) if xs else None

        path = ["grades", "sharp_share", "r", HEAD, "diff"]
        for (feed, which, level), got in sorted(agg.items()):
            means = _mean_of(got, [*path, "mean"])
            ses = _mean_of(got, [*path, "se"])
            t = (avg(means) / avg(ses)) if means and ses and avg(ses) > 0 else 0.0
            print(
                f"{feed:9s} {which:8s} {level:6.2f} "
                f"{sum(g['episodes'] for g in got) / len(got):6.0f} "
                f"{(avg(_mean_of(got, ['hold', 'value'])) or 0):7.4f} "
                f"{sum(g['shares']['sharp'] for g in got) / len(got):7.3f} "
                f"{_fmt(avg(_mean_of(got, ['r', HEAD, 'mean'])), 9)} "
                f"{_fmt(avg(means), 9)} {(avg(ses) or 0):8.4f} {t:+6.2f} "
                f"{(avg(_mean_of(got, ['grades', 'sharp_share', 'auc', 'value'])) or 0):6.3f}"
            )


if __name__ == "__main__":
    main()
