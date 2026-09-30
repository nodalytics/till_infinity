"""Is there a market language? OHLC -> symbols -> grammar -> structural state -> regime transition.

`findings.md`: this desk forecasts risk, not direction. The formal-language question is aimed there.
Is there structure in the *sequence* of bar shapes beyond what volatility clustering alone makes,
and does it warn of shocks and volatility-regime transitions beyond the production shock forecaster?
Direction is checked for completeness, expecting a null.

Pre-registered, per family (FX, metals, crypto, and Deriv as a market), with walks we generate as the
control. iid t(3) has no structure at all. GARCH(1,1) has volatility clustering, which by itself
makes "compression -> expansion", so the GARCH walks are the bar any grammar has to clear.

1. The alphabet, two ways.
   (a) Hand-built, from production's structural vocabulary, as bar-level definitions: a sweep (wick
       through the 20-bar high/low, close back), a break (close through it), displacement
       (|r| > 2 vol, body > 60% of range), compression (true-range percentile < 0.2), expansion
       (> 0.8), and small up/down otherwise. 12 symbols. The Engine replay was too slow to symbolise
       every bar of 20 series; these are the same quantities production reads.
   (b) Learned: a Gaussian mixture on the bar's shape (return, log range, body, wicks, all in vol
       units), with k chosen by BIC, the MDL criterion for a mixture.
   For each: the alphabet size, and the information it keeps about the next bar's |r| quintile,
   I(S; Y) in bits.
2. Is there grammar? On each series' last 40%, with models fitted on the first 60%:
   - Markov log-loss at orders 0-6 (add-1/2, backing off to the lower order on unseen contexts).
     The grammar gain is order 0's log-loss minus the best order's, in bits per symbol, with a
     day-bootstrap CI.
   - LZ78 phrase count, as a share of a frequency-preserving shuffle's (< 1 means compressible
     beyond the symbol frequencies).
   - Re-Pair grammar size (rules x 2 + the final sequence), as a share of the shuffle's.
3. Stratigraphy and inheritance. The next bar's |r| quintile, by gradient boosting, out of sample:
   shallow (this symbol, the last, the volatility state) against shallow plus deep layers (symbol
   counts over the last 20 and 100 bars, bars since the last big move, position in and width of the
   100-bar range). The gain in log-loss per bar, with a day-bootstrap CI. It is inheritance only
   where it beats the same gain on GARCH walks.
4. Motifs -> transitions. The production shock label and features (`models/shocks_train.dataset`,
   the production `Shocks` class): AUC of gradient boosting on the shock features, against the same
   plus motif features. The motifs are the 30 most frequent hand 3-grams, the 30 most frequent
   learned 3-grams, and the order-3 surprise of the current symbol. The same for a volatility-
   regime transition (volatility state low -> high within 20 bars, from low bars only). Direction:
   the sign over the next 5 bars from the motifs alone. Univariate: each hand motif's shock rate
   against the base rate (two-proportion z), with BH, and the largest z against the expected
   maximum of N null trials (`lopezdeprado.expected_max`).

Pass bars:
- grammar beats GARCH walks (log-loss gain or compressibility) with the CI clear;
- inheritance's out-of-sample gain beats the GARCH walks' with the CI clear;
- motifs add >= 0.01 AUC over the shock features, the CI above 0, in both halves, surviving
  deflation.

Run on the lab, one process per family: FAMILY=fx|metals|crypto|deriv|walks
  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/grammar.py
"""
from __future__ import annotations

import math
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

FAMILY = os.environ.get("FAMILY", "walks")
START = pd.Timestamp(os.environ.get("START", "2024-06-01"), tz="UTC").timestamp()
BARS = int(os.environ.get("BARS", "0"))  # cap per series for smoke tests; 0 = all
FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY"],
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD"],
    "deriv": ["Volatility_75_Index", "Boom_1000_Index", "Jump_50_Index", "Step_Index"],
    "walks": ["iid_0", "iid_1", "iid_2", "garch_0", "garch_1", "garch_2"],
}
HAND = ["Su", "Sd", "Bu", "Bd", "Du", "Dd", "C", "Eu", "Ed", "u", "d", "x"]
SEED = 7


