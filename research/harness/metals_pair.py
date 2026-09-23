"""Do gold and silver gauge each other - and is the pair worth its two spreads?

Run from the repository root:  python research/harness/metals_pair.py

The operator's question, from a live chart: *silver and gold move together? use them to gauge
each other.* It turns out to be the open question in
[`cross-spreads.md`](../planned/cross-spreads.md) arriving from a different direction, which is
why it is worth a harness rather than an opinion.

## Why this pair is different from everything else measured here

`constructing.md` holds the only positive directional result in this repository - constructed
cross-venue spreads at AUC 0.70 against 0.50 outright - and `Spread.tradeable` is **false** for
every one of them, because holding a venue spread needs an account at each venue and this desk has
one broker. The addendum then showed the deviation has a **sub-second half-life**, so it is
unreachable regardless.

**XAUUSD against XAGUSD is not that.** Both are quoted by the same broker, so the pair is two
orders on one account - the `cross` kind, which `constructing.md` says is holdable and then says
in terms that *"whether it is worth its two spreads is not answered here"*. This answers it.

## Three questions, in increasing order of what they would be worth

**Do they move together?** Contemporaneous correlation of hourly log returns. Necessary for any
pair trade and on its own worth nothing - correlation is not an edge, it is a precondition.

**Does one lead the other?** Cross-correlation at lags either side of zero. A peak away from zero
would be a genuine second sensor: gold's move at `t` carrying information about silver at `t+1`
that silver's own history does not. **Tested against silver's own lagged return as a control**,
because two series that are both autocorrelated will show cross-lag correlation with no lead-lag
relationship at all - which is the trap this question walks straight into.

**Does the ratio revert, and does it pay?** The gold/silver ratio is the classic form. Measured as
the half-life of deviations around a slow level, then as a z-score trade charged with **both
legs' spreads** - 0.020 TR each from `spread_cost.py`, so 0.040 TR round trip, which is the number
that has killed everything else here.

## What would make it a result

`barrier-geometry-is-irrelevant.md` derived that expectancy is drift over the holding period and
nothing else, so this is scored as mean return over a fixed horizon with market exits, not as a
barrier trade. And the period split runs first - the method note from the efficiency candidate,
which measured +0.0861 early and -0.0308 late and was only caught because the split was eventually
run.

A half-life measured in **hours** would be the first reverting thing found here that a desk on a
bar clock could actually act on; the cross-venue deviations died at under a second.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Lags in bars for the lead-lag scan, either side of zero.
LAGS = (-6, -4, -3, -2, -1, 0, 1, 2, 3, 4, 6)

#: Trailing window for the ratio's slow level, in bars.
LEVEL = 120

#: Holding periods for the reversion trade, in bars.
HOLDS = (6, 12, 24, 48)

#: |z| beyond this is a deviation worth trading.
THRESHOLD = 2.0

#: Round-trip cost: both legs crossed, at the FX/metals figure from spread_cost.py.
LEG_SPREAD = 0.020
ROUND_TRIP = 2 * LEG_SPREAD


def aligned(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Closes of both series on the timestamps they share."""
    ta = {int(row[0]): float(row[4]) for row in a if row[4] > 0}
    tb = {int(row[0]): float(row[4]) for row in b if row[4] > 0}
    common = sorted(set(ta) & set(tb))
    return (
        np.array(common, dtype=float),
        np.array([ta[t] for t in common]),
        np.array([tb[t] for t in common]),
    )


