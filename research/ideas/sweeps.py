"""Liquidity sweeps, protected highs and lows and broken zones on Deriv's synthetics, against our own
walks and against real markets.

Frozen in `sweep_rule.json` before any real-data run; the patterns are MCFL entities (`mcfl/sweeps.py`
and the v2 entities it reuses). Deriv's synthetics are a real market whose generators are published:
the expectation is that every pattern occurs at the rate a walk produces it and predicts nothing.

  base      events per 1,000 bars of every pattern, real against iid, GARCH and bar-bootstrap walks
  predict   P(the nearest standing swing low is swept within 10 bars): geometry (G0) against G0 + causal
            features (G1), held out, day-bootstrap AUC gain
  trades    after each pattern: P(k ATR the trade's way before k against), and the trade - next open (E)
            or a limit back at the level (L), stop beyond the sweep's wick, 2-ATR trail (E1) and 2R (X2)
  protected strong, weak and sweep-strong lows: P(held until the next break of structure)
  spikes    Boom / Crash spikes and Jump jumps on one-minute bars: rate, clustering, predictability

  OUT=... MT5BT_DB=... RESEARCH_DB=... MODE=run|plot|smoke python research/ideas/sweeps.py
"""
from __future__ import annotations

import json
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

OUT = Path(os.environ.get("OUT", ".data/sweeps"))
SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
IVS = tuple(SEC)
DIFFUSIVE = ("Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index",
             "Volatility 100 Index", "Step Index", "Step Index 200", "Step Index 500", "Drift Switch Index 10",
             "Drift Switch Index 20", "Drift Switch Index 30")
JUMPY = ("Boom 1000 Index", "Crash 1000 Index", "Jump 50 Index", "Range Break 100 Index")
DERIV = DIFFUSIVE + JUMPY
REAL = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "XAGUSD", "US SP 500", "US Tech 100", "Germany 40",
        "Japan 225", "BTCUSD", "ETHUSD", "SOLUSD")
NULLS = ("walk", "garch", "boot")
WALK_STEPS = 256
PAD, SLIP, MINRISK, TRAIL = 0.1, 0.05, 0.2, 2.0
LIMIT_BARS = 5
REV_K = (1, 2)
REV_MAX = 500
NS = (0.5, 1, 2, 4, 10)
N_PRED = 10
PRED_STEP = {"15m": 6, "1h": 3, "4h": 1, "1d": 1}
WARM = 300
PATTERNS = ("P1_SFP", "P2_TURTLE", "P3_POOL", "P4_CRT", "P5_RAID", "P5_JUDAS", "P6_SHIFT", "P7_ZONE", "P7_INDUCE",
            "P8_BRK_ZONE", "P8_REC_ZONE", "P8_BRK_VOID", "P8_REC_VOID")
SESSION_IVS = ("15m", "1h")
GRADES = ("WEAK", "STRONG", "SWEEP_STRONG")


def scope(sym):
    return "diffusive" if sym in DIFFUSIVE else "jumpy" if sym in JUMPY else "real"


def hold_bars(iv):
    return max(20, int(10 * 86400 / SEC[iv]))


# ---------------------------------------------------------------- data and nulls

def load(sym, iv):
    """The broker's bars and the spread floor in price."""
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None, None
    df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "volume"]]
    df["ts"] = df["ts"].astype(np.int64)
    spec = load_specs(R.DB).get(sym)
    return df, (R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0)


def boot_bars(df, seed):
    """iid bar bootstrap: the series' own bars, relative to their open, drawn with replacement and chained."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    rng = np.random.default_rng(seed)
    i = rng.integers(0, len(df), len(df))
    dc, dh, dl = (c - o)[i], (h - o)[i], (l - o)[i]
    op = o[0] + np.r_[0.0, np.cumsum(dc)[:-1]]
    return pd.DataFrame({"open": op, "high": op + dh, "low": op + dl, "close": op + dc, "volume": 0.0})


def published_sigma(sym, iv, df):
    n = float(sym.split()[1])
    return n / 100 * float(df["close"].median()) * np.sqrt(SEC[iv] / 31_536_000)


def make_source(df, sym, iv, source):
    from mcfl import synth
    n = len(df)
    seed = zlib.crc32(f"sweeps{sym}{iv}{source}".encode()) % 100000
    sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
    if source == "walk":
        out = synth.walk(n, sigma=sigma, seed=seed, steps=WALK_STEPS)
    elif source == "garch":
        out = synth.garch(n, sigma=sigma, seed=seed, steps=WALK_STEPS)
    elif source == "boot":
        out = boot_bars(df, seed)
    elif source == "pub":
        out = synth.walk(n, sigma=published_sigma(sym, iv, df), seed=seed, steps=WALK_STEPS)
    else:
        raise ValueError(source)
    out = out.reset_index(drop=True).iloc[:n].copy()
    out["ts"] = df["ts"].to_numpy()[:len(out)]
    out["volume"] = 0.0
    return out[["ts", "open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------- the patterns as signals

def signals(ch, n, iv):
    """Every traded pattern as (pattern, side, k = the bar it is known, a = the first bar of its wick,
    level or nan, entity bar, extra). side +1 is a long: a low swept, read on the chart as it is."""
    ids = ch.by_id()
    out = []

    def side_low_swept(e):  # BREACH_REVERT / CLOSE_REVERT / POOL_TAKEN / PURGE / SESSION_EXTREME_TAKEN
        return 1 if e.dir.value == "DOWN" else -1

    for e in ch.of("BREACH_REVERT"):
        out.append(("P1_SFP", side_low_swept(e), e.known_at, e.at, e.get("level"), {}))
    for e in ch.of("CLOSE_REVERT"):
        out.append(("P2_TURTLE", side_low_swept(e), e.known_at, e.get("through"), e.get("level"), {}))
    for e in ch.of("POOL_TAKEN"):
        if e.get("closed_back"):
            out.append(("P3_POOL", side_low_swept(e), e.known_at, e.at, e.get("level"), {}))
    for e in ch.of("PURGE"):
        lvl = e.get("upper_edge") if e.dir.value == "UP" else e.get("lower_edge")
        out.append(("P4_CRT", side_low_swept(e), e.known_at, e.at, lvl, {}))
    if iv in SESSION_IVS:
        for e in ch.of("SESSION_EXTREME_TAKEN"):
            if e.get("session") == "ASIA" and e.get("closed_back"):
                out.append(("P5_RAID", side_low_swept(e), e.known_at, e.at, e.get("level"), {}))
        for e in ch.of("SESSION_FIRST_MOVE"):
            if e.get("name") == "LONDON" and e.get("kind") == "SESSION":
                # a first swing high (UP) is faded short; the wick is the extreme's bar
                out.append(("P5_JUDAS", -1 if e.dir.value == "UP" else 1, e.known_at, e.at, e.get("price"), {}))
    seen = set()
    for e in sorted(ch.of("SWEEP_SHIFT"), key=lambda e: e.at):
        if e.get("sweep") in seen:
            continue  # one trade per sweep: its first shift
        seen.add(e.get("sweep"))
        sw = ids[e.get("sweep")]
        a = sw.get("through") if sw.type == "CLOSE_REVERT" else sw.at
        out.append(("P6_SHIFT", 1 if e.dir.value == "UP" else -1, e.known_at, a, e.get("level"),
                    {"sweep_type": sw.type, "shift_type": e.get("shift_type")}))
    for e in ch.of("BREAKER_RETEST", "RECLAIM"):
        kind = e.get("kind")
        up = e.dir.value == "UP"
        if e.type == "BREAKER_RETEST":  # against the old structure: short a broken up structure
            out.append((f"P8_BRK_{kind}", -1 if up else 1, e.known_at, e.at, e.get("level"), {}))
        else:  # with it: the stop under the lowest low since the break
            out.append((f"P8_REC_{kind}", 1 if up else -1, e.known_at, e.get("broke_at"), e.get("level"), {}))
    return [s for s in out if s[2] + 1 < n]


def zone_signals(ch):
    """P7: every zone's first revisit (P7_ZONE) and those with an INDUCEMENT (P7_INDUCE)."""
    ids = ch.by_id()
    ind = {e.get("zone") for e in ch.of("INDUCEMENT")}
    out = []
    for e in ch.of("REVISIT"):
        if e.get("count") != 1:
            continue
        z = ids[e.get("zone")]
        side = 1 if z.dir.value == "UP" else -1
        out.append((side, e.at, side * z.get("near"), side * z.get("far"), z.get("atr"), z.id in ind))
    return out


