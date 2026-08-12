"""The contract a destination implements, and the failure classes around it.

A notifier is bound to one *channel*, not one provider: sending to four
Telegram chats means four notifiers sharing a token. That keeps a per-channel
failure per-channel — a deleted webhook cannot take the other three with it.

Both providers rate-limit with a 429 carrying the exact number of seconds to
wait. Honouring that number is the difference between a delivered alert and a
backoff schedule fighting the server's own.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Self

import httpx

from .config import Settings
from .models import Channel, Delivery, Notification


class NotifierError(Exception):
    """Base for delivery failures."""


class NotConfiguredError(NotifierError):
    """No credentials for this destination."""


class PermanentError(NotifierError):
    """Bad token, unknown chat, deleted webhook — retrying cannot help."""


class TransientError(NotifierError):
    """Timeout, 5xx, or a rate limit. Worth another attempt."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        #: Seconds the provider asked us to wait, when it said so.
        self.retry_after = retry_after


class Notifier(ABC):
    """Sends notifications to one channel."""

    target: ClassVar[str]

    def __init__(self, settings: Settings, channel: Channel | None = None) -> None:
        self.settings = settings
        self.channel = channel or Channel(target=self.target, address="")
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return self.channel.name

    @property
    @abstractmethod
    def ready(self) -> bool:
        """True when this channel has the credentials it needs."""

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.settings.timeout))
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(f"{self.name} notifier is not open")
        return self._client

    async def post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        """POST JSON, translating transport and status failures."""
        try:
            response = await self.client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise TransientError(f"{self.name}: {exc}") from exc
        return self.checked(response)

    def checked(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise TransientError(
                f"{self.name}: rate limited", retry_after=self.retry_after(response)
            )
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise TransientError(f"{self.name}: HTTP {response.status_code}")
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise PermanentError(
                f"{self.name}: HTTP {response.status_code} {self.reason(response)}"
            )
        return response

    def retry_after(self, response: httpx.Response) -> float | None:
        """Seconds to wait, from whichever place the provider put it."""
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(float(header), self.settings.max_retry_after)
            except ValueError:
                pass
        try:
            body = response.json()
        except ValueError:
            return None
        for key in ("retry_after", "parameters"):
            value = body.get(key) if isinstance(body, dict) else None
            if isinstance(value, dict):
                value = value.get("retry_after")
            if isinstance(value, int | float):
                return min(float(value), self.settings.max_retry_after)
        return None

    def reason(self, response: httpx.Response) -> str:
        """A short server-supplied explanation, if there is one."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:120]
        if isinstance(body, dict):
            for key in ("description", "message", "error"):
                if body.get(key):
                    return str(body[key])[:120]
        return str(body)[:120]

    @abstractmethod
    async def send(self, notification: Notification) -> Delivery:
        """Deliver one notification to this channel."""
