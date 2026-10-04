"""The 13 Expert Advisors of github.com/geraked/metatrader5, ported to Python and backtested three ways.

Source: github.com/geraked/metatrader5, MIT licence, Copyright 2023-2024 Geraked (Rabist). Each EA's
entry rule, stop, target, close rule and default inputs are re-expressed from `Experts/<EA>.mq5`; the
indicators are in `geraked_ind.py`, the order/grid/risk layer of `Include/EAUtils.mqh` in
`geraked_sim.py`. Frozen in `geraked_rule.json` before any real-data run.

  Mode S  the signal with its own coded SL/TP and trail, one position: R, P(N R) vs 1/(N+1),
          against iid and GARCH walks, a coin twin and the reversed signal (primary)
  Mode G  the author's defaults: the grid without stops, an account in money, real vs walks
  Mode R  the risk layer one factor at a time on Mode S's signals

  OUT=... MT5BT_DB=... MODE=run|report|plot python research/ideas/geraked_eas.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import geraked_ind as G  # noqa: E402
import geraked_sim as S  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/geraked"))
BIN = Path(os.environ.get("BINANCE", os.path.expanduser("~/till_infinity/data/binance")))
SEQLAB = Path(os.environ.get("SEQLAB", os.path.expanduser("~/till_infinity/data/seqlab")))
COT_CSV = Path(os.environ.get("COT_TFF", os.path.expanduser("~/till_infinity/geraked/data/tff.csv.gz")))
SEC = {"5m": 300, "15m": 900, "1h": 3600, "2h": 7200, "3h": 10800, "4h": 14400, "1d": 86400}
TFS = ("15m", "1h", "4h", "1d")
NS = (0.5, 1, 2, 4, 10)
WALK_STEPS = 256
SPLIT = pd.Timestamp("2024-01-01", tz="UTC").timestamp()
COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")
FEE = 0.0007
STOCK_FEE = 0.0005
EAS = ("2MAAOS", "2MACDSTO", "2MOMEMA", "3MACD", "3MAF", "AFAOSMD", "BBRSI", "CEZLSMA", "COT1",
       "DHLAOS", "LRCMACD", "LRCUTB", "NWERSIASF")
BAR_EAS = tuple(e for e in EAS if e != "COT1")


# ----------------------------------------------------------------------------------- the EAs' inputs
@dataclass
class Meta:
    """Each EA's default inputs that the engines read."""
    risk: float
    ignore_sl: bool
    ignore_tp: bool
    trail: bool
    grid: bool
    mult: float
    grid_trail: float
    max_lvl: int
    reverse: bool = False
    close_orders: bool = False
    close_on_profit: bool = True
    min_interval: int = 0
    tpcoef: float = 1.0
    sl_lookback: int = 10
    sl_dev: int = 60
    trail_lvl: float = 0.5
    single_symbol: bool = True


META = {
    "2MAAOS": Meta(5.5, False, True, True, True, 1.3, 0.0, 20, min_interval=6, sl_lookback=10, sl_dev=100,
                   single_symbol=False),
    "2MACDSTO": Meta(2.25, True, True, True, True, 1.0, 0.0, 50, sl_lookback=7, sl_dev=60),
    "2MOMEMA": Meta(1.0, False, False, False, False, 1.0, 0.0, 50, sl_lookback=10, sl_dev=60),
    "3MACD": Meta(0.5, True, True, True, True, 1.0, 0.0, 50, reverse=True, tpcoef=2.0, sl_lookback=7, sl_dev=60),
    "3MAF": Meta(1.0, True, True, True, True, 1.5, 0.4, 20, tpcoef=1.5),
    "AFAOSMD": Meta(1.0, False, True, True, True, 1.1, 0.0, 20, reverse=True, sl_lookback=7, sl_dev=60),
    "BBRSI": Meta(1.0, True, True, True, True, 1.1, 0.0, 20),
    "CEZLSMA": Meta(3.0, True, True, True, True, 1.5, 0.0, 50, close_orders=True, sl_dev=650),
    "COT1": Meta(3.5, False, True, True, True, 1.2, 0.0, 20, tpcoef=2.0, sl_lookback=6, sl_dev=30,
                 single_symbol=False),
    "DHLAOS": Meta(0.5, True, True, True, True, 1.1, 0.2, 50, tpcoef=1.5, sl_lookback=7, sl_dev=60),
    "LRCMACD": Meta(1.0, False, True, True, True, 1.5, 0.0, 20, sl_lookback=10, sl_dev=60, single_symbol=False),
    "LRCUTB": Meta(0.6, False, True, True, True, 1.2, 0.0, 50, sl_lookback=10, sl_dev=100),
    "NWERSIASF": Meta(1.2, False, True, True, True, 1.1, 0.0, 20, tpcoef=1.5, min_interval=4,
                      single_symbol=False),
}


@dataclass
class Bars:
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    ts: np.ndarray
    point: float
    day_ts: np.ndarray | None = None
    min_stop: float = 0.0  # the broker's stops level, in price
    min_frac: float = 0.0  # or a fraction of the price where there is no broker spec
    on: np.ndarray = field(init=False)  # the next bar's open: the price an order at bar t's close gets

    def __post_init__(self):
        self.on = np.r_[self.o[1:], np.nan]


def _sh(x, k=1):
    """x shifted k bars later: _sh(x)[t] = x[t-1]."""
    x = np.asarray(x)
    out = np.empty(len(x), dtype=float if x.dtype.kind == "f" else x.dtype)
    if x.dtype.kind == "f":
        out[:k] = np.nan
    else:
        out[:k] = False
    out[k:] = x[:-k] if k else x
    return out


def swing(b: Bars, lookback, dev, start, buy):
    """BuySL/SellSL with SL_SWING: the lowest low (highest high) of `lookback` bars from `start`; start 0
    takes in the forming bar, which on its first tick is just its open."""
    x = b.l if buy else b.h
    f = G.rmin if buy else G.rmax
    if start == 1:
        ext = f(x, lookback)
    else:
        ext = f(x, lookback - 1) if lookback > 1 else np.full(len(x), np.nan)
        ext = np.fmin(ext, b.on) if buy else np.fmax(ext, b.on)
    return ext - dev * b.point if buy else ext + dev * b.point


def sl_by_type(b: Bars, kind, lookback, dev, start, buy):
    """The four ENUM_SL stop types of BuySL/SellSL, for the entry at the next open."""
    s = 1 if buy else -1
    if kind == "swing":
        return swing(b, lookback, dev, start, buy)
    rng_ = b.h - b.l
    if start == 0:  # the forming bar's range on its first tick is 0
        tot = G.sma(rng_, lookback - 1) * (lookback - 1) if lookback > 1 else np.zeros(len(rng_))
        mx = G.rmax(rng_, lookback - 1) if lookback > 1 else np.zeros(len(rng_))
        avg, mx = tot / lookback, np.fmax(mx, 0.0)
    else:
        avg, mx = G.sma(rng_, lookback), G.rmax(rng_, lookback)
    if kind == "ar":
        return b.on - s * (avg + dev * b.point)
    if kind == "mr":
        return b.on - s * (mx + dev * b.point)
    if kind == "fixed":
        return b.on - s * dev * b.point
    raise ValueError(kind)


def _out(buy, sell, slb, sls, tpcoef, extra=None, tp=True, cl=None, cs=None, ind=None, slkind="swing"):
    """Signals for bars t (entry at t+1's open). Buy beats sell (`if (BuySignal()) return;`)."""
    buy = np.asarray(buy, bool) & np.isfinite(slb)
    sell = np.asarray(sell, bool) & ~np.asarray(buy, bool)
    return dict(buy=buy, sell=sell & np.isfinite(sls), sl_buy=slb, sl_sell=sls, tpcoef=tpcoef if tp else 0.0,
                close_long=cl, close_short=cs, ind=ind or {}, slkind=slkind, **(extra or {}))


