"""Constructed spreads, as instruments the rest of the desk cannot tell apart.

Everything downstream of this package reads bars out of the store and knows
nothing about where they came from: `structures` builds levels from whatever
`SELECT DISTINCT feed FROM bars` returns, `vol` measures it, `zma` scores it,
`trading` reads the signals off the bus. So a constructed series only has to be
**written like any other feed** and the whole machine works on it unchanged.

## Why build these at all

[`research/zma.md`](../../research/zma.md) is the reason. The attention-weighted
z-score is a working mean-reversion detector - AUC 0.62 on a graded
Ornstein-Uhlenbeck control - measuring 0.49 to 0.52 on every outright price this
desk follows, because `generators.md` has the synthetics at `H = 0.50` and a
random walk has no mean to return to. On **constructed cross-venue spreads** the
same detector scores **AUC 0.67 to 0.73 and hit 78.7% to 83.7%**.

[`adapting.md`](../../research/adapting.md) says the same thing from the other
end: a mixture that can decline to bet puts 0.86 to 0.998 of its weight on
saying nothing across every family the desk trades. The machinery is sound and
the input is wrong. This is the input.

## Two kinds, and only one of them is tradeable

**`venue`** - the same asset at two venues, weighted `+1` and `-1` in logs. It
reverts **by arbitrage** rather than by hope: BTC at Binance and at Kraken
cannot drift apart without somebody closing it. It needs no model and no fitted
ratio, which is why it is the clean case.

It is also **not tradeable by this account**, and saying so is the point of
`Spread.tradeable`. Holding it means a position at each venue, and this desk has
one broker. `crossing.md` already measured what that costs from the other
direction: 90.2% of cross-venue deviations belong to a venue the desk cannot
hold. These are built to be *measured*, so the AUC above can be confirmed on
stored bars rather than on the six pairs one harness happened to construct.

**`cross`** - two USD pairs at **one** venue, which is an implied cross exactly:
`ln(EURUSD) - ln(GBPUSD) = ln(EURGBP)`, no residual and no hedge ratio. This one
**is** tradeable - two orders at one broker - and it is a genuinely new
instrument rather than a reverting residual. It costs two spreads to hold, which
is the question worth asking about it and is not answered here.

## What is exact here, and what is not

**Open and close are exact.** Both legs' opens are at the bar's open time and
both closes at its close, so the weighted log sum is the spread at that instant.

**High and low are not**, and cannot be: each leg's extreme happened at an
unknown instant inside the bar, and pairing them would assume they coincided.
So the range is built **from a finer interval where one exists** - the coarse
bar's high is the highest the constructed spread was seen at across the fine
bars inside it - and falls back to `max(open, close)` at the finest interval
available. That fallback understates the range, which matters because
`rogers_satchell_bps` is what `har.py` forecasts from; it is recorded in
`Built.exact_range` rather than left for somebody to discover.

**A missing leg drops the bucket.** Never forward-filled. Carrying one leg
forward while the other moves manufactures a spread move that did not happen,
and on a series whose entire content is the difference between two nearly equal
numbers that is not a small error - it is the signal.

**One source per spread, by default.** A leg from TradingView and a leg from
Yahoo are two different clocks: `lagging.md` measured that every quote timestamp
stored here is our own receive clock, and a cross-source spread measures the
skew between them as well as the price. `cross_source=True` allows it for the
cases where there is no alternative, and the built series says which it was.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..logging import get_logger
from .config import FEEDS, Feed
from .models import Bar, Symbol

log = get_logger(__name__)

#: The level a spread of zero maps to. The series published is
#: `BASE * exp(sum of weighted log legs)`, so its **log returns are the spread's
#: own increments exactly** - which is what every downstream estimator reads.
#: An affine map like `100 + spread * 100` would be easier and would distort
#: every relative quantity computed from it.
BASE = 100.0

#: How constructed series are identified in the store. The source is what marks
#: them as derived; the venue is a constant because a spread does not have one.
SOURCE = "spread"
VENUE = "SPREAD"

#: Shared bars a pair needs before it is worth constructing. Below this the
#: overlap is an accident of when two collectors happened to be running.
MIN_SHARED = 1_000

#: Venues whose quotes this desk can actually hold a position at. A spread whose
#: legs all sit inside this set is tradeable as two orders on one account;
#: anything else is an observation. Deliberately a small set that has to be
#: edited by hand - guessing wrong here is how a study becomes a trade.
TRADEABLE_VENUES = frozenset({"DERIV", "PEPPERSTONE"})


@dataclass(frozen=True, slots=True)
class Leg:
    """One instrument at one venue, with its weight **in log space**.

    `source` and `ticker` are carried because the store's only index on `bars`
    is `(source, venue, ticker, interval, ts)`, and a query naming the feed
    instead of those three scans the whole index rather than seeking into it.
    They are discovered rather than configured: `venue_pairs` and `crosses`
    read them out of the store, and a leg without them still reads correctly
    through the slower query.
    """

    feed: str
    venue: str
    weight: float = 1.0
    source: str = ""
    ticker: str = ""

    def __str__(self) -> str:
        sign = "+" if self.weight >= 0 else "-"
        return f"{sign}{abs(self.weight):g}*{self.feed}@{self.venue}"

    @property
    def indexed(self) -> bool:
        """Whether this leg can be read through the store's index."""
        return bool(self.source and self.ticker)


