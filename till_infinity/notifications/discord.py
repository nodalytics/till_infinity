"""Discord, via incoming webhooks.

Create one per channel under Channel Settings → Integrations → Webhooks:

    export DISCORD_WEBHOOK_URLS="alerts=https://discord.com/api/webhooks/1/x, https://.../2/y"

Sent as an embed rather than plain content: it carries a colour (which encodes
the level at a glance), a title, and the notification's fields as their own
columns. A successful webhook post answers 204 with an empty body, so there is
nothing to parse on the way out.

A notification with an image is sent as a multipart form instead: the embed in
`payload_json` and the PNG as `files[0]`, which the embed shows by pointing its
`image.url` at `attachment://<name>`. If that post fails for any reason the
same embed is sent again without the picture - one retry, text only - so an
alert is never lost for its image.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from till_platform.logging import get_logger

from .config import DISCORD_DESCRIPTION_LIMIT
from .models import Delivery, Notification, truncate
from .notifier import NotConfiguredError, Notifier, NotifierError

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

    def with_image(self, notification: Notification) -> tuple[dict[str, Any], dict]:
        """The multipart form for a notification with a picture: (data, files)."""
        payload = self.payload(notification)
        name = notification.image_name or "chart.png"
        payload["embeds"][0]["image"] = {"url": f"attachment://{name}"}
        kind = "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else "image/png"
        files = {"files[0]": (name, notification.image or b"", kind)}
        return {"payload_json": json.dumps(payload)}, files

    async def send(self, notification: Notification) -> Delivery:
        if not self.ready:
            raise NotConfiguredError("discord: set DISCORD_WEBHOOK_URLS")
        if notification.image:
            data, files = self.with_image(notification)
            try:
                await self.post_files(self.channel.address, data, files)
                return Delivery(self.name, ok=True)
            except NotifierError as exc:
                log.warning("%s: image send failed (%s) - sending text only", self.name, exc)
            notification = notification.without_image()
        await self.post(self.channel.address, self.payload(notification))
        return Delivery(self.name, ok=True)
