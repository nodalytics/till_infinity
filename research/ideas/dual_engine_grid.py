"""The dual-engine rule as a parameter grid, over five instruments on one account.

`dual_engine_port.py` ran the rule as specified and found it fires **seven
times in 76-86 days** on its own two instruments. This is the grid search that
follows from that: twelve cells over tolerance, attention percentile and risk
per trade, on EURUSD, XAUUSD, GBPUSD, USDJPY and AUDUSD, reporting the Sharpe
ratio, compounded annual return and maximum drawdown each cell produces.

## The thing to settle before reading any cell

**The premise is that the rule over-filters, and that is true. What the port
already measured is that relaxing the filter removes the edge with it:**

| tolerance | EURUSD+GOLD | its own flip |
|---|---|---|
| 0.015 | n 7, +1.103 +/-0.749 | n 5, -0.025 |
| 0.05 | n 14, +0.301 +/-0.473 | n 8, -0.372 |
| 0.10 | n 22, +0.114 +/-0.346 | n 14, -0.079 |

Trade frequency comes almost entirely from the alignment tolerance, and the
expectancy falls toward the flip as the tolerance opens. So "more trades at the
same expectancy" is not a free parameter choice on this data - it is the thing
being tested. The grid is the right way to test it and this file does not
prejudge it; it is stated here so the result is read against the prediction
rather than after it.

## Why the grid carries its own null

**A best-of-twelve is not a measurement.** `smc_bos_c_catalogue.py` says it in
full: the best of six cells beats the best of three "by construction", because
the max of six draws sits about 1.5 standard errors above their median. Twelve
cells at 50 trades each, with a per-trade sd near 1.5R, gives a per-cell
standard error around 0.2R - so a best cell sitting 0.4R above the grid median
is what **noise** looks like here, before any edge is involved.

So every cell is run twice: once as the rule and once with every signal's
direction reversed, and the same filter - Sharpe > 0.5, max drawdown < 15%, at
least 50 trades - is applied to both grids. The question the output answers is
not "does a cell pass" but **"does a cell pass that the flip grid cannot
match"**. If the flip has passing cells too, the filter is selecting noise and
the surviving parameters are a description of this sample.

## What the three statistics are worth over 75 days

They are reported because they were asked for, and each is labelled rather than
left to look like what it is not.

* **Compounded annual return** annualises **72-86 days**. It multiplies the
  period return by about 4.5 and multiplies its error by the same, so a cell
  reading +40% CAR made about +7% over the window. The raw period return is
  printed beside it and is the honest number.
* **Sharpe** is computed on daily returns of the realised equity curve and
  annualised by `sqrt(252)`, over roughly **54 trading days**. The standard
  error of an annualised Sharpe on n days is about `sqrt(252/n)`, which here is
  about **2.2** - so a cell reading 1.0 and a cell reading 0.5 are not
  distinguishable, and the > 0.5 constraint is being applied to a quantity
  whose error bar is four times the threshold. This is printed with every row.
* **Max drawdown** is on the **realised** curve - it moves when a position
  closes, not while it is open - so it is a floor on the true drawdown and not
  an estimate of it. A rule holding to a 48-hour time stop can be well under
  water between two points on this curve.

## The account

One engine, five instruments, **one account** - which is what the original does
and what `dual_engine_port.py` did not: it ran an engine per instrument, so
`MAX_GROSS_LEVERAGE` only ever saw one instrument's own positions and the
portfolio cap never bound. Here it does, and concurrent positions compete for
the same buying power, which is the thing a portfolio Sharpe has to be computed
over.

## What it read, 2026-11-12

**No cell passes. 0 of 12 in the rule grid and 0 of 12 in the flip grid.** The
three constraints together are unsatisfiable on this data: every cell that
reaches 50 trades has a negative Sharpe and a drawdown of 12.5-21.6%, and every
cell with a good Sharpe has 11 to 15 trades.

**Frequency and expectancy are monotonically opposed, over the whole grid:**

| tolerance | trades | R/trade (rule) | R/trade (flip) |
|---|---|---|---|
| 0.015 | 11-15 | **+0.157 to +0.321** | +0.140 to +0.467 |
| 0.05 | 24-37 | **-0.116 to -0.122** | -0.149 to +0.005 |
| 0.10 | 44-65 | **-0.152 to -0.251** | +0.051 to +0.089 |

That is the premise answered directly. The cash drag is real and the rule does
over-filter, but the filter and the expectancy are the same object: every step
toward the 50-trade floor costs expectancy, and the floor is only reached where
the rule loses a fifth to a quarter of a unit of risk per trade.

**At the only tolerance that meets the trade count, the rule loses and its own
reverse wins** - on all four of those cells, 0.10 at both percentiles and both
risk fractions. No single gap clears its error bar (about 0.3R against an SE of
0.31 on the widest cell) but the sign is the same in four of four. And at the
tight tolerance the flip is **ahead** of the rule, +0.467 against +0.321 at the
85th percentile, so the headline cell is not separable from trading its own
signals backwards either.

### `risk_per_trade` is not a risk axis on this universe

The most useful thing in the run, and it would have been invisible without
checking the trade lists. Doubling the risk fraction leaves the **same fifteen
trades** with the **same R each**, and changes the P&L by **2.88x** rather than
2x. Position by position:

| instrument | 1% -> 2% size | scaled by |
|---|---|---|
| GOLD | 17.0 -> 33.8 oz | **1.99-2.05** |
| EUR/USD | 441,009 -> 452,011 | **1.02** |
| AUD/USD | 700,391 -> 716,389 | **1.02** |
| USD/JPY | 3,079 -> 3,093 | **1.01** |

**FX is already against `MAX_LEVERAGE` and `MAX_GROSS_LEVERAGE` at 1%**, so
raising the fraction doubles the metal and does not move the currencies. The 2%
cell is therefore not the 1% cell with more risk - it is a **silently
gold-weighted** version of it, and gold is the only instrument in the five with
winning trades. Sharpe goes +1.50 -> +2.22 on an identical trade list for that
reason alone. Any optimiser run over this axis will choose 2% whenever gold
happened to do well in the window, and will report it as "more risk pays".

This also re-states what `dual_engine_port.py` found on two instruments: the
rule's sizing wants six to seven times the account on an FX trade with a
16-pip stop, so the caps bind before the risk fraction does.

### What the statistics were worth

* **Sharpe** carries a standard error of **+/-2.0 to +/-2.8** here against a
  threshold of 0.5. The constraint is being applied to a quantity whose error
  bar is four to five times the thing it is testing, which is why every row
  prints it.
* **CAR** annualises 86 days. The best rule cell reads **+54.9% CAR** off a
  period return of **+10.9%** on eleven trades.
* **Max drawdown** is realised-only and so is a floor, not an estimate.

Run it as `uv run python research/ideas/dual_engine_grid.py`.
"""

