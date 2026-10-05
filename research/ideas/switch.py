"""When to pause or resume a strategy: the frozen rules of `switch_rule.json`, measured.

For `research/docs/strategy-switching.md`. Streams: production's level strategies replayed through
production's code (`switch_replay.py`, PROD) and the LRC research rules (`switch_lrc.py`, LRC), each on
real data and on matched iid and GARCH walks. Modes:

  nec     the necessary condition: is a strategy's next R predictable from its own record?
  rules   every pause/resume rule on every stream: timing value against a random-pause twin,
          value over always-on, portfolio Sharpe, P(N R)
  hedge   exponential weights across strategies, with a cash arm
  kill    closes needed to call a strategy dead or alive; hot streaks on zero-edge streams
  live    the same rules on the live closes export (run locally: CLOSES=.data/closes.json; a journal
          .db, or several sources comma-separated, are read too - see read_closes)
  plot    figures

Every rule's state is a function of the shadow record only (every outcome is observed whether the
strategy traded or not), so it is computed once per stream, after each close in exit order, and each
trade reads the state left by the closes known at its entry.

  OUT=... PROD=... LRC=... MODE=... python research/ideas/switch.py
"""
from __future__ import annotations

import json
import math
import os
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("OUT", ".data/switch"))
PROD = Path(os.environ.get("PROD", ".data/switch_replay/prod_trades.pkl.gz"))
LRC = Path(os.environ.get("LRC", ".data/switch_lrc/lrc_streams.pkl.gz"))
RULE = json.loads((HERE / "switch_rule.json").read_text())
SPLIT = pd.Timestamp("2024-01-01", tz="UTC").timestamp()
CLASSES = ("FX", "METAL", "INDEX", "ENERGY", "CRYPTO_CFD", "BINANCE", "FRESH", "DERIV_1S", "DERIV_DIFFUSIVE",
           "DERIV_JUMPY")
SOURCES = ("real", "walk", "garch")
SEQ_RULES = ("EQ20", "EQ50", "DD", "CUSUM", "PH", "SPRT", "BAYES_ALL", "BAYES_100")
REG_RULES = ("REGIME_VOL", "REGIME_TREND")
RULES = SEQ_RULES + REG_RULES
NS = (0.5, 1, 2, 4, 10)
DRAWS = 1000
SHIFTS = 200
WORKERS = int(os.environ.get("WORKERS", 48))


# ----------------------------------------------------------------------------------------------- streams

def load():
    """One table: fam, strat, cls, iv, src, sym, ts, exit_ts, R, mfe, vol_ratio, seff."""
    out = []
    if PROD.exists():
        p = pd.read_pickle(PROD)  # our own replay output
        p = p.rename(columns={"variant": "strat"})
        p["fam"], p["iv"] = "PROD", "15-30m"
        out.append(p)
    if LRC.exists():
        q = pd.read_pickle(LRC)  # our own lab output
        q = q.rename(columns={"rule": "strat", "X2": "R"})
        q["fam"] = "LRC"
        out.append(q[q["iv"].isin(("15m", "1h", "4h", "1d"))])  # the frozen timeframes (the source also has 30m)
    t = pd.concat(out, ignore_index=True)
    t["seff"] = t["eff"] * t["trend_with"]
    keep = ["fam", "strat", "cls", "iv", "src", "sym", "ts", "exit_ts", "R", "mfe", "vol_ratio", "seff"]
    t = t[keep]
    t = t[np.isfinite(t["R"]) & t["cls"].notna() & (t["cls"] != "KNOWN_BAD")]
    t["exit_ts"] = np.maximum(t["exit_ts"].to_numpy(np.int64), t["ts"].to_numpy(np.int64))
    return t.reset_index(drop=True)


def streams(t):
    """(scope, fam, strat, cls, iv, src) -> frame sorted by entry. CELL for every cell; BOOK per PROD
    strategy across its book without Range Break."""
    for (fam, strat, cls, iv, src), g in t.groupby(["fam", "strat", "cls", "iv", "src"], sort=False):
        yield ("CELL", fam, strat, cls, iv, src), g
    pb = t[(t["fam"] == "PROD") & (t["cls"] != "RANGE_BREAK")]
    for (strat, src), g in pb.groupby(["strat", "src"], sort=False):
        yield ("BOOK", "PROD", strat, "BOOK", "15-30m", src), g


