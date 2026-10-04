"""The time core, items 1, 5 and 7: time in the core, elapsed time, and several clocks.

THE CLOCK. A chart with a `ts` column (each bar's open, UTC epoch seconds) has a wall clock. Each bar
has a length L[t]: the `close_ts` column minus `ts` when the bars carry their closes (volume and tick
bars do), else the `sec` given to the parse, else the running minimum of the positive gaps between
consecutive opens up to t - known at t, so a prefix reads the same lengths. Bar 0 has no gap yet and
takes the coarsest standard bar its open is aligned to (STANDARD; an hour when none is): too long
rather than too short, so nothing is ever stamped as known before it could be. Whether a period
has ended is the opposite question, and there bar 0's unobserved length counts as 0 (`seen`): a
guess must not end a session early. A bar closes at `ts + L`; trading time is the bars' lengths summed, calendar time the clock's difference, and their
difference is the clock's gaps (weekends, closures).

ITEM 1, TIME IN THE CORE. `stamp` gives every entity a `core.Span`: its interval in bars (`start`,
`end`, inclusive) and in time ([open of start, close of end)), its `known_at_ts` (the close of its
known_at bar), its trading time and its `hour_rate` (item 8, `seasonal.hour_rates`). An event's (L2)
interval is the tokens it consumed and its own bar - a BREAK spans its leg (origin to break), a
PATTERN its bars, a STALL the confined bars - and an event that consumed no token (a POOL_TAKEN, a
SWING, a TIMEOUT) is its own bar. A structure's (L3) interval is its derivation: the bars of
everything it was built from (an id carries its bar) - a ZONE its origin to its break, a POOL its
first member to its newest, an EPISODE its structure to the event that ended it. The exceptions are
in SPANS: an EXTREME is its own bar (its window's right side is the confirmation, not the swing), a
LEG runs from its origin to its end, a calendar WINDOW is known when it opens and has a scheduled end
in time but no last bar yet.

EPISODE (L3) makes the lifecycles intervals: one for every ZONE, VOID and RANGE that ended - a zone
at ACCEPT, FAIL or EXPIRE, a void at VOID_INVERTED, a range at ESCAPE - from the structure's first
bar to the ending event's, known when that event is. `of`, `outcome`, `events` (lifecycle events
in between), parts the structure and the ending event.

ITEM 5, ELAPSED TIME. `age(chart, e, t)`: since entity e became known, at bar t, in bars, seconds,
trading seconds and sessions (session WINDOWs opened since). Remaining time and HTF progress are
CANDLE qualifiers (`anchors.columns`). In productions, ages are clauses on the stamped fields:
`C("known_at_ts", "<=", ("+", "zone.known_at_ts", 3600))` is "within an hour of the zone".

ITEM 7, SEVERAL CLOCKS.
    bar      the bar index                     time    the bar's close, UTC seconds
    trade    trading seconds since bar 0       volume  volume traded since bar 0
    event    events known since bar 0 (one step per event)
`reading(chart, clock)` is the event sentence with each token stamped on the chosen clock - the
same sentence on any clock. `volume_bars` builds bars of equal volume from bars, `tick_bars` bars of
equal tick count from ticks; both carry `close_ts`, so the parse runs on them unchanged, and
`in_source` maps an entity of such a chart back to the source bar at which it was known.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mcfl.core import LAYER, Chart, Entity, Span, attrs_of, make_id

STANDARD = (60, 300, 900, 1800, 3600, 14400, 86400)
"""Standard bar lengths (seconds): bar 0's length is the coarsest its open is aligned to."""
FALLBACK_SEC = 3600
"""Bar 0's length when its open is aligned to none of STANDARD."""


def first_length(ts0: int) -> int:
    for s in reversed(STANDARD):
        if ts0 % s == 0:
            return s
    return FALLBACK_SEC


