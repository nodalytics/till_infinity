"""High dispersion as a decision: precision, recall, F1, accuracy - and the base rate.

Asked on 2026-10-17: "we need high volatility precision, accuracy, f1 score,
recall and other metrics", after `dispersion-forecast.md` measured the
regression side at R2 +0.54 to +0.83. A gate is a classification, not a
regression, so these are the right metrics for it - and two things have to be
on the page beside them or they cannot be read at all.

## The two traps, both already measured on this desk

**Accuracy is free on an imbalanced label.** If "high dispersion" is the top
10% of bars, a model that says *never* scores 90% accuracy and has no skill
whatsoever. So the **base rate** is printed beside every accuracy, and the
column that matters is lift over it rather than the level.

**AUC is nearly free on a volatility target.** `auc-is-free-on-volatility-targets`
is on record: **0.805 on a constant-sigma process**, where by construction
there is nothing to forecast, falling to **0.525 within strata** - and the
incumbent features alone read 0.74 to 0.78. Volatility is persistent, so
yesterday's level predicts today's class almost for free, and a model scored
against a flat null is being credited with persistence it did not discover.

The answer to both is the same: **stratify**. Every metric is reported twice -
pooled, and within bins of the incumbent reading - and only the second one can
support a claim. A number that survives the strata is a number about the
model; a number that only exists pooled is a number about volatility
clustering.

## Arms, labels and nulls

The label is *the next `h` bars' mean log-variance lands in the top `share` of
the **training** half's distribution*. Thresholds come from the training half
only, so the test half's own distribution is never consulted.

* `har` - the three-lag regression's prediction, used as a score.
* `lin48` - ridge on 48 lags, which beat the reservoir at 4h.
* `esn` - the reservoir, which beat everything at 1h.
* `last` - the previous bar's log-variance, the incumbent. **This is the arm to
  beat**, because it is what "volatility is persistent" looks like with no
  model at all.

Nulls: a **base-rate** predictor, **shuffled** labels, and the
**constant-sigma synthetics** where every metric must collapse to the base
rate.

Every score is thresholded at the quantile that reproduces the label's own
prevalence, so precision and recall are comparable across arms rather than
each one choosing its own operating point. The threshold sweep is printed too,
because a single operating point hides the trade.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from dispersion_ml import SIZE, _design, _reservoir, _ridge, onescale, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

FRAMES = ("1h", "4h")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 8
LIMIT = 12000
HORIZONS = (5, 20)
#: What counts as high dispersion, as a share of the training distribution.
#: Two, because the base-rate trap is worst at the rarer one.
SHARES = (0.20, 0.10)
#: Bins of the incumbent reading. Metrics within these are the only ones that
#: can support a claim; pooled ones mostly restate persistence.
STRATA = 5
RIDGES = (1e-6, 1e-4, 1e-2, 1.0, 100.0)
SEED = 20261017


def _metrics(truth: np.ndarray, called: np.ndarray) -> dict[str, float]:
    """Accuracy, precision, recall and F1, with the base rate beside them."""
    hit = float(np.sum(called & truth))
    missed = float(np.sum(~called & truth))
    wrong = float(np.sum(called & ~truth))
    right = float(np.sum(~called & ~truth))
    total = hit + missed + wrong + right
    base = (hit + missed) / total if total else float("nan")
    precision = hit / (hit + wrong) if hit + wrong else float("nan")
    recall = hit / (hit + missed) if hit + missed else float("nan")
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall and not math.isnan(precision) and not math.isnan(recall)
        else float("nan")
    )
    return {
        "accuracy": (hit + right) / total if total else float("nan"),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "base": base,
        # What a base-rate guesser would score: always calling the majority
        # class. Printed because accuracy without it is unreadable.
        "accuracy base": max(base, 1.0 - base) if total else float("nan"),
        # Precision over prevalence: 1.0 is no better than calling at random.
        "lift": precision / base if base > 0 and not math.isnan(precision) else float("nan"),
    }


def _auc(truth: np.ndarray, score: np.ndarray) -> float:
    """Rank AUC, ties averaged."""
    order = np.argsort(score)
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = np.arange(1, len(score) + 1, dtype=float)
    # Average the ranks of ties, so a constant score reads exactly 0.5.
    values = score[order]
    start = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or values[i] != values[start]:
            if i - start > 1:
                ranks[order[start:i]] = (start + i + 1) / 2.0
            start = i
    positive = truth.sum()
    negative = len(truth) - positive
    if not positive or not negative:
        return float("nan")
    return float((ranks[truth].sum() - positive * (positive + 1) / 2.0) / (positive * negative))


def _tuned(x: np.ndarray, y: np.ndarray, cut: int) -> np.ndarray:
    """Ridge on the training half, penalty chosen inside it; returns test scores."""
    best, pick = -math.inf, RIDGES[0]
    inner = max(cut // 2, 1)
    for lam in RIDGES:
        coef, _ = _ridge(x[:inner], y[:inner], lam)
        guess = coef[0] + x[inner:cut] @ coef[1:]
        err = float(np.sum((y[inner:cut] - guess) ** 2))
        if -err > best:
            best, pick = -err, lam
    coef, _ = _ridge(x[:cut], y[:cut], pick)
    return coef[0] + x @ coef[1:]


def score(bars: dict[str, np.ndarray], horizon: int, share: float, rng, shuffle=False) -> dict:
    """Every arm as a classifier, pooled and within strata of the incumbent."""
    logvar = parkinson(bars["high"], bars["low"])
    good = np.isfinite(logvar)
    if good.sum() < 2000:
        return {}
    logvar = logvar[good]
    x, y, start = _design(logvar, horizon)
    if len(y) < 1000:
        return {}
    cut = len(y) // 2

    # The threshold comes from the training half alone.
    mark = float(np.quantile(y[:cut], 1.0 - share))
    truth = y > mark
    if shuffle:
        truth = truth[rng.permutation(len(truth))]

    scores: dict[str, np.ndarray] = {"last": x[:, 0], "har": _tuned(x, y.astype(float), cut)}
    deep = np.asarray(
        [[float(logvar[i - k]) for k in range(SIZE)] for i in range(start, start + len(y))],
        dtype=float,
    )
    scores["lin48"] = _tuned(deep, y.astype(float), cut)
    states = _reservoir(logvar, rng, start + cut)[start : start + len(y)]
    scores["esn"] = _tuned(np.hstack([x, states]), y.astype(float), cut)

    out: dict[str, dict[str, float]] = {}
    held = slice(cut, None)
    want = truth[held]
    # Strata of the incumbent, so persistence is held constant inside each bin.
    incumbent = x[held, 0]
    edges = np.quantile(incumbent, np.linspace(0.0, 1.0, STRATA + 1)[1:-1])
    bins = np.digitize(incumbent, edges)

    for arm, series in scores.items():
        got = series[held]
        # One operating point for every arm: the quantile that reproduces the
        # label's prevalence, so precision and recall are comparable.
        cutoff = float(np.quantile(got, 1.0 - share))
        pooled = _metrics(want, got > cutoff)
        pooled["auc"] = _auc(want, got)
        out[arm] = pooled

        # And again inside each stratum, with the operating point refitted per
        # bin so a bin is not called entirely one way by construction.
        inner: list[dict[str, float]] = []
        for b in range(STRATA):
            keep = bins == b
            if keep.sum() < 100 or want[keep].sum() < 10:
                continue
            local = float(np.quantile(got[keep], 1.0 - share))
            row = _metrics(want[keep], got[keep] > local)
            row["auc"] = _auc(want[keep], got[keep])
            inner.append(row)
        if inner:
            out[f"{arm} (strata)"] = {
                k: float(np.nanmean([row[k] for row in inner])) for k in inner[0]
            }
    return out


def main() -> None:
    print(
        "High dispersion as a decision. Every metric has its base rate beside\n"
        "it, because accuracy on a 10% label is 90% for a model that says\n"
        "never. `(strata)` holds the incumbent reading constant - and\n"
        "`auc-is-free-on-volatility-targets` says that is the only row that\n"
        "can support a claim: 0.805 pooled on a constant-sigma process against\n"
        "0.525 within strata.\n"
    )
    rng = np.random.default_rng(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)

    arms = ("last", "har", "lin48", "esn")
    for frame in FRAMES:
        for label in ("onescale", *TRADED, *CONTROLS):
            if label != "onescale" and label not in groups:
                continue
            for horizon in HORIZONS:
                for share in SHARES:
                    for shuffle in (False, True):
                        pooled: dict[str, list[dict[str, float]]] = {}
                        names = (
                            [f"onescale{k}" for k in range(PER_CLASS)]
                            if label == "onescale"
                            else sorted(groups[label])[:PER_CLASS]
                        )
                        for name in names:
                            bars = (
                                onescale(LIMIT, rng) if label == "onescale" else load(name, frame)
                            )
                            if bars is None:
                                continue
                            cut = {k: v[-LIMIT:] for k, v in bars.items()}
                            for arm, row in score(
                                cut, horizon, share, rng, shuffle=shuffle
                            ).items():
                                pooled.setdefault(arm, []).append(row)
                        if not pooled:
                            continue
                        tag = f"{label}, {frame}, h={horizon}, top {share:.0%}" + (
                            "  [SHUFFLED]" if shuffle else ""
                        )
                        print(f"\n=== {tag}")
                        print(
                            f"  {'arm':<16}{'acc':>7}{'accbase':>9}{'prec':>7}"
                            f"{'recall':>8}{'f1':>7}{'lift':>7}{'auc':>7}{'base':>7}"
                        )
                        for arm in arms:
                            for key in (arm, f"{arm} (strata)"):
                                rows = pooled.get(key)
                                if not rows:
                                    continue
                                m = {k: float(np.nanmedian([r[k] for r in rows])) for k in rows[0]}
                                print(
                                    f"  {key:<16}{m['accuracy']:>7.3f}{m['accuracy base']:>9.3f}"
                                    f"{m['precision']:>7.3f}{m['recall']:>8.3f}{m['f1']:>7.3f}"
                                    f"{m['lift']:>7.2f}{m['auc']:>7.3f}{m['base']:>7.3f}"
                                )


if __name__ == "__main__":
    main()
