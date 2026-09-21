"""How long does a cross-venue deviation stay open? Quotes, not bars.

Run from the repository root:

    python research/harness/xvenue_halflife.py --from /path/to/xq.csv.gz

`constructing.md`'s addendum established that the cross-venue reversion signal **lives entirely
inside one 1-minute bar** - AUC 0.7610 at lag 1, 0.5151 at lag 2, 0.5001 by lag 10 - and that
1-minute closes cannot say whether that is sub-minute arbitrage or receive-clock sampling noise,
because both produce the same profile.

Quotes can say something bars cannot, and it is the question that decides whether any of this is
reachable: **how long is a deviation actually open?**

## The measurement

For each venue pair, the log spread of mids on a common time grid. If deviations decay
exponentially toward a slowly-moving level - which is what a z-score detector assumes - then

    ds = -(1/tau) s dt + noise

so regressing the change in the demeaned spread on its own level gives the decay rate, and

    half-life = tau * ln(2)

That is one number per pair, in seconds, and it is the whole answer. A half-life of two seconds
means nothing retail can act on it, whatever the AUC says. A half-life of a minute means the
deviation is at least theoretically reachable and the question moves on to execution.

Measured at several grid resolutions, because the estimate is biased downward when the grid is
coarser than the process - the classic discretisation bias in an Ornstein-Uhlenbeck fit - and
seeing it move with resolution is how that bias makes itself visible rather than being assumed
away.

## What this still cannot settle

`venue_ts` - the venue's own clock - is present on only about a fifth of these rows, so the
non-synchronous sampling question remains open. A deviation measured between two receive clocks
has a spurious component whose half-life is the clock jitter, and that is indistinguishable here
from a real deviation with the same lifetime.

So a **short** half-life is decisive: it rules the thing out whether it is noise or arbitrage,
because neither is reachable. A **long** half-life would not be decisive on its own, and would
need the venue clocks to interpret. The test is therefore worth running for its downside.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

#: Grid resolutions in seconds.
GRIDS = (1, 5, 15, 60)

#: Window for the slowly-moving level the deviation is measured against, in grid steps.
LEVEL_WINDOW = 120

#: Minimum aligned points to score a pair.
MIN_POINTS = 5_000


def load(path: Path) -> dict[str, list[tuple[int, float]]]:
    """`venue -> [(ms timestamp, mid)]`, sorted."""
    opener = gzip.open if str(path).endswith(".gz") else open
    out: dict[str, list[tuple[int, float]]] = defaultdict(list)
    with opener(path, "rt") as handle:
        for row in csv.DictReader(handle):
            try:
                mid = float(row["mid"])
                ts = int(row["ts"])
            except (KeyError, TypeError, ValueError):
                continue
            if mid > 0:
                out[row["venue"]].append((ts, mid))
    for points in out.values():
        points.sort()
    return out


def on_grid(points: list[tuple[int, float]], step_s: int) -> dict[int, float]:
    """Last observed mid in each grid bucket. Last, not mean - a mean invents a price."""
    out: dict[int, float] = {}
    step_ms = step_s * 1000
    for ts, mid in points:
        out[ts // step_ms] = mid
    return out


def half_life(spread: np.ndarray, step_s: int) -> tuple[float, float]:
    """Half-life in seconds of reversion toward a rolling level, and the fitted R^2.

    The level is a trailing mean rather than a constant because `constructing.md` established
    these spreads do not revert to zero - BTC Binance-against-Bitstamp sits at a median +10.8
    bps - so what decays is the deviation around a level that itself drifts.
    """
    n = len(spread)
    if n < LEVEL_WINDOW * 3:
        return float("nan"), float("nan")
    csum = np.cumsum(np.insert(spread, 0, 0.0))
    # csum has n+1 entries, so the trailing-mean slice needs both ends trimmed:
    # level[j-W] = (csum[j] - csum[j-W]) / W for j in [W, n).
    level = (csum[LEVEL_WINDOW:-1] - csum[: -LEVEL_WINDOW - 1]) / LEVEL_WINDOW
    dev = spread[LEVEL_WINDOW:] - level
    x = dev[:-1]
    y = np.diff(dev)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < MIN_POINTS or float(np.std(x)) == 0:
        return float("nan"), float("nan")
    slope, _intercept = np.polyfit(x, y, 1)
    if slope >= 0 or slope <= -1:
        return float("nan"), float("nan")
    fit = np.polyval([slope, _intercept], x)
    ss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum((y - fit) ** 2)) / ss if ss > 0 else float("nan")
    # s_{t+1} - s_t = slope * s_t  =>  decay factor per step is (1 + slope)
    per_step = -math.log(1.0 + slope)
    return (math.log(2.0) / per_step) * step_s, r2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="source", required=True)
    args = ap.parse_args()

    data = load(Path(args.source))
    venues = sorted(data)
    print(
        f"cross-venue deviation half-life, from quotes. venues: {', '.join(venues)}\n"
        f"counts: " + ", ".join(f"{v} {len(data[v]):,}" for v in venues)
    )
    print(f"\n  {'pair':<24}" + "".join(f"{f'{g}s grid':>12}" for g in GRIDS) + f"{'R2 @1s':>9}")

    per_grid: dict[int, list[float]] = defaultdict(list)
    for i, a in enumerate(venues):
        for b in venues[i + 1 :]:
            row = f"  {a + '-' + b:<24}"
            r2_first = float("nan")
            any_scored = False
            for g in GRIDS:
                ga, gb = on_grid(data[a], g), on_grid(data[b], g)
                common = sorted(set(ga) & set(gb))
                if len(common) < MIN_POINTS:
                    row += f"{'-':>12}"
                    continue
                spread = np.array([math.log(ga[k]) - math.log(gb[k]) for k in common])
                hl, r2 = half_life(spread, g)
                if g == GRIDS[0]:
                    r2_first = r2
                if np.isfinite(hl):
                    per_grid[g].append(hl)
                    row += f"{hl:>11.1f}s"
                    any_scored = True
                else:
                    row += f"{'-':>12}"
            if any_scored:
                print(row + (f"{r2_first:>9.4f}" if np.isfinite(r2_first) else f"{'-':>9}"))

    print(
        f"\n  {'MEDIAN':<24}"
        + "".join(
            f"{np.median(per_grid[g]):>11.1f}s" if per_grid.get(g) else f"{'-':>12}" for g in GRIDS
        )
    )
    print(
        "\n  **The half-life is the answer.** A deviation that decays in seconds is not\n"
        "  reachable by anything this desk can do, whether it is arbitrage or clock jitter -\n"
        "  and that verdict does not depend on resolving which, which is why this test was\n"
        "  worth running when the lag profile could not.\n"
        "\n  Watch the estimate across grids. Rising with coarser grids is the expected\n"
        "  discretisation bias of fitting a fast process on a slow clock; if the 60s figure is\n"
        "  far above the 1s figure, the 1s figure is the one to believe."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
