"""Three TradingView indicators, traded as the strategy each one implies, on the broker's bars.

Frozen in `tv_rule.json` before this ran on real data. The indicators are the BOS study's rebuilds
(`bos_predict.py`, from the public descriptions, not their source):

  Z  Levels Likely to Break (Zeiierman): repeated-pivot levels and a break-pressure score. Trade the
     break of a level whose pressure (at the bar before the break) is in the top decile; baseline every
     break. Secondary: fade the first touch of a low-pressure level.
  W  Weinstein Stage Cycle Tracker (MarkitTick): long on entering Stage 2, short on entering Stage 4,
     out when the stage ends; % slope (the default) and the BOS study's ATR slope. Baseline every fresh
     30-bar breakout / breakdown.
  F  FVG Magnet Engine (Neblok): toward the nearest unfilled gap >= 1 ATR away when its learned fill
     odds are >= 70%, a bracket at the gap's CE with the stop at the same distance; baseline the same
     toward the nearest gap ignoring the odds, and a coin twin.

Every symbol of `run.FAMILY` on 1h, 4h and 1d, against geometric iid and GARCH walks matched to each
series (256 sub-steps a bar, real timestamps, the real cost in ATR units). Deriv reported apart.

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/tv_indicators.py
  SMOKE=EURUSD:4h:real  one series: counts and timings only
"""
from __future__ import annotations

import os
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

from turn_trade import SPLIT  # noqa: E402
from turn_zones import SLIP, atr  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/tv"))
IVS = ("1h", "4h", "1d")
SOURCES = ("real", "iid", "garch")
WALK_STEPS = 256
HOLD = 300
NS = (0.5, 1, 2, 4, 10)
PIV = 3
MIN_RISK = 0.25
PAD = 0.1
WARM = 120
LEVEL_LIFE = 300
# Z
Z_MATCH, Z_GAP_MIN, Z_GAP_MAX = 0.25, 5, 100
# F
FVG_MIN, FVG_WIN, FVG_DIST, FVG_ODDS, FVG_NMIN = 0.25, 150, 1.0, 0.70, 30
THR = np.array([0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89])
DRAWS = 2000
SCOPES = ("MT5", "fx", "metal", "index", "energy", "crypto", "deriv")


# ------------------------------------------------------------------ data

def family():
    import run as R
    return R.FAMILY


