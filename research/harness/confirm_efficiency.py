"""One pre-registered cell, held-out instruments. The confirmatory test.

Run from the repository root:  python research/harness/confirm_efficiency.py

`a-theory-from-ohlc.md` left one candidate: directional efficiency over 20 bars predicting
continuation, with top-minus-bottom decile returns of +0.0468, +0.0631 and +0.0961 at holds of
6, 12 and 24, net of measured costs. It cleared per-cell error bars and **failed Bonferroni
across the eighteen cells scored**, which by the standard `power.py` applies to everything else
here means it is not yet a result.

This is the run that decides it, and it is deliberately narrow.

## Pre-registration

Fixed before execution and not to be changed after seeing the output:

* **one cell.** Directional efficiency window **20 bars**, holding period **12 bars**. No other
  window, no other hold, no sweep. A single hypothesis, so no multiple-comparison correction
  applies and none will be invented afterwards.
* **held-out instruments.** The effect was found on fourteen instruments; this uses only the
  ones that were *never* in that search. They are listed in `SEARCHED` and excluded.
* **the statistic is the difference.** Top decile mean minus bottom decile mean, with the
  standard error of **that difference**, bootstrapped on both arms. The earlier run quoted the
  difference against the top decile's own error bar, which is the lenient choice and overstated
  significance.
* **non-overlapping observations.** Stride is `max(window, hold)`, so no two rows share a
  measurement window or a holding period.
* **market exit, no stop**, so the expectancy result `E = m` applies exactly and no barrier term
  can contaminate the reading.
* **costs charged** at the measured figures: spread from `spread_cost.py`, carry from
  `costs.md`, no slippage term because there is no stop to slip.

## What counts as confirmation, decided in advance

**Confirmed** if the difference exceeds two bootstrap standard errors *of the difference* and the
top decile's mean net of costs is positive.

**Not confirmed** otherwise - including if the direction is right but the bar is not cleared,
which is the most likely outcome given the earlier run failed correction.

**Refuted** if the difference is negative by more than two standard errors, which would say the
earlier ladder was an artefact of the instruments it was found on.

There is no fourth option and no partial credit. The point of writing this down is that the
result is whatever it is when the run finishes.

## Why this is worth one run

`(6)` says expectancy equals drift over the holding period and nothing else, so directional
efficiency is not one candidate among many - it is the best available estimator of the only term
that can pay. If it fails here, the conclusion in `a-theory-from-ohlc.md` stands as written: the
strategy space reachable from OHLC is close to empty and the binding constraint is data. If it
holds, there is one thing to build on, and it is a forecast with a horizon rather than a level or
a pattern.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
from efficiency import efficiency  # noqa: E402

#: The pre-registered cell. Not swept.
WINDOW = 20
HOLD = 12

#: Instruments the effect was found on. Excluded, so this is a genuine holdout.
SEARCHED = frozenset(
    {
        "boom_1000_index",
        "crash_1000_index",
        "volatility_75_index",
        "volatility_100_index",
        "btcusd",
        "usdcad",
        "usdchf",
        "eurjpy",
        "gbpjpy",
        "us_sp_500",
        "wall_street_30",
        "australia_200",
        "germany_40",
        "uk_brent_oil",
    }
)

#: Measured costs, as elsewhere.
SPREAD = {"boom": 0.004, "crash": 0.004, "volatility": 0.004, "default": 0.020}
ANNUAL_SWAP = {"boom": 36.0, "crash": 18.0}

DRAWS = 2000
BLOCK = 4 * HOLD


def cost_for(symbol: str, tr_frac: float) -> float:
    spread = next((v for k, v in SPREAD.items() if k in symbol), SPREAD["default"])
    carry = 0.0
    for key, annual in ANNUAL_SWAP.items():
        if key in symbol and tr_frac > 0:
            carry = (annual / 365.0 / 100.0) / tr_frac
    return spread + carry * HOLD / 24.0


def difference_error(top: np.ndarray, bottom: np.ndarray, seed: int = 0) -> float:
    """Bootstrap standard error of `mean(top) - mean(bottom)`, blocks in both arms.

    Both arms resampled in the same draw, because the quantity of interest is the difference
    and its error is not the sum of the two single-arm errors unless they are independent -
    which, drawn from the same series, they are not.
    """
    rng = np.random.default_rng(seed)
    out = np.empty(DRAWS)
    for d in range(DRAWS):
        picks = []
        for arm in (top, bottom):
            if len(arm) < BLOCK * 3:
                return float("nan")
            count = int(np.ceil(len(arm) / BLOCK))
            starts = rng.integers(0, len(arm) - BLOCK, size=count)
            picks.append(np.concatenate([arm[i : i + BLOCK] for i in starts])[: len(arm)])
        out[d] = picks[0].mean() - picks[1].mean()
    return float(out.std())


def collect(where: Path, held: list[str], interval: str):
    """Top and bottom decile returns across the held-out instruments, plus mean cost."""
    top: list[float] = []
    bottom: list[float] = []
    costs: list[float] = []
    used = 0
    for symbol in held:
        found = sorted(where.glob(f"{symbol}_{interval}_*.csv.gz"))
        if not found:
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < 5000:
            continue
        tr = candles.true_range(bars)
        close = bars[:, 4]
        de, side = efficiency(close, WINDOW)
        finite = de[np.isfinite(de)]
        if len(finite) < 2000:
            continue
        lo_edge, hi_edge = np.quantile(finite, [0.1, 0.9])
        tr_frac = float(np.median(tr[np.isfinite(tr) & (tr > 0)]))
        costs.append(cost_for(symbol, tr_frac))
        step = max(WINDOW, HOLD)
        for at in range(WINDOW, len(bars) - HOLD, step):
            if not np.isfinite(de[at]) or side[at] == 0:
                continue
            unit = tr[at] * max(close[at], 1e-12)
            if unit <= 0:
                continue
            got = side[at] * (close[at + HOLD] - close[at]) / unit
            if de[at] >= hi_edge:
                top.append(got)
            elif de[at] <= lo_edge:
                bottom.append(got)
        used += 1
    return np.array(top), np.array(bottom), (float(np.mean(costs)) if costs else 0.02), used


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=[])
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    where = Path(args.where).expanduser()
    if args.symbols:
        names = args.symbols
    elif os.environ.get("SYMBOLS"):
        names = [s.strip() for s in os.environ["SYMBOLS"].split(",") if s.strip()]
    else:
        names = sorted(
            p.name.split(f"_{args.interval}_")[0] for p in where.glob(f"*_{args.interval}_*.csv.gz")
        )
    held = [n for n in names if n not in SEARCHED and "micro" not in n and ".conv" not in n]

    print(
        f"PRE-REGISTERED: directional efficiency window {WINDOW}, hold {HOLD}, one cell.\n"
        "Non-overlapping, market exit, no stop. Error bar on the DIFFERENCE.\n"
        f"\nheld out {len(held)} instruments, excluding the {len(SEARCHED)} the effect was "
        "found on:\n  " + ", ".join(held)
    )

    top_a, bottom_a, cost, used = collect(where, held, args.interval)

    if len(top_a) < 500 or len(bottom_a) < 500:
        print(f"\nnot enough held-out observations: top {len(top_a)}, bottom {len(bottom_a)}")
        return 1

    diff = float(top_a.mean() - bottom_a.mean())
    err = difference_error(top_a, bottom_a)
    net = float(top_a.mean()) - cost

    print(
        f"\n  {used} instruments used, top n = {len(top_a):,}, bottom n = {len(bottom_a):,}\n"
        f"\n  {'top decile mean':<28}{top_a.mean():>+10.4f}"
        f"\n  {'bottom decile mean':<28}{bottom_a.mean():>+10.4f}"
        f"\n  {'difference':<28}{diff:>+10.4f}"
        f"\n  {'2 x bootstrap SE (difference)':<28}{2 * err:>10.4f}"
        f"\n  {'cost charged':<28}{cost:>10.4f}"
        f"\n  {'top decile net of cost':<28}{net:>+10.4f}"
    )

    if not np.isfinite(err):
        verdict = "INDETERMINATE - not enough data for the bootstrap"
    elif diff < -2 * err:
        verdict = "REFUTED - the difference is negative beyond two standard errors"
    elif diff > 2 * err and net > 0:
        verdict = "CONFIRMED - difference clears two standard errors and net is positive"
    else:
        verdict = "NOT CONFIRMED - direction may be right but the bar is not cleared"
    print(f"\n  ==> {verdict}")
    print(
        "\n  One hypothesis, so no correction applies and none is being invented. The verdict\n"
        "  was defined before the run and is whatever it is."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
