"""The time core, item 4 (time anchors as events) and item 5's remaining time.

WINDOWS are calendar intervals, each with a start and an end event:

    SESSION   v2's sessions, fixed UTC hours: ASIA 22:00-07:00, LONDON 07:00-12:00, OVERLAP 12:00-16:00,
              NY 16:00-22:00
    KILLZONE  ICT's, in New York time (daylight saving followed): ASIA_KZ 20:00-24:00, LONDON_KZ
              02:00-05:00, NY_AM_KZ 07:00-10:00, LONDON_CLOSE_KZ 10:00-12:00, NY_PM_KZ 13:30-16:00
    MACRO     ICT's macro windows, New York time: 02:33-03:00, 04:03-04:30, 08:50-09:10, 09:50-10:10,
              10:50-11:10, 11:50-12:10, 13:10-13:40, 15:15-15:45 (named M0233 ...)

A bar belongs to a window's instance when its open is inside it, so a window shorter than the bars
can hold no bar and have no instance (a 20-minute macro on hourly bars).

    WINDOW (L3, NONE)    an instance, at its first bar and known there: the calendar has announced its
                         end. `kind`, `name`, `sched_start`, `sched_end` (UTC seconds), `open` (the
                         first bar's open). Its span is the scheduled time; its last bar is not known
                         yet, so in bar time it has no end
    WINDOW_CLOSE (NONE)  the instance's end, at its last bar: known there when that bar's close
                         reaches the scheduled end, else at the next bar (the clock passed the end
                         with bars missing). `window`, `close`, `high`, `low`, parts its CANDLEs.
                         A session's close is WINDOW_CLOSE[kind=SESSION]
    DAY_OPEN (NONE)      the first bar of a day: `clock` UTC (midnight UTC) or NY (midnight New York)
    WEEK_OPEN (NONE)     the first bar of a trading week, which starts Sunday 17:00 New York (the FX
                         convention; a week with no Sunday session opens at its first bar after that)
    MONTH_OPEN (NONE)    the first bar of a UTC month
    HTF_CLOSE (NONE)     every higher-timeframe bar's close: the period `ts // tf` (UTC aligned) is
                         complete at its last bar when that bar's close reaches the period's end, or
                         at the next bar after a gap - the moment its facts become knowable. `tf`
                         (1h, 4h, 1d by default, each longer than the bar), `period_ts`, the HTF bar's
                         `open`, `high`, `low`, `close`, `bars`. This is the shared clock of every
                         multi-timeframe relation: `mtf` reads an HTF fact only at or after it

An open event (DAY_OPEN, ...) is at the first bar whose period differs from the previous bar's - or
at bar 0 when that bar opens exactly at the period's start. Every event here is decided by the
calendar and the bar's own timestamp: a walk given the same timestamps has the same ones.

REMAINING TIME (item 5), CANDLE qualifiers, seconds from the bar's close: `left_session` (to the
scheduled end of the session its open is in), `left_day` (to UTC midnight), and per HTF timeframe
`left_<tf>` and `prog_<tf>`, the share of the HTF bar elapsed at the bar's close (0.75: three
quarters of a 4h bar). Qualifiers `CANDLE[left.session≤1800]`, `CANDLE[prog.4h≥0.75]`. Also
`killzone` and `macro`, the name of the window the bar is in, or NONE: `CANDLE[killzone=LONDON_KZ]`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mcfl import candles
from mcfl.candles import Table
from mcfl.core import Dir, Entity, attrs_of, make_id
from mcfl.timing import SESSIONS

NY = "America/New_York"
WINDOWS: tuple[tuple[str, str, str, int, int], ...] = (
    *(("SESSION", name, "UTC", a * 60, b * 60) for name, a, b in SESSIONS),
    ("KILLZONE", "ASIA_KZ", NY, 20 * 60, 24 * 60), ("KILLZONE", "LONDON_KZ", NY, 2 * 60, 5 * 60),
    ("KILLZONE", "NY_AM_KZ", NY, 7 * 60, 10 * 60), ("KILLZONE", "LONDON_CLOSE_KZ", NY, 10 * 60, 12 * 60),
    ("KILLZONE", "NY_PM_KZ", NY, 13 * 60 + 30, 16 * 60),
    *(("MACRO", f"M{a // 60:02d}{a % 60:02d}", NY, a, b) for a, b in (
        (153, 180), (243, 270), (530, 550), (590, 610), (650, 670), (710, 730), (790, 820), (915, 945))),
)
"""(kind, name, time zone, start, end): minutes of the local day, [start, end); start > end wraps midnight."""
HTF_TFS = (3600, 14400, 86400)
"""The higher timeframes whose closes are anchors by default (each only when longer than the bar)."""
WEEK_START = (6, 17 * 60)
"""The trading week starts Sunday (weekday 6) 17:00 New York."""


def tf_label(sec: int) -> str:
    for unit, name in ((86400, "d"), (3600, "h"), (60, "m")):
        if sec % unit == 0:
            return f"{sec // unit}{name}"
    return f"{sec}s"


# ---------------------------------------------------------------- local time and window instances

def local(ts: np.ndarray, tz: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per bar, in time zone tz: the local day number (days since 1970-01-01, local), the minute of
    the local day, the weekday (0 Monday)."""
    ts = np.asarray(ts, np.int64)
    if tz == "UTC":
        day = ts // 86400
        return day, (ts % 86400) // 60, (day + 3) % 7
    t = pd.to_datetime(ts, unit="s", utc=True).tz_convert(tz).tz_localize(None)
    ns = np.asarray(t.asi8)
    day = ns // (86400 * 10**9)
    return day, (ns % (86400 * 10**9)) // (60 * 10**9), (day + 3) % 7


