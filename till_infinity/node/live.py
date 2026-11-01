"""The live node.

One `TradingNode`: the MT5 adapter for data and execution, `statespace` as an
Actor, strategies on top. What used to be `stack.py`'s supervision, the bus,
the cache, order and position management and the risk limits are all the
engine's now.

**A node is up when the venue says so.** `_connect` on the execution client
queries the account, and that answer - not a log line of ours - is what makes
the claim. Three deploys on 2026-10-09 were built, tagged, health-checked and
reported up while running none of the code they claimed, because every check
read our own side of the wire.
"""

from __future__ import annotations

import os

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import (
    CacheConfig,
    LiveDataEngineConfig,
    LiveExecEngineConfig,
    LiveRiskEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.enums import TradingState

from till_infinity.adapters.mt5 import (
    MT5,
    MT5DataClientConfig,
    MT5ExecClientConfig,
    MT5LiveDataClientFactory,
    MT5LiveExecClientFactory,
)
from till_infinity.node import desks
from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig
from till_infinity.utils.env import flag

#: The venue's magic, and **no longer how a strategy is identified.**
#:
#: It was both, and that was the bug: append-only and positional, a strategy
#: without a slot stamped a hashed magic with no inverse, and being off by one
#: relabelled every strategy as its neighbour. Attribution is now Nautilus's
#: `strategy_id`, assigned by the framework and carried on every order, fill
#: and position - so this is one number the bridge stamps on the desk's orders
#: to tell them from a human's, which is all a magic was ever good for.
DEFAULT_MAGIC = 777_701


def settings() -> TradingNodeConfig:
    """Build the node config from the environment.

    Deliberately the same variables the desk already uses, so a deploy does
    not have to learn a new vocabulary at the same time as a new engine.
    """
    bridge = os.environ.get("TRADING_MT5_URL", "http://localhost:8000")
    key = os.environ.get("TRADING_MT5_API_KEY") or None
    return TradingNodeConfig(
        trader_id=os.environ.get("TRADER_ID", "TILL-001"),
        logging=LoggingConfig(log_level=os.environ.get("LOG_LEVEL", "INFO")),
        # **The risk limits live here, not in our code.** Nautilus's risk
        # engine owns order rate and notional caps and the HALTED/REDUCING
        # states; what stays ours is the sizing rule, because that is an input
        # to an order rather than a limit on one.
        # **`LiveRiskEngineConfig`, not `RiskEngineConfig`.** The plain one
        # raises `Cannot use RiskEngineConfig in a 'live' environment` from the
        # kernel's constructor, so this node could never be built - and nothing
        # caught it, because nothing constructed one. The same shape as the
        # three deploys that were built, tagged, health-checked and ran none of
        # the code they claimed: every check read our own side of the wire.
        risk_engine=LiveRiskEngineConfig(
            bypass=False,
            max_order_submit_rate=os.environ.get("RISK_ORDER_RATE", "10/00:00:01"),
        ),
        cache=CacheConfig(timestamps_as_iso8601=True),
        data_engine=LiveDataEngineConfig(time_bars_timestamp_on_close=True),
        # **Reconcile on start, against the broker.** The desk's own record is
        # not evidence about the account: `judge-the-desk-on-the-broker-not-
        # the-journal`, where a magic off by one relabelled every strategy.
        exec_engine=LiveExecEngineConfig(
            reconciliation=True,
            inflight_check_interval_ms=2_000,
        ),
        data_clients={
            MT5: MT5DataClientConfig(
                base_url=bridge,
                api_key=key,
                poll_seconds=float(os.environ.get("MT5_POLL_SECONDS", "0.25")),
            )
        },
        exec_clients={
            MT5: MT5ExecClientConfig(
                base_url=bridge,
                api_key=key,
                magic=int(os.environ.get("DEFAULT_MAGIC", DEFAULT_MAGIC)),
            )
        },
        timeout_connection=float(os.environ.get("NODE_CONNECT_TIMEOUT", "60")),
        timeout_reconciliation=float(os.environ.get("NODE_RECONCILE_TIMEOUT", "30")),
        timeout_portfolio=float(os.environ.get("NODE_PORTFOLIO_TIMEOUT", "30")),
        timeout_disconnection=float(os.environ.get("NODE_DISCONNECT_TIMEOUT", "30")),
        # **Positions are left alone on a clean stop.** A restart for a code
        # change must not close a book, so flattening is never implicit - it is
        # a named operation, because the right answer depends on why the node
        # is coming down.
        timeout_post_stop=float(os.environ.get("NODE_POST_STOP_TIMEOUT", "10")),
    )


def build() -> TradingNode:
    """A node with the venue registered and the desks on it, not yet running.

    **Strategies are added before `node.build()`**, because that is when
    Nautilus wires each one to the cache, the clock and the message bus. Added
    after, they exist and are never registered - which is a node that reports
    up and trades nothing, the failure three deploys on 2026-10-09 already
    produced by a different route.
    """
    node = TradingNode(config=settings())
    _arm(node)
    node.add_data_client_factory(MT5, MT5LiveDataClientFactory)
    node.add_exec_client_factory(MT5, MT5LiveExecClientFactory)

    strategies, clipped = desks.build(MT5)
    if clipped:
        # **Said out loud, never silent.** A set smaller than the one asked for
        # is the shape of bug this desk has paid for repeatedly: a min-events
        # guard once dropped 141 of 146 feeds and made 0.9 sigma look like 4.8.
        node.kernel.logger.warning(
            f"{len(clipped)} desk(s) clipped for the machine's ceiling of "
            f"{desks.ceiling()}: {', '.join(clipped)}"
        )
    if not strategies:
        # Refused rather than started empty. A live node with no strategies
        # connects, reconciles, reports healthy and trades nothing, and every
        # check that would notice reads our own side of the wire.
        raise ValueError(
            "no desks to run: TRADING_SYMBOLS names no instrument, so this "
            "node would connect, reconcile, report healthy and trade nothing."
        )
    for strategy in strategies:
        node.trader.add_strategy(strategy)
    for actor in _actors():
        node.trader.add_actor(actor)

    node.build()
    return node


def _arm(node: TradingNode) -> bool:
    """`TRADING_LIVE=1` or no orders. Returns whether the node is armed.

    **The one gate on this path that can lose money, and it fails closed.**
    `TRADING_LIVE` has always been the desk's arming switch - the retired
    `service.py` chose a paper book without it - and when that path retired on
    2026-11-01 the switch went with it: this node registered the MT5 execution
    client unconditionally, so a host with `TRADING_SYMBOLS` set and
    `TRADING_LIVE` unset sent **real orders** where the same environment used
    to paper-trade. A control regression, found by review rather than by a
    test, which is why there is now a test per state.

    The mechanism is Nautilus's own and not a flag of ours: `HALTED` denies
    every trading command except cancels inside `RiskEngine`, below the
    strategies and above the execution client, so nothing a strategy, an exit
    or a managed stop does can route around it. Set here rather than after
    `node.build()` because the engine exists from the kernel's constructor and
    this leaves no window in which an order could be accepted.

    An unarmed node still connects, reconciles, subscribes and computes. That
    is deliberate: those are reads, they are how the desk is observed, and
    refusing to build at all would make a dry run impossible on a path that
    has no paper venue wired. What it cannot do is open or change a position.
    """
    # `utils.env.flag` and not `Settings.from_env().live`: the same variable
    # read through the same primitive `Settings` uses, without the broker
    # instrument registration that `from_env` performs as a side effect.
    armed = flag("TRADING_LIVE")
    if armed:
        return True
    node.kernel.risk_engine.set_trading_state(TradingState.HALTED)
    # Said at `error`, not `info`. A node that is up, connected, reconciled
    # and refusing every order looks healthy from our own side of the wire,
    # which is exactly how three deploys on 2026-10-09 reported up while
    # running none of the code they claimed.
    node.kernel.logger.error(
        "TRADING_LIVE is not set: the risk engine is HALTED and every order "
        "will be denied. Data, reconciliation and the strategies all run; "
        "nothing reaches the venue. Set TRADING_LIVE=1 to arm."
    )
    return False


def _actors() -> list[Actor]:
    """The actors: the basket watcher, and statespace where it is configured.

    `STATESPACE_BARS` names the bar types it folds. Absent, it is not added -
    a node may trade without it, and an actor subscribed to nothing is a fold
    that never runs pretending to be a model that does.
    """
    found: list[Actor] = list(desks.actors(MT5))
    bars = tuple(
        part for part in (os.environ.get("STATESPACE_BARS") or "").replace(",", " ").split() if part
    )
    if bars:
        found.append(
            StatespaceActor(
                StatespaceConfig(
                    bar_types=bars,
                    indicators=tuple(
                        part
                        for part in (os.environ.get("STATESPACE_INDICATORS") or "")
                        .replace(",", " ")
                        .split()
                        if part
                    ),
                )
            )
        )
    return found


def main() -> None:
    node = build()
    try:
        node.run()
    finally:
        node.dispose()


if __name__ == "__main__":
    main()
