"""Which features carry the signal, and can more be generated from them.

Run from the repository root:  python research/harness/features.py

Two questions, both open since edge.md §6 found that `Features.distance` does
not order neighbours by relevance and nobody has ever asked which features
belong in it.

  importance   drop one feature, measure what accuracy is lost. Model-agnostic
               and honest, unlike reading coefficients off a fitted model,
               which measures the model as much as the feature.
  generation   river can build features from features — pairwise products,
               random Fourier bases, target statistics per group. Does any of
               it beat the raw nine?

Walk-forward throughout: every touch is predicted before it is learned.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from river import compose, feature_extraction, linear_model, preprocessing, stats
from touches import FIELDS, load

WARM = 150
KEYS = (*FIELDS, "above")


def score(rows, build, keys=KEYS, name=""):
    """Walk-forward accuracy of a pipeline over the given feature keys."""
    model = build()
    hits = seen = 0
    start = time.perf_counter()
    for i, row in enumerate(rows):
        x = {k: row[0][k] for k in keys}
        if name == "with feed/interval":
            x["feed"], x["interval"] = row[2], row[3]
        said = model.predict_one(x)
        if said is not None and i >= WARM:
            seen += 1
            hits += said == row[1]
        model.learn_one(x, row[1])
    return (hits / seen if seen else 0.0), time.perf_counter() - start


def logistic():
    return preprocessing.StandardScaler() | linear_model.LogisticRegression()


def main() -> None:
    rows = load()
    print(f"touches: {len(rows):,}, {sum(1 for r in rows if r[1]) / len(rows):.1%} up")
    print("baseline model is logistic regression over the raw features\n")

    full, _ = score(rows, logistic)
    print(f"all {len(KEYS)} features: {full:.1%}\n")

    print("=== 1. importance, by what is lost when the feature is dropped")
    print(f"    {'feature':<16} {'without it':>11} {'cost':>8}")
    print("    " + "-" * 37)
    losses = []
    for drop in KEYS:
        kept = tuple(k for k in KEYS if k != drop)
        got, _ = score(rows, logistic, kept)
        losses.append((full - got, drop, got))
    for cost, drop, got in sorted(losses, reverse=True):
        print(f"    {drop:<16} {got:>10.1%} {100 * cost:>+7.1f}pp")

    print("\n=== 2. what one feature alone is worth")
    print(f"    {'feature':<16} {'alone':>11}")
    print("    " + "-" * 28)
    solo = []
    for only in KEYS:
        got, _ = score(rows, logistic, (only,))
        solo.append((got, only))
    for got, only in sorted(solo, reverse=True):
        print(f"    {only:<16} {got:>10.1%}")

    print("\n=== 3. generated features")
    print(f"    {'pipeline':<34} {'right':>8} {'seconds':>9}")
    print("    " + "-" * 53)
    variants = {
        "raw (baseline)": logistic,
        "+ pairwise products (degree 2)": lambda: (
            preprocessing.StandardScaler()
            | feature_extraction.PolynomialExtender(degree=2, include_bias=False)
            | linear_model.LogisticRegression()
        ),
        "+ random Fourier basis (RBF)": lambda: (
            preprocessing.StandardScaler()
            | feature_extraction.RBFSampler(n_components=50, seed=7)
            | linear_model.LogisticRegression()
        ),
        "standardised only": logistic,
    }
    for label, build in variants.items():
        got, secs = score(rows, build)
        print(f"    {label:<34} {got:>7.1%} {secs:>9.1f}")

    # Target statistics need the group key, so they get their own pass.
    def target_agg():
        by_cell = compose.TransformerUnion(
            compose.Select(*KEYS),
            feature_extraction.TargetAgg(by="feed", how=stats.Mean()),
            feature_extraction.TargetAgg(by="interval", how=stats.Mean()),
        )
        return by_cell | preprocessing.StandardScaler() | linear_model.LogisticRegression()

    got, secs = score(rows, target_agg, name="with feed/interval")
    print(f"    {'+ target mean per feed and interval':<34} {got:>7.1%} {secs:>9.1f}")


if __name__ == "__main__":
    main()
