"""Discord, via incoming webhooks.

Create one per channel under Channel Settings → Integrations → Webhooks:

    export DISCORD_WEBHOOK_URLS="alerts=https://discord.com/api/webhooks/1/x, https://.../2/y"

Sent as an embed rather than plain content: it carries a colour (which encodes
the level at a glance), a title, and the notification's fields as their own
columns. A successful webhook post answers 204 with an empty body, so there is
nothing to parse on the way out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..logging import get_logger
from .config import DISCORD_DESCRIPTION_LIMIT
from .models import Delivery, Notification, truncate
from .notifier import NotConfiguredError, Notifier

log = get_logger(__name__)

#: Discord rejects an embed with more than this many fields.
MAX_FIELDS = 25
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024


class DiscordNotifier(Notifier):
    """One webhook. Each is self-contained, unlike Telegram's shared token."""

    target = "discord"

    @property
    def ready(self) -> bool:
        return bool(self.channel.address)

    def payload(self, notification: Notification) -> dict[str, Any]:
        embed: dict[str, Any] = {
            "title": truncate(f"{notification.mark} {notification.title}", 256),
            "color": notification.colour,
        }
        if notification.body:
            embed["description"] = truncate(notification.body, DISCORD_DESCRIPTION_LIMIT)
        if notification.url:
            embed["url"] = notification.url
        if notification.fields:
            embed["fields"] = [
                {
                    "name": truncate(str(key), FIELD_NAME_LIMIT),
                    "value": truncate(str(value), FIELD_VALUE_LIMIT) or "-",
                    "inline": True,
                }
                for key, value in list(notification.fields.items())[:MAX_FIELDS]
            ]
        if notification.source:
            embed["footer"] = {"text": truncate(notification.source, 2048)}
        # Discord renders this itself, in the reader's own timezone, so the
        # embed gets the machine-readable form rather than the string
        # `as_text` builds for Telegram.
        if notification.at:
            embed["timestamp"] = datetime.fromtimestamp(notification.at, UTC).isoformat()
        return {"embeds": [embed]}

    async def send(self, notification: Notification) -> Delivery:
        if not self.ready:
            raise NotConfiguredError("discord: set DISCORD_WEBHOOK_URLS")
        await self.post(self.channel.address, self.payload(notification))
        return Delivery(self.name, ok=True)
