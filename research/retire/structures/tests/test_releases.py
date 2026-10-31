"""The calendar as a volatility multiple: matching, reach, and the lull.

Four things here would fail silently and each would look like a working feature.

**Currency matching.** The two calendar providers label the same print differently - one by ISO
country, one by currency - so a feed that answers to `US` but not `USD` would miss half the
releases and publish a confident number from the other half.

**Reach.** A release four hours away must say *nothing*, and "nothing" has to be an absent key
rather than a 1.0 - because "no opinion" and "expect normal volatility" are different claims and
the journal has to be able to tell them apart.

**The lull.** The pre-release multiple is **below** one. A sign error there would size *up* into
the quietest window of the day, which is the expensive direction to be wrong in.

**Restore safety.** A capped `deque` restored from an older save comes back unbounded - that
happened in this codebase and was found on the live heap rather than in the declaration.
"""

from __future__ import annotations

import datetime as dt

from till_infinity.structures.context.releases import (
    IMPORTANT,
    KEEP,
    PROFILE,
    REACH,
    Releases,
)

NOON = dt.datetime(2026, 9, 23, 12, 30, tzinfo=dt.UTC).timestamp()


def book(*rows) -> Releases:
    got = Releases()
    got.note(rows)
    return got


def row(when, code, importance=IMPORTANT):
    return {"time": when, "country": code, "importance": importance}


def test_the_profile_is_the_measured_shape_including_the_lull():
    """0.79x before, 2.42x on the print, decaying to below normal by four hours."""
    values = dict(PROFILE)
    assert values[-120.0] < 1.0, "the pre-release lull must be below normal"
    assert values[0.0] > 2.0
    # Monotone decay after the print.
    after = [m for offset, m in PROFILE if offset >= 0]
    assert after == sorted(after, reverse=True)
    # And it undershoots by the end rather than merely returning to normal.
    assert after[-1] < 1.0


def test_a_release_on_the_quote_currency_is_matched_by_country_or_by_currency():
    """One provider files the US print as `US`, the other as `USD`. Both must match."""
    for code in ("US", "USD"):
        got = book(row(NOON, code))
        assert got.nearest("eurusd", NOON) == 0.0, code
        assert got.expect("eurusd", NOON) == dict(PROFILE)[0.0], code


def test_a_german_print_moves_the_euro():
    """The calendar files it under `DE` and it is a euro release."""
    got = book(row(NOON, "DE"))
    assert got.nearest("eurusd", NOON) == 0.0
    assert got.nearest("gbpusd", NOON) is None


def test_gold_answers_to_the_dollar_and_not_to_a_base_currency():
    """`xauusd` is not a pair, so its base is empty and only the quote leg matches."""
    assert book(row(NOON, "US")).nearest("xauusd", NOON) == 0.0
    assert book(row(NOON, "JP")).nearest("xauusd", NOON) is None


def test_the_lull_is_reported_before_the_release_and_is_below_one():
    got = book(row(NOON, "USD"))
    before = got.expect("eurusd", NOON - 60 * 60)
    assert before is not None
    assert before < 1.0, "sizing up into the pre-release lull is the expensive error"
    assert before == dict(PROFILE)[-120.0]


def test_the_multiple_steps_down_through_the_measured_windows():
    got = book(row(NOON, "USD"))
    seen = [got.expect("eurusd", NOON + m * 60) for m in (0, 30, 60, 120, 239)]
    assert all(v is not None for v in seen)
    assert seen == sorted(seen, reverse=True)
    assert seen[0] > 2.0
    # Still above normal four hours out. The measured **0.920 undershoot is deliberately not
    # published**: it is the realised volatility over the whole four-hour window, which is a
    # statement about a window rather than about the instant a caller is standing in. Exposing
    # it as a live multiple would be modelling past the measurement.
    assert seen[-1] > 1.0
    assert seen[-1] == dict(PROFILE)[120.0]


