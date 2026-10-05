"""The turn trades T2 and T_any, and the violent-origin zones SIG, re-run with the corrected BREACH_REVERT side.

Frozen in `turn_retrade_rule.json` before this ran. MCFL labels BREACH_REVERT by the swept swing: DOWN is
a swing low traded through and closed back above, the bullish one. `turn_trade.ups` read the UP label
until 2026-10-04, so T2, T_any and SIG ran on the wrong side. Everything else is the frozen code:
`turn_trade.trades` (fixed 1R/2R/3R, `turn_rule.json`), `turn_trade.trades_exits` (E1 trail, E2 opposite
CISD, `turn_rule2.json`), `turn_zones.zones` (`turn_zone_rule.json`) and `deriv_turns.lows` (the
signature's lift). The old side is carried alongside (`T2_old`, `T_any_old`, `SIG_old`) on the same bars
and walks, so the comparison is like for like.

  OUT=... MT5BT_DB=... MODE=run|summary|plot python research/ideas/turn_retrade.py
  OUT=... CACHE=... MODE=confirm CELLS=... python research/ideas/turn_retrade.py   (fresh coins, SET_C)
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

import turn_trade as TT  # noqa: E402  (first, so every later import gets the fixed module)
import turn_zones as TZ  # noqa: E402
import deriv_turns as DT  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/turn_retrade"))
CACHE = Path(os.environ.get("CACHE", os.path.expanduser("~/till_infinity/data/binance_fresh")))
IVS = ("15m", "1h", "4h", "1d")
SECS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
TT.SEC.update(SECS)
TZ.SEC.update(SECS)
TZ.RZ.setdefault("15m", 2.637)  # violence.py's MT5 VIOLENT range_z threshold at 15m
SOURCES = ("real", "walk", "garch")
NS = (0.5, 1, 2, 4, 10)
TT.SIGNALS.update({"T2_old": ("BREACH_REVERT_OLD",),
                   "T_any_old": ("DISPLACE_C", "BREACH_REVERT_OLD", "DELIVERY_SHIFT")})
SIGS = ("T1", "T2", "T_any", "T2_old", "T_any_old")


# ------------------------------------------------------------------ one parse per frame, both sides of T2

_memo: dict = {}


def ups_both(df, both=False):
    """`turn_trade.ups` (the fixed one) plus BREACH_REVERT_OLD, the UP-labelled event the old code read.
    Memoised on the frame object, so the trade, the exits, the zones and the lift share one parse."""
    key = id(df)
    hit = _memo.get(key)
    if hit is not None and hit[0] is df:
        return hit[1]
    from mcfl.parse import parse
    n = len(df)
    out = {p: np.zeros(n, bool) for p in ("DISPLACE_C", "BREACH_REVERT", "DELIVERY_SHIFT",
                                           "DELIVERY_SHIFT_DOWN", "BREACH_REVERT_OLD")}
    for e in parse(df).entities:
        if e.type in ("DISPLACE_C", "BREACH_REVERT", "DELIVERY_SHIFT") and 0 <= e.known_at < n:
            up = getattr(e.dir, "name", str(e.dir)).upper() in ("UP", "U")
            if e.type == "BREACH_REVERT":
                (out["BREACH_REVERT_OLD"] if up else out["BREACH_REVERT"])[e.known_at] = True
            elif up:
                out[e.type][e.known_at] = True
            elif e.type == "DELIVERY_SHIFT":
                out["DELIVERY_SHIFT_DOWN"][e.known_at] = True
    _memo.clear()
    _memo[key] = (df, out)
    return out


TT.ups = ups_both
TZ.ups = ups_both


def fixed_walk(df, side, cost_atr, src, sym, iv):
    """`turn_trade.trades` with the cost in ATR units at the bar (the walk's cost; the frozen code charged
    0.07% of the walk's own price, the cost-scaling bug turning-points.md notes)."""
    from mcfl import candles
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    n = len(df)
    atr = np.asarray(candles.table(df)["atr"], float)
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    U = TT.ups(df)
    H = max(1, int(5 * 86400 / TT.SEC[iv]))
    rows = []
    for t in np.flatnonzero(low3 <= prior):
        if t + 1 >= n or not atr[t] > 0:
            continue
        fired = {k: any(U[p][t] for p in v) for k, v in TT.SIGNALS.items()}
        entry, stop = o[t + 1], low3[t] - 0.1 * atr[t]
        risk = entry - stop
        if not risk > 0:
            continue
        cost = cost_atr[t] * atr[t]
        res = {}
        for k in TT.TARGETS:
            tgt, R = entry + k * risk, None
            for j in range(t + 1, min(n, t + 1 + H)):
                if l[j] <= stop:
                    R = -1.0
                    break
                if h[j] >= tgt:
                    R = float(k)
                    break
            if R is None:
                R = (c[min(n - 1, t + H)] - entry) / risk
            res[f"R{k}"] = R - cost / risk
        rows.append(dict(src=src, sym=sym, iv=iv, side=side, t=t, ts=int(ts[t]), risk_atr=risk / atr[t], **fired, **res))
    return rows


# ------------------------------------------------------------------ data

def klass(venue, sym):
    if venue in ("binance", "fresh", "setc"):
        return "crypto perp"
    import run as R
    f = R.FAMILY.get(sym, "other")
    if f == "deriv":
        return "deriv range break" if sym.startswith("Range Break") else \
            "deriv jumpy" if sym.startswith(("Boom", "Crash", "Jump")) else "deriv diffusive"
    return {"crypto": "crypto CFD"}.get(f, f)


def load(venue, sym, iv):
    """The series and each bar's cost in price."""
    if venue in ("fresh", "setc"):
        path = CACHE / f"{sym}USDT.{iv}.npz"
        if not path.exists():
            return None, None
        z = np.load(path)
        df = pd.DataFrame({k: z[k] for k in ("ts", "open", "high", "low", "close", "volume")}).reset_index(drop=True)
        return df, TT.FEE * df["close"].to_numpy(float)
    if venue == "binance":
        try:
            df = TT._bin(sym, iv)
        except OSError:
            return None, None
        return df, TT.FEE * df["close"].to_numpy(float)
    return TZ.load("mt5", sym, iv)


def one(job):
    from mcfl import candles, synth
    from mcfl.parse import flip
    venue, sym, iv, source = job
    part = OUT / "parts" / f"{venue}_{sym.replace(' ', '_')}_{iv}_{source}.pkl.gz"
    if part.exists():
        return str(part)
    df, fee_px = load(venue, sym, iv)
    if df is None or len(df) < 300:
        return None
    a_c = np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
    cost_c = fee_px / a_c  # the trade studies' cost in ATR (candles' ATR)
    cost_c = np.where(np.isfinite(cost_c), cost_c, np.nanmedian(cost_c))
    cost_z = fee_px / np.maximum(TZ.atr(df), 1e-12)  # the zone study's
    cost_z = np.where(np.isfinite(cost_z), cost_z, np.nanmedian(cost_z))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=TT.WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        df["volume"] = 0.0
        cost_c, cost_z = cost_c[:len(df)], cost_z[:len(df)]
    src = f"{venue}:{source}"
    F, X, Z, L = [], [], [], []
    for side, frame in ((1, df), (-1, flip(df))):
        U = ups_both(frame)
        if source == "real" and venue in ("binance", "fresh", "setc"):
            F += TT.trades(frame, side, TT.FEE, 0.0, src, sym, iv)
        elif source == "real":
            F += TT.trades(frame, side, None, float(fee_px[0]), src, sym, iv)
        else:
            F += fixed_walk(frame, side, cost_c, src, sym, iv)
        X += TT.trades_exits(frame, side, cost_c, src, sym, iv)
        z = TZ.zones(frame, side, cost_z, src, sym, iv)
        for r in z:
            t = r["t"]
            r["T1"], r["T2"] = bool(U["DISPLACE_C"][t]), bool(U["BREACH_REVERT"][t])
            r["T2_old"] = bool(U["BREACH_REVERT_OLD"][t])
            r["SIG_old"] = bool(U["DISPLACE_C"][t] or U["BREACH_REVERT_OLD"][t] or U["DELIVERY_SHIFT"][t])
        Z += z
        for r in DT.lows(frame):
            r["T2_old"] = bool(U["BREACH_REVERT_OLD"][r["t"]])
            r["side"] = side
            L.append(r)
    k = klass(venue, sym)
    out = {name: pd.DataFrame(rows).assign(cls=k, venue=venue) for name, rows in
           (("fixed", F), ("exits", X), ("zones", Z), ("lows", L))}
    out["lows"] = out["lows"].assign(src=src, sym=sym, iv=iv)
    part.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, part)
    print(f"  {src} {sym} {iv}: {len(F)} lows traded, {len(Z)} zone returns", flush=True)
    return str(part)


