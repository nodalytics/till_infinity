"""The cross-asset lead-lag claims: oil to CAD, gold to AUD, dollar to equities.

Several of the published ideas share one mechanism: two instruments are
fundamentally tethered, one moves first, the correlation "temporarily breaks",
and the laggard is "statistically forced to catch up" over the next 8 to 48
hours. The named pairs are WTI leading USDCAD, gold leading AUDUSD, and the
dollar index leading equities.

This repo already has a standing result that bears directly on the class:
**relationships here are contemporaneous.** Volatility and tail co-movement are
large, and every lagged measure tested has come back null. That is a prior, not
an answer, so these specific pairs get measured - with the power statement that
makes a null mean something.

## What is and is not in the cache

Oil and gold are there, so **USDCAD-oil and AUDUSD-gold are the real tests**.
There is **no dollar index and no equity index** - `DOW` in the cache sits in
the 222-name equity set and is Dow Inc. the company, not the average, which is
the kind of mistake that would quietly produce a headline. So the dollar leg is
**constructed** from the six ICE basket currencies at their published weights,
and it is labelled constructed everywhere it appears.

## The design

A "decoupling" needs a definition that cannot fire on noise. The leader's move
over a window is measured in its own volatility units, the laggard's over the
same window in its own, and an event is a leader move past `MOVE` sigma while
the laggard stays inside `STILL` sigma. The bet is that the laggard closes the
gap, signed by the sign the standing relationship implies.

The sign is **measured, not assumed**. Each pair's contemporaneous beta is
fitted on a training half and the bet takes that sign on the held-out half -
because asserting that oil strengthens CAD and then testing it is a way to get
the answer from the assertion. A pair whose own data does not show the
relationship is reported as such.

Controls: a placebo pair of two independent Deriv volatility indices, which
have no fundamental tether of any kind, and the spacing rule - events inside
one horizon of an accepted event are dropped.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screen import load  # noqa: E402

WINDOW = int(os.environ.get("WINDOW", "4"))
HORIZON = tuple(int(k) for k in os.environ.get("HORIZON", "8,24,48").split(","))
MOVE = float(os.environ.get("MOVE", "2.0"))
STILL = float(os.environ.get("STILL", "0.5"))
DRAWS = int(os.environ.get("DRAWS", "400"))
PLANT = tuple(float(k) for k in os.environ.get("PLANT", "0.1,0.25,0.5").split(","))
SEED = int(os.environ.get("SEED", "11"))

#: The ICE dollar basket, as `(feed, weight, inverted)`. A weight applies to
#: the currency per dollar, so a pair quoted the other way round is inverted.
BASKET = (
    ("EURUSD", 0.576, True),
    ("USDJPY", 0.136, False),
    ("GBPUSD", 0.119, True),
    ("USDCAD", 0.091, False),
    ("USDSEK", 0.042, False),
    ("USDCHF", 0.036, False),
)

PAIRS = (
    ("oil -> USDCAD", "US_Oil", "USDCAD"),
    ("brent -> USDCAD", "UK_Brent_Oil", "USDCAD"),
    ("gold -> AUDUSD", "XAUUSD", "AUDUSD"),
    ("gold -> USDCAD", "XAUUSD", "USDCAD"),
    ("placebo vol75 -> vol100", "Volatility_75_Index", "Volatility_100_Index"),
)


def aligned(first: str, second: str) -> tuple[np.ndarray, np.ndarray] | None:
    """Common timestamps, then returns - never the other way round.

    Aligning on common timestamps after differencing turns every session gap
    into a fake one-bar return, which is a mistake already made here once.
    """
    one, two = load(first, "1h"), load(second, "1h")
    if one is None or two is None:
        return None
    shared = np.intersect1d(one["time"], two["time"])
    if len(shared) < 4000:
        return None
    a = np.log(one["close"][np.isin(one["time"], shared)])
    b = np.log(two["close"][np.isin(two["time"], shared)])
    return np.diff(a), np.diff(b)


def dollar() -> np.ndarray | None:
    """The constructed ICE basket, as log returns on common timestamps."""
    legs, stamps = {}, None
    for name, _, _ in BASKET:
        got = load(name, "1h")
        if got is None:
            return None
        legs[name] = got
        stamps = got["time"] if stamps is None else np.intersect1d(stamps, got["time"])
    if stamps is None or len(stamps) < 4000:
        return None
    total = np.zeros(len(stamps) - 1)
    for name, weight, inverted in BASKET:
        got = legs[name]
        moved = np.diff(np.log(got["close"][np.isin(got["time"], stamps)]))
        total += weight * (-moved if inverted else moved)
    return total


def run(label: str, lead: np.ndarray, lag: np.ndarray) -> None:
    half = len(lead) // 2
    # The sign of the relationship, fitted where it is not being tested.
    train_lead, train_lag = lead[:half], lag[:half]
    denom = float(np.dot(train_lead, train_lead))
    beta = float(np.dot(train_lead, train_lag)) / denom if denom else 0.0
    sign = 1 if beta > 0 else -1
    tie = float(np.corrcoef(train_lead, train_lag)[0, 1])
    lead, lag = lead[half:], lag[half:]

    rolled_lead = np.convolve(lead, np.ones(WINDOW), mode="valid")
    rolled_lag = np.convolve(lag, np.ones(WINDOW), mode="valid")
    unit_lead = float(np.std(rolled_lead)) or 1.0
    unit_lag = float(np.std(rolled_lag)) or 1.0
    rng = np.random.default_rng(SEED)

    print(f"  {label:<26} beta {beta:+.3f}  r {tie:+.3f}  bet sign {sign:+d}")
    for horizon in HORIZON:
        picked, last = [], -(10**9)
        for i in range(len(rolled_lead)):
            if i - last < horizon or i + WINDOW + horizon >= len(lag):
                continue
            moved = rolled_lead[i] / unit_lead
            still = abs(rolled_lag[i]) / unit_lag
            if abs(moved) < MOVE or still > STILL:
                continue
            last = i
            start = i + WINDOW
            ahead = float(np.sum(lag[start : start + horizon]))
            picked.append(sign * math.copysign(1.0, moved) * ahead / unit_lag)
        if len(picked) < 25:
            print(f"    h={horizon:<3}{len(picked):>5} events   too few to measure")
            continue
        got = np.asarray(picked)
        draws = np.array(
            [float(np.mean(got * rng.choice((-1.0, 1.0), size=len(got)))) for _ in range(DRAWS)]
        )
        spread = float(np.std(draws)) or float("nan")
        mean = float(np.mean(got))
        power = "  ".join(f"{p:g}:{(mean + p) / spread:.1f}" for p in PLANT)
        print(
            f"    h={horizon:<3}{len(got):>5} events   mean {mean:>+7.3f}"
            f"   z {mean / spread:>+6.2f}   hit {float(np.mean(got > 0)):.3f}"
            f"   power {power}"
        )


def main() -> None:
    print(
        f"A leader move past {MOVE} sigma over {WINDOW} bars while the laggard stays\n"
        f"inside {STILL} sigma, then the convergence bet held 8, 24 and 48 bars.\n"
        "Mean is in the laggard's own sigma units. The bet's sign is fitted on a\n"
        "training half, so the relationship is measured rather than asserted.\n"
    )
    for label, first, second in PAIRS:
        got = aligned(first, second)
        if got is None:
            print(f"  {label:<26} not enough shared history in the cache")
            continue
        run(label, *got)
    made = dollar()
    if made is None:
        print("\n  constructed dollar basket: a leg is missing from the cache")
        return
    print("\n  the dollar leg is CONSTRUCTED from the six ICE basket weights:")
    for name in ("Germany_40", "XAUUSD", "AUDUSD"):
        other = load(name, "1h")
        if other is None:
            continue
        legs, stamps = {}, None
        for leg, _, _ in BASKET:
            got = load(leg, "1h")
            if got is None:
                continue
            legs[leg] = got
            stamps = got["time"] if stamps is None else np.intersect1d(stamps, got["time"])
        shared = np.intersect1d(stamps, other["time"]) if stamps is not None else None
        if shared is None or len(shared) < 4000:
            print(f"  {'constructed USD -> ' + name:<26} not enough shared history")
            continue
        total = np.zeros(len(shared) - 1)
        for leg, weight, inverted in BASKET:
            got = legs[leg]
            moved = np.diff(np.log(got["close"][np.isin(got["time"], shared)]))
            total += weight * (-moved if inverted else moved)
        tail = np.diff(np.log(other["close"][np.isin(other["time"], shared)]))
        run(f"constructed USD -> {name}", total, tail)
    print(
        "\n  A real lead-lag needs the mean to clear its null at a horizon the idea\n"
        "  names, the placebo pair to stay at zero, and the power line to show the\n"
        "  claimed size was reachable. The standing result here is that every lagged\n"
        "  measure is null while contemporaneous ones are large."
    )


if __name__ == "__main__":
    main()
