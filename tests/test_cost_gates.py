"""The two cost limits, and the band between them that used to be free.

This desk had four and only the unmeasured one fired.

`SurpriseProfile.cost_share` and `deciding.COST_SHARE`, both 0.10 of the
**target**, are the two that run. `Envelope.max_spread_risk_fraction` at 0.16
of the **risk** and `max_spread_fraction` at 0.25 of the target are read only
inside `Guard.allows`, which has no production caller, and
`DeskConfig.max_spread_vol` at 0.5 volatility units is read by nothing at all.
So the limit that refused trades was the one with no measurement behind it -
and `deciding.py` named `surprise.py` as the place it was measured while
`surprise.py` named nothing.

**The denominator is the finding.** `risk/guard.py` records it: *49 trades
passed the reward test while expensive against the risk, at -0.471R and 53%
stopped, for -502.70.* A permitted spread that scales with the target lets a
distant target buy the right to pay more; a spread that is half the stop
distance is half the stop distance wherever the target sits.

On the geometry both rules use - a 2-volatility stop and a 2R target - the two
limits are **0.32** and **0.40** volatility units, and everything between them
is a trade that passed. That band is what these tests are about.
"""

from __future__ import annotations

import pytest

from till_infinity.domain import costs
from till_infinity.domain.models import Intent, Refusal, Side, Tick
from till_infinity.strategies.config import Settings
from till_infinity.strategies.surprise import Surprise, SurpriseProfile

#: One volatility unit at a price of 1.10 and `vol_bps` 4.0, which is the
#: median 15m eurusd reading on the recorded bars.
ENTRY = 1.10
VOL_BPS = 4.0
UNIT = VOL_BPS / 1e4 * ENTRY

#: What each limit permits, in volatility units, at `stop_vol` 2 and
#: `target_r` 2: risk is 2 units and reward is 4.
RISK_LIMIT = 0.16 * 2
REWARD_LIMIT = 0.10 * 2 * 2


def test_the_number_has_one_home():
    """It had three and they disagreed about which denominator they were on.
    `Settings` defaults from `domain/costs.py` now, and `Envelope` projects
    that, so `TRADING_MAX_SPREAD_RISK_FRACTION` still moves it and there is one
    value to change."""
    assert Settings().max_spread_risk_fraction == costs.MAX_SPREAD_RISK_FRACTION
    assert Settings().envelope().max_spread_risk_fraction == costs.MAX_SPREAD_RISK_FRACTION


def test_the_two_limits_are_a_third_and_two_fifths_of_a_volatility_unit():
    """Stated as the arithmetic rather than as the configured fractions,
    because the fractions are on different denominators and comparing them
    directly is the mistake that left the looser one in charge."""
    measured, looser = RISK_LIMIT, REWARD_LIMIT
    assert measured == pytest.approx(0.32)
    assert looser == pytest.approx(0.40)
    assert measured < looser, "the measured limit is the tighter of the two"


@pytest.mark.parametrize(
    ("share", "refused"),
    [(0.20, False), (0.31, False), (0.33, True), (0.39, True), (0.45, True)],
)
def test_the_risk_limit_refuses_the_band_the_reward_limit_passed(share, refused):
    """**The band is 0.32 to 0.40 volatility units and it was free.**

    A round trip of 0.35 units is 35% of a 2-volatility stop and 17.5% of a 2R
    target, so it passed a 10%-of-target test and failed a 16%-of-risk one.
    Those are the 49 trades.
    """
    found = costs.too_expensive(share * UNIT, 2 * UNIT)
    assert bool(found) is refused
    if refused:
        assert "of the risk" in found


def test_a_missing_quote_and_a_stop_at_the_entry_are_other_gates_reasons():
    """Affordable rather than refused, which is about the tally and not about
    permissiveness. Both conditions have their own gate upstream -
    `Desk._undealable` for the quote and the volatility check for the stop - and
    a trade attributed to the wrong gate is a per-gate count that cannot be
    read, which is the whole reason the counts exist."""
    assert costs.too_expensive(0.0, 2 * UNIT) == ""
    assert costs.too_expensive(0.0001, 0.0) == ""
    assert costs.too_expensive(0.0001, 2 * UNIT, limit=0.0) == "", "zero disables it"


