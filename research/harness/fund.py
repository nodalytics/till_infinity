"""Could this desk's risk forecasts run a better volatility-managed fund than the standard recipe?

The desk has found no return edge (research/docs/triage.md: every strategy's gross is about 0 and
none beats random selection; indicators, stophunt, confirm, chan, calendar-returns and agents are
all null). What survived is **risk forecasting**: the shock forecaster, the calibrated envelope,
the vol clock. A fund does not need a return edge if it can deliver a known asset class's premium
with better risk control, which is the volatility-managed portfolio (Moreira & Muir 2017; Harvey
et al. 2018; Cederburg et al. 2020 for the out-of-sample critique). So the question here is
narrow and fund-shaped:

  Do our forecasts, fed through production code, run a better volatility-targeted portfolio of
  fund-investable assets than the standard EWMA recipe?

Assets: daily ETFs (yfinance, adjusted closes and OHLC) - SPY, EFA, EEM (equity), TLT, IEF
(bonds), GLD (gold), DBC (commodities), VNQ (property) - from 2006. Not CFDs and not Deriv
synthetics: a regulated fund holds investable assets, and a broker's synthetic has a house edge by
construction (research/docs/deriv-payouts.md).

Sigma forecasts, each known at the close of day t and used for day t+1:
  ewma      RiskMetrics, lambda 0.94, close-to-close (the standard recipe)
  tr        production `Ranges` EWMA of true range - the desk's measured best near-term forecast
            (research/docs/volatility-estimators.md)
  env       production `Envelope` (5-day, AgACI) width, as a next-day sd; `tr` until warm
Each forecast is put on the return scale by a causal expanding median of |r| / sigma, so no
forecast wins by being biased high or low.

Strategies (daily, next-day returns; 2 bp per unit turnover; cash earns the 3-month T-bill (FRED
DTB3) and leverage above 1 pays it plus 0.5%; gross capped at 2):
  bh        buy and hold (each asset; 60/40 SPY/TLT and equal weight, monthly rebalance)
  vt:<f>    single-asset vol targeting to 10% with forecast f
  rp:<f>    inverse-vol risk parity across all assets, monthly weights, then vol-targeted to 10%
            on the portfolio's own forecast
  hrp:<f>   hierarchical risk parity (Lopez de Prado 2016) on trailing 252-day correlation,
            monthly, vol-targeted the same way
  shock     the S&P sleeve de-risked by half on days the production shock forecaster, run on the
            broker's hourly US_SP_500 (2024-2026 only), reads lift >= 3 at the US close

Controls: GARCH(1,1) walks we generate (t(5) innovations, alpha 0.09, beta 0.90, 16% vol, 7%
drift), where vol targeting helps Sharpe mechanically, and iid t(5) walks at the same vol, where it
should not. Each gets bh, vt:ewma, vt:tr, vt:env.

Pre-registered pass bar: vt/rp/hrp with our forecasts (tr or env) beats the same strategy with ewma
by Sharpe >= 0.1 or by max drawdown >= 20% relative, in both halves, with a Deflated Sharpe Ratio
> 0.95 over every variant tried.

Run on the lab:  PART=data python research/harness/fund.py; then PART=run.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

OUT = Path(os.environ.get("OUT", ".data/fund"))
PART = os.environ.get("PART", "run")
ETFS = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]
START = "2006-03-01"
TARGET, CAP, COST_BP, BORROW = 0.10, 2.0, 2.0, 0.005
FORECASTS = ("ewma", "tr", "env")
SEED = 11


# ------------------------------------------------------------------------------ data


def _curl(url: str, tries: int = 5) -> str:
    last = ""
    for attempt in range(tries):
        got = subprocess.run(["curl", "-s", "-f", "-m", "60", url], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout:
            return got.stdout
        last = got.stderr or f"curl exit {got.returncode}"
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def data() -> None:
    import yfinance as yf

    OUT.mkdir(parents=True, exist_ok=True)
    got = yf.download(ETFS, start=START, progress=False, auto_adjust=True, group_by="ticker")
    frames = {}
    for t in ETFS:
        d = got[t][["Open", "High", "Low", "Close"]].dropna()
        d.columns = ["open", "high", "low", "close"]
        frames[t] = d
        print(f"{t}: {len(d):,} days {d.index[0]:%Y-%m-%d} to {d.index[-1]:%Y-%m-%d}", flush=True)
    pd.to_pickle(frames, OUT / "etfs.pkl")
    text = _curl("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3")
    (OUT / "dtb3.csv").write_text(text)
    print("DTB3 saved", flush=True)


def load() -> tuple[dict[str, pd.DataFrame], pd.Series]:
    # Written by `data()` above on the same machine - trusted, not third-party input.
    frames = pd.read_pickle(OUT / "etfs.pkl")
    bill = pd.read_csv(OUT / "dtb3.csv", index_col=0, parse_dates=True).iloc[:, 0]
    bill = pd.to_numeric(bill, errors="coerce").ffill() / 100.0
    return frames, bill


# ------------------------------------------------------------------------------ forecasts


def forecasts(d: pd.DataFrame) -> pd.DataFrame:
    """Daily sd forecasts known at each close, all on the return scale (causal calibration)."""
    from till_infinity.structures.vol import envelope as ev
    from till_infinity.structures.vol.ranges import Ranges

    r = np.log(d["close"]).diff()
    ewma_var = r.pow(2).ewm(alpha=0.06, adjust=False).mean()
    out = pd.DataFrame(index=d.index)
    out["r"] = r
    out["ewma"] = np.sqrt(ewma_var)
    ranges, env = Ranges(), ev.Envelope(horizon=5)
    tr, width = [], []
    for o, h, lo, c in zip(d["open"], d["high"], d["low"], d["close"], strict=True):
        ranges.observe(float(o), float(h), float(lo), float(c))
        unit = ranges.ewma_tr_bps / 10_000
        tr.append(unit if unit > 0 else np.nan)
        if unit > 0:
            env.observe(float(c), unit)
        if unit > 0 and env.warm:
            q10, _, q90 = env.quote
            width.append((q90 - q10) / (2 * 1.2816) * unit / math.sqrt(5))
        else:
            width.append(np.nan)
    out["tr"] = tr
    out["env"] = pd.Series(width, index=d.index).fillna(out["tr"])
    # Causal calibration onto the return scale: median |r_{t+1}| / f_t over everything resolved.
    for f in FORECASTS:
        ratio = (r.abs().shift(-1) / out[f]).replace([np.inf, -np.inf], np.nan)
        scale = ratio.shift(1).expanding(min_periods=120).median() / 0.6745
        out[f] = out[f] * scale
    return out


# ------------------------------------------------------------------------------ portfolios


def run_weights(w: pd.DataFrame, rets: pd.DataFrame, bill: pd.Series) -> pd.Series:
    """Daily net return of weights set at close t, held over t+1, with costs and financing."""
    w = w.reindex(rets.index).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    gross = (held * rets.fillna(0.0)).sum(axis=1)
    lev = held.abs().sum(axis=1)
    cash = bill.reindex(rets.index).ffill().fillna(0.0) / 252
    carry = np.where(lev <= 1, (1 - lev) * cash, -(lev - 1) * (cash + BORROW / 252))
    turn = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).shift(1).fillna(0.0)
    return gross + carry - turn * COST_BP / 10_000


def target(sigma: pd.Series) -> pd.Series:
    return (TARGET / math.sqrt(252) / sigma).clip(upper=CAP)


def monthly(w: pd.DataFrame) -> pd.DataFrame:
    """Hold weights set at each month's last day for the month."""
    keep = w.index.to_series().dt.to_period("M")
    return w.groupby(keep).transform("last").where(keep != keep.shift(-1)).ffill()


