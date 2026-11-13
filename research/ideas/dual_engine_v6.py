"""v6: four engines behind a mandatory 1H pin-bar gate, on eight years.

The change from v2 is a **conjunctive confirmation**: a zone being touched is
no longer a trade. A 1H pin bar has to form at the zone and prove rejection
there. Two new engines come with it - a daily institutional engulfing and a CRT
daily-liquidity sweep - and the runner gets a structural target instead of
trailing indefinitely.

## What is already known, and what it implies for this

Both earlier triggers are closed on this same data
([`dual-engine-confluence.md`](../docs/dual-engine-confluence.md)):

* v1's volatility z-score: **-0.210R on n 906**, indistinguishable from its own
  flip at -0.219R;
* v2's softmax price z-score: **-0.127R on n 356** over 3,111 days, after
  reading +0.162R on n 48 over 464;
* and the shared exit stack - break-even at 1R, half off at 2R, an ATR trail,
  a 48-hour time stop - costs about **0.2R a trade on a direction-free entry**,
  twenty-five times what the spread costs.

v6 keeps that exit stack almost intact, so **any entry it produces has to clear
0.2R before it clears zero**. The one genuine change to the management is TP2:
the runner now targets the daily midpoint or the opposing daily extreme rather
than trailing until something stops it. That is the first structural exit in
this family and it is the part of v6 most likely to matter, because it is the
only change that acts on the thing the measurements have actually convicted.

## The prediction, written before the run

The alignment gate alone rejected **94%** of bars that cleared attention and
**96%** of clusters that cleared both body tests, and the specified
configuration produced **7 trades in 86 days**. A 1H pin bar at the zone is a
second conjunctive gate on top of that one.

So the expectation is that **frequency collapses**, and that the engines which
survive do so because they are the loosest rather than the best. Every gate is
therefore counted separately: a rule that takes four trades and wins three is
not a finding, and without the per-gate counts it is indistinguishable from one.

The two new engines are the interesting half. Engulfing and CRT read daily
structure, which neither earlier trigger touched - a daily engulfing sweeping a
pivot, and a daily high taken out and rejected inside one bar, are different
observations from "the market is volatile" or "price is far from its mean".

## Structure

* `is_pin_bar` - the shared gate, applied before any execution, for all engines.
* `engine_exhaustion`, `engine_choppy`, `engine_engulfing`, `engine_crt` - one
  function each, independently switchable, each returning a `Setup` or None.
* `V6` - the strategy, which owns the frames, runs the engines, holds armed
  setups until the pin bar confirms or they expire, and manages the position.

Sizing, protection, the reduce-only stop and the wrong-side-stop guard are
inherited from `dual_engine_port.DualEngine` rather than rewritten, because
that file carries four measured port defects' worth of fixes and a second
implementation would reintroduce them.

Run it as `uv run python research/ideas/dual_engine_v6.py`.
"""

from __future__ import annotations

import argparse
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nautilus_trader.model.data import Bar

from dual_engine_port import ATR_PERIOD, Candle, DualEngineConfig, Signal, Wilder

# --- the timeframes, in 5-minute execution bars ------------------------------

MINUTES_15 = 3
HOUR_1 = 12
HOUR_4 = 48
DAILY = 288

#: Swing lookback each side, on the 4H frame.
SWING = 7

#: Pivot alignment tolerance, as a multiple of that frame's ATR.
TOLERANCE = 0.015

#: Attention percentile the exhaustion and CRT engines gate on.
Z_PCT = 0.85
Z_HISTORY = 200
Z_LOOKBACK = 70

#: Pin bar geometry, exactly as specified.
PIN_WICK_RATIO = 2.0
PIN_BODY_SHARE = 0.35
PIN_CLOSE_SHARE = 0.25

#: Choppy cluster, and the breakout that ends it.
CHOP_BODY_MAX = 0.35
BREAKOUT_BODY_MIN = 0.50
CLUSTER_MIN = 2
CLUSTER_MAX = 4

#: Origin candle search, in 4H bars.
IMPULSE = 10

#: 15m structure shift for the engulfing engine: a close beyond this many
#: bars' extreme.
SHIFT_BARS = 20

