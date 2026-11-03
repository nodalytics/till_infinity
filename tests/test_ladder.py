"""The promotion loop, wired into the node that trades.

`node/pipeline.py` is the unattended loop - discover, gate, small capital, full
capital, and back out again - with its state persisted, a ceiling no amount of
passing can lift, and every decision written with its evidence. **Its only
importer was `tests/test_pipeline.py`.** `node/live.py` never mentioned it, so
the basket was whatever `TRADING_STRATEGIES` named for ever: nothing promoted,
nothing retired, and a discovery run had nowhere to deliver a candidate.

Wiring it found a crash that had never fired. `Allocation.limits` built the
`max_notional_per_order` mapping as `"5000.00 USD"`, and `RiskEngine` reads that
mapping with `Decimal(value)` - so a node configured from it raised
`decimal.InvalidOperation` during construction. The function's docstring said
it "produces the mapping Nautilus's risk engine already takes". It did not, and
nothing had called it.

The split in this file follows the split in the code. `pipeline.step` decides
and does not act, because "the node holds the `Trader`, so this decides and the
caller acts"; an `Actor` cannot act either, since Nautilus gives it the bus, the
cache, the clock and the portfolio and nothing else. So `LadderActor` decides
and publishes, and `node/live._supervise` subscribes a handler closed over the
trader and the risk engine. The tests for the glue bind the **real** Nautilus
signatures rather than trusting a stub, because a stub that stands in for a
method creates the attribute instead of checking one exists - which is how
three modules came to call `Actor.publish_data_dict`, a method that has never
existed.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest
from nautilus_trader.risk.engine import RiskEngine
from nautilus_trader.trading.trader import Trader

from till_infinity.node import ladder as rungs
from till_infinity.node.pipeline import Ladder
from till_infinity.node.promotion import Allocation, Candidate, Rung
from till_infinity.utils.topics import DECLARED, LADDER

# ------------------------------------------------- the crash that never fired


def test_the_notional_mapping_is_one_the_engine_can_read():
    """**The regression, and it would have stopped the node from starting.**

    `RiskEngine.__init__` reads this mapping with `Decimal(value)`, so a
    currency inside the value is `decimal.InvalidOperation` rather than a unit.
    `Allocation.limits` emitted `"5000.00 USD"` and had no caller on any live
    path, so the only way to find it was to wire the loop that calls it.
    """
    found = Allocation().limits(Rung.SMALL, 100_000.0, ["EURUSD.SIM"])
    assert found == {"EURUSD.SIM": "5000.00"}
    # The assertion that matters is not the string, it is that the engine's own
    # parse of it succeeds.
    assert Decimal(found["EURUSD.SIM"]) == Decimal("5000.00")


def test_a_rung_that_may_not_trade_gets_no_permission_rather_than_no_limit():
    """An empty mapping is read by the risk engine as no permission. A
    candidate off the ladder must not be able to place an order by default,
    which is the opposite of what a missing key would mean if the default were
    "unlimited"."""
    assert Allocation().limits(Rung.DISCOVERED, 100_000.0, ["EURUSD.SIM"]) == {}
    assert Allocation().limits(Rung.RETIRED, 100_000.0, ["EURUSD.SIM"]) == {}


# ---------------------------------------------------------------- the switch


def test_the_ladder_is_off_unless_asked(monkeypatch):
    """**This is the actor that changes how much of the account a strategy may
    use**, so it is off until somebody says otherwise - the same argument as
    `TRADING_LIVE`, and unlike the journal and the notifier beside it, which
    are on by default because a node trading without a record is the worse
    failure."""
    monkeypatch.delenv("TRADING_LADDER", raising=False)
    assert rungs.wanted() is False
    monkeypatch.setenv("TRADING_LADDER", "1")
    assert rungs.wanted() is True


def test_the_ladder_file_lives_on_the_mounted_volume():
    """Under `.data/`, which `docker-compose.yml` binds. Anywhere else and
    every deploy starts with an empty ladder and silently loses every
    candidate's rung and history - `restore-drops-deque-maxlen` is the warning
    about how that goes wrong quietly."""
    assert rungs.PATH.startswith(".data/")
    assert rungs.configured().path.startswith(".data/")


def test_the_file_can_be_moved_and_the_cadence_changed(monkeypatch):
    monkeypatch.setenv("TRADING_LADDER_PATH", ".data/other.json")
    monkeypatch.setenv("TRADING_LADDER_SECONDS", "60")
    found = rungs.configured()
    assert found.path == ".data/other.json"
    assert found.every == pytest.approx(60.0)


def test_the_topic_is_declared():
    """A publisher using a name the registry does not carry is publishing where
    nothing listens, which is the failure this desk has paid for twice - a
    subscriber with no publisher and a publisher with no subscriber look
    identical from either side, and both look like a quiet market."""
    assert LADDER in DECLARED


# ------------------------------------------------------------- the glue, bound


def test_the_engine_still_takes_a_notional_cap_the_way_this_calls_it():
    """Bound against Nautilus's own class, not a stub.

    `_supervise` exists to make two calls, and if either signature moves the
    handler fails at the moment a promotion happens - inside a live node, on
    the publishing actor's stack. A stub standing in for these would create the
    attribute rather than check one exists.
    """
    bound = inspect.signature(RiskEngine.set_max_notional_per_order)
    assert list(bound.parameters) == ["self", "instrument_id", "new_value"]
    # Documented as "integer, float, string, or Decimal" - and explicitly not a
    # `Money`, which is what the config-shaped string tempted.
    assert "Decimal" in (RiskEngine.set_max_notional_per_order.__doc__ or "")


def test_the_trader_still_stops_one_strategy_the_way_this_calls_it():
    """And that it takes a strategy id, which is the whole reason a candidate's
    name has to be one: the ladder keys on the identifier Nautilus already
    carries on every order, fill and position."""
    bound = inspect.signature(Trader.stop_strategy)
    assert list(bound.parameters) == ["self", "strategy_id"]


def test_retiring_one_leg_does_not_halt_the_node():
    """**The trading state is global and a retirement is not.**

    `promotion.retire`'s docstring describes `TradingState.REDUCING` then
    `stop_strategy`, which is right for a node-level wind-down and wrong for
    one leg: `set_trading_state` applies to the whole engine, so using it to
    retire one candidate would stop every other strategy opening a position.
    The exception is a breached limit, which keeps the global halt because that
    is what a breach means.

    Asserted on the source of the handler, which is weaker than running a node
    and is the strongest check available without one - the alternative is a
    stub whose `set_trading_state` nobody calls, which would pass either way.
    """
    from till_infinity.node import live

    source = inspect.getsource(live._supervise)
    assert "stop_strategy" in source
    halt = source.index("set_trading_state")
    guard = source.index('if action == "HALTED"')
    assert guard < halt, "the global halt is reached without checking the reason first"


# --------------------------------------------------------------- the counting


def test_the_episode_count_is_a_delta_and_not_the_total():
    """`Cache.positions_closed` returns every closed position the process has
    seen, so a pass that added the total would multiply the sample by the
    number of passes - and a candidate needing ten episodes would promote on
    its second pass having traded once.

    `Episodes` exists so this arithmetic is assertable without a kernel, which
    is the same argument `pipeline.step` and `strategies/sizes.py` make: the
    figure that must not be wrong should not be reachable only through a node
    nobody stands up in a test.
    """
    episodes = rungs.Episodes()
    assert episodes.since("Rule-EURUSD-E270", 4) == 4
    assert episodes.since("Rule-EURUSD-E270", 4) == 0, "the same positions were counted twice"
    assert episodes.since("Rule-EURUSD-E270", 7) == 3


def test_a_cache_that_has_gone_backwards_adds_nothing():
    """A restart empties the cache and not the ladder, so the count it reads is
    lower than the count already recorded. Zero rather than a negative: the
    sample a candidate has traded does not shrink because this process
    forgot."""
    episodes = rungs.Episodes(counted={"Rule-EURUSD-E270": 12})
    assert episodes.since("Rule-EURUSD-E270", 3) == 0
    assert episodes.counted["Rule-EURUSD-E270"] == 12


def test_a_candidate_that_is_not_a_strategy_id_counts_as_nothing():
    """A ladder can hold a candidate this node is not running - a discovery
    that has not been deployed, or a name from another host. `None` rather than
    a raise, so the gates hold it for want of a sample, which is the correct
    outcome; a loop that raised on somebody else's candidate would stop
    deciding about its own."""
    assert rungs.named("not a strategy id") is None
    assert str(rungs.named("Rule-EURUSD-E270")) == "Rule-EURUSD-E270"


def test_a_promotion_publishes_the_share_and_not_a_notional():
    """The handler holds the account, so it converts once, where the equity is.
    A notional computed in the actor would be computed from a portfolio read at
    a different moment than the one the cap is applied at - and the engine
    denominates the cap in the instrument's quote currency, which only the side
    holding the instrument can see."""
    candidate = Candidate(name="Rule-EURUSD-E270", rung=Rung.SMALL)
    candidate.allocation = 0.05
    payload = rungs.allocation_message("Rule-EURUSD-E270", candidate)

    assert payload["share"] == pytest.approx(0.05)
    assert payload["rung"] == "small"
    assert payload["action"] == "allocate"
    assert "notional" not in payload


# ---------------------------------------------------------------- the seeding


def test_a_seeded_candidate_is_granted_nothing_and_held():
    """**Seeding has to be safe by construction, not by a caller being careful.**

    A leg this node is running was put there by configuration, not by passing a
    gate, so it enters at `DISCOVERED` - where `Allocation.of` is zero and
    `Candidate.blocking` refuses to climb with "no gate has been run". The
    alternative, seeding at the rung the configuration implies, would hand it
    an allocation the gates never granted, which is the one thing this loop
    must not do.
    """
    candidate = Candidate(name="Rule-EURUSD-E270", origin="configured on this node")
    assert candidate.rung is Rung.DISCOVERED
    assert Allocation().of(Rung.DISCOVERED) == 0.0
    assert candidate.blocking() == ["no gate has been run"]


def test_a_seeded_candidate_cannot_be_promoted_by_time_alone():
    """The sample passing is not the gate passing. A seeded leg accumulating a
    hundred closed positions still has no gate, and `step` holds it - which is
    what makes seeding every running strategy safe rather than a slow
    automatic grant of capital."""
    from till_infinity.node.pipeline import step

    ladder = Ladder(candidates={"Rule-EURUSD-E270": Candidate(name="Rule-EURUSD-E270")})
    ladder.note_episodes("Rule-EURUSD-E270", 10_000)

    decided = step(ladder)
    assert [d.action for d in decided] == ["held"]
    assert "no gate has been run" in decided[0].reason
    assert ladder.candidates["Rule-EURUSD-E270"].rung is Rung.DISCOVERED
    assert ladder.allocated() == 0.0
