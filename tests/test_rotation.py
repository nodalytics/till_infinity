"""The sample a live leg is judged on, and what may take it off the node.

The desk this is for is a basket of legs that each earned their place and each
lose it: `smc_bos_c_L50` on gold at M15 looks profitable now, will stop, and
something a discovery run found should take its slot. `node/promotion.py` has
had the ladder for that since it was written - `Rung`, `Retirement`, `retire`,
`revive` - and three things it needed were missing.

**The sample was not fixed when a rung was entered**, though `decide_after`'s
own docstring said it was. `promote` moved the rung and left the field alone,
so a candidate carried one number from discovery to full capital. The direction
that matters is a short sample surviving the climb: the decision made with the
whole account would then be made on the sample chosen for a 5% one.

**Ten episodes is the live sample now, and it is an exploration budget rather
than a validation.** The best per-trade edge this desk has measured is
`+0.1436R +/- 0.0485 over 905 trades at t 2.96`, a per-trade Sharpe of about
0.098 - so ten episodes of exactly that edge reads t 0.31, and reaching t 2
would take about 417. Ten cannot separate a working leg from a dead one. What
it decides is whether to spend 5% of the account finding out, which is a
question a short sample can answer and a different question from whether the
edge is real.

**And the retirement side had no way to produce evidence.** `may_retire`
demands it for every reason but `MANUAL`, correctly, and nothing built any -
so the only reachable rotation was a person deciding. The gap mattered because
of what fills it badly: `strategy-rotation-is-not-timeable` is measured here,
every pause rule tested matched random pausing at the same duty cycle, so "it
has been losing" is the one criterion already known to be worth nothing.
"""

from __future__ import annotations

import pytest

from till_infinity.node import promotion
from till_infinity.node.promotion import (
    LIVE_EPISODES,
    MIN_EPISODES,
    Allocation,
    Candidate,
    Gate,
    Retirement,
    Rung,
    book_evidence,
    live_episodes,
    may_retire,
    promote,
    required_dsr,
    retire,
    revive,
    sample_for,
)


def passing(episodes: int = MIN_EPISODES) -> Gate:
    """A gate that passes without a deflated Sharpe, so a test can vary one
    thing. `verdict` falls back to `passed` when it was not given the trials
    and returns a DSR needs."""
    return Gate(
        name="walk-forward",
        criterion="Sharpe",
        control="walk",
        # One candidate, because this gate stands in for a pre-registered test
        # rather than a search - the deflation is exercised in `test_dsr.py`.
        candidates=1,
        passed=True,
        episodes=episodes,
    )


def ready(rung: Rung = Rung.BACKTESTED, episodes: int = MIN_EPISODES) -> Candidate:
    return Candidate(name="smc_bos_c_L50", rung=rung, gates=[passing(episodes)])


# ------------------------------------------------------------- the live sample


def test_the_live_sample_is_ten_and_the_backtest_bar_is_not():
    """They govern different decisions and conflating them is the mistake this
    guards. A backtest episode is cheap, so the gate before money is risked
    keeps its power bar; a live episode costs a trade."""
    assert LIVE_EPISODES == 10
    assert sample_for(Rung.SMALL) == 10
    assert sample_for(Rung.FULL) == 10
    assert sample_for(Rung.BACKTESTED) == MIN_EPISODES


def test_the_sample_can_be_raised(monkeypatch):
    """The supported direction. Every statistical argument favours more, so
    there is no ceiling here and no warning for a large value."""
    monkeypatch.setenv("TRADING_LIVE_EPISODES", "50")
    assert live_episodes() == 50
    assert sample_for(Rung.SMALL) == 50


def test_a_sample_of_zero_is_refused():
    """A rung whose sample is zero promotes on the first episode, which is not
    a sample. Refused rather than floored, because a deploy that asked for it
    believes something that is not true."""
    for bad in ("0", "-3"):
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("TRADING_LIVE_EPISODES", bad)
            with pytest.raises(ValueError, match="no episodes at all"):
                live_episodes()


def test_the_sample_is_fixed_when_the_rung_is_entered():
    """**The field claimed this and nothing did it.** A candidate promoted into
    small capital was handed the 200-episode backtest sample, so a leg that was
    meant to be reviewed after ten would not be looked at again for two
    hundred - and one built by hand with a short sample kept it to full
    capital, which is the same bug pointing at the whole account."""
    candidate = ready()
    assert candidate.decide_after == MIN_EPISODES

    promote(candidate, Allocation(), episodes_seen=MIN_EPISODES)
    assert candidate.rung is Rung.SMALL
    assert candidate.decide_after == LIVE_EPISODES

    promote(candidate, Allocation(), episodes_seen=LIVE_EPISODES)
    assert candidate.rung is Rung.FULL
    assert candidate.decide_after == LIVE_EPISODES


def test_a_leg_reaches_small_capital_on_ten_live_episodes():
    """What the short sample buys, stated as the thing it actually permits: a
    bounded amount spent finding out. `Allocation.small` is the bound."""
    candidate = ready()
    promote(candidate, Allocation(), episodes_seen=MIN_EPISODES)
    assert candidate.allocation == pytest.approx(0.05)

    held = ready(rung=Rung.SMALL)
    held.decide_after = LIVE_EPISODES
    ok, why = promotion.may_promote(held, episodes_seen=9)
    assert not ok
    assert "9 of 10 episodes" in why


