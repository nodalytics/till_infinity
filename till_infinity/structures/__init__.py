"""Online models over the price data: what is unusual, and what has changed.

The numeric half of the project. It watches `prices.quotes` and `prices.bars`,
learns continuously, and publishes what it finds — without an API key, without
a language model, and without stopping when either is unavailable.

    prices ──▶ structures ──┬──▶ structures.signals ──▶ agents ──▶ alerts
                            └──▶ alerts (unambiguous only)

Every feature is **relative to the other venues**. An anomaly detector fed one
venue's spread learns what is normal for that venue, which is useful and not
the point: the project collects six venues because the disagreement between
them carries information no single feed does. So a venue is measured against
the median of the others, taken without it.

```python
from till_infinity.bus import Bus
from till_infinity.structures import watch

await watch(Bus(redis_url="redis://localhost:6379"))
```
"""

from __future__ import annotations

from . import confluence, patterns, pips, reactions, timing
from .anomaly import Detector
from .config import DRIFT_INTERVALS, INTERVALS, Settings
from .confluence import Zone, combine
from .drift import Drift
from .engine import Call, Engine
from .facto import Example, Model, Report, dataset, evaluate, fit
from .features import Book, Books, Reading
from .levels import Level, Outcome, Side, State, nearby
from .models import Consensus, Shape, Signal
from .reactions import Features, Inference, Memory, Touch, Tracker
from .service import TOPICS, UNAMBIGUOUS, BarConsensus, Watcher, watch
from .store import load, save
from .timing import Approach, bars_to_reach, estimate, next_levels, probability_within
from .volatility import Volatility

__all__ = [
    "DRIFT_INTERVALS",
    "INTERVALS",
    "TOPICS",
    "UNAMBIGUOUS",
    "Approach",
    "BarConsensus",
    "Book",
    "Books",
    "Call",
    "Consensus",
    "Detector",
    "Drift",
    "Engine",
    "Example",
    "Features",
    "Inference",
    "Level",
    "Memory",
    "Model",
    "Outcome",
    "Reading",
    "Report",
    "Settings",
    "Shape",
    "Side",
    "Signal",
    "State",
    "Touch",
    "Tracker",
    "Volatility",
    "Watcher",
    "Zone",
    "bars_to_reach",
    "combine",
    "confluence",
    "dataset",
    "estimate",
    "evaluate",
    "facto",
    "fit",
    "levels_near",
    "load",
    "nearby",
    "next_levels",
    "patterns",
    "pips",
    "probability_within",
    "reactions",
    "save",
    "timing",
    "watch",
    "zones_for",
]


def levels_near(engine: Engine, feed: str, price: float, within_vol: float = 3.0) -> list[Level]:
    """Levels close enough to `price` to matter, nearest first.

    Lives here rather than on the engine because it spans intervals: a price
    can sit against a 5m swing level and a daily pivot at once, and which of
    those matters is exactly what the caller is asking.
    """
    # The reference estimate, not any one timeframe's: ranking levels from
    # different timeframes needs one denominator or the distances are not
    # comparable with each other.
    vol = engine.reference(feed)
    return nearby(engine.levels(feed), price, vol, within_vol)


def zones_for(engine: Engine, feed: str) -> list[Zone]:
    """Confluence zones for one instrument, each level measured on its own
    timeframe.

    The resolver is the point: a 4h level's zone must be computed in 4h
    volatility or it is compared against the others on the wrong scale.
    """
    return combine(
        engine.levels(feed),
        engine.reference(feed),
        volatility=lambda level: engine.vol.of(feed, level.interval),
    )
