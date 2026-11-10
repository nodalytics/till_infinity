"""Bjorgum key levels as a tradeable rule, with its asymmetry exposed.

`indicators/levels.BjorgumLevels` has had no caller in `till_infinity/`. It
carries the asymmetry this desk keeps asking for and nothing reads it:

* **`left` and `right` are separate**, defaulting to 20 and 15, so the pivot
  window is already asymmetric in time - a swing is confirmed by fewer bars
  after it than before.
* **`mult` is a `Sided`**, so a resistance zone and a support zone need not be
  the same width, with the geometric mean held at `shared` whatever the tilt.
  A tilt of 1 is exactly neutral, which is what makes the asymmetry separable
  from the average - `refit-the-parameter-a-lever-multiplies` records a
  multiplier whose mean was not 1 reversing a +1192 result to -24 by moving
  the average instead.
* **`pivots` offers three sources**, and the two this desk keeps comparing are
  among them: `HIGH_LOW` is the wick as the venue printed it and
  `HIGH_LOW_BODY` is `max(open, close)` / `min(open, close)`, a level where
  the auction settled rather than where it reached. On an instrument whose
  round trip is a whole bar range - the exotics measured at **0.40 to 0.97**
  of one - the wick is partly spread.

## Two presets that must not be mixed

`BjorgumLevels()` is the published script: 20/15, ATR 30, four zones a side,
Heikin-Ashi bodies. `BjorgumLevels.measured()` is what `bjorgum.md` was run
on: symmetric 5/5, ATR 14, ten zones a side, raw high/low. Both are reachable
and neither is a silent default, because mixing them gives numbers belonging
to neither configuration - which is how a figure ends up quoted for a run it
never had. `TRADING_ZONE_PRESET` picks one and every other knob overrides it.

## What this rule is for

**The exit and the asymmetry, not a direction claim.** `magnet.md` measured a
level reached 44.9% of the time against **49.5% for an arbitrary price the
same distance away**, and `level-shield.md` found the entry side closed with
real below its hardest null in 188 of 210 cells. So a zone is not expected to
predict; what is untested is whether the *zone's own geometry* - its width,
its side, its break count - places a better stop than a flat volatility
distance, which is the question `stop-anchor.md` asked of clusters and
answered no for.

Both signal forms are offered because the sign is the thing nobody has pinned:
`reject` trades price turning at a zone and `break` trades price leaving it,
and they are exact opposites. A rule that only ships one is asserting the sign.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, ClassVar

from nautilus_trader.model.data import Bar

from ..domain.models import Intent, Refusal, Side
from ..indicators.levels import BjorgumLevels, PivotSource, Sided
from .crossing import side_of
from .entries import ArrivalEntry, EdgeEntry, RestingEntry
from .exits import ManagedExit
from .profile import Profile

#: The two published configurations. `script` is `BjorgumLevels()`'s own
#: defaults; `measured` is what every number in `bjorgum.md` was run on.
PRESETS: tuple[str, ...] = ("script", "measured")

#: The four readings a key level offers, and they are not variations - two
#: are **reversal** trades and two are **continuation** trades, so a rule that
#: ships one is asserting the sign of the whole family.
#:
#: * `reject` - price enters the zone and leaves back the way it came.
#:   **Reversal.** The zone held.
#: * `break` - price closes through the zone from outside. **Continuation.**
#:   The zone failed.
#: * `retest` - price broke the zone earlier, has returned to it, and leaves
#:   again on the break side. **Continuation**, and the one with a published
#:   null to beat: `lrc-retest.md` measured a break-and-retest setup at
#:   **-0.291R over 167,501 trades against walks at -0.274**, on a different
#:   level type. Included because the claim here is a different level, not a
#:   tuning of that one, and because excluding it would leave the family's
#:   most-traded form unmeasured.
#: * `flip` - the bar on which a zone's role changes, resistance becoming
#:   support or the reverse. **Continuation** of whatever broke it.
#:   `Zone.flipped` carries it and its own docstring says "a 15m effect that
#:   does not survive to 4h. Reported, not trusted."
MODES: tuple[str, ...] = ("reject", "break", "retest", "flip")

#: What an opposing signal does to a held position.
#:
#: **`close` is not a refinement, it is the difference between a rule and a
#: one-sided accounting of stops.** With no target and no hold clock the only
#: exit is the stop, so the win rate is 0.00 by construction - which is what
#: the first run of this rule measured on all 15 positions of its `break` mode.
#: `bands.py` measured the same thing and the same fix took `ema` from -160.27
#: at 7 positions to +100.78 at 57.
EXITS_ON: tuple[str, ...] = ("close", "hold")

DEFAULT_STOP_VOL = 3.0
DEFAULT_MODE = "reject"
DEFAULT_PRESET = "script"


def _opposite(raw: str | None) -> str:
    name = (raw or "close").strip().lower()
    if name not in EXITS_ON:
        raise ValueError(f"{name!r} is not an opposite-signal policy: {', '.join(EXITS_ON)}.")
    return name


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
class Tuning:
    """What a sweep varies, read from the environment on every call.

    **Per call and not at import**, because a sweep sets the environment per
    cell inside one process and a value captured at import would run every
    cell as the first one.
    """

    preset: str = DEFAULT_PRESET
    mode: str = DEFAULT_MODE
    pivots: str = PivotSource.HA.value
    #: `0` keeps the preset's own value, so a sweep can vary one knob without
    #: silently pinning the rest to this module's opinion.
    left: int = 0
    right: int = 0
    atr_len: int = 0
    mult: float = 0.0
    #: Resistance-to-support ratio for the zone width, in `Sided`'s sense.
    mult_tilt: float = 1.0
    stop_vol: float = DEFAULT_STOP_VOL
    stop_tilt: float = 1.0
    #: What an opposing signal does to a held position. See `EXITS_ON`.
    on_opposite: str = "close"
    #: Keep each signal with this probability, dropping the rest at random.
    #: **The duty-cycle control, and it is not optional for this rule.**
    #:
    #: `zones-traded.md` measured the `script` preset beating `measured` on 64%
    #: of paired cells - and trading **half as much**, median 88 positions
    #: against 165. The `finding-edges` skill's standing rule is that on a
    #: net-negative book *any* rule that trades less shows a profit
    #: improvement, so a preset that trades less cannot be told from a preset
    #: that is better without a twin that trades less at random at the same
    #: rate. Every pause rule ever proposed here beat its baseline and none
    #: beat its own random twin, at p 0.45 to 0.51.
    #:
    #: Seeded from the feed, the zone and the bar so a cell is reproducible:
    #: an unseeded drop would make two runs of the same cell different trades
    #: and the comparison meaningless.
    duty: float = 1.0
    #: Require the zone to have been visited this many times before trading
    #: it. **Reported as a swept parameter and not as a gate on a prior**:
    #: `gap-levels.md` measured `drawn_by_n` - how many passes agree on a
    #: price - failing as a filter, and `Zone.proven` ("three to five prior
    #: visits") is the same shape of claim. Sweeping it is how it gets scored
    #: rather than assumed.
    min_tested: int = 0

    @classmethod
    def read(cls) -> Tuning:
        preset = (os.environ.get("TRADING_ZONE_PRESET") or DEFAULT_PRESET).strip().lower()
        if preset not in PRESETS:
            raise ValueError(f"{preset!r} is not a preset: {', '.join(PRESETS)}.")
        mode = (os.environ.get("TRADING_ZONE_MODE") or DEFAULT_MODE).strip().lower()
        if mode not in MODES:
            raise ValueError(f"{mode!r} is not a mode: {', '.join(MODES)}.")
        source = (os.environ.get("TRADING_ZONE_PIVOTS") or PivotSource.HA.value).strip().lower()
        if source not in {s.value for s in PivotSource}:
            known = ", ".join(s.value for s in PivotSource)
            raise ValueError(f"{source!r} is not a pivot source: {known}.")
        return cls(
            preset=preset,
            mode=mode,
            pivots=source,
            left=max(0, _int("TRADING_ZONE_LEFT", 0)),
            right=max(0, _int("TRADING_ZONE_RIGHT", 0)),
            atr_len=max(0, _int("TRADING_ZONE_ATR", 0)),
            mult=max(0.0, _float("TRADING_ZONE_MULT", 0.0)),
            mult_tilt=max(1e-6, _float("TRADING_ZONE_MULT_TILT", 1.0)),
            stop_vol=max(0.0, _float("TRADING_ZONE_STOP_VOL", DEFAULT_STOP_VOL)),
            stop_tilt=max(1e-6, _float("TRADING_ZONE_STOP_TILT", 1.0)),
            on_opposite=_opposite(os.environ.get("TRADING_ZONE_ON_OPPOSITE")),
            duty=min(1.0, max(0.0, _float("TRADING_ZONE_DUTY", 1.0))),
            min_tested=max(0, _int("TRADING_ZONE_MIN_TESTED", 0)),
        )

    def stop_for(self, sign: int) -> float:
        """The stop multiple on one side, geometric mean preserved."""
        root = self.stop_tilt**0.5
        return self.stop_vol * root if sign > 0 else self.stop_vol / root

    def build(self) -> BjorgumLevels:
        """The indicator this cell asks for.

        The preset is applied first and the explicit knobs override it, so a
        sweep that varies only `mult_tilt` leaves every other number at the
        configuration it named rather than at this module's defaults.
        """
        kwargs: dict[str, Any] = {"pivots": self.pivots}
        if self.left:
            kwargs["left"] = self.left
        if self.right:
            kwargs["right"] = self.right
        if self.atr_len:
            kwargs["atr_len"] = self.atr_len
        shared = self.mult or None
        if self.preset == "measured":
            found = BjorgumLevels.measured(**kwargs)
            shared = shared or float(found.mult.shared)
            kwargs["mult"] = Sided(shared=shared, tilt=self.mult_tilt)
            return BjorgumLevels.measured(**kwargs)
        probe = BjorgumLevels(**kwargs)
        shared = shared or float(probe.mult.shared)
        kwargs["mult"] = Sided(shared=shared, tilt=self.mult_tilt)
        return BjorgumLevels(**kwargs)


class ZoneProfile(Profile):
    """The rule's identity. Built with `__new__`, as every other profile is:
    configuration is shared between instances on two instruments."""

    name: ClassVar[str] = "zones"
    description: ClassVar[str] = "bjorgum key levels, both signs, per-side widths"
    #: Its own shape, so a proposal from another producer on the same bus is
    #: skipped rather than counted as unwanted.
    shape: ClassVar[str] = "zones"
    style: ClassVar[str] = "swing"
    interval: ClassVar[str] = "15m"
    hold_bars: ClassVar[float] = 0.0
    hold_seconds: ClassVar[float] = 0.0


class Zones:
    """Bjorgum zones into orders. A mixin; the leaves below compose it."""

    profile: ClassVar[ZoneProfile] = ZoneProfile.__new__(ZoneProfile)

    def on_start(self) -> None:
        """Build the indicator and register it, then start the desk.

        Registration before `super()`, which subscribes: the two orders are
        indistinguishable on a live feed and differ in a backtest, which
        delivers the first bar immediately.
        """
        self.tuning = Tuning.read()
        self.levels = self.tuning.build()
        self.register_indicator_for_bars(self._cfg.bar_type, self.levels)
        #: Whether price was inside each zone on the previous bar, keyed by the
        #: zone's pivot bar. A *crossing* is the signal, not a state: a rule
        #: that fires on every bar price sits in a zone re-proposes a held
        #: position on every bar, and the desk refuses it as already held -
        #: which reads as a gate count rather than as the design error it is.
        self.inside: dict[int, bool] = {}
        #: Whether each zone had already flipped. `flip` needs the **edge**,
        #: and `Zone.flipped` is a state that stays true once set.
        self.flipped: dict[int, bool] = {}
        #: The side this rule last proposed, so an opposing signal can close
        #: what the previous one opened. Without it the only exit is the stop
        #: and the win rate is 0.00 by construction, which is what the first
        #: run of this rule measured on all 15 of its `break` positions.
        self.standing = 0
        self.counts: dict[str, int] = {"bars": 0, "signals": 0, "unwarmed": 0}
        super().on_start()

    def on_bar(self, bar: Bar) -> None:
        """One closed bar, and any zone crossing it produced.

        Nautilus updates every registered indicator before this runs, so
        `self.levels` is as of this bar's close.
        """
        super().on_bar(bar)
        self.counts["bars"] += 1
        if not self.levels.initialized:
            self.counts["unwarmed"] += 1
            return

        close = float(bar.close)
        for zone in self.levels.zones:
            was = self.inside.get(zone.at)
            now = zone.bottom <= close <= zone.top
            self.inside[zone.at] = now
            if was is None:
                continue
            side = self._side(zone, was=was, now=now, close=close)
            self.flipped[zone.at] = bool(zone.flipped)
            if side == 0:
                continue
            if self.tuning.on_opposite == "close" and self.standing != 0 and side == -self.standing:
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

        # Zones that have been evicted keep no state: `keep` bounds the book at
        # four or ten a side, so an unbounded dict here would be a slow leak on
        # a long run rather than a visible one.
        live = {zone.at for zone in self.levels.zones}
        for gone in [at for at in self.inside if at not in live]:
            del self.inside[gone]
        for gone in [at for at in self.flipped if at not in live]:
            del self.flipped[gone]

    def _kept(self, zone: Any, bar: Bar) -> bool:
        """Whether this signal survives the duty-cycle draw.

        Deterministic in `(feed, zone, bar)` rather than drawn from a running
        generator, so the same cell re-run drops the same signals. A sweep that
        set a seed once per process would give each of its cells a different
        draw and the comparison would be against a different twin each time.
        """
        import hashlib

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
            if self._close(position_id, f"a {side:+d} zone signal reversed it"):
                self.counts["closed_on_turn"] = self.counts.get("closed_on_turn", 0) + 1

    def _side(self, zone: Any, *, was: bool, now: bool, close: float) -> int:
        """Which way this zone reads on this bar: +1, -1 or 0.

        **The scoring is `crossing.side_of` and is shared**, because an order
        block, a displacement origin and a Bjorgum key level are one hypothesis
        with several nominators - `delivering.md` puts the four names in a
        table - so a reading taken here and a reading taken by
        `strategies/origins.py` have to be the same function or they are not
        comparable. What stays with this rule is the *nomination*: which prices
        are zones at all.
        """
        return side_of(
            zone,
            self.tuning.mode,
            was=was,
            now=now,
            close=close,
            seen=bool(self.flipped.get(zone.at)),
        )

    def _payload(self, side: int, zone: Any, bar: Bar) -> dict[str, Any]:
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
                "zone_breaks": float(zone.breaks),
                "zone_stop_vol": self.tuning.stop_for(side),
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
            return Refusal(gate="atr", detail=f"the zone ATR reads {atr:.6g}", feed=feed)

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
            # **No target.** `EdgeEntry` submits the entry alone on a zero and
            # attaches the stop from `on_order_filled`; a target invented here
            # would be a different rule with better arithmetic, which is what
            # `a-martingale-cannot-pay` is about.
            target=0.0,
            reason=(
                f"{self.tuning.mode} of a "
                f"{'resistance' if features.get('zone_resistance') else 'support'} zone "
                f"{'up' if side is Side.BUY else 'down'} on {feed}"
            ),
            interval=self.interval or self.profile.interval,
            features={str(k): float(v) for k, v in features.items()},
            hold=0.0,
        )


class ZonesEdge(Zones, ManagedExit, EdgeEntry):
    """A zone crossing taken at market."""


class ZonesResting(Zones, ManagedExit, RestingEntry):
    """A zone crossing left as a limit at the price it named."""


class ZonesArrival(Zones, ManagedExit, ArrivalEntry):
    """A zone crossing parked until price returns and a bar confirms."""
