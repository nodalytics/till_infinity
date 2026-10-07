"""The hand rules and the model, head to head, on the question a trade asks.

Asked 2026-10-07 - "so hand rules beat ML?" - and the honest answer needed one
more run, because the comparison so far was unfair in both directions.

The hand rules were scored on the **conditional mean of a forward move** and the
model was eventually scored on the **barrier** - did price reach +1 ATR before
-1 ATR - and the barrier is where the model died. Nobody had put the hand rules
through the same question. So this does, on the same bars, the same label and the
same test period:

  |z| >= 2 and a 70% body        the two inequalities from `zscore-window.md`
  normalised z >= 0.8 at N = 12  the best cell in `zscore-variants.md`
  term structure aligned         fast and slow both extended, from variant 2
  model, corner-trained          the best ML cell from `zscore-ml.md`
  model, barrier-trained         the classifier that already found nothing

A rule that shifts the mean but not the touch probability is a rule that dies at
the stop, and that is the only thing worth knowing about any of them.

  MT5BT_DB=... SYMBOLS=... python research/ideas/zscore_barrier.py
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

OUT = Path(os.environ.get("OUT", ".data/zbar"))
TRAIN = float(os.environ.get("TRAIN", 0.70))


def ci(v, days, draws=1500, seed=67):
    return Z.block_ci(v, days, draws=draws, seed=seed)


def row(name, mask, te, note=""):
    sel = te[mask & np.isfinite(te["hit"])]
    if len(sel) < 40:
        print(f"  {name:<34} n={len(sel):>6}  too few")
        return dict(rule=name, n=len(sel))
    wr, lo, hi = ci(sel["hit"].to_numpy(), sel["day"].to_numpy())
    m, l2, h2 = ci(sel["y"].to_numpy(), sel["day"].to_numpy())
    print(f"  {name:<34} n={len(sel):>6}  win {wr:.1%} [{lo:.1%},{hi:.1%}]  "
          f"-> {2 * wr - 1:+.3f} R at 1:1   mean move {m:+.3f} [{l2:+.3f},{h2:+.3f}] {note}")
    return dict(rule=name, n=len(sel), win=wr, win_lo=lo, win_hi=hi,
                r_at_1to1=2 * wr - 1, mean_move=m, move_lo=l2, move_hi=h2)


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(Z.one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=Z.FEATURES).reset_index(drop=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    d = d.sort_values("ts").reset_index(drop=True)
    cut = d["ts"].quantile(TRAIN)
    gap = max(Z.H, Z.BARS) * 14400
    tr, te = d[d["ts"] <= cut - gap], d[d["ts"] > cut]
    base_all = float(d["hit"].mean())
    base_te = float(te["hit"].mean())
    print(f"{len(d):,} bars, test {len(te):,}. Barrier +-{Z.BARRIER:g} ATR within "
          f"{Z.BARS} bars, ties to the stop.")
    print(f"base rate: {base_all:.1%} overall, {base_te:.1%} on the test period "
          f"-> {2 * base_te - 1:+.3f} R at 1:1 before costs\n")

    # the raw z at N = 12 in the units `zscore-window.md` used
    z12_raw = te["z12"].to_numpy() * Z.ceiling(12)
    rows = [row("everything (the base rate)", np.ones(len(te), bool), te)]
    print()
    rows.append(row("|z| >= 2 (N=12)", np.abs(z12_raw) >= 2, te))
    rows.append(row("|z| >= 2 and body >= 70%", (np.abs(z12_raw) >= 2) & (te["body"] >= 0.70), te,
                    "<- the two inequalities"))
    rows.append(row("normalised |z| >= 0.8 (N=12)", te["z12"].abs() >= 0.8, te,
                    "<- best cell in the study"))
    rows.append(row("term structure aligned", (te["z8"].abs() >= 0.5)
                    & (np.sign(te["z8"]) == np.sign(te["z36"])) & (te["z36"].abs() >= 0.4), te))
    rows.append(row("aligned and body >= 70%", (te["z8"].abs() >= 0.5)
                    & (np.sign(te["z8"]) == np.sign(te["z36"]))
                    & (te["z36"].abs() >= 0.4) & (te["body"] >= 0.70), te))
    print()

    corner_tr = tr[tr[[f"z{n}" for n in Z.ZW]].abs().max(axis=1) >= Z.CORNER]
    m, _ = Z.fit(corner_tr, corner_tr.head(1), corner_tr["y"].to_numpy(), seed=5)
    p = m.predict(te[Z.FEATURES])
    for q in (0.10, 0.01):
        rows.append(row(f"model (corner), top {q:.0%}", p >= np.quantile(p, 1 - q), te))
    lab_tr = tr[np.isfinite(tr["hit"])]
    mh, _ = Z.fit(lab_tr, lab_tr.head(1), lab_tr["hit"].to_numpy().astype(int), clf=True, seed=6)
    ph = mh.predict_proba(te[Z.FEATURES])[:, 1]
    for q in (0.10, 0.01):
        rows.append(row(f"model (barrier), top {q:.0%}", ph >= np.quantile(ph, 1 - q), te))

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "barrier.csv", index=False)
    print(f"\nwritten: {OUT / 'barrier.csv'}")


if __name__ == "__main__":
    main()
