"""What gets sent, independent of where it goes.

A notification is written once and rendered per destination — Telegram wants
escaped HTML in a single string, Discord wants an embed object. Keeping the
message provider-agnostic means an alert can be added without touching either
transport.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Level(IntEnum):
    """How loud a notification is. Drives colour and prefix, nothing else."""

    INFO = 0
    WARNING = 1
    CRITICAL = 2

    @classmethod
    def parse(cls, value: str | int | None) -> Level:
        if value is None:
            return cls.INFO
        if isinstance(value, int) and not isinstance(value, bool):
            return cls(min(max(int(value), 0), 2))
        try:
            return cls[str(value).strip().upper()]
        except KeyError as exc:
            raise ValueError(f"unknown level {value!r} (use info, warning or critical)") from exc


#: Brand colours, reused for Discord embeds.
COLOURS: dict[Level, int] = {
    Level.INFO: 0x2AA79B,
    Level.WARNING: 0xE0A63C,
    Level.CRITICAL: 0xD9534F,
}

MARKS: dict[Level, str] = {Level.INFO: "•", Level.WARNING: "▲", Level.CRITICAL: "■"}


@dataclass(frozen=True, slots=True)
class Channel:
    """One destination within a provider — a chat, or a webhook.

    A provider is not a destination: one bot posts to many chats, and a server
    has a webhook per channel. `min_level` lets a noisy feed and an on-call
    channel share the same bot without sharing the same traffic.
    """

    target: str
    address: str
    label: str = ""
    min_level: Level = Level.INFO

    @property
    def name(self) -> str:
        return f"{self.target}[{self.label}]" if self.label else self.target

    def accepts(self, notification: Notification) -> bool:
        return notification.level >= self.min_level

    @property
    def masked(self) -> str:
        """Something recognisable that is safe to print.

        A webhook URL is a credential — anyone holding it can post — so only
        its host and a short tail are shown. A chat id identifies a room but
        grants nothing, so it is shown whole.
        """
        if "://" not in self.address:
            return self.address
        host = self.address.split("://", 1)[1].split("/", 1)[0]
        tail = self.address[-4:] if len(self.address) > 4 else ""
        return f"{host}/…{tail}"


@dataclass(frozen=True, slots=True)
class Notification:
    """One message, plus the structured bits a destination may render."""

    title: str
    body: str = ""
    level: Level = Level.INFO
    url: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    source: str = ""

    @property
    def colour(self) -> int:
        return COLOURS[self.level]

    @property
    def mark(self) -> str:
        return MARKS[self.level]

    def as_text(self, *, escape: bool = False, limit: int | None = None) -> str:
        """Flatten to plain text — the shape Telegram and logs both want."""
        esc = html.escape if escape else (lambda text: text)
        lines = [f"{self.mark} <b>{esc(self.title)}</b>" if escape else f"{self.mark} {self.title}"]
        if self.body:
            lines.append(esc(self.body))
        for key, value in self.fields.items():
            lines.append(f"{esc(key)}: {esc(str(value))}")
        if self.url:
            lines.append(esc(self.url))
        text = "\n".join(lines)
        return truncate(text, limit) if limit else text

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "level": self.level.name,
            "url": self.url,
            "fields": dict(self.fields),
            "source": self.source,
        }


def truncate(text: str, limit: int) -> str:
    """Cut to `limit` characters, leaving a visible marker.

    Both providers reject an over-long message outright rather than trimming
    it, so a 5000-character alert would simply never arrive.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    marker = " […]"
    return text[: max(0, limit - len(marker))].rstrip() + marker


@dataclass(frozen=True, slots=True)
class Delivery:
    """The outcome of sending one notification to one destination."""

    target: str
    ok: bool
    detail: str = ""

    def __str__(self) -> str:
        state = "sent" if self.ok else "failed"
        return f"{self.target}: {state}" + (f" ({self.detail})" if self.detail else "")
