"""Do Boom/Crash spikes follow the trend? Spike hazard and size by the trend read from closed bars.

Frozen in `bc_rule.json` before any tick was fetched (see `research/docs/boomcrash-trend.md`).

Spikes are found on ticks: the grind is one-signed, so a bid move on the spike side larger than 3x the
99.9th percentile of the grind step is a spike. Every bar at every timeframe (1m 5m 15m 1h 4h 1d) is
built from the ticks' bids, for the full series and for the ex-spike series (the bid with every spike
taken out). Each minute is scored with the trend of the last bar of each timeframe closed before it:
LRC(100) slope sign, MCFL v2 structure, strength terciles. The hazard is spikes per tick in a state.
The null is a compound-Poisson tick simulator fitted on discovery (constant hazard, iid jump and grind
draws on the real timestamps), run through the identical code 40 times per index; a positive control
raises the hazard 1.25x while the simulated path's own 4h trend is aligned.

  DATA=.../boomcrash/data OUT=.../boomcrash/out MODE=prep|sim|agg|plot python research/ideas/boomcrash_trend.py
"""
from __future__ import annotations

import json
import os
import pickle
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import lrc_retest as LR  # noqa: E402  (atr, pivots, structure: the desk's frozen definitions)

# Intermediate results are pickles this script writes into its own OUT directory and reads back; no
# pickle from anywhere else is ever loaded.

DATA = Path(os.environ.get("DATA", os.path.expanduser("~/till_infinity/boomcrash/data")))
OUT = Path(os.environ.get("OUT", os.path.expanduser("~/till_infinity/boomcrash/out")))
WORKERS = int(os.environ.get("WORKERS", "8"))
N_NULL = int(os.environ.get("N_NULL", "40"))
N_CTRL = int(os.environ.get("N_CTRL", "4"))
CTRL_MULT = 1.25

SYMS = ["Boom 300 Index", "Boom 500 Index", "Boom 1000 Index", "Crash 300 Index", "Crash 500 Index", "Crash 1000 Index"]
NAME_RATE = {"boom_300": 300, "boom_500": 500, "boom_1000": 1000, "crash_300": 300, "crash_500": 500, "crash_1000": 1000}
DERIVING = {"boom_300": 267.7, "boom_500": 529.4, "boom_1000": 908.3, "crash_300": 329.0, "crash_500": 507.7,
            "crash_1000": 973.8}
TFS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
HTF, LTF = ("1h", "4h", "1d"), ("1m", "5m", "15m")
L = 100
OUTAGE_MS = 60_000
WARM_DAYS = 150
F_TICKS, F_SPK, F_SIZE, F_BIG, F_MIN, F_HIT, F_SATR = range(7)
NF = 7


def slug(sym):
    return sym.lower().replace(" index", "").replace(" ", "_")


def side(sl):
    return 1 if sl.startswith("boom") else -1


# ------------------------------------------------------------------------------------------------ data

def load_ticks(sl):
    fs = sorted((DATA / "ticks" / sl).glob("*.npz"))
    ms, bid, ask = [], [], []
    for f in fs:
        z = np.load(f)
        if len(z["ms"]):
            ms.append(z["ms"]), bid.append(z["bid"]), ask.append(z["ask"])
    ms, bid, ask = np.concatenate(ms), np.concatenate(bid), np.concatenate(ask)
    k = (bid > 0) & (ask > 0)
    ms, bid, ask = ms[k], bid[k], ask[k]
    o = np.argsort(ms, kind="stable")
    return ms[o], bid[o], ask[o]


def warm_bars(sym, tf):
    db = sqlite3.connect(f"file:{DATA / 'bars.db'}?mode=ro", uri=True)
    r = np.array(db.execute("SELECT ts, open, high, low, close FROM bars WHERE symbol = ? AND interval = ? ORDER BY ts",
                            (sym, tf)).fetchall(), float)
    db.close()
    return r


# ------------------------------------------------------------------------------------------- mechanics

def theta_of(bid, ms, s, disc_end_ms):
    d = np.diff(np.log(bid))
    ok = (np.diff(ms) <= OUTAGE_MS) & (ms[1:] < disc_end_ms)
    g = np.abs(d[ok & (s * d <= 0)])
    return 3.0 * float(np.quantile(g, 0.999))