def test_stopping_early_is_still_choosing():
    """The sample is pre-registered whatever its size. Ten episodes read until
    the eighth looks good is not a ten-episode sample."""
    candidate = ready(rung=Rung.SMALL)
    candidate.decide_after = LIVE_EPISODES
    ok, why = promotion.may_promote(candidate, episodes_seen=3)
    assert not ok
    assert "fixed when this rung was entered" in why


# ----------------------------------------------------------------- the gates


def test_the_deflated_sharpe_bar_can_be_moved_and_stays_a_probability(monkeypatch):
    """Movable because a looser bar on a bounded allocation is a decision
    somebody may make. Bounded to (0, 1) because the deflated Sharpe **is** a
    probability, and a threshold outside that range is not a weaker gate - it
    is a gate that always passes or never does."""
    assert required_dsr() == pytest.approx(0.95)
    monkeypatch.setenv("TRADING_DSR_REQUIRED", "0.90")
    assert required_dsr() == pytest.approx(0.90)
    for bad in ("1.0", "0", "-0.5", "95"):
        monkeypatch.setenv("TRADING_DSR_REQUIRED", bad)
        with pytest.raises(ValueError, match="not a probability"):
            required_dsr()


def test_the_gate_reports_the_bar_it_was_judged_against(monkeypatch):
    """A verdict naming a threshold the deploy did not use is a record nobody
    can review, which is the whole reason every decision here carries its
    reason."""
    monkeypatch.setenv("TRADING_DSR_REQUIRED", "0.80")
    gate = Gate(
        name="walk-forward",
        criterion="Sharpe",
        control="walk",
        candidates=3,
        episodes=MIN_EPISODES,
        trial_sharpes=(0.1, 0.2, 0.3),
        returns=(0.01, -0.004, 0.02, 0.005, -0.001, 0.013),
    )
    _, why = gate.verdict()
    assert "against 0.8" in why


def test_the_short_live_sample_does_not_touch_the_gate():
    """They are two decisions and the gate's returns come from the backtest,
    where episodes are cheap. Lowering the statistical bar because a live
    sample is short would leave a number that still prints as a probability and
    no longer is one."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("TRADING_LIVE_EPISODES", "10")
    try:
        assert required_dsr() == pytest.approx(Gate.DSR_REQUIRED)
    finally:
        monkeypatch.undo()


# ------------------------------------------------------------- the retirement


def test_a_short_sample_is_not_evidence_for_retiring_anything():
    """**The finding this has to beat.** Every pause rule tested on this desk
    matched random pausing at the same duty cycle, so a leg losing to the book
    over a handful of episodes is the sample being short. An empty string is
    what `may_retire` reads as no evidence, so the refusal is by
    construction rather than by a caller remembering."""
    assert book_evidence(-0.8, episodes=9) == ""


def test_a_leg_losing_to_the_book_over_the_sample_is_evidence():
    """And it is deflated, which is what makes it a reason rather than a mood:
    the number already confronts how many legs were compared to find the worst
    one. Comparing twenty legs and retiring the worst is a search."""
    found = book_evidence(-0.4, episodes=12)
    assert "deflated information ratio -0.400" in found
    assert "12 episodes" in found


def test_a_leg_beating_the_book_is_never_evidence():
    """The floor is the book, not zero profit. A leg that is up and behind the
    book is a different decision from a leg that is losing, and only the
    second is a refutation."""
    assert book_evidence(0.2, episodes=400) == ""
    assert book_evidence(0.0, episodes=400) == ""


def test_the_evidence_actually_satisfies_the_retirement_it_is_for():
    """The pairing, end to end: the function produces what `may_retire`
    demands, and a retired leg returns to the backtest rung rather than to
    nothing - so reviving it means passing the gate again rather than arguing
    from memory."""
    candidate = ready(rung=Rung.SMALL)
    ok, _ = may_retire(candidate, Retirement.REFUTED, evidence=book_evidence(-0.4, episodes=12))
    assert ok

    retire(candidate, Retirement.REFUTED, evidence=book_evidence(-0.4, episodes=12))
    assert candidate.rung is Rung.RETIRED
    assert candidate.allocation == 0.0

    revive(candidate)
    assert candidate.rung is Rung.BACKTESTED
    assert candidate.gates == []


def test_a_replacement_still_needs_its_own_gate():
    """The rotation the desk wants - one leg out, a discovery in - runs through
    `SUPERSEDED`, and that reason needs the replacement's gate result. Without
    it the rotation is a preference, and preferring the newer thing is how
    rotation gets timed."""
    candidate = ready(rung=Rung.FULL)
    ok, why = may_retire(candidate, Retirement.SUPERSEDED, evidence="the new one looks better")
    assert not ok
    assert "replacement's own gate result" in why

    ok, _ = may_retire(
        candidate,
        Retirement.SUPERSEDED,
        evidence="smc_fvg_M15 passed its walk-forward gate at DSR 0.971",
    )
    assert ok
