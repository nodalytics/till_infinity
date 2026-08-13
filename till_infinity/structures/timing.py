"""How long until price gets there.

A level three volatility units away is not "close" or "far" — it is a distance
a random walk has to cover, and asking how long that takes is a **first-passage
time** problem with a known answer. The input is a distance measured in
volatility units, which is precisely what `distance_vol` already produces.

## The arithmetic

For a driftless walk with per-bar volatility sigma, the time to first touch a
point `n` volatility units away has a Lévy distribution, and inverting its
cumulative form gives the quantiles directly:

    bars(q)  =  ( n / Phi^-1(1 - q/2) )^2

and the reflection principle gives the other direction:

    P(touched within N bars)  =  2 * ( 1 - Phi( n / sqrt(N) ) )

Both are exact for Brownian motion and need nothing beyond the normal
quantile function.

## The quadratic is the point

Time goes as the **square** of distance. Twice as far is four times as long,
not twice — which is the single most useful thing this module says, because it
is not what intuition offers. A level 1v away is typically touched within a
couple of bars; one 5v away takes fifty.

## What "the mean" would be, and why it is not here

The expected first-passage time of a driftless walk is **infinite**. The
distribution has a tail heavy enough that the mean does not converge, so any
"average time to reach" is an artefact of where the sample was truncated.
Quantiles are reported instead: a median, and a slow case. That is not
pedantry — an average here would be a number that gets larger the longer you
collect data for.

## What this is not

Markets are not Brownian. Volatility clusters, moves have fat tails, and price
trends. Treat these as **the null model**: what the distance alone implies,
before anything about the market's direction is taken into account. A level
that keeps getting reached far sooner than this says something; the estimate is
the baseline that makes "sooner" mean anything.

Drift is deliberately excluded. Estimating it from recent data is noisy enough
that a wrong sign would make the answer worse than the null — and the honest
version of "price is heading there" is the directional inference, which is
already a separate answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from .levels import SECONDS, Level, Side
from .volatility import Volatility

_NORMAL = NormalDist()

#: Distances below this are already there. Without a floor the estimate goes to
#: zero bars, which is true and useless.
MIN_DISTANCE_VOL = 0.05

#: Anything beyond this many bars is "not soon" and the precision is spurious.
MAX_BARS = 10_000.0


def bars_to_reach(distance_vol: float, quantile: float = 0.5) -> float:
    """Bars until a walk first touches something `distance_vol` away.

    `quantile` 0.5 is the median — half the time it is reached sooner. 0.9 is
    the slow case. There is no mean: the distribution's is infinite.
    """
    n = abs(distance_vol)
    if n < MIN_DISTANCE_VOL:
        return 0.0
    quantile = min(max(quantile, 1e-6), 1.0 - 1e-6)
    # erfc^-1 expressed through the normal quantile, so this needs no scipy.
    z = _NORMAL.inv_cdf(1.0 - quantile / 2.0)
    if z <= 0:
        return MAX_BARS
    return min((n / z) ** 2, MAX_BARS)


def probability_within(distance_vol: float, bars: float) -> float:
    """Chance of touching something `distance_vol` away within `bars`.

    The reflection principle: a walk that would end beyond the point must have
    touched it, and so must half of those that end short of it.
    """
    n = abs(distance_vol)
    if n < MIN_DISTANCE_VOL:
        return 1.0
    if bars <= 0:
        return 0.0
    return min(1.0, 2.0 * (1.0 - _NORMAL.cdf(n / math.sqrt(bars))))


def _humanise(seconds: float) -> str:
    """A duration a person reads without converting anything."""
    if seconds <= 0:
        return "now"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.0f}m"
    hours = minutes / 60.0
    if hours < 48:
        return f"{hours:.1f}h"
    days = hours / 24.0
    if days < 60:
        return f"{days:.1f}d"
    return f"{days / 7:.0f}w"


@dataclass(frozen=True, slots=True)
class Approach:
    """When price is likely to reach a level, and how sure that is."""

    distance_vol: float
    interval: str
    #: Bars, at the quantiles that mean something.
    median_bars: float
    slow_bars: float
    #: The same in seconds, using this timeframe's bar length.
    median_seconds: float
    slow_seconds: float
    #: Chance of getting there within one window of this timeframe.
    within_window: float
    bars_in_window: float

    @property
    def median(self) -> str:
        return _humanise(self.median_seconds)

    @property
    def capped(self) -> bool:
        """True when the slow case hit the bound rather than being estimated."""
        return self.slow_bars >= MAX_BARS

    @property
    def slow(self) -> str:
        """The unlucky case, or "beyond" when it ran past the horizon.

        Printing a precise duration for a clamped value would read as an
        estimate when it is a ceiling — and "34.7d" looks like a finding while
        "beyond" is what is actually known.
        """
        return "beyond" if self.capped else _humanise(self.slow_seconds)

    @property
    def soon(self) -> bool:
        """Better than even odds inside the window. The only binary worth having."""
        return self.within_window >= 0.5

    def to_dict(self) -> dict:
        return {
            "distance_vol": round(self.distance_vol, 3),
            "interval": self.interval,
            "median_bars": round(self.median_bars, 1),
            "median_seconds": round(self.median_seconds),
            "median": self.median,
            "slow_bars": round(self.slow_bars, 1),
            "slow": self.slow,
            "slow_capped": self.capped,
            "within_window": round(self.within_window, 3),
            "bars_in_window": self.bars_in_window,
            "soon": self.soon,
        }

    def __str__(self) -> str:
        return (
            f"{abs(self.distance_vol):.1f}v away, typically {self.median} "
            f"(slow case {self.slow}), {self.within_window:.0%} within "
            f"{int(self.bars_in_window)} bars"
        )


def estimate(
    distance_vol: float,
    interval: str,
    *,
    slow_quantile: float = 0.9,
    window_bars: float = 24.0,
) -> Approach:
    """Turn a distance into a time, on one timeframe's clock.

    The same distance is minutes on 5m and months on 1w, so the timeframe is
    not decoration — it is what converts bars into anything anyone can use.
    """
    seconds = SECONDS.get(interval, 3_600.0)
    median = bars_to_reach(distance_vol, 0.5)
    slow = bars_to_reach(distance_vol, slow_quantile)
    return Approach(
        distance_vol=distance_vol,
        interval=interval,
        median_bars=median,
        slow_bars=slow,
        median_seconds=median * seconds,
        slow_seconds=slow * seconds,
        within_window=probability_within(distance_vol, window_bars),
        bars_in_window=window_bars,
    )


def to_level(level: Level, price: float, vol: Volatility, **kwargs) -> Approach:
    """When price is likely to reach this level from where it is now."""
    return estimate(level.distance_vol(price, vol), level.interval, **kwargs)


def next_levels(
    levels: list[Level], price: float, vol: Volatility, *, limit: int = 5, **kwargs
) -> list[tuple[Level, Approach, Side]]:
    """Levels ahead of price, soonest first, with the side each would be met from.

    Sorted by time rather than distance, which is not the same ordering: a
    level on a fast timeframe can be reached long before a nearer one measured
    on a slow one, because the clock differs by more than the distance does.
    """
    found = []
    for level in levels:
        approach = to_level(level, price, vol, **kwargs)
        # The side price would *arrive* from is the side it is on now.
        found.append((level, approach, level.side_of(price)))
    found.sort(key=lambda row: row[1].median_seconds)
    return found[:limit]
