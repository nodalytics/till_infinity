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

from river import stats

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

#: Readings kept for the regime percentile. Roughly a day of 1m bars: long
#: enough that "high for this instrument" means something, short enough that it
#: still describes the market you are in rather than the one from last month.
REGIME_WINDOW = 1_500

#: Percentiles tracked. The pair brackets "normal", so a reading outside them is
#: outside what this instrument has recently been doing.
REGIME_LOW, REGIME_HIGH = 0.15, 0.85


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
    #: Rolling quantiles of the estimate itself. A number is not interpretable
    #: on its own — "25bps" says nothing without knowing what this instrument
    #: usually does — so the percentile is tracked alongside it.
    _low: stats.RollingQuantile = field(
        default_factory=lambda: stats.RollingQuantile(q=REGIME_LOW, window_size=REGIME_WINDOW)
    )
    _high: stats.RollingQuantile = field(
        default_factory=lambda: stats.RollingQuantile(q=REGIME_HIGH, window_size=REGIME_WINDOW)
    )
    _history: list[float] = field(default_factory=list)

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
        current = self.bps
        self._low.update(current)
        self._high.update(current)
        self._history.append(current)
        if len(self._history) > REGIME_WINDOW:
            del self._history[: len(self._history) - REGIME_WINDOW]
        return current

    @property
    def bps(self) -> float:
        return max(self._mean_abs, self.floor_bps)

    @property
    def warm(self) -> bool:
        return self._seen >= self.warmup

    @property
    def regime(self) -> float:
        """Where the current estimate sits in its own recent history, in [0, 1].

        This is the number that is actually interpretable. "Volatility is 25bps"
        says nothing without knowing what this instrument usually does; "at the
        92nd percentile of the last day" says it immediately, and says it in a
        form gold and BTC can share.

        Returns 0.5 before there is enough history to place anything.
        """
        if len(self._history) < self.warmup:
            return 0.5
        current = self.bps
        below = sum(1 for value in self._history if value < current)
        return below / len(self._history)

    @property
    def calm(self) -> bool:
        """Below what this instrument has recently been doing."""
        low = self._low.get()
        return bool(low) and self.bps < low

    @property
    def violent(self) -> bool:
        """Above it. The half of the band that usually matters."""
        high = self._high.get()
        return bool(high) and self.bps > high

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
