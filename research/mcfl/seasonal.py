"""The time core, item 8: seasonality and tempo states, against the market's own hour of day.

Every baseline here is causal and per hour of the day (UTC, of the bar's open): it holds only what
was known strictly before the bar or event it judges, and a fixed number of the latest values, so a
prefix of the series judges the same.

TIME-OF-DAY VOLATILITY, CANDLE qualifiers. The bar's range against the ranges of the last TOD_N (80)
bars that opened in the same hour: `tod_ratio` = range / their median, and `tod_vol` NORMAL when
the range is within their TOD_LO (10th) and TOD_HI (90th) percentiles, UNUSUAL outside, WARMUP with
fewer than TOD_MIN (40). So a 3 a.m. bar as wide as a London bar is UNUSUAL, a London bar of the
same width is not: `CANDLE[tod=UNUSUAL]`, `CANDLE[tod.ratio≥2]`. `profile(chart)` is the market's
profile: the median range per hour over the median of all.

TEMPO_STATE (L2, NONE). The market's tempo: TEMPO_EVENTS (EXTREME, VOID, BREAK, DISPLACE,
BREACH_REVERT, DELIVERY_SHIFT) known in the TEMPO_SPAN (4 hours) of wall-clock time up to the bar's
close, as events per hour. Against the same hour's last TOD_N rates: FAST above their 80th
percentile, SLOW below their 20th, else NORMAL (WARMUP under TOD_MIN). A TEMPO_STATE event is emitted
at each bar where the state changes: `state`, `rate`, `lo`, `hi`.

HOUR RATE, every event's time attribute (`Span.hour_rate`): of the last HOUR_WINDOW (400) events of
its type known strictly before it, the share that happened (by `at`) in its hour of the day, times
24 - 1 is the type's average hour, under 1 an hour rarer for it than average. None for tokens, and
with fewer than HOUR_MIN (50). "Rare for this hour" is the qualifier `BREAK[hour_rate<0.5]`.
`hour_profile` also gives the type's usual hour (the circular mean of the window's hours), which
LATE / EARLY read (`timed.py`).
"""
from __future__ import annotations

import bisect
from collections import deque

import numpy as np

from mcfl import candles
from mcfl.candles import Table
from mcfl.core import CALENDAR_TYPES, LAYER, Dir, Entity, attrs_of, make_id

TOD_N = 80
"""Same-hour values in a baseline: twenty days of 15-minute bars, eighty of hourly ones."""
TOD_MIN = 40
TOD_LO, TOD_HI = 0.10, 0.90
TEMPO_EVENTS = ("EXTREME", "VOID", "BREAK", "DISPLACE", "BREACH_REVERT", "DELIVERY_SHIFT")
TEMPO_SPAN = 4 * 3600
TEMPO_LO, TEMPO_HI = 0.20, 0.80
HOUR_WINDOW = 400
HOUR_MIN = 50
STATES = ("SLOW", "NORMAL", "FAST")


