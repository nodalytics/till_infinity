"""Which recursion does Deriv run? Answered from history, not from waiting.

`till_infinity/structures/vol/projection.py` accumulates this live, and live it
is slow: the two candidate conventions differ by `sigma^2 T / 2`, which at 1h is
0.4% of one standard deviation, so `Calibration.resolved` does not go true until
of order fifty thousand settled bars have gone through it. That is weeks of
desk time to answer a question whose evidence already exists.

**It does not have to be waited for.** A settled observation is a price at `t`
and a price at `t + T`, and a closed bar is exactly that pair - its open and its
close. Every bar ever printed is therefore an observation this calibration could
have had, and `seqcache.py` already has 9.4M of them on disk.

## The arithmetic, before the run

The conventions are `S exp(-sigma^2/2 dt + sigma dW)`, which makes **price** a
martingale, and `S exp(sigma dW)`, which makes **log price** one. Scoring an
outcome under the wrong one displaces the probability integral transform by

    z shift = (sigma^2 T / 2) / (sigma sqrt(T)) = sigma sqrt(T) / 2

so the mean PIT moves by about `phi(0) * sigma sqrt(T) / 2`, against a standard
error of `1 / sqrt(12 n)`. Two things follow and they decide the whole design:

* **Longer bars separate better.** The shift grows as `sqrt(T)` while the error
  does not care what `T` is. At 1d on Volatility 75 the shift is 0.0078 and 2,811
  bars give an error of 0.0054 - 1.4 sigma, not enough alone. Pooled over the
  twenty-two feeds it is about 6.7 sigma. **At 3m the shift is 0.00045 and fifty
  thousand bars give 0.0013, so that cell cannot answer the question at any
  sample this venue holds.** It is still run, and reported as unable rather than
  as negative.
* **Bigger sigma separates better**, so Volatility 250 (1s) carries more
  information per bar than Volatility 10, and a pooled answer that ignored that
  would be throwing away the strongest feeds.

## The control that makes it a measurement

Everything here is run first against **simulated paths built with a known
convention**, at each feed's own sigma and each timeframe's own `T`. If the test
cannot recover the convention it was given, it cannot report Deriv's - and both
directions are checked, because a test that always answers `ito` would look
perfect on an `ito` truth and be worthless.

    ./.secrets/lab.sh run research/harness/convention.py
"""

from __future__ import annotations

import math
import re
import sys

import numpy as np

from research.harness import seqlab
from till_infinity.structures.vol import projection as pj

#: Seconds per bar, from the same table `seqlab` annualises with.
SECONDS = {k: pj.SECONDS_PER_YEAR / v for k, v in seqlab.PER_YEAR.items()}

#: How many simulated paths per control cell.
CONTROL_DRAWS = 40_000


def production_name(broker: str) -> str:
    """`Volatility 75 (1s) Index` -> `volatility_75_1s_index`.

    The desk and the terminal spell the same instrument differently, and
    `stated.NAMED` - which is what supplies sigma - only matches the desk's
    spelling. Getting this wrong returns `None` for every feed and reads as
    "nothing is projectable" rather than as a naming bug.
    """
    found = re.match(r"^Volatility (\d+)(?: \(1s\))? Index$", broker.strip())
    if not found:
        return broker.strip().lower().replace(" ", "_")
    one_sec = "(1s)" in broker
    return f"volatility_{found.group(1)}{'_1s' if one_sec else ''}_index"


def settle_series(
    feed: str, bars: dict[str, np.ndarray], seconds: float
) -> dict[str, pj.Calibration]:
    """Score both conventions over every bar in one series.

    Open to close, which is the same pair the live engine hook uses, so a
    number here and a number there are the same measurement.
    """
    out = {c: pj.Calibration(convention=c) for c in pj.CONVENTIONS}
    opens, closes = bars["open"], bars["close"]
    for convention in pj.CONVENTIONS:
        cal = out[convention]
        # One cone per series rather than per bar: it depends only on the
        # price it starts from, and `Cone.pit` rescales by that price, so a
        # single cone at price 1 scores every bar correctly.
        base = pj.project(feed, 1.0, seconds, convention=convention)
        if base is None:
            return {}
        for opened, close in zip(opens, closes, strict=True):
            if opened > 0 and close > 0:
                cal.record(base, close / opened)
    return out


def pooled(cals: list[pj.Calibration]) -> tuple[int, float, float]:
    """Total n, mean PIT and its bias in standard errors, over many series."""
    n = sum(c.n for c in cals)
    if n < 2:
        return 0, float("nan"), float("nan")
    total = sum(c.mean * c.n for c in cals if c.n)
    mean = total / n
    return n, mean, (mean - 0.5) / math.sqrt(1.0 / (12.0 * n))


