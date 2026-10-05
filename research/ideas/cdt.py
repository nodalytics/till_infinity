"""Crypto daily trend combination: 2MAAOS, DHLAOS, Weinstein Stage 2 and DISPLACE_C, alone and combined.

Frozen in `cdt_rule.json` (commit d50a9ce) before any real-data run. Every signal is traded with the
desk's geometry (next open, a 3-bar structural stop at least 0.25 ATR away, the strategy's own state
exit or a 2-ATR trail) on Binance USDT perpetuals, against matched iid and GARCH walks, a random-entry
twin with the same exposure and 1/(N+1). The report splits each trade into the crypto market's move
and a residual, compares it with BTC held over the same windows, and builds an equal-risk book.

  DATA=.data/cdt/data OUT=.data/cdt/out MODE=run IV=1d python research/ideas/cdt.py
  MODE=sanity   DISPLACE_C as published (turn_confirm, fresh58 1d) must give +0.142R
  MODE=report   tables and verdicts;  MODE=plot   figures
"""
from __future__ import annotations

import json
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

import cdt_data as D  # noqa: E402

RULE = json.loads((HERE / "cdt_rule.json").read_text())
OUT = Path(os.environ.get("OUT", ".data/cdt/out"))
IVSEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
NS = (0.5, 1, 2, 4, 10, 20)
HOLD = 300
SLIP = 0.05
PAD = 0.1
MIN_RISK = 0.25
TRAIL = 2.0
FEE = 0.0007
K_TWIN = 20
WARM = 200
SPLIT = pd.Timestamp("2024-01-01", tz="UTC").timestamp()
STRATS = ("C1", "C2", "C3", "C4", "AGREE")
NAMES = {"C1": "2MAAOS", "C2": "DHLAOS", "C3": "Stage 2/4", "C4": "DISPLACE_C", "AGREE": "AGREE (>=2 of 4)",
         "DCS": "DISPLACE_C x Stage"}
EXITS = ("STATE", "TRAIL")
WALK_SEEDS = {"1d": 5, "4h": 1, "1h": 1, "15m": 1}


# ------------------------------------------------------------------------------------------ signals

def ups_v1(df):
    """DISPLACE_C up and DELIVERY_SHIFT down known at each bar (turn_trade.ups' two arrays), from the v1
    chart alone - the same entities as the full parse, about six times faster. Series over 60k bars are
    parsed in 50k-bar segments with 5k bars of warm-up (as tail_scan)."""
    from mcfl.parse import parse
    n = len(df)
    dc, dsd = np.zeros(n, bool), np.zeros(n, bool)
    seg, warm = (50_000, 5_000) if n > 60_000 else (n, 0)
    for s0 in range(0, n, seg):
        a = max(0, s0 - warm)
        sub = df.iloc[a:min(n, s0 + seg)].reset_index(drop=True)
        for e in parse(sub, v2=False, time=False).entities:
            k = e.known_at + a
            if not (s0 <= k < min(n, s0 + seg)):
                continue
            up = getattr(e.dir, "name", str(e.dir)).upper() in ("UP", "U")
            if e.type == "DISPLACE_C" and up:
                dc[k] = True
            elif e.type == "DELIVERY_SHIFT" and not up:
                dsd[k] = True
    return dc, dsd


def next_false(cond):
    """nf[k] = the first j >= k where cond[j] is False (len(cond) if none)."""
    n = len(cond)
    idx = np.where(cond, n, np.arange(n))
    return np.minimum.accumulate(idx[::-1])[::-1]


def windows(entries, off_from, n, cap=None):
    """The union of ON windows [t, off) over the entries; off = off_from[t + 1] (capped at t + cap)."""
    d = np.zeros(n + 1, int)
    for t in np.flatnonzero(entries):
        e = off_from[t + 1] if t + 1 < n else n
        if cap is not None:
            e = min(e, t + cap)
        d[t] += 1
        d[min(e, n)] -= 1
    return np.cumsum(d[:n]) > 0