def detect(ms, bid, s, theta):
    """Spike events on ticks, in log-price units (the indices are multiplicative: Boom 300 went from 715
    to 4,359 and back to 1,055 in the sample, and its grind and spikes scaled with it). Returns (first
    tick, last tick, log size J > 0) per event, the ex-spike LOG bid, the count of sub-threshold spike-side
    moves and the outage mask (moves across a > 60 s hole)."""
    d = np.diff(np.log(bid))
    outage = np.diff(ms) > OUTAGE_MS
    sp = (s * d > theta) & ~outage
    sub = int(((s * d > 0) & (s * d <= theta) & ~outage).sum())
    t = np.flatnonzero(sp) + 1                       # tick index at which the spike move lands
    if len(t):
        new = np.r_[True, np.diff(t) > 1]
        st = np.flatnonzero(new)
        en = np.r_[st[1:], len(t)] - 1
        first, last = t[st], t[en]
        J = s * (np.log(bid[last]) - np.log(bid[first - 1]))
    else:
        first = last = np.zeros(0, np.int64)
        J = np.zeros(0)
    inc = np.where(sp | outage, 0.0, d)
    # the ex-spike series is kept in LOG price: exponentiated, the one-signed grind compounds over 55M
    # ticks to exp(-500) and underflows to zero within months
    ex = np.log(bid[0]) + np.r_[0.0, np.cumsum(inc)]
    return first, last, J, ex, sub, outage


def minute_bars(ms, x):
    m = ms // 60000
    st = np.flatnonzero(np.r_[True, m[1:] != m[:-1]])
    en = np.r_[st[1:], len(m)]
    return (m[st] * 60, x[st], np.maximum.reduceat(x, st), np.minimum.reduceat(x, st), x[en - 1], st, en)


def resample(ts, o, h, l, c, sec):
    k = ts // sec * sec
    st = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    en = np.r_[st[1:], len(k)]
    return k[st], o[st], np.maximum.reduceat(h, st), np.minimum.reduceat(l, st), c[en - 1]


def lrc_r(c, n=L, chunk=20000):
    """Rolling LRC(n): slope per bar and Pearson R of the closes against bar index; NaN before n-1."""
    c = np.asarray(c, float)
    slope, R = np.full(len(c), np.nan), np.full(len(c), np.nan)
    if len(c) < n:
        return slope, R
    x = np.arange(n, dtype=float) - (n - 1) / 2
    sxx = float((x ** 2).sum())
    W = np.lib.stride_tricks.sliding_window_view(c, n)
    for s0 in range(0, len(W), chunk):
        w = W[s0:s0 + chunk]
        wc = w - w.mean(1)[:, None]
        b = wc @ x / sxx
        ss = (wc ** 2).sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(ss > 0, b * np.sqrt(sxx) / np.sqrt(ss), 0.0)
        slope[n - 1 + s0:n - 1 + s0 + len(w)] = b
        R[n - 1 + s0:n - 1 + s0 + len(w)] = r
    return slope, R


def readings(ts, o, h, l, c, s):
    a = LR.atr(h, l, c)
    b, R = lrc_r(c)
    hi, lo = LR.pivots(h, l)
    st, _, _, _ = LR.structure(h, l, a, hi, lo)
    with np.errstate(invalid="ignore", divide="ignore"):
        bs = np.abs(b) / a
    return dict(ts=ts, c=c, o=o, h=h, l=l, atr=a, b=b, R=R, dir=np.sign(s * b), mcfl=s * st.astype(float), bs=bs, aR=np.abs(R),
                valid=np.r_[np.zeros(min(L - 1, len(c)), bool), np.ones(max(len(c) - L + 1, 0), bool)])


def at_minutes(rd, sec, T, causal=True):
    """Index of the bar whose reading applies to each minute start T: the last bar closed at or before T
    (causal) or the bar containing T (non-causal, S10)."""
    if causal:
        i = np.searchsorted(rd["ts"] + sec, T, "right") - 1
    else:
        i = np.searchsorted(rd["ts"], T, "right") - 1
    ok = i >= 0
    ok[ok] &= rd["valid"][i[ok]] & np.isfinite(rd["b"][i[ok]])
    return np.where(ok, i, -1)


def terc(x, disc, k=3):
    """Codes 0..k-1 by quantiles of x over discovery entries (finite x where disc)."""
    v = x[disc & np.isfinite(x)]
    if len(v) < 10:
        return np.full(len(x), -1, np.int8)
    cuts = np.quantile(v, np.arange(1, k) / k)
    out = np.searchsorted(cuts, x, "right").astype(np.int8)
    out[~np.isfinite(x)] = -1
    return out


