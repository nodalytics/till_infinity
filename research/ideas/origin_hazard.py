"""Is an origin that has not been returned to yet **due**, or less likely?

The operator, 2026-11-21: *"since we know the longer it takes the more likely
price is to return to an origin we can look for origins that price has not
return to before and it is close to if not due time."*

## Two different claims, and only one of them is measured

**The cumulative rate rises with time.** True, and
[`leg-lengths.md`](../docs/leg-lengths.md) measures it: **0.90 to 0.93** of
origins are traded back through within 500 bars, on every frame from M5 to D1.

**The hazard rises with time** - an origin that is overdue is more likely to
return *soon*. That is what "due time" needs, and it does **not** follow from
the first. A distribution can have a rising CDF and a falling hazard at the same
time, and heavy-tailed first-passage times do exactly that.

The measured distribution already looks like one: M15 bars-to-return reads
**p50 12, p75 35, p90 99.6, p99 399** - a 33x ratio between the median and the
99th. And the day-shuffled twin reproduces it: *p50 12, p75 36, p90 102, p99
386.* So whatever shape the wait has, a market with its day order destroyed has
the same shape.

**This file measures the hazard directly**, because the difference between the
two claims is the whole idea and an argument from the shape is not a
measurement.

## What is computed

For each origin, the wait until price trades back through it. Then, for a ladder
of ages `t`, among the origins **still unreturned at `t`**:

    hazard(t, k) = P(returns within k more bars | has not returned by t)

* **Rising in `t`** - the operator is right, an old origin is due, and the
  magnitude says how much.
* **Flat in `t`** - the wait is memoryless and age carries nothing.
* **Falling in `t`** - an old origin is *less* likely to return soon, the
  expected remaining wait grows with the wait, and "due time" is the gambler's
  fallacy applied to a first-passage time.

**The shuffled arm decides it either way**, because a hazard is a property of
the wait distribution and a driftless walk has one too. `a-martingale-cannot-pay`
is the standing form: any positive expectancy on a walk has been a measurement
error every time.

**Censoring is handled rather than dropped.** An origin whose wait exceeds the
patience limit is unreturned-and-still-counted at every age below the limit; the
alternative - keeping only origins that did return - conditions on the outcome
and manufactures a rising hazard out of nothing, which is the most likely way
this measurement goes wrong.

Run as:

    uv run python research/ideas/origin_hazard.py --frames M15,H1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from leg_lengths import CHEAP, DEEP, atr, pivots, point_of, read

#: Ages to condition on, in bars. Spans the measured quantiles: p50 is 12 and
#: p90 near 100, so the ladder has to reach past both to see a trend.
AGES = (0, 6, 12, 24, 48, 96, 192, 384)

#: Windows to ask about, in bars. 12 is the measured median wait, so
#: `hazard(t, 12)` is "does the next median-wait-worth of bars return it".
WINDOWS = (6, 12, 48)


def waits(feed, left: int, right: int, patience: int) -> np.ndarray:
    """Bars from each origin until price trades back through it.

    `patience` for an origin that never did, which is a **censor** and not a
    value: every reader below has to treat it as "at least this long".

    The walk starts `right + 1` bars after the pivot, because a pivot is not
    knowable until its right-hand bars have closed - counting from the pivot
    itself would include bars nobody could have acted on, which on a
    first-passage time is the few bars most likely to end it.
    """
    bars = feed.bars
    band = atr(bars)
    at, side = pivots(feed, left, right)
    n = len(bars)
    out = []
    for k in range(at.size):
        i = int(at[k])
        if not np.isfinite(band[i]) or band[i] <= 0:
            continue
        up = side[k] == 1
        origin = float(bars.low[i]) if up else float(bars.high[i])
        waited = patience
        for j in range(i + right + 1, min(i + right + 1 + patience, n)):
            back = bars.low[j] <= origin if up else bars.high[j] >= origin
            if back:
                waited = j - (i + right + 1)
                break
        out.append(waited)
    return np.asarray(out, dtype=float)


def hazard(waited: np.ndarray, age: int, window: int, patience: int) -> tuple[int, float] | None:
    """`(at risk, share returning within `window`)` among those alive at `age`.

    Alive means `waited > age`. An origin censored at `patience` is alive at
    every age below it and is **excluded from the numerator only when the
    window would reach past the censor**, which is where a naive version
    silently counts "did not return" as "returned late".
    """
    alive = waited > age
    if age + window > patience:
        return None
    risk = int(alive.sum())
    if risk < 200:
        return None
    returned = int(((waited > age) & (waited <= age + window)).sum())
    return risk, returned / risk


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(CHEAP))
    parser.add_argument("--frames", default="M15,H1")
    parser.add_argument("--left", type=int, default=5)
    parser.add_argument("--right", type=int, default=3)
    parser.add_argument("--patience", type=int, default=500)
    parser.add_argument("--arms", default="real,shuffled")
    args = parser.parse_args()

    print(
        "Is an unreturned origin due? The hazard of returning, by how long it has waited.\n"
        "Rising means due. Flat means memoryless. Falling means the opposite of due,\n"
        f"and the expected remaining wait grows. Patience {args.patience} bars.\n"
    )
    names = [s.strip() for s in args.symbols.split(",") if s.strip()]
    for frame in (f.strip() for f in args.frames.split(",") if f.strip()):
        print("=" * 78)
        print(f"  {frame}")
        print("=" * 78)
        for arm in (a.strip() for a in args.arms.split(",") if a.strip()):
            pooled = []
            for symbol in names:
                probe = read(symbol, frame, 0.0, DEEP)
                if probe is None:
                    continue
                feed = read(symbol, frame, point_of(symbol, float(probe.bars.close[-1])), DEEP)
                if feed is None or len(feed.bars) < 400:
                    continue
                if arm == "shuffled":
                    from leg_lengths import shuffle_days

                    feed = shuffle_days(feed, seed=23)
                pooled.append(waits(feed, args.left, args.right, args.patience))
            if not pooled:
                continue
            waited = np.concatenate(pooled)
            head = "".join(f"{f'+{w}b':>10}" for w in WINDOWS)
            print(f"    {arm:<10}{'age':>5}{'at risk':>10}{head}")
            for age in AGES:
                cells = [hazard(waited, age, w, args.patience) for w in WINDOWS]
                shown = [c for c in cells if c]
                if not shown:
                    continue
                risk = shown[0][0]
                row = "".join(f"{c[1]:>9.1%}" + " " if c else f"{'-':>10}" for c in cells)
                print(f"    {'':<10}{age:>5}{risk:>10,}{row}")
            print()


if __name__ == "__main__":
    main()
