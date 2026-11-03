"""The 2008 carry crash as a positive control, and the triangle as an integrity check.

**Run and reported before anything else in the study.** Brunnermeier, Nagel and
Pedersen, *Carry Trades and Currency Crashes* (2008) describe the unwind of the
carry trade in the summer and autumn of 2008 - carry crosses falling fast and
deep after building slowly - and that episode is inside this store's 19.25-year
window. So the control is not a convenience: **if a fear reading built here
does not light up in late 2008 on AUDJPY and NZDJPY, the reading is broken and
nothing else in the study means anything.**

Two checks, in order, both pre-registered before the run.

## 1. The triangle, which is an alignment test and not a discovery

`currency-triangles-are-the-positive-control` records that an FX screen missing
the triangles at t past -50 with weights at +-1 is broken. For a cross built by
multiplying its legs the identity is **exact in logs**, so the regression is
degenerate by construction: the weights are 1.0 to machine precision and the t
statistics come back at 1e15, which is a statement about float arithmetic and
not about the market.

What the check can actually fail on is a **shifted calendar**, and that is the
failure mode worth having an arm for. `plant_misalign` shifts one leg by k bars
and reruns the same screen, so the write-up can say what the check costs when
it is wrong rather than only that it passed.

## 2. The crash, with its pass rule fixed first

The reading is `fear_greed.basket_risk_off` - the six real basket legs, each
component oriented to risk-off - because a synthetic cross's range is a bound
inflated about 1.7x on the JPY pairs and three of `FearGreed`'s five components
read a range. The index is built from real bars only.

**The pass rule, all three parts required:**

1. the maximum of `risk_off` inside 2008-08-01 to 2009-03-31 is at or above the
   **99th percentile** of the whole sample;
2. the window's **mean** `risk_off` is the largest of the non-overlapping
   windows of the same length - about 20 of them over 19.25 years, so this is a
   rank test at about p 0.05 and is reported as such rather than as a p value
   it cannot support;
3. the **single most risk-off day of the 19.25 years** falls inside the window.

Reported separately for `volatile_off` and `directional_off`, because a pass on
the composite cannot say which half carried it - and the honest prediction is
that the volatility half carries it, `relationships-are-contemporaneous` having
measured volatility and tails large.

And **the power for it**, which a control that is expected to pass still needs:
`plant_crash` injects a crash of known depth into surrogate legs that contain
no 2008 and asks whether the index finds it, swept over depth. A control that
only ever passes on the one episode it was built for has not been tested.
"""

from __future__ import annotations

import datetime as dt
import math
import random

import numpy as np

import research.ideas.fear_greed as F

#: Depths swept by `plant_crash`, as the fraction a carry leg falls over
#: `CRASH_BARS`. The real synthetic AUDJPY fell 46.5% from 2008-07-21 to
#: 2008-10-26, which is 68 trading days, so the sweep brackets it.
CRASH_DEPTHS = (0.0, 0.05, 0.10, 0.20, 0.30, 0.45)

#: Bars the planted crash is spread over. 68 trading days, the real episode's
#: peak-to-trough length, so the planted event has the shape the control is
#: supposed to see rather than a one-bar jump no reading could miss.
CRASH_BARS = 68

#: Leg shifts swept by `plant_misalign`, in bars.
MISALIGN = (0, 1, 2, 5)


def _dates(ts: np.ndarray) -> list[dt.date]:
    return [dt.datetime.fromtimestamp(t, tz=dt.UTC).date() for t in ts]


def plant_misalign(held: dict[str, F.Series], shift: int) -> list[dict]:
    """The triangle screen with the legs' calendar shifted `shift` bars.

    The power arm for a check that is exact by construction. Each cross keeps
    its own bars and its legs are rolled forward by `shift`, which is exactly
    what a one-day calendar disagreement between two feeds looks like from
    outside. At `shift` 0 this is the check itself, and the numbers it reports
    are the ones the write-up quotes.

    Without this arm "weights 1.0, t 1e15" is unfalsifiable - it would read the
    same if the whole study were multiplying the wrong days together.
    """
    if shift == 0:
        return F.triangle_check(held)
    cut = len(held["audusd"].ts) - shift
    rolled: dict[str, F.Series] = {}
    for name, series in held.items():
        keep = slice(shift, shift + cut) if name in F.LEGS else slice(0, cut)
        rolled[name] = F.Series(
            feed=series.feed,
            venue=series.venue,
            interval=series.interval,
            ts=series.ts[:cut],
            open=series.open[keep],
            high=series.high[keep],
            low=series.low[keep],
            close=series.close[keep],
            synthetic=series.synthetic,
            kind=series.kind,
        )
    return F.triangle_check(rolled)


