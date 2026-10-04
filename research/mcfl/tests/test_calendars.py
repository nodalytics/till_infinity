"""Time core item 3: calendar tokens - minute, hour, week of month, month, quarter, month / quarter /
year ends and holidays and half-days from a configurable calendar - as CANDLE qualifiers."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from mcfl import calendars as K
from mcfl.core import flip_value
from mcfl.grammar import Clause, q


def _ts(*stamps: str) -> np.ndarray:
    return np.array([int(pd.Timestamp(s, tz="UTC").timestamp()) for s in stamps], np.int64)


def _cols(ts: np.ndarray, cal=None) -> dict:
    T: dict = {}
    K.columns(T, ts, cal)
    return T


def test_clock_words():
    T = _cols(_ts("2024-01-01 00:00", "2024-02-08 13:45", "2024-05-15 23:59", "2024-12-29 07:30"))
    assert list(T["minute"]) == [0, 45, 59, 30] and list(T["hour"]) == [0, 13, 23, 7]
    assert list(T["wom"]) == [1, 2, 3, 5]  # days 1-7 are week 1, 8-14 week 2, ...
    assert list(T["month"]) == ["JAN", "FEB", "MAY", "DEC"]
    assert list(T["quarter"]) == ["QTR1", "QTR1", "QTR2", "QTR4"]
    assert flip_value("quarter", "QTR1") == "QTR1"  # not Q1, which the flip would swap with Q4


def test_period_ends_follow_the_calendar():
    T = _cols(_ts("2024-03-28 15:00", "2024-03-29 15:00", "2024-06-28 15:00", "2024-06-27 15:00",
                  "2024-12-31 15:00", "2024-11-29 15:00"))
    # Good Friday (Mar 29) is closed: the 28th is March's last business day
    assert list(T["month_end"]) == [True, False, True, False, True, True]
    assert list(T["quarter_end"]) == [True, False, True, False, True, False]
    assert list(T["year_end"]) == [False, False, False, False, True, False]
    c = _cols(_ts("2024-03-28 15:00", "2024-03-31 15:00"), K.CRYPTO)
    assert list(c["month_end"]) == [False, True]  # a market that never closes ends its month on the 31st


def test_holidays_and_half_days_in_local_time():
    T = _cols(_ts("2024-07-04 15:00", "2024-07-04 02:00", "2024-07-03 15:00", "2024-07-05 15:00"))
    # 02:00 UTC on the 4th is 22:00 on the 3rd in New York: the half-day, not the holiday
    assert list(T["holiday"]) == [True, False, False, False]
    assert list(T["half_day"]) == [False, True, True, False]
    mine = K.Calendar("DESK", "UTC", holidays={"2024-07-05": "desk day"}, weekends=False)
    assert list(_cols(_ts("2024-07-05 15:00"), mine)["holiday"]) == [True]


@pytest.mark.parametrize(("spec", "want"), [
    ("CANDLE[hour=8]", (Clause("hour", "==", 8.0),)),
    ("CANDLE[minute<15]", (Clause("minute", "<", 15.0),)),
    ("CANDLE[month=DEC]", (Clause("month", "==", "DEC"),)),
    ("CANDLE[month_end]", (Clause("month_end", "==", True),)),
    ("CANDLE[not holiday]", (Clause("holiday", "==", False),)),
])
def test_qualifiers(spec, want):
    assert q(spec) == want


def test_on_the_chart():
    import fixtures as F
    from mcfl import synth
    from mcfl.parse import parse
    df = F.with_calendar(synth.walk(400, seed=1), 3600, int(pd.Timestamp("2024-03-25", tz="UTC").timestamp()))
    ch = parse(df)
    c = {e.at: e for e in ch.of("CANDLE")}
    ts = df["ts"].to_numpy()
    for t in range(len(ts)):
        d = pd.Timestamp(int(ts[t]), unit="s", tz="UTC")
        assert (c[t].get("hour"), c[t].get("month")) == (d.hour, K.MONTHS[d.month - 1])
        assert c[t].get("month_end") == (d.strftime("%Y-%m-%d") == "2024-03-28")
