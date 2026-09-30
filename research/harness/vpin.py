"""VPIN as a warning of shocks and volatility bursts, on real aggressor-tagged trades.

VPIN (Easley, Lopez de Prado & O'Hara, "Flow Toxicity and Liquidity in a High-Frequency World",
RFS 2012; "The Microstructure of the 'Flash Crash'", JPM 2011) was built to warn of liquidity
events, not to call direction. This repo tested order flow for direction only (orderflow.md,
directional-questions.md: null). Here it is asked what it was built for: does flow toxicity warn of
shocks, range blowouts and volatility bursts, **beyond what the production shock forecaster
(structures/learning/shocks.py) already knows**, and beyond plain volume and trade intensity?

Data: Binance USDT-M futures, BTC/ETH/SOL, 2025-09 to 2026-08, from research/harness/orderflow.py:
1-minute bars carrying the **true taker buy and sell volume** (`is_buyer_maker`). A volume bucket of
1/50 of a day's volume spans about half an hour, so minute resolution is fine enough to split trades
into buckets (a minute straddling a boundary is split pro rata).

Measures:
  vpin (true)   equal-volume buckets of V = ADV / 50 (ADV from the training 60%), n = 50 buckets:
                VPIN = sum |buy - sell| / (n V) over the last n buckets, known once the last bucket
                completes; its CDF is the rank against the trailing 1,500 buckets (about a month)
  vpin_bvc      the same buckets with buy volume by bulk volume classification on 1-minute bars
                (buy share Phi(r / sd)) - what VPIN is when the tape has no aggressor side
  vpin_bar      the bar-level proxy research/harness/ensemble.py used (50 bars of |2 Phi - 1| v)
  shuffled      the true VPIN with each minute's buy share permuted within its day: volumes and
                timing kept, toxicity destroyed (control)
  volume        placebo features (Andersen & Bondarenko 2014: VPIN mostly tracks volume and
                intensity): bar volume and trade count against their trailing median, and the last
                four bars' volume against it

Targets, at 15m and 1h bars (clock time, as production):
  shock         a bar beyond 4x the trailing mean |return| within the next 4 bars - the production
                shock forecaster's own label, its features computed by replaying the bars through the
                production `Shocks` class (models/shocks_train.dataset)
  blowout       a bar range beyond 3x the trailing 100-bar mean range within the next 4 bars
  rv1h, rv4h    realised volatility over the next 1h / 4h from 1-minute returns, against the
                production unit (the EWMA of true range, structures/vol/ranges.py)

Pre-registered pass bar (the docstring is the registration):
  * shock AUC gain of (shock features + volume + VPIN) over (shock features + volume) >= 0.01, the
    day-bootstrap 95% CI above 0, in both halves of the test block - i.e. beyond the forecaster
    AND beyond volume and intensity;
  * and no such gain from the shuffled VPIN, nor on walks we generate (iid t(3) prices, real volume
    profiles, random buy shares);
  * reported beside it: blowout AUC, incremental out-of-sample R^2 for log realised volatility, the
    flash-crash lift P(shock | VPIN CDF > 0.9) / P(shock), and whether VPIN rises *before* one-minute
    shocks (5-60 minutes) or only with them; robustness over bucket size (ADV/25, /50, /100) and
    window (25, 50, 100).

Walk-forward: models fit on the first 60% of time (symbols pooled per interval), scored on the last
40%, halves of it reported. Gradient boosting as the shock forecaster itself uses.

Run on the lab (orderflow data in $HOME/till_infinity/data/orderflow):
  PART=run INTERVAL=15m ORDERFLOW=$HOME/till_infinity/data/orderflow python research/harness/vpin.py
  PART=run INTERVAL=1h ...        PART=lead ...  (lead-lag and robustness)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import orderflow as of

from till_infinity.models import shocks_train as st
from till_infinity.prices.models import Bar
from till_infinity.structures.learning import shocks as sh
from till_infinity.structures.vol.ranges import Ranges

PART = os.environ.get("PART", "run")
INTERVAL = os.environ.get("INTERVAL", "15m")
of.OUT = Path(os.path.expanduser(os.environ.get("ORDERFLOW", "~/till_infinity/data/orderflow")))
SYMBOLS = tuple(os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(","))
MINUTES = {"15m": 15, "1h": 60}
BUCKET_FRAC, WINDOW, CDF_BUCKETS = 1 / 50, 50, 1500
SPLIT = 0.6
RNG = np.random.default_rng(5)

BASE = list(sh.NAMES)
VOLUME = ["vol_rel", "trades_rel", "vol4_rel"]
TRUE = ["vpin", "vpin_cdf"]
SETS = {
    "base": BASE,
    "base+vpin": BASE + TRUE,
    "base+volume": BASE + VOLUME,
    "base+volume+vpin": BASE + VOLUME + TRUE,
    "base+volume+shuffled": BASE + VOLUME + ["shuf", "shuf_cdf"],
    "base+volume+bvc": BASE + VOLUME + ["bvc", "bvc_cdf"],
    "base+volume+barproxy": BASE + VOLUME + ["vpin_bar"],
}


# --------------------------------------------------------------------------------------------- data

def minutes(symbol: str) -> pd.DataFrame:
    """1-minute bars with true taker buy/sell volume (orderflow.py's store), every minute present."""
    m = of.load(symbol)
    m["trades"] = m["nb"] + m["ns"]
    return m[["open", "high", "low", "close", "buy", "sell", "trades"]]


def walk_minutes(like: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Our control: iid t(3) prices at a fixed scale, the real series' volume and trade counts, and a
    buy share drawn independently of everything - no toxicity by construction."""
    rng = np.random.default_rng(seed)
    n = len(like)
    lr = np.log(like["close"].to_numpy())
    scale = np.nanmedian(np.abs(np.diff(lr))) / 0.82 or 5e-4
    r = rng.standard_t(3, n) * scale
    close = 100.0 * np.exp(np.cumsum(r))
    opn = np.r_[100.0, close[:-1]]
    wick = np.abs(rng.standard_t(3, (n, 2))) * scale * 0.5
    vol = (like["buy"] + like["sell"]).to_numpy()
    share = rng.beta(20, 20, n)
    return pd.DataFrame({
        "open": opn, "close": close,
        "high": np.maximum(opn, close) * np.exp(wick[:, 0]),
        "low": np.minimum(opn, close) * np.exp(-wick[:, 1]),
        "buy": vol * share, "sell": vol * (1 - share), "trades": like["trades"].to_numpy(),
    }, index=like.index)


# --------------------------------------------------------------------------------------------- vpin

def buckets(minute: np.ndarray, vol: np.ndarray, buy: np.ndarray, size: float, n: int):
    """Equal-volume buckets: (completion time in seconds, VPIN over the last n buckets, bucket
    duration in minutes). A minute straddling a boundary is split pro rata."""
    cum = np.cumsum(vol)
    cumbuy = np.cumsum(buy)
    k = np.arange(1, int(cum[-1] // size) + 1) * size
    p = np.searchsorted(cum, k)  # the minute in which each boundary is crossed
    prev = np.where(p > 0, cum[np.maximum(p - 1, 0)], 0.0)
    prevbuy = np.where(p > 0, cumbuy[np.maximum(p - 1, 0)], 0.0)
    frac = np.where(vol[p] > 0, (k - prev) / np.where(vol[p] > 0, vol[p], 1.0), 1.0)
    at = prevbuy + frac * buy[p]  # cumulative buy volume at each boundary
    bbuy = np.diff(np.r_[0.0, at])
    imb = np.abs(2 * bbuy - size) / size
    vp = pd.Series(imb).rolling(n, min_periods=n).mean().to_numpy()
    done = (minute[p] + 1) * 60.0  # known at the end of the minute that completes it
    return done, vp


def as_of(done: np.ndarray, values: np.ndarray, times: np.ndarray) -> np.ndarray:
    """The last completed bucket's value at each time (causal); NaN before the first."""
    i = np.searchsorted(done, times, side="right") - 1
    out = np.full(len(times), np.nan)
    ok = i >= 0
    out[ok] = values[i[ok]]
    return out


def cdf(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rolling(CDF_BUCKETS, min_periods=CDF_BUCKETS // 3).rank(pct=True).to_numpy()


def flows(m: pd.DataFrame, train_end: int, frac: float = BUCKET_FRAC, n: int = WINDOW) -> dict:
    """Every VPIN variant's buckets for one series: {name: (done, vpin, vpin_cdf)}."""
    minute = m.index.to_numpy()
    vol = (m["buy"] + m["sell"]).to_numpy()
    days = max((minute[train_end] - minute[0]) / 1440.0, 1.0)
    size = vol[:train_end].sum() / days * frac
    out = {}
    done, vp = buckets(minute, vol, m["buy"].to_numpy(), size, n)
    out["vpin"] = (done, vp, cdf(vp))
    # shuffled: each minute's buy share permuted within its day
    share = np.where(vol > 0, m["buy"].to_numpy() / np.where(vol > 0, vol, 1.0), 0.5)
    order = np.lexsort((RNG.random(len(minute)), minute // 1440))
    done_s, vp_s = buckets(minute, vol, vol * share[order], size, n)
    out["shuf"] = (done_s, vp_s, cdf(vp_s))
    # bulk volume classification on 1-minute bars
    lr = np.log(m["close"].to_numpy())
    r = np.r_[0.0, np.diff(lr)]
    sd = pd.Series(r).rolling(1000, min_periods=200).std().shift(1).to_numpy()
    bshare = np.where(np.isfinite(sd) & (sd > 0), norm.cdf(r / np.where(sd > 0, sd, 1.0)), 0.5)
    done_b, vp_b = buckets(minute, vol, vol * bshare, size, n)
    out["bvc"] = (done_b, vp_b, cdf(vp_b))
    return out


# --------------------------------------------------------------------------------------------- bars

def bars(m: pd.DataFrame, interval: str) -> pd.DataFrame:
    step = MINUTES[interval]
    g = m.groupby(m.index // step)
    b = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": (g["buy"].sum() + g["sell"].sum()),
        "trades": g["trades"].sum(),
    })
    b.index = b.index * step  # the minute the bar opens
    return b[b["volume"] > 0]


def bar_frame(sym: str, m: pd.DataFrame, interval: str, fl: dict) -> pd.DataFrame:
    """Per-bar features known at the bar's close, and the non-shock targets."""
    b = bars(m, interval)
    step = MINUTES[interval]
    close_t = (b.index.to_numpy() + step) * 60.0
    f = pd.DataFrame(index=b.index)
    f["when"] = close_t
    for name, (done, vp, vc) in fl.items():
        f[name] = as_of(done, vp, close_t)
        f[f"{name}_cdf"] = as_of(done, vc, close_t)
    # the bar-level proxy research/harness/ensemble.py used
    r = np.log(b["close"]).diff()
    sd = r.rolling(100, min_periods=50).std()
    imb = (2 * norm.cdf(r / sd) - 1)
    v = b["volume"]
    f["vpin_bar"] = (v * np.abs(imb)).rolling(50, min_periods=25).sum() / v.rolling(50, min_periods=25).sum()
    med = lambda s: s.shift(1).rolling(500, min_periods=100).median()  # noqa: E731
    f["vol_rel"] = np.log(v / med(v))
    f["trades_rel"] = np.log(b["trades"] / med(b["trades"]))
    f["vol4_rel"] = np.log(v.rolling(4).sum() / (4 * med(v)))
    # the production unit, then the targets
    ranges, unit = Ranges(), []
    for o, h, lo, c in zip(b["open"], b["high"], b["low"], b["close"], strict=True):
        ranges.observe(float(o), float(h), float(lo), float(c))
        unit.append(ranges.ewma_tr_bps)
    f["unit_bps"] = unit
    rng_ = (b["high"] - b["low"]) / b["close"]
    base = rng_.shift(1).rolling(100, min_periods=50).mean()
    ahead = pd.concat([rng_.shift(-k) for k in range(1, 5)], axis=1).max(axis=1)
    f["blowout"] = np.where(ahead.notna() & base.notna(), (ahead > 3 * base).astype(float), np.nan)
    lm = np.log(m["close"].to_numpy())
    rm = np.r_[0.0, np.diff(lm)] ** 2
    csum = np.r_[0.0, np.cumsum(rm)]
    pos = np.searchsorted(m.index.to_numpy(), b.index.to_numpy() + step)  # first minute after the close
    for label, h in (("rv1h", 60), ("rv4h", 240)):
        end = pos + h
        ok = end < len(csum)
        rv = np.full(len(pos), np.nan)
        rv[ok] = np.sqrt(csum[end[ok]] - csum[pos[ok]]) * 1e4
        f[label] = rv
    nxt = np.log(b["close"].shift(-4) / b["close"])  # next 4 bars' move, for adverse size
    f["move4"] = np.abs(nxt) / (f["unit_bps"] / 1e4)
    f["sym"] = sym
    return f.reset_index(drop=True)


def dataset(frames: dict[str, pd.DataFrame], interval: str, fl_by: dict) -> pd.DataFrame:
    """The production shock forecaster's rows and label, joined to the flow features."""
    series = {}
    for sym, m in frames.items():
        b = bars(m, interval)
        series[(sym, interval)] = [Bar(int(t * 60), float(o), float(h), float(lo), float(c))
                                   for t, o, h, lo, c in zip(b.index, b["open"], b["high"], b["low"],
                                                             b["close"], strict=True)]
    rows = st.dataset(series)
    x = pd.DataFrame(np.array(rows.x, dtype=float), columns=BASE)
    x["when"], x["sym"], x["shock"] = rows.when, [k.split("|")[0] for k in rows.key], rows.y
    feats = pd.concat([bar_frame(sym, m, interval, fl_by[sym]) for sym, m in frames.items()])
    return x.merge(feats, on=["sym", "when"], how="inner").sort_values("when").reset_index(drop=True)


# --------------------------------------------------------------------------------------------- scoring

def fit(train: pd.DataFrame, cols: list[str], target: str):
    model = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                           min_samples_leaf=300, random_state=0)
    model.fit(train[cols], train[target])
    return model


def day_boot_diff(y, pa, pb, when, draws=300, seed=1):
    """AUC(b) - AUC(a) with a 95% interval from resampling whole days."""
    days = (np.asarray(when) // 86_400).astype(int)
    uniq = np.unique(days)
    by = {d: np.flatnonzero(days == d) for d in uniq}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        idx = np.concatenate([by[d] for d in rng.choice(uniq, len(uniq))])
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        out.append(roc_auc_score(yy, pb[idx]) - roc_auc_score(yy, pa[idx]))
    return float(roc_auc_score(y, pb) - roc_auc_score(y, pa)), np.quantile(out, [0.025, 0.975])


def contest(d: pd.DataFrame, target: str, label: str) -> dict:
    d = d.dropna(subset=[target])
    cut = d["when"].quantile(SPLIT)
    train, test = d[d["when"] < cut], d[d["when"] >= cut].reset_index(drop=True)
    mid = test["when"].median()
    y = test[target].to_numpy()
    preds = {name: fit(train, cols, target).predict_proba(test[cols])[:, 1] for name, cols in SETS.items()}
    print(f"\n  {label} · {target} · train {len(train):,} test {len(test):,} · rate {y.mean():.3f}", flush=True)
    for name, p in preds.items():
        print(f"    {name:22s} AUC {roc_auc_score(y, p):.4f}", flush=True)
    res = {}
    for a, b in (("base", "base+vpin"), ("base+volume", "base+volume+vpin"),
                 ("base+volume", "base+volume+shuffled"), ("base+volume", "base+volume+bvc"),
                 ("base+volume", "base+volume+barproxy"), ("base", "base+volume")):
        g, ci = day_boot_diff(y, preds[a], preds[b], test["when"].to_numpy())
        halves = []
        for part in (test["when"] < mid, test["when"] >= mid):
            yy = y[part.to_numpy()]
            halves.append(roc_auc_score(yy, preds[b][part.to_numpy()]) - roc_auc_score(yy, preds[a][part.to_numpy()])
                          if 0 < yy.mean() < 1 else float("nan"))
        res[(a, b)] = (g, ci, halves)
        print(f"    gain {b:22s} over {a:14s} {g:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}] halves {halves[0]:+.4f} / "
              f"{halves[1]:+.4f}", flush=True)
    return {"preds": preds, "test": test, "res": res}


def rv_r2(d: pd.DataFrame, label: str) -> None:
    """Out-of-sample R^2 for log realised volatility, over the production unit alone."""
    for target in ("rv1h", "rv4h"):
        e = d.dropna(subset=[target, "vpin", "vpin_cdf", "vol_rel", "trades_rel", "vol4_rel", "unit_bps"])
        e = e[(e[target] > 0) & (e["unit_bps"] > 0)]
        cut = e["when"].quantile(SPLIT)
        tr, te = e[e["when"] < cut], e[e["when"] >= cut]
        yt, ye = np.log(tr[target]), np.log(te[target])

        def r2(cols):
            X = np.column_stack([np.ones(len(tr)), np.log(tr["unit_bps"])] + [tr[c] for c in cols])
            Z = np.column_stack([np.ones(len(te)), np.log(te["unit_bps"])] + [te[c] for c in cols])
            beta = np.linalg.lstsq(X, yt, rcond=None)[0]
            res = ye - Z @ beta
            return 1 - (res ** 2).sum() / ((ye - ye.mean()) ** 2).sum()

        base, vol, vp, both, shuf = (r2([]), r2(VOLUME), r2(TRUE), r2(VOLUME + TRUE),
                                     r2(VOLUME + ["shuf", "shuf_cdf"]))
        print(f"    {label} {target}: OOS R^2 unit {base:.4f} | +vpin {vp - base:+.4f} | +volume {vol - base:+.4f}"
              f" | +volume+vpin over +volume {both - vol:+.4f} | +volume+shuffled over +volume {shuf - vol:+.4f}",
              flush=True)


def flash(out: dict, d: pd.DataFrame, label: str) -> None:
    """P(shock | VPIN CDF > 0.9) / P(shock), and the adverse move after, on the test block."""
    test = out["test"]
    for name in ("vpin", "shuf", "bvc"):
        hi = test[f"{name}_cdf"] > 0.9
        rate, lift = test["shock"].mean(), test.loc[hi, "shock"].mean() / max(test["shock"].mean(), 1e-9)
        mv = test.loc[hi, "move4"].mean() / test["move4"].mean()
        bl = test.loc[hi, "blowout"].mean() / max(test["blowout"].mean(), 1e-9)
        vhi = test["vol_rel"] > test["vol_rel"].quantile(0.9)
        vl = test.loc[vhi, "shock"].mean() / max(rate, 1e-9)
        print(f"    {label} {name:5s} CDF>0.9: {hi.mean():.1%} of bars | shock lift {lift:.2f}x (volume top decile "
              f"{vl:.2f}x) | blowout lift {bl:.2f}x | next-4-bar |move| {mv:.2f}x", flush=True)


def run() -> None:
    real = {s: minutes(s) for s in SYMBOLS}
    walks = {f"WALK{i}": walk_minutes(real[s], 100 + i) for i, s in enumerate(SYMBOLS)}
    for universe, frames in (("real", real), ("walks", walks)):
        fl_by = {s: flows(m, int(len(m) * SPLIT)) for s, m in frames.items()}
        d = dataset(frames, INTERVAL, fl_by)
        print(f"\n{'=' * 110}\n{universe} · {INTERVAL} · {len(d):,} rows · {', '.join(frames)}", flush=True)
        out = contest(d, "shock", universe)
        contest(d, "blowout", universe)
        rv_r2(d, universe)
        flash(out, d, universe)
        if universe == "real":
            for sym in real:
                sub = d[d["sym"] == sym]
                if len(sub) > 2000:
                    contest(sub, "shock", sym)


def lead() -> None:
    """Does VPIN rise *before* one-minute shocks, or only with them? And robustness of the gain."""
    print("LEAD-LAG: VPIN CDF around one-minute shocks (|r| > 10x trailing mean), against all minutes", flush=True)
    for sym in SYMBOLS:
        m = minutes(sym)
        fl = flows(m, int(len(m) * SPLIT))
        lr = np.log(m["close"].to_numpy())
        ar = np.abs(np.r_[0.0, np.diff(lr)])
        base = pd.Series(ar).shift(1).rolling(1440, min_periods=600).mean().to_numpy()
        ev = np.flatnonzero(ar > 10 * base)
        keep, last = [], -10**9
        for e in ev:  # at least an hour apart
            if e - last >= 60:
                keep.append(e)
                last = e
        ev = np.array(keep)
        minute = m.index.to_numpy()
        vol = (m["buy"] + m["sell"]).to_numpy()
        vol60 = pd.Series(vol).rolling(60).sum()
        vrel = (vol60 / vol60.shift(60).rolling(1440, min_periods=600).median()).to_numpy()
        rnd = RNG.choice(np.arange(2000, len(minute) - 100), 5000, replace=False)
        print(f"\n  {sym}: {len(ev)} shocks", flush=True)
        for name in ("vpin", "shuf", "bvc"):
            done, _, vc = fl[name]
            cells = []
            for lag in (-60, -30, -15, -5, 0, 5, 15):
                t_ev = (minute[ev] + 1 + lag) * 60.0
                t_rn = (minute[rnd] + 1 + lag) * 60.0
                a = np.nanmean(as_of(done, vc, t_ev))
                b = np.nanmean(as_of(done, vc, t_rn))
                cells.append(f"{lag:+d}m {a - b:+.3f}")
            print(f"    {name:5s} CDF, shocks minus random minutes: " + " ".join(cells), flush=True)
        cells = []
        for lag in (-60, -30, -15, -5, 0):
            a = np.nanmean(vrel[np.clip(ev + lag, 0, len(vrel) - 1)])
            b = np.nanmean(vrel[np.clip(rnd + lag, 0, len(vrel) - 1)])
            cells.append(f"{lag:+d}m {a / b:.2f}x")
        print("    60m volume vs its norm, shocks over random minutes: " + " ".join(cells), flush=True)

    print("\nROBUSTNESS: shock AUC gain of base+volume+vpin over base+volume, 15m, real", flush=True)
    real = {s: minutes(s) for s in SYMBOLS}
    for frac in (1 / 25, 1 / 50, 1 / 100):
        for n in (25, 50, 100):
            fl_by = {s: flows(m, int(len(m) * SPLIT), frac, n) for s, m in real.items()}
            d = dataset(real, "15m", fl_by).dropna(subset=["shock"])
            cut = d["when"].quantile(SPLIT)
            tr, te = d[d["when"] < cut], d[d["when"] >= cut]
            y = te["shock"].to_numpy()
            pa = fit(tr, SETS["base+volume"], "shock").predict_proba(te[SETS["base+volume"]])[:, 1]
            pb = fit(tr, SETS["base+volume+vpin"], "shock").predict_proba(te[SETS["base+volume+vpin"]])[:, 1]
            g, ci = day_boot_diff(y, pa, pb, te["when"].to_numpy(), draws=200)
            print(f"  bucket ADV/{round(1 / frac)} window {n}: {g:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]", flush=True)


if __name__ == "__main__":
    lead() if PART == "lead" else run()
