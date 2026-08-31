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
from dataclasses import dataclass
from typing import Any, ClassVar

from .models import Intent, Refusal, Side, SymbolSpec, Tick, Verdict
from .sizing import lots, price_distance, respects_stops_level, stop_for, target_for
from .speeds import Speeds
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

        Zero for a market entry, which is most of them, and the caller takes
        the smaller of this and the ordinary distance - so this can only ever
        tighten a stop, never widen one. A setting that could widen would be a
        way to increase risk through a field named for reducing it.

        **Zero as well for a trade held longer than `PARKED_STOP_HOLD`**, and
        that bound is the correction of a real mistake. The tighter stop was
        adopted from a replay grid, and the grid was scored over resolutions
        with a median life of eighteen seconds; it says nothing about a
        position held for thirty minutes. Stop width has to match hold length,
        and applying a short-hold number to a long-hold trade is how five gold
        sells were stopped inside a point and a half on a day gold fell
        twenty-eight.
        """
        want = self.settings.parked_stop_vol
        if want <= 0 or not features.get("after_pullback"):
            return 0.0
        if self.hold_for(interval, self.settings.max_hold) > self.PARKED_STOP_HOLD:
            return 0.0
        return price_distance(level, vol_bps, want)

    def momentum_scale(self, features: dict[str, float], side: Side) -> float:
        """Size multiplier for whether momentum is confirming this trade.

        Full size when the accumulated run is with the trade, reduced when it
        is merely not against it. The two gates either side of this are
        yes-or-no - `max_against_vol` refuses a run still going the wrong way,
        `require_turn_vol` asks for the turn after a pullback - and between
        them sits a case neither covers: momentum flat or unreadable, which is
        weaker evidence than momentum turning and stronger than momentum
        opposing.

        Returns 1.0 when the setting is off, when there is no reading, or when
        momentum is with the trade. It can only reduce.
        """
        share = self.settings.unconfirmed_size
        if share >= 1.0 or share <= 0:
            return 1.0
        pressure = features.get("pressure_vol")
        if pressure is None:
            return 1.0  # no reading is not the same as no confirmation
        with_trade = float(pressure) if side is Side.BUY else -float(pressure)
        return 1.0 if with_trade > 0 else share

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

    def quality(
        self, feed: str, features: dict[str, float], side: Side, interval: str = ""
    ) -> Refusal | None:
        """The gates every strategy here should clear, wherever it decides.

        Extracted because one of them was not clearing them. `FadeToValue`
        overrides `consider` entirely and therefore ran none of this - so the
        probability floor, the per-direction percentile, the edge floor and the
        base-rate floor applied to three strategies and not to the fourth. The
        exemption was invisible from the configuration, which read as though
        every gate protected every strategy, and the exempt one was first in
        the running order taking most of the trades.

        A shared method rather than a copied block, so the two paths cannot
        drift apart again.
        """
        settings = self.settings

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

        `min_stop_vol` is denominated in **one bar** of the entry interval,
        because that is what `vol_bps` measures. The trade is held for many
        bars, and volatility grows with the square root of time - measured on
        our own instruments, not assumed - so a one-bar stop on a thirty-bar
        trade sits inside the noise it has to survive and is taken by ordinary
        wandering rather than by the level failing.

        Scaled by `sqrt(hold_bars)`, capped by `max_stop_scale`. The cap is
        there because the uncapped number is large enough that
        `reward_to_risk` refuses nearly everything - possibly the honest
        answer, but not one to arrive at without deciding to.
        """
        floor = self.settings.min_stop_vol
        share = self.settings.stop_hold_scaling
        if floor <= 0 or share <= 0:
            return floor
        bars = self.hold_bars_for(interval, self.settings.max_hold)
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
    ) -> tuple[float, float]:
        """Stop distance from the level, target distance from the entry.

        The stop is floored at `min_stop_vol`. A stop inside one volatility
        unit is inside the width of the estimate it is protecting, and is taken
        by ordinary movement rather than by the thesis failing - see
        `Settings.min_stop_vol` for the two live trades that made the case.
        """
        wide = max(risk_vol * self.stop_multiple, self.stop_floor_vol(interval))
        return (
            price_distance(level, vol_bps, wide),
            price_distance(entry, vol_bps, push_vol * self.target_multiple),
        )

    def _chasing(
        self, feed: str, side: Side, level: float, entry: float, vol_bps: float
    ) -> Refusal | None:
        """Refuse a fill that has already left the level behind.

        Entry is a market order, so it lands wherever price is when the call
        arrives, and nothing used to look at that. The call was measured *at*
        the level and the push it predicts runs from there, so a fill well past
        it has already spent part of the move - and the stop, being anchored to
        the level, ends up sitting close underneath the fill. Both halves of
        "stopped out before the move came" meet at this number.

        Only counted when the fill is past the level in the trade's own
        direction. Arriving before it is the setup behaving as advertised.
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

        `stop_for` anchors it beyond the level's zone, which is the right place
        to decide the trade is wrong: the level is the thing being traded, and
        the invalidation should not move because the spread did.

        What that leaves open is the fill. `distances` floors the stop at
        `min_stop_vol` measured **from the level**, and says nothing about how
        far the entry ended up from it. Entry is market, so it lands wherever
        price is when the call arrives, and it can land most of the way to a
        level-anchored stop - hardest on `approach-scalp`, whose whole geometry
        is entering away from the level it measures.

        Sizing then uses `abs(entry - stop)`, correctly, because that is what
        is actually lost. The two together are the failure: a fill one unit
        above its own stop is sized as a one-unit trade, which is a large one,
        and is then taken out by ordinary movement rather than by the thesis
        breaking. That is the loss this was written after - a gold buy filled
        1.0v above a stop sitting 5.9v below the level, sized 0.18 lots on the
        short distance, stopped within minutes.

        So the floor is applied twice, from both anchors. It can only ever push
        the stop further from the fill, which only ever reduces size for the
        same money at risk. It never moves a stop closer in.
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

        Applied only after the `through` check has passed, and the order is not
        a detail. A fill already on the far side of the level-anchored stop is
        an invalidated trade, not a trade to re-stop; running this first would
        quietly rebase the stop below such a fill and turn a refusal into a
        position. An existing test says so, and caught exactly that.

        Past that point this can only push the stop further from the fill,
        which only ever reduces size for the same money at risk.
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

        A target sitting exactly where everyone else is watching fills last.
        Price stalls *at* a level rather than through it, so the final fraction
        is the part most often not given - and giving it up costs a known
        small amount to avoid an unknown larger one. `approach-scalp` has
        always done this; this is the same idea for every other target.

        Applied after the strategy has aimed, so an override that already
        stands off - the next level minus a buffer, the opposite origin's near
        edge - gets the same treatment and does not have to remember to.

        **Never past the entry.** A buffer larger than the move would invert
        the trade, and a target behind the fill is not a smaller target.
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

        if self.needs_context and not self.anchored(payload):
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

        risk_distance, push_distance = self.distances(
            level, entry, vol_bps, risk_vol, push_vol, interval
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
            hold=self.hold_for(interval, self.settings.max_hold),
            break_even_at=protect_at,
            trail_vol=protect_trail,
        )


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
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m")
    #: Anchored above, without requiring it. A 5m call confirmed by 1h is a
    #: better 5m call; one without is still a call, and refusing it is
    #: `confluence-scalp`'s job rather than this one's.
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")


@register
class ConfluenceScalp(LevelStrategy):
    """Only levels more than one timeframe agrees on.

    The intuition is the one the level model states about itself: a price that
    several timeframes independently placed a level at is one structure seen
    several times, the higher carrying the significance and the lower the
    placement. Taking fewer trades for that reason is paid for with half a
    volatility unit more room on the stop, since a confirmed level is not a
    more *precisely located* one.

    **The only measurement bearing on this says breadth does not predict.**
    [strength.md](../../research/strength.md) tested confluence depth against
    whether a level holds and found nothing, in the strongest form of nothing:
    four runs produced four different orderings - best at depth 1, at depth 2,
    monotone increasing, and best at depth 3 - and as a ranking signal depth
    scores an **AUC of 0.476 and 0.452**, below the 0.5 that means no
    information at all. `depth >= 3` against `depth < 3` came out -2.2
    [-6.3, +1.7], -5.2 [-9.4, -1.2] and +0.3 [-4.2, +4.9]; not one interval
    excludes zero in the direction this strategy assumes. That document also
    calls `Zone.strength`'s existing `1 + 0.15 x (depth - 1)` multiplier
    "unearned on this evidence".

    So why is this still here. Two reasons, and neither is that the measurement
    is wrong. First, what it measured is *did price get through the level*, and
    strength.md is explicit that this is not the same question as *did the
    trade make money* - a level that holds after a 3v excursion is a hold and a
    loss. Second, this uses depth to **select** rather than to weight, and a
    filter that halves the trade count is a different object from a multiplier
    on a score.

    Both of those are excuses until something measures them, so treat this as
    **unvalidated and probably not better than `level-scalp`**. It is kept as a
    named strategy precisely so the journal can settle it rather than having
    the assumption buried as a flag inside the default.
    """

    name: ClassVar[str] = "confluence-scalp"
    description: ClassVar[str] = (
        "Only calls confirmed by another timeframe, with a wider stop. Fewer trades."
    )
    #: Same fast trigger as `level-scalp`. The difference is that the anchor
    #: is required rather than merely welcome.
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h", "1d")
    needs_context: ClassVar[bool] = True
    stop_multiple: ClassVar[float] = 1.5

    # The requirement is `needs_context`, applied by `LevelStrategy.consider`
    # for every strategy that sets it. It used to live here as a bespoke check
    # against any other timeframe at all, which is a different and weaker
    # claim: a 1m call confirmed by 3m is not "confirmed by a higher
    # timeframe", it is the same fast noise seen twice.


@register
class MomentumScalp(LevelStrategy):
    """Only calls that point the way the recent calls have been pointing.

    score.md §2 keeps three exponential averages of its score and treats their
    agreement as the confidence: "the fast line is what is happening, the slow
    line is the context". The same three speeds are kept here over the *signed*
    edge of the calls arriving for each instrument, and a trade is taken only
    when all three agree with the direction it states.

    What that buys is a filter against calls fighting their own context - a
    short at a level while every recent call on that instrument has been long.
    What it costs is the turn: the trade at the exact moment a move reverses is
    precisely the one all three lines disagree with, and this strategy will
    always miss it. That is the trade-off, not a defect, and it is the reason
    this is a separate strategy rather than a filter added to the default.
    """

    name: ClassVar[str] = "momentum-scalp"
    description: ClassVar[str] = (
        "Only calls agreeing with three speeds of recent edge. Misses turns by construction."
    )
    #: The speeds are half-lives of 3/12/48 arriving calls. On a 1w level those
    #: forty-eight calls span months, so the slow line would describe a market
    #: that no longer exists. Fast data is where the estimator has enough
    #: observations for its own half-lives to mean anything.
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m")
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

    Every other strategy here holds for a fraction of an hour. Measured over
    53,372 resolutions, that is roughly a hundred times longer than the event
    it is trading:

    | resolved within | share | median push |
    | --- | ---: | ---: |
    | 30s | 53.1% | 2.47v |
    | 60s | 63.5% | 2.41v |
    | 120s | 72.2% | 2.33v |
    | 300s | 84.1% | 2.24v |

    **The median touch resolves in eighteen seconds**, and the fast ones carry
    the *larger* push - 2.47v inside thirty seconds against 2.24v for
    everything. Holding longer does not get more of the move; it gets less of
    it, on a resolution that has already happened, while remaining exposed to
    whatever comes next.

    That reframes two failures this session kept producing. A trade stopped
    before its move arrived and a trade that gave back profit are both what
    holding a twenty-second event for thirty minutes looks like from the
    account. This strategy holds for `hold_seconds` instead and lets the clock
    be the exit rather than the accident.

    **It is the same call as `level-scalp` with one difference**, deliberately,
    so the comparison says something. Same entries, same anchors, same stop
    rule, same target. Only the hold changes.

    A caveat on the measurement it rests on: about a tenth of recorded
    resolutions carry a negative duration, from bar timestamps being compared
    against quote clocks - a bug the tracker documents. The very fastest tail
    is therefore partly artefact. The median at eighteen seconds and the
    thirty- and sixty-second shares sit well clear of it.
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
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")


@register
class ThesisOnly(LevelStrategy):
    """The same call, with the stop moved out of the way. An experiment.

    Six of twelve stopped trades later reached the target they were aiming at,
    by between 3.7R and 25.7R - so the direction the level model produces is
    largely right and something in the execution is giving back money the
    thesis earned. That is a hypothesis, and every fix for it so far has been
    another adjustment to where the stop goes. This tests it directly by taking
    the stop out of the decision entirely and letting the trade end on its
    target or on the clock.

    **It is not stopless, and the difference matters.** A genuinely stopless
    trade on a leveraged account is how accounts die, and it would also break
    sizing - `lots` derives position size *from* the stop distance, so with no
    stop there is no size. What this does is move the stop far enough out that
    it stops being a trade decision and becomes a circuit breaker: at
    `thesis_stop_vol` volatility units it should almost never be reached, and
    when it is, something has gone wrong that no thesis anticipated.

    Money at risk is therefore unchanged and bounded exactly as everywhere
    else. What changes is that the position is much smaller, because the same
    risk spread over a stop several times wider buys proportionally fewer lots
    - which is the honest price of giving a trade room, and is itself part of
    what the comparison will show.

    **What it is for.** Run beside the others on the same signals it becomes a
    controlled comparison: same calls, same gates, same sizing rule, one
    difference. If it beats them, the stops were the problem and the fixes have
    been treating a symptom. If it loses, the theses were wrong and no amount
    of room would have saved them - which is worth knowing before another
    session is spent moving stops around.
    """

    name: ClassVar[str] = "thesis-only"
    description: ClassVar[str] = (
        "The level call with the stop moved out of the way - a circuit breaker "
        "rather than a trade decision. Exits on target or on the clock. An "
        "experiment to test whether the stops or the theses are wrong."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")

    def distances(
        self,
        level: float,
        entry: float,
        vol_bps: float,
        risk_vol: float,
        push_vol: float,
        interval: str = "",
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

    Every strategy here trades the direction the level model names, and the
    account has been going down while doing it. Two explanations fit that
    equally well from the outside: the direction is right and the execution
    gives it back, or the direction is wrong and better execution would only
    lose money faster. Everything built this session has assumed the first.
    Nothing has tested the second.

    This tests it directly. It takes the calls the model likes *best* - the
    gates run unchanged, on the side the call named, so it selects the same
    signals `level-scalp` selects - and then trades the opposite side. Same
    entries, same anchors, same stop rule, same target. One difference, and it
    is the one that matters.

    **What each outcome would mean.** If this loses roughly what the others
    lose, direction is not the problem and the execution work is aimed
    correctly. If it wins, the direction model is worse than nothing and the
    entries, stops and trails have been polishing a sign error - which would
    be the single most valuable thing this repo could learn, and the cheapest
    way to learn it is to have run the control from the start.

    **It is not a prediction that the model is backwards.** Anti-correlation
    strong enough to trade is rare and usually turns out to be a measurement
    artefact. The expected result is that it loses, and a control that is
    expected to lose is still worth running, because the alternative is
    continuing to assume the answer.

    A caveat that will matter when this is scored. The gates are
    direction-aware - the probability floor is a per-direction percentile, the
    base-rate floor reads `base_rate_up` - so this is not a clean sign flip of
    the whole system. It inverts the *trade* while keeping the *selection*,
    which is the comparison that isolates direction. A version that also
    inverted the selection would be a different strategy and a different
    question.
    """

    name: ClassVar[str] = "inverse"
    description: ClassVar[str] = (
        "The calls the model likes best, traded the other way. A control on "
        "whether the direction or the execution is what loses money."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")

    #: Fading a run that is still running is the worst version of what this
    #: does. The control is meant to test the *direction* the model produces,
    #: not to stand in front of momentum, and without this the two are
    #: confounded - a loss could be either.
    max_against_vol: ClassVar[float] = 1.5

    def orient(self, side: Side) -> Side:
        """The other one. This is the whole strategy."""
        return side.opposite


@register
class SweepAware(LevelStrategy):
    """The plain call, refused when the stop is standing in front of the door.

    `level-scalp` places its stop outside the level's zone and stops thinking
    about it. This one asks the further question: is that stop sitting between
    price and the next obvious pool of resting orders. If it is, a run at those
    orders takes this one on the way, and the trade is closed by a move that
    was never about it.

    Two pieces of evidence, both published by `structures.sweeps` and both
    derived from what is already recorded rather than declared:

    * `sweep_rate` - the share of this level's decisive interactions, on this
      side, that were `TRAP`: price through and back. A level that has been run
      four times in ten is telling you about itself directly, and no geometry
      has to be inferred to hear it.
    * `liquidity_beyond_vol` - how far to the next level out, on the side a
      sweep would travel. Close liquidity beyond is a reason for price to run
      this one; nothing within reach means the stop is not in front of an
      obvious target.

    The ratio of the two is what gets judged. A stop at 1.2v with liquidity at
    1.0v beyond sits *past* the pool, which is the worst place to stand; the
    same stop with the next level six units away is standing in open ground.

    **It refuses rather than adjusting.** Widening the stop to clear the pool
    would keep the trade and change what it costs, which sizes a worse trade
    smaller rather than declining it - and the sizing already assumes the stop
    is where the thesis is wrong, not where it is convenient.

    Unvalidated, like everything else here. The prior from elsewhere is
    discouraging for anything in this family, which is a reason to measure it
    against `level-scalp` on the same signals rather than to skip it.
    """

    name: ClassVar[str] = "sweep-aware"
    #: Every call `level-scalp` takes, minus the ones whose stop sits in front
    #: of resting liquidity. Listed after it, this would never fire.
    refines: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "level-scalp, refusing setups whose stop sits in front of resting liquidity."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")
    #: A sweep *is* momentum - a run through a level, taking the stops behind
    #: it. This strategy refuses when its stop sits in front of that liquidity,
    #: which is a statement about geometry; whether the run is still going is a
    #: separate question and it was not asking it. Nine of its twelve trades
    #: were stopped, more than any other strategy here.
    max_against_vol: ClassVar[float] = 1.5

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        feed = str(payload.get("feed") or "")
        settings = self.settings

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

        risk_vol = abs(_number(features, "risk_vol")) * self.stop_multiple
        exposure = risk_vol / beyond
        if exposure >= settings.sweep_max_exposure:
            return Refusal(
                "in_front",
                f"a {risk_vol:.2f}v stop reaches {exposure:.0%} of the way to "
                f"liquidity {beyond:.2f}v beyond",
                feed,
            )
        return None
