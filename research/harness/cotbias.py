"""Does COT positioning work as a **trend** bias, and at what horizon?

    ./.secrets/lab.sh run research/harness/cotbias.py

A screen, not a registered study: it decides whether an intraday entry layer
is worth building at all. Any positive here needs its own pre-registration
before it becomes a rule.

## Why this is a different claim from the fade

`ideas/cot_fade_rule.json` fades the 4-week **change** beyond 1.5 sigma and
`cotfade.py` measured it: +0.243R gross, -0.126R of carry, interval straddling
zero. This asks the opposite question with a different statistic - does the
**level** of speculative positioning, or the direction of its drift, say which
way the market is going - and it is the bias a lower-timeframe entry would be
gated on.

## Why it is measured at a day before anything is measured at an hour

The bias is a weekly number. It cannot carry information specific to an hour
that a day does not also see, so the daily test strictly dominates on power.
And cost runs the other way: the same spread is about 19x dearer in R at 15m
than at 1d, so an hourly rule needs a far larger edge to survive. Measuring
the cheap, high-power version first is the only order that can save the work.

## What would make this worth the entry layer

A conditional mean that beats its own stale and shuffled arms at a horizon
short enough that carry is small - a few days at most. The arms matter more
than the headline: `origin-zones.md` put 3,697 intraday entry cells against
random-time and coin twins and none beat them, and `imported-ideas.md` failed
every SMC, level, pattern, reversion and sweep rule on this venue. The entry
side is closed ground. The bias is the only new thing, so the bias is what has
to carry the result.
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cotfade as cf  # noqa: E402

HORIZONS = [1, 2, 5, 10, 20]
TRAILING = 156
DRAWS = 400
SEED = 20261107


def bias_series(feed: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Each candidate bias, as (usable dates, side) with side in -1/0/+1.

    `level` is the crowding itself; `slope` follows the 4-week change, which
    is the fade's own statistic with the sign reversed - carried so the two
    claims are measured by one harness and cannot disagree by construction.
    """
    dates, share = cf.load_cot(feed)
    signed = share * cf.direction(cf.PAIRS[feed].lower())
    usable = dates + 8 * 86400.0

    level_z = np.full(len(signed), np.nan)
    for t in range(TRAILING, len(signed)):
        window = signed[t - TRAILING : t]
        sd = np.nanstd(window)
        if sd > 0.0:
            level_z[t] = (signed[t] - np.nanmean(window)) / sd

    change = np.full(len(signed), np.nan)
    change[4:] = signed[4:] - signed[:-4]

    out: dict[str, tuple[np.ndarray, np.ndarray]] = {
        "level-sign": (usable, np.sign(signed)),
        "level-z>1": (usable, np.where(np.abs(level_z) > 1.0, np.sign(level_z), 0.0)),
        "level-z-sign": (usable, np.sign(level_z)),
        "slope-follow": (usable, np.sign(change)),
    }
    return {k: (u, np.nan_to_num(s, nan=0.0)) for k, (u, s) in out.items()}


def forward(
    bars: dict[str, np.ndarray], risk: np.ndarray, usable: np.ndarray, side: np.ndarray, days: int
) -> list[tuple[float, float, float]]:
    """(entry ts, R, side) for every week the bias takes a side.

    The side rides along because rows are **skipped** - a horizon running off
    the end of the series, a bar with no ATR yet - so a caller that re-derived
    the sides from `side` would pair each outcome with the wrong one. That
    misalignment is silent and would corrupt the drift correction only.
    """
    time, close = bars["time"], bars["close"]
    out = []
    for t in range(len(side)):
        if side[t] == 0.0:
            continue
        i = int(np.searchsorted(time, usable[t], side="left"))
        j = i + days
        if j >= len(time) or not np.isfinite(risk[i]) or risk[i] <= 0.0:
            continue
        out.append(
            (float(time[i]), float(side[t] * (close[j] - close[i]) / risk[i]), float(side[t]))
        )
    return out


