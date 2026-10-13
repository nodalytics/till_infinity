"""Turning a relationship into a directional bet, which is a different question.

Every screen so far asked whether a **spread** reverts. That is the wrong
question for this desk, for a reason that is arithmetic rather than
philosophical.

## A spread pays N costs and a leg pays one

Everything killed in the pair and basket work was killed on cost: a residual
that reverts beautifully over a range smaller than its own round trip is not a
trade, and a two-leg spread crosses two instruments while a five-leg spread
crosses five. **A single leg crosses one.** A relationship rejected at
`range/cost 0.5` as a spread is `1.0` as a one-legged bet, and the whole body of
negative results sits inside that factor.

## And reversion is not prediction

The fitted relationship gives a **conditional expectation** for one leg given
the others. The deviation from it is observable, and the directional question is
whether that deviation predicts **that leg's own forward return** - not the
spread's.

Those come apart, and which way decides whether there is a trade:

* the deviation closes and **one leg does the adjusting** - that leg is a
  directional bet, at one cost;
* the deviation closes and **both legs adjust** - there is no directional bet,
  only the spread, at two costs;
* the deviation **persists** - the spread is stationary on a long enough window
  and nothing is predictable at a tradeable horizon.

A Dickey-Fuller `t` cannot tell these three apart. It is the same number in all
three cases, which is why the question has to be asked separately.

## The identities are the decisive case, not a leftover

Seven currency triangles are relationships that are **known to be real** - the
weights come back at exactly ±1.000 and the residual is 0.8 to 3.2 basis
points. So they remove the usual doubt: there is no question of whether the
relationship exists, only of whether a known relationship converts.

**If a perfect, exact, known relationship yields no directional edge past cost,
that is a far stronger statement than another null on a doubtful one.** It says
the conversion fails at the step where the deviation becomes a forecast, and no
better relationship would rescue it.

## What is measured

Weights are fitted on the first half and held. On the second half the deviation
is standardised with first-half scale, and for each leg and each horizon the
harness reports the mean forward return **signed so that positive is
profitable**, conditional on the deviation being wide (`|z| > ENTER`), divided
by **one round trip in that leg alone** using the leg's own measured spread.

`edge/cost` above 1 is a trade. Everything else is a description.

The null rotates the other leg, which leaves the deviation meaningless while
preserving every marginal property of both series, and runs the identical
pipeline. A planted arm checks the detector can see a relationship where one
leg does all the adjusting, so that a null means something.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from itertools import combinations

import relationship_screen as screen

#: Deviation, in first-half standard deviations, wide enough to act on.
ENTER = float(os.environ.get("ENTER", "2.0"))
#: Forward horizons in bars.
HORIZONS = tuple(int(h) for h in os.environ.get("HORIZONS", "1,6,24").split(","))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "3"))
SEED = 20261013

#: The seven currency triangles: relationships known to be real by arithmetic.
TRIANGLES = (
    ("EURUSD", "USDCHF", "EURCHF"),
    ("EURUSD", "GBPUSD", "EURGBP"),
    ("EURUSD", "AUDUSD", "EURAUD"),
    ("GBPUSD", "USDJPY", "GBPJPY"),
    ("USDJPY", "USDCHF", "CHFJPY"),
    ("USDJPY", "AUDUSD", "AUDJPY"),
    ("EURUSD", "USDJPY", "EURJPY"),
)


def rotated(series, rng):
    """The same series at a random offset: the deviation dies, the process lives."""
    import numpy as np

    times, values, spread = series
    shift = rng.randrange(120, max(len(values) - 120, 121))
    steps = np.diff(np.roll(values, shift))
    rebuilt = np.empty_like(values)
    rebuilt[0] = values[0]
    rebuilt[1:] = values[0] + np.cumsum(steps)
    return times, rebuilt, spread


def convert(legs, names, enter: float = ENTER):
    """Per-leg directional readings from one relationship's deviation.

    Returns a list of rows, one per `(leg, horizon)`, each carrying the signed
    edge conditional on a wide deviation and that leg's own round-trip cost.
    """
    import numpy as np

    times = legs[0][0]
    for leg in legs[1:]:
        times = np.intersect1d(times, leg[0])
    if len(times) < screen.LEAST:
        return []
    values, crossing = [], []
    for leg in legs:
        _, index, _ = np.intersect1d(leg[0], times, return_indices=True)
        values.append(leg[1][index])
        crossing.append(leg[2][index])
    values = np.column_stack(values)
    crossing = np.column_stack(crossing)

    half = len(values) // 2
    if half < screen.LEAST // 2:
        return []
    design = np.column_stack([values[:half, :-1], np.ones(half)])
    try:
        weights, *_ = np.linalg.lstsq(design, values[:half, -1], rcond=None)
    except np.linalg.LinAlgError:
        return []

    def deviation(block):
        return block[:, -1] - (block[:, :-1] @ weights[:-1] + weights[-1])

    scale = float(deviation(values[:half]).std())
    if scale <= 0:
        return []
    # Standardised with first-half scale, so nothing from the test half leaks.
    z = deviation(values[half:]) / scale

    rows = []
    for index, name in enumerate(names):
        # A positive deviation means the dependent leg sits ABOVE the
        # relationship, so it is shorted and pays when it falls: with
        # `earned = direction * -sign(z) * forward`, that is direction +1.
        # A regressor with a positive weight is correspondingly too LOW and is
        # bought, which is direction -1. Getting these backwards reads a
        # planted adjuster at -19.78 instead of +19.78, which is how it was
        # caught - the planted arm is the only thing that checks a sign.
        if index == len(names) - 1:
            direction = 1.0
        else:
            direction = -1.0 if weights[index] > 0 else 1.0
        # One round trip in this leg alone, which is the point of the exercise.
        cost = 2.0 * float(crossing[half:, index].mean())
        if cost <= 0:
            continue
        level = values[half:, index]
        for horizon in HORIZONS:
            if len(z) <= horizon + 10:
                continue
            forward = level[horizon:] - level[:-horizon]
            zz = z[:-horizon]
            wide = np.abs(zz) > enter
            if wide.sum() < 30:
                continue
            # Signed so that positive is money: trade with `direction`, against
            # the deviation's sign.
            earned = direction * -np.sign(zz[wide]) * forward[wide]
            spread_of = float(earned.std())
            rows.append(
                {
                    "legs": "/".join(names),
                    "leg": name,
                    "horizon": horizon,
                    "count": int(wide.sum()),
                    "edge_over_cost": float(earned.mean()) / cost,
                    # Size and reliability are different things: a tiny cost
                    # turns an insignificant mean into a large edge/cost, and
                    # the planted arm's controls read 0.7 to 0.9 on noise.
                    "t": (
                        float(earned.mean()) / (spread_of / math.sqrt(len(earned)))
                        if spread_of > 0
                        else float("nan")
                    ),
                    "hit": float((earned > 0).mean()),
                    "cost": cost,
                }
            )
    return rows


def planted_arm() -> None:
    """A relationship where one named leg does all the adjusting."""
    import numpy as np

    print("=" * 104)
    print("ARM 0  planted: one leg adjusts, so the detector must find a bet in it")
    print("=" * 104)
    n, rng = 12_000, np.random.default_rng(3)
    when = np.arange(n, dtype=float)
    spread_level = np.full(n, 0.00005)

    anchor = np.cumsum(rng.standard_normal(n) * 0.001)
    print(
        f"{'planted':<30}{'leg':<10}{'h':>4}{'edge/cost':>11}{'t':>8}"
        f"{'hit':>8}{'n':>7}"
    )
    for label, adjust in (("the follower adjusts", 0.05), ("neither adjusts", 0.0)):
        gap = np.zeros(n)
        follow = np.zeros(n)
        for i in range(1, n):
            # The follower is pulled back toward the anchor by `adjust`.
            gap[i] = gap[i - 1] * (1.0 - adjust) + rng.standard_normal() * 0.001
            follow[i] = anchor[i] + gap[i]
        legs = [
            (when, anchor, spread_level),
            (when, follow, spread_level),
        ]
        for row in convert(legs, ("anchor", "follow")):
            if row["horizon"] != 6:
                continue
            print(
                f"{label:<30}{row['leg']:<10}{row['horizon']:>4}"
                f"{row['edge_over_cost']:>+11.2f}{row['t']:>+8.2f}"
                f"{row['hit']:>8.3f}{row['count']:>7}"
            )
    print(
        "\nThe follower must show a positive edge where it adjusts and nothing\n"
        "where it does not. If both rows read the same the detector is blind\n"
        "and the nulls below would mean nothing."
    )


def report(label: str, rows, top: int = 10) -> None:
    by_horizon: dict[int, list[float]] = {}
    for row in rows:
        by_horizon.setdefault(row["horizon"], []).append(row["edge_over_cost"])
    print(f"\n{label}")
    print(f"{'horizon':>9}{'readings':>10}{'best':>11}{'99th pct':>11}{'median':>11}")
    for horizon in sorted(by_horizon):
        values = sorted(by_horizon[horizon])
        print(
            f"{horizon:>9}{len(values):>10,}{values[-1]:>+11.3f}"
            f"{values[max(len(values) - len(values) // 100 - 1, 0)]:>+11.3f}"
            f"{statistics.median(values):>+11.3f}"
        )


def main() -> None:
    print(
        f"deviation wider than {ENTER} first-half sd, horizons {HORIZONS} bars,\n"
        "edge divided by ONE round trip in the traded leg alone\n"
    )
    planted_arm()

    live = [name for name in screen.TRADED if screen.load(name) is not None]
    series = {name: screen.load(name) for name in live}
    rng = random.Random(SEED)

    print("\n" + "=" * 104)
    print("ARM 1  the seven triangles, which are relationships known to be real")
    print("=" * 104)
    print(
        f"{'legs':<26}{'leg':<10}{'h':>4}{'edge/cost':>11}{'t':>8}"
        f"{'hit':>8}{'n':>7}{'cost bp':>9}"
    )
    identity_rows = []
    for names in TRIANGLES:
        if any(series.get(n) is None for n in names):
            continue
        rows = convert([series[n] for n in names], names)
        identity_rows.extend(rows)
        for row in rows:
            if row["horizon"] != HORIZONS[1]:
                continue
            print(
                f"{row['legs']:<26}{row['leg']:<10}{row['horizon']:>4}"
                f"{row['edge_over_cost']:>+11.3f}{row['t']:>+8.2f}"
                f"{row['hit']:>8.3f}{row['count']:>7}{row['cost'] * 1e4:>9.2f}"
            )
    report("every triangle leg and horizon:", identity_rows)
    best = max(identity_rows, key=lambda r: r["edge_over_cost"], default=None)
    if best is not None:
        print(
            f"\nbest single reading: {best['legs']} leg {best['leg']} at h="
            f"{best['horizon']}, edge/cost {best['edge_over_cost']:+.3f}"
        )

    print("\n" + "=" * 104)
    print("ARM 2  every pair, against a rotation of the other leg")
    print("=" * 104)
    real, null = [], []
    for a, b in combinations(live, 2):
        real.extend(convert([series[a], series[b]], (a, b)))
    for _ in range(REPS):
        for a, b in combinations(live, 2):
            null.extend(convert([series[a], rotated(series[b], rng)], (a, b)))
    report("traded pairs:", real)
    report("rotation null:", null)

    for horizon in HORIZONS:
        bar = max(
            (r["edge_over_cost"] for r in null if r["horizon"] == horizon),
            default=float("nan"),
        )
        here = [r for r in real if r["horizon"] == horizon]
        beat = [r for r in here if r["edge_over_cost"] > bar]
        pays = [r for r in here if r["edge_over_cost"] > 1.0]
        print(
            f"\nh={horizon:<3} null's best {bar:+.3f}   "
            f"{len(beat)} of {len(here)} beat it   "
            f"{len(pays)} clear edge/cost 1.0"
        )
        for row in sorted(here, key=lambda r: -r["edge_over_cost"])[:6]:
            print(
                f"      {row['legs']:<20}leg {row['leg']:<9}"
                f"edge/cost {row['edge_over_cost']:>+8.3f}  t {row['t']:>+6.2f}"
                f"  hit {row['hit']:.3f}  n {row['count']:>5}"
                f"{'  BEATS NULL' if row['edge_over_cost'] > bar else ''}"
            )


if __name__ == "__main__":
    main()
