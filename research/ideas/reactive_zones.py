"""The sequence rule, multi-timeframe, measured gross on the last two years.

A **reactive** rule: nothing here forecasts. A level is nominated on a slow
frame, price arrives at it, and the rule reacts to what the fast frame then
does - a bounce, a pull-back, and a rejection candle. Entry is the close of the
candle that completes the sequence.

    structure frame   Bjorgum zones, `desk` preset: 15/5 pivot, one a side,
                      ATR 30, a 0.015 ATR band, body pivots
    execution frame   the bounce, the pull-back and the pattern

## What is measured, and what is deliberately not

**Gross, as asked.** Every number here is before costs, which is the right way
round for a first pass: a rule with no edge before costs cannot have one after,
and `a-shorter-clock-multiplies-cost-in-r` means the cost question is answered
separately and per clock. `--net` applies the catalogue's own median spread for
the contrast.

**The outcome is a horizon return in volatility units, not a stop-and-target
race.** `dual-thrust.md` measured an OHLC trigger fill at **+0.03 to +0.06
units a trade on a direction-free series** - a trade-level side coin, whose
expectation is exactly zero, passed BH on 4 of 36 cells. Entering on a close
and scoring a close-to-close move has no intrabar fill to be wrong about. A
barrier version belongs in the run that prices the exits, not in the one that
asks whether the entry carries a side.

## The arms, and why each exists

| arm | what it adds | what it controls for |
|---|---|---|
| `bounce` | the reject alone | the baseline the rest must beat |
| `pullback` | bounce, then a return toward the zone | whether waiting costs or pays |
| `pattern` | and a pin/hammer/star/engulf | the operator's rule as stated |
| `tsi` | and TSI agreement on the structure frame | the filter, tested before it gates |
| `twin` | **random drops at the matched rate** | the one control a filter cannot skip |
| `flip` | the same entries, side reversed | prices the mechanical bias, if any |

`twin` is not optional. `finding-edges`: on a net-negative book *any* rule that
trades less shows an improvement, and every pause rule ever measured on this
desk beat its baseline and none beat its own random twin (p 0.45-0.51). A
filter is a pause rule wearing a reason, so each filtered arm is reported
beside a twin that drops the same share of signals at random, seeded per feed
so the cell is reproducible.

## Known before running

The `desk` band is **0.015 ATR against the published 0.5**, so a zone is
touched rarely and the signal count falls with it. The same constant measured
at 0.7% of a 4H candle's body in the confluence blueprint. Expect small n, and
read the per-instrument counts before reading anything else.

Run as:

    uv run python research/ideas/reactive_zones.py --years 2
"""

from __future__ import annotations

import argparse
import glob
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

CATALOGUE = Path.home() / "till-data" / "mt5-deep"
SPEC = "5-MINUTE-LAST-EXTERNAL"
PRICE_SCALE = 1e16

SYMBOLS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")

#: Bars per frame, in units of the base series. The catalogue's base is 5m and
#: matches `dual_engine_v6.Frame.fold`; an hourly source folds the same shape
#: one step slower, which is what the synthetic feeds are kept at.
#:
#: **24 bars to the day on the hourly table, deliberately.** The Deriv
#: synthetics never close - measured quoting normally on a Saturday with every
#: real market on the account hours stale - so a day really is 24 of their
#: bars, where an FX day is not.
RATIOS = {
    "5m": {"15m": 3, "1h": 12, "4h": 48, "1d": 288},
    "1h": {"1h": 1, "4h": 4, "1d": 24},
    # For the feeds held no finer than 4h. A week is 42 of them because these
    # never close; on a real market it would be 30 and the two tables are not
    # interchangeable.
    "4h": {"4h": 1, "1d": 6, "1w": 42},
}
FRAMES = RATIOS["5m"]

#: The `desk` preset, the one `zones.DESK` carries.
LEFT, RIGHT, KEEP = 15, 5, 1
ATR_LEN = 30
MULT = 0.015

#: Bars the sequence is allowed to take. A bounce that is still waiting for its
#: pattern after this many execution bars is abandoned: the level was reacted
#: to, and whatever happens twelve hours later is a different trade.
PATIENCE = 24

#: How much of the move away from the level price must give back for a
#: pull-back to count.
#:
#: **A share of the excursion, not a distance from the level.** Requiring
#: price to return to the level - or to within some ATR of it - asks for a
#: second visit to the same price, which is both a different event and the one
#: the rule just reacted to. What the operator described is a retracement of
#: the leg: price left, then gave some of it back. That is scale-free, so it
#: means the same thing on gold and on EURUSD and in a quiet year and a loud
#: one.
PULLBACK_SHARE = 0.33

#: Bars the outcome is measured over, on the execution frame.
HORIZON = 16

#: TSI, Bjorgum's slow speed. The fast pair is 13/7.
TSI_LONG, TSI_SHORT = 25, 13

#: "Volatility is currently low", as a percentile of the instrument's own
#: recent ATR rather than a level.
#:
#: **A threshold in price units is not comparable across instruments and is
#: not comparable across years on one.** Gold's ATR triples over this window;
#: a fixed number would read as a regime filter on the calendar. The quantile
#: asks the only question that travels: quiet *for this instrument lately*.
QUIET_WINDOW, QUIET_PERCENTILE = 200, 40.0


@dataclass(slots=True)
class Candles:
    symbol: str
    frame: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    def __len__(self) -> int:
        return int(self.close.size)

    @property
    def body(self) -> np.ndarray:
        return np.abs(self.close - self.open)

    @property
    def span(self) -> np.ndarray:
        return self.high - self.low

    @property
    def upper_wick(self) -> np.ndarray:
        return self.high - np.maximum(self.open, self.close)

    @property
    def lower_wick(self) -> np.ndarray:
        return np.minimum(self.open, self.close) - self.low


def _prices(raw: list[bytes]) -> np.ndarray:
    """Nautilus's 128-bit fixed-point price column, as floats.

    **Both words, and the low one unsigned.** This read the low `int64` alone,
    which is correct only while the value fits in a *signed* 64-bit integer -
    that is, below `2**63 / 1e16 = 922.3`. EURUSD, GBPUSD and AUDUSD are under
    one and USDJPY is about 150, so the error was invisible on four of five
    instruments; gold at 1,313 wrapped to **-531.28**, and every gold figure
    taken through this loader was computed on negative prices.

    Found by a mean that was too good: a sequence rule read `+2.92` units a
    trade on gold against `-0.15` to `-0.85` on everything else, and its top
    two trades were `+204` and `+129` units. A number that size is a defect
    before it is an edge.
    """
    pair = np.frombuffer(b"".join(raw), dtype=np.int64).reshape(-1, 2)
    low = pair[:, 0].view(np.uint64).astype(np.float64)
    high = pair[:, 1].astype(np.float64)
    return (low + high * 2.0**64) / PRICE_SCALE


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
            columns[name].append(_prices(table.column(name).to_pylist()))
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


