"""The one configuration where the measured edge could survive: maker fills, no stop, no carry.

Run from the repository root:  python research/harness/maker_exits.py

`costs.md` showed the barrier programme cannot be collected: stop overshoot is 0.24 TR on
Boom and 0.29 TR on gold, against a largest-ever measured effect of 0.08 TR. `stopfree.py`
then showed that removing the stop does not rescue it, because **carry is linear in holding
time while any edge is at best proportional to its square root** - the cost catches up at
exactly the horizons a signal would need.

Three cost terms remain, and each has a structural escape that this research has never
tested. This harness tests them together, because individually none of them is large enough
to matter and together they are the whole cost.

## Escape one: a limit order cannot slip

A stop is a **market** order - it triggers on touch and fills wherever the book is, which on
a spike instrument is far away. A limit order fills **at its price or better, or not at
all**. So an exit at a limit target pays no slippage, by construction rather than by
assumption.

## Escape two: swap is charged at rollover, not by the hour

This is a correction to `net_edge.py`, which charged `carry * hours / 24` and was wrong in
both directions at once. Swap is a **discrete charge at a rollover instant**, so a 2.7-hour
trade pays either **nothing** or a **full day** - never a ninth of one. The expected value
happens to match, which is why the earlier figure looked right, but the distribution does
not, and the consequence was missed entirely:

**a trade that is flat at rollover pays exactly zero carry.** Mean holding time at a
reward-to-risk of one was 2.7 hours, so avoiding the rollover hour costs almost no
opportunity and saves 0.036 TR - about 44% of the gross edge, for nothing.

`ROLLOVER_HOUR` is the broker's charging instant and is **not known**; it is assumed to be
00:00 UTC here. The harness prints what share of trades that assumption excludes so the
sensitivity is visible, and confirming it needs the swap actually charged on live tickets.

## Escape three: a maker earns the spread instead of paying it

Every study here assumes crossing the spread. A resting limit is filled by someone else
crossing, so the maker buys at the bid rather than the ask.

**This is not free, and the harness is built to show the cost rather than hide it.** A
resting buy is filled only when price comes *down* to it, so a maker systematically enters
after a small adverse move and misses the bars that run away immediately - adverse
selection. That is a real cost in the return distribution, and it is why `limit` entries
here are filled only on bars that actually traded through the limit price, and the fill is
at the limit price rather than at the close.

To avoid overclaiming, a maker fill is charged **zero** spread rather than credited with a
rebate that may not exist on this account.

## What is being compared

Four corners, same signals, same bars, so the effect of each escape is separable:

| configuration | entry | exit | carry |
|---|---|---|---|
| `taker, carry` | market | market at `N` bars | charged |
| `taker, flat` | market | market at `N` bars | zero, rollover avoided |
| `maker, flat` | limit | market at `N` bars | zero, rollover avoided |
| `maker, limit exit` | limit | limit target, else market | zero, rollover avoided |

The last row is the configuration in which costs are as near zero as this venue allows, and
it is the only one left in which a 0.08 TR effect could be collected.

There is still no stop in any of them, so **`R` is undefined and no fair-odds line applies**.
Returns are in true ranges at entry, error bars come from a moving-block bootstrap with
blocks longer than the holding period, and every rule is scored against the unconditional
trade in the same direction, same horizon and **same configuration** - because Boom rose
64.9% over these bars and any long will otherwise look clever.

`p01` is printed and should be read first. Without a stop the left tail is unbounded, and a
rule with a good mean in front of a ruinous 1st percentile is selling insurance.
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
from net_edge import ANNUAL_SWAP, SPREAD_R  # noqa: E402
from stopfree import BLOCK, DRAWS, HORIZONS, TARGET, signals  # noqa: E402

#: Assumed rollover instant, hours UTC. **Not confirmed** - see the module docstring.
ROLLOVER_HOUR = 0

#: The four corners, as (entry, exit, avoid rollover).
CONFIGS = (
    ("taker, carry", "market", "time", False),
    ("taker, flat", "market", "time", True),
    ("maker, flat", "limit", "time", True),
    ("maker, limit exit", "limit", "target", True),
)


def spans_rollover(t_entry: float, t_exit: float) -> bool:
    """Does the holding period cross the charging instant?"""
    shift = ROLLOVER_HOUR * 3600
    return int((t_entry - shift) // 86400) != int((t_exit - shift) // 86400)


def trade(
    bars: np.ndarray,
    tr: np.ndarray,
    i: int,
    side: int,
    horizon: int,
    entry_style: str,
    exit_style: str,
    avoid: bool,
    spread: float,
    carry_day: float,
) -> tuple[float, bool] | None:
    """One trade's net return in true ranges, and whether it paid carry.

    Returns `None` when the trade does not happen at all - a limit that was never filled,
    or a holding period that crosses rollover while `avoid` is set. Those are exclusions,
    not zero-return trades, and counting them as zeros would flatter every configuration.
    """
    ts, high, low, close = bars[:, 0], bars[:, 2], bars[:, 3], bars[:, 4]
    n = len(bars)
    if i + horizon >= n:
        return None
    unit = tr[i] * max(close[i], 1e-12)
    if unit <= 0:
        return None

    # Entry. A market order fills at the close and pays the spread. A resting limit at the
    # same price fills only if the next bar trades through it, and pays nothing - but it
    # misses every bar that ran away, which is the cost being measured.
    entry = float(close[i])
    paid = spread
    start = i
    if entry_style == "limit":
        j = i + 1
        if j >= n:
            return None
        reached = low[j] <= entry if side > 0 else high[j] >= entry
        if not reached:
            return None
        paid = 0.0
        start = j

    stop_at = start + horizon
    if stop_at >= n:
        return None
    if avoid and spans_rollover(float(ts[start]), float(ts[stop_at])):
        return None

    # Exit.
    gross = None
    if exit_style == "target":
        target = entry + side * TARGET * unit
        for step in range(1, horizon + 1):
            k = start + step
            if k >= n:
                break
            hit = high[k] >= target if side > 0 else low[k] <= target
            if hit:
                gross = TARGET  # a limit fills at its price; nothing slips
                break
    if gross is None:
        gross = side * (float(close[stop_at]) - entry) / unit
        paid += spread  # the time exit is a market order

    charged = 0.0 if avoid else carry_day * horizon / 24.0
    return gross - paid - charged, not avoid


def block_error(values: np.ndarray, horizon: int) -> float:
    """Bootstrap standard error of the mean, blocks longer than the holding period."""
    n = len(values)
    size = max(horizon * BLOCK, 10)
    if n < size * 3:
        return float("nan")
    rng = np.random.default_rng(0)
    count = int(np.ceil(n / size))
    means = np.empty(DRAWS)
    for d in range(DRAWS):
        picks = rng.integers(0, n - size, size=count)
        means[d] = np.concatenate([values[p : p + size] for p in picks])[:n].mean()
    return float(means.std())


def score(bars, tr, where, side, horizon, config, spread, carry_day) -> np.ndarray:
    _name, entry_style, exit_style, avoid = config
    out = []
    for raw in where:
        got = trade(
            bars, tr, int(raw), side, horizon, entry_style, exit_style, avoid, spread, carry_day
        )
        if got is not None:
            out.append(got[0])
    return np.array(out, dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["boom_1000_index", "crash_1000_index"])
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--horizons", default="", help="comma list, else the shared default")
    args = ap.parse_args()

    horizons = (
        tuple(int(h) for h in args.horizons.split(",") if h.strip()) if args.horizons else HORIZONS
    )

    print(
        "net returns in true ranges at entry. No stop anywhere, so there is no R and no\n"
        f"fair-odds line. Rollover assumed at {ROLLOVER_HOUR:02d}:00 UTC and NOT confirmed.\n"
        "\n  `kept` is the share of candidate entries that actually traded - a limit that\n"
        "  never filled and a trade crossing rollover are exclusions, not zero returns.\n"
        "  `vs always` compares against holding the same direction in the same\n"
        "  configuration. `p01` first: an unstopped loss is unbounded.\n"
    )

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_1h_broker.csv.gz"))
        if not found:
            print(f"{symbol:<22} no file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < 5000:
            continue
        tr = candles.true_range(bars)
        rules = signals(bars, tr)
        spread = next((v for k, v in SPREAD_R.items() if k in symbol), SPREAD_R["default"])
        annual = ANNUAL_SWAP.get(symbol, 0.0)
        tr_frac = float(np.median(tr[np.isfinite(tr) & (tr > 0)]))
        carry_day = (annual / 365.0 / 100.0) / tr_frac if tr_frac > 0 else 0.0

        print(f"\n{symbol}   spread {spread:.3f} TR, carry {carry_day:.3f} TR/day when paid")
        for config in CONFIGS:
            name = config[0]
            print(f"\n  {name}")
            print(
                f"    {'rule':<18}{'bars':>5}{'n':>8}{'kept':>7}{'net':>8}"
                f"{'+/-':>7}{'p01':>8}{'vs always':>11}"
            )
            for horizon in horizons:
                base = {}
                for side in (1, -1):
                    got = score(
                        bars, tr, rules["always long"][0], side, horizon, config, spread, carry_day
                    )
                    base[side] = float(got.mean()) if len(got) else 0.0
                for rule, (where, side) in rules.items():
                    got = score(bars, tr, where, side, horizon, config, spread, carry_day)
                    if len(got) < 200:
                        continue
                    err = block_error(got, horizon)
                    mean = float(got.mean())
                    mark = "  <-" if np.isfinite(err) and mean > 2 * err else ""
                    print(
                        f"    {rule:<18}{horizon:>5}{len(got):>8,}"
                        f"{len(got) / max(len(where), 1):>7.0%}{mean:>+8.3f}"
                        f"{2 * err if np.isfinite(err) else float('nan'):>7.3f}"
                        f"{np.percentile(got, 1):>8.2f}{mean - base[side]:>+11.3f}{mark}"
                    )

    print(
        "\n  A marked row beats zero by two bootstrap standard errors, and still needs a\n"
        "  positive `vs always` or it is the instrument's drift rather than a signal.\n"
        "\n  If `maker, limit exit` is no better than `taker, carry`, then the costs were\n"
        "  never what stood in the way and the signals are simply absent - which is a more\n"
        "  useful conclusion than it sounds, because it closes the question."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