def ea_2MAAOS(b: Bars):
    bull, bear, sg = G.andean(b.o, b.c, 50, 9)
    f, s_ = G.sma(b.c, 50), G.sma(b.c, 200)
    diff = np.abs(f - s_)
    bc = (_sh(bull) <= _sh(sg)) & (bull > sg) & (bull > bear) & (f > s_) & (b.on > f - 0.5 * diff)
    sc = (_sh(bear) <= _sh(sg)) & (bear > sg) & (bull < bear) & (f < s_) & (b.on < f + 0.5 * diff)
    return _out(bc, sc, swing(b, 10, 100, 0, True), swing(b, 10, 100, 0, False), 1.0,
                ind=dict(ma50=f, ma200=s_, bull=bull, bear=bear, signal=sg))


def ea_2MACDSTO(b: Bars):
    m1, m2 = G.macd_main(b.c, 13, 21), G.macd_main(b.c, 34, 144)
    k, d = G.stochastic(b.h, b.l, b.c, 7, 3, 3)
    bc = (_sh(m2) > 0) & (_sh(m1) < 0) & (_sh(k) < 20) & (_sh(k) <= _sh(d)) & (k > d)
    sc = (_sh(m2) < 0) & (_sh(m1) > 0) & (_sh(k) > 80) & (_sh(k) >= _sh(d)) & (k < d)
    return _out(bc, sc, swing(b, 7, 60, 1, True), swing(b, 7, 60, 1, False), 1.0,
                ind=dict(macd1=m1, macd2=m2, stoch=k, stoch_sig=d))


def ea_2MOMEMA(b: Bars):
    fm, sm = G.momentum(b.c, 10), G.momentum(b.c, 34)
    fe, se = G.ema(b.c, 10), G.ema(b.c, 34)
    upk, dnk = (sm > 100) & (fe > se), (sm < 100) & (fe < se)
    allup = G.rmin(upk.astype(float), 9) == 1
    alldn = G.rmin(dnk.astype(float), 9) == 1
    bc = (fm > 100) & (_sh(fm) <= 100) & allup
    sc = (fm < 100) & (_sh(fm) >= 100) & alldn
    return _out(bc, sc, swing(b, 10, 60, 1, True), swing(b, 10, 60, 1, False), 1.0,
                ind=dict(ema10=fe, ema34=se, mom10=fm, mom34=sm))


def _3macd_side(m1, m2, m3, t, s, buff=32):
    """3MACD's buffer scan for one side at bar t (s = +1 buy, -1 sell); series index i is bar t+1-i."""
    def M(a, i):
        return s * a[t + 1 - i]
    if M(m3, 1) > 0 and M(m2, 1) > 0 and M(m2, 2) > 0 and M(m2, 3) > 0 and M(m2, 1) > M(m2, 2) and M(m2, 2) < M(m2, 3):
        j = 0
        for i in range(2, buff - 1):
            if M(m3, i) <= 0 or M(m3, i + 1) <= 0:
                return False
            if M(m2, i) <= 0 or M(m2, i + 1) <= 0:
                return False
            if M(m1, i) < 0 and M(m1, i + 1) > 0:
                j = i + 1
                break
        if j == 0:
            return False
        for i in range(j, buff - 2):
            if M(m3, i) <= 0 or M(m3, i + 1) <= 0 or M(m3, i + 2) <= 0:
                return False
            if M(m2, i) <= 0 or M(m2, i + 1) <= 0 or M(m2, i + 2) <= 0:
                return False
            if M(m2, i) < M(m2, i + 1) and M(m2, i + 1) > M(m2, i + 2):
                return True
        return False
    if M(m3, 1) > 0 and M(m3, 2) > 0 and M(m3, 3) > 0 and M(m3, 1) > M(m3, 2) and M(m3, 2) < M(m3, 3):
        j = 0
        for i in range(2, buff - 1):
            if M(m3, i) <= 0 or M(m3, i + 1) <= 0:
                return False
            if M(m2, i) < 0 and M(m2, i + 1) > 0:
                j = i + 1
                break
        if j == 0:
            return False
        k = 0
        for i in range(j, buff - 1):
            if M(m3, i) <= 0 or M(m3, i + 1) <= 0:
                return False
            if M(m2, i) <= 0 or M(m2, i + 1) <= 0:
                return False
            if M(m1, i) < 0 and M(m1, i + 1) > 0:
                k = i + 1
                break
        if k == 0:
            return False
        for i in range(k, buff - 2):
            if M(m3, i) <= 0 or M(m3, i + 1) <= 0 or M(m3, i + 2) <= 0:
                return False
            if M(m2, i) <= 0 or M(m2, i + 1) <= 0 or M(m2, i + 2) <= 0:
                return False
            if M(m2, i) < M(m2, i + 1) and M(m2, i + 1) > M(m2, i + 2):
                return True
        return False
    return False


def ea_3MACD(b: Bars):
    m1, m2, m3 = G.macd_main(b.c, 5, 8), G.macd_main(b.c, 13, 21), G.macd_main(b.c, 34, 144)
    n = len(b.c)
    bc, sc = np.zeros(n, bool), np.zeros(n, bool)
    for s, out in ((1, bc), (-1, sc)):
        a1, a2, a3 = s * m1, s * m2, s * m3
        p1 = (a3 > 0) & (a2 > 0) & (_sh(a2) > 0) & (_sh(a2, 2) > 0) & (a2 > _sh(a2)) & (_sh(a2) < _sh(a2, 2))
        p2 = (a3 > 0) & (_sh(a3) > 0) & (_sh(a3, 2) > 0) & (a3 > _sh(a3)) & (_sh(a3) < _sh(a3, 2))
        for t in np.flatnonzero(p1 | p2):
            if 200 <= t < n - 1:
                out[t] = _3macd_side(m1, m2, m3, t, s)
    return _out(bc, sc, swing(b, 7, 60, 1, True), swing(b, 7, 60, 1, False), 2.0,
                ind=dict(macd1=m1, macd2=m2, macd3=m3))


def ea_3MAF(b: Bars):
    m1, m2, m3 = G.ema(b.c, 60), G.ema(b.c, 350), G.ema(b.c, 600)
    # iFractals at buffer 2 (bar t-1) on the new bar's first tick: the later bars are t and the
    # forming bar's open
    lf = (_sh(b.l) < b.l) & (_sh(b.l) < b.on) & (_sh(b.l) <= _sh(b.l, 2)) & (_sh(b.l) <= _sh(b.l, 3))
    uf = (_sh(b.h) > b.h) & (_sh(b.h) > b.on) & (_sh(b.h) >= _sh(b.h, 2)) & (_sh(b.h) >= _sh(b.h, 3))
    bc = (m1 > m2) & (m2 > m3) & (b.l > m3) & (b.l < m1) & lf
    sc = (m3 > m2) & (m2 > m1) & (b.h < m3) & (b.h > m1) & uf
    slb = np.where(b.l > m2, m2, m3)
    sls = np.where(b.h < m2, m2, m3)
    minsl = 100 * b.point
    bc &= np.abs(b.on - slb) >= minsl
    sc &= np.abs(b.on - sls) >= minsl
    bc[:600], sc[:600] = False, False
    return _out(bc, sc, slb, sls, 1.5, ind=dict(ema60=m1, ema350=m2, ema600=m3), slkind="ma")


def ea_AFAOSMD(b: Bars):
    af = G.average_force(b.h, b.l, b.c, 20, 9)
    bull, bear, _ = G.andean(b.o, b.c, 50, 9)
    md = G.macd_main(b.c, 100, 200)
    bc = (bull > bear) & (_sh(af) < 0) & (af > 0) & (_sh(md) > 0) & (md > 0) & (_sh(md) < md)
    sc = (bull < bear) & (_sh(af) > 0) & (af < 0) & (_sh(md) < 0) & (md < 0) & (_sh(md) > md)
    return _out(bc, sc, swing(b, 7, 60, 1, True), swing(b, 7, 60, 1, False), 1.0,
                ind=dict(af=af, bull=bull, bear=bear, macd=md))


