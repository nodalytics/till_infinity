"""Which wall does price reach first — the ceiling or the floor?

## The question, and why it is a different one

`drawing/level_range.py` finds the two zones price sits between. That is a picture,
not a decision. The decision it makes possible is **which bound gets touched
first**, because an answer to that is directly an entry and a target: go toward
the bound price is likely to reach, put the target at the far one, and trail.

Everything else in `learning/` answers a question about **one** level - will it
hold, which way will price go from it. This is a race between two, and the
difference matters more than it looks:

* The label is **symmetric and complete**. A range resolves upward or
  downward and there is no third outcome except running out of time, so there
  is no `chop` bucket to argue about and no definitional trap of the kind
  `research/horizon.md` found in fast resolutions.
* The counterfactual is **observed**. Price reaches a bound whether or not
  anybody traded it, so this is supervised, not a bandit - the test
  [bandits.md](../../../research/bandits.md) sets at the top.
* It is **not** direction. `up_rate` carries almost all of "which way from
  here" and predicts a break at AUC 0.4892; whether the ceiling is nearer in
  *time* is a question about two distances and the speed between them.

## The control travels with the model

Which wall price reaches first is **close to a geometric fact**: most of the
time it is the nearer one. So a high accuracy here is the expected result of
learning nothing at all beyond the shape of the range, and is
indistinguishable from a high accuracy for a real edge.

`naive_right`/`naive_seen` score the rule "the nearer bound wins" on exactly
the same races, updated in the same call before the model is, so the two are
never compared on different samples. `edge` is the difference and it is the
only number here worth reading. It can be negative.

The first live reading was **84.1% accuracy over 252 races**, with weights that
all point the sensible way - `range_position` +1.00, `room_down_vol` +0.49,
`room_up_vol` -0.43. That looked like a result and is exactly the shape
`research/inert.md` warns about: a strong number is usually impossible rather
than impressive, and this one had no control against it.

## What it is allowed to do, which is nothing yet

`Races.reading` publishes `up_first` on a signal's features and refuses
anything else. No strategy reads it, no entry is placed from it, and it is
`None` rather than 0.5 until the model has seen enough - "no opinion" and "an
even chance" being different claims.

That order is deliberate and this project keeps paying for the other one. A
model that decides before it is scored is one nothing can contradict, which is
the shape `research/inert.md` catalogues. The estimate lands in the journal
beside what actually happened, and the record gets to say whether it is worth
anything before it is worth money.

## The label has to exist before the model can

Which is what `Races.watch` and `Races.step` are for, and they are the larger
half of this module. A range is opened when it is published, carries the
features it was published with, and is resolved by the next price that reaches
either bound. Nothing is learned from an unresolved range, and a range that
never resolves is dropped rather than counted - a timeout is not a draw.

**One open race per feed.** A newer range supersedes an older one rather than
queueing beside it: the bounds move as levels move, and two races on the same
instrument would resolve on the same tick and enter the same observation twice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ...logging import get_logger
from ..state import Restorable
from .online import Logistic

log = get_logger(__name__)

#: The readings the model is fitted on, in this order. All four are scale-free
#: - volatility units and a ratio - so one model serves the whole book, the
#: same argument `breaking.Breaks` makes for borrowing evidence across
#: instruments.
NAMES: tuple[str, ...] = (
    "range_position",
    "room_up_vol",
    "room_down_vol",
    "range_width_vol",
)

#: How many resolved races before it will say anything. Lower than
#: `breaking.MIN_SEEN` of 200 because the label here is balanced by
#: construction - roughly half of all ranges resolve upward - where breaks
#: are rare and need more of them to see.
MIN_SEEN = 60.0

#: Slower than the 0.05 `breaking` started at and the same as what it settled
#: on. See research/learning.md: the fast rate made the weights flip sign
#: between batches, which reads as a model changing its mind and is a model
#: chasing its last few observations.
RATE = 0.02

#: Bump when the **meaning** of an input changes, so saved statistics gathered
#: under the old meaning are dropped rather than carried. Adding an input is
#: handled by `Logistic` rebuilding on a length change; re-meaning one is not.
#:
#: Bumped once for a **rename**, which is worth saying because it looks like it
#: should not need one. The keys the model reads are the keys the features
#: arrive under: `channel_position` became `range_position`, so state saved
#: under the old names would restore into a model reading the new ones and
#: quietly find nothing - every input zero, no error, a model that had been
#: trained and now predicts from a constant. Renaming an input is re-meaning
#: it as far as this is concerned.
RECIPE = "2026-09-05 channel renamed to range"

#: A race left open longer than this is discarded rather than resolved. Twelve
#: hours: long enough that an intraday range resolves inside it, short enough
#: that a stale range drawn against levels that have since moved does not
#: come back and claim an outcome it did not predict.
STALE_SECONDS = 12 * 3600.0


@dataclass(slots=True)
class Pending(Restorable):
    """A range waiting to find out which way it resolves."""

    feed: str
    upper: float
    lower: float
    #: The readings as published, frozen here so the model is fitted on what was
    #: known at the time rather than on what the range looks like now.
    features: dict[str, float] = field(default_factory=dict)
    opened: float = field(default_factory=time.time)

    def resolves(self, price: float) -> str:
        """Which bound this price reaches, or "" for neither."""
        if self.upper > 0 and price >= self.upper:
            return "upper"
        if self.lower > 0 and price <= self.lower:
            return "lower"
        return ""


@dataclass(slots=True)
class Races(Restorable):
    """P(price reaches the ceiling before the floor), learned online."""

    model: Logistic = field(default_factory=lambda: Logistic(rate=RATE))
    #: feed -> the race currently open on it.
    open: dict[str, Pending] = field(default_factory=dict)
    recipe: str = RECIPE
    #: How the **nearest bound wins** rule would have scored on the same races,
    #: and how many it has seen. This is the control, and it travels with the
    #: model rather than living in a harness somebody has to remember to run.
    #:
    #: Without it the model's accuracy cannot be read. Which wall price reaches
    #: first is close to a geometric fact - the nearer one, most of the time -
    #: so a high score is the *expected* result of learning nothing but the
    #: geometry, and is indistinguishable from a high score for a real edge.
    #: The number that means something is the gap between the two.
    naive_right: float = 0.0
    naive_seen: float = 0.0

    @staticmethod
    def inputs(features: object) -> list[float]:
        """The four readings, off a mapping or off anything carrying them."""
        if isinstance(features, dict):
            return [float(features.get(name) or 0.0) for name in NAMES]
        return [float(getattr(features, name, 0.0) or 0.0) for name in NAMES]

    def _fresh_start_if_the_recipe_changed(self) -> None:
        if self.recipe == RECIPE:
            return
        log.warning(
            "structures: race recipe changed (%r -> %r) - dropping %d observation(s)",
            self.recipe,
            RECIPE,
            int(self.model.seen),
        )
        self.model = Logistic(rate=RATE)
        self.open.clear()
        self.naive_right = 0.0
        self.naive_seen = 0.0
        self.recipe = RECIPE

    def predict(self, features: object) -> float | None:
        """P(upper first), or None while there is not enough behind it."""
        if self.model.seen < MIN_SEEN:
            return None
        # A range open on one side is not a race. Reporting a probability for
        # it would be answering a question that was not asked: with no ceiling
        # there is nothing for the floor to beat.
        values = self.inputs(features)
        if not values[1] or not values[2]:
            return None
        return self.model.predict(values)

    def reading(self, features: object) -> dict[str, float]:
        """The estimate as a float dictionary, for a signal's features."""
        said = self.predict(features)
        if said is None:
            return {}
        return {"up_first": round(said, 5), "up_first_seen": round(self.model.seen, 1)}

    @property
    def naive(self) -> float | None:
        """What "the nearer bound wins" scores on the same races, or None."""
        if self.naive_seen <= 0:
            return None
        return self.naive_right / self.naive_seen

    @property
    def edge(self) -> float | None:
        """Accuracy above the geometric rule. **This is the number that means
        something**, and it can be negative - a model that has learned the
        geometry and nothing else scores zero here however high its accuracy
        reads."""
        rule = self.naive
        got = getattr(self.model, "accuracy", None)
        if rule is None or not isinstance(got, int | float):
            return None
        return float(got) - rule

    def watch(self, feed: str, upper: float, lower: float, features: dict[str, float]) -> None:
        """Open a race on this feed, replacing whatever was open on it.

        Both bounds are required. A one-sided range has no race to run, and
        opening one would put a resolution in the record that the model could
        never have predicted.
        """
        if not feed or upper <= 0 or lower <= 0 or upper <= lower:
            return
        self._fresh_start_if_the_recipe_changed()
        self.open[feed] = Pending(
            feed=feed, upper=float(upper), lower=float(lower), features=dict(features)
        )

    def step(self, feed: str, price: float, now: float = 0.0) -> str | None:
        """Take one price. Returns the bound it resolved, or None.

        Predict-then-update, like every other model here: the estimate is taken
        from the weights as they were before this observation, so the score is
        out of sample by construction rather than by discipline.
        """
        pending = self.open.get(feed)
        if pending is None or price <= 0:
            return None
        when = now or time.time()
        if when - pending.opened > STALE_SECONDS:
            # Dropped, not resolved. A range this old was drawn against
            # levels that have since moved, and letting it resolve would credit
            # the model for a prediction about a picture that no longer exists.
            del self.open[feed]
            return None
        which = pending.resolves(price)
        if not which:
            return None
        del self.open[feed]
        self._fresh_start_if_the_recipe_changed()
        upward = which == "upper"
        # Scored before the model is updated, on the same race, so the two are
        # always compared on identical events.
        nearer_up = float(pending.features.get("range_position") or 0.5) > 0.5
        self.naive_seen += 1.0
        self.naive_right += 1.0 if nearer_up == upward else 0.0
        self.model.observe(self.inputs(pending.features), upward)
        return which

    def forget(self, feed: str) -> None:
        self.open.pop(feed, None)

    @property
    def warm(self) -> bool:
        return self.model.seen >= MIN_SEEN
