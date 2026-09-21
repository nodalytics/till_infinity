"""How far a breakout runs before it breaks, and whether that distance is predictable.

Run from the repository root:  python research/harness/breakout_runs.py

Three questions arrived as separate ideas and turn out to be one event read three ways:
how far a breakout runs, whether that distance can be predicted, and **when momentum
reverses**. The last one is the same run measured in bars instead of true ranges, so it
shares the data, the null and the answer - and the null has an exact closed form, which
is what makes all three decidable rather than arguable.

## How far does it drift before it breaks

Define the run the way a trailing stop does: from the breakout close, in the break's
direction, the **maximum favourable excursion reached before price gives back `GIVEBACK`
true ranges from its running peak**. The run ends when it retraces that much. That is
"how far does the series drift before it breaks", stated so it can be counted.

For driftless Brownian motion this distribution is known exactly, and the derivation is
short enough to keep. Standing at the running maximum with a stop `g` below it, the
probability of advancing a further `dx` before dropping `g` is `g / (g + dx) ≈ 1 - dx/g`.
Multiplying those along the path,

    P(M >= x) = exp(-x / g)

so **the maximum excursion is exponentially distributed with mean exactly `g`**. With a
giveback of one true range, the expected run is 1 TR and the median is `ln 2 = 0.693` TR.

That is the benchmark every row below is measured against, and it is a real one rather
than a fitted one.

## Why the exponential answer settles the second question

**An exponential distribution is memoryless.** Under the null, how much further a move
runs is independent of how far it has already run, of how it started, and of everything
else. So there is nothing to predict - not approximately, but exactly - and any
predictability at all is a departure from memorylessness rather than a matter of degree.

This is a cleaner null than anything else in this repository. It also explains why
measured-move targets keep landing on the fair-odds line in `patterns.md`: a target set as
a multiple of a prior swing is asking the run to remember its own size.

The same memorylessness answers the turning-point question, and answers it in the form a
mean-reversion algorithm actually needs. Under the null the **hazard of reversal is flat**
- the chance of the run ending in the next bar does not depend on how long it has already
lasted - so there is no moment to target. A rising hazard would mean runs exhaust with
age, and that is the one shape that would justify a mean-reversion entry. That column is
printed directly rather than inferred from an average duration, because an average over a
heavy-tailed survival time says very little about the next bar.

## The trap, which is the part worth reading

Predict the excursion **in price units** and a model will score a large out-of-sample
`R²` immediately. That number is worthless. Volatility clusters, so a bar with a wide true
range is followed by wide bars, and any model that has seen recent range will predict a
bigger move in points - which is a restatement of GARCH, already measured in
`vol_baseline.py`, where topology lost to six trailing ratios by 6.8 points.

Dividing the excursion by the true range at entry removes exactly that, and what remains
is the only question a desk cares about: **given what it costs to be wrong, does this
break run further than the next one?** Both targets are reported side by side, because
seeing the price-unit `R²` collapse to nothing when the units change is more convincing
than being told it would.

Scored on purged, embargoed walk-forward folds against a constant predictor, with a
block-shuffled null to price in the multiple comparisons.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import splits  # noqa: E402

#: Bars either side of a pivot, so a swing is knowable only `SWING` bars later.
SWING = 5

#: Giveback that ends the run, in true ranges. This is `g` in the exponential law, so
#: the driftless mean excursion is numerically equal to it.
GIVEBACK = 1.0

#: Bars a run may last before it is called off. The exponential law has an infinite
#: tail, so some cap is needed and it censors the largest runs - which biases every
#: measured mean **downwards**, and therefore cannot manufacture a large-run result.
HORIZON = 192

#: Quantiles reported, against `-g ln(1 - q)` from the exponential law.
QUANTILES = (0.25, 0.5, 0.75, 0.9, 0.95)


def pivots(bars: np.ndarray, k: int = SWING):
    """Running last confirmed swing high and low, delayed by `k` bars."""
    high, low = bars[:, 2], bars[:, 3]
    n = len(bars)
    hi = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    hi_at = np.zeros(n, dtype=int)
    hi_now = lo_now = np.nan
    hi_idx = 0
    for i in range(k, n - k):
        j = i - k
        if j >= k:
            if high[j] >= high[j - k : j + k + 1].max():
                hi_now, hi_idx = float(high[j]), j
            if low[j] <= low[j - k : j + k + 1].min():
                lo_now = float(low[j])
        hi[i], lo[i] = hi_now, lo_now
        hi_at[i] = hi_idx
    return hi, lo, hi_at


def run_length(
    bars: np.ndarray, at: int, side: int, unit: float, horizon: int
) -> tuple[float, int, bool]:
    """Excursion in `unit`s, bars it lasted, and whether it ended rather than censored.

    The peak is tracked bar by bar and the run ends the first time the adverse extreme
    of a bar sits `GIVEBACK` units below it. Within a bar the order of the high and the
    low is unknown, so the **peak is updated after the stop is checked** - the
    pessimistic order, which shortens every run slightly and is the safe direction for
    a study asking whether runs are long.

    The duration is returned because "when does momentum reverse" is this same event read
    as a time rather than a distance, and the censoring flag is returned because a run
    still alive at the horizon must be excluded from the hazard rather than counted as
    having ended there - that mistake would manufacture a spike in the hazard at exactly
    the horizon and it would look like exhaustion.
    """
    high, low, close = bars[:, 2], bars[:, 3], bars[:, 4]
    peak = 0.0
    for step in range(1, horizon + 1):
        i = at + step
        if i >= len(bars):
            return max(peak, 0.0), step, False
        if side > 0:
            adverse = (low[i] - close[at]) / unit
            favour = (high[i] - close[at]) / unit
        else:
            adverse = (close[at] - high[i]) / unit
            favour = (close[at] - low[i]) / unit
        if adverse <= peak - GIVEBACK:
            return max(peak, 0.0), step, True
        peak = max(peak, favour)
    return max(peak, 0.0), horizon, False


def breakouts(bars: np.ndarray, tr: np.ndarray, horizon: int):
    """Every close beyond a confirmed swing extreme, with features and the run length.

    Yields `(at, side, features, run_tr, run_price, bars_lasted, ended)`. `features` is
    everything knowable at the breakout close - the shared 34 from `candles.features` plus
    six describing the break itself, which a generic feature set cannot see.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    hi, lo, hi_at = pivots(bars)
    start = max(SWING * 2, candles.WINDOW + max(candles.SPANS) + 2, candles.GAP_LOOKBACK + 2)

    for at in range(start, len(bars) - horizon):
        here = close[at]
        unit = tr[at] * max(here, 1e-12)
        if unit <= 0:
            continue
        for side in (1, -1):
            level = hi[at] if side > 0 else lo[at]
            prev = hi[at - 1] if side > 0 else lo[at - 1]
            if not (np.isfinite(level) and np.isfinite(prev)):
                continue
            # A break is a close beyond the level whose previous close was not.
            broke = (
                (here > level and close[at - 1] <= level)
                if side > 0
                else (here < level and close[at - 1] >= level)
            )
            if not broke:
                continue
            span = hi[at] - lo[at]
            if not np.isfinite(span) or span <= 0:
                continue

            # Five features about the break, which the generic set cannot express.
            beyond = abs(here - level) / unit
            age = float(at - hi_at[at])
            body = abs(here - bars[at, 1]) / unit
            reach = (high[at] - low[at]) / unit
            # Unfilled three-candle gaps left in the last twelve bars - the
            # "leaves imbalance" condition from `displacement.py`, as a count.
            left = 0
            for j in range(max(at - 12, 2), at + 1):
                if (
                    side > 0
                    and high[j - 2] < low[j]
                    and low[j + 1 : at + 1].min(initial=np.inf) > low[j]
                ) or (
                    side < 0
                    and low[j - 2] > high[j]
                    and high[j + 1 : at + 1].max(initial=-np.inf) < high[j]
                ):
                    left += 1

            base = candles.features(bars, tr, at)
            extra = [beyond, span / unit, age, body, reach, float(left)]
            got, lasted, ended = run_length(bars, at, side, unit, horizon)
            yield at, side, base + extra, got, got * unit, lasted, ended


