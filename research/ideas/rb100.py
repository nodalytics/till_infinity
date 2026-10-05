"""Range Break 100 (and 200): the generator from its own ticks, a fitted simulator of it, and a frozen
test of the rules that 'survived' on it, with bar fills and with executable tick fills.

Frozen in `rb100_rule.json` before any rule ran on real data (see research/docs/range-break-100.md).

  MODE=char   the generator on ticks and bars (both periods), stability by year       -> OUT/char_*
  MODE=fit    the simulator's parameters on discovery ticks only                       -> OUT/rb_sim_params.json
  MODE=run    every rule x timeframe x source (real, rbsim, iid, garch), bar and tick fill -> OUT/parts
  MODE=agg    tables, bootstraps, BH, verdicts                                         -> OUT/*.csv, verdict.json
  MODE=plot   figures                                                                  -> OUT/img

Environment: DATA (the bridge fetch: rb_bars.db and ticks/<100|200>/<day>.npz), OUT, WORKERS.
Reuses lrc_retest.py (R2, R5s and their exits) and mean_reversion.py (signals and sim) unchanged.
"""
from __future__ import annotations

import glob
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

import lrc_retest as L  # noqa: E402
import mean_reversion as M  # noqa: E402

DATA = Path(os.environ.get("DATA", os.path.expanduser("~/till_infinity/rb100/data")))
OUT = Path(os.environ.get("OUT", ".data/rb100"))
WORKERS = int(os.environ.get("WORKERS", 8))

INST = {"RB100": ("Range Break 100 Index", "100"), "RB200": ("Range Break 200 Index", "200")}
IVS = ("15m", "1h", "4h", "1d")
SEC = {"1m": 60, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
SPLIT_BAR = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())
SPLIT_T = int(pd.Timestamp("2025-10-01", tz="UTC").timestamp())
SPREAD, SWAP = 1.0, 3.0          # price units: ask - bid on every tick; 30 points x 0.1 a night
JUMP = 5                          # |d bid| >= 5 is a break (every other step is +/-1)
NS = (0.5, 1, 2, 4, 10)
SEEDS = (0, 1, 2, 3)
NULLS = ("rbsim", "iid", "garch")
GARCH = (0.08, 0.90)
MR_RULES = ("bb", "z50", "kelt", "ibs1")
LRC_RULES = ("R2", "R5s")
LRC_EXITS = ("X2", "TR", "BAND")
MR_EXITS = ("st", "own")
TICK_H = 200                      # bars for the tick P(N R)


def split_of(iv):
    return SPLIT_T if iv == "15m" else SPLIT_BAR


# ------------------------------------------------------------------------------------------------ data

def load_bars(inst, iv):
    sym = INST[inst][0]
    con = sqlite3.connect(f"file:{DATA / 'rb_bars.db'}?mode=ro", uri=True)
    try:
        d = pd.read_sql_query("SELECT ts, open, high, low, close FROM bars WHERE symbol = ? AND interval = ? ORDER BY ts",
                              con, params=(sym, iv))
    finally:
        con.close()
    d["volume"] = 0.0
    return d.drop_duplicates("ts").reset_index(drop=True)


def tick_files(inst):
    return sorted(glob.glob(str(DATA / "ticks" / INST[inst][1] / "*.npz")))


def load_ticks(inst, lo=None, hi=None):
    """Raw ticks (ms, bid, ask) of whole UTC days in [lo, hi)."""
    ms, bid, ask = [], [], []
    for f in tick_files(inst):
        day = int(pd.Timestamp(Path(f).stem, tz="UTC").timestamp())
        if (lo is not None and day < lo) or (hi is not None and day >= hi):
            continue
        z = np.load(f)
        ms.append(z["ms"])
        bid.append(z["bid"])
        ask.append(z["ask"])
    if not ms:
        return np.zeros(0, np.int64), np.zeros(0), np.zeros(0)
    ms, bid, ask = np.concatenate(ms), np.concatenate(bid), np.concatenate(ask)
    o = np.argsort(ms, kind="stable")
    return ms[o], bid[o], ask[o]


