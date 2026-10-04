"""Classic mean-reversion rules on real markets, against matched walks, a coin twin and a reverting control.

Frozen in `mr_rule.json` before any real-data run; the confirmation cell in `mr_selected.json` before the
confirmation was read. Rules: Connors RSI(2), Bollinger, z-score/OU, Keltner and VWAP fades, IBS, N down
closes, the index gap fade, each split by variance-ratio/Hurst regime, and rolling cointegrated pairs.

  OUT=... MT5BT_DB=... MODE=discover|confirm|plot python research/ideas/mean_reversion.py
  MODE=smoke SMOKE=binance:BTC:4h SOURCES=iid,ou ...   one series, a walk and the OU control
"""
from __future__ import annotations

import itertools
import json
import os
import pickle
import sqlite3
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

OUT = Path(os.environ.get("OUT", ".data/mr"))
DB = os.environ.get("MT5BT_DB")
BIN = Path(os.environ.get("BINANCE", os.path.expanduser("~/till_infinity/data/binance")))
CACHE = Path(os.environ.get("CACHE", os.path.expanduser("~/till_infinity/data/binance_fresh")))
WORKERS = int(os.environ.get("WORKERS", 12))

SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
IVS = tuple(SEC)
SPLIT = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())
SPLIT_DAY = SPLIT // 86400
NS = (0.5, 1, 2, 4, 10)
H_OWN, H_FP, PAD, SLIP, MIN_RISK, MAX_RISK = 20, 100, 0.1, 0.05, 0.1, 10.0
FEE, MAX_COST = 0.0007, 0.5
STEPS = 256
GARCH = (0.08, 0.90)
OU_HL, AR_PHI = 20, -0.2
GAP_ATR, GAP_HOURS = 0.5, 8
VR_W, VR_Q, VR_T = 100, 4, 0.9
HU_W, HU_LAGS, HU_T = 100, (1, 2, 4, 8, 16), 0.45
OUF_W, OUF_HL = 200, 50
PAIR_STEP, PAIR_H, DF_CRIT = 25, 100, -2.86
BASE = ("rsi2_ma", "rsi2", "bb", "z50", "z50_ou", "kelt", "vwap", "ibs1", "ibsrev", "down3", "down4", "down5", "gap")
PAIR_RULES = ("pair", "pair_coint")
REGIMES = ("", "|VR<0.9", "|VR>=0.9", "|H<0.45", "|H>=0.45")
FAMS = ("fx", "metal", "index", "energy", "crypto", "binance")
GAP_FAMS = ("fx", "metal", "index", "energy")
PANEL = (("mt5", "EURUSD", "fx"), ("mt5", "XAUUSD", "metal"), ("mt5", "US SP 500", "index"), ("binance", "BTC", "binance"))
PAIRS_MT5 = {
    "fx": [("EURUSD", "GBPUSD"), ("AUDUSD", "NZDUSD"), ("EURUSD", "USDCHF"), ("EURJPY", "GBPJPY")],
    "metal": [("XAUUSD", "XAGUSD"), ("XPTUSD", "XPDUSD")],
    "index": [("US SP 500", "US Tech 100"), ("US SP 500", "Wall Street 30"), ("Germany 40", "UK 100")],
    "energy": [("US Oil", "UK Brent Oil")],
    "crypto": [("BTCUSD", "ETHUSD")],
}


def _universe():
    import run as RUN
    import turn_confirm as TC
    import turn_trade as TT
    fresh = [c for c in TC.SET_A + TC.SET_B if c not in TT.COINS] + list(TC.SET_C)
    return RUN, TT.COINS, tuple(dict.fromkeys(fresh))


# ---------------------------------------------------------------- data

def mt5_cost(sym):
    """The cost a trade pays, in price: the spread floor, else the median of the bars' positive spreads."""
    import run as RUN
    RUN.DB = DB
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        spec = conn.execute("SELECT spec FROM specs WHERE symbol = ?", (sym,)).fetchone()
        if spec is None:
            return None, "no spec"
        point = float(json.loads(spec[0])["point"])
        floor = RUN.spread_floor(sym, SimpleNamespace(point=point))
        if floor > 0:
            return floor * point, "floor"
        s = np.array([r[0] for r in conn.execute("SELECT spread FROM bars WHERE symbol = ? AND spread > 0", (sym,))], float)
        return (float(np.median(s)) * point, "bar-median fallback") if len(s) else (None, "no spread")
    finally:
        conn.close()


def load(venue, sym, iv, cost_px=None):
    """(bars with ts, open, high, low, close, volume; cost per bar in price) or (None, None)."""
    cols = ("ts", "open", "high", "low", "close", "volume")
    if venue == "mt5":
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        df = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = ? AND interval = ?"
                               " ORDER BY ts", conn, params=(sym, iv))
        conn.close()
        if len(df) < 400 or cost_px is None:
            return None, None
        df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        return df, np.full(len(df), float(cost_px))
    path = BIN / f"{sym}USDT.klines.{iv}.npz" if venue == "binance" else CACHE / f"{sym}USDT.{iv}.npz"
    if not path.exists():
        return None, None
    z = np.load(path)
    df = pd.DataFrame({k: z["time" if (k == "ts" and "time" in z.files) else k] for k in cols})
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["ts"] = df["ts"].astype(np.int64)
    if len(df) < 400:
        return None, None
    return df, FEE * df["close"].to_numpy(float)


def flip(df):
    return df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])


def ou_bars(ts, sigma, start, seed, hl=OU_HL, steps=STEPS):
    """An Ornstein-Uhlenbeck price: half-life `hl` bars, sub-step innovations of sd sigma / sqrt(steps)."""
    from scipy.signal import lfilter
    from mcfl import synth
    n = len(ts)
    rng = np.random.default_rng(seed)
    phi = 0.5 ** (1.0 / (hl * steps))
    x = lfilter([1.0], [1.0, -phi], rng.normal(0.0, sigma / np.sqrt(steps), n * steps))
    d = synth.bars_from_path(start + np.r_[0.0, x], steps)
    d["ts"] = np.asarray(ts, np.int64)[:len(d)]
    return d