from __future__ import annotations

import argparse
import itertools
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from dual_engine_port import EQUITY, LEVERAGE, DualEngine, DualEngineConfig, Trade

#: The grid the request names, in the order the axes were given.
TOLERANCES: tuple[float, ...] = (0.015, 0.05, 0.10)
PERCENTILES: tuple[float, ...] = (0.75, 0.85)
RISKS: tuple[float, ...] = (0.01, 0.02)

#: The constraints the request names. Applied identically to the rule grid and
#: to the flip grid, because a constraint only one of them can meet is a
#: finding and a constraint both can meet is a filter on noise.
MIN_SHARPE = 0.5
MAX_DRAWDOWN = 0.15
MIN_TRADES = 50

#: The probability the true Sharpe is above zero, required before a result is
#: treated as one.
#:
#: **This is the statistic that answers what has been wrong all along here.** A
#: Sharpe is a point estimate and says nothing about how much data stands
#: behind it; PSR (Bailey and Lopez de Prado) folds in the sample length, the
#: skew and the kurtosis and returns a probability. Every reversal in this
#: repository has been a short sample with a flattering point estimate -
#: +0.368R on 11 trades becoming -0.300R on 41 - and a rule that cleared 0.5
#: Sharpe on fifty observations would have had a PSR nowhere near this.
#:
#: It is strict about exactly the shape these strategies have: a trailing stop
#: with a partial cuts the right tail and keeps the left, which is negative
#: skew, and negative skew lowers PSR for the same Sharpe. That is correct and
#: is the point.
MIN_PSR = 0.85