def jobs_main():
    import run as R
    deriv = [s for s, f in R.FAMILY.items() if f == "deriv"]
    J = [("binance", c, iv, s) for c in TT.COINS for iv in IVS for s in SOURCES]
    J += [("mt5", m, iv, s) for m in TT.MT5 for iv in IVS for s in SOURCES]
    J += [("deriv", d, iv, s) for d in deriv for iv in IVS for s in SOURCES]
    # the heavy 15m jobs first, so the pool ends on small ones
    return sorted(J, key=lambda j: (j[2] != "15m", j[2] != "1h"))


def run_jobs(jobs):
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8)), max_tasks_per_child=4) as pool:
        for _ in pool.map(one, jobs):
            pass


def gather(venues=None):
    parts = sorted((OUT / "parts").glob("*.pkl.gz"))
    acc = {k: [] for k in ("fixed", "exits", "zones", "lows")}
    for p in parts:
        if venues and not p.name.startswith(tuple(f"{v}_" for v in venues)):
            continue
        d = pd.read_pickle(p)
        for k in acc:
            if len(d[k]):
                acc[k].append(d[k])
    out = {k: pd.concat(v, ignore_index=True) for k, v in acc.items() if v}
    for k, d in out.items():
        d["source"] = d["src"].str.split(":").str[1]
    if "zones" in out:
        z = out["zones"]
        z["ALL"] = True
        z["SIG_RZ"] = z["SIG"] & z["RZ"]
        z["SIG_RZ_old"] = z["SIG_old"] & z["RZ"]
    if "lows" in out:
        lo = out["lows"]
        lo["T_any"] = lo["T1"] | lo["T2"] | lo["T3"]
        lo["T_any_old"] = lo["T1"] | lo["T2_old"] | lo["T3"]
    return out


