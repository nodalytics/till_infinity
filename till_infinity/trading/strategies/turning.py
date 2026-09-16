"""Trading the cycle reading directly, and the record it has to earn first.

Every other use of the z-score on this desk can only **remove** a trade:
`zma_gate` vetoes a `cycle-scalp` call the reading leans against, and
`cycles.capped_push` pulls a target in front of a predicted turn. This one
opens positions on it, which is a different and much stronger claim, so it
carries a much stronger condition.

## What the measurements say, because they are not encouraging

| where | result |
| --- | --- |
| Volatility, Step, Jump | AUC 0.493 to 0.504, on their own shuffles |
| real outright prices | 0.483 to 0.513, mean **0.5031** |
| **Boom and Crash** | hit **0.119 and 0.164** - an anti-signal with a mechanism |
| **constructed spreads** | AUC 0.662 to 0.722, hit **0.798 to 0.844** |

`research/zma.md`, `adapting.md` and `constructing.md`. On everything this
account can currently hold, the reading is a coin; on two families it is
reliably **wrong**; and the one place it works is a series that needs an account
at each of two venues.

So a strategy that traded this reading on today's book would be trading noise
on most of it and paying to be wrong on the rest. **That is why the condition
is not a threshold on the reading but a threshold on the reading's record.**

## The condition

Three things, and the third is what makes the first two safe to ship:

* the reading **agrees** - displacement and momentum pointing the same way,
  which is stricter than either alone because the thresholds are percentiles
  and something is always extreme;
* it agrees with **the direction the call already states**, so this narrows an
  existing thesis rather than inventing one;
* and this feed's own scored record clears `zma_min_calls` settled calls at
  `zma_min_accuracy` - **the same bar `zma_gate` defers to**.

On a family where the reading is an anti-signal the record never clears and
this strategy never trades it. On a series where it works - a constructed
spread, if one ever becomes holdable - it clears within a few hundred bars.
Nobody maintains a list of which families are which, and no global sign has to
be right everywhere at once, which is the trap `research/diverging.md` is about.

**Off unless named.** It is not in the default strategy set; `TRADING_STRATEGIES`
has to ask for it. A strategy this well evidenced against should be run
deliberately or not at all.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from ...structures import zma as zm
from ..models import Refusal, Side
from ..sizing import price_distance
from .scalper import LevelStrategy, _number
from .strategy import register


@register
class CycleTurn(LevelStrategy):
    """A 1m-to-1h entry that the 1h and 4h cycles both have to agree with.

    ## The shape

    **Entry anywhere from 1m to 1h.** The entry timeframe decides when the
    trade is taken, not what it is: every one of them is stopped on the 1h
    horizon and targeted on the 4h, so a 1m entry and a 1h entry aim at the
    same two distances and differ only in how promptly they notice. What keeps
    a fast entry from being one bar of noise is not the bar - it is the
    requirement below that the 1h and 4h cycles both already agree.

    **Anchored on 1h, 4h and 1d, and they are not worth the same.** The 4h is
    the mother cycle: without its agreement there is no agreement at all, and
    a 1h and a 1d that agree with each other while it does not are two
    timeframes agreeing about something the cycle they sit inside has already
    turned away from. So 4h is necessary - and not sufficient, because one
    reading is not an agreement however senior the timeframe. At least one of
    the other two has to agree with it.

    The anchors are read out of the call's own confluence: `structures` has
    already grouped the price into a zone across timeframes, so this reads that
    rather than asking a second, differently-wrong version of the same
    question. The call's own interval never counts - a timeframe cannot confirm
    itself - so a 1h entry is anchored on the 4h and the 1d.

    All three agreeing is recorded as `fully_aligned` and does not gate, which
    keeps the difference between "the mother and one" and "everything" in the
    record where a later comparison can use it.

    **Stop sized for the 1h horizon, target for the 4h**, which is the part
    worth being precise about. The signal publishes no per-timeframe structure
    prices - `last_high_structure` and the zone bounds all belong to the call's
    own interval - so "the stop comes from 1h" cannot mean "placed at the 1h
    swing". It means **sized for how far price travels in an hour**: a
    diffusive move over `T` scales as the square root of `T`, so a 15m call's
    stop is widened by `sqrt(3600/900) = 2` and its target by
    `sqrt(14400/900) = 4`. On a 1h entry the stop is unscaled and only the
    target stretches; on a 1m entry both stretch hard, by 7.7 and 15.5, which
    is the same pair of absolute distances arrived at from a smaller bar.

    That is a real implementation of the intent rather than a relabelling, and
    it is stated here because the alternative reading - that this finds the
    actual 1h swing low - is the one somebody will assume.

    **A break has to have happened first, and its line is the entry.** A change
    point with no broken structure behind it is a turn with nothing under it.
    The order is the claim: a run of higher lows fails, and *then* the cycle
    rolls over. The price that failed - the last higher low - was defended and
    then was not, so price returning to it is the moment worth taking: support
    that broke is tested as resistance, and the move through it took out
    whoever was leaning on it. `structures/breaks.py` finds that line; this
    refuses when there is none, when it points the other way from the cycle,
    and when price is not near enough to it for the line to be an entry at all.
    That last one is not a formality: measured on the desk, the median call
    sits twelve volatility units from its broken line, which is structure
    rather than a setup.

    **Then `ride`'s exit.** A trail half a volatility unit behind the best
    price, which `research/exiting.md` measured as the best of six policies
    over 31,820 replayed touches, with a break-even once the trade is in front.
    The target is deliberately far so the trail is what usually ends the trade.

    ## What it is gated on, and why that matters more than any of the above

    The reading this trades measures **AUC 0.5031 on real outright prices**,
    0.493 to 0.504 on the synthetics against their own shuffles, and a hit rate
    of **0.119 to 0.164 on Boom and Crash**, where it is an anti-signal with a
    known mechanism - see `research/zma.md`, `adapting.md` and `diverging.md`.
    The one place it works is a constructed spread this account cannot hold.

    So the condition is not a threshold on the reading, it is a threshold on
    the reading's **record on that feed**: `zma_min_calls` settled calls at
    `zma_min_accuracy` - the same two settings `zma_gate` reads, so nobody has
    to maintain two ideas of what earning a say means. On a family where the
    reading is an anti-signal that record never clears and this never trades
    there, with nobody maintaining a list of which families those are.

    **The record of the 4h series, not of the bar the call arrived on.** A
    record is a record of its own horizon: `edge_calls` on a 1m series counts
    one-minute-ahead calls, and the 1m series are exactly where the record
    looks best - 0.83 on usdcnh, 0.82 on eurgbp, against a median 0.56 at 4h.
    Reading the entry bar's record here would let a minute of evidence license
    a three-day position, and since the entry may be as fast as 1m the mistake
    would get louder the faster the trade. `zma_gate` still reads the entry
    bar's, because a scalp's horizon *is* the entry bar - the two now differ on
    purpose, each asking about the horizon it trades.

    The cost is that a feed with no 4h record trades nothing, which on the day
    this ships is every feed: the deepest 4h records on the desk are 168 to 184
    scored calls against the 200 the gate wants, six of them, and they arrive
    at six calls a day.
    """

    name: ClassVar[str] = "cycle-turn"
    refines: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "A 1m-to-1h reversion entry that the 1h and 4h cycles must both agree "
        "with, stopped on the 1h horizon and targeted on the 4h, trailed like "
        "`ride`. Only on feeds whose own scored record beats a coin."
    )
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m", "30m", "1h")
    #: Every anchor this reads. What each one is worth is below.
    context: ClassVar[tuple[str, ...]] = ("1h", "4h", "1d")
    needs_context: ClassVar[bool] = True

    #: **The mother cycle.** Without its agreement there is no anchor
    #: agreement at all: the others are read as confirmation of *it*, so a 1h
    #: and a 1d that agree with each other while 4h does not are two
    #: timeframes agreeing about something the cycle they sit inside has
    #: already turned away from. Refused outright rather than scored down.
    MOTHER: ClassVar[str] = "4h"
    #: The rest of the anchors. **4h is not allowed to agree alone** - at least
    #: one of these has to agree with it, which is what makes the agreement an
    #: agreement rather than one reading repeated. `1h` drops out when it is
    #: itself the entry: a timeframe cannot confirm itself, and `anchored`
    #: already excludes the call's own interval.
    SUPPORTING: ClassVar[tuple[str, ...]] = ("1h", "1d")

    #: How close the call has to sit to the broken line for that line to be an
    #: entry rather than a fact about the past. In volatility units of the
    #: entry bar, because the same gap is a different thing on gold and on a
    #: crypto pair - the unit every distance in this strategy is measured in.
    MAX_BREAK_GAP_VOL: ClassVar[float] = 2.0

    #: The horizons the stop and the target belong to, in seconds.
    STOP_HORIZON: ClassVar[float] = 3_600.0
    TARGET_HORIZON: ClassVar[float] = 14_400.0
    #: How far the scaling may stretch either distance. It exists because a
    #: horizon far enough past the entry asks for a target no market will
    #: reach: a 15m entry aiming at a **1d** horizon wants 9.8 units out, which
    #: the reward-to-risk gate would happily pass.
    #:
    #: **Sized so that no declared entry is capped at the declared horizons.**
    #: At 4.0 it was not, and the damage was silent: a 1m entry wants 7.7 and
    #: 15.5, and capping both at 4 does not tighten a trade evenly - it flattens
    #: the *ratio* between them, so the fast entries alone would have carried
    #: half the reward-to-risk of the slow ones while claiming the same design.
    #: The fastest entry against the 4h target needs `sqrt(14400/60) = 15.5`.
    #: `test_no_declared_entry_is_capped` fails if a faster entry or a longer
    #: horizon is added without revisiting this.
    MAX_SCALE: ClassVar[float] = 16.0

    #: **A position, not a scalp.** Its entry is 15m to 1h and its context is
    #: 4h and 1d, so the move it bets on takes days. Capped by the scalp
    #: ceiling it would be closed by the clock at thirty minutes and by the
    #: swing ceiling at six hours - which is how `research/spending.md`
    #: measured `snap` losing: ended by the timer rather than by being right or
    #: wrong, which teaches the journal nothing.
    style: ClassVar[str] = "position"
    #: Seventy-two hours. `hold_for` takes the smaller of this and
    #: `max_hold_position`, so the strategy asks and configuration decides.
    hold_seconds: ClassVar[float] = 72 * 3_600.0

    #: `ride`'s exit, measured as the best of six over 31,820 replayed touches.
    #: The target is far enough that the trail ends the trade in the ordinary
    #: case; 1.0 scored +0.228 against this one's +0.404 and 2.0 went negative.
    trail_vol: ClassVar[float] = 0.5
    target_multiple: ClassVar[float] = 1.0
    stop_multiple: ClassVar[float] = 1.0

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        feed = str(payload.get("feed") or "")

        agrees = _number(features, "zma_agrees")
        if not agrees:
            return Refusal(
                "cycle_quiet", "displacement and momentum do not point the same way", feed
            )

        side = Side.from_direction(str(payload.get("direction") or ""))
        if side is not None and (agrees > 0) != (side is Side.BUY):
            return Refusal(
                "cycle_against",
                f"the cycle expects {'a rise' if agrees > 0 else 'a fall'} "
                f"and the call says {side.value}",
                feed,
            )

        refused = self._without_a_break(feed, features, agrees)
        if refused is not None:
            return refused

        missing = self._unconfirmed(payload)
        if missing == (self.MOTHER,):
            return Refusal(
                "cycle_no_mother",
                f"the {self.MOTHER} cycle does not agree with this "
                f"{payload.get('interval') or '?'} call, which ends it whatever "
                f"the others say",
                feed,
            )
        if missing:
            return Refusal(
                "cycle_alone",
                f"only the {self.MOTHER} agrees - {'/'.join(missing)} would have "
                f"to as well for this to be an agreement",
                feed,
            )

        # **The record, not the reading.** Everything above is true on a feed
        # where this has never worked; only this knows the difference.
        #
        # **And the mother cycle's record, not the entry bar's.** A record is a
        # record of its own horizon: `zma_edge_calls` on a 1m series counts
        # one-minute-ahead calls, and this trade is stopped on the hour and
        # targeted at four - so a 1m series right 83% of the time says nothing
        # about it, however much it looks like permission. Reading the entry
        # bar's record here would let a minute of evidence license a three-day
        # position, and the faster the entry the louder that mistake gets.
        #
        # A feed whose 4h series has no record yet therefore trades nothing,
        # which is the right default: the absence of the number is the absence
        # of the evidence, and `_number` returning 0 falls through to the first
        # refusal below rather than to a trade.
        calls = _number(features, "zma_anchor_edge_calls")
        if calls < self.settings.zma_min_calls:
            return Refusal(
                "cycle_unproven",
                f"{calls:.0f} scored {zm.ANCHOR} calls on this feed, "
                f"{self.settings.zma_min_calls:.0f} needed before this trades it",
                feed,
            )
        rate = _number(features, "zma_anchor_edge_right") / max(calls, 1.0)
        if rate <= self.settings.zma_min_accuracy:
            return Refusal(
                "cycle_poor",
                f"the {zm.ANCHOR} reading is right {rate:.0%} of {calls:.0f} times here, "
                f"which is not past {self.settings.zma_min_accuracy:.0%}",
                feed,
            )
        return None

    def _without_a_break(
        self, feed: str, features: dict[str, float], agrees: float
    ) -> Refusal | None:
        """**The break comes first, and its line is what the entry is drawn at.**

        A change point that no break preceded is a turn with nothing behind it.
        The sequence that matters is a run of higher lows failing and *then* the
        cycle rolling over - the line that failed is a price that was defended
        and then was not, which is why price returning to it is the moment worth
        taking: support that broke is tested as resistance, and the move through
        it took out whoever was leaning on it.

        Refused rather than taken at the level, because a turn with no broken
        structure behind it is a different trade from the one this is gated to.
        """
        broke = _number(features, "break_side")
        if not broke:
            return Refusal(
                "no_break", "nothing broke before this turn - there is no line to enter at", feed
            )
        if (broke > 0) != (agrees > 0):
            return Refusal(
                "break_against",
                f"the last break turned {'up' if broke > 0 else 'down'} "
                f"and the cycle expects {'a rise' if agrees > 0 else 'a fall'}",
                feed,
            )
        line = _number(features, "break_price")
        if not line:
            return Refusal("break_priceless", "the break carries no line to enter at", feed)

        # **The line has to be within reach, or it is a fact about the past
        # rather than an entry.** The trade is taken *at* the broken level -
        # support that failed being tested as resistance - so a call twelve
        # volatility units away from it is not that trade, however correct the
        # break and the cycle both are. Measured on the desk over three hours:
        # the median call sat 12.3 units from its line and only 11 of 73 were
        # inside two, which is the shape of a condition that is meant to be
        # rare.
        level = _number(features, "level")
        vol_bps = _number(features, "vol_bps")
        if not level or not vol_bps:
            # The absence of the number is the absence of the evidence - the
            # same rule the record gate follows. Without a volatility there is
            # no saying whether the line is near, and "near" is the condition.
            return Refusal("break_unmeasured", "no volatility to measure the line against", feed)
        gap = abs(level - line) / price_distance(level, vol_bps, 1.0)
        if gap > self.MAX_BREAK_GAP_VOL:
            return Refusal(
                "break_far",
                f"the broken line is {gap:.1f} volatility units away, "
                f"past the {self.MAX_BREAK_GAP_VOL:.0f} this enters within",
                feed,
            )
        return None

    def _unconfirmed(self, payload: dict[str, Any]) -> tuple[str, ...]:
        """What is missing from the anchor agreement, mother cycle first.

        Two different failures, and they are not the same size. `4h` missing
        is the whole agreement gone - see `MOTHER`. `4h` present with nothing
        beside it is one reading, not an agreement, and the caller turns that
        into its own refusal.

        The call's own interval is excluded throughout: a timeframe cannot
        confirm itself, which is why a 1h entry is anchored on 4h and 1d.
        """
        interval = str(payload.get("interval") or "")
        agreeing = set(self.anchored(payload))
        if interval != self.MOTHER and self.MOTHER not in agreeing:
            return (self.MOTHER,)
        support = [t for t in self.SUPPORTING if t != interval]
        if support and not any(t in agreeing for t in support):
            return tuple(support)
        return ()

    def fully_aligned(self, payload: dict[str, Any]) -> bool:
        """Whether every anchor agrees, not just the two that gate. Recorded."""
        interval = str(payload.get("interval") or "")
        agreeing = set(self.anchored(payload))
        wanted = [t for t in (self.MOTHER, *self.SUPPORTING) if t != interval]
        return bool(wanted) and all(t in agreeing for t in wanted)

    def _horizon_scale(self, interval: str, horizon: float) -> float:
        """How much wider a distance is over `horizon` than over one bar of `interval`.

        Square root of time, because a diffusive move scales that way - the
        same convention `structures/vol` uses everywhere. Never below 1: this
        stretches a distance toward a slower horizon and must not shrink one
        toward a faster one, or a 1h entry would end up with a tighter stop
        than a 15m entry of the same thesis.
        """
        from ...structures.levels import SECONDS

        seconds = SECONDS.get(interval, 0.0)
        if seconds <= 0 or horizon <= seconds:
            return 1.0
        return min(math.sqrt(horizon / seconds), self.MAX_SCALE)

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
        """Stop on the 1h horizon, target on the 4h. See the class note."""
        stop_distance, target_distance = super().distances(
            level, entry, vol_bps, risk_vol, push_vol, interval, features=features, side=side
        )
        stop_distance *= self._horizon_scale(interval, self.STOP_HORIZON)
        target_distance *= self._horizon_scale(interval, self.TARGET_HORIZON)
        return stop_distance, target_distance