# ------------------------------------------------------------------------------------- rule states

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def states(rx):
    """State after each close (index k = closes so far, 0..n) for every sequential rule. True = on."""
    rx = [float(r) for r in rx]
    n = len(rx)
    out = {}
    E = np.r_[0.0, np.cumsum(rx)]
    for N in (20, 50):
        cs = np.r_[0.0, np.cumsum(E)]
        st = np.ones(n + 1, bool)
        k = np.arange(N, n + 1)
        ma = (cs[k + 1] - cs[k + 1 - N]) / N
        st[N:] = E[N:] > ma
        out[f"EQ{N}"] = st
    p = RULE  # parameters are written out below as frozen; this is a reminder they are not tuned
    del p
    # DD
    s, on, peak, eq, trough = [True], True, 0.0, 0.0, 0.0
    for r in rx:
        eq += r
        if on:
            peak = max(peak, eq)
            if eq <= peak - 8.0:
                on, trough = False, eq
        else:
            trough = min(trough, eq)
            if eq >= trough + 4.0:
                on, peak = True, eq
        s.append(on)
    out["DD"] = np.array(s)
    # CUSUM
    s, on, lo, hi = [True], True, 0.0, 0.0
    for r in rx:
        if on:
            lo = max(0.0, lo + 0.05 - r)
            if lo > 5.0:
                on, lo, hi = False, 0.0, 0.0
        else:
            hi = max(0.0, hi + r - 0.05)
            if hi > 5.0:
                on, lo, hi = True, 0.0, 0.0
        s.append(on)
    out["CUSUM"] = np.array(s)
    # PH (online form: the running mean at each step since the last switch)
    s, on = [True], True
    cnt, tot, m, ext = 0, 0.0, 0.0, 0.0
    for r in rx:
        cnt += 1
        tot += r
        xbar = tot / cnt
        if on:
            m += r - xbar + 0.05
            ext = max(ext, m)
            if ext - m > 5.0:
                on, cnt, tot, m, ext = False, 0, 0.0, 0.0, 0.0
        else:
            m += r - xbar - 0.05
            ext = min(ext, m)
            if m - ext > 5.0:
                on, cnt, tot, m, ext = True, 0, 0.0, 0.0, 0.0
        s.append(on)
    out["PH"] = np.array(s)
    # SPRT, BAYES_ALL, BAYES_100 share a running sd (Welford)
    A, B = math.log(0.8 / 0.05), math.log(0.2 / 0.95)
    s1, s2, s3 = [True], [True], [True]
    on1 = on2 = on3 = True
    llr, k, mean, m2 = 0.0, 0, 0.0, 0.0
    tot, sw, ww = 0.0, 0.0, 0.0
    tau2 = 0.10 ** 2
    for r in rx:
        k += 1
        d = r - mean
        mean += d / k
        m2 += d * (r - mean)
        sd = math.sqrt(m2 / (k - 1)) if k >= 20 else 1.0
        sd = max(sd, 1e-6)
        var = sd * sd
        # SPRT
        llr += 0.10 / var * (r - 0.05)
        if on1:
            if llr <= B:
                on1, llr = False, 0.0
            elif llr >= A:
                llr = 0.0
        else:
            if llr >= A:
                on1, llr = True, 0.0
            elif llr <= B:
                llr = 0.0
        s1.append(on1)
        # BAYES_ALL
        tot += r
        prec = 1.0 / tau2 + k / var
        pr = norm_cdf((tot / var) / prec * math.sqrt(prec))
        on2 = (pr > 0.50) if not on2 else not (pr < 0.20)
        s2.append(on2)
        # BAYES_100
        sw = 0.99 * sw + r
        ww = 0.99 * ww + 1.0
        prec = 1.0 / tau2 + ww / var
        pr = norm_cdf((sw / var) / prec * math.sqrt(prec))
        on3 = (pr > 0.50) if not on3 else not (pr < 0.20)
        s3.append(on3)
    out["SPRT"], out["BAYES_ALL"], out["BAYES_100"] = np.array(s1), np.array(s2), np.array(s3)
    return out


def regime_mask(x, R, disc):
    """REGIME gate: tercile cuts and the traded tercile from discovery; (mask, gated?)."""
    ok = np.isfinite(x)
    d = disc & ok
    if d.sum() < 90:
        return np.ones(len(R), bool), False
    cuts = np.quantile(x[d], [1 / 3, 2 / 3])
    ter = np.digitize(x, cuts)
    means = []
    for k in range(3):
        sel = d & (ter == k)
        if sel.sum() < 30:
            return np.ones(len(R), bool), False
        means.append(R[sel].mean())
    best = int(np.argmax(means))
    return np.where(ok, ter == best, True), True


def twin_mask(m, rng):
    n = len(m)
    if n < 10:
        return np.full(n, m.mean())
    offs = rng.integers(max(1, n // 10), max(2, 9 * n // 10), SHIFTS)
    acc = np.zeros(n)
    for o in offs:
        acc += np.roll(m, int(o))
    return acc / SHIFTS


def day_boot(day, d, rng, draws=DRAWS):
    """Mean of d per opportunity with a day bootstrap: (mean, lo5, hi95, p one-sided <= 0)."""
    if len(d) == 0:
        return (np.nan,) * 4
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=d)
    k = np.bincount(inv).astype(float)
    if len(u) < 10:
        return float(d.mean()), np.nan, np.nan, np.nan
    m = np.empty(draws)
    for i in range(0, draws, 100):
        idx = rng.integers(0, len(u), (min(100, draws - i), len(u)))
        m[i:i + len(idx)] = s[idx].sum(1) / k[idx].sum(1)
    return float(d.mean()), float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95)), float((m <= 0).mean())


# ---------------------------------------------------------------------------------------- per stream

def stream_rules(args):
    key, g = args
    scope, fam, strat, cls, iv, src = key
    g = g.sort_values("ts", kind="stable")
    R = g["R"].to_numpy(float)
    ts = g["ts"].to_numpy(np.int64)
    ex = g["exit_ts"].to_numpy(np.int64)
    n = len(R)
    if n < 30:
        return [], None
    order = np.argsort(ex, kind="stable")
    c = np.searchsorted(ex[order], ts, side="right")
    st = states(R[order])
    masks = {name: s[c] for name, s in st.items()}
    disc = ts < SPLIT
    gated = {}
    for name, col in (("REGIME_VOL", "vol_ratio"), ("REGIME_TREND", "seff")):
        masks[name], gated[name] = regime_mask(g[col].to_numpy(float), R, disc)
    rng = np.random.default_rng(zlib.crc32(repr(key).encode()))
    day = ts // 86400
    mfe = g["mfe"].to_numpy(float)
    rows, days = [], []
    base = dict(scope=scope, fam=fam, strat=strat, cls=cls, iv=iv, src=src)
    for name in RULES:
        m = masks[name].astype(float)
        for half, hm in (("disc", disc), ("conf", ~disc), ("all", np.ones(n, bool))):
            if name in REG_RULES and half != "conf":
                continue
            if hm.sum() < 30:
                continue
            Rh, mh, dh = R[hm], m[hm], day[hm]
            # the twin is drawn within the half, so it has the half's own pause fraction: a rule that
            # pauses more as evidence accumulates must not be credited for pausing late in the stream
            th = np.full(len(mh), mh.mean()) if name in REG_RULES else twin_mask(mh, rng)
            dt = (mh - th) * Rh
            do = (mh - 1.0) * Rh
            tv = day_boot(dh, dt, rng) if scope == "BOOK" or half == "conf" else (dt.mean(), np.nan, np.nan, np.nan)
            ov = (do.mean(),)
            taken = mh > 0.5
            sw = int(np.abs(np.diff(mh)).sum())
            rows.append(dict(base, rule=name, half=half, n=int(hm.sum()), always=float(Rh.mean()),
                             switched=float((mh * Rh).mean()), twin=float((th * Rh).mean()),
                             timing=tv[0], t_lo=tv[1], t_hi=tv[2], t_p=tv[3], over_on=ov[0],
                             paused=float(1 - mh.mean()), switches=sw,
                             taken_R=float(Rh[taken].mean()) if taken.any() else np.nan,
                             gated=gated.get(name, True),
                             **{f"P{N}_on": float((mfe[hm] >= N).mean()) for N in NS},
                             **{f"P{N}_tk": float((mfe[hm][taken] >= N).mean()) if taken.any() else np.nan
                                for N in NS}))
            if half != "all":
                u, inv = np.unique(dh, return_inverse=True)
                days.append(pd.DataFrame(dict(base, rule=name, half=half, day=u,
                                              n=np.bincount(inv).astype(float),
                                              R=np.bincount(inv, weights=Rh),
                                              sw=np.bincount(inv, weights=mh * Rh),
                                              tw=np.bincount(inv, weights=th * Rh))))
    return rows, (pd.concat(days, ignore_index=True) if days else None)