# ------------------------------------------------------------------ statistics

def day_boot(ts, R, rng, draws=2000):
    """Day-bootstrap draws of the mean of R."""
    day = np.asarray(ts) // 86400
    s = pd.DataFrame({"d": day, "R": R}).groupby("d")["R"].agg(["sum", "count"])
    su, co = s["sum"].to_numpy(), s["count"].to_numpy()
    idx = rng.integers(0, len(s), (draws, len(s)))
    return su[idx].sum(1) / co[idx].sum(1)


def zprop(k1, n1, k0, n0):
    """One-sided p that proportion 1 exceeds proportion 0."""
    from scipy.stats import norm
    if n1 == 0 or n0 == 0:
        return np.nan
    p = (k1 + k0) / (n1 + n0)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    return float(norm.sf((k1 / n1 - k0 / n0) / se)) if se > 0 else np.nan


def cell_stats(x, rcol, mcol, rng, boot=True):
    R = x[rcol].to_numpy(float)
    r = dict(n=len(x), R=R.mean() if len(R) else np.nan,
             R_before=x.loc[x["ts"] < TT.SPLIT, rcol].mean(), R_after=x.loc[x["ts"] >= TT.SPLIT, rcol].mean(),
             win=(R > 0).mean() if len(R) else np.nan)
    if mcol is not None:
        r.update({f"P{N}R": (x[mcol] >= N).mean() if len(x) else np.nan for N in NS})
        r.update({f"k{N}R": int((x[mcol] >= N).sum()) for N in (4, 10)})
    r["lo"] = r["hi"] = np.nan
    r["_boot"] = None
    if boot and len(x) > 30:
        b = day_boot(x["ts"].to_numpy(), R, rng)
        r["lo"], r["hi"] = np.quantile(b, [0.05, 0.95])
        r["_boot"] = b
    return r


TRADE_TESTS = (  # (table, exit column, mfe column, signals)
    ("fixed", "R2", None), ("fixed", "R1", None), ("fixed", "R3", None),
    ("exits", "E1", "E1_mfe"), ("exits", "E2", "E2_mfe"))


