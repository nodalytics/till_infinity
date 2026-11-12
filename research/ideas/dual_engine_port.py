"""The dual-engine confluence rule, ported from LEAN to Nautilus and run on the catalogue.

Two signal engines feeding one retest entry and one management stack, as
specified: **exhaustion reversal** (a multi-timeframe attention z-score above
its 85th percentile plus a 10-bar 4H impulse candle aligned to a swing pivot)
and **choppy breakout** (2-4 low-body 4H candles broken by a strong one, also
aligned to a pivot). Both wait for a 15m retest of the signal level, then run
break-even at +1R, a 50% partial at +2R, an ATR trail after the partial, and a
48-hour time stop.

## What this can settle, and what it cannot

The catalogue is **76-86 days of 15m bars for six feeds** with one modelled
quote per bar. This rule signals on the **4H** close, so each feed offers about
**450 4H bars**, of which the first ~100 go to warming the 4H attention
statistics and the first 64 to filling the pivot window. Call it **350 signal
opportunities per feed**, and the rule declines most of them by construction.

So the honest reading of anything below is: **mechanic, not edge.** Trade
counts, firing rates by branch, which exit binds, and what the round trip costs
in R are all settled here. A mean R is not, and the standard error is printed
beside every one so that is visible rather than argued.

`node/corpus.py` records the rest: the quotes are modelled at the measured
median spread for that feed on that venue, never pooled, so the cost figures
are real and the path between bar closes is not.

## The nulls, written before the run

* **`flip`** - every signal's direction reversed, nothing else touched. Same
  pivots, same levels, same stop distances, same retest clock, same spread.
  Anything both arms earn is not direction, it is geometry. This is the arm
  that has killed ideas on this desk before and it is run on every feed.
* **The four feeds the rule was not written for.** It specifies EURUSD and
  XAUUSD; the catalogue also holds GBPUSD, BTC, US100 and SPX500. Widening the
  universe from sixteen instruments to twenty-nine once killed the only
  positive cell in a sixty-cell sweep here, so the four are run and reported
  separately rather than pooled in or left out.
* **Per branch, never only together.** The two engines are independent and the
  toggles exist in the original for exactly this reason, so each is run alone
  as well as composed. A rule that only works composed is a rule whose two
  halves are being selected over.

**No power arm is claimed.** At these trade counts a null would not be a null,
it would be a sample too small to read, and `show-power-before-reporting-a-null`
is the standing instruction. What is reported is the count and the error.

## Divergences from the LEAN original, each one deliberate

| what | the original | here | why |
|---|---|---|---|
| 4H bars | `QuoteBarConsolidator` | aggregated in the strategy, **no back-fill** | `timeframes.py` measured a 48.5-hour session gap becoming 194 empty M15 bars; an internally aggregated 4H frame would hold candles no session produced, and this rule reads candle bodies |
| retest trigger | `bar.bid.low` / `bar.ask.high` | the bar's own high/low | the store keeps one modelled quote per bar, so there are no bid/ask extremes; the spread is still paid on the fill |
| stale stop after a partial | cancel, re-arm, `SL-RESIDUAL` flatten | `reduce_only=True` | the venue clamps a reduce-only stop to the open size, so the whole residual-flip path the original had to hand-code cannot arise |
| indicators | QC `AverageTrueRange` etc. | computed here | QC's ATR is Wilder-smoothed and its `StandardDeviation` is a population sd; matching them by naming a framework indicator is how two implementations quietly stop agreeing |
| `int(quantity)` | truncation | `instrument.make_qty` | gold is one ounce per unit in this catalogue (`corpus.CONTRACTS` records why), and truncating a 0.02-lot budget is a 15% error on the risk |

## What it read, 2026-11-12

**The rule as specified fires seven times on its own two instruments in 76-86
days.** Not seven a month - seven. That is the first result and it is a
mechanic, not a reading.

Widening the one parameter that does nearly all the selection is what makes it
measurable, and what it measures is the gap closing:

| tolerance | EURUSD+GOLD | its own flip | gap | the other four |
|---|---|---|---|---|
| 0.015 (specified) | n 7, **+1.103** +/-0.749 | n 5, -0.025 +/-0.595 | +1.13 | n 6, -0.164 |
| 0.05 | n 14, **+0.301** +/-0.473 | n 8, -0.372 +/-0.429 | +0.67 | n 13, -0.213 |
| 0.10 | n 22, **+0.114** +/-0.346 | n 14, -0.079 +/-0.356 | +0.19 | n 32, -0.190 |

At 0.10 the standard error of the difference is about **0.50R against a gap of
0.19R** - four tenths of a standard error - and the win rate falls 71% -> 43%
-> 36% as the sample grows. That is the shape `Kills` already records for
fade-to-value: "+0.120R on 477 trades at 1d, +0.017R on 985 at 4h and -0.007R
on 2,786 at 1h - shrinking as the sample grew and reversing on the largest".

**On the four feeds the rule was not written for, both directions lose** at
every tolerance (-0.213 and -0.345 at 0.05; -0.190 and -0.175 at 0.10). Two
arms that both lose by about the same amount is the round trip being paid, not
a direction being read.

Three further mechanics, each of which is a fact about the rule and not about
the sample:

* **Alignment is the whole filter.** Of the 4H bars that clear the attention
  percentile, the pivot test rejects **94%**; on the choppy side it rejects
  **96%** of clusters that survive both body tests. At `0.015 x ATR(4H)` the
  tolerance on EURUSD is about **0.2 pips**, which is an exact-price match
  wearing a tolerance's clothes.
* **GBPUSD produces zero signals** in every arm at the specified tolerance -
  not zero trades, zero signals.
* **The sizing does not risk what it says on FX.** 1% of equity against a
  16-pip stop wants about 619,000 EURUSD units, seven times the account, so
  `MAX_LEVERAGE` binds and the trade actually risks **0.7%**. Two of the three
  EURUSD entries were capped. On gold, where the stop is wide in price terms,
  the full 1% goes on.

## Four port defects, each of which read as a result

Kept because every one printed a plausible number rather than an error, and
the number is the only reason it was caught.

| what | what it printed |
|---|---|
| entries submitted `FOK` - the bar-built book cannot fill 437,000 units at once, so the venue canceled them silently | `EUR/USD: no trades` |
| the protective stop attached on `on_order_filled`, which runs before the position reaches the cache, so it was never submitted | 48-hour exits at **-3.4R**, a loss no 1R stop can produce |
| the stop sized to the **first fill slice** - 1,113 units of a 437,897-unit position - and the same slice recorded as the R denominator | **-1350R a trade**, with the P&L correct throughout |
| the flip's mirrored stop landing on the wrong side of a retest that overshot | five rejected protective orders, all of them in the null arm |

The first two were silent; the second two were loud and wrong. `on_order_denied`,
`on_order_rejected` and `on_order_canceled` are now counted by reason, and a
trade that reaches its close with no stop attached is labelled `!naked` in the
exit mix rather than averaged in.

Run it as `uv run python research/ideas/dual_engine_port.py`, `--why` for the
per-feed gate counts, `--tolerance` for the alignment grid.
"""

