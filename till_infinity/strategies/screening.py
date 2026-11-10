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
from .timeframes import seconds_of

#: Bars of history each ranking is computed over. 120 of them is thirty hours
#: at 15m and ten at 5m - long enough that one session does not set the
#: ranking, short enough that yesterday's regime does not.
WINDOW = 120

#: Seconds between rankings. Volatility moves within the session but not
#: within the minute, and each pass costs one bar request per instrument, so
#: this is deliberately slower than a bar: `tis-research-jobs-starve-the-
#: service` is a measured outcome on a two-core box.
EVERY = 900.0

#: The share of the volatility ranking a desk may trade. 0.3 is the top third.
SHARE = 0.3

#: The share of the **cost** ranking admitted as well - the cheapest fifth of
#: the book by round-trip spread, measured in the same basis points the range
#: is.
#:
#: **Admitted as a union with the volatility set, not an intersection**, which
#: is the operator's call and is the permissive direction: an instrument gets
#: in by moving a lot *or* by being cheap. The per-trade cost gate still
#: refuses anything that cannot pay, so the screen is the coarse filter and
#: the gate does the fine work with the actual numbers.
#:
#: **The two criteria pull against each other on this book**, which is why the
#: cost half is worth having at all. Ranking by range selects for cost too,
#: because the spread here scales with the range: the first live ranking, on
#: 2026-11-10, admitted oil, crypto and exotic metals - and `BNBUSD`, which
#: cannot clear its own cost gate at 18% of target against a 10% ceiling.
#: Exotic round trips run 0.40 to 0.97 of a **whole bar range**.
COST_SHARE = 0.2


