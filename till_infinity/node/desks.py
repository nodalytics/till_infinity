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

`TRADING_EXITS` is the second, and it is **empty by default on purpose**: each
rule declares its own exit in `strategies/leaves.py`, because how long to hold
and whether a stop trails are statements about the thesis rather than about the
deploy. See `exits` below for the one case the override is for.

## What a desk is, and where that is written down

A desk is a **(decision, exit, entry, instrument)**, and the first three are
composed into one class in `strategies/leaves.py`. This file builds those
classes; it does not know how they are put together.

It used to build the bare entries - `EdgeEntry`, `RestingEntry`,
`ArrivalEntry` - with no decision mixin in front of them. `Desk.decide` raises
by design, so **every desk this node registered raised `NotImplementedError`
on the first proposal it was handed**: a node that came up, tagged itself,
passed its health check and could not judge a signal. Fixed on 2026-11-01.

That fix changes every `strategy_id`, from `EdgeEntry-EURUSD-E270` to
`SurpriseEdge-EURUSD-E270`, and `_tag` says at length why a changing id is a
hazard - Nautilus matches an external order back to a strategy by it, so a
renamed desk orphans whatever the previous run left open. It is safe here for
exactly one reason, and the reason is the bug: a desk that raised before it
could place has nothing open to orphan.
"""

from __future__ import annotations

import os
import re
import zlib

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ImportableActorConfig, ImportableStrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from till_infinity.adapters.mt5 import MT5
from till_infinity.strategies.basket import BasketConfig, BasketExit
from till_infinity.strategies.leaves import ENTRIES, EXITS, RULES, leaf

from . import sizing

#: Re-exported so an operator greps one name. The registries live in
#: `strategies/leaves.py`, because what a desk *is* - which decision, which
#: exit, which entry - is a question about `strategies` and not about a node.
__all__ = ["ENTRIES", "EXITS", "RULES"]

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
    """The decision rules to run. `TRADING_STRATEGIES`.

    Unknown names raise, for the same reason `entries` does: a typo that
    silently runs nothing is a node that reports up and trades nothing, which
    is on record from three deploys that were built, tagged, health-checked and
    ran none of the code they claimed.
    """
    asked = _names(os.environ.get("TRADING_STRATEGIES")) or ("statespace-surprise",)
    unknown = [name for name in asked if name not in RULES]
    if unknown:
        raise ValueError(
            f"TRADING_STRATEGIES names {', '.join(unknown)}, which is not a "
            f"decision rule. Known: {', '.join(RULES)}."
        )
    return asked


def exits() -> str:
    """The exit mechanism to override every rule's own with. `TRADING_EXITS`.

    Empty by default, meaning **each rule keeps the exit it declared** - the
    exit is a statement about the thesis, so `strategies/leaves.py` is where it
    is chosen rather than a deploy.

    The override exists for one real case. `manage.py` records three things
    that can move a stop on this desk - the MT5 bridge's own twenty-second
    trailing handler, Nautilus's native trailing order, and `advance` - and
    exactly one may, because two on different clocks give whichever wrote last.
    A deploy that cannot switch the bridge's handler off says
    `TRADING_EXITS=venue` and gets the stop left where the venue holds it.
    """
    asked = _names(os.environ.get("TRADING_EXITS"))
    if not asked:
        return ""
    if len(asked) > 1 or asked[0] not in EXITS:
        raise ValueError(
            f"TRADING_EXITS={os.environ.get('TRADING_EXITS')!r} names "
            f"{len(asked)} mechanism(s). It takes exactly one of "
            f"{', '.join(sorted(EXITS))}, and it replaces every rule's own."
        )
    return asked[0]


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


#: The units in `SPECS`, which are the ones a venue can publish.
TIME_UNITS: frozenset[str] = frozenset(spec.split("-")[1] for spec in SPECS.values())

#: Activity clocks Nautilus will build, by the suffix a deploy writes:
#: `TRADING_INTERVALS=500tick` is a bar every 500 ticks.
CLOCKS: dict[str, str] = {"tick": "TICK"}

#: Activity clocks Nautilus will build and **this venue cannot feed**.
#:
#: Nautilus aggregates `VOLUME` and `VALUE` bars, and they are the clocks this
#: desk's own measurements favour - volume time absorbs 76% of what the Q clock
#: does, and still pays on top of it. They are refused anyway, because the
#: measurement was made on the lab's cached data and the live feed has no sizes
#: to build them from: `adapters/mt5/data.py` records that an MT5 tick's trade
#: fields read **0 or a constant 5000**, which is why it publishes a `QuoteTick`
#: with a placeholder size and never a `TradeTick`.
#:
#: So a `VOLUME` bar of 500 here would be a 500-tick bar with a scale factor,
#: carrying the name of a clock that was measured somewhere else. That is worse
#: than not having it: the bars would arrive, the fold would run, and the result
#: would be read as the measured clock.
UNFED: dict[str, str] = {"vol": "VOLUME", "value": "VALUE"}

#: How the bars are built. `TRADING_BAR_SOURCE`, `external` by default.
SOURCES: tuple[str, ...] = ("external", "internal")


def spec_for(interval: str) -> str:
    """Nautilus's bar specification for the name a deploy writes.

    Either one of `SPECS`' seven time clocks, or `<count><clock>` for an
    activity clock - `500tick`. A count is accepted rather than tabulated, for
    the reason `statespace._seconds` gives about `3-MINUTE`: a step nobody has
    used yet should not need an edit here.
    """
    name = interval.strip().lower()
    found = SPECS.get(name)
    if found is not None:
        return found

    match = re.fullmatch(r"(\d+)(tick|vol|value)", name)
    if match is None:
        raise ValueError(
            f"{interval!r} is not an interval this node can subscribe to. "
            f"Known: {', '.join(SPECS)}, or a count and a clock - "
            f"{', '.join(f'500{clock}' for clock in CLOCKS)}."
        )
    count, clock = match.groups()
    if clock in UNFED:
        raise ValueError(
            f"{interval!r} asks for {UNFED[clock]} bars, which Nautilus will "
            f"build and this venue cannot feed: an MT5 tick's trade fields read "
            f"0 or a constant 5000, so there is no size to aggregate and a "
            f"{UNFED[clock]} bar would be a {count}-tick bar with a scale "
            f"factor. Use {count}tick, or a venue that publishes trade ticks."
        )
    return f"{count}-{CLOCKS[clock]}"


def source() -> str:
    """Whether Nautilus builds the bars or the venue does. `TRADING_BAR_SOURCE`."""
    asked = (os.environ.get("TRADING_BAR_SOURCE") or "external").strip().lower()
    if asked not in SOURCES:
        raise ValueError(
            f"TRADING_BAR_SOURCE={asked!r} is not a bar source. One of: {', '.join(SOURCES)}."
        )
    return asked


def bar_type(symbol: str, venue: str, interval: str, *, aggregate: str | None = None) -> BarType:
    """The bar type a desk subscribes to, and who aggregates it.

    **`EXTERNAL` is still the default, and its old reason is now only half
    true.** It used to read: the venue aggregates, and an `INTERNAL` bar type
    would have Nautilus build bars from a *sampled* tick stream, which MT5's
    is. The EA changed that for part of the book - `MT5/ea/TillTickFeed.mq5`
    pushes from `OnTick`, which fires for every tick the terminal sees - but
    `OnTick` only fires for the symbol its chart is on, so the stream is
    complete where an EA is attached and still a 0.25s poll everywhere else.
    That is a per-feed property, so it is a switch and not a new default: a
    deploy that knows its feed is pushed says `TRADING_BAR_SOURCE=internal`.

    **An internal bar type is `MID`, never `LAST`, and this is the detail that
    would make the whole thing silently inert.** Checked in Nautilus's
    `data/engine.pyx`: `_subscribe_bar_aggregator` subscribes to **trade
    ticks** when an internally aggregated bar type's price type is `LAST`, and
    to quote ticks for anything else. The MT5 adapter publishes `QuoteTick`
    and never a `TradeTick`, so `LAST-INTERNAL` would subscribe to a stream
    nothing produces: no bars, no error, a desk that is subscribed and inert.
    `MID` is therefore chosen here rather than left to configuration. A venue
    that does publish trade ticks would want `LAST`, and that belongs with
    that venue's kind in `node/venues.py` when one has an adapter.

    An activity clock forces internal whatever the setting says, because no
    venue publishes one. That cannot surprise a deploy: nothing but this
    function can produce an activity clock in the first place.
    """
    spec = spec_for(interval)
    chosen = aggregate or source()
    if chosen not in SOURCES:
        raise ValueError(f"{chosen!r} is not a bar source. One of: {', '.join(SOURCES)}.")
    if spec.split("-")[1] not in TIME_UNITS:
        chosen = "internal"
    if chosen == "internal":
        return BarType.from_str(f"{symbol}.{venue}-{spec}-MID-INTERNAL")
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
    chosen = exits()
    built: list[Strategy] = []
    for rule, entry, symbol in taken:
        # **The composed leaf, not the bare entry.** This built `EdgeEntry`
        # itself until 2026-11-01, with no decision mixin in front of it -
        # and `Desk.decide` raises by design, so every desk this node
        # registered raised `NotImplementedError` on the first proposal it was
        # handed. The leaves existed, were tested, and were built by nothing.
        strategy = leaf(rule, entry, chosen)
        _, config = ENTRIES[entry]
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


def strategy_name(config: ImportableStrategyConfig) -> str:
    """The `StrategyId` Nautilus will assign this config, as a string.

    **The join between a measurement and a promotion.** `LadderActor` counts
    a candidate's episodes with `Cache.positions_closed(strategy_id=...)`, so
    a candidate delivered under any other name is one the loop can never find
    a sample for: held for want of episodes while the strategy it names
    trades beside it.

    Derived from the importable config, not from `(rule, entry, symbol)`, so
    the name cannot disagree with the one the kernel assigns. Nautilus
    composes it from the class name and the order id tag; a test holds that
    against a real strategy's own `id` rather than against this docstring.
    """
    leaf_class = config.strategy_path.rsplit(":", 1)[-1]
    tag = (config.config or {}).get("order_id_tag", "")
    return f"{leaf_class}-{tag}" if tag else leaf_class


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
    chosen = exits()
    out: list[ImportableStrategyConfig] = []
    for rule, entry, symbol in taken:
        strategy = leaf(rule, entry, chosen)
        _, config = ENTRIES[entry]
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
    """The actors, as importable configs - **including statespace.**

    It was `BasketExit` alone, and that made the backtest path incapable of
    running three of the four decision rules. `statespace-surprise`, `-long`
    and `-short` all consume `statespace.proposals`, `StatespaceActor` is the
    only producer of it, and nothing registered that actor for a backtest. So
    a sweep over those rules completed, reported no orders and raised nothing:
    a consumer with no producer, where both sides look healthy. That exact
    shape has now hidden this topic three times.

    It is the failure the whole port argues against - the thing that measures
    and the thing that trades not being the same thing - so the condition is
    `STATESPACE_BARS`, read the same way `live._actors` reads it, and the
    bar types default to the desks' own interval on this venue's symbols
    rather than being left unset. An actor subscribed to nothing is a fold
    that never runs pretending to be a model that does, which is why the live
    node omits it when the variable is empty; here the symbols are known, so
    the sensible default is the bars the desks already subscribe to.
    """
    from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig

    out = [
        ImportableActorConfig(
            actor_path=f"{BasketExit.__module__}:{BasketExit.__name__}",
            config_path=f"{BasketConfig.__module__}:{BasketConfig.__name__}",
            config={"venue": venue},
        )
    ]
    named = _names(os.environ.get("STATESPACE_BARS"))
    interval = intervals()[0]
    bars = named or tuple(str(bar_type(symbol, venue, interval)) for symbol in symbols(venue))
    if bars:
        out.append(
            ImportableActorConfig(
                actor_path=f"{StatespaceActor.__module__}:{StatespaceActor.__name__}",
                config_path=f"{StatespaceConfig.__module__}:{StatespaceConfig.__name__}",
                config={
                    "bar_types": list(bars),
                    "indicators": list(_names(os.environ.get("STATESPACE_INDICATORS"))),
                },
            )
        )
    return out