def test_the_reason_carries_the_share_and_the_limit():
    """A refusal a person cannot act on is a refusal they will switch off. The
    share says how far over it was and the limit says what it was judged
    against, so the next decision is whether to drop the instrument rather
    than whether to re-refuse one signal."""
    # 0.8 of a unit against a 2-unit stop is 40% of the risk. The share is
    # against the risk and the threshold is in units, which is exactly the
    # confusion that let two limits on two denominators be compared directly.
    found = costs.too_expensive(0.80 * UNIT, 2 * UNIT)
    assert "40% of the risk" in found
    assert "limit is 16%" in found


# ----------------------------------------------------- through the real rule


class Standing(Surprise):
    """`Surprise` over a stand-in for the desk it mixes into.

    A stand-in rather than a `BacktestEngine` because `Surprise` is a mixin
    with **no base** - that is the design, so a decision and an entry stay
    independent - and `decide` reads exactly two things off whatever it is
    composed with. The method under test is the real one.
    """

    profile = SurpriseProfile.__new__(SurpriseProfile)

    def __init__(self, spread: float) -> None:
        half = spread / 2.0
        self._quote = Tick(symbol="EURUSD", bid=ENTRY - half, ask=ENTRY + half, time=0.0)

    def _tick(self) -> Tick:
        return self._quote

    def _spec(self):
        return None


def proposal() -> dict:
    return {
        "feed": "eurusd",
        "shape": "statespace",
        "interval": "5m",
        "direction": 1,
        "features": {"surprise": 4.2, "vol_bps": VOL_BPS, "stop_vol": 2.0, "target_r": 2.0},
    }


def test_the_rule_refuses_at_spread_risk_in_the_band():
    """The gate reaches a real `decide`, under the name `Guard.allows` already
    uses - so a tally from the decision layer and one from the account layer
    count the same thing."""
    verdict = Standing(0.35 * UNIT).decide(proposal())
    assert isinstance(verdict, Refusal)
    assert verdict.gate == "spread_risk"
    assert verdict.feed == "eurusd"


def test_the_rule_still_refuses_the_dearest_round_trips_on_the_target():
    """The looser limit keeps its own gate name, because the two answer
    different questions and a tally that merged them could not say which
    denominator did the refusing."""
    verdict = Standing(0.60 * UNIT).decide(proposal())
    assert isinstance(verdict, Refusal)
    assert verdict.gate == "cost"


def test_the_tally_carries_the_cost_arithmetic_whichever_gate_bound():
    """**One line at INFO would have saved a whole diagnosis.**

    On 2026-11-07 the live desk refused two of two proposals on `cost` and
    nothing at INFO carried the numbers, so which side of the inequality the
    refusal sat on had to be inferred from tally ordering and a 5.7-year
    volatility estimate off a different data source. The two gates use
    different denominators - the target and the risk - so a reader needs both
    ratios and both limits to know which one bound.

    The **tally** rather than a log line, because refusals are hundreds a day
    by design, which is exactly why `Desk.consider` records them at debug, and
    this desk has already filled a log with 38,748 lines in one deploy.
    """
    dear = Standing(0.60 * UNIT)
    assert dear.decide(proposal()).gate == "cost"

    extra = dear._tally_extra()
    assert "of target" in extra, extra
    assert "of risk" in extra, extra
    # Both limits named, so the line says what it was measured against.
    assert "limit" in extra
    assert extra.count("limit") == 2, extra


def test_a_desk_that_has_priced_nothing_reports_nothing():
    """Absent is not zero. A tally reading "0% of target" on a desk that never
    saw a quote is a measurement of nothing presented as a measurement - the
    failure the `{}`-not-zeros rule exists for."""
    assert Standing(0.10 * UNIT)._tally_extra() == ""


def test_a_cheap_round_trip_still_becomes_a_trade():
    """The control. A gate added to the money path has to be shown to let
    something through, or the 40% it refuses is indistinguishable from 100%."""
    verdict = Standing(0.10 * UNIT).decide(proposal())
    assert isinstance(verdict, Intent)
    assert verdict.side is Side.BUY
    assert verdict.volume == 0.0, "sizing happens in Desk.consider, not here"
