"""Tests for fxml_data: causality of every feature, the targets, the structural-stop MFE.

  PYTHONPATH=<repo>:<repo>/research:<repo>/research/ideas python -m pytest research/ideas/test_fxml.py
"""
import numpy as np
import pandas as pd

import fxml_data as D


def bars(n=900, seed=0, sec=3600):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.001, n)))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.001, n)))
    ts = 1_600_000_000 // sec * sec + sec * np.arange(n)
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c})


def test_features_are_causal():
    df = bars()
    full, _ = D.features(df, "1h", False)
    for cut in (400, 650, 899):
        part, _ = D.features(df.iloc[:cut + 1].reset_index(drop=True), "1h", False)
        a, b = full.iloc[cut].to_numpy(float), part.iloc[cut].to_numpy(float)
        bad = ~((a == b) | (np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-5, atol=1e-6))
        assert not bad.any(), list(full.columns[bad])


def test_lrc_slope_and_r():
    c = np.array([1.0, 3.0, 2.0, 5.0])
    s, r = D.lrc_stats(c, 4)
    assert np.isclose(s[-1], 1.1)
    assert np.isclose(r[-1], np.corrcoef(np.arange(4), c)[0, 1])


def test_mfe_long():
    # entry at O[1] = 10, 3-bar low 9.5 - 0.1*1 -> stop 9.4, risk 0.6
    o = np.array([10, 10, 10.5, 11.0, 11.5, 9.0])
    h = np.array([10.2, 10.6, 11.2, 11.9, 11.6, 9.1])
    l = np.array([9.5, 9.8, 10.4, 10.9, 9.0, 8.5])
    c = np.array([10, 10.5, 11.0, 11.5, 9.2, 8.6])
    a = np.ones(6)
    mfe, risk, stopped, tst = D.mfe_side(o, h, l, c, a)
    # row 2: low3 over bars 0..2 = 9.5, stop 9.4, entry O[3] = 11.0 -> risk 1.6
    assert np.isclose(risk[2], 1.6)
    # bar 3 (up): low 10.9 > stop, high 11.9 -> 0.9/1.6; bar 4 (down): high 11.6 first, then low 9.0 hits
    assert np.isclose(mfe[2], 0.9 / 1.6)
    assert stopped[2] and tst[2] == 2


def test_min_risk_floor():
    o = np.array([10, 10, 10, 10.0, 10.0])
    h = np.array([10.01] * 5)
    l = np.array([9.99] * 5)
    c = np.array([10.0] * 5)
    a = np.ones(5)
    _, risk, _, _ = D.mfe_side(o, h, l, c, a)
    assert np.isclose(risk[2], 0.25)


def test_targets_first_and_sign():
    df = bars(300, 3)
    F, a = D.features(df, "1h", False)
    T, _ = D.targets(df, a, "1h")
    c = df["close"].to_numpy()
    assert T["sign1"].iloc[10] == float(c[11] > c[10])
    assert np.isnan(T["sign1"].iloc[-1])


def test_rollover_trim():
    ts = np.array([pd.Timestamp("2024-07-01 21:00", tz="UTC").timestamp(),
                   pd.Timestamp("2024-01-08 22:00", tz="UTC").timestamp(),
                   pd.Timestamp("2024-01-08 21:00", tz="UTC").timestamp()]).astype(np.int64)
    df = pd.DataFrame({"ts": ts, "open": [1.0] * 3, "close": [1.1] * 3, "high": [2.0] * 3, "low": [0.5] * 3})
    t = D.trim_rollover(df, "1h")
    assert list(t["high"]) == [1.1, 1.1, 2.0]
    assert list(t["low"]) == [1.0, 1.0, 0.5]


def test_polyfit_quadratic_exact():
    n = 200
    x = np.arange(n, dtype=float)
    c = 100 + 0.5 * x + 0.01 * x ** 2
    F = {}
    a = np.ones(n)
    D.polyfit_block(c, a, F)
    t = n - 1
    # slope at t = 0.5 + 0.02 t, curvature 0.02, residual 0, extrapolation c(t+1) - c(t), R^2 1
    assert np.isclose(F["pf20_2_slope"][t], 0.5 + 0.02 * t)
    assert np.isclose(F["pf50_3_curv"][t], 0.02)
    assert np.isclose(F["pf100_3_jerk"][t], 0.0, atol=1e-8)
    assert np.isclose(F["pf20_2_resid"][t], 0.0, atol=1e-8)
    assert np.isclose(F["pf20_2_ext1"][t], 0.5 + 0.01 * (2 * t + 1))
    assert np.isclose(F["pf100_2_r2"][t], 1.0)


def test_ohlc_block_is_causal():
    df = bars(700, 5)
    _, a = D.features(df, "1h", False)
    full = D.ohlc_block(df, a)
    for cut in (400, 699):
        d2 = df.iloc[:cut + 1].reset_index(drop=True)
        _, a2 = D.features(d2, "1h", False)
        part = D.ohlc_block(d2, a2)
        x, y = full.iloc[cut].to_numpy(float), part.iloc[cut].to_numpy(float)
        bad = ~((x == y) | (np.isnan(x) & np.isnan(y)) | np.isclose(x, y, rtol=1e-5, atol=1e-6))
        assert not bad.any(), list(full.columns[bad])


def test_session_x_us_open():
    # 2025-07-01 13:00 UTC 1h bar = 09:00-10:00 New York (EDT): contains the 09:30 open; at its close
    # 10:00 NY it is 0.5h since the open and inside regular hours
    ts = np.array([pd.Timestamp("2025-07-01 13:00", tz="UTC").timestamp()], np.int64)
    F = D.session_x(ts, "1h")
    assert F["x_us_open_in_bar"][0] == 1.0
    assert np.isclose(F["x_us_since_open"][0], 0.5)
    assert F["x_us_rth"][0] == 1.0
    # Frankfurt (CEST) 15:00-16:00: no EU open in the bar, 7h since the 09:00 open
    assert F["x_eu_open_in_bar"][0] == 0.0
    assert np.isclose(F["x_eu_since_open"][0], 7.0)


def test_add_roll_slope_and_touch():
    import fxml_add as A
    y = np.arange(10, dtype=float) * 2.0 + 1
    s, r = A.roll_slope(y, 5)
    assert np.isclose(s[-1], 2.0) and np.isclose(r[-1], 1.0) and np.isnan(s[3])
    sw, _ = A.roll_slope(y, 5, np.ones(10))
    assert np.isclose(sw[-1], 2.0)
    h = np.array([1.0, 1.5, 2.6, 1.0, 1.0, 1.0])
    l = np.array([0.5, 0.4, 0.9, 0.2, 0.9, 0.9])
    up, dn, first = A.first_touch(h, l, np.full(6, 2.5), np.full(6, 0.3), 2)
    # from bar 0: bar 1 neither, bar 2 high 2.6 -> up first
    assert up[0] == 1.0 and dn[0] == 0.0 and first[0] == 1.0
    # from bar 1: bar 2 up, bar 3 low 0.2 -> up first, both reached
    assert first[1] == 1.0 and dn[1] == 1.0
    assert np.isnan(up[5])