def bar_lengths(ts: np.ndarray, sec: float | None = None, close_ts: np.ndarray | None = None,
                seen: bool = False) -> np.ndarray:
    """Each bar's length in seconds, known at the bar (see the module's docstring). `seen=True` gives
    the lengths that have been observed: bar 0's, when inferred, is then 0 (unknown) - what decides
    whether a period has ended, where a guessed length would end it too early."""
    n = len(ts)
    if close_ts is not None:
        return (np.asarray(close_ts, np.int64) - ts).astype(np.int64)
    if sec is not None:
        return np.full(n, int(sec), np.int64)
    if n == 0:
        return np.empty(0, np.int64)
    gaps = np.r_[first_length(int(ts[0])), np.diff(ts)].astype(np.int64)
    gaps[gaps <= 0] = gaps[0]  # a repeated or out-of-order stamp says nothing about the length
    out = np.minimum.accumulate(gaps)
    if seen:
        out[0] = 0
    return out


@dataclass(frozen=True)
class Clock:
    """The bars' clocks. Without timestamps only the bar clock exists (`ts` None)."""
    n: int
    ts: np.ndarray | None = field(default=None, repr=False)  # each bar's open
    length: np.ndarray | None = field(default=None, repr=False)  # its length, known at it
    volume: np.ndarray | None = field(default=None, repr=False)  # cumulative volume through each bar
    seen: np.ndarray | None = field(default=None, repr=False)  # its observed length (bar 0's may be 0)

    @staticmethod
    def of(df: pd.DataFrame, sec: float | None = None) -> Clock:
        n = len(df)
        vol = np.cumsum(df["volume"].to_numpy(float)) if "volume" in df else None
        if "ts" not in df:
            return Clock(n, volume=vol)
        ts = df["ts"].to_numpy(np.int64)
        ct = df["close_ts"].to_numpy(np.int64) if "close_ts" in df else None
        return Clock(n, ts, bar_lengths(ts, sec, ct), vol, bar_lengths(ts, sec, ct, seen=True))

    @property
    def close(self) -> np.ndarray:
        return self.ts + self.length

    @property
    def trade(self) -> np.ndarray:
        """Trading seconds through each bar: the observed lengths summed."""
        return np.cumsum(self.seen)

    def at(self, kind: str) -> np.ndarray:
        """Each bar's reading on clock `kind` (bar, time, trade, volume; `event` needs a chart)."""
        if kind == "bar":
            return np.arange(self.n)
        if kind == "time":
            return self.close
        if kind == "trade":
            return self.trade
        if kind == "volume":
            return self.volume
        raise ValueError(kind)


# ---------------------------------------------------------------- item 1: spans

def _bar(pid: str) -> int | None:
    """The bar an id carries (`TYPE.D.bar[.suffix]`); None for another chart's id (`4h:...`)."""
    if ":" in pid:
        return None
    try:
        return int(pid.split(".")[2])
    except (IndexError, ValueError):
        return None


def _derived(e: Entity, tokens: bool = False) -> tuple[int, int]:
    """The bars of e's parts and its own bar; `tokens`: of its L1 token parts only."""
    parts = [p for p in e.parts if p.startswith(("CANDLE.", "BAR_RELATION."))] if tokens else e.parts
    bars = [b for b in map(_bar, parts) if b is not None]
    if not bars:
        return e.at, e.at
    return min(min(bars), e.at), max(max(bars), e.at)


SPANS = {
    "EXTREME": lambda e: (e.at, e.at),
    "SESSION_EXTREME": lambda e: (e.at, e.at),
    "IN_WINDOW": lambda e: (e.at, e.at),
    "LEG": lambda e: (e.at, e.get("end") - 1 if e.get("reason") == "INVALIDATED" else e.get("end")),
    "WINDOW": lambda e: (e.at, None),
}
"""Spans that are not the derivation's: an EXTREME (and a session's extreme) is its own bar, a LEG its
origin to its end (an invalidating bar is not part of it), a calendar WINDOW is open-ended in bars."""


