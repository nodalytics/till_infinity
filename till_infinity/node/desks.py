"""Which strategies and actors a node runs, from the environment.

Shared by the live node and the backtest node, so the two cannot drift: a
backtest that built a different set from production would be measuring a desk
that does not exist.

## One strategy per instrument, deliberately

`DeskConfig` names a single `instrument_id`, so the unit is
**(rule, entry, instrument)**. That is the point rather than an accident:
Nautilus puts a framework-assigned `strategy_id` on every order, fill and
position, so per-instrument strategies make "which rule took this, on what,
through which mechanism" a fact the engine carries. `Trader` answered the same
question with a broker magic number, and `DEFAULT_MAGIC` being off by one
relabelled every strategy as its neighbour.

It also multiplies: two rules on three mechanisms over twenty symbols is a
hundred and twenty strategies. So the set is **bounded by the machine**, not by
a number in a config file - `node/sizing.py` already derives that for the
pipeline, and the same argument applies here. A research job silently starved
the service on tis, which has two cores; a node that builds a hundred and
twenty strategies on the same box is the same mistake with a different name.

## The vocabulary is the one the desk already uses

`TRADING_STRATEGIES`, `TRADING_SYMBOLS`, `TRADING_INTERVALS` and
`STATESPACE_FEEDS` keep their meanings. A deploy should not have to learn a new
vocabulary at the same time as a new engine, and the names are what the
operator already greps for.

`TRADING_ENTRIES` is the one addition, naming the mechanisms: `edge`,
`resting`, `arrival`. It defaults to `edge` alone, because that is the one that
places at market and needs nothing from the venue beyond an order - the other
two depend on a venue minimum and on bars respectively, and a default that
quietly needs more than the simplest case is a default that fails on the
narrowest venue.
"""

from __future__ import annotations

import os
import zlib

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ImportableActorConfig, ImportableStrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from till_infinity.adapters.mt5 import MT5
from till_infinity.strategies.basket import BasketConfig, BasketExit
from till_infinity.strategies.entries import (
    ArrivalEntry,
    ArrivalEntryConfig,
    EdgeEntry,
    EdgeEntryConfig,
    RestingEntry,
    RestingEntryConfig,
)

from . import sizing

#: The entry mechanisms, by the name an operator writes.
ENTRIES: dict[str, tuple[type[Strategy], type]] = {
    "edge": (EdgeEntry, EdgeEntryConfig),
    "resting": (RestingEntry, RestingEntryConfig),
    "arrival": (ArrivalEntry, ArrivalEntryConfig),
}

#: Strategies per core, when nothing says otherwise. Each one holds a window
#: of bars and a handful of indicators, so the cost is memory and a fold per
#: bar rather than a thread - but a node that cannot keep up with its feed is
#: a node whose quotes arrive late, and late quotes are the one input every
#: gate here trusts.
PER_CORE = 8


def _names(value: str | None) -> tuple[str, ...]:
    """A list of names, empty entries dropped. **Commas win over spaces.**

    It used to split on both at once - `value.replace(",", " ").split()` -
    which silently cannot express a broker symbol containing a space. Deriv's
    synthetics all do: `TRADING_SYMBOLS="Volatility 75 Index"` became the
    three symbols `Volatility`, `75` and `Index`, so one synthetic produced
    three desks on instruments no venue lists. Nothing raised - `Symbol("75")`
    is a valid symbol and the instrument simply never resolves - so the node
    came up, registered three desks and traded none of them.

    The rule is therefore: **a comma anywhere makes commas the only
    separator**, which is what `utils.env.names` already does and what
    `PRICES_BROKER_SYMBOLS` is written with. Whitespace still works where
    there is no comma, because that is how every existing deploy and test
    writes `EURUSD GBPUSD`. A single spaced name needs a trailing comma -
    `"Volatility 75 Index,"` - which is also what a hand-edited env file
    tends to look like anyway.
    """
    if not value:
        return ()
    if "," in value:
        return tuple(part.strip() for part in value.split(",") if part.strip())
    found = tuple(part for part in value.split() if part)
    # **Refuse the shape that used to pass silently.** No broker lists a
    # symbol called `75`, so a bare number among whitespace-split parts means
    # a name was torn apart - `Volatility 75 Index`, `Boom 1000 Index`,
    # `Crash 500 Index`, `Jump 25 Index`. Raising here costs a deploy a clear
    # error; the alternative cost three desks quoting instruments that do not
    # exist, with nothing to say so.
    #
    # It does not catch every case: `Step Index` has no number in it, and
    # without a comma it still splits into two. The comma rule is the one that
    # always works, and this guard is for the spelling somebody will reach for
    # first.
    if any(part.isdigit() for part in found):
        raise ValueError(
            f"TRADING_SYMBOLS={value!r} splits on whitespace into {list(found)}, "
            f"which contains a bare number - so a symbol name with a space in it "
            f"has been torn apart. Separate the names with commas: "
            f'"Volatility 75 Index,Boom 1000 Index", or a single one with a '
            f'trailing comma: "Volatility 75 Index,".'
        )
    return found


