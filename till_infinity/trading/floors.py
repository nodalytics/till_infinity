"""One threshold, two distributions, and why that produced a one-sided book.

`min_probability` is a single number applied to the probability a call carries
in the direction it claims. Measured over 7,498 published level calls, those
two directions do not have the same distribution:

| direction | n | median | passes 0.75 | passes 0.85 |
| --- | ---: | ---: | ---: | ---: |
| up | 3,608 | 0.824 | 79.9% | 38.7% |
| down | 3,890 | 0.880 | 95.9% | 61.5% |

The signals themselves are balanced - 48.1% up against 51.9% down - so the
model offers both directions almost evenly and is simply *more confident* when
it says down. A single absolute floor on an asymmetric distribution therefore
lets nearly every sell through and refuses one buy in five, and the book comes
out 21 sells to 4 buys with no rule anywhere saying it should.

## Why a percentile here and not elsewhere

[edge.md](../../docs/edge.md) measured a rolling quantile losing to a matched
constant four times out of four, and a walk-forward test of an adaptive
probability floor came out **worse than no floor at all**. Three measured nulls
on dynamic rules is a strong prior against another one.

What makes this different is the same distinction edge.md itself draws. `edge`
was already scale-free, so normalising it per cell destroyed a comparability it
had. A directional probability is *not* comparable across directions - the two
groups demonstrably sit in different places - and a constant that means "the
top fifth" for one means "the top half" for the other. That is the case where a
quantile is the honest form rather than a clever one.

**The matched-constant version is still available and is the one the evidence
favours**: two fixed floors, one per direction, chosen once. `by_direction`
does that with no estimation at all. The percentile is for when the
distributions drift and a fixed pair would silently stop meaning what it meant.

## What it does not do

It does not adapt to outcomes. Raising a bar after a loss and lowering it after
a win was the rule that lost to no rule, and nothing here does that: the
distribution being tracked is of *what the model says*, not of what happened
next, so a losing streak cannot tighten it and a winning one cannot loosen it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..structures.state import Restorable

#: Calls per direction before a percentile means anything. Below it the floor
#: falls back to whatever absolute number was configured, because a quantile of
#: forty observations is a statement about forty observations.
WARMUP = 200

#: How many recent calls each direction keeps. Long enough to be a
#: distribution, short enough to still describe this market.
MEMORY = 2_000


@dataclass(slots=True)
class Floors(Restorable):
    """The recent distribution of claimed probability, kept per direction."""

    #: Which percentile to sit at, in [0, 1]. 0.5 keeps the better half of each
    #: direction's calls, 0.8 the top fifth.
    percentile: float = 0.0
    _seen: dict[str, deque[float]] = field(default_factory=dict)

    def _for(self, direction: str) -> deque[float]:
        got = self._seen.get(direction)
        if got is None:
            got = self._seen[direction] = deque(maxlen=MEMORY)
        return got

    def observe(self, direction: str, probability: float) -> None:
        """Note what the model claimed, whatever is decided about it."""
        if not direction or not 0.0 < probability <= 1.0:
            return
        self._for(direction).append(probability)

    def floor(self, direction: str, fallback: float) -> float:
        """The bar for this direction. `fallback` until there is a distribution.

        Never *below* the fallback: the percentile exists to correct an
        asymmetry, not to open a door the absolute floor was holding shut.
        """
        if self.percentile <= 0:
            return fallback
        seen = self._seen.get(direction)
        if not seen or len(seen) < WARMUP:
            return fallback
        ranked = sorted(seen)
        at = min(len(ranked) - 1, int(self.percentile * (len(ranked) - 1)))
        return max(fallback, ranked[at])

    def counts(self) -> dict[str, int]:
        """How much each direction has behind it. For the log, and for doubt."""
        return {k: len(v) for k, v in self._seen.items()}


def by_direction(up: float, down: float) -> dict[str, float]:
    """Two fixed floors, one per direction - the matched-constant version.

    Here because it is the shape this repository's own measurements keep
    favouring, and because writing it down beside the percentile makes the
    choice visible rather than implicit.
    """
    return {"up": up, "down": down}
