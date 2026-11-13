"""Turning a sweep into a gate, and getting the gate to the ladder.

This module is the accounting that makes a deflated Sharpe honest, and until
now it was reached only incidentally by another test file. It is also the one
place where an undercount is invisible: a gate built from a search that forgot
its losers still looks like a gate, and reports a number that cannot be
challenged by reading it.

The tests here are about three ways that goes wrong. The trial count can be
understated, by dropping a proposal that failed or by counting only today's
sweep. The returns can be missing, in which case the deflation silently
becomes the `passed` flag. And the candidate can be delivered under a name the
live loop will never match to a strategy, in which case it is held for want of
episodes while the strategy it names trades beside it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from till_infinity.node.discovery import (
    Proposal,
    Question,
    Trial,
    Trials,
    deliver_to,
    gate_from,
    read,
    summarise,
)
from till_infinity.node.pipeline import Ladder
from till_infinity.node.promotion import Candidate, Rung


@dataclass(frozen=True)
class Result:
    """What `BacktestNode.run()` hands back, in the two fields read here.

    A stand-in rather than a real `BacktestResult` because the point of these
    tests is the accounting around the result, and building a real one needs a
    kernel and a catalogue. The two fields are the ones `Trial.of` reads, and
    `stats_returns` is a dict of finished statistics in the real thing too -
    which is the whole reason `read` has to be given the returns separately.
    """

    stats_returns: dict[str, float]
    total_positions: int = 0


def proposals(count: int) -> list[Proposal]:
    return [
        Proposal(
            name=f"candidate {i}",
            question=Question.DISPERSION,
            origin="a sweep over the stored catalogue",
            control="a walk through the same detector",
        )
        for i in range(count)
    ]


def results(count: int) -> list[Result]:
    return [Result({"SR_period": 0.1 * i}, total_positions=40 + i) for i in range(count)]


def series(count: int, length: int = 400) -> list[tuple[float, ...]]:
    return [tuple(0.004 + 0.0001 * i for i in range(length)) for _ in range(count)]


# ------------------------------------------------------------ the trial count


def test_a_length_mismatch_is_refused_rather_than_zipped_short():
    """Zipping short would drop trials from the count, and the count is what
    the deflation rests on - so the failure has to be loud."""
    with pytest.raises(ValueError, match="cannot be zipped away"):
        read(proposals(3), list(results(2)))


def test_a_returns_series_paired_with_the_wrong_trial_is_refused():
    """A series short by one silently shifts every later pairing, so each
    candidate would be deflated against another one's record."""
    with pytest.raises(ValueError, match="deflates the wrong candidate"):
        read(proposals(3), list(results(3)), series(2))


def test_a_proposal_that_could_not_be_measured_still_counts():
    """A search that drops its failures undercounts itself, and the deflation
    is only as honest as that count."""
    trials = Trials()
    for trial in read(proposals(2), list(results(2))).kept:
        trials.add(trial)
    trials.refuse(proposals(1)[0], "the run raised before it placed")

    assert trials.attempted == 3
    assert len(trials.kept) == 2
    assert "3 attempted, 2 measured, 1 failed" in summarise(trials)


def test_the_count_may_be_raised_for_earlier_searching_but_never_lowered():
    """`prior_trials` is usually the larger adjustment: this sweep's count is
    only what happened today, and a great many things have been tried on this
    data before. Lowering it below what the run itself measured would be an
    assertion against the evidence in hand."""
    trials = read(proposals(4), list(results(4)), series(4))
    raised = gate_from(trials, trials.best(), prior_trials=24)
    assert raised.candidates == 28

    with pytest.raises(ValueError, match="never lowered"):
        gate_from(trials, trials.best(), candidates=2)


def test_the_gate_records_whether_the_count_was_counted_or_asserted():
    """A later reader has to be able to tell a search that counted its trials
    from one that was told a number."""
    trials = read(proposals(4), list(results(4)), series(4))
    assert "4 measured here plus 24 prior" in gate_from(trials, trials.best(), prior_trials=24).note
    assert "set explicitly to 240" in gate_from(trials, trials.best(), candidates=240).note