@dataclass(frozen=True, slots=True)
class Spread:
    """A constructed series, named and defined by its legs."""

    name: str
    legs: tuple[Leg, ...]
    kind: str = "venue"
    note: str = ""

    @property
    def tradeable(self) -> bool:
        """Can one account hold the whole thing.

        Every leg at one venue **and** that venue one the desk trades. Two legs
        at two venues is two accounts, which this desk does not have, however
        attractive the series looks.
        """
        venues = {leg.venue for leg in self.legs}
        return len(venues) == 1 and venues <= TRADEABLE_VENUES

    @property
    def ticker(self) -> str:
        return "/".join(f"{'+' if leg.weight >= 0 else '-'}{leg.feed}" for leg in self.legs)

    @property
    def symbol(self) -> Symbol:
        return Symbol(VENUE, self.ticker)

    @property
    def feeds(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(leg.feed for leg in self.legs))

    def as_feed(self) -> Feed:
        return Feed(name=self.name, symbols={SOURCE: (self.symbol,)})

    def price(self, closes: Sequence[float]) -> float | None:
        """`BASE * exp(sum of w_i * ln p_i)`, or None if any leg is unusable."""
        total = 0.0
        for leg, price in zip(self.legs, closes, strict=True):
            if price is None or price <= 0:
                return None
            total += leg.weight * math.log(price)
        # A weighting that lands far from zero is a definition error, not a
        # market move: guarding it here stops an overflow becoming a price.
        if not -50.0 < total < 50.0:
            return None
        return BASE * math.exp(total)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "legs": [str(leg) for leg in self.legs],
            "tradeable": self.tradeable,
            "note": self.note,
        }


@dataclass(slots=True)
class Built:
    """One constructed series, and what is true about how it was made."""

    spread: Spread
    interval: str
    bars: list[Bar] = field(default_factory=list)
    #: Whether the high and low are real extremes of the constructed series or
    #: only `max`/`min` of the two exact endpoints. False means every
    #: range-based estimator reading this understates - see the module note.
    exact_range: bool = False
    #: The interval the spread was actually computed at before aggregation.
    built_from: str = ""
    #: Buckets dropped because a leg had no bar there. Reported rather than
    #: swallowed: a pair that drops most of its buckets is not a spread, it is
    #: two series that were rarely collected at the same time.
    dropped: int = 0
    cross_source: bool = False

    def __str__(self) -> str:
        return (
            f"{self.spread.name} {self.interval}: {len(self.bars)} bars "
            f"from {self.built_from}, {self.dropped} dropped"
            f"{'' if self.exact_range else ', range is endpoints only'}"
        )


# ------------------------------------------------------------------ discovery


def _cells(conn: sqlite3.Connection) -> list[tuple[str, str, str, str, str, int]]:
    """`(feed, venue, source, ticker, interval, n)` for every stored series."""
    return list(
        conn.execute(
            "SELECT feed, venue, source, ticker, interval, COUNT(*) n FROM bars"
            " GROUP BY feed, venue, source, ticker, interval"
        )
    )


def venue_pairs(
    conn: sqlite3.Connection,
    *,
    interval: str = "1m",
    feeds: Iterable[str] | None = None,
    min_shared: int = MIN_SHARED,
    cross_source: bool = False,
) -> list[Spread]:
    """Every same-asset two-venue pair the store can actually build.

    Counted from the stored cells rather than probed, and the `min_shared`
    bound is on each leg's own bar count - a cheap upper bound on the overlap,
    checked properly by `build`, which is where the inner join happens.
    """
    wanted = set(feeds) if feeds else None
    by_feed: dict[str, dict[str, tuple[str, str, int]]] = {}
    for feed, venue, source, ticker, got_interval, n in _cells(conn):
        if got_interval != interval or n < min_shared:
            continue
        if wanted is not None and feed not in wanted:
            continue
        # One venue can carry one feed under two tickers. Kept on the deeper of
        # them, because two legs of the same asset at the same venue is not a
        # spread and would otherwise be built as one.
        held = by_feed.setdefault(feed, {}).get(venue)
        if held is None or n > held[2]:
            by_feed[feed][venue] = (source, ticker, n)

    out: list[Spread] = []
    for feed, cells in sorted(by_feed.items()):
        ordered = sorted(cells)
        for i, venue_a in enumerate(ordered):
            source_a, ticker_a, _ = cells[venue_a]
            for venue_b in ordered[i + 1 :]:
                source_b, ticker_b, _ = cells[venue_b]
                if not cross_source and source_a != source_b:
                    continue
                out.append(
                    Spread(
                        name=slug(f"{feed} {venue_a} {venue_b}"),
                        legs=(
                            Leg(feed, venue_a, 1.0, source_a, ticker_a),
                            Leg(feed, venue_b, -1.0, source_b, ticker_b),
                        ),
                        kind="venue",
                        note=f"{feed} at {venue_a} against {venue_b}",
                    )
                )
    return out


