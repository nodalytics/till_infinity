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

import contextlib
import os
import sys
from decimal import Decimal

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
from nautilus_trader.model.identifiers import StrategyId

from till_infinity.adapters.mt5 import MT5DataClientConfig, MT5ExecClientConfig
from till_infinity.node import desks, ladder, venues
from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig
from till_infinity.utils.env import flag
from till_infinity.utils.topics import LADDER

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
        # **One client pair per venue, in one kernel.** Nautilus keys its
        # clients by name and runs them side by side with one cache and one
        # portfolio, which is what makes exposure across venues answerable at
        # all - a node per venue would put each one's positions out of the
        # other's sight. Only MT5 has an adapter, so several venues today
        # means several MT5 accounts: a demo beside a live one, or two brokers
        # both on MT5.
        data_clients={venue: venues.configs(venues.kind(venue), venue)[0] for venue in _wanted()},
        exec_clients={venue: venues.configs(venues.kind(venue), venue)[1] for venue in _wanted()},
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


def _wanted() -> tuple[str, ...]:
    """The venues this node runs, from the one place that decides.

    `settings()` registers the clients and `build()` registers the factories,
    and the two must name the same venues or a client is configured with no
    factory to build it - which fails at `node.build()` with a message about
    a missing factory rather than about a mismatched list.
    """
    return desks.venues()


def _env(name: str, venue: str, fallback: str | None = None) -> str | None:
    """A setting for one venue, or the shared one.

    `TRADING_MT5_URL_DERIV` beats `TRADING_MT5_URL`, so a second venue is
    added by naming what differs rather than by re-stating everything. The
    venue is upper-cased into the variable name because that is how every
    other variable here is spelled and a mixed-case one would be missed
    silently - which, for a credential, means connecting to the wrong account.
    """
    return os.environ.get(f"{name}_{venue.upper()}") or os.environ.get(name) or fallback


def data_config(venue: str) -> MT5DataClientConfig:
    return MT5DataClientConfig(
        base_url=_env("TRADING_MT5_URL", venue, "http://localhost:8000"),
        api_key=_env("TRADING_MT5_API_KEY", venue),
        poll_seconds=float(_env("MT5_POLL_SECONDS", venue, "0.25")),
        transport=_env("TRADING_MT5_TRANSPORT", venue, "http"),
        rpyc_host=_env("TRADING_RPYC_HOST", venue),
        rpyc_port=int(_env("TRADING_RPYC_PORT", venue, "18812")),
    )


