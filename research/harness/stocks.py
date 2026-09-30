"""Mean reversion on the broker's share CFDs: does any classic stock reversal survive our costs?

The MT5 terminal serves 448 share CFDs (222 NYSE, 217 NASDAQ, 9 European) with no sector labels,
floating spreads, and financing in `swap_mode` 5 (annual % of price: US longs -7.4% a year, shorts
0). It serves about **13 months** of history (270 daily bars from 2025-09-03, ~5,800 hourly bars of
22-hour CFD sessions), which caps every test below. The 439 US names are the cross-section; the 9
European names are too few and trade another calendar, so they are left out.

Pre-registered tests. Fit (choose among a small grid) on the first 60% of days, score the last
40%, and report the scored block's two halves. Net of the round-trip spread (the median recorded
spread of each stock's regular-hours 1h bars, relative to price, charged on every unit of turnover)
and financing (long exposure x 7.4% / 365 per calendar day held; shorts 0):

  (a) xs        cross-sectional short-term reversal (Lehmann 1990; Lo & MacKinlay 1990): weights
                minus the demeaned L-day return, L in {1, 2, 3, 5}, dollar-neutral, gross 1, held
                1 day (daily) or 5 days (weekly, overlapping tranches). Also "cluster-neutral":
                demeaned within correlation clusters of the fit block, standing in for industries
                (Da, Liu & Schaumburg 2014), since the broker carries no sectors.
  (b) rsi2      Connors RSI(2): long below 10 above the 100-day mean (the 200-day of the rule does
                not fit in 270 days - a stated deviation), out on a close above the 5-day mean or
                after 10 days; long-short adds the mirror. Equal weight across open positions.
  (c) zscore    z = (close - 20-day mean) / 20-day sd; in beyond +-2, out inside +-0.5; with and
                without Chan's regime filter (60-day variance ratio VR(5) < 0.9, chan.md).
  (d) pairs     distance method (Gatev, Goetzmann & Rouwenhorst 2006): the 20 pairs with the
                smallest squared distance of normalised prices in the fit block, opened at 2
                formation sd, closed on crossing; and Engle-Granger pairs (fit-block p < 0.05,
                half-life < 20 days), in at |z| > 2, out at 0. Both legs' spreads.
  (e) night     1h bars: overnight (16:00 -> 10:00 New York, the close of the bar holding the
                open) against intraday; and the overnight-intraday reversal (short the top
                overnight decile, long the bottom, at the open proxy, flat at the close).

Controls: factor walks we generate (one common factor plus idiosyncratic noise, each stock's
volatility and beta matched to the fit block) run through the same code; a random-rank placebo for
(a); BH across every configuration; the Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) over
all trials; cost multiples 1x / 2x / 3x.

Pass bar: net Sharpe >= 0.5 in the scored block and in both of its halves, DSR > 0.95, positive at
2x costs, and not reproduced by the walks (walk 95th percentile below the real Sharpe).

Survivorship: the terminal serves only names listed today, so losers that were delisted are
missing, which flatters reversal (the losers bought are the ones that survived). With 13 months the
effect is small but it biases *towards* a pass.

Run on the lab:
  PART=fetch python research/harness/stocks.py     (rate-limited, into the seqlab cache)
  PART=run   python research/harness/stocks.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import feed
import seqlab

PART = os.environ.get("PART", "run")
SPECS = Path(os.environ.get("SPECS", str(Path.home() / "till_infinity" / "data" / "stock_specs.json")))
OUT = Path(os.environ.get("OUT", str(Path.home() / "till_infinity" / "data" / "stocks")))
PAUSE = float(os.environ.get("PAUSE", "0.6"))  # between terminal calls: production shares the bridge
LONG_FIN = 0.074 / 365  # per calendar day, US longs (swap_mode 5, -7.4% a year)
FIT = 0.6
NY = ZoneInfo("America/New_York")
WALKS = int(os.environ.get("WALKS", "40"))
PLACEBOS = int(os.environ.get("PLACEBOS", "200"))
RNG = np.random.default_rng(545)


# ------------------------------------------------------------------------------------ the data

def universe() -> dict[str, dict]:
    specs = json.loads(SPECS.read_text())
    return {s: v for s, v in specs.items()
            if (v.get("path") or "").startswith(("Equities\\NYSE", "Equities\\NASDAQ"))}


def fetch() -> None:
    names = sorted(universe())
    ok = {"1d": 0, "1h": 0}
    for n, sym in enumerate(names):
        for iv in ("1d", "1h"):
            try:
                seqlab.cache(sym, iv)
                ok[iv] += 1
            except Exception as exc:  # noqa: BLE001 - one missing name is not the study
                print(f"  {sym} {iv}: {str(exc)[:80]}", flush=True)
            time.sleep(PAUSE)
        if n % 50 == 0:
            print(f"  {n}/{len(names)} {ok}", flush=True)
    print(f"fetched {ok} of {len(names)} names", flush=True)


def panels():
    """Daily close panel (US regular-session days), per-stock relative spread, 1h open proxies."""
    uni = universe()
    closes, spreads, night, day = {}, {}, {}, {}
    for sym, spec in uni.items():
        try:
            d = seqlab.cache(sym, "1d")
            h = seqlab.cache(sym, "1h")
        except Exception:  # noqa: BLE001
            continue
        if len(d["close"]) < 200 or len(h["close"]) < 2000:
            continue
        point = float(spec.get("point") or 0.01)
        dates = pd.to_datetime(d["time"], unit="s", utc=True).tz_convert(NY).normalize().tz_localize(None)
        closes[sym] = pd.Series(d["close"], index=dates)
        ht = pd.to_datetime(h["time"], unit="s", utc=True).tz_convert(NY)
        hf = pd.DataFrame({"close": h["close"], "spread": h["spread"], "hour": ht.hour, "wd": ht.weekday,
                           "date": ht.normalize().tz_localize(None)})
        rth = hf[(hf["hour"] >= 9) & (hf["hour"] <= 15) & (hf["wd"] < 5)]
        spreads[sym] = float(np.median(rth["spread"] * point / rth["close"])) if len(rth) else np.nan
        # the bar opening 09:00 holds the 09:30 open; its close is the open proxy. 15:00 closes 16:00.
        op = rth[rth["hour"] == 9].groupby("date")["close"].last()
        cl = rth[rth["hour"] == 15].groupby("date")["close"].last()
        both = pd.concat({"open": op, "close": cl}, axis=1).dropna()
        night[sym] = np.log(both["open"] / both["close"].shift(1))
        day[sym] = np.log(both["close"] / both["open"])
    px = pd.DataFrame(closes).sort_index()
    px = px[px.index.dayofweek < 5].ffill(limit=2)
    return px, pd.Series(spreads), pd.DataFrame(night).sort_index(), pd.DataFrame(day).sort_index()


# ------------------------------------------------------------------------------------ scoring

def stats(daily: pd.Series) -> dict:
    daily = daily.dropna()
    if len(daily) < 20 or daily.std() == 0:
        return {"sharpe": float("nan"), "n": len(daily)}
    sr = daily.mean() / daily.std() * math.sqrt(252)
    eq = daily.cumsum()
    return {"sharpe": float(sr), "ann": float(daily.mean() * 252), "maxdd": float((eq - eq.cummax()).min()),
            "n": len(daily), "sr_d": float(daily.mean() / daily.std()), "skew": float(daily.skew()),
            "kurt": float(daily.kurt() + 3)}


def split(daily: pd.Series) -> dict:
    daily = daily.dropna()
    cut = daily.index[int(len(daily) * FIT)] if len(daily) else None
    test = daily[daily.index >= cut] if cut is not None else daily
    mid = test.index[len(test) // 2] if len(test) else None
    return {"fit": stats(daily[daily.index < cut]) if cut is not None else {}, "test": stats(test),
            "h1": stats(test[test.index < mid]), "h2": stats(test[test.index >= mid]), "test_series": test}


def book(weights: pd.DataFrame, rets: pd.DataFrame, spread: pd.Series, mult: float = 1.0) -> pd.Series:
    """Daily net return of a weight book held close to close: weights set at t earn t+1's return."""
    w = weights.reindex_like(rets).fillna(0.0)
    gross = (w.shift(1) * rets).sum(axis=1)
    turn = (w - w.shift(1)).abs().fillna(w.abs())
    cost = (turn * spread.reindex(w.columns).fillna(spread.median()) * mult / 2).sum(axis=1)
    days = pd.Series(w.index, index=w.index).diff().dt.days.fillna(1).clip(lower=1)
    fin = (w.shift(1).clip(lower=0).sum(axis=1)) * LONG_FIN * days
    return gross - cost - fin