#: The implied crosses worth carrying, as `(name, numerator, denominator)` over
#: the USD pairs this desk already follows. `ln(A/USD) - ln(B/USD)` is `ln(A/B)`
#: exactly, so these are instruments and not residuals - no ratio is fitted and
#: nothing is assumed to revert.
#:
#: The JPY and CHF crosses are inverted relative to the others because those
#: pairs are quoted USD-first: `ln(USDJPY) - ln(USDCAD)` is `ln(CADJPY)`.
CROSSES: tuple[tuple[str, str, str], ...] = (
    ("eurgbp", "eurusd", "gbpusd"),
    ("euraud", "eurusd", "audusd"),
    ("eurnzd", "eurusd", "nzdusd"),
    ("gbpaud", "gbpusd", "audusd"),
    ("gbpnzd", "gbpusd", "nzdusd"),
    ("audnzd", "audusd", "nzdusd"),
    ("cadjpy", "usdjpy", "usdcad"),
    ("chfjpy", "usdjpy", "usdchf"),
    ("cadchf", "usdchf", "usdcad"),
)


def crosses(
    conn: sqlite3.Connection,
    *,
    interval: str = "1m",
    min_shared: int = MIN_SHARED,
    venues: Iterable[str] | None = None,
) -> list[Spread]:
    """Implied FX crosses, one venue per spread, from the pairs already stored.

    One venue because these are meant to be **held**: two legs at one broker is
    two orders on one account, and two legs at two brokers is not a trade.
    """
    allowed = set(venues) if venues else set(TRADEABLE_VENUES)
    have: dict[tuple[str, str], tuple[str, str, int]] = {}
    for feed, venue, source, ticker, got_interval, n in _cells(conn):
        if got_interval != interval:
            continue
        held = have.get((feed, venue))
        if held is None or n > held[2]:
            have[(feed, venue)] = (source, ticker, n)

    out: list[Spread] = []
    for name, top, bottom in CROSSES:
        for venue in sorted(allowed):
            over, under = have.get((top, venue)), have.get((bottom, venue))
            if over is None or under is None:
                continue
            if over[2] < min_shared or under[2] < min_shared:
                continue
            out.append(
                Spread(
                    name=slug(f"{name} {venue}"),
                    legs=(
                        Leg(top, venue, 1.0, over[0], over[1]),
                        Leg(bottom, venue, -1.0, under[0], under[1]),
                    ),
                    kind="cross",
                    note=f"{name} implied by {top}/{bottom} at {venue}",
                )
            )
    return out


def slug(text: str) -> str:
    """Feed names travel through journal keys and log lines. No spaces."""
    return "_".join(part for part in text.lower().replace("/", " ").split() if part)


# --------------------------------------------------------------- construction


def _leg_bars(
    conn: sqlite3.Connection, leg: Leg, interval: str, since: int
) -> dict[int, tuple[float, float]]:
    """`ts -> (open, close)` for one leg. Extremes are deliberately not read.

    A leg's high and low cannot be combined into the spread's - they happened at
    unknown instants - so reading them would only make it easy to.
    """
    if leg.indexed:
        # Seeks into `bars_series_ts` rather than scanning it. See `Leg`.
        rows = conn.execute(
            "SELECT ts, open, close FROM bars"
            " WHERE source=? AND venue=? AND ticker=? AND interval=? AND ts>=?"
            " AND open>0 AND close>0",
            (leg.source, leg.venue, leg.ticker, interval, since),
        )
    else:
        rows = conn.execute(
            "SELECT ts, open, close FROM bars"
            " WHERE feed=? AND venue=? AND interval=? AND ts>=? AND open>0 AND close>0",
            (leg.feed, leg.venue, interval, since),
        )
    return {int(ts): (float(o), float(c)) for ts, o, c in rows}


