"""Forward volatility: GARCH against trailing ratios against topology.

Run from the repository root:

    .venv-research/bin/python research/harness/vol_baseline.py

`topology.md` states that the bar for a volatility signal "is not the shuffled null, it
is GARCH", and then does not run GARCH. This runs it. Leaving that owed while reaching
for a third sophisticated method would be the exact mistake this repository keeps
recording.

## Why GARCH is the bar and not a nicety

Volatility clustering is the most replicated fact in empirical finance, the model for it
is standard textbook material, and `clustering.md` opens this repository by saying so.
Any new volatility forecaster is therefore competing against something cheap and
well-understood, not against noise. `tda.py` already showed how wide that gap can be:
six trailing realised-volatility ratios beat twelve persistence features by 6.8 points
of balanced accuracy.

The ranking this produces is the useful artefact, because it says where the ceiling is
before anything more elaborate gets built.

## What is compared

All on the same rows, same folds, same label - `expansion`, three classes, is forward
realised volatility about to contract, hold, or expand:

| model | what it is |
|-------|------------|
| `shuffled null` | the label block-permuted; what this apparatus scores on nothing |
| `shortest ratio` | one feature: the 5-bar realised volatility over the 64-bar |
| `trailing ratios` | six realised-volatility ratios over different lookbacks |
| `GARCH(1,1)` | the conditional-variance forecast, fitted causally |
| `GARCH + trailing` | both, to see whether either adds to the other |

`GARCH(1,1)` is fitted on an expanding window and forecast one step ahead, refitted every
`--refit` bars because refitting at every bar is thousands of maximum-likelihood
optimisations for a number that barely moves between adjacent bars. The refit interval is
stated rather than hidden, and the forecast between refits uses the fitted parameters
recursively, which is what a desk would actually do.

## The one thing to be careful about

A GARCH forecast is a *variance*, and the label is a three-class band around the
instrument's own median ratio. Feeding the raw variance to a classifier would let it
learn the instrument's level rather than its direction of change, so what is fed is the
**ratio** of the forecast to the trailing realised volatility - dimensionless, and the
same quantity the other models see.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import splits  # noqa: E402

#: Bars of history each row's features look back over.
WINDOW = 64

#: Bars between GARCH refits. Thousands of likelihood fits for a parameter set that
#: barely moves is a poor trade; between refits the recursion carries the forecast.
REFIT = 500

#: Bars of history a GARCH fit needs before it is trusted at all.
BURN = 1000


def trailing(bars: np.ndarray, at: int) -> list[float]:
    """Six realised-volatility ratios - the baseline that beat topology."""
    close = bars[at - WINDOW : at + 1, 4]
    if len(close) < WINDOW or (close <= 0).any():
        return [0.0] * 6
    returns = np.diff(np.log(close))
    long = returns.std()
    if long <= 0:
        return [0.0] * 6
    tr = candles.true_range(bars[at - WINDOW : at + 1])
    return [
        float(returns[-5:].std() / long),
        float(returns[-10:].std() / long),
        float(returns[-20:].std() / long),
        float(abs(returns[-1]) / long),
        float(tr[-1] / long),
        float(np.abs(returns).mean() / long),
    ]


def garch_track(returns: np.ndarray, refit: int = REFIT, burn: int = BURN) -> np.ndarray:
    """One-step-ahead conditional volatility, causally, for every bar.

    Refitted every `refit` bars on everything seen so far; between refits the fitted
    `omega`, `alpha`, `beta` carry the recursion forward. Every value at index `i` uses
    only returns up to `i`, which is the only way it can be a forecast.
    """
    from arch import arch_model

    out = np.full(len(returns), np.nan)
    if len(returns) < burn + 10:
        return out

    scaled = returns * 100.0  # arch is happier away from 1e-4 magnitudes
    params = None
    var = float(np.var(scaled[:burn]))
    for at in range(burn, len(returns)):
        if params is None or (at - burn) % refit == 0:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    fitted = arch_model(
                        scaled[:at], vol="GARCH", p=1, q=1, mean="Zero", rescale=False
                    ).fit(disp="off", show_warning=False)
                    params = (
                        float(fitted.params.get("omega", 0.0)),
                        float(fitted.params.get("alpha[1]", 0.0)),
                        float(fitted.params.get("beta[1]", 0.0)),
                    )
                    var = float(fitted.conditional_volatility[-1] ** 2)
                except Exception:
                    params = params or (float(np.var(scaled[:at])) * 0.1, 0.1, 0.8)
        omega, alpha, beta = params
        # The recursion: tomorrow's variance from today's shock and today's variance.
        var = omega + alpha * scaled[at - 1] ** 2 + beta * var
        if var > 0:
            out[at] = float(np.sqrt(var) / 100.0)
    return out


def build(paths: list[Path], horizon: int, band: float, every: int):
    """Rows carrying every model's features, so all of them see identical data."""
    from labels import FAMILIES

    make = FAMILIES["expansion"]
    xs, ys, whens, groups = [], [], [], []
    for path in sorted(paths):
        name = path.name.split("_")[0]
        bars, _repaired = candles.read(path)
        if len(bars) < BURN + WINDOW + horizon + 10:
            print(f"  {name:<22} only {len(bars)} bars, skipped")
            continue
        tr = candles.true_range(bars)
        y, _ret, valid, classes = make(bars, tr, horizon, band)
        close = bars[:, 4]
        returns = np.zeros(len(close))
        good = (close[1:] > 0) & (close[:-1] > 0)
        returns[1:] = np.where(
            good, np.log(np.maximum(close[1:], 1e-12) / np.maximum(close[:-1], 1e-12)), 0.0
        )
        forecast = garch_track(returns)

        kept = 0
        for at in range(max(WINDOW, BURN), len(bars) - horizon, every):
            if not valid[at] or not np.isfinite(forecast[at]):
                continue
            ratios = trailing(bars, at)
            if not all(np.isfinite(ratios)):
                continue
            window = returns[at - WINDOW + 1 : at + 1]
            realised = float(window.std())
            if realised <= 0:
                continue
            # Dimensionless: the forecast against what has just been realised, so no
            # model can win by learning the instrument's volatility level.
            xs.append([forecast[at] / realised, *ratios])
            ys.append(int(y[at]))
            whens.append(bars[at, 0])
            groups.append(name)
            kept += 1
        print(f"  {name:<22} {kept:>6} rows")
    return (
        np.array(xs, dtype=np.float32),
        np.array(ys, dtype=np.int64),
        np.array(whens, dtype=float),
        np.array(groups),
        classes,
    )


