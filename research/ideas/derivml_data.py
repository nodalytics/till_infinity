"""Deriv synthetics for ML and adaptive conformal inference: registry, bars, nulls, features, targets.

Frozen in `derivml_rule.json` before any real-data run (see `research/docs/deriv-ml.md`). The Deriv twin of
fx-metals-ml: features() / ohlc_block() / targets() / pca_panel() are copied from `fxml_data.py` (that
worktree is never edited) with the substitutions the rule lists (class flags, the spike block J, the spike
target spk, per-series splits, no FX rollover trim).

One row per (series, bar t), for the real bars and for each group's nulls, written to

  OUT/ds_<tf>_<group>_<source>.pkl     the rows (features, targets, cost)
  OUT/ds_<tf>_<group>_<source>_O.pkl   the OHLC block (amendment O)
  OUT/bars_<tf>_<group>_<source>.pkl   the bars per series (for the trade translation)
  OUT/null/<source>_<slug>.npz         the null's day start levels (to regenerate its ticks for tick fills)

  OUT=... MODE=build GROUPS=DIFF,STEP,JUMPY,RB WORKERS=8 python research/ideas/derivml_data.py

Needs OUT/gen_params.json (derivml_gen.py MODE=gen, committed before any model run).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

TI = Path(os.environ.get("TI_HOME", os.path.expanduser("~/till_infinity")))
DDATA = Path(os.environ.get("DDATA", TI / "derivml" / "data"))
BCDATA = Path(os.environ.get("BCDATA", TI / "boomcrash" / "data"))
RBDATA = Path(os.environ.get("RBDATA", TI / "rb100" / "data"))
OUT = Path(os.environ.get("OUT", TI / "derivml" / "out"))

TFS = ("1h", "4h", "1d")
SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
K = {"15m": 16, "1h": 24, "4h": 6, "1d": 5}
SPLIT = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())
LATE = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp())
YEAR = 365 * 86400
MIN_BARS = 600
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
WARM = 120
RESET_X = 20.0
SPK_Q = 0.90

GROUPS = ("DIFF", "STEP", "JUMPY", "RB")
SOURCES = {"DIFF": ("real", "iid", "garch", "gen"), "STEP": ("real", "gen"), "JUMPY": ("real", "gen"),
           "RB": ("real", "gen")}
CLASSES = {"DIFF": ("VOL2", "VOL1", "VOLHF"), "STEP": ("STEP", "MSTEP", "SKEW"), "JUMPY": ("BC", "JUMP"),
           "RB": ("RB",)}


def registry():
    """symbol -> dict(group, cls, store, mult (log-price generator), sigma (named, DIFF/JUMP), side)."""
    R = {}
    for n in (5, 10, 15, 25, 30, 50, 75, 90, 100):
        R[f"Volatility {n} Index"] = dict(group="DIFF", cls="VOL2", store="d", mult=True, sigma=n / 100)
    for n in (5, 10, 15, 25, 30, 50, 75, 90, 100, 150, 250):
        R[f"Volatility {n} (1s) Index"] = dict(group="DIFF", cls="VOL1", store="d", mult=True, sigma=n / 100)
    for n in (10, 25, 50, 75, 100):
        R[f"High Frequency Vol {n} Index"] = dict(group="DIFF", cls="VOLHF", store="d", mult=True, sigma=n / 100)
    for s in ("Step Index", "Step Index 200", "Step Index 300", "Step Index 400", "Step Index 500"):
        R[s] = dict(group="STEP", cls="STEP", store="d", mult=False)
    for n in (2, 3, 4):
        R[f"Multi Step {n} Index"] = dict(group="STEP", cls="MSTEP", store="d", mult=False)
    for s in ("4 Up", "4 Down", "5 Up", "5 Down"):
        R[f"Skew Step Index {s}"] = dict(group="STEP", cls="SKEW", store="d", mult=False)
    for kind, side in (("Boom", 1), ("Crash", -1)):
        for n in (300, 500, 1000):
            R[f"{kind} {n} Index"] = dict(group="JUMPY", cls="BC", store="bc", mult=True, side=side)
    for n in (10, 25, 50, 75, 100):
        R[f"Jump {n} Index"] = dict(group="JUMPY", cls="JUMP", store="d", mult=True, sigma=n / 100, side=0)
    for n in (100, 200):
        R[f"Range Break {n} Index"] = dict(group="RB", cls="RB", store="rb", mult=False)
    return R


REG = registry()


def slug(sym):
    return (sym.lower().replace(" index", "").replace("(1s)", "1s").replace("  ", " ").strip()
            .replace(" ", "_"))


def tick_dir(sym):
    r = REG[sym]
    if r["store"] == "bc":
        return BCDATA / "ticks" / sym.lower().replace(" index", "").replace(" ", "_")
    if r["store"] == "rb":
        return RBDATA / "ticks" / sym.split()[2]
    return DDATA / "ticks" / slug(sym)


def bar_db(sym):
    st = REG[sym]["store"]
    return {"d": DDATA / "bars.db", "bc": BCDATA / "bars.db", "rb": RBDATA / "rb_bars.db"}[st]


def load_bars(sym, tf):
    con = sqlite3.connect(f"file:{bar_db(sym)}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(bars)")]
        sp = ", spread" if "spread" in cols else ""
        d = pd.read_sql_query(f"SELECT ts, open, high, low, close{sp} FROM bars WHERE symbol = ? AND interval = ? "
                              "ORDER BY ts", con, params=(sym, tf))
    finally:
        con.close()
    d = d.drop_duplicates("ts").reset_index(drop=True)
    d = d[(d[["open", "high", "low", "close"]] > 0).all(1)].reset_index(drop=True)
    d["ts"] = d["ts"].astype(np.int64)
    return d


def split_ts(ts):
    """Rule: 2024-01-01 when the series starts before 2023-01-01, else the UTC day at its midpoint."""
    ts = np.asarray(ts, np.int64)
    if ts[0] < LATE:
        return SPLIT
    return int(round((ts[0] + ts[-1]) / 2 / 86400)) * 86400


def load_ticks(sym, days=None):
    """[(day, ms, bid, ask)] of the fetched UTC days (np.load of our own / the stores' npz arrays)."""
    out = []
    for f in sorted(tick_dir(sym).glob("*.npz")):
        day = int(np.datetime64(f.stem, "D").astype(np.int64))
        if days is not None and day not in days:
            continue
        z = np.load(f)
        if len(z["ms"]):
            ok = (z["bid"] > 0) & (z["ask"] > 0)
            out.append((day, z["ms"][ok], z["bid"][ok], z["ask"][ok]))
    return out


def gen_params():
    return json.loads((OUT / "gen_params.json").read_text())


# ------------------------------------------------------------------------------------------ fxml copies

def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def lrc(c, L, chunk=20000):
    """lrc_retest.lrc, copied (slope per bar)."""
    c = np.asarray(c, float)
    n = len(c)
    slope = np.full(n, np.nan)
    if n < L:
        return slope
    x = np.arange(L, dtype=float)
    xc = x - x.mean()
    sxx = float((xc ** 2).sum())
    W = np.lib.stride_tricks.sliding_window_view(c, L)
    for s in range(0, len(W), chunk):
        w = W[s:s + chunk]
        m = w.mean(1)
        slope[L - 1 + s:L - 1 + s + len(w)] = (w - m[:, None]) @ xc / sxx
    return slope


def lrc_stats(c, L):
    slope = lrc(c, L)
    x = np.arange(L, dtype=float)
    sx = float(x.std())
    sy = pd.Series(c).rolling(L).std(ddof=0).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(sy > 0, slope * sx / sy, 0.0)
    return slope, r


def polyfit_block(c, a, F, prefix="pf"):
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
            pre = f"{prefix}{L}_{deg}"
            F[f"{pre}_slope"] = pad(B[:, 1] / L) / a
            F[f"{pre}_curv"] = pad(2 * B[:, 2] / L ** 2) / a
            if deg == 3:
                F[f"{pre}_jerk"] = pad(6 * B[:, 3] / L ** 3) / a
            F[f"{pre}_resid"] = (c - pad(B[:, 0])) / a
            ext = (np.vander(np.array([1.0 / L]), deg + 1, increasing=True) @ B.T)[0]
            F[f"{pre}_ext1"] = (pad(ext) - c) / a
            with np.errstate(divide="ignore", invalid="ignore"):
                F[f"{pre}_r2"] = pad(np.where(ss_tot > 0, 1 - ss_res / ss_tot, 0.0))


def lag(x, k):
    out = np.full_like(x, np.nan)
    if k < len(x):
        out[k:] = x[:-k] if k else x
    return out


def slope_block(name, s, a, F):
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
    """fxml amendment O, copied."""
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
    hs = SEC[htf]
    r = resample(df, hs)
    hh, hl, hc = (r[k].to_numpy(float) for k in ("high", "low", "close"))
    s = lrc(hc, 50)
    v = s / atr(hh, hl, hc)
    end_h = r["ts"].to_numpy(np.int64) + hs
    end_b = df["ts"].to_numpy(np.int64) + SEC[tf]
    j = np.searchsorted(end_h, end_b, side="right") - 1
    return np.where(j >= 0, v[np.clip(j, 0, None)], np.nan)


def prior_hl(ts, h, l, key):
    k = key(ts)
    u, inv = np.unique(k, return_inverse=True)
    ph = pd.Series(h).groupby(inv).max().to_numpy()
    pl = pd.Series(l).groupby(inv).min().to_numpy()
    prev = inv - 1
    ok = prev >= 0
    H = np.where(ok, ph[np.clip(prev, 0, None)], np.nan)
    L = np.where(ok, pl[np.clip(prev, 0, None)], np.nan)
    return H, L


def excursion(df, side):
    """The spike-side excursion of each bar: H - O (Boom), O - L (Crash), max of both (Jump)."""
    o, h, l = (df[k].to_numpy(float) for k in ("open", "high", "low"))
    if side > 0:
        return h - o
    if side < 0:
        return o - l
    return np.maximum(h - o, o - l)


def features(df, tf, sym, split, step=1.0):
    """fxml features() with the rule's substitutions: class flags (+ log nominal sigma / step size) for
    is_metal, rollover 0, and the spike block J on JUMPY."""
    r = REG[sym]
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy(np.int64)
    k = K[tf]
    a = atr(h, l, c)
    a = np.where(a > 0, a, np.nan)
    F = {}
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
    F["rollover"] = np.zeros(len(ts))
    for cl in CLASSES[r["group"]]:
        F[f"is_{cl}"] = np.full(len(c), float(r["cls"] == cl))
    if r["group"] == "DIFF":
        F["lsig_name"] = np.full(len(c), np.log(r["sigma"]))
    if r["group"] == "JUMPY":
        F["side"] = np.full(len(c), float(r["side"]))
    if r["group"] == "STEP":
        F["lstep"] = np.log(float(step) / c)
    # S: slopes
    for L in LRC_L:
        s, rr = lrc_stats(c, L)
        slope_block(f"lrc{L}", s, a, F)
        F[f"lrc{L}_R"] = rr
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
    polyfit_block(c, a, F)
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
    q90 = np.nan
    if r["group"] == "JUMPY":
        e = excursion(df, r["side"]) / a
        disc = ts < split
        q90 = float(np.nanquantile(e[disc][WARM:], SPK_Q)) if (disc.sum() > WARM + 50) else float(np.nanquantile(e, SPK_Q))
        spike = (e >= q90).astype(float)
        idx = np.arange(len(c))
        last = np.where(spike > 0, idx, -1)
        last = np.maximum.accumulate(last)
        F["j_since"] = np.where(last >= 0, idx - last, np.nan)
        F["j_n20"] = pd.Series(spike).rolling(20, min_periods=1).sum().to_numpy()
        F["j_n100"] = pd.Series(spike).rolling(100, min_periods=1).sum().to_numpy()
        lastsize = pd.Series(np.where(spike > 0, e, np.nan)).ffill().to_numpy()
        F["j_last"] = lastsize
        F["j_e"] = e
    out = pd.DataFrame({k_: np.asarray(v, np.float32) for k_, v in F.items()})
    return out, a, q90


# ------------------------------------------------------------------------------------------ targets (fxml)

def mfe_side(o, h, l, c, a, cap=NR_CAP):
    n = len(c)
    E = np.r_[o[1:], np.nan]
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    stop = low3 - PAD * a
    risk = E - stop
    risk = np.where(risk < MIN_RISK * a, MIN_RISK * a, risk)
    stop = E - risk
    ok = np.isfinite(E) & np.isfinite(risk) & (risk > 0) & np.isfinite(a)
    mfe = np.where(ok, 0.0, np.nan)
    stopped = np.zeros(n, bool)
    tstop = np.full(n, -1, np.int32)
    up = c >= o
    idx = np.flatnonzero(ok)
    for j in range(1, cap + 1):
        if not len(idx):
            break
        b = idx + j
        inb = b < n
        idx, b = idx[inb], b[inb]
        if not len(idx):
            break
        st = stop[idx]
        gap = o[b] <= st
        hit = l[b] <= st
        upb = up[b]
        fav = (h[b] - E[idx]) / risk[idx]
        take = ~gap & (~hit | ~upb)
        cur = mfe[idx]
        mfe[idx] = np.where(take, np.maximum(cur, fav), cur)
        die = gap | hit
        stopped[idx[die]] = True
        tstop[idx[die]] = j
        idx = idx[~die]
    return mfe, risk / a, stopped, tstop


def targets(df, a, tf, sym, q90):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    k = K[tf]
    T = {}
    nxt = lambda x, j=1: np.r_[x[j:], np.full(j, np.nan)]  # noqa: E731
    T["range1"] = (nxt(h) - nxt(l)) / a
    T["absret1"] = np.abs(nxt(c) - c) / a
    dl = np.r_[np.nan, np.diff(np.log(c))]
    cs = np.r_[0.0, np.cumsum(np.nan_to_num(dl ** 2))]
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
    tr = {"range1": 1, "absret1": 1, "rvk": k, "tup05": 1, "tdn05": 1, "tup10": 1, "tdn10": 1,
          "first": FIRST_H, "sign1": 1, "signk": SIGNK}
    if REG[sym]["group"] == "JUMPY":
        e1 = nxt(excursion(df, REG[sym]["side"])) / a
        T["spk"] = np.where(np.isfinite(e1), (e1 >= q90).astype(float), np.nan)
        tr["spk"] = 1
    out = pd.DataFrame({k_: np.asarray(v, np.float32) for k_, v in T.items()})
    out["res_nrL"] = np.where(tL > 0, tL + 1, NR_CAP + 1).astype(np.int32)
    out["res_nrS"] = np.where(tS > 0, tS + 1, NR_CAP + 1).astype(np.int32)
    return out, tr


# ------------------------------------------------------------------------------------------ nulls

def seed_of(sym, src):
    return zlib.crc32(f"{sym}{src}derivml".encode()) % 2**31


def make_walk(df, kind, seed):
    """fxml's matched walk in log price on the real timestamps: iid or GARCH(1,1), 256 sub-steps."""
    from mcfl import synth
    c = df["close"].to_numpy(float)
    sig = float(np.std(np.diff(np.log(c))))
    n = len(df)
    gen = synth.walk if kind == "iid" else synth.garch
    w = gen(n, sigma=sig, seed=seed, steps=WALK_STEPS).reset_index(drop=True).iloc[:n]
    out = pd.DataFrame({"ts": df["ts"].to_numpy(np.int64)})
    for k_ in ("open", "high", "low", "close"):
        out[k_] = c[0] * np.exp(w[k_].to_numpy(float) - synth.START)
    return out


class TickGen:
    """A generator's ticks on a continuous calendar, one UTC day per rng stream (seeded by (seed, day)),
    so any day can be regenerated from its start level. kind: gbm | step | bc | jump (rb: see rb_path)."""

    def __init__(self, sym, prm, seed):
        self.sym, self.p, self.seed = sym, prm, seed
        self.dt = float(prm["dt_s"])                       # seconds between ticks
        self.n = int(round(86400 / self.dt))
        self.kind = prm["kind"]
        self.mult = REG[sym]["mult"]
        if self.kind == "bc":
            z = np.load(OUT / "gen" / f"bc_{slug(sym)}.npz")
            self.grind, self.J, self.ps = z["grind"], z["J"], float(prm["p"])
        if self.kind == "jump":
            z = np.load(OUT / "gen" / f"jump_{slug(sym)}.npz")
            self.J, self.pj, self.sd = z["J"], float(prm["p"]), float(prm["sd"])
        if self.kind == "step":
            self.vals, self.probs = np.asarray(prm["values"], float), np.asarray(prm["probs"], float)

    def increments(self, day):
        rng = np.random.default_rng([self.seed, int(day)])
        n = self.n
        if self.kind == "gbm":
            s = self.p["sigma"] * np.sqrt(self.dt / YEAR)
            return rng.normal(-0.5 * s * s, s, n)
        if self.kind == "step":
            return self.vals[rng.choice(len(self.vals), n, p=self.probs)]
        if self.kind == "bc":
            side = REG[self.sym]["side"]
            d = self.grind[rng.integers(0, len(self.grind), n)]
            sp = rng.random(n) < self.ps
            m = int(sp.sum())
            if m:
                d[sp] = side * self.J[rng.integers(0, len(self.J), m)]
            return d
        if self.kind == "jump":
            d = rng.normal(0.0, self.sd, n)
            jp = rng.random(n) < self.pj
            m = int(jp.sum())
            if m:
                d[jp] += self.J[rng.integers(0, len(self.J), m)]
            return d
        raise ValueError(self.kind)

    def day_path(self, day, level):
        inc = self.increments(day)
        if self.mult:
            return level * np.exp(np.cumsum(inc))
        return level + np.cumsum(inc)

    def hourly(self, day0, day1, start):
        """Hourly OHLC from day0 to day1 (exclusive) and the start level of each day. The first tick of a
        day is the first step from the previous day's last price."""
        nd = day1 - day0
        H = np.empty((nd * 24, 4))
        lev = np.empty(nd)
        px = start
        for i, d in enumerate(range(day0, day1)):
            lev[i] = px
            P = self.day_path(d, px).reshape(24, -1)
            H[i * 24:(i + 1) * 24] = np.c_[P[:, 0], P.max(1), P.min(1), P[:, -1]]
            px = P[-1, -1]
        ts = (np.arange(day0 * 24, day1 * 24, dtype=np.int64)) * 3600
        return ts, H, lev

    def ticks(self, day, level):
        """(ms, bid) of one regenerated day."""
        P = self.day_path(day, level)
        ms = day * 86400000 + np.round(np.arange(self.n) * self.dt * 1000).astype(np.int64)
        return ms, P


def rb_path(sym, prm, nsec, seed, start):
    import rb100
    return rb100.rbsim(nsec, prm, seed, start=start)


def agg_hours(ts_h, H, sec):
    """Bars of `sec` seconds from hourly OHLC on a continuous hourly grid."""
    m = sec // 3600
    n = len(ts_h) // m * m
    k0 = np.flatnonzero(ts_h % sec == 0)
    if not len(k0):
        return np.zeros(0, np.int64), np.zeros((0, 4))
    a = k0[0]
    n = (len(ts_h) - a) // m * m
    R = H[a:a + n].reshape(-1, m, 4)
    out = np.c_[R[:, 0, 0], R[:, :, 1].max(1), R[:, :, 2].min(1), R[:, -1, 3]]
    return ts_h[a:a + n:m], out


def null_series(sym, real, prm):
    """The gen null of one series: dict tf -> bars at the real timestamps (continuous calendar path)."""
    seed = seed_of(sym, "gen")
    t0 = min(int(real[tf]["ts"].iloc[0]) for tf in real)
    t1 = max(int(real[tf]["ts"].iloc[-1]) + SEC[tf] for tf in real)
    day0, day1 = t0 // 86400, -(-t1 // 86400)
    first_tf = min(real, key=lambda tf: int(real[tf]["ts"].iloc[0]))
    start = float(real[first_tf]["open"].iloc[0])
    lev = None
    if prm["kind"] == "rb":
        nsec = (day1 - day0) * 86400
        P = rb_path(sym, prm["rbsim"], nsec, seed, start)
        Hh = P.reshape(-1, 3600)
        H = np.c_[Hh[:, 0], Hh.max(1), Hh.min(1), Hh[:, -1]]
        ts_h = np.arange(day0 * 24, day1 * 24, dtype=np.int64) * 3600
        tick0 = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp()) // 86400
        if day1 > tick0:
            a = max(tick0 - day0, 0) * 86400
            np.savez_compressed(OUT / "null" / f"gen_{slug(sym)}_sec.npz", day0=max(tick0, day0),
                                P=np.round(P[a:]).astype(np.int32))
    else:
        g = TickGen(sym, prm, seed)
        ts_h, H, lev = g.hourly(day0, day1, start)
        np.savez_compressed(OUT / "null" / f"gen_{slug(sym)}.npz", day0=day0, lev=lev, seed=seed)
    out = {}
    for tf, df in real.items():
        if tf == "1h":
            tsb, B = ts_h, H
        else:
            tsb, B = agg_hours(ts_h, H, SEC[tf])
        ix = np.searchsorted(tsb, df["ts"].to_numpy(np.int64))
        ok = (ix < len(tsb)) & (tsb[np.clip(ix, 0, len(tsb) - 1)] == df["ts"].to_numpy(np.int64))
        b = pd.DataFrame({"ts": df["ts"].to_numpy(np.int64)[ok]})
        for j, k_ in enumerate(("open", "high", "low", "close")):
            b[k_] = B[ix[ok], j]
        out[tf] = b
    return out


