"""Telegram, via the Bot API.

One bot token, any number of chats:

    export TELEGRAM_BOT_TOKEN=123456:AA...
    export TELEGRAM_CHAT_IDS="ops=-1001111|warning, feed=-1002222"

Chat ids are awkward to find by hand, so they can be discovered instead -
``till-infinity notify chats`` asks the bot what it can see. Two caveats come
from the API itself and are worth knowing before trusting it:

* ``getUpdates`` only returns the last 24 hours of activity, so a chat the bot
  has been idle in will not appear. Send it any message first;
* it returns HTTP 409 while a webhook is registered, because the two delivery
  modes are mutually exclusive.

Messages are sent as HTML because the alternative, Markdown, makes any stray
underscore or asterisk in a symbol name a parse error - and instrument names
are full of them. Everything interpolated is escaped.

A notification with an image goes out through `sendPhoto`, the text as its
HTML caption. A caption is limited to 1,024 characters, so it is cut at a line
boundary - never inside an escaped entity or a tag - and the lines that do not
fit follow as an ordinary `sendMessage`. If the photo fails for any reason the
whole text is sent once more without it, so an alert is never lost for its
picture.
"""

from __future__ import annotations

from typing import Any

from till_platform.logging import get_logger

from .config import TELEGRAM_API, TELEGRAM_TEXT_LIMIT
from .models import Channel, Delivery, Notification
from .notifier import NotConfiguredError, Notifier, NotifierError, PermanentError

#: Telegram's limit on a photo caption.
CAPTION_LIMIT = 1024

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

    def photo(self, notification: Notification) -> tuple[dict[str, object], dict, str]:
        """The `sendPhoto` form for a notification with a picture: (data, files,
        overflow), where overflow is the text that did not fit the caption."""
        caption, overflow = split_caption(notification.as_text(escape=True))
        data: dict[str, object] = {
            "chat_id": self.channel.address,
            "caption": caption,
            "parse_mode": "HTML",
        }
        name = notification.image_name or "chart.png"
        kind = "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else "image/png"
        return data, {"photo": (name, notification.image or b"", kind)}, overflow

    async def send(self, notification: Notification) -> Delivery:
        if not self.ready:
            raise NotConfiguredError("telegram: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS")
        if notification.image:
            sent = await self._send_photo(notification)
            if sent is not None:
                return sent
            notification = notification.without_image()
        return await self._send_text(self.payload(notification))

    async def _send_photo(self, notification: Notification) -> Delivery | None:
        """Send with the picture; None means it failed and text alone should follow."""
        data, files, overflow = self.photo(notification)
        try:
            response = await self.post_files(self.api("sendPhoto"), data, files)
            body = response.json() if response.content else {}
        except (NotifierError, ValueError) as exc:
            log.warning("%s: photo send failed (%s) - sending text only", self.name, exc)
            return None
        if isinstance(body, dict) and body.get("ok") is False:
            log.warning(
                "%s: photo refused (%s) - sending text only",
                self.name,
                str(body.get("description"))[:120],
            )
            return None
        if overflow:
            return await self._send_text(
                {
                    "chat_id": self.channel.address,
                    "text": overflow[:TELEGRAM_TEXT_LIMIT],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
            )
        return Delivery(self.name, ok=True)

    async def _send_text(self, payload: dict[str, object]) -> Delivery:
        response = await self.post(self.api("sendMessage"), payload)
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


def split_caption(text: str, limit: int = CAPTION_LIMIT) -> tuple[str, str]:
    """(caption, overflow): whole lines up to `limit`, and the rest.

    Cut between lines because every line of `as_text(escape=True)` is complete
    HTML on its own - the title's `<b>` closes on its line and entities are
    escaped per line - so a line boundary can never split a tag or an `&amp;`.
    A first line longer than the limit is the one case that has to be cut
    mid-line, and it is cut only after its tags have closed.
    """
    if len(text) <= limit:
        return text, ""
    lines = text.split("\n")
    caption: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        extra = len(line) + (1 if caption else 0)
        if used + extra > limit:
            if not caption:
                return _cut(line, limit), "\n".join(lines[i + 1 :])
            return "\n".join(caption), "\n".join(lines[i:])
        caption.append(line)
        used += extra
    return "\n".join(caption), ""


def _cut(line: str, limit: int) -> str:
    """A line shortened to `limit` without breaking a tag or an entity."""
    cut = line[: max(0, limit - 2)]
    amp = cut.rfind("&")
    if amp > cut.rfind(";"):
        cut = cut[:amp]
    if "<b>" in cut and "</b>" not in cut:
        cut = cut.replace("<b>", "")
    return cut + " …"


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