def ea_BBRSI(b: Bars):
    m, u, lo = G.bands(b.c, 500, 2.0)
    r = G.rsi(b.c, 7)
    bc = (_sh(r) < 30) & (_sh(b.c) < _sh(lo)) & (r > 30) & (b.c > lo) & (r < 50) & (b.c < m)
    sc = (_sh(r) > 70) & (_sh(b.c) > _sh(u)) & (r < 70) & (b.c < u) & (r > 50) & (b.c > m)
    slb = lo - 0.9 * (m - lo)
    sls = u + 0.9 * (u - m)
    cl = (_sh(b.c) <= _sh(m)) & (b.c > m)
    cs = (_sh(b.c) >= _sh(m)) & (b.c < m)
    return _out(bc, sc, slb, sls, 1.0, cl=cl, cs=cs, ind=dict(bb_mid=m, bb_up=u, bb_lo=lo, rsi=r), slkind="bands")


def ea_CEZLSMA(b: Bars):
    ceb, ces, hc = G.chandelier_exit(b.o, b.h, b.l, b.c, 1, 0.75)
    zl = G.zlsma(hc, 50)
    bc = (ceb != 0) & (hc > zl)
    sc = (ces != 0) & (hc < zl)
    slb = np.where(ceb != 0, ceb - 650 * b.point, np.nan)
    sls = np.where(ces != 0, ces + 650 * b.point, np.nan)
    cl = (_sh(hc) >= _sh(zl)) & (hc < zl)
    cs = (_sh(hc) <= _sh(zl)) & (hc > zl)
    bc[:120], sc[:120] = False, False
    return _out(bc, sc, slb, sls, 0.0, tp=False, cl=cl, cs=cs, ind=dict(zlsma=zl, ha_close=hc, ce_buy=ceb, ce_sell=ces),
                slkind="chandelier")


def _dhl_side(bull, bear, sg, hi_or_lo, dhl, t, s, on, ncheck=300, dcheck=50):
    """DHLAOS's scan for one side at bar t; series index i is bar t+1-i, i = 0 the forming bar."""
    B, R = (bull, bear) if s > 0 else (bear, bull)

    def at(a, i):
        return a[t + 1 - i] if i >= 1 else a[t]
    j = 0
    for i in range(3, ncheck):
        if t + 1 - (i + 1) < 0:
            return False
        if s > 0:
            if at(bull, i + 1) >= at(bear, i + 1) and at(bull, i) < at(bear, i):
                return False
        else:
            if at(bull, i + 1) <= at(bear, i + 1) and at(bull, i) > at(bear, i):
                return False
        if at(B, i + 1) >= at(sg, i + 1) and at(B, i) < at(sg, i):
            return False
        if at(B, i + 1) <= at(sg, i + 1) and at(B, i) > at(sg, i):
            return False
        if s > 0:
            if at(bull, i + 1) <= at(bear, i + 1) and at(bull, i) > at(bear, i):
                j = i
                break
        else:
            if at(bull, i + 1) >= at(bear, i + 1) and at(bull, i) < at(bear, i):
                j = i
                break
    for i in range(j, j + dcheck):
        if t + 1 - i < 0:
            break
        x = on[t] if i == 0 else hi_or_lo[t + 1 - i]
        lvl = dhl[min(t + 1, len(dhl) - 1)] if i == 0 else dhl[t + 1 - i]
        if s > 0 and x < lvl and at(bull, i) < at(bear, i):
            return True
        if s < 0 and x > lvl and at(bull, i) > at(bear, i):
            return True
    return False


def ea_DHLAOS(b: Bars):
    bull, bear, sg = G.andean(b.o, b.c, 50, 9)
    ph, pl = G.prev_day_hl(b.ts, b.h, b.l, b.day_ts)
    n = len(b.c)
    bc, sc = np.zeros(n, bool), np.zeros(n, bool)
    cb = (_sh(bull) <= _sh(sg)) & (bull > sg)
    cs_ = (_sh(bear) <= _sh(sg)) & (bear > sg)
    for t in np.flatnonzero(cb):
        if 400 <= t < n - 1:
            bc[t] = _dhl_side(bull, bear, sg, b.h, pl, t, 1, b.on)
    for t in np.flatnonzero(cs_ & ~bc):
        if 400 <= t < n - 1:
            sc[t] = _dhl_side(bull, bear, sg, b.l, ph, t, -1, b.on)
    return _out(bc, sc, swing(b, 7, 60, 1, True), swing(b, 7, 60, 1, False), 1.5,
                ind=dict(bull=bull, bear=bear, signal=sg, prev_high=ph, prev_low=pl))


def _lrcmacd_side(lc, lo, md, t, s, pb=4):
    def L(i):
        return s * (lc[t + 1 - i] - lo[t + 1 - i])  # > 0: an up candle on this side
    def Mi(i):
        return s * md[t + 1 - i]
    j = 0
    for i in range(2, pb + 2):
        if Mi(i) <= 0:
            return False
        if L(i) < 0:
            j = i
            break
    if not j:
        return False
    for i in range(j, j + pb):
        if Mi(i) <= 0:
            return False
        if L(i) > 0:
            return False
    return True


def ea_LRCMACD(b: Bars):
    lo, _, _, lc, ls = G.lrc(b.o, b.h, b.l, b.c, 11, 5)
    md = G.macd_main(b.c, 34, 144)
    n = len(b.c)
    pre_b = (md > 0) & (_sh(md) > 0) & (lc > lo) & (lc > ls) & (_sh(lc) <= _sh(ls)) & (_sh(lc) > _sh(lo))
    pre_s = (md < 0) & (_sh(md) < 0) & (lc < lo) & (lc < ls) & (_sh(lc) >= _sh(ls)) & (_sh(lc) < _sh(lo))
    bc, sc = np.zeros(n, bool), np.zeros(n, bool)
    for t in np.flatnonzero(pre_b):
        if 200 <= t < n - 1:
            bc[t] = _lrcmacd_side(lc, lo, md, t, 1)
    for t in np.flatnonzero(pre_s):
        if 200 <= t < n - 1:
            sc[t] = _lrcmacd_side(lc, lo, md, t, -1)
    return _out(bc, sc, swing(b, 10, 60, 0, True), swing(b, 10, 60, 0, False), 1.0,
                ind=dict(lrc_open=lo, lrc_close=lc, lrc_signal=ls, macd=md))


def ea_LRCUTB(b: Bars):
    lo, _, _, lc, ls = G.lrc(b.o, b.h, b.l, b.c, 11, 7)
    ub, ur, _ = G.utbot(b.h, b.l, b.c, 2.0, 1)
    anyb = (ub != 0) | (_sh(ub, 1) != 0) | (_sh(ub, 2) != 0)
    anys = (ur != 0) | (_sh(ur, 1) != 0) | (_sh(ur, 2) != 0)
    bc = (lc > lo) & (lc > ls) & anyb
    sc = (lc < lo) & (lc < ls) & anys
    cl = (_sh(lc) > _sh(lo)) & (lc < lo)
    cs = (_sh(lc) < _sh(lo)) & (lc > lo)
    bc[:30], sc[:30] = False, False
    return _out(bc, sc, swing(b, 10, 100, 0, True), swing(b, 10, 100, 0, False), 1.0, cl=cl, cs=cs,
                ind=dict(lrc_open=lo, lrc_close=lc, lrc_signal=ls, utb_bull=ub, utb_bear=ur))


def ea_NWERSIASF(b: Bars):
    up, dn = G.nadaraya_watson(b.c, 8.0, 3.0, 500)
    r = G.rsi(b.c, 5)
    au, ad = G.atr_sl_finder(b.h, b.l, b.c, 14, 0.75)
    half = 0.5 * (up - dn)
    bc = (_sh(b.l) < _sh(dn)) & (b.c > b.o) & (b.on < dn + half) & (_sh(r) < 30)
    sc = (_sh(b.h) > _sh(up)) & (b.c < b.o) & (b.on > up - half) & (_sh(r) > 70)
    return _out(bc, sc, ad, au, 1.5, ind=dict(nwe_up=up, nwe_dn=dn, rsi=r, asf_up=au, asf_dn=ad), slkind="asf")


SIGNALS = {name: globals()[f"ea_{name}"] for name in BAR_EAS}


