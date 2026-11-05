"""Nautilus's own indicators, their parameters and the desk's money management.

The grid is frozen in `nautilus_grid_rule.json` and that file is committed
before this one runs. Read it rather than this docstring for what was
pre-registered; what follows is why the harness is shaped the way it is.

## What is new here, and what is a re-measurement

**Closed, and not re-opened:** textbook indicators at default parameters as
standalone entries ([battery.md](../docs/battery.md), 15 of 323 cells, FX and
metals zero); lagging indicators timing an entry at a structure zone
([indicators.md](../docs/indicators.md), 0 of ~170); indicators as confirmation
gates on level signals ([confirm.md](../docs/confirm.md), 17 of 8,366);
published multi-indicator EAs with their own geometry
([geraked-eas.md](../docs/geraked-eas.md), 12 of 13 lose 0.02-0.09R); a wider
stop at constant money risk ([widestop.md](../docs/widestop.md), mean R scales
as exactly 1/m); a stop anchored to a level
([stop-anchor.md](../docs/stop-anchor.md), 0 of 14); grid, martingale, trail,
equity-limit and lot-mode overlays ([geraked-eas.md](../docs/geraked-eas.md)
Mode R: every factor's shift in mean R matches the walks' to within 0.007R).

**The entry axis of this grid is therefore a re-measurement, and is declared as
one.** It is the carrier, not the question. What it adds over battery.md is
that the parameters are *swept* - battery ran every rule at its default and its
own fresh-instrument re-run is the only parameter-changing observation it has -
and that it runs through `BacktestNode` and the production catalogue, which no
indicator study here has ever done.

**The question is the money-management axis**, which is open for a specific
reason. `sizing-multipliers.md` measured the eight sizing levers and found that
**not one of them could change a position size**: `Profile.multipliers` had no
caller, `Intent.volume` was set by no producer, and all 25 intents died at
`(desk):zero-volume`, leaving the four engine arms bit-identical at 10,000.00.
`strategies/sizes.py` has since wired that path. So this is the first run in
which the desk's sizing arithmetic reaches an order, and `Strategy
.reward_floor` - flagged by `hold-clock.md` as the lever and measured by no doc
- gets its first measurement.

## The prediction, written before the run

`deriving.md` is a theorem: a predictable position on a martingale has zero
gross expectancy, so `E[net] = -(c/2) * turnover` for every stop, target,
trail, breakeven, scale-out and sizing scheme. Mode R measured exactly that on
thirteen EAs. **The pre-registered expectation is therefore a null on every
money-management arm**, and the result that would be worth something is a clean
one with its power shown.

## Four counters per cell, because a zero is a reading of something

`bars`, `signals`, `gated`, `sized`, `orders`, `trades`. A cell that reports no
trades has to say at which stage the number died: `leaf_sweep.py` reported
`+0.00 over 0 positions` for nine of twelve leaves and that was three separate
defects, none of which raised. And `total_orders` off a `BacktestResult` is
**not** one of these - `BacktestNode._run` disposes the engine before
`get_result()` reads `cache.orders_total_count()`, so it counts an emptied
cache. `node/backtest.run_config` sets `dispose_on_completion=False`; these
counters are the strategy's own either way.

## R, and where the cost is

`R = (exit_fill - entry_fill) * sign / |entry_ref - stop|`, from the engine's
own fills, so the spread is paid twice and shows up in the numerator. The
denominator is the **stop**, never the target - moving a target out does not
dilute a spread by a basis point.
"""

from __future__ import annotations

import json
import os
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from till_infinity.domain.models import Side
from till_infinity.indicators import framework
from till_infinity.risk import sizing as risk_sizing
from till_infinity.strategies import sizes
from till_infinity.strategies.profile import Profile

#: Bars a position may be held before it is closed at the market. Fixed, not
#: swept: `stop-anchor.md` records that with a risk-scaled target the stop
#: width cancels out of R exactly and a stop-width question needs a time exit,
#: and an uncapped hold on eleven years of 15-minute bars leaves positions open
#: for months. 200 is battery.md's, so the two are comparable.
HOLD_BARS = 200

#: Bars of ATR history the volatility regime reads. 96 is one day of 15-minute
#: bars, so "quiet for this instrument" means quiet against yesterday.
REGIME_BARS = 96


class GridConfig(StrategyConfig, frozen=True):
    """One cell: a rule at a parameter, under one money-management variant."""

    instrument_id: InstrumentId
    bar_type: BarType
    rule: str
    param: int
    mm: str
    risk_fraction: float = 0.0025
    stop_atr: float = 2.0
    target_r: float = 2.0
    reward_floor: float = 0.0
    #: Share of signals the `twin` variant keeps, measured from the `gate` cell
    #: it twins. Ignored by every other variant.
    keep: float = 1.0
    seed: int = 0
    out: str = ""


