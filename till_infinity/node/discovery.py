"""The discovery node: where candidates come from, and how they are counted.

    discovery -> backtest -> small capital -> full capital

**Almost all of this is Nautilus's.** `BacktestNode(configs=[...]).run()` takes
many run configs, runs them, and returns a `BacktestResult` each - which is
exactly a trial set, with `stats_returns` carrying whatever
`PortfolioStatistic`s were registered. An earlier version of this module had
its own `Search` with its own `measure` callable and its own list of results,
which was a second backtest runner beside the engine's. It is gone.

What is left is the part Nautilus has no opinion about: **the accounting that
makes a deflated Sharpe honest.** The engine will happily run a thousand
configs and report the best one; it does not know, or care, that reporting the
best of a thousand as though it were the only one is the error. So this module
turns a set of proposals into run configs, and turns the results back into a
`Gate` that cannot be constructed without the trial count.

This desk has the failure on record. A block of eight found structure in 27 of
36 *placebo* pools; a trailing z-score took +0.111 of a +0.137 effect from its
own shuffled twin. In both cases the search was fine and the accounting was
not.

**What a model may be asked.** `direction-is-closed-not-just-null` is
measured: the gate finds a *planted* drift at z +2.90 and earns 2% of a
spread. An agent proposing "which way" proposes into the one question already
closed here. `Proposal.question` records which was asked, so a later reader
can tell a regime claim from a direction claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Question(StrEnum):
    """What a candidate claims. The claims are not equally open."""

    #: Which way price goes. Measured closed here; allowed, recorded, and held
    #: to the same gate - but not expected to pass.
    DIRECTION = "direction"
    #: How much it will move. Where the measured edge is.
    DISPERSION = "dispersion"
    #: Whether to trade at all, now, on this feed.
    PARTICIPATION = "participation"
    #: Which state the market is in.
    REGIME = "regime"
    #: What a calendar or news item implies.
    CONTEXT = "context"


@dataclass(frozen=True, slots=True)
class Proposal:
    """One thing to try: a strategy config plus where it came from."""

    name: str
    question: Question
    #: Which harness, which search, which model and prompt. A candidate whose
    #: origin cannot be stated cannot be reproduced or defended.
    origin: str
    #: The `ImportableStrategyConfig` this trial runs, as Nautilus takes it.
    strategy: Any = None
    #: What it is measured against: a shuffled twin, a distance-matched
    #: placebo, a walk through the same detector.
    control: str = ""

    def __post_init__(self) -> None:
        if not self.origin:
            raise ValueError(
                f"proposal {self.name!r} has no origin - a candidate that cannot say "
                f"how it was found cannot be reproduced or counted"
            )


@dataclass(frozen=True, slots=True)
class Trial:
    """One `BacktestResult`, read. Kept whether it won or lost."""

    proposal: Proposal
    result: Any
    #: The per-period Sharpe, taken from the statistics the node registered
    #: rather than recomputed here.
    sharpe: float
    episodes: int
    returns: tuple[float, ...] = ()

    @classmethod
    def of(cls, proposal: Proposal, result: Any, returns: tuple[float, ...] = ()) -> Trial:
        """Read a Nautilus result.

        `SR_period` is ours, registered through `PortfolioStatistic` - see
        `node/statistics.py`. Taken from there rather than recomputed so that
        the figure a gate judges is the same figure the backtest reported.
        """
        stats = getattr(result, "stats_returns", None) or {}
        return cls(
            proposal=proposal,
            result=result,
            sharpe=float(stats.get("SR_period") or 0.0),
            episodes=int(getattr(result, "total_positions", 0) or 0),
            returns=returns,
        )


@dataclass(slots=True)
class Trials:
    """Every trial a search produced, including the ones that lost.

    **Keeping the losers is the whole function of this class.** The deflated
    Sharpe needs `Var(SR_trials)`, which only exists if the search kept what it
    rejected - and a guessed variance makes the deflation decorative. So
    `best()` is a view over the set rather than the thing that was returned.
    """

    kept: list[Trial] = field(default_factory=list)
    failed: list[tuple[Proposal, str]] = field(default_factory=list)

    def add(self, trial: Trial) -> None:
        self.kept.append(trial)

    def refuse(self, proposal: Proposal, why: str) -> None:
        """A proposal that could not be measured is still one that was tried.

        Dropping it silently would undercount the search, which is the one
        input the deflation depends on.
        """
        self.failed.append((proposal, why))

    @property
    def attempted(self) -> int:
        return len(self.kept) + len(self.failed)

    def sharpes(self) -> tuple[float, ...]:
        return tuple(t.sharpe for t in self.kept)

    def best(self, question: Question | None = None) -> Trial | None:
        pool = [t for t in self.kept if question is None or t.proposal.question == question]
        return max(pool, key=lambda t: t.sharpe) if pool else None

    def asked(self) -> dict[str, int]:
        """How many candidates asked each kind of question.

        A run that is mostly `DIRECTION` is spending itself on the question
        measured closed here.
        """
        counts: dict[str, int] = {}
        for trial in self.kept:
            key = trial.proposal.question.value
            counts[key] = counts.get(key, 0) + 1
        return counts


def read(proposals: list[Proposal], results: list[Any]) -> Trials:
    """Pair proposals with the `BacktestResult`s `BacktestNode.run()` returned.

    Positional, because `BacktestNode` returns results in the order of the
    configs it was given. A length mismatch is refused rather than zipped
    short, which would silently drop trials from the count.
    """
    if len(proposals) != len(results):
        raise ValueError(
            f"{len(proposals)} proposals and {len(results)} results - the trial count "
            f"is what the deflation rests on, so a mismatch cannot be zipped away"
        )
    trials = Trials()
    for proposal, result in zip(proposals, results, strict=True):
        trials.add(Trial.of(proposal, result))
    return trials


def gate_from(trials: Trials, trial: Trial, *, name: str = "backtest") -> Any:
    """Build the backtest gate, carrying the search's own count.

    The one function joining the halves: a gate cannot be constructed without
    the trial set, so the number of candidates cannot be left out by omission.
    """
    from .promotion import Gate

    return Gate(
        name=name,
        criterion="DSR >= 0.95",
        control=trial.proposal.control or "none declared",
        candidates=trials.attempted,
        episodes=trial.episodes,
        trial_sharpes=trials.sharpes(),
        returns=trial.returns,
    )


def summarise(trials: Trials) -> str:
    """One readable line, with the numbers that decide the gate."""
    best = trials.best()
    head = f"{trials.attempted} attempted, {len(trials.kept)} measured, {len(trials.failed)} failed"
    return f"{head}; best {best.proposal.name} at SR {best.sharpe:.3f}" if best else head