# ----------------------------------------------------------------------------------- orders
def orders(sig, b: Bars, meta: Meta, reverse: bool):
    """Every bar's order as the EA would send it: side, entry, sl, tp (nan = none), the trail's unit pd,
    and the risk distance r0 = |entry - sl| of the order actually placed. Invalid orders (stop or target
    on the wrong side of the price; order() refuses them) are dropped."""
    n = len(b.c)
    side = np.where(sig["buy"], 1, np.where(sig["sell"], -1, 0))
    entry = b.on
    sl = np.where(side > 0, sig["sl_buy"], sig["sl_sell"])
    d = np.abs(entry - sl)
    tpc = sig["tpcoef"]
    tp = np.where(tpc > 0, entry + side * tpc * d, np.nan)
    pd_ = d.copy()
    if reverse:
        if tpc > 0:
            sl, tp = tp, sl
        else:  # no coded TP: the reversed order would carry no stop; mirror it at the same distance
            sl = entry + side * d
            tp = np.full(n, np.nan)
        side = -side
    ok = (side != 0) & np.isfinite(entry) & np.isfinite(sl) & (d > 0)
    ok &= np.where(side > 0, sl < entry, sl > entry)
    # a stop inside the broker's stops level is refused (TRADE_RETCODE_INVALID_STOPS)
    ok &= np.abs(entry - sl) >= np.maximum(b.min_stop, b.min_frac * np.abs(entry))
    ok &= np.where(np.isfinite(tp), np.where(side > 0, tp > entry, tp < entry), True)
    return dict(side=np.where(ok, side, 0), entry=entry, sl=sl, tp=tp, pd=pd_, r0=np.abs(entry - sl),
                any_signal=(sig["buy"] | sig["sell"]))


def close_vertices(sig, n, side):
    """The close rule as a per-vertex mask at the next bar's open."""
    key = "close_long" if side > 0 else "close_short"
    cl = sig.get(key)
    if cl is None:
        return None
    m = np.zeros(4 * n, bool)
    idx = np.flatnonzero(np.asarray(cl, bool)[:-1]) + 1
    m[4 * idx] = True
    return m


@dataclass
class Cfg:
    """Mode S/R's trade settings."""
    trail_lvl: float
    close_orders: bool
    gated: bool
    min_interval: int
    multi: bool = False