def week_starts(ts):
    """Monday 00:00 UTC of each bar's ISO week (1970-01-05 was a Monday)."""
    m = 4 * 86400
    return np.unique(((np.asarray(ts, np.int64) - m) // 604800) * 604800 + m)


def components(df, iv):
    """Entries per side and the off-arrays of every strategy. Returns {strat: {side: (entries, off_from, cap)}}
    plus the coin's own stage."""
    import geraked_eas as GE
    import geraked_ind as G
    import tv_indicators as TV
    from mcfl.parse import flip
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy(np.int64)
    n = len(c)
    b = GE.Bars(o, h, l, c, ts, GE._tick(c), week_starts(ts) if iv == "1d" else None)
    s1, s2 = GE.ea_2MAAOS(b), GE.ea_DHLAOS(b)
    bull, bear = s1["ind"]["bull"], s1["ind"]["bear"]
    ma50, ma200 = s1["ind"]["ma50"], s1["ind"]["ma200"]
    stage = TV.stages(df[["ts", "open", "high", "low", "close", "volume"]], "pct")
    dcL, dsdL = ups_v1(df)
    dcS, dsdS = ups_v1(flip(df))
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    lowp = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    high3 = pd.Series(h).rolling(3).max().to_numpy()
    highp = pd.Series(h).shift(3).rolling(9).max().to_numpy()
    at_low, at_high = np.nan_to_num(low3 <= lowp).astype(bool), np.nan_to_num(high3 >= highp).astype(bool)
    H10 = max(1, int(10 * 86400 / IVSEC[iv]))
    ok = np.arange(n) >= WARM
    S = {}
    c1L = (bull > bear) & (ma50 > ma200)
    c1S = (bear > bull) & (ma50 < ma200)
    S["C1"] = {1: (s1["buy"] & ok, next_false(c1L), None), -1: (s1["sell"] & ok, next_false(c1S), None)}
    S["C2"] = {1: (s2["buy"] & ok, next_false(bull > bear), None), -1: (s2["sell"] & ok, next_false(bear > bull), None)}
    prev = np.r_[1, stage[:-1]]
    S["C3"] = {1: ((stage == 2) & (prev != 2) & ok, next_false(stage == 2), None),
               -1: ((stage == 4) & (prev != 4) & ok, next_false(stage == 4), None)}
    S["C4"] = {1: (at_low & dcL & ok, next_false(~dsdL), H10), -1: (at_high & dcS & ok, next_false(~dsdS), H10)}
    on = {s: [] for s in (1, -1)}
    for k in ("C1", "C2", "C3", "C4"):
        for s in (1, -1):
            e, off, cap = S[k][s]
            on[s].append(windows(e, off, n, cap))
    nL, nS = np.sum(on[1], 0), np.sum(on[-1], 0)
    agL, agS = (nL >= 2) & (nL > nS), (nS >= 2) & (nS > nL)
    S["AGREE"] = {1: (agL & ~np.r_[False, agL[:-1]] & ok, next_false(agL), None),
                  -1: (agS & ~np.r_[False, agS[:-1]] & ok, next_false(agS), None)}
    return S, stage, dict(nL=nL, nS=nS)


# ------------------------------------------------------------------------------------------ trades

class Arr:
    """The chart for one side, as a long: shorts on the negated chart (highs and lows swapped)."""

    def __init__(self, df, side):
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        if side < 0:
            o, h, l, c = -o, -l, -h, -c
        pad = HOLD + 2
        self.n = len(o)
        self.O = np.r_[o, np.full(pad, np.nan)]
        self.H = np.r_[h, np.full(pad, -np.inf)]
        self.L = np.r_[l, np.full(pad, np.inf)]
        self.C = np.r_[c, np.full(pad, np.nan)]


def first(mask):
    """Index of the first True along the last axis, or the axis length."""
    any_ = mask.any(-1)
    return np.where(any_, mask.argmax(-1), mask.shape[-1])


def barrier(A, f, entry, stop, risk):
    """The most R reached before the initial stop within HOLD bars (a bar touching the stop counts as
    stopped), for one or many trades (f, entry, stop, risk broadcast)."""
    f = np.atleast_1d(f)
    idx = f[:, None] + np.arange(HOLD)[None, :]
    Lw, Hw = A.L[idx], A.H[idx]
    ks = first(Lw <= np.atleast_1d(stop)[:, None])
    Hm = np.where(np.arange(HOLD)[None, :] < ks[:, None], Hw, -np.inf)
    best = Hm.max(1)
    return np.maximum(0.0, (best - np.atleast_1d(entry)) / np.atleast_1d(risk))


def trade(A, t, a, cost_atr_t, off, cap, exit_):
    """One trade from signal bar t: (R, mfe, risk, entry, last bar held, final price, stopped)."""
    n = A.n
    f = t + 1
    entry = A.O[f]
    stop = min(np.min(A.L[t - 2:t + 1]) - PAD * a, entry - MIN_RISK * a)
    risk = entry - stop
    cost = cost_atr_t * a / risk
    end = min(n, f + HOLD)  # bars f .. end-1
    m = end - f
    Lw, Hw = A.L[f:end], A.H[f:end]
    mfe = float(barrier(A, f, entry, stop, risk)[0])
    if exit_ == "STATE":
        joff = off[f] if f < n else n
        if cap is not None:
            joff = min(joff, t + cap)
        ks = int(first(Lw <= stop))
        jo = joff - f  # window index of the first off bar
        if ks < m and ks <= jo:
            fill = stop if ks == 0 else min(A.O[f + ks], stop)
            px, last, stopped = fill - SLIP * a, f + ks, True
        elif jo < m:  # out at the open after the first off bar (the last close if the data ends there)
            stopped = False
            px, last = (A.O[joff + 1], joff) if joff + 1 < n else (A.C[n - 1], n - 1)
        else:  # held HOLD bars
            px, last, stopped = A.C[end - 1], end - 1, False
    else:  # TRAIL: 2 ATR(t) behind the best high of completed bars, from the second bar
        prevbest = np.maximum.accumulate(np.r_[entry, Hw[:-1]])
        tr = np.maximum(stop, prevbest - TRAIL * a)
        tr[0] = stop
        k = int(first(Lw <= tr))
        if k < m:
            fill = stop if k == 0 else min(A.O[f + k], tr[k])
            px, last, stopped = fill - SLIP * a, f + k, True
        else:
            px, last, stopped = A.C[end - 1], end - 1, False
    R = (px - entry) / risk - cost
    return R, mfe, risk, entry, int(last), float(px), stopped, cost


def daily_path(A, ts, sec, f, last, entry, px, risk, cost):
    """Mark-to-market R per UTC day while the trade is open: closes of bars f..last-1, then the exit
    price at `last` (costs half on the first day, half on the last)."""
    marks = np.r_[A.C[f:last], px]
    dR = np.diff(np.r_[entry, marks]) / risk
    day = (ts[f:last + 1] + sec) // 86400 - 1
    d0 = int(day[0])
    v = np.bincount((day - d0).astype(int), weights=dR).astype(np.float32)
    v[0] -= cost / 2
    v[-1] -= cost / 2
    return d0, v


def twins(A, t_hold, risk_atr, atr, cost_atr, rng, k=K_TWIN):
    """k random-entry twins: same side and risk in ATR, held `t_hold` bars unless stopped first."""
    n = A.n
    hi = n - 2 - t_hold
    if hi <= WARM:
        return np.nan, np.nan
    tp = rng.integers(WARM, hi, k)
    a = atr[tp]
    good = np.isfinite(a) & (a > 0)
    tp, a = tp[good], a[good]
    if not len(tp):
        return np.nan, np.nan
    f = tp + 1
    entry = A.O[f]
    risk = risk_atr * a
    stop = entry - risk
    idx = f[:, None] + np.arange(t_hold)[None, :]
    ks = first(A.L[idx] <= stop[:, None])
    stopped = ks < t_hold
    fill = np.where(ks == 0, stop, np.minimum(A.O[f + np.minimum(ks, t_hold - 1)], stop)) - SLIP * a
    xo = A.O[np.minimum(f + t_hold, n - 1)]
    px = np.where(stopped, fill, xo)
    R = (px - entry) / risk - cost_atr[tp] / risk_atr
    mfe = barrier(A, f[:1], entry[:1], stop[:1], risk[:1])[0]
    return float(np.nanmean(R)), float(mfe)


# ------------------------------------------------------------------------------------------ series

def btc_daily(iv, src, seed, btc="BTC"):
    """BTC's daily bars for the regime: the real 1d file, or BTC's walk at this timeframe resampled to
    UTC days (so a walk panel's regime comes from its own BTC). `btc`: 'BTC' (Binance) or 'mt5:BTCUSD'."""
    if src == "real":
        d = D.load(btc, "1d")
    else:
        d, _ = series(btc, iv, src, seed)
        g = d["ts"] // 86400 * 86400
        d = d.groupby(g).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                             close=("close", "last")).reset_index().rename(columns={"index": "ts"})
        d["volume"] = 1.0
    return d


def regime(btc, ts, sec):
    """For each bar (open ts): BTC's last completed daily close (close time <= the bar's close) above /
    below its 200-day SMA, and BTC's daily Stage (pct) there."""
    import tv_indicators as TV
    dts = btc["ts"].to_numpy(np.int64)
    c = btc["close"].to_numpy(float)
    sma = pd.Series(c).rolling(200).mean().to_numpy()
    st = TV.stages(btc[["ts", "open", "high", "low", "close", "volume"]], "pct")
    k = np.searchsorted(dts + 86400, np.asarray(ts, np.int64) + sec, side="right") - 1
    okk = k >= 0
    kk = np.maximum(k, 0)
    up = okk & np.nan_to_num(c[kk] > sma[kk]).astype(bool)
    dn = okk & np.nan_to_num(c[kk] < sma[kk]).astype(bool)
    stg = np.where(okk, st[kk], 0)
    return {1: up, -1: dn}, {1: stg == 2, -1: stg == 4}


def series(coin, iv, src, seed):
    """Bars and each bar's cost in ATR units (the real series' cost, also on its walks)."""
    import geraked_eas as GE
    from mcfl import candles
    df = D.load(coin, iv)
    if df is None:
        return None, None
    a = candles._atr(df)
    if coin.startswith("mt5:"):
        cost_px = np.full(len(df), D.MT5_COST[coin[4:]])
    elif coin.startswith("mt5x:"):
        cost_px = np.full(len(df), D.mt5x_cost(coin[5:], df))
    else:
        cost_px = FEE * df["close"].to_numpy(float)
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    cost_atr = cost_px / np.maximum(a, 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if src != "real":
        s = zlib.crc32(f"cdt{coin}{iv}{src}{seed}".encode()) % 2 ** 31
        w = GE.make_walk(df, "garch" if src == "garch" else "iid", s)
        w["volume"] = 1.0
        df = w[["ts", "open", "high", "low", "close", "volume"]]
    return df.reset_index(drop=True), cost_atr


def job(spec):
    """Every strategy's trades on one series. Writes OUT/jobs/<iv>/<src><seed>_<coin>.pkl."""
    from mcfl import candles
    coin, iv, src, seed = spec
    path = OUT / "jobs" / iv / f"{src}{seed}_{coin}.pkl"
    if path.exists():
        return str(path)
    t0 = time.time()
    df, cost_atr = series(coin, iv, src, seed)
    if df is None or len(df) < WARM + 50:
        return None
    sec = IVSEC[iv]
    ts = df["ts"].to_numpy(np.int64)
    atr = candles._atr(df)
    S, stage, _ = components(df, iv)
    reg200, regst = regime(btc_daily(iv, src, seed, "mt5:BTCUSD" if coin.startswith("mt5") else "BTC"), ts, sec)
    rng = np.random.default_rng(zlib.crc32(f"twin{coin}{iv}{src}{seed}".encode()))
    keep_path = iv in ("1d", "4h")
    rows, paths = [], []
    for side in (1, -1):
        A = Arr(df, side)
        for strat in STRATS:
            ent, off, cap = S[strat][side]
            for t in np.flatnonzero(ent):
                if t + 2 >= len(df) or not atr[t] > 0 or t < 3:
                    continue
                for ex in EXITS:
                    R, mfe, risk, entry, last, px, stopped, cost = trade(A, t, atr[t], cost_atr[t], off, cap, ex)
                    if not np.isfinite(R):
                        continue
                    hold = last - t  # bars from the entry bar through the last bar held
                    r = dict(coin=coin, iv=iv, src=src, seed=seed, strat=strat, exit=ex, side=side, t=int(t),
                             ts=int(ts[t]), x_ts=int(ts[last]), R=R, mfe=mfe, risk_atr=risk / atr[t],
                             risk_frac=risk / abs(entry), hold=hold, stopped=stopped,
                             reg200=bool(reg200[side][t]), regst=bool(regst[side][t]),
                             stage_ok=bool(stage[t] == (2 if side > 0 else 4)))
                    if src == "real":
                        r["twin_R"], r["twin_mfe"] = twins(A, max(1, hold), risk / atr[t], atr, cost_atr, rng)
                    if keep_path:
                        d0, v = daily_path(A, ts, sec, t + 1, last, entry, px, risk, cost)
                        r["path"] = len(paths)
                        paths.append((d0, v))
                    rows.append(r)
    out = dict(trades=pd.DataFrame(rows), paths=paths, first=int(ts[0]), last=int(ts[-1]))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, path)
    print(f"  {iv} {src}{seed} {coin}: {len(rows)} trades, {time.time() - t0:.0f}s", flush=True)
    return str(path)


def specs(iv):
    coins = {"1d": D.CORE + D.FRESH131 + D.SETD, "4h": D.CORE + D.FRESH131, "1h": D.CORE + D.FRESH131,
             "15m": D.CORE + D.FRESH58}[iv]
    coins = [c for c in coins if D.kpath(c, iv).exists()]
    coins += [f"mt5:{s}" for s in D.MT5_COST if D.load(f"mt5:{s}", iv) is not None]
    if iv in ("1d", "4h") and os.environ.get("OTHER", "1") == "1":
        coins += [f"mt5x:{s}" for s in D.mt5x_specs() if D.load(f"mt5x:{s}", iv) is not None]
    out = [(c, iv, "real", 0) for c in coins]
    for k in range(WALK_SEEDS[iv]):
        out += [(c, iv, s, k) for s in ("iid", "garch") for c in coins]
    return out


def run():
    iv = os.environ.get("IV", "1d")
    sp = specs(iv)
    todo = [s for s in sp if not (OUT / "jobs" / iv / f"{s[2]}{s[3]}_{s[0]}.pkl").exists()]
    print(f"{iv}: {len(sp)} series, {len(todo)} to do", flush=True)
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 6))) as pool:
        for _ in pool.map(job, todo, chunksize=1):
            pass
    (OUT / f"run_{iv}.done").write_text("ok")


