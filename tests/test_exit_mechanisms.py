"""The exit as a composable mechanism, and the asymmetries it has to allow.

`surprise.py` claimed that "a mixin with no base lets any decision compose with
any entry, which is what entries and exits are asymmetric means in code", and
the claim held for exactly half of it. The decision composed; the exit did not
exist as a thing to compose. `EdgeEntry` and `ArrivalEntry` submitted a bracket
inside `place`, `RestingEntry` submitted nothing at all, and `Exits`,
`manage.advance`, `manage.partial` and `Profile.protection` had **no caller in
`till_infinity/`** - so every decision got the same exit whatever its thesis,
and no decision had any way to state one.

Three failures are measured here rather than reasoned about, because each one
looked like somebody else's problem from inside a unit test of the part that
contained it:

* a resting entry that filled was an **unprotected position** - its `place`
  leaves a bare limit and its `on_order_filled` only forgets the wait;
* `BasketExit` logged "closing all N position(s)", counted them closed and
  **closed nothing**, because it publishes on `alerts` and the only subscriber
  was the Telegram notifier;
* nothing differed by **side**, on a desk whose own `DEFAULT_STOP_OVERSHOOT`
  records that a boom's sell and a crash's buy are not the same trade as their
  opposites.

The composition tests build every pairing and put a signal through it, because
reading an `issubclass` tells you a class exists and not that a proposal
reaches a venue through it - which is how nine working leaves came to be built
by nothing at all.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig, BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.domain.models import Intent, Side
from till_infinity.strategies import leaves
from till_infinity.strategies.entries import (
    ArrivalEntry,
    ArrivalEntryConfig,
    EdgeEntry,
    EdgeEntryConfig,
    RestingEntry,
    RestingEntryConfig,
)
from till_infinity.strategies.exits import (
    ExitMechanism,
    ManagedExit,
    Protection,
    VenueExit,
    protection_for,
)
from till_infinity.strategies.surprise import Surprise, SurpriseEdge, SurpriseResting
from till_infinity.utils.topics import COMMANDS, PROPOSALS

VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
BAR_TYPE = BarType.from_str(f"{EURUSD.id}-1-HOUR-LAST-EXTERNAL")
SECOND = 1_000_000_000

#: Quotes before the proposal, so the feed is warm and the proposal is not
#: racing the first tick into the cache - `_undealable` refuses on a missing
#: quote, and a test that published first would assert that gate instead.
WARM = 3

ENTRIES = {
    "edge": (EdgeEntry, EdgeEntryConfig),
    "resting": (RestingEntry, RestingEntryConfig),
    "arrival": (ArrivalEntry, ArrivalEntryConfig),
}
#: `StatespaceLong`/`StatespaceShort` and not `deciding.LongSide` itself: the
#: bare mixin's profile is a `SideProfile`, which has no `multipliers`, so a
#: leaf built on it decides correctly and then raises on the way to a size.
DECISIONS = {
    "surprise": Surprise,
    "long": leaves.StatespaceLong,
    "short": leaves.StatespaceShort,
}
EXITS = {"managed": ManagedExit, "venue": VenueExit}


# ------------------------------------------------------------------ the harness


class PitchConfig(ActorConfig, frozen=True):
    instrument_id: InstrumentId
    surprise: float = 4.2
    direction: int = 1
    after: int = WARM


class Pitcher(Actor):
    """One statespace proposal on the real topic, through the real bus.

    `StatespaceActor` is not used on purpose: it would bring its own folds and
    thresholds, and a failure in those would arrive looking like a failure of
    this chain. Copied from `test_first_trade.py`, where the argument is made
    at length.
    """

    def __init__(self, config: PitchConfig) -> None:
        super().__init__(config)
        self._seen = 0
        self.sent = 0

    def on_start(self) -> None:
        self.subscribe_quote_ticks(self.config.instrument_id)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._seen += 1
        if self._seen != self.config.after:
            return
        self.sent += 1
        self.msgbus.publish(
            PROPOSALS,
            {
                "feed": "eurusd",
                "shape": "statespace",
                "interval": "5m",
                "direction": self.config.direction,
                "features": {
                    "surprise": self.config.surprise,
                    "vol_bps": 10.0,
                    "stop_vol": 2.0,
                    "target_r": 2.0,
                },
            },
        )


class CloserConfig(ActorConfig, frozen=True):
    instrument_id: InstrumentId
    #: Which strategy the close is addressed to. A wrong one is how the
    #: `strategy_id` filter is tested.
    strategy_id: str = ""
    after: int = WARM + 4


class Closer(Actor):
    """`BasketExit`'s close request, published the way `BasketExit` publishes it.

    Not `BasketExit` itself: its own gate is `Guard.basket` over an account's
    floating total, which is tested in `test_exits.py`. What is under test here
    is whether the *request* reaches the position's owner, which is the half
    that reached nobody.
    """

    def __init__(self, config: CloserConfig) -> None:
        super().__init__(config)
        self._seen = 0
        self.sent = 0

    def on_start(self) -> None:
        self.subscribe_quote_ticks(self.config.instrument_id)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._seen += 1
        if self._seen != self.config.after:
            return
        held = self.cache.positions_open()
        if not held:
            return
        position = held[0]
        self.sent += 1
        self.msgbus.publish(
            # `COMMANDS`, as `BasketExit` publishes it: this asks for a close
            # and is not a finding for a person.
            COMMANDS,
            {
                "shape": "basket.close",
                "position_id": str(position.id),
                "strategy_id": self.config.strategy_id or str(position.strategy_id),
                "instrument_id": str(position.instrument_id),
            },
        )


def quotes(
    count: int = 14,
    step: float = 1e-05,
    jump_after: int = 10**9,
    jump: float = 5e-04,
) -> list[QuoteTick]:
    """A quiet feed that may be made to run, at half a point of spread.

    `jump_after` switches to the larger step, which is what gets a trade past a
    break-even threshold inside a short feed: the risk here is 22 points, so a
    one-point drift would need a hundred and ten ticks to reach 1R.

    The callers that want a stop *moved* also want the position still open at
    the end, so they pick a `jump` whose total rise clears 1R - 22 points - and
    stays under the 44-point target. A feed that reaches the target instead
    tests the bracket, which `test_first_trade.py` already does.
    """
    rows = []
    mid = 1.10000
    for i in range(count):
        mid += step if i < jump_after else jump
        rows.append(
            QuoteTick(
                instrument_id=EURUSD.id,
                bid_price=Price(mid - 2.5e-05, 5),
                ask_price=Price(mid + 2.5e-05, 5),
                bid_size=Quantity(1_000_000, 0),
                ask_size=Quantity(1_000_000, 0),
                ts_event=i * SECOND,
                ts_init=i * SECOND,
            )
        )
    return rows


def engine_for(instruments=(EURUSD,), equity: float = 100_000.0) -> BacktestEngine:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(equity, USD)],
    )
    for instrument in instruments:
        engine.add_instrument(instrument)
    return engine


def run(
    build=SurpriseEdge,
    config=EdgeEntryConfig,
    *,
    feed=None,
    actors=(),
    tune=None,
    **pitch,
):
    """One backtest from the quote feed to the venue's fills, for one leaf."""
    engine = engine_for()
    engine.add_data(feed if feed is not None else quotes())
    strategy = build(config(instrument_id=EURUSD.id, bar_type=BAR_TYPE))
    if tune is not None:
        # Before the run, so the exit book is built from the tuned settings -
        # `ExitMechanism.exits` builds it on first use and keeps it.
        tune(strategy.settings)
    engine.add_strategy(strategy)
    pitcher = Pitcher(PitchConfig(instrument_id=EURUSD.id, **pitch))  # type: ignore[arg-type]
    engine.add_actor(pitcher)
    for actor in actors:
        engine.add_actor(actor)
    engine.run()
    return strategy, pitcher


