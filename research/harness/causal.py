"""Causal inference: which of the shock forecaster's inputs are causes, and which are symptoms?

research/docs/findings.md: the desk forecasts risk and not direction, and the shock forecaster works
(AUC 0.73-0.76). Prediction is not mechanism. A wider spread predicts a bigger bar, but that alone
cannot say whether withdrawn liquidity *makes* price move, or a moving price makes dealers withdraw.
Only a variation in one that the other did not cause can separate them. This harness looks for such
variation in the calendar and the broker's own mechanics.

Designs, each with its identifying assumption, pre-registered:

  D1 news   A scheduled release's time is fixed in advance, and its surprise z (actual - consensus,
            over its own history; surprise.md) is as good as random given the consensus.
            (a) The pre-release window: dealers widen spreads *before* a known release whose
                content nobody knows yet. That is liquidity withdrawal without information. Does
                volatility rise with it, against the same weekday and time in event-free weeks?
            (b) |z| -> spread at the release bar and |z| -> volatility after it. Both are causal
                effects of information. A mediation split (does spread carry the |z| effect on
                later volatility?) needs sequential ignorability and is reported as descriptive only.
            (c) At 3m: which peaks and decays first around the release, the spread or |r|?
  D2 roll   The broker's 17:00 New York rollover widens FX spreads mechanically every weekday
            (rollover.md), for no reason in the market. Assumption: once the pre-rollover hour's
            volatility, the pair and the weekday are fixed, a day's spike size is unrelated to how
            volatile the following hour would have been (selection on observables). Outcome:
            realised |r| in bars +3..+6 after 17:00, after the spread has normalised, so bid-based
            bars cannot contaminate it mechanically. Placebo spike at 15:00 New York, a placebo
            outcome before the cutoff, and a clock-matched comparison with crypto and Deriv, which
            have no rollover (a design role, not a null claim). Walks we generate with a
            mechanical, price-independent daily spike and bid-based bars measure what the harness
            reads when there is no mechanism.
  D3 fund   Binance perpetual funding settles at 00/08/16 UTC, a schedule nobody chooses. Treatment
            intensity is the rate being paid. Does funding pressure move price around settlement
            (signed by who pays), in a dose-response on |f|, against the same funding value at
            non-settlement hours? Dislocation is the perp's own move: there is no spot series here
            to measure the basis.
  D4 crowd  Exogenous crowding shifts (index inclusions, reporting surprises) are not in our data;
            the CFTC report's timing is fixed but its content is positioning already held. Stated as
            not identifiable here. The density-dependence test is the ecology program's
            (ecology.md).
  D5 graph  PCMCI (tigramite, ParCorr) over the shock forecaster's inputs at 1h: log |r|, log spread
            ratio, log volume ratio, volatility state, shock flag. **Discovery, not
            identification**: an edge is a hypothesis, checked against D1-D2 and against a walk
            whose true graph we built.

Pass bar for "causal" (pre-registered): coefficient |t| >= 3 with day-clustered SE, the same sign in
both halves, the placebo |t| < 2, the walk control |t| < 2, and BH q < 0.05 across every design x
outcome here.

Run on the lab:
  PART=roll|news|fund|pcmci SEQLAB=$HOME/till_infinity/data/seqlab \
      CALENDAR=$HOME/till_infinity/data/surprise/calendar.jsonl \
      CROWD=$HOME/till_infinity/data/crowding python research/harness/causal.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PART = os.environ.get("PART", "roll")
SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
CALENDAR = Path(os.environ.get("CALENDAR", ".data/surprise/calendar.jsonl"))
CROWD = Path(os.environ.get("CROWD", ".data/crowding"))
OUT = Path(os.environ.get("OUT", ".data/causal"))
NY = ZoneInfo("America/New_York")
RNG = np.random.default_rng(11)

FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP"]
COMPARE = {"crypto": ["BTCUSD", "ETHUSD"], "deriv": ["Volatility_75_Index", "Volatility_25_Index",
                                                   "Step_Index", "Jump_50_Index"]}
RESULTS: list[dict] = []  # every design x outcome, for BH


# ------------------------------------------------------------------ data

def bars(sym: str, iv: str) -> pd.DataFrame | None:
    path = SEQLAB / f"{sym}.{iv}.npz"
    if not path.exists():
        return None
    z = np.load(path)
    d = pd.DataFrame({k: z[k].astype(float) for k in ("time", "open", "high", "low", "close", "spread")})
    d = d.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return frame(d)


def frame(d: pd.DataFrame) -> pd.DataFrame:
    """Returns in the production unit (EWMA true range of the bars before), spread against its own
    trailing median, and the New York clock."""
    c = np.log(d["close"].to_numpy())
    prev = np.r_[np.nan, d["close"].to_numpy()[:-1]]
    tr = np.nanmax(np.column_stack([d["high"] - d["low"], np.abs(d["high"] - prev), np.abs(d["low"] - prev)]),
                   axis=1) / d["close"]
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().shift(1).to_numpy()
    d["r"] = np.r_[np.nan, np.diff(c)]
    d["ar"] = np.abs(d["r"]) / sig
    sp = d["spread"].replace(0, np.nan)
    d["sratio"] = sp / sp.rolling(500, min_periods=100).median()
    d["vstate"] = np.log(sig / pd.Series(sig).rolling(500, min_periods=100).mean().to_numpy())
    t = pd.to_datetime(d["time"], unit="s", utc=True)
    local = t.dt.tz_convert(NY)
    d["ny_h"] = local.dt.hour + local.dt.minute / 60.0
    d["ny_date"] = local.dt.date
    d["wd"] = local.dt.weekday
    d["day"] = (d["time"] // 86400).astype(int)
    return d


def ols(y, X, groups):
    """OLS with day-clustered SE. Returns (coef, t) per column, or None if too few rows."""
    import statsmodels.api as sm

    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    if ok.sum() < 50:
        return None
    m = sm.OLS(y[ok], sm.add_constant(X[ok], has_constant="add")).fit(
        cov_type="cluster", cov_kwds={"groups": np.asarray(groups)[ok]})
    return m.params[1:], m.tvalues[1:], int(ok.sum())


def record(design, outcome, coef, t, n, **extra):
    from scipy.stats import norm

    RESULTS.append({"design": design, "outcome": outcome, "coef": float(coef), "t": float(t),
                    "p": float(2 * norm.sf(abs(t))), "n": n, **extra})
    print(f"    {design:6s} {outcome:44s} coef {coef:+.4f} t {t:+.2f} n {n:,}"
          + "".join(f" | {k} {v}" for k, v in extra.items()), flush=True)


def fe(values, prefix):
    """One-hot fixed effects, first level dropped."""
    s = pd.Series(values).astype(str)
    dm = pd.get_dummies(s, prefix=prefix, drop_first=True, dtype=float)
    return dm.to_numpy()


def save():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{PART}.json").write_text(json.dumps(RESULTS, default=str))


# ------------------------------------------------------------------ D2: the rollover

def rollover_days(d: pd.DataFrame, cutoff: float, step_h: float) -> pd.DataFrame:
    """Per New York weekday date: the spike around `cutoff`, pre and post volatility."""
    rows = []
    rel = (d["ny_h"] - cutoff) / step_h  # bar index relative to the cutoff, in bars
    d = d.assign(k=np.round(rel).astype(int))
    for date, g in d[(d["k"] >= -12) & (d["k"] <= 8) & (d["wd"] < 5)].groupby("ny_date"):
        g = g.set_index("k")
        if not {-12, -8, -3, -1, 0, 2, 3, 6}.issubset(g.index):
            continue
        spike = g.loc[-1:2, "sratio"].max()
        rows.append({
            "date": date, "day": int(g.loc[0, "day"]), "wd": int(g.loc[0, "wd"]),
            "spike": spike,
            "pre": g.loc[-8:-3, "ar"].mean(),        # control: the hour before, spread still normal
            "placebo_out": g.loc[-12:-9, "ar"].mean(),  # before the pre window: cannot be caused
            "post": g.loc[3:6, "ar"].mean(),         # after the spread normalised
            "spike_bar": g.loc[0, "ar"],             # the spike bar itself: contaminated by design
        })
    return pd.DataFrame(rows)


def part_roll():
    print("D2 - the rollover as an exogenous liquidity shock (15m bars, New York clock)", flush=True)
    for iv, step in (("15m", 0.25),):
        pooled = []
        for sym in FX:
            d = bars(sym, iv)
            if d is None:
                continue
            for cutoff, label in ((17.0, "rollover"), (15.0, "placebo 15:00")):
                days = rollover_days(d, cutoff, step)
                if len(days):
                    pooled.append(days.assign(sym=sym, cutoff=label))
        if not pooled:
            print("  no FX data", flush=True)
            return
        allp = pd.concat(pooled, ignore_index=True)
        for label in ("rollover", "placebo 15:00"):
            p = allp[allp["cutoff"] == label].copy()
            p = p[np.isfinite(p["spike"]) & (p["spike"] > 0)]
            print(f"\n  {label}: {len(p):,} pair-days, median spike {p['spike'].median():.1f}x the normal spread", flush=True)
            X = np.column_stack([np.log(p["spike"]), p["pre"], fe(p["sym"], "s"), fe(p["wd"], "w")])
            for outcome in ("post", "placebo_out", "spike_bar"):
                got = ols(p[outcome].to_numpy(), X, p["day"])
                if got is None:
                    continue
                coef, t, n = got
                halves = []
                cut = p["day"].median()
                for part in (p[p["day"] < cut], p[p["day"] >= cut]):
                    Xh = np.column_stack([np.log(part["spike"]), part["pre"], fe(part["sym"], "s"), fe(part["wd"], "w")])
                    h = ols(part[outcome].to_numpy(), Xh, part["day"])
                    halves.append(f"{h[0][0]:+.4f}" if h else "n/a")
                record("roll", f"{label}: log spike -> {outcome}", coef[0], t[0], n, halves="/".join(halves))
    # clock-matched comparison: markets without a rollover, same New York clock
    print("\n  comparison markets at the same New York clock (no rollover): spike and post-vol", flush=True)
    for fam, syms in COMPARE.items():
        pooled = []
        for sym in syms:
            d = bars(sym, "15m")
            if d is None:
                continue
            days = rollover_days(d, 17.0, 0.25)
            if len(days):
                pooled.append(days.assign(sym=sym))
        if not pooled:
            continue
        p = pd.concat(pooled, ignore_index=True)
        p = p[np.isfinite(p["spike"]) & (p["spike"] > 0)]
        print(f"   {fam}: {len(p):,} days, median spike {p['spike'].median():.2f}x", flush=True)
        X = np.column_stack([np.log(p["spike"]), p["pre"], fe(p["sym"], "s"), fe(p["wd"], "w")])
        got = ols(p["post"].to_numpy(), X, p["day"])
        if got:
            record("roll", f"{fam} 17:00 NY: log spike -> post", got[0][0], got[1][0], got[2])
    # walks: a mechanical daily spike on bid-based bars, independent of the price
    print("\n  walks we generate: mid is a t(3) walk with GARCH-free constant scale; bid bars carry a "
          "daily 17:00 NY spike of random size, independent of price", flush=True)
    wp = []
    for w in range(6):
        wp.append(rollover_days(walk_frame(w), 17.0, 0.25).assign(sym=f"walk{w}"))
    p = pd.concat(wp, ignore_index=True)
    p = p[np.isfinite(p["spike"]) & (p["spike"] > 0)]
    X = np.column_stack([np.log(p["spike"]), p["pre"], fe(p["sym"], "s"), fe(p["wd"], "w")])
    for outcome in ("post", "spike_bar"):
        got = ols(p[outcome].to_numpy(), X, p["day"])
        if got:
            record("roll", f"walks: log spike -> {outcome}", got[0][0], got[1][0], got[2])
    save()


def walk_frame(w: int, n: int = 60_000) -> pd.DataFrame:
    """Mid: iid t(3) at one scale. Bid bars = mid - spread/2, with the spread normal except a
    random-size spike in the 15m bars around 17:00 New York on weekdays."""
    rng = np.random.default_rng(100 + w)
    t = 1_725_840_000 + 900 * np.arange(n)
    mid = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.0006))
    local = pd.to_datetime(t, unit="s", utc=True).tz_convert(NY)
    nyh = local.hour + local.minute / 60.0
    base = 0.00008 * mid
    spike_day = np.exp(rng.normal(np.log(8), 0.6, n // 96 + 2))
    day_ix = (t - t[0]) // 86400
    spread = base.copy()
    near = (np.abs(nyh - 17.0) <= 0.5) & (local.weekday < 5)
    spread[near] = base[near] * spike_day[day_ix[near]]
    bid_close = mid - spread / 2
    wick = np.abs(rng.standard_t(3, (n, 2))) * 0.0003 * mid[:, None]
    bid_open = np.r_[bid_close[0], bid_close[:-1]]
    hi = np.maximum(bid_open, bid_close) + wick[:, 0]
    lo = np.minimum(bid_open, bid_close) - wick[:, 1] - spread / 2 * near  # the spike dips the bid low
    d = pd.DataFrame({"time": t.astype(float), "open": bid_open, "high": hi, "low": lo, "close": bid_close,
                      "spread": spread / (0.00001 * mid) })
    return frame(d)


# ------------------------------------------------------------------ D1: scheduled news

def events() -> pd.DataFrame:
    rows = [json.loads(line) for line in CALENDAR.open()]
    d = pd.DataFrame(rows)
    d = d[d["actual"].notna() & d["forecast"].notna() & d["currency"].notna()].copy()
    d = d[~d["category"].isin(("engy",))]
    d["t"] = pd.to_datetime(d["date"], utc=True)
    if "ticker" not in d:
        d["ticker"] = d["country"].astype(str) + ":" + d["indicator"].astype(str)
    d = d.drop_duplicates(["ticker", "t"]).sort_values("t")
    d["s"] = d["actual"].astype(float) - d["forecast"].astype(float)
    past = d.groupby("ticker")["s"].transform(lambda x: x.shift(1).expanding(6).std())
    d["z"] = d["s"] / past.replace(0, np.nan)
    return d[np.isfinite(d["z"])]


def part_news():
    print("D1 - scheduled releases (15m and 3m bars)", flush=True)
    ev = events()
    ev = ev[ev["importance"].astype(float) >= 1]
    by = ev.groupby(["currency", "t"]).agg(z=("z", lambda s: float(np.max(np.abs(s)))),
                                           n=("z", "size")).reset_index()
    print(f"  {len(by):,} high-importance release times with a surprise", flush=True)
    for iv, step_min in (("15m", 15), ("3m", 3)):
        rows_pre, rows_post, prof = [], [], []
        for sym in FX:
            d = bars(sym, iv)
            if d is None:
                continue
            idx = pd.to_datetime(d["time"], unit="s", utc=True)
            pos = pd.Series(np.arange(len(d)), index=idx)
            ccys = (sym[:3], sym[3:])
            mine = by[by["currency"].isin(ccys)]
            ev_times = set(mine["t"])
            for _, e in mine.iterrows():
                i = idx.searchsorted(e["t"])
                if i < 30 or i + 25 >= len(d) or idx[i] - e["t"] > pd.Timedelta(minutes=step_min):
                    continue
                # a control: the same weekday and time one and two weeks earlier, if event-free
                ctl = []
                for wk in (1, 2):
                    tc = e["t"] - pd.Timedelta(weeks=wk)
                    j = idx.searchsorted(tc)
                    if 30 <= j < len(d) - 25 and abs((idx[j] - tc).total_seconds()) < 60 * step_min \
                            and not any(abs((tc - x).total_seconds()) < 7200 for x in ev_times):
                        ctl.append(j)
                pre_k = range(-2, 0) if iv == "15m" else range(-10, 0)
                post_k = range(1, 5) if iv == "15m" else range(5, 21)
                s_pre = d["sratio"].iloc[[i + k for k in pre_k]].mean()
                a_pre = d["ar"].iloc[[i + k for k in pre_k]].mean()
                for j in ctl:
                    rows_pre.append({"day": int(d["day"].iloc[i]), "sym": sym, "event": 1,
                                     "s": s_pre, "a": a_pre})
                    rows_pre.append({"day": int(d["day"].iloc[i]), "sym": sym, "event": 0,
                                     "s": d["sratio"].iloc[[j + k for k in pre_k]].mean(),
                                     "a": d["ar"].iloc[[j + k for k in pre_k]].mean()})
                rows_post.append({"day": int(d["day"].iloc[i]), "sym": sym, "z": abs(e["z"]),
                                  "s0": d["sratio"].iloc[i], "a0": d["ar"].iloc[i],
                                  "apost": d["ar"].iloc[[i + k for k in post_k]].mean(),
                                  "apre": d["ar"].iloc[i - 20:i - 4].mean()})
                if iv == "3m":
                    for k in range(-10, 21):
                        prof.append({"k": k, "s": d["sratio"].iloc[i + k], "a": d["ar"].iloc[i + k],
                                     "big": abs(e["z"]) > 1.5})
        if not rows_post:
            continue
        pre = pd.DataFrame(rows_pre)
        post = pd.DataFrame(rows_post)
        print(f"\n  {iv}: {len(post):,} pair-releases, {len(pre) // 2:,} matched control windows", flush=True)
        # (a) pre-release: liquidity withdrawn before any information
        for outcome, label in (("s", "pre-release spread ratio"), ("a", "pre-release |r| (vol units)")):
            X = np.column_stack([pre["event"], fe(pre["sym"], "s")])
            got = ols(pre[outcome].to_numpy(), X, pre["day"])
            if got:
                ev_m = pre.loc[pre["event"] == 1, outcome].mean()
                ct_m = pre.loc[pre["event"] == 0, outcome].mean()
                record("news", f"{iv} event vs control: {label}", got[0][0], got[1][0], got[2],
                       event=f"{ev_m:.3f}", control=f"{ct_m:.3f}")
        # (b) |z| -> spread and vol (causal effects of information)
        X = np.column_stack([post["z"], post["apre"], fe(post["sym"], "s")])
        for outcome, label in (("s0", "|z| -> spread ratio at the release bar"),
                               ("a0", "|z| -> |r| at the release bar"),
                               ("apost", "|z| -> |r| after the release")):
            got = ols(post[outcome].to_numpy(), X, post["day"])
            if got:
                cut = post["day"].median()
                halves = []
                for part in (post[post["day"] < cut], post[post["day"] >= cut]):
                    Xh = np.column_stack([part["z"], part["apre"], fe(part["sym"], "s")])
                    h = ols(part[outcome].to_numpy(), Xh, part["day"])
                    halves.append(f"{h[0][0]:+.4f}" if h else "n/a")
                record("news", f"{iv} {label}", got[0][0], got[1][0], got[2], halves="/".join(halves))
        # mediation, descriptive only: does the release-bar spread carry |z|'s effect on later vol?
        X2 = np.column_stack([post["z"], np.log(post["s0"].clip(lower=1e-3)), post["apre"], fe(post["sym"], "s")])
        got = ols(post["apost"].to_numpy(), X2, post["day"])
        if got:
            print(f"    news   {iv} mediation (descriptive): |z| coef {got[0][0]:+.4f} (t {got[1][0]:+.2f}) "
                  f"with log spread in, spread coef {got[0][1]:+.4f} (t {got[1][1]:+.2f})", flush=True)
        if prof:
            pr = pd.DataFrame(prof)
            print("\n  3m event-time profile around releases with |z| > 1.5 (mean spread ratio, mean |r| in vol units):", flush=True)
            g = pr[pr["big"]].groupby("k")[["s", "a"]].mean()
            for k, row in g.iterrows():
                if k % 2 == 0 or k in (-1, 1):
                    print(f"    k={k:+3d}  spread {row['s']:.2f}x  |r| {row['a']:.2f}", flush=True)
            s_peak, a_peak = g["s"].idxmax(), g["a"].idxmax()
            s_half = next((k for k in g.index if k > s_peak and g.loc[k, "s"] < 1 + (g["s"].max() - 1) / 2), None)
            a_half = next((k for k in g.index if k > a_peak and g.loc[k, "a"] < g["a"].median() + (g["a"].max() - g["a"].median()) / 2), None)
            print(f"    peaks: spread at k={s_peak}, |r| at k={a_peak}; back to half: spread k={s_half}, |r| k={a_half}", flush=True)
    save()


# ------------------------------------------------------------------ D3: funding settlement

def part_fund():
    print("D3 - Binance funding settlement (00/08/16 UTC) as scheduled pressure, hourly perps", flush=True)
    rows = []
    for path in sorted(CROWD.glob("*USDT.npz")):
        z = np.load(path)
        t = pd.to_datetime(z["t"], unit="s", utc=True)
        c = np.log(z["close"].astype(float))
        f = z["funding"].astype(float)
        r = np.r_[np.nan, np.diff(c)]
        sig = pd.Series(np.abs(r)).rolling(24 * 20, min_periods=24 * 5).mean().shift(1).to_numpy()
        hour = t.hour
        for i in range(8, len(c) - 4):
            if not np.isfinite(sig[i]) or not np.isfinite(f[i]) or f[i] == 0:
                continue
            settle = hour[i] % 8 == 0
            placebo = hour[i] % 8 == 4
            if not (settle or placebo):
                continue
            s = -np.sign(f[i])  # the side that pays is pressed to close: +1 if shorts pay
            rows.append({"coin": path.stem, "day": int(z["t"][i] // 86400), "settle": int(settle),
                         "af": abs(f[i]) * 1e4,  # bps per 8h
                         "pre": s * (c[i] - c[i - 3]) / sig[i],   # the 3h into settlement
                         "post": s * (c[i + 3] - c[i]) / sig[i],  # the 3h after
                         "ar_post": np.abs(c[i + 3] - c[i]) / sig[i]})
    d = pd.DataFrame(rows)
    if d.empty:
        print("  no crowding data", flush=True)
        return
    print(f"  {len(d):,} coin-hours ({d['settle'].sum():,} settlements), {d['coin'].nunique()} coins", flush=True)
    for label, part in (("settlement", d[d["settle"] == 1]), ("placebo (4h off)", d[d["settle"] == 0])):
        for outcome in ("pre", "post", "ar_post"):
            X = np.column_stack([part["af"], fe(part["coin"], "c")])
            got = ols(part[outcome].to_numpy(), X, part["day"])
            if got:
                cut = part["day"].median()
                halves = []
                for h in (part[part["day"] < cut], part[part["day"] >= cut]):
                    hh = ols(h[outcome].to_numpy(), np.column_stack([h["af"], fe(h["coin"], "c")]), h["day"])
                    halves.append(f"{hh[0][0]:+.4f}" if hh else "n/a")
                record("fund", f"{label}: |funding| bps -> signed {outcome}", got[0][0], got[1][0], got[2],
                       halves="/".join(halves))
    # dose-response table at settlement
    s = d[d["settle"] == 1].copy()
    s["q"] = pd.qcut(s["af"], 5, labels=False, duplicates="drop")
    print("\n  settlement, by |funding| quintile: mean signed pre / post (vol units)", flush=True)
    for q, g in s.groupby("q"):
        print(f"    q{int(q)}  |f| {g['af'].median():.2f} bps  pre {g['pre'].mean():+.3f}  post {g['post'].mean():+.3f}  n {len(g):,}", flush=True)
    # walks: a random walk carrying the real funding series (no mechanism)
    w = d.copy()
    w["pre"] = RNG.standard_t(3, len(w))
    w["post"] = RNG.standard_t(3, len(w))
    sw = w[w["settle"] == 1]
    for outcome in ("pre", "post"):
        got = ols(sw[outcome].to_numpy(), np.column_stack([sw["af"], fe(sw["coin"], "c")]), sw["day"])
        if got:
            record("fund", f"walks: |funding| -> signed {outcome}", got[0][0], got[1][0], got[2])
    save()


# ------------------------------------------------------------------ D5: causal discovery (exploratory)

def part_pcmci():
    print("D5 - PCMCI over the shock forecaster's inputs at 1h (exploratory: hypotheses, not identification)", flush=True)
    from tigramite import data_processing as pp
    from tigramite.independence_tests.parcorr import ParCorr
    from tigramite.pcmci import PCMCI

    names = ["log|r|", "log spread", "log volume", "vol state", "shock"]

    def matrix(d: pd.DataFrame) -> np.ndarray:
        v = pd.Series(d["volume"].to_numpy() if "volume" in d else np.ones(len(d)))
        vol_ratio = v / v.rolling(500, min_periods=100).median()
        base = pd.Series(d["ar"]).rolling(100, min_periods=50).mean().shift(1)
        shock = (d["ar"] > 4 * base).astype(float)
        X = np.column_stack([np.log(d["ar"] + 0.05), np.log(d["sratio"].clip(lower=0.05)),
                             np.log(vol_ratio.clip(lower=0.01)), d["vstate"], shock])
        return X[np.all(np.isfinite(X), axis=1)]

    def run(X, label):
        X = (X - X.mean(0)) / X.std(0).clip(min=1e-9)
        df = pp.DataFrame(X[-15_000:], var_names=names)
        res = PCMCI(dataframe=df, cond_ind_test=ParCorr(), verbosity=0).run_pcmci(tau_max=3, pc_alpha=0.01)
        p, v = res["p_matrix"], res["val_matrix"]
        print(f"\n  {label}: links at p < 0.001 into log|r| and shock, and between spread and |r|", flush=True)
        for j in (0, 4):
            for i in range(len(names)):
                for tau in range(1, 4):
                    if p[i, j, tau] < 0.001:
                        print(f"    {names[i]:10s} (t-{tau}) -> {names[j]:7s}  MCI {v[i, j, tau]:+.3f}", flush=True)
        for (i, j) in ((1, 0), (0, 1)):
            best = min(range(1, 4), key=lambda tau: p[i, j, tau])
            print(f"    {names[i]} -> {names[j]}: strongest lag {best}, MCI {v[i, j, best]:+.3f}, p {p[i, j, best]:.1e}", flush=True)
        return v, p

    for sym in ("EURUSD", "USDJPY", "XAUUSD", "BTCUSD", "Volatility_75_Index"):
        z = SEQLAB / f"{sym}.1h.npz"
        if not z.exists():
            continue
        raw = np.load(z)
        d = pd.DataFrame({k: raw[k].astype(float) for k in ("time", "open", "high", "low", "close", "spread", "volume")})
        d = frame(d.drop_duplicates("time").sort_values("time").reset_index(drop=True))
        run(matrix(d), sym)
    # a walk with a known graph: volatility (GARCH) causes both |r| and a lagged spread; spread causes nothing
    n = 15_000
    rng = np.random.default_rng(3)
    h = np.zeros(n)
    r = np.zeros(n)
    for t in range(1, n):
        h[t] = 0.05 + 0.1 * r[t - 1] ** 2 + 0.85 * h[t - 1]
        r[t] = np.sqrt(h[t]) * rng.standard_normal()
    sig = pd.Series(np.abs(r)).ewm(alpha=1 / 14).mean().shift(1).to_numpy()
    spread = np.r_[1.0, np.sqrt(h[:-1])] * np.exp(0.2 * rng.standard_normal(n))  # follows last vol
    d = pd.DataFrame({"ar": np.abs(r) / sig, "sratio": spread / np.median(spread),
                      "vstate": np.log(sig / pd.Series(sig).rolling(500, min_periods=100).mean().to_numpy()),
                      "volume": np.exp(rng.standard_normal(n))})
    print("\n  walk with a known graph: vol -> |r| and vol(t-1) -> spread; spread causes nothing", flush=True)
    run(matrix(d), "GARCH walk")


# ------------------------------------------------------------------ report

def report():
    from statsmodels.stats.multitest import multipletests

    rows = []
    for name in ("roll", "news", "fund"):
        path = OUT / f"{name}.json"
        if path.exists():
            rows += json.loads(path.read_text())
    if not rows:
        return
    d = pd.DataFrame(rows)
    d["q"] = multipletests(d["p"], method="fdr_bh")[1]
    print(f"All {len(d)} design x outcome tests, BH-adjusted:", flush=True)
    for _, r in d.sort_values("q").iterrows():
        print(f"  q {r['q']:.3g}  t {r['t']:+6.2f}  {r['design']:5s} {r['outcome']}", flush=True)


if __name__ == "__main__":
    {"roll": part_roll, "news": part_news, "fund": part_fund, "pcmci": part_pcmci, "report": report}[PART]()
