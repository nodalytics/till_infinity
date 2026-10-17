"""Deriv ML addendum (derivml_addendum.json): price and return regression, range-breakout first passage and the
forward trend, on the main datasets' rows, features, splits and nulls.

One job is (timeframe, group, source). It reads OUT/ds_<tf>_<group>_<source>.pkl and OUT/bars_*.pkl (our own
pickles, derivml_data.py) and writes OUT/add/<tf>_<group>_<source>.pkl: for every addendum target the label,
its resolution time, the masks, each model's prediction and the baselines (naive, persistence, first passage).
The first-passage baselines are learned on the gen null, so gen jobs run first (MODE=fp, then MODE=run).

  OUT=... MODE=fp|run DGROUPS=... TFS=... WORKERS=4 OMP_NUM_THREADS=1 python research/ideas/derivml_add.py
"""
from __future__ import annotations

import os
import pickle
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derivml_data as D  # noqa: E402
import derivml_models as M  # noqa: E402

OUT = D.OUT
ADD = OUT / "add"
SEED = 20261006
MAX_FIT = 200000
RET_K = (1, 3, 6, 12)
BAND_DAYS = (1, 5, 20)
RNG_DAYS = (1, 5)
RNG_L = (20, 50, 100)
TR_H = (5, 10, 20, 50, 100)
Z_CLS = 0.5


def kbars(tf, days):
    return max(1, int(round(days * 86400 / D.SEC[tf])))


# ------------------------------------------------------------------------------------------ helpers

def fwd_ext(x, k, fn):
    """fn (max / min) of x[t+1..t+k] for each t (NaN where the window runs off the end)."""
    n = len(x)
    out = np.full(n, np.nan)
    if n <= k:
        return out
    W = np.lib.stride_tricks.sliding_window_view(x[1:], k)  # W[t] = x[t+1..t+k]
    out[:len(W)] = fn(W, axis=1)
    return out


def first_hit(up_hit, dn_hit, k):
    """Which of two boolean bar series (hit at bar j) comes first in t+1..t+k: 1 up, 0 down, NaN if both on
    the same bar or neither."""
    n = len(up_hit)
    out = np.full(n, np.nan)
    done = np.zeros(n, bool)
    for j in range(1, k + 1):
        u = np.r_[up_hit[j:], np.zeros(j, bool)]
        d = np.r_[dn_hit[j:], np.zeros(j, bool)]
        new = ~done & (u | d)
        out[new & u & ~d] = 1.0
        out[new & d & ~u] = 0.0
        done |= new
    out[np.arange(n) + k >= n] = np.nan
    return out


def lrc_slope_r(x, L, w=None):
    """Rolling LRC(L) slope and Pearson R ending at each bar (optionally weighted)."""
    n = len(x)
    s = np.full(n, np.nan)
    r = np.full(n, np.nan)
    if n < L:
        return s, r
    t = np.arange(L, dtype=float)
    W = np.lib.stride_tricks.sliding_window_view(x, L)
    if w is None:
        tc = t - t.mean()
        xm = W.mean(1, keepdims=True)
        sxy = (W - xm) @ tc
        sxx = (tc ** 2).sum()
        syy = ((W - xm) ** 2).sum(1)
        s[L - 1:] = sxy / sxx
        with np.errstate(divide="ignore", invalid="ignore"):
            r[L - 1:] = np.where(syy > 0, sxy / np.sqrt(sxx * syy), 0.0)
        return s, r
    Wt = np.lib.stride_tricks.sliding_window_view(w, L).astype(float)
    Wt = Wt / np.maximum(Wt.sum(1, keepdims=True), 1e-12)
    tm = Wt @ t
    xm = (Wt * W).sum(1)
    tc = t[None, :] - tm[:, None]
    sxy = (Wt * tc * (W - xm[:, None])).sum(1)
    sxx = (Wt * tc ** 2).sum(1)
    s[L - 1:] = sxy / np.maximum(sxx, 1e-12)
    return s, r


