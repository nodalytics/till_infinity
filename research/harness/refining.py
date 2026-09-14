"""Does refining a level on a lower timeframe help, and if it stops helping, why?

**The claim.** A level found on a high timeframe can be sharpened by locating the
precise extreme on a lower one, and price rejects the refined level more often
than the coarse one. Measured on a deep panel it improved the rejection rate on
**15 of 15 cells**; measured on an independent later panel it did nothing.

Both of those can be true, and only two things make them so.

| | signature |
| --- | --- |
| **overfitting** | decays smoothly as the fitting sample shrinks, and has **no date** |
| **a regime change** | ignores sample size entirely, and has **a date** |

So the study is two cuts of one panel, made independently: **by size** and **by
era**. Whichever axis kills the effect names the cause, and the two answers call
for opposite responses - one retires the method, the other dates a regime and
keeps it.

## What this can and cannot say

It does not reproduce the original panel: the cache here reaches 2019 at four
hours and 2020 at one, where that study ran from 2012. So this measures the
**mechanism** on the data we hold rather than replicating that result, and a
disagreement between them is a difference of sample and not a contradiction.

What it adds instead is a control the original could not have. **The generated
family cannot have a refinable level**: `generated.md` has those feeds at
`H = 0.50` with no structure at any scale, so a refinement that helps there is
measuring the procedure and not the market. That is the cleanest available check
on the whole idea, and it is free.

## The measurement

A level is a confirmed swing extreme on the coarse timeframe. Its **refinement**
is the most extreme price on the fine timeframe inside the coarse bar that formed
it - which is a genuine sharpening and uses only bars at or before formation.

A **retest** is a later approach within `TOLERANCE` volatility units. It
**rejects** when price then moves `REJECT_BY` units away from the level without
first travelling `BREAK_BY` units through it. Both legs are required: counting an
approach as a rejection because price merely left is how a rejection rate reaches
70% and then loses seven points to a look-ahead correction.

Everything is causal - the refinement is fixed at formation, the retest is scored
forward only - and the paired design means refined and coarse are scored on **the
same retests**, so a difference cannot come from one of them seeing more events.

    ./.secrets/lab.sh run research/harness/refining.py
"""

from __future__ import annotations

import math
import sys

import numpy as np

from research.harness import seqlab
from research.harness.convention import SECONDS
from research.harness.retracing import zigzag

#: Coarse timeframe, and the fine one it is refined on.
PAIRS = (("4h", "1h"), ("1h", "15m"))

#: Zigzag threshold for the coarse level, in that series' per-bar sigma.
THETA = 2.0

#: How close an approach has to be to count as a retest.
TOLERANCE = 0.5

#: How far price must travel away from the level for a rejection,
#: and how far through it for a break. Both in volatility units.
REJECT_BY = 2.0
BREAK_BY = 1.0

#: Bars after a retest in which the outcome must resolve. An unresolved retest
#: is dropped rather than counted either way - `research/exiting.md`'s clock
#: exits are what a horizon does to an outcome that had not happened yet.
HORIZON = 40

#: Fewest resolved retests before a cell is reported.
FEWEST = 30


def levels(prices: np.ndarray, times: np.ndarray, sigma: float) -> list[tuple[int, float]]:
    """Confirmed swing extremes on the coarse series, as (bar index, price)."""
    turns = zigzag(prices, THETA * sigma)
    return [(i, float(prices[i])) for i in turns]


def refine(
    level_time: float,
    coarse_seconds: float,
    fine_times: np.ndarray,
    fine_high: np.ndarray,
    fine_low: np.ndarray,
    upward: bool,
) -> float | None:
    """The extreme price on the fine series inside the coarse bar that formed it.

    Uses only the bar that formed the level, so nothing after formation enters -
    a refinement that looked forward would be a different and much better study
    of nothing.
    """
    lo = level_time
    hi = level_time + coarse_seconds
    inside = (fine_times >= lo) & (fine_times < hi)
    if not inside.any():
        return None
    return float(fine_high[inside].max() if upward else fine_low[inside].min())