class _Floored(Profile):
    """A `Profile` carrying only the floor, so `floored_target` is the desk's.

    The arithmetic is three lines and copying it would be the mistake this desk
    has paid for more than any other - the thing that measures and the thing
    that trades drifting apart. `reward_floor` is a `ClassVar`, so one subclass
    per value is how it is set.
    """

    reward_floor: float = 0.0

    def __init__(self, floor: float) -> None:
        self.reward_floor = floor


@dataclass
class Trade:
    """One closed position, in the units the write-up reports."""

    ts_open: int
    ts_close: int
    side: int
    entry_ref: float
    entry_fill: float
    exit_fill: float
    stop: float
    target: float
    qty: float
    risk_money: float
    pnl: float
    r: float
    bars: int
    reason: str


@dataclass
class Counters:
    """Where the number dies, stage by stage."""

    bars: int = 0
    warm: int = 0
    signals: int = 0
    gated: int = 0
    sized: int = 0
    unsized: int = 0
    orders: int = 0
    trades: int = 0
    notes: list[str] = field(default_factory=list)


class Grid(Strategy):
    """One indicator rule, the desk's sizing, and a bracket.

    Everything that decides a size or a target is the desk's own function -
    `sizes.spec_of`, `risk.sizing.lots`, `Profile.floored_target`. The rule and
    the indicators are Nautilus's.
    """

    def __init__(self, config: GridConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self.counts = Counters()
        self.trades: list[Trade] = []
        self.rng = random.Random(config.seed)
        self.profile = _Floored(config.reward_floor)
        self.atr = framework("atr", 14)
        self.signal = self._signal_indicator()
        self.atr_history: list[float] = []
        self.previous: dict[str, float] = {}
        self.bars_seen = 0
        self.open_at = 0
        self.pending: dict[str, float] = {}

    def _signal_indicator(self):
        """Nautilus's own, by the name `indicators.FRAMEWORK` carries.

        MACD is built from the framework table's module directly because
        `indicators.framework` replaces only the **first** default argument and
        a MACD needs both periods; everything else is one period.
        """
        n = self.cfg.param
        if self.cfg.rule == "ema_cross":
            self.slow = framework("ema", 3 * n)
            return framework("ema", n)
        if self.cfg.rule == "macd_signal":
            from nautilus_trader.indicators.trend import MovingAverageConvergenceDivergence

            return MovingAverageConvergenceDivergence(n, 2 * n)
        return framework(
            {
                "donchian_break": "donchian",
                "rsi_revert": "rsi",
                "bb_revert": "bollinger",
                "keltner_break": "keltner",
            }[self.cfg.rule],
            n,
        )

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.cfg.instrument_id)
        self.register_indicator_for_bars(self.cfg.bar_type, self.atr)
        self.register_indicator_for_bars(self.cfg.bar_type, self.signal)
        if self.cfg.rule == "ema_cross":
            self.register_indicator_for_bars(self.cfg.bar_type, self.slow)
        self.subscribe_bars(self.cfg.bar_type)
        self.subscribe_quote_ticks(self.cfg.instrument_id)

    def on_stop(self) -> None:
        if self.cfg.out:
            path = Path(self.cfg.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "counts": {
                            k: v for k, v in vars(self.counts).items() if k != "notes"
                        }
                        | {"notes": self.counts.notes[:20]},
                        "trades": [vars(t) for t in self.trades],
                    }
                )
            )

    # ------------------------------------------------------------------ rules

    def _side(self, bar: Bar) -> int:
        """+1 to buy, -1 to sell, 0 for nothing. Six rules, one shape.

        Every rule that needs a previous reading reads `self.previous`, which
        is written at the end of `on_bar`. Nautilus updates a registered
        indicator **before** `on_bar`, so an unsnapshotted `donchian.upper` is
        already the current bar's high and `close > upper` can never be true.
        """
        close = float(bar.close)
        rule = self.cfg.rule
        prev = self.previous
        if rule == "ema_cross":
            fast, slow = self.signal.value, self.slow.value
            was = prev.get("ema_diff")
            now = fast - slow
            if was is None or was == 0.0:
                return 0
            return 1 if was < 0 < now else (-1 if was > 0 > now else 0)
        if rule == "donchian_break":
            upper, lower = prev.get("upper"), prev.get("lower")
            if upper is None or lower is None:
                return 0
            return 1 if close > upper else (-1 if close < lower else 0)
        if rule == "rsi_revert":
            was, now = prev.get("rsi"), self.signal.value
            if was is None:
                return 0
            return 1 if was < 0.30 <= now else (-1 if was > 0.70 >= now else 0)
        if rule == "macd_signal":
            was, now = prev.get("macd"), self.signal.value
            if was is None or was == 0.0:
                return 0
            return 1 if was < 0 < now else (-1 if was > 0 > now else 0)
        if rule == "bb_revert":
            was_close = prev.get("close")
            upper, lower = prev.get("upper"), prev.get("lower")
            if was_close is None or upper is None or lower is None:
                return 0
            return 1 if was_close < lower <= close else (-1 if was_close > upper >= close else 0)
        if rule == "keltner_break":
            upper, lower = prev.get("upper"), prev.get("lower")
            if upper is None or lower is None:
                return 0
            return 1 if close > upper else (-1 if close < lower else 0)
        raise ValueError(f"{rule!r} is not a rule in this grid")

    def _snapshot(self, bar: Bar) -> None:
        self.previous["close"] = float(bar.close)
        rule = self.cfg.rule
        if rule == "ema_cross":
            self.previous["ema_diff"] = self.signal.value - self.slow.value
        elif rule == "rsi_revert":
            self.previous["rsi"] = self.signal.value
        elif rule == "macd_signal":
            self.previous["macd"] = self.signal.value
        elif rule in ("donchian_break", "bb_revert", "keltner_break"):
            self.previous["upper"] = self.signal.upper
            self.previous["lower"] = self.signal.lower

    # ------------------------------------------------------------------- bars

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self.cfg.bar_type:
            return
        self.bars_seen += 1
        self.counts.bars += 1

        ready = self.atr.initialized and self.signal.initialized
        if self.cfg.rule == "ema_cross":
            ready = ready and self.slow.initialized
        if ready:
            self.counts.warm += 1
            self.atr_history.append(self.atr.value)
            if len(self.atr_history) > REGIME_BARS:
                self.atr_history.pop(0)

        position = self._position()
        if position is not None:
            if self.bars_seen - self.open_at >= HOLD_BARS:
                self.cancel_all_orders(self.cfg.instrument_id)
                self.close_position(position)
            self._snapshot(bar)
            return
        if self.cache.orders_open(instrument_id=self.cfg.instrument_id):
            self._snapshot(bar)
            return

        if ready:
            side = self._side(bar)
            if side:
                self.counts.signals += 1
                if self._passes():
                    self._enter(bar, side)
                else:
                    self.counts.gated += 1
        self._snapshot(bar)

    def _passes(self) -> bool:
        """The money-management variant's own filter, and its random twin.

        `gate` trades only where this instrument's ATR is below its own recent
        median; `twin` trades at the same *rate* and at random. On a net-
        negative book any rule that trades less improves the headline, so the
        twin is the only comparison that carries information - every pause rule
        this desk has tested beat its baseline by hundreds and none beat its
        own twin.
        """
        if self.cfg.mm == "gate":
            if len(self.atr_history) < REGIME_BARS:
                return False
            return self.atr.value < statistics.median(self.atr_history)
        if self.cfg.mm == "twin":
            if len(self.atr_history) < REGIME_BARS:
                return False
            return self.rng.random() < self.cfg.keep
        return True

    def _equity(self) -> float:
        return sizes.equity_of(self.portfolio.account(self.cfg.instrument_id.venue))

    def _enter(self, bar: Bar, side: int) -> None:
        entry = float(bar.close)
        distance = self.cfg.stop_atr * self.atr.value
        if distance <= 0:
            self.counts.unsized += 1
            return
        stop = entry - side * distance
        target = entry + side * self.cfg.target_r * distance
        spec = sizes.spec_of(self.instrument)
        if self.cfg.reward_floor > 0:
            target = self.profile.floored_target(
                spec, Side.BUY if side > 0 else Side.SELL, entry, stop, target
            )

        fraction = self.cfg.risk_fraction
        if self.cfg.mm == "volsize" and len(self.atr_history) >= REGIME_BARS:
            # A volatility target: risk less where this instrument is louder
            # than its own recent self. Clipped, because an unclipped ratio is
            # a lever whose mean is not one and that changes the average on its
            # own. The statistic it is judged on - net over risk deployed - is
            # scale-free, so a multiplier whose mean drifts cannot fake it.
            ratio = statistics.median(self.atr_history) / max(self.atr.value, 1e-12)
            fraction *= min(2.0, max(0.5, ratio))

        found = risk_sizing.lots(
            spec,
            equity=self._equity(),
            risk_fraction=fraction,
            stop_distance=abs(entry - stop),
        )
        if not found.ok:
            self.counts.unsized += 1
            if len(self.counts.notes) < 20:
                self.counts.notes.append(found.reason)
            return
        breach = risk_sizing.respects_stops_level(spec, entry, stop, target)
        if breach:
            self.counts.unsized += 1
            if len(self.counts.notes) < 20:
                self.counts.notes.append(breach)
            return
        self.counts.sized += 1

        digits = self.instrument.price_precision
        orders = self.order_factory.bracket(
            instrument_id=self.cfg.instrument_id,
            order_side=OrderSide.BUY if side > 0 else OrderSide.SELL,
            quantity=self.instrument.make_qty(found.volume),
            sl_trigger_price=self.instrument.make_price(round(stop, digits)),
            tp_price=self.instrument.make_price(round(target, digits)),
            time_in_force=TimeInForce.GTC,
        )
        self.pending = {
            "entry_ref": entry,
            "stop": stop,
            "target": target,
            "risk_money": found.risk_money,
        }
        self.open_at = self.bars_seen
        self.counts.orders += 1
        self.submit_order_list(orders)

    def _position(self):
        for position in self.cache.positions_open(instrument_id=self.cfg.instrument_id):
            return position
        return None

    def on_position_closed(self, event) -> None:
        position = self.cache.position(event.position_id)
        if position is None or not self.pending:
            return
        entry_ref = self.pending["entry_ref"]
        stop = self.pending["stop"]
        target = self.pending["target"]
        risk = abs(entry_ref - stop)
        # `Position.entry` is the entry order's own side and survives the
        # close; `signed_qty` and `side` are both flat by the time this fires.
        side = 1 if position.entry == OrderSide.BUY else -1
        entry_fill = float(position.avg_px_open)
        exit_fill = float(position.avg_px_close)
        move = (exit_fill - entry_fill) * side
        reason = "time"
        if risk > 0:
            if (side > 0 and exit_fill <= stop) or (side < 0 and exit_fill >= stop):
                reason = "stop"
            elif (side > 0 and exit_fill >= target) or (side < 0 and exit_fill <= target):
                reason = "target"
        self.trades.append(
            Trade(
                ts_open=int(position.ts_opened),
                ts_close=int(position.ts_closed or position.ts_opened),
                side=side,
                entry_ref=entry_ref,
                entry_fill=entry_fill,
                exit_fill=exit_fill,
                stop=stop,
                target=target,
                qty=float(position.peak_qty),
                risk_money=self.pending["risk_money"],
                pnl=float(position.realized_pnl) if position.realized_pnl is not None else 0.0,
                r=move / risk if risk > 0 else 0.0,
                bars=self.bars_seen - self.open_at,
                reason=reason,
            )
        )
        self.counts.trades += 1
        self.pending = {}
        if self.cache.orders_open(instrument_id=self.cfg.instrument_id):
            self.cancel_all_orders(self.cfg.instrument_id)


