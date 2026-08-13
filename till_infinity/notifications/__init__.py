"""Notifications: send an alert to Telegram and Discord.

    from till_infinity.notifications import Level, Notification, notify

    await notify(
        Notification(
            title="Gold spread blew out",
            body="OANDA 4.2bps vs Pepperstone 0.2bps",
            level=Level.WARNING,
            fields={"instrument": "gold", "brokers": "6"},
        )
    )

Credentials come from the environment and are never stored or logged:

    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, DISCORD_WEBHOOK_URLS

Each provider fans out to as many channels as you list.
"""

from .config import DEFAULT_TARGETS, Settings, parse_channels
from .discord import DiscordNotifier
from .models import COLOURS, Channel, Delivery, Level, Notification, truncate
from .notifier import (
    NotConfiguredError,
    Notifier,
    NotifierError,
    PermanentError,
    TransientError,
)
from .service import (
    NOTIFIERS,
    build_notifiers,
    discover_telegram_chats,
    from_message,
    listen,
    notify,
    send_one,
)
from .telegram import TelegramNotifier, parse_chats

__all__ = [
    "COLOURS",
    "DEFAULT_TARGETS",
    "NOTIFIERS",
    "Channel",
    "Delivery",
    "DiscordNotifier",
    "Level",
    "NotConfiguredError",
    "Notification",
    "Notifier",
    "NotifierError",
    "PermanentError",
    "Settings",
    "TelegramNotifier",
    "TransientError",
    "build_notifiers",
    "discover_telegram_chats",
    "from_message",
    "listen",
    "notify",
    "parse_channels",
    "parse_chats",
    "send_one",
    "truncate",
]
