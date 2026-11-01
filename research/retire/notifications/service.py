"""`till_infinity/notifications/service.py`'s bus loop, retired 2026-11-01.

The whole of `listen` - subscribe to `alerts` on the `Carrier`, parse, filter,
deliver, log the tally - plus the `notifications.delivered` effect declaration
that went with it. **`notifications/actor.py` is this loop now**: Nautilus's
`msgbus` owns the subscription, `queue_for_executor` owns the "do not block the
handler" part, and the three things the loop did besides looping - `Filter`,
`from_message` and the effect - moved onto the Actor rather than retiring,
because each one was the only thing standing between a trading alarm and nobody
reading it.

The rest of the file did **not** retire. `notify`, `send_one`,
`build_notifiers`, `discover_telegram_chats` and `NOTIFIERS` are
`till_infinity/notifications/delivery.py`, and `from_message` with its image
validation is `till_infinity/notifications/models.py`, beside the `to_dict`
that is its inverse. A framework can replace a bus loop; it cannot replace a
Telegram client, and there is no `ExecutionClient` for one.

Kept runnable rather than frozen: it imports the live package, so the claim
"this is what ran" stays checkable. Nothing in the package imports it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from till_infinity.carrier import Carrier
from till_infinity.notifications import Filter, Settings, from_message, notify
from till_infinity.utils import effects
from till_infinity.utils.logging import get_logger
from till_infinity.utils.topics import ALERTS

#: Always on. Every trading alarm this desk raised was dropped before this line
#: for weeks, and nothing said so.
effects.declare("notifications.delivered", enabled=True)

log = get_logger(__name__)


async def listen(
    bus: Carrier,
    *,
    settings: Settings | None = None,
    targets: Sequence[str] | None = None,
    group: str = "notifications",
    limit: int | None = None,
    alert_filter: Filter | None = None,
) -> int:
    """Deliver every alert published to the bus. Returns how many were sent.

    Runs until the bus closes (or `limit` alerts have been handled). Delivery
    failures are logged and the loop continues - one unreachable webhook must
    not stop the next alert from reaching the chat that is up.

    **Two things the Actor does differently, both visible in this body.** It
    awaits `notify` inside the loop, so a Telegram timeout stalls every alert
    queued behind it - the Actor hands the send to `queue_for_executor` and
    returns. And an exception anywhere in the body ends the loop and with it
    the service: `Level.parse` raises on a misspelled level, and one bad
    payload would stop every later alert. The Actor counts a failure instead,
    because an alert is worth less than the desk it is about.
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
        effects.fired("notifications.delivered")
        deliveries = await notify(notification, settings=settings, targets=targets)
        failed = [d for d in deliveries if not d.ok]
        # The first body line comes along, because the title alone cannot be
        # checked against anything. For a level call that line carries the
        # price and which timeframes agreed - the one claim in the message that
        # is verifiable from outside, against `structures zones` for the same
        # instrument. Logging what was *sent* rather than what was computed is
        # the point: those are the two things that can silently disagree.
        summary = notification.body.splitlines()[0] if notification.body else ""
        log.info(
            "alert %r%s -> %d/%d channels%s",
            notification.title,
            f" [{summary}]" if summary else "",
            len(deliveries) - len(failed),
            len(deliveries),
            f" ({', '.join(d.target for d in failed)} failed)" if failed else "",
        )
        handled += 1
        if limit is not None and handled >= limit:
            return handled
    return handled