from __future__ import annotations

import argparse
import math
import random
from collections import deque
from decimal import Decimal
from dataclasses import dataclass
from typing import Any

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import (
    BacktestEngineConfig,
    LoggingConfig,
    RiskEngineConfig,
    StrategyConfig,
)
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import (
    AccountType,
    OmsType,
    OrderSide,
    PositionSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.trading.strategy import Strategy

from till_infinity.node.backtest import catalogue

# --- the rule's constants, names and values as specified ---------------------

SWING_LOOKBACK = 7
MAX_PIVOTS = 4
PIVOT_TOLERANCE_ATR = 0.015
ATR_PERIOD = 14
IMPULSE_LOOKBACK = 10
ATTENTION_PERIOD_15M = 200
ATTENTION_PERIOD_4H = 100
ATTENTION_WINDOW = 500
MIN_ATTENTION_SAMPLES = 250
STRONG_PERCENTILE = 85.0
BODY_RANGE_RATIO_MAX = 0.35
BREAKOUT_BODY_RATIO = 0.50
CLUSTER_MIN = 2
CLUSTER_MAX = 4
BE_TRIGGER_R = 1.0
BE_OFFSET_ATR = 0.1
TP_TRIGGER_R = 2.0
TP_FRACTION = 0.5
TSL_ATR_MULT = 2.0
RISK_FRACTION = 0.01
MAX_LEVERAGE = 5.0
MAX_GROSS_LEVERAGE = 10.0
MIN_RISK_ATR = 0.5
WINDOW_4H = 64

#: Nanoseconds. The original states both as `timedelta(hours=48)`.
TIME_STOP_NS = 48 * 3600 * 1_000_000_000
PENDING_EXPIRY_NS = 48 * 3600 * 1_000_000_000

#: Account size, matching the original's `set_cash(100_000)`.
EQUITY = 100_000.0

#: Account leverage, and **the first thing this port got wrong**.
#:
#: `node/backtest.DEFAULT_LEVERAGE` says it in full: "an unset leverage
#: silently decides every backtest's trade count. A run that cannot afford its
#: own orders reports no trades, not an error." This file built its venue by
#: hand and inherited Nautilus's 1.0, so EURUSD fired five signals, submitted
#: five orders worth about 386,000 USD of notional against a 100,000 account,
#: had every one denied for margin, and printed **"no trades"** - which reads
#: as a rule that does not fire on its own headline instrument.
#:
#: 30 is the retail cap on a major FX pair and what `node/backtest.py` uses. It
#: is set here so the rule's **own** caps bind - `MAX_LEVERAGE` at 5 per
#: position and `MAX_GROSS_LEVERAGE` at 10 - rather than the venue's, which is
#: the thing being measured.
LEVERAGE = 30.0

#: Four hours in 15-minute bars. The 4H frame is built from these rather than
#: requested, so a weekend produces no bar instead of 192 empty ones.
BARS_PER_4H = 16


# --- the pieces of state the rule carries ------------------------------------


class Window:
    """A fixed-length history where index 0 is the newest.

    LEAN's `RollingWindow` indexes newest-first and the rule's arithmetic
    depends on it - `lo_offset < hi_offset` means the low is *more recent*, and
    reading it oldest-first reverses every exhaustion signal. Written out rather
    than wrapped around a deque so the direction is visible at the call site.
    """

    def __init__(self, size: int) -> None:
        self._rows: deque[Any] = deque(maxlen=size)
        self._size = size

    def add(self, row: Any) -> None:
        self._rows.appendleft(row)

    def __getitem__(self, index: int) -> Any:
        return self._rows[index]

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def ready(self) -> bool:
        return len(self._rows) == self._size


class Wilder:
    """Wilder-smoothed average true range, which is what QC's ATR defaults to.

    Seeded on the first `period` true ranges with their mean, then smoothed -
    the standard definition. Computed here rather than taken from a framework
    because QC's default is Wilder and Nautilus's is simple, and a port that
    swaps one for the other reports a different stop distance on every trade
    while both sides claim to be "the ATR".
    """

    def __init__(self, period: int) -> None:
        self.period = period
        self._seed: list[float] = []
        self.value = 0.0

    @property
    def ready(self) -> bool:
        return self.value > 0.0

    def update(self, true_range: float) -> None:
        if len(self._seed) < self.period:
            self._seed.append(true_range)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
            return
        self.value = (self.value * (self.period - 1) + true_range) / self.period


class Rolling:
    """Rolling mean and **population** standard deviation over a fixed window.

    Population, not sample: QC's `StandardDeviation` divides by n, and a port
    that divides by n-1 shifts every z-score by a factor of `sqrt(n/(n-1))` -
    0.25% at n=200, which is invisible in a plot and moves a percentile gate.
    """

    def __init__(self, period: int) -> None:
        self._rows: deque[float] = deque(maxlen=period)
        self.period = period

    def update(self, value: float) -> None:
        self._rows.append(value)

    @property
    def ready(self) -> bool:
        return len(self._rows) == self.period

    @property
    def mean(self) -> float:
        return sum(self._rows) / len(self._rows) if self._rows else 0.0

    @property
    def sd(self) -> float:
        if len(self._rows) < 2:
            return 0.0
        mean = self.mean
        return math.sqrt(sum((v - mean) ** 2 for v in self._rows) / len(self._rows))

    def z(self, value: float) -> float | None:
        if not self.ready or self.sd <= 0.0:
            return None
        return (value - self.mean) / self.sd


@dataclass(slots=True)
class Candle:
    """One aggregated 4H bar, or one 15m bar, in the fields the rule reads."""

    open: float
    high: float
    low: float
    close: float
    ts: int

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def span(self) -> float:
        return self.high - self.low


@dataclass(slots=True)
class Signal:
    """A signal waiting for its 15-minute retest."""

    branch: str
    direction: int
    level: float
    stop: float
    created: int

    def expired(self, now: int) -> bool:
        return now - self.created > PENDING_EXPIRY_NS


@dataclass(slots=True)
class Trade:
    """One finished trade, in the terms the summary is computed from."""

    feed: str
    branch: str
    direction: int
    entry: float
    exit: float
    quantity: float
    risk_price: float
    profit: float
    ending: str
    seconds: float
    day: int

    @property
    def reward(self) -> float:
        """R, against the money the trade was sized to risk."""
        risked = self.risk_price * self.quantity
        return self.profit / risked if risked > 0 else 0.0


# --- the strategy ------------------------------------------------------------


class DualEngineConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    feed: str = ""
    risk_per_trade: float = RISK_FRACTION
    tolerance_mult: float = PIVOT_TOLERANCE_ATR
    z_pct: float = STRONG_PERCENTILE / 100.0
    tsl_atr_mult: float = TSL_ATR_MULT
    min_risk_atr: float = MIN_RISK_ATR
    exhaustion: bool = True
    choppy: bool = True
    #: The null. Every signal's direction reversed and nothing else changed.
    flip: bool = False


class DualEngine(Strategy):
    """The rule, on one instrument.

    One trade at a time, as the original enforces - "one trade per symbol at a
    time" is in its 4H handler and the 15m handler re-checks it, so a signal
    found while a position is open is discarded rather than queued.
    """

    def __init__(self, config: DualEngineConfig) -> None:
        super().__init__(config)
        self.feed = config.feed or str(config.instrument_id.symbol)
        self.window4h = Window(WINDOW_4H)
        self.atr15 = Wilder(ATR_PERIOD)
        self.atr4h = Wilder(ATR_PERIOD)
        self.tr15 = Rolling(ATTENTION_PERIOD_15M)
        self.tr4h = Rolling(ATTENTION_PERIOD_4H)
        self.attention = Window(ATTENTION_WINDOW)
        self.attention_seen = 0
        self.bars4h = 0
        self._prev15: float | None = None
        self._prev4h: float | None = None
        self._z4h: float | None = None
        self.pivot_highs: list[Candle] = []
        self.pivot_lows: list[Candle] = []
        self.pending: Signal | None = None

        self._forming: list[Bar] = []
        self._instrument: Any = None

        self._trade: dict[str, Any] | None = None
        self._stop_order: Any = None
        self.closed: list[Trade] = []
        #: Why a signal was not taken, by reason. A rule that fires nothing and
        #: a rule that is refused everywhere read identically without this.
        self.declined: dict[str, int] = {}
        self.signals: dict[str, int] = {}

    # ----------------------------------------------------------------- wiring

    def on_start(self) -> None:
        self._instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_bars(self.config.bar_type)

    def on_order_denied(self, event: Any) -> None:
        """**A denied order used to be indistinguishable from a quiet rule.**

        The engine's own risk check refuses before the venue sees anything, and
        with no handler the strategy simply never heard back - five EURUSD
        entries vanished into a printed "no trades". Counted with the reason
        attached so the next one says so on the first run.
        """
        self._count(f"order:denied:{str(getattr(event, 'reason', ''))[:40]}")

    def on_order_rejected(self, event: Any) -> None:
        self._count(f"order:rejected:{str(getattr(event, 'reason', ''))[:40]}")

    def on_order_canceled(self, event: Any) -> None:
        """**The one that was actually happening, and the quietest of the three.**

        The entry was submitted `FOK`, so the venue canceled any order larger
        than the size its bar-built book could fill at once - no denial, no
        rejection, no fill, no log. EURUSD sizes to about 333,000 units on a 1%
        risk and a 30-pip stop, so every one of its five entries was canceled
        and the feed printed "no trades". The original submits a plain market
        order and that is what is submitted now; this counter stays so the
        next cancel says so rather than reading as a rule that does not fire.
        """
        if self._stop_order is not None and event.client_order_id == self._stop_order.client_order_id:
            return
        self._count("order:canceled")

    def on_stop(self) -> None:
        if self.pending is not None:
            self._count("entry:still-pending-at-end")

    def _count(self, name: str) -> None:
        self.declined[name] = self.declined.get(name, 0) + 1

    @staticmethod
    def _true_range(bar: Candle, previous: float | None) -> float:
        if previous is None:
            return bar.span
        return max(bar.span, abs(bar.high - previous), abs(bar.low - previous))

    # -------------------------------------------------------------------- 15m

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
        self._attend(tr)

        self._forming.append(bar)
        if len(self._forming) >= BARS_PER_4H:
            self._close_4h()

        held = self.cache.positions_open(instrument_id=self.config.instrument_id)
        if self._trade is not None and not held:
            self._trade = None
            self._stop_order = None
        if self._trade is not None:
            self._manage(candle)
        elif self.pending is not None:
            self._try_enter(candle)

    def _attend(self, tr15: float) -> None:
        """The multi-timeframe attention score: half the 15m z, half the 4H z."""
        z15 = self.tr15.z(tr15)
        if z15 is None or self._z4h is None:
            return
        self.attention.add(0.5 * z15 + 0.5 * self._z4h)
        self.attention_seen += 1

    def _attention_strong(self) -> bool:
        """Is the newest attention reading above its own window's percentile?

        **The window includes the reading being tested**, which is how the
        original is written and is kept: excluding it would make the gate
        slightly easier and the two implementations would stop agreeing on the
        trades, which is the thing a port is for.
        """
        if self.attention_seen < MIN_ATTENTION_SAMPLES:
            return False
        values = sorted(self.attention[i] for i in range(len(self.attention)))
        if not values:
            return False
        # Linear interpolation between order statistics - `np.percentile`'s
        # default, written out so the port does not depend on a default.
        position = self.config.z_pct * (len(values) - 1)
        lower = int(math.floor(position))
        upper = min(lower + 1, len(values) - 1)
        threshold = values[lower] + (values[upper] - values[lower]) * (position - lower)
        return self.attention[0] > threshold

    # --------------------------------------------------------------------- 4H

    def _close_4h(self) -> None:
        """Emit one 4H candle from the 15m bars that actually arrived.

        **No back-fill.** `strategies/timeframes.py` records a 48.5-hour session
        gap becoming 194 empty M15 bars under internal aggregation. This rule
        grades candle bodies against their ranges, so an empty candle is not a
        quiet market to it - it is a division by a zero range, or a body of
        exactly nothing that passes the choppy test on every cluster.
        """
        rows, self._forming = self._forming, []
        candle = Candle(
            open=float(rows[0].open),
            high=max(float(r.high) for r in rows),
            low=min(float(r.low) for r in rows),
            close=float(rows[-1].close),
            ts=rows[-1].ts_event,
        )
        tr = self._true_range(candle, self._prev4h)
        self._prev4h = candle.close
        self.atr4h.update(tr)
        self.tr4h.update(tr)
        self._z4h = self.tr4h.z(tr)

        self.window4h.add(candle)
        self.bars4h += 1
        if not self.window4h.ready:
            return
        self._refresh_pivots()

        if self._trade is not None:
            return  # one trade per symbol at a time
        if not (self.atr15.ready and self.atr4h.ready):
            return
        tolerance = self.config.tolerance_mult * self.atr4h.value

        found = None
        if self.config.exhaustion:
            found = self._eval_exhaustion(tolerance)
        if found is None and self.config.choppy:
            found = self._eval_choppy(tolerance)
        if found is None:
            return
        if self.config.flip:
            found = self._reverse(found)
        self.signals[found.branch] = self.signals.get(found.branch, 0) + 1
        if self.pending is not None:
            # **Counted, because otherwise the arithmetic does not close.** The
            # original overwrites an untriggered signal with the next one and so
            # does this; without the count, signals minus trades minus expiries
            # left a silent remainder that looks like trades going missing.
            self._count("entry:replaced")
        self.pending = found

    def _reverse(self, found: Signal) -> Signal:
        """The null arm: the same signal, the other way round.

        The stop is mirrored through the level rather than copied, because a
        reversed trade with the original's stop would have a different risk
        distance and the two arms would stop being comparable in R - which is
        the one thing the flip exists to compare.
        """
        return Signal(
            branch=found.branch,
            direction=-found.direction,
            level=found.level,
            stop=found.level + (found.level - found.stop),
            created=found.created,
        )

    def _refresh_pivots(self) -> None:
        """The four most recent confirmed 4H swing highs and lows."""
        highs: list[Candle] = []
        lows: list[Candle] = []
        for k in range(SWING_LOOKBACK, WINDOW_4H - SWING_LOOKBACK):
            bar = self.window4h[k]
            is_high = True
            is_low = True
            for j in range(k - SWING_LOOKBACK, k + SWING_LOOKBACK + 1):
                if j == k:
                    continue
                other = self.window4h[j]
                if other.high >= bar.high:
                    is_high = False
                if other.low <= bar.low:
                    is_low = False
                if not (is_high or is_low):
                    break
            if is_high:
                highs.append(bar)
            if is_low:
                lows.append(bar)
            if len(highs) >= MAX_PIVOTS and len(lows) >= MAX_PIVOTS:
                break
        self.pivot_highs = highs[:MAX_PIVOTS]
        self.pivot_lows = lows[:MAX_PIVOTS]

    def _aligned(self, candle: Candle, tolerance: float) -> float | None:
        """The candle's open or close that sits on a tracked pivot, or None."""
        for price in (candle.open, candle.close):
            for pivot in self.pivot_highs + self.pivot_lows:
                if abs(pivot.high - price) <= tolerance or abs(pivot.low - price) <= tolerance:
                    return price
        return None

    def _eval_exhaustion(self, tolerance: float) -> Signal | None:
        """Attention above its percentile, plus a 10-bar impulse on a pivot."""
        if not self._attention_strong():
            self._count("exhaustion:attention")
            return None
        closes = [self.window4h[i].close for i in range(IMPULSE_LOOKBACK)]
        high_at = closes.index(max(closes))
        low_at = closes.index(min(closes))
        if low_at < high_at:
            direction, offset = 1, low_at
        elif high_at < low_at:
            direction, offset = -1, high_at
        else:
            self._count("exhaustion:flat")
            return None
        origin = self.window4h[offset]
        level = self._aligned(origin, tolerance)
        if level is None:
            self._count("exhaustion:unaligned")
            return None
        pad = 0.5 * self.atr15.value
        stop = origin.low - pad if direction > 0 else origin.high + pad
        return Signal("exhaustion", direction, level, stop, self.window4h[0].ts)

    def _eval_choppy(self, tolerance: float) -> Signal | None:
        """A strong 4H candle closing out of a 2-4 candle low-body cluster."""
        breakout = self.window4h[0]
        if breakout.span <= 0:
            self._count("choppy:flat")
            return None
        if breakout.body < BREAKOUT_BODY_RATIO * breakout.span:
            self._count("choppy:weak-break")
            return None
        for size in range(CLUSTER_MIN, CLUSTER_MAX + 1):
            cluster = [self.window4h[i] for i in range(1, size + 1)]
            if not all(
                row.span > 0 and row.body < BODY_RANGE_RATIO_MAX * row.span for row in cluster
            ):
                continue
            top = max(row.high for row in cluster)
            bottom = min(row.low for row in cluster)
            if breakout.close > top:
                direction = 1
            elif breakout.close < bottom:
                direction = -1
            else:
                continue
            level = self._aligned(breakout, tolerance)
            if level is None:
                self._count("choppy:unaligned")
                continue
            pad = 0.5 * self.atr15.value
            stop = bottom - pad if direction > 0 else top + pad
            return Signal("choppy", direction, level, stop, breakout.ts)
        self._count("choppy:no-cluster")
        return None

    # -------------------------------------------------------- retest and entry

    def _try_enter(self, candle: Candle) -> None:
        found = self.pending
        if found is None:
            return
        self._count("entry:looked")
        if found.expired(candle.ts):
            self.pending = None
            self._count("entry:expired")
            return
        if self.cache.positions_open(instrument_id=self.config.instrument_id):
            return
        # **The bar's own extremes, not a bid and an ask.** The store keeps one
        # modelled quote per bar, so there are no intrabar quote extremes to
        # read; the spread is paid on the fill instead of on the trigger, which
        # makes the trigger about half a spread easier than the original's.
        retested = candle.low <= found.level if found.direction > 0 else candle.high >= found.level
        if not retested:
            return

        self.pending = None
        price = candle.close
        risk = abs(price - found.stop)
        if risk <= 0:
            self._count("entry:no-risk")
            return
        # **The stop has to be on the protecting side of the fill.** A retest
        # that overshoots its level can close beyond the stop the signal named,
        # and the venue then rejects the protective order outright - which
        # leaves the trade running naked and its R incomparable. It showed up
        # in the flip arm first, where mirroring the stop through the level
        # makes the overshoot more likely, but the guard is not a flip fix and
        # is applied to both arms so the two stay matched.
        if (found.direction > 0 and found.stop >= price) or (
            found.direction < 0 and found.stop <= price
        ):
            self._count("entry:stop-wrong-side")
            return
        if self.atr15.ready and risk < self.config.min_risk_atr * self.atr15.value:
            # Inside the noise: sizing explodes to the leverage cap and the stop
            # is taken out by spread jitter.
            self._count("entry:risk-under-atr")
            return

        quantity = self._size(price, risk)
        if quantity <= 0:
            self._count("entry:unaffordable")
            return
        side = OrderSide.BUY if found.direction > 0 else OrderSide.SELL
        self._trade = {
            "branch": found.branch,
            "direction": found.direction,
            "stop": found.stop,
            "initial_stop": found.stop,
            "risk": risk,
            "partial": False,
            "entry_ts": candle.ts,
            "entry": price,
            "ordered": float(quantity),
            "filled": 0.0,
        }
        self.submit_order(
            self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=side,
                quantity=quantity,
            )
        )

    def _size(self, price: float, risk: float) -> Any:
        """Risk a fraction of equity, capped by position and gross leverage."""
        account = self.portfolio.account(self.config.instrument_id.venue)
        equity = float(account.balance_total(USD).as_double()) if account else EQUITY
        wanted = equity * self.config.risk_per_trade / risk
        gross = 0.0
        for position in self.cache.positions_open():
            gross += abs(float(position.quantity)) * float(position.avg_px_open)
        room = max(equity * MAX_GROSS_LEVERAGE - gross, 0.0)
        ceiling = min(equity * MAX_LEVERAGE, room) / price
        return self._instrument.make_qty(max(min(wanted, ceiling), 0.0))

    # ------------------------------------------------------------- management

    def _manage(self, candle: Candle) -> None:
        state = self._trade
        held = self.cache.positions_open(instrument_id=self.config.instrument_id)
        if state is None or not held:
            return
        position = held[0]
        is_long = position.side == PositionSide.LONG
        moved = (
            candle.close - state["entry"] if is_long else state["entry"] - candle.close
        )

        if candle.ts - state["entry_ts"] >= TIME_STOP_NS:
            self._flatten(position, "time-stop")
            return

        atr = self.atr15.value if self.atr15.ready else 0.0
        if moved >= BE_TRIGGER_R * state["risk"] and atr > 0:
            target = (
                state["entry"] - BE_OFFSET_ATR * atr
                if is_long
                else state["entry"] + BE_OFFSET_ATR * atr
            )
            self._move_stop(target, is_long)

        if not state["partial"] and moved >= TP_TRIGGER_R * state["risk"]:
            half = self._instrument.make_qty(float(position.quantity) * TP_FRACTION)
            if float(half) > 0:
                state["partial"] = True
                self.submit_order(
                    self.order_factory.market(
                        instrument_id=self.config.instrument_id,
                        order_side=OrderSide.SELL if is_long else OrderSide.BUY,
                        quantity=half,
                        reduce_only=True,
                    )
                )

        if state["partial"] and atr > 0:
            trail = (
                candle.close - self.config.tsl_atr_mult * atr
                if is_long
                else candle.close + self.config.tsl_atr_mult * atr
            )
            self._move_stop(trail, is_long)

    def _move_stop(self, target: float, is_long: bool) -> None:
        """Only toward profit, and only on a working order."""
        state = self._trade
        if state is None:
            return
        better = target > state["stop"] if is_long else target < state["stop"]
        if not better:
            return
        order = self._stop_order
        if order is None or not order.is_open:
            return
        state["stop"] = target
        self.modify_order(order, trigger_price=self._instrument.make_price(target))

    def _flatten(self, position: Any, why: str) -> None:
        state = self._trade
        if state is None:
            return
        state["ending"] = why
        if self._stop_order is not None and self._stop_order.is_open:
            self.cancel_order(self._stop_order)
        self.close_position(position)

    # ----------------------------------------------------------------- events

    def on_position_opened(self, event: Any) -> None:
        """Attach the protective stop, **here and not on the fill**.

        `on_order_filled` runs before the position reaches the cache, so an
        earlier version read an empty `positions_open`, returned, and never
        submitted a stop at all. The trades then ended on the 48-hour time stop
        at **-3.4R**, a loss no 1R stop can produce, and that number is the only
        reason it was caught. Production attaches protection in this same place
        for this same reason - see `strategies/exits.on_position_opened`.
        """
        self._adopt(event)

    def on_position_changed(self, event: Any) -> None:
        """**An entry fills in slices, and the first slice is not the trade.**

        The simulated book is built from bars, so a 437,900-unit EURUSD market
        order opens the position with about **1,100 units** and grows it over
        the following fills. Reading the size at `on_position_opened` therefore
        sized the protective stop at a quarter of one percent of the position -
        the stop was real, working, and covered nothing - and recorded an R
        denominator 400x too small, which printed as **-1350R a trade**. The
        P&L was right the whole time; only the two numbers beside it were not.

        Every later order is reduce-only, so a position that *grows* is still
        filling and nothing else. That is the condition this refreshes on.
        """
        self._adopt(event)

    def _adopt(self, event: Any) -> None:
        """Take the entry price, risk and size off the position itself."""
        state = self._trade
        if state is None:
            return
        position = self.cache.position(event.position_id)
        if position is None:
            self._count("entry:no-position-to-protect")
            return
        size = abs(float(position.quantity))
        if size > state["filled"]:
            state["filled"] = size
            state["entry"] = float(position.avg_px_open)
            state["risk"] = abs(state["entry"] - state["initial_stop"])
        if self._stop_order is not None or state["risk"] <= 0:
            return
        self._stop_order = self.order_factory.stop_market(
            instrument_id=self.config.instrument_id,
            order_side=(OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY),
            # **The size that was ordered, not the size filled so far.** A stop
            # for the first slice is the bug above. `reduce_only` clamps it to
            # whatever is actually open, so ordering the full intent is safe in
            # the direction that matters and wrong in neither.
            quantity=self._instrument.make_qty(state["ordered"]),
            trigger_price=self._instrument.make_price(state["initial_stop"]),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self.submit_order(self._stop_order)

    def on_position_closed(self, event: Any) -> None:
        state = self._trade
        self._trade = None
        if self._stop_order is not None and self._stop_order.is_open:
            self.cancel_order(self._stop_order)
        naked = self._stop_order is None
        self._stop_order = None
        if state is None:
            return
        state["unprotected"] = naked
        position = self.cache.position(event.position_id)
        if position is None:
            return
        ending = state.get("ending") or ("stop" if not state["partial"] else "trail")
        if state.get("unprotected"):
            ending = f"{ending}!naked"
        self.closed.append(
            Trade(
                feed=self.feed,
                branch=state["branch"],
                direction=state["direction"],
                entry=state["entry"],
                exit=float(position.avg_px_close or 0.0),
                quantity=state["filled"],
                risk_price=state["risk"],
                profit=float(position.realized_pnl.as_double() if position.realized_pnl else 0.0),
                ending=ending,
                seconds=float(position.duration_ns or 0) / 1e9,
                day=int(state["entry_ts"] // (86_400 * 1_000_000_000)),
            )
        )


# --- running it --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Arm:
    """One configuration of the rule, run on every feed."""

    name: str
    exhaustion: bool = True
    choppy: bool = True
    flip: bool = False


ARMS: tuple[Arm, ...] = (
    Arm("both"),
    Arm("exhaustion-only", choppy=False),
    Arm("choppy-only", exhaustion=False),
    Arm("both:flip", flip=True),
    Arm("exhaustion-only:flip", choppy=False, flip=True),
    Arm("choppy-only:flip", exhaustion=False, flip=True),
)

#: The two the rule was written for - XAUUSD is `GOLD` in this store. The other
#: four in the catalogue are run too and reported apart, because widening the
#: universe is what has done the killing here before.
#:
#: **Spelled as the catalogue spells them.** `CurrencyPair` symbols carry the
#: slash, so a membership test against `EURUSD` silently put the rule's own
#: headline feed in the control group and reported GOLD alone as both.
SPECIFIED = ("EUR/USD", "GOLD")


def load(where: str) -> list[tuple[Any, list[Any]]]:
    """Every instrument in the catalogue, with its bars and quotes interleaved."""
    book = ParquetDataCatalog(where)
    out = []
    for instrument in book.instruments():
        iid = str(instrument.id)
        bars = book.bars(bar_types=[f"{iid}-15-MINUTE-LAST-EXTERNAL"])
        quotes = book.quote_ticks(instrument_ids=[iid])
        if not bars:
            print(f"  {iid}: no 15m bars - skipped")
            continue
        out.append((instrument, sorted([*bars, *quotes], key=lambda d: d.ts_init)))
    return sorted(out, key=lambda row: str(row[0].id))


def run_one(
    instrument: Any, data: list[Any], arm: Arm, tolerance: float = PIVOT_TOLERANCE_ATR
) -> DualEngine:
    """One instrument, one arm."""
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="BACKTEST-001",
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    engine.add_venue(
        venue=instrument.id.venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(EQUITY, USD)],
        default_leverage=Decimal(str(LEVERAGE)),
    )
    engine.add_instrument(instrument)
    engine.add_data(data)
    strategy = DualEngine(
        DualEngineConfig(
            instrument_id=instrument.id,
            bar_type=BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL"),
            feed=str(instrument.id.symbol),
            exhaustion=arm.exhaustion,
            choppy=arm.choppy,
            flip=arm.flip,
            tolerance_mult=tolerance,
            order_id_tag="0001",
        )
    )
    engine.add_strategy(strategy)
    engine.run()
    # **Read before disposing.** `dispose_on_completion` zeroes the engine's own
    # counters while the P&L survives, so a count of 0 beside a non-zero P&L is
    # a reporting bug rather than a result - measured on this desk already.
    out = strategy
    engine.dispose()
    return out


def block_bootstrap(trades: list[Trade], draws: int = 2000) -> tuple[float, float]:
    """A day-block interval on the mean R.

    Blocked by entry day because two trades opened the same day on the same
    feed share a regime, and an i.i.d. resample of them reports an interval
    narrower than the sample supports.
    """
    if len(trades) < 2:
        return (float("nan"), float("nan"))
    days: dict[int, list[float]] = {}
    for trade in trades:
        days.setdefault(trade.day, []).append(trade.reward)
    blocks = list(days.values())
    rng = random.Random(20261112)
    means = []
    for _ in range(draws):
        drawn: list[float] = []
        for _ in range(len(blocks)):
            drawn.extend(rng.choice(blocks))
        if drawn:
            means.append(sum(drawn) / len(drawn))
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means))])


