"""Release proximity, and the sign that would size up into the quiet window.

`news-volatility.md` is the measurement: realised volatility runs **0.789x** in
the two hours before a print, **2.424x** on the print's own bar, and **0.920x**
four hours later - *below* normal. Every interval excludes 1.0 and both halves
of the sample agree in sign at every horizon.

The whole file is a volatility statement. `break-features.md` measured that the
calendar moves volatility and does **not** move the probability a level breaks,
so nothing here may reach a direction.
"""

from __future__ import annotations

import math

import pytest

from till_infinity.risk.releases import PROFILE, REACH, Releases, upcoming

HOUR = 3600.0
NOW = 1_800_000_000.0


def holding(*events) -> Releases:
    found = Releases()
    found.note([{"time": w, "importance": 2, "country": c} for w, c in events])
    return found


def test_the_sign_is_negative_before_the_print_and_positive_after():
    """**The one that would be expensive backwards.** Reading the post-release
    spike as the pre-release lull sizes *up* into the quietest window of the
    day and down into the loudest."""
    found = holding((NOW, "US"))
    assert found.nearest("eurusd", NOW - HOUR) == pytest.approx(-60.0)
    assert found.nearest("eurusd", NOW + HOUR) == pytest.approx(60.0)
    assert found.nearest("eurusd", NOW) == pytest.approx(0.0)


def test_the_print_is_the_loudest_and_four_hours_later_is_quieter_than_normal():
    """The shape of the measurement: a short overshoot, then an undershoot."""
    found = holding((NOW, "US"))
    assert found.expect("eurusd", NOW) == pytest.approx(2.424)
    assert found.expect("eurusd", NOW - HOUR) == pytest.approx(0.789)
    assert found.expect("eurusd", NOW + 3 * HOUR) == pytest.approx(1.120)
    # Below one, which is the finding that is easy to disbelieve.
    assert PROFILE[-1][1] < 1.0


def test_it_steps_rather_than_interpolating():
    """The entries are cumulative realised volatility over distinct windows, so
    a straight line between two of them is not a quantity anything measured. A
    caller 45 minutes past a print reads the 30-minute row."""
    found = holding((NOW, "US"))
    assert found.expect("eurusd", NOW + 45 * 60.0) == pytest.approx(1.762)
    assert found.expect("eurusd", NOW + 31 * 60.0) == found.expect("eurusd", NOW + 59 * 60.0)


def test_nothing_in_reach_is_no_opinion_rather_than_normal():
    """**`None`, never 1.0.** "No opinion" and "expect normal volatility" are
    different claims and the journal has to tell them apart."""
    found = holding((NOW, "US"))
    assert found.expect("eurusd", NOW + (REACH + 1) * 60.0) is None
    assert found.nearest("eurusd", NOW + 10 * 24 * HOUR) is None
    assert found.features("eurusd", NOW + 10 * 24 * HOUR) == {}


def test_a_registered_synthetic_still_answers_to_nothing():
    """**The order-dependent one, and a live defect before it was pinned.**
    `register_broker_legs` gives every unmapped broker symbol a `USD` quote
    leg - correct for netting a dollar book, and it made a US print widen the
    stop on a Deriv synthetic whose generator is a broker's RNG. Registration
    happens at config time in prod, so without this the whole synthetic book
    carried `release_vol_multiple` into the journal.
    """
    from till_infinity.risk import exposure

    exposure.register_broker_legs(["volatility_75_index"])
    assert exposure.legs("volatility_75_index") == ("VOLATILITY_75", "USD")

    found = holding((NOW, "US"))
    assert found.codes("volatility_75_index") == ()
    assert found.expect("volatility_75_index", NOW) is None
    assert found.features("volatility_75_index", NOW) == {}
    # And the mapped half is untouched, so this is a filter and not an off switch.
    assert found.expect("eurusd", NOW) is not None


def test_a_release_only_touches_the_feeds_whose_currencies_it_moves():
    """A US print moves EURUSD and USDJPY and says nothing about a Deriv
    synthetic, which has no currency at all."""
    found = holding((NOW, "US"))
    assert found.expect("eurusd", NOW) is not None
    assert found.expect("usdjpy", NOW) is not None
    assert found.expect("volatility_75_index", NOW) is None


def test_a_german_print_moves_the_euro():
    """The calendar files a German print under the country, and it moves the
    euro - the one case the code map needs."""
    assert holding((NOW, "DE")).expect("eurusd", NOW) == pytest.approx(2.424)
    assert holding((NOW, "FR")).expect("euraud", NOW) == pytest.approx(2.424)


def test_only_important_releases_are_carried():
    """The measurement was made on grade 2. The live store holds 398 rows at
    that grade against 3,004 at grade 0, so carrying the rest would mean
    standing aside almost always."""
    found = Releases()
    found.note([{"time": NOW, "importance": 1, "country": "US"}])
    assert found.events == []


def test_the_nearest_release_wins_when_two_are_in_reach():
    found = holding((NOW, "US"), (NOW + 3 * HOUR, "US"))
    assert found.nearest("eurusd", NOW + 2.5 * HOUR) == pytest.approx(-30.0)


def test_the_features_are_a_volatility_statement_and_carry_no_direction():
    """`break-features.md`: the calendar moves volatility and does not move the
    probability a level breaks. A key here implying a side would be read as one
    within a day."""
    got = holding((NOW, "US")).features("eurusd", NOW)
    assert set(got) == {"release_minutes", "release_vol_multiple", "release_vol_log"}
    assert got["release_vol_log"] == pytest.approx(math.log(2.424), abs=1e-4)
    for key in got:
        assert not any(word in key for word in ("side", "direction", "up", "down", "bias"))


def test_an_absent_store_is_empty_rather_than_an_error(tmp_path):
    """A desk without a calendar sizes as it did before, which is what makes
    switching this on safe to undo."""
    assert upcoming(tmp_path / "nothing.db") == []


def test_the_store_is_read_only_and_filtered(tmp_path):
    """Read-only because the collector owns the file, and filtered in SQL
    because the live store holds 4,555 rows and a desk reads this on a timer."""
    import sqlite3

    path = tmp_path / "news.db"
    link = sqlite3.connect(path)
    link.execute("create table events (time real, importance int, country text)")
    link.executemany(
        "insert into events values (?,?,?)",
        [(NOW, 2, "US"), (NOW, 0, "US"), (NOW - 400 * 86_400.0, 2, "US")],
    )
    link.commit()
    link.close()

    rows = upcoming(path, window_days=30.0, now=NOW)
    assert len(rows) == 1, rows
    assert rows[0]["country"] == "US"
