"""Do Deriv synthetics move together, even briefly?

`generated.md` found no shared driver across 325 synthetic pairs, and `linear-algebra.md`
found no eigenvalue of their correlation matrix outside the noise band - both over whole
samples. The desk's objection is fair: a co-movement that lasts an afternoon is a regime
too, and a full-sample average would bury it. So this asks it window by window.

For every window of W bars (50 and 200, non-overlapping), across all synthetics at once:

  lambda1     the largest eigenvalue of the window's correlation matrix - how much of the
              window's movement one common factor carries
  max |r|     the strongest pair in the window

Neither means anything alone: 60 random walks over 50 bars produce large correlations by
chance, and the largest of 1,800 pairs is always impressive. So each is compared against
a **null that keeps every series intact** - each is circularly shifted by its own random
offset, which preserves its volatility, its jumps and its autocorrelation and destroys only
its alignment with the others. If the synthetics share even a transient driver, real
windows exceed the null's 99th percentile far more often than 1% of the time.

Then the question a trade needs answered: **persistence.** Across every pair and every pair
of consecutive windows, does a pair's correlation in one window predict its correlation in
the next? A co-movement regime that does not persist into the next window cannot be traded,
however real it was.

**The positive control** runs the identical pipeline on the real FX majors in the same
files. The dollar is a shared driver there, so the test must find it - lambda1 far above the
null and strong persistence. If it did not, a null on the synthetics would mean nothing.

Returns are log returns, winsorised at 5 standard deviations per series so a single Boom or
Crash spike cannot make a window's correlation. Series are aligned on common timestamps.

Run on the lab (reads its seqlab/ bars):
  ./.secrets/lab.sh run research/harness/comovement.py SEQLAB=$HOME/till_infinity/data/seqlab
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(os.environ.get("SEQLAB", ".data/seqlab"))
INTERVALS = ("3m", "15m", "1h")
WINDOWS = (50, 200)
SHIFTS = 30
RNG = np.random.default_rng(7)
FX = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
      "AUDJPY", "EURGBP", "EURCHF", "EURAUD", "CHFJPY"]


def load(names, interval):
    cols = {}
    for n in names:
        f = DATA / f"{n}.{interval}.npz"
        if not f.exists():
            continue
        z = np.load(f)  # plain arrays; never allow_pickle
        s = pd.Series(z["close"], index=z["time"].astype(np.int64))
        s = s[~s.index.duplicated()]
        cols[n] = s
    px = pd.DataFrame(cols).sort_index().dropna()
    r = np.log(px).diff().iloc[1:]
    r = r.loc[:, r.std() > 0]
    z = (r - r.mean()) / r.std()
    return z.clip(-5, 5), px


def window_stats(X, W):
    """lambda1 and max |r| per non-overlapping window of W rows; and per-pair correlations."""
    n = X.shape[0] // W
    lam, mx, pairs = np.empty(n), np.empty(n), []
    iu = np.triu_indices(X.shape[1], 1)
    for i in range(n):
        w = X[i * W:(i + 1) * W]
        sd = w.std(0)
        ok = sd > 0
        C = np.corrcoef(w[:, ok], rowvar=False)
        lam[i] = np.linalg.eigvalsh(C)[-1]
        full = np.full((X.shape[1], X.shape[1]), np.nan)
        full[np.ix_(ok, ok)] = C
        v = full[iu]
        mx[i] = np.nanmax(np.abs(v))
        pairs.append(v)
    return lam, mx, np.array(pairs)


def shifted(X):
    """Each column circularly shifted by its own random offset: same series, no alignment."""
    out = np.empty_like(X)
    for j in range(X.shape[1]):
        out[:, j] = np.roll(X[:, j], RNG.integers(X.shape[0] // 10, X.shape[0] - X.shape[0] // 10))
    return out


def persistence(P):
    """Correlation between a pair's r in window w and in window w+1, pooled over pairs."""
    a, b = P[:-1].ravel(), P[1:].ravel()
    ok = np.isfinite(a) & np.isfinite(b)
    return np.corrcoef(a[ok], b[ok])[0, 1]


