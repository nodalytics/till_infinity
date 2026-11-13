"""The confluence blueprint's candle definitions, drawn from bars that passed them.

Written for `docs/specs/2026-11-13-multi-structural-confluence-blueprint.md`.
Arithmetic that is subtly wrong looks exactly like arithmetic that is right, so
every definition in that spec is implemented here **verbatim from the
blueprint** - not from `dual_engine_v6.py`, which differs - and then run over
eight years of the broker's own 5-minute bars so the figures show bars the
definition actually selected.

Two modes:

* `--rates` prints how often each definition fires on each frame, per
  instrument. That is the input to the frequency arithmetic in the spec: a
  conjunction of five gates is only measurable if the gates fire.
* `--figures` writes the PNGs the spec references.

## What the implementation choices are, and why they matter

* **Frames are folded by bar count** - 3, 12, 48 and 288 five-minute bars for
  15m/1H/4H/1D - exactly as `dual_engine_v6.Frame.fold` does, so the figures
  describe the bars that implementation would see. A calendar fold would give
  different 1D candles across a weekend and the two are not interchangeable.
* **ATR is Wilder's, 14 periods, on the frame's own candles**, which is what
  `ATR_t` means everywhere in the blueprint.
* **No bar is synthesised.** Every figure names the instrument, the frame and
  the UTC timestamp of the bar it drew, and the figures are regenerated from
  the catalogue rather than stored.

Run as `uv run --with matplotlib python research/ideas/confluence_figures.py --rates`.
"""

from __future__ import annotations

import argparse
import glob
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

CATALOGUE = Path.home() / "till-data" / "mt5-deep"
SPEC = "5-MINUTE-LAST-EXTERNAL"

#: Nautilus stores prices as a 128-bit fixed-point integer with 16 decimal
#: places. Reading the parquet directly rather than through the catalogue keeps
#: three million bars out of Python objects.
PRICE_SCALE = 1e16

#: Execution bars per frame, matching `dual_engine_v6`.
FRAMES = {"15m": 3, "1h": 12, "4h": 48, "1d": 288}

ATR_PERIOD = 14

#: The blueprint's grid centre: q 85, N 100, q_chop 30, tau 0.015, k 3.
Q = 85
N_PCT = 100
Q_CHOP = 30
TAU = 0.015
K = 3

#: Bjorgum pivot lookback, section 4.
PIVOT_K = 7


@dataclass(slots=True)
class Candles:
    """One frame of one instrument, as parallel arrays. Index 0 is oldest."""

    symbol: str
    frame: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    def __len__(self) -> int:
        return len(self.close)

    @property
    def body(self) -> np.ndarray:
        return np.abs(self.close - self.open)

    @property
    def span(self) -> np.ndarray:
        return self.high - self.low

    @property
    def body_ratio(self) -> np.ndarray:
        """`BR_t = B_t / R_t`, with a dead bar scored 0 rather than divided by.

        A zero-range bar passes every `BR <= x` test trivially, which is how a
        weekend of flat bars would read as a market in chop.
        """
        return np.divide(self.body, self.span, out=np.zeros_like(self.body), where=self.span > 0)

    @property
    def upper_wick(self) -> np.ndarray:
        return self.high - np.maximum(self.open, self.close)

    @property
    def lower_wick(self) -> np.ndarray:
        return np.minimum(self.open, self.close) - self.low


# --- loading -----------------------------------------------------------------


def load(where: Path, symbol: str) -> Candles:
    """5-minute bars for one symbol, straight out of the parquet."""
    import pyarrow.parquet as pq

    folder = where / "data" / "bar" / f"{symbol}.MT5-{SPEC}"
    files = sorted(glob.glob(str(folder / "*.parquet")))
    if not files:
        raise SystemExit(f"no bars under {folder}")
    columns: dict[str, list[np.ndarray]] = {k: [] for k in ("open", "high", "low", "close", "ts")}
    for path in files:
        table = pq.read_table(path)
        for name in ("open", "high", "low", "close"):
            raw = np.frombuffer(
                b"".join(table.column(name).to_pylist()), dtype=np.int64
            ).reshape(-1, 2)[:, 0]
            columns[name].append(raw.astype(np.float64) / PRICE_SCALE)
        columns["ts"].append(np.asarray(table.column("ts_event").to_pylist(), dtype=np.int64))
    joined = {k: np.concatenate(v) for k, v in columns.items()}
    order = np.argsort(joined["ts"], kind="stable")
    return Candles(
        symbol=symbol,
        frame="5m",
        ts=joined["ts"][order],
        open=joined["open"][order],
        high=joined["high"][order],
        low=joined["low"][order],
        close=joined["close"][order],
    )


