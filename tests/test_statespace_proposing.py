"""Statespace as a producer of trading signals.

The tests that matter are the ones about the **sign** and the **vocabulary**.
This service folds log variance, so a directional field or a directional word
sourced from the readout would be a price claim made by a variance model -
the error already corrected twice in this package, where `side` became
`variance_side` and the alert kind `break` became `surprise`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pytest

from till_infinity.actors.statespace import proposing


@dataclass
class _Reach:
    low: float = -1.0
    high: float = 1.0
    coverage: float = 0.9
    source: str = "anchored"


@dataclass
class _Readout:
    """Only what `proposing` reads, so a field it does not read cannot pass."""

    feed: str = "eurusd"
    interval: str = "5m"
    at: float = 1_700_000_000.0
    #: log variance. exp(value / 2) is a return standard deviation.
    value: float = 2.0 * math.log(1e-4)
    spread: float = 0.05
    surprise: float = 4.0
    stretch: float = 0.3
    _barrier: dict[str, float] | None = field(default_factory=lambda: {"probability": 0.42})

    def covering(self, coverage: float) -> _Reach:
        return _Reach()

    def barrier(self, probability: float, horizon: float):
        return self._barrier


def _bar(opened: float = 1.1000, closed: float = 1.1010) -> dict:
    return {"open": opened, "close": closed, "high": 1.1012, "low": 1.0999}


class TestVolatility:
    def test_it_is_the_folded_log_variance_in_basis_points(self) -> None:
        """`exp(value / 2) * 1e4`, and nothing converts a spread column."""
        got = proposing.volatility_bps(_Readout(value=2.0 * math.log(1e-4)))
        assert got == pytest.approx(1.0)

    def test_it_scales_with_the_variance_not_the_spread(self) -> None:
        quiet = proposing.volatility_bps(_Readout(value=2.0 * math.log(5e-5)))
        loud = proposing.volatility_bps(_Readout(value=2.0 * math.log(2e-4)))
        assert quiet < 1.0 < loud
        assert loud / quiet == pytest.approx(4.0)


class TestDirection:
    def test_the_sign_is_the_bar_body(self) -> None:
        assert proposing.direction_of(_bar(1.10, 1.11)) == 1
        assert proposing.direction_of(_bar(1.11, 1.10)) == -1

    def test_a_doji_takes_no_side_rather_than_defaulting_long(self) -> None:
        """`0` lets the caller drop the proposal instead of inventing a side."""
        assert proposing.direction_of(_bar(1.10, 1.10)) == 0

    def test_unparseable_input_takes_no_side(self) -> None:
        assert proposing.direction_of({"open": "x", "close": 1.0}) == 0
        assert proposing.direction_of({}) == 0


class TestProposal:
    def test_a_quiet_bar_is_not_a_proposal(self) -> None:
        assert proposing.proposal_for(_Readout(surprise=1.0), _bar()) is None

    def test_a_doji_is_not_a_proposal_however_surprising(self) -> None:
        assert proposing.proposal_for(_Readout(surprise=9.0), _bar(1.10, 1.10)) is None

    def test_it_fires_on_either_sign_of_surprise(self) -> None:
        """`surprise` is signed and the trigger is on its magnitude.

        A variance surprise downward is as much a surprise as one upward, and
        the side comes from the bar either way - so an absolute threshold here
        is the point, not an oversight.
        """
        for value in (4.0, -4.0):
            got = proposing.proposal_for(_Readout(surprise=value), _bar())
            assert got is not None
            assert got["direction"] == 1

    def test_it_emits_the_signal_contract_not_an_intent(self) -> None:
        """The strategies build the Intent; this must speak their input."""
        got = proposing.proposal_for(_Readout(), _bar())
        assert got is not None
        for key in ("feed", "interval", "time", "direction", "shape", "features"):
            assert key in got
        # Not an Intent: no side/entry/stop/target/volume at the top level.
        for absent in ("entry", "stop", "target", "volume", "side", "symbol"):
            assert absent not in got

    def test_the_shape_matches_what_the_filter_and_agents_use(self) -> None:
        """One word in three places, or a card renders as the wrong shape.

        `NOTIFY_SHAPES` silently dropped every statespace alert while the path
        itself worked, because the allowlist did not carry this string.
        """
        got = proposing.proposal_for(_Readout(), _bar())
        assert got is not None
        assert got["shape"] == "statespace"

    def test_it_reports_the_honest_base_rate_below_the_desk_floor(self) -> None:
        """0.50 against a configured `TRADING_MIN_BASE_RATE` of 0.51.

        Direction is a coin on this service - 0.50150 over 7,728,858 rows - so
        reporting 0.51 would be clearing a gate rather than measuring. The
        consequence is that the desk as configured refuses these proposals,
        which is a fact about the gates and is meant to be visible.
        """
        got = proposing.proposal_for(_Readout(), _bar())
        assert got is not None
        assert got["features"]["base_rate_up"] == 0.5
        assert got["features"]["base_rate_up"] < 0.51

    def test_the_probability_is_a_touch_probability_in_range(self) -> None:
        got = proposing.proposal_for(_Readout(), _bar())
        assert got is not None
        assert 0.0 <= got["features"]["probability"] <= 1.0

    def test_an_infeasible_barrier_does_not_stop_a_proposal(self) -> None:
        """`barrier` returns None when the geometry is unreachable."""
        got = proposing.proposal_for(_Readout(_barrier=None), _bar())
        assert got is not None
        assert got["features"]["probability"] == 0.0

    def test_a_raising_barrier_does_not_take_the_service_down(self) -> None:
        class Angry(_Readout):
            def barrier(self, probability: float, horizon: float):
                raise RuntimeError("no")

        got = proposing.proposal_for(Angry(), _bar())
        assert got is not None
        assert got["features"]["probability"] == 0.0

    def test_vol_bps_is_published_because_three_strategies_read_it(self) -> None:
        got = proposing.proposal_for(_Readout(), _bar())
        assert got is not None
        assert got["features"]["vol_bps"] > 0

    def test_a_degenerate_variance_is_refused_rather_than_published(self) -> None:
        got = proposing.proposal_for(_Readout(value=-1e9), _bar())
        assert got is None

    def test_the_detail_carries_no_directional_word(self) -> None:
        """The same ban the alert line carries, for the same reason."""
        for bar in (_bar(1.10, 1.11), _bar(1.11, 1.10)):
            got = proposing.proposal_for(_Readout(), bar)
            assert got is not None
            line = str(got["detail"]).lower()
            for word in ("up", "down", "bull", "bear", "long", "short", "buy", "sell"):
                assert word not in line.replace("lower", "").replace("higher", "")

    def test_the_detail_says_what_printed_and_how_big(self) -> None:
        got = proposing.proposal_for(_Readout(surprise=4.0), _bar())
        assert got is not None
        line = str(got["detail"])
        assert "4.0 times" in line
        assert "bp" in line

    def test_the_topic_is_not_the_structures_one(self) -> None:
        """Two producers on a topic named after one of them loses the trail."""
        assert proposing.TOPIC == "statespace.proposals"
        assert "structures" not in proposing.TOPIC


class TestTheTopicAgrees:
    """Three places name this topic, and a mismatch is a silent drop.

    `NOTIFY_SHAPES` already demonstrated the failure mode: the whole
    statespace alert path worked and every card was discarded because one
    allowlist did not carry the string.
    """

    def test_the_bus_the_service_and_the_producer_agree(self) -> None:
        from till_infinity.actors.statespace.service import PROPOSES
        from till_infinity.bus import PROPOSALS

        assert proposing.TOPIC == PROPOSALS == PROPOSES

    def test_it_is_not_the_signals_topic(self) -> None:
        from till_infinity.bus import PROPOSALS, SIGNALS

        assert PROPOSALS != SIGNALS


class TestTheServicePublishes:
    """A producer shipped switched off is no witness that it works."""

    def test_the_flag_is_on_by_default(self) -> None:
        from till_infinity.actors.statespace.config import Settings

        assert Settings().proposals is True

    def test_the_counter_is_reported(self) -> None:
        """`report` is the only witness in a container that runs at INFO."""
        from till_infinity.actors.statespace.config import Settings
        from till_infinity.actors.statespace.engine import Engine
        from till_infinity.actors.statespace.service import Watcher

        watcher = Watcher(engine=Engine(Settings()))
        watcher.proposed = 7
        line = watcher.report(at=1e12)
        assert "7 proposed" in line