def top_persistence(P, q=0.99):
    """Among pair-windows in the top 1% of |r|: mean r in the next window, signed by this one."""
    a, b = P[:-1].ravel(), P[1:].ravel()
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    cut = np.quantile(np.abs(a), q)
    k = np.abs(a) >= cut
    return float(np.mean(np.sign(a[k]) * b[k])), float(np.mean(np.abs(a[k]))), int(k.sum())


def study(label, names, interval):
    Z, _ = load(names, interval)
    X = Z.to_numpy()
    if X.shape[1] < 3 or X.shape[0] < 1000:
        print(f"{label} {interval}: too little aligned data ({X.shape})")
        return []
    rows = []
    print(f"\n{'=' * 100}\n{label} {interval}: {X.shape[1]} series, {X.shape[0]:,} aligned bars")
    full = np.corrcoef(X, rowvar=False)
    iu = np.triu_indices(X.shape[1], 1)
    # full-sample: the strongest pairs, judged against the null's strongest pair
    null_max = [np.nanmax(np.abs(np.corrcoef(shifted(X), rowvar=False)[iu])) for _ in range(10)]
    order = np.argsort(-np.abs(full[iu]))[:5]
    cols = Z.columns
    print(f"full sample: lambda1 {np.linalg.eigvalsh(full)[-1]:.2f}; strongest pairs "
          + ", ".join(f"{cols[iu[0][k]]}/{cols[iu[1][k]]} {full[iu][k]:+.3f}" for k in order)
          + f"; null's strongest pair {np.mean(null_max):.3f} (max {np.max(null_max):.3f})")
    for W in WINDOWS:
        lam, mx, P = window_stats(X, W)
        nl, nm, npers, ntop = [], [], [], []
        for _ in range(SHIFTS):
            l0, m0, P0 = window_stats(shifted(X), W)
            nl.append(l0)
            nm.append(m0)
            npers.append(persistence(P0))
            ntop.append(top_persistence(P0)[0])
        nl, nm = np.concatenate(nl), np.concatenate(nm)
        l99, m99 = np.quantile(nl, 0.99), np.quantile(nm, 0.99)
        pers = persistence(P)
        tp, tp_abs, tp_n = top_persistence(P)
        row = dict(label=label, interval=interval, W=W, series=X.shape[1], windows=len(lam),
                   lam_median=np.median(lam), lam_null_median=np.median(nl),
                   share_lam_over_null99=np.mean(lam > l99), share_max_over_null99=np.mean(mx > m99),
                   persistence=pers, persistence_null=np.mean(npers), persistence_null_sd=np.std(npers),
                   top_next=tp, top_next_null=np.mean(ntop), top_next_null_sd=np.std(ntop),
                   top_abs=tp_abs, top_n=tp_n)
        rows.append(row)
        print(f"  W={W:>3} ({len(lam)} windows): lambda1 median {np.median(lam):.2f} vs null {np.median(nl):.2f}; "
              f"windows beyond the null's 99th pct: lambda1 {np.mean(lam > l99):.1%}, max|r| {np.mean(mx > m99):.1%} "
              f"(chance 1%)")
        print(f"         persistence r(w)->r(w+1) {pers:+.4f} vs null {np.mean(npers):+.4f} +- {np.std(npers):.4f}; "
              f"top-1% pairs (|r|~{tp_abs:.2f}, n={tp_n}) keep {tp:+.4f} next window vs null "
              f"{np.mean(ntop):+.4f} +- {np.std(ntop):.4f}")
    return rows


def synthetic_names():
    names = sorted({p.name.split(".")[0] for p in DATA.glob("*.3m.npz")})
    return [n for n in names if "Index" in n]


if __name__ == "__main__":
    out = []
    synth = synthetic_names()
    families = {
        "volatility": [n for n in synth if n.startswith("Volatility")],
        "all synthetics": synth,
    }
    for interval in INTERVALS:
        out += study("FX control", FX, interval)
        for label, names in families.items():
            out += study(label, names, interval)
    Path("results").mkdir(exist_ok=True)
    pd.DataFrame(out).to_csv("results/comovement.csv", index=False)
