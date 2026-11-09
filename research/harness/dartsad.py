"""The floor under the darts anomaly-detection study: geometry, de-overlap, transitions, nulls.

A library, not a run. The invocation lives in
[`dartsad_run.py`](dartsad_run.py)'s docstring and the launcher is
`dartsad_lab.sh`; `tests/test_dartsad.py` is what pins everything here.

Nothing in this file imports `darts`. The scorers live in `dartsad_run.py` and
need a separate venv (`u8darts` pulls its own numpy and pandas major versions);
this file is plain numpy so the suite can exercise the arithmetic that the
result actually rests on - the de-overlap stride, the transition counts, the
barrier race and the planted regime - in the repo's own environment.

## What is assumed, with the number attached

* **`base` and `mrng` are shifted by one bar.** The scale a bar is divided by is
  measured on bars strictly before it. Without the shift a bar's own return is
  inside its own denominator, and the scaled series stops being causal.
* **A window score is stamped at the window's last bar.** darts returns
  `n - window + 1` values for a `window`-bar scorer; this file aligns them to
  the original index at `window - 1 ..  n - 1`. See
  `dartsad_run.SCORE_SPECS` for why `window_agg=False` is not optional: the
  darts default spreads each window's score across every bar the window
  touches, which raised the score **four bars before** a planted spike in a
  40-bar probe.
* **One observation per disjoint window.** `deoverlap` steps by the scorer's
  window, so two consecutive observations share no bar. A transition matrix
  built on stride-1 window scores counts the same bars up to `window` times and
  reports the overlap as persistence.
* **The scale is gold's, not one.** `plant` builds its bars at a price near
  2,000 because relative standard deviation and price offset coincide at 1.0
  and a scale bug is invisible there.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Trailing window for the scale every scaled feature is divided by, and for
#: the anomaly labels' own denominator. `anomalies.py`'s 500 bars, kept so the
#: labels here are the labels that file measured.
LONG = 500

#: Scaled features are clipped to this many trailing mean absolute returns.
#: `fractal_twins.bars` uses the same bound; a 4x label is well inside it, and
#: the clip stops one 30-sigma bar from owning a k-means centroid.
CLIP = 10.0

#: Deciles of the incumbent volatility percentile. The standing rule from
#: `candle-screen.md`: an AUC of 0.8052 on a constant-volatility generator fell
#: to 0.5250 inside these, so the within-strata column is the only one that
#: carries a claim about anything other than volatility.
STRATA = 10


def rolling_mean(x: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    return pd.Series(x).rolling(window, min_periods=min_periods).mean().to_numpy()


def log_level(tr: np.ndarray) -> np.ndarray:
    """log of the 14-bar EWMA of true range: the volatility LEVEL, not a ratio.

    One definition with two callers - `geometry`, and `dartsad_run`'s report,
    which rebuilds it from the stored true range rather than from a second copy
    of this arithmetic. Both incumbents (`lvol`, `trpct`) are scale-free, so a
    forward-log-variance baseline without this column read an out-of-sample R2
    of 0.0221 on EURUSD and would have made any delta a delta against nothing.
    """
    return np.log(pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy() + 1e-12)


def clv_corr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> float:
    """`spikerisk.leak_check`'s own statistic: close location against the NEXT return.

    It refuses a series above 0.15, because a bar whose fields are misaligned
    makes every model built on it look like a 94% winner. Returned rather than
    raised on, so a series can be reported instead of only rejected: the three
    `Drift Switch` indices read +0.136, +0.154 and +0.136 here against -0.012
    to -0.030 on EURUSD, GBPUSD, USDJPY, XAUUSD and BTCUSD, and that is the
    planted drift being visible rather than a defect.
    """
    lc, hi, lo = np.log(close), np.log(high), np.log(low)
    width = np.where(hi - lo > 0, hi - lo, np.nan)
    clv = ((lc - lo) - (hi - lc)) / width
    nxt = np.r_[np.diff(lc), np.nan]
    good = np.isfinite(clv) & np.isfinite(nxt)
    if good.sum() < 300:
        return float("nan")
    return float(np.corrcoef(clv[good], nxt[good])[0, 1])


def geometry(
    o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, long: int = LONG
) -> dict[str, np.ndarray]:
    """Causal bar geometry and the incumbent volatility readings, in log price.

    `lvol` and `trpct` are `anomalies.py`'s two incumbents verbatim - the
    14-bar EWMA of true range over its 500-bar mean, and that EWMA's percentile
    in 1,500 bars - because the claim under test is whether an anomaly score
    adds to them, and a re-derived incumbent would make the comparison about
    the derivation.

    `llevel` is the log of that EWMA and is **not** one of them. It is here
    because both incumbents are scale-free - a ratio and a percentile - so a
    baseline built from them alone cannot predict the *level* of forward log
    variance at all: it read an out-of-sample R2 of 0.0221 on EURUSD against
    0.4 or more with the level included. A delta measured against the
    scale-free pair would be a delta against a straw man.
    """
    lo_, hi_, c_, o_ = np.log(lo), np.log(h), np.log(c), np.log(o)
    n = len(c_)
    r = np.diff(c_, prepend=np.nan)
    prev = np.r_[np.nan, c_[:-1]]
    rng = hi_ - lo_
    tr = np.nanmax(np.column_stack([rng, np.abs(hi_ - prev), np.abs(lo_ - prev)]), axis=1)
    shifted_abs = pd.Series(np.abs(r)).shift(1)
    base = shifted_abs.rolling(long, min_periods=long // 2).mean().to_numpy()
    mrng = pd.Series(rng).shift(1).rolling(long, min_periods=long // 2).mean().to_numpy()
    ew = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    width = np.where(rng > 0, rng, np.nan)
    return {
        "r": r,
        "rng": rng,
        "tr": tr,
        "open_gap": o_ - prev,
        "clv": np.nan_to_num(((c_ - lo_) - (hi_ - c_)) / width, nan=0.0),
        "base": base,
        "mrng": mrng,
        "llevel": log_level(tr),
        "lvol": np.log(ew / pd.Series(tr).rolling(long, min_periods=long // 2).mean()).to_numpy(),
        "trpct": ew.rolling(1500, min_periods=300).rank(pct=True).to_numpy(),
        "volvol": pd.Series(np.log(tr + 1e-12)).rolling(50).std().to_numpy(),
        "n": np.arange(n),
    }


def scaled_features(g: dict[str, np.ndarray]) -> np.ndarray:
    """Bar shape with the volatility level divided out: (n, 3).

    The point of the arm. A scorer fed raw returns is a volatility detector by
    construction - `raw_features` is kept so that can be shown rather than
    asserted - and this arm removes the level so anything the scorer finds is
    about the *shape* of a bar relative to the recent scale.
    """
    cols = np.column_stack(
        [g["r"] / g["base"], g["rng"] / g["mrng"], g["clv"]],
    )
    return np.clip(np.nan_to_num(cols, nan=0.0, posinf=CLIP, neginf=-CLIP), -CLIP, CLIP)


def raw_features(g: dict[str, np.ndarray]) -> np.ndarray:
    """Return and range in log price, undivided: (n, 2). The volatility arm."""
    cols = np.column_stack([g["r"], g["rng"]])
    return np.nan_to_num(cols, nan=0.0)


def labels(g: dict[str, np.ndarray], ahead: int = 4) -> dict[str, np.ndarray]:
    """`anomalies.py`'s shock and range labels, and the forward readings.

    A label is true at bar `t` if the anomaly happens in bars `t+1 .. t+ahead`,
    so every label is a function of bars strictly after the score's last bar.
    The tail `ahead` rows are set False and must be dropped by the caller.
    """
    n = len(g["r"])
    shock = np.abs(g["r"]) > 4 * g["base"]
    rng_blow = g["rng"] > 4 * g["mrng"]
    out: dict[str, np.ndarray] = {"is_shock": shock, "is_range": rng_blow}
    for name, flag in (("shock", shock), ("range", rng_blow)):
        fut = np.zeros(n, bool)
        for j in range(1, ahead + 1):
            fut |= np.r_[np.nan_to_num(flag[j:], nan=0).astype(bool), np.zeros(j, bool)]
        fut[n - ahead :] = False
        out[f"y_{name}"] = fut
    return out


def forward_logrv(g: dict[str, np.ndarray], ahead: int = 20) -> np.ndarray:
    """log of the mean squared return over bars `t+1 .. t+ahead`, else NaN.

    The regression target `statespace-anomaly.md` names as the frame still worth
    running: forecasting the *level* of log variance is where a better filter
    was worth +0.21 to +0.24 R2, while classifying a 4x bar was not.
    """
    r2 = np.square(g["r"])
    n = len(r2)
    out = np.full(n, np.nan)
    acc = pd.Series(r2).rolling(ahead, min_periods=ahead).mean().to_numpy()
    out[: n - ahead] = acc[ahead:]
    return np.log(np.where(out > 0, out, np.nan))


def deoverlap(n: int, window: int, start: int) -> np.ndarray:
    """Indices `start, start+window, ...` below `n`: one observation per disjoint window.

    The whole point of the file. A stride-1 window score shares `window - 1`
    bars with its neighbour, so a transition matrix over it reports the overlap
    as persistence: `overlapping-outcome-windows-leak` is the standing version
    of the same mistake, where a direction AUC of 0.79 collapsed to 0.51.
    """
    if window < 1:
        raise ValueError("window must be at least 1")
    return np.arange(max(start, 0), n, window)


def transition_counts(labels_: np.ndarray, k: int) -> np.ndarray:
    """k x k counts of consecutive pairs in an already de-overlapped label sequence."""
    a = np.asarray(labels_, dtype=int)
    if a.size < 2:
        return np.zeros((k, k), dtype=np.int64)
    flat = np.bincount(a[:-1] * k + a[1:], minlength=k * k)
    return flat.reshape(k, k)


def row_normalise(counts: np.ndarray) -> np.ndarray:
    rows = counts.sum(axis=1, keepdims=True)
    return np.divide(counts, rows, out=np.full(counts.shape, np.nan), where=rows > 0)


def stay_share(counts: np.ndarray) -> tuple[float, float]:
    """(observed share of pairs that stay, the share independence would give).

    The second number is why a raw persistence figure says nothing: a state
    holding 60% of the bars stays 60% of the time by arithmetic.
    """
    total = counts.sum()
    if total == 0:
        return float("nan"), float("nan")
    rows = counts.sum(axis=1)
    cols = counts.sum(axis=0)
    return float(np.trace(counts) / total), float((rows * cols).sum() / total**2)


def chi2_independence(counts: np.ndarray) -> float:
    """Pearson chi-square of the pair table against the product of its margins.

    Reported against a permutation null rather than a chi-square distribution,
    because the states are estimated from the same data and the asymptotic
    df is not (k-1)^2 once the clustering has been fitted.
    """
    total = counts.sum()
    if total == 0:
        return float("nan")
    rows = counts.sum(axis=1, keepdims=True)
    cols = counts.sum(axis=0, keepdims=True)
    expect = rows * cols / total
    good = expect > 0
    return float(np.sum((counts[good] - expect[good]) ** 2 / expect[good]))


def label_permutation_chi2(
    labels_: np.ndarray, k: int, draws: int, rng: np.random.Generator
) -> np.ndarray:
    """The chi-square a permuted label sequence gives: the marginals held exactly.

    This null answers "are consecutive de-overlapped states dependent", holding
    each state's share fixed. It cannot answer whether the *detector* invents
    dependence out of the bar marginals; `dartsad_run` scores a whole-bar
    shuffle through the same scorers for that.
    """
    a = np.asarray(labels_, dtype=int)
    out = np.empty(draws)
    for i in range(draws):
        out[i] = chi2_independence(transition_counts(rng.permutation(a), k))
    return out


def nmi(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised mutual information, 2I/(Ha+Hb), from a contingency table.

    Used to answer one question: are the score clusters volatility bins with
    new names? Read against the value the same clustering gives on a shuffled
    series, because NMI is biased upward by the number of cells.
    """
    a, b = np.asarray(a, int), np.asarray(b, int)
    keep = (a >= 0) & (b >= 0)
    a, b = a[keep], b[keep]
    if a.size == 0:
        return float("nan")
    ka, kb = a.max() + 1, b.max() + 1
    table = np.bincount(a * kb + b, minlength=ka * kb).reshape(ka, kb).astype(float)
    total = table.sum()
    pa = table.sum(axis=1) / total
    pb = table.sum(axis=0) / total
    p = table / total
    outer = np.outer(pa, pb)
    good = p > 0
    mi = float(np.sum(p[good] * np.log(p[good] / outer[good])))
    ha = -float(np.sum(pa[pa > 0] * np.log(pa[pa > 0])))
    hb = -float(np.sum(pb[pb > 0] * np.log(pb[pb > 0])))
    return 2 * mi / (ha + hb) if ha + hb > 0 else float("nan")


