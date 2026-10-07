"""How much does each normalisation leak buy you, in apparent skill?

Asked 2026-10-07: "test models with information leakage in the data
normalisation process, use only 4h". It is a measurement worth having on its own,
because this session has already been fooled once - the first online run reported
an IC of +0.30 against an honest +0.0047 because it learned from each bar before
its label existed. That was a hundredfold inflation from one line.

So: take the same 4h data, the same model, the same test rows, and build the
features through pipelines that differ **only** in where their statistics come
from.

  honest        every statistic is trailing. Z-scores over a rolling window, the
                target over the ATR at the bar, split by date with the boundary
                purged. This is the baseline every other row is measured against
  scaler        features standardised with the mean and variance of the **whole**
                dataset, train and test together - the classic `fit_transform`
                on everything before splitting
  z_full        the z-scores themselves computed against the **full sample's**
                mean and standard deviation instead of a rolling window
  atr_full      the target divided by the sample's mean ATR instead of the ATR
                at the bar
  clip_full     features winsorised at the full sample's 1st and 99th percentiles
  random_split  honest features, but the test rows drawn at **random** instead of
                by date - so a 3-bar forward move sits on both sides of the split
  everything    all of them at once: the pipeline that looks reasonable in a
                notebook

Both targets, because they fail differently: the signed move, where there was
nothing to inflate, and |move|, where there is a real result that a leak could
flatter.

  MT5BT_DB=... SYMBOLS=... python research/ideas/zscore_leak.py
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

import prims as P  # noqa: E402
import zscore_ml2 as Z  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/zleak"))
TRAIN = float(os.environ.get("TRAIN", 0.70))
ZW = Z.ZW


def one(sym):
    """Both the honest features and the raw series the leaky ones need."""
    import run as R
    import survivors
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    d = Z.one(sym)
    if d is None:
        return None
    df = R.load(sym, "4h").reset_index(drop=True)
    c = df["close"].to_numpy()
    a = P.atr(df, 14)
    d = d.copy()
    d["close"] = c
    d["atr"] = a
    fwd = np.full(len(c), np.nan)
    fwd[:-Z.H] = c[Z.H:] - c[:-Z.H]
    d["fwd_px"] = fwd                      # the move in price, before any scaling
    return d


def rebuild(d, kind):
    """One pipeline's feature frame. `kind` names the single thing that leaks."""
    x = d.copy()
    if kind in ("z_full", "everything"):
        # the z-score against the whole sample, per instrument, instead of a
        # rolling window - the statistic a reader would call "standardised"
        for n in ZW:
            z = x.groupby("sym")["close"].transform(
                lambda s: (s - s.mean()) / (s.std(ddof=1) or np.nan))
            x[f"z{n}"] = z / Z.ceiling(n)
    if kind in ("atr_full", "everything"):
        # the target scaled by the sample's mean ATR rather than the ATR at the bar
        m = x.groupby("sym")["atr"].transform("mean")
        x["y"] = x["fwd_px"] / m
    if kind in ("clip_full", "everything"):
        for f in Z.FEATURES:
            lo, hi = x[f].quantile([0.01, 0.99])
            x[f] = x[f].clip(lo, hi)
    if kind in ("scaler", "everything"):
        for f in Z.FEATURES:
            s = x[f].std(ddof=0)
            x[f] = (x[f] - x[f].mean()) / (s if s else 1.0)
    x["absy"] = x["y"].abs()
    return x


def split(x, kind, rng):
    if kind in ("random_split", "everything"):
        pick = rng.random(len(x)) < TRAIN
        return x[pick], x[~pick]
    cut = x["ts"].quantile(TRAIN)
    gap = max(Z.H, Z.BARS) * 14400
    return x[x["ts"] <= cut - gap], x[x["ts"] > cut]


def score(pred, te, col):
    y = te[col].to_numpy()
    ok = np.isfinite(pred) & np.isfinite(y)
    p, t, dd = pred[ok], y[ok], te["day"].to_numpy()[ok]
    ic = float(pd.Series(p).corr(pd.Series(t), method="spearman"))
    hi_, lo_ = np.quantile(p, [0.9, 0.1])
    m_t, _, _ = Z.block_ci(t[p >= hi_], dd[p >= hi_])
    m_b, _, _ = Z.block_ci(t[p <= lo_], dd[p <= lo_])
    return ic, m_t - m_b


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 14))) as pool:
        parts = [p for p in pool.map(one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=Z.FEATURES + ["close", "atr"]).reset_index(drop=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    d = d.sort_values("ts").reset_index(drop=True)
    print(f"{len(d):,} 4h bars, {d['sym'].nunique()} instruments\n")

    kinds = ["honest", "scaler", "z_full", "atr_full", "clip_full", "random_split", "everything"]
    rows = []
    for target, col in (("signed move", "y"), ("|move|", "absy")):
        print(f"target: {target}")
        base = None
        for kind in kinds:
            rng = np.random.default_rng(99)
            x = rebuild(d, kind)
            tr, te = split(x, kind, rng)
            if len(tr) < 1000 or len(te) < 1000:
                continue
            _, p = Z.fit(tr, te, tr[col].to_numpy(), seed=1)
            ic, sp = score(p, te, col)
            base = (ic, sp) if kind == "honest" else base
            mult = f"  x{ic / base[0]:.1f} IC" if base and base[0] and kind != "honest" else ""
            print(f"  {kind:<14} IC {ic:+.4f}   decile spread {sp:+.4f}{mult}")
            rows.append(dict(target=target, pipeline=kind, ic=ic, spread=sp,
                             n_train=len(tr), n_test=len(te)))
        print()
    t = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT / "leak.csv", index=False)
    print(t.round(4).to_string(index=False))
    print(f"\nwritten: {OUT / 'leak.csv'}")


if __name__ == "__main__":
    main()
