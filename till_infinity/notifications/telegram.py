"""Telegram, via the Bot API.

One bot token, any number of chats:

    export TELEGRAM_BOT_TOKEN=123456:AA...
    export TELEGRAM_CHAT_IDS="ops=-1001111|warning, feed=-1002222"

Chat ids are awkward to find by hand, so they can be discovered instead —
``till-infinity notify chats`` asks the bot what it can see. Two caveats come
from the API itself and are worth knowing before trusting it:

* ``getUpdates`` only returns the last 24 hours of activity, so a chat the bot
  has been idle in will not appear. Send it any message first;
* it returns HTTP 409 while a webhook is registered, because the two delivery
  modes are mutually exclusive.

Messages are sent as HTML because the alternative, Markdown, makes any stray
underscore or asterisk in a symbol name a parse error — and instrument names
are full of them. Everything interpolated is escaped.
"""

from __future__ import annotations

from typing import Any

from ..logging import get_logger
from .config import TELEGRAM_API, TELEGRAM_TEXT_LIMIT
from .models import Channel, Delivery, Notification
from .notifier import NotConfiguredError, Notifier, PermanentError

log = get_logger(__name__)

#: Chat types worth posting into, in the order a human would expect them.
CHAT_TYPES = ("channel", "supergroup", "group", "private")


class TelegramNotifier(Notifier):
    """One chat. Many of these share a token."""

    target = "telegram"

    @property
    def ready(self) -> bool:
        return bool(self.settings.telegram_token and self.channel.address)

    def api(self, method: str) -> str:
        # The token lives in the path, which is why it never reaches a log line.
        return f"{TELEGRAM_API}/bot{self.settings.telegram_token}/{method}"

    def payload(self, notification: Notification) -> dict[str, object]:
        return {
            "chat_id": self.channel.address,
            "text": notification.as_text(escape=True, limit=TELEGRAM_TEXT_LIMIT),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

    async def send(self, notification: Notification) -> Delivery:
        if not self.ready:
            raise NotConfiguredError("telegram: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS")
        response = await self.post(self.api("sendMessage"), self.payload(notification))
        body = response.json() if response.content else {}
        if isinstance(body, dict) and body.get("ok") is False:
            # A 200 with ok=false happens; treat it as the failure it is.
            return Delivery(self.name, ok=False, detail=str(body.get("description"))[:120])
        return Delivery(self.name, ok=True)

    async def discover(self) -> tuple[Channel, ...]:
        """Ask the bot which chats it has seen recently."""
        if not self.settings.telegram_token:
            raise NotConfiguredError("telegram: set TELEGRAM_BOT_TOKEN")
        response = self.checked(await self.client.get(self.api("getUpdates")))
        try:
            body = response.json()
        except ValueError as exc:
            raise PermanentError(f"telegram: {exc}") from exc
        return parse_chats(body)


def parse_chats(payload: Any) -> tuple[Channel, ...]:
    """Pull the distinct chats out of a getUpdates response, newest first."""
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise PermanentError(f"telegram: {str(payload)[:120]}")

    found: dict[str, Channel] = {}
    for update in payload.get("result") or []:
        if not isinstance(update, dict):
            continue
        for value in update.values():
            chat = value.get("chat") if isinstance(value, dict) else None
            if not isinstance(chat, dict) or chat.get("id") is None:
                continue
            address = str(chat["id"])
            label = (
                chat.get("title")
                or chat.get("username")
                or " ".join(filter(None, (chat.get("first_name"), chat.get("last_name"))))
                or address
            )
            # Later updates win, so a renamed chat shows its current name.
            found[address] = Channel(target="telegram", address=address, label=str(label))
    return tuple(found.values())
