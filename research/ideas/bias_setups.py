"""Kinds of bias, each scored against its own flip on the same bars.

Named `bias_setups` and not `setups` because `research/ideas/setups.py`
already exists - 1,417 lines of catalogued trade ideas, imported by
`run.py`, `survivors.py` and `test_setups.py`. This file was first written
to that path and destroyed it, so the name now says which of the two
questions it asks: that one tests catalogued **setups**, this one tests
kinds of **bias**.

Entry and exit rules a competent retail trader would use, scored against
the geometry they carry.

Asked across 2026-10-17: *"keep testing different entry and exit conditions
until we get what we want in RR and the win rate is high too"*, with OHLCV,
multi-timeframe and fractality available, and then *"we can start from the
mindset and approaches and improve on it fast"*.

So this starts from the approach rather than from a model: higher-timeframe
bias, an entry on a pullback, a stop beyond the swing that would disprove the
idea, and a target at a fixed reward or at the next structure. Every piece of
that is a rule here, and every rule is scored the same way.

## The one number, and why it is the only one

**A win rate and a reward are not independent.** On a driftless market the
chance of reaching the target before the stop is exactly `1 / (1 + r)`: 33% at
1:2, 25% at 1:3, 9% at 1:10. So "a high win rate **at** a high reward" is not a
setup to be found among entry rules - it is directional edge under another
name. Every row below therefore reports

    win - geometric

where `geometric` is averaged over each trade's **own** realised reward, since
a structural stop makes every trade's geometry different. That difference is
the only quantity that can be an edge. A rule with a 70% win rate at 1:0.4 and
a rule with a 9% win rate at 1:10 are **the same rule** by this measure, and
the point of the column is that it says so.

## The nulls

* **the flip.** Every setup is scored again with its side reversed. If a rule
  has no directional content, flipping pays the same, and the pair straddles
  zero. This is the sharpest null available for an entry rule and it costs
  nothing.
* **`all`.** Taking every bar, same geometry. A rule that does not beat
  "always on" has selected nothing.
* **the walk.** Generated bars through the identical pipeline, where every
  reading must collapse to the geometry.

## What is deliberately not here

No level-based entry, because `magnets.md` measured twenty-one kinds against a
story-free control and every one sat inside its noise. No named candle pattern,
because `sweep_bos_engulf.py` found them level with geometry-preserving twins.
What is here is **structure** - the directional-change decomposition, which is
scale-free and is v1's own turn rule generalised - and **dispersion**, which is
the one forecastable quantity on this desk.
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from dispersion_ml import SIZE, _apply, _ridge, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.pivoting import pivots  # noqa: E402
from till_infinity.structures.drawing.displacement import displacements  # noqa: E402
from till_infinity.structures.vol.volatility import Volatility  # noqa: E402
from till_infinity.trading.candles import Bar, engulfing  # noqa: E402

FRAME = "1h"
#: The higher timeframe, for bias. Multi-timeframe is the first thing a
#: competent retail approach does, so it is an arm rather than an assumption.
HIGHER = "4h"
#: Seconds in the higher timeframe's bar, for the resampler.
HIGHER_SECONDS = 4 * 3600.0
#: Classes. Widened from three because the thirty-six cells a rule produces are
#: heavily correlated - same bars, overlapping rewards - so the number of
#: genuinely independent units is the number of **classes**, and three is too
#: few to read a median across.
TRADED = ("fx_major", "fx_cross", "metal", "equity", "index", "energy")
PER_CLASS = 20
LIMIT = 12000
#: Directional-change thresholds, in volatility units. **Fractality**: the same
#: rule at several scales, which is what the intrinsic-time framework is for.
EDGES = (1.0, 2.0, 4.0)
#: Reward multiples, and the hold in bars.
REWARDS = (1.0, 2.0, 3.0, 5.0)
HOLD = 120
#: Round-trip cost in volatility units. Not zero, because
#: `exotic-spreads-are-a-whole-bar-range` makes cost decisive.
COST = 0.05
SEED = 20261017


def _resample(bars: dict[str, np.ndarray], every: float) -> dict[str, np.ndarray]:
    """Aggregate bars onto fixed `every`-second boundaries.

    **Why this is here rather than reading a 4h file.** The cache holds 555
    series at 1h and only **84** at 4h, so taking the higher timeframe from
    disk silently capped the panel at three classes - and the thirty-six cells
    a rule produces are correlated, which makes the class count the number of
    genuinely independent units. Three was too few to read a median across.
    A four-hour bar **is** four one-hour bars, so building it is exact rather
    than an approximation.

    Grouped on absolute boundaries - `floor(time / every)` - and not in runs of
    four from wherever the series starts, because a 4h bar beginning at 01:00
    on one instrument and 03:00 on another is not the same clock, and a shared
    clock is the whole point of a higher timeframe.
    """
    times = np.asarray(bars["time"], dtype=float)
    if len(times) == 0:
        return {k: np.asarray([], dtype=float) for k in ("time", "open", "high", "low", "close")}
    buckets = np.floor(times / every).astype(np.int64)
    edges = np.flatnonzero(np.diff(buckets)) + 1
    starts = np.concatenate([[0], edges])
    stops = np.concatenate([edges, [len(times)]])
    opens, highs, lows, closes, stamps = [], [], [], [], []
    for a, b in zip(starts, stops, strict=True):
        opens.append(float(bars["open"][a]))
        highs.append(float(np.max(bars["high"][a:b])))
        lows.append(float(np.min(bars["low"][a:b])))
        closes.append(float(bars["close"][b - 1]))
        # Stamped at the **close** of the aggregate, because that is when it
        # became knowable. Stamping it at the open would let a bias be read
        # four hours before the bar producing it had finished.
        stamps.append(float(times[b - 1]))
    return {
        "time": np.asarray(stamps),
        "open": np.asarray(opens),
        "high": np.asarray(highs),
        "low": np.asarray(lows),
        "close": np.asarray(closes),
    }


def _unit(closes: np.ndarray) -> float:
    steps = np.abs(np.diff(closes))
    return float(np.mean(steps[steps > 0])) if np.any(steps > 0) else 0.0


def _dispersion(logvar: np.ndarray) -> np.ndarray:
    """Forecast forward dispersion with the arm that measured best, causally."""
    start, stop = SIZE, len(logvar) - HOLD
    if stop - start < 400:
        return np.full(len(logvar), np.nan)
    rows = np.asarray(
        [[float(logvar[i - k]) for k in range(SIZE)] for i in range(start, stop)], dtype=float
    )
    want = np.asarray(
        [float(np.mean(logvar[i + 1 : i + 1 + HOLD])) for i in range(start, stop)], dtype=float
    )
    cut = len(want) // 2
    coef, _ = _ridge(rows[:cut], want[:cut], 1e-4)
    out = np.full(len(logvar), np.nan)
    out[start:stop] = _apply(coef, rows)
    return out


def _structure(bars: dict[str, np.ndarray], edge: float) -> list:
    """Directional-change pivots on log prices, so a swing is scale-free."""
    closes = np.asarray(bars["close"], dtype=float)
    if np.any(closes <= 0):
        return []
    logs = {
        k: np.log(np.maximum(np.asarray(bars[k], dtype=float), 1e-300))
        for k in ("close", "high", "low")
    }
    unit = _unit(logs["close"])
    if unit <= 0:
        return []
    return pivots(
        [float(v) for v in bars["time"]],
        [float(v) for v in logs["high"]],
        [float(v) for v in logs["low"]],
        unit=unit,
        threshold=edge,
    )


#: Bars within which a break has to be rejected for it to count as a sweep
#: rather than a break of structure. This is what keeps the two from being the
#: same event with opposite signs.
REJECTED = 3


#: Kinds of bias, which is the frame this harness settled into. Each is a
#: separate claim about **which way**, read off the higher timeframe, and each
#: needs its own walk null because each carries its own mechanics:
#:
#: * **structural** - the last confirmed directional-change pivot (`agree`)
#: * **break** - a prior swing exceeded and extended (`bos 4h`)
#: * **rejection** - a prior swing exceeded and immediately refused (`sweep 4h`)
#: * **candle** - an engulfing body (`engulf 4h`)
#: * **displacement** - a two-bar one-sided push leaving an origin (`displace 4h`)
#: * **trend** - the sign of a fitted slope (`slope 4h`)
#: * **location** - where price sits in the higher timeframe's range (`range 4h`)
#: * **gap** - the sign of the last bar-to-bar gap (`gap 4h`)
#: * **imbalance** - a band price left behind rather than a shape it drew: a
#:   fair value gap (`fvg 4h`), as a **causal** three-bar condition. The void
#:   and volume-imbalance kinds are absent because neither has a causal
#:   definition - both are defined by what later price did - and the production
#:   detector that emits all three filters on the gap still being unfilled,
#:   which is the future. See `_imbalances`.
#:
#: Dispersion is deliberately **not** in this list. It is the one forecastable
#: quantity here and the others are not, but it says how **far** and not which
#: way - so it enters as the gate `loud` rather than as a bias, which is the
#: distinction the whole architecture turns on.
BIASES = (
    "agree",
    "bos 4h",
    "sweep 4h",
    "engulf 4h",
    "displace 4h",
    "slope 4h",
    "range 4h",
    "gap 4h",
    "fvg 4h",
    "void 4h",
    "ma200 4h",
    "wick 4h",
    "streak 4h",
    "skew 4h",
    "slope 1d",
    # Kept as a **known null**: the intraday pattern is in volatility, not
    # direction, so this has to read nothing or the harness is broken.
    "session",
)

#: Higher-timeframe bars a slope is fitted over, and the share of its range
#: that counts as the top or the bottom for the location bias.
SLOPE_BARS = 20
EDGE_SHARE = 0.33


def _pushes(bars: dict[str, np.ndarray], run: int = 2) -> list[tuple[float, int]]:
    """`(time, side)` for every displacement origin left by a `run`-bar push.

    Production's own `drawing.displacement.displacements` at `run = 2`, the
    two-push-candle version. The time is the **confirmation** bar and not the
    origin bar: an origin is knowable only once the push that left it has
    completed, and using the origin's own time is the leak that distinction
    exists to prevent.
    """
    closes = np.asarray(bars["close"], dtype=float)
    live = Volatility()
    for one in closes:
        live.update(float(one))
    found = displacements(
        [float(v) for v in bars["open"]],
        [float(v) for v in bars["high"]],
        [float(v) for v in bars["low"]],
        [float(v) for v in closes],
        live,
        run=run,
    )
    times = bars["time"]
    out = [
        (float(times[min(one.confirmed_at, len(times) - 1)]), 1 if one.up else -1) for one in found
    ]
    out.sort()
    return out


def _imbalances(bars: dict[str, np.ndarray], kind: str) -> list[tuple[float, int]]:
    """`(time, side)` for a three-bar gap, computed **causally**.

    **This does not call `drawing.gaps.imbalances`, and the reason is the most
    expensive thing found in this harness.** That function ends with

        top, bottom = _remaining(highs, lows, i + 2, low, high, open_share)
        if top - bottom < (high - low) * open_share:
            continue

    - it scans **forward** from the gap and emits it only if it is still
    unfilled. That is exactly right for its own job, which is drawing the gaps
    that are open *now*; inside a loop over history, "now" is the end of the
    series, so the rule is handed *a strong move happened **and price never
    came back to fill it***. The second half is the future, and a gap that
    stays unfilled is one where price kept going - which is the direction.

    Measured, before the leak was found: `fvg 4h` read a win gap of **+0.31**
    and **+0.50R a trade** against a -0.13R baseline, in both halves and every
    class. Nothing else in the panel was within 0.3R of it, which is what
    prompted the check rather than the celebration.

    So the causal version is the bare three-bar condition - bar `i+1`'s low
    above bar `i-1`'s high, or the mirror - knowable at `i + 1` and filtered on
    nothing that comes after. `kind` is kept in the signature so the caller
    reads the same, but only the fair-value-gap shape survives a causal
    definition: a void and a volume imbalance are both defined by what later
    price did or did not do.
    """
    if kind != "fvg":
        return []
    highs = np.asarray(bars["high"], dtype=float)
    lows = np.asarray(bars["low"], dtype=float)
    times = bars["time"]
    unit = _unit(np.asarray(bars["close"], dtype=float))
    out: list[tuple[float, int]] = []
    for i in range(1, len(highs) - 1):
        if lows[i + 1] > highs[i - 1]:
            size, side = float(lows[i + 1] - highs[i - 1]), 1
        elif lows[i - 1] > highs[i + 1]:
            size, side = float(lows[i - 1] - highs[i + 1]), -1
        else:
            continue
        # A size floor, in the series' own units, so a one-tick gap is not a
        # structural claim. No forward reference.
        if unit <= 0 or size < 0.5 * unit:
            continue
        out.append((float(times[i + 1]), side))
    return out


def _averages(bars: dict[str, np.ndarray], span: int = 200) -> list[tuple[float, int]]:
    """`(time, side)` for price above or below its own long average.

    **The most widely used bias in retail trading, and untested here as one.**
    `magnets.md` measured the 200-period average as a *magnet* - does price get
    drawn back to it - and found it indistinguishable from the previous bar's
    high. That is a different claim from *above it means up*, which is what
    everyone actually uses it for, and a null on the first says nothing about
    the second.
    """
    closes = np.asarray(bars["close"], dtype=float)
    times = bars["time"]
    out = []
    total = 0.0
    for i, one in enumerate(closes):
        total += float(one)
        if i < span:
            continue
        total -= float(closes[i - span])
        mean = total / span
        out.append((float(times[i]), 1 if float(one) > mean else -1))
    return out


def _wicks(bars: dict[str, np.ndarray]) -> list[tuple[float, int]]:
    """`(time, side)` for where a bar closed inside its own range.

    A close in the top third reads up, the bottom third down - the rejection
    reading. A different kind of candle claim from an engulfing: that one is
    about **two** bars' bodies, this is about **one** bar's close against its
    own extremes, and the two can disagree.
    """
    highs = np.asarray(bars["high"], dtype=float)
    lows = np.asarray(bars["low"], dtype=float)
    closes = np.asarray(bars["close"], dtype=float)
    times = bars["time"]
    out = []
    for i in range(len(closes)):
        span = float(highs[i]) - float(lows[i])
        if span <= 0:
            out.append((float(times[i]), 0))
            continue
        share = (float(closes[i]) - float(lows[i])) / span
        out.append(
            (float(times[i]), 1 if share >= 1.0 - EDGE_SHARE else -1 if share <= EDGE_SHARE else 0)
        )
    return out


def _streaks(bars: dict[str, np.ndarray], least: int = 3) -> list[tuple[float, int]]:
    """`(time, side)` after `least` consecutive bars closing the same way.

    Run length rather than slope: a slope fits a line through twenty bars and
    is indifferent to their order, while a streak is **only** about order. The
    two are different readings of momentum and a null on one does not carry.
    """
    closes = np.asarray(bars["close"], dtype=float)
    times = bars["time"]
    out = []
    run = 0
    for i in range(1, len(closes)):
        step = 1 if closes[i] > closes[i - 1] else -1 if closes[i] < closes[i - 1] else 0
        run = run + step if step and (run == 0 or (run > 0) == (step > 0)) else step
        out.append((float(times[i]), (1 if run > 0 else -1) if abs(run) >= least else 0))
    return out


def _skews(bars: dict[str, np.ndarray], span: int = 40) -> list[tuple[float, int]]:
    """`(time, side)` for whether recent up-moves or down-moves were larger.

    The **shape** of the return distribution rather than its location, which
    makes it a different kind of information from everything above: slope,
    streak and location are all about where price went, this is about how it
    travelled. `one-bar-band.md` found skew null for *density scoring*, which
    is a statement about fitting a shape and not about direction.
    """
    closes = np.log(np.maximum(np.asarray(bars["close"], dtype=float), 1e-300))
    times = bars["time"]
    steps = np.diff(closes)
    out = []
    for i in range(span, len(steps)):
        window = steps[i - span : i]
        ups = window[window > 0]
        downs = -window[window < 0]
        if len(ups) < 3 or len(downs) < 3:
            out.append((float(times[i + 1]), 0))
            continue
        out.append((float(times[i + 1]), 1 if float(ups.mean()) > float(downs.mean()) else -1))
    return out


def _sessions(bars: dict[str, np.ndarray]) -> list[tuple[float, int]]:
    """`(time, side)` by hour of day - **a calibration arm, expected null.**

    `seasonality-belongs-on-q` is explicit: the intraday pattern is in
    **volatility**, and it drives `Q` rather than `R`. So an hour-of-day
    *direction* bias should read nothing, and it is here to confirm the harness
    can still say so after ten other rules have been added to it. A panel with
    no known-null arm cannot tell a dead detector from a dead effect.

    The split is London-and-after against Asia, which is the crudest version
    and the point: if a crude clock bias reads something, the harness is wrong.
    """
    times = np.asarray(bars["time"], dtype=float)
    hours = (times / 3600.0) % 24.0
    return [(float(t), 1 if 7.0 <= h < 19.0 else -1) for t, h in zip(times, hours, strict=True)]


def _slopes(bars: dict[str, np.ndarray]) -> list[tuple[float, int]]:
    """`(time, side)` for the sign of a slope fitted over `SLOPE_BARS`."""
    closes = np.log(np.maximum(np.asarray(bars["close"], dtype=float), 1e-300))
    times = bars["time"]
    x = np.arange(SLOPE_BARS, dtype=float)
    x -= x.mean()
    spread = float((x * x).sum())
    out = []
    for i in range(SLOPE_BARS, len(closes)):
        window = closes[i - SLOPE_BARS : i]
        slope = float((x * (window - window.mean())).sum() / spread) if spread > 0 else 0.0
        out.append((float(times[i]), 1 if slope > 0 else -1 if slope < 0 else 0))
    return out


def _locations(bars: dict[str, np.ndarray]) -> list[tuple[float, int]]:
    """`(time, side)` for where price sits in its own recent range.

    Top third reads as upward and bottom third as downward - the momentum
    reading rather than the mean-reverting one. Which of the two is right is
    exactly what the flip arm answers, so only one has to be written.
    """
    highs = np.asarray(bars["high"], dtype=float)
    lows = np.asarray(bars["low"], dtype=float)
    closes = np.asarray(bars["close"], dtype=float)
    times = bars["time"]
    out = []
    for i in range(SLOPE_BARS, len(closes)):
        top = float(highs[i - SLOPE_BARS : i].max())
        bottom = float(lows[i - SLOPE_BARS : i].min())
        if top <= bottom:
            out.append((float(times[i]), 0))
            continue
        share = (float(closes[i]) - bottom) / (top - bottom)
        out.append(
            (float(times[i]), 1 if share >= 1.0 - EDGE_SHARE else -1 if share <= EDGE_SHARE else 0)
        )
    return out


def _gaps(bars: dict[str, np.ndarray]) -> list[tuple[float, int]]:
    """`(time, side)` for the sign of each bar-to-bar gap, zero where none."""
    opens = np.asarray(bars["open"], dtype=float)
    closes = np.asarray(bars["close"], dtype=float)
    times = bars["time"]
    return [
        (
            float(times[i]),
            1
            if float(opens[i]) > float(closes[i - 1])
            else -1
            if float(opens[i]) < float(closes[i - 1])
            else 0,
        )
        for i in range(1, len(closes))
    ]


def _latest(series: list[tuple[float, int]], when: float, within: float) -> int:
    """The most recent side in `series` already known at `when`, or 0."""
    side = 0
    for seen, which in series:
        if seen > when:
            break
        if (when - seen) <= within:
            side = which
    return side


def _engulfings(bars: dict[str, np.ndarray]) -> list[tuple[float, int]]:
    """`(time, side)` for every engulfing bar, using production's own predicate.

    The shipped `trading.candles.engulfing` rather than a copy: it compares
    **bodies** strictly, which is the claim being made - this bar traded
    through everything the last one did *and closed beyond it*. A bar whose
    range covers the previous range but whose body does not is a wider bar and
    nothing more.

    Marked at the bar's own close, which is when it was knowable - unlike a
    pivot, an engulfing needs no confirmation lag. As a **higher-timeframe
    bias** this is untested here: `one_push.py` measured the shape against a
    push and `sweep_bos_engulf.py` measured it inside a composite, both at one
    scale.
    """
    opens, highs = bars["open"], bars["high"]
    lows, closes, times = bars["low"], bars["close"], bars["time"]
    out: list[tuple[float, int]] = []
    for i in range(1, len(closes)):
        was = Bar(
            float(opens[i - 1]), float(highs[i - 1]), float(lows[i - 1]), float(closes[i - 1])
        )
        now = Bar(float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]))
        got = engulfing(was, now)
        if got:
            out.append((float(times[i]), 1 if got == "up" else -1))
    return out


def _breaks(found: list) -> dict[int, tuple[int, bool]]:
    """Per confirmed pivot: the break's direction, and whether it was rejected.

    **A sweep and a break of structure are the same event read two ways**, and
    that has to be designed around rather than measured around. On a
    directional-change sequence a confirmed peak above the previous peak is
    both *a swept high* - liquidity taken, trade the reversal - and *a bullish
    break of structure* - trade the continuation. Those are opposite sides of
    one bar, so a harness testing both would be testing a rule against its own
    flip and would find a perfectly symmetric nothing. `smc-primitives-overlap-and-are-closed`
    is the standing record of that shape.

    So they are separated by **what happened next**. A break is a break; it is
    a *sweep* only if the next confirmed pivot arrives within `REJECTED` bars,
    which is the market refusing the break rather than extending it. The two
    rules then select different events, and the flip arm means something again.
    """
    out: dict[int, tuple[int, bool]] = {}
    last: dict[bool, float] = {}
    for i, one in enumerate(found):
        prior = last.get(one.peak)
        last[one.peak] = one.level
        if prior is None:
            continue
        # A peak above the last peak breaks up; a trough below the last trough
        # breaks down.
        if one.peak and one.level > prior:
            side = 1
        elif not one.peak and one.level < prior:
            side = -1
        else:
            continue
        quick = (
            i + 1 < len(found) and (found[i + 1].confirmed_index - one.confirmed_index) <= REJECTED
        )
        out[one.confirmed_index] = (side, quick)
    return out


def _bias(higher: list, when: float) -> int:
    """The higher timeframe's last **confirmed** direction at `when`, or 0.

    Confirmed, not current: a pivot is knowable only at its confirmation time,
    and using the extreme's own time is the leak `pivoting.Pivot` carries two
    timestamps to prevent.
    """
    side = 0
    for one in higher:
        if one.confirmed > when:
            break
        # A confirmed peak ends an up-leg, so the bias after it is down.
        side = -1 if one.peak else 1
    return side


def run(bars: dict[str, np.ndarray], higher: dict[str, np.ndarray], rng) -> dict:
    """Every entry rule by every exit geometry, with the flip arm beside it."""
    closes = np.asarray(bars["close"], dtype=float)
    highs = np.asarray(bars["high"], dtype=float)
    lows = np.asarray(bars["low"], dtype=float)
    unit = _unit(closes)
    if unit <= 0 or len(closes) < 2000:
        return {}
    logvar = parkinson(highs, lows)
    logvar = np.where(np.isfinite(logvar), logvar, np.nanmedian(logvar[np.isfinite(logvar)]))
    forecast = _dispersion(logvar)
    loud = float(np.nanquantile(forecast, 0.75)) if np.isfinite(forecast).any() else np.inf

    out: dict[tuple[str, float, float], list[tuple[float, float]]] = {}
    # **Hoisted out of the threshold loop.** None of these depends on `edge`,
    # and `_pushes` builds a whole `Volatility` pass over the series, so
    # computing them per threshold was three times the work for one answer.
    swallowed = _engulfings(higher)
    pushed_by = _pushes(higher)
    sloped = _slopes(higher)
    located = _locations(higher)
    gapped = _gaps(higher)
    # Three more kinds of bias, each a band price left behind rather than a
    # shape it drew: a fair value gap, a volume imbalance and a void.
    fvgs = _imbalances(higher, "fvg")
    # Six more kinds, and one of them is a known null kept on purpose.
    averaged = _averages(higher)
    wicked = _wicks(higher)
    streaked = _streaks(higher)
    skewed = _skews(higher)
    sessioned = _sessions(bars)
    # The next scale up, built by the same resampler. Not a new kind of
    # information but a new **scale**, and whether bias strength grows with the
    # timeframe is a question nothing here has asked.
    daily = _resample(bars, 24 * 3600.0)
    sloped_1d = _slopes(daily)
    window = 8 * 4 * 3600.0
    middle = float(bars["time"][len(bars["time"]) // 2])

    for edge in EDGES:
        here = _structure(bars, edge)
        there = _structure(higher, edge)
        marks = {one.confirmed_index: one for one in here}
        broke = _breaks(here)
        # The higher timeframe's breaks, keyed by the time they were
        # **confirmed** so an entry bar can ask what was known by then.
        above = _breaks(there)
        upstairs = [
            (there[i].confirmed, side, quick)
            for i, (side, quick) in (
                (next(k for k, one in enumerate(there) if one.confirmed_index == idx), v)
                for idx, v in above.items()
            )
            for side, quick in ((side, quick),)
        ]
        upstairs.sort()
        for at in range(SIZE + 1, len(closes) - HOLD - 1):
            one = marks.get(at)
            when = float(bars["time"][at])
            price = float(closes[at])
            # The structural stop: beyond the swing that would disprove it.
            if one is None:
                continue
            side = -1 if one.peak else 1
            # **Back to price.** The detector ran on log prices so a swing is
            # scale-free, which means every level it reports is a log price -
            # and comparing one to a close in price units made every risk about
            # 95 and every candidate fail its own filter. The conversion is
            # unconditional, not a guess from the sign.
            invalid = math.exp(one.level)
            risk = abs(price - invalid)
            if risk <= 0.2 * unit or risk > 8.0 * unit:
                continue
            bias = _bias(there, when)
            noisy = bool(np.isfinite(forecast[at]) and forecast[at] >= loud)
            # This bar's own break, if it is one, and the most recent one on
            # the higher timeframe that was already confirmed.
            mine = broke.get(at)
            theirs = None
            for seen, up_side, up_quick in upstairs:
                if seen > when:
                    break
                theirs = (up_side, up_quick, seen)
            fresh = theirs is not None and (when - theirs[2]) <= 8 * 3600.0 * 4
            eaten = 0
            for seen, which in swallowed:
                if seen > when:
                    break
                if (when - seen) <= 8 * 3600.0 * 4:
                    eaten = which
            rules = {
                "structure": True,
                "agree": bias == side,
                "against": bias == -side,
                "loud": noisy,
                "agree+loud": bias == side and noisy,
                # A break of structure, traded **with** the break.
                "bos": mine is not None and not mine[1] and mine[0] == side,
                # A sweep: a break that was rejected, traded **against** it.
                "sweep": mine is not None and mine[1] and mine[0] == -side,
                # The same two, but the break is on the higher timeframe and
                # the entry is down here - which is the version a competent
                # retail approach actually uses.
                "bos 4h": fresh and not theirs[1] and theirs[0] == side,
                "sweep 4h": fresh and theirs[1] and theirs[0] == -side,
                "bos 4h+loud": fresh and not theirs[1] and theirs[0] == side and noisy,
                "engulf 4h": eaten == side,
                "engulf 4h+loud": eaten == side and noisy,
                "engulf+bos 4h": eaten == side and fresh and not theirs[1] and theirs[0] == side,
                # The other kinds of bias, each its own claim about which way.
                "displace 4h": _latest(pushed_by, when, window) == side,
                "slope 4h": _latest(sloped, when, window) == side,
                "range 4h": _latest(located, when, window) == side,
                "gap 4h": _latest(gapped, when, window) == side,
                "ma200 4h": _latest(averaged, when, window) == side,
                "wick 4h": _latest(wicked, when, window) == side,
                "streak 4h": _latest(streaked, when, window) == side,
                "skew 4h": _latest(skewed, when, window) == side,
                "session": _latest(sessioned, when, 3600.0) == side,
                "slope 1d": _latest(sloped_1d, when, 6 * 24 * 3600.0) == side,
                "fvg 4h": _latest(fvgs, when, window) == side,
                "fvg 4h+loud": _latest(fvgs, when, window) == side and noisy,
                "displace 4h+loud": _latest(pushed_by, when, window) == side and noisy,
                "slope+displace 4h": _latest(sloped, when, window) == side
                and _latest(pushed_by, when, window) == side,
            }
            for reward in REWARDS:
                stop = price - side * risk
                target = price + side * reward * risk
                got = _settle(highs, lows, at, side, stop, target, reward)
                flip = _settle(
                    highs,
                    lows,
                    at,
                    -side,
                    price + side * risk,
                    price - side * reward * risk,
                    reward,
                )
                half = 0 if when < middle else 1
                for name, passes in rules.items():
                    if not passes:
                        continue
                    out.setdefault((name, edge, reward, half), []).append((got, reward))
                    out.setdefault((f"{name}~flip", edge, reward, half), []).append((flip, reward))
    return out


def _settle(
    highs: np.ndarray,
    lows: np.ndarray,
    at: int,
    side: int,
    stop: float,
    target: float,
    reward: float,
) -> float:
    """Realised R over the hold: `reward` on a win, -1 on a loss, 0 unresolved.

    A bar that reaches both is charged as a loss, because assuming the
    favourable order is how a backtest invents edge.
    """
    for k in range(at + 1, min(at + 1 + HOLD, len(highs))):
        hit = highs[k] >= target if side > 0 else lows[k] <= target
        out = lows[k] <= stop if side > 0 else highs[k] >= stop
        if hit and out:
            return -1.0
        if hit:
            return reward
        if out:
            return -1.0
    return 0.0


def _walk(n: int, rng: random.Random) -> dict[str, np.ndarray]:
    """Generated bars through the identical pipeline. **The null for each rule.**

    Not a sanity check but the comparison itself. The structural stop sits at
    the swing price has only just left, so it is nearer recent action than its
    mirror - enough to make a rule and its flip differ by **0.17** on a random
    walk, with no market in the data. Zero is therefore the wrong null; each
    rule's own reading here is, and `real - walk` is the number worth printing.
    """
    step = 0.002
    closes = [100.0]
    for _ in range(n):
        closes.append(closes[-1] * math.exp(rng.gauss(0.0, step)))
    price = np.asarray(closes[1:], dtype=float)
    wick = np.abs(np.asarray([rng.gauss(0.0, step) for _ in range(n)]))
    opens = np.concatenate([[price[0]], price[:-1]])
    return {
        "time": np.arange(n, dtype=float) * 3600.0,
        "open": opens,
        "high": np.maximum(price, opens) * np.exp(wick),
        "low": np.minimum(price, opens) * np.exp(-wick),
        "close": price,
    }


def _read(pooled: dict, key) -> tuple[int, float, float] | None:
    """`(trades, win rate among resolved, mean R)` or None if too thin.

    The win rate and the money are both returned because they answer different
    questions and a difference in one does not imply a difference in the other:
    a rule can win more often at a reward where winning more often does not
    pay for the crossing.
    """
    rows = pooled.get(key)
    if not rows:
        return None
    resolved = [v for v, _ in rows if v != 0]
    if len(rows) < 60 or len(resolved) < 40:
        return None
    return (
        len(rows),
        sum(1 for v in resolved if v > 0) / len(resolved),
        sum(v for v, _ in rows) / len(rows),
    )


def main() -> None:
    print(
        "Entry and exit rules, scored against the geometry they carry.\n"
        f"{FRAME} entries with {HIGHER} bias, structural stops, hold {HOLD} bars,\n"
        f"cost {COST} of the stop. `win-geom` is the realised win rate less\n"
        "1/(1+r) - the only column that can be an edge. `~flip` is the same\n"
        "setup with the side reversed and must straddle zero with it.\n"
    )
    rng = random.Random(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)

    # Per (rule, class, half), pooled over instruments. The thirty-six cells a
    # rule produces are correlated, so the independent units are the classes,
    # and the halves say whether an effect is stable in time.
    got: dict[tuple[str, str, int], list[tuple[float, float]]] = {}
    for label in TRADED:
        if label not in groups:
            continue
        for name in sorted(groups[label])[:PER_CLASS]:
            bars = load(name, FRAME)
            if bars is None:
                continue
            cut = {k: v[-LIMIT:] for k, v in bars.items()}
            top = _resample(cut, HIGHER_SECONDS)
            for key, rows in run(cut, top, rng).items():
                rule, _edge, reward, half = key
                got.setdefault((rule, label, half), []).extend(rows)

    rules = sorted({k[0] for k in got if not k[0].endswith("~flip")})
    classes = sorted({k[1] for k in got})
    print(
        f"  {'rule':<19}{'half':>5}{'cls':>5}{'win gap':>9}{'+/-':>7}"
        f"{'R gap':>8}{'cls +':>7}{'R real':>9}{'R flip':>9}{'best net':>10}"
    )
    for rule in rules:
        for half in (0, 1):
            gaps, monies, reals, flips, trades = [], [], [], [], 0
            for label in classes:
                real = _read(got, (rule, label, half))
                flip = _read(got, (f"{rule}~flip", label, half))
                if real is None or flip is None:
                    continue
                gaps.append(real[1] - flip[1])
                # Cost cancels in the gap, so what is left is the directional
                # content in units of risk - **but a gap is not money.** Both
                # arms can be net negative while differing by 0.20R, so the
                # absolute figures are carried too and `best net` is the better
                # side after cost. A stable gap with both sides under water is
                # a real finding about direction and not a tradeable one.
                monies.append(real[2] - flip[2])
                reals.append(real[2] - COST)
                flips.append(flip[2] - COST)
                trades += real[0]
            if not gaps:
                continue
            # Standard error of a win-rate difference, pooled over the classes
            # that contributed, at the rate those classes won at.
            spread = (
                statistics.pstdev(gaps) / math.sqrt(len(gaps)) if len(gaps) > 1 else float("nan")
            )
            best = max(statistics.median(reals), statistics.median(flips))
            print(
                f"  {rule:<19}{half:>5}{len(gaps):>5}{statistics.median(gaps):>+9.4f}"
                f"{spread:>7.4f}{statistics.median(monies):>+8.3f}"
                f"{sum(1 for g in gaps if g > 0):>4}/{len(gaps):<2}"
                f"{statistics.median(reals):>+9.3f}{statistics.median(flips):>+9.3f}"
                f"{best:>+10.3f}"
            )


if __name__ == "__main__":
    main()
