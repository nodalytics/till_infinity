"""Ernest Chan's *Algorithmic Trading: Winning Strategies and Their Rationale*, on this desk.

The ideas the repo had not yet tested, from the book's methods (the PDF was not used). What it had:
pairs and co-movement (`comovement`), reversion to a moving average (`zma-ml`), weekend gaps
(`gaptrade`), carry (`carry`), news drift (`surprise`), the calendar (`calendar-returns`),
Bollinger and lagging triggers (`indicators`, `stophunt`) and stop width (`widestop`).

PART=regime   **Stationarity as a regime filter** - Chan's core claim: trade mean reversion where the
              series is mean-reverting and momentum where it trends. Production's zone touches (the
              Engine replay `indicators.py` saved in data/indicators) are split by the variance ratio
              VR(8) of the last 200 bars' log closes: mean-reverting VR < 0.9, trending VR > 1.1
              (pre-registered; the Hurst exponent and a Dickey-Fuller t are reported beside it).
              Fading should pay in the first, breaking in the second, beyond the same split on walks.
              Also Chan's claim that stops hurt mean reversion: the mean-reverting fades with a
              1-vol stop against the same fades held to the horizon.
PART=coint    **FX cross-rate cointegration with a Kalman hedge ratio** (Chan's ch. 3): AUDUSD/NZDUSD,
              EURUSD/GBPUSD, EURUSD/USDCHF, and the EURGBP triangle against EURUSD/GBPUSD, at 1h.
              The Kalman filter (delta 1e-4, Chan's; Ve the training block's residual variance,
              since his 1e-3 was for dollar prices) gives the hedge;
              enter at |z| > 1, exit at z = 0; every leg's spread charged. Out of sample: the static
              spread's Dickey-Fuller t and half-life, and the strategy's net Sharpe. Walks: pairs of
              independent walks we generate.
PART=tsmom    **Time-series momentum on daily bars** (Chan's ch. 6): the sign of the last L days'
              return (L = 21, 63, 126, 252), a 10%-a-year volatility target, rebalanced every 21
              days; FX, metals, crypto, and Deriv as markets; walks as the control. Net of costs,
              the crash check (monthly skew, worst month, drawdown), and Chan's claim that stops help
              momentum (a 2-sigma stop against the entry).
Roll-return / term-structure momentum needs futures or term data; the lab has none, so it is not
testable here. Kelly and constant-proportion sizing are applied in PART=report.

Pass bar (pre-registered): net Sharpe >= 0.5 out of sample (last 40%), positive in both halves of
it, Benjamini-Hochberg across every test, and no pass on walks. Costs are COST_V (fx 0.8, metals
0.16, crypto 0.5, Deriv and walks 0.15 in units of a 5-minute sigma), as elsewhere.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

PART = os.environ.get("PART", "report")
OUT = Path(os.environ.get("OUT", ".data/chan"))
IND = Path(os.environ.get("IND", ".data/indicators"))
COST_V = {"fx": 0.8, "metals": 0.16, "crypto": 0.5, "deriv": 0.15, "walks": 0.15}
DERIV = ("volatility", "boom", "crash", "jump", "step", "range", "dex", "drift", "spot")


def family(sym: str) -> str:
    s = sym.lower()
    if s.startswith("walk"):
        return "walks"
    if any(w in s for w in DERIV):
        return "deriv"
    if s.startswith(("xau", "xag")):
        return "metals"
    if s.startswith(("btc", "eth", "sol")):
        return "crypto"
    return "fx"


def load(sym: str, iv: str) -> pd.DataFrame | None:
    try:
        return spikerisk.load(None, sym, "SEQLAB", iv)
    except (ValueError, FileNotFoundError):
        return None


def tstat(v: np.ndarray) -> float:
    v = v[np.isfinite(v)]
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))) if len(v) > 2 else float("nan")


def pvalue(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2)) if np.isfinite(t) else 1.0


# ------------------------------------------------------------------ stationarity statistics

def vr(logp: np.ndarray, q: int = 8) -> float:
    r1 = np.diff(logp)
    rq = logp[q:] - logp[:-q]
    v1 = r1.var(ddof=1)
    return float(rq.var(ddof=1) / (q * v1)) if v1 > 0 else float("nan")


def hurst(logp: np.ndarray) -> float:
    lags = np.array([1, 2, 4, 8, 16])
    sd = np.array([np.std(logp[k:] - logp[:-k]) for k in lags])
    ok = sd > 0
    return float(np.polyfit(np.log(lags[ok]), np.log(sd[ok]), 1)[0]) if ok.sum() > 2 else float("nan")


def dickey_fuller(y: np.ndarray) -> tuple[float, float]:
    """(t on y[t-1] in dy = a + b y[t-1] + e, half-life -ln 2 / ln(1 + b)); no lags, as Chan's."""
    dy, lag = np.diff(y), y[:-1]
    x = np.column_stack([np.ones_like(lag), lag])
    beta, *_ = np.linalg.lstsq(x, dy, rcond=None)
    resid = dy - x @ beta
    s2 = resid @ resid / max(len(dy) - 2, 1)
    cov = s2 * np.linalg.inv(x.T @ x)
    b = beta[1]
    half = -math.log(2) / math.log(1 + b) if -1 < b < 0 else float("inf")
    return float(b / math.sqrt(cov[1, 1])), float(half)


