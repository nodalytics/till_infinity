"""The time core, item 3: calendar tokens.

CANDLE qualifiers from the bar's open, in UTC (as v2's SESSION and DAY_OF_WEEK are):

    minute, hour     of the day, 0-59 and 0-23              CANDLE[hour=8], CANDLE[minute<15]
    wom              week of the month, 1-5 (day 1-7 is 1)  CANDLE[wom=1]
    month            JAN .. DEC                             CANDLE[month=DEC]
    quarter          QTR1 .. QTR4 (not Q1: Q1..Q4 are the close quartiles, which the flip swaps)
    month_end        the bar's date is the month's last business day        CANDLE[month_end]
    quarter_end      ... of a quarter's last month;  year_end  ... of December
    holiday          the date (in the calendar's own time zone) is a holiday of the calendar
    half_day         ... an early close

Business days, holidays and early closes come from a `Calendar`, which is configuration: a time zone,
holidays and half-days by local date, and whether weekends are closed. NYSE (the default) lists the
exchange's holidays and early closes for 2024-2026 as published; CRYPTO has none and no weekend. A
date outside the listed years simply has no holiday. Everything here is known in advance, so every
qualifier is known at its bar.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mcfl import candles
from mcfl.candles import Table

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
QUARTERS = ("QTR1", "QTR2", "QTR3", "QTR4")
NY = "America/New_York"


@dataclass(frozen=True)
class Calendar:
    """A market's calendar: local dates (YYYY-MM-DD) of holidays and of early closes (local HH:MM)."""
    name: str
    tz: str = NY
    holidays: dict[str, str] = field(default_factory=dict, hash=False)
    half_days: dict[str, str] = field(default_factory=dict, hash=False)
    weekends: bool = True  # Saturday and Sunday are not business days

    def business(self, d: dt.date) -> bool:
        return not (self.weekends and d.weekday() >= 5) and d.isoformat() not in self.holidays


NYSE = Calendar("NYSE", NY, holidays={
    "2024-01-01": "New Year", "2024-01-15": "MLK", "2024-02-19": "Presidents", "2024-03-29": "Good Friday",
    "2024-05-27": "Memorial", "2024-06-19": "Juneteenth", "2024-07-04": "Independence", "2024-09-02": "Labor",
    "2024-11-28": "Thanksgiving", "2024-12-25": "Christmas",
    "2025-01-01": "New Year", "2025-01-09": "Day of mourning (Carter)", "2025-01-20": "MLK",
    "2025-02-17": "Presidents", "2025-04-18": "Good Friday", "2025-05-26": "Memorial", "2025-06-19": "Juneteenth",
    "2025-07-04": "Independence", "2025-09-01": "Labor", "2025-11-27": "Thanksgiving", "2025-12-25": "Christmas",
    "2026-01-01": "New Year", "2026-01-19": "MLK", "2026-02-16": "Presidents", "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial", "2026-06-19": "Juneteenth", "2026-07-03": "Independence (observed)",
    "2026-09-07": "Labor", "2026-11-26": "Thanksgiving", "2026-12-25": "Christmas"},
    half_days={"2024-07-03": "13:00", "2024-11-29": "13:00", "2024-12-24": "13:00",
               "2025-07-03": "13:00", "2025-11-28": "13:00", "2025-12-24": "13:00",
               "2026-11-27": "13:00", "2026-12-24": "13:00"})
"""NYSE holidays and 13:00 early closes, 2024-2026, as the exchange published them."""
CRYPTO = Calendar("CRYPTO", "UTC", weekends=False)
"""A market that never closes: every day is a business day, no holidays."""
DEFAULT = NYSE

COLUMNS = ("minute", "hour", "wom", "month", "quarter", "month_end", "quarter_end", "year_end", "holiday", "half_day")
FLAG_COLUMNS = ("month_end", "quarter_end", "year_end", "holiday", "half_day")


def _last_business(y: int, m: int, cal: Calendar) -> dt.date:
    d = (dt.date(y + (m == 12), m % 12 + 1, 1)) - dt.timedelta(days=1)
    while not cal.business(d):
        d -= dt.timedelta(days=1)
    return d


def utc(ts: np.ndarray) -> pd.DatetimeIndex:
    return pd.to_datetime(np.asarray(ts, np.int64), unit="s", utc=True)


def columns(T: Table, ts: np.ndarray, cal: Calendar | None = None) -> None:
    """Add the calendar qualifiers to the token table, in place."""
    cal = DEFAULT if cal is None else cal
    t = utc(ts)
    T["minute"] = np.asarray(t.minute, np.int64)
    T["hour"] = np.asarray(t.hour, np.int64)
    day, mon = np.asarray(t.day), np.asarray(t.month)
    T["wom"] = (day - 1) // 7 + 1
    T["month"] = np.array(MONTHS, object)[mon - 1]
    T["quarter"] = np.array(QUARTERS, object)[(mon - 1) // 3]
    dates = np.asarray(t.normalize().date)
    ends = {}
    me = np.zeros(len(ts), bool)
    for i, d in enumerate(dates):
        k = (d.year, d.month)
        if k not in ends:
            ends[k] = _last_business(d.year, d.month, cal)
        me[i] = d == ends[k]
    T["month_end"] = me
    T["quarter_end"] = me & (mon % 3 == 0)
    T["year_end"] = me & (mon == 12)
    loc = t.tz_convert(cal.tz).strftime("%Y-%m-%d") if len(ts) else []
    T["holiday"] = np.array([x in cal.holidays for x in loc], bool)
    T["half_day"] = np.array([x in cal.half_days for x in loc], bool)
    candles.V2_CANDLE.update({k: False for k in COLUMNS})


def register() -> None:
    """The qualifier keys: `CANDLE[hour=8]`, `CANDLE[month=DEC]`, `CANDLE[month_end]` ..."""
    from mcfl import grammar
    grammar._KEYS.update({"minute": ("minute", "num"), "hour": ("hour", "num"), "wom": ("wom", "num"),
                          "month": ("month", None), "quarter": ("quarter", None)})
    grammar.FLAGS.update(FLAG_COLUMNS)


register()