def summarise(D, scopes, rng, tag):
    """Every cell: per scope (a name and a row filter), test, signal/family, source."""
    rows = []
    for scope, filt in scopes:
        for tab, ex, mfe in TRADE_TESTS:
            if tab not in D:
                continue
            d = D[tab][filt(D[tab])]
            if not len(d):
                continue
            for sig in ("all", *SIGS):
                for source, g in d.groupby("source"):
                    x = g if sig == "all" else g[g[sig]]
                    st = cell_stats(x, ex, mfe, rng, boot=source == "real")
                    rows.append(dict(scope=scope, test=f"{'turn' if tab == 'fixed' else 'turn'} {ex}", family=sig,
                                     act="", source=source, **st))
        if "zones" in D:
            d = D["zones"][filt(D["zones"])]
            for act in ("proven", "left"):
                da = d[d["act"] == act]
                for fam in ("ALL", "SIG", "SIG_old", "SIG_RZ", "SIG_RZ_old", "RZ"):
                    for ex in ("E1", "X2"):
                        for source, g in da.groupby("source"):
                            x = g[g[fam]]
                            st = cell_stats(x, ex, "mfe", rng, boot=source == "real")
                            rows.append(dict(scope=scope, test=f"zone {ex}", family=fam, act=act, source=source, **st))
    t = pd.DataFrame(rows)
    # wide: real with its walks beside it
    key = ["scope", "test", "family", "act"]
    real = t[t["source"] == "real"].set_index(key)
    for s in ("walk", "garch"):
        w = t[t["source"] == s].set_index(key)
        real[f"R_{s}"] = w["R"]
        for N in NS:
            real[f"P{N}R_{s}"] = w.get(f"P{N}R")
        for N in (4, 10):
            real[f"k{N}R_{s}"] = w.get(f"k{N}R")
        real[f"n_{s}"] = w["n"]
    real = real.reset_index()
    # p-values: mean above the better walk; tails above the pooled walks
    p_mean, p4, p10 = [], [], []
    for _, r in real.iterrows():
        b = r["_boot"]
        wbest = np.nanmax([r["R_walk"], r["R_garch"]])
        p_mean.append(float((b <= wbest).mean()) if b is not None and np.isfinite(wbest) else np.nan)
        for N, acc in ((4, p4), (10, p10)):
            if pd.isna(r.get(f"k{N}R")) or pd.isna(r.get("P4R")):
                acc.append(np.nan)
                continue
            k0 = np.nansum([r[f"k{N}R_walk"], r[f"k{N}R_garch"]])
            n0 = np.nansum([r["n_walk"], r["n_garch"]])
            acc.append(zprop(r[f"k{N}R"], r["n"], k0, n0))
    real["p_mean"], real["p_4R"], real["p_10R"] = p_mean, p4, p10
    real = real.drop(columns=["_boot"])
    real.to_csv(OUT / f"cells_{tag}.csv", index=False)
    return real


def bh(p, q=0.10):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    ps = p[ok]
    if not len(ps):
        return out
    order = np.argsort(ps)
    m = len(ps)
    thr = q * np.arange(1, m + 1) / m
    passed = ps[order] <= thr
    k = np.max(np.flatnonzero(passed)) + 1 if passed.any() else 0
    sel = np.zeros(m, bool)
    sel[order[:k]] = True
    out[np.flatnonzero(ok)] = sel
    return out


