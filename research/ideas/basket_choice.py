"""Choosing a basket: does picking the best one generalise, or is it selection?

`relating.Relating` carries a hedge ratio as a state but **does not choose the
basket**, which was the second of three limits named when it was built. The
obvious remedy - fit every candidate basket and keep the best - is also the
oldest way to manufacture a result, so the question is not "which basket wins"
but **"does the winner keep winning"**.

Three arms, and the gap between them is the whole measurement:

* **chosen** - the basket with the best likelihood on the training period,
  scored on the held-out period. What a desk would actually do.
* **random** - a basket of the same size drawn at random, scored on the same
  held-out period. If `chosen` matches this, selection found nothing and the
  apparent skill is the maximum of a pile of noise.
* **oracle** - the basket with the best likelihood *on the test period*,
  which nobody could have picked. It is the ceiling, and the distance from
  `chosen` to it says how much of the achievable was reachable in advance.

The oracle arm matters because `random` alone cannot distinguish "selection
does not work" from "no basket works". If the oracle is also near random, the
instruments have no relationship to find and selection was never the problem.

## Causality

Train on the first `SHARE` of the series, score on the rest. Candidate
enumeration, fitting and choosing all happen inside the training period; the
test period is touched once, at the end, by three already-chosen baskets.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.statespace.relating import Relating

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("btcusd", "BTCUSD"),
    ("v75", "Volatility_75_Index"),
)
FRAME = os.environ.get("FRAME", "1h")

#: How many legs in a basket. Two and three, because a pair is the usual case
#: and three is where the candidate count starts to matter.
WIDTHS = (1, 2, 3)

SHARE = 0.6
SINCE = float(os.environ.get("SINCE", "1262304000"))
LIMIT = int(os.environ.get("LIMIT", "12000"))
SEED = 20261011


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
    first = 0
    while first < len(times) and times[first] < SINCE:
        first += 1
    return times[first:], closes[first:]


def aligned() -> tuple[list[float], dict[str, list[float]]]:
    """Every instrument on one clock, as log prices.

    Logs because a hedge ratio between log prices is a *proportional* hedge,
    which is the one that survives a price level changing - and because the
    legs then sit on one scale, which `Relating`'s centring needs.
    """
    series = {}
    for label, stem in SYMBOLS:
        got = load(stem, FRAME)
        if got is not None and len(got[1]) > 3000:
            series[label] = dict(zip(got[0], got[1], strict=True))
    if len(series) < 3:
        return [], {}
    stamps = sorted(set.intersection(*(set(v) for v in series.values())))
    if len(stamps) > LIMIT:
        stamps = stamps[-LIMIT:]
    return stamps, {name: [math.log(values[t]) for t in stamps] for name, values in series.items()}


def score(
    dependent: list[float],
    legs: list[list[float]],
    stamps: list[float],
    first: int,
    last: int,
) -> float:
    """Held-out log-likelihood of `Relating` over `[first, last)`."""
    engine = Relating(legs=len(legs), ratio_wander=1e-7)
    for i in range(last):
        engine.predict(stamps[i])
        engine.update(dependent[i], 0.0001, stamps[i], against=[leg[i] for leg in legs])
        if i == first - 1:
            engine.loglike = 0.0
    return engine.loglike


def main() -> None:
    stamps, series = aligned()
    if not stamps:
        print("not enough overlapping history")
        return
    names = sorted(series)
    cut = int(len(stamps) * SHARE)
    rng = random.Random(SEED)

    print("Choosing a basket: does the winner keep winning?")
    print(f"{FRAME}, {len(stamps)} aligned bars, {len(names)} instruments.")
    print("'chosen' is best on train, scored on test. 'random' is a basket of")
    print("the same size drawn blind. 'oracle' is best on test, which nobody")
    print("could pick. chosen ~ random means selection found nothing.\n")

    for width in WIDTHS:
        print(f"=== baskets of {width} leg(s) ===")
        print(
            f"  {'dependent':<10}{'cands':>7}{'chosen':>12}{'random':>12}"
            f"{'oracle':>12}{'captured':>10}"
        )
        rows = []
        for target in names:
            others = [n for n in names if n != target]
            candidates = list(itertools.combinations(others, width))
            if not candidates:
                continue
            dependent = series[target]

            trained = {
                combo: score(dependent, [series[c] for c in combo], stamps, 0, cut)
                for combo in candidates
            }
            tested = {
                combo: score(dependent, [series[c] for c in combo], stamps, cut, len(stamps))
                for combo in candidates
            }
            chosen = max(trained, key=lambda c: trained[c])
            oracle = max(tested, key=lambda c: tested[c])
            drawn = rng.choice(candidates)

            got, blind, best = tested[chosen], tested[drawn], tested[oracle]
            captured = (got - blind) / (best - blind) if best > blind else float("nan")
            rows.append((got, blind, best, captured))
            print(
                f"  {target:<10}{len(candidates):>7}{got:>12.0f}{blind:>12.0f}"
                f"{best:>12.0f}{captured:>9.0%}"
            )
        if rows:
            share = [r[3] for r in rows if r[3] == r[3]]
            if share:
                print(
                    f"  {'mean':<10}{'':>7}{'':>12}{'':>12}{'':>12}{statistics.fmean(share):>9.0%}"
                )
        print()

    print("Reading it: 'captured' is how much of the gap between a blind")
    print("basket and the best possible one the training period could find.")
    print("At or below zero, choosing is worse than not choosing - which is")
    print("what selection on a noisy likelihood surface produces.")


if __name__ == "__main__":
    main()