def control(rng: np.random.Generator) -> None:
    """Can this recover a convention it was given? Both directions."""
    print("=" * 78)
    print("CONTROL - simulated paths at a known convention")
    print("=" * 78)
    print(f"{'truth':8} {'timeframe':10} {'n':>9} {'ito bias':>11} {'plain bias':>11}  verdict")

    for truth in pj.CONVENTIONS:
        for interval in ("1h", "1d"):
            seconds = SECONDS[interval]
            cals = {c: pj.Calibration(convention=c) for c in pj.CONVENTIONS}
            for broker in seqlab.VOLATILITY[:8]:
                feed = production_name(broker)
                sigma = pj.sigma_for(feed, seconds)
                if sigma is None:
                    continue
                drift = pj.drift_for(feed, seconds, truth)
                ratios = np.exp(drift + sigma * rng.normal(0.0, 1.0, CONTROL_DRAWS // 8))
                for convention in pj.CONVENTIONS:
                    cone = pj.project(feed, 1.0, seconds, convention=convention)
                    for r in ratios:
                        cals[convention].record(cone, float(r))
            got = {c: pooled([cals[c]]) for c in pj.CONVENTIONS}
            best = min(pj.CONVENTIONS, key=lambda c: abs(got[c][2]))
            mark = "RECOVERED" if best == truth else "*** WRONG ***"
            print(
                f"{truth:8} {interval:10} {got['ito'][0]:>9,} "
                f"{got['ito'][2]:>11.2f} {got['plain'][2]:>11.2f}  {mark}"
            )
    print()


def main() -> int:
    rng = np.random.default_rng(19)
    control(rng)

    print("=" * 78)
    print("DERIV - every cached Volatility bar, both conventions")
    print("=" * 78)
    shift_at = {}
    for interval in seqlab.GRID:
        seconds = SECONDS[interval]
        # The separation this timeframe can offer, before looking at any data.
        sig = pj.sigma_for("volatility_75_index", seconds) or 0.0
        shift_at[interval] = 0.3989 * sig / 2.0

    print(
        f"{'timeframe':10} {'feeds':>6} {'n':>10} {'ito bias':>10} {'plain bias':>11} "
        f"{'sep/SE':>8}  verdict"
    )

    grand: dict[str, list[pj.Calibration]] = {c: [] for c in pj.CONVENTIONS}
    for interval in seqlab.GRID:
        seconds = SECONDS[interval]
        per: dict[str, list[pj.Calibration]] = {c: [] for c in pj.CONVENTIONS}
        feeds = 0
        for broker in seqlab.VOLATILITY:
            try:
                bars = seqlab.load(broker, interval)
            except Exception:
                continue
            feed = production_name(broker)
            got = settle_series(feed, bars, seconds)
            if not got:
                continue
            feeds += 1
            for convention in pj.CONVENTIONS:
                per[convention].append(got[convention])
                grand[convention].append(got[convention])
        if not feeds:
            print(f"{interval:10} {'-':>6}  no cached bars")
            continue
        stats = {c: pooled(per[c]) for c in pj.CONVENTIONS}
        n = stats["ito"][0]
        # How many standard errors apart the two hypotheses are at this sample.
        se = math.sqrt(1.0 / (12.0 * n)) if n > 1 else float("inf")
        separation = shift_at[interval] / se if se else float("inf")
        best = min(pj.CONVENTIONS, key=lambda c: abs(stats[c][2]))
        verdict = best if separation >= 3.0 else "cannot resolve"
        print(
            f"{interval:10} {feeds:>6} {n:>10,} {stats['ito'][2]:>10.2f} "
            f"{stats['plain'][2]:>11.2f} {separation:>8.1f}  {verdict}"
        )

    print()
    stats = {c: pooled(grand[c]) for c in pj.CONVENTIONS}
    n = stats["ito"][0]
    print(f"POOLED over every timeframe and feed: n = {n:,}")
    for convention in pj.CONVENTIONS:
        _, mean, bias = stats[convention]
        print(f"  {convention:6} mean PIT {mean:.6f}   bias {bias:+.2f} SE")
    best = min(pj.CONVENTIONS, key=lambda c: abs(stats[c][2]))
    print(f"\nCloser to uniform: {best}")
    print(
        "Read the per-timeframe table before this line: pooling mixes cells that "
        "can resolve the question with cells that cannot."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