def guards(strategy) -> list:
    """The stop orders this strategy has live at the venue."""
    return [
        order
        for order in strategy.cache.orders(strategy_id=strategy.id)
        if getattr(order, "trigger_price", None) is not None
    ]


# -------------------------------------------------------------- the composition


def test_every_decision_exit_and_entry_pairing_places_a_trade():
    """**Eighteen pairings, built and driven, not read.**

    The property is that the three pieces are independent: any decision, with
    any exit, on any entry. The existing test for it asserted `issubclass` and
    nothing else, and `issubclass` is exactly what was true while `node/desks.py`
    built the bare entry classes and every production desk raised
    `NotImplementedError` on its first proposal.

    So each pairing gets a real engine, a real proposal and a real venue, and
    is asked for the one thing a composed leaf exists to do - take the trade or
    park it, under its own `strategy_id`.
    """
    seen = set()
    for (dname, decision), (xname, exit_), (ename, (entry, config)) in itertools.product(
        DECISIONS.items(), EXITS.items(), ENTRIES.items()
    ):
        leaf = type(f"{dname}{xname}{ename}".title(), (decision, exit_, entry), {})
        strategy, pitcher = run(
            leaf,
            config,
            direction=-1 if dname == "short" else 1,
        )
        where = f"{dname}+{xname}+{ename}"
        assert pitcher.sent == 1, where
        assert strategy.taken == 1, f"{where} judged nothing: {strategy.passed_over}"
        assert strategy.refused == 0, where
        if ename == "arrival":
            # An arrival parks the signal rather than placing it, and the feed
            # here only rises - so what is proven is that the decision reached
            # the mechanism, which is the composition under test.
            assert strategy._payload is None or strategy._trigger > 0.0, where
        else:
            assert strategy.cache.orders(strategy_id=strategy.id), f"{where} placed nothing"
        seen.add(str(strategy.id).rsplit("-", 1)[0])
    assert len(seen) == 18, "each pairing is its own strategy_id, not a flag inside one"


def test_what_the_node_builds_puts_a_proposal_through_to_the_venue(monkeypatch):
    """**The registry, and not a class named in a test.**

    `test_first_trade.py` instantiates `SurpriseEdge` directly, so it proves
    the chain and not the thing that builds the chain - and the thing that
    builds the chain was building `EdgeEntry`, which has no decision at all.
    Two independent faults, one in each half, and neither visible from the
    other's test: the leaf worked and nothing built it, while the builder ran
    and built something that could not judge a signal.

    So this points the end-to-end harness at `desks.build_all()`. It is the
    assertion that would have caught both in one run.
    """
    from till_infinity.node import desks

    monkeypatch.setenv("TRADING_VENUES", "SIM")
    monkeypatch.setenv("TRADING_SYMBOLS", "EUR/USD,")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")
    monkeypatch.setenv("TRADING_STRATEGIES", "statespace-surprise")

    built, dropped = desks.build_all()
    assert len(built) == 1, f"the node built {len(built)} desks, dropped {dropped}"
    strategy = built[0]

    engine = engine_for()
    engine.add_data(quotes())
    engine.add_strategy(strategy)
    pitcher = Pitcher(PitchConfig(instrument_id=EURUSD.id))
    engine.add_actor(pitcher)
    engine.run()

    assert pitcher.sent == 1
    assert strategy.taken == 1, f"the built desk judged nothing: {strategy.passed_over}"
    assert strategy.cache.orders(strategy_id=strategy.id), "the built desk placed nothing"
    assert isinstance(strategy, ExitMechanism), "the built desk has no exit"
    assert strategy.cache.positions_open(strategy_id=strategy.id)


