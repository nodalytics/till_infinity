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

from .anomaly import Detector
from .config import INTERVALS, Settings
from .drift import Drift
from .features import Book, Books, Reading
from .models import Consensus, Shape, Signal
from .service import TOPICS, UNAMBIGUOUS, BarConsensus, Watcher, watch
from .store import load, save

__all__ = [
    "INTERVALS",
    "TOPICS",
    "UNAMBIGUOUS",
    "BarConsensus",
    "Book",
    "Books",
    "Consensus",
    "Detector",
    "Drift",
    "Reading",
    "Settings",
    "Shape",
    "Signal",
    "Watcher",
    "load",
    "save",
    "watch",
]
