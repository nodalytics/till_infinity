"""Monetary policy series from FRED."""

import datetime as dt

import pytest

from till_infinity.news.config import Settings
from till_infinity.news.fred import CURRENCY, SERIES, FredSource, parse
from till_infinity.news.service import SOURCES
from till_infinity.news.source import PermanentError


def payload(rows):
    return {"observations": [{"date": d, "value": v} for d, v in rows]}


def test_a_missing_value_is_a_dot_not_a_null():
    """FRED writes a missing observation as the string ".", so a naive read
    raises on a document that is otherwise fine. Dropping the whole response
    would lose a series for one absent day."""
    got = parse(
        payload([("2026-08-26", "4.67"), ("2026-08-27", "."), ("2026-08-28", "4.70")]), "DGS10"
    )
    assert [o.value for o in got] == [4.67, 4.70]


def test_the_date_is_read_as_utc_midnight():
    got = parse(payload([("2026-08-26", "4.67")]), "DGS10")
    when = dt.datetime.fromtimestamp(got[0].time, dt.UTC)
    assert (when.year, when.month, when.day, when.hour) == (2026, 8, 26, 0)


def test_a_series_carries_the_currency_it_speaks_about():
    """So a consumer can line it up with a pair without knowing the code."""
    assert parse(payload([("2026-08-21", "5913000")]), "ECBASSETSW")[0].country == "EUR"
    assert parse(payload([("2026-07-01", "6443000")]), "JPNASSETS")[0].country == "JPY"
    assert parse(payload([("2026-08-27", "4.67")]), "DGS10")[0].country == "USD"


def test_the_indicator_says_what_the_code_means():
    assert parse(payload([("2026-08-28", "2.31")]), "T10YIE")[0].indicator == (
        "10-year breakeven inflation"
    )


def test_a_malformed_response_is_empty_rather_than_an_error():
    assert parse(None, "DGS10") == []
    assert parse({}, "DGS10") == []
    assert parse({"observations": "nonsense"}, "DGS10") == []
    assert parse(payload([("not-a-date", "1.0")]), "DGS10") == []


async def test_it_refuses_to_poll_without_a_key():
    """Loud rather than empty: the keyless endpoint answers 400, so a source
    that carried on would collect nothing and look healthy."""
    source = FredSource(Settings(fred_api_key=""))
    with pytest.raises(PermanentError, match="FRED_API_KEY"):
        await source.poll()


def test_every_series_has_a_label():
    """The label is stored as the indicator, so a code without one would reach
    the journal as itself and mean nothing to a reader."""
    assert all(SERIES.values())
    assert set(CURRENCY) <= set(SERIES)


def test_the_default_selection_is_every_series():
    assert set(FredSource(Settings()).series) == set(SERIES)
    assert FredSource(Settings(), series=("DGS10",)).series == ("DGS10",)


def test_it_is_registered_and_runs_on_the_slow_clock():
    """Daily at fastest and mostly weekly - nothing to gain from the fast
    clock, and a rate limit to lose."""
    assert SOURCES["fred"] is FredSource
    assert FredSource.slow is True


def test_the_breakeven_identity_is_what_it_claims():
    """A breakeven is the nominal yield minus the real one of the same
    maturity. Live on 2026-08-27: DGS10 4.67 - DFII10 2.34 = 2.33 against
    T10YIE 2.31. Kept as a check on the reading rather than on FRED: if these
    three ever stop lining up, the parse is wrong, not the bond market."""
    nominal = parse(payload([("2026-08-27", "4.67")]), "DGS10")[0].value
    real = parse(payload([("2026-08-27", "2.34")]), "DFII10")[0].value
    breakeven = parse(payload([("2026-08-27", "2.31")]), "T10YIE")[0].value
    assert abs((nominal - real) - breakeven) < 0.05


def test_the_source_list_is_reachable_from_settings():
    """It was not: `stack` called `collect` without one, so the default won and
    nothing a deployment said could change it. `fred` was configured on a live
    box with its key present and was never constructed, with no error to say
    so."""
    import os
    from unittest import mock

    assert Settings().sources == ()
    with mock.patch.dict(os.environ, {"NEWS_SOURCES": "rss,imf,fred"}):
        assert Settings.from_env().sources == ("rss", "imf", "fred")


def test_the_stack_hands_the_source_list_to_collect():
    """The setting existing is not the same as it arriving."""
    import inspect

    from till_infinity import stack

    source = inspect.getsource(stack.Stack._run_news)
    assert "sources=settings.sources or None" in source