def rules() -> tuple[str, ...]:
    """The decision rules to run. `TRADING_STRATEGIES`."""
    return _names(os.environ.get("TRADING_STRATEGIES")) or ("statespace-surprise",)


def entries() -> tuple[str, ...]:
    """The entry mechanisms to run. `TRADING_ENTRIES`.

    Unknown names raise rather than being skipped: a typo that silently runs
    nothing is a node that reports up and trades nothing, which is the failure
    this desk has on record from three deploys that were built, tagged,
    health-checked and ran none of the code they claimed.
    """
    asked = _names(os.environ.get("TRADING_ENTRIES")) or ("edge",)
    unknown = [name for name in asked if name not in ENTRIES]
    if unknown:
        raise ValueError(
            f"TRADING_ENTRIES names {', '.join(unknown)}, which is not a "
            f"mechanism. Known: {', '.join(sorted(ENTRIES))}."
        )
    return asked


def venues() -> tuple[str, ...]:
    """The venues this node trades. `TRADING_VENUES`, default one.

    **Several venues is one node, not several.** Nautilus keys its data and
    execution clients by name and runs them side by side in one kernel, with
    one cache and one portfolio - which is what makes exposure across venues
    answerable at all. Running a node per venue would put each one's positions
    out of the other's sight, and `risk/exposure.py` exists precisely because
    what is at risk is a question about an account rather than about a ticket.

    Only `MT5` has an adapter today, so more than one venue currently means
    more than one MT5 account - a demo beside a live one, or two brokers both
    on MT5, which is an ordinary arrangement rather than a hypothetical.
    """
    # The adapter's own constant, so the default venue name has one home. A
    # literal here and a literal there is how a client keyed `MT5` comes to be
    # asked for by a desk keyed `mt5`, and a client that is never found is a
    # node that subscribes to nothing.
    return _names(os.environ.get("TRADING_VENUES")) or (MT5,)


def symbols(venue: str | None = None) -> tuple[str, ...]:
    """The instruments to trade. `TRADING_SYMBOLS`, or per venue.

    `TRADING_SYMBOLS_<VENUE>` overrides the shared list for one venue, because
    two venues rarely list the same things: a Deriv account carries the
    synthetics and an ECN account carries the FX crosses, and a shared list
    would have each node asking its venue for instruments it does not have.
    Absent, the shared list applies - which is what a single-venue deploy
    wants and what every existing one already sets.
    """
    if venue:
        private = _names(os.environ.get(f"TRADING_SYMBOLS_{venue.upper()}"))
        if private:
            return private
    return _names(os.environ.get("TRADING_SYMBOLS"))


def intervals() -> tuple[str, ...]:
    """The timeframes. `TRADING_INTERVALS`, first one used for the bar type."""
    return _names(os.environ.get("TRADING_INTERVALS")) or ("15m",)


#: How an interval is written as a Nautilus bar specification.
SPECS: dict[str, str] = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "30m": "30-MINUTE",
    "1h": "1-HOUR",
    "4h": "4-HOUR",
    "1d": "1-DAY",
}


def bar_type(symbol: str, venue: str, interval: str) -> BarType:
    """The bar type a desk subscribes to.

    `EXTERNAL` because the venue aggregates: an `INTERNAL` bar type would have
    Nautilus build bars from ticks, and on a venue whose tick stream is
    *sampled* - which MT5's is - those bars would be built from a sample and
    would not match the venue's own.
    """
    spec = SPECS.get(interval)
    if spec is None:
        raise ValueError(
            f"{interval!r} is not an interval this node can subscribe to. "
            f"Known: {', '.join(SPECS)}."
        )
    return BarType.from_str(f"{symbol}.{venue}-{spec}-LAST-EXTERNAL")


