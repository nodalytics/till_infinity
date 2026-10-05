"""The alert engine: closed bars in, cards out. No I/O.

`Desk.observe` takes one series' closed bars and returns the cards its new
bars produce - entries, exits, the market mirror - updating `State` as it
goes. It reads no store, opens no socket and publishes nothing, which is what
lets the tests drive a restart, a pause and a duplicate source through it bar
by bar. `service.py` does the I/O around it.

## One bar at a time

Every bar newer than the series' `last` is processed in order, each against the
window of bars that ended with it. That is the only way an open trade can be
stepped exactly as the research loop steps it, and the only way a burst of
bars - a catch-up after a restart - gives the same events as the bars arriving
one by one.

## When a bar is quiet

A bar is processed **quietly** - its trades stepped, its signals not alerted,
no trade opened - when it closed too long ago to act on (`FRESH_SHARE` of a
bar, at least `FRESH_MIN` seconds), or before `quiet_before`, which the service
sets when it resumes from a pause. So a resume or a long restart re-seeds from
the current bars instead of sending what it missed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..logging import get_logger
from ..prices.models import INTERVALS
from . import cards
from .config import Settings
from .detect import Finding, detect
from .state import State
from .tokens import Bars, frames
from .trade import Exit, Open, against
from .universe import TARGET

log = get_logger(__name__)

#: A bar's alerts go out only within this share of a bar after it closed...
FRESH_SHARE = 0.25
#: ...and never less than this many seconds, so a 15m bar has its ten minutes.
FRESH_MIN = 600.0
#: Alts signalling on one daily close before the breadth rule fires.
BREADTH_MIN = 3
#: Days the breadth position is held.
HOLD_B = 5
DAY = 86_400

#: Patterns that open the frozen trade (and so have exits).
TRADES = ("DISPLACE_C_LOW12", "DISPLACE_C_LOW12_X")


@dataclass(frozen=True, slots=True)
class Series:
    """One series of closed bars, as the engine knows it."""

    id: str
    symbol: str
    timeframe: str
    klass: str
    venue: str = ""

    @property
    def seconds(self) -> int:
        return INTERVALS[self.timeframe].seconds


class Desk:
    """Patterns, trades and the mirror over every series the service sees."""

    def __init__(self, settings: Settings, state: State | None = None) -> None:
        self.settings = settings
        self.state = state or State()

    # ------------------------------------------------------------- the loop

    def observe(
        self, series: Series, bars: Bars, now: float, quiet_before: float = 0.0
    ) -> list[cards.Card]:
        """Process every bar of `series` not seen before; return the cards to send."""
        if not len(bars):
            return []
        last = self.state.last.get(series.id)
        if last is None:
            # First sight: the newest bar is the first one this service owns.
            # Older bars were somebody else's moment; the freshness guard
            # decides whether this one still is.
            last = int(bars.ts[-2]) if len(bars) > 1 else int(bars.ts[-1]) - series.seconds
        out: list[cards.Card] = []
        for i in map(int, np.flatnonzero(bars.ts > last)):
            start = max(0, i + 1 - self.settings.lookback)
            window = Bars(
                bars.ts[start : i + 1],
                bars.open[start : i + 1],
                bars.high[start : i + 1],
                bars.low[start : i + 1],
                bars.close[start : i + 1],
            )
            closed = int(bars.ts[i]) + series.seconds
            fresh = closed >= now - max(FRESH_MIN, FRESH_SHARE * series.seconds)
            quiet = not fresh or closed <= quiet_before
            out += self._step(series, window, quiet)
            if series.timeframe == "1d" and series.symbol == TARGET:
                out += self._btc_day(window, quiet)
            if not quiet:
                out += self._findings(series, window)
            self.state.last[series.id] = int(bars.ts[i])
        return out

    # ----------------------------------------------------------- the trades

    def _step(self, series: Series, window: Bars, quiet: bool) -> list[cards.Card]:
        last = len(window) - 1
        ts = int(window.ts[last])
        mine = [
            (k, t)
            for k, t in self.state.trades.items()
            if t["series"] == series.id and t["signal_ts"] < ts
        ]
        if not mine:
            return []
        shifts = against(frames(window))
        out: list[cards.Card] = []
        for k, t in mine:
            trade = Open.from_dict(t["open"])
            done = trade.step(
                float(window.open[last]),
                float(window.high[last]),
                float(window.low[last]),
                float(window.close[last]),
                last in shifts[trade.side],
            )
            t["open"] = trade.to_dict()
            if done is None:
                continue
            del self.state.trades[k]
            log.info("mcfl: %s exited %s %+.2fR", k, done.reason, done.r)
            if quiet:
                self._close_mirrors(k, ts, done, quiet=True)
                continue
            if t.get("alerted"):
                hit = np.flatnonzero(window.ts == t["signal_ts"])
                out.append(
                    cards.exited(
                        t["rule"],
                        series.symbol,
                        series.timeframe,
                        k,
                        trade,
                        done,
                        window,
                        last,
                        int(hit[0]) if len(hit) else None,
                    )
                )
            out += self._close_mirrors(k, ts, done, quiet=False)
        return [c for c in out if self._fresh_key(c)]

    def _close_mirrors(self, trade_key: str, ts: int, done: Exit, quiet: bool) -> list[cards.Card]:
        out = []
        for mk, m in list(self.state.mirrors.items()):
            if m["alt_trade"] != trade_key:
                continue
            del self.state.mirrors[mk]
            if quiet:
                continue
            how = {"stop": "its stop", "shift": "an opposite CISD", "time": "ten days"}.get(
                done.reason, done.reason
            )
            out.append(
                cards.mirror_exited(
                    m["alt"], mk, m.get("entry_ref"), self.state.btc.get("close"), ts, how
                )
            )
        return out

    def _btc_day(self, window: Bars, quiet: bool) -> list[cards.Card]:
        """BTC's daily close: the mirror's reference prices and the breadth exits."""
        last = len(window) - 1
        ts = int(window.ts[last])
        self.state.btc = {
            "ts": ts,
            "open": float(window.open[last]),
            "close": float(window.close[last]),
        }
        for book in (self.state.mirrors, self.state.holds):
            for m in book.values():
                if m.get("entry_ref") is None and ts == m["signal_ts"] + DAY:
                    m["entry_ref"] = float(window.open[last])
        out = []
        for hk, h in list(self.state.holds.items()):
            if ts < h["signal_ts"] + HOLD_B * DAY:
                continue
            del self.state.holds[hk]
            if quiet or ts > h["signal_ts"] + HOLD_B * DAY:
                continue
            out.append(
                cards.breadth_exited(
                    h["signal_ts"], h.get("entry_ref"), float(window.close[last]), ts
                )
            )
        return [c for c in out if self._fresh_key(c)]

    # ---------------------------------------------------------- the findings

    def _wanted(self, series: Series) -> tuple[str, ...]:
        """Patterns to detect on this series: the enabled ones, plus the
        DISPLACE_C trade where the mirror needs it to know when to exit."""
        wanted = list(self.settings.patterns)
        mirror = any(p in wanted for p in ("M1", "B"))
        if (
            mirror
            and series.timeframe == "1d"
            and series.klass == "crypto"
            and "DISPLACE_C_LOW12" not in wanted
        ):
            wanted.append("DISPLACE_C_LOW12")
        return tuple(wanted)

    def _findings(self, series: Series, window: Bars) -> list[cards.Card]:
        if series.timeframe not in self.settings.timeframes:
            return []
        found = detect(
            window,
            series.timeframe,
            series.klass,
            self._wanted(series),
            pivot=self.settings.major_pivot,
            move_atr=self.settings.major_move_atr,
        )
        out: list[cards.Card] = []
        for f in found:
            card = cards.finding(
                f, series.symbol, series.timeframe, series.klass, window, venue=series.venue
            )
            if self.state.seen(card.key) or card.key in self.state.trades:
                continue
            self.state.mark(card.key)
            alert = f.pattern in self.settings.patterns
            if f.signal is not None:
                self._open(card.key, f, series, window, alerted=alert)
                out += self._mirror(card.key, f, series, window)
            if alert:
                out.append(card)
        return out

    def _open(self, k: str, f: Finding, series: Series, window: Bars, *, alerted: bool) -> None:
        s = f.signal
        assert s is not None
        trade = Open(s.side, int(window.ts[f.at]), series.seconds, s.stop, s.atr)
        self.state.trades[k] = {
            "series": series.id,
            "rule": f.pattern,
            "symbol": series.symbol,
            "timeframe": series.timeframe,
            "signal_ts": int(window.ts[f.at]),
            "alerted": alerted,
            "open": trade.to_dict(),
        }

    def _mirror(self, k: str, f: Finding, series: Series, window: Bars) -> list[cards.Card]:
        """M1 and B: an alt's daily long signal, traded on BTC."""
        if not (
            f.side > 0
            and series.timeframe == "1d"
            and series.klass == "crypto"
            and series.symbol != TARGET
        ):
            return []
        bar_ts = int(window.ts[f.at])
        btc = self.state.btc.get("close") if self.state.btc.get("ts") == bar_ts else None
        out = []
        if "M1" in self.settings.patterns:
            card = cards.mirror(series.symbol, window, f.at, btc)
            if not self.state.seen(card.key):
                self.state.mark(card.key)
                self.state.mirrors[card.key] = {
                    "alt": series.symbol,
                    "alt_trade": k,
                    "signal_ts": bar_ts,
                    "entry_ref": None,
                }
                out.append(card)
        day = self.state.breadth.setdefault(str(bar_ts), [])
        if series.symbol not in day:
            day.append(series.symbol)
        if "B" in self.settings.patterns and len(day) >= BREADTH_MIN:
            card = cards.breadth(bar_ts, day, btc)
            if not self.state.seen(card.key):
                self.state.mark(card.key)
                self.state.holds[card.key] = {"signal_ts": bar_ts, "entry_ref": None}
                out.append(card)
        return out

    def _fresh_key(self, card: cards.Card) -> bool:
        """Mark an exit card's key; False if it was already sent."""
        if self.state.seen(card.key):
            return False
        self.state.mark(card.key)
        return True
