"""Factorisation machines over what actually happened.

The levels model treats its features one at a time: deviation, then spread,
then how recently the level broke. A factorisation machine models how they
**combine** — a back check on a strong level in a violent regime is not the sum
of those three things, and an additive model cannot say so.

This module was deliberately empty until now, because an FM is supervised and
there were no labels. The journal changed that: every level call is recorded
with the features it was made from, and the touch resolving attaches what
followed. Collect first, fit second.

## Progressive validation, which is walk-forward by construction

Every example is **predicted before it is learned**, in time order:

    for example in sorted(examples, key=time):
        error += |predict(x) - y|
        model.learn(x, y)

There is no train/test split to get wrong and no way for a later example to
inform an earlier prediction. A shuffled split would leak: two touches at the
same level minutes apart are nearly the same observation, so putting one in
train and one in test measures memorisation.

## Against a baseline, always

The score means nothing alone. Two are reported beside it:

- **mean** — predict the average push, every time. A model that cannot beat
  this has learned nothing from the features.
- **the levels model** — what `reactions.infer` predicted at the time, which is
  already in the journal. This is the one that matters: an FM that does not
  beat the model it was meant to improve on is not an improvement.

## It refuses to answer on too little

Below `MIN_EXAMPLES` this reports the count and declines. A factorisation
machine over ten observations will produce a number, and the number will be
noise wearing a decimal point.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from river import facto, metrics

from ..logging import get_logger

log = get_logger(__name__)

#: Examples before a fit is worth reporting. An FM has latent factors per
#: feature; fitting them from a few dozen rows is curve-drawing, not learning.
MIN_EXAMPLES = 200

#: How much better than a baseline counts as better at all. A model that edges
#: the running mean by one per cent over a few hundred examples has not learned
#: anything — it has been handed a small advantage by the baseline starting
#: cold, and calling that a win is how a system talks itself into believing its
#: own noise.
MARGIN = 0.05

#: Latent dimensions. Small on purpose — the interactions worth finding here
#: are low-order (side x regime, backcheck x strength), and capacity beyond
#: that is capacity to memorise.
N_FACTORS = 4

#: Features taken straight through. Everything here is already scale-free.
NUMERIC: tuple[str, ...] = (
    "approach_vol",
    "depth_vol",
    "strength",
    "run_vol",
    "experience",
    "pivot",
    "backcheck",
    "regime",
)

#: Features that are names rather than numbers, one-hot encoded.
CATEGORICAL: tuple[str, ...] = ("side", "interval")


@dataclass(slots=True)
class Example:
    """One resolved interaction: what we saw, and what followed."""

    features: dict[str, float]
    #: Signed push in volatility units. Positive is up.
    target: float
    when: float
    #: What the levels model predicted at the time, if it said anything.
    predicted: float | None = None

    @property
    def up(self) -> bool:
        return self.target > 0


def encode(context: dict[str, Any]) -> dict[str, float]:
    """Journal context -> the flat dict river wants.

    Categoricals become `name_value: 1.0` rather than an integer code. An
    integer would tell the model that `1h` sits between `15m` and `4h` on some
    scale it should interpolate along, which is true of the durations and not
    of anything the model does with them.
    """
    out: dict[str, float] = {}
    for name in NUMERIC:
        value = context.get(name)
        if isinstance(value, int | float):
            out[name] = float(value)
    for name in CATEGORICAL:
        value = context.get(name)
        if value:
            out[f"{name}_{value}"] = 1.0
    return out


def dataset(journal_db: Path | str, *, limit: int = 5_000, since: float = 0.0) -> list[Example]:
    """Assemble `(features, outcome)` pairs from the journal, oldest first.

    The outcome entry carries both, which is not an accident: it was written
    from the touch, and the touch holds the features it began with alongside
    what it resolved to. Joining back to the decision recovers what the levels
    model predicted, so the two can be compared on the same rows.
    """
    from .. import journal as jr

    try:
        rows = jr.read(journal_db, limit=limit)
    except FileNotFoundError:
        return []

    if since:
        rows = [entry for entry in rows if entry.time >= since]
    by_id = {entry.id: entry for entry in rows}
    found: list[Example] = []
    for entry in rows:
        if str(entry.kind) != "outcome":
            continue
        target = entry.context.get("push_vol")
        if not isinstance(target, int | float):
            continue
        features = encode(entry.context)
        if not features:
            continue
        parent = by_id.get(entry.parent)
        predicted = None
        if parent is not None:
            said = parent.context.get("expected_push_vol")
            if isinstance(said, int | float):
                predicted = float(said)
        found.append(
            Example(features=features, target=float(target), when=entry.time, predicted=predicted)
        )
    found.sort(key=lambda example: example.when)
    return found


@dataclass(slots=True)
class Report:
    """How the fit went, next to the things it has to beat."""

    examples: int
    #: Mean absolute error, in volatility units.
    model_mae: float = 0.0
    baseline_mae: float = 0.0
    levels_mae: float = 0.0
    levels_examples: int = 0
    #: Share of pushes whose direction the model called correctly.
    direction: float = 0.0
    base_rate: float = 0.0

    @property
    def enough(self) -> bool:
        return self.examples >= MIN_EXAMPLES

    @property
    def beats_baseline(self) -> bool:
        """Better than predicting the average, by enough to mean it."""
        return self.enough and self.model_mae < self.baseline_mae * (1.0 - MARGIN)

    @property
    def beats_levels(self) -> bool:
        """The one that decides whether this is worth having at all."""
        return (
            self.enough
            and self.levels_examples > 0
            and self.model_mae < self.levels_mae * (1.0 - MARGIN)
        )

    @property
    def verdict(self) -> str:
        if not self.enough:
            return f"not enough data — {self.examples} of {MIN_EXAMPLES} needed"
        if not self.beats_baseline:
            return (
                f"no better than predicting the average "
                f"({self.model_mae:.3f}v against {self.baseline_mae:.3f}v); "
                "the features are not helping"
            )
        if self.levels_examples and not self.beats_levels:
            return "beats the average but not the levels model it was meant to improve on"
        return "beats both the average and the levels model"

    def to_dict(self) -> dict[str, Any]:
        return {
            "examples": self.examples,
            "enough": self.enough,
            "model_mae": round(self.model_mae, 4),
            "baseline_mae": round(self.baseline_mae, 4),
            "levels_mae": round(self.levels_mae, 4),
            "levels_examples": self.levels_examples,
            "direction": round(self.direction, 4),
            "base_rate": round(self.base_rate, 4),
            "beats_baseline": self.beats_baseline,
            "beats_levels": self.beats_levels,
            "verdict": self.verdict,
        }

    def __str__(self) -> str:
        if not self.enough:
            return self.verdict
        return (
            f"{self.examples} examples · MAE {self.model_mae:.3f}v "
            f"(mean {self.baseline_mae:.3f}v, levels {self.levels_mae:.3f}v) · "
            f"direction {self.direction:.0%} vs {self.base_rate:.0%} · {self.verdict}"
        )


@dataclass(slots=True)
class Model:
    """A factorisation machine over touch features, fitted progressively."""

    n_factors: int = N_FACTORS
    seed: int = 7
    _fm: Any = field(default=None)
    _fitted: int = 0

    def __post_init__(self) -> None:
        if self._fm is None:
            self._fm = facto.FMRegressor(n_factors=self.n_factors, seed=self.seed)

    def predict(self, features: dict[str, float]) -> float:
        """Zero when there is nothing to say. Two cases, both real.

        `FMRegressor.predict_one` raises `AttributeError` — not something
        catchable by intent — in two situations, because its internal dot
        product returns a plain float where river expects a numpy scalar and
        calls `.item()` on it:

        - **nothing learned yet.** Progressive validation predicts *before* it
          learns, so the first example hits this every time. The discipline and
          the library disagree, and this is where they are reconciled.
        - **fewer than two features.** An FM models *pairwise* interactions, and
          one feature has no pairs. Real rows carry several, but a sparse
          journal entry would otherwise take down a running service.

        Zero is also the honest answer in both: a model with no history, or no
        interaction to look at, has no opinion about the next push.
        """
        if not self._fitted or len(features) < 2:
            return 0.0
        guess = float(self._fm.predict_one(features))
        # river's FM warns rather than raises when its latent factors go
        # non-finite — `invalid value encountered in scalar add` — and hands
        # back a NaN. A NaN propagates silently through `metrics.MAE`, which
        # then reports a NaN error the comparisons read as "not better", so a
        # diverged model would be scored as merely unhelpful. Zero is the
        # honest answer: a model that has produced a non-number has no opinion.
        if not math.isfinite(guess):
            log.warning("facto: model produced a non-finite prediction — treating as no opinion")
            return 0.0
        return guess

    def learn(self, features: dict[str, float], target: float) -> None:
        self._fm.learn_one(features, target)
        self._fitted += 1


def evaluate(examples: Sequence[Example], *, model: Model | None = None) -> Report:
    """Fit and score in one pass, predicting each example before learning it.

    Walk-forward by construction rather than by convention: there is no split
    to arrange incorrectly, and no later row can inform an earlier prediction.
    """
    if not examples:
        return Report(examples=0)

    model = model or Model()
    ordered = sorted(examples, key=lambda example: example.when)
    ups = sum(1 for example in ordered if example.up)

    # The baseline predicts the running mean, which is the fair comparison: it
    # gets the same one-pass, no-lookahead treatment the model does.
    mae = metrics.MAE()
    baseline = metrics.MAE()
    levels = metrics.MAE()
    seen: list[float] = []
    right = 0
    scored = 0

    for example in ordered:
        guess = model.predict(example.features)
        mae.update(example.target, guess)
        baseline.update(example.target, statistics.fmean(seen) if seen else 0.0)
        if example.predicted is not None:
            levels.update(example.target, example.predicted)
            scored += 1
        right += (guess > 0) == example.up
        model.learn(example.features, example.target)
        seen.append(example.target)

    return Report(
        examples=len(ordered),
        model_mae=mae.get(),
        baseline_mae=baseline.get(),
        levels_mae=levels.get() if scored else 0.0,
        levels_examples=scored,
        direction=right / len(ordered),
        base_rate=max(ups, len(ordered) - ups) / len(ordered),
    )


def fit(journal_db: Path | str, *, since: float = 0.0, **kwargs) -> Report:
    """Read the journal and report. The everyday entry point.

    `since` exists because a measurement bug does not only corrupt the numbers
    it produced — it corrupts every example recorded while it was live. Touch
    counts fed `experience` and `strength`, and a pooled base rate made `edge`
    wrong on every row, so examples from before those were fixed describe a
    model that no longer exists. Fitting across the boundary would teach the FM
    the relationship between features and outcomes *as they were mismeasured*,
    which is worse than having no model, because it would look like one.

    Pass a unix timestamp to count only what was recorded after a known-good
    point. There is no default: where the boundary sits is a judgement about
    this deployment's history, not something the code can know.
    """
    return evaluate(dataset(journal_db, since=since), **kwargs)
