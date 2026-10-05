"""The LRC computation against hand-computed regressions, and the trade mechanics of lrc_retest.py."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import lrc_retest as L  # noqa: E402


def test_lrc_hand_computed():
    # closes 1, 3, 2, 5 over x = 0..3: xbar 1.5, ybar 2.75, Sxy = 5.5, Sxx = 5 -> slope 1.1,
    # intercept 2.75 - 1.65 = 1.1, endpoint 1.1 + 3.3 = 4.4; residuals -0.1, 0.8, -1.3, 0.6 -> RMS sqrt(2.7/4)
    s, m, d = L.lrc(np.array([1.0, 3.0, 2.0, 5.0]), 4)
    assert np.isnan(s[:3]).all()
    assert abs(s[3] - 1.1) < 1e-12
    assert abs(m[3] - 4.4) < 1e-12
    assert abs(d[3] - np.sqrt(2.7 / 4)) < 1e-12


def test_lrc_matches_polyfit_and_pine_linreg():
    rng = np.random.default_rng(0)
    c = 100 + np.cumsum(rng.normal(size=600))
    for n in (50, 100, 200):
        s, m, d = L.lrc(c, n, chunk=97)
        for t in (n - 1, 333, 599):
            y = c[t - n + 1:t + 1]
            b, a = np.polyfit(np.arange(n), y, 1)
            assert abs(s[t] - b) < 1e-9
            assert abs(m[t] - (a + b * (n - 1))) < 1e-8  # ta.linreg(close, n, 0)
            assert abs(d[t] - np.sqrt(np.mean((y - (a + b * np.arange(n))) ** 2))) < 1e-8


def test_lrc_flip_is_negated():
    rng = np.random.default_rng(1)
    c = 50 + np.cumsum(rng.normal(size=300))
    s, m, d = L.lrc(c, 100)
    s2, m2, d2 = L.lrc(-c, 100)
    np.testing.assert_allclose(s2[99:], -s[99:])
    np.testing.assert_allclose(m2[99:], -m[99:])
    np.testing.assert_allclose(d2[99:], d[99:])


def test_rsi_extremes():
    up = np.arange(100, dtype=float)
    assert L.rsi(up)[-1] == 100.0
    assert L.rsi(up[::-1])[-1] < 1e-9


def test_pivots_three_three():
    h = np.array([1, 2, 3, 9, 3, 2, 9, 1, 1, 1], float)
    hi, _ = L.pivots(h, h - 1)
    assert hi[3] and not hi[6]  # bar 6 equals bar 3 on its left within 3 bars: not strictly above
    _, lo = L.pivots(-h + 20, -h + 19)
    assert lo[3]


def _frame(c, spread=0.0):
    c = np.asarray(c, float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.2
    l = np.minimum(o, c) - 0.2
    return o, h, l, c


def test_exits_target_stop_and_fill_bar():
    o, h, l, c = _frame([10, 10, 10, 10, 10, 10])
    l[1] = 8.0  # the fill bar touches the stop: a loss with slippage
    r = L.exits(o, h, l, c, 1, 10.0, 9.0, 1.0, 0.0, None)
    assert abs(r["X2"] - (-1.0 - L.SLIP)) < 1e-12
    o, h, l, c = _frame([10, 10, 10.5, 11, 12.5, 12.5])
    r = L.exits(o, h, l, c, 1, 10.0, 9.0, 1.0, 0.1, None)
    assert abs(r["X2"] - (2.0 - 0.1)) < 1e-12  # target 12 reached on bar 4, cost 0.1 / risk 1
    assert r["x2_bar"] == 4
    assert r["mfe"] >= 2.0


def test_reach_counts_stop_first_on_a_bar_touching_both():
    o, h, l, c = _frame([10, 10, 10, 10])
    h[2], l[2] = 15.0, 8.0
    assert abs(L.reach(h, l, 0, 10.0, 9.0, 1.0, 10.0) - 0.2) < 1e-9  # bar 1 (10.2), then the stop bar; the fill bar never counts


def test_bos_and_retest_fire_both_ways_on_a_walk():
    rng = np.random.default_rng(3)
    n = 3000
    c = 1000 + np.cumsum(rng.normal(size=n))
    o = np.r_[c[0], c[:-1]]
    e = np.abs(rng.normal(size=n)) * 0.5
    df = pd.DataFrame({"ts": np.arange(n) * 3600, "open": o, "close": c,
                       "high": np.maximum(o, c) + e, "low": np.minimum(o, c) - e})
    trades, holds = L.scan(df, np.full(n, 0.01), twin_seed=1)
    t = pd.DataFrame(trades)
    for rule in ("R1", "R2", "R3", "R4"):
        sides = set(t.loc[t["rule"] == rule, "side"])
        assert sides == {1, -1}, (rule, sides)
    r1 = t[t["rule"] == "R1"]
    assert (r1["risk_atr"] >= L.MIN_RISK - 1e-6).all()
    assert (r1["f"] > r1["b"]).all() and (r1["f"] <= r1["b"] + L.WINDOW).all()
    assert (r1["b"] >= r1["p"] + L.SWING + 1).all()  # the swing is known before it breaks
    assert r1["tw_X2"].notna().all()
    assert {"SWING", "BOS"} <= set(pd.DataFrame(holds)["type"])


def test_fill_path_mirror():
    # a down bar O-H-L-C filled while falling: after the fill only L and C; mirrored it is an up bar
    # O-L-H-C filled while rising: only H and C
    assert L.fill_path(10.0, 12.0, 7.0, 8.0, 9.0, "down") == [7.0, 8.0]
    assert L.fill_path(-10.0, -7.0, -12.0, -8.0, -9.0, "up") == [-7.0, -8.0]
    # an up bar O-L-H-C filled while falling: L, then H, then C all come after the fill
    assert L.fill_path(10.0, 13.0, 8.0, 12.0, 9.0, "down") == [8.0, 13.0, 12.0]