def test_the_exit_sits_in_front_of_the_entry_in_the_bases():
    """Put it behind the entry and it never sees a fill.

    `RestingEntry.on_order_filled` and `EdgeEntry.on_order_filled` do not call
    `super()`, so an exit resolved after them in the MRO is simply skipped - no
    tracking, no stop, no stale clock, and nothing to say so. In front of them
    the exit runs first and hands the event on, which is also what lets it read
    the entry's own `_waiting` before the entry clears it.
    """
    for leaf in leaves.LEAVES.values():
        order = [base.__name__ for base in leaf.__mro__]
        exits = next(i for i, base in enumerate(leaf.__mro__) if issubclass(base, ExitMechanism))
        entry = next(i for i, base in enumerate(leaf.__mro__) if base in ENTRIES_BY_CLASS)
        assert exits < entry, f"{leaf.__name__} resolves its exit after its entry: {order}"


ENTRIES_BY_CLASS = {cls for cls, _ in ENTRIES.values()}


def test_a_decision_does_not_know_which_exit_it_got():
    """The mirror of `Surprise.__mro__ == (Surprise, object)`.

    An exit mixin that subclassed `Strategy`, or that named a decision, would
    fix the pairing in one direction again - and the whole point of three
    independent pieces is that none of them can.
    """
    assert ExitMechanism.__mro__ == (ExitMechanism, object)
    assert not hasattr(ExitMechanism, "decide")
    assert not hasattr(ExitMechanism, "place"), "an exit that placed would shadow the entry's"


# -------------------------------------------------- the exit differs per rule


def test_one_decision_can_hold_its_stop_two_different_ways():
    """**The asymmetry, measured.** One decision, one entry, two exits.

    `ManagedExit` moves the stop to break even once the trade is 1R in front;
    `VenueExit` leaves whatever the venue is holding. Before this there was no
    way to express either choice: `manage.advance` had no caller at all, so
    every trade got the bracket its entry happened to submit and the four
    combinations of break-even and trailing the module docstring asks to be
    compared could not be run even once.
    """

    def on(settings):
        settings.break_even_at = 1.0

    feed = quotes(count=16, jump_after=WARM + 2, jump=3e-04)
    managed, _ = run(SurpriseEdge, feed=feed, tune=on)
    standing, _ = run(leaves.leaf("statespace-surprise", "edge", "venue"), feed=feed, tune=on)

    assert managed.taken == standing.taken == 1
    assert managed.passed_over.get("(exit):advanced") == 1, "the managed stop never moved"
    assert "(exit):advanced" not in standing.passed_over, "the venue's stop was moved anyway"

    moved = guards(managed)[0]
    left = guards(standing)[0]
    assert float(moved.trigger_price) > float(left.trigger_price), (
        "the two exits put the stop in the same place, so the choice was nominal"
    )


def test_the_stop_moves_once_per_improvement_and_not_once_per_quote():
    """`Held.stop` is why. Without it the comparison is against `intent.stop`,
    which never changes - so every quote after the threshold re-proposes the
    same stop and sends the same modify, and a venue answering a modify per
    tick is noise that hides a real rejection."""

    def on(settings):
        settings.break_even_at = 1.0

    # Twelve quotes past the threshold, so a per-quote modify would be obvious.
    managed, _ = run(
        SurpriseEdge, feed=quotes(count=24, jump_after=WARM + 2, jump=1.5e-04), tune=on
    )
    assert managed.passed_over.get("(exit):advanced") == 1
    assert managed.cache.positions_open(strategy_id=managed.id), (
        "the position closed, so the twenty quotes after the move were not seen"
    )


def test_a_rule_whose_thesis_is_duration_is_exempt_from_the_stale_clock():
    """Per rule, not per deployment. The stale rule exists because a level
    touch resolves in eighteen seconds at the median and 84% inside five
    minutes - a premise true of a scalp and false of a swing, at any length of
    clock - so a swing must be able to switch it off rather than scale it."""

    def on(settings):
        settings.stale_after = 2.0

    patient = type("SurprisePatient", (Surprise, ManagedExit, EdgeEntry), {"stale": False})
    quick, _ = run(SurpriseEdge, tune=on)
    slow, _ = run(patient, tune=on)

    assert quick.passed_over.get("(exit):closed") == 1, "the scalp was not closed for going nowhere"
    assert "(exit):closed" not in slow.passed_over, "the swing was closed by a scalp's clock"


def test_a_position_is_only_asked_to_close_once():
    """A close is an order, and the event that clears the book arrives later.

    Without a latch the next quote asks the same question, gets the same answer
    and sends a second closing order - and the bug is **invisible in a
    backtest**, where the fill lands before the next quote. On a live feed it
    is one order per quote until the venue answers. So the close is stubbed
    here, which is the only way to hold the position open across the second
    ask.
    """

    strategy, _ = run(SurpriseEdge)
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]

    # The stale clock is switched on *after* the run, so the position is still
    # open to be asked about. `Exits` holds this same `Settings` object.
    strategy.settings.stale_after = 2.0
    strategy.exits._held.clear()
    strategy.exits.opened(position.id, strategy._intended, when=0.0)
    sent: list[object] = []
    strategy.close_position = sent.append

    for tick in quotes(count=3):
        strategy.on_quote_tick(tick)

    assert len(sent) == 1, f"asked to close {len(sent)} times"
    assert strategy.passed_over.get("(exit):closed") == 1
    assert strategy.exits.held(position.id).closing, "the latch was never set"


def test_a_rule_s_own_hold_is_enforced_and_the_configured_default_is_not():
    """`Intent.hold` is the strategy's and is applied; `Settings.max_hold` is
    1800s by default and is deliberately left out of the exit.

    Folding the global in would put a thirty-minute timeout on every trade this
    desk takes on the quiet authority of a default, and `research/spending.md`
    measured the holds already running short - 50 of 133 closes exited at 5% of
    their planned target because the clock ran out before the geometry could
    resolve.
    """
    from till_infinity.strategies.config import Settings
    from till_infinity.strategies.exits import Exits, Held

    assert Settings().max_hold == 1800.0, "the default this must not apply"
    book = Exits(settings=Settings())
    patient = Held(
        intent=Intent(
            feed="f", symbol="S", side=Side.BUY, volume=1.0, entry=1.0, stop=0.9, target=1.2
        ),
        best=1.0,
        opened=0.0,
    )
    assert book._expired(patient, now=10_000.0) == "", "a global hold was applied"
    asked = replace(patient.intent, hold=60.0)
    assert book._expired(Held(intent=asked, best=1.0, opened=0.0), now=59.0) == ""
    assert book._expired(Held(intent=asked, best=1.0, opened=0.0), now=61.0)