def stream_nec(args):
    """The necessary condition on one stream."""
    key, g = args
    scope, fam, strat, cls, iv, src = key
    g = g.sort_values("ts", kind="stable")
    R = g["R"].to_numpy(float)
    ts = g["ts"].to_numpy(np.int64)
    ex = g["exit_ts"].to_numpy(np.int64)
    n = len(R)
    if n < RULE["necessary_condition_stats"]["minimum_n"]:
        return [], None
    order = np.argsort(ex, kind="stable")
    C = np.r_[0.0, np.cumsum(R[order])]
    c = np.searchsorted(ex[order], ts, side="right")
    disc = ts < SPLIT
    rows, days = [], []
    base = dict(scope=scope, fam=fam, strat=strat, cls=cls, iv=iv, src=src)
    for half, hm in (("disc", disc), ("conf", ~disc), ("all", np.ones(n, bool))):
        if hm.sum() < 100:
            continue
        row = dict(base, half=half, n=int(hm.sum()), meanR=float(R[hm].mean()), sdR=float(R[hm].std()))
        for N in (10, 30, 100):
            ok = hm & (c >= N)
            if ok.sum() < 50:
                row[f"pred_{N}"] = np.nan
                continue
            x = (C[c[ok]] - C[c[ok] - N]) / N
            y = R[ok]
            row[f"pred_{N}"] = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else np.nan
            if N == 30 and half != "all" and x.std() > 0:
                zx, zy = (x - x.mean()) / x.std(), (y - y.mean()) / y.std()
                dd = ts[ok] // 86400
                u, inv = np.unique(dd, return_inverse=True)
                days.append(pd.DataFrame(dict(base, half=half, day=u, n=np.bincount(inv).astype(float),
                                              zz=np.bincount(inv, weights=zx * zy))))
        Rh = R[hm]
        row["ac1"] = float(np.corrcoef(Rh[:-1], Rh[1:])[0, 1]) if Rh.std() > 0 else np.nan
        w = Rh > 0
        n1, n0 = w.sum(), (~w).sum()
        runs = 1 + int((w[1:] != w[:-1]).sum())
        if n1 > 0 and n0 > 0:
            mu = 2 * n1 * n0 / (n1 + n0) + 1
            var = 2 * n1 * n0 * (2 * n1 * n0 - n1 - n0) / ((n1 + n0) ** 2 * (n1 + n0 - 1))
            row["runs_z"] = float((runs - mu) / math.sqrt(var)) if var > 0 else np.nan
        mon = pd.Series(Rh, index=pd.to_datetime(ts[hm], unit="s").to_period("M"))
        gm = mon.groupby(level=0).agg(["mean", "size"])
        gm = gm[gm["size"] >= 10]["mean"]
        row["month_pers"] = float(np.corrcoef(gm.to_numpy()[:-1], gm.to_numpy()[1:])[0, 1]) if len(gm) >= 6 else np.nan
        row["months"] = int(len(gm))
        rows.append(row)
    return rows, (pd.concat(days, ignore_index=True) if days else None)


# ------------------------------------------------------------------------------------------ pooling

def pooled_boot(dd, num, den, rng, draws=DRAWS):
    """A ratio of day sums, bootstrapped over days: (value, lo5, hi95, p<=0, draws array)."""
    g = dd.groupby("day")[[num, den]].sum()
    s, k = g[num].to_numpy(), g[den].to_numpy()
    if len(g) < 10 or k.sum() == 0:
        return np.nan, np.nan, np.nan, np.nan, None
    m = np.empty(draws)
    for i in range(0, draws, 100):
        idx = rng.integers(0, len(g), (min(100, draws - i), len(g)))
        m[i:i + len(idx)] = s[idx].sum(1) / k[idx].sum(1)
    return float(s.sum() / k.sum()), float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95)), float((m <= 0).mean()), m


def bh(p, q=0.10):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if not ok.any():
        return out
    pv = p[ok]
    o = np.argsort(pv)
    m = len(pv)
    thr = q * np.arange(1, m + 1) / m
    passed = pv[o] <= thr
    k = np.flatnonzero(passed).max() + 1 if passed.any() else 0
    sel = np.zeros(m, bool)
    sel[o[:k]] = True
    out[np.flatnonzero(ok)] = sel
    return out


def sharpe(x):
    return float(x.mean() / x.std() * math.sqrt(365)) if len(x) > 2 and x.std() > 0 else np.nan