# ------------------------------------------------------------------------------------ strategies

def xs_weights(rets: pd.DataFrame, look: int, hold: int, clusters: dict | None = None) -> pd.DataFrame:
    past = np.log1p(rets).rolling(look).sum()
    sig = -past
    if clusters:
        for members in clusters.values():
            cols = [c for c in members if c in sig.columns]
            sig[cols] = sig[cols].sub(sig[cols].mean(axis=1), axis=0)
    else:
        sig = sig.sub(sig.mean(axis=1), axis=0)
    w = sig.div(sig.abs().sum(axis=1), axis=0)
    if hold > 1:  # overlapping tranches
        w = w.rolling(hold, min_periods=1).mean()
    return w


def rsi(px: pd.DataFrame, n: int = 2) -> pd.DataFrame:
    d = px.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def state_book(entry_long, exit_long, entry_short=None, exit_short=None, max_hold: int = 10) -> pd.DataFrame:
    """Positions from entry/exit masks, equal weight across open positions, gross <= 1."""
    pos = pd.DataFrame(0.0, index=entry_long.index, columns=entry_long.columns)
    cur = np.zeros(len(pos.columns))
    age = np.zeros(len(pos.columns))
    el, xl = entry_long.to_numpy(), exit_long.to_numpy()
    es = entry_short.to_numpy() if entry_short is not None else None
    xs = exit_short.to_numpy() if exit_short is not None else None
    out = np.zeros(pos.shape)
    for t in range(len(pos)):
        age = np.where(cur != 0, age + 1, 0)
        cur = np.where((cur > 0) & (xl[t] | (age >= max_hold)), 0, cur)
        if es is not None:
            cur = np.where((cur < 0) & (xs[t] | (age >= max_hold)), 0, cur)
        cur = np.where((cur == 0) & el[t], 1, cur)
        if es is not None:
            cur = np.where((cur == 0) & es[t], -1, cur)
        n = np.abs(cur).sum()
        out[t] = cur / n if n else 0
    return pd.DataFrame(out, index=pos.index, columns=pos.columns)


