"""`smc_bos_c_L50|M15|N20|time` through the Nautilus engine, on generated bars.

**Every number this prints is synthetic.** `node/backtest.catalogue()` points at
`~/till-data/catalog` and there is no such directory on this workstation, so
there are no stored bars to run the rule on and nothing here is a reading of
any market. What it measures is the port: how many swings the causal fold
confirms, how many breaks it classifies, how many of those reach the venue as
orders, and what the engine then does with them.

## The nulls, written before the run

Two feeds, and the prediction for each was fixed before either was generated.

* **A driftless walk.** Expected R per trade is **minus the cost**: entry at
  the ask and exit at the bid is one spread, against a stop of
  `max(ATR, 20 spreads)`, so the arithmetic says about -0.04 to -0.06R a trade
  and no exit rule can change it - `cost_px / risk` is set by the stop. A
  materially *positive* reading on this feed is a bug in the port, not an
  edge: a martingale cannot pay, and any positive expectancy on a walk has
  been a measurement error every time this desk has seen one.
* **A regime-switching drift.** The same generator with a drift that flips sign
  on a Poisson clock, which is the one process a trend-continuation rule should
  find. This is the power arm: a rule that reads nothing here is not a null
  result, it is a broken detector, and `show-power-before-reporting-a-null` is
  the standing instruction.

Costs: the spread, and nothing else. Commission and swap are not modelled -
every instrument is built with zero maker and taker fees so the fee model
charges nothing - and the feed has no session gap, so 1,440 one-minute bars and
24 hours of clock are the same thing here and are not on a real feed.

Run it as `uv run python research/ideas/smc_bos_c_port.py --months 3`.
"""

from __future__ import annotations

import argparse
import math
import os
import time
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Money, Price, Quantity

from till_infinity.strategies.config import Settings
from till_infinity.strategies.entries import EdgeEntryConfig
from till_infinity.strategies.leaves import leaf
from till_infinity.strategies.structure import StructureEdge

class Reversed(StructureEdge):
    """The same rule with the side of every break reversed - the coin twin.

    The geometry is identical: the same bars, the same swings, the same stop
    distance, the same clock, the same spread paid. Only the side changes, so
    anything this arm earns is **not** direction - and
    `let-the-shuffled-twin-name-the-mechanical-observables` is why it is here
    rather than a note saying it would be a good idea. On the trending feed the
    true arm should win and this one should lose; if both earn, what was
    measured is the geometry of a stop against a clock and not the trend.
    """

    def _payload(self, event, bar):
        found = super()._payload(event, bar)
        return found | {"direction": -int(found["direction"])}


SEC = 1_000_000_000
MINUTE = 60 * SEC
VENUE = Venue("SIM")
EQUITY = 100_000.0


@dataclass(frozen=True, slots=True)
class Market:
    """One synthetic instrument, at the scale and cost its name suggests.

    At gold's scale deliberately as well as at an FX major's:
    `a-synthetic-at-price-one-hides-scale-bugs` is on record here - relative
    standard deviation and a price offset coincide at 1.0 - and half of the
    rule's standing R is said to come from gold, so a port that is only
    exercised on a 1.1-handle pair is exercised on the easy half.
    """

    symbol: str
    price: float
    digits: int
    #: Per-minute relative standard deviation of the close.
    sd: float
    #: The quoted spread, in price units, held constant.
    spread: float
    size_precision: int
    min_qty: float


#: Three instruments at roughly the volatility and spread the real ones carry:
#: an M15 ATR near 10 pips on EURUSD and near $3 on gold, against 20 spreads of
#: 10 pips and $5 - so which of the two sets the stop is a live question on
#: this feed rather than settled by construction.
MARKETS: tuple[Market, ...] = (
    Market("EUR/USD", 1.1000, 5, 1.2e-4, 0.00005, 0, 1_000),
    Market("GBP/USD", 1.2700, 5, 1.3e-4, 0.00008, 0, 1_000),
    Market("XAU/USD", 2_000.0, 2, 2.5e-4, 0.25, 2, 1.0),
)

#: Two windows, named for the eras the rule's standing figures are quoted over.
#: **They are labels on generated data**: the dates set the timestamps and
#: nothing else, so "2023" here is not 2023.
ERAS: dict[str, str] = {"2023-24": "2023-01-02", "2025-26": "2025-07-01"}