def ari(a: np.ndarray, b: np.ndarray) -> float:
    """Adjusted Rand index. The power curve's recovery measure against a planted state."""
    a, b = np.asarray(a, int), np.asarray(b, int)
    ka, kb = a.max() + 1, b.max() + 1
    table = np.bincount(a * kb + b, minlength=ka * kb).reshape(ka, kb).astype(float)
    pairs = lambda m: np.sum(m * (m - 1) / 2)  # noqa: E731
    index = pairs(table)
    ra, cb = pairs(table.sum(axis=1)), pairs(table.sum(axis=0))
    n = table.sum()
    expect = ra * cb / (n * (n - 1) / 2)
    most = (ra + cb) / 2
    return float((index - expect) / (most - expect)) if most != expect else 0.0


def auc(y: np.ndarray, score: np.ndarray) -> float:
    """Mann-Whitney AUC with ties at half, written here so the suite needs no sklearn."""
    y = np.asarray(y).astype(bool)
    score = np.asarray(score, dtype=float)
    keep = np.isfinite(score)
    y, score = y[keep], score[keep]
    pos, neg = int(y.sum()), int((~y).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    sorted_score = score[order]
    i = 0
    while i < len(sorted_score):
        j = i
        while j + 1 < len(sorted_score) and sorted_score[j + 1] == sorted_score[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * neg))


