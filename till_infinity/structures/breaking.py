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

from ..logging import get_logger
from .online import Logistic
from .state import Restorable

#: The features that separate, in the order the fitted weights are reported.
#:
#: `slope` and `prior_slope` were added 2026-09-03 on a measured lift. Scored
#: the way this model works - predict then update, one pass in time order, so
#: every score is out of sample - over 5,452 touches lasting five minutes or
#: more:
#:
#: | features | AUC |
#: | --- | --- |
#: | the original three | 0.6104 |
#: | + slope | 0.6262 |
#: | + slope and prior_slope | **0.6408** |
#: | slope alone | 0.5642 |
#:
#: +0.030 AUC, which is a 28% increase in this model's edge over a coin. The
#: magnitude is taken, not the sign: which way the fit points is a directional
#: question and this one is not.
#:
#: **Both, or neither.** `slope` alone is *worse* than the original three, and
#: the pair beats either - a flat approach means one thing after quiet and
#: another after a run, and only the prior window tells them apart. Over
#: 10,869 five-minute touches "flat now, steep a window ago" breaks 17.2% of
#: the time against a 29.6% base, the strongest hold signal measured here.
#: See research/slopes.md.
#:
#: `interval_log` was added 2026-09-03 and is the largest single separator this
#: book has produced. Break rate by the timeframe a level was drawn on, over
#: 126,296 resolutions lasting five minutes or more against a 33.1% base: 1m
#: 57.9%, 3m 26.8%, 5m 20.4%, 15m 12.8%, 30m 2.8%, 1h **1.4%**, 2h 0.0%, 4h
#: 4.3%. Monotone, fortyfold.
#:
#: It was invisible here because every other feature is scale-free by
#: construction - which is precisely why the timeframe is orthogonal to them.
#: Scored predict-then-update in time order on the five-minute cut, adding it
#: takes this model from **0.5999 to 0.7542** AUC, and the interval alone
#: scores 0.7396.
#:
#: **A price shared across timeframes was measured beside it and is not worth
#: carrying**: grouping resolutions by price to five basis points, break rate
#: falls only from 41.0% at one timeframe to 29.5% at five, and adding that
#: count on top of the interval moves AUC by +0.001. The per-touch timeframe is
#: the signal; what else names the price is nearly nothing.
NAMES: tuple[str, ...] = (
    "approach_vol",
    "depth_vol",
    "slowing",
    "slope",
    "prior_slope",
    "interval_log",
)

#: Features read as magnitudes rather than signed values. The slope's sign says
#: which way price is going, which is a different question from whether the
#: level survives - and leaving it signed would ask the model to learn "steep
#: up and steep down both break" from scratch, on a linear fit that cannot.
ABSOLUTE: frozenset[str] = frozenset({"slope", "prior_slope"})

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

log = get_logger(__name__)

#: What the model was trained on. Bump whenever the **meaning** of an input
#: changes, so the saved statistics are dropped rather than carried.
#:
#: A module constant rather than a class attribute: on a `slots=True`
#: dataclass, `Breaks.recipe` is the slot *descriptor*, not the default value,
#: so comparing an instance against it always differs and the model would
#: restart on every single restore.
#: How fast the fit moves. Swept over the whole record on 2026-09-04,
#: predict-then-update in time order, reporting accuracy against **drift** -
#: the mean absolute weight change per observation, measured over the last
#: third of the run once the fit should have settled:
#:
#: | rate | AUC | drift per 100 |
#: | ---: | ---: | ---: |
#: | 0.005 | 0.6848 | 0.281 |
#: | 0.010 | 0.7071 | 0.559 |
#: | **0.020** | **0.7206** | **1.110** |
#: | 0.050 | 0.7304 | 2.751 |
#: | 0.100 | 0.7312 | 5.468 |
#:
#: **Accuracy saturates long before stability does.** 0.05 to 0.10 buys 0.0008
#: AUC for double the drift; coming down to 0.02 costs 0.0098 and cuts drift to
#: 40%.
#:
#: The cost of the old rate was not academic. The live weights moved 1.652,
#: 1.174, 1.840 and 1.441 in four consecutive half-hours, and `interval_log`
#: changed sign three times - so `max_break_risk`, which acts on this model's
#: output, could refuse a level on one pass and accept the same features on the
#: next. That is not a rule being applied.
#:
#: Not a `RECIPE` change: the rate alters how fast the fit moves, not what any
#: input means, so the standardiser's statistics stay valid.
RATE = 0.02

