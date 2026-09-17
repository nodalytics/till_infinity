"""The z-score's *displacement* as a scalp, at the line a structure broke.

`cycle-turn` trades the same reading as a position: a 4h mother cycle, a 1h
stop, a 4h target, held for days, and licensed by the 4h record because that is
the horizon it bets on. This is the same idea one tier down - 1h mother, 15m
and 30m supporting, entries from 1m to 15m - and it differs from it in one more
way that matters more than the timeframes.

## Displacement gates; agreement sizes

`cycle-turn` requires `zma_agrees`: displacement **and** momentum pointing the
same way. That is the stricter reading and it fires on about **1.5%** of the
calls this desk publishes - 11 of 754 over two days - which is why that
strategy has never traded. Stricter is not the same as better, and here the
desk's own measurement says it is worse: `research/adapting.md` scored the
continuous displacement call beating the agreement flag by **2.5 to 7.8
points** at an identical bet count on three OU controls.

There is also a consistency argument, and it is the one that decided this.
`edge_calls` and `edge_right` - the record both strategies are licensed by -
score the *continuous* call. Gating on `agrees` while licensing on that record
asks one question and checks the answer to another.

So displacement is the gate, and agreement becomes **conviction**: a call the
momentum has already begun to confirm is the same trade with more behind it, so
it gets full risk, and displacement alone gets less. Sizing down rather than
up, because a multiplier that enlarges is a way to exceed a risk budget through
a setting nobody reads as a risk setting - the rule `scaling.py` states and
every other multiplier here obeys.

## A break first, and the line is the entry

Unchanged from `cycle-turn`, because it is the same claim: a change point with
no broken structure behind it is a turn with nothing under it. A run of higher
lows fails, and *then* the reading stretches. The price that failed was
defended and then was not, so price returning to it is the moment worth taking
- and the entry rests there rather than paying the spread to enter wherever
price happens to be when the call lands. See `structures/breaks.py`.

## The record it is licensed by

**The entry bar's own**, and this is where it parts company with `cycle-turn`
deliberately. That strategy reads the 4h record because a trade stopped on the
hour and targeted at four hours is a 4h bet, and a 1m series being right 83% of
the time says nothing about it. A scalp's horizon *is* the entry bar, so the
entry bar's record is the honest one - the same bar `zma_gate` defers to.

Which is also where the evidence is: 28 of the 1m series on this desk have two
hundred scored calls beating 52%, against **none** at 4h until a backfill put
them there.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..models import Refusal, Side
from ..sizing import price_distance
from .scalper import LevelStrategy, _number
from .strategy import register


@register
class CycleTurnScalp(LevelStrategy):
    """A 1m-to-15m reversion scalp at a broken line, under an agreeing 1h cycle.

    ## The shape

    **Entry on 1m to 15m**, stopped and targeted on the entry bar's own scale.
    No horizon stretching: this is a scalp, and a scalp that aims at a slower
    horizon is a position trade with a scalp's stop.

    **The 1h is the mother cycle.** Without its agreement there is no agreement
    at all - a 15m and a 30m agreeing with each other while the hour does not
    are two timeframes agreeing about something the cycle they sit inside has
    already turned away from. And it may not agree alone: one reading is not an
    agreement however senior, so at least one of the 15m and 30m has to agree
    with it. The call's own interval never counts, so a 15m entry is anchored
    on the 30m and the 1h.

    **A break has to have happened first**, pointing the same way, with price
    still near enough to the line for the line to be an entry. The order is the
    claim: structure fails, and *then* the reading stretches.

    **Licensed by the entry bar's own record**, because a scalp's horizon is
    the entry bar. See the module note.
    """

    name: ClassVar[str] = "cycle-turn-scalp"
    refines: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "A 1m-to-15m reversion scalp entered at the line a structure broke, "
        "gated on the z-score's displacement, sized by whether momentum agrees, "
        "under a 1h cycle that must agree with one of the 15m and 30m."
    )

    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m")
    #: Every anchor this reads. What each is worth is below.
    context: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h")
    needs_context: ClassVar[bool] = True

    #: The mother cycle. Necessary, and not sufficient - see the class note.
    MOTHER: ClassVar[str] = "1h"
    #: The rest of the anchors; at least one has to agree with the mother. The
    #: call's own interval drops out, which is why a 15m entry is anchored on
    #: the 30m and the 1h.
    SUPPORTING: ClassVar[tuple[str, ...]] = ("15m", "30m")

    #: How close the call has to sit to the broken line for that line to be an
    #: entry rather than a fact about the past, in volatility units of the
    #: entry bar. Measured on the desk: the median call sits twelve units from
    #: its line, and two admits about one in seven.
    MAX_BREAK_GAP_VOL: ClassVar[float] = 2.0

    #: What displacement alone is worth against displacement with momentum
    #: behind it. **Only ever shrinks**: a multiplier that enlarges is a way to
    #: exceed the risk budget through a setting nobody reads as a risk setting.
    UNCONFIRMED_RISK: ClassVar[float] = 0.5

    #: **Fifteen minutes.** Enter fast and leave fast: this trades a
    #: displacement that has already begun to unwind, and a reversion that has
    #: not happened within a quarter of an hour is not the trade that was
    #: taken. `hold_for` takes the smaller of this and the configured scalp
    #: ceiling, so the strategy asks and configuration decides.
    #:
    #: The cost is known and accepted: 48% of this desk's trades already expire
    #: on the clock at about 0R, and a shorter clock makes that fraction
    #: larger, not smaller. It is paired with banking small profits rather than
    #: waiting for targets - see `research/giveback.md`.
    style: ClassVar[str] = "scalp"
    hold_seconds: ClassVar[float] = 15 * 60.0

    #: `ride`'s exit, which `research/exiting.md` measured as the best of six
    #: over 31,820 replayed touches.
    trail_vol: ClassVar[float] = 0.5

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        feed = str(payload.get("feed") or "")

        # **Displacement, not agreement.** See the module note: `agrees` fires
        # on 1.5% of calls and scores worse than this by the desk's own
        # measurement. Agreement is not discarded - it decides the size.
        stretched = _number(features, "zma_stretched")
        if not stretched:
            return Refusal(
                "cycle_flat", "the reading is inside its own band - nothing is stretched", feed
            )

        side = Side.from_direction(str(payload.get("direction") or ""))
        if side is not None and (stretched > 0) != (side is Side.BUY):
            return Refusal(
                "cycle_against",
                f"the reading expects {'a rise' if stretched > 0 else 'a fall'} "
                f"and the call says {side.value}",
                feed,
            )

        refused = self._without_a_break(feed, features, stretched)
        if refused is not None:
            return refused

        missing = self._unconfirmed(payload)
        if missing == (self.MOTHER,):
            return Refusal(
                "cycle_no_mother",
                f"the {self.MOTHER} cycle does not agree with this "
                f"{payload.get('interval') or '?'} call, which ends it whatever the others say",
                feed,
            )
        if missing:
            return Refusal(
                "cycle_alone",
                f"only the {self.MOTHER} agrees - {'/'.join(missing)} would have "
                f"to as well for this to be an agreement",
                feed,
            )

        # **The entry bar's own record**, because a scalp's horizon is the
        # entry bar - the same bar `zma_gate` defers to, and the opposite
        # choice from `cycle-turn`, which bets on four hours and is licensed by
        # the 4h record for exactly the same reason.
        calls = _number(features, "zma_edge_calls")
        if calls < self.settings.zma_min_calls:
            return Refusal(
                "cycle_unproven",
                f"{calls:.0f} scored calls on this feed, "
                f"{self.settings.zma_min_calls:.0f} needed before this trades it",
                feed,
            )
        rate = _number(features, "zma_edge_right") / max(calls, 1.0)
        if rate <= self.settings.zma_min_accuracy:
            return Refusal(
                "cycle_poor",
                f"the reading is right {rate:.0%} of {calls:.0f} times here, "
                f"which is not past {self.settings.zma_min_accuracy:.0%}",
                feed,
            )
        return None

    def conviction_scale(self, features: dict[str, float], side: Side) -> float:
        """Full risk when momentum has begun to confirm, less when it has not.

        The agreement flag is the stricter reading of the same reading: the
        displacement is there *and* momentum has already started to unwind it.
        That is a better-supported version of this trade rather than a
        different one, so it sizes rather than gates.

        Shrinking only. `1.0` is the ceiling and `UNCONFIRMED_RISK` the floor,
        because a multiplier that enlarges would be a way past `max_risk_money`
        and every other cap downstream.
        """
        agrees = _number(features, "zma_agrees")
        if not agrees:
            return self.UNCONFIRMED_RISK
        if side is not None and (agrees > 0) != (side is Side.BUY):
            return self.UNCONFIRMED_RISK
        return 1.0

    def resting_price(self, features: dict[str, float]) -> float:
        """The broken line, because that is the trade. See `cycle-turn`."""
        return _number(features, "break_price")

    def _without_a_break(
        self, feed: str, features: dict[str, float], side: float
    ) -> Refusal | None:
        """The break comes first, and its line is what the entry is drawn at.

        The same three conditions `cycle-turn` applies, for the same reasons:
        something has to have broken, it has to point the way the reading does,
        and price has to be near enough to the line for the line to be an entry
        rather than a fact about the past.
        """
        broke = _number(features, "break_side")
        if not broke:
            return Refusal(
                "no_break", "nothing broke before this turn - there is no line to enter at", feed
            )
        if (broke > 0) != (side > 0):
            return Refusal(
                "break_against",
                f"the last break turned {'up' if broke > 0 else 'down'} "
                f"and the reading expects {'a rise' if side > 0 else 'a fall'}",
                feed,
            )
        line = _number(features, "break_price")
        if not line:
            return Refusal("break_priceless", "the break carries no line to enter at", feed)
        level = _number(features, "level")
        vol_bps = _number(features, "vol_bps")
        if not level or not vol_bps:
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

        Two different failures of different sizes: the mother missing is the
        whole agreement gone, and the mother alone is one reading rather than
        an agreement. The caller turns each into its own refusal, because a
        counter that merged them would not say which.

        The call's own interval is excluded throughout - a timeframe cannot
        confirm itself - so a 15m entry is anchored on the 30m and the 1h.
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