def per_second(ms, bid):
    """(T0, bid per second): the last tick in each second, forward-filled across seconds with none."""
    sec = ms // 1000
    T0 = int(sec[0])
    n = int(sec[-1]) - T0 + 1
    P = np.full(n, np.nan)
    P[sec - T0] = bid  # later ticks in the same second overwrite earlier ones
    idx = np.where(np.isfinite(P), np.arange(n), 0)
    np.maximum.accumulate(idx, out=idx)
    return T0, P[idx]


def bars_from_sec(P, T0, ts, sec):
    """OHLC bars at the given open times from a per-second series (bar = [ts, ts + sec))."""
    a = np.asarray(ts, np.int64) - T0
    ok = (a >= 0) & (a + sec <= len(P))
    starts = a[ok]
    o = P[starts]
    c = P[starts + sec - 1]
    P2 = np.r_[P, P[-1]]
    edges = np.empty(2 * len(starts), np.int64)
    edges[0::2], edges[1::2] = starts, starts + sec
    h = np.maximum.reduceat(P2, edges)[0::2]
    lo = np.minimum.reduceat(P2, edges)[0::2]
    return pd.DataFrame({"ts": np.asarray(ts, np.int64)[ok], "open": o, "high": h, "low": lo, "close": c, "volume": 0.0})


# ------------------------------------------------------------------------------------- the generator

def segments(bid):
    """Ranges between break jumps on a tick bid series. One row per range that ends in a break."""
    d = np.diff(bid)
    J = np.flatnonzero(np.abs(d) >= JUMP)
    rows = []
    for k in range(1, len(J)):
        s, e = J[k - 1] + 1, J[k]  # ticks s..e; s is the landing of jump k-1, e is the last before jump k
        seg = bid[s:e + 1]
        lo, hi = seg.min(), seg.max()
        land_dir = np.sign(d[J[k - 1]])
        land = bid[s]
        rows.append(dict(i0=s, i1=e, n=e - s + 1, W=hi - lo, land_dir=land_dir, land_at_edge=bool(land == (hi if land_dir > 0 else lo)),
                         visits_land=int((seg == land).sum()), jump=d[e], prev_jump=d[J[k - 1]],
                         cont=bool(np.sign(d[e]) == land_dir), pre_at_edge=bool(bid[e] == (hi if d[e] > 0 else lo)),
                         W_exact=float(abs(bid[e] - land)) if np.sign(d[e]) != land_dir else np.nan,
                         touches=int((seg == lo).sum() + (seg == hi).sum())))
    return pd.DataFrame(rows)


def p_rev(W, p):
    """P(a range of width W, entered at one edge, ends by breaking at the other edge): reflecting +/-1
    walk with break probability p on each boundary tick (closed form, linear harmonic function)."""
    W = np.asarray(W, float)
    return (1 - p) / (p * W + 2 * (1 - p))


