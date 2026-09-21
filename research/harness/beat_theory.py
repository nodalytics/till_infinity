"""A directional label with the fair-odds line already subtracted out.

Run from the repository root:

    .venv-research/bin/python research/harness/beat_theory.py

Every directional test in this repository has landed on its null, and `barrier_pde.py`
says why in one line: for a stop `a` below and a target `b` above, a driftless diffusion
reaches the target first with probability `a / (a + b)`. **Geometry alone determines the
base rate.** A model trained on the raw outcome therefore spends nearly all of its
capacity re-deriving a number that was never in doubt, and whatever edge exists is a
rounding error on top of it.

So embed the known part in the label and make the model learn only the rest.

## Why a fixed band cannot do this

With a symmetric barrier the theory is exactly 0.5 for every row. Subtracting a constant
is recentring, not residualising - it removes nothing the model had to learn. This is
worth stating because it is the obvious first attempt and it is empty.

The theory only varies per row when **the geometry varies per row**. So the barriers here
come from structure rather than from a multiple of volatility: the stop sits at the last
confirmed swing low, the target at the last confirmed swing high. That is also what a
real strategy does, so the geometry is the desk's rather than an artefact.

Each row then carries its own fair-odds probability, and the question becomes sharp:

> does a model given the features beat a forecaster that simply reports `a / (a + b)`?

## How that is scored

Not by accuracy. A model and the theory can share an accuracy while differing entirely in
calibration, and the quantity that matters to a desk is the probability, not the label.
So both are scored by **Brier score** - mean squared error of the predicted probability -
and by log loss, on identical purged walk-forward folds:

| forecaster | what it knows |
|------------|---------------|
| `always base` | the single unconditional hit rate. The dumbest thing that is not wrong |
| `fair odds` | `a / (a + b)` per row, and nothing else. The geometry, with no edge |
| `features` | the desk's features, with no knowledge of the geometry |
| `features + fair odds` | both |

**The only comparison that matters is the last against the second.** If knowing the
features does not improve on knowing the geometry, there is no directional edge here -
and this time that conclusion cannot be blamed on the model having wasted itself on the
base rate, because the base rate was handed to it.

A negative Brier skill against `fair odds` would mean the features actively mislead.

## What is deliberately not done

No drift term. A trailing drift estimate could be folded into the theory, which would
subtract momentum as well as geometry - but momentum is exactly the thing under test, and
removing it from the label would be removing the signal along with the noise. The theory
here is the driftless one, so the entire drift is left for the model to find.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import splits  # noqa: E402

#: Bars either side of a swing for it to count. A swing is confirmed this many bars
#: after it forms and nothing may use it before then.
SWING = 5

#: Bars allowed for a barrier to be reached.
HORIZON = 48

#: Widest and narrowest fair-odds probability worth keeping. A row whose stop is a
#: hundred times nearer than its target is not a trade anyone takes, and such rows
#: would otherwise dominate the Brier score by being trivially predictable.
BOUNDS = (0.15, 0.85)


def swings(bars: np.ndarray, k: int = SWING) -> tuple[np.ndarray, np.ndarray]:
    """Running last-confirmed swing low and high, per bar, causally.

    At bar `i` the newest usable swing is at `i - k`, because a pivot is only known `k`
    bars after it forms. Carrying them forward as arrays keeps that offset in one place
    rather than in every caller.
    """
    high, low = bars[:, 2], bars[:, 3]
    n = len(bars)
    last_low = np.full(n, np.nan)
    last_high = np.full(n, np.nan)
    low_now = high_now = np.nan
    for i in range(k, n - k):
        j = i - k
        if j >= k:
            window_hi = high[j - k : j + k + 1]
            window_lo = low[j - k : j + k + 1]
            if high[j] >= window_hi.max():
                high_now = float(high[j])
            if low[j] <= window_lo.min():
                low_now = float(low[j])
        last_low[i] = low_now
        last_high[i] = high_now
    return last_low, last_high


def rows(bars: np.ndarray, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per bar: the fair-odds probability, the outcome, and whether it is usable.

    The outcome is 1 when the target is reached first and 0 when the stop is, with a
    bar that touches both scored as a stop - the same convention as everywhere else
    here, which biases the measured rate below the theory by construction.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    last_low, last_high = swings(bars)
    n = len(bars)
    theory = np.full(n, np.nan)
    outcome = np.zeros(n, dtype=np.int64)
    ok = np.zeros(n, dtype=bool)

    for at in range(n - horizon):
        here = close[at]
        stop, target = last_low[at], last_high[at]
        if not (np.isfinite(stop) and np.isfinite(target)):
            continue
        a, b = here - stop, target - here
        if a <= 0 or b <= 0:
            continue
        # Driftless first passage: the ratio of the distances, nothing else.
        fair = a / (a + b)
        if not (BOUNDS[0] <= fair <= BOUNDS[1]):
            continue
        for step in range(1, horizon + 1):
            hit_up = high[at + step] >= target
            hit_down = low[at + step] <= stop
            if hit_up and hit_down:
                outcome[at], ok[at], theory[at] = 0, True, fair
                break
            if hit_up:
                outcome[at], ok[at], theory[at] = 1, True, fair
                break
            if hit_down:
                outcome[at], ok[at], theory[at] = 0, True, fair
                break
    return theory, outcome, ok


def build(paths: list[Path], horizon: int, every: int):
    """Features, outcome and the per-row fair-odds probability."""
    xs, ys, ts, whens, groups = [], [], [], [], []
    for path in sorted(paths):
        name = path.name.split("_")[0]
        bars, _repaired = candles.read(path)
        if len(bars) < candles.WARMUP + horizon + 50:
            continue
        tr = candles.true_range(bars)
        run, strong = candles.consistency(bars, tr)
        standing = candles.standing_gaps(bars, tr)
        theory, outcome, ok = rows(bars, horizon)

        kept = 0
        for at in range(candles.WARMUP, len(bars) - horizon, every):
            if not ok[at]:
                continue
            row = candles.features(bars, tr, at)
            row += list(standing[at])
            row += [run[at], strong[at]]
            if not all(np.isfinite(row)):
                continue
            xs.append(row)
            ys.append(int(outcome[at]))
            ts.append(float(theory[at]))
            whens.append(float(bars[at, 0]))
            groups.append(name)
            kept += 1
        print(f"  {name:<22} {kept:>6} rows")
    return (
        np.array(xs, dtype=np.float32),
        np.array(ys, dtype=np.int64),
        np.array(ts, dtype=float),
        np.array(whens, dtype=float),
        np.array(groups),
    )


def brier(prob: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((prob - y) ** 2))


def logloss(prob: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(prob, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def run_folds(x, y, theory, when, folds: int) -> dict[str, list[tuple[float, float]]]:
    """Every forecaster on identical purged folds."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    got: dict[str, list[tuple[float, float]]] = {
        "always base": [],
        "fair odds": [],
        "features": [],
        "features + fair odds": [],
    }
    for train, test in splits.walk_forward(when, 1, folds=folds):
        if len(np.unique(y[train])) < 2:
            continue
        base = float(y[train].mean())
        got["always base"].append(
            (brier(np.full(len(test), base), y[test]), logloss(np.full(len(test), base), y[test]))
        )
        got["fair odds"].append((brier(theory[test], y[test]), logloss(theory[test], y[test])))

        for label, cols in (
            ("features", x),
            ("features + fair odds", np.column_stack([x, theory])),
        ):
            model = HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.06, l2_regularization=1.0, random_state=0
            )
            model.fit(cols[train], y[train])
            prob = model.predict_proba(cols[test])[:, 1]
            got[label].append((brier(prob, y[test]), logloss(prob, y[test])))
    return got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    ap.add_argument("--every", type=int, default=6)
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    paths = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if found:
            paths.append(found[0])
    if not paths:
        print("no candle files found")
        return 1

    print(
        f"barriers from the last confirmed swings, horizon {args.horizon}, "
        f"one row per {args.every} bars\n"
    )
    x, y, theory, when, groups = build(paths, args.horizon, args.every)
    if len(y) < 2000:
        print(f"only {len(y)} rows")
        return 1

    print(
        f"\n{len(y):,} rows over {len(set(groups.tolist()))} instruments, "
        f"target reached first {y.mean():.1%} of the time"
    )
    print(
        f"fair odds averages {theory.mean():.1%}, ranging {theory.min():.2f} to {theory.max():.2f}"
    )

    got = run_folds(x, y, theory, when, args.folds)
    print(f"\n  {'forecaster':<24}{'Brier':>9}{'log loss':>11}{'skill vs fair odds':>21}")
    fair = float(np.mean([b for b, _ in got["fair odds"]])) if got["fair odds"] else float("nan")
    for label, scores in got.items():
        if not scores:
            continue
        b = float(np.mean([s[0] for s in scores]))
        ll = float(np.mean([s[1] for s in scores]))
        skill = (fair - b) / fair if fair else float("nan")
        print(f"  {label:<24}{b:>9.5f}{ll:>11.5f}{skill:>20.2%}")

    print(
        "\n  Brier is mean squared error of the predicted probability, so lower is\n"
        "  better, and skill is the fractional improvement over the fair-odds\n"
        "  forecaster. The row that decides it is `features + fair odds`: the geometry\n"
        "  has been handed to the model, so anything it adds is edge and anything it\n"
        "  loses is the features actively misleading it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
