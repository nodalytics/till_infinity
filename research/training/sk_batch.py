"""Batch-train scikit-learn models on the candle panel, and report honestly.

Run from the repository root:

    .venv-research/bin/python research/training/sk_batch.py --family triple
    .venv-research/bin/python research/training/sk_batch.py --family speed --interval 1h

**Why a separate interpreter.** scikit-learn and TensorFlow are not dependencies
of the desk and must not become them: the live container has a 2.6GB limit and has
been OOM-killed sixty-three times, and adding a deep-learning stack to its image
to answer a research question would be a poor trade. `.venv-research` is built
from `research/training/requirements.txt` and nothing imports it at runtime.

## What this prints, and which number matters

Four, in increasing order of how much they should change anyone's mind:

1. **accuracy** - nearly worthless on its own, and printed next to the majority
   share so it cannot be read on its own. A three-class banded label is roughly
   50% flat, so 50% accuracy is a model that has learned to say nothing.
2. **balanced accuracy** - accuracy after each class is given equal weight, which
   is the first number that can distinguish a model from a constant.
3. **edge per call** - of the rows where the model made a directional call, the
   mean realised return under that family's own exit rule, **minus cost**. This is
   the only number denominated in money.
4. **the shuffled null** - the same pipeline with labels block-permuted. Whatever
   it scores is what this apparatus produces from noise, and a result that does
   not clear it by a wide margin is not a result. Six findings here have died at
   this step and one survived four weaker controls before dying at a fifth.

Then leave-one-instrument-out, which is the control that has caught what nothing
else did.

## What it deliberately does not do

No hyperparameter search. Tuning against a walk-forward score and then reporting
that score is how a null becomes a finding, and the honest version of tuning needs
a third split this sample cannot spare. The settings are ordinary defaults, chosen
once, and left alone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "harness"))

import candles  # noqa: E402
import splits  # noqa: E402

#: Round-trip cost in fractional return terms. 2bp is deliberately above the
#: 0.10-1.07bp spread measured on this broker, to cover the 2-8% stop overshoot
#: that was measured alongside it. A model that only works at zero cost does not
#: work.
COST = 0.0002


def models():
    """The two estimators, plus the baseline that has to be beaten.

    `HistGradientBoosting` because it is the strongest thing in scikit-learn for
    tabular data of this size and it handles unscaled features and NaNs itself;
    logistic regression because a linear model scoring the same means the trees
    found nothing a line could not.
    """
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "majority": DummyClassifier(strategy="prior"),
        "logistic": make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, class_weight="balanced"),
        ),
        "boosted": HistGradientBoostingClassifier(
            max_iter=300,
            learning_rate=0.06,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            early_stopping=True,
            validation_fraction=0.15,
            random_state=0,
        ),
    }


def score(fit, x, y, ret, classes) -> dict[str, float]:
    """Accuracy, balanced accuracy, and what the calls would have paid."""
    from sklearn.metrics import accuracy_score, balanced_accuracy_score

    said = fit.predict(x)
    out = {
        "acc": float(accuracy_score(y, said)),
        "bal": float(balanced_accuracy_score(y, said)),
    }

    # A "call" is anything but the neutral middle class. Every family here puts
    # its do-nothing class in the middle, so this is one rule for all of them.
    neutral = 1
    took = said != neutral
    out["calls"] = float(took.sum())
    out["call_share"] = float(took.mean()) if len(said) else 0.0
    if took.any():
        # Direction: the top class is the favourable one, the bottom the adverse
        # one. `ret` is already signed the way the family resolves, so an adverse
        # call earns the negative of it.
        top = len(classes) - 1
        side = np.where(said[took] == top, 1.0, -1.0)
        paid = side * ret[took] - COST
        out["edge"] = float(paid.mean())
        out["edge_se"] = float(paid.std(ddof=1) / max(np.sqrt(len(paid)), 1.0))
    else:
        out["edge"] = 0.0
        out["edge_se"] = 0.0
    return out


def average(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    return {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}


def run(panel, folds: int, *, shuffled: bool = False) -> dict[str, dict[str, float]]:
    """Walk-forward every model over the panel, returning mean fold scores."""
    y = splits.block_shuffle(panel.y, panel.when, panel.horizon) if shuffled else panel.y
    gathered: dict[str, list[dict[str, float]]] = {name: [] for name in models()}
    folds_seen = 0
    for train, test in splits.walk_forward(panel.when, panel.horizon, folds=folds):
        folds_seen += 1
        for name, model in models().items():
            # A fold whose training slice is missing a class cannot be fitted for
            # that class, and pretending otherwise gives a silent zero.
            if len(np.unique(y[train])) < 2:
                continue
            model.fit(panel.x[train], y[train])
            gathered[name].append(
                score(model, panel.x[test], y[test], panel.ret[test], panel.classes)
            )
    if not folds_seen:
        print("  not enough data for a purged walk-forward at this horizon")
    return {name: average(rows) for name, rows in gathered.items() if rows}


def table(title: str, scored: dict[str, dict[str, float]], majority: float) -> None:
    print(f"\n{title}")
    print(f"  {'model':<10} {'acc':>7} {'bal':>7} {'calls':>7} {'edge/call':>11} {'t':>6}")
    for name, got in scored.items():
        t = got["edge"] / got["edge_se"] if got.get("edge_se") else 0.0
        print(
            f"  {name:<10} {got['acc']:>7.3f} {got['bal']:>7.3f} "
            f"{got['call_share']:>6.1%} {got['edge']:>+11.5f} {t:>6.2f}"
        )
    print(f"  majority class is {majority:.1%} - accuracy below that is worse than a constant")


def held_out(panel) -> None:
    """Leave-one-instrument-out, with the time cut kept."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    print("\nleave-one-instrument-out (boosted only)")
    print(f"  {'held out':<14} {'rows':>7} {'acc':>7} {'bal':>7} {'edge/call':>11}")
    rows = []
    for name, train, test in splits.leave_one_out(panel.groups, panel.when, panel.horizon):
        if len(np.unique(panel.y[train])) < 2:
            continue
        model = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, l2_regularization=1.0, random_state=0
        )
        model.fit(panel.x[train], panel.y[train])
        got = score(model, panel.x[test], panel.y[test], panel.ret[test], panel.classes)
        rows.append(got["edge"])
        print(
            f"  {name:<14} {len(test):>7} {got['acc']:>7.3f} {got['bal']:>7.3f} "
            f"{got['edge']:>+11.5f}"
        )
    if rows:
        wins = sum(1 for r in rows if r > 0)
        print(
            f"  {wins} of {len(rows)} instruments profitable when never trained on. "
            "A result carried by one instrument shows up here and nowhere else."
        )