# --------------------------------------------------------------------------------------------- modes

def run_pool(fn, t):
    rows, days = [], []
    jobs = list(streams(t))
    jobs.sort(key=lambda j: -len(j[1]))
    with ProcessPoolExecutor(WORKERS) as pool:
        for r, d in pool.map(fn, jobs, chunksize=1):
            rows += r
            if d is not None:
                days.append(d)
    return pd.DataFrame(rows), (pd.concat(days, ignore_index=True) if days else pd.DataFrame())


def nec():
    OUT.mkdir(parents=True, exist_ok=True)
    t = load()
    tab, days = run_pool(stream_nec, t)
    tab.to_csv(OUT / "nec_cells.csv", index=False)
    days.to_pickle(OUT / "nec_days.pkl.gz")
    rng = np.random.default_rng(7)
    rows = []
    cell_p = []
    nonrb = days[days["cls"] != "RANGE_BREAK"]
    groups = [("PROD BOOK, all strategies", (days["scope"] == "BOOK")),
              ("LRC, all non-RB cells", (days["scope"] == "CELL") & (days["fam"] == "LRC") & (days["cls"] != "RANGE_BREAK")),
              ("PROD CELL, all non-RB cells", (days["scope"] == "CELL") & (days["fam"] == "PROD") & (days["cls"] != "RANGE_BREAK"))]
    for cls in CLASSES + ("RANGE_BREAK",):
        groups.append((f"PROD {cls}", (days["scope"] == "CELL") & (days["fam"] == "PROD") & (days["cls"] == cls)))
        for iv in ("15m", "1h", "4h", "1d"):
            groups.append((f"LRC {cls} {iv}", (days["scope"] == "CELL") & (days["fam"] == "LRC") & (days["cls"] == cls)
                           & (days["iv"] == iv)))
    for iv in ("15m", "1h", "4h", "1d"):
        groups.append((f"LRC all non-RB {iv}", (days["scope"] == "CELL") & (days["fam"] == "LRC") & (days["iv"] == iv)
                       & (days["cls"] != "RANGE_BREAK")))
    del nonrb
    for name, m in groups:
        for half in ("disc", "conf"):
            res = {}
            for src in SOURCES:
                dd = days[m & (days["half"] == half) & (days["src"] == src)]
                if len(dd) == 0:
                    continue
                res[src] = pooled_boot(dd, "zz", "n", rng)
            if "real" not in res or res["real"][4] is None:
                continue
            row = dict(group=name, half=half)
            for src, v in res.items():
                row.update({f"{src}": v[0], f"{src}_lo": v[1], f"{src}_hi": v[2]})
            for w in ("walk", "garch"):
                if w in res and res[w][4] is not None:
                    diff = res["real"][4] - res[w][4]
                    row[f"real_minus_{w}"] = res["real"][0] - res[w][0]
                    row[f"rm{w}_lo"], row[f"rm{w}_hi"] = float(np.quantile(diff, 0.05)), float(np.quantile(diff, 0.95))
                    row[f"rm{w}_p"] = float((diff <= 0).mean())
            rows.append(row)
    pt = pd.DataFrame(rows)
    pt["p_max"] = pt[["rmwalk_p", "rmgarch_p"]].max(axis=1) if "rmgarch_p" in pt else np.nan
    pt.to_csv(OUT / "nec_pooled.csv", index=False)
    # per cell, real against both walks on confirmation, BH across cells
    for _, r in tab[(tab["src"] == "real") & (tab["half"] == "conf")].iterrows():
        key = (r["scope"], r["fam"], r["strat"], r["cls"], r["iv"])
        sub = days[(days["scope"] == key[0]) & (days["fam"] == key[1]) & (days["strat"] == key[2]) &
                   (days["cls"] == key[3]) & (days["iv"] == key[4]) & (days["half"] == "conf")]
        res = {src: pooled_boot(sub[sub["src"] == src], "zz", "n", rng) for src in SOURCES}
        ps = []
        for w in ("walk", "garch"):
            if res["real"][4] is None or res[w][4] is None:
                ps.append(np.nan)
                continue
            ps.append(float(((res["real"][4] - res[w][4]) <= 0).mean()))
        cell_p.append(dict(zip(("scope", "fam", "strat", "cls", "iv"), key), real=res["real"][0],
                           walk=res["walk"][0], garch=res["garch"][0], p=max(ps) if all(np.isfinite(ps)) else np.nan))
    cp = pd.DataFrame(cell_p)
    if len(cp):
        cp["bh"] = bh(cp["p"].to_numpy())
    cp.to_csv(OUT / "nec_cell_tests.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(pt.round(4).to_string(index=False))
    print("cells tested", len(cp), "BH survivors", int(cp["bh"].sum()) if len(cp) else 0)
    print(cp[cp["bh"]].round(4).to_string(index=False) if len(cp) else "")
    summ = tab[tab["half"] == "conf"].groupby(["scope", "fam", "src"])[["pred_10", "pred_30", "pred_100", "ac1", "runs_z",
                                                                         "month_pers"]].median()
    print(summ.round(4).to_string())


def rules():
    OUT.mkdir(parents=True, exist_ok=True)
    t = load()
    tab, days = run_pool(stream_rules, t)
    tab.to_csv(OUT / "rules_cells.csv", index=False)
    days.to_pickle(OUT / "rules_days.pkl.gz")
    rng = np.random.default_rng(11)
    days["dt"] = days["sw"] - days["tw"]
    days["do"] = days["sw"] - days["R"]
    pools = [("PROD BOOK", (days["scope"] == "BOOK")),
             ("LRC CELL", (days["scope"] == "CELL") & (days["fam"] == "LRC") & (days["cls"] != "RANGE_BREAK")),
             ("PROD CELL", (days["scope"] == "CELL") & (days["fam"] == "PROD") & (days["cls"] != "RANGE_BREAK"))]
    for cls in CLASSES + ("RANGE_BREAK",):
        pools.append((f"PROD {cls}", (days["scope"] == "CELL") & (days["fam"] == "PROD") & (days["cls"] == cls)))
        pools.append((f"LRC {cls}", (days["scope"] == "CELL") & (days["fam"] == "LRC") & (days["cls"] == cls)))
    for iv in ("15m", "1h", "4h", "1d"):
        pools.append((f"LRC {iv}", (days["scope"] == "CELL") & (days["fam"] == "LRC") & (days["iv"] == iv)
                      & (days["cls"] != "RANGE_BREAK")))
    rows = []
    for name, m in pools:
        for rule in RULES:
            for half in ("disc", "conf"):
                if rule in REG_RULES and half == "disc":
                    continue
                res = {}
                for src in SOURCES:
                    dd = days[m & (days["rule"] == rule) & (days["half"] == half) & (days["src"] == src)]
                    if len(dd) == 0:
                        continue
                    agg = dd.groupby("day")[["n", "R", "sw", "tw", "dt", "do"]].sum().reset_index()
                    tv = pooled_boot(agg, "dt", "n", rng)
                    ov = pooled_boot(agg, "do", "n", rng)
                    shp = [sharpe(agg[c].to_numpy()) for c in ("R", "sw", "tw")]
                    res[src] = (tv, ov, shp, float(agg["R"].sum() / agg["n"].sum()), float(agg["n"].sum()),
                                float(agg["sw"].sum() / agg["n"].sum()))
                if "real" not in res:
                    continue
                row = dict(pool=name, rule=rule, half=half)
                for src, (tv, ov, shp, mr, nn, sw) in res.items():
                    row.update({f"{src}_n": nn, f"{src}_always": mr, f"{src}_switched": sw, f"{src}_timing": tv[0],
                                f"{src}_t_lo": tv[1], f"{src}_t_hi": tv[2], f"{src}_t_p": tv[3], f"{src}_over_on": ov[0],
                                f"{src}_o_lo": ov[1], f"{src}_o_hi": ov[2], f"{src}_sh_on": shp[0],
                                f"{src}_sh_sw": shp[1], f"{src}_sh_tw": shp[2]})
                for w in ("walk", "garch"):
                    if w in res and res[w][0][4] is not None and res["real"][0][4] is not None:
                        diff = res["real"][0][4] - res[w][0][4]
                        row[f"rm{w}_lo"], row[f"rm{w}_hi"] = float(np.quantile(diff, 0.05)), float(np.quantile(diff, 0.95))
                rows.append(row)
    pt = pd.DataFrame(rows)
    pt.to_csv(OUT / "rules_pooled.csv", index=False)
    # BH over rule x cell (CELL scope, real, confirmation) and over rule x strategy (BOOK)
    c = tab[(tab["src"] == "real") & (tab["half"] == "conf") & (tab["cls"] != "RANGE_BREAK")].copy()
    c["bh"] = False
    for scope in ("CELL", "BOOK"):
        mm = c["scope"] == scope
        c.loc[mm, "bh"] = bh(c.loc[mm, "t_p"].to_numpy())
    c.to_csv(OUT / "rules_cell_tests.csv", index=False)
    # verdicts against `passes_if`
    ver = []
    for rule in RULES:
        for pool in ("PROD BOOK", "LRC CELL"):
            conf = pt[(pt["pool"] == pool) & (pt["rule"] == rule) & (pt["half"] == "conf")]
            disc = pt[(pt["pool"] == pool) & (pt["rule"] == rule) & (pt["half"] == "disc")]
            if not len(conf):
                continue
            r = conf.iloc[0]
            i_ = r["real_t_lo"] > 0
            ii = (rule in REG_RULES) or (len(disc) and np.sign(disc.iloc[0]["real_timing"]) == np.sign(r["real_timing"]))
            iii = all(r.get(f"rm{w}_lo", -1) > 0 for w in ("walk", "garch"))
            iv_ = bool(c[(c["rule"] == rule) & (c["fam"] == pool.split()[0])]["bh"].any())
            walk_fit = any(r.get(f"{w}_t_lo", -1) > 0 for w in ("walk", "garch"))
            ver.append(dict(rule=rule, pool=pool, timing=r["real_timing"], lo=r["real_t_lo"], hi=r["real_t_hi"],
                            i=bool(i_), ii=bool(ii), iii=bool(iii), iv=iv_, helps_on_walks=bool(walk_fit),
                            passes=bool(i_ and ii and iii and iv_ and not walk_fit)))
    vt = pd.DataFrame(ver)
    vt.to_csv(OUT / "rules_verdicts.csv", index=False)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 800)
    pd.set_option("display.max_columns", 80)
    show = ["pool", "rule", "half", "real_n", "real_always", "real_switched", "real_timing", "real_t_lo", "real_t_hi",
            "real_over_on", "walk_timing", "walk_t_lo", "walk_t_hi", "garch_timing", "garch_t_lo", "garch_t_hi",
            "real_sh_on", "real_sh_sw", "real_sh_tw"]
    print(pt[[k for k in show if k in pt]].round(4).to_string(index=False))
    print(vt.round(4).to_string(index=False))
    print("BH survivors:", c[c["bh"]][["scope", "fam", "strat", "cls", "iv", "rule", "timing", "t_lo", "t_p"]].to_string())


