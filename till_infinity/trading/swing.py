"""Swings: the same machinery, pointed at a longer horizon.

Split from `scalper.py` because the two answer different questions and the
file had stopped saying which was which - `approach-scalp` and `fade-to-value`
carry a scalp's name and hold for four hours, and finding that out meant
reading their class bodies.

**The swing contract**, shared by everything here: entry on 15m, 30m or 1h,
with 2h, 4h, 1d and 1w as compulsory context, and the timeframes below the
entry contributing momentum rather than agreement.

Entry was 1h alone and that turned out to be unreachable: over 2,123 signals,
**two arrived on 1h** - 0.09% - so every swing was starved before any of its
own conditions applied, and `origin-swing` never fired once. 15m and 30m carry
enough calls to be measurable while keeping the slow context and the slow hold.
The entry interval fixes the stop, and a tighter one buys more of the same idea
for the same money, which is the argument `swing-level` already made for
triggering below its anchor. The slow ones say *whether* - a level several hours of
auction respected - and the fast ones say *when*, through the momentum
ensemble. Asking a 1m series whether a weekly level is real is asking the wrong
series; asking a weekly bar to time an entry is asking it to answer four hours
late.

Holds are four 1h bars or more. A hold shorter than the entry bar is
incoherent - the trade would be closed on its clock before the bar it was
entered on had finished forming - and that is not a theoretical objection: when
the entries moved to 1h, the forty-five minute holds made every level read as
unreachable in the single bar available.

`LevelStrategy` still lives in `scalper.py`, which is where the translation
from a published call into an order is written. It is shared machinery rather
than a scalping detail, and moving it would be a second, larger change.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, ClassVar

from ..logging import get_logger
from ..structures.levels import SECONDS
from ..structures.timing import probability_within
from .book import Book, Seen
from .models import Intent, Refusal, Side, SymbolSpec, Tick, Verdict
from .scalper import Aim, LevelStrategy, _confluence, _features, _number
from .sizing import lots, price_distance, respects_stops_level, stop_for
from .strategy import register

log = get_logger(__name__)


@register
class ApproachScalp(LevelStrategy):
    """Trade *toward* the next level rather than reacting at the one price is on.

    The setup, in the desk's words: a level below price is something to sell
    down to, a level above is something to buy up to, once something confirms
    the direction. The confirmation here is the ordinary level call - a
    measured, directional reading at the level price is standing on - and the
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

    #: Forty-five minutes, longer than `max_hold`. A swing wearing a
    #: scalp's name - the name is historical, the hold is what decides.
    style: ClassVar[str] = "swing"
    description: ClassVar[str] = (
        "Buys up to the level above and sells down to the level below, on a "
        "confirming call. Targets the next level instead of the push."
    )
    #: Forty-five minutes. See the last paragraph above.
    #: Four 1h bars. A swing enters on 1h, and a hold shorter than its own
    #: entry bar is incoherent: the trade would be closed on its clock before
    #: the bar it was entered on had finished forming, and every level beyond
    #: about a unit reads as unreachable in the one bar available. That is not
    #: a conservative filter, it is a strategy that refuses everything - which
    #: is how the forty-five minute hold showed up the moment the entry moved
    #: to 1h.
    hold_seconds: ClassVar[float] = 4 * 3_600.0

    #: **The swing contract.** Entry on 1h; 2h, 4h, 1d and 1w are compulsory
    #: context; the timeframes below 1h are optional and contribute momentum
    #: rather than agreement.
    #:
    #: The division of labour is the point. The slow timeframes say *whether* -
    #: a level several hours of auction respected - and the fast ones say
    #: *when*, through the momentum accumulator. Asking a 1m series whether a
    #: weekly level is real is asking the wrong series; asking a weekly bar to
    #: time an entry is asking it to answer four hours late.
    entries: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h")
    context: ClassVar[tuple[str, ...]] = ("2h", "4h", "1d", "1w")
    needs_context: ClassVar[bool] = True

    #: The rejection has to show on 4h. A pin bar there is a claim that several
    #: hours of auction failed at this price; the same shape on the 1h entry
    #: bar is one hour's worth.
    candle_interval: ClassVar[str] = "4h"

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


