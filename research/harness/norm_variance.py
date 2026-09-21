"""Is the persistence-landscape norm just a variance? Regress it and see.

Run from the repository root:

    .venv-research/bin/python research/harness/norm_variance.py

The whole topological-crash literature rests on the `L^p` norm of a persistence
landscape rising before crashes. There is a closed form for that norm, and it settles
what the statistic is:

    ||lambda||_p^p = sum_i 2 h_i^(p+1) / (p+1),    h_i = (d_i - b_i) / 2

so for `p = 1`, `||lambda||_1 = (1/4) sum_i (d_i - b_i)^2` - **a sum of squared
lifetimes, which is dimensionally a variance.**

Vietoris-Rips is scale-equivariant: `VR(cX, ct) = VR(X, t)`. Scaling a point cloud by
`c` scales every birth and death by `c`, so the norm scales by `c^(1 + 1/p)` - degree
**2** for `p = 1`. Gidea and Katz derive this in their own paper and state the norms
are "proportional to the variance", and then do not draw the inference.

## The test, which appears never to have been published

If the norm is a variance times an uninformative shape factor, then

    log ||lambda||_1  =  2 log(sigma)  +  constant  +  noise

so a regression of `log ||lambda||_1` on `log(realised variance)` should have a slope
of **1.0** against log-variance (equivalently 2.0 against log-volatility) and a high
`R^2`. Whatever is left over is the shape factor - the only part that could carry
topological information that volatility does not already have.

Three things are reported, in order of how much they decide:

1. **the slope**, against its predicted value;
2. **the `R^2`**, which is the share of the norm that is simply variance;
3. **whether the residual forecasts anything** that realised variance does not - the
   residual being, by construction, the part of the topology with the variance removed.

A slope near the prediction with a high `R^2` and a residual that forecasts nothing
would mean the statistic is a noisy variance estimator wearing a topological label.

## Why this is worth the afternoon

A survey of the literature could not find this regression in roughly 370 works citing
the two anchor papers. It is also the cheapest possible test of the strongest available
criticism, and it runs on data already in hand.

**The prediction is recorded before the run**, as with `tda.py`: slope close to 1.0
against log-variance, `R^2` above 0.8, and no out-of-sample forecasting power in the
residual.
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

#: Delay embedding, as measured by `embed.py` rather than assumed.
DIM = 6
LAG = 4

#: Window the point cloud and the realised variance are both computed over. They must
#: be the same window or the regression compares two different things.
WINDOW = 64

#: Bars ahead for the forecasting leg.
HORIZON = 12


def landscape_l1(pairs: np.ndarray) -> float:
    """`(1/4) sum (d - b)^2`, the closed form of the first landscape's `L1` norm.

    Computed in closed form rather than by integrating a gridded landscape, because
    the closed form is exact and the grid is not - and because writing it this way
    makes the claim under test visible: it is a sum of squared lifetimes.
    """
    if not len(pairs):
        return 0.0
    finite = pairs[np.isfinite(pairs[:, 1])]
    if not len(finite):
        return 0.0
    lives = finite[:, 1] - finite[:, 0]
    lives = lives[lives > 0]
    return float(0.25 * np.sum(lives**2))


def norms_and_variance(bars: np.ndarray, every: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per sampled bar: the `H1` landscape norm, the realised variance, the timestamp.

    **The returns are not standardised here.** Every other harness in this repository
    divides them by their own spread, which is exactly what would destroy the
    relationship under test - the point is to let the scale vary and watch the norm
    follow it.
    """
    from ripser import ripser

    close = bars[:, 4]
    logs = np.zeros(len(close))
    good = (close[1:] > 0) & (close[:-1] > 0)
    logs[1:] = np.where(
        good, np.log(np.maximum(close[1:], 1e-12) / np.maximum(close[:-1], 1e-12)), 0.0
    )

    span = (DIM - 1) * LAG
    norms, variance, whens = [], [], []
    for at in range(WINDOW + span, len(bars), every):
        window = logs[at - WINDOW + 1 : at + 1]
        if len(window) < WINDOW or not np.isfinite(window).all():
            continue
        var = float(np.var(window, ddof=1))
        if var <= 0:
            continue
        count = len(window) - span
        if count < DIM + 2:
            continue
        cloud = np.stack([window[i * LAG : i * LAG + count] for i in range(DIM)], axis=1)
        dgms = ripser(cloud, maxdim=1)["dgms"]
        if len(dgms) < 2:
            continue
        norm = landscape_l1(np.asarray(dgms[1]))
        if norm <= 0:
            continue
        norms.append(norm)
        variance.append(var)
        whens.append(float(bars[at, 0]))
    return np.array(norms), np.array(variance), np.array(whens)


