"""Can `SIZING_MULTIPLIERS` change a position size in a backtest? Run it.

`sizing_multipliers.py` next door replays the recorded trades. This runs the
engine, because a reachability claim read off a grep is a claim about text and
the question is about behaviour: **does a desk the node would build ever reach
`Profile.multipliers`, and does the switch change what it places?**

The engine is the low-level `BacktestEngine` rather than `node/backtest.py`'s
`desk_config`, for one reason stated plainly: `desk_config` reads a Nautilus
catalogue out of `~/till-data/catalog`, which does not exist on this machine.
The bars here come from `.data/prices/prices.db`, which does. Everything else
is the shipped article - the real `StatespaceActor`, the real `SurpriseEdge`,
the real gates.

**The quotes are synthesised** from each bar's close at a one-point spread, and
nothing measured here depends on their values: they exist so `_undealable`'s
`no-quote` gate is not the thing that stops the run, which would hide whatever
stops it next. They are the only invented input and they are labelled.

Run: `.venv/bin/python research/ideas/sizing_multipliers_engine.py`
"""

from __future__ import annotations

import datetime
import os
import pathlib
import sqlite3
import sys
import tempfile

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from till_infinity.statespace import proposing  # noqa: E402
from till_infinity.utils import topics  # noqa: E402
from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig  # noqa: E402
from till_infinity.strategies import desk as desk_module  # noqa: E402
from till_infinity.strategies import profile as profile_module  # noqa: E402
from till_infinity.strategies.entries import EdgeEntryConfig  # noqa: E402
from till_infinity.strategies.surprise import SurpriseEdge  # noqa: E402

PRICES = pathlib.Path(".data/prices/prices.db")
VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
BAR_SPEC = "15-MINUTE-LAST-EXTERNAL"
BAR_TYPE = BarType.from_str(f"{EURUSD.id}-{BAR_SPEC}")


def bars(limit: int = 5_200) -> list[Bar]:
    """EURUSD 15m out of the price store, oldest first."""
    sql = (
        "select ts, open, high, low, close, volume from bars "
        "where feed='eurusd' and interval='15m' and venue='OANDA' "
        "order by ts limit ?"
    )
    with sqlite3.connect(f"file:{PRICES}?mode=ro", uri=True) as db:
        rows = list(db.execute(sql, (limit,)))
    made = []
    for ts, o, h, low, c, volume in rows:
        seconds = ts / 1000.0 if ts > 1e11 else float(ts)
        ns = int(seconds * 1e9)
        made.append(
            Bar(
                bar_type=BAR_TYPE,
                open=Price(o, EURUSD.price_precision),
                high=Price(h, EURUSD.price_precision),
                low=Price(low, EURUSD.price_precision),
                close=Price(c, EURUSD.price_precision),
                volume=Quantity(max(float(volume or 0.0), 1.0), EURUSD.size_precision),
                ts_event=ns,
                ts_init=ns,
            )
        )
    return made


def quotes(made: list[Bar]) -> list[QuoteTick]:
    """One synthesised quote a bar, a point either side of the close."""
    step = float(EURUSD.price_increment)
    out = []
    for bar in made:
        mid = float(bar.close)
        out.append(
            QuoteTick(
                instrument_id=EURUSD.id,
                bid_price=Price(mid - step, EURUSD.price_precision),
                ask_price=Price(mid + step, EURUSD.price_precision),
                bid_size=Quantity(1_000_000, EURUSD.size_precision),
                ask_size=Quantity(1_000_000, EURUSD.size_precision),
                ts_event=bar.ts_event + 1,
                ts_init=bar.ts_event + 1,
            )
        )
    return out


class Counted:
    """Call counters hung on the shipped classes for the length of one run."""

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}
        self._undo: list[tuple[object, str, object]] = []

    def wrap(self, owner, name: str, label: str) -> None:
        original = getattr(owner, name)

        def counting(*args, **kwargs):
            self.hits[label] = self.hits.get(label, 0) + 1
            return original(*args, **kwargs)

        setattr(owner, name, counting)
        self._undo.append((owner, name, original))

    def __enter__(self) -> Counted:
        self.wrap(profile_module.Profile, "multipliers", "Profile.multipliers")
        self.wrap(profile_module.Profile, "risk_scale", "Profile.risk_scale")
        self.wrap(profile_module, "spike_scale", "profile.spike_scale")
        self.wrap(proposing, "proposal_for", "proposing.proposal_for")
        self.wrap(desk_module.Desk, "on_data", "Desk.on_data")
        self.wrap(desk_module.Desk, "consider", "Desk.consider")
        self.wrap(StatespaceActor, "on_bar", "StatespaceActor.on_bar")
        self.wrap(StatespaceActor, "_propose", "StatespaceActor._propose")
        self.wrap(topics, "publish", "topics.publish")
        return self

    def __exit__(self, *_exc) -> None:
        for owner, name, original in reversed(self._undo):
            setattr(owner, name, original)


