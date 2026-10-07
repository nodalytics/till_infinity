"""Online learners on the same features: does anything survive bar-by-bar?

Asked 2026-10-07. It is the right question for this desk and not only a variant:
production's structures models are **online**, so a result that only a batch fit
can see does not transfer however good it looks.

Evaluated **prequentially** - predict, score, then learn from the same bar. There
is no train/test split because there does not need to be one: every prediction is
made before its own outcome is known, which is a stricter test than a date split
and the only one that matches how the live desk would run it. Bars are fed in
global timestamp order, interleaved across instruments, as production sees them.

Features are standardised **online** too, by a running mean and variance, because
a learner fed raw features has to spend its first thousand bars discovering their
scale - and because a batch standardiser would leak the whole sample's moments
into the first prediction.

Two targets, because they are different questions:

  y     the 3-bar forward move over the ATR - the number the batch study reported
  hit   did price reach +1 ATR before -1 ATR within 12 bars, ties to the stop -
        the question a trade asks

Each model is run again against a within-symbol shuffle of its target, which is
what "it learned nothing" looks like for that model at that capacity.

  MT5BT_DB=... SYMBOLS=... python research/ideas/zscore_online.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

OUT = Path(os.environ.get("OUT", ".data/zonline"))
SRC = Path(os.environ.get("SRC", ".data/zml3"))
EVERY = int(os.environ.get("EVERY", 1))


def regressors():
    from river import forest, linear_model, optim, preprocessing, tree
    return {
        "linear SGD": preprocessing.StandardScaler() | linear_model.LinearRegression(
            optimizer=optim.SGD(0.01)),
        "passive aggressive": preprocessing.StandardScaler() | linear_model.PARegressor(C=0.01),
        "Hoeffding adaptive tree": preprocessing.StandardScaler() | tree.HoeffdingAdaptiveTreeRegressor(
            grace_period=200, seed=7),
        "adaptive random forest": preprocessing.StandardScaler() | forest.ARFRegressor(
            n_models=10, seed=7),
    }


def classifiers():
    from river import forest, linear_model, preprocessing, tree
    return {
        "logistic": preprocessing.StandardScaler() | linear_model.LogisticRegression(),
        "Hoeffding adaptive tree": preprocessing.StandardScaler() | tree.HoeffdingAdaptiveTreeClassifier(
            grace_period=200, seed=7),
        "adaptive random forest": preprocessing.StandardScaler() | forest.ARFClassifier(
            n_models=10, seed=7),
    }


def block_ci(v, days, draws=1500, seed=61):
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    v, days = v[ok], np.asarray(days)[ok]
    if len(v) < 40:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def prequential(model, X, y, ts, ready, warm=5000, clf=False):
    """Predict, then learn from whichever labels have actually arrived by now.

    **The label is not available when the bar closes.** `y` is a move over the
    next `H` bars and `hit` is a barrier touched up to `BARS` later, so learning
    from `(x_i, y_i)` at step `i` hands the model the next three bars before it
    predicts bars `i+1`, `i+2` and `i+3` - whose own labels overlap `y_i` by two
    thirds. The first version of this file did exactly that and reported an IC of
    **+0.30** against the batch model's +0.0045, a hundredfold jump that was
    entirely the overlap.

    So a bar enters the queue when it closes and is learned from only once its
    label's own window has elapsed - `ready[i]`, a timestamp. That is also how a
    live desk would have to do it: the outcome of a trade opened now is not a
    training example until it is over.
    """
    pred = np.full(len(y), np.nan)
    queue, head = list(zip(ready, X, y)), 0
    for i, x in enumerate(X):
        now = ts[i]
        while head < len(queue) and queue[head][0] <= now:
            _, xq, tq = queue[head]
            if clf:
                model.learn_one(xq, bool(tq))
            else:
                model.learn_one(xq, float(tq))
            head += 1
        if i >= warm:
            pred[i] = model.predict_proba_one(x).get(1, 0.5) if clf else model.predict_one(x)
    return pred


def report(name, pred, y, day, clf=False, base=None):
    ok = np.isfinite(pred) & np.isfinite(y)
    p, t, d = pred[ok], y[ok], day[ok]
    if np.ptp(p) == 0:
        print(f"  {name:<26} constant prediction")
        return dict(model=name, ic=np.nan)
    ic = float(pd.Series(p).corr(pd.Series(t), method="spearman"))
    bits, row = [], dict(model=name, n=len(p), ic=ic)
    for q in (0.10, 0.01):
        hi_ = np.quantile(p, 1 - q)
        up = p >= hi_
        m_, l_, h_ = block_ci(t[up], d[up])
        if clf:
            bits.append(f"top {q:.0%}: win {m_:.1%} [{l_:.1%},{h_:.1%}] n={int(up.sum())}")
        else:
            lo_ = np.quantile(p, q)
            m_b, _, _ = block_ci(t[p <= lo_], d[p <= lo_])
            bits.append(f"top {q:.0%}: {m_ - m_b:+.3f} (top {m_:+.3f} [{l_:+.3f},{h_:+.3f}])")
        row |= {f"top{int(q * 100)}": m_, f"lo{int(q * 100)}": l_, f"hi{int(q * 100)}": h_}
    extra = f"  base {base:.1%}" if base is not None else ""
    print(f"  {name:<26} IC {ic:+.4f}  " + "  ".join(bits) + extra)
    return row


def main() -> None:
    import zscore_ml2 as Z
    syms = os.environ.get("SYMBOLS")
    import run as R
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(Z.one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=Z.FEATURES).reset_index(drop=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    d = d.sort_values(["ts", "sym"]).reset_index(drop=True)
    if EVERY > 1:
        d = d.iloc[::EVERY].reset_index(drop=True)
    print(f"{len(d):,} rows in time order, {d['sym'].nunique()} instruments, "
          f"prequential (predict then learn)\n")

    X = d[Z.FEATURES].to_dict("records")
    y = d["y"].to_numpy()
    hit = d["hit"].to_numpy()
    day = d["day"].to_numpy()
    sec = {"1h": 3600, "4h": 14400, "1d": 86400}[os.environ.get("IV", "4h")]
    ts = d["ts"].to_numpy()
    ready_y = ts + Z.H * sec          # the forward move is known H bars later
    ready_h = ts + Z.BARS * sec       # the barrier, at worst BARS later
    rng = np.random.default_rng(17)
    ysh = y.copy()
    for s_ in d["sym"].unique():
        w = np.flatnonzero(d["sym"].to_numpy() == s_)
        ysh[w] = rng.permutation(ysh[w])

    rows = []
    print("target: the 3-bar forward move, in ATR")
    for name, mk in regressors().items():
        t0 = time.time()
        rows.append(report(name, prequential(mk, X, y, ts, ready_y), y, day))
        rows[-1] |= {"target": "y", "secs": round(time.time() - t0, 1)}
    rows.append(report("linear SGD, y shuffled",
                       prequential(regressors()["linear SGD"], X, ysh, ts, ready_y), y, day))
    rows[-1] |= {"target": "y shuffled"}

    ok = np.isfinite(hit)
    Xh = [x for x, k in zip(X, ok) if k]
    yh, dayh, tsh, readyh = hit[ok], day[ok], ts[ok], ready_h[ok]
    base = float(yh.mean())
    print(f"\ntarget: +-1 ATR within 12 bars, ties to the stop (base rate {base:.1%})")
    for name, mk in classifiers().items():
        t0 = time.time()
        rows.append(report(name, prequential(mk, Xh, yh, tsh, readyh, clf=True),
                           yh, dayh, clf=True, base=base))
        rows[-1] |= {"target": "hit", "secs": round(time.time() - t0, 1)}

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "online.csv", index=False)
    print(f"\nwritten: {OUT / 'online.csv'}")


if __name__ == "__main__":
    main()