@register
class Runner(LevelStrategy):
    """The same call with the target moved out of the way, so the trail decides.

    Every other strategy here closes at the push the level model predicted.
    That number is a *median* estimate of where price goes, and closing there
    keeps the half of the distribution below it while giving away the half
    above. Measured over 54,529 resolutions the tail is where the money is:

    | push reached | volatility units |
    | --- | ---: |
    | median | 2.24v |
    | p75 | 3.37v |
    | p90 | 4.93v |
    | p99 | 9.55v |

    Replayed against those resolutions at a 0.5v stop, letting the move run and
    exiting on a trail returned **+8.4R against +1.7R** for the same entries
    closed at a fixed target - roughly five times as much from identical calls,
    entirely in how they were exited.

    **`trail_vol` already half-does this and cannot finish the job.** The trail
    protects a runner once it is running, but the *target* still closes the
    trade at the modelled push, so on most trades the target is hit first and
    the trail never gets the chance to do anything. Raising the target is what
    lets the mechanism that already exists actually operate.

    So the target here sits at `target_multiple` times the modelled push rather
    than at it. It is deliberately not removed: `lots` and the reward-to-risk
    gate both need a target to exist, and a trade with no defined objective
    cannot be sized or refused. Placed near the ninetieth percentile of the
    push distribution, it stops being the thing that ends the trade in the
    ordinary case and becomes what `thesis-only` did for the stop - an outer
    bound rather than a decision.

    **What ends the trade instead** is the trail, tightened here because it now
    carries the exit rather than assisting it, and the clock. The risk this
    takes is the obvious one and it should be stated: a trail that has not been
    reached gives back everything between the peak and the stop, so this will
    show more round trips through profit than the fixed target does. That is
    the trade being made - a worse win rate for a longer right tail - and it is
    exactly what running it beside the others will measure.

    **One difference from `level-scalp`**, like `snap` and `thesis-only` before
    it: same entries, same anchors, same gates, same stop. Only the exit moves.
    """

    name: ClassVar[str] = "runner"

    #: Four 1h bars, for the same reason the other swings carry one: `runner`
    #: took `max_hold`, which is thirty minutes, and a 1h entry cannot be held
    #: for half its own bar.
    hold_seconds: ClassVar[float] = 4 * 3_600.0

    #: A swing by target rather than by clock: `target_multiple` 3.0 puts
    #: the exit past the modelled push, which is riding a move rather than
    #: taking a reaction.
    style: ClassVar[str] = "swing"
    description: ClassVar[str] = (
        "The level call with the target moved out past the push distribution, "
        "so the trail ends the trade rather than the cap. Trades the tail."
    )

    #: **The swing contract.** Entry on 1h; 2h, 4h, 1d and 1w are compulsory
    #: context; the timeframes below 1h are optional and contribute momentum
    #: rather than agreement.
    #:
    #: The division of labour is the point. The slow timeframes say *whether* -
    #: a level several hours of auction respected - and the fast ones say
    #: *when*, through the momentum accumulator. Asking a 1m series whether a
    #: weekly level is real is asking the wrong series; asking a weekly bar to
    #: time an entry is asking it to answer four hours late.
    entries: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h")
    context: ClassVar[tuple[str, ...]] = ("2h", "4h", "1d", "1w")
    needs_context: ClassVar[bool] = True

    #: The rejection has to show on 4h. A pin bar there is a claim that several
    #: hours of auction failed at this price; the same shape on the 1h entry
    #: bar is one hour's worth.
    candle_interval: ClassVar[str] = "4h"
    #: Three times the modelled push. With the push capped near 1.3v that lands
    #: around 4v - close to the ninetieth percentile of what touches actually
    #: reach, so it bounds the trade without being what normally ends it.
    target_multiple: ClassVar[float] = 3.0
    #: Tighter than the shared default because the trail is the exit here, not
    #: a safety net behind a target that fires first.
    trail_vol: ClassVar[float] = 1.0
    #: Protect the trade as soon as it has paid for its own risk.
    break_even_at: ClassVar[float] = 1.0