def rejected(prices: np.ndarray, start: int, level: float, sigma: float) -> bool | None:
    """Did a retest at `start` reject the level, break it, or fail to resolve?

    `None` when neither threshold is reached inside `HORIZON`, which is dropped
    rather than counted - an unresolved retest is not a rejection and calling it
    one is the look-ahead that cost the original claim seven points.
    """
    reject_at = REJECT_BY * sigma
    break_at = BREAK_BY * sigma
    above = prices[start] >= level
    for j in range(start + 1, min(start + HORIZON + 1, len(prices))):
        gap = prices[j] - level
        if above:
            if gap >= reject_at:
                return True
            if gap <= -break_at:
                return False
        else:
            if gap <= -reject_at:
                return True
            if gap >= break_at:
                return False
    return None


def score(coarse: dict, fine: dict, interval_seconds: float) -> tuple[int, int, int]:
    """Retests, rejections at the coarse level, rejections at the refined one.

    **Paired**: both are scored on the same retests, so a difference cannot come
    from one seeing more events than the other.
    """
    closes = np.asarray(coarse["close"], dtype=float)
    times = np.asarray(coarse["time"], dtype=float)
    logs = np.log(np.maximum(closes, 1e-12))
    sigma = float(np.std(np.diff(logs), ddof=1))
    if sigma <= 0 or len(logs) < 500:
        return 0, 0, 0

    fine_times = np.asarray(fine["time"], dtype=float)
    fine_high = np.log(np.maximum(np.asarray(fine["high"], dtype=float), 1e-12))
    fine_low = np.log(np.maximum(np.asarray(fine["low"], dtype=float), 1e-12))

    found = levels(logs, times, sigma)
    tolerance = TOLERANCE * sigma
    tested = raw_ok = fine_ok = 0
    for at, price in found:
        upward = at > 0 and logs[at] >= logs[at - 1]
        sharper = refine(
            float(times[at]), interval_seconds, fine_times, fine_high, fine_low, upward
        )
        if sharper is None:
            continue
        # The first later approach only: a level retested five times in a row is
        # one event seen five ways, and counting them all weights whichever
        # levels happened to be revisited.
        for j in range(at + 2, len(logs)):
            if abs(logs[j] - price) <= tolerance:
                a = rejected(logs, j, price, sigma)
                b = rejected(logs, j, sharper, sigma)
                if a is not None and b is not None:
                    tested += 1
                    raw_ok += int(a)
                    fine_ok += int(b)
                break
    return tested, raw_ok, fine_ok


def run(symbols: list[str], coarse_tf: str, fine_tf: str, share: float, era: str) -> dict:
    """One cut: a share of each series, taken from one end or the other."""
    # Bar length in seconds. `SECONDS` is `convention.py`'s table, which is
    # derived from `seqlab.PER_YEAR` - the constant itself lives in
    # `projection.py`, not in `seqlab`.
    seconds = SECONDS[coarse_tf]
    tested = raw_ok = fine_ok = cells = 0
    for broker in symbols:
        try:
            coarse = seqlab.load(broker, coarse_tf)
            fine = seqlab.load(broker, fine_tf)
        except Exception:  # noqa: BLE001
            continue
        n = len(coarse["close"])
        take = int(n * share)
        if take < 400:
            continue
        cut = slice(0, take) if era == "early" else slice(n - take, n)
        sliced = {k: np.asarray(v)[cut] for k, v in coarse.items()}
        t, r, f = score(sliced, fine, seconds)
        if t >= FEWEST:
            cells += 1
            tested += t
            raw_ok += r
            fine_ok += f
    if not tested:
        return {}
    return {
        "cells": cells,
        "tested": tested,
        "coarse": raw_ok / tested,
        "refined": fine_ok / tested,
        "lift": (fine_ok - raw_ok) / tested,
        # Paired proportions: the standard error of a difference on the same
        # trials, which is smaller than two independent ones and is the right
        # one because the design is paired.
        "se": math.sqrt(max(raw_ok + fine_ok - 2 * min(raw_ok, fine_ok), 1)) / tested,
    }