def summary():
    D = gather()
    rng = np.random.default_rng(71)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_columns", 60)

    # 0. how often each side of T2 fires at a 12-bar low
    lo = D["lows"]
    fire = lo.groupby(["cls", "iv", "source"])[["T2", "T2_old", "T1", "T_any", "T_any_old"]].mean().round(4)
    fire["n_lows"] = lo.groupby(["cls", "iv", "source"]).size()
    fire.to_csv(OUT / "fire_rates.csv")
    print("fire rate at a 12-bar low:\n", fire.to_string())
    # the signature's lift of P(major turn), real vs walks
    rows = []
    for (c, iv, s), g in lo.groupby(["cls", "iv", "source"]):
        base = g["major"].mean()
        for f in ("T1", "T2", "T2_old", "T3", "T_any", "T_any_old"):
            x = g[g[f]]
            rows.append(dict(cls=c, iv=iv, source=s, feature=f, n=len(x), lift=x["major"].mean() / base if base else np.nan))
    lift = pd.DataFrame(rows)
    lift.to_csv(OUT / "lift.csv", index=False)
    print(lift.pivot_table(index=["cls", "feature"], columns=["iv", "source"], values="lift").round(2).to_string())

    # 1. the frozen primaries, corrected and old side
    prim = []
    B12 = lambda d: (d["venue"] == "binance") & d["iv"].isin(["1h", "4h"])  # noqa: E731
    B12z = lambda d: (d["venue"] == "binance") & d["iv"].isin(["1h", "4h", "1d"])  # noqa: E731
    cp = summarise(D, [("binance 1h+4h", B12)], rng, "primary_trades")
    cz = summarise({"zones": D["zones"]}, [("binance 1h+4h+1d", B12z)], rng, "primary_zones")
    for name, t, test, fam, base, act in (
            ("P1 T_any 2R (turn_rule.json)", cp, "turn R2", "T_any", "all", ""),
            ("P1 old side", cp, "turn R2", "T_any_old", "all", ""),
            ("P2 T_any E1 (turn_rule2.json)", cp, "turn E1", "T_any", "all", ""),
            ("P2 old side", cp, "turn E1", "T_any_old", "all", ""),
            ("P3 SIG proven E1 (turn_zone_rule.json)", cz, "zone E1", "SIG", "ALL", "proven"),
            ("P3 old side", cz, "zone E1", "SIG_old", "ALL", "proven")):
        r = t[(t["test"] == test) & (t["family"] == fam) & (t["act"] == act)].iloc[0]
        a = t[(t["test"] == test) & (t["family"] == base) & (t["act"] == act)].iloc[0]
        ok = (r["R"] > 0 and r["lo"] > 0 and r["R_before"] > 0 and r["R_after"] > 0 and r["R"] > a["R"]
              and r["R"] > r["R_walk"] and r["R"] > r["R_garch"])
        prim.append(dict(primary=name, n=r["n"], R=r["R"], lo=r["lo"], hi=r["hi"], before=r["R_before"],
                         after=r["R_after"], every_low=a["R"], walk=r["R_walk"], garch=r["R_garch"],
                         P1R=r["P1R"] if "P1R" in r and pd.notna(r.get("P1R")) else np.nan,
                         P4R=r.get("P4R"), P10R=r.get("P10R"), P4R_walk=r.get("P4R_walk"), P10R_walk=r.get("P10R_walk"),
                         verdict="PASSES" if ok else "fails"))
    prim = pd.DataFrame(prim).round(3)
    prim.to_csv(OUT / "primaries.csv", index=False)
    print("\nPRIMARIES:\n", prim.to_string(index=False))

    # 2. every class x timeframe cell, and BH over the corrected ones
    scopes = []
    for c in sorted(D["exits"]["cls"].unique()):
        for iv in IVS:
            scopes.append((f"{c} | {iv}", lambda d, c=c, iv=iv: (d["cls"] == c) & (d["iv"] == iv)))
        scopes.append((f"{c} | all tf", lambda d, c=c: d["cls"] == c))
    cells = summarise(D, scopes, rng, "grid")
    corr = cells["family"].isin(["T2", "T_any", "SIG", "SIG_RZ"]) & (cells["n"] >= 30) & ~cells["scope"].str.endswith("all tf")
    cells["bh_mean"] = False
    cells["bh_4R"] = False
    cells["bh_10R"] = False
    P = pd.concat([cells.loc[corr, "p_mean"], cells.loc[corr, "p_4R"], cells.loc[corr, "p_10R"]], ignore_index=True)
    sel = bh(P.to_numpy())
    m = corr.sum()
    cells.loc[corr, "bh_mean"] = sel[:m]
    cells.loc[corr, "bh_4R"] = sel[m:2 * m]
    cells.loc[corr, "bh_10R"] = sel[2 * m:]
    cells["n_bh_tests"] = len(P.dropna())
    cells.round(4).to_csv(OUT / "cells_grid.csv", index=False)
    show = ["scope", "test", "family", "act", "n", "R", "lo", "hi", "R_before", "R_after", "R_walk", "R_garch",
            "P4R", "P4R_walk", "P10R", "P10R_walk", "p_mean", "p_4R", "p_10R", "bh_mean", "bh_4R", "bh_10R"]
    print(f"\nBH over {len(P.dropna())} p-values; survivors:")
    surv = cells[cells["bh_mean"] | cells["bh_4R"] | cells["bh_10R"]]
    print(surv[show].round(3).to_string(index=False))
    # confirmation candidates (the frozen trigger)
    base = cells[cells["family"].isin(["all", "ALL"])].set_index(["scope", "test", "act"])["R"]
    cand = []
    for _, r in surv.iterrows():
        b = base.get((r["scope"], r["test"], r["act"]), np.nan)
        mean_ok = bool(r["bh_mean"] and r["R"] > 0 and r["lo"] > 0 and r["R_before"] > 0 and r["R_after"] > 0 and r["R"] > b)
        if mean_ok or r["bh_4R"] or r["bh_10R"]:
            cand.append(dict(r[["scope", "test", "family", "act", "n", "R", "lo", "P4R", "P10R"]], mean_ok=mean_ok,
                             tail4=bool(r["bh_4R"]), tail10=bool(r["bh_10R"]), every_low=b))
    cand = pd.DataFrame(cand)
    cand.to_csv(OUT / "candidates.csv", index=False)
    print("\nconfirmation candidates:\n", cand.to_string(index=False) if len(cand) else "none")


