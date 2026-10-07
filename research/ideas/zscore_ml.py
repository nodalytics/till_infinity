"""Can a model predict the forward move from the z-score features?

Asked 2026-10-07 after the single-feature tables in `zscore-window.md`. There is
a real reason to expect a model to beat them: that study established the relation
is **non-monotone** - the Spearman IC is negative at h = 1 while the decile
spread is positive - and every number in it came from one feature at a time. A
tree finds interactions (window x level x candle) that a decile table cannot see.

The design matters more than the model, so:

* **Split by date, never at random.** The target is a forward return over `h`
  bars, so adjacent rows share bars; a random split puts the same move on both
  sides of it and reports leakage as skill. Train is the first 70% of the
  calendar, test the last 30%, with a gap of `h` bars purged at the boundary.
* **A shuffled-target null, refit.** The model is trained again on `y` permuted
  within symbol and scored the same way. That is what "the model found nothing"
  looks like with this many features and this much capacity, and it is not zero.
* **Per-instrument test scores**, so one symbol cannot carry the result.
* **Report the decile spread in ATR**, not only the IC. An IC of 0.03 on 200,000
  rows is overwhelming statistically and may be worth nothing; the spread is in
  the units the desk loses money in.
* Every feature is from bars at or before `t`, and the z-scores are divided by
  their own ceiling `(N-1)/sqrt(N)` so a window's reading means the same thing at
  every window - which `zscore-window.md` showed it otherwise does not.

  MT5BT_DB=... SYMBOLS=... IV=4h H=3 python research/ideas/zscore_ml.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

import prims as P  # noqa: E402

ZW = (4, 6, 8, 12, 20, 36)
IV = os.environ.get("IV", "4h")
H = int(os.environ.get("H", 3))
OUT = Path(os.environ.get("OUT", ".data/zml"))
TRAIN = float(os.environ.get("TRAIN", 0.70))


def ceiling(n: int) -> float:
    """The largest |z| a window of n points can produce."""
    return (n - 1) / np.sqrt(n)


def zscores(c: np.ndarray, n: int) -> np.ndarray:
    s = pd.Series(c)
    sd = s.rolling(n).std(ddof=1)
    return ((s - s.rolling(n).mean()) / sd.replace(0.0, np.nan)).to_numpy()


def one(sym):
    import run as R
    import survivors
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, IV)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    o, h_, l_, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = P.atr(df, 14)
    rng = np.maximum(h_ - l_, 1e-12)
    out = {"sym": sym, "ts": df["ts"].to_numpy()}
    for n in ZW:
        z = zscores(c, n) / ceiling(n)      # share of the attainable maximum
        out[f"z{n}"] = z
        if n in (6, 12, 36):
            out[f"dz{n}"] = np.r_[np.nan, np.diff(z)]
    # the term structure: fast against slow, at the same bar
    out["z_fast_slow"] = out["z4"] - out["z36"]
    out["body"] = np.abs(c - o) / rng
    with np.errstate(invalid="ignore", divide="ignore"):
        out["body_atr"] = np.where(a > 0, np.abs(c - o) / a, np.nan)
        out["range_atr"] = np.where(a > 0, rng / a, np.nan)
        out["atr_rel"] = np.where(a > 0, a / pd.Series(a).rolling(100).mean().to_numpy(), np.nan)
        fwd = np.full(len(c), np.nan)
        fwd[:-H] = c[H:] - c[:-H]
        out["y"] = np.where(a > 0, fwd / a, np.nan)
    out["up"] = (c >= o).astype(float)
    out["wick_up"] = (h_ - np.maximum(o, c)) / rng
    out["wick_dn"] = (np.minimum(o, c) - l_) / rng
    return pd.DataFrame(out)


FEATURES = [f"z{n}" for n in ZW] + ["dz6", "dz12", "dz36", "z_fast_slow",
                                    "body", "body_atr", "range_atr", "atr_rel",
                                    "up", "wick_up", "wick_dn"]


def fit_score(tr, te, y_tr, seed=0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_depth=4, min_samples_leaf=200,
        l2_regularization=1.0, random_state=seed)
    m.fit(tr[FEATURES], y_tr)
    return m, m.predict(te[FEATURES])


def spread(pred, y, q=0.1):
    lo, hi = np.quantile(pred, [q, 1 - q])
    a_, b_ = y[pred >= hi], y[pred <= lo]
    if len(a_) < 50 or len(b_) < 50:
        return np.nan
    return float(a_.mean() - b_.mean())


def block_ci(v, days, draws=2000, seed=31):
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    v, days = v[ok], np.asarray(days)[ok]
    if len(v) < 50:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def report(name, te, pred):
    """Score at three sharpnesses.

    The decile is the fair comparison against a decile table, but the conditional
    cells in `zscore-window.md` that reached 0.15 ATR were an **extreme** subset -
    `|z| >= 2` **and** a 70% body, a few percent of bars. A model trained on
    squared error over every bar is optimising the middle, so it has to be read
    at the sharp end too or the comparison is unfair to it.
    """
    y = te["y"].to_numpy()
    dt = te["day"].to_numpy()
    ic = float(pd.Series(pred).corr(pd.Series(y), method="spearman")) if np.ptp(pred) > 0 else np.nan
    line, row = [], dict(model=name, ic=ic)
    for q in (0.10, 0.05, 0.01):
        hi_, lo_ = np.quantile(pred, [1 - q, q])
        up, dn = pred >= hi_, pred <= lo_
        m_t, l_t, h_t = block_ci(y[up], dt[up])
        m_b, l_b, h_b = block_ci(y[dn], dt[dn])
        line.append(f"{q:.0%}: {m_t - m_b:+.3f} (top {m_t:+.3f} [{l_t:+.3f},{h_t:+.3f}])")
        row |= {f"spread_{int(q * 100)}": m_t - m_b, f"top_{int(q * 100)}": m_t,
                f"top_lo_{int(q * 100)}": l_t, f"top_hi_{int(q * 100)}": h_t,
                f"bottom_{int(q * 100)}": m_b, f"n_{int(q * 100)}": int(up.sum())}
    print(f"  {name:<22} IC {ic:+.4f}   " + "   ".join(line))
    return row


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=FEATURES).reset_index(drop=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    d = d.sort_values("ts").reset_index(drop=True)

    cut = d["ts"].quantile(TRAIN)
    gap = H * {"1h": 3600, "4h": 14400, "1d": 86400}[IV]
    tr = d[d["ts"] <= cut - gap]
    te = d[d["ts"] > cut]
    print(f"{len(d):,} rows, {d['sym'].nunique()} instruments, horizon {H} bars of {IV}")
    print(f"train {len(tr):,} to {pd.to_datetime(cut, unit='s').date()}, test {len(te):,}")
    print(f"the target overlaps {H} bars, so the test holds about "
          f"{len(te) // H:,} non-overlapping observations\n")

    rows = []
    print("out of sample:")
    rows.append(report("always the mean", te, np.full(len(te), tr["y"].mean())))
    best = max(FEATURES, key=lambda f: abs(tr[f].corr(tr["y"], method="spearman")))
    sign = np.sign(tr[best].corr(tr["y"], method="spearman"))
    rows.append(report(f"best feature ({best})", te, sign * te[best].to_numpy()))
    _, pred = fit_score(tr, te, tr["y"].to_numpy())
    rows.append(report("gradient boosting", te, pred))

    rng = np.random.default_rng(4)
    ysh = tr["y"].to_numpy().copy()
    for s_ in tr["sym"].unique():
        w = np.flatnonzero(tr["sym"].to_numpy() == s_)
        ysh[w] = rng.permutation(ysh[w])
    _, pred_sh = fit_score(tr, te, ysh, seed=1)
    rows.append(report("same model, y shuffled", te, pred_sh))

    print("\nper instrument, gradient boosting (test only):")
    for s_, g in te.assign(pred=pred).groupby("sym"):
        if len(g) < 200:
            continue
        print(f"  {s_:<10} n={len(g):>6}  IC {g['pred'].corr(g['y'], method='spearman'):+.4f}"
              f"   spread {spread(g['pred'].to_numpy(), g['y'].to_numpy()):+.4f}")

    print("\nwalk forward, refit each calendar year:")
    years = pd.to_datetime(d["ts"], unit="s").dt.year.to_numpy()
    wf = []
    for y_ in sorted(set(years))[3:]:
        a_, b_ = d[years < y_], d[years == y_]
        if len(a_) < 20000 or len(b_) < 1000:
            continue
        _, p_ = fit_score(a_, b_, a_["y"].to_numpy())
        # **Both sides as plain arrays.** `pd.Series(p_)` is indexed 0..n-1 while
        # `b_["y"]` carries the frame's own index, so `.corr` aligns on the index,
        # finds no overlap and returns NaN - which the first run printed as a
        # column of `+nan` and nearly read as "the model learned nothing".
        wf.append((y_, len(b_), float(pd.Series(p_).corr(
            pd.Series(b_["y"].to_numpy()), method="spearman")), spread(p_, b_["y"].to_numpy())))
    for y_, n_, ic_, sp_ in wf:
        print(f"  {y_}  n={n_:>6}  IC {ic_:+.4f}  spread {sp_:+.4f}")
    if wf:
        ics = np.array([x[2] for x in wf])
        print(f"  -> positive in {int((ics > 0).sum())} of {len(ics)} years, mean IC {ics.mean():+.4f}")

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "zml.csv", index=False)
    print(f"\nwritten: {OUT / 'zml.csv'}")


if __name__ == "__main__":
    main()