def test_closing_wins_over_banking_and_banking_over_moving_a_stop():
    """The order inside one answer is the design, the way the gate sequence is.

    A position that should come off whole is not also partially banked, and a
    stop moved on a position about to be closed is a modify nobody needed - and
    before `apply` existed each of the three was a separate question with no
    stated order, so a caller had to know one. There was no caller, so nothing
    knew it.
    """
    from till_infinity.strategies.config import Settings
    from till_infinity.strategies.exits import Exits

    plan_for = Intent(
        feed="eurusd",
        symbol="EUR/USD",
        side=Side.BUY,
        volume=1.0,
        entry=1.1000,
        stop=1.0950,
        target=1.1100,
        hold=60.0,
    )
    settings = Settings()
    settings.scale_out_at = 0.5
    settings.break_even_at = 0.5
    book = Exits(settings=settings)
    book.opened("p1", plan_for, when=0.0)

    position = type(
        "P",
        (),
        {"ticket": 1, "side": Side.BUY, "volume": 1.0, "price_open": 1.1000, "stop": 1.0950},
    )()
    spec = type("S", (), {"volume_step": 0.01, "volume_min": 0.01})()

    inside = book.apply("p1", position, spec, now=10.0, vol_bps=10.0)
    assert inside.close == "", "closed a trade that still had time"
    expired = book.apply("p1", position, spec, now=61.0, vol_bps=10.0)
    assert expired.close, "the rule's own hold was not enforced"
    assert expired.take is None, "banked a position being closed"
    assert expired.move is None, "moved the stop on a position being closed"


# --------------------------------------------------------- the exit by side


def test_the_exit_geometry_can_differ_by_side_on_one_feed():
    """**Long and short are not the same trade**, and the exit path has to be
    able to say so.

    The shape is `risk.scaling.overshoot_for`'s, deliberately: a key of
    `boom_500_index.sell` beats `boom_500_index`, because on a jump instrument
    a stop on the spike side can only be gapped over. Nothing in `exits.py` or
    `manage.py` read a per-side policy at all before this - the only
    side-dependence was mechanical (which quote side is the best price, which
    direction is a tighter stop), and a mechanical asymmetry is not a policy.
    """
    sided = (
        ("eurusd.sell", Protection(break_even_at=0.5, stale_exempt=True)),
        ("eurusd", Protection(trail_vol=9.0)),
    )
    assert protection_for(sided, "eurusd", Side.SELL).break_even_at == 0.5
    assert protection_for(sided, "eurusd", Side.BUY).trail_vol == 9.0, "the unqualified row"
    assert protection_for(sided, "gbpusd", Side.SELL) is None, "nothing names this feed"

    # And it reaches the intent, which is where every exit rule reads it.
    leaf = type("SurpriseSided", (Surprise, ManagedExit, EdgeEntry), {"sided": sided})
    strategy = leaf(EdgeEntryConfig(instrument_id=EURUSD.id, bar_type=BAR_TYPE))
    base = Intent(
        feed="eurusd",
        symbol="EUR/USD",
        side=Side.SELL,
        volume=1.0,
        entry=1.1,
        stop=1.11,
        target=1.08,
    )
    short = strategy._sided(base)
    long_ = strategy._sided(replace(base, side=Side.BUY, stop=1.09, target=1.12))
    assert short.break_even_at == 0.5
    assert short.stale_exempt is True
    assert long_.break_even_at == 0.0, "the long took the short's protection"
    assert long_.trail_vol == 9.0


def test_no_shipped_leaf_asserts_a_long_short_difference():
    """**The null, and it is the honest answer.**

    No long/short asymmetry in *exit* behaviour has been measured on this desk.
    The machinery above exists so the first measured one is a single row; until
    there is one, every leaf must resolve both sides identically, or the
    capability has quietly become a claim.

    The measured asymmetry next door is in the *gapping* - `boom_*.sell` and
    `crash_*.buy` at 2.0 in `DEFAULT_STOP_OVERSHOOT` - and turning an overshoot
    multiple into a trail distance is arithmetic nobody has done.
    """
    assert ExitMechanism.sided == (), "the base ships a table"
    base = Intent(
        feed="eurusd",
        symbol="EUR/USD",
        side=Side.BUY,
        volume=1.0,
        entry=1.1,
        stop=1.09,
        target=1.12,
    )
    for name, leaf in leaves.LEAVES.items():
        assert leaf.sided == (), f"{name} ships a per-side table"
        strategy = leaf.__new__(leaf)
        long_ = strategy._sided(base)
        short = strategy._sided(replace(base, side=Side.SELL))
        for field in ("break_even_at", "trail_vol", "trail_levels", "hold", "stale_exempt"):
            assert getattr(long_, field) == getattr(short, field), f"{name} differs on {field}"

    # And the two side profiles the statespace leaves run on agree, which is
    # the same claim one level up - `deciding.py` writes them out separately so
    # that the difference today is visibly zero.
    from till_infinity.statespace.deciding import LongProfile, ShortProfile

    for field in ("break_even_at", "trail_vol", "trail_levels", "hold", "stale_exempt"):
        assert getattr(LongProfile, field) == getattr(ShortProfile, field), field


# ------------------------------------------------------------- the protection


