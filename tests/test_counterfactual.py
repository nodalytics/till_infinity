"""What would have happened to the trades the desk did not take.

Tested harder than its size suggests, because **every failure here is silent**.
A counterfactual that lapses still prints a number; it just prints one computed
from a search that looks smaller and more uniformly good than it was, which
makes every deflated Sharpe on the desk optimistic. So these tests are mostly
about the ways it could quietly stop counting, or count the wrong thing.
"""

from __future__ import annotations

import pytest

from till_infinity.domain.models import Intent, Side
from till_infinity.strategies.counterfactual import Counterfactual, Resolved

HOLD = 3_600.0


def intent(**kwargs) -> Intent:
    base = {
        "feed": "eurusd",
        "symbol": "EUR/USD",
        "side": Side.BUY,
        "volume": 100_000.0,
        "entry": 1.1000,
        "stop": 1.0950,
        "target": 1.1100,
        "interval": "15m",
    }
    return Intent(**(base | kwargs))


def book(**kwargs) -> Counterfactual:
    return Counterfactual(**kwargs)


# ---------------------------------------------------------------- the untaken


def test_a_wanted_trade_is_followed_to_its_target():
    """The happy path, and the one that fixes the sign convention: a reward of
    +2.0 is the 100-pip target over the 50-pip risk, so R is read off the stop
    distance rather than off the entry price."""
    got = book()
    got.wanted(intent(), by="edge", now=0.0, hold=HOLD)
    # Fills: a buy pays the ask, so the ask has to reach the entry.
    assert got.observe("eurusd", 1.09980, 1.10000, now=10.0) == []
    # Then the bid reaches the target.
    done = got.observe("eurusd", 1.11000, 1.11020, now=100.0)
    assert len(done) == 1
    assert done[0].how == "target"
    assert done[0].reward == pytest.approx(2.0), "100 pips reward on 50 pips risk"


def test_a_wanted_trade_that_stops_is_recorded_at_minus_one():
    """Exactly -1.0 by definition, since R is denominated in the stop. A
    stopped counterfactual recorded at its price distance instead would make
    wide-stop strategies look like they lose less."""
    got = book()
    got.wanted(intent(), by="edge", now=0.0, hold=HOLD)
    got.observe("eurusd", 1.09980, 1.10000, now=10.0)
    done = got.observe("eurusd", 1.09500, 1.09520, now=100.0)
    assert done[0].how == "stop"
    assert done[0].reward == -1.0


def test_a_fill_is_never_assumed():
    """Crediting a rested entry with a price it never traded at would rank it
    above strategies that paid the spread to be certain - which is the
    comparison the whole record exists to make."""
    got = book()
    got.wanted(intent(entry=1.0990), by="rest", now=0.0, hold=HOLD)
    # The ask gets to 1.0991 - one pip short. Nothing fills.
    assert got.observe("eurusd", 1.09890, 1.09910, now=10.0) == []
    assert got.following == 1
    # And after the fill window it is recorded as never filled, not as a loss.
    done = got.observe("eurusd", 1.09890, 1.09910, now=HOLD + 1.0)
    assert done[0].how == "never filled"
    assert done[0].reward == 0.0


def test_both_sides_are_paid_as_a_real_trade_would_pay_them():
    """A counterfactual filled at the mid and exited at the mid is a strategy
    that never paid a spread, and it will beat every real one."""
    got = book()
    got.wanted(intent(), by="edge", now=0.0, hold=HOLD)
    # The mid is at the entry but the ask is not: no fill.
    assert got.observe("eurusd", 1.09950, 1.10050, now=10.0) == []
    # The ask reaching it fills.
    assert got.observe("eurusd", 1.09900, 1.10000, now=20.0) == []
    # The mid is at the target but the bid is not: no target.
    assert got.observe("eurusd", 1.10950, 1.11050, now=30.0) == []
    done = got.observe("eurusd", 1.11000, 1.11100, now=40.0)
    assert done[0].how == "target"


def test_a_timeout_is_marked_to_market_rather_than_dropped():
    got = book()
    got.wanted(intent(), by="edge", now=0.0, hold=HOLD)
    got.observe("eurusd", 1.09980, 1.10000, now=10.0)
    # Half way to the target when the hold runs out.
    done = got.observe("eurusd", 1.10250, 1.10270, now=HOLD + 20.0)
    assert done[0].how == "timeout"
    assert done[0].reward == pytest.approx(0.5), "25 pips on 50 pips of risk"


def test_a_short_is_followed_on_the_other_sides():
    """The side that gets written second and tested less. Every comparison is
    bid-against-ask, so a short that reuses the long's sides is credited with
    the spread twice instead of paying it twice."""
    got = book()
    got.wanted(
        intent(side=Side.SELL, entry=1.1000, stop=1.1050, target=1.0900),
        by="edge",
        now=0.0,
        hold=HOLD,
    )
    # A sell pays the bid, so the bid has to reach the entry.
    assert got.observe("eurusd", 1.09980, 1.10000, now=10.0) == []
    assert got.observe("eurusd", 1.10000, 1.10020, now=20.0) == []
    # Closed at the ask, so the ask reaches the target.
    done = got.observe("eurusd", 1.08980, 1.09000, now=30.0)
    assert done[0].how == "target"
    assert done[0].reward == pytest.approx(2.0)


def test_a_trade_with_no_risk_is_not_followed_at_all():
    """An R with a zero denominator is not a small number, it is not a number."""
    got = book()
    assert got.wanted(intent(stop=1.1000), by="edge", now=0.0, hold=HOLD) is None
    assert got.following == 0


