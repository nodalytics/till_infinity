"""Carver's framework on this desk's instruments, against its own flip.

`research/docs/dual-engine-confluence.md` measured that the dual-engine rule's
exit stack - break-even at 1R, a half off at 2R, an ATR trail, a 48-hour time
stop - costs about **0.2R a trade on a direction-free entry**, which is
twenty-five times what the spread costs. That is a finding about *management*,
not about one rule, and it raises an obvious question: is there a management
framework that does not do that?

Carver's is the obvious candidate, because it does not manage a trade at all.
There is no stop, no target, no partial and no time limit. There is a
**continuous position** whose size is a forecast divided by a volatility
estimate, re-sized as both move. A trade is never "exited"; the position
shrinks to zero and through it.

## What is implemented

Daily bars aggregated from the broker's own 5-minute series.

1. **Volatility**, exponentially weighted standard deviation of daily price
   changes, 36-day span, in price units. Carver's risk unit.
2. **Forecast: EWMAC**, his canonical rule - `(EWMA_fast - EWMA_slow) / vol` at
   six speeds, (2,8) through (64,256).
3. **Forecast scaling** to an average absolute value of 10, then **capped at
   +/-20**.
4. **Combination** across the six speeds, equally weighted, re-scaled and
   capped again.
5. **Position** = `capital * daily_vol_target * (forecast / 10) / vol_price`.
6. **Position inertia** - no trade while the held position is within 10% of
   the target, which is his cost-reduction rule.
7. **Costs** charged on every unit traded at the instrument's measured median
   spread.

## Two choices the framework leaves open, made here and stated

* **The forecast scalars are estimated, not quoted.** Carver publishes a fixed
  scalar per speed. Quoting numbers from memory into a backtest is how a
  result ends up resting on a misremembered constant, so these are estimated
  on an **expanding window** of the instrument's own history - causal, using
  only data before the bar being scaled. It costs a little accuracy early in
  the sample and removes a whole class of error.
* **No stop loss.** Carver does discuss volatility-based stops; the continuous
  core of the framework does not need one, and the entire point of running it
  here is to measure management *without* an exit stack. A stop would
  reintroduce the thing being tested.

## The nulls, and why the obvious one is worthless here

**The flip is not a null for this system, and that is worth stating because it
looks like one.** For a linear continuous rule, reversing the forecast negates
the position exactly, so `gross_flip = -gross_rule` by construction - measured
here as EURUSD +8,734 against -8,734, to the dollar. "Beats its own flip"
therefore means nothing more than "gross is positive". For the *discrete*
dual-engine rule the flip was informative, because a stop, a target and a time
limit break the symmetry; here nothing does. It is reported, and it is
decoration.

Two controls that are not decoration:

* **Buy and hold at the same volatility target.** A trend follower on a
  trending sample makes money for reasons that have nothing to do with the
  machinery around the forecast. Gold roughly tripled across this window. The
  question is not whether the system made money, it is whether it beat being
  long with the same risk appetite and none of the apparatus.
* **Block-shuffled returns.** The same daily moves in a scrambled order,
  rebuilt into a price series and run through the identical system. It keeps
  the distribution - the fat tails, the volatility clustering within a block -
  and destroys the trend. A system that scores the same here is scoring on its
  own machinery rather than on the market. Twenty draws, and the best of them
  is reported as well as the mean, because the best of twenty is what a
  selected result looks like.

## The second question, which is the one worth asking

Carver's **speed limit**: do not run a rule whose costs exceed about a third of
its expected gross profit. The dual-engine rule failed that in a way the per-trade
number hid - 0.008R a trade sounds free until it is multiplied by 713 trades a
year against no gross profit at all. This reports cost as a fraction of gross,
per instrument, so the same question gets a number rather than an impression.

Run it as `uv run python research/ideas/carver.py`.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: Where the pulled bars live. Gitignored - the broker's own candles stay out
#: of a public repository.
BARS = Path(".secrets/broker/mt5-deep")

#: Carver's canonical EWMAC speeds, fast and slow span in days.
SPEEDS: tuple[tuple[int, int], ...] = ((2, 8), (4, 16), (8, 32), (16, 64), (32, 128), (64, 256))

#: Span of the exponentially weighted volatility estimate, in days.
VOL_SPAN = 36

#: The scale every forecast is normalised to, and the cap applied after.
FORECAST_SCALE = 10.0
FORECAST_CAP = 20.0

#: Annualised volatility target, and the trading days it is spread over.
VOL_TARGET = 0.20
TRADING_DAYS = 256.0

#: No trade while the held position is within this fraction of the target.
INERTIA = 0.10

#: Account size per instrument, matching the other studies here.
CAPITAL = 100_000.0

#: The minimum history before a forecast is scaled or traded at all.
WARMUP = 300

#: Block length for the shuffled control, in days, and how many draws.
#: Blocks rather than single days because daily moves cluster, and an
#: i.i.d. shuffle would destroy that too and make the control easier than
#: the market it stands in for.
BLOCK = 20
DRAWS = 20

#: Median recorded spread in **points**, measured per feed in
#: `mt5_catalogue.py`, with the price increment needed to turn it into price.
SPREADS: dict[str, tuple[float, float]] = {
    "EURUSD": (2.0, 1e-05),
    "GBPUSD": (3.0, 1e-05),
    "XAUUSD": (15.0, 0.01),
    "USDJPY": (3.0, 0.001),
    "AUDUSD": (2.0, 1e-05),
}


def daily(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Daily closes from a 5-minute file, with their dates.

    The last 5-minute close of each UTC day. Not a session close - this store
    has no session boundaries recorded - so a day is a calendar day and a
    weekend is simply absent rather than filled.
    """
    closes: dict[dt.date, float] = {}
    with gzip.open(path, "rt") as handle:
        for row in csv.DictReader(handle):
            stamp = dt.datetime.fromisoformat(row["time"])
            closes[stamp.date()] = float(row["close"])
    days = sorted(closes)
    return np.array(days, dtype="datetime64[D]"), np.array([closes[d] for d in days])