class ScreenConfig(ActorConfig, frozen=True):
    """What to rank, how often, and how much of it to admit."""

    bar_types: tuple[str, ...] = ()
    window: int = WINDOW
    every: float = EVERY
    share: float = SHARE
    #: The cheapest share admitted beside the loudest, as a union. 0 turns the
    #: cost half off and leaves the volatility ranking alone.
    cost_share: float = COST_SHARE
    #: Bars to request per instrument on start. **Without this the gate is a
    #: five-hour trading halt after every deploy**: `_rank` needs 20 bars of an
    #: instrument's own before it will rank it, which at 15m is five hours of
    #: live bars, and `Desk._volatile_enough` refuses everything until a
    #: ranking exists. Measured on 2026-11-10 - the screen came up at 19:04,
    #: and at 19:19 it reported "no instrument with 20 bars yet, of 38
    #: subscribed" while four signals were refused as `no-ranking`.
    warm_bars: int = 40


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
        if self._cfg.warm_bars > 0:
            self._warm()
        self.clock.set_timer(
            name="volatile-screen",
            interval=timedelta(seconds=max(60.0, self._cfg.every)),
            callback=lambda _event: self._rank(),
        )
        self.log.info(
            f"screening {len(self._cfg.bar_types)} bar type(s) every "
            f"{self._cfg.every:.0f}s, admitting the top {self._cfg.share:.0%}"
        )

    def _warm(self) -> None:
        """Request enough history that the first ranking is not five hours away.

        Asked for as a **span of each bar type** rather than a date, so one
        number covers every interval the deployment screens - the same shape
        `statespace/actor.py` uses, and for the same reason.

        Never raises: a screen that fails to warm still ranks from live bars,
        and taking the node down over a history request would turn a slow gate
        into no desk at all.
        """
        for raw in self._cfg.bar_types:
            try:
                bar_type = BarType.from_str(raw)
                span = seconds_of(bar_type) * self._cfg.warm_bars
                if span <= 0:
                    continue
                self.request_bars(
                    bar_type,
                    self.clock.utc_now() - timedelta(seconds=span),
                    limit=self._cfg.warm_bars,
                )
            except Exception as exc:  # pragma: no cover - the transport's shapes
                self.log.warning(f"could not request history for {raw}: {exc}")

    def on_historical_data(self, data: Any) -> None:
        """Fold requested history into the ranges, through `on_bar`.

        **Nautilus delivers a `request_bars` response here, not to `on_bar`**,
        so without this handler the request is answered into a no-op and the
        screen warms at the speed of the live market. It also delivers one bar
        per call and per *bar type* rather than per requester, which is
        harmless here - the screen subscribes to every bar type it ranks, and
        `on_bar` keys each range by its own - but it is why there is no
        de-duplication: a repeated bar moves a median of 20+ ranges by less
        than the ranking's own resolution, and dropping a genuine bar would be
        worse.
        """
        rows = data if isinstance(data, (list, tuple)) else [data]
        for row in rows:
            if isinstance(row, Bar):
                self.on_bar(row)

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

    def _costs(self, names: list[str]) -> dict[str, float]:
        """Round-trip cost per bar type in basis points, where a quote exists.

        Read from the cache rather than subscribed, because one read per bar
        type every `every` seconds is free and a quote subscription for the
        whole book is not: `the-healthcheck-is-the-cpu-load` measures the
        instance at 1.2 cores for 2s every 60s on two cores.

        **The same basis points the range is in**, so the two rankings are
        comparable and their ratio - how many round trips wide a bar is - is
        the quantity a scalp actually needs. An instrument with no quote is
        absent rather than zero: a missing cost ranked as free would admit
        exactly the instruments nothing can be priced on.
        """
        out: dict[str, float] = {}
        for name in names:
            try:
                quote = self.cache.quote_tick(BarType.from_str(name).instrument_id)
            except Exception:  # pragma: no cover - the cache's shapes
                continue
            if quote is None:
                continue
            bid, ask = float(quote.bid_price), float(quote.ask_price)
            mid = 0.5 * (bid + ask)
            if mid > 0.0 and ask >= bid:
                out[name] = 10_000.0 * (ask - bid) / mid
        return out

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
        loud = [name for name, _ in ranked[:cut]]

        # **A union, not an intersection.** An instrument gets in by moving a
        # lot *or* by being cheap, and the per-trade cost gate still refuses
        # anything that cannot pay - so this is the coarse filter and the gate
        # does the fine work with the actual numbers.
        costs = self._costs(list(ready))
        cheap: list[str] = []
        if self._cfg.cost_share > 0.0 and costs:
            by_cost = sorted(costs.items(), key=lambda kv: kv[1])
            cheap = [
                name for name, _ in by_cost[: max(1, round(len(by_cost) * self._cfg.cost_share))]
            ]
        admitted = list(dict.fromkeys(loud + cheap))

        self._rankings += 1
        topics.publish(
            self,
            topics.VOLATILE,
            {
                "share": float(self._cfg.share),
                "cost_share": float(self._cfg.cost_share),
                "ranked": [
                    {
                        "bar_type": name,
                        "range_bps": value,
                        # Both numbers and their ratio, because a desk refused
                        # for being outside the head should be able to say how
                        # far outside and on which axis.
                        **(
                            {
                                "cost_bps": costs[name],
                                "ranges_per_cost": value / costs[name] if costs[name] > 0 else 0.0,
                            }
                            if name in costs
                            else {}
                        ),
                    }
                    for name, value in ranked
                ],
                "admitted": admitted,
                "loud": loud,
                "cheap": cheap,
                "rankings": self._rankings,
            },
        )
        head = ", ".join(f"{name.split('.')[0]} {value:.0f}bps" for name, value in ranked[:cut])
        line = f"volatile screen: top {self._cfg.share:.0%} of {len(ranked)} is {cut} - {head}"
        if self._cfg.cost_share > 0.0:
            # Said every pass, because the union's size is the whole question:
            # if the two criteria are anti-correlated the union is close to no
            # filter at all, and that is visible here rather than inferred.
            line += (
                f"; + cheapest {self._cfg.cost_share:.0%} is {len(cheap)}, "
                f"union {len(admitted)} of {len(ranked)}"
            )
            if len(costs) < len(ready):
                line += f" ({len(ready) - len(costs)} unquoted, cost-ineligible)"
        self.log.info(line)


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
