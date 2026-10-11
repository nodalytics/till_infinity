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
#: Round-trip cost of the BTC position, in bps (the research's 7).
FEE_BPS = 7.0
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
        #: Set by the service during a pass over the alt universe, so the
        #: day's mirror card waits for the whole close (`flush`).
        self.hold_mirror = False

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
                self._btc_day(window)
            if not quiet:
                out += self._findings(series, window)
            self.state.last[series.id] = int(bars.ts[i])
        if not self.hold_mirror:
            out += self.flush()
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
        """Record one alt trade's exit in its day; the day's exit card goes out
        when the last of its trades has exited."""
        out = []
        btc = self.state.btc.get("close")
        for day, d in list(self.state.mirrors.items()):
            sig = d["signals"].get(trade_key)
            if sig is None or not sig["open"]:
                continue
            ref = d.get("entry_ref")
            sig.update(
                open=False,
                reason=done.reason,
                r=done.r,
                bps=(btc / ref - 1) * 1e4 - FEE_BPS if ref and btc else None,
            )
            # Per signal, machine-side: M1 stays scorable exactly as research scores it.
            log.info(
                "mcfl: M1 %s on day %s exited %s, BTC %s bps",
                sig["alt"],
                day,
                done.reason,
                "n/a" if sig["bps"] is None else f"{sig['bps']:+.1f}",
            )
            if any(x["open"] for x in d["signals"].values()):
                continue
            del self.state.mirrors[day]
            if quiet or not d.get("sent"):
                continue
            scored = [x["bps"] for x in d["signals"].values() if x["bps"] is not None]
            mean = sum(scored) / len(scored) if scored else None
            out.append(cards.mirror_exited(int(day), d["card"], mean, len(d["signals"]), ts))
        return out

    def _btc_day(self, window: Bars) -> None:
        """BTC's daily close: the mirror's entry references, and B scored machine-side."""
        last = len(window) - 1
        ts = int(window.ts[last])
        close = float(window.close[last])
        self.state.btc = {"ts": ts, "open": float(window.open[last]), "close": close}
        for book in (self.state.mirrors, self.state.holds):
            for m in book.values():
                if m.get("entry_ref") is None and ts == m["signal_ts"] + DAY:
                    m["entry_ref"] = float(window.open[last])
        # B is folded into the daily card; its 5-day hold is still scored, in
        # the log, so the paper record stays comparable to the research.
        for hk, h in list(self.state.holds.items()):
            if ts < h["signal_ts"] + HOLD_B * DAY:
                continue
            del self.state.holds[hk]
            ref = h.get("entry_ref")
            bps = (close / ref - 1) * 1e4 - FEE_BPS if ref else None
            log.info(
                "mcfl: B of %s held %d days: %s bps",
                hk,
                HOLD_B,
                "n/a" if bps is None else f"{bps:+.1f}",
            )

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
        """M1 and B: an alt's daily long signal joins its day. The day's one card
        goes out at `flush`, once every alt of that close has been read."""
        if not (
            f.side > 0
            and series.timeframe == "1d"
            and series.klass == "crypto"
            and series.symbol != TARGET
            and any(p in self.settings.patterns for p in ("M1", "B"))
        ):
            return []
        bar_ts = int(window.ts[f.at])
        day = self.state.mirrors.setdefault(
            str(bar_ts),
            {"signal_ts": bar_ts, "signals": {}, "entry_ref": None, "sent": False, "card": ""},
        )
        if k not in day["signals"]:
            day["signals"][k] = {"alt": series.symbol, "open": True, "bps": None, "r": None}
            log.info("mcfl: M1 signal %s on day %s", series.symbol, bar_ts)
        return []

    def flush(self) -> list[cards.Card]:
        """One BTC card per daily close with unsent signals - M1 and B together.

        Called after a pass over the alt universe, so a day's count is the
        whole close; a signal arriving later joins the day's exit but not its
        card.
        """
        out = []
        for day, d in sorted(self.state.mirrors.items()):
            if d["sent"]:
                continue
            n = len(d["signals"])
            broad = n >= BREADTH_MIN and "B" in self.settings.patterns
            if "M1" not in self.settings.patterns and not broad:
                continue
            btc = self.state.btc.get("close") if self.state.btc.get("ts") == int(day) else None
            card = cards.mirror_day(int(day), n, broad, btc)
            d["sent"], d["card"] = True, card.key
            if broad:
                self.state.holds[card.key] = {"signal_ts": int(day), "entry_ref": None}
            if self._fresh_key(card):
                out.append(card)
        return out

    def _fresh_key(self, card: cards.Card) -> bool:
        """Mark an exit card's key; False if it was already sent."""
        if self.state.seen(card.key):
            return False
        self.state.mark(card.key)
        return True
