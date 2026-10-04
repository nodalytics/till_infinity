"""Checks for the geraked EA ports: indicators against hand-worked bars, the engines against cases whose
answer is known, and every EA firing both ways on a walk."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import geraked_eas as E  # noqa: E402
import geraked_ind as G  # noqa: E402
import geraked_sim as S  # noqa: E402


# ------------------------------------------------------------------------------- indicators by hand
def test_ema_is_seeded_with_the_first_price():
    assert np.allclose(G.ema([1.0, 2.0, 3.0], 3), [1.0, 1.5, 2.25])


def test_sma_and_population_bands():
    m, u, lo = G.bands([1.0, 2.0, 3.0, 4.0], 2, 2.0)
    assert np.isnan(m[0]) and np.allclose(m[1:], [1.5, 2.5, 3.5])
    assert np.allclose(u[1:] - m[1:], 2 * 0.5) and np.allclose(m[1:] - lo[1:], 1.0)


def test_rsi_metatrader_seed_and_wilder_step():
    r = G.rsi([1.0, 2.0, 3.0, 2.0], 2)
    assert np.isnan(r[1]) and r[2] == 100.0 and np.isclose(r[3], 50.0)
    assert G.rsi([1.0, 1.0, 1.0], 2)[2] == 50.0  # no move either way


def test_stochastic_with_slowing():
    h = np.array([2.0, 3.0, 4.0, 5.0])
    l = np.array([1.0, 1.0, 2.0, 3.0])
    c = np.array([1.5, 2.0, 3.0, 4.0])
    k, d = G.stochastic(h, l, c, 2, 2, 2)
    # bar 2: LL=1 HH=4 (c-LL=2, HH-LL=3); bar 3: LL=2 HH=5 (2, 3); slowing 2 -> 4/6
    assert np.isclose(k[3], 100 * 4 / 6)
    # bar 1: LL=1 HH=3 (1, 2); bar 2 -> (1+2)/(2+3)
    assert np.isclose(k[2], 100 * 3 / 5) and np.isclose(d[3], (k[2] + k[3]) / 2)


def test_momentum_and_macd():
    c = np.array([10.0, 11.0, 12.0, 13.2])
    assert np.isclose(G.momentum(c, 2)[3], 13.2 / 11.0 * 100)
    assert np.allclose(G.macd_main(c, 2, 2), 0.0)


def test_atr_is_a_simple_mean_of_true_range():
    h = np.array([2.0, 3.0, 2.5])
    l = np.array([1.0, 2.0, 0.5])
    c = np.array([1.5, 2.5, 1.0])
    tr = G.true_range(h, l, c)
    assert np.allclose(tr, [1.0, 1.5, 2.0])
    assert np.isclose(G.atr(h, l, c, 2)[2], 1.75)


def test_heiken_ashi_two_bars():
    o, h, l, c = (np.array(x) for x in ([1.0, 2.0], [3.0, 4.0], [0.5, 1.0], [2.0, 3.0]))
    ho, hh, hl, hc = G.heiken_ashi(o, h, l, c)
    assert ho[1] == 1.5 and hc[1] == 2.5 and hh[1] == 4.0 and hl[1] == 1.0


def test_lrma_and_zlsma_follow_a_straight_line_exactly():
    x = np.arange(100, dtype=float) * 0.5 + 3
    assert np.allclose(G.lrma(x, 11)[10:], x[10:])
    assert np.allclose(G.zlsma(x, 14)[30:], x[30:])


def test_andean_flat_market_and_one_hand_step():
    # MQL seeds Dn1/Dn2 at zero, so a flat market starts with a transient that decays away
    bull, bear, sig = G.andean(np.full(60, 5.0), np.full(60, 5.0), 3, 2)
    assert bull[-1] < 1e-3 and np.allclose(bear[1:], 0) and np.all(np.diff(bull[1:]) <= 0)
    o, c = np.array([1.0, 1.0, 2.0]), np.array([1.0, 2.0, 1.0])
    bull, bear, _ = G.andean(o, c, 3, 2)
    a = 0.5
    u1 = max(2.0, 0 - (0 - 2.0) * a)  # bar 1: up1 = max(max(c, o), ...)
    u2 = max(4.0, 0 - (0 - 4.0) * a)
    d1 = min(1.0, 0 + (2.0 - 0) * a)
    d2 = min(1.0, 0 + (4.0 - 0) * a)
    assert np.isclose(bear[1], np.sqrt(max(u2 - u1 * u1, 0)))
    assert np.isclose(bull[1], np.sqrt(max(d2 - d1 * d1, 0)))


def test_average_force_by_hand():
    h = np.array([2.0, 3.0, 4.0])
    l = np.array([1.0, 1.0, 2.0])
    c = np.array([1.5, 3.0, 2.0])
    af = G.average_force(h, l, c, 2, 1)
    assert np.isclose(af[1], (3.0 - 1.0) / 2.0 - 0.5) and np.isclose(af[2], (2.0 - 1.0) / 3.0 - 0.5)


def test_atr_sl_finder():
    h = np.array([2.0, 3.0])
    l = np.array([1.0, 2.0])
    c = np.array([1.5, 2.5])
    up, dn = G.atr_sl_finder(h, l, c, 2, 2.0)
    assert np.isclose(up[1], 3.0 + 2 * 1.25) and np.isclose(dn[1], 2.0 - 2 * 1.25)


def test_utbot_flags_a_cross():
    c = np.array([10.0, 10.0, 10.0, 11.0, 12.0, 9.0, 8.0, 7.5, 9.5, 11.0])
    h, l = c + 0.5, c - 0.5
    bull, bear, line = G.utbot(h, l, c, 1.0, 1)
    assert np.flatnonzero(bear).tolist() == [5] and np.flatnonzero(bull).tolist() == [8]
    assert c[5] < line[5] and c[4] >= line[4] and np.isclose(bear[5], h[5] + (h[4] - l[4]))
    assert c[8] > line[8] and c[7] <= line[7] and np.isclose(bull[8], l[8] - (h[7] - l[7]))


def test_chandelier_flips_on_heiken_ashi_closes():
    # with ATR period 1 it flips on a bar that outruns the last one's HA range, not on a steady trend
    c = np.r_[np.linspace(10, 5, 20), 9.0, 9.2]
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) + 0.1, np.minimum(o, c) - 0.1
    buy, sell, hc = G.chandelier_exit(o, h, l, c, 1, 0.75)
    assert np.flatnonzero(buy).tolist() == [20] and np.flatnonzero(sell).tolist() == [1]
    ho, hh, hl, hc2 = G.heiken_ashi(o, h, l, c)
    tr19 = max(hh[19], hc2[18]) - min(hl[19], hc2[18])
    ls1 = hc2[20] - 0.75 * (max(hh[20], hc2[19]) - min(hl[20], hc2[19]))
    ls2 = hc2[19] - 0.75 * tr19
    assert hc2[20] > hc2[19] + 0.75 * tr19
    assert np.isclose(buy[20], max(ls1, ls2) if hc2[19] > ls2 else ls1)


def test_nadaraya_watson_on_a_constant_is_flat():
    up, dn = G.nadaraya_watson(np.full(1200, 7.0), 8.0, 3.0, 500)
    assert np.allclose(up[1000:], 7.0) and np.allclose(dn[1000:], 7.0)


def test_fractals():
    h = np.array([1, 2, 5, 3, 2, 1], float)
    l = -h
    up, dn = G.fractals(h, l)
    assert up[2] == 5 and np.isnan(up[3]) and dn[2] == -5


def test_previous_day_high_low():
    ts = np.array([0, 3600, 86400, 90000, 172800])
    h = np.array([5.0, 6.0, 7.0, 4.0, 1.0])
    l = np.array([1.0, 2.0, 3.0, 0.5, 0.2])
    ph, pl = G.prev_day_hl(ts, h, l)
    assert np.isnan(ph[0]) and ph[2] == 6.0 and pl[3] == 1.0 and ph[4] == 7.0 and pl[4] == 0.5


# ------------------------------------------------------------------------------- engines
def test_path_order():
    V = S.path([1.0, 2.0], [3.0, 3.0], [0.0, 1.0], [2.0, 1.5])
    assert list(V) == [1.0, 0.0, 3.0, 2.0, 2.0, 3.0, 1.0, 1.5]


def _bars(rows):
    o, h, l, c = (np.array(x, float) for x in zip(*rows))
    return S.path(o, h, l, c)


def test_trade_hits_target_then_stop_and_trails():
    V = _bars([(10, 10, 10, 10), (10, 10.5, 9.8, 10.4), (10.4, 11.2, 10.3, 11.0)])
    k, fill, why, mfe, mae = S.run_trade(V, 1, 1, 9.0, 11.0, 1.0, 0.0, 0.001)
    assert why == "tp" and fill == 11.0
    V = _bars([(10, 10, 10, 10), (10, 10.2, 8.5, 9.0)])
    assert S.run_trade(V, 1, 1, 9.0, 11.0, 1.0, 0.0, 0.001)[1:3] == (9.0, "sl")
    # the trail: up 0.8 (trail at entry + 0.8 - 0.5), then back down: out at 10.3
    V = _bars([(10, 10, 10, 10), (10, 10.8, 10.0, 10.7), (10.7, 10.7, 10.0, 10.1)])
    k, fill, why, *_ = S.run_trade(V, 1, 1, 9.0, None, 1.0, 0.5, 0.001)
    assert why == "trail" and np.isclose(fill, 10.3)
    # a short is the same trade upside down
    Vs = _bars([(10, 10, 10, 10), (10, 10.2, 8.9, 9.0)])
    assert S.run_trade(Vs, -1, 1, 11.0, 9.0, 1.0, 0.0, 0.001)[1:3] == (-9.0, "tp")  # side frame


def test_gap_through_a_stop_fills_at_the_open():
    V = _bars([(10, 10, 10, 10), (10, 10.1, 9.9, 10.0), (8.0, 8.5, 7.9, 8.2)])
    assert S.run_trade(V, 1, 1, 9.0, None, 1.0, 0.0, 0.001)[1:3] == (8.0, "sl")


def test_first_passage_on_a_walk_is_one_over_n_plus_one():
    rng = np.random.default_rng(3)
    n = 60_000
    x = 1000 + np.cumsum(rng.normal(0, 1, n * 16))
    seg = x.reshape(n, 16)
    o = np.r_[1000.0, seg[:-1, -1]]
    V = S.path(o, np.maximum(seg.max(1), o), np.minimum(seg.min(1), o), seg[:, -1])
    hits = []
    for e in range(100, n - 5000, 40):
        side = 1 if e % 80 else -1
        hits.append(S.first_passage(V, side, e, V[4 * e] - side * 6.0, (1, 4)))
    p = np.mean(hits, 0)
    assert abs(p[0] - 0.5) < 0.04 and abs(p[1] - 0.2) < 0.04


def test_grid_adds_levels_and_takes_back_the_first_risk():
    spec = S.Spec(point=0.001, vpu=1000.0, vol_min=0.01, vol_step=0.01)
    # down two pd (two adds), then up through the grid target
    V = _bars([(10, 10, 10, 10), (10, 10, 7.9, 8.0), (8.0, 9.6, 8.0, 9.5)])
    cfg = S.GridCfg(risk=0.01, trail=False, mult=1.0, max_lvl=5)
    res = S.grid_cycle(V, 1, 1, 9.0, None, 1.0, cfg, spec, 10_000.0, 0.0)
    assert res["lvl"] == 3 and res["why"] == "tp"
    assert np.isclose(res["bal"] - 10_000.0, 0.1 * 1000 * 1.0, atol=1e-6)  # one pd on the first lot: +1% back
    assert res["worst"] < 10_000 - 0.1 * 1000 * (2 + 1 - 0.1)


def test_grid_stop_out_on_a_long_fall():
    spec = S.Spec(point=0.001, vpu=100_000.0, vol_min=0.01, vol_step=0.01)
    V = _bars([(1.0, 1.0, 1.0, 1.0)] + [(1.0 - 0.01 * i, 1.0 - 0.01 * i, 0.99 - 0.01 * i, 0.99 - 0.01 * i)
                                        for i in range(60)])
    cfg = S.GridCfg(risk=0.01, trail=False, mult=1.5, max_lvl=20)
    res = S.grid_cycle(V, 1, 1, 0.99, None, 0.01, cfg, spec, 10_000.0, 0.0)
    assert res["stopout"] and res["bal"] < 5_000


def test_martingale_doubles_after_a_loss():
    spec = S.Spec(point=0.001, vpu=1.0, vol_min=0.001, vol_step=0.001, vol_max=1e9)
    tr = dict(R=np.array([-1.0, 1.0]), r0=np.array([1.0, 1.0]), tpd=np.array([1.0, 1.0]),
              mae=np.array([1.0, 0.0]), px=np.array([100.0, 100.0]))
    eq, lo, fr = S.account(tr, spec, mart=True, mart_risk=0.04)
    assert np.isclose(eq[0], 9_900) and np.isclose(eq[1], 9_900 + 200)


# ------------------------------------------------------------------------------- the EAs
def _walk_bars(n=6000, seed=1):
    rng = np.random.default_rng(seed)
    x = np.log(1.2) + np.cumsum(rng.normal(0, 0.002, n * 8))
    seg = np.exp(x).reshape(n, 8)
    o = np.r_[1.2, seg[:-1, -1]]
    h, l = np.maximum(seg.max(1), o), np.minimum(seg.min(1), o)
    ts = 1_600_000_000 + np.arange(n) * 3600
    return E.Bars(o, h, l, seg[:, -1], ts, 1e-5)


@pytest.mark.parametrize("ea", E.BAR_EAS)
def test_every_ea_fires_both_ways_with_valid_orders(ea):
    b = _walk_bars()
    sig = E.SIGNALS[ea](b)
    od = E.orders(sig, b, E.META[ea], E.META[ea].reverse)
    assert (od["side"] > 0).sum() > 0 and (od["side"] < 0).sum() > 0, ea
    k = od["side"] != 0
    s = od["side"][k]
    assert np.all(s * (od["entry"][k] - od["sl"][k]) > 0)


def test_reverse_swaps_stop_and_target():
    b = _walk_bars()
    sig = E.SIGNALS["3MACD"](b)
    a = E.orders(sig, b, E.META["3MACD"], False)
    r = E.orders(sig, b, E.META["3MACD"], True)
    k = np.flatnonzero(a["side"] != 0)[0]
    assert r["side"][k] == -a["side"][k] and r["sl"][k] == a["tp"][k] and r["tp"][k] == a["sl"][k]


def test_cot_week_picks_pairs_that_exist():
    import pandas as pd
    rows = []
    for cur, (l, s_, cl, cs) in {"EUR": (80, 20, 5, 1), "JPY": (10, 90, -3, 2), "GBP": (70, 30, 2, 1),
                                  "USD": (20, 80, 0, 4), "AUD": (60, 40, 1, 0), "CAD": (50, 50, 0, 0),
                                  "CHF": (40, 60, 0, 1), "NZD": (30, 70, 0, 0)}.items():
        rows.append(dict(cur=cur, date=pd.Timestamp("2024-01-02"), dl=l, ds=s_, dcl=cl, dcs=cs, ll=l, ls=s_,
                         lcl=cl, lcs=cs))
    tab = pd.DataFrame(rows)
    sig = E.cot_week(tab, pd.Timestamp("2024-01-08"))
    assert ("EURJPY", 1) in sig and ("EURUSD", 1) in sig and ("GBPJPY", 1) in sig
    assert E.cot_week(tab, pd.Timestamp("2024-01-15")) == []  # a week without a report trades nothing