def instrument(market: Market) -> CurrencyPair:
    """A Nautilus instrument whose quantity is in base units.

    Quantity in units and not in MT5 lots, because the engine computes the
    position's money from the instrument and `risk/sizing.lots` computes the
    budget from the spec - and those two have to be the same convention or the
    R this prints is wrong by the contract size. With the venue stating no tick
    value, `sizes.spec_of` derives it as `tick x multiplier`, which is one
    quote-currency tick per unit of quantity: the same arithmetic the engine's
    own P&L does.

    Zero fees, so the spread is the only cost and the cost in R is exactly the
    one the rule's own geometry implies.
    """
    base, _, quote = market.symbol.partition("/")
    return CurrencyPair(
        instrument_id=InstrumentId(Symbol(market.symbol), VENUE),
        raw_symbol=Symbol(market.symbol),
        base_currency=Currency.from_str(base),
        quote_currency=Currency.from_str(quote),
        price_precision=market.digits,
        size_precision=market.size_precision,
        price_increment=Price(10**-market.digits, market.digits),
        size_increment=Quantity(10**-market.size_precision, market.size_precision),
        lot_size=None,
        max_quantity=Quantity(1e7, market.size_precision),
        min_quantity=Quantity(market.min_qty, market.size_precision),
        max_price=None,
        min_price=None,
        max_notional=Money(50_000_000.0, USD),
        min_notional=Money(100.0, USD),
        margin_init=Decimal("0.03"),
        margin_maint=Decimal("0.03"),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
    )


