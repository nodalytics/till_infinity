"""Headlines from RSS.

Five feeds, polled concurrently. Publishers disagree about everything —
RSS 2.0 versus Atom, `guid` versus `id` versus bare link, tag soup in the
description — so parsing is deliberately forgiving: anything with a title and
something usable as an id becomes an Article, and the rest is skipped rather
than raising.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET

from ..logging import get_logger
from .config import RSS_FEEDS, Settings
from .models import Article, Batch, clean, digest, parse_time
from .source import PermanentError, Source, TransientError

log = get_logger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"


def _text(node: ET.Element, *names: str) -> str:
    """First non-empty child among `names`, trying the Atom namespace too."""
    for name in names:
        for tag in (name, f"{ATOM}{name}"):
            found = node.find(tag)
            if found is not None and (found.text or "").strip():
                return found.text.strip()  # type: ignore[union-attr]
    return ""


def _link(node: ET.Element) -> str:
    direct = _text(node, "link")
    if direct:
        return direct
    # Atom puts the URL in an attribute rather than the element body.
    for tag in ("link", f"{ATOM}link"):
        for element in node.findall(tag):
            href = element.get("href")
            if href:
                return href
    return ""


def parse_feed(source: str, payload: bytes) -> list[Article]:
    """Turn one feed body into articles. Never raises on bad entries."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PermanentError(f"{source}: malformed feed ({exc})") from exc

    articles: list[Article] = []
    entries = list(root.iter("item")) + list(root.iter(f"{ATOM}entry"))
    for entry in entries:
        title = clean(_text(entry, "title"))
        if not title:
            continue
        url = _link(entry)
        ident = _text(entry, "guid", "id") or url or digest(source, title)
        articles.append(
            Article(
                source=source,
                id=ident,
                title=title,
                url=url,
                published=parse_time(_text(entry, "pubDate", "published", "updated")),
                summary=clean(_text(entry, "description", "summary"))[:400],
            )
        )
    return articles


class RssSource(Source):
    """Every configured RSS feed, fetched in parallel."""

    name = "rss"

    def __init__(self, settings: Settings, feeds: dict[str, str] | None = None) -> None:
        super().__init__(settings)
        self.feeds = dict(feeds or RSS_FEEDS)

    async def poll(self) -> Batch:
        limit = asyncio.Semaphore(max(1, self.settings.concurrency))
        batch = Batch()

        async def one(source: str, url: str) -> None:
            async with limit:
                try:
                    response = await self.get(url)
                    batch.articles.extend(parse_feed(source, response.content))
                except (PermanentError, TransientError) as exc:
                    # One dead publisher must not take the other four with it.
                    log.warning("rss %s: %s", source, exc)

        async with asyncio.TaskGroup() as group:
            for source, url in self.feeds.items():
                group.create_task(one(source, url))
        return batch
