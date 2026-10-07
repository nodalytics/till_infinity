"""Change what the model optimises for, and see whether the signal sharpens.

Asked 2026-10-07, off the finding in `zscore-variants.md` that a boosted model
finds something real (+0.056 ATR at the decile, against a flat shuffled control)
and still loses to two hand-written inequalities. The diagnosis there was that
**squared error over every bar optimises the middle**, while the hand condition
goes straight to the rare corner where the effect lives. That is a claim about
the loss, so it is testable by changing the loss.

Six fits, one date split, one scoring function:

  mean        squared error on the forward move - the baseline
  q90 / q10   quantile loss. Predicts the *upper* and *lower* conditional
              quantile, which is what a trade with a target and a stop actually
              needs; the signal is `q10 > 0` (even the bad case is up)
  weighted    squared error weighted by |y|, so a big move counts for more
  corner      the same squared error, but **fitted only on the rare corner** -
              bars already past 0.6 of the attainable z - so the capacity goes
              to telling those apart rather than to the 90% of bars nobody will
              trade
  barrier     a classifier on the **triple-barrier label**: did price reach
              +1 ATR before -1 ATR within `BARS`? That is the question a trade
              asks, and its output reads directly as a win rate

Scored out of sample at three sharpnesses, with the shuffled-target control
refit for each loss, and permutation importance on the test set so the thing
that carries it can be named.

  MT5BT_DB=... SYMBOLS=... IV=4h python research/ideas/zscore_ml2.py
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

ZW = (4, 6, 8, 12, 20, 36)
IV = os.environ.get("IV", "4h")
H = int(os.environ.get("H", 3))
BARS = int(os.environ.get("BARS", 12))     # the barrier label's horizon
BARRIER = float(os.environ.get("BARRIER", 1.0))  # in ATR, symmetric
CORNER = float(os.environ.get("CORNER", 0.6))
OUT = Path(os.environ.get("OUT", ".data/zml2"))
TRAIN = float(os.environ.get("TRAIN", 0.70))


def ceiling(n):
    return (n - 1) / np.sqrt(n)


def roll_z(x, n):
    s = pd.Series(x)
    sd = s.rolling(n).std(ddof=1)
    return ((s - s.rolling(n).mean()) / sd.replace(0.0, np.nan)).to_numpy()


def barrier_label(h_, l_, c, a, k, b):
    """+1 if the up barrier is touched first, 0 if the down one is, NaN if neither.

    **The stop wins a tie.** When a single bar spans both barriers the bar data
    cannot say which came first, and the desk's engine resolves that against the
    trade; labelling it a win here would teach the model an outcome the
    backtester would never pay.
    """
    out = np.full(len(c), np.nan)
    for i in range(len(c) - k):
        if not a[i] > 0:
            continue
        up, dn = c[i] + b * a[i], c[i] - b * a[i]
        hi = h_[i + 1:i + 1 + k]
        lo = l_[i + 1:i + 1 + k]
        tu = np.flatnonzero(hi >= up)
        td = np.flatnonzero(lo <= dn)
        fu = tu[0] if len(tu) else 10**9
        fd = td[0] if len(td) else 10**9
        if fu == 10**9 and fd == 10**9:
            continue
        out[i] = 1.0 if fu < fd else 0.0
    return out


def one(sym):
    import run as R
    import survivors
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, IV)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    o, h_, l_, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = P.atr(df, 14)
    rng = np.maximum(h_ - l_, 1e-12)
    out = {"sym": sym, "ts": df["ts"].to_numpy()}
    for n in ZW:
        z = roll_z(c, n) / ceiling(n)
        out[f"z{n}"] = z
        if n in (6, 12, 36):
            out[f"dz{n}"] = np.r_[np.nan, np.diff(z)]
    out["z_fast_slow"] = out["z8"] - out["z36"]
    out["body"] = np.abs(c - o) / rng
    with np.errstate(invalid="ignore", divide="ignore"):
        out["body_atr"] = np.where(a > 0, np.abs(c - o) / a, np.nan)
        out["range_atr"] = np.where(a > 0, rng / a, np.nan)
        out["atr_rel"] = np.where(a > 0, a / pd.Series(a).rolling(100).mean().to_numpy(), np.nan)
        fwd = np.full(len(c), np.nan)
        fwd[:-H] = c[H:] - c[:-H]
        out["y"] = np.where(a > 0, fwd / a, np.nan)
    out["up"] = (c >= o).astype(float)
    out["wick_up"] = (h_ - np.maximum(o, c)) / rng
    out["wick_dn"] = (np.minimum(o, c) - l_) / rng
    out["hit"] = barrier_label(h_, l_, c, a, BARS, BARRIER)
    return pd.DataFrame(out)


FEATURES = [f"z{n}" for n in ZW] + ["dz6", "dz12", "dz36", "z_fast_slow",
                                    "body", "body_atr", "range_atr", "atr_rel",
                                    "up", "wick_up", "wick_dn"]


def block_ci(v, days, draws=1500, seed=53):
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    v, days = v[ok], np.asarray(days)[ok]
    if len(v) < 40:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def score(name, pred, te, col="y"):
    y, dt = te[col].to_numpy(), te["day"].to_numpy()
    ok = np.isfinite(y) & np.isfinite(pred)
    y, dt, pred = y[ok], dt[ok], pred[ok]
    row = {"model": name, "n": len(y)}
    bits = []
    for q in (0.10, 0.05, 0.01):
        hi_, lo_ = np.quantile(pred, [1 - q, q])
        up, dn = pred >= hi_, pred <= lo_
        m_t, l_t, h_t = block_ci(y[up], dt[up])
        m_b, _, _ = block_ci(y[dn], dt[dn])
        bits.append(f"{q:.0%} {m_t - m_b:+.3f} (top {m_t:+.3f} [{l_t:+.3f},{h_t:+.3f}] n={int(up.sum())})")
        row |= {f"sp{int(q * 100)}": m_t - m_b, f"top{int(q * 100)}": m_t,
                f"lo{int(q * 100)}": l_t, f"hi{int(q * 100)}": h_t}
    print(f"  {name:<26} " + "  ".join(bits))
    return row


def fit(tr, te, y, loss="squared_error", quantile=None, weight=None, clf=False, seed=0):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    kw = dict(max_iter=300, learning_rate=0.05, max_depth=4, min_samples_leaf=200,
              l2_regularization=1.0, random_state=seed)
    if clf:
        m = HistGradientBoostingClassifier(**kw)
        m.fit(tr[FEATURES], y, sample_weight=weight)
        return m, m.predict_proba(te[FEATURES])[:, 1]
    m = HistGradientBoostingRegressor(loss=loss, quantile=quantile, **kw)
    m.fit(tr[FEATURES], y, sample_weight=weight)
    return m, m.predict(te[FEATURES])


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=FEATURES).reset_index(drop=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    d = d.sort_values("ts").reset_index(drop=True)
    cut = d["ts"].quantile(TRAIN)
    gap = max(H, BARS) * {"1h": 3600, "4h": 14400, "1d": 86400}[IV]
    tr, te = d[d["ts"] <= cut - gap], d[d["ts"] > cut]
    print(f"{len(d):,} rows, {d['sym'].nunique()} instruments, forward {H} bars of {IV}")
    print(f"train {len(tr):,}, test {len(te):,}, boundary purged by {max(H, BARS)} bars")
    print(f"barrier label: +-{BARRIER:g} ATR within {BARS} bars, ties to the stop; "
          f"base rate {d['hit'].mean():.1%} on {int(d['hit'].notna().sum()):,} labelled bars\n")

    rows = []
    print("out of sample, forward move in ATR:")
    _, p_mean = fit(tr, te, tr["y"].to_numpy())
    rows.append(score("mean (baseline)", p_mean, te))
    _, p90 = fit(tr, te, tr["y"].to_numpy(), loss="quantile", quantile=0.9, seed=2)
    rows.append(score("quantile 0.90", p90, te))
    _, p10 = fit(tr, te, tr["y"].to_numpy(), loss="quantile", quantile=0.1, seed=3)
    rows.append(score("quantile 0.10", p10, te))
    # Both quantiles averaged: a bar is attractive when the *bad* case is
    # already up and the good case is well up, which is nearer to what a trade
    # needs than a conditional mean is.
    rows.append(score("q10 and q90 together", (p10 + p90) / 2, te))
    w = np.abs(tr["y"].to_numpy())
    _, p_w = fit(tr, te, tr["y"].to_numpy(), weight=w, seed=4)
    rows.append(score("weighted by |y|", p_w, te))

    corner_tr = tr[tr[[f"z{n}" for n in ZW]].abs().max(axis=1) >= CORNER]
    corner_te = te[te[[f"z{n}" for n in ZW]].abs().max(axis=1) >= CORNER]
    _, p_c = fit(corner_tr, corner_te, corner_tr["y"].to_numpy(), seed=5)
    print(f"  (corner: trained on {len(corner_tr):,} of {len(tr):,}, "
          f"scored on {len(corner_te):,} of {len(te):,})")
    rows.append(score("corner only", p_c, corner_te))

    lab_tr = tr[np.isfinite(tr["hit"])]
    lab_te = te[np.isfinite(te["hit"])]
    _, p_h = fit(lab_tr, lab_te, lab_tr["hit"].to_numpy().astype(int), clf=True, seed=6)
    rows.append(score("barrier classifier", p_h, lab_te))

    print("\nthe barrier classifier read as a trade (+-1 ATR, ties to the stop):")
    base = lab_te["hit"].mean()
    for q in (0.20, 0.10, 0.05, 0.01):
        th = np.quantile(p_h, 1 - q)
        sel = p_h >= th
        wr = lab_te["hit"].to_numpy()[sel].mean()
        m_, l_, h_ = block_ci(lab_te["hit"].to_numpy()[sel], lab_te["day"].to_numpy()[sel])
        print(f"  top {q:>5.0%}  n={int(sel.sum()):>6}  win rate {wr:.1%} "
              f"[{l_:.1%},{h_:.1%}]  against a base rate of {base:.1%}  "
              f"-> {2 * wr - 1:+.3f} R at 1:1 before costs")

    rng = np.random.default_rng(11)
    ysh = tr["y"].to_numpy().copy()
    for s_ in tr["sym"].unique():
        wix = np.flatnonzero(tr["sym"].to_numpy() == s_)
        ysh[wix] = rng.permutation(ysh[wix])
    _, p_sh = fit(tr, te, ysh, seed=7)
    print()
    rows.append(score("shuffled control", p_sh, te))

    print("\npermutation importance on the test set (drop in the 10% spread):")
    base_sp = rows[0]["sp10"]
    imp = []
    rr = np.random.default_rng(13)
    m_mean, _ = fit(tr, te, tr["y"].to_numpy(), seed=0)
    for f in FEATURES:
        t2 = te.copy()
        t2[f] = rr.permutation(t2[f].to_numpy())
        p2 = m_mean.predict(t2[FEATURES])
        y, dt = te["y"].to_numpy(), te["day"].to_numpy()
        hi_, lo_ = np.quantile(p2, [0.9, 0.1])
        sp = np.nanmean(y[p2 >= hi_]) - np.nanmean(y[p2 <= lo_])
        imp.append((f, base_sp - sp))
    for f, v in sorted(imp, key=lambda x: -x[1])[:10]:
        print(f"  {f:<14} {v:+.4f}")

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "losses.csv", index=False)
    print(f"\nwritten: {OUT / 'losses.csv'}")


if __name__ == "__main__":
    main()