# ------------------------------------------------------------------ PART=regime

def regime() -> None:
    import indicators as ind

    frames: dict[tuple[str, str], tuple[np.ndarray, dict]] = {}
    symbols = {s.lower(): s for s in ind.FAMILY} | {f"walk_{i}": f"walk_{i}" for i in range(6)}
    rows = []
    for name in ("real", "deriv", "walks"):
        path = IND / f"{name}.pkl.gz"
        if not path.exists():
            print(f"  missing {path}", flush=True)
            continue
        df = pd.read_pickle(path)
        rows.append(df[(df["kind"] == "zone") & (df["rule"] == "touch")])
    touches = pd.concat(rows, ignore_index=True)
    print(f"{len(touches):,} zone-touch rows (both horizons)", flush=True)
    out = []
    for (feed, iv), g in touches.groupby(["feed", "interval"]):
        sym = symbols.get(feed)
        if sym is None:
            continue
        key = (sym, iv)
        if key not in frames:
            df = ind.frame(sym, iv)
            if df is None or len(df) < 400:
                continue
            frames[key] = (df["ts"].to_numpy(), ind.indicators(df) | {
                "high": df["high"].to_numpy(), "low": df["low"].to_numpy()})
        ts, x = frames[key]
        logp = np.log(x["close"])
        for row in g.itertuples(index=False):
            i = int(np.searchsorted(ts, row.time))
            if i < 200 or i >= len(ts) or ts[i] != row.time:
                continue
            w = logp[i - 199:i + 1]
            h = int(row.h)
            stop_net = held_net = float("nan")
            if h == 20 and i + h < len(ts) and np.isfinite(x["vol"][i]) and x["vol"][i] > 0:
                s, c0, v = int(row.s), x["close"][i], x["vol"][i]
                stop = c0 * math.exp(-s * v)  # a 1-vol stop against the fade
                exit_price = x["close"][i + h]
                for j in range(i + 1, i + h + 1):
                    if (s > 0 and x["low"][j] <= stop) or (s < 0 and x["high"][j] >= stop):
                        exit_price = stop
                        break
                stop_net = s * math.log(exit_price / c0) / v - row.cost
                held_net = row.net
            out.append({
                "family": family(sym), "feed": feed, "interval": iv, "time": row.time, "h": h,
                "fade": row.net, "brk": -row.gross - row.cost, "vr": vr(w), "hurst": hurst(w),
                "df": dickey_fuller(w)[0], "stop": stop_net, "held": held_net,
            })
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out).to_pickle(OUT / "regime.pkl.gz")
    print(f"regime: {len(out):,} rows written", flush=True)


# ------------------------------------------------------------------ PART=coint

PAIRS = [("AUDUSD", "NZDUSD"), ("EURUSD", "GBPUSD"), ("EURUSD", "USDCHF"), ("EURGBP", "EURUSD/GBPUSD")]


def walk_close(seed: int, n: int, scale: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.standard_t(3, n) * scale))


def kalman(y: np.ndarray, x: np.ndarray, delta: float = 1e-4, ve: float = 1e-3):
    """Chan's Kalman hedge: state (beta, alpha) a random walk; returns beta, e, sqrt(Q)."""
    n = len(y)
    beta, e, q = np.zeros((n, 2)), np.zeros(n), np.ones(n)
    # Chan's delta and Ve (1e-3) are for dollar prices; keep his ratio of state to observation
    # noise and scale both to this series' residual variance.
    vw = delta / (1 - delta) * (ve / 1e-3) * np.eye(2)
    theta, p = np.zeros(2), np.zeros((2, 2))
    for t in range(n):
        f = np.array([x[t], 1.0])
        r = p + vw
        yhat = f @ theta
        q[t] = f @ r @ f + ve
        e[t] = y[t] - yhat
        k = r @ f / q[t]
        theta = theta + k * e[t]
        p = r - np.outer(k, f) @ r
        beta[t] = theta
    return beta, e, np.sqrt(q)