#: Where `node/corpus.py` was asked to write the five-instrument catalogue.
#: Separate from the shared one so adding USDJPY and AUDUSD does not change
#: what every other script in `research/ideas/` reads.
GRID_CATALOGUE = Path.home() / "till-data" / "grid5"

#: Trading days in a year, for annualising a daily Sharpe.
TRADING_DAYS = 252.0

#: The execution bar this file's own grid reads. `dual_engine_timeframes.py`
#: overrides it per pair, because cost is set by the structure timeframe and
#: the execution one can be raised to buy sample without paying for it.
SPEC = "15-MINUTE-LAST-EXTERNAL"


@dataclass(frozen=True, slots=True)
class Cell:
    """One point of the grid, and the arm it was run as."""

    tolerance: float
    percentile: float
    risk: float
    flip: bool
    #: Execution bars per structure bar. Defaulted so the twelve-cell grid in
    #: this file is unchanged by `dual_engine_timeframes.py` adding the axis.
    bars_per_structure: int = 16
    #: Where the 50% partial is taken, in units of initial risk.
    tp_trigger_r: float = 2.0
    #: The bar spec to read and trade, or None for 15-minute.
    bar_spec: str | None = None

    @property
    def spec(self) -> str:
        return self.bar_spec or SPEC

    @property
    def name(self) -> str:
        return f"tol {self.tolerance:<5} pct {self.percentile:.2f} risk {self.risk:.2f}"


@dataclass(frozen=True, slots=True)
class Result:
    """What one cell produced, in the terms the request asked for."""

    cell: Cell
    trades: int
    reward: float
    reward_se: float
    period_return: float
    car: float
    sharpe: float
    sharpe_se: float
    drawdown: float
    days: float
    wins: int
    #: Probabilistic Sharpe Ratio: the probability the **true** Sharpe exceeds
    #: zero, given this many observations with this skew and this kurtosis.
    psr: float = float("nan")

    @property
    def passes(self) -> bool:
        return (
            self.trades >= MIN_TRADES
            and self.sharpe > MIN_SHARPE
            and self.drawdown < MAX_DRAWDOWN
            and (math.isnan(self.psr) or self.psr > MIN_PSR)
        )

    def __str__(self) -> str:
        flag = "PASS" if self.passes else "    "
        return (
            f"  {flag} {self.cell.name}  n {self.trades:>3}  "
            f"R/trade {self.reward:>+6.3f} +/-{self.reward_se:>5.3f}  "
            f"sharpe {self.sharpe:>+6.2f} +/-{self.sharpe_se:>4.2f}  "
            f"car {self.car:>+7.1%} (period {self.period_return:>+6.1%})  "
            f"maxdd {self.drawdown:>5.1%}  win {self.wins / self.trades:>4.0%}"
            if self.trades
            else f"  {flag} {self.cell.name}  no trades"
        )


