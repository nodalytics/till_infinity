"""Every mirrored setup must be able to fire both ways: the code-symmetry test.

A rule built on log prices fired long only once mirrored (the flipped chart is negative), and was
validated as if two-sided. On a driftless walk each side should fire a fair share of the time."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import setups as S  # noqa: E402

ONE_SIDED = {"rug_short", "btc_overnight", "volume_day", "divergence", "usd_confluence", "fatigue",
             "physics", "ts_momentum", "focus_size", "level_reaction", "zma", "ma_reaction",
             "asia_sweep", "silver_bullet", "focus_mtf", "tf_coherent_breakout", "htf_pullback",
             "cusum_x_trend", "anomaly_x_trend", "cusum_x_anomaly", "breakout_x_cusum"}


def _walk(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.01))
    df = pd.DataFrame({"ts": np.arange(n) * 3600, "open": np.r_[c[0], c[:-1]], "close": c})
    wick = np.abs(rng.standard_normal((n, 2))) * 0.004
    df["high"] = df[["open", "close"]].max(axis=1) * (1 + wick[:, 0])
    df["low"] = df[["open", "close"]].min(axis=1) * (1 - wick[:, 1])
    df["tick_volume"] = rng.integers(50, 150, n)
    return df


@pytest.mark.parametrize("name", sorted(set(S.SETUPS) - ONE_SIDED))
def test_a_mirrored_setup_fires_both_ways_on_a_walk(name):
    df = _walk()
    out = S.SETUPS[name](S.Ctx("WALK", "fx", "1h", 3600, df))
    if out.empty or len(out) < 20:
        pytest.skip(f"{name} fires too rarely on this walk to judge")
    up = (out["side"] > 0).mean()
    assert 0.2 < up < 0.8, f"{name}: {up:.0%} of its signals are long"
