"""The level strategies: what to do with a call when one arrives.

`structures` publishes a `LEVEL` signal when price reaches somewhere it has
repeatedly turned and the history says which way it goes from there. The signal
carries a price, a direction, a probability against its own base rate, the push
it expects and the risk it runs - the last two in volatility units - and says
nothing about how to trade any of it.

`LevelStrategy` is that translation, done once. The two registered strategies
below differ only in which calls they accept and how they place the stop and
target; neither adds an indicator, for the reason given in `strategy`.

**Thresholds here are higher than the ones upstream, on purpose.** A signal on
the bus has already passed `actionable`, which is the bar for telling a person.
Putting money on it is a different question with a different cost of being
wrong, so `min_probability` and `min_edge` are set separately and set higher.

**A missing field is a refusal, never a default.** A call with no `vol_bps`
cannot have its volatility units turned into a price. Substituting a plausible
constant would put the stop somewhere nobody chose, and would do it silently.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from ..models import Intent, Refusal, Side, SymbolSpec, Tick, Verdict
from ..sizing import lots, price_distance, respects_stops_level, stop_for, target_for
from ..speeds import Speeds
from .strategy import Strategy, register


def _number(features: dict[str, Any], name: str, default: float = 0.0) -> float:
    value = features.get(name, default)
    return float(value) if isinstance(value, int | float) else default


def _features(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("features")
    if not isinstance(raw, dict):
        return {}
    return {k: float(v) for k, v in raw.items() if isinstance(v, int | float)}


def _confluence(payload: dict[str, Any]) -> tuple[str, ...]:
    raw = payload.get("confluence")
    return tuple(str(t) for t in raw) if isinstance(raw, list) else ()


@dataclass(frozen=True, slots=True)
class Aim:
    """Everything a strategy needs to place a target, gathered once.

    A parameter object rather than eight arguments, because the two overrides
    that exist use different halves of it and the signature would otherwise
    have to grow every time a third one wants something else.
    """

    payload: dict[str, Any]
    features: dict[str, float]
    spec: SymbolSpec
    side: Side
    #: The level the call was made at, which is what the stop is anchored to.
    level: float
    entry: float
    vol_bps: float
    #: The expected push, already a price distance.
    push: float


class LevelStrategy(Strategy):
    """Everything common to trading a level call.

    Subclasses override `accept` to narrow which calls they take, and
    `distances` to place the stop and target differently. The order of the
    checks in `consider` is not arbitrary - the cheap refusals about the signal
    come before the arithmetic, and the arithmetic comes before anything that
    would need the broker.
    """

    shape: ClassVar[str] = "level"
    #: Whether this strategy is allowed to flip to the better side of a
    #: pullback when the opposite geometry is materially cleaner. Default off:
    #: the plain level trade is not a direction-flip strategy.
    reverse_if_better: ClassVar[bool] = False
    #: Multiplied into the stop distance. A subclass that wants more room says
    #: so here rather than reimplementing the placement.
    stop_multiple: ClassVar[float] = 1.0
    target_multiple: ClassVar[float] = 1.0

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        """Extra conditions beyond the shared ones. None means take it."""
        return None

    #: Longest hold for which the tightened parked stop still applies.
    #:
    #: The grid that produced it was scored over touch resolutions whose median
    #: life is **eighteen seconds** and 84% of which finish inside five
    #: minutes. A 0.5v stop is right for a trade on that horizon. Applied to
    #: one held for half an hour it is half of a single bar against roughly 5.5
    #: units of wandering - the exact mistake `stop_hold_scaling` exists to
    #: correct, made worse.
    PARKED_STOP_HOLD: ClassVar[float] = 300.0

    def _parked_stop(
        self, features: dict[str, float], level: float, vol_bps: float, interval: str = ""
    ) -> float:
        """The tightened stop distance for an entry that waited, or 0.

        See `strategies-scalper.md` in research/docs.
        """
        want = self.settings.parked_stop_vol
        if want <= 0 or not features.get("after_pullback"):
            return 0.0
        if self.hold_for(interval) > self.PARKED_STOP_HOLD:
            return 0.0
        return price_distance(level, vol_bps, want)

    def momentum_scale(self, features: dict[str, float], side: Side) -> float:
        """Size multiplier for whether momentum is confirming this trade.

        See `trading-strategies-scalper.md` in research/docs.
        """
        share = self.settings.unconfirmed_size
        if share >= 1.0 or share <= 0:
            return 1.0
        pressure = features.get("pressure_vol")
        if pressure is None:
            return 1.0  # no reading is not the same as no confirmation
        with_trade = float(pressure) if side is Side.BUY else -float(pressure)
        return 1.0 if with_trade > 0 else share

    def conviction_scale(self, features: dict[str, float], side: Side) -> float:
        """Size multiplier from how well supported this particular call is.

        See `trading-strategies-scalper.md` in research/docs.
        """
        return 1.0

    def trend_scale(self, features: dict[str, float]) -> float:
        """Size multiplier from the trend context. 1.0 when off or unknown.

        Applied to `risk_fraction` rather than to the lot count, so every cap
        downstream still binds - `max_risk_money`, the volume step, the broker
        limits. A multiplier that bypassed those would be a way to exceed the
        risk budget through a setting nobody reads as a risk setting.
        """
        span = self.settings.trend_sizing
        if span <= 0:
            return 1.0
        ratio = features.get("efficiency")
        if ratio is None:
            return 1.0
        return 1.0 + span * (2.0 * float(ratio) - 1.0)

    def orient(self, side: Side) -> Side:
        """Which way to actually trade, given the side the call named.

        Identity for everything except `inverse`. A hook rather than an
        override of `consider`, because an override is how `fade-to-value`
        came to run none of the shared gates while reading, from the
        configuration, as though it ran all of them.
        """
        return side

    def _reward_to_risk(
        self,
        payload: dict[str, Any],
        features: dict[str, float],
        side: Side,
        interval: str,
        spec: SymbolSpec,
        tick: Tick,
    ) -> float:
        """The trade's reward-to-risk on the side we are actually judging.

        Every strategy here is allowed to be more selective than the model, but
        it is not allowed to ignore the model's own geometry. This is the
        comparison the opposite-side optimization uses before it reverses a
        setup, and it is intentionally based on the same stop and target maths
        the order itself would use.
        """
        if not features:
            return 0.0
        level = _number(features, "level")
        vol_bps = _number(features, "vol_bps")
        risk_vol = abs(_number(features, "risk_vol"))
        push_vol = abs(_number(features, "expected_push_vol"))
        if level <= 0 or vol_bps <= 0 or risk_vol <= 0 or push_vol <= 0:
            return 0.0

        entry = tick.entry(side)
        risk_distance, push_distance = self.distances(
            level,
            entry,
            vol_bps,
            risk_vol,
            push_vol,
            interval,
            features=features,
            side=side,
        )
        unit = price_distance(level, vol_bps, 1.0)
        stop = self._anchored_stop(spec, features, side, level, risk_distance, unit)
        aimed = self.target(
            Aim(
                payload=payload,
                features=features,
                spec=spec,
                side=side,
                level=level,
                entry=entry,
                vol_bps=vol_bps,
                push=push_distance,
            )
        )
        if isinstance(aimed, Refusal):
            return 0.0
        target = self._short_of(aimed, entry, side, unit, spec)
        risk = abs(entry - stop)
        reward = abs(target - entry)
        if risk <= 0:
            return 0.0
        return reward / risk

    def _better_side(
        self,
        payload: dict[str, Any],
        features: dict[str, float],
        side: Side,
        interval: str,
        spec: SymbolSpec,
        tick: Tick,
    ) -> Side:
        """Flip only when the opposite side is structurally cleaner.

        The cycle scalp thesis is specifically about entering on a pullback and
        taking the move into the next structural extreme. If the signal's own
        stop is already wider than the move it expects, the higher-probability
        answer is often the mirrored trade: the same level, the same structure,
        but the stop and target are placed on the opposite side of the pullback.
        """
        if not features:
            return side
        current = self._reward_to_risk(payload, features, side, interval, spec, tick)
        if current <= 0:
            return side

        opposite = side.opposite
        # The mirror has to clear the same gates as the original trade. If the
        # opposite side is not usable, do not invent a better one.
        quality = self.quality(str(payload.get("feed") or ""), features, opposite, interval)
        if quality is not None:
            return side

        mirror = self._reward_to_risk(payload, features, opposite, interval, spec, tick)
        if mirror <= current:
            return side
        # Require a material improvement, not a one-tick rounding change.
        if mirror < current * 1.15:
            return side
        return opposite

    def quality(
        self, feed: str, features: dict[str, float], side: Side, interval: str = ""
    ) -> Refusal | None:
        """The gates every strategy here should clear, wherever it decides.

        See `trading-strategies-scalper.md` in research/docs.
        """
        settings = self.settings

        # How likely the level is to give way, from the arrival speed and how
        # deep the touch went. A different question from the direction every
        # other gate here reads, and the evidence that it is different is that
        # `up_rate` - which carries almost all of direction - predicts a break
        # at AUC 0.4928, which is nothing. See research/force.md.
        #
        # Measured over 10,977 resolved touches at five to thirty minutes: the
        # top fifth by this estimate breaks 43.2% of the time against the
        # bottom fifth's 16.9%, so the call is right 56.8% there against 83.1%
        # at the other end. This refuses that top fifth.
        #
        # **Refuse, not invert.** Inverting the trade there was measured and
        # loses: the call is still right more often than not even where it is
        # weakest, so flipping it turns 56.8% into 43.2%.
        #
        # Silent when the estimate is absent, which is the honest state until
        # the model has 200 resolutions behind it - a level call with no break
        # reading is not a level call with a low one.
        ceiling = settings.max_break_risk
        if ceiling > 0:
            risk = features.get("break_probability")
            if risk is not None and float(risk) > ceiling:
                return Refusal(
                    "break_risk",
                    f"a {float(risk):.0%} chance this level gives way, over the "
                    f"{ceiling:.0%} it allows",
                    feed,
                )

        agree_at = self.min_momentum_agree
        if agree_at > 0 and features.get("momentum_ready"):
            agreement = _number(features, "momentum_agree")
            facing = agreement if side is Side.BUY else -agreement
            if facing < agree_at:
                return Refusal(
                    "momentum",
                    f"the sub-hour timeframes are {facing:+.2f} behind this "
                    f"{side.name.lower()}, under the {agree_at:.2f} it needs",
                    feed,
                )

        probability = _number(features, "probability")
        # The bar for *this* direction. A single absolute number let 96% of
        # sells through and refused one buy in five, because the two
        # directions' probabilities do not sit in the same place - see
        # `floors.py`. Falls back to the absolute floor until each direction
        # has a distribution, and can never sit below it.
        claimed = "up" if side is Side.BUY else "down"
        self.floors.observe(claimed, probability)
        bar = self.floors.floor(claimed, settings.min_probability)
        if probability < bar:
            return Refusal(
                "probability",
                f"{probability:.0%} against a {bar:.0%} floor for {claimed} calls",
                feed,
            )

        edge = abs(_number(features, "edge"))
        if edge < settings.min_edge:
            return Refusal("edge", f"{edge:.3f} against a {settings.min_edge:.3f} floor", feed)

        # How often this level holds *at all*, in the direction being claimed.
        #
        # `base_rate_up` is always the up rate, so it has to be flipped for a
        # sell before it means anything - comparing it raw across a set that is
        # mostly sells describes the direction mix rather than the levels, which
        # is a mistake this was written after making.
        #
        # Gated because the losses concentrate below it: over the first
        # nineteen closed trades the eight with a directional base under 0.55
        # produced one winner and -6.74R.
        # Momentum still running against the trade. Read from the feature the
        # service injects rather than computed here, because it is an
        # accumulation over the quote stream and a strategy sees one signal.
        limit = self.against_limit(interval)
        if limit > 0:
            pressure = _number(features, "pressure_vol")
            against = -pressure if side is Side.BUY else pressure
            if against > limit:
                return Refusal(
                    "momentum",
                    f"{against:.2f}v of momentum still running against a {side}, "
                    f"limit {limit:.2f}v",
                    feed,
                )

        # Trend context. Refuses the chop rather than selecting the trend,
        # which is the same thing said from the side that loses money.
        if settings.min_efficiency > 0:
            ratio = features.get("efficiency")
            if ratio is not None and float(ratio) < settings.min_efficiency:
                return Refusal(
                    "chop",
                    f"the market here is oscillating - efficiency {float(ratio):.2f} "
                    f"against a {settings.min_efficiency:.2f} floor",
                    feed,
                )

        if settings.min_base_rate > 0:
            base_up = _number(features, "base_rate_up")
            base = base_up if side is Side.BUY else 1.0 - base_up
            if base_up and base < settings.min_base_rate:
                return Refusal(
                    "base_rate",
                    f"the level holds {base:.0%} of the time this way, "
                    f"against a {settings.min_base_rate:.0%} floor",
                    feed,
                )
        return None

    def stop_floor_vol(self, interval: str) -> float:
        """The stop floor in volatility units, scaled to how long it must last.

        See `strategies-scalper.md` in research/docs.
        """
        floor = self.settings.min_stop_vol
        share = self.settings.stop_hold_scaling
        if floor <= 0 or share <= 0:
            return floor
        bars = self.hold_bars_for(interval)
        scale = min(math.sqrt(max(bars, 1.0)), max(self.settings.max_stop_scale, 1.0))
        # Interpolated rather than switched, so the setting can be walked up
        # from the old behaviour while the shadow watch collects evidence.
        return floor * (1.0 + (scale - 1.0) * min(share, 1.0))

    def distances(
        self,
        level: float,
        entry: float,
        vol_bps: float,
        risk_vol: float,
        push_vol: float,
        interval: str = "",
        features: dict[str, float] | None = None,
        side: Side | None = None,
    ) -> tuple[float, float]:
        """Stop distance from the level, target distance from the entry.

        See `trading-strategies-scalper.md` in research/docs.
        """
        wide = max(risk_vol * self.stop_multiple, self.stop_floor_vol(interval))
        return (
            price_distance(level, vol_bps, wide),
            price_distance(entry, vol_bps, self._aim(push_vol, wide)),
        )

    def _aim(self, push_vol: float, stop_vol: float) -> float:
        """The target distance, never less than `reward_floor` of the stop.

        See `strategies-scalper.md` in research/docs.
        """
        aim = push_vol * self.target_multiple
        floor = getattr(self, "reward_floor", 0.0) or 0.0
        return max(aim, stop_vol * floor) if floor > 0 else aim

    def at_the_right_place(
        self, feed: str, side: Side, features: dict[str, float]
    ) -> Refusal | None:
        """Whether the structure agrees this is the place. Nothing, by default.

        Overridden by `SwingLevel`, which trades a range rather than a level
        and therefore has somewhere it must be: at a bound, on the side that
        bound is defending.
        """
        return None

    def _chasing(
        self, feed: str, side: Side, level: float, entry: float, vol_bps: float
    ) -> Refusal | None:
        """Refuse a fill that has already left the level behind.

        See `trading-strategies-scalper.md` in research/docs.
        """
        limit = self.settings.max_chase_vol
        if limit <= 0:
            return None
        unit = price_distance(entry, vol_bps, 1.0)
        if unit <= 0:
            return None
        if (entry - level) * side.sign <= 0:
            return None
        gone = abs(entry - level) / unit
        if gone <= limit:
            return None
        return Refusal(
            "chase",
            f"the fill is {gone:.2f}v past the level at {level:.5g}, over the {limit:.2f}v limit",
            feed,
        )

    def _anchored_stop(
        self,
        spec: SymbolSpec,
        features: dict[str, float],
        side: Side,
        level: float,
        risk_distance: float,
        unit: float,
    ) -> float:
        """Where the stop goes, floored against the level *and* the fill.

        See `strategies-scalper.md` in research/docs.
        """
        # The **sweep** zone, not the touch zone, and they are different
        # questions. The touch zone's far edge is built from the average wick,
        # which is right for "is price at this level" and wrong for "how far
        # past it does price go" - a stop there is exceeded by about half of
        # all sweeps by construction, which from the account looks like being
        # stopped out and then watching the move happen.
        #
        # Falls back to the touch zone on a signal that predates the wider one,
        # so an older producer degrades to the previous behaviour rather than
        # to no zone at all.
        if side is Side.BUY:
            edge = _number(features, "sweep_low") or _number(features, "zone_low")
        else:
            edge = _number(features, "sweep_high") or _number(features, "zone_high")
        return spec.round_price(
            stop_for(level, side, risk_distance, zone_edge=edge, clearance=unit * 0.25)
        )

    def _floored_stop(
        self,
        spec: SymbolSpec,
        side: Side,
        entry: float,
        anchored: float,
        unit: float,
        interval: str = "",
        spread: float = 0.0,
        floor_vol: float = 0.0,
    ) -> float:
        """Push the stop out until it is `min_stop_vol` from the **fill** too.

        See `trading-strategies-scalper.md` in research/docs.
        """
        # A parked entry brings its own floor, because `min_stop_vol` is written
        # for a fill that may be anywhere near the level and a parked fill is
        # at it. Without this the floor below would push the tightened stop
        # straight back out and the setting would do nothing - visibly
        # configured, silently inert, which is the failure this repository
        # spent a day finding.
        # A parked entry brings its own floor, and it is **capped at the
        # ordinary one** so it can only ever lower it. Guarding the anchored
        # distance alone was not enough: a large `parked_stop_vol` came
        # straight back through here and widened the stop, which a test caught
        # by asking for 99v and getting a position too small to place. A
        # setting named for reducing risk must not have a path that raises it.
        ordinary = self.stop_floor_vol(interval)
        floor = (min(floor_vol, ordinary) if floor_vol else ordinary) * unit
        # The broker has a floor of its own and it is not a suggestion: a stop
        # closer than `stops_level` is refused outright, and the refusal
        # arrives after the decision has been made.
        #
        # Wall Street 30 asks for 300 points - 3.00 in price - against gold's
        # 20, and our stops on it land near 2.7, so the order is accepted or
        # rejected depending on where volatility happens to be. Taking the
        # broker's minimum as a floor here turns that coin flip into a trade
        # with a slightly wider stop, which is the outcome worth having: the
        # alternative is a refusal, and a refusal is not a safer trade, it is
        # no trade.
        #
        # A small margin over the minimum, because the minimum is checked
        # against the price at the moment the order lands, not the moment it
        # was built.
        # Two terms, because the gap has two causes. The multiple absorbs
        # movement between deciding and sending; the spread absorbs the part
        # that is not movement at all - a buy fills at the ask and its stop is
        # measured against the bid, so one spread of the clearance is gone
        # before anything has happened.
        floor = max(floor, spec.min_stop_distance * self.settings.stops_level_margin + spread)
        if floor <= 0:
            return anchored
        against_fill = spec.round_price(entry - floor if side is Side.BUY else entry + floor)
        return min(anchored, against_fill) if side is Side.BUY else max(anchored, against_fill)

    def _short_of(
        self, target: float, entry: float, side: Side, unit: float, spec: SymbolSpec
    ) -> float:
        """Pull the target back by `target_buffer_vol`, if one is asked for.

        See `strategies-scalper.md` in research/docs.
        """
        want = self.settings.target_buffer_vol
        if want <= 0 or unit <= 0 or not target:
            return target
        move = (target - entry) * side.sign
        if move <= 0:
            return target
        pulled = min(want * unit, move * 0.5)
        return spec.round_price(target - side.sign * pulled)

    def target(self, context: Aim) -> float | Refusal:
        """Where to take profit. Overridden by anything not aiming at the push."""
        return context.spec.round_price(target_for(context.entry, context.side, context.push))

    def consider(
        self,
        payload: dict[str, Any],
        *,
        spec: SymbolSpec,
        tick: Tick,
        equity: float,
        # What the book already holds, and the equity high-water mark. Both
        # optional and both default to "nothing known", so a caller that does
        # not track them - a test, a replay - sizes exactly as before rather
        # than differently and silently. See `risk_scale`.
        positions: Sequence[Any] = (),
        peak: float = 0.0,
    ) -> Verdict:
        self.seen += 1
        feed = str(payload.get("feed") or "")
        settings = self.settings

        if not self.wants(payload):
            return Refusal("shape", f"{payload.get('shape')} is not a level call", feed)

        interval = str(payload.get("interval") or "")
        if interval not in self.intervals:
            return Refusal(
                "interval", f"{interval} is not scalped ({', '.join(self.intervals)})", feed
            )

        side = Side.from_direction(str(payload.get("direction") or ""))
        if side is None:
            return Refusal("direction", "the call names no direction", feed)

        features = _features(payload)

        bad = self.quality(feed, features, side, interval)
        if bad is not None:
            return bad

        # Deliberately after the gates and before everything else. A strategy
        # that trades against the call still wants the calls the model likes
        # best - gating on the flipped side would select a different set of
        # signals and stop being a comparison. Everything downstream reads
        # `side`, so the trade this builds is a correct one on the other side.
        side = self.orient(side)
        if self.reverse_if_better:
            side = self._better_side(payload, features, side, interval, spec, tick)

        # Both, and the second half is the guard: a strategy that names no
        # context timeframes cannot be unanchored, and asking would refuse
        # every call it ever saw. `council` is that case - it declares no
        # context because it delegates, and its members carry their own.
        wants_context = self.needs_context and bool(self.context)
        if wants_context and not self.anchored(payload):
            return Refusal(
                "unanchored",
                f"no {'/'.join(self.anchors)} agrees with this {interval} call",
                feed,
            )

        narrowed = self.accept(payload, features)
        if narrowed is not None:
            return narrowed

        level = _number(features, "level")
        if level <= 0:
            return Refusal("level", "the call carries no level price", feed)

        vol_bps = _number(features, "vol_bps")
        if vol_bps <= 0:
            return Refusal(
                "volatility",
                "the call carries no volatility unit, so its distances cannot be priced",
                feed,
            )

        risk_vol = abs(_number(features, "risk_vol"))
        push_vol = abs(_number(features, "expected_push_vol"))
        if risk_vol <= 0:
            return Refusal("risk", "the call states no risk distance", feed)
        if push_vol <= 0:
            return Refusal("push", "the call expects no push", feed)
        # A push far past anything the market does is a fault, not a forecast.
        # See `Settings.max_push_vol`: a brent call arrived claiming 10,229v
        # against a measured p99 of 9.55v, and became a target 43 times the
        # price of the instrument.
        if self.settings.max_push_vol > 0 and push_vol > self.settings.max_push_vol:
            return Refusal(
                "push",
                f"the call expects {push_vol:.4g}v, past the {self.settings.max_push_vol:.4g}v "
                "any real push reaches - this is a broken number",
                feed,
            )

        entry = tick.entry(side)

        # How far the fill is from the level the trade is about. Entry is a
        # market order, so this is wherever price happened to be when the call
        # arrived - and nothing used to look at it. A call measured at the
        # level does not describe a price two volatility units away from it:
        # the push it predicts is measured from the level, so buying late
        # spends part of the move before the trade starts, and the stop, which
        # is anchored to the level, ends up close underneath the fill.
        chased = self._chasing(feed, side, level, entry, vol_bps)
        if chased is not None:
            return chased

        # A hook for a strategy whose thesis is about *where in a structure*
        # price is, rather than about the level alone. Returns nothing for
        # everything that does not implement it.
        placed = self.at_the_right_place(feed, side, features)
        if placed is not None:
            return placed

        risk_distance, push_distance = self.distances(
            level, entry, vol_bps, risk_vol, push_vol, interval, features=features, side=side
        )
        # A stop that waited for its price can afford to be tighter, and only
        # that one can. See `Settings.parked_stop_vol` for why this is not a
        # general setting: the replay's tight stop is measured from the level,
        # and a parked entry is the only kind that is actually there.
        tight = self._parked_stop(features, level, vol_bps, interval)
        if tight:
            risk_distance = min(risk_distance, tight)
        # The far edge of the level's own band on the side the stop sits, and a
        # quarter unit of clearance beyond it. Absent on an older signal, in
        # which case the stop falls back to the origin as before.
        unit = price_distance(level, vol_bps, 1.0)
        stop = self._anchored_stop(spec, features, side, level, risk_distance, unit)
        aimed = self.target(
            Aim(
                payload=payload,
                features=features,
                spec=spec,
                side=side,
                level=level,
                entry=entry,
                vol_bps=vol_bps,
                push=push_distance,
            )
        )
        if isinstance(aimed, Refusal):
            return aimed
        target = self._short_of(aimed, entry, side, unit, spec)

        # The stop is anchored to the level, so a fill on the far side of it -
        # price ran through while this was being decided - leaves a stop that is
        # already behind price. That is not a trade to shrink; it is a trade
        # that has already been invalidated.
        if (side is Side.BUY and entry <= stop) or (side is Side.SELL and entry >= stop):
            return Refusal("through", f"price is already past the stop at {stop:.5g}", feed)

        # Only now, with the trade known to be still valid, is the stop widened
        # to clear the fill by a volatility unit. See `_floored_stop`.
        stop = self._floored_stop(
            spec,
            side,
            entry,
            stop,
            unit,
            interval,
            tick.spread,
            floor_vol=self.settings.parked_stop_vol if tight else 0.0,
        )

        broker_says = respects_stops_level(spec, entry, stop, target)
        if broker_says:
            return Refusal("stops_level", broker_says, feed)

        sized = lots(
            spec,
            equity=equity,
            risk_fraction=(
                settings.risk_fraction
                * self.trend_scale(features)
                * self.momentum_scale(features, side)
                # How well supported this call is by the strategy's own
                # stricter reading of it. 1.0 unless a strategy overrides it,
                # and never above 1.0 - see `conviction_scale`.
                * self.conviction_scale(features, side)
                # Crowding, volatility, measured edge and drawdown. All four
                # off unless set, and none can enlarge - see `scaling.py`.
                * self.risk_scale(feed, features, positions, equity, peak, interval, side)
            ),
            stop_distance=abs(entry - stop),
            max_risk_money=settings.max_risk_money,
            slippage=settings.stop_slippage,
        )
        if not sized.ok:
            return Refusal("size", sized.reason, feed)

        # Stretched to this strategy's horizon rather than taken flat. See
        # `Strategy.horizon`: a 1R break-even and a 2v trail describe one bar,
        # and the trade is held for many.
        protect_at, protect_trail = self.protection(interval, push_vol)
        self.wanted += 1
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
            confluence=_confluence(payload),
            # Carried from the signal so a closed trade can be added up
            # against the level that produced it. Levels drift under the
            # filter, so the price is not a name.
            level_id=str(payload.get("level_id") or ""),
            features=features,
            risk_money=sized.risk_money,
            stop_vol=abs(entry - stop) / unit if unit else 0.0,
            stop_scale=self.stop_floor_vol(interval) / (self.settings.min_stop_vol or 1.0),
            hold=self.hold_for(interval),
            stale_exempt=self.stale_exempt,
            break_even_at=protect_at,
            trail_vol=protect_trail,
            # Carried on the intent for the same reason the two above are: by
            # the time a stop is being moved, the strategy is a name in a log
            # line and nothing links it back to the class.
            trail_levels=self.trail_levels,
        )


@register
class CycleScalp(LevelStrategy):
    """The unified scalping thesis: the cycle is higher-timeframe trend, lower-timeframe pullback.

    The market is read in layers: 4h sets the bias, 1h confirms the structure,
    and 15m/1m waits for the pullback into the level. The trade is only taken
    when the level still agrees with the cycle and the stop is not sitting in
    front of obvious liquidity. This collapses the older scalp variants into a
    single strategy that follows the same idea without splitting it into
    separate names for minor execution differences.
    """

    name: ClassVar[str] = "cycle-scalp"
    refines: ClassVar[str] = "level-scalp"
    reverse_if_better: ClassVar[bool] = True
    description: ClassVar[str] = (
        "Cycle scalp: higher-timeframe trend, lower-timeframe pullback, and a "
        "liquidity-aware stop. The unified scalp strategy for the 4h=>1h=>15m "
        "cycle. Uses a slightly wider stop and target to let the cycle breathe "
        "without turning into a swing."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m")
    context: ClassVar[tuple[str, ...]] = ("30m", "1h", "4h")
    #: Give the cycle room to pull back before an invalidation, without
    #: abandoning the scalp horizon. The wider target matches the wider stop so
    #: the trade still earns the full expected push from the trend cycle instead
    #: of being cut off by a shallow pullback.
    stop_multiple: ClassVar[float] = 1.25
    target_multiple: ClassVar[float] = 1.25

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        """Keep the unified scalp thesis lean: refuse clogging liquidity, then a z-score against.

        The z gate is inert unless `TRADING_ZMA_GATE` is set, and even then it
        can only ever remove a trade - see `zma_gate` for why a detector
        measuring 0.50 on this book is not allowed to add one.
        """
        clogged = sweep_gate(self, payload, features)
        if clogged is not None:
            return clogged
        return zma_gate(self, payload, features)

    def distances(
        self,
        level: float,
        entry: float,
        vol_bps: float,
        risk_vol: float,
        push_vol: float,
        interval: str = "",
        features: dict[str, float] | None = None,
        side: Side | None = None,
    ) -> tuple[float, float]:
        """Cycle scalp wants a pullback stop and a trend-side target.

        The stop sits beyond the most recent pullback extreme, not just beyond
        the level itself. The target sits near the next structural extreme on
        the trend side. Both are still capped by whichever geometry the level
        model already says is the trade's own risk and push.
        """
        stop_distance, target_distance = super().distances(
            level,
            entry,
            vol_bps,
            risk_vol,
            push_vol,
            interval,
            features=features,
            side=side,
        )
        if not features or side is None:
            return stop_distance, target_distance

        unit = price_distance(level, vol_bps, 1.0)
        if side is Side.BUY:
            pullback = _number(features, "sweep_low") or _number(features, "zone_low")
            if pullback and pullback < level:
                stop_distance = max(stop_distance, abs(level - pullback) + unit * 0.25)
            trend = _number(features, "origin_high") or _number(features, "zone_high")
            if trend and trend > entry:
                target_distance = min(
                    max(target_distance, abs(trend - entry) * 0.85),
                    abs(trend - entry),
                )
        else:
            pullback = _number(features, "sweep_high") or _number(features, "zone_high")
            if pullback and pullback > level:
                stop_distance = max(stop_distance, abs(pullback - level) + unit * 0.25)
            trend = _number(features, "origin_low") or _number(features, "zone_low")
            if trend and trend < entry:
                target_distance = min(
                    max(target_distance, abs(entry - trend) * 0.85),
                    abs(entry - trend),
                )
        return stop_distance, target_distance


@register
class LevelScalp(LevelStrategy):
    """The plain reading: take the call as published."""

    name: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "Trade a level call in the direction it states, stop beyond the level, "
        "target the expected push. Fast timeframes only. The default."
    )
    #: Triggers on fast data. The stop is a volatility unit or two and
    #: `max_hold` closes it inside the hour, so a 4h thesis would be ended by
    #: the clock rather than by being right or wrong - which teaches the
    #: journal nothing.
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    #: Anchored above, without requiring it. A 5m call confirmed by 1h is a
    #: better 5m call; one without is still a call, and refusing it is
    #: `confluence-scalp`'s job rather than this one's.
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")


@register
class ConfluenceScalp(LevelStrategy):
    """Only levels more than one timeframe agrees on.

    See `strategies-scalper.md` in research/docs.
    """

    name: ClassVar[str] = "confluence-scalp"
    description: ClassVar[str] = (
        "Only calls confirmed by another timeframe, with a wider stop. Fewer trades."
    )
    #: Same fast trigger as `level-scalp`. The difference is that the anchor
    #: is required rather than merely welcome.
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h", "1d")
    needs_context: ClassVar[bool] = True
    stop_multiple: ClassVar[float] = 1.5

    #: `ride`'s exit, the same three numbers `sweep-aware` carries. Six times
    #: the modelled push is past the p99 of what touches reach, so it bounds
    #: the trade without being what normally ends it; half a volatility unit
    #: was the best trail of the six measured; and the trade protects itself
    #: once it has paid for its own risk.
    target_multiple: ClassVar[float] = 6.0
    trail_vol: ClassVar[float] = 0.5
    break_even_at: ClassVar[float] = 1.0

    # The requirement is `needs_context`, applied by `LevelStrategy.consider`
    # for every strategy that sets it. It used to live here as a bespoke check
    # against any other timeframe at all, which is a different and weaker
    # claim: a 1m call confirmed by 3m is not "confirmed by a higher
    # timeframe", it is the same fast noise seen twice.

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        """`sweep-aware`'s gate, judged against *this* strategy's wider stop."""
        return sweep_gate(self, payload, features)


@register
class MomentumScalp(LevelStrategy):
    """Only calls that point the way the recent calls have been pointing.

    See `strategies-scalper.md` in research/docs.
    """

    name: ClassVar[str] = "momentum-scalp"
    description: ClassVar[str] = (
        "Only calls agreeing with three speeds of recent edge. Misses turns by construction."
    )
    #: The speeds are half-lives of 3/12/48 arriving calls. On a 1w level those
    #: forty-eight calls span months, so the slow line would describe a market
    #: that no longer exists. Fast data is where the estimator has enough
    #: observations for its own half-lives to mean anything.
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h")

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.speeds = Speeds()

    def observe(self, payload: dict[str, Any]) -> None:
        """Every call feeds the speeds, not only the ones already agreed with.

        The series has to be what the instrument actually produced. Building it
        from calls that had already passed a directional filter would make the
        three lines agree with themselves by construction.
        """
        if not self.wants(payload):
            return
        self.speeds.observe(str(payload.get("feed") or ""), _number(_features(payload), "edge"))

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        feed = str(payload.get("feed") or "")
        side = Side.from_direction(str(payload.get("direction") or ""))
        if side is None:
            return Refusal("direction", "the call names no direction", feed)
        if not self.speeds.ready(feed):
            return Refusal("warmup", "the speeds have not seen enough calls yet", feed)
        if not self.speeds.agree(feed, side.sign):
            fast, mid, slow = self.speeds.of(feed)
            return Refusal(
                "momentum",
                f"{side} against speeds {fast:+.3f}/{mid:+.3f}/{slow:+.3f}",
                feed,
            )
        return None


@register
class Snap(LevelStrategy):
    """Enter at the touch, leave when it has resolved. Seconds, not minutes.

    See `strategies-scalper.md` in research/docs.
    """

    name: ClassVar[str] = "snap"
    description: ClassVar[str] = (
        "The level call held for as long as the interaction actually lasts - "
        "the median touch resolves in 18 seconds. Same trade as level-scalp "
        "with a two-minute clock instead of a thirty-minute one."
    )
    #: Two minutes covers 72% of resolutions. Longer buys a smaller share of a
    #: smaller push; shorter starts cutting theses off before they resolve.
    hold_seconds: ClassVar[float] = 120.0
    #: Protect early and trail close, because the trade is over in seconds.
    #:
    #: The global numbers are built for a half-hour thesis: a 1R threshold and
    #: a 2v trail. On a two-minute trade that is most of its life spent
    #: unprotected, and it misses the case this is for - a bar that runs almost
    #: to the target, stops just short, and gives it all back. Half an R is
    #: reached inside the first few seconds of a real move, and a trail under a
    #: volatility unit keeps most of a spike that never quite closed the
    #: distance.
    break_even_at: ClassVar[float] = 0.5
    trail_vol: ClassVar[float] = 0.75
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")


@register
class ThesisOnly(LevelStrategy):
    """The same call, with the stop moved out of the way. An experiment.

    See `strategies-scalper.md` in research/docs.
    """

    name: ClassVar[str] = "thesis-only"
    description: ClassVar[str] = (
        "The level call with the stop moved out of the way - a circuit breaker "
        "rather than a trade decision. Exits on target or on the clock. An "
        "experiment to test whether the stops or the theses are wrong."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")

    def distances(
        self,
        level: float,
        entry: float,
        vol_bps: float,
        risk_vol: float,
        push_vol: float,
        interval: str = "",
        features: dict[str, float] | None = None,
        side: Side | None = None,
    ) -> tuple[float, float]:
        """A stop far enough away to be a circuit breaker, and the usual target.

        The target is untouched on purpose. Moving both would make this a
        different trade rather than the same trade with more room, and the
        comparison would say nothing.
        """
        return (
            price_distance(level, vol_bps, self.settings.thesis_stop_vol),
            price_distance(entry, vol_bps, push_vol * self.target_multiple),
        )

    def stop_floor_vol(self, interval: str) -> float:
        """The circuit breaker is the floor here, not `min_stop_vol`."""
        return max(self.settings.thesis_stop_vol, self.settings.min_stop_vol)


@register
class Inverse(LevelStrategy):
    """The same call, taken the other way. A control, not a conviction.

    See `strategies-scalper.md` in research/docs.
    """

    name: ClassVar[str] = "inverse"
    description: ClassVar[str] = (
        "The calls the model likes best, traded the other way. A control on "
        "whether the direction or the execution is what loses money."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")

    #: Fading a run that is still running is the worst version of what this
    #: does. The control is meant to test the *direction* the model produces,
    #: not to stand in front of momentum, and without this the two are
    #: confounded - a loss could be either.
    max_against_vol: ClassVar[float] = 1.5

    def orient(self, side: Side) -> Side:
        """The other one. This is the whole strategy."""
        return side.opposite


def zma_gate(strategy: Any, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
    """Refuse a call the z-score is leaning against, **if that feed's record earns it.**

    See `strategies-scalper.md` in research/docs.
    """
    settings = strategy.settings
    if not settings.zma_gate:
        return None

    z = _number(features, "zma_z")
    strong = _number(features, "zma_strong")
    if strong <= 0 or abs(z) <= strong:
        return None  # inside its own band, which is most bars

    calls = _number(features, "zma_edge_calls")
    if calls < settings.zma_min_calls:
        return None
    if _number(features, "zma_edge_right") / max(calls, 1.0) <= settings.zma_min_accuracy:
        return None

    side = Side.from_direction(str(payload.get("direction") or ""))
    if side is None:
        return None
    # Stretched down expects a rise, so it leans with a buy and against a sell.
    expects_up = z < 0
    if expects_up == (side is Side.BUY):
        return None

    feed = str(payload.get("feed") or "")
    # The word is rendered from the two numbers that define it: `features` is
    # `dict[str, float]` and `Signal.to_dict` rounds it, so a published string
    # raises at publication rather than here.
    state = "overbought" if z > 0 else "oversold"
    return Refusal(
        "zma_against",
        f"the z-score is {state} at {z:+.2f} against a {strong:.2f} threshold, "
        f"and has been right {_number(features, 'zma_edge_right') / max(calls, 1.0):.0%} "
        f"of {calls:.0f} calls on this feed",
        feed,
    )


def sweep_gate(
    strategy: Any, payload: dict[str, Any], features: dict[str, float]
) -> Refusal | None:
    """`sweep-aware`'s entry gate, as something any level strategy can wear.

    See `strategies-scalper.md` in research/docs.
    """
    feed = str(payload.get("feed") or "")
    settings = strategy.settings

    swept = _number(features, "sweep_rate")
    swept_n = _number(features, "sweep_n")
    if swept_n >= settings.sweep_min_history and swept >= settings.sweep_max_rate:
        return Refusal(
            "swept_often",
            f"this level has been run {swept:.0%} of {swept_n:.0f} decisive "
            f"interactions from this side",
            feed,
        )

    beyond = _number(features, "liquidity_beyond_vol")
    if beyond <= 0:
        return None  # nothing within reach to be run toward

    risk_vol = abs(_number(features, "risk_vol")) * strategy.stop_multiple
    exposure = risk_vol / beyond
    if exposure >= settings.sweep_max_exposure:
        return Refusal(
            "in_front",
            f"a {risk_vol:.2f}v stop reaches {exposure:.0%} of the way to "
            f"liquidity {beyond:.2f}v beyond",
            feed,
        )
    return None


@register
class SweepAware(LevelStrategy):
    """The plain call, refused when the stop is standing in front of the door.

    See `strategies-scalper.md` in research/docs.
    """

    name: ClassVar[str] = "sweep-aware"
    #: Every call `level-scalp` takes, minus the ones whose stop sits in front
    #: of resting liquidity. Listed after it, this would never fire.
    refines: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "level-scalp, refusing setups whose stop sits in front of resting liquidity."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")
    #: A sweep *is* momentum - a run through a level, taking the stops behind
    #: it. This strategy refuses when its stop sits in front of that liquidity,
    #: which is a statement about geometry; whether the run is still going is a
    #: separate question and it was not asking it. Nine of its twelve trades
    #: were stopped, more than any other strategy here.
    max_against_vol: ClassVar[float] = 1.5

    # **`ride`'s exit, kept on this entry.** The filter above is what works -
    # the calls it declines are worth +0.189R each - and the exit it had was
    # the third-worst of the six policies `Ride` was measured over: a fixed
    # target at one push, no trail, -0.041R against ride's +0.404R.
    #
    # Replayed on this strategy's own rule across 52,395 published calls,
    # 30,875 with the 1m history to walk forward, **with the spread charged**:
    #
    #     its own exit   +0.099R   median +0.467   win 61.6%
    #     ride's exit    +0.655R   median +0.353   win 64.4%
    #     paired         +0.556R, better on 70.8% of the same trades
    #
    # The spread is real and does not reverse it - it costs the old policy
    # 0.073R a trade, 42% of everything that policy made.
    #
    # **Those numbers are inflated about tenfold and the exit stays anyway.**
    # The harness that produced them had two look-aheads: the trail was raised
    # on a bar's own high and then allowed to fill on that same bar, and a stop
    # was booked at its own price even on a bar that gapped through it. A
    # trailing policy benefits from both; a fixed target does neither.
    #
    # Re-run on the corrected walk over 18,272 calls, with the old arithmetic
    # kept beside it so both saw **the same trades**, the bug was worth
    # **+0.386R to this exit and +0.006R to the one it beat**:
    #
    #     legacy walk    ride - own  +0.432R, better on 68.0%
    #     corrected      ride - own  +0.046R, better on 36.3%
    #
    # So the advantage is real and an order of magnitude smaller, and the shape
    # is not what the paragraph above describes. The median falls from +0.498 to
    # **+0.133** and the policy is worse on **64% of the same trades**, winning
    # only through a thin right tail. Held in both halves of a split sample.
    #
    # It is kept rather than reverted because the corrected edge is still
    # positive, and changed on evidence rather than on a number's collapse. But
    # a tail edge is a different risk profile from a broad one, and
    # `research/giveback.md` measures what it feels like live: this strategy
    # keeps **27%** of its high-water mark and 38 of its 47 closes end on the
    # hold timeout rather than on any rule here firing at all.
    #
    # **Only the exit moves.** The stop, the entry price and the resting
    # behaviour are what the replay held constant; changing them would make
    # this a different trade rather than the same trade with a better exit,
    # which is the mistake `thesis-only` made in reverse - it moved the stop
    # and left the target, and went on at 0.37 reward-to-risk.
    #
    # **The median falls while the mean rises.** A trail wins by the right
    # tail, so the typical trade is worse and the average one much better. That
    # is a different risk profile, not only a bigger number, and it will show
    # as more round trips through profit. See `research/exiting.md`.

    #: Six times the modelled push is far past the p99 of what touches reach,
    #: so it bounds the trade without being what normally ends it.
    target_multiple: ClassVar[float] = 6.0
    #: The exit. Half a volatility unit was the best of the six measured.
    trail_vol: ClassVar[float] = 0.5
    #: Protect the trade once it has paid for its own risk.
    break_even_at: ClassVar[float] = 1.0

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        return sweep_gate(self, payload, features)