def hrp_weights(cov: np.ndarray, corr: np.ndarray) -> np.ndarray:
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.spatial.distance import squareform

    dist = np.sqrt(np.clip((1 - corr) / 2, 0, None))
    np.fill_diagonal(dist, 0)
    order = leaves_list(linkage(squareform(dist, checks=False), "single"))
    w = np.ones(len(order))
    clusters = [list(order)]
    while clusters:
        nxt = []
        for c in clusters:
            if len(c) < 2:
                continue
            half = len(c) // 2
            a, b = c[:half], c[half:]

            def var(idx):
                sub = cov[np.ix_(idx, idx)]
                iv = 1 / np.diag(sub)
                iv /= iv.sum()
                return float(iv @ sub @ iv)

            va, vb = var(a), var(b)
            alpha = 1 - va / (va + vb)
            w[a] *= alpha
            w[b] *= 1 - alpha
            nxt += [a, b]
        clusters = nxt
    return w / w.sum()


def portfolios(frames, bill) -> dict[str, pd.Series]:
    fc = {t: forecasts(d) for t, d in frames.items()}
    idx = sorted(set.intersection(*(set(f.index) for f in fc.values())))
    rets = pd.DataFrame({t: np.exp(fc[t]["r"]) - 1 for t in fc}).reindex(idx)
    out: dict[str, pd.Series] = {}
    for t in fc:
        one = pd.DataFrame({t: 1.0}, index=idx)
        out[f"bh:{t}"] = run_weights(one, rets[[t]], bill)
        for f in FORECASTS:
            s = fc[t][f].reindex(idx)
            out[f"vt:{f}:{t}"] = run_weights(pd.DataFrame({t: target(s)}), rets[[t]], bill)
    six = pd.DataFrame({"SPY": 0.6, "TLT": 0.4}, index=idx)
    out["bh:60/40"] = run_weights(monthly(six), rets, bill)
    out["bh:equal"] = run_weights(monthly(pd.DataFrame(1 / len(fc), index=idx, columns=list(fc))), rets, bill)
    for f in FORECASTS:
        sig = pd.DataFrame({t: fc[t][f].reindex(idx) for t in fc})
        base = (1 / sig).div((1 / sig).sum(axis=1), axis=0)
        port = (base * rets).sum(axis=1)
        pvol = np.sqrt(port.pow(2).ewm(alpha=0.06, adjust=False).mean())
        scale = target(pvol)
        out[f"rp:{f}"] = run_weights(monthly(base).mul(scale, axis=0), rets, bill)
        # HRP on trailing 252-day correlation, covariance scaled by the forecast's vols
        hw = pd.DataFrame(np.nan, index=idx, columns=list(fc))
        ends = rets.index.to_series().groupby(rets.index.to_period("M")).last()
        for end in ends:
            i = rets.index.get_loc(end)
            if i < 252:
                continue
            window = rets.iloc[i - 252 : i + 1].dropna()
            corr = window.corr().to_numpy()
            vols = sig.loc[end].to_numpy()
            if not np.isfinite(vols).all() or not np.isfinite(corr).all():
                continue
            cov = corr * np.outer(vols, vols)
            hw.loc[end] = hrp_weights(cov, corr)
        hw = hw.ffill()
        hport = (hw * rets).sum(axis=1)
        hvol = np.sqrt(hport.pow(2).ewm(alpha=0.06, adjust=False).mean())
        out[f"hrp:{f}"] = run_weights(hw.mul(target(hvol), axis=0), rets, bill)
    return out