# ---------------------------------------------------------------- trades

def exits(o, h, l, c, f, entry, stop, a_t, hold, worst):
    """A long filled at `entry` on bar f (its own bar's later path unknown: a stop on the fill bar is hit
    first), stop at `stop`: E1 (2-ATR trail behind completed bars' best high) and X2 (2R target). With
    `worst`, a stop hit fills at the bar's low instead (jumps through a stop on a jumpy index). Returns
    E1, X2 and the most R the E1 trade reached, all in R before costs, and the E1 exit bar."""
    n = len(c)
    risk = entry - stop
    end = min(n - 1, f + hold)

    def fill(j, st):
        px = l[j] if worst else (min(o[j], st) if j > f else st)
        return (px - SLIP * a_t - entry) / risk

    # E1
    R, ex = None, end
    mfe = max(0.0, (c[f] - entry) / risk)
    best, st = max(entry, c[f]), stop
    if l[f] <= stop:
        R, ex, mfe = fill(f, stop), f, 0.0
    else:
        for j in range(f + 1, end + 1):
            st = max(st, best - TRAIL * a_t)
            if l[j] <= st:
                R, ex = fill(j, st), j
                break
            best = max(best, h[j])
            mfe = max(mfe, (h[j] - entry) / risk)
        if R is None:
            R = (c[end] - entry) / risk
    e1 = R
    # X2
    tgt = entry + 2 * risk
    R = None
    if l[f] <= stop:
        R = fill(f, stop)
    elif c[f] >= tgt:
        R = 2.0
    else:
        for j in range(f + 1, end + 1):
            if l[j] <= stop:
                R = fill(j, stop)
                break
            if h[j] >= tgt:
                R = (max(o[j], tgt) - entry) / risk
                break
        if R is None:
            R = (c[end] - entry) / risk
    return e1, R, mfe, ex


def reversal(h, l, c, k, a_t, K):
    """From close k: 1 if K ATR up comes first, 0 if K ATR down, 0.5 if one bar reaches both, nan if neither."""
    up, dn = c[k] + K * a_t, c[k] - K * a_t
    hh, ll = h[k + 1:k + 1 + REV_MAX], l[k + 1:k + 1 + REV_MAX]
    iu, idn = np.flatnonzero(hh >= up), np.flatnonzero(ll <= dn)
    iu = iu[0] if len(iu) else np.inf
    idn = idn[0] if len(idn) else np.inf
    if iu == idn:
        return np.nan if not np.isfinite(iu) else 0.5
    return 1.0 if iu < idn else 0.0


def spike_sides(sym):
    """The trade sides whose stop sits on the jump side: Boom spikes up (a short's stop), Crash down (a
    long's), Jump and Range Break either way. Empty for a diffusive index."""
    if sym.startswith("Boom"):
        return (-1,)
    if sym.startswith("Crash"):
        return (1,)
    return (1, -1) if sym in JUMPY else ()


def trade_rows(df, ch, iv, cost_atr, atr, jumpy):
    from mcfl.parse import flip
    n = len(df)
    frames = {1: df, -1: flip(df)}
    arr = {s: tuple(f[k].to_numpy(float) for k in ("open", "high", "low", "close")) for s, f in frames.items()}
    hold = hold_bars(iv)
    ts = df["ts"].to_numpy()
    rows = []

    def one(pat, side, k, f, entry, stop, extra, limit=False, a=None, lvl=np.nan):
        o, h, l, c = arr[side]
        a_t = atr[k]
        risk = entry - stop
        if not (a_t > 0 and risk >= MINRISK * a_t):
            return
        cost = cost_atr[k] * a_t / risk
        e1, x2, mfe, ex = exits(o, h, l, c, f, entry, stop, a_t, hold, False)
        r = dict(pattern=pat, side=side, k=k, f=f, ex=ex, a=k if a is None else a, level=lvl, ts=int(ts[f]),
                 risk_atr=risk / a_t, cost=cost,
                 E1=e1 - cost, X2=x2 - cost, mfe=mfe, limit=limit, **extra)
        if jumpy:  # a tuple of spike sides; the other side keeps the bar fill
            if side in jumpy:
                w1, w2, _, _ = exits(o, h, l, c, f, entry, stop, a_t, hold, True)
                r.update(E1w=w1 - cost, X2w=w2 - cost)
            else:
                r.update(E1w=r["E1"], X2w=r["X2"])
        if not limit:
            for K in REV_K:
                r[f"rev{K}"] = reversal(h, l, c, k, a_t, K)
        rows.append(r)

    for pat, side, k, a, lvl, extra in signals(ch, n, iv):
        o, h, l, c = arr[side]
        wick = l[a:k + 1].min()
        if pat.startswith("P8_BRK"):
            wick = l[k]  # the retest bar's extreme (in the trade's frame)
        stop = wick - PAD * atr[k]
        lv = float(lvl) if lvl is not None and np.isfinite(lvl) else np.nan
        one(pat, side, k, k + 1, o[k + 1], stop, extra, a=a, lvl=lv)
        if np.isfinite(lv):  # L: a limit back at the swept level, live LIMIT_BARS bars
            L = side * lv
            if L < c[k]:
                for f in range(k + 1, min(n, k + 1 + LIMIT_BARS)):
                    if l[f] <= L:
                        one(pat, side, k, f, min(o[f], L), stop, extra, limit=True, a=a, lvl=lv)
                        break
    for side, r, near, far, A, induced in zone_signals(ch):
        o, h, l, c = arr[side]
        if not (A and A > 0):
            continue
        stop = far - PAD * A
        for pat in ("P7_ZONE",) + (("P7_INDUCE",) if induced else ()):
            one(pat, side, r, r, min(o[r], near), stop, {}, limit=True)
    return rows


