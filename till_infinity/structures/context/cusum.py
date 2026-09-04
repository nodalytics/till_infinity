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

from ..state import Restorable

#: Volatility units of net directional progress that constitute an event.
#:
#: Kept as the ceiling rather than the working value. Measured over 59,982
#: resolutions, a 2.0v threshold is **silent through 47.5% of all moves** - the
#: median realised push is 2.07v, so it confirms after essentially the whole
#: move has happened, which is useless for timing an entry. See
#: `adaptive_threshold`.
THRESHOLD = 2.0

#: The share of a typical move the filter should fire inside. A filter meant to
#: time an entry has to speak partway through, not at the end.
SHARE = 0.35

#: The hard floor, below which this is reading noise rather than momentum. Only
#: 1.9% of measured moves are smaller than this, so the floor costs almost
#: nothing and stops a quiet instrument from firing on every tick.
FLOOR = 0.5


def adaptive_threshold(
    typical_push: float, *, share: float = SHARE, floor: float = FLOOR, ceiling: float = THRESHOLD
) -> float:
    """A threshold sized to the moves this instrument actually makes.

    Volatility units already normalise for how much an instrument moves per
    bar, and that turns out not to be enough: the *push* an instrument makes
    once it starts moving varies on top of it, from 1.66v on eurusd to 2.75v
    on brent - a 1.7x spread that a single number cannot serve. A threshold
    right for one is late for the other.

    So the threshold is a share of the typical push, floored and capped. The
    floor is what keeps this honest when the estimate is missing, cold, or
    absurd: an unknown push returns the floor rather than zero, because a
    threshold of zero makes every tick an event.
    """
    if typical_push <= 0:
        return floor
    return max(floor, min(ceiling, share * typical_push))


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


#: The timeframes an ensemble reads, all below 1h. Above that the swing's own
#: context timeframes already speak, and they answer a different question:
#: whether the level is real, not whether it is being rejected right now.
SUB_HOUR: tuple[str, ...] = ("1m", "3m", "5m", "15m", "30m")

#: Seconds per interval, kept here rather than imported so this module stays
#: free of the level machinery.
CADENCE: dict[str, float] = {
    "1m": 60.0,
    "3m": 180.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1_800.0,
}


@dataclass
class Ensemble(Restorable):
    """One CUSUM per sub-hour timeframe, read together.

    A single tick-driven filter answers "is there momentum" at one speed, and
    which speed it happens to be is an accident of how often quotes arrive. A
    burst on a quiet instrument and a drift on a busy one produce the same
    accumulation for different reasons.

    Several filters, each sampled at its own cadence, separate those. Momentum
    that shows on 1m and nowhere else is noise; momentum that shows on 1m, 5m
    and 15m at once is the market doing one thing at several resolutions. What
    the ensemble adds over any single member is **agreement**, which is the
    part a single filter cannot report however it is tuned.

    Members are sampled rather than resampled: a tick is handed to a member
    only once its interval has elapsed since that member last saw one. That
    makes each member a filter over that timeframe's closes without needing
    bars, which matters because this is fed from the quote stream.
    """

    intervals: tuple[str, ...] = SUB_HOUR
    threshold: float = THRESHOLD
    members: dict[str, Cusum] = field(default_factory=dict)
    seen_at: dict[str, float] = field(default_factory=dict)

    def push(self, price: float, unit: float, when: float = 0.0) -> None:
        """Feed one price to whichever members are due for it."""
        for interval in self.intervals:
            every = CADENCE.get(interval, 0.0)
            if every <= 0:
                continue
            last = self.seen_at.get(interval)
            if last is not None and when - last < every:
                continue
            self.seen_at[interval] = when
            member = self.members.setdefault(interval, Cusum(threshold=self.threshold))
            # Applied on every push, not only at construction. The threshold
            # adapts as the instrument's typical push is re-estimated, and a
            # member built with the old one would keep it forever.
            member.threshold = self.threshold
            member.push(price, unit, when=when)

    @property
    def ready(self) -> int:
        """How many members have seen enough to have an opinion."""
        return sum(1 for m in self.members.values() if m.started)

    @property
    def pressure(self) -> float:
        """The members' mean accumulation, in volatility units.

        The mean rather than the sum, so the reading does not change scale when
        a member is added or is not yet warm - it stays comparable with the
        single-filter reading it replaces, and with `require_turn_vol`, which
        is calibrated in those units.
        """
        warm = [m.pressure for m in self.members.values() if m.started]
        return sum(warm) / len(warm) if warm else 0.0

    @staticmethod
    def _opinion(member: Cusum) -> int:
        """Which way one member is pointing: 1, -1, or 0 for no view.

        **The accumulator alone is not enough.** A CUSUM resets when it fires,
        so a member that has just confirmed a run reads a pressure of exactly
        zero - the strongest case it can report looks identical to a flat
        market. Falling back to the side of its last event is what keeps a
        confirmed run counted as a view rather than an abstention.
        """
        if member.pressure > 0:
            return 1
        if member.pressure < 0:
            return -1
        if member.events:
            return 1 if member.events[-1].side == "up" else -1
        return 0

    @property
    def agreement(self) -> float:
        """Signed share of warm members pointing the same way, -1 to 1.

        1.0 is every timeframe pushing up, -1.0 every one pushing down, and
        zero either a split or nothing moving. This is the reading a single
        filter cannot give, and the reason for the ensemble.

        Divided by every warm member, not only those with a view, so a
        timeframe that is genuinely flat dilutes the reading. That is the
        honest answer: not all of them agree.
        """
        warm = [m for m in self.members.values() if m.started]
        if not warm:
            return 0.0
        views = [self._opinion(m) for m in warm]
        return sum(views) / len(warm)
