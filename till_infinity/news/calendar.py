"""Economic calendars, from two providers that disagree usefully.

ForexFactory publishes a flat weekly JSON keyed by currency; TradingView's
calendar service is keyed by country and carries `importance` plus raw numeric
fields. Both are stored, keyed by source, so a print can be cross-checked
between them the same way a price is cross-checked between brokers.

Neither is fetched once and forgotten. An event exists for days as a forecast
and only gains its `actual` at the moment of release, so the window is
re-polled and rows are rewritten in place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging import get_logger
from .config import (
    CALENDAR_COUNTRIES,
    CALENDAR_CURRENCIES,
    FOREXFACTORY_URLS,
    TRADINGVIEW_CALENDAR_URL,
    TRADINGVIEW_ORIGIN,
)
from .models import Batch, Event, clean, digest, parse_importance, parse_time
from .source import PermanentError, Source, TransientError

log = get_logger(__name__)


def _str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value).strip()


def parse_forexfactory(rows: Any, currencies: tuple[str, ...] | None = None) -> list[Event]:
    """Map ForexFactory's weekly JSON onto events."""
    if not isinstance(rows, list):
        raise PermanentError("forexfactory: expected a list of events")
    keep = set(currencies or CALENDAR_CURRENCIES)
    events: list[Event] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        country = str(row.get("country") or "").upper()
        if keep and country not in keep:
            continue
        title = clean(row.get("title"))
        when = row.get("date")
        if not title:
            continue
        events.append(
            Event(
                source="forexfactory",
                # No id in the feed, so one is derived from what identifies it.
                id=digest(title, country, when),
                title=title,
                country=country,
                time=parse_time(when),
                importance=parse_importance(row.get("impact")),
                actual=_str(row.get("actual")),
                forecast=_str(row.get("forecast")),
                previous=_str(row.get("previous")),
            )
        )
    return events


def parse_tradingview(payload: Any) -> list[Event]:
    """Map TradingView's calendar response onto events."""
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise PermanentError(f"tradingview calendar: {str(payload)[:80]}")
    events: list[Event] = []
    for row in payload.get("result") or []:
        if not isinstance(row, dict):
            continue
        title = clean(row.get("title") or row.get("indicator"))
        if not title:
            continue
        events.append(
            Event(
                source="tradingview",
                id=str(row.get("id") or digest(title, row.get("country"), row.get("date"))),
                title=title,
                country=str(row.get("country") or "").upper(),
                time=parse_time(row.get("date")),
                importance=parse_importance(row.get("importance")),
                actual=_str(row.get("actual")),
                forecast=_str(row.get("forecast")),
                previous=_str(row.get("previous")),
                unit=str(row.get("unit") or ""),
                period=str(row.get("period") or ""),
            )
        )
    return events


class ForexFactoryCalendar(Source):
    """This week and next, from ForexFactory's public JSON."""

    name = "forexfactory"
    slow = True

    async def poll(self) -> Batch:
        batch = Batch()
        for url in FOREXFACTORY_URLS:
            try:
                response = await self.get(url)
                batch.events.extend(parse_forexfactory(response.json()))
            except (PermanentError, TransientError, ValueError) as exc:
                log.warning("forexfactory %s: %s", url.rsplit("/", 1)[-1], exc)
        return batch


class TradingViewCalendar(Source):
    """A rolling window from TradingView's calendar service."""

    name = "tradingview"
    slow = True

    def headers(self) -> dict[str, str]:
        # The service checks the browser origin and 403s without it.
        return {
            **super().headers(),
            "Origin": TRADINGVIEW_ORIGIN,
            "Referer": f"{TRADINGVIEW_ORIGIN}/",
        }

    def window(self, *, now: datetime | None = None) -> tuple[str, str]:
        """The from/to pair, in the exact format TradingView's parser wants."""
        now = now or datetime.now(UTC)
        start = now - timedelta(days=self.settings.calendar_back_days)
        end = now + timedelta(days=self.settings.calendar_forward_days)
        return (_stamp(start), _stamp(end))

    async def poll(self) -> Batch:
        start, end = self.window()
        response = await self.get(
            TRADINGVIEW_CALENDAR_URL,
            params={
                "from": start,
                "to": end,
                "countries": ",".join(CALENDAR_COUNTRIES),
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PermanentError(f"tradingview calendar: {exc}") from exc
        return Batch(events=parse_tradingview(payload))


def _stamp(moment: datetime) -> str:
    """``2026-05-06T00:00:00.000Z`` — the literal shape the endpoint requires."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
