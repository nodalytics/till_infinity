"""The MT5 adapter's conversions, which is where its risk is.

The clients themselves need a running kernel to exercise, and that belongs in
a node test. What is tested here is everything that turns bridge JSON into
Nautilus objects and back - because a wrong conversion does not raise, it
quietly changes a number.
"""

from __future__ import annotations

import pytest

from till_infinity.adapters.mt5.bridge import Bridge, BridgeError, _rows
from till_infinity.adapters.mt5.data import TIMEFRAMES, _bar, _is_forming, _timeframe


class Instrument:
    """Just the two precisions the bar builder reads."""

    def __init__(self, price: int = 5, size: int = 2) -> None:
        self.price_precision = price
        self.size_precision = size


def bar_type(spec: str = "1-MINUTE-LAST-EXTERNAL"):
    from nautilus_trader.model.data import BarType

    return BarType.from_str(f"EURUSD.MT5-{spec}")


class TestTheBarTimestampMovesToTheClose:
    """`ts_event` is a Nautilus bar's **close**; MT5 stamps a bar's **open**.

    This is not an off-by-one that shifts a series. `statespace.observe_bar`
    refuses a bar whose time is not strictly after the last one, so feeding it
    closes where it expects opens silences the series after the first bar -
    and a silent series looks exactly like a feed that is not running.
    """

    def test_a_minute_bar_is_stamped_a_minute_after_its_open(self):
        row = {"time": 1_700_000_000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15}
        bar = _bar(bar_type(), row, Instrument(), 60.0)
        assert bar.ts_event == int((1_700_000_000 + 60) * 1e9)

    def test_the_open_is_recoverable_by_subtracting_the_length(self):
        row = {"time": 1_700_000_000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15}
        bar = _bar(bar_type(), row, Instrument(), 60.0)
        assert (bar.ts_event / 1e9) - 60.0 == 1_700_000_000

    def test_every_timeframe_has_a_length_and_a_bridge_name(self):
        for spec, (name, seconds) in TIMEFRAMES.items():
            assert name, spec
            assert seconds > 0, spec
            assert _timeframe(bar_type(f"{spec}-LAST-EXTERNAL")) == (name, seconds)

    def test_an_unserved_timeframe_is_refused_rather_than_guessed(self):
        with pytest.raises(ValueError, match="no MT5 timeframe"):
            _timeframe(bar_type("1-SECOND-LAST-EXTERNAL"))


class TestPrecisionComesFromTheInstrument:
    """`Price` and `Quantity` are fixed-precision, so this truncates the feed.

    Measured on the dispersion fold: btc at its tradable two decimals moved a
    1m reading by 3e-5 relative while 15m stayed at float noise, because
    truncation matters in proportion to how small a bar's range is against its
    tick size.
    """

    def test_a_price_carries_exactly_the_digits_the_instrument_declares(self):
        row = {"time": 1, "open": 1.123456789, "high": 1.2, "low": 1.0, "close": 1.15}
        bar = _bar(bar_type(), row, Instrument(price=5), 60.0)
        assert str(bar.open) == "1.12346"

    def test_a_fractional_volume_survives_when_the_precision_allows_it(self):
        """A size precision of 0 rounded 701 of 3,000 btc volumes to zero.

        They run 0.28, 0.45, 0.48, and `statespace` decides `paced` as
        `paced and volume > 0` - so the conversion silently flipped a boolean
        a strategy acts on, and it looked like a knife-edge threshold inside
        statespace rather than a lost volume.
        """
        row = {"time": 1, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "tick_volume": 0.45}
        assert float(_bar(bar_type(), row, Instrument(size=2), 60.0).volume) == 0.45

    def test_a_size_precision_of_zero_is_what_lost_the_volume(self):
        """Power for the test above, on the one number that caused it.

        A test that a volume survives proves nothing unless the same volume
        demonstrably dies at the precision that was shipped - otherwise it
        could be passing because 0.45 is unremarkable.
        """
        row = {"time": 1, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "tick_volume": 0.45}
        assert float(_bar(bar_type(), row, Instrument(size=0), 60.0).volume) == 0.0


class TestAFormingBarIsNotPublished:
    """A forming bar is a different measurement, not an early one.

    The sampling variance of `log(garman_klass)` runs 0.265 on a bar built
    from thousands of ticks and 0.50 on one from twelve, with the bias going
    from -0.15 to -0.79. A tenth-formed bar is an accurate reading of a tenth
    of the bar.
    """

    def test_a_bar_whose_window_is_open_is_forming(self):
        assert _is_forming(1_000, 60.0, int(1_030 * 1e9)) is True

    def test_a_bar_whose_window_has_closed_is_not(self):
        assert _is_forming(1_000, 60.0, int(1_061 * 1e9)) is False

    def test_the_boundary_belongs_to_the_closed_bar(self):
        assert _is_forming(1_000, 60.0, int(1_060 * 1e9)) is False


