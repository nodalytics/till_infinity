"""Will this level break? A different question from which way price goes.

Everything else here predicts **direction**. The kNN, the floor, the linear
baseline - all of them answer "which way from here", and research/learning.md
found `up_rate`, the level's own record, carries almost all of it at weight
+2.29 against nothing else above 0.22.

`up_rate` predicts a break at **AUC 0.4892**. Nothing. The strongest direction
feature there is, and it is worthless for hold-versus-break, which is the
evidence that these are separate questions rather than two views of one.

## What does predict it

Two features that were already in the set and ignored, measured over 10,904
resolved touches in the horizon band where the answer is not definitional (see
research/force.md and research/horizon.md):

* **`approach_vol`** - how fast price was travelling in, AUC 0.560. Fast
  arrivals break 59.8% of the time against 51.4% for slow ones, and the
  quintile ladder rises without a kink. This is the desk's own claim: a level
  can be valid and still fail, because what matters is how hard price is
  coming at it.
* **`depth_vol`** - how far into the zone the touch had pushed when it opened,
  AUC 0.599 read the right way round. A touch that barely enters breaks 64.6%
  of the time; one that pushes deep breaks 38.3%. Depth is evidence the level
  did something.

**Together, 0.658** - materially better than either, because they disagree.
Fitted weights put `approach_vol` at +0.255 and `depth_vol` at -0.779, which is
the model saying the same thing the quintiles do.

* **`slowing`** - the speed of the last few bars against the few before them,
  AUC 0.5237. Weaker than either, and **nearly orthogonal to arrival speed**:
  correlation +0.008 over 4,078 touches. That is the reason it is here. A weak
  separator uncorrelated with a strong one adds information; a second strong
  one that agrees restates it.

`run_vol` - how far the leg had already travelled - does nothing at all, AUC
0.5000. Speed on arrival matters and distance already covered does not, which
is worth stating because they are the same intuition and only half survives.

## Point in time, checked

Both inputs come from `Features`, built once by `features_for` when the touch
*opens*, on a frozen dataclass that is never mutated afterwards. `depth_vol` is
the distance at that moment and not the excursion that follows - which had to
be verified rather than assumed, because a leaking feature is exactly what an
AUC of 0.599 would look like.

## It decides nothing

Published as `break_probability` on every level call and scored beside the
direction models. A break rate is not money: what it is worth depends on the
size of what follows and the cost of being wrong, which is the arithmetic
research/paying.md holds direction to and which nothing has yet held this to.

The one thing already known about the size: **a break is the more predictable
move but not the larger one.** Breaks push a median 2.82v against a hold's
2.08v, but the means are 3.38v and 5.67v - holds have a fat right tail. A model
that trades breaks is trading the consistent side of a skewed distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .online import Logistic
from .state import Restorable

#: The two that separate, in the order the fitted weights are reported.
NAMES: tuple[str, ...] = ("approach_vol", "depth_vol", "slowing")

#: A **trap is not a break.** Price gets through, traps whoever followed it,
#: and comes back - so the level ultimately held and the push lands in the hold
#: direction. Measured on 10,977 touches: an `above` trap pushes up 100.0% of
#: the time, exactly like an `above` reject.
#:
#: Grouping it with breaks inflated the break rate from 32% to 55.6% and
#: produced a "the level's call is right 44.7% of the time" that was simply
#: wrong. `chop` is neither and is excluded, as everywhere else here.
BROKE = ("break",)
HELD = ("reject", "backcheck", "trap")

#: How many resolutions before the estimate is worth publishing.
MIN_SEEN = 200.0


@dataclass(slots=True)
class Breaks(Restorable):
    """P(this level gives way), learned online from resolved touches.

    One model across the book rather than one per instrument. The features are
    scale-free by construction - a volatility unit means the same thing on gold
    and eurusd - which is the same argument that lets the kNN borrow evidence
    across instruments, and here it matters more because breaks are rarer than
    touches.
    """

    model: Logistic = field(default_factory=lambda: Logistic(rate=0.05))

    @staticmethod
    def inputs(features: object) -> list[float]:
        """The two, read off whatever carries them.

        Takes the object rather than importing `reactions.Features`, so this
        module stays cheap to import and to test - and so a caller can pass the
        plain feature dictionary a signal carries.
        """
        if isinstance(features, dict):
            return [float(features.get(name) or 0.0) for name in NAMES]
        return [float(getattr(features, name, 0.0) or 0.0) for name in NAMES]

    def predict(self, features: object) -> float | None:
        """P(break), or None while there is not enough behind it.

        None rather than 0.5, because "no opinion" and "an even chance" are
        different claims and a consumer that cannot tell them apart will act on
        the second when it was given the first.
        """
        if self.model.seen < MIN_SEEN:
            return None
        return self.model.predict(self.inputs(features))

    def observe(self, features: object, outcome: str) -> float | None:
        """Take one resolved touch. Returns what it predicted beforehand.

        `chop` and anything unrecognised is ignored rather than counted as a
        hold: a touch that went nowhere is not evidence the level held.
        """
        name = str(outcome)
        if name in BROKE:
            broke = True
        elif name in HELD:
            broke = False
        else:
            return None
        return self.model.observe(self.inputs(features), broke)

    def reading(self, features: object) -> dict[str, float]:
        """The estimate as a float dictionary, for a signal's features."""
        said = self.predict(features)
        if said is None:
            return {}
        return {"break_probability": round(said, 5), "break_seen": round(self.model.seen, 1)}

    @property
    def warm(self) -> bool:
        return self.model.seen >= MIN_SEEN

    def importance(self) -> list[tuple[str, float]]:
        """Which of the two the model is leaning on."""
        return self.model.importance(NAMES)
