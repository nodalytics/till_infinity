"""Load a universe, find the relationships, and know which ones are real.

`relating.Relating` already carries a hedge ratio as a **state** rather than a
fitted constant, so the per-pair machinery exists. What was missing is the
search: a stat-arb state space is supposed to be handed a set of assets and
come back with the pairs, not be told which pair to test.

This is that search. The hard part is not finding candidates.

## Screening N squared pairs guarantees spurious ones

28 traded instruments is 378 pairs; at the conventional 5% that is **19
"significant" relationships from nothing at all.** Every cointegration screen
ever run has this problem and most of them answer it with a Dickey-Fuller
critical value, which assumes the series are independent random walks and says
nothing about the screen's own multiplicity.

**The Deriv synthetics look like the answer, and the assumption has to be
checked rather than made.** The first version of this said they are "generated
by separate engines from independent random streams" and used every
synthetic-by-synthetic pair as the null. That is probably false in at least
three ways:

* `DEX_600_UP_Index` and `DEX_600_DOWN_Index` are **named as a pair** and are
  very likely mirror constructions - a perfect relationship by design;
* `Volatility_10/25/50/75/100_Index` are the same process at different
  volatilities and may be driven by **one scaled random stream**;
* `Volatility_75_Index` and `Volatility_75_1s_Index` are plausibly the same
  path sampled at two rates.

Any of those would put a strong **engineered** relationship inside the null -
and because the bar is the *most* reverting null pair, a single mirror pair
would set a threshold nothing could beat and the screen would report no real
relationships while looking rigorous.

So the null is **partitioned and printed**: cross-family pairs, same-family
pairs, and the ten most reverting null pairs by name. If the extremes are all
same-family, the independence assumption is dead and visible rather than
load-bearing and invisible.

## The null has to share the candidates' tails, and independence is not it

The first version of this reached for a traded-against-synthetic null and
justified it as "the only one with guaranteed independence". **That was wrong.**
Two cross-family synthetics are independent of each other exactly as a
synthetic is independent of EURUSD; swapping a leg changes nothing about
independence.

What it changes is the **leg distribution**, and that is what sets a
Dickey-Fuller threshold. Measured on this universe: the 20 traded instruments
have median return kurtosis **20.07**, the 36 synthetics **3.19** - Gaussian is
3.0. **The synthetics are Gaussian-tailed and the candidates are not, by a
factor of six**, so a synthetic-only null judges them against the wrong
reference however independent it is.

So the null is partitioned by **how many legs are real markets**, which is the
variable, rather than by independence, which is constant:

* **0 real legs** - synthetic against synthetic, across families;
* **1 real leg** - traded against synthetic, which is still a cross-family
  independent pair and not a different kind of null;
* **2 real legs** - traded against **another traded instrument's returns in
  day-long blocks, scrambled.** A block shuffle is a permutation, so each leg
  keeps its tails *exactly* and its within-day clustering, while any
  relationship between the legs is destroyed. This is the only partition whose
  legs are distributed like the pairs being screened.

The cross-universe arm also runs in the other direction. A traded-against-
synthetic pair showing a genuine relationship would mean either that Deriv's
engine is seeded from market data - a finding about Deriv - or that the screen
is broken. Either is worth knowing, and neither is testable without the arm.

## The live hedge ratio manufactures the statistic, and the null proves it

`Relating` adapts its ratio to every reading, so the first version of this used
the ratio **as of the previous bar** - the only version a desk could have held,
and what the pair work established.

**It is not enough, and the null is what showed it.** With a lagged live ratio
the screen reads `DF t = -29.39` between `Boom_50_Index` and
`Skew_Step_Index_4_Down`, two unrelated generated processes, while the best
real-market pair reads `-18.19` and the textbook augmented-Dickey-Fuller
critical value is about `-3.4`. **The pipeline produces more apparent
cointegration from noise than from markets.**

The mechanism is that one bar is no lag at all: the ratio barely moves in a
bar, so it still absorbs whatever the two series jointly do and leaves a
residual that looks stationary by construction.

So both arms are run:

* **`live`** - the lagged adaptive ratio, kept because it is what a desk
  holding `Relating` would actually have, and because its null is the finding;
* **`split`** - one ratio fitted by least squares on the **first half** and
  applied unchanged to the second, which is a genuine out-of-sample test and
  cannot absorb anything it has not seen.

If `split`'s null collapses toward the textbook value, the live ratio was the
whole effect and the screen only works in the split form.

## What is reported

A Dickey-Fuller `t` on the spread - reverting is negative, and more negative is
faster - plus the half-life in bars and the share of the two legs' spreads the
reversion has to clear. A pair that reverts beautifully over a range smaller
than its own round-trip cost is not a trade.

## What the numbers said

The null partition came back clean: the ten most reverting null pairs are all
**cross**-family, so the engineered-pair worry above did not bite, and the
mirror and scaled-stream families are not what sets the bar.

The live ratio was the whole effect - it reads past `-28` between processes with
no connection, and the split form collapses to the textbook `-3.4` as predicted.
On the split arm the threshold then moves with the tails:

| real legs | pairs | split best | 1st pct | median |
|-----------|------:|-----------:|--------:|-------:|
| 0, synthetic x synthetic        | 553 | -3.46 | -3.16 | -1.60 |
| 1, traded x synthetic           | 720 | -3.94 | -3.47 | -1.76 |
| **2, traded x shuffled traded** | 570 | **-4.07** | -3.79 | -2.17 |

**Monotone in the number of real legs, and the median shifts too** - so this is
the distribution moving rather than one lucky extreme. Independence is identical
across all three rows, which is what rules it out as the cause.

Against the bar whose legs match the candidates: **0 of 190 traded pairs beat
-4.07**, where 17 beat the synthetic-only -3.46. The best traded pair on the
honest statistic is `USDJPY/XAGUSD` at `-3.37`, which clears none of the three.

The live arm runs the other way across the partitions - `-29.39`, `-28.31`,
`-18.88` - which confirms the first defect a second time. A shuffled leg leaves
an adaptive ratio no co-movement to absorb, so the live statistic deflates by 10
points of `t` once the joint dynamics are gone. It was never cointegration.

The reverse reading is a null too: no traded-against-synthetic pair shows a
relationship, so Deriv's engine shows no sign of being seeded from market data.
The synthetics stay usable as controls - for **structure**, with the caveat that
at kurtosis 3.19 they are a poor control for **tails**.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from itertools import combinations
from pathlib import Path

from till_infinity.structures.statespace.relating import Relating

HOUR = 3600.0
SEED = 20261013

#: The live universe. FX majors and crosses, metals, crypto - anything whose
#: price is set by an auction somebody else is also trading.
TRADED = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "NZDUSD", "AUDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "EURCHF", "EURAUD", "AUDJPY", "CHFJPY",
    "USDCNH", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "SOLUSD",
)
#: The null universe: independent generators, so every pair here is a draw from
#: "no relationship" through the identical pipeline.
GENERATED_PREFIXES = (
    "Volatility_", "Jump_", "Boom_", "Crash_", "Step_", "Range_Break_",
    "DEX_", "Drift_Switch_", "Multi_Step_", "Skew_Step_",
)

FRAME = os.environ.get("FRAME", "1h")
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "20000"))
#: Minimum overlapping bars before a pair is scored at all.
LEAST = int(os.environ.get("LEAST", "4000"))
#: Repetitions of the block-shuffled arm, so its draw count is comparable
#: to the other two partitions rather than a tenth of them.
REPS = int(os.environ.get("REPS", "3"))
#: Cap on the null universe, so the screen stays inside a sensible runtime.
NULLS = int(os.environ.get("NULLS", "40"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def family(name: str) -> str:
    """Which generator family a synthetic belongs to.

    Pairs inside one family are **not** independent draws: `DEX_600_UP` and
    `DEX_600_DOWN` are named as a pair, and `Volatility_10` through
    `Volatility_100` are one process at different volatilities. So the null has
    to be built across families, and the within-family distribution is the
    diagnostic that says whether that mattered.
    """
    for prefix in GENERATED_PREFIXES:
        if name.startswith(prefix):
            return prefix.rstrip("_")
    return "other"


def universe(frame: str) -> list[str]:
    """Every synthetic in the cache for `frame`, by prefix."""
    found = []
    for path in sorted(CACHE.glob(f"*.{frame}.npz")):
        name = path.name[: -len(f".{frame}.npz")]
        if any(name.startswith(prefix) for prefix in GENERATED_PREFIXES):
            found.append(name)
    return found[:NULLS]


def point_size(closes) -> float:
    """The quote grid the prices sit on, inferred from the prices themselves.

    **The `spread` column is in integer points, not price.** EURUSD carries a
    median raw spread of `2.0` at a close near `1.12`, and dividing one by the
    other reads a 476% round trip. Worse, the error scales with the price
    level, so a JPY pair quoted near 133 was penalised a hundred times less
    than a EUR pair near 1.1 - which silently reorders every pair by cost
    rather than merely inflating them all.

    The grid is recoverable without a hard-coded table: the smallest non-zero
    gap between consecutive closes *is* one point, rounded to the nearest power
    of ten to absorb binary representation error.
    """
    import numpy as np

    steps = np.abs(np.diff(np.asarray(closes, dtype=float)))
    steps = steps[steps > 0]
    if not len(steps):
        return float("nan")
    return float(10.0 ** round(math.log10(float(steps.min()))))


def load(name: str, frame: str = FRAME):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
        spread = (
            np.asarray(bundle["spread"], dtype=float)[order]
            if "spread" in bundle
            else np.zeros_like(closes)
        )
    keep = (closes > 0) & (times >= SINCE)
    times, closes, spread = times[keep], closes[keep], spread[keep]
    if len(times) > LIMIT:
        times, closes, spread = times[-LIMIT:], closes[-LIMIT:], spread[-LIMIT:]
    if len(times) < LEAST:
        return None
    # Relative spread, so it is comparable across instruments priced
    # differently. `spread` is in points, so it needs the quote grid first.
    point = point_size(closes)
    return times, np.log(closes), spread * point / closes


def block_shuffled(series, rng, blocks: int = 24):
    """One leg's own returns, reordered in day-long blocks, on its own clock.

    A traded instrument against a **shuffled traded instrument** keeps a real
    market's fat tails and its within-block clustering on *both* legs while
    destroying any relationship between them.

    This is the null for the pairs actually being screened, and the synthetic
    arms cannot be. Swapping a leg for a near-Gaussian process changes the leg
    distribution, and **the leg distribution is what sets the threshold** - so
    a null with fewer real legs than the candidate measures the wrong quantity,
    however independent it is.
    """
    import numpy as np

    times, values, spread = series
    steps = np.diff(values)
    pieces = np.split(steps, range(blocks, len(steps), blocks))
    rng.shuffle(pieces)
    rebuilt = np.empty_like(values)
    rebuilt[0] = values[0]
    rebuilt[1:] = values[0] + np.cumsum(np.concatenate(pieces))
    return times, rebuilt, spread


def align(left, right):
    """The two series on their common timestamps.

    **Not a merge on position.** Instruments keep different sessions and
    holidays, so the nth bar of one is not the nth bar of the other, and
    zipping them would silently compare Tuesday with Wednesday on any pair
    whose venues differ.
    """
    import numpy as np

    lt, lv, ls = left
    rt, rv, rs = right
    common, li, ri = np.intersect1d(lt, rt, return_indices=True)
    if len(common) < LEAST:
        return None
    return common, lv[li], rv[ri], ls[li], rs[ri]


def dickey_fuller(series) -> tuple[float, float]:
    """`(slope, t)` from `d(x) = a + b x`. Reverting is `b < 0`."""
    import numpy as np

    values = np.asarray(series, dtype=float)
    if len(values) < 200:
        return 0.0, 0.0
    left = values[:-1]
    steps = np.diff(values)
    mx, my = float(np.mean(left)), float(np.mean(steps))
    den = float(np.sum((left - mx) ** 2))
    if den <= 0:
        return 0.0, 0.0
    slope = float(np.sum((left - mx) * (steps - my))) / den
    residual = steps - (my + slope * (left - mx))
    spread = float(np.sum(residual**2)) / max(len(residual) - 2, 1)
    error = math.sqrt(spread / den) if spread > 0 else 0.0
    return slope, (slope / error if error > 0 else 0.0)


def screen(left, right) -> dict | None:
    """One pair: the lagged-ratio spread, its reversion, and what it must clear."""
    import numpy as np

    got = align(left, right)
    if got is None:
        return None
    times, lv, rv, ls, rs = got

    unit = float(np.std(np.diff(lv))) or 1e-6
    hedge = Relating(legs=1, centre=True)
    ratios = np.zeros(len(times))
    for i, when in enumerate(times):
        # **The ratio as of the previous bar**, recorded before this reading is
        # folded in, so the spread could have been formed at the time.
        ratios[i] = hedge.ratio
        hedge.predict(float(when))
        hedge.update(float(lv[i]), unit, float(when), against=float(rv[i]))

    live = lv - ratios * rv
    # Drop the warm-up, where the ratio is still at its starting value.
    start = max(len(live) // 10, 200)
    live = live[start:]
    if len(live) < LEAST // 2:
        return None

    # **The split arm.** One ratio from the first half by least squares, held
    # fixed over the second, which is the only form that cannot absorb what it
    # has not seen. Centred, because an uncentred fit carries the level and
    # these series are not cointegrated in levels.
    half = len(times) // 2
    x, y = rv[:half], lv[:half]
    mx, my = float(np.mean(x)), float(np.mean(y))
    den = float(np.sum((x - mx) ** 2))
    fixed = float(np.sum((x - mx) * (y - my))) / den if den > 0 else 0.0
    split = lv[half:] - fixed * rv[half:]

    slope, t = dickey_fuller(live)
    split_slope, split_t = dickey_fuller(split)
    wander = float(np.std(live))
    # What a round trip costs, in the same units as the spread's own range:
    # both legs' relative spreads, scaled by the hedge ratio on the second.
    ratio = float(np.median(ratios[start:]))
    cost = float(np.mean(ls[start:])) + abs(ratio) * float(np.mean(rs[start:]))
    return {
        "n": len(live),
        "t": t,
        "split_t": split_t,
        "fixed": fixed,
        "split_half_life": (math.log(2.0) / -split_slope if split_slope < 0 else math.inf),
        "ratio": ratio,
        "ratio_sd": float(np.std(ratios[start:])),
        "half_life": (math.log(2.0) / -slope if slope < 0 else math.inf),
        "wander": wander,
        # Reversion is only tradeable if the spread's own range exceeds the
        # round trip. Below 1 is not a trade however good the `t` is.
        "range_over_cost": (wander / cost if cost > 0 else float("nan")),
    }


def main() -> None:
    print(
        f"frame {FRAME}, up to {LIMIT:,} bars, pairs aligned on common timestamps\n"
        "Dickey-Fuller `t` on the spread: reverting is negative and more\n"
        "negative is faster. The hedge ratio is the one as of the **previous**\n"
        "bar. 'range/cost' is the spread's own standard deviation over a round\n"
        "trip in both legs - **below 1 is not a trade whatever the t.**\n"
    )

    live = [name for name in TRADED if load(name) is not None]
    nulls = [name for name in universe(FRAME) if load(name) is not None]
    print(f"{len(live)} traded instruments -> {len(live) * (len(live) - 1) // 2} pairs")
    print(f"{len(nulls)} independent generators -> {len(nulls) * (len(nulls) - 1) // 2} null pairs\n")

    series = {name: load(name) for name in live + nulls}

    print("=" * 104)
    print("ARM 1  the null, and whether it is actually a null")
    print("=" * 104)
    scored = []
    for a, b in combinations(nulls, 2):
        got = screen(series[a], series[b])
        if got is not None and math.isfinite(got["t"]):
            got["pair"] = f"{a}/{b}"
            got["same"] = family(a) == family(b)
            scored.append(got)
    if not scored:
        print("  no null pairs scored")
        return
    scored.sort(key=lambda r: r["t"])

    print("the ten most reverting null pairs - if these are same-family, the")
    print("independence assumption this screen rested on is wrong:\n")
    print(f"{'pair':<46}{'DF t':>8}{'family':>10}{'range/cost':>12}")
    for got in scored[:10]:
        print(
            f"{got['pair']:<46}{got['t']:>+8.2f}"
            f"{'SAME' if got['same'] else 'cross':>10}{got['range_over_cost']:>12.1f}"
        )

    cross = sorted(r["t"] for r in scored if not r["same"])
    same = sorted(r["t"] for r in scored if r["same"])
    cross_split = sorted(r["split_t"] for r in scored if not r["same"])
    print(f"\n{len(cross):,} cross-family null pairs, {len(same):,} same-family")
    print(
        f"{'partition':<22}{'best':>10}{'1st pct':>10}{'median':>10}"
    )
    for label, values in (
        ("cross-family, live", cross),
        ("same-family, live", same),
        ("cross-family, SPLIT", cross_split),
    ):
        if not values:
            continue
        print(
            f"{label:<22}{values[0]:>+10.2f}"
            f"{values[max(len(values) // 100, 0)]:>+10.2f}"
            f"{statistics.median(values):>+10.2f}"
        )
    print(
        "\nThe textbook augmented-Dickey-Fuller 1% value is about -3.4. A null\n"
        "far past it is the screen manufacturing its own statistic; a null near\n"
        "it is a screen that works."
    )
    if not cross:
        print("  no cross-family pairs; cannot form a null")
        return
    # Every arm below is independent by construction, exactly as the cross-
    # family pairs above are. What varies is how many legs are real markets.
    mixed, mixed_split = [], []
    for a in live:
        for b in nulls:
            got = screen(series[a], series[b])
            if got is None or not math.isfinite(got["t"]):
                continue
            mixed.append(got["t"])
            if math.isfinite(got["split_t"]):
                mixed_split.append(got["split_t"])
    mixed.sort()
    mixed_split.sort()

    rng = random.Random(SEED)
    shuffled, shuffled_split = [], []
    for _ in range(REPS):
        for a, b in combinations(live, 2):
            got = screen(series[a], block_shuffled(series[b], rng))
            if got is None or not math.isfinite(got["t"]):
                continue
            shuffled.append(got["t"])
            if math.isfinite(got["split_t"]):
                shuffled_split.append(got["split_t"])
    shuffled.sort()
    shuffled_split.sort()

    print(
        f"\nOne null, partitioned by how many legs are real markets. All three\n"
        f"are independent by construction - synthetic against synthetic across\n"
        f"families, synthetic against a market its engine never sees, and a\n"
        f"market against another market's blocks in a scrambled order.\n"
    )
    print(f"{'partition':<34}{'pairs':>8}{'best':>10}{'1st pct':>10}{'median':>10}")
    for label, values in (
        ("0 real legs, live", cross),
        ("1 real leg, live", mixed),
        ("2 real legs, live", shuffled),
        ("0 real legs, SPLIT", cross_split),
        ("1 real leg, SPLIT", mixed_split),
        ("2 real legs, SPLIT", shuffled_split),
    ):
        if not values:
            continue
        print(
            f"{label:<34}{len(values):>8,}{values[0]:>+10.2f}"
            f"{values[max(len(values) // 100, 0)]:>+10.2f}"
            f"{statistics.median(values):>+10.2f}"
        )
    print(
        "\n**The two-real-leg split null is the bar**, because it is the only\n"
        "partition whose legs are distributed like the pairs being screened.\n"
        "If the threshold moves with the number of real legs, independence was\n"
        "never the variable - the tails were."
    )

    cuts = {
        "best (min)": cross[0],
        "split best": cross_split[0] if cross_split else float("nan"),
        "mixed split best": mixed_split[0] if mixed_split else float("nan"),
        "shuffled split best": (
            shuffled_split[0] if shuffled_split else float("nan")
        ),
    }
    print("\n" + "=" * 104)
    print("ARM 2  the traded universe, ranked")
    print("=" * 104)
    rows = []
    for a, b in combinations(live, 2):
        got = screen(series[a], series[b])
        if got is None or not math.isfinite(got["t"]):
            continue
        got["pair"] = f"{a}/{b}"
        rows.append(got)
    rows.sort(key=lambda r: r["t"])
    print(
        f"{'pair':<18}{'live t':>8}{'SPLIT t':>9}{'ratio':>8}{'fixed':>8}"
        f"{'half-life':>11}{'range/cost':>12}{'beats':>8}"
    )
    for got in rows[:20]:
        wins = got["split_t"] < cuts["split best"]
        print(
            f"{got['pair']:<18}{got['t']:>+8.2f}{got['split_t']:>+9.2f}"
            f"{got['ratio']:>+8.3f}{got['fixed']:>+8.3f}"
            + (
                f"{got['split_half_life']:>11.0f}"
                if math.isfinite(got["split_half_life"])
                else f"{'inf':>11}"
            )
            + f"{got['range_over_cost']:>12.1f}{'yes' if wins else '':>8}"
        )
    live_beat = sum(1 for r in rows if r["t"] < cuts["best (min)"])
    split_beat = sum(1 for r in rows if r["split_t"] < cuts["split best"])
    mixed_beat = sum(1 for r in rows if r["split_t"] < cuts["mixed split best"])
    print(
        f"\nlive arm:       {live_beat:>3} of {len(rows)} beat the synthetic live null "
        f"({cuts['best (min)']:+.2f})"
    )
    print(
        f"SPLIT arm:      {split_beat:>3} of {len(rows)} beat the synthetic split null "
        f"({cuts['split best']:+.2f})"
    )
    print(
        f"1 real leg:     {mixed_beat:>3} of {len(rows)} beat the one-real-leg split "
        f"null ({cuts['mixed split best']:+.2f})"
    )
    shuffled_beat = sum(
        1 for r in rows if r["split_t"] < cuts["shuffled split best"]
    )
    print(
        f"2 real legs:    {shuffled_beat:>3} of {len(rows)} beat the two-real-leg "
        f"split null ({cuts['shuffled split best']:+.2f}) - THE BAR"
    )

    print("\n" + "=" * 104)
    print("ARM 3  the pair that was asked about")
    print("=" * 104)
    for want in (("XAUUSD", "USDCHF"), ("XAUUSD", "XAGUSD"), ("USDJPY", "XAGUSD")):
        found = next(
            (r for r in rows if r["pair"] in (f"{want[0]}/{want[1]}", f"{want[1]}/{want[0]}")),
            None,
        )
        if found is None:
            print(f"{want[0]}/{want[1]}: not scored")
            continue
        by_split = sorted(rows, key=lambda r: r["split_t"])
        print(
            f"{found['pair']:<18}live t {found['t']:+.2f} (rank "
            f"{rows.index(found) + 1}/{len(rows)}), SPLIT t {found['split_t']:+.2f} "
            f"(rank {by_split.index(found) + 1}/{len(rows)}), "
            f"fixed ratio {found['fixed']:+.3f}, range/cost "
            f"{found['range_over_cost']:.1f}, "
            f"{'beats' if found['split_t'] < cuts['split best'] else 'does NOT beat'} "
            "the split null"
        )
    print("\nDONE")


if __name__ == "__main__":
    main()