def strata_auc(
    y: np.ndarray, score: np.ndarray, strata: np.ndarray, bands: int = STRATA, least: int = 200
) -> float:
    """Size-weighted mean AUC inside `bands` quantiles of `strata`.

    `statespace_anomaly._within` with the same defaults, so the two studies'
    second columns are the same statistic.
    """
    good = np.isfinite(strata) & np.isfinite(score)
    if good.sum() < 1_000:
        return float("nan")
    edges = np.quantile(strata[good], np.linspace(0, 1, bands + 1)[1:-1])
    which = np.digitize(strata, edges)
    total = weight = 0.0
    for band in range(bands):
        keep = good & (which == band)
        if keep.sum() < least or len(np.unique(y[keep])) < 2:
            continue
        got = auc(y[keep], score[keep])
        if np.isfinite(got):
            total += got * keep.sum()
            weight += keep.sum()
    return total / weight if weight else float("nan")


def ols_r2(x_train, y_train, x_test, y_test) -> float:
    """Out-of-sample R2 of a ridge-stabilised least squares fit with an intercept.

    Ridge at 1e-6 of the trace, not for shrinkage but because the score columns
    are collinear enough that an exact solve is not reproducible across BLAS
    builds.
    """
    x_train, x_test = np.asarray(x_train, float), np.asarray(x_test, float)
    y_train, y_test = np.asarray(y_train, float), np.asarray(y_test, float)
    a = np.column_stack([np.ones(len(x_train)), x_train])
    b = np.column_stack([np.ones(len(x_test)), x_test])
    gram = a.T @ a
    gram = gram + np.eye(len(gram)) * 1e-6 * np.trace(gram) / len(gram)
    beta = np.linalg.solve(gram, a.T @ y_train)
    resid = y_test - b @ beta
    var = np.sum((y_test - y_train.mean()) ** 2)
    return float(1 - np.sum(resid**2) / var) if var > 0 else float("nan")


