"""Four ways to size a trade by something other than a fixed fraction.

Every one returns a multiplier and **none can enlarge a position**. That is the
property worth testing hardest: a sizing model that can size up is one that can
turn a measurement error into a margin call, and every input here rests on a
few hundred observations.
"""

from __future__ import annotations

import pytest

from till_infinity.trading import scaling
from till_infinity.trading.models import Side


def held(feed, side=Side.BUY):
    """One open trade, as `crowding` wants it: the feed and the side's sign."""
    return (feed, side.sign)


# ------------------------------------------------------------------ crowding


def test_a_shared_leg_reduces_the_second_position():
    """Long EURUSD and long GBPUSD is one dollar trade in two tickets - they
    will be right together and wrong together."""
    assert scaling.crowding("gbpusd", [held("eurusd")], 0.5) == pytest.approx(0.5)


def test_it_compounds_rather_than_adding():
    """Three positions all short the dollar are not three-halves of one trade,
    they are closer to three of it."""
    book = [held("eurusd"), held("audusd")]
    assert scaling.crowding("gbpusd", book, 0.5) == pytest.approx(0.25)


def test_an_unshared_leg_is_untouched():
    assert scaling.crowding("eurusd", [held("usdjpy", Side.BUY)], 0.5) == 1.0


def test_an_empty_book_changes_nothing():
    assert scaling.crowding("eurusd", [], 0.5) == 1.0


def test_it_is_off_at_zero_and_at_one():
    assert scaling.crowding("gbpusd", [held("eurusd")], 0.0) == 1.0
    assert scaling.crowding("gbpusd", [held("eurusd")], 1.0) == 1.0


def test_an_unmapped_instrument_is_not_penalised():
    """A feed with no exposure leg is unmeasured rather than uncrowded, and
    guessing either way would be inventing a number."""
    assert scaling.crowding("not_a_thing", [held("eurusd")], 0.5) == 1.0


# ---------------------------------------------------------------- volatility


def test_twice_the_volatility_is_half_the_size():
    assert scaling.by_volatility(20.0, 10.0) == pytest.approx(0.5)


def test_a_quiet_instrument_does_not_get_a_bigger_position():
    """Sizing up into calm is how a book discovers the calm was the beginning
    of something. The stop already widens with volatility, so the money at risk
    is constant either way."""
    assert scaling.by_volatility(2.0, 10.0) == 1.0


def test_it_is_off_without_a_target():
    assert scaling.by_volatility(50.0, 0.0) == 1.0


# ---------------------------------------------------------------------- edge


def test_full_size_at_the_full_edge():
    assert scaling.by_edge(0.9, 0.9) == pytest.approx(1.0)


def test_half_the_edge_is_half_the_size():
    assert scaling.by_edge(0.45, 0.9) == pytest.approx(0.5)


def test_a_measured_loss_falls_to_the_floor_rather_than_zero():
    """Refusing is `paying.md`'s job, not a sizing model's - usdcnh at -4.663v
    should be refused by the instrument list, not silently sized to nothing."""
    assert scaling.by_edge(-4.663, 0.9) == scaling.FLOOR


def test_an_unmeasured_instrument_is_not_a_measured_loss():
    assert scaling.by_edge(None, 0.9) == 1.0


def test_a_huge_edge_is_still_capped():
    """Linear and capped is the conservative end of the Kelly family. Full
    Kelly on an edge estimated from fifty touches is a way to be wiped out by
    an estimation error rather than by a market."""
    assert scaling.by_edge(50.0, 0.9) == 1.0


# ------------------------------------------------------------------ drawdown


def test_no_drawdown_is_full_size():
    assert scaling.by_drawdown(10_000.0, 10_000.0, 0.2) == 1.0
    assert scaling.by_drawdown(10_000.0, 11_000.0, 0.2) == 1.0


def test_it_tapers_as_the_drawdown_deepens():
    shallow = scaling.by_drawdown(10_000.0, 9_800.0, 0.2)
    deep = scaling.by_drawdown(10_000.0, 9_000.0, 0.2)
    assert 1.0 > shallow > deep > scaling.FLOOR


def test_the_first_losses_barely_register():
    """Square root rather than linear: a book that tapers hard on a 2% dip
    cannot recover, because it trades a quarter size exactly when the edge it
    was sized for is still there."""
    assert scaling.by_drawdown(10_000.0, 9_800.0, 0.2) > 0.9


def test_at_the_halt_it_is_the_floor():
    assert scaling.by_drawdown(10_000.0, 8_000.0, 0.2) == scaling.FLOOR


def test_it_is_off_without_a_halt():
    assert scaling.by_drawdown(10_000.0, 5_000.0, 0.0) == 1.0


# ------------------------------------------------------------------ together


def test_they_multiply():
    assert scaling.combined(0.5, 0.5) == pytest.approx(0.25)


def test_order_does_not_matter():
    assert scaling.combined(0.5, 0.8, 0.3) == pytest.approx(scaling.combined(0.3, 0.5, 0.8))


def test_nothing_can_enlarge_a_position():
    """The property that matters most. Every input rests on a few hundred
    observations, and a model that can size up can turn an estimation error
    into a margin call."""
    assert scaling.combined(5.0, 3.0) == 1.0


def test_it_never_reaches_zero():
    """A position sized to nothing is a refusal wearing a number, and the
    broker's volume step would round it away anyway."""
    assert scaling.combined(0.0, 0.0) == scaling.FLOOR


# ------------------------------------------------------------- the handover


def test_a_strategy_applies_all_four():
    import inspect

    from till_infinity.trading.strategy import Strategy

    source = inspect.getsource(Strategy.risk_scale)
    for name in ("crowding", "by_volatility", "by_edge", "by_drawdown"):
        assert name in source


def test_sizing_reads_it():
    import inspect

    from till_infinity.trading import scalper

    assert "self.risk_scale(" in inspect.getsource(scalper.LevelStrategy.consider)


def test_all_four_are_off_by_default():
    """Better sizing of a signal with no edge scales the loss rather than
    fixing it - see research/horizon.md - so these wait for that question."""
    from till_infinity.trading.config import Settings

    s = Settings()
    assert s.crowding_share == 0.0
    assert s.volatility_target_bps == 0.0
    assert s.edge_full_at == 0.0
    assert s.drawdown_halt_at == 0.0


# ------------------------------------------- the call the service actually makes


def test_every_strategy_accepts_what_the_service_passes():
    """The test that would have caught a two-hour outage.

    `FadeToValue` and `Council` override `consider` with their own signatures.
    Widening the base and the scalper left those two unchanged, and the service
    passes `positions` and `peak` to every strategy - so the trading service
    stopped with `FadeToValue.consider() got an unexpected keyword argument
    'positions'` while 1,653 tests passed, because none of them called it the
    way the service does.

    Signature-level, not behavioural: it asks whether each strategy can be
    *called*, which is exactly what broke.
    """
    import inspect

    import till_infinity.trading as td

    for name, cls in td.STRATEGIES.items():
        for method in ("consider", "consider_async"):
            found = getattr(cls, method, None)
            if found is None or method not in vars(cls):
                continue  # inherited, so the base's signature governs
            parameters = inspect.signature(found).parameters
            for wanted in ("positions", "peak"):
                assert wanted in parameters, f"{name}.{method} cannot take {wanted}"


def test_the_service_passes_them():
    """And the other half: a signature that accepts them is useless if the
    caller never sends them."""
    import inspect

    from till_infinity.trading import service

    source = inspect.getsource(service.Trader.on_signal)
    assert "positions=positions" in source
    assert "peak=self.peak_equity" in source