@register
class SwingLevel(LevelStrategy):
    """A slower trade: anchored on the daily, triggered as low as it can be.

    Everything else here is a scalp. This is the same machinery pointed at a
    longer horizon, and it exists mainly to show that the entry/anchor split is
    a real structure rather than a scalping detail.

    **The anchor and the entry are not the same timeframe, and the gap is the
    point.** The bias comes from 4h, 1d and 1w - where a level has enough
    history to mean something and enough distance to be worth crossing. The
    *trigger* is allowed as low as 15m, because the entry is what fixes the
    stop, and a stop measured on 15m is a fraction of one measured on 1d for
    the identical idea. That is risk reduction, not a different trade: same
    thesis, smaller distance to being wrong, so the same money buys more of it.

    It requires its anchor. A 1h call with nothing above it agreeing is a fast
    trade wearing a swing's hold, which is the worst combination available -
    the patience of the one and the evidence of the other.

    Given six hours rather than the scalpers' thirty minutes, because a daily
    level's push is measured in sessions. The hold is the setting most likely
    to be wrong here and it has never been measured; `max_hold` closing a
    winner early would look exactly like the strategy not working.
    """

    name: ClassVar[str] = "swing-level"

    #: Six hours on a daily-anchored level. The plainest swing here.
    style: ClassVar[str] = "swing"
    description: ClassVar[str] = (
        "Bias from 4h/1d/1w, trigger as low as 15m for a tighter stop. Held for hours."
    )

    #: **The swing contract.** Entry on 1h; 2h, 4h, 1d and 1w are compulsory
    #: context; the timeframes below 1h are optional and contribute momentum
    #: rather than agreement.
    #:
    #: The division of labour is the point. The slow timeframes say *whether* -
    #: a level several hours of auction respected - and the fast ones say
    #: *when*, through the momentum accumulator. Asking a 1m series whether a
    #: weekly level is real is asking the wrong series; asking a weekly bar to
    #: time an entry is asking it to answer four hours late.
    entries: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h")
    context: ClassVar[tuple[str, ...]] = ("2h", "4h", "1d", "1w")
    needs_context: ClassVar[bool] = True

    #: The rejection has to show on 4h. A pin bar there is a claim that several
    #: hours of auction failed at this price; the same shape on the 1h entry
    #: bar is one hour's worth.
    candle_interval: ClassVar[str] = "4h"
    #: Six hours. A daily level does not resolve inside a scalper's half hour.
    hold_seconds: ClassVar[float] = 6 * 3_600.0
    #: More room than a scalp, because the level is placed on slower data and
    #: the noise around it is proportionally larger.
    stop_multiple: ClassVar[float] = 1.5
    #: Inherited from `high-timeframe`, removed as a near-duplicate of this.
    #: The two shared entries, context and the requirement that a higher
    #: timeframe agree; what it had that this did not is below.
    #:
    #: **It rests its entry.** A swing thesis measured on 4h is not made or
    #: lost by filling this minute, so it waits for price to come back to the
    #: level rather than paying the spread to chase - and says so itself rather
    #: than inheriting whatever the deployment is tuned to, because an entry
    #: that quietly became a market order is not the same trade.
    pullback_fraction: ClassVar[float] = 1.0
    #: Protection scaled to the horizon rather than inherited. A 1R break-even
    #: is right for a trade resolving in eighteen seconds and wrong for one
    #: measured in sessions, where ordinary retracement passes 1R before the
    #: thesis has begun and a stop moved there is a scratch waiting to happen.
    break_even_at: ClassVar[float] = 1.5
    #: Wide enough to survive a session's pullback rather than a minute's.
    trail_vol: ClassVar[float] = 3.0
    #: Double the scalpers' momentum filter. 1.5v is a real run on a 3m chart
    #: and ordinary noise on a 4h one, so their number here would refuse most
    #: entries for movement this timeframe does not consider movement.
    max_against_vol: ClassVar[float] = 3.0


