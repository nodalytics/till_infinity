"""FX and metals candles for ML and adaptive conformal inference: bars, walks, features, targets.

Frozen in `fxml_rule.json` before any real-data run (see `research/docs/fx-metals-ml.md`). This module
builds one row per (series, bar t) with every causal feature known at t's close and every target
resolved after it, for the real bars and for matched iid and GARCH walks, and writes

  OUT/ds_<tf>_<source>.pkl     the rows (features, targets, cost) for one timeframe and source
  OUT/bars_<tf>_<source>.pkl   the bars per series (for the trade translation)

  OUT=... MT5BT_DB=... SEQLAB=... WORKERS=8 python research/ideas/fxml_data.py
"""
from __future__ import annotations

import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

OUT = Path(os.environ.get("OUT", ".data/fxml"))
SEQLAB = os.environ.get("SEQLAB", os.path.expanduser("~/till_infinity/data/seqlab"))

FX = "EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP AUDJPY USDCNH".split()
METAL = "XAUUSD XAGUSD XPTUSD XPDUSD XCUUSD".split()
HOLD = "EURCHF CHFJPY EURAUD".split()
MAIN = FX + METAL
TFS = ("1h", "4h", "1d")
SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
K = {"15m": 16, "1h": 24, "4h": 6, "1d": 5}
SPLIT = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())
SOURCES = ("real", "iid", "garch")
WALK_STEPS = 256
MAX_COST_ATR = 0.5
LRC_L = (10, 20, 50, 100)
PAIRS = ((1, 3), (1, 5), (3, 10), (5, 20))
POLY_L = (20, 50, 100)
POLY_DEG = (2, 3)
PCA_W = {"15m": 960, "1h": 720, "4h": 360, "1d": 250}
PCA_R = {"15m": 32, "1h": 24, "4h": 6, "1d": 5}
NPC = 3
SIGNK = 5
FIRST_H = 10
NR_CAP = 500
PAD, MIN_RISK = 0.1, 0.25
NY = ZoneInfo("America/New_York")


# ------------------------------------------------------------------------------------------ the bars

def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def rollover_open(ts):
    """Whether a bar opens at 17:00 New York (21:00 UTC in summer, 22:00 in winter)."""
    hrs = pd.to_datetime(ts, unit="s", utc=True).tz_convert(NY)
    return np.asarray((hrs.hour == 17) & (hrs.minute == 0))


def trim_rollover(df, tf):
    """rollover.md: the 1h FX bar opening at 17:00 New York has its wick cut to the body."""
    if tf not in ("15m", "1h"):
        return df
    m = rollover_open(df["ts"].to_numpy())
    if tf == "15m":  # the 16:55-17:10 window: bars opening 16:45, 17:00
        hrs = pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True).tz_convert(NY)
        m = np.asarray(((hrs.hour == 16) & (hrs.minute == 45)) | ((hrs.hour == 17) & (hrs.minute == 0)))
    df = df.copy()
    body_hi = np.maximum(df["open"], df["close"])
    body_lo = np.minimum(df["open"], df["close"])
    df.loc[m, "high"] = body_hi[m]
    df.loc[m, "low"] = body_lo[m]
    return df


def load_main(sym, tf):
    """(bars, cost in price) from MT5BT_DB, cost as lrc_retest._mt5."""
    from mt5bt import load_bars, load_specs
    import run as R
    db = os.environ.get("MT5BT_DB")
    try:
        df = load_bars(sym, tf, "sqlite", db)
    except (ValueError, OSError):
        return None, None
    R.DB = db
    spec = load_specs(db).get(sym)
    if spec is None:
        return None, None
    floor = R.spread_floor(sym, spec)
    if not floor > 0:
        sp = df["spread"].to_numpy(float) if "spread" in df else np.array([np.nan])
        floor = float(np.nanmedian(sp)) if np.isfinite(sp).any() else 0.0
    df = df[["ts", "open", "high", "low", "close"]].astype({"ts": np.int64}).reset_index(drop=True)
    if sym in FX:
        df = trim_rollover(df, tf)
    return df, floor * spec.point


