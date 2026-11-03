"""The promotion loop: what it keeps between runs, and whether it can close.

Every part of this loop existed and it could not run. Three separate breaks,
each of which left it looking like a loop that was simply waiting for news:

1. The ladder file could not carry a gate. `save` excluded them and `load`
   rebuilt every candidate without them, so one passing at DSR 1.0 came back
   from its own file saying "no gate has been run".
2. Nothing could deliver one. The loop says candidates arrive "by being
   written to the ladder file - by a discovery run, or by a person", and no
   function wrote one.
3. The two rungs before capital were judged on live episodes. Neither has an
   allocation, so neither can trade, so neither can reach the 200 closed
   positions it needed in order to be allowed to trade.

The tests below are about those three behaviours rather than about the code
that implements them: does a passing candidate still pass after a restart, can
a search hand one over, and does one reach capital. The last test is about a
precondition nobody had written down - see its docstring.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from till_infinity.node import live
from till_infinity.node.ladder import allocation_message
from till_infinity.node.pipeline import Ladder, deliver, sample_seen, step
from till_infinity.node.promotion import Allocation, Candidate, Gate, Rung

NAME = "SurpriseEdge-EUR/USD-E580"


def passing() -> Gate:
    """A gate that passes, with everything the deflation needs.

    Both float sequences are supplied because `deflated` returns `None`
    without them and `verdict` then falls back to the `passed` flag. A fixture
    that left them out would make every assertion here about the fallback.
    """
    return Gate(
        name="backtest",
        criterion="DSR >= 0.95",
        control="a walk through the same detector",
        candidates=20,
        episodes=240,
        trial_sharpes=tuple(0.1 * i for i in range(20)),
        returns=tuple(0.004 + 0.0001 * i for i in range(400)),
    )


def failing(name: str = "backtest") -> Gate:
    """A gate that cannot pass: no returns to deflate and `passed` unset."""
    return Gate(
        name=name,
        criterion="DSR >= 0.95",
        control="a walk through the same detector",
        candidates=20,
        episodes=240,
        passed=False,
    )


def roundtrip(ladder: Ladder) -> Ladder:
    """The ladder as a restarted node would read it back."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ladder.json"
        ladder.save(path)
        return Ladder.load(path)


def ticking(start: float = 1_800_000_000.0):
    """A clock that moves on a quarter hour each time it is read."""
    at = [start]

    def now() -> float:
        at[0] += 900.0
        return at[0]

    return now


# --------------------------------------------------------- what the file keeps


def test_a_passing_gate_survives_the_file():
    """The regression, measured before it was fixed: DSR 1.000 and nothing
    blocking became zero gates and "no gate has been run".

    Asserted on the reloaded candidate's own verdict rather than on the JSON,
    because what matters is that it still reaches the same decision.
    """
    candidate = Candidate(name=NAME, origin="a sweep")
    candidate.gates.append(passing())
    assert candidate.blocking() == []

    back = roundtrip(Ladder(candidates={NAME: candidate})).candidates[NAME]
    assert len(back.gates) == 1
    assert back.blocking() == []
    assert back.gates[0].deflated() == pytest.approx(candidate.gates[0].deflated())


def test_the_returns_are_written_whole():
    """`deflated` recomputes the DSR from the returns and the trial Sharpes
    every time, so a gate saved without them is judged on `passed` instead -
    a weaker test swapped in at the restart, which is the kind of change
    nobody sees. They come back as the tuples the dataclass declares."""
    candidate = Candidate(name=NAME)
    candidate.gates.append(passing())
    back = roundtrip(Ladder(candidates={NAME: candidate})).candidates[NAME].gates[0]
    assert back.returns == passing().returns
    assert back.trial_sharpes == passing().trial_sharpes
    assert isinstance(back.returns, tuple)


def test_one_unreadable_gate_does_not_cost_the_others():
    """A hand-edited file can hold a gate that cannot exist, since `Gate`
    refuses one naming no control. Dropping it costs a hold for want of
    evidence; raising would lose every candidate in the file."""
    candidate = Candidate(name=NAME)
    candidate.gates.append(passing())
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ladder.json"
        Ladder(candidates={NAME: candidate}).save(path)
        raw = json.loads(path.read_text())
        gates = raw["candidates"][NAME]["gates"]
        gates.append({**gates[0], "name": "control-less", "control": ""})
        path.write_text(json.dumps(raw))
        back = Ladder.load(path)

    assert [gate.name for gate in back.candidates[NAME].gates] == ["backtest"]


def test_a_hold_reason_survives_so_a_restart_does_not_relog_it():
    """`holding` was written and never read back, so the de-duplication it
    exists for lasted as long as the process. A loop that re-states every hold
    on every restart buries the pass that matters."""
    ladder = Ladder(candidates={NAME: Candidate(name=NAME)})
    ladder.holding[NAME] = "no gate has been run"
    assert roundtrip(ladder).holding == {NAME: "no gate has been run"}


# -------------------------------------------------------------- the delivery


def test_delivering_a_gate_grants_no_capital():
    """Evidence is not a promotion. A delivered candidate lands where a
    configured leg lands - `DISCOVERED`, allocating nothing - and `step`
    decides the rest on its next pass."""
    ladder = Ladder()
    decision = deliver(ladder, NAME, passing(), origin="a sweep", now=ticking())

    candidate = ladder.candidates[NAME]
    assert candidate.rung is Rung.DISCOVERED
    assert candidate.allocation == 0.0
    assert decision.action == "delivered"
    assert "DSR 1.000" in decision.reason
    assert "240 episodes" in decision.evidence