# ------------------------------------------------------------------ confirmation on unseen coins

def confirm():
    """The candidates of `summary()` (CELLS: a JSON list of {iv, test, family, act}) on the 58 fresh coins
    and SET_C, with walks, judged by turn_retrade_rule.json's confirmation rule."""
    import turn_confirm as TC
    cells = json.loads(os.environ["CELLS"])
    fresh = tuple(c for c in TC.SET_A + TC.SET_B if c not in TT.COINS)
    ivs = sorted({c["iv"] for c in cells})
    J = [(v, c, iv, s) for v, coins in (("fresh", fresh), ("setc", TC.SET_C)) for c in coins for iv in ivs for s in SOURCES]
    run_jobs(J)
    D = gather(("fresh", "setc"))
    rng = np.random.default_rng(81)
    rows = []
    for venue in ("fresh", "setc"):
        for c in cells:
            ivl = c["iv"].split("+")
            scope = (f"{venue} {c['iv']}", lambda d, venue=venue, ivl=ivl: (d["venue"] == venue) & d["iv"].isin(ivl))
            t = summarise(D, [scope], rng, f"confirm_{venue}_{c['iv']}")
            r = t[(t["test"] == c["test"]) & (t["family"] == c["family"]) & (t["act"] == c.get("act", ""))].iloc[0]
            a = t[(t["test"] == c["test"]) & (t["family"].isin(["all", "ALL"])) & (t["act"] == c.get("act", ""))].iloc[0]
            mean_ok = (r["R"] > 0 and r["lo"] > 0 and r["R_before"] > 0 and r["R_after"] > 0 and r["R"] > a["R"]
                       and r["R"] > r["R_walk"] and r["R"] > r["R_garch"])
            tail = {}
            for N in (4, 10):
                if pd.notna(r.get(f"P{N}R")):
                    tail[N] = bool(r[f"P{N}R"] > max(r[f"P{N}R_walk"], r[f"P{N}R_garch"], 1 / (N + 1)) and r[f"p_{N}R"] < 0.05)
            rows.append(dict(set=venue, **c, n=r["n"], R=r["R"], lo=r["lo"], hi=r["hi"], before=r["R_before"],
                             after=r["R_after"], every_low=a["R"], walk=r["R_walk"], garch=r["R_garch"],
                             P4R=r.get("P4R"), P4R_walk=r.get("P4R_walk"), P10R=r.get("P10R"), P10R_walk=r.get("P10R_walk"),
                             p_4R=r.get("p_4R"), p_10R=r.get("p_10R"), mean_pass=mean_ok, tail4_pass=tail.get(4),
                             tail10_pass=tail.get(10)))
    t = pd.DataFrame(rows).round(4)
    t.to_csv(OUT / "confirm.csv", index=False)
    pd.set_option("display.width", 300)
    print(t.to_string(index=False))


