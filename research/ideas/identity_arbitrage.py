"""The triangle residual, pre-specified, and whether a stale quote explains it.

The search over relationships found its edge concentrating on `EURAUD` - a
cross, so most of its configurations are **currency identities** rather than
fitted guesses. Restricted to the seven identities, the aggregate readings point
somewhere specific and mechanically sensible:

* reversion is fastest at **1 to 6 bars** and **negative by 240**, which is what
  an arbitrage residual should look like and not what a fitted relationship
  looks like;
* the median configuration on the cheap legs clears a round trip - `USDCHF`
  **1.85**, `GBPUSD` **1.16**, `CHFJPY` **1.11**.

And the search's own pick - chosen by the best search-slice reading - landed on
`|z| > 6, h = 240`, the one corner where the aggregate is *negative*, and
confirmed at `p = 0.488`. **Maximising the search slice is worse than not
searching**: it finds noise spikes at extreme settings while the aggregate
points elsewhere. So nothing here is searched. Every configuration is
pre-specified from the mechanism.

## Why a retail venue can carry this at all

Triangular arbitrage is the most competed trade in FX and does not survive to an
hourly bar on an interbank feed. **A retail CFD venue is not an interbank feed.**
The broker prices `EURCHF` on its own book rather than deriving it from
`EURUSD` and `USDCHF`, so the identity need not hold tightly and a real
inefficiency is possible in a way it is not on a primary venue.

## And why it could equally be nothing

The same pattern is produced exactly by a **stale quote**. If one instrument's
bar close is a last tick that has not moved recently, the triangle appears
deviated at that close and "reverts" on the next bar when the quote updates.
That is measurement noise, it is not tradeable, and it would show the same fast
reversion and the same decay with horizon.

**An entry delay separates them.** Staleness is gone within a bar: the quote has
updated and the apparent deviation never existed at a tradeable price. A real
mispricing that takes hours to close survives a bar's delay with most of its
edge intact. So the delay is swept, and the claim stands or falls on it.

A second check runs alongside: the same readings on the **non-identity** triples,
which have no arithmetic reason to revert. If those look similar, the effect is
in the measurement rather than the identity.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics

import relationship_screen as screen

#: Entry delays in bars. 0 is the deviation acted on at the bar it is seen.
DELAYS = tuple(int(d) for d in os.environ.get("DELAYS", "0,1,2,3").split(","))
#: Horizons, kept short because the aggregate says reversion is fast.
HORIZONS = tuple(int(h) for h in os.environ.get("HORIZONS", "1,3,6,24").split(","))
#: Entry threshold, pre-specified from the aggregate's peak rather than swept.
ENTRY = float(os.environ.get("ENTRY", "3.0"))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "200"))
SEED = 20261013

IDENTITIES = (
    ("EURUSD", "USDCHF", "EURCHF"),
    ("EURUSD", "GBPUSD", "EURGBP"),
    ("EURUSD", "AUDUSD", "EURAUD"),
    ("GBPUSD", "USDJPY", "GBPJPY"),
    ("USDJPY", "USDCHF", "CHFJPY"),
    ("USDJPY", "AUDUSD", "AUDJPY"),
    ("EURUSD", "USDJPY", "EURJPY"),
)
#: Triples with no arithmetic reason to revert, as the comparison class.
CONTROLS = (
    ("EURUSD", "USDJPY", "USDCAD"),
    ("GBPUSD", "NZDUSD", "AUDUSD"),
    ("EURUSD", "USDJPY", "NZDUSD"),
    ("USDJPY", "USDCAD", "NZDUSD"),
    ("EURUSD", "USDCHF", "USDCAD"),
    ("GBPUSD", "USDJPY", "NZDUSD"),
    ("USDCHF", "AUDUSD", "NZDUSD"),
)


def readings(legs, names, *, delay: int, break_link=None):
    """Pre-specified readings for one leg ordering, at one entry delay."""
    import numpy as np

    times = legs[0][0]
    for leg in legs[1:]:
        times = np.intersect1d(times, leg[0])
    if len(times) < 2 * screen.LEAST:
        return []
    values, crossing = [], []
    for leg in legs:
        _, index, _ = np.intersect1d(leg[0], times, return_indices=True)
        values.append(leg[1][index])
        crossing.append(leg[2][index])
    values = np.column_stack(values)
    crossing = np.column_stack(crossing)

    half = len(values) // 2
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
    test = values[half:]
    cross = crossing[half:]
    z = deviation(test) / scale

    out = []
    for index, name in enumerate(names):
        direction = 1.0 if index == len(names) - 1 else (
            -1.0 if weights[index] > 0 else 1.0
        )
        # **One leg, one spread.** Converting a relationship into a
        # directional bet means trading the single leg, so the cost is that
        # leg's own round trip - not the basket's. Charging the basket here
        # over-charged a USDCHF bet by 3.9x (2.868 bp against 0.739) and made
        # the effect look like it missed its cost when it does not.
        cost = 2.0 * float(cross[:, index].mean())
        if cost <= 0:
            continue
        level = test[:, index]
        for horizon in HORIZONS:
            # The deviation is seen at t, the position is taken at t+delay, and
            # held for `horizon` bars from there.
            start = delay
            stop = len(level) - horizon
            if stop - start < 40:
                continue
            seen = z[: stop - start]
            forward = level[start + horizon : stop + horizon] - level[start:stop]
            if break_link is not None:
                forward = break_link(seen, forward)
            wide = np.abs(seen) > ENTRY
            if wide.sum() < 25:
                continue
            earned = direction * -np.sign(seen[wide]) * forward[wide]
            sd = float(earned.std())
            out.append(
                {
                    "legs": "/".join(names),
                    "leg": name,
                    "delay": delay,
                    "horizon": horizon,
                    "count": int(wide.sum()),
                    "edge_over_cost": float(earned.mean()) / cost,
                    "t": (
                        float(earned.mean()) / (sd / math.sqrt(len(earned)))
                        if sd > 0
                        else float("nan")
                    ),
                }
            )
    return out


def link_breaker(rng):
    import numpy as np

    def go(seen, forward):
        if len(forward) < 50:
            return forward
        return np.roll(forward, rng.randrange(20, len(forward) - 20))

    return go


def gather(series, families, *, delay, break_link=None):
    rows = []
    for names in families:
        if any(series.get(n) is None for n in names):
            continue
        for turn in range(len(names)):
            order = names[turn:] + names[:turn]
            rows.extend(
                readings(
                    [series[n] for n in order], order, delay=delay, break_link=break_link
                )
            )
    return rows


def main() -> None:
    print(
        f"entry |z| > {ENTRY} pre-specified, horizons {HORIZONS}, delays {DELAYS},\n"
        f"{REPS} null repetitions; nothing here is searched\n"
    )
    live = {name: screen.load(name) for name in screen.TRADED}
    live = {k: v for k, v in live.items() if v is not None}
    rng = random.Random(SEED)

    print("=" * 104)
    print("ARM 1  does the edge survive waiting a bar, which a stale quote does not")
    print("=" * 104)
    print(
        f"{'':<26}{'delay':>7}{'configs':>9}{'median edge/cost':>19}"
        f"{'best':>9}{'median t':>10}"
    )
    survived = {}
    for label, families in (("identities", IDENTITIES), ("control triples", CONTROLS)):
        for delay in DELAYS:
            rows = gather(live, families, delay=delay)
            if not rows:
                continue
            edges = sorted(r["edge_over_cost"] for r in rows)
            survived[(label, delay)] = rows
            print(
                f"{label:<26}{delay:>7}{len(rows):>9}"
                f"{statistics.median(edges):>+19.4f}{edges[-1]:>+9.3f}"
                f"{statistics.median([r['t'] for r in rows]):>+10.3f}"
            )
        print()
    print(
        "A stale quote is gone within one bar, so an effect that is measurement\n"
        "noise collapses from delay 0 to delay 1. A real mispricing that takes\n"
        "hours to close keeps most of its edge."
    )

    print("\n" + "=" * 104)
    print("ARM 2  the identity rows at each delay, against a broken link")
    print("=" * 104)
    for delay in DELAYS:
        rows = survived.get(("identities", delay))
        if not rows:
            continue
        nulls = []
        for _ in range(REPS):
            got = gather(
                live, IDENTITIES, delay=delay, break_link=link_breaker(rng)
            )
            if got:
                nulls.append(statistics.median(r["edge_over_cost"] for r in got))
        if not nulls:
            continue
        nulls.sort()
        here = statistics.median(r["edge_over_cost"] for r in rows)
        beat = sum(1 for v in nulls if v >= here)
        print(
            f"delay {delay}: median edge/cost {here:>+8.4f}   "
            f"null median {statistics.median(nulls):>+8.4f}   "
            f"null best {nulls[-1]:>+8.4f}   "
            f"p = {(beat + 1) / (len(nulls) + 1):.4f}"
        )

    print("\n" + "=" * 104)
    print("ARM 3  the rows themselves at the delay that matters")
    print("=" * 104)
    for delay in (0, 1):
        rows = survived.get(("identities", delay))
        if not rows:
            continue
        print(f"\ndelay {delay}:")
        print(
            f"{'legs':<26}{'leg':<9}{'h':>4}{'edge/cost':>11}{'t':>8}{'n':>7}"
        )
        for row in sorted(rows, key=lambda r: -r["edge_over_cost"])[:10]:
            print(
                f"{row['legs']:<26}{row['leg']:<9}{row['horizon']:>4}"
                f"{row['edge_over_cost']:>+11.3f}{row['t']:>+8.2f}{row['count']:>7}"
            )


if __name__ == "__main__":
    main()
