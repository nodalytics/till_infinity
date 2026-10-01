"""River's online ensembles against the frozen gradient-boosted model, on the expansion alert.

research/docs/models.md compared river's bagging and forests on level touches (logistic regression
won). River's boosting and stacking were never tried, and no online model has been tried on a target
that works. This asks it on the expansion alert's own rows (structures/learning/expansion.py).

Pre-registered (2026-10-01), before any run.

  rows      expansion_build.py's rows (compressed bars, 15m and 1h, real markets and Deriv), in time
            order, every 3rd row (to keep the slow ensembles tractable); each series' first 60%
            by time is training
  features  the alert's 16; a missing value is 0 plus a missing flag (river models take no NaN)
  models    river: LogisticRegression (scaled), HoeffdingAdaptiveTree, ARF, AdaBoost (Hoeffding
            trees), ADWINBoosting, BOLE, LeveragingBagging, SRP, Stacking (LR + HT + ARF under an
            LR), Voting (the same, averaged); against sklearn HistGradientBoosting trained once on
            the training rows (what production ships)
  modes     online: test-then-train through the whole stream (river's natural mode, which keeps
            learning on the held-out rows); frozen: learn the training rows, then only predict
  judged    held-out AUC and both halves; memory (pickled bytes); microseconds per prediction
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT))

OUT = Path(os.environ.get("OUT", ".data/riverbench"))
DATA = OUT / "rows.npz"


def build() -> None:
    import expansion_build as eb
    from till_infinity.models import expansion_train as et
    from till_infinity.structures.learning import expansion as ex

    series = {}
    for sym in eb.FAMILY:
        for iv in ("15m", "1h", "4h"):
            bars = eb.load(sym, iv)
            if len(bars) > 2_000:
                series[(sym, iv)] = bars
    rows = et.dataset(series)
    when, kinds, x, y = rows.arrays()
    keys = np.array(rows.key)
    train = np.zeros(len(y), bool)
    second = np.zeros(len(y), bool)
    for k in np.unique(keys):
        m = np.flatnonzero(keys == k)
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        te = m[when[m] >= cut]
        second[te] = when[te] >= np.median(when[te])
    order = np.argsort(when, kind="stable")[::3]
    np.savez_compressed(DATA, x=x[order], y=y[order], train=train[order], second=second[order],
                        names=np.array(ex.NAMES))


def models():
    from river import compose, ensemble, forest, linear_model, preprocessing, tree

    def lr():
        return compose.Pipeline(preprocessing.StandardScaler(), linear_model.LogisticRegression())

    def ht():
        return tree.HoeffdingTreeClassifier(max_depth=6, grace_period=200)

    return {
        "river_logistic": lr,
        "river_hoeffding_adaptive": lambda: tree.HoeffdingAdaptiveTreeClassifier(max_depth=6, grace_period=200, seed=1),
        "river_arf": lambda: forest.ARFClassifier(n_models=10, seed=1),
        "river_adaboost": lambda: ensemble.AdaBoostClassifier(ht(), n_models=10, seed=1),
        "river_adwin_boosting": lambda: ensemble.ADWINBoostingClassifier(ht(), n_models=10, seed=1),
        "river_bole": lambda: ensemble.BOLEClassifier(ht(), n_models=10, seed=1),
        "river_leveraging_bagging": lambda: ensemble.LeveragingBaggingClassifier(ht(), n_models=10, seed=1),
        "river_srp": lambda: ensemble.SRPClassifier(n_models=10, seed=1),
        "river_stacking": lambda: ensemble.StackingClassifier(
            [lr(), ht(), forest.ARFClassifier(n_models=5, seed=2)], meta_classifier=lr()),
        # river's VotingClassifier only hard-votes; this averages the members' probabilities
        "river_voting": lambda: Average([lr(), ht(), forest.ARFClassifier(n_models=5, seed=3)]),
    }


class Average:
    """Soft voting: the mean of the members' P(1)."""

    def __init__(self, members):
        self.members = members

    def learn_one(self, x, y):
        for m in self.members:
            m.learn_one(x, y)

    def predict_proba_one(self, x):
        ps = []
        for m in self.members:
            pr = m.predict_proba_one(x)
            ps.append(pr.get(1.0, 0.0) if pr else 0.0)
        p = float(np.mean(ps))
        return {1.0: p, 0.0: 1 - p}


def as_dicts(x: np.ndarray) -> list[dict]:
    miss = np.isnan(x)
    xf = np.where(miss, 0.0, x)
    cols = [f"f{i}" for i in range(x.shape[1])]
    out = []
    for r, m in zip(xf, miss, strict=True):
        d = dict(zip(cols, r.tolist(), strict=True))
        for i in np.flatnonzero(m):
            d[f"m{i}"] = 1.0
        out.append(d)
    return out


def auc(y, p) -> float:
    from till_infinity.models.shocks_train import auc as a
    return round(a(y, p), 4)


def score(y, p, train, second) -> dict:
    te = ~train
    return dict(auc=auc(y[te], p[te]), halves=[auc(y[te & ~second], p[te & ~second]),
                                               auc(y[te & second], p[te & second])])


def bench(name: str) -> dict:
    z = np.load(DATA)
    x, y, train, second = z["x"], z["y"], z["train"], z["second"]
    X = as_dicts(x)
    out = {}
    for mode in ("online", "frozen"):
        model = models()[name]()
        p = np.full(len(y), np.nan)
        t0 = time.time()
        for k, (xi, yi) in enumerate(zip(X, y, strict=True)):
            if not train[k] or mode == "online":
                pr = model.predict_proba_one(xi)
                p[k] = pr.get(1.0, pr.get(True, 0.0)) if pr else 0.0
            if mode == "online" or train[k]:
                model.learn_one(xi, yi)
        out[mode] = score(y, p, train, second) | {"seconds": round(time.time() - t0)}
    sample = X[-2000:]
    t0 = time.perf_counter()
    for xi in sample:
        model.predict_proba_one(xi)
    out["us_per_prediction"] = round((time.perf_counter() - t0) / len(sample) * 1e6)
    out["kb"] = round(len(pickle.dumps(model)) / 1024)
    print(name, json.dumps(out), flush=True)
    return out


def frozen_gb() -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    z = np.load(DATA)
    x, y, train, second = z["x"], z["y"], z["train"], z["second"]
    m = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                       min_samples_leaf=300).fit(x[train], y[train])
    p = m.predict_proba(x)[:, 1]
    out = score(y, p, train, second)
    t0 = time.perf_counter()
    for row in x[-2000:]:
        m.predict_proba(row[None, :])
    out["us_per_prediction_sklearn"] = round((time.perf_counter() - t0) / 2000 * 1e6)
    out["kb"] = round(len(pickle.dumps(m)) / 1024)
    print("frozen_gb", json.dumps(out), flush=True)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not DATA.exists():
        build()
    z = np.load(DATA)
    print(f"{len(z['y']):,} rows, {int(z['train'].sum()):,} training, base rate {z['y'].mean():.3f}", flush=True)
    res = {"rows": int(len(z["y"])), "frozen_gb": frozen_gb()}
    names = list(models())
    with ProcessPoolExecutor(len(names)) as pool:
        for name, r in zip(names, pool.map(bench, names), strict=True):
            res[name] = r
    (OUT / "riverbench.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