def load_csv(path: Path, symbol: str, frame: str) -> Candles:
    """`ts,open,high,low,close,volume` from a gzipped broker export.

    Kept beside the parquet loader rather than folded into it: the synthetic
    feeds are only held at hourly and coarser, so they are read at their own
    base frame and folded from there. The path is an argument and never a
    literal - this file is public and the exports are not.
    """
    import csv
    import gzip

    ts, opens, highs, lows, closes = [], [], [], [], []
    with gzip.open(path, "rt") as handle:
        for row in csv.DictReader(handle):
            ts.append(int(float(row["ts"])) * 1_000_000_000)
            opens.append(float(row["open"]))
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))
            closes.append(float(row["close"]))
    order = np.argsort(np.asarray(ts), kind="stable")
    return Candles(
        symbol=symbol,
        frame=frame,
        ts=np.asarray(ts)[order],
        open=np.asarray(opens)[order],
        high=np.asarray(highs)[order],
        low=np.asarray(lows)[order],
        close=np.asarray(closes)[order],
    )


def window(bars: Candles, years: float, before: float = 0.0) -> Candles:
    """The last `years` of bars, optionally ending `before` years ago.

    **`before` is what makes a held-out test possible here.** Everything in
    `reactive-zones.md` was found on the most recent two years; setting
    `before=2` runs the same detector on data that search never touched, which
    is the only confirmation available without waiting for more of it.
    """
    if years <= 0 and before <= 0:
        return bars
    end = bars.ts[-1] - int(before * 365.25 * 86_400 * 1e9)
    start = end - int(years * 365.25 * 86_400 * 1e9) if years > 0 else bars.ts[0]
    keep = (bars.ts >= start) & (bars.ts <= end)
    return Candles(
        symbol=bars.symbol,
        frame=bars.frame,
        ts=bars.ts[keep],
        open=bars.open[keep],
        high=bars.high[keep],
        low=bars.low[keep],
        close=bars.close[keep],
    )


