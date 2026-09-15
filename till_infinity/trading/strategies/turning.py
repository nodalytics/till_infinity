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

from ..models import Refusal, Side
from .scalper import LevelStrategy, _number
from .strategy import register


@register
class CycleTurn(LevelStrategy):
    """A 15m-to-1h entry that the 1h and 4h cycles both have to agree with.

    ## The shape

    **Entry on 15m, 30m or 1h.** Fast enough that a stop means something, slow
    enough that the cycle reading on it is not one bar of noise.

    **Confirmed by 1h and 4h, with 1d optional.** Both required anchors have to
    appear in the call's own confluence - `structures` has already grouped the
    price into a zone across timeframes, so this reads that rather than asking
    a second, differently-wrong version of the same question. A 1d agreement is
    recorded as `fully_aligned` and does not gate: making it mandatory would
    refuse most of the trades the 1h/4h pair already qualifies, and nothing has
    measured that it should.

    **Stop sized for the 1h horizon, target for the 4h**, which is the part
    worth being precise about. The signal publishes no per-timeframe structure
    prices - `last_high_structure` and the zone bounds all belong to the call's
    own interval - so "the stop comes from 1h" cannot mean "placed at the 1h
    swing". It means **sized for how far price travels in an hour**: a
    diffusive move over `T` scales as the square root of `T`, so a 15m call's
    stop is widened by `sqrt(3600/900) = 2` and its target by
    `sqrt(14400/900) = 4`. On a 1h entry the stop is unscaled and only the
    target stretches.

    That is a real implementation of the intent rather than a relabelling, and
    it is stated here because the alternative reading - that this finds the
    actual 1h swing low - is the one somebody will assume.

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
    `zma_min_accuracy`, the same bar `zma_gate` defers to, so the entry and the
    veto cannot disagree about whether a feed has earned a say. On a family
    where the reading is an anti-signal that record never clears and this never
    trades there, with nobody maintaining a list of which families those are.
    """

    name: ClassVar[str] = "cycle-turn"
    refines: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "A 15m-to-1h reversion entry that the 1h and 4h cycles must both agree "
        "with, stopped on the 1h horizon and targeted on the 4h, trailed like "
        "`ride`. Only on feeds whose own scored record beats a coin."
    )
    entries: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h")
    #: 1d is listed so `anchored` reports it; only `REQUIRED` gates.
    context: ClassVar[tuple[str, ...]] = ("1h", "4h", "1d")
    needs_context: ClassVar[bool] = True

    #: Both have to agree. `1h` drops out of the requirement when it is itself
    #: the entry - a timeframe cannot confirm itself, and `anchored` already
    #: excludes the call's own interval.
    REQUIRED: ClassVar[tuple[str, ...]] = ("1h", "4h")
    #: Recorded when it also agrees, never required. See the class note.
    OPTIONAL: ClassVar[str] = "1d"

    #: The horizons the stop and the target belong to, in seconds.
    STOP_HORIZON: ClassVar[float] = 3_600.0
    TARGET_HORIZON: ClassVar[float] = 14_400.0
    #: How far the scaling may stretch either distance. Without it a 15m entry
    #: aiming at a 1d horizon would ask for a target 9.8 units out, which the
    #: reward-to-risk gate would pass and no market would reach.
    MAX_SCALE: ClassVar[float] = 4.0

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

        missing = self._unconfirmed(payload)
        if missing:
            return Refusal(
                "cycle_unaligned",
                f"{'/'.join(missing)} does not agree with this "
                f"{payload.get('interval') or '?'} call",
                feed,
            )

        # **The record, not the reading.** Everything above is true on a feed
        # where this has never worked; only this knows the difference.
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

    def _unconfirmed(self, payload: dict[str, Any]) -> tuple[str, ...]:
        """Required anchors that do not agree with this call.

        The call's own interval is excluded - a timeframe cannot confirm
        itself, which is why a 1h entry needs only 4h.
        """
        interval = str(payload.get("interval") or "")
        agreeing = set(self.anchored(payload))
        return tuple(t for t in self.REQUIRED if t != interval and t not in agreeing)

    def fully_aligned(self, payload: dict[str, Any]) -> bool:
        """Whether the daily agrees too. Recorded, never required."""
        return self.OPTIONAL in set(self.anchored(payload))

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
