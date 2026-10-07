"""Take the sign away and see what is left.

Asked 2026-10-07: "for the z-score ML, can we remove the sign + or - and see if
it still sees something". It is the sharpest diagnostic available on this
problem, because there are two different claims hiding inside "the model sees
something":

  direction  it knows **which way** price goes
  magnitude  it knows **how far** price goes, whichever way

Only the first is a trade on its own; the second is a sizing and stop-placement
number, which this desk needs more. And the barrier result in `zscore-ml.md`
already hints which one is there: a model that shifted the odds of touching
+1 ATR before -1 ATR would have direction, and it did not - 48.7% against a base
rate of 48.6%.

Four fits, one date split:

  signed y        the baseline, for reference
  |y|             the same features against the **magnitude** of the move
  |y|, |features| sign stripped from both sides, so nothing can encode direction
  range           the forward realised range over the current ATR - the number a
                  stop is actually set from

Plus the diagnostic that answers the question directly: **how well does the
signed model's own prediction correlate with |y|?** If it correlates better with
the magnitude than with the signed move, then what it found was never direction.

  MT5BT_DB=... SYMBOLS=... python research/ideas/zscore_sign.py
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

OUT = Path(os.environ.get("OUT", ".data/zsign"))
TRAIN = float(os.environ.get("TRAIN", 0.70))
SIGNED = [f for f in Z.FEATURES if f.startswith(("z", "dz"))] + ["up"]


def one(sym):
    d = Z.one(sym)
    if d is None:
        return None
    o = d.copy()
    h = Z.H
    return o


def score(name, pred, y, day, note=""):
    ok = np.isfinite(pred) & np.isfinite(y)
    p, t, dd = pred[ok], y[ok], day[ok]
    if np.ptp(p) == 0:
        print(f"  {name:<30} constant")
        return {}
    ic = float(pd.Series(p).corr(pd.Series(t), method="spearman"))
    bits, row = [], dict(model=name, ic=ic, n=len(p))
    for q in (0.10, 0.01):
        hi_, lo_ = np.quantile(p, [1 - q, q])
        up, dn = p >= hi_, p <= lo_
        m_t, l_t, h_t = Z.block_ci(t[up], dd[up])
        m_b, _, _ = Z.block_ci(t[dn], dd[dn])
        bits.append(f"{q:.0%}: top {m_t:+.3f} [{l_t:+.3f},{h_t:+.3f}] "
                    f"bottom {m_b:+.3f} spread {m_t - m_b:+.3f}")
        row |= {f"top{int(q * 100)}": m_t, f"lo{int(q * 100)}": l_t,
                f"hi{int(q * 100)}": h_t, f"sp{int(q * 100)}": m_t - m_b}
    print(f"  {name:<30} IC {ic:+.4f}  " + "  ".join(bits) + note)
    return row


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(Z.one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=Z.FEATURES).reset_index(drop=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    d["absy"] = d["y"].abs()
    d = d.sort_values("ts").reset_index(drop=True)
    cut = d["ts"].quantile(TRAIN)
    gap = max(Z.H, Z.BARS) * 14400
    tr, te = d[d["ts"] <= cut - gap], d[d["ts"] > cut]
    print(f"{len(d):,} rows, train {len(tr):,}, test {len(te):,}")
    print(f"the signed move averages {d['y'].mean():+.4f} ATR and its magnitude "
          f"{d['absy'].mean():.4f} - the second is the bigger number by far\n")

    rows = []
    print("out of sample:")
    m_s, p_s = Z.fit(tr, te, tr["y"].to_numpy())
    rows.append(score("signed move (baseline)", p_s, te["y"].to_numpy(), te["day"].to_numpy()))
    m_a, p_a = Z.fit(tr, te, tr["absy"].to_numpy(), seed=2)
    rows.append(score("|move|", p_a, te["absy"].to_numpy(), te["day"].to_numpy()))

    # sign stripped from the features too: nothing left that can encode direction
    tr2, te2 = tr.copy(), te.copy()
    for f in SIGNED:
        tr2[f] = tr2[f].abs()
        te2[f] = te2[f].abs()
    m_b, p_b = Z.fit(tr2, te2, tr2["absy"].to_numpy(), seed=3)
    rows.append(score("|move| from |features|", p_b, te["absy"].to_numpy(), te["day"].to_numpy()))

    rng = np.random.default_rng(21)
    ash = tr["absy"].to_numpy().copy()
    for s_ in tr["sym"].unique():
        w = np.flatnonzero(tr["sym"].to_numpy() == s_)
        ash[w] = rng.permutation(ash[w])
    _, p_sh = Z.fit(tr, te, ash, seed=4)
    rows.append(score("|move|, y shuffled", p_sh, te["absy"].to_numpy(), te["day"].to_numpy()))

    # **The single-feature baselines.** On the signed problem two inequalities
    # beat the model, so the same question has to be asked here before any
    # credit is given to it: is the magnitude result just the current bar's own
    # range, or the ATR regime, under a heavier name?
    print("\n  single-feature baselines on |move|:")
    for f in ("range_atr", "body_atr", "atr_rel", "z8", "z36"):
        v = te[f].to_numpy()
        rows.append(score(f"  {f} alone", np.abs(v) if f.startswith("z") else v,
                          te["absy"].to_numpy(), te["day"].to_numpy()))

    print("\nthe diagnostic - what is the *signed* model's prediction actually tracking?")
    ys, ya = te["y"].to_numpy(), te["absy"].to_numpy()
    ok = np.isfinite(p_s)
    ic_signed = float(pd.Series(p_s[ok]).corr(pd.Series(ys[ok]), method="spearman"))
    ic_abs = float(pd.Series(np.abs(p_s[ok])).corr(pd.Series(ya[ok]), method="spearman"))
    print(f"  against the signed move   IC {ic_signed:+.4f}")
    print(f"  |prediction| against |move|   IC {ic_abs:+.4f}")
    print(f"  -> {'magnitude' if abs(ic_abs) > abs(ic_signed) else 'direction'} is the stronger of the two")

    print("\nand the magnitude model read as a stop: mean |move| by predicted decile")
    q = np.quantile(p_a, np.linspace(0, 1, 11))
    for i in range(10):
        sel = (p_a >= q[i]) & (p_a <= q[i + 1])
        m_, l_, h_ = Z.block_ci(te["absy"].to_numpy()[sel], te["day"].to_numpy()[sel])
        print(f"  decile {i + 1:>2}  n={int(sel.sum()):>6}  |move| {m_:.3f} [{l_:.3f},{h_:.3f}]")

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([r for r in rows if r]).to_csv(OUT / "sign.csv", index=False)
    print(f"\nwritten: {OUT / 'sign.csv'}")


if __name__ == "__main__":
    main()