def shock_overlay(frames, bill) -> dict[str, pd.Series]:
    """SPY vol-targeted (tr), de-risked by half the day after the shock forecaster's lift >= 3 at the
    US close, from the broker's hourly US_SP_500 (2024-2026)."""
    from till_infinity.structures.learning import shocks as sh

    path = Path(os.environ.get("CARRY", os.path.expanduser("~/till_infinity/data/carry"))) / "US_SP_500.1h.csv"
    if not path.exists():
        return {}
    h = pd.read_csv(path)
    model = sh.Shocks()
    flags = {}
    for t, hi, lo, c in zip(h["time"], h["high"], h["low"], h["close"], strict=True):
        model.observe("us_sp_500", "1h", 3600.0, float(t) + 3600, float(hi), float(lo), float(c))
        got = model.reading("us_sp_500", "1h")
        stamp = pd.Timestamp(float(t) + 3600, unit="s", tz="UTC").tz_convert("America/New_York")
        if got and stamp.hour == 16:
            flags[stamp.normalize().tz_localize(None)] = got.get("shock_lift", 0.0) >= sh.CARD_LIFT
    flag = pd.Series(flags).sort_index()
    fc = forecasts(frames["SPY"])
    idx = fc.index[(fc.index >= flag.index.min()) & (fc.index <= flag.index.max())]
    rets = pd.DataFrame({"SPY": np.exp(fc["r"]) - 1}).reindex(idx)
    base = target(fc["tr"].reindex(idx))
    cut = base * np.where(flag.reindex(idx).fillna(False).astype(bool), 0.5, 1.0)
    return {
        "shock:off": run_weights(pd.DataFrame({"SPY": base}), rets, bill),
        "shock:on": run_weights(pd.DataFrame({"SPY": cut}), rets, bill),
        "_flag_rate": pd.Series([flag.mean()]),
    }