#: How long an armed setup waits for its pin bar before it is dropped, and how
#: long a pending entry waits for its retrace. Both in nanoseconds.
ARM_NS = 48 * 3600 * 1_000_000_000
PENDING_NS = 48 * 3600 * 1_000_000_000


@dataclass(slots=True)
class Zone:
    """An execution zone: a price band, not a price.

    A band because three of the four engines name one - the CRT body, the
    engulfing body, and a pivot plus its tolerance - and collapsing them to a
    midpoint would make "price is inside the zone" a different test from the
    one specified.
    """

    low: float
    high: float

    def holds(self, price: float) -> bool:
        return self.low <= price <= self.high

    def touched(self, candle: Candle) -> bool:
        """Did this candle trade into the band at any point?"""
        return candle.low <= self.high and candle.high >= self.low

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0


@dataclass(slots=True)
class Setup:
    """A signal that has passed its engine and is waiting for confirmation."""

    engine: str
    direction: int
    zone: Zone
    stop: float
    created: int
    #: Set once a 1H pin bar has confirmed rejection at the zone.
    confirmed: bool = False


@dataclass(slots=True)
class Frame:
    """One timeframe, aggregated from the execution feed with no back-fill."""

    span: int
    bars: deque[Candle] = field(default_factory=lambda: deque(maxlen=512))
    atr: Wilder = field(default_factory=lambda: Wilder(ATR_PERIOD))
    forming: list[Bar] = field(default_factory=list)
    previous: float | None = None
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=Z_LOOKBACK))

    def __getitem__(self, index: int) -> Candle:
        """Newest first, as every rule in this family is written."""
        return self.bars[-(index + 1)]

    def __len__(self) -> int:
        return len(self.bars)

    def fold(self, bar: Bar) -> Candle | None:
        """Add one execution bar; return the frame's candle when it closes."""
        self.forming.append(bar)
        if len(self.forming) < self.span:
            return None
        rows, self.forming = self.forming, []
        candle = Candle(
            open=float(rows[0].open),
            high=max(float(r.high) for r in rows),
            low=min(float(r.low) for r in rows),
            close=float(rows[-1].close),
            ts=rows[-1].ts_event,
        )
        span = candle.high - candle.low
        true_range = span
        if self.previous is not None:
            true_range = max(
                span, abs(candle.high - self.previous), abs(candle.low - self.previous)
            )
        self.previous = candle.close
        self.atr.update(true_range)
        self.bars.append(candle)
        self.closes.appendleft(candle.close)
        return candle


# --- the shared gate ---------------------------------------------------------


def is_pin_bar(candle: Candle, direction: int) -> bool:
    """Does this candle reject in `direction`? The gate every engine passes through.

    Three conditions, all of them as specified:

    * the rejecting wick is at least `PIN_WICK_RATIO` times the body;
    * the body is at most `PIN_BODY_SHARE` of the whole range;
    * the close sits in the far `PIN_CLOSE_SHARE` of the range, away from the
      wick.

    The third is written in prose in the specification and is formalised here
    as a share of the range, because "the close must be in the top 25%" has no
    other reading that is checkable.

    **A zero-range candle is refused rather than divided by.** A dead bar
    passes a body-share test trivially - zero is less than any share - and a
    weekend of them would arm every zone on the book.
    """
    span = candle.high - candle.low
    if span <= 0:
        return False
    body = abs(candle.close - candle.open)
    if body / span > PIN_BODY_SHARE:
        return False
    if direction > 0:
        wick = min(candle.open, candle.close) - candle.low
        close_share = (candle.close - candle.low) / span
        return wick >= PIN_WICK_RATIO * body and close_share >= 1.0 - PIN_CLOSE_SHARE
    wick = candle.high - max(candle.open, candle.close)
    close_share = (candle.high - candle.close) / span
    return wick >= PIN_WICK_RATIO * body and close_share >= 1.0 - PIN_CLOSE_SHARE


# --- shared structure --------------------------------------------------------