def path(
    market: Market, minutes: int, seed: int, *, strength: float = 0.0, switch_days: float = 3.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One minute-by-minute OHLC path.

    Student-t innovations at five degrees of freedom, scaled to unit variance,
    because a Gaussian feed has none of the tails a stop distance is actually
    exposed to. `strength` is the drift as a multiple of the per-minute
    standard deviation, with its sign flipping on a Poisson clock of
    `switch_days` - zero is the walk.
    """
    rng = np.random.default_rng(seed)
    dof = 5
    z = rng.standard_t(dof, minutes) / math.sqrt(dof / (dof - 2))
    drift = np.zeros(minutes)
    if strength:
        flips = rng.random(minutes) < 1.0 / (switch_days * 1_440)
        sign = np.cumprod(np.where(flips, -1.0, 1.0))
        drift = sign * strength * market.sd
    close = market.price * np.exp(np.cumsum(drift + market.sd * z))
    opens = np.concatenate([[market.price], close[:-1]])
    # Wicks on both sides, so "a wick is not enough" is a rule the feed can
    # actually violate. Without them every break would be a close by
    # construction and step 3 would be untested.
    up = np.abs(rng.normal(0.0, market.sd * 0.6, minutes)) * close
    down = np.abs(rng.normal(0.0, market.sd * 0.6, minutes)) * close
    return (
        opens,
        np.maximum(opens, close) + up,
        np.minimum(opens, close) - down,
        close,
    )


def feed(market: Market, instr: CurrencyPair, minutes: int, start: str, seed: int, **kind: float):
    """The M1 bars and the quotes, interleaved in time.

    **The quote for a minute is stamped at its open and the bar at its close**,
    one nanosecond before the next minute. That ordering is step 5: the M15 bar
    closes, the strategy decides, and the first thing the venue then sees is
    the quote that opens the next minute - so a market order fills at that
    quote's ask on a buy and its bid on a sell, which is what the rule says and
    is a price that was not known when the decision was made.
    """
    opens, highs, lows, closes = path(market, minutes, seed, **kind)
    bar_type = BarType.from_str(f"{instr.id}-1-MINUTE-LAST-EXTERNAL")
    base = pd.Timestamp(start, tz="UTC").value
    digits = market.digits
    half = market.spread / 2.0
    # The venue checks a tick's size precision against the instrument's, so
    # these are built at the instrument's own and not at zero.
    size = Quantity(1_000_000, market.size_precision)
    volume = Quantity(1, market.size_precision)
    data: list[object] = []
    for i in range(minutes):
        ts = base + i * MINUTE
        mid = float(opens[i])
        data.append(
            QuoteTick(
                instrument_id=instr.id,
                bid_price=Price(mid - half, digits),
                ask_price=Price(mid + half, digits),
                bid_size=size,
                ask_size=size,
                ts_event=ts,
                ts_init=ts,
            )
        )
        data.append(
            Bar(
                bar_type=bar_type,
                open=Price(mid, digits),
                high=Price(float(highs[i]), digits),
                low=Price(float(lows[i]), digits),
                close=Price(float(closes[i]), digits),
                volume=volume,
                ts_event=ts + MINUTE - 1,
                ts_init=ts + MINUTE - 1,
            )
        )
    return data


def one(
    market: Market, era: str, minutes: int, seed: int, *, flip: bool = False, **kind: float
) -> dict[str, object]:
    """One cell: one market, one era, one process. Returns what it did."""
    instr = instrument(market)
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="BACKTEST-001",
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(EQUITY, USD)],
        # **Quotes alone decide a fill.** With bar execution on, the engine
        # would also match against the bar it has just processed - which is the
        # bar the signal was read from, at no spread at all. That is a fill the
        # desk could never get and the exact shape of generosity
        # `node/backtest.venue` refuses to tune for.
        bar_execution=False,
    )
    engine.add_instrument(instr)
    engine.add_data(feed(market, instr, minutes, ERAS[era], seed, **kind))
    built = Reversed if flip else leaf("smc-bos-causal", "edge")
    strategy = built(
        EdgeEntryConfig(
            instrument_id=instr.id,
            # The composite: M15 aggregated from the M1 bars inside the engine,
            # so the signal clock and the entry clock are the same data.
            bar_type=BarType.from_str(f"{instr.id}-15-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL"),
            order_id_tag=f"{abs(hash((market.symbol, era, seed))) % 10_000:04d}",
        )
    )
    engine.add_strategy(strategy)
    started = time.monotonic()
    engine.run()

    orders = engine.cache.orders(strategy_id=strategy.id)
    fills = [o for o in orders if o.filled_qty > 0]
    closed = list(strategy.closed)
    account = engine.portfolio.account(VENUE)
    balance = float(account.balance_total().as_double()) if account is not None else 0.0
    found = {
        "market": market.symbol,
        "era": era,
        "minutes": minutes,
        "seconds": round(time.monotonic() - started, 1),
        "structure": dict(strategy.structure),
        "gates": dict(sorted(strategy.passed_over.items())),
        "taken": strategy.taken,
        "refused": strategy.refused,
        "orders": len(orders),
        "fills": len(fills),
        "trades": len(closed),
        "stopped": sum(1 for t in closed if t.how == "stop"),
        "clocked": sum(1 for t in closed if t.how == "clock"),
        "r_total": sum(t.reward for t in closed),
        "r_mean": (sum(t.reward for t in closed) / len(closed)) if closed else 0.0,
        "r_sd": _sd([t.reward for t in closed]),
        "money": sum(t.money for t in closed),
        "balance": balance,
        "open_at_end": len(engine.cache.positions_open(strategy_id=strategy.id)),
        "r": [round(t.reward, 4) for t in closed],
        # The cost, as the only thing that sets it: one spread over the stop
        # distance. Reported rather than inferred from the mean, because at
        # this payoff's variance the mean cannot see a number this small.
        "cost_r": _median([t.spread_px / t.risk_px for t in closed if t.risk_px > 0.0]),
        "risk_px": _median([t.risk_px for t in closed]),
    }
    engine.dispose()
    return found


def _median(values: list[float]) -> float:
    """The median, or zero on nothing."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _sd(values: list[float]) -> float:
    """The sample standard deviation, or zero on fewer than two values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def tails(rewards: list[float]) -> str:
    """The shape of the payoff, which is what a stop against a clock makes.

    **Lead with the tail.** The mean of this distribution is the last thing it
    tells you: with no target, a win is whatever 1,440 minutes gave and a loss
    is one R, so the mean is a small number living inside a very wide one. The
    quantiles say what the rule actually produces.
    """
    if not rewards:
        return "no trades"
    ordered = sorted(rewards)
    wins = sum(1 for r in rewards if r > 0) / len(rewards)
    return (
        f"win {wins:.0%}  median {ordered[len(ordered) // 2]:+.2f}R  "
        f"P(>=1R) {sum(1 for r in rewards if r >= 1.0) / len(rewards):.0%}  "
        f"P(>=3R) {sum(1 for r in rewards if r >= 3.0) / len(rewards):.0%}  "
        f"worst {ordered[0]:+.2f}R  best {ordered[-1]:+.2f}R"
    )


def report(rows: list[dict[str, object]], months: float) -> None:
    """Per cell, then per instrument, then per era. Never pooled only.

    `pooled-medians-invert-subgroups` is why: a pooled answer on this desk has
    already agreed with a claim that every subgroup refuted, and two of the
    five figures this run is checked against - half the R from gold, negative
    in 2023-24 - are facts a pooled number hides by construction.
    """
    print(f"\n{'cell':26} {'bars':>6} {'swings':>7} {'brk':>4} {'bos':>4} {'ch':>4} "
          f"{'ord':>4} {'fill':>4} {'trd':>4} {'stop':>4} {'clk':>4} {'R':>8} {'R/trd':>7} {'/mo':>5}")
    for row in rows:
        s = row["structure"]  # type: ignore[index]
        print(
            f"{row['market']:>8} {row['era']:>8} {row['process']:>8} "  # type: ignore[index]
            f"{s['bars']:>6} {s['swing_highs'] + s['swing_lows']:>7} {s['breaks']:>4} "
            f"{s['bos']:>4} {s['choch']:>4} {row['orders']:>4} {row['fills']:>4} "
            f"{row['trades']:>4} {row['stopped']:>4} {row['clocked']:>4} "
            f"{row['r_total']:>8.2f} {row['r_mean']:>7.3f} "
            f"{row['trades'] / months:>5.1f}"  # type: ignore[operator]
        )
    for key in ("process", "market", "era"):
        print(f"\nby {key}:")
        for name in dict.fromkeys(row[key] for row in rows):  # type: ignore[index]
            cells = [row for row in rows if row[key] == name]
            rewards = [r for row in cells for r in row["r"]]  # type: ignore[union-attr]
            total = sum(rewards)
            n = len(rewards)
            sd = _sd(rewards)
            # **The standard error, printed next to the mean every time.** The
            # payoff has a one-R floor and no ceiling, so a per-trade sd of
            # several R is normal and a few hundred trades cannot resolve a
            # tenth of one. A mean without this beside it reads as a finding.
            print(
                f"  {str(name):>11}  trades {n:>4}  R {total:>8.2f}  "
                f"R/trade {total / n if n else 0.0:>+7.3f} +/- {sd / math.sqrt(n) if n else 0.0:>5.3f}  "
                f"trades/month {n / (months * len(cells)):>5.1f}"
            )
            print(f"               {tails(rewards)}")
            costs = [float(row["cost_r"]) for row in cells if row["cost_r"]]
            stops = [float(row["risk_px"]) for row in cells if row["risk_px"]]
            if costs:
                print(
                    f"               median stop {_median(stops):.5g} in price, "
                    f"round trip {_median(costs):.4f}R - which is what the mean has "
                    f"to beat before anything else"
                )
    rewards = [r for row in rows for r in row["r"]]  # type: ignore[union-attr]
    total = sum(rewards)
    print(
        f"\npooled across every arm (which is not a result, only a tally): "
        f"{len(rewards)} trades, {total:+.2f}R"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=float, default=3.0, help="per cell")
    parser.add_argument("--seed", type=int, default=20_261_102)
    parser.add_argument(
        "--process",
        default="walk,walk-flip,trend,trend-flip",
        help="walk (the null), trend (the power arm), and the reversed twin of each",
    )
    parser.add_argument("--markets", default="", help="a symbol substring, or all of them")
    #: The planted drift, as a multiple of the per-minute standard deviation.
    #: 0.01 is about 0.4 of the 24-hour move's own sd, which is a trend far
    #: stronger than anything claimed for this rule - deliberately, because
    #: the power arm has to be detectable at a sample size this box can
    #: generate. What that costs is stated in the report: an effect the size
    #: of the rule's own standing figure is **invisible** here, and saying so
    #: is the point of running the arm at all.
    parser.add_argument("--trend-strength", type=float, default=0.01)
    args = parser.parse_args()

    minutes = int(args.months * 30 * 1_440)
    settings = Settings()
    print(f"catalogue: {os.environ.get('CORPUS_DIR', '~/till-data/catalog')} - generated feed")
    print(
        f"risk_fraction {settings.risk_fraction}, break_even_at {settings.break_even_at}, "
        f"trail_vol {settings.trail_vol}, stale_after {settings.stale_after}, "
        f"scale_out_at {settings.scale_out_at}"
    )
    arms: dict[str, dict[str, float | bool]] = {
        "walk": {},
        "walk-flip": {"flip": True},
        "trend": {"strength": args.trend_strength},
        "trend-flip": {"strength": args.trend_strength, "flip": True},
    }
    rows: list[dict[str, object]] = []
    seed = args.seed
    for name in args.process.split(","):
        for market in MARKETS:
            if args.markets and args.markets.upper() not in market.symbol:
                continue
            for era in ERAS:
                seed += 1
                row = one(market, era, minutes, seed, **arms[name.strip()])  # type: ignore[arg-type]
                row["process"] = name.strip()
                rows.append(row)
                print(
                    f"{market.symbol} {era} {name}: {row['trades']} trades, "
                    f"{row['r_total']:+.2f}R in {row['seconds']}s  gates {row['gates']}"
                )
    report(rows, args.months)


if __name__ == "__main__":
    main()
