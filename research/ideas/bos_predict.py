"""Can a break of structure be predicted before it happens?

Frozen in `bos_rule.json` before this ran on real data. At each sampled bar t with a live swing high H
(the most recent unbroken 3/3 swing high, so above the close) and a live swing low L, two targets:

  (a) timing  a close beyond H or L within N bars (24 on 1h, 12 on 4h)
  (b) side    given the first close beyond either comes within 60 bars, is it above H

Predicted by a standardised logistic regression from the geometry of H and L (G0, the baseline) and
from G0 plus each of: volatility compression (G1), "Levels Likely to Break" pressure (G2), Weinstein
stage (G3), the FVG magnet (G4), MCFL violence (G5) and the swing-label sentence (G6), and all of
them. Walk-forward (train before 2024-01-01, score after), per venue, 1h and 4h pooled. The same
pipeline runs on iid and GARCH walks matched to each series (256 sub-steps a bar, real timestamps,
synthetic volume from `mcfl.synth.ticks`). A group predicts only if its held-out AUC gain over G0 has
its day-bootstrap 90% interval above 0 and beats its gain on both walks.

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/bos_predict.py
  SMOKE=binance:BTC:4h:garch  runs one series and prints its rows
"""
from __future__ import annotations

import os
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

from turn_trade import COINS, MT5, SPLIT, _bin  # noqa: E402
from turn_zones import atr, load  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/bos"))
TFS = ("1h", "4h")
SEC = {"1h": 3600, "4h": 14400}
STRIDE = {"1h": 3, "4h": 1}
N_TIME = {"1h": 24, "4h": 12}
SIDE_WIN = 60
WARM = 300
WALK_STEPS = 256
SOURCES = ("real", "iid", "garch")
GROUPS = ("g1", "g2", "g3", "g4", "g5", "g6")
SETS = ("G0",) + tuple(f"G0+{g.upper()}" for g in GROUPS) + ("G0+all",)
LABELS = ("HH", "LH", "EH", "LL", "HL", "EL")
VIOL = ("DISPLACE_C", "DELIVERY_SHIFT", "BREACH_REVERT")
DRAWS = 1000
C_L2 = 1.0


# ------------------------------------------------------------------ series

def series(venue, sym, iv, source):
    from mcfl import synth
    df, _ = load(venue, sym, iv)
    if df is None or len(df) < 1000:
        return None
    df = df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"bos{venue}{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "iid" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=WALK_STEPS).iloc[:n].reset_index(drop=True)
        df = synth.ticks(df, seed=seed + 1)
        df["ts"] = ts[:len(df)]
    return df


def first_beyond(c, at, price, sign):
    """For each swing (bar `at`, `price`): the first later bar whose close is beyond it (n if none)."""
    n = len(c)
    out = np.full(len(at), n)
    for i, (p, px) in enumerate(zip(at, price)):
        for lo, hi in ((p + 1, min(n, p + 513)), (p + 513, n)):
            if lo >= hi:
                break
            hit = np.flatnonzero(sign * (c[lo:hi] - px) > 0)
            if len(hit):
                out[i] = lo + int(hit[0])
                break
    return out


def live_level(known, brk, n):
    """Per bar, the index of the most recent swing known by t and not yet broken (-1 if none).
    Swings are in bar order; a swing is pushed at its known_at and popped once its break bar is reached."""
    idx = np.full(n, -1)
    stack, k = [], 0
    for t in range(n):
        while k < len(known) and known[k] <= t:
            stack.append(k)
            k += 1
        while stack and brk[stack[-1]] <= t:
            stack.pop()
        if stack:
            idx[t] = stack[-1]
    return idx


def rolling_rank(x, w):
    return pd.Series(x).rolling(w, min_periods=w).rank(pct=True).to_numpy()


