"""Market state topology and complex-systems early warning: do borrowed tools warn of a regime
transition before it comes, beyond what the production shock forecaster already knows?

`findings.md`: this desk forecasts risk, not direction. So the targets are transitions - a shock, a
range blowout, a volatility-regime shift - and the question is incremental: the production shock
forecaster (`anomalies.md`, AUC 0.73-0.76) already reads volatility state, clustering and the
clock. A borrowed statistic is only worth anything if it adds to that.

Tools, each computed causally on the last W = 50 bars of returns in units of the trailing 500-bar
mean |return| (`z`), at every `STRIDE`-th bar:

  tda        persistent homology (Gidea & Katz 2018): a Takens delay embedding of z (dimension 3,
             delay 1) as a point cloud; Vietoris-Rips H0 and H1 by ripser. Persistence-landscape
             norms, exact from the lifetimes l: summed over all landscape layers, L1 = sum l^2 / 4
             and L2^2 = sum l^3 / 12 (the layers are the order statistics of the points' tents).
             Plus the count of H1 features living longer than 0.5.
  tda_shape  the same on the window standardised by its own sd - topology with the volatility
             level removed, which is what the "killer question" needs
  csd        critical slowing down (Scheffer et al. 2009): lag-1 autocorrelation of z and of |z|,
             the variance of z, and the Kendall tau of variance across five 20-bar blocks
  phys       statistical physics: the Hill tail exponent of |z| over 250 bars (top 25), sample
             entropy (m = 2, r = 0.2 sd) at scales 1 and 2 over 100 bars, and a Rosenstein
             largest-Lyapunov estimate on the delay embedding of the last 100 bars

Baseline: the production shock forecaster's features (`structures/learning/shocks.py`), computed
from bars: log EWMA-true-range over its 500-bar mean and its square, its rank in 500 bars and its
square, the volatility of log volatility over 50 bars, shocks in the last 20 and 100 bars, hour
(sin, cos), hours to Friday 21:00 UTC.

Targets, pre-registered (next bars only, from bar t+1):
  shock   a bar with |r| > 4x the trailing 500-bar mean |r| within 4 bars (as `shocks.py`)
  range   a bar with high-low > 4x its trailing 500-bar mean within 4 bars
  vshift  the realised sd of r over the next 20 bars >= 2x its sd over the last 100 bars - a
          volatility-regime shift up. A defined proxy, not a fitted Markov switch or Bai-Perron
          break: those need the future to place the break.

Test, per family x interval x target: gradient boosting on the baseline against baseline + each
tool group, fit on the first 60% by time, scored on the last 40%. Incremental AUC with a paired
day-bootstrap (200) CI, and in each half of the test. Each statistic's AUC alone. Families: FX,
metals, crypto, Deriv (a market: Volatility, Boom, Crash, Jump, Range Break), and walks we generate -
iid t(3), and GARCH(1,1) with t innovations: volatility clustering and nothing else, the control
that matters here. Intervals 15m, 1h, 1d.

Pass bar (pre-registered): incremental AUC >= 0.01, CI above 0, positive in both halves, and not
on the GARCH walks. BH across every (family, interval, target, group) cell, and the best cell
deflated against the expected maximum of that many null draws (`lopez-de-prado.md`).

The killer question: are regimes told apart by topology when the moments look the same? Baseline
= the window's moments (sd, skew, kurtosis of z, plus their tercile cell), then add tda_shape.

Run on the lab: PART=run (per family, parallel), then PART=report.
"""
from __future__ import annotations

import math
import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

PART = os.environ.get("PART", "run")
OUT = Path(os.environ.get("OUT", ".data/topology"))
ONLY = os.environ.get("ONLY", "")
PROCS = int(os.environ.get("PROCS", "10"))
W, NORM = 50, 500
INTERVALS = ("15m", "1h", "1d")
SECONDS = {"15m": 900, "1h": 3600, "1d": 86400}
STRIDE = {"15m": 4, "1h": 2, "1d": 1}
KEEP = {"15m": 120_000, "1h": 60_000, "1d": 100_000}
FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY"],
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "deriv": ["Volatility_75_Index", "Boom_1000_Index", "Crash_1000_Index", "Jump_50_Index",
              "Range_Break_100_Index"],
    "walks_iid": [f"iid_{i}" for i in range(6)],
    "walks_garch": [f"garch_{i}" for i in range(6)],
}
BASE = ["lvol", "lvol2", "rank", "rank2", "volvol", "sh20", "sh100", "hsin", "hcos", "toweek"]
GROUPS = {
    "tda": ["h0_l1", "h0_l2", "h1_l1", "h1_l2", "h1_n"],
    "tda_shape": ["sh0_l1", "sh0_l2", "sh1_l1", "sh1_l2", "sh1_n"],
    "csd": ["ac1", "acabs", "var", "vartau"],
    "phys": ["hill", "se1", "se2", "lyap"],
}
GROUPS["all"] = [f for g in GROUPS.values() for f in g]
MOMENTS = ["m_sd", "m_skew", "m_kurt"]
TARGETS = ("shock", "range", "vshift")