def tick_volume(sym, tf, ts):
    """The bridge bars' tick_volume for the real series (NaN where absent)."""
    try:
        con = sqlite3.connect(f"file:{D.bar_db(sym)}?mode=ro", uri=True)
        cols = [r[1] for r in con.execute("PRAGMA table_info(bars)")]
        if "tick_volume" not in cols:
            return None
        d = pd.read_sql_query("SELECT ts, tick_volume FROM bars WHERE symbol = ? AND interval = ? ORDER BY ts", con,
                              params=(sym, tf)).drop_duplicates("ts")
        con.close()
    except Exception:  # noqa: BLE001
        return None
    v = d.set_index("ts")["tick_volume"].reindex(ts).to_numpy(float)
    return v


def band_width(b, tf, split):
    """The frozen round-number width: the power of ten nearest (log) to 4 median daily ATRs on discovery."""
    a = b["atr"].to_numpy(float)
    ts = b["ts"].to_numpy(np.int64)
    disc = ts < split
    da = np.nanmedian(a[disc] if disc.sum() > 50 else a) * np.sqrt(86400 / D.SEC[tf])
    m = np.round(np.log10(4 * da))
    return float(10 ** m)


# ------------------------------------------------------------------------------------------ targets

def series_targets(sym, tf, b, src, split, q90):
    """All addendum targets of one series (index = bar). Returns DataFrame of targets, a dict of horizons
    (bars to resolution) and extra columns (baselines, distance features, spike-window flags)."""
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = b["atr"].to_numpy(float)
    n = len(c)
    k = D.K[tf]
    T, X, hz = {}, {}, {}
    nxt = lambda x, j=1: np.r_[x[j:], np.full(j, np.nan)]  # noqa: E731
    # A: price
    T["c1"] = (nxt(c) - c) / a
    T["h1"] = (nxt(h) - c) / a
    T["l1"] = (nxt(l) - c) / a
    T["ck"] = (nxt(c, k) - c) / a
    hz.update(c1=1, h1=1, l1=1, ck=k)
    # C: returns (fit on the vol-scaled return; raw log returns kept for the metrics)
    lc = np.log(c)
    unit = a / c
    for kk in RET_K:
        T[f"lr{kk}"] = (nxt(lc, kk) - lc) / unit
        hz[f"lr{kk}"] = kk
    T["oc1"] = (np.log(nxt(c)) - np.log(nxt(o))) / unit
    hz["oc1"] = 1
    X["unit"] = unit
    # spike bars and their windows (JUMPY and RB)
    side = D.REG[sym].get("side", 0)
    e = D.excursion(b, side) / a
    spk = (e >= q90).astype(float) if np.isfinite(q90) else np.zeros(n)
    cs = np.r_[0.0, np.cumsum(spk)]
    for hh in sorted(set([1, k] + list(RET_K) + [kbars(tf, d) for d in BAND_DAYS + RNG_DAYS] + list(TR_H))):
        j = np.minimum(np.arange(n) + hh, n - 1)
        X[f"spkwin{hh}"] = (cs[j + 1] - cs[np.arange(n) + 1]) > 0
    # E: round-number bands
    W = band_width(b, tf, split)
    X["band_W"] = np.full(n, W)
    lo_b = np.floor(c / W) * W
    hi_b = lo_b + W
    for d in BAND_DAYS:
        kb = kbars(tf, d)
        mh, ml = fwd_ext(h, kb, np.max), fwd_ext(l, kb, np.min)
        T[f"bup{d}"] = np.where(np.isfinite(mh), (mh >= hi_b).astype(float), np.nan)
        T[f"bdn{d}"] = np.where(np.isfinite(ml), (ml < lo_b).astype(float), np.nan)
        # which first: hit at bar j means the bar reaches a level fixed at t; use per-bar comparisons
        up_lvl, dn_lvl = hi_b, lo_b
        T[f"bfirst{d}"] = _first_level(h, l, up_lvl, dn_lvl, kb, strict_dn=True)
        X[f"bdu{d}"] = (hi_b - c) / a / np.sqrt(kb)
        X[f"bdd{d}"] = (c - lo_b) / a / np.sqrt(kb)
        for nm in ("bup", "bdn", "bfirst"):
            hz[f"{nm}{d}"] = kb
    # E: trading ranges
    for L in RNG_L:
        hiL = pd.Series(h).rolling(L).max().to_numpy()
        loL = pd.Series(l).rolling(L).min().to_numpy()
        up_lvl, dn_lvl = hiL + 0.5 * a, loL - 0.5 * a
        for d in RNG_DAYS:
            kb = kbars(tf, d)
            mc, nc = fwd_ext(c, kb, np.max), fwd_ext(c, kb, np.min)
            T[f"rup{L}_{d}"] = np.where(np.isfinite(mc), (mc >= up_lvl).astype(float), np.nan)
            T[f"rdn{L}_{d}"] = np.where(np.isfinite(nc), (nc <= dn_lvl).astype(float), np.nan)
            T[f"rfirst{L}_{d}"] = _first_level(c, c, up_lvl, dn_lvl, kb, strict_dn=False)
            T[f"rext{L}_{d}"] = _extension(h, l, c, a, up_lvl, dn_lvl, kb)
            X[f"rdu{L}_{d}"] = (up_lvl - c) / a / np.sqrt(kb)
            X[f"rdd{L}_{d}"] = (c - dn_lvl) / a / np.sqrt(kb)
            for nm in ("rup", "rdn", "rfirst", "rext"):
                hz[f"{nm}{L}_{d}"] = kb
    # F: forward trend on HLC3 (primary), OHLC4 (= one regression through all four prices), close, tick volume
    p3 = (h + l + c) / 3
    p4 = (o + h + l + c) / 4
    vol = tick_volume(sym, tf, b["ts"].to_numpy(np.int64)) if src == "real" else None
    import lrc_retest as LR
    hi_p, lo_p = LR.pivots(h, l)
    st, _, _, _ = LR.structure(h, l, a, hi_p, lo_p)
    st = st.astype(float)
    for H in TR_H:
        s3, r3 = lrc_slope_r(p3, H)
        fs = nxt(s3, H) / a
        fr = nxt(r3, H)
        T[f"tr_sgn{H}"] = np.where(np.isfinite(fs) & (fs != 0), (fs > 0).astype(float), np.nan)
        T[f"tr_slope{H}"] = fs
        T[f"tr_R{H}"] = fr
        z = fs * (H - 1) / np.sqrt(H)
        T[f"tr_cls{H}"] = np.where(np.isfinite(z), np.where(z > Z_CLS, 2.0, np.where(z < -Z_CLS, 0.0, 1.0)), np.nan)
        T[f"tr_mcfl{H}"] = nxt(st, H) + 1.0                     # 0 down, 1 mixed, 2 up
        bs = s3 / a
        X[f"pers_slope{H}"] = bs
        X[f"pers_R{H}"] = r3
        zb = bs * (H - 1) / np.sqrt(H)
        X[f"pers_cls{H}"] = np.where(np.isfinite(zb), np.where(zb > Z_CLS, 2.0, np.where(zb < -Z_CLS, 0.0, 1.0)), np.nan)
        X[f"pers_mcfl{H}"] = st + 1.0
        for nm, px in (("ohlc", p4), ("close", c)):
            sv, _ = lrc_slope_r(px, H)
            fv = nxt(sv, H)
            T[f"tr_sgn{H}_{nm}"] = np.where(np.isfinite(fv) & (fv != 0), (fv > 0).astype(float), np.nan)
            X[f"pers_sgn{H}_{nm}"] = sv
        if vol is not None and np.isfinite(vol).mean() > 0.9:
            sv, _ = lrc_slope_r(p3, H, np.nan_to_num(vol, nan=np.nanmedian(vol)))
            fv = nxt(sv, H)
            T[f"tr_sgn{H}_vw"] = np.where(np.isfinite(fv) & (fv != 0), (fv > 0).astype(float), np.nan)
            X[f"pers_sgn{H}_vw"] = sv
        for nm in ("tr_sgn", "tr_slope", "tr_R", "tr_cls", "tr_mcfl"):
            hz[f"{nm}{H}"] = H
        for nm in ("ohlc", "close", "vw"):
            hz[f"tr_sgn{H}_{nm}"] = H
    if vol is not None:
        X["tickvol"] = vol
    return pd.DataFrame({k_: np.asarray(v, np.float32) for k_, v in T.items()}), hz, X