def regress(y: np.ndarray, x: np.ndarray) -> tuple[float, float, float]:
    """Slope, intercept and `R^2` of an ordinary least squares fit."""
    design = np.column_stack([x, np.ones_like(x)])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coef
    resid = y - fitted
    total = y - y.mean()
    r2 = 1.0 - float(resid @ resid) / float(total @ total)
    return float(coef[0]), float(coef[1]), r2


def forecasts(variance, resid, when, horizon: int, folds: int) -> tuple[float, float]:
    """Out-of-sample `R^2` for forward variance, from variance alone and with the residual.

    The residual is the topology with the variance divided out, so if it adds nothing
    here then the norm contains nothing that realised variance does not.
    """
    from sklearn.linear_model import Ridge

    ahead = np.full(len(variance), np.nan)
    ahead[:-horizon] = variance[horizon:]
    ok = np.isfinite(ahead)
    y = np.log(ahead[ok])
    base = np.log(variance[ok]).reshape(-1, 1)
    both = np.column_stack([np.log(variance[ok]), resid[ok]])
    stamps = when[ok]

    scores = {"base": [], "both": []}
    for train, test in splits.walk_forward(stamps, horizon, folds=folds):
        if len(train) < 100 or len(test) < 50:
            continue
        for label, cols in (("base", base), ("both", both)):
            model = Ridge(alpha=1.0).fit(cols[train], y[train])
            said = model.predict(cols[test])
            err = float(np.mean((y[test] - said) ** 2))
            var = float(np.var(y[test]))
            scores[label].append(1.0 - err / var if var > 0 else 0.0)
    return (
        float(np.mean(scores["base"])) if scores["base"] else float("nan"),
        float(np.mean(scores["both"])) if scores["both"] else float("nan"),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--every", type=int, default=16)
    ap.add_argument("--folds", type=int, default=4)
    args = ap.parse_args()

    print(
        f"H1 landscape L1 norm against realised variance, window {WINDOW}, "
        f"delay d={DIM} lag={LAG}, one sample per {args.every} bars\n"
    )
    print(
        "prediction, recorded before the run: slope near 1.0 against log-variance,\n"
        "R^2 above 0.8, and no out-of-sample gain from the residual.\n"
    )
    print(f"{'instrument':<22}{'n':>7}{'slope':>8}{'R^2':>8}{'OOS base':>10}{'OOS both':>10}")
    slopes, r2s, gains = [], [], []
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        norms, variance, when = norms_and_variance(bars, args.every)
        if len(norms) < 500:
            print(f"{symbol:<22} only {len(norms)} samples")
            continue
        slope, _intercept, r2 = regress(np.log(norms), np.log(variance))
        design = np.column_stack([np.log(variance), np.ones_like(variance)])
        coef, *_ = np.linalg.lstsq(design, np.log(norms), rcond=None)
        resid = np.log(norms) - design @ coef
        base, both = forecasts(variance, resid, when, HORIZON, args.folds)
        slopes.append(slope)
        r2s.append(r2)
        gains.append(both - base)
        print(f"{symbol:<22}{len(norms):>7,}{slope:>8.3f}{r2:>8.3f}{base:>10.4f}{both:>10.4f}")

    if slopes:
        print(
            f"\nmean slope {np.mean(slopes):.3f} against a predicted 1.000, "
            f"mean R^2 {np.mean(r2s):.3f}"
        )
        print(
            f"mean out-of-sample gain from the residual {np.mean(gains):+.4f} over variance alone"
        )
        print(
            "\n  A slope near 1.0 with a high R^2 means the norm is a variance in\n"
            "  disguise: the shape factor multiplies it but does not vary much. A\n"
            "  residual that adds nothing out of sample means the part of the topology\n"
            "  with variance removed carries no forecast - which is the strongest\n"
            "  available criticism of the whole persistence-norm literature, tested\n"
            "  directly rather than argued."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
