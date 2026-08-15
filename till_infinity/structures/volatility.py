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

from .state import Restorable

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

#: Observations before the tick estimate is trusted. The minimum of three
#: samples is not a minimum.
TICK_WARMUP = 30

#: Where in the distribution of price changes the grid step is read off.
#:
#: Not the minimum, which is what this used to be. Both give the same answer on
#: clean data — identical on all eight instruments tested — but the minimum is
#: a one-observation estimator and behaves like one: a single spurious print a
#: seventh the size of a real tick collapsed it on **every** instrument, 0.01
#: to 0.0014, and that number widens a zone. The first percentile did not move
#: on any of them.
#:
#: An approximate GCD was tried too, on the grounds that the tick divides every
#: change. It matched on seven instruments, went degenerate on btc (0.000064,
#: which trivially divides everything) and collapsed under the same outlier.
TICK_QUANTILE = 0.01

#: Changes remembered for that quantile. Enough to place a percentile, few
#: enough to follow a re-tiering rather than the year.
TICK_WINDOW = 500

#: Distinct multiples of the smallest change that must be seen before the
#: estimate is believed to be a grid step at all.
#:
#: This is the discriminator, and the obvious one does not work. "The smallest
#: move must be small against a typical move" sounds right and rejects exactly
#: the instruments that need this most: on ADA the tick genuinely *is* most of
#: a typical move, which is the whole problem, so that test throws away the
#: worst case as if it were the degenerate one.
#:
#: What separates them is the spread of multiples. Price on a real grid moves
#: one step, then two, then five — many distinct multiples of the same base.
#: A series that only ever moves by one identical amount has not resolved a
#: grid at all; it has jumped, and its jump is not a tick.
TICK_MULTIPLES = 3

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
class Volatility(Restorable):
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
    #: The smallest non-zero price change seen — the venue's tick, measured
    #: rather than configured. See `tick`.
    _tick: float = 0.0
    #: Distinct multiples of `_tick` observed, which is what tells a grid from
    #: a series that happens to move in equal jumps. Bounded: past a handful
    #: the answer does not change.
    _steps: set[int] = field(default_factory=set)
    #: The estimate itself: a low quantile of the changes rather than their
    #: minimum, so one bad print cannot move it. See `TICK_QUANTILE`.
    _grid: stats.RollingQuantile = field(
        default_factory=lambda: stats.RollingQuantile(q=TICK_QUANTILE, window_size=TICK_WINDOW)
    )

    # `__setstate__` comes from `Restorable`, which fills in fields a saved
    # state predates. This class is why that exists: `_tick`, `_steps` and
    # `_grid` were added, the restore raised on the first quote, and the
    # throw landed inside the structures consumer — so the container stayed
    # healthy and simply stopped producing for four hours. See state.py.

    @property
    def tick(self) -> float:
        """The smallest price change this instrument has been seen to make.

        Every price on a venue sits on a grid and every change is a multiple of
        its step, so the smallest non-zero change observed *is* the step — once
        enough have gone past for the smallest to be a single step rather than
        the smallest jump that happened to occur. Measured rather than
        configured, because the tick table belongs to the venue and changes
        without notice, and because `structures` has no other route to it:
        `prices` sees the quotes and does not pass this on.

        **Zero unless the series has actually demonstrated a grid**, and the
        two guards matter more than the estimate.

        A series that only ever moves by one identical amount says nothing
        about the step: "the tick is that size" and "the tick is tiny and price
        is jumping" fit the data equally well, and taking the first would widen
        every zone on the instrument by that jump. So the estimate is withheld
        until price has been seen to move by several *different* multiples of
        it — one step, then two, then five — which is what a grid being
        resolved looks like and what a uniform jump never produces. See
        `TICK_MULTIPLES`, and note that the tempting test — "the tick should be
        small against a typical move" — rejects ADA, the instrument this exists
        for.

        It is also withheld until `TICK_WARMUP` observations, because the
        minimum of three samples is not a minimum.

        **The estimate is only ever an upper bound.** It is the smallest change
        that has *happened*, not the smallest that is possible, so an
        instrument whose prints are all several steps apart reads as coarser
        than it is. The error is always in that direction and it shrinks with
        data, never growing — but a consumer should bound what it does with the
        number rather than trust it early. `Level.zone` clamps it at
        `MAX_ZONE_VOL` for exactly this reason.

        Both failures return zero, so anything built on this falls back rather
        than inventing a number, and the estimate can only shrink with more
        data — biasing it towards the old behaviour rather than towards a
        spuriously wide band. That is the safe direction for a value whose job
        is to widen one.
        """
        if not self._tick or self._seen < TICK_WARMUP:
            return 0.0
        if len(self._steps) < TICK_MULTIPLES:
            return 0.0
        # The minimum decides *whether* there is a grid; the quantile decides
        # how wide it is. Separating them is what makes one bad print harmless:
        # it drags the minimum down, which only loosens the guard, while the
        # quantile it would have to move is defended by every other change.
        return float(self._grid.get() or self._tick)

    def update(self, price: float) -> float:
        """Take one price, return the current volatility estimate in bps."""
        if price <= 0:
            return self.bps
        if not self._last:
            self._last = price
            return self.bps
        step = abs(price - self._last)
        if step:
            if not self._tick or step < self._tick:
                # A smaller step rewrites the base, so what was counted as a
                # multiple of the old one says nothing about the new.
                self._tick = step
                self._steps = {1}
            elif len(self._steps) < 16:
                self._steps.add(round(step / self._tick))
            self._grid.update(step)
        move = step / self._last * 10_000
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
class Book(Restorable):
    """One volatility estimate per instrument **and timeframe**.

    Per timeframe, not merely per instrument, and that distinction is
    load-bearing. A typical 4h move on gold is tens of times a typical 5m move,
    so a single estimate — in practice dominated by whichever series updates
    most often — makes every threshold expressed in volatility units wrong for
    every timeframe but one.

    Concretely: with one estimate, gold's clustering tolerance came out at about
    $0.86 while the 4h window spanned seventy days over a $574 range. Swings at
    that scale essentially never clustered, so the higher timeframes produced
    almost no levels at all.

    An empty `interval` is the instrument's tick-level estimate, updated from
    quotes. That is the right denominator for cross-timeframe comparisons: it
    is the only one every level can be measured against on the same footing.
    """

    half_life: float = HALF_LIFE
    _by_key: dict[tuple[str, str], Volatility] = field(default_factory=dict)

    # `__setstate__` from `Restorable` too, and it matters more here: this
    # holds one estimate per instrument *and* timeframe, so one missing
    # field takes out every one of them at once.

    def of(self, feed: str, interval: str = "") -> Volatility:
        key = (feed, interval)
        found = self._by_key.get(key)
        if found is None:
            found = self._by_key[key] = Volatility(half_life=self.half_life)
        return found

    def update(self, feed: str, price: float, interval: str = "") -> float:
        return self.of(feed, interval).update(price)

    def feeds(self) -> list[str]:
        return sorted({feed for feed, _ in self._by_key})

    def intervals(self, feed: str) -> list[str]:
        return sorted(interval for this, interval in self._by_key if this == feed and interval)