# --------------------------------------------------------------------------------------------- hedge

def hedge_run(rew, eta, gamma=0.99):
    """rew: days x arms (strategy arms; cash is implicit at 0). Weights for day d from days < d.
    Returns the portfolio's daily return (K x sum w r) and the weight matrix."""
    D, K = rew.shape
    clipped = np.clip(rew, -10, 10)
    G = np.zeros(K + 1)
    W = np.zeros((D, K + 1))
    for d in range(D):
        z = eta * (G - G.max())
        w = np.exp(z)
        W[d] = w / w.sum()
        G[:K] = gamma * G[:K] + clipped[d]
        G[K] = gamma * G[K]
    port = K * (W[:, :K] * rew).sum(1)
    return port, W


def hedge():
    OUT.mkdir(parents=True, exist_ok=True)
    t = load()
    t = t[t["cls"] != "RANGE_BREAK"]
    t["xday"] = t["exit_ts"] // 86400
    rng = np.random.default_rng(13)
    portfolios = []
    for src in SOURCES:
        portfolios.append((f"PROD {src}", t[(t["fam"] == "PROD") & (t["src"] == src)], "strat"))
        for iv in ("15m", "1h", "4h", "1d"):
            for side, cl in (("nonDeriv", ("FX", "METAL", "INDEX", "ENERGY", "CRYPTO_CFD", "BINANCE", "FRESH")),
                             ("Deriv", ("DERIV_1S", "DERIV_DIFFUSIVE", "DERIV_JUMPY"))):
                sub = t[(t["fam"] == "LRC") & (t["src"] == src) & (t["iv"] == iv) & t["cls"].isin(cl)].copy()
                sub["arm"] = sub["strat"] + "|" + sub["cls"]
                portfolios.append((f"LRC {iv} {side} {src}", sub, "arm"))
    rows, curves = [], {}
    for name, sub, armcol in portfolios:
        if not len(sub):
            continue
        piv = sub.pivot_table(index="xday", columns=armcol, values="R", aggfunc="sum").fillna(0.0)
        full = np.arange(piv.index.min(), piv.index.max() + 1)
        piv = piv.reindex(full, fill_value=0.0)
        rew = piv.to_numpy()
        days_ = piv.index.to_numpy()
        always = rew.sum(1)
        for eta, tag in ((0.02, "HEDGE_02"), (0.10, "HEDGE_10")):
            port, W = hedge_run(rew, eta)
            K = rew.shape[1]
            twin = np.zeros(len(days_))
            for hm in (days_ * 86400 < SPLIT, days_ * 86400 >= SPLIT):  # shifted within each half
                nh = int(hm.sum())
                if nh < 30:
                    continue
                Wh, rh = W[hm, :K], rew[hm]
                for o in rng.integers(nh // 10, 9 * nh // 10, 100):
                    twin[hm] += K * (np.roll(Wh, int(o), axis=0) * rh).sum(1) / 100
            curves[(name, tag)] = (days_, always, port, twin, W[:, K])
            for half, hm in (("disc", days_ * 86400 < SPLIT), ("conf", days_ * 86400 >= SPLIT)):
                if hm.sum() < 30:
                    continue
                a, p, tw = always[hm], port[hm], twin[hm]
                res = {}
                for lab, x in (("over_on", p - a), ("timing", p - tw)):
                    m = np.empty(DRAWS)
                    for i in range(0, DRAWS, 100):
                        idx = rng.integers(0, len(x), (100, len(x)))
                        m[i:i + 100] = x[idx].mean(1)
                    res[lab] = (float(x.mean()), float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95)))
                rows.append(dict(portfolio=name, rule=tag, half=half, days=int(hm.sum()), arms=rew.shape[1],
                                 always_day=float(a.mean()), hedge_day=float(p.mean()), twin_day=float(tw.mean()),
                                 cash=float(W[hm, -1].mean()), sh_always=sharpe(a), sh_hedge=sharpe(p),
                                 sh_twin=sharpe(tw), over_on=res["over_on"][0], oo_lo=res["over_on"][1],
                                 oo_hi=res["over_on"][2], timing=res["timing"][0], t_lo=res["timing"][1],
                                 t_hi=res["timing"][2]))
    ht = pd.DataFrame(rows)
    ht.to_csv(OUT / "hedge.csv", index=False)
    pd.to_pickle(curves, OUT / "hedge_curves.pkl.gz")
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    print(ht.round(3).to_string(index=False))