def pivots(frame: Frame, lookback: int = SWING, most: int = 4) -> tuple[list[float], list[float]]:
    """The most recent confirmed swing highs and lows on a frame."""
    highs: list[float] = []
    lows: list[float] = []
    if len(frame) < 2 * lookback + 1:
        return highs, lows
    for k in range(lookback, min(len(frame) - lookback, 64)):
        bar = frame[k]
        is_high = True
        is_low = True
        for j in range(k - lookback, k + lookback + 1):
            if j == k or j >= len(frame):
                continue
            other = frame[j]
            if other.high >= bar.high:
                is_high = False
            if other.low <= bar.low:
                is_low = False
            if not (is_high or is_low):
                break
        if is_high and len(highs) < most:
            highs.append(bar.high)
        if is_low and len(lows) < most:
            lows.append(bar.low)
        if len(highs) >= most and len(lows) >= most:
            break
    return highs, lows


def aligned(price: float, levels: list[float], tolerance: float) -> bool:
    return any(abs(level - price) <= tolerance for level in levels)


def attention_z(frame: Frame) -> float | None:
    """A softmax-weighted price z-score on one frame, as v2 defines it."""
    prices = list(frame.closes)
    if len(prices) < Z_LOOKBACK:
        return None
    returns = [
        abs(prices[i] / prices[i + 1] - 1.0) if prices[i + 1] else 0.0
        for i in range(len(prices) - 1)
    ]
    returns.append(0.0)
    top = max(returns)
    weights = [math.exp(r - top) for r in returns]
    total = sum(weights)
    if total <= 0:
        return None
    weights = [w / total for w in weights]
    mean = sum(w * p for w, p in zip(weights, prices, strict=True))
    variance = sum(w * (p - mean) ** 2 for w, p in zip(weights, prices, strict=True))
    deviation = math.sqrt(variance)
    if deviation <= 0:
        return None
    return (prices[0] - mean) / deviation


def consensus(zs: list[float]) -> float | None:
    if not zs:
        return None
    top = max(abs(z) for z in zs)
    weights = [math.exp(abs(z) - top) for z in zs]
    total = sum(weights)
    if total <= 0:
        return None
    return sum(w * z for w, z in zip(weights, zs, strict=True)) / total


# --- the four engines --------------------------------------------------------


def engine_exhaustion(
    four: Frame, strong: int, tolerance: float, pad: float
) -> Setup | None:
    """4H reversal: an attention extreme, an impulse origin, on a pivot.

    `strong` is the sign of the attention breach: +1 above the upper threshold,
    -1 below the lower, 0 for no breach. The trade is the **reversal**, so a
    positive breach is a short.
    """
    if strong == 0 or len(four) < IMPULSE + 1:
        return None
    closes = [four[i].close for i in range(IMPULSE)]
    high_at = closes.index(max(closes))
    low_at = closes.index(min(closes))
    if low_at < high_at:
        direction, offset = 1, low_at
    elif high_at < low_at:
        direction, offset = -1, high_at
    else:
        return None
    highs, lows = pivots(four)
    origin = four[offset]
    for price in (origin.open, origin.close):
        if aligned(price, highs + lows, tolerance):
            stop = origin.low - pad if direction > 0 else origin.high + pad
            zone = Zone(min(price, origin.close), max(price, origin.close))
            if zone.low == zone.high:
                zone = Zone(price - tolerance, price + tolerance)
            return Setup("exhaustion", direction, zone, stop, origin.ts)
    return None


def engine_choppy(four: Frame, tolerance: float, pad: float) -> Setup | None:
    """4H breakout: a strong candle leaving a 2-4 bar low-body cluster."""
    if len(four) < CLUSTER_MAX + 2:
        return None
    breakout = four[0]
    if breakout.span <= 0 or breakout.body < BREAKOUT_BODY_MIN * breakout.span:
        return None
    highs, lows = pivots(four)
    for size in range(CLUSTER_MIN, CLUSTER_MAX + 1):
        cluster = [four[i] for i in range(1, size + 1)]
        if not all(c.span > 0 and c.body < CHOP_BODY_MAX * c.span for c in cluster):
            continue
        top = max(c.high for c in cluster)
        bottom = min(c.low for c in cluster)
        if breakout.close > top:
            direction = 1
        elif breakout.close < bottom:
            direction = -1
        else:
            continue
        for price in (breakout.open, breakout.close):
            if aligned(price, highs + lows, tolerance):
                stop = bottom - pad if direction > 0 else top + pad
                return Setup(
                    "choppy",
                    direction,
                    Zone(price - tolerance, price + tolerance),
                    stop,
                    breakout.ts,
                )
    return None