def window_rank(
    values: np.ndarray, mask: np.ndarray
) -> tuple[float, int, int, float, int]:
    """The window's mean, its rank among non-overlapping windows, its percentile.

    Returns `(mean, rank, tiles, overlapping_percentile, start)`. Rank 1 is the
    largest of `tiles` non-overlapping windows of the same width. The tiling is
    the honest number - `overlapping-windows-inflate-permutation-nulls` turned
    a level finding at p 0.015 into anchor overlap - and the overlapping
    percentile is reported beside it as the optimistic one, never alone.
    """
    width = int(mask.sum())
    if width < 2:
        raise ValueError(f"a {width}-bar window has no mean worth ranking")
    good = np.isfinite(values)
    start = int(np.argmax(mask))
    here = float(np.nanmean(values[mask]))

    # Tiled in phase with the window being tested, so the window *is* one of
    # the tiles. A fixed phase from index 0 splits a 172-bar window across two
    # tiles, each holding half the episode, and the episode then ranks behind
    # both halves of itself - which is how `volatile_off` read rank 3 of 28
    # before this line was in phase.
    tiles: list[float] = []
    for begin in range(start % width, len(values) - width + 1, width):
        block = values[begin : begin + width]
        if np.isfinite(block).sum() >= width // 2:
            tiles.append(float(np.nanmean(block)))
    rank = 1 + sum(1 for t in tiles if t > here)

    kernel = np.ones(width)
    filled = np.where(good, values, 0.0)
    sums = np.convolve(filled, kernel, mode="valid")
    counts = np.convolve(good.astype(float), kernel, mode="valid")
    rolling = np.where(counts >= width // 2, sums / np.maximum(counts, 1.0), np.nan)
    valid = rolling[np.isfinite(rolling)]
    pct = float((valid <= here).mean()) if len(valid) else float("nan")
    return here, rank, max(1, len(tiles)), pct, start


def crash_control(held: dict[str, F.Series], basket: F.Basket) -> dict:
    """The 2008 control, with its three pass criteria scored separately.

    Every number the pass rule names, plus the cross drawdowns over the same
    window, so a reader can see both that the index fired and that the thing
    it fired on was the episode Brunnermeier, Nagel and Pedersen describe.
    """
    ts = held["audusd"].ts
    dates = _dates(ts)
    mask = F.window_mask(ts, F.CRASH_FROM, F.CRASH_TO)
    out: dict = {
        "from": F.CRASH_FROM,
        "to": F.CRASH_TO,
        "bars_in_window": int(mask.sum()),
        "bars_total": int(len(ts)),
        "legs": list(basket.legs),
        "halves": {},
        "crosses": {},
    }
    for name in ("risk_off", "volatile_off", "directional_off"):
        values = getattr(basket, name)
        mean, rank, tiles, pct, _ = window_rank(values, mask)
        inside = values[mask]
        good = np.isfinite(values)
        peak = float(np.nanmax(inside))
        out["halves"][name] = {
            "window_mean": mean,
            "window_rank": rank,
            "window_tiles": tiles,
            "overlapping_pct": pct,
            "window_max": peak,
            "sample_q99": float(np.nanquantile(values[good], 0.99)),
            "sample_q95": float(np.nanquantile(values[good], 0.95)),
            "peak_pct": float((values[good] <= peak).mean()),
            "argmax_date": str(dates[int(np.nanargmax(np.where(good, values, -np.inf)))]),
            "argmax_in_window": bool(mask[int(np.nanargmax(np.where(good, values, -np.inf)))]),
            "window_peak_date": str(
                dates[int(np.nanargmax(np.where(mask & good, values, -np.inf)))]
            ),
        }
    for recipe in F.CROSSES:
        series = held[recipe.name]
        inside = series.close[mask]
        peak = int(np.argmax(inside))
        trough = peak + int(np.argmin(inside[peak:]))
        when = [d for d, m in zip(dates, mask, strict=True) if m]
        out["crosses"][recipe.name] = {
            "kind": recipe.kind,
            "peak": float(inside[peak]),
            "peak_date": str(when[peak]),
            "trough": float(inside[trough]),
            "trough_date": str(when[trough]),
            "drawdown": float(inside[trough] / inside[peak] - 1.0),
            "bars_peak_to_trough": trough - peak,
            "window_return": float(inside[-1] / inside[0] - 1.0),
        }
    # Breadth at the index's own peak: how many of the six legs read risk-off
    # on the most fearful day. A reading carried by one leg is not a basket.
    good = np.isfinite(basket.risk_off)
    top = int(np.nanargmax(np.where(good, basket.risk_off, -np.inf)))
    out["breadth_at_peak"] = int(basket.breadth[top])
    out["breadth_legs"] = len(basket.legs)
    out["episodes"] = episodes(
        basket.risk_off, ts, int(mask.sum()), phase=int(np.argmax(mask))
    )
    return out


def episodes(
    values: np.ndarray, ts: np.ndarray, width: int, *, phase: int, keep: int = 6
) -> list[dict]:
    """The `keep` most risk-off non-overlapping windows, largest first.

    The table that makes the control's one failure readable. Criterion 3 asked
    for the global maximum to fall in 2008 and it does not; without knowing
    *what* beat it that reads as a broken index, and with the list it reads as
    the index ranking two real risk-off episodes in an order the
    pre-registration did not anticipate.

    `phase` is the tested window's own start, so this tiling is **the same
    tiling `window_rank` ranks against**. Off by a phase the 2008 episode
    splits across two tiles and ranks 2nd here while ranking 1st there, and
    the write-up would carry two rankings of the same thing.
    """
    dates = _dates(ts)
    tiles: list[dict] = []
    for begin in range(phase % width, len(values) - width + 1, width):
        block = values[begin : begin + width]
        if np.isfinite(block).sum() < width // 2:
            continue
        tiles.append(
            {
                "from": str(dates[begin]),
                "to": str(dates[begin + width - 1]),
                "mean": float(np.nanmean(block)),
            }
        )
    tiles.sort(key=lambda row: -row["mean"])
    return tiles[:keep]


def plant_crash(
    held: dict[str, F.Series], depth: float, *, rng: random.Random, span: int = 20
) -> dict:
    """Does the index find a crash of known depth planted in surrogate legs?

    The power arm for the control. Every basket leg is replaced by a
    `walk-geometry` surrogate - this market's step distribution and wickiness,
    no 2008 - and then a crash of fractional depth `depth` is spread over
    `CRASH_BARS` consecutive bars at a random start, **with each leg's own
    risk-off sign**: the carry legs fall, the havens rise, which is the event
    the index is built to see rather than a common shock it would see anyway.

    Reports whether the index's global maximum lands inside the planted window
    and what percentile the window's own peak reaches. `depth` 0 is a plain
    surrogate and must come back at chance, which is `CRASH_BARS / n` - the
    arm that must read nothing, and the one that catches an index
    manufacturing an answer out of its own warm-up.
    """
    legs: dict[str, F.Series] = {}
    n = len(held["audusd"].close)
    start = rng.randrange(span * 2, n - CRASH_BARS - span)
    ramp = np.zeros(n)
    # Log-linear so the move is a constant daily rate rather than a step, and
    # held afterwards: a carry crash does not retrace in a week.
    ramp[start : start + CRASH_BARS] = np.linspace(
        0.0, 1.0, CRASH_BARS, endpoint=True
    )
    ramp[start + CRASH_BARS :] = 1.0
    # `RISK_OFF_SIGN` is +1 where a **rise** is risk-off (gold, usdcad) and -1
    # where a fall is (audusd, nzdusd, usdjpy, usdchf), so a leg's log move
    # over the crash is `sign * rate` with `rate` **positive**.
    #
    # The first version of this line used `log1p(-depth)`, which is negative,
    # and so planted a rally: the index's argmax then missed the planted
    # window at every depth and the window's own peak percentile *fell* from
    # 0.98 to 0.08 as the crash got deeper. That is what a planted effect with
    # one sign backwards looks like - a test with no power - and it is the
    # argument for having the power arm at all.
    rate = -math.log1p(-depth) if depth > 0.0 else 0.0
    for feed in F.RISK_OFF_SIGN:
        base = F.walk_geometry(held[feed], rng)
        move = np.exp(F.RISK_OFF_SIGN[feed] * rate * ramp)
        legs[feed] = F.Series(
            feed=base.feed,
            venue=base.venue,
            interval=base.interval,
            ts=base.ts,
            open=base.open * move,
            high=base.high * move,
            low=base.low * move,
            close=base.close * move,
        )
    moods = {f: F.mood_path(s) for f, s in legs.items()}
    basket = F.basket_risk_off(moods)
    window = np.zeros(n, dtype=bool)
    window[start : start + CRASH_BARS] = True
    good = np.isfinite(basket.risk_off)
    found = int(np.nanargmax(np.where(good, basket.risk_off, -np.inf)))
    peak = float(np.nanmax(basket.risk_off[window & good])) if (window & good).any() else np.nan
    return {
        "depth": depth,
        "start": start,
        "argmax_in_window": bool(window[found]),
        "window_peak_pct": float((basket.risk_off[good] <= peak).mean()),
        "chance": CRASH_BARS / float(good.sum() or 1),
        "volatile_in_window": bool(
            window[int(np.nanargmax(np.where(good, basket.volatile_off, -np.inf)))]
        ),
        "directional_in_window": bool(
            window[int(np.nanargmax(np.where(good, basket.directional_off, -np.inf)))]
        ),
    }