def test_the_losers_are_what_make_the_deflation_possible():
    """`Var(SR_trials)` only exists if the search kept what it rejected. A gate
    built from one trial has nothing to deflate against, whatever that trial
    scored."""
    alone = read(proposals(1), list(results(1)), series(1))
    assert gate_from(alone, alone.best()).deflated() is None

    many = read(proposals(6), list(results(6)), series(6))
    assert gate_from(many, many.best()).deflated() is not None


# --------------------------------------------------------------- the returns


def test_without_returns_a_gate_falls_back_to_a_flag_nothing_sets():
    """The defect `read`'s signature warns about. A `BacktestResult` carries
    finished statistics and no returns series, so a sweep that does not supply
    one builds gates that can never pass - and the verdict says how many
    returns it was given rather than leaving a reader to guess."""
    trials = read(proposals(4), list(results(4)))
    gate = gate_from(trials, trials.best())

    assert gate.returns == ()
    assert gate.deflated() is None
    passed, why = gate.verdict()
    assert passed is False
    assert "0 returns were supplied" in why


def test_with_returns_the_same_sweep_can_be_deflated():
    """The control for the test above: the only thing that changed is the
    series, so a failure there is about the returns and not about the sweep."""
    trials = read(proposals(4), list(results(4)), series(4))
    gate = gate_from(trials, trials.best())

    assert gate.deflated() is not None
    assert gate.verdict()[0] is True


def test_the_episodes_come_from_the_result_not_from_the_returns():
    """A returns series is one value per period and the sample is one per
    closed position. Reading the first as the second would let a long backtest
    of few trades claim a large sample."""
    trials = read(proposals(3), list(results(3)), series(3, length=400))
    assert [trial.episodes for trial in trials.kept] == [40, 41, 42]


def test_the_sharpe_is_the_one_the_backtest_reported():
    """Taken from the statistics the node registered rather than recomputed,
    so the figure a gate judges is the figure the run printed."""
    trials = read(proposals(3), list(results(3)), series(3))
    assert trials.sharpes() == pytest.approx((0.0, 0.1, 0.2))
    assert trials.best().sharpe == pytest.approx(0.2)


# -------------------------------------------------------------- the delivery


def test_delivering_leaves_the_other_candidates_alone():
    """The live node owns this file and is writing to it on its own timer, so
    a discovery run that wrote a fresh ladder would drop every leg the node is
    running along with its rung and its episode count."""
    running = Candidate(name="SurpriseEdge-GBP/USD-E111", rung=Rung.SMALL, allocation=0.05)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ladder.json"
        Ladder(candidates={running.name: running}, episodes={running.name: 6}).save(path)

        trials = read(proposals(4), list(results(4)), series(4))
        deliver_to(path, "SurpriseEdge-EUR/USD-E580", trials, trials.best(), prior_trials=24)

        back = Ladder.load(path)

    assert sorted(back.candidates) == ["SurpriseEdge-EUR/USD-E580", "SurpriseEdge-GBP/USD-E111"]
    assert back.candidates[running.name].rung is Rung.SMALL
    assert back.candidates[running.name].allocation == 0.05
    assert back.episodes[running.name] == 6


def test_a_delivery_onto_a_missing_file_starts_a_ladder():
    """A first discovery run on a fresh deploy has no ladder to amend, and
    refusing there would make the loop impossible to start."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ladder.json"
        trials = read(proposals(4), list(results(4)), series(4))
        decision = deliver_to(path, "SurpriseEdge-EUR/USD-E580", trials, trials.best())
        back = Ladder.load(path)

    assert decision.action == "delivered"
    assert "SurpriseEdge-EUR/USD-E580" in back.candidates


def test_a_gate_that_passes_on_too_few_trades_is_still_held():
    """**The case the desk is actually in.** The stand-in results here carry
    43 closed positions, which is what the real catalogue produces for this
    rule over its 76 days, and a deflated Sharpe computed on 43 trades passes
    comfortably. `underpowered` is what stops it: a pass under 200 episodes is
    reported as a pass *and* as a hold, so a candidate cannot reach capital on
    a sample too short to have measured anything.

    This is the gate between a backtest that ran and a backtest that means
    something, and it is the one most worth not losing.
    """
    trials = read(proposals(4), list(results(4)), series(4))
    gate = gate_from(trials, trials.best())
    assert gate.episodes == 43
    assert gate.verdict()[0] is True, "the deflation itself passes on 43 trades"

    candidate = Candidate(name="SurpriseEdge-EUR/USD-E580")
    candidate.gates.append(gate)
    assert candidate.blocking() == ["backtest: passed on 43 episodes, under 200"]


def test_the_origin_defaults_to_the_sweep_that_found_it():
    """A candidate whose origin cannot be stated cannot be reproduced or
    defended, so the delivery supplies one rather than leaving it blank."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ladder.json"
        trials = read(proposals(4), list(results(4)), series(4))
        deliver_to(path, "SurpriseEdge-EUR/USD-E580", trials, trials.best())
        origin = Ladder.load(path).candidates["SurpriseEdge-EUR/USD-E580"].origin

    assert "candidate 3" in origin
    assert "4 trials" in origin