def sanity():
    """DISPLACE_C as published: turn_trade.trades_exits (E2, no risk floor) on fresh58 1d with this study's
    data, with ups swapped for the v1 parse (identical entities). turn_confirm: +0.142R [+0.015, +0.280]."""
    import turn_trade as TT
    from mcfl import candles
    from mcfl.parse import flip
    TT.SEC["1d"] = 86400

    def ups(df, both=False):
        dc, dsd = ups_v1(df)
        z = np.zeros(len(df), bool)
        return {"DISPLACE_C": dc, "BREACH_REVERT": z, "DELIVERY_SHIFT": z, "DELIVERY_SHIFT_DOWN": dsd}
    TT.ups = ups
    rows = []
    for coin in D.FRESH58:
        df = D.load(coin, "1d")
        if df is None or len(df) < 300:
            continue
        cost_atr = FEE * df["close"].to_numpy(float) / np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
        cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
        for side, frame in ((1, df), (-1, flip(df))):
            rows += TT.trades_exits(frame, side, cost_atr, "fresh:real", coin, "1d")
    d = pd.DataFrame(rows)
    d = d[d["T1"]].assign(R=lambda x: x["E2"])
    lo, hi = TT.boot(d, np.random.default_rng(51))
    print(f"SANITY DISPLACE_C E2 fresh58 1d: n={len(d)} R {d['R'].mean():+.3f} [{lo:+.3f}, {hi:+.3f}] "
          f"(turn_confirm: +0.142 [+0.015, +0.280])", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sanity.txt").write_text(f"n={len(d)} R={d['R'].mean():+.4f} lo={lo:+.4f} hi={hi:+.4f}\n")


def main():
    mode = os.environ.get("MODE", "run")
    if mode == "run":
        run()
    elif mode == "sanity":
        sanity()
    elif mode == "report":
        import cdt_report
        cdt_report.report()
    elif mode == "plot":
        import cdt_report
        cdt_report.plot()


if __name__ == "__main__":
    main()