# ------------------------------------------------------------------------------------------ one series

def reset_bars(c, split_t, ts):
    """Feed resets: a bar-to-bar log move above RESET_X x the median absolute move of discovery bars."""
    d = np.abs(np.diff(np.log(c)))
    disc = ts[1:] < split_t
    med = np.median(d[disc]) if disc.sum() > 50 else np.median(d)
    return np.flatnonzero(d > RESET_X * med) + 1


def build_rows(sym, tf, df, cost_px, split, src, step=1.0, gen_v=np.nan, resets=()):
    F, a, q90 = features(df, tf, sym, split, step)
    O = ohlc_block(df, a)
    T, tr = targets(df, a, tf, sym, q90)
    ts = df["ts"].to_numpy(np.int64)
    cost_atr = cost_px / np.maximum(a, 1e-12) if np.ndim(cost_px) == 0 else cost_px
    r = REG[sym]
    meta = pd.DataFrame({"sym": sym, "cls": r["cls"], "ts": ts, "bar": np.arange(len(df), dtype=np.int32),
                         "split": np.int64(split), "cost_atr": np.asarray(cost_atr, np.float32),
                         "gen_v": (gen_v / df["close"].to_numpy(float) ** 2 if not r["mult"] else
                                   np.full(len(df), gen_v)).astype(np.float64),
                         "atr": a.astype(np.float64), "close": df["close"].to_numpy(float)})
    rows = pd.concat([meta, F, T], axis=1)
    keep = np.ones(len(rows), bool)
    keep[:WARM] = False
    if src == "real":
        H = max(K[tf], FIRST_H, SIGNK)
        js = sorted({int(j) for T in resets for j in np.flatnonzero((ts >= T - 14400) & (ts < T + 14400))})
        for j in js:
            keep[max(j - WARM, 0):j + 1] = False
            keep[max(j - H, 0):j] = False
            for side in "LS":
                rows.loc[max(j - NR_CAP, 0):j - 1, [f"nr2{side}", f"mfe{side}"]] = np.nan
    rows = rows[keep].reset_index(drop=True)
    O = O[keep].reset_index(drop=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = (df["high"].to_numpy(float) - df["low"].to_numpy(float))
        rz = np.r_[np.nan, np.log(hl[1:] / a[:-1])][keep]
    bars = df.assign(atr=a, cost_atr=np.asarray(cost_atr, float))
    return rows, bars, tr, O, np.where(np.isfinite(rz), rz, np.nan), q90


def series_job(job):
    """All timeframes and all sources of one series: dict (tf, src) -> build_rows output."""
    sym = job
    r = REG[sym]
    gp = gen_params()
    prm = gp["series"].get(sym)
    real = {}
    for tf in TFS:
        try:
            df = load_bars(sym, tf)
        except Exception:  # noqa: BLE001
            continue
        if len(df) >= MIN_BARS:
            real[tf] = df[["ts", "open", "high", "low", "close"]].reset_index(drop=True)
    if not real or prm is None:
        return sym, {}, f"no data ({len(real)} tfs, params {prm is not None})"
    cost_px = float(prm["spread"])
    res, msg = {}, []
    # feed resets (amended before any model run): found on the 4h bars, applied by time to every timeframe
    resets = []
    if "4h" in real:
        b4 = real["4h"]
        t4 = b4["ts"].to_numpy(np.int64)
        resets = [int(t4[j]) for j in reset_bars(b4["close"].to_numpy(float), split_ts(t4), t4)]
    srcs = SOURCES[r["group"]]
    nulls = null_series(sym, real, prm) if "gen" in srcs else {}
    for tf, df in real.items():
        h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
        a_real = atr(h, l, c)
        cost_atr = cost_px / np.maximum(a_real, 1e-12)
        med = float(np.nanmedian(cost_atr[50:]))
        if not med <= MAX_COST_ATR:
            msg.append(f"{tf} dropped: cost {med:.2f} ATR")
            continue
        split = split_ts(df["ts"].to_numpy(np.int64))
        if r["group"] == "DIFF":
            gen_v = r["sigma"] ** 2 * SEC[tf] / YEAR             # the published law, log units
        else:                                                    # the fitted null's own per-bar variance
            cn = nulls[tf]["close"].to_numpy(float)
            gen_v = float(np.mean(np.diff(np.log(cn)) ** 2)) if r["mult"] else float(np.mean(np.diff(cn) ** 2))
        step = float(prm.get("step", 1.0))
        for src in srcs:
            if src == "real":
                d2, ca = df, cost_atr
            elif src in ("iid", "garch"):
                d2 = make_walk(df, src, seed_of(sym, src + tf))
                ca = cost_atr
            else:
                d2 = nulls[tf]
                ix = np.searchsorted(df["ts"].to_numpy(np.int64), d2["ts"].to_numpy(np.int64))
                ca = cost_atr[ix]
            res[(tf, src)] = build_rows(sym, tf, d2.reset_index(drop=True), ca, split, src, step, gen_v, resets)
        msg.append(f"{tf} {len(df)} bars, {len(resets)} resets, split {pd.Timestamp(split, unit='s').date()}, cost {med:.3f} ATR")
    return sym, res, "; ".join(msg)


# ------------------------------------------------------------------------------------------ cross-sectional PCA

def pca_panel(series, tf, prefix="pc_"):
    """fxml's pca_panel with every series of the group's panel a member."""
    W, R = PCA_W[tf], PCA_R[tf]
    grid = np.unique(np.concatenate([series[s][0] for s in series]))
    syms = list(series)
    Z = np.full((len(grid), len(syms)), np.nan)
    for j, s in enumerate(syms):
        ts, z = series[s]
        Z[np.searchsorted(grid, ts), j] = z
    mi = np.arange(len(syms))
    feats = {nm: np.full((len(grid), len(syms)), np.nan) for nm in
             ("pc_b1", "pc_b2", "pc_b3", "pc_res", "pc_evr1", "pc_evr3", "pc_f1")}
    for tau in range(W, len(grid), R):
        win = Z[tau - W:tau]
        cov_ok = np.isfinite(win[:, mi]).mean(0) >= 0.9
        m = mi[cov_ok]
        if len(m) < 2:
            continue
        X = win[:, m]
        mu = np.nanmean(X, 0)
        sd = np.nanstd(X, 0)
        sd = np.where(sd > 0, sd, 1.0)
        Xs = np.nan_to_num((X - mu) / sd)
        C = Xs.T @ Xs / len(Xs)
        ev, V = np.linalg.eigh(C)
        order = np.argsort(ev)[::-1]
        npc = min(NPC, len(m))
        ev, V = ev[order], V[:, order[:npc]]
        V = V * np.where(V.sum(0) < 0, -1.0, 1.0)
        evr = ev / ev.sum()
        Fw = Xs @ V
        end = min(tau + R, len(grid))
        Fa = np.nan_to_num((Z[tau:end][:, m] - mu) / sd) @ V
        if npc < NPC:
            Fw = np.c_[Fw, np.zeros((len(Fw), NPC - npc))]
            Fa = np.c_[Fa, np.zeros((len(Fa), NPC - npc))]
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
    (OUT / "null").mkdir(parents=True, exist_ok=True)
    groups = os.environ.get("DGROUPS", ",".join(GROUPS)).split(",")
    for grp in groups:
        syms = [s for s, r in REG.items() if r["group"] == grp]
        res = {}
        info = {}
        with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
            for sym, r_, msg in pool.map(series_job, syms, chunksize=1):
                print(f"  {grp} {sym}: {msg}", flush=True)
                for key, v in r_.items():
                    res[(sym,) + key] = v
                    info.setdefault(sym, {})[key[0]] = dict(q90=v[5])
        for tf in TFS:
            for src in SOURCES[grp]:
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
                frames, oframes, bars, trs = [], [], {}, {}
                for k in keys:
                    rows, b, tr, O, _, _ = res[k]
                    p = pc[k[0]].set_index("ts").loc[rows["ts"].to_numpy()].reset_index(drop=True)
                    q = pr[k[0]].drop(columns="ts").reset_index(drop=True)
                    frames.append(pd.concat([rows, p], axis=1))
                    oframes.append(pd.concat([O, q], axis=1))
                    bars[k[0]] = b
                    trs.update(tr)
                ds = pd.concat(frames, ignore_index=True)
                pd.to_pickle(dict(rows=ds, horizons=trs, tf=tf, source=src, group=grp),
                             OUT / f"ds_{tf}_{grp}_{src}.pkl")
                pd.to_pickle(pd.concat(oframes, ignore_index=True), OUT / f"ds_{tf}_{grp}_{src}_O.pkl")
                pd.to_pickle(bars, OUT / f"bars_{tf}_{grp}_{src}.pkl")
                print(f"{grp} {tf} {src}: {len(ds)} rows, {ds.shape[1]} columns, {ds['sym'].nunique()} series",
                      flush=True)
                for k in keys:
                    del res[k]
        (OUT / f"build_{grp}.json").write_text(json.dumps(info, indent=1, default=float))
    print("build done", flush=True)


if __name__ == "__main__":
    if os.environ.get("MODE", "build") == "build":
        build()