def load_all(where: Path, spec: str = SPEC) -> tuple[list[Any], list[Any]]:
    """Every instrument in the catalogue, and one stream of all their data.

    One stream and one engine, because the account is shared: a rule that is
    already holding four positions must be refused the fifth by its own gross
    leverage cap, and an engine per instrument cannot refuse it.
    """
    book = ParquetDataCatalog(str(where))
    instruments = sorted(book.instruments(), key=lambda i: str(i.id))
    rows: list[Any] = []
    for instrument in instruments:
        iid = str(instrument.id)
        bars = book.bars(bar_types=[f"{iid}-{spec}"])
        quotes = book.quote_ticks(instrument_ids=[iid])
        if not bars:
            print(f"  {iid}: no {spec} bars - skipped")
            continue
        rows.extend(bars)
        rows.extend(quotes)
    rows.sort(key=lambda d: d.ts_init)
    return instruments, rows


def run_cell(instruments: list[Any], data: list[Any], cell: Cell) -> list[Trade]:
    """One grid cell: five strategies, one engine, one account."""
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="GRID-001",
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    venues = {instrument.id.venue for instrument in instruments}
    for venue in sorted(venues, key=str):
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USD,
            starting_balances=[Money(EQUITY, USD)],
            default_leverage=Decimal(str(LEVERAGE)),
        )
    strategies = []
    for n, instrument in enumerate(instruments):
        engine.add_instrument(instrument)
        strategy = DualEngine(
            DualEngineConfig(
                instrument_id=instrument.id,
                bar_type=BarType.from_str(f"{instrument.id}-{cell.spec}"),
                feed=str(instrument.id.symbol),
                tolerance_mult=cell.tolerance,
                z_pct=cell.percentile,
                risk_per_trade=cell.risk,
                bars_per_structure=cell.bars_per_structure,
                tp_trigger_r=cell.tp_trigger_r,
                flip=cell.flip,
                # **Distinct per strategy.** `order-ids-namespace-on-the-last-hyphen`
                # is a measured outage here: eighteen desks shared two id
                # namespaces and collided, and a duplicate denial is not a retry.
                order_id_tag=f"{n:04d}",
            )
        )
        engine.add_strategy(strategy)
        strategies.append(strategy)
    engine.add_data(data)
    engine.run()
    closed = [trade for strategy in strategies for trade in strategy.closed]
    engine.dispose()
    return closed


def curve(trades: list[Trade], start: float = EQUITY) -> list[tuple[int, float]]:
    """The realised equity curve, by the day each trade closed.

    Realised: it moves when a position closes and not while it is open, so the
    drawdown taken off it is a floor on the real one. Said here because a
    drawdown that looks mark-to-market and is not is exactly the shape of
    number this desk has been misled by before.
    """
    by_day: dict[int, float] = {}
    for trade in trades:
        day = int(trade.day + trade.seconds / 86_400.0)
        by_day[day] = by_day.get(day, 0.0) + trade.profit
    if not by_day:
        return []
    equity = start
    out = []
    for day in range(min(by_day), max(by_day) + 1):
        equity += by_day.get(day, 0.0)
        out.append((day, equity))
    return out


def drawdown_of(rows: list[tuple[int, float]], start: float = EQUITY) -> float:
    peak = start
    worst = 0.0
    for _, equity in rows:
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)
    return worst


def sharpe_of(rows: list[tuple[int, float]], start: float = EQUITY) -> tuple[float, float]:
    """Annualised Sharpe on daily realised returns, with its own standard error.

    The error is `sqrt(TRADING_DAYS / n)`, which over 54 days of data is about
    2.2 - four times the 0.5 threshold the request filters on. Returned rather
    than mentioned, so every row carries it.
    """
    if len(rows) < 3:
        return (0.0, float("nan"))
    previous = start
    daily = []
    for _, equity in rows:
        daily.append((equity - previous) / previous if previous > 0 else 0.0)
        previous = equity
    n = len(daily)
    mean = sum(daily) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in daily) / (n - 1))
    if sd <= 0:
        return (0.0, math.sqrt(TRADING_DAYS / n))
    return (mean / sd * math.sqrt(TRADING_DAYS), math.sqrt(TRADING_DAYS / n))


