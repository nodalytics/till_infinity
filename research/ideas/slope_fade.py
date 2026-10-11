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
from collections import Counter
from pathlib import Path

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)

FRAMES = ("15m", "1h", "4h", "1d")

#: Bar lookbacks asked for, plus the one-to-two week pair which has to be
#: expressed in time and converted per timeframe - 480 bars of 15m is a week,
#: 5 bars of 1d is.
LOOKBACKS = (5, 10, 20)
WEEKS = (1.0, 2.0)

#: Horizons to hold for, in bars.
HORIZONS = (5, 20, 50)

#: Bars used to forecast volatility, from the speed result: the mean absolute
#: move over the recent past, which beat every model quantity as a predictor of
#: the next move's size.
VOL_BARS = 20

LIMIT = int(os.environ.get("LIMIT", "20000"))


def tick_size(closes: list[float]) -> float:
    """The smallest price increment, inferred rather than hard-coded per symbol.

    The seqlab `spread` array is in **points**. Treating it as price inflates
    every cost by `1/tick` - 100,000 on EURUSD - which is how the
    innovation-reversion harness first reported a spread of 136 volatility
    units on a market that trades.
    """
    positive = [
        abs(closes[i] - closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] != closes[i - 1]
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
        spreads = (
            bundle["spread"][order].tolist()
            if "spread" in bundle
            else [0.0] * len(closes)
        )
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
    outcome with the trade opened at `k+1`, so consecutive observations are not
    independent draws - and with a lookback of 960 and a horizon of 50 on 15m
    bars, neighbouring observations share 1,010 bars out of 1,010. Treating
    10,000 of those as 10,000 independent samples overstates `t` by roughly
    `sqrt(overlap)`, which is how an overlapping-window test manufactures
    significance from nothing.

    Stepping by the overlap keeps one observation per independent window. It
    throws away most of the data, which is the honest price: what is left is a
    number that means what it says.
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
            spread_vol = (
                (statistics.median(points) * tick / unit) if points and tick > 0 else 0.0
            )
            # Everything downstream in volatility units.
            values = [(c / closes[0] - 1.0) * 10_000 / (unit * 10_000 / closes[0]) for c in closes]
            bar_hours = max(
                statistics.median(
                    [(times[i] - times[i - 1]) / 3600.0 for i in range(1, min(500, len(times)))]
                ),
                1e-9,
            )
            week_bars = [max(int(round(w * 5 * 24 / bar_hours)), 2) for w in WEEKS]
            # **Deduplicated, and the collision is informative.** On daily bars
            # one week is 5 bars and two weeks is 10, which are already in
            # `LOOKBACKS` - so the "1-2 week" test at 1d *is* the 5 and 10 bar
            # test, and the first version of this harness ran and reported each
            # of them twice.
            lookbacks = sorted(set(LOOKBACKS) | set(week_bars))

            print(f"=== {label} {frame}: {len(values)} bars, bar={bar_hours:.3g}h, "
                  f"spread={spread_vol:.3f} vol units, week={week_bars[0]} bars ===")

            moves = [0.0] + [values[k] - values[k - 1] for k in range(1, len(values))]

            # Rolling per-bar volatility, causal, used both to standardise the
            # moves and to size. One pass rather than a window per bar.
            sigmas = [0.0] * len(values)
            run = 0.0
            for k in range(1, len(values)):
                if k <= VOL_BARS:
                    run = statistics.fmean(abs(v) for v in moves[1 : k + 1]) if k else 0.0
                else:
                    run += (abs(moves[k]) - abs(moves[k - VOL_BARS])) / VOL_BARS
                sigmas[k] = max(run, 1e-9)

            def ema(source: list[float], span: int) -> list[float]:
                """Causal EMA, `alpha = 2/(span+1)`. Nothing here sees ahead."""
                alpha = 2.0 / (span + 1.0)
                out = [0.0] * len(source)
                current = 0.0
                for k, value in enumerate(source):
                    current = value if k == 0 else current + alpha * (value - current)
                    out[k] = current
                return out

            #: The standardised move, which is what an EMA over z-scores
            #: smooths. Standardising *before* the EMA rather than after is
            #: the point of the variant: it weights a move by how surprising it
            #: was at the time rather than by its raw size, so a quiet-market
            #: drift and a volatile-market drift of the same magnitude do not
            #: contribute equally.
            zmoves = [moves[k] / sigmas[k] if sigmas[k] > 0 else 0.0 for k in range(len(moves))]
            print(f"  {'look':>4}{'signal':>11}{'h':>5}{'follow R':>10}{'t':>7}"
                  f"{'after cost':>12}{'hit':>7}{'overstretched':>15}{'t':>7}")

            emas = {look: ema(moves, look) for look in lookbacks}
            zemas = {look: ema(zmoves, look) for look in lookbacks}

            for look in lookbacks:
              for kind in ("slope", "ema slope", "ema zscore"):
                for horizon in HORIZONS:
                    plain: list[float] = []
                    sized: list[float] = []
                    stretched: list[float] = []
                    vols: list[float] = []
                    ratios: list[float] = []
                    start = max(look, VOL_BARS) + 1
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
                    # window. The overlap is the horizon, which is what two
                    # neighbouring trades actually share.
                    imean, it, inn = independent(plain, horizon)
                    flag = ""
                    if abs(it) > 3 and abs(after) > 0:
                        flag = " <-"
                        survivors.append(
                            f"{label} {frame} {kind} look={look} h={horizon} "
                            f"follow {mean:+.3f} (overlapping t{t:+.1f}, "
                            f"INDEPENDENT t{it:+.1f} on n={inn}) "
                            f"after cost {after:+.3f}"
                        )
                    zmean, _zse, zt, _zn = stats(sized)
                    print(f"  {look:>4}{kind[:10]:>11}{horizon:>5}{mean:>+10.3f}{t:>+7.1f}"
                          f"{after:>+12.3f}{hit:>7.1%}"
                          f"{smean:>+15.3f}{st:>+7.1f}{flag}")
                    print(f"  {'':>6}{'sized 1/vol':>9}{zmean:>+11.3f}{zt:>+7.1f}"
                          f"   independent t{it:>+6.1f} on n={inn}")

                    if look == lookbacks[0] and horizon == HORIZONS[0] and kind == "slope":
                        # Volatility regime, on the shortest pair only, to keep
                        # the table readable.
                        paired = sorted(zip(vols, plain, strict=True))
                        fifth = len(paired) // 5
                        for b, name in enumerate(("quietest", "quiet", "mid", "fast", "fastest")):
                            chunk = paired[b * fifth : (b + 1) * fifth]
                            if len(chunk) < 100:
                                continue
                            m, _s, tt, _nn = stats([g for _v, g in chunk])
                            regime_rows.append((label, frame, name, m, tt, spread_vol))

            # How wide does it get in N bars - the excursion question, which is
            # what a stop and a target actually need.
            for horizon in HORIZONS:
                widest = []
                for k in range(1, len(values) - horizon):
                    window = values[k : k + horizon + 1]
                    widest.append(max(window) - min(window))
                excursions[(f"{label} {frame}", horizon)] = widest
            print()

    print("=== how wide does the distance get in N bars? ===")
    print("  the full range travelled within the window, in volatility units")
    print(f"  {'series':<16}{'N':>5}{'median':>9}{'p90':>9}{'p99':>9}{'max':>9}{'vs sqrt(N)':>12}")
    for (series, horizon), widest in excursions.items():
        widest.sort()
        n = len(widest)
        med = widest[n // 2]
        print(f"  {series:<16}{horizon:>5}{med:>9.2f}{widest[int(n * 0.9)]:>9.2f}"
              f"{widest[int(n * 0.99)]:>9.2f}{widest[-1]:>9.2f}"
              f"{med / math.sqrt(horizon):>12.2f}")

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