def _first_level(hp, lp, up, dn, k, strict_dn):
    n = len(hp)
    out = np.full(n, np.nan)
    done = np.zeros(n, bool)
    idx = np.arange(n)
    for j in range(1, k + 1):
        jj = np.minimum(idx + j, n - 1)
        u = hp[jj] >= up
        d = (lp[jj] < dn) if strict_dn else (lp[jj] <= dn)
        ok = idx + j < n
        new = ~done & (u | d) & ok
        out[new & u & ~d] = 1.0
        out[new & d & ~u] = 0.0
        done |= new
    out[idx + k >= n] = np.nan
    return out


def _extension(h, l, c, a, up, dn, k):
    """After the first close beyond up / dn within k bars, the largest further excursion beyond that level
    (in ATR_t) over the rest of the window. NaN where there is no break."""
    n = len(c)
    out = np.full(n, np.nan)
    idx = np.arange(n)
    first = np.full(n, -1)
    side = np.zeros(n)
    for j in range(1, k + 1):
        jj = np.minimum(idx + j, n - 1)
        ok = (idx + j < n) & (first < 0)
        u = ok & (c[jj] >= up)
        d = ok & (c[jj] <= dn) & ~u
        first[u | d] = j
        side[u] = 1
        side[d] = -1
    for t in np.flatnonzero(first > 0):
        j0, j1 = t + first[t], min(t + k, n - 1)
        if side[t] > 0:
            out[t] = (h[j0:j1 + 1].max() - up[t]) / a[t]
        else:
            out[t] = (dn[t] - l[j0:j1 + 1].min()) / a[t]
    out[idx + k >= n] = np.nan
    return out