def fold(base: Candles, frame: str, unit: str = "5m") -> Candles:
    """Fold base bars into `frame` by bar count, as the live `Frame.fold` does.

    By count and not by calendar: a calendar fold gives different candles
    across a weekend and the two are not interchangeable.
    """
    step = RATIOS[unit][frame]
    usable = (len(base) // step) * step
    shape = (usable // step, step)
    return Candles(
        symbol=base.symbol,
        frame=frame,
        ts=base.ts[:usable].reshape(shape)[:, -1],
        open=base.open[:usable].reshape(shape)[:, 0],
        high=base.high[:usable].reshape(shape).max(axis=1),
        low=base.low[:usable].reshape(shape).min(axis=1),
        close=base.close[:usable].reshape(shape)[:, -1],
    )


def atr(bars: Candles, period: int = ATR_LEN) -> np.ndarray:
    """Wilder's ATR on the frame's own candles."""
    previous = np.concatenate(([bars.close[0]], bars.close[:-1]))
    true = np.maximum(
        bars.high - bars.low,
        np.maximum(np.abs(bars.high - previous), np.abs(bars.low - previous)),
    )
    out = np.full(len(bars), np.nan)
    if len(bars) <= period:
        return out
    out[period] = true[1 : period + 1].mean()
    for i in range(period + 1, len(bars)):
        out[i] = (out[i - 1] * (period - 1) + true[i]) / period
    return out


def tsi(close: np.ndarray, long: int = TSI_LONG, short: int = TSI_SHORT) -> np.ndarray:
    """True Strength Index: momentum smoothed twice, over its own magnitude.

    `100 * EMA_s(EMA_l(dP)) / EMA_s(EMA_l(|dP|))`, which is bounded by +/-100
    by construction and is zero where the two smoothings of the signed and
    unsigned change agree in magnitude - that is, where recent moves cancel.

    The slow speed is 25/13; Bjorgum's fast pair is 13/7. Stated because the
    speed is the whole of what the setting chooses.
    """

    def ema(values: np.ndarray, span: int) -> np.ndarray:
        alpha = 2.0 / (span + 1.0)
        out = np.empty_like(values)
        out[0] = values[0]
        for i in range(1, values.size):
            out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
        return out

    change = np.diff(close, prepend=close[0])
    smooth = ema(ema(change, long), short)
    magnitude = ema(ema(np.abs(change), long), short)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(magnitude > 0, 100.0 * smooth / magnitude, 0.0)
    out[: long + short] = np.nan
    return out


def quiet_mask(
    band: np.ndarray, window: int = QUIET_WINDOW, percentile: float = QUIET_PERCENTILE
) -> np.ndarray:
    """Where ATR sits in the lower `percentile` of its own last `window` bars.

    **Trailing and closed.** The window ends at the previous bar, so the
    reading at bar `i` uses nothing from `i` onward: a quantile that includes
    the bar being judged is a comparison with itself and reads as a filter
    that knows the answer. `overlapping-windows-inflate-permutation-nulls` is
    the same mistake one level up.
    """
    out = np.zeros(band.size, dtype=bool)
    for i in range(window, band.size):
        past = band[i - window : i]
        past = past[np.isfinite(past)]
        if past.size < window // 2 or not np.isfinite(band[i]):
            continue
        out[i] = band[i] <= np.percentile(past, percentile)
    return out


def pin_like(bars: Candles) -> tuple[np.ndarray, np.ndarray]:
    """+1 bullish, -1 bearish, 0 otherwise: the four patterns, as one array.

    Pin bar, hammer and shooting star are the same geometry read at different
    ends, and an engulf is the opposite shape - `smc-primitives-overlap-and-are-closed`
    records that an engulf is the *opposite* shape to a displacement origin, so
    they are not interchangeable and all four are wanted. A bar that satisfies
    both a bullish and a bearish form is refused rather than resolved.
    """
    span, body = bars.span, bars.body
    alive = span > 0
    ratio = np.divide(body, span, out=np.ones_like(body), where=alive)
    # The rejection family: a small body with a long tail, closing away from it.
    small = alive & (ratio <= 0.35)
    up = small & (bars.lower_wick >= 2.0 * body) & (bars.close >= bars.high - 0.25 * span)
    down = small & (bars.upper_wick >= 2.0 * body) & (bars.close <= bars.low + 0.25 * span)
    # The engulf: this body covers the last one and closes the other way.
    top = np.maximum(bars.open, bars.close)
    bottom = np.minimum(bars.open, bars.close)
    covers = np.zeros(len(bars), dtype=bool)
    covers[1:] = (bottom[1:] <= bottom[:-1]) & (top[1:] >= top[:-1])
    bull = np.zeros(len(bars), dtype=bool)
    bear = np.zeros(len(bars), dtype=bool)
    bull[1:] = covers[1:] & (bars.close[:-1] < bars.open[:-1]) & (bars.close[1:] > bars.open[1:])
    bear[1:] = covers[1:] & (bars.close[:-1] > bars.open[:-1]) & (bars.close[1:] < bars.open[1:])
    rising = up | bull
    falling = down | bear
    both = rising & falling
    side = np.where(both, 0, np.where(rising, 1, np.where(falling, -1, 0)))
    # Which shape fired, because a rejection wick and an engulf are opposite
    # geometries and pooling them is the mistake `smc-primitives-overlap` names.
    kind = np.where(both, "", np.where(up | down, "rejection", np.where(bull | bear, "engulf", "")))
    return side, kind


def shuffled(base: Candles, seed: int) -> Candles:
    """The same bars, their **days** reordered and re-based to join up.

    **Whole days of real bars, not a generated path.**
    `re-hung-bar-shapes-break-bar-derived-nulls` is explicit that a null built
    by re-hanging bar shapes is invalid for anything read off a wick - and this
    rule reads pin bars, ranges and ATR off wicks. Shuffling whole days keeps
    every bar's own geometry exactly as the market made it and destroys only
    the thing under test: that a level drawn on one day has anything to do with
    price arriving at it on another.

    Each day is re-based to continue from the previous day's close, so the
    joins do not manufacture gaps the detector would read as displacement.
    """
    day = base.ts // 86_400_000_000_000
    edges = np.flatnonzero(np.diff(day)) + 1
    blocks = np.split(np.arange(base.ts.size), edges)
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(blocks))

    opens, highs, lows, closes = [], [], [], []
    carry = float(base.close[0])
    for index in order:
        block = blocks[index]
        shift = carry - float(base.open[block[0]])
        opens.append(base.open[block] + shift)
        highs.append(base.high[block] + shift)
        lows.append(base.low[block] + shift)
        closes.append(base.close[block] + shift)
        carry = float(closes[-1][-1])
    return Candles(
        symbol=f"{base.symbol}~shuffled",
        frame=base.frame,
        ts=base.ts,
        open=np.concatenate(opens),
        high=np.concatenate(highs),
        low=np.concatenate(lows),
        close=np.concatenate(closes),
    )


@dataclass(slots=True)
class Zone:
    """One Bjorgum level, with the band the preset gives it."""

    at: int
    top: float
    bottom: float
    resistance: bool


def adaptive_band(bars: Candles, percentile: float, window: int = QUIET_WINDOW) -> np.ndarray:
    """Band half-width from a **quantile of the frame's own recent ranges**.

    The fixed form is `ATR(30) * 0.015`, which is a multiple of a mean - so it
    inherits the mean's sensitivity to the few bars that made it. A quantile of
    the trailing ranges asks a different question: how wide is a *typical* bar
    here lately, where typical is chosen rather than averaged.

    **Trailing and closed**, ending at the previous bar, for the reason
    `quiet_mask` gives: a quantile that includes the bar being measured is a
    comparison with itself.

    Returned as the full band, to be halved by the caller exactly as the ATR
    form is - so the two are the same quantity and the only difference is how
    the width was chosen.
    """
    span = bars.span
    out = np.full(span.size, np.nan)
    for i in range(window, span.size):
        past = span[i - window : i]
        past = past[np.isfinite(past)]
        if past.size >= window // 2:
            out[i] = np.percentile(past, percentile)
    return out


def zones_of(
    bars: Candles, band: np.ndarray, scale: float = MULT, *, placebo: bool = False
) -> list[Zone]:
    """Bjorgum pivots on this frame, `keep` of each side kept.

    The pivot is **asymmetric**: a high is a pivot when it is the highest of
    the `left` bars before it and the `right` after, so it is confirmed `right`
    bars late and never sooner. Reading it at the pivot's own index would be
    lookahead of exactly `right` bars.
    """
    high = np.maximum(bars.open, bars.close)
    low = np.minimum(bars.open, bars.close)
    found: list[Zone] = []
    for index in range(LEFT, len(bars) - RIGHT):
        half = float(band[index]) * scale / 2.0
        if not np.isfinite(half) or half <= 0:
            continue
        if high[index] == high[index - LEFT : index + RIGHT + 1].max():
            found.append(Zone(index + RIGHT, high[index] + half, high[index] - half, True))
        if low[index] == low[index - LEFT : index + RIGHT + 1].min():
            found.append(Zone(index + RIGHT, low[index] + half, low[index] - half, False))
    if not placebo:
        return found

    # **The placebo: the same distance, the other way, with no pivot behind
    # it.** `a-return-rate-is-geometry` records that an origin's 82% return
    # rate was matched by a distance-matched placebo on every class, and
    # `the-placebo-arm-selects-the-null` that a block of 8 found structure in
    # 27 of 36 placebo pools. Without this arm a level study measures the
    # geometry of approaching *any* price at that distance and reports it as
    # structure.
    #
    # Mirrored about the close that confirmed the pivot: a resistance 3 ATR
    # above becomes a band 3 ATR below, which price can reach and bounce from
    # the same way, and the role flips with it so the geometry is consistent.
    mirrored: list[Zone] = []
    for zone in found:
        anchor = float(bars.close[min(zone.at, len(bars) - 1)])
        centre = (zone.top + zone.bottom) / 2.0
        half = (zone.top - zone.bottom) / 2.0
        other = anchor - (centre - anchor)
        mirrored.append(Zone(zone.at, other + half, other - half, not zone.resistance))
    return mirrored


def _roundness(zone: "Zone", step, unit: float) -> float:
    """Distance from the level's centre to the nearest round number, in ATR."""
    centre = (zone.top + zone.bottom) / 2.0
    spacing = step(centre)
    if not np.isfinite(spacing) or spacing <= 0 or not np.isfinite(unit) or unit <= 0:
        return float("nan")
    nearest = round(centre / spacing) * spacing
    return float(abs(centre - nearest) / unit)


def _perch(frame: "Candles", zone: "Zone", at: int, look: int = 50) -> float:
    """Where the level sits in the frame's trailing range: 0 low, 1 high."""
    start = max(0, at - look)
    if at <= start:
        return float("nan")
    low = float(frame.low[start:at].min())
    high = float(frame.high[start:at].max())
    if not np.isfinite(low) or high <= low:
        return float("nan")
    centre = (zone.top + zone.bottom) / 2.0
    return float((centre - low) / (high - low))


@dataclass(slots=True)
class Trade:
    """One entry, with what every frame said at the moment it was taken.

    **The frames' states travel with the trade rather than gating inside the
    state machine.** One pass then answers every conjunction, and - more to the
    point - each conjunct's cost in sample size is visible beside its effect,
    which is the thing a confluence rule actually trades away.
    """

    feed: str
    at: int
    side: int
    gross: float
    stage: str
    #: The structure frame's TSI agrees with the side.
    tsi_slow: bool
    #: The middle frame's TSI agrees with the side.
    tsi_mid: bool
    #: The middle frame's last closed candle is a rejection the same way.
    pattern_mid: bool
    #: The execution frame's ATR sits in the lower `QUIET_PERCENTILE` of its
    #: own recent range at the moment of entry.
    quiet: bool
    #: Day index, for the block bootstrap: trades cluster in days and an
    #: ordinary standard error over trades is far too narrow.
    day: int
    #: The same move over a **fixed** unit - the instrument's trailing median
    #: ATR - rather than over the ATR at entry.
    #:
    #: **The denominator is the first cause to rule out.** `gross` divides by
    #: the ATR of the entry bar, and the drift arm selects quiet windows, so a
    #: smaller denominator would manufacture the effect out of nothing. This
    #: is the same move measured against a unit the selection cannot move. If
    #: the effect is in `gross` and not here, it was the denominator.
    steady: float = float("nan")
    #: What armed the sequence - `bounce` or `sweep`. Two shapes, kept apart
    #: rather than pooled: `two detectors with the same name are usually two
    #: detectors`, and these two are not even the same name.
    trigger: str = "bounce"
    #: The volatility path through the sequence, each one the execution ATR at
    #: that point over the instrument's own trailing median ATR. **A ratio and
    #: not a level**, so gold and EURUSD can be read on one line and a year
    #: whose ATR has tripled does not read as a signal.
    vol_before: float = float("nan")
    vol_trigger: float = float("nan")
    vol_after: float = float("nan")
    vol_last3: float = float("nan")
    #: UTC hour of the entry bar. Sessions differ by three times in volatility
    #: - `seasonality-belongs-on-q` - so an effect that is really a session is
    #: a thing this has to be able to show.
    hour: int = -1
    #: `rejection` or `engulf`, never pooled.
    kind: str = ""
    #: Execution bars from the trigger to this entry.
    waited: int = 0
    #: Share of the move away from the level given back by this bar.
    depth: float = 0.0
    #: Support or resistance, which is also long or short.
    role: str = ""
    #: Structure-frame bars from the pivot to the touch. A level's age is the
    #: one property of it that needs no theory.
    age: int = 0
    #: How far price travelled to reach the level, over the 12 execution bars
    #: before the trigger, in ATR. An arrival, not a drift.
    approach: float = float("nan")
    #: Distance from the level to the nearest round number, in ATR.
    #: **The watchedness proxy.** `a-magnet-is-a-shared-reference`: liquidity
    #: rests where many participants compute the same price, which is a claim
    #: about agreement rather than attraction - and a round number is the one
    #: price everybody computes identically. `magnet.md` closed attraction; it
    #: did not close agreement.
    roundness: float = float("nan")
    #: Where the level sits in the structure frame's trailing 50-bar range:
    #: 0 at the low, 1 at the high. A level at an extreme and a level in the
    #: middle of a range are different objects.
    perch: float = float("nan")


def sequence(
    slow: Candles,
    middle: Candles,
    fast: Candles,
    *,
    patience: int = PATIENCE,
    horizon: int = HORIZON,
    share: float = PULLBACK_SHARE,
    band: str = "fixed",
    percentile: float = 25.0,
    placebo: bool = False,
    unit: str = "5m",
) -> list[Trade]:
    """Every completed sequence on this pair of frames.

    The state machine, per zone, in the order it must happen:

    1. **fresh** - the zone has not been visited before. A level price has
       already worked twice is a different claim, measured in `gap-levels.md`
       and refuted there, so this rule takes only the first approach.
    2. **bounce** - a fast bar trades into the band and closes back out the way
       it came. The zone held.
    3. **pull-back** - price gives back `PULLBACK_SHARE` of its move away from
       the level, without closing through it. **Not a return to the level**: a
       second visit to the same price is a different event, and the operator's
       rule is a retracement of the leg, not a re-test of the line.
    4. **pattern** - a pin, hammer, star or engulf in the bounce's direction.
       Entry is that bar's close.

    A close through the band at any stage abandons the sequence: the level
    failed, and the reason to be in the trade was that it held.
    """
    slow_band = atr(slow, ATR_LEN)
    fast_band = atr(fast, ATR_LEN)
    pattern, pattern_kind = pin_like(fast)
    mid_pattern, _mid_kind = pin_like(middle)
    slow_tsi = tsi(slow.close)
    mid_tsi = tsi(middle.close)
    calm = quiet_mask(fast_band)
    # The trailing median ATR, as the unit every volatility reading is in.
    # Trailing and closed, for the reason `quiet_mask` gives.
    typical = np.full(fast_band.size, np.nan)
    for j in range(QUIET_WINDOW, fast_band.size):
        past = fast_band[j - QUIET_WINDOW : j]
        past = past[np.isfinite(past)]
        if past.size >= QUIET_WINDOW // 2:
            typical[j] = np.median(past)

    def vol_at(at: int) -> float:
        """ATR at `at` over the trailing median there. NaN where unknowable.

        Named apart from `ratio`, which is the frame ratio in this scope and
        which this shadowed - a call then raised `'int' object is not
        callable`, which is the loud version of that mistake.
        """
        if at < 0 or at >= fast_band.size:
            return float("nan")
        unit = typical[at]
        if not np.isfinite(unit) or unit <= 0 or not np.isfinite(fast_band[at]):
            return float("nan")
        return float(fast_band[at] / unit)
    table = RATIOS[unit]
    step = table[fast.frame]
    ratio = table[slow.frame] // step
    mid_ratio = table[middle.frame] // step

    out: list[Trade] = []
    # **The band, chosen two ways and reported as two cells.** `fixed` is the
    # preset's `ATR(30) * 0.015`; `quantile` is the q-th percentile of the
    # structure frame's own trailing ranges, which adapts to the instrument
    # and to the regime without a constant anybody picked.
    def round_step(price: float) -> float:
        """The spacing of the round numbers a human would draw on this price.

        Decided by the price's own magnitude rather than by instrument: 1.0850
        rounds at 0.0050 and 4,100 rounds at 50. One rule, no table to go
        stale when an instrument is added.
        """
        if not np.isfinite(price) or price <= 0:
            return float("nan")
        decade = 10.0 ** np.floor(np.log10(abs(price)))
        return float(decade / 200.0)

    widths = slow_band if band == "fixed" else adaptive_band(slow, percentile)
    scale = MULT if band == "fixed" else 1.0
    for zone in zones_of(slow, widths, scale, placebo=placebo):
        # The zone exists from the bar that confirms it, in fast-frame bars.
        start = (zone.at + 1) * ratio
        if start >= len(fast) - horizon:
            continue
        side = -1 if zone.resistance else +1
        stage, armed_at, armed_by, best = "fresh", -1, "bounce", 0.0
        for i in range(start, min(len(fast) - horizon, start + ratio * 200)):
            close = float(fast.close[i])
            touched = fast.low[i] <= zone.top and fast.high[i] >= zone.bottom
            through = close > zone.top if zone.resistance else close < zone.bottom
            if through:
                break
            reach = float(fast_band[i])
            if not np.isfinite(reach) or reach <= 0:
                continue

            def record(
                stage_name: str, at: int = i, close: float = close, trigger: str = ""
            ) -> None:
                """One entry at this bar's close, scored over the horizon.

                **Each stage is its own entry, not a filter on the last one.**
                Waiting costs time and price, so "does the pattern help" is a
                question about the trade you would have taken instead - which
                is the bounce, entered earlier at a different price.
                """
                unit = float(fast_band[at])
                if not np.isfinite(unit) or unit <= 0:
                    return
                raw = (float(fast.close[at + horizon]) - close) * side
                move = raw / unit
                steady_unit = typical[at] if at < typical.size else float("nan")
                steady = (
                    raw / float(steady_unit)
                    if np.isfinite(steady_unit) and steady_unit > 0
                    else float("nan")
                )
                # **The last *closed* bar of each slower frame, never the one
                # in progress.** `at // ratio` is the bar this entry sits
                # inside, and reading it would be lookahead of up to a whole
                # structure candle - which on 4h against 15m is sixteen bars
                # of the future.
                slow_at = min(at // ratio, len(slow_tsi) - 1) - 1
                mid_at = min(at // mid_ratio, len(mid_tsi) - 1) - 1
                slow_ok = slow_at >= 0 and np.isfinite(slow_tsi[slow_at])
                mid_ok = mid_at >= 0 and np.isfinite(mid_tsi[mid_at])
                out.append(
                    Trade(
                        feed=fast.symbol,
                        at=at,
                        side=side,
                        gross=move,
                        steady=steady,
                        stage=stage_name,
                        tsi_slow=bool(slow_ok and slow_tsi[slow_at] * side > 0),
                        tsi_mid=bool(mid_ok and mid_tsi[mid_at] * side > 0),
                        pattern_mid=bool(mid_at >= 0 and mid_pattern[mid_at] == side),
                        quiet=bool(calm[at]),
                        vol_before=vol_at(armed_at - 6) if armed_at >= 0 else vol_at(at - 6),
                        vol_trigger=vol_at(armed_at) if armed_at >= 0 else vol_at(at),
                        vol_after=vol_at((armed_at if armed_at >= 0 else at) + 3),
                        vol_last3=float(
                            np.nanmean([vol_at(at - 1), vol_at(at - 2), vol_at(at - 3)])
                        ),
                        day=int(fast.ts[at] // 86_400_000_000_000),
                        trigger=trigger or armed_by,
                        hour=int((fast.ts[at] // 3_600_000_000_000) % 24),
                        kind=str(pattern_kind[at]) if stage_name == "pattern" else "",
                        waited=int(at - armed_at) if armed_at >= 0 else 0,
                        depth=float(1.0 - (away / best)) if best > 0 else 0.0,
                        role="resistance" if zone.resistance else "support",
                        age=int(at // ratio - zone.at) if at // ratio > zone.at else 0,
                        approach=(
                            abs(float(fast.close[at]) - float(fast.close[max(0, at - 12)]))
                            / float(fast_band[at])
                            if np.isfinite(fast_band[at]) and fast_band[at] > 0
                            else float("nan")
                        ),
                        roundness=_roundness(zone, round_step, fast_band[at]),
                        perch=_perch(slow, zone, min(at // ratio, len(slow) - 1)),
                    )
                )

            if stage == "fresh":
                # **Two shapes arm this, and they are not the same event.**
                #
                # `bounce` - the bar traded into the band and closed back out
                #   the way it came. The level held where it was drawn.
                # `sweep`  - the wick went *beyond* the band and the close
                #   came back inside the original side. Price reached past the
                #   level, found nothing, and returned: a liquidity grab, which
                #   is the CRT shape `v6` carries and a different claim from a
                #   level simply holding.
                #
                # Kept apart rather than pooled. `CLAUDE.md`: two detectors
                # with the same name are usually two detectors, and these two
                # do not even have the same name.
                back = (close < zone.bottom) if zone.resistance else (close > zone.top)
                beyond = (
                    float(fast.high[i]) > zone.top
                    if zone.resistance
                    else float(fast.low[i]) < zone.bottom
                )
                if back and beyond:
                    stage, armed_at, armed_by = "bounced", i, "sweep"
                    record("bounce", trigger="sweep")
                elif back and touched:
                    stage, armed_at, armed_by = "bounced", i, "bounce"
                    record("bounce", trigger="bounce")
                continue
            if i - armed_at > patience:
                break
            # How far price has travelled away from the level since the
            # trigger, and how much of that it has given back.
            anchor = zone.bottom if zone.resistance else zone.top
            away = (anchor - close) * (1.0 if zone.resistance else -1.0)
            best = max(best, away)
            if stage == "bounced":
                if best > 0 and away <= best * (1.0 - share):
                    stage = "pulled"
                    record("pullback")
                continue
            if pattern[i] == side:
                record("pattern")
                break
    return out


# --- reporting ---------------------------------------------------------------


def block_error(rows: list[Trade], draws: int = 400, seed: int = 7) -> float:
    """Standard error of the mean, resampling **whole days**.

    Trades cluster in days and the frames' states persist for hours, so an
    ordinary standard error over trades is far too narrow - `finding-edges`
    names this as the control that catches it.
    """
    if len(rows) < 2:
        return float("nan")
    by_day: dict[int, list[float]] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row.gross)
    days = list(by_day.values())
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for draw in range(draws):
        picked = rng.integers(0, len(days), len(days))
        pooled = [value for index in picked for value in days[index]]
        means[draw] = float(np.mean(pooled)) if pooled else np.nan
    return float(np.nanstd(means, ddof=1))


def twin(rows: list[Trade], keep: int, seed: int) -> list[Trade]:
    """`keep` of these trades, chosen at random. **The control a filter needs.**

    On a net-negative book any rule that trades less shows an improvement, so
    a filter is only interesting beside a twin that drops the same share at
    random. Every pause rule measured on this desk beat its baseline and none
    beat its own twin, at p 0.45 to 0.51. Seeded, so a cell is reproducible.
    """
    if keep >= len(rows):
        return list(rows)
    rng = np.random.default_rng(seed)
    picked = rng.choice(len(rows), size=keep, replace=False)
    return [rows[int(i)] for i in sorted(picked)]


#: The ladder, each rung adding one frame's agreement to the one above it.
#: Reported with its own sample size, because what a confluence rule trades
#: away is trades - and the blueprint measured four-frame agreement firing
#: about never.
ARMS: tuple[tuple[str, object], ...] = (
    ("pattern", lambda t: True),
    ("quiet only", lambda t: t.quiet),
    ("tsi slow only", lambda t: t.tsi_slow),
    ("+ quiet", lambda t: t.quiet),
    ("+ tsi slow", lambda t: t.quiet and t.tsi_slow),
    ("+ tsi both", lambda t: t.quiet and t.tsi_slow and t.tsi_mid),
    ("+ mid pattern", lambda t: t.quiet and t.tsi_slow and t.tsi_mid and t.pattern_mid),
    # The operator's question as a filter rather than a description: did
    # volatility *fall* into the entry, whatever its level?
    ("vol falling", lambda t: t.vol_last3 < t.vol_trigger),
    ("vol fell after trigger", lambda t: t.vol_after < t.vol_trigger),
    ("falling and quiet", lambda t: t.quiet and t.vol_last3 < t.vol_trigger),
)


def cut(rows: list[Trade], title: str, key, floor: int = 15) -> None:
    """One breakdown, every bucket with its own n and block-bootstrap error.

    **Buckets below `floor` are printed and not hidden.** A cell with four
    trades in it is not a result, and the way to stop it being quoted as one is
    to show the count beside it rather than to drop the row - a table that
    silently omits its thin cells reads as if every cell shown were the whole
    story.
    """
    buckets: dict[object, list[Trade]] = {}
    for row in rows:
        buckets.setdefault(key(row), []).append(row)
    print(f"  by {title}:")
    for name, group in sorted(buckets.items(), key=lambda kv: str(kv[0])):
        mean = float(np.mean([row.gross for row in group]))
        error = block_error(group) if len(group) >= floor else float("nan")
        thin = "" if len(group) >= floor else "   (thin)"
        print(f"    {str(name):<14} n {len(group):>5,}  {mean:+7.4f} +/- {error:.4f}{thin}")


def microscope(found: dict[str, list[Trade]]) -> None:
    """Every cut of the pattern entry, because a pooled mean hides its parts.

    `pooled-medians-invert-subgroups` is the standing warning: a pooled answer
    here once agreed with a claim that every subgroup refuted. The cuts below
    are the ones that can each produce that, in the order they are most likely
    to - what armed it, which way it faced, what shape confirmed it, when, and
    how long it took.
    """
    rows = [row for rows_ in found.values() for row in rows_ if row.stage == "pattern"]
    if not rows:
        print("no pattern entries to break down")
        return
    print(f"=== the microscope: {len(rows):,} pattern entries, every cut\n")
    cut(rows, "instrument", lambda t: t.feed)
    cut(rows, "what armed it", lambda t: t.trigger)
    cut(rows, "side", lambda t: "long" if t.side > 0 else "short")
    cut(rows, "level role", lambda t: t.role)
    cut(rows, "pattern shape", lambda t: t.kind or "(none)")
    cut(rows, "session (UTC)", lambda t: f"{(t.hour // 4) * 4:02d}-{(t.hour // 4) * 4 + 3:02d}h")
    cut(rows, "bars waited", lambda t: "0-3" if t.waited <= 3 else ("4-11" if t.waited <= 11 else "12+"))
    cut(
        rows,
        "ATR at entry (quantile of its own trailing 200)",
        lambda t: "unknown"
        if not np.isfinite(t.vol_last3)
        else ("low <0.9" if t.vol_last3 < 0.9 else ("mid 0.9-1.2" if t.vol_last3 < 1.2 else "high >1.2")),
    )
    cut(
        rows,
        "level age, structure bars",
        lambda t: "new <5" if t.age < 5 else ("5-20" if t.age < 20 else "old 20+"),
    )
    cut(
        rows,
        "how hard price arrived (ATR over 12 bars)",
        lambda t: "unknown"
        if not np.isfinite(t.approach)
        else ("drift <1" if t.approach < 1 else ("1-2" if t.approach < 2 else "hard 2+")),
    )
    cut(
        rows,
        "distance to a round number (ATR)",
        lambda t: "unknown"
        if not np.isfinite(t.roundness)
        else ("on it <0.1" if t.roundness < 0.1 else ("0.1-0.4" if t.roundness < 0.4 else "away 0.4+")),
    )
    cut(
        rows,
        "where it perches in the range",
        lambda t: "unknown"
        if not np.isfinite(t.perch)
        else ("low <0.25" if t.perch < 0.25 else ("middle" if t.perch < 0.75 else "high >0.75")),
    )
    cut(
        rows,
        "how deep the pull-back went",
        lambda t: "shallow <0.4" if t.depth < 0.4 else ("0.4-0.7" if t.depth < 0.7 else "deep >0.7"),
    )
    print()


def halves(found: dict[str, list[Trade]]) -> None:
    """The two candidates, found on the first half and confirmed on the second.

    **A tail picked out of many cells looks good by chance**, and the two cuts
    below were picked out of about thirty-five. Fixing the date and asking the
    other half is the cheapest thing that can embarrass them.

    A disagreement is reported as information, not as a verdict: the operator's
    standing instruction is that findings may be regime-specific, so the
    question a split raises is "which half are we in now, and is there anything
    observable that says so" rather than "is this real".
    """
    rows = [row for rows_ in found.values() for row in rows_ if row.stage == "pattern"]
    if len(rows) < 40:
        print("too few pattern entries to split\n")
        return
    rows.sort(key=lambda t: t.day)
    middle = rows[len(rows) // 2].day
    first = [row for row in rows if row.day < middle]
    second = [row for row in rows if row.day >= middle]
    print("=== discovery and confirmation, split at the median trading day\n")
    for label, pick in (
        ("armed by a hold", lambda t: t.trigger == "bounce"),
        ("armed by a sweep", lambda t: t.trigger == "sweep"),
        ("waited 0-3 bars", lambda t: t.waited <= 3),
        ("waited 4-11 bars", lambda t: 4 <= t.waited <= 11),
        ("waited 12+ bars", lambda t: t.waited >= 12),
        ("arrived on a drift", lambda t: np.isfinite(t.approach) and t.approach < 1.0),
        ("arrived hard 2+", lambda t: np.isfinite(t.approach) and t.approach >= 2.0),
        ("on a round number", lambda t: np.isfinite(t.roundness) and t.roundness < 0.1),
        ("fresh level <5", lambda t: t.age < 5),
    ):
        line = f"  {label:<18}"
        for half in (first, second):
            picked = [row for row in half if pick(row)]
            if len(picked) < 10:
                line += f"  n {len(picked):>3} (thin)      "
                continue
            mean = float(np.mean([row.gross for row in picked]))
            line += f"  n {len(picked):>3}  {mean:+7.4f} +/- {block_error(picked):.3f}"
        print(line)
    print(f"\n  first half {len(first)} entries, second half {len(second)}\n")


def report(found: dict[str, list[Trade]], horizon: int) -> None:
    """Per instrument and pooled, every stage and every rung of the ladder."""
    print(f"\nhorizon {horizon} execution bars, gross, in ATR of the execution frame")
    print("a mean is printed with its block-bootstrap standard error over days\n")
    for stage in ("bounce", "pullback", "pattern"):
        print(f"=== stage: {stage}")
        pooled: list[Trade] = []
        for feed, rows in found.items():
            picked = [row for row in rows if row.stage == stage]
            pooled += picked
            if not picked:
                print(f"  {feed:<8} no sequences")
                continue
            mean = float(np.mean([row.gross for row in picked]))
            error = block_error(picked)
            print(f"  {feed:<8} n {len(picked):>5,}  {mean:+7.4f} +/- {error:.4f}")
        if pooled:
            mean = float(np.mean([row.gross for row in pooled]))
            print(f"  {'POOLED':<8} n {len(pooled):>5,}  {mean:+7.4f} +/- {block_error(pooled):.4f}")
        print()

    print("=== what armed it: a level that held, against a level that was swept")
    for stage in ("bounce", "pattern"):
        for trigger in ("bounce", "sweep"):
            picked = [
                row
                for rows in found.values()
                for row in rows
                if row.stage == stage and row.trigger == trigger
            ]
            if not picked:
                print(f"  {stage:<8} {trigger:<7} n 0")
                continue
            mean = float(np.mean([row.gross for row in picked]))
            print(
                f"  {stage:<8} {trigger:<7} n {len(picked):>5,}  "
                f"{mean:+7.4f} +/- {block_error(picked):.4f}"
            )
    print()

    print("=== the volatility path through the sequence")
    print("    ATR over the instrument's own trailing median, so 1.00 is normal\n")
    entries = [row for rows in found.values() for row in rows if row.stage == "pattern"]
    if entries:
        for label, pick in (
            ("6 bars before the trigger", lambda t: t.vol_before),
            ("at the trigger", lambda t: t.vol_trigger),
            ("3 bars after it", lambda t: t.vol_after),
            ("the 3 bars before entry", lambda t: t.vol_last3),
        ):
            values = np.array([pick(row) for row in entries], dtype=float)
            values = values[np.isfinite(values)]
            if values.size:
                print(f"  {label:<26} {np.mean(values):5.2f}  (median {np.median(values):4.2f})")
        # **Does any of it separate the outcome?** The question a filter is
        # asking, put directly rather than through a threshold nobody chose.
        print("\n    the same readings, split by how the trade went")
        won = [row for row in entries if row.gross > 0]
        lost = [row for row in entries if row.gross <= 0]
        print(f"    {'':<26} {'won':>6} {'lost':>6}   n {len(won)}/{len(lost)}")
        for label, pick in (
            ("6 bars before", lambda t: t.vol_before),
            ("at the trigger", lambda t: t.vol_trigger),
            ("3 bars after", lambda t: t.vol_after),
            ("3 bars before entry", lambda t: t.vol_last3),
        ):
            a = np.array([pick(row) for row in won], dtype=float)
            b = np.array([pick(row) for row in lost], dtype=float)
            a, b = a[np.isfinite(a)], b[np.isfinite(b)]
            if a.size and b.size:
                print(f"    {label:<26} {np.mean(a):6.2f} {np.mean(b):6.2f}")
    print()

    print("=== the confluence ladder, on the pattern entry")
    print("    each rung against a twin dropping the same share at random\n")
    base = [row for rows in found.values() for row in rows if row.stage == "pattern"]
    if not base:
        print("  no pattern entries at all")
        return
    for name, keep in ARMS:
        picked = [row for row in base if keep(row)]
        if not picked:
            print(f"  {name:<14} n 0")
            continue
        mean = float(np.mean([row.gross for row in picked]))
        error = block_error(picked)
        control = twin(base, len(picked), seed=len(name))
        shadow = float(np.mean([row.gross for row in control]))
        share = len(picked) / len(base)
        print(
            f"  {name:<14} n {len(picked):>5,} ({share:5.1%})  {mean:+7.4f} +/- {error:.4f}"
            f"   twin {shadow:+7.4f}   edge over twin {mean - shadow:+7.4f}"
        )


def drift_table(found: dict[str, list[Trade]], label: str, thresholds=(0.5, 0.75, 1.0, 1.5, 2.0)):
    """The approach effect across thresholds, per instrument and pooled.

    **Swept on the mean and not on a z.** `sweep-thresholds-on-the-mean`
    records a z grid faking a ridge exactly at the chosen threshold where the
    mean grid was monotone; a mean grid that is not monotone is itself the
    finding, and here it was not.
    """
    rows = [row for rows_ in found.values() for row in rows_ if row.stage == "pattern"]
    rows = [row for row in rows if np.isfinite(row.approach)]
    if not rows:
        print(f"  {label}: no entries")
        return
    print(f"  {label}: {len(rows):,} entries")
    header = "    threshold  " + "".join(f"{t:>20.2f}" for t in thresholds)
    print(header)
    for feed in sorted({row.feed for row in rows}) + ["POOLED"]:
        picked = rows if feed == "POOLED" else [row for row in rows if row.feed == feed]
        line = f"    {feed:<10}"
        for t in thresholds:
            under = [row for row in picked if row.approach < t]
            if len(under) < 20:
                line += "      -/-   "
                continue
            own = float(np.mean([row.gross for row in under]))
            fixed = [row.steady for row in under if np.isfinite(row.steady)]
            # **Both denominators, side by side.** The left number divides by
            # the ATR of the entry bar and the right by a unit this selection
            # cannot move. A gap between them is the denominator talking.
            other = float(np.mean(fixed)) if fixed else float("nan")
            line += f"  {own:+6.3f}|{other:+6.3f}/{len(under):<3d}"
        print(line)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument(
        "--csv",
        default="",
        help="name=path,name=path - read these instead of the catalogue, at "
        "--unit, which is how the synthetic feeds are held",
    )
    parser.add_argument("--unit", default="5m", choices=tuple(RATIOS))
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument(
        "--before",
        type=float,
        default=0.0,
        help="end the window this many years before the last bar, so the "
        "search window can be held out",
    )
    parser.add_argument("--slow", default="4h")
    parser.add_argument("--middle", default="1h")
    parser.add_argument("--fast", default="15m")
    parser.add_argument("--horizon", type=int, default=HORIZON)
    parser.add_argument("--band", default="fixed", choices=("fixed", "quantile"))
    parser.add_argument(
        "--overshoot",
        action="store_true",
        help="measure where excursions beyond a level end, instead of trading it",
    )
    parser.add_argument(
        "--arms",
        default="real",
        help="comma-separated: real, placebo, shuffled - the level, a "
        "distance-matched price with no pivot behind it, and the same bars "
        "with their days reordered",
    )
    parser.add_argument(
        "--percentile",
        type=float,
        default=25.0,
        help="percentile of the structure frame's trailing ranges, for --band quantile",
    )
    parser.add_argument(
        "--pullback",
        default=str(PULLBACK_SHARE),
        help="share of the move away from the level that must be given back; "
        "a comma-separated list sweeps it",
    )
    args = parser.parse_args()

    where = Path(args.catalogue)
    shares = [float(part) for part in str(args.pullback).split(",") if part.strip()]
    sources: list[tuple[str, Candles]] = []
    if args.csv:
        for pair in args.csv.split(","):
            name, _, path = pair.partition("=")
            sources.append((name, load_csv(Path(path), name, args.unit)))
    else:
        for symbol in (s for s in args.symbols.split(",") if s):
            sources.append((symbol, load(where, symbol)))

    folded = {}
    raw: dict[str, Candles] = {}
    for symbol, loaded in sources:
        base = window(loaded, args.years, args.before)
        raw[symbol] = base
        start = datetime.fromtimestamp(base.ts[0] / 1e9, UTC).date()
        end = datetime.fromtimestamp(base.ts[-1] / 1e9, UTC).date()
        folded[symbol] = tuple(
            fold(base, name, args.unit) for name in (args.slow, args.middle, args.fast)
        )
        print(
            f"{symbol}: {len(base):,} {args.unit} bars {start} to {end}, "
            f"{len(folded[symbol][0]):,} {args.slow} / {len(folded[symbol][2]):,} {args.fast}"
        )

    if args.overshoot:
        print("\n=== how far beyond a level an excursion gets before it turns\n")
        for arm in ("real", "shuffled"):
            rows: list[tuple] = []
            for symbol, frames in folded.items():
                use = frames
                if arm == "shuffled":
                    use = tuple(
                        fold(shuffled(raw[symbol], seed=11), name, args.unit)
                        for name in (args.slow, args.middle, args.fast)
                    )
                rows += overshoots(use[0], use[2], args.band, args.percentile, args.unit)
            hazard(rows, arm)
            print()
        return

    arms = [name.strip() for name in args.arms.split(",") if name.strip()]
    for share in shares:
        if len(shares) > 1:
            print(f"\n################ pull-back share {share:.2f}")
        per_arm: dict[str, dict[str, list[Trade]]] = {}
        for arm in arms:
            found: dict[str, list[Trade]] = {}
            for symbol, frames in folded.items():
                use = frames
                if arm == "shuffled":
                    use = tuple(
                        fold(shuffled(raw[symbol], seed=11), name, args.unit)
                        for name in (args.slow, args.middle, args.fast)
                    )
                found[symbol] = sequence(
                    *use,
                    horizon=args.horizon,
                    share=share,
                    band=args.band,
                    percentile=args.percentile,
                    placebo=(arm == "placebo"),
                    unit=args.unit,
                )
            per_arm[arm] = found

        print("\n=== the approach effect, swept, per instrument, every arm\n")
        for arm, found in per_arm.items():
            drift_table(found, arm)

        if "real" in per_arm:
            report(per_arm["real"], args.horizon)
            microscope(per_arm["real"])
            halves(per_arm["real"])




# --- the retail lens: where do stops rest? -----------------------------------


def overshoots(slow: Candles, fast: Candles, band: str, percentile: float, unit: str) -> list[tuple]:
    """Every excursion beyond a level, and how far it got before coming back.

    **The only trace stop clustering leaves in bars.** There is no DOM here and
    `real_volume` is zero, so positioning cannot be observed directly. What can
    be observed is where excursions *end*: if retail stops rest just beyond the
    obvious level - which is what every course teaches - then excursions should
    terminate at that distance more often than at any other, and the hazard of
    reversal as a function of overshoot should have a bump in it.

    Returns `(feed, reach, returned)` per excursion: how far beyond the band
    price got, in ATR of the execution frame, and whether it came back inside.
    """
    slow_band = atr(slow, ATR_LEN)
    fast_band = atr(fast, ATR_LEN)
    widths = slow_band if band == "fixed" else adaptive_band(slow, percentile)
    scale = MULT if band == "fixed" else 1.0
    table = RATIOS[unit]
    ratio = table[slow.frame] // table[fast.frame]

    out: list[tuple] = []
    for zone in zones_of(slow, widths, scale):
        start = (zone.at + 1) * ratio
        if start >= len(fast) - 2:
            continue
        edge = zone.top if zone.resistance else zone.bottom
        sign = 1.0 if zone.resistance else -1.0
        inside = True
        reach = 0.0
        for i in range(start, min(len(fast), start + ratio * 200)):
            unit_now = float(fast_band[i])
            if not np.isfinite(unit_now) or unit_now <= 0:
                continue
            beyond = (float(fast.close[i]) - edge) * sign
            extreme = (float(fast.high[i] if zone.resistance else fast.low[i]) - edge) * sign
            if beyond > 0:
                inside = False
                reach = max(reach, extreme / unit_now)
                continue
            if not inside and reach > 0:
                # Closed back inside: the excursion ended and it reversed.
                out.append((fast.symbol, reach, True))
                inside, reach = True, 0.0
        if not inside and reach > 0:
            # Still out at the end of the window: it never came back.
            out.append((fast.symbol, reach, False))
    return out


def hazard(rows: list[tuple], label: str, step: float = 0.25, top: float = 4.0) -> None:
    """P(this excursion ends here | it got this far), by distance beyond.

    **A hazard and not a histogram.** The raw distribution of overshoots falls
    away for the trivial reason that fewer excursions travel further. The
    hazard conditions on having got there, so a flat line means "no distance is
    special" and a bump means excursions are ending at one - which is what a
    shelf of resting stops would look like from the outside.
    """
    if not rows:
        print(f"  {label}: nothing")
        return
    reach = np.array([row[1] for row in rows])
    back = np.array([row[2] for row in rows], dtype=bool)
    print(f"  {label}: {len(rows):,} excursions, {back.mean():.1%} came back")
    edges = np.arange(0.0, top + step, step)
    for lo in edges[:-1]:
        hi = lo + step
        got = reach >= lo
        if got.sum() < 30:
            continue
        ends = got & (reach < hi) & back
        bar = "#" * int(round(60 * ends.sum() / max(1, got.sum())))
        print(f"    {lo:4.2f}-{hi:4.2f}  n {got.sum():>6,}  {ends.sum() / got.sum():6.1%} {bar}")


if __name__ == "__main__":
    main()
