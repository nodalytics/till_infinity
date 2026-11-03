"""What it costs to hold a perpetual."""

import pytest

from till_infinity.prices.funding import Book, Funding, current, history


def rate(**over):
    made = {
        "feed": "btc_usdt_usdt",
        "exchange": "binance",
        "pair": "BTC/USDT:USDT",
        "rate": 8.893e-05,
        "time": 1788451200.0,
        "interval": "8h",
    }
    made.update(over)
    return Funding(**made)


class _Exchange:
    def __init__(self, *, rates=True, hist=True, rows=None, raises=False):
        self.has = {"fetchFundingRates": rates, "fetchFundingRateHistory": hist}
        self._rows = rows
        self._raises = raises
        self.asked = []

    async def fetch_funding_rates(self):
        if self._raises:
            raise RuntimeError("down")
        return {
            "BTC/USDT:USDT": {
                "symbol": "BTC/USDT:USDT",
                "fundingRate": 7.7e-07,
                "interval": "8h",
                "markPrice": 79628.0,
                "indexPrice": 79667.6,
                "timestamp": 1788569000000,
            },
            "DOGE/USDT:USDT": {"symbol": "DOGE/USDT:USDT", "fundingRate": None},
            "NOTCARRIED/USDT:USDT": {"symbol": "NOTCARRIED/USDT:USDT", "fundingRate": 0.01},
        }

    async def fetch_funding_rate_history(self, pair, since=None, limit=None):
        self.asked.append((pair, since, limit))
        return (
            self._rows
            if self._rows is not None
            else [
                {"symbol": pair, "fundingRate": 8.4e-05, "timestamp": 1788451200000},
                {"symbol": pair, "fundingRate": 3.8e-05, "timestamp": 1788480000000},
            ]
        )


def test_the_annualised_rate_is_computed_not_stored():
    """8-hourly against 4-hourly is a factor of two, so an annualised number in
    the record would bake a presentation choice into the measurement."""
    assert rate(interval="8h").annualised == pytest.approx(8.893e-05 * 3 * 365)
    assert rate(interval="4h").annualised == pytest.approx(8.893e-05 * 6 * 365)


def test_an_unknown_interval_annualises_to_nothing():
    """Rather than assuming eight hours, which is wrong by a factor of two on
    the pairs that fund fastest - exactly where the number matters."""
    assert rate(interval="").annualised is None


def test_the_basis_needs_both_prices():
    assert rate(mark=81316.7, index=81300.0).basis == pytest.approx(0.000205, abs=1e-6)
    assert rate(mark=81316.7).basis is None
    assert rate(index=81300.0).basis is None


async def test_current_keeps_only_the_pairs_the_desk_carries():
    """An exchange lists hundreds more and none of them have levels."""
    got = await current(_Exchange(), "binance", {"BTC/USDT:USDT": "btc_usdt_usdt"})

    assert [f.pair for f in got] == ["BTC/USDT:USDT"]
    assert got[0].rate == pytest.approx(7.7e-07)
    assert got[0].mark == pytest.approx(79628.0)


async def test_a_current_rate_is_marked_unsettled():
    """It is the rate for the *next* stamp. A prediction that moved is not a
    correction of history, and averaging the two would mix what was paid with
    what might be."""
    got = await current(_Exchange(), "binance", {"BTC/USDT:USDT": "btc_usdt_usdt"})

    assert got[0].settled is False


async def test_a_pair_with_no_rate_is_skipped_rather_than_zeroed():
    """Zero is a real funding rate and means the sides are balanced."""
    got = await current(
        _Exchange(),
        "binance",
        {"BTC/USDT:USDT": "btc_usdt_usdt", "DOGE/USDT:USDT": "doge_usdt_usdt"},
    )

    assert [f.feed for f in got] == ["btc_usdt_usdt"]


async def test_an_exchange_that_cannot_answer_costs_nothing():
    """Funding is an input to sizing and to research, not to whether the desk
    runs."""
    assert await current(_Exchange(raises=True), "binance", {"BTC/USDT:USDT": "b"}) == []
    assert await current(_Exchange(rates=False), "binance", {"BTC/USDT:USDT": "b"}) == []


async def test_history_asks_from_the_newest_stamp_already_stored():
    """A top-up asks for what is missing rather than re-fetching the window."""
    exchange = _Exchange()

    await history(
        exchange,
        "binance",
        {"BTC/USDT:USDT": "btc_usdt_usdt"},
        since={"BTC/USDT:USDT": 1788451200.0},
    )

    pair, since, _limit = exchange.asked[0]
    assert pair == "BTC/USDT:USDT"
    assert since == 1788451200000 + 1  # strictly after what is stored


async def test_history_rows_are_marked_settled():
    got = await history(_Exchange(), "binance", {"BTC/USDT:USDT": "btc_usdt_usdt"})

    assert len(got) == 2
    assert all(f.settled for f in got)


async def test_a_history_row_without_a_stamp_is_dropped():
    """It cannot be placed in time, which is worse than being absent."""
    rows = [{"symbol": "BTC/USDT:USDT", "fundingRate": 1e-4, "timestamp": None}]

    got = await history(_Exchange(rows=rows), "binance", {"BTC/USDT:USDT": "b"})

    assert got == []


def test_the_book_keeps_the_newest_row_per_feed():
    book = Book()
    book.observe([rate(time=100.0, rate=1e-4), rate(time=50.0, rate=9e-9)])

    assert book.rate("btc_usdt_usdt") == pytest.approx(1e-4)


def test_the_cost_of_holding_scales_with_time():
    book = Book()
    book.observe([rate(rate=1e-4, interval="8h")])

    day = book.cost_over("btc_usdt_usdt", 86_400)
    half = book.cost_over("btc_usdt_usdt", 43_200)
    assert day == pytest.approx(1e-4 * 3)
    assert half == pytest.approx(day / 2)


def test_the_cost_is_unknown_rather_than_guessed_without_an_interval():
    book = Book()
    book.observe([rate(interval="")])

    assert book.cost_over("btc_usdt_usdt", 86_400) is None
    assert book.cost_over("nothing_here", 86_400) is None
