"""Fan a notification out to every configured channel.

One notifier per channel, all sent at once. A failing channel never blocks
another: each is retried on its own and the call returns a Delivery per
channel rather than raising, because an alert that reached the ops chat but not
the Discord board is a partial success and the caller should see exactly that.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import AsyncExitStack

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging import get_logger
from .config import DEFAULT_TARGETS, Settings
from .discord import DiscordNotifier
from .models import Channel, Delivery, Notification
from .notifier import NotConfiguredError, Notifier, PermanentError, TransientError
from .telegram import TelegramNotifier

log = get_logger(__name__)

NOTIFIERS: dict[str, type[Notifier]] = {
    TelegramNotifier.target: TelegramNotifier,
    DiscordNotifier.target: DiscordNotifier,
}


def build_notifiers(
    names: Sequence[str] | None,
    settings: Settings,
    *,
    channels: Sequence[Channel] | None = None,
) -> list[Notifier]:
    """One notifier per configured channel of each named target."""
    chosen = tuple(names) if names else DEFAULT_TARGETS
    unknown = [n for n in chosen if n not in NOTIFIERS]
    if unknown:
        raise ValueError(f"unknown target(s): {', '.join(unknown)} (have: {', '.join(NOTIFIERS)})")

    built: list[Notifier] = []
    for target in chosen:
        wanted = [c for c in channels if c.target == target] if channels is not None else None
        for channel in wanted if wanted is not None else settings.channels(target):
            notifier = NOTIFIERS[target](settings, channel)
            if notifier.ready:
                built.append(notifier)
    return built


async def discover_telegram_chats(settings: Settings) -> tuple[Channel, ...]:
    """Ask Telegram which chats the bot can post to."""
    async with TelegramNotifier(settings, Channel("telegram", "")) as notifier:
        return await notifier.discover()


async def send_one(notifier: Notifier, notification: Notification, settings: Settings) -> Delivery:
    """Deliver to one channel, retrying transient failures."""
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(1, settings.retries)),
            wait=wait_exponential_jitter(initial=1.0, max=settings.max_retry_after),
            retry=retry_if_exception_type(TransientError),
            reraise=True,
        ):
            with attempt:
                return await notifier.send(notification)
    except TransientError as exc:
        # The provider told us how long to wait and we ran out of attempts.
        detail = str(exc) + (f", retry after {exc.retry_after}s" if exc.retry_after else "")
        log.warning("%s: %s", notifier.name, detail)
        return Delivery(notifier.name, ok=False, detail=detail)
    except (PermanentError, NotConfiguredError) as exc:
        log.warning("%s: %s", notifier.name, exc)
        return Delivery(notifier.name, ok=False, detail=str(exc))
    except Exception as exc:  # a channel must not take the process with it
        log.warning("%s: unexpected failure: %s", notifier.name, exc)
        return Delivery(notifier.name, ok=False, detail=str(exc))
    raise AssertionError("unreachable")


async def notify(
    notification: Notification,
    *,
    settings: Settings | None = None,
    targets: Sequence[str] | None = None,
) -> list[Delivery]:
    """Send to every channel that accepts this notification's level."""
    settings = settings or Settings.from_env()

    if settings.telegram_auto_chats and not settings.telegram_chats:
        try:
            settings._discovered = await discover_telegram_chats(settings)
            log.info("telegram: discovered %d chat(s)", len(settings._discovered))
        except Exception as exc:  # discovery is a convenience, not a requirement
            log.warning("telegram: chat discovery failed: %s", exc)

    notifiers = [n for n in build_notifiers(targets, settings) if n.channel.accepts(notification)]
    if not notifiers:
        log.warning("no notification channel accepts this message")
        return []

    async with AsyncExitStack() as stack:
        live = [await stack.enter_async_context(n) for n in notifiers]
        return list(await asyncio.gather(*(send_one(n, notification, settings) for n in live)))
    return []  # pragma: no cover - AsyncExitStack always returns above
