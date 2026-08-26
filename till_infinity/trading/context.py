"""What the rest of the system knows that a level call does not say.

A `LEVEL` signal is a statement about price structure and nothing else. It
cannot see that CPI prints in four minutes, that our broker is quoting eleven
basis points away from where six venues agree, or that the volatility regime
changed an hour ago and every level's history was learned in the old one.

All three are already on the bus. This module consumes them and answers three
questions, which `risk.Guard` then asks before any trade:

| topic | question |
|---|---|
| `news.events` | is a high-impact release about to land on this instrument |
| `prices.quotes` | is our broker's price or spread out of line with the venues |
| `structures.signals` (`drift`) | did the regime just change under this instrument |

**Nothing here is a forecast.** Each is a reason to stand aside, not a reason
to trade, and each fails safe: an empty calendar imposes no blackout, an absent
consensus imposes no dislocation check, and no drift signal means no pause.
A guard that refuses everything when its input is missing would stop the system
the first time a collector restarted.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..logging import get_logger
from . import exposure as ex
from .models import Tick
from .spreads import Spreads, hour_of

log = get_logger(__name__)

#: Calendar importance at or above which a release is worth standing aside for.
#: The scale is the news module's: 0 low, 1 medium, 2 high.
HIGH = 2

#: Venues needed before a median price means anything, matching what
#: `structures` requires of a consensus bar. Two venues that disagree have no
#: median worth the name.
MIN_VENUES = 3

#: Quotes older than this stop counting toward the consensus. A venue that has
#: stopped updating should not anchor the price our broker is judged against -
#: that is the `stale` shape, and it would otherwise turn one dead feed into a
#: dislocation on everybody else.
QUOTE_TTL = 90.0


@dataclass(frozen=True, slots=True)
class Release:
    """One scheduled release, reduced to what a blackout needs."""

    title: str
    currency: str
    when: float
    importance: int


@dataclass(slots=True)
class Context:
    """Everything outside the level call, kept current from the bus."""

    #: Seconds either side of a high-impact release to stand aside. Wider
    #: after than before: see `Settings.news_before`.
    before: float = 600.0
    after: float = 900.0
    #: Basis points our broker may sit away from the venue median before a
    #: quote is treated as unusable for entry.
    max_dislocation_bps: float = 8.0
    #: Multiple of the venue-median spread our broker may charge.
    max_spread_ratio: float = 2.5
    #: Seconds to stand aside on an instrument after a drift signal.
    drift_pause: float = 900.0
    #: Seconds to stand aside after the venues covering an instrument widen
    #: together. Much shorter than `drift_pause`: a widening passes, a regime
    #: change does not.
    wide_pause: float = 300.0
    #: Seconds an instrument must have been seen before a widening counts.
    #:
    #: `structures` scores spread with a per-venue model that needs history
    #: before it means anything, and a newly added instrument has none - so its
    #: first minutes produce anomalies that are a statement about the detector
    #: rather than about the market. Caught the day fourteen instruments were
    #: added at once: two of them were flagged wide on three venues within two
    #: minutes of first being quoted, which would have stood the trader aside
    #: on precisely the symbols that had just been switched on.
    wide_warmup: float = 900.0
    #: How many distinct venues must be flagged wide at once before the market
    #: is treated as wide rather than one venue being wide.
    #:
    #: `structures` scores spread per venue and publishes an anomaly whenever
    #: one is out of line with the group. Those fire continuously and are
    #: *supposed* to - one venue quoting badly is what the detector is for -
    #: so standing aside on each would stop trading altogether. Several venues
    #: widening at the same moment is a different statement: the instrument has
    #: thinned out everywhere, and there is no good fill to be had from anyone.
    wide_venues: int = 3

    _events: dict[str, Release] = field(default_factory=dict)
    _quotes: dict[str, dict[str, tuple[float, float, float]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    _drifted: dict[str, float] = field(default_factory=dict)
    #: feed -> {venue: when it was last flagged wide}.
    _wide: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(dict))
    #: feed -> when anything was first heard about it, for `wide_warmup`.
    _first_seen: dict[str, float] = field(default_factory=dict)
    #: feed -> already announced as wide, so one widening is one line rather
    #: than one per venue report for as long as it lasts.
    _said_wide: dict[str, bool] = field(default_factory=dict)
    #: This broker's own spread by instrument and hour. Only consulted when
    #: there is no peer group to judge against - see `dislocation`.
    spreads: Spreads = field(default_factory=Spreads)

    # ------------------------------------------------------------- consuming

    def observe_event(self, payload: dict[str, Any]) -> None:
        """Take one calendar row. Rows are rewritten in place as prints land."""
        importance = payload.get("importance")
        when = payload.get("time")
        if not isinstance(when, int | float) or not when:
            return
        if not isinstance(importance, int) or importance < HIGH:
            return
        currency = ex.currency_of(str(payload.get("country") or ""))
        if not currency:
            return  # an instrument we do not price; see news/symbols.py
        key = f"{payload.get('source')}:{payload.get('id')}"
        self._events[key] = Release(
            title=str(payload.get("title") or ""),
            currency=currency,
            when=float(when),
            importance=int(importance),
        )
        self._forget(float(when))

    def observe_quote(self, payload: dict[str, Any]) -> None:
        """Take one venue's quote, for the consensus our broker is judged against."""
        feed = str(payload.get("feed") or "")
        venue = str(payload.get("venue") or "")
        mid, spread = payload.get("mid"), payload.get("spread_bps")
        if not feed or not venue or not isinstance(mid, int | float) or not mid:
            return
        when = payload.get("time")
        self._quotes[feed][venue] = (
            float(mid),
            float(spread) if isinstance(spread, int | float) else 0.0,
            float(when) if isinstance(when, int | float) and when else time.time(),
        )

    def observe_signal(self, payload: dict[str, Any]) -> None:
        """Note a regime change or a widening. Everything else is ignored."""
        shape = str(payload.get("shape") or "")
        feed = str(payload.get("feed") or "")
        if not feed:
            return
        when = payload.get("time")
        at = float(when) if isinstance(when, int | float) and when else time.time()
        self._first_seen.setdefault(feed, at)

        if shape == "drift":
            self._drifted[feed] = at
            log.info("trading: %s drifted - standing aside for %.0fs", feed, self.drift_pause)
            return

        if shape == "spread":
            # Recorded per venue rather than counted, because the same venue
            # reporting five times is one wide venue and not five.
            venue = str((payload.get("fields") or {}).get("venue") or payload.get("venue") or "")
            if not venue:
                return
            seen = self._wide[feed]
            seen[venue] = at
            # Asked through `widened` rather than counted here, so the log
            # cannot claim an action the gate is not taking. It said "standing
            # aside" during the warm-up window, when the gate was correctly
            # doing nothing - a log that announces a decision nobody made is
            # worse than no log, because it is what gets believed later.
            if self.widened(feed, at) and not self._said_wide.get(feed):
                self._said_wide[feed] = True
                log.info(
                    "trading: %s is wide on %d venues at once - standing aside for %.0fs",
                    feed,
                    self.widened(feed, at),
                    self.wide_pause,
                )
            elif not self.widened(feed, at):
                self._said_wide.pop(feed, None)

    # -------------------------------------------------------------- answering

    def blackout(self, feed: str, now: float | None = None) -> Release | None:
        """The release this instrument is inside the window of, if any.

        A US release blacks out gold, BTC and every major, because the dollar
        is on one side of all of them. That is wide, and it is correct: a
        scalper's stop is a few volatility units, and NFP moves gold by more
        than that in the first second.
        """
        when = now if now is not None else time.time()
        currencies = set(ex.legs(feed))
        if not currencies or currencies == {""}:
            return None
        for release in self._events.values():
            if release.currency not in currencies:
                continue
            # `since` is negative before the print and positive after it, so
            # `before` bounds the negative side. Getting this backwards swaps
            # the two windows and blacks out the wrong minutes - which is what
            # the first version did, with a comment warning against it.
            since = when - release.when
            if -self.before <= since <= self.after:
                return release
        return None

    def consensus(self, feed: str, now: float | None = None) -> tuple[float, float, int]:
        """Median mid, median spread and venue count. Zeros when too thin."""
        when = now if now is not None else time.time()
        fresh = [
            (mid, spread)
            for mid, spread, seen in self._quotes.get(feed, {}).values()
            if when - seen <= QUOTE_TTL
        ]
        if len(fresh) < MIN_VENUES:
            return (0.0, 0.0, len(fresh))
        mids = sorted(mid for mid, _ in fresh)
        spreads = sorted(spread for _, spread in fresh)
        return (_median(mids), _median(spreads), len(fresh))

    def dislocation(self, feed: str, tick: Tick, now: float | None = None) -> str:
        """ "" if our broker's quote is usable, else why it is not.

        Two separate faults with the same remedy. A broker priced away from
        where six venues agree is offering a fill at a price the market does
        not hold, and a broker charging several times the group's spread is
        charging the trade's whole expected push to open it.
        """
        when = now if now is not None else time.time()
        self.spreads.observe(feed, when, tick.spread_bps)

        median, spread, venues = self.consensus(feed, now)
        if venues < MIN_VENUES or median <= 0:
            # No peer group. This used to fail open, which meant no spread
            # check of any kind - and the moments with too few fresh quotes are
            # thin hours, rollover, holidays and the instruments carried by
            # fewer venues, which is exactly when a broker's spread is worst.
            #
            # So fall back to the instrument's own history at this hour. It
            # cannot overrule the peer test, only stand in when there is none,
            # and it stays silent until it has evidence - `ratio` returns 0.0
            # rather than 1.0 for "unknown" so an unmeasured instrument can
            # never be mistaken for a normal one.
            times = self.spreads.ratio(feed, when, tick.spread_bps)
            if times > self.max_spread_ratio:
                usual, _ = self.spreads.expected(feed, when)
                return (
                    f"our spread is {tick.spread_bps:.2f}bps against the "
                    f"{usual:.2f}bps usual for {hour_of(when):02d}:00 on this "
                    f"instrument ({times:.1f}x), and only {venues} peer "
                    f"quote(s) to check it against"
                )
            return ""

        away_bps = abs(tick.mid - median) / median * 10_000
        if away_bps > self.max_dislocation_bps:
            return (
                f"our quote is {away_bps:.1f}bps from the {venues}-venue median "
                f"{median:.5g}, limit is {self.max_dislocation_bps:.1f}bps"
            )
        if spread > 0 and tick.spread_bps > spread * self.max_spread_ratio:
            return (
                f"our spread is {tick.spread_bps:.2f}bps against the group's "
                f"{spread:.2f}bps, limit is {self.max_spread_ratio:.1f}x"
            )
        return ""

    def widened(self, feed: str, now: float | None = None) -> int:
        """How many venues are currently quoting this instrument wide.

        Zero unless it is at or past `wide_venues`, so a caller cannot read a
        single badly-behaved venue as the market thinning out. One venue out of
        line is what `dislocation` already judges our own broker against; this
        is the case where there is nobody left to be judged against.
        """
        seen = self._wide.get(feed)
        if not seen:
            return 0
        when = now if now is not None else time.time()
        # An instrument nobody has watched for long enough cannot be judged
        # unusual. See `wide_warmup`.
        first = self._first_seen.get(feed)
        if first is not None and when - first < self.wide_warmup:
            return 0
        fresh = sum(1 for last in seen.values() if when - last <= self.wide_pause)
        return fresh if fresh >= self.wide_venues else 0

    def drifting(self, feed: str, now: float | None = None) -> float:
        """Seconds of stand-aside left after a regime change. Zero if none."""
        drifted = self._drifted.get(feed)
        if drifted is None:
            return 0.0
        when = now if now is not None else time.time()
        left = self.drift_pause - (when - drifted)
        return max(0.0, left)

    # ---------------------------------------------------------------- inside

    def _forget(self, now: float) -> None:
        """Drop rows whose window has closed, so the calendar cannot grow."""
        cutoff = now - self.after - 3_600
        stale = [key for key, release in self._events.items() if release.when < cutoff]
        for key in stale:
            del self._events[key]

    def upcoming(self, now: float | None = None) -> list[Release]:
        when = now if now is not None else time.time()
        return sorted((r for r in self._events.values() if r.when >= when), key=lambda r: r.when)


def _median(ordered: list[float]) -> float:
    """Median of an already-sorted list. Robust to the one venue gone wrong,
    which is the entire reason a median is used rather than a mean."""
    count = len(ordered)
    if not count:
        return 0.0
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0