# ------------------------------------------------------------------------------------------- simulator

def fit_null(ms, bid, s, first, last, J, outage, disc_end_ms, rng):
    n_disc = int(np.searchsorted(ms, disc_end_ms))
    k = first < n_disc
    d = np.diff(np.log(bid[:n_disc]))
    is_sp = np.zeros(len(d), bool)
    for a, b in zip(first[k], last[k]):
        is_sp[a - 1:b] = True
    g = d[~is_sp & ~outage[:n_disc - 1] & (s * d <= 0)]
    # sub-threshold spike-side moves are grind by the rule; keep them in the grind sample
    g2 = d[~is_sp & ~outage[:n_disc - 1] & (s * d > 0)]
    grind = np.r_[g, g2]
    return dict(p=float(k.sum()) / n_disc, J=J[k].copy(), grind=rng.choice(grind, min(len(grind), 4_000_000),
                                                                           replace=False))


def sim_steps(n, par, s, rng, p=None, jscale=1.0):
    p = par["p"] if p is None else p
    is_sp = rng.random(n) < p
    d = par["grind"][rng.integers(0, len(par["grind"]), n)]
    m = int(is_sp.sum())
    if m:
        d[is_sp] = s * jscale * par["J"][rng.integers(0, len(par["J"]), m)]
    return d


def simulate(ms, start_px, par, s, seed, feedback=False, warm=None):
    """Bid path on the real timestamps. feedback: hazard x CTRL_MULT and jump size / CTRL_MULT while the
    path's own 4h LRC(100) (warm-up 4h closes + completed simulated 4h blocks) points the spike's way."""
    rng = np.random.default_rng(seed)
    n = len(ms)
    bid = np.empty(n)
    if not feedback:
        px = start_px
        for a in range(0, n, 5_000_000):
            d = sim_steps(min(5_000_000, n - a), par, s, rng)
            bid[a:a + len(d)] = px * np.exp(np.cumsum(d))
            px = bid[a + len(d) - 1]
        return bid
    closes = list(warm[:, 4]) if warm is not None and len(warm) else []
    blk = ms // (14400 * 1000)
    st = np.flatnonzero(np.r_[True, blk[1:] != blk[:-1]])
    en = np.r_[st[1:], n]
    x = np.arange(L, dtype=float) - (L - 1) / 2
    px = start_px
    for a, b in zip(st, en):
        p, js = par["p"], 1.0
        if len(closes) >= L:
            w = np.asarray(closes[-L:])
            if s * float((w - w.mean()) @ x) > 0:
                # more spikes, each smaller by the same factor: the drift stays zero (the closure), so
                # the control changes the hazard without making the trend feed itself
                p, js = par["p"] * CTRL_MULT, 1.0 / CTRL_MULT
        d = sim_steps(b - a, par, s, rng, p, js)
        bid[a:b] = px * np.exp(np.cumsum(d))
        px = bid[b - 1]
        closes.append(px)
    return bid


def sim_warm(ms0, start_px, par, s, seed):
    """WARM_DAYS of ticks at the median real tick interval before the first tick, as 1m bars."""
    rng = np.random.default_rng(seed + 7919)
    step = 1000
    n = WARM_DAYS * 86400 * 1000 // step
    ms = ms0 - step * np.arange(n, 0, -1)
    d = sim_steps(n, par, s, rng)
    bid = start_px * np.exp(np.cumsum(d) - d.sum())   # ends next to the real start price
    return ms, bid


# --------------------------------------------------------------------------------------------- pipeline

