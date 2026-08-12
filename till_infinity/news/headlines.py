"""TradingView headlines — the feed behind its own news pane.

Worth having alongside the RSS feeds because it is *symbol-attached*: a story
arrives already tagged with the instruments it concerns, so gold headlines can
be lined up against the gold series without a keyword search. Each item also
carries provider attribution (Reuters, and so on) and an urgency flag.

Both shapes of the endpoint are polled: one request per watched symbol, plus
the broad per-category feeds for stories tied to no single instrument.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..logging import get_logger
from .config import (
    HEADLINE_CATEGORIES,
    HEADLINE_SYMBOLS,
    TRADINGVIEW_HEADLINES_URL,
    TRADINGVIEW_ORIGIN,
    Settings,
)
from .models import Article, Batch, clean, digest
from .source import PermanentError, Source, TransientError

log = get_logger(__name__)

STORY_BASE = "https://www.tradingview.com"

#: The endpoint pools stories by category, and the venue prefix implies it.
_CRYPTO_VENUES = frozenset({"BINANCE", "COINBASE", "BITFINEX", "KRAKEN", "BITSTAMP", "BYBIT"})
_FOREX_VENUES = frozenset({"FX", "FOREX", "OANDA", "FX_IDC", "PEPPERSTONE", "SAXO", "FOREXCOM"})


def category_for(symbol: str) -> str:
    """Which pool a symbol's news lives in."""
    venue = symbol.split(":", 1)[0].upper() if ":" in symbol else ""
    if venue in _CRYPTO_VENUES:
        return "crypto"
    if venue in _FOREX_VENUES:
        return "forex"
    return "stock"


def parse_headlines(payload: Any, *, fallback_symbol: str = "") -> list[Article]:
    """Map a headlines response onto articles."""
    if not isinstance(payload, dict):
        raise PermanentError("tradingview headlines: unexpected response")
    items = payload.get("items")
    if not isinstance(items, list):
        raise PermanentError(f"tradingview headlines: {str(payload)[:80]}")

    articles: list[Article] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = clean(item.get("title"))
        if not title:
            continue
        related = tuple(
            str(r.get("symbol"))
            for r in item.get("relatedSymbols") or []
            if isinstance(r, dict) and r.get("symbol")
        )
        story = str(item.get("storyPath") or "")
        articles.append(
            Article(
                source="tradingview",
                id=str(item.get("id") or digest(title, item.get("published"))),
                title=title,
                url=f"{STORY_BASE}{story}" if story.startswith("/") else story,
                published=_epoch(item.get("published")),
                provider=str(item.get("source") or item.get("provider") or ""),
                symbols=related or ((fallback_symbol,) if fallback_symbol else ()),
                urgency=_int(item.get("urgency")),
            )
        )
    return articles


def _epoch(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


class HeadlineSource(Source):
    """TradingView headlines for the watched symbols and categories."""

    name = "headlines"

    def __init__(
        self,
        settings: Settings,
        symbols: tuple[str, ...] | None = None,
        categories: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(settings)
        self.symbols = tuple(symbols if symbols is not None else HEADLINE_SYMBOLS)
        self.categories = tuple(categories if categories is not None else HEADLINE_CATEGORIES)

    def headers(self) -> dict[str, str]:
        return {
            **super().headers(),
            "Origin": TRADINGVIEW_ORIGIN,
            "Referer": f"{TRADINGVIEW_ORIGIN}/",
        }

    async def poll(self) -> Batch:
        limit = asyncio.Semaphore(max(1, self.settings.concurrency))
        batch = Batch()

        async def fetch(params: dict[str, str], label: str, symbol: str = "") -> None:
            async with limit:
                try:
                    response = await self.get(TRADINGVIEW_HEADLINES_URL, params=params)
                    batch.articles.extend(parse_headlines(response.json(), fallback_symbol=symbol))
                except (PermanentError, TransientError, ValueError) as exc:
                    log.warning("headlines %s: %s", label, exc)

        async with asyncio.TaskGroup() as group:
            for symbol in self.symbols:
                group.create_task(
                    fetch(
                        {
                            "symbol": symbol,
                            "category": category_for(symbol),
                            "client": "web",
                            "lang": "en",
                        },
                        symbol,
                        symbol,
                    )
                )
            for category in self.categories:
                group.create_task(
                    fetch({"category": category, "client": "web", "lang": "en"}, category)
                )
        return batch
