"""How a node builds the news client."""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.live.factories import LiveDataClientFactory
from nautilus_trader.model.identifiers import ClientId

from .client import NewsDataClient, NewsDataClientConfig

NEWS = "NEWS"


class NewsLiveDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: NewsDataClientConfig,
        msgbus: Any,
        cache: Any,
        clock: Any,
    ) -> NewsDataClient:
        return NewsDataClient(
            loop=loop,
            client_id=ClientId(name or NEWS),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