def ceiling(budget: sizing.Budget | None = None) -> int:
    """How many strategies this machine will carry.

    Zero on the trading host for a *backtest*, and never zero here: a live node
    with no strategies is a node that reports up and trades nothing. So this
    floors at one and says so in the log when it has had to clip.
    """
    # **`cores_seen`, because `Budget` has no `cores`.** The old expression
    # read `.cores` off the budget when one was passed, so `ceiling(budget)`
    # raised `AttributeError` - and nothing had ever passed one, so the branch
    # was dead until `build_all` needed to spend one budget across venues.
    #
    # `cores_seen` and not `workers`: `workers` reserves a core for the
    # service and is the more conservative number - 7 against 8 on this box,
    # 56 desks against 64 - but it is a different ceiling from the one every
    # existing deploy runs, and changing that silently is not a bug fix. Worth
    # revisiting against `tis-research-jobs-starve-the-service`, where tis has
    # two cores and a research job starving the desk is a measured outcome.
    cores = (budget or sizing.measure()).cores_seen if budget else sizing.cores()
    return max(1, cores * PER_CORE)


def build(
    venue: str,
    *,
    budget: sizing.Budget | None = None,
    limit: int | None = None,
    qualify: bool = False,
) -> tuple[list[Strategy], list[str]]:
    """Every (rule, entry, instrument) this node runs, and what it clipped.

    Returns the strategies and the names of anything dropped for the ceiling,
    so the caller can say it out loud. **A set silently smaller than the one
    asked for is the shape of bug this desk has paid for repeatedly** - a
    min-events guard once dropped 141 of 146 feeds and made 0.9 sigma look like
    4.8 - so the drop is returned rather than logged here.
    """
    taken, clipped = _wanted(venue=venue, budget=budget, limit=limit)
    interval = intervals()[0]
    built: list[Strategy] = []
    for rule, entry, symbol in taken:
        strategy, config = ENTRIES[entry]
        built.append(
            strategy(
                config(
                    # **A distinct tag per desk, or they collide.** Left
                    # unset, every strategy is `EdgeEntry-None` and they share
                    # an order-id tag, so Nautilus generates colliding client
                    # order ids and the `strategy_id` that was the whole
                    # argument for the carve-up names several desks at once -
                    # the magic-number bug reproduced exactly.
                    #
                    # Only the tag is set: Nautilus derives `strategy_id` as
                    # `ClassName-tag`, so passing both gives the tag twice.
                    order_id_tag=_tag(rule, entry, symbol, venue if qualify else None),
                    instrument_id=InstrumentId.from_str(f"{symbol}.{venue}"),
                    bar_type=bar_type(symbol, venue, interval),
                    rule=rule,
                )
            )
        )
    return built, [f"{r}/{e}/{s}" for r, e, s in clipped]


