"""Fade the recent slope, size by forecast volatility, and only when overstretched.

Asked on 2026-10-11. The proposal, in the order it was put:

1. forecast volatility, then **invert the previous slope direction**
2. try a one-to-two week lookback as well as short ones
3. ask how wide the distance can get in `N` bars
4. optionally fade only when `|slope| * N / sigma` is above one
5. compare lookbacks of 5, 10 and 20 bars, fade against follow
6. size by `1 / forecast vol`
7. check by volatility regime, since fading breaks in high-vol breakouts
8. find what counts as overstretched, and test a filter above one standard
   deviation

## The prior, stated before the measurement

Two things already measured here argue **against** fading and one argues for the
filter.

Against: this series diffuses at **1.00, 1.04, 1.06 and 1.07** times a
`sqrt(h)` random walk at h of 1, 5, 20 and 50. A faded series would diffuse
*slower* than `sqrt(h)`; a trending one faster. It is faintly trending, and more
so the further out you look, which is the opposite of what a fade wants.

Against: direction has been a coin in every test run here - `continue` between
48.3% and 49.6% across every bucket of every signal, and the signed regression
gives `t = -1.7` at best on 70,000 points.

For: **volatility is forecastable**, which is what makes the sizing and the
filter worth having even if the direction is not. Recent speed predicts the next
move's size with a 3.12x spread between its extreme quintiles at one bar, still
2.03x at fifty. So `sigma` in `slope * N / sigma` is a real quantity rather than
a placeholder, and that ratio is a genuine measure of how far price has gone
relative to how far it should have.

## What is reported

Per symbol, timeframe, lookback and horizon: the mean return to **following**
the slope, which is the fade's return with the sign flipped, so one number
answers both. In volatility units, then again after one spread, then split by
volatility regime and by overstretch.

**Costs are not optional here.** The innovation-reversion harness found an effect
with `t = -7.1` that was 0.16 spreads wide, and the lesson is that a return
before costs is not a result. The spread comes from the seqlab `spread` array,
in points, converted by a tick inferred from the series.

## The multiple-comparison surface, counted rather than ignored

Lookbacks times horizons times filters times regimes times symbols times
timeframes runs to several hundred cells. At that width a handful of `|t| > 3`
is the expected yield of pure noise, so the table prints the cell count and the
honest reading is the *pattern* across cells - a fade that works should work at
neighbouring lookbacks and horizons, not in one isolated square.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.inputs import WEEK, bar_hours, coverage, ema

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)

FRAMES = ("15m", "1h", "4h", "1d")

#: Slope lookbacks, in **hours**. Redone on 2026-10-11: these were `(5, 10,
#: 20)` bars with the one-to-four week pair bolted on beside them, which made
#: the table two different things at once - a bar count means 1.25h at 15m and
#: 5 days at 1d, so "lookback 5" named five estimators rather than one. Stated
#: as durations the short end and the multi-week end are the same ladder, and
#: the deduplication that used to be a special case for daily bars happens for
#: every timeframe by construction.
LOOKS = (1.0, 4.0, 24.0, 1 * WEEK, 2 * WEEK, 3 * WEEK, 4 * WEEK)

#: Horizons to hold for, in **hours**, for the same reason.
HORIZONS = (4.0, 24.0, 1 * WEEK)

#: The volatility forecast's own window, in **hours**. From the speed result:
#: the mean absolute move over the recent past, which beat every model quantity
#: as a predictor of the next move's size. A day of trading rather than twenty
#: bars, which was five hours at 15m and twenty days at 1d.
VOL_HOURS = 24.0

LIMIT = int(os.environ.get("LIMIT", "20000"))

#: Fewest independent observations before a `t` is reported at all. A `t` on
#: ten points is not a weak result, it is not a result, and the long lookbacks
#: on fast bars produce exactly that - see `independent`.
LEAST_INDEPENDENT = 30

#: Only use bars at or after this date. **Not a tuning knob - a provenance
#: filter.** `EURUSD.1d` in seqlab starts on 1971-01-03, twenty-eight years
#: before the euro existed, so the early part of that series is a vendor's
#: reconstruction rather than the market. `USDJPY.1d` starts the same day, at
#: the collapse of Bretton Woods, under capital controls and official
#: intervention that no longer exist.
#:
#: The first time this harness ran on hours it reported a momentum cluster on
#: `usdjpy 1d` surviving costs at `t` up to +4.1 across seven neighbouring
#: cells - over a window starting in 1971. Whatever that is evidence about, it
#: is not the market this desk trades. Set `SINCE=0` to see the whole file.
SINCE = float(os.environ.get("SINCE", "1262304000"))  # 2010-01-01


def tick_size(closes: list[float]) -> float:
    """The smallest price increment, inferred rather than hard-coded per symbol.

    The seqlab `spread` array is in **points**. Treating it as price inflates
    every cost by `1/tick` - 100,000 on EURUSD - which is how the
    innovation-reversion harness first reported a spread of 136 volatility
    units on a market that trades.
    """
    positive = [
        abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)) if closes[i] != closes[i - 1]
    ]
    return min(positive) if positive else 0.0


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
        spreads = bundle["spread"][order].tolist() if "spread" in bundle else [0.0] * len(closes)
    # **The provenance filter, before the length cap.** Cutting after the cap
    # would silently return nothing for a series whose last 20,000 bars all
    # predate the cut.
    first = 0
    while first < len(times) and times[first] < SINCE:
        first += 1
    times, closes, spreads = times[first:], closes[first:], spreads[first:]
    if len(closes) > LIMIT:
        times, closes, spreads = times[-LIMIT:], closes[-LIMIT:], spreads[-LIMIT:]
    return times, closes, spreads


def volatility_unit(closes: list[float]) -> float:
    """Price of one volatility unit: an exponential average of absolute moves."""
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    for i in range(1, len(closes)):
        move = abs(closes[i] - closes[i - 1]) / closes[i - 1] * 10_000
        average = move if i == 1 else average + alpha * (move - average)
    bps = max(average, 0.25)
    return bps * closes[0] / 10_000


def stats(values: list[float]) -> tuple[float, float, float, int]:
    """`(mean, standard error, t, n)` on overlapping observations.

    **This `t` is inflated and must not be read alone** - see `independent`.
    """
    n = len(values)
    if n < 30:
        return 0.0, 0.0, 0.0, n
    mean = statistics.fmean(values)
    se = statistics.stdev(values) / math.sqrt(n)
    return mean, se, (mean / se if se > 0 else 0.0), n


def independent(values: list[float], overlap: int) -> tuple[float, float, int]:
    """`(mean, t, n)` on **non-overlapping** windows only.

    This is the correction that decides whether anything in this harness is
    real. A trade opened at bar `k` and held `h` bars shares `h` bars of its
    outcome with the one opened at `k+1`, so consecutive observations are not
    independent draws. Treating ten thousand of them as ten thousand samples
    overstates `t` by roughly `sqrt(overlap)`, which is how an
    overlapping-window test manufactures significance from nothing.

    **The overlap is `max(look, horizon)`, not the horizon.** Two observations
    are independent only when they share neither their *outcome* window nor
    their *signal* window, and a slope over `look` bars is shared by every
    observation within `look` of it. Stepping by the horizon alone leaves a
    4-week lookback on 15m bars sharing 1,870 of its 1,920 signal bars with its
    neighbour - which still inflates `t`, just less obviously.

    The consequence is worth stating plainly: a 4-week lookback on 15m bars,
    over the 20,000 bars available, yields about **ten** independent
    observations. That is not a small sample, it is no sample, and it is the
    honest reason the long-lookback results cannot be tested here rather than a
    reason they are false.

    **And that paragraph used to be the only place it was enforced.** The
    survivor gate tested `|t| > 3` and nothing else, so the rerun on 2026-10-11
    duly promoted `usdjpy 15m look=672h h=168h` - `t = -3.1` **on ten points**,
    reporting a mean of -8.0 volatility units - into the list of things worth
    reading. A docstring that states a limit the code does not apply is bug
    shape #8 in the `finding-bugs` skill, and this was an instance of it in the
    file that exists to prevent exactly this error. `LEAST_INDEPENDENT` applies
    it now.
    """
    step = max(overlap, 1)
    sample = values[::step]
    n = len(sample)
    if n < 10:
        return (statistics.fmean(sample) if sample else 0.0), 0.0, n
    mean = statistics.fmean(sample)
    se = statistics.stdev(sample) / math.sqrt(n)
    return mean, (mean / se if se > 0 else 0.0), n


def main() -> None:
    print("Fade the slope, or follow it? Sized by forecast vol, filtered by overstretch.")
    print("All returns are in volatility units of the series' own bar.")
    print("A positive 'follow' return means the slope continues; negative means it fades.\n")

    cells = 0
    survivors: list[str] = []
    excursions: dict[tuple[str, int], list[float]] = {}
    regime_rows: list[tuple] = []

    for label, stem in SYMBOLS:
        for frame in FRAMES:
            loaded = load(stem, frame)
            if loaded is None:
                continue
            times, closes, spreads = loaded
            if len(closes) < 2000:
                continue
            unit = volatility_unit(closes)
            tick = tick_size(closes)
            points = [s for s in spreads if s > 0]
            spread_vol = (statistics.median(points) * tick / unit) if points and tick > 0 else 0.0
            # Everything downstream in volatility units.
            values = [(c / closes[0] - 1.0) * 10_000 / (unit * 10_000 / closes[0]) for c in closes]
            bar = bar_hours(times)
            if bar <= 0:
                continue
            # **`coverage`, not a hardcoded five-day week.** This harness had
            # `w * 5 * 24 / bar`, which is wrong on crypto and on the Deriv
            # synthetics - they trade seven days - and wrong by a different
            # amount on every instrument with its own session. The share of the
            # calendar a series trades is inferred from its own timestamps.
            cover = coverage(times, bar)

            def spans(hours: float, cover: float = cover, bar: float = bar) -> int:
                """Calendar hours to bars for *this* series. Bound explicitly,
                because a closure over a loop variable reads the last
                iteration's value if it is ever called later."""
                return max(round(hours * max(cover, 1e-9) / bar), 2)

            # Durations that land on the same bar count are one lookback, not
            # several - which on 1d bars collapses the short end into the weekly
            # end, exactly the collision the bar-count version had to special-
            # case and then got wrong anyway.
            looks: dict[int, float] = {}
            for hours in LOOKS:
                looks.setdefault(spans(hours), hours)
            lookbacks = sorted(looks)
            vol_bars = spans(VOL_HOURS)

            print(
                f"=== {label} {frame}: {len(values)} bars, bar={bar:.3g}h, "
                f"coverage={cover:.3f}, spread={spread_vol:.3f} vol units, "
                f"week={spans(WEEK)} bars ==="
            )

            moves = [0.0] + [values[k] - values[k - 1] for k in range(1, len(values))]

            # Rolling per-bar volatility, causal, used both to standardise the
            # moves and to size. One pass rather than a window per bar.
            sigmas = [0.0] * len(values)
            run = 0.0
            for k in range(1, len(values)):
                if k <= vol_bars:
                    run = statistics.fmean(abs(v) for v in moves[1 : k + 1]) if k else 0.0
                else:
                    run += (abs(moves[k]) - abs(moves[k - vol_bars])) / vol_bars
                sigmas[k] = max(run, 1e-9)

            #: The standardised move, which is what an EMA over z-scores
            #: smooths. Standardising *before* the EMA rather than after is
            #: the point of the variant: it weights a move by how surprising it
            #: was at the time rather than by its raw size, so a quiet-market
            #: drift and a volatile-market drift of the same magnitude do not
            #: contribute equally.
            zmoves = [moves[k] / sigmas[k] if sigmas[k] > 0 else 0.0 for k in range(len(moves))]
            print(
                f"  {'look':>4}{'signal':>11}{'h':>5}{'follow R':>10}{'t':>7}"
                f"{'after cost':>12}{'hit':>7}{'overstretched':>15}{'t':>7}"
            )

            emas = {look: ema(moves, look) for look in lookbacks}
            zemas = {look: ema(zmoves, look) for look in lookbacks}

            for look in lookbacks:
                for kind in ("slope", "ema slope", "ema zscore"):
                    for hours_ahead in HORIZONS:
                        horizon = spans(hours_ahead)
                        plain: list[float] = []
                        sized: list[float] = []
                        stretched: list[float] = []
                        vols: list[float] = []
                        ratios: list[float] = []
                        start = max(look, vol_bars) + 1
                        for k in range(start, len(values) - horizon):
                            slope = (values[k] - values[k - look]) / look
                            sigma = sigmas[k]
                            if sigma <= 0:
                                continue
                            if kind == "slope":
                                signal = slope
                            elif kind == "ema slope":
                                signal = emas[look][k]
                            else:
                                signal = zemas[look][k]
                            side = 1.0 if signal > 0 else (-1.0 if signal < 0 else 0.0)
                            if side == 0.0:
                                continue
                            # Return to FOLLOWING the slope. Fade is the negative.
                            got = side * (values[k + horizon] - values[k])
                            plain.append(got)
                            # Sized by `1 / forecast vol`, which is the quantity a
                            # desk actually earns: return per unit of risk taken,
                            # rather than return per trade regardless of size.
                            sized.append(got / sigma)
                            vols.append(sigma)
                            # Overstretch: how far price went over the lookback
                            # against what this volatility implies it should have.
                            #
                            # **The `sqrt(look)` matters.** The proposal was
                            # `slope * N / sigma`, and `slope * N` is the total
                            # travel, so dividing by one bar's `sigma` gives a
                            # number that grows like `sqrt(N)` for *any* series -
                            # a random walk would read as more overstretched the
                            # longer the lookback, purely by arithmetic. Dividing
                            # by `sigma * sqrt(N)` compares the travel to what a
                            # random walk would have done over the same span, so
                            # 1.0 means "exactly as far as chance" and the number
                            # is comparable across lookbacks.
                            ratio = abs(slope) * look / (sigma * math.sqrt(look))
                            ratios.append(ratio)
                        if len(plain) < 200:
                            continue
                        cells += 1
                        mean, _se, t, n = stats(plain)
                        after = mean - spread_vol
                        hit = statistics.fmean(1.0 if v > 0 else 0.0 for v in plain)

                        # The >1 standard deviation overstretch filter, measured on
                        # this series' own distribution of the ratio rather than
                        # assumed to be 1.0.
                        cut = statistics.fmean(ratios) + statistics.stdev(ratios)
                        stretched = [g for g, r in zip(plain, ratios, strict=True) if r >= cut]
                        smean, _sse, st, sn = stats(stretched)
                        cells += 1

                        # The honest `t`: one observation per non-overlapping
                        # window, where the window spans the signal's lookback as
                        # well as the outcome's horizon.
                        imean, it, inn = independent(plain, max(look, horizon))
                        flag = ""
                        if inn < LEAST_INDEPENDENT:
                            # Not a weak test - no test. Say so rather than
                            # print a number that will be read as one.
                            flag = " (n too small)"
                        elif abs(it) > 3 and abs(after) > 0:
                            flag = " <-"
                            survivors.append(
                                f"{label} {frame} {kind} look={looks[look]:g}h "
                                f"h={hours_ahead:g}h "
                                f"follow {mean:+.3f} (overlapping t{t:+.1f}, "
                                f"INDEPENDENT t{it:+.1f} on n={inn}) "
                                f"after cost {after:+.3f}"
                            )
                        zmean, _zse, zt, _zn = stats(sized)
                        print(
                            f"  {looks[look]:>3g}h{kind[:10]:>11}{hours_ahead:>4g}h"
                            f"{mean:>+10.3f}{t:>+7.1f}"
                            f"{after:>+12.3f}{hit:>7.1%}"
                            f"{smean:>+15.3f}{st:>+7.1f}{flag}"
                        )
                        tail = (
                            f"   independent n={inn} - too few to test"
                            if inn < LEAST_INDEPENDENT
                            else f"   independent t{it:>+6.1f} on n={inn}"
                        )
                        print(f"  {'':>6}{'sized 1/vol':>9}{zmean:>+11.3f}{zt:>+7.1f}{tail}")

                        if look == lookbacks[0] and hours_ahead == HORIZONS[0] and kind == "slope":
                            # Volatility regime, on the shortest pair only, to keep
                            # the table readable.
                            paired = sorted(zip(vols, plain, strict=True))
                            fifth = len(paired) // 5
                            for b, name in enumerate(
                                ("quietest", "quiet", "mid", "fast", "fastest")
                            ):
                                chunk = paired[b * fifth : (b + 1) * fifth]
                                if len(chunk) < 100:
                                    continue
                                m, _s, tt, _nn = stats([g for _v, g in chunk])
                                regime_rows.append((label, frame, name, m, tt, spread_vol))

            # How wide does it get in N bars - the excursion question, which is
            # what a stop and a target actually need.
            for hours_ahead in HORIZONS:
                horizon = spans(hours_ahead)
                widest = []
                for k in range(1, len(values) - horizon):
                    window = values[k : k + horizon + 1]
                    widest.append(max(window) - min(window))
                excursions[(f"{label} {frame}", hours_ahead, horizon)] = widest
            print()

    print("=== how wide does the distance get in N bars? ===")
    print("  the full range travelled within the window, in volatility units")
    print(
        f"  {'series':<16}{'span':>5}{'median':>9}{'p90':>9}{'p99':>9}{'max':>9}{'vs sqrt(N)':>12}"
    )
    for (series, hours_ahead, horizon), widest in excursions.items():
        widest.sort()
        n = len(widest)
        med = widest[n // 2]
        print(
            f"  {series:<16}{hours_ahead:>4g}h{med:>9.2f}{widest[int(n * 0.9)]:>9.2f}"
            f"{widest[int(n * 0.99)]:>9.2f}{widest[-1]:>9.2f}"
            f"{med / math.sqrt(horizon):>12.2f}"
        )

    print("\n=== by volatility regime, shortest lookback and horizon ===")
    print("  fading is said to break in high-vol breakouts; this is the test")
    print(f"  {'series':<16}{'regime':<10}{'follow R':>11}{'t':>7}{'spread':>9}")
    for label, frame, name, mean, t, spread_vol in regime_rows:
        print(f"  {label + ' ' + frame:<16}{name:<10}{mean:>+11.3f}{t:>+7.1f}{spread_vol:>9.3f}")

    print("\n  NOTE: every 't' in the tables above is on OVERLAPPING windows and is")
    print("  inflated by roughly sqrt(horizon). The 'independent t' beside each row")
    print("  is the one to read, and the survivor list below is gated on it.\n")
    print(f"=== {cells} cells tested ===")
    if survivors:
        print(f"  {len(survivors)} with |t| > 3:")
        for line in survivors:
            print(f"    {line}")
        print(f"\n  At {cells} cells, {cells * 0.0027:.1f} are expected above |t| = 3 by")
        print("  chance alone. Read the pattern across neighbouring cells, not the list.")
    else:
        print("  none with |t| > 3.")
    print("\n  A fade that is real works at neighbouring lookbacks and horizons too.")


if __name__ == "__main__":
    main()