def weinstein(c, h, l, a14):
    n = len(c)
    sma = pd.Series(c).rolling(30).mean().to_numpy()
    slope = (sma - np.r_[np.full(4, np.nan), sma[:-4]]) / a14
    sd = pd.Series(slope).rolling(500, min_periods=100).std().shift(1).to_numpy()
    z = np.clip(np.nan_to_num(slope / sd), -5, 5)
    hi30 = pd.Series(h).rolling(30).max().shift(1).to_numpy()
    lo30 = pd.Series(l).rolling(30).min().shift(1).to_numpy()
    bo = np.nan_to_num(c > hi30).astype(bool)
    bd = np.nan_to_num(c < lo30).astype(bool)
    rising, falling = z > 0.5, z < -0.5
    stage, since = np.ones(n, int), np.zeros(n, int)
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
        stage[t], since[t] = s, t - enter
    pva = (c - sma) / a14
    return stage, since, z, pva, bo, bd


def fvg_features(o, h, l, c, a14, ts_idx):
    """FVG magnet features at the bars in ts_idx (sorted)."""
    n = len(c)
    gaps = []  # (k, type +1 up/-1 down, lo, hi, size_atr, fill_bar or -1)
    for k in range(2, n):
        if not a14[k] > 0:
            continue
        for typ, lo, hi in ((1, h[k - 2], l[k]), (-1, h[k], l[k - 2])):
            if hi - lo >= 0.25 * a14[k]:
                seg = slice(k + 1, min(n, k + 151))
                hit = np.flatnonzero(l[seg] <= lo) if typ > 0 else np.flatnonzero(h[seg] >= hi)
                fill = k + 1 + int(hit[0]) if len(hit) else -1
                gaps.append((k, typ, lo, hi, (hi - lo) / a14[k], fill))
    sb = lambda s: 0 if s < 0.5 else 1 if s < 1 else 2 if s < 2 else 3  # noqa: E731
    ab = lambda a: 0 if a < 10 else 1 if a < 50 else 2  # noqa: E731
    starts = (0, 10, 50)
    # resolution events, in time order: (bar resolved, key parts, fill age or None)
    res = sorted((((g[5] if g[5] >= 0 else g[0] + 150), g[1], sb(g[4]), (g[5] - g[0]) if g[5] >= 0 else None)
                  for g in gaps), key=lambda x: x[0])
    cnt, fil = {}, {}
    ri, gi = 0, 0
    live = []
    out = np.zeros((len(ts_idx), 11), np.float32)
    want = set(int(t) for t in ts_idx)
    row = 0
    for t in range(n):
        while gi < len(gaps) and gaps[gi][0] <= t:
            live.append(gaps[gi])
            gi += 1
        while ri < len(res) and res[ri][0] <= t:
            _, typ, s, fa = res[ri]
            for b, a0 in enumerate(starts):
                if fa is None or fa >= a0:
                    key = (typ, s, b)
                    cnt[key] = cnt.get(key, 0) + 1
                    fil[key] = fil.get(key, 0) + (fa is not None)
            ri += 1
        if t not in want:
            continue
        live = [g for g in live if (g[5] < 0 or g[5] > t) and t - g[0] < 150]
        best = {1: None, -1: None}
        for g in live:
            k, typ, lo, hi, size, _ = g
            pos = 1 if (lo + hi) / 2 > c[t] else -1
            d = max(0.0, (lo - c[t]) if pos > 0 else (c[t] - hi)) / a14[t]
            if best[pos] is None or d < best[pos][0]:
                best[pos] = (d, g)
        f = []
        pulls = []
        for pos in (1, -1):
            if best[pos] is None:
                f += [0, 10, 0, 0, 0]
                pulls.append(0.0)
                continue
            d, (k, typ, lo, hi, size, _) = best[pos]
            age = t - k
            key = (typ, sb(size), ab(age))
            fr = (1 + fil.get(key, 0)) / (2 + cnt.get(key, 0))
            f += [1, min(d, 10), min(size, 3), np.log1p(age), fr]
            pulls.append(fr / (1 + min(d, 10)))
        out[row] = f + [pulls[0] - pulls[1]]
        row += 1
    return out


FV4 = ["g4_has_ab", "g4_dist_ab", "g4_size_ab", "g4_age_ab", "g4_fr_ab",
       "g4_has_bl", "g4_dist_bl", "g4_size_bl", "g4_age_bl", "g4_fr_bl", "g4_pull"]