def race(
    high: np.ndarray,
    low: np.ndarray,
    open_: np.ndarray,
    close: np.ndarray,
    stop_px: np.ndarray,
    entries: np.ndarray,
    side: int,
    max_hold: int,
) -> tuple[np.ndarray, np.ndarray]:
    """One-at-a-time barrier race at reward-to-risk 1, in R. Returns (taken, R).

    Frozen: enter at the open of `t+1`, stop and target both `stop_px[t]` away,
    barriers read on the wicks with **the stop winning a tie**, exit at the
    close after `max_hold` bars otherwise. A candidate inside an open position
    is skipped, so no two observations share a bar - the de-overlap rule applied
    to outcomes rather than to features.

    The null is 0.5 of the races won, which is `1/(1+N)` at N = 1, so gross
    expectancy is zero before costs by arithmetic and not by measurement.
    """
    taken: list[int] = []
    got: list[float] = []
    busy_until = -1
    n = len(high)
    for t in entries:
        t = int(t)
        if t <= busy_until or t + 1 >= n:
            continue
        risk = float(stop_px[t])
        if not np.isfinite(risk) or risk <= 0:
            continue
        entry = float(open_[t + 1])
        stop = entry - side * risk
        target = entry + side * risk
        end = min(t + max_hold, n - 1)
        out = None
        for j in range(t + 1, end + 1):
            hit_stop = low[j] <= stop if side > 0 else high[j] >= stop
            hit_target = high[j] >= target if side > 0 else low[j] <= target
            if hit_stop:
                out, busy_until = -1.0, j
                break
            if hit_target:
                out, busy_until = 1.0, j
                break
        if out is None:
            out = side * (float(close[end]) - entry) / risk if end > t else 0.0
            busy_until = end
        taken.append(t)
        got.append(out)
    return np.asarray(taken, dtype=int), np.asarray(got, dtype=float)