def engine_engulfing(day: Frame, four: Frame, tolerance: float, pad: float) -> Setup | None:
    """Daily institutional engulfing that sweeps a 4H pivot.

    The zone is frozen at the engulfing body and is **not** re-derived later -
    the specification says freeze it, and a zone that drifts with price is a
    zone that always contains price.
    """
    if len(day) < 2:
        return None
    current, prior = day[0], day[1]
    if current.span <= 0:
        return None
    engulfs_up = current.close > prior.open and current.open < prior.close
    engulfs_down = current.close < prior.open and current.open > prior.close
    if not (engulfs_up or engulfs_down):
        return None
    direction = 1 if engulfs_up else -1
    highs, lows = pivots(four)
    swept = current.low if direction > 0 else current.high
    if not aligned(swept, lows if direction > 0 else highs, tolerance):
        return None
    zone = Zone(min(current.open, current.close), max(current.open, current.close))
    stop = current.low - pad if direction > 0 else current.high + pad
    return Setup("engulfing", direction, zone, stop, current.ts)


def engine_crt(
    fifteen: Frame, four: Frame, day_high: float, day_low: float,
    strong: int, tolerance: float, pad: float,
) -> Setup | None:
    """A daily extreme taken out and rejected inside one 15m bar."""
    if len(fifteen) < 1 or strong == 0:
        return None
    sweep = fifteen[0]
    highs, lows = pivots(four)
    if sweep.high > day_high > sweep.close and strong > 0:
        if not aligned(sweep.high, highs, tolerance):
            return None
        zone = Zone(min(sweep.open, sweep.close), max(sweep.open, sweep.close))
        return Setup("crt", -1, zone, sweep.high + pad, sweep.ts)
    if sweep.low < day_low < sweep.close and strong < 0:
        if not aligned(sweep.low, lows, tolerance):
            return None
        zone = Zone(min(sweep.open, sweep.close), max(sweep.open, sweep.close))
        return Setup("crt", 1, zone, sweep.low - pad, sweep.ts)
    return None


# --- the strategy ------------------------------------------------------------


class V6Config(DualEngineConfig, frozen=True):
    enable_exhaustion: bool = True
    enable_choppy: bool = True
    enable_engulfing: bool = True
    enable_crt: bool = True
    #: Off turns the 1H pin bar gate into a no-op, which is the control that
    #: says what the gate itself is worth rather than what the engines are.
    require_pin: bool = True