def hazard(lasted: np.ndarray, ended: np.ndarray) -> None:
    """When momentum reverses, as the per-bar chance of reversing given it has not.

    This is the direct answer to "when does momentum reverse", and it is the right
    statistic rather than the average duration, because an average over a heavy-tailed
    survival time says almost nothing about what to expect next bar.

    Read it as three cases:

    * **flat** - the chance of reversing in the next bar is the same whatever has
      happened, the process is memoryless, and there is no turning point to target;
    * **rising** - runs exhaust with age, which is what a mean-reversion algorithm
      needs to be true and is the case that would justify one;
    * **falling** - survival breeds survival, trends persist, and holding is right.

    Runs still alive at the horizon are **censored, not ended**: they leave the
    denominator when they leave and never enter the numerator. Counting them as
    reversals would put a spike at exactly the horizon and it would read as exhaustion.
    """
    buckets = [(1, 2), (3, 5), (6, 10), (11, 20), (21, 40), (41, 80), (81, 10**9)]
    print(
        "\n  when momentum reverses - per-bar hazard, given the run got that far\n"
        f"  {'bars into the run':<20}{'at risk':>10}{'reversed':>10}{'hazard/bar':>12}"
    )
    for lo, hi in buckets:
        at_risk = int(np.sum(lasted >= lo))
        if at_risk < 50:
            continue
        stopped = int(np.sum(ended & (lasted >= lo) & (lasted <= hi)))
        width = min(hi, int(lasted.max())) - lo + 1
        # Exposure in bar-observations, so the rate is per bar rather than per bucket -
        # otherwise a wide bucket always looks more dangerous than a narrow one.
        exposure = float(np.sum(np.clip(lasted, lo - 1, min(hi, int(lasted.max()))) - (lo - 1)))
        rate = stopped / exposure if exposure > 0 else 0.0
        span = f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
        print(f"  {span:<20}{at_risk:>10,}{stopped:>10,}{rate:>12.3f}   (width {width})")
    print(
        "  A flat column is memorylessness and means no turning point can be timed.\n"
        "  A rising one is exhaustion and is the only case that justifies a\n"
        "  mean-reversion entry; a falling one says hold."
    )