RECIPE = "2026-09-03 interval_log added"


@dataclass(slots=True)
class Breaks(Restorable):
    """P(this level gives way), learned online from resolved touches.

    One model across the book rather than one per instrument. The features are
    scale-free by construction - a volatility unit means the same thing on gold
    and eurusd - which is the same argument that lets the kNN borrow evidence
    across instruments, and here it matters more because breaks are rarer than
    touches.
    """

    model: Logistic = field(default_factory=lambda: Logistic(rate=RATE))

    #: What the model was trained on. Bump it whenever the **meaning** of an
    #: input changes, and the saved state is dropped rather than carried.
    #:
    #: This exists because a fix landed and did nothing. `slowing` was an
    #: unbounded ratio whose running mean in the standardiser had reached
    #: **141,380,329**; it was capped at 10.0, and the cap could never take
    #: effect - `Scaler` is plain Welford with no decay, so with n at 5,256 a
    #: clamped observation moves the mean by (10 - 141M)/5256 and pulling it
    #: back to a sane figure would take on the order of 1e11 samples. The input
    #: was fixed and the statistics describing it were not, which is a fix that
    #: reads as done and changes nothing.
    #:
    #: Adding an input is handled already - `Logistic` and `Scaler` rebuild on
    #: a length change. Re-*meaning* one is not, and that is what this catches.
    recipe: str = RECIPE

    @staticmethod
    def inputs(features: object) -> list[float]:
        """Every feature, read off whatever carries them.

        Takes the object rather than importing `reactions.Features`, so this
        module stays cheap to import and to test - and so a caller can pass the
        plain feature dictionary a signal carries.

        `ABSOLUTE` names are taken as magnitudes. A signed slope would ask a
        linear fit to learn that steep up and steep down both break, which is
        exactly the shape a linear fit cannot represent.
        """
        if isinstance(features, dict):
            raw = [float(features.get(name) or 0.0) for name in NAMES]
        else:
            raw = [float(getattr(features, name, 0.0) or 0.0) for name in NAMES]
        return [abs(v) if name in ABSOLUTE else v for name, v in zip(NAMES, raw, strict=True)]

    def predict(self, features: object) -> float | None:
        """P(break), or None while there is not enough behind it.

        None rather than 0.5, because "no opinion" and "an even chance" are
        different claims and a consumer that cannot tell them apart will act on
        the second when it was given the first.
        """
        if self.model.seen < MIN_SEEN:
            return None
        return self.model.predict(self.inputs(features))

    def _fresh_start_if_the_recipe_changed(self) -> None:
        """Drop statistics gathered under a different meaning of the inputs.

        Adding an input is handled already: `Logistic` and `Scaler` rebuild on
        a length change. **Re-meaning one is not**, and that is the case this
        catches. `slowing` was an unbounded ratio whose running mean in the
        standardiser had reached 141,380,329; capping it at 10.0 fixed every
        future value and could never fix the statistics, because `Scaler` is
        plain Welford with no decay - at n=5,256 a clamped observation moves
        the mean by (10 - 141M)/5256, and recovery would take on the order of
        1e11 samples. The cap read as done and changed nothing.

        Checked here rather than in `__setstate__`, which was tried and is a
        trap: a `slots=True` dataclass is a new class object built after the
        method bodies compile, so bare `super()` raises at unpickling time
        only, and `Breaks.recipe` is the slot *descriptor* rather than the
        default, so the comparison never matches.
        """
        if self.recipe == RECIPE:
            return
        log.warning(
            "structures: the break model was trained on %r and this build "
            "expects %r - starting it again rather than standardising new "
            "inputs against statistics gathered under the old meaning",
            self.recipe,
            RECIPE,
        )
        self.model = Logistic(rate=RATE)
        self.recipe = RECIPE

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
        self._fresh_start_if_the_recipe_changed()
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
