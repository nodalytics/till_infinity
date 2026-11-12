"""The dual-engine rule across timeframe pairs and reward targets.

Two axes, both asked for: the **(execution, structure) timeframe pair** and the
**reward-to-risk** the 50% partial is taken at, from 1.5 upward. Tolerance and
attention percentile are held at the specified 0.015 and 0.85 throughout, so
this measures the two new axes rather than reopening the four from
`dual_engine_grid.py` at once - twenty-four cells and a best-of-24 is already a
selection problem, and 144 would be a worse one.

`risk_per_trade` is not on the grid, and that is a result rather than a
shortcut: `dual_engine_grid.py` measured it leaving the **same trades with the
same R each** and changing the P&L by 2.88x, because FX is already against
`MAX_LEVERAGE` at 1% and only gold has room to scale. It is an axis that
reweights the book toward one instrument while looking like a risk setting.

## Two things the data settled before the grid was built

**Execution below 15m is not testable here, and that is an absence rather than
a judgement.** The store holds 1m and 5m for **three of the five feeds** and
only 5.6 to 6.5 days of either. The rule needs 164 structure bars before its
first possible signal - 100 to warm the structure attention z-score and 64 to
fill the pivot window - so every pair below a 15m structure never finishes
warming up:

| execution | span | feeds | struct 1H | struct 4H |
|---|---|---|---|---|
| 1m | 5.6 days | 3/5 | never warms | never warms |
| 5m | 6.5 days | 3/5 | never warms | never warms |
| 15m | 72-86 days | 5/5 | 1,569 bars | 269 bars |
| 1h | 294-321 days | 5/5 | 6,899 bars | **1,602 bars** |

> ## Retracted 2026-11-12, both of the above
>
> **The data table is out of date and the cost table below is the wrong
> venue's.** `research/ideas/mt5_catalogue.py` pulls the terminal's own bars:
> 90,000 M5 bars a symbol is **441-464 days on all five feeds**, against the
> 6.5 days on three that this file calls untestable. Execution below 15m is
> testable; it was the *store* that could not reach it, not the market.
>
> The cost table below is measured on **DERIV's** recorded spreads. The account
> this desk trades is 4-6x tighter, so the same arithmetic gives EURUSD **1.2%**
> at a 4H structure, **2.1%** at 1H and **4.8%** at 15m, and USDJPY **6.5%** at
> 15m. **"A 15m structure is priced out in advance" does not hold for this
> broker** - the conclusion was right about the arithmetic and wrong about
> whose spread to put in it.
>
> What survives unchanged is the *ordering* - cost still rises as the structure
> timeframe falls, by the same ratios - and every result below it, because
> those were measured on the store's bars at the store's costs and are what
> they are. The fine-structure arms were refused on a cost that does not apply
> here, and `mt5_catalogue.py` is the run they were refused.

**Cost is set by the structure timeframe, not the execution one**, because the
stop is drawn off the structure candle's own geometry. Measured on this store,
one round trip against a one-structure-bar stop:

| structure | EURUSD | GBPUSD | USDJPY | AUDUSD | GOLD |
|---|---|---|---|---|---|
| 1D | 1.8% | 1.4% | 1.4% | 2.0% | 0.3% |
| 4H | 7.0% | 5.1% | - | - | 0.5% |
| 1H | 12.5% | 9.0% | 11.4% | 13.1% | 1.0% |
| 15m | 29.1% | 21.7% | **37.3%** | 31.9% | 2.3% |

EURUSD runs 1.8% at 1d to 29.1% at 15m - **16x dearer**, which reproduces the
19x this desk has already measured from a different direction. The rule's best
cell anywhere so far was +0.321R with a standard error of 0.567. **A 15m
structure would charge most of that in costs before the first trade is judged**,
so a 15m structure is priced out in advance and is on the grid only as the
control that shows it.

The useful consequence of the same fact: **1h execution with a 4H structure
costs exactly what 15m execution with a 4H structure costs**, and buys 1,602
signal bars over 294 days against 269 over 76. That is six times the sample for
the same price per trade, and it is the single largest gain available in this
store.

## The prediction, written before the run

Lowering the structure timeframe raises the signal count by the ratio of the
timeframes and raises the cost in R by roughly the same ratio's square root.
`dual_engine_grid.py` already measured expectancy falling toward the flip as
frequency rose through the tolerance axis. If frequency is the thing that costs
expectancy rather than the tolerance specifically, the timeframe axis should
show the same shape - more trades, worse R - and the 1h/4H arm, which raises
the *sample* without lowering the structure, should show neither.

That is the separation this file exists to make: **more data is not the same
lever as more trades**, and only one of the two is free.

## What it read, 2026-11-12

**0 of 35 rule cells clear the three constraints. 1 of 35 flip cells does.**

### The prediction above was wrong, and its failure is the result

It said the 1h/4H arm - more sample, same structure, same cost - "should show
neither" more trades nor worse R. It showed **much** worse R, and that is the
finding rather than a miss. Set the two 4H arms side by side: same structure
timeframe, same geometry, **same measured 7.0% cost per round trip**, differing
only in how long they ran.

| arm | span | n/cell | rule R |
|---|---|---|---|
| 15m/4H | 86 days | 11 | **+0.368** |
| 1h/4H | 321 days | 41 | **-0.300** |

Cost is held constant by construction, so the sign change cannot be cost and
cannot be the timeframe. **It is the sample.** The +0.368 was eleven trades.
More data did not leave the expectancy where it was; it revealed that the
expectancy was never there.

### Every cell with a real sample is negative

Ordered by trades per cell, not by timeframe:

| pair | cost/trip | n/cell | rule R | flip R | rule-flip |
|---|---|---|---|---|---|
| 1h/1D | 2.0% | **6** | +0.700 | -0.640 | +1.340 |
| 15m/4H | 7.0% | **11** | +0.368 | +0.407 | -0.038 |
| 1h/8H | ~3% | **13** | +0.279 | -0.309 | +0.588 |
| 15m/2H | ~9% | **14** | -0.292 | -0.365 | +0.073 |
| 15m/1H | 13.1% | **35** | -0.414 | -0.173 | -0.241 |
| 1h/4H | 7.0% | **41** | -0.300 | -0.530 | +0.230 |
| 15m/15m | 37.3% | **119** | -0.235 | **+0.232** | -0.467 |

Every positive cell has **n <= 13**. Every cell with **n >= 35** is negative.
The ordering is by sample size and it is monotone in the sign; it is not by
cost, and it is not by timeframe.

The best Sharpe anywhere in the grid is **+2.25**, at 15m/4H with a 4.0 reward
target, on **eleven trades** - and its own flip reads +0.479R on eight. That is
the artefact the null arm exists to catch, caught.

### At the two finest structures the rule is worse than random direction

Cost falls on both arms equally, so a gap between them is directional and
nothing else. At 15m/1H the rule reads -0.414 against its flip's -0.173, and at
15m/15m it reads **-0.235 against its flip's +0.232**. Trading the identical
signals backwards is better by 0.24R and 0.47R respectively, on the two largest
samples in the grid. The fine-structure arms are not merely paying a cost the
edge cannot cover - at those timeframes the direction itself is wrong.

The one reasonably-sampled cell where the rule beats its own reverse is 1h/4H,
by **+0.230R on n 41** - against a standard error on the difference of about
0.37, so **0.6 standard errors**, and both arms lose anyway. "Loses less than
its reverse" is the whole of it.

### The reward axis is inert

Across all seven pairs, moving the partial trigger from 1.5R to 4.0R moves the
trade count by **at most 5** and R by **at most 0.2**, and in the 1h/1D arm the
trades at 1.5 and 2.0 are identical. The rule's P&L is decided by the stop and
the 48-hour time stop; raising the target does not help because the trades do
not reach the old one. **There is no reward-to-risk setting that rescues this**,
which is the cleanest reading the axis can give.

### The frequency question, answered

15m/15m delivers **119 trades per cell**, comfortably past the 50-trade floor,
at **-0.235R each** with a 17-20% drawdown while its reverse makes +0.232R. The
cost screen said 37.3% of R per round trip at that structure before the run.
The floor is reachable; it is reachable only where the rule loses.

### A reporting defect fixed in this file

The pooled line summed trade counts across the reward axis, and the reward rows
re-exit the **same** signals - so it printed "n 587" for a pair that found 119
trades, five times over. It reports `n/cell` now. The weighted mean was never
affected; only the figure a reader would take for a sample size was.

Run it as `uv run python research/ideas/dual_engine_timeframes.py`, or
`--pair 1h/4H` for one timeframe pair.
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dual_engine_grid import (
    MAX_DRAWDOWN,
    MIN_SHARPE,
    MIN_TRADES,
    Result,
    load_all,
    measure,
    run_cell,
    span_days,
)
from dual_engine_port import PIVOT_TOLERANCE_ATR, STRONG_PERCENTILE


@dataclass(frozen=True, slots=True)
class Pair:
    """One (execution, structure) timeframe pair, and where its bars live."""

    execution: str
    structure: str
    #: Execution bars per structure bar.
    span: int
    catalogue: Path
    #: Measured round-trip cost against a one-structure-bar stop, worst feed.
    cost: str
    #: The execution bar spec the catalogue holds.
    spec: str

    @property
    def name(self) -> str:
        return f"{self.execution}/{self.structure}"


FIFTEEN = Path.home() / "till-data" / "grid5"
HOURLY = Path.home() / "till-data" / "grid5h"
MIN_SPEC = "15-MINUTE-LAST-EXTERNAL"
HOUR_SPEC = "1-HOUR-LAST-EXTERNAL"

#: Every pair this store can actually run, cheapest structure first. The 15m
#: structure is kept as the **cost control**: it is priced out in advance and
#: is here so the output shows that rather than asserting it.
PAIRS: tuple[Pair, ...] = (
    Pair("1h", "1D", 24, HOURLY, "2.0%", HOUR_SPEC),
    Pair("1h", "8H", 8, HOURLY, "~3%", HOUR_SPEC),
    Pair("15m", "4H", 16, FIFTEEN, "7.0%", MIN_SPEC),
    Pair("1h", "4H", 4, HOURLY, "7.0%", HOUR_SPEC),
    Pair("15m", "2H", 8, FIFTEEN, "~9%", MIN_SPEC),
    Pair("15m", "1H", 4, FIFTEEN, "13.1%", MIN_SPEC),
    Pair("15m", "15m", 1, FIFTEEN, "37.3%", MIN_SPEC),
)

#: The reward-to-risk axis: where the 50% partial is taken. The remainder
#: rides the ATR trail from there, as the rule specifies.
REWARDS: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0, 4.0)


@dataclass(frozen=True, slots=True)
class Row:
    pair: Pair
    reward: float
    rule: Result
    flip: Result

    @property
    def beats_its_null(self) -> float:
        return self.rule.reward - self.flip.reward


def banner(pair: Pair, days: float, instruments: int) -> str:
    return (
        f"== {pair.name:<9} structure {pair.span:>2} bars  "
        f"{days:>5.0f} days  {instruments} instruments  cost/trip {pair.cost}"
    )


def line(row: Row) -> str:
    rule, flip = row.rule, row.flip
    if not rule.trades and not flip.trades:
        return f"   rr {row.reward:<4} no trades in either arm"
    flag = "PASS" if rule.passes else "    "
    return (
        f"   {flag} rr {row.reward:<4} "
        f"rule n {rule.trades:>3} R {rule.reward:>+6.3f} +/-{rule.reward_se:>5.3f} "
        f"sharpe {rule.sharpe:>+6.2f} dd {rule.drawdown:>5.1%}  |  "
        f"flip n {flip.trades:>3} R {flip.reward:>+6.3f}  |  "
        f"rule-flip {row.beats_its_null:>+6.3f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", default="", help="run one pair by name, e.g. 1h/4H")
    args = parser.parse_args()

    print(
        f"constraints: sharpe > {MIN_SHARPE}, maxdd < {MAX_DRAWDOWN:.0%}, "
        f"trades >= {MIN_TRADES}; tolerance {PIVOT_TOLERANCE_ATR}, "
        f"percentile {STRONG_PERCENTILE / 100.0}\n"
    )
    loaded: dict[str, tuple[list[Any], list[Any], float]] = {}
    rows: list[Row] = []

    for pair in PAIRS:
        if args.pair and pair.name != args.pair:
            continue
        key = f"{pair.catalogue}:{pair.spec}"
        if key not in loaded:
            instruments, data = load_all(pair.catalogue, pair.spec)
            if not instruments:
                print(f"== {pair.name}: nothing in {pair.catalogue} - skipped\n")
                continue
            loaded[key] = (instruments, data, span_days(data))
        instruments, data, days = loaded[key]
        print(banner(pair, days, len(instruments)))
        for reward in REWARDS:
            found = {}
            for flip in (False, True):
                cell = _cell(pair, reward, flip)
                found[flip] = measure(cell, run_cell(instruments, data, cell), days)
            row = Row(pair, reward, found[False], found[True])
            rows.append(row)
            print(line(row))
        print()

    _verdict(rows)


def _cell(pair: Pair, reward: float, flip: bool) -> Any:
    """A `Cell` carrying the two new axes as well as the four old ones."""
    from dual_engine_grid import Cell

    return Cell(
        tolerance=PIVOT_TOLERANCE_ATR,
        percentile=STRONG_PERCENTILE / 100.0,
        risk=0.01,
        flip=flip,
        bars_per_structure=pair.span,
        tp_trigger_r=reward,
        bar_spec=pair.spec,
    )


def _verdict(rows: list[Row]) -> None:
    if not rows:
        return
    print("== the verdict")
    passing = [r for r in rows if r.rule.passes]
    flip_passing = [r for r in rows if r.flip.passes]
    print(f"  {len(passing)}/{len(rows)} rule cells clear all three constraints")
    print(f"  {len(flip_passing)}/{len(rows)} flip cells clear them too")

    # Frequency against expectancy, pooled over the reward axis, one line per
    # pair - the shape the prediction is about.
    print("\n  by structure timeframe, pooled over the reward axis:")
    seen: dict[str, list[Row]] = {}
    for row in rows:
        seen.setdefault(row.pair.name, []).append(row)
    for name, group in seen.items():
        trades = sum(r.rule.trades for r in group)
        if not trades:
            print(f"    {name:<9} no trades")
            continue
        weighted = sum(r.rule.reward * r.rule.trades for r in group) / trades
        flip_trades = sum(r.flip.trades for r in group)
        flip_weighted = (
            sum(r.flip.reward * r.flip.trades for r in group) / flip_trades
            if flip_trades
            else float("nan")
        )
        # **`n/cell`, not the sum.** The reward rows re-exit the *same* signals,
        # so adding their trade counts multiplies one sample by the length of
        # the reward axis - "n 587" for a pair that found 119 trades. The
        # weighted mean below is still a mean over the reward axis and is kept;
        # only the figure a reader would take for a sample size is corrected.
        per_cell = statistics.median(r.rule.trades for r in group)
        flip_per_cell = statistics.median(r.flip.trades for r in group)
        print(
            f"    {name:<9} cost/trip {group[0].pair.cost:<6} "
            f"rule n/cell {per_cell:>4.0f} R {weighted:>+6.3f}  |  "
            f"flip n/cell {flip_per_cell:>4.0f} R {flip_weighted:>+6.3f}  |  "
            f"rule-flip {weighted - flip_weighted:>+6.3f}"
        )

    best = max(rows, key=lambda r: r.rule.sharpe if r.rule.trades else -99)
    print(
        f"\n  best sharpe {best.rule.sharpe:+.2f} at {best.pair.name} rr {best.reward} "
        f"(n {best.rule.trades}); its own flip read {best.flip.reward:+.3f}R on "
        f"n {best.flip.trades}"
    )
    if flip_passing:
        print(
            "\n  **The flip clears the constraints somewhere too.** The filter is not\n"
            "  separating the rule from its own reverse."
        )


if __name__ == "__main__":
    main()
