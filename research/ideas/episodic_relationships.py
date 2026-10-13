"""A relationship that holds for a while and then breaks, which the screen cannot see.

`relationship_screen.py` fits one hedge ratio on the first half and takes **one**
Dickey-Fuller `t` over the whole second. That tests for a *time-invariant*
cointegration, and its answer was that no traded pair has one.

**That is not the same as no relationship, and the test is built so it cannot
tell the difference.** A pair that tracks tightly for three months and then
diverges contributes a reverting stretch and a trending stretch to the same
regression, and they cancel. The statistic is an average over regimes, so a
relationship that exists in some of them averages to nothing - and the more
cleanly it breaks, the more completely it cancels.

This is also the shape the desk's own machinery assumes. `relating.Relating`
carries the hedge ratio as a **state** rather than a constant, and
`switching.py`, `changepoint.py` and `hmm.py` all exist because the regime is
expected to change. A single global `t` is the one statistic that contradicts
every one of them.

## So the question changes

Not "is this pair cointegrated" but **"how much of the time is it reverting,
and is that enough time to act on"**. Three statistics, all per pair, all on
non-overlapping windows of the out-of-sample half:

* **share** - the fraction of windows that revert. A pair that reverts a third
  of the time has a relationship; the global `t` would report nothing.
* **persistence** - `P(next window reverts | this one did) - P(next reverts)`.
  **This is the one that decides whether any of it is tradeable.** An episodic
  relationship whose episodes are unpredictable is not an edge, it is a
  description. Reversion has to be *persistent* to be actionable, because the
  position is taken after the episode is observed.
* **divergence after reversion** - `P(next window trends | this one reverted)`.
  Elevated against the null, a reverting pair is one that is about to break,
  which is how a stat-arb book fails rather than underperforms.

## The null gets the identical treatment, which is the whole discipline

A rolling maximum over forty windows finds reversion in noise, and run lengths
in noise are longer than intuition says. So every statistic above is also
computed on the **two-real-leg block-shuffled null** from `relationship_screen`
- a traded instrument against another traded instrument's returns in day-long
blocks, scrambled - which keeps both legs' tails exactly (that partition set the
`-4.07` bar where synthetics set `-3.46`) and destroys any relationship between
them.

**And the comparison is between distributions, not extremes.** The earlier
screen took the minimum `t` over 553 null pairs, which is a severe multiplicity
correction and a blunt instrument: it asks whether the best pair is
extraordinary. The episodic question is different - whether traded pairs spend
*more* of their time reverting than unrelated ones do - and that is a shift in
the middle of the distribution, which a comparison of extremes has almost no
power to see.

## Two ratio arms, neither of which may peek

* **fixed** - the ratio from the first half, held throughout. A relationship
  whose ratio drifts will look like divergence here, which is the conservative
  reading and is exactly the failure being asked about.
* **rolling** - the ratio fitted on window `k-1` and applied to window `k`.
  Strictly causal, so it is a genuine test, and it allows a slowly drifting
  relationship to stay detected. This is `Relating`'s premise without the
  absorption defect that made the live arm read `-29`.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from itertools import combinations

import relationship_screen as screen

#: Bars per window. At 1h, 250 is about five weeks - long enough for a
#: Dickey-Fuller `t` to mean something and short enough that forty of them fit
#: in the out-of-sample half.
WINDOW = int(os.environ.get("WINDOW", "250"))
#: `t` below this counts the window as reverting, above `+TREND` as trending.
REVERTS = float(os.environ.get("REVERTS", "-2.0"))
TRENDS = float(os.environ.get("TRENDS", "0.0"))
#: Repetitions of the shuffled null, for a comparable number of pairs.
REPS = int(os.environ.get("REPS", "3"))
SEED = 20261013


def least_squares(x, y) -> float:
    """The ratio `b` in `y = a + b x`, by the normal equations."""
    import numpy as np

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    varx = float(((x - x.mean()) ** 2).sum())
    if varx <= 0:
        return 0.0
    return float(((x - x.mean()) * (y - y.mean())).sum() / varx)


def windows(left, right):
    """Per-window `t` for both ratio arms, on the out-of-sample half.

    Returns `(fixed, rolling)`, each a list of `t` in window order, so the
    adjacency the persistence statistics need is preserved.
    """
    import numpy as np

    got = screen.align(left, right)
    if got is None:
        return None, None
    _, a, b, _, _ = got
    half = len(a) // 2
    if half < WINDOW:
        return None, None
    held = least_squares(a[:half], b[:half])

    out_a, out_b = a[half:], b[half:]
    count = len(out_a) // WINDOW
    if count < 4:
        return None, None

    fixed, rolling = [], []
    for k in range(count):
        lo, hi = k * WINDOW, (k + 1) * WINDOW
        fixed.append(screen.dickey_fuller(out_b[lo:hi] - held * out_a[lo:hi])[1])
        # The rolling arm may only use ratios fitted strictly before `lo`.
        if k == 0:
            earlier = least_squares(a[:half], b[:half])
        else:
            earlier = least_squares(out_a[lo - WINDOW : lo], out_b[lo - WINDOW : lo])
        rolling.append(screen.dickey_fuller(out_b[lo:hi] - earlier * out_a[lo:hi])[1])
    return (
        [t for t in fixed if math.isfinite(t)],
        [t for t in rolling if math.isfinite(t)],
    )


def statistics_for(ts) -> dict[str, float] | None:
    """`share`, `persistence` and `breaks` from one pair's window sequence."""
    if len(ts) < 4:
        return None
    reverting = [t < REVERTS for t in ts]
    trending = [t > TRENDS for t in ts]
    share = sum(reverting) / len(reverting)

    after_reverting = [reverting[k + 1] for k in range(len(ts) - 1) if reverting[k]]
    broke = [trending[k + 1] for k in range(len(ts) - 1) if reverting[k]]
    base = sum(reverting[1:]) / max(len(ts) - 1, 1)
    base_trend = sum(trending[1:]) / max(len(ts) - 1, 1)

    run, longest = 0, 0
    for flag in reverting:
        run = run + 1 if flag else 0
        longest = max(longest, run)

    return {
        "windows": float(len(ts)),
        "share": share,
        # Lift over the unconditional rate, so a pair that always reverts
        # scores zero persistence rather than a perfect one.
        "persistence": (
            sum(after_reverting) / len(after_reverting) - base
            if after_reverting
            else float("nan")
        ),
        "breaks": (sum(broke) / len(broke) - base_trend if broke else float("nan")),
        "longest": float(longest),
        "median_t": statistics.median(ts),
    }


