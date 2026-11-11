"""The backtest node.

**The reason for the move, in one file.** The same `Strategy` and the same
`Actor` run here and in `live.py`, over the same engine, so a measurement and
a deployment stop being different code. Nearly every hard lesson on this desk
is a measurement that did not mean what it claimed - an edge with good fills
and -98%, a 0.6365 that was overlapping touches and became 0.5092, a
directional AUC of 0.79 that collapsed to 0.51 - and all of them are the same
failure: the thing that measured and the thing that traded were not the same.

**Backtests do not run where trading runs.** tis has two cores and a research
job has already silently starved the desk on that box. A backtest is the
opposite of a small service: a burst of exactly the work the live node needs
cores for. `where()` refuses to build one on the trading host.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
    LoggingConfig,
    RiskEngineConfig,
)
from nautilus_trader.model.data import Bar, QuoteTick
from nautilus_trader.model.enums import PositionSide

from till_infinity.adapters.mt5 import MT5

#: Hosts that run the live desk and must not run a backtest.
TRADING_HOSTS = ("tis",)


class WrongHostError(RuntimeError):
    """A backtest was asked for on the box that trades."""


def where() -> str:
    """The host, having refused if it is the one that trades.

    Not advice. `tis-research-jobs-starve-the-service` is a measured outage:
    the service stalled, the journal showed it by actor rather than in docker
    logs, and the box has two cores. Set `ALLOW_BACKTEST_HERE=1` to override,
    which exists so that the refusal can be stepped over deliberately rather
    than worked around silently.
    """
    host = socket.gethostname()
    if any(h in host for h in TRADING_HOSTS) and not os.environ.get("ALLOW_BACKTEST_HERE"):
        raise WrongHostError(
            f"{host} runs the live desk - a backtest here starves it. Run it on a "
            f"burst host, or set ALLOW_BACKTEST_HERE=1 if you mean it."
        )
    return host


def catalogue() -> Path:
    """Where the bars live.

    `~/till-data` is bind-mounted on the instances, and
    `analyse-from-the-host-not-the-container` is why it is read from the host:
    `docker exec` runs in the desk's cgroup and can take the desk down with it.
    """
    return Path(os.environ.get("CORPUS_DIR", Path.home() / "till-data" / "catalog"))


#: Starting balance, in `BACKTEST_CURRENCY`. `BACKTEST_BALANCE` moves it.
DEFAULT_BALANCE = 10_000.0

#: Account leverage. **Named because it decides whether an order is
#: affordable at all**, and it was previously left at Nautilus's default
#: without anybody choosing it.
#:
#: This desk sizes a risk fraction, not a notional: 0.25% of the account
#: against a stop measured in volatility units, which on EUR/USD produced
#: **113,634 units - about 124,000 USD of notional** against a hardcoded
#: 10,000 balance. Whether that order survives the risk engine is therefore
#: entirely a leverage question, and an unset leverage silently decides every
#: backtest's trade count. A run that cannot afford its own orders reports no
#: trades, not an error.
#:
#: 30 is the retail cap on a major FX pair under both ESMA and the FCA, which
#: is the ceiling the live account is subject to; `BACKTEST_LEVERAGE` moves
#: it. It is deliberately **not** the broker's headline figure for an exotic:
#: a leverage that makes every order affordable measures the rule without the
#: constraint the desk actually trades under.
DEFAULT_LEVERAGE = 30.0


def venue(
    starting: float | None = None,
    currency: str = "USD",
    name: str = MT5,
    leverage: float | None = None,
    bar_execution: bool = True,
) -> BacktestVenueConfig:
    """The venue as the broker actually behaves.

    `NETTING`, because the Deriv account is netting and not hedging: a second
    buy adds to one position rather than opening another, and the difference
    changes what a position report means.

    **Margin, not cash.** And the fill model is left at the engine's default
    deliberately rather than tuned: `the-updown-edge-is-dead` records an edge
    that produced good fills and -98%, so a backtest that is generous about
    fills is the specific way this desk has already been misled.

    **The balance and the leverage are read from the environment**, because a
    discovery sweep and a single run have to be able to state the account they
    measured against. They were a hardcoded 10,000 and an unchosen default,
    which is the shape of a parameter that moves every result and appears in
    no write-up: `BACKTEST_BALANCE`, `BACKTEST_CURRENCY` and
    `BACKTEST_LEVERAGE` now carry them, and `described()` prints what was
    used so a result can say.

    `bar_execution` is on, which is what makes a bar-only catalogue tradable
    at all - and it is the generosity this desk has measured: a stop filled
    off a bar path fills *at* the stop with no overshoot, where the real
    overshoot was **+0.363R on spx500**. Named so a run can turn it off and
    see what it is worth rather than inheriting it unseen.
    """
    balance = (
        starting
        if starting is not None
        else float(os.environ.get("BACKTEST_BALANCE", DEFAULT_BALANCE))
    )
    gearing = (
        leverage
        if leverage is not None
        else float(os.environ.get("BACKTEST_LEVERAGE", DEFAULT_LEVERAGE))
    )
    money = os.environ.get("BACKTEST_CURRENCY", currency)
    return BacktestVenueConfig(
        default_leverage=gearing,
        bar_execution=bar_execution,
        # **Named, not hardcoded.** It was fixed at `MT5` while the desks were
        # built from the instrument's own venue, so a backtest on
        # `EURUSD.SIM` got a venue called MT5 and the instrument would never
        # have resolved - a run that fails at load, or worse, loads nothing
        # and reports a result computed from no trades.
        name=name,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency=money,
        starting_balances=[f"{balance} {money}"],
    )


def described() -> str:
    """The account a run measured against, for a write-up to quote.

    A result that does not say its balance and leverage cannot be compared to
    another, and both were previously invisible.
    """
    config = venue()
    return (
        f"{config.starting_balances[0]} at {config.default_leverage:g}x, "
        f"{config.account_type} {config.oms_type}, "
        f"bar_execution={config.bar_execution}"
    )


#: The aggregation sources a bar type spells out, which a `bar_spec` must not.
SOURCES = ("-EXTERNAL", "-INTERNAL")


def specification(bar_spec: str) -> str:
    """A `BacktestDataConfig.bar_spec` from a full bar type suffix.

    **Nautilus appends the aggregation source itself**, so a `bar_spec` that
    already carries one resolves to `...-EXTERNAL-EXTERNAL` - a bar type that
    exists nowhere. The query then returns nothing, the engine runs, and the
    result prints `PnL (total): 0.0` with every other statistic `nan`. No
    exception, no warning, and `total_orders` is zero because no strategy ever
    received a bar.

    That is the shape of every backtest this module could have produced, and
    `run_config`'s own default was `1-MINUTE-LAST-EXTERNAL`, so the defect was
    in the default. It survived because nothing had ever run: the catalogue was
    empty until `node/corpus.py`, and both agents who needed a backtest drove
    `BacktestEngine` by hand instead.

    Callers keep passing a full bar type, because that is what a desk
    subscribes to and `node/desks.bar_type` builds one. The stripping happens
    here, once.
    """
    found = bar_spec.strip()
    for source in SOURCES:
        if found.upper().endswith(source):
            return found[: -len(source)]
    return found


def data(instrument_id: str, bar_spec: str, start: str | None = None, end: str | None = None):
    """One instrument's data out of the catalogue - the bars **and** the quotes.

    A list, because a desk needs both and they are two configs.

    **An externally aggregated run used to load bars alone, and every desk
    refused every proposal.** `Desk._undealable` refuses on a missing quote,
    `Surprise.decide` refuses earlier still on its own, and `cache.quote_tick`
    returns `None` for the whole run when nothing put a quote in it - measured
    on a ten-bar probe: ten bars delivered, zero with a cached quote. So
    `desk_config()` at its default spec built the production desks over a
    stream they could not trade, and reported a result computed from no
    trades. That is the failure this desk has on record more than any other,
    and it was one line.

    **An internally aggregated run is fed quotes only.** `INTERNAL` means
    Nautilus builds the bars itself from the tick stream, so a config that also
    loaded `Bar` would hand the aggregator the output it exists to produce. The
    spec string already says which it is, so nothing has to be passed twice.

    A catalogue with no quotes still produces no trades, and that is then
    visible: the config asked for them and they were not there, rather than
    nobody having asked.
    """
    quotes = BacktestDataConfig(
        catalog_path=str(catalogue()),
        data_cls=QuoteTick,
        instrument_id=instrument_id,
        start_time=start,
        end_time=end,
    )
    if bar_spec.strip().upper().endswith("INTERNAL"):
        return [quotes]
    return [
        BacktestDataConfig(
            catalog_path=str(catalogue()),
            data_cls=Bar,
            instrument_id=instrument_id,
            bar_spec=specification(bar_spec),
            start_time=start,
            end_time=end,
        ),
        quotes,
    ]


def run_config(
    instrument_id: str,
    bar_spec: str = "1-MINUTE-LAST-EXTERNAL",
    *,
    actors=(),
    strategies=(),
    start: str | None = None,
    end: str | None = None,
    venue_name: str | None = None,
) -> BacktestRunConfig:
    """One run, with the same actors and strategies the live node takes.

    `venue_name` defaults to the instrument's own, so the venue the engine
    builds and the venue the instrument belongs to cannot disagree.
    """
    return BacktestRunConfig(
        engine=BacktestEngineConfig(
            trader_id="BACKTEST-001",
            logging=LoggingConfig(log_level=os.environ.get("LOG_LEVEL", "WARNING")),
            # The same limits as live. A backtest that is allowed to do what
            # live cannot is measuring a strategy nobody can run.
            risk_engine=RiskEngineConfig(bypass=False),
            actors=list(actors),
            strategies=list(strategies),
        ),
        venues=[venue(name=venue_name or instrument_id.rsplit(".", 1)[-1])],
        data=data(instrument_id, bar_spec, start, end),
        # **`dispose_on_completion=True` is Nautilus's default and it zeroes
        # the trade counts in the result.** `node.py` calls `engine.dispose()`
        # - "drop data and all state" - and *then* `engine.get_result()`, whose
        # `total_orders` is `cache.orders_total_count()` and whose
        # `total_positions` counts `cache.positions()`. Both read a cache that
        # was just emptied, so every run reports 0 orders and 0 positions.
        #
        # `stats_pnls` survives because it comes off the portfolio analyzer
        # rather than the cache, which is what makes this so hard to see: the
        # result carries `PnL (total): -62.32` at a 0.25 win rate next to
        # `total_orders = 0`. A sweep reading the counts concludes nothing
        # traded on a run that traded eight times, which is how `leaf_sweep`
        # reported 0 of 72 cells and why this was first mis-diagnosed as a
        # `BacktestDataConfig` bar-type fault. The data was never the problem.
        #
        # `False` leaves `clear_data()` to drop the bars - the large part - and
        # keeps the order and position records the counts are computed from.
        dispose_on_completion=False,
    )


@dataclass(frozen=True, slots=True)
class Swaps:
    """What a run's positions owed in overnight financing."""

    #: Total financing, in the account currency. Positive is a cost.
    charged: float = 0.0
    #: How many closed positions paid any of it.
    positions: int = 0
    #: How many were held across at least one rollover, which is the number
    #: that says whether a result is a carry result at all.
    overnight: int = 0
    #: How many of those the catalogue has **no swap rate for**, so they were
    #: charged zero for want of a number rather than because they owed none.
    #:
    #: Reported rather than folded away, because the two read identically in a
    #: total and only one of them is a fact. The catalogue's instruments are
    #: Nautilus's standard conventions and carry no broker swap at all, so
    #: every rate here comes from `swap.DERIV_FALLBACK` - which was measured
    #: off this broker on 2026-09-30 and covers the **Deriv indices only**. An
    #: FX pair in a backtest therefore owes nothing, and a reader has to be
    #: told that rather than left to infer it from a zero.
    unknown: int = 0

    def __str__(self) -> str:
        said = (
            f"swap {self.charged:.2f} over {self.overnight} of "
            f"{self.positions} positions held overnight"
        )
        if self.unknown:
            said += f"; {self.unknown} held overnight with no rate, charged nothing"
        return said


