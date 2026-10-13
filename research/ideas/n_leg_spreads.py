"""N-leg spreads, where the degrees of freedom are the adversary.

Two legs found nothing. Three legs found seven relationships and all seven were
currency-triangle identities. The generalisation to `N` is not just more of the
same, because two things change with `N` and both of them flatter the result.

## Every extra leg buys stationarity for free

A spread of `N` legs fits `N-1` weights. More weights mean more ways to make a
residual look stationary, and the null already shows it: the block-shuffled
null's best reads `-3.94` at two legs and `-4.49` at three. **The threshold is
a function of `N`**, so a bar measured at one width says nothing at another and
every `N` here gets its own null.

## And at four legs most baskets contain a triangle

`{EURUSD, USDCHF, EURCHF, GBPUSD}` contains the `EURCHF` triangle, so it
inherits `t = -77` without anything new being true. Past three legs the
identities dominate by count, and a table that does not separate them is a
table of identities.

**Identity is exactly computable rather than a judgement.** Treat each
instrument as an edge between its two currencies; the log prices satisfy an
exact linear relation if and only if the edge set contains a **cycle**:

    edges > nodes - components

`EURUSD/USDCHF/EURCHF` is three edges on three connected nodes, so `3 > 2` and
it is an identity. `EURUSD/USDJPY/USDCAD` is three edges on four, so `3 = 3` -
a tree, no cycle, not an identity. That reproduces exactly what the fitted
weights said at three legs (`+/-1.000` against `-0.675`, `+0.161`), which is
the check that the rule is the right one.

So every basket is classified before it is scored, and the two classes are
reported apart. The identities are the **positive control** - they must come
back enormous or the pipeline is broken - and the question is whether anything
*else* survives at any `N`.

## Cost is the other thing that scales

An `N`-leg spread is opened and closed in every leg, so a five-leg combination
whose residual is tiny is not thereby attractive - the residual has to clear a
crossing of five instruments rather than one. `range/cost` divides the
residual's standard deviation by a round trip across all the legs, **each
weighted by how much of that leg the fit holds**, using the legs' own measured
relative spreads rather than a constant.

## What the numbers said

The identity rule agrees with the fitted weights, which is the check that it is
the right rule: identities come back at `|w| = 1.000`, and the two
non-identities at `0.675/0.161` and `0.595/0.424`.

| width | identities | best non-identity | its own null | survivors |
|------:|-----------:|------------------:|-------------:|----------:|
| 2 |  0 | -3.70 | -3.77 | **0 of 190** |
| 3 |  5 | -3.72 | -4.43 | **0 of 495** |
| 4 | 21 | -3.63 | -4.24 | **0 of 479** |
| 5 | 39 | -3.82 | -4.33 | **0 of 461** |

**1,625 non-identity baskets across four widths and nothing survives.** Every
basket that beats its own null is a currency identity.

Two predictions above were wrong and the measurement is what corrected them.

**The bar does not keep rising.** It goes `-3.77`, `-4.43`, `-4.24`, `-4.33` -
the degrees-of-freedom inflation **saturates after the third leg** rather than
growing with `N`. Measuring a null per width was still right, but not for the
reason given.

**An identity dilutes with width.** Three-leg identities have a median of
`-71.59`; five-leg identities have a best of `-77.84` and a median of `-2.38`.
The regression fits the last leg on the others, so if the dependent leg is not
part of the cycle the identity sits *among the regressors* and the residual is
not stationary. The cycle test correctly flags the set; whether the fit recovers
the identity depends on which leg is dependent. That makes the exclusion
conservative in the right direction - some excluded baskets were never strong -
rather than hiding anything.

The identity count rising `0, 5, 21, 39` is why the classification was worth
building. Without it the four- and five-leg tables are 21 and 39 rows of `-77`,
and the screen reports relationships it has merely restated.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from itertools import combinations

import relationship_screen as screen

#: Widths to test. Two is the pair screen, three the basket screen.
WIDTHS = tuple(int(n) for n in os.environ.get("WIDTHS", "2,3,4,5").split(","))
#: Cap on baskets scored per width, so the runtime stays sane at C(20,5).
SAMPLE = int(os.environ.get("SAMPLE", "500"))
#: Repetitions of the shuffled null per width.
REPS = int(os.environ.get("REPS", "2"))
SEED = 20261013


def currencies(name: str) -> tuple[str, str]:
    """The two codes a symbol spans. `EURUSD` is an edge from EUR to USD."""
    return name[:3], name[3:6]


def is_identity(names) -> bool:
    """Whether the legs' currency graph contains a cycle.

    A cycle means the log prices satisfy an exact linear relation, so the
    residual is the spread and rounding rather than a relationship.
    """
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    edges = 0
    for name in names:
        left, right = currencies(name)
        a, b = find(left), find(right)
        edges += 1
        if a != b:
            parent[a] = b
    codes = {code for name in names for code in currencies(name)}
    # `nodes` counts currencies; `components` counts the trees they fall into.
    # Conflating the two makes every connected set look like an identity.
    components = len({find(code) for code in codes})
    return edges > len(codes) - components


def spread(legs):
    """DF `t` of the last leg against the others, weights fitted on the first half.

    The cost is the legs' **own measured relative spreads**, weighted by the
    weights the fit chose, rather than a constant - a round trip crosses every
    leg in proportion to how much of it the spread holds.
    """
    import numpy as np

    times = legs[0][0]
    for leg in legs[1:]:
        times = np.intersect1d(times, leg[0])
    if len(times) < screen.LEAST:
        return None
    columns, spreads = [], []
    for leg in legs:
        _, index, _ = np.intersect1d(leg[0], times, return_indices=True)
        columns.append(leg[1][index])
        spreads.append(leg[2][index])
    values = np.column_stack(columns)
    crossing = np.column_stack(spreads)
    half = len(values) // 2
    if half < screen.LEAST // 2:
        return None
    design = np.column_stack([values[:half, :-1], np.ones(half)])
    try:
        weights, *_ = np.linalg.lstsq(design, values[:half, -1], rcond=None)
    except np.linalg.LinAlgError:
        return None
    predicted = values[half:, :-1] @ weights[:-1] + weights[-1]
    residual = values[half:, -1] - predicted
    t = screen.dickey_fuller(residual)[1]
    if not math.isfinite(t):
        return None
    # One crossing of each leg, weighted by how much of it is held; the
    # dependent leg carries weight 1. A round trip is twice that.
    held = np.concatenate([np.abs(weights[:-1]), [1.0]])
    one_way = float((crossing[half:].mean(axis=0) * held).sum())
    return {
        "t": t,
        "range_over_cost": (
            float(residual.std()) / (2.0 * one_way) if one_way > 0 else float("nan")
        ),
        "weights": weights[:-1],
    }


def summarise(label: str, values) -> None:
    values = sorted(values)
    if not values:
        print(f"{label:<40}{'-':>9}")
        return
    print(
        f"{label:<40}{len(values):>9,}{values[0]:>+10.2f}"
        f"{values[max(len(values) // 100, 0)]:>+10.2f}"
        f"{statistics.median(values):>+10.2f}"
    )


def main() -> None:
    print(f"widths {WIDTHS}, up to {SAMPLE:,} baskets each, {REPS} null repetitions")
    print(
        "cost is each leg's own measured relative spread, weighted by how much\n"
        "of that leg the fit holds, doubled for a round trip\n"
    )

    live = [name for name in screen.TRADED if screen.load(name) is not None]
    series = {name: screen.load(name) for name in live}
    print(f"{len(live)} instruments\n")
    rng = random.Random(SEED)

    print("=" * 104)
    print("ARM 0  the identity rule against the fitted weights, at three legs")
    print("=" * 104)
    print(f"{'legs':<30}{'identity?':>11}{'max |w|':>10}{'min |w|':>10}{'DF t':>9}")
    for names in (
        ("EURUSD", "USDCHF", "EURCHF"),
        ("EURUSD", "GBPUSD", "EURGBP"),
        ("EURUSD", "USDJPY", "USDCAD"),
        ("GBPUSD", "NZDUSD", "AUDUSD"),
    ):
        got = spread([series[n] for n in names])
        if got is None:
            continue
        weights = [abs(float(w)) for w in got["weights"]]
        print(
            f"{'/'.join(names):<30}{'yes' if is_identity(names) else 'no':>11}"
            f"{max(weights):>10.3f}{min(weights):>10.3f}{got['t']:>+9.2f}"
        )
    print(
        "\nThe rule is structural and the weights are measured, so agreement\n"
        "between them is evidence the classification is the right one."
    )

    print("\n" + "=" * 104)
    print("ARM 1  the bar rises with every leg, which is the thing to control for")
    print("=" * 104)
    print(f"{'':<40}{'baskets':>9}{'best':>10}{'1st pct':>10}{'median':>10}")
    bars: dict[int, float] = {}
    survivors: dict[int, list] = {}
    for width in WIDTHS:
        every = list(combinations(live, width))
        rng.shuffle(every)
        chosen = every[:SAMPLE]

        plain, identities, nulls = [], [], []
        for names in chosen:
            got = spread([series[n] for n in names])
            if got is None:
                continue
            got["legs"] = "/".join(names)
            (identities if is_identity(names) else plain).append(got)
        for _ in range(REPS):
            for names in chosen:
                legs = [series[names[0]]] + [
                    screen.block_shuffled(series[n], rng) for n in names[1:]
                ]
                got = spread(legs)
                if got is not None:
                    nulls.append(got["t"])
        if not nulls:
            continue
        bars[width] = min(nulls)
        survivors[width] = [r for r in plain if r["t"] < bars[width]]
        summarise(f"{width} legs, identities", [r["t"] for r in identities])
        summarise(f"{width} legs, not identities", [r["t"] for r in plain])
        summarise(f"  {width} legs, block-shuffled null", nulls)
        print(
            f"{'':<40}{'':>9}-> {len(survivors[width])} of {len(plain)} "
            f"non-identity baskets beat the null's best "
            f"({bars[width]:+.2f}), {len(identities)} identities excluded\n"
        )

    print("=" * 104)
    print("ARM 2  what survives, and whether it pays for its legs")
    print("=" * 104)
    print(f"{'legs':<44}{'width':>7}{'DF t':>9}{'range/cost':>12}")
    any_survivor = False
    for width in WIDTHS:
        for got in sorted(survivors.get(width, []), key=lambda r: r["t"])[:8]:
            any_survivor = True
            print(
                f"{got['legs']:<44}{width:>7}{got['t']:>+9.2f}"
                f"{got['range_over_cost']:>12.3f}"
            )
    if not any_survivor:
        print(
            "\nNothing at any width. Every basket that beats its own null is an\n"
            "identity, and every basket that is not an identity is inside the\n"
            "range the same procedure produces from unrelated series."
        )


if __name__ == "__main__":
    main()
