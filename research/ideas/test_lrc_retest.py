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


# ------------------------------------------------- structural targets (XL / XI / XF)


class _F:
    """The three arrays `leg_top` and `imbalance_top` read, and nothing else."""

    def __init__(self, h, l):
        self.h, self.l = np.asarray(h, float), np.asarray(l, float)
        self.n = len(self.h)


def test_leg_top_is_the_highest_high_in_the_window():
    F = _F(h=[10, 12, 15, 13, 11], l=[9, 11, 14, 12, 10])
    assert L.leg_top(F, 0, 4) == 15.0
    # The window is clipped at WINDOW bars past the break, like `strength`.
    assert L.leg_top(F, 1, 2) == 15.0
    assert L.leg_top(F, 3, 4) == 13.0


def test_an_imbalance_is_the_three_bar_gap_and_its_far_side_is_the_target():
    # Bar 2 displaces: low[3] = 14 is above high[1] = 11, so bars 1-3 leave a gap.
    F = _F(h=[10, 11, 16, 17, 18], l=[9, 10, 12, 14, 15])
    assert L.imbalance_top(F, 0, 4, entry=10.0) == 14.0


def test_a_leg_with_no_gap_has_no_imbalance_target():
    """Most quiet legs. NaN rather than a substitute, so the trades that have one
    can be read on their own instead of being averaged with the ones that do not.

    The bars have to *overlap* for there to be no gap - a steady climb whose
    bars clear each other is a run of imbalances, which is the point of the
    pattern and was the bug in this test's first fixture.
    """
    F = _F(h=[10, 11, 12, 13, 14], l=[9, 9.5, 10, 10.5, 11])
    assert np.isnan(L.imbalance_top(F, 0, 4, entry=10.0))


def test_an_imbalance_price_has_traded_back_through_is_not_a_target():
    """A gap that has been filled is history, not a destination."""
    # Exactly one gap: low[3] = 14 clears high[1] = 11, and no other triple does.
    gapped = _F(h=[10, 11, 12, 17, 18], l=[9, 9.5, 10, 14, 11.5])
    assert L.imbalance_top(gapped, 0, 4, entry=10.0) == 14.0
    # The same leg, with the last bar trading back down through high[1].
    filled = _F(h=[10, 11, 12, 17, 18], l=[9, 9.5, 10, 14, 10.5])
    assert np.isnan(L.imbalance_top(filled, 0, 4, entry=10.0))


def test_the_imbalance_target_is_the_furthest_one_still_open():
    """"Way past the imbalance candles" - the far side of the last gap price has
    not come back through, not the first one it would meet."""
    F = _F(h=[10, 11, 12, 17, 18, 24], l=[9, 9.5, 10, 14, 15, 20])
    assert L.imbalance_top(F, 0, 5, entry=10.0) == 20.0


def test_an_imbalance_below_the_fill_is_not_a_target_either():
    F = _F(h=[10, 11, 16, 17, 18], l=[9, 10, 12, 14, 15])
    assert np.isnan(L.imbalance_top(F, 0, 4, entry=20.0))


def test_a_structural_target_uses_the_same_fill_and_stop_rules_as_2r():
    o, h, l, c = _frame([10, 10, 10.5, 11, 12.5, 12.5])
    r = L.exits(o, h, l, c, 1, 10.0, 9.0, 1.0, 0.1, None, tgts={"XL": 12.0})
    # A limit at 12.0 is the 2R target here, so the two must agree exactly.
    assert abs(r["R_XL"] - r["X2"]) < 1e-12
    assert abs(r["d_XL"] - 2.0) < 1e-12


def test_a_target_at_or_below_the_fill_is_recorded_as_absent():
    o, h, l, c = _frame([10, 10, 10.5, 11, 12.5, 12.5])
    r = L.exits(o, h, l, c, 1, 10.0, 9.0, 1.0, 0.1, None, tgts={"XI": float("nan"), "XL": 9.5})
    assert np.isnan(r["R_XI"])
    assert np.isnan(r["d_XI"])
    assert np.isnan(r["R_XL"])


def test_a_further_structural_target_is_further_in_r_and_hit_less_often():
    o, h, l, c = _frame([10, 10, 10.5, 11, 12.5, 12.5])
    r = L.exits(o, h, l, c, 1, 10.0, 9.0, 1.0, 0.0, None, tgts={"near": 11.0, "far": 20.0})
    assert abs(r["d_near"] - 1.0) < 1e-12
    assert abs(r["d_far"] - 10.0) < 1e-12
    assert abs(r["R_near"] - 1.0) < 1e-12
    # 20.0 is never reached, so the trade runs to the cap and closes at 12.5.
    assert abs(r["R_far"] - 2.5) < 1e-12