class TestTheBridgeUnwrapsWhateverShapeItIsGiven:
    """Routes return a list, or a dict wrapping one, depending on the route."""

    @pytest.mark.parametrize(
        "raw",
        [
            [{"a": 1}],
            {"data": [{"a": 1}]},
            {"rates": [{"a": 1}]},
            {"ticks": [{"a": 1}]},
            {"positions": [{"a": 1}]},
            {"orders": [{"a": 1}]},
            {"deals": [{"a": 1}]},
        ],
    )
    def test_each_wrapper_yields_the_rows(self, raw):
        assert _rows(raw) == [{"a": 1}]

    def test_nothing_is_an_empty_list_rather_than_an_error(self):
        """A 404 from the tick route means an empty range, not a failure."""
        assert _rows(None) == []

    def test_a_shape_with_no_rows_is_empty_rather_than_a_guess(self):
        assert _rows({"unexpected": 1}) == []

    def test_non_dict_entries_are_dropped(self):
        assert _rows([{"a": 1}, "junk", None]) == [{"a": 1}]


class TestTheSessionIsOpenedDeliberately:
    def test_using_it_before_opening_says_so(self):
        """Loop-bound resources belong in `_connect`, not the constructor -
        the client is built before the node's event loop exists."""
        with pytest.raises(BridgeError, match="not open"):
            _ = Bridge("http://nowhere:8000").session

    async def test_open_is_idempotent_and_close_releases(self):
        bridge = Bridge("http://nowhere:8000", api_key="k")
        await bridge.open()
        first = bridge.session
        await bridge.open()
        assert bridge.session is first
        assert first.headers["X-API-Key"] == "k"
        await bridge.close()
        with pytest.raises(BridgeError):
            _ = bridge.session


class TestABarsTimeArrivesInThreeShapes:
    """**The desk held quotes and never received a bar.**

    The HTTP bridge runs its rows through `pandas.to_datetime`, so a bar's
    `time` arrives as an ISO string. Both bar sites did a bare numeric
    conversion on it - the poll loop `int(row.get("time") or 0)` and `_bar`
    `float(...)` - so against the live bridge every poll raised `invalid
    literal for int() with base 10: '2026-11-...'`, on all six symbols,
    continuously. Every strategy here is bar-driven, so the desk was inert.

    The tick path was already correct because it went through
    `_milliseconds`, whose own docstring describes this exact behaviour. The
    knowledge was in the file and the bar path did not use it, which is why
    the fake-bridge tests passed: they return integers.
    """

    def test_an_epoch_integer_still_reads(self):
        from till_infinity.adapters.mt5.data import _bar_seconds

        assert _bar_seconds({"time": 1793735408}) == 1793735408.0
        assert _bar_seconds({"time": 1793735408.0}) == 1793735408.0

    def test_the_iso_string_the_bridge_actually_sends(self):
        from till_infinity.adapters.mt5.data import _bar_seconds

        naive = _bar_seconds({"time": "2026-11-03T20:15:00"})
        zulu = _bar_seconds({"time": "2026-11-03T20:15:00Z"})

        assert naive > 0.0, "this is the shape that broke every bar poll"
        assert naive == zulu, "a naive string is UTC - pandas produced it from an epoch"

    def test_an_unparseable_row_reads_zero_rather_than_raising(self):
        """The caller treats a non-advancing timestamp as "nothing new", which
        is the safe reading. A raise would also lose the other bar in the same
        response, since the bridge is asked for two."""
        from till_infinity.adapters.mt5.data import _bar_seconds

        assert _bar_seconds({}) == 0.0
        assert _bar_seconds({"time": "not a time"}) == 0.0
        assert _bar_seconds({"time": None}) == 0.0

    def test_a_bar_built_from_an_iso_row_carries_a_real_timestamp(self):
        """Through `_bar` itself, not just the helper: the bug was in two
        places and a test of one would have missed the other."""
        from nautilus_trader.model.data import BarType
        from nautilus_trader.test_kit.providers import TestInstrumentProvider

        from till_infinity.adapters.mt5.data import _bar, _bar_seconds

        instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
        bar_type = BarType.from_str(f"{instrument.id}-5-MINUTE-LAST-EXTERNAL")
        row = {
            "time": "2026-11-03T20:15:00",
            "open": 1.1000,
            "high": 1.1020,
            "low": 1.0990,
            "close": 1.1010,
            "tick_volume": 120,
        }
        made = _bar(bar_type, row, instrument, 300.0)

        assert made.ts_event > 0, "a zero timestamp is the defect, not a bar"
        # Stamped at the close, which is one interval past the open.
        assert made.ts_event == int((_bar_seconds(row) + 300.0) * 1e9)
