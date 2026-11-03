"""Who is positioned, not just where price is."""

import pytest

from till_infinity.prices.positioning import (
    Book,
    Interest,
    Ratio,
    long_short,
    open_interest,
    open_interest_history,
)


class _Exchange:
    """Shapes taken from the live probe on 2026-09-05, not invented."""

    def __init__(self, *, bulk=False, current=True, hist=True, ls=True, rows=None):
        self.has = {
            "fetchOpenInterests": bulk,
            "fetchOpenInterest": current,
            "fetchOpenInterestHistory": hist,
            "fetchLongShortRatioHistory": ls,
        }
        self._rows = rows
        self.asked: list = []

    async def fetch_open_interests(self):
        # okx: the only one that answers every pair at once, and the only one
        # that populates the notional.
        return {
            "BTC/USDT:USDT": {
                "symbol": "BTC/USDT:USDT",
                "openInterestAmount": 2744748.9,
                "openInterestValue": 2183818291.05,
                "timestamp": 1788569483722,
            },
            "NOTCARRIED/USDT:USDT": {
                "symbol": "NOTCARRIED/USDT:USDT",
                "openInterestAmount": 1.0,
                "timestamp": 1788569483722,
            },
        }

    async def fetch_open_interest(self, pair):
        # binance: amount only, no notional.
        return {"symbol": pair, "openInterestAmount": 107919.883, "timestamp": 1788569471571}

    async def fetch_open_interest_history(self, pair, timeframe, since=None, limit=None):
        self.asked.append((pair, timeframe, since, limit))
        if self._rows is not None:
            return self._rows
        return [
            {
                "symbol": pair,
                "openInterestAmount": 107852.44,
                "openInterestValue": 8584148263.5,
                "timestamp": 1788569100000,
            }
        ]

    async def fetch_long_short_ratio_history(self, pair, timeframe, since=None, limit=None):
        self.asked.append((pair, timeframe, since, limit))
        return [
            {
                "symbol": pair,
                "longShortRatio": 1.0129,
                "timestamp": 1788569100000,
                "info": {"longAccount": "0.5032", "shortAccount": "0.4968"},
            },
            # okx gives the ratio and nothing else.
            {"symbol": pair, "longShortRatio": 1.0779, "timestamp": 1788569400000, "info": {}},
        ]


FEEDS = {"BTC/USDT:USDT": "btc_usdt_usdt"}


# --------------------------------------------------------------- the readings


def test_open_interest_in_contracts_does_not_pretend_to_be_a_notional():
    """A contract count and a notional differ by orders of magnitude, and
    quietly returning one where the other is expected would put two
    incomparable quantities in the same column."""
    assert Interest(feed="f", exchange="e", pair="p", amount=100.0).notional is None
    assert Interest(feed="f", exchange="e", pair="p", amount=100.0, mark=80_000.0).notional == 8e6
    assert Interest(feed="f", exchange="e", pair="p", amount=1.0, value=42.0).notional == 42.0


def test_the_exchanges_own_notional_wins_over_the_computed_one():
    got = Interest(feed="f", exchange="e", pair="p", amount=100.0, value=7.0, mark=80_000.0)

    assert got.notional == 7.0


def test_tilt_reads_the_same_from_shares_or_from_the_ratio():
    """binance gives both shares, okx gives only the ratio, and one number has
    to serve both."""
    shares = Ratio(
        feed="f", exchange="binance", pair="p", ratio=1.0129, long_share=0.5032, short_share=0.4968
    )
    ratio_only = Ratio(feed="f", exchange="okx", pair="p", ratio=1.0129)

    assert shares.tilt == pytest.approx(0.0064, abs=1e-3)
    assert ratio_only.tilt == pytest.approx(0.0064, abs=1e-3)


def test_a_balanced_book_tilts_at_zero():
    assert Ratio(feed="f", exchange="e", pair="p", ratio=1.0).tilt == 0.0
    assert (
        Ratio(feed="f", exchange="e", pair="p", ratio=1.0, long_share=0.5, short_share=0.5).tilt
        == 0.0
    )


# ------------------------------------------------------------- the collectors


