"""v7: v6's four engines plus a displacement double rejection, behind the same gate.

Engine 5 is a two-phase pattern. A 15m displacement candle sweeps a swing pivot
while the attention score is extreme; the **body of the candle before it**
becomes a frozen origin zone; price retraces into that zone; and a second
displacement through it, or a 1H pin bar at it, is the trigger.

## What this already is, and what is actually new

**The base pattern is fade-to-value, and it is refuted in this repository.**
`CLAUDE.md` records it at length: giving "value" the definition this engine
uses - the origin candle of a displacement - turned an 82% return rate into a
target hit rate. Traded *from* the zone it was "negative everywhere"; as a
filter on origins it read +0.120R on 477 trades at 1d, +0.017R on 985 at 4h and
**-0.007R on 2,786 trades at 1h**, shrinking as the sample grew and reversing on
the largest. `the-origin-picks-a-distance-not-a-probability` is the same
finding from the other side: the origin selects how far price will travel, not
whether it will turn.

So the engine's *shape* is not an open question. What is new is that it is
wrapped in four conjunctive gates the refuted version never had:

1. the displacement must **sweep a swing pivot**;
2. the attention z-score must be **beyond its 85th percentile**;
3. a **second** displacement must push back through the zone, or
4. a **1H pin bar** must form at it.

The question this file asks is therefore narrow and worth asking: **do those
gates rescue a pattern that is negative without them?** The honest prior is no -
a filter that improves a negative expectancy usually does it by shrinking the
sample until the error bar covers everything - and the measurement that would
change my mind is a positive gap against the flip that survives the full span.

## What this inherits, and why

Everything below the signal: the four engines from `dual_engine_v6`, the shared
1H pin gate, the frames, the sizing, the protection, the reduce-only stop, the
wrong-side-stop guard and the TP2 runner. `dual_engine_port` carries four
measured port defects' worth of fixes and re-implementing any of it would
reintroduce them.

## Specified but already present, so not re-implemented

The brief's engineering guards are the ones v1 was fixed for and they are
closed upstream rather than here:

* **Ticket states.** Nautilus's `reduce_only` makes the stale-stop problem
  impossible - the venue clamps the order to the open position - so there is no
  `SUBMITTED`/`UPDATE_SUBMITTED` state machine to maintain. `dual_engine_port`
  explains why that replaced the hand-rolled version.
* **Residual flatten.** Cannot arise under `reduce_only`, for the same reason.
* **Minimum stop distance.** `min_risk_atr` already refuses a trade whose stop
  is inside `0.5 * ATR_15m`. **Note the difference from the brief**: v1
  *declines* such a trade where the brief *floors* the risk and takes it.
  Flooring R without widening the stop sizes the position against a risk larger
  than the distance to the stop, so R per trade reads better than the money
  does. Left as a decline, and the difference is stated rather than silently
  resolved.

Run it as `uv run python research/ideas/dual_engine_v7.py`.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.model.data import Bar

from dual_engine_port import Candle
from dual_engine_v6 import (
    HOUR_4,
    TOLERANCE,
    Frame,
    Setup,
    V6Config,
    Zone,
    aligned,
    build as build_v6,
    is_pin_bar,
    pivots,
)

#: The first push: a 15m candle whose body is this many ATRs, and this much of
#: its own range.
FIRST_BODY_ATR = 1.5
FIRST_BODY_SHARE = 0.70

#: The second push, back through the frozen zone. Smaller, because it is
#: confirmation rather than the event itself.
SECOND_BODY_ATR = 1.0

#: How long a frozen origin zone waits for its retrace before it is dropped.
#: The same 48 hours the rest of the family uses, so a zone cannot outlive the
#: context that created it.
FREEZE_NS = 48 * 3600 * 1_000_000_000


@dataclass(slots=True)
class Frozen:
    """A displacement that happened, waiting for price to come back to it."""

    direction: int
    zone: Zone
    stop: float
    created: int
    #: True once price has traded back into the zone. The second push only
    #: counts after that, which is what makes this a *double* rejection rather
    #: than a momentum entry.
    revisited: bool = False


def displaced(candle: Candle, atr15: float) -> int:
    """Is this a first-push displacement candle, and which way? 0 if not.

    Both tests as specified: the body against `ATR_15m`, and the body against
    the candle's own range. The second is what separates a decisive bar from a
    large one that spent its range going nowhere.
    """
    if atr15 <= 0 or candle.span <= 0:
        return 0
    body = abs(candle.close - candle.open)
    if body < FIRST_BODY_ATR * atr15:
        return 0
    if body / candle.span <= FIRST_BODY_SHARE:
        return 0
    return 1 if candle.close > candle.open else -1


def engine_displacement(
    fifteen: Frame, four: Frame, strong: int, tolerance: float, pad: float
) -> Frozen | None:
    """Phase 1: a displacement that sweeps a pivot while attention is extreme.

    Returns the **frozen origin zone**, not a `Setup` - this engine is the only
    one of the five that cannot arm a trade on the bar it fires, because the
    trade needs a retrace that has not happened yet.

    The zone is the body of the candle **before** the displacement, which is the
    definition `CLAUDE.md` records as the one that turned fade-to-value's 82%
    into a target hit rate rather than an entry signal.
    """
    if strong == 0 or len(fifteen) < 2:
        return None
    push = fifteen[0]
    atr15 = fifteen.atr.value if fifteen.atr.ready else 0.0
    direction = displaced(push, atr15)
    if direction == 0:
        return None

    highs, lows = pivots(four)
    # A down-push sweeps a low, an up-push sweeps a high. The wick is what
    # swept it, not the close.
    swept = push.low if direction < 0 else push.high
    if not aligned(swept, lows if direction < 0 else highs, tolerance):
        return None

    origin = fifteen[1]
    zone = Zone(min(origin.open, origin.close), max(origin.open, origin.close))
    if zone.low >= zone.high:
        return None

    # **The trade is the reversal of the retrace, not of the push.** A down
    # displacement leaves a zone above; price returning to it and being rejected
    # is a short continuing the push. So the direction carries through.
    stop = push.high + pad if direction < 0 else push.low - pad
    return Frozen(direction=direction, zone=zone, stop=stop, created=push.ts)


class V7Config(V6Config, frozen=True):
    enable_displacement: bool = True


def build(config: V7Config) -> Any:
    """v6's strategy with phase-2 bookkeeping and a fifth engine."""
    base = build_v6(config)
    kind = type(base)

    class V7(kind):  # type: ignore[valid-type, misc]
        def __init__(self, cfg: V7Config) -> None:
            super().__init__(cfg)
            self.cfg7 = cfg
            self.frozen: list[Frozen] = []
            self.phases: dict[str, int] = {}

        def _look(self, closed: dict[str, Candle | None], strong: int) -> None:
            # The other four first, unchanged.
            super()._look(closed, strong)
            if not self.cfg7.enable_displacement:
                return
            fifteen = self.frames["15m"]
            four = self.frames["4h"]
            if closed["15m"] is None or not four.atr.ready or not self.atr15.ready:
                return
            tol = TOLERANCE * four.atr.value
            pad = 0.5 * self.atr15.value

            self._phase_two(closed["15m"], pad)

            if self._trade is not None or self.pending is not None:
                return
            found = engine_displacement(fifteen, four, strong, tol, pad)
            if found is not None:
                self.frozen.append(found)
                self._tally(self.phases, "displacement:frozen")

        def _phase_two(self, latest: Candle, pad: float) -> None:
            """Retrace into a frozen zone, then a second push or a pin bar."""
            atr15 = self.atr15.value if self.atr15.ready else 0.0
            for zone in list(self.frozen):
                if latest.ts - zone.created > FREEZE_NS:
                    self.frozen.remove(zone)
                    self._tally(self.phases, "displacement:never-revisited")
                    continue
                if not zone.revisited:
                    if zone.zone.touched(latest):
                        zone.revisited = True
                        self._tally(self.phases, "displacement:revisited")
                    continue
                # A second displacement closing back through the zone, in the
                # push's own direction.
                body = abs(latest.close - latest.open)
                through = (
                    latest.close < zone.zone.low
                    if zone.direction < 0
                    else latest.close > zone.zone.high
                )
                second = through and body >= SECOND_BODY_ATR * atr15 and atr15 > 0
                pinned = is_pin_bar(latest, zone.direction) and zone.zone.touched(latest)
                if not (second or pinned):
                    continue
                self.frozen.remove(zone)
                self._tally(
                    self.phases, "displacement:second-push" if second else "displacement:pinned"
                )
                setup = Setup(
                    engine="displacement",
                    direction=zone.direction,
                    zone=zone.zone,
                    stop=zone.stop,
                    created=latest.ts,
                    confirmed=True,
                )
                self._tally(self.fired, "displacement")
                self._tally(self.confirmed, "displacement")
                # **Armed directly, not queued behind the 1H pin gate.** The
                # brief makes the pin one of two alternative triggers for this
                # engine rather than a gate on top of them, so routing it
                # through `self.armed` would require a pin that the second-push
                # branch has already stood in for.
                self._arm(setup)
                return

    return V7(config)