# ------------------------------------------------------------------------------ walks


def walks(kind: str, n: int = 20, days: int = 5000) -> dict[str, list[dict]]:
    rng = np.random.default_rng(SEED + (0 if kind == "garch" else 1))
    rows: dict[str, list[dict]] = {}
    daily_vol, drift = 0.16 / math.sqrt(252), 0.07 / 252
    for _ in range(n):
        z = rng.standard_t(5, days) / math.sqrt(5 / 3)
        if kind == "garch":
            alpha, beta = 0.09, 0.90
            omega = daily_vol**2 * (1 - alpha - beta)
            var, r = daily_vol**2, np.empty(days)
            for i in range(days):
                r[i] = math.sqrt(var) * z[i]
                var = omega + alpha * r[i] ** 2 + beta * var
        else:
            r = daily_vol * z
        r = r + drift
        close = 100 * np.exp(np.cumsum(r))
        sub = rng.standard_normal((days, 8)) * (np.abs(r)[:, None] / 2 + daily_vol / 4) / math.sqrt(8)
        path = np.cumsum(sub, axis=1)
        opn = np.r_[100.0, close[:-1]]
        hi = np.maximum(np.maximum(opn, close), opn * np.exp(path.max(axis=1).clip(min=0)))
        lo = np.minimum(np.minimum(opn, close), opn * np.exp(path.min(axis=1).clip(max=0)))
        idx = pd.bdate_range("2000-01-03", periods=days)
        d = pd.DataFrame({"open": opn, "high": hi, "low": lo, "close": close}, index=idx)
        fc = forecasts(d)
        rets = pd.DataFrame({"x": np.exp(fc["r"]) - 1})
        zero = pd.Series(0.0, index=idx)
        rows.setdefault("bh", []).append(stats(run_weights(pd.DataFrame({"x": 1.0}, index=idx), rets, zero)))
        for f in FORECASTS:
            w = pd.DataFrame({"x": target(fc[f])})
            rows.setdefault(f"vt:{f}", []).append(stats(run_weights(w, rets, zero)))
    return rows


# ------------------------------------------------------------------------------ scoring