_LOCAL: dict[tuple[str, int], int] = {}


def utc_of(tz: str, day: int, minute: int) -> int:
    """The UTC time of a local day and minute (a nonexistent local time moves forward an hour, an
    ambiguous one takes the first)."""
    if tz == "UTC":
        return int(day * 86400 + minute * 60)
    k = (tz, int(day) * 1440 + int(minute))
    if k not in _LOCAL:
        x = pd.Timestamp(int(day) * 86400 + int(minute) * 60, unit="s").tz_localize(
            tz, ambiguous=True, nonexistent="shift_forward")
        _LOCAL[k] = int(x.timestamp())
    return _LOCAL[k]


@dataclass(frozen=True)
class Instances:
    """One window's instances over the bars: per bar, whether its open is in one, the instance's first
    bar (-1 outside), and its scheduled start and end (UTC seconds)."""
    kind: str
    name: str
    inn: np.ndarray
    first: np.ndarray
    start: np.ndarray
    end: np.ndarray


def instances(ts: np.ndarray, spec: tuple[str, str, str, int, int], cache: dict | None = None) -> Instances:
    kind, name, tz, s, e = spec
    cache = {} if cache is None else cache
    if tz not in cache:
        cache[tz] = local(ts, tz)
    day, m, _ = cache[tz]
    n = len(ts)
    if s < e:
        inn = (m >= s) & (m < e)
        idate = day.copy()
    else:
        inn = (m >= s) | (m < e)
        idate = day - (m < e)
    idx = np.arange(n)
    prev_in = np.r_[False, inn[:-1]]
    prev_date = np.r_[-1, idate[:-1]]
    new = inn & (~prev_in | (idate != prev_date))
    first = np.maximum.accumulate(np.where(new, idx, -1)) if n else np.zeros(0, np.int64)
    first = np.where(inn, first, -1)
    start = np.zeros(n, np.int64)
    end = np.zeros(n, np.int64)
    wrap = s > e
    for d in np.unique(idate[inn]):
        sel = inn & (idate == d)
        start[sel] = utc_of(tz, d, s)
        end[sel] = utc_of(tz, d + (1 if wrap or e >= 1440 else 0), e % 1440 if e >= 1440 else e)
    return Instances(kind, name, inn, first, start, end)


def layout(ts: np.ndarray, specs: tuple = WINDOWS) -> dict[str, Instances]:
    cache: dict = {}
    return {spec[1]: instances(ts, spec, cache) for spec in specs}


# ---------------------------------------------------------------- HTF periods: the shared clock

def periods(ts: np.ndarray, length: np.ndarray, tf: int) -> list[tuple[int, int, int, int, int]]:
    """Complete periods of `tf` seconds as (first bar, last bar, bar it is known at, open ts, period):
    known at the last bar when its close reaches the period's end, else at the next period's first bar."""
    ts = np.asarray(ts, np.int64)
    n = len(ts)
    if n == 0:
        return []
    key = ts // tf
    starts = np.r_[0, np.flatnonzero(key[1:] != key[:-1]) + 1]
    out = []
    for j, a in enumerate(starts):
        a = int(a)
        b = int(starts[j + 1]) - 1 if j + 1 < len(starts) else n - 1
        end = (int(key[a]) + 1) * tf
        if ts[b] + length[b] >= end:
            known = b
        elif j + 1 < len(starts):
            known = int(starts[j + 1])
        else:
            continue
        out.append((a, b, known, int(key[a]) * tf, int(key[a])))
    return out


# ---------------------------------------------------------------- events

def _opens(key: np.ndarray, at_start: bool) -> np.ndarray:
    """Bars that open a new period: the key changes, or bar 0 opens at its period's start."""
    new = np.r_[at_start, key[1:] != key[:-1]] if len(key) else np.zeros(0, bool)
    return np.flatnonzero(new)