def build(df, iv):
    """One row per sampled bar: labels, levels and features (all known at t's close)."""
    from mcfl.parse import parse
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    a5, a14, a20, a50, a100 = (atr(df, k) for k in (5, 14, 20, 50, 100))
    ch = parse(df)
    up = lambda e: getattr(e.dir, "name", str(e.dir)).upper() == "UP"  # noqa: E731
    sh = sorted((e.at, e.known_at, e.get("price")) for e in ch.entities if e.type == "EXTREME" and up(e))
    sl = sorted((e.at, e.known_at, e.get("price")) for e in ch.entities if e.type == "EXTREME" and not up(e))
    sh_at, sh_kn, sh_px = (np.array(x) for x in zip(*sh))
    sl_at, sl_kn, sl_px = (np.array(x) for x in zip(*sl))
    sh_brk = first_beyond(c, sh_at, sh_px, 1)
    sl_brk = first_beyond(c, sl_at, sl_px, -1)
    hi_i, lo_i = live_level(sh_kn, sh_brk, n), live_level(sl_kn, sl_brk, n)
    # violence: each production's completion bar, per direction
    V = {}
    for p in VIOL:
        for d in ("up", "dn"):
            V[(p, d)] = np.zeros(n, bool)
    for e in ch.entities:
        if e.type in VIOL and 0 <= e.known_at < n:
            V[(e.type, "up" if up(e) else "dn")][e.known_at] = True
    V5 = {k: pd.Series(x.astype(float)).rolling(5, min_periods=1).max().to_numpy() for k, x in V.items()}
    rng_ = h - l
    rm = pd.Series(rng_).rolling(10).mean().shift(1).to_numpy()
    rs = pd.Series(rng_).rolling(10).std().shift(1).to_numpy()
    range_z = np.clip(np.nan_to_num((rng_ - rm) / np.where(rs > 0, rs, np.nan)), -10, 10)
    # swing sentence
    sw = sorted((e.known_at, e.at, e.get("label")) for e in ch.entities if e.type == "SWING")
    sw_kn = np.array([x[0] for x in sw])
    sw_lab = [x[2] for x in sw]
    # rolling helpers
    ser = lambda x: pd.Series(x)  # noqa: E731
    range10 = (ser(h).rolling(10).max() - ser(l).rolling(10).min()).to_numpy() / a50
    range5 = (ser(h).rolling(5).max() - ser(l).rolling(5).min()).to_numpy() / a14
    bbw = 4 * ser(c).rolling(20).std().to_numpy() / a50
    bbw_pct = rolling_rank(bbw, 100)
    vm = ser(v).rolling(20).mean().shift(1).to_numpy()
    rv = np.where(vm > 0, v / np.where(vm > 0, vm, 1), 1.0)
    clv = np.where(rng_ > 0, ((c - l) - (h - c)) / np.where(rng_ > 0, rng_, 1), 0.0)
    clv5 = ser(clv).rolling(5).mean().to_numpy()
    vclv5 = ser(rv * clv).rolling(5).mean().to_numpy()
    stage, since, sz, pva, bo, bd = weinstein(c, h, l, a14)

    ts = df["ts"].to_numpy()
    T = [t for t in range(WARM, n - SIDE_WIN - 1) if t % STRIDE[iv] == 0 and hi_i[t] >= 0 and lo_i[t] >= 0
         and a14[t] > 0 and a50[t] > 0]
    if not T:
        return None
    T = np.array(T)
    G4 = fvg_features(o, h, l, c, a14, T)
    rows = []
    for r, t in enumerate(T):
        i, j = hi_i[t], lo_i[t]
        H, L, A = sh_px[i], sl_px[j], a14[t]
        fut = c[t + 1:t + 1 + SIDE_WIN]
        u = np.flatnonzero(fut > H)
        dn = np.flatnonzero(fut < L)
        fu = u[0] + 1 if len(u) else 10 ** 6
        fd = dn[0] + 1 if len(dn) else 10 ** 6
        first = min(fu, fd)
        y_time = float(first <= N_TIME[iv])
        y_side = float(fu < fd) if first <= SIDE_WIN else np.nan
        dH, dL = (H - c[t]) / A, (c[t] - L) / A
        # repeated pivots: an earlier same-side swing within 100 bars of the level's, >= 5 bars from it
        def rep(at_arr, px_arr, k):
            m = (at_arr >= at_arr[k] - 100) & (at_arr <= at_arr[k] - 5) & (np.abs(px_arr - px_arr[k]) <= 0.25 * A)
            return float(m[:k].any())
        w5 = slice(t - 4, t + 1)
        near_h = h[w5] >= H - 0.5 * A
        near_l = l[w5] <= L + 0.5 * A
        shrink = np.maximum(0.0, 1 - rng_[w5] / A)
        w20 = slice(t - 19, t + 1)
        ns = np.searchsorted(sw_kn, t, side="right")
        last3 = sw_lab[max(0, ns - 3):ns]
        last3 = [None] * (3 - len(last3)) + last3
        f = {
            "g0_dH": dH, "g0_dL": dL, "g0_l1dH": np.log1p(dH), "g0_l1dL": np.log1p(dL),
            "g0_lr": np.log((dH + 0.05) / (dL + 0.05)), "g0_a5_a50": a5[t] / a50[t],
            "g0_ageH": np.log1p(t - sh_at[i]), "g0_ageL": np.log1p(t - sl_at[j]), "g0_is4h": float(iv == "4h"),
            "g1_range10": range10[t], "g1_a5_a20": a5[t] / a20[t], "g1_bbw_pct": bbw_pct[t],
            "g1_a14_a100": a14[t] / a100[t],
            "g2_repH": rep(sh_at, sh_px, i), "g2_repL": rep(sl_at, sl_px, j),
            "g2_mom5": (c[t] - c[t - 5]) / A, "g2_relvol": rv[t], "g2_clv5": clv5[t], "g2_vclv5": vclv5[t],
            "g2_absH": float(np.mean(rv[w5] * shrink * near_h)), "g2_absL": float(np.mean(rv[w5] * shrink * near_l)),
            "g2_range5": range5[t], "g2_touchH": float((h[w20] >= H - 0.25 * A).sum()),
            "g2_touchL": float((l[w20] <= L + 0.25 * A).sum()),
            **{f"g3_st{s}": float(stage[t] == s) for s in (1, 2, 3, 4)},
            "g3_since": np.log1p(since[t]), "g3_slopez": sz[t], "g3_pva": pva[t],
            "g3_bo": float(bo[t]), "g3_bd": float(bd[t]),
            **{f"g5_{p}_{d}": V5[(p, d)][t] for p in VIOL for d in ("up", "dn")},
            "g5_range_z": range_z[t],
            **{f"g6_p{k}_{lab}": float(last3[k] == lab) for k in range(3) for lab in LABELS},
        }
        f.update(dict(zip(FV4, G4[r])))
        rows.append(dict(t=int(t), ts=int(ts[t]), H=H, L=L, first=int(min(first, 10 ** 6)),
                         y_time=y_time, y_side=y_side, **f))
    d = pd.DataFrame(rows)
    fc = [k for k in d.columns if k[:2] in ("g0", "g1", "g2", "g3", "g4", "g5", "g6")]
    x = d[fc].to_numpy(float)
    x[~np.isfinite(x)] = np.nan
    d[fc] = np.clip(np.nan_to_num(x, nan=0.0), -50, 50).astype(np.float32)
    if "g2_relvol" in d:
        d.loc[d["g2_relvol"] == 0, "g2_relvol"] = 1.0
    return d