def summarise(label: str, trades: list[Trade]) -> str:
    if not trades:
        return f"  {label:<26} no trades"
    rewards = [t.reward for t in trades]
    n = len(rewards)
    mean = sum(rewards) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rewards) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    wins = sum(1 for r in rewards if r > 0)
    lo, hi = block_bootstrap(trades)
    endings: dict[str, int] = {}
    for trade in trades:
        endings[trade.ending] = endings.get(trade.ending, 0) + 1
    mix = " ".join(f"{k}:{v}" for k, v in sorted(endings.items()))
    return (
        f"  {label:<26} n {n:>3}  R/trade {mean:>+7.3f} +/-{se:>5.3f}  "
        f"day-block [{lo:>+6.3f},{hi:>+6.3f}]  win {wins / n:>4.0%}  {mix}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(catalogue()))
    parser.add_argument("--arm", default="", help="run one arm by name")
    parser.add_argument(
        "--why", action="store_true", help="per-feed gate counts, not pooled across feeds"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=PIVOT_TOLERANCE_ATR,
        help="pivot alignment tolerance as a multiple of ATR(4H); the original's grid is 0.015, 0.05, 0.10",
    )
    args = parser.parse_args()

    loaded = load(args.catalogue)
    if not loaded:
        raise SystemExit(f"no instruments in {args.catalogue}")
    print(f"catalogue: {args.catalogue}   tolerance {args.tolerance} x ATR(4H)")
    for instrument, rows in loaded:
        bars = sum(1 for r in rows if isinstance(r, Bar))
        print(f"  {instrument.id}: {bars} bars, {len(rows) - bars} quotes")
    print()

    arms = [a for a in ARMS if not args.arm or a.name == args.arm]
    for arm in arms:
        print(f"== {arm.name}")
        named: list[Trade] = []
        other: list[Trade] = []
        declined: dict[str, int] = {}
        signals: dict[str, int] = {}
        for instrument, rows in loaded:
            strategy = run_one(instrument, rows, arm, args.tolerance)
            symbol = str(instrument.id.symbol)
            (named if symbol in SPECIFIED else other).extend(strategy.closed)
            print(summarise(symbol, strategy.closed))
            if args.why:
                gates = ", ".join(f"{k} {v}" for k, v in sorted(strategy.declined.items()))
                fired = ", ".join(f"{k} {v}" for k, v in sorted(strategy.signals.items()))
                print(f"       4H bars {strategy.bars4h}  signals [{fired or 'none'}]")
                print(f"       declined {gates}")
            for key, count in strategy.declined.items():
                declined[key] = declined.get(key, 0) + count
            for key, count in strategy.signals.items():
                signals[key] = signals.get(key, 0) + count
        print(summarise("EURUSD+GOLD (specified)", named))
        print(summarise("the other four", other))
        print(f"  signals {dict(sorted(signals.items()))}")
        print(f"  declined {dict(sorted(declined.items()))}")
        print()


if __name__ == "__main__":
    main()