def test_a_trial_keeps_its_result_so_a_decision_can_be_reread():
    """The result object stays on the trial rather than being reduced to a
    Sharpe, because a candidate that comes back round is reviewed on what the
    run actually produced."""
    trials = read(proposals(2), list(results(2)), series(2))
    trial = trials.best()
    assert isinstance(trial, Trial)
    assert trial.result.total_positions == 41


# ------------------------------------------------- PSR is the standard, DSR secondary


def test_a_gate_is_decided_by_the_probabilistic_sharpe():
    """**PSR gates and DSR is reported beside it.**

    A deflated Sharpe needs `trial_sharpes` - the readings of everything the
    search rejected - which most callers do not keep, and the gate used to fall
    through to a bare boolean when they were missing. That verdict carried no
    sample size at all. PSR needs only the candidate's own returns, so it
    applies on every path, and the reason string now names it.
    """
    from till_infinity.node.promotion import required_psr

    trials = read(proposals(4), list(results(4)), series(4))
    gate = gate_from(trials, trials.best())

    assert gate.probabilistic() is not None
    passed, why = gate.verdict()
    assert f"against {required_psr()}" in why, why
    assert "PSR" in why
    assert passed is (gate.probabilistic() >= required_psr() and gate.deflated() >= 0.60)


def test_a_gate_with_too_few_returns_says_so_rather_than_inventing_a_psr():
    """Below four returns the third and fourth moments are not estimable, and a
    PSR computed from them would be a number rather than an estimate."""
    trials = read(proposals(4), list(results(4)))
    gate = gate_from(trials, trials.best())

    assert gate.probabilistic() is None
    passed, why = gate.verdict()
    assert passed is False
    assert "four are needed" in why, why


def test_a_strong_psr_does_not_excuse_a_deflated_sharpe_below_its_floor():
    """**The control that keeps the multiple-testing defence.** PSR asks
    whether the record is long enough to mean something; DSR asks whether it is
    simply the best of a wide search. Clearing one does not answer the other,
    so a gate that can be asked both is asked both - and a candidate with a
    fine PSR and a DSR under the floor must still fail."""
    from till_infinity.node.promotion import Gate, required_dsr

    # A **modest** per-period Sharpe over a long record: 0.001 mean against a
    # 0.01 standard deviation is 0.1 a period, which over a thousand periods
    # puts PSR past 0.99. The first draft used returns with a per-period Sharpe
    # of about 123, which no deflation can touch and which proved nothing.
    rows = tuple(0.011 if i % 2 else -0.009 for i in range(1000))
    # A search wide enough that its expected best beats the candidate.
    wide = tuple(x / 10.0 for x in range(40))
    gate = Gate(
        name="wide-search",
        criterion="mean",
        control="shuffle",
        candidates=39,
        passed=True,
        episodes=400,
        trial_sharpes=wide,
        returns=rows,
    )

    assert gate.probabilistic() > 0.99, "the returns were meant to be unambiguous"
    dsr = gate.deflated()
    assert dsr is not None, "the search was meant to be wide enough to deflate"
    assert dsr < required_dsr(), f"the spread did not bite: {dsr}"
    passed, why = gate.verdict()
    assert passed is False
    assert "DSR" in why, why
    assert "did not" in why, why
