"""The frozen DISPLACE_C trade: the signal at a 12-bar low, and its structure exit.

The one turn result that passed fresh coins (`turn_confirm_rule.json`), as the
research runs it in `turn_trade.trades_exits` and `market_mirror.exits`:

    signal   bar t is a 12-bar low (the lowest low of t-2..t at or below the
             lowest of t-11..t-3) and completes DISPLACE_C up; shorts on the
             flipped chart
    entry    bar t+1's open
    stop     0.1 ATR beyond the 3-bar low (every stop fill takes 0.05 ATR)
    exit E2  the next open after a DELIVERY_SHIFT against the trade, or the
             stop, or the close of bar t+H - ten days of bars at most

**This module describes a trade; nothing here places one.** The service turns a
`Signal` into an alert and an `Open` position into an exit alert, and the only
thing either can reach is the `alerts` topic.

`Open.step` advances one position one closed bar at a time - the incremental
form of the research's loop over j, so a restart that restores an `Open` picks
up at the next bar exactly where the research loop would be.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .events import Event, delivery_shifts, displace_c
from .tokens import Bars, Tokens, frames

#: The stop sits this many ATR beyond the 3-bar extreme.
STOP_ATR = 0.1
#: Adverse slippage on every stop fill, in ATR.
SLIP_ATR = 0.05
#: The longest a trade is held, in days.
MAX_DAYS = 10


def hold_bars(seconds: int) -> int:
    """H: ten days of bars of this length (10 on 1d, 60 on 4h, 240 on 1h)."""
    return max(1, int(MAX_DAYS * 86_400 / seconds))


def low12(low: np.ndarray) -> np.ndarray:
    """Where a 12-bar low is knowable at the bar's close.

    The lowest low of t-2..t at or below the lowest of t-11..t-3. False until
    there are twelve bars, as the research's rolling windows are NaN there.
    """
    n = len(low)
    out = np.zeros(n, bool)
    if n < 12:
        return out
    view = np.lib.stride_tricks.sliding_window_view(low, 12)  # row r is bars r..r+11
    out[11:] = view[:, 9:].min(axis=1) <= view[:, :9].min(axis=1)
    return out


@dataclass(frozen=True, slots=True)
class Signal:
    """DISPLACE_C at a 12-bar low on bar `at`, in chart prices."""

    side: int
    at: int
    close: float
    atr: float
    stop: float
    low3: float


def signals(bars: Bars, fr: dict[int, Tokens] | None = None) -> list[Signal]:
    """Every signal in the series, both sides, oldest first."""
    fr = fr if fr is not None else frames(bars)
    found = {(e.dir, e.at) for e in displace_c(fr)}
    out = []
    for side in (1, -1):
        f = fr[side]
        low = f.bars.low
        at_low = low12(low)
        for t in map(int, np.flatnonzero(at_low)):
            if (side, t) not in found or not f.atr[t] > 0:
                continue
            l3 = float(low[t - 2 : t + 1].min())
            stop = l3 - STOP_ATR * f.atr[t]
            out.append(
                Signal(side, t, float(bars.close[t]), float(f.atr[t]), side * stop, side * l3)
            )
    return sorted(out, key=lambda s: (s.at, -s.side))


def against(fr: dict[int, Tokens]) -> dict[int, set[int]]:
    """Bars with a DELIVERY_SHIFT against each side: the structure exit's trigger."""
    out: dict[int, set[int]] = {1: set(), -1: set()}
    for e in delivery_shifts(fr):
        out[-e.dir].add(e.at)
    return out


@dataclass(slots=True)
class Open:
    """One frozen trade between its signal and its exit.

    Prices are in chart terms; `side` turns them into the frame the rule is
    written in. `entry` is unknown until bar t+1 has opened.
    """

    side: int
    signal_ts: int
    seconds: int
    stop: float
    atr: float
    entry: float | None = None
    bars_held: int = 0
    mfe: float = 0.0

    @property
    def hold(self) -> int:
        return hold_bars(self.seconds)

    def risk(self) -> float | None:
        if self.entry is None:
            return None
        r = self.side * (self.entry - self.stop)
        return r if r > 0 else None

    def step(self, open_: float, high: float, low: float, close: float, shift: bool) -> Exit | None:
        """Advance one closed bar after the signal. Returns the exit, if this is it.

        `shift` is whether this bar completed a DELIVERY_SHIFT against the
        trade. The order is the research loop's: the stop, then the best
        excursion, then the shift, then the time cap.
        """
        s = self.side
        if self.entry is None:
            self.entry = open_
        risk = self.risk()
        if risk is None:
            # A stop on the wrong side of the open: the research skips these.
            return Exit("void", close, 0.0, self.bars_held)
        self.bars_held += 1
        first = self.bars_held == 1
        o, lo, hi = s * open_, s * (low if s > 0 else high), s * (high if s > 0 else low)
        stop, entry = s * self.stop, s * self.entry
        if lo <= stop:
            fill = (stop if first else min(o, stop)) - SLIP_ATR * self.atr
            return Exit("stop", s * fill, (fill - entry) / risk, self.bars_held, self.mfe)
        self.mfe = max(self.mfe, (hi - entry) / risk)
        if shift:
            return Exit("shift", close, (s * close - entry) / risk, self.bars_held, self.mfe)
        if self.bars_held >= self.hold:
            return Exit("time", close, (s * close - entry) / risk, self.bars_held, self.mfe)
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> Open:
        return cls(**{k: raw[k] for k in cls.__dataclass_fields__ if k in raw})


@dataclass(frozen=True, slots=True)
class Exit:
    """How a frozen trade ended.

    `reason` is `stop` (filled during the bar, at `price`), `shift` (out at the
    *next* open - `price` and `r` are marked at this close), `time` (out at
    this close) or `void` (the stop was beyond the entry; no trade).
    """

    reason: str
    price: float
    r: float
    bars: int
    mfe: float = 0.0

    @property
    def at_next_open(self) -> bool:
        return self.reason == "shift"


def walk(bars: Bars, signal: Signal, seconds: int) -> tuple[int, Exit] | None:
    """Run one signal's trade to its exit over a whole series (for tests and replays)."""
    fr = frames(bars)
    shifts = against(fr)[signal.side]
    trade = Open(signal.side, int(bars.ts[signal.at]), seconds, signal.stop, signal.atr)
    for j in range(signal.at + 1, len(bars)):
        done = trade.step(
            float(bars.open[j]),
            float(bars.high[j]),
            float(bars.low[j]),
            float(bars.close[j]),
            j in shifts,
        )
        if done is not None:
            return j, done
    return None


def by_kind(events: list[Event], kind: str) -> list[Event]:
    return [e for e in events if e.kind == kind]
