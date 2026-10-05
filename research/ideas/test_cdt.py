"""Tests for cdt.py on synthetic bars only (no market data): state arrays, the trade engine by hand,
the regime's knowable time, the v1 parse against turn_trade.ups, and a walk's barrier odds."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import cdt as C  # noqa: E402


def bars(o, h, l, c, step=86400):
    n = len(o)
    return pd.DataFrame({"ts": np.arange(n, dtype=np.int64) * step + 1_600_000_000 // step * step,
                         "open": o, "high": h, "low": l, "close": c, "volume": np.ones(n)})


def test_next_false_and_windows():
    cond = np.array([1, 1, 0, 1, 1, 1, 0, 0, 1], bool)
    assert C.next_false(cond).tolist() == [2, 2, 2, 6, 6, 6, 6, 7, 9]
    ent = np.zeros(9, bool)
    ent[3] = True
    on = C.windows(ent, C.next_false(cond), 9)
    assert on.tolist() == [0, 0, 0, 1, 1, 1, 0, 0, 0]
    on = C.windows(ent, C.next_false(cond), 9, cap=2)
    assert on.tolist() == [0, 0, 0, 1, 1, 0, 0, 0, 0]


def _flat(n=20, px=100.0):
    o = np.full(n, px)
    return o.copy(), o + 1, o - 1, o.copy()


def test_trade_stop_and_state():
    o, h, l, c = _flat()
    df = bars(o, h, l, c)
    A = C.Arr(df, 1)
    t, a = 5, 2.0
    # stop = min(low t-2..t) - 0.1 a = 99 - 0.2 = 98.8; entry 100; risk 1.2 (>= 0.25 a)
    off = np.full(20, 20)
    off[:10] = 9  # the first off bar at or after k is 9 -> out at bar 10's open
    R, mfe, risk, entry, last, px, stopped, cost = C.trade(A, t, a, 0.0, off, None, "STATE")
    assert abs(risk - 1.2) < 1e-12 and not stopped and last == 9 and px == 100.0 and abs(R) < 1e-12
    # a crash on bar 8 through the stop: the gap fills at the open, less slippage
    o2, h2, l2, c2 = o.copy(), h.copy(), l.copy(), c.copy()
    o2[8], l2[8] = 97.0, 96.0
    A = C.Arr(bars(o2, h2, l2, c2), 1)
    R, mfe, risk, entry, last, px, stopped, cost = C.trade(A, t, a, 0.0, off, None, "STATE")
    assert stopped and last == 8 and abs(px - (97.0 - C.SLIP * a)) < 1e-12
    assert abs(R - (97.0 - 0.1 - 100.0) / 1.2) < 1e-12
    # the barrier: highs of 101 before the stop -> (101 - 100) / 1.2
    assert abs(mfe - 1 / 1.2) < 1e-12


def test_trade_trail_and_short_mirror():
    n = 40
    c = np.r_[np.full(10, 100.0), 100 + np.arange(1, 16) * 2.0, 130 - np.arange(1, 16) * 3.0]
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) + 0.5, np.minimum(o, c) - 0.5
    df = bars(o, h, l, c)
    A = C.Arr(df, 1)
    off = np.full(n, n)
    R, mfe, risk, entry, last, px, stopped, cost = C.trade(A, 9, 1.0, 0.0, off, None, "TRAIL")
    assert stopped and R > 10  # rode the rally, out on the way down
    # the same trade as a short on the mirrored chart gives the same R
    m = bars(-o, -l, -h, -c)
    B = C.Arr(m, -1)
    R2, *_ = C.trade(B, 9, 1.0, 0.0, off, None, "TRAIL")
    assert abs(R - R2) < 1e-9


def test_regime_knowable_time():
    d = bars(*[np.r_[np.full(200, 100.0), np.full(5, 200.0)]] * 4)  # BTC jumps above its SMA on day 200
    ts4 = d["ts"].iat[200] + np.arange(6) * 14400  # the six 4h bars of day 200
    up, _ = C.regime(d, ts4, 14400)
    # only the last 4h bar closes at day 200's close; the earlier ones see day 199 (flat, not above)
    assert up[1].tolist() == [False] * 5 + [True]
    up1, _ = C.regime(d, d["ts"].to_numpy()[198:202], 86400)
    assert up1[1].tolist() == [False, False, True, True]


def test_ups_v1_matches_turn_trade():
    import geraked_eas as GE
    import turn_trade as TT
    base = pd.DataFrame({"ts": np.arange(800, dtype=np.int64) * 14400 + 1_600_000_000,
                         "close": np.full(800, 100.0)})
    w = GE.make_walk(base.assign(close=100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.02, 800)))), "iid", 5)
    w["volume"] = 1.0
    dc, dsd = C.ups_v1(w)
    U = TT.ups(w, both=True)
    assert (dc == U["DISPLACE_C"]).all() and (dsd == U["DELIVERY_SHIFT_DOWN"]).all()


def test_walk_barrier_is_one_over_n_plus_1():
    import geraked_eas as GE
    n = 6000
    base = pd.DataFrame({"ts": np.arange(n, dtype=np.int64) * 86400, "close": np.full(n, 100.0)})
    base["close"] = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.03, n)))
    w = GE.make_walk(base, "iid", 9)
    from mcfl import candles
    a = candles._atr(w)
    A = C.Arr(w, 1)
    f = np.arange(300, n - C.HOLD - 2, 3)
    entry = A.O[f]
    risk = 1.0 * a[f - 1]
    p = C.barrier(A, f, entry, entry - risk, risk)
    # P(4R before -1R) on a log walk at 1 ATR risk: close to 1/5, a bar touching both counts as stopped
    assert 0.15 < (p >= 4).mean() < 0.23, (p >= 4).mean()


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
