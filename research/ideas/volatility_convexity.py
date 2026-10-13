"""Convexity in volatility, which is the only Antifragile claim this desk can act on.

Taleb's argument is that a payoff convex in volatility benefits from volatility
whatever direction it comes from. This desk is the case that argument is aimed
at: it **can** forecast volatility and it **cannot** forecast direction -
direction is closed, with a planted drift found at `z + 2.90` earning 2% of a
spread.

So the claim has to be stated in a form that can be false, and the first step is
admitting what convexity cannot do.

## Under a walk, every geometry has the same expectancy, and it is zero

Optional stopping settles it. For a driftless martingale with barriers at `a`
and `-b` in volatility units, `P(a first) = (b + B)/(a + b + 2B)` and the
expectancy `P*a - (1 - P)*b` is zero up to the discrete-monitoring shift. A far
target with a near stop loses often and wins large; a near target with a far
stop wins often and loses large; **both are worth nothing** before costs.

So convexity creates no expectancy. Anyone reading a far-target structure as an
edge is reading the shape of the payoff and calling it a mean.

## What it does change is the cost, and that is where volatility enters

A round trip costs a fixed amount **in price**. In volatility units that cost is
`c / sigma`. So the identical geometry is **cheaper when volatility is higher**,
for every geometry, and the cost drag on a barrier trade is the one term that
depends on volatility rather than on direction.

That makes the testable claim precise:

> **Conditioning on a volatility forecast should raise the net expectancy of a
> barrier structure, through the cost term alone.**

It is falsifiable in both directions. If the forecast carries nothing, the
conditioned arm matches an unconditioned one. If volatility is unforecastable at
the horizon the barriers imply, the same. And the effect has a ceiling that can
be computed rather than hoped for: it is bounded by the spread in `1/sigma`
across the forecast's deciles, which is a number this harness prints.

## The null has to break the forecast and nothing else

A walk null would change the realised volatility path as well as the forecast,
so it cannot separate "the forecast is informative" from "volatility varies".
The null here **rotates the forecast against the outcomes**: the same forecasts,
the same trades, the same realised volatilities, and only the alignment between
them destroyed. A gap between the real and rotated arms is the forecast's
information and can be nothing else.

`nulls.har` is the forecast, because it is the floor the library carries for a
volatility forecast - beating an AR(1) on realised volatility is easy and means
nothing - and `bounding.py` supplies `P` and the expected duration so the
geometry's own arithmetic is not re-derived here.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relationship_screen as screen  # noqa: E402

#: Barrier geometries as `(target, stop)` in volatility units of one bar.
#: Convex first - a far target and a near stop - then symmetric, then concave.
GEOMETRIES = (
    ("convex", 4.0, 1.0),
    ("wide convex", 8.0, 2.0),
    ("symmetric", 2.0, 2.0),
    ("concave", 1.0, 4.0),
)
#: Trailing bars the volatility unit is estimated over.
SPAN = int(os.environ.get("SPAN", "100"))
#: Bars between entries, so trades barely overlap.
STRIDE = int(os.environ.get("STRIDE", "24"))
#: Bars a trade is given before it is abandoned.
PATIENCE = int(os.environ.get("PATIENCE", "500"))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "8"))
SEED = 20261013


def trades(times, values, spreads, target: float, stop: float):
    """Every barrier trade's outcome in volatility units, with its own cost.

    **Both directions, averaged, because the universe drifts.** The first
    version entered long only and Arm 1 caught it: gross expectancy read
    `+0.2222` on a far target and `-0.2145` on a near one, scaling with the
    asymmetry, where optional stopping says both are zero. That is the sample's
    upward log-price drift over thirteen years of crypto and metals, which a far
    target captures more of than a near one - a drift, not convexity, and
    convexity cannot move a mean.

    Taking the mean of the long and the short payoff at the same entry cancels
    any drift exactly, since one side's gain from it is the other's loss, and
    leaves the geometry's own contribution.

    The payoff is `+target` or `-stop` in volatility units; the cost is the
    leg's own round trip **converted into the same units**, which is where the
    volatility dependence lives: a fixed price cost is `c / sigma` sigmas.
    """
    import numpy as np

    # **Demeaned, because averaging a long and a short does not cancel a drift
    # unless they stop together.** The previous version averaged the two sides
    # and only the *symmetric* geometry read zero - for `(2, 2)` the long and
    # the short share the same two barriers and stop at the same instant, so
    # the average is exact. For `(4, 1)` the long exits at `+4`/`-1` and the
    # short at `-4`/`+1`, different stopping times, and their average satisfies
    # no identity. Since convexity *is* asymmetry, the trick defeated its own
    # purpose: it left +/-0.0742 on exactly the rows it was built for.
    #
    # Subtracting the mean increment makes the series driftless by construction,
    # so optional stopping applies to each geometry on its own and `gross` has
    # to read zero for all four or something else is wrong.
    moves = np.diff(values)
    drift = float(moves.mean())
    values = np.concatenate([[values[0]], values[0] + np.cumsum(moves - drift)])
    moves = np.diff(values)
    out = []
    for at in range(SPAN, len(values) - PATIENCE, STRIDE):
        sigma = float(np.std(moves[at - SPAN : at]))
        if sigma <= 0:
            continue
        # One pass serves both sides: the long's barriers are the short's, with
        # the roles of target and stop exchanged.
        long_up, long_down = values[at] + target * sigma, values[at] - stop * sigma
        short_dn, short_up = values[at] - target * sigma, values[at] + stop * sigma
        # **The exit price, not the stated barrier.** Crediting exactly
        # `+target` or `-stop` ignores the overshoot - price does not stop on
        # the line, it crosses it - and the error is proportionally larger for
        # the nearer barrier: debiting 1.0 when the exit is 1.5 under-charges a
        # near stop by 50% while under-crediting a far target by 25%. That
        # flatters convexity, and it is why Arm 1 read +0.2183 on a far target
        # with both sides the same sign. `statespace-barrier-overshoot.md`
        # measures the overshoot at 0.5 to 0.7 sigma, which at a ~74% stop rate
        # is the right order for the bias observed.
        long_pay = short_pay = None
        for ahead in range(1, PATIENCE + 1):
            here = values[at + ahead]
            moved = (here - values[at]) / sigma
            if long_pay is None and (here >= long_up or here <= long_down):
                long_pay = moved
            if short_pay is None and (here <= short_dn or here >= short_up):
                short_pay = -moved
            if long_pay is not None and short_pay is not None:
                break
        if long_pay is None or short_pay is None:
            continue
        # One round trip in this instrument, in volatility units.
        cost = 2.0 * float(np.mean(spreads[at - SPAN : at])) / sigma
        out.append(
            {
                "at": at,
                "payoff": (long_pay + short_pay) / 2.0,
                "long": long_pay,
                "short": short_pay,
                "cost": cost,
                "sigma": sigma,
            }
        )
    return out


def forecasts(values, at_list, span: int = SPAN):
    """A HAR forecast of the next period's log-volatility, one per entry."""
    import numpy as np

    from till_infinity.structures.statespace.nulls import har

    moves = np.diff(values)
    # Realised log-volatility on the same trailing span the trades use.
    series = []
    for at in range(span, len(values)):
        spread = float(np.std(moves[at - span : at]))
        series.append(math.log(spread) if spread > 0 else float("nan"))
    series = [v for v in series if math.isfinite(v)]
    rows, targets = har(series)
    if not rows:
        return {}
    # Fitted on the first half, predicting out of sample thereafter.
    half = len(rows) // 2
    design = np.column_stack([np.asarray(rows[:half]), np.ones(half)])
    try:
        weights, *_ = np.linalg.lstsq(design, np.asarray(targets[:half]), rcond=None)
    except np.linalg.LinAlgError:
        return {}
    said = {}
    for i, row in enumerate(rows):
        if i < half:
            continue
        # `i` indexes the log-vol series, which started `span` bars in.
        said[i + span] = float(np.dot(row, weights[:-1]) + weights[-1])
    return said