def pair_series(a: str, b: str):
    """Aligned log closes (y, x) at 1h, and each leg's cost in log return; the triangle's x is the
    synthetic cross with two legs' cost."""
    def one(sym):
        df = load(sym, "1h")
        return None if df is None else df.set_index("ts")["close"]
    if "/" in b:
        u, v = b.split("/")
        su, sv, sy = one(u), one(v), one(a)
        if su is None or sv is None or sy is None:
            return None
        df = pd.concat([sy, su, sv], axis=1, join="inner").dropna()
        y, x = np.log(df.iloc[:, 0].to_numpy()), np.log(df.iloc[:, 1].to_numpy() / df.iloc[:, 2].to_numpy())
        legs_x = 2
    else:
        sy, sx = one(a), one(b)
        if sy is None or sx is None:
            return None
        df = pd.concat([sy, sx], axis=1, join="inner").dropna()
        y, x = np.log(df.iloc[:, 0].to_numpy()), np.log(df.iloc[:, 1].to_numpy())
        legs_x = 1
    return df.index.to_numpy(), y, x, legs_x


def trade_spread(y, x, legs_x, fam="fx", cut=None):
    # Chan's Ve (1e-3) was set for ETF prices in dollars; on log prices the residual is ~100x
    # smaller and z never reaches 1. So Ve is the static hedge's residual variance on the training
    # block, measured there and fixed before the test.
    cut = int(0.6 * len(y)) if cut is None else cut
    bb = np.polyfit(x[:cut], y[:cut], 1)
    ve = float(np.var(y[:cut] - (bb[0] * x[:cut] + bb[1])))
    beta, e, sq = kalman(y, x, ve=ve)
    z = e / sq
    pos = np.zeros(len(y))
    for t in range(1, len(y)):
        prev = pos[t - 1]
        if prev == 0:
            pos[t] = -1.0 if z[t] > 1 else (1.0 if z[t] < -1 else 0.0)
        elif (prev > 0 and z[t] >= 0) or (prev < 0 and z[t] <= 0):
            pos[t] = 0.0
        else:
            pos[t] = prev
    dy, dx = np.diff(y), np.diff(x)
    b = beta[:-1, 0]
    pnl = pos[:-1] * (dy - b * dx)
    sd1h = np.nanstd(dy)
    leg = COST_V[fam] * sd1h / math.sqrt(12)  # a 5-minute sigma from the hourly one
    cost = np.abs(np.diff(pos)) * leg * (1 + legs_x * np.abs(b))
    return pnl - cost, pnl, pos


