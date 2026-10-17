"""Tests for the deriv-ml harness: the null tick engine, bar aggregation, splits and the baselines.

  python -m pytest research/ideas/test_derivml.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import derivml_data as D  # noqa: E402


def test_split_rule():
    early = np.array([pd.Timestamp("2019-01-01", tz="UTC").timestamp(), pd.Timestamp("2026-10-01", tz="UTC").timestamp()],
                     dtype=np.int64)
    assert D.split_ts(early) == D.SPLIT
    late = np.array([pd.Timestamp("2025-01-01", tz="UTC").timestamp(), pd.Timestamp("2026-01-01", tz="UTC").timestamp()],
                    dtype=np.int64)
    s = D.split_ts(late)
    assert s % 86400 == 0 and late[0] < s < late[1]
    assert abs(s - (late[0] + late[1]) / 2) <= 86400


def test_tickgen_regenerates_its_hours():
    prm = dict(kind="gbm", sigma=0.75, dt_s=2.0)
    g = D.TickGen("Volatility 75 Index", prm, seed=123)
    ts, H, lev = g.hourly(20000, 20003, 1000.0)
    assert H.shape == (72, 4) and len(lev) == 3
    ms, P = g.ticks(20001, float(lev[1]))
    assert len(P) == 43200
    hr = P.reshape(24, -1)
    np.testing.assert_allclose(hr[:, 0], H[24:48, 0])
    np.testing.assert_allclose(hr.max(1), H[24:48, 1])
    np.testing.assert_allclose(hr.min(1), H[24:48, 2])
    np.testing.assert_allclose(hr[:, -1], H[24:48, 3])
    assert ms[0] == 20001 * 86400000 and ms[1] - ms[0] == 2000
    # continuity: day 2 starts from day 1's last tick
    assert np.isclose(lev[2], H[47, 3])


def test_gbm_null_sigma():
    prm = dict(kind="gbm", sigma=0.5, dt_s=1.0)
    g = D.TickGen("Volatility 50 (1s) Index", prm, seed=7)
    ts, H, lev = g.hourly(20000, 20060, 1000.0)
    r = np.diff(np.log(H[:, 3]))
    sig = np.std(r) * np.sqrt(24 * 365)
    assert abs(sig / 0.5 - 1) < 0.05


def test_step_null_is_fair():
    prm = dict(kind="step", values=[-0.1, 0.1], probs=[0.5, 0.5], dt_s=1.0)
    g = D.TickGen("Step Index", prm, seed=3)
    inc = g.increments(20000)
    assert set(np.round(np.unique(inc), 6)) == {-0.1, 0.1}
    assert abs(np.mean(inc > 0) - 0.5) < 0.01


def test_agg_hours():
    ts = np.arange(0, 48) * 3600 + 20000 * 86400
    H = np.c_[np.arange(48.0), np.arange(48.0) + 1, np.arange(48.0) - 1, np.arange(48.0) + 0.5]
    t4, B4 = D.agg_hours(ts, H, 14400)
    assert len(t4) == 12 and (t4 % 14400 == 0).all()
    np.testing.assert_allclose(B4[0], [0.0, 4.0, -1.0, 3.5])
    t1, B1 = D.agg_hours(ts, H, 86400)
    np.testing.assert_allclose(B1[1], [24.0, 48.0, 23.0, 47.5])


def test_excursion_sides():
    df = pd.DataFrame({"open": [10.0], "high": [13.0], "low": [9.0], "close": [11.0]})
    assert D.excursion(df, 1)[0] == 3.0
    assert D.excursion(df, -1)[0] == 1.0
    assert D.excursion(df, 0)[0] == 3.0


def test_features_are_causal():
    """Changing bar t+1 onward must not change any feature at bar t."""
    rng = np.random.default_rng(0)
    n = 700
    c = 1000 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.002, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.002, n))
    ts = (np.arange(n) + 20000 * 24) * 3600
    df = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c})
    F1, _, _ = D.features(df, "1h", "Volatility 75 Index", D.SPLIT)
    df2 = df.copy()
    df2.loc[600:, ["open", "high", "low", "close"]] *= 1.05
    F2, _, _ = D.features(df2, "1h", "Volatility 75 Index", D.SPLIT)
    a, b = F1.iloc[:600].to_numpy(), F2.iloc[:600].to_numpy()
    same = (a == b) | (np.isnan(a) & np.isnan(b))
    bad = [F1.columns[j] for j in np.flatnonzero(~same.all(0))]
    # the 1d multi-timeframe slope reads the last COMPLETED day, so a day that ends after bar 599 is unseen
    assert not bad, bad