def load_hold(sym, tf):
    """Holdout pairs from the lab's broker bars (seqlab npz)."""
    from mt5bt import load_bars
    try:
        df = load_bars(sym, tf, "seqlab", SEQLAB)
    except (ValueError, OSError, FileNotFoundError):
        return None, None
    point = 0.001 if sym.endswith("JPY") else 0.00001
    sp = df["spread"].to_numpy(float) if "spread" in df else np.array([])
    sp = sp[np.isfinite(sp) & (sp > 0)]
    cost = float(np.median(sp)) * point if len(sp) else 0.0
    df = df[["ts", "open", "high", "low", "close"]].astype({"ts": np.int64}).reset_index(drop=True)
    return trim_rollover(df, tf), cost


def make_walk(df, kind, seed):
    """A matched walk in log price on the real timestamps: iid or GARCH(1,1), 256 sub-steps."""
    from mcfl import synth
    c = df["close"].to_numpy(float)
    lc = np.log(c)
    sig = float(np.std(np.diff(lc)))
    n = len(df)
    gen = synth.walk if kind == "iid" else synth.garch
    w = gen(n, sigma=sig, seed=seed, steps=WALK_STEPS).reset_index(drop=True).iloc[:n]
    out = pd.DataFrame({"ts": df["ts"].to_numpy(np.int64)})
    for k in ("open", "high", "low", "close"):
        out[k] = c[0] * np.exp(w[k].to_numpy(float) - synth.START)
    return out


# ------------------------------------------------------------------------------------------ features

def lrc_stats(c, L):
    """LRC(L) slope per bar (lrc_retest.lrc) and the window's Pearson R."""
    from lrc_retest import lrc
    slope, _, _ = lrc(c, L)
    x = np.arange(L, dtype=float)
    sx = float(x.std())
    sy = pd.Series(c).rolling(L).std(ddof=0).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(sy > 0, slope * sx / sy, 0.0)
    return slope, r


def polyfit_block(c, a, F, prefix="pf"):
    """Amendment Q: rolling least-squares polynomials of degree 2 and 3 in time over the last L closes
    (bar t at x = 0). Slope, curvature, jerk at t over ATR; residual of the close from the fit; the
    one-bar extrapolation; the fit's R^2."""
    n = len(c)
    for L in POLY_L:
        if n < L:
            continue
        u = np.arange(-(L - 1), 1, dtype=float) / L
        W = np.lib.stride_tricks.sliding_window_view(c, L)
        ss_tot = ((W - W.mean(1, keepdims=True)) ** 2).sum(1)
        for deg in POLY_DEG:
            V = np.vander(u, deg + 1, increasing=True)
            Pm = np.linalg.pinv(V)
            B = W @ Pm.T
            fit = B @ V.T
            ss_res = ((W - fit) ** 2).sum(1)
            pad = lambda x: np.r_[np.full(L - 1, np.nan), x]  # noqa: E731
            at = a
            pre = f"{prefix}{L}_{deg}"
            F[f"{pre}_slope"] = pad(B[:, 1] / L) / at
            F[f"{pre}_curv"] = pad(2 * B[:, 2] / L ** 2) / at
            if deg == 3:
                F[f"{pre}_jerk"] = pad(6 * B[:, 3] / L ** 3) / at
            F[f"{pre}_resid"] = (c - pad(B[:, 0])) / at
            ext = (np.vander(np.array([1.0 / L]), deg + 1, increasing=True) @ B.T)[0]
            F[f"{pre}_ext1"] = (pad(ext) - c) / at
            with np.errstate(divide="ignore", invalid="ignore"):
                F[f"{pre}_r2"] = pad(np.where(ss_tot > 0, 1 - ss_res / ss_tot, 0.0))


def lag(x, k):
    out = np.full_like(x, np.nan)
    if k < len(x):
        out[k:] = x[:-k] if k else x
    return out


def slope_block(name, s, a, F):
    """One slope series s (price per bar): normalised, sign, derivatives, frozen (M, N) differences."""
    sn = s / a
    F[f"{name}"] = sn
    F[f"{name}_sgn"] = np.sign(sn)
    d1 = sn - lag(sn, 1)
    F[f"{name}_d1"] = d1
    F[f"{name}_acc"] = d1 - lag(d1, 1)
    for m, n in PAIRS:
        F[f"{name}_d0_{n}"] = sn - lag(sn, n)
        F[f"{name}_d{m}_{n}"] = lag(sn, m) - lag(sn, n)


