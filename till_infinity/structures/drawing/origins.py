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

It is a **zone**, not a price, and the zone is **the last bar of the leg the
other way** - the final candle of buying before a drop, or of selling before a
rally. Its high to its low is the band.

Not the whole opposing leg, which was the second attempt: a leg can run for
many bars and the interest that mattered was placed in the last of them, so
using the whole thing gives a band far wider than anything that was actually
defended. Not the extreme padded by a constant either, which was the first:
that gave a width nobody had measured.

**And where that last bar is itself huge, its body is used instead.** A bar
whose range runs to `WIDE_BAR` volatility units is mostly wick - the price
went there and did not stay - so its open to its close is the part that
represents traded interest rather than a probe. This is the one judgement in
the definition and it is stated as a constant so it can be argued with.

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

from ..state import Restorable

#: How large a move must be, in volatility units, for its start to count as an
#: origin. Three is deliberately well beyond an ordinary bar - the point is to
#: catch displacement, not movement.
MOVE_VOL = 4.0
#: How many bars the move may take. A drop that takes fifty bars is a trend and
#: its "origin" is wherever you started looking; the claim being made here is
#: about a move fast enough that resting interest did not get refilled.
MOVE_BARS = 6

#: How far past the prior extremum the impulse must go, in volatility units.
#:
#: **Barely clearing it is worse than nothing.** Measured on the first return
#: to 3,458 origins: one that cleared the extremum by under 0.5 units held
#: 49.7% of the time, against 60.4% for the same bucket on Deriv's synthetics -
#: a generated process with no structure at all. Clearing it by 0.5 to 1.5
#: units held 75.6%.
#:
#: So this is a floor rather than a preference, and the same is true of
#: `MOVE_VOL`: impulses of 3-4 units held 54.3% against 57.6% on synthetics,
#: and 4-5.5 units held 75.0%. Both tests have a region where they select
#: origins worse than noise, and past it both plateau - bigger is not better,
#: it is just not worse. That is why they are two floors rather than a score
#: trading one against the other.
MIN_EXTREMUM_VOL = 0.5

#: Bars the impulse's extremum is measured against.
#:
#: **An origin has to lead somewhere.** A turn followed by a large move is not
#: yet an origin: price turns and runs constantly inside a range, and every one
#: of those is a "last opposing bar before an impulse" that meant nothing. What
#: separates the ones that matter is that the impulse **set a new running
#: extremum** over this window - exceeded the highest high or lowest low that
#: had been holding - because that is the move which leaves unfilled interest
#: behind it.
#:
#: A desk calls this a *break of structure*. The name here is the mathematical
#: one because it says what is computed: the running maximum or minimum of the
#: lookback, and whether the impulse exceeded it. `record` would be the term
#: from probability - a value larger than everything before it - but this
#: package already uses `record` for a level's touch history, and one word
#: meaning two things is worse than a longer word.
#:
#: This is also the most likely reason origin *proximity* measured -0.166 over
#: 49,619 resolutions: unfiltered, most origins are range noise, and a signal
#: averaged over noise measures the noise. **A hypothesis, not a result** - the
#: filter keeps 62-72% of origins across gold, eurusd, us100 and btc, so it is
#: a real cut, and whether what survives scores better is unmeasured until the
#: journal has enough of them.
EXTREMUM_BARS = 20
#: How far either side of the origin price the zone reaches, in volatility
#: units, when there is no bar to measure from at all.
ZONE_VOL = 0.5
#: A bar whose whole range reaches this many volatility units is treated as
#: mostly wick, and its body is used for the zone instead. Price went there and
#: did not stay, so the open to the close is the part that traded rather than
#: probed.
WIDE_BAR = 2.0