# ------------------------------------------------------------------------------------------ assembly

def load(tf, grp, src):
    d = pd.read_pickle(OUT / f"ds_{tf}_{grp}_{src}.pkl")  # our own pickle
    rows = d["rows"].reset_index(drop=True)
    bars = pd.read_pickle(OUT / f"bars_{tf}_{grp}_{src}.pkl")  # our own pickle
    return rows, bars


def targets_for(tf, grp, src, rows, bars):
    frames, xs, hz = [], [], {}
    q90 = _q90(bars)
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        ix = np.sort(ix)
        b = bars[sym].reset_index(drop=True)
        split = int(rows["split"].iloc[ix[0]])
        T, h_, X = series_targets(sym, tf, b, src, split, q90.get(sym, np.nan))
        bi = rows["bar"].to_numpy()[ix]
        frames.append(T.iloc[bi].set_index(ix))
        xs.append(pd.DataFrame({k_: np.asarray(v)[bi] for k_, v in X.items()}, index=ix))
        hz.update(h_)
    T = pd.concat(frames).sort_index()
    X = pd.concat(xs).sort_index()
    return T, X, hz


def _q90(bars):
    """The J block's discovery 90th percentile of e/ATR per series (the same definition, applied to RB and
    to DIFF/STEP for the spike-bar flags)."""
    out = {}
    for sym, b in bars.items():
        a = b["atr"].to_numpy(float)
        ts = b["ts"].to_numpy(np.int64)
        e = D.excursion(b, D.REG[sym].get("side", 0)) / a
        split = D.split_ts(ts)
        disc = ts < split
        x = e[disc][D.WARM:] if disc.sum() > D.WARM + 50 else e
        out[sym] = float(np.nanquantile(x, D.SPK_Q))
    return out


def res_times(rows, hz):
    ts = rows["ts"].to_numpy(np.int64)
    res = {}
    groups = rows.groupby("sym", sort=False).indices
    for tgt, hh in hz.items():
        out = np.full(len(rows), np.iinfo(np.int64).max, np.int64)
        for sym, ix in groups.items():
            ix = np.sort(ix)
            j = np.arange(len(ix)) + hh
            ok = j < len(ix)
            out[ix[ok]] = ts[ix[j[ok]]]
        res[tgt] = out
    return res


# ------------------------------------------------------------------------------------------ models