def fold(base: Candles, frame: str) -> Candles:
    """Aggregate by bar count, the way `dual_engine_v6.Frame.fold` does.

    Count, not calendar: a frame closes every `span` execution bars regardless
    of what the clock says. The implementation this spec is written against
    does the same, and a calendar fold would put the 1D candles in different
    places across a weekend.
    """
    span = FRAMES[frame]
    usable = (len(base) // span) * span
    shaped = {
        name: getattr(base, name)[:usable].reshape(-1, span)
        for name in ("open", "high", "low", "close", "ts")
    }
    return Candles(
        symbol=base.symbol,
        frame=frame,
        ts=shaped["ts"][:, -1],
        open=shaped["open"][:, 0],
        high=shaped["high"].max(axis=1),
        low=shaped["low"].min(axis=1),
        close=shaped["close"][:, -1],
    )


def atr(bars: Candles, period: int = ATR_PERIOD) -> np.ndarray:
    """Wilder's ATR on the frame's own candles. NaN until it is seeded."""
    high, low, close = bars.high, bars.low, bars.close
    previous = np.concatenate(([np.nan], close[:-1]))
    true_range = np.maximum(
        high - low, np.maximum(np.abs(high - previous), np.abs(low - previous))
    )
    true_range[0] = high[0] - low[0]
    out = np.full(len(bars), np.nan)
    if len(bars) <= period:
        return out
    seed = true_range[:period].mean()
    out[period - 1] = seed
    running = seed
    for i in range(period, len(bars)):
        running = (running * (period - 1) + true_range[i]) / period
        out[i] = running
    return out


def rolling_percentile(values: np.ndarray, window: int, q: float) -> np.ndarray:
    """`Percentile_q(X_{t-1} .. X_{t-N})` - the prior N bars, excluding t.

    Excluding the current bar is the blueprint's own indexing and it matters:
    including `B_t` in the sample `B_t` is graded against makes a very large
    body raise its own threshold.
    """
    out = np.full(len(values), np.nan)
    if len(values) <= window:
        return out
    view = np.lib.stride_tricks.sliding_window_view(values[:-1], window)
    out[window:] = np.percentile(view, q, axis=1)
    return out


# --- section 2: single-candle anatomy ----------------------------------------


def is_impulse(bars: Candles, atr_values: np.ndarray) -> np.ndarray:
    """`B >= 0.8 ATR AND BR >= 0.60 AND close within 0.25 R of the extreme`.

    Returns +1 bullish, -1 bearish, 0 otherwise. No FVG is required, which is
    the whole difference from a displacement.
    """
    body, span, ratio = bars.body, bars.span, bars.body_ratio
    big = (body >= 0.8 * atr_values) & (ratio >= 0.60) & (span > 0)
    up = big & (bars.close >= bars.high - 0.25 * span)
    down = big & (bars.close <= bars.low + 0.25 * span)
    return np.where(up, 1, np.where(down, -1, 0))


def is_displacement(bars: Candles, atr_values: np.ndarray, q: float, window: int) -> np.ndarray:
    """`B >= 1.5 ATR AND B >= P_q AND BR >= 0.70` plus the FVG against t-2."""
    body, ratio = bars.body, bars.body_ratio
    threshold = rolling_percentile(body, window, q)
    big = (body >= 1.5 * atr_values) & (body >= threshold) & (ratio >= 0.70)
    gap_up = np.full(len(bars), False)
    gap_down = np.full(len(bars), False)
    gap_up[2:] = bars.low[2:] > bars.high[:-2]
    gap_down[2:] = bars.high[2:] < bars.low[:-2]
    up = big & gap_up & (bars.close > bars.open)
    down = big & gap_down & (bars.close < bars.open)
    return np.where(up, 1, np.where(down, -1, 0))


def is_pin_bar(bars: Candles) -> np.ndarray:
    """`wick >= 2 B AND BR <= 0.35 AND close in the far quarter of the range`."""
    span, body, ratio = bars.span, bars.body, bars.body_ratio
    alive = span > 0
    small = alive & (ratio <= 0.35)
    up = small & (bars.lower_wick >= 2.0 * body) & (bars.close >= bars.high - 0.25 * span)
    down = small & (bars.upper_wick >= 2.0 * body) & (bars.close <= bars.low + 0.25 * span)
    return np.where(up, 1, np.where(down, -1, 0))


def choppy_parts(bars: Candles, q_chop: float, window: int) -> dict[str, np.ndarray]:
    """The three branches of the blueprint's choppy candle, separately.

    Reported separately because they are an **OR**, and an OR is only as strict
    as its loosest member: an inside bar alone marks a candle choppy however
    large its body is.
    """
    span, ratio = bars.span, bars.body_ratio
    threshold = rolling_percentile(span, window, q_chop)
    small = (span <= threshold) & (ratio <= 0.35)
    overlap = np.full(len(bars), False)
    inside = np.full(len(bars), False)
    if len(bars) > 1:
        top = np.minimum(bars.high[1:], bars.high[:-1])
        bottom = np.maximum(bars.low[1:], bars.low[:-1])
        floor = np.minimum(span[1:], span[:-1])
        share = np.divide(top - bottom, floor, out=np.zeros_like(floor), where=floor > 0)
        overlap[1:] = share >= 0.60
        inside[1:] = (bars.high[1:] <= bars.high[:-1]) & (bars.low[1:] >= bars.low[:-1])
    return {"small": small, "overlap": overlap, "inside": inside, "any": small | overlap | inside}


# --- section 3: multi-candle anatomy -----------------------------------------


def is_engulfing(bars: Candles) -> np.ndarray:
    """`O_t <= C_{t-1} AND C_t > O_{t-1} AND B_t > B_{t-1}`, and its mirror.

    **No colour clause.** The textbook pattern needs the prior candle to be the
    opposite colour; this one does not, so a larger continuation candle opening
    at the prior close counts. `classic_engulfing` is the comparison.
    """
    out = np.zeros(len(bars), dtype=int)
    if len(bars) < 2:
        return out
    body = bars.body
    up = (
        (bars.open[1:] <= bars.close[:-1])
        & (bars.close[1:] > bars.open[:-1])
        & (body[1:] > body[:-1])
    )
    down = (
        (bars.open[1:] >= bars.close[:-1])
        & (bars.close[1:] < bars.open[:-1])
        & (body[1:] > body[:-1])
    )
    out[1:] = np.where(up, 1, np.where(down, -1, 0))
    return out


def classic_engulfing(bars: Candles) -> np.ndarray:
    """Opposite colours and the prior body wholly covered - the textbook rule."""
    out = np.zeros(len(bars), dtype=int)
    if len(bars) < 2:
        return out
    top = np.maximum(bars.open, bars.close)
    bottom = np.minimum(bars.open, bars.close)
    bull_prior = bars.close[:-1] < bars.open[:-1]
    bear_prior = bars.close[:-1] > bars.open[:-1]
    covers = (bottom[1:] <= bottom[:-1]) & (top[1:] >= top[:-1])
    up = covers & bull_prior & (bars.close[1:] > bars.open[1:])
    down = covers & bear_prior & (bars.close[1:] < bars.open[1:])
    out[1:] = np.where(up, 1, np.where(down, -1, 0))
    return out


def sequential_parts(bars: Candles, atr_values: np.ndarray, k: int = K) -> dict[str, np.ndarray]:
    """The four clauses of the sequential impulse leg, each on its own.

    Separately because the spec's finding is about one of them: as written, the
    efficiency numerator spans `C_t - C_{t-k+1}` - two bars for k=3 - while the
    denominator sums `k` bodies, so a perfect gapless three-bar run scores
    **2/3 = 0.667** against a 0.70 threshold and fails its own definition.
    """
    n = len(bars)
    body, close, open_ = bars.body, bars.close, bars.open
    first = k - 1  # the index offset of the leg's first candle, t-k+1

    push = np.full(n, np.nan)
    efficiency = np.full(n, np.nan)
    consistent_up = np.zeros(n, dtype=bool)
    consistent_down = np.zeros(n, dtype=bool)
    stacked_up = np.zeros(n, dtype=bool)
    stacked_down = np.zeros(n, dtype=bool)

    bodies = np.zeros(n)
    for i in range(k):
        bodies[first:] += body[first - i : n - i]
    with np.errstate(invalid="ignore"):
        push[first:] = np.abs(close[first:] - open_[: n - first])
        efficiency[first:] = np.divide(
            np.abs(close[first:] - close[: n - first]),
            bodies[first:],
            out=np.full(n - first, np.nan),
            where=bodies[first:] > 0,
        )
    bullish = (close > open_).astype(int)
    bearish = (close < open_).astype(int)
    up_count = np.zeros(n, dtype=int)
    down_count = np.zeros(n, dtype=int)
    for i in range(k):
        up_count[first:] += bullish[first - i : n - i]
        down_count[first:] += bearish[first - i : n - i]
    consistent_up[first:] = up_count[first:] >= k - 1
    consistent_down[first:] = down_count[first:] >= k - 1
    stacked_up[first:] = bars.low[first:] > bars.high[: n - first]
    stacked_down[first:] = bars.high[first:] < bars.low[: n - first]

    big = push >= 2.0 * atr_values
    efficient = efficiency >= 0.70
    return {
        "push": push,
        "efficiency": efficiency,
        "big": big,
        "efficient": efficient,
        "consistent_up": consistent_up,
        "consistent_down": consistent_down,
        "stacked_up": stacked_up,
        "stacked_down": stacked_down,
        "up": big & efficient & consistent_up & stacked_up,
        "down": big & efficient & consistent_down & stacked_down,
    }


def choppy_block(bars: Candles, atr_values: np.ndarray, k: int) -> dict[str, np.ndarray]:
    """`max(H) - min(L) <= 1.5 ATR` and `|C_t - C_{t-k}| / sum R <= 0.30`.

    The block is read as the `k + 1` candles `t-k .. t`, because the efficiency
    clause names `C_{t-k}` and a block that did not contain it would be
    measuring a return it does not cover.
    """
    n = len(bars)
    span = bars.span
    top = np.full(n, np.nan)
    bottom = np.full(n, np.nan)
    total = np.zeros(n)
    for i in range(k + 1):
        window = slice(k, n)
        source = slice(k - i, n - i)
        top[window] = np.fmax(top[window], bars.high[source])
        bottom[window] = np.fmin(bottom[window], bars.low[source])
        total[window] += span[source]
    reach = top - bottom
    efficiency = np.full(n, np.nan)
    efficiency[k:] = np.divide(
        np.abs(bars.close[k:] - bars.close[: n - k]),
        total[k:],
        out=np.full(n - k, np.nan),
        where=total[k:] > 0,
    )
    tight = reach <= 1.5 * atr_values
    inert = efficiency <= 0.30
    return {"reach": reach, "efficiency": efficiency, "tight": tight, "inert": inert,
            "block": tight & inert}


# --- section 4: structural anatomy -------------------------------------------


def bjorgum_pivots(bars: Candles, k: int = PIVOT_K) -> dict[str, np.ndarray]:
    """`H_{t-k} > H_{t-2k} AND H_{t-k} > H_t` - a three-point test, as written.

    **This is not a swing high.** It compares the candidate to exactly two
    bars, `t-2k` and `t`, where `dual_engine_v6.pivots` compares it to every
    bar within `k` either side. The rate difference is in `--rates`.
    """
    n = len(bars)
    high_at = np.zeros(n, dtype=bool)
    low_at = np.zeros(n, dtype=bool)
    if n > 2 * k:
        window = slice(2 * k, n)
        candidate = slice(k, n - k)
        far = slice(0, n - 2 * k)
        high_at[candidate] = (bars.high[candidate] > bars.high[far]) & (
            bars.high[candidate] > bars.high[window]
        )
        low_at[candidate] = (bars.low[candidate] < bars.low[far]) & (
            bars.low[candidate] < bars.low[window]
        )
    return {"high": high_at, "low": low_at}


def strict_pivots(bars: Candles, k: int = PIVOT_K) -> dict[str, np.ndarray]:
    """The swing `dual_engine_v6.pivots` finds: an extreme over the whole window."""
    n = len(bars)
    high_at = np.zeros(n, dtype=bool)
    low_at = np.zeros(n, dtype=bool)
    if n <= 2 * k:
        return {"high": high_at, "low": low_at}
    width = 2 * k + 1
    highs = np.lib.stride_tricks.sliding_window_view(bars.high, width).max(axis=1)
    lows = np.lib.stride_tricks.sliding_window_view(bars.low, width).min(axis=1)
    high_at[k : n - k] = bars.high[k : n - k] >= highs
    low_at[k : n - k] = bars.low[k : n - k] <= lows
    return {"high": high_at, "low": low_at}


def crt_sweep(bars: Candles, day_high: np.ndarray, day_low: np.ndarray) -> np.ndarray:
    """`H_t > H_D AND C_t < H_D` bearish; `L_t < L_D AND C_t > L_D` bullish."""
    bear = (bars.high > day_high) & (bars.close < day_high)
    bull = (bars.low < day_low) & (bars.close > day_low)
    return np.where(bull, 1, np.where(bear, -1, 0))


def previous_day_levels(base: Candles, frame: Candles) -> tuple[np.ndarray, np.ndarray]:
    """The last *closed* daily candle's extremes, aligned to `frame`'s bars."""
    daily = fold(base, "1d")
    highs = np.concatenate(([np.nan], daily.high[:-1]))
    lows = np.concatenate(([np.nan], daily.low[:-1]))
    where = np.searchsorted(daily.ts, frame.ts, side="left")
    where = np.clip(where, 0, len(daily) - 1)
    return highs[where], lows[where]


# --- the conjunctions --------------------------------------------------------

#: How many recent pivots an alignment test may match against. `v6.pivots`
#: keeps four highs and four lows, so this is the same budget.
RECENT_PIVOTS = 8


def pivot_levels(bars: Candles, finder, k: int = PIVOT_K) -> tuple[np.ndarray, np.ndarray]:
    """(confirmation timestamp, level) for every pivot the finder reports.

    **Confirmed at `t`, not at the pivot bar.** A pivot at `t-k` is only known
    at `t`, and using it earlier is the lookahead that makes a level study
    report structure it could not have traded.
    """
    found = finder(bars, k)
    rows: list[tuple[int, float]] = []
    for flag, price in (("high", bars.high), ("low", bars.low)):
        where = np.flatnonzero(found[flag])
        confirm = np.clip(where + k, 0, len(bars) - 1)
        rows.extend(zip(bars.ts[confirm].tolist(), price[where].tolist(), strict=True))
    rows.sort()
    if not rows:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    return (
        np.asarray([r[0] for r in rows], dtype=np.int64),
        np.asarray([r[1] for r in rows], dtype=np.float64),
    )


def aligned_any(
    prices: list[np.ndarray],
    at: np.ndarray,
    pivot_ts: np.ndarray,
    pivots_: np.ndarray,
    tolerance: np.ndarray,
    most: int = RECENT_PIVOTS,
) -> np.ndarray:
    """Does any of `prices` sit within `tolerance` of a recent confirmed pivot?"""
    out = np.zeros(len(at), dtype=bool)
    if len(pivot_ts) == 0:
        return out
    end = np.searchsorted(pivot_ts, at, side="right")
    start = np.maximum(end - most, 0)
    for i in range(len(at)):
        if end[i] <= start[i] or not np.isfinite(tolerance[i]):
            continue
        window = pivots_[start[i] : end[i]]
        for price in prices:
            if np.min(np.abs(window - price[i])) <= tolerance[i]:
                out[i] = True
                break
    return out


def align_to(source_ts: np.ndarray, values: np.ndarray, target_ts: np.ndarray) -> np.ndarray:
    """The most recent closed `source` value as of each `target` timestamp."""
    where = np.searchsorted(source_ts, target_ts, side="right") - 1
    out = np.full(len(target_ts), np.nan)
    live = where >= 0
    out[live] = values[where[live]]
    return out


#: How long a setup waits for its 1H confirmation, in nanoseconds. The same 48
#: hours `dual_engine_v6.ARM_NS` uses.
ARM_NS = 48 * 3600 * 1_000_000_000


@dataclass(slots=True)
class Engines:
    """Per-engine structural hit counts on one instrument, and where they are."""

    counts: dict[str, int]
    where: dict[str, np.ndarray]
    frames: dict[str, Candles]
    atrs: dict[str, np.ndarray]
    #: index -> (direction, zone low, zone high) for each hit, per engine.
    setups: dict[str, list[tuple[int, int, float, float]]]
    confirmed: dict[str, int]


def confirm_by_pin(
    hourly: Candles,
    pin: np.ndarray,
    setups: list[tuple[int, int, float, float]],
    source_ts: np.ndarray,
) -> int:
    """How many setups get a 1H pin bar, in their direction, touching the zone?

    The gate the blueprint puts on four of its five engines, measured rather
    than assumed. 48 hours is the window, matching `dual_engine_v6.ARM_NS`.
    """
    passed = 0
    for at, direction, low, high in setups:
        start = int(np.searchsorted(hourly.ts, source_ts[at], side="right"))
        stop = int(np.searchsorted(hourly.ts, source_ts[at] + ARM_NS, side="right"))
        if stop <= start:
            continue
        window = slice(start, stop)
        touched = (hourly.low[window] <= high) & (hourly.high[window] >= low)
        if np.any((pin[window] == direction) & touched):
            passed += 1
    return passed


def engines(base: Candles, loose: bool = True) -> Engines:
    """The structural half of each of the five engines, counted on real bars.

    **The attention gate and the 1H pin bar are deliberately not applied here.**
    Both are measured separately: the attention gate fires at its own
    percentile by construction (10.7-14.7% as measured in
    `research/docs/dual-engine-confluence.md`) and the 1H pin bar's marginal
    rate is in `--rates`. What this counts is the part that is pure candle and
    level geometry, so the spec's frequency arithmetic rests on a measurement
    for the structural gates and on a stated assumption for the other two.
    """
    frames = {name: fold(base, name) for name in FRAMES}
    atrs = {name: atr(bars) for name, bars in frames.items()}
    four, day, fifteen = frames["4h"], frames["1d"], frames["15m"]
    finder = bjorgum_pivots if loose else strict_pivots
    pivot_ts, pivots_ = pivot_levels(four, finder)

    def tol(target: Candles) -> np.ndarray:
        return TAU * align_to(four.ts, atrs["4h"], target.ts)

    counts: dict[str, int] = {}
    where: dict[str, np.ndarray] = {}

    # 1. statistical exhaustion: a 4H impulse or leg, on a pivot.
    leg4 = sequential_parts(four, atrs["4h"])
    anchor4 = (is_impulse(four, atrs["4h"]) != 0) | leg4["up"] | leg4["down"]
    on_pivot4 = aligned_any([four.open, four.close], four.ts, pivot_ts, pivots_, tol(four))
    hit = anchor4 & on_pivot4
    counts["1 exhaustion"] = int(hit.sum())
    where["1 exhaustion"] = np.flatnonzero(hit)

    # 2. choppy breakout: a block that ended on the prior bar, then a
    #    displacement or leg out of it, on a pivot.
    block = choppy_block(four, atrs["4h"], K)["block"]
    prior_block = np.concatenate(([False], block[:-1]))
    breakout = (is_displacement(four, atrs["4h"], Q, N_PCT) != 0) | leg4["up"] | leg4["down"]
    hit = prior_block & breakout & on_pivot4
    counts["2 choppy breakout"] = int(hit.sum())
    where["2 choppy breakout"] = np.flatnonzero(hit)

    # 3. daily engulfing sweeping a 4H pivot.
    engulf = is_engulfing(day)
    swept = np.where(engulf > 0, day.low, day.high)
    on_pivot_d = aligned_any([swept], day.ts, pivot_ts, pivots_, tol(day))
    hit = (engulf != 0) & on_pivot_d
    counts["3 engulfing"] = int(hit.sum())
    where["3 engulfing"] = np.flatnonzero(hit)

    # 4. CRT: a 15m sweep of the prior daily extreme, on a pivot.
    day_high, day_low = previous_day_levels(base, fifteen)
    sweep = crt_sweep(fifteen, day_high, day_low)
    extreme = np.where(sweep > 0, fifteen.low, fifteen.high)
    on_pivot_15 = aligned_any([extreme], fifteen.ts, pivot_ts, pivots_, tol(fifteen))
    hit = (sweep != 0) & on_pivot_15
    counts["4 crt"] = int(hit.sum())
    where["4 crt"] = np.flatnonzero(hit)

    # 5. displacement double rejection, phase 1: a 15m displacement whose wick
    #    swept a pivot.
    push = is_displacement(fifteen, atrs["15m"], Q, N_PCT)
    tip = np.where(push > 0, fifteen.high, fifteen.low)
    on_pivot_push = aligned_any([tip], fifteen.ts, pivot_ts, pivots_, tol(fifteen))
    hit = (push != 0) & on_pivot_push
    counts["5 displacement"] = int(hit.sum())
    where["5 displacement"] = np.flatnonzero(hit)

    # The direction and zone each setup would hand the 15m execution layer.
    # Exhaustion is the only reversal: the anchor pushed, the trade fades it.
    anchor_side = np.sign(four.close - four.open).astype(int)
    setups: dict[str, list[tuple[int, int, float, float]]] = {
        "1 exhaustion": _zones(four, where["1 exhaustion"], -anchor_side),
        "2 choppy breakout": _zones(four, where["2 choppy breakout"], anchor_side),
        "3 engulfing": _zones(day, where["3 engulfing"], engulf),
        "4 crt": _zones(fifteen, where["4 crt"], sweep),
        "5 displacement": _zones(fifteen, where["5 displacement"], push, origin=1),
    }
    pin1h = is_pin_bar(frames["1h"])
    confirmed = {
        name: confirm_by_pin(frames["1h"], pin1h, rows, frames[src].ts)
        for name, (rows, src) in {
            "1 exhaustion": (setups["1 exhaustion"], "4h"),
            "2 choppy breakout": (setups["2 choppy breakout"], "4h"),
            "3 engulfing": (setups["3 engulfing"], "1d"),
            "4 crt": (setups["4 crt"], "15m"),
            "5 displacement": (setups["5 displacement"], "15m"),
        }.items()
    }
    return Engines(
        counts=counts, where=where, frames=frames, atrs=atrs,
        setups=setups, confirmed=confirmed,
    )


def _zones(
    bars: Candles, at: np.ndarray, side: np.ndarray, origin: int = 0
) -> list[tuple[int, int, float, float]]:
    """(index, direction, zone low, zone high) for each hit.

    `origin` shifts the zone back a candle, which is what engine 5 does: its
    zone is the body of the candle **before** the displacement.
    """
    rows = []
    for i in at:
        i = int(i)
        j = max(i - origin, 0)
        low = float(min(bars.open[j], bars.close[j]))
        high = float(max(bars.open[j], bars.close[j]))
        direction = int(side[i]) if side.ndim else int(side)
        if direction == 0 or high <= low:
            continue
        rows.append((i, direction, low, high))
    return rows


# --- rates -------------------------------------------------------------------

SYMBOLS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")


def rates(where: Path, symbols: tuple[str, ...]) -> None:
    """How often each definition fires, per 1,000 candles of its own frame."""
    print(f"catalogue {where}, {SPEC}, q {Q} N {N_PCT} q_chop {Q_CHOP} k {K}\n")
    for symbol in symbols:
        base = load(where, symbol)
        start = datetime.fromtimestamp(base.ts[0] / 1e9, UTC).date()
        end = datetime.fromtimestamp(base.ts[-1] / 1e9, UTC).date()
        print(f"{symbol}: {len(base):,} 5m bars, {start} to {end}")
        for frame in ("15m", "1h", "4h", "1d"):
            bars = fold(base, frame)
            a = atr(bars)
            n = len(bars)
            per_k = 1000.0 / n
            impulse = is_impulse(bars, a)
            displacement = is_displacement(bars, a, Q, N_PCT)
            pin = is_pin_bar(bars)
            chop = choppy_parts(bars, Q_CHOP, N_PCT)
            engulf = is_engulfing(bars)
            leg = sequential_parts(bars, a)
            block = choppy_block(bars, a, K)
            loose = bjorgum_pivots(bars)
            strict = strict_pivots(bars)
            print(
                f"  {frame:<4} n {n:>7,} | impulse {np.count_nonzero(impulse) * per_k:>6.1f} "
                f"displace {np.count_nonzero(displacement) * per_k:>5.1f} "
                f"pin {np.count_nonzero(pin) * per_k:>6.1f} "
                f"engulf {np.count_nonzero(engulf) * per_k:>6.1f} "
                f"chop {np.count_nonzero(chop['any']) * per_k:>6.1f} "
                f"(small {np.count_nonzero(chop['small']) * per_k:>5.1f} "
                f"ovl {np.count_nonzero(chop['overlap']) * per_k:>6.1f} "
                f"ins {np.count_nonzero(chop['inside']) * per_k:>6.1f})"
            )
            legs = np.count_nonzero(leg["up"] | leg["down"])
            best = np.nanmax(leg["efficiency"]) if n > K else float("nan")
            classic = classic_engulfing(bars)
            # Does the efficiency clause reject legs for being *too* decisive?
            # Three strong bodies with no gaps cannot reach 0.70, so count the
            # runs that pass every other clause and fail only on efficiency.
            nearly = (
                leg["big"]
                & ((leg["consistent_up"] & leg["stacked_up"]) | (leg["consistent_down"] & leg["stacked_down"]))
            )
            print(
                f"       leg {legs * per_k:>6.3f} (push {np.count_nonzero(leg['big']) * per_k:>5.1f}"
                f" eff>=0.70 {np.count_nonzero(leg['efficient']) * per_k:>6.1f}"
                f" max eff {best:>7.3f}"
                f" fail-only-on-eff {np.count_nonzero(nearly & ~leg['efficient']) * per_k:>6.3f})"
                f" | block {np.count_nonzero(block['block']) * per_k:>6.1f}"
            )
            print(
                f"       pivot loose {np.count_nonzero(loose['high'] | loose['low']) * per_k:>6.1f}"
                f" strict {np.count_nonzero(strict['high'] | strict['low']) * per_k:>6.1f}"
                f" | engulf classic {np.count_nonzero(classic) * per_k:>6.1f}"
            )
            # `B >= 1.5 ATR` and `B >= P_q` are both "an unusually large body",
            # so the question is whether the percentile adds a second test or
            # restates the first. CLAUDE.md's `displace` vs `DISPLACE_C` entry
            # is the same comparison and found them agreeing on a quarter.
            over_atr = bars.body >= 1.5 * a
            over_pct = bars.body >= rolling_percentile(bars.body, N_PCT, Q)
            live = np.isfinite(a) & np.isfinite(rolling_percentile(bars.body, N_PCT, Q))
            union = np.count_nonzero((over_atr | over_pct) & live)
            both = np.count_nonzero(over_atr & over_pct & live)
            print(
                f"       body >= 1.5 ATR {np.count_nonzero(over_atr & live) * per_k:>6.1f}"
                f" | body >= P_{Q} {np.count_nonzero(over_pct & live) * per_k:>6.1f}"
                f" | jaccard {both / union if union else float('nan'):>5.3f}"
                f" | contradictions: impulse+choppy "
                f"{np.count_nonzero((impulse != 0) & chop['any']) * per_k:>6.1f}"
                f" displace+choppy {np.count_nonzero((displacement != 0) & chop['any']) * per_k:>5.1f}"
                f" pin+impulse {np.count_nonzero((pin != 0) & (impulse != 0)) * per_k:>5.1f}"
            )
        print()


def engine_rates(where: Path, symbols: tuple[str, ...]) -> None:
    """Structural conjunction counts per engine, over the whole catalogue."""
    print(f"catalogue {where}, structural gates; the attention gate is not applied\n")
    totals: dict[str, int] = {}
    strict_totals: dict[str, int] = {}
    confirmations: dict[str, int] = {}
    days = 0.0
    for symbol in symbols:
        base = load(where, symbol)
        days = max(days, (base.ts[-1] - base.ts[0]) / 1e9 / 86400)
        for label, book in (("loose", True), ("strict", False)):
            found = engines(base, loose=book)
            bucket = totals if book else strict_totals
            for name, count in found.counts.items():
                bucket[name] = bucket.get(name, 0) + count
            rows = ", ".join(
                f"{k} {v}/{found.confirmed.get(k, 0)}" for k, v in sorted(found.counts.items())
            )
            print(f"  {symbol:<7} {label:<7} {rows}")
            if book:
                for name, count in found.confirmed.items():
                    confirmations[name] = confirmations.get(name, 0) + count
    print(f"\n  five instruments, {days:.0f} days, Bjorgum pivot as written.")
    print("  structural = candle and level geometry only; +pin = a 1H pin bar in the")
    print("  setup's direction touching its zone inside 48h.\n")
    print(f"    {'engine':<20} {'structural':>10} {'+1H pin':>9} {'pass':>7}   strict-pivot")
    for name in sorted(totals):
        passed = confirmations.get(name, 0)
        share = passed / totals[name] if totals[name] else float("nan")
        print(
            f"    {name:<20} {totals[name]:>10,} {passed:>9,} {share:>6.1%}   "
            f"{strict_totals[name]:>7,}"
        )


# --- drawing -----------------------------------------------------------------

UP = "#1b7f5a"
DOWN = "#b4432e"
EDGE = "#2a2a2a"
MARK = "#1f4e9c"
BAND = "#cfd9ee"


def when(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1e9, UTC).strftime("%Y-%m-%d %H:%M")


def draw_candles(axis, bars: Candles, lo: int, hi: int, focus: tuple[int, ...] = ()) -> None:
    """Candles `lo..hi` on one axis, with `focus` bars drawn at full strength."""
    for i in range(lo, hi):
        up = bars.close[i] >= bars.open[i]
        colour = UP if up else DOWN
        strong = i in focus or not focus
        axis.plot(
            [i, i],
            [bars.low[i], bars.high[i]],
            color=EDGE if strong else "#9aa0a6",
            linewidth=1.0 if strong else 0.7,
            zorder=2,
            alpha=1.0 if strong else 0.45,
        )
        bottom = min(bars.open[i], bars.close[i])
        height = abs(bars.close[i] - bars.open[i]) or (bars.high[i] - bars.low[i]) * 1e-3
        axis.add_patch(
            __import__("matplotlib").patches.Rectangle(
                (i - 0.32, bottom),
                0.64,
                height,
                facecolor=colour,
                edgecolor=EDGE,
                linewidth=0.7,
                zorder=3,
                alpha=1.0 if strong else 0.35,
            )
        )
    axis.set_xlim(lo - 0.8, hi - 0.2)
    span = bars.high[lo:hi].max() - bars.low[lo:hi].min()
    axis.set_ylim(bars.low[lo:hi].min() - 0.12 * span, bars.high[lo:hi].max() + 0.12 * span)
    axis.set_xticks([])
    axis.tick_params(labelsize=7)
    for side in ("top", "right", "bottom"):
        axis.spines[side].set_visible(False)


def typical(flags: np.ndarray, statistic: np.ndarray, pad: int) -> int | None:
    """The qualifying bar whose statistic is the median of all qualifiers.

    **Median, not maximum.** Drawing the biggest example of a definition shows
    what it looks like at its best; the question here is what it selects
    *usually*, so the middle one is the honest draw.
    """
    where = np.flatnonzero(flags)
    where = where[(where >= pad) & (where < len(flags) - pad)]
    if len(where) == 0:
        return None
    values = statistic[where]
    order = np.argsort(values)
    return int(where[order[len(order) // 2]])


def _panel(axis, bars: Candles, at: int, pad: int, title: str, note: str) -> None:
    draw_candles(axis, bars, at - pad, at + pad + 1, focus=(at,))
    axis.axvline(at, color=MARK, linewidth=0.8, linestyle=":", zorder=1)
    axis.set_title(title, fontsize=9, loc="left")
    axis.set_xlabel(note, fontsize=7, labelpad=6)


def figure_single(base: Candles, frame: str, out: Path) -> list[str]:
    """Impulse, displacement, pin and the three choppy branches, side by side."""
    import matplotlib.pyplot as plt

    bars = fold(base, frame)
    a = atr(bars)
    impulse = is_impulse(bars, a)
    displacement = is_displacement(bars, a, Q, N_PCT)
    pin = is_pin_bar(bars)
    chop = choppy_parts(bars, Q_CHOP, N_PCT)
    ratio = bars.body_ratio
    with np.errstate(invalid="ignore", divide="ignore"):
        over_atr = bars.body / a

    picks = [
        ("IsImpulse", impulse != 0, over_atr),
        ("IsDisplacement", displacement != 0, over_atr),
        ("IsPinBar", pin != 0, np.maximum(bars.upper_wick, bars.lower_wick) / np.where(bars.body > 0, bars.body, np.nan)),
        ("IsChoppy - statistical smallness", chop["small"], bars.span),
        ("IsChoppy - high overlap", chop["overlap"], ratio),
        ("IsChoppy - inside bar", chop["inside"], ratio),
    ]
    figure, axes = plt.subplots(2, 3, figsize=(13.5, 7.2))
    said: list[str] = []
    for axis, (name, flags, statistic) in zip(axes.ravel(), picks, strict=True):
        at = typical(flags, statistic, pad=5)
        if at is None:
            axis.set_axis_off()
            continue
        note = (
            f"{base.symbol} {frame} {when(bars.ts[at])}\n"
            f"B/ATR {bars.body[at] / a[at]:.2f}   BR {ratio[at]:.2f}   "
            f"UW/B {bars.upper_wick[at] / bars.body[at]:.1f}   LW/B {bars.lower_wick[at] / bars.body[at]:.1f}\n"
            f"close sits {(bars.close[at] - bars.low[at]) / bars.span[at]:.0%} up the range"
        )
        extra = []
        if impulse[at]:
            extra.append("IsImpulse")
        if displacement[at]:
            extra.append("IsDisplacement")
        if pin[at]:
            extra.append("IsPinBar")
        if chop["any"][at]:
            extra.append("IsChoppy")
        note += "\nalso passes: " + ", ".join(extra)
        _panel(axis, bars, at, 5, name, note)
        said.append(f"{name}: {base.symbol} {frame} {when(bars.ts[at])} -> {', '.join(extra)}")
    figure.suptitle(
        f"Section 2, single-candle anatomy - the median bar each definition selects "
        f"({base.symbol}, {frame}, q {Q} N {N_PCT} q_chop {Q_CHOP})",
        fontsize=10,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.96))
    figure.savefig(out / "single-candle-anatomy.png", dpi=150)
    plt.close(figure)
    return said


def figure_leg(base: Candles, frame: str, out: Path) -> list[str]:
    """A sequential impulse leg that passes, beside one that fails on efficiency."""
    import matplotlib.pyplot as plt

    bars = fold(base, frame)
    a = atr(bars)
    leg = sequential_parts(bars, a)
    passes = leg["up"] | leg["down"]
    nearly = (
        leg["big"]
        & ((leg["consistent_up"] & leg["stacked_up"]) | (leg["consistent_down"] & leg["stacked_down"]))
        & ~leg["efficient"]
    )
    figure, axes = plt.subplots(1, 2, figsize=(11.5, 5.4))
    said: list[str] = []
    for axis, (name, flags) in zip(
        axes, (("passes IsSequentialImpulseLeg", passes), ("fails on the efficiency ratio alone", nearly)), strict=True
    ):
        at = typical(flags, leg["efficiency"], pad=6)
        if at is None:
            axis.set_axis_off()
            continue
        first = at - K + 1
        draw_candles(axis, bars, at - 6, at + 3, focus=tuple(range(first, at + 1)))
        axis.axvspan(first - 0.5, at + 0.5, color=BAND, alpha=0.45, zorder=0)
        # The stacked FVG: the gap between the leg's first bar and its last.
        up = bars.close[at] > bars.open[first]
        edge = (bars.high[first], bars.low[at]) if up else (bars.low[first], bars.high[at])
        axis.axhline(edge[0], color=MARK, linewidth=0.8, linestyle="--")
        axis.axhline(edge[1], color=MARK, linewidth=0.8, linestyle="--")
        axis.fill_between(
            [first - 0.5, at + 0.5], edge[0], edge[1], color=MARK, alpha=0.10, zorder=1
        )
        bodies = float(sum(bars.body[at - i] for i in range(K)))
        note = (
            f"{base.symbol} {frame} {when(bars.ts[at])}, k {K}\n"
            f"net push |C_t - O_(t-2)| = {leg['push'][at] / a[at]:.2f} ATR   (needs >= 2.00)\n"
            f"efficiency |C_t - C_(t-2)| / sum B = "
            f"{abs(bars.close[at] - bars.close[first]):.5f} / {bodies:.5f} = "
            f"{leg['efficiency'][at]:.3f}   (needs >= 0.70)\n"
            f"stacked FVG {'yes' if (leg['stacked_up'][at] or leg['stacked_down'][at]) else 'no'}, "
            f"consistency {'yes' if (leg['consistent_up'][at] or leg['consistent_down'][at]) else 'no'}"
        )
        axis.set_title(name, fontsize=9, loc="left")
        axis.set_xlabel(note, fontsize=7.5, labelpad=6)
        said.append(f"{name}: {base.symbol} {frame} {when(bars.ts[at])} eff {leg['efficiency'][at]:.3f}")
    figure.suptitle(
        "Section 3, the sequential impulse leg - the shaded band is the leg, "
        "the dashed pair is the stacked FVG it must leave",
        fontsize=10,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(out / "sequential-impulse-leg.png", dpi=150)
    plt.close(figure)
    return said


def figure_block(base: Candles, frame: str, out: Path) -> list[str]:
    """A choppy block with its range against 1.5 ATR and its efficiency."""
    import matplotlib.pyplot as plt

    bars = fold(base, frame)
    a = atr(bars)
    block = choppy_block(bars, a, K)
    figure, axes = plt.subplots(1, 2, figsize=(11.5, 5.2))
    said: list[str] = []
    arms = (
        ("passes IsChoppyBlock", block["block"]),
        ("fails - tight enough, but not inert enough", block["tight"] & ~block["inert"]),
    )
    for axis, (name, flags) in zip(axes, arms, strict=True):
        at = typical(flags, block["efficiency"], pad=7)
        if at is None:
            axis.set_axis_off()
            continue
        first = at - K
        draw_candles(axis, bars, at - 7, at + 4, focus=tuple(range(first, at + 1)))
        axis.axvspan(first - 0.5, at + 0.5, color=BAND, alpha=0.5, zorder=0)
        axis.hlines(
            [block["reach"][at] + bars.low[first : at + 1].min(), bars.low[first : at + 1].min()],
            first - 0.5,
            at + 0.5,
            color=MARK,
            linewidth=0.9,
        )
        note = (
            f"{base.symbol} {frame} {when(bars.ts[at])}, k {K} ({K + 1} candles)\n"
            f"block range max(H)-min(L) = {block['reach'][at] / a[at]:.2f} ATR   (needs <= 1.50)\n"
            f"block efficiency |C_t - C_(t-k)| / sum R = {block['efficiency'][at]:.3f}   (needs <= 0.30)"
        )
        axis.set_title(name, fontsize=9, loc="left")
        axis.set_xlabel(note, fontsize=7.5, labelpad=6)
        said.append(f"{name}: {base.symbol} {frame} {when(bars.ts[at])}")
    figure.suptitle("Section 3, the choppy block", fontsize=10)
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(out / "choppy-block.png", dpi=150)
    plt.close(figure)
    return said


def figure_engine(base: Candles, out: Path) -> list[str]:
    """Engine 1 end to end: anchor, pivot band, frozen zone, retrace, 1H gate."""
    import matplotlib.pyplot as plt

    found = engines(base, loose=True)
    four = found.frames["4h"]
    hourly = found.frames["1h"]
    a4 = found.atrs["4h"]
    places = found.where["1 exhaustion"]
    if len(places) == 0:
        return []
    at = int(places[len(places) // 2])
    tolerance = TAU * a4[at]
    pivot_ts, pivots_ = pivot_levels(four, bjorgum_pivots)
    end = int(np.searchsorted(pivot_ts, four.ts[at], side="right"))
    window = pivots_[max(end - RECENT_PIVOTS, 0) : end]
    level = float(window[np.argmin(np.abs(window - four.close[at]))]) if len(window) else four.close[at]

    figure, axes = plt.subplots(1, 2, figsize=(13.0, 5.6), width_ratios=(1.25, 1.0))
    draw_candles(axes[0], four, at - 14, at + 10, focus=(at,))
    axes[0].axhspan(level - tolerance, level + tolerance, color=MARK, alpha=0.22, zorder=1)
    axes[0].axhline(level, color=MARK, linewidth=0.9)
    zone = (min(four.open[at], four.close[at]), max(four.open[at], four.close[at]))
    axes[0].axhspan(zone[0], zone[1], color=UP, alpha=0.13, zorder=1)
    axes[0].set_title("4H: anchor candle, Bjorgum level +/- tau, frozen zone", fontsize=9, loc="left")
    axes[0].set_xlabel(
        f"{base.symbol} 4H {when(four.ts[at])}\n"
        f"anchor B/ATR {four.body[at] / a4[at]:.2f}, BR {four.body_ratio[at]:.2f}\n"
        f"pivot {level:.5f}, tau = 0.015 x ATR_4H = {tolerance:.6f} "
        f"({tolerance / four.body[at]:.1%} of the anchor's own body)",
        fontsize=7.5,
        labelpad=6,
    )

    # The 1H window after the anchor, where the gate would have to form.
    start = int(np.searchsorted(hourly.ts, four.ts[at], side="right"))
    stop = min(start + 48, len(hourly))
    pin = is_pin_bar(hourly)
    gates = [i for i in range(start, stop) if pin[i] and zone[0] <= hourly.high[i] and hourly.low[i] <= zone[1]]
    draw_candles(axes[1], hourly, start - 2, stop, focus=tuple(gates))
    axes[1].axhspan(zone[0], zone[1], color=UP, alpha=0.13, zorder=1)
    axes[1].axhspan(level - tolerance, level + tolerance, color=MARK, alpha=0.22, zorder=1)
    axes[1].set_title("1H: the 48 hours the pin-bar gate has to fire in", fontsize=9, loc="left")
    axes[1].set_xlabel(
        f"{stop - start} hourly candles, {len(gates)} of them a pin bar touching the zone\n"
        "the zone is the anchor's body; the trade needs a pin bar inside it",
        fontsize=7.5,
        labelpad=6,
    )
    figure.suptitle("Engine 1, statistical exhaustion, end to end", fontsize=10)
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(out / "engine-exhaustion.png", dpi=150)
    plt.close(figure)
    return [
        f"engine 1: {base.symbol} 4H {when(four.ts[at])}, tau {tolerance:.6f}, "
        f"{len(gates)} pin gates in 48h"
    ]


def figure_double(base: Candles, out: Path) -> list[str]:
    """Engine 5: the displacement, the frozen origin body, the retrace, the trigger."""
    import matplotlib.pyplot as plt

    found = engines(base, loose=True)
    fifteen = found.frames["15m"]
    a15 = found.atrs["15m"]
    places = found.where["5 displacement"]
    if len(places) == 0:
        return []
    at = int(places[len(places) // 2])
    origin = at - 1
    zone = (min(fifteen.open[origin], fifteen.close[origin]), max(fifteen.open[origin], fifteen.close[origin]))
    pin = is_pin_bar(fifteen)
    direction = 1 if fifteen.close[at] > fifteen.open[at] else -1
    stop = min(at + 60, len(fifteen))
    back = [i for i in range(at + 1, stop) if fifteen.low[i] <= zone[1] and fifteen.high[i] >= zone[0]]
    triggers = [i for i in back if pin[i] == direction]

    figure, axis = plt.subplots(figsize=(13.0, 5.6))
    draw_candles(axis, fifteen, at - 6, stop, focus=(origin, at, *triggers))
    axis.axhspan(zone[0], zone[1], color=UP if direction > 0 else DOWN, alpha=0.16, zorder=1)
    axis.annotate(
        "displacement",
        (at, fifteen.high[at]),
        xytext=(at, fifteen.high[at] + 0.5 * a15[at]),
        fontsize=7.5,
        ha="center",
        arrowprops={"arrowstyle": "->", "color": EDGE, "linewidth": 0.7},
    )
    axis.annotate(
        "frozen origin body",
        (origin, zone[0]),
        xytext=(origin - 4, zone[0] - 1.2 * a15[at]),
        fontsize=7.5,
        arrowprops={"arrowstyle": "->", "color": EDGE, "linewidth": 0.7},
    )
    axis.set_title(
        "Engine 5, displacement double rejection - the base pattern CLAUDE.md records at "
        "-0.007R on 2,786 trades",
        fontsize=9,
        loc="left",
    )
    axis.set_xlabel(
        f"{base.symbol} 15m {when(fifteen.ts[at])}, direction {'up' if direction > 0 else 'down'}\n"
        f"push B/ATR {fifteen.body[at] / a15[at]:.2f}, BR {fifteen.body_ratio[at]:.2f}; "
        f"zone is the body of the candle before it, {zone[1] - zone[0]:.5f} wide "
        f"({(zone[1] - zone[0]) / a15[at]:.2f} ATR)\n"
        f"{len(back)} of the next {stop - at - 1} candles traded back into the zone; "
        f"{len(triggers)} of those were a pin bar in the push's direction",
        fontsize=7.5,
        labelpad=6,
    )
    figure.tight_layout()
    figure.savefig(out / "displacement-double-rejection.png", dpi=150)
    plt.close(figure)
    return [
        f"engine 5: {base.symbol} 15m {when(fifteen.ts[at])}, zone "
        f"{(zone[1] - zone[0]) / a15[at]:.2f} ATR wide, {len(back)} revisits, {len(triggers)} pin triggers"
    ]


def draw_all(where: Path, symbols: tuple[str, ...], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    base = load(where, symbols[0])
    said: list[str] = []
    said += figure_single(base, "1h", out)
    said += figure_leg(base, "1h", out)
    said += figure_block(base, "4h", out)
    said += figure_engine(base, out)
    said += figure_double(base, out)
    print(f"wrote {len(list(out.glob('*.png')))} figures to {out}")
    for line in said:
        print(f"  {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--rates", action="store_true")
    parser.add_argument("--engines", action="store_true")
    parser.add_argument("--figures", action="store_true")
    parser.add_argument("--out", default="docs/specs/img/multi-structural-confluence")
    args = parser.parse_args()

    symbols = tuple(s for s in args.symbols.split(",") if s)
    where = Path(args.catalogue)
    if args.rates:
        rates(where, symbols)
    if args.engines:
        engine_rates(where, symbols)
    if args.figures:
        draw_all(where, symbols, Path(args.out))
    if not (args.rates or args.engines or args.figures):
        parser.error("pick --rates, --engines or --figures")


if __name__ == "__main__":
    main()