def variance_ratio(rets: pd.DataFrame, q: int = 5, win: int = 60) -> pd.DataFrame:
    v1 = rets.rolling(win).var()
    vq = np.log1p(rets).rolling(q).sum().rolling(win).var()
    return vq / (q * v1)


def clusters_of(rets: pd.DataFrame, k: int = 20) -> dict:
    corr = rets.corr().fillna(0).to_numpy()
    rng = np.random.default_rng(3)
    x = corr
    cent = x[rng.choice(len(x), k, replace=False)]
    for _ in range(30):
        lab = np.argmin(((x[:, None, :] - cent[None]) ** 2).sum(-1), axis=1)
        cent = np.array([x[lab == j].mean(0) if (lab == j).any() else cent[j] for j in range(k)])
    return {j: list(rets.columns[lab == j]) for j in range(k)}


def pairs_book(px: pd.DataFrame, fit_end, method: str, n_pairs: int = 20) -> pd.DataFrame:
    logp = np.log(px)
    form = logp[logp.index < fit_end].dropna(axis=1)
    cols = list(form.columns)
    norm = (form - form.iloc[0])
    arr = norm.to_numpy()
    cands = []
    if method == "distance":
        for i in range(len(cols)):
            d = ((arr[:, [i]] - arr[:, i + 1:]) ** 2).sum(0)
            for j, v in enumerate(d):
                cands.append((v, cols[i], cols[i + 1 + j]))
        cands.sort()
        chosen = [(a, b, 1.0) for _, a, b in cands[:n_pairs]]
    else:  # Engle-Granger on the formation block, on the most correlated few thousand
        r = form.diff().corr().to_numpy()
        iu = np.triu_indices(len(cols), 1)
        order = np.argsort(-r[iu])[:3000]
        chosen = []
        for o in order:
            a, b = cols[iu[0][o]], cols[iu[1][o]]
            y, x = form[a].to_numpy(), form[b].to_numpy()
            beta = np.polyfit(x, y, 1)[0]
            s = y - beta * x
            ds = np.diff(s)
            phi = np.polyfit(s[:-1] - s[:-1].mean(), ds, 1)[0]
            resid = ds - phi * (s[:-1] - s[:-1].mean())
            tstat = phi / (resid.std() / math.sqrt(((s[:-1] - s[:-1].mean()) ** 2).sum()))
            hl = -math.log(2) / math.log(1 + phi) if -1 < phi < 0 else float("inf")
            if tstat < -3.37 and hl < 20:  # EG 5% critical value, two series
                chosen.append((a, b, beta))
            if len(chosen) >= n_pairs:
                break
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for a, b, beta in chosen:
        f = logp[logp.index < fit_end]
        spread = logp[a] - beta * logp[b]
        mu, sd = spread[spread.index < fit_end].mean(), spread[spread.index < fit_end].std()
        if not sd:
            continue
        z = (spread - mu) / sd
        pos = np.zeros(len(z))
        cur = 0
        for t, v in enumerate(z.to_numpy()):
            if cur == 0 and v > 2:
                cur = -1
            elif cur == 0 and v < -2:
                cur = 1
            elif (cur == 1 and v >= 0) or (cur == -1 and v <= 0):
                cur = 0
            pos[t] = cur
        scale = 1.0 / (len(chosen) * (1 + abs(beta)))
        w[a] += pos * scale
        w[b] -= pos * beta * scale
        del f
    return w


