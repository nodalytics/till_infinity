"""Value types for headlines and macro events.

Two shapes, because they behave differently. A headline is immutable once
published — it arrives whole and never changes. A calendar event is the
opposite: it exists for days as a forecast, and the number that matters
(`actual`) appears the instant the print lands. Storage has to respect that.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")

#: Calendar providers disagree on wording, so importance is normalised.
LOW, MEDIUM, HIGH = 0, 1, 2

_IMPORTANCE_WORDS = {
    "holiday": LOW,
    "low": LOW,
    "medium": MEDIUM,
    "moderate": MEDIUM,
    "high": HIGH,
}


def clean(text: str | None) -> str:
    """Strip tags and collapse whitespace out of feed-supplied HTML."""
    import html

    if not text:
        return ""
    return _SPACE.sub(" ", _TAGS.sub("", html.unescape(text))).strip()


def digest(*parts: Any) -> str:
    """Stable id for a row a provider gave no id for."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def parse_time(value: Any) -> float | None:
    """Epoch seconds from the several date shapes these feeds emit."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    try:  # ISO-8601, including the literal Z that TradingView sends
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    try:  # RFC 2822, which is what RSS pubDate uses
        return parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError):
        return None


def parse_importance(value: Any) -> int:
    """Map a provider's impact wording or number onto LOW/MEDIUM/HIGH."""
    if isinstance(value, bool):
        return LOW
    if isinstance(value, int | float):
        # TradingView uses -1 low / 0 medium / 1 high.
        return {-1: LOW, 0: MEDIUM, 1: HIGH}.get(int(value), min(max(int(value), LOW), HIGH))
    return _IMPORTANCE_WORDS.get(str(value).strip().lower(), LOW)


def parse_number(value: Any) -> float | None:
    """``"220K"`` / ``"-1.2%"`` / ``"3.5"`` -> float, scaled where suffixed."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    scale = 1.0
    if text and text[-1] in "KMBT":
        scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[text[-1]]
        text = text[:-1]
    try:
        return float(text) * scale
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Article:
    """One headline. Immutable once published."""

    source: str
    id: str
    title: str
    url: str = ""
    published: float | None = None
    provider: str = ""
    summary: str = ""
    symbols: tuple[str, ...] = ()
    urgency: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "published": self.published,
            "provider": self.provider,
            "summary": self.summary,
            "symbols": list(self.symbols),
            "urgency": self.urgency,
        }


@dataclass(frozen=True, slots=True)
class Event:
    """One scheduled macro release.

    `actual` is empty until the print lands, which is the whole point of
    re-polling: the row is rewritten in place the moment the number exists.
    """

    source: str
    id: str
    title: str
    country: str = ""
    time: float | None = None
    importance: int = LOW
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    unit: str = ""
    period: str = ""

    @property
    def released(self) -> bool:
        return self.actual not in (None, "")

    @property
    def surprise(self) -> float | None:
        """Actual minus forecast, once both are numbers. The tradable part."""
        actual, forecast = parse_number(self.actual), parse_number(self.forecast)
        if actual is None or forecast is None:
            return None
        return actual - forecast

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "title": self.title,
            "country": self.country,
            "time": self.time,
            "importance": self.importance,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "unit": self.unit,
            "period": self.period,
            "surprise": self.surprise,
        }


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What a store did with a batch."""

    inserted: int = 0
    updated: int = 0

    @property
    def touched(self) -> int:
        return self.inserted + self.updated

    def __add__(self, other: WriteResult) -> WriteResult:
        return WriteResult(self.inserted + other.inserted, self.updated + other.updated)


@dataclass(frozen=True, slots=True)
class FeedInfo:
    """Summary of what is stored for one source, for `news info`."""

    kind: str
    source: str
    rows: int
    first_time: float | None
    last_time: float | None


@dataclass(slots=True)
class Batch:
    """Whatever one poll of one source produced."""

    articles: list[Article] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.articles) + len(self.events)


def utc(value: float | None) -> datetime | None:
    return None if value is None else datetime.fromtimestamp(value, UTC)