def swap_charged(engine: Any) -> Swaps:
    """The overnight financing a finished run's closed positions owed.

    **Charged after the fact rather than at a fill, because Nautilus has no
    financing hook.** A `FeeModel` sees `(order, quantity, price)` and knows
    nothing about how long a position will be held, so a swap charged there
    would have to be the *planned* hold - the quantity the live gate prices -
    rather than the one that happened. A closed position carries both
    timestamps, so this charges what was actually owed.

    `research/docs/carry.md` is the measurement: about the interbank
    differential plus a markup on FX, and on the 24/7 synthetics an annual
    rate on **both** sides - Boom 1000 36% a year, Crash 1000 about 5 bps a
    night. `swap-does-not-cancel-in-a-long-short-basket` is the consequence
    that catches people out: both legs of a market-neutral basket pay, so a
    CFD basket that is market-neutral is not carry-neutral.

    **It is a cost on top of the spread, not instead of it.** The catalogue's
    quotes already straddle each close by the feed's measured median spread,
    which is the round-trip cost; this is the cost of time. A 15-minute rule
    crosses no rollover and owes nothing, which is the right answer and is
    also why swap alone would make every intraday rule read as free.

    **The catalogue has no broker swap, so most of the book owes nothing
    here.** Its instruments are Nautilus's standard conventions - there is no
    `symbol_info` without the terminal - so every rate comes from
    `swap.DERIV_FALLBACK`, which covers the Deriv indices and not FX. An FX
    backtest is charged zero, and `Swaps.unknown` counts the positions that
    happened to, so the two readings of a zero stay apart.

    Returns zeroes rather than raising where the engine kept no positions:
    `dispose_on_completion=True` empties the cache, and a run reporting no
    swap because its records were dropped must not look like a run that owed
    none - so `positions` says which it was.
    """
    from ..domain import swap
    from ..domain.models import Side
    from ..strategies import sizes

    cache = getattr(engine, "cache", None)
    if cache is None:
        return Swaps()
    from ..domain.swap import _terms

    total = 0.0
    counted = 0
    overnight = 0
    unknown = 0
    for position in cache.positions_closed():
        counted += 1
        opened = float(getattr(position, "ts_opened", 0) or 0) / 1e9
        closed = float(getattr(position, "ts_closed", 0) or 0) / 1e9
        if opened <= 0.0 or closed <= opened:
            continue
        instrument = cache.instrument(position.instrument_id)
        if instrument is None:
            continue
        side = Side.BUY if position.side == PositionSide.LONG else Side.SELL
        # In price units per unit held, which the corpus's instruments turn
        # into quote-currency money by the quantity alone: both shapes it
        # builds price one unit of the underlying - see `CONTRACTS`.
        cost = swap.expected(
            sizes.spec_of(instrument),
            sizes.feed_of(position.instrument_id),
            side,
            float(position.avg_px_open or 0.0),
            opened,
            closed - opened,
        )
        if cost <= 0.0:
            # A hold that crossed a rollover and was charged nothing is one of
            # two different facts, and the total cannot tell them apart.
            feed = sizes.feed_of(position.instrument_id)
            if _terms(sizes.spec_of(instrument), feed) is None and swap.nights(
                opened, closed - opened, swap.NO_TRIPLE
            ):
                unknown += 1
            continue
        overnight += 1
        total += cost * float(position.quantity)
    return Swaps(charged=total, positions=counted, overnight=overnight, unknown=unknown)


