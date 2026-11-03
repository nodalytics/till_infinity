"""The statespace decision, as one mixin per side, so entries can be asymmetric.

Asked for on 2026-11-01 - statespace "can send signals to its own strategy that
handles entries and exits for it which can be asymmetric". This is that
strategy's decision half, written in the shape `strategies/surprise.py`
established: **a mixin with no base of its own.**

    class Surprise: ...                     # the decision
    class SurpriseEdge(Surprise, EdgeEntry)  # the decision plus a mechanism

`Surprise.__mro__` is `(Surprise, object)`, and that is what makes the pairing
free: the decision does not know how it will be placed and the thing that
places it does not know what it is, so one decision across three mechanisms is
three classes and no flags - and *which* mechanism took a trade is a fact
Nautilus records on the `strategy_id` rather than something we remember.

## How the asymmetry is expressed: one leaf per side, not a flag

The long side and the short side need not use the same mechanism, the same
geometry or the same sizing. In this pattern that is **two leaves**, because a
leaf *is* a Nautilus `Strategy` and a strategy has one `place`:

    class StatespaceLongEdge(LongSide, EdgeEntry): ...
    class StatespaceShortResting(ShortSide, RestingEntry): ...

Those two lines, plus a subscription of `statespace.proposals` to `Desk.on_data`
and an entry in the desk's strategy list, are the whole addition `strategies/`
needs. Nothing else here reaches into it.

`wants()` on each side refuses the other side's proposals, so the two run
together on one feed without either seeing the other's signals, and the engine
books their fills under different strategy ids. A `side` flag inside one class
would have produced one `strategy_id` across both mechanisms, which is the
fact the magic-number argument says not to lose.

**The exits are asymmetric through the `Intent` and need no change in
`strategies/`.** `Intent` already carries `stop_vol`, `stop_scale`,
`break_even_at`, `trail_vol`, `trail_levels`, `hold` and `stale_exempt`, and
`exits.Exits` reads every one of them off the intent rather than off the
strategy - the field comments say why: by the time a stop is being moved, the
strategy that wanted the trade is a name in a log line. So a per-side exit
policy is a per-side set of numbers on the intent, which is what `SideProfile`
holds.

## The numbers are identical on both sides, and that is deliberate

Nothing on this desk has measured a long/short asymmetry in a dispersion
trigger. So the two profiles below carry the **same** numbers, and the
asymmetry is a capability rather than a claim - `surprise.py` states the rule
this follows: "a rule invented here would be an unmeasured one riding on a
measured one's reputation". The machinery is tested with a profile pair that
*does* differ, so the path is proven without the numbers being invented.

## What this decides, and the direction it does not claim

The trigger is a **dispersion** reading: `proposing.py` publishes a
standardised surprise on the folded log variance, and the side comes from the
triggering bar's own body, which is continuation. `direction-is-closed-not-
just-null` is why nothing cleverer is attempted - the gate that looks for
direction finds a *planted* drift at z +2.90 and earns 2% of one spread - and
`searching.py`'s own sweep over 42 shape families and the detector panel found
nothing directional either.

Expects to be composed with `strategies.desk.Desk`, which supplies `_tick`
and `_spec`. It imports neither: `statespace` may read `domain` and
`indicators` and nothing else, and a mixin that imported its own host would
make the host un-substitutable in a test.
"""

from __future__ import annotations

from typing import Any, ClassVar

from till_infinity.domain import costs
from till_infinity.domain.models import Intent, Refusal, Side

#: Standardised surprise that counts as a trigger. 3.0, matching
#: `proposing.TRIGGER`: `origin-returns-turn-at-z-one-three` measured returns
#: turning at z 1.3 to 1.95 and non-returners reaching 2.2, so z 2.5 already
#: misses 85-89% of them.
TRIGGER = 3.0

#: Reward to risk the geometry is solved for, and the stop in units of the
#: feed's own per-bar volatility. Both from `proposing`, so the producer and
#: the consumer do not carry two different defaults.
TARGET_R = 2.0
STOP_VOL = 2.0

#: The share of the target a round trip may cost. 0.10, from
#: `surprise.SurpriseProfile`.
#:
#: **It said "where it is measured", and it is not measured there or anywhere.**
#: `SurpriseProfile.cost_share` carries the number and no source, so the two
#: files cited each other and neither held a measurement. Corrected rather than
#: deleted, because the number is doing real work and a reader has to be able
#: to tell it from one that was fitted.
#:
#: What *is* measured sits next door and uses a different denominator. This
#: gate is `cost > reward * share`, and `risk/guard.py` records what a
#: reward-denominated test misses: **49 trades passed the reward test while
#: expensive against the risk, at -0.471R and 53% stopped, for -502.70.** Hence
#: `Envelope.max_spread_risk_fraction` at 0.16 of the *risk*, which on this
#: geometry - `STOP_VOL` 2, `TARGET_R` 2 - is a limit of 0.32 volatility units
#: against this one's 0.40. The measured gate is the tighter of the two, and it
#: has no production caller: it lives inside `Guard.allows`.
#:
#: Measured on the recorded quotes, per venue, on 15m bars: a Deriv eurusd
#: round trip is 0.26 of one volatility unit at the median, so 0.40 refuses
#: 12% of bars and 0.32 refuses 29%. The same rule on the same bars costs 0.04
#: of a unit at FOREXCOM and 0.81 at Pepperstone - a nineteenfold spread range
#: across six venues on one instrument - and 0.02 on Deriv *gold*, whose
#: volatility unit is five times eurusd's for a smaller spread. The threshold
#: is not what decides whether this gate binds; the instrument and the venue
#: are.
COST_SHARE = 0.10