def build(config: V6Config) -> Any:
    """Imported lazily so the module can be read without an engine present."""
    from dual_engine_port import DualEngine

    class V6(DualEngine):
        """Four engines, one gate, inheriting v1's fixed execution path."""

        def __init__(self, cfg: V6Config) -> None:
            super().__init__(cfg)  # type: ignore[arg-type]
            self.cfg6 = cfg
            self.frames = {
                "15m": Frame(MINUTES_15),
                "1h": Frame(HOUR_1),
                "4h": Frame(HOUR_4),
                "1d": Frame(DAILY),
            }
            self.armed: list[Setup] = []
            self._zs: deque[float] = deque(maxlen=Z_HISTORY)
            self._day_high = 0.0
            self._day_low = 0.0
            self._day_mid = 0.0
            self.fired: dict[str, int] = {}
            self.gated: dict[str, int] = {}
            self.confirmed: dict[str, int] = {}
            self.target: float | None = None
            self._latest_z: float | None = None

        def _close_4h(self) -> None:
            """Disabled: v6 drives its own frames from `on_bar`."""

        def _tally(self, book: dict[str, int], key: str) -> None:
            book[key] = book.get(key, 0) + 1

        def on_bar(self, bar: Bar) -> None:
            candle = Candle(
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                ts=bar.ts_event,
            )
            tr = self._true_range(candle, self._prev15)
            self._prev15 = candle.close
            self.atr15.update(tr)
            self.tr15.update(tr)

            closed = {name: frame.fold(bar) for name, frame in self.frames.items()}
            if closed["1d"] is not None:
                done = closed["1d"]
                self._day_high, self._day_low = done.high, done.low
                self._day_mid = (done.high + done.low) / 2.0

            zs = [
                z
                for frame in self.frames.values()
                if (z := attention_z(frame)) is not None
            ]
            if len(zs) == len(self.frames) and (found := consensus(zs)) is not None:
                self._zs.append(abs(found))
                self._latest_z = found
            strong = self._breach()

            if closed["4h"] is not None or closed["1d"] is not None or closed["15m"] is not None:
                self._look(closed, strong)
            if closed["1h"] is not None:
                self._confirm(closed["1h"])
            self._expire(candle.ts)

            held = self.cache.positions_open(instrument_id=self.config.instrument_id)
            if self._trade is not None and not held:
                self._trade = None
                self._stop_order = None
                self.target = None
            if self._trade is not None:
                self._manage(candle)
                self._runner(candle)
            elif self.pending is not None:
                self._try_enter(candle)

        def _breach(self) -> int:
            latest = getattr(self, "_latest_z", None)
            if latest is None or len(self._zs) < Z_HISTORY:
                return 0
            values = sorted(self._zs)
            position = Z_PCT * (len(values) - 1)
            lower = int(math.floor(position))
            upper = min(lower + 1, len(values) - 1)
            threshold = values[lower] + (values[upper] - values[lower]) * (position - lower)
            if abs(latest) <= threshold:
                return 0
            return 1 if latest > 0 else -1

        def _look(self, closed: dict[str, Candle | None], strong: int) -> None:
            if self._trade is not None or self.pending is not None:
                return
            four, day, fifteen = self.frames["4h"], self.frames["1d"], self.frames["15m"]
            if not four.atr.ready or not self.atr15.ready:
                return
            tol4 = TOLERANCE * four.atr.value
            told = TOLERANCE * day.atr.value if day.atr.ready else tol4
            pad = 0.5 * self.atr15.value

            found: Setup | None = None
            if self.cfg6.enable_exhaustion and closed["4h"] is not None:
                found = engine_exhaustion(four, strong, tol4, pad)
            if found is None and self.cfg6.enable_choppy and closed["4h"] is not None:
                found = engine_choppy(four, tol4, pad)
            if found is None and self.cfg6.enable_engulfing and closed["1d"] is not None:
                found = engine_engulfing(day, four, told, pad)
            if found is None and self.cfg6.enable_crt and closed["15m"] is not None and self._day_high:
                found = engine_crt(fifteen, four, self._day_high, self._day_low, strong, tol4, pad)
            if found is None:
                return
            self._tally(self.fired, found.engine)
            if not self.cfg6.require_pin:
                found.confirmed = True
                self._arm(found)
                return
            self.armed.append(found)

        def _confirm(self, hourly: Candle) -> None:
            """A 1H pin bar at an armed zone is what turns a setup into a trade."""
            for setup in list(self.armed):
                if not is_pin_bar(hourly, setup.direction):
                    continue
                if not setup.zone.touched(hourly):
                    self._tally(self.gated, f"{setup.engine}:pin-away-from-zone")
                    continue
                setup.confirmed = True
                self._tally(self.confirmed, setup.engine)
                self.armed.remove(setup)
                self._arm(setup)
                return

        def _arm(self, setup: Setup) -> None:
            if self.config.flip:
                direction = -setup.direction
                level = setup.zone.mid
                stop = level + (level - setup.stop)
            else:
                direction, level, stop = setup.direction, setup.zone.mid, setup.stop
            self.pending = Signal(setup.engine, direction, level, stop, setup.created)
            self.signals[setup.engine] = self.signals.get(setup.engine, 0) + 1

        def _expire(self, now: int) -> None:
            for setup in list(self.armed):
                if now - setup.created > ARM_NS:
                    self.armed.remove(setup)
                    self._tally(self.gated, f"{setup.engine}:never-confirmed")

        def _runner(self, candle: Candle) -> None:
            """TP2: the runner targets the daily midpoint rather than trailing on."""
            state = self._trade
            if state is None or not state.get("partial") or not self._day_mid:
                return
            held = self.cache.positions_open(instrument_id=self.config.instrument_id)
            if not held:
                return
            position = held[0]
            long = state["direction"] > 0
            reached = candle.close >= self._day_mid if long else candle.close <= self._day_mid
            if reached:
                state["ending"] = "tp2"
                self._flatten(position, "tp2")

    return V6(config)


# --- running it --------------------------------------------------------------