def one(job):
    venue, sym, iv, source = job
    try:
        df = series(venue, sym, iv, source)
        if df is None:
            return None
        d = build(df, iv)
    except Exception as ex:  # one bad series should not sink the run
        print(f"  FAILED {job}: {ex!r}", flush=True)
        return None
    if d is None:
        return None
    d.insert(0, "src", source)
    d.insert(0, "iv", iv)
    d.insert(0, "sym", sym)
    d.insert(0, "venue", venue)
    print(f"  {venue} {source} {sym} {iv}: {len(d)} bars, timing rate {d['y_time'].mean():.3f}, "
          f"side up {d['y_side'].mean():.3f} of {d['y_side'].notna().sum()}", flush=True)
    return d


# ------------------------------------------------------------------ models and scoring

def cols(d, name):
    fc = [k for k in d.columns if k.startswith("g")]
    if name == "G0+all":
        return fc
    want = ["g0"] + ([name.split("+")[1].lower()] if "+" in name else [])
    return [k for k in fc if k[:2] in want]


def fit_predict(tr, te, fc, y):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = make_pipeline(StandardScaler(), LogisticRegression(C=C_L2, max_iter=3000))
    m.fit(tr[fc].to_numpy(float), tr[y].to_numpy(int))
    return m.predict_proba(te[fc].to_numpy(float))[:, 1]