def stats(r: pd.Series) -> dict[str, float]:
    r = r.dropna()
    r = r[r.index >= r.index[0] + pd.Timedelta(days=400)] if len(r) > 600 else r  # past warm-up
    if len(r) < 60 or r.std() == 0:
        return {"sharpe": float("nan"), "ann": float("nan"), "vol": float("nan"), "maxdd": float("nan")}
    wealth = (1 + r).cumprod()
    dd = (wealth / wealth.cummax() - 1).min()
    ann = wealth.iloc[-1] ** (252 / len(r)) - 1
    return {
        "sharpe": float(r.mean() / r.std() * math.sqrt(252)),
        "ann": float(ann),
        "vol": float(r.std() * math.sqrt(252)),
        "maxdd": float(dd),
        "calmar": float(ann / abs(dd)) if dd < 0 else float("nan"),
        "skew": float(r.skew()),
        "kurt": float(r.kurt() + 3),
        "n": len(r),
    }


def episode(r: pd.Series, start: str, end: str) -> float:
    part = r[(r.index >= start) & (r.index <= end)]
    return float((1 + part).prod() - 1) if len(part) else float("nan")


def block_boot_diff(a: pd.Series, b: pd.Series, n: int = 1000, block: int = 20) -> tuple[float, float]:
    """95% interval for Sharpe(a) - Sharpe(b), stationary blocks of `block` days."""
    x = pd.concat([a, b], axis=1).dropna().to_numpy()
    rng = np.random.default_rng(SEED)
    m = len(x)
    out = []
    for _ in range(n):
        starts = rng.integers(0, m, m // block + 1)
        idx = np.concatenate([np.arange(s, s + block) % m for s in starts])[:m]
        s = x[idx]
        sh = s.mean(0) / s.std(0) * math.sqrt(252)
        out.append(sh[0] - sh[1])
    return tuple(np.quantile(out, [0.025, 0.975]))


def deflated_sharpe(r: pd.Series, trials_sr: np.ndarray) -> float:
    """Bailey & Lopez de Prado (2014): P(true Sharpe > the best expected from `len(trials_sr)` noise
    trials), with the observed skew and kurtosis. Daily units inside."""
    from scipy.stats import norm

    r = r.dropna()
    n = len(r)
    sr = r.mean() / r.std()
    g3, g4 = r.skew(), r.kurt() + 3
    trials = trials_sr / math.sqrt(252)
    v = np.nanvar(trials)
    k = len(trials)
    emc = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - emc) * norm.ppf(1 - 1 / k) + emc * norm.ppf(1 - 1 / (k * math.e)))
    denom = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    return float(norm.cdf((sr - sr0) * math.sqrt(n - 1) / denom))


def fmt(s: dict) -> str:
    return (f"Sharpe {s['sharpe']:+.2f} | ann {s['ann'] * 100:+.1f}% vol {s['vol'] * 100:.1f}% | "
            f"maxDD {s['maxdd'] * 100:.1f}% calmar {s.get('calmar', float('nan')):+.2f} | "
            f"skew {s.get('skew', float('nan')):+.2f}")