def zone_of(bar, unit: float) -> tuple[float, float]:
    """The band one bar contributes: its range, or its body when that is huge.

    `bar` is anything carrying `open`, `high`, `low` and `close` - duck-typed
    rather than imported, so `structures` need not depend on the trading
    package that happens to define a Bar today.

    High to low is the interest placed during that bar. Where the whole range
    reaches `WIDE_BAR` volatility units the bar is mostly wick - price went
    there and did not stay - so the open to the close is used instead: the part
    that traded rather than probed.
    """
    high, low = float(bar.high), float(bar.low)
    if unit > 0 and (high - low) >= WIDE_BAR * unit:
        top, bottom = float(bar.open), float(bar.close)
        if top != bottom:
            return min(top, bottom), max(top, bottom)
    return low, high


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
    #: How far past the structure it broke, in volatility units.
    #:
    #: The magnitude test (`MOVE_VOL`) and the structural one are separate
    #: questions - how big was it, and did it clear a particular prior extreme -
    #: and measured against a 4.5-unit move they agree only 59-78% of the time.
    #: Keeping the margin lets a consumer weigh them together instead of taking
    #: both as pass/fail, and lets the journal say whether a decisive break is
    #: worth more than a large one.
    extremum_vol: float = 0.0

    #: When the impulse that made this origin broke structure.
    #:
    #: **Not the same as `when`, and the difference is a look-ahead bug.** The
    #: turn happens first; the origin does not exist until the move that
    #: followed took out the structure that was holding, which is several bars
    #: later. Anything asking "when was this knowable" - a level's `confirmed`,
    #: a replay's cut-off - has to read this, or it is drawing a level at a
    #: price nobody could have known was one.
    settled: float = 0.0
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
            "extremum_vol": round(self.extremum_vol, 4),
            "when": self.when,
            "settled": self.settled,
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
        bars_at: list | None = None,
        extremum_bars: int = EXTREMUM_BARS,
        require_extremum: bool = True,
        min_extremum_vol: float = MIN_EXTREMUM_VOL,
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
            # **The turn, not the window.** Detection measures net change
            # across `bars`, and a window can straddle a reversal - a fall
            # from 104 to 100 followed by a rally to 110 nets positive, so the
            # walk reports an up-impulse beginning at 103 when price was still
            # falling there. The impulse really begins at the extreme inside
            # the window, so find that first.
            span = prices[i : end + 1]
            turn = i + (span.index(max(span)) if down else span.index(min(span)))
            price = prices[turn]

            # Then the zone: the **last leg the other way** before the turn,
            # and its own range is the band. Walk back while price was still
            # travelling opposite to the impulse.
            #
            # Not the extreme of a fixed window padded by a constant, which is
            # what this did first - that gave a zone whose width was chosen
            # rather than observed, with its far edge an arbitrary distance
            # from the one price that meant anything.
            back = turn
            while back > 0 and (
                (prices[back - 1] < prices[back]) if down else (prices[back - 1] > prices[back])
            ):
                back -= 1
            # The **last bar** of that leg, not the whole leg. A leg can run
            # for many bars and the interest that mattered was placed in the
            # last of them; the whole thing gives a band far wider than
            # anything that was actually defended.
            # The bar *at* the turn, which is the last bar of the opposing leg -
            # it is the one that made the extreme. Taking the bar before it
            # reads the second-to-last stretch of buying and misses the one
            # that actually turned.
            last = turn
            if bars_at is not None and 0 <= last < len(bars_at):
                low, high = zone_of(bars_at[last], unit)
            elif back != turn:
                # No bars to read. The two ends of the leg are wider than they
                # should be, and better than a constant.
                low, high = min(prices[back], price), max(prices[back], price)
            else:
                # Nothing opposing at all: an impulse from a flat, or from the
                # start of the series. The constant survives only here, and
                # this is the weakest case.
                edge = price - ZONE_VOL * unit if down else price + ZONE_VOL * unit
                low, high = min(price, edge), max(price, edge)
            # **Did the impulse break structure?** The extreme that was
            # holding before the turn, and whether the move took it out. A
            # move that stops short of it is a swing inside a range, not the
            # break that leaves interest stranded.
            # Before the turn, not including it: the turn is the origin, and
            # the structure is what was holding until it.
            look = prices[max(0, turn - extremum_bars) : turn] if require_extremum else []
            if require_extremum and len(look) < 2:
                # No history to have broken. An impulse off the first bars of a
                # series has no structure behind it, and calling that a break
                # would make every series begin with an origin.
                i = turn + 1
                continue
            past_by = 0.0
            if require_extremum:
                held = min(look) if down else max(look)
                if not (prices[end] < held if down else prices[end] > held):
                    i = turn + 1
                    continue
                past_by = abs(prices[end] - held) / unit if unit else 0.0
                if past_by < min_extremum_vol:
                    i = turn + 1
                    continue

            move = prices[end] - price
            found.append(
                Origin(
                    price=price,
                    low=low,
                    high=high,
                    launched="down" if down else "up",
                    size_vol=abs(move) / unit,
                    extremum_vol=past_by,
                    # The turn, not the window that found it. `price` is
                    # `prices[turn]` and this was `times[i]` - the start of the
                    # detection window, which sits at or before the turn. One
                    # origin was reporting its price from one bar and its time
                    # from another.
                    when=times[turn] if turn < len(times) else 0.0,
                    # When the impulse broke structure, which is when this
                    # became knowable. See `Origin.settled`.
                    settled=times[end] if end < len(times) else 0.0,
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
