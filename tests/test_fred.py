"""The one feed here whose numbers are published rather than inferred.

FRED is read for the rate and balance-sheet series behind the currencies this
desk trades, which makes two of its quirks expensive. It writes a missing
observation as the **string "."**, so a naive read raises on a document that
is otherwise fine, and discarding the whole response over one absent day loses
a series. And its keyless endpoint answers 400 rather than nothing, so a
source that carried on without a key would collect nothing and look healthy
doing it - `fred` was configured on a live box with its key present and was
never constructed at all, because `stack` called `collect` without the
source list and the default won.

The series are mapped to the currency they speak about so a consumer can line
one up against a pair without knowing that `ECBASSETSW` is about the euro. A
mapping that drifts produces a number of the right size attached to the wrong
market, which nothing downstream can detect.
"""

import datetime as dt

import pytest

from till_infinity.adapters.news.sources import SOURCES
from till_infinity.adapters.news.sources.config import Settings
from till_infinity.adapters.news.sources.fred import CURRENCY, SERIES, FredSource, parse
from till_infinity.adapters.news.sources.source import PermanentError


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
    """A daily series has no time of day, so one has to be chosen rather than
    inferred. Midnight UTC is the choice; stamping it with the fetch time
    instead would make a figure published this morning sort after everything
    that has happened since."""
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


# **`test_the_stack_hands_the_source_list_to_collect` left with its
# subject.** It read the source of `stack.Stack._run_news` to confirm the
# setting reached `collect`, and `stack.py` is retired: the node starts
# services now, and news is an adapter whose `countries` and
# `minimum_importance` are config on the client rather than arguments threaded
# through a supervisor. The equivalent assertion is that the adapter's config
# reaches its `_rows` filter, which `test_news_adapter.py` makes.