# ------------------------------------------------------------------------------------ the bars

def walk(name: str, n: int = 60_000) -> pd.DataFrame:
    """Our control: iid t(3) or GARCH(1,1) with t(4) shocks, 15m bars with wicks."""
    kind, i = name.split("_")
    rng = np.random.default_rng(SEED + 100 * int(i) + (0 if kind == "iid" else 50))
    if kind == "iid":
        sig = np.full(n, 0.001)
        z = rng.standard_t(3, n) / np.sqrt(3.0)
    else:
        z = rng.standard_t(4, n) / np.sqrt(2.0)
        sig = np.empty(n)
        omega, alpha, beta = 0.001**2 * 0.02, 0.08, 0.90
        v = 0.001**2
        for t in range(n):
            sig[t] = math.sqrt(v)
            v = omega + alpha * (sig[t] * z[t]) ** 2 + beta * v
    r = sig * z
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.r_[100.0, close[:-1]]
    wick = np.abs(rng.standard_normal((n, 2))) * (sig * 0.5)[:, None]
    return pd.DataFrame({
        "ts": (START + 900 * np.arange(n)).astype(np.int64), "open": open_, "close": close,
        "high": np.maximum(open_, close) * np.exp(wick[:, 0]),
        "low": np.minimum(open_, close) * np.exp(-wick[:, 1]),
    })


def load(sym: str) -> pd.DataFrame:
    if FAMILY == "walks":
        df = walk(sym)
    else:
        import spikerisk

        df = spikerisk.load(None, sym, "SEQLAB", "15m")
        df = df[df["ts"] >= START].reset_index(drop=True)
    return df.iloc[:BARS] if BARS else df


def frame(df: pd.DataFrame) -> pd.DataFrame:
    """Bar shape in volatility units, and the hand-built symbol."""
    lo, lh, ll, lc = (np.log(df[k].to_numpy(float)) for k in ("open", "high", "low", "close"))
    pc = np.r_[lc[0], lc[:-1]]
    tr = np.maximum.reduce([lh - ll, np.abs(lh - pc), np.abs(ll - pc)])
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().shift(1).to_numpy()
    r = (lc - pc) / sig
    trn = tr / sig
    rng = np.maximum(lh - ll, 1e-12)
    body = np.abs(lc - lo) / rng
    uw = (lh - np.maximum(lo, lc)) / rng
    lw = (np.minimum(lo, lc) - ll) / rng
    trp = pd.Series(trn).rolling(500, min_periods=200).rank(pct=True).to_numpy()
    hh = pd.Series(lh).rolling(20).max().shift(1).to_numpy()
    lw20 = pd.Series(ll).rolling(20).min().shift(1).to_numpy()
    hh100 = pd.Series(lh).rolling(100).max().shift(1).to_numpy()
    ll100 = pd.Series(ll).rolling(100).min().shift(1).to_numpy()
    lvol = np.log(sig / pd.Series(sig).rolling(500, min_periods=200).mean().to_numpy())
    sym = np.full(len(r), HAND.index("x"))
    up = r >= 0
    sym[up] = HAND.index("u")
    sym[~up] = HAND.index("d")
    sym[trp > 0.8] = np.where(up[trp > 0.8], HAND.index("Eu"), HAND.index("Ed"))
    sym[trp < 0.2] = HAND.index("C")
    disp = (np.abs(r) > 2) & (body > 0.6)
    sym[disp] = np.where(up[disp], HAND.index("Du"), HAND.index("Dd"))
    sym[lc < lw20] = HAND.index("Bd")
    sym[lc > hh] = HAND.index("Bu")
    sym[(ll < lw20) & (lc >= lw20)] = HAND.index("Sd")
    sym[(lh > hh) & (lc <= hh)] = HAND.index("Su")
    d = pd.DataFrame({
        "ts": df["ts"].to_numpy(), "r": r, "trn": trn, "body": body, "uw": uw, "lw": lw, "trp": trp,
        "lvol": lvol, "hand": sym, "pos100": (lc - ll100) / np.maximum(hh100 - ll100, 1e-12),
        "width100": (hh100 - ll100) / sig, "dist_hi": (hh100 - lc) / sig, "dist_lo": (lc - ll100) / sig,
    })
    d["big"] = (np.abs(d["r"]) > 3).astype(float)
    d["since_big"] = d.groupby(d["big"].cumsum()).cumcount()
    d["yabs"] = d["r"].abs().shift(-1)
    d["y5"] = pd.Series(lc).shift(-5).to_numpy() - lc
    d = d.replace([np.inf, -np.inf], np.nan)
    return d.dropna(subset=["r", "trp", "lvol", "width100"]).reset_index(drop=True)


