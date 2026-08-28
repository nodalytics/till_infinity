"""How long a touch on this feed and interval takes to resolve.

`stop_hold_scaling` widens every stop by the square root of the hold, because
`vol_bps` is one bar of the entry interval and a trade held for many wanders
further than one. The hold it scales by is the strategy's **configured**
constant - 1800 seconds for the scalpers, 120 for `snap`. The trade does not
care what was configured.

Measured over 38,244 resolutions, how long a touch actually takes runs from 4
seconds at p25 to 651 at p90 - a **163x** spread - so one constant is right for
a slice of trades and wrong for the rest. And it persists: lag-1
autocorrelation **+0.269** on the log, positive in 86% of series.

Those are the same two properties that justify five volatility estimators, on a
quantity that had none. Direction, for contrast, varies just as much and does
not persist at all (-0.013), which is why there is no direction estimator here
and should not be.

## Why the log, and why an exponential average

**The log**, because the distribution is long-tailed enough that one
3,500-second touch dominates any mean taken on the raw seconds - and because
persistence is stronger there (+0.269 against +0.173), which is the shape the
estimator has to exploit. The estimate is a geometric mean, which for a
long-tailed positive quantity is the honest centre.

**Exponential rather than a window**, because the persistence measured is
lag-1: what happened recently carries the information, and a window either
throws it away at the boundary or dilutes it with history that has stopped
being relevant. One number of state, no boundary.

## What it does not do

It offers **no opinion** until it has seen `FEWEST` resolutions, rather than
extrapolating from two. A caller that gets `None` should use whatever it used
before this existed - the point is to improve on a constant where there is
evidence, not to replace it with a guess that has less behind it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .state import Restorable

#: Observations before an estimate is offered at all.
FEWEST = 8
#: How many observations it takes for old evidence to lose half its weight.
#: Twenty is short enough to track a change in regime and long enough that a
#: single unusual touch does not move the estimate far.
HALF_LIFE = 20.0
#: Sanity bounds in seconds. A resolution outside these is not a hold, it is a
#: fault - and the push estimator taught this repository what an unbounded
#: input does downstream.
QUICKEST = 0.5
SLOWEST = 24 * 3_600.0


@dataclass(slots=True)
class Holds(Restorable):
    """The expected resolution time for one feed and interval."""

    half_life: float = HALF_LIFE
    #: Exponentially weighted mean of log(seconds).
    log_mean: float = 0.0
    seen: int = 0

    def observe(self, seconds: float) -> None:
        """Fold in one resolution. Out-of-range values are ignored, not clamped.

        Ignored rather than clamped because a clamp would quietly fold a fault
        into the estimate at the boundary value, which is how a broken number
        becomes a slightly wrong one that nobody notices.
        """
        if not QUICKEST <= seconds <= SLOWEST:
            return
        value = math.log(seconds)
        if self.seen == 0:
            self.log_mean = value
        else:
            alpha = 1.0 - 0.5 ** (1.0 / max(1.0, self.half_life))
            self.log_mean += alpha * (value - self.log_mean)
        self.seen += 1

    @property
    def expected(self) -> float | None:
        """Expected seconds to resolve, or None while there is not enough."""
        if self.seen < FEWEST:
            return None
        return math.exp(self.log_mean)

    def to_dict(self) -> dict:
        return {
            "expected": round(self.expected or 0.0, 2),
            "seen": self.seen,
            "log_mean": round(self.log_mean, 6),
        }


@dataclass(slots=True)
class Book(Restorable):
    """Every feed and interval, with a pooled estimate to fall back on.

    A feed nobody has seen resolve yet is the common case after a restart and
    on a newly traded instrument. Pooling across everything is a poor estimate
    and a much better one than a constant chosen by hand, so it is offered
    where there is nothing better and marked as what it is.
    """

    by_key: dict[tuple[str, str], Holds] = field(default_factory=dict)
    pooled: Holds = field(default_factory=Holds)

    def observe(self, feed: str, interval: str, seconds: float) -> None:
        self.by_key.setdefault((feed, interval), Holds()).observe(seconds)
        self.pooled.observe(seconds)

    def expected(self, feed: str, interval: str) -> float | None:
        """This series' own estimate, else the pooled one, else None."""
        own = self.by_key.get((feed, interval))
        if own is not None:
            got = own.expected
            if got is not None:
                return got
        return self.pooled.expected

    def ready(self) -> int:
        """How many series can answer for themselves."""
        return sum(1 for h in self.by_key.values() if h.expected is not None)