def _wanted(
    *,
    venue: str | None = None,
    budget: sizing.Budget | None = None,
    limit: int | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """The (rule, entry, instrument) triples this machine will carry, and the
    ones it clipped.

    Shared by `build` and `importable` so the live node and a backtest cannot
    name different desks - see `importable` for why that matters more than it
    looks.
    """
    wanted = [
        (rule, entry, symbol)
        for symbol in symbols(venue)
        for rule in rules()
        for entry in entries()
    ]
    cap = ceiling(budget) if limit is None else limit
    return wanted[:cap], wanted[cap:]


def _tag(rule: str, entry: str, symbol: str, venue: str | None = None) -> str:
    """A short, stable, unique tag for one desk.

    Stable so that a restart reclaims its own orders: Nautilus matches an
    external order to a strategy by this tag, so a tag that changed between
    runs would orphan everything the previous run left open. Hence derived from
    the three names rather than from a counter or a uuid - a counter renumbers
    when the config changes, which is the same positional bug `DEFAULT_MAGIC`
    had.

    **`crc32` and not `hash`.** The first version used `abs(hash(rule))`, and
    Python randomises `hash` of a `str` per process unless `PYTHONHASHSEED` is
    fixed - three runs gave 619, 480 and 849 for the same rule. A tag derived
    from it changes on every restart, which orphans every open order: the exact
    failure the paragraph above says must not happen, written two lines under
    it. `crc32` is a checksum rather than a hash and is stable by definition.

    **`venue` is appended only when it is needed**, and that asymmetry is
    deliberate. One symbol on two venues is two desks, and they collided:
    Nautilus refused the second with `Already registered a strategy with ID
    EdgeEntry-EURUSD-E270`, because the tag named the symbol and not where it
    traded. Appending the venue unconditionally would be tidier and would
    change every existing desk's `strategy_id` once - which is precisely what
    the paragraph above says must not happen, since on the next restart
    Nautilus would no longer recognise its own open orders.

    So a single-venue deploy keeps byte-identical tags and a multi-venue one
    qualifies them. The condition is the deploy's own config rather than
    anything that varies at runtime, so it is stable across restarts, which is
    the property that actually matters.
    """
    short = f"{symbol}-{entry[:1].upper()}{zlib.crc32(rule.encode()) % 997:03d}"
    return f"{short}-{venue}" if venue else short


def build_all(
    names: tuple[str, ...] | None = None,
    *,
    budget: sizing.Budget | None = None,
) -> tuple[list[Strategy], list[str]]:
    """Every desk on every venue, sharing one ceiling.

    **The ceiling is a property of the machine, not of a venue.** Built per
    venue it would multiply: two venues at `PER_CORE` x cores each is twice
    the fold on the same two cores, and `tis-research-jobs-starve-the-service`
    is what that costs - a node that cannot keep up with its feed has late
    quotes, and a late quote is the one input every gate trusts. So the budget
    is computed once and spent down across venues in order.

    The venues are taken in the order they are named, so a deploy that cares
    which one survives a clip says so by ordering `TRADING_VENUES` - and the
    clipped names are returned carrying their venue, because a set silently
    smaller than the one asked for is the shape of bug this desk has paid for
    repeatedly.
    """
    budget = budget or sizing.measure()
    wanted = names or venues()
    left = ceiling(budget)
    built: list[Strategy] = []
    dropped: list[str] = []
    for venue in wanted:
        # Qualified by venue only where there is more than one - see `_tag`.
        some, clipped = build(venue, budget=budget, limit=max(0, left), qualify=len(wanted) > 1)
        built.extend(some)
        dropped.extend(f"{venue}:{name}" for name in clipped)
        left -= len(some)
    return built, dropped


def actors_all(names: tuple[str, ...] | None = None) -> list[Actor]:
    """The per-venue actors, for every venue.

    `BasketExit` is per venue because a basket is judged against one venue's
    quotes, and `judge(positions, price_of)` needs a pricer that can price
    every position it is given.
    """
    found: list[Actor] = []
    for venue in names or venues():
        found.extend(actors(venue))
    return found


def actors(venue: str) -> list[Actor]:
    """The actors a node runs beside its strategies.

    `BasketExit` is here rather than among the strategies because its whole
    subject is *other strategies'* positions - see `strategies/basket.py`.
    `StatespaceActor` is added by the caller where it is configured, because it
    needs its own bar types and a node may run it without trading.
    """
    # **`component_id` per venue, or the second one is refused.** Nautilus
    # requires actor ids to be unique in a trader, so two venues both adding
    # a `BasketExit` raise `Already registered an actor with ID BasketExit`.
    # Found by building a two-venue node rather than by reading, which is the
    # argument for building one.
    return [BasketExit(BasketConfig(venue=venue, component_id=f"BasketExit-{venue}"))]


def importable(
    venue: str,
    *,
    budget: sizing.Budget | None = None,
    limit: int | None = None,
    qualify: bool = False,
) -> tuple[list[ImportableStrategyConfig], list[str]]:
    """The same desks, as the importable configs a `BacktestNode` takes.

    **The same function would have been two, and they would have drifted.**
    `BacktestRunConfig` is serialisable, so it holds `strategy_path` and a
    config dict rather than an instance - a different shape from what
    `TradingNode.trader.add_strategy` wants. Building the two sets from two
    pieces of code is how a backtest comes to measure a desk that is not the
    one deployed, which is the single failure this whole move is for: an edge
    with good fills and -98%, a 0.6365 that was overlapping touches, a
    directional AUC of 0.79 that collapsed to 0.51 - every one of them the
    thing that measured and the thing that traded not being the same thing.

    So `build` and this share `_wanted`, and a test asserts the two sets name
    the same desks.
    """
    taken, clipped = _wanted(venue=venue, budget=budget, limit=limit)
    interval = intervals()[0]
    out: list[ImportableStrategyConfig] = []
    for rule, entry, symbol in taken:
        strategy, config = ENTRIES[entry]
        out.append(
            ImportableStrategyConfig(
                strategy_path=f"{strategy.__module__}:{strategy.__name__}",
                config_path=f"{config.__module__}:{config.__name__}",
                config={
                    "order_id_tag": _tag(rule, entry, symbol, venue if qualify else None),
                    "instrument_id": f"{symbol}.{venue}",
                    "bar_type": str(bar_type(symbol, venue, interval)),
                    "rule": rule,
                },
            )
        )
    return out, [f"{r}/{e}/{s}" for r, e, s in clipped]


def importable_actors(venue: str) -> list[ImportableActorConfig]:
    """The actors, as importable configs."""
    return [
        ImportableActorConfig(
            actor_path=f"{BasketExit.__module__}:{BasketExit.__name__}",
            config_path=f"{BasketConfig.__module__}:{BasketConfig.__name__}",
            config={"venue": venue},
        )
    ]
