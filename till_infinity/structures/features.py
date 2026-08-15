"""Turning quotes into features that describe a venue *relative to the others*.

This is the part that matters. An anomaly detector fed one venue's spread
learns what is normal for that venue, which is useful but not the point — the
project collects six venues precisely because the disagreement between them
carries information no single feed does.

So every feature here is relative:

- `dev_bps` — how far this venue's mid sits from where the others agree it is.
  Robust to the venue itself, because the consensus is a median taken *without*
  it. Including a venue in the number it is measured against is how a stale
  feed hides: with six venues one bad reading barely moves a mean, and with two
  it moves it halfway.
- `spread_ratio` — this venue's spread against the group's, so "wide" means
  wide compared with everyone quoting the same instrument at the same instant,
  not wide against a constant.
- `staleness` — how long since this venue last moved, against how long since
  the group last moved. A market that stops on a Sunday is not an anomaly; one
  venue stopping while five carry on is.

The state kept per venue is small and bounded: the last quote and a rolling
mean of its deviation. Nothing here grows with time.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

from .models import Consensus
from .state import Restorable

#: Bound once at import: a dataclass field called `time` shadows the module
#: inside the class body, so the second default would resolve against a Field.
_now = time.time

#: Below this many venues there is no "rest of the market" to compare against,
#: and a two-venue median is just the midpoint of a disagreement.
MIN_VENUES = 3

#: A quote older than this is not evidence about the present.
MAX_AGE = 300.0

#: Treat the group as having been still for at least this long. A busy market
#: has a median stillness near zero, and that is a divisor, not a signal.
STILL_FLOOR = 1.0


@dataclass(slots=True)
class Reading(Restorable):
    """The last thing one venue said."""

    venue: str
    mid: float
    spread_bps: float = 0.0
    time: float = field(default_factory=_now)
    #: When this venue's mid last actually changed, not when it last spoke.
    moved: float = field(default_factory=_now)

    def age(self, now: float) -> float:
        return max(0.0, now - self.time)

    def still(self, now: float) -> float:
        """Seconds since the price last changed."""
        return max(0.0, now - self.moved)


class Book:
    """The latest reading from every venue quoting one instrument.

    One per feed. Holds at most one row per venue, so memory is bounded by how
    many brokers are configured rather than by how long it has been running.
    """

    def __init__(self, feed: str, max_age: float = MAX_AGE) -> None:
        self.feed = feed
        self.max_age = max_age
        self._readings: dict[str, Reading] = {}

    def update(self, venue: str, mid: float, spread_bps: float, when: float) -> None:
        previous = self._readings.get(venue)
        moved = when
        if previous is not None and previous.mid == mid:
            # Same price: it spoke, it did not move. Keeping these apart is what
            # makes a stale feed detectable — a dead feed often keeps sending.
            moved = previous.moved
        self._readings[venue] = Reading(venue, mid, spread_bps, when, moved)

    def live(self, now: float | None = None) -> list[Reading]:
        now = time.time() if now is None else now
        return [r for r in self._readings.values() if r.age(now) <= self.max_age]

    def consensus(self, exclude: str = "", now: float | None = None) -> Consensus | None:
        """Where the venues agree, optionally leaving one out.

        `exclude` is not optional in spirit: a venue must never be part of the
        number it is being measured against.
        """
        now = time.time() if now is None else now
        others = [r for r in self.live(now) if r.venue != exclude]
        if len(others) < MIN_VENUES - (1 if exclude else 0):
            return None
        mids = [r.mid for r in others]
        spreads = [r.spread_bps for r in others if r.spread_bps]
        return Consensus(
            feed=self.feed,
            mid=statistics.median(mids),
            venues=len(others),
            spread_bps=statistics.median(spreads) if spreads else 0.0,
            time=now,
        )

    def features(self, venue: str, now: float | None = None) -> dict[str, float] | None:
        """How this venue looks against the rest, right now.

        Returns None when there is nothing to compare against — silence is the
        honest answer when five of six feeds are down, not a score of zero.
        """
        now = time.time() if now is None else now
        reading = self._readings.get(venue)
        if reading is None or reading.age(now) > self.max_age:
            return None
        rest = self.consensus(exclude=venue, now=now)
        if rest is None or not rest.mid:
            return None

        others = [r for r in self.live(now) if r.venue != venue]
        group_still = statistics.median([r.still(now) for r in others]) if others else 0.0
        return {
            "dev_bps": (reading.mid - rest.mid) / rest.mid * 10_000,
            "abs_dev_bps": abs(reading.mid - rest.mid) / rest.mid * 10_000,
            "spread_bps": reading.spread_bps,
            "spread_ratio": (reading.spread_bps / rest.spread_bps) if rest.spread_bps else 1.0,
            "staleness": reading.still(now),
            # Against a floor, not against the raw group figure. When every
            # other venue is updating, their median stillness is ~0, and
            # dividing by it would either explode or — worse — be guarded away
            # to 1.0, blinding the ratio at the exact moment it matters most.
            "staleness_ratio": reading.still(now) / max(group_still, STILL_FLOOR),
            "venues": float(rest.venues),
        }

    def venues(self) -> list[str]:
        return sorted(self._readings)

    def __len__(self) -> int:
        return len(self._readings)


class Books:
    """One book per instrument. The whole feature layer's state."""

    def __init__(self, max_age: float = MAX_AGE) -> None:
        self.max_age = max_age
        self._books: dict[str, Book] = {}

    def book(self, feed: str) -> Book:
        found = self._books.get(feed)
        if found is None:
            found = self._books[feed] = Book(feed, self.max_age)
        return found

    def observe(self, payload: dict) -> tuple[str, str, dict[str, float]] | None:
        """Take one `prices.quotes` message and return (feed, venue, features).

        None when the message cannot produce a comparison — no mid, an unknown
        venue, or not enough other venues to be a consensus yet.
        """
        feed = str(payload.get("feed") or "")
        venue = str(payload.get("venue") or "")
        mid = payload.get("mid")
        if not feed or not venue or not isinstance(mid, int | float) or not mid:
            return None
        bps = payload.get("spread_bps")
        when = float(payload.get("time") or time.time())
        book = self.book(feed)
        book.update(venue, float(mid), float(bps) if isinstance(bps, int | float) else 0.0, when)
        features = book.features(venue, now=when)
        return (feed, venue, features) if features else None

    def feeds(self) -> list[str]:
        return sorted(self._books)
