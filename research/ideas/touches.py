"""The band, measured on touches instead of closes.

Asked on 2026-10-12, as the largest unaddressed debt in the package: every
measurement here has been on **bar closes**, which `__init__.py`'s fourth
principle warns about, and this is the first one that is not.

## Why this one measurement and not another

`statespace-backtest.md` ended with a recommendation: use the random walk's
band for stops, because its two-sigma coverage is 0.953 against a nominal
0.954 - right to one part in a thousand, and nothing in the package beats it.

**That number was measured on closes, and a stop is not hit on a close.** A
stop is hit the moment price *touches* it, at any instant inside the interval.
So the honest question is not whether the next close falls inside the band but
whether the whole path does, and those can differ enormously: a band that
contains 95% of closes might be breached intra-interval far more often,
because the interval's extremes are invisible to a close.

If the gap is large, the recommendation was wrong - and it was my own
recommendation, made one day earlier, so it is the first thing to check.

## What a stop actually touches

Not the mid. A long position's stop is hit when the **bid** reaches it, and a
short's when the **ask** does, so the honest band test is asymmetric and the
spread enters it directly. Tick data makes that measurable and bar data never
could, which is the second reason to do this on ticks rather than on a finer
bar series.

Three coverages per interval, therefore:

* **close** - does the next mid close fall inside? The number already
  reported, reproduced here so the comparison is on one sample.
* **touch, mid** - does the mid's whole path stay inside? What a
  mid-priced band would experience.
* **touch, quoted** - does the **bid** stay above the lower edge and the
  **ask** below the upper? What a stop on a real position experiences.

## The data, and its limits stated first

Tick stores hold 47 instruments with bid, ask and mid. The spans are **short**:
about five hours for XAUUSD and ten for BTCUSD at a tenth of a second, and
one and a half to three and a half days for the Deriv synthetics at one to two
seconds. EURUSD's store is corrupt - a bad CRC on its time array - so the
pair this desk trades most is absent.

That bounds the study rather than invalidating it. At ten-second intervals
XAUUSD gives about 1,700 observations and BTCUSD 3,400, each with roughly a
hundred ticks inside to describe the path - which is the resolution the
question needs. The synthetics carry the longer samples.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import statistics
from pathlib import Path

HOUR = 3600.0

#: The two traded instruments with readable ticks, then generated markets.
TRADED = ("XAUUSD", "BTCUSD")
GENERATED = (
    "Volatility_75_Index",
    "Volatility_100_Index",
    "Step_Index",
    "Boom_500_Index",
    "Range_Break_100_Index",
)

#: Interval lengths in seconds. Ten seconds and a minute, because the spans
#: are hours: an hour would leave eighty observations.
INTERVALS = tuple(int(v) for v in os.environ.get("INTERVALS", "10,60").split(","))

#: Smallest number of ticks inside an interval for its path to be described.
#: An interval with two ticks has no interior worth testing.
LEAST_TICKS = 5

TICKS = Path.home() / "till_infinity" / "data" / "seqlab" / "ticks"


def load(name: str):
    import numpy as np

    path = TICKS / f"{name}.tick.npz"
    if not path.exists():
        return None
    try:
        with np.load(path) as bundle:
            if not {"time", "bid", "ask"} <= set(bundle.keys()):
                return None
            order = np.argsort(bundle["time"])
            times = np.asarray(bundle["time"], dtype=float)[order]
            bids = np.asarray(bundle["bid"], dtype=float)[order]
            asks = np.asarray(bundle["ask"], dtype=float)[order]
    except Exception:
        # A corrupt store is a fact about the data, not an error to raise: one
        # of the 48 has a bad CRC and the study should report that rather than
        # stop.
        return None
    keep = (bids > 0) & (asks >= bids)
    return times[keep], bids[keep], asks[keep]


def intervals(times, bids, asks, seconds: int):
    """Group ticks into fixed intervals, keeping each one's whole path.

    Returns, per interval: the close of the mid, the mid's extremes, and the
    extremes of the **quoted** sides - the lowest bid and the highest ask -
    which is what a stop is reached by.
    """
    import numpy as np

    mids = (bids + asks) / 2.0
    edges = (times // seconds).astype(np.int64)
    out = []
    start = 0
    for i in range(1, len(edges) + 1):
        if i < len(edges) and edges[i] == edges[start]:
            continue
        if i - start >= LEAST_TICKS:
            out.append(
                {
                    "at": float(times[i - 1]),
                    "close": float(mids[i - 1]),
                    "mid_low": float(mids[start:i].min()),
                    "mid_high": float(mids[start:i].max()),
                    "bid_low": float(bids[start:i].min()),
                    "ask_high": float(asks[start:i].max()),
                    "ticks": i - start,
                }
            )
        start = i
    return out


def score(bars: list[dict], *, build, base: float, variance: float) -> dict:
    """Run a member on the closes, then test its band three ways.

    The band is asked for at the **next** interval's end and compared with the
    next interval's close, with the mid's path, and with the quoted path. One
    pass, three readings, so the three cannot differ by sample.
    """
    member = build(base)
    rows = {
        name: dict.fromkeys((1.0, 2.0, 3.0), 0) for name in ("close", "touch_mid", "touch_quoted")
    }
    counted = 0
    half = len(bars) // 2

    for i, bar in enumerate(bars):
        member.predict(bar["at"])
        member.update(bar["close"], variance, bar["at"])
        if i + 1 >= len(bars) or i < half:
            continue
        nxt = bars[i + 1]
        counted += 1
        for sigmas in (1.0, 2.0, 3.0):
            low, high = member.band(nxt["at"], sigmas)
            if low <= nxt["close"] <= high:
                rows["close"][sigmas] += 1
            if low <= nxt["mid_low"] and nxt["mid_high"] <= high:
                rows["touch_mid"][sigmas] += 1
            # A long's stop is reached by the **bid** and a short's by the
            # **ask**, so the quoted test asks whether the lowest bid held
            # above the lower edge and the highest ask below the upper.
            if low <= nxt["bid_low"] and nxt["ask_high"] <= high:
                rows["touch_quoted"][sigmas] += 1

    if counted < 100:
        return {}
    return {
        "counted": counted,
        **{
            f"{name}{int(sigmas)}": rows[name][sigmas] / counted
            for name in rows
            for sigmas in (1.0, 2.0, 3.0)
        },
    }


def fit_base(bars: list[dict], *, build, variance: float) -> float:
    """Sweep the walk's step on the first half, as everything else here does."""
    spread = (
        statistics.pstdev([b["close"] - a["close"] for a, b in itertools.pairwise(bars)]) or 1e-12
    )
    half = len(bars) // 2
    best, chosen = float("-inf"), 0.0
    for power in range(-4, 5):
        base = spread * (2.0**power)
        member = build(base)
        for bar in bars[:half]:
            member.predict(bar["at"])
            member.update(bar["close"], variance, bar["at"])
        if math.isfinite(member.loglike) and member.loglike > best:
            best, chosen = member.loglike, base
    return chosen