def ohlc_block(df, a):
    """Amendment O: features from open, high and low as well as closes (every name starts with o_)."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    F = {}
    series = {"o": o, "h": h, "l": l, "tp": (h + l + c) / 3, "mp": (h + l) / 2}
    sl = {}
    for nm, x in series.items():
        for L in LRC_L:
            s_, r = lrc_stats(x, L)
            slope_block(f"o_{nm}lrc{L}", s_, a, F)
            F[f"o_{nm}lrc{L}_R"] = r
            sl[(nm, L)] = s_ / a
        polyfit_block(x, a, F, prefix=f"o_{nm}pf")
    for L in LRC_L:
        sc, _ = lrc_stats(c, L)
        hl = sl[("h", L)] - sl[("l", L)]
        co = sc / a - sl[("o", L)]
        F[f"o_sp_hl{L}"] = hl
        F[f"o_sp_hl{L}_d1"] = hl - lag(hl, 1)
        F[f"o_sp_co{L}"] = co
        F[f"o_sp_co{L}_d1"] = co - lag(co, 1)
    rngp = h - l
    pc = np.r_[np.nan, c[:-1]]
    ph, pl = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        cand = {
            "body": np.where(rngp > 0, (c - o) / rngp, 0.0),
            "uwick": np.where(rngp > 0, (h - np.maximum(o, c)) / rngp, 0.0),
            "lwick": np.where(rngp > 0, (np.minimum(o, c) - l) / rngp, 0.0),
            "cloc": np.where(rngp > 0, (c - l) / rngp, 0.5),
            "gap": (o - pc) / a,
            "overlap": np.where(rngp > 0, np.clip(np.minimum(h, ph) - np.maximum(l, pl), 0, None) / rngp, 0.0),
        }
    for nm, x in cand.items():
        for k_ in range(0 if nm in ("gap", "overlap") else 1, 6):
            F[f"o_c_{nm}{k_}"] = lag(x, k_) if k_ else x
        xs = pd.Series(x)
        F[f"o_c_{nm}_m5"] = xs.rolling(5).mean().to_numpy()
        F[f"o_c_{nm}_m20"] = xs.rolling(20).mean().to_numpy()
        s_, _ = lrc_stats(np.nan_to_num(x), 10)
        F[f"o_c_{nm}_sl10"] = s_
    inside = ((h <= ph) & (l >= pl)).astype(float)
    outside = ((h >= ph) & (l <= pl)).astype(float)
    F["o_c_inside"], F["o_c_outside"] = inside, outside
    F["o_c_inside_n5"] = pd.Series(inside).rolling(5).sum().to_numpy()
    F["o_c_outside_n5"] = pd.Series(outside).rolling(5).sum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    F["o_rs20"] = np.sqrt(np.clip(pd.Series(rs).rolling(20).mean().to_numpy(), 0, None)) / (a / c)
    return pd.DataFrame({k_: np.asarray(v, np.float32) for k_, v in F.items()})


def resample(df, sec):
    g = df.groupby(df["ts"] // sec * sec)
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last()}).rename_axis("ts").reset_index()


def htf_slope(df, tf, htf):
    """LRC(50) slope / ATR of the last COMPLETED higher-timeframe bar, at each base bar's close."""
    hs = SEC[htf]
    r = resample(df, hs)
    hh, hl, hc = (r[k].to_numpy(float) for k in ("high", "low", "close"))
    from lrc_retest import lrc
    s, _, _ = lrc(hc, 50)
    v = s / atr(hh, hl, hc)
    end_h = r["ts"].to_numpy(np.int64) + hs
    end_b = df["ts"].to_numpy(np.int64) + SEC[tf]
    j = np.searchsorted(end_h, end_b, side="right") - 1
    out = np.where(j >= 0, v[np.clip(j, 0, None)], np.nan)
    return out


def prior_hl(ts, h, l, key):
    """High and low of the period (day / week key) before the one containing each bar."""
    k = key(ts)
    u, inv = np.unique(k, return_inverse=True)
    ph = pd.Series(h).groupby(inv).max().to_numpy()
    pl = pd.Series(l).groupby(inv).min().to_numpy()
    prev = inv - 1
    ok = prev >= 0
    H = np.where(ok, ph[np.clip(prev, 0, None)], np.nan)
    L = np.where(ok, pl[np.clip(prev, 0, None)], np.nan)
    return H, L