# ------------------------------------------------------------------------------------ controls

def factor_walk(rets: pd.DataFrame, fit_end, seed: int) -> pd.DataFrame:
    """One market factor plus noise, vol and beta matched per stock on the fit block."""
    rng = np.random.default_rng(seed)
    fit = rets[rets.index < fit_end]
    mkt = fit.mean(axis=1)
    beta = fit.apply(lambda c: np.cov(c.fillna(0), mkt)[0, 1] / mkt.var())
    idio = (fit.sub(mkt, axis=0).mul(1)).std()
    f = rng.standard_normal(len(rets)) * mkt.std()
    e = rng.standard_normal(rets.shape) * idio.to_numpy()
    sim = pd.DataFrame(np.outer(f, beta.to_numpy()) + e, index=rets.index, columns=rets.columns)
    return sim.where(rets.notna())


def dsr(sr_d: float, sr_trials: list[float], t: int, skew: float, kurt: float) -> float:
    n = len(sr_trials)
    if n < 2 or not np.isfinite(sr_d):
        return float("nan")
    var = float(np.nanvar(sr_trials))
    nd = NormalDist()
    g = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e)))
    den = math.sqrt(max(1 - skew * sr_d + (kurt - 1) / 4 * sr_d**2, 1e-9))
    return float(nd.cdf((sr_d - sr0) * math.sqrt(t - 1) / den))


# ------------------------------------------------------------------------------------ run

