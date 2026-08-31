"""Positioning from the CFTC - the one *observed* supply and demand here.

Everything else this system knows about supply and demand is inferred from
price, because the broker feed has a spread and no book behind it. This is
reported rather than inferred, which is the whole reason to carry it - and the
reason the sign matters more than usual: a mapping that inverts produces a
signal of exactly the right size pointing exactly the wrong way.
"""

from __future__ import annotations

import pytest

from till_infinity.news.cot import INVERTED, MARKETS, direction, parse

# One real row per market, trimmed to the columns the parser reads. Taken from
# the live file on 2026-08-31 so the layout under test is the layout served.
CAD = (
    '"CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",260825,2026-08-25,090741,CME ,00,090 ,'
    "  329544,  183841,   58911,    7616,   55489,  114432,    5260,   27384,   99476,"
    "    3777,   13049,    5235,     445,  296861,  295152,   32683,   34392"
)
EUR = (
    '"EURO FX - CHICAGO MERCANTILE EXCHANGE",260825,2026-08-25,099741,CME ,00,099 ,'
    "  818524,  400000,  300000,   10000,  100000,  150000,    5000,  100000,  138359,"
    "    4000,   20000,   10000,     500,  700000,  700000,   50000,   50000"
)


def series_of(rows, name):
    return next(o for o in rows if o.series == name)


# ------------------------------------------------------------------ the sign


def test_a_dollar_first_pair_inverts():
    """CME currency futures are quoted as the foreign currency, so a long yen
    future is *short* USDJPY."""
    assert direction("usdjpy") == -1
    assert direction("usdcad") == -1
    assert direction("usdchf") == -1


def test_a_dollar_last_pair_does_not():
    for feed in ("eurusd", "gbpusd", "audusd", "nzdusd"):
        assert direction(feed) == 1


def test_being_short_the_foreign_currency_reads_as_long_our_feed():
    """The check that catches an inverted table rather than restating it.
    Leveraged funds are net short Canadian dollar futures in this row, which is
    a long USDCAD position."""
    got = parse(CAD)
    net = series_of(got, "usdcad.leveraged_net")
    assert net.value > 0
    assert net.value == pytest.approx((27384 - 99476) / 329544 * -1, abs=1e-9)


def test_a_dollar_last_pair_keeps_the_futures_sign():
    got = parse(EUR)
    net = series_of(got, "eurusd.leveraged_net")
    assert net.value == pytest.approx((100000 - 138359) / 818524, abs=1e-9)
    assert net.value < 0


def test_every_inverted_feed_is_a_market_we_map():
    """A feed in `INVERTED` that nothing maps would be a sign rule with no
    subject - silently correct and doing nothing."""
    assert set(MARKETS.values()) >= INVERTED


def test_every_inverted_feed_really_has_the_dollar_first():
    for feed in INVERTED:
        assert feed.startswith("usd"), feed


# ------------------------------------------------------------ normalisation


def test_positions_are_a_share_of_open_interest():
    """Raw contract counts are not comparable between a market with two
    million outstanding and one with twenty-two thousand, nor with themselves a
    year later."""
    got = parse(CAD)
    for o in got:
        if o.series.endswith("_net"):
            assert -1.0 <= o.value <= 1.0


def test_open_interest_is_carried_as_well():
    got = parse(CAD)
    assert series_of(got, "usdcad.open_interest").value == 329544


def test_a_market_with_no_open_interest_is_skipped():
    """Dividing by it would be an infinity in a feature dictionary."""
    broken = CAD.replace("  329544,", "       0,", 1)
    assert not [o for o in parse(broken) if o.country == "usdcad"]


# ------------------------------------------------------------- what is read


def test_both_speculative_categories_are_taken():
    got = {o.series for o in parse(CAD)}
    assert "usdcad.leveraged_net" in got
    assert "usdcad.asset_manager_net" in got


def test_a_market_nobody_trades_here_is_ignored():
    row = CAD.replace("CANADIAN DOLLAR - CHICAGO", "LEAN HOGS - CHICAGO")
    assert parse(row) == []


def test_a_short_row_is_skipped_rather_than_raised_on():
    """The file is a fixed-layout text dump with no version marker."""
    assert parse('"EURO FX - CME",260825,2026-08-25,099741') == []


def test_junk_is_not_an_exception():
    assert parse("") == []
    assert parse("not,a,cot,file\n") == []


def test_the_reported_date_is_used_not_the_fetch_time():
    """Tuesday's positions, published Friday. Stamping them with now would make
    a three-day-old number look current."""
    got = parse(CAD)
    from datetime import UTC, datetime

    when = datetime.fromtimestamp(got[0].time, UTC)
    assert (when.year, when.month, when.day) == (2026, 8, 25)


def test_the_source_is_registered():
    """A source the service cannot build is a source that does not exist."""
    from till_infinity.news.service import SOURCES

    assert "cot" in SOURCES