# ------------------------------------------------------------------------------------ helpers

def day_boot(values: np.ndarray, ts: np.ndarray, n: int = 300) -> tuple[float, float, float]:
    """Mean and 95% CI of per-bar values, resampling whole days."""
    ok = np.isfinite(values)
    values, days = values[ok], (ts[ok] // 86_400).astype(np.int64)
    if len(values) < 10:
        return float("nan"), float("nan"), float("nan")
    uniq, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=values)
    cnts = np.bincount(inv).astype(float)
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(n):
        pick = rng.integers(0, len(uniq), len(uniq))
        draws.append(sums[pick].sum() / cnts[pick].sum())
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return float(values.mean()), float(lo), float(hi)


def entropy(counts: np.ndarray) -> float:
    p = counts[counts > 0] / counts.sum()
    return float(-(p * np.log2(p)).sum())


def mutual_info(s: np.ndarray, y: np.ndarray) -> float:
    ok = (s >= 0) & (y >= 0)
    s, y = s[ok], y[ok]
    joint = Counter(zip(s.tolist(), y.tolist(), strict=True))
    ys = Counter(y.tolist())
    h_y = entropy(np.array(list(ys.values()), float))
    h_y_given_s = 0.0
    for sv, n_s in Counter(s.tolist()).items():
        row = np.array([joint.get((sv, yv), 0) for yv in ys], float)
        h_y_given_s += n_s / len(s) * entropy(row)
    return h_y - h_y_given_s


def markov_logloss(train: np.ndarray, test: np.ndarray, size: int, order: int,
                   lower: np.ndarray | None) -> np.ndarray:
    """Per-symbol log-loss (bits) on `test` under an order-k Markov model fitted on `train`,
    add-1/2 smoothed, backing off to `lower` (the order k-1 probabilities) on unseen contexts."""
    def keys(seq):
        ctx = np.zeros(len(seq) - order, dtype=np.int64)
        for j in range(order):
            ctx = ctx * size + seq[j:len(seq) - order + j]
        return ctx, seq[order:]
    tc, tn = keys(train)
    ec, en = keys(test)
    pair = np.unique(tc * size + tn, return_counts=True)
    ctx = np.unique(tc, return_counts=True)
    def lookup(table, q):
        i = np.searchsorted(table[0], q)
        i = np.minimum(i, len(table[0]) - 1)
        return np.where(table[0][i] == q, table[1][i], 0)
    n_pair = lookup(pair, ec * size + en)
    n_ctx = lookup(ctx, ec)
    p = (n_pair + 0.5) / (n_ctx + 0.5 * size)
    if lower is not None:
        p = np.where(n_ctx > 0, p, lower[-len(p):])
    return -np.log2(p)


def orders(train: np.ndarray, test: np.ndarray, size: int, top: int = 6) -> list[np.ndarray]:
    """Per-symbol log-loss at orders 0..top, each aligned to the test positions >= top."""
    out, lower = [], None
    for k in range(top + 1):
        ll = markov_logloss(train, test, size, k, None if lower is None else 2.0 ** -lower)
        out.append(ll)
        lower = ll
    n = len(test) - top
    return [x[-n:] for x in out]


