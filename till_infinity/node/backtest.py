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
from pathlib import Path

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


def venue(
    starting: float = 10_000.0, currency: str = "USD", name: str = MT5
) -> BacktestVenueConfig:
    """The venue as the broker actually behaves.

    `NETTING`, because the Deriv account is netting and not hedging: a second
    buy adds to one position rather than opening another, and the difference
    changes what a position report means.

    **Margin, not cash.** And the fill model is left at the engine's default
    deliberately rather than tuned: `the-updown-edge-is-dead` records an edge
    that produced good fills and -98%, so a backtest that is generous about
    fills is the specific way this desk has already been misled.
    """
    return BacktestVenueConfig(
        # **Named, not hardcoded.** It was fixed at `MT5` while the desks were
        # built from the instrument's own venue, so a backtest on
        # `EURUSD.SIM` got a venue called MT5 and the instrument would never
        # have resolved - a run that fails at load, or worse, loads nothing
        # and reports a result computed from no trades.
        name=name,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency=currency,
        starting_balances=[f"{starting} {currency}"],
    )


def data(instrument_id: str, bar_spec: str, start: str | None = None, end: str | None = None):
    """One instrument's data out of the catalogue - bars, or the ticks behind them.

    **An internally aggregated run is fed quotes, not bars.** `INTERNAL` means
    Nautilus builds the bars itself, from the tick stream, so a data config
    that loaded `Bar` would hand an aggregator the output it was supposed to
    produce: the aggregator would receive nothing, the desks would receive no
    bars, and the run would report a result computed from no trades. The spec
    string already says which it is, so nothing has to be passed twice.

    This is the half of internal aggregation that only shows up in a backtest.
    Live, the adapter publishes quotes whatever the bar type is; here the
    catalogue has both and the config chooses.
    """
    if bar_spec.strip().upper().endswith("INTERNAL"):
        return BacktestDataConfig(
            catalog_path=str(catalogue()),
            data_cls=QuoteTick,
            instrument_id=instrument_id,
            start_time=start,
            end_time=end,
        )
    return BacktestDataConfig(
        catalog_path=str(catalogue()),
        data_cls=Bar,
        instrument_id=instrument_id,
        bar_spec=bar_spec,
        start_time=start,
        end_time=end,
    )


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
        data=[data(instrument_id, bar_spec, start, end)],
    )


def run(configs) -> list:
    """Run them, having checked this is a host allowed to."""
    where()
    return BacktestNode(configs=list(configs)).run()


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
        actors=desks.importable_actors(venue_name),
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
