"""Fan a notification out to every configured channel.

One notifier per channel, all sent at once. A failing channel never blocks
another: each is retried on its own and the call returns a Delivery per
channel rather than raising, because an alert that reached the ops chat but not
the Discord board is a partial success and the caller should see exactly that.

**Moved out of `notifications/service.py` on 2026-11-01**, which retired to
`research/retire/notifications/`. What retired was the loop around these
functions - `listen`, pulling `alerts` off a `Carrier` - because
`notifications/actor.py` is that loop now and Nautilus owns the subscription.
The fan-out itself came here rather than retiring with it: there is no
`ExecutionClient` for Telegram, so nothing in the framework replaces it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from till_infinity.utils.logging import get_logger

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


async def _open_and_send(
    notifier: Notifier, notification: Notification, settings: Settings
) -> Delivery:
    """Open this channel's own session, send through it, and close it.

    **Per channel, rather than one `AsyncExitStack` over all of them.** The
    stack entered the contexts in sequence, so a notifier that failed to open
    cost every channel after it: the order is `DEFAULT_TARGETS`, telegram
    first, so a Telegram session failure meant Discord was never attempted -
    and with the order reversed it is the Telegram attempt that goes. On the
    worst day, broker down and terminal unreachable and one transport sick,
    the healthy one has to carry the message.
    """
    try:
        async with notifier:
            return await send_one(notifier, notification, settings)
    except Exception as exc:  # opening a session must not cost the other channels
        log.warning("%s: could not open a session: %s", notifier.name, exc)
        return Delivery(notifier.name, ok=False, detail=str(exc))


async def notify(
    notification: Notification,
    *,
    settings: Settings | None = None,
    targets: Sequence[str] | None = None,
) -> list[Delivery]:
    """Send to every channel that accepts this notification's level.

    Returns one `Delivery` per channel and raises nothing a caller has to
    handle, because the caller is an Actor handler on the path that decides
    trades.
    """
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

    # `return_exceptions=True` for the same reason the legs are independent:
    # without it, one leg raising discards every other leg's result, including
    # the ones that were delivered, and the caller reads a total failure.
    results = await asyncio.gather(
        *(_open_and_send(n, notification, settings) for n in notifiers),
        return_exceptions=True,
    )
    out: list[Delivery] = []
    for notifier, result in zip(notifiers, results, strict=True):
        if isinstance(result, Delivery):
            out.append(result)
        elif isinstance(result, asyncio.CancelledError):
            # The node is going away. Reporting this as a delivery failure
            # would make a clean shutdown look like an outage.
            raise result
        else:
            log.warning("%s: unexpected failure: %s", notifier.name, result)
            out.append(Delivery(notifier.name, ok=False, detail=str(result)))
    return out