#: Matched nulls per symbol when testing the excess lift. The scoring loop is
#: the expensive part, so this is smaller than the 200 `retracing.py` uses and
#: the standard error is reported rather than implied.
DRAWS = 40


def simulated_pair(
    coarse: dict, fine: dict, per_coarse: int, rng: np.random.Generator
) -> tuple[dict, dict]:
    """A matched Brownian pair: one path, seen at two resolutions.

    **The two series have to be the same path.** Simulating the coarse and fine
    series independently would give a null in which the fine series carries no
    information about the coarse one at all - so the refinement would be pointing
    at unrelated noise, the lift would collapse, and the test would "prove" the
    real lift significant by comparing it against a null that had been broken.

    So the fine series is generated and the coarse one is **aggregated from it**,
    exactly as a real feed's timeframes relate.
    """
    fine_close = np.asarray(fine["close"], dtype=float)
    logs = np.log(np.maximum(fine_close, 1e-12))
    sigma = float(np.std(np.diff(logs), ddof=1))
    n_fine = (len(logs) // per_coarse) * per_coarse
    if n_fine < per_coarse * 200 or sigma <= 0:
        return {}, {}

    sub = 8
    steps = rng.normal(0.0, sigma / math.sqrt(sub), (n_fine, sub))
    path = float(logs[0]) + np.cumsum(steps.reshape(-1))
    grid = path.reshape(n_fine, sub)
    opens = np.concatenate(([float(logs[0])], grid[:-1, -1]))
    f_close, f_high, f_low = grid[:, -1], grid.max(axis=1), grid.min(axis=1)
    f_high = np.maximum(f_high, opens)
    f_low = np.minimum(f_low, opens)
    f_time = np.asarray(fine["time"], dtype=float)[:n_fine]

    blocks = n_fine // per_coarse
    c_close = f_close.reshape(blocks, per_coarse)[:, -1]
    c_time = f_time.reshape(blocks, per_coarse)[:, 0]
    return (
        {"close": np.exp(c_close), "time": c_time},
        {
            "close": np.exp(f_close),
            "high": np.exp(f_high),
            "low": np.exp(f_low),
            "time": f_time,
        },
    )


def excess(symbols: list[str], coarse_tf: str, fine_tf: str, rng) -> dict:
    """Is a real feed's refinement lift above its own matched Brownian null?

    The headline lift is **not** the question - the generated family reproduces
    four fifths of it with no level in it to refine, so most of it is the
    procedure preferring an extreme. What is left is the part that could be a
    market fact, and this is the only test of it.

    Paired per symbol against its own null, so a difference cannot come from real
    and simulated being different instruments at different volatilities.
    """
    seconds = SECONDS[coarse_tf]
    per_coarse = max(1, int(round(SECONDS[coarse_tf] / SECONDS[fine_tf])))
    rows = []
    for broker in symbols:
        try:
            coarse = seqlab.load(broker, coarse_tf)
            fine = seqlab.load(broker, fine_tf)
        except Exception:  # noqa: BLE001
            continue
        t, r, f = score(coarse, fine, seconds)
        if t < FEWEST:
            continue
        here = (f - r) / t

        nulls = []
        for _ in range(DRAWS):
            c2, f2 = simulated_pair(coarse, fine, per_coarse, rng)
            if not c2:
                break
            t2, r2, f2ok = score(c2, f2, seconds)
            if t2 >= FEWEST:
                nulls.append((f2ok - r2) / t2)
        if len(nulls) < DRAWS // 2:
            continue
        null = np.asarray(nulls)
        rows.append(
            {
                "symbol": broker,
                "lift": here,
                "null": float(np.median(null)),
                "rank": float((null >= here).mean()),
                "excess": here - float(np.median(null)),
            }
        )
    if not rows:
        return {}
    above = sum(1 for r in rows if r["excess"] > 0)
    n = len(rows)
    sd = math.sqrt(n * 0.25)
    return {
        "cells": n,
        "above": above,
        "sign_z": (above - n / 2.0) / sd if sd else float("nan"),
        "median_lift": float(np.median([r["lift"] for r in rows])),
        "median_null": float(np.median([r["null"] for r in rows])),
        "median_excess": float(np.median([r["excess"] for r in rows])),
        "tail": sum(1 for r in rows if r["rank"] <= 0.05),
    }


def main() -> int:
    print("Does lower-timeframe refinement help, and if it stopped, was it the")
    print("sample or the era?\n")
    print("overfitting decays with sample size and has no date;")
    print("a regime change ignores sample size and has one.\n")

    groups = {
        "real": list(seqlab.REAL),
        "volatility": list(seqlab.VOLATILITY)[:10],
    }
    for name, symbols in groups.items():
        for coarse_tf, fine_tf in PAIRS:
            print("=" * 88)
            print(f"{name.upper()}  {coarse_tf} refined on {fine_tf}")
            print("=" * 88)
            print(
                f"{'cut':14} {'cells':>6} {'retests':>8} {'coarse':>8} "
                f"{'refined':>8} {'lift':>8} {'lift/se':>8}"
            )
            for label, share, era in (
                ("size 25%", 0.25, "late"),
                ("size 50%", 0.50, "late"),
                ("size 100%", 1.00, "late"),
                ("era early half", 0.50, "early"),
                ("era late half", 0.50, "late"),
            ):
                got = run(symbols, coarse_tf, fine_tf, share, era)
                if not got:
                    print(f"{label:14} {0:>6}  nothing reached {FEWEST} retests")
                    continue
                ratio = got["lift"] / got["se"] if got["se"] else float("nan")
                print(
                    f"{label:14} {got['cells']:>6} {got['tested']:>8,} "
                    f"{got['coarse']:>8.4f} {got['refined']:>8.4f} "
                    f"{got['lift']:>+8.4f} {ratio:>8.2f}"
                )
            print()

    # ----------------------------------------------- is the excess lift real?
    print("=" * 88)
    print("IS THE EXCESS LIFT - real minus its OWN matched null - ANYTHING?")
    print("=" * 88)
    print(f"{DRAWS} Brownian pairs per symbol, generated at the fine resolution and")
    print("aggregated to the coarse one, so the two timeframes are one path.\n")
    print(
        f"{'pair':16} {'cells':>6} {'above':>6} {'sign z':>8} {'lift':>9} "
        f"{'null lift':>10} {'excess':>9} {'p<=.05':>7}"
    )
    for coarse_tf, fine_tf in PAIRS:
        got = excess(list(seqlab.REAL), coarse_tf, fine_tf, np.random.default_rng(31))
        label = f"{coarse_tf}<-{fine_tf}"
        if not got:
            print(f"{label:16}  nothing scored")
            continue
        print(
            f"{label:16} {got['cells']:>6} {got['above']:>6} {got['sign_z']:>8.2f} "
            f"{got['median_lift']:>+9.4f} {got['median_null']:>+10.4f} "
            f"{got['median_excess']:>+9.4f} {got['tail']:>7}"
        )
    print()

    print("Reading it:")
    print("  * lift shrinking from 'size 100%' to 'size 25%' is overfitting.")
    print("  * lift present in one era half and absent in the other, at the same")
    print("    size, is a regime change and the boundary dates it.")
    print("  * any lift at all on the volatility family is the procedure, not the")
    print("    market - those feeds have no level to refine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