def exec_config(venue: str) -> MT5ExecClientConfig:
    return MT5ExecClientConfig(
        base_url=_env("TRADING_MT5_URL", venue, "http://localhost:8000"),
        api_key=_env("TRADING_MT5_API_KEY", venue),
        # **Per venue, and that is the point of it.** The magic tells this
        # desk's orders from a human's on the same account, so two venues that
        # are two accounts may share one - but two *desks* on one account must
        # not, and being off by one relabels every strategy as its neighbour.
        #
        # **`TRADING_MAGIC`, and it read `DEFAULT_MAGIC` until 2026-11-01** -
        # the *constant's* name passed where a variable name belongs, so the
        # documented knob reached nothing and the live one was a spelling
        # nobody had written down. Every sibling below passes the full
        # variable name; this one did not, and the default being identical is
        # why no deploy noticed. The old spelling is not kept as a fallback: it
        # was a bug rather than an interface, and two names for one number is
        # how one of them goes stale.
        magic=int(_env("TRADING_MAGIC", venue, str(DEFAULT_MAGIC))),
        transport=_env("TRADING_MT5_TRANSPORT", venue, "http"),
        rpyc_host=_env("TRADING_RPYC_HOST", venue),
        rpyc_port=int(_env("TRADING_RPYC_PORT", venue, "18812")),
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
    for venue in _wanted():
        data, orders = venues.factories(venues.kind(venue))
        node.add_data_client_factory(venue, data)
        node.add_exec_client_factory(venue, orders)

    strategies, clipped = desks.build_all()
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
    for actor in _actors(len(strategies)):
        node.trader.add_actor(actor)

    node.build()
    _supervise(node)
    return node


def _supervise(node: TradingNode) -> None:
    """Let the promotion ladder reach the trader and the risk engine.

    **The one thing `LadderActor` cannot do itself.** Nautilus gives an actor
    the bus, the cache, the clock and the portfolio; changing a notional cap is
    `RiskEngine.set_max_notional_per_order` and stopping one strategy is
    `Trader.stop_strategy`, and an actor has neither object. So the actor
    publishes its decisions and this subscribes a handler closed over both -
    which also puts the conversion from a share to a notional where the account
    is, rather than in a second copy of the arithmetic beside the loop.

    Subscribed after `node.build()`, because the kernel's risk engine and
    trader are what the closure captures and they are built with it.

    Does nothing when the ladder is not running, which is the default: an
    unsubscribed topic with no publisher is the quiet state, not a broken one.
    """
    from . import ladder as rungs

    if not rungs.wanted():
        return

    def apply(message: object) -> None:
        """One ladder decision, applied to the engine.

        Every failure is caught. This runs on the publishing actor's stack -
        Nautilus's bus calls handlers inline - so a cap that cannot be applied
        must not take down the pass that decided it, and the allocation already
        in force stays in force, which is the safe direction.
        """
        if not isinstance(message, dict):
            return
        name = str(message.get("candidate") or "")
        action = str(message.get("action") or "")
        try:
            if action in ("REDUCING", "HALTED"):
                # **Stopping the one strategy, not the node.** `retire`'s
                # docstring describes `TradingState.REDUCING` followed by
                # `stop_strategy`, and that is right for a node-level
                # wind-down and wrong for one leg: the trading state is global,
                # so putting the engine in `REDUCING` to retire one candidate
                # would stop every other strategy opening a position. A
                # breached limit is the exception and keeps the global halt,
                # because that is what a breach means.
                if action == "HALTED":
                    node.kernel.risk_engine.set_trading_state(TradingState.HALTED)
                    node.kernel.logger.error(
                        f"ladder halted the node over {name}: a risk limit was breached"
                    )
                node.trader.stop_strategy(StrategyId(name))
                node.kernel.logger.warning(f"ladder stopped {name}")
                return

            share = float(message.get("share") or 0.0)
            if share <= 0.0:
                return
            # The cap is per instrument and the ladder decides per strategy, so
            # it is applied to the instruments that strategy trades. One
            # position per instrument is already the desk's rule - see
            # `Desk._already_held` - so the two keyings do not collide in
            # practice, and where they would the tighter cap is the one that
            # should win.
            for config in (s.config for s in node.trader.strategies() if str(s.id) == name):
                instrument_id = getattr(config, "instrument_id", None)
                if instrument_id is None:
                    continue
                account = node.portfolio.account(instrument_id.venue)
                balance = account.balance_total() if account is not None else None
                if balance is None:
                    node.kernel.logger.warning(
                        f"ladder cannot cap {name}: {instrument_id.venue} reports no balance"
                    )
                    continue
                instrument = node.cache.instrument(instrument_id)
                # **The engine denominates the cap in the instrument's quote
                # currency** - `risk/engine.pyx` builds
                # `Money(float(setting), instrument.quote_currency)` - and the
                # share is of an account balance. Where those two currencies
                # differ the number needs the same conversion `Desk._rate`
                # does, and a cap applied without it is wrong by the rate. Not
                # applied rather than guessed: an unguarded instrument is
                # visible in this log, and a cap 150 times the wrong size is
                # not visible anywhere.
                if instrument is None or instrument.quote_currency != balance.currency:
                    node.kernel.logger.warning(
                        f"ladder cannot cap {name} on {instrument_id}: the account is in "
                        f"{balance.currency} and the instrument is quoted in "
                        f"{getattr(instrument, 'quote_currency', 'an unknown currency')}"
                    )
                    continue
                # A `Decimal`, not a `Money`. The setter documents "integer,
                # float, string, or Decimal" and the config path calls
                # `Decimal(value)` on what it is given, so a currency in the
                # value is an `InvalidOperation` rather than a unit.
                cap = Decimal(f"{float(balance.as_double()) * share:.2f}")
                node.kernel.risk_engine.set_max_notional_per_order(instrument_id, cap)
                node.kernel.logger.info(
                    f"ladder capped {name} on {instrument_id} at {cap} "
                    f"{balance.currency} ({share:.0%} of the account)"
                )
        except Exception as exc:  # a cap that cannot be applied is not a halt
            node.kernel.logger.error(f"ladder could not apply {action} to {name}: {exc}")

    node.kernel.msgbus.subscribe(LADDER, apply)


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


def _actors(registered: int = 0) -> list[Actor]:
    """The actors: the basket watchers, the record, the alerts, and statespace.

    `registered` is how many strategies the caller built, passed through to the
    heartbeat because an `Actor` can reach `trader_id` and nothing else. The
    heartbeat used to count `cache.strategy_ids()`, which is empty until a
    strategy has an order, so the healthcheck called every fresh desk "up and
    trading nothing".

    `STATESPACE_BARS` names the bar types statespace folds. Absent, it is not
    added - a node may trade without it, and an actor subscribed to nothing is
    a fold that never runs pretending to be a model that does.

    **The journal and the notifier are added by default and switched off by
    name**, which is the opposite of statespace and deliberately so. A node
    that trades without a record is the state this desk has been in since the
    port - both actors existed and neither was ever registered, so every
    refusal reason went to a debug log and every alert to nothing - and the
    failure is silent in both cases. An opt-in record is a record nobody
    turns on.
    """
    found: list[Actor] = list(desks.actors_all())
    if not flag("JOURNAL_OFF"):
        from till_infinity.journal.actor import JournalActor, JournalConfig

        found.append(
            JournalActor(
                JournalConfig(
                    path=os.environ.get("JOURNAL_DB") or JournalConfig().path,
                    flush_seconds=float(os.environ.get("JOURNAL_FLUSH_SECONDS", "5.0")),
                )
            )
        )
    if not flag("STATUS_OFF"):
        # **What the container's `HEALTHCHECK` reads.** Without it the probe
        # has no source and can only prove a process is alive, which Docker
        # already knew - and the three deploys on 2026-10-09 were health
        # checked exactly that way while running none of the code they
        # claimed. On by default for the same reason as the journal: a check
        # nobody turns on is a check nobody has.
        from till_infinity.node.status import Heartbeat, HeartbeatConfig

        # **The kwarg is omitted when the variable is unset**, not passed as
        # `None`. `HeartbeatConfig.path` is a `str` with a default, so `None`
        # reached `Path(None)` and raised `TypeError` - which meant the node
        # could not build at all unless `TILL_STATUS_PATH` was set, and unset
        # is the default case.
        #
        # My own smoke test set the variable, so it exercised the configured
        # path and never the default. `status.DEFAULT_PATH` already reads the
        # environment itself, so there is nothing for this to pass on.
        found.append(Heartbeat(HeartbeatConfig(registered=registered)))
    if not flag("ALERTS_OFF"):
        from till_infinity.notifications.actor import Notifier, NotifierConfig

        found.append(
            Notifier(
                NotifierConfig(
                    minimum_level=os.environ.get("ALERTS_MINIMUM_LEVEL")
                    or NotifierConfig().minimum_level,
                )
            )
        )
    if ladder.wanted():
        # **Opt-in, unlike the journal and the notifier beside it.** Those two
        # are on by default because a node that trades without a record is the
        # worse failure. This one changes how much of the account a strategy
        # may use, so it is off until asked - the same argument as
        # `TRADING_LIVE`, and the reason `_supervise` is what finally lets it
        # reach the engine.
        found.append(ladder.LadderActor(ladder.configured()))
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


def check() -> int:
    """Build the node and exit, without connecting or trading.

    **A preflight for a deploy, and the thing that would have prevented an
    outage.** On 2026-11-03 a deploy met an environment still naming sixteen
    retired rules, `desks.rules` raised as designed, and the container
    restart-looped **27 times** - having already replaced a working desk. The
    pipeline detected it afterwards and failed the job, which left production
    down rather than untouched.

    Everything that reads configuration happens in `build`: the rule names,
    the entry and exit names, the symbols, the venues, the bar types. So
    running `build` against the host's own environment, in the image about to
    be deployed, catches a stale variable **before** anything is switched
    over. It opens no socket and places no order.

    What it cannot catch is a name the broker does not carry: a symbol is only
    wrong once the bridge answers 404, and the node stays up and healthy while
    every quote poll fails. That is a separate check against a live bridge and
    is deliberately not done here, because a preflight that needs the venue
    cannot run before the venue is reachable.
    """
    try:
        node = build()
    except Exception as exc:
        print(f"preflight FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    try:
        count = len(getattr(node.trader, "strategies", lambda: ())())
    except Exception:
        count = -1
    print(f"preflight ok: node built, {count} strategies")
    # Disposing a node that never ran is not a failure.
    with contextlib.suppress(Exception):
        node.dispose()
    return 0


def main() -> None:
    if "--check" in sys.argv[1:]:
        raise SystemExit(check())
    node = build()
    try:
        node.run()
    finally:
        node.dispose()


if __name__ == "__main__":
    main()
