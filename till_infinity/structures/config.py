"""Settings for the online models.

Nothing here needs an API key. That is the point of keeping `structures` out of
`agents`: the numeric layer runs continuously, on a laptop or a box with no
credentials at all, and is never held up by a provider being down.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .state import Restorable

DEFAULT_STATE_DIR = ".data/structures"
DEFAULT_JOURNAL_DB = ".data/journal/journal.db"
DEFAULT_PRICES_DB = ".data/prices/prices.db"

#: Only fast data. Above five minutes a "cross-venue disagreement" is mostly
#: different bar boundaries, not different opinions about the price.
INTERVALS: tuple[str, ...] = ("1m", "5m")

#: Timeframes the drift detector watches. Wider than INTERVALS on purpose: a
#: regime change now discounts every level's history, so it has to be confirmed
#: across timeframes rather than declared by whichever one is noisiest.
DRIFT_INTERVALS: tuple[str, ...] = ("5m", "15m", "1h", "4h")

#: Seconds between saves. An online model that resets on every restart has
#: learned nothing, so persistence is not optional - only its frequency is.
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
class Settings(Restorable):
    """How the models are tuned, where their state lives."""

    state_dir: Path = field(default_factory=lambda: Path(DEFAULT_STATE_DIR))
    journal_db: Path = field(default_factory=lambda: Path(DEFAULT_JOURNAL_DB))
    #: Read-only, and only to warm the level windows on start.
    prices_db: Path = field(default_factory=lambda: Path(DEFAULT_PRICES_DB))
    warm: bool = True
    journalling: bool = True
    warmup: int = 60
    quantile: float = 0.999
    sigma: float = 4.0
    save_seconds: float = DEFAULT_SAVE_SECONDS
    direct_dev_bps: float = DEFAULT_DIRECT_DEV_BPS
    cooldown: float = DEFAULT_COOLDOWN
    alert_direct: bool = True
    #: Whether an actionable level call reaches a person without an agent in
    #: between. On by default, because it is the thing the system is *for* -
    #: with it off and agents disabled, level calls are published to a topic
    #: nobody is subscribed to and the channel receives only feed faults.
    alert_levels: bool = True
    #: Whether the measured spread is charged against every level call before
    #: it is judged. On by default: a push that has not had the cost of taking
    #: it deducted is a gross number, and the gap between gross and net is the
    #: whole difference between a figure and a decision.
    #:
    #: Turning it off is for comparison, not for production - run the same
    #: history both ways and the difference is exactly what the cost is worth.
    #: Worth knowing before doing so: the charge is not uniform, running from
    #: 0.003v on btc to 2.5v on gbpusd intraday, so switching it off does not
    #: loosen one gate evenly. See levels.md, "What the cost actually comes to".
    charge_spread: bool = True

    #: How swings are found: `pip` takes bar extremes by prominence, `run` the
    #: boundaries between volatility runs, `origin` the turns whose impulse set
    #: a new running extremum, `profile` the price bands where the most
    #: activity happened, and `both` runs pip and run as separate passes and
    #: merges them.
    #:
    #: A setting because it was not one, and the `origin` formation shipped
    #: unreachable: `Engine` took the argument, nothing passed it, and the
    #: default won. Every level in production was drawn by `pip` while the
    #: other two sat there looking available.
    #:
    #: The point is to run them over one history and let the outcome machinery
    #: say which price gets respected, which needs the choice to be reachable
    #: from a deployment rather than from a keyword argument nobody sets.
    #:
    #: **Three by default**, because they find different prices and merging is
    #: additive - a pass that draws nothing costs a little work and removes no
    #: level. `origin` alone draws none at all on gold at 1m, 5m or 15m, so
    #: selecting it instead of `pip` would have stopped that instrument
    #: trading; selecting it *alongside* cannot.
    #:
    #: `profile` is left out of the default: it is measured but unproven, and
    #: a default is not the place to find out.
    formation: str = "pip,run,origin"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            state_dir=Path(os.environ.get("STRUCTURES_DIR") or DEFAULT_STATE_DIR),
            journal_db=Path(os.environ.get("JOURNAL_DB") or DEFAULT_JOURNAL_DB),
            prices_db=Path(os.environ.get("PRICES_DB") or DEFAULT_PRICES_DB),
            warm=os.environ.get("STRUCTURES_WARM", "1") not in ("0", "false", "no"),
            journalling=os.environ.get("JOURNAL", "1") not in ("0", "false", "no"),
            warmup=_int("STRUCTURES_WARMUP", 60),
            quantile=_float("STRUCTURES_QUANTILE", 0.999),
            sigma=_float("STRUCTURES_SIGMA", 4.0),
            save_seconds=_float("STRUCTURES_SAVE_S", DEFAULT_SAVE_SECONDS),
            direct_dev_bps=_float("STRUCTURES_DIRECT_DEV_BPS", DEFAULT_DIRECT_DEV_BPS),
            cooldown=_float("STRUCTURES_COOLDOWN_S", DEFAULT_COOLDOWN),
            alert_direct=os.environ.get("STRUCTURES_DIRECT", "1") not in ("0", "false", "no"),
            alert_levels=os.environ.get("STRUCTURES_ALERT_LEVELS", "1") not in ("0", "false", "no"),
            charge_spread=os.environ.get("STRUCTURES_CHARGE_SPREAD", "1")
            not in ("0", "false", "no"),
            formation=os.environ.get("STRUCTURES_FORMATION") or "pip",
        )