def hours(ts: np.ndarray) -> np.ndarray:
    return (np.asarray(ts, np.int64) // 3600) % 24


class Rolling:
    """The last `size` values, kept in arrival order and sorted, for order statistics."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.fifo: deque = deque()
        self.sorted: list[float] = []

    def __len__(self) -> int:
        return len(self.fifo)

    def add(self, x: float) -> None:
        self.fifo.append(x)
        bisect.insort(self.sorted, x)
        if len(self.fifo) > self.size:
            del self.sorted[bisect.bisect_left(self.sorted, self.fifo.popleft())]

    def quantile(self, q: float) -> float:
        """Linear interpolation between order statistics (numpy's default method)."""
        a = self.sorted
        pos = q * (len(a) - 1)
        i = int(pos)
        return a[i] if i + 1 >= len(a) else a[i] + (pos - i) * (a[i + 1] - a[i])


def _by_hour(x: np.ndarray, hr: np.ndarray, qs: tuple[float, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per bar: the median and the quantiles `qs` of the last TOD_N values of `x` at the bar's hour,
    known strictly before the bar, and how many there were."""
    n = len(x)
    med = np.full(n, np.nan)
    qv = np.full((n, len(qs)), np.nan)
    cnt = np.zeros(n, np.int64)
    win: dict[int, Rolling] = {}
    xs, hs = x.tolist(), hr.tolist()
    for t in range(n):
        d = win.get(hs[t])
        if d is None:
            d = win[hs[t]] = Rolling(TOD_N)
        cnt[t] = len(d)
        if len(d) >= TOD_MIN:
            med[t] = d.quantile(0.5)
            qv[t] = [d.quantile(q) for q in qs]
        if xs[t] == xs[t]:
            d.add(xs[t])
    return med, qv, cnt


def columns(T: Table, ts: np.ndarray) -> None:
    """Add `tod_ratio` and `tod_vol` to the token table, in place."""
    rng = T["high"] - T["low"]
    med, qv, cnt = _by_hour(rng, hours(ts), (TOD_LO, TOD_HI))
    with np.errstate(invalid="ignore", divide="ignore"):
        T["tod_ratio"] = np.where(med > 0, rng / np.where(med > 0, med, 1.0), np.nan)
    cls = np.where((rng < qv[:, 0]) | (rng > qv[:, 1]), "UNUSUAL", "NORMAL").astype(object)
    cls[cnt < TOD_MIN] = "WARMUP"
    T["tod_vol"] = cls
    candles.V2_CANDLE.update(tod_ratio=True, tod_vol=False)


def profile(chart, ts: np.ndarray | None = None) -> dict[int, float]:
    """The market's time-of-day volatility profile: each UTC hour's median range over the median of
    all bars' ranges."""
    c = sorted(chart.of("CANDLE"), key=lambda e: e.at)
    rng = np.array([e.get("high") - e.get("low") for e in c])
    ts = chart.clock.ts if ts is None else ts
    hr = hours(ts)
    m = float(np.median(rng)) or 1.0
    return {h: float(np.median(rng[hr == h])) / m for h in range(24) if (hr == h).any()}


def tempo_states(ents: list[Entity], ts: np.ndarray, length: np.ndarray, cid: list[str]) -> list[Entity]:
    """TEMPO_STATE changes; `length` the bars' observed lengths (`Clock.seen`), so the closes rise."""
    n = len(ts)
    close = ts + length
    cnt = np.zeros(n, np.int64)
    for e in ents:
        if e.type in TEMPO_EVENTS:
            cnt[e.known_at] += 1
    cum = np.r_[0, np.cumsum(cnt)]
    # bars whose close is inside (close[t] - span, close[t]]: from the first such bar to t
    lo = np.searchsorted(np.maximum.accumulate(close), close - TEMPO_SPAN, side="right")
    rate = (cum[np.arange(n) + 1] - cum[lo]) / (TEMPO_SPAN / 3600)
    _, qv, k = _by_hour(rate.astype(float), hours(ts), (TEMPO_LO, TEMPO_HI))
    out, last = [], None
    for t in range(n):
        if k[t] < TOD_MIN:
            continue
        st = "FAST" if rate[t] > qv[t, 1] else "SLOW" if rate[t] < qv[t, 0] else "NORMAL"
        if st != last:
            out.append(Entity(make_id("TEMPO_STATE", Dir.NONE, t), "TEMPO_STATE", Dir.NONE, t, t, attrs_of({
                "state": st, "rate": float(rate[t]), "lo": float(qv[t, 0]), "hi": float(qv[t, 1])}), parts=(cid[t],)))
            last = st
    return out


def hour_profile(ents: list[Entity], ts: np.ndarray | None) -> dict[str, tuple[float, float]]:
    """Per event id: (its hour rate, its type's usual hour), from the type's last HOUR_WINDOW events
    known strictly before it. Events of a type are taken in (known_at, at) order: ties have the same
    hour, so which of them a full window drops cannot change the counts."""
    if ts is None:
        return {}
    hr = hours(ts)
    by: dict[str, list[Entity]] = {}
    for e in ents:
        if LAYER[e.type] >= 2:
            by.setdefault(e.type, []).append(e)
    ang = 2 * np.pi * np.arange(24) / 24
    out: dict[str, tuple[float, float]] = {}
    for es in by.values():
        es.sort(key=lambda e: (e.known_at, e.at))
        win: deque = deque()
        counts = np.zeros(24, np.int64)
        i = 0
        while i < len(es):
            j = i
            while j < len(es) and es[j].known_at == es[i].known_at:
                j += 1
            m = len(win)
            if m >= HOUR_MIN:
                c = float(np.arctan2((counts * np.sin(ang)).sum(), (counts * np.cos(ang)).sum()))
                usual = (c % (2 * np.pi)) * 24 / (2 * np.pi)
                for e in es[i:j]:
                    out[e.id] = (float(24.0 * counts[hr[e.at]] / m), float(usual))
            for e in es[i:j]:
                h = int(hr[e.at])
                win.append(h)
                counts[h] += 1
                if len(win) > HOUR_WINDOW:
                    counts[win.popleft()] -= 1
            i = j
    return out


def hour_rates(ents: list[Entity], clock) -> dict[str, float]:
    """`Span.hour_rate` for every event (not the calendar's anchors' - those are the calendar)."""
    prof = hour_profile([e for e in ents if e.type not in CALENDAR_TYPES], clock.ts)
    return {k: v[0] for k, v in prof.items()}


def register() -> None:
    from mcfl import grammar
    grammar._KEYS.update({"tod": ("tod_vol", None), "tod.ratio": ("tod_ratio", "num")})


register()
