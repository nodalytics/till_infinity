"""Causality and mechanics of wick_levels.py and wick_info.py (walks and hand-made bars only)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import lrc_retest as LR  # noqa: E402
import wick_info as WI  # noqa: E402
import wick_levels as WL  # noqa: E402


def _walk(n=3000, seed=1):
    from mcfl import synth
    w = synth.walk(n, sigma=1.0, seed=seed, steps=64).reset_index(drop=True)
    w["ts"] = 1_700_000_000 + 3600 * np.arange(len(w))
    return w[["ts", "open", "high", "low", "close", "volume"]]


def test_counts_read_only_closed_bars():
    w = _walk()
    X = tuple(w[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = LR.atr(X[1], X[2], X[3])
    ev, _ = WL.level_rows(X, w["ts"].to_numpy(), a, np.zeros(len(w)), 1)
    assert len(ev) > 50
    for e in ev[::7]:
        f, wb = e["f"], e["w"]
        # scramble everything from the test bar on: the counts must not move
        Y = [x.copy() for x in X]
        rng = np.random.default_rng(f)
        for k in range(4):
            Y[k][f:] = Y[k][f:] + rng.normal(0, 5, len(Y[k]) - f)
        Y[1][f:] = np.maximum.reduce([Y[0][f:], Y[1][f:], Y[2][f:], Y[3][f:]])
        Y[2][f:] = np.minimum.reduce([Y[0][f:], Y[1][f:], Y[2][f:], Y[3][f:]])
        a2 = LR.atr(Y[1], Y[2], Y[3])
        wbm, u, top = WL.wick_bars(*Y, a2)
        cnt, mtop, _ = WL.counts_at(f, Y[1][wb], WL.TOL * a2[wb], a2[wb], Y[1], Y[3], wbm, u, top, a2)
        for k in ("K", "K50", "tests", "B"):
            assert cnt[k] == e[k], (k, cnt[k], e[k])
        assert e["K"] >= 1  # the spawning wick is always a member


def test_hold_label_by_hand():
    # a resistance at 10.0 from a wick at bar 70; price leaves, comes back at bar 80 and reverses
    n = 120
    c = np.full(n, 9.0)
    o = c.copy()
    h = c + 0.2
    l = c - 0.2
    o[70], c[70], h[70], l[70] = 9.3, 9.2, 10.0, 9.1      # upper wick 0.7, body 0.1, range 0.9
    for k in range(71, 79):
        o[k], c[k], h[k], l[k] = 8.0, 8.0, 8.2, 7.8        # leaves by more than an ATR
    o[80], c[80], h[80], l[80] = 9.6, 9.7, 9.95, 9.5      # the test touch (high >= p - tol)
    o[79], c[79], h[79], l[79] = 8.5, 9.5, 9.6, 8.4
    for k in range(81, n):
        o[k], c[k], h[k], l[k] = 8.0, 7.9, 8.1, 7.0        # reverses far below
    a = LR.atr(h, l, c)
    ts = np.arange(n) * 3600
    ev, tr = WL.level_rows((o, h, l, c), ts, a, np.zeros(n), 1)
    e = [x for x in ev if x["w"] == 70]
    assert e and e[0]["f"] == 80 and e[0]["held"] == 1.0 and e[0]["K"] == 1


def test_bar_rows_features_are_causal():
    w = _walk(2000, 3)
    old = WI.N_SAMPLE
    WI.N_SAMPLE = 10 ** 6
    try:
        S_full, *_ = WI.bar_rows(w, np.zeros(len(w)), "1h", 0)
        m = 1500
        S_cut, *_ = WI.bar_rows(w.iloc[:m].reset_index(drop=True), np.zeros(m), "1h", 0)
    finally:
        WI.N_SAMPLE = old
    a = S_full.set_index("t")
    b = S_cut.set_index("t")
    common = b.index.intersection(a.index)
    assert len(common) > 1000
    cols = [k for k in WI.FEATS + WI.VOL_BASE + WI.VOL_WICK + ["wi", "wbr", "h_wi"] if k in a.columns]
    for k in cols:
        x, y = a.loc[common, k].to_numpy(float), b.loc[common, k].to_numpy(float)
        same = (np.isclose(x, y, equal_nan=True))
        assert same.all(), (k, np.flatnonzero(~same)[:5])


def test_tick_fill_matches_bar_fill_on_a_smooth_path():
    rng = np.random.default_rng(4)
    sec, nb = 60, 400
    P = 1000 + np.cumsum(rng.normal(0, 0.05, sec * nb))
    ts = np.arange(nb, dtype=np.int64) * sec
    import rb100 as RBM
    b = RBM.bars_from_sec(P, 0, ts, sec)
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = LR.atr(h, l, c)
    tape = WL.Tape(0, P, 0.0)
    diffs = []
    for f in range(50, 300, 25):
        stop = o[f] - 1.0 * a[f - 1]
        Rb, *_ = WL.exits_e1(o, h, l, c, f, o[f], stop, a[f - 1], 0.0, hold=100)
        res = WL.tick_fill(tape, 1, ts, sec, h, c, f, "market", o[f], stop, a[f - 1], hold=100)
        assert res is not None
        diffs.append(abs(res[0] - (Rb + 0.0)))
    # the bar replay charges 0.05 ATR slippage on stops; otherwise they agree closely
    assert np.median(diffs) < 0.1


def test_htf_uses_completed_blocks_only():
    w = _walk(400, 2)
    a = LR.atr(*(w[k].to_numpy(float) for k in ("high", "low", "close")))
    F = WI.htf_feats(w, a, "1h")
    ts = w["ts"].to_numpy()
    # within a 4h block, the value is constant until the block's last bar closes
    blk = ts // 14400
    for t in range(20, 300):
        if (ts[t] + 3600) % 14400 != 0 and blk[t] == blk[t - 1]:
            assert np.isclose(F["h_ush"][t], F["h_ush"][t - 1], equal_nan=True)
