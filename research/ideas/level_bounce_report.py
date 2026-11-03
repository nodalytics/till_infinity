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


def duration_cells(rows: list[dict]) -> list[dict]:
    """The time exponent per cell, real against the hardest null arm.

    **The comparison is the arms, never the asymptotic 0.5.** The estimator
    reads 0.397 on a simulated walk at a 20-bar horizon and 0.429 at 48 - the
    bias is finite-horizon censoring and is measured in
    `level_bounce_duration` - so an absolute exponent is not quotable and only
    the excess over the hardest arm is.

    "Hardest" for duration means the arm whose exponent is **furthest from
    real in the direction that would explain it away**, which is the largest
    arm exponent: a bounce with a characteristic length decays faster than a
    power law, so the claim predicts real **above** its arms.
    """
    out = []
    for (feed, interval, kind), arms in sorted(_grouped(rows).items()):
        real = _mean_of(arms.get("real", []), ["survival", "exponent"])
        if not real:
            continue
        # **Hardest by S(8), not by the exponent.** S(8) is the deciding
        # statistic under the corrected pass rule - monotone across the whole
        # planted-length sweep where the exponent is not - so the arm that has
        # to be beaten is the one with the longest departures, and its exponent
        # is reported for the same arm rather than cherry-picked from another.
        best = None
        for arm in NULLS:
            vals = _mean_of(arms.get(arm, []), ["survival", "at", "8"])
            if not vals:
                continue
            top = max(vals)
            if best is None or top > best[1]:
                best = (arm, top)
        se = _mean_of(arms.get("real", []), ["survival", "exponent_se"])
        med = _mean_of(arms.get("real", []), ["survival", "median"])
        arm_med = (
            _mean_of(arms.get(best[0], []), ["survival", "median"]) if best else []
        )
        better = [
            r["survival"]["power_better"]
            for r in arms.get("real", [])
            if r.get("survival")
        ]
        arm_expt = (
            (_mean_of(arms.get(best[0], []), ["survival", "exponent"]) or [0.0])[0]
            if best
            else 0.0
        )
        t = (real[0] - arm_expt) / se[0] if best and se and se[0] > 0 else 0.0
        out.append(
            {
                "feed": feed,
                "interval": interval,
                "kind": kind,
                "n": int(_mean_of(arms.get("real", []), ["survival", "n"])[0]),
                "censored": (_mean_of(arms.get("real", []), ["survival", "censored"]) or [0.0])[0],
                "median": med[0] if med else None,
                "arm_median": arm_med[0] if arm_med else None,
                "s2": (_mean_of(arms.get("real", []), ["survival", "at", "2"]) or [0.0])[0],
                "s8": (_mean_of(arms.get("real", []), ["survival", "at", "8"]) or [0.0])[0],
                "arm_s8": best[1] if best else 0.0,
                "tail": (_mean_of(arms.get("real", []), ["survival", "tail"]) or [0.0])[0],
                "exponent": real[0],
                "se": se[0] if se else 0.0,
                "power_better": bool(better and all(better)),
                "hardest": best[0] if best else None,
                "hardest_exponent": (
                    (_mean_of(arms.get(best[0], []), ["survival", "exponent"]) or [0.0])[0]
                    if best
                    else None
                ),
                "excess": (
                    real[0] - (_mean_of(arms.get(best[0], []), ["survival", "exponent"]) or [0.0])[0]
                    if best
                    else None
                ),
                "t": t,
                "p": _p_two_sided(t),
            }
        )
    return out