def events(T: Table, ts: np.ndarray, length: np.ndarray, lay: dict[str, Instances], cid: list[str],
           htf: tuple[int, ...] = HTF_TFS) -> list[Entity]:
    o, h, l, c = T["open"], T["high"], T["low"], T["close"]
    n = len(c)
    close = ts + length
    out: list[Entity] = []
    for name, w in lay.items():
        for a in np.flatnonzero(w.inn & (w.first == np.arange(n))):
            a = int(a)
            wid = make_id("WINDOW", Dir.NONE, a, name)
            out.append(Entity(wid, "WINDOW", Dir.NONE, a, a, attrs_of({
                "kind": w.kind, "name": name, "sched_start": int(w.start[a]), "sched_end": int(w.end[a]),
                "open": float(o[a])}), parts=(cid[a],)))
            b = a
            while b + 1 < n and w.first[b + 1] == a:
                b += 1
            if close[b] >= w.end[a]:
                known = b
            elif b + 1 < n:
                known = b + 1
            else:
                continue  # the window has not been seen to end
            out.append(Entity(make_id("WINDOW_CLOSE", Dir.NONE, b, f"{name}{a}"), "WINDOW_CLOSE", Dir.NONE, b, known,
                              attrs_of({"kind": w.kind, "name": name, "window": wid, "close": float(c[b]),
                                        "high": float(h[a:b + 1].max()), "low": float(l[a:b + 1].min()),
                                        "complete": known == b}), parts=tuple(cid[a:b + 1])))
    # day, week and month opens
    uday = ts // 86400
    nday, nmin, _ = local(ts, NY)
    # the trading week: New York time moved on by (24h - 17:00) + a day, so Sunday 17:00 is a Monday 00:00
    shift = (7 - WEEK_START[0]) * 1440 - WEEK_START[1]
    wk_min = nday * 1440 + nmin + shift
    week = (wk_min // 1440 - 4) // 7  # 1970-01-05 was a Monday
    month = pd.to_datetime(ts, unit="s", utc=True)
    mkey = np.asarray(month.year) * 12 + np.asarray(month.month) if n else np.zeros(0, np.int64)
    first_min = n > 0 and ts[0] % 86400 == 0
    week_at0 = n > 0 and wk_min[0] % 1440 == 0 and (wk_min[0] // 1440 - 4) % 7 == 0
    for kind, key, clock, at0 in (
            ("DAY_OPEN", uday, "UTC", first_min),
            ("DAY_OPEN", nday, "NY", n > 0 and nmin[0] == 0),
            ("WEEK_OPEN", week, "NY", week_at0),
            ("MONTH_OPEN", mkey, "UTC", first_min and n > 0 and int(month.day[0]) == 1)):
        for t in _opens(key, bool(at0)):
            t = int(t)
            out.append(Entity(make_id(kind, Dir.NONE, t, clock if kind == "DAY_OPEN" else ""), kind, Dir.NONE, t, t,
                              attrs_of({"clock": clock, "price": float(o[t])}), parts=(cid[t],)))
    # higher-timeframe closes
    for tf in htf:
        lab = tf_label(tf)
        for a, b, known, t0, _ in periods(ts, length, tf):
            if tf <= length[b]:
                continue
            out.append(Entity(make_id("HTF_CLOSE", Dir.NONE, b, lab), "HTF_CLOSE", Dir.NONE, b, known, attrs_of({
                "tf": lab, "period_ts": t0, "open": float(o[a]), "high": float(h[a:b + 1].max()),
                "low": float(l[a:b + 1].min()), "close": float(c[b]), "bars": b - a + 1}), parts=tuple(cid[a:b + 1])))
    return out


# ---------------------------------------------------------------- item 5: remaining time

def columns(T: Table, ts: np.ndarray, length: np.ndarray, lay: dict[str, Instances],
            htf: tuple[int, ...] = HTF_TFS) -> None:
    """Add the remaining-time and window qualifiers to the token table, in place."""
    close = ts + length
    n = len(ts)
    left = np.full(n, np.nan)
    for name, w in lay.items():
        if w.kind == "SESSION":
            left = np.where(w.inn, (w.end - close).astype(float), left)
    T["left_session"] = left
    T["left_day"] = ((ts // 86400 + 1) * 86400 - close).astype(float)
    keys = {"left_session": True, "left_day": True}
    for tf in htf:
        lab = tf_label(tf)
        p0 = ts // tf * tf
        T[f"left_{lab}"] = (p0 + tf - close).astype(float)
        T[f"prog_{lab}"] = np.clip((close - p0) / tf, 0.0, 1.0)
        keys.update({f"left_{lab}": True, f"prog_{lab}": True})
    for kind in ("KILLZONE", "MACRO"):
        col = np.full(n, "NONE", object)
        for name, w in lay.items():
            if w.kind == kind:
                col[w.inn] = name
        T[kind.lower()] = col
        keys[kind.lower()] = False
    candles.V2_CANDLE.update(keys)
    register(htf)


def register(htf: tuple[int, ...] = HTF_TFS) -> None:
    from mcfl import grammar
    grammar._KEYS.update({"left.session": ("left_session", "num"), "left.day": ("left_day", "num"),
                          "killzone": ("killzone", None), "macro": ("macro", None)})
    for tf in htf:
        lab = tf_label(tf)
        grammar._KEYS.update({f"left.{lab}": (f"left_{lab}", "num"), f"prog.{lab}": (f"prog_{lab}", "num")})


register()