def test_delivering_to_a_running_leg_leaves_its_rung_alone():
    """A leg already at small capital that gets a fresh backtest keeps its
    rung, its allocation and its episode count. The new reading is evidence
    for its next decision, not a re-run of the ones already taken."""
    candidate = Candidate(name=NAME, rung=Rung.SMALL, allocation=0.05, origin="configured")
    ladder = Ladder(candidates={NAME: candidate}, episodes={NAME: 7})

    deliver(ladder, NAME, passing(), origin="a later sweep", now=ticking())

    assert candidate.rung is Rung.SMALL
    assert candidate.allocation == 0.05
    assert ladder.episodes[NAME] == 7
    assert candidate.origin == "configured", "the first origin is the one that found it"


def test_a_second_reading_replaces_the_first():
    """`blocking` reads every gate, so a superseded failure left beside a pass
    would hold a candidate for ever on a number its own harness has already
    withdrawn."""
    ladder = Ladder()
    deliver(ladder, NAME, failing(), now=ticking())
    assert ladder.candidates[NAME].blocking() != []

    decision = deliver(ladder, NAME, passing(), now=ticking())
    candidate = ladder.candidates[NAME]
    assert len(candidate.gates) == 1
    assert candidate.blocking() == []
    assert decision.action == "gated", "a replacement reads differently from a first"


def test_two_differently_named_gates_both_still_apply():
    """Replacement is by name, so a cost gate and a backtest gate are two
    tests and a candidate has to satisfy both."""
    ladder = Ladder()
    deliver(ladder, NAME, passing(), now=ticking())
    deliver(ladder, NAME, failing("cost"), now=ticking())

    candidate = ladder.candidates[NAME]
    assert len(candidate.gates) == 2
    assert any("cost" in reason for reason in candidate.blocking())


# ------------------------------------------------- which sample gates a climb


@pytest.mark.parametrize("rung", [Rung.DISCOVERED, Rung.BACKTESTED])
def test_before_capital_the_sample_is_the_gates(rung):
    """The deadlock. Neither rung has an allocation, so asking either for 200
    closed positions asks for a sample that cannot exist."""
    candidate = Candidate(name=NAME, rung=rung)
    candidate.gates.append(passing())
    assert sample_seen(candidate, live=0) == 240


@pytest.mark.parametrize("rung", [Rung.SMALL, Rung.FULL])
def test_at_capital_the_sample_is_what_the_account_closed(rung):
    """Both live rungs review real trading, so a backtest's episodes are not
    evidence about them at all."""
    candidate = Candidate(name=NAME, rung=rung)
    candidate.gates.append(passing())
    assert sample_seen(candidate, live=4) == 4


def test_two_gates_on_one_backtest_are_not_two_samples():
    """The largest, not the sum. Adding them would let a second opinion stand
    in for a longer record."""
    candidate = Candidate(name=NAME, rung=Rung.DISCOVERED)
    candidate.gates.append(passing())
    candidate.gates.append(
        Gate(
            name="cost",
            criterion="pays its own spread",
            control="the same trades at twice the spread",
            candidates=1,
            episodes=90,
            passed=True,
        )
    )
    assert sample_seen(candidate, live=0) == 240


def test_a_candidate_with_no_gate_has_no_sample():
    """Zero rather than a raise, so a candidate somebody added by hand is held
    with "no gate has been run" instead of stopping the loop."""
    assert sample_seen(Candidate(name=NAME), live=0) == 0


# --------------------------------------------------------------- the whole loop


def test_a_discovered_candidate_reaches_capital_through_the_file():
    """End to end, and the test the three fixes exist for.

    A search delivers a gate; the ladder is written and read back as a
    restarted node would read it; the loop walks it with **no live episodes at
    all**, because a candidate with no allocation cannot trade; and it arrives
    at small capital with a message the node can act on. Every step is the
    production function and only the clock stands in for the node.
    """
    now = ticking()
    ladder = Ladder()
    deliver(ladder, NAME, passing(), origin="a sweep over the catalogue", now=now)

    ladder = roundtrip(ladder)
    for _ in range(2):
        step(ladder, allocation=Allocation(), now=now)

    candidate = ladder.candidates[NAME]
    assert candidate.rung is Rung.SMALL
    assert candidate.allocation == pytest.approx(0.05)
    assert allocation_message(NAME, candidate) == {
        "candidate": NAME,
        "action": "allocate",
        "rung": "small",
        "share": 0.05,
    }
    assert [decision.action for decision in ladder.log] == ["delivered", "promoted", "promoted"]


def test_a_failing_candidate_stays_where_it_is():
    """The control. A loop that promotes a passing candidate is only worth
    having if it refuses a failing one down the same path - otherwise the test
    above is satisfied by a loop that promotes everything."""
    now = ticking()
    ladder = Ladder()
    deliver(ladder, NAME, failing(), now=now)

    ladder = roundtrip(ladder)
    for _ in range(3):
        step(ladder, allocation=Allocation(), now=now)

    candidate = ladder.candidates[NAME]
    assert candidate.rung is Rung.DISCOVERED
    assert candidate.allocation == 0.0


# ------------------------------------------------ the precondition behind it all


def test_the_live_cache_has_no_database():
    """Load-bearing, and nowhere written down until now.

    `ladder.Episodes.since` keeps a high-water mark per candidate and returns
    the delta, so a sample is counted once rather than once per pass. That mark
    is in memory and deliberately not persisted: the Nautilus cache starts
    empty on every restart, so a fresh mark of zero counts the new closed
    positions correctly on top of the total the ladder file already holds.

    Give the cache a database and both halves break together - the cache comes
    back holding positions already counted, the mark is zero, and the loop adds
    a candidate's whole history to a total that contains it, promoting it on a
    sample it never traded. So this test is where a future deploy finds out
    that the absence of a cache database is a precondition of the arithmetic.
    """
    assert live.settings().cache.database is None
