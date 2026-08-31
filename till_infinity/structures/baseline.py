"""The comparison nobody has run: is the kNN buying anything?

`reactions.py` decides every level call. It compares the touch in front of it
with past touches by a hand-built Euclidean distance over nine equally-weighted
features, takes the nearest, and votes. It has never been compared with
anything, which means "the kNN works" has never been distinguished from "the
features work and any model would do".

That distinction has consequences either way:

* if a **linear model matches it**, the kNN is complexity with no return in the
  most important path in the system, and simplifying is a plain win;
* if **both sit at the base rate**, the features do not carry the signal - a
  finding about the features, which no amount of model fixes;
* if the kNN **wins clearly**, that is worth knowing too, and it is the first
  evidence for it rather than the assumption it has been.

## Three models, one stream of touches

Every touch that resolves goes to all three, each of which must predict before
it is told the answer:

* `linear` - logistic regression on the same nine features. The baseline.
* `attention` - the same neighbours the kNN uses, weighted by a *learned*
  distance instead of a fixed one. The upgrade path.
* `sequence` - what has followed this shape of move before, from a symbol
  n-gram over the price series. A different kind of evidence entirely: it knows
  nothing about the level.
* `up_rate` - **no model**. The level's own record of which way its touches
  went, read straight off the feature. The floor everything else has to clear.

The kNN's own answer is recorded beside them on the same touches, so the
comparison is like-for-like rather than two numbers from two runs.

## Scoring

Accuracy, log loss, and **edge over the base rate**, all decayed so an
improving model can show it. Edge is the one to read: 63% accuracy on a problem
whose base rate is 63% is a model that has discovered which answer is commoner,
and accuracy alone presents that as skill.

Nothing here decides anything. It publishes numbers beside the kNN's and the
record settles it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .attention import Attention, Embedding
from .online import Logistic
from .state import Restorable

#: The nine, in the order `reactions.Features.distance` compares them, so the
#: fitted weights line up with the thing being compared against.
NAMES: tuple[str, ...] = (
    "approach_vol",
    "depth_vol",
    "strength",
    "run_vol",
    "experience",
    "pivot",
    "backcheck",
    "regime",
    "up_rate",
)


def vector(features: object) -> list[float]:
    """`reactions.Features` as a plain list, in `NAMES` order.

    Takes the object rather than importing its type, so this module does not
    depend on `reactions` - which depends on rather a lot, and would make the
    baseline harder to run in a harness than the thing it is baselining.
    """
    return [float(getattr(features, name, 0.0) or 0.0) for name in NAMES]


@dataclass(slots=True)
class Comparison(Restorable):
    """One model's record against the same touches the others saw."""

    name: str = ""
    seen: float = 0.0
    right: float = 0.0
    positives: float = 0.0

    def observe(self, said: float, actual: bool) -> None:
        keep = max(0.0, 1.0 - 1.0 / 2_000.0)
        self.seen = self.seen * keep + 1.0
        self.right = self.right * keep + (1.0 if (said >= 0.5) == actual else 0.0)
        self.positives = self.positives * keep + (1.0 if actual else 0.0)

    @property
    def accuracy(self) -> float:
        return self.right / self.seen if self.seen else 0.0

    @property
    def base_rate(self) -> float:
        if not self.seen:
            return 0.5
        share = self.positives / self.seen
        return max(share, 1.0 - share)

    @property
    def edge(self) -> float:
        """Accuracy above always guessing the commoner answer."""
        return self.accuracy - self.base_rate

    def __str__(self) -> str:
        return (
            f"{self.name:10s} {self.accuracy:6.1%} of {self.seen:7.0f}"
            f"  base {self.base_rate:6.1%}  edge {self.edge:+6.2%}"
        )


@dataclass(slots=True)
class Band(Restorable):
    """One horizon band's models and its scores. See `Bench`."""

    linear: Logistic = field(default_factory=Logistic)
    attention: Attention = field(default_factory=Attention)
    scores: dict[str, Comparison] = field(default_factory=dict)

    def score(self, name: str) -> Comparison:
        found = self.scores.get(name)
        if found is None:
            found = self.scores[name] = Comparison(name=name)
        return found