def importance(panel) -> None:
    """Permutation importance on the last fold, for reading rather than selecting."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance

    last = None
    for train, test in splits.walk_forward(panel.when, panel.horizon, folds=5):
        last = (train, test)
    if last is None:
        return
    train, test = last
    model = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, l2_regularization=1.0, random_state=0
    )
    model.fit(panel.x[train], panel.y[train])
    got = permutation_importance(
        model,
        panel.x[test],
        panel.y[test],
        n_repeats=5,
        random_state=0,
        scoring="balanced_accuracy",
    )
    order = np.argsort(got.importances_mean)[::-1][:8]
    print("\nwhat the model leaned on (permutation, balanced accuracy, last fold)")
    for i in order:
        print(f"  {panel.names[i]:<18} {got.importances_mean[i]:>+8.4f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--family",
        default="banded",
        help="banded, triple, speed, expansion, regime or seasonal",
    )
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--where", default=".secrets", help="directory holding the candle files")
    ap.add_argument("--horizon", type=int, default=5, help="bars ahead the label looks")
    ap.add_argument("--band", type=float, default=1.0, help="barrier in true ranges")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--skip-null", action="store_true", help="skip the null; it doubles the run")
    args = ap.parse_args()

    paths = candles.find(args.where, args.interval)
    if not paths:
        print(f"no {args.interval} candle files in {args.where} - run research/harness/history.py")
        return 1

    print(f"{len(paths)} files, family={args.family} horizon={args.horizon} band={args.band}")
    panel = candles.build(paths, family=args.family, horizon=args.horizon, band=args.band)
    if not len(panel):
        print("no usable rows")
        return 1

    counts = np.bincount(panel.y, minlength=len(panel.classes))
    spread = "  ".join(
        f"{c}={n / len(panel):.1%}" for c, n in zip(panel.classes, counts, strict=False)
    )
    print(f"\n{len(panel):,} rows over {len(set(panel.groups.tolist()))} instruments   {spread}")

    from labels import NEEDS_EXTREMES

    if args.family in NEEDS_EXTREMES:
        worst = max(panel.repairs.items(), key=lambda kv: kv[1], default=("", 0))
        if worst[1]:
            print(
                f"  this family reads highs and lows; worst repaired bar count is "
                f"{worst[0]} at {worst[1]:,} - treat first-passage results as soft"
            )

    table(f"walk-forward, {args.folds} purged folds", run(panel, args.folds), panel.majority)
    if not args.skip_null:
        table(
            "the same, on block-shuffled labels - this is what noise scores",
            run(panel, args.folds, shuffled=True),
            panel.majority,
        )
    held_out(panel)
    importance(panel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
