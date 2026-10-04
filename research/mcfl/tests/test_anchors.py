"""Time core items 4 and 5: time anchors as events (windows and their closes, day, week and month
opens, HTF_CLOSE) and the remaining-time qualifiers, in UTC and New York time across daylight saving."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.anchors import local, periods
from mcfl.mtf import groups
from mcfl.parse import parse


def _utc(t: int) -> pd.Timestamp:
    return pd.Timestamp(int(t), unit="s", tz="UTC")


@pytest.fixture(scope="module", params=[("winter", F.WINTER_MONDAY), ("summer", F.SUMMER_MONDAY)], ids=lambda p: p[0])
def week(request):
    name, start = request.param
    df = F.with_calendar(synth.garch(2 * 460, seed=61), 900, start, "index")  # two trading weeks of 15m bars
    return name, df, parse(df)


def test_windows_follow_their_clocks(week):
    name, df, ch = week
    ts = df["ts"].to_numpy()
    off = 5 if name == "winter" else 4  # New York is UTC-5 in January, UTC-4 in June
    for w in ch.of("WINDOW"):
        t = _utc(ts[w.at])
        s = _utc(w.get("sched_start"))
        assert s <= t < _utc(w.get("sched_end"))
        if w.get("name") == "LONDON":
            assert (s.hour, s.minute) == (7, 0)
        if w.get("name") == "LONDON_KZ":
            assert (s.hour, s.minute) == (2 + off, 0)  # 02:00 New York
        if w.get("name") == "M1310":
            assert (s.hour, s.minute) == (13 + off, 10)
    kinds = {w.get("kind") for w in ch.of("WINDOW")}
    assert kinds == {"SESSION", "KILLZONE", "MACRO"}
    # one window instance per day per name, at most; sessions every day the market is open
    lon = [w for w in ch.of("WINDOW") if w.get("name") == "LONDON"]
    assert len(lon) == 10 and len({_utc(ts[w.at]).date() for w in lon}) == 10


def test_window_close_is_known_when_the_clock_passes_the_end(week):
    _, df, ch = week
    ts = df["ts"].to_numpy()
    ids = ch.by_id()
    for c in ch.of("WINDOW_CLOSE"):
        w = ids[c.get("window")]
        assert c.at >= w.at and ts[c.at] < w.get("sched_end")
        if c.get("complete"):
            assert c.known_at == c.at and ts[c.at] + 900 >= w.get("sched_end")
        else:
            assert c.known_at == c.at + 1 and ts[c.at] + 900 < w.get("sched_end") <= ts[c.at + 1]
        assert (c.time.start, c.time.end) == (w.at, c.at)
    # the index closes 21:00-22:00: NY (16:00-22:00) ends at 21:00 with no bar until 22:00
    ny = [c for c in ch.of("WINDOW_CLOSE") if c.get("name") == "NY"]
    assert ny and all(not c.get("complete") for c in ny)
    lon = [c for c in ch.of("WINDOW_CLOSE") if c.get("name") == "LONDON"]
    assert lon and all(c.get("complete") and _utc(ts[c.at]).hour == 11 for c in lon)


def test_day_week_month_opens(week):
    name, df, ch = week
    ts = df["ts"].to_numpy()
    days = {(e.get("clock"), e.at) for e in ch.of("DAY_OPEN")}
    for t in range(1, len(ts)):
        assert (("UTC", t) in days) == (ts[t] // 86400 != ts[t - 1] // 86400)
    nday = local(ts, "America/New_York")[0]
    for t in range(1, len(ts)):
        assert (("NY", t) in days) == (nday[t] != nday[t - 1])
    assert ("UTC", 0) in days  # bar 0 opens at midnight
    wk = ch.of("WEEK_OPEN")
    # the trading week opens Sunday 17:00 New York; the index's first bar after it is Sunday 22:00 UTC
    assert [(_utc(ts[e.at]).day_name(), _utc(ts[e.at]).hour) for e in wk] == [("Sunday", 22)] * 2  # bar 0 is Monday 00:00
    assert not ch.of("MONTH_OPEN") or all(_utc(ts[e.at]).day == 1 for e in ch.of("MONTH_OPEN"))


def test_htf_close_is_the_moment_the_htf_bar_is_complete(week):
    _, df, ch = week
    ts = df["ts"].to_numpy()
    closes = [e for e in ch.of("HTF_CLOSE") if e.get("tf") == "4h"]
    gs = groups(df, 14400, None)
    assert [(e.time.start, e.at, e.known_at, e.get("period_ts")) for e in closes] == [g[:4] for g in gs]
    for e in closes:
        a, b = e.time.start, e.at
        seg = df.iloc[a:b + 1]
        assert (e.get("open"), e.get("high"), e.get("low"), e.get("close")) == (
            seg["open"].iloc[0], seg["high"].max(), seg["low"].min(), seg["close"].iloc[-1])
    # a Friday 20:00 period ends at 21:00 when the index closes: known at Sunday's first bar
    fri = [e for e in closes if _utc(e.get("period_ts")).day_name() == "Friday" and _utc(e.get("period_ts")).hour == 20]
    assert fri and all(_utc(ts[e.known_at]).day_name() == "Sunday" for e in fri)
    assert {e.get("tf") for e in ch.of("HTF_CLOSE")} == {"1h", "4h", "1d"}
    assert all(e.known_at in (e.at, e.at + 1) for e in ch.of("HTF_CLOSE"))


def test_periods_need_an_observed_close():
    ts = np.array([0, 900, 1800, 2700], np.int64) + 86400 * 100
    assert periods(ts, np.array([0, 900, 900, 900]), 3600) == [(0, 3, 3, 86400 * 100, 24 * 100)]
    assert periods(ts[:3], np.array([0, 900, 900]), 3600) == []  # 2700 is not reached yet


def test_remaining_time(week):
    _, df, ch = week
    ts = df["ts"].to_numpy()
    for c in ch.of("CANDLE")[1::37]:  # bar 0's length is a guess (`clocks.first_length`)
        close = ts[c.at] + 900
        assert c.get("left_4h") == (ts[c.at] // 14400 + 1) * 14400 - close
        assert c.get("prog_4h") == pytest.approx((close - ts[c.at] // 14400 * 14400) / 14400)
        assert c.get("left_day") == (ts[c.at] // 86400 + 1) * 86400 - close
        h = _utc(ts[c.at]).hour
        end = {"ASIA": 7, "LONDON": 12, "OVERLAP": 16, "NY": 22}[c.get("session")]
        left = ((end - h) % 24) * 3600 - (ts[c.at] % 3600) - 900
        assert c.get("left_session") == left
    q = [c for c in ch.of("CANDLE") if c.get("prog_4h") == 1.0 and c.at > 0]
    assert q and all(_utc(ts[c.at]).hour % 4 == 3 and _utc(ts[c.at]).minute == 45 for c in q)
    from mcfl.grammar import q as qual
    assert qual("CANDLE[prog.4h≥0.75]")[0].field == "prog_4h"
    assert qual("CANDLE[killzone=LONDON_KZ]")[0].field == "killzone"