@dataclass(slots=True)
class Bench(Restorable):
    """Every model on one stream of touches, scored the same way.

    **One set of models per horizon band, not one across everything.** Pooled,
    every score here was dominated by a population where the answer is written
    into the question: a touch approached from above that resolves inside a
    minute resolves upward 100.0% of the time, because that is what a rejection
    means, and 46% of resolutions are that fast. Every model reproduced the
    definition and scored 84-88% against a 52% base rate.

    Banding is not a reporting change. A parametric model fitted on the pooled
    stream *learns* the fast tautology and carries it into its predictions
    about slow touches, so the band has to reach the training and not only the
    report. See research/similarity.md.

    The kNN needs no equivalent here because it has no parameters - its
    training set is its neighbour pool, and `Memory.neighbours` bands that
    directly.
    """

    bands: dict[int, Band] = field(default_factory=dict)
    levels: Embedding = field(default_factory=Embedding)
    #: The pooled models, fitted alongside the banded ones so the pooled row
    #: compares like with like.
    linear: Logistic = field(default_factory=Logistic)
    attention: Attention = field(default_factory=Attention)
    #: Kept for the pooled view, which is worth having beside the bands rather
    #: than instead of them: it is what every earlier number in this repository
    #: was, and the gap between it and the bands is the size of the mistake.
    scores: dict[str, Comparison] = field(default_factory=dict)

    def band(self, at: int | None) -> Band:
        key = -1 if at is None else at
        found = self.bands.get(key)
        if found is None:
            found = self.bands[key] = Band()
        return found

    def score(self, name: str) -> Comparison:
        found = self.scores.get(name)
        if found is None:
            found = self.scores[name] = Comparison(name=name)
        return found

    def observe(
        self,
        features: object,
        held: bool,
        *,
        knn_said: float | None = None,
        neighbours: Sequence[tuple[Sequence[float], float]] = (),
        level_id: str = "",
        sequence_said: float | None = None,
        interval: str = "",
    ) -> dict[str, float]:
        """One resolved touch through every model. Returns what each predicted.

        `held` is the ground truth. `knn_said` is what `reactions` claimed, so
        the incumbent is scored on exactly the touches its challengers saw -
        the alternative, two separate runs, compares two samples rather than
        two models.

        `interval` picks the horizon band. Everything is scored twice: into its
        own band, which is the number worth reading, and into the pooled set,
        which is what every earlier figure in this repository was. Keeping both
        is what makes the size of the mistake visible rather than asserted.
        """
        from .reactions import band_of

        x = vector(features)
        said: dict[str, float] = {}
        band = self.band(band_of(interval))

        def record(name: str, value: float) -> None:
            said[name] = value
            self.score(name).observe(value, held)
            band.score(name).observe(value, held)

        record("linear", band.linear.observe(x, held))
        # The pooled linear model is kept fitted too, so the pooled row is a
        # like-for-like comparison rather than a banded model wearing a pooled
        # score.
        self.linear.observe(x, held)

        if neighbours:
            keys = [list(k) for k, _ in neighbours]
            values = [v for _, v in neighbours]
            got = band.attention.observe(x, keys, values, 1.0 if held else 0.0)
            self.attention.observe(x, keys, values, 1.0 if held else 0.0)
            if got is not None:
                record("attention", got)

        if knn_said is not None:
            record("knn", float(knn_said))

        # One feature, no model at all: the level's own record of which way its
        # touches went, read straight off. This is the floor everything above
        # has to clear, and it exists because the first bench result put the
        # kNN, a logistic model and a learned distance within 0.7 points of
        # each other while the logistic weights put `up_rate` at +0.94 and
        # nothing else above +0.34. If this scores what they score, then eight
        # features and the whole neighbour machinery are earning nothing, and
        # that is worth knowing precisely rather than suspecting.
        rate = getattr(features, "up_rate", None)
        if rate is not None:
            record("up_rate", float(rate))

        if sequence_said is not None:
            record("sequence", float(sequence_said))

        if level_id:
            self.levels.observe(level_id, x, held)
        return said

    def report(self) -> str:
        """The comparison as a person would want to read it.

        Bands first, pooled last and labelled as such. The pooled row is the
        one every earlier figure here was, and it is kept so the gap is visible
        - not because it is the number to act on.
        """
        if not self.scores:
            return "nothing scored yet"
        from .reactions import HORIZON_BAND

        lines: list[str] = []
        for key in sorted(self.bands):
            band = self.bands[key]
            if not band.scores:
                continue
            seconds = HORIZON_BAND**key if key >= 0 else 0.0
            name = f"~{seconds / 60:.0f}m horizon" if key >= 0 else "no interval"
            lines.append(f"{name}:")
            lines += [f"   {c}" for c in sorted(band.scores.values(), key=lambda c: -c.edge)]
        if lines:
            lines.append("")
            lines.append("pooled (what every earlier number here was):")
        ordered = sorted(self.scores.values(), key=lambda c: -c.edge)
        lines += [f"   {c}" for c in ordered]
        weights = self.linear.importance(NAMES)
        if weights:
            lines.append("")
            lines.append("what the linear model leans on:")
            lines += [f"   {name:14s} {w:+.4f}" for name, w in weights[:6]]
        learned = self.attention.importance(NAMES)
        if learned and self.attention.warm:
            lines.append("")
            lines.append("what the learned distance kept:")
            lines += [f"   {name:14s} {w:.4f}" for name, w in learned[:6]]
        return "\n".join(lines)

    def reading(self, interval: str = "") -> dict[str, float]:
        """The scores as floats, for a signal's features or the journal.

        This band's numbers when an interval is given, because a pooled edge on
        a signal is the tautology's edge and not this call's.
        """
        from .reactions import band_of

        out: dict[str, float] = {}
        scores = self.band(band_of(interval)).scores if interval else self.scores
        for name, score in scores.items():
            if score.seen >= 30.0:
                out[f"bench_{name}_edge"] = round(score.edge, 5)
        if self.linear.warm:
            out["bench_linear_logloss"] = round(self.linear.log_loss, 5)
        if self.attention.warm:
            out["bench_attention_r2"] = round(self.attention.r2, 5)
        return out
