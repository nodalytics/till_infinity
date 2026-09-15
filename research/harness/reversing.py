"""When a trend reverses, is the depth of what follows predictable at the time?

**Not whether a reversal can be called.** That is closed:
`research/deriving.md` proves `E[net] = -(c/2) x turnover` for any predictable
position on a martingale, and `research/sequencing.md` measured direction at AUC
**0.50150** over 7,728,858 test rows with the phase surrogate scoring *higher*.
Asking it again would be re-running a settled null.

**The open question is depth.** A reversal has happened; the question is how far
it goes. That is the number a stop and a target are made of, and
`research/spending.md`'s conclusion is that the desk's weakness is its
conditional estimates rather than its direction calls. `deriving.md` does not bar
it: a conditional estimate of magnitude is not a predictable position.

Two results from this week make it worth asking now rather than in general.

* `research/retracing.md` measured the unconditional retracement at **0.982** on
  real feeds against **1.000** on the generated family and 0.996 to 1.008 on
  matched Brownian - and found alpha **does not move**, block to block, beyond
  its own null. So there is no *state* to track. Whether there is *conditional*
  structure is a different question and this is it.
* `research/families.md` found Range Break at direction AUC **0.6627**, invisible
  to lag-1 autocorrelation (+0.0008) and to a phase surrogate (0.4956), because
  the structure was conditional on **position within a band**. The lesson is that
  the conditioning variable was the whole finding, so one is included here.

## The causality that decides whether any of this means anything

**A zigzag turn is not known at the extreme. It is known at confirmation**, when
price has moved `theta` against it - which is bars later and at a different
price. Building features at the extreme would hand the model the knowledge that
this bar was a turn, which is precisely the thing it would have to predict.

So every feature is read at the **confirmation bar**, and the target is measured
from there forward. At that moment the completed leg is genuinely known and the
correction is genuinely unfinished, which is the real decision point: it is when
a desk would be sizing the trade it is already in.

## The answer, 2026-09-15

**Yes, modestly, and only on real markets.** Out-of-sample AUC for deep-versus-
shallow on a forward split, 60 cells across twenty real feeds and three
timeframes:

| arm | cells | rows | AUC | above 0.5 | t |
| --- | --- | --- | --- | --- | --- |
| **real, feed** | 60 | 75,348 | **0.5349** | **58 / 60** | **12.39** |
| real, surrogate | 60 | 107,176 | 0.5021 | 35 / 60 | 0.98 |
| real, gbm | 60 | 106,938 | 0.5017 | 33 / 60 | 1.15 |
| real, shuffle | 60 | 80,169 | 0.5032 | 38 / 60 | 1.66 |
| volatility, feed | 34 | 43,004 | 0.4968 | 14 / 34 | -0.94 |
| volatility, gbm | 34 | 42,975 | 0.5012 | 18 / 34 | 0.33 |

Three and a half points of AUC, on 58 of 60 cells, against three controls that
all sit on the floor and a generated family that is flat. It is a **magnitude**
estimate rather than a direction call, so `deriving.md`'s theorem does not bar
it, and `spending.md` says conditional estimates are where this desk is weak.

**Whether it clears the spread is not measured here and should not be assumed.**
An AUC is not money - `research/policies.md` priced that distinction on this
book, where a 0.619 filter cleared 0.103 to 0.692 of the quoted spread.

## Controls

`shuffle` on the target, `surrogate` through `seqlab.surrogate_bars`, a matched
`gbm`, and the **generated family**, which cannot have conditional structure -
`generated.md` has it at `H = 0.50`. Anything found there is the procedure.

    ./.secrets/lab.sh run research/harness/reversing.py
"""

from __future__ import annotations

import math
import sys

import numpy as np

from research.harness import seqlab

#: Zigzag threshold in per-bar sigma, and the timeframes to ask on.
THETA = 2.0
GRID = ("15m", "1h", "4h")

#: Lookback for the position-in-range feature - the `families.md` lesson.
BAND = 100

#: Fewest completed turns in a cell before it is scored.
FEWEST = 120


