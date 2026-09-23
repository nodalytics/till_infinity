"""The crash-timing score as a risk switch rather than a direction call.

`crashlab.py` showed the big-move model ranks crashes and melt-ups equally well:
it knows *when*, not *which way*. What that is worth is on the risk side, so the
question here is what a position held through a high-score window suffers, and
whether acting on the score - smaller size, a wider stop - improves the
distribution of outcomes without costing return.

Score: P(some bar in the next H exceeds 4x baseline, either sign), a gradient-boosted
model fit on each series' first 60% by time, scored on the last 40%.

Two toy positions stand in for "whatever the desk is holding", because the switch
must work without knowing the direction:
  long      always long, held H bars
  momentum  the sign of the last 20 bars, held H bars

Three policies:
  flat      size 1 always
  halve     size 0.5 when the score is above its training 80th percentile
  inverse   size proportional to 1 / predicted E|move|, normalised to mean 1 on training

And the stop question, on the same positions: a stop at 1U (U = baseline x sqrt(H))
against one at 2U with half the size, so the money at risk is identical - both as a
resting stop order taken out by the wick, and as an exit on a close beyond the level.

Run from the repository root:  .venv-research/bin/python research/harness/riskswitch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).parent))
from horizons import build
from bars import race
from questions import H_FOR, paths
from spikerisk import DAILY, SERIES


def summary(x):
    x = x[~np.isnan(x)]
    cum = np.cumsum(x)
    mdd = np.max(np.maximum.accumulate(cum) - cum) if len(cum) else np.nan
    return dict(mean=x.mean(), sd=x.std(), sharpe=x.mean() / x.std() if x.std() else np.nan,
                p1=np.quantile(x, 0.01), worst=x.min(), mdd=mdd)


def run(interval, universe):
    H = H_FOR[interval]
    d, cols = build(interval, universe)
    d = d.drop(columns=[c for c in d.columns if "@" in c])
    X = d[cols].to_numpy(float)
    fut = paths(d, H)
    unit = d["_base"].to_numpy() * np.sqrt(H)
    z = fut.c / unit[:, None]
    end = z[:, -1]
    big = (np.nanmax(np.abs(np.diff(np.column_stack([np.zeros(len(d)), fut.c]), axis=1)), axis=1)
           > 4 * d["_base"].to_numpy()).astype(float)
    absmove = np.abs(end)
    split = d.split.to_numpy()
    ok = ~np.isnan(end)
    tr, te = ok & (split == 0), ok & (split > 0)
    slot = te & ((d["_pos"].to_numpy() % H) == 0)

    p = np.full(len(d), np.nan)
    p[ok] = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                           min_samples_leaf=200).fit(X[tr], big[tr]).predict_proba(X[ok])[:, 1]
    e = np.full(len(d), np.nan)
    e[ok] = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200,
                                          min_samples_leaf=200).fit(X[tr], absmove[tr]).predict(X[ok])
    e = np.clip(e, np.nanquantile(e[tr], 0.01), None)

    print(f"\n{'=' * 100}\n{interval}, H={H} bars, {slot.sum():,} non-overlapping test positions")
    q = pd.qcut(p[slot], 5, labels=False)
    mae = np.clip(-np.nanmin(fut.l[slot], axis=1), 0, None) / unit[slot]   # wicks, not closes
    mfe = np.clip(np.nanmax(fut.h[slot], axis=1), 0, None) / unit[slot]
    print("score quintile -> what a position lives through (U units):")
    print(f"{'q':>3} {'P(4x bar)':>9} {'E|end|':>7} {'MAE p95':>8} {'MFE p95':>8} {'P(|end|>2U)':>11}")
    for k in range(5):
        m = q == k
        print(f"{k + 1:>3} {big[slot][m].mean():9.1%} {absmove[slot][m].mean():7.2f} {np.quantile(mae[m], .95):8.2f} "
              f"{np.quantile(mfe[m], .95):8.2f} {np.mean(absmove[slot][m] > 2):11.1%}")

    hi = p >= np.quantile(p[tr], 0.8)
    inv = 1 / e
    inv = inv / np.nanmean(inv[tr])
    sizes = {"flat": np.ones(len(d)), "halve": np.where(hi, 0.5, 1.0), "inverse": inv}
    mom = np.sign(d.mom20.to_numpy())
    print(f"\n{'position':<9} {'policy':<8} {'mean':>7} {'sd':>6} {'sharpe':>7} {'1% tail':>8} {'worst':>7} {'max dd':>7}")
    out = []
    for pos_name, sgn in (("long", np.ones(len(d))), ("momentum", mom)):
        for pol, size in sizes.items():
            x = (sgn * size * end)[slot]
            s = summary(x)
            out.append(dict(interval=interval, position=pos_name, policy=pol, **s))
            print(f"{pos_name:<9} {pol:<8} {s['mean']:+7.3f} {s['sd']:6.3f} {s['sharpe']:+7.3f} {s['p1']:+8.2f} "
                  f"{s['worst']:+7.2f} {s['mdd']:7.1f}")

    print("\nstops, equal money at risk: 1U stop at size 1 vs 2U stop at size 0.5. 'wick' is a resting stop"
          " order (taken by the low, filled at the level or the open on a gap); 'close' exits on a close beyond it")
    idx = np.flatnonzero(slot)
    for pos_name, sgn in (("long", np.ones(len(d))), ("momentum", mom)):
        P = fut * sgn
        for stop, size in ((1, 1.0), (2, 0.5)):
            level = stop * unit
            w, fill = race(P, np.full(len(d), np.inf), level)
            wick = np.where(w == -1, fill, P.end) / unit
            crossed = P.c <= -level[:, None]
            first = np.argmax(crossed, axis=1)
            closed = np.where(crossed.any(axis=1), P.c[np.arange(len(d)), first], P.end) / unit
            for name, m in (("low score", ~hi[idx]), ("high score", hi[idx])):
                k = idx[m]
                wk, cl = size * wick[k], size * closed[k]
                print(f"  {pos_name:<9} {stop}U x{size:.1f} {name:<10}: wick stopped {np.mean(w[k] == -1):5.1%} "
                      f"mean {wk.mean():+.3f} 1% {np.quantile(wk, .01):+.2f} | close stopped "
                      f"{np.mean(crossed[k].any(axis=1)):5.1%} mean {cl.mean():+.3f} 1% {np.quantile(cl, .01):+.2f}")
    return out


if __name__ == "__main__":
    rows = []
    for interval in ("15m", "1h"):
        rows += run(interval, SERIES)
    rows += run("1d", DAILY)
    Path(".data/research").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(".data/research/riskswitch.csv", index=False)