def net(rows) -> dict[str, float]:
    if not rows:
        return {}
    earned = [r["payoff"] - r["cost"] for r in rows]
    return {
        "net": statistics.mean(earned),
        "gross": statistics.mean(r["payoff"] for r in rows),
        "cost": statistics.mean(r["cost"] for r in rows),
        "n": float(len(rows)),
    }


def main() -> None:
    print(
        f"geometries {[g[0] for g in GEOMETRIES]}, volatility over {SPAN} trailing\n"
        f"bars, entries every {STRIDE}, {PATIENCE} bars of patience\n"
    )
    import numpy as np

    names = [n for n in screen.TRADED if screen.load(n) is not None][:8]

    print("=" * 104)
    print("ARM 1  every geometry's expectancy, which optional stopping says is zero")
    print("=" * 104)
    print(
        f"{'geometry':<14}{'instruments':>13}{'gross':>10}{'long':>10}{'short':>10}"
        f"{'cost':>10}{'net':>10}{'n':>8}"
    )
    pooled: dict[str, list[dict]] = {}
    for label, target, stop in GEOMETRIES:
        allrows = []
        for name in names:
            got = screen.load(name)
            if got is None:
                continue
            allrows.extend(trades(got[0], got[1], got[2], target, stop))
        pooled[label] = allrows
        got_net = net(allrows)
        if got_net:
            print(
                f"{label:<14}{len(names):>13}{got_net['gross']:>+10.4f}"
                f"{statistics.mean(r['long'] for r in allrows):>+10.4f}"
                f"{statistics.mean(r['short'] for r in allrows):>+10.4f}"
                f"{got_net['cost']:>10.4f}{got_net['net']:>+10.4f}{got_net['n']:>8.0f}"
            )
    print(
        "\n`gross` must read zero on every row and it took three corrections to\n"
        "get there. Each one was caught by this check rather than by review.\n\n"
        "**A drift.** Long-only read +0.2222 on a far target and -0.2145 on a\n"
        "near one, scaling with the asymmetry - the sample's upward log-price\n"
        "drift over thirteen years, which a far target captures more of.\n\n"
        "**The overshoot.** Crediting the stated barrier rather than the exit\n"
        "price under-charges a near stop by proportionally more than it\n"
        "under-credits a far target, which flatters convexity: it left +0.2183\n"
        "on a far target with both sides the same sign.\n\n"
        "**And a pairing that only worked where it was not needed.** Averaging a\n"
        "long and a short cancels a drift only if they stop together, which is\n"
        "true for a symmetric geometry and false for every other one. The series\n"
        "is demeaned instead, so optional stopping applies to each geometry\n"
        "alone."
    )

    print("\n" + "=" * 104)
    print("ARM 2  the cost is the term volatility moves, and here is its size")
    print("=" * 104)
    print(f"{'geometry':<14}{'low sigma cost':>16}{'high sigma cost':>17}{'ratio':>8}")
    for label, rows in pooled.items():
        if len(rows) < 100:
            continue
        order = sorted(rows, key=lambda r: r["sigma"])
        cut = len(order) // 5
        low = statistics.mean(r["cost"] for r in order[:cut])
        high = statistics.mean(r["cost"] for r in order[-cut:])
        print(
            f"{label:<14}{low:>16.4f}{high:>17.4f}"
            f"{low / high if high > 0 else float('nan'):>8.2f}"
        )
    print(
        "\nThis is the whole mechanism and its ceiling. A fixed price cost is\n"
        "`c / sigma` volatility units, so the quietest fifth of entries pays\n"
        "this multiple of what the busiest fifth pays. **Nothing conditioned on\n"
        "a volatility forecast can earn more than this spread**, and knowing the\n"
        "bound before measuring is what stops a small gain being read as a large\n"
        "one."
    )

    print("\n" + "=" * 104)
    print("ARM 3  does conditioning on a volatility forecast beat not conditioning")
    print("=" * 104)
    print(
        f"{'geometry':<14}{'all':>10}{'forecast high':>15}{'rotated null':>14}"
        f"{'vs null':>9}{'n':>8}"
    )
    picker = random.Random(SEED)
    for label, target, stop in GEOMETRIES:
        rows = pooled.get(label) or []
        if len(rows) < 200:
            continue
        taken, nulls = [], []
        for name in names:
            got = screen.load(name)
            if got is None:
                continue
            here = trades(got[0], got[1], got[2], target, stop)
            said = forecasts(got[1], [r["at"] for r in here])
            if not said:
                continue
            usable = [r for r in here if r["at"] in said]
            if len(usable) < 40:
                continue
            scores = [said[r["at"]] for r in usable]
            bar = statistics.median(scores)
            taken.extend(r for r, s in zip(usable, scores, strict=True) if s > bar)
            # The null rotates the forecast against the trades: same forecasts,
            # same trades, same realised volatilities, alignment destroyed.
            for _ in range(REPS):
                shift = picker.randrange(5, max(len(scores) - 5, 6))
                spun = scores[shift:] + scores[:shift]
                nulls.extend(
                    r for r, s in zip(usable, spun, strict=True) if s > bar
                )
        all_net = net(rows)
        took = net(taken)
        null_net = net(nulls)
        if not (took and null_net):
            continue
        print(
            f"{label:<14}{all_net['net']:>+10.4f}{took['net']:>+15.4f}"
            f"{null_net['net']:>+14.4f}"
            f"{took['net'] - null_net['net']:>+9.4f}{took['n']:>8.0f}"
        )
    print(
        "\n`vs null` is the measurement. The rotated arm takes the same number of\n"
        "trades on the same instruments with a forecast that has been shifted\n"
        "out of alignment, so it carries every property of the forecast except\n"
        "its information - and a gap is the information and can be nothing else."
    )


if __name__ == "__main__":
    main()