def describe(symbol: str, runs: np.ndarray) -> None:
    """Measured excursion quantiles against the exponential law."""
    if not len(runs):
        return
    line = f"  {symbol:<24}{len(runs):>8,}{runs.mean():>9.2f}"
    for q in QUANTILES:
        line += f"{np.quantile(runs, q):>9.2f}"
    print(line)


def fit(x: np.ndarray, y: np.ndarray, when: np.ndarray, horizon: int, label: str) -> None:
    """Out-of-sample `R²` and rank correlation against a constant predictor.

    ## Normalisation, and where it can and cannot matter

    Four scalings are swept - none, z-score, min-max and a robust median/IQR one - and
    every one of them is **fitted on the training fold only** and then applied to the
    test fold. That is not pedantry: fitting a scaler on all the data first lets the test
    window's mean and spread into the training set, and it is the most common way a
    walk-forward result turns out to be nothing.

    The sweep is worth running for `ridge`, where it decides the answer. A linear model
    penalises coefficients, so a feature measured in thousands is shrunk differently from
    one measured in hundredths, and min-max in particular is at the mercy of a single
    outlier deciding the whole range.

    **For the trees it cannot matter, and that is a fact rather than an expectation.** A
    tree splits on `feature <= threshold`, and every scaling here is monotone, so the same
    rows land on the same side of every split and the fitted tree is identical. It is
    still swept, because it costs little and four identical numbers confirm the reasoning
    while four different ones would mean a bug - which is the more useful outcome.
    """
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler
    except ImportError:
        print("  scikit-learn is not installed - skipping the predictive half")
        return
    from scipy.stats import spearmanr

    models = {
        "ridge": lambda: Ridge(alpha=10.0),
        "trees": lambda: HistGradientBoostingRegressor(
            max_depth=4, max_iter=200, learning_rate=0.05, random_state=0
        ),
    }
    scalings = {
        "none": None,
        "z-score": StandardScaler,
        "min-max": MinMaxScaler,
        "robust": RobustScaler,
    }
    shuffled = splits.block_shuffle(y, when, horizon, seed=0)

    for name, make in models.items():
        for scale, maker in scalings.items():
            for tag, target in (("real", y), ("shuffled null", shuffled)):
                scores, rhos = [], []
                for train, test in splits.walk_forward(when, horizon, folds=5):
                    # Fitted on train only. See the docstring - this one line is the
                    # difference between a walk-forward and a leak.
                    if maker is None:
                        xt, xv = x[train], x[test]
                    else:
                        scaler = maker().fit(x[train])
                        xt, xv = scaler.transform(x[train]), scaler.transform(x[test])
                    model = make().fit(xt, target[train])
                    pred = model.predict(xv)
                    truth = target[test]
                    # R² against the **training** mean, not the test mean: a model that
                    # only knew the past cannot centre on a window it has not seen, and
                    # scoring against the test mean quietly credits it with that.
                    base = float(target[train].mean())
                    denom = float(((truth - base) ** 2).sum())
                    if denom <= 0:
                        continue
                    scores.append(1.0 - float(((truth - pred) ** 2).sum()) / denom)
                    if np.std(pred) > 0:
                        rhos.append(float(spearmanr(pred, truth).statistic))
                if scores:
                    rank = np.mean(rhos) if rhos else 0.0
                    print(
                        f"  {label:<18}{name:<7}{scale:<9}{tag:<15}"
                        f"R2 {np.mean(scores):>+7.3f}   rank {rank:>+6.3f}"
                        f"   over {len(scores)} folds"
                    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[
            "xauusd",
            "eurusd",
            "gbpusd",
            "usdjpy",
            "boom_1000_index",
            "crash_1000_index",
            "volatility_75_index",
        ],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    args = ap.parse_args()

    print(
        f"run ends on a giveback of {GIVEBACK:g} true range, so the driftless law is\n"
        f"exponential with mean {GIVEBACK:g} - shown on the last line for comparison\n"
        f"\n  {'instrument':<24}{'n':>8}{'mean':>9}"
        + "".join(f"{f'q{q:.2f}':>9}" for q in QUANTILES)
    )

    rows_x: list[list[float]] = []
    rows_tr: list[float] = []
    rows_price: list[float] = []
    rows_when: list[int] = []
    rows_lasted: list[int] = []
    rows_ended: list[bool] = []
    offset = 0

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<24} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < args.horizon + 2000:
            continue
        tr = candles.true_range(bars)
        runs = []
        for at, _side, feats, got, price, lasted, ended in breakouts(bars, tr, args.horizon):
            runs.append(got)
            rows_x.append(feats)
            rows_tr.append(got)
            rows_price.append(price)
            rows_when.append(offset + at)
            rows_lasted.append(lasted)
            rows_ended.append(ended)
        offset += len(bars) + args.horizon
        describe(symbol, np.array(runs))

    theory = [-GIVEBACK * np.log(1 - q) for q in QUANTILES]
    print(
        f"  {'exponential law':<24}{'-':>8}{GIVEBACK:>9.2f}" + "".join(f"{t:>9.2f}" for t in theory)
    )
    print(
        "\n  A mean and quantiles matching that last line mean breakouts run exactly as\n"
        "  far as a coin-flipping series does, and the exponential is memoryless, so\n"
        "  there is then nothing about the size of the run left to predict."
    )

    hazard(np.array(rows_lasted), np.array(rows_ended, dtype=bool))

    if len(rows_x) < 2000:
        print("\nnot enough breakouts to fit anything")
        return 0

    x = np.nan_to_num(np.array(rows_x, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    when = np.array(rows_when)
    print(f"\n{len(x):,} breakouts, {x.shape[1]} features, purged walk-forward")
    print("scalers are fitted on the training fold only\n")
    fit(x, np.array(rows_tr), when, args.horizon, "size, true range")
    print()
    fit(x, np.array(rows_lasted, dtype=float), when, args.horizon, "duration, bars")
    print()
    fit(x, np.array(rows_price), when, args.horizon, "size, price units")
    print(
        "\n  The price-unit rows are the control, and they are expected to score well\n"
        "  for a reason that is no use: volatility clusters, so recent range predicts\n"
        "  future range. Only the true-range rows answer the question that was asked.\n"
        "\n  The duration rows are the turning-point question: a model that cannot beat\n"
        "  a constant at guessing how long a run lasts is telling you the reversal is\n"
        "  not timeable, which is the same thing the hazard column says directly."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