def test_a_resting_fill_is_protected_rather_than_left_naked():
    """**The live bug.** `RestingEntry.place` leaves a bare limit with no stop
    and no target, and its `on_order_filled` only pops the wait - so a rest
    that filled was an unprotected position for as long as resting entries have
    existed, and the two bracketing entries being correct is exactly why nobody
    looked.

    Whether a position is protected is a question about the venue and not about
    which entry ran, so the rule is one rule and no entry has to remember it.
    """
    strategy, _ = run(SurpriseResting, RestingEntryConfig)
    assert strategy.taken == 1
    held = strategy.cache.positions_open(strategy_id=strategy.id)
    assert held, f"the rest never filled: {strategy.passed_over}"
    stops = guards(strategy)
    assert len(stops) == 1, f"a filled rest has no stop at the venue: {strategy.passed_over}"
    assert strategy.passed_over.get("(exit):protected") == 1
    assert stops[0].side is OrderSide.SELL, "the stop closes, so it is the other side"
    assert stops[0].is_reduce_only


def test_a_bracketed_entry_is_not_given_a_second_stop():
    """Two stops on one position is not two policies, it is one position that
    closes twice. The question asked is the cache's - *is anything holding a
    stop* - so the entry that already bracketed is left alone."""
    strategy, _ = run(SurpriseEdge)
    assert len(guards(strategy)) == 1
    assert "(exit):protected" not in strategy.passed_over


def test_the_stop_covers_what_is_open_and_not_what_was_intended():
    """The quantity is the position's, and that is the only answer that cannot
    be wrong.

    A partial fill, a venue that rounds, or a second fill into one position all
    leave `intent.volume` and `position.quantity` disagreeing - and a stop
    sized from the intent would then leave part of a live position uncovered,
    which is the exact failure a bracket exists to make impossible.
    """

    strategy, _ = run(SurpriseResting, RestingEntryConfig)
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]
    held = strategy.exits.held(position.id)

    # The disagreement a partial fill produces, made directly: the plan asked
    # for four times what is open. A venue that rounds, or a second fill into
    # one position, produces the same gap in the other direction.
    held.intent = replace(held.intent, volume=float(position.quantity) * 4)
    sent: list[object] = []
    strategy.submit_order = sent.append
    strategy._guards = list  # as though nothing were holding a stop yet
    strategy._attach(position.id)

    assert len(sent) == 1
    assert sent[0].quantity == position.quantity, "the stop does not cover the whole position"
    assert float(sent[0].trigger_price) == pytest.approx(held.intent.stop, abs=1e-05), (
        "the price is the plan's, and only ever the plan's"
    )


def test_a_position_with_no_remembered_intent_is_closed_rather_than_left_naked():
    """**The price is the one number that must never be invented.**

    A quantity has a correct answer whatever this process remembers; a stop does
    not. A distance, a volatility multiple or the configured default all put a
    price nobody chose at the venue, and that price then reads as protection in
    every report - which is worse than no stop, because an unprotected position
    at least looks like one.

    So a position whose plan cannot be reconstructed is an orphan: said out
    loud, journalled, and flattened.
    """
    strategy, _ = run(SurpriseEdge)
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]

    # Stubbed because the engine has stopped and `close_position` routes to a
    # disconnected client. What is under test is the decision to flatten.
    flattened: list[object] = []
    strategy.close_position = flattened.append

    strategy._intended = None
    strategy._filled = None
    strategy.on_position_opened(type("Opened", (), {"position_id": position.id})())

    assert strategy.passed_over.get("(exit):orphan") == 1
    assert flattened == [position], "an unnameable stop was left standing"
    assert strategy.exits.held(position.id) is not None, "the real plan was forgotten too"


# ------------------------------------------------------------ the basket close


def test_the_basket_close_reaches_the_position_s_own_strategy():
    """**The exit that reported itself and did nothing.**

    `BasketExit` has no order factory and must not have one - submitting under
    its own identity would stop the position's `strategy_id` naming what opened
    *and* closed it, which is the whole property the carve-up was for. So it
    publishes, and for as long as it has existed the only subscriber on `alerts`
    was the Telegram notifier: the log said "closing all N position(s)", the
    counter agreed, and the book stayed open.
    """
    closer = Closer(CloserConfig(instrument_id=EURUSD.id))
    strategy, _ = run(SurpriseEdge, feed=quotes(count=20), actors=(closer,))
    assert closer.sent == 1, "the request was never published"
    assert strategy.passed_over.get("(exit):basket") == 1
    assert not strategy.cache.positions_open(strategy_id=strategy.id), "the book stayed open"


def test_another_strategy_s_basket_close_is_ignored():
    """An exit rule that could close another strategy's position is the magic
    number bug wearing a new hat, and the request names its owner precisely so
    this does not have to guess."""
    closer = Closer(CloserConfig(instrument_id=EURUSD.id, strategy_id="SurpriseEdge-SOMEONE-ELSE"))
    strategy, _ = run(SurpriseEdge, feed=quotes(count=20), actors=(closer,))
    assert closer.sent == 1
    assert "(exit):basket" not in strategy.passed_over
    assert strategy.cache.positions_open(strategy_id=strategy.id), "it closed someone else's trade"


# --------------------------------------------------------------- the conflict


