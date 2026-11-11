"""The two-clock rule's construction, where the lookahead would live.

`daily_frame` is the only place in this file that could see the future: the
range is a *daily* object used by *intraday* bars, so an off-by-one hands a
day the range that includes itself. These pin the two directions separately.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dualthrust import Series  # noqa: E402
from dualthrust_session import daily_frame, run_session  # noqa: E402

DAY = 86_400.0
BAR = 900.0


def _series(days: int = 12, bars: int = 96) -> Series:
    """`days` UTC days of 15m bars whose daily ranges grow, so a day that read
    its own range would be visibly different from one that read the day before.
    """
    ts, op, hi, lo, cl = [], [], [], [], []
    price = 100.0
    for d in range(days):
        width = 1.0 + d  # a range that grows every day, which is the tell
        for b in range(bars):
            t = d * DAY + b * BAR
            ts.append(t)
            op.append(price)
            hi.append(price + width / 2)
            lo.append(price - width / 2)
            cl.append(price)
    return Series(
        feed="TEST",
        venue="test",
        interval="15m",
        ts=np.array(ts, dtype=float),
        open=np.array(op),
        high=np.array(hi),
        low=np.array(lo),
        close=np.array(cl),
    )


def test_the_range_uses_only_days_before_today():
    """**The lookahead that would matter.** Each day's range grows by one, so
    a day reading its own bars would carry a strictly larger width than one
    reading the days before it - which is what this separates."""
    series = _series()
    width, _opens = daily_frame(series)
    day = np.floor(series.ts / DAY).astype(int)

    # Day 8 is the first with 8 complete days behind it.
    at = np.flatnonzero(day == 8)
    got = width[at]
    assert np.all(np.isfinite(got)), "day 8 should have a range"
    assert len(set(np.round(got, 9))) == 1, "the range must be constant within a day"

    # Days 0..7 have widths 1..8; the thrust range over them is max(hh-lc, hc-ll).
    # Whatever its exact value, it must be strictly below what day 8's own
    # bars would give if they were included.
    assert got[0] < 9.0, "day 8 read a range that includes its own bars"


def test_a_day_without_enough_history_has_no_range():
    """No range is absent rather than zero: a zero width would make the
    trigger the open itself and fire on every bar."""
    series = _series()
    width, _opens = daily_frame(series)
    day = np.floor(series.ts / DAY).astype(int)
    assert np.all(np.isnan(width[day < 8])), "a day with too little history was given a range"


def test_the_reference_open_is_the_day_s_first_open_and_not_the_bar_s():
    """The rule triggers off **today's open**, held constant all day. Using
    each bar's own open is the published rule and a different object."""
    series = _series()
    _width, opens = daily_frame(series)
    day = np.floor(series.ts / DAY).astype(int)
    for d in (8, 9, 10):
        at = np.flatnonzero(day == d)
        assert len(set(np.round(opens[at], 9))) == 1, "the reference open moved within a day"
        assert opens[at][0] == series.open[at[0]], "it is not the day's first open"


def test_the_flat_ends_the_day_rather_than_freeing_a_re_entry():
    """**The defect the trade count caught.** Flattening at 21:00 clears the
    position, and without a day guard the next bar sees `pos == 0` and
    re-enters on a trigger still touched - 5,669 trades where the rule takes
    about ten a month. The duty cycle is the object under test.
    """
    series = _series(days=14)
    width, opens = daily_frame(series)
    # A trigger near zero so every eligible bar would fire if it could.
    trades = run_session(series, width, opens, 0.01, 21)
    day = np.floor(series.ts / DAY).astype(int)
    entered = [int(day[t.enter]) for t in trades]
    assert entered == sorted(set(entered)), f"more than one entry on a day: {entered}"


def test_without_a_flat_it_is_the_always_invested_rule():
    """`DTS_FLAT=-1` turns the exit off, which is the arm that says how much
    the flat is worth rather than assuming it."""
    series = _series(days=14)
    width, opens = daily_frame(series)
    assert run_session(series, width, opens, 0.01, -1) is not None
