"""Many weak scenario models, weighted with their covariance, traded only when they line up.

Every single directional model in `horizons.py` and `questions.py` is weak. The desk's
framing is that trading is a game of probabilities - several scenarios, each with a
probability, and waiting for enough of them to agree. That is an ensemble question,
and the linear algebra decides how much agreement is worth: ten models that are the
same model in ten coats agree for free.

The bank. One gradient-boosted classifier per (feature family x horizon x side):

  families  technical, volatility, bar shape (OHLC), borrowed fields, calendar,
            cross-asset, and all of them together
  horizons  horizons.HORIZONS for the interval
  sides     long = P(upper barrier first), short = P(lower barrier first), wick-resolved

Event-conditioned models join the bank: the same long/short pair per horizon, trained
only on bars where an event fired (a 4x shock bar either way, a fresh 50-bar high or low,
a breakout from a compressed range, a volatility alarm, the London and New York opens).
Such a model has a view only on its own event bars and is neutral (0) everywhere else.
Pair-spread models join last: for each pair in `questions.PAIRS`, the long/short pair per
horizon on log(A/B) - does A outperform by the barrier first, or B. A relative-value view
lands on both legs, +edge on A and -edge on B at the same timestamp (summed where an
instrument sits in two pairs), neutral on everything else.

Every combination is reported for the bank alone, with the event models, and with both.

Two more families in the bank, both of which carry information the price series does not:
  vix     ^VIX against its own 250-day history, its 5-day change, the term structure
          (VIX9D/VIX and VIX/VIX3M - inversion is stress), and VIX over realised S&P
          volatility (the variance risk premium). Each bar sees the close of the last day
          strictly before its own date - no look-ahead into a close it could not have seen.
  dollar  `linear-algebra.md` found this book's one real factor is the dollar. A leave-one-out dollar
          index from the other FX pairs and gold (each oriented so + means dollar up), its
          5- and 20-bar momentum, and the same signed by the instrument's own dollar exposure.

  flow    order flow inferred from OHLCV - there is no trade-side data here, and FX/CFD volume
          is the broker's tick count rather than traded size (Coinbase crypto is real volume;
          yahoo daily FX has none). Bulk volume classification splits each bar's volume into
          buys and sells by Phi(r / sigma), giving an order-flow imbalance over 5 and 20 bars
          and VPIN; accumulation/distribution weights volume by where the close sits in the
          bar; OBV-style signed volume; volume against its own history and against the same
          hour-of-week; Amihud illiquidity; and the volume-|return| correlation.

  fvg     fair value gaps as standing levels, from `training/candles.py`'s `standing_gaps` so
          the definition is the one `imbalance.md` measured (603,375 visits, directions right,
          nothing paying on its own): distance to the nearest unfilled bullish and bearish
          edge in true ranges, its age, the origin candle's wick, and the size of a gap
          opened on this very bar. Two more event models join the event bank: price within
          half a true range of an unfilled bullish edge, and of a bearish one.

Two more combinations: `stacked`, a logistic meta-model on the validation block's signals
predicting the sign of the payoff; and `regime`, inverse-covariance weights estimated
separately on calm and volatile validation bars and switched by the volatility state.

The economic calendar joins as a gate, not a model. The store (`.secrets/journal/events.jsonl.gz`)
begins 2026-08-09 - six weeks, shorter than any training block - so nothing can be learned from
it yet and it sits entirely inside the test period. What it can do honestly is what
`news-volatility.md` measured: tell you a release is coming. On calendar-covered test trades each
combination is reported three ways - all, with any high-importance release for the
instrument's currencies inside the holding window excluded, and those release windows alone.

Each model's probability becomes an edge, logit(p) - logit(its training base rate), and
each (family, horizon) gives one directional signal: long edge minus short edge.

Three time blocks per series: fit on the first 40%, estimate the covariance and each
signal's information coefficient on 40-60%, trade on the last 40%.

On the validation block:
  covariance and eigen-decomposition of the signals - the eigenvalues, the share on the
  first component, and the effective number of independent views (participation ratio,
  (sum l)^2 / sum l^2), against the Marchenko-Pastur edge a pure-noise matrix of this shape
  would reach
  IC = correlation of each signal with the realised value of the trade horizon's
  long-minus-short payoff

Combinations traded on the test block (long above the validation 80th percentile, short
below the 20th, non-overlapping, net of spread, halves and families reported):
  best single  the signal with the highest validation IC
  equal        mean of standardised signals
  inverse-cov  w ~ S^-1 IC with S shrunk toward its diagonal (Ledoit-Wolf) - Markowitz on signals
  eigen        project on the eigenvectors with l above the noise edge, weight components by IC
  confluence   trade only when at least 70% of the clusters' signals agree in sign, where a
               cluster is a group of signals correlated above 0.6 - agreement between
               independent views, not between copies

Run from the repository root:  .venv-research/bin/python research/harness/ensemble.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).parent))
from horizons import HORIZONS, build
from bars import Fitted, long_R, paths
from questions import COST_V, MINUTES, event_masks, pair_frame, thin
from news_vol import FLOATING, load_events
from spikerisk import DAILY, SERIES

TRADE_H = {"15m": 8, "1h": 5, "1d": 5}
SECONDS = {"15m": 900, "1h": 3600, "1d": 86400}
CALENDAR = ".secrets/journal/events.jsonl.gz"
#: which calendar codes move an instrument - both legs of a pair; gold, indices and crypto are dollar
CURRENCIES = {
    "EURUSD": ("EUR", "EU", "DE", "FR", "IT"), "GBPUSD": ("GBP", "GB", "UK"), "AUDUSD": ("AUD", "AU"),
    "NZDUSD": ("NZD", "NZ"), "USDCAD": ("CAD", "CA"), "USDCHF": ("CHF", "CH"), "USDJPY": ("JPY", "JP"),
    "USDCNH": ("CNY", "CN", "CNH"),
}


#: +1 when the quote rises with the dollar, -1 when it falls; 0 for no direct dollar leg
USD_SIDE = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDCAD": 1, "USDCHF": 1, "USDJPY": 1,
            "USDCNH": 1, "XAUUSD": -1}
VIX_CACHE = Path(".data/research/vix.csv")


def vix_table():
    """Daily ^VIX, ^VIX9D, ^VIX3M closes and S&P realised vol; fetched once, cached."""
    try:
        import yfinance as yf
        cols = {}
        for t in ("^VIX", "^VIX9D", "^VIX3M", "^GSPC"):
            h = yf.Ticker(t).history(period="max", interval="1d", auto_adjust=False)["Close"]
            h.index = pd.to_datetime(h.index.date)
            cols[t] = h
        v = pd.DataFrame(cols).sort_index()
        VIX_CACHE.parent.mkdir(parents=True, exist_ok=True)
        v.to_csv(VIX_CACHE)
    except Exception as exc:  # offline: the cache is the fallback
        print(f"vix fetch failed ({exc}); using {VIX_CACHE}")
        v = pd.read_csv(VIX_CACHE, index_col=0, parse_dates=True)
    v = v[~v.index.duplicated(keep="last")]
    spx = v["^GSPC"].dropna()
    rv = (np.log(spx).diff().rolling(20).std() * np.sqrt(252) * 100).reindex(v.index).ffill()
    v = v[v["^VIX"].notna()]
    rv = rv.reindex(v.index)
    out = pd.DataFrame(index=v.index)
    lv = np.log(v["^VIX"])
    out["vix_z"] = (lv - lv.rolling(250, min_periods=120).mean()) / lv.rolling(250, min_periods=120).std()
    out["vix_chg5"] = lv.diff(5)
    out["vix_9d"] = np.log(v["^VIX9D"] / v["^VIX"])
    out["vix_3m"] = np.log(v["^VIX"] / v["^VIX3M"])
    out["vix_vrp"] = lv - np.log(rv)
    return out


def add_vix(d):
    """Attach the last VIX row dated strictly before each bar's UTC date."""
    v = vix_table().dropna(how="all").reset_index().rename(columns={"index": "date"})
    v["date"] = pd.to_datetime(v["date"]).astype("datetime64[ns]")
    day = pd.to_datetime(d.ts, unit="s").dt.normalize().astype("datetime64[ns]")
    left = pd.DataFrame({"date": day, "_row": np.arange(len(d))}).sort_values("date")
    m = pd.merge_asof(left, v.sort_values("date"), on="date", allow_exact_matches=False).sort_values("_row")
    names = [c for c in v.columns if c != "date"]
    for c in names:
        d[c] = m[c].to_numpy()
    return names