def run() -> None:
    frames, bill = load()
    series = portfolios(frames, bill)
    shock = shock_overlay(frames, bill)
    flag_rate = float(shock.pop("_flag_rate").iloc[0]) if "_flag_rate" in shock else float("nan")
    series.update(shock)
    names = sorted(series)
    first = min(s.dropna().index[0] for s in series.values())
    last = max(s.dropna().index[-1] for s in series.values())
    mid = first + (last - first) / 2
    print(f"FUND - {len(frames)} ETFs, {first:%Y-%m-%d} to {last:%Y-%m-%d}; halves split {mid:%Y-%m-%d}")
    print(f"target {TARGET:.0%}, cap {CAP}x, cost {COST_BP} bp per unit turnover, borrow bill+{BORROW:.1%}\n")
    table = {}
    for k in names:
        r = series[k]
        whole, h1, h2 = stats(r), stats(r[r.index < mid]), stats(r[r.index >= mid])
        table[k] = (whole, h1, h2)
        turn = ""
        print(f"  {k:18s} {fmt(whole)} | halves Sharpe {h1['sharpe']:+.2f} / {h2['sharpe']:+.2f} "
              f"maxDD {h1['maxdd'] * 100:.1f}% / {h2['maxdd'] * 100:.1f}% | 2008 "
              f"{episode(r, '2008-09-01', '2009-03-09') * 100:+.1f}% | 2020 "
              f"{episode(r, '2020-02-19', '2020-04-30') * 100:+.1f}% | 2022 "
              f"{episode(r, '2022-01-01', '2022-12-31') * 100:+.1f}%{turn}", flush=True)
    print(f"\n  shock overlay: flagged {flag_rate:.1%} of days (2024-2026 only)")
    trials = np.array([v[0]["sharpe"] for k, v in table.items() if not k.startswith("shock")])
    trials = trials[np.isfinite(trials)]
    print(f"\nPASS TEST - ours (tr, env) against ewma, same strategy; DSR over {len(trials)} variants")
    groups = sorted({k.split(":", 2)[0] + ":" + (k.split(":", 2)[2] if k.startswith("vt") else "") for k in names
                     if k.startswith(("vt:", "rp:", "hrp:"))})
    for g in groups:
        kind, asset = g.split(":")
        key = (lambda f: f"vt:{f}:{asset}") if kind == "vt" else (lambda f: f"{kind}:{f}")
        base = table[key("ewma")]
        for f in ("tr", "env"):
            mine = table[key(f)]
            ds = [mine[i]["sharpe"] - base[i]["sharpe"] for i in range(3)]
            dd = [(abs(base[i]["maxdd"]) - abs(mine[i]["maxdd"])) / abs(base[i]["maxdd"]) for i in range(3)]
            ci = block_boot_diff(series[key(f)], series[key("ewma")])
            dsr = deflated_sharpe(series[key(f)], trials)
            ok = (all(x >= 0.1 for x in ds[1:]) or all(x >= 0.2 for x in dd[1:])) and dsr > 0.95
            print(f"  {key(f):18s} dSharpe {ds[0]:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] halves {ds[1]:+.3f} / "
                  f"{ds[2]:+.3f} | dMaxDD {dd[0]:+.0%} halves {dd[1]:+.0%} / {dd[2]:+.0%} | DSR {dsr:.3f} | "
                  f"{'PASS' if ok else 'fail'}", flush=True)
    for k in ("bh:60/40", "bh:equal", "rp:ewma", "hrp:ewma", "rp:tr", "hrp:tr"):
        print(f"  DSR {k:10s} {deflated_sharpe(series[k], trials):.3f}")
    for kind in ("garch", "iid"):
        rows = walks(kind)
        print(f"\nWALKS ({kind}, {len(rows['bh'])} x 5,000 days): mean Sharpe / maxDD")
        for k, v in rows.items():
            sh = np.array([x["sharpe"] for x in v])
            md = np.array([x["maxdd"] for x in v])
            print(f"  {k:8s} Sharpe {np.nanmean(sh):+.3f} (sd {np.nanstd(sh):.3f}) | maxDD {np.nanmean(md) * 100:.1f}%")
        bh = np.array([x["sharpe"] for x in rows["bh"]])
        for f in FORECASTS:
            d = np.array([x["sharpe"] for x in rows[f"vt:{f}"]]) - bh
            print(f"  vt:{f} - bh  dSharpe {d.mean():+.3f} (se {d.std(ddof=1) / math.sqrt(len(d)):.3f})")
        for f in ("tr", "env"):
            d = np.array([x["sharpe"] for x in rows[f"vt:{f}"]]) - np.array([x["sharpe"] for x in rows["vt:ewma"]])
            print(f"  vt:{f} - vt:ewma dSharpe {d.mean():+.3f} (se {d.std(ddof=1) / math.sqrt(len(d)):.3f})")


if __name__ == "__main__":
    data() if PART == "data" else run()