def ewma(values: np.ndarray, span: int) -> np.ndarray:
    """Exponentially weighted mean, causal, seeded on the first value."""
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def ewm_vol(prices: np.ndarray, span: int = VOL_SPAN) -> np.ndarray:
    """Exponentially weighted standard deviation of daily price changes.

    In **price units**, which is what the position formula divides by. Shifted
    by one so the volatility used on a bar is estimated from changes strictly
    before it - an unshifted estimate uses the bar's own move to size the
    position taken on it, which is a lookahead worth about the move itself.
    """
    changes = np.diff(prices, prepend=prices[0])
    mean = ewma(changes, span)
    squared = ewma((changes - mean) ** 2, span)
    vol = np.sqrt(np.maximum(squared, 0.0))
    out = np.empty_like(vol)
    out[0] = np.nan
    out[1:] = vol[:-1]
    return out


def ewmac(prices: np.ndarray, vol: np.ndarray, fast: int, slow: int) -> np.ndarray:
    """One EWMAC forecast, volatility-normalised and lagged one day.

    Lagged because a crossover computed from today's close cannot be traded at
    today's close. Carver's own systems trade the next day; so does this.
    """
    raw = (ewma(prices, fast) - ewma(prices, slow)) / np.where(vol > 0, vol, np.nan)
    out = np.empty_like(raw)
    out[0] = np.nan
    out[1:] = raw[:-1]
    return out


def scaled(raw: np.ndarray, warmup: int = WARMUP) -> np.ndarray:
    """Scale a raw forecast to an average absolute value of `FORECAST_SCALE`.

    **Expanding window, strictly causal.** The scalar on bar `i` is estimated
    from bars before `i` only. A scalar fitted over the whole sample is a
    lookahead that flatters every forecast by exactly the amount the sample's
    own volatility differs from the live one.
    """
    out = np.full_like(raw, np.nan)
    absolute = np.abs(raw)
    total = 0.0
    count = 0
    for i in range(len(raw)):
        if count >= warmup and total > 0:
            out[i] = raw[i] * FORECAST_SCALE / (total / count)
        if np.isfinite(absolute[i]):
            total += absolute[i]
            count += 1
    return np.clip(out, -FORECAST_CAP, FORECAST_CAP)


