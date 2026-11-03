"""Stability: does the result hold when the sample is cut up by time?

| test | answers |
| --- | --- |
| walk-forward | the stitched out-of-sample result, and its efficiency |
| walk-back | does a *frozen* setup hold era by era |
| day-block bootstrap | how wide the Sharpe's interval is, allowing for clustered days |

**Walk-forward and walk-back are not the same test and the difference is the
point.** Walk-forward refits on each window, so it measures a *process* - can
this be refitted as it goes. Walk-back freezes one setup and runs it across
eras, so it measures a *claim* - was this ever true elsewhere. A result can
pass the first and fail the second, and that combination means the refitting
was doing the work.

**Days are the block, not observations.** Intraday returns within a day share
the day's volatility, its news and its session, so resampling observations
independently understates the interval badly. `a-pair-of-bars-needs-the-hour-
of-day-null` measured half a two-bar statistic's suppression as the daily
cycle, which is the same dependence seen from the other side.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .metrics import sharpe


@dataclass(frozen=True, slots=True)
class Fold:
    """One train/test split and what each half scored."""

    index: int
    train_score: float
    test_score: float
    train_size: int
    test_size: int


@dataclass(frozen=True, slots=True)
class WalkForward:
    """Stitched out-of-sample performance, refitting as it goes."""

    folds: tuple[Fold, ...]
    #: The statistic on all out-of-sample segments joined end to end. This is
    #: the number that matters: a mean of per-fold scores flatters a strategy
    #: whose good folds are its short ones.
    stitched: float
    efficiency: float

    @property
    def positive_folds(self) -> int:
        return sum(1 for f in self.folds if f.test_score > 0)

    @property
    def passes(self) -> bool:
        """Stitched positive, and more than half the folds positive.

        Both, because either alone is weak: one enormous fold can carry a
        stitched result, and a majority of marginally positive folds can sum
        to nothing.
        """
        return self.stitched > 0 and self.positive_folds > len(self.folds) / 2

    def lines(self) -> list[str]:
        return [
            f"walk-forward: stitched {self.stitched:+.4f}, efficiency "
            f"{self.efficiency:.2f}, {self.positive_folds}/{len(self.folds)} folds positive"
        ]


def walk_forward(
    returns: Sequence[float],
    fit_and_score: Callable[[Sequence[float], Sequence[float]], tuple[float, list[float]]],
    *,
    folds: int = 6,
    minimum_train: int = 100,
) -> WalkForward:
    """Expanding-window walk-forward.

    `fit_and_score(train, test)` fits on `train` and returns
    `(in-sample score, out-of-sample returns)`. The caller owns the model;
    this owns the splitting and the stitching.

    **Expanding rather than rolling**, because a rolling window throws away
    history that a refit could use, and the question here is what the process
    would really have produced. A rolling variant is a different question and
    should be a different call.

    Efficiency is `stitched / mean in-sample`. Above 1 is suspicious rather
    than good: out-of-sample beating in-sample usually means the in-sample
    score was computed on something other than what was fitted.
    """
    n = len(returns)
    if folds < 2:
        raise ValueError("a walk-forward needs at least two folds")
    step = (n - minimum_train) // folds
    if step < 10:
        raise ValueError(
            f"{n} returns with {minimum_train} held for training leaves {step} per "
            f"fold - too few to score"
        )
    out: list[Fold] = []
    stitched: list[float] = []
    for i in range(folds):
        train_end = minimum_train + i * step
        test_end = train_end + step
        train = returns[:train_end]
        test = returns[train_end:test_end]
        if len(test) < 5:
            continue
        in_sample, oos = fit_and_score(train, test)
        stitched.extend(oos)
        out.append(
            Fold(
                index=i,
                train_score=in_sample,
                test_score=_score(oos),
                train_size=len(train),
                test_size=len(test),
            )
        )
    if not out:
        raise ValueError("no fold produced a scorable test segment")
    stitched_score = _score(stitched)
    mean_in = sum(f.train_score for f in out) / len(out)
    efficiency = (stitched_score / mean_in) if mean_in else 0.0
    return WalkForward(folds=tuple(out), stitched=stitched_score, efficiency=efficiency)


def _score(series: Sequence[float]) -> float:
    try:
        return sharpe(series)
    except ValueError:
        return 0.0


@dataclass(frozen=True, slots=True)
class Era:
    """One slice of history, scored by a setup that was not fitted to it."""

    index: int
    score: float
    size: int


@dataclass(frozen=True, slots=True)
class WalkBack:
    """A frozen setup, run era by era."""

    eras: tuple[Era, ...]

    @property
    def positive(self) -> int:
        return sum(1 for e in self.eras if e.score > 0)

    @property
    def worst(self) -> Era | None:
        return min(self.eras, key=lambda e: e.score, default=None)

    @property
    def passes(self) -> bool:
        """Positive in more than half the eras, and not catastrophic in any.

        The second clause is the one that matters. A setup that is mildly
        positive in five eras and ruinous in the sixth is not a stable setup;
        it is one whose regime has not arrived yet.
        """
        if not self.eras:
            return False
        worst = self.worst
        return self.positive > len(self.eras) / 2 and worst is not None and worst.score > -1.0

    def lines(self) -> list[str]:
        worst = self.worst
        tail = f", worst era {worst.index} at {worst.score:+.3f}" if worst else ""
        return [f"walk-back: {self.positive}/{len(self.eras)} eras positive{tail}"]


def walk_back(
    returns: Sequence[float],
    score: Callable[[Sequence[float]], float] | None = None,
    *,
    eras: int = 6,
) -> WalkBack:
    """Run one frozen setup across equal eras, newest to oldest.

    Nothing is refitted. **That is the whole difference from walk-forward**,
    and a result that passes there and fails here was being carried by the
    refitting - which is a process that works rather than a claim that holds.
    """
    n = len(returns)
    if eras < 2:
        raise ValueError("a walk-back needs at least two eras")
    size = n // eras
    if size < 10:
        raise ValueError(f"{n} returns over {eras} eras leaves {size} each - too few")
    scorer = score or _score
    out = []
    for i in range(eras):
        # Newest first, so era 0 is the most recent - the one a reader asks
        # about first.
        end = n - i * size
        chunk = returns[end - size : end]
        out.append(Era(index=i, score=scorer(chunk), size=len(chunk)))
    return WalkBack(eras=tuple(out))


@dataclass(frozen=True, slots=True)
class Interval:
    """A bootstrapped confidence interval for a statistic."""

    point: float
    low: float
    high: float
    draws: int
    block: str

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0.0 or self.high < 0.0

    def lines(self) -> list[str]:
        return [
            f"{self.block}-block CI: {self.point:+.4f} "
            f"[{self.low:+.4f}, {self.high:+.4f}] over {self.draws} draws"
            + ("" if self.excludes_zero else " - includes zero")
        ]


def day_block_interval(
    returns: Sequence[float],
    day_of: Sequence[int],
    *,
    statistic: Callable[[Sequence[float]], float] | None = None,
    draws: int = 1_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Interval:
    """Resample whole days, keeping what happens inside a day together.

    `day_of[i]` is the day index of `returns[i]`. Days are resampled with
    replacement and their contents kept intact, so the interval carries the
    within-day dependence instead of assuming it away.

    **The interval is usually much wider than the i.i.d. one**, and that is
    the correct answer rather than a disappointing one: intraday returns share
    the day's volatility, its news and its session, and this desk measures
    size autocorrelation of 0.21 and an intraday volatility cycle peaking at
    three times quiet.
    """
    if len(returns) != len(day_of):
        raise ValueError(f"{len(returns)} returns and {len(day_of)} day labels")
    scorer = statistic or _score
    days: dict[int, list[float]] = {}
    for value, day in zip(returns, day_of, strict=True):
        days.setdefault(day, []).append(value)
    keys = list(days)
    if len(keys) < 4:
        raise ValueError(f"{len(keys)} distinct days is too few to resample")

    point = scorer(returns)
    values: list[float] = []
    for i in range(draws):
        rng = random.Random(seed * 2_654_435_761 + i)
        picked = [rng.choice(keys) for _ in keys]
        sample = [x for day in picked for x in days[day]]
        try:
            values.append(scorer(sample))
        except (ValueError, ZeroDivisionError):
            continue
    if not values:
        raise ValueError("no bootstrap draw could be scored")
    values.sort()
    tail = (1.0 - confidence) / 2.0
    low = values[max(0, math.floor(tail * len(values)))]
    high = values[min(len(values) - 1, math.ceil((1.0 - tail) * len(values)))]
    return Interval(point=point, low=low, high=high, draws=len(values), block="day")