def series(sym, iv, source):
    """The bars (ts, open, high, low, close, volume) and each bar's cost in price, for the real series or
    its geometric iid / GARCH walk (whose cost is the real cost in ATR units times the walk's ATR)."""
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None, None
    df = df.reset_index(drop=True)
    n = len(df)
    spec = load_specs(R.DB).get(sym)
    floor = R.spread_floor(sym, spec) if spec is not None else 0.0
    pt = spec.point if spec is not None else 0.0
    if floor > 0:
        cost = np.full(n, floor * pt)
    elif "spread" in df:
        cost = np.full(n, float(np.nanmedian(df["spread"].to_numpy(float))) * pt)
    else:
        cost = np.zeros(n)
    df = df[["ts", "open", "high", "low", "close", "volume"]].copy()
    cost_atr = cost / np.maximum(atr(df), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        from mcfl import synth
        ts = df["ts"].to_numpy()
        lc = np.log(df["close"].to_numpy(float))
        sigma = float(np.std(np.diff(lc)))
        seed = zlib.crc32(f"tv{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "iid" else synth.garch
        w = gen(n, sigma=sigma, seed=seed, steps=WALK_STEPS).iloc[:n].reset_index(drop=True)
        c0 = float(df["close"].iat[0])
        for k in ("open", "high", "low", "close"):
            w[k] = c0 * np.exp(w[k].to_numpy(float) - synth.START)
        w = synth.ticks(w, seed=seed + 1)
        w["ts"] = ts[:len(w)]
        df = w[["ts", "open", "high", "low", "close", "volume"]]
    return df.reset_index(drop=True), cost_atr[:len(df)] * atr(df)


def arrays(df):
    return tuple(df[k].to_numpy(float) for k in ("open", "high", "low", "close"))


def neg(X):
    o, h, l, c = X
    return -o, -l, -h, -c


# ------------------------------------------------------------------ exits (long; shorts on the negated chart)

def exits_x(o, h, l, c, f, top, stop, a_t, cost_px, hold=HOLD):
    """turn_zones.exits (E1 and X2) with the exit bar and X2's MFE recorded as well (checked equal to it
    in SMOKE). A limit at `top` filled on bar f (a market entry passes top = open[f])."""
    n = len(c)
    risk = top - stop
    entry = min(o[f], top)
    cost = cost_px / risk
    out = {}
    R, mfe, best, st, xb = None, max(0.0, (c[f] - entry) / risk), max(entry, c[f]), stop, f
    if l[f] <= stop:
        R = (min(entry, stop) - SLIP * a_t - entry) / risk
    else:
        for j in range(f + 1, min(n, f + 1 + hold)):
            st = max(st, best - 2 * a_t)
            if l[j] <= st:
                R, xb = (min(o[j], st) - SLIP * a_t - entry) / risk, j
                break
            best = max(best, h[j])
            mfe = max(mfe, (h[j] - entry) / risk)
        if R is None:
            xb = min(n - 1, f + hold)
            R = (c[xb] - entry) / risk
    out["E1"], out["E1_mfe"], out["E1_x"] = R - cost, mfe, xb
    tgt = entry + 2 * risk
    mfe, xb = max(0.0, min(2.0, (c[f] - entry) / risk)), f
    if l[f] <= stop:
        R = (min(entry, stop) - SLIP * a_t - entry) / risk
    elif c[f] >= tgt:
        R = 2.0
    else:
        R = None
        for j in range(f + 1, min(n, f + 1 + hold)):
            if l[j] <= stop:
                R, xb = (min(o[j], stop) - SLIP * a_t - entry) / risk, j
                break
            if h[j] >= tgt:
                R, xb = (max(o[j], tgt) - entry) / risk, j
                mfe = max(mfe, R)
                break
            mfe = max(mfe, (h[j] - entry) / risk)
        if R is None:
            xb = min(n - 1, f + hold)
            R = (c[xb] - entry) / risk
    out["X2"], out["X2_mfe"], out["X2_x"] = R - cost, mfe, xb
    out["entry"], out["risk"] = entry, risk
    return out


def exit_stage(o, h, l, c, f, stop, a_t, cost_px, ok, hold=HOLD):
    """Market entry at open[f], a fixed stop, out at the next open after the first bar (from f) on which
    `ok` is False (the stage has ended); at most `hold` bars."""
    n = len(c)
    entry = o[f]
    risk = entry - stop
    R, mfe, xb = None, max(0.0, (c[f] - entry) / risk), None
    for j in range(f, min(n, f + 1 + hold)):
        if l[j] <= stop:
            R, xb = ((stop if j == f else min(o[j], stop)) - SLIP * a_t - entry) / risk, j
            break
        if j > f:
            mfe = max(mfe, (h[j] - entry) / risk)
        if not ok[j] and j + 1 < n:
            R, xb = (o[j + 1] - entry) / risk, j + 1
            break
    if R is None:
        xb = min(n - 1, f + hold)
        R = (c[xb] - entry) / risk
    return {"STG": R - cost_px / risk, "STG_mfe": mfe, "STG_x": xb}


def exit_bracket(o, h, l, c, f, stop, tgt, a_t, cost_px, cap):
    """Market entry at open[f], a stop and a target (stop first when both trade in one bar), out at the
    close of bar `cap` if neither."""
    n = len(c)
    entry = o[f]
    risk = entry - stop
    R, mfe, xb = None, max(0.0, (c[f] - entry) / risk), None
    for j in range(f, min(n, cap + 1)):
        if l[j] <= stop:
            R, xb = ((stop if j == f else min(o[j], stop)) - SLIP * a_t - entry) / risk, j
            break
        if h[j] >= tgt:
            R, xb = ((tgt if j == f else max(o[j], tgt)) - entry) / risk, j
            mfe = max(mfe, R)
            break
        if j > f:
            mfe = max(mfe, (h[j] - entry) / risk)
    if R is None:
        xb = min(n - 1, cap)
        R = (c[xb] - entry) / risk
    return {"BR": R - cost_px / risk, "BR_mfe": mfe, "BR_x": xb}


# ------------------------------------------------------------------ pivots and levels

def pivots(h, k=PIV):
    """3/3 pivot highs: high above the k before, at or above the k after; known at p + k."""
    s = pd.Series(h)
    left = s.shift(1).rolling(k).max().to_numpy()
    right = s[::-1].shift(1).rolling(k).max().to_numpy()[::-1]
    return np.flatnonzero(np.nan_to_num(h > left) & np.nan_to_num(h >= right))


def first_after(mask, lo, hi):
    """The first index in [lo, hi] where mask is True, else -1."""
    if lo > hi:
        return -1
    x = np.flatnonzero(mask[lo:hi + 1])
    return lo + int(x[0]) if len(x) else -1


class Pressure:
    """Zeiierman break pressure (the BOS study's G2 components; equal weights are ours), for a resistance
    at centre m on a chart (o, h, l, c) - pass the negated chart for a support."""

    def __init__(self, X, v, a):
        o, h, l, c = X
        self.h, self.c, self.a = h, c, a
        rng_ = h - l
        self.rng = rng_
        vm = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
        self.rv = np.where(vm > 0, v / np.where(vm > 0, vm, 1), 1.0)
        clv = np.where(rng_ > 0, ((c - l) - (h - c)) / np.where(rng_ > 0, rng_, 1), 0.0)
        self.clv5 = pd.Series(clv).rolling(5).mean().to_numpy()
        self.range5 = (pd.Series(h).rolling(5).max() - pd.Series(l).rolling(5).min()).to_numpy()

    def __call__(self, t, m):
        A = self.a[t]
        c, h = self.c, self.h
        prox = 1 / (1 + max(0.0, (m - c[t]) / A))
        mom = np.clip((c[t] - c[t - 5]) / (3 * A), -1, 1) / 2 + 0.5
        rvol = np.clip(self.rv[t] / 3, 0, 1)
        dirp = (np.nan_to_num(self.clv5[t]) + 1) / 2
        w = slice(t - 4, t + 1)
        absorb = np.clip(np.mean(self.rv[w] * np.maximum(0, 1 - self.rng[w] / A) * (h[w] >= m - 0.5 * A)), 0, 1)
        comp = np.clip(1 - self.range5[t] / (5 * A), 0, 1)
        touch = np.clip((h[t - 19:t + 1] >= m - 0.25 * A).sum() / 5, 0, 1)
        return float(np.mean([prox, mom, rvol, dirp, absorb, comp, touch]))


def level_events(X, a, b, m, lo, hi):
    """For a resistance born at b (centre m, edges lo/hi): the break bar (first close above hi within the
    level's life), the live bar (a close <= m - ATR(b) before the break), the first touch after live
    (high >= m, not after the break). -1 where none."""
    o, h, l, c = X
    n = len(c)
    end = min(n - 2, b + LEVEL_LIFE)
    t_brk = first_after(c > hi, b + 1, end)
    last = t_brk if t_brk >= 0 else end
    u = first_after(c <= m - a[b], b + 1, last)
    f = first_after(h >= m, u + 1, last) if u >= 0 else -1
    return t_brk, u, f


def break_trade(X, a, cost_px, t, lo):
    """Long at t+1's open after a close above a level; stop below its near edge (min_risk)."""
    o = X[0]
    f = t + 1
    A = a[t]
    stop = min(lo - PAD * A, o[f] - MIN_RISK * A)
    return f, exits_x(*X, f, o[f], stop, A, cost_px[f])


def bounce_trade(X, a, cost_px, f, m, hi):
    """Short at a limit at the centre m of a resistance, filled on bar f; stop above its far edge."""
    A = a[f - 1]
    stop = max(hi + PAD * A, m + MIN_RISK * A)
    return exits_x(*neg(X), f, -m, -stop, A, cost_px[f])


# ------------------------------------------------------------------ Z: levels likely to break

def z_rows(df, cost_px):
    X0 = arrays(df)
    v = df["volume"].to_numpy(float)
    a = atr(df)
    n = len(a)
    rows = []
    for s in (1, -1):
        X = X0 if s > 0 else neg(X0)
        o, h, l, c = X
        P = Pressure(X, v, a)
        piv = pivots(h)
        for i, p in enumerate(piv):
            b = p + PIV
            if b < WARM or b >= n - 2 or not a[b] > 0:
                continue
            j = i - 1
            match = -1
            while j >= 0 and piv[j] >= p - Z_GAP_MAX:
                q = piv[j]
                if q <= p - Z_GAP_MIN and abs(h[q] - h[p]) <= Z_MATCH * a[b] and c[q + 1:b + 1].max() <= h[q]:
                    match = q
                    break
                j -= 1
            if match < 0:
                continue
            lo, hi = min(h[p], h[match]), max(h[p], h[match])
            m = (lo + hi) / 2
            t_brk, u, f = level_events(X, a, b, m, lo, hi)
            base = dict(sym=None, b=b, p1=match, p2=p, lvl_lo=s * lo if s > 0 else -hi, lvl_hi=hi if s > 0 else -lo,
                        lvl_m=s * m)
            if t_brk >= 0 and t_brk - 1 >= 20:
                ff, ex = break_trade(X, a, cost_px, t_brk, lo)
                rows.append(dict(base, strat="Z", var="break", kind="Z", side=s, t=t_brk, f=ff,
                                 press=P(t_brk - 1, m), stop=s * (ex["entry"] - ex["risk"]), entry=s * ex["entry"],
                                 **{k: v_ for k, v_ in ex.items() if k not in ("entry", "risk")}))
            if f >= 0 and f - 1 >= 20:
                ex = bounce_trade(X, a, cost_px, f, m, hi)
                rows.append(dict(base, strat="Z", var="fade", kind="Z", side=-s, t=f - 1, f=f, live=u,
                                 press=P(f - 1, m), stop=-s * (ex["entry"] - ex["risk"]), entry=-s * ex["entry"],
                                 **{k: v_ for k, v_ in ex.items() if k not in ("entry", "risk")}))
    return rows


# ------------------------------------------------------------------ W: Weinstein stages

def machine(c, bo, bd, hi30, rising, falling):
    """bos_predict.weinstein's stage machine, unchanged, with the rising/falling flags passed in."""
    n = len(c)
    stage = np.ones(n, int)
    s, enter, lvl, seen = 1, 0, np.nan, False
    for t in range(n):
        new = s
        if s == 1:
            new = 4 if bd[t] else 2 if bo[t] else 1
        elif s == 2:
            if bd[t]:
                new = 4
            elif t - enter <= 10 and c[t] < lvl:
                new = 1
            elif seen and not rising[t]:
                new = 3
        elif s == 3:
            new = 4 if bd[t] else 2 if bo[t] else 3
        elif s == 4:
            if bo[t]:
                new = 2
            elif seen and not falling[t]:
                new = 1
        if new != s:
            s, enter, seen = new, t, False
            if s == 2:
                lvl = hi30[t]
        if (s == 2 and rising[t]) or (s == 4 and falling[t]):
            seen = True
        stage[t] = s
    return stage


def stages(df, variant):
    from bos_predict import weinstein
    o, h, l, c = arrays(df)
    a = atr(df)
    if variant == "atr":
        return weinstein(c, h, l, a)[0]
    sma = pd.Series(c).rolling(30).mean().to_numpy()
    slope = (sma / np.r_[np.full(4, np.nan), sma[:-4]] - 1) * 100
    hi30 = pd.Series(h).rolling(30).max().shift(1).to_numpy()
    lo30 = pd.Series(l).rolling(30).min().shift(1).to_numpy()
    bo = np.nan_to_num(c > hi30).astype(bool)
    bd = np.nan_to_num(c < lo30).astype(bool)
    return machine(c, bo, bd, hi30, np.nan_to_num(slope > 0.5).astype(bool), np.nan_to_num(slope < -0.5).astype(bool))


def w_rows(df, cost_px):
    X0 = arrays(df)
    o, h, l, c = X0
    a = atr(df)
    n = len(c)
    sma = pd.Series(c).rolling(30).mean().to_numpy()
    hi30 = pd.Series(h).rolling(30).max().shift(1).to_numpy()
    lo30 = pd.Series(l).rolling(30).min().shift(1).to_numpy()
    bo = np.nan_to_num(c > hi30).astype(bool)
    bd = np.nan_to_num(c < lo30).astype(bool)
    rows = []
    for var in ("pct", "atr"):
        st = stages(df, var)
        prev = np.r_[1, st[:-1]]
        for s, want, brk in ((1, 2, bo), (-1, 4, bd)):
            enter = (st == want) & (prev != want)
            fresh = brk & ~np.r_[False, brk[:-1]]
            X = X0 if s > 0 else neg(X0)
            ok = st == want
            for t in np.flatnonzero(enter | fresh):
                if t < WARM or t + 2 >= n or not a[t] > 0 or not np.isfinite(sma[t]):
                    continue
                f, A = t + 1, a[t]
                ma = s * sma[t]
                stop = min(ma - PAD * A, X[0][f] - MIN_RISK * A)
                ex = exits_x(*X, f, X[0][f], stop, A, cost_px[f])
                ex.update(exit_stage(*X, f, stop, A, cost_px[f], ok))
                rows.append(dict(strat="W", var=var, kind="W" if enter[t] else "B", fresh=bool(fresh[t]),
                                 stage_entry=bool(enter[t]), side=s, t=t, f=f, stop=s * stop, entry=s * ex.pop("entry"),
                                 **{k: v_ for k, v_ in ex.items() if k != "risk"}))
    return rows


# ------------------------------------------------------------------ F: FVG magnet

def gaps(X, a):
    o, h, l, c = X
    n = len(c)
    G = []
    for k in range(2, n):
        if not a[k] > 0:
            continue
        for typ, lo, hi in ((1, h[k - 2], l[k]), (-1, h[k], l[k - 2])):
            if hi - lo >= FVG_MIN * a[k]:
                ce = (lo + hi) / 2
                seg = slice(k + 1, min(n, k + 1 + FVG_WIN))
                if typ > 0:
                    x1, x2 = np.flatnonzero(l[seg] <= ce), np.flatnonzero(l[seg] <= lo)
                else:
                    x1, x2 = np.flatnonzero(h[seg] >= ce), np.flatnonzero(h[seg] >= hi)
                big = 10 ** 9
                G.append((k, typ, lo, hi, (hi - lo) / a[k], k + 1 + int(x1[0]) if len(x1) else big,
                          k + 1 + int(x2[0]) if len(x2) else big))
    return G


def sbucket(s):
    return 0 if s < 0.5 else 1 if s < 1 else 2 if s < 2 else 3


def f_rows(df, cost_px, seed):
    """F entries, baseline entries and coin twins for both fill targets (CE, full), and the calibration
    rows at each gap's birth."""
    X0 = arrays(df)
    o, h, l, c = X0
    a = atr(df)
    n = len(c)
    G = gaps(X0, a)
    rng = np.random.default_rng(seed)
    # odds[mode][typ, size bucket, threshold] = (count, fills)
    cnt = np.zeros((2, 2, 4, len(THR)))
    fil = np.zeros((2, 2, 4, len(THR)))

    def odds(mode, g, age):
        ti = int(np.searchsorted(THR, age, side="right")) - 1
        key = (mode, 0 if g[1] > 0 else 1, sbucket(g[4]), ti)
        nn = cnt[key]
        return (fil[key] + 1) / (nn + 2) if nn >= FVG_NMIN else np.nan

    calib, events = [], []
    used = {(mode, kind): set() for mode in (0, 1) for kind in ("F", "B")}
    live = []
    ri = gi = 0
    for t in range(n - 1):
        while ri < len(G) and G[ri][0] + FVG_WIN <= t:      # window closed: the outcome is known
            g = G[ri]
            for mode in (0, 1):
                fa = g[5 + mode] - g[0]
                m = THR < fa
                key = (mode, 0 if g[1] > 0 else 1, sbucket(g[4]))
                cnt[key][m] += 1
                fil[key][m] += fa <= FVG_WIN
            ri += 1
        while gi < len(G) and G[gi][0] <= t:
            g = G[gi]
            live.append(gi)
            calib.append(dict(k=g[0], typ=g[1], size=g[4], ts=0, p_ce=odds(0, g, 0), p_full=odds(1, g, 0),
                              y_ce=float(g[5] - g[0] <= FVG_WIN), y_full=float(g[6] - g[0] <= FVG_WIN)))
            gi += 1
        if t < WARM or not a[t] > 0:
            live = [i for i in live if t - G[i][0] < FVG_WIN and G[i][6] > t]
            continue
        live = [i for i in live if t - G[i][0] < FVG_WIN and G[i][6] > t]
        for mode in (0, 1):
            best, bd = -1, np.inf
            for i in live:
                g = G[i]
                if g[5 + mode] <= t:
                    continue
                tgt = (g[2] + g[3]) / 2 if mode == 0 else (g[2] if g[1] > 0 else g[3])
                d = abs(tgt - c[t])
                if d < bd:
                    best, bd = i, d
            if best < 0 or bd < FVG_DIST * a[t]:
                continue
            g = G[best]
            od = odds(mode, g, t - g[0])
            if best not in used[(mode, "B")]:
                used[(mode, "B")].add(best)
                events.append((t, best, mode, "B", od))
            if od >= FVG_ODDS and best not in used[(mode, "F")]:
                used[(mode, "F")].add(best)
                events.append((t, best, mode, "F", od))
    rows = []
    for t, gi_, mode, kind, od in events:
        g = G[gi_]
        k, typ, lo, hi = g[:4]
        f, cap = t + 1, k + FVG_WIN
        if f > cap or f >= n:
            continue
        tgt = (lo + hi) / 2 if mode == 0 else (lo if typ > 0 else hi)
        entry = o[f]
        D = abs(tgt - entry)
        if not D > 0 or np.sign(tgt - entry) != np.sign(tgt - c[t]):
            continue
        sides = [("F" if kind == "F" else "B", int(np.sign(tgt - entry)))]
        if kind == "F":
            sides.append(("C", int(rng.choice((-1, 1)))))
        for kd, s in sides:
            X = X0 if s > 0 else neg(X0)
            e = s * entry
            stop, tg = e - D, e + D
            ex = exit_bracket(*X, f, stop, tg, a[t], cost_px[f], cap)
            ex.update({k_: v_ for k_, v_ in exits_x(*X, f, e, stop, a[t], cost_px[f]).items()
                       if k_ not in ("entry", "risk", "X2", "X2_mfe", "X2_x")})
            rows.append(dict(strat="F", var="ce" if mode == 0 else "full", kind=kd, side=s, t=t, f=f, odds=od,
                             d_atr=D / a[t], g_k=k, g_typ=typ, g_lo=lo, g_hi=hi, g_size=g[4], cap=cap,
                             filled=float(g[5 + mode] - k <= FVG_WIN), entry=entry, stop=s * stop, tgt=s * tg, **ex))
    return rows, calib


# ------------------------------------------------------------------ run

def one(job):
    sym, iv, source = job
    t0 = time.time()
    try:
        df, cost_px = series(sym, iv, source)
        if df is None:
            return None
        fam = family()[sym]
        ts = df["ts"].to_numpy()
        seed = zlib.crc32(f"tvF{sym}{iv}{source}".encode()) % 100000
        out = z_rows(df, cost_px) + w_rows(df, cost_px)
        fr, calib = f_rows(df, cost_px, seed)
        out += fr
    except Exception as ex:  # one bad series should not sink the run
        import traceback
        print(f"  FAILED {job}: {ex!r}\n{traceback.format_exc()}", flush=True)
        return None
    d = pd.DataFrame(out)
    cb = pd.DataFrame(calib)
    for x in (d, cb):
        if len(x):
            x.insert(0, "src", source)
            x.insert(0, "iv", iv)
            x.insert(0, "fam", fam)
            x["sym"] = sym
    if len(d):
        d["ts"] = ts[d["f"].to_numpy(int)]
    if len(cb):
        cb["ts"] = ts[cb["k"].to_numpy(int)]
    print(f"  {source} {sym} {iv}: {len(d)} trades ({(d['strat'] == 'Z').sum() if len(d) else 0} Z, "
          f"{(d['strat'] == 'W').sum() if len(d) else 0} W, {(d['strat'] == 'F').sum() if len(d) else 0} F), "
          f"{len(cb)} gaps, {time.time() - t0:.0f}s", flush=True)
    return d, cb


def jobs():
    fam = family()
    order = {"1h": 0, "4h": 1, "1d": 2}
    return sorted([(s, iv, src) for s in fam for iv in IVS for src in SOURCES], key=lambda j: order[j[1]])


def boot_draws(x, col, rng, draws=DRAWS):
    """turn_trade.boot's day bootstrap, returning the draws (for the interval and a one-sided p)."""
    g = x.groupby(x["ts"] // 86400)[col].agg(["sum", "count"])
    s, k = g["sum"].to_numpy(), g["count"].to_numpy()
    idx = rng.integers(0, len(g), (draws, len(g)))
    return s[idx].sum(1) / k[idx].sum(1)


def stats(x, col, rng, **tag):
    y = x[col].to_numpy(float)
    r = dict(**tag, n=len(x), R=float(np.mean(y)) if len(x) else np.nan)
    if len(x) > 30:
        b = boot_draws(x, col, rng)
        r.update(lo=np.quantile(b, 0.05), hi=np.quantile(b, 0.95), p=float((b <= 0).mean()))
    else:
        r.update(lo=np.nan, hi=np.nan, p=np.nan)
    before = x["ts"] < SPLIT
    r.update(R_before=x.loc[before, col].mean(), R_after=x.loc[~before, col].mean(), win=float((y > 0).mean()) if len(x) else np.nan)
    mc = col + "_mfe"
    if mc in x:
        r.update({f"P{N}R": float((x[mc] >= N).mean()) for N in NS})
    r.update(P_R4=float((y >= 4).mean()) if len(x) else np.nan, P_R10=float((y >= 10).mean()) if len(x) else np.nan)
    return r


def scope_mask(d, scope):
    if scope == "MT5":
        return (d["fam"] != "deriv").to_numpy()
    return (d["fam"] == scope).to_numpy()


def z_cut(d):
    """Pressure cut-offs per source and interval from pre-2024 non-Deriv events: top decile of breaks,
    bottom decile of first touches."""
    out = {}
    for (src, iv, var), g in d[(d["strat"] == "Z") & (d["fam"] != "deriv") & (d["ts"] < SPLIT)].groupby(["src", "iv", "var"]):
        out[(src, iv, var)] = g["press"].quantile(0.9 if var == "break" else 0.1)
    return out


def cells(d):
    """Every (strategy, cell name) -> (row mask, exits): the primaries, baselines and secondaries."""
    cut = z_cut(d)
    zc = np.array([cut.get((s, iv, v), np.nan) for s, iv, v in zip(d["src"], d["iv"], d["var"], strict=False)])
    Z, W, F = (d["strat"] == "Z").to_numpy(), (d["strat"] == "W").to_numpy(), (d["strat"] == "F").to_numpy()
    var, kind = d["var"].to_numpy(), d["kind"].to_numpy()
    press = d["press"].to_numpy(float) if "press" in d else np.full(len(d), np.nan)
    C = {
        "Z top decile": (Z & (var == "break") & (press >= zc), ("E1", "X2")),
        "Z all breaks": (Z & (var == "break"), ("E1", "X2")),
        "Z bottom 90%": (Z & (var == "break") & (press < zc), ("E1", "X2")),
        "Z fade bottom decile": (Z & (var == "fade") & (press <= zc), ("E1", "X2")),
        "Z fade all touches": (Z & (var == "fade"), ("E1", "X2")),
    }
    for v in ("pct", "atr"):
        C[f"W {v} stage entries"] = (W & (var == v) & d["stage_entry"].fillna(False).to_numpy(bool), ("STG", "E1", "X2"))
        C[f"W {v} fresh breakouts"] = (W & (var == v) & d["fresh"].fillna(False).to_numpy(bool), ("STG", "E1", "X2"))
    for v in ("ce", "full"):
        C[f"F {v} odds>=70%"] = (F & (var == v) & (kind == "F"), ("BR", "E1"))
        C[f"F {v} nearest gap"] = (F & (var == v) & (kind == "B"), ("BR", "E1"))
        C[f"F {v} coin twin"] = (F & (var == v) & (kind == "C"), ("BR", "E1"))
    return C


PRIMARY = {"Z": ("Z top decile", "E1", "Z all breaks"),
           "W": ("W pct stage entries", "STG", "W pct fresh breakouts"),
           "F": ("F ce odds>=70%", "BR", "F ce nearest gap")}


def table(d, C, rng):
    rows = []
    for name, (m, exs) in C.items():
        for scope in SCOPES:
            ms = m & scope_mask(d, scope)
            for src in SOURCES:
                msrc = ms & (d["src"] == src).to_numpy()
                for iv in ("all",) + IVS:
                    mm = msrc if iv == "all" else msrc & (d["iv"] == iv).to_numpy()
                    if iv != "all" and scope not in ("MT5", "deriv"):
                        continue
                    x = d[mm]
                    for ex in exs:
                        rows.append(stats(x, ex, rng, cell=name, exit=ex, scope=scope, src=src, iv=iv))
    return pd.DataFrame(rows)


def bh(t, q=0.10):
    """Benjamini-Hochberg over the real cells with a p (n > 30): adds `bh` (passes at q)."""
    m = (t["src"] == "real") & t["p"].notna()
    p = t.loc[m, "p"].to_numpy()
    o = np.argsort(p)
    k = len(p)
    ok = p[o] <= q * (np.arange(1, k + 1) / k)
    last = np.flatnonzero(ok).max() + 1 if ok.any() else 0
    flag = np.zeros(k, bool)
    flag[o[:last]] = True
    t["bh"] = False
    t.loc[m, "bh"] = flag
    return t, k


def verdict(t, name, ex, base, scope="MT5"):
    def g(cell, src):
        r = t[(t["cell"] == cell) & (t["exit"] == ex) & (t["scope"] == scope) & (t["src"] == src) & (t["iv"] == "all")]
        return r.iloc[0] if len(r) else None
    p, w, gw, b = g(name, "real"), g(name, "iid"), g(name, "garch"), g(base, "real")
    if p is None or w is None or gw is None or b is None or not p["n"]:
        return "n/a", False
    ok = bool(p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0 and p["R"] > b["R"]
              and p["R"] > w["R"] and p["R"] > gw["R"])
    s = (f"R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={int(p['n'])}, before {p['R_before']:+.3f}, "
         f"after {p['R_after']:+.3f}; baseline {b['R']:+.3f}; iid {w['R']:+.3f}; garch {gw['R']:+.3f} -> "
         f"{'PASSES' if ok else 'fails'}")
    return s, ok


def calib_table(cb, d):
    rows = []
    bins = np.linspace(0, 1, 11)
    for (src, scope_d), g in cb.assign(scope_d=np.where(cb["fam"] == "deriv", "deriv", "MT5")).groupby(["src", "scope_d"]):
        for mode in ("ce", "full"):
            x = g[g[f"p_{mode}"].notna()]
            k = np.clip(np.digitize(x[f"p_{mode}"], bins) - 1, 0, 9)
            for b_, y in x.groupby(k):
                rows.append(dict(src=src, scope=scope_d, at="birth", target=mode, bin=bins[b_] + 0.05, n=len(y),
                                 pred=y[f"p_{mode}"].mean(), real=y[f"y_{mode}"].mean()))
    f = d[(d["strat"] == "F") & (d["kind"] == "B") & d["odds"].notna()]
    for (src, scope_d, mode), g in f.assign(scope_d=np.where(f["fam"] == "deriv", "deriv", "MT5")).groupby(["src", "scope_d", "var"]):
        k = np.clip(np.digitize(g["odds"], bins) - 1, 0, 9)
        for b_, y in g.groupby(k):
            rows.append(dict(src=src, scope=scope_d, at="entry", target=mode, bin=bins[b_] + 0.05, n=len(y),
                             pred=y["odds"].mean(), real=y["filled"].mean(), hit=(y["BR"] > 0).mean()))
    return pd.DataFrame(rows)


def report(d, t, k, prim):
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 2000)
    cols = ["cell", "exit", "scope", "src", "iv", "n", "R", "lo", "hi", "p", "R_before", "R_after", "win",
            "P0.5R", "P1R", "P2R", "P4R", "P10R", "P_R4", "P_R10", "bh"]
    show = t[(t["iv"] == "all")][[c for c in cols if c in t]]
    print(show.round(3).to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})
    print(f"\nBenjamini-Hochberg (q = 0.10) over {k} real cells with n > 30; passing, R > 0:")
    print(t[(t["src"] == "real") & t["bh"] & (t["R"] > 0)][cols].round(3).to_string(index=False))
    print("\nPRIMARIES (MT5 non-Deriv pooled, 1h/4h/1d):")
    for key, (name, ex, base) in prim.items():
        s, _ = verdict(t, name, ex, base)
        print(f"  {key}: {name}, {ex}: {s}")
    print("\nPer family (reported):")
    for key, (name, ex, base) in prim.items():
        for scope in SCOPES[1:]:
            s, _ = verdict(t, name, ex, base, scope)
            print(f"  {key} {scope:7s} {s}")


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    smoke = os.environ.get("SMOKE")
    if smoke:
        smoke_one(*smoke.split(":"))
        return
    with ProcessPoolExecutor(min(10, int(os.environ.get("WORKERS", 10)))) as pool:
        got = [g for g in pool.map(one, jobs(), chunksize=1) if g is not None]
    d = pd.concat([g[0] for g in got if len(g[0])], ignore_index=True)
    cb = pd.concat([g[1] for g in got if len(g[1])], ignore_index=True)
    d.to_pickle(OUT / "tv_trades.pkl.gz")
    cb.to_pickle(OUT / "tv_gaps.pkl.gz")
    score()


def score():
    d = pd.read_pickle(OUT / "tv_trades.pkl.gz")
    cb = pd.read_pickle(OUT / "tv_gaps.pkl.gz")
    rng = np.random.default_rng(71)
    t = table(d, cells(d), rng)
    t, k = bh(t)
    t.round(5).to_csv(OUT / "tv_cells.csv", index=False)
    c = calib_table(cb, d)
    c.round(4).to_csv(OUT / "tv_calibration.csv", index=False)
    pd.Series({f"{a}|{b}|{v}": x for (a, b, v), x in z_cut(d).items()}).to_csv(OUT / "tv_zcut.csv")
    report(d, t, k, PRIMARY)
    print("\nFVG calibration (MT5 non-Deriv):")
    print(c[c["scope"] == "MT5"].round(3).to_string(index=False))


def smoke_one(sym, iv, source):
    """One series: counts, timings and the exits check against turn_zones.exits; no R is printed."""
    from bos_predict import weinstein
    from turn_zones import exits
    t0 = time.time()
    df, cost_px = series(sym, iv, source)
    print(f"{sym} {iv} {source}: {len(df)} bars, cost median {np.median(cost_px / atr(df)):.4f} ATR, "
          f"{time.time() - t0:.1f}s", flush=True)
    X = arrays(df)
    a = atr(df)
    rng = np.random.default_rng(0)
    bad = 0
    for f in rng.integers(200, len(df) - 400, 300):
        top = X[0][f]
        stop = top - (0.25 + rng.random()) * a[f - 1]
        e, r = exits(*X, f, top, stop, a[f - 1], 0.3 * a[f], HOLD), exits_x(*X, f, top, stop, a[f - 1], 0.3 * a[f])
        bad += abs(e["E1"] - r["E1"]) > 1e-9 or abs(e["X2"] - r["X2"]) > 1e-9 or abs(e["mfe"] - r["E1_mfe"]) > 1e-9
    print(f"exits_x vs turn_zones.exits on 300 random fills: {bad} differ", flush=True)
    o, h, l, c = X
    # the machine reproduces bos_predict.weinstein given its own flags
    sma = pd.Series(c).rolling(30).mean().to_numpy()
    slope = (sma - np.r_[np.full(4, np.nan), sma[:-4]]) / a
    sd = pd.Series(slope).rolling(500, min_periods=100).std().shift(1).to_numpy()
    z = np.clip(np.nan_to_num(slope / sd), -5, 5)
    hi30 = pd.Series(h).rolling(30).max().shift(1).to_numpy()
    lo30 = pd.Series(l).rolling(30).min().shift(1).to_numpy()
    st = machine(c, np.nan_to_num(c > hi30).astype(bool), np.nan_to_num(c < lo30).astype(bool), hi30, z > 0.5, z < -0.5)
    print(f"machine vs bos_predict.weinstein: {(st != weinstein(c, h, l, a)[0]).sum()} bars differ", flush=True)
    for name, fn in (("Z", lambda: z_rows(df, cost_px)), ("W", lambda: w_rows(df, cost_px)),
                     ("F", lambda: f_rows(df, cost_px, 1))):
        t1 = time.time()
        r = fn()
        r = pd.DataFrame(r[0] if name == "F" else r)
        print(f"{name}: {len(r)} rows in {time.time() - t1:.1f}s", flush=True)
        if len(r):
            print(r.groupby(["var", "kind"]).size().to_string(), flush=True)
            if name == "Z":
                print(r.groupby("var")["press"].describe().round(3).to_string(), flush=True)
            if name == "W":
                print(f"stage share pct: {np.bincount(stages(df, 'pct'), minlength=5)[1:] / len(df)}; "
                      f"atr: {np.bincount(stages(df, 'atr'), minlength=5)[1:] / len(df)}", flush=True)
            if name == "F":
                print(r.groupby(["var", "kind"])[["odds", "d_atr"]].describe().round(3).to_string(), flush=True)


# ------------------------------------------------------------------ plots

STAGE_COL = {1: "#8d99ae", 2: "#2a9d8f", 3: "#e9c46a", 4: "#e63946"}


def candles(ax, w, x):
    up = (w["close"] >= w["open"]).to_numpy()
    ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
    ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
    ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)