def cell_config(
    instrument_id: str,
    rule: str,
    param: int,
    mm: str,
    out: str,
    *,
    keep: float = 1.0,
    seed: int = 0,
    reward_floor: float = 0.0,
):
    """One `BacktestRunConfig`, through `node/backtest` so the venue is shared.

    The strategy path is the **flat** module name, not a dotted one: `research/`
    has no `__init__.py` anywhere, so `research.ideas.nautilus_grid` does not
    import. The runner beside this file puts its own directory on `sys.path`
    by being the script, which makes `nautilus_grid` importable in the parent
    and - because a pool forks - in every worker.
    """
    from nautilus_trader.config import ImportableStrategyConfig

    from till_infinity.node.backtest import run_config

    spec = "15-MINUTE-LAST-EXTERNAL"
    return run_config(
        instrument_id,
        spec,
        strategies=[
            ImportableStrategyConfig(
                strategy_path="nautilus_grid:Grid",
                config_path="nautilus_grid:GridConfig",
                config={
                    "instrument_id": instrument_id,
                    "bar_type": f"{instrument_id}-{spec}",
                    "rule": rule,
                    "param": param,
                    "mm": mm,
                    "reward_floor": reward_floor,
                    "keep": keep,
                    "seed": seed,
                    "out": out,
                },
            )
        ],
    )


def run_cell(args: tuple) -> dict:
    """One cell, start to finish, in whatever process the pool gives it."""
    import time
    import traceback

    (instrument_id, rule, param, mm, out, keep, seed, floor) = args
    os.environ.setdefault("BACKTEST_BALANCE", "100000")
    started = time.perf_counter()
    row = {
        "instrument_id": instrument_id,
        "rule": rule,
        "param": param,
        "mm": mm,
        "keep": keep,
        "out": out,
    }
    try:
        from nautilus_trader.backtest.node import BacktestNode

        config = cell_config(
            instrument_id, rule, param, mm, out, keep=keep, seed=seed, reward_floor=floor
        )
        BacktestNode(configs=[config]).run()
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        row["trace"] = traceback.format_exc()[-800:]
        row["seconds"] = time.perf_counter() - started
        return row
    row["seconds"] = time.perf_counter() - started
    path = Path(out)
    if not path.exists():
        row["error"] = "the strategy wrote no file: on_stop did not run"
        return row
    written = json.loads(path.read_text())
    row["counts"] = written["counts"]
    row["trades"] = len(written["trades"])
    return row
