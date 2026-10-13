"""Three audits of this session's own measurements, not of the market.

Each arm takes a number this desk has reported and asks whether it survives a
resampling or a reconditioning it was never subjected to. None of them is about
markets; all three are about whether the published figures mean what they say.

## Why these three

**Tail estimability.** `statespace-volatility-relationships.md` reports a median
tail lift of `+0.1275` at the 99th percentile with 177 of 190 pairs beating the
null, and that result carries the session's main risk conclusion -
diversification fails when it is needed. It is computed from the **top 1% of
observations**, and the concentration audit has since measured the traded tail
index at `alpha` 2.4 to 3.4, so the fourth moment does not exist. Taleb's
sharpest technical claim is that such a quantity cannot be estimated from data.
If the lift swings across disjoint subsamples, the number needs qualifying
however significant it looked.

**Survivorship.** `statespace-panel-volatility.md` reports `+4.3%` on equities
and the arm selected the "best 21 by coverage" - which explicitly selects
**long-lived listings**, and delisted names are not in the cache at all. So the
figure is measured on survivors. Comparing the long-coverage group against the
next group down bounds how much of it that is.

**The turkey.** Every fit in this session trains on a first half and scores a
second. If the first half happened to be quiet, the fit is a turkey: confident
because nothing has happened yet. Conditioning the out-of-sample degradation on
the **training half's own volatility** says whether that is a real failure mode
here, and it audits the panel estimator, the slope wander and the exploit search
at once.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import panel_volatility as panel  # noqa: E402
import relationship_screen as screen  # noqa: E402

#: Disjoint subsamples the tail lift is recomputed on.
PIECES = int(os.environ.get("PIECES", "4"))
#: Quantiles the lift is measured at.
EDGES = (0.90, 0.95, 0.99)
#: Equities per coverage group.
GROUP = int(os.environ.get("GROUP", "20"))
SEED = 20261013


def lift(left, right, edge: float) -> float:
    """`P(|y| past its own edge | |x| past its own)` less the unconditional rate."""
    import numpy as np

    got = screen.align(left, right)
    if got is None:
        return float("nan")
    _, a, b, _, _ = got
    da, db = np.abs(np.diff(a)), np.abs(np.diff(b))
    if len(da) < 400:
        return float("nan")
    x = da > np.quantile(da, edge)
    y = db > np.quantile(db, edge)
    if x.sum() < 10:
        return float("nan")
    return float(y[x].mean() - y.mean())


def lift_on(left, right, edge: float, piece: int, pieces: int) -> float:
    """The same lift on one disjoint slice, with the quantiles refitted locally."""
    import numpy as np

    got = screen.align(left, right)
    if got is None:
        return float("nan")
    _, a, b, _, _ = got
    size = len(a) // pieces
    if size < 500:
        return float("nan")
    lo, hi = piece * size, (piece + 1) * size
    da, db = np.abs(np.diff(a[lo:hi])), np.abs(np.diff(b[lo:hi]))
    x = da > np.quantile(da, edge)
    y = db > np.quantile(db, edge)
    if x.sum() < 10:
        return float("nan")
    return float(y[x].mean() - y.mean())


def tail_arm(names, series) -> None:
    from itertools import combinations

    print("=" * 112)
    print("ARM 1  is the tail lift estimable, or a statement about which window")
    print("=" * 112)
    print(
        f"{'edge':>7}{'pairs':>8}{'whole':>10}{'piece median':>14}"
        f"{'piece spread':>14}{'spread/effect':>15}{'sign agrees':>13}"
    )
    for edge in EDGES:
        whole, spreads, agrees = [], [], []
        for a, b in combinations(names, 2):
            full = lift(series[a], series[b], edge)
            if not math.isfinite(full):
                continue
            pieces = [
                lift_on(series[a], series[b], edge, i, PIECES) for i in range(PIECES)
            ]
            pieces = [p for p in pieces if math.isfinite(p)]
            if len(pieces) < PIECES:
                continue
            whole.append(full)
            spreads.append(statistics.pstdev(pieces))
            agrees.append(all((p > 0) == (full > 0) for p in pieces))
        if not whole:
            continue
        middle = statistics.median(whole)
        spread = statistics.median(spreads)
        print(
            f"{edge:>7.2f}{len(whole):>8}{middle:>+10.4f}{middle:>+14.4f}"
            f"{spread:>14.4f}{spread / abs(middle) if middle else float('nan'):>15.2f}"
            f"{sum(agrees) / len(agrees):>13.3f}"
        )
    print(
        f"\nEach pair's lift is recomputed on {PIECES} **disjoint** slices with the\n"
        "quantiles refitted inside each, so a slice is an independent estimate of\n"
        "the same quantity. `spread/effect` is the across-slice standard\n"
        "deviation over the whole-sample effect: **below 1 the quantity is\n"
        "estimable and above 1 it is a statement about which window was used.**\n"
        "`sign agrees` is the share of pairs where every slice agrees with the\n"
        "whole on direction, which is the weaker and more forgiving test."
    )


def survivorship_arm() -> None:
    print("\n" + "=" * 112)
    print("ARM 2  is the equity panel result measured on survivors")
    print("=" * 112)
    covered = []
    for path in sorted(screen.CACHE.glob(f"*.{screen.FRAME}.npz")):
        name = path.name[: -len(f".{screen.FRAME}.npz")]
        if name.count(".") != 1:
            continue
        got = screen.load(name)
        if got is not None:
            covered.append((len(got[0]), name))
    covered.sort(reverse=True)
    if len(covered) < GROUP + 4:
        print(f"  only {len(covered)} equities load; cannot split into groups")
        print(
            "\n**That is the finding.** The published arm took the best 21 by\n"
            "coverage because 21 is all that clear the 4,000-bar floor, so there\n"
            "is no second group to compare against and the result cannot be\n"
            "separated from survivorship with this cache. Bounding it needs\n"
            "delisted names, which are not here at all."
        )
        return
    print(f"{'group':<18}{'instruments':>13}{'bars, median':>14}{'median gain':>13}{'pooled t':>10}")
    for label, group in (
        ("long coverage", covered[:GROUP]),
        ("shorter coverage", covered[GROUP : GROUP * 2]),
    ):
        picked = [n for _, n in group]
        pool = {n: screen.load(n) for n in picked}
        pool = {k: v for k, v in pool.items() if v is not None}
        kept, matrix = panel.aligned(list(pool), pool)
        if kept is None:
            print(f"{label:<18}  not enough common spans")
            continue
        rows = panel.compare(kept, matrix, factor="nearest")
        if not rows:
            print(f"{label:<18}  nothing scored")
            continue
        print(
            f"{label:<18}{len(kept):>13}"
            f"{statistics.median(b for b, _ in group):>14.0f}"
            f"{statistics.median(r['gain'] for r in rows):>+13.4f}"
            f"{panel.pooled_t(rows):>10.2f}"
        )
    print(
        "\nIf the gain lives only in the long-coverage group it is survivorship.\n"
        "Delisted names are absent from the cache entirely, so this bounds the\n"
        "bias rather than removing it."
    )


def turkey_arm(names, series) -> None:
    import numpy as np

    print("\n" + "=" * 112)
    print("ARM 3  does a quiet training half make the fit worse out of sample")
    print("=" * 112)
    rows = []
    for name in names:
        got = screen.load(name)
        if got is None:
            continue
        values = got[1]
        half = len(values) // 2
        steps = np.diff(values)
        early, late = steps[:half], steps[half:]
        if early.std() <= 0 or late.std() <= 0:
            continue
        # A HAR fitted on the first half, scored on the second, against the
        # same model refitted on the second - the degradation a turkey suffers.
        from till_infinity.structures.statespace.nulls import har

        span = 100
        logs = []
        for at in range(span, len(values)):
            spread = float(np.std(steps[at - span : at]))
            if spread > 0:
                logs.append(math.log(spread))
        design, targets = har(logs)
        if len(design) < 400:
            continue
        cut = len(design) // 2
        first = np.column_stack([np.asarray(design[:cut]), np.ones(cut)])
        second = np.column_stack(
            [np.asarray(design[cut:]), np.ones(len(design) - cut)]
        )
        want_first = np.asarray(targets[:cut])
        want_second = np.asarray(targets[cut:])
        try:
            weights, *_ = np.linalg.lstsq(first, want_first, rcond=None)
            ideal, *_ = np.linalg.lstsq(second, want_second, rcond=None)
        except np.linalg.LinAlgError:
            continue
        out = float(np.mean((want_second - second @ weights) ** 2))
        best = float(np.mean((want_second - second @ ideal) ** 2))
        rows.append(
            {
                "name": name,
                "quiet": float(early.std() / late.std()),
                "degradation": out / best if best > 0 else float("nan"),
            }
        )
    if len(rows) < 6:
        print("  too few instruments")
        return
    print(f"{'instrument':<14}{'train/test sd':>15}{'degradation':>13}")
    rows.sort(key=lambda r: r["quiet"])
    for row in rows:
        print(
            f"{row['name']:<14}{row['quiet']:>15.3f}{row['degradation']:>13.4f}"
        )
    quiet = [r["quiet"] for r in rows]
    bad = [r["degradation"] for r in rows]
    spread_q, spread_b = statistics.pstdev(quiet), statistics.pstdev(bad)
    rho = (
        float(np.corrcoef(quiet, bad)[0, 1]) if spread_q > 0 and spread_b > 0 else float("nan")
    )
    print(
        f"\ncorrelation of degradation with the training half's relative"
        f" volatility: {rho:+.4f}"
    )
    print(
        "\n`train/test sd` below 1 means the training half was **quieter** than\n"
        "what followed, which is the turkey's position. A **negative**\n"
        "correlation is the turkey effect: the quieter the training half, the\n"
        "worse the fit does afterwards. A correlation near zero says the split\n"
        "discipline used throughout this session is not exposed to it."
    )


def main() -> None:
    print(f"{PIECES} disjoint slices, lift at {EDGES}, {GROUP} equities per group\n")
    names = [n for n in screen.TRADED if screen.load(n) is not None][:10]
    series = {n: screen.load(n) for n in names}
    tail_arm(names, series)
    survivorship_arm()
    turkey_arm(names, series)


if __name__ == "__main__":
    main()