def sub(fit):
    ix = np.flatnonzero(fit)
    if len(ix) <= MAX_FIT:
        return fit
    keep = np.zeros(len(fit), bool)
    keep[np.random.default_rng(SEED).choice(ix, MAX_FIT, replace=False)] = True
    return keep


def fit_hgb(kind, X, y, fit, cfg=None, nclass=2):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    cfg = dict(cfg or M.HGB_DEFAULT)
    fs = sub(fit)
    Xf = X[fs]
    dead = ~np.isfinite(Xf).any(0)
    Xa = X
    if dead.any():
        Xa = X.copy()
        Xa[:, dead] = 0.0
        Xf = Xa[fs]
    if kind == "reg":
        m = HistGradientBoostingRegressor(random_state=SEED, early_stopping=False, **cfg).fit(Xf, y[fs])
        return m.predict(Xa)
    m = HistGradientBoostingClassifier(random_state=SEED, early_stopping=False, **cfg).fit(Xf, y[fs].astype(int))
    P = m.predict_proba(Xa)
    return P[:, 1] if nclass == 2 else P


def fit_lin(kind, Xs, y, fit, nclass=2):
    from sklearn.linear_model import LogisticRegression, Ridge
    if kind == "reg":
        return Ridge(alpha=1.0).fit(Xs[fit], y[fit]).predict(Xs)
    m = LogisticRegression(C=0.1, max_iter=300).fit(Xs[fit], y[fit].astype(int))
    P = m.predict_proba(Xs)
    return P[:, 1] if nclass == 2 else P


def online_lin(Xs, y, ts, res_t, lab):
    """The main rule's online AdaGrad learner with an identity link (signed regression targets)."""
    n, p = Xs.shape
    w = np.zeros(p + 1)
    G = np.full(p + 1, 1e-8)
    order = np.argsort(ts, kind="stable")
    tsu, first = np.unique(ts[order], return_index=True)
    bounds = np.r_[first, len(order)]
    lo = np.flatnonzero(lab)
    lo = lo[np.argsort(res_t[lo], kind="stable")]
    rt = res_t[lo]
    ptr = 0
    pred = np.full(n, np.nan)
    for g in range(len(tsu)):
        k = np.searchsorted(rt, tsu[g], side="right")
        if k > ptr:
            ix = lo[ptr:k]
            ptr = k
            A = np.c_[Xs[ix], np.ones(len(ix))]
            err = A @ w - y[ix]
            grad = A.T @ err / len(ix) + M.SGD_L2 * w
            G += grad ** 2
            w -= M.SGD_LR * grad / np.sqrt(G)
        rix = order[bounds[g]:bounds[g + 1]]
        pred[rix] = np.c_[Xs[rix], np.ones(len(rix))] @ w
    return pred


def walk_fwd(X, y, ts, res_t, lab):
    pred = np.full(len(y), np.nan)
    t = pd.Timestamp(D.SPLIT, unit="s", tz="UTC")
    edges = []
    while t.timestamp() <= ts.max():
        edges.append(int(t.timestamp()))
        t = t + pd.DateOffset(months=M.WF_MONTHS)
    edges.append(int(ts.max()) + 1)
    for a_, b_ in zip(edges[:-1], edges[1:]):
        tr = lab & (res_t < a_)
        sc = (ts >= a_) & (ts < b_)
        if sc.any() and tr.sum() >= 200:
            pred[sc] = fit_hgb("reg", X, y, tr)[sc]
    return pred


KINDS = {}


def kind_of(tgt):
    if tgt.startswith(("c1", "h1", "l1", "ck", "lr", "oc1", "tr_slope", "tr_R", "rext")):
        return "reg"
    if tgt.startswith(("tr_cls", "tr_mcfl")):
        return "multi"
    return "cls"


