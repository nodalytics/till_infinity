"""Value types shared by every price source.

Sources speak different dialects (TradingView resolution codes, Yahoo interval
strings), so the source modules own their own code maps. Everything that leaves
a source is expressed with the types below.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def slugify(value: str) -> str:
    """Filesystem-safe form of a venue or ticker (``GC=F`` -> ``GC_F``)."""
    return _SLUG_RE.sub("_", value).strip("_").upper()


@dataclass(frozen=True, slots=True)
class Interval:
    """A bar size, identified by its canonical name."""

    name: str
    seconds: int

    def __str__(self) -> str:
        return self.name


INTERVALS: dict[str, Interval] = {
    "1m": Interval("1m", 60),
    "3m": Interval("3m", 180),
    "5m": Interval("5m", 300),
    "15m": Interval("15m", 900),
    "1h": Interval("1h", 3_600),
    "2h": Interval("2h", 7_200),
    "4h": Interval("4h", 14_400),
    "1d": Interval("1d", 86_400),
    "1w": Interval("1w", 604_800),
}

DEFAULT_INTERVALS: tuple[str, ...] = tuple(INTERVALS)


def resolve_intervals(names: Sequence[str] | None) -> tuple[Interval, ...]:
    """Map interval names to `Interval`s, raising on anything unknown."""
    if not names:
        return tuple(INTERVALS.values())
    unknown = [n for n in names if n not in INTERVALS]
    if unknown:
        raise ValueError(
            f"unknown interval(s): {', '.join(unknown)} (have: {', '.join(INTERVALS)})"
        )
    return tuple(INTERVALS[n] for n in names)


@dataclass(frozen=True, slots=True)
class Symbol:
    """A ticker at a venue - ``OANDA:XAUUSD``, ``YAHOO:GC=F``."""

    venue: str
    ticker: str

    @classmethod
    def parse(cls, raw: str, default_venue: str = "UNKNOWN") -> Self:
        venue, sep, ticker = raw.partition(":")
        if not sep:
            return cls(default_venue, venue)
        return cls(venue, ticker)

    @property
    def full(self) -> str:
        return f"{self.venue}:{self.ticker}"

    @property
    def slug(self) -> str:
        return f"{slugify(self.venue)}_{slugify(self.ticker)}"

    def __str__(self) -> str:
        return self.full


@dataclass(frozen=True, slots=True)
class SeriesKey:
    """Identity of one stored candle series."""

    source: str
    feed: str
    symbol: Symbol
    interval: str

    @property
    def slug(self) -> str:
        return f"{self.feed}_{self.symbol.slug}_{self.interval}"

    def __str__(self) -> str:
        return f"{self.feed} {self.symbol.full} {self.interval}"


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV candle. `time` is the bar's *open* time, epoch seconds UTC."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    @classmethod
    def from_series(cls, values: Any) -> Self | None:
        """Build from a TradingView ``v`` array; return None if malformed."""
        if not isinstance(values, list | tuple) or len(values) < 5:
            return None
        try:
            time = int(values[0])
            open_, high, low, close = (float(x) for x in values[1:5])
        except (TypeError, ValueError):
            return None
        volume: float | None = None
        if len(values) > 5:
            try:
                volume = float(values[5])
            except (TypeError, ValueError):
                volume = None
        return cls(time, open_, high, low, close, volume)

    def close_time(self, interval: Interval) -> int:
        return self.time + interval.seconds

    def is_closed(self, interval: Interval, now: float) -> bool:
        """A bar is final once its window has elapsed; until then it still moves."""
        return self.close_time(interval) <= now

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.time,
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "v": self.volume,
        }


@dataclass(frozen=True, slots=True)
class QuoteKey:
    """Identity of one realtime quote stream (a symbol at a source)."""

    source: str
    feed: str
    symbol: Symbol

    @property
    def slug(self) -> str:
        return f"{self.feed}_{self.symbol.slug}"

    def __str__(self) -> str:
        return f"{self.feed} {self.symbol.full}"


@dataclass(frozen=True, slots=True)
class Quote:
    """A top-of-book snapshot. `time` is when it was observed, epoch seconds."""

    time: float
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    change: float | None = None
    change_pct: float | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return self.last
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float | None:
        """Spread in basis points of mid - the cross-broker comparable."""
        spread, mid = self.spread, self.mid
        if spread is None or not mid:
            return None
        return spread / mid * 10_000

    @property
    def is_empty(self) -> bool:
        return self.bid is None and self.ask is None and self.last is None

    def same_price_as(self, other: Quote | None) -> bool:
        """True when nothing tradable moved - used to skip redundant writes."""
        if other is None:
            return False
        return (self.bid, self.ask, self.last) == (other.bid, other.ask, other.last)

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.time,
            "bid": self.bid,
            "ask": self.ask,
            "lp": self.last,
            "mid": self.mid,
            "spread": self.spread,
            "v": self.volume,
            "ch": self.change,
            "chp": self.change_pct,
        }


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What a store did with a batch of bars."""

    inserted: int = 0
    updated: int = 0

    @property
    def touched(self) -> int:
        return self.inserted + self.updated

    def __add__(self, other: WriteResult) -> WriteResult:
        return WriteResult(self.inserted + other.inserted, self.updated + other.updated)


@dataclass(frozen=True, slots=True)
class PruneResult:
    """What retention removed, and whether the file was rebuilt afterwards.

    `kept` is reported alongside `deleted` on purpose: a prune that deleted a
    great many rows and a prune that emptied the table read the same from the
    deletion count alone.
    """

    deleted: int = 0
    kept: int = 0
    vacuumed: bool = False

    def __str__(self) -> str:
        rebuilt = ", file rebuilt" if self.vacuumed else ", file not shrunk (pass --vacuum)"
        return f"dropped {self.deleted:,} bars, kept {self.kept:,}{rebuilt}"


@dataclass(frozen=True, slots=True)
class SeriesInfo:
    """Summary of a stored series, for `prices info`."""

    key: SeriesKey
    bars: int
    first_time: int | None
    last_time: int | None
