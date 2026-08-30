"""Price as a sequence of symbols, and what tends to follow what.

`patterns.py` already asks "has this shape happened before", and answers it with
dynamic time warping against every shape it has stored - a *continuous*
comparison with a distance threshold. That is the right tool for "is this the
same shape", and the wrong one for "what usually comes next", because a
continuous space has no next.

So this discretises first. Each leg between consecutive turning points becomes
one symbol from its direction and its size in volatility units:

    U1  up, between half and one and a half units
    D3  down, about three units
    F   flat - shorter than half a unit, which is not a leg

A finite vocabulary, derived from the series rather than clustered into
existence, and scale-free by construction: `U2` means the same thing on gold
and on eurusd, which is the property that lets one instrument's history inform
another's.

## Counting, not fitting

Given the last `k` symbols, what followed? That is a conditional distribution
and the honest way to estimate it is to count. No gradient, no parameters, and -
importantly - no capacity to memorise: a context that has occurred four times
has an estimate made of four observations and says so.

**Backoff** is the one piece of machinery. A long context is more specific and
almost always rarer, so the model asks for the longest context with at least
`MIN_COUNT` observations and shortens until it finds one. Without it, the model
is silent exactly where it is most confident and loud where it has three
examples.

## What this is not

It is not a language model and the resemblance should not be oversold. There is
no learned representation, no attention, no depth; what carries over from that
literature is the framing - a sequence over a finite vocabulary with a backoff
n-gram baseline - and the reason to start there is that the baseline is what
anything more elaborate has to beat, and nobody has established it here.

The prediction is a **forward return in volatility units**, not the next
symbol. The next symbol is a means; what a trade needs is a number with a sign
and a size, and scoring on the symbol would report accuracy on a quantity
nobody acts on.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from .pips import Point
from .state import Restorable
from .volatility import Volatility

#: Legs shorter than this are not legs. In volatility units.
FLAT_VOL = 0.5

#: The largest size a symbol distinguishes. Beyond it everything is "a big
#: move", because the difference between six units and nine is not something a
#: few thousand observations can say anything about.
MAX_STEP = 4

#: How many symbols of context the longest model keeps.
ORDER = 3

#: How many observations a context needs before it is used rather than backed
#: off from.
MIN_COUNT = 8

FLAT = "F"


def symbol(size_vol: float) -> str:
    """One leg as a symbol. Direction and magnitude, nothing else."""
    if abs(size_vol) < FLAT_VOL:
        return FLAT
    step = min(MAX_STEP, max(1, round(abs(size_vol))))
    return ("U" if size_vol > 0 else "D") + str(step)


def tokens(points: Sequence[Point], vol: Volatility) -> list[str]:
    """The legs between consecutive turns, as symbols, oldest first."""
    out: list[str] = []
    for before, after in pairwise(points):
        if not before.price:
            continue
        moved = (after.price - before.price) / before.price * 10_000
        out.append(symbol(vol.units(moved)))
    return out


@dataclass(slots=True)
class Following(Restorable):
    """What happened after one context: how often, and how far."""

    n: float = 0.0
    total: float = 0.0
    squares: float = 0.0

    def add(self, moved: float) -> None:
        self.n += 1.0
        self.total += moved
        self.squares += moved * moved

    @property
    def mean(self) -> float:
        return self.total / self.n if self.n else 0.0

    @property
    def sigma(self) -> float:
        if self.n < 2:
            return 0.0
        var = self.squares / self.n - self.mean**2
        return math.sqrt(max(var, 0.0))

    @property
    def t(self) -> float:
        """How many standard errors the mean is from zero.

        The number that decides whether this context says anything. A mean of
        0.4 units over six observations with a sigma of two is noise, and
        reporting the mean alone would present it as a forecast.
        """
        if self.n < 2 or self.sigma <= 1e-9:
            return 0.0
        return self.mean / (self.sigma / math.sqrt(self.n))


@dataclass(slots=True)
class Grammar(Restorable):
    """Contexts and what followed them, with backoff.

    Keyed by the context joined with "|", at every order from 1 to `ORDER`, so
    a lookup can shorten without re-deriving anything.
    """

    order: int = ORDER
    minimum: float = MIN_COUNT
    counts: dict[str, Following] = field(default_factory=dict)
    #: Walk-forward score, kept the same way everything else here keeps one:
    #: the model predicts before it learns, and is judged against predicting
    #: the running mean.
    seen: float = 0.0
    error: float = 0.0
    variance: float = 0.0
    mean: float = 0.0

    @staticmethod
    def key(context: Sequence[str]) -> str:
        return "|".join(context)

    def learn(self, context: Sequence[str], moved: float) -> None:
        """Record that this move followed this context, at every order."""
        for size in range(1, min(self.order, len(context)) + 1):
            name = self.key(context[-size:])
            found = self.counts.get(name)
            if found is None:
                found = self.counts[name] = Following()
            found.add(moved)

    def lookup(self, context: Sequence[str]) -> tuple[Following, int] | None:
        """The longest context with enough behind it, and how long it was.

        None when even a single symbol has not been seen `minimum` times, which
        is the correct answer early and stays the correct answer for a symbol
        that is genuinely rare.
        """
        for size in range(min(self.order, len(context)), 0, -1):
            found = self.counts.get(self.key(context[-size:]))
            if found is not None and found.n >= self.minimum:
                return found, size
        return None

    def predict(self, context: Sequence[str]) -> float | None:
        """Expected forward move in volatility units, or None."""
        got = self.lookup(context)
        return got[0].mean if got else None

    def observe(self, context: Sequence[str], moved: float) -> float | None:
        """Predict, score, then learn. Returns what it said beforehand."""
        said = self.predict(context)
        if said is not None:
            keep = max(0.0, 1.0 - 1.0 / 2_000.0)
            self.seen = self.seen * keep + 1.0
            self.error = self.error * keep + (moved - said) ** 2
            self.variance = self.variance * keep + (moved - self.mean) ** 2
            self.mean += (moved - self.mean) / self.seen
        self.learn(context, moved)
        return said

    @property
    def r2(self) -> float:
        if self.variance <= 1e-12:
            return 0.0
        return 1.0 - self.error / self.variance

    @property
    def warm(self) -> bool:
        return self.seen >= 50.0

    def strongest(self, limit: int = 10) -> list[tuple[str, Following]]:
        """Contexts whose next move is furthest from zero, by t.

        Reported by `t` rather than by mean, because the contexts with the
        largest means are the rarest ones by construction and a list of them is
        a list of small samples.
        """
        ready = [(name, f) for name, f in self.counts.items() if f.n >= self.minimum]
        ready.sort(key=lambda kv: -abs(kv[1].t))
        return ready[:limit]

    def prune(self, keep: int = 20_000) -> int:
        """Drop the least-seen contexts. This runs forever."""
        if len(self.counts) <= keep:
            return 0
        ordered = sorted(self.counts.items(), key=lambda kv: -kv[1].n)
        dropped = len(self.counts) - keep
        self.counts = dict(ordered[:keep])
        return dropped
