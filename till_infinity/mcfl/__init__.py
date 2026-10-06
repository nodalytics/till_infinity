"""MCFL pattern alerts: the desk's measured patterns, published as alerts only.

    prices.bars, alt universe ──▶ mcfl ──▶ alerts ──▶ notifications

The patterns are the MCFL productions of `research/mcfl/`, ported (`events.py`,
`trade.py`) and held to the research parser by `tests/test_mcfl_parity.py`.
Two of them carry a measured edge - DISPLACE_C at a 12-bar low on crypto 1d
with its structure exit, and the BTC market mirror - and every card says
which, per timeframe, or says plainly that no edge was found (`registry.py`).

**It never trades.** Nothing here imports `trading` or reaches a broker; the
only topic it publishes is `alerts`, and every card is marked "paper alert,
not a trade instruction".

Switches (see `service.py`): `MCFL_ENABLED=1` starts it with the stack;
`MCFL_PAUSE_FILE` (default `.data/mcfl.off`) pauses it at runtime while the
file exists. Patterns: `MCFL_PATTERNS`; timeframes: `MCFL_TIMEFRAMES`
(`config.py`).
"""

from .config import Settings
from .desk import Desk, Series
from .registry import DEFAULT_ENABLED, PATTERNS
from .service import EFFECT, Service, classify, watch

__all__ = [
    "DEFAULT_ENABLED",
    "EFFECT",
    "PATTERNS",
    "Desk",
    "Series",
    "Service",
    "Settings",
    "classify",
    "watch",
]
