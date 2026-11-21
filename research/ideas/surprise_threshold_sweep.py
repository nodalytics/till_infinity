"""How often the fold clears each threshold, from 1.3 sigma up.

The operator, 2026-11-21: *"can you run the trigger % for 1.3 sigma?"* - the
floor the band in `strategies/surprise.py` can now be set to, and the number
the volume argument in `research/docs/surprise-band.md` was **estimated**
rather than measured: *"a standardised innovation reaches 1.3 on roughly a
fifth of them, so 1.3 is something like a sixteen-fold increase"*. That was a
Gaussian guess about a quantity whose whole point is that it is not Gaussian,
so this measures it.

## What is reported

Per feed, the share of readouts clearing each threshold, and the share landing
**inside** the band [1.3, 3.5] - which is the quantity that decides the
proposal rate if both ends are set, and is not the difference between two
tail rates when the ceiling bites.

`ratio` is the multiple on today's flow: the 1.3 rate over the 3.0 rate. The
estimate on record is sixteen.

## Why the shape matters more than the level

`origin-returns-turn-at-z-one-three` has returns turning at z 1.3 to 1.95 and
non-returners reaching 2.2, so if this rule is a reversion rule its edge is at
the **low** end and the 3.0 floor sits above almost every return that study
could see. But a fat-tailed innovation reaches 1.3 far more often than a
Gaussian one, so the cost of opening the floor is larger than the Gaussian
guess - the two effects push opposite ways and only the measured rate settles
which dominates.

Everything else is `index_surprise_reach`'s: the same production fold, the
same noise, the same feeds and loaders, so the rows here and there are
comparable.

Run as:

    uv run python research/ideas/surprise_threshold_sweep.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from index_surprise_reach import (
    ADMITTED,
    BARS,
    CSV_FRAME,
    FOLD_FRAME,
    INDICES,
    NOISE,
    SLOWER,
    fold,
    load_cached,
    read_index,
)

from till_infinity.statespace.proposing import TRIGGER

#: The thresholds swept. 1.3 is the operator's floor, 3.0 the producer's
#: trigger, 3.5 the ceiling the band work added.
STEPS: tuple[float, ...] = (1.3, 1.95, 2.2, 2.5, 3.0, 3.5, 4.0)

#: The band both ends of the new setting would describe.
BAND: tuple[float, float] = (1.3, 3.5)


def line(group: str, feed: str, values: np.ndarray) -> str:
    inside = float(np.mean((values >= BAND[0]) & (values <= BAND[1])))
    at = {step: float(np.mean(values >= step)) for step in STEPS}
    ratio = at[1.3] / at[TRIGGER] if at[TRIGGER] > 0 else float("nan")
    cells = "".join(f"{100 * at[step]:>8.2f}%" for step in STEPS)
    return f"  {group:<10}{feed:<22}{values.size:>8,}{cells}{100 * inside:>9.2f}%{ratio:>8.1f}x"


def main() -> None:
    print(
        f"Share of readouts clearing each threshold. {CSV_FRAME}/{FOLD_FRAME} bars\n"
        f"through the production fold at noise {NOISE} x range/4, same as\n"
        "index_surprise_reach. 'in band' is [1.3, 3.5], the share a floor AND\n"
        "ceiling together would admit. 'ratio' is the 1.3 rate over the 3.0\n"
        "rate: the multiple on today's proposal flow, estimated at 16 in\n"
        "research/docs/surprise-band.md from a Gaussian the data does not obey.\n"
    )
    head = "".join(f"{f'>={step}':>9}" for step in STEPS)
    print(f"  {'group':<10}{'feed':<22}{'bars':>8}{head}{'in band':>10}{'ratio':>9}")

    seen: dict[str, list[float]] = {}
    for group, names in (("admitted", ADMITTED), ("slower", SLOWER)):
        for name in names:
            got = load_cached(name, FOLD_FRAME)
            if got is None:
                continue
            cut = {k: np.asarray(v, dtype=float)[-BARS:] for k, v in got.items()}
            values, _ = fold(
                cut["time"], cut["close"], cut["high"], cut["low"], cut["volume"], name
            )
            if values.size < 500:
                continue
            print(line(group, name, values))
            seen.setdefault(group, []).append(float(np.mean(values >= BAND[0])))

    for name, where in INDICES:
        feed = read_index(name, CSV_FRAME, float("nan"), where=where)
        if feed is None:
            continue
        bars = feed.bars
        seconds = bars.ts.astype(np.float64) / 1e9
        order = np.argsort(seconds, kind="stable")
        values, _ = fold(
            seconds[order][-BARS:],
            np.asarray(bars.close, dtype=float)[order][-BARS:],
            np.asarray(bars.high, dtype=float)[order][-BARS:],
            np.asarray(bars.low, dtype=float)[order][-BARS:],
            np.asarray(feed.quotes, dtype=float)[order][-BARS:],
            name,
        )
        if values.size < 500:
            continue
        print(line("index", name, values))
        seen.setdefault("index", []).append(float(np.mean(values >= BAND[0])))

    print()
    for group in ("admitted", "slower", "index"):
        got = seen.get(group) or []
        if got:
            print(
                f"  {group:<10}at 1.3 sigma: {100 * min(got):.2f}% to {100 * max(got):.2f}% of bars"
            )


if __name__ == "__main__":
    main()