def simulate(V, b: Bars, od, sig, cfg: Cfg, cost_px, atr_, entries=None, sides=None, fp=True):
    """Mode S: one position at a time (or overlapping with `multi`), each order through run_trade.
    `entries`/`sides` replay given entry bars (the coin twin). Returns a frame of trades."""
    n = len(b.c)
    cls = {s: close_vertices(sig, n, s) if cfg.close_orders else None for s in (1, -1)}
    rows = []
    free_k, last_e = 0, -10 ** 9
    if entries is None:
        cand = np.flatnonzero(od["side"] != 0)
        cand = cand[cand < n - 1]
        anysig = np.flatnonzero(od["any_signal"])
    else:
        cand = np.asarray(entries)
    for q, t in enumerate(cand):
        e = t + 1
        if entries is None and not cfg.multi:
            if 4 * e < free_k:
                continue
            if cfg.min_interval and e - last_e < cfg.min_interval:
                continue
        if sides is None:
            s = int(od["side"][t])
            sl, tp = od["sl"][t], od["tp"][t]
        else:
            s = int(sides[q])
            r0 = od["r0"][t]
            tpd = abs(od["tp"][t] - od["entry"][t]) if np.isfinite(od["tp"][t]) else np.nan
            sl = od["entry"][t] - s * r0
            tp = od["entry"][t] + s * tpd if np.isfinite(tpd) else np.nan
        pin = b.on[t]
        r0 = abs(pin - sl)
        if not (r0 > 0):
            continue
        kx, fill, why, mfe, mae = S.run_trade(V, s, e, sl, None if not np.isfinite(tp) else tp, od["pd"][t],
                                              cfg.trail_lvl, b.point, cls[s], cfg.gated)
        slip = S.SLIP * atr_[t] if why in ("sl", "trail") else 0.0
        R = (fill - s * pin - slip) / r0 - cost_px[t] / r0
        row = dict(t=int(t), e=int(e), side=s, ts=int(b.ts[t]), R=R, why=why, r0=r0,
                   tpd=abs(tp - pin) if np.isfinite(tp) else 0.0, mfe=mfe / r0, mae=mae, px=pin,
                   kx=int(kx), bars=int(kx // 4 - e))
        if fp:
            hit = S.first_passage(V, s, e, sl, NS)
            row.update({f"P{N}": bool(h) for N, h in zip(NS, hit)})
        rows.append(row)
        free_k, last_e = kx, e
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------- data
FAMILY_CLASS = {"fx": "fx", "metal": "metal", "index": "index", "energy": "energy", "crypto": "crypto_cfd"}
JUMPY = ("Boom 1000 Index", "Crash 1000 Index", "Jump 50 Index")
RANGE_BREAK = "Range Break 100 Index"


def asset_class(venue, sym):
    if venue == "binance":
        return "binance"
    if venue == "stock":
        return "stock"
    import run as R
    fam = R.FAMILY.get(sym)
    if fam == "deriv":
        if sym == RANGE_BREAK:
            return "range_break"
        return "deriv_jumpy" if sym in JUMPY else "deriv_diffusive"
    return FAMILY_CLASS.get(fam, fam)


def stock_tickers():
    files = sorted(p.name for p in SEQLAB.glob("*.1d.npz") if p.name.count(".") == 3
                   and p.name.split(".")[1] in ("N", "OQ"))
    tick = sorted({".".join(f.split(".")[:2]) for f in files})
    rng = np.random.default_rng(7)
    return sorted(rng.choice(tick, size=min(50, len(tick)), replace=False).tolist())


def _resample(df, sec):
    """Coarser bars from finer ones, on UTC multiples of `sec` (2h and 3h from the broker's 1h)."""
    g = ((df["ts"] // sec) * sec).rename("ts")
    a = df.groupby(g).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                          close=("close", "last"), spread=("spread", "median"))
    return a.reset_index()


def load(venue, sym, iv):
    """Bars, the cost a trade pays (price, per bar), point, the spec, the broker's D1 opens, spreads."""
    if venue == "binance":
        try:
            z = np.load(BIN / f"{sym}USDT.klines.{iv}.npz")
        except OSError:
            return None
        df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close")}).rename(columns={"time": "ts"})
        df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        df["ts"] = df["ts"].astype(np.int64)
        if df["ts"].iloc[-1] > 1e11:
            df["ts"] //= 1000
        cpx = FEE * df["close"].to_numpy(float)
        point = _tick(df["close"].to_numpy(float))
        spec = S.Spec(point=point, vpu=1.0, vol_min=0.001, vol_step=0.001, vol_max=1e6)
        return dict(df=df, cost=cpx, point=point, spec=spec, day_ts=None, spread=None, min_stop=0.0, min_frac=1e-4)
    if venue == "stock":
        f = SEQLAB / f"{sym}.{iv}.npz"
        if not f.exists():
            return None
        z = np.load(f)
        df = pd.DataFrame({k: z[k] for k in ("open", "high", "low", "close")})
        df.insert(0, "ts", z["time"].astype(np.int64))
        df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        specs = json.load(open(SEQLAB.parent / "stock_specs.json"))
        sp = specs.get(sym, {})
        point = float(sp.get("point", 0.01))
        cs = float(sp.get("trade_contract_size", 1.0))
        spec = S.Spec(point=point, vpu=cs, vol_min=float(sp.get("volume_min", 1.0)),
                      vol_step=float(sp.get("volume_min", 1.0)), vol_max=1e6)
        return dict(df=df, cost=STOCK_FEE * df["close"].to_numpy(float), point=point, spec=spec, day_ts=None,
                    spread=None, min_stop=0.0, min_frac=1e-4)
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    base = {"2h": "1h", "3h": "1h"}.get(iv, iv)
    df = R.load(sym, base)
    if df is None:
        return None
    df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "spread"]]
    if base != iv:
        df = _resample(df, SEC[iv])
    spec0 = load_specs(R.DB).get(sym)
    if spec0 is None:
        return None
    floor = R.spread_floor(sym, spec0)
    if not floor > 0:
        floor = float(np.nanmedian(df["spread"].to_numpy(float)))
    cpx = np.full(len(df), floor * spec0.point)
    d1 = R.load(sym, "1d")
    spec = S.Spec(point=spec0.point, vpu=spec0.tick_value / spec0.tick_size, vol_min=spec0.volume_min,
                  vol_step=spec0.volume_step, vol_max=spec0.volume_max)
    stops = max(float(getattr(spec0, "stops_level", 0) or 0), 10.0) * spec0.point
    return dict(df=df, cost=cpx, point=spec0.point, spec=spec, day_ts=None if d1 is None else d1["ts"].to_numpy(),
                spread=df["spread"].to_numpy(float), floor_pts=floor, min_stop=stops, min_frac=0.0)


def _tick(x):
    d = np.abs(np.diff(np.unique(np.round(x[-5000:], 10))))
    d = d[d > 0]
    if not len(d):
        return 1e-8
    m = float(d.min())
    return float(10 ** np.floor(np.log10(m) + 1e-9))


def make_walk(df, kind, seed, steps=WALK_STEPS):
    """A walk in log price matched to the series' sigma (iid or GARCH(1,1) a=0.08 b=0.9), `steps`
    sub-steps a bar, from the real first price, on the real timestamps. Built in chunks."""
    c = df["close"].to_numpy(float)
    lr = np.diff(np.log(c))
    sigma = float(np.std(lr[np.isfinite(lr)]))
    n = len(df)
    rng = np.random.default_rng(seed)
    if kind == "garch":
        a, bt = 0.08, 0.9
        om = sigma ** 2 * (1 - a - bt)
        var, rp = sigma ** 2, 0.0
        vols = np.empty(n)
        z = rng.standard_normal(n)
        for i in range(n):
            var = om + a * rp * rp + bt * var
            vols[i] = np.sqrt(var)
            rp = z[i] * vols[i]
    else:
        vols = np.full(n, sigma)
    o, h, l, cl = (np.empty(n) for _ in range(4))
    x0 = np.log(c[0])
    for s0 in range(0, n, 4096):
        s1 = min(n, s0 + 4096)
        inc = rng.standard_normal((s1 - s0, steps)) * (vols[s0:s1] / np.sqrt(steps))[:, None]
        p = x0 + np.cumsum(inc.ravel()).reshape(inc.shape)  # one path through the chunk's bars
        o[s0:s1] = np.r_[x0, p[:-1, -1]]
        h[s0:s1] = np.maximum(p.max(1), o[s0:s1])
        l[s0:s1] = np.minimum(p.min(1), o[s0:s1])
        cl[s0:s1] = p[:, -1]
        x0 = p[-1, -1]
    w = pd.DataFrame({"ts": df["ts"].to_numpy(), "open": np.exp(o), "high": np.exp(h), "low": np.exp(l),
                      "close": np.exp(cl)})
    if "spread" in df:
        w["spread"] = df["spread"].to_numpy()
    return w


# ----------------------------------------------------------------------------------- Mode G
def grid_flags(m: Meta):
    """IgnoreSL/IgnoreTP as the order actually carries them: the grid forces IgnoreSL on, and Reverse
    swaps the two (order(SELL, ..., tp, sl, ..., itp, isl))."""
    isl, itp = (m.ignore_sl or m.grid), m.ignore_tp
    if m.reverse:
        isl, itp = m.ignore_tp, (True if m.grid else m.ignore_sl)
    return isl, itp


def mode_g(V, b: Bars, od, sig, m: Meta, spec, cost, risk, eq_limit=0.0, start=10_000.0):
    """The author's defaults as an account: every signal while flat opens an order and its grid."""
    isl, itp = grid_flags(m)
    cfg = S.GridCfg(risk=risk, ignore_sl=isl, ignore_tp=itp, trail=m.trail, trail_lvl=m.trail_lvl, grid=m.grid,
                    mult=m.mult, grid_trail=m.grid_trail, max_lvl=m.max_lvl, eq_limit=eq_limit)
    n = len(b.c)
    cls = {s: close_vertices(sig, n, s) if m.close_orders else None for s in (1, -1)}
    eq = np.full(n, np.nan)
    eq[0] = start
    bal, free_k, last_e = start, 0, -10 ** 9
    cyc = []
    first_so, ruin_t, peak = None, None, start
    worst_dd = 0.0
    for t in np.flatnonzero(od["side"] != 0):
        e = t + 1
        if e >= n or 4 * e < free_k:
            continue
        if m.min_interval and e - last_e < m.min_interval:
            continue
        s = int(od["side"][t])
        tp = od["tp"][t]
        res = S.grid_cycle(V, s, e, od["sl"][t], None if not np.isfinite(tp) else tp, od["pd"][t], cfg, spec, bal,
                           cost[t], cls[s])
        if res is None:
            continue
        idx, val = S.book_equity(V, s, res["segs"], res["k"])
        eq[idx] = val
        jx = min(n - 1, res["k"] // 4)
        peak = max(peak, np.nanmax(eq[:e + 1]) if np.isfinite(eq[:e + 1]).any() else peak)
        worst_dd = max(worst_dd, (peak - res["worst"]) / peak if peak > 0 else 0.0)
        bal = res["bal"]
        eq[jx] = bal
        cyc.append(dict(t=int(t), e=int(e), kx=int(res["k"]), lvl=res["lvl"], why=res["why"], bal=bal,
                        worst=res["worst"]))
        if res["stopout"] and first_so is None:
            first_so = (b.ts[jx] - b.ts[0]) / 86400
        free_k, last_e = res["k"], e
        if bal <= 0.1 * start:
            ruin_t = (b.ts[jx] - b.ts[0]) / 86400
            eq[jx:] = bal
            break
    eq = pd.Series(eq).ffill().to_numpy()
    years = max((b.ts[-1] - b.ts[0]) / 86400 / 365.25, 1e-9)
    fin = eq[-1]
    cagr = (fin / start) ** (1 / years) - 1 if fin > 0 else -1.0
    pk = np.maximum.accumulate(eq)
    mdd = float(np.nanmax((pk - eq) / pk))
    c = pd.DataFrame(cyc)
    maxed = float((c["lvl"] >= m.max_lvl).mean()) if len(c) and m.grid else np.nan
    return dict(cagr=cagr, final=fin, mdd=mdd, worst_open_dd=max(worst_dd, mdd), first_stopout_days=first_so,
                ruin_days=ruin_t, cycles=len(c), maxed=maxed, mean_lvl=float(c["lvl"].mean()) if len(c) else np.nan,
                stopouts=int((c["why"] == "stopout").sum()) if len(c) else 0, years=years), eq


# ----------------------------------------------------------------------------------- Mode R
def acct_metrics(eq_after, eq_low, ts_span_years, start=10_000.0):
    fin = eq_after[-1] if len(eq_after) else start
    cagr = (fin / start) ** (1 / max(ts_span_years, 1e-9)) - 1 if fin > 0 else -1.0
    return dict(cagr=cagr, final=fin, mdd=S.max_dd(eq_after, start), worst_open_dd=S.worst_open_dd(eq_after, eq_low, start))


def account_overlap(tr, spec, risk=0.01, start=10_000.0, margin_limit=3.0, lev=100.0):
    """Overlapping positions (MultipleOpenPos): sized on balance at entry, realised at exit, a new one
    refused while balance / margin in use is under MarginLimit."""
    ev = sorted([(r.e * 4, 0, i) for i, r in enumerate(tr.itertuples())] +
                [(r.kx, -1, i) for i, r in enumerate(tr.itertuples())])
    bal, used, live = start, 0.0, {}
    eq_after, eq_low, frac = [], [], []
    R, r0, px, mae = (tr[k].to_numpy(float) for k in ("R", "r0", "px", "mae"))
    for k, kind, i in ev:
        if kind == 0:
            vol = S.norm_vol(bal * risk / (r0[i] * spec.vpu), spec)
            mg = vol * spec.vpu * abs(px[i]) / lev
            if used > 0 and bal / (used + mg) < margin_limit:
                continue
            live[i] = (vol, mg, bal)
            used += mg
        elif i in live:
            vol, mg, b0 = live.pop(i)
            used -= mg
            pnl = vol * spec.vpu * r0[i] * R[i]
            eq_low.append(bal - vol * spec.vpu * mae[i])
            frac.append(pnl / bal if bal > 0 else 0.0)
            bal = max(bal + pnl, 0.0)
            eq_after.append(bal)
    return np.array(eq_after), np.array(eq_low), np.array(frac)


def summarise(tr, name, extra=None):
    if tr is None or not len(tr):
        return dict(config=name, n=0, **(extra or {}))
    r = dict(config=name, n=len(tr), R=float(tr["R"].mean()), R_sd=float(tr["R"].std()),
             win=float((tr["R"] > 0).mean()), **{f"P{N}": float(tr[f"P{N}"].mean()) for N in NS if f"P{N}" in tr})
    r.update(extra or {})
    return r


def mode_r(V, b: Bars, sig, m: Meta, base_tr, spec, cost, atr_, spread, g_base, g_eq20, rng):
    """Each factor of the risk layer swapped alone on this EA's signals. Returns (summaries, samples)."""
    years = max((b.ts[-1] - b.ts[0]) / 86400 / 365.25, 1e-9)
    out, samples = [], {}
    cfg0 = Cfg(trail_lvl=m.trail_lvl if m.trail else 0.0, close_orders=m.close_orders, gated=m.close_on_profit,
               min_interval=m.min_interval)

    def acct(tr, name, **kw):
        if tr is None or not len(tr):
            out.append(summarise(tr, name))
            return
        ea_, lo_, fr_ = S.account({k: tr[k].to_numpy(float) for k in ("R", "r0", "tpd", "mae", "px")}, spec, **kw)
        out.append(summarise(tr, name, acct_metrics(ea_, lo_, years)))
        keep = rng.choice(len(fr_), min(200, len(fr_)), replace=False)
        samples[name] = fr_[np.sort(keep)].astype(np.float32)

    od0 = orders(sig, b, m, m.reverse)
    # path factors: the stop type, the trail, overlapping positions
    for kind in ("swing", "ar", "mr", "fixed"):
        s2 = dict(sig)
        s2["sl_buy"] = sl_by_type(b, kind, m.sl_lookback, m.sl_dev, 1, True)
        s2["sl_sell"] = sl_by_type(b, kind, m.sl_lookback, m.sl_dev, 1, False)
        tr = simulate(V, b, orders(s2, b, m, m.reverse), s2, cfg0, cost, atr_)
        acct(tr, f"sl_{kind}")
    for lv in (0.0, 0.25, 0.5, 0.75):
        if (lv == cfg0.trail_lvl):
            tr = base_tr
        else:
            tr = simulate(V, b, od0, sig, Cfg(lv, cfg0.close_orders, cfg0.gated, cfg0.min_interval), cost, atr_)
        acct(tr, f"trail_{int(lv * 100)}")
    # account factors on the base trades
    acct(base_tr, "base")
    acct(base_tr, "size_equity")
    if len(base_tr):
        v0 = S.norm_vol(10_000 * 0.01 / (base_tr["r0"].iloc[0] * spec.vpu), spec)
        acct(base_tr, "size_fixed", mode="fixed", fixed_vol=v0)
        acct(base_tr, "size_min_amount", mode="min_amount", min_amount=10_000 * spec.vol_step / v0)
    acct(base_tr, "martingale", mart=True)
    acct(base_tr, "eq_limit5", eq_limit=0.05)
    if spread is not None and len(base_tr):
        med = np.nanmedian(spread)
        keep = spread[base_tr["t"].to_numpy()] <= 2 * med if med > 0 else np.ones(len(base_tr), bool)
        acct(base_tr[keep].reset_index(drop=True), "spread_limit")
    if m.single_symbol:
        trm = simulate(V, b, od0, sig, Cfg(cfg0.trail_lvl, cfg0.close_orders, cfg0.gated, cfg0.min_interval, multi=True),
                       cost, atr_)
        if len(trm):
            ea_, lo_, fr_ = account_overlap(trm, spec)
            out.append(summarise(trm, "multi_open", acct_metrics(ea_, lo_, years) if len(ea_) else {}))
            if len(fr_):
                samples["multi_open"] = fr_[np.sort(rng.choice(len(fr_), min(200, len(fr_)), replace=False))].astype(np.float32)
    for name, g in (("grid", g_base), ("grid_eq20", g_eq20)):
        if g is not None:
            out.append(dict(config=name, n=g["cycles"], cagr=g["cagr"], final=g["final"], mdd=g["mdd"],
                            worst_open_dd=g["worst_open_dd"], ruin=g["ruin_days"] is not None,
                            stopout=g["first_stopout_days"] is not None))
    if len(base_tr):
        samples["base_Rtp"] = np.c_[base_tr["R"].to_numpy(), np.where(base_tr["tpd"] > 0, base_tr["tpd"] / base_tr["r0"], 0)
                                    ][np.sort(rng.choice(len(base_tr), min(300, len(base_tr)), replace=False))].astype(np.float32)
    return out, samples


# ----------------------------------------------------------------------------------- one series
AUTHOR = {  # (EA, symbol, interval): the author's own Test/ cells that this broker carries
    ("2MAAOS", "EURUSD", "4h"), ("2MAAOS", "USDCAD", "4h"), ("2MACDSTO", "NZDUSD", "3h"), ("3MACD", "AUDUSD", "5m"),
    ("3MAF", "USDCAD", "15m"), ("BBRSI", "XAUUSD", "5m"), ("CEZLSMA", "AUDUSD", "15m"), ("DHLAOS", "AUDUSD", "5m"),
    ("NWERSIASF", "USDCAD", "2h"), ("NWERSIASF", "AUDUSD", "2h"),
}
CURVE_CELLS = {("mt5", "XAUUSD", "1h"), ("mt5", "EURUSD", "1h"), ("mt5", "US SP 500", "1h"), ("binance", "BTC", "4h")}


def one(job):
    venue, sym, iv, source, eas, with_r = job
    t0 = time.time()
    d = load(venue, sym, iv)
    if d is None or len(d["df"]) < 800:
        return None
    df = d["df"]
    real_atr = G.atr(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), 14)
    cost_atr = d["cost"] / np.where(real_atr > 0, real_atr, np.nan)
    med = float(np.nanmedian(cost_atr))
    cls_ = asset_class(venue, sym)
    meta_row = dict(venue=venue, sym=sym, iv=iv, src=source, cls=cls_, bars=len(df), cost_atr=med,
                    t0=int(df["ts"].iloc[0]), t1=int(df["ts"].iloc[-1]))
    if med > 0.5:
        return dict(meta=dict(meta_row, dropped=True))
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, med)
    if source != "real":
        seed = zlib.crc32(f"{venue}|{sym}|{iv}|{source}".encode()) % (2 ** 31)
        df = make_walk(df, source, seed)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr_ = G.atr(h, l, c, 14)
    atr_ = np.where(np.isfinite(atr_), atr_, np.nanmedian(atr_))
    cost = cost_atr * atr_ if source != "real" else d["cost"]
    b = Bars(o, h, l, c, df["ts"].to_numpy(np.int64), d["point"], d["day_ts"], d.get("min_stop", 0.0),
             d.get("min_frac", 0.0))
    V = S.path(o, h, l, c)
    spec = d["spec"]
    spread = d["spread"]
    rng = np.random.default_rng(zlib.crc32(f"{venue}{sym}{iv}{source}".encode()))
    trades, gsum, rsum, rsamp, curves = [], [], [], {}, {}
    for ea in eas:
        m = META[ea]
        sig = SIGNALS[ea](b)
        od = orders(sig, b, m, m.reverse)
        cfg = Cfg(trail_lvl=m.trail_lvl if m.trail else 0.0, close_orders=m.close_orders, gated=m.close_on_profit,
                  min_interval=m.min_interval)
        tS = simulate(V, b, od, sig, cfg, cost, atr_)
        kinds = [("S", tS)]
        if source == "real" and len(tS):
            sides = np.where(np.random.default_rng(zlib.crc32(f"coin{sym}{iv}{ea}".encode())).random(len(tS)) < 0.5, 1, -1)
            kinds.append(("coin", simulate(V, b, od, sig, cfg, cost, atr_, entries=tS["t"].to_numpy(), sides=sides)))
            kinds.append(("rev", simulate(V, b, orders(sig, b, m, not m.reverse), sig, cfg, cost, atr_)))
        for k, tr in kinds:
            if len(tr):
                tr = tr.assign(kind=k, ea=ea)
                trades.append(tr)
        g1, eq1 = mode_g(V, b, od, sig, m, spec, cost, 0.01)
        gsum.append(dict(ea=ea, risk=0.01, eq_limit=0.0, **g1))
        if (ea, sym, iv) in AUTHOR or (venue, sym, iv) in CURVE_CELLS:
            curves[(ea, 0.01)] = _daily(b.ts, eq1)
        if (ea, sym, iv) in AUTHOR and abs(m.risk - 1.0) > 1e-9:
            ga, eqa = mode_g(V, b, od, sig, m, spec, cost, m.risk / 100)
            gsum.append(dict(ea=ea, risk=m.risk / 100, eq_limit=0.0, **ga))
            curves[(ea, m.risk / 100)] = _daily(b.ts, eqa)
        if with_r:
            g20, _ = mode_g(V, b, od, sig, m, spec, cost, 0.01, eq_limit=0.2)
            gsum.append(dict(ea=ea, risk=0.01, eq_limit=0.2, **g20))
            rs, smp = mode_r(V, b, sig, m, tS, spec, cost, atr_, spread, g1, g20, rng)
            for r in rs:
                r["ea"] = ea
            rsum += rs
            for k, v in smp.items():
                rsamp[(ea, k)] = v
    tr = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    for k, v in meta_row.items():
        if k not in ("bars", "cost_atr", "t0", "t1"):
            tr[k] = v
    print(f"  {venue} {source} {sym} {iv}: {len(tr)} trades {time.time() - t0:.0f}s", flush=True)
    return dict(meta=meta_row, trades=_compact(tr), g=pd.DataFrame(gsum).assign(**{k: v for k, v in meta_row.items()}),
                r=pd.DataFrame(rsum).assign(**{k: v for k, v in meta_row.items()}), rsamp=rsamp, curves=curves)


