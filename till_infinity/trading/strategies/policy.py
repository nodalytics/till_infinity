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

Keeps a decayed mean reward per (context, arm) and returns the best arm once it
has seen enough of it. Three rules, each of which exists because of something
this repository has already got wrong:

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

from dataclasses import dataclass, field
from typing import ClassVar

from .opportunity import PRESETS, Shape

#: Reward is in units of the trade's own risk, so it is already comparable
#: across instruments. These bounds are about malformed intents rather than
#: about unusual markets: a target 30,000 times the risk away is a fault.
CLIP: tuple[float, float] = (-3.0, 5.0)


@dataclass(slots=True)
class Score:
    """A decayed mean, and how much it rests on."""

    #: Exponentially weighted mean reward.
    mean: float = 0.0
    #: Observations, undecayed, so `seen` answers "how much do we know" rather
    #: than "how recent is it". The two questions want different counters and
    #: conflating them is how a stale cell looks confident.
    seen: int = 0

    def push(self, reward: float, decay: float) -> None:
        reward = max(CLIP[0], min(CLIP[1], reward))
        self.mean = reward if not self.seen else (1 - decay) * self.mean + decay * reward
        self.seen += 1


@dataclass(slots=True)
class Ledger:
    """Decayed mean reward per context and arm."""

    #: How fast old evidence stops counting. 0.05 gives a half-life of about
    #: fourteen observations, which is short enough to follow a regime and long
    #: enough not to chase one bad afternoon.
    decay: float = 0.05
    cells: dict[tuple[str, str], Score] = field(default_factory=dict)

    def observe(self, context: str, arm: str, reward: float) -> None:
        self.cells.setdefault((context, arm), Score()).push(reward, self.decay)

    def score(self, context: str, arm: str) -> Score | None:
        return self.cells.get((context, arm))

    def arms(self, context: str) -> dict[str, Score]:
        return {arm: s for (ctx, arm), s in self.cells.items() if ctx == context}


def context_of(feed: str, interval: str) -> tuple[str, ...]:
    """Context keys from most specific to least, for backing off.

    Family rather than instrument: gold and silver share a process in a way
    gold and a synthetic do not, and per-instrument cells would be thin for
    months. `research/failing.md` measures the family split as the one that
    actually separates.
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
    return (f"{family}|{interval}", family, "")


@dataclass(slots=True)
class Policy:
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

    def pick(self, feed: str, interval: str) -> tuple[Shape, str]:
        """The best-known shape for this context, and why it was chosen."""
        for context in context_of(feed, interval):
            best: tuple[float, str] | None = None
            for arm, score in self.ledger.arms(context).items():
                if score.seen < self.MIN_SEEN or arm not in self.arms:
                    continue
                if best is None or score.mean > best[0]:
                    best = (score.mean, arm)
            if best is not None:
                return self.arms[best[1]], f"{context or 'book'}:{best[1]} at {best[0]:+.3f}R"
        return self.fallback, "cold, using the measured default"