def coint() -> None:
    rows = []
    cases = [(f"{a}~{b}", pair_series(a, b)) for a, b in PAIRS]
    for k in range(4):  # our walks: two independent series, so any "cointegration" is noise
        n = 40_000
        a, b = walk_close(100 + k, n, 0.0012), walk_close(200 + k, n, 0.0012)
        cases.append((f"walks_{k}", (np.arange(n), np.log(a), np.log(b), 1)))
    for name, got in cases:
        if got is None:
            print(f"  skip {name}", flush=True)
            continue
        ts, y, x, legs = got
        fam = "walks" if name.startswith("walks") else "fx"
        cut = int(0.6 * len(y))
        # the static spread: hedge fitted on the first 60%, stationarity judged on the last 40%
        bb = np.polyfit(x[:cut], y[:cut], 1)
        spread = y[cut:] - (bb[0] * x[cut:] + bb[1])
        t_df, half = dickey_fuller(spread)
        net, gross, pos = trade_spread(y, x, legs, fam, cut)
        test = net[cut:]
        halves = np.array_split(test, 2)
        ann = math.sqrt(24 * 260)
        sh = lambda v: float(v.mean() / v.std() * ann) if v.std() > 0 else float("nan")  # noqa: E731
        rows.append({"case": name, "family": fam, "n": len(y), "df_t": t_df, "half_life_h": half,
                     "sharpe": sh(test), "sharpe_gross": sh(gross[cut:]), "h1": sh(halves[0]),
                     "h2": sh(halves[1]), "t": tstat(test), "in_market": float(np.mean(pos[cut:] != 0)),
                     "trades": int(np.sum(np.abs(np.diff(pos[cut:])) > 0) / 2)})
        print(f"  {name:22s} DF t {t_df:+.2f} (5% crit -2.86) half-life {half:,.0f}h | net Sharpe "
              f"{rows[-1]['sharpe']:+.2f} (gross {rows[-1]['sharpe_gross']:+.2f}) halves "
              f"{rows[-1]['h1']:+.2f}/{rows[-1]['h2']:+.2f} | trades {rows[-1]['trades']}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_pickle(OUT / "coint.pkl.gz")


# ------------------------------------------------------------------ PART=tsmom

def daily_symbols() -> list[str]:
    root = Path(os.environ.get("SEQLAB", ".data/seqlab"))
    return sorted(p.name[:-7] for p in root.glob("*.1d.npz"))


def tsmom_one(close: np.ndarray, fam: str, lookback: int, hold: int = 21, stop_sigmas: float = 0.0):
    r = np.diff(np.log(close))
    sig = pd.Series(r).ewm(span=60, adjust=False).std().to_numpy()
    n = len(r)
    w = np.zeros(n)
    entry, target = 0, 0.0
    for t in range(lookback, n):
        if (t - lookback) % hold == 0:
            past = math.log(close[t] / close[t - lookback])
            target = (np.sign(past) * 0.10 / (sig[t - 1] * math.sqrt(260))) if sig[t - 1] > 0 else 0.0
            target = float(np.clip(target, -5, 5))
            entry = t
        w[t] = target
        if stop_sigmas > 0 and target != 0:
            move = math.log(close[t] / close[entry])
            if np.sign(target) * move < -stop_sigmas * sig[entry - 1] * math.sqrt(max(t - entry, 1)):
                target = 0.0
                w[t] = 0.0
    pnl = w[:-1] * r[1:]
    c5 = sig[1:] / math.sqrt(288)
    cost = np.abs(np.diff(w)) * COST_V[fam] * c5
    return pnl - cost


def tsmom() -> None:
    syms = daily_symbols()
    rows = []
    series = {}
    for s in syms:
        df = load(s, "1d")
        if df is not None and len(df) > 600:
            series[s] = df["close"].to_numpy()
    for k in range(8):  # walks: daily t(3), 1% a day
        series[f"walk_{k}"] = walk_close(300 + k, 2500, 0.01)
    print(f"{len(series)} daily series", flush=True)
    for stop in (0.0, 2.0):
        for lookback in (21, 63, 126, 252):
            by_fam: dict[str, list[np.ndarray]] = {}
            for s, close in series.items():
                net = tsmom_one(close, family(s), lookback, stop_sigmas=stop)
                by_fam.setdefault(family(s), []).append(net)
            for fam, lst in by_fam.items():
                m = min(len(v) for v in lst)
                port = np.nanmean(np.vstack([v[-m:] for v in lst]), axis=0)  # the most recent m days
                cut = int(0.6 * m)
                test = port[cut:]
                halves = np.array_split(test, 2)
                sh = lambda v: float(np.nanmean(v) / np.nanstd(v) * math.sqrt(260)) if np.nanstd(v) > 0 else float("nan")  # noqa: E731
                monthly = np.add.reduceat(test, np.arange(0, len(test), 21))
                eq = np.cumsum(test)
                rows.append({"family": fam, "lookback": lookback, "stop": stop, "n_inst": len(lst),
                             "days": m, "sharpe": sh(test), "h1": sh(halves[0]), "h2": sh(halves[1]),
                             "t": tstat(test), "skew_m": float(pd.Series(monthly).skew()),
                             "worst_m": float(monthly.min()), "maxdd": float((eq - np.maximum.accumulate(eq)).min())})
                print(f"  L={lookback:3d} stop {stop:.0f} {fam:7s} n={len(lst):2d} days {m:,} | Sharpe "
                      f"{rows[-1]['sharpe']:+.2f} halves {rows[-1]['h1']:+.2f}/{rows[-1]['h2']:+.2f} | "
                      f"monthly skew {rows[-1]['skew_m']:+.2f} worst {rows[-1]['worst_m']:+.3f} "
                      f"maxDD {rows[-1]['maxdd']:+.3f}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_pickle(OUT / "tsmom.pkl.gz")


# ------------------------------------------------------------------ PART=report

def bh(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    order = np.argsort(p)
    ranked = p[order] * len(p) / (np.arange(len(p)) + 1)
    passed = np.zeros(len(p), bool)
    ok = np.flatnonzero(ranked <= q)
    if len(ok):
        passed[order[: ok.max() + 1]] = True
    return passed


def report() -> None:
    tests = []
    path = OUT / "regime.pkl.gz"
    if path.exists():
        d = pd.read_pickle(path)
        d["regime"] = np.where(d["vr"] < 0.9, "revert", np.where(d["vr"] > 1.1, "trend", "neutral"))
        print("REGIME FILTER - zone touches split by VR(8) of the last 200 bars (net, vol units)")
        cut = d["time"].quantile(0.6)
        for (fam, h), g in d.groupby(["family", "h"]):
            shares = g["regime"].value_counts(normalize=True)
            line = []
            for reg, col in (("revert", "fade"), ("trend", "brk")):
                gg = g[g["regime"] == reg]
                other = g[g["regime"] != reg]
                diff = gg[col].mean() - other[col].mean()
                t = (diff / math.sqrt(gg[col].var() / len(gg) + other[col].var() / len(other))
                     if len(gg) > 20 and len(other) > 20 else float("nan"))
                test = gg[gg["time"] >= cut][col]
                halves = [x[col].mean() for x in np.array_split(gg[gg["time"] >= cut].sort_values("time"), 2)]
                line.append(f"{col} in {reg} {gg[col].mean():+.3f} (vs rest {diff:+.3f}, t {t:+.1f}; test "
                            f"{test.mean():+.3f}, halves {halves[0]:+.3f}/{halves[1]:+.3f})")
                if fam != "walks":
                    tests.append((f"regime {fam} H={h} {col} in {reg}", pvalue(t), diff, fam))
            corr_h = g["vr"].corr(g["hurst"])
            print(f"  {fam:7s} H={h:2d} n={len(g):6,} revert {shares.get('revert', 0):.0%} trend "
                  f"{shares.get('trend', 0):.0%} | " + " | ".join(line) + f" | corr(VR, Hurst) {corr_h:+.2f}")
        s = d[(d["h"] == 20) & d["stop"].notna()]
        print("\n  Chan: stops hurt mean reversion - fades in the reverting regime, H=20, net vol units")
        for fam, g in s[s["regime"] == "revert"].groupby("family"):
            print(f"    {fam:7s} n={len(g):6,} held {g['held'].mean():+.3f} | 1-vol stop {g['stop'].mean():+.3f} "
                  f"| stop - held {g['stop'].mean() - g['held'].mean():+.3f} (t {tstat((g['stop'] - g['held']).to_numpy()):+.1f})")
    path = OUT / "coint.pkl.gz"
    if path.exists():
        c = pd.read_pickle(path)
        print("\nCOINTEGRATION (Kalman hedge, |z| > 1 in, z = 0 out; test = last 40%)")
        print(c.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))
        for r in c.itertuples():
            if r.family != "walks":
                tests.append((f"coint {r.case}", pvalue(r.t), r.sharpe, r.family))
    path = OUT / "tsmom.pkl.gz"
    if path.exists():
        m = pd.read_pickle(path)
        print("\nTSMOM (daily, 10% vol target, 21-day hold; test = last 40%)")
        print(m.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))
        for r in m[m["stop"] == 0].itertuples():
            if r.family != "walks":
                tests.append((f"tsmom {r.family} L={r.lookback}", pvalue(r.t), r.sharpe, r.family))
    if tests:
        p = np.array([t[1] for t in tests])
        passed = bh(p)
        print(f"\nBH across {len(tests)} tests: {int(passed.sum())} pass at q = 0.05")
        for (name, pv, eff, _), ok in zip(tests, passed, strict=True):
            if ok:
                print(f"  {name}: p {pv:.2g}, effect {eff:+.3f}")
    # Kelly on the desk's own edge: triage.md's per-strategy net R, per-trade sd about 1R
    print("\nKELLY on the desk's edges: f* = mean / variance of per-trade R (triage.md, sd about 1R)")
    for name, mean in (("best strategy (opportunity)", -0.050), ("thesis-only", -0.108),
                       ("worst (inverse)", -0.392)):
        print(f"  {name:28s} mean {mean:+.3f}R -> f* {mean / 1.0:+.3f} of capital per 1R: size zero")


if __name__ == "__main__":
    {"regime": regime, "coint": coint, "tsmom": tsmom}.get(PART, report)()
