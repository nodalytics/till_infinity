"""Does a higher frame's zone tell the lower frame's entry anything?

The operator, 2026-11-21: *"i think we should make it multitimeframe
confluence instead of just one... include 1h and 4h to it too... there should
be a story from the higher timeframe to the lower timeframe"*, and then the
clarification that decides the design: *"it does not need to agree exactly"*.

## Why the exact version is already refuted, and this is not it

[`reactive-zones.md`](../docs/reactive-zones.md) measured confluence as a
**vote** - every frame has to agree - and it dies of arithmetic rather than of
edge:

| rung | n | share |
|---|---:|---:|
| pattern | 271 | 100% |
| + quiet | 106 | 39.1% |
| + TSI slow | 17 | 6.3% |
| + TSI both frames | **1** | 0.4% |
| + a rejection candle on the middle frame | **0** | 0% |

*"Three frames agreeing happens once in two years across five instruments, and
four conditions agreeing happens never... a conjunction of independent-ish
gates multiplies its way out of existence long before it runs out of edge."*

**A tolerance is not a conjunction.** Asking whether a 15m zone sits *near* a
4h zone turns a binary agreement into a **distance**, and a distance has a
sweep. That is the whole difference between this file and the ladder above, and
it is the operator's clarification doing the work.

## What the higher frames are known to carry

[`bjorgum.md`](../docs/bjorgum.md) measured the same zones at 15m, 1h and 4h
and the three frames are not equal:

| | 15m | 1h | 4h |
|---|---:|---:|---:|
| never-flipped effect | **+23.6** | +12.3 | +5.0 |
| *its control* | *+0.9* | ***+5.6*** | *0.0* |

So 15m is clean, **4h is clean on 481 visits**, and **1h is the one where half
the effect is in the control**. It also found the best cell on the book at 4h -
a zone with three to five prior visits breaks 25.3% against a 37.3% base. That
is why 4h is the frame this study leads with and 1h is reported beside it
rather than pooled into it.

## What is measured

For every 15m zone **visit** - price entering the band, which is the live
rule's entry trigger - the distance to the nearest higher-frame zone, in units
of the 15m ATR at that moment. Then, swept over a tolerance ladder:

1. **Retention.** The share of entries kept. This is the number that killed the
   vote, so it is reported first and at every rung. A tolerance that retains 6%
   is the same wall under a different name.
2. **The outcome**, as the forward excursion from the visit in ATR, so the
   answer is in the units a stop is set in.
3. **Two arms.** `shuffled` reorders whole days and rebuilds every frame, so
   the geometry of approaching a band at that distance survives and the path's
   memory does not. `placebo` uses `zones_of(placebo=True)` - the same distance,
   mirrored, with no pivot behind it - because
   `a-return-rate-is-geometry` records an 82% return rate matched by exactly
   that arm on every class.

**The thing that would make this worth building is a tolerance where retention
is high and the real arm separates from both controls.** If separation only
appears where retention collapses, this is the vote again and the answer is no.

Run as:

    uv run python research/ideas/zone_story.py --years 2
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import (
    CATALOGUE,
    MULT,
    SYMBOLS,
    Candles,
    Zone,
    adaptive_band,
    atr,
    fold,
    load,
    shuffled,
    window,
    zones_of,
)

#: Tolerances in 15m ATR. **0.0 is overlap** - the band edges touching - and
#: the rest widen from there. Swept rather than chosen: `sweep-thresholds-on-the-mean-not-z`
#: records a z grid faking a ridge at the chosen threshold where the mean grid
#: was monotone, so the shape of the whole ladder is the evidence.
TOLERANCES = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)

#: Bars after the visit to measure the excursion over. 16 at 15m is four hours,
#: which is one bar of the frame doing the selecting.
FORWARD = 16


def visits(bars: Candles, zones: list[Zone]) -> list[tuple[int, Zone]]:
    """Every bar at which price enters a zone's band from outside it.

    The **entry**, not the whole stay: a bar inside a band it was already
    inside is the same visit continuing, and counting it again would weight a
    long consolidation as many entries. `overlapping-windows-inflate-permutation-nulls`
    is what that costs a null.
    """
    found: list[tuple[int, Zone]] = []
    high = np.maximum(bars.open, bars.close)
    low = np.minimum(bars.open, bars.close)
    for zone in zones:
        inside = False
        for index in range(zone.at, len(bars)):
            now = low[index] <= zone.top and high[index] >= zone.bottom
            if now and not inside:
                found.append((index, zone))
            inside = now
    return found


def nearest(level: float, others: list[Zone], before: int, span: int) -> float | None:
    """Distance from `level` to the nearest higher-frame band, in price.

    `before` is the 15m bar index and `span` the fold ratio, so a higher-frame
    zone counts only once **its own** confirming bar has closed. Reading a 4h
    zone at a 15m bar inside the 4h bar that confirmed it is lookahead of up to
    sixteen bars, which is the defect `#431` was opened for in another guise.
    """
    best: float | None = None
    for zone in others:
        if zone.at * span > before:
            continue
        if zone.bottom <= level <= zone.top:
            return 0.0
        gap = zone.bottom - level if level < zone.bottom else level - zone.top
        if best is None or gap < best:
            best = gap
    return best


def excursion(bars: Candles, index: int, resistance: bool, band: float) -> float | None:
    """Forward move from a visit, in ATR, signed the way the zone is traded.

    A resistance is sold and a support bought, so a favourable move is down
    from a resistance and up from a support. Measured on the **close** at the
    horizon rather than on the best price reached, because the best price is a
    maximum over a path and `let-shuffled-twin-name-the-mechanical-observables`
    records overshoot at an extreme being definitional.
    """
    if band <= 0 or index + FORWARD >= len(bars):
        return None
    moved = float(bars.close[index + FORWARD] - bars.close[index])
    return (-moved if resistance else moved) / band


def study(bars15: Candles, slow: Candles, span: int, *, placebo: bool) -> dict:
    """One arm: every 15m visit, its distance to the slow frame, its outcome."""
    band15 = adaptive_band(bars15, 50.0)
    reach = atr(bars15)
    fast = zones_of(bars15, band15, MULT)
    slower = zones_of(slow, adaptive_band(slow, 50.0), MULT, placebo=placebo)
    rows: list[tuple[float, float]] = []
    for index, zone in visits(bars15, fast):
        here = float(reach[index])
        if not np.isfinite(here) or here <= 0:
            continue
        gap = nearest(
            zone.level if hasattr(zone, "level") else (zone.top + zone.bottom) / 2.0,
            slower,
            index,
            span,
        )
        if gap is None:
            continue
        got = excursion(bars15, index, zone.resistance, here)
        if got is None:
            continue
        rows.append((gap / here, got))
    return {"rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--slow", default="4h,1h")
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--seed", type=int, default=23)
    args = parser.parse_args()

    print(
        "Does a higher frame's zone tell a 15m entry anything?\n"
        f"Every 15m zone visit, its distance to the nearest higher-frame band in 15m ATR,\n"
        f"and the {FORWARD}-bar forward close in ATR. Retention first: the vote died at 0.4%.\n"
    )
    from reactive_zones import RATIOS

    for slow_name in (s.strip() for s in args.slow.split(",") if s.strip()):
        span = RATIOS[args.unit][slow_name] // RATIOS[args.unit]["15m"]
        print("=" * 92)
        print(f"the story from {slow_name} down to 15m   (one {slow_name} bar is {span} 15m bars)")
        print("=" * 92)
        arms: dict[str, list[tuple[float, float]]] = {}
        for arm in ("real", "shuffled", "placebo"):
            pooled: list[tuple[float, float]] = []
            for symbol in (s.strip() for s in args.symbols.split(",") if s.strip()):
                try:
                    base = load(Path(args.catalogue), symbol)
                except SystemExit:
                    continue
                if args.years > 0:
                    base = window(base, args.years)
                if arm == "shuffled":
                    base = shuffled(base, seed=args.seed)
                bars15 = fold(base, "15m", unit=args.unit)
                slow = fold(base, slow_name, unit=args.unit)
                pooled += study(bars15, slow, span, placebo=arm == "placebo")["rows"]
            arms[arm] = pooled
        base_n = len(arms["real"]) or 1
        print(
            f"  {'tol ATR':>8}{'kept':>8}{'share':>8}"
            f"{'real':>10}{'shuffled':>11}{'placebo':>10}{'real-best':>11}"
        )
        for tol in TOLERANCES:
            cells = {}
            for arm, rows in arms.items():
                near = [got for gap, got in rows if gap <= tol]
                cells[arm] = (len(near), statistics.mean(near) if near else 0.0)
            kept, real = cells["real"]
            worst = max(cells["shuffled"][1], cells["placebo"][1])
            print(
                f"  {tol:>8.2f}{kept:>8,}{100 * kept / base_n:>7.0f}%"
                f"{real:>+10.4f}{cells['shuffled'][1]:>+11.4f}{cells['placebo'][1]:>+10.4f}"
                f"{real - worst:>+11.4f}"
            )
        print(
            f"  all {base_n:,} visits pooled; 'real-best' is the real arm less the "
            f"stronger control,\n  which is the only column that can be an edge.\n"
        )


if __name__ == "__main__":
    main()
