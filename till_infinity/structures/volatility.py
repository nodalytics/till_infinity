"""How much this instrument moves, right now.

Everything about levels is measured in volatility units rather than price
units, and that is not a stylistic choice. A level held to within 5bps is
remarkable in a calm hour and meaningless in a violent one; a zone 20bps wide
is a hairline on gold in a crisis and a canyon on EURUSD overnight. Fixed
thresholds encode one market regime and quietly stop describing the next.

So this module is small and load-bearing. It produces one number per
instrument — the typical size of a move — and the rest of the package divides
by it.

Exponentially weighted rather than a rolling window, because a window has an
edge: a violent bar leaves the average abruptly N bars later, and a level's
zone would jump for no reason anyone could point at. An EW estimator forgets
smoothly, which is what "recent" actually means.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Bars of history before the estimate is trusted. Below this the variance of
#: the variance is larger than anything it would be used to decide.
WARMUP = 20

#: Half-life in bars. About an hour of 1m bars: long enough to survive a single
#: spike, short enough to notice a regime that has actually changed.
HALF_LIFE = 60.0

#: A floor, in basis points. Without one, an instrument that has not moved for
#: an hour gets a near-zero volatility and every subsequent tick looks like a
#: hundred-sigma event — division by something approaching zero.
MIN_VOL_BPS = 0.05


def _alpha(half_life: float) -> float:
    return 1.0 - math.exp(math.log(0.5) / max(half_life, 1.0))


@dataclass(slots=True)
class Volatility:
    """Exponentially weighted volatility of returns, in basis points.

    Tracks the mean absolute return rather than the standard deviation: the
    question asked of it is "how big is a normal move", and for fat-tailed
    financial returns the mean absolute deviation answers that more stably
    than a variance a single outlier can dominate.
    """

    half_life: float = HALF_LIFE
    floor_bps: float = MIN_VOL_BPS
    warmup: int = WARMUP
    _mean_abs: float = 0.0
    _last: float = 0.0
    _seen: int = 0

    def update(self, price: float) -> float:
        """Take one price, return the current volatility estimate in bps."""
        if price <= 0:
            return self.bps
        if not self._last:
            self._last = price
            return self.bps
        move = abs(price - self._last) / self._last * 10_000
        self._last = price
        self._seen += 1
        alpha = _alpha(self.half_life)
        self._mean_abs = (
            move if self._seen == 1 else self._mean_abs + alpha * (move - self._mean_abs)
        )
        return self.bps

    @property
    def bps(self) -> float:
        return max(self._mean_abs, self.floor_bps)

    @property
    def warm(self) -> bool:
        return self._seen >= self.warmup

    def units(self, distance_bps: float) -> float:
        """Express a distance in volatility units. The project's common currency."""
        return distance_bps / self.bps

    def price_units(self, price: float, multiple: float) -> float:
        """`multiple` volatility units, as a price distance at `price`."""
        return price * (self.bps * multiple) / 10_000


@dataclass(slots=True)
class Book:
    """One volatility estimate per instrument."""

    half_life: float = HALF_LIFE
    _by_feed: dict[str, Volatility] = field(default_factory=dict)

    def of(self, feed: str) -> Volatility:
        found = self._by_feed.get(feed)
        if found is None:
            found = self._by_feed[feed] = Volatility(half_life=self.half_life)
        return found

    def update(self, feed: str, price: float) -> float:
        return self.of(feed).update(price)

    def feeds(self) -> list[str]:
        return sorted(self._by_feed)