def construct(
    conn: sqlite3.Connection,
    spread: Spread,
    interval: str,
    *,
    since: int = 0,
    limit: int = 0,
) -> Built:
    """The spread at `interval`, from the legs' own bars at that interval.

    Endpoints exact, range from the endpoints only. `aggregate` is the version
    to prefer wherever a finer interval exists.
    """
    legs = [_leg_bars(conn, leg, interval, since) for leg in spread.legs]
    if not legs or any(not got for got in legs):
        return Built(spread, interval, built_from=interval)
    shared = set(legs[0])
    for got in legs[1:]:
        shared &= set(got)
    stamps = sorted(shared)
    if limit > 0:
        stamps = stamps[-limit:]

    bars: list[Bar] = []
    for ts in stamps:
        opened = spread.price([got[ts][0] for got in legs])
        closed = spread.price([got[ts][1] for got in legs])
        if opened is None or closed is None:
            continue
        bars.append(
            Bar(
                time=ts,
                open=opened,
                high=max(opened, closed),
                low=min(opened, closed),
                close=closed,
                # Not a count of anything. A spread has no volume, and
                # inventing one would be read downstream as activity.
                volume=None,
            )
        )
    widest = max((len(got) for got in legs), default=0)
    return Built(
        spread=spread,
        interval=interval,
        bars=bars,
        exact_range=False,
        built_from=interval,
        dropped=max(0, widest - len(bars)),
        cross_source=False,
    )


def aggregate(
    conn: sqlite3.Connection,
    spread: Spread,
    interval: str,
    *,
    base: str,
    seconds: int,
    since: int = 0,
    limit: int = 0,
) -> Built:
    """The spread at `interval`, built at `base` and bucketed up to it.

    **This is the version whose high and low mean something.** The coarse bar's
    extremes are the highest and lowest the constructed spread was actually
    seen at inside the bucket, which is exactly how every other bar in the
    store understates its own range - by the resolution it was sampled at, not
    by an assumption that two legs peaked together.
    """
    fine = construct(conn, spread, base, since=since)
    if not fine.bars:
        return Built(spread, interval, built_from=base)

    buckets: dict[int, list[Bar]] = {}
    for bar in fine.bars:
        buckets.setdefault(bar.time - (bar.time % seconds), []).append(bar)

    stamps = sorted(buckets)
    if limit > 0:
        stamps = stamps[-limit:]
    bars = []
    for ts in stamps:
        inside = sorted(buckets[ts], key=lambda b: b.time)
        bars.append(
            Bar(
                time=ts,
                open=inside[0].open,
                high=max(b.high for b in inside),
                low=min(b.low for b in inside),
                close=inside[-1].close,
                volume=None,
            )
        )
    return Built(
        spread=spread,
        interval=interval,
        bars=bars,
        exact_range=True,
        built_from=base,
        dropped=fine.dropped,
    )


def register(spreads: Sequence[Spread]) -> tuple[str, ...]:
    """Add these to the feed catalogue, and report the ones that were new.

    Mutating `FEEDS` for the same reason `register_broker_feeds` does: it is
    what `resolve_feeds` and every alias lookup read, and a parallel registry
    would be a second place for a feed to exist and a second place to forget to
    look.
    """
    added = []
    for spread in spreads:
        if spread.name in FEEDS:
            continue
        FEEDS[spread.name] = spread.as_feed()
        _CONSTRUCTED[spread.name] = spread
        added.append(spread.name)
    return tuple(added)


#: Constructed feeds, by name, so a consumer can ask what a feed is made of.
#: `trading` needs this to know a spread is two orders and not one.
_CONSTRUCTED: dict[str, Spread] = {}


def constructed() -> dict[str, Spread]:
    return dict(_CONSTRUCTED)


def definition(feed: str) -> Spread | None:
    """What this feed is made of, or None if it is an ordinary instrument."""
    return _CONSTRUCTED.get(feed)


def catalogue(
    conn: sqlite3.Connection,
    *,
    kinds: Sequence[str] = ("cross",),
    interval: str = "1m",
    min_shared: int = MIN_SHARED,
    cross_source: bool = False,
    feeds: Iterable[str] | None = None,
    venues: Iterable[str] | None = None,
) -> list[Spread]:
    """Every spread of the requested kinds that this store can actually build.

    One entry point for the service and the CLI, so what gets collected and what
    gets listed cannot drift apart - which is how a feed ends up being watched
    by one half of the desk and unknown to the other.
    """
    wanted = {k.strip().lower() for k in kinds if k.strip()}
    out: list[Spread] = []
    if "cross" in wanted:
        out.extend(crosses(conn, interval=interval, min_shared=min_shared, venues=venues))
    if "venue" in wanted:
        out.extend(
            venue_pairs(
                conn,
                interval=interval,
                feeds=feeds,
                min_shared=min_shared,
                cross_source=cross_source,
            )
        )
    unknown = wanted - {"cross", "venue"}
    if unknown:
        log.warning("prices: no such spread kind: %s", ", ".join(sorted(unknown)))
    return out
