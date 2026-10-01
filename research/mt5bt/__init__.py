"""A backtester for MT5 CFDs: bid/ask fills, per-bar spread, commission, swap and the broker's lot grid.

See research/mt5bt/README.md.
"""

from .data import Book, bars_from_ticks, load_bars, load_specs, load_ticks
from .engine import Costs, Signal, run
from .nulls import garch_walk, random_null, t_walk
from .report import summary
from .audit import lookahead

__all__ = [
    "Book",
    "bars_from_ticks",
    "Costs",
    "Signal",
    "garch_walk",
    "load_bars",
    "load_specs",
    "load_ticks",
    "lookahead",
    "random_null",
    "run",
    "summary",
    "t_walk",
]