def _moments(returns: list[float]) -> tuple[float, float, float, float]:
    """Mean, standard deviation, skewness and **non-excess** kurtosis."""
    n = len(returns)
    mean = sum(returns) / n
    centred = [r - mean for r in returns]
    variance = sum(c * c for c in centred) / (n - 1)
    sd = math.sqrt(variance) if variance > 0 else 0.0
    if sd <= 0:
        return mean, 0.0, 0.0, 3.0
    skew = (sum(c**3 for c in centred) / n) / sd**3
    kurtosis = (sum(c**4 for c in centred) / n) / sd**4
    return mean, sd, skew, kurtosis


def probabilistic_sharpe(returns: list[float], benchmark: float = 0.0) -> float:
    """The probability that the true Sharpe exceeds `benchmark`.

    Bailey and Lopez de Prado's PSR:

        PSR = N[ (SR - SR*) * sqrt(n - 1) /
                 sqrt(1 - g3*SR + (g4 - 1)/4 * SR^2) ]

    with `SR` the observed Sharpe **per period** - not annualised, because the
    sample size and the Sharpe have to be in the same units - `g3` the skew and
    `g4` the non-excess kurtosis.

    Why it belongs on every row here: a Sharpe is a point estimate that says
    nothing about how much data stands behind it, and every reversal in this
    repository has been a flattering point estimate on a short sample. PSR
    makes the sample size part of the answer, and it is harsh on negative skew
    - which is precisely the shape a partial-plus-trailing-stop produces, since
    that cuts the right tail and keeps the left.

    Returns `nan` below four observations, where the third and fourth moments
    are not estimable and a number would be an invention.
    """
    if len(returns) < 4:
        return float("nan")
    mean, sd, skew, kurtosis = _moments(returns)
    if sd <= 0:
        return float("nan")
    sharpe = mean / sd
    lower = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if lower <= 0:
        return float("nan")
    z = (sharpe - benchmark) * math.sqrt(len(returns) - 1) / math.sqrt(lower)
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def measure(cell: Cell, trades: list[Trade], days: float) -> Result:
    if not trades:
        return Result(cell, 0, 0.0, 0.0, 0.0, 0.0, 0.0, float("nan"), 0.0, days, 0)
    rewards = [t.reward for t in trades]
    n = len(rewards)
    mean = sum(rewards) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rewards) / (n - 1)) if n > 1 else 0.0
    rows = curve(trades)
    final = rows[-1][1] if rows else EQUITY
    period = final / EQUITY - 1.0
    # Annualising 72-86 days. The multiplier is about 4.5 and it is applied to
    # the error as faithfully as to the return.
    car = (final / EQUITY) ** (365.0 / days) - 1.0 if final > 0 and days > 0 else -1.0
    sharpe, sharpe_se = sharpe_of(rows)
    previous = EQUITY
    daily = []
    for _, equity in rows:
        daily.append((equity - previous) / previous if previous > 0 else 0.0)
        previous = equity
    return Result(
        cell=cell,
        trades=n,
        reward=mean,
        reward_se=sd / math.sqrt(n) if n else 0.0,
        period_return=period,
        car=car,
        sharpe=sharpe,
        sharpe_se=sharpe_se,
        drawdown=drawdown_of(rows),
        days=days,
        wins=sum(1 for r in rewards if r > 0),
        psr=probabilistic_sharpe(daily),
    )


#: Rolling windows every backtest reports, in years, newest-anchored.
WINDOWS: tuple[int, ...] = (1, 2, 3)


