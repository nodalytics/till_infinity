"""Directional efficiency as a drift estimator - the one term the theory leaves standing.

Run from the repository root:  python research/harness/efficiency.py

`barrier-geometry-is-irrelevant.md` derived and verified that a barrier trade with market orders
on both sides earns

    E[P&L] = m = mu E[tau]

exactly - the drift over the holding period - with the barrier distances, the reward-to-risk
ratio, the jump structure and both overshoots cancelling out. Every study in this repository
that swept barrier geometry was varying a quantity that cannot pay, which is why they all landed
on the fair-odds line.

So there is exactly one thing left to look for, and it is `m`. This tests the best available
estimator of it.

## Directional efficiency, and why it is the right estimator

**Directional efficiency** is the ratio of net displacement to total path travelled over a
window:

    DE = |close_n - close_0| / sum_i |close_i - close_{i-1}|

bounded in `[0, 1]`, dimensionless, and invariant to any rescaling of price - it is the Kaufman
efficiency ratio, and in a physical reading it is useful work over total energy expended.

Its scaling is what makes it the right instrument here. For a random walk `DE ~ 1/sqrt(n)`; for a
perfectly directed walk `DE = 1` at every `n`. Expanding for small drift, net displacement is
about `mu n` and total path about `sigma n sqrt(2/pi)`, so

    DE ~ (mu / sigma) sqrt(pi / 2)

**DE is a normalised drift estimate** - drift per unit of volatility - which is precisely the
quantity `(6)` says is the only one that can pay. A source I was handed reports that DE
correlates with its own fill probability "despite not being an input to the probability formula",
and that is not a coincidence needing explanation: `(3)` makes the hit rate a function of `m`,
and DE estimates `m / sigma`. Both are reading drift.

## What is measured, and why there is no stop

Entry at the close in the direction of the window's net move, **market exit after a fixed number
of bars, and no stop at all.** That is deliberate: `(6)` holds exactly for market orders both
sides, so the realised mean return *is* `m` and nothing about barrier placement can contaminate
it. Adding a stop would reintroduce the overshoot term `(4)` and measure something else.

Returns are in true ranges at entry, so they are comparable across instruments, and the reading
is the mean by **decile of DE**. If DE carries drift, the top decile beats the bottom one and the
ladder is monotone. A flat ladder says the only remaining term is not forecastable this way.

## Costs, and the detection floor stated first

A market round trip pays the spread once - `spread_cost.py` measured 0.004 TR on the synthetics
and 0.020 on FX - plus carry over the holding period, at the rates in `costs.md`. No slippage
term, because there is no stop to slip.

Per `power-and-sizing.md` the floor is computed before the run rather than discovered after. This
is a **mean-return** test rather than a hit-rate test, so

    MDE = (z_alpha/2 + z_beta) * sigma / sqrt(n_effective)

and `n_effective` is not the row count: windows overlap heavily, so the standard error comes from
a **moving-block bootstrap** with blocks longer than the holding period. The naive standard error
would be far too small and would make a flat ladder look significant.

## The prediction, recorded before the run

Short horizons only, and small. `breakout-runs.md` measured the reversal hazard stepping from
0.243 to 0.362 after two bars and then going **flat**, so momentum persists for about two bars
and never exhausts. If that is the whole of the drift structure, then DE should show a positive
top decile at holds of one to three bars and nothing beyond, and the magnitude should be well
under the cost line.

**What would falsify the programme's pessimism**: a monotone DE ladder whose top decile clears
spread plus carry at some horizon. That is the only shape of result left, so it is worth one
clean, well-powered run.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Windows over which directional efficiency is computed, in bars.
WINDOWS = (10, 20, 50)

#: Holding periods, in bars. Market exit, no stop.
HOLDS = (1, 2, 3, 6, 12, 24)

#: Bootstrap draws and the block length as a multiple of the holding period.
DRAWS = 400
BLOCK = 4

#: Measured costs. Spread is paid once on a market round trip; carry per day from `costs.md`.
SPREAD = {"boom": 0.004, "crash": 0.004, "volatility": 0.004, "default": 0.020}
ANNUAL_SWAP = {"boom": 36.0, "crash": 18.0}


def spread_for(symbol: str) -> float:
    for key, value in SPREAD.items():
        if key in symbol:
            return value
    return SPREAD["default"]


def carry_for(symbol: str, tr_frac: float) -> float:
    """Carry in true ranges per day, or zero where the mode is not convertible."""
    for key, annual in ANNUAL_SWAP.items():
        if key in symbol and tr_frac > 0:
            return (annual / 365.0 / 100.0) / tr_frac
    return 0.0


def efficiency(close: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Directional efficiency and the sign of the net move, per bar.

    Vectorised with cumulative sums, because the naive loop over 65,000 bars and three
    windows is the difference between a minute and an hour.
    """
    n = len(close)
    steps = np.abs(np.diff(close, prepend=close[0]))
    path = np.cumsum(steps)
    de = np.full(n, np.nan)
    side = np.zeros(n)
    if n <= window:
        return de, side
    net = close[window:] - close[:-window]
    travelled = path[window:] - path[:-window]
    ok = travelled > 0
    idx = np.arange(window, n)
    de[idx[ok]] = np.abs(net[ok]) / travelled[ok]
    side[idx] = np.sign(net)
    return de, side