def run(configs) -> list:
    """Run them, having checked this is a host allowed to.

    The engines are kept (`dispose_on_completion=False`) so a caller can read
    the closed positions a result does not carry - which is what
    `swap_charged` needs and what `discovery.read` already does for returns.
    """
    where()
    node = BacktestNode(configs=list(configs))
    results = node.run()
    if charges():
        for result in results:
            found = swap_charged(node.get_engine(result.run_config_id))
            if found.overnight:
                print(f"{result.run_config_id}: {found}")
    return results


def charges() -> bool:
    """Whether a run reports the swap its positions owed. `BACKTEST_SWAP`, on.

    On by default, because the cost is real and was charged nowhere: a run
    that silently omits a cost the live desk pays is the shape of measurement
    this file's own docstring is about. Off is for reproducing a number
    measured before it existed.
    """
    return (os.environ.get("BACKTEST_SWAP", "1").strip().lower()) not in ("0", "false", "no", "")


def desk_config(
    instrument_id: str,
    bar_spec: str = "15-MINUTE-LAST-EXTERNAL",
    *,
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
) -> BacktestRunConfig:
    """One run, with **the desks the live node would build**.

    The whole argument for the move, in one function: `node/desks.py` derives
    the set from the same environment for both, so a measurement and a
    deployment are the same desks rather than two sets that agree until they
    do not. `test_desks.py` asserts the two name the same ones.

    The venue is taken from the instrument, so a backtest on `EURUSD.SIM` runs
    simulated desks and one on `EURUSD.MT5` runs the deployed ones against
    stored data.
    """
    from . import desks

    venue_name = instrument_id.rsplit(".", 1)[-1]
    strategies, clipped = desks.importable(venue_name, limit=limit)
    if not strategies:
        raise ValueError(
            f"no desks for {instrument_id}: TRADING_SYMBOLS names no "
            f"instrument, so this backtest would run nothing and report a "
            f"result computed from no trades."
        )
    if clipped:
        print(f"clipped {len(clipped)} desk(s) for the ceiling: {', '.join(clipped)}")
    return run_config(
        instrument_id,
        bar_spec,
        actors=desks.importable_actors(venue_name, fresh=True),
        strategies=strategies,
        start=start,
        end=end,
    )


def main() -> None:
    """Report what this box would allow, since a bare run has nothing to run.

    A backtest needs actors and strategies named, and naming them on a command
    line was what the retired CLI did. Run as a module it says whether a sweep
    is permitted here and what it would cost - which is the question worth
    answering before anything else.
    """
    from .sizing import describe
    from .windows import budget

    print(f"host: {where()}")
    print(f"sizing: {describe()}")
    print(f"catalogue: {catalogue()}")
    print(budget(per_day=50, candidates=20))


if __name__ == "__main__":
    main()