async def test_the_bulk_call_is_used_where_the_exchange_has_one():
    """Only okx does, and it is the difference between one request and 250."""
    got = await open_interest(_Exchange(bulk=True), "okx", FEEDS)

    assert [i.feed for i in got] == ["btc_usdt_usdt"]
    assert got[0].notional == pytest.approx(2183818291.05)


async def test_pairs_the_desk_does_not_carry_are_dropped():
    got = await open_interest(_Exchange(bulk=True), "okx", FEEDS)

    assert all(i.pair == "BTC/USDT:USDT" for i in got)


async def test_without_a_bulk_call_it_asks_pair_by_pair():
    got = await open_interest(_Exchange(bulk=False), "binance", FEEDS)

    assert len(got) == 1
    assert got[0].amount == pytest.approx(107919.883)
    # No notional from binance, and none invented.
    assert got[0].notional is None


async def test_an_exchange_with_neither_call_returns_nothing():
    assert await open_interest(_Exchange(bulk=False, current=False), "mexc", FEEDS) == []
    assert await open_interest_history(_Exchange(hist=False), "mexc", FEEDS) == []
    assert await long_short(_Exchange(ls=False), "mexc", FEEDS) == []


async def test_history_asks_from_the_newest_stamp_already_stored():
    exchange = _Exchange()

    await open_interest_history(
        exchange, "binance", FEEDS, timeframe="5m", since={"BTC/USDT:USDT": 1788569100.0}
    )

    pair, timeframe, since, _limit = exchange.asked[0]
    assert (pair, timeframe) == ("BTC/USDT:USDT", "5m")
    assert since == 1788569100000 + 1


async def test_a_history_row_without_a_stamp_is_dropped():
    rows = [{"symbol": "BTC/USDT:USDT", "openInterestAmount": 1.0, "timestamp": None}]

    got = await open_interest_history(_Exchange(rows=rows), "binance", FEEDS)

    assert got == []


async def test_the_long_short_split_is_read_from_both_shapes():
    got = await long_short(_Exchange(), "binance", FEEDS)

    assert len(got) == 2
    assert got[0].long_share == pytest.approx(0.5032)
    assert got[1].long_share == 0.0  # okx-shaped row
    assert got[1].ratio == pytest.approx(1.0779)


# ------------------------------------------------- what the change is telling us


def _oi(amount, when):
    return Interest(
        feed="btc", exchange="binance", pair="B", amount=amount, mark=80_000.0, time=when
    )


def test_the_four_stories_a_move_in_open_interest_tells():
    """The whole reason to collect it: the price path is identical for fresh
    longs and for shorts covering, and they resolve at a level differently."""
    book = Book()
    book.observe([_oi(100.0, 1.0), _oi(105.0, 2.0)])
    assert book.flow("btc", price_change=+1) == "fresh longs"
    assert book.flow("btc", price_change=-1) == "fresh shorts"

    book.observe([_oi(90.0, 3.0)])
    assert book.flow("btc", price_change=+1) == "shorts covering"
    assert book.flow("btc", price_change=-1) == "longs capitulating"


def test_the_shift_is_a_share_not_a_count():
    """Scale-free, so one model can borrow evidence across instruments - the
    same argument volatility units make everywhere else here."""
    book = Book()
    book.observe([_oi(100.0, 1.0), _oi(105.0, 2.0)])

    assert book.shift("btc") == pytest.approx(0.05)


def test_a_small_move_is_steady_rather_than_a_story():
    book = Book()
    book.observe([_oi(100.0, 1.0), _oi(100.5, 2.0)])

    assert book.flow("btc", price_change=+1) == "steady"


def test_nothing_to_compare_is_unknown_not_steady():
    """A different answer, and confusing the two would report "no change" for a
    feed that has never been read."""
    book = Book()
    book.observe([_oi(100.0, 1.0)])

    assert book.shift("btc") is None
    assert book.flow("btc", price_change=+1) == "unknown"
    assert book.flow("never_seen", price_change=+1) == "unknown"


def test_an_older_reading_does_not_displace_a_newer_one():
    book = Book()
    book.observe([_oi(100.0, 5.0)])
    book.observe([_oi(999.0, 1.0)])

    assert book.interest["btc"].amount == pytest.approx(100.0)