def part_two_survival(rows: list[dict], grade: str) -> list[dict]:
    """The grade's exponent difference, high-grade minus low, against the arms.

    The causal grading question asked in the time domain: do a level's
    **previous** durations say anything about its next one. Same split as the
    shape and R versions - each compression-by-age cell's own median grade - so
    the three answers are comparable.
    """
    path = ["grades", grade, "survival"]
    out = []
    for (feed, interval, kind), arms in sorted(_grouped(rows).items()):
        real = _mean_of(arms.get("real", []), [*path, "diff"])
        if not real:
            continue
        se = _mean_of(arms.get("real", []), [*path, "se"])
        best = None
        for arm in NULLS:
            vals = _mean_of(arms.get(arm, []), [*path, "diff"])
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
                "n_high": int((_mean_of(arms.get("real", []), [*path, "n_high"]) or [0])[0]),
                "n_low": int((_mean_of(arms.get("real", []), [*path, "n_low"]) or [0])[0]),
                "exponent_high": (_mean_of(arms.get("real", []), [*path, "exponent_high"]) or [0.0])[0],
                "exponent_low": (_mean_of(arms.get("real", []), [*path, "exponent_low"]) or [0.0])[0],
                "diff": real[0],
                "se": se[0] if se else 0.0,
                "t": t,
                "p": _p_two_sided(t),
                "hardest": best[0] if best else None,
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

    print(f"\n=== duration: the time exponent, real against the hardest null arm ===")
    print(
        "  The asymptotic walk exponent is 0.5, but this estimator reads 0.397 on a\n"
        "  simulated walk at horizon 20 and 0.429 at 48, so the ARMS are the comparison\n"
        "  and the 0.5 is only an anchor.\n"
        "  A characteristic length shows as pow? FALSE and S8 above the arm's S8.\n"
        "  The EXPONENT is non-monotone in the planted length (0.426 -> 0.457 -> 0.245\n"
        "  -> 0.113 at lengths 0/2/8/16) and so cannot carry the sign - it is printed\n"
        "  as description. dS8 is the deciding column.\n"
    )
    dcells = duration_cells(rows)
    print(
        f"{'feed':9s} {'iv':4s} {'kind':9s} {'n':>6s} {'cens':>6s} {'tail':>6s} "
        f"{'S2':>6s} {'S8':>6s} {'armS8':>6s} {'dS8':>7s} {'expt':>7s} {'se':>7s} "
        f"{'pow?':>5s} {'hardest':>14s} {'theirs':>7s} {'dexpt':>8s} {'t':>6s}"
    )
    for c in dcells:
        print(
            f"{c['feed']:9s} {c['interval']:4s} {c['kind']:9s} {c['n']:6d} "
            f"{c['censored']:6.3f} {c['tail']:6.3f} "
            f"{c['s2']:6.3f} {c['s8']:6.3f} {c['arm_s8']:6.3f} "
            f"{_fmt(c['s8'] - c['arm_s8'], 7, 3)} "
            f"{c['exponent']:7.4f} {c['se']:7.4f} {str(c['power_better'])[:5]:>5s} "
            f"{(c['hardest'] or ''):>14s} {(c['hardest_exponent'] or 0):7.4f} "
            f"{_fmt(c['excess'], 8)} {c['t']:+6.2f}"
        )
    if dcells:
        qs = benjamini_hochberg([c["p"] for c in dcells])
        longer = [c for c in dcells if c["s8"] > c["arm_s8"]]
        print(
            f"  cells {len(dcells)}; **S8 above the hardest arm's in "
            f"{len(longer)}**; exponent above its arm in "
            f"{sum(1 for c in dcells if (c['excess'] or 0) > 0)}; "
            f"BH on the exponent {sum(1 for q in qs if q < 0.05)}; "
            f"power-law still better in {sum(1 for c in dcells if c['power_better'])} "
            f"(a characteristic length would make this small)"
        )
        cens = [c["censored"] for c in dcells]
        print(
            f"  censored share across cells: min {min(cens):.3f} "
            f"median {sorted(cens)[len(cens) // 2]:.3f} max {max(cens):.3f}"
        )
        no_med = [c for c in dcells if c["median"] is None]
        if no_med:
            print(f"  cells whose curve never reaches 0.5 (longer than the horizon): {len(no_med)}")

    print("\n=== duration: does a level's PREVIOUS durations predict its next ===")
    got = part_two_survival(rows, "long_share")
    if got:
        print(
            f"{'feed':9s} {'iv':4s} {'kind':9s} {'nhi':>6s} {'nlo':>6s} "
            f"{'ehi':>7s} {'elo':>7s} {'diff':>8s} {'se':>7s} {'t':>6s} "
            f"{'hardest':>14s} {'excess':>8s}"
        )
        for c in got:
            print(
                f"{c['feed']:9s} {c['interval']:4s} {c['kind']:9s} {c['n_high']:6d} "
                f"{c['n_low']:6d} {c['exponent_high']:7.4f} {c['exponent_low']:7.4f} "
                f"{_fmt(c['diff'], 8)} {c['se']:7.4f} {c['t']:+6.2f} "
                f"{(c['hardest'] or ''):>14s} {_fmt(c['excess'], 8)}"
            )
        qs = benjamini_hochberg([c["p"] for c in got])
        print(
            f"  cells {len(got)}; beating their hardest null "
            f"{sum(1 for c in got if c['excess'] is not None and c['excess'] > 0)}; "
            f"BH survivors {sum(1 for q in qs if q < 0.05)}; "
            f"positive {sum(1 for c in got if c['diff'] > 0)}"
        )

    print("\n=== does duration restate shape or R? Spearman, real arm ===")
    keys = ("r_mtm", "r1", "r2", "r3", "peak_at", "held", "excursion", "sharp", "run")
    print(f"{'iv':4s} {'kind':9s} {'n':>8s} " + " ".join(f"{k:>9s}" for k in keys))
    pooled: dict = defaultdict(list)
    for row in rows:
        if row["arm"] == "real" and row.get("correlations"):
            pooled[(row["interval"], row["kind"])].append(row["correlations"])
    for (interval, kind), got2 in sorted(pooled.items()):
        total = sum(c.get("n", 0) for c in got2)
        cells = " ".join(
            f"{sum(c.get(k, 0.0) * c.get('n', 0) for c in got2) / max(1.0, total):9.3f}"
            for k in keys
        )
        print(f"{interval:4s} {kind:9s} {total:8.0f} {cells}")

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
            f"{'sharp':>7s} {'meanR':>9s} {'gradeR':>9s} {'se':>8s} {'t':>6s} {'auc':>6s} "
            f"{'expt':>7s} {'med':>5s} {'pow?':>5s}"
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
            expt = _mean_of(got, ["survival", "exponent"])
            med = _mean_of(got, ["survival", "median"])
            pw = [
                g["survival"]["power_better"] for g in got if g.get("survival")
            ]
            print(
                f"{feed:9s} {which:8s} {level:6.2f} "
                f"{sum(g['episodes'] for g in got) / len(got):6.0f} "
                f"{(avg(_mean_of(got, ['hold', 'value'])) or 0):7.4f} "
                f"{sum(g['shares']['sharp'] for g in got) / len(got):7.3f} "
                f"{_fmt(avg(_mean_of(got, ['r', HEAD, 'mean'])), 9)} "
                f"{_fmt(avg(means), 9)} {(avg(ses) or 0):8.4f} {t:+6.2f} "
                f"{(avg(_mean_of(got, ['grades', 'sharp_share', 'auc', 'value'])) or 0):6.3f} "
                f"{(avg(expt) or 0):7.4f} {(avg(med) or -1):5.0f} "
                f"{(sum(pw) / len(pw) if pw else 0):5.2f}"
            )


if __name__ == "__main__":
    main()
