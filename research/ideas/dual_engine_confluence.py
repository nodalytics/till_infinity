"""The dual-engine rule on several structure timeframes at once, agreeing k of n.

The rule as written watches **one** structure timeframe. This runs it on two or
three at the same time - 1D, 4H and 1H on an hourly feed - and takes a trade
when **at least `k`** of them want the same direction, rather than requiring all
of them to agree or trusting any one alone.

`k = 1` is the union: any frame's signal is a trade, which is the frequency
lever. `k = 2` of 3 is partial confluence. `k = 3` is full agreement, which is
the strictest the rule can be. All three are run, because which way the count
cuts is the question and not an assumption.

## Why this is a different experiment and not another parameter sweep

`dual_engine_timeframes.py` measured each structure **alone** and found the sign
tracks the sample rather than the timeframe: every cell with n >= 35 was
negative, and at the two finest structures the rule was beaten by its own
reverse. What it did not test is whether the frames carry *different*
information - whether a 1H signal that a 4H frame also wants is a better trade
than a 1H signal on its own.

That is a real question with a real mechanism behind it, and it is the first
change proposed here that could move the answer rather than reselect it. It
also has a measurable prediction attached, below, written before the run.

## What each frame costs, and why the stop comes from the coarsest

Cost in R is set by the frame that draws the stop, measured on this store:

| structure | EURUSD | GBPUSD | USDJPY | AUDUSD | GOLD |
|---|---|---|---|---|---|
| 1D | 1.8% | 1.4% | 1.4% | 2.0% | 0.3% |
| 4H | 7.0% | 5.1% | - | - | 0.5% |
| 1H | 12.5% | 9.0% | 11.4% | 13.1% | 1.0% |

So when several frames agree, **the stop is taken from the coarsest agreeing
frame**. That is not a tidy-up: it is a seven-fold difference in the round trip
between a 1D stop and a 1H one on EURUSD, and taking the finest frame's stop
would hand most of the confluence back in costs. The entry level still comes
from the frame that fired most recently, because that is the retest actually
being waited for.

## The prediction, written before the run

If the frames carry independent information, `k = 2` should beat `k = 1` on R
per trade by more than the cost difference alone, and the rule-minus-flip gap
should **widen** with `k`. If the frames are three views of one thing - which
is what a shared attention z-score and a shared pivot construction suggest -
then raising `k` will cut the trade count roughly as the frames' overlap
predicts and leave R where it was, and the gap against the flip will not move.

**The honest prior is the second.** All three frames read the same price series
through the same detector, the attention score already mixes two timeframes
inside itself, and `smc-primitives-overlap-and-are-closed` records two
detectors that looked independent and agreed on a quarter of their union. A
confluence rule over correlated detectors buys variance reduction, not
expectancy - `the-book-is-composable-judge-rules-marginally` says exactly this.

What would change that reading is `k = 2` showing a **larger** rule-minus-flip
gap than `k = 1`, not merely a better R: a better R at a lower trade count is
what selection looks like.

Run it as `uv run python research/ideas/dual_engine_confluence.py`.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
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
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Money

from dual_engine_grid import MAX_DRAWDOWN, MIN_SHARPE, MIN_TRADES, load_all, measure, span_days
from dual_engine_port import (
    ATR_PERIOD,
    ATTENTION_PERIOD_4H,
    ATTENTION_WINDOW,
    BODY_RANGE_RATIO_MAX,
    BREAKOUT_BODY_RATIO,
    CLUSTER_MAX,
    CLUSTER_MIN,
    EQUITY,
    IMPULSE_LOOKBACK,
    LEVERAGE,
    MAX_PIVOTS,
    MIN_ATTENTION_SAMPLES,
    PIVOT_TOLERANCE_ATR,
    STRONG_PERCENTILE,
    SWING_LOOKBACK,
    WINDOW_4H,
    Candle,
    DualEngine,
    Rolling,
    Signal,
    Wilder,
    Window,
)

HOURLY = Path.home() / "till-data" / "grid5h"
HOUR_SPEC = "1-HOUR-LAST-EXTERNAL"

#: Execution bars per structure bar, on an **hourly** feed: 1H, 4H, 1D.
#: Coarsest last, because `_coarsest` relies on the ordering and a set that
#: was not sorted would hand the stop to the wrong frame silently.
FRAMES: tuple[int, ...] = (1, 4, 24)

#: How long a frame's signal stays live for another frame to agree with it.
#: One day in nanoseconds: shorter than the 48-hour pending expiry the rule
#: already uses, so agreement is a statement about the same move rather than
#: about two unrelated ones in the same week.
AGREE_WINDOW_NS = 24 * 3600 * 1_000_000_000


@dataclass
class Frame:
    """One structure timeframe's own state, lifted out of `DualEngine`.

    Everything here was a field on the strategy when there was one structure
    timeframe. It is a class now because three frames need three of each, and
    sharing a pivot list or an attention window between them would make
    "the frames agree" true by construction.
    """

    span: int
    window: Window = field(default_factory=lambda: Window(WINDOW_4H))
    atr: Wilder = field(default_factory=lambda: Wilder(ATR_PERIOD))
    trs: Rolling = field(default_factory=lambda: Rolling(ATTENTION_PERIOD_4H))
    attention: Window = field(default_factory=lambda: Window(ATTENTION_WINDOW))
    seen: int = 0
    forming: list[Bar] = field(default_factory=list)
    previous: float | None = None
    z: float | None = None
    highs: list[Candle] = field(default_factory=list)
    lows: list[Candle] = field(default_factory=list)
    #: The last signal this frame produced, and when, for the agreement count.
    signal: Signal | None = None
    fired: int = 0

    @property
    def ready(self) -> bool:
        return self.window.ready and self.atr.ready


class ConfluenceConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    feed: str = ""
    risk_per_trade: float = 0.01
    tolerance_mult: float = PIVOT_TOLERANCE_ATR
    z_pct: float = STRONG_PERCENTILE / 100.0
    tsl_atr_mult: float = 2.0
    min_risk_atr: float = 0.5
    tp_trigger_r: float = 2.0
    exhaustion: bool = True
    choppy: bool = True
    flip: bool = False
    #: Execution bars per structure bar, coarsest last.
    frames: tuple[int, ...] = FRAMES
    #: How many frames must want the same direction before a trade is taken.
    agree_at_least: int = 1


class Confluence(DualEngine):
    """The rule over several structure frames, trading on k-of-n agreement.

    Inherits the entry, sizing, protection and management from `DualEngine`
    unchanged - every port defect fixed there is fixed here, and the two
    cannot drift - and replaces only the part that decides a signal.
    """

    def __init__(self, config: ConfluenceConfig) -> None:
        super().__init__(config)  # type: ignore[arg-type]
        self.frames = [Frame(span=span) for span in sorted(config.frames)]
        #: How often each agreement count was reached, so a `k` that never
        #: fires is visible as that rather than as a rule with no edge.
        self.agreed: dict[int, int] = {}

    # The structure half is replaced wholesale; `DualEngine.on_bar` calls
    # `_close_4h`, so the override is the single seam.

    def _close_4h(self) -> None:  # noqa: N802 - the base class names the seam
        """Nothing: `on_bar` drives the frames through `_fold` instead."""

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

        for frame in self.frames:
            frame.forming.append(bar)
            if len(frame.forming) >= frame.span:
                self._fold(frame, candle.ts)
        self._decide(candle.ts)

        held = self.cache.positions_open(instrument_id=self.config.instrument_id)
        if self._trade is not None and not held:
            self._trade = None
            self._stop_order = None
        if self._trade is not None:
            self._manage(candle)
        elif self.pending is not None:
            self._try_enter(candle)

    def _fold(self, frame: Frame, now: int) -> None:
        """Close one structure bar on one frame and ask it for a signal."""
        rows, frame.forming = frame.forming, []
        candle = Candle(
            open=float(rows[0].open),
            high=max(float(r.high) for r in rows),
            low=min(float(r.low) for r in rows),
            close=float(rows[-1].close),
            ts=rows[-1].ts_event,
        )
        tr = self._true_range(candle, frame.previous)
        frame.previous = candle.close
        frame.atr.update(tr)
        frame.trs.update(tr)
        frame.z = frame.trs.z(tr)

        if frame.z is not None:
            z_exec = self.tr15.z(self.atr15.value) if self.tr15.ready else None
            if z_exec is not None:
                frame.attention.add(0.5 * z_exec + 0.5 * frame.z)
                frame.seen += 1

        frame.window.add(candle)
        if not frame.ready:
            return
        self._pivots(frame)
        if self._trade is not None:
            return
        tolerance = self.config.tolerance_mult * frame.atr.value
        found = self._exhaustion(frame, tolerance) or self._choppy(frame, tolerance)
        if found is not None:
            frame.signal = found
            frame.fired += 1

    def _decide(self, now: int) -> None:
        """Take a trade when `agree_at_least` frames want the same direction.

        **The stop comes from the coarsest agreeing frame**, which is a
        seven-fold difference in the round trip on EURUSD between a 1D stop and
        a 1H one. The level comes from the frame that fired most recently,
        because that is the retest actually being waited for.
        """
        if self._trade is not None or self.pending is not None:
            return
        live = [
            frame
            for frame in self.frames
            if frame.signal is not None and now - frame.signal.created <= AGREE_WINDOW_NS
        ]
        for direction in (1, -1):
            agreeing = [f for f in live if f.signal is not None and f.signal.direction == direction]
            if len(agreeing) < self.config.agree_at_least:
                continue
            self.agreed[len(agreeing)] = self.agreed.get(len(agreeing), 0) + 1
            coarsest = max(agreeing, key=lambda f: f.span)
            newest = max(agreeing, key=lambda f: f.signal.created)  # type: ignore[union-attr]
            found = Signal(
                branch=f"{newest.signal.branch}@{len(agreeing)}of{len(self.frames)}",  # type: ignore[union-attr]
                direction=direction,
                level=newest.signal.level,  # type: ignore[union-attr]
                stop=coarsest.signal.stop,  # type: ignore[union-attr]
                created=newest.signal.created,  # type: ignore[union-attr]
            )
            if self.config.flip:
                found = self._reverse(found)
            self.signals[found.branch] = self.signals.get(found.branch, 0) + 1
            self.pending = found
            for frame in agreeing:
                frame.signal = None
            return

    # ---- the per-frame detectors, identical to the base class but frame-local

    def _pivots(self, frame: Frame) -> None:
        highs: list[Candle] = []
        lows: list[Candle] = []
        for k in range(SWING_LOOKBACK, WINDOW_4H - SWING_LOOKBACK):
            bar = frame.window[k]
            is_high = True
            is_low = True
            for j in range(k - SWING_LOOKBACK, k + SWING_LOOKBACK + 1):
                if j == k:
                    continue
                other = frame.window[j]
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
        frame.highs = highs[:MAX_PIVOTS]
        frame.lows = lows[:MAX_PIVOTS]

    def _strong(self, frame: Frame) -> bool:
        if frame.seen < MIN_ATTENTION_SAMPLES:
            return False
        values = sorted(frame.attention[i] for i in range(len(frame.attention)))
        if not values:
            return False
        position = self.config.z_pct * (len(values) - 1)
        lower = int(math.floor(position))
        upper = min(lower + 1, len(values) - 1)
        threshold = values[lower] + (values[upper] - values[lower]) * (position - lower)
        return frame.attention[0] > threshold

    def _lines_up(self, frame: Frame, candle: Candle, tolerance: float) -> float | None:
        for price in (candle.open, candle.close):
            for pivot in frame.highs + frame.lows:
                if abs(pivot.high - price) <= tolerance or abs(pivot.low - price) <= tolerance:
                    return price
        return None

    def _exhaustion(self, frame: Frame, tolerance: float) -> Signal | None:
        if not self.config.exhaustion or not self._strong(frame):
            return None
        closes = [frame.window[i].close for i in range(IMPULSE_LOOKBACK)]
        high_at = closes.index(max(closes))
        low_at = closes.index(min(closes))
        if low_at < high_at:
            direction, offset = 1, low_at
        elif high_at < low_at:
            direction, offset = -1, high_at
        else:
            return None
        origin = frame.window[offset]
        level = self._lines_up(frame, origin, tolerance)
        if level is None:
            self._count(f"f{frame.span}:exhaustion-unaligned")
            return None
        pad = 0.5 * self.atr15.value
        stop = origin.low - pad if direction > 0 else origin.high + pad
        return Signal("exhaustion", direction, level, stop, frame.window[0].ts)

    def _choppy(self, frame: Frame, tolerance: float) -> Signal | None:
        if not self.config.choppy:
            return None
        breakout = frame.window[0]
        if breakout.span <= 0 or breakout.body < BREAKOUT_BODY_RATIO * breakout.span:
            return None
        for size in range(CLUSTER_MIN, CLUSTER_MAX + 1):
            cluster = [frame.window[i] for i in range(1, size + 1)]
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
            level = self._lines_up(frame, breakout, tolerance)
            if level is None:
                self._count(f"f{frame.span}:choppy-unaligned")
                continue
            pad = 0.5 * self.atr15.value
            stop = bottom - pad if direction > 0 else top + pad
            return Signal("choppy", direction, level, stop, breakout.ts)
        return None


@dataclass(frozen=True, slots=True)
class Arm:
    frames: tuple[int, ...]
    agree: int
    flip: bool

    @property
    def name(self) -> str:
        names = {1: "1H", 4: "4H", 8: "8H", 24: "1D"}
        shown = "+".join(names.get(s, f"{s}b") for s in sorted(self.frames))
        return f"{shown} k={self.agree}"


def run_arm(instruments: list[Any], data: list[Any], arm: Arm) -> list[Any]:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="CONF-001",
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
        strategy = Confluence(
            ConfluenceConfig(
                instrument_id=instrument.id,
                bar_type=BarType.from_str(f"{instrument.id}-{HOUR_SPEC}"),
                feed=str(instrument.id.symbol),
                frames=arm.frames,
                agree_at_least=arm.agree,
                flip=arm.flip,
                order_id_tag=f"{n:04d}",
            )
        )
        engine.add_strategy(strategy)
        built.append(strategy)
    engine.add_data(data)
    engine.run()
    closed = [t for s in built for t in s.closed]
    fired = [sum(f.fired for f in s.frames) for s in built]
    agreed: dict[int, int] = {}
    for s in built:
        for k, v in s.agreed.items():
            agreed[k] = agreed.get(k, 0) + v
    engine.dispose()
    return closed, sum(fired), agreed


#: Two and three frames, every agreement count each can carry.
ARMS: tuple[Arm, ...] = (
    Arm((1, 4, 24), 1, False),
    Arm((1, 4, 24), 2, False),
    Arm((1, 4, 24), 3, False),
    Arm((4, 24), 1, False),
    Arm((4, 24), 2, False),
    Arm((1, 4), 2, False),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(HOURLY))
    args = parser.parse_args()

    instruments, data = load_all(Path(args.catalogue), HOUR_SPEC)
    if not instruments:
        raise SystemExit(f"nothing in {args.catalogue}")
    days = span_days(data)
    print(f"catalogue: {args.catalogue}  {len(instruments)} instruments, {days:.0f} days")
    print(
        f"constraints: sharpe > {MIN_SHARPE}, maxdd < {MAX_DRAWDOWN:.0%}, "
        f"trades >= {MIN_TRADES}\n"
    )

    rows = []
    for arm in ARMS:
        found = {}
        for flip in (False, True):
            one = Arm(arm.frames, arm.agree, flip)
            closed, fired, agreed = run_arm(instruments, data, one)
            found[flip] = (measure(_cell(one), closed, days), fired, agreed)
        rule, fired, agreed = found[False]
        null = found[True][0]
        gap = rule.reward - null.reward if rule.trades and null.trades else float("nan")
        rows.append((arm, rule, null, gap))
        counts = " ".join(f"{k}:{v}" for k, v in sorted(agreed.items()))
        flag = "PASS" if rule.passes else "    "
        print(
            f"  {flag} {arm.name:<16} rule n {rule.trades:>3} R {rule.reward:>+6.3f} "
            f"+/-{rule.reward_se:>5.3f} sharpe {rule.sharpe:>+6.2f} dd {rule.drawdown:>5.1%}  |  "
            f"flip n {null.trades:>3} R {null.reward:>+6.3f}  |  gap {gap:>+6.3f}"
        )
        print(f"       frame signals {fired}, agreement counts [{counts}]")

    print("\n== does agreement buy anything")
    for frames in ((1, 4, 24), (4, 24)):
        group = [(a, r, n, g) for a, r, n, g in rows if a.frames == frames]
        if len(group) < 2:
            continue
        label = group[0][0].name.split(" k=")[0]
        for arm, rule, _null, gap in sorted(group, key=lambda row: row[0].agree):
            print(f"  {label:<10} k={arm.agree}  n {rule.trades:>3}  R {rule.reward:>+6.3f}  gap {gap:>+6.3f}")


def _cell(arm: Arm) -> Any:
    from dual_engine_grid import Cell

    return Cell(
        tolerance=PIVOT_TOLERANCE_ATR,
        percentile=STRONG_PERCENTILE / 100.0,
        risk=0.01,
        flip=arm.flip,
        bars_per_structure=max(arm.frames),
        tp_trigger_r=2.0,
        bar_spec=HOUR_SPEC,
    )


if __name__ == "__main__":
    main()