def job(spec):
    tf, grp, src, mode = spec
    t0 = time.time()
    path = ADD / f"{tf}_{grp}_{src}.pkl"
    if mode == "run" and path.exists():
        return f"{tf}_{grp}_{src}: cached"
    rows, bars = load(tf, grp, src)
    T, Xx, hz = targets_for(tf, grp, src, rows, bars)
    res = res_times(rows, hz)
    feats = [c for c in rows.columns if c not in M.META and c not in M.TARGET_COLS and not c.startswith("pf")]
    ts = rows["ts"].to_numpy(np.int64)
    flags = [c for c in rows.columns if c.startswith("is_")]
    fpdir = ADD / "fp"
    fpdir.mkdir(parents=True, exist_ok=True)
    if mode == "fp":
        # first-passage baselines learned on the generator null (gen source only)
        from sklearn.ensemble import HistGradientBoostingClassifier
        fpm = {}
        for tgt in T.columns:
            if not tgt.startswith(("bup", "bdn", "bfirst", "rup", "rdn", "rfirst")):
                continue
            Z = fp_features(tgt, Xx, rows, flags)
            y = T[tgt].to_numpy(float)
            sp = M.splits(rows, res[tgt], y)
            fs = sub(sp["fit"])
            if fs.sum() < 200 or len(np.unique(y[fs])) < 2:
                continue
            fpm[tgt] = HistGradientBoostingClassifier(max_leaf_nodes=15, max_iter=200, learning_rate=0.05,
                                                      random_state=SEED).fit(Z[fs], y[fs].astype(int))
        with open(fpdir / f"{tf}_{grp}.pkl", "wb") as f:
            pickle.dump(fpm, f)
        return f"{tf}_{grp}_{src} fp: {len(fpm)} models in {time.time() - t0:.0f}s"
    with open(fpdir / f"{tf}_{grp}.pkl", "rb") as f:   # our own pickle (MODE=fp above)
        fpm = pickle.load(f)
    X = rows[feats].to_numpy(np.float32)
    out = dict(tf=tf, group=grp, source=src, targets={}, extra=Xx.astype(np.float32),
               sym=rows["sym"].to_numpy(), cls=rows["cls"].to_numpy(), ts=ts, hz=hz)
    for tgt in T.columns:
        y = T[tgt].to_numpy(float)
        if np.isfinite(y).sum() < 500:
            continue
        kind = kind_of(tgt)
        sp = M.splits(rows, res[tgt], y)
        fit, lab = sp["fit"], np.isfinite(y)
        if fit.sum() < 300 or (kind == "cls" and len(np.unique(y[fit])) < 2) or \
                (kind == "multi" and len(np.unique(y[fit])) < 3):
            continue
        P = {}
        extra_cols = []
        if tgt[:3] in ("bup", "bdn", "bfi") or tgt[:3] in ("rup", "rdn", "rfi", "rex"):
            Z = fp_features(tgt, Xx, rows, flags)
            extra_cols = Z
            Xa = np.c_[X, Z]
        else:
            Xa = X
        st = M.Std(Xa[fit])
        Xs = st(Xa)
        secondary = tgt.endswith(("_ohlc", "_close", "_vw"))
        if kind == "multi":
            P["hgb"] = fit_hgb("cls", Xa, y, fit, nclass=3).astype(np.float32)
            P["linear"] = fit_lin("cls", Xs, y, fit, nclass=3).astype(np.float32)
        elif kind == "cls":
            P["hgb"] = fit_hgb("cls", Xa, y, fit).astype(np.float32)
            if not secondary:
                P["linear"] = fit_lin("cls", Xs, y, fit).astype(np.float32)
            if tgt in fpm:
                P["fp"] = fpm[tgt].predict_proba(np.nan_to_num(extra_cols))[:, 1].astype(np.float32)
        else:
            P["hgb"] = fit_hgb("reg", Xa, y, fit).astype(np.float32)
            P["linear"] = fit_lin("reg", Xs, y, fit).astype(np.float32)
            if tgt in ("c1", "h1", "l1", "ck", "oc1") or tgt.startswith("lr"):
                P["wf"] = walk_fwd(Xa, y, ts, res[tgt], lab).astype(np.float32)
                P["sgd"] = online_lin(Xs, np.where(lab, y, 0.0), ts, res[tgt], lab).astype(np.float32)
                # baselines: naive (zero move / zero return) and the series' discovery fit-row mean
                mean = np.full(len(y), np.nan)
                for sym, ix in rows.groupby("sym", sort=False).indices.items():
                    f_ = ix[fit[ix]]
                    mean[ix] = np.nanmean(y[f_]) if len(f_) else 0.0
                P["mean"] = mean.astype(np.float32)
                P["naive"] = (mean if tgt in ("h1", "l1") else np.zeros(len(y))).astype(np.float32)
        tg = dict(y=y.astype(np.float32), res_t=res[tgt], kind=kind, pred=P,
                  masks={k_: v_ for k_, v_ in sp.items() if k_ != "t80"})
        if tgt == "c1" and "hgb" in P:
            tg["cqr"] = price_intervals(rows, Xa, y, fit, sp, res[tgt], ts)
        if kind == "cls" and tgt.startswith(("tr_sgn", "bup", "bdn", "rup", "rdn")) and not secondary:
            cs = M.class_sets(rows, P["hgb"].astype(float), y, res[tgt], ts, sp["cal"], sp["conf"], sp["cal_main"])
            tg["sets"] = {m_: (a_, b_) for m_, (a_, b_) in cs.items()}
        out["targets"][tgt] = tg
    ADD.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, path)
    return f"{tf}_{grp}_{src}: {len(out['targets'])} targets in {time.time() - t0:.0f}s"


