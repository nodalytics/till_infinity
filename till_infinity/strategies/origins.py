"""The origin zone as a tradeable rule, nominated two ways.

`indicators/levels.Origin` states the fact this module is built on: **an order
block, a displacement origin and a supply/demand zone are the same candle under
three names**, and `delivering.md` puts a fourth - this desk's own `Level` -
in the same table. They are "the last price at which the market changed its
mind", and the claim attached to every one of them is identical: price comes
back to that point and is rejected there.

So two rules here, and the difference between them is **not** the zone. It is
what has to have happened for a candle to be nominated as one:

* **`displacement-zones`** - the candle an impulsive chain left from. `PUSH_MIN`
  candles each with a body `PUSH_BODY` of its range, a chain that may step over
  `CHAIN_GAP` ordinary candles. This is the rule the desk specified over an
  afternoon in `zone-rules.md`.
* **`smc-zones`** - the same candle, nominated only when the move that left it
  also **broke structure** in that direction. The structure reading is
  `structure.Fold`, the same causal detector `smc-bos-causal` trades, rather
  than a second derivation of "the trend is up".

Keeping them apart is the point. `smc-primitives-overlap-and-are-closed`
records what happens when two named primitives turn out to be one event: a
range engulf already takes out the prior bar's high, so Candle Range Theory is
satisfied on 0.706 of engulfing bars **by construction**. Two rules whose zones
are the same object and whose nominators are the same test would be that again,
and the way to know is to run both and compare, which is what registering both
makes possible.

## What is measured, and what is not

**The zone population is measured and the fade is dead.** `displacement-origin.md`
established that the 82% return rate is a statement about *distance*: a
price-matched placebo the same distance away is reached just as often, on every
class. CLAUDE.md's Kills section is blunter - fade-to-value as a displacement
thesis had **0 of 105 cells** with a positive lower bound, and as a filter on
origins it read -0.007R over 2,786 trades at 1h, shrinking as the sample grew.
`order-block-zones.md` found "an 82% return rate and a losing read" on the same
object at 4h and 1d.

**So this rule is not that trade.** The fade enters *toward* the zone and aims
at it. What is nominated here is a **crossing** - price leaving the zone, or
closing through it - which is what `zones.py` says has never been settled: the
open question is whether a zone's own geometry, its width and its side, places
a better stop than a flat volatility distance. `stop-anchor.md` asked exactly
that of clusters and answered no; it has not been asked of origins.

Both signs ship, because `reject` and `break` are exact opposites and a rule
offering one would be asserting the sign of the family. `retest` and `flip` are
**refused** rather than approximated: they need a zone that remembers having
been broken, `Origin` does not carry that, and inventing a second derivation of
"broken" here would make a `retest` cell from this rule incomparable with the
one `zones.py` reports under the same name.

Enabling either one live needs a measurement this repository does not have.
Both are registered so that `TRADING_STRATEGIES=displacement-zones` is runnable
at all - `desks.build` refuses an unregistered name - which is the same footing
`vol-impulse` was registered on and for the same reason.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, ClassVar

from nautilus_trader.model.data import Bar

from ..domain.models import Intent, Refusal, Side
from ..indicators.levels import CHAIN_GAP, PUSH_BODY, PUSH_MIN, SPAN, Displacement, Origin
from .crossing import NEEDS_HISTORY, side_of
from .entries import ArrivalEntry, EdgeEntry, RestingEntry
from .exits import ManagedExit
from .profile import Profile
from .structure import Fold
from .warming import WarmFromHistory

#: The readings this nominator can offer. `reject` is the reversal and `break`
#: the continuation, so both signs are present; see the module docstring for
#: why the other two are refused rather than approximated.
MODES: tuple[str, ...] = ("reject", "break")

#: Stop distance in volatility units, matching `zones.py` so a result from one
#: rule and a result from the other differ by the nomination and not by the
#: stop. `risk-vol-is-not-the-stop-distance` is why this is named `stop_vol`.
DEFAULT_STOP_VOL = 3.0
DEFAULT_MODE = "reject"


def _float(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name) or fallback)
    except ValueError:
        return fallback


def _int(name: str, fallback: int) -> int:
    try:
        return int(float(os.environ.get(name) or fallback))
    except ValueError:
        return fallback


@dataclass(frozen=True, slots=True)
class Zone:
    """One origin, in the shape `crossing.side_of` reads.

    A thin adapter and deliberately not a second zone model: the band is
    `Origin`'s own high-to-low and the line is where the origin closed, both of
    which are the desk's specification recorded in `Origin`'s docstring.

    `flipped` is **always False**, which is why `MODES` here is two names and
    not four. A field that lied by defaulting to False would make `retest`
    silently return zero on every bar - a rule that validates, runs, and
    reports a cell nothing computed.
    """

    at: int
    bottom: float
    top: float
    level: float
    atr: float
    resistance: bool
    #: The leg that left this origin: signed size in price, and its rank.
    move: float
    rank: int
    breaks: int = 0
    flipped: bool = False

    @classmethod
    def of(cls, origin: Origin, atr: float) -> Zone:
        """Adapt one `Origin`. **`side` +1 is demand, so it is support.**

        The inversion is worth stating where it happens: `Origin.side` is the
        direction of the leg that left the candle, so an up leg leaves a zone
        *below* price that price may return to and bounce from. Reading it as
        resistance would trade every one of these backwards, and the sign would
        still print.
        """
        return cls(
            at=int(origin.when),
            bottom=float(origin.low),
            top=float(origin.high),
            level=float(origin.line),
            atr=float(atr),
            resistance=origin.side < 0,
            move=float(origin.move),
            rank=int(origin.rank),
        )


@dataclass(frozen=True, slots=True)
class Tuning:
    """What a sweep varies, read from the environment on every call.

    Per call and not at import, because a sweep sets the environment per cell
    inside one process and a value captured at import would run every cell as
    the first one.
    """

    mode: str = DEFAULT_MODE
    stop_vol: float = DEFAULT_STOP_VOL
    span: int = SPAN
    push_min: int = PUSH_MIN
    push_body: float = PUSH_BODY
    chain_gap: int = CHAIN_GAP
    #: Keep each signal with this probability, dropping the rest at random.
    #: **The duty-cycle control, and it is not optional.** On a net-negative
    #: book any rule that trades less shows a profit improvement, so a headline
    #: without this carries no information about the rule. Every pause rule
    #: ever proposed here beat its baseline and none beat its own random twin.
    duty: float = 1.0

    @classmethod
    def read(cls) -> Tuning:
        mode = (os.environ.get("TRADING_ORIGIN_MODE") or DEFAULT_MODE).strip().lower()
        if mode in NEEDS_HISTORY:
            raise ValueError(
                f"{mode!r} needs a zone that remembers having been broken, and a "
                f"displacement origin does not carry that. This rule offers "
                f"{', '.join(MODES)}; `zones` offers all four on Bjorgum levels, "
                f"whose zones track their own breaks."
            )
        if mode not in MODES:
            raise ValueError(f"{mode!r} is not a mode: {', '.join(MODES)}.")
        return cls(
            mode=mode,
            stop_vol=_float("TRADING_ORIGIN_STOP_VOL", DEFAULT_STOP_VOL),
            span=_int("TRADING_ORIGIN_SPAN", SPAN),
            push_min=_int("TRADING_ORIGIN_PUSH_MIN", PUSH_MIN),
            push_body=_float("TRADING_ORIGIN_PUSH_BODY", PUSH_BODY),
            chain_gap=_int("TRADING_ORIGIN_CHAIN_GAP", CHAIN_GAP),
            duty=_float("TRADING_ORIGIN_DUTY", 1.0),
        )

    def build(self) -> Displacement:
        return Displacement(
            span=self.span,
            push_min=self.push_min,
            push_body=self.push_body,
            chain_gap=self.chain_gap,
        )


class OriginProfile(Profile):
    """The rule's identity. Built with `__new__`, as every other profile is:
    configuration is shared between instances on two instruments."""

    name: ClassVar[str] = "displacement-zones"
    description: ClassVar[str] = "the candle an impulsive chain left from, traded on a crossing"
    #: Its own shape, so a proposal from another producer on the same bus is
    #: skipped rather than counted as unwanted.
    shape: ClassVar[str] = "origin-zones"
    style: ClassVar[str] = "swing"
    #: The clock `displacement-origin.md` and `order-block-zones.md` measured
    #: the origin population on. `Desk.interval` is what a fanned-out desk
    #: actually trades and `Desk._say_clock` reports the difference.
    interval: ClassVar[str] = "4h"
    hold_bars: ClassVar[float] = 0.0
    hold_seconds: ClassVar[float] = 0.0
    #: Bars of history to warm `Displacement` with on start.
    #:
    #: `SPAN` is 40 bars and an origin needs an impulsive chain inside that
    #: window, so a cold desk cannot nominate a zone for ten hours on 15m and
    #: six days on 4h - the clock this rule's numbers were measured on. 400
    #: gives the window several turnovers.
    warm_bars_request: ClassVar[int] = 400
    #: Zero, for the reason `ZoneProfile.warm_fresh_bars` gives: a crossing is
    #: a transition between two bars rather than an event with a timestamp, so
    #: a replayed crossing is one this rule has already passed on. The warm
    #: pass is for the detector, not for the signal.
    warm_fresh_bars: ClassVar[int] = 0


class StructureProfile(OriginProfile):
    """`smc-zones`: the same zone, nominated only behind a break of structure."""

    name: ClassVar[str] = "smc-zones"
    description: ClassVar[str] = "an origin whose leg also broke structure, traded on a crossing"
    shape: ClassVar[str] = "smc-zones"


class Origins(WarmFromHistory):
    """Origin crossings into orders. A mixin; the leaves below compose it."""

    profile: ClassVar[OriginProfile] = OriginProfile.__new__(OriginProfile)
    #: Whether a break of structure in the zone's direction is required before
    #: the zone may be traded. False is `displacement-zones`.
    confirms: ClassVar[bool] = False

    def on_start(self) -> None:
        """Build the detectors and register them, then start the desk.

        Registration before `super()`, which subscribes: the two orders are
        indistinguishable on a live feed and differ in a backtest, which
        delivers the first bar immediately.
        """
        self.tuning = Tuning.read()
        self.displacement = self.tuning.build()
        self.register_indicator_for_bars(self._cfg.bar_type, self.displacement)
        #: The causal structure reading, fed by hand rather than registered:
        #: `Fold.update` takes three floats and is not a Nautilus indicator.
        #: Built for both rules so the tally can report what the gate would
        #: have done, and consulted only when `confirms`.
        self.fold = Fold()
        #: Whether price was inside each zone on the previous bar, keyed by the
        #: origin's close time. A *crossing* is the signal and not a state.
        self.inside: dict[int, bool] = {}
        #: The side this rule last proposed, so an opposing signal can close
        #: what the previous one opened. Without it the only exit is the stop
        #: and the win rate is 0.00 by construction, which is what the first
        #: run of the Bjorgum rule measured on all 15 of its `break` positions.
        self.standing = 0
        self.counts: dict[str, int] = {"bars": 0, "signals": 0, "unwarmed": 0}
        super().on_start()
        # After `super()`, which subscribes: a request issued before the
        # subscription can have its response delivered to a strategy that is
        # not yet listening for one.
        self.start_warming()

    def warm_bar(self, bar: Bar) -> None:
        """Fold one historical bar into both detectors, and never propose.

        **`Fold` is fed here too, not only `Displacement`.** `smc-zones` gates
        on structure, so a warm pass that advanced the zone nominator and left
        the structure reading cold would make every early live crossing read as
        `unconfirmed` - a rule refusing itself for ten hours and counting it as
        a gate rather than as a warm-up.

        The `inside` book is built for the same reason `zones.py` builds it: a
        crossing is the transition between two bars, so leaving it empty would
        make the first live bar look like a crossing of every zone price
        happened to be outside.
        """
        self.displacement.handle_bar(bar)
        self.fold.update(float(bar.high), float(bar.low), float(bar.close))
        self.counts["bars"] += 1
        if not self.displacement.initialized:
            self.counts["unwarmed"] += 1
            return
        close = float(bar.close)
        for zone in self._zones(self.displacement.scale):
            self.inside[zone.at] = zone.bottom <= close <= zone.top

    def on_bar(self, bar: Bar) -> None:
        """One closed bar, and any origin crossing it produced.

        Nautilus updates every registered indicator before this runs, so
        `self.displacement` is as of this bar's close. `Fold` is updated here
        because it is not an indicator, and **before** the zones are read, so
        the structure gate sees this bar too rather than the previous one.
        """
        super().on_bar(bar)
        self.counts["bars"] += 1
        self.fold.update(float(bar.high), float(bar.low), float(bar.close))
        if not self.displacement.initialized:
            self.counts["unwarmed"] += 1
            return

        close = float(bar.close)
        atr = self.displacement.scale
        for zone in self._zones(atr):
            was = self.inside.get(zone.at)
            now = zone.bottom <= close <= zone.top
            self.inside[zone.at] = now
            if was is None:
                continue
            side = side_of(zone, self.tuning.mode, was=was, now=now, close=close, seen=False)
            if side == 0:
                continue
            if self.confirms and not self._confirmed(side):
                self.counts["unconfirmed"] = self.counts.get("unconfirmed", 0) + 1
                continue
            if self.standing != 0 and side == -self.standing:
                self._leave(side)
            self.standing = side
            if self.tuning.duty < 1.0 and not self._kept(zone, bar):
                self.counts["duty_dropped"] = self.counts.get("duty_dropped", 0) + 1
                continue
            self.counts["signals"] += 1
            # Through `on_data` and not `consider`, because that is where the
            # desk counts what it took and follows what it declined.
            self.on_data(self._payload(side, zone, bar))
            return

        # `Displacement` keeps `ORIGIN_KEEP` origins per leg over a bounded
        # window, so an unbounded dict here would be a slow leak on a long run
        # rather than a visible one.
        live = {zone.at for zone in self._zones(atr)}
        for gone in [at for at in self.inside if at not in live]:
            del self.inside[gone]

    def _zones(self, atr: float) -> list[Zone]:
        """Every live origin, adapted. Nearest leg first, as `origins` orders."""
        return [Zone.of(origin, atr) for origin in self.displacement.origins]

    def _confirmed(self, side: int) -> bool:
        """Whether structure agrees with the side this crossing proposes.

        **`Fold.trend` and not a slope or a moving average**, because that is
        the reading `smc-bos-causal` is written in and a second derivation of
        "the trend is up" would make this rule's results incomparable with its.
        A trend of 0 is "neither established yet", which is a refusal rather
        than a pass: the whole claim of the SLK and EMS frameworks is that the
        higher-level bias is what makes the conjunction worth taking.
        """
        return self.fold.trend == side

    def _kept(self, zone: Zone, bar: Bar) -> bool:
        """Whether this signal survives the duty-cycle draw.

        Deterministic in `(feed, zone, bar)` rather than drawn from a running
        generator, so the same cell re-run drops the same signals. A sweep that
        seeded once per process would give each cell a different draw and the
        comparison would be against a different twin each time.
        """
        key = f"{self._feed_name()}|{zone.at}|{bar.ts_event}|{self.tuning.duty}"
        digest = hashlib.sha256(key.encode()).digest()
        draw = int.from_bytes(digest[:8], "big") / float(1 << 64)
        return draw < self.tuning.duty

    def _leave(self, side: int) -> None:
        """Flatten what the previous signal opened, because this one disagrees.

        Through `ExitMechanism._close` and the desk's own registry: that is the
        one latched close path, so a position this rule and the stop both ask
        for in the same instant is flattened once.
        """
        for position_id in tuple(self.exits.positions):
            position = self.cache.position(position_id)
            if position is None or position.is_closed:
                continue
            if self._close(position_id, f"a {side:+d} origin signal reversed it"):
                self.counts["closed_on_turn"] = self.counts.get("closed_on_turn", 0) + 1

    def _payload(self, side: int, zone: Zone, bar: Bar) -> dict[str, Any]:
        """The crossing as the payload `Desk.consider` reads."""
        return {
            "feed": self._feed_name(),
            "shape": self.profile.shape,
            "interval": self.interval or self.profile.interval,
            "direction": side,
            "features": {
                # `zone_atr` with `zone_close` as its anchor, **not** `vol_bps`:
                # that column is a folded log variance elsewhere on this desk
                # and an ATR in it would put one journal column in two
                # estimators. `exits._trail_vol_bps` converts any `*_atr` that
                # carries its own `*_close`.
                "zone_atr": float(zone.atr),
                "zone_close": float(bar.close),
                "zone_top": float(zone.top),
                "zone_bottom": float(zone.bottom),
                "zone_level": float(zone.level),
                "zone_width": float(zone.top - zone.bottom),
                "zone_resistance": 1.0 if zone.resistance else 0.0,
                "zone_stop_vol": self.tuning.stop_vol,
                # The leg that left the origin, so a sweep can ask whether a
                # bigger displacement leaves a better zone. Reported, untested.
                "origin_move": float(zone.move),
                "origin_rank": float(zone.rank),
                "origin_trend": float(self.fold.trend),
            },
        }

    def wants(self, payload: dict[str, Any]) -> bool:
        return str(payload.get("shape") or "") == self.profile.shape

    def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """The crossing as an order, or a refusal naming the gate."""
        feed = str(payload.get("feed") or "")
        sign = int(payload.get("direction") or 0)
        if sign == 0:
            return Refusal(gate="direction", detail="the crossing took no side", feed=feed)
        side = Side.BUY if sign > 0 else Side.SELL

        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal(gate="features", detail="no features on the crossing", feed=feed)
        atr = float(features.get("zone_atr") or 0.0)
        if atr <= 0.0:
            return Refusal(gate="atr", detail=f"the origin scale reads {atr:.6g}", feed=feed)

        tick = self._tick()
        if tick is None:
            return Refusal(gate="no-quote", detail=f"{feed} has no cached quote", feed=feed)
        entry = tick.ask if side is Side.BUY else tick.bid
        if entry <= 0.0:
            return Refusal(gate="bad-quote", detail=f"{feed} quoted {entry}", feed=feed)

        reach = float(features.get("zone_stop_vol") or DEFAULT_STOP_VOL) * atr
        if reach <= 0.0:
            return Refusal(gate="stop", detail="a zero stop distance", feed=feed)

        return Intent(
            feed=feed,
            symbol=self._cfg.instrument_id.symbol.value,
            # Zero: `Desk.consider` sizes it. Two places computing a size is
            # how they come to disagree.
            volume=0.0,
            side=side,
            entry=entry,
            stop=entry - sign * reach,
            # **No target.** The fade that aimed at this zone is dead - 0 of
            # 105 cells with a positive lower bound - and a target invented
            # here would be that trade with better arithmetic.
            target=0.0,
            reason=(
                f"{self.tuning.mode} of a "
                f"{'supply' if features.get('zone_resistance') else 'demand'} origin "
                f"{'up' if side is Side.BUY else 'down'} on {feed}"
            ),
            interval=self.interval or self.profile.interval,
            features={str(k): float(v) for k, v in features.items()},
            hold=0.0,
        )


class OriginsEdge(Origins, ManagedExit, EdgeEntry):
    """An origin crossing taken at market."""


class OriginsResting(Origins, ManagedExit, RestingEntry):
    """An origin crossing left as a limit at the price it named."""


class OriginsArrival(Origins, ManagedExit, ArrivalEntry):
    """An origin crossing parked until price returns and a bar confirms."""


class SmcZones(Origins):
    """The same zone, behind a break of structure."""

    profile: ClassVar[StructureProfile] = StructureProfile.__new__(StructureProfile)
    confirms: ClassVar[bool] = True


class SmcZonesEdge(SmcZones, ManagedExit, EdgeEntry):
    """A confirmed origin crossing taken at market."""


class SmcZonesResting(SmcZones, ManagedExit, RestingEntry):
    """A confirmed origin crossing left as a limit at the price it named."""


class SmcZonesArrival(SmcZones, ManagedExit, ArrivalEntry):
    """A confirmed origin crossing parked until price returns and a bar confirms."""