def test_a_trailing_order_at_the_venue_makes_advance_stand_down():
    """`manage.py` says three things can move a stop on this desk - the MT5
    bridge's twenty-second handler, Nautilus's native trailing order, and
    `advance` - and exactly one may, because two on different clocks give
    whichever wrote last and that is not a policy.

    `Exits.conflicts` was the assertion of that and had no caller, so the
    assertion was a docstring. `advance` is the one that stands down: the
    trailing order is already live, and cancelling it from the loop would be a
    second policy racing the first rather than replacing it.
    """
    from till_infinity.strategies.exits import Exits

    def order(name: str, kind: str):
        kinds = type("T", (), {"name": kind})()
        return type("O", (), {"client_order_id": name, "order_type": kinds})()

    trailing = order("O-1", "TRAILING_STOP_MARKET")
    plain = order("O-2", "STOP_MARKET")
    assert Exits.conflicts([trailing, plain]) == ["O-1"]

    def on(settings):
        settings.break_even_at = 1.0

    strategy, _ = run(SurpriseEdge, feed=quotes(count=16, jump_after=WARM + 2, jump=3e-04), tune=on)
    assert strategy.passed_over.get("(exit):advanced") == 1, "the control: advance normally runs"
    assert strategy.cache.positions_open(strategy_id=strategy.id), "nothing left to manage"

    strategy._guards = lambda: [trailing]
    strategy.on_quote_tick(quotes(count=1)[0])
    assert strategy.passed_over.get("(exit):trailing-conflict") == 1
    assert strategy.passed_over.get("(exit):advanced") == 1, "advance moved a stop anyway"


class TestTheTrailGetsAVolatilityFromEveryRule:
    """**`advance` stood down on one rule in four, and silently.**

    `price_distance` multiplies by `vol_bps`, so an intent carrying none gets
    no trail at all - and a trail that never moves a stop is indistinguishable
    from a trail that was never switched on.

    Measured before the fix: `TRADING_TRAIL_VOL` at 0.25, 0.5, 1.0 and 3.0,
    crossed with `TRADING_TRAIL_SIGMAS` at 0.5 and 0.0, moved
    `smc-bos-causal` by **0.00 on all eight combinations**, while the same
    settings moved `statespace-surprise` from -93.58 to -56.12 and
    `statespace-long` from -145.89 to -58.90. After it, the structure rule
    moves too: -62.32 at no trail against -16.46, -21.70 and +40.06 at 0.5, 1.0
    and 2.0 volatility units. **Eight positions, so those are mechanics and
    not an edge** - `node/corpus.py` holds 76 days.
    """

    def _intent(self, **features):
        from types import SimpleNamespace

        return SimpleNamespace(features=features)

    def test_a_folded_log_variance_is_used_as_it_stands(self):
        """The statespace rules publish `vol_bps` already, in the unit
        `price_distance` wants, so nothing is converted."""
        from till_infinity.strategies.exits import _trail_vol_bps

        assert _trail_vol_bps(self._intent(vol_bps=2.3231)) == pytest.approx(2.3231)

    def test_an_atr_is_converted_rather_than_renamed(self):
        """`structure.py` publishes `bos_atr` and says in place why it is not
        called `vol_bps`: that column is a folded log variance elsewhere, and
        an ATR written into it would put one journal column in two estimators.
        So the conversion happens at the one caller that needs a distance.

        An ATR is a price distance and `vol_bps` is relative, so the factor is
        `atr / price * 10_000` - the inverse of `price_distance`.
        """
        from till_infinity.risk.sizing import price_distance
        from till_infinity.strategies.exits import _trail_vol_bps

        atr, price = 0.0012, 1.1000
        found = _trail_vol_bps(self._intent(bos_atr=atr, bos_close=price))

        assert found == pytest.approx(atr / price * 10_000.0)
        assert price_distance(price, found, 1.0) == pytest.approx(atr), (
            "one volatility unit must come back as the ATR it was built from"
        )

    def test_the_folded_reading_wins_where_a_rule_carries_both(self):
        """Not an arbitrary precedence: `vol_bps` is the measured estimator
        this desk scores on, and the ATR is a fallback for the one rule that
        publishes no folded reading."""
        from till_infinity.strategies.exits import _trail_vol_bps

        both = self._intent(vol_bps=2.0, bos_atr=0.0012, bos_close=1.1)
        assert _trail_vol_bps(both) == pytest.approx(2.0)

    def test_a_rule_with_no_volatility_gets_no_trail_rather_than_a_guess(self):
        """**The control for the fix.** Inventing a distance here would put a
        stop at a price nothing measured, which is worse than standing down -
        and `advance` already returns None on a zero, so standing down is the
        behaviour the rest of the code expects."""
        from till_infinity.strategies.exits import _trail_vol_bps

        assert _trail_vol_bps(self._intent()) == 0.0
        assert _trail_vol_bps(self._intent(bos_atr=0.0012)) == 0.0, "an ATR with no anchor price"
        assert _trail_vol_bps(self._intent(bos_close=1.1)) == 0.0, "a price with no ATR"
        assert _trail_vol_bps(self._intent(vol_bps=0.0, bos_atr=0.0, bos_close=0.0)) == 0.0


# ------------------------------------------------------- what the notifier sees


def test_closing_a_position_publishes_a_trade_alert():
    """**The Telegram notifier had nothing to send, and every signal said it was fine.**

    It starts, subscribes to `alerts`, logs `RUNNING`, and reports the shapes
    `NOTIFY_SHAPES` names - `trade` among them. The only code in the repository
    that published to `alerts` was `basket.close`, from a strategy that is not
    in the configured list. So the desk opened and closed positions for months
    and not one message was ever sent.
    """
    from till_infinity.utils import topics

    strategy, _ = run(SurpriseEdge, feed=quotes(count=20))
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]

    seen: list[dict] = []
    topics.subscribe(strategy, topics.ALERTS, seen.append)
    strategy.on_position_closed(
        type(
            "Closed",
            (),
            {
                "position_id": position.id,
                "instrument_id": position.instrument_id,
                "realized_pnl": "1.23",
            },
        )()
    )

    trades = [p for p in seen if (p.get("fields") or {}).get("shape") == "trade"]
    assert len(trades) == 1, f"nothing a notifier could send: {seen}"
    sent = trades[0]["fields"]
    assert sent["event"] == "closed"
    assert sent["realized_pnl"] == "1.23"
    assert sent["strategy_id"] == str(strategy.id)

    # The payload the *filter* reads, which is the half that was wrong first.
    from till_infinity.notifications.filters import Filter

    assert Filter(shapes=frozenset({"trade"})).rejects(trades[0]) == ""