#: The share of the **risk** a round trip may cost, which is the measured one.
#: From `domain/costs.py`, where the number and the comparison both live.
SPREAD_RISK_SHARE = costs.MAX_SPREAD_RISK_FRACTION


def _number(value: Any) -> float:
    """A float, or zero. A feature that is absent and one that is unparseable
    are the same thing to a threshold, and neither is a reason to raise."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class SideProfile:
    """One side's numbers: the gate, the geometry, the sizing and the exit.

    A plain class of `ClassVar`s rather than a `strategies.profile.Profile`
    subclass, because `statespace` may not import `strategies` - and because
    nothing here needs `Profile`'s settings, floors or limits. A concrete
    strategy in `strategies/` that wants `Profile.floored_target` on top can
    apply it to `Intent.target` after this returns; the fields are all public.
    """

    #: Which side this profile is for. `None` on the base, so an unset profile
    #: refuses every proposal rather than taking both sides.
    side: ClassVar[Side | None] = None
    name: ClassVar[str] = "statespace"
    shape: ClassVar[str] = "statespace"

    #: The gate.
    least_surprise: ClassVar[float] = TRIGGER
    cost_share: ClassVar[float] = COST_SHARE
    #: And against the risk. See `SPREAD_RISK_SHARE`.
    spread_risk_share: ClassVar[float] = SPREAD_RISK_SHARE

    #: The geometry.
    stop_vol: ClassVar[float] = STOP_VOL
    target_r: ClassVar[float] = TARGET_R

    #: The exit, carried onto the `Intent` so `exits.Exits` reads it there.
    #: Zero means "use the configured default" for each of these, which is the
    #: convention the `Intent` fields already declare.
    break_even_at: ClassVar[float] = 0.0
    trail_vol: ClassVar[float] = 0.0
    trail_levels: ClassVar[bool] = False
    hold: ClassVar[float] = 0.0
    stale_exempt: ClassVar[bool] = False

    #: Share of the account's per-trade risk this side may use. 1.0 is the
    #: whole allowance.
    #:
    #: **Carried, not applied, and nothing reads it yet.** The desk's own
    #: mechanism is `strategies.profile.Profile.share_of_risk`, which resolves
    #: `risk_share` off the *profile* and caps it at 1 - "a per-strategy knob
    #: may argue for less risk and never for more, so a typo cannot enlarge a
    #: position". `SideProfile` is not a `Profile`, because `statespace` may not
    #: import `strategies`, so a leaf that wants a per-side risk share sets it
    #: on a `Profile` subclass where the leaf is defined. The copy on
    #: `Intent.features` is for the **journal**: it records what the side asked
    #: for, so a closed trade can be added up against it.
    #:
    #: Stated rather than left implied, because a field that looks like it
    #: sizes and does not is the `research/inert.md` shape - "a feature
    #: configured, correct and inert", of which `scale_out_at` sat at 1.0 for
    #: the life of the desk without a single scale-out firing.
    risk_share: ClassVar[float] = 1.0

    #: The feeds this side is allowed on. From `surprise.SurpriseProfile`,
    #: because `TRADING_SYMBOLS` is global and naming a strategy would
    #: otherwise put it on every one of them.
    feeds: ClassVar[frozenset[str]] = frozenset(
        {"eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "xauusd"}
    )


class LongProfile(SideProfile):
    """The long side. Same numbers as the short side - see the module docstring."""

    side: ClassVar[Side | None] = Side.BUY
    name: ClassVar[str] = "statespace-long"


class ShortProfile(SideProfile):
    """The short side. Same numbers as the long side, and not by coincidence.

    An asymmetry here would be a rule nobody measured. The two are written out
    separately rather than aliased so that the first measured difference is a
    one-line change in one place, and so a reader can see that the difference
    today is zero.
    """

    side: ClassVar[Side | None] = Side.SELL
    name: ClassVar[str] = "statespace-short"


class OneSided:
    """A statespace dispersion trigger, taken on one side only.

    A mixin with no base: it expects an entry from `strategies/entries.py` to
    supply the Nautilus `Strategy`, the `place` and `Desk`'s `_tick` and
    `_spec`.
    """

    #: The numbers. A class attribute rather than built per instance, because
    #: a profile is configuration and two instances of one strategy on two
    #: instruments share it.
    profile: ClassVar[type[SideProfile]] = SideProfile

    def wants(self, payload: dict[str, Any]) -> bool:
        """The shape, the feed **and the side**.

        The side is checked here rather than in `decide` so that the other
        side's proposals cost nothing and are not counted as refusals - they
        were never this leaf's to decline. That is what lets a long leaf and a
        short leaf run together on one feed with different mechanisms.
        """
        if self.profile.side is None:
            return False
        if str(payload.get("shape") or "") != self.profile.shape:
            return False
        if str(payload.get("feed") or "").lower() not in self.profile.feeds:
            return False
        return _side_of(payload) is self.profile.side

    def decide(  # noqa: PLR0911 - one gate per return, in the order applied
        self, payload: dict[str, Any]
    ) -> Intent | Refusal | None:
        """A trade, or the reason there is not one. Never raises on a payload."""
        feed = str(payload.get("feed") or "")
        side = self.profile.side
        if side is None:
            return Refusal(gate="side", detail="this profile names no side", feed=feed)
        if _side_of(payload) is not side:
            return Refusal(gate="side", detail=f"not the {side.value} side", feed=feed)

        tick = self._tick()  # type: ignore[attr-defined]
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
        reward = target_r * risk
        if risk <= 0.0 or reward <= 0.0:
            return Refusal(gate="volatility", detail="a zero stop or target", feed=feed)

        # **The gate that decides this strategy**, before the geometry and
        # before sizing: a trade that cannot pay for its own round trip is not
        # a trade, whatever the rest of the arithmetic says. On an exotic a
        # round trip is 0.40 to 0.97 of a whole bar range, which ends most
        # ideas before they are measured.
        cost = tick.ask - tick.bid
        if cost > reward * self.profile.cost_share:
            return Refusal(
                gate="cost",
                detail=f"the round trip is {cost / reward:.0%} of the target, "
                f"limit is {self.profile.cost_share:.0%}",
                feed=feed,
            )
        # **And against the risk**, which is the denominator the damage was
        # measured in. The check above scales the permitted spread with the
        # target, so a distant target buys the right to pay more; this one does
        # not. 49 trades passed the reward test while expensive against risk,
        # at -0.471R and 53% stopped, for -502.70. The limit and the comparison
        # are in `domain/costs.py` rather than here, so this rule and
        # `strategies/surprise.py` cannot come to disagree about either - which
        # is what happened to the looser limit, where each file cited the other
        # as the place it was measured and neither held a measurement.
        if dear := costs.too_expensive(cost, risk, self.profile.spread_risk_share):
            return Refusal(gate="spread_risk", detail=dear, feed=feed)

        sign = side.sign
        spec = self._spec()  # type: ignore[attr-defined]
        return Intent(
            feed=feed,
            symbol=spec.symbol if spec is not None else feed,
            side=side,
            # Sized by `risk`, not here. Zero means "the sizer has not run",
            # and `place` refuses a zero rather than rounding it up.
            volume=_number(features.get("volume")),
            entry=entry,
            stop=entry - sign * risk,
            target=entry + sign * reward,
            reason=f"statespace surprise {surprise:.2f} on {feed}, {side.value} side",
            interval=str(payload.get("interval") or ""),
            confluence=("statespace:surprise", f"statespace:{self.profile.name}"),
            features={
                **{k: _number(v) for k, v in features.items()},
                "risk_share": self.profile.risk_share,
            },
            stop_vol=stop_vol,
            # The asymmetric exit. Every one of these is read off the intent
            # by `exits.Exits` and `manage`, so a per-side policy needs no
            # change in `strategies/`.
            break_even_at=self.profile.break_even_at,
            trail_vol=self.profile.trail_vol,
            trail_levels=self.profile.trail_levels,
            hold=self.profile.hold,
            stale_exempt=self.profile.stale_exempt,
        )


class LongSide(OneSided):
    """The long leaf's decision. Compose with an entry to get a strategy."""

    profile: ClassVar[type[SideProfile]] = LongProfile


class ShortSide(OneSided):
    """The short leaf's decision. Compose with an entry to get a strategy."""

    profile: ClassVar[type[SideProfile]] = ShortProfile


def _side_of(payload: dict[str, Any]) -> Side | None:
    """The side a proposal names, from `direction`, or None.

    `proposing.py` publishes `direction` as `+1` or `-1` - the sign of the
    triggering bar's body, which is the continuation side - and a doji takes
    no side rather than defaulting to long. A string `"up"`/`"down"` is also
    accepted, because that is what `Side.from_direction` reads and the signal
    contract carries both shapes across producers.
    """
    raw = payload.get("direction")
    if isinstance(raw, str):
        return Side.from_direction(raw)
    got = int(_number(raw))
    if got > 0:
        return Side.BUY
    return Side.SELL if got < 0 else None


__all__ = [
    "COST_SHARE",
    "STOP_VOL",
    "TARGET_R",
    "TRIGGER",
    "LongProfile",
    "LongSide",
    "OneSided",
    "ShortProfile",
    "ShortSide",
    "SideProfile",
]