def test_the_regime_is_carried_so_the_conditional_question_can_be_asked():
    """`research/choosing.md` measured 536 of these and could not ask the
    interesting version: strategies could be alike pooled and separate cleanly
    within a state. It could not be asked "because `regime` is on every level
    call and was dropped here"."""
    got = book()
    got.wanted(intent(), by="edge", now=0.0, hold=HOLD, regime=0.8, market="trending")
    got.observe("eurusd", 1.09980, 1.10000, now=10.0)
    done = got.observe("eurusd", 1.11000, 1.11020, now=100.0)
    assert done[0].regime == 0.8
    assert done[0].market == "trending"


def test_records_split_by_market_and_by_strategy():
    """Both cuts, because the interesting question is the conditional one and
    `pooled-medians-invert-subgroups` is what asking it pooled costs. An empty
    input is an empty dict rather than an absent key."""
    rows = [
        Resolved(
            shape="untaken", feed="f", by="a", how="stop", reward=-1.0, when=0.0, market="quiet"
        ),
        Resolved(
            shape="untaken", feed="f", by="b", how="target", reward=2.0, when=0.0, market="quiet"
        ),
        Resolved(
            shape="untaken", feed="f", by="a", how="target", reward=2.0, when=0.0, market="fast"
        ),
    ]
    assert Counterfactual.by_market(rows) == {"quiet": [-1.0, 2.0], "fast": [2.0]}
    assert Counterfactual.by_strategy(rows) == {"a": [-1.0, 2.0], "b": [2.0]}
    assert Counterfactual.by_market([]) == {}


def test_an_unattributed_record_is_grouped_rather_than_dropped():
    """Dropping it would shrink the recorded search, which is the one thing
    that must not happen quietly."""
    rows = [Resolved(shape="untaken", feed="f", by="", how="stop", reward=-1.0, when=0.0)]
    assert Counterfactual.by_strategy(rows) == {"(unattributed)": [-1.0]}
    assert Counterfactual.by_market(rows) == {"(unknown)": [-1.0]}


# ----------------------------------------------------------------- the shadow


def test_a_stopped_trade_that_reaches_its_target_says_the_stop_cost_a_winner():
    """A stop hit at full size looks the same whether the level failed or the
    stop sat inside the noise. `best_r` above 1 is the difference."""
    got = book()
    got.stopped("p1", intent(), by="edge", now=0.0, hold=HOLD)
    done = got.observe("eurusd", 1.11000, 1.11020, now=100.0)
    assert len(done) == 1
    assert done[0].shape == "shadow"
    assert done[0].how == "reached"
    assert done[0].reward == pytest.approx(2.0)
    assert done[0].extra["cost_a_winner"] is True


def test_a_stopped_trade_that_goes_nowhere_reaches_zero_and_not_a_negative():
    """A trade that never got in front of its entry got nowhere, and a
    negative "how far it reached" would average as progress."""
    got = book()
    got.stopped("p1", intent(), by="edge", now=0.0, hold=HOLD)
    done = got.observe("eurusd", 1.09000, 1.09020, now=HOLD + 10.0)
    assert done[0].how == "never reached"
    assert done[0].reward == 0.0, "clamped, not negative"
    assert done[0].extra["cost_a_winner"] is False


def test_a_shadow_tracks_the_best_it_reached_before_giving_up():
    """From the best it saw, not the last price it was at. A stop that cost a
    winner is only visible in the high-water mark; marking to the final quote
    would report the same number for a trade that went nowhere and one that
    nearly paid."""
    got = book()
    got.stopped("p1", intent(), by="edge", now=0.0, hold=HOLD)
    got.observe("eurusd", 1.10700, 1.10720, now=10.0)
    got.observe("eurusd", 1.10200, 1.10220, now=20.0)
    done = got.observe("eurusd", 1.10200, 1.10220, now=HOLD + 10.0)
    assert done[0].how == "never reached"
    # 70 pips of the 50-pip risk, from the best it saw rather than the last.
    assert done[0].reward == pytest.approx(1.4)
    assert done[0].extra["cost_a_winner"] is True


def test_a_shadow_can_be_forgotten_when_the_position_reopens():
    """Idempotent on purpose. The desk calls `forget` on a reopen and on a
    close, so a second call is a normal event and raising there would take the
    node down for bookkeeping."""
    got = book()
    got.stopped("p1", intent(), by="edge", now=0.0, hold=HOLD)
    assert got.following == 1
    got.forget("p1")
    assert got.following == 0
    got.forget("p1")  # and twice is not an error


def test_another_feeds_quote_resolves_nothing():
    """One book follows every feed at once. A quote matched by time rather
    than by feed would resolve a EURUSD counterfactual on a GBPUSD tick, at a
    price that instrument never traded."""
    got = book()
    got.wanted(intent(), by="edge", now=0.0, hold=HOLD)
    got.stopped("p1", intent(), by="edge", now=0.0, hold=HOLD)
    assert got.observe("gbpusd", 1.11000, 1.11020, now=1e9) == []
    assert got.following == 2, "both are still being followed"


def test_following_counts_both_kinds():
    """The number that must not quietly go to zero."""
    got = book()
    got.wanted(intent(), by="edge", now=0.0, hold=HOLD)
    got.wanted(intent(feed="gbpusd"), by="edge", now=0.0, hold=HOLD)
    got.stopped("p1", intent(), by="edge", now=0.0, hold=HOLD)
    assert got.following == 3
