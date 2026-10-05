"""Tables, verdicts and figures for `cdt.py` (the crypto daily trend combination).

  DATA=.data/cdt/data OUT=.data/cdt/out MODE=report python research/ideas/cdt.py
  ... MODE=plot  (figures into IMG, default research/docs/img/crypto-daily-trend)
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import cdt as C
import cdt_data as D

OUT = C.OUT
IMG = Path(os.environ.get("IMG", "research/docs/img/crypto-daily-trend"))
DRAWS = 2000
BLOCK = 20
RISK = 0.02
DAY0 = pd.Timestamp("2019-09-01", tz="UTC").timestamp() // 86400
NDAYS = int((pd.Timestamp("2026-10-02", tz="UTC").timestamp() // 86400) - DAY0)
SAMPLES = {
    "fresh131": lambda d: d["coin"].isin(D.FRESH131),
    "fresh58": lambda d: d["coin"].isin(D.FRESH58),
    "setC": lambda d: d["coin"].isin(D.SETC),
    "core12_disc": lambda d: d["coin"].isin(D.CORE) & (d["ts"] < C.SPLIT),
    "core12_conf": lambda d: d["coin"].isin(D.CORE) & (d["ts"] >= C.SPLIT),
    "setD": lambda d: d["coin"].isin(D.SETD),
    "mt5": lambda d: d["coin"].str.startswith("mt5:"),
}
for _fam in ("fx", "metal", "index", "energy", "deriv", "range_break"):
    SAMPLES[f"cls_{_fam}"] = (lambda fam: lambda d: d["coin"].isin(
        [f"mt5x:{s}" for s, v in D.mt5x_specs().items() if v[0] == fam]))(_fam)
FILTERS = ("none", "REG200", "REGST")
CELLS = tuple(C.STRATS) + ("DCS",)


# ------------------------------------------------------------------------------------------ loading

def load(iv):
    files = sorted((OUT / "jobs" / iv).glob("*.pkl"))
    fr = []
    for i, f in enumerate(files):
        d = pd.read_pickle(f)["trades"]
        if len(d):
            fr.append(d.assign(file=i))
    d = pd.concat(fr, ignore_index=True)
    d["src_k"] = d["src"] + d["seed"].astype(str)
    return d, files


def select(d, cell, filt):
    """A strategy cell's trades: DCS is DISPLACE_C (C4) in the coin's own Stage; filters by BTC regime."""
    m = (d["strat"] == ("C4" if cell == "DCS" else cell))
    if cell == "DCS":
        m &= d["stage_ok"]
    if filt == "REG200":
        m &= d["reg200"]
    elif filt == "REGST":
        m &= d["regst"]
    return m


# ------------------------------------------------------------------------------------------ statistics

def day_boot(x, ts, rng, draws=DRAWS):
    """Mean of x, its 90% day-bootstrap interval and the one-sided p of mean <= 0."""
    x = np.asarray(x, float)
    if len(x) < 10:
        return np.nan, np.nan, np.nan, np.nan
    day = np.asarray(ts, np.int64) // 86400
    u, inv = np.unique(day, return_inverse=True)
    S = np.bincount(inv, weights=x)
    N = np.bincount(inv).astype(float)
    nd = len(u)
    b = np.empty(draws)
    for k in range(0, draws, 200):
        idx = rng.integers(0, nd, (min(200, draws - k), nd))
        b[k:k + len(idx)] = S[idx].sum(1) / N[idx].sum(1)
    return float(x.mean()), float(np.quantile(b, 0.05)), float(np.quantile(b, 0.95)), float((b <= 0).mean())


def pnr(mfe):
    m = np.asarray(mfe, float)
    return {f"P{N}": float((m >= N).mean()) if len(m) else np.nan for N in C.NS}


def bh(p, q=0.10):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if not ok.any():
        return out
    pp = p[ok]
    o = np.argsort(pp)
    m = len(pp)
    thr = q * np.arange(1, m + 1) / m
    passed = pp[o] <= thr
    k = np.flatnonzero(passed).max() + 1 if passed.any() else 0
    sel = np.zeros(m, bool)
    sel[o[:k]] = True
    out[np.flatnonzero(ok)] = sel
    return out


def cell_row(ds, cell, filt, ex, iv, sample, rng, halves=None):
    """Every number a cell is judged on (`ds`: the sample's trades)."""
    base = ds[ds["exit"] == ex]
    x = base[select(base, cell, filt)]
    r = x[x["src"] == "real"]
    out = dict(cell=cell, filt=filt, exit=ex, iv=iv, sample=sample, n=len(r))
    if len(r) < 10:
        return out
    R, lo, hi, p = day_boot(r["R"], r["ts"], rng)
    split = C.SPLIT if halves is None else halves
    out.update(R=R, lo=lo, hi=hi, p=p,
               R_before=r.loc[r["ts"] < split, "R"].mean(), R_after=r.loc[r["ts"] >= split, "R"].mean(),
               n_long=int((r["side"] > 0).sum()), R_long=r.loc[r["side"] > 0, "R"].mean(),
               R_short=r.loc[r["side"] < 0, "R"].mean(),
               R_iid=x.loc[x["src"] == "iid", "R"].mean(), R_garch=x.loc[x["src"] == "garch", "R"].mean(),
               n_iid=int((x["src"] == "iid").sum()),
               twin=r["twin_R"].mean(), hold=r["hold"].mean(), risk_frac=r["risk_frac"].median(),
               PR4=(r["R"] >= 4).mean(), PR10=(r["R"] >= 10).mean())
    ex_ = (r["R"] - r["twin_R"]).dropna()
    m, l2, h2, p2 = day_boot(ex_, r.loc[ex_.index, "ts"], rng)
    out.update(ex_twin=m, ex_twin_lo=l2, ex_twin_hi=h2)
    for s, tag in (("real", ""), ("iid", "iid_"), ("garch", "garch_")):
        for k, v in pnr(x.loc[x["src"] == s, "mfe"]).items():
            out[tag + k] = v
    for k, v in pnr(r["twin_mfe"].dropna()).items():
        out["twin_" + k] = v
    return out


def table(d, iv, rng):
    rows = []
    samples = ("fresh131", "fresh58", "setC", "core12_disc", "core12_conf")
    if iv == "1d":
        samples += ("setD",)
    if iv == "1h":
        samples = ("fresh58", "core12_disc", "core12_conf")
    if iv == "15m":
        samples = ("core12_disc", "core12_conf")
    samples += ("mt5",)
    if iv in ("1d", "4h"):
        samples += tuple(k for k in SAMPLES if k.startswith("cls_"))
    for sample in samples:
        halves = None
        ds = d[SAMPLES[sample](d)]
        if sample == "setD":
            sd = d[(d["src"] == "real") & d["coin"].isin(D.SETD)]
            halves = float(np.median(np.unique(sd["ts"]))) if len(sd) else None
        for cell in CELLS:
            for filt in FILTERS:
                for ex in C.EXITS:
                    rows.append(cell_row(ds, cell, filt, ex, iv, sample, rng, halves))
    return pd.DataFrame(rows)


def passes(row, sets):
    """The frozen pass rule (without Holm, which needs both primaries)."""
    return bool(row["R"] > 0 and row["lo"] > 0 and row["R_before"] > 0 and row["R_after"] > 0
                and all(s > 0 for s in sets) and row["R"] > row["R_iid"] and row["R"] > row["R_garch"]
                and row["R"] > row["twin"])


# ------------------------------------------------------------------------------------------ market split

def panel_returns(iv, coins):
    """Log close-to-close returns T x N on the bar grid, and the grid."""
    step = C.IVSEC[iv]
    fr = {c: D.load(c, iv) for c in coins}
    fr = {c: x for c, x in fr.items() if x is not None}
    t0 = min(int(x["ts"].iloc[0]) for x in fr.values())
    t1 = max(int(x["ts"].iloc[-1]) for x in fr.values())
    grid = np.arange(t0 - t0 % step, t1 + 1, step, dtype=np.int64)
    names = list(fr)
    Cl = np.full((len(grid), len(names)), np.nan)
    for j, c in enumerate(names):
        x = fr[c]
        idx = ((x["ts"].to_numpy() - grid[0]) // step).astype(int)
        ok = (idx >= 0) & (idx < len(grid))
        Cl[idx[ok], j] = x["close"].to_numpy()[ok]
    lr = np.vstack([np.full((1, len(names)), np.nan), np.log(Cl[1:] / Cl[:-1])])
    return grid, names, lr, Cl


def market_split(d, iv):
    """Each real trade's market part (equal-weight index of core12 + fresh131, and BTC) and residual, and
    the BTC / basket trades over the same windows, in bps."""
    r = d[(d["src"] == "real") & ~d["coin"].str.startswith("mt5")].copy()
    coins = tuple(dict.fromkeys(D.CORE + D.FRESH131 + tuple(r["coin"].unique())))
    grid, names, lr, Cl = panel_returns(iv, coins)
    idx_coins = [names.index(c) for c in D.CORE + D.FRESH131 if c in names]
    ew = np.nan_to_num(np.nanmean(lr[:, idx_coins], 1))
    btc = np.nan_to_num(lr[:, names.index("BTC")])
    cum = {"ew": np.r_[0, np.cumsum(ew)], "btc": np.r_[0, np.cumsum(btc)]}
    L = pd.DataFrame(lr, columns=names)
    beta = {}
    for m, v in (("ew", ew), ("btc", btc)):
        mv = pd.Series(v)
        var = mv.rolling(60, min_periods=30).var()
        cov = L.rolling(60, min_periods=30).cov(mv)
        beta[m] = (cov.div(var, axis=0)).to_numpy()
    step = C.IVSEC[iv]
    ti = ((r["ts"].to_numpy() - grid[0]) // step).astype(int)
    xi = ((r["x_ts"].to_numpy() - grid[0]) // step).astype(int)
    j = np.array([names.index(c) for c in r["coin"]])
    side = r["side"].to_numpy()
    for m in ("ew", "btc"):
        b = beta[m][ti, j]
        M = np.exp(cum[m][xi + 1] - cum[m][ti + 1]) - 1  # close t .. the last bar's close
        r[f"beta_{m}"] = b
        r[f"Rmkt_{m}"] = side * b * M / r["risk_frac"].to_numpy()
        r[f"Rres_{m}"] = r["R"] - r[f"Rmkt_{m}"]
        r[f"bps_{m}_same"] = (side * M * 1e4) - C.FEE * 1e4
    r["bps_btc_long"] = (np.exp(cum["btc"][xi + 1] - cum["btc"][ti + 1]) - 1) * 1e4 - C.FEE * 1e4
    r["bps_alt"] = r["R"] * r["risk_frac"] * 1e4
    return r


# ------------------------------------------------------------------------------------------ portfolio

def live_counts(files, sample_coins):
    """Coins with bars on each day (from the real jobs' first and last bar)."""
    n = np.zeros(NDAYS + 1)
    for f in files:
        name = f.stem
        if not name.startswith("real0_"):
            continue
        coin = name[len("real0_"):]
        if coin not in sample_coins:
            continue
        x = pd.read_pickle(f)
        a = int(x["first"] // 86400 - DAY0)
        b = int(x["last"] // 86400 - DAY0)
        n[max(a, 0):b + 1] += 1
    return n


def funding_days(coin):
    f = D.funding(coin)
    out = np.zeros(NDAYS + 1)
    if f is None:
        return out
    k = (f[0] // 86400 - DAY0).astype(int)
    ok = (k >= 0) & (k <= NDAYS)
    np.add.at(out, k[ok], f[1][ok])
    return out


def books(files, d, cells, sample, with_funding=True):
    """Daily book R sums per (cell label, src_k): sum over open trades of the day's mark-to-market R.
    `cells`: {label: (cell, filt, exit)}. Returns {label: {src_k: array}} and the funding R."""
    coins = set(D.FRESH131 if sample == "fresh131" else D.CORE if sample == "core12" else D.SETD)
    acc = {lab: {} for lab in cells}
    fund = {lab: np.zeros(NDAYS + 1) for lab in cells}
    fcache = {}
    for i, f in enumerate(files):
        coin = f.stem.split("_", 1)[1]
        if coin not in coins:
            continue
        x = pd.read_pickle(f)
        tr, paths = x["trades"], x["paths"]
        if not len(tr):
            continue
        for lab, (cell, filt, ex) in cells.items():
            sel = tr[(tr["exit"] == ex) & select(tr, cell, filt)]
            if not len(sel):
                continue
            sk = sel["src"].iat[0] + str(sel["seed"].iat[0])
            a = acc[lab].setdefault(sk, np.zeros(NDAYS + 1))
            for pi, side, rf in zip(sel["path"], sel["side"], sel["risk_frac"]):
                d0, v = paths[int(pi)]
                k = int(d0 - DAY0)
                a[k:k + len(v)] += v
                if with_funding and sk == "real0":
                    if coin not in fcache:
                        fcache[coin] = funding_days(coin)
                    fund[lab][k:k + len(v)] -= side * fcache[coin][k:k + len(v)] / rf
    return acc, fund


def btc_bench(iv="1d"):
    b = D.load("BTC", "1d")
    k = (b["ts"].to_numpy() // 86400 - DAY0).astype(int)
    r = np.zeros(NDAYS + 1)
    c = b["close"].to_numpy()
    r[k[1:]] = c[1:] / c[:-1] - 1
    return r


def ew_bench(coins):
    tot = np.zeros(NDAYS + 1)
    cnt = np.zeros(NDAYS + 1)
    for c in coins:
        b = D.load(c, "1d")
        if b is None or len(b) < 2:
            continue
        k = (b["ts"].to_numpy() // 86400 - DAY0).astype(int)
        cl = b["close"].to_numpy()
        tot[k[1:]] += cl[1:] / cl[:-1] - 1
        cnt[k[1:]] += 1
    return np.where(cnt > 0, tot / np.maximum(cnt, 1), 0.0), cnt


def stats(r):
    r = np.asarray(r, float)
    s = r.std()
    eq = np.cumprod(1 + r)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    yrs = len(r) / 365
    return dict(sharpe=float(r.mean() / s * np.sqrt(365)) if s > 0 else np.nan, vol=float(s * np.sqrt(365)),
                cagr=float(eq[-1] ** (1 / yrs) - 1) if yrs > 0 and eq[-1] > 0 else np.nan, maxdd=float(dd))


def block_boot(cols, rng, draws=DRAWS, block=BLOCK):
    """Circular block bootstrap over days of several aligned daily series: draws x series of
    (sharpe, maxdd)."""
    X = np.column_stack(cols)
    n = len(X)
    nb = int(np.ceil(n / block))
    sh = np.empty((draws, X.shape[1]))
    dd = np.empty((draws, X.shape[1]))
    for k in range(draws):
        st = rng.integers(0, n, nb)
        idx = (st[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        Y = X[idx]
        s = Y.std(0)
        sh[k] = np.where(s > 0, Y.mean(0) / np.where(s > 0, s, 1) * np.sqrt(365), np.nan)
        eq = np.cumprod(1 + Y, 0)
        dd[k] = (eq / np.maximum.accumulate(eq, 0) - 1).min(0)
    return sh, dd


def twin_book(trades, rng, k=C.K_TWIN):
    """k books of random-entry twins: each trade re-entered on the same coin at a random bar, same side,
    risk in ATR and bars held, marked to daily closes."""
    from mcfl import candles
    acc = np.zeros((k, NDAYS + 1))
    for coin, g in trades.groupby("coin"):
        df = D.load(coin, "1d")
        a = candles._atr(df)
        cost_atr = C.FEE * df["close"].to_numpy(float) / np.maximum(a, 1e-12)
        ts = df["ts"].to_numpy(np.int64)
        n = len(df)
        A = {s: C.Arr(df, s) for s in (1, -1)}
        for side, ra, hold in zip(g["side"], g["risk_atr"], g["hold"]):
            hold = max(1, int(hold))
            hi = n - 2 - hold
            if hi <= C.WARM:
                continue
            Ar = A[side]
            for b in range(k):
                tp = int(rng.integers(C.WARM, hi))
                if not a[tp] > 0:
                    continue
                f = tp + 1
                entry = Ar.O[f]
                risk = ra * a[tp]
                stop = entry - risk
                Lw = Ar.L[f:f + hold]
                ks = int(C.first(Lw <= stop))
                if ks < hold:
                    px = (stop if ks == 0 else min(Ar.O[f + ks], stop)) - C.SLIP * a[tp]
                    last = f + ks
                else:
                    px, last = Ar.O[f + hold], f + hold - 1
                d0, v = C.daily_path(Ar, ts, 86400, f, last, entry, px, risk, cost_atr[tp] / ra)
                kk = int(d0 - DAY0)
                acc[b, kk:kk + len(v)] += v
    return acc


def portfolio(rng, d1, files1):
    """The equal-risk books at 1d (fresh131 and core12) and their comparisons."""
    out = []
    cells = {"P1 AGREE": ("AGREE", "none", "STATE"), "P2 DCS": ("DCS", "none", "STATE"),
             "AGREE REG200": ("AGREE", "REG200", "STATE"), "DCS REG200": ("DCS", "REG200", "STATE"),
             **{f"{C.NAMES[c]}": (c, "none", "STATE") for c in ("C1", "C2", "C3", "C4")},
             **{f"{C.NAMES[c]} REG200": (c, "REG200", "STATE") for c in ("C1", "C2", "C3", "C4")}}
    btc = btc_bench()
    series = {}
    for sample, coins in (("fresh131", D.FRESH131), ("core12", D.CORE)):
        nlive = live_counts(files1, set(coins))
        acc, fund = books(files1, d1, cells, sample)
        ew, _ = ew_bench(coins)
        live = nlive > 0
        first_day = int(np.argmax(live))
        sl = slice(first_day + 200, NDAYS)  # after the components' 200-bar warm-up
        scale = np.where(nlive > 0, RISK / np.maximum(nlive, 1), 0.0)
        bk = {lab: {sk: v * scale for sk, v in a.items()} for lab, a in acc.items()}
        series[sample] = dict(bk=bk, fund={lab: f * scale for lab, f in fund.items()}, btc=btc, ew=ew, sl=sl)
        for lab in cells:
            if "real0" not in bk[lab]:
                continue
            gross = bk[lab]["real0"][sl]
            net_f = gross + series[sample]["fund"][lab][sl]
            cols = [gross, net_f, btc[sl], ew[sl]]
            sh, dd = block_boot(cols, rng, draws=1000)
            st = stats(gross)
            walks = {s: [stats(v[sl])["sharpe"] for k, v in bk[lab].items() if k.startswith(s)] for s in ("iid", "garch")}
            vm = gross * (btc[sl].std() / gross.std()) if gross.std() > 0 else gross
            out.append(dict(sample=sample, book=lab, **{k: st[k] for k in st},
                            sh_lo=np.nanquantile(sh[:, 0], 0.05), sh_hi=np.nanquantile(sh[:, 0], 0.95),
                            dd_lo=np.nanquantile(dd[:, 0], 0.05), sharpe_fund=stats(net_f)["sharpe"],
                            maxdd_volmatched=stats(vm)["maxdd"], cagr_volmatched=stats(vm)["cagr"],
                            d_sh_btc=st["sharpe"] - stats(btc[sl])["sharpe"],
                            d_sh_btc_lo=np.nanquantile(sh[:, 0] - sh[:, 2], 0.05),
                            d_sh_btc_hi=np.nanquantile(sh[:, 0] - sh[:, 2], 0.95),
                            btc_sharpe=stats(btc[sl])["sharpe"], btc_maxdd=stats(btc[sl])["maxdd"],
                            btc_cagr=stats(btc[sl])["cagr"],
                            ew_sharpe=stats(ew[sl])["sharpe"], ew_maxdd=stats(ew[sl])["maxdd"],
                            walk_iid=np.mean(walks["iid"]) if walks["iid"] else np.nan,
                            walk_iid_max=np.max(walks["iid"]) if walks["iid"] else np.nan,
                            walk_garch=np.mean(walks["garch"]) if walks["garch"] else np.nan,
                            walk_garch_max=np.max(walks["garch"]) if walks["garch"] else np.nan,
                            exposure=float((gross != 0).mean()), start=str(pd.Timestamp((DAY0 + sl.start) * 86400, unit="s").date())))
    p = pd.DataFrame(out)
    # the random-entry twin books and the BTC-over-the-same-exposure books for the primaries (fresh131)
    extra = []
    S = series["fresh131"]
    sl = S["sl"]
    nlive = live_counts(files1, set(D.FRESH131))
    scale = np.where(nlive > 0, RISK / np.maximum(nlive, 1), 0.0)
    real = d1[(d1["src"] == "real") & d1["coin"].isin(D.FRESH131) & (d1["exit"] == "STATE")]
    for lab, (cell, filt, ex) in (("P1 AGREE", ("AGREE", "none", "STATE")), ("P2 DCS", ("DCS", "none", "STATE"))):
        tr = real[select(real, cell, filt)]
        tw = twin_book(tr, rng) * scale
        tws = [stats(b[sl])["sharpe"] for b in tw]
        # BTC over the same exposure: same side, same days, the trade's notional (1 / risk_frac per R)
        bb = np.zeros(NDAYS + 1)
        bl = np.zeros(NDAYS + 1)
        for side, rf, ts_, xts in zip(tr["side"], tr["risk_frac"], tr["ts"], tr["x_ts"]):
            a = int(ts_ // 86400 - DAY0) + 1
            b = int(xts // 86400 - DAY0) + 1
            bb[a:b] += side * S["btc"][a:b] / rf
            bl[a:b] += S["btc"][a:b] / rf
            bb[a] -= C.FEE / rf
            bl[a] -= C.FEE / rf
        bb, bl = bb * scale, bl * scale
        g = S["bk"][lab]["real0"]
        extra.append(dict(book=lab, sharpe=stats(g[sl])["sharpe"], twin_mean=np.mean(tws), twin_p95=np.quantile(tws, 0.95),
                          twin_max=np.max(tws), btc_same_side=stats(bb[sl])["sharpe"], btc_same_long=stats(bl[sl])["sharpe"],
                          btc_same_side_cagr=stats(bb[sl])["cagr"], corr_btc=np.corrcoef(g[sl], S["btc"][sl])[0, 1],
                          beta_btc=np.cov(g[sl], S["btc"][sl])[0, 1] / S["btc"][sl].var()))
        series["fresh131"][f"twin_{lab}"] = tw
        series["fresh131"][f"btcsame_{lab}"] = bb
    return p, pd.DataFrame(extra), series


# ------------------------------------------------------------------------------------------ report

def fmt(x, k=3):
    return "nan" if x is None or not np.isfinite(x) else f"{x:+.{k}f}"


def report():
    rng = np.random.default_rng(2026)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_columns", 80)
    ivs = [iv for iv in ("1d", "4h", "1h", "15m") if (OUT / f"run_{iv}.done").exists()]
    tabs, splits = [], []
    for iv in ivs:
        d, files = load(iv)
        t = table(d, iv, rng)
        tabs.append(t)
        print(f"{iv}: {len(d)} trades loaded", flush=True)
        if iv in ("1d", "4h"):
            ms = market_split(d, iv)
            ms.drop(columns=["file"]).to_pickle(OUT / f"split_{iv}.pkl.gz")
            splits.append(ms)
        if iv == "1d":
            d1, files1 = d, files
    T = pd.concat(tabs, ignore_index=True)
    # BH over the secondary cells on the confirmation sample
    conf = (T["sample"] == "fresh131") | ((T["iv"] == "1h") & (T["sample"] == "fresh58")) | ((T["iv"] == "15m") & (T["sample"] == "core12_conf"))
    prim = (T["iv"] == "1d") & (T["sample"] == "fresh131") & (T["filt"] == "none") & (T["exit"] == "STATE") & T["cell"].isin(["AGREE", "DCS"])
    sec = conf & ~prim & T["p"].notna()
    T["bh"] = False
    T.loc[sec, "bh"] = bh(T.loc[sec, "p"].to_numpy())
    T["survives"] = T["bh"] & (T["R"] > 0) & (T["R"] > T["R_iid"]) & (T["R"] > T["R_garch"]) & (T["R"] > T["twin"])
    T.to_csv(OUT / "cells.csv", index=False)
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)
    if (OUT / "sanity.txt").exists():
        say("SANITY " + (OUT / "sanity.txt").read_text().strip() + "  (turn_confirm +0.142 [+0.015, +0.280])")
    # primaries
    def get(cell, sample, iv="1d", filt="none", ex="STATE"):
        x = T[(T["cell"] == cell) & (T["sample"] == sample) & (T["iv"] == iv) & (T["filt"] == filt) & (T["exit"] == ex)]
        return x.iloc[0] if len(x) else None
    ps = {}
    for name, cell in (("P1", "AGREE"), ("P2", "DCS")):
        r = get(cell, "fresh131")
        s58, sC = get(cell, "fresh58"), get(cell, "setC")
        ps[name] = (r, passes(r, [s58["R"], sC["R"]]))
    pv = sorted([(ps[k][0]["p"], k) for k in ps])
    holm = {pv[0][1]: pv[0][0] < 0.025, pv[1][1]: pv[0][0] < 0.025 and pv[1][0] < 0.05}
    say("\nPRIMARIES (1d, STATE exit, both sides, fresh131)")
    for name, (r, ok) in ps.items():
        s58, sC = get(r["cell"], "fresh58"), get(r["cell"], "setC")
        verdict = "PASSES" if ok and holm[name] else "fails"
        say(f"{name} {C.NAMES[r['cell']]}: n={r['n']} R {fmt(r['R'])} [{fmt(r['lo'])}, {fmt(r['hi'])}] p={r['p']:.4f} "
            f"(Holm {'ok' if holm[name] else 'no'}); before {fmt(r['R_before'])} after {fmt(r['R_after'])}; "
            f"fresh58 {fmt(s58['R'])} setC {fmt(sC['R'])}; iid {fmt(r['R_iid'])} garch {fmt(r['R_garch'])}; "
            f"twin {fmt(r['twin'])}; long {fmt(r['R_long'])} (n {r['n_long']}) short {fmt(r['R_short'])} -> {verdict}")
        say(f"   beyond the twin: {fmt(r['ex_twin'])} [{fmt(r['ex_twin_lo'])}, {fmt(r['ex_twin_hi'])}]; "
            f"P(4R) {r['P4']:.3f} / iid {r['iid_P4']:.3f} / garch {r['garch_P4']:.3f} / twin {r['twin_P4']:.3f} / 0.200; "
            f"P(10R) {r['P10']:.3f} / {r['iid_P10']:.3f} / {r['garch_P10']:.3f} / {r['twin_P10']:.3f} / 0.091")
        for rep in ("setD", "core12_conf", "core12_disc"):
            q = get(r["cell"], rep)
            if q is not None and "R" in q and np.isfinite(q.get("R", np.nan)):
                say(f"   {rep}: n={q['n']} R {fmt(q['R'])} [{fmt(q['lo'])}, {fmt(q['hi'])}] halves {fmt(q['R_before'])} / "
                    f"{fmt(q['R_after'])}; iid {fmt(q['R_iid'])} garch {fmt(q['R_garch'])} twin {fmt(q['twin'])} -> "
                    f"{'passes' if passes(q, []) else 'fails'}")
    # market split for the primaries and components
    if splits:
        say("\nMARKET SPLIT (STATE exit, real trades; R = market part + residual; EW = equal-weight index of 143)")
        rows = []
        for ms in splits:
            for sample in ("fresh131", "core12_conf", "setD"):
                if sample == "setD" and ms["iv"].iat[0] != "1d":
                    continue
                base = ms[(ms["exit"] == "STATE") & SAMPLES[sample](ms)]
                for cell in CELLS:
                    for filt in ("none", "REG200"):
                        x = base[select(base, cell, filt)].dropna(subset=["Rres_ew"])
                        if len(x) < 30:
                            continue
                        _, lo, hi, _ = day_boot(x["Rres_ew"], x["ts"], rng)
                        _, lob, hib, _ = day_boot(x["Rres_btc"], x["ts"], rng)
                        _, loa, hia, _ = day_boot(x["bps_alt"], x["ts"], rng)
                        _, los, his, _ = day_boot(x["bps_btc_same"], x["ts"], rng)
                        rows.append(dict(iv=ms["iv"].iat[0], sample=sample, cell=cell, filt=filt, n=len(x), R=x["R"].mean(),
                                         mkt_ew=x["Rmkt_ew"].mean(), res_ew=x["Rres_ew"].mean(), res_ew_lo=lo, res_ew_hi=hi,
                                         mkt_btc=x["Rmkt_btc"].mean(), res_btc=x["Rres_btc"].mean(), res_btc_lo=lob, res_btc_hi=hib,
                                         beta_ew=x["beta_ew"].mean(), bps_alt=x["bps_alt"].mean(), bps_alt_lo=loa, bps_alt_hi=hia,
                                         bps_btc_same=x["bps_btc_same"].mean(), bps_btc_lo=los, bps_btc_hi=his,
                                         bps_ew_same=x["bps_ew_same"].mean(), bps_btc_long=x["bps_btc_long"].mean(),
                                         side_match_ew=float((np.sign(x["Rmkt_ew"] * x["side"]) == x["side"]).mean())))
        M = pd.DataFrame(rows)
        M.to_csv(OUT / "market_split.csv", index=False)
        say(M.round(3).to_string(index=False))
    # portfolio
    if "1d" in ivs:
        P, X, series = portfolio(rng, d1, files1)
        P.to_csv(OUT / "portfolio.csv", index=False)
        X.to_csv(OUT / "portfolio_twins.csv", index=False)
        pd.to_pickle(series, OUT / "books.pkl")
        say("\nPORTFOLIO (1d, equal-risk, 2% of each coin's sleeve per trade; net of 0.07% + stop slippage)")
        say(P.round(3).to_string(index=False))
        say(X.round(3).to_string(index=False))
    # secondary
    say("\nSECONDARY CELLS that survive BH (q 0.10) and beat both walks and the twin:")
    say(T[T["survives"]][["cell", "filt", "exit", "iv", "sample", "n", "R", "lo", "hi", "p", "R_iid", "R_garch", "twin",
                          "R_long", "R_short", "R_before", "R_after"]].round(3).to_string(index=False))
    say(f"({int(sec.sum())} secondary cells tried, {int(T['bh'].sum())} pass BH, {int(T['survives'].sum())} survive)")
    say("\nALL CELLS (fresh131; 1h fresh58; 15m core12 from 2024):")
    cols = ["cell", "filt", "exit", "iv", "n", "R", "lo", "hi", "R_before", "R_after", "R_long", "R_short", "R_iid",
            "R_garch", "twin", "ex_twin", "P4", "iid_P4", "twin_P4", "P10", "iid_P10", "twin_P10", "bh"]
    say(T[conf][cols].round(3).to_string(index=False))
    (OUT / "report.txt").write_text("\n".join(lines))


# ------------------------------------------------------------------------------------------ plots

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    IMG.mkdir(parents=True, exist_ok=True)
    T = pd.read_csv(OUT / "cells.csv")
    plt.rcParams.update({"font.size": 9})
    Ns = np.array(C.NS)
    ref = 1 / (Ns + 1)

    # 1. P(N R): primaries and components, 1d fresh131, STATE
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    for ax, cell in zip(axes.flat, ("AGREE", "DCS", "C1", "C2", "C3", "C4")):
        r = T[(T["cell"] == cell) & (T["sample"] == "fresh131") & (T["iv"] == "1d") & (T["filt"] == "none") & (T["exit"] == "STATE")].iloc[0]
        for tag, col, lab in (("", "k", "real"), ("iid_", "#1f77b4", "iid walk"), ("garch_", "#ff7f0e", "GARCH walk"),
                              ("twin_", "#2ca02c", "random-entry twin")):
            ax.plot(Ns, [r[f"{tag}P{N}"] for N in C.NS], "o-", color=col, label=lab, lw=1.5 if tag == "" else 1)
        ax.plot(Ns, ref, "--", color="grey", label="1/(N+1)")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xticks(Ns)
        ax.set_xticklabels([str(x) for x in C.NS])
        ax.set_title(f"{C.NAMES[cell]}  n={int(r['n'])}  R {r['R']:+.3f}")
        ax.set_xlabel("N (R before the initial stop)")
        ax.set_ylabel("P(reach +N R)")
        ax.grid(alpha=0.3, which="both")
    axes.flat[0].legend(fontsize=8)
    fig.suptitle("P(+N R before -1R), 1d, fresh131 coins, both sides: real against walks, the random-entry twin and 1/(N+1)")
    fig.tight_layout()
    fig.savefig(IMG / "pnr_1d.png", dpi=90)
    plt.close(fig)

    # 2. R by cell and timeframe (fresh131), with walks and twin
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), sharey=True)
    for ax, filt in zip(axes, FILTERS):
        x = T[(T["filt"] == filt) & (T["exit"] == "STATE") & ((T["sample"] == "fresh131") | ((T["iv"] == "1h") & (T["sample"] == "fresh58")) | ((T["iv"] == "15m") & (T["sample"] == "core12_conf")))]
        ivs = [iv for iv in ("1d", "4h", "1h", "15m") if iv in set(x["iv"])]
        w = 0.8 / max(1, len(ivs))
        for k, iv in enumerate(ivs):
            y = x[x["iv"] == iv].set_index("cell").reindex(CELLS)
            pos = np.arange(len(CELLS)) + k * w
            ax.bar(pos, y["R"], w, label=iv, alpha=0.85)
            ax.errorbar(pos, y["R"], yerr=[y["R"] - y["lo"], y["hi"] - y["R"]], fmt="none", ecolor="k", lw=0.8)
            ax.scatter(pos, y["R_iid"], marker="_", color="#1f77b4", s=80, zorder=3)
            ax.scatter(pos, y["twin"], marker="x", color="#2ca02c", s=25, zorder=3)
        ax.axhline(0, color="k", lw=0.7)
        ax.set_xticks(np.arange(len(CELLS)) + 0.4 - w / 2)
        ax.set_xticklabels([C.NAMES[c] for c in CELLS], rotation=30, ha="right")
        ax.set_title(f"filter: {filt} (STATE exit)")
        ax.grid(alpha=0.3, axis="y")
    axes[0].set_ylabel("net R a trade (90% day bootstrap)")
    axes[0].legend(title="timeframe; - iid walk, x twin", fontsize=8)
    fig.suptitle("Net R per trade by strategy, regime filter and timeframe (fresh131; 1h: fresh58; 15m: core12 from 2024)")
    fig.tight_layout()
    fig.savefig(IMG / "r_by_cell.png", dpi=90)
    plt.close(fig)

    # 3. market split
    if (OUT / "market_split.csv").exists():
        M = pd.read_csv(OUT / "market_split.csv")
        fig, axes = plt.subplots(1, 2, figsize=(16, 5.5))
        for ax, iv in zip(axes, ("1d", "4h")):
            x = M[(M["iv"] == iv) & (M["sample"] == "fresh131")]
            labs = [f"{C.NAMES[c]}{' REG200' if f == 'REG200' else ''}" for c, f in zip(x["cell"], x["filt"])]
            pos = np.arange(len(x))
            ax.bar(pos - 0.27, x["R"], 0.27, label="R (net)", color="k")
            ax.bar(pos, x["mkt_ew"], 0.27, label="market part (EW index)", color="#1f77b4")
            ax.bar(pos + 0.27, x["res_ew"], 0.27, label="residual", color="#d62728")
            ax.errorbar(pos + 0.27, x["res_ew"], yerr=[x["res_ew"] - x["res_ew_lo"], x["res_ew_hi"] - x["res_ew"]],
                        fmt="none", ecolor="k", lw=0.8)
            ax.axhline(0, color="k", lw=0.7)
            ax.set_xticks(pos)
            ax.set_xticklabels(labs, rotation=35, ha="right")
            ax.set_title(f"{iv}: each trade = beta x market move + residual (fresh131)")
            ax.grid(alpha=0.3, axis="y")
        axes[0].legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(IMG / "market_split.png", dpi=90)
        plt.close(fig)

    # 4. books
    if (OUT / "books.pkl").exists():
        S = pd.read_pickle(OUT / "books.pkl")["fresh131"]
        sl = S["sl"]
        days = pd.to_datetime((DAY0 + np.arange(NDAYS + 1)) * 86400, unit="s")[sl]
        fig, axes = plt.subplots(2, 2, figsize=(17, 10))
        for ax, lab in zip(axes[0], ("P1 AGREE", "P2 DCS")):
            g = S["bk"][lab]["real0"][sl]
            vol = g.std()
            k = S["btc"][sl].std() / vol if vol > 0 else 1
            for b in S[f"twin_{lab}"]:
                ax.plot(days, np.cumprod(1 + b[sl] * k), color="#2ca02c", alpha=0.15, lw=0.6)
            for sk, v in S["bk"][lab].items():
                if sk != "real0":
                    ax.plot(days, np.cumprod(1 + v[sl] * k), color="#1f77b4" if sk.startswith("iid") else "#ff7f0e", alpha=0.35, lw=0.6)
            ax.plot(days, np.cumprod(1 + S["btc"][sl]), color="#f2a900", lw=1.3, label="BTC buy-and-hold")
            ax.plot(days, np.cumprod(1 + S["ew"][sl]), color="purple", lw=1.0, label="equal-weight basket")
            ax.plot(days, np.cumprod(1 + S[f"btcsame_{lab}"][sl] * k), color="#8c564b", lw=1.0, label="BTC over the same exposure")
            ax.plot(days, np.cumprod(1 + g * k), color="k", lw=1.6, label=f"{lab} (vol-matched to BTC)")
            ax.set_yscale("log")
            ax.set_title(f"{lab} book, fresh131, at BTC's volatility; green: 20 twin books, blue/orange: walk books")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3, which="both")
        for ax, lab in zip(axes[1], ("P1 AGREE", "P2 DCS")):
            g = S["bk"][lab]["real0"][sl]
            k = S["btc"][sl].std() / g.std() if g.std() > 0 else 1
            for v, col, nm in ((S["ew"][sl], "purple", "EW basket"), (S["btc"][sl], "#f2a900", "BTC"), (g * k, "k", lab)):
                eq = np.cumprod(1 + v)
                ax.plot(days, eq / np.maximum.accumulate(eq) - 1, color=col, lw=1.2 if col == "k" else 0.9, label=nm)
            ax.set_title(f"drawdown at BTC's volatility: {lab}")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(IMG / "books.png", dpi=90)
        plt.close(fig)

    # 5. by year, primaries
    if (OUT / "split_1d.pkl.gz").exists():
        ms = pd.read_pickle(OUT / "split_1d.pkl.gz")
        fig, axes = plt.subplots(1, 2, figsize=(15, 5))
        for ax, cell in zip(axes, ("AGREE", "DCS")):
            x = ms[(ms["exit"] == "STATE") & ms["coin"].isin(D.FRESH131)]
            x = x[select(x, cell, "none")]
            yr = pd.to_datetime(x["ts"], unit="s").dt.year
            for k, (s, col) in enumerate(((1, "#2ca02c"), (-1, "#d62728"))):
                g = x[x["side"] == s].groupby(yr[x["side"] == s])
                ax.bar(g["R"].mean().index + (k - 0.5) * 0.35, g["R"].mean(), 0.35, color=col, label="long" if s > 0 else "short")
            g = x.groupby(yr)
            ax.plot(g["Rres_ew"].mean().index, g["Rres_ew"].mean(), "ko-", label="residual (both sides)")
            ax.axhline(0, color="k", lw=0.7)
            ax.set_title(f"{C.NAMES[cell]}, 1d fresh131: R by signal year")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        fig.savefig(IMG / "by_year.png", dpi=90)
        plt.close(fig)
    gallery(plt)
    print("plots written", flush=True)


def gallery(plt):
    """Six AGREE trades (1d, fresh131): three winners and three losers, with the four components' states."""
    import tv_indicators as TV
    ms = pd.read_pickle(OUT / "split_1d.pkl.gz")
    x = ms[(ms["exit"] == "STATE") & ms["coin"].isin(D.FRESH131) & (ms["strat"] == "AGREE")]
    rng = np.random.default_rng(5)
    pick = pd.concat([x[x["R"] > 2].sample(3, random_state=1), x[x["R"] < 0].sample(3, random_state=2)])
    fig, axes = plt.subplots(2, 3, figsize=(20, 10))
    for ax, (_, r) in zip(axes.flat, pick.iterrows()):
        df = D.load(r["coin"], "1d")
        S, stage, cnt = C.components(df, "1d")
        t = int(r["t"])
        last = t + int(r["hold"])
        i0, i1 = max(0, t - 60), min(len(df) - 1, last + 30)
        w = df.iloc[i0:i1 + 1]
        xx = np.arange(i0, i1 + 1)
        up = (w["close"] >= w["open"]).to_numpy()
        ax.vlines(xx, w["low"], w["high"], color="#555", lw=0.6)
        ax.bar(xx[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
        ax.bar(xx[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
        sma = pd.Series(df["close"]).rolling(30).mean().to_numpy()[i0:i1 + 1]
        ax.plot(xx, sma, color="grey", lw=0.8, ls="--")
        entry = df["open"].iat[t + 1]
        stop = entry - r["side"] * r["risk_frac"] * entry
        ax.hlines([entry, stop], t + 1, last, colors=["k", "red"], lw=1)
        ax.axvspan(t + 1, last, color="gold", alpha=0.12)
        n = cnt["nL"] if r["side"] > 0 else cnt["nS"]
        ax2 = ax.twinx()
        ax2.step(xx, n[i0:i1 + 1], color="purple", lw=0.8, where="mid")
        ax2.set_ylim(0, 8)
        ax2.set_yticks([0, 1, 2, 3, 4])
        ax.set_title(f"{r['coin']}USDT 1d {'long' if r['side'] > 0 else 'short'} {pd.Timestamp(r['ts'], unit='s'):%Y-%m-%d} "
                     f"-> {r['R']:+.2f}R (market {r['Rmkt_ew']:+.2f}, residual {r['Rres_ew']:+.2f})", fontsize=9)
    fig.suptitle("AGREE trades on fresh coins (gold: held; black entry, red stop; purple step: components ON the trade's way, "
                 "right axis; dashed SMA30)")
    fig.tight_layout()
    fig.savefig(IMG / "agree_gallery.png", dpi=80)
    plt.close(fig)