def make_source(df, source, seed):
    from mcfl import synth
    if source == "real":
        return df
    ts, n = df["ts"].to_numpy(np.int64), len(df)
    sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
    if source == "iid":
        w = synth.matched_profiled(df, seed, steps=STEPS)
    elif source == "garch":
        w = synth.matched_profiled(df, seed, steps=STEPS, garch=GARCH)
    elif source == "ou":
        w = ou_bars(ts, sigma, float(df["open"].iloc[0]), seed)
    elif source == "ar":
        w = synth.trend(n, sigma=sigma, phi=AR_PHI, seed=seed, steps=STEPS)
        w["ts"] = ts
    else:
        raise ValueError(source)
    w = w.reset_index(drop=True).iloc[:n].copy()
    w["volume"] = df["volume"].to_numpy(float)[:len(w)]
    return w[["ts", "open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------- indicators

def wilder(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    return wilder(np.maximum(h, pc) - np.minimum(l, pc), n)


def rsi(c, n=2):
    d = np.r_[0.0, np.diff(c)]
    up, dn = wilder(np.maximum(d, 0), n), wilder(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(dn > 0, 100 - 100 / (1 + up / dn), 100.0)


def regimes(c):
    """Trailing variance ratio VR(4), Hurst slope and OU half-life, each known at the bar's close."""
    s = pd.Series(c)
    d1 = s.diff()
    with np.errstate(divide="ignore", invalid="ignore"):
        vr = ((s - s.shift(VR_Q)).rolling(VR_W).var() / (VR_Q * d1.rolling(VR_W).var())).to_numpy()
        logs = np.column_stack([np.log((s - s.shift(k)).rolling(HU_W).std().to_numpy()) for k in HU_LAGS])
        x = np.log(np.array(HU_LAGS, float))
        xc = x - x.mean()
        hu = logs @ xc / (xc ** 2).sum()
        lag = s.shift(1)
        cov = (d1 * lag).rolling(OUF_W).mean() - d1.rolling(OUF_W).mean() * lag.rolling(OUF_W).mean()
        b = (cov / lag.rolling(OUF_W).var(ddof=0)).to_numpy()
        hl = np.where((b < 0) & (b > -1), -np.log(2) / np.log1p(np.clip(b, -0.999999, 0)), np.inf)
    return vr, hu, hl


def onset(cond):
    return cond & ~np.r_[False, cond[:-1]]


def signals(f, iv):
    """{rule: (signal bars, exit-on-close flags)} for the long side of frame f."""
    o, h, l, c, v = (f[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    s = pd.Series(c)
    a10 = atr(h, l, c, 10)
    r2 = rsi(c, 2)
    sma5, sma20, sma50, sma200 = (s.rolling(k).mean().to_numpy() for k in (5, 20, 50, 200))
    sd20, sd50 = (s.rolling(k).std(ddof=0).to_numpy() for k in (20, 50))
    ema20 = s.ewm(span=20, adjust=False).mean().to_numpy()
    rng_ = h - l
    with np.errstate(divide="ignore", invalid="ignore"):
        ibs = np.where(rng_ > 0, (c - l) / rng_, np.nan)
    dn = np.r_[False, c[1:] < c[:-1]]
    up = np.r_[False, c[1:] > c[:-1]]
    idx = np.arange(n)
    run = idx - np.maximum.accumulate(np.where(~dn, idx, 0))
    out = {
        "rsi2": (onset(r2 < 10), c > sma5),
        "rsi2_ma": (onset((r2 < 10) & (c > sma200)), c > sma5),
        "bb": (onset(c < sma20 - 2 * sd20), c >= sma20),
        "z50": (onset(c < sma50 - 2 * sd50), c >= sma50),
        "kelt": (onset(c < ema20 - 2 * a10), c >= ema20),
        "ibs1": (ibs < 0.2, np.ones(n, bool)),
        "ibsrev": (ibs < 0.2, ibs > 0.8),
        "down3": (run == 3, up),
        "down4": (run == 4, up),
        "down5": (run == 5, up),
    }
    if iv in ("15m", "1h"):
        D = int(86400 / SEC[iv])
        tp = (h + l + c) / 3
        vv = np.where(np.isfinite(v) & (v > 0), v, 0.0)
        num = pd.Series(tp * vv).rolling(D).sum().to_numpy()
        den = pd.Series(vv).rolling(D).sum().to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            vw = np.where(den > 0, num / den, pd.Series(tp).rolling(D).mean().to_numpy())
        dev = c - vw
        sd = pd.Series(dev).rolling(D).std(ddof=0).to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            z = dev / sd
        out["vwap"] = (onset(z < -2), c >= vw)
    return {k: (np.flatnonzero(sig), x) for k, (sig, x) in out.items()}


# ---------------------------------------------------------------- trade simulation (vectorised over trades)

def sim(o, h, l, c, e, entry, risk, slip, X, H, target=None):
    """Own exit (no stop), the same with the structural stop, and the opposite side with its stop on the
    other side, all exiting on the same own-exit event. R gross; the own exit's bar."""
    n, m = len(c), len(e)
    stop, ostop = entry - risk, entry + risk
    own, st, op = np.full(m, np.nan), np.full(m, np.nan), np.full(m, np.nan)
    xb, xs = np.full(m, -1, np.int64), np.full(m, -1, np.int64)
    a_own, a_st, a_op = np.ones(m, bool), np.ones(m, bool), np.ones(m, bool)
    for k in range(H):
        if not (a_own.any() or a_st.any() or a_op.any()):
            break
        j = np.minimum(e + k, n - 1)
        end = (k == H - 1) | (e + k >= n - 1)
        hs = a_st & (l[j] <= stop)
        st[hs] = (np.minimum(o[j], stop)[hs] - slip[hs] - entry[hs]) / risk[hs]
        xs[hs] = j[hs]
        a_st &= ~hs
        ho = a_op & (h[j] >= ostop)
        op[ho] = (entry[ho] - np.maximum(o[j], ostop)[ho] - slip[ho]) / risk[ho]
        a_op &= ~ho
        nxt = np.where(j + 1 < n, o[np.minimum(j + 1, n - 1)], c[j])
        xo = X[j]
        if target is not None:
            ht = h[j] >= target
            ev = ht | xo | end
            px = np.where(ht, np.maximum(o[j], target), np.where(xo, nxt, c[j]))
        else:
            ev = xo | end
            px = np.where(xo, nxt, c[j])
        f = a_own & ev
        own[f] = (px[f] - entry[f]) / risk[f]
        xb[f] = j[f]
        a_own &= ~f
        f = a_st & ev
        st[f] = (px[f] - entry[f]) / risk[f]
        xs[f] = j[f]
        a_st &= ~f
        f = a_op & ev
        op[f] = (entry[f] - px[f]) / risk[f]
        a_op &= ~f
    return own, st, op, xb, xs


def fpass(h, l, e, entry, risk, HP=H_FP):
    """The most R reached before the stop at -1R, within HP bars, long and short from the same entry."""
    n, m = len(h), len(e)
    up, dn = np.zeros(m), np.zeros(m)
    au, ad = np.ones(m, bool), np.ones(m, bool)
    for k in range(HP):
        live = e + k <= n - 1
        au &= live
        ad &= live
        if not (au.any() or ad.any()):
            break
        j = np.minimum(e + k, n - 1)
        au &= ~(l[j] <= entry - risk)
        up = np.where(au, np.maximum(up, (h[j] - entry) / risk), up)
        ad &= ~(h[j] >= entry + risk)
        dn = np.where(ad, np.maximum(dn, (entry - l[j]) / risk), dn)
    return up, dn


def frame_trades(f, iv, fam, cost_atr, key, gapmask):
    o, h, l, c = (f[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = f["ts"].to_numpy(np.int64)
    n = len(c)
    a = atr(h, l, c, 14)
    vr, hu, hl = regimes(c)
    sig = signals(f, iv)
    jobs = []
    for rule, (t, X) in sig.items():
        t = t[(t >= 1) & (t < n - 1)]
        e = t + 1
        entry = o[e]
        risk = entry - (l[t] - PAD * a[t])
        jobs.append((rule, t, e, entry, risk, X, H_OWN, None))
    if fam in GAP_FAMS and iv in ("15m", "1h"):
        s = np.flatnonzero(gapmask)
        s = s[(s >= 1) & (s < n)]
        g = o[s] - c[s - 1]
        s = s[g <= -GAP_ATR * a[s - 1]]
        t = s - 1
        risk = (c[t] - o[s]) + PAD * a[t]
        jobs.append(("gap", t, s, o[s], risk, np.zeros(n, bool), max(1, int(GAP_HOURS * 3600 / SEC[iv])), c[t]))
    rows = []
    for rule, t, e, entry, risk, X, H, target in jobs:
        ok = np.isfinite(risk) & (a[t] > 0) & (risk >= MIN_RISK * a[t]) & (risk <= MAX_RISK * a[t])
        t, e, entry, risk = t[ok], e[ok], entry[ok], risk[ok]
        if target is not None:
            target = target[ok]
        if not len(t):
            continue
        slip = SLIP * a[t]
        own, st, op, xb, xs = sim(o, h, l, c, e, entry, risk, slip, X, H, target)
        up, dn = fpass(h, l, e, entry, risk)
        rng = np.random.default_rng(zlib.crc32(f"{key}{rule}".encode()))
        rows.append(pd.DataFrame({
            "rule": rule, "t": t.astype(np.int32), "ts": ts[e], "risk_atr": (risk / a[t]).astype(np.float32),
            "cost": (cost_atr[t] * a[t] / risk).astype(np.float32),
            "own": own.astype(np.float32), "st": st.astype(np.float32), "op": op.astype(np.float32),
            "up": up.astype(np.float32), "dn": dn.astype(np.float32),
            "hold": (xb - e + 1).astype(np.int16), "hold_st": (xs - e + 1).astype(np.int16),
            "twin": np.where(rng.random(len(t)) < 0.5, 1, -1).astype(np.int8),
            "vr": vr[t].astype(np.float32), "hu": hu[t].astype(np.float32), "hl": hl[t].astype(np.float32)}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _path(source, venue, sym, iv, kind="single"):
    safe = sym if isinstance(sym, str) else "-".join(sym)
    return OUT / "trades" / source / f"{kind}__{venue}__{safe.replace(' ', '_')}__{iv}.pkl"


def one(job):
    try:
        return _one(job)
    except Exception as exc:  # one bad series must not stop the pool
        print(f"  FAILED {job[:4]}: {exc!r}", flush=True)
        return job, f"error {exc!r}", None


def _one(job):
    """One series x one source: every rule, both sides."""
    from mcfl import synth
    venue, sym, iv, source, fam, cost_px = job
    path = _path(source, venue, sym, iv)
    if path.exists():
        return job, "cached", None
    df, cpx = load(venue, sym, iv, cost_px)
    if df is None:
        return job, "no data", None
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a = atr(h, l, c, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        cost_atr = cpx / np.maximum(a, 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    med = float(np.nanmedian(cost_atr[50:]))
    if med > MAX_COST:
        return job, "dropped", med
    gapmask = synth.gaps(df["ts"].to_numpy(np.int64))
    key = f"{venue}{sym}{iv}{source}"
    frame = make_source(df, source, zlib.crc32(key.encode()) % 100000)
    cost_atr = cost_atr[:len(frame)]
    gapmask = gapmask[:len(frame)]
    parts = []
    for side, fr in ((1, frame), (-1, flip(frame))):
        d = frame_trades(fr, iv, fam, cost_atr, f"{key}{side}", gapmask)
        if len(d):
            d["side"] = np.int8(side)
            parts.append(d)
    d = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(d):
        d["venue"], d["sym"], d["iv"], d["fam"] = venue, sym, iv, fam
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(d, fh, protocol=5)
    print(f"  {source} {venue} {sym} {iv}: {len(d)} trades (cost {med:.3f} ATR)", flush=True)
    return job, "ok", med


# ---------------------------------------------------------------- pairs

def garch_vols(n, rng, alpha=GARCH[0], beta=GARCH[1]):
    z = rng.normal(0.0, 1.0, n)
    var, v = np.empty(n), 1.0
    for i in range(n):
        var[i] = v
        v = (1 - alpha - beta) + alpha * v * z[i] ** 2 + beta * v
    return np.sqrt(var / var.mean())


def pair_trades(yo, yc, xo, xc, cfy, cfx, ts, iv, key):
    n = len(yc)
    W = 250 if iv == "1d" else 500
    A, B, S, T = (np.full(n, np.nan) for _ in range(4))
    for r in range(W - 1, n, PAIR_STEP):
        Y, Xw = yc[r - W + 1:r + 1], xc[r - W + 1:r + 1]
        xm, ym = Xw.mean(), Y.mean()
        vx = ((Xw - xm) ** 2).sum()
        if not vx > 0:
            continue
        b = ((Xw - xm) * (Y - ym)).sum() / vx
        a_ = ym - b * xm
        res = Y - a_ - b * Xw
        sd = res.std()
        e0, de = res[:-1], np.diff(res)
        rho = (de @ e0) / (e0 @ e0)
        u = de - rho * e0
        se = np.sqrt((u @ u) / (len(u) - 1) / (e0 @ e0))
        sl = slice(r, min(n, r + PAIR_STEP))
        A[sl], B[sl], S[sl], T[sl] = a_, b, sd, rho / se
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (yc - A - B * xc) / S
    rows = []
    for side in (1, -1):
        cond = (side * z <= -2) & np.isfinite(z)
        t = np.flatnonzero(onset(cond))
        t = t[t < n - 1]
        if not len(t):
            continue
        e = t + 1
        a_, b, sd = A[t], B[t], S[t]
        se_ = yo[e] - b * xo[e]
        m = len(t)
        R = np.full(m, np.nan)
        xb = np.full(m, -1, np.int64)
        act = np.ones(m, bool)
        up, dn = np.zeros(m), np.zeros(m)
        au, ad = np.ones(m, bool), np.ones(m, bool)
        for k in range(PAIR_H):
            j = np.minimum(e + k, n - 1)
            live = e + k <= n - 1
            sc = yc[j] - b * xc[j]
            zc = (sc - a_) / sd
            g = side * (sc - se_) / (2 * sd)
            au &= live
            ad &= live
            au &= ~(g <= -1)
            up = np.where(au, np.maximum(up, g), up)
            ad &= ~(-g <= -1)
            dn = np.where(ad, np.maximum(dn, -g), dn)
            end = (k == PAIR_H - 1) | (e + k >= n - 1)
            hit = (side * zc >= 0) | (side * zc <= -4)
            jn = np.minimum(j + 1, n - 1)
            px = np.where(hit & (j + 1 < n), yo[jn] - b * xo[jn], sc)
            f = act & (hit | end)
            R[f] = side * (px[f] - se_[f]) / (2 * sd[f])
            xb[f] = j[f]
            act &= ~f
            if not (act.any() or au.any() or ad.any()):
                break
        rng = np.random.default_rng(zlib.crc32(f"{key}{side}".encode()))
        cost = (cfy[t] + np.abs(b) * cfx[t]) / (2 * sd)
        rows.append(pd.DataFrame({
            "rule": "pair", "t": t.astype(np.int32), "ts": ts[e], "risk_atr": np.float32(np.nan),
            "cost": cost.astype(np.float32), "own": R.astype(np.float32), "st": R.astype(np.float32),
            "op": (-R).astype(np.float32), "up": up.astype(np.float32), "dn": dn.astype(np.float32),
            "hold": (xb - e + 1).astype(np.int16), "hold_st": (xb - e + 1).astype(np.int16),
            "twin": np.where(rng.random(m) < 0.5, 1, -1).astype(np.int8),
            "vr": np.float32(np.nan), "hu": np.float32(np.nan), "hl": np.float32(np.nan),
            "dft": T[t].astype(np.float32), "side": np.int8(side)}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def pair_one(job):
    try:
        return _pair_one(job)
    except Exception as exc:
        print(f"  FAILED pair {job[:4]}: {exc!r}", flush=True)
        return job, f"error {exc!r}", None


def _pair_one(job):
    (va, A), (vb, Bs), iv, source, fam, costs = job
    path = _path(source, f"{va}-{vb}", (A, Bs), iv, "pair")
    if path.exists():
        return job, "cached", None
    da, ca = load(va, A, iv, costs.get(A))
    db, cb = load(vb, Bs, iv, costs.get(Bs))
    if da is None or db is None:
        return job, "no data", None
    da = da.assign(cost=ca)
    db = db.assign(cost=cb)
    m = da.merge(db, on="ts", suffixes=("_y", "_x"))
    if len(m) < 600:
        return job, "no overlap", None
    ts = m["ts"].to_numpy(np.int64)
    yo, yc = np.log(m["open_y"].to_numpy(float)), np.log(m["close_y"].to_numpy(float))
    xo, xc = np.log(m["open_x"].to_numpy(float)), np.log(m["close_x"].to_numpy(float))
    cfy = m["cost_y"].to_numpy(float) / m["close_y"].to_numpy(float)
    cfx = m["cost_x"].to_numpy(float) / m["close_x"].to_numpy(float)
    key = f"{va}{A}{vb}{Bs}{iv}{source}"
    rng = np.random.default_rng(zlib.crc32(key.encode()))
    n = len(ts)
    if source != "real":
        sy, sx = float(np.std(np.diff(yc))), float(np.std(np.diff(xc)))
        if source == "coint":
            rx = rng.normal(0.0, sx, n)
            phi = 0.5 ** (1.0 / OU_HL)
            from scipy.signal import lfilter
            spread = lfilter([1.0], [1.0, -phi], rng.normal(0.0, sy, n))
            xc = xc[0] + np.cumsum(rx)
            yc = yc[0] - xc[0] + xc + spread
        else:
            vy = garch_vols(n, rng) if source == "garch" else 1.0
            vx = garch_vols(n, rng) if source == "garch" else 1.0
            yc = yc[0] + np.cumsum(rng.normal(0.0, sy, n) * vy)
            xc = xc[0] + np.cumsum(rng.normal(0.0, sx, n) * vx)
        yo, xo = np.r_[yc[0], yc[:-1]], np.r_[xc[0], xc[:-1]]
    d = pair_trades(yo, yc, xo, xc, cfy, cfx, ts, iv, key)
    if len(d):
        d["venue"], d["sym"], d["iv"], d["fam"] = f"{va}-{vb}", f"{A}~{Bs}", iv, fam
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(d, fh, protocol=5)
    print(f"  pair {source} {A}~{Bs} {iv}: {len(d)} trades", flush=True)
    return job, "ok", None


# ---------------------------------------------------------------- jobs

def build_jobs():
    RUN, coins, fresh = _universe()
    costs = {}
    single, pairs = [], []
    for sym, fam in RUN.FAMILY.items():
        costs[sym] = mt5_cost(sym)
    for src in ("real", "iid", "garch"):
        for iv in IVS:
            for sym, fam in RUN.FAMILY.items():
                if costs[sym][0] is not None:
                    single.append(("mt5", sym, iv, src, fam, costs[sym][0]))
            for c in coins:
                single.append(("binance", c, iv, src, "binance", None))
            if iv in ("4h", "1d"):
                for c in fresh:
                    single.append(("fresh", c, iv, src, "fresh", None))
    for src in ("ou", "ar"):
        for iv in IVS:
            for venue, sym, fam in PANEL:
                single.append((venue, sym, iv, src, fam, costs.get(sym, (None,))[0]))
    cpx = {s: v[0] for s, v in costs.items() if v[0] is not None}
    for src in ("real", "iid", "garch", "coint"):
        for iv in IVS:
            for fam, prs in PAIRS_MT5.items():
                for a, b in prs:
                    pairs.append(((("mt5", a), ("mt5", b)), iv, src, fam, cpx))
            for a, b in itertools.combinations(coins, 2):
                pairs.append(((("binance", a), ("binance", b)), iv, src, "binance", cpx))
            if iv in ("4h", "1d"):
                for c in fresh:
                    pairs.append(((("fresh", c), ("binance", "BTC")), iv, src, "fresh", cpx))
    pairs = [(pa[0], pa[1], iv, src, fam, cp) for pa, iv, src, fam, cp in pairs]
    return single, pairs, costs


def compute():
    OUT.mkdir(parents=True, exist_ok=True)
    single, pairs, costs = build_jobs()
    (OUT / "costs.json").write_text(json.dumps({k: list(v) for k, v in costs.items()}, indent=1))
    print(f"{len(single)} single-series jobs, {len(pairs)} pair jobs", flush=True)
    # big series first, so the pool's tail is short
    order = {"15m": 0, "1h": 1, "4h": 2, "1d": 3}
    single.sort(key=lambda j: (order[j[2]], j[0] != "binance"))
    status = []
    with ProcessPoolExecutor(WORKERS) as pool:
        for job, st, med in pool.map(one, single, chunksize=1):
            status.append(dict(kind="single", venue=job[0], sym=job[1], iv=job[2], source=job[3], fam=job[4],
                               status=st, cost_atr=med))
        for job, st, med in pool.map(pair_one, pairs, chunksize=4):
            status.append(dict(kind="pair", venue=f"{job[0][0]}-{job[1][0]}", sym=f"{job[0][1]}~{job[1][1]}",
                               iv=job[2], source=job[3], fam=job[4], status=st, cost_atr=med))
    pd.DataFrame(status).to_csv(OUT / "jobs.csv", index=False)


# ---------------------------------------------------------------- aggregation

# The pickles read below are this script's own outputs under OUT, never external data.
COLS = ("own", "st", "tw_own", "tw_st", "mom_own", "mom_st", "win_own", "win_st", "cost", "hold")


def load_trades(source, venues=None):
    parts = []
    root = OUT / "trades" / source
    for p in sorted(root.glob("*.pkl")):
        with open(p, "rb") as fh:
            d = pickle.load(fh)
        if not len(d):
            continue
        if venues is not None and d["venue"].iloc[0] not in venues:
            continue
        parts.append(d)
    if not parts:
        return pd.DataFrame()
    d = pd.concat(parts, ignore_index=True)
    if "dft" not in d:
        d["dft"] = np.float32(np.nan)
    extra = [d[(d["rule"] == "z50") & (d["hl"] <= OUF_HL)].assign(rule="z50_ou"),
             d[(d["rule"] == "pair") & (d["dft"] < DF_CRIT)].assign(rule="pair_coint")]
    d = pd.concat([d, *extra], ignore_index=True)
    for k in ("rule", "venue", "sym", "iv", "fam"):
        d[k] = d[k].astype("category")
    d["day"] = (d["ts"] // 86400).astype(np.int32)
    return d


def derive(d):
    """Net R per trade for each exit, its twin and its momentum mirror; first-passage indicators."""
    tw = d["twin"].to_numpy() > 0
    own, st, op, cost = (d[k].to_numpy(np.float64) for k in ("own", "st", "op", "cost"))
    x = pd.DataFrame({
        "own": own - cost, "st": st - cost,
        "tw_own": np.where(tw, own, -own) - cost, "tw_st": np.where(tw, st, op) - cost,
        "mom_own": -own - cost, "mom_st": op - cost,
        "win_own": (own - cost > 0).astype(float), "win_st": (st - cost > 0).astype(float),
        "cost": cost, "hold": d["hold"].to_numpy(float)})
    up, dn = d["up"].to_numpy(), d["dn"].to_numpy()
    twu = np.where(tw, up, dn)
    for N in NS:
        x[f"P{N}"] = (up >= N).astype(float)
        x[f"tP{N}"] = (twu >= N).astype(float)
    return x


def masks(d):
    vr, hu = d["vr"].to_numpy(), d["hu"].to_numpy()
    return {"": np.ones(len(d), bool), "|VR<0.9": vr < VR_T, "|VR>=0.9": vr >= VR_T,
            "|H<0.45": hu < HU_T, "|H>=0.45": hu >= HU_T}


def day_table(d, by=("fam",)):
    """Sums per (variant, *by, iv, side, day): the only thing the statistics need."""
    if not len(d):
        return pd.DataFrame()
    x = derive(d)
    vals = list(x.columns)
    keys = d[["rule", *by, "iv", "side", "day"]].copy()
    for k in ("rule", *by, "iv"):
        keys[k] = keys[k].astype(str)
    out = []
    for name, m in masks(d).items():
        if not m.any():
            continue
        g = pd.concat([keys[m].reset_index(drop=True), x[m].reset_index(drop=True)], axis=1)
        g["N"] = 1.0
        t = g.groupby(["rule", *by, "iv", "side", "day"], observed=True)[vals + ["N"]].sum().reset_index()
        t["variant"] = t["rule"] + name
        out.append(t.drop(columns="rule"))
    return pd.concat(out, ignore_index=True)


def cluster(Sd, Nd):
    N = Nd.sum()
    if N == 0:
        return np.nan, np.nan
    m = Sd.sum() / N
    D = len(Sd)
    if D < 2:
        return m, np.nan
    u = Sd - m * Nd
    return m, float(np.sqrt((u @ u) * D / (D - 1)) / N)


def boot_ci(Sd, Nd, seed, draws=2000):
    rng = np.random.default_rng(seed)
    D = len(Sd)
    if D < 5:
        return np.nan, np.nan
    idx = rng.integers(0, D, (draws, D))
    b = Sd[idx].sum(1) / np.maximum(Nd[idx].sum(1), 1)
    return tuple(np.quantile(b, [0.05, 0.95]))


def cell_stats(t, keys, exits=("own", "st")):
    """One row per cell (keys) and exit, from a day table."""
    from scipy.stats import norm
    rows = []
    if not len(t):
        return pd.DataFrame()
    for kv, g in t.groupby(list(keys), observed=True):
        kv = kv if isinstance(kv, tuple) else (kv,)
        rule = kv[list(keys).index("variant")].split("|")[0] if "variant" in keys else ""
        dd = g.groupby("day").sum(numeric_only=True).sort_index()
        Nd = dd["N"].to_numpy()
        N = Nd.sum()
        if N == 0:
            continue
        cum = np.cumsum(Nd)
        half = cum <= N / 2
        side = g.groupby("side")[["N", "own", "st"]].sum()
        for ex in exits:
            if rule in PAIR_RULES and ex == "st":
                continue
            col = ex
            Sd = dd[col].to_numpy()
            m, se = cluster(Sd, Nd)
            r = dict(zip(keys, kv))
            r.update(exit=ex, n=int(N), days=len(Nd), R=m, se=se,
                     p=float(norm.sf(m / se)) if se and np.isfinite(se) and se > 0 else np.nan,
                     lo=m - 1.645 * se if np.isfinite(se) else np.nan, hi=m + 1.645 * se if np.isfinite(se) else np.nan,
                     R_h1=Sd[half].sum() / max(Nd[half].sum(), 1) if half.any() else np.nan,
                     R_h2=Sd[~half].sum() / max(Nd[~half].sum(), 1) if (~half).any() else np.nan,
                     R_long=side.loc[1, col] / side.loc[1, "N"] if 1 in side.index and side.loc[1, "N"] else np.nan,
                     R_short=side.loc[-1, col] / side.loc[-1, "N"] if -1 in side.index and side.loc[-1, "N"] else np.nan,
                     twin=dd[f"tw_{ex}"].sum() / N, mom=dd[f"mom_{ex}"].sum() / N, win=dd[f"win_{ex}"].sum() / N,
                     cost=dd["cost"].sum() / N, hold=dd["hold"].sum() / N,
                     gross=(dd[col].sum() + dd["cost"].sum()) / N)
            for Nn in NS:
                r[f"P{Nn}"] = dd[f"P{Nn}"].sum() / N
                r[f"tP{Nn}"] = dd[f"tP{Nn}"].sum() / N
            rows.append(r)
    return pd.DataFrame(rows)


def bh(p, q=0.10):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if not ok.any():
        return out
    pp = p[ok]
    order = np.argsort(pp)
    m = len(pp)
    thr = q * np.arange(1, m + 1) / m
    passed = pp[order] <= thr
    k = np.flatnonzero(passed).max() + 1 if passed.any() else 0
    sel = np.zeros(m, bool)
    sel[order[:k]] = True
    out[np.flatnonzero(ok)] = sel
    return out


def period(t, which):
    if not len(t):
        return t
    if which == "disc":
        return t[(t["day"] < SPLIT_DAY) & (t["fam"] != "fresh")]
    if which == "conf":
        return t[(t["day"] >= SPLIT_DAY) | (t["fam"] == "fresh")]
    return t


def pooled(t):
    """The day table plus pooled rows: across timeframes ('all') and across families ('all'), real markets only."""
    if not len(t):
        return t
    real = t[~t["fam"].isin(["deriv", "fresh"])]
    a = real.assign(iv="all")
    b = real.assign(fam="all")
    c = real.assign(iv="all", fam="all")
    return pd.concat([t, a, b, c], ignore_index=True)


def tables(which):
    """Real, iid and GARCH cells for a period, merged; with the walks' R and P(N R) alongside."""
    keys = ("variant", "fam", "iv")
    got = {}
    for src in ("real", "iid", "garch"):
        cache = OUT / f"day_{src}.pkl"
        if cache.exists():
            dt = pd.read_pickle(cache)
        else:
            d = load_trades(src)
            d = d[d["fam"] != "deriv"]
            dt = day_table(d)
            dt.to_pickle(cache)
        got[src] = cell_stats(pooled(period(dt, which)), keys)
    r = got["real"]
    for src in ("iid", "garch"):
        w = got[src][list(keys) + ["exit", "R", "n"] + [f"P{N}" for N in NS]]
        w = w.rename(columns={c: f"{src}_{c}" for c in w.columns if c not in (*keys, "exit")})
        r = r.merge(w, on=[*keys, "exit"], how="left")
    r["excess"] = r["R"] - r[["iid_R", "garch_R"]].mean(axis=1)
    for N in (4, 10):
        r[f"tail{N}"] = r[f"P{N}"] - r[[f"iid_P{N}", f"garch_P{N}"]].mean(axis=1)
    return r


def judge(which, variant, fam, iv, ex, label, seed=7):
    """The frozen pass conditions for one cell on a period (with fresh coins for crypto cells at 4h/1d)."""
    out = {}
    for src in ("real", "iid", "garch"):
        dt = pd.read_pickle(OUT / f"day_{src}.pkl")
        dt = period(dt, which)
        fams = [fam]
        if which == "conf" and fam in ("binance", "crypto") and iv in ("4h", "1d"):
            fams.append("fresh")
        g = dt[(dt["variant"] == variant) & dt["fam"].isin(fams) & (dt["iv"] == iv if iv != "all" else True)]
        if fam == "all":
            g = dt[(dt["variant"] == variant) & ~dt["fam"].isin(["deriv", "fresh"])]
        if not len(g):
            out[src] = None
            continue
        s = cell_stats(g.assign(variant=variant, fam=fam, iv=iv), ("variant", "fam", "iv"), exits=(ex,))
        s = s.iloc[0].to_dict() if len(s) else None
        if s is not None and src == "real":
            dd = g.groupby("day").sum(numeric_only=True)
            s["blo"], s["bhi"] = boot_ci(dd[ex].to_numpy(), dd["N"].to_numpy(), seed)
        out[src] = s
    p, w, gw = out["real"], out["iid"], out["garch"]
    if p is None:
        return dict(label=label, verdict="no trades"), out
    ok = (p["R"] > 0 and p["blo"] > 0 and p["R_h1"] > 0 and p["R_h2"] > 0 and w is not None and gw is not None
          and p["R"] > w["R"] and p["R"] > gw["R"] and p["R"] > p["twin"])
    txt = (f"{label}: R {p['R']:+.3f} [{p['blo']:+.3f}, {p['bhi']:+.3f}] n={p['n']}, halves {p['R_h1']:+.3f} / "
           f"{p['R_h2']:+.3f}; iid {w['R'] if w else np.nan:+.3f}; garch {gw['R'] if gw else np.nan:+.3f}; "
           f"twin {p['twin']:+.3f}; P4R {p['P4']:.3f} (iid {w['P4'] if w else np.nan:.3f}, 1/5 0.200); "
           f"P10R {p['P10']:.3f} (iid {w['P10'] if w else np.nan:.3f}) -> {'PASSES' if ok else 'fails'}")
    return dict(label=label, verdict="PASSES" if ok else "fails", text=txt, **{f"real_{k}": v for k, v in p.items()}), out


def discover():
    compute()
    t = tables("disc")
    t.to_csv(OUT / "discovery_cells.csv", index=False)
    grid = t[t["fam"].isin(FAMS) & t["iv"].isin(IVS) & (t["n"] >= 30)].copy()
    grid["bh"] = bh(grid["p"].to_numpy())
    grid["beats"] = (grid["R"] > grid["iid_R"]) & (grid["R"] > grid["garch_R"]) & (grid["R"] > grid["twin"])
    grid["elig"] = grid["bh"] & grid["beats"] & (grid["R_h1"] > 0) & (grid["R_h2"] > 0)
    grid.to_csv(OUT / "discovery_grid.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    show = ["variant", "fam", "iv", "exit", "n", "R", "lo", "hi", "p", "R_h1", "R_h2", "iid_R", "garch_R", "twin",
            "P4", "iid_P4", "P10", "iid_P10", "bh", "elig"]
    print(f"\nDISCOVERY: {len(grid)} cells with n >= 30; BH (q = 0.10) rejections: {int(grid['bh'].sum())}; "
          f"eligible: {int(grid['elig'].sum())}")
    print(grid.sort_values("R", ascending=False).head(40)[show].round(3).to_string(index=False))
    el = grid[grid["elig"]].sort_values("R", ascending=False)
    if len(el):
        sel, expl = el.iloc[0], False
    else:
        alt = grid[grid["beats"] & (grid["n"] >= 100)].sort_values("R", ascending=False)
        sel, expl = alt.iloc[0], True
    pick = dict(variant=sel["variant"], fam=sel["fam"], iv=sel["iv"], exit=sel["exit"], exploratory=bool(expl),
                discovery=dict(n=int(sel["n"]), R=float(sel["R"]), p=float(sel["p"]), iid=float(sel["iid_R"]),
                               garch=float(sel["garch_R"]), twin=float(sel["twin"])),
                cells_tried=int(len(grid)), bh_rejections=int(grid["bh"].sum()), eligible=int(grid["elig"].sum()))
    (OUT / "mr_selected.json").write_text(json.dumps(pick, indent=1))
    print("\nSELECTED:", json.dumps(pick))


def confirm():
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    sel = json.loads((HERE / "mr_selected.json").read_text())
    t = tables("conf")
    t.to_csv(OUT / "confirmation_cells.csv", index=False)
    grid = t[t["fam"].isin(FAMS) & t["iv"].isin(IVS) & (t["n"] >= 30)].copy()
    grid["bh"] = bh(grid["p"].to_numpy())
    grid.to_csv(OUT / "confirmation_grid.csv", index=False)
    v1, _ = judge("conf", "rsi2_ma", "index", "1d", "own", "P1 Connors RSI(2) + 200-MA, MT5 indices 1d, own exit")
    v2, _ = judge("conf", sel["variant"], sel["fam"], sel["iv"], sel["exit"],
                  f"P2 {'(exploratory) ' if sel['exploratory'] else ''}{sel['variant']} {sel['fam']} {sel['iv']} {sel['exit']}")
    print("\nPRIMARY VERDICTS")
    print(" ", v1.get("text", v1["verdict"]))
    print(" ", v2.get("text", v2["verdict"]))
    (OUT / "verdicts.json").write_text(json.dumps([v1, v2], indent=1, default=float))
    show = ["variant", "fam", "iv", "exit", "n", "R", "lo", "hi", "p", "R_h1", "R_h2", "iid_R", "garch_R", "twin",
            "P4", "iid_P4", "P10", "iid_P10", "bh"]
    print(f"\nCONFIRMATION: {len(grid)} cells with n >= 30; BH (q = 0.10) rejections: {int(grid['bh'].sum())}")
    print(grid.sort_values("R", ascending=False).head(30)[show].round(3).to_string(index=False))
    base = t[t["variant"].isin(BASE + PAIR_RULES) & (t["fam"] == "all")]
    print("\nPOOLED REAL MARKETS (confirmation), per timeframe and all:")
    print(base.sort_values(["variant", "exit", "iv"])[["variant", "iv", "exit", "n", "R", "lo", "hi", "iid_R", "garch_R",
                                                          "twin", "mom", "R_long", "R_short", "P2", "iid_P2", "P4",
                                                          "iid_P4", "P10", "iid_P10"]].round(3).to_string(index=False))
    fresh = t[t["variant"].isin(BASE + PAIR_RULES) & (t["fam"] == "fresh")]
    print("\nFRESH COINS (every date):")
    print(fresh.sort_values(["variant", "exit", "iv"])[["variant", "iv", "exit", "n", "R", "lo", "hi", "iid_R", "garch_R",
                                                           "twin", "P4", "iid_P4"]].round(3).to_string(index=False))
    full = tables("all")
    full.to_csv(OUT / "all_cells.csv", index=False)
    deriv()
    controls()


def deriv():
    keys = ("variant", "sym", "iv")
    res = {}
    for src in ("real", "iid", "garch"):
        d = load_trades(src)
        d = d[d["fam"] == "deriv"]
        d = d[d["rule"].isin(BASE)]
        dt = day_table(d, by=("sym",))
        dt = dt[~dt["variant"].str.contains("|", regex=False)]
        res[src] = cell_stats(pd.concat([dt, dt.assign(iv="all")]), keys)
    r = res["real"]
    for src in ("iid", "garch"):
        w = res[src][[*keys, "exit", "R", "P4"]].rename(columns={"R": f"{src}_R", "P4": f"{src}_P4"})
        r = r.merge(w, on=[*keys, "exit"], how="left")
    r.to_csv(OUT / "deriv_cells.csv", index=False)
    a = r[(r["iv"] == "all")]
    print("\nDERIV (all dates, all timeframes pooled), per symbol, own exit: R real / iid / garch")
    piv = a[a["exit"] == "own"].pivot_table(index="sym", columns="variant", values="R")
    print(piv.round(3).to_string())
    rb = a[a["sym"] == "Range Break 100 Index"]
    print("\nRange Break 100:")
    print(rb[["variant", "exit", "n", "R", "lo", "hi", "iid_R", "garch_R", "twin", "P4", "iid_P4"]].round(3).to_string(index=False))


def controls():
    keys = ("variant", "iv")
    res = {}
    panel_syms = {s for _, s, _ in PANEL}
    for src in ("ou", "ar", "iid"):
        d = load_trades(src)
        d = d[d["sym"].isin(panel_syms) & d["rule"].isin(BASE)]
        dt = day_table(d)
        dt = dt[~dt["variant"].str.contains("|", regex=False)]
        res[src] = cell_stats(pd.concat([dt, dt.assign(iv="all")]), keys).assign(source=src)
    pc = pd.concat(res.values(), ignore_index=True)
    pc.to_csv(OUT / "positive_controls.csv", index=False)
    a = pc[pc["iv"] == "all"]
    print("\nPOSITIVE CONTROLS (panel, all timeframes): gross R (net R) per rule; own and stop exits")
    for ex in ("own", "st"):
        x = a[a["exit"] == ex]
        g = x.pivot_table(index="variant", columns="source", values="gross")
        nn = x.pivot_table(index="variant", columns="source", values="R")
        p4 = x.pivot_table(index="variant", columns="source", values="P4")
        print(f"\n exit {ex}: gross / net / P4R")
        print(pd.concat([g.add_suffix("_gross"), nn.add_suffix("_net"), p4.add_suffix("_P4")], axis=1).round(3).to_string())
    pr = []
    for src in ("coint", "iid", "real"):
        d = load_trades(src, venues=None)
        d = d[d["rule"].isin(PAIR_RULES)]
        if not len(d):
            continue
        dt = day_table(d)
        dt = dt[~dt["variant"].str.contains("|", regex=False)]
        s = cell_stats(pd.concat([dt.assign(fam="all"), dt.assign(fam="all", iv="all")]), ("variant", "fam", "iv"), exits=("own",))
        pr.append(s.assign(source=src))
    pr = pd.concat(pr, ignore_index=True)
    pr.to_csv(OUT / "pair_controls.csv", index=False)
    print("\nPAIRS: cointegrated positive control vs independent walks vs real (all dates, all families)")
    print(pr[pr["iv"] == "all"][["source", "variant", "n", "gross", "R", "lo", "hi", "P2", "P4"]].round(3).to_string(index=False))


# ---------------------------------------------------------------- plots

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    full = pd.read_csv(OUT / "all_cells.csv")
    disc = pd.read_csv(OUT / "discovery_cells.csv")
    conf = pd.read_csv(OUT / "confirmation_cells.csv")
    rules = [r for r in BASE + PAIR_RULES]
    # 1. P(N R) per rule family, real markets pooled, every timeframe and date
    fig, axes = plt.subplots(3, 5, figsize=(26, 14), sharey=True)
    for ax, rule in zip(axes.flat, rules, strict=False):
        r = full[(full["variant"] == rule) & (full["fam"] == "all") & (full["iv"] == "all") & (full["exit"] == "own")]
        if not len(r):
            ax.set_visible(False)
            continue
        r = r.iloc[0]
        ax.plot(NS, [r[f"P{N}"] for N in NS], "-o", label=f"real  R {r['R']:+.3f} (n {int(r['n'])})")
        ax.plot(NS, [r[f"iid_P{N}"] for N in NS], "--s", label=f"iid  R {r['iid_R']:+.3f}")
        ax.plot(NS, [r[f"garch_P{N}"] for N in NS], ":^", label=f"garch  R {r['garch_R']:+.3f}")
        ax.plot(NS, [r[f"tP{N}"] for N in NS], "-.x", label=f"coin twin  R {r['twin']:+.3f}")
        ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"{rule}: P(+N R before -1R, 100 bars)", fontsize=10)
        ax.legend(fontsize=7)
    for ax in axes.flat[len(rules):]:
        ax.set_visible(False)
    fig.suptitle("mean reversion, real markets pooled (FX, metals, indices, energy, crypto CFDs, Binance; all timeframes "
                 "and dates): P(N R) real vs iid and GARCH walks vs coin twin; mean net R (own exit) in the legend")
    fig.tight_layout()
    fig.savefig(OUT / "mr_pnr.png", dpi=70)
    plt.close(fig)
    # 2. heatmap: real - walk R per rule x timeframe, discovery vs confirmation, both exits
    fig, axes = plt.subplots(2, 2, figsize=(16, 14))
    cols = list(IVS) + ["all"]
    for i, ex in enumerate(("own", "st")):
        for j, (name, t) in enumerate((("discovery (before 2024)", disc), ("confirmation (2024 on + fresh coins)", conf))):
            ax = axes[i, j]
            x = t[(t["fam"] == "all") & (t["exit"] == ex) & t["variant"].isin(rules)]
            m = x.pivot_table(index="variant", columns="iv", values="excess").reindex(index=rules, columns=cols)
            nn = x.pivot_table(index="variant", columns="iv", values="R").reindex(index=rules, columns=cols)
            lim = 0.3
            im = ax.imshow(m.to_numpy(float), cmap="RdBu", vmin=-lim, vmax=lim, aspect="auto")
            for (a_, b_), v in np.ndenumerate(m.to_numpy(float)):
                if np.isfinite(v):
                    ax.text(b_, a_, f"{v:+.2f}\n({nn.to_numpy(float)[a_, b_]:+.2f})", ha="center", va="center", fontsize=7)
            ax.set_xticks(range(len(cols)), cols)
            ax.set_yticks(range(len(rules)), rules)
            ax.set_title(f"{name}, exit {ex}: real - mean(iid, GARCH) R (real net R)", fontsize=10)
            fig.colorbar(im, ax=ax, fraction=0.03)
    fig.suptitle("mean R excess over matched walks per rule x timeframe, real markets pooled (Deriv apart)")
    fig.tight_layout()
    fig.savefig(OUT / "mr_heatmap.png", dpi=70)
    plt.close(fig)
    # 3. positive controls
    pc = pd.read_csv(OUT / "positive_controls.csv")
    a = pc[(pc["iv"] == "all")]
    fig, axes = plt.subplots(1, 3, figsize=(24, 7))
    rr = [r for r in BASE if r != "gap"]
    for ax, ex in zip(axes[:2], ("own", "st"), strict=False):
        x = a[a["exit"] == ex].pivot_table(index="variant", columns="source", values="gross").reindex(rr)
        x[["ou", "ar", "iid"]].plot.bar(ax=ax)
        ax.axhline(0, color="k", lw=0.8)
        ax.set_title(f"gross mean R per trade, exit {ex}: OU (half-life 20) and AR(-0.2) vs iid walk", fontsize=10)
    x = a[a["exit"] == "own"].pivot_table(index="variant", columns="source", values="P2").reindex(rr)
    x[["ou", "ar", "iid"]].plot.bar(ax=axes[2])
    axes[2].axhline(1 / 3, color="grey", lw=0.8, ls="--")
    axes[2].set_title("P(+2R before -1R): 1/3 on a martingale", fontsize=10)
    fig.suptitle("positive controls: every rule on reverting series (panel: EURUSD, XAUUSD, US SP 500, BTCUSDT on "
                 "their own timestamps, 15m-1d)")
    fig.tight_layout()
    fig.savefig(OUT / "mr_controls.png", dpi=70)
    plt.close(fig)
    plot_pairs(plt)
    plot_gallery(plt)
    print("plots written", flush=True)


def plot_pairs(plt):
    examples = ((("mt5", "XAUUSD"), ("mt5", "XAGUSD"), "1d"), (("binance", "BTC"), ("binance", "ETH"), "4h"))
    costs = json.loads((OUT / "costs.json").read_text())
    fig, axes = plt.subplots(2, 1, figsize=(20, 10))
    for ax, ((va, A), (vb, Bs), iv) in zip(axes, examples, strict=False):
        da, _ = load(va, A, iv, (costs.get(A) or [None])[0])
        db, _ = load(vb, Bs, iv, (costs.get(Bs) or [None])[0])
        m = da.merge(db, on="ts", suffixes=("_y", "_x"))
        yc, xc = np.log(m["close_y"].to_numpy()), np.log(m["close_x"].to_numpy())
        n, W = len(m), (250 if iv == "1d" else 500)
        A_, B_, S_ = (np.full(n, np.nan) for _ in range(3))
        for r in range(W - 1, n, PAIR_STEP):
            Y, X = yc[r - W + 1:r + 1], xc[r - W + 1:r + 1]
            b = np.cov(X, Y, ddof=0)[0, 1] / X.var()
            a_ = Y.mean() - b * X.mean()
            sl = slice(r, min(n, r + PAIR_STEP))
            A_[sl], B_[sl], S_[sl] = a_, b, (Y - a_ - b * X).std()
        z = (yc - A_ - B_ * xc) / S_
        k0 = max(0, n - 700)
        x = pd.to_datetime(m["ts"].to_numpy()[k0:], unit="s")
        ax.plot(x, z[k0:], lw=0.8, color="#333")
        for lv, col in ((2, "orange"), (-2, "orange"), (4, "red"), (-4, "red"), (0, "grey")):
            ax.axhline(lv, color=col, lw=0.7, ls="--")
        p = _path("real", f"{va}-{vb}", (A, Bs), iv, "pair")
        if p.exists():
            d = pd.read_pickle(p)
            d = d[d["t"] >= k0]
            for _, r in d.iterrows():
                e = int(r.t) + 1
                xb = e + int(r.hold) - 1
                if e >= n:
                    continue
                col = "green" if r.own - r.cost > 0 else "red"
                ax.plot([x[e - k0]], [z[e]], "^" if r.side > 0 else "v", color=col, ms=7)
                if xb < n:
                    ax.plot([x[min(xb, n - 1) - k0]], [z[min(xb, n - 1)]], "o", color=col, ms=4, mfc="none")
        ax.set_title(f"{A}~{Bs} {iv}: rolling-OLS spread z (fit on trailing {W} bars, re-fit every {PAIR_STEP}); "
                     "triangles = entries (green won net, red lost), circles = exits", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "mr_pairs.png", dpi=70)
    plt.close(fig)


def plot_gallery(plt):
    sel = json.loads((HERE / "mr_selected.json").read_text())
    costs = json.loads((OUT / "costs.json").read_text())
    picks = (("P1", "rsi2_ma", "index", "1d", "own"), ("P2", sel["variant"], sel["fam"], sel["iv"], sel["exit"]))
    for tag, variant, fam, iv, ex in picks:
        d = load_trades("real")
        rule = variant.split("|")[0]
        if rule in PAIR_RULES:
            continue  # pairs have their own plot
        d = d[(d["rule"] == rule) & (d["fam"] == fam) & (d["iv"] == iv) & (d["ts"] >= SPLIT)]
        m = masks(d)["|" + variant.split("|")[1] if "|" in variant else ""]
        d = d[m]
        if not len(d):
            continue
        R = d[ex] - d["cost"]
        rng = np.random.default_rng(9)
        for kind, sub in (("winners", d[R > 0]), ("losers", d[R <= 0])):
            if not len(sub):
                continue
            pick = sub.iloc[rng.choice(len(sub), min(6, len(sub)), replace=False)]
            fig, axes = plt.subplots(2, 3, figsize=(21, 10))
            for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
                venue, sym = str(r.venue), str(r.sym)
                df, _ = load(venue, sym, iv, (costs.get(sym) or [None])[0])
                if df is None:
                    continue
                t = int(r.t)
                e = t + 1
                xb = e + int(r.hold if ex == "own" else r.hold_st) - 1
                i0, i1 = max(0, t - 40), min(len(df) - 1, xb + 15)
                w = df.iloc[i0:i1 + 1]
                xx = np.arange(i0, i1 + 1)
                upb = (w["close"] >= w["open"]).to_numpy()
                ax.vlines(xx, w["low"], w["high"], color="#555", lw=0.6)
                ax.bar(xx[upb], (w["close"] - w["open"])[upb], bottom=w["open"][upb], color="#2a9d8f", width=0.7)
                ax.bar(xx[~upb], (w["close"] - w["open"])[~upb], bottom=w["open"][~upb], color="#e76f51", width=0.7)
                c = df["close"]
                if rule in ("rsi2", "rsi2_ma"):
                    ax.plot(xx, c.rolling(5).mean().iloc[i0:i1 + 1], color="#457b9d", lw=0.8, label="SMA5")
                    ax.plot(xx, c.rolling(200).mean().iloc[i0:i1 + 1], color="#6a4c93", lw=0.8, label="SMA200")
                s = int(r.side)
                a = atr(*(df[k].to_numpy(float) for k in ("high", "low", "close")))
                entry = df["open"].iat[e]
                stop = (df["low"].iat[t] - PAD * a[t]) if s > 0 else (df["high"].iat[t] + PAD * a[t])
                ax.axvline(t, color="purple", lw=1, ls=":")
                ax.plot([e], [entry], "k>", ms=9)
                ax.hlines(stop, e, xb, colors="red", lw=1)
                ax.plot([min(xb + 1, i1)], [df["open"].iat[min(xb + 1, len(df) - 1)]], "ks", ms=6)
                ax.set_title(f"{sym} {iv} {'long' if s > 0 else 'short'} {pd.Timestamp(int(r.ts), unit='s'):%Y-%m-%d} "
                             f"-> {float(r[ex] - r.cost):+.2f}R net ({int(r.hold)} bars)", fontsize=9)
            fig.suptitle(f"{tag} {variant} {fam} {iv} exit {ex} ({kind}, confirmation): purple dotted - the signal bar; "
                         "arrow - entry at the next open; red - structural stop (R unit); square - exit", fontsize=11)
            fig.tight_layout()
            fig.savefig(OUT / f"mr_gallery_{tag}_{kind}.png", dpi=70)
            plt.close(fig)


# ---------------------------------------------------------------- smoke

def smoke():
    venue, sym, iv = os.environ.get("SMOKE", "binance:BTC:4h").split(":")
    global OUT
    OUT = OUT / "smoke"
    cost = mt5_cost(sym)[0] if venue == "mt5" else None
    fam = "binance" if venue == "binance" else __import__("run").FAMILY.get(sym, "fx")
    import time
    for src in os.environ.get("SOURCES", "iid,ou").split(","):
        t0 = time.time()
        p = _path(src, venue, sym, iv)
        if p.exists():
            p.unlink()
        one((venue, sym, iv, src, fam, cost))
        d = pd.read_pickle(p)
        x = derive(d)
        g = pd.concat([d[["rule"]], x], axis=1).groupby("rule", observed=True)
        s = g[["own", "st", "cost", "P2", "P4", "hold"]].mean()
        s["gross_own"] = s["own"] + s["cost"]
        s["n"] = g.size()
        print(f"\n{src} {venue} {sym} {iv}: {time.time() - t0:.1f}s")
        print(s.round(3).to_string())


def main():
    {"discover": discover, "confirm": confirm, "plot": plot, "smoke": smoke, "compute": compute}[os.environ.get("MODE", "discover")]()


if __name__ == "__main__":
    main()