def test_nothing_is_published_out_of_reach():
    """An absent key, not a 1.0 - "no opinion" is a different claim from "expect normal"."""
    got = book(row(NOON, "USD"))
    far = NOON + (REACH + 60) * 60
    assert got.expect("eurusd", far) is None
    assert got.features("eurusd", far) == {}
    assert "release_vol_multiple" not in got.features("eurusd", far)


def test_a_low_importance_release_is_not_carried():
    """The profile was measured on importance 2, so that is what may use it."""
    got = book(row(NOON, "USD", importance=IMPORTANT - 1))
    assert got.events == []
    assert got.features("eurusd", NOON) == {}


def test_the_closest_release_wins_when_several_are_near():
    got = book(row(NOON, "USD"), row(NOON + 90 * 60, "USD"), row(NOON - 30 * 60, "USD"))
    # Standing twenty minutes after the first, the first is closest.
    minutes = got.nearest("eurusd", NOON + 20 * 60)
    assert minutes == 20.0


def test_features_are_floats_and_carry_the_log_form():
    got = book(row(NOON, "USD"))
    feats = got.features("eurusd", NOON)
    assert set(feats) == {"release_minutes", "release_vol_multiple", "release_vol_log"}
    assert all(isinstance(v, float) for v in feats.values())
    # Log, so a doubling and a halving sit the same distance from normal.
    assert feats["release_vol_log"] > 0
    assert got.features("eurusd", NOON - 60 * 60)["release_vol_log"] < 0


def test_notes_are_deduplicated_and_capped():
    got = Releases()
    got.note([row(NOON, "USD")])
    got.note([row(NOON, "USD")])
    assert len(got.events) == 1, "the same print twice is one print"
    got.note([row(NOON + i * 60, "USD") for i in range(KEEP + 500)])
    assert len(got.events) <= KEEP


def test_it_takes_objects_as_well_as_mappings():
    """So the two services stay uncoupled - this must not import the news models."""

    class Event:
        time = NOON
        importance = IMPORTANT
        country = "USD"

    got = Releases()
    got.note([Event()])
    assert got.nearest("eurusd", NOON) == 0.0


def test_a_feed_with_no_currency_says_nothing_rather_than_guessing():
    got = book(row(NOON, "USD"))
    # A synthetic has no currency leg the calendar knows about.
    assert got.features("boom_1000_index", NOON - 10**7) == {}


def test_it_holds_nothing_with_a_length_that_could_come_back_uncapped():
    got = book(row(NOON, "USD"))
    assert isinstance(got.events, list)
    for when, code in got.events:
        assert isinstance(when, float)
        assert isinstance(code, str)


def test_the_store_reader_survives_a_missing_file():
    """A structures service must not fall over because a sibling service wrote nothing yet."""
    from till_infinity.structures.context.releases import upcoming

    assert upcoming("/nonexistent/news.db") == []


def test_the_store_reader_returns_only_important_events_in_the_window(tmp_path):
    import sqlite3
    import time

    from till_infinity.structures.context.releases import upcoming

    path = tmp_path / "news.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (source TEXT, id TEXT, time REAL, title TEXT,"
        " country TEXT, importance INTEGER, actual TEXT, forecast TEXT,"
        " previous TEXT, unit TEXT, period TEXT, updated REAL)"
    )
    now = time.time()
    conn.executemany(
        "INSERT INTO events (source, id, time, title, country, importance, updated)"
        " VALUES (?,?,?,?,?,?,?)",
        [
            ("tv", "a", now + 3600, "CPI", "USD", IMPORTANT, now),
            ("tv", "b", now + 3600, "Retail", "USD", IMPORTANT - 1, now),
            ("tv", "c", now + 400 * 86_400, "CPI next year", "USD", IMPORTANT, now),
        ],
    )
    conn.commit()
    conn.close()

    got = upcoming(path)
    assert len(got) == 1, "only the important event inside the window"
    assert got[0]["country"] == "USD"
    # And it feeds a book that then reads it.
    book = Releases()
    book.note(got)
    assert book.nearest("eurusd", now) is not None