try:  # ripser on the lab; a local smoke test falls back to H0 only
    from ripser import ripser as _ripser
except ImportError:  # pragma: no cover
    _ripser = None


# ------------------------------------------------------------------------------------------ bars

def walk(kind: str, seed: int, n: int, step: int) -> pd.DataFrame:
    """Our own control: iid t(3), or GARCH(1,1) with t(4) innovations; 12 sub-steps a bar."""
    rng = np.random.default_rng(seed)
    sub = 12
    m = n * sub
    if kind == "iid":
        e = rng.standard_t(3, m) * 0.0006
    else:
        z = rng.standard_t(4, m) / math.sqrt(2.0)
        e = np.empty(m)
        var, w, a, b = 1e-6, 1e-6 * 0.02, 0.08, 0.90
        for i in range(m):
            e[i] = math.sqrt(var) * z[i]
            var = w + a * e[i] ** 2 + b * var
    path = 100 * np.exp(np.cumsum(e)).reshape(n, sub)
    close = path[:, -1]
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(path.max(1), open_)
    low = np.minimum(path.min(1), open_)
    return pd.DataFrame({"ts": 1_500_000_000 + step * np.arange(n), "open": open_, "high": high,
                         "low": low, "close": close})


def load(sym: str, iv: str) -> pd.DataFrame | None:
    step = SECONDS[iv]
    if sym.startswith(("iid_", "garch_")):
        kind, i = sym.split("_")
        n = int({"15m": 60_000, "1h": 40_000, "1d": 6_000}[iv] * float(os.environ.get("SCALE", "1")))
        return walk(kind, 97 * int(i) + step, n, step)
    import spikerisk
    try:
        df = spikerisk.load(None, sym, "SEQLAB", iv)
    except (ValueError, FileNotFoundError):
        return None
    return df.iloc[-KEEP[iv]:].reset_index(drop=True)


# ------------------------------------------------------------------------------------------ tools

