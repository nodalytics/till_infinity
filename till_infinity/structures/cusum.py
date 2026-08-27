"""Momentum as an accumulating sum rather than a fixed lookback.

`speeds.py` measures recent edge over windows - so many bars back, averaged.
Every fixed window makes the same two mistakes in opposite directions: it
dilutes a move that happened inside it with the bars either side that did not
participate, and it misses a move that spans its boundary entirely. A run of
twelve small pushes in one direction and a single large push are the same
number to a mean, and are not the same thing.

A cumulative sum has no window. It carries a running total of how far price has
gone in each direction, and reports the moment that total exceeds a threshold -
so a slow accumulation and a fast one both register, at the point they earn it,
without anybody choosing a lookback that suits one and not the other.

## The reset is what makes it a filter rather than a running total

A plain `cumsum` of returns is just price again, and drifts with it. The
version here is the **symmetric CUSUM filter**: two accumulators, one for
upward deviation and one for downward, each floored at zero, and both reset to
zero whenever either fires. That floor is the whole mechanism. It means the up
accumulator cannot be paid down by a drift lower - it can only be held at zero -
so what it measures is *consecutive net progress upward since the last event*,
which is the thing "momentum" is usually reaching for.

Without the reset it would report every bar after the first event. With it, one
move produces one signal, and the next signal requires the market to do the
work again.

## Volatility units, again

The threshold is in volatility units, for the same reason everything else here
is: a fixed price threshold makes every sol bar an event and almost no eurgbp
bar one, which describes the instruments rather than the market. At
`THRESHOLD` volatility units the filter fires when net directional progress
exceeds a few ordinary bars' worth of movement.

## What it is not

It is not a forecast, and the direction it reports is the direction that just
happened. Whether that persists is exactly the question `momentum-scalp` exists
to ask and this module does not answer - it only makes the input to that
question something better than an average over a window somebody guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .state import Restorable

#: Volatility units of net directional progress that constitute an event.
THRESHOLD = 2.0


@dataclass(slots=True)
class Event(Restorable):
    """One threshold crossing."""

    index: int
    when: float
    price: float
    #: "up" or "down" - which accumulator fired.
    side: str
    #: How far the accumulator had run when it fired, in volatility units.
    run_vol: float

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "when": self.when,
            "price": round(self.price, 8),
            "side": self.side,
            "run_vol": round(self.run_vol, 4),
        }


@dataclass(slots=True)
class Cusum(Restorable):
    """A symmetric CUSUM filter over a price series.

    Stateful across calls, so it can be fed a stream one price at a time and
    keep its accumulators - which is the point of it over a windowed measure.
    """

    threshold: float = THRESHOLD
    up: float = 0.0
    down: float = 0.0
    last: float = 0.0
    started: bool = False
    events: list[Event] = field(default_factory=list)

    def reset(self) -> None:
        self.up = 0.0
        self.down = 0.0

    def push(self, price: float, unit: float, when: float = 0.0, index: int = 0) -> Event | None:
        """Feed one price. Returns an Event if this one crossed the threshold.

        `unit` is one volatility unit in price, and is taken per call rather
        than stored, because volatility moves and a filter calibrated to last
        week's is measuring the wrong thing this week.
        """
        if not self.started:
            self.last, self.started = price, True
            return None
        if unit <= 0:
            self.last = price
            return None

        change = (price - self.last) / unit
        self.last = price
        # Floored at zero, so an accumulator can be held down by movement the
        # other way but never driven negative. That is what makes this
        # "progress since the last event" rather than a running total of price.
        self.up = max(0.0, self.up + change)
        self.down = min(0.0, self.down + change)

        if self.up >= self.threshold:
            run = self.up
            self.reset()
            return self._record(index, when, price, "up", run)
        if -self.down >= self.threshold:
            run = -self.down
            self.reset()
            return self._record(index, when, price, "down", run)
        return None

    def _record(self, index: int, when: float, price: float, side: str, run: float) -> Event:
        event = Event(index=index, when=when, price=price, side=side, run_vol=run)
        self.events.append(event)
        return event

    def feed(self, times: list[float], prices: list[float], unit: float) -> list[Event]:
        """Run the whole series through. Convenience over `push`."""
        out = []
        for i, price in enumerate(prices):
            when = times[i] if i < len(times) else 0.0
            got = self.push(price, unit, when=when, index=i)
            if got is not None:
                out.append(got)
        return out

    @property
    def pressure(self) -> float:
        """Current net accumulation, in volatility units. Positive is upward.

        The reading *between* events, for anything that wants a continuous
        measure rather than a trigger - how close the market is to having done
        enough in one direction to count.
        """
        return self.up + self.down
