"""A strategy that exists to carry the mechanics tests, and nothing else.

Most of `test_trading.py` is about the trading service's **mechanics** - one
slot per feed, exposure caps, sizing through `lots`, reconciliation, what
reaches the journal - and it used `level-scalp` as a vehicle for them. When the
level strategies retired with the structures service that fed them, those tests
needed a vehicle rather than a replacement strategy.

**Why not re-base them onto `statespace-surprise`.** It is a real strategy with
real gates, and the suite's gold fixture fails one of them: a 1.00 spread
against a 2-volatility stop at `vol_bps` 10 is a cost share of 0.1136 against
its 0.10 ceiling, so every re-based test would be refused. Tuning the fixture
until an unrelated strategy's gate passes is how a suite stays green and stops
meaning anything.

**Why not copy `LevelStrategy` here.** The level geometry is four methods deep -
an anchored stop, a target held short of the level, two floors - and copying
them into the test suite would keep 700 lines of retired code alive under a
different name. The tests that assert that geometry are tests *of* it, and they
retired with it; what is left needs a valid Intent, not a particular one.

So this is the plainest strategy that can produce one: a side, a stop a
volatility unit away, a target at the expected push, sized by the same `lots`
call every strategy makes. It keeps `shape = "level"` - the base class default -
so the existing `signal()` fixture is accepted unchanged and none of the call
sites had to move.

It is **not registered at import**. `tests/conftest.py` puts it in the registry
for the session, so nothing in the package can reach it and `trading
strategies` does not list it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from till_infinity.trading.models import Intent, Refusal, Side, SymbolSpec, Tick, Verdict
from till_infinity.trading.sizing import lots, price_distance
from till_infinity.trading.strategies.strategy import Strategy

#: The name the tests ask for. Prefixed so the floors partition and anything
#: else that enumerates shipped strategies can tell it apart from one.
NAME = "test-mechanics"


def _number(features: dict[str, Any], key: str) -> float:
    try:
        return float(features.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


class Mechanics(Strategy):
    """A valid Intent from a level call, with no opinion about levels."""

    name: ClassVar[str] = NAME
    description: ClassVar[str] = "Test vehicle. Not shipped; see tests/mechanics.py."
    #: **The fast band, not every interval.** A first version accepted all of
    #: them and quietly broke the tests about interval refusals: a vehicle that
    #: never refuses cannot carry a test about refusing. These are the five
    #: `level-scalp` declared, so the refusal those tests provoke still happens.
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    context: ClassVar[tuple[str, ...]] = ()
    needs_context: ClassVar[bool] = False

    def consider(
        self,
        payload: dict[str, Any],
        *,
        spec: SymbolSpec,
        tick: Tick,
        equity: float,
        positions: Sequence[Any] = (),
        peak: float = 0.0,
    ) -> Verdict:
        feed = str(payload.get("feed") or "")
        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal("features", "no features", feed)

        side = Side.from_direction(str(payload.get("direction") or ""))
        if side is None:
            return Refusal("direction", "no side", feed)

        vol_bps = _number(features, "vol_bps")
        risk_vol = abs(_number(features, "risk_vol")) or 1.0
        push_vol = abs(_number(features, "expected_push_vol")) or 1.0
        entry = tick.entry(side)
        if vol_bps <= 0 or entry <= 0:
            return Refusal("volatility", f"vol_bps {vol_bps}", feed)

        # **The volatility unit is priced off the level, not the entry**, when
        # the call carries one. Off the entry it differs by the spread, which
        # put the pullback ceiling 0.002 the wrong side of its bound - small
        # enough to look like a rounding argument and large enough to fail.
        level = _number(features, "level")
        unit = price_distance(level or entry, vol_bps, 1.0)
        risk = risk_vol * unit
        if risk <= 0:
            return Refusal("volatility", "a zero stop distance", feed)

        interval = str(payload.get("interval") or "5m")
        # **The interval gate, which lives in `consider` and not in `wants`.**
        # `Strategy.wants` is a shape check only, so a vehicle without this
        # accepts a 1d call on a fast-band strategy - and the tests about
        # interval refusals then see a trade taken instead of a refusal
        # tallied, which reads as the tally being broken.
        if interval not in self.intervals:
            return Refusal("interval", f"{interval} is not one of {self.intervals}", feed)
        away = 1.0 if side is Side.BUY else -1.0
        stop = entry - away * risk
        target = entry + away * push_vol * unit
        # The one shared refinement kept, because it lives on `Strategy` rather
        # than on the retired level class and several mechanics tests are about
        # what it does to a target.
        target = self.floored_target(spec, side, entry, stop, target)

        sized = lots(
            spec,
            equity=equity,
            risk_fraction=(
                self.settings.risk_fraction
                * self.risk_scale(feed, features, positions, equity, peak, interval, side)
            ),
            stop_distance=risk,
            max_risk_money=self.settings.max_risk_money,
            slippage=self.settings.stop_slippage,
        )
        return Intent(
            feed=feed,
            symbol=spec.symbol,
            side=side,
            volume=sized.volume,
            entry=entry,
            stop=stop,
            target=target,
            reason=str(payload.get("detail") or ""),
            interval=interval,
            confluence=tuple(str(x) for x in (payload.get("confluence") or ())),
            features={str(k): _number(features, k) for k in features},
            risk_money=sized.risk_money,
            stop_vol=risk_vol,
            hold=self.hold_for(interval),
            break_even_at=self.break_even_at,
            trail_vol=self.trail_vol,
        )
