"""Bars that contradict themselves, and the filter that drops them.

Not a hypothetical class of bug: 1,187 daily and 37 weekly bars in
`.data/prices/prices.db` violate one of these invariants, 0.3 to 0.8% of daily
bars per FX feed, and one has `high < low`. None of the intraday intervals
does, which points at the source - Yahoo carries an adjusted close against
unadjusted highs and lows, and the terminal's intraday feeds do not.
"""

from __future__ import annotations

import pytest

from till_infinity.prices.models import Bar, drop_unsound


def bar(open_: float, high: float, low: float, close: float, volume: float | None = None) -> Bar:
    return Bar(time=1_700_000_000, open=open_, high=high, low=low, close=close, volume=volume)


class TestTheBarFromTheStore:
    """The exact row that was found, so the filter is pinned to reality."""

    REAL = bar(0.841467499732971, 0.843170344829559, 0.833611190319061, 0.847026884555817)

    def test_it_is_caught(self):
        assert self.REAL.defects() == ("close outside the range",)

    def test_it_is_not_sound(self):
        assert self.REAL.sound is False

    def test_the_close_really_is_above_the_high(self):
        """46 pips above, which is not float noise."""
        assert self.REAL.close - self.REAL.high > 0.003


class TestEachWayABarCanContradictItself:
    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            (bar(1.05, 1.10, 1.00, 1.08), ()),
            (bar(1.05, 1.10, 1.00, 1.15), ("close outside the range",)),
            (bar(1.05, 1.10, 1.00, 0.95), ("close outside the range",)),
            (bar(1.15, 1.10, 1.00, 1.05), ("open outside the range",)),
            (bar(0.95, 1.10, 1.00, 1.05), ("open outside the range",)),
            (bar(1.05, 1.10, 1.00, 1.08, -1.0), ("negative volume",)),
            (bar(0.0, 1.10, 1.00, 1.08), ("non-positive price", "open outside the range")),
            (bar(-1.0, 1.10, 1.00, 1.08), ("non-positive price", "open outside the range")),
        ],
    )
    def test_the_defects_are_named(self, candidate, expected):
        assert candidate.defects() == expected

    def test_high_below_low_reports_everything_it_breaks(self):
        """A crossed range puts open and close outside it by construction."""
        assert bar(1.00, 0.90, 1.10, 1.00).defects() == (
            "high below low",
            "open outside the range",
            "close outside the range",
        )

    def test_a_nan_short_circuits(self):
        """Every comparison is false against a NaN, so a bar carrying one
        would otherwise be reported as perfectly sound."""
        assert bar(float("nan"), 1.10, 1.00, 1.05).defects() == ("not a number",)
        assert bar(1.05, 1.10, 1.00, float("nan")).defects() == ("not a number",)

    def test_a_zero_range_bar_is_sound(self):
        """A dead bar - no movement - is not malformed. Synthetics and thin
        sessions produce them, and refusing them would drop real data."""
        assert bar(1.05, 1.05, 1.05, 1.05).defects() == ()

    def test_volume_is_optional_and_absent_is_not_negative(self):
        assert bar(1.05, 1.10, 1.00, 1.08, None).defects() == ()
        assert bar(1.05, 1.10, 1.00, 1.08, 0.0).defects() == ()


class TestDroppingThemTallies:
    def test_the_sound_ones_survive_in_order(self):
        good = [bar(1.05, 1.10, 1.00, 1.08), bar(1.06, 1.11, 1.01, 1.09)]
        kept, tally = drop_unsound([good[0], bar(1.0, 0.9, 1.1, 1.0), good[1]])
        assert kept == good
        assert tally["high below low"] == 1

    def test_the_tally_counts_every_reason_not_every_bar(self):
        """A bar with three defects contributes to three counts, because the
        question a tally answers is what is wrong with this feed."""
        _kept, tally = drop_unsound([bar(1.0, 0.9, 1.1, 1.0)])
        assert sum(tally.values()) == 3

    def test_nothing_in_means_nothing_out(self):
        assert drop_unsound([]) == ([], {})

    def test_an_all_bad_batch_keeps_nothing_and_says_why(self):
        kept, tally = drop_unsound([bar(1.05, 1.10, 1.00, 1.15) for _ in range(5)])
        assert kept == []
        assert tally == {"close outside the range": 5}
