"""Settings for the agents package.

The model is named once here rather than at each call site, and the store paths
default to where the collectors put them, so an agent run needs no arguments in
the common case.

No credential appears in this object. Every provider's client reads its own key
straight from the environment, so a key is never held in a settings instance
that might end up in a log line, a repr or a journal entry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import providers

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_FALLBACKS = ("claude-sonnet-5",)
DEFAULT_PRICES_DB = ".data/prices/prices.db"
DEFAULT_NEWS_DB = ".data/news/news.db"
DEFAULT_JOURNAL_DB = ".data/journal/journal.db"

#: How long a batch of bus messages is gathered before the model sees it.
#: The bus carries tens of quotes a second and a model call takes seconds, so
#: something has to absorb the difference — a window, not a queue.
DEFAULT_WINDOW_SECONDS = 60.0
#: Only wake the model when the market is actually doing something.
DEFAULT_SPREAD_BPS = 8.0
DEFAULT_IMPORTANCE = 3

DEFAULT_MAX_TOKENS = 2_048
DEFAULT_TIMEOUT = 120.0
DEFAULT_TOOL_CALLS = 12


def _float(name: str, fallback: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _int(name: str, fallback: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


@dataclass(slots=True)
class Settings:
    """Everything an agent run needs, resolved from the environment."""

    model: str = DEFAULT_MODEL
    fallbacks: tuple[str, ...] = DEFAULT_FALLBACKS
    prices_db: Path = field(default_factory=lambda: Path(DEFAULT_PRICES_DB))
    news_db: Path = field(default_factory=lambda: Path(DEFAULT_NEWS_DB))
    journal_db: Path = field(default_factory=lambda: Path(DEFAULT_JOURNAL_DB))
    journalling: bool = True
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    spread_bps: float = DEFAULT_SPREAD_BPS
    importance: int = DEFAULT_IMPORTANCE
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = DEFAULT_TIMEOUT
    tool_calls: int = DEFAULT_TOOL_CALLS
    thinking: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("AGENTS_FALLBACK_MODELS", "")
        fallbacks = tuple(name.strip() for name in raw.split(",") if name.strip())
        return cls(
            model=os.environ.get("AGENTS_MODEL") or DEFAULT_MODEL,
            fallbacks=fallbacks or DEFAULT_FALLBACKS,
            prices_db=Path(os.environ.get("PRICES_DB") or DEFAULT_PRICES_DB),
            news_db=Path(os.environ.get("NEWS_DB") or DEFAULT_NEWS_DB),
            journal_db=Path(os.environ.get("JOURNAL_DB") or DEFAULT_JOURNAL_DB),
            journalling=os.environ.get("JOURNAL", "1") not in ("0", "false", "no"),
            window_seconds=_float("AGENTS_WINDOW_S", DEFAULT_WINDOW_SECONDS),
            spread_bps=_float("AGENTS_SPREAD_BPS", DEFAULT_SPREAD_BPS),
            importance=_int("AGENTS_IMPORTANCE", DEFAULT_IMPORTANCE),
            max_tokens=_int("AGENTS_MAX_TOKENS", DEFAULT_MAX_TOKENS),
            timeout=_float("AGENTS_TIMEOUT_S", DEFAULT_TIMEOUT),
            tool_calls=_int("AGENTS_TOOL_CALLS", DEFAULT_TOOL_CALLS),
            thinking=os.environ.get("AGENTS_THINKING", "1") not in ("0", "false", "no"),
        )

    @property
    def ready(self) -> bool:
        """Whether the chosen model's provider has what it needs."""
        return providers.ready(self.model)

    @property
    def provider(self) -> str:
        return providers.split(self.model)[0]