def wauc(y, s, w):
    """AUC with row weights (ties in s broken by order; scores are continuous)."""
    o = np.argsort(s, kind="mergesort")
    y, w = y[o], w[o]
    wn = w * (1 - y)
    wp = w * y
    below = np.cumsum(wn) - wn
    den = wp.sum() * wn.sum()
    return float((wp * below).sum() / den) if den > 0 else np.nan


def score(d, rng):
    """Per venue x source x target: held-out AUC of every set, and gains over G0 with day-bootstrap
    intervals (the same draws for every set). Returns the table and the held-out predictions."""
    rows, preds = [], []
    for (venue, src), g in d.groupby(["venue", "src"]):
        sec = g["iv"].map(SEC).to_numpy()
        tr_m = g["ts"].to_numpy() + (SIDE_WIN + 1) * sec < SPLIT
        te_m = g["ts"].to_numpy() >= SPLIT
        for target in ("y_time", "y_side"):
            tr = g[tr_m & g[target].notna().to_numpy()]
            te = g[te_m & g[target].notna().to_numpy()]
            if len(tr) < 1000 or len(te) < 1000:
                continue
            y = te[target].to_numpy(float)
            P = {s: fit_predict(tr, te, cols(g, s), target) for s in SETS}
            day = (te["ts"].to_numpy() // 86400).astype(np.int64)
            ud, inv = np.unique(day, return_inverse=True)
            W = [np.bincount(rng.integers(0, len(ud), len(ud)), minlength=len(ud))[inv].astype(float)
                 for _ in range(DRAWS)]
            ones = np.ones(len(y))
            base = wauc(y, P["G0"], ones)
            base_b = np.array([wauc(y, P["G0"], w) for w in W])
            half = te["ts"].to_numpy() >= pd.Timestamp("2025-01-01", tz="UTC").timestamp()
            for s in SETS:
                a = wauc(y, P[s], ones)
                gb = np.array([wauc(y, P[s], w) for w in W]) - base_b if s != "G0" else np.zeros(DRAWS)
                r = dict(venue=venue, src=src, target=target[2:], set=s, n_train=len(tr), n_test=len(te),
                         rate=float(y.mean()), auc=a, gain=a - base, lo=np.quantile(gb, 0.05),
                         hi=np.quantile(gb, 0.95), auc_2024=wauc(y[~half], P[s][~half], ones[~half]),
                         auc_2025=wauc(y[half], P[s][half], ones[half]))
                for iv in TFS:
                    m = (te["iv"] == iv).to_numpy()
                    r[f"auc_{iv}"] = wauc(y[m], P[s][m], ones[m]) if m.sum() > 100 else np.nan
                rows.append(r)
            keep = te[["venue", "src", "sym", "iv", "t", "ts", "H", "L", "first", target]].copy()
            keep["target"] = target[2:]
            keep["p_G0"], keep["p_all"] = P["G0"], P["G0+all"]
            preds.append(keep.rename(columns={target: "y"}))
            print(f"  scored {venue} {src} {target}: G0 {base:.4f}, all {wauc(y, P['G0+all'], ones):.4f}", flush=True)
    return pd.DataFrame(rows), pd.concat(preds, ignore_index=True)


def verdict(t):
    out = []
    for venue in ("binance", "mt5"):
        for target in ("time", "side"):
            for s in SETS[1:]:
                def cell(src):
                    x = t[(t["venue"] == venue) & (t["src"] == src) & (t["target"] == target) & (t["set"] == s)]
                    return x.iloc[0] if len(x) else None
                r, i, gw = cell("real"), cell("iid"), cell("garch")
                if r is None:
                    continue
                ok = bool(r["lo"] > 0 and i is not None and gw is not None and r["gain"] > i["gain"] and r["gain"] > gw["gain"])
                out.append(dict(venue=venue, target=target, set=s, gain_real=r["gain"], lo=r["lo"], hi=r["hi"],
                                gain_iid=i["gain"] if i is not None else np.nan,
                                gain_garch=gw["gain"] if gw is not None else np.nan, predicts=ok))
    return pd.DataFrame(out)


def calibration(p):
    rows = []
    for (venue, src, target), g in p.groupby(["venue", "src", "target"]):
        for model in ("p_G0", "p_all"):
            q = pd.qcut(g[model].rank(method="first"), 10, labels=False)
            for k, x in g.groupby(q):
                rows.append(dict(venue=venue, src=src, target=target, model=model, decile=int(k) + 1, n=len(x),
                                 pred=x[model].mean(), real=x["y"].mean()))
    return pd.DataFrame(rows)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    smoke = os.environ.get("SMOKE")
    if smoke:
        v, s, iv, src = smoke.split(":")
        d = one((v, s, iv, src))
        pd.set_option("display.width", 250)
        print(d.describe().T.to_string())
        return
    jobs = [(v, s, iv, src) for src in SOURCES for iv in TFS
            for v, syms in (("binance", COINS), ("mt5", MT5)) for s in syms]
    with ProcessPoolExecutor(min(10, int(os.environ.get("WORKERS", 10)))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "bos_rows.pkl.gz")
    rng = np.random.default_rng(61)
    t, p = score(d, rng)
    t.to_csv(OUT / "bos_auc.csv", index=False)
    p.to_pickle(OUT / "bos_preds.pkl.gz")
    v = verdict(t)
    v.to_csv(OUT / "bos_verdict.csv", index=False)
    c = calibration(p)
    c.to_csv(OUT / "bos_calibration.csv", index=False)
    pd.set_option("display.width", 280)
    pd.set_option("display.max_rows", 400)
    print(t.round(4).to_string(index=False))
    print(v.round(4).to_string(index=False))
    print(c[(c["venue"] == "binance") & (c["src"] == "real") & (c["target"] == "side")].round(4).to_string(index=False))
    pr = v[(v["venue"] == "binance") & (v["target"] == "side") & (v["set"] == "G0+all")].iloc[0]
    print(f"\nPRIMARY (side, G0+all vs G0, Binance): gain {pr['gain_real']:+.4f} [{pr['lo']:+.4f}, {pr['hi']:+.4f}]; "
          f"iid {pr['gain_iid']:+.4f}; garch {pr['gain_garch']:+.4f} -> {'PASSES' if pr['predicts'] else 'fails'}")


# ------------------------------------------------------------------ plots

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = pd.read_csv(OUT / "bos_auc.csv")
    col = {"real": "#1d3557", "iid": "#a8dadc", "garch": "#e9c46a"}
    # 1. gain over G0 by group, real vs walks, per venue and target
    fig, axes = plt.subplots(2, 2, figsize=(18, 10))
    for i, venue in enumerate(("binance", "mt5")):
        for j, target in enumerate(("side", "time")):
            ax = axes[i, j]
            x = np.arange(len(SETS) - 1)
            for k, src in enumerate(SOURCES):
                g = t[(t["venue"] == venue) & (t["src"] == src) & (t["target"] == target)].set_index("set")
                if not len(g):
                    continue
                g = g.reindex(SETS[1:])
                ax.bar(x + (k - 1) * 0.27, g["gain"], 0.27, color=col[src], label=src,
                       yerr=[g["gain"] - g["lo"], g["hi"] - g["gain"]], capsize=2, ecolor="#555")
            ax.axhline(0, color="k", lw=0.7)
            ax.set_xticks(x)
            ax.set_xticklabels([s.replace("G0+", "+") for s in SETS[1:]])
            b = t[(t["venue"] == venue) & (t["target"] == target) & (t["set"] == "G0")].set_index("src")["auc"]
            ax.set_title(f"{venue} ({'b' if target == 'side' else 'a'}) {target}: AUC gain over G0, 90% day-bootstrap; "
                         f"G0 AUC " + ", ".join(f"{s} {b.get(s, np.nan):.3f}" for s in SOURCES), fontsize=9)
            ax.legend(fontsize=8)
    fig.suptitle("Break of structure: held-out (2024 on) AUC gain of each feature group over the H/L geometry baseline, real vs walks")
    fig.tight_layout()
    fig.savefig(OUT / "bos_gain.png", dpi=80)
    plt.close(fig)
    # 2. calibration of the side model
    c = pd.read_csv(OUT / "bos_calibration.csv")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, venue in zip(axes, ("binance", "mt5"), strict=False):
        for src in SOURCES:
            for model, st in (("p_all", "-o"), ("p_G0", ":s")):
                g = c[(c["venue"] == venue) & (c["src"] == src) & (c["target"] == "side") & (c["model"] == model)]
                if len(g):
                    ax.plot(g["pred"], g["real"], st, color=col[src], label=f"{src} {'G0+all' if model == 'p_all' else 'G0'}")
        ax.plot([0, 1], [0, 1], color="grey", lw=0.8)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xlabel("predicted P(up first), decile mean")
        ax.set_title(f"{venue}: side model calibration, held out")
        ax.legend(fontsize=8)
    axes[0].set_ylabel("realised P(up first)")
    fig.tight_layout()
    fig.savefig(OUT / "bos_calibration.png", dpi=80)
    plt.close(fig)
    # 3. gallery: held-out Binance 4h real, three of the most bullish and three of the most bearish calls
    p = pd.read_pickle(OUT / "bos_preds.pkl.gz")
    p = p[(p["venue"] == "binance") & (p["src"] == "real") & (p["target"] == "side") & (p["iv"] == "4h")]
    rng = np.random.default_rng(7)
    hi_q, lo_q = p["p_all"].quantile(0.9), p["p_all"].quantile(0.1)
    pick = pd.concat([p[p["p_all"] >= hi_q].sample(3, random_state=rng.integers(1e9)),
                      p[p["p_all"] <= lo_q].sample(3, random_state=rng.integers(1e9))])
    fig, axes = plt.subplots(2, 3, figsize=(21, 10))
    for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
        df = _bin(r.sym, r.iv)
        t0 = int(r.t)
        i0, i1 = max(0, t0 - 60), min(len(df) - 1, t0 + min(SIDE_WIN, int(r["first"])) + 15)
        w = df.iloc[i0:i1 + 1]
        x = np.arange(i0, i1 + 1)
        up = (w["close"] >= w["open"]).to_numpy()
        ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
        ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
        ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
        ax.hlines(r.H, i0, i1, colors="green", lw=1.2, label="H")
        ax.hlines(r.L, i0, i1, colors="red", lw=1.2, label="L")
        ax.axvline(t0, color="purple", lw=1, ls=":")
        what = ("up (close above H)" if r.y == 1 else "down (close below L)") + f" after {int(r['first'])} bars"
        ax.set_title(f"{r.sym}USDT 4h {pd.Timestamp(r.ts, unit='s'):%Y-%m-%d %H:%M}  P(up first) {r.p_all:.2f} "
                     f"(G0 {r.p_G0:.2f})  -> {what}", fontsize=9)
    fig.suptitle("Held-out Binance 4h examples: top row the model's most bullish decile, bottom row its most bearish; "
                 "green H, red L, purple dotted the prediction bar", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "bos_gallery.png", dpi=80)
    plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