def features(df, tf, is_metal):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy(np.int64)
    k = K[tf]
    a = atr(h, l, c)
    a = np.where(a > 0, a, np.nan)
    F = {}
    # B0: returns, volatility, time
    for n_ in (1, 5, 20):
        F[f"r{n_}"] = (c - lag(c, n_)) / a
    F["absr1"] = np.abs(F["r1"])
    F["rng"] = (h - l) / a
    a5, a50 = atr(h, l, c, 5), atr(h, l, c, 50)
    with np.errstate(divide="ignore", invalid="ignore"):
        F["atr_ratio"] = np.log(a5 / a50)
        lv = np.log(a / c)
    F["lvol_z"] = lv - pd.Series(lv).rolling(500, min_periods=100).median().to_numpy()
    unit = a / c
    with np.errstate(divide="ignore", invalid="ignore"):
        hl2 = np.log(h / l) ** 2
        co2 = np.log(c / o) ** 2
    park = np.sqrt(pd.Series(hl2).rolling(20).mean().to_numpy() / (4 * np.log(2)))
    gk = np.sqrt(np.clip(pd.Series(0.5 * hl2 - (2 * np.log(2) - 1) * co2).rolling(20).mean().to_numpy(), 0, None))
    F["park20"] = park / unit
    F["gk20"] = gk / unit
    dl = np.r_[np.nan, np.diff(np.log(c))]
    sq = dl ** 2
    cs = np.r_[0.0, np.nancumsum(sq)]
    for w, nm in ((1, "rv_p1"), (k, "rv_pk"), (5 * k, "rv_p5k")):
        s = np.full(len(c), np.nan)
        s[w:] = cs[w + 1:] - cs[1:-w] if w < len(c) else np.nan
        F[nm] = s / unit ** 2
    hr = (ts // 3600) % 24
    F["hour"] = hr.astype(float)
    F["hsin"] = np.sin(2 * np.pi * hr / 24)
    F["hcos"] = np.cos(2 * np.pi * hr / 24)
    F["dow"] = ((ts // 86400 + 3) % 7).astype(float)
    F["s_asia"] = (hr < 7).astype(float)
    F["s_london"] = ((hr >= 7) & (hr < 12)).astype(float)
    F["s_overlap"] = ((hr >= 12) & (hr < 16)).astype(float)
    F["s_ny"] = ((hr >= 16) & (hr < 21)).astype(float)
    F["rollover"] = rollover_open(ts).astype(float) if tf in ("15m", "1h") else np.zeros(len(ts))
    F["is_metal"] = np.full(len(c), float(is_metal))
    # S: slopes
    for L in LRC_L:
        s, r = lrc_stats(c, L)
        slope_block(f"lrc{L}", s, a, F)
        F[f"lrc{L}_R"] = r
        slope_block(f"cs{L}", (c - lag(c, L)) / L, a, F)
    for L in (20, 50):
        e = pd.Series(c).ewm(span=L, adjust=False).mean().to_numpy()
        slope_block(f"ema{L}", e - lag(e, 1), a, F)
    if tf in ("15m", "1h"):
        v4 = htf_slope(df, tf, "4h")
        vd = htf_slope(df, tf, "1d")
        F["mtf_4h"], F["mtf_1d"] = v4, vd
        F["mtf_4h_sgn"], F["mtf_1d_sgn"] = np.sign(v4), np.sign(vd)
        F["mtf_agree"] = np.sign(F["lrc50"]) + np.sign(v4) + np.sign(vd)
    elif tf == "4h":
        vd = htf_slope(df, tf, "1d")
        F["mtf_1d"], F["mtf_1d_sgn"] = vd, np.sign(vd)
        F["mtf_agree"] = np.sign(F["lrc50"]) + np.sign(vd)
    else:
        F["mtf_agree"] = sum(np.sign(F[f"lrc{L}"]) for L in LRC_L)
    # Q (amendment): polynomial fits of price
    polyfit_block(c, a, F)
    # C: context
    day = lambda t: t // 86400  # noqa: E731
    week = lambda t: (t // 86400 + 3) // 7  # noqa: E731
    for nm, key in (("pd", day), ("pw", week)):
        H, L_ = prior_hl(ts, h, l, key)
        F[f"{nm}h_d"] = (c - H) / a
        F[f"{nm}l_d"] = (c - L_) / a
    rngp = h - l
    with np.errstate(divide="ignore", invalid="ignore"):
        F["body"] = np.where(rngp > 0, (c - o) / rngp, 0.0)
        F["uwick"] = np.where(rngp > 0, (h - np.maximum(o, c)) / rngp, 0.0)
        F["lwick"] = np.where(rngp > 0, (np.minimum(o, c) - l) / rngp, 0.0)
        F["cloc"] = np.where(rngp > 0, (c - l) / rngp, 0.5)
    out = pd.DataFrame({k_: np.asarray(v, np.float32) for k_, v in F.items()})
    return out, a


# ------------------------------------------------------------------------------------------ targets

def mfe_side(o, h, l, c, a, cap=NR_CAP):
    """Long from O_{t+1} with a 3-bar structural stop: (MFE in R before the stop, risk in ATR,
    stopped flag, bars to stop). Up bars run O-L-H-C (stop checked first), down bars O-H-L-C."""
    n = len(c)
    E = np.r_[o[1:], np.nan]
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    stop = low3 - PAD * a
    risk = E - stop
    risk = np.where(risk < MIN_RISK * a, MIN_RISK * a, risk)
    stop = E - risk
    ok = np.isfinite(E) & np.isfinite(risk) & (risk > 0) & np.isfinite(a)
    mfe = np.where(ok, 0.0, np.nan)
    dead = ~ok
    stopped = np.zeros(n, bool)
    tstop = np.full(n, -1, np.int32)
    up = c >= o
    idx = np.flatnonzero(ok)
    for j in range(1, cap + 1):
        if not len(idx):
            break
        b = idx + j
        inb = b < n
        idx_out = idx[~inb]
        idx, b = idx[inb], b[inb]
        if not len(idx):
            break
        st = stop[idx]
        gap = o[b] <= st
        hit = l[b] <= st
        upb = up[b]
        fav = (h[b] - E[idx]) / risk[idx]
        # down bar: high first, then the low; up bar: low first
        take = ~gap & (~hit | ~upb)
        cur = mfe[idx]
        mfe[idx] = np.where(take, np.maximum(cur, fav), cur)
        die = gap | hit
        stopped[idx[die]] = True
        tstop[idx[die]] = j
        idx = idx[~die]
        del idx_out
    return mfe, risk / a, stopped, tstop


def targets(df, a, tf):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    k = K[tf]
    T = {}
    nxt = lambda x, j=1: np.r_[x[j:], np.full(j, np.nan)]  # noqa: E731
    T["range1"] = (nxt(h) - nxt(l)) / a
    T["absret1"] = np.abs(nxt(c) - c) / a
    dl = np.r_[np.nan, np.diff(np.log(c))]
    sq = dl ** 2
    cs = np.r_[0.0, np.cumsum(np.nan_to_num(sq))]
    rv = np.full(n, np.nan)
    if n > k:
        rv[:n - k] = cs[k + 1:n + 1] - cs[1:n - k + 1]
    T["rvk"] = rv / (a / c) ** 2
    for x, nm in ((0.5, "05"), (1.0, "10")):
        T[f"tup{nm}"] = np.where(np.isfinite(nxt(h)), (nxt(h) >= c + x * a).astype(float), np.nan)
        T[f"tdn{nm}"] = np.where(np.isfinite(nxt(l)), (nxt(l) <= c - x * a).astype(float), np.nan)
    first = np.full(n, np.nan)
    done = np.zeros(n, bool)
    for j in range(1, FIRST_H + 1):
        hj, lj = nxt(h, j), nxt(l, j)
        uh = hj >= c + a
        dh = lj <= c - a
        new = ~done & (uh | dh) & np.isfinite(hj)
        first[new & uh & dh] = np.nan
        first[new & uh & ~dh] = 1.0
        first[new & dh & ~uh] = 0.0
        done |= new
    T["first"] = first
    d1 = nxt(c) - c
    T["sign1"] = np.where(np.isfinite(d1) & (d1 != 0), (d1 > 0).astype(float), np.nan)
    dk = nxt(c, SIGNK) - c
    T["signk"] = np.where(np.isfinite(dk) & (dk != 0), (dk > 0).astype(float), np.nan)
    mL, rL, sL, tL = mfe_side(o, h, l, c, a)
    mS, rS, sS, tS = mfe_side(-o, -l, -h, -c, a)
    T["mfeL"], T["riskL"], T["tstopL"] = mL, rL, tL.astype(float)
    T["mfeS"], T["riskS"], T["tstopS"] = mS, rS, tS.astype(float)
    T["nr2L"] = np.where(np.isfinite(mL), (mL >= 2).astype(float), np.nan)
    T["nr2S"] = np.where(np.isfinite(mS), (mS >= 2).astype(float), np.nan)
    # resolution time (bars after t) of each label, for purging and online feedback
    tr = {"range1": 1, "absret1": 1, "rvk": k, "tup05": 1, "tdn05": 1, "tup10": 1, "tdn10": 1,
          "first": FIRST_H, "sign1": 1, "signk": SIGNK}
    out = pd.DataFrame({k_: np.asarray(v, np.float32) for k_, v in T.items()})
    # nr resolves at the stop (or the cap); take the cap where unresolved, entry needs one bar
    out["res_nrL"] = np.where(tL > 0, tL + 1, NR_CAP + 1).astype(np.int32)
    out["res_nrS"] = np.where(tS > 0, tS + 1, NR_CAP + 1).astype(np.int32)
    return out, tr


# ------------------------------------------------------------------------------------------ one series

def series_job(job):
    sym, tf, source = job
    cls = "FX" if sym in FX else "METAL" if sym in METAL else "HOLD"
    df, cost_px = (load_hold if cls == "HOLD" else load_main)(sym, tf)
    if df is None or len(df) < 600:
        return sym, tf, source, None, "no data"
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a_real = atr(h, l, c)
    cost_atr = cost_px / np.maximum(a_real, 1e-12)
    med = float(np.nanmedian(cost_atr[50:]))
    if not med <= MAX_COST_ATR:
        return sym, tf, source, None, f"dropped: cost {med:.2f} ATR"
    if source != "real":
        seed = zlib.crc32(f"{sym}{tf}{source}fxml".encode()) % 2**31
        df = make_walk(df, source, seed)
    F, a = features(df, tf, cls == "METAL")
    O = ohlc_block(df, a)
    T, tr = targets(df, a, tf)
    meta = pd.DataFrame({"sym": sym, "cls": cls, "ts": df["ts"].to_numpy(np.int64),
                         "bar": np.arange(len(df), dtype=np.int32),
                         "cost_atr": cost_atr.astype(np.float32), "atr": a.astype(np.float64),
                         "close": df["close"].to_numpy(float)})
    rows = pd.concat([meta, F, T], axis=1)
    rows = rows.iloc[120:].reset_index(drop=True)  # warm-up
    O = O.iloc[120:].reset_index(drop=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        rz = np.r_[np.nan, np.log((df["high"].to_numpy(float) - df["low"].to_numpy(float))[1:] / a[:-1])][120:]
    bars = df.assign(atr=a, cost_atr=cost_atr)
    return sym, tf, source, (rows, bars, tr, O, np.where(np.isfinite(rz), rz, np.nan)), \
        f"{len(rows)} rows, cost {med:.3f} ATR"


# ------------------------------------------------------------------------------------------ cross-sectional PCA

def pca_panel(series, tf, prefix="pc_"):
    """series: sym -> (ts, z), z the per-bar standardised value (close returns, or log range shocks).
    Returns sym -> DataFrame(ts, pca features named <prefix>*)."""
    W, R = PCA_W[tf], PCA_R[tf]
    grid = np.unique(np.concatenate([series[s][0] for s in series]))
    syms = list(series)
    members = [s for s in syms if s in MAIN]
    Z = np.full((len(grid), len(syms)), np.nan)
    for j, s in enumerate(syms):
        ts, z = series[s]
        Z[np.searchsorted(grid, ts), j] = z
    mi = np.array([syms.index(s) for s in members])
    feats = {nm: np.full((len(grid), len(syms)), np.nan) for nm in
             ("pc_b1", "pc_b2", "pc_b3", "pc_res", "pc_evr1", "pc_evr3", "pc_f1")}
    for tau in range(W, len(grid), R):
        win = Z[tau - W:tau]
        cov_ok = np.isfinite(win[:, mi]).mean(0) >= 0.9
        m = mi[cov_ok]
        if len(m) < 4:
            continue
        X = win[:, m]
        mu = np.nanmean(X, 0)
        sd = np.nanstd(X, 0)
        sd = np.where(sd > 0, sd, 1.0)
        Xs = np.nan_to_num((X - mu) / sd)
        C = Xs.T @ Xs / len(Xs)
        ev, V = np.linalg.eigh(C)
        order = np.argsort(ev)[::-1]
        ev, V = ev[order], V[:, order[:NPC]]
        V = V * np.where(V.sum(0) < 0, -1.0, 1.0)
        evr = ev / ev.sum()
        Fw = Xs @ V
        end = min(tau + R, len(grid))
        Xa = np.nan_to_num((Z[tau:end][:, m] - mu) / sd)
        Fa = Xa @ V
        for j in range(len(syms)):
            y = win[:, j]
            ok = np.isfinite(y)
            if ok.sum() < 0.5 * W:
                continue
            beta, *_ = np.linalg.lstsq(np.c_[np.ones(ok.sum()), Fw[ok]], y[ok], rcond=None)
            za = Z[tau:end, j]
            feats["pc_b1"][tau:end, j] = beta[1]
            feats["pc_b2"][tau:end, j] = beta[2]
            feats["pc_b3"][tau:end, j] = beta[3]
            feats["pc_res"][tau:end, j] = za - beta[0] - Fa @ beta[1:]
        feats["pc_evr1"][tau:end, :] = evr[0]
        feats["pc_evr3"][tau:end, :] = evr[:NPC].sum()
        feats["pc_f1"][tau:end, :] = Fa[:, 0][:, None]
    out = {}
    for j, s in enumerate(syms):
        ts = series[s][0]
        ix = np.searchsorted(grid, ts)
        d = pd.DataFrame({nm.replace("pc_", prefix): v[ix, j].astype(np.float32) for nm, v in feats.items()})
        res = pd.Series(d[f"{prefix}res"].to_numpy(float))
        d[f"{prefix}res5"] = res.rolling(5, min_periods=3).sum().to_numpy(np.float32)
        d[f"{prefix}res20"] = res.rolling(20, min_periods=10).sum().to_numpy(np.float32)
        d["ts"] = ts
        out[s] = d
    return out


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    tfs = os.environ.get("TFS", ",".join(TFS)).split(",")
    sources = os.environ.get("SOURCES", ",".join(SOURCES)).split(",")
    jobs = [(s, tf, src) for tf in tfs for src in sources for s in MAIN + HOLD]
    res = {}
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
        for sym, tf, src, r, msg in pool.map(series_job, jobs, chunksize=1):
            print(f"  {sym} {tf} {src}: {msg}", flush=True)
            if r is not None:
                res[(sym, tf, src)] = r
    for tf in tfs:
        for src in sources:
            keys = [k for k in res if k[1] == tf and k[2] == src]
            if not keys:
                continue
            series = {}
            for k in keys:
                b = res[k][1]
                c_, a_ = b["close"].to_numpy(float), b["atr"].to_numpy(float)
                series[k[0]] = (b["ts"].to_numpy(np.int64), np.r_[np.nan, np.diff(np.log(c_)) / (a_[:-1] / c_[:-1])])
            pc = pca_panel(series, tf)
            rseries = {k[0]: (res[k][0]["ts"].to_numpy(np.int64), res[k][4]) for k in keys}
            pr = pca_panel(rseries, tf, prefix="o_pr_")
            frames, oframes, bars, trs = [], [], {}, None
            for k in keys:
                rows, b, tr, O, _ = res[k]
                p = pc[k[0]].set_index("ts").loc[rows["ts"].to_numpy()].reset_index(drop=True)
                q = pr[k[0]].drop(columns="ts").reset_index(drop=True)
                frames.append(pd.concat([rows, p], axis=1))
                oframes.append(pd.concat([O, q], axis=1))
                bars[k[0]] = b
                trs = tr
            ds = pd.concat(frames, ignore_index=True)
            pd.to_pickle(dict(rows=ds, horizons=trs, tf=tf, source=src), OUT / f"ds_{tf}_{src}.pkl")
            pd.to_pickle(pd.concat(oframes, ignore_index=True), OUT / f"ds_{tf}_{src}_O.pkl")
            pd.to_pickle(bars, OUT / f"bars_{tf}_{src}.pkl")
            print(f"{tf} {src}: {len(ds)} rows, {ds.shape[1]} columns", flush=True)
    print("build done", flush=True)


if __name__ == "__main__":
    build()