@register
class OriginSwing(LevelStrategy):
    """Run from one origin to the other, entering at whichever price reaches first.

    An origin is where volatility turned - the last opposing bar before an
    impulse, kept as a zone rather than a price because the zone is what price
    reacts to. See `structures/origins.py`.

    **The trade is the space between two of them.** When price sits between an
    origin above and an origin below there are two places worth trading and one
    question: which does price reach first. It arrives, it is confirmed there,
    and the trade runs to the opposite origin. Long from the one below, short
    from the one above; the far edge is the target either way.

    That makes the target a **structure** rather than a multiple of the
    modelled push. `expected_push_vol` is a forecast about the next few bars,
    and over a swing horizon the honest answer to "how far does this go" is "to
    the next place that stopped it last time".

    **Two confirmations at the origin, and they are different questions.** The
    4h rejection candle says the auction failed there; the momentum ensemble
    below 1h says it is failing *now*. The candle is slower, stronger, and has
    to wait for a close; the accumulator reads the same event tick by tick.
    Both are required here rather than the disjunction the scalps use - a swing
    can afford to wait, and an origin price merely touched is not an origin
    that rejected it.

    **The stop sits beyond the rejection, by an amount the instrument sets.**
    Past the far edge of the origin zone plus a volatility buffer: inside the
    zone is where the wicks are, and a stop placed there is stopped by the very
    rejection it is trading.

    **What is claimed and what is not.** Origin *freshness* separates - never
    revisited returned 1.136R against 0.822R twice revisited. Origin
    *proximity* did not: it read +0.299 on the first live sample and -0.166
    over 49,619. So nothing here scores on distance. The bracket is used as
    geometry - where to enter, where to aim, where the stop clears - which is a
    placement decision this repository has not measured either way.
    """

    name: ClassVar[str] = "origin-swing"
    style: ClassVar[str] = "swing"
    description: ClassVar[str] = (
        "Between two origins: enter where price arrives first, run to the other."
    )

    entries: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h")
    context: ClassVar[tuple[str, ...]] = ("2h", "4h", "1d", "1w")
    needs_context: ClassVar[bool] = True

    #: The rejection has to show on 4h - several hours of auction failing at
    #: this price, rather than one hour's worth on the entry bar.
    candle_interval: ClassVar[str] = "4h"

    #: Six hours, like `swing-level`. The distance between two origins is not
    #: covered inside a scalper's half hour.
    hold_seconds: ClassVar[float] = 6 * 3_600.0

    #: More room than a scalp, for the reason `swing-level` takes it: the level
    #: is placed on slower data and the noise around it is proportionally
    #: larger.
    stop_multiple: ClassVar[float] = 1.5

    #: Rest the entry. The thesis is that price comes to the origin, so paying
    #: the spread to chase it there is paying for the thing being waited for.
    pullback_fraction: ClassVar[float] = 1.0

    #: Protection scaled to the horizon. A 1R break-even is right for a trade
    #: resolving in seconds and wrong for one measured in sessions, where
    #: ordinary retracement passes 1R before the thesis has begun.
    break_even_at: ClassVar[float] = 1.5

    #: Both witnesses, not either. See `needs_both_witnesses`.
    needs_both_witnesses: ClassVar[bool] = True

    #: More than half the sub-hour timeframes pointing the trade's way. An
    #: origin price merely touched is not an origin that rejected it, and one
    #: timeframe moving alone is what a touch looks like.
    min_momentum_agree: ClassVar[float] = 0.5

    #: How far past the origin's far edge the stop sits, in volatility units,
    #: so the instrument's own noise sets the buffer rather than a fixed number
    #: of points.
    CLEARANCE_VOL: ClassVar[float] = 0.5

    #: How many times the origin may already have been returned to.
    #:
    #: Measured over 3,412 returns: the first holds 63.5%, the second 55.6%,
    #: against a driftless-walk null near 33%. Freshness helps and it is not
    #: decisive - the third and fourth returns are no worse than the second, and
    #: ger40 improved with every visit - so this prefers fresh origins rather
    #: than demanding them. See `research/origins.md`.
    max_revisits: ClassVar[float] = 1.0

    #: How far into the zone price must be before the origin counts as reached.
    #: Zero would fire on the outer edge, which price grazes without trading
    #: there.
    REACH_VOL: ClassVar[float] = 0.25

    def __init__(self, settings) -> None:
        super().__init__(settings)
        #: Which origin price arrived at, decided in `quality` and read by
        #: `orient`. Reset on every call so a stale side cannot be inherited by
        #: the next signal - the gate chain runs `quality` before `orient` for
        #: exactly this ordering.
        self._facing: Side | None = None

    def orient(self, side: Side) -> Side:
        """Which origin price is standing at decides the side.

        At the lower origin the trade is long to the upper one; at the upper it
        is short to the lower. The published direction is about the level, and
        this strategy is not trading the level.
        """
        return self._facing or side

    def bracket(self, features: dict[str, float]) -> tuple[float, float] | None:
        """`(below_high, above_low)` - the two inner edges, or None.

        Both ends or nothing. One origin gives an entry with no structural
        target, which is the ordinary push trade every other strategy here
        already takes.
        """
        if "origin_below_high" not in features or "origin_above_low" not in features:
            return None
        below_high = float(features["origin_below_high"])
        above_low = float(features["origin_above_low"])
        if below_high >= above_low:
            return None
        return below_high, above_low

    def quality(
        self, feed: str, features: dict[str, float], side: Side, interval: str = ""
    ) -> Refusal | None:
        self._facing = None
        refusal = super().quality(feed, features, side, interval)
        if refusal is not None:
            return refusal

        if self.bracket(features) is None:
            return Refusal("no_bracket", "no origin above and below to run between", feed)

        # `origin_*_vol` is the gap to that zone's near edge, so a price inside
        # the zone reports zero or less.
        to_above = features.get("origin_above_vol")
        to_below = features.get("origin_below_vol")
        if to_above is None or to_below is None:
            return Refusal("no_bracket", "the bracket carries no distances", feed)
        if to_below <= self.REACH_VOL and to_below <= to_above:
            self._facing = Side.BUY
            revisits = features.get("origin_below_revisits")
        elif to_above <= self.REACH_VOL:
            self._facing = Side.SELL
            revisits = features.get("origin_above_revisits")
        else:
            near = min(to_above, to_below)
            return Refusal(
                "not_at_origin",
                f"price is {near:.2f}v from the nearer origin, past the "
                f"{self.REACH_VOL:.2f}v that counts as trading there",
                feed,
            )

        # Freshness, which is the one origin reading that has measured. A
        # missing count is not a stale origin - it is an unknown one, and
        # refusing on it would stand this strategy down on every feed whose
        # origins have not been published yet.
        if revisits is not None and float(revisits) > self.max_revisits:
            self._facing = None
            return Refusal(
                "stale_origin",
                f"this origin has been returned to {float(revisits):.0f} times, "
                f"over the {self.max_revisits:.0f} it is worth trading",
                feed,
            )
        return None

    def _anchored_stop(
        self,
        spec: SymbolSpec,
        features: dict[str, float],
        side: Side,
        level: float,
        risk_distance: float,
        unit: float,
    ) -> float:
        """Beyond the origin being traded, not beyond the level.

        The level is not what this trade is about. Anchoring there put the stop
        on the wrong side of the fill outright - a long entered at the lower
        origin, 2v under the level, got a stop *above* its own entry and was
        refused as already through.

        The far edge of the zone plus a volatility unit of clearance. Inside
        the zone is where the wicks are, and a stop placed there is taken out
        by the rejection the trade exists to trade.
        """
        edge = features.get("origin_below_low" if side is Side.BUY else "origin_above_high")
        if edge is None:
            return super()._anchored_stop(spec, features, side, level, risk_distance, unit)
        clearance = self.CLEARANCE_VOL * unit
        beyond = edge - clearance if side is Side.BUY else edge + clearance
        return spec.round_price(beyond)

    def target(self, context: Aim) -> float | Refusal:
        """The opposite origin's near edge."""
        pair = self.bracket(context.features)
        if pair is None:
            return Refusal("no_bracket", "the bracket went away between gate and target", "")
        below_high, above_low = pair
        far = above_low if context.side is Side.BUY else below_high
        return context.spec.round_price(far)


