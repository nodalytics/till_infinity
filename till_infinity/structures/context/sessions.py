"""What the hour of the day is worth, measured rather than named.

Every model in this package conditions on the *shape* of price. None has ever
conditioned on **when**. That is a real gap and an unusually cheap one to close,
because the timestamp is already on every bar.

## The claim, and the honest version of it

The folk version names windows - sessions, "killzones", fixed one-hour slots -
and asserts that price behaves differently inside them. The literature that
actually survives says something narrower and better supported: **volatility,
volume and liquidity have pronounced time-of-day structure**, consistently
across venues and instruments, with crypto realised volatility peaking around
the opens of the major equity markets. What it does *not* establish is that
**returns** are seasonal, and the two are easy to conflate. A more volatile
hour is equally an argument that costs are worse in it.

So this module asserts nothing about which hours are good. It measures two
things per instrument and hour, and lets whatever consumes it decide:

- **how the hour behaves** - the volatility of that hour against the
  instrument's own day, which is the part the literature supports;
- **how calls made in that hour resolved** - held or broke, against the
  instrument's own base rate, which is the part nobody here has measured.

## Why it is a model and not a table of hours

An hour with four observations knows nothing, and the naive version - bucket by
hour, divide, compare - will happily report 100% from two samples and send a
strategy chasing it. Every rate here is therefore **shrunk toward the
instrument's own pooled rate** with a Beta prior, so a thin hour reports
approximately the base rate and only earns a distinct number as evidence
accumulates. The count travels with the rate for the same reason it does on
`SideStats.hold_rate`: a rate with nothing behind it is not a low rate.

Counts **decay**, as everywhere else in this package. An hour's character in
March is evidence about April and not about next year, and a hard window would
make the estimate jump on an arbitrary boundary.

## What it is deliberately not

It is not a filter, and it does not decide anything. It publishes two numbers
and their counts onto the level signal; a strategy may use them as context, and
the journal records them against outcomes so the question *"does the hour carry
information here"* becomes answerable from our own data rather than from
somebody's chart. Given six prior nulls in this project on filters over an
already-selected entry, the prior is not high - which is the reason to measure
rather than to assume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..state import Restorable

#: Hours in a day, and the only bucketing this module does. Finer than an hour
#: divides the evidence past the point of meaning anything; coarser loses the
#: equity-open structure that is the one well-supported effect.
HOURS = 24

#: Weight of the prior each hour is shrunk toward. An hour needs roughly this
#: many observations before it is speaking for itself rather than repeating the
#: instrument's pooled rate.
PRIOR_WEIGHT = 12.0

#: Per-observation decay, applied on write. About a 30-day half-life at a few
#: observations an hour - long enough to be a distribution, short enough to
#: still be this market.
DECAY = 0.999

#: Named windows, for reading rather than for deciding. The boundaries are the
#: major cash opens in UTC, which is the mechanism behind the one time-of-day
#: effect the literature actually supports.
SESSIONS: tuple[tuple[str, int, int], ...] = (
    ("asia", 0, 7),
    ("london", 7, 12),
    ("overlap", 12, 16),
    ("newyork", 16, 21),
    ("late", 21, 24),
)


def session_of(hour: int) -> str:
    """Which named window an hour falls in. Presentation, not a decision."""
    hour %= HOURS
    for name, start, end in SESSIONS:
        if start <= hour < end:
            return name
    return "late"


def hour_of(when: float) -> int:
    """UTC hour of a timestamp. UTC because every other clock here is."""
    return datetime.fromtimestamp(when, UTC).hour


@dataclass(slots=True)
class Hour(Restorable):
    """One instrument's record for one hour of the day."""

    #: Decayed counts of decisive interactions and of those that held.
    decisive: float = 0.0
    held: float = 0.0
    #: Exponential mean of the volatility observed in this hour, in bps.
    vol_bps: float = 0.0
    seen: float = 0.0

    def record(self, held: bool) -> None:
        self.decisive = self.decisive * DECAY + 1.0
        self.held = self.held * DECAY + (1.0 if held else 0.0)

    def observe_vol(self, bps: float) -> None:
        if bps <= 0:
            return
        self.seen = self.seen * DECAY + 1.0
        # Weighted toward the accumulated estimate once there is one, so a
        # single violent hour does not redefine the hour's character.
        weight = 1.0 / min(max(self.seen, 1.0), 50.0)
        self.vol_bps = bps if not self.vol_bps else self.vol_bps * (1 - weight) + bps * weight