def analyse(sl, ms, bid, ask, theta, meta, warm1m=None, warm_bridge=None, by_day=True, trades=True):
    """Everything the study measures on one tick path. Returns a dict of small arrays."""
    s = side(sl)
    day0, split_day, day_end = meta["day0"], meta["split_day"], meta["day_end"]
    keep = (ms >= day0 * 86400000) & (ms < (day_end + 1) * 86400000)
    ms, bid, ask = ms[keep], bid[keep], ask[keep]
    first, last, J, ex, sub, outage = detect(ms, bid, s, theta)
    disc_end_ms = split_day * 86400000
    T, o1, h1, l1, c1, st1, en1 = minute_bars(ms, bid)
    _, eo1, eh1, el1, ec1, _, _ = minute_bars(ms, ex)
    nm = len(T)
    ticks_m = (en1 - st1).astype(float)
    sp_min = np.searchsorted(st1, first, "right") - 1               # minute of each spike
    disc_m = T < split_day * 86400
    day_m = (T // 86400 - day0).astype(np.int64)
    ndays = day_end - day0 + 1
    medJ = float(np.median(J[first < np.searchsorted(ms, disc_end_ms)]))
    sizerel = J / medJ

    # bars and readings, per timeframe and series
    R = {}
    for tf, sec in TFS.items():
        for ser, (o, h, l, c) in (("full", (o1, h1, l1, c1)), ("ex", (eo1, eh1, el1, ec1))):
            b = resample(T, o, h, l, c, sec) if sec > 60 else (T, o, h, l, c)
            if ser == "full" and tf in HTF:
                w = warm_bridge.get(tf) if warm_bridge is not None else None
                if warm1m is not None:
                    wt, wo, wh, wl, wc = warm1m
                    w = np.column_stack(resample(wt, wo, wh, wl, wc, sec))
                if w is not None and len(w):
                    w = w[w[:, 0] < b[0][0]]
                    b = tuple(np.r_[w[:, j], b[j]] for j in range(5))
            R[(tf, ser)] = readings(*b, s)

    # 1h full ATR for size in ATR
    ih = at_minutes(R[("1h", "full")], 3600, T)
    atr1h = np.where(ih >= 0, R[("1h", "full")]["atr"][np.maximum(ih, 0)], np.nan)

    codes = {}
    idx_c = {}
    for tf, sec in TFS.items():
        for ser in ("full", "ex"):
            rd = R[(tf, ser)]
            i = at_minutes(rd, sec, T)
            idx_c[(tf, ser)] = i
            ok = i >= 0
            ii = np.maximum(i, 0)
            dr = np.where(ok, rd["dir"][ii], 0)
            cd = np.where(dr > 0, 0, np.where(dr < 0, 1, -1)).astype(np.int8)
            codes[f"{tf}|{ser}|dir"] = (cd, 2)
            mc = np.where(ok, rd["mcfl"][ii], np.nan)
            codes[f"{tf}|{ser}|mcfl"] = (np.where(~ok, -1, np.where(mc > 0, 0, np.where(mc < 0, 1, 2))).astype(np.int8), 3)
            for nm_, key in (("bs", "bs"), ("R", "aR")):
                x = np.where(ok, rd[key][ii], np.nan)
                t3 = terc(x, disc_m)
                codes[f"{tf}|{ser}|dirx{nm_}"] = (np.where((cd >= 0) & (t3 >= 0), cd * 3 + t3, -1).astype(np.int8), 6)
                codes[f"{tf}|{ser}|{nm_}"] = (t3, 3)
            if ser == "ex":
                g = np.abs(np.diff(rd["c"]))
                dsc = rd["ts"][1:] < split_day * 86400
                mg = float(np.mean(g[dsc])) if dsc.any() else np.nan
                x = np.where(ok, np.abs(rd["b"][ii]) / mg, np.nan)
                codes[f"{tf}|ex|grind"] = (terc(x, disc_m), 3)
            if ser == "full":
                j = at_minutes(rd, sec, T, causal=False)
                ok2 = j >= 0
                d2 = np.where(ok2, rd["dir"][np.maximum(j, 0)], 0)
                codes[f"{tf}|full|nc"] = (np.where(d2 > 0, 0, np.where(d2 < 0, 1, -1)).astype(np.int8), 2)

    for ser in ("full", "ex"):
        al = np.stack([codes[f"{tf}|{ser}|dir"][0] for tf in TFS])
        okall = (al >= 0).all(0)
        cnt = (al == 0).sum(0)
        codes[f"mtf|{ser}|count"] = (np.where(okall, cnt, -1).astype(np.int8), 7)
        score = np.zeros(nm)
        for k, tf in enumerate(TFS):
            i = idx_c[(tf, ser)]
            r = np.where(i >= 0, R[(tf, ser)]["aR"][np.maximum(i, 0)], np.nan)
            score += np.where(al[k] == 0, 1.0, -1.0) * r
        score = np.where(okall, score, np.nan)
        codes[f"mtf|{ser}|score"] = (terc(score, disc_m, 5), 5)
    for H in HTF:
        for Lt in LTF:
            a = codes[f"{H}|full|dir"][0]
            b = codes[f"{Lt}|full|dir"][0]
            nest = np.where((a == 0) & (b == 0), 0, np.where((a == 0) & (b == 1), 1,
                            np.where((a == 1) & (b == 0), 2, np.where((a == 1) & (b == 1), 3, -1))))
            codes[f"nest|{H}|{Lt}"] = (np.where((a < 0) | (b < 0), -1, nest).astype(np.int8), 4)

    # aggregation
    spk_m = np.bincount(sp_min, minlength=nm).astype(float)
    hit_m = (spk_m > 0).astype(float)
    big = (sizerel > 2).astype(float)
    satr = (bid[last] - bid[first - 1]) * s / atr1h[sp_min]
    unit = day_m if by_day else (~disc_m).astype(np.int64)
    nu = ndays if by_day else 2
    unit_sp = unit[sp_min]
    agg = {}
    for name, (cd, K) in codes.items():
        out = np.zeros((nu, K, NF))
        ok = cd >= 0
        key = unit[ok] * K + cd[ok]
        for f, w in ((F_TICKS, ticks_m), (F_SPK, spk_m), (F_MIN, np.ones(nm)), (F_HIT, hit_m)):
            out[:, :, f] = np.bincount(key, weights=w[ok], minlength=nu * K).reshape(nu, K)
        cs = cd[sp_min]
        oks = cs >= 0
        ks = unit_sp[oks] * K + cs[oks]
        for f, w in ((F_SIZE, sizerel), (F_BIG, big), (F_SATR, np.nan_to_num(satr))):
            out[:, :, f] = np.bincount(ks, weights=w[oks], minlength=nu * K).reshape(nu, K)
        agg[name] = out.astype(np.float32)
    tot = np.zeros((nu, 2))
    tot[:, 0] = np.bincount(unit, weights=ticks_m, minlength=nu)
    tot[:, 1] = np.bincount(unit_sp, minlength=nu)

    # next-15m windows, full direction, state at the window start
    p15 = {}
    W = T // 900
    wst = np.flatnonzero(np.r_[True, W[1:] != W[:-1]])
    wh = np.add.reduceat(spk_m, wst) > 0
    wT = W[wst] * 900
    wdisc = wT < split_day * 86400
    for tf, sec in TFS.items():
        i = at_minutes(R[(tf, "full")], sec, wT)
        dr = np.where(i >= 0, R[(tf, "full")]["dir"][np.maximum(i, 0)], 0)
        tab = np.zeros((2, 2, 2))
        for h in (0, 1):
            m_ = (wdisc if h == 0 else ~wdisc)
            for c_, v in ((0, 1), (1, -1)):
                sel = m_ & (dr == v)
                tab[h, c_] = (sel.sum(), wh[sel].sum())
        p15[tf] = tab

    # clustering, per half
    clu = {}
    gaps_t = np.diff(first).astype(float)
    g_half = (ms[first[1:]] >= disc_end_ms).astype(int)
    c4 = codes["4h|full|dir"][0][sp_min[:-1]] if len(first) > 1 else np.zeros(0)
    for h in (0, 1):
        gg = gaps_t[g_half == h]
        r = dict(cv=float(gg.std() / gg.mean()) if len(gg) > 2 else np.nan, n=int(len(gg)),
                 cv_geo=float(np.sqrt(1 - 1 / gg.mean())) if len(gg) > 2 else np.nan)
        for v, nmv in ((0, "al"), (1, "co")):
            x = gaps_t[(g_half == h) & (c4 == v)]
            r[f"cv_{nmv}"] = float(x.std() / x.mean()) if len(x) > 2 else np.nan
        mh = disc_m if h == 0 else ~disc_m
        for wsec, wn in ((900, "15m"), (3600, "1h"), (86400, "1d")):
            key = T[mh] // wsec
            stw = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
            cnt = np.add.reduceat(spk_m[mh], stw)
            tk = np.add.reduceat(ticks_m[mh], stw)
            full = tk >= 0.9 * np.median(tk)
            cc = cnt[full]
            r[f"fano_{wn}"] = float(cc.var() / cc.mean()) if cc.mean() > 0 else np.nan
            if wn == "1h":
                st4 = codes["4h|full|dir"][0][mh][stw]
                for v, nmv in ((0, "al"), (1, "co")):
                    x = cnt[full & (st4 == v)]
                    r[f"fano_1h_{nmv}"] = float(x.var() / x.mean()) if len(x) > 2 and x.mean() > 0 else np.nan
            if wn == "15m":
                r["acf_15m"] = float(np.corrcoef(cc[:-1], cc[1:])[0, 1])
        x = spk_m[mh]
        r["acf_1m"] = float(np.corrcoef(x[:-1], x[1:])[0, 1])
        clu[h] = r

    res = dict(agg=agg, tot=tot, p15=p15, clu=clu, by_day=by_day, sub=sub, n_outage=int(outage.sum()),
               n_ticks=len(ms), n_spikes=len(first), medJ=medJ,
               rate=[float(len(first[first < np.searchsorted(ms, disc_end_ms)]) / np.searchsorted(ms, disc_end_ms)),
                     float((first >= np.searchsorted(ms, disc_end_ms)).sum() / (len(ms) - np.searchsorted(ms, disc_end_ms)))],
               ex_share={f"{tf}": float((codes[f"{tf}|ex|dir"][0] == 0).sum() / max((codes[f"{tf}|ex|dir"][0] >= 0).sum(), 1))
                         for tf in TFS})
    if trades:
        res["trades"] = trade(sl, ms, bid, ask, first, last, R, split_day, meta["swap"])
    return res


# ------------------------------------------------------------------------------------------------ trade

def trade(sl, ms, bid, ask, first, last, R, split_day, swap):
    """The spike-side trade at every 15m close (bc_rule.json 'trade'). One row per entry:
    (time, half, R net, R gross, exit kind 0 stop / 1 spike / 2 time, 4h full dir, 4h ex grind tercile,
    seconds held, risk in ATR)."""
    s = side(sl)
    r15, r4, r4x = R[("15m", "full")], R[("4h", "full")], R[("4h", "ex")]
    ts, h, l, a = r15["ts"], r15["h"], r15["l"], r15["atr"]
    T_entry = ts + 900
    e_all = np.searchsorted(ms, T_entry * 1000, "left")
    i4 = np.searchsorted(r4["ts"] + 14400, T_entry, "right") - 1
    i4x = np.searchsorted(r4x["ts"] + 14400, T_entry, "right") - 1
    g = np.abs(np.diff(r4x["c"]))
    dsc = r4x["ts"][1:] < split_day * 86400
    mg = float(np.mean(g[dsc]))
    gr = np.abs(r4x["b"]) / mg
    gv = gr[np.isfinite(gr) & (r4x["ts"] < split_day * 86400) & r4x["valid"]]
    cuts = np.quantile(gv, [1 / 3, 2 / 3]) if len(gv) >= 10 else None
    rows = []
    n = len(ms)
    for k in range(3, len(ts)):
        e = e_all[k]
        if e >= n - 2 or ms[e] - T_entry[k] * 1000 > OUTAGE_MS:
            continue
        if s > 0:
            entry = ask[e]
            stop = min(l[k - 2:k + 1].min() - 0.1 * a[k], entry - 0.25 * a[k])
            risk = entry - stop
        else:
            entry = bid[e]
            stop = max(h[k - 2:k + 1].max() + 0.1 * a[k], entry + 0.25 * a[k])
            risk = stop - entry
        if not (risk > 0) or not np.isfinite(risk):
            continue
        q = np.searchsorted(first, e, "right")
        cap = min(int(np.searchsorted(ms, ms[e] + 86_400_000)) - 1, n - 1)
        q_first = first[q] if q < len(first) else n
        end = min(q_first - 1, cap)
        seg = bid[e + 1:end + 1] if s > 0 else ask[e + 1:end + 1]
        hit = (seg <= stop) if s > 0 else (seg >= stop)
        if hit.any():
            j = e + 1 + int(np.argmax(hit))
            out, kind = (bid[j] if s > 0 else ask[j]), 0
        elif q_first <= cap and last[q] + 1 < n:
            j = last[q] + 1
            out, kind = (bid[j] if s > 0 else ask[j]), 1
        else:
            j = cap
            out, kind = (bid[j] if s > 0 else ask[j]), 2
        held = (ms[j] - ms[e]) / 1000
        sw = abs(swap) / 100 * entry * held / (365 * 86400) / risk
        rn = s * (out - entry) / risk - sw
        rg = s * (bid[j] - bid[e]) / risk
        d4 = r4["dir"][i4[k]] if i4[k] >= 99 else 0
        x4 = gr[i4x[k]] if i4x[k] >= 99 else np.nan
        t4 = int(np.searchsorted(cuts, x4, "right")) if (cuts is not None and np.isfinite(x4)) else -1
        rows.append((T_entry[k], int(T_entry[k] >= split_day * 86400), rn, rg, kind, d4, t4, held, risk / a[k]))
    return np.array(rows, float)


# -------------------------------------------------------------------------------------------- jobs

def meta_info():
    p = OUT / "meta.json"
    if p.exists():
        return json.loads(p.read_text())
    spans = {}
    for sym in SYMS:
        fs = [f for f in sorted((DATA / "ticks" / slug(sym)).glob("*.npz")) if f.stat().st_size > 50_000]
        days = [int(np.datetime64(f.stem, "D").astype(np.int64)) for f in fs]
        if days:
            spans[slug(sym)] = (min(days), max(days))
    day0 = max(v[0] for v in spans.values())
    day_end = min(v[1] for v in spans.values())
    if os.environ.get("META_DAYS"):          # the span fixed in advance, so indices can run as their fetch completes
        day0, day_end = (int(x) for x in os.environ["META_DAYS"].split(","))
    split_day = int(round((day0 + day_end + 1) / 2))
    info = json.loads((DATA / "info.json").read_text())
    swap = {slug(k): float(v.get("swap_long", 0.0)) for k, v in info.items()}
    m = dict(day0=day0, day_end=day_end, split_day=split_day, spans=spans, swap=swap,
             split=str(np.datetime64(split_day, "D")), first=str(np.datetime64(day0, "D")), last=str(np.datetime64(day_end, "D")))
    OUT.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=1))
    return m


