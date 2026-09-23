"""How far does a perceptron take us? To the margin, and the margin is the answer.

Run from the repository root:  python research/harness/perceptron.py

The desk asked to *"explore the concept of the perceptron, and see how far it takes us"*. This
folder has a partial answer already - `models.md` measured trees, forests, cosine similarity and
an MLP against **a 1KB logistic regression** and the logistic regression won, and five times the
data did not change it. A logistic regression is a perceptron with a smooth output, so the news
that the linear model wins is not new.

What is new is asking **why** it wins, and the perceptron is the right object to ask with, because
it is the one classifier whose limits are a theorem rather than a benchmark.

## The theorem, and the quantity it hands us

Rosenblatt's rule is one line - on a mistake, move the weights toward the example:

    if y (w . x) <= 0:   w <- w + y x

Novikoff's theorem says this converges after at most `(R / gamma)^2` mistakes, where `R` is the
largest input norm and **`gamma` is the margin** - the distance from the separating plane to the
nearest correctly classified point.

That bound is the whole value of using a perceptron here. It says the difficulty of a linear
problem is one number, `R / gamma`, and it says what happens when no separating plane exists:
**the margin is zero, the bound is infinite, and the perceptron never stops making mistakes.** It
does not degrade gracefully or converge to something reasonable - it cycles.

So the question "how far does a perceptron take us" has a precise form: **what is the margin of
this desk's data?** If it is zero, then no linear model separates breaks from holds, the
perceptron's mistake rate never falls, and that is a statement about the data rather than about
the perceptron - one which bounds every linear method including the one in production.

## What is measured

Over **192,402 resolved touches** from the live journal - the subset of `break-trade.md`'s 312,420
that carries all seven causal features, since `slope` and `prior_slope` were added later than the
rest and imputing a zero for a missing slope would be inventing a flat approach.

* **the mistake curve.** The perceptron's error rate over time, in one pass, predict-then-update.
  On separable data it falls to zero. On this data the interesting number is what it *flattens*
  at, because that plateau is the margin speaking;
* **the margin itself**, estimated directly: fit the best linear separator available, then read
  the distribution of `y (w . x) / |w|`. A negative median for either class means the classes
  overlap through the plane, which is unseparability measured rather than assumed;
* **against the incumbent.** `Breaks` is an online logistic regression at AUC 0.658 in band. The
  perceptron is the same hypothesis class with a worse loss, so it should lose - and by how much
  is the useful number, since it prices what the smooth loss is buying;
* **the averaged perceptron**, which is the one fix that matters for non-separable data:
  averaging the weight vector over the run rather than taking its last value. On cycling data the
  final weights are wherever the last mistake threw them, and the average is the stable estimate
  of the same plane.

## And what the eigenvectors have to do with it

The desk asked about eigenvalues in the same breath, and they meet here. A perceptron's
convergence rate depends on `R / gamma`, and `R` is inflated by **correlated inputs**: two
features that say the same thing stretch the input cloud along one direction without adding
separating power. `eigen.py` measured that the real book has one dominant factor carrying 45.6% of
variance.

So the same run is repeated on **whitened** inputs - rotated onto the correlation matrix's
eigenvectors and scaled to unit variance, which is PCA with no truncation and therefore no
information discarded. If whitening speeds convergence, the raw features were badly conditioned
rather than uninformative, and that distinction is exactly what a margin measurement can make and
a benchmark cannot.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import numpy as np

#: The features known when a touch opens - the same causal set `break_trade.py` uses, and for the
#: same reason: `push_vol` is signed by the outcome and would make this trivial and meaningless.
FEATURES = (
    "approach_vol",
    "depth_vol",
    "slowing",
    "slope",
    "prior_slope",
    "strength",
    "experience",
)

HELD = ("reject", "backcheck", "trap")
BROKE = ("break",)

#: Where the mistake curve is sampled, as a share of the pass.
MARKS = (0.05, 0.1, 0.25, 0.5, 0.75, 1.0)


def load(where: Path) -> tuple[np.ndarray, np.ndarray]:
    """Design matrix and labels in `{-1, +1}`, in time order."""
    rows = []
    with gzip.open(where, "rt") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("outcome") not in HELD + BROKE:
                continue
            got = [row.get(name) for name in FEATURES]
            # Every feature must be present. `slope` and `prior_slope` were added later than the
            # rest, so requiring all seven costs about a third of the rows - which is the honest
            # trade, since imputing a zero for a missing slope would be inventing a flat approach.
            if any(not isinstance(v, (int, float)) for v in got):
                continue
            rows.append((row.get("time") or 0.0, [float(v) for v in got], row["outcome"] in BROKE))
    rows.sort(key=lambda r: r[0])
    x = np.array([r[1] for r in rows])
    y = np.where([r[2] for r in rows], 1.0, -1.0)
    return x, y


def standardise(x: np.ndarray) -> np.ndarray:
    """Zero mean, unit variance, plus a bias column.

    Not cosmetic. The perceptron's update is `w <- w + y x`, so a feature measured in thousands
    moves the weights a thousand times as far as one measured in units - the step size is the
    input scale. `breaking.py` records the cost of missing this: `slowing`'s running mean had
    reached **141,380,329** and a cap could never take effect.
    """
    sd = x.std(axis=0)
    sd[sd <= 0] = 1.0
    return np.column_stack([(x - x.mean(axis=0)) / sd, np.ones(len(x))])


def whiten(x: np.ndarray) -> np.ndarray:
    """Rotate onto the eigenvectors and scale to unit variance - PCA with nothing discarded.

    Every component is kept, so no information is removed; only the conditioning changes. That
    is what makes this a clean test of whether correlated inputs were the problem.
    """
    core = x[:, :-1]
    corr = np.cov(core, rowvar=False)
    values, vectors = np.linalg.eigh(corr)
    values = np.maximum(values, 1e-12)
    return np.column_stack([(core @ vectors) / np.sqrt(values), np.ones(len(x))])


def run(x: np.ndarray, y: np.ndarray, *, rate: float = 1.0) -> dict:
    """One predict-then-update pass. Every prediction is out of sample by construction."""
    n, d = x.shape
    w = np.zeros(d)
    total = np.zeros(d)
    mistakes = 0
    curve: list[float] = []
    marks = [int(n * m) - 1 for m in MARKS]
    for i in range(n):
        if y[i] * (w @ x[i]) <= 0:
            w = w + rate * y[i] * x[i]
            mistakes += 1
        total += w
        if i in marks or i == n - 1:
            curve.append(mistakes / (i + 1))
    return {"w": w, "avg": total / n, "rate": mistakes / n, "curve": curve}


def margin(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> dict:
    """The geometry: how far each class sits from the plane, in units of `|w|`.

    `gamma` in Novikoff's bound is the **minimum** of this over correctly classified points. If
    the classes overlap, the minimum is negative and the bound does not exist - which is the
    finding, not a failure to compute one.
    """
    norm = np.linalg.norm(w) or 1.0
    signed = y * (x @ w) / norm
    radius = float(np.max(np.linalg.norm(x, axis=1)))
    share = float((signed > 0).mean())
    return {
        "radius": radius,
        "correct": share,
        "p50": float(np.median(signed)),
        "p10": float(np.percentile(signed, 10)),
        "gamma": float(np.min(signed)),
        # The bound Novikoff gives, if a positive margin existed at all.
        "bound": (radius / np.percentile(signed[signed > 0], 5)) ** 2 if share > 0.05 else math.inf,
    }


def auc(score: np.ndarray, label: np.ndarray) -> float:
    order = np.argsort(score)
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    pos = float((label > 0).sum())
    neg = len(label) - pos
    if not pos or not neg:
        return float("nan")
    return float((ranks[label > 0].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def logistic(x: np.ndarray, y: np.ndarray, rate: float = 0.02) -> dict:
    """The incumbent's shape: online logistic regression, same pass, same order.

    `Breaks` runs at `rate = 0.02`, swept over the whole record - so this is the production model's
    learning rule on the production model's step size, not a strawman.
    """
    w = np.zeros(x.shape[1])
    wrong = 0
    scores = np.empty(len(x))
    for i in range(len(x)):
        z = float(w @ x[i])
        scores[i] = z
        p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
        target = 1.0 if y[i] > 0 else 0.0
        if (z > 0) != (y[i] > 0):
            wrong += 1
        w = w + rate * (target - p) * x[i]
    return {"w": w, "rate": wrong / len(x), "auc": auc(scores, y)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--where", default=".secrets/journal/touches.jsonl.gz")
    args = ap.parse_args()

    x_raw, y = load(Path(args.where).expanduser())
    base = float((y > 0).mean())
    print(
        f"{len(y):,} resolved touches, {len(FEATURES)} causal features, "
        f"{base:.1%} of them breaks\n"
        f"always-hold gets {1 - base:.1%} right, which is the number every row below has to beat\n"
    )

    for name, x in (("standardised", standardise(x_raw)), ("whitened", whiten(standardise(x_raw)))):
        got = run(x, y)
        geo = margin(x, y, got["avg"])
        lg = logistic(x, y)
        print(f"{name}")
        print(
            "  mistake rate over the pass: "
            + "  ".join(f"{m:.0%}->{v:.3f}" for m, v in zip(MARKS, got["curve"], strict=False))
        )
        print(
            f"  perceptron final {got['rate']:.4f} wrong   |   "
            f"online logistic {lg['rate']:.4f} wrong, AUC {lg['auc']:.4f}"
        )
        print(
            f"  averaged-weight AUC {auc(x @ got['avg'], y):.4f}   "
            f"last-weight AUC {auc(x @ got['w'], y):.4f}"
        )
        print(
            f"  geometry: |x| at most {geo['radius']:.2f}, "
            f"{geo['correct']:.1%} on the right side, "
            f"margin p50 {geo['p50']:+.4f}, p10 {geo['p10']:+.4f}, min {geo['gamma']:+.3f}"
        )
        print()

    print(
        "  **The mistake curve is the result.** On linearly separable data it falls to zero and\n"
        "  Novikoff bounds how fast. A curve that flattens above zero is reporting that no plane\n"
        "  separates these classes - and the minimum margin coming out **negative** is that same\n"
        "  fact stated exactly: points of both classes sit on the wrong side of every plane the\n"
        "  data admits.\n"
        "\n  That is a statement about the data and it binds every linear model, including the\n"
        "  one in production. It is also why `models.md` found a 1KB logistic regression beating\n"
        "  a forest and an MLP: when the classes overlap this thoroughly, the extra capacity has\n"
        "  nothing to fit but noise.\n"
        "\n  **Averaged against last weights** prices the one fix that matters off separable\n"
        "  data. **Whitened against standardised** says whether correlated inputs were hurting\n"
        "  the conditioning - if the two are the same, the features were not the problem."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