# ------------------------------------------------------------------ plots

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    img = OUT / "img"
    img.mkdir(exist_ok=True)
    g = pd.read_csv(OUT / "cells_grid.csv")
    fire = pd.read_csv(OUT / "fire_rates.csv")
    C = {"real": "#1d3557", "walk": "#a8dadc", "garch": "#e9c46a", "old": "#e76f51", "rw": "#999999"}
    classes = [c for c in ("crypto perp", "fx", "metal", "index", "energy", "crypto CFD", "deriv diffusive",
                           "deriv jumpy", "deriv range break") if (fire["cls"] == c).any()]

    # 1. fire rates: T2 old vs corrected
    fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    for ax, src in zip(axes, ("real", "walk"), strict=True):
        f = fire[fire["source"] == src]
        x = np.arange(len(classes))
        for k, iv in enumerate(IVS):
            v = f[f["iv"] == iv].set_index("cls").reindex(classes)
            ax.bar(x + (k - 1.5) * 0.2, v["T2"], 0.2, color=plt.cm.Blues(0.4 + 0.15 * k), label=f"T2 corrected {iv}")
            ax.bar(x + (k - 1.5) * 0.2, v["T2_old"], 0.2, color=plt.cm.Reds(0.4 + 0.15 * k), alpha=0.9,
                   label=f"T2 old {iv}")
        ax.set_xticks(x, classes, rotation=25, fontsize=8)
        ax.set_ylabel("share of 12-bar lows where T2 fires")
        ax.set_title(f"{src}: corrected (blue) vs old (red) T2 fire rate", fontsize=10)
        ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(img / "fire_rates.png", dpi=80)
    plt.close(fig)

    # 2. P(N R) curves: T_any E1 and T2 E1 per class (all timeframes pooled), corrected vs old vs walks
    def curves(test, fams, act, fname, title):
        fig, axes = plt.subplots(len(fams), len(classes), figsize=(3.2 * len(classes), 3.4 * len(fams)), sharey=True,
                                 squeeze=False)
        for i, (fam, old) in enumerate(fams):
            for j, c in enumerate(classes):
                ax = axes[i, j]
                r = g[(g["scope"] == f"{c} | all tf") & (g["test"] == test) & (g["family"] == fam) & (g["act"].fillna("") == act)]
                o = g[(g["scope"] == f"{c} | all tf") & (g["test"] == test) & (g["family"] == old) & (g["act"].fillna("") == act)]
                if len(r):
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}R"] for N in NS], "-o", color=C["real"], label=f"real {r['R']:+.3f} (n {int(r['n'])})")
                    ax.plot(NS, [r[f"P{N}R_walk"] for N in NS], "--s", color=C["walk"], label=f"iid {r['R_walk']:+.3f}")
                    ax.plot(NS, [r[f"P{N}R_garch"] for N in NS], ":^", color=C["garch"], label=f"GARCH {r['R_garch']:+.3f}")
                if len(o):
                    o = o.iloc[0]
                    ax.plot(NS, [o[f"P{N}R"] for N in NS], "-x", color=C["old"], lw=0.8, label=f"old side {o['R']:+.3f} (n {int(o['n'])})")
                ax.plot(NS, [1 / (N + 1) for N in NS], color=C["rw"], lw=0.8, label="1/(N+1)")
                ax.set_xscale("log")
                ax.set_yscale("log")
                ax.set_title(f"{c}: {fam}", fontsize=9)
                ax.legend(fontsize=6)
                ax.set_xlabel("N (R)", fontsize=8)
        axes[0, 0].set_ylabel("P(trade reaches N R)")
        fig.suptitle(title, fontsize=11)
        fig.tight_layout()
        fig.savefig(img / fname, dpi=80)
        plt.close(fig)

    curves("turn E1", (("T2", "T2_old"), ("T_any", "T_any_old")), "", "pnr_turn_e1.png",
           "turn trade, E1 trail, 15m-1d pooled: P(N R) real vs iid and GARCH walks; old side in red; mean R in the legend")
    curves("turn E2", (("T2", "T2_old"), ("T_any", "T_any_old")), "", "pnr_turn_e2.png",
           "turn trade, E2 opposite CISD, 15m-1d pooled: P(N R) real vs walks; old side in red")
    curves("zone E1", (("SIG", "SIG_old"),), "proven", "pnr_zones.png",
           "turn-origin zones SIG, proven, E1 trail, 1h-1d and 15m pooled: P(N R) real vs walks; old side in red")

    # 3. mean R per class x timeframe: corrected vs old vs walk, for the frozen exits
    for test, fam, old, act, fname in (("turn E1", "T_any", "T_any_old", "", "r_grid_tany_e1.png"),
                                       ("turn E1", "T2", "T2_old", "", "r_grid_t2_e1.png"),
                                       ("turn R2", "T_any", "T_any_old", "", "r_grid_tany_2r.png"),
                                       ("zone E1", "SIG", "SIG_old", "proven", "r_grid_sig_zone.png")):
        fig, axes = plt.subplots(1, len(IVS), figsize=(22, 5.5), sharey=True)
        for ax, iv in zip(axes, IVS, strict=True):
            x = np.arange(len(classes))
            sub = g[(g["test"] == test) & (g["act"].fillna("") == act)]
            cor = sub[sub["family"] == fam].set_index("scope").reindex([f"{c} | {iv}" for c in classes])
            od = sub[sub["family"] == old].set_index("scope").reindex([f"{c} | {iv}" for c in classes])
            ax.bar(x - 0.3, cor["R"], 0.2, color=C["real"], label="corrected, real")
            ax.errorbar(x - 0.3, cor["R"], yerr=[cor["R"] - cor["lo"], cor["hi"] - cor["R"]], fmt="none", ecolor="k", lw=0.8)
            ax.bar(x - 0.1, od["R"], 0.2, color=C["old"], label="old side, real")
            ax.bar(x + 0.1, cor["R_walk"], 0.2, color=C["walk"], label="corrected, iid walk")
            ax.bar(x + 0.3, cor["R_garch"], 0.2, color=C["garch"], label="corrected, GARCH walk")
            ax.axhline(0, color="grey", lw=0.8)
            ax.set_xticks(x, classes, rotation=30, fontsize=8)
            ax.set_title(f"{iv}", fontsize=10)
        axes[0].set_ylabel("mean R a trade (90% day-bootstrap interval)")
        axes[0].legend(fontsize=8)
        fig.suptitle(f"{test} {fam}{' ' + act if act else ''}: corrected vs old side vs walks, per class and timeframe")
        fig.tight_layout()
        fig.savefig(img / fname, dpi=80)
        plt.close(fig)

    # 4. lift of P(major turn): T2 corrected vs old, real vs walk
    lift = pd.read_csv(OUT / "lift.csv")
    fig, ax = plt.subplots(figsize=(16, 5.5))
    x = np.arange(len(classes))
    for k, (f, s, col) in enumerate((("T2", "real", C["real"]), ("T2", "walk", C["walk"]), ("T2", "garch", C["garch"]),
                                     ("T2_old", "real", C["old"]), ("T1", "real", "#2a9d8f"))):
        v = lift[(lift["feature"] == f) & (lift["source"] == s)].groupby("cls")["lift"].mean().reindex(classes)
        ax.bar(x + (k - 2) * 0.16, v, 0.16, color=col, label=f"{f} {s}")
    ax.axhline(1, color="grey", lw=0.8)
    ax.set_xticks(x, classes, rotation=20, fontsize=9)
    ax.set_ylabel("lift of P(major turn) over any 12-bar low (mean over timeframes)")
    ax.legend(fontsize=8)
    ax.set_title("the signature: corrected T2 marks major turns, as on its walks; the old side marked fewer")
    fig.tight_layout()
    fig.savefig(img / "lift.png", dpi=80)
    plt.close(fig)
    gallery(img)
    print("plots written", flush=True)


