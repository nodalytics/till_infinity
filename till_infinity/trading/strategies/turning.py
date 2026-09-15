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

from typing import Any, ClassVar

from ..models import Refusal, Side
from .scalper import LevelStrategy, _number
from .strategy import register


@register
class CycleTurn(LevelStrategy):
    """Take the level call only when the cycle reading has earned a say on this feed."""

    name: ClassVar[str] = "cycle-turn"
    refines: ClassVar[str] = "level-scalp"
    description: ClassVar[str] = (
        "Trade a level call only where the cycle reading agrees with it and that "
        "feed's own scored record beats a coin. Narrows an existing thesis; it "
        "does not invent one. Off unless TRADING_STRATEGIES names it."
    )
    #: Where the reading is computed. `structures/cycles.py` runs 1m as its fast
    #: stream, so a call on a slower entry is being judged by a reading taken
    #: from bars it does not contain.
    entries: ClassVar[tuple[str, ...]] = ("1m", "3m", "5m", "15m")
    context: ClassVar[tuple[str, ...]] = ("15m", "1h", "4h")
    #: A reversion trade is wrong quickly or not at all: the agreement condition
    #: is about a turn that has already begun, so a wide stop buys nothing but
    #: time to be wrong in.
    stop_multiple: ClassVar[float] = 0.9
    target_multiple: ClassVar[float] = 1.0

    def accept(self, payload: dict[str, Any], features: dict[str, float]) -> Refusal | None:
        feed = str(payload.get("feed") or "")

        agrees = _number(features, "zma_agrees")
        if not agrees:
            return Refusal(
                "cycle_quiet",
                "displacement and momentum do not point the same way",
                feed,
            )

        side = Side.from_direction(str(payload.get("direction") or ""))
        if side is None:
            return None
        if (agrees > 0) != (side is Side.BUY):
            return Refusal(
                "cycle_against",
                f"the cycle expects {'a rise' if agrees > 0 else 'a fall'} "
                f"and the call says {side.value}",
                feed,
            )

        # **The record, not the reading.** Everything above is true on a feed
        # where this has never worked; only this line knows the difference.
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
