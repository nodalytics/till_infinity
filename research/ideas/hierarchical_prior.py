"""Pooling per-instrument parameters, with the pooling strength estimated.

`statespace/__init__` maps prod's `kNN neighbours + K = 150 shrinkage` to a
**hierarchical prior over level parameters** and makes it Phase 1 of the plan,
with the null named: the fixed `K`, scored on held-out data. It has never been
built. This builds the member-parameter version of it.

## Why it is the right import, and the evidence is this session's own

Every member here fits its parameters **per instrument from a grid**, and grid
edges have turned up in nearly every harness: `theta` at 1e-10 and at 2000,
`sigma2` at both ends, `kappa` at 50, `jerk` on its floor in 9 of 10 cells, the
best `nu` at 200. A parameter pinned to the edge of its grid is an estimate
whose uncertainty exceeded its range, and the session has been reporting those
point estimates as if they were measurements.

The same defect appeared four times in four different clothes:

* the relationship screen's **live hedge ratio**, re-estimated every bar, which
  manufactured a Dickey-Fuller `t` of -29 from independent noise;
* the barrier duration's **entry volatility**, where 70% of the conditional
  bias was regression in the estimate and the fix was `w = 0.5` shrinkage;
* prod's **`probability_up`**, which ranks at AUC 0.6365 and needs its distance
  from 0.5 multiplied by 0.47;
* prod's own **`PRIOR_WEIGHT = 4.0`**, an unestimated guess at exactly this
  quantity, which `structures/shrinkage.py` exists to replace.

Shrinkage is one fix for all four.

## The estimator is prod's, with the pool changed

`structures/shrinkage.py` uses **DerSimonian and Laird's method of moments**,
and states the thing that makes it a method rather than a gesture: the observed
spread of per-group estimates *already contains* the sampling noise, so it
always overstates the real between-group variance, and **subtracting that noise
is the whole method.**

    tau^2 = max(0, weighted spread of estimates - mean sampling variance)
    B_i   = tau^2 / (tau^2 + s_i^2)

`B_i` near 1 keeps an instrument's own estimate; near 0 pools it. The pool here
is **instruments** rather than levels, and prod's caveat carries over exactly:
the estimate needs enough *instruments*, not more bars per instrument.

## A grid edge becomes maximal shrinkage instead of a silent artefact

`s_i^2` comes from the curvature of the log-likelihood at its peak - a parabola
through the grid, so `s^2 = -h^2 / (ll[i-1] - 2 ll[i] + ll[i+1])` in log-
parameter units. **When the peak sits on a grid edge there is no curvature to
read, and the honest reading is infinite uncertainty**, which sends `B_i` to
zero and pools that instrument completely.

That is the right behaviour and it is the point: the cells this session kept
flagging as grid-edge artefacts become the cells that borrow most from their
neighbours, automatically, rather than being reported as fits.

## The synthetics are the test instrument, not just a control

Their heterogeneity is **known by construction**, which is what an estimator of
heterogeneity needs:

* `Volatility_10/25/50/75/100_Index` are the same process at volatilities that
  differ by a factor of ten, so their `sigma2` genuinely differs by a hundred.
  The estimator **must** report large `tau^2` and refuse to pool. If it pools
  them it is broken.
* `Volatility_75_Index` and `Volatility_75_1s_Index` are plausibly one process
  sampled at two rates, so their parameters should agree and pooling should
  cost nothing.

A shrinkage estimator that cannot tell those two cases apart is not measuring
heterogeneity, it is just averaging.

## What the numbers said

The estimator passes both tests and the import is a null.

It tells the two synthetic cases apart: arm 1 reports `tau^2 = 3.718` with
every `B = 1.00` and fitted values ordered `1e-07` to `1e-05` with the
volatility, and arm 2 **reproduces the sampling-rate pairing it was never told
about** - both 75s at `1e-05`, both 25s at `1e-06`. Pooling costs `-251.5` and
`-320.1` respectively.

On the 14 traded instruments: `tau^2 = 2.859`, **every `B = 1.00`**, median
held-out gain from shrinking **-0.2** and from pooling completely **-373.7**.
Shrinking helps 3 of 14, pooling helps 0 of 14.

**And no instrument sat on a grid edge**, which withdraws the motivation above.
`sd(log)` is `0.04` to `0.05` on all 23 instruments across all three arms,
independent of the fitted value, because for a scale parameter
`sd(log q) ~= sqrt(2/n)` - a function of the sample size alone. Against a
between-instrument spread of `2.6` in log units that gives `tau^2/s^2 ~ 1100`.

The fits are sharp, the parameters genuinely differ, and there is nothing to
borrow. **A hierarchical prior pays when the per-group sample is small**, and a
member parameter fitted on tens of thousands of bars is not that. Prod's
level statistics, touched a handful of times each, are.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.linear import Gaussian
from till_infinity.statespace.reverting import Reverting

HOUR = 3600.0
SEED = 20261013

TRADED = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "NZDUSD", "AUDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD",
)
#: Volatilities differing by a factor of ten, so `sigma2` differs by a hundred.
#: The estimator must refuse to pool these.
SPREAD_OUT = (
    "Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index",
    "Volatility_75_Index", "Volatility_100_Index",
)
#: Plausibly one process at two sampling rates, so pooling should be free.
TOGETHER = (
    "Volatility_75_Index", "Volatility_75_1s_Index",
    "Volatility_25_Index", "Volatility_25_1s_Index",
)

FRAME = os.environ.get("FRAME", "1h")
#: Log-spaced, and the spacing matters: the curvature is read in these units.
POWERS = tuple(range(-9, 2))
GRID = tuple(10.0**k for k in POWERS)
STEP = math.log(10.0)
MEMBER = os.environ.get("MEMBER", "kalman")
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "20000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str = FRAME):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
    keep = (closes > 0) & (times >= SINCE)
    times, closes = times[keep], closes[keep]
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return (times.tolist(), np.log(closes).tolist()) if len(times) > 4000 else None


def build(value: float):
    if MEMBER == "kalman":
        return Gaussian(jerk=value, p00=1.0)
    return Reverting(sigma2=value, theta=0.5)


def score(times, levels, value: float, noise: float, lo: int, hi: int) -> tuple[float, int]:
    """Log-likelihood over `[lo, hi)`, warmed up on everything before `lo`."""
    member = build(value)
    for i in range(lo):
        member.update(levels[i], noise, times[i])
    member.loglike = 0.0
    member.burn = 0
    counted = 0
    for i in range(lo, hi):
        before = member.loglike
        member.update(levels[i], noise, times[i])
        if not math.isfinite(member.value) or not math.isfinite(member.sd):
            return -math.inf, counted
        if member.loglike != before:
            counted += 1
    if not math.isfinite(member.loglike):
        return -math.inf, counted
    return member.loglike, counted


def fit_one(times, levels):
    """Per-instrument estimate, its curvature standard error, and the held-out score.

    Fitted on the first half, curvature read on the same half, and the held-out
    half kept untouched for scoring - so the shrinkage comparison later is on
    data no arm has seen.
    """
    noise = (
        0.25
        * statistics.pstdev([levels[i] - levels[i - 1] for i in range(1, min(len(levels), 3000))])
        ** 2
    )
    half = len(levels) // 2
    curve = []
    for value in GRID:
        got, _n = score(times, levels, value, noise, 0, half)
        curve.append(got)
    best = max(range(len(curve)), key=lambda i: curve[i])
    on_edge = best in (0, len(curve) - 1)
    if on_edge:
        # No curvature to read, so the honest variance is infinite and this
        # instrument pools completely.
        variance = math.inf
    else:
        second = curve[best - 1] - 2.0 * curve[best] + curve[best + 1]
        variance = (-STEP * STEP / second) if second < 0 else math.inf
    return {
        "log_value": math.log(GRID[best]),
        "value": GRID[best],
        "variance": variance,
        "on_edge": on_edge,
        "noise": noise,
        "half": half,
    }


def dersimonian_laird(estimates, variances):
    """`tau^2` by method of moments: the observed spread **minus** sampling noise.

    Prod's `structures/shrinkage.py` states why the subtraction is the method:
    the spread of the estimates already contains their own noise, so taking it
    directly always overstates the real between-group variance.

    Instruments whose variance is infinite - a grid edge - carry no information
    about heterogeneity and are left out of `tau^2` while still receiving a
    shrunk estimate.
    """
    usable = [(e, v) for e, v in zip(estimates, variances, strict=True) if math.isfinite(v) and v > 0]
    if len(usable) < 4:
        return 0.0, statistics.fmean(estimates), len(usable)
    weights = [1.0 / v for _e, v in usable]
    total = sum(weights)
    pooled = sum(w * e for w, (e, _v) in zip(weights, usable, strict=True)) / total
    q = sum(w * (e - pooled) ** 2 for w, (e, _v) in zip(weights, usable, strict=True))
    squares = sum(w * w for w in weights)
    denominator = total - squares / total
    tau2 = max(0.0, (q - (len(usable) - 1)) / denominator) if denominator > 0 else 0.0
    return tau2, pooled, len(usable)


def report(label: str, names: list[str]) -> None:
    fits, series = {}, {}
    for name in names:
        found = load(name)
        if found is None:
            continue
        series[name] = found
        fits[name] = fit_one(*found)
    if len(fits) < 3:
        print(f"{label}: too few instruments loaded")
        return

    estimates = [fits[n]["log_value"] for n in fits]
    variances = [fits[n]["variance"] for n in fits]
    tau2, pooled, usable = dersimonian_laird(estimates, variances)
    spread = statistics.pvariance(estimates) if len(estimates) > 1 else 0.0

    print(f"\n--- {label}: {len(fits)} instruments, {usable} with readable curvature ---")
    print(
        f"observed spread of log estimates {spread:.3f}, "
        f"tau^2 after subtracting sampling noise {tau2:.3f}, "
        f"pooled estimate {math.exp(pooled):.2e}"
    )
    print(
        f"\n{'instrument':<24}{'own fit':>10}{'edge':>6}{'sd(log)':>9}{'B':>7}"
        f"{'shrunk':>11}{'own held':>11}{'shrunk held':>13}{'pooled held':>13}"
    )
    gains, pooled_gains = [], []
    for name, got in fits.items():
        variance = got["variance"]
        weight = 0.0 if not math.isfinite(variance) else tau2 / (tau2 + variance)
        shrunk = math.exp(weight * got["log_value"] + (1.0 - weight) * pooled)
        times, levels = series[name]
        own, n_own = score(times, levels, got["value"], got["noise"], got["half"], len(levels))
        new, n_new = score(times, levels, shrunk, got["noise"], got["half"], len(levels))
        full, n_full = score(times, levels, math.exp(pooled), got["noise"], got["half"], len(levels))
        if not (n_own == n_new == n_full) or not all(map(math.isfinite, (own, new, full))):
            continue
        gains.append(new - own)
        pooled_gains.append(full - own)
        print(
            f"{name:<24}{got['value']:>10.0e}{'*' if got['on_edge'] else '':>6}"
            + (f"{math.sqrt(variance):>9.2f}" if math.isfinite(variance) else f"{'inf':>9}")
            + f"{weight:>7.2f}{shrunk:>11.0e}{own:>11.0f}{new:>13.0f}{full:>13.0f}"
        )
    if gains:
        print(
            f"\nmedian held-out gain from shrinking: {statistics.median(gains):+.1f}; "
            f"from pooling completely: {statistics.median(pooled_gains):+.1f}"
        )
        print(
            f"shrinking helps {sum(1 for g in gains if g > 0)} of {len(gains)}; "
            f"full pooling helps {sum(1 for g in pooled_gains if g > 0)} of {len(pooled_gains)}"
        )


def main() -> None:
    print(
        f"member {MEMBER}, frame {FRAME}, grid 1e{POWERS[0]} to 1e{POWERS[-1]}\n"
        "`B` is the weight on an instrument's own estimate: 1 keeps it, 0 pools\n"
        "it. `edge` marks a fit pinned to the grid's end, where there is no\n"
        "curvature to read - infinite variance, so it pools completely.\n"
        "Held-out columns are the second half, which no arm was fitted on.\n"
    )
    print("=" * 116)
    print("ARM 1  known heterogeneity: volatilities a factor of ten apart")
    print("=" * 116)
    print(
        "`sigma2` differs by a hundred across these by construction, so the\n"
        "estimator must report a large tau^2 and refuse to pool. If it pools\n"
        "them, it is averaging rather than measuring heterogeneity."
    )
    report("Volatility 10 to 100", list(SPREAD_OUT))

    print("\n" + "=" * 116)
    print("ARM 2  known agreement: the same index at two sampling rates")
    print("=" * 116)
    print("Pooling should cost nothing here, and B should be small.")
    report("Volatility 75 and 25, both rates", list(TOGETHER))

    print("\n" + "=" * 116)
    print("ARM 3  the traded universe, which is the question")
    print("=" * 116)
    report("traded", list(TRADED))
    print("\nDONE")


if __name__ == "__main__":
    main()
