"""What this broker's spread usually is, at this hour, on this instrument.

There are already two spread gates and both are right, so this one exists for
a narrower reason than "spread varies".

`Context.dislocation` compares our spread against the **peer group's spread at
that instant**, which is the best available test: if six venues have all
widened, ours widening with them is the market, not the broker. `Guard.allows`
compares spread against the **trade's own reward**, which is the economic
question - a cost that eats the target refuses the trade whatever the reason
for it. Between them, the ordinary case is covered, and a time-of-day model
layered on top would refuse trades that are economically fine.

**The gap is the fail-open.** The peer test needs `MIN_VENUES` fresh quotes and
returns "" when it does not have them - no spread check at all. That is not a
rare path: it is thin hours, rollover, holidays, and any instrument carried by
fewer venues than the majors, which is exactly the set of moments a broker's
spread is worst. In those moments there is no reference at all today.

So this supplies one, from the instrument's own history rather than from peers.

## Why this is not the rolling quantile that was already refuted

[edge.md](../../docs/edge.md) measured a rolling quantile against a matched
constant and the constant won by four to ten points, four times out of four.
The reasoning behind that result is what matters here: `edge` was **already
scale-free**, so normalising it per cell destroyed a comparability it already
had.

A broker's spread in bps is not in that position. It has no fixed meaning
across instruments or hours, there is no constant that could mean the same
thing on gold at rollover and on EURUSD at the London open, and - the part that
settles it - **on this path there is currently no reference of any kind.** This
is not a normalisation replacing a comparable number. It is a reference where
the alternative is nothing.

It is also not a quantile. Quantiles need a stored distribution and a warm-up
long enough to fill it, and edge.md's second finding was that 9 of 24 cells
never reached the 50 observations the rolling rule needed. This keeps a decayed
mean and a count, shrinks the hour toward the instrument's own pooled spread,
and refuses to speak at all until it has evidence - the same shape as
`structures.sessions`, for the same reasons.

## What it deliberately does not do

It cannot overrule the peer test, only stand in when there is none. It never
loosens anything: on the path it covers the current behaviour is to allow
everything, so its only possible effect is to refuse a trade that would
otherwise have been taken on an unexamined spread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

#: Hours in a day. Matches `structures.sessions.HOURS` deliberately - the same
#: bucketing, so the two can be read against each other.
HOURS = 24

#: How much evidence an hour needs before it speaks for itself rather than
#: repeating the instrument's pooled spread.
PRIOR_WEIGHT = 12.0

#: Observations before this estimate is allowed to refuse anything at all.
#: Below it the module reports what it has and the caller is expected to ignore
#: it - a spread limit derived from four quotes is not a limit.
MIN_EVIDENCE = 30.0

#: Per-observation decay. A spread regime is a property of the broker and the
#: month, not of the year: brokers change their pricing and a stale mean would
#: refuse ordinary trades long after the change.
DECAY = 0.999


def hour_of(when: float) -> int:
    """UTC hour of a timestamp. UTC because every other clock here is."""
    return datetime.fromtimestamp(when, UTC).hour


@dataclass(slots=True)
class Bucket:
    """One instrument's spread record for one hour of the day."""

    #: Decayed exponential mean of spread, in basis points.
    bps: float = 0.0
    #: Decayed count of observations behind it.
    seen: float = 0.0

    def observe(self, bps: float) -> None:
        if bps <= 0:
            return
        self.seen = self.seen * DECAY + 1.0
        # Weighted toward the accumulated estimate once there is one, so a
        # single widening does not redefine the hour. Capped so the estimate
        # keeps tracking rather than freezing once the count is large.
        weight = 1.0 / min(max(self.seen, 1.0), 50.0)
        self.bps = bps if not self.bps else self.bps * (1 - weight) + bps * weight


@dataclass(slots=True)
class Spreads:
    """Every instrument's spread by hour, and what it is usually worth.

    Keyed by feed rather than by (feed, interval): the spread a broker quotes
    is a property of the instrument and the clock, not of the timeframe a level
    happens to sit on.
    """

    _hours: dict[str, list[Bucket]] = field(default_factory=dict)
    _pooled: dict[str, Bucket] = field(default_factory=dict)

    def _for(self, feed: str) -> list[Bucket]:
        found = self._hours.get(feed)
        if found is None:
            found = self._hours[feed] = [Bucket() for _ in range(HOURS)]
        return found

    def observe(self, feed: str, when: float, bps: float) -> None:
        """Fold in a spread seen on this instrument at this time."""
        if not feed or bps <= 0:
            return
        self._for(feed)[hour_of(when) % HOURS].observe(bps)
        pooled = self._pooled.get(feed)
        if pooled is None:
            pooled = self._pooled[feed] = Bucket()
        pooled.observe(bps)

    def expected(self, feed: str, when: float) -> tuple[float, float]:
        """The spread to expect here, in bps, and the evidence behind it.

        The hour's own mean shrunk toward the instrument's pooled mean, so a
        thin hour reports approximately the instrument's usual spread and only
        earns a distinct number as observations accumulate. Returns
        `(0.0, 0.0)` when there is nothing to say, which callers must treat as
        "no opinion" rather than as a spread of zero.
        """
        pooled = self._pooled.get(feed)
        if pooled is None or pooled.bps <= 0:
            return (0.0, 0.0)
        bucket = self._for(feed)[hour_of(when) % HOURS]
        if bucket.bps <= 0:
            return (pooled.bps, pooled.seen)
        weight = bucket.seen / (bucket.seen + PRIOR_WEIGHT)
        return (bucket.bps * weight + pooled.bps * (1 - weight), bucket.seen)

    def ratio(self, feed: str, when: float, bps: float) -> float:
        """How many times the usual spread this one is. Zero if unknown.

        Zero rather than 1.0 for "unknown", so a caller cannot accidentally
        treat an unmeasured instrument as a normal one.
        """
        if bps <= 0:
            return 0.0
        usual, seen = self.expected(feed, when)
        if usual <= 0 or seen < MIN_EVIDENCE:
            return 0.0
        return bps / usual