def pnr_plot(t, prim, fname, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(prim), len(SCOPES), figsize=(4 * len(SCOPES), 3.6 * len(prim)), sharey=True, squeeze=False)
    for i, (key, (name, ex, base)) in enumerate(prim.items()):
        for j, scope in enumerate(SCOPES):
            ax = axes[i, j]
            for src, cell, st, lab in (("real", name, "-o", "real"), ("iid", name, "--s", "iid"),
                                       ("garch", name, ":^", "garch"), ("real", base, "-.x", "baseline")):
                r = t[(t["cell"] == cell) & (t["exit"] == ex) & (t["scope"] == scope) & (t["src"] == src) & (t["iv"] == "all")]
                if len(r) and r.iloc[0]["n"] > 0:
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}R"] for N in NS], st, label=f"{lab} R {r['R']:+.3f} (n {int(r['n'])})")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_title(f"{key} {scope}: {name}, {ex}", fontsize=8)
            ax.legend(fontsize=6)
    for ax in axes[:, 0]:
        ax.set_ylabel("P(trade reaches N R)")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / fname, dpi=70)
    plt.close(fig)


def gallery(d, strat_cell, ex, tag, draw, fname, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rng = np.random.default_rng(9)
    x = d[strat_cell & (d["src"] == "real").to_numpy() & (d["fam"] != "deriv").to_numpy()]
    x = x[x["iv"] == "4h"] if (x["iv"] == "4h").sum() > 50 else x
    sub = x[x[ex] > 0] if tag == "winners" else x[x[ex] <= 0]
    if not len(sub):
        return
    pick = sub.iloc[rng.choice(len(sub), min(6, len(sub)), replace=False)]
    fig, axes = plt.subplots(2, 3, figsize=(21, 10))
    cache = {}
    for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
        key = (r.sym, r.iv)
        if key not in cache:
            cache[key] = series(r.sym, r.iv, "real")[0]
        df = cache[key]
        draw(ax, df, r, ex)
    fig.suptitle(title + f" ({tag}, real MT5, {ex})", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / fname, dpi=70)
    plt.close(fig)


def _trade_marks(ax, r, ex, i1):
    f, xb = int(r.f), int(r[f"{ex}_x"])
    ax.plot([f], [r.entry], "k>" if r.side > 0 else "k<", ms=9)
    ax.hlines(r.stop, f, xb, colors="red", lw=1, label="stop")
    ax.axvline(xb, color="k", lw=0.8, ls="--")


def draw_z(ax, df, r, ex):
    t, f, xb = int(r.t), int(r.f), int(r[f"{ex}_x"])
    i0, i1 = max(0, int(r.p1) - 15), min(len(df) - 1, xb + 15)
    w = df.iloc[i0:i1 + 1]
    candles(ax, w, np.arange(i0, i1 + 1))
    ax.fill_between([int(r.b), min(i1, int(r.b) + LEVEL_LIFE)], r.lvl_lo, r.lvl_hi, color="#457b9d", alpha=0.3)
    ax.hlines(r.lvl_m, int(r.p1), i1, colors="#1d3557", lw=1)
    for p in (int(r.p1), int(r.p2)):
        ax.plot([p], [df["high"].iat[p] if r.lvl_m >= df["close"].iat[int(r.b)] else df["low"].iat[p]], "o", color="#1d3557")
    _trade_marks(ax, r, ex, i1)
    ax.axvline(t, color="purple", lw=1, ls=":")
    ax.set_title(f"{r.sym} {r.iv} {r['var']} {'long' if r.side > 0 else 'short'} pressure {r.press:.2f} -> {r[ex]:+.2f}R "
                 f"{pd.Timestamp(int(r.ts), unit='s'):%Y-%m-%d}", fontsize=9)


def draw_w(ax, df, r, ex):
    t, xb = int(r.t), int(r[f"{ex}_x"])
    i0, i1 = max(0, t - 60), min(len(df) - 1, xb + 15)
    w = df.iloc[i0:i1 + 1]
    x = np.arange(i0, i1 + 1)
    candles(ax, w, x)
    st = stages(df, r["var"])[i0:i1 + 1]
    sma = pd.Series(df["close"].to_numpy(float)).rolling(30).mean().to_numpy()[i0:i1 + 1]
    for k in range(len(x) - 1):
        ax.plot(x[k:k + 2], sma[k:k + 2], color=STAGE_COL[int(st[k])], lw=2.5)
    hi30 = df["high"].iloc[t - 30:t].max()
    lo30 = df["low"].iloc[t - 30:t].min()
    ax.hlines([hi30, lo30], t - 30, t, colors="#999", lw=1, ls="--")
    _trade_marks(ax, r, ex, i1)
    ax.axvline(t, color="purple", lw=1, ls=":")
    ax.set_title(f"{r.sym} {r.iv} slope {r['var']} {'long (Stage 2)' if r.side > 0 else 'short (Stage 4)'} -> {r[ex]:+.2f}R "
                 f"{pd.Timestamp(int(r.ts), unit='s'):%Y-%m-%d}  MA: grey 1, green 2, yellow 3, red 4", fontsize=9)


def draw_f(ax, df, r, ex):
    k, t, xb = int(r.g_k), int(r.t), int(r[f"{ex}_x"])
    i0, i1 = max(0, k - 10), min(len(df) - 1, max(xb, t) + 15)
    w = df.iloc[i0:i1 + 1]
    candles(ax, w, np.arange(i0, i1 + 1))
    ax.fill_between([k - 1, min(i1, int(r.cap))], r.g_lo, r.g_hi, color="#f4a261", alpha=0.35)
    ax.hlines((r.g_lo + r.g_hi) / 2, k - 1, min(i1, int(r.cap)), colors="#e76f51", lw=1, ls=":")
    ax.hlines(r.tgt, int(r.f), xb, colors="green", lw=1)
    _trade_marks(ax, r, ex, i1)
    ax.axvline(t, color="purple", lw=1, ls=":")
    ax.set_title(f"{r.sym} {r.iv} {'long' if r.side > 0 else 'short'} to a {'up' if r.g_typ > 0 else 'down'} gap "
                 f"{r.g_size:.1f} ATR, odds {r.odds:.2f}, {r.d_atr:.1f} ATR away -> {r[ex]:+.2f}R "
                 f"{pd.Timestamp(int(r.ts), unit='s'):%Y-%m-%d}", fontsize=9)


def calib_plot(c):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    col = {"real": "#1d3557", "iid": "#a8dadc", "garch": "#e9c46a"}
    for i, scope in enumerate(("MT5", "deriv")):
        for j, (at, target) in enumerate((("birth", "ce"), ("birth", "full"), ("entry", "ce"))):
            ax = axes[i, j]
            for src in SOURCES:
                g = c[(c["scope"] == scope) & (c["src"] == src) & (c["at"] == at) & (c["target"] == target) & (c["n"] >= 50)]
                ax.plot(g["pred"], g["real"], "-o", color=col[src], label=f"{src} (n {int(g['n'].sum())})")
                if at == "entry":
                    ax.plot(g["pred"], g["hit"], ":^", color=col[src], label=f"{src}: bracket won")
            ax.plot([0, 1], [0, 1], color="grey", lw=0.8)
            ax.axvline(FVG_ODDS, color="purple", lw=0.8, ls=":")
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.set_xlabel("predicted fill odds (bin mean)")
            ax.set_ylabel("realised fill within 150 bars")
            ax.set_title(f"{scope}: {target} fill odds at the gap's {at}", fontsize=10)
            ax.legend(fontsize=7)
    fig.suptitle("FVG Magnet: learned (age-adjusted, small-sample corrected) fill odds against realised fills, real vs walks")
    fig.tight_layout()
    fig.savefig(OUT / "tv_fvg_calibration.png", dpi=70)
    plt.close(fig)


def plot():
    t = pd.read_csv(OUT / "tv_cells.csv")
    d = pd.read_pickle(OUT / "tv_trades.pkl.gz")
    pnr_plot(t, PRIMARY, "tv_pnr.png", "TradingView indicators, primaries: P(N R) real vs iid, GARCH and the baseline, per family")
    sec = {"Z fade": ("Z fade bottom decile", "E1", "Z fade all touches"),
           "W atr": ("W atr stage entries", "STG", "W atr fresh breakouts"),
           "F full": ("F full odds>=70%", "BR", "F full nearest gap")}
    pnr_plot(t, sec, "tv_pnr_secondary.png", "TradingView indicators, secondary variants: P(N R) real vs walks and baseline")
    C = cells(d)
    for key, draw, title in (("Z", draw_z, "Z: break of a top-decile pressure level (blue band: the repeated-pivot level; "
                                            "purple: the break bar; red: stop; dashed: exit)"),
                             ("W", draw_w, "W: entering Stage 2 / 4, % slope (MA coloured by stage; dashed grey: the "
                                           "30-bar range broken; red: stop; dashed: exit)"),
                             ("F", draw_f, "F: toward a >= 70% odds gap (orange: the gap to expiry; dotted: CE; green: "
                                           "target; red: stop; dashed: exit)")):
        name, ex, _ = PRIMARY[key]
        for tag in ("winners", "losers"):
            gallery(d, C[name][0], ex, tag, draw, f"tv_{key}_{tag}.png", title)
    calib_plot(pd.read_csv(OUT / "tv_calibration.csv"))
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot, "score": score}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
