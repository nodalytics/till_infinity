"""Round 2 of the pre-expansion state: the rest of the candidate sensors, and onset-duration-
magnitude-velocity as one target.

precursors.py found the calendar (the vol clock's next 16 bars against the last 16) adds +0.017
AUC to the expansion alert in both halves, and cross-asset breadth, spread state and the volume
trend add nothing. This tests the remaining sensors that bars and tick volume can measure, over the
new baseline (the alert's 15 features plus the calendar).

Pre-registered (2026-10-01), before any run. Held-out = each series' last 40%.

  boundary exhaustion  tests = bars in the last 16 that made a new 16-bar high or low;
                       pen_slope = the slope of those penetrations' sizes (in sigma) over time,
                       0 with fewer than 3 tests (repeated tests with shrinking reach)
  vol term structure   log(RV 4 / RV 16) and log(RV 16 / RV 64), RV the root mean squared return
  directional entropy  binary entropy of the share of up closes over the last 32 bars
  sequence entropy     Shannon entropy of the 8 sign 3-grams over the last 64 bars, and its change
                       from 64 bars earlier
  cross-asset          the family's cross-sectional dispersion of 16-bar returns (in sigma) against
                       its own 500-bar median; the family's mean pairwise correlation of returns
                       over 64 bars, and its change over 256 bars
  counts if            >= 0.005 AUC over the baseline in both halves of the held-out period
  latent state         do the sensors share a common factor? first principal component's share of
                       variance among them at compressed bars (descriptive)

Part 2, extended: at each expansion onset (percentile crosses 0.8), the episode's duration D (bars
until it falls below 0.5), magnitude M (the largest |log price - onset close| during it, in
pre-onset sigma) and velocity V = M / D. Predicted at the onset from the onset bar's range, the
compression before it, the calendar, the new sensors and the family; Spearman on the held-out 40%.
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
import precursors as pc  # noqa: E402
from till_infinity.models import expansion_train as et  # noqa: E402
from till_infinity.models.shocks_train import auc  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/expansion"))
NEW = ["tests", "pen_slope", "rv_4_16", "rv_16_64", "dir_entropy", "seq_entropy", "seq_entropy_change",
       "dispersion", "corr", "corr_change"]


def sensors(df: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    h, l, c = (np.log(df[k].to_numpy()) for k in ("high", "low", "close"))
    r = np.r_[0.0, np.diff(c)]
    sig = base["slow"].to_numpy()
    n = len(c)
    hi_prev = pd.Series(h).rolling(16).max().shift(1).to_numpy()
    lo_prev = pd.Series(l).rolling(16).min().shift(1).to_numpy()
    pen = np.where(h > hi_prev, (h - hi_prev) / sig, np.where(l < lo_prev, (lo_prev - l) / sig, np.nan))
    tests = pd.Series(~np.isnan(pen)).astype(float).rolling(16).sum().to_numpy()

    def slope(w):
        k = np.flatnonzero(~np.isnan(w))
        if len(k) < 3:
            return 0.0
        x = k - k.mean()
        return float(np.dot(x, w[k] - w[k].mean()) / np.dot(x, x))

    pen_slope = pd.Series(pen).rolling(16, min_periods=1).apply(slope, raw=True).to_numpy()
    sq = pd.Series(r * r)
    rv = {w: np.sqrt(sq.rolling(w).mean()).to_numpy() for w in (4, 16, 64)}
    up = pd.Series((r > 0).astype(float)).rolling(32).mean().to_numpy()
    pq = np.clip(up, 1e-9, 1 - 1e-9)
    dir_h = -(pq * np.log2(pq) + (1 - pq) * np.log2(1 - pq))
    s = (r > 0).astype(int)
    gram = s + 2 * np.r_[0, s[:-1]] + 4 * np.r_[0, 0, s[:-2]]
    onehot = np.eye(8)[gram]
    counts = pd.DataFrame(onehot).rolling(64).sum().to_numpy()
    p = counts / np.maximum(counts.sum(axis=1, keepdims=True), 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        seq_h = -np.nansum(np.where(p > 0, p * np.log2(p), 0.0), axis=1) / 3.0
    seq_h[:64] = np.nan
    return pd.DataFrame({
        "when": base["when"].to_numpy(), "r": r / np.maximum(sig, 1e-12),
        "ret16": pd.Series(c).diff(16).to_numpy() / np.maximum(sig, 1e-12),
        "tests": tests, "pen_slope": pen_slope,
        "rv_4_16": np.log(rv[4] / rv[16]), "rv_16_64": np.log(rv[16] / rv[64]),
        "dir_entropy": dir_h, "seq_entropy": seq_h,
        "seq_entropy_change": seq_h - np.r_[[np.nan] * 64, seq_h[:-64]] if n > 64 else np.nan,
    })


def family_terms(frames: dict, fam_of: dict) -> pd.DataFrame:
    """Cross-sectional dispersion and mean pairwise correlation per family and interval."""
    out = []
    for (fam, iv), keys in pd.Series(fam_of).groupby(lambda k: (fam_of[k], k.split("|")[1])).groups.items():
        keys = list(keys)
        if len(keys) < 3:
            continue
        r = pd.concat({k: frames[k].set_index("when")["r"] for k in keys}, axis=1).sort_index()
        r16 = pd.concat({k: frames[k].set_index("when")["ret16"] for k in keys}, axis=1).sort_index()
        disp = r16.std(axis=1)
        disp_rel = np.log(disp / disp.rolling(500, min_periods=100).median())
        z = (r - r.rolling(64, min_periods=32).mean()) / r.rolling(64, min_periods=32).std()
        m = z.notna().sum(axis=1)
        tot = z.sum(axis=1)
        var_sum = (tot * tot).rolling(64, min_periods=32).mean()
        # mean pairwise correlation from the variance of the standardised sum
        corr = (var_sum - m) / (m * (m - 1)).replace(0, np.nan)
        frame = pd.DataFrame({"dispersion": disp_rel, "corr": corr, "corr_change": corr - corr.shift(256)})
        for k in keys:
            out.append(frame.assign(key=k).reset_index())
    return pd.concat(out, ignore_index=True)


def main() -> None:
    series, frames, base_frames, fam_of = {}, {}, {}, {}
    for sym in eb.FAMILY:
        for iv in ("15m", "1h", "4h"):
            df = pc.frame(sym, iv)
            if df is None or len(df) < 2_000:
                continue
            series[(sym, iv)] = eb.load(sym, iv)
            if iv in ("15m", "1h"):
                k = f"{sym}|{iv}"
                b = pc.per_series(df, iv)
                base_frames[k] = b
                frames[k] = sensors(df, b)
                fam_of[k] = eb.FAMILY[sym]
    print(f"{len(frames)} series", flush=True)
    fam = family_terms(frames, fam_of).set_index(["key", "when"])

    rows = et.dataset(series)
    when, kinds, x, y = rows.arrays()
    keys = np.array(rows.key)
    keep = kinds == "real"
    when, x, y, keys = when[keep], x[keep], y[keep], keys[keep]
    clock = np.full(len(y), np.nan)
    extra = np.full((len(y), len(NEW)), np.nan)
    train = np.zeros(len(y), bool)
    second = np.zeros(len(y), bool)
    for k in np.unique(keys):
        m = np.flatnonzero(keys == k)
        if k not in frames:
            continue
        b, f = base_frames[k], frames[k]
        pos = np.minimum(np.searchsorted(b["when"].to_numpy(), when[m]), len(b) - 1)
        ok = b["when"].to_numpy()[pos] == when[m]
        clock[m] = np.where(ok, b["clock"].to_numpy()[pos], np.nan)
        for j, nm in enumerate(NEW[:7]):
            extra[m, j] = np.where(ok, f[nm].to_numpy()[pos], np.nan)
        if k in fam.index.get_level_values(0):
            fk = fam.loc[k].reindex(when[m])
            for j, nm in enumerate(NEW[7:], start=7):
                extra[m, j] = fk[nm].to_numpy()
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        te_m = m[when[m] >= cut]
        second[te_m] = when[te_m] >= np.median(when[te_m])
    te = ~train
    basex = np.column_stack([x, clock])
    res: dict = {"rows": int(len(y))}

    def score(X):
        m, a = pc.fit_auc(X[train], y[train], X[te], y[te])
        Xte = X[te].copy()
        Xte[:, np.all(np.isnan(X[train]), axis=0)] = 0.0
        p = m.predict_proba(Xte)[:, 1]
        s2 = second[te]
        return dict(auc=round(a, 4), first_half=round(auc(y[te][~s2], p[~s2]), 4),
                    second_half=round(auc(y[te][s2], p[s2]), 4))

    part1 = {"base+clock": score(basex)}
    b0 = part1["base+clock"]
    print("  base+clock", b0, flush=True)
    for j, nm in enumerate(NEW):
        v = score(np.column_stack([basex, extra[:, j]]))
        v["counts"] = bool(v["first_half"] - b0["first_half"] >= 0.005 and v["second_half"] - b0["second_half"] >= 0.005)
        part1[f"+{nm}"] = v
        print(f"  +{nm:20s} {v}", flush=True)
    part1["+all"] = score(np.column_stack([basex, extra]))
    print("  +all", part1["+all"], flush=True)
    res["part1"] = part1
    # the latent state: do the sensors move together at compressed bars?
    z = pd.DataFrame(extra, columns=NEW).dropna()
    z = (z - z.mean()) / z.std()
    ev = np.linalg.eigvalsh(np.cov(z.to_numpy().T))[::-1]
    res["sensor_pc_shares"] = [round(float(e / ev.sum()), 3) for e in ev[:4]]
    res["sensor_corr_with_label"] = {nm: round(float(pd.Series(extra[:, j]).corr(pd.Series(y))), 4)
                                     for j, nm in enumerate(NEW)}

    # ---------------------------------------------------------------- part 2: D, M, V
    from scipy.stats import spearmanr
    from sklearn.ensemble import HistGradientBoostingRegressor
    eps = []
    for k, b in base_frames.items():
        f = frames[k]
        df = pc.frame(*k.split("|"))
        lc = np.log(df["close"].to_numpy())
        pct, slow, tr = b["pct"].to_numpy(), b["slow"].to_numpy(), b["tr"].to_numpy()
        n = len(pct)
        for o in np.flatnonzero((pct[1:] >= 0.8) & (pct[:-1] < 0.8)) + 1:
            if o < 70:
                continue
            end = o
            while end < n and end - o < 200 and not (pct[end] < 0.5):
                end += 1
            if end >= n:
                break
            pre = slow[o - 1]
            if not pre > 0:
                continue
            D = end - o
            M = float(np.max(np.abs(lc[o:end + 1] - lc[o - 1])) / pre)
            row = dict(key=k, family=fam_of[k], train=bool(b["train"].iat[o]), D=D, M=M, V=M / max(D, 1),
                       onset_range=tr[o] / pre, depth=float(np.nanmin(pct[o - 16:o])), clock=b["clock"].iat[o],
                       vol_z=b["vol_z"].iat[o])
            for nm in NEW[:7]:
                row[nm] = f[nm].iat[o]
            eps.append(row)
    ep = pd.DataFrame(eps)
    feats = ["onset_range", "depth", "clock", "vol_z", *NEW[:7]]
    X = np.column_stack([ep[feats].to_numpy(float), pd.get_dummies(ep["family"]).astype(float).to_numpy()])
    tr_ = ep["train"].to_numpy()
    part2 = {"n": len(ep), "n_test": int((~tr_).sum())}
    for target in ("D", "M", "V"):
        yv = np.log(ep[target].to_numpy(float) + 1e-6)
        gb = HistGradientBoostingRegressor(max_depth=3, max_iter=200, learning_rate=0.05,
                                           min_samples_leaf=100).fit(X[tr_], yv[tr_])
        rho = spearmanr(gb.predict(X[~tr_]), yv[~tr_]).statistic
        singles = {f: round(float(spearmanr(ep[f].to_numpy(float)[~tr_], yv[~tr_], nan_policy="omit").statistic), 3)
                   for f in feats}
        top = sorted(singles.items(), key=lambda kv: -abs(kv[1]))[:4]
        part2[target] = dict(median=round(float(ep[target].median()), 3),
                             p25=round(float(ep[target].quantile(0.25)), 3),
                             p75=round(float(ep[target].quantile(0.75)), 3),
                             spearman_gb=round(float(rho), 4), strongest_single=top)
    part2["corr_D_M"] = round(float(spearmanr(ep["D"], ep["M"]).statistic), 3)
    res["part2"] = part2
    print(json.dumps(res, indent=1, default=str), flush=True)
    (OUT / "signature.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