def fp_features(tgt, Xx, rows, flags):
    """The first-passage features: distance up / down in ATR / sqrt(k), atr_ratio, lvol_z, class flags."""
    if tgt.startswith(("bup", "bdn", "bfirst")):
        d = tgt.lstrip("bupdnfirst")
        du, dd = Xx[f"bdu{d}"].to_numpy(float), Xx[f"bdd{d}"].to_numpy(float)
    else:
        key = tgt.lstrip("rupdnfirstext")
        du, dd = Xx[f"rdu{key}"].to_numpy(float), Xx[f"rdd{key}"].to_numpy(float)
    return np.c_[du, dd, rows["atr_ratio"].to_numpy(float), rows["lvol_z"].to_numpy(float),
                 rows[flags].to_numpy(float)].astype(np.float32)


def price_intervals(rows, X, y, fit, sp, res_t, ts):
    """CQR on c1 (HGB quantiles 0.05 / 0.95) and the naive interval (0 plus the fit-row residual quantiles),
    each with split / ACI / AgACI (the main rule's cqr)."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    fs = sub(fit)
    q = {}
    for a_ in (0.05, 0.95):
        m = HistGradientBoostingRegressor(loss="quantile", quantile=a_, random_state=SEED, early_stopping=False,
                                          **M.HGB_DEFAULT).fit(np.nan_to_num(X[fs], nan=np.nan), y[fs])
        q[a_] = m.predict(X)
    ints = {"hgb": (np.minimum(q[0.05], q[0.95]), np.maximum(q[0.05], q[0.95]))}
    r_ = y[fit & np.isfinite(y)]
    ints["naive"] = (np.full(len(y), np.quantile(r_, 0.05)), np.full(len(y), np.quantile(r_, 0.95)))
    C = {}
    for nm, (lo, hi) in ints.items():
        C[nm] = {m_: (a2.astype(np.float32), b2.astype(np.float32))
                 for m_, (a2, b2) in M.cqr(rows, y, lo, hi, res_t, ts, sp["cal"], sp["conf"], sp["cal_main"]).items()}
    return C


def main():
    mode = os.environ.get("MODE", "run")
    groups_ = os.environ.get("DGROUPS", ",".join(D.GROUPS)).split(",")
    tfs = os.environ.get("TFS", "1d,4h,1h").split(",")
    js = []
    for tf in tfs:
        for g in groups_:
            if not (OUT / f"ds_{tf}_{g}_real.pkl").exists():
                continue
            if mode == "fp":
                js.append((tf, g, "gen", "fp"))
            else:
                for s in D.SOURCES[g]:
                    js.append((tf, g, s, "run"))
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 4))) as pool:
        for msg in pool.map(job, js, chunksize=1):
            print("  " + msg, flush=True)
    print(f"add {mode} done", flush=True)


if __name__ == "__main__":
    main()