def run() -> None:
    px, spread, night, day = panels()
    rets = px.pct_change()
    fit_end = px.index[int(len(px) * FIT)]
    print(f"universe {px.shape[1]} US share CFDs, {len(px)} days {px.index[0].date()} -> {px.index[-1].date()}; "
          f"fit ends {fit_end.date()}; median round-trip spread {spread.median() * 1e4:.1f} bps "
          f"(p10 {spread.quantile(0.1) * 1e4:.1f}, p90 {spread.quantile(0.9) * 1e4:.1f})", flush=True)
    clus = clusters_of(rets[rets.index < fit_end])
    configs: dict[str, callable] = {}
    for look in (1, 2, 3, 5):
        for hold in (1, 5):
            configs[f"xs L{look} H{hold}"] = lambda r, p, L=look, H=hold: xs_weights(r, L, H)
            configs[f"xs-cluster L{look} H{hold}"] = lambda r, p, L=look, H=hold: xs_weights(r, L, H, clus)

    def rsi_long(r, p):
        x, m100, m5 = rsi(p), p.rolling(100).mean(), p.rolling(5).mean()
        return state_book((x < 10) & (p > m100), p > m5)

    def rsi_ls(r, p):
        x, m100, m5 = rsi(p), p.rolling(100).mean(), p.rolling(5).mean()
        return state_book((x < 10) & (p > m100), p > m5, (x > 90) & (p < m100), p < m5)

    def zbook(r, p, filt: bool):
        m, s = p.rolling(20).mean(), p.rolling(20).std()
        z = (p - m) / s
        ok = variance_ratio(r) < 0.9 if filt else pd.DataFrame(True, index=p.index, columns=p.columns)
        return state_book((z < -2) & ok, z.abs() < 0.5, (z > 2) & ok, z.abs() < 0.5, max_hold=20)

    configs["rsi2 long"] = rsi_long
    configs["rsi2 long-short"] = rsi_ls
    configs["zscore"] = lambda r, p: zbook(r, p, False)
    configs["zscore +VR<0.9"] = lambda r, p: zbook(r, p, True)
    configs["pairs distance"] = lambda r, p: pairs_book(p, fit_end, "distance")
    configs["pairs coint"] = lambda r, p: pairs_book(p, fit_end, "coint")

    results = {}
    for name, make in configs.items():
        w = make(rets, px)
        res = {m: split(book(w, rets, spread, m)) for m in (1.0, 2.0, 3.0)}
        # walks: the same rule on factor walks we generate
        walk_sr = []
        for k in range(WALKS if not name.startswith("pairs") else max(WALKS // 4, 5)):
            sim = factor_walk(rets, fit_end, k)
            simpx = (1 + sim.fillna(0)).cumprod() * 100
            walk_sr.append(split(book(make(sim, simpx), sim, spread, 1.0))["test"]["sharpe"])
        results[name] = {"res": res, "walks": walk_sr, "turnover": float((w - w.shift(1)).abs().sum(axis=1).mean())}
        t = res[1.0]
        print(f"  {name:22s} test Sharpe {t['test']['sharpe']:+.2f} (halves {t['h1']['sharpe']:+.2f} / "
              f"{t['h2']['sharpe']:+.2f}) | fit {t['fit'].get('sharpe', float('nan')):+.2f} | 2x "
              f"{res[2.0]['test']['sharpe']:+.2f} 3x {res[3.0]['test']['sharpe']:+.2f} | walks p95 "
              f"{np.nanpercentile(walk_sr, 95):+.2f} median {np.nanmedian(walk_sr):+.2f} | daily turnover "
              f"{results[name]['turnover']:.2f}", flush=True)

    # random-rank placebo for the xs family: permute the signal across stocks each day
    best_xs = max((k for k in results if k.startswith("xs ")), key=lambda k: results[k]["res"][1.0]["fit"].get("sharpe", -9))
    look, hold = (int(best_xs.split("L")[1].split()[0]), int(best_xs.split("H")[1]))
    base = xs_weights(rets, look, hold)
    plac = []
    for _ in range(PLACEBOS):
        perm = base.apply(lambda row: pd.Series(RNG.permutation(row.to_numpy()), index=row.index), axis=1)
        plac.append(split(book(perm, rets, spread))["test"]["sharpe"])
    print(f"  random-rank placebo on {best_xs}: test Sharpe p95 {np.nanpercentile(plac, 95):+.2f} "
          f"median {np.nanmedian(plac):+.2f}", flush=True)

    # overnight vs intraday
    common = night.columns.intersection(day.columns)
    nt, dy = night[common], day[common]
    eqn, eqd = nt.mean(axis=1), dy.mean(axis=1)
    print(f"\n  night vs day, equal-weight: overnight {split(eqn)['test']['sharpe']:+.2f} Sharpe "
          f"(ann {eqn.mean() * 252:+.2%}), intraday {split(eqd)['test']['sharpe']:+.2f} (ann {eqd.mean() * 252:+.2%})",
          flush=True)
    rank = nt.rank(axis=1, pct=True)
    wn = (rank <= 0.1).astype(float).div((rank <= 0.1).sum(axis=1), axis=0) - \
         (rank >= 0.9).astype(float).div((rank >= 0.9).sum(axis=1), axis=0)
    for mult in (1.0, 2.0, 3.0):
        # in at the open proxy, out at the close: one round trip a day on gross 2
        net = (wn * dy).sum(axis=1) - 2 * mult * spread.reindex(common).median() / 1
        r = split(net)
        results.setdefault("night reversal", {"res": {}, "walks": [], "turnover": 2.0})["res"][mult] = r
    r1 = results["night reversal"]["res"]
    print(f"  overnight-intraday reversal: gross test Sharpe {split((wn * dy).sum(axis=1))['test']['sharpe']:+.2f} | net "
          f"{r1[1.0]['test']['sharpe']:+.2f} (halves {r1[1.0]['h1']['sharpe']:+.2f} / {r1[1.0]['h2']['sharpe']:+.2f}) "
          f"2x {r1[2.0]['test']['sharpe']:+.2f}", flush=True)

    # BH and DSR over every trial (the placebo is a control, not a trial)
    names = list(results)
    trials = [results[k]["res"][1.0]["test"].get("sr_d", float("nan")) for k in names]
    print(f"\n  trials {len(names)} | pass bar: test Sharpe >= 0.5 both halves, DSR > 0.95, 2x > 0, > walks p95",
          flush=True)
    pvals = []
    for k in names:
        t = results[k]["res"][1.0]["test"]
        n = t.get("n", 0)
        pvals.append(1 - NormalDist().cdf(t["sharpe"] / math.sqrt(252) * math.sqrt(max(n, 1))) if np.isfinite(t["sharpe"]) else 1.0)
    order = np.argsort(pvals)
    q = np.empty(len(pvals))
    prev = 1.0
    for rank_i, idx in enumerate(order[::-1]):
        m = len(pvals) - rank_i
        prev = min(prev, pvals[idx] * len(pvals) / m)
        q[idx] = prev
    table = []
    for i, k in enumerate(names):
        rr = results[k]["res"]
        t = rr[1.0]["test"]
        d = dsr(t.get("sr_d", float("nan")), trials, t.get("n", 0), t.get("skew", 0.0), t.get("kurt", 3.0))
        w95 = np.nanpercentile(results[k]["walks"], 95) if results[k]["walks"] else float("nan")
        passed = (t["sharpe"] >= 0.5 and rr[1.0]["h1"]["sharpe"] >= 0.5 and rr[1.0]["h2"]["sharpe"] >= 0.5
                  and d > 0.95 and rr[2.0]["test"]["sharpe"] > 0 and not (np.isfinite(w95) and t["sharpe"] <= w95))
        table.append({"name": k, "test": t["sharpe"], "h1": rr[1.0]["h1"]["sharpe"], "h2": rr[1.0]["h2"]["sharpe"],
                      "x2": rr[2.0]["test"]["sharpe"], "x3": rr[3.0]["test"]["sharpe"], "walk95": w95,
                      "q": float(q[i]), "dsr": d, "maxdd": t.get("maxdd"), "pass": bool(passed)})
        print(f"  {k:22s} Sharpe {t['sharpe']:+.2f} | BH q {q[i]:.3f} | DSR {d:.3f} | maxDD "
              f"{t.get('maxdd', float('nan')):+.3f} | {'PASS' if passed else 'fail'}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps({"table": table, "universe": int(px.shape[1]),
                                                  "days": int(len(px)), "start": str(px.index[0].date()),
                                                  "end": str(px.index[-1].date()),
                                                  "spread_bps_median": float(spread.median() * 1e4),
                                                  "written": datetime.now(UTC).isoformat()}, default=float))
    print("\nwritten", OUT / "results.json", flush=True)


if __name__ == "__main__":
    fetch() if PART == "fetch" else run()
