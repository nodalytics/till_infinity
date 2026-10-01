"""Two questions about volatility expansion: what else foretells it, and how long it lasts.

Builds on research/docs/expansion.md (the alert: from compression, expansion within 16 bars at
AUC 0.781). Same universe, same walk-forward split (each series' first 60% by time trains).

Pre-registered (2026-10-01), before any run.

## Part 1: precursors besides compression

Five candidates, each computed from what is known at the bar:
  clock      expected volatility of the next 16 bars against the last 16, from a weekday x hour
             profile of log true range fitted on the series' training 60% (the calendar is known in
             advance: a quiet Asian session with London coming expands by the clock alone)
  breadth    the share of the other series in the same family and interval whose range percentile
             is >= 0.8 at that bar (expansion spreading across related markets)
  breadth_up the mean percentile of the others
  spread_z   log of the bar's spread against its 500-bar median (market makers widening)
  vol_slope  the slope of log tick volume over the last 16 bars, in its own standard deviations
             (activity building while the range stays quiet)
Judged by held-out AUC: the current 15 features, against those plus each candidate alone, and all
five together; both halves of the held-out period; GARCH walks (on which clock = 1, spreads are
flat and volume absent, so a gain there would be an artefact). A candidate counts if it adds >=
0.005 AUC in both halves.

## Part 2: how long the expansion lasts

  onset      the bar where the range percentile crosses from < 0.8 to >= 0.8
  duration   bars from the onset until the percentile falls below 0.5 (capped at 200)
  also       the excess range delivered: sum over the episode of (true range / pre-onset smoothed
             range - 1)
  groups     onsets that came out of compression (percentile <= 0.2 within the 16 bars before)
             against those that did not; by family; GARCH walks
  predict    at the onset bar: its range in sigma, the compression depth before it, the clock
             ratio, breadth, the volume z, the family; gradient boosting on the training 60%,
             scored on the held-out 40% by Spearman correlation of predicted against realised
             duration, against a persistence baseline (the duration of the series' previous
             episode)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "harness"))

import expansion_build as eb  # noqa: E402
from till_infinity.models import expansion_train as et  # noqa: E402
from till_infinity.models.shocks_train import auc  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/expansion"))
SECONDS = {"15m": 900, "1h": 3600, "4h": 14400}
RNG = np.random.default_rng(31)


def frame(sym: str, iv: str) -> pd.DataFrame | None:
    path = eb.find(sym, iv)
    if path is None:
        return None
    z = np.load(path)
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")})
    df["spread"] = z["spread"] if "spread" in z.files else np.nan
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


def per_series(df: pd.DataFrame, iv: str) -> pd.DataFrame:
    h, l, c = (np.log(df[k].to_numpy()) for k in ("high", "low", "close"))
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    slow = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    pct = slow.rolling(1500, min_periods=300).rank(pct=True)
    n = len(df)
    when = df["time"].to_numpy().astype(np.int64) + SECONDS[iv]
    # the clock: weekday x hour profile of log TR on the first 60%
    t = pd.to_datetime(df["time"], unit="s", utc=True)
    slot = (t.dt.weekday * 24 + t.dt.hour).to_numpy()
    train = np.arange(n) < int(0.6 * n)
    ltr = np.log(np.maximum(tr, 1e-12))
    prof = pd.Series(ltr[train]).groupby(slot[train]).mean()
    level = np.exp(pd.Series(slot).map(prof).fillna(prof.mean()).to_numpy())
    ahead = pd.Series(level[::-1]).rolling(16, min_periods=1).mean().to_numpy()[::-1]
    ahead = np.r_[ahead[1:], np.nan]  # bars t+1..t+16
    behind = pd.Series(level).rolling(16, min_periods=1).mean().to_numpy()
    sp = df["spread"].to_numpy(float)
    sp_med = pd.Series(sp).rolling(500, min_periods=50).median().to_numpy()
    lv = np.log(np.maximum(df["volume"].to_numpy(float), 1))
    k = np.arange(16) - 7.5
    slope = pd.Series(lv).rolling(16).apply(lambda w: np.dot(w - w.mean(), k) / np.dot(k, k), raw=True)
    vsd = pd.Series(lv).rolling(100, min_periods=30).std()
    vz = (pd.Series(lv) - pd.Series(lv).rolling(100, min_periods=30).mean()) / vsd
    return pd.DataFrame({
        "when": when, "pct": pct.to_numpy(), "slow": slow.to_numpy(), "tr": tr,
        "clock": np.log(ahead / behind),
        "spread_z": np.log(np.maximum(sp, 1e-9) / np.maximum(sp_med, 1e-9)) if np.isfinite(sp).any() else np.nan,
        "vol_slope": (slope / vsd).to_numpy(), "vol_z": vz.to_numpy(), "train": train,
    })


def fit_auc(Xtr, ytr, Xte, yte):
    from sklearn.ensemble import HistGradientBoostingClassifier
    Xtr, Xte = Xtr.copy(), Xte.copy()
    empty = np.all(np.isnan(Xtr), axis=0)  # a column with no values breaks the binning
    Xtr[:, empty], Xte[:, empty] = 0.0, 0.0
    m = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                       min_samples_leaf=300).fit(Xtr, ytr)
    return m, auc(yte, m.predict_proba(Xte)[:, 1])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    series, frames = {}, {}
    for sym in eb.FAMILY:
        for iv in ("15m", "1h", "4h"):
            df = frame(sym, iv)
            if df is None or len(df) < 2_000:
                continue
            series[(sym, iv)] = eb.load(sym, iv)
            if iv in ("15m", "1h"):
                frames[f"{sym}|{iv}"] = per_series(df, iv).assign(family=eb.FAMILY[sym])
    print(f"{len(frames)} series", flush=True)

    # breadth: other series of the same family and interval at the same close time
    allp = pd.concat([f[["when", "pct", "family"]].assign(key=k) for k, f in frames.items()])
    allp["iv"] = allp["key"].str.split("|").str[1]
    allp["hot"] = (allp["pct"] >= 0.8).astype(float)
    grp = allp.groupby(["family", "iv", "when"])
    tot_hot, tot_pct, cnt = grp["hot"].transform("sum"), grp["pct"].transform("sum"), grp["pct"].transform("count")
    allp["breadth"] = (tot_hot - allp["hot"].fillna(0)) / (cnt - 1).replace(0, np.nan)
    allp["breadth_up"] = (tot_pct - allp["pct"].fillna(0)) / (cnt - 1).replace(0, np.nan)
    br = allp.set_index(["key", "when"])[["breadth", "breadth_up"]]

    # ---------------------------------------------------------------- part 1
    rows = et.dataset(series)
    when, kinds, x, y = rows.arrays()
    keys = np.array(rows.key)
    real = kinds == "real"
    when, x, y, keys = when[real], x[real], y[real], keys[real]
    extra = np.full((len(y), 5), np.nan)
    names = ["clock", "breadth", "breadth_up", "spread_z", "vol_slope"]
    train = np.zeros(len(y), bool)
    second = np.zeros(len(y), bool)
    for k in np.unique(keys):
        m = np.flatnonzero(keys == k)
        f = frames.get(k)
        if f is None:
            continue
        pos = np.searchsorted(f["when"].to_numpy(), when[m])
        pos = np.minimum(pos, len(f) - 1)
        ok = f["when"].to_numpy()[pos] == when[m]
        b = br.loc[k].reindex(when[m])
        extra[m, 0] = np.where(ok, f["clock"].to_numpy()[pos], np.nan)
        extra[m, 1] = b["breadth"].to_numpy()
        extra[m, 2] = b["breadth_up"].to_numpy()
        extra[m, 3] = np.where(ok, f["spread_z"].to_numpy()[pos], np.nan)
        extra[m, 4] = np.where(ok, f["vol_slope"].to_numpy()[pos], np.nan)
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        te = m[when[m] >= cut]
        second[te] = when[te] >= np.median(when[te])
    te = ~train
    res: dict = {"rows": int(len(y)), "base_rate": round(float(y.mean()), 4)}
    variants = {"base": x}
    for j, nm in enumerate(names):
        variants[f"+{nm}"] = np.column_stack([x, extra[:, j]])
    variants["+all"] = np.column_stack([x, extra])
    part1 = {}
    for nm, X in variants.items():
        m, a = fit_auc(X[train], y[train], X[te], y[te])
        p = m.predict_proba(X[te])[:, 1]
        s2 = second[te]
        part1[nm] = dict(auc=round(a, 4), first_half=round(auc(y[te][~s2], p[~s2]), 4),
                         second_half=round(auc(y[te][s2], p[s2]), 4))
        print(f"  {nm:12s} {part1[nm]}", flush=True)
    base = part1["base"]
    for nm, v in part1.items():
        v["gain"] = round(v["auc"] - base["auc"], 4)
        v["counts"] = bool(v["first_half"] - base["first_half"] >= 0.005
                           and v["second_half"] - base["second_half"] >= 0.005)
    res["part1"] = part1
    res["part1_single_auc"] = {nm: round(auc(y[te & ~np.isnan(extra[:, j])],
                                             extra[te & ~np.isnan(extra[:, j]), j]), 4)
                               for j, nm in enumerate(names)}

    # GARCH walks: the clock is flat, spreads flat, no volume; breadth across independent walks
    walks = et.walks(8, 20_000, garch=True)
    wr = et.dataset(walks)
    ww, wk, wx, wy = wr.arrays()
    wkeys = np.array(wr.key)
    wframes = {}
    for (s, iv), bars in walks.items():
        if iv in ("15m", "1h"):
            df = pd.DataFrame({"time": [b.time for b in bars], "open": [b.open for b in bars],
                               "high": [b.high for b in bars], "low": [b.low for b in bars],
                               "close": [b.close for b in bars], "volume": 0.0, "spread": 8.0})
            wframes[f"{s}|{iv}"] = per_series(df, iv)
    wp = pd.concat([f[["when", "pct"]].assign(key=k) for k, f in wframes.items()])
    wp["iv"] = wp["key"].str.split("|").str[1]
    wp["hot"] = (wp["pct"] >= 0.8).astype(float)
    g = wp.groupby(["iv", "when"])
    wp["breadth"] = (g["hot"].transform("sum") - wp["hot"].fillna(0)) / (g["pct"].transform("count") - 1).replace(0, np.nan)
    wbr = wp.set_index(["key", "when"])["breadth"]
    wb = np.array([wbr.get((k, t), np.nan) for k, t in zip(wkeys, ww, strict=True)])
    wtr = ww < np.quantile(ww, 0.6)
    _, a0 = fit_auc(wx[wtr], wy[wtr], wx[~wtr], wy[~wtr])
    _, a1 = fit_auc(np.column_stack([wx, wb])[wtr], wy[wtr], np.column_stack([wx, wb])[~wtr], wy[~wtr])
    res["part1_walks"] = dict(base=round(a0, 4), plus_breadth=round(a1, 4))
    print(json.dumps(res["part1_walks"]), flush=True)

    # ---------------------------------------------------------------- part 2
    eps = []
    for k, f in frames.items():
        pct, slow, tr = f["pct"].to_numpy(), f["slow"].to_numpy(), f["tr"].to_numpy()
        n = len(pct)
        onsets = np.flatnonzero((pct[1:] >= 0.8) & (pct[:-1] < 0.8)) + 1
        prev_dur = np.nan
        b = br.loc[k] if k in br.index.get_level_values(0) else None
        for o in onsets:
            if o < 20:
                continue
            end = o
            while end < n and end - o < 200 and not (pct[end] < 0.5):
                end += 1
            if end >= n:
                break
            dur = end - o
            pre = slow[o - 1]
            excess = float(np.sum(tr[o:end] / pre - 1)) if pre > 0 else np.nan
            eps.append(dict(key=k, family=f["family"].iloc[0], onset=o, when=f["when"].iat[o],
                            duration=dur, excess=excess, train=bool(f["train"].iat[o]),
                            from_compression=bool(np.nanmin(pct[o - 16:o]) <= 0.2),
                            onset_range=tr[o] / pre if pre > 0 else np.nan,
                            depth=float(np.nanmin(pct[o - 16:o])), clock=f["clock"].iat[o],
                            vol_z=f["vol_z"].iat[o], prev=prev_dur,
                            breadth=b["breadth"].get(f["when"].iat[o], np.nan) if b is not None else np.nan))
            prev_dur = dur
    ep = pd.DataFrame(eps)
    summary = {}
    for nm, g2 in [("all", ep), ("from_compression", ep[ep["from_compression"]]),
                   ("not_from_compression", ep[~ep["from_compression"]])] + [(f"family:{f}", x) for f, x in ep.groupby("family")]:
        summary[nm] = dict(n=len(g2), median=float(g2["duration"].median()),
                           p25=float(g2["duration"].quantile(0.25)), p75=float(g2["duration"].quantile(0.75)),
                           p90=float(g2["duration"].quantile(0.9)),
                           excess_median=round(float(g2["excess"].median()), 2))
    res["part2_duration"] = summary
    from scipy.stats import spearmanr
    from sklearn.ensemble import HistGradientBoostingRegressor
    feats = ["onset_range", "depth", "clock", "vol_z", "breadth", "prev", "from_compression"]
    fam = pd.get_dummies(ep["family"]).astype(float)
    X = np.column_stack([ep[feats].to_numpy(float), fam.to_numpy()])
    yd = np.log(ep["duration"].to_numpy(float))
    tr_ = ep["train"].to_numpy()
    gb = HistGradientBoostingRegressor(max_depth=3, max_iter=200, learning_rate=0.05,
                                       min_samples_leaf=100).fit(X[tr_], yd[tr_])
    pred = gb.predict(X[~tr_])
    rho = spearmanr(pred, yd[~tr_]).statistic
    prevm = ~np.isnan(ep["prev"].to_numpy()) & ~tr_
    rho_prev = spearmanr(ep["prev"].to_numpy()[prevm], yd[prevm]).statistic
    singles = {f: round(float(spearmanr(ep[f].to_numpy(float)[~tr_], yd[~tr_], nan_policy="omit").statistic), 4)
               for f in feats}
    res["part2_predict"] = dict(n_test=int((~tr_).sum()), spearman_gb=round(float(rho), 4),
                                spearman_persistence=round(float(rho_prev), 4), singles=singles)
    # walks: the same duration distribution on GARCH walks
    wd = []
    for k, f in wframes.items():
        pct = f["pct"].to_numpy()
        n = len(pct)
        for o in np.flatnonzero((pct[1:] >= 0.8) & (pct[:-1] < 0.8)) + 1:
            end = o
            while end < n and end - o < 200 and not (pct[end] < 0.5):
                end += 1
            if end < n:
                wd.append(end - o)
    res["part2_walks"] = dict(n=len(wd), median=float(np.median(wd)), p75=float(np.percentile(wd, 75)),
                              p90=float(np.percentile(wd, 90)))
    print(json.dumps({k: v for k, v in res.items() if k.startswith("part2")}, indent=1), flush=True)
    (OUT / "precursors.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
