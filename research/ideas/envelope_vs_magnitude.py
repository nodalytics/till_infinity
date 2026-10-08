"""Does the shipped envelope already know what the magnitude model found?

Asked 2026-10-08, and it is the check that decides whether
`zscore-magnitude.md` is an addition or a rediscovery. Predicting |move| is
volatility forecasting, and this desk already ships an offline quantile
forecaster that does exactly that - `models/envelope_train.py`, with its own
fortnightly retrain contest. The honest comparison is not against raw ATR, which
the magnitude model beats; it is against **the model already in production**.

Run on the envelope's own ground so nothing is tilted:

  * its bars - 15m, the fx family, `model_applies` deciding membership
  * its features - `MODEL_NAMES` = lvol, r1, r5, r20, rng, hour, replayed through
    `Touches` exactly as the engine builds them
  * its target - `log(close[i+h] / close[i]) / sigma[i]`, the signed move in
    volatility units, at its own horizons 5, 20 and 50

Scored against **|y|**, the magnitude, which is the quantity in dispute:

  envelope      the shipped model's interval half-width, (P90 - P10) / 2 - what
                a quantile forecast says about size
  direct        a magnitude regression on the **same six features**. If this
                beats the envelope, the information is in the features and the
                quantile fit is leaving it there
  mine          the same regression on the z-score feature set, to say whether
                those features add anything the envelope's do not
  shuffled      the direct fit on a permuted target, for the floor

A date split, trained before and scored after, with the boundary purged by the
horizon.

  MT5BT_DB=... python research/ideas/envelope_vs_magnitude.py
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

OUT = Path(os.environ.get("OUT", ".data/envvsmag"))
HORIZONS = (5, 20, 50)
TRAIN = 0.70


def bars_for(sym, limit=50_000):
    """mt5bt 15m bars as the production `Bar`, newest `limit`."""
    import run as R
    from till_infinity.prices.models import Bar
    df = R.load(sym, "15m")
    if df is None or len(df) < 5000:
        return None
    df = df.tail(limit).reset_index(drop=True)
    return [Bar(time=float(t), open=float(o), high=float(h), low=float(l), close=float(c),
                volume=float(v) if v == v else 0.0)
            for t, o, h, l, c, v in zip(df.ts, df.open, df.high, df.low, df.close,
                                        df.get("volume", pd.Series(0, index=df.index)))]


def ic(p, y):
    ok = np.isfinite(p) & np.isfinite(y)
    if ok.sum() < 200 or np.ptp(p[ok]) == 0:
        return np.nan
    return float(pd.Series(p[ok]).corr(pd.Series(y[ok]), method="spearman"))


def spread(p, y):
    ok = np.isfinite(p) & np.isfinite(y)
    if ok.sum() < 400 or np.ptp(p[ok]) == 0:
        return np.nan
    a, b = p[ok], y[ok]
    hi, lo = np.quantile(a, [0.9, 0.1])
    return float(b[a >= hi].mean() - b[a <= lo].mean())


def fit(xtr, ytr, xte, seed=0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=4,
                                      min_samples_leaf=200, l2_regularization=1.0,
                                      random_state=seed)
    m.fit(xtr, ytr)
    return m.predict(xte)


def main() -> None:
    import run as R
    import survivors
    from till_infinity.models import envelope_train as et
    from till_infinity.structures.vol import envelope as ev
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")

    fam = os.environ.get("FAMILY", "fx")
    syms = [s for s in R.FAMILY if R.FAMILY[s] == fam and s not in R.FRESH]
    series = {}
    for s in syms:
        got = bars_for(s)
        if got and ev.model_applies(s.lower(), "15m"):
            series[(s, "15m")] = got
    print(f"{len(series)} {fam} series at 15m, "
          f"{sum(len(v) for v in series.values()):,} bars")
    # `family=` only exists on a later build than the lab's synced copy, and it
    # is redundant here: `series` already holds one family and nothing else.
    try:
        found = et.tracks(series, family=fam)
    except TypeError:
        found = et.tracks(series)
    print(f"replayed {len(found)} tracks through Touches\n")

    rows = []
    for h in HORIZONS:
        when, x, y = et.rows(found, h)
        ok = np.isfinite(y) & np.isfinite(x).all(axis=1)
        when, x, y = when[ok], x[ok], y[ok]
        if len(y) < 5000:
            print(f"horizon {h}: only {len(y)} rows")
            continue
        order = np.argsort(when)
        when, x, y = when[order], x[order], y[order]
        mag = np.abs(y)
        cut = np.quantile(when, TRAIN)
        gap = h * 900
        tr = when <= cut - gap
        te = when > cut
        print(f"=== horizon {h}: {len(y):,} rows, train {tr.sum():,}, test {te.sum():,}, "
              f"mean |y| {mag.mean():.3f}")

        # the shipped envelope, as the engine would read it
        env = np.full(len(y), np.nan)
        for i in np.flatnonzero(te):
            feat = dict(zip(ev.MODEL_NAMES, x[i], strict=False))
            # `family=` arrived with the family-aware contest and is not on the
            # lab's synced build. It defaults to "fx", which is the family under
            # test, so the fallback is the same call.
            try:
                q = ev.model_quantiles(h, feat, family=fam)
            except TypeError:
                q = ev.model_quantiles(h, feat)
            if q:
                env[i] = (q[-2] - q[1]) / 2.0        # (P90 - P10) / 2
        got = ic(env[te], mag[te]), spread(env[te], mag[te])
        print(f"    envelope (P90-P10)/2   IC {got[0]:+.4f}   spread {got[1]:+.3f}   "
              f"n={int(np.isfinite(env[te]).sum())}")
        rows.append(dict(horizon=h, model="envelope", ic=got[0], spread=got[1]))

        # a magnitude regression on the envelope's own features
        p = fit(x[tr], mag[tr], x[te], seed=1)
        got = ic(p, mag[te]), spread(p, mag[te])
        print(f"    direct on its features IC {got[0]:+.4f}   spread {got[1]:+.3f}")
        rows.append(dict(horizon=h, model="direct_same_features", ic=got[0], spread=got[1]))

        rng = np.random.default_rng(3)
        p = fit(x[tr], rng.permutation(mag[tr]), x[te], seed=2)
        got = ic(p, mag[te]), spread(p, mag[te])
        print(f"    shuffled target        IC {got[0]:+.4f}   spread {got[1]:+.3f}\n")
        rows.append(dict(horizon=h, model="shuffled", ic=got[0], spread=got[1]))

    t = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT / "envvsmag.csv", index=False)
    print(t.round(4).to_string(index=False))
    print(f"\nwritten: {OUT / 'envvsmag.csv'}")


if __name__ == "__main__":
    main()
