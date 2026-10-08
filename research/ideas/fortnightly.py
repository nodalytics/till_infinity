"""Score a model the way production runs it: refit every fortnight, promote on gates.

Asked for 2026-10-08 - "can we recalibrate models every 2 weeks based on data,
for offline models training included, cause that is how it is gonna be in real
life". The gap is not production, which already runs
`till-infinity models retrain --every-days 14`. The gap is **this** side: every
model in `zscore-magnitude.md` was fitted once and scored on everything after,
which is not a number the desk could ever have collected.

So this mirrors `models/retrain.py` rather than inventing a protocol, including
the part a plain walk-forward leaves out:

  1. every `CADENCE` (14) days, hold out the most recent `HOLDOUT_DAYS` (14)
  2. train a **challenger** on everything before that hold-out
  3. score challenger and **champion** - the model actually in service - on the
     hold-out, which neither was trained on
  4. **promote only if the challenger wins**; otherwise the champion stays and
     keeps trading. A retrain that ships because it is newer rather than better
     is how a working model gets replaced by a broken one
  5. trade the fortnight after that with whichever model is in service

Step 4 is the one that matters and the one a walk-forward cannot see. A plain
walk-forward always uses the newest fit, so it measures a desk that redeploys
blindly; this measures the desk that exists.

Three arms, because the difference between them is the whole question:

  fit_once      train once on the first 70%, score everything after - what
                `zscore-magnitude.md` reported
  always_new    refit every fortnight, always deploy the challenger
  gated         refit every fortnight, deploy only on a win - production's rule

And two training windows, because a desk does not necessarily keep all history:
expanding, and trailing `TRAIL_DAYS`.

  MT5BT_DB=... IV=4h python research/ideas/fortnightly.py
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

import zscore_ml2 as Z  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/fortnightly"))
CADENCE = int(os.environ.get("CADENCE", 14))        # days between retrains
HOLDOUT = int(os.environ.get("HOLDOUT", 14))        # days held out to judge on
WARM = int(os.environ.get("WARM", 540))             # days before the first fit
TRAIL = int(os.environ.get("TRAIL", 730))           # trailing-window length
DAY = 86400


def ic(pred, y):
    ok = np.isfinite(pred) & np.isfinite(y)
    if ok.sum() < 100 or np.ptp(pred[ok]) == 0:
        return np.nan
    return float(pd.Series(pred[ok]).corr(pd.Series(y[ok]), method="spearman"))


def spread(pred, y):
    ok = np.isfinite(pred) & np.isfinite(y)
    if ok.sum() < 200 or np.ptp(pred[ok]) == 0:
        return np.nan
    p, t = pred[ok], y[ok]
    hi, lo = np.quantile(p, [0.9, 0.1])
    return float(t[p >= hi].mean() - t[p <= lo].mean())


def run(d, mode, window, target="absy"):
    """One pass of the protocol. Returns the traded fortnights, in order."""
    ts = d["ts"].to_numpy()
    t0, t1 = ts.min(), ts.max()
    gap = max(Z.H, Z.BARS) * {"1h": 3600, "4h": 14400, "1d": 86400}[os.environ.get("IV", "4h")]
    champion, rows = None, []
    first = t0 + WARM * DAY
    for k, now in enumerate(np.arange(first, t1, CADENCE * DAY)):
        hold_from = now - HOLDOUT * DAY
        train_to = hold_from - gap
        lo = train_to - TRAIL * DAY if window == "trailing" else t0
        tr = d[(d.ts > lo) & (d.ts <= train_to)]
        ho = d[(d.ts > hold_from) & (d.ts <= now)]
        nxt = d[(d.ts > now) & (d.ts <= now + CADENCE * DAY)]
        if len(tr) < 5000 or len(ho) < 300 or len(nxt) < 300:
            continue
        _, pc = Z.fit(tr, ho, tr[target].to_numpy(), seed=k)
        chal_ic = ic(pc, ho[target].to_numpy())
        # the contest, on data neither model saw
        if champion is None:
            promoted, champ_ic = True, np.nan
        else:
            champ_ic = ic(champion.predict(ho[Z.FEATURES]), ho[target].to_numpy())
            promoted = bool(np.isfinite(chal_ic) and (not np.isfinite(champ_ic)
                                                      or chal_ic > champ_ic))
        if mode == "always_new" or (mode == "gated" and promoted) or champion is None:
            champion, _ = Z.fit(tr, tr.head(1), tr[target].to_numpy(), seed=k)
            served = "challenger"
        else:
            served = "champion"
        p = champion.predict(nxt[Z.FEATURES])
        rows.append(dict(mode=mode, window=window, fortnight=k,
                         date=str(pd.to_datetime(now, unit="s").date()),
                         n_train=len(tr), n=len(nxt), served=served,
                         chal_ic=chal_ic, champ_ic=champ_ic, promoted=promoted,
                         ic=ic(p, nxt[target].to_numpy()),
                         spread=spread(p, nxt[target].to_numpy())))
    return pd.DataFrame(rows)


def main() -> None:
    import run as R
    iv = os.environ.get("IV", "4h")
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 14))) as pool:
        parts = [p for p in pool.map(Z.one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=Z.FEATURES).reset_index(drop=True)
    d["absy"] = d["y"].abs()
    d = d.sort_values("ts").reset_index(drop=True)
    span = (d.ts.max() - d.ts.min()) / DAY
    print(f"{len(d):,} {iv} bars, {d['sym'].nunique()} instruments, {span:.0f} days")
    print(f"retrain every {CADENCE}d, judged on the last {HOLDOUT}d, "
          f"first fit after {WARM}d\n")

    out = []
    for window in ("expanding", "trailing"):
        for mode in ("always_new", "gated"):
            t = run(d, mode, window)
            if t.empty:
                continue
            out.append(t)
            pos = (t.ic > 0).sum()
            print(f"{window:<10} {mode:<11} {len(t):>3} fortnights  "
                  f"IC mean {t.ic.mean():+.4f}  median {t.ic.median():+.4f}  "
                  f"positive {pos}/{len(t)}   spread mean {t.spread.mean():+.3f}   "
                  f"promoted {int(t.promoted.sum())}/{len(t)}  "
                  f"served challenger {int((t.served=='challenger').sum())}")
    # the figure the desk has been quoting, for comparison
    cut = d.ts.quantile(0.70)
    gap = max(Z.H, Z.BARS) * {"1h": 3600, "4h": 14400, "1d": 86400}[iv]
    a, b = d[d.ts <= cut - gap], d[d.ts > cut]
    _, p = Z.fit(a, b, a["absy"].to_numpy(), seed=99)
    print(f"\n{'fit_once':<10} {'(published)':<11}   1 fit         "
          f"IC {ic(p, b['absy'].to_numpy()):+.4f}                       "
          f"spread      {spread(p, b['absy'].to_numpy()):+.3f}")
    if out:
        t = pd.concat(out, ignore_index=True)
        OUT.mkdir(parents=True, exist_ok=True)
        t.to_csv(OUT / "fortnightly.csv", index=False)
        pd.set_option("display.width", 220)
        g = t[(t["window"] == "expanding") & (t["mode"] == "gated")]
        print("\n=== expanding + gated, production's own rule, fortnight by fortnight ===")
        print(g[["date", "n_train", "n", "served", "chal_ic", "champ_ic", "ic", "spread"]]
              .round(4).to_string(index=False))
        print(f"\nwritten: {OUT / 'fortnightly.csv'}")


if __name__ == "__main__":
    main()