@register
class FadeToValue(LevelStrategy):
    """Price the market, then take the stance the distance implies.

    The thesis in its plainest form. Every other strategy here reacts *at* a
    level: price arrives, the level's record says what usually happens, the
    trade is taken there. This one asks the question the README opens with -
    what is this worth, and where is it trading - and takes the difference.

    **Fair value is the best-evidenced level within reach**, not the nearest
    one. A price the instrument has turned at forty times is a claim about
    value; one it clipped twice is barely a claim at all, and taking the
    closest level regardless would make the estimate a function of where price
    happens to be standing. The book is scanned and the level with the most
    decisive history wins, provided it has enough to speak.

    **The stance is arithmetic.** Fair value above the market is a long, below
    it is a short. Nothing is forecast: the side falls out of the valuation,
    which is the property the whole design exists to protect.

    **The distance has to clear the noise before it is a mispricing.** Fair
    value is a distribution and volatility is its width, so a price one unit
    away is inside the estimate and says nothing. `fade_min_distance_vol` is
    where a distance starts being a statement.

    **And it stops short of the target**, for the reason `approach-scalp` does:
    price is not drawn to a level. The distance is an opportunity because the
    level is a place with statistics attached, not because anything pulls price
    to it, and the last stretch into the zone is exactly the part that was
    measured and did not survive.

    The stop goes beyond the level price is *at* - the one that triggered the
    signal - because that is where this reading of value is wrong. If price
    settles through the level it just arrived at, the estimate that said it was
    cheap here was the thing that failed.
    """

    name: ClassVar[str] = "fade-to-value"

    #: Forty-five minutes, and a thesis about where value is rather than
    #: about the next few ticks.
    style: ClassVar[str] = "swing"
    description: ClassVar[str] = (
        "Takes the distance from spot to the best-evidenced level. The thesis, plainly."
    )

    #: **The swing contract.** Entry on 1h; 2h, 4h, 1d and 1w are compulsory
    #: context; the timeframes below 1h are optional and contribute momentum
    #: rather than agreement.
    #:
    #: The division of labour is the point. The slow timeframes say *whether* -
    #: a level several hours of auction respected - and the fast ones say
    #: *when*, through the momentum accumulator. Asking a 1m series whether a
    #: weekly level is real is asking the wrong series; asking a weekly bar to
    #: time an entry is asking it to answer four hours late.
    entries: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h")
    context: ClassVar[tuple[str, ...]] = ("2h", "4h", "1d", "1w")
    needs_context: ClassVar[bool] = True

    #: The rejection has to show on 4h. A pin bar there is a claim that several
    #: hours of auction failed at this price; the same shape on the 1h entry
    #: bar is one hour's worth.
    candle_interval: ClassVar[str] = "4h"
    #: Four 1h bars. A swing enters on 1h, and a hold shorter than its own
    #: entry bar is incoherent: the trade would be closed on its clock before
    #: the bar it was entered on had finished forming, and every level beyond
    #: about a unit reads as unreachable in the one bar available. That is not
    #: a conservative filter, it is a strategy that refuses everything - which
    #: is how the forty-five minute hold showed up the moment the entry moved
    #: to 1h.
    hold_seconds: ClassVar[float] = 4 * 3_600.0

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.book = Book()

    def observe(self, payload: dict[str, Any]) -> None:
        """Remember every level published; the valuation is built from them."""
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
                touches=_number(features, "record_n") or _number(features, "own_touches"),
                when=float(payload.get("time") or time.time()),
            ),
            vol_bps,
        )

    def fair_value(self, feed: str, unit: float, spot: float) -> Seen | None:
        """The best-evidenced level within reach, or None.

        Evidence rather than proximity, and the difference is the whole point:
        an estimate of value that changed every time price drifted toward a
        different line would not be an estimate of anything.
        """
        candidates = [
            seen
            for seen in self.book.levels(feed)
            if seen.touches >= self.settings.fade_min_touches
            and abs(seen.price - spot) / unit <= self.settings.fade_max_distance_vol
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda s: (s.touches, -abs(s.price - spot)))

    def consider(
        self,
        payload: dict[str, Any],
        *,
        spec: SymbolSpec,
        tick: Tick,
        equity: float,
        # Accepted and unused. The service passes these to every strategy, and
        # a strategy that does not size on them must still be callable - the
        # version of this without them stopped the trading service outright
        # with `FadeToValue.consider() got an unexpected keyword argument
        # 'positions'`, because `FadeToValue` overrides `consider` and the
        # signature was only widened on the base and the scalper.
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
            return Refusal("interval", f"{interval} is not traded here", feed)

        features = _features(payload)
        vol_bps = _number(features, "vol_bps")
        here = _number(features, "level")
        if vol_bps <= 0 or here <= 0:
            return Refusal("volatility", "the call carries no volatility unit", feed)

        spot = tick.mid
        unit = price_distance(spot, vol_bps, 1.0)
        if unit <= 0:
            return Refusal("volatility", "no volatility unit to price against", feed)

        value = self.fair_value(feed, unit, spot)
        if value is None:
            return Refusal(
                "no_value",
                f"no level with {settings.fade_min_touches:.0f}+ interactions within "
                f"{settings.fade_max_distance_vol:.1f}v of {spot:.5g}",
                feed,
            )

        distance = (value.price - spot) / unit
        if abs(distance) < settings.fade_min_distance_vol:
            return Refusal(
                "at_value",
                f"{abs(distance):.2f}v from fair value at {value.price:.5g}, inside the "
                f"{settings.fade_min_distance_vol:.2f}v that makes it a statement",
                feed,
            )

        # The stance is arithmetic once the valuation exists.
        side = Side.BUY if distance > 0 else Side.SELL

        # The same gates every other strategy clears. This overrides `consider`
        # entirely, so it used to run none of them - and being first in the
        # running order, it was taking most of the trades through the only
        # ungated path in the system while the other three were refused by
        # floors it never saw.
        #
        # The chase gate is deliberately *not* applied here and the difference
        # is real rather than an oversight: chasing means filling far from the
        # level the call was measured at, and this strategy's whole premise is
        # being far from fair value. That gate would refuse every trade it ever
        # wanted, by construction.
        bad = self.quality(feed, features, side, interval)
        if bad is not None:
            return bad

        entry = tick.entry(side)

        # Stop beyond the level price is standing at, outside its zone: that is
        # where this reading of value is wrong.
        risk_vol = abs(_number(features, "risk_vol")) or 1.0
        edge = _number(features, "zone_low") if side is Side.BUY else _number(features, "zone_high")
        stop = spec.round_price(
            stop_for(here, side, risk_vol * unit, zone_edge=edge, clearance=unit * 0.25)
        )
        # Short of fair value, because price is not drawn to it. See magnet.md.
        target = spec.round_price(value.price - side.sign * settings.fade_buffer_vol * unit)

        if (side is Side.BUY and entry <= stop) or (side is Side.SELL and entry >= stop):
            return Refusal("through", f"price is already past {stop:.5g}", feed)
        if (target - entry) * side.sign <= 0:
            return Refusal("at_value", "the buffer puts the target behind price", feed)

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
        # and the trade is held for many. The move this one expects is the distance
        # to fair value, which is what it aims at instead of a modelled push.
        aimed_vol = abs(target - entry) / unit if unit else 0.0
        protect_at, protect_trail = self.protection(interval, aimed_vol)
        self.wanted += 1
        return Intent(
            feed=feed,
            symbol=spec.symbol,
            side=side,
            volume=sized.volume,
            entry=entry,
            stop=stop,
            target=target,
            reason=(
                f"{abs(distance):.2f}v {'below' if side is Side.BUY else 'above'} fair "
                f"value {value.price:.5g} ({value.touches:.0f} interactions)"
            ),
            interval=interval,
            confluence=_confluence(payload),
            # Carried from the signal so a closed trade can be added up
            # against the level that produced it. Levels drift under the
            # filter, so the price is not a name.
            level_id=str(payload.get("level_id") or ""),
            features={**features, "distance_vol": distance, "fair_value": value.price},
            risk_money=sized.risk_money,
            stop_vol=abs(entry - stop) / unit if unit else 0.0,
            stop_scale=self.stop_floor_vol(interval) / (self.settings.min_stop_vol or 1.0),
            hold=self.hold_for(interval, self.settings.max_hold),
            break_even_at=protect_at,
            trail_vol=protect_trail,
        )