# --- running it --------------------------------------------------------------

CATALOGUE = Path.home() / "till-data" / "mt5-deep"
SPEC = "5-MINUTE-LAST-EXTERNAL"

#: The new engine alone, the five together, and the four that came before, so
#: the fifth's contribution is a difference rather than an assertion.
ARMS: tuple[tuple[str, dict[str, bool]], ...] = (
    (
        "displacement only",
        {
            "enable_exhaustion": False,
            "enable_choppy": False,
            "enable_engulfing": False,
            "enable_crt": False,
        },
    ),
    ("four (v6)", {"enable_displacement": False}),
    ("all five", {}),
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
            trader_id="V7-001",
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
            V7Config(
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

    def merge(books: Any) -> dict[str, int]:
        out: dict[str, int] = {}
        for book in books:
            for key, value in book.items():
                out[key] = out.get(key, 0) + value
        return out

    out = {
        "closed": [t for s in built for t in s.closed],
        "fired": merge(s.fired for s in built),
        "phases": merge(getattr(s, "phases", {}) for s in built),
    }
    engine.dispose()
    return out


def main() -> None:
    from dual_engine_grid import Cell, load_all, measure, rolling, span_days

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--arm", default="")
    args = parser.parse_args()

    instruments, data = load_all(Path(args.catalogue), SPEC)
    if not instruments:
        raise SystemExit(f"nothing in {args.catalogue}")
    days = span_days(data)
    bars = sum(1 for row in data if isinstance(row, Bar))
    print(f"{len(instruments)} instruments, {bars} bars, {days:.0f} days, 5m execution\n")

    for name, knobs in ARMS:
        if args.arm and name != args.arm:
            continue
        out = {}
        for flip in (False, True):
            found = run(instruments, data, knobs, flip=flip)
            cell = Cell(0.015, 0.85, 0.01, flip, bars_per_structure=HOUR_4, bar_spec=SPEC)
            out[flip] = (measure(cell, found["closed"], days), found)
        rule, detail = out[False]
        null = out[True][0]
        gap = rule.reward - null.reward if rule.trades and null.trades else float("nan")
        se = math.sqrt(rule.reward_se**2 + null.reward_se**2) or float("nan")
        print(
            f"  {name:<20} rule n {rule.trades:>4} R {rule.reward:>+6.3f} "
            f"+/-{rule.reward_se:>5.3f} dd {rule.drawdown:>5.1%}  |  "
            f"flip n {null.trades:>4} R {null.reward:>+6.3f}  |  "
            f"gap {gap:>+6.3f} ({gap / se:>+5.2f} se)"
        )
        # **Every window, never the best one.** README: "Backtests are reported
        # on rolling recent windows", because a full-span figure can be an
        # average over a regime that has ended.
        windows = dict(rolling(detail["closed"], days))
        nulls = dict(rolling(out[True][1]["closed"], days))
        for label, found in windows.items():
            other = nulls.get(label)
            if found.trades == 0:
                continue
            spread = found.reward - other.reward if other and other.trades else float("nan")
            print(
                f"       {label:<4} n {found.trades:>4} R {found.reward:>+6.3f} "
                f"+/-{found.reward_se:>5.3f} dd {found.drawdown:>5.1%}  "
                f"vs flip {spread:>+6.3f}"
            )
        fired = ", ".join(f"{k} {v}" for k, v in sorted(detail["fired"].items())) or "none"
        print(f"       fired [{fired}]")
        if detail["phases"]:
            print(
                f"       phases [{', '.join(f'{k} {v}' for k, v in sorted(detail['phases'].items()))}]"
            )


if __name__ == "__main__":
    main()