def test_a_trade_alert_survives_the_notifier_s_own_filter(monkeypatch):
    """Publishing is half of it: the filter decides whether it is sent.

    `NOTIFY_SHAPES` on the instance lists `trade`, and an alert carrying no
    interval is kept - so this is the pair that has to hold for a message to
    arrive. A publisher whose shape the filter drops is the same silence with
    an extra step.
    """
    from till_infinity.notifications.filters import Filter

    monkeypatch.setenv("NOTIFY_SHAPES", "drift,agent,trade,statespace")
    monkeypatch.delenv("NOTIFY_MIN_INTERVAL", raising=False)

    kept = Filter.from_env()

    assert kept.rejects({"fields": {"shape": "trade", "event": "closed"}}) == ""


def test_the_filter_control_still_drops_a_shape_nobody_asked_for():
    """The control. A filter that accepts everything would make the test above
    pass for the wrong reason."""
    from till_infinity.notifications.filters import Filter

    only_trades = Filter(shapes=frozenset({"trade"}))

    assert only_trades.rejects({"fields": {"shape": "spread"}}) != ""


def test_a_refused_order_is_announced():
    """**The desk tried to trade and could not, and nobody was told.**

    On the night of 2026-11-05 three brackets were refused with retcode 10018,
    `Market closed`, on index feeds whose session had ended, and nine more
    were denied as duplicates behind them. The only publisher on `alerts` was
    a position *opening*, so a desk that reached twelve decisions and acted on
    none of them sent nothing - and a position is rare, so the channel can
    stay silent for days while the desk is refused nightly.
    """
    from till_infinity.utils import topics

    strategy, _ = run(SurpriseEdge, feed=quotes(count=20))
    seen: list[dict] = []
    topics.subscribe(strategy, topics.ALERTS, seen.append)

    strategy.on_order_rejected(
        type(
            "Rejected",
            (),
            {
                "instrument_id": EURUSD.id,
                "position_id": None,
                "reason": "Order failed: Market closed",
            },
        )()
    )

    sent = [p for p in seen if (p.get("fields") or {}).get("shape") == "trade"]
    assert len(sent) == 1, f"a refusal told nobody: {seen}"
    assert sent[0]["fields"]["event"] == "rejected"
    assert "Market closed" in sent[0]["fields"]["reason"]
    assert sent[0]["level"] == "warning", "a refusal is not an info line"


def _rejected(instrument=None, reason: str = "UNKNOWN"):
    return type(
        "Rejected",
        (),
        {
            "instrument_id": (instrument or EURUSD).id,
            "position_id": None,
            "client_order_id": None,
            "reason": reason,
        },
    )()


def test_a_refusal_names_the_side_the_desk_proposed():
    """`eurcad rejected / reason UNKNOWN` does not say which way it wanted to go.

    Asked for after the alert arrived on 2026-11-09 and could not be acted on:
    a refusal is a decision the desk reached, and the decision is a direction.
    Read off the `Intent` rather than the order, because an exit sells a long -
    so an order side names the position only for an entry, and `short` about a
    refused exit on a long would be exactly backwards.
    """
    from till_infinity.domain.models import Intent, Side
    from till_infinity.utils import topics

    strategy, _ = run(SurpriseEdge, feed=quotes(count=20))
    strategy._intended = Intent(
        feed="eurusd",
        symbol="EURUSD",
        side=Side.SELL,
        volume=0.1,
        entry=1.08,
        stop=1.09,
        target=1.06,
    )
    seen: list[dict] = []
    topics.subscribe(strategy, topics.ALERTS, seen.append)

    strategy.on_order_rejected(_rejected())

    sent = [p for p in seen if (p.get("fields") or {}).get("shape") == "trade"]
    assert len(sent) == 1
    assert sent[0]["fields"]["side"] == "short", "a SELL intent is a short position"
    assert "short" in sent[0]["title"], f"the title still hides the side: {sent[0]['title']}"
    assert "rejected" in sent[0]["title"], "the side must not displace the event"


def test_a_refusal_with_no_intent_behind_it_still_announces_without_a_side():
    """The control. Without it "it names the side" cannot be told from "it
    refuses to announce anything it cannot label", and a refusal that reaches
    nobody is the defect `test_a_refused_order_is_announced` exists for.

    A rejection can arrive with no intent in hand - reconciliation refusing an
    order this process did not place is the real case - and it is still news.
    """
    from till_infinity.utils import topics

    strategy, _ = run(SurpriseEdge, feed=quotes(count=20))
    strategy._intended = None
    seen: list[dict] = []
    topics.subscribe(strategy, topics.ALERTS, seen.append)

    strategy.on_order_rejected(_rejected())

    sent = [p for p in seen if (p.get("fields") or {}).get("shape") == "trade"]
    assert len(sent) == 1, "a refusal it could not label told nobody"
    assert "side" not in sent[0]["fields"], "a side was invented from nothing"
    assert sent[0]["title"].endswith("rejected")


def test_a_denied_order_is_announced_separately_from_a_rejection():
    """The cause differs and so does the remedy: a denial is this process's
    own risk engine or a duplicate and names a defect here, where a rejection
    names a condition at the broker."""
    from till_infinity.utils import topics

    strategy, _ = run(SurpriseEdge, feed=quotes(count=20))
    seen: list[dict] = []
    topics.subscribe(strategy, topics.ALERTS, seen.append)

    strategy.on_order_denied(
        type(
            "Denied",
            (),
            {"instrument_id": EURUSD.id, "position_id": None, "reason": "duplicate OrderListId"},
        )()
    )

    sent = [p for p in seen if (p.get("fields") or {}).get("shape") == "trade"]
    assert len(sent) == 1
    assert sent[0]["fields"]["event"] == "denied"