def summarise(label: str, rows: list[dict[str, float]], keys) -> None:
    print(f"{label:<34}{len(rows):>7,}", end="")
    for key in keys:
        values = [r[key] for r in rows if math.isfinite(r[key])]
        print(f"{statistics.median(values):>+12.4f}" if values else f"{'-':>12}", end="")
    print()


def tail(rows: list[dict[str, float]], key: str, share: float) -> float:
    """The `share` quantile from the top of `key`, for a one-sided bar."""
    values = sorted(r[key] for r in rows if math.isfinite(r[key]))
    if not values:
        return float("nan")
    return values[min(int(len(values) * share), len(values) - 1)]


#: The bar the single-`t` screen was judged against, from the two-real-leg
#: block-shuffled null in `research/docs/statespace-relationship-screen.md`.
BAR = float(os.environ.get("BAR", "-4.07"))


def planted(frac: float, seed: int, bars: int = 8000):
    """A pair tied for `frac` of its out-of-sample life, then broken.

    The relationship is real and strong while it lasts - the two legs differ by
    bounded noise - and afterwards the difference is a free walk. This is the
    shape the screen was never built to see.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    half = bars // 2
    when = np.arange(bars, dtype=float)
    lead = np.cumsum(rng.standard_normal(bars))
    kept = int(half + half * frac)
    follow = lead + np.concatenate(
        [rng.standard_normal(kept) * 0.5, np.cumsum(rng.standard_normal(bars - kept))]
    )
    zeros = np.zeros(bars)
    return (when, lead, zeros), (when, follow, zeros)


def planted_arm(trials: int = 12) -> None:
    """How much of a real relationship has to survive for the screen to see it."""
    print("\n" + "=" * 104)
    print("ARM 0  what the single-t screen misses, measured on a planted relationship")
    print("=" * 104)
    print(
        "Each row is a pair genuinely tied for that share of its out-of-sample\n"
        f"life and a free walk afterwards, over {trials} seeds. The screen gets one\n"
        f"ratio and one t; this harness gets {WINDOW}-bar windows of the same data.\n"
    )
    print(
        f"{'tied share':>11}{'single t':>11}{f'passes {BAR}':>15}"
        f"{'share':>9}{'median t':>10}{'longest':>9}"
    )
    for frac in (1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1):
        singles, shares, medians, longest, passed = [], [], [], [], 0
        for seed in range(trials):
            left, right = planted(frac, seed)
            one = screen.screen(left, right)
            fixed, _ = windows(left, right)
            if one is None or fixed is None:
                continue
            got = statistics_for(fixed)
            if got is None:
                continue
            singles.append(one["split_t"])
            shares.append(got["share"])
            medians.append(got["median_t"])
            longest.append(got["longest"])
            passed += one["split_t"] < BAR
        if not singles:
            continue
        print(
            f"{frac:>11.1f}{statistics.median(singles):>+11.2f}"
            f"{f'{passed}/{len(singles)}':>15}{statistics.median(shares):>9.3f}"
            f"{statistics.median(medians):>+10.2f}{statistics.median(longest):>9.0f}"
        )
    print(
        "\n**A relationship does not have to be weak to be missed, only finite.**\n"
        "The windowed statistics degrade smoothly as the tied share falls; the\n"
        "single t has a cliff, and below it the pair is reported as unrelated\n"
        "while the windows still read it clearly."
    )


def main() -> None:
    print(
        f"windows of {WINDOW} bars on the out-of-sample half, reverting at "
        f"t < {REVERTS}, trending at t > {TRENDS}\n"
    )
    planted_arm()
    live = [name for name in screen.TRADED if screen.load(name) is not None]
    series = {name: screen.load(name) for name in live}
    print(f"{len(live)} traded instruments -> {len(live) * (len(live) - 1) // 2} pairs")

    real: dict[str, list[dict[str, float]]] = {"fixed": [], "rolling": []}
    for a, b in combinations(live, 2):
        fixed, rolling = windows(series[a], series[b])
        if fixed is None:
            continue
        for arm, ts in (("fixed", fixed), ("rolling", rolling)):
            got = statistics_for(ts)
            if got is not None:
                got["pair"] = f"{a}/{b}"  # type: ignore[assignment]
                real[arm].append(got)

    rng = random.Random(SEED)
    null: dict[str, list[dict[str, float]]] = {"fixed": [], "rolling": []}
    for _ in range(REPS):
        for a, b in combinations(live, 2):
            fixed, rolling = windows(
                series[a], screen.block_shuffled(series[b], rng)
            )
            if fixed is None:
                continue
            for arm, ts in (("fixed", fixed), ("rolling", rolling)):
                got = statistics_for(ts)
                if got is not None:
                    null[arm].append(got)

    keys = ("share", "persistence", "breaks", "longest", "median_t")
    print("\n" + "=" * 104)
    print("ARM 1  do traded pairs spend more of their time reverting than unrelated ones")
    print("=" * 104)
    print(f"{'':<34}{'pairs':>7}" + "".join(f"{k:>12}" for k in keys))
    for arm in ("fixed", "rolling"):
        summarise(f"traded, {arm} ratio", real[arm], keys)
        summarise(f"  block-shuffled null, {arm}", null[arm], keys)

    print("\n" + "=" * 104)
    print("ARM 2  and is any of it persistent enough to act on")
    print("=" * 104)
    print(
        "`share` says a relationship is present some of the time. `persistence`\n"
        "says the episode can be seen before it is over, which is the only form\n"
        "a desk can trade: the position is taken after the window is observed.\n"
        "A share above the null with persistence at the null is a description.\n"
    )
    for arm in ("fixed", "rolling"):
        for key in ("share", "persistence", "breaks"):
            bar = tail(null[arm], key, 0.95)
            beat = sum(
                1
                for r in real[arm]
                if math.isfinite(r[key]) and r[key] > bar
            )
            expected = 0.05 * len(real[arm])
            print(
                f"{arm:<9}{key:<13}null 95th pct {bar:>+8.4f}   "
                f"{beat:>3} of {len(real[arm])} above it, {expected:.1f} expected"
            )

    print("\n" + "=" * 104)
    print("ARM 3  the pairs that spend the most time reverting, rolling ratio")
    print("=" * 104)
    rows = sorted(real["rolling"], key=lambda r: -r["share"])
    bar_share = tail(null["rolling"], "share", 0.95)
    bar_persist = tail(null["rolling"], "persistence", 0.95)
    print(
        f"{'pair':<18}{'windows':>9}{'share':>9}{'persistence':>13}"
        f"{'breaks':>10}{'longest':>9}{'median t':>10}{'beats':>18}"
    )
    for got in rows[:15]:
        marks = []
        if got["share"] > bar_share:
            marks.append("share")
        if math.isfinite(got["persistence"]) and got["persistence"] > bar_persist:
            marks.append("persistence")
        print(
            f"{got['pair']:<18}{got['windows']:>9.0f}{got['share']:>9.3f}"
            f"{got['persistence']:>+13.4f}{got['breaks']:>+10.4f}"
            f"{got['longest']:>9.0f}{got['median_t']:>+10.2f}"
            f"{' + '.join(marks) or '':>18}"
        )


if __name__ == "__main__":
    main()