def half_life(series: np.ndarray) -> float:
    """Half-life in bars of reversion toward a trailing level."""
    n = len(series)
    if n < LEVEL * 3:
        return float("nan")
    csum = np.cumsum(np.insert(series, 0, 0.0))
    level = (csum[LEVEL:-1] - csum[: -LEVEL - 1]) / LEVEL
    dev = series[LEVEL:] - level
    x, y = dev[:-1], np.diff(dev)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 500 or float(np.std(x)) == 0:
        return float("nan")
    slope, _ = np.polyfit(x, y, 1)
    if slope >= 0 or slope <= -1:
        return float("nan")
    return math.log(2.0) / -math.log(1.0 + slope)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default=os.environ.get("INTERVAL", "1h"))
    ap.add_argument("--a", default="xauusd")
    ap.add_argument("--b", default="xagusd")
    args = ap.parse_args()

    where = Path(args.where).expanduser()
    files = {}
    for name in (args.a, args.b):
        got = sorted(where.glob(f"{name}_{args.interval}_*.csv.gz"))
        if not got:
            print(f"no {args.interval} file for {name}")
            return 1
        files[name] = got[0]

    bars_a, _ = candles.read(files[args.a])
    bars_b, _ = candles.read(files[args.b])
    _ts, pa, pb = aligned(bars_a, bars_b)
    if len(pa) < 5000:
        print(f"only {len(pa)} shared bars")
        return 1

    ra = np.diff(np.log(pa))
    rb = np.diff(np.log(pb))
    print(
        f"{args.a.upper()} vs {args.b.upper()}, {args.interval} bars, "
        f"{len(pa):,} shared timestamps\n"
    )

    print(
        f"1. do they move together?   contemporaneous correlation: {np.corrcoef(ra, rb)[0, 1]:+.4f}"
    )
    print("   (a precondition for a pair trade, not an edge)\n")

    print("2. does one lead the other?")
    print(f"   {'lag':>5}{'corr(a_t, b_t+lag)':>22}{'partial, b_t-1 controlled':>28}")
    for lag in LAGS:
        if lag >= 0:
            x, y = ra[: len(ra) - lag], rb[lag:]
            own = rb[lag - 1 :][: len(x)] if lag >= 1 else None
        else:
            x, y = ra[-lag:], rb[: len(rb) + lag]
            own = None
        m = min(len(x), len(y))
        x, y = x[:m], y[:m]
        corr = float(np.corrcoef(x, y)[0, 1])
        # Control for the target's own lagged return: two autocorrelated series show
        # cross-lag correlation without any lead-lag relationship at all.
        partial = float("nan")
        if lag >= 1:
            prev = rb[lag - 1 : lag - 1 + m]
            if len(prev) == m and np.std(prev) > 0:
                design = np.column_stack([x, prev, np.ones(m)])
                beta, *_ = np.linalg.lstsq(design, y, rcond=None)
                resid_y = y - beta[1] * prev - beta[2]
                resid_x = x - np.polyval(np.polyfit(prev, x, 1), prev)
                if np.std(resid_x) > 0 and np.std(resid_y) > 0:
                    partial = float(np.corrcoef(resid_x, resid_y)[0, 1])
        star = "  <-" if lag != 0 and abs(corr) > 0.05 else ""
        print(
            f"   {lag:>5}{corr:>22.4f}"
            + (f"{partial:>28.4f}" if np.isfinite(partial) else f"{'-':>28}")
            + star
        )
    print("   a peak away from lag 0 that survives the control is a genuine lead\n")

    # 3. The ratio, which is the holdable form.
    ratio = np.log(pa) - np.log(pb)
    hl = half_life(ratio)
    print("3. does the ratio revert, and does it pay?")
    print(
        f"   log(gold/silver) half-life: "
        + (
            f"{hl:.1f} bars ({hl * (1 if args.interval == '1h' else 1):.1f}h)"
            if np.isfinite(hl)
            else "not reverting"
        )
    )

    csum = np.cumsum(np.insert(ratio, 0, 0.0))
    level = (csum[LEVEL:-1] - csum[: -LEVEL - 1]) / LEVEL
    dev = ratio[LEVEL:] - level
    roll_sd = np.array(
        [float(np.std(ratio[i - LEVEL : i])) for i in range(LEVEL, len(ratio))][: len(dev)]
    )
    z = np.where(roll_sd > 0, dev / np.maximum(roll_sd, 1e-12), np.nan)
    base = LEVEL
    mid = len(z) // 2

    print(
        f"\n   {'hold':>5}{'n':>8}{'m early':>10}{'m late':>9}{'mean':>9}"
        f"{'net of 2 legs':>15}{'+/-':>8}"
    )
    for hold in HOLDS:
        early, late = [], []
        for i in range(len(z) - hold):
            if not np.isfinite(z[i]) or abs(z[i]) < THRESHOLD:
                continue
            at = base + i
            # Fade the deviation: short the ratio when stretched up, long when stretched down.
            side = -1 if z[i] > 0 else 1
            got = side * (ratio[at + hold] - ratio[at]) / max(roll_sd[i], 1e-12)
            (early if i < mid else late).append(got)
        both = np.array(early + late)
        if len(both) < 200:
            continue
        err = 2.0 * float(both.std()) / math.sqrt(len(both))
        net = float(both.mean()) - ROUND_TRIP
        mark = "  <-" if net > err else ""
        print(
            f"   {hold:>5}{len(both):>8,}{np.mean(early) if early else float('nan'):>10.3f}"
            f"{np.mean(late) if late else float('nan'):>9.3f}{both.mean():>9.3f}"
            f"{net:>+15.3f}{err:>8.3f}{mark}"
        )

    print(
        "\n   returns are in units of the ratio's own rolling sigma, and both legs' spreads\n"
        f"   are charged at {ROUND_TRIP:.3f} of a true range - the cost that has ended every\n"
        "   other candidate here.\n"
        "\n   Read `m early` against `m late` before anything else. An effect in one half only\n"
        "   is decayed, which is what killed the directional-efficiency candidate."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