# ------------------------------------------------------------------------------------- kill and hot

def kill():
    OUT.mkdir(parents=True, exist_ok=True)
    t = load()
    base = t[(t["fam"] == "PROD") & (t["src"] == "real") & (t["cls"] != "RANGE_BREAK")]["R"].to_numpy(float)
    base = base[np.isfinite(base)]
    sd = float(base.std())
    centred = base - base.mean()
    print("pooled real PROD R: n", len(base), "mean", round(base.mean(), 4), "sd", round(sd, 4), flush=True)
    from scipy.special import ndtr
    rng = np.random.default_rng(17)
    rows = []
    LEN, PATHS = 3000, int(os.environ.get("PATHS", 2000))
    for shape in ("empirical", "normal_sd1"):
        for mu in RULE["kill_math"]["true_edges"]:
            first = {k: [] for k in ("SPRT", "BAYES_ALL", "BAYES_P05", "CUSUM", "DD", "EQ20", "PH")}
            sprt_dead = []
            paused = {k: [] for k in SEQ_RULES}
            for _ in range(PATHS):
                if shape == "empirical":
                    x = rng.choice(centred, LEN) + mu
                else:
                    x = rng.normal(mu, 1.0, LEN)
                st = states(x)
                for k in first:
                    if k == "BAYES_P05":
                        cs = np.cumsum(x)
                        nn = np.arange(1, LEN + 1)
                        ssd = np.maximum(pd.Series(x).expanding(20).std().fillna(1.0).to_numpy(), 1e-6)
                        prec = 1 / 0.01 + nn / ssd ** 2
                        pr = ndtr((cs / ssd ** 2) / prec * np.sqrt(prec))
                        hit = np.flatnonzero(pr < 0.05)
                        first[k].append(hit[0] + 1 if len(hit) else np.inf)
                        continue
                    off = np.flatnonzero(~st[k][1:])
                    first[k].append(off[0] + 1 if len(off) else np.inf)
                # SPRT first decision either side (one-shot, no restart)
                A, B = math.log(0.8 / 0.05), math.log(0.2 / 0.95)
                llr, dec = 0.0, (np.inf, None)
                kk, mean, m2 = 0, 0.0, 0.0
                for i, r in enumerate(x):
                    kk += 1
                    d = r - mean
                    mean += d / kk
                    m2 += d * (r - mean)
                    s_ = math.sqrt(m2 / (kk - 1)) if kk >= 20 else 1.0
                    llr += 0.10 / (s_ * s_) * (r - 0.05)
                    if llr <= B:
                        dec = (i + 1, "dead")
                        break
                    if llr >= A:
                        dec = (i + 1, "alive")
                        break
                sprt_dead.append(dec)
                for k in SEQ_RULES:
                    paused[k].append(1 - st[k][1:].mean())
            for k, v in first.items():
                v = np.array(v, float)
                fin = v[np.isfinite(v)]
                rows.append(dict(shape=shape, mu=mu, rule=k, what="first pause" if k != "BAYES_P05" else "P(mu>0)<0.05",
                                 share_by_3000=float(np.isfinite(v).mean()),
                                 p10=float(np.quantile(fin, 0.1)) if len(fin) else np.nan,
                                 p50=float(np.quantile(fin, 0.5)) if len(fin) else np.nan,
                                 p90=float(np.quantile(fin, 0.9)) if len(fin) else np.nan,
                                 paused_share=float(np.mean(paused[k])) if k in paused else np.nan))
            nd = np.array([d[0] for d in sprt_dead], float)
            kind = np.array([d[1] or "" for d in sprt_dead])
            fin = np.isfinite(nd)
            rows.append(dict(shape=shape, mu=mu, rule="SPRT one-shot", what="first decision",
                             share_by_3000=float(fin.mean()), p10=float(np.quantile(nd[fin], 0.1)),
                             p50=float(np.quantile(nd[fin], 0.5)), p90=float(np.quantile(nd[fin], 0.9)),
                             dead=float((kind == "dead").mean()), alive=float((kind == "alive").mean())))
            print(shape, mu, "done", flush=True)
    kt = pd.DataFrame(rows)
    kt.to_csv(OUT / "kill.csv", index=False)
    pd.set_option("display.width", 250)
    print(kt.round(3).to_string(index=False))
    power(rng)
    hot(t, centred, rng)