def evaluate(x, y, when, folds: int, *, shuffled: bool = False) -> float | None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import balanced_accuracy_score

    labels = splits.block_shuffle(y, when, 1) if shuffled else y
    scores = []
    for train, test in splits.walk_forward(when, 1, folds=folds):
        if len(np.unique(labels[train])) < 2:
            continue
        model = HistGradientBoostingClassifier(
            max_iter=250, learning_rate=0.06, l2_regularization=1.0, random_state=0
        )
        model.fit(x[train], labels[train])
        scores.append(balanced_accuracy_score(labels[test], model.predict(x[test])))
    return float(np.mean(scores)) if scores else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=12)
    ap.add_argument("--band", type=float, default=1.0)
    ap.add_argument("--every", type=int, default=12)
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

    print(f"expansion label, horizon {args.horizon}, one row per {args.every} bars\n")
    x, y, when, groups, _classes = build(paths, args.horizon, args.band, args.every)
    if not len(y):
        print("no rows")
        return 1

    blocks = {
        "shortest ratio only": [1],
        "GARCH(1,1) only": [0],
        "trailing ratios only": list(range(1, x.shape[1])),
        "GARCH + trailing": list(range(x.shape[1])),
    }
    null = evaluate(x, y, when, args.folds, shuffled=True)
    print(f"\n{len(y):,} rows over {len(set(groups.tolist()))} instruments")
    print(f"  {'shuffled null':<24}{null:.4f}   <- what noise scores")
    for label, cols in blocks.items():
        got = evaluate(x[:, cols], y, when, args.folds)
        if got is None:
            continue
        print(f"  {label:<24}{got:.4f}   lift {got - null:+.4f}   ({len(cols)} features)")
    print(
        "\n  For reference, `tda.py` on the same label and instruments: topology only\n"
        "  0.3604, trailing volatility only 0.4279, both 0.4305, null 0.3324.\n"
        "  If GARCH matches or beats `trailing ratios`, the ceiling for a volatility\n"
        "  forecaster here is a standard model and anything more elaborate has to clear\n"
        "  it rather than clear noise."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