def main() -> None:
    from till_infinity.structures.statespace.nulls import Walk

    print(
        f"intervals {INTERVALS}s  least ticks {LEAST_TICKS}\n"
        "close    = the next close inside the band, which is what every earlier\n"
        "           measurement in this package tested.\n"
        "touch    = the next interval's whole mid path inside.\n"
        "quoted   = the lowest bid above the lower edge and the highest ask\n"
        "           below the upper, which is what a stop is reached by.\n"
        "nominal coverage is 0.683, 0.954 and 0.9973.\n"
    )
    print(
        f"{'instrument':<24}{'secs':>5}{'n':>6}{'ticks':>6}"
        f"{'close2':>9}{'touch2':>9}{'quoted2':>9}"
        f"{'close3':>9}{'touch3':>9}{'quoted3':>9}"
    )

    rows: list[dict] = []
    for name in TRADED + GENERATED:
        found = load(name)
        if found is None:
            print(f"{name:<24}{'unreadable - corrupt store or missing keys'}")
            continue
        times, bids, asks = found
        for seconds in INTERVALS:
            bars = intervals(times, bids, asks, seconds)
            if len(bars) < 300:
                continue
            spread = (
                statistics.pstdev([b["close"] - a["close"] for a, b in itertools.pairwise(bars)])
                or 1e-12
            )
            # The measurement variance is the quoted half-spread squared: on
            # ticks that is not a guess, it is the price's own granularity.
            variance = statistics.median(
                [((a - b) / 2.0) ** 2 for a, b in zip(asks[:5000], bids[:5000], strict=False)]
            )
            base = fit_base(bars, build=Walk, variance=variance)
            if base <= 0:
                continue
            got = score(bars, build=Walk, base=base, variance=variance)
            if not got:
                continue
            label = f"*{name}" if name in GENERATED else name
            print(
                f"{label:<24}{seconds:>5}{got['counted']:>6}"
                f"{statistics.median([b['ticks'] for b in bars]):>6.0f}"
                f"{got['close2']:>9.3f}{got['touch_mid2']:>9.3f}{got['touch_quoted2']:>9.3f}"
                f"{got['close3']:>9.3f}{got['touch_mid3']:>9.3f}{got['touch_quoted3']:>9.3f}"
            )
            rows.append({"label": label, "seconds": seconds, "spread": spread, **got})

    _summary(rows)


def _summary(rows: list[dict]) -> None:
    if not rows:
        print("\nno cells: no readable tick store had enough intervals")
        return
    print("\n== medians, and the gap the debt was about")
    print(f"{'arm':<12}{'cells':>6}{'1 sigma':>10}{'2 sigma':>10}{'3 sigma':>10}")
    traded = [r for r in rows if not r["label"].startswith("*")]
    pools = (("traded", traded), ("generated", [r for r in rows if r["label"].startswith("*")]))
    for tag, pool in pools:
        if not pool:
            continue
        print(f"  {tag}:")
        for arm, key in (
            ("close", "close"),
            ("touch mid", "touch_mid"),
            ("touch quoted", "touch_quoted"),
        ):
            print(
                f"{arm:<12}{len(pool):>6}"
                + "".join(
                    f"{statistics.median([r[f'{key}{s}'] for r in pool]):>10.3f}" for s in (1, 2, 3)
                )
            )
    if traded:
        gap = statistics.median([r["close2"] - r["touch_quoted2"] for r in traded])
        closes = statistics.median([r["close2"] for r in traded])
        quoted = statistics.median([r["touch_quoted2"] for r in traded])
        print(
            f"\n   On traded instruments the two-sigma band contains the next"
            f" close {closes:.3f}\n   of the time and holds a quoted path"
            f" {quoted:.3f} of the time: a gap of {gap:.3f}.\n"
            "   That gap is the whole content of the closes-versus-touches debt."
        )


if __name__ == "__main__":
    main()
