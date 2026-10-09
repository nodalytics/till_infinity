"""Do levels differ in how tightly price touches them, or only pools?

The conformal calibrator estimates `q` per `(feed, interval, side)` - how many
sigmas that **pool** actually needs - and the pools say the instrument's
volatility systematically overstates touch dispersion: 97.6-98.6% coverage
against a 90% target (`level-filters.md`).

That is a pool-wide correction. The open question is whether **levels differ
from each other** beyond it, because that decides whether a per-level width can
exist at all:

* if the true spread between levels is near zero, levels are interchangeable,
  the pool estimate is the whole story, and a per-level multiplier would be
  fitting noise
* if it is not, each level should carry its own width, shrunk toward its pool
  by `shrinkage.prior_weight`

**This measures the spread before anything is built**, which is the cheap half
of the question and the half that can say no.

## Why log dispersion

A level's own dispersion is a variance estimated from a handful of touches, and
the sampling error of a variance depends on its size - which makes the spread
of raw dispersions uninterpretable. On the log scale that error is free of the
mean, so the method-of-moments subtraction below compares like with like:

    x_i   = log(dispersion of level i, in volatility units)
    var_i = trigamma((n_i - 1) / 2) / 4        # exact for a normal sample
    tau^2 = max(0, weighted Var(x) - mean(var_i))

The same DerSimonian and Laird move `shrinkage.py` makes for rates: the
observed spread contains the sampling noise, and subtracting it is the method
rather than a refinement.

**The exact variance, not the asymptotic `1 / (2 * (n - 1))`.** That
approximation is what this was written with first, and on a synthetic pool of
*identical* levels at six touches each it reported `tau = 0.114` - "a loose
level is 1.34x a tight one" - for levels that were the same. At `n = 6` the
true variance of `log s` is 0.1226 against the approximation's 0.100, and the
missing 0.023 comes back out as spread. The null case caught it; the real data
would have looked like a finding.

## What the answer looks like

`tau` is a spread of logs, so the interpretable form is the ratio between a
tight level and a loose one:

    spread = exp(2 * 1.2816 * tau)      # p90 / p10

**At 1.0 there is no feature.** Much above it and a per-level width is worth
the machinery.

  MT5BT_DB=... INTERVALS=1h,4h,1d python research/ideas/level_dispersion.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

INTERVALS = os.environ.get("INTERVALS", "1h,4h,1d").split(",")
CLUSTER_VOL = float(os.environ.get("CLUSTER_VOL", 0.75))
#: Touches a level needs for its own dispersion to be worth estimating. Four
#: gives three degrees of freedom, which is thin and is the point - this is the
#: regime the real book is in.
MIN_TOUCHES = int(os.environ.get("MIN_TOUCHES", 5))
#: Levels a pool needs before its spread is reported.
MIN_LEVELS = int(os.environ.get("MIN_LEVELS", 30))


def trigamma(x: float) -> float:
    """`psi'(x)`, by recurrence onto the asymptotic tail.

    Exact enough well past what this needs, and here rather than from scipy
    because this repository does not depend on scipy and one series is cheaper
    than one dependency.
    """
    total = 0.0
    while x < 6.0:
        total += 1.0 / (x * x)
        x += 1.0
    inv = 1.0 / x
    inv2 = inv * inv
    return total + inv * (1.0 + inv / 2.0 + inv2 * (1.0 / 6.0 - inv2 / 30.0))


def log_sd_variance(n: int) -> float:
    """Sampling variance of `log s` for a normal sample of size `n`.

    `s**2` is `sigma**2 * chi2(n-1) / (n-1)`, so `log s` has variance
    `trigamma((n-1)/2) / 4` - which is **not** `1 / (2 * (n - 1))` at the
    sample sizes a level actually gets. See the module docstring.
    """
    return trigamma((n - 1) / 2.0) / 4.0 if n > 1 else float("inf")


def pivots(high: np.ndarray, low: np.ndarray) -> list[tuple[int, float]]:
    out = []
    for i in range(1, len(high) - 1):
        if high[i] >= high[i - 1] and high[i] >= high[i + 1]:
            out.append((i, float(high[i])))
        elif low[i] <= low[i - 1] and low[i] <= low[i + 1]:
            out.append((i, float(low[i])))
    return out


def cluster(points, unit: float):
    if unit <= 0:
        return []
    groups: list[list[tuple[int, float]]] = []
    for i, price in sorted(points, key=lambda p: p[1]):
        if groups and abs(price - np.mean([p for _, p in groups[-1]])) <= CLUSTER_VOL * unit:
            groups[-1].append((i, price))
        else:
            groups.append([(i, price)])
    return [sorted(g) for g in groups if len(g) >= MIN_TOUCHES]


def spread_between(samples: list[tuple[int, float]]) -> tuple[float, float, int]:
    """`(tau, tau over its own error, levels)` for one pool of `(n, log s)`."""
    usable = [(n, x) for n, x in samples if n >= 3 and math.isfinite(x)]
    if len(usable) < MIN_LEVELS:
        return float("nan"), float("nan"), len(usable)
    # Each level weighted by its own precision, which is what makes the
    # subtraction below a comparison of like with like.
    weights = [1.0 / log_sd_variance(n) for n, _ in usable]
    total = sum(weights)
    mean = sum(w * x for w, (_, x) in zip(weights, usable, strict=True)) / total
    q = sum(w * (x - mean) ** 2 for w, (_, x) in zip(weights, usable, strict=True))
    spread_sq = sum(w * w for w in weights)
    divisor = total - spread_sq / total
    if divisor <= 0:
        return 0.0, 0.0, len(usable)
    tau_sq = max(0.0, (q - (len(usable) - 1)) / divisor)
    tau = math.sqrt(tau_sq)
    # Its own standard error, roughly, so "near zero" can be told from "small".
    err = math.sqrt(2.0 / max(len(usable) - 1, 1)) * max(tau, 1e-9)
    return tau, (tau / err if err > 0 else 0.0), len(usable)


def main() -> None:
    import run as runner
    import survivors

    from till_infinity.structures.vol.volatility import Volatility

    runner.DB = survivors.DB = os.environ.get("MT5BT_DB")
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in runner.FAMILY if s not in runner.FRESH]

    pools: dict[str, list[tuple[int, float]]] = {}
    levels = 0
    for iv in INTERVALS:
        for sym in syms:
            got = survivors.book_for(sym, iv)
            if got is None:
                continue
            df = got[0].bars.reset_index(drop=True)
            if len(df) < 300:
                continue
            close = df["close"].to_numpy(float)
            vol = Volatility()
            for price in close:
                vol.update(float(price))
            unit = vol.price_units(float(close[-1]), 1.0)
            if not unit or unit <= 0:
                continue
            found = cluster(pivots(df["high"].to_numpy(float), df["low"].to_numpy(float)), unit)
            for group in found:
                prices = np.array([p for _, p in group], float)
                levels += 1
                # Dispersion of this level's own touches, in volatility units.
                sd = float(prices.std(ddof=1)) / unit
                if sd <= 0:
                    continue
                pools.setdefault(iv, []).append((len(prices), math.log(sd)))

    rows = []
    for iv, samples in sorted(pools.items()):
        tau, ratio, n = spread_between(samples)
        if not math.isfinite(tau):
            continue
        rows.append(
            {
                "iv": iv,
                "levels": n,
                "median_dispersion_vol": float(np.exp(np.median([x for _, x in samples]))),
                "tau": tau,
                "tau_over_error": ratio,
                "p90_over_p10": math.exp(2 * 1.2816 * tau),
            }
        )
    t = pd.DataFrame(rows)
    if t.empty:
        print("not enough levels")
        return
    pd.set_option("display.width", 200)
    print(f"{levels} levels, {MIN_TOUCHES}+ touches each\n")
    print("`tau` is the spread of log dispersion between levels once each level's own")
    print("sampling error is subtracted. `p90_over_p10` is what that means: how much")
    print("looser a loose level is than a tight one.\n")
    print(t.round(4).to_string(index=False))
    print("\n=== does a per-level width have anything to estimate? ===")
    for _, r in t.iterrows():
        verdict = (
            "no - levels are interchangeable, the pool is the whole story"
            if r.p90_over_p10 < 1.15
            else f"yes - a loose level is {r.p90_over_p10:.2f}x a tight one"
        )
        print(f"  {r.iv}: {verdict}")
    out = Path(os.environ.get("OUT", ".data/dispersion"))
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "spread.csv", index=False)
    print(f"\nwritten: {out / 'spread.csv'}")


if __name__ == "__main__":
    main()
