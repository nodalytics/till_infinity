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
import logging
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
from till_infinity.utils.env import flag, symbol_names
from till_infinity.utils.topics import LADDER

log = logging.getLogger(__name__)

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
            # **Without this the desk does not notice that the broker closed a
            # position.** `reconciliation=True` reconciles at startup and
            # `inflight_check_interval_ms` watches orders this process is still
            # waiting on; neither re-reads the book afterwards, and the engine
            # said so on every boot: `continuous reconciliation with intervals:
            # inflight=2000ms, consistency=Nones, position=Nones`.
            #
            # Measured on 2026-11-09, the first day this desk ever filled. It
            # opened BTCUSD long at 19:00:26; the broker's own stop closed it at
            # **19:01:55** for +3.18; the desk went on trailing that stop at
            # 19:06, logging an error per attempt because the ticket was
            # "neither a resting order nor an open position"; and it did not
            # emit `PositionClosed` until **19:20:27** - eighteen and a half
            # minutes believing it held a position it did not, which is also
            # eighteen minutes in which a new signal would have been refused as
            # a duplicate.
            #
            # 60s, the conservative end of Nautilus's recommended 30-60: every
            # check is a `/positions/` read against a single Wine-hosted
            # terminal that the same box serves quotes from, and the thing this
            # catches resolves in minutes, not seconds.
            position_check_interval_secs=60.0,
            # **`open_check_interval_secs` is deliberately left unset.** It
            # polls the venue for orders the cache thinks are open, and this
            # venue has none of the kind: MT5 carries a stop and a target as
            # *fields on the position*, so the adapter reports a bracket's legs
            # against the entry's ticket with an `-SL`/`-TP` suffix. Asking the
            # venue about those would be asking after orders that by design do
            # not exist, and the check resolves what it cannot find - so it
            # would cancel this desk's protective legs for being absent.
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
    """The read side. **`quote_source` is wired here and was not.**

    `data.py` implements three sources and validates the name, and this
    function never passed one - so every deploy ran `poll` whatever it asked
    for, and `push` and `ticks` were unreachable from configuration. That is
    the third feature found this way: the news adapters had no consumer and
    `statespace.proposals` had no subscriber, both for weeks.

    It matters beyond tidiness. `poll` asks each symbol for its latest tick
    every `poll_seconds`, so **seven symbols at 0.25s is 28 requests a second**
    and sixty-four would be 256 - on an instance with two cores, through an SSH
    tunnel. `push` is one WebSocket for every symbol, and the bridge polls
    centrally for any symbol with no EA attached, so the request count stops
    scaling with the universe whether or not the EA is there.

    It stays `poll` by default: that is what every existing deploy has been
    running, and a default that changes the transport under a working desk is
    not a default.
    """
    return MT5DataClientConfig(
        base_url=_env("TRADING_MT5_URL", venue, "http://localhost:8000"),
        api_key=_env("TRADING_MT5_API_KEY", venue),
        quote_source=_env("TRADING_MT5_QUOTE_SOURCE", venue, "poll"),
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

    `STATESPACE_BARS` names the bar types statespace folds. **Absent, it is
    derived from the desks when a configured rule needs it, and omitted only
    when none does.**

    It used to be omitted whenever the variable was empty, on the argument
    that "an actor subscribed to nothing is a fold that never runs pretending
    to be a model that does". That is true and it was the wrong default,
    because it does not ask what the desks consume. Measured on the live
    instance on 2026-11-04: `TRADING_STRATEGIES=smc-bos-causal,statespace-surprise`
    with `STATESPACE_BARS` unset, so **seven of fourteen desks subscribed to
    `statespace.proposals` and nothing published it**. They could not trade,
    nothing raised, and both sides looked healthy - the desks logged
    `proposals on statespace.proposals` and the actor simply did not exist.

    `desks.importable_actors` already defaults the bar types this way for the
    backtest path, and its docstring says why: a sweep over those rules
    "completed, reported no orders and raised nothing: a consumer with no
    producer, where both sides look healthy. That exact shape has now hidden
    this topic three times." This is the fourth, and the asymmetry between the
    two paths was the cause - the thing that measures and the thing that trades
    were not the same thing, which is the failure the whole port argues
    against.

    So: if any configured rule consumes proposals, the actor is built on the
    bars the desks already subscribe to. If none does, it is still omitted.

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
    found.extend(_statespace())
    return found


def _statespace() -> list[Actor]:
    """The fold, built when a configured rule consumes its proposals.

    **Two defects lived in the five lines this replaces.**

    It split both variables with `.replace(",", " ").split()`, which cannot
    express a value containing a space - and a bar type for a Deriv synthetic
    is `Volatility 75 Index.MT5-15-MINUTE-LAST-EXTERNAL`. The same shape
    produced three desks on instruments no venue lists before `symbol_names`
    was written for it; this was the third place carrying it.

    And it built the actor **only** when `STATESPACE_BARS` was set, without
    asking what the desks consume. Measured on the live instance on
    2026-11-04: `TRADING_STRATEGIES=smc-bos-causal,statespace-surprise` with
    the variable unset, so **seven of fourteen desks subscribed to
    `statespace.proposals` and nothing published it**. They could not trade,
    nothing raised, and both halves looked healthy - each desk logged
    `proposals on statespace.proposals` and the actor simply did not exist.

    `desks.importable_actors` already defaults these bars for the backtest
    path, and its docstring says why: a sweep over those rules "completed,
    reported no orders and raised nothing: a consumer with no producer, where
    both sides look healthy. That exact shape has now hidden this topic three
    times." This was the fourth, and the asymmetry between the two paths was
    the cause.

    The import is function-local because `statespace` is a separate
    distribution: a deleted directory should fail this actor, not stop the
    node importing.
    """
    from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig

    named = symbol_names(os.environ.get("STATESPACE_BARS"))
    wanted = tuple(rule for rule in desks.rules() if rule.startswith("statespace"))
    bars = named
    if not bars and wanted:
        allowed = _consumers_allow(wanted)
        every = tuple((symbol, venue) for venue in _wanted() for symbol in desks.symbols(venue))
        # **Fold what something can actually trade.** With no allowlist to
        # consult this folded every desk symbol, and on 2026-11-09 that meant
        # a reading published for `australia 200` which `statespace-surprise`
        # is not permitted to trade: every desk declined it as `unwanted`, so
        # the signal was computed, published and discarded. The fold is not
        # free - it is a Kalman update per feed per bar - and an unactionable
        # proposal is worse than none, because it reads on the bus exactly
        # like one that was refused on its merits.
        #
        # An empty intersection falls back to everything rather than folding
        # nothing: a rule whose allowlist does not overlap the deployed
        # symbols is a misconfiguration to be seen, and a silent empty fold is
        # how `statespace-surprise` sat inert for days with the node healthy.
        from ..strategies.sizes import feed_of_symbol

        keep = tuple((s, v) for s, v in every if feed_of_symbol(s) in allowed)
        used = keep if (keep and allowed) else every
        # **Every interval the desks trade, not the first.** The fold is keyed
        # by feed *and* interval, so a 4h desk reading a 15m proposal is not a
        # slower view of the same state - it is a different estimate, and with
        # only `intervals()[0]` folded it would be subscribed to a topic
        # nothing published for its clock.
        # **Per clock, the symbols that clock actually trades.** `5m` is scoped
        # by `TRADING_SYMBOLS_5M` because a 5m desk costs three units against
        # the ceiling, so folding 5m for a feed that has no 5m desk would be a
        # Kalman update per bar whose reading nothing can act on - the
        # `australia 200` failure again, one clock down.
        # **And only the clocks a consuming rule still runs on.** A rule can be
        # scoped off one clock - `five-minute-surprise-is-a-different-rule` is
        # why `statespace-surprise` is kept off 5m - and folding an interval
        # whose only consumer no longer trades it is a Kalman update per bar
        # producing a reading nothing can act on. That is the `australia 200`
        # failure a second time: computed, published, and declined by every
        # desk as `unwanted`.
        clocks = tuple(
            interval
            for interval in desks.intervals()
            if any(rule in desks.rules_for(interval) for rule in wanted)
        )
        bars = tuple(
            str(desks.bar_type(symbol, venue, interval))
            for symbol, venue in used
            for interval in clocks
            if symbol in desks.symbols_for(venue, interval)
        )
        if bars:
            log.warning(
                "STATESPACE_BARS is unset and %s consume statespace.proposals, so "
                "the fold is built on %d of the desks' %d bar type(s) - the feeds "
                "those rules allow%s. Nothing else publishes that topic: without "
                "it those desks cannot trade.",
                "/".join(wanted),
                len(bars),
                # Both counts over bar *types*, so the ratio means what it
                # says. `every` is symbol-venue pairs, so narrowing 30 feeds
                # to 8 on four intervals is "32 of 120" and not "32 of 30".
                len(every) * max(1, len(clocks)),
                "" if used is keep else " (no overlap, so all of them)",
            )
    if not bars:
        return []
    return [
        StatespaceActor(
            StatespaceConfig(
                bar_types=bars,
                indicators=symbol_names(os.environ.get("STATESPACE_INDICATORS")),
            )
        )
    ]


def _consumers_allow(rules: tuple[str, ...]) -> frozenset[str]:
    """The union of the feed allowlists of the rules that consume a proposal.

    Read off the strategy classes rather than restated here, for the reason
    `leaves` exists: the allowlist is a trading decision that lives with the
    rule, and a second copy in the node is a copy that goes stale. Every entry
    of a rule is consulted, because a deploy may run `resting` or `arrival`
    rather than `edge` and they need not agree.

    A rule with no `feeds` constrains nothing and contributes nothing, which
    is why the caller treats an empty union as "no allowlist to apply".
    """
    from ..strategies import leaves

    allowed: set[str] = set()
    for rule in rules:
        for entry in ("edge", "resting", "arrival"):
            try:
                cls = leaves.leaf(rule, entry)
            except Exception:  # a rule need not offer every entry
                continue
            feeds = getattr(getattr(cls, "profile", None), "feeds", None)
            if feeds:
                allowed.update(str(f).lower() for f in feeds)
    return frozenset(allowed)


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
