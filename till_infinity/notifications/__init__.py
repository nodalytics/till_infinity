"""Notifications: send an alert to Telegram and Discord.

    from . import Level, Notification, notify

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

from till_infinity.utils.topics import alert

from .config import DEFAULT_TARGETS, Settings, parse_channels
from .delivery import (
    NOTIFIERS,
    build_notifiers,
    discover_telegram_chats,
    notify,
    send_one,
)
from .discord import DiscordNotifier
from .filters import Filter
from .models import (
    COLOURS,
    Channel,
    Delivery,
    Level,
    Notification,
    from_message,
    truncate,
)
from .notifier import (
    NotConfiguredError,
    Notifier,
    NotifierError,
    PermanentError,
    TransientError,
)
from .telegram import TelegramNotifier, parse_chats

__all__ = [
    "COLOURS",
    "DEFAULT_TARGETS",
    "NOTIFIERS",
    "Channel",
    "Delivery",
    "DiscordNotifier",
    "Filter",
    "Level",
    "NotConfiguredError",
    "Notification",
    "Notifier",
    "NotifierError",
    "PermanentError",
    "Settings",
    "TelegramNotifier",
    "TransientError",
    "alert",
    "build_notifiers",
    "discover_telegram_chats",
    "from_message",
    "notify",
    "parse_channels",
    "parse_chats",
    "send_one",
    "truncate",
]
