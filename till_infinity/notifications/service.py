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
from dataclasses import replace
from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..bus import ALERTS, Bus
from ..logging import get_logger
from .config import DEFAULT_TARGETS, Settings
from .discord import DiscordNotifier
from .filters import Filter
from .models import Channel, Delivery, Level, Notification
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


def from_message(payload: dict[str, Any]) -> Notification | None:
    """Turn an `alerts` message into a Notification.

    The payload comes off the bus, which means an agent wrote it — so nothing
    here trusts it. A message with no title is dropped rather than sent as an
    empty alert, and `fields` is flattened to strings because a notifier
    renders text, not arbitrary JSON.
    """
    title = str(payload.get("title") or "").strip()
    if not title:
        return None
    raw = payload.get("fields")
    fields = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    return Notification(
        title=title,
        body=str(payload.get("body") or ""),
        level=Level.parse(payload.get("level")),
        url=str(payload.get("url") or ""),
        fields=fields,
        source=str(payload.get("source") or ""),
    )


async def listen(
    bus: Bus,
    *,
    settings: Settings | None = None,
    targets: Sequence[str] | None = None,
    group: str = "notifications",
    limit: int | None = None,
    alert_filter: Filter | None = None,
) -> int:
    """Deliver every alert published to the bus. Returns how many were sent.

    Runs until the bus closes (or `limit` alerts have been handled). Delivery
    failures are logged and the loop continues — one unreachable webhook must
    not stop the next alert from reaching the chat that is up.
    """
    settings = settings or Settings.from_env()
    alert_filter = alert_filter or Filter.from_env()
    log.info("notify: accepting %s", alert_filter.describe())
    handled = 0
    async for message in bus.subscribe(ALERTS, group=group):
        notification = from_message(message.payload)
        if notification is None:
            log.warning("alerts: dropped a message with no title")
            continue
        # Filtered here rather than at the publisher: what is worth *recording*
        # and what is worth *interrupting someone with* are different
        # questions, and the journal should keep everything either way.
        if not alert_filter.accept(message.payload):
            continue
        if not notification.source:
            notification = replace(notification, source=message.source)
        deliveries = await notify(notification, settings=settings, targets=targets)
        failed = [d for d in deliveries if not d.ok]
        log.info(
            "alert %r -> %d/%d channels%s",
            notification.title,
            len(deliveries) - len(failed),
            len(deliveries),
            f" ({', '.join(d.target for d in failed)} failed)" if failed else "",
        )
        handled += 1
        if limit is not None and handled >= limit:
            return handled
    return handled
