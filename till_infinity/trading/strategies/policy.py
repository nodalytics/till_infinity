"""Which shape to give an opportunity, learned from what every shape got.

## Why this is not a bandit, and why that is the stronger position

A bandit exists to handle **partial feedback**: it sees the reward of the arm
it pulled and never the arms it did not, and every part of its machinery -
exploration, confidence bounds, Thompson sampling's posterior - is the price of
that missing counterfactual. research/bandits.md states the test:

> If you would have learned the outcome anyway, whatever you chose, it is not a
> bandit problem.

Here the outcome *is* learned anyway. `_also_wanted` asks every strategy what
it would have done with each signal, and `Untaken` now follows each of those
intents to its own target or stop on the live quote stream. Every arm reports a
reward on every signal. That is full information, and the right algorithm for
choosing among experts whose losses are all observed is **exponential weights**
- Hedge - which is Exp3 with the exploration term removed, because that term
buys information already in hand.

Paying for exploration you do not need is not caution. It is trading real money
to rediscover something the record already says.

**Where exploration does earn its place**, and where a genuine bandit belongs,
is the half a stored price path cannot settle: whether a resting order actually
filled, what spread was really paid, whether a partial got done. Those are only
ever observed on trades actually taken. That is `Shape.PENDING`, and it is not
what this module decides yet.

## What it does

Keeps a decayed mean reward per (context, arm) and returns an arm other than the
default only when its lead over the default is beyond what noise produces. Four
rules, each of which exists because of something this repository has already got
wrong:

* **A lead must be significant, over a default that is in the race.**
  `research/docs/zeroskill.md` drove this module with rewards that carry no
  skill: it departed from its default in **100%** of warm contexts, because it
  took the highest mean among warm arms with no margin, and the default was
  never scored often enough to be warm. On noise the winner's lead reaches
  0.35-0.42R at the 95th percentile. So an arm now wins only when the default
  is warm too (the service scores the default on every signal) and the lead
  clears `MARGIN_Z` standard errors of the difference, on each arm's effective
  sample size. See `Policy.choose`.
* **Cold means the default, never a guess.** An arm below `MIN_SEEN` cannot win.
  A policy that acts on four observations is how a 5-stop sample became an
  instrument-wide sizing rule, and how a corridor boundary was set on 46 setups
  that 40,803 later contradicted.
* **Context backs off rather than fragments.** The ranking already differs
  sharply by instrument family, so the table is keyed per family and per
  interval - but a thin cell falls back to the broader one instead of deciding
  on three observations.
* **Rewards are clipped.** Five intents of 1,757 carried an implied
  reward-to-risk up to 30,338, and one of them touching produced +23R a trade
  across the whole book on the first ranking run. `CLIP` is what stops a single
  malformed target from owning the policy.

Nothing here sizes a position or overrides a guard. It chooses the shape of a
trade; `scaling.py` and `risk.py` keep their veto, which is the arrangement the
operator asked for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import ClassVar

from ...shared.state import Restorable
from .opportunity import PRESETS, Shape

#: Reward is in units of the trade's own risk, so it is already comparable
#: across instruments. These bounds are about malformed intents rather than
#: about unusual markets: a target 30,000 times the risk away is a fault.
CLIP: tuple[float, float] = (-3.0, 5.0)

#: How fast old evidence stops counting. It was 0.05, a memory of about 40
#: effective observations - too few for any edge this desk could have to clear
#: noise (`research/docs/zeroskill.md`: rewards sd 0.75R, so the standard error
#: of a difference of two such means is about 0.24R, against leads of a tenth of
#: an R). 0.01 remembers about 200 (half-life about 70). The price is
#: adaptivity: a change in which shape works now takes a few hundred signals in a
#: context to show, where it took a few dozen - acceptable, because the policy
#: may only ever pick an exit geometry, never size or take a trade.
DECAY = 0.01

#: Standard errors a lead over the default must clear. One-sided Bonferroni for
#: about 8 challengers across about 30 warm contexts (0.05 / 240 -> 3.5): the
#: policy is consulted in every context at once, so its false-departure rate
#: is judged across the book, not per cell (`zeroskill.md`'s rule 4).
MARGIN_Z = 3.5

#: The reward spread assumed where a score's own is unknown - one restored from
#: state written before `square` existed. Measured: 0.753R over the journal's
#: 773 untaken rewards (`zeroskill.md`). Not zero, which would make any lead
#: significant the moment a deploy restored the ledger.
PRIOR_SD = 0.75


#: What a score restored from state written before `weights` existed is assumed to rest on, at
#: most: the old decay's own limit, (2 - 0.05) / 0.05. Those means were plain EWMAs started at
#: their first reward, so they rest on no more than this whatever `seen` says.
LEGACY_EFFECTIVE = 39.0


@dataclass(slots=True)
class Score(Restorable):
    """A decayed mean and spread, and how much they rest on."""

    #: The mean reward: an equal-weighted average until `1 / decay` observations, an EWMA after.
    #: A plain EWMA started at the first reward keeps most of its weight on that one reward for
    #: its first hundred-odd observations - at decay 0.01 and 50 observations the first still
    #: weighs 61%, so the mean rests on under three - which is what let noise win.
    mean: float = 0.0
    #: Observations, undecayed, so `seen` answers "how much do we know" rather
    #: than "how recent is it". The two questions want different counters and
    #: conflating them is how a stale cell looks confident.
    seen: int = 0
    #: The same average of the squared reward, for the spread. -1 is "unknown": a score restored
    #: from state written before this field existed. A real one is never below 0.
    square: float = -1.0
    #: The sum of the squared weights behind `mean`, so the effective sample size is 1 / this,
    #: exactly, whatever the history of weights. -1 is "unknown", as for `square`.
    weights: float = -1.0

    def push(self, reward: float, decay: float) -> None:
        reward = max(CLIP[0], min(CLIP[1], reward))
        if not self.seen:
            self.mean, self.square, self.weights, self.seen = reward, reward * reward, 1.0, 1
            return
        if self.square < 0.0:  # restored without a spread: start it at the measured one
            self.square = self.mean * self.mean + PRIOR_SD * PRIOR_SD
        if self.weights < 0.0:
            self.weights = 1.0 / min(float(self.seen), LEGACY_EFFECTIVE)
        self.seen += 1
        w = max(decay, 1.0 / self.seen)
        self.mean = min(max((1 - w) * self.mean + w * reward, CLIP[0]), CLIP[1])
        self.square = (1 - w) * self.square + w * reward * reward
        self.weights = (1 - w) * (1 - w) * self.weights + w * w

    @property
    def variance(self) -> float:
        """The variance of the reward; `PRIOR_SD` squared while it is unknown."""
        if self.square < 0.0:
            return PRIOR_SD * PRIOR_SD
        return max(self.square - self.mean * self.mean, 0.0)

    def effective(self) -> float:
        """How many observations `mean` effectively rests on: 1 / the sum of squared weights."""
        if self.weights > 0.0:
            return 1.0 / self.weights
        return min(float(self.seen), LEGACY_EFFECTIVE)


@dataclass(slots=True)
class Ledger(Restorable):
    """Decayed mean reward per context and arm."""

    #: See `DECAY`. A ledger restored from an older state carries the decay it
    #: was written with; the service resets it to `DECAY` on load.
    decay: float = DECAY
    cells: dict[tuple[str, str], Score] = field(default_factory=dict)

    def observe(self, context: str, arm: str, reward: float) -> None:
        self.cells.setdefault((context, arm), Score()).push(reward, self.decay)

    def score(self, context: str, arm: str) -> Score | None:
        return self.cells.get((context, arm))

    def arms(self, context: str) -> dict[str, Score]:
        return {arm: s for (ctx, arm), s in self.cells.items() if ctx == context}


def family_of(feed: str) -> str:
    """Which process this instrument belongs to.

    Family rather than instrument: gold and silver share a process in a way gold
    and a synthetic do not, and per-instrument cells would be thin for months.
    `research/failing.md` measures the family split as the one that separates.
    """
    low = feed.lower()
    if "boom" in low:
        family = "boom"
    elif "crash" in low:
        family = "crash"
    elif any(k in low for k in ("volatility", "step", "jump", "range_break")):
        family = "volatility"
    elif any(k in low for k in ("xau", "gold", "silver", "xag", "brent", "wti", "oil")):
        family = "metals/oil"
    elif any(k in low for k in ("btc", "eth")):
        family = "crypto"
    elif len(low) == 6 and low.isalpha():
        family = "fx"
    else:
        family = "index"
    return family


def context_of(feed: str, interval: str) -> tuple[str, ...]:
    """Context keys from most specific to least, for backing off."""
    family = family_of(feed)
    return (f"{family}|{interval}", family, "")


@dataclass(slots=True)
class Policy(Restorable):
    """Pick a shape for an opportunity, from what every shape has been worth."""

    #: Observations a cell needs before it may beat the default.
    MIN_SEEN: ClassVar[int] = 30

    ledger: Ledger = field(default_factory=Ledger)
    #: What to do when nothing is known, which is most of the time at first.
    fallback: Shape = field(default_factory=Shape)
    #: The arms on offer, by name. Defaults to the named strategies as points
    #: plus the measured default, so the space is anchored to things that ran.
    arms: dict[str, Shape] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.arms:
            self.arms = {shape.named(): shape for shape in PRESETS.values()}
            self.arms[self.fallback.named()] = self.fallback

    def observe(self, feed: str, interval: str, arm: str, reward: float) -> None:
        """Credit an arm with what it was worth, at every context it belongs to.

        Every level, not just the most specific one, so the broad cells stay
        warm enough to back off onto. A cell that only fills when its narrow
        sibling is cold is a cell that is never ready when needed.
        """
        for context in context_of(feed, interval):
            self.ledger.observe(context, arm, reward)

    def choose(self, context: str) -> tuple[str, float, float] | None:
        """In one context: `(arm, lead, margin)` for an arm whose lead over the default is
        beyond noise, else None.

        The default must itself be warm - an arm cannot beat a default that has not been
        measured, which is how every warm context departed on noise - and the best challenger's
        lead must clear `MARGIN_Z` standard errors of the difference of the two decayed means.
        """
        fallback = self.fallback.named()
        arms = self.ledger.arms(context)
        default = arms.get(fallback)
        if default is None or default.seen < self.MIN_SEEN:
            return None
        warm = [
            (arm, s)
            for arm, s in arms.items()
            if arm != fallback and arm in self.arms and s.seen >= self.MIN_SEEN
        ]
        if not warm:
            return None
        arm, best = max(warm, key=lambda kv: kv[1].mean)
        spread = math.sqrt(
            best.variance / best.effective() + default.variance / default.effective()
        )
        lead, margin = best.mean - default.mean, MARGIN_Z * spread
        return (arm, lead, margin) if lead > margin else None

    def pick(self, feed: str, interval: str) -> tuple[Shape, str]:
        """The shape for this context, and why: a challenger only where it has earned it."""
        measured = False
        for context in context_of(feed, interval):
            chosen = self.choose(context)
            if chosen is not None:
                arm, lead, margin = chosen
                return (
                    self.arms[arm],
                    f"{context or 'book'}:{arm} leads the default by {lead:+.3f}R "
                    f"(margin {margin:.3f}R)",
                )
            got = self.ledger.score(context, self.fallback.named())
            measured = measured or (got is not None and got.seen >= self.MIN_SEEN)
        if measured:
            return self.fallback, "no shape leads the measured default beyond noise"
        return self.fallback, "cold, using the measured default"


@dataclass(slots=True)
class Entries:
    """Which strategy's *entry* is worth taking on a family. Recording only.

    A second ledger rather than more arms in the first, because the two learn
    different things and need different densities.

    `Policy` chooses exit geometry, and `_credit` keys its arms by shape on
    purpose: two strategies with the same exit pool their evidence, so
    `level-scalp` and `sweep-aware` are one arm there. That is right for
    geometry - and it makes "does this strategy read gold better than that one"
    unaskable, because the strategies disappear into their shapes. Everything the
    shape ledger has learned differs by `target`, `trail` and `hold`, never by a
    strategy name, and that is why.

    This asks the other question and pays for it in density. Keyed on the family
    alone, with no interval split: seven families by seventeen strategies is 119
    cells, where splitting by interval would be eight hundred. The shape ledger
    already sits at 241 cells and 9.7 observations each, and a thinner table
    would be noise with a ranking printed over it.

    **Nothing reads this.** It records, so that whether the interaction exists
    can be decided on evidence instead of assumed. The evidence arrives free:
    `Untaken` already follows every strategy's intent to its own target or stop
    on the live quote stream, so every strategy reports on every signal whether
    or not it traded - which is the full-information setting `Policy`'s docstring
    argues makes exponential weights right and a bandit's exploration a waste.
    """

    #: Observations a cell needs before it is worth reading at all. The same
    #: floor `Policy` uses, for the same reason: a ranking on four observations
    #: is how a 5-stop sample became an instrument-wide sizing rule.
    MIN_SEEN: ClassVar[int] = 30

    ledger: Ledger = field(default_factory=Ledger)

    def observe(self, feed: str, by: str, reward: float) -> None:
        """Credit one strategy with what its entry was worth on this family."""
        if by:
            self.ledger.observe(family_of(feed), by, reward)

    def ranking(self, feed: str, warm_only: bool = True) -> list[tuple[str, Score]]:
        """Strategies on this family, best first. Empty while it is cold."""
        arms = self.ledger.arms(family_of(feed))
        keep = [(n, s) for n, s in arms.items() if s.seen >= self.MIN_SEEN or not warm_only]
        return sorted(keep, key=lambda kv: -kv[1].mean)

    def describe(self) -> str:
        """One line per family, for the operator to read before trusting any of it."""
        families: dict[str, dict[str, Score]] = {}
        for (family, arm), score in self.ledger.cells.items():
            families.setdefault(family, {})[arm] = score
        if not families:
            return "entries: nothing recorded yet"
        out = []
        busiest = sorted(families.items(), key=lambda kv: -sum(s.seen for s in kv[1].values()))
        for family, arms in busiest:
            warm = sorted(
                ((n, s) for n, s in arms.items() if s.seen >= self.MIN_SEEN),
                key=lambda kv: -kv[1].mean,
            )
            seen = sum(s.seen for s in arms.values())
            best = (
                ", ".join(f"{n} {s.mean:+.2f}R(n={s.seen})" for n, s in warm[:3])
                if warm
                else f"none of {len(arms)} warm yet"
            )
            out.append(
                f"  {family or 'book':<12} {seen:>6} obs over {len(arms):>2} strategies - {best}"
            )
        return "entries, by family:\n" + "\n".join(out)
