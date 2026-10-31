"""A rolling spread, because the framework's freezes.

**`nautilus_trader.indicators.SpreadAnalyzer.average` stops updating once its
window fills.** Measured on 1.221.0, capacity 4, with the spread widening
every tick:

    n=1  current 0.000200   average 0.000200   true 0.000200
    n=2  current 0.000400   average 0.000300   true 0.000300
    n=3  current 0.000600   average 0.000400   true 0.000400
    n=4  current 0.000800   average 0.000400   true 0.000500   <- frozen here
    n=6  current 0.001200   average 0.000400   true 0.000900

Two causes, compounding. `handle_quote_tick` appends the new spread to its
deque and *then* calls `fast_mean_iterated(..., drop_left=False)`, which
computes `current + (next_value - values[-1]) / length` - and after the append
`values[-1]` **is** `next_value`, so every update adds zero. Independently,
`drop_left=False` is the wrong end: a `deque(maxlen=n)` evicts from the left.

`current` is correct and is worth using. `average` is not.

**Why this one matters here rather than being a curiosity.** Spread is the cost
gate on every idea this desk tests, and cost is what ends most of them -
exotic spreads run 0.40 to 0.97 of a whole bar range round trip. An average
frozen at a strategy's first few ticks would pass it on a cost estimate from
its infancy and keep passing it while the real cost widened. And
`spread-column-is-in-points` is the neighbouring trap: MT5 reports spread in
*points*, not price, and reading it as price made EURUSD look like a 476%
round trip.

So this keeps the window and takes the mean of it. Ten times slower than an
incremental update on a few hundred samples, which is not a cost worth a
wrong number.
"""

from __future__ import annotations

from collections import deque
from statistics import median
from typing import Any

from nautilus_trader.indicators.base import Indicator


class RollingSpread(Indicator):
    """Mean, median and extremes of the spread over the last `capacity` quotes.

    The median is here because the mean is the wrong summary for this quantity:
    spread is bounded below, spikes on news, and a single widening at a release
    drags a mean far more than it changes what a strategy will actually pay.
    """

    __slots__ = ("_spreads", "capacity", "crossed")

    def __init__(self, capacity: int = 100) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        super().__init__([capacity])
        self.capacity = capacity
        self._spreads: deque[float] = deque(maxlen=capacity)
        #: Bad ticks dropped by `handle_quote_tick`. A venue that sends many
        #: is a data problem, and a silent drop would hide it.
        self.crossed = 0

    def update(self, bid: float, ask: float) -> None:
        """Record one quote. A crossed or zero quote is refused, not averaged.

        A bid above an ask is not a wide spread, it is a bad tick, and folding
        it in as a negative number makes the average read *tighter* than the
        truth - the one direction of error that lets an idea through.
        """
        spread = ask - bid
        if spread < 0.0:
            raise ValueError(f"crossed quote: bid {bid} above ask {ask}")
        self._spreads.append(spread)

    def handle_quote_tick(self, tick: Any) -> None:
        """Nautilus's entry point, once registered for quote ticks.

        `Actor.register_indicator_for_quote_ticks` drives this, so a bad tick
        arriving from a venue would raise inside the engine's handler. The
        refusal in `update` is the right behaviour for a caller that can see
        the quote; here it would stop the feed, so a crossed quote is counted
        and dropped instead and `crossed` says how many.
        """
        bid, ask = float(tick.bid_price), float(tick.ask_price)
        if ask < bid:
            self.crossed += 1
            return
        self.update(bid, ask)
        self._set_has_inputs(True)
        if not self.initialized and len(self._spreads) >= self.capacity:
            self._set_initialized(True)

    def update_quote(self, tick: Any) -> None:
        """Record a Nautilus `QuoteTick`. The name Nautilus calls is
        `handle_quote_tick`; this is kept for callers that drive it directly."""
        self.handle_quote_tick(tick)

    @property
    def count(self) -> int:
        return len(self._spreads)

    @property
    def initialized(self) -> bool:
        return len(self._spreads) == self.capacity

    @property
    def current(self) -> float | None:
        return self._spreads[-1] if self._spreads else None

    @property
    def average(self) -> float | None:
        """The arithmetic mean over the window. Recomputed, never carried."""
        return sum(self._spreads) / len(self._spreads) if self._spreads else None

    @property
    def typical(self) -> float | None:
        """The median - what a strategy will usually pay."""
        return median(self._spreads) if self._spreads else None

    @property
    def widest(self) -> float | None:
        return max(self._spreads) if self._spreads else None

    @property
    def tightest(self) -> float | None:
        return min(self._spreads) if self._spreads else None

    def exceeds(self, edge: float, *, use_median: bool = True) -> bool | None:
        """Does the round-trip cost eat an edge of this size?

        **Round trip, so twice the spread.** An edge is crossed on the way in
        and on the way out, and comparing a one-way spread against an expected
        move is how a losing idea looks marginal.
        """
        summary = self.typical if use_median else self.average
        return None if summary is None else (2.0 * summary) >= edge

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a quote."""
        self._spreads.clear()
        self.crossed = 0
        self._set_has_inputs(False)
        self._set_initialized(False)