def prep_one(sym):
    """Real ticks: cache arrays, fit theta and the null, analyse the real path."""
    sl = slug(sym)
    m = meta_info()
    t0 = time.time()
    ms, bid, ask = load_ticks(sl)
    k = (ms >= m["day0"] * 86400000) & (ms < (m["day_end"] + 1) * 86400000)
    ms, bid, ask = ms[k], bid[k], ask[k]
    cache = OUT / "cache" / sl
    cache.mkdir(parents=True, exist_ok=True)
    np.save(cache / "ms.npy", ms)
    np.save(cache / "bid.npy", bid)
    np.save(cache / "spread.npy", (ask - bid).astype(np.float32))
    s = side(sl)
    disc_end = m["split_day"] * 86400000
    theta = theta_of(bid, ms, s, disc_end)
    first, last, J, ex, sub, outage = detect(ms, bid, s, theta)
    par = fit_null(ms, bid, s, first, last, J, outage, disc_end, np.random.default_rng(1))
    with open(cache / "null.pkl", "wb") as f:
        pickle.dump(dict(theta=theta, par=par, start=float(bid[0]), ms0=int(ms[0])), f)
    warm = {tf: warm_bars(sym, tf) for tf in HTF}
    m2 = dict(m, swap=m["swap"].get(sl, 0.0))
    res = analyse(sl, ms, bid, ask, theta, m2, warm_bridge=warm, by_day=True)
    res["theta"] = theta
    res["check"] = bridge_check(sym, ms, bid)
    res["spikes"] = dict(t=ms[first] // 1000, J=J.astype(np.float32), i=first)
    with open(OUT / f"real_{sl}.pkl", "wb") as f:
        pickle.dump(res, f)
    return f"{sl}: {len(ms)} ticks, {res['n_spikes']} spikes, theta {theta:.4g}, sub {res['sub']}, {time.time() - t0:.0f}s"


def bridge_check(sym, ms, bid):
    """Tick-built 1h bars against the bridge's H1 bars over the overlap: share of exact closes."""
    w = warm_bars(sym, "1h")
    T, o, h, l, c, _, _ = minute_bars(ms, bid)
    tb = resample(T, o, h, l, c, 3600)
    common, ia, ib = np.intersect1d(w[:, 0].astype(np.int64), tb[0], return_indices=True)
    if not len(common):
        return {}
    dc = np.abs(w[ia, 4] - tb[4][ib])
    dh = np.abs(w[ia, 2] - tb[2][ib])
    return dict(n=int(len(common)), close_exact=float((dc < 1e-6).mean()), close_p99=float(np.quantile(dc, 0.99)),
                high_exact=float((dh < 1e-6).mean()))


def sim_one(job):
    sym, kind, k = job
    sl = slug(sym)
    outp = OUT / "sim" / f"{kind}_{sl}_{k:03d}.pkl"
    if outp.exists():
        return f"{outp.name} cached"
    m = meta_info()
    cache = OUT / "cache" / sl
    ms = np.load(cache / "ms.npy", mmap_mode="r")
    spread = np.load(cache / "spread.npy", mmap_mode="r")
    with open(cache / "null.pkl", "rb") as f:
        nl = pickle.load(f)
    s = side(sl)
    seed = (SYMS.index(sym) + 1) * 100_000 + k + (5_000 if kind == "ctrl" else 0)
    wms, wbid = sim_warm(nl["ms0"], nl["start"], nl["par"], s, seed)
    wT, wo, wh, wl, wc, _, _ = minute_bars(wms, wbid)
    warm4 = np.column_stack(resample(wT, wo, wh, wl, wc, 14400))
    ms = np.asarray(ms)
    bid = simulate(ms, nl["start"], nl["par"], s, seed, feedback=(kind == "ctrl"), warm=warm4)
    ask = bid + np.asarray(spread, float)
    m2 = dict(m, swap=m["swap"].get(sl, 0.0))
    res = analyse(sl, ms, bid, ask, nl["theta"], m2, warm1m=(wT, wo, wh, wl, wc), by_day=(kind == "ctrl"))
    outp.parent.mkdir(parents=True, exist_ok=True)
    with open(outp, "wb") as f:
        pickle.dump(res, f)
    return f"{outp.name}: {res['n_spikes']} spikes"


def walk_trades(sym):
    """The desk's iid and GARCH walks matched to the 15m full-series bars: same entries, stop, a hold to
    96 bars (24h) or the stop, the real spread in ATR units."""
    sys.path.insert(0, str(HERE.parent))
    from mcfl import synth
    sl = slug(sym)
    m = meta_info()
    cache = OUT / "cache" / sl
    ms = np.load(cache / "ms.npy")
    bid = np.load(cache / "bid.npy")
    spr = float(np.median(np.load(cache / "spread.npy")))
    T, o, h, l, c, _, _ = minute_bars(ms, bid)
    t15, o15, h15, l15, c15 = resample(T, o, h, l, c, 900)
    a15 = LR.atr(h15, l15, c15)
    cost_atr = spr / np.median(a15[100:])
    disc = t15 < m["split_day"] * 86400
    sigma = float(np.std(np.diff(c15[disc])))
    out = {}
    for name, fn in (("iid", synth.walk), ("garch", synth.garch)):
        df = fn(len(c15), sigma=sigma, seed=11, steps=256)
        H, Lo, C = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
        A = LR.atr(H, Lo, C)
        rows = []
        for k in range(100, len(C) - 1):
            entry = C[k] + 0.5 * cost_atr * A[k]
            stop = min(Lo[k - 2:k + 1].min() - 0.1 * A[k], entry - 0.25 * A[k])
            risk = entry - stop
            seg = Lo[k + 1:k + 97]
            hit = seg <= stop
            if hit.any():
                r = -1.0 - 0.5 * cost_atr * A[k] / risk
            else:
                r = (C[min(k + 96, len(C) - 1)] - 0.5 * cost_atr * A[k] - entry) / risk
            rows.append((t15[k] + 900, int(t15[k] >= m["split_day"] * 86400), r))
        out[name] = np.array(rows)
    with open(OUT / f"walk_{sl}.pkl", "wb") as f:
        pickle.dump(out, f)
    return f"walks {sl}"


def only():
    o = os.environ.get("ONLY")
    return [s for s in SYMS if not o or slug(s) in o.split(",")]


def run_prep():
    meta_info()
    with ProcessPoolExecutor(min(WORKERS, 6)) as ex:
        for r in ex.map(prep_one, only()):
            print(r, flush=True)


def run_sim():
    jobs = [(sym, "null", k) for k in range(N_NULL) for sym in only()] + [(sym, "ctrl", k) for k in range(N_CTRL) for sym in only()]
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(sim_one, jobs):
            print(r, flush=True)
        for r in ex.map(walk_trades, only()):
            print(r, flush=True)


if __name__ == "__main__":
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(v, "1")
    mode = os.environ.get("MODE", "prep")
    if mode == "prep":
        run_prep()
    elif mode == "sim":
        run_sim()
    elif mode in ("agg", "plot"):
        import boomcrash_agg
        boomcrash_agg.main(mode)
    (OUT / f"{mode}.flag").write_text("done\n")