def block_error(values: np.ndarray, hold: int, seed: int = 0) -> float:
    """Bootstrap standard error of the mean, blocks longer than the holding period."""
    n = len(values)
    size = max(hold * BLOCK, 12)
    if n < size * 3:
        return float("nan")
    rng = np.random.default_rng(seed)
    count = int(np.ceil(n / size))
    means = np.empty(DRAWS)
    for d in range(DRAWS):
        picks = rng.integers(0, n - size, size=count)
        means[d] = np.concatenate([values[i : i + size] for i in picks])[:n].mean()
    return float(means.std())


def study(bars: np.ndarray, tally: dict, stride: int = 1) -> int:
    """`stride > 1` samples entries further apart.

    Set to `max(window, hold)` it makes the observations **non-overlapping**: neither the
    measurement window nor the holding period is shared between consecutive rows. The block
    bootstrap then has nothing to correct for, and the error bar is the plain one - which is
    the cheapest way to find out whether the overlapping ladder was real or an artefact of
    counting the same move many times.
    """
    tr = candles.true_range(bars)
    close = bars[:, 4]
    counted = 0
    for window in WINDOWS:
        de, side = efficiency(close, window)
        # Deciles over the instrument's own DE distribution at this window.
        finite = de[np.isfinite(de)]
        if len(finite) < 2000:
            continue
        edges = np.quantile(finite, np.linspace(0.0, 1.0, 11))
        for hold in HOLDS:
            step = max(window, hold) if stride > 1 else 1
            for at in range(window, len(bars) - hold, step):
                if not np.isfinite(de[at]) or side[at] == 0:
                    continue
                unit = tr[at] * max(close[at], 1e-12)
                if unit <= 0:
                    continue
                # Market exit after `hold` bars, no stop, so (6) applies exactly.
                got = side[at] * (close[at + hold] - close[at]) / unit
                decile = int(np.clip(np.searchsorted(edges, de[at], side="right") - 1, 0, 9))
                tally[(window, hold, decile)].append(got)
                tally[(window, hold, -1)].append(got)  # unconditional, for comparison
                counted += 1
    return counted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["xauusd", "eurusd", "boom_1000_index", "crash_1000_index"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    ap.add_argument(
        "--stride",
        type=int,
        default=int(os.environ.get("STRIDE", "1")),
        help="1 overlaps every bar; >1 makes observations non-overlapping",
    )
    args = ap.parse_args()

    tally: dict[tuple, list] = defaultdict(list)
    cost_of: dict[str, float] = {}
    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<26} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < 5000:
            continue
        tr = candles.true_range(bars)
        tr_frac = float(np.median(tr[np.isfinite(tr) & (tr > 0)]))
        cost_of[symbol] = spread_for(symbol) + carry_for(symbol, tr_frac) / 24.0
        n = study(bars, tally, stride=args.stride)
        print(f"  {symbol:<26}{n:>10,} observations")

    cost = float(np.mean(list(cost_of.values()))) if cost_of else 0.02
    print(
        f"\nmean return in true ranges, market exit, no stop - so (6) applies and this is m\n"
        f"sampling: {'non-overlapping' if args.stride > 1 else 'every bar (overlapping)'}\n"
        f"pooled cost: {cost:.4f} TR of spread plus one hour of carry; longer holds pay more\n"
        f"\n  {'win':>4}{'hold':>6}{'top decile':>12}{'bottom':>9}{'top-bottom':>12}"
        f"{'+/-':>8}{'uncond':>9}{'net top':>9}{'n':>10}"
    )
    for window in WINDOWS:
        for hold in HOLDS:
            top = np.array(tally.get((window, hold, 9), []))
            bottom = np.array(tally.get((window, hold, 0), []))
            uncond = np.array(tally.get((window, hold, -1), []))
            if len(top) < 1000 or len(bottom) < 1000:
                continue
            err = block_error(top, hold)
            spread_gap = float(top.mean()) - float(bottom.mean())
            net = float(top.mean()) - cost * (1.0 + hold / 24.0)
            mark = "  <-" if np.isfinite(err) and spread_gap > 2 * err else ""
            print(
                f"  {window:>4}{hold:>6}{top.mean():>+12.4f}{bottom.mean():>+9.4f}"
                f"{spread_gap:>+12.4f}{2 * err if np.isfinite(err) else math.nan:>8.4f}"
                f"{uncond.mean():>+9.4f}{net:>+9.4f}{len(top):>10,}{mark}"
            )

    print(
        "\n  The claim is a monotone ladder: high directional efficiency should predict more\n"
        "  drift than low. `top-bottom` against its bootstrap bar is the test, and `net top`\n"
        "  is the only column that is money - it charges the spread once and carry for the\n"
        "  holding period.\n"
        "\n  Predicted before the run: a small positive at one to three bars and nothing\n"
        "  beyond, well under the cost line, consistent with the flat reversal hazard after\n"
        "  two bars in breakout-runs.md. A monotone ladder clearing cost at any horizon is\n"
        "  the one result that would reopen this programme."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