def span(e: Entity, clock: Clock, hour_rate: float | None = None, _lists: tuple | None = None) -> Span:
    f = SPANS.get(e.type)
    if f is not None:
        a, b = f(e)
    elif not e.parts:
        a = b = e.at
    else:
        a, b = _derived(e, tokens=LAYER[e.type] < 3)
    if clock.ts is None:
        return Span(a, b, hour_rate=hour_rate)
    ts, close, cum = _lists if _lists is not None else _as_lists(clock)
    if e.type == "WINDOW":
        return Span(a, None, e.get("sched_start"), e.get("sched_end"), close[e.known_at], None, hour_rate)
    return Span(a, b, ts[a], close[b], close[e.known_at], cum[b + 1] - cum[a], hour_rate)


def _as_lists(clock: Clock) -> tuple[list[int], list[int], list[int]]:
    """Opens, closes, and trading time summed - over the observed lengths, so bar 0's guessed one
    counts as no trading time and trading time never exceeds calendar time."""
    return clock.ts.tolist(), clock.close.tolist(), np.r_[0, np.cumsum(clock.seen)].tolist()


def stamp(ents: list[Entity], clock: Clock) -> list[Entity]:
    """Every entity with its Span (item 1) and its hour rate (item 8)."""
    from mcfl.seasonal import hour_rates
    rates = hour_rates(ents, clock) if clock.ts is not None else {}
    lists = _as_lists(clock) if clock.ts is not None else None
    return [Entity(e.id, e.type, e.dir, e.at, e.known_at, e.attrs, e.force, e.parts,
                   span(e, clock, rates.get(e.id), lists)) for e in ents]


# ---------------------------------------------------------------- item 1: episodes

ENDS = {"ZONE": ("zone", ("ACCEPT", "FAIL", "EXPIRE")), "VOID": ("void", ("VOID_INVERTED",)),
        "RANGE": ("range", ("ESCAPE",))}
"""Each structure's lifecycle: the attribute its events point to it by, and the events that end it."""
LIFE = {"ZONE": ("REVISIT", "REJECT_PATH", "ACCEPT", "FAIL", "EXPIRE"),
        "VOID": ("VOID_PARTIAL", "VOID_FILLED", "VOID_INVERTED"),
        "RANGE": ("RANGE_TEST", "FAILED_ESCAPE", "ESCAPE")}


def episodes(ents: list[Entity]) -> list[Entity]:
    """EPISODE: a structure from its first bar to the event that ended it."""
    ids = {e.id: e for e in ents}
    life: dict[str, list[Entity]] = {}
    for e in ents:
        for typ, (key, _) in ENDS.items():
            if e.type in LIFE[typ] and e.get(key) is not None:
                life.setdefault(e.get(key), []).append(e)
    out = []
    for sid, evs in life.items():
        s = ids.get(sid)
        if s is None:
            continue
        ends = sorted((e for e in evs if e.type in ENDS[s.type][1]), key=lambda e: (e.known_at, e.at, e.type))
        if not ends:
            continue
        x = ends[0]
        n_ev = sum(1 for e in evs if e.known_at <= x.known_at and e.id != x.id)
        out.append(Entity(make_id("EPISODE", s.dir, s.at, s.type), "EPISODE", s.dir, s.at, max(x.known_at, s.known_at),
                          attrs_of({"of": s.id, "outcome": x.type, "events": n_ev, "end": x.at}), parts=(s.id, x.id)))
    return out


# ---------------------------------------------------------------- item 5: elapsed time

def age(chart: Chart, e: Entity, t: int) -> dict:
    """Time since `e` became known, at bar t (t >= e.known_at): bars, seconds and trading seconds from
    the close of its known_at bar to the close of t, and session WINDOWs opened in between."""
    if t < e.known_at:
        raise ValueError(f"{e.id} is not known at bar {t}")
    out = {"bars": t - e.known_at, "seconds": None, "trade_sec": None, "sessions": None}
    clk = chart.clock
    if clk is not None and clk.ts is not None:
        c = clk.close
        out["seconds"] = int(c[t] - c[e.known_at])
        out["trade_sec"] = int(clk.seen[e.known_at + 1:t + 1].sum())
        out["sessions"] = sum(1 for w in chart.of("WINDOW")
                              if w.get("kind") == "SESSION" and e.known_at < w.known_at <= t)
    return out


# ---------------------------------------------------------------- item 7: several clocks

CLOCKS = ("bar", "time", "trade", "volume", "event")


