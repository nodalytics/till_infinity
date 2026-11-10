"""Which of the deployed instruments are currently volatile enough to scalp.

**Two quantities that move at different speeds, so they are measured in two
places.** Cost barely moves: a broker's spread on EURUSD is a property of the
broker and the month, which is why `strategies/spreads.py` decays its estimate
per observation rather than per day. Volatility moves within the session -
`seasonality-belongs-on-q` measured FX intraday volatility peaking 14-15 UTC
at **3x**. So choosing *which* instruments are affordable at all belongs to a
survey that runs occasionally over the broker's whole book
(`research/harness/volatile.py`, 725 symbols), and choosing which of those are
volatile *now* belongs here, on a timer, inside the running node.

**This screens the deployed universe and not the broker's.** The adapter loads
the instruments `TRADING_SYMBOLS` names, so an actor can only request bars for
those - ranking 725 live would mean loading 725 instruments and paying a quote
poller for each, which is the cost `node/desks.PER_CORE` exists to bound. Said
plainly because "screens every instrument the broker offers" is what a reader
would otherwise assume.

## What the ranking is, and what it is not

The range, not the close-to-close standard deviation: `drive-q-from-the-range`
measured the range-vs-close estimator ratio at **0.648 within strata on FX**
and 0.667 on 371 of 392 equities, and records that the advantage *grows as the
window shortens* - which is the regime a scalp lives in. The median of the
window and not the mean, because a scalp meets the typical bar and one news bar
would otherwise set the ranking.

In basis points of price, so an instrument at 1.09 and one at 74,000 are
comparable at all.

**A high rank is not an edge.** `auc-is-free-on-volatility-targets` is the
standing warning: predicting volatility reads **0.805 on a constant-vol
process** and 0.525 within strata, so a ranking by volatility is mostly a
ranking of what is mechanically volatile. What this buys a scalp is that the
move is large relative to a toll that is paid once - a necessary condition, and
`research/docs/` already records a scalping survey finding "nothing affordable
beats its coin", so it is nowhere near sufficient.

It reports and refuses; it never places. A desk reads the ranking through
`Desk._volatile_enough`.
"""

from __future__ import annotations

import statistics
from collections import deque
from datetime import timedelta
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.model.data import Bar, BarType

from ..utils import topics

#: Bars of history each ranking is computed over. 120 of them is thirty hours
#: at 15m and ten at 5m - long enough that one session does not set the
#: ranking, short enough that yesterday's regime does not.
WINDOW = 120

#: Seconds between rankings. Volatility moves within the session but not
#: within the minute, and each pass costs one bar request per instrument, so
#: this is deliberately slower than a bar: `tis-research-jobs-starve-the-
#: service` is a measured outcome on a two-core box.
EVERY = 900.0

#: The share of the ranking a desk may trade. 0.2 is the top fifth.
SHARE = 0.2


class ScreenConfig(ActorConfig, frozen=True):
    """What to rank, how often, and how much of it to admit."""

    bar_types: tuple[str, ...] = ()
    window: int = WINDOW
    every: float = EVERY
    share: float = SHARE


class VolatileScreen(Actor):
    """Ranks the deployed instruments by range volatility, on a timer.

    Publishes `topics.VOLATILE` as `{"share": float, "ranked": [...],
    "admitted": [...], "by_feed": {...}}` - the whole ranking and not only the
    admitted head, because a desk refused for being outside the top fifth
    should be able to say how far outside it was.
    """

    def __init__(self, config: ScreenConfig) -> None:
        super().__init__(config)
        self._cfg = config
        #: Rolling ranges per bar type, by `str(bar_type)`.
        self._ranges: dict[str, deque[float]] = {}
        self._rankings = 0

    def on_start(self) -> None:
        for raw in self._cfg.bar_types:
            bar_type = BarType.from_str(raw)
            self._ranges[str(bar_type)] = deque(maxlen=max(20, self._cfg.window))
            self.subscribe_bars(bar_type)
        if not self._cfg.bar_types:
            # A screener with nothing to rank is a timer that logs an empty
            # list for ever. Said once, loudly, rather than discovered by a
            # reader wondering why every desk is refused.
            self.log.warning(
                "VolatileScreen has no bar types, so every desk reading its "
                "ranking will be refused as not volatile. Set its bar types or "
                "do not register it."
            )
        self.clock.set_timer(
            name="volatile-screen",
            interval=timedelta(seconds=max(60.0, self._cfg.every)),
            callback=lambda _event: self._rank(),
        )
        self.log.info(
            f"screening {len(self._cfg.bar_types)} bar type(s) every "
            f"{self._cfg.every:.0f}s, admitting the top {self._cfg.share:.0%}"
        )

    def on_bar(self, bar: Bar) -> None:
        """One closed bar's range, kept against its own bar type."""
        found = self._ranges.get(str(bar.bar_type))
        if found is None:
            return
        span = float(bar.high) - float(bar.low)
        if span > 0.0:
            # Relative to the close, so instruments four orders of magnitude
            # apart are on one scale. Basis points, as the rest of this desk
            # states volatility.
            close = float(bar.close)
            if close > 0.0:
                found.append(10_000.0 * span / close)

    def _rank(self) -> None:
        """Publish the ranking, or say why there is not one."""
        ready = {
            name: statistics.median(rows)
            for name, rows in self._ranges.items()
            if len(rows) >= min(20, self._cfg.window)
        }
        if not ready:
            self.log.warning(
                f"volatile screen has no instrument with {min(20, self._cfg.window)} "
                f"bars yet, of {len(self._ranges)} subscribed - nothing is admitted "
                f"until one does"
            )
            return
        ranked = sorted(ready.items(), key=lambda kv: -kv[1])
        cut = max(1, round(len(ranked) * self._cfg.share))
        admitted = [name for name, _ in ranked[:cut]]
        self._rankings += 1
        topics.publish(
            self,
            topics.VOLATILE,
            {
                "share": float(self._cfg.share),
                "ranked": [{"bar_type": name, "range_bps": value} for name, value in ranked],
                "admitted": admitted,
                "rankings": self._rankings,
            },
        )
        head = ", ".join(f"{name.split('.')[0]} {value:.0f}bps" for name, value in ranked[:cut])
        self.log.info(
            f"volatile screen: top {self._cfg.share:.0%} of {len(ranked)} is {cut} - {head}"
        )


def ranked_bar_types(payload: Any) -> list[str]:
    """The admitted bar types from a `VOLATILE` payload, or an empty list.

    A function rather than a method so a desk can read the payload without
    importing the actor, and so the shape is asserted in one place: a consumer
    guessing at a producer's dict is how `statespace.proposals` came to have a
    producer and no consumer for weeks.
    """
    if not isinstance(payload, dict):
        return []
    found = payload.get("admitted")
    return [str(name) for name in found] if isinstance(found, list) else []


__all__ = ["EVERY", "SHARE", "WINDOW", "ScreenConfig", "VolatileScreen", "ranked_bar_types"]