# ---------------------------------------------------------------- protected levels

def protected_rows(ch, df, atr):
    """Each PROTECTED low: its grade, distance when graded, and whether it held until the next break."""
    c = df["close"].to_numpy(float)
    taken = {e.get("protected"): e for e in ch.of("PROTECTED_TAKEN")}
    brk = {d: sorted(e.known_at for e in ch.of("BREAK") if e.dir.value == d) for d in ("UP", "DOWN")}
    rows = []
    for e in ch.of("PROTECTED"):
        d = e.dir.value
        side = 1 if d == "UP" else -1
        k = e.known_at
        nb = brk[d]
        i = np.searchsorted(nb, k, side="right")
        nxt = nb[i] if i < len(nb) else None
        tk = taken.get(e.id)
        t_at = tk.at if tk is not None else None
        if t_at is not None and (nxt is None or t_at <= nxt):
            out = "lost"
        elif nxt is not None:
            out = "held"
        else:
            out = "censored"
        rows.append(dict(grade=e.get("grade"), bos=e.get("bos"), k=k, side=side,
                         dist=side * (c[k] - e.get("level")) / atr[k] if atr[k] > 0 else np.nan,
                         outcome=out, swept=bool(tk is not None and tk.get("closed_back")),
                         held50=bool(t_at is None or t_at - k > 50) if k + 50 < len(c) else np.nan))
    return rows


# ---------------------------------------------------------------- prediction rows

