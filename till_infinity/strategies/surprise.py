"""The statespace-surprise decision, and the strategies it composes into.

**A mixin and not a base class, so a decision and an entry stay independent.**
The old shape was a `Strategy` ABC that a runner consulted: one hierarchy
carrying the decision, the parameters and the helpers together, with the
mechanism chosen elsewhere. That made the pair fixed in the wrong direction -
the decision knew nothing about how it would be placed, and the thing that
placed it knew nothing about what it was.

Here the decision is a mixin with no base of its own, the entry mechanisms are
in `entries.py`, the exit mechanisms are in `exits.py`, and a concrete strategy
is the composition of all three:

    class SurpriseEdge(Surprise, ManagedExit, EdgeEntry): ...
    class SurpriseResting(Surprise, ManagedExit, RestingEntry): ...

Each leaf **is** a `nautilus_trader` `Strategy`, so the framework assigns it a
`strategy_id` and carries it on every order, fill and position. One decision
across three mechanisms is three classes and no flags, and *which* mechanism
took a trade is a fact the engine records rather than something we remember.

**The exit was the half that was only claimed.** This docstring said a free
pairing is "what entries and exits are asymmetric means in code" while the
exit was whatever bracket the entry happened to submit inside `place` -
identical for every decision, with no way for a decision to state one.
`exits.ExitMechanism` is the missing third piece and composes the same way;
`leaves.py` is where every triple this node builds is written out.

## What this decides, and what it does not

It answers one question - *is this proposal worth trading, and where do the
stop and target go* - and nothing else. `Profile` holds the numbers and the
helpers measured on them, `plans` bounds the loss, `risk` decides whether this
account may take another, and Nautilus sends it and reconciles. The last of
those used to be `service.py`, which is the whole reason for the move.

**It claims no edge of its own.** It reads the surprise `statespace` publishes;
what it adds is a threshold on it and the geometry around the entry. A rule
invented here would be an unmeasured one riding on a measured one's reputation.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..domain.models import Intent, Refusal, Side
from .entries import ArrivalEntry, EdgeEntry, RestingEntry
from .exits import ManagedExit
from .profile import Profile


def _number(value: Any) -> float:
    """A float, or zero. A feature that is absent and one that is unparseable
    are the same thing to a threshold, and neither is a reason to raise."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class SurpriseProfile(Profile):
    """The numbers this decision runs on. Lifted unchanged from `dispersing`."""

    name: ClassVar[str] = "statespace-surprise"
    shape: ClassVar[str] = "statespace"
    #: A target must pay this multiple of the real risk. 1.70 measured.
    reward_floor: ClassVar[float] = 1.70
    #: How surprising a reading has to be. Below it there is nothing to trade.
    least_surprise: ClassVar[float] = 3.5
    #: The share of the move a round trip may cost before the idea is over.
    cost_share: ClassVar[float] = 0.10
    #: Fallbacks where the proposal names neither.
    stop_vol: ClassVar[float] = 2.0
    target_r: ClassVar[float] = 2.0
    #: The feeds it is allowed on, because `TRADING_SYMBOLS` is global and
    #: naming the strategy would otherwise put it on every one of them.
    feeds: ClassVar[frozenset[str]] = frozenset(
        {"eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "xauusd"}
    )


class Surprise:
    """Trade a statespace reading that is surprising enough to pay for itself.

    A mixin: it has no base and expects to be composed with an entry from
    `entries.py`, which supplies the Nautilus `Strategy` and the `place`.
    """

    #: The numbers. A class attribute rather than built per instance, because
    #: a profile is configuration and two instances of one strategy on two
    #: instruments share it.
    profile: ClassVar[SurpriseProfile] = SurpriseProfile.__new__(SurpriseProfile)

    def wants(self, payload: dict[str, Any]) -> bool:
        """The shape **and** the feed.

        Checked before `decide` so a proposal on an unlisted feed costs nothing
        and is not counted as a refusal - it was never this strategy's to
        decline.
        """
        if str(payload.get("shape") or "") != self.profile.shape:
            return False
        return str(payload.get("feed") or "").lower() in self.profile.feeds

    def decide(  # noqa: PLR0911 - one gate per return, in the order they are
        # applied: the order is the design, and each return is a distinct way a
        # proposal stops being a trade, counted under its own gate.
        self,
        payload: dict[str, Any],
    ) -> Intent | Refusal | None:
        """A trade, or the reason there is not one. Never raises on a payload."""
        feed = str(payload.get("feed") or "")
        tick = self._tick()
        if tick is None:
            return Refusal(gate="no-quote", detail=f"no quote for {feed}", feed=feed)

        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal(gate="features", detail="no features on the proposal", feed=feed)

        surprise = abs(_number(features.get("surprise")))
        if surprise < self.profile.least_surprise:
            return Refusal(
                gate="surprise",
                detail=f"{surprise:.2f} below {self.profile.least_surprise:.2f}",
                feed=feed,
            )

        side_raw = int(_number(payload.get("direction")))
        if side_raw == 0:
            # A doji expressed no direction. The producer drops these, so this
            # is a second line rather than the only one.
            return Refusal(gate="direction", detail="the bar took no side", feed=feed)
        side = Side.BUY if side_raw > 0 else Side.SELL

        # One volatility unit as a price distance. `vol_bps` is the folded log
        # variance - `exp(value / 2)` in basis points - and nothing here reads
        # the spread *column*, whose conversion is a measured 476% error.
        vol_bps = _number(features.get("vol_bps"))
        entry = tick.ask if side is Side.BUY else tick.bid
        if vol_bps <= 0.0 or entry <= 0.0:
            return Refusal(gate="volatility", detail=f"vol_bps {vol_bps:.4f}", feed=feed)
        unit = vol_bps / 1e4 * entry

        stop_vol = _number(features.get("stop_vol")) or self.profile.stop_vol
        target_r = _number(features.get("target_r")) or self.profile.target_r
        risk = stop_vol * unit
        if risk <= 0.0:
            return Refusal(gate="volatility", detail="a zero stop distance", feed=feed)

        # **The gate that decides this strategy**, checked before the geometry
        # and before sizing: a trade that cannot pay for its own round trip is
        # not a trade, whatever the rest of the arithmetic says.
        cost = tick.ask - tick.bid
        reward = target_r * risk
        if reward <= 0.0:
            return Refusal(gate="reward", detail="a zero target", feed=feed)
        if cost > reward * self.profile.cost_share:
            return Refusal(
                gate="cost",
                detail=f"the round trip is {cost / reward:.0%} of the target, "
                f"limit is {self.profile.cost_share:.0%}",
                feed=feed,
            )

        sign = side.sign
        stop = entry - sign * risk
        target = entry + sign * reward
        spec = self._spec()
        if spec is not None:
            # Pushed out until it pays `reward_floor` times the real risk,
            # where the geometry is finished rather than where it is proposed.
            target = self.profile.floored_target(spec, side, entry, stop, target)

        return Intent(
            feed=feed,
            symbol=spec.symbol if spec is not None else feed,
            side=side,
            # Sized by `risk`, not here: two places computing a size is how
            # they come to disagree. Zero means "the sizer has not run", and
            # `place` refuses a zero rather than rounding it up.
            volume=_number(features.get("volume")),
            entry=entry,
            stop=stop,
            target=target,
            reason=f"surprise {surprise:.2f} on {feed}",
            interval=str(payload.get("interval") or ""),
            features={k: _number(v) for k, v in features.items()},
            stop_vol=stop_vol,
        )


class SurpriseEdge(Surprise, ManagedExit, EdgeEntry):
    """Surprise, taken at market. The pairing with the fewest moving parts."""


class SurpriseResting(Surprise, ManagedExit, RestingEntry):
    """Surprise, left as a limit at the entry it named."""


class SurpriseArrival(Surprise, ManagedExit, ArrivalEntry):
    """Surprise, parked until price comes to it and a bar confirms."""
