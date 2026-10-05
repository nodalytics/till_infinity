"""The service: closed bars in from two places, alert cards out to `alerts`.

    prices.bars ──▶ (store read) ──┐
                                   ├──▶ Desk ──▶ chart ──▶ alerts ──▶ notifications
    alt universe (ccxt, 4h/1d) ────┘

**Alert-only.** This service publishes to `alerts` and nowhere else. It does
not import `trading`, does not publish `structures.signals`, and has no path to
a broker; every card ends "paper alert, not a trade instruction".

## Two inputs

* `prices.bars` - whatever the prices service already carries (FX, metals,
  indices, energy, BTC/ETH/SOL, Deriv when the broker feed is on). A notice is
  only a notice, so the series is read back from the prices store, which the
  prices service writes before it announces. One venue per instrument and
  timeframe is adopted and kept until it goes quiet.
* the alt universe (`universe.py`) - the coins the market mirror was validated
  on, fetched by this service on 4h and 1d, once per closed bar, and **never
  written to the prices store or published on `prices.bars`**.

## Switches

* **Off unless asked for.** `MCFL_ENABLED=1` in the stack's environment starts
  it (`stack.Plan.mcfl`); unset, the service never starts - nothing is polled,
  rendered or sent. Changing it needs a restart.
* **Paused at runtime by a file.** While `MCFL_PAUSE_FILE` (default
  `.data/mcfl.off`) exists, nothing is fetched and nothing is sent; incoming
  bar notices are dropped. It is checked before every fetch cycle, every bar
  notice and every send, so `touch .data/mcfl.off` takes effect within one
  message and `rm` resumes it without a restart. **A resume does not replay
  what was missed**: every bar that closed before the resume is processed
  quietly - trades stepped, nothing alerted - so the state re-seeds from the
  current bars. The pause and the resume are each logged once.

## Effects

`mcfl.alerts` is declared on start and fired per card published, so an
enabled service that never alerts shows up in `stack.json`'s `inert` list
(see `shared/effects.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from ..bus import ALERTS, BARS, Bus
from ..logging import get_logger
from ..prices.models import INTERVALS
from ..shared import effects
from . import chart as charts
from . import state as st
from .cards import Card
from .config import Settings
from .desk import Desk, Series
from .tokens import Bars, resample
from .universe import TARGET, Fetcher, default_venues, requests_per_day

log = get_logger(__name__)

EFFECT = "mcfl.alerts"

#: Instruments the prices service carries, by class. Anything unnamed that
#: arrives from ccxt is crypto; from the broker, a Deriv synthetic; else FX.
_CLASSES: dict[str, str] = {
    "btc": "crypto",
    "eth": "crypto",
    "sol": "crypto",
    "gold": "metals",
    "silver": "metals",
    "wti": "energy",
    "brent": "energy",
    **dict.fromkeys(
        (
            "us100",
            "spx500",
            "ger40",
            "uk100",
            "us30",
            "us2000",
            "jp225",
            "fra40",
            "eu50",
            "aus200",
            "hk50",
        ),
        "indices",
    ),
}


def classify(feed: str, source: str, ticker: str) -> tuple[str, str]:
    """(asset class, display symbol) for a prices feed."""
    feed = feed.lower()
    if source == "ccxt":
        base = ticker.split("/", maxsplit=1)[0].split(":", maxsplit=1)[0].upper()
        return "crypto", base or feed.upper()
    if feed in _CLASSES:
        return _CLASSES[feed], feed.upper()
    if source == "broker":
        return "deriv", feed.upper()
    return "fx", feed.upper()


def read_bars(
    db: Path, source: str, feed: str, venue: str, ticker: str, interval: str, limit: int
) -> Bars:
    """The newest `limit` stored bars of one series, oldest first. Read-only."""
    if not Path(db).exists():
        return Bars.of([])
    with contextlib.closing(sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT ts, open, high, low, close FROM bars"
            " WHERE source=? AND feed=? AND venue=? AND ticker=? AND interval=?"
            " ORDER BY ts DESC LIMIT ?",
            (source, feed, venue, ticker, interval, limit),
        ).fetchall()
    return Bars.of(reversed(rows))


class Service:
    """Bars in, cards out. See the module docstring for what it will not do."""

    def __init__(
        self,
        bus: Bus,
        settings: Settings | None = None,
        *,
        group: str = "mcfl",
        fetcher: Fetcher | None = None,
        clock: Callable[[], float] = time.time,
        render: Callable[[charts.Spec], bytes | None] | None = None,
    ) -> None:
        self.bus = bus
        self.settings = settings or Settings.from_env()
        self.group = group
        self.clock = clock
        self.render = render or charts.render
        self.desk = Desk(self.settings, st.load(self.settings.state_file))
        self.fetcher = fetcher
        self.sent = 0
        #: Set when the pause file goes away: bars closed before it are quiet.
        self.quiet_before = 0.0
        self._paused: bool | None = None
        #: series id -> when its last notice arrived, for venue adoption.
        self._heard: dict[str, float] = {}
        self._started = clock()
        effects.declare(EFFECT, enabled=True)

    # --------------------------------------------------------------- switches

    def paused(self) -> bool:
        """Whether the pause file exists. Logs each change once; a resume
        re-seeds by making everything closed before now quiet."""
        now_paused = self.settings.pause_file.exists()
        if now_paused != self._paused:
            if now_paused:
                log.warning(
                    "mcfl: paused - %s exists; fetching and sending nothing",
                    self.settings.pause_file,
                )
            elif self._paused is not None:
                self.quiet_before = self.clock()
                log.warning(
                    "mcfl: resumed - %s is gone; bars closed before now stay quiet",
                    self.settings.pause_file,
                )
            self._paused = now_paused
        return now_paused

    # ------------------------------------------------------------------ run

    async def run(self, *, messages: int | None = None) -> int:
        """Consume `prices.bars` and poll the alt universe until stopped."""
        subscription = self.bus.subscribe(BARS, group=self.group)
        log.info(
            "mcfl: patterns %s on %s; alt universe %d coins on %s (%s kline requests/day)",
            ",".join(self.settings.patterns),
            ",".join(self.settings.timeframes),
            len(self.settings.alt_coins) if self.settings.wants_alts else 0,
            ",".join(self.settings.alt_timeframes),
            f"{requests_per_day(len(self.settings.alt_coins), self.settings.alt_timeframes):,}"
            if self.settings.wants_alts
            else "0",
        )
        async with asyncio.TaskGroup() as group:
            poller = None
            if self.settings.wants_alts and self.settings.alt_timeframes:
                poller = group.create_task(self.poll_alts(), name="mcfl:alts")
            seen = 0
            async for message in subscription:
                try:
                    await self.on_bar(message.payload)
                except Exception as exc:  # one bad series must not stop the rest
                    log.warning("mcfl: bar notice failed: %r", exc, exc_info=True)
                seen += 1
                if messages is not None and seen >= messages:
                    break
            if poller is not None:
                poller.cancel()
        return self.sent

    async def on_bar(self, payload: dict) -> int:
        """One `prices.bars` notice. Returns the cards it sent."""
        if self.paused():
            return 0
        interval = str(payload.get("interval") or "")
        feed = str(payload.get("feed") or "")
        if not feed or not payload.get("closed", True):
            return 0
        source = str(payload.get("source") or "")
        venue = str(payload.get("venue") or "")
        ticker = str(payload.get("ticker") or "")
        sent = 0
        if interval in self.settings.timeframes:
            sent += await self._prices_series(source, feed, venue, ticker, interval)
        if self.settings.derive_1d and "1d" in self.settings.timeframes:
            sent += await self._derived_day(payload, source, feed, venue, ticker, interval)
        return sent

    async def _prices_series(
        self, source: str, feed: str, venue: str, ticker: str, interval: str
    ) -> int:
        sid = f"bars:{source}:{venue}:{ticker}:{interval}"
        if not self._adopt(feed, interval, sid):
            return 0
        klass, symbol = classify(feed, source, ticker)
        series = Series(sid, symbol, interval, klass, f"{venue}:{ticker}")
        limit = self._limit(series)
        bars = await asyncio.to_thread(
            read_bars, self.settings.prices_db, source, feed, venue, ticker, interval, limit
        )
        return await self.process(series, bars)

    async def _derived_day(
        self, payload: dict, source: str, feed: str, venue: str, ticker: str, interval: str
    ) -> int:
        """1d built from the finest stored bars, when the stack does not collect 1d."""
        if interval not in ("1h", "4h"):
            return 0
        sub = INTERVALS[interval].seconds
        when = payload.get("time")
        if not isinstance(when, int | float) or (int(when) + sub) % 86_400:
            return 0  # only the sub-bar that completes a UTC day
        sid = f"bars:{source}:{venue}:{ticker}:1d<{interval}"
        if not self._adopt(feed, "1d", sid):
            return 0
        klass, symbol = classify(feed, source, ticker)
        series = Series(sid, symbol, "1d", klass, f"{venue}:{ticker} ({interval} resampled)")
        limit = self.settings.lookback * (86_400 // sub)
        fine = await asyncio.to_thread(
            read_bars, self.settings.prices_db, source, feed, venue, ticker, interval, limit
        )
        return await self.process(series, resample(fine, 86_400, sub))

    def _adopt(self, feed: str, interval: str, sid: str) -> bool:
        """Whether this series speaks for its instrument and timeframe.

        The first venue heard is adopted and kept until it has been silent for
        three bars while another speaks - one series per instrument, so the
        same candle on six venues is one alert, not six.
        """
        now = self.clock()
        self._heard[sid] = now
        slot = f"{feed}|{interval}"
        held = self.desk.state.adopted.get(slot)
        if held is None or held == sid:
            self.desk.state.adopted[slot] = sid
            return True
        quiet_for = now - self._heard.get(held, self._started)
        if quiet_for > 3 * INTERVALS[interval.split("<", maxsplit=1)[0]].seconds:
            log.info("mcfl: %s now read from %s (%s went quiet)", slot, sid, held)
            self.desk.state.adopted[slot] = sid
            return True
        return False

    def _limit(self, series: Series) -> int:
        """Bars to read: the window, plus any bars missed since the last one."""
        last = self.desk.state.last.get(series.id)
        behind = 0
        if last is not None:
            behind = int((self.clock() - last) // series.seconds)
        return self.settings.lookback + min(max(behind, 0), self.settings.lookback)

    # ------------------------------------------------------------ the alts

    async def poll_alts(self) -> None:
        """Fetch the alt universe once now, then after every 4h / 1d close."""
        await self.start_fetcher()
        fetcher = self.fetcher
        assert fetcher is not None
        await fetcher.open()
        try:
            tfs = self.settings.alt_timeframes
            await self._cycle(tfs)
            while True:
                now = self.clock()
                due = min((now // INTERVALS[tf].seconds + 1) * INTERVALS[tf].seconds for tf in tfs)
                await asyncio.sleep(max(1.0, due + self.settings.poll_delay - now))
                ready = tuple(tf for tf in tfs if int(due) % INTERVALS[tf].seconds == 0)
                await self._cycle(ready)
        finally:
            await fetcher.close()

    async def _cycle(self, timeframes: tuple[str, ...]) -> None:
        """A cycle that cannot end the poller: a bad pass waits for the next close."""
        try:
            await self.alt_cycle(timeframes)
        except Exception as exc:
            log.warning(
                "mcfl: alt cycle on %s failed: %r", ",".join(timeframes), exc, exc_info=True
            )

    async def alt_cycle(self, timeframes: tuple[str, ...]) -> int:
        """One pass over the alt universe on these timeframes."""
        if self.paused():
            return 0
        fetcher = self.fetcher
        if fetcher is None:
            return 0
        coins = tuple(dict.fromkeys((TARGET, *self.settings.alt_coins)))
        sent = 0
        for tf in timeframes:
            for coin in coins:
                if self.paused():
                    return sent
                if coin == TARGET and tf != "1d" and coin not in self.settings.alt_coins:
                    continue
                got = await fetcher.bars(coin, tf, self.settings.lookback)
                if got is None:
                    continue
                venue, rows = got
                bars = Bars.of([(b.time, b.open, b.high, b.low, b.close) for b in rows])
                sent += await self.process(
                    Series(f"alt:{coin}:{tf}", coin, tf, "crypto", venue), bars
                )
        return sent

    async def start_fetcher(self) -> None:
        if self.fetcher is None:
            self.fetcher = Fetcher(default_venues(self.settings.binance_url))

    # -------------------------------------------------------------- sending

    async def process(self, series: Series, bars: Bars) -> int:
        """Run the desk over a series, send what it produced, save the state."""
        found = self.desk.observe(series, bars, self.clock(), self.quiet_before)
        self.desk.state.prune(self.clock())
        sent = 0
        for card in found:
            sent += await self.send(card)
        st.save(self.desk.state, self.settings.state_file)
        return sent

    async def send(self, card: Card) -> int:
        if self.paused():
            log.info("mcfl: paused - dropped %s", card.key)
            return 0
        if self.settings.charts and card.chart is not None:
            try:
                card.attach(await asyncio.to_thread(self.render, card.chart))
            except Exception as exc:  # the picture is optional; the alert is not
                log.debug("mcfl: chart failed for %s: %s", card.key, exc)
        await self.bus.publish(ALERTS, card.payload, source="mcfl")
        effects.fired(EFFECT)
        self.sent += 1
        log.info("mcfl: alert %s", card.payload.get("title"))
        return 1


async def watch(bus: Bus, *, settings: Settings | None = None, group: str = "mcfl") -> int:
    """Run the pattern alerts over the bus. The stack's entry point."""
    return await Service(bus, settings, group=group).run()
