"""The level strategies: what to do with a call when one arrives.

`structures` publishes a `LEVEL` signal when price reaches somewhere it has
repeatedly turned and the history says which way it goes from there. The signal
carries a price, a direction, a probability against its own base rate, the push
it expects and the risk it runs — the last two in volatility units — and says
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

import time
from dataclasses import dataclass
from typing import Any, ClassVar

from ..structures.levels import SECONDS
from ..structures.timing import probability_within
from .book import Book, Seen
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
    checks in `consider` is not arbitrary — the cheap refusals about the signal
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

    def distances(
        self, level: float, entry: float, vol_bps: float, risk_vol: float, push_vol: float
    ) -> tuple[float, float]:
        """Stop distance from the level, target distance from the entry."""
        return (
            price_distance(level, vol_bps, risk_vol * self.stop_multiple),
            price_distance(entry, vol_bps, push_vol * self.target_multiple),
        )

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

        probability = _number(features, "probability")
        if probability < settings.min_probability:
            return Refusal(
                "probability",
                f"{probability:.0%} against a {settings.min_probability:.0%} floor",
                feed,
            )

        edge = abs(_number(features, "edge"))
        if edge < settings.min_edge:
            return Refusal("edge", f"{edge:.3f} against a {settings.min_edge:.3f} floor", feed)

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

        entry = tick.entry(side)
        risk_distance, push_distance = self.distances(level, entry, vol_bps, risk_vol, push_vol)
        stop = spec.round_price(stop_for(level, side, risk_distance))
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
        target = aimed

        # The stop is anchored to the level, so a fill on the far side of it —
        # price ran through while this was being decided — leaves a stop that is
        # already behind price. That is not a trade to shrink; it is a trade
        # that has already been invalidated.
        if (side is Side.BUY and entry <= stop) or (side is Side.SELL and entry >= stop):
            return Refusal("through", f"price is already past the stop at {stop:.5g}", feed)

        broker_says = respects_stops_level(spec, entry, stop, target)
        if broker_says:
            return Refusal("stops_level", broker_says, feed)

        sized = lots(
            spec,
            equity=equity,
            risk_fraction=settings.risk_fraction,
            stop_distance=abs(entry - stop),
            max_risk_money=settings.max_risk_money,
        )
        if not sized.ok:
            return Refusal("size", sized.reason, feed)

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
            features=features,
            risk_money=sized.risk_money,
            hold=self.hold_seconds,
        )


@register
class LevelScalp(LevelStrategy):
    """The plain reading: take the call as published."""

    name: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "Trade a level call in the direction it states, stop beyond the level, "
        "target the expected push. The default."
    )


@register
class ConfluenceScalp(LevelStrategy):
    """Only levels more than one timeframe agrees on.

    The claim is the one the level model already makes about itself: a price
    that several timeframes have independently placed a level at is one
    structure seen several times, not several findings. The higher timeframe
    carries the significance and the lower the placement.

    Taking fewer trades for that reason needs paying for, so the stop is given
    half a volatility unit more room — a confirmed level is worth more but is
    not more precisely located — and the target is left where the model put it.
    Whether the trade-off is worth it is a question for the journal, which is
    why this is a separate named strategy rather than a flag on the other one.
    """

    name: ClassVar[str] = "confluence-scalp"
    description: ClassVar[str] = (
        "Only calls confirmed by another timeframe, with a wider stop. Fewer trades."
    )
    stop_multiple: ClassVar[float] = 1.5

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        agreed = _confluence(payload)
        interval = str(payload.get("interval") or "")
        others = [t for t in agreed if t != interval]
        if not others:
            return Refusal(
                "confluence",
                "no other timeframe has a level here",
                str(payload.get("feed") or ""),
            )
        return None


@register
class MomentumScalp(LevelStrategy):
    """Only calls that point the way the recent calls have been pointing.

    score.md §2 keeps three exponential averages of its score and treats their
    agreement as the confidence: "the fast line is what is happening, the slow
    line is the context". The same three speeds are kept here over the *signed*
    edge of the calls arriving for each instrument, and a trade is taken only
    when all three agree with the direction it states.

    What that buys is a filter against calls fighting their own context — a
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
class ApproachScalp(LevelStrategy):
    """Trade *toward* the next level rather than reacting at the one price is on.

    The setup, in the desk's words: a level below price is something to sell
    down to, a level above is something to buy up to, once something confirms
    the direction. The confirmation here is the ordinary level call — a
    measured, directional reading at the level price is standing on — and the
    target is the next level the book knows about in that direction.

    So the geometry is inverted from the other strategies. They enter at a
    level and take the expected push; this one enters *on* a call and exits at
    a level. The stop is unchanged, still anchored beyond the confirming level,
    because that is still what makes the read wrong.

    **What the repository already knows about this, stated up front.**
    [magnet.md](../../docs/magnet.md) tested whether levels pull price and
    found they do not: across 22,219 evaluation bars a level was reached within
    twenty bars 44.9% of the time against 49.5% for an arbitrary price the same
    distance away, and with the day held fixed the gap is nine-tenths of a
    point and indistinguishable from zero. So this strategy is **not** an
    attraction bet, and it is built so as not to become one by accident:

    * the target stops `approach_buffer_vol` **short** of the level, because
      the last quarter unit into the zone is exactly the part the measurement
      says nothing supports;
    * the distance is checked against `structures.timing`, the same
      first-passage model magnet.md used as its baseline, and refused when
      diffusion alone says the move is unlikely inside the hold. A level is
      therefore chosen as a target because it is a price the model has
      statistics at and a plausible place to be taken out, not because being a
      level makes it more likely to be reached.

    What is left after that is a rule for choosing a *target distance*, which
    the null does not touch, on an entry that is separately measured.

    **It is given longer to work.** The desk's observation is that this takes
    twenty to thirty minutes to deliver; the module's default hold is thirty,
    which would close a good trade at the moment it started paying. So this
    strategy asks for forty-five and that is why.
    """

    name: ClassVar[str] = "approach-scalp"
    description: ClassVar[str] = (
        "Buys up to the level above and sells down to the level below, on a "
        "confirming call. Targets the next level instead of the push."
    )
    #: Forty-five minutes. See the last paragraph above.
    hold_seconds: ClassVar[float] = 2_700.0

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.book = Book()

    def observe(self, payload: dict[str, Any]) -> None:
        """Remember every level published, whatever is decided about it."""
        if not self.wants(payload):
            return
        features = _features(payload)
        price = _number(features, "level")
        vol_bps = _number(features, "vol_bps")
        if price <= 0 or vol_bps <= 0:
            return
        self.book.observe(
            str(payload.get("feed") or ""),
            Seen(
                price=price,
                interval=str(payload.get("interval") or ""),
                probability=_number(features, "probability"),
                strength=_number(features, "strength"),
                touches=_number(features, "own_touches"),
                when=float(payload.get("time") or time.time()),
            ),
            vol_bps,
        )

    def target(self, context: Aim) -> float | Refusal:
        feed = str(context.payload.get("feed") or "")
        settings = self.settings
        unit = price_distance(context.entry, context.vol_bps, 1.0)
        if unit <= 0:
            return Refusal("volatility", "no volatility unit to measure the approach in", feed)

        aim = self.book.toward(feed, context.entry, context.side.sign)
        if aim is None:
            side = "above" if context.side.sign > 0 else "below"
            return Refusal(
                "no_target",
                f"no known level {side} {context.entry:.5g} to trade toward "
                f"({self.book.count(feed)} in the book)",
                feed,
            )

        distance_vol = abs(aim.price - context.entry) / unit
        if distance_vol < settings.approach_min_vol:
            return Refusal(
                "too_close",
                f"the next level is {distance_vol:.2f}v away, inside the "
                f"{settings.approach_min_vol:.2f}v floor",
                feed,
            )
        if distance_vol > settings.approach_max_vol:
            return Refusal(
                "too_far",
                f"the next level is {distance_vol:.2f}v away, past the "
                f"{settings.approach_max_vol:.2f}v ceiling",
                feed,
            )

        # How many bars of this timeframe fit in the hold, and what a driftless
        # walk says about covering the distance in them. This is magnet.md's
        # own baseline, used here as a floor rather than as a claim.
        interval = str(context.payload.get("interval") or "")
        bars = self._bars(interval)
        reach = probability_within(distance_vol, bars) if bars > 0 else 0.0
        if reach < settings.approach_min_reach:
            return Refusal(
                "unreachable",
                f"{distance_vol:.2f}v in {bars:.0f} bars is a {reach:.0%} chance, "
                f"under the {settings.approach_min_reach:.0%} floor",
                feed,
            )

        # Stop short of the level, on the near side. See the class docstring.
        buffer = settings.approach_buffer_vol * unit
        target = aim.price - context.side.sign * buffer
        if (target - context.entry) * context.side.sign <= 0:
            return Refusal(
                "too_close",
                f"the buffer puts the target at or behind {context.entry:.5g}",
                feed,
            )
        return context.spec.round_price(target)

    def _bars(self, interval: str) -> float:
        """Bars of `interval` inside this strategy's hold."""
        seconds = SECONDS.get(interval, 0.0)
        hold = self.hold_seconds or self.settings.max_hold
        return hold / seconds if seconds > 0 else 0.0