def predict_rows(df, ch, iv, atr):
    """At sampled bars, on each frame, the nearest standing swing low below the close and whether it is
    swept within N_PRED bars, with the G0 and G1 features (all known at t)."""
    from mcfl.parse import flip
    n = len(df)
    step = PRED_STEP[iv]
    ts = df["ts"].to_numpy()
    a = atr
    a5 = pd.Series(a).rolling(5).mean().to_numpy()
    a50 = pd.Series(a).rolling(50).mean().to_numpy()
    a100 = pd.Series(a).rolling(100).mean().to_numpy()
    rows = []
    for side, frame in ((1, df), (-1, flip(df))):
        o, h, l, c = (frame[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        d = "DOWN" if side > 0 else "UP"
        ext = [e for e in ch.of("EXTREME") if e.dir.value == d]
        P = np.array([side * e.get("price") for e in ext], float)
        kn = np.array([e.known_at for e in ext], int)
        at = np.array([e.at for e in ext], int)
        tk = np.full(len(ext), n)
        for i in range(len(ext)):
            hit = np.flatnonzero(l[kn[i] + 1:] < P[i])
            if len(hit):
                tk[i] = kn[i] + 1 + hit[0]
        takes = np.zeros(n)
        np.add.at(takes, tk[tk < n], 1)
        takes20 = pd.Series(takes).rolling(20, min_periods=1).sum().to_numpy()
        br = np.zeros(n)
        for e in ch.of("BREACH_REVERT"):
            if e.dir.value == d:
                br[e.at] += 1
        br20 = pd.Series(br).rolling(20, min_periods=1).sum().to_numpy()
        rng_ = h - l
        lw = np.where(rng_ > 0, (np.minimum(o, c) - l) / np.where(rng_ > 0, rng_, 1), 0.0)
        lw10 = pd.Series(lw).rolling(10).mean().to_numpy()
        r10 = (pd.Series(h).rolling(10).max() - pd.Series(l).rolling(10).min()).to_numpy()
        for t in range(WARM, n - N_PRED, step):
            if not a[t] > 0:
                continue
            m = (kn <= t) & (tk > t) & (P < c[t])
            if not m.any():
                continue
            j = np.flatnonzero(m)
            i = j[np.argmax(P[j])]
            L = P[i]
            pool = int(np.sum(np.abs(P[j] - L) <= 0.1 * a[t]))
            take = tk[i] <= t + N_PRED
            swept = bool(take and c[tk[i]] >= L)
            dist = (c[t] - L) / a[t]
            rows.append((side, t, int(ts[t]), int(ts[min(n - 1, t + N_PRED)]), dist, pool, np.log1p(t - at[i]),
                         br20[t], lw10[t], a5[t] / a50[t] if a50[t] > 0 else np.nan, r10[t] / a50[t] if a50[t] > 0 else np.nan,
                         a[t] / a100[t] if a100[t] > 0 else np.nan, takes20[t], (c[t] - c[t - 20]) / a[t], take, swept))
    cols = ("side", "t", "ts", "ts_end", "dist", "pool", "lage", "br20", "lw10", "a5_50", "r10_50", "a14_100", "takes20",
            "drift20", "y_take", "y_sweep")
    d = pd.DataFrame(rows, columns=cols)
    for k in ("dist", "lage", "br20", "lw10", "a5_50", "r10_50", "a14_100", "takes20", "drift20"):
        d[k] = d[k].astype(np.float32)
    return d


# ---------------------------------------------------------------- one series

def counts(ch, n, iv):
    """Events per pattern (both directions), for the base rates."""
    c = {p: 0 for p in PATTERNS}
    for s in signals(ch, n + 1, iv):
        c[s[0]] += 1
    zs = zone_signals(ch)
    c["P7_ZONE"], c["P7_INDUCE"] = len(zs), sum(1 for z in zs if z[5])
    for g in GRADES:
        c[f"P9_{g}"] = sum(1 for e in ch.of("PROTECTED") if e.get("grade") == g)
    c["SWING"] = len(ch.of("EXTREME"))
    c["ZONE"] = len(ch.of("ZONE"))
    c["VOID"] = len(ch.of("VOID"))
    return c


def one(job):
    from mcfl import candles
    from mcfl.parse import parse
    venue, sym, iv, source, do_pred = job
    try:
        df, fee_px = load(sym, iv)
    except Exception as ex:  # noqa: BLE001
        print(f"  load failed {sym} {iv}: {ex}", flush=True)
        return None
    if df is None or len(df) < 400:
        return None
    atr_real = np.asarray(candles.table(df)["atr"], float)
    cost_atr = fee_px / np.maximum(atr_real, 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        df = make_source(df, sym, iv, source)
    n = len(df)
    ch = parse(df, sec=SEC[iv])
    atr = np.asarray(candles.table(df)["atr"], float)
    tag = dict(venue=venue, scope=scope(sym), src=source, sym=sym, iv=iv)
    mid = int(df["ts"].iloc[n // 2])
    cnt = dict(tag, n=n, mid=mid, **counts(ch, n, iv))
    T = pd.DataFrame(trade_rows(df, ch, iv, cost_atr, atr, spike_sides(sym)))
    if len(T):
        T = T.assign(**tag, mid=mid)
    Pr = pd.DataFrame(protected_rows(ch, df, atr))
    if len(Pr):
        Pr = Pr.assign(**tag, ts=df["ts"].to_numpy()[Pr["k"].to_numpy()], mid=mid)
    X = predict_rows(df, ch, iv, atr) if do_pred else pd.DataFrame()
    if len(X):
        X = X.assign(**tag, mid=mid)
    print(f"  {venue} {source} {sym} {iv}: {n} bars, {len(T)} trades, {len(Pr)} protected, {len(X)} rows", flush=True)
    return cnt, T, Pr, X


def jobs_all():
    out = []
    for iv in IVS:
        for sym in DERIV:
            for src in ("real",) + NULLS:
                out.append(("deriv", sym, iv, src, src in ("real", "walk", "garch")))
            if sym.startswith("Volatility"):
                out.append(("deriv", sym, iv, "pub", False))
        for sym in REAL:
            for src in ("real",) + NULLS:
                out.append(("mt5", sym, iv, src, src in ("real", "walk", "garch")))
    # the longest first, so the pool ends together
    return sorted(out, key=lambda j: IVS.index(j[2]))


# ---------------------------------------------------------------- spikes (pattern 10)

SPIKE_FEEDS = ("boom_300_index", "boom_500_index", "boom_1000_index", "crash_300_index", "crash_500_index",
               "crash_1000_index", "jump_10_index", "jump_25_index", "jump_50_index", "jump_75_index", "jump_100_index")
SPIKE_SIGMAS = 8.0


def spikes():
    import sqlite3

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    db = os.environ.get("RESEARCH_DB")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = []
    rng = np.random.default_rng(10)
    for feed in SPIKE_FEEDS:
        d = pd.read_sql_query("SELECT ts, open, high, low, close FROM bars WHERE feed = ? AND interval = '1m' ORDER BY ts",
                              conn, params=(feed,))
        if len(d) < 1000:
            continue
        x = (d["close"] - d["open"]).to_numpy(float)
        sig = 1.4826 * np.median(np.abs(x - np.median(x)))
        if feed.startswith("boom"):
            s = x > SPIKE_SIGMAS * sig
        elif feed.startswith("crash"):
            s = x < -SPIKE_SIGMAS * sig
        else:
            s = np.abs(x) > SPIKE_SIGMAS * sig
        n = len(s)
        p = s.mean()
        idx = np.flatnonzero(s)
        w = np.diff(idx)
        hours = pd.Series(s.astype(int)).groupby(np.arange(n) // 60).sum()
        acf1 = float(np.corrcoef(s[:-1], s[1:])[0, 1])
        # predict a spike in the next bar
        since = np.full(n, np.nan)
        last = -10_000
        for i in range(n):
            since[i] = i - last
            if s[i]:
                last = i
        cnt60 = pd.Series(s.astype(float)).rolling(60, min_periods=1).sum().to_numpy()
        abs5 = pd.Series(np.abs(x)).rolling(5, min_periods=1).mean().to_numpy() / sig
        Xf = np.c_[np.log1p(np.minimum(since, 10_000)), cnt60, abs5][:-1]
        y = s[1:]
        h = len(y) // 2

        def auc(yy):
            m = LogisticRegression(C=1.0, max_iter=500).fit(Xf[:h], yy[:h])
            return float(roc_auc_score(yy[h:], m.predict_proba(Xf[h:])[:, 1])) if yy[h:].any() else np.nan
        rows.append(dict(feed=feed, bars=n, spikes=int(s.sum()), per_1000=1000 * p, minutes_per_spike=1 / p if p else np.nan,
                         wait_cv=float(w.std() / w.mean()) if len(w) > 2 else np.nan, cv_geometric=float(np.sqrt(1 - p)),
                         hourly_dispersion=float(hours.var() / hours.mean()) if hours.mean() > 0 else np.nan,
                         acf1=acf1, auc_next=auc(y), auc_shuffled=auc(rng.permutation(y))))
        print(f"  spikes {feed}: {rows[-1]}", flush=True)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- statistics

def boot(x, rng, draws=2000, col="R"):
    """Day-bootstrap 90% interval of the mean, and the one-sided p (share of draws at or below 0)."""
    d = x.groupby(x["ts"] // 86400)[col].agg(["sum", "count"])
    s, k = d["sum"].to_numpy(), d["count"].to_numpy()
    idx = rng.integers(0, len(d), (draws, len(d)))
    b = s[idx].sum(1) / k[idx].sum(1)
    return float(np.quantile(b, 0.05)), float(np.quantile(b, 0.95)), float((b <= 0).mean())


def bh(p, q=0.10):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if not ok.any():
        return out
    pv = p[ok]
    o = np.argsort(pv)
    m = len(pv)
    thr = q * (np.arange(1, m + 1) / m)
    passed = pv[o] <= thr
    kmax = np.max(np.flatnonzero(passed)) if passed.any() else -1
    sel = np.zeros(m, bool)
    if kmax >= 0:
        sel[o[:kmax + 1]] = True
    out[np.flatnonzero(ok)] = sel
    return out


def trade_table(T, rng, by, ex_col):
    rows = []
    for key, g in T.groupby(list(by)):
        y = g.assign(R=g[ex_col])
        lo, hi, p = boot(y, rng) if len(y) > 30 else (np.nan, np.nan, np.nan)
        r = dict(zip(by, key if isinstance(key, tuple) else (key,)), exit=ex_col, n=len(y), R=y["R"].mean(),
                 lo=lo, hi=hi, p=p, win=(y["R"] > 0).mean(),
                 R_h1=y.loc[y["ts"] < y["mid"], "R"].mean(), R_h2=y.loc[y["ts"] >= y["mid"], "R"].mean(),
                 cost=y["cost"].mean(), risk_atr=y["risk_atr"].median(),
                 **{f"P{N}R": (y["mfe"] >= N).mean() for N in NS})
        if "rev1" in y:
            r.update(rev1=y["rev1"].mean(), rev2=y["rev2"].mean())
        rows.append(r)
    return pd.DataFrame(rows)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = jobs_all()
    for key, pos in (("ONLY", 1), ("ONLY_IV", 2), ("ONLY_SRC", 3)):  # smoke runs: a subset of the jobs
        if os.environ.get(key):
            jobs = [j for j in jobs if j[pos] in os.environ[key].split(",")]
    workers = int(os.environ.get("WORKERS", 8))
    C, T, P, X = [], [], [], []
    with ProcessPoolExecutor(workers) as pool:
        for g in pool.map(one, jobs):
            if g is None:
                continue
            C.append(g[0])
            for lst, d in zip((T, P, X), g[1:]):
                if len(d):
                    lst.append(d)
    C = pd.DataFrame(C)
    T = pd.concat(T, ignore_index=True)
    P = pd.concat(P, ignore_index=True)
    X = pd.concat(X, ignore_index=True) if X else pd.DataFrame()
    C.to_csv(OUT / "counts.csv", index=False)
    T.to_pickle(OUT / "trades.pkl.gz")
    P.to_pickle(OUT / "protected.pkl.gz")
    if len(X):
        X.to_pickle(OUT / "predict_rows.pkl.gz")
    S = spikes() if os.environ.get("RESEARCH_DB") else pd.DataFrame()
    if len(S):
        S.to_csv(OUT / "spikes.csv", index=False)
    report(C, T, P, X, S)


def base_rates(C):
    pats = [p for p in C.columns if p.startswith("P")] + ["SWING", "ZONE", "VOID"]
    long = C.melt(id_vars=["venue", "scope", "src", "sym", "iv", "n"], value_vars=pats, var_name="pattern", value_name="count")
    long["per_1000"] = 1000 * long["count"] / long["n"]
    return long


def wauc(y, order, w):
    """AUC of scores already sorted by `order` (ascending), with row weights w; ties broken by order."""
    yy, ww = y[order], w[order]
    neg = np.cumsum(ww * (~yy))
    pos_w = ww * yy
    wp, wn = pos_w.sum(), (ww * (~yy)).sum()
    return float((pos_w * (neg - ww * (~yy))).sum() / (wp * wn)) if wp > 0 and wn > 0 else np.nan


def predict_report(X, rng):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler
    if not len(X):
        return pd.DataFrame()
    G1 = ["pool", "lage", "br20", "lw10", "a5_50", "r10_50", "a14_100", "takes20", "drift20"]
    X = X.copy()
    X["ldist"] = np.log1p(np.maximum(X["dist"], 0))
    X["dist2"] = X["dist"] ** 2
    for iv in IVS:
        X[f"iv_{iv}"] = (X["iv"] == iv).astype(float)
    G0 = ["dist", "ldist", "dist2"] + [f"iv_{iv}" for iv in IVS]
    rows = []
    for (sc, src), g in X.groupby(["scope", "src"]):
        g = g.replace([np.inf, -np.inf], np.nan).dropna(subset=G0 + G1)
        tr, te = g[g["ts_end"] < g["mid"]], g[g["ts"] >= g["mid"]]
        for target, sub_tr, sub_te in (("y_sweep", tr, te), ("y_take", tr, te),
                                       ("y_sweep|take", tr[tr["y_take"]], te[te["y_take"]])):
            ycol = "y_sweep" if target != "y_take" else "y_take"
            if len(sub_tr) < 500 or sub_tr[ycol].nunique() < 2:
                continue
            if len(sub_te) > 400_000:
                sub_te = sub_te.sample(400_000, random_state=1)
            preds = {}
            for name, cols in (("G0", G0), ("G0+G1", G0 + G1)):
                sc_ = StandardScaler().fit(sub_tr[cols].to_numpy(float))
                m = LogisticRegression(C=1.0, max_iter=1000).fit(sc_.transform(sub_tr[cols].to_numpy(float)), sub_tr[ycol])
                preds[name] = m.predict_proba(sc_.transform(sub_te[cols].to_numpy(float)))[:, 1]
            y = sub_te[ycol].to_numpy()
            a0, a1 = roc_auc_score(y, preds["G0"]), roc_auc_score(y, preds["G0+G1"])
            day = (sub_te["ts"] // 86400).to_numpy()
            ud, inv = np.unique(day, return_inverse=True)
            yb = y.astype(bool)
            o0, o1 = np.argsort(preds["G0"], kind="stable"), np.argsort(preds["G0+G1"], kind="stable")
            gains = []
            for _ in range(1000):
                w = np.bincount(rng.integers(0, len(ud), len(ud)), minlength=len(ud))[inv].astype(float)
                gains.append(wauc(yb, o1, w) - wauc(yb, o0, w))
            r = dict(scope=sc, src=src, target=target, n_train=len(sub_tr), n_test=len(sub_te), base=float(y.mean()),
                     auc_G0=a0, auc_G1=a1, gain=a1 - a0, lo=float(np.quantile(gains, 0.05)), hi=float(np.quantile(gains, 0.95)))
            for iv in IVS:
                mk = (sub_te["iv"] == iv).to_numpy()
                if mk.sum() > 200 and 0 < y[mk].mean() < 1:
                    r[f"gain_{iv}"] = roc_auc_score(y[mk], preds["G0+G1"][mk]) - roc_auc_score(y[mk], preds["G0"][mk])
            rows.append(r)
            print(f"  predict {sc} {src} {target}: G0 {a0:.4f} gain {a1 - a0:+.4f} [{r['lo']:+.4f}, {r['hi']:+.4f}]", flush=True)
    return pd.DataFrame(rows)


def report(C, T, P, X, S):
    rng = np.random.default_rng(71)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 2000)
    pd.set_option("display.max_columns", 60)
    # (a) base rates
    B = base_rates(C)
    B.to_csv(OUT / "base_rates.csv", index=False)
    piv = B.groupby(["scope", "pattern", "src"])["per_1000"].mean().unstack("src")
    for s in ("walk", "garch", "boot", "pub"):
        if s in piv:
            piv[f"real/{s}"] = piv["real"] / piv[s]
    piv.round(3).to_csv(OUT / "base_rates_pivot.csv")
    print("\n(a) events per 1,000 bars, mean over symbols and timeframes:")
    print(piv.round(3).to_string())
    pv2 = B.groupby(["scope", "iv", "pattern", "src"])["per_1000"].mean().unstack("src")
    pv2.round(3).to_csv(OUT / "base_rates_by_tf.csv")
    # (b) prediction
    Pd = predict_report(X, rng)
    if len(Pd):
        Pd.to_csv(OUT / "predict.csv", index=False)
        print("\n(b) prediction, held-out AUC gain of G0+G1 over G0:")
        print(Pd.round(4).to_string(index=False))
    # (c) trades
    T = T.copy()
    E = T[~T["limit"] | T["pattern"].str.startswith("P7")]
    L = T[T["limit"] & ~T["pattern"].str.startswith("P7")]
    tabs = []
    for name, d in (("E", E), ("L", L)):
        for ex in ("E1", "X2", "E1w", "X2w"):
            if ex not in d:
                continue
            dd = d[d[ex].notna()]
            if not len(dd):
                continue
            t1 = trade_table(dd, rng, ("scope", "src", "pattern"), ex).assign(entry=name, iv="pooled")
            t2 = trade_table(dd, rng, ("scope", "src", "pattern", "iv"), ex).assign(entry=name)
            tabs += [t1, t2]
    TT = pd.concat(tabs, ignore_index=True)
    TT.to_csv(OUT / "trades_pooled.csv", index=False)
    print("\n(c) trades, pooled over symbols (E entry, E1 trail):")
    show = TT[(TT["entry"] == "E") & (TT["exit"] == "E1")]
    print(show.pivot_table(index=["scope", "pattern", "iv"], columns="src", values="R").round(3).to_string())
    print("\nreversal k=1 ATR the trade's way first (0.5 = coin):")
    print(show[show["iv"] == "pooled"].pivot_table(index=["scope", "pattern"], columns="src", values="rev1").round(3).to_string())
    # cells: Deriv pattern x symbol x timeframe, E entry, E1 (E1w on jumpy)
    cells = []
    D = E[E["venue"] == "deriv"]
    wm = {ex: D.groupby(["src", "sym", "iv", "pattern"])[ex].mean() for ex in ("E1", "E1w") if ex in D}
    for (sym, iv, pat), g in D[D["src"] == "real"].groupby(["sym", "iv", "pattern"]):
        ex = "E1w" if sym in JUMPY else "E1"
        y = g.assign(R=g[ex])
        if len(y) < 30:
            continue
        lo, hi, p = boot(y, rng)
        w = {s_: wm[ex].get((s_, sym, iv, pat), np.nan) for s_ in ("walk", "garch")}
        cells.append(dict(sym=sym, iv=iv, pattern=pat, exit=ex, n=len(y), R=y["R"].mean(), lo=lo, hi=hi, p=p,
                          R_h1=y.loc[y["ts"] < y["mid"], "R"].mean(), R_h2=y.loc[y["ts"] >= y["mid"], "R"].mean(),
                          R_walk=w["walk"], R_garch=w["garch"]))
    Cl = pd.DataFrame(cells)
    Cl["bh"] = bh(Cl["p"].to_numpy())
    Cl["passes"] = (Cl["R"] > 0) & (Cl["lo"] > 0) & (Cl["R_h1"] > 0) & (Cl["R_h2"] > 0) & (Cl["R"] > Cl["R_walk"]) & \
        (Cl["R"] > Cl["R_garch"]) & Cl["bh"]
    Cl.to_csv(OUT / "cells.csv", index=False)
    print(f"\nDeriv cells (pattern x symbol x timeframe): {len(Cl)}; BH-significant {int(Cl['bh'].sum())}; "
          f"passing every rule {int(Cl['passes'].sum())}")
    if Cl["passes"].any():
        print(Cl[Cl["passes"]].round(3).to_string(index=False))
    # the primary
    prim = {}
    for s in ("real", "walk", "garch", "boot"):
        x = E[(E["scope"] == "diffusive") & (E["src"] == s) & (E["pattern"] == "P6_SHIFT")]
        y = x.assign(R=x["E1"])
        lo, hi, p = boot(y, rng)
        prim[s] = dict(n=len(y), R=y["R"].mean(), lo=lo, hi=hi, p=p, R_h1=y.loc[y["ts"] < y["mid"], "R"].mean(),
                       R_h2=y.loc[y["ts"] >= y["mid"], "R"].mean(),
                       **{f"R_{iv}": y.loc[y["iv"] == iv, "R"].mean() for iv in IVS},
                       R_3tf=y.loc[y["iv"] != "1d", "R"].mean())
    r = prim["real"]
    ok = r["R"] > 0 and r["lo"] > 0 and r["R_h1"] > 0 and r["R_h2"] > 0 and r["R"] > prim["walk"]["R"] and r["R"] > prim["garch"]["R"]
    json.dump({"primary": prim, "passes": bool(ok)}, open(OUT / "primary.json", "w"), indent=1, default=float)
    print(f"\nPRIMARY (P6_SHIFT, Deriv diffusive, E then E1, 15m-1d pooled): R {r['R']:+.3f} [{r['lo']:+.3f}, {r['hi']:+.3f}] "
          f"n={r['n']}, halves {r['R_h1']:+.3f} / {r['R_h2']:+.3f}; walk {prim['walk']['R']:+.3f}, garch {prim['garch']['R']:+.3f}, "
          f"boot {prim['boot']['R']:+.3f} -> {'PASSES' if ok else 'fails'}")
    # protected
    P = P.copy()
    rows = []
    for (sc, src, iv, g), x in pd.concat([P.assign(iv_="pooled"), P.assign(iv_=P["iv"])]).groupby(["scope", "src", "iv_", "grade"]):
        dec = x[x["outcome"] != "censored"]
        rows.append(dict(scope=sc, src=src, iv=iv, grade=g, n=len(x), held=(dec["outcome"] == "held").mean(),
                         held50=x["held50"].dropna().astype(float).mean(), dist=x["dist"].median(),
                         swept_share=x["swept"].mean(), bos_share=x["bos"].mean()))
    for (sc, src), x in P[P["bos"]].groupby(["scope", "src"]):
        dec = x[x["outcome"] != "censored"]
        rows.append(dict(scope=sc, src=src, iv="pooled", grade="STRONG_BOS", n=len(x), held=(dec["outcome"] == "held").mean(),
                         held50=x["held50"].dropna().astype(float).mean(), dist=x["dist"].median(),
                         swept_share=x["swept"].mean(), bos_share=1.0))
    PR = pd.DataFrame(rows)
    PR.to_csv(OUT / "protected.csv", index=False)
    print("\nprotected lows: P(held until the next break of structure):")
    print(PR[PR["iv"] == "pooled"].pivot_table(index=["scope", "grade"], columns="src", values="held").round(3).to_string())
    if len(S):
        print("\nspikes (one-minute bars, 60 days):")
        print(S.round(4).to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})


# ---------------------------------------------------------------- plots

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cols = {"real": "#1d3557", "walk": "#a8dadc", "garch": "#e9c46a", "boot": "#e76f51", "pub": "#2a9d8f"}
    B = pd.read_csv(OUT / "base_rates.csv")
    pats = [p for p in PATTERNS] + [f"P9_{g}" for g in GRADES]
    fig, axes = plt.subplots(3, 1, figsize=(22, 15))
    for ax, sc in zip(axes, ("diffusive", "jumpy", "real")):
        g = B[B["scope"] == sc].groupby(["pattern", "src"])["per_1000"].mean().unstack("src").reindex(pats)
        x = np.arange(len(pats))
        srcs = [s for s in cols if s in g]
        w = 0.8 / len(srcs)
        for i, s in enumerate(srcs):
            ax.bar(x + (i - len(srcs) / 2 + 0.5) * w, g[s], w, color=cols[s], label=s)
        ax.set_xticks(x, pats, rotation=30, fontsize=8)
        ax.set_yscale("log")
        ax.set_title(f"{'Deriv ' if sc != 'real' else 'real markets (positive control) '}{sc}: events per 1,000 bars, mean over symbols and timeframes")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "sweeps_base_rates.png", dpi=80)
    plt.close(fig)
    # base-rate ratio real / walk per pattern and timeframe
    fig, axes = plt.subplots(1, 3, figsize=(22, 7), sharey=True)
    for ax, sc in zip(axes, ("diffusive", "jumpy", "real")):
        g = B[B["scope"] == sc].groupby(["iv", "pattern", "src"])["per_1000"].mean().unstack("src")
        for iv, m in zip(IVS, "osD^"):
            r = (g.loc[iv]["real"] / g.loc[iv]["walk"]).reindex(pats)
            ax.plot(r.values, range(len(pats)), m, label=f"{iv} real/walk")
            if sc == "jumpy":
                rb = (g.loc[iv]["real"] / g.loc[iv]["boot"]).reindex(pats)
                ax.plot(rb.values, range(len(pats)), m, mfc="none", color="#e76f51", label=f"{iv} real/boot")
        ax.axvline(1, color="grey", lw=0.8)
        ax.set_yticks(range(len(pats)), pats, fontsize=8)
        ax.set_xscale("log")
        ax.set_title(f"{sc}: rate on the real series / rate on its walk (1 = no difference)")
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "sweeps_base_ratio.png", dpi=80)
    plt.close(fig)
    # prediction gains
    if (OUT / "predict.csv").exists():
        Pd = pd.read_csv(OUT / "predict.csv")
        fig, axes = plt.subplots(1, 3, figsize=(20, 6))
        for ax, tg in zip(axes, ("y_sweep", "y_take", "y_sweep|take")):
            g = Pd[Pd["target"] == tg]
            labels = []
            for i, (_, r) in enumerate(g.iterrows()):
                ax.errorbar([i], [r["gain"]], yerr=[[r["gain"] - r["lo"]], [r["hi"] - r["gain"]]], fmt="o",
                            color=cols.get(r["src"], "k"))
                labels.append(f"{r['scope']}\n{r['src']}\nG0 {r['auc_G0']:.3f}")
            ax.axhline(0, color="grey", lw=0.8)
            ax.set_xticks(range(len(labels)), labels, fontsize=7)
            ax.set_title(f"{tg}: held-out AUC gain of G0+G1 over geometry (90% day bootstrap)")
        fig.tight_layout()
        fig.savefig(OUT / "sweeps_predict.png", dpi=80)
        plt.close(fig)
    # P(N R) per pattern, real vs walks
    TT = pd.read_csv(OUT / "trades_pooled.csv")
    for sc in ("diffusive", "jumpy", "real"):
        tp = [p for p in PATTERNS if len(TT[(TT["scope"] == sc) & (TT["pattern"] == p)])]
        k = int(np.ceil(len(tp) / 5))
        fig, axes = plt.subplots(k, 5, figsize=(24, 4.6 * k), sharey=True, squeeze=False)
        for ax, p in zip(axes.flat, tp):
            for s, col in cols.items():
                r = TT[(TT["scope"] == sc) & (TT["src"] == s) & (TT["pattern"] == p) & (TT["entry"] == "E")
                       & (TT["exit"] == "E1") & (TT["iv"] == "pooled")]
                if len(r):
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}R"] for N in NS], "-o", color=col, label=f"{s} R {r['R']:+.3f} (n {int(r['n'])})")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_title(f"{sc} {p}", fontsize=10)
            ax.legend(fontsize=7)
        for ax in axes.flat[len(tp):]:
            ax.axis("off")
        fig.suptitle(f"{sc}: P(trade reaches N R) after each pattern, E entry, 2-ATR trail; mean R in the legend")
        fig.tight_layout()
        fig.savefig(OUT / f"sweeps_pnr_{sc}.png", dpi=80)
        plt.close(fig)
    # protected hold rates
    PR = pd.read_csv(OUT / "protected.csv")
    fig, axes = plt.subplots(1, 3, figsize=(20, 6), sharey=True)
    for ax, sc in zip(axes, ("diffusive", "jumpy", "real")):
        g = PR[(PR["scope"] == sc) & (PR["iv"] == "pooled")]
        grades = list(GRADES) + ["STRONG_BOS"]
        x = np.arange(len(grades))
        srcs = [s for s in cols if s in set(g["src"])]
        w = 0.8 / len(srcs)
        for i, s in enumerate(srcs):
            v = g[g["src"] == s].set_index("grade").reindex(grades)["held"]
            ax.bar(x + (i - len(srcs) / 2 + 0.5) * w, v, w, color=cols[s], label=s)
        ax.set_xticks(x, grades)
        ax.set_title(f"{sc}: P(protected low holds until the next break of structure)")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "sweeps_protected.png", dpi=80)
    plt.close(fig)
    if (OUT / "spikes.csv").exists():
        S = pd.read_csv(OUT / "spikes.csv")
        fig, axes = plt.subplots(1, 3, figsize=(20, 5))
        axes[0].bar(S["feed"], S["minutes_per_spike"], color="#1d3557")
        axes[0].set_title("minutes per spike (one-minute bars)")
        axes[1].bar(S["feed"], S["wait_cv"], color="#1d3557", label="waiting-time CV")
        axes[1].plot(S["feed"], S["cv_geometric"], "r_", ms=20, mew=2, label="memoryless")
        axes[1].plot(S["feed"], S["hourly_dispersion"], "k.", ms=10, label="hourly var/mean (Poisson 1)")
        axes[1].legend(fontsize=8)
        axes[2].bar(np.arange(len(S)) - 0.2, S["auc_next"], 0.4, label="next-bar spike AUC", color="#1d3557")
        axes[2].bar(np.arange(len(S)) + 0.2, S["auc_shuffled"], 0.4, label="same, indicator shuffled", color="#a8dadc")
        axes[2].axhline(0.5, color="grey")
        axes[2].set_ylim(0.4, 0.6)
        axes[2].legend(fontsize=8)
        for ax in axes:
            ax.tick_params(axis="x", rotation=60, labelsize=7)
        fig.tight_layout()
        fig.savefig(OUT / "sweeps_spikes.png", dpi=80)
        plt.close(fig)
    gallery()
    print("plots written", flush=True)


def gallery():
    """Six Deriv trades per main pattern, winners and losers: the swept level, the wick, entry, stop, exit."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mcfl import candles
    from mcfl.parse import flip
    T = pd.read_pickle(OUT / "trades.pkl.gz")
    T = T[(T["venue"] == "deriv") & (T["src"] == "real") & ~T["limit"] & (T["iv"].isin(["1h", "4h"]))]
    rng = np.random.default_rng(9)
    cache = {}
    for pat in ("P1_SFP", "P2_TURTLE", "P3_POOL", "P4_CRT", "P6_SHIFT", "P8_BRK_ZONE", "P8_REC_ZONE", "P8_BRK_VOID"):
        sub = T[T["pattern"] == pat]
        if not len(sub):
            continue
        win, lose = sub[sub["E1"] > 0], sub[sub["E1"] <= 0]
        pick = pd.concat([win.iloc[rng.choice(len(win), min(3, len(win)), replace=False)],
                          lose.iloc[rng.choice(len(lose), min(3, len(lose)), replace=False)]])
        fig, axes = plt.subplots(2, 3, figsize=(21, 10))
        for ax, (_, r) in zip(axes.flat, pick.iterrows()):
            key = (r.sym, r.iv)
            if key not in cache:
                cache[key] = load(r.sym, r.iv)[0]
            df = cache[key]
            frame = df if r.side > 0 else flip(df)
            atr = np.asarray(candles.table(df)["atr"], float)
            k, f, ex = int(r.k), int(r.f), int(r.ex)
            i0, i1 = max(0, k - 30), min(len(df) - 1, max(ex, f) + 10)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            s = r.side
            entry = frame["open"].iat[f]
            stop = entry - r.risk_atr * atr[k]
            ax.hlines(s * entry, f, ex, colors="k", lw=1.2, label="entry")
            ax.hlines(s * stop, f, ex, colors="red", lw=1.2, label="initial stop")
            ax.axvline(k, color="purple", lw=1, ls=":", label="pattern known")
            ax.plot([ex], [df["close"].iat[ex]], "bx", ms=10, label="E1 exit")
            ax.set_title(f"{r.sym} {r.iv} {'long' if s > 0 else 'short'} -> {r.E1:+.2f}R trail, {r.X2:+.2f}R at 2R  "
                         f"{pd.Timestamp(int(r.ts), unit='s'):%Y-%m-%d %H:%M}", fontsize=9)
            ax.legend(fontsize=7)
        fig.suptitle(f"{pat} on Deriv (3 winners, 3 losers): purple dotted - the bar the pattern is known; black - entry at the "
                     "next open; red - stop beyond the sweep's wick; blue x - the trailing exit", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"sweeps_gallery_{pat}.png", dpi=75)
        plt.close(fig)


def smoke():
    """Walks only: one Deriv-like walk through every stage, and the timing."""
    import time
    from mcfl import candles, synth
    from mcfl.parse import parse
    OUT.mkdir(parents=True, exist_ok=True)
    n = int(os.environ.get("SMOKE_N", 20000))
    for name, df in (("walk", synth.walk(n, sigma=1.0, seed=5, steps=WALK_STEPS)),
                     ("garch", synth.garch(n, sigma=1.0, seed=6, steps=WALK_STEPS))):
        df["ts"] = 1_700_000_000 + 3600 * np.arange(len(df), dtype=np.int64)
        t0 = time.time()
        ch = parse(df, sec=3600)
        atr = np.asarray(candles.table(df)["atr"], float)
        cost = np.full(len(df), 0.02)
        t1 = time.time()
        T = pd.DataFrame(trade_rows(df, ch, "1h", cost, atr, (1, -1)))
        t2 = time.time()
        P = pd.DataFrame(protected_rows(ch, df, atr))
        X = predict_rows(df, ch, "1h", atr)
        t3 = time.time()
        print(f"{name}: parse {t1 - t0:.1f}s trades {t2 - t1:.1f}s rest {t3 - t2:.1f}s; {len(T)} trades, {len(X)} rows")
        print(pd.Series(counts(ch, len(df), "1h")).to_string())
        T["mid"] = T["ts"].median()
        T["scope"], T["src"] = "smoke", name
        print(trade_table(T[~T["limit"]], np.random.default_rng(1), ("pattern",), "E1").round(3).to_string(index=False))
        print(trade_table(T[~T["limit"]], np.random.default_rng(1), ("pattern",), "E1w").round(3)[["pattern", "n", "R"]].to_string(index=False))
        print(T[~T["limit"]].groupby("pattern")[["rev1", "rev2"]].mean().round(3).to_string())
        print(P.groupby("grade")["outcome"].value_counts(normalize=True).round(3).to_string())
        print(X[["y_take", "y_sweep"]].mean().to_string())


def main():
    {"run": run, "plot": plot, "smoke": smoke}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
