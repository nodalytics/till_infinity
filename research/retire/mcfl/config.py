"""Settings for the pattern alerts.

Read from the environment the way every other service reads it
(`shared/env.py`): a bad value falls back to the default and says so, rather
than stopping the service or being silently ignored.

    MCFL_ENABLED=1               start the service at all (the stack's switch;
                                 read in `stack.Plan`, not here)
    MCFL_PAUSE_FILE              while this file exists the service fetches and
                                 sends nothing (default .data/mcfl.off)
    MCFL_PATTERNS                patterns that alert (default: DISPLACE_C_LOW12, M1, B)
    MCFL_TIMEFRAMES              15m,1h,4h,1d by default
    MCFL_ALT_COINS               the alt universe (default: the 344 validated coins)
    MCFL_ALT_TIMEFRAMES          4h,1d by default
    MCFL_MAJOR_PIVOT             bars either side of a 15m major swing (10)
    MCFL_MAJOR_MOVE_ATR          ATR away from it before the break counts (3.0)
    MCFL_CHARTS                  attach a chart to each card (on; needs matplotlib)
    MCFL_BINANCE_URL             Binance spot's API host (the public data mirror)
    MCFL_DIR                     where state lives (.data/mcfl)
    MCFL_DERIVE_1D               build 1d from the finest stored bars (auto: when
                                 INTERVALS is set and does not name 1d)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..logging import get_logger
from ..prices.models import INTERVALS
from ..shared.env import env, flag, names, number, whole
from . import registry
from .universe import ALT_TIMEFRAMES, BINANCE_MIRROR, DEFAULT_COINS

log = get_logger(__name__)

DEFAULT_DIR = ".data/mcfl"
DEFAULT_PAUSE_FILE = ".data/mcfl.off"
DEFAULT_PRICES_DB = ".data/prices/prices.db"

#: Bars of history each detection reads. The longest look-back of any pattern
#: is a protected low's 40-bar sweep window plus its 20-bar leg; 300 is the
#: paper logger's own window and leaves the ATR long settled.
LOOKBACK = 300

#: Seconds after a bar closes before the alt universe is asked for it. Venues
#: take a moment to finalise a candle, and the paper logger waits two minutes.
POLL_DELAY = 90.0


@dataclass(slots=True)
class Settings:
    """Everything the service reads, resolved once at start."""

    patterns: tuple[str, ...] = registry.DEFAULT_ENABLED
    timeframes: tuple[str, ...] = registry.TIMEFRAMES
    alt_coins: tuple[str, ...] = DEFAULT_COINS
    alt_timeframes: tuple[str, ...] = ALT_TIMEFRAMES
    major_pivot: int = 10
    major_move_atr: float = 3.0
    charts: bool = True
    binance_url: str = BINANCE_MIRROR
    state_dir: Path = Path(DEFAULT_DIR)
    pause_file: Path = Path(DEFAULT_PAUSE_FILE)
    prices_db: Path = Path(DEFAULT_PRICES_DB)
    derive_1d: bool = False
    lookback: int = LOOKBACK
    poll_delay: float = POLL_DELAY

    @classmethod
    def from_env(cls) -> Settings:
        wanted = names("MCFL_PATTERNS", registry.DEFAULT_ENABLED)
        patterns = registry.resolve(wanted)
        unknown = [n for n in wanted if n not in patterns]
        if unknown:
            log.warning(
                "config: MCFL_PATTERNS names %s, which no pattern is called - have %s",
                ", ".join(unknown),
                ", ".join(registry.PATTERNS),
            )
        timeframes = _intervals("MCFL_TIMEFRAMES", registry.TIMEFRAMES)
        stack_intervals = names("INTERVALS")
        derive = flag("MCFL_DERIVE_1D", bool(stack_intervals) and "1d" not in stack_intervals)
        return cls(
            patterns=patterns,
            timeframes=timeframes,
            alt_coins=tuple(c.upper() for c in names("MCFL_ALT_COINS", DEFAULT_COINS)),
            alt_timeframes=_intervals("MCFL_ALT_TIMEFRAMES", ALT_TIMEFRAMES),
            major_pivot=max(1, whole("MCFL_MAJOR_PIVOT", 10)),
            major_move_atr=number("MCFL_MAJOR_MOVE_ATR", 3.0),
            charts=flag("MCFL_CHARTS", True),
            binance_url=env("MCFL_BINANCE_URL", BINANCE_MIRROR),
            state_dir=Path(env("MCFL_DIR", DEFAULT_DIR)),
            pause_file=Path(env("MCFL_PAUSE_FILE", DEFAULT_PAUSE_FILE)),
            prices_db=_prices_db(),
            derive_1d=derive,
        )

    @property
    def wants_alts(self) -> bool:
        """Whether any enabled pattern needs the alt universe fetched."""
        return any(p in self.patterns for p in ("DISPLACE_C_LOW12", "M1", "B"))

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"


def _prices_db() -> Path:
    """Where the prices service stores bars: `PRICES_DB`, else `PRICES_DIR`/prices.db."""
    db = env("PRICES_DB")
    if db:
        return Path(db)
    return Path(env("PRICES_DIR", ".data/prices")) / "prices.db"


def _intervals(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    got = names(name, default)
    known = tuple(i for i in got if i in INTERVALS)
    if len(known) != len(got):
        log.warning("config: %s has unknown interval(s) - using %s", name, ", ".join(known))
    return known or default
