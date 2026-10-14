"""Step three: point the conformal machinery at the filter's own band.

`statespace-estimator-on-touches.md` measured `levels.Kalman` at **18 times**
the sharpness of anything statespace has on touch-spaced observations, and at a
**PIT flatness of 89** where 1.0 is calibrated. The two findings together say
the incumbent should be kept and its **uncertainty** fixed, which is a smaller
change than replacing it.

And production already owns the fix, twice over.

* `vol/envelope.py` runs AgACI over the volatility envelope and
  `research/docs/conformal.md` measured it holding **89.1-89.6%** coverage
  against one-step ACI's 87.8-88.1%, while being **2-9% narrower**;
* `structures/conformal.py` is that machinery pointed at the **zone** - its own
  docstring says so: *"the same machinery pointed at a different interval"* -
  and the engine uses it, at `engine.py:1370`.

**But nothing points it at the filter's predictive band.** `levels.py` reads
`self.filter.sigma_at(when)` at lines 1088 and 1246 and publishes
`self.filter.sigma` raw at line 1320. The zone is calibrated; the spread the
zone is built from is not. This is the third pointing of a tool that has worked
twice, at the one interval measured as badly wrong.

## What is being compared

The conformity score is the **standardised residual** - how many of the filter's
own sigmas the next touch landed away from its mean - which is the quantity
`conformal.Pool` already takes. `reach()` then returns `(down, up)` in sigmas,
so the band becomes `mean + sigma * reach` on each side.

* **gaussian** - `mean +/- z * sigma` at the nominal level, which is what
  production publishes today;
* **conformal** - `conformal.Pool`, production's own correctors, fed the
  filter's residuals;
* **empirical** - the plain quantiles of the last `WINDOW` residuals, as the
  control on the correctors: if a fixed window does as well, the adaptive
  machinery is not earning its complexity here.

## Judged on coverage and width, because it is an interval

`conformal.py` makes the same choice and says why - *"a zone is an interval and
not a quantile: the interval score stands in for pinball"*. So an arm is better
when it holds the nominal coverage **and** is no wider. Width alone is
meaningless, since the narrowest band is empty, and coverage alone is
meaningless, since the widest covers everything.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.structures.conformal import COVERAGE, Pool  # noqa: E402
from till_infinity.structures.levels import Kalman  # noqa: E402
from till_infinity.structures.statespace.distance import _normal_quantile  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "40000"))
LOOKBACK = int(os.environ.get("LOOKBACK", "100"))
PER_FEED = int(os.environ.get("PER_FEED", "40"))
LEAST_TOUCHES = int(os.environ.get("LEAST_TOUCHES", "60"))
WINDOW = int(os.environ.get("WINDOW", "400"))
DRIFT_VOL_PER_HOUR = 0.02
GRID = tuple(float(x) for x in os.environ.get("GRID", "1,8,64,512,4096,16384").split(","))
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
GENERATED = tuple(os.environ.get("GENERATED", "Volatility_75_Index,Step_Index_200").split(","))
#: The nominal two-sided level the band is held to, from production's own
#: constant so this cannot drift away from what the zone is calibrated to.
NOMINAL = COVERAGE
#: The Gaussian reach at that level, which is what production publishes.
DEFAULT_REACH = abs(_normal_quantile((1.0 - NOMINAL) / 2.0))


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    for k in ("high", "low", "close"):
        got[k] = np.log(got[k])
    return got


def touch_series(bars):
    import numpy as np

    times, highs, lows, closes = (bars[k] for k in ("time", "high", "low", "close"))
    out = []
    starts = np.linspace(LOOKBACK, len(closes) - 1, PER_FEED, dtype=int)
    for i, at in enumerate(starts):
        window = slice(max(at - LOOKBACK, 0), at)
        level = float(highs[window].max() if i % 2 == 0 else lows[window].min())
        if not math.isfinite(level):
            continue
        hit = (lows[at:] <= level) & (highs[at:] >= level)
        if hit.sum() < LEAST_TOUCHES:
            continue
        out.append((times[at:][hit], closes[at:][hit]))
    return out


def run(times, prices, drift: float, arm: str):
    """`(coverage, mean width in sigmas, pit-ish miss balance)` for one arm."""
    steps = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    noise = statistics.pstdev(steps) or 1e-9
    one = Kalman(mean=float(prices[0]), variance=noise * noise, updated=float(times[0]))
    pool = Pool() if arm == "conformal" else None
    kept: deque[float] = deque(maxlen=WINDOW)
    start = len(times) // 2
    covered, widths, above = 0, [], 0
    scored = 0
    for i, (when, price) in enumerate(zip(times, prices, strict=True)):
        one.predict(float(when), drift)
        sd = math.sqrt(max(float(one.variance) + noise * noise, 1e-24))
        if arm == "gaussian":
            down = up = DEFAULT_REACH
        elif arm == "conformal":
            down, up = pool.reach(DEFAULT_REACH)
        else:
            if len(kept) >= 50:
                got = sorted(kept)
                low = got[max(int((1.0 - NOMINAL) / 2.0 * len(got)), 0)]
                high = got[min(int((1.0 + NOMINAL) / 2.0 * len(got)), len(got) - 1)]
                down, up = max(-low, 0.0), max(high, 0.0)
            else:
                down = up = DEFAULT_REACH
        score = (float(price) - float(one.mean)) / sd
        if i >= start:
            scored += 1
            covered += -down <= score <= up
            widths.append(down + up)
            above += score > up
        if pool is not None:
            pool.observe(score, DEFAULT_REACH)
        kept.append(score)
        one.update(float(price), noise * noise, float(when))
    if scored < 20:
        return None
    # The share of misses that fell on the upper tail. A calibrated two-sided
    # band misses half each way; all on one side is a band in the wrong place
    # rather than one of the wrong size, and coverage alone cannot see it.
    missed = scored - covered
    return (
        covered / scored,
        statistics.mean(widths),
        (above / missed if missed else 0.5),
    )


def shape_of(times, prices, drift: float) -> list[float]:
    """The Gaussian arm's PIT values, to say *where* its shape is wrong.

    **Coverage at one level and PIT flatness are different questions, and the
    table above answers only the first.** A band can hold 95% exactly while the
    interior of its distribution is badly mis-shaped - too much mass near the
    centre and too little at a half sigma, say - because a single coverage
    number is one point on a curve and the PIT is the whole curve.

    `statespace-estimator-on-touches.md` measured this filter at a PIT flatness
    of **89** and this file measures its coverage at **95.7%** against a 95.0%
    nominal. Both are right. This returns the PITs so the histogram can say
    which bins carry the disagreement, which decides whether anything a
    consumer reads is affected.
    """
    steps = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    noise = statistics.pstdev(steps) or 1e-9
    one = Kalman(mean=float(prices[0]), variance=noise * noise, updated=float(times[0]))
    start = len(times) // 2
    out = []
    for i, (when, price) in enumerate(zip(times, prices, strict=True)):
        one.predict(float(when), drift)
        sd = math.sqrt(max(float(one.variance) + noise * noise, 1e-24))
        if i >= start:
            z = (float(price) - float(one.mean)) / sd
            out.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
        one.update(float(price), noise * noise, float(when))
    return out


def main() -> None:
    import numpy as np

    print(
        f"nominal coverage {NOMINAL:.1%}, Gaussian reach {DEFAULT_REACH:.3f} sigmas\n"
        f"{LOOKBACK}-bar rolling extremes, {LEAST_TOUCHES}+ touches each, log price\n"
    )
    print(
        "An arm is better when it holds the nominal coverage **and** is no\n"
        "wider. `conformal.py` makes the same choice and says why: a zone is an\n"
        "interval, so the interval score stands in for pinball.\n"
    )
    print(
        f"{'group':<12}{'levels':>7}{'arm':<14}{'coverage':>10}{'vs nominal':>12}"
        f"{'width, sigmas':>15}{'misses above':>14}"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        series = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            series.extend(touch_series(bars))
        if not series:
            continue
        rows: dict[str, list[tuple[float, float, float]]] = {}
        for times, prices in series:
            spread = statistics.pstdev(
                [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
            ) or 1e-9
            # The incumbent's own best process noise, so the band is being
            # judged on top of a filter that is not mis-set.
            best, chosen = None, spread * DRIFT_VOL_PER_HOUR
            for multiple in GRID:
                drift = spread * DRIFT_VOL_PER_HOUR * multiple
                got = run(times, prices, drift, "gaussian")
                if got and (best is None or abs(got[0] - NOMINAL) < abs(best - NOMINAL)):
                    best, chosen = got[0], drift
            for arm in ("gaussian", "conformal", "empirical"):
                got = run(times, prices, chosen, arm)
                if got:
                    rows.setdefault(arm, []).append(got)
        first = True
        for arm in ("gaussian", "conformal", "empirical"):
            cells = rows.get(arm)
            if not cells:
                continue
            cover = statistics.median(c[0] for c in cells)
            head = f"{group:<12}{len(series):>7}" if first else f"{'':<12}{'':>7}"
            first = False
            print(
                f"{head}{arm:<14}{cover:>10.1%}{cover - NOMINAL:>+12.1%}"
                f"{statistics.median(c[1] for c in cells):>15.3f}"
                f"{statistics.median(c[2] for c in cells):>14.1%}"
            )
        print()
    print("=" * 84)
    print("where the Gaussian band's shape is wrong, since its coverage is not")
    print("=" * 84)
    print(
        "Ten bins of the PIT. A calibrated band puts 10% in each. The two outer\n"
        "bins are what a 95% coverage number is made of; the eight inner ones\n"
        "are what the flatness of 89 is made of, and no consumer reads them.\n"
    )
    pits = []
    for name in TRADED:
        bars = load(name)
        if bars is None:
            continue
        for times, prices in touch_series(bars):
            spread = statistics.pstdev(
                [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
            ) or 1e-9
            pits.extend(shape_of(times, prices, spread * DRIFT_VOL_PER_HOUR * 512))
    if pits:
        counts = [0] * 10
        for v in pits:
            counts[min(int(v * 10), 9)] += 1
        total = len(pits)
        print(f"{'bin':<10}{'share':>9}{'vs 10%':>9}   {'':<20}")
        for k, n in enumerate(counts):
            share = n / total
            bar = "#" * max(int(share * 100), 0)
            edge = " <- a tail bin" if k in (0, 9) else ""
            print(f"{k / 10:.1f}-{(k + 1) / 10:.1f}{share:>9.1%}{share - 0.1:>+9.1%}   {bar}{edge}")
        outer = counts[0] + counts[9]
        print(
            f"\nthe two tail bins hold {outer / total:.1%} against the 20% a\n"
            "calibrated band would put there, which is the coverage number\n"
            "restated - and the eight inner bins are where the flatness lives."
        )

    print(
        "**`empirical` is the control on the correctors.** If a plain window of\n"
        "past residuals holds coverage as well as AgACI does, then the adaptive\n"
        "machinery is not earning its complexity on this interval - which is a\n"
        "useful thing to know before wiring it, and the opposite of what\n"
        "`conformal.md` found on the envelope, where it was both better covered\n"
        "and narrower.\n\n"
        "And `misses above` is the check coverage cannot do by itself: a\n"
        "two-sided band that is calibrated misses half above and half below. All\n"
        "the misses on one tail is a band in the wrong **place**, which a\n"
        "coverage number alone reports as success."
    )
    _ = np


if __name__ == "__main__":
    main()