def lifetimes(cloud: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Finite H0 and H1 lifetimes of the Vietoris-Rips filtration."""
    if _ripser is not None:
        dg = _ripser(cloud, maxdim=1)["dgms"]
        h0 = dg[0][np.isfinite(dg[0][:, 1])]
        h1 = dg[1]
        return h0[:, 1] - h0[:, 0], (h1[:, 1] - h1[:, 0]) if len(h1) else np.zeros(0)
    from scipy.sparse.csgraph import minimum_spanning_tree
    from scipy.spatial.distance import pdist, squareform
    mst = minimum_spanning_tree(squareform(pdist(cloud))).data
    return np.sort(mst), np.zeros(0)


def landscape(l: np.ndarray, floor: float) -> list[float]:
    if not len(l):
        return [0.0, 0.0, 0.0]
    return [float((l**2).sum() / 4), float(np.sqrt((l**3).sum() / 12)), float((l > floor).sum())]


def tda(z: np.ndarray) -> list[float]:
    cloud = np.column_stack([z[:-2], z[1:-1], z[2:]])
    h0, h1 = lifetimes(cloud)
    a = landscape(h0, 0.5)[:2]
    return a + landscape(h1, 0.5)


def sampen(x: np.ndarray, m: int = 2) -> float:
    r = 0.2 * x.std()
    if r <= 0 or len(x) < m + 3:
        return float("nan")

    def count(mm):
        e = np.lib.stride_tricks.sliding_window_view(x, mm)
        d = np.max(np.abs(e[:, None, :] - e[None, :, :]), axis=2)
        return (d <= r).sum() - len(e)

    b, a = count(m), count(m + 1)
    return float(-math.log(a / b)) if a > 0 and b > 0 else float("nan")


def lyapunov(x: np.ndarray, k: int = 4) -> float:
    """Rosenstein: mean log divergence of nearest neighbours in the delay embedding, its slope."""
    e = np.column_stack([x[:-2], x[1:-1], x[2:]])
    n = len(e) - k
    if n < 10:
        return float("nan")
    d = np.linalg.norm(e[:n, None, :] - e[None, :n, :], axis=2)
    idx = np.arange(n)
    d[np.abs(idx[:, None] - idx[None, :]) < 3] = np.inf
    nn = d.argmin(1)
    curve = []
    for j in range(k + 1):
        dist = np.linalg.norm(e[idx + j] - e[nn + j], axis=1)
        curve.append(np.log(dist[dist > 0]).mean() if (dist > 0).any() else np.nan)
    return float(np.polyfit(np.arange(k + 1), curve, 1)[0]) if np.all(np.isfinite(curve)) else float("nan")


def hill(a: np.ndarray, top: int = 25) -> float:
    s = np.sort(a[a > 0])[::-1]
    if len(s) <= top:
        return float("nan")
    return float(1.0 / np.mean(np.log(s[:top] / s[top])))


def kendall_tau(y: np.ndarray) -> float:
    n = len(y)
    s = sum(np.sign(y[j] - y[i]) for i in range(n) for j in range(i + 1, n))
    return float(s / (n * (n - 1) / 2))


# ------------------------------------------------------------------------------------------ rows

def series_rows(args) -> pd.DataFrame | None:
    fam, sym, iv = args
    df = load(sym, iv)
    if df is None or len(df) < NORM + 300:
        return None
    c, h, lo, o = (df[k].to_numpy(float) for k in ("close", "high", "low", "open"))
    ts = df["ts"].to_numpy(np.int64)
    lc = np.log(c)
    r = np.r_[0.0, np.diff(lc)]
    rng = np.log(h) - np.log(lo)
    base = pd.Series(np.abs(r)).rolling(NORM, min_periods=NORM).mean().to_numpy()
    rbase = pd.Series(rng).rolling(NORM, min_periods=NORM).mean().to_numpy()
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, prev) - np.minimum(lo, prev)
    ewma = pd.Series(tr).ewm(span=14, adjust=False).mean().to_numpy()
    trm = pd.Series(tr).rolling(NORM, min_periods=NORM).mean().to_numpy()
    lvol = np.log(np.where((ewma > 0) & (trm > 0), ewma / trm, 1.0))
    rank = pd.Series(ewma).rolling(NORM, min_periods=NORM).rank(pct=True).to_numpy()
    volvol = pd.Series(np.log(np.maximum(ewma, 1e-12))).rolling(50).std().to_numpy()
    shock_now = (np.abs(r) > 4 * base).astype(float)
    range_now = (rng > 4 * rbase).astype(float)
    sh20 = pd.Series(shock_now).rolling(20).mean().to_numpy()
    sh100 = pd.Series(shock_now).rolling(100).mean().to_numpy()
    z_all = np.where(base > 0, r / base, 0.0)
    step = SECONDS[iv]
    rows = []
    last = len(c) - 21
    for t in range(NORM + 250, last, STRIDE[iv]):
        z = z_all[t - W + 1: t + 1]
        if not np.isfinite(z).all() or z.std() <= 0:
            continue
        zs = (z - z.mean()) / z.std()
        when = ts[t] + step
        hour = (when % 86400) / 3600
        week_hour = (when / 3600 + 72) % 168
        f = {
            "family": fam, "sym": sym, "iv": iv, "t": float(when),
            "lvol": lvol[t], "lvol2": lvol[t] ** 2, "rank": rank[t], "rank2": rank[t] ** 2,
            "volvol": volvol[t], "sh20": sh20[t], "sh100": sh100[t],
            "hsin": math.sin(2 * math.pi * hour / 24), "hcos": math.cos(2 * math.pi * hour / 24),
            "toweek": math.log1p((4 * 24 + 21 - week_hour) % 168),
        }
        f.update(zip(GROUPS["tda"], tda(z)))
        f.update(zip(GROUPS["tda_shape"], tda(zs)))
        az = np.abs(z)
        blocks = [z_all[t - 100 + 1 + 20 * k: t - 100 + 1 + 20 * (k + 1)].var() for k in range(5)]
        f.update({
            "ac1": float(np.corrcoef(z[:-1], z[1:])[0, 1]),
            "acabs": float(np.corrcoef(az[:-1], az[1:])[0, 1]) if az.std() > 0 else 0.0,
            "var": float(z.var()), "vartau": kendall_tau(np.array(blocks)),
        })
        z100 = z_all[t - 99: t + 1]
        f.update({
            "hill": hill(np.abs(z_all[t - 249: t + 1])),
            "se1": sampen(z100), "se2": sampen(z100.reshape(-1, 2).mean(1)),
            "lyap": lyapunov(z100),
        })
        f.update({"m_sd": float(z.std()), "m_skew": float(pd.Series(z).skew()),
                  "m_kurt": float(pd.Series(z).kurt())})
        f["shock"] = float(shock_now[t + 1: t + 5].max())
        f["range"] = float(range_now[t + 1: t + 5].max())
        past = r[t - 99: t + 1].std()
        f["vshift"] = float(r[t + 1: t + 21].std() >= 2 * past) if past > 0 else 0.0
        rows.append(f)
    return pd.DataFrame(rows) if rows else None


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fams = [f for f in FAMILIES if not ONLY or f in ONLY.split(",")]
    for fam in fams:
        jobs = [(fam, s, iv) for s in FAMILIES[fam] for iv in INTERVALS]
        with Pool(PROCS) as pool:
            parts = [p for p in pool.map(series_rows, jobs) if p is not None]
        if parts:
            d = pd.concat(parts, ignore_index=True)
            d.to_pickle(OUT / f"{fam}.pkl.gz")
            print(f"{fam}: {len(d):,} rows from {len(parts)} series", flush=True)


# ------------------------------------------------------------------------------------------ report

def auc(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else float("nan")


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str], target: str) -> np.ndarray:
    from sklearn.ensemble import HistGradientBoostingClassifier
    m = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                       min_samples_leaf=200, random_state=0)
    x = train[cols].replace([np.inf, -np.inf], np.nan)
    m.fit(x, train[target])
    return m.predict_proba(test[cols].replace([np.inf, -np.inf], np.nan))[:, 1]


def incremental(test: pd.DataFrame, target: str, p0: np.ndarray, p1: np.ndarray, reps: int = 200):
    y = test[target].to_numpy()
    d = auc(y, p1) - auc(y, p0)
    days = (test["t"] // 86400).to_numpy()
    uniq = np.unique(days)
    by = {k: np.flatnonzero(days == k) for k in uniq}
    rng = np.random.default_rng(0)
    draws = []
    for _ in range(reps):
        idx = np.concatenate([by[k] for k in rng.choice(uniq, len(uniq))])
        a1, a0 = auc(y[idx], p1[idx]), auc(y[idx], p0[idx])
        if np.isfinite(a1) and np.isfinite(a0):
            draws.append(a1 - a0)
    draws = np.array(draws)
    lo, hi = (np.quantile(draws, [0.025, 0.975]) if len(draws) else (np.nan, np.nan))
    p = float((draws <= 0).mean()) if len(draws) else float("nan")
    return d, lo, hi, p, float(draws.std()) if len(draws) else float("nan")


def report() -> None:
    cells = []
    for fam in FAMILIES:
        path = OUT / f"{fam}.pkl.gz"
        if not path.exists():
            continue
        data = pd.read_pickle(path)  # this harness's own output, never external data
        for iv, g in data.groupby("iv"):
            g = g.sort_values("t").reset_index(drop=True)
            cut = g["t"].quantile(0.6)
            train, test = g[g["t"] < cut], g[g["t"] >= cut]
            mid = test["t"].median()
            print(f"\n== {fam} {iv}: {len(g):,} rows, test {len(test):,}", flush=True)
            for target in TARGETS:
                y = test[target].to_numpy()
                rate = y.mean()
                if train[target].sum() < 30 or y.sum() < 30:
                    print(f"  {target:6s} rate {rate:.3f} - too few events", flush=True)
                    continue
                p0 = fit_predict(train, test, BASE, target)
                a0 = auc(y, p0)
                singles = []
                for col in GROUPS["all"]:
                    a = auc(y, test[col].fillna(test[col].median()).to_numpy())
                    singles.append(f"{col} {a:.3f}")
                print(f"  {target:6s} rate {rate:.3f} | baseline AUC {a0:.3f}", flush=True)
                print(f"      alone: {' '.join(singles)}", flush=True)
                for name in ("tda", "tda_shape", "csd", "phys", "all"):
                    p1 = fit_predict(train, test, BASE + GROUPS[name], target)
                    d, lo, hi, pv, sd = incremental(test, target, p0, p1)
                    halves = []
                    for part in (test["t"] < mid, test["t"] >= mid):
                        yy = y[part.to_numpy()]
                        halves.append(auc(yy, p1[part.to_numpy()]) - auc(yy, p0[part.to_numpy()]))
                    passed = d >= 0.01 and lo > 0 and min(halves) > 0
                    cells.append({"family": fam, "iv": iv, "target": target, "group": name,
                                  "d": d, "lo": lo, "hi": hi, "p": pv, "sd": sd,
                                  "h1": halves[0], "h2": halves[1], "pass": passed})
                    print(f"      + {name:9s} {d:+.4f} [{lo:+.4f}, {hi:+.4f}] halves {halves[0]:+.4f} / "
                          f"{halves[1]:+.4f}{'  PASS' if passed else ''}", flush=True)
                # the killer question: topology beyond matched moments
                mt = train.copy()
                ms = test.copy()
                for m in MOMENTS:
                    qs = np.quantile(mt[m].dropna(), [1 / 3, 2 / 3])
                    mt[m + "_c"] = np.digitize(mt[m], qs)
                    ms[m + "_c"] = np.digitize(ms[m], qs)
                mcols = MOMENTS + [m + "_c" for m in MOMENTS]
                q0 = fit_predict(mt, ms, mcols, target)
                q1 = fit_predict(mt, ms, mcols + GROUPS["tda_shape"], target)
                d, lo, hi, pv, _ = incremental(ms, target, q0, q1)
                print(f"      moments only AUC {auc(y, q0):.3f} | + tda_shape {d:+.4f} [{lo:+.4f}, {hi:+.4f}]",
                      flush=True)
                cells.append({"family": fam, "iv": iv, "target": target, "group": "moments+tda_shape",
                              "d": d, "lo": lo, "hi": hi, "p": pv, "sd": np.nan, "h1": np.nan,
                              "h2": np.nan, "pass": False})
    c = pd.DataFrame(cells)
    if c.empty:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    c.to_csv(OUT / "cells.csv", index=False)
    # BH across the incremental cells (bootstrap p)
    inc = c[c["group"] != "moments+tda_shape"].copy()
    inc = inc[np.isfinite(inc["p"])].sort_values("p").reset_index(drop=True)
    m = len(inc)
    inc["bh"] = inc["p"] <= 0.05 * (np.arange(1, m + 1) / m)
    real = inc[~inc["family"].str.startswith("walks")]
    garch = inc[inc["family"] == "walks_garch"]
    print(f"\n{m} incremental cells; BH survivors: {int(inc['bh'].sum())} "
          f"(real {int(real['bh'].sum())}, GARCH walks {int(garch['bh'].sum())})", flush=True)
    print("pre-registered passes (d >= 0.01, CI > 0, both halves):", flush=True)
    for _, row in inc[inc["pass"]].iterrows():
        garch_same = garch[(garch["iv"] == row["iv"]) & (garch["target"] == row["target"])
                           & (garch["group"] == row["group"])]
        g = garch_same["d"].iloc[0] if len(garch_same) else np.nan
        print(f"  {row['family']:12s} {row['iv']:4s} {row['target']:6s} {row['group']:9s} "
              f"{row['d']:+.4f} [{row['lo']:+.4f}, {row['hi']:+.4f}] | GARCH walks same cell {g:+.4f}",
              flush=True)
    # deflation: best real t against the expected maximum of m null draws
    real = real.assign(tstat=real["d"] / real["sd"])
    if len(real):
        best = real.sort_values("tstat", ascending=False).iloc[0]
        from statistics import NormalDist
        nd = NormalDist()
        emax = (1 - 0.5772) * nd.inv_cdf(1 - 1 / m) + 0.5772 * nd.inv_cdf(1 - 1 / (m * math.e))
        print(f"deflation: best real cell {best['family']} {best['iv']} {best['target']} "
              f"{best['group']} t {best['tstat']:.2f} against E[max] over {m} cells {emax:.2f}", flush=True)


if __name__ == "__main__":
    report() if PART == "report" else run()