#: **Scope, and a state directory that is not production's.** `statespace`
#: folds `("1m", "5m")` by default and `Engine.observe_bar` returns `None` for
#: anything else, so 15m bars produce no reading at all - and `Engine.restore`
#: reads `.data/statespace/`, whose live progress is months ahead of these
#: bars, which would make every one of them a replay and skip it. Both are
#: pointed somewhere harmless.
SCOPE = {
    "STATESPACE_INTERVALS": "15m",
    "STATESPACE_FEEDS": "eurusd",
    # A scratch directory, never `.data/statespace/`: `Engine.on_stop` saves
    # with `force=True`, so a run pointed at the real one rewrites production's
    # progress file for a measurement that wanted to read bars.
    "STATESPACE_STATE_DIR": os.environ.get(
        "MEASURE_STATE_DIR"
    ) or tempfile.mkdtemp(prefix="till-measure-statespace-"),
}


def run(switch: str | None, data: list[Bar], ticks: list[QuoteTick]) -> dict:
    """One arm. `switch` is the `SIZING_MULTIPLIERS` value, or None for unset."""
    # **A fresh state directory per arm, and the first run proved why.** The
    # engine saves its progress and `observe_bar` skips a bar at or before
    # `seen.at`, so a second arm restoring the first arm's progress folds
    # 5,136 bars and publishes nothing - which reads exactly like a switch
    # that turned the desk off.
    for name, value in SCOPE.items():
        os.environ[name] = value
    where = pathlib.Path(SCOPE["STATESPACE_STATE_DIR"]) / f"arm-{switch or 'unset'}"
    if where.exists():
        for found in where.iterdir():
            found.unlink()
    where.mkdir(parents=True, exist_ok=True)
    os.environ["STATESPACE_STATE_DIR"] = str(where)
    was = os.environ.pop("SIZING_MULTIPLIERS", None)
    if switch is not None:
        os.environ["SIZING_MULTIPLIERS"] = switch
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="MEASURE-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    try:
        engine.add_venue(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USD,
            starting_balances=[Money(10_000, USD)],
        )
        engine.add_instrument(EURUSD)
        engine.add_data(data)
        engine.add_data(ticks)
        engine.add_actor(
            StatespaceActor(
                StatespaceConfig(
                    bar_types=(str(BAR_TYPE),),
                    feeds={"EUR/USD": "eurusd"},
                    proposals=True,
                )
            )
        )
        strategy = SurpriseEdge(
            EdgeEntryConfig(
                instrument_id=EURUSD.id,
                bar_type=BAR_TYPE,
                rule="statespace-surprise",
                order_id_tag="001",
            )
        )
        engine.add_strategy(strategy)
        with Counted() as counted:
            engine.run()
        account = engine.trader.generate_account_report(VENUE)
        return {
            "switch": switch,
            "counts": dict(counted.hits),
            "orders": len(engine.cache.orders()),
            "positions": len(engine.cache.positions()),
            "taken": strategy.taken,
            "refused": strategy.refused,
            "gates": dict(sorted(strategy.passed_over.items())),
            "equity": None if account.empty else float(account.iloc[-1]["total"]),
        }
    finally:
        engine.dispose()
        os.environ.pop("SIZING_MULTIPLIERS", None)
        if was is not None:
            os.environ["SIZING_MULTIPLIERS"] = was


def main() -> None:
    data = bars()
    if not data:
        print(f"no eurusd 15m bars in {PRICES} - nothing to run")
        return
    span = (
        datetime.datetime.fromtimestamp(data[0].ts_event / 1e9, datetime.UTC),
        datetime.datetime.fromtimestamp(data[-1].ts_event / 1e9, datetime.UTC),
    )
    print(f"{len(data)} bars, {span[0]:%Y-%m-%d} .. {span[1]:%Y-%m-%d}, "
          f"{BAR_SPEC}, {EURUSD.id}")
    ticks = quotes(data)
    for switch in (None, "all", "spike", "interval"):
        got = run(switch, data, ticks)
        label = "unset" if switch is None else switch
        print(f"\nSIZING_MULTIPLIERS={label}")
        print(f"  counts     {got['counts']}")
        print(f"  orders     {got['orders']}   positions {got['positions']}")
        print(f"  taken      {got['taken']}   refused {got['refused']}")
        print(f"  equity     {got['equity']}")
        print(f"  gates      {got['gates']}")


if __name__ == "__main__":
    main()