def gallery(img):
    """Six corrected T2 trades on Binance 4h, to show the side: the swept swing low and the close back above."""
    import matplotlib.pyplot as plt
    from mcfl.parse import flip
    parts = sorted((OUT / "parts").glob("binance_*_4h_real.pkl.gz"))
    d = pd.concat([pd.read_pickle(p)["exits"] for p in parts], ignore_index=True)
    d = d[d["T2"]]
    rng = np.random.default_rng(9)
    pick = d.iloc[rng.choice(len(d), min(6, len(d)), replace=False)]
    fig, axes = plt.subplots(2, 3, figsize=(21, 10))
    for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
        df = TT._bin(r.sym, r.iv)
        s = r.side
        frame = df if s > 0 else flip(df)
        from mcfl import candles
        a = np.asarray(candles.table(frame)["atr"], float)
        t = int(r.t)
        i0, i1 = max(0, t - 30), min(len(df) - 1, t + 30)
        w = df.iloc[i0:i1 + 1]
        x = np.arange(i0, i1 + 1)
        up = (w["close"] >= w["open"]).to_numpy()
        ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
        ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
        ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
        low3 = frame["low"].iloc[t - 2:t + 1].min()
        entry = frame["open"].iat[t + 1]
        stop = low3 - 0.1 * a[t]
        ax.hlines(s * stop, t + 1, i1, colors="red", lw=1)
        ax.hlines(s * entry, t + 1, i1, colors="k", lw=1)
        ax.axvline(t, color="purple", lw=1, ls=":")
        ax.set_title(f"{r.sym}USDT 4h {'long' if s > 0 else 'short'}  T2 corrected -> E1 {r.E1:+.2f}R, E2 {r.E2:+.2f}R  "
                     f"{pd.Timestamp(r.ts, unit='s'):%Y-%m-%d %H:%M}", fontsize=9)
    fig.suptitle("corrected T2 (BREACH_REVERT through a swing low, closed back above; mirrored for shorts) at a 12-bar low: "
                 "purple - the signal bar; black - entry at the next open; red - the stop", fontsize=11)
    fig.tight_layout()
    fig.savefig(img / "t2_gallery.png", dpi=80)
    plt.close(fig)


def main():
    mode = os.environ.get("MODE", "run")
    if mode == "run":
        J = jobs_main()
        only = os.environ.get("ONLY")
        if only:
            J = [j for j in J if f"{j[0]}:{j[1]}:{j[2]}:{j[3]}" in only.split(",")]
        run_jobs(J)
    else:
        {"summary": summary, "plot": plot, "confirm": confirm}[mode]()


if __name__ == "__main__":
    main()
