"""Is the market trending through here, or oscillating inside it?

Measured 2026-08-27 over 54,143 resolutions, this separates outcomes better
than anything else this repository has tried - and not in the direction the
obvious reading suggests:

| efficiency | break share | R with the level |
| --- | ---: | ---: |
| 0.017-0.096 (chop) | 11.3% | 0.807 |
| 0.985-1.000 (trend) | **1.4%** | **1.149** |

**A trend does not run levels over.** Breaks are *rarest* in the most trending
decile - 1.4% against 11.3% in the chop. What a trend does is make a level hold
harder and pay more. So this is a pullback-in-trend effect, and the obvious
implementation of "trade the trend" would have the sign backwards.

0.34R between the extremes, monotonic across the top three deciles, holding
inside every interval and strengthening as the timeframe slows: +0.081 on 1m
against +0.245 on 15m. For scale, every direction gate measured the same day
spread 0.09 to 0.15 across its whole range, and all three were switched off.

## The measure

    efficiency = |net displacement| / sum of absolute steps

over the last `WINDOW` level prices seen on one feed and interval. One means
every step went the same way; zero means they cancelled. It is the standard
efficiency ratio, and it is the first of the momentum detectors
[todo](../../docs/todo.md) 0m says are missing.

**Only prior levels count.** The level currently being decided is never in its
own window - that is what keeps this a prediction rather than a restatement,
and it is the trap `push_vol` fell into, where a quantity signed by the outcome
was scored against the outcome.

## What is still a guess

`WINDOW` is twelve because twelve worked, not because anything was compared
against it. The efficiency ratio is one trend measure among several and was
picked first for being cheap to compute. And the measurement behind all of it
is a fixed stop-and-target rule over touch resolutions, not the trades the book
actually took.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .state import Restorable

#: How many prior level prices define the context.
WINDOW = 12
#: Below this many, no opinion is offered. Two points is one step, which is
#: trivially perfectly efficient and says nothing.
FEWEST = 3


@dataclass(slots=True)
class Trend(Restorable):
    """Efficiency of recent level prices on one feed and interval."""

    window: int = WINDOW
    seen: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))

    def observe(self, level: float) -> None:
        """Fold in a level. Call *after* reading, never before."""
        self.seen.append(float(level))

    @property
    def efficiency(self) -> float | None:
        """0 ranges, 1 trends, None when there is not enough to say."""
        if len(self.seen) < FEWEST:
            return None
        prices = list(self.seen)
        steps = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
        travelled = sum(abs(s) for s in steps)
        if travelled <= 0:
            return None
        return abs(sum(steps)) / travelled

    def scale(self, span: float) -> float:
        """A sizing multiplier from the trend context, centred on 1.

        `span` is how far either side of 1 the multiplier may reach, so 0.3
        gives 0.7x in the flattest chop and 1.3x in a clean trend. Bounded on
        purpose: the measured effect is 0.34R between extreme deciles, which
        justifies leaning, not doubling.

        Sizing rather than a gate uses the whole curve. The relationship is
        continuous and monotonic across the top deciles, so a threshold throws
        away the middle - and a gate that turns out to be wrong shows up as
        nothing happening, which is the failure this repository keeps finding
        late.

        No opinion means no adjustment: a feed without enough history sizes
        exactly as it did before this existed.
        """
        if span <= 0:
            return 1.0
        ratio = self.efficiency
        if ratio is None:
            return 1.0
        return 1.0 + span * (2.0 * ratio - 1.0)