def lz78(seq: np.ndarray) -> int:
    seen, w, phrases = set(), "", 0
    for s in seq.tolist():
        w = w + chr(48 + int(s))
        if w not in seen:
            seen.add(w)
            phrases += 1
            w = ""
    return phrases + (1 if w else 0)


def repair(seq: list[int], cap: int = 800) -> int:
    """Re-Pair grammar size: 2 per rule plus the final sequence length."""
    seq, nxt, rules = list(seq), max(seq) + 1, 0
    for _ in range(cap):
        pairs = Counter(zip(seq, seq[1:], strict=False))
        if not pairs:
            break
        (a, b), n = pairs.most_common(1)[0]
        if n < 4:
            break
        out, i = [], 0
        while i < len(seq):
            if i + 1 < len(seq) and seq[i] == a and seq[i + 1] == b:
                out.append(nxt)
                i += 2
            else:
                out.append(seq[i])
                i += 1
        seq, nxt, rules = out, nxt + 1, rules + 1
    return len(seq) + 2 * rules


def expected_max(n: float) -> float:
    from statistics import NormalDist

    g, nd = 0.5772156649, NormalDist()
    return (1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e))


# ------------------------------------------------------------------------------------ the study

def main() -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.mixture import GaussianMixture

    frames = {}
    for sym in FAMILIES[FAMILY]:
        try:
            frames[sym] = (load(sym), None)
        except (ValueError, FileNotFoundError) as exc:
            print(f"  skip {sym}: {str(exc)[:60]}", flush=True)
    frames = {s: (df, frame(df)) for s, (df, _) in frames.items()}
    print(f"GRAMMAR · {FAMILY} · {len(frames)} series · 15m", flush=True)
    for s, (_, d) in frames.items():
        d["cut"] = d["ts"] < d["ts"].quantile(0.6)
        print(f"  {s}: {len(d):,} bars", flush=True)

    # --- 1. the learned alphabet, k by BIC
    shape = ["r", "trn", "body", "uw", "lw"]
    def feats(d):
        x = d[shape].to_numpy(float).copy()
        x[:, 0] = np.clip(x[:, 0], -6, 6)
        x[:, 1] = np.log(np.clip(x[:, 1], 1e-3, None))
        return x
    train_x = np.vstack([feats(d[d["cut"]]) for _, d in frames.values()])
    mu, sd = train_x.mean(0), train_x.std(0) + 1e-9
    sample = train_x[np.random.default_rng(SEED).choice(len(train_x), min(60_000, len(train_x)), replace=False)]
    sample = (sample - mu) / sd
    bics = {}
    for k in (3, 4, 6, 8, 12, 16, 24, 32):
        gm = GaussianMixture(k, covariance_type="full", random_state=SEED, max_iter=200).fit(sample)
        bics[k] = gm.bic(sample)
    k_best = min(bics, key=bics.get)
    gm = GaussianMixture(k_best, covariance_type="full", random_state=SEED, max_iter=300).fit(sample)
    for _, d in frames.values():
        d["learned"] = gm.predict((feats(d) - mu) / sd)
    print("\n1. ALPHABETS")
    print(f"  learned: BIC by k {', '.join(f'{k}:{v:,.0f}' for k, v in bics.items())} -> k = {k_best}")
    for name, size in (("hand", len(HAND)), ("learned", k_best)):
        mis = []
        for _, d in frames.values():
            t = d[~d["cut"]].dropna(subset=["yabs"])
            q = np.quantile(d.loc[d["cut"], "yabs"].dropna(), [0.2, 0.4, 0.6, 0.8])
            y = np.searchsorted(q, t["yabs"].to_numpy())
            mis.append(mutual_info(t[name].to_numpy(), y))
        used = np.unique(np.concatenate([d[name].to_numpy() for _, d in frames.values()])).size
        print(f"  {name:8s} size {size:2d} (used {used:2d}) | I(symbol; next |r| quintile) "
              f"{np.mean(mis):.4f} bits (series {min(mis):.4f}-{max(mis):.4f}) of H = {math.log2(5):.3f}")

    # --- 2. grammar
    print("\n2. GRAMMAR (test block; gain = order-0 log-loss minus the best order's, bits/symbol)")
    for name, size in (("hand", len(HAND)), ("learned", k_best)):
        for s, (_, d) in frames.items():
            tr, te = d.loc[d["cut"], name].to_numpy(), d.loc[~d["cut"], name].to_numpy()
            lls = orders(tr, te, size, 6)
            means = [x.mean() for x in lls]
            best = int(np.argmin(means))
            ts = d.loc[~d["cut"], "ts"].to_numpy()[-len(lls[0]):]
            g, lo, hi = day_boot(lls[0] - lls[best], ts)
            n = min(20_000, len(te))
            rng = np.random.default_rng(SEED)
            shuf = te[:n].copy()
            lz_sh = np.mean([lz78(rng.permutation(shuf)) for _ in range(3)])
            lz = lz78(te[:n]) / lz_sh
            m = min(8_000, len(te))
            rp = repair(te[:m].tolist()) / repair(rng.permutation(te[:m]).tolist())
            print(f"  {name:8s} {s:22s} order0 {means[0]:.3f} best order {best} {means[best]:.3f} | "
                  f"gain {g:+.4f} [{lo:+.4f}, {hi:+.4f}] | LZ78/shuffle {lz:.3f} | Re-Pair/shuffle {rp:.3f}",
                  flush=True)

    # --- 3. stratigraphy and inheritance
    print("\n3. INHERITANCE (next |r| quintile; log-loss gain of deep layers over shallow, bits/bar)")
    def layered(d):
        h = pd.get_dummies(d["hand"]).reindex(columns=range(len(HAND)), fill_value=0).astype(float)
        c20 = h.rolling(20, min_periods=1).sum().add_prefix("c20_")
        c100 = h.rolling(100, min_periods=1).sum().add_prefix("c100_")
        out = pd.DataFrame({"sym": d["hand"], "prev": d["hand"].shift(1).fillna(-1), "lvol": d["lvol"],
                            "trp": d["trp"]})
        deep = pd.concat([c20, c100, d[["since_big", "pos100", "width100", "dist_hi", "dist_lo"]]], axis=1)
        return out, pd.concat([out, deep], axis=1)
    rows = []
    for _, d in frames.values():
        q = np.quantile(d.loc[d["cut"], "yabs"].dropna(), [0.2, 0.4, 0.6, 0.8])
        dd = d.dropna(subset=["yabs"])
        sh, dp = layered(dd)
        rows.append((sh, dp, np.searchsorted(q, dd["yabs"].to_numpy()), dd["cut"].to_numpy(), dd["ts"].to_numpy()))
    sh = pd.concat([r[0] for r in rows]); dp = pd.concat([r[1] for r in rows])
    y = np.concatenate([r[2] for r in rows]); cut = np.concatenate([r[3] for r in rows])
    ts = np.concatenate([r[4] for r in rows])
    def fit_ll(x):
        m = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_depth=5,
                                           random_state=SEED).fit(x[cut], y[cut])
        p = m.predict_proba(x[~cut])
        return -np.log2(np.clip(p[np.arange((~cut).sum()), y[~cut]], 1e-9, 1))
    ll_sh, ll_dp = fit_ll(sh.to_numpy(float)), fit_ll(dp.to_numpy(float))
    g, lo, hi = day_boot(ll_sh - ll_dp, ts[~cut])
    half = ts[~cut] < np.quantile(ts[~cut], 0.5)
    g1 = (ll_sh - ll_dp)[half].mean(); g2 = (ll_sh - ll_dp)[~half].mean()
    print(f"  shallow {ll_sh.mean():.4f} | deep {ll_dp.mean():.4f} | gain {g:+.4f} [{lo:+.4f}, {hi:+.4f}]"
          f" halves {g1:+.4f} / {g2:+.4f}", flush=True)

    # --- 4. motifs -> transitions
    print("\n4. MOTIFS -> TRANSITIONS (production shock features and label)")
    from till_infinity.models import shocks_train as st
    from till_infinity.prices.models import Bar

    def bars_of(df):
        return [Bar(int(t), float(o), float(h), float(lo), float(c)) for t, o, h, lo, c in
                zip(df["ts"], df["open"], df["high"], df["low"], df["close"], strict=True)]
    series = {(s, "15m"): bars_of(df) for s, (df, _) in frames.items()}
    ds = st.dataset(series)
    when, _, xs, ys = ds.arrays()
    keys = np.array([k.split("|")[0] for k in ds.key])
    base = pd.DataFrame(xs, columns=[f"f{i}" for i in range(xs.shape[1])])
    base["sym"], base["close_ts"], base["y"] = keys, when, ys
    motif_rows = []
    grams_hand = Counter(); grams_learned = Counter()
    for s, (_, d) in frames.items():
        tr = d[d["cut"]]
        grams_hand.update(zip(tr["hand"].shift(2), tr["hand"].shift(1), tr["hand"], strict=True))
        grams_learned.update(zip(tr["learned"].shift(2), tr["learned"].shift(1), tr["learned"], strict=True))
    top_h = [g for g, _ in grams_hand.most_common(33) if not any(pd.isna(v) for v in g)][:30]
    top_l = [g for g, _ in grams_learned.most_common(33) if not any(pd.isna(v) for v in g)][:30]
    for s, (_, d) in frames.items():
        g3h = list(zip(d["hand"].shift(2), d["hand"].shift(1), d["hand"], strict=True))
        g3l = list(zip(d["learned"].shift(2), d["learned"].shift(1), d["learned"], strict=True))
        m = pd.DataFrame({"sym": s, "close_ts": d["ts"].to_numpy() + 900, "ts": d["ts"].to_numpy(),
                          "lvol": d["lvol"].to_numpy(), "y5": d["y5"].to_numpy(), "cut": d["cut"].to_numpy()})
        for i, g in enumerate(top_h):
            m[f"h{i}"] = [1.0 if x == g else 0.0 for x in g3h]
        for i, g in enumerate(top_l):
            m[f"l{i}"] = [1.0 if x == g else 0.0 for x in g3l]
        tr_seq, all_seq = d.loc[d["cut"], "hand"].to_numpy(), d["hand"].to_numpy()
        ll3 = markov_logloss(tr_seq, all_seq, len(HAND), 3, None)
        m["surprise"] = np.r_[np.full(3, np.nan), ll3]
        motif_rows.append(m)
    mt = pd.concat(motif_rows)
    j = base.merge(mt, on=["sym", "close_ts"], how="inner").dropna(subset=["lvol"])
    fcols = [c for c in base.columns if c.startswith("f")]
    mcols = [c for c in mt.columns if c[0] in "hl" and c[1:].isdigit()] + ["surprise"]
    cutj = j["cut"].to_numpy()

    def auc_gain(target, rows_mask, cols_a, cols_b, label):
        jj = j[rows_mask].dropna(subset=[target])
        c = jj["cut"].to_numpy(); yy = jj[target].to_numpy().astype(int)
        if yy[c].min() == yy[c].max() or yy[~c].min() == yy[~c].max():
            print(f"  {label}: one class only, skipped"); return
        def fit(cols):
            m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_depth=4,
                                               random_state=SEED).fit(jj.loc[c, cols].to_numpy(float), yy[c])
            return m.predict_proba(jj.loc[~c, cols].to_numpy(float))[:, 1]
        pa, pb = fit(cols_a), fit(cols_b) if cols_b else None
        yt, tt = yy[~c], jj.loc[~c, "ts"].to_numpy()
        a = roc_auc_score(yt, pa)
        if pb is None:
            print(f"  {label}: AUC {a:.4f} (n {len(yt):,}, rate {yt.mean():.3f})", flush=True); return
        b = roc_auc_score(yt, pb)
        days = (tt // 86_400).astype(np.int64); uniq = np.unique(days)
        idx = {u: np.flatnonzero(days == u) for u in uniq}
        rng = np.random.default_rng(SEED); diffs = []
        for _ in range(60):
            pick = np.concatenate([idx[u] for u in rng.choice(uniq, len(uniq))])
            if yt[pick].min() == yt[pick].max():
                continue
            diffs.append(roc_auc_score(yt[pick], pb[pick]) - roc_auc_score(yt[pick], pa[pick]))
        half = tt < np.quantile(tt, 0.5)
        h1 = roc_auc_score(yt[half], pb[half]) - roc_auc_score(yt[half], pa[half])
        h2 = roc_auc_score(yt[~half], pb[~half]) - roc_auc_score(yt[~half], pa[~half])
        lo, hi = np.quantile(diffs, [0.025, 0.975])
        print(f"  {label}: shock features {a:.4f} -> + motifs {b:.4f} | gain {b - a:+.4f} [{lo:+.4f}, {hi:+.4f}]"
              f" halves {h1:+.4f} / {h2:+.4f} (n {len(yt):,}, rate {yt.mean():.3f})", flush=True)

    j["shock"] = j["y"]
    auc_gain("shock", np.ones(len(j), bool), fcols, fcols + mcols, "shock within 4 bars")
    lq = np.nanquantile(j.loc[cutj, "lvol"], [1 / 3, 2 / 3])
    fut = []
    for s in j["sym"].unique():
        m = j["sym"] == s
        lv = j.loc[m, "lvol"].to_numpy()
        ahead = pd.Series(lv[::-1]).rolling(20, min_periods=1).max().to_numpy()[::-1]
        ahead = np.r_[ahead[1:], np.nan]
        fut.append(pd.Series(ahead, index=j.index[m]))
    j["ahead_max"] = pd.concat(fut).reindex(j.index)
    j["regime"] = np.where(j["ahead_max"].isna(), np.nan, (j["ahead_max"] > lq[1]).astype(float))
    auc_gain("regime", (j["lvol"] < lq[0]).to_numpy(), fcols, fcols + mcols, "vol regime low -> high within 20")
    j["dir"] = np.where(j["y5"].isna(), np.nan, (j["y5"] > 0).astype(float))
    auc_gain("dir", np.ones(len(j), bool), mcols, None, "direction, next 5 bars, motifs alone")

    # univariate motif lifts, BH and deflation
    te = j[~cutj]
    base_rate = te["shock"].mean()
    zs = []
    for i, g in enumerate(top_h):
        mm = te[f"h{i}"] == 1
        n1 = mm.sum()
        if n1 < 50:
            continue
        p1 = te.loc[mm, "shock"].mean()
        se = math.sqrt(base_rate * (1 - base_rate) * (1 / n1 + 1 / len(te)))
        zs.append((abs((p1 - base_rate) / se), g, p1, n1))
    zs.sort(reverse=True)
    from scipy.stats import norm

    pv = np.array([2 * (1 - norm.cdf(z)) for z, *_ in zs])
    order = np.argsort(pv); m = len(pv)
    bh = np.zeros(m, bool)
    for rank, k in enumerate(order, 1):
        if pv[k] <= 0.05 * rank / m:
            bh[order[:rank]] = True
    ntrials = 2 * 30 * 3  # motifs x alphabets x targets
    print(f"\n  univariate hand motifs vs the shock base rate {base_rate:.3f}: {bh.sum()} of {m} pass BH;"
          f" max |z| {zs[0][0]:.2f} against E[max] {expected_max(ntrials):.2f} over {ntrials} trials")
    for z, g, p1, n1 in zs[:6]:
        print(f"    {'>'.join(HAND[int(v)] for v in g):14s} n {n1:6,} shock rate {p1:.3f} z {z:5.2f}")


if __name__ == "__main__":
    main()