def event_clock(chart: Chart, types: tuple[str, ...] | None = None) -> np.ndarray:
    """Per bar, the events (of `types`, default every L2/L3 entity but the calendar's anchors) known
    at or before it: one step per event."""
    from mcfl.core import CALENDAR_TYPES, LAYER
    cnt = np.zeros(chart.n, np.int64)
    for e in chart.entities:
        if (e.type in types) if types is not None else (LAYER[e.type] >= 2 and e.type not in CALENDAR_TYPES):
            cnt[e.known_at] += 1
    return np.cumsum(cnt)


def reading(chart: Chart, clock: str = "bar", types: tuple[str, ...] | None = None) -> list[tuple[float, str]]:
    """The event sentence (`serialise.sentence`) with each token at its known_at on `clock`."""
    from mcfl.serialise import SENTENCE_TYPES, sentence, token
    if clock == "event":
        x = event_clock(chart, types)
    else:
        x = chart.clock.at(clock) if chart.clock is not None else None
        if x is None:
            raise ValueError(f"the chart has no {clock} clock")
    return [(float(x[e.known_at]), token(e, v2=True)) for e in sentence(chart, types or SENTENCE_TYPES)]


def volume_bars(df: pd.DataFrame, size: float, sec: float | None = None) -> pd.DataFrame:
    """Bars of (at least) `size` volume, built from bars: each closes at the source bar whose volume
    takes it to `size` (a source bar is not split), so a volume bar is known at that source bar. The
    last, incomplete bar is left out. Carries `ts` (its first source bar's open), `close_ts` (its last
    source bar's close), `src_first`, `src_last`."""
    df = df.reset_index(drop=True)
    clk = Clock.of(df, sec)
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    extra = [k for k in ("taker_buy_volume", "taker_sell_volume") if k in df]
    rows, a, acc = [], 0, 0.0
    for t in range(len(df)):
        acc += v[t]
        if acc >= size:
            r = dict(open=o[a], high=h[a:t + 1].max(), low=l[a:t + 1].min(), close=c[t], volume=acc,
                     src_first=a, src_last=t)
            for k in extra:
                r[k] = float(df[k].iloc[a:t + 1].sum())
            if clk.ts is not None:
                r["ts"], r["close_ts"] = int(clk.ts[a]), int(clk.close[t])
            rows.append(r)
            a, acc = t + 1, 0.0
    cols = ["open", "high", "low", "close", "volume", "src_first", "src_last"] + extra
    return pd.DataFrame(rows, columns=None if rows else cols)


def tick_bars(ticks: pd.DataFrame, n_ticks: int) -> pd.DataFrame:
    """Bars of `n_ticks` ticks from a tick frame (`ts` in seconds, `price`, or `bid` and `ask` for the
    mid; optional `volume`). `ts` is the first tick's second, `close_ts` the second after the last
    tick (known then); the incomplete last bar is left out."""
    px = ticks["price"].to_numpy(float) if "price" in ticks else (ticks["bid"].to_numpy(float) + ticks["ask"].to_numpy(float)) / 2
    ts = ticks["ts"].to_numpy(float)
    vol = ticks["volume"].to_numpy(float) if "volume" in ticks else np.ones(len(px))
    k = len(px) // n_ticks
    if k == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "ts", "close_ts"])
    P, T, V = (x[:k * n_ticks].reshape(k, n_ticks) for x in (px, ts, vol))
    return pd.DataFrame({"open": P[:, 0], "high": P.max(1), "low": P.min(1), "close": P[:, -1], "volume": V.sum(1),
                         "ts": np.floor(T[:, 0]).astype(np.int64), "close_ts": np.floor(T[:, -1]).astype(np.int64) + 1})


def in_source(bars: pd.DataFrame, e: Entity) -> int:
    """The source bar at which an entity parsed on volume (or other built) bars was known."""
    return int(bars["src_last"].iloc[e.known_at])


__all__ = ["Clock", "age", "bar_lengths", "episodes", "event_clock", "in_source", "reading", "span", "stamp",
           "tick_bars", "volume_bars"]
