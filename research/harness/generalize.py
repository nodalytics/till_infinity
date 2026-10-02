"""One volatility model for every market? Leave one family out, for the expansion alert and the
shock forecaster.

Both production models are already pooled: one model across FX, metals, crypto, stocks and Deriv.
The question here is stronger: does a family the model has **never seen** score as well as it does
when the family is in the training data? If so, a new instrument gets a working alert on its
first day, and volatility's precursors are a property of markets rather than of each family.

Pre-registered (2026-10-02), before any run.

  data      the lab's broker bars (SEQLAB) for expansion_build.py's universe: 15 FX pairs, gold and
            silver, 3 coins, 20 stocks, 8 Deriv indices; 15m and 1h scored, 4h feeding the higher
            timeframe. Each series' first 60% of rows by time trains, its last 40% scores
  tasks     expansion   expansion_train.dataset: compressed bars, expansion within 16 bars
            shock       shocks_train.dataset: every bar, a shock within the next 4 bars
  models    per task and per held-out family F, each scored on F's test rows only
              pooled   trained on every family's training rows (production's arrangement)
              lofo     trained on every family's training rows except F's
              own      trained on F's training rows alone
  measures  AUC in each half of the test period; the top decile's calibration (realised over
            predicted) and lift
  passes    a family generalises if lofo's AUC is within 0.02 of pooled's in both halves and its
            top-decile calibration is within 0.7-1.4. "One model" holds if every real family does;
            Deriv is reported as its own market, under the same rule
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import expansion_build as eb

from till_infinity.models import expansion_train as et
from till_infinity.models import shocks_train as st

OUT = Path(os.environ.get("OUT", ".data/generalize"))
FAMS = list(eb.FAMILIES)


def split(keys: np.ndarray, when: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each series' first 60% by time trains; the test's later half is marked."""
    train = np.zeros(len(when), bool)
    second = np.zeros(len(when), bool)
    for k in np.unique(keys):
        m = np.flatnonzero(keys == k)
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        t = m[when[m] >= cut]
        if len(t):
            second[t] = when[t] >= np.median(when[t])
    return train, second


def auc(y, p):
    return round(float(et.auc(y, p)), 4) if len(y) > 50 and 0 < y.mean() < 1 else None


def evaluate(name: str, rows, trainer) -> dict:
    when, _kinds, x, y = rows.arrays()
    keys = np.array(rows.key)
    fam = np.array([eb.FAMILY.get(k.split("|")[0], "?") for k in keys])
    train, second = split(keys, when)
    test = ~train
    print(f"{name}: {len(y):,} rows, base rate {y.mean():.3f}", flush=True)

    def fit(mask):
        spec = trainer(x[mask], y[mask])
        return spec["_sklearn"]

    def predict(model, mask):
        z = x[mask].copy()
        return model.predict_proba(z)[:, 1]

    pooled = fit(train)
    out = {"rows": len(y), "base_rate": round(float(y.mean()), 4), "families": {}}
    for f in FAMS:
        tm = test & (fam == f)
        if tm.sum() < 500:
            continue
        cell = {"test_rows": int(tm.sum()), "base_rate": round(float(y[tm].mean()), 4)}
        models = {"pooled": pooled, "lofo": fit(train & (fam != f)), "own": fit(train & (fam == f))}
        for label, model in models.items():
            p = predict(model, tm)
            yy, ss = y[tm], second[tm]
            top = p >= np.quantile(p, 0.9)
            cell[label] = {
                "auc": auc(yy, p),
                "halves": [auc(yy[~ss], p[~ss]), auc(yy[ss], p[ss])],
                "calibration": round(float(yy[top].mean() / max(p[top].mean(), 1e-9)), 3),
                "lift": round(float(yy[top].mean() / max(yy.mean(), 1e-9)), 3),
            }
        gap = [None if (a is None or b is None) else round(a - b, 4)
               for a, b in zip(cell["lofo"]["halves"], cell["pooled"]["halves"], strict=True)]
        cell["lofo_minus_pooled"] = gap
        cell["generalises"] = bool(
            all(g is not None and g >= -0.02 for g in gap)
            and 0.7 <= cell["lofo"]["calibration"] <= 1.4
        )
        out["families"][f] = cell
        print(f"  {name} {f}: {json.dumps(cell)}", flush=True)
    real = [c["generalises"] for f, c in out["families"].items() if f != "deriv"]
    out["one_model_for_real_markets"] = bool(real) and all(real)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    series = {}
    for sym in eb.FAMILY:
        for iv in ("15m", "1h", "4h"):
            bars = eb.load(sym, iv)
            if len(bars) > 2_000:
                series[(sym, iv)] = bars
    print(f"{len(series)} series loaded ({time.time() - started:.0f}s)", flush=True)
    report = {}
    which = os.environ.get("TASKS", "expansion,shock").split(",")
    if "expansion" in which:
        report["expansion"] = evaluate("expansion", et.dataset(series), et.train)
        (OUT / "report.json").write_text(json.dumps(report, indent=1))
    if "shock" in which:
        scored = {k: v for k, v in series.items() if k[1] in st.SECONDS}
        report["shock"] = evaluate("shock", st.dataset(scored), st.train)
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({t: {"one_model_for_real_markets": r["one_model_for_real_markets"]}
                      for t, r in report.items()}), flush=True)
    print(f"done in {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