def test_a_fill_survives_the_minimum_level_and_a_level_call_does_not():
    """**The desk could report failing to trade and not trading.**

    `on_order_rejected` and `on_order_denied` publish at `warning` and
    arrived. `on_position_opened` names no level, so `_announce` defaults it to
    `info`, which is under the notifier's `minimum_level = WARNING`. On
    2026-11-09 the first fill this desk ever took - BTCUSD BUY 0.10 at
    74,649.207, ticket 5830761681 - was published, dropped, and the tally moved
    from `1 sent, 1 dropped` to `1 sent, 3 dropped` with nothing saying why.

    `minimum_level` is a volume control and its own docstring gives the reason:
    "the bus carries a notice per touched bar". That is an argument about
    readings. A trade is not a reading, so `UNFILTERED` exempts the shape - the
    same argument `UNCAPPED` already makes about the hourly budget.

    The second half is the control, and it is the point: a `statespace` level
    call at `info` must **still** be dropped. Without it this test cannot tell
    "a fill is exempt" from "the floor was removed", and removing the floor is
    how the channel becomes something nobody reads.
    """
    from till_infinity.notifications.actor import WARNING, Notifier, NotifierConfig
    from till_infinity.utils.topics import alert

    opened = alert(
        shape="trade",
        source="trading",
        level="info",
        title="btcusd long opened",
        body="0.10 at 74649.207",
        event="opened",
        feed="btcusd",
    )
    reading = alert(
        shape="statespace",
        source="statespace",
        level="info",
        title="btcusd touched a level",
        body="a notice per touched bar, which is what the floor is for",
        feed="btcusd",
    )

    said: list[tuple[str, str]] = []

    class Recording(Notifier):
        """`_quiet` recorded rather than logged.

        `Actor.log` is a read-only Cython attribute and cannot be stubbed on an
        instance, so the override is on the one method that writes to it. What
        is asserted below is that a drop *produces a reason at all* - the real
        `_quiet` was written for that and was never wired into this gate.
        """

        def _quiet(self, kind: str, detail: str) -> None:
            said.append((kind, detail))
            self._silent[kind] = self._silent.get(kind, 0) + 1

    # Built without `__init__` on purpose: what is under test is the gate, and
    # constructing a real `Actor` needs a node.
    actor = Recording.__new__(Recording)
    actor._cfg = NotifierConfig()
    actor._filter = None
    actor._silent = {}
    assert actor._cfg.minimum_level == WARNING, "the floor moved; this test pins the exemption"

    assert actor._wanted(opened) is True, "a fill was dropped under the level floor again"
    assert actor._wanted(reading) is False, "the floor was removed rather than scoped"
    # The drop says why. `_quiet` was written for this and was not wired in,
    # so the fill's drop left no reason anywhere at all.
    assert any("minimum level" in kind for kind in actor._silent), actor._silent
    assert said, "the drop was counted and still said nothing"
    assert "statespace" in said[-1][1], said[-1]


def test_an_announced_refusal_survives_the_notifier_and_becomes_a_message():
    """The whole chain in one assertion: published, past the filter, and built
    into the Notification a destination is handed.

    Publishing is not sending. The first version of `_announce` put `shape` at
    the top of the payload where `ExitMechanism.on_alert` reads it, and the
    notifier's filter reads `fields.shape` - so it was dropped silently as
    `shape '' not in [...]`, with nothing logged at the publisher.
    """
    from till_infinity.notifications.filters import Filter
    from till_infinity.notifications.models import Level, from_message
    from till_infinity.utils import topics

    strategy, _ = run(SurpriseEdge, feed=quotes(count=20))
    seen: list[dict] = []
    topics.subscribe(strategy, topics.ALERTS, seen.append)
    strategy.on_order_rejected(
        type(
            "Rejected",
            (),
            {"instrument_id": EURUSD.id, "position_id": None, "reason": "Market closed"},
        )()
    )
    payload = next(p for p in seen if (p.get("fields") or {}).get("shape") == "trade")

    assert Filter(shapes=frozenset({"trade"})).rejects(payload) == ""

    message = from_message(payload)
    assert message is not None, "the filter passed it and nothing could be built"
    assert message.level is Level.WARNING
    assert message.title
    assert message.fields["event"] == "rejected"


def test_an_alert_names_the_side_in_words_and_never_as_an_enum_number():
    """**A live alert read `side 2` under a title that said `short`.**

    `PositionOpened.entry` is an `OrderSide`, which is an int enum on the
    Cython model, so `str(...)` of it is `"2"` - and the value the caller
    passed won over the word `_announce` computes. The same shape as
    `order.order_type` reading `"3"` against `"STOP_MARKET"`.

    Asserted on the payload rather than through a bus: `Strategy.msgbus` is
    read-only, which is why `_announce` is reached with a stub here.
    """
    from types import SimpleNamespace

    from till_infinity.strategies import exits

    sent: list[dict] = []
    stub = SimpleNamespace(
        id="ZonesEdge-EURCAD_E637",
        msgbus=SimpleNamespace(publish=lambda topic, msg: sent.append(msg)),
        log=SimpleNamespace(warning=lambda *a: None),
        _feed_name=lambda: "eurcad",
        _announced_side=lambda event: "short",
    )
    event = SimpleNamespace(
        instrument_id="EURCAD.MT5",
        position_id="EURCAD.MT5-ZonesEdge-EURCAD_E637",
        entry=2,  # `OrderSide.SELL`, as the Cython enum stringifies it
    )

    # The caller still passing the enum through must not be able to win.
    exits.ManagedExit._announce(stub, "opened", event, side=str(event.entry), quantity="0.26")

    assert sent, "nothing was published"
    fields = sent[0]["fields"]
    assert fields["side"] == "short", f"the alert said side {fields['side']!r}"
    assert "side 2" not in sent[0]["body"], sent[0]["body"]
    assert sent[0]["title"] == "eurcad short opened"
