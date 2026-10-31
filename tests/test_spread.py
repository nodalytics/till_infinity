"""Our rolling spread, and the upstream one it exists because of."""

from __future__ import annotations

import pytest
from nautilus_trader.indicators.spread_analyzer import SpreadAnalyzer
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity

from till_infinity.actors.spread import RollingSpread

IID = InstrumentId(Symbol("EURUSD"), Venue("MT5"))


def quote(bid: float, ask: float, n: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=IID,
        bid_price=Price(bid, 5),
        ask_price=Price(ask, 5),
        bid_size=Quantity(1, 0),
        ask_size=Quantity(1, 0),
        ts_event=n,
        ts_init=n,
    )


WIDENING = [(1.1000, 1.1000 + 0.0002 * (i + 1)) for i in range(6)]


class TestTheUpstreamAverageFreezes:
    """**Pinned on purpose.** If Nautilus fixes this, this test fails and we
    find out - which is the only way a workaround gets removed rather than
    outliving its reason.

    `handle_quote_tick` appends the spread and *then* calls
    `fast_mean_iterated(..., drop_left=False)`, which subtracts
    `values[-1]` - the value just appended - from `next_value`. Every update
    adds zero. `drop_left=False` is also the wrong end for a `maxlen` deque,
    which evicts from the left.
    """

    def test_it_tracks_until_the_window_fills(self):
        analyzer = SpreadAnalyzer(IID, 4)
        for i, (bid, ask) in enumerate(WIDENING[:3]):
            analyzer.handle_quote_tick(quote(bid, ask, i + 1))
        assert analyzer.average == pytest.approx(0.0004, abs=1e-9)

    def test_and_then_stops(self):
        analyzer = SpreadAnalyzer(IID, 4)
        for i, (bid, ask) in enumerate(WIDENING):
            analyzer.handle_quote_tick(quote(bid, ask, i + 1))
        assert analyzer.current == pytest.approx(0.0012, abs=1e-9)
        # Frozen at the value it held when the window filled, while the true
        # rolling mean of the last four is 0.0009.
        assert analyzer.average == pytest.approx(0.0004, abs=1e-9)

    def test_current_is_fine_and_is_what_we_use_from_it(self):
        analyzer = SpreadAnalyzer(IID, 4)
        for i, (bid, ask) in enumerate(WIDENING):
            analyzer.handle_quote_tick(quote(bid, ask, i + 1))
            assert analyzer.current == pytest.approx(ask - bid, abs=1e-9)


class TestOursTracks:
    def test_the_mean_follows_the_window(self):
        rolling = RollingSpread(4)
        for bid, ask in WIDENING:
            rolling.update(bid, ask)
        assert rolling.average == pytest.approx(0.0009, abs=1e-9)
        assert rolling.current == pytest.approx(0.0012, abs=1e-9)

    def test_it_agrees_with_upstream_before_the_window_fills(self):
        """Where upstream is correct, we match it - so the difference is the
        bug and not two different definitions."""
        analyzer = SpreadAnalyzer(IID, 4)
        rolling = RollingSpread(4)
        for i, (bid, ask) in enumerate(WIDENING[:3]):
            analyzer.handle_quote_tick(quote(bid, ask, i + 1))
            rolling.update(bid, ask)
            assert rolling.average == pytest.approx(analyzer.average, abs=1e-9)

    def test_the_window_is_bounded(self):
        rolling = RollingSpread(3)
        for bid, ask in WIDENING:
            rolling.update(bid, ask)
        assert rolling.count == 3
        assert rolling.average == pytest.approx((0.0008 + 0.0010 + 0.0012) / 3, abs=1e-9)

    def test_the_median_is_reported_too(self):
        """Spread is bounded below and spikes on news, so a single release
        drags the mean far more than it changes what gets paid."""
        rolling = RollingSpread(5)
        for spread in (0.0002, 0.0002, 0.0002, 0.0002, 0.0100):
            rolling.update(1.1, 1.1 + spread)
        assert rolling.typical == pytest.approx(0.0002, abs=1e-9)
        assert rolling.average > rolling.typical
        assert rolling.widest == pytest.approx(0.0100, abs=1e-9)

    def test_a_crossed_quote_is_refused_rather_than_averaged(self):
        """Folding a negative spread in makes the average read *tighter* than
        the truth, which is the one direction that lets an idea through."""
        rolling = RollingSpread(4)
        with pytest.raises(ValueError, match="crossed quote"):
            rolling.update(1.1005, 1.1000)

    def test_the_cost_test_is_a_round_trip(self):
        """Comparing a one-way spread against an expected move is how a losing
        idea looks marginal."""
        rolling = RollingSpread(4)
        for _ in range(4):
            rolling.update(1.1, 1.1003)  # 3 pips one way, 6 round trip
        assert rolling.exceeds(0.0005) is True
        assert rolling.exceeds(0.0007) is False

    def test_an_empty_window_answers_none_rather_than_zero(self):
        rolling = RollingSpread(4)
        assert rolling.average is None
        assert rolling.exceeds(0.001) is None
        assert rolling.initialized is False

    def test_a_nonpositive_capacity_is_refused(self):
        with pytest.raises(ValueError, match="must be positive"):
            RollingSpread(0)