@dataclass(frozen=True, slots=True)
class Run:
    name: str
    days: int
    gross: float
    costs: float
    net: float
    sharpe: float
    turnover: float
    drawdown: float

    @property
    def cost_share(self) -> float:
        """Costs against gross profit - Carver's speed limit is about a third."""
        return self.costs / self.gross if self.gross > 0 else float("inf")


def simulate(
    prices: np.ndarray,
    spread: float,
    *,
    flip: bool = False,
    hold: bool = False,
    capital: float = CAPITAL,
) -> Run | None:
    """One instrument through the framework. Returns None if it never warms.

    `hold` replaces the forecast with a constant `+FORECAST_SCALE`, which is
    buy-and-hold carrying the same volatility target and the same sizing - the
    control that asks whether the apparatus beat simply being long.
    """
    vol = ewm_vol(prices)
    if hold:
        combined = np.full(len(prices), FORECAST_SCALE)
        combined[:WARMUP] = np.nan
    else:
        forecasts = [scaled(ewmac(prices, vol, fast, slow)) for fast, slow in SPEEDS]
        stack = np.vstack(forecasts)
        combined = np.nanmean(stack, axis=0)
        combined = scaled(combined)
    # Re-scaling after combining (above) is Carver's diversification
    # multiplier: averaging correlated forecasts shrinks the average absolute
    # value and it has to be put back. Estimated the same causal way, not quoted.
    if flip:
        combined = -combined

    daily_target = capital * VOL_TARGET / math.sqrt(TRADING_DAYS)
    positions = np.zeros(len(prices))
    held = 0.0
    traded = np.zeros(len(prices))
    for i in range(len(prices)):
        if not np.isfinite(combined[i]) or not np.isfinite(vol[i]) or vol[i] <= 0:
            positions[i] = held
            continue
        target = daily_target * (combined[i] / FORECAST_SCALE) / vol[i]
        if abs(target - held) > INERTIA * max(abs(target), 1e-9):
            traded[i] = abs(target - held)
            held = target
        positions[i] = held

    changes = np.diff(prices, prepend=prices[0])
    # Yesterday's position earns today's move.
    carried = np.empty_like(positions)
    carried[0] = 0.0
    carried[1:] = positions[:-1]
    gross_daily = carried * changes
    cost_daily = traded * spread
    net_daily = gross_daily - cost_daily

    live = np.isfinite(net_daily) & (carried != 0)
    if live.sum() < 100:
        return None
    equity = capital + np.cumsum(np.nan_to_num(net_daily))
    peak = np.maximum.accumulate(equity)
    drawdown = float(np.max((peak - equity) / np.where(peak > 0, peak, 1.0)))
    returns = np.nan_to_num(net_daily) / capital
    sd = float(np.std(returns[WARMUP:], ddof=1))
    sharpe = (
        float(np.mean(returns[WARMUP:]) / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan")
    )
    return Run(
        name="",
        days=int(live.sum()),
        gross=float(np.nansum(gross_daily)),
        costs=float(np.nansum(cost_daily)),
        net=float(np.nansum(net_daily)),
        sharpe=sharpe,
        turnover=float(np.nansum(traded) / max(len(prices) / TRADING_DAYS, 1e-9)),
        drawdown=drawdown,
    )


def shuffled(prices: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """The same daily moves in a scrambled block order, rebuilt into prices.

    Blocks keep the clustering of daily moves and destroy the trend between
    them, which is the property a trend follower is supposed to be reading. An
    i.i.d. shuffle would destroy the clustering too and make the control easier
    than the market it stands in for - `clocks-must-pass-an-iid-control`
    records a measure that invented clustering at 5.3x on a process specified
    to have none.
    """
    changes = np.diff(prices)
    blocks = [changes[i : i + BLOCK] for i in range(0, len(changes), BLOCK)]
    rng.shuffle(blocks)
    return np.concatenate([[prices[0]], prices[0] + np.cumsum(np.concatenate(blocks))])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", default=str(BARS))
    args = parser.parse_args()

    bars = Path(args.bars)
    print(f"from {bars}\n")
    header = (
        f"{'instrument':<10} {'arm':<5} {'days':>6} {'gross $':>11} {'costs $':>10} "
        f"{'net $':>11} {'sharpe':>7} {'maxdd':>7} {'cost/gross':>11}"
    )
    print(header)
    print("-" * len(header))
    rows: dict[bool, list[Run]] = {False: [], True: []}
    holds: list[Run] = []
    shuffles: list[float] = []
    for symbol, (points, increment) in SPREADS.items():
        path = bars / f"{symbol}_M5.csv.gz"
        if not path.exists():
            print(f"{symbol:<10} no file - skipped")
            continue
        _, prices = daily(path)
        spread = points * increment
        def show(label: str, found: Run | None) -> None:
            if found is None:
                print(f"{symbol:<10} {label:<5} never warmed")
                return
            share = f"{found.cost_share:.1%}" if found.gross > 0 else "n/a (gross<=0)"
            print(
                f"{symbol:<10} {label:<5} {found.days:>6} "
                f"{found.gross:>+11,.0f} {found.costs:>10,.0f} {found.net:>+11,.0f} "
                f"{found.sharpe:>+7.2f} {found.drawdown:>6.1%} {share:>11}"
            )

        for flip in (False, True):
            found = simulate(prices, spread, flip=flip)
            if found is not None:
                rows[flip].append(found)
            show("flip" if flip else "rule", found)
        held = simulate(prices, spread, hold=True)
        if held is not None:
            holds.append(held)
        show("hold", held)

        rng = np.random.default_rng(20261112)
        drawn = [simulate(shuffled(prices, rng), spread) for _ in range(DRAWS)]
        scores = [r.sharpe for r in drawn if r is not None and math.isfinite(r.sharpe)]
        if scores:
            shuffles.extend(scores)
            print(
                f"{symbol:<10} {'shuf':<5} {DRAWS:>6} draws: sharpe mean "
                f"{sum(scores) / len(scores):+.2f}, best {max(scores):+.2f}, "
                f"worst {min(scores):+.2f}"
            )

    print()
    for flip in (False, True):
        group = rows[flip]
        if not group:
            continue
        side = "flip" if flip else "rule"
        net = sum(r.net for r in group)
        gross = sum(r.gross for r in group)
        costs = sum(r.costs for r in group)
        sharpes = [r.sharpe for r in group if math.isfinite(r.sharpe)]
        mean = sum(sharpes) / len(sharpes) if sharpes else float("nan")
        share = f"{costs / gross:.1%}" if gross > 0 else "n/a"
        print(
            f"  {side:<5} across {len(group)} instruments: net ${net:+,.0f}, "
            f"gross ${gross:+,.0f}, costs ${costs:,.0f} ({share} of gross), "
            f"mean sharpe {mean:+.2f}"
        )
    if holds:
        scores = [r.sharpe for r in holds if math.isfinite(r.sharpe)]
        if scores:
            print(
                f"  {'hold':<5} across {len(holds)} instruments: net "
                f"${sum(r.net for r in holds):+,.0f}, mean sharpe "
                f"{sum(scores) / len(scores):+.2f}"
            )
    if shuffles:
        print(
            f"  {'shuf':<5} {len(shuffles)} draws: mean sharpe "
            f"{sum(shuffles) / len(shuffles):+.2f}, best {max(shuffles):+.2f}"
        )
    if rows[False] and rows[True]:
        a = [r.sharpe for r in rows[False] if math.isfinite(r.sharpe)]
        b = [r.sharpe for r in rows[True] if math.isfinite(r.sharpe)]
        if a and b:
            print(f"\n  rule - flip, mean sharpe: {sum(a) / len(a) - sum(b) / len(b):+.2f}")
    print(
        "\n  Carver's speed limit is costs at or under about a third of gross profit.\n"
        "  A negative gross makes the ratio meaningless rather than good."
    )


if __name__ == "__main__":
    main()