def fit_params(inst):
    ms, bid, _ = load_ticks(inst, hi=SPLIT_T)
    S = segments(bid)
    p = float(S["cont"].sum() / S["visits_land"].sum())
    wx = S["W_exact"].dropna().astype(int).to_numpy()
    wx = wx[wx >= 1]
    ws, cnt = np.unique(wx, return_counts=True)
    wt = cnt / p_rev(ws, p)
    pmf = wt / wt.sum()
    J = np.abs(S["jump"].to_numpy()).astype(int)
    hours = (ms[-1] - ms[0]) / 3.6e6
    return dict(inst=inst, p=p, W_values=ws.tolist(), W_pmf=pmf.tolist(), J_values=np.sort(J).tolist(),
                n_ranges=int(len(S)), n_exact=int(len(wx)), hours=hours, first=int(ms[0] // 1000), last=int(ms[-1] // 1000),
                jumps_per_hour=float(len(S) / hours), jump_up_share=float((S["jump"] > 0).mean()),
                mean_absJ=float(J.mean()), martingale_drift=float(p * J.mean() - (1 - p)))


def rbsim(nsec, prm, seed, start=50000.0):
    """The fitted range-break process, one tick a second, as a float array of bids."""
    rng = np.random.default_rng(seed)
    p = prm["p"]
    Wv, Wp = np.asarray(prm["W_values"]), np.asarray(prm["W_pmf"])
    Jv = np.asarray(prm["J_values"])
    out = np.empty(nsec)
    W = int(rng.choice(Wv, p=Wp))
    lo = float(start)
    x = int(rng.integers(0, W + 1))
    pos = 0
    out[pos] = lo + x
    pos += 1
    while pos < nsec:
        K = int(rng.geometric(p))  # boundary ticks until (and including) the one that breaks
        cur = x
        while True:
            Lc = max(2048, 3 * K * W)
            steps = rng.integers(0, 2, Lc, dtype=np.int8) * 2 - 1
            S = cur + np.cumsum(steps, dtype=np.int64)
            y = np.mod(S, 2 * W)
            xs = np.where(y <= W, y, 2 * W - y)
            seq = np.r_[cur, xs]
            bnd = (seq == 0) | (seq == W)
            cb = np.cumsum(bnd)
            if cb[-1] >= K:
                k = int(np.searchsorted(cb, K))  # index in seq of the K-th boundary tick
                emit = seq[1:k + 1]
                m = min(len(emit), nsec - pos)
                out[pos:pos + m] = lo + emit[:m]
                pos += m
                at = int(seq[k])
                break
            emit = seq[1:]
            m = min(len(emit), nsec - pos)
            out[pos:pos + m] = lo + emit[:m]
            pos += m
            K -= int(cb[-1])
            cur = int(seq[-1])
            if pos >= nsec:
                return out
        if pos >= nsec:
            break
        J = int(rng.choice(Jv))
        W2 = int(rng.choice(Wv, p=Wp))
        if at == W:  # up break: lands on the new range's top
            land = lo + W + J
            lo, x = land - W2, W2
        else:
            land = lo - J
            lo, x = land, 0
        W = W2
        out[pos] = land
        pos += 1
    return out


def walk_sec(nsec, sigma, seed, start, garch=False):
    rng = np.random.default_rng(seed)
    sig = np.full(nsec, sigma)
    if garch:
        nh = nsec // 3600 + 1
        z = rng.normal(0, 1, nh)
        var = np.empty(nh)
        v = 1.0
        a, b = GARCH
        for i in range(nh):
            var[i] = v
            v = (1 - a - b) + a * v * z[i] ** 2 + b * v
        sig = sigma * np.sqrt(np.repeat(var / var.mean(), 3600)[:nsec])
    return start + np.cumsum(rng.normal(0, 1, nsec) * sig)


# ------------------------------------------------------------------------------------- characterise

def vr_curve(P, lags=(1, 60, 300, 900, 3600, 14400, 86400)):
    """Var(P[t+n]-P[t]) / (n Var(1-second step)) on a per-second series, non-overlapping."""
    d1 = np.var(np.diff(P))
    return {n: float(np.var(np.diff(P[::n])) / (n * d1)) for n in lags if len(P) > 20 * n}


def char_inst(inst):
    res = {}
    ms, bid, ask = load_ticks(inst)
    if not len(ms):
        return {}
    sp = ask - bid
    d = np.diff(bid)
    dt = np.diff(ms)
    per = {"discovery": ms < SPLIT_T * 1000, "confirmation": ms >= SPLIT_T * 1000}
    res["ticks"] = dict(n=int(len(ms)), first=str(pd.to_datetime(ms[0], unit="ms")), last=str(pd.to_datetime(ms[-1], unit="ms")),
                        spread_values={str(k): int(v) for k, v in zip(*np.unique(sp, return_counts=True))},
                        step_share_pm1=float((np.abs(d) == 1).mean()), step_share_jump=float((np.abs(d) >= JUMP).mean()),
                        step_other=int(((np.abs(d) != 1) & (np.abs(d) < JUMP)).sum()),
                        dt_ms_q=np.percentile(dt, [1, 50, 99]).tolist(), gaps_over_10s=int((dt > 10000).sum()),
                        interior_up_share=float((d[np.abs(d) == 1] > 0).mean()))
    S = segments(bid)
    S["ts"] = ms[S["i0"].to_numpy()] // 1000
    S["dur_s"] = (ms[S["i1"].to_numpy()] - ms[S["i0"].to_numpy()]) / 1000
    S["period"] = np.where(S["ts"] < SPLIT_T, "discovery", "confirmation")
    for name, g in S.groupby("period"):
        hrs = per[name].sum() / 3600
        p_land = g["cont"].sum() / g["visits_land"].sum()
        Jabs = np.abs(g["jump"])
        boot = np.random.default_rng(1).integers(0, len(g), (500, len(g)))
        cont, vis, ja = g["cont"].to_numpy(), g["visits_land"].to_numpy(), Jabs.to_numpy()
        drifts = [(cont[b].sum() / vis[b].sum()) * ja[b].mean() - (1 - cont[b].sum() / vis[b].sum()) for b in boot]
        res[name] = dict(
            ranges=int(len(g)), breaks_per_hour=float(len(g) / hrs), minutes_per_break=float(60 * hrs / len(g)),
            p_per_boundary_tick=float(p_land), p_all_touches=float(len(g) / g["touches"].sum()),
            land_at_far_edge=float(g["land_at_edge"].mean()), break_outward=float(g["pre_at_edge"].mean()),
            continuation_share=float(g["cont"].mean()), up_share=float((g["jump"] > 0).mean()),
            immediate_rebreak=float((g["n"] == 1).mean()),
            absJ_q=np.percentile(Jabs, [5, 25, 50, 75, 95]).tolist(), absJ_mean=float(Jabs.mean()),
            W_exact_q=np.nanpercentile(g["W_exact"], [5, 25, 50, 75, 95]).tolist(),
            W_obs_q=np.percentile(g["W"], [5, 25, 50, 75, 95]).tolist(),
            dur_min_q=(np.percentile(g["dur_s"], [5, 25, 50, 75, 95]) / 60).tolist(),
            corr_absJ_W=float(np.corrcoef(Jabs[g["W_exact"].notna()], g["W_exact"].dropna())[0, 1]),
            corr_W_next=float(pd.Series(g["W_exact"].to_numpy()).autocorr()),
            drift_per_boundary_tick=float(p_land * Jabs.mean() - (1 - p_land)),
            drift_ci=np.percentile(drifts, [5, 95]).tolist(),
            new_range_overlaps_old=float((g["W"].shift(-1) >= Jabs).mean()))
    T0, P = per_second(ms, bid)
    res["vr"] = {k: vr_curve(P[(np.arange(len(P)) + T0 < SPLIT_T) if k == "discovery" else (np.arange(len(P)) + T0 >= SPLIT_T)])
                 for k in ("discovery", "confirmation")}
    S.to_pickle(OUT / f"char_segments_{inst}.pkl")
    # do the broker's bars agree with bars rebuilt from its ticks (bars are bid)?
    agree = {}
    for iv in ("15m", "1h"):
        b = load_bars(inst, iv)
        b = b[(b["ts"] >= T0) & (b["ts"] + SEC[iv] <= T0 + len(P))]
        if len(b):
            t = bars_from_sec(P, T0, b["ts"].to_numpy(np.int64), SEC[iv])
            agree[iv] = {k: float((np.abs(t[k].to_numpy() - b[k].to_numpy()) <= 0.5).mean()) for k in ("open", "high", "low", "close")}
            agree[iv]["bars"] = int(len(b))
    res["bars_vs_ticks"] = agree
    # in bar units: ranges and breaks against ATR(14) of each timeframe, at the time of the range
    rows = []
    for iv in IVS:
        b = load_bars(inst, iv)
        if len(b) < 50:
            continue
        a = L.atr(*(b[k].to_numpy(float) for k in ("high", "low", "close")))
        k = np.searchsorted(b["ts"].to_numpy(), S["ts"].to_numpy(), "right") - 1
        ok = k >= 20
        A = a[k[ok]]
        rows.append(dict(iv=iv, atr_median=float(np.median(a[20:])),
                         W_atr_q=np.nanpercentile(S["W_exact"].to_numpy()[ok] / A, [25, 50, 75]).tolist(),
                         J_atr_q=np.percentile(np.abs(S["jump"].to_numpy()[ok]) / A, [25, 50, 75]).tolist(),
                         dur_bars_q=np.percentile(S["dur_s"].to_numpy()[ok] / SEC[iv], [25, 50, 75]).tolist(),
                         breaks_per_bar=float(SEC[iv] * res["discovery"]["breaks_per_hour"] / 3600)))
    res["bar_units"] = rows
    # stability: bars by year (all history), price units
    yrs = []
    for iv in ("1h", "1d"):
        b = load_bars(inst, iv)
        if not len(b):
            continue
        b["year"] = pd.to_datetime(b["ts"], unit="s").dt.year
        for y, g in b.groupby("year"):
            r = (g["high"] - g["low"]).to_numpy()
            dc = np.diff(g["close"].to_numpy())
            yrs.append(dict(iv=iv, year=int(y), bars=len(g), range_med=float(np.median(r)), range_p95=float(np.percentile(r, 95)),
                            sd_dc=float(np.std(dc)), kurt=float(pd.Series(dc).kurt()),
                            vr4=float(np.var(np.diff(g["close"].to_numpy()[::4])) / (4 * np.var(dc))) if len(dc) > 40 else np.nan))
    res["by_year"] = yrs
    return res


def char():
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "char.json"
    out = json.loads(f.read_text()) if f.exists() else {}
    for inst in os.environ.get("INSTS", ",".join(INST)).split(","):
        out[inst] = char_inst(inst)
    (OUT / "char.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float)[:6000])


def fit():
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "rb_sim_params.json"
    prm = json.loads(f.read_text()) if f.exists() else {}
    insts = os.environ.get("INSTS", ",".join(INST)).split(",")
    for inst in insts:
        if tick_files(inst):
            prm[inst] = fit_params(inst)
            q = {k: v for k, v in prm[inst].items() if k not in ("W_values", "W_pmf", "J_values")}
            print(inst, q, flush=True)
    for inst in insts:  # the iid walk's sigma per second, from the real discovery 1h bars
        b = load_bars(inst, "1h")
        b = b[b["ts"] < SPLIT_BAR]
        if len(b) > 100:
            prm.setdefault(inst, {})["sigma_1s"] = float(np.std(np.diff(b["close"].to_numpy())) / np.sqrt(3600))
        else:  # RB200 1h may not reach back: use its discovery ticks' 1h variance
            ms, bid, _ = load_ticks(inst, hi=SPLIT_T)
            if len(ms):
                T0, P = per_second(ms, bid)
                prm.setdefault(inst, {})["sigma_1s"] = float(np.std(np.diff(P[::3600])) / np.sqrt(3600))
    (OUT / "rb_sim_params.json").write_text(json.dumps(prm))


def validate():
    """The fitted simulator against real ticks of both periods: the same segment statistics and VR."""
    prm = json.loads((OUT / "rb_sim_params.json").read_text())
    f = OUT / "sim_validate.json"
    out = json.loads(f.read_text()) if f.exists() else {}
    for inst in os.environ.get("INSTS", ",".join(INST)).split(","):
        if inst not in prm or "p" not in prm[inst]:
            continue
        P = rbsim(int(180 * 86400), prm[inst], 99)
        S = segments(P)
        hrs = len(P) / 3600
        out[inst] = dict(breaks_per_hour=len(S) / hrs, p_land=float(S["cont"].sum() / S["visits_land"].sum()),
                         continuation_share=float(S["cont"].mean()), absJ_mean=float(np.abs(S["jump"]).mean()),
                         W_obs_q=np.percentile(S["W"], [5, 25, 50, 75, 95]).tolist(),
                         W_exact_q=np.nanpercentile(S["W_exact"], [5, 25, 50, 75, 95]).tolist(),
                         dur_min_q=(np.percentile(S["n"], [5, 25, 50, 75, 95]) / 60).tolist(),
                         immediate_rebreak=float((S["n"] == 1).mean()), vr=vr_curve(P))
        S.to_pickle(OUT / f"sim_segments_{inst}.pkl")
    (OUT / "sim_validate.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


# ---------------------------------------------------------------------------------------- the rules

def mr_trades(f, iv):
    """mean_reversion's frame_trades for the four rules, keeping what the tick replay needs."""
    o, h, l, c = (f[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    a = M.atr(h, l, c, 14)
    sig = M.signals(f, iv)
    rows = []
    for rule in MR_RULES:
        t, X = sig[rule]
        t = t[(t >= 1) & (t < n - 1)]
        e = t + 1
        entry = o[e]
        risk = entry - (l[t] - M.PAD * a[t])
        ok = np.isfinite(risk) & (a[t] > 0) & (risk >= M.MIN_RISK * a[t]) & (risk <= M.MAX_RISK * a[t])
        t, e, entry, risk = t[ok], e[ok], entry[ok], risk[ok]
        if not len(t):
            continue
        slip = M.SLIP * a[t]
        own, st, op, xb, xs = M.sim(o, h, l, c, e, entry, risk, slip, X, M.H_OWN)
        up, dn = M.fpass(h, l, e, entry, risk)
        for i in range(len(t)):
            rows.append(dict(rule=rule, f=int(e[i]), entry=float(entry[i]), stop=float(entry[i] - risk[i]),
                             risk=float(risk[i]), atr=float(a[t[i]]), bar_st=float(st[i]), bar_own=float(own[i]),
                             xb_st=int(xs[i]), xb_own=int(xb[i]), mfe_bar=float(up[i]), X=X))
    return rows


def lrc_trades(f, cost_px):
    o, h, l, c = (f[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    F = L.Frame(o, h, l, c, f["ts"].to_numpy(np.int64), np.full(len(c), cost_px))
    rows = [r for r in L.rules_r1_r2(F) if r["rule"] == "R2"]
    r5, _ = L.levels_r5(F)
    rows += [r for r in r5 if r["rule"] == "R5s"]
    out = []
    for r in rows:
        risk = r["entry"] - r["stop"]
        a_t = risk / r["risk_atr"]
        out.append(dict(rule=r["rule"], f=int(r["f"]), entry=float(r["entry"]), stop=float(r["stop"]), risk=float(risk),
                        atr=float(a_t), bar_X2=float(r["X2"]), bar_TR=float(r["TR"]), bar_BAND=float(r["BAND"]),
                        xb_X2=int(r["x2_bar"]), xb_TR=int(r["tr_bar"]), xb_BAND=int(r["band_bar"]), mfe_bar=float(r["mfe"]),
                        F=F))
    return out


def nights(t0, t1):
    return np.maximum(0, np.floor_divide(np.asarray(t1), 86400) - np.floor_divide(np.asarray(t0), 86400))


# ------------------------------------------------------------------------------------ the tick replay

class Tape:
    """A per-second bid series with its spread; side +1 reads bid, side -1 reads -(bid + spread)."""

    def __init__(self, T0, P, spread):
        self.T0, self.P, self.s = T0, P, spread

    def seg(self, side, t0, t1):
        a, b = t0 - self.T0, t1 - self.T0
        if a < 0 or b > len(self.P):
            return None
        x = self.P[a:b]
        return x if side > 0 else -(x + self.s)

    def gross(self, side, t0, t1):
        a, b = t0 - self.T0, t1 - self.T0
        if a < 0 or b > len(self.P):
            return None
        x = self.P[a:b]
        return x if side > 0 else -x


def first(mask):
    k = int(np.argmax(mask)) if len(mask) else 0
    return k if len(mask) and mask[k] else None


def tick_trade(tape, side, ts, sec, f, o_f, stop, kind, H, **kw):
    """One long (on the side's tape) from the open of bar f. Returns (R net of spread, exit second, how,
    jump-fill flag) or None when the window is outside the tape. R's denominator is o_f - stop."""
    n = len(ts)
    end_bar = min(n - 1, f + H)
    t0, t1 = int(ts[f]), int(ts[end_bar]) + sec
    x = tape.seg(side, t0, t1)
    if x is None:
        return None
    risk = o_f - stop
    entry = x[0] + tape.s
    bar_of = np.searchsorted(ts, t0 + np.arange(len(x)), "right") - 1  # bar index of each second
    lo_thr = np.full(len(x), stop)
    hi_thr = np.full(len(x), np.inf)
    exit_at = None  # a forced exit second (own exit / time stop)
    if kind == "X2":
        hi_thr[:] = o_f + 2 * risk
    elif kind == "TR":
        hh, best0, a_t = kw["h"], max(o_f, kw["c"][f]), kw["a_t"]
        js = np.arange(f, end_bar + 1)
        prev_best = np.maximum.accumulate(np.r_[best0, np.maximum(best0, hh[f + 1:end_bar])]) if end_bar > f else np.array([best0])
        trail = np.r_[stop, np.maximum(stop, prev_best - L.TRAIL * a_t)][:len(js)]
        lo_thr = trail[bar_of - f]
    elif kind == "BAND":
        band = kw["band"]
        bt = np.r_[np.inf, band[f:end_bar]]  # bar j >= f+1 uses band[j-1]
        hi_thr = np.where(np.isfinite(bt), bt, np.inf)[bar_of - f]
    elif kind in ("st", "own"):
        X = kw["X"]
        js = np.arange(f, min(n, f + M.H_OWN))
        hit = np.flatnonzero(X[js])
        if len(hit):
            j = js[hit[0]]
            exit_at = (int(ts[j + 1]) if j + 1 < n else int(ts[j]) + sec - 1) - t0
        else:
            j = js[-1]
            exit_at = int(ts[j]) + sec - 1 - t0
        if kind == "own":
            lo_thr[:] = -np.inf
    lim = len(x) if exit_at is None else min(len(x), exit_at + 1)
    xs = x[1:lim]
    k = first((xs <= lo_thr[1:lim]) | (xs >= hi_thr[1:lim]))
    if k is not None:
        k += 1
        px = x[k]
        how = "stop" if x[k] <= lo_thr[k] else "limit"
        jump = how == "stop" and abs(x[k] - x[k - 1]) >= JUMP
    elif exit_at is not None and exit_at < len(x):
        k, px, how, jump = exit_at, x[exit_at], "rule", False
    else:
        k, px, how, jump = len(x) - 1, x[-1], "cap", False
    return (px - entry) / risk, t0 + k, how, jump


def tick_mfe(tape, side, ts, sec, f, o_f, stop):
    """Most R reached (gross, bid series) before the stop, within TICK_H bars."""
    end_bar = min(len(ts) - 1, f + TICK_H)
    x = tape.gross(side, int(ts[f]), int(ts[end_bar]) + sec)
    if x is None:
        return np.nan
    risk = o_f - stop
    k = first(x[1:] <= stop)
    seg = x[:k + 1] if k is not None else x
    return max(0.0, (seg.max() - o_f) / risk)


def tick_twin(tape, rng, ts, sec, f, o_f, risk, t_exit):
    """The coin twin: a random side from the same open with the same stop distance, out at the original's exit
    second or its own stop."""
    side = 1 if rng.random() < 0.5 else -1
    t0 = int(ts[f])
    x = tape.seg(side, t0, max(t0 + 1, int(t_exit) + 1))
    if x is None:
        return np.nan
    o = x[0] if side > 0 else x[0] + tape.s  # the side's own bar open (bid, or -bid)
    entry = x[0] + tape.s
    stop = o - risk
    k = first(x[1:] <= stop)
    px = x[k + 1] if k is not None else x[-1]
    return (px - entry) / risk


# ---------------------------------------------------------------------------------------------- run

def sources_for(inst, prm):
    src = [("real", 0)]
    if inst in prm and "p" in prm[inst]:
        src += [("rbsim", s) for s in SEEDS]
    if inst in prm and "sigma_1s" in prm[inst]:
        src += [(k, s) for k in ("iid", "garch") for s in SEEDS]
    return src


def build(inst, src, seed, prm):
    """(per-timeframe bars, Tape or None, spread and swap per timeframe)."""
    real = {iv: load_bars(inst, iv) for iv in IVS}
    real = {iv: b for iv, b in real.items() if len(b) >= 400}
    if src == "real":
        ms, bid, _ = load_ticks(inst)
        tape = None
        if len(ms):
            T0, P = per_second(ms, bid)
            tape = (T0, P)
        return real, tape, {iv: (SPREAD, SWAP) for iv in real}
    T0 = min(int(b["ts"].iloc[0]) for b in real.values())
    T1 = max(int(b["ts"].iloc[-1]) + SEC[iv] for iv, b in real.items())
    nsec = T1 - T0
    sd = zlib.crc32(f"{inst}{src}{seed}".encode()) % 2 ** 31
    start = float(real[max(real, key=lambda k: len(real[k]))]["open"].iloc[0])
    if src == "rbsim":
        P = rbsim(nsec, prm[inst], sd, start)
    else:
        P = walk_sec(nsec, prm[inst]["sigma_1s"], sd, start, garch=(src == "garch"))
    bars, costs = {}, {}
    for iv, rb in real.items():
        b = bars_from_sec(P, T0, rb["ts"].to_numpy(np.int64), SEC[iv])
        bars[iv] = b
        if src == "rbsim":
            costs[iv] = (SPREAD, SWAP)
        else:
            ar = np.median(L.atr(*(rb[k].to_numpy(float) for k in ("high", "low", "close")))[50:])
            aw = np.median(L.atr(*(b[k].to_numpy(float) for k in ("high", "low", "close")))[50:])
            costs[iv] = (SPREAD * aw / ar, SWAP * aw / ar)
    return bars, (T0, P), costs


def job(args):
    inst, src, seed = args
    part = OUT / "parts" / f"{inst}_{src}_{seed}.pkl"
    if part.exists():
        return f"{part.name} cached"
    prm = json.loads((OUT / "rb_sim_params.json").read_text())
    bars, tp, costs = build(inst, src, seed, prm)
    rows = []
    rng = np.random.default_rng(zlib.crc32(f"{inst}{src}{seed}twin".encode()))
    for iv, df in bars.items():
        sp, sw = costs[iv]
        sec = SEC[iv]
        ts = df["ts"].to_numpy(np.int64)
        tape = Tape(tp[0], tp[1], sp) if tp is not None else None
        for side, d in ((1, df), (-1, L.flip(df))):
            o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
            ents = [(r, LRC_EXITS) for r in lrc_trades(d, sp)] + [(r, MR_EXITS) for r in mr_trades(d, iv)]
            for r, exits in ents:
                f = r["f"]
                for ex in exits:
                    xb = min(len(ts) - 1, max(f, r[f"xb_{ex}"]))
                    nt = float(nights(ts[f], ts[xb] + sec // 2))
                    R_bar = r[f"bar_{ex}"] - (sp / r["risk"] if ex in MR_EXITS else 0.0) - sw * nt / r["risk"]
                    row = dict(inst=inst, src=src, seed=seed, iv=iv, rule=r["rule"], exit=ex, side=side, ts=int(ts[f]),
                               risk=r["risk"], risk_atr=r["risk"] / r["atr"] if r["atr"] > 0 else np.nan,
                               R_bar=R_bar, R_bar_noswap=R_bar + sw * nt / r["risk"], mfe_bar=r["mfe_bar"],
                               R_tick=np.nan, R_tick_noswap=np.nan, how="", jump=False, mfe_tick=np.nan, twin=np.nan)
                    if tape is not None:
                        kw = dict(h=h, c=c, a_t=r["atr"])
                        if ex == "BAND":
                            kw["band"] = r["F"].ub
                        if ex in MR_EXITS:
                            kw["X"] = r["X"]
                        H = M.H_OWN if ex in MR_EXITS else L.CAP
                        res = tick_trade(tape, side, ts, sec, f, o[f], r["stop"], ex, H, **kw)
                        if res is not None:
                            R, tx, how, jump = res
                            ntt = float(nights(ts[f], tx))
                            row.update(R_tick=R - sw * ntt / r["risk"], R_tick_noswap=R, how=how, jump=bool(jump),
                                       mfe_tick=tick_mfe(tape, side, ts, sec, f, o[f], r["stop"]),
                                       twin=tick_twin(tape, rng, ts, sec, f, o[f], r["risk"], tx) - sw * ntt / r["risk"])
                    rows.append(row)
    t = pd.DataFrame(rows)
    for col in t.columns:
        if t[col].dtype == np.float64 and col not in ("risk",):
            t[col] = t[col].astype(np.float32)
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    t.to_pickle(part)
    return f"{part.name}: {len(t)} rows"


def run():
    prm = json.loads((OUT / "rb_sim_params.json").read_text())
    jobs = [(inst, s, k) for inst in INST for s, k in sources_for(inst, prm)]
    only = os.environ.get("ONLY")
    if only:
        jobs = [j for j in jobs if only in f"{j[0]}_{j[1]}_{j[2]}"]
    with ProcessPoolExecutor(WORKERS) as pool:
        for msg in pool.map(job, jobs, chunksize=1):
            print(" ", msg, flush=True)
    print("run done", flush=True)


def main():
    mode = os.environ.get("MODE", "char")
    {"char": char, "fit": fit, "validate": validate, "run": run}[mode]() if mode in ("char", "fit", "validate", "run") else None
    if mode == "agg":
        import rb100_agg
        rb100_agg.agg()
    if mode == "plot":
        import rb100_agg
        rb100_agg.plot()


if __name__ == "__main__":
    main()
