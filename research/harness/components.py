"""What the ensemble's independent components are.

`ensemble.py` found 15-22 eigenvalues of its signal correlation matrix above the
Marchenko-Pastur noise edge. Raw eigenvectors are hard to name - the first is a
blend of everything and each later one is forced orthogonal to it - so the
components above the edge are varimax-rotated: the same subspace, turned so each
component loads heavily on a few signals and near zero on the rest. That is what
makes "component 7 is the VIX term structure at every horizon" a sentence.

Per rotated component: the share of its squared loadings by feature family and by
horizon, its largest loadings, and its information coefficient - correlation with the
realised long-minus-short payoff - on the validation block and on the test block.
A component whose IC flips sign between the two is structure without direction.

Reads `.data/research/signals_{interval}.npz`, written by `ensemble.py`
(`ENSEMBLE_DUMP_ONLY=1` stops it there). Writes the rotated loadings to
`.data/research/components_{interval}.csv`.

Run from the repository root:  .venv-research/bin/python research/harness/components.py
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

H = {"15m": 8, "1h": 5, "1d": 5}


def varimax(L, iters=500, tol=1e-8):
    """Kaiser's varimax: rotate loadings L (p x k) to maximise the variance of squared loadings."""
    p, k = L.shape
    R = np.eye(k)
    last = 0.0
    for _ in range(iters):
        Lr = L @ R
        u, s, vt = np.linalg.svd(L.T @ (Lr**3 - Lr @ np.diag((Lr**2).sum(0)) / p))
        R = u @ vt
        if s.sum() - last < tol:
            break
        last = s.sum()
    return L @ R, R


def family(name):
    """'vix@8' -> ('vix', '8'); 'ev:shock_dn@4' -> ('event: shock_dn', '4'); 'pair@5' -> ('pair', '5')."""
    base, _, h = name.partition("@")
    return (f"event: {base[3:]}" if base.startswith("ev:") else base), h


def ic(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    return np.corrcoef(x[ok], y[ok])[0, 1] if ok.sum() > 30 and x[ok].std() > 0 else np.nan


def run(interval):
    path = Path(".data/research") / f"signals_{interval}.npz"
    if not path.exists():
        print(f"{interval}: no {path} - run ensemble.py first")
        return []
    z = np.load(path)  # plain arrays only; never allow_pickle
    S, names, val, test, value = z["S"], list(z["names"]), z["val"], z["test"], z["value"]
    ok = np.isfinite(value) & np.isfinite(S).all(axis=1)
    val, test = val & ok, test & ok
    mu, sd = S[val].mean(0), S[val].std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = (S - mu) / sd
    V = Z[val]
    C = np.corrcoef(V, rowvar=False)
    lam, vec = np.linalg.eigh(C)
    lam, vec = lam[::-1], vec[:, ::-1]
    p = V.shape[1]
    n_eff = V.shape[0] / H[interval]
    edge = (1 + np.sqrt(p / n_eff)) ** 2
    k = int((lam > edge).sum())
    L = vec[:, :k] * np.sqrt(lam[:k])       # loadings: correlation of each signal with each component
    Lr, _ = varimax(L)
    # orient each component so its largest loading is positive, order by variance explained
    Lr = Lr * np.sign(Lr[np.abs(Lr).argmax(0), np.arange(k)])
    order = np.argsort(-(Lr**2).sum(0))
    Lr = Lr[:, order]
    scores = Z @ np.linalg.pinv(Lr).T         # component scores for every bar

    print(f"\n{'=' * 100}\n{interval}: {p} signals, {k} components above the noise edge {edge:.2f} "
          f"(eigenvalues {', '.join(f'{x:.2f}' for x in lam[:k])})")
    rows = []
    for j in range(k):
        w2 = Lr[:, j] ** 2
        share = w2 / w2.sum()
        by_fam, by_h = defaultdict(float), defaultdict(float)
        for n, s in zip(names, share):
            f, h = family(n)
            by_fam[f] += s
            by_h[h] += s
        fams = sorted(by_fam.items(), key=lambda x: -x[1])
        hs = sorted(by_h.items(), key=lambda x: -x[1])
        top = np.argsort(-np.abs(Lr[:, j]))[:6]
        ic_v, ic_t = ic(scores[val, j], value[val]), ic(scores[test, j], value[test])
        label = " + ".join(f for f, s in fams[:2] if s >= 0.2) or fams[0][0]
        print(f"\nC{j + 1:<2} {label}   variance {w2.sum() / p:.1%}   IC validation {ic_v:+.3f}  test {ic_t:+.3f}")
        print("     families: " + ", ".join(f"{f} {s:.0%}" for f, s in fams[:4] if s >= 0.05))
        print("     horizons: " + ", ".join(f"{h} {s:.0%}" for h, s in hs[:3] if s >= 0.05))
        print("     loadings: " + ", ".join(f"{names[i]} {Lr[i, j]:+.2f}" for i in top))
        rows.append(dict(interval=interval, component=f"C{j + 1}", label=label, variance=w2.sum() / p,
                         ic_validation=ic_v, ic_test=ic_t,
                         families="; ".join(f"{f} {s:.0%}" for f, s in fams[:4] if s >= 0.05),
                         horizons="; ".join(f"{h} {s:.0%}" for h, s in hs[:3] if s >= 0.05),
                         top="; ".join(f"{names[i]} {Lr[i, j]:+.2f}" for i in top)))
    pd.DataFrame(Lr, index=names, columns=[f"C{j + 1}" for j in range(k)]).to_csv(
        Path(".data/research") / f"components_{interval}.csv")
    return rows


if __name__ == "__main__":
    rows = []
    for interval in ("15m", "1h", "1d"):
        rows += run(interval)
    pd.DataFrame(rows).to_csv(".data/research/components.csv", index=False)