def add_dollar(d):
    """Leave-one-out dollar index from the other dollar legs at the same timestamp, and its momentum."""
    side = d.ticker.map(USD_SIDE).fillna(0).to_numpy()
    contrib = pd.Series(np.where(side != 0, side * d["_z"].fillna(0).to_numpy(), 0.0))
    has = pd.Series((side != 0) & d["_z"].notna().to_numpy()).astype(float)
    g_sum = contrib.groupby(d.ts.to_numpy()).transform("sum").to_numpy()
    g_n = has.groupby(d.ts.to_numpy()).transform("sum").to_numpy()
    own = contrib.to_numpy()
    n = g_n - has.to_numpy()
    usd = np.where(n >= 2, (g_sum - own) / np.maximum(n, 1), np.nan)
    d["_usd"] = usd
    names = []
    for w in (5, 20):
        m = d.groupby("ticker")["_usd"].transform(lambda s: s.rolling(w, min_periods=w // 2).sum() / np.sqrt(w))
        d[f"usd_mom{w}"] = m
        d[f"usd_mom{w}_exp"] = m * side
        names += [f"usd_mom{w}", f"usd_mom{w}_exp"]
    return names


def add_flow(d, interval):
    """Order-flow and volume features per series, from OHLCV only."""
    from scipy.stats import norm
    out = {k: np.full(len(d), np.nan) for k in ("ofi5", "ofi20", "vpin", "ad20", "obv20", "vol_z",
                                                "vol_season", "amihud", "vol_absr")}
    for t, g in d.groupby("ticker"):
        v = g["_volume"].astype(float)
        if v.notna().mean() < 0.5:
            continue
        r = g["_lc"].diff()
        sig = r.rolling(100, min_periods=50).std()
        imb = pd.Series(2 * norm.cdf(r / sig) - 1, index=r.index)  # bulk volume classification: (buy - sell) / volume
        sv = v * imb
        rng = (g["_hi"] - g["_lo"]).replace(0, np.nan)
        clv = ((g["_lc"] - g["_lo"]) - (g["_hi"] - g["_lc"])) / rng
        idx = g.index.to_numpy()
        roll = lambda x, w: x.rolling(w, min_periods=w // 2).sum()
        out["ofi5"][idx] = roll(sv, 5) / roll(v, 5)
        out["ofi20"][idx] = roll(sv, 20) / roll(v, 20)
        out["vpin"][idx] = roll(v * imb.abs(), 50) / roll(v, 50)
        out["ad20"][idx] = roll(clv * v, 20) / roll(v, 20)
        out["obv20"][idx] = roll(np.sign(r) * v, 20) / roll(v, 20)
        lv = np.log(v)
        out["vol_z"][idx] = (lv - lv.rolling(250, min_periods=100).mean()) / lv.rolling(250, min_periods=100).std()
        if interval != "1d":
            tt = pd.to_datetime(g.ts, unit="s")
            slot = (tt.dt.dayofweek * 10_000 + tt.dt.hour * 100 + tt.dt.minute).to_numpy()
            prior = lv.groupby(slot).transform(lambda x: x.shift(1).expanding(min_periods=3).mean())
            out["vol_season"][idx] = lv - prior
        il = (r.abs() / v).rolling(20, min_periods=10).mean()
        out["amihud"][idx] = np.log(il / il.rolling(250, min_periods=100).mean())
        out["vol_absr"][idx] = r.abs().rolling(50, min_periods=25).corr(lv)
    for k, x in out.items():
        d[k] = x
    return [k for k in out if np.isfinite(d[k]).any()]


def add_fvg(d):
    """Standing fair value gaps per series, and 'near an unfilled edge' event masks."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "training"))
    import candles
    cols = ["fvg_bull_dist", "fvg_bull_age", "fvg_bull_wick", "fvg_bear_dist", "fvg_bear_age", "fvg_bear_wick"]
    out = np.zeros((len(d), 6))
    fresh_bull, fresh_bear = np.zeros(len(d)), np.zeros(len(d))
    for t, g in d.groupby("ticker"):
        idx = g.index.to_numpy()
        bars = np.column_stack([g.ts.to_numpy(float)] + [np.exp(g[c].to_numpy()) for c in ("_op", "_hi", "_lo", "_lc")])
        ok = np.isfinite(bars).all(axis=1)
        bars = bars[ok]
        idx = idx[ok]
        tr = candles.true_range(bars)
        out[idx] = candles.standing_gaps(bars, tr)
        hi, lo, cl = bars[:, 2], bars[:, 3], bars[:, 4]
        unit = np.maximum(tr * cl, 1e-12)
        fb, fr = np.zeros(len(bars)), np.zeros(len(bars))
        fb[2:] = np.clip(lo[2:] - hi[:-2], 0, None) / unit[2:]   # a gap opened on this bar, in TR
        fr[2:] = np.clip(lo[:-2] - hi[2:], 0, None) / unit[2:]
        fresh_bull[idx], fresh_bear[idx] = fb, fr
    for j, c in enumerate(cols):
        d[c] = out[:, j]
    d["fvg_fresh_bull"], d["fvg_fresh_bear"] = fresh_bull, fresh_bear
    near = {
        "fvg_bull_near": (out[:, 0] > 0) & (out[:, 0] <= 0.5),  # just above an unfilled bullish edge
        "fvg_bear_near": (out[:, 3] > 0) & (out[:, 3] <= 0.5),  # just below an unfilled bearish edge
    }
    return cols + ["fvg_fresh_bull", "fvg_fresh_bear"], near


def release_windows(d, interval, H):
    """(covered, release): the bar is inside the calendar's span, and a high-importance release
    for its currencies lands in (entry, entry + H bars]."""
    try:
        events = [e for e in load_events(Path(CALENDAR)) if (e.get("importance") or 0) >= 2
                  and not any(f in (e.get("title") or "").lower() for f in FLOATING)]
    except OSError:
        return np.zeros(len(d), bool), np.zeros(len(d), bool)
    if not events:
        return np.zeros(len(d), bool), np.zeros(len(d), bool)
    first = min(e["time"] for e in events)
    ts = d.ts.to_numpy().astype(float)
    covered = ts >= first
    release = np.zeros(len(d), bool)
    span = SECONDS[interval] * H
    tick = d.ticker.to_numpy()
    for t in np.unique(tick):
        codes = set(CURRENCIES.get(t, ())) | {"USD", "US"}
        when = np.sort([e["time"] for e in events if (e.get("country") or e.get("currency")) in codes])
        k = tick == t
        nxt = np.searchsorted(when, ts[k], side="right")  # first release strictly after entry
        has = nxt < len(when)
        gap = np.full(k.sum(), np.inf)
        gap[has] = when[nxt[has]] - ts[k][has]
        release[k] = gap <= span
    return covered, release
FAMILIES = {
    "technical": ["zscore20", "rsi14", "mom5", "mom20", "mom60", "macd", "stoch14", "bbwidth", "fatigue",
                  "swing_ext", "swing_age", "impulse"],
    "volatility": ["short", "shock", "downshare", "skew100", "kurt100"],
    "bar": ["range", "rs_vol", "range_last", "upwick", "dnwick", "wick_skew", "clv", "clv5", "body", "gap"],
    "borrowed": ["ac1", "ac1_trend", "var_trend", "perm_ent", "vr4", "katz", "superexp", "hawkes_dn", "hawkes_up"],
    "calendar": ["hour_s", "hour_c", "dow_s", "dow_c", "season_vol", "season_drift", "asia", "london", "newyork",
                 "to_weekend", "dom_s", "dom_c", "mon_s", "mon_c", "turn_of_month"],
    "cross": ["cx_absz", "cx_big4", "cx_mom"],
}


def gbm(leaf=300):
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150,
                                          min_samples_leaf=leaf, l2_regularization=1.0)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def trade(name, d, score, fit_block, val, te, Rl, Rs, cost, H, rows, interval):
    hi, lo = np.nanquantile(score[val], 0.8), np.nanquantile(score[val], 0.2)
    side = np.where(score >= hi, 1, np.where(score <= lo, -1, 0))
    g = np.where(side == 1, Rl, np.where(side == -1, Rs, np.nan))
    net = g - cost
    taken = thin(d, te & (side != 0) & ~np.isnan(g), H)
    x = net[taken]
    se = x.std(ddof=1) / np.sqrt(len(x))
    half = d["_half"].to_numpy()
    a, b = net[taken & (half == 0)].mean(), net[taken & (half == 1)].mean()
    fam = d.family.to_numpy()
    fams = " ".join(f"{f[:3]}{net[taken & (fam == f)].mean():+.2f}" for f in COST_V if (taken & (fam == f)).sum() >= 15)
    t = x.mean() / se
    flag = "  <==" if t >= 3 and a > 0 and b > 0 else ""
    print(f"  {name:<22} n={len(x):>5} gross {g[taken].mean():+.3f} net {x.mean():+.3f} +- {se:.3f} t={t:+.1f}"
          f" | {a:+.2f} {b:+.2f} | win {np.mean(x > 0):.0%} | {fams}{flag}")
    cov, rel = d["_cal_cov"].to_numpy(), d["_cal_rel"].to_numpy()
    if (taken & cov).sum() >= 20:
        st = lambda m: f"{net[m].mean():+.3f} (n={m.sum()})" if m.sum() else "-"
        print(f"  {'':<22}   calendar-covered: all {st(taken & cov)}  gated (no release in window) "
              f"{st(taken & cov & ~rel)}  release windows only {st(taken & cov & rel)}")
    rows.append(dict(interval=interval, combo=name, n=len(x), net=x.mean(), se=se, t=t, a=a, b=b))


def run(interval, universe, rows):
    H = TRADE_H[interval]
    d, cols = build(interval, universe)
    size = d.groupby("ticker").ts.transform("size").to_numpy()
    pos = d["_pos"].to_numpy()
    frac = pos / size
    fit_block, val, te = frac < 0.4, (frac >= 0.4) & (frac < 0.6), frac >= 0.6
    d["_half"] = (frac >= 0.8).astype(int)
    d["_cal_cov"], d["_cal_rel"] = release_windows(d, interval, H)
    if d["_cal_cov"].any():
        print(f"calendar: covers {d['_cal_cov'].mean():.0%} of {interval} bars; a release inside the "
              f"{H}-bar window on {d['_cal_rel'][d['_cal_cov']].mean():.0%} of covered bars")
    families = {k: [c for c in v if c in cols] for k, v in FAMILIES.items()}
    families = {k: v for k, v in families.items() if v}
    families["all"] = cols
    families["vix"] = add_vix(d)
    families["dollar"] = add_dollar(d)
    families["flow"] = add_flow(d, interval)
    families["fvg"], fvg_events = add_fvg(d)
    print("fvg: near an unfilled bullish edge on {:.1%} of bars, bearish on {:.1%}".format(
        fvg_events["fvg_bull_near"].mean(), fvg_events["fvg_bear_near"].mean()))
    print(f"vix features present on {d[families['vix']].notna().all(axis=1).mean():.0%} of bars; "
          f"dollar on {d[families['dollar']].notna().all(axis=1).mean():.0%}; "
          f"flow on {d[families['flow']].notna().all(axis=1).mean():.0%}")

    signals, names = [], []
    for fam, fc in families.items():
        Xf = d[fc].to_numpy(float)
        for h in HORIZONS[interval]:
            edge = []
            for lab in ("tb_up", "tb_dn"):
                y = d[f"{lab}@{h}"].to_numpy()
                ok = ~np.isnan(y)
                m = Fitted(gbm(), Xf[fit_block & ok], y[fit_block & ok])
                edge.append(logit(m.predict_proba(Xf)[:, 1]) - logit(y[fit_block & ok].mean()))
            signals.append(edge[0] - edge[1])
            names.append(f"{fam}@{h}")
    Sg = np.column_stack(signals)
    n_bank = len(names)

    # event-conditioned models: a view on their own bars, neutral elsewhere
    X = d[cols].to_numpy(float)
    for ev, mask in {**event_masks(d, interval), **fvg_events}.items():
        for h in HORIZONS[interval]:
            edge = []
            for lab in ("tb_up", "tb_dn"):
                y = d[f"{lab}@{h}"].to_numpy()
                trn = fit_block & mask & ~np.isnan(y)
                if trn.sum() < 150 or y[trn].min() == y[trn].max():
                    break
                m = Fitted(gbm(leaf=40), X[trn], y[trn])  # hundreds of events, not tens of thousands of bars
                e = np.zeros(len(d))
                e[mask] = logit(m.predict_proba(X[mask])[:, 1]) - logit(y[trn].mean())
                edge.append(e)
            if len(edge) == 2:
                signals.append(edge[0] - edge[1])
                names.append(f"ev:{ev}@{h}")
    Sev = np.column_stack(signals)
    n_ev = len(names)

    # pair-spread models: a relative-value view on both legs
    pd_, pcols = pair_frame(interval)
    if pd_ is not None:
        psize = pd_.groupby("ticker").ts.transform("size").to_numpy()
        pfit = pd_["_pos"].to_numpy() / psize < 0.4
        PX = pd_[pcols].to_numpy(float)
        for h in HORIZONS[interval]:
            P = paths(pd_, h)
            U = 1.5 * pd_["_base"].to_numpy() * np.sqrt(h)
            _, wl = long_R(P, U, U)
            _, ws = long_R(P * -1, U, U)
            ok = ~np.isnan(P.end)
            edge = []
            for w in (wl, ws):
                y = (w == 1).astype(float)
                m = Fitted(gbm(), PX[pfit & ok], y[pfit & ok])
                edge.append(logit(m.predict_proba(PX)[:, 1]) - logit(y[pfit & ok].mean()))
            e = pd.DataFrame({"ts": pd_.ts, "pair": pd_.ticker, "e": edge[0] - edge[1]})
            col = np.zeros(len(d))
            for pair, g in e.groupby("pair"):
                a, b = pair.split("/")
                look = dict(zip(g.ts, g.e))
                for leg, sgn in ((a, 1.0), (b, -1.0)):
                    k = (d.ticker == leg).to_numpy()
                    col[k] += sgn * np.array([look.get(t, 0.0) for t in d.ts.to_numpy()[k]])
            signals.append(col)
            names.append(f"pair@{h}")
    Sall = np.column_stack(signals)
    # every signal, its name and the time blocks, for `components.py` to take apart
    out = Path(".data/research") / f"signals_{interval}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    Rl_, Rs_ = d[f"R@{TRADE_H[interval]}"].to_numpy(), d[f"Rs@{TRADE_H[interval]}"].to_numpy()
    np.savez_compressed(out, S=Sall, names=np.array(names), fit=fit_block, val=val, test=te,
                        value=(Rl_ - Rs_) / 2, ticker=d.ticker.to_numpy().astype(str), ts=d.ts.to_numpy())
    if os.environ.get("ENSEMBLE_DUMP_ONLY"):
        return
    print(f"\n{'#' * 110}\n{interval}: bank {n_bank} signals, event-conditioned {n_ev - n_bank}, "
          f"pair-spread {len(names) - n_ev}")
    evaluate(interval, "bank", d, Sg, names[:n_bank], fit_block, val, te, H, rows)
    evaluate(interval, "bank+ev", d, Sev, names[:n_ev], fit_block, val, te, H, rows)
    if len(names) > n_ev:
        evaluate(interval, "bank+ev+pairs", d, Sall, names, fit_block, val, te, H, rows)


def evaluate(interval, tag, d, Sg, names, fit_block, val, te, H, rows):
    Rl, Rs = d[f"R@{H}"].to_numpy(), d[f"Rs@{H}"].to_numpy()
    value = (Rl - Rs) / 2  # realised long-minus-short payoff at the trade horizon
    ok = ~np.isnan(value) & ~np.isnan(Sg).any(axis=1)
    fit_block, val, te = fit_block & ok, val & ok, te & ok
    mu, sd = Sg[val].mean(0), Sg[val].std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = (Sg - mu) / sd

    # --- the linear algebra, on the validation block
    V = Z[val]
    C = np.corrcoef(V, rowvar=False)
    lam, vec = np.linalg.eigh(C)
    lam, vec = lam[::-1], vec[:, ::-1]
    n_obs, p = V.shape
    n_eff = n_obs / H  # overlapping horizons: roughly one independent row per H bars
    mp_edge = (1 + np.sqrt(p / n_eff)) ** 2
    pr = lam.sum() ** 2 / (lam**2).sum()
    ic = np.array([np.corrcoef(V[:, j], value[val])[0, 1] for j in range(p)])
    print(f"\n{'=' * 110}\n{interval} [{tag}]: {p} signals, trade horizon {H} bars, validation n={n_obs:,}")
    print(f"eigenvalues: {', '.join(f'{x:.2f}' for x in lam[:8])} ...  first component {lam[0] / lam.sum():.0%};"
          f" participation ratio {pr:.1f} of {p}; noise edge (MP) {mp_edge:.2f}; above it: {(lam > mp_edge).sum()}")
    top = np.argsort(-np.abs(vec[:, 0]))[:6]
    print("first eigenvector's heaviest loadings: " + ", ".join(f"{names[j]} {vec[j, 0]:+.2f}" for j in top))
    order = np.argsort(-ic)
    print("validation IC, best: " + ", ".join(f"{names[j]} {ic[j]:+.3f}" for j in order[:6]))
    print("validation IC, worst: " + ", ".join(f"{names[j]} {ic[j]:+.3f}" for j in order[-3:]))
    print(f"IC standard error ~ {1 / np.sqrt(n_eff):.3f}")

    # clusters of near-duplicate signals
    dist = np.clip(1 - C, 0, 2)
    np.fill_diagonal(dist, 0)
    cl = fcluster(linkage(squareform(dist, checks=False), "average"), t=0.4, criterion="distance")
    print(f"clusters at |corr| > 0.6: {cl.max()} independent views")

    unit = d["_base"].to_numpy() * np.sqrt(H) * 1.5
    cost = d.family.map(COST_V).to_numpy() * d["_base"].to_numpy() / np.sqrt(MINUTES[interval] / 5) / unit

    j = order[0]
    trade(f"{tag}: best single ({names[j]})", d, Z[:, j], fit_block, val, te, Rl, Rs, cost, H, rows, interval)
    trade(f"{tag}: equal weight", d, Z.mean(1), fit_block, val, te, Rl, Rs, cost, H, rows, interval)
    Sh = LedoitWolf().fit(V).covariance_
    w = np.linalg.solve(Sh, ic)
    trade(f"{tag}: inverse-covariance", d, Z @ w, fit_block, val, te, Rl, Rs, cost, H, rows, interval)
    k = max(1, int((lam > mp_edge).sum()))
    comps = Z @ vec[:, :k]
    cic = np.array([np.corrcoef(comps[val][:, i], value[val])[0, 1] for i in range(k)])
    trade(f"{tag}: eigen (top {k})", d, comps @ cic, fit_block, val, te, Rl, Rs, cost, H, rows, interval)
    from sklearn.linear_model import LogisticRegression
    yv = (value[val] > 0).astype(float)
    stk = LogisticRegression(C=0.05, max_iter=2000).fit(V, yv)
    trade(f"{tag}: stacked", d, Z @ stk.coef_[0], fit_block, val, te, Rl, Rs, cost, H, rows, interval)
    calm = d["short"].to_numpy() <= np.nanmedian(d["short"].to_numpy()[val])
    wr = {}
    for nm, m in (("calm", calm), ("volatile", ~calm)):
        vv = val & m
        ic_r = np.array([np.corrcoef(Z[vv][:, j], value[vv])[0, 1] for j in range(p)])
        wr[nm] = np.linalg.solve(LedoitWolf().fit(Z[vv]).covariance_, np.nan_to_num(ic_r))
    trade(f"{tag}: regime", d, np.where(calm, Z @ wr["calm"], Z @ wr["volatile"]), fit_block, val, te,
          Rl, Rs, cost, H, rows, interval)
    # confluence: one vote per cluster (its mean signal), trade when 70% of votes agree
    votes = np.column_stack([np.sign(Z[:, cl == c].mean(1)) for c in range(1, cl.max() + 1)])
    agree = votes.mean(1)
    conf = np.where(agree >= 0.7, 1.0, np.where(agree <= -0.7, -1.0, 0.0)) * np.abs(Z @ w)
    side = np.sign(conf)
    g = np.where(side == 1, Rl, np.where(side == -1, Rs, np.nan))
    taken = thin(d, te & (side != 0) & ~np.isnan(g), H)
    x = (g - cost)[taken]
    se = x.std(ddof=1) / np.sqrt(max(len(x), 2))
    half = d["_half"].to_numpy()
    a, b = (g - cost)[taken & (half == 0)].mean(), (g - cost)[taken & (half == 1)].mean()
    print(f"  {'confluence >= 70%':<22} n={len(x):>5} net {x.mean():+.3f} +- {se:.3f} t={x.mean() / se:+.1f}"
          f" | {a:+.2f} {b:+.2f} | win {np.mean(x > 0):.0%}  ({cl.max()} votes; agreement on "
          f"{np.mean(np.abs(agree[te]) >= 0.7):.0%} of test bars)")
    rows.append(dict(interval=interval, combo=f"{tag}: confluence", n=len(x), net=x.mean(), se=se, t=x.mean() / se, a=a, b=b))
    uncond = [(Rl - cost)[thin(d, te & ~np.isnan(Rl), H)].mean(), (Rs - cost)[thin(d, te & ~np.isnan(Rs), H)].mean()]
    print(f"  unconditional: always long {uncond[0]:+.3f}, always short {uncond[1]:+.3f} (net)")


if __name__ == "__main__":
    rows: list[dict] = []
    for interval in ("15m", "1h"):
        run(interval, SERIES, rows)
    run("1d", DAILY, rows)
    Path(".data/research").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(".data/research/ensemble.csv", index=False)