CATALOGUE = Path.home() / "till-data" / "mt5-deep"
SPEC = "5-MINUTE-LAST-EXTERNAL"

#: Each engine alone, then all four, then the gate removed. The last is the
#: control that separates "the engines found nothing" from "the gate refused
#: everything" - two outcomes that look identical in a trade count.
ARMS: tuple[tuple[str, dict[str, bool]], ...] = (
    ("exhaustion", {"enable_choppy": False, "enable_engulfing": False, "enable_crt": False}),
    ("choppy", {"enable_exhaustion": False, "enable_engulfing": False, "enable_crt": False}),
    ("engulfing", {"enable_exhaustion": False, "enable_choppy": False, "enable_crt": False}),
    ("crt", {"enable_exhaustion": False, "enable_choppy": False, "enable_engulfing": False}),
    ("all four", {}),
    ("all four, no pin gate", {"require_pin": False}),
)


def run(instruments: list[Any], data: list[Any], knobs: dict[str, bool], *, flip: bool) -> Any:
    from decimal import Decimal

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.objects import Money

    from dual_engine_port import EQUITY, LEVERAGE

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="V6-001",
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    for venue in sorted({i.id.venue for i in instruments}, key=str):
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USD,
            starting_balances=[Money(EQUITY, USD)],
            default_leverage=Decimal(str(LEVERAGE)),
        )
    built = []
    for n, instrument in enumerate(instruments):
        engine.add_instrument(instrument)
        strategy = build(
            V6Config(
                instrument_id=instrument.id,
                bar_type=BarType.from_str(f"{instrument.id}-{SPEC}"),
                feed=str(instrument.id.symbol),
                bars_per_structure=HOUR_4,
                flip=flip,
                order_id_tag=f"{n:04d}",
                **knobs,
            )
        )
        engine.add_strategy(strategy)
        built.append(strategy)
    engine.add_data(data)
    engine.run()
    out = {
        "closed": [t for s in built for t in s.closed],
        "fired": _merge(s.fired for s in built),
        "confirmed": _merge(s.confirmed for s in built),
        "gated": _merge(s.gated for s in built),
    }
    engine.dispose()
    return out


def _merge(books: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for book in books:
        for key, value in book.items():
            out[key] = out.get(key, 0) + value
    return out


def main() -> None:
    from dual_engine_grid import Cell, load_all, measure, span_days

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--arm", default="")
    args = parser.parse_args()

    instruments, data = load_all(Path(args.catalogue), SPEC)
    if not instruments:
        raise SystemExit(f"nothing in {args.catalogue}")
    days = span_days(data)
    bars = sum(1 for row in data if isinstance(row, Bar))
    print(f"{len(instruments)} instruments, {bars} bars, {days:.0f} days, 5m execution")
    print("frames 15m/1H/4H/1D; pin gate on 1H\n")

    for name, knobs in ARMS:
        if args.arm and name != args.arm:
            continue
        out = {}
        for flip in (False, True):
            found = run(instruments, data, knobs, flip=flip)
            cell = Cell(0.015, Z_PCT, 0.01, flip, bars_per_structure=HOUR_4, bar_spec=SPEC)
            out[flip] = (measure(cell, found["closed"], days), found)
        rule, detail = out[False]
        null = out[True][0]
        gap = rule.reward - null.reward if rule.trades and null.trades else float("nan")
        se = math.sqrt(rule.reward_se**2 + null.reward_se**2) or float("nan")
        print(
            f"  {name:<22} rule n {rule.trades:>4} R {rule.reward:>+6.3f} "
            f"+/-{rule.reward_se:>5.3f} dd {rule.drawdown:>5.1%}  |  "
            f"flip n {null.trades:>4} R {null.reward:>+6.3f}  |  "
            f"gap {gap:>+6.3f} ({gap / se:>+5.2f} se)"
        )
        fired = ", ".join(f"{k} {v}" for k, v in sorted(detail["fired"].items())) or "none"
        ok = ", ".join(f"{k} {v}" for k, v in sorted(detail["confirmed"].items())) or "none"
        print(f"       engines fired [{fired}]  confirmed by pin [{ok}]")
        if detail["gated"]:
            print(f"       dropped [{', '.join(f'{k} {v}' for k, v in sorted(detail['gated'].items()))}]")


if __name__ == "__main__":
    main()
