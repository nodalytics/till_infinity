"""Credentials, channels and delivery settings.

Secrets are read from the environment and never written anywhere - not to the
store, not to a log line, not to `notify targets`, which prints a masked
address at most.

Each provider takes a *list* of destinations, because one bot posts to many
chats and a server has a webhook per channel:

    TELEGRAM_BOT_TOKEN=123:AA...
    TELEGRAM_CHAT_IDS="ops=-1001111|warning, feed=-1002222"
    DISCORD_WEBHOOK_URLS="alerts=https://discord.com/api/webhooks/1/x, https://.../2/y"

An entry is ``[label=]address[|min-level]``. The label is optional and only for
reading logs; the level filter lets an on-call channel and a firehose share one
bot without sharing traffic.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .models import Channel, Level

TELEGRAM_API = "https://api.telegram.org"

#: Provider hard limits. Both reject an over-long message rather than trimming.
TELEGRAM_TEXT_LIMIT = 4096
DISCORD_CONTENT_LIMIT = 2000
DISCORD_DESCRIPTION_LIMIT = 4096

DEFAULT_TARGETS: tuple[str, ...] = ("telegram", "discord")

#: A label is a plain word. Anything else - a URL, a negative chat id - is an
#: address, which is how ``https://…`` avoids being mistaken for ``label=…``.
_LABEL = re.compile(r"^[A-Za-z0-9_-]+$")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def parse_channels(raw: str, target: str) -> tuple[Channel, ...]:
    """Parse ``label=address|level, address, …`` into channels."""
    channels: list[Channel] = []
    for index, item in enumerate(raw.split(","), start=1):
        entry = item.strip()
        if not entry:
            continue

        head, pipe, level_text = entry.rpartition("|")
        if pipe:
            entry, level = head.strip(), Level.parse(level_text.strip())
        else:
            level = Level.INFO

        label, equals, rest = entry.partition("=")
        if equals and _LABEL.match(label.strip()):
            label, address = label.strip(), rest.strip()
        else:
            label, address = "", entry
        if not address:
            continue
        channels.append(
            Channel(target=target, address=address, label=label or str(index), min_level=level)
        )
    return tuple(channels)


@dataclass(slots=True)
class Settings:
    """Where notifications go, and how hard to try."""

    telegram_token: str = ""
    telegram_chats: tuple[Channel, ...] = ()
    discord_webhooks: tuple[Channel, ...] = ()

    #: Ask Telegram which chats the bot can see, instead of listing them.
    telegram_auto_chats: bool = False

    timeout: float = 15.0
    retries: int = 3
    #: Providers answer a 429 with the exact wait; never sleep longer than this.
    max_retry_after: float = 60.0

    _discovered: tuple[Channel, ...] = field(default=(), repr=False)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_token) and bool(self.telegram_chats or self.telegram_auto_chats)

    @property
    def discord_ready(self) -> bool:
        return bool(self.discord_webhooks)

    def channels(self, target: str) -> tuple[Channel, ...]:
        if target == "telegram":
            return self.telegram_chats or self._discovered
        if target == "discord":
            return self.discord_webhooks
        return ()

    def configured(self) -> tuple[str, ...]:
        """Which targets have everything they need."""
        return tuple(
            name
            for name, ready in (("telegram", self.telegram_ready), ("discord", self.discord_ready))
            if ready
        )

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            telegram_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chats=parse_channels(_env("TELEGRAM_CHAT_IDS"), "telegram"),
            discord_webhooks=parse_channels(_env("DISCORD_WEBHOOK_URLS"), "discord"),
            telegram_auto_chats=_env("TELEGRAM_AUTO_CHATS") in ("1", "true", "yes"),
        )
