"""The contract every news or calendar source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Self

import httpx

from .config import Settings
from .models import Batch


class SourceError(Exception):
    """Base for source failures."""


class PermanentError(SourceError):
    """A dead feed or a rejected request — retrying will not help."""


class TransientError(SourceError):
    """Timeout, disconnect, throttle — worth another attempt."""


class Source(ABC):
    """Polls one provider and returns whatever is new."""

    name: ClassVar[str]
    #: Calendars change slowly; headline feeds do not. The service uses this to
    #: decide which clock a source runs on.
    slow: ClassVar[bool] = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    def headers(self) -> dict[str, str]:
        return {"User-Agent": self.settings.user_agent}

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            headers=self.headers(),
            timeout=httpx.Timeout(self.settings.timeout),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(f"{self.name} source is not open")
        return self._client

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        """One GET, with transport failures translated into TransientError."""
        try:
            response = await self.client.get(url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            raise TransientError(f"{url}: {exc}") from exc
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise TransientError(f"{url}: HTTP {response.status_code}")
        if response.status_code != httpx.codes.OK:
            raise PermanentError(f"{url}: HTTP {response.status_code}")
        return response

    @abstractmethod
    async def poll(self) -> Batch:
        """Fetch the current state of this source."""