def power(rng):
    """Positive control: streams whose mean switches between +a and -a every `blk` trades (sd 1).
    What each rule earns over its twin there, and the pred_30 such a regime produces."""
    rows = []
    for blk in (50, 200, 500):
        for amp in (0.1, 0.2, 0.3):
            acc = {k: [] for k in SEQ_RULES}
            preds = []
            for _ in range(100):
                x = np.concatenate([rng.normal(amp if i % 2 == 0 else -amp, 1.0, blk) for i in range(3000 // blk)])
                st = states(x)
                for k in SEQ_RULES:
                    m = st[k][:-1].astype(float)
                    acc[k].append(float((m * x).mean() - (twin_mask(m, rng) * x).mean()))
                cs = np.r_[0.0, np.cumsum(x)]
                prev = (cs[30:-1] - cs[:-31]) / 30
                preds.append(np.corrcoef(prev, x[30:])[0, 1])
            rows.append(dict(block=blk, amp=amp, pred_30=float(np.mean(preds)),
                             **{k: float(np.mean(v)) for k, v in acc.items()}))
    pt = pd.DataFrame(rows)
    pt.to_csv(OUT / "power.csv", index=False)
    print(pt.round(3).to_string(index=False))


def streak_stats(x):
    w = x > 0
    best_run, cur = 0, 0
    for v in w:
        cur = cur + 1 if v else 0
        best_run = max(best_run, cur)
    out = {"win_run": best_run}
    cs = np.r_[0.0, np.cumsum(x)]
    for N in (10, 20, 30):
        out[f"best{N}"] = float(((cs[N:] - cs[:-N]) / N).max()) if len(x) >= N else np.nan
    out["best_cum"] = float((cs - np.minimum.accumulate(cs)).max())
    return out


def hot(t, centred, rng):
    rows = []
    walks = t[(t["fam"] == "PROD") & (t["src"].isin(["walk", "garch"])) & (t["cls"] != "RANGE_BREAK")]
    wstreams = [g.sort_values("ts")["R"].to_numpy(float) for _, g in walks.groupby(["strat", "src"])]
    wstreams = [s - s.mean() for s in wstreams if len(s) >= 1000]  # centred: zero edge, the walk's own shape
    for L_ in (30, 100, 300, 1000):
        for kind in ("iid_empirical", "walk_blocks"):
            stats = []
            for _ in range(2000):
                if kind == "iid_empirical":
                    x = rng.choice(centred, L_)
                else:
                    s = wstreams[rng.integers(len(wstreams))]
                    i = rng.integers(0, len(s) - L_)
                    x = s[i:i + L_]
                stats.append(streak_stats(x))
            df = pd.DataFrame(stats)
            for col in df:
                rows.append(dict(length=L_, kind=kind, stat=col, p50=float(df[col].median()),
                                 p90=float(df[col].quantile(0.9)), p95=float(df[col].quantile(0.95))))
    ht = pd.DataFrame(rows)
    ht.to_csv(OUT / "hot.csv", index=False)
    print(ht.pivot_table(index=["stat", "kind"], columns="length", values=["p50", "p95"]).round(2).to_string())


# --------------------------------------------------------------------------------------------- live

def read_closes(path):
    """Close records [{t, title, ctx, src}] from one source: the desk's closes export (a JSON list, as
    `.data/closes.json`) or a journal database (SQLite, table `entries`), where a close is an entry by
    actor `trading` of kind `outcome` (attributed) or `observation` (unattributed) whose context carries
    `profit`. The export is exactly those journal rows, so both read the same closes."""
    p = Path(path)
    if p.suffix not in (".db", ".sqlite", ".sqlite3"):
        return json.loads(p.read_text())  # the desk's closes export (research data)
    import sqlite3
    from urllib.parse import quote
    con = sqlite3.connect(f"file:{quote(str(p.resolve()))}?immutable=1", uri=True)  # read-only, no -shm writes
    try:
        rows = con.execute("SELECT time, kind, title, context FROM entries WHERE actor = 'trading' "
                           "AND kind IN ('outcome', 'observation') ORDER BY time").fetchall()
    finally:
        con.close()
    out = []
    for t, kind, title, ctx in rows:
        c = json.loads(ctx or "{}")
        if c.get("profit") is None:
            continue  # trading observations that are not closes (entries, skips)
        out.append(dict(t=float(t), title=title, ctx=c, src="outcome" if kind == "outcome" else "unattributed"))
    return out


def read_all_closes(paths):
    """Several sources (comma-separated paths or a list), merged and de-duplicated on (time, title):
    an export and a newer journal can be read together and each close counts once."""
    if isinstance(paths, (str, Path)):
        paths = [s.strip() for s in str(paths).split(",") if s.strip()]
    seen, out = set(), []
    for p in paths:
        for r in read_closes(p):
            key = (round(float(r.get("t") or 0), 3), r.get("title"))
            if key not in seen:
                seen.add(key)
                out.append(r)
    return sorted(out, key=lambda r: float(r.get("t") or 0))


def live_streams(path):
    raw = read_all_closes(path)
    rows = []
    for r in raw:
        c = r.get("ctx", {})
        rows.append(dict(t=float(r.get("t") or 0), strat=c.get("strategy") or "", profit=c.get("profit"),
                         risk=c.get("risk_money"), rm=c.get("r_multiple"), feed=c.get("feed"), iv=c.get("interval"),
                         secs=c.get("seconds")))
    d = pd.DataFrame(rows)
    d = d[d["profit"].notna()]
    med = d[d["risk"].fillna(0) > 0].groupby("strat")["risk"].median()
    R = []
    for _, r in d.iterrows():
        if pd.notna(r["rm"]):
            R.append(float(r["rm"]))
        elif pd.notna(r["risk"]) and r["risk"] > 0:
            R.append(float(r["profit"]) / float(r["risk"]))
        elif r["strat"] in med:
            R.append(float(r["profit"]) / float(med[r["strat"]]))
        else:
            R.append(np.nan)
    d["R"] = R
    d = d[np.isfinite(d["R"])].sort_values("t")
    return d


def live():
    OUT.mkdir(parents=True, exist_ok=True)
    d = live_streams(os.environ.get("CLOSES", ".data/closes.json"))
    rng = np.random.default_rng(23)
    rows, traces = [], {}
    for strat, g in d.groupby("strat"):
        if len(g) < 25 or not strat:
            continue
        x = g["R"].to_numpy(float)
        st = states(x)
        traces[strat] = dict(t=g["t"].to_numpy(), R=x, **{k: v[:-1] for k, v in st.items()})
        n = len(x)
        # the necessary condition on the live record: closes are in close order, so the record up to
        # close j-1 is known at close j (a conservative stand-in for entry-time knowledge)
        stats = {}
        for N in (5, 10):
            cs = np.r_[0.0, np.cumsum(x)]
            prev = np.array([(cs[j] - cs[max(0, j - N)]) / min(j, N) for j in range(1, n)])
            y = x[1:]
            obs = np.corrcoef(prev, y)[0, 1]
            perm = []
            for _ in range(10000):
                xp = rng.permutation(x)
                csp = np.r_[0.0, np.cumsum(xp)]
                pp = np.array([(csp[j] - csp[max(0, j - N)]) / min(j, N) for j in range(1, n)])
                perm.append(np.corrcoef(pp, xp[1:])[0, 1])
            perm = np.array(perm)
            stats[f"pred_{N}"], stats[f"pred_{N}_p"] = float(obs), float((perm >= obs).mean())
        ac = np.corrcoef(x[:-1], x[1:])[0, 1]
        pa = np.array([np.corrcoef(p[:-1], p[1:])[0, 1] for p in (rng.permutation(x) for _ in range(10000))])
        stats["ac1"], stats["ac1_p"] = float(ac), float((pa >= ac).mean())
        row = dict(strat=strat, n=n, meanR=float(x.mean()), sdR=float(x.std(ddof=1)),
                   first=pd.to_datetime(g["t"].min(), unit="s").strftime("%Y-%m-%d"),
                   last=pd.to_datetime(g["t"].max(), unit="s").strftime("%Y-%m-%d"), **stats)
        for k, s in st.items():
            off = np.flatnonzero(~s[1:])
            row[f"{k}_first_pause"] = int(off[0] + 1) if len(off) else None
            row[f"{k}_pause_date"] = pd.to_datetime(g["t"].iloc[off[0]], unit="s").strftime("%m-%d %H:%M") if len(off) else ""
            row[f"{k}_end"] = "on" if s[-1] else "paused"
            m = s[:-1].astype(float)  # the decision for close j uses closes before j
            row[f"{k}_switched"] = float((m * x).sum())
        # posterior and SPRT readings at the end
        sd_ = max(x.std(ddof=1), 1e-6)
        prec = 1 / 0.01 + n / sd_ ** 2
        row["post_mean"] = float((x.sum() / sd_ ** 2) / prec)
        row["P_mu_gt_0"] = norm_cdf(row["post_mean"] * math.sqrt(prec))
        row["total"] = float(x.sum())
        rows.append(row)
    lt = pd.DataFrame(rows)
    lt.to_csv(OUT / "live.csv", index=False)
    pd.to_pickle(traces, OUT / "live_traces.pkl")
    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 100)
    print(lt.T.to_string())


def main():
    {"nec": nec, "rules": rules, "hedge": hedge, "kill": kill, "live": live}[os.environ.get("MODE", "nec")]()


if __name__ == "__main__":
    main()
