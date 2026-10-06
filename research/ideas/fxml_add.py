"""Second addendum (fxml_add_rule.json): returns and prices, range escapes, the forward trend.

MODE=targets builds OUT/ds2_<tf>_<source>.pkl, the new targets and family features aligned to the rows of
ds_<tf>_<source>.pkl (fxml_data.py). MODE=models fits each family and writes OUT/pred2/<tf>_<src>_<fam>.pkl.

  OUT=... MODE=targets|models [FAMS=ret,price,trend,band,range] python research/ideas/fxml_add.py
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
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fxml_data as D  # noqa: E402
import fxml_models as M  # noqa: E402

OUT = D.OUT
PRED2 = OUT / "pred2"
RET_H = (1, 3, 6, 12)
TREND_H = (5, 10, 20, 50, 100)
RANGE_L = (20, 50, 100)
KDAYS = {"15m": (96, 480, 1920), "1h": (24, 120, 480), "4h": (6, 30, 120), "1d": (1, 5, 20)}
FAMS = ("ret", "price", "trend", "trend2", "band", "range")


# ------------------------------------------------------------------------------------------ helpers

def fwd(x, h):
    return np.r_[x[h:], np.full(h, np.nan)] if h < len(x) else np.full(len(x), np.nan)


def roll_slope(y, L, w=None):
    """Rolling least-squares slope (per bar) and Pearson R of y on the bar index over windows ending at
    each bar; weighted by w when given. NaN before L-1."""
    n = len(y)
    s = np.full(n, np.nan)
    r = np.full(n, np.nan)
    if n < L:
        return s, r
    x = np.arange(L, dtype=float)
    Y = np.lib.stride_tricks.sliding_window_view(y, L)
    if w is None:
        xc = x - x.mean()
        m = Y.mean(1, keepdims=True)
        b = (Y - m) @ xc / (xc ** 2).sum()
        sy = Y.std(1)
        s[L - 1:] = b
        with np.errstate(divide="ignore", invalid="ignore"):
            r[L - 1:] = np.where(sy > 0, b * xc.std() / sy, 0.0)
        return s, r
    Wv = np.lib.stride_tricks.sliding_window_view(np.nan_to_num(w), L)
    sw = Wv.sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        mx = (Wv * x).sum(1) / sw
        my = (Wv * Y).sum(1) / sw
        cxy = (Wv * (x - mx[:, None]) * (Y - my[:, None])).sum(1)
        cxx = (Wv * (x - mx[:, None]) ** 2).sum(1)
        b = np.where((sw > 0) & (cxx > 0), cxy / cxx, np.nan)
    s[L - 1:] = b
    return s, r


def ewma_sigma(c):
    r = np.r_[0.0, np.diff(np.log(c))]
    e = pd.Series(r ** 2).ewm(alpha=1 - M.LAMBDA, adjust=False).mean().to_numpy()
    return np.sqrt(e)


def first_touch(h, l, up_level, dn_level, k):
    """Per bar t: whether H reaches up_level / L reaches dn_level within t+1..t+k, and which first
    (1 up, 0 down, NaN both in one bar or neither)."""
    n = len(h)
    up = np.zeros(n, bool)
    dn = np.zeros(n, bool)
    first = np.full(n, np.nan)
    done = np.zeros(n, bool)
    valid = np.arange(n) + k < n
    for j in range(1, k + 1):
        hj, lj = fwd(h, j), fwd(l, j)
        u = hj >= up_level
        d = lj <= dn_level
        up |= u & np.isfinite(hj)
        dn |= d & np.isfinite(lj)
        new = ~done & (u | d)
        first[new & u & ~d] = 1.0
        first[new & d & ~u] = 0.0
        done |= new
    upf = np.where(valid, up.astype(float), np.nan)
    dnf = np.where(valid, dn.astype(float), np.nan)
    first = np.where(valid, first, np.nan)
    return upf, dnf, first


def first_close_beyond(c, up_level, dn_level, k):
    """As first_touch, on closes: a close above up_level / below dn_level within k bars; and the bar of
    the first break (relative offset) for the excursion."""
    n = len(c)
    up = np.zeros(n, bool)
    dn = np.zeros(n, bool)
    first = np.full(n, np.nan)
    jfirst = np.full(n, -1, np.int32)
    done = np.zeros(n, bool)
    valid = np.arange(n) + k < n
    for j in range(1, k + 1):
        cj = fwd(c, j)
        u = cj > up_level
        d = cj < dn_level
        up |= u
        dn |= d
        new = ~done & (u | d)
        first[new & u] = 1.0
        first[new & d] = 0.0
        jfirst[new] = j
        done |= new
    return (np.where(valid, up.astype(float), np.nan), np.where(valid, dn.astype(float), np.nan),
            np.where(valid, first, np.nan), np.where(valid, jfirst, -1))


# ------------------------------------------------------------------------------------------ volume

def real_volume(sym, tf):
    """The bar volume (MT5 tick volume, or the exports' volume) on the real timestamps."""
    from mt5bt import load_bars
    try:
        if sym in D.INDEX_CSV:
            f = Path(D.DEEP2) / f"{D.INDEX_CSV[sym]}_1h_broker.csv.gz"
            df = pd.read_csv(f)[["ts", "volume"]].drop_duplicates("ts").sort_values("ts")
            if tf != "1h":
                df = df.groupby(df["ts"] // D.SEC[tf] * D.SEC[tf])["volume"].sum().rename_axis("ts").reset_index()
            return df
        if sym in D.HOLD:
            df = load_bars(sym, tf, "seqlab", D.SEQLAB)
        else:
            df = load_bars(sym, tf, "sqlite", os.environ.get("MT5BT_DB"))
        return df[["ts", "volume"]]
    except Exception:  # noqa: BLE001
        return None


def volume_for(bars, sym, tf, source):
    v = real_volume(sym, tf)
    ts = bars["ts"].to_numpy(np.int64)
    if v is None or not len(v):
        return np.full(len(ts), np.nan)
    real = v.set_index("ts")["volume"].reindex(ts).to_numpy(float)
    if source == "real":
        return real
    # walks: each bar's volume drawn from the real volumes at the same UTC hour (seeded)
    rng = np.random.default_rng(zlib.crc32(f"{sym}{tf}{source}vol".encode()) % 2**31)
    hr = (ts // 3600) % 24
    out = np.full(len(ts), np.nan)
    for hh in np.unique(hr):
        pool = real[(hr == hh) & np.isfinite(real)]
        m = hr == hh
        if len(pool):
            out[m] = rng.choice(pool, m.sum())
    return out


# ------------------------------------------------------------------------------------------ targets per series

def band_width(sym):
    """Frozen per instrument: the power of ten closest (in log) to 3 x the median daily ATR on real
    discovery bars."""
    b = pd.read_pickle(OUT / "bars_1d_real.pkl").get(sym)  # our own pickle
    if b is None or not len(b):
        b4 = pd.read_pickle(OUT / "bars_4h_real.pkl").get(sym)  # our own pickle
        if b4 is None:
            return np.nan
        a = float(np.nanmedian(b4["atr"][b4["ts"] < D.SPLIT])) * np.sqrt(6)
    else:
        sel = b["ts"] < D.SPLIT
        a = float(np.nanmedian(b["atr"][sel] if sel.any() else b["atr"]))
    return float(10 ** np.round(np.log10(3 * a)))


def series_targets(job):
    sym, tf, source, W = job
    bars = pd.read_pickle(OUT / f"bars_{tf}_{source}.pkl").get(sym)  # our own pickle
    if bars is None:
        return sym, None
    o, h, l, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = bars["atr"].to_numpy(float)
    n = len(c)
    T = {}
    # 2: returns and prices
    for hh in RET_H:
        T[f"ret{hh}"] = (fwd(c, hh) - c) / a
        T[f"lret{hh}"] = np.log(fwd(c, hh) / c)
    T["oc1"] = (fwd(c, 1) - fwd(o, 1)) / a
    T["hi1"] = (fwd(h, 1) - c) / a
    T["lo1"] = (fwd(l, 1) - c) / a
    T["mid1_up"] = np.where(np.isfinite(fwd(h, 1)), (((fwd(h, 1) + fwd(l, 1)) / 2) > c).astype(float), np.nan)
    sig = ewma_sigma(c) * c / a  # EWMA one-bar sigma in ATR units
    T["ewma_sig"] = sig
    # 5: forward trend on HLC3 (primary), OHLC4 (= the 4H-point line), volume-weighted HLC3, closes
    hlc3 = (h + l + c) / 3
    ohlc4 = (o + h + l + c) / 4
    vol = volume_for(bars, sym, tf, source)
    T["vol_cov"] = np.full(n, float(np.isfinite(vol).mean()))
    for H in TREND_H:
        s3, r3 = roll_slope(hlc3, H)
        s4, _ = roll_slope(ohlc4, H)
        sc, _ = roll_slope(c, H)
        sv, _ = roll_slope(hlc3, H, vol) if np.isfinite(vol).mean() > 0.9 else (np.full(n, np.nan), None)
        T[f"bk_slope{H}"], T[f"bk_R{H}"] = s3 / a, r3
        T[f"bk_ohlc{H}"], T[f"bk_close{H}"], T[f"bk_vw{H}"] = s4 / a, sc / a, sv / a
        fs3, fr3 = fwd(s3, H) / a, fwd(r3, H)
        T[f"tr_slope{H}"] = fs3
        T[f"tr_R{H}"] = fr3
        ok = np.isfinite(fs3)
        T[f"tr_sign{H}"] = np.where(ok & (fs3 != 0), (fs3 > 0).astype(float), np.nan)
        T[f"tr_clean{H}"] = np.where(np.isfinite(fr3), (np.abs(fr3) > 0.8).astype(float), np.nan)
        thr = 0.5 * np.sqrt(H)
        cls = np.where(ok, 1.0, np.nan)
        cls = np.where(ok & (fs3 * H >= thr) & (fr3 >= 0.5), 2.0, cls)
        cls = np.where(ok & (fs3 * H <= -thr) & (fr3 <= -0.5), 0.0, cls)
        T[f"tr_cls{H}"] = cls
        for nm, ss in (("ohlc", s4), ("close", sc), ("vw", sv)):
            f_ = fwd(ss, H)
            T[f"tr_{nm}{H}"] = np.where(np.isfinite(f_) & (f_ != 0), (f_ > 0).astype(float), np.nan)
    # 4: round-number bands
    k1, k5, k20 = KDAYS[tf]
    if np.isfinite(W):
        lo_b = np.floor(c / W) * W
        hi_b = lo_b + W
        T["bd_up_d"] = (hi_b - c) / a
        T["bd_dn_d"] = (c - lo_b) / a
        T["bd_pos"] = (c - lo_b) / W
        for k, nm in ((k1, "1d"), (k5, "5d"), (k20, "20d")):
            u, d, f = first_touch(h, l, hi_b, lo_b, k)
            T[f"bd_up_{nm}"], T[f"bd_dn_{nm}"], T[f"bd_first_{nm}"] = u, d, f
            sk = sig * np.sqrt(k)
            T[f"fp_bd_up_{nm}"] = np.clip(2 * (1 - norm.cdf(T["bd_up_d"] / sk)), 0, 1)
            T[f"fp_bd_dn_{nm}"] = np.clip(2 * (1 - norm.cdf(T["bd_dn_d"] / sk)), 0, 1)
            T[f"fp_bd_a_{nm}"] = T["bd_up_d"] / sk
            T[f"fp_bd_b_{nm}"] = T["bd_dn_d"] / sk
        # the round-number crowd test: touches of the next round / half level, and rejections
        prev = np.r_[np.nan, c[:-1]]
        a_prev = np.r_[np.nan, a[:-1]]
        for fam_, off in (("round", 0.0), ("half", 0.5)):
            lvl_up = (np.floor(prev / W - off) + 1 + off) * W
            lvl_dn = (np.ceil(prev / W - off) - 1 + off) * W
            tu = h >= lvl_up
            td = l <= lvl_dn
            T[f"rn_{fam_}_touch_up"] = tu.astype(float)
            T[f"rn_{fam_}_rej_up"] = np.where(tu, (c <= lvl_up - 0.25 * a_prev).astype(float), np.nan)
            T[f"rn_{fam_}_touch_dn"] = td.astype(float)
            T[f"rn_{fam_}_rej_dn"] = np.where(td, (c >= lvl_dn + 0.25 * a_prev).astype(float), np.nan)
    # 4: trading ranges
    for L in RANGE_L:
        HH = pd.Series(h).rolling(L).max().to_numpy()
        LL = pd.Series(l).rolling(L).min().to_numpy()
        T[f"rg{L}_up_d"] = (HH + 0.5 * a - c) / a
        T[f"rg{L}_dn_d"] = (c - (LL - 0.5 * a)) / a
        T[f"rg{L}_pos"] = (c - LL) / np.where(HH > LL, HH - LL, np.nan)
        ks = ((k1, "1d"), (k5, "5d"), (k20, "20d")) if L == 50 else ((k5, "5d"),)
        for k, nm in ks:
            u, d, f, jf = first_close_beyond(c, HH + 0.5 * a, LL - 0.5 * a, k)
            T[f"rg{L}_up_{nm}"], T[f"rg{L}_dn_{nm}"], T[f"rg{L}_first_{nm}"] = u, d, f
            sk = sig * np.sqrt(k)
            T[f"fp_rg{L}_up_{nm}"] = np.clip(2 * (1 - norm.cdf(T[f"rg{L}_up_d"] / sk)), 0, 1)
            T[f"fp_rg{L}_dn_{nm}"] = np.clip(2 * (1 - norm.cdf(T[f"rg{L}_dn_d"] / sk)), 0, 1)
            T[f"fp_rg{L}_a_{nm}"] = T[f"rg{L}_up_d"] / sk
            T[f"fp_rg{L}_b_{nm}"] = T[f"rg{L}_dn_d"] / sk
            if L == 50 and nm == "5d":
                exc = np.full(n, np.nan)
                for t in np.flatnonzero(jf > 0):
                    seg = c[t + jf[t]:t + k + 1]
                    if f[t] == 1:
                        exc[t] = (seg.max() - HH[t]) / a[t]
                    elif f[t] == 0:
                        exc[t] = (LL[t] - seg.min()) / a[t]
                T["rg50_exc_5d"] = exc
    out = pd.DataFrame({k_: np.asarray(v, np.float32) for k_, v in T.items()})
    out["bar"] = np.arange(n, dtype=np.int32)
    out["sym"] = sym
    return sym, out


def horizons(tf):
    k1, k5, k20 = KDAYS[tf]
    hz = {f"ret{h}": h for h in RET_H}
    hz.update(oc1=1, hi1=1, lo1=1, mid1_up=1)
    for H in TREND_H:
        for nm in ("slope", "R", "sign", "clean", "cls", "ohlc", "close", "vw"):
            hz[f"tr_{nm}{H}"] = H
    for k, nm in ((k1, "1d"), (k5, "5d"), (k20, "20d")):
        for s in ("up", "dn", "first"):
            hz[f"bd_{s}_{nm}"] = k
            hz[f"rg50_{s}_{nm}"] = k
    for L in (20, 100):
        for s in ("up", "dn", "first"):
            hz[f"rg{L}_{s}_5d"] = k5
    hz["rg50_exc_5d"] = k5
    return hz


def build_targets():
    PRED2.mkdir(parents=True, exist_ok=True)
    tfs = D.TFS
    widths = {}
    for tf in tfs:
        for src in D.SOURCES:
            d = pd.read_pickle(OUT / f"ds_{tf}_{src}.pkl")  # our own pickle
            rows = d["rows"][["sym", "bar"]]
            syms = list(rows["sym"].unique())
            for s in syms:
                if s not in widths:
                    widths[s] = band_width(s)
            jobs = [(s, tf, src, widths[s]) for s in syms]
            parts = []
            with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
                for sym, T in pool.map(series_targets, jobs):
                    if T is not None:
                        parts.append(T)
            T = pd.concat(parts, ignore_index=True)
            al = rows.merge(T, on=["sym", "bar"], how="left")
            pd.to_pickle(dict(rows=al.drop(columns=["sym", "bar"]), horizons=horizons(tf), widths=widths),
                         OUT / f"ds2_{tf}_{src}.pkl")
            print(f"{tf} {src}: {al.shape}", flush=True)
    print("targets done", flush=True)


# ------------------------------------------------------------------------------------------ models

def two_barrier_table(n_paths=20000, steps=256, grid=np.linspace(0.05, 4.0, 41), seed=11):
    """P(up first | a touch) for a driftless Brownian motion on [0, 1] with barriers +a and -b (in sigma
    sqrt(T) units), simulated; returns an interpolator over (a, b)."""
    from scipy.interpolate import RegularGridInterpolator
    rng = np.random.default_rng(seed)
    P = np.full((len(grid), len(grid)), 0.5)
    inc = rng.normal(0, 1 / np.sqrt(steps), (n_paths, steps))
    path = np.cumsum(inc, 1)
    runmax = np.maximum.accumulate(path, 1)
    runmin = np.minimum.accumulate(path, 1)
    for i, a in enumerate(grid):
        tu = np.where((runmax >= a).any(1), (runmax >= a).argmax(1), steps + 1)
        for j, b in enumerate(grid):
            td = np.where((runmin <= -b).any(1), (runmin <= -b).argmax(1), steps + 1)
            hit = (tu <= steps) | (td <= steps)
            P[i, j] = float(((tu < td) & hit).sum() / max(hit.sum(), 1))
    f = RegularGridInterpolator((grid, grid), P, bounds_error=False, fill_value=None)
    return lambda a, b: np.clip(f(np.c_[np.clip(a, grid[0], grid[-1]), np.clip(b, grid[0], grid[-1])]), 0, 1)


FAM_TARGETS = {
    "ret": [f"ret{h}" for h in RET_H] + ["oc1"],
    "price": ["hi1", "lo1", "mid1_up"],
    "trend": [f"tr_{nm}{H}" for H in TREND_H for nm in ("sign", "slope", "R", "clean", "cls")],
    "trend2": [f"tr_{nm}{H}" for H in TREND_H for nm in ("ohlc", "close", "vw")],
    "band": [f"bd_{s}_{k}" for k in ("1d", "5d", "20d") for s in ("up", "dn", "first")],
    "range": ([f"rg50_{s}_{k}" for k in ("1d", "5d", "20d") for s in ("up", "dn", "first")]
              + [f"rg{L}_{s}_5d" for L in (20, 100) for s in ("up", "dn", "first")] + ["rg50_exc_5d"]),
}
REG_T = {f"ret{h}" for h in RET_H} | {"oc1", "hi1", "lo1", "rg50_exc_5d"} | {f"tr_slope{H}" for H in TREND_H} | \
    {f"tr_R{H}" for H in TREND_H}


def res_times(rows, tf, hz):
    ts = rows["ts"].to_numpy(np.int64)
    res = {}
    idx = rows.groupby("sym", sort=False).indices
    for tgt, h in hz.items():
        out = np.full(len(rows), np.iinfo(np.int64).max, np.int64)
        for sym, ix in idx.items():
            ix = np.sort(ix)
            j = np.arange(len(ix)) + h
            ok = j < len(ix)
            out[ix[ok]] = ts[ix[j[ok]]]
        res[tgt] = out
    return res


def fam_job(spec):
    tf, src, fam = spec
    t0 = time.time()
    path = PRED2 / f"{tf}_{src}_{fam}.pkl"
    if path.exists():
        return f"{tf}_{src}_{fam}", "cached"
    d = pd.read_pickle(OUT / f"ds_{tf}_{src}.pkl")  # our own pickle
    rows = d["rows"].reset_index(drop=True)
    d2 = pd.read_pickle(OUT / f"ds2_{tf}_{src}.pkl")  # our own pickle
    T = d2["rows"].reset_index(drop=True)
    hz = d2["horizons"]
    feats = [c for c in rows.columns if c not in M.META and c not in M.TARGET_COLS and not c.startswith("pf")]
    extra = []
    if fam in ("trend", "trend2"):
        extra = [c for c in T.columns if c.startswith("bk_")]
    elif fam == "band":
        extra = ["bd_up_d", "bd_dn_d", "bd_pos", "ewma_sig"]
    elif fam == "range":
        extra = [c for c in T.columns if c.startswith("rg") and c.endswith(("_up_d", "_dn_d", "_pos"))] + ["ewma_sig"]
    elif fam in ("ret", "price"):
        extra = ["ewma_sig"]
    X = np.c_[rows[feats].to_numpy(np.float32), T[extra].to_numpy(np.float32)] if extra else \
        rows[feats].to_numpy(np.float32)
    tgts = [t for t in FAM_TARGETS[fam] if t in T.columns]
    res = res_times(rows, tf, {t: hz[t] for t in tgts})
    ts = rows["ts"].to_numpy(np.int64)
    out = dict(tf=tf, source=src, family=fam, targets={})
    fp_table = two_barrier_table() if fam in ("band", "range") else None
    for tgt in tgts:
        y = T[tgt].to_numpy(float)
        sp = M.splits(rows, res[tgt], y)
        if sp["fit"].sum() < 500:
            continue
        st = M.Std(X[sp["fit"]])
        Xs = st(X)
        P = {}
        info = {}
        if tgt in REG_T:
            m = M.hgb("reg", M.HGB_DEFAULT, "squared_error").fit(X[sp["fit"]], y[sp["fit"]])
            P["hgb"] = m.predict(X)
            from sklearn.linear_model import Ridge
            P["ridge"] = Ridge(alpha=1.0).fit(Xs[sp["fit"]], y[sp["fit"]]).predict(Xs)
            P["zero"] = np.zeros(len(y))
            P["histmean"] = np.full(len(y), float(np.mean(y[sp["fit"]])))
            if tgt.startswith("tr_slope"):
                P["persist"] = T[f"bk_slope{tgt[8:]}"].to_numpy(float)
            if tgt.startswith("tr_R"):
                P["persist"] = T[f"bk_R{tgt[4:]}"].to_numpy(float)
            if tgt in ("ret1", "hi1", "lo1"):
                P["sgd"] = M.online_sgd(Xs, y, ts, res[tgt], np.isfinite(y), "lin")
                # 90% intervals: HGB quantiles and an EWMA-sigma band, each under ACI
                ints = {}
                q = {}
                for qq in (0.05, 0.95):
                    mq = M.hgb("reg", M.HGB_DEFAULT, "quantile")
                    mq.set_params(quantile=qq)
                    q[qq] = mq.fit(X[sp["fit"]], y[sp["fit"]]).predict(X)
                ints["hgb"] = (np.minimum(q[0.05], q[0.95]), np.maximum(q[0.05], q[0.95]))
                sg = T["ewma_sig"].to_numpy(float)
                if tgt == "ret1":
                    base_c = np.zeros(len(y))
                else:
                    cfit = float(np.nanmean(y[sp["fit"]] / sg[sp["fit"]]))
                    base_c = cfit * sg
                    P["naive"] = base_c
                    info["naive_c"] = cfit
                z = (y - base_c) / sg
                zq = np.nanquantile(z[sp["fit"]], [0.05, 0.95])
                ints["ewma"] = (base_c + zq[0] * sg, base_c + zq[1] * sg)
                C = {}
                for nm, (lo, hi) in ints.items():
                    cq = M.cqr(rows, y, lo, hi, res[tgt], ts, sp["cal"], sp["conf"], sp["cal_main"])
                    C[nm] = {k: (a.astype(np.float32), b.astype(np.float32)) for k, (a, b) in cq.items()
                             if k in ("split", "aci")}
                info["cqr"] = C
        else:
            yy = y.astype(float)
            nclass = int(np.nanmax(yy)) + 1 if np.isfinite(yy).any() else 2
            mc = M.hgb("cls", M.HGB_DEFAULT).fit(X[sp["fit"]], yy[sp["fit"]].astype(int))
            pr = mc.predict_proba(X)
            from sklearn.linear_model import LogisticRegression
            lg = LogisticRegression(C=0.1, max_iter=300).fit(Xs[sp["fit"]], yy[sp["fit"]].astype(int))
            pl = lg.predict_proba(Xs)
            if nclass > 2:
                P["hgb"] = pr.astype(np.float32)
                P["logistic"] = pl.astype(np.float32)
                P["prior"] = np.tile(np.bincount(yy[sp["fit"]].astype(int), minlength=nclass) / sp["fit"].sum(),
                                     (len(yy), 1)).astype(np.float32)
                info["sets"] = multiclass_sets(P["hgb"], yy, sp)
            else:
                P["hgb"] = pr[:, 1]
                P["logistic"] = pl[:, 1]
                P["prior"] = np.full(len(yy), float(np.nanmean(yy[sp["fit"]])))
                if tgt.startswith("tr_") and tgt[3:].rstrip("0123456789") in ("sign", "ohlc", "close", "vw"):
                    nm = tgt[3:].rstrip("0123456789")
                    Hs = tgt[len("tr_") + len(nm):]
                    key = {"sign": "slope", "ohlc": "ohlc", "close": "close", "vw": "vw"}[nm]
                    P["persist"] = T[f"bk_{key}{Hs}"].to_numpy(float)
                if fam in ("band", "range"):
                    P.update(first_passage(T, tgt, fp_table, yy, sp))
                if tgt in ("tr_sign20", "bd_first_5d", "rg50_first_5d", "tr_sign5", "tr_sign100"):
                    cs = M.class_sets(rows, P["hgb"], yy, res[tgt], ts, sp["cal"], sp["conf"], sp["cal_main"])
                    info["sets"] = {k: (a, b) for k, (a, b) in cs.items()}
        out["targets"][tgt] = dict(pred={k: np.asarray(v, np.float32) for k, v in P.items()}, y=y.astype(np.float32),
                                   masks={k: v for k, v in sp.items() if k != "t80"}, **info)
    PRED2.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, path)
    return f"{tf}_{src}_{fam}", f"done in {time.time() - t0:.0f}s"


def first_passage(T, tgt, table, y, sp):
    """The first-passage baseline for a band / range target, Platt-recalibrated on the fit rows."""
    from sklearn.linear_model import LogisticRegression
    base = tgt.replace("bd_", "fp_bd_").replace("rg", "fp_rg", 1) if not tgt.startswith("fp") else tgt
    if "_first_" in tgt:
        a = T[base.replace("_first_", "_a_")].to_numpy(float)
        b = T[base.replace("_first_", "_b_")].to_numpy(float)
        p = table(np.nan_to_num(a, nan=4.0), np.nan_to_num(b, nan=4.0))
    else:
        p = T[base].to_numpy(float)
    p = np.clip(np.nan_to_num(p, nan=0.5), 1e-4, 1 - 1e-4)
    lg = np.log(p / (1 - p)).reshape(-1, 1)
    ok = sp["fit"] & np.isfinite(y)
    cal = LogisticRegression(C=1e6).fit(lg[ok], y[ok].astype(int)).predict_proba(lg)[:, 1]
    return {"fpass_raw": p, "fpass": cal}


def multiclass_sets(P, y, sp, alpha=M.ALPHA_SET):
    """Split-conformal sets for a 3-class label, score 1 - p(y): returns the included-class matrix."""
    ok = sp["cal_main"] & np.isfinite(y)
    s = 1 - P[ok, y[ok].astype(int)]
    q = M._quant(np.sort(s), 1 - alpha)
    return (1 - P) <= q


def run_models():
    PRED2.mkdir(parents=True, exist_ok=True)
    fams = os.environ.get("FAMS", ",".join(FAMS)).split(",")
    js = [(tf, src, f) for tf in D.TFS for src in D.SOURCES for f in fams]
    js.sort(key=lambda j: {"15m": 0, "1h": 0, "4h": 1, "1d": 2}[j[0]])
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 6))) as pool:
        for name, msg in pool.map(fam_job, js, chunksize=1):
            print(f"  {name}: {msg}", flush=True)
    print("models done", flush=True)


if __name__ == "__main__":
    mode = os.environ.get("MODE", "targets")
    if mode == "targets":
        build_targets()
    else:
        run_models()