def day_block_means(values: np.ndarray, blocks: np.ndarray, draws: int, rng) -> np.ndarray:
    """Bootstrap means resampling whole days.

    Regime labels persist for hours and trades cluster in days, so an ordinary
    standard error is far too narrow - which is the difference between a cell
    with a 90% interval clear of zero and one without.
    """
    values, blocks = np.asarray(values, float), np.asarray(blocks)
    if len(values) == 0:
        return np.array([])
    keys, inverse = np.unique(blocks, return_inverse=True)
    buckets = [values[inverse == i] for i in range(len(keys))]
    means = np.empty(draws)
    for d in range(draws):
        pick = rng.integers(0, len(buckets), len(buckets))
        means[d] = np.concatenate([buckets[i] for i in pick]).mean()
    return means


def day_block_ci(values: np.ndarray, blocks: np.ndarray, draws: int, rng, level=0.90):
    """(mean, low, high, two-sided p) from a day-block bootstrap."""
    means = day_block_means(values, blocks, draws, rng)
    if means.size == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    tail = (1 - level) / 2
    p = 2 * min(float((means <= 0).mean()), float((means >= 0).mean()))
    return (
        float(np.mean(values)),
        float(np.quantile(means, tail)),
        float(np.quantile(means, 1 - tail)),
        min(p, 1.0),
    )


def bh(pvalues: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg rejections. Picking the best of 43 instruments gives a winner."""
    p = np.asarray(pvalues, float)
    good = np.flatnonzero(np.isfinite(p))
    out = np.zeros(len(p), bool)
    if good.size == 0:
        return out
    order = good[np.argsort(p[good])]
    m = len(order)
    thresholds = q * np.arange(1, m + 1) / m
    passed = p[order] <= thresholds
    if passed.any():
        out[order[: np.flatnonzero(passed).max() + 1]] = True
    return out


def plant(
    n: int,
    lam: float,
    p_stay: float,
    mu: float = 0.0,
    sigma: float = 5e-4,
    sub: int = 15,
    price: float = 2000.0,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """A two-state planted regime as OHLC bars: (o, h, l, c, state).

    State 1 has `lam` times the volatility and `mu` times sigma of drift per
    bar; the chain stays in its state with probability `p_stay`. Each bar is
    built from `sub` sub-steps so the high and low are extremes of a real path
    rather than a formula, which is what a range-based estimator reads.

    Priced near 2,000 rather than 1.0 on purpose: at a price of one, a relative
    standard deviation and a price offset are the same number and a scale bug
    cannot be seen.
    """
    rng = np.random.default_rng(seed)
    flips = rng.random(n) > p_stay
    state = np.empty(n, dtype=int)
    s = 0
    for i in range(n):
        if flips[i]:
            s = 1 - s
        state[i] = s
    scale = np.where(state == 1, lam, 1.0) * sigma
    drift = np.where(state == 1, mu, 0.0) * sigma
    steps = rng.standard_normal((n, sub)) * (scale / np.sqrt(sub))[:, None] + (drift / sub)[:, None]
    walk = np.cumsum(steps, axis=1)
    opens = np.r_[0.0, np.cumsum(walk[:, -1])[:-1]]
    hi = opens + np.maximum(walk.max(axis=1), 0.0)
    lo = opens + np.minimum(walk.min(axis=1), 0.0)
    close = opens + walk[:, -1]
    return (
        price * np.exp(opens),
        price * np.exp(hi),
        price * np.exp(lo),
        price * np.exp(close),
        state,
    )


def tick_size(close: np.ndarray) -> float:
    """The quoted price grid, as the 1st percentile of gaps between distinct closes.

    The broker's `spread` column is in **points, not price**
    (EURUSD read a 476% round trip when it was taken as price, and the error
    reorders the book by cost), and the point is not in the bar file. The grid
    is, so it is measured.

    **The percentile, not the median, and not the minimum.** On an instrument
    whose typical move is far larger than its grid, consecutive *distinct*
    closes are a move apart rather than a tick apart, so the median gap reads
    the move: BTCUSD came back at 0.601 against a true grid of 0.01, which put
    its round trip at 1,456 and its cost at 3.9R. The minimum is the other
    failure - one anomalous gap takes BTCUSD to 0.001. Measured over 60,000
    closes the 1st percentile recovers 1e-5 on EURUSD, 0.001 on USDJPY, 0.01 on
    XAUUSD, Jump 75 and Volatility 75, 0.1 on Step Index, and 0.009 on BTCUSD
    against a true 0.01 - so a cost read this way is good to about 10%.
    """
    uniq = np.unique(np.asarray(close, float))
    if len(uniq) < 300:
        return float("nan")
    gaps = np.diff(uniq)
    gaps = gaps[gaps > 0]
    return float(np.quantile(gaps, 0.01)) if len(gaps) else float("nan")