@dataclass(slots=True)
class Clock(Restorable):
    """Every instrument's hours, and what they are worth.

    Keyed by feed rather than by (feed, interval): the hour of the day is a
    property of the market, not of the timeframe a level happens to sit on, and
    splitting by interval would divide already-thin evidence eight ways.
    """

    _hours: dict[str, list[Hour]] = field(default_factory=dict)

    def _for(self, feed: str) -> list[Hour]:
        found = self._hours.get(feed)
        if found is None:
            found = self._hours[feed] = [Hour() for _ in range(HOURS)]
        return found

    def record(self, feed: str, when: float, held: bool) -> None:
        """Fold in how a call made in this hour resolved."""
        self._for(feed)[hour_of(when) % HOURS].record(held)

    def observe_vol(self, feed: str, when: float, bps: float) -> None:
        """Fold in the volatility seen in this hour."""
        self._for(feed)[hour_of(when) % HOURS].observe_vol(bps)

    def base_rate(self, feed: str) -> float:
        """The instrument's pooled hold rate across every hour.

        The thing each hour is shrunk toward, and the thing an hour's rate has
        to be read against. An hour at 70% where the instrument holds 70%
        anyway has said nothing, however many observations are behind it.

        **Itself shrunk, toward a coin.** Shrinking an hour toward a base rate
        computed from the same handful of observations is no protection at all:
        an instrument whose only two interactions both held has a pooled rate
        of 1.0, so the hour is shrunk toward 1.0 and reports 1.0. Caught by
        asking a two-observation clock what it thought and being told
        "certainty". A new instrument now reads near a coin flip until it has
        earned otherwise.
        """
        hours = self._hours.get(feed)
        if not hours:
            return 0.5
        decisive = sum(h.decisive for h in hours)
        held = sum(h.held for h in hours)
        return (held + PRIOR_WEIGHT * 0.5) / (decisive + PRIOR_WEIGHT)

    def hold_rate(self, feed: str, when: float) -> tuple[float, float]:
        """(shrunk hold rate, observations) for the hour of `when`.

        Shrunk toward the instrument's pooled rate, so a thin hour reports
        approximately the base rate rather than whatever its four samples did.
        """
        hour = self._for(feed)[hour_of(when) % HOURS]
        prior = self.base_rate(feed)
        if hour.decisive <= 0:
            return prior, 0.0
        rate = (hour.held + PRIOR_WEIGHT * prior) / (hour.decisive + PRIOR_WEIGHT)
        return rate, hour.decisive

    def edge(self, feed: str, when: float) -> float:
        """How far this hour sits from the instrument's own base rate.

        The number worth reading. Positive means calls made in this hour have
        held more often than the instrument does generally; zero means the hour
        carries no information, which is the expected answer.
        """
        rate, _ = self.hold_rate(feed, when)
        return rate - self.base_rate(feed)

    def volatility(self, feed: str, when: float) -> tuple[float, float]:
        """(this hour's volatility in bps, its share of the day's mean).

        The share is the interpretable half: 1.0 is an ordinary hour for this
        instrument, 1.8 is one of its violent ones. It is also the half the
        literature actually supports, and it cuts both ways - a violent hour is
        equally an argument that the spread is worse in it.
        """
        hours = self._for(feed)
        this = hours[hour_of(when) % HOURS].vol_bps
        seen = [h.vol_bps for h in hours if h.vol_bps > 0]
        if not this or not seen:
            return this, 1.0
        mean = math.fsum(seen) / len(seen)
        return this, (this / mean if mean > 0 else 1.0)

    def observations(self, feed: str) -> float:
        hours = self._hours.get(feed)
        return sum(h.decisive for h in hours) if hours else 0.0

    def feeds(self) -> list[str]:
        return sorted(self._hours)