def drift_at(bars: dict[str, np.ndarray], risk: np.ndarray, days: int) -> float:
    """What a long earns over every entry at this horizon, in R."""
    close = bars["close"]
    got = [
        (close[i + days] - close[i]) / risk[i]
        for i in range(len(close) - days)
        if np.isfinite(risk[i]) and risk[i] > 0.0
    ]
    return float(np.mean(got)) if got else float("nan")


def interval(rows: list[tuple[float, float]], days: int, rng) -> tuple[float, float]:  # noqa: D401
    """Blocks the length of the forward window, so overlap is paid for."""
    if len(rows) < 8:
        return float("nan"), float("nan")
    width = max(days, 1) * 86400.0
    start = min(ts for ts, _ in rows)
    keyed: dict[int, list[float]] = defaultdict(list)
    for ts, r in rows:
        keyed[int((ts - start) // width)].append(r)
    blocks = list(keyed.values())
    means = []
    for _ in range(DRAWS):
        drawn = [blocks[k] for k in rng.integers(0, len(blocks), len(blocks))]
        flat = [v for b in drawn for v in b]
        if flat:
            means.append(float(np.mean(flat)))
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    rng = np.random.default_rng(SEED)
    bars = {f: cf.load_bars(s) for f, s in cf.PAIRS.items()}
    risk = {f: 2.0 * cf.atr(bars[f]) for f in cf.PAIRS}
    biases = {f: bias_series(f) for f in cf.PAIRS}
    names = list(next(iter(biases.values())).keys())

    print("COT as a trend bias: conditional mean forward R, de-drifted\n")
    head = f"{'bias':14s} {'h':>3s} {'n':>5s} {'meanR':>8s} {'lo':>8s} {'hi':>8s}  {'stale':>8s} {'shuffled':>9s}  {'pos/8':>5s}"
    print(head)
    print("-" * len(head))

    for name in names:
        for days in HORIZONS:
            pooled: list[tuple[float, float]] = []
            stale_all: list[float] = []
            shuf_all: list[float] = []
            per_feed_mean = []
            for feed in cf.PAIRS:
                usable, side = biases[feed][name]
                shift = drift_at(bars[feed], risk[feed], days)
                rows = [
                    (ts, r - taken * shift)
                    for ts, r, taken in forward(bars[feed], risk[feed], usable, side, days)
                ]
                pooled.extend(rows)
                per_feed_mean.append(np.mean([r for _, r in rows]) if rows else float("nan"))

                stale = np.concatenate((np.zeros(8), side[:-8]))
                stale_all.extend(
                    r - taken * shift
                    for _, r, taken in forward(bars[feed], risk[feed], usable, stale, days)
                )
                shuffled = side.copy()
                nonzero = shuffled != 0.0
                shuffled[nonzero] = rng.permutation(shuffled[nonzero])
                shuf_all.extend(
                    r - taken * shift
                    for _, r, taken in forward(bars[feed], risk[feed], usable, shuffled, days)
                )

            if not pooled:
                continue
            values = [r for _, r in pooled]
            mean = float(np.mean(values))
            lo, hi = interval(pooled, days, rng)
            stale_mean = float(np.mean(stale_all)) if stale_all else float("nan")
            shuf_mean = float(np.mean(shuf_all)) if shuf_all else float("nan")
            positive = sum(1 for m in per_feed_mean if np.isfinite(m) and m > 0)
            print(
                f"{name:14s} {days:3d} {len(values):5d} {mean:8.3f} {lo:8.3f} {hi:8.3f}  "
                f"{stale_mean:8.3f} {shuf_mean:9.3f}  {positive:d}/8"
            )

    print(
        "\nReference: the fade at its primary cell reads +0.243R de-drifted on a 4-week hold,\n"
        "and pays -0.126R of carry. A bias at 1-5 days pays almost none, so a smaller\n"
        "number here can still be worth more than the fade - if it beats its own arms."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