def turns_with_confirmation(prices: np.ndarray, theta: float) -> list[tuple[int, int]]:
    """Alternating extremes as `(extreme index, confirmation index)`.

    The second element is the whole point: a turn at bar `i` is not *known* at
    bar `i`. It becomes known when price has moved `theta` against it, which is
    later and at a different price, and every feature here is read there.
    """
    n = len(prices)
    if n < 3 or theta <= 0:
        return []
    out: list[tuple[int, int]] = []
    hi = lo = float(prices[0])
    hi_at = lo_at = 0
    direction = 0
    for i in range(1, n):
        p = float(prices[i])
        if direction >= 0 and p > hi:
            hi, hi_at = p, i
        if direction <= 0 and p < lo:
            lo, lo_at = p, i
        if direction >= 0 and p <= hi - theta:
            out.append((hi_at, i))
            direction, lo, lo_at = -1, p, i
        elif direction <= 0 and p >= lo + theta:
            out.append((lo_at, i))
            direction, hi, hi_at = 1, p, i
    return out


def build(prices: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
    """Features at confirmation, and how much FURTHER the correction then runs.

    **Two earlier versions of this scored 0.78 and then 0.85 on simulated
    Brownian motion**, and the controls are the only reason either was caught.
    Both faults are ones this folder already has names for, and both are worth
    keeping because the second survived a fix aimed at the first.

    *Look-ahead* (first version). The target was the leg **after** the
    correction and a feature was the correction itself, which is not finished at
    confirmation.

    *A shared term* (first version). Target `|following| / |correction|` against
    feature `|correction| / |leg|` - the same quantity as a numerator in one and
    a denominator in the other, anti-correlated whatever the data. `predictable.py`
    names this: a variable scored against itself is an identity.

    *A bounded target* (second version, and the subtler one). The target became
    this correction's **total** depth, and a feature was how far it had already
    travelled by confirmation. But the distance already travelled is a **lower
    bound** on the total - a correction that has gone three sigma cannot end
    under three - so the feature did not predict the target, it partly *was* the
    target. The AUC went up to 0.85 precisely because the fix had made the
    relationship cleaner.

    So the target here is the **additional** distance past the confirmation
    price, which nothing known bounds, and the distance already travelled is a
    feature of it rather than a component of it. That is also the question a desk
    actually has at that moment: it is already in the trade, and what it needs is
    how much further this goes.
    """
    marks = turns_with_confirmation(prices, THETA * sigma)
    if len(marks) < 5:
        return np.empty((0, 0)), np.empty(0), ()

    names = (
        "leg_size",
        "leg_bars",
        "leg_speed",
        "travelled",
        "leg_ratio",
        "band_pos",
        "vol_ratio",
        "direction",
        "confirm_bars",
    )
    rows, targets = [], []
    for k in range(3, len(marks)):
        two_back, _ = marks[k - 3]
        one_back, _ = marks[k - 2]
        this_at, confirmed = marks[k - 1]
        next_at, _ = marks[k]
        if next_at <= confirmed:
            continue

        leg = prices[this_at] - prices[one_back]
        older = prices[one_back] - prices[two_back]
        if leg == 0 or older == 0:
            continue

        # **How much further, from where we stand.** Nothing known bounds this:
        # the correction may end at the next bar or run for many more.
        further = abs(prices[next_at] - prices[confirmed]) / sigma

        lo = max(0, confirmed - BAND)
        window = prices[lo : confirmed + 1]
        span = float(window.max() - window.min())
        realised = float(np.std(np.diff(window), ddof=1)) if confirmed - lo > 2 else sigma
        rows.append(
            [
                abs(leg) / sigma,
                float(this_at - one_back),
                abs(leg) / max(this_at - one_back, 1) / sigma,
                # A feature of the target now, not a component of it.
                abs(prices[confirmed] - prices[this_at]) / sigma,
                abs(leg) / abs(older),
                (prices[confirmed] - window.min()) / span if span > 0 else 0.5,
                realised / sigma if sigma > 0 else 1.0,
                1.0 if leg > 0 else -1.0,
                float(confirmed - this_at),
            ]
        )
        targets.append(further)

    if len(rows) < FEWEST:
        return np.empty((0, 0)), np.empty(0), names
    x = np.asarray(rows, dtype=float)
    y = np.asarray(targets, dtype=float)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
    return x[ok], y[ok], names


def cell(prices: np.ndarray, sigma: float, rng) -> dict:
    """Out-of-sample AUC for deep-vs-shallow, on a forward split."""
    x, y, _ = build(prices, sigma)
    if len(y) < FEWEST:
        return {}
    half = len(y) // 2
    cut = float(np.median(y[:half]))
    deep_train = (y[:half] > cut).astype(float)
    deep_test = (y[half:] > cut).astype(int)
    if deep_test.min() == deep_test.max():
        return {}

    mu = x[:half].mean(axis=0)
    sd = x[:half].std(axis=0)
    sd[sd == 0] = 1.0
    train = (x[:half] - mu) / sd
    test = (x[half:] - mu) / sd
    # Ridge on the standardised features - the shared linear floor, fitted on
    # train only, exactly as `seqlab.ridge` does it for the other arms.
    lam = 1.0
    gram = train.T @ train + lam * np.eye(train.shape[1])
    weights = np.linalg.solve(gram, train.T @ (deep_train - deep_train.mean()))
    return {
        "n": int(len(deep_test)),
        "auc": seqlab.auc(test @ weights, deep_test),
    }


def fit_auc(x: np.ndarray, y: np.ndarray, keep: list[int] | None = None) -> float:
    """Out-of-sample AUC on a forward split, optionally on a subset of columns."""
    cols = list(range(x.shape[1])) if keep is None else keep
    if not cols:
        return float("nan")
    half = len(y) // 2
    cut = float(np.median(y[:half]))
    train_y = (y[:half] > cut).astype(float)
    test_y = (y[half:] > cut).astype(int)
    if test_y.min() == test_y.max():
        return float("nan")
    a, b = x[:half][:, cols], x[half:][:, cols]
    mu, sd = a.mean(axis=0), a.std(axis=0)
    sd[sd == 0] = 1.0
    a, b = (a - mu) / sd, (b - mu) / sd
    gram = a.T @ a + np.eye(len(cols))
    weights = np.linalg.solve(gram, a.T @ (train_y - train_y.mean()))
    return seqlab.auc(b @ weights, test_y)


def importance(symbols: list[str]) -> dict:
    """Which feature carries the edge, by dropping it and by using it alone.

    **Drop-one rather than coefficients**, which is `research/features.py`'s
    method and its reasoning: reading weights off a fitted model measures the
    model as much as the feature, and a ridge on correlated columns splits one
    effect across several of them.

    Both directions are reported because they answer different questions and
    disagree in an informative way. **Alone** says how much a feature knows;
    **dropped** says how much only it knows. A feature that scores well alone and
    costs nothing when dropped is duplicated by the others, which is a different
    fact about the book than one that carries the edge by itself.
    """
    full, drops, alones, names_out, cells = [], {}, {}, (), 0
    for broker in symbols:
        for interval in GRID:
            try:
                bars = seqlab.load(broker, interval)
            except Exception:  # noqa: BLE001
                continue
            closes = np.asarray(bars["close"], dtype=float)
            logs = np.log(np.maximum(closes, 1e-12))
            sigma = float(np.std(np.diff(logs), ddof=1))
            if sigma <= 0:
                continue
            x, y, names = build(logs, sigma)
            if len(y) < FEWEST:
                continue
            base = fit_auc(x, y)
            if not math.isfinite(base):
                continue
            cells += 1
            names_out = names
            full.append(base)
            for i, nm in enumerate(names):
                keep = [j for j in range(x.shape[1]) if j != i]
                got = fit_auc(x, y, keep)
                if math.isfinite(got):
                    drops.setdefault(nm, []).append(base - got)
                solo = fit_auc(x, y, [i])
                if math.isfinite(solo):
                    alones.setdefault(nm, []).append(solo)
    if not cells:
        return {}
    return {
        "cells": cells,
        "full": float(np.mean(full)),
        "names": names_out,
        "drop": {k: float(np.mean(v)) for k, v in drops.items()},
        "drop_se": {
            k: float(np.std(v, ddof=1) / math.sqrt(len(v))) if len(v) > 1 else float("nan")
            for k, v in drops.items()
        },
        "alone": {k: float(np.mean(v)) for k, v in alones.items()},
    }


def run(symbols: list[str], arm: str, rng) -> dict:
    aucs, rows, cells = [], 0, 0
    for broker in symbols:
        for interval in GRID:
            try:
                bars = seqlab.load(broker, interval)
            except Exception:  # noqa: BLE001
                continue
            closes = np.asarray(bars["close"], dtype=float)
            logs = np.log(np.maximum(closes, 1e-12))
            sigma = float(np.std(np.diff(logs), ddof=1))
            if sigma <= 0:
                continue
            if arm == "feed":
                series = logs
            elif arm == "gbm":
                series = logs[0] + np.cumsum(rng.normal(0.0, sigma, len(logs)))
            elif arm == "surrogate":
                try:
                    sur = seqlab.surrogate_bars(bars, rng)
                    series = np.log(np.maximum(np.asarray(sur["close"], float), 1e-12))
                except Exception:  # noqa: BLE001
                    continue
            else:  # shuffle the increments, keeping the marginal
                steps = np.diff(logs)
                rng.shuffle(steps)
                series = np.concatenate(([logs[0]], logs[0] + np.cumsum(steps)))
            got = cell(series, sigma, rng)
            if got and math.isfinite(got["auc"]):
                aucs.append(got["auc"])
                rows += got["n"]
                cells += 1
    if not cells:
        return {}
    arr = np.asarray(aucs)
    se = float(arr.std(ddof=1) / math.sqrt(len(arr))) if len(arr) > 1 else float("nan")
    return {
        "cells": cells,
        "rows": rows,
        "auc": float(arr.mean()),
        "se": se,
        "above": int((arr > 0.5).sum()),
        "t": float((arr.mean() - 0.5) / se) if se and se > 0 else float("nan"),
    }


def main() -> int:
    rng = np.random.default_rng(37)
    print("When a trend reverses, is the depth of what follows predictable at the time?\n")
    print("Features are read at the CONFIRMATION bar, not at the extreme - a turn is")
    print("not known when it happens. Target is the next leg over this correction.\n")
    print(
        f"{'group':12} {'arm':11} {'cells':>6} {'rows':>9} {'AUC':>8} "
        f"{'se':>7} {'above .5':>9} {'t':>7}"
    )
    for name, symbols in (
        ("real", list(seqlab.REAL)),
        ("volatility", list(seqlab.VOLATILITY)[:12]),
    ):
        for arm in ("feed", "surrogate", "gbm", "shuffle"):
            got = run(symbols, arm, np.random.default_rng(37))
            if not got:
                print(f"{name:12} {arm:11}  nothing scored")
                continue
            print(
                f"{name:12} {arm:11} {got['cells']:>6} {got['rows']:>9,} "
                f"{got['auc']:>8.4f} {got['se']:>7.4f} "
                f"{got['above']:>9} {got['t']:>7.2f}"
            )
        print()

    # ------------------------------------------------ which feature carries it
    print("=" * 84)
    print("WHICH FEATURE CARRIES IT")
    print("=" * 84)
    got = importance(list(seqlab.REAL))
    if got:
        print(f"full model {got['full']:.4f} over {got['cells']} cells\n")
        print(f"{'feature':14} {'alone':>8} {'dropped costs':>14} {'se':>8} {'t':>7}")
        order = sorted(got["names"], key=lambda n: -got["drop"].get(n, 0.0))
        for nm in order:
            d = got["drop"].get(nm, float("nan"))
            se = got["drop_se"].get(nm, float("nan"))
            t = d / se if se and math.isfinite(se) and se > 0 else float("nan")
            print(
                f"{nm:14} {got['alone'].get(nm, float('nan')):>8.4f} "
                f"{d:>+14.4f} {se:>8.4f} {t:>7.2f}"
            )
        print()
        print("alone says how much a feature knows; dropped says how much ONLY it knows.")
        print("A feature strong alone and free to drop is duplicated by the others.")
    print()

    print("Reading it: the feed against its own surrogate and gbm, not against 0.50.")
    print("A gbm arm far from 0.50 means the target is bounded by a feature again -")
    print("two earlier versions of this read 0.78 and 0.85 for exactly that.")
    print("Anything on the volatility family is the procedure - those feeds have no")
    print("conditional structure to find.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
