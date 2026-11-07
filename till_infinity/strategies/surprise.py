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

from ..domain import costs
from ..domain.models import Intent, Refusal, Side
from ..statespace.proposing import TRIGGER
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
    #:
    #: **It must not exceed the producer's own trigger.** `proposing.TRIGGER`
    #: is 3.0, so at 3.5 every proposal in [3.0, 3.5) was emitted only to be
    #: refused here - a band of work done and thrown away, and a refusal
    #: counter that reads as the market being quiet rather than as two
    #: constants in different modules disagreeing. Measured 2026-11-07:
    #: `|surprise| >= 3.0` on 1.80% of real-market 15m bars, so the discarded
    #: band was not rare.
    #:
    #: Set to the trigger. Raising it again is a decision to refuse what was
    #: asked for, and `test_the_floor_is_not_above_the_producers_trigger`
    #: fails if the two drift apart.
    least_surprise: ClassVar[float] = TRIGGER
    #: The share of the move a round trip may cost before the idea is over.
    #:
    #: **Chosen, not measured.** `statespace/deciding.py` cited this as the
    #: place it was measured and nothing here measures it. The measured cost
    #: limit on this desk is `Envelope.max_spread_risk_fraction` at 0.16 of the
    #: *risk*, which is 0.32 volatility units on a 2-vol stop against this
    #: one's 0.40 - so the gate that fires is the looser of the two, and the
    #: tighter one has no production caller. See `COST_SHARE` in
    #: `statespace/deciding.py` for the per-venue measurement and for the 49
    #: trades that passed a reward-denominated test and lost -0.471R.
    cost_share: ClassVar[float] = 0.10
    #: Fallbacks where the proposal names neither.
    stop_vol: ClassVar[float] = 2.0
    target_r: ClassVar[float] = 2.0
    #: The feeds it is allowed on, because `TRADING_SYMBOLS` is global and
    #: naming the strategy would otherwise put it on every one of them.
    #:
    #: **Crypto is admitted on a measurement, not on hope.** Replaying the
    #: production fold over 3,941 BTCUSD readouts, `|surprise| >= TRIGGER`
    #: fires on **2.11%** of bars - 83 of them, max 11.43, q99 at 3.49 -
    #: against **1.80%** on the FX and index feeds. Crypto is *more* likely to
    #: clear the trigger than the majors it was measured on, so it needs
    #: nothing but admission.
    #:
    #: **The Deriv synthetics are deliberately still absent.** Over 4,725
    #: readouts on the `Volatility N (1s)` family, `|surprise|` never reached
    #: **2.5**, let alone the trigger: max 2.242. The fold's surprise is a
    #: standardised innovation and these are a known-generator process with a
    #: well-calibrated one-step predictive and thin tails, so the trigger sits
    #: above their entire observed support. Admitting them would add desks that
    #: cannot fire, which is the state 26 of 32 desks were in before this
    #: comment existed. Opening them is a **separate** decision needing a
    #: per-family trigger - gate on the residual deque's empirical quantile at
    #: a target rate rather than on a fixed sigma - and the rate-matched number
    #: to carry into that work is **1.446 on the synthetics is 3.0 on a real
    #: market**. That is a measurement with a planted-effect power check and a
    #: placebo arm, not a constant to edit, and `Volatility N (1s)` is one of
    #: this repository's own structure controls.
    #:
    #: Override with `SURPRISE_FEEDS`, comma-separated, for a sweep that wants
    #: a different scope without a code change. Empty means this default.
    feeds: ClassVar[frozenset[str]] = frozenset(
        {
            # Measured: the majors and gold.
            "eurusd",
            "gbpusd",
            "usdjpy",
            "audusd",
            "usdcad",
            "xauusd",
            # Measured 2026-11-07: 2.11% of bars clear the trigger.
            "btcusd",
            "ethusd",
            "bnbusd",
        }
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
        return str(payload.get("feed") or "").lower() in self._allowed()

    def _allowed(self) -> frozenset[str]:
        """`SURPRISE_FEEDS` if set, else the profile's measured default.

        Read per call rather than cached, so a sweep can change scope without
        a restart and a reader can see what the desk is actually using.
        """
        import os

        raw = os.environ.get("SURPRISE_FEEDS") or ""
        named = frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
        return named or self.profile.feeds

    def on_start(self) -> None:
        """Say once if this desk can never trade.

        **A rule that is not allowed on its feed and a feed that is quiet read
        identically in a log.** On 2026-11-07 twenty-six of thirty-two desks
        were inert by construction and nothing said so, and establishing that
        took an afternoon.
        """
        super().on_start()
        feed = self._feed_name()
        if feed not in self._allowed():
            self.log.warning(
                f"statespace-surprise is not allowed on {feed}; "
                f"this desk can never trade. Allowed: {sorted(self._allowed())}"
            )

    def _spread_limit(self) -> float:
        """The share of the risk a round trip may cost, as configured.

        Read off `Settings` rather than carried as a `ClassVar`, so the number
        has one home and `TRADING_MAX_SPREAD_RISK_FRACTION` still moves it.
        Falls back to the measured default where there is no settings object -
        a `Profile` built with `__new__`, which is how the class attribute on
        this mixin is constructed.
        """
        settings = getattr(self.profile, "settings", None)
        found = getattr(settings, "max_spread_risk_fraction", None)
        return float(found) if isinstance(found, int | float) else costs.MAX_SPREAD_RISK_FRACTION

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
        # **And against the risk, which is the denominator the damage was
        # measured in.** The check above scales the permitted spread with the
        # target, so a distant target buys the right to pay more; this one does
        # not, because a spread that is half the stop distance is half the stop
        # distance wherever the target sits. 49 trades passed the reward test
        # while expensive against risk, at -0.471R and 53% stopped, for
        # -502.70 - see `domain/costs.py`, which holds the limit and the
        # comparison so this rule and `statespace/deciding.py` cannot disagree
        # about either.
        if dear := costs.too_expensive(cost, risk, self._spread_limit()):
            return Refusal(gate="spread_risk", detail=dear, feed=feed)

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