def _daily(ts, eq):
    s = pd.Series(eq, index=pd.to_datetime(ts, unit="s"))
    return s.resample("1D").last().dropna().astype(np.float32)


def _compact(tr):
    if not len(tr):
        return tr
    for c_ in ("R", "r0", "tpd", "mfe", "mae", "px"):
        tr[c_] = tr[c_].astype(np.float32)
    for c_ in ("why", "kind", "ea", "venue", "sym", "iv", "src", "cls"):
        if c_ in tr:
            tr[c_] = tr[c_].astype("category")
    return tr


# ----------------------------------------------------------------------------------- COT1
CUR = {"232741": "AUD", "099741": "EUR", "096742": "GBP", "112741": "NZD", "090741": "CAD", "092741": "CHF",
       "097741": "JPY", "098662": "USD"}
FX12 = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
        "AUDJPY", "USDCNH")


def fetch_cot():
    """CFTC Traders in Financial Futures, futures only, for the eight currencies COT1 reads."""
    import io
    import urllib.request
    import zipfile
    urls = ["https://www.cftc.gov/files/dea/history/fin_fut_txt_2006_2016.zip"] + \
        [f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{y}.zip" for y in range(2017, 2027)]
    frames = []
    for u in urls:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        blob = urllib.request.urlopen(req, timeout=120).read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            d = pd.read_csv(z.open(z.namelist()[0]), low_memory=False, dtype={"CFTC_Contract_Market_Code": str})
        cols = {c.lower(): c for c in d.columns}

        def col(key):
            return d[cols[key.lower()]]
        code = col("CFTC_Contract_Market_Code").astype(str).str.strip().str.zfill(6)
        keep = code.isin(CUR)
        f = pd.DataFrame({
            "code": code[keep], "cur": code[keep].map(CUR),
            "date": pd.to_datetime(col("Report_Date_as_YYYY-MM-DD")[keep]).dt.strftime("%Y-%m-%d"),
            "dl": col("Dealer_Positions_Long_All")[keep], "ds": col("Dealer_Positions_Short_All")[keep],
            "dcl": col("Change_in_Dealer_Long_All")[keep], "dcs": col("Change_in_Dealer_Short_All")[keep],
            "ll": col("Lev_Money_Positions_Long_All")[keep], "ls": col("Lev_Money_Positions_Short_All")[keep],
            "lcl": col("Change_in_Lev_Money_Long_All")[keep], "lcs": col("Change_in_Lev_Money_Short_All")[keep]})
        frames.append(f)
        print(u, len(f), flush=True)
    out = pd.concat(frames).drop_duplicates(["code", "date"]).sort_values(["date", "cur"])
    COT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(COT_CSV, index=False)
    print(f"tff: {len(out)} rows {out['date'].min()} .. {out['date'].max()}", flush=True)


def cot_week(tab, monday):
    """COT1's FetchSignals for one week: the report dated in [Monday, Thursday) of the week before, per
    class (Dealer, then Leveraged Funds): the two currencies with a positive net change and the highest
    long share against the two with a negative net change and the highest short share; their pairs
    that exist here, buy green/red or sell red/green."""
    to = monday - pd.Timedelta(days=4)  # last Sunday - 3 days = Thursday
    fr = to - pd.Timedelta(days=3)
    w = tab[(tab["date"] >= fr) & (tab["date"] < to)]
    if w.empty:
        return []
    w = w[w["date"] == w["date"].max()]
    sigs = []
    for lc, sc, lch, sch in (("dl", "ds", "dcl", "dcs"), ("ll", "ls", "lcl", "lcs")):
        x = w.assign(lp=(w[lc] * 100.0 / (w[lc] + w[sc])).round(2), sp=(w[sc] * 100.0 / (w[lc] + w[sc])).round(2),
                     cnp=w[lch] - w[sch])
        g = x[x["cnp"] > 0].sort_values("lp", ascending=False, kind="stable").head(2)
        r = x[x["cnp"] < 0].sort_values("sp", ascending=False, kind="stable").head(2)
        for gc in g["cur"]:
            for rc in r["cur"]:
                if gc + rc in FX12:
                    sigs.append((gc + rc, 1))
                elif rc + gc in FX12:
                    sigs.append((rc + gc, -1))
    return sigs


def _cot_sl(b: Bars, e, buy, day_ts):
    """SL_AR on D1, lookback 6, start 0, dev 30: the mean range of today so far and the five days before."""
    day = np.searchsorted(day_ts, b.ts, side="right") - 1
    de = day[e]
    i0 = np.searchsorted(day, de)
    part = (b.h[i0:e].max() - b.l[i0:e].min()) if e > i0 else 0.0
    rng_ = [part]
    j = i0
    for _ in range(5):
        if j <= 0:
            break
        dj = day[j - 1]
        k0 = np.searchsorted(day, dj)
        rng_.append(b.h[k0:j].max() - b.l[k0:j].min())
        j = k0
    avg = sum(rng_) / 6.0
    s = 1 if buy else -1
    return b.o[e] - s * (avg + 30 * b.point)


def run_cot(source):
    """COT1 on the 12 FX pairs' 15m bars: Mode S (with its coin and reversed twins on real) and Mode G."""
    if not COT_CSV.exists():
        print("COT1: no TFF data, skipped", flush=True)
        return None
    tab = pd.read_csv(COT_CSV)
    tab["date"] = pd.to_datetime(tab["date"])
    ser = {}
    for sym in FX12:
        d = load("mt5", sym, "15m")
        if d is None:
            continue
        df = d["df"]
        ra = G.atr(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), 14)
        ca = d["cost"] / np.where(ra > 0, ra, np.nan)
        ca = np.where(np.isfinite(ca), ca, np.nanmedian(ca))
        if source != "real":
            df = make_walk(df, source, zlib.crc32(f"mt5|{sym}|15m|{source}".encode()) % (2 ** 31))
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        a = G.atr(h, l, c, 14)
        a = np.where(np.isfinite(a), a, np.nanmedian(a))
        b = Bars(o, h, l, c, df["ts"].to_numpy(np.int64), d["point"], d["day_ts"])
        ser[sym] = dict(b=b, V=S.path(o, h, l, c), atr=a, cost=ca * a if source != "real" else d["cost"],
                        spec=d["spec"], pos={int(x): i for i, x in enumerate(b.ts)}, min_stop=d.get("min_stop", 0.0),
                        day_ts=d["day_ts"] if d["day_ts"] is not None else (b.ts // 86400) * 86400)
    times = np.unique(np.concatenate([s["b"].ts for s in ser.values()]))
    wd = pd.to_datetime(times, unit="s").weekday
    times = times[(wd == 0) | (wd == 1)]
    rows, gsum = [], []
    variants = [("S", False, None)] + ([("coin", False, 1), ("rev", True, None)] if source == "real" else [])
    rng = np.random.default_rng(zlib.crc32(b"coinCOT1"))
    week_cache = {}
    for kind, rev, coin in variants + [("G", False, None)]:
        free_ts, dealt, bal = -1, {}, 10_000.0
        cyc_eq = []
        for tau in times:
            if tau < free_ts:
                continue
            day = pd.Timestamp(tau, unit="s").normalize()
            monday = day - pd.Timedelta(days=day.weekday())
            wk = monday.value
            if wk not in week_cache:
                week_cache[wk] = cot_week(tab, monday)
            for sym, side in week_cache[wk]:
                if sym not in ser or dealt.get(sym) == wk:
                    continue
                s_ = ser[sym]
                e = s_["pos"].get(int(tau))
                if e is None or e < 200 or e >= len(s_["b"].c) - 1:
                    continue
                b = s_["b"]
                if coin:
                    side = 1 if rng.random() < 0.5 else -1
                sl = _cot_sl(b, e, side > 0, s_["day_ts"])
                pin = b.o[e]
                dd = abs(pin - sl)
                tp = pin + side * 2.0 * dd
                pd_ = dd
                if rev:
                    side, sl, tp = -side, tp, sl
                r0 = abs(pin - sl)
                if not r0 >= max(s_["min_stop"], 1e-12):
                    continue
                if kind == "G":
                    m = META["COT1"]
                    cfg = S.GridCfg(risk=0.01, ignore_sl=True, ignore_tp=True, trail=True, trail_lvl=0.5, grid=True,
                                    mult=m.mult, grid_trail=0.0, max_lvl=m.max_lvl)
                    res = S.grid_cycle(s_["V"], side, e, sl, tp, pd_, cfg, s_["spec"], bal, s_["cost"][e - 1])
                    if res is None:
                        continue
                    bal = res["bal"]
                    kx = res["k"]
                    cyc_eq.append(dict(ts=int(b.ts[min(kx // 4, len(b.ts) - 1)]), bal=bal, worst=res["worst"],
                                       lvl=res["lvl"], why=res["why"], sym=sym))
                else:
                    kx, fill, why, mfe, mae = S.run_trade(s_["V"], side, e, sl, tp, pd_, 0.5, b.point)
                    slip = S.SLIP * s_["atr"][e - 1] if why in ("sl", "trail") else 0.0
                    R = (fill - side * pin - slip) / r0 - s_["cost"][e - 1] / r0
                    hit = S.first_passage(s_["V"], side, e, sl, NS)
                    rows.append(dict(t=e - 1, e=e, side=side, ts=int(b.ts[e - 1]), R=R, why=why, r0=r0,
                                     tpd=abs(tp - pin), mfe=mfe / r0, mae=mae, px=pin, kx=int(kx),
                                     bars=int(kx // 4 - e), kind=kind, ea="COT1", sym=sym,
                                     **{f"P{N}": bool(x) for N, x in zip(NS, hit)}))
                dealt[sym] = wk
                free_ts = int(b.ts[min(kx // 4, len(b.ts) - 1)])
                break
            if kind == "G" and bal <= 1000:
                break
        if kind == "G" and cyc_eq:
            c_ = pd.DataFrame(cyc_eq)
            years = (times[-1] - times[0]) / 86400 / 365.25
            eqs = np.r_[10_000.0, c_["bal"].to_numpy()]
            pk = np.maximum.accumulate(eqs)
            gsum.append(dict(ea="COT1", risk=0.01, eq_limit=0.0, cagr=(eqs[-1] / 1e4) ** (1 / years) - 1 if eqs[-1] > 0 else -1,
                             final=eqs[-1], mdd=float(((pk - eqs) / pk).max()),
                             worst_open_dd=float(((pk[:-1] - c_["worst"].to_numpy()) / pk[:-1]).max()),
                             first_stopout_days=None if not (c_["why"] == "stopout").any() else
                             (c_.loc[c_["why"] == "stopout", "ts"].iloc[0] - times[0]) / 86400,
                             ruin_days=None if eqs[-1] > 1000 else (c_["ts"].iloc[-1] - times[0]) / 86400,
                             cycles=len(c_), maxed=float((c_["lvl"] >= META["COT1"].max_lvl).mean()),
                             mean_lvl=float(c_["lvl"].mean()), stopouts=int((c_["why"] == "stopout").sum()),
                             years=years))
    tr = pd.DataFrame(rows)
    if len(tr):
        tr = tr.assign(venue="mt5", iv="15m", src=source, cls="fx")
    g = pd.DataFrame(gsum).assign(venue="mt5", sym="FX12", iv="15m", src=source, cls="fx")
    print(f"  COT1 {source}: {len(tr)} trades", flush=True)
    return dict(meta=dict(venue="mt5", sym="FX12", iv="15m", src=source, cls="fx"), trades=_compact(tr), g=g,
                r=pd.DataFrame(), rsamp={}, curves={})


# ----------------------------------------------------------------------------------- the run
def jobs():
    import run as R
    with_r = os.environ.get("MODE_R", "1") == "1"
    srcs = ("real", "walk", "garch")
    js = []
    for src in srcs:
        for iv in TFS:
            js += [("mt5", s, iv, src, BAR_EAS, with_r) for s in R.FAMILY]
            js += [("binance", c_, iv, src, BAR_EAS, with_r) for c_ in COINS]
        for iv in ("1h", "1d"):
            js += [("stock", s, iv, src, BAR_EAS, with_r) for s in stock_tickers()]
        extra = {}
        for ea, sym, iv in AUTHOR:
            if iv not in TFS:
                extra.setdefault((sym, iv), []).append(ea)
        js += [("mt5", sym, iv, src, tuple(sorted(e)), False) for (sym, iv), e in sorted(extra.items())]
    only = os.environ.get("ONLY")
    if only:  # e.g. ONLY="mt5|EURUSD|1h|real" for a smoke test
        js = [j for j in js if "|".join(j[:4]) == only]
    return js


def _key(job):
    return zlib.crc32("|".join(map(str, job[:4])).encode() + ",".join(job[4]).encode() + bytes([job[5]]))


def _job(job):
    f = OUT / "parts" / f"{_key(job)}.pkl"
    if f.exists():
        return str(f)
    try:
        res = one(job)
    except Exception as exc:  # one broken series must not cost the rest
        import traceback
        print(f"  FAILED {job[:4]}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}", flush=True)
        return None
    if res is None:
        return None
    pd.to_pickle(res, f)
    return str(f)


def _cot(src):
    f = OUT / "parts" / f"cot_{src}.pkl"
    if not f.exists():
        res = run_cot(src)
        if res is not None:
            pd.to_pickle(res, f)
    return str(f)


def run():
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    js = jobs()
    print(f"{len(js)} series jobs", flush=True)
    workers = int(os.environ.get("WORKERS", 12))
    with ProcessPoolExecutor(workers) as pool:
        futs = [pool.submit(_cot, s) for s in ("real", "walk", "garch")] if not os.environ.get("ONLY") else []
        done = list(pool.map(_job, js, chunksize=1))
        for f in futs:
            f.result()
    print(f"{sum(d is not None for d in done)} parts written", flush=True)


def main():
    mode = os.environ.get("MODE", "run")
    if mode == "fetch_cot":
        fetch_cot()
    elif mode == "run":
        run()
    elif mode == "report":
        import geraked_report
        geraked_report.report(OUT)
    elif mode == "plot":
        import geraked_report
        geraked_report.plot(OUT)


if __name__ == "__main__":
    main()