def rolling(trades: list[Trade], days: float, windows: tuple[int, ...] = WINDOWS) -> list[Any]:
    """One `Result` per recent window, newest-anchored, plus the full span.

    **A single full-span number is not the result; the series is.** Measured on
    this desk: Carver's framework reads +0.14 Sharpe over eight years, -0.04
    over three, -0.11 over two and **-0.22 over one** - decaying monotonically
    into the present, with its own flip crossing over it in the final year. The
    full-span figure was not wrong, it was an average over a regime that ended,
    and only the series shows that.

    Every window is returned, never the best one. Choosing the window that pays
    is the selection this repository has refuted two dozen ideas for, and a
    rolling series is informative precisely because the whole of it is visible.

    A window shorter than the data is still a **small sample** - a rule firing
    weekly gives fifty trades a year - so each `Result` carries its own standard
    error and a positive one-year reading is a reason to keep measuring.
    """
    if not trades:
        return []
    newest = max(t.day + t.seconds / 86_400.0 for t in trades)
    out = [("all", measure(_ANY, trades, days))]
    for years in windows:
        span = 365.0 * years
        if days < span * 1.05:
            continue  # the data does not cover it; say nothing rather than a part-window
        cut = newest - span
        kept = [t for t in trades if t.day + t.seconds / 86_400.0 >= cut]
        out.append((f"{years}y", measure(_ANY, kept, span)))
    return out


#: A placeholder cell: `measure` only reads it back out onto the `Result`, and
#: a window is not a parameter choice.
_ANY = Cell(0.0, 0.0, 0.0, False)


def span_days(data: list[Any]) -> float:
    bars = [row for row in data if isinstance(row, Bar)]
    if len(bars) < 2:
        return 1.0
    return max(1.0, (bars[-1].ts_event - bars[0].ts_event) / 1e9 / 86_400.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(GRID_CATALOGUE))
    args = parser.parse_args()

    instruments, data = load_all(Path(args.catalogue))
    if not instruments:
        raise SystemExit(
            f"no instruments in {args.catalogue} - build it with\n"
            f'  CORPUS_DIR={args.catalogue} CORPUS_FEEDS="eurusd gbpusd gold usdjpy audusd" '
            f"CORPUS_VENUE=DERIV uv run python -m till_infinity.node.corpus"
        )
    days = span_days(data)
    print(f"catalogue: {args.catalogue}")
    print(f"  {len(instruments)} instruments, {len(data)} rows, {days:.1f} days")
    print(f"  {', '.join(str(i.id) for i in instruments)}")
    print(
        f"\nconstraints: sharpe > {MIN_SHARPE}, maxdd < {MAX_DRAWDOWN:.0%}, "
        f"trades >= {MIN_TRADES}\n"
    )

    grids: dict[bool, list[Result]] = {False: [], True: []}
    for flip in (False, True):
        print(f"== {'flip (the null)' if flip else 'the rule'}")
        for tolerance, percentile, risk in itertools.product(TOLERANCES, PERCENTILES, RISKS):
            cell = Cell(tolerance, percentile, risk, flip)
            found = measure(cell, run_cell(instruments, data, cell), days)
            grids[flip].append(found)
            print(found)
        print()

    print("== the verdict")
    for flip in (False, True):
        passing = [r for r in grids[flip] if r.passes]
        label = "flip" if flip else "rule"
        best = max(grids[flip], key=lambda r: r.sharpe if r.trades else -99)
        print(f"  {label:<5} {len(passing)}/{len(grids[flip])} cells pass; best sharpe {best.sharpe:+.2f} at {best.cell.name} (n {best.trades})")
    rule_pass = [r for r in grids[False] if r.passes]
    flip_pass = [r for r in grids[True] if r.passes]
    if flip_pass:
        print(
            f"\n  **The flip grid has {len(flip_pass)} passing cell(s) too.** The constraint is\n"
            f"  not separating the rule from its own reverse, so a cell that passes is\n"
            f"  describing this sample rather than an edge."
        )
    elif rule_pass:
        print(
            f"\n  {len(rule_pass)} rule cell(s) pass and no flip cell does. That is the only\n"
            f"  shape in which these constraints mean anything - read it against the\n"
            f"  standard errors above before sizing anything on it."
        )
    else:
        print("\n  No cell in either grid clears all three constraints.")


if __name__ == "__main__":
    main()
