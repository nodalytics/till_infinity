"""Where a violent move started, which is a different question from where it went.

Levels here are built from where price *turned* - swing highs and lows, run
boundaries, prices touched repeatedly. That records where the market changed
its mind, and it is silent about how hard. A high that price drifted away from
and a high that price fell 1% away from in four bars are the same point to
`pips` and are not the same thing to whoever sold at it: the second says a
large resting interest was there and was not fully filled, and price returning
to it meets the remainder.

This module finds those. An **origin** is the price a volatile move began
from - the last extreme before the impulse, not the extreme the impulse
reached. Ask "the market dropped 1%, where did the drop start", and the answer
is a price that has not been traded through since; the drop *is* the evidence
that it was not.

## Why volatility units and not percent

The intuition is naturally stated in percent - "a 1% drop" - and percent is the
wrong unit to implement it in. One percent of gold on a quiet afternoon is an
event; one percent of a crypto pair before the open is a normal bar. The same
threshold would make every sol level an origin and almost no eurgbp level one,
which is a statement about the instruments rather than about the market. So the
size is measured in volatility units, `MOVE_VOL`, and a 1% move qualifies
exactly where 1% is genuinely violent.

## An origin is a zone, and it wears out

Two things follow from what an origin is supposed to represent.

It is a **zone**, not a price: the resting interest that launched the move sat
across a range, so the origin spans from the extreme to where the impulse
became decisive, and price entering that band has reached it.

It is **consumed by being revisited**. The claim is unfilled interest; each
return trades some of it away. A fresh origin and one price has already worked
through twice are not equally interesting, and `revisits` is what separates
them - kept rather than used to expire the origin, because how fast they wear
out is a measurement nobody here has made yet.

## The exit is the same question backwards

If a buy is worth taking at the origin of a *drop*, the natural target is the
origin of the *rally* above it - the next price where a violent move began in
the other direction, and therefore where the interest that stopped the last
advance is still sitting. `opposing` exists for that, and it means a target is
drawn from the same evidence as the entry rather than from a fixed multiple.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .state import Restorable

#: How large a move must be, in volatility units, for its start to count as an
#: origin. Three is deliberately well beyond an ordinary bar - the point is to
#: catch displacement, not movement.
MOVE_VOL = 3.0
#: How many bars the move may take. A drop that takes fifty bars is a trend and
#: its "origin" is wherever you started looking; the claim being made here is
#: about a move fast enough that resting interest did not get refilled.
MOVE_BARS = 6
#: How far either side of the origin price the zone reaches, in volatility
#: units, when the impulse gives nothing better to measure from.
ZONE_VOL = 0.5


@dataclass(slots=True)
class Origin(Restorable):
    """A price a violent move began from."""

    price: float
    #: The band price has to enter to have reached this. Ordered low, high.
    low: float
    high: float
    #: "down" if a drop started here - so it sits above price and is
    #: resistance - and "up" if a rally did.
    launched: str
    #: How far the move went, in volatility units. The strength of the claim.
    size_vol: float
    when: float
    #: How many times price has come back into the zone since. Each return
    #: trades away some of whatever was resting here.
    revisits: int = 0

    def holds(self, price: float) -> bool:
        return self.low <= price <= self.high

    def supports(self, want_up: bool) -> bool:
        """Whether this origin is on the right side to back that direction.

        A drop began here, so it is unfilled selling and it backs a *sell*
        into it. The naming is worth being careful about because the opposite
        convention is equally sayable and silently inverts every gate built on
        this.
        """
        return self.launched == ("up" if want_up else "down")

    def to_dict(self) -> dict:
        return {
            "price": round(self.price, 8),
            "low": round(self.low, 8),
            "high": round(self.high, 8),
            "launched": self.launched,
            "size_vol": round(self.size_vol, 4),
            "when": self.when,
            "revisits": self.revisits,
        }


@dataclass(slots=True)
class Origins(Restorable):
    """Every origin found in one feed and timeframe, newest last."""

    found: list[Origin] = field(default_factory=list)

    def observe(
        self,
        times: list[float],
        prices: list[float],
        unit: float,
        *,
        move_vol: float = MOVE_VOL,
        bars: int = MOVE_BARS,
    ) -> list[Origin]:
        """Find the origins in a price series. `unit` is one volatility unit.

        Walks forward looking for displacement over at most `bars` bars, and
        when it finds some, walks *back* to where the move began. Forward to
        detect, backward to locate - the two are different steps because the
        move announces itself only after it has happened, and the price worth
        recording is the one before it did.
        """
        if unit <= 0 or len(prices) < bars + 2:
            return []
        found: list[Origin] = []
        i = 0
        while i < len(prices) - 1:
            end = min(i + bars, len(prices) - 1)
            move = prices[end] - prices[i]
            if abs(move) < move_vol * unit:
                i += 1
                continue
            down = move < 0
            # Run the move out to its full extent before recording it. Without
            # this, a long impulse is found at the first offset that can see
            # `move_vol` of it and then again from where that left off, so one
            # drop becomes two origins at the same price with a fraction of
            # the size each - which understates exactly the thing being
            # measured. A test says so, and caught it.
            while end + 1 < len(prices) and (
                (prices[end + 1] < prices[end]) if down else (prices[end + 1] > prices[end])
            ):
                end += 1
            move = prices[end] - prices[i]
            # Where it began: the extreme in the other direction at the start
            # of the window, not `prices[i]`, which is wherever the walk
            # happened to be standing.
            back = max(0, i - bars)
            window = prices[back : i + 1]
            price = max(window) if down else min(window)
            edge = price - ZONE_VOL * unit if down else price + ZONE_VOL * unit
            found.append(
                Origin(
                    price=price,
                    low=min(price, edge),
                    high=max(price, edge),
                    launched="down" if down else "up",
                    size_vol=abs(move) / unit,
                    when=times[i] if i < len(times) else 0.0,
                )
            )
            # Past the move, so one impulse is recorded once rather than at
            # every offset that can see part of it.
            i = end
        self.found = found
        self._count_revisits(prices)
        return found

    def _count_revisits(self, prices: list[float]) -> None:
        """How often price has come back into each zone since it formed."""
        for origin in self.found:
            inside = False
            for price in prices:
                if origin.holds(price):
                    if not inside:
                        origin.revisits += 1
                    inside = True
                else:
                    inside = False
            # Forming the origin is itself one pass through the zone.
            origin.revisits = max(0, origin.revisits - 1)

    def nearest(self, price: float, want_up: bool) -> Origin | None:
        """The closest origin backing this direction, or None."""
        usable = [o for o in self.found if o.supports(want_up)]
        if not usable:
            return None
        return min(usable, key=lambda o: abs(o.price - price))

    def opposing(self, price: float, want_up: bool) -> Origin | None:
        """The nearest origin in the trade's *direction* - a natural target.

        For a buy, the origin of the last violent rally above here: the price
        where interest stopped the previous advance, and therefore where this
        one is most likely to be stopped too. A target drawn from the same
        evidence as the entry rather than from a multiple of the stop.
        """
        ahead = [
            o
            for o in self.found
            if not o.supports(want_up) and ((o.price > price) if want_up else (o.price < price))
        ]
        if not ahead:
            return None
        return min(ahead, key=lambda o: abs(o.price - price))
