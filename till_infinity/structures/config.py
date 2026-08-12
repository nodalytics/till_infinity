"""Settings for the online models.

Nothing here needs an API key. That is the point of keeping `structures` out of
`agents`: the numeric layer runs continuously, on a laptop or a box with no
credentials at all, and is never held up by a provider being down.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STATE_DIR = ".data/structures"
DEFAULT_JOURNAL_DB = ".data/journal/journal.db"

#: Only fast data. Above five minutes a "cross-venue disagreement" is mostly
#: different bar boundaries, not different opinions about the price.
INTERVALS: tuple[str, ...] = ("1m", "5m")

#: Seconds between saves. An online model that resets on every restart has
#: learned nothing, so persistence is not optional — only its frequency is.
DEFAULT_SAVE_SECONDS = 300.0

#: A deviation this large is not a market opinion, it is a broken quote, so it
#: goes straight to `alerts` without waiting for an agent. Nothing on the
#: economic calendar moves one venue 100bps while five others hold still.
DEFAULT_DIRECT_DEV_BPS = 100.0

#: One signal per (shape, feed, venue) per this many seconds. A venue that
#: stays stale for an hour is one situation, not three thousand.
DEFAULT_COOLDOWN = 900.0


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
    """How the models are tuned, where their state lives."""

    state_dir: Path = field(default_factory=lambda: Path(DEFAULT_STATE_DIR))
    journal_db: Path = field(default_factory=lambda: Path(DEFAULT_JOURNAL_DB))
    journalling: bool = True
    warmup: int = 60
    quantile: float = 0.999
    sigma: float = 4.0
    save_seconds: float = DEFAULT_SAVE_SECONDS
    direct_dev_bps: float = DEFAULT_DIRECT_DEV_BPS
    cooldown: float = DEFAULT_COOLDOWN
    alert_direct: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            state_dir=Path(os.environ.get("STRUCTURES_DIR") or DEFAULT_STATE_DIR),
            journal_db=Path(os.environ.get("JOURNAL_DB") or DEFAULT_JOURNAL_DB),
            journalling=os.environ.get("JOURNAL", "1") not in ("0", "false", "no"),
            warmup=_int("STRUCTURES_WARMUP", 60),
            quantile=_float("STRUCTURES_QUANTILE", 0.999),
            sigma=_float("STRUCTURES_SIGMA", 4.0),
            save_seconds=_float("STRUCTURES_SAVE_S", DEFAULT_SAVE_SECONDS),
            direct_dev_bps=_float("STRUCTURES_DIRECT_DEV_BPS", DEFAULT_DIRECT_DEV_BPS),
            cooldown=_float("STRUCTURES_COOLDOWN_S", DEFAULT_COOLDOWN),
            alert_direct=os.environ.get("STRUCTURES_DIRECT", "1") not in ("0", "false", "no"),
        )
