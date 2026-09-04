"""Choosing which crypto pairs are worth carrying."""

import time

import pytest

from till_infinity.prices import Board, CcxtSource, Filters
from till_infinity.prices.crypto import TIMEFRAMES


def board(symbol, **over):
    base = {
        "quote_volume": 1e9,
        "bid": 100.0,
        "ask": 100.05,
        "last": 100.0,
        "listed_days": 400.0,
        "range_share": 0.03,
    }
    base.update(over)
    return Board(symbol=symbol, **base)


def test_nothing_is_filtered_until_a_threshold_is_set():
    """A pairlist filter with a number nobody chose will one day empty the
    board on a quiet day, which is worse than collecting too much."""
    pairs = [board("BTC/USDT:USDT"), board("DOGE/USDT:USDT", quote_volume=1.0)]
    kept, dropped = Filters().choose(pairs)
    assert len(kept) == 2
    assert dropped == {}


def test_the_ranking_is_taken_before_the_rejections():
    """Ranking a filtered list would let one strict threshold change which
    pairs are even considered."""
    pairs = [
        board("A/USDT:USDT", quote_volume=10.0),
        board("B/USDT:USDT", quote_volume=30.0),
        board("C/USDT:USDT", quote_volume=20.0),
    ]
    kept, _ = Filters(top=2).choose(pairs)
    assert [p.symbol for p in kept] == ["B/USDT:USDT", "C/USDT:USDT"]


def test_each_filter_says_why_it_dropped_a_pair():
    """ "The board came back empty" has to be answerable."""
    pairs = [
        board("THIN/USDT:USDT", quote_volume=1.0),
        board("NEW/USDT:USDT", listed_days=2.0),
        board("WIDE/USDT:USDT", bid=100.0, ask=101.0),
        board("DUST/USDT:USDT", last=0.000001),
        board("DEAD/USDT:USDT", range_share=0.0001),
        board("GOOD/USDT:USDT"),
    ]
    kept, dropped = Filters(
        min_volume=1e5, min_days=30, max_spread=0.002, min_price=0.01, min_range=0.005
    ).choose(pairs)
    assert [p.symbol for p in kept] == ["GOOD/USDT:USDT"]
    assert set(dropped) == {
        "too little volume",
        "listed too recently",
        "spread too wide",
        "priced below the tick floor",
        "range too small to trade",
    }


def test_an_unknown_reading_does_not_cost_a_pair_its_place():
    """An exchange that reports no listing date should not have every pair
    dropped for being too new. Zero is unknown, not failing."""
    pairs = [board("BTC/USDT:USDT", listed_days=0.0, last=0.0, range_share=0.0)]
    kept, dropped = Filters(min_days=30, min_price=0.01, min_range=0.005).choose(pairs)
    assert len(kept) == 1
    assert dropped == {}


def test_only_perpetuals_when_asked():
    """A dated contract expires, and a level learned on one dies with it."""
    pairs = [board("BTC/USDT:USDT"), board("BTC/USDT"), board("BTC/USDT:USDT-260626")]
    kept, dropped = Filters(swaps_only=True).choose(pairs)
    assert [p.symbol for p in kept] == ["BTC/USDT:USDT"]
    assert dropped == {"not a perpetual": 2}


def test_the_spread_is_a_share_of_the_mid():
    """So a $60,000 pair and a $10 one compare."""
    assert board("X/USDT:USDT", bid=100.0, ask=101.0).spread_share > 0.009
    assert board("X/USDT:USDT", bid=0.0, ask=0.0).spread_share == 0.0


def test_it_serves_only_timeframes_ccxt_speaks():
    """Anything else would have to be resampled, and guessing is worse than
    declining."""
    from till_infinity.prices.models import INTERVALS

    source = CcxtSource.__new__(CcxtSource)
    got = source.supported([INTERVALS["1m"], INTERVALS["4h"]])
    assert {i.name for i in got} == {"1m", "4h"}
    assert "1m" in TIMEFRAMES


def test_it_is_a_registered_source():
    from till_infinity.prices import SOURCES

    assert SOURCES["ccxt"] is CcxtSource


# ------------------------------------------- the fields the filters actually read


class _FakeExchange:
    """Binance's real answer shape: `fetch_tickers` carries no top of book and
    no listing date, and both live on other calls."""

    def __init__(self, *, bids_asks=True, created=True):
        self.has = {"fetchBidsAsks": bids_asks}
        self._created = created

    async def fetch_tickers(self):
        return {"BTC/USDT:USDT": {"quoteVolume": 1e9, "last": 100.0, "high": 103.0, "low": 100.0}}

    async def fetch_bids_asks(self):
        return {"BTC/USDT:USDT": {"bid": 99.9, "ask": 100.1}}

    async def load_markets(self):
        made = {"BTC/USDT:USDT": {"swap": True}}
        if self._created:
            # 100 days ago, in epoch milliseconds.
            made["BTC/USDT:USDT"]["created"] = (time.time() - 100 * 86_400) * 1000.0
        return made


def _source(exchange):
    source = CcxtSource.__new__(CcxtSource)
    source._exchange = exchange
    return source


async def test_the_board_carries_a_spread_and_an_age():
    """Neither was populated, so `max_spread` and `min_days` could not reject
    anything at any threshold: on the live board all 762 rows came back with
    `bid=0, ask=0`, and `listed_days` was assigned nowhere in the module. A
    filter reading a field nothing fills is off however it is configured, and
    the old fixtures hid it by setting both by hand."""
    got = await _source(_FakeExchange()).board()

    assert len(got) == 1
    assert got[0].bid == 99.9
    assert got[0].ask == 100.1
    assert got[0].spread_share > 0
    assert got[0].listed_days == pytest.approx(100.0, abs=1.0)


async def test_a_populated_spread_can_now_be_rejected():
    """The point of carrying it. An impossibly tight threshold has to drop the
    pair - the old board would have kept it."""
    got = await _source(_FakeExchange()).board()

    kept, dropped = Filters(max_spread=1e-9).choose(got)

    assert kept == []
    assert dropped == {"spread too wide": 1}


async def test_an_exchange_without_a_book_still_returns_a_board():
    """Best-effort: an unknown spread costs a pair nothing, which is the
    behaviour `_rejects` was written around."""
    got = await _source(_FakeExchange(bids_asks=False, created=False)).board()

    assert len(got) == 1
    assert got[0].spread_share == 0.0
    assert got[0].listed_days == 0.0
    assert Filters(max_spread=1e-9, min_days=10_000).choose(got)[0] == got


# --------------------------------------------- discovered pairs become feeds


def test_a_discovered_pair_becomes_an_ordinary_feed():
    """`pairs_for` was exported and called by nothing, and no feed carried a
    CCXT symbol - so `ccxt` in PRICES_SOURCES would have started a source with
    no work to do, which looks exactly like an exchange that is down."""
    from till_infinity.prices.config import FEEDS, ccxt_feed_names, register_ccxt_feeds

    added = register_ccxt_feeds(["TESTCOIN/USDT:USDT"])

    assert added == ("testcoin_usdt_usdt",)
    assert "testcoin_usdt_usdt" in ccxt_feed_names()
    # The ccxt pair is kept verbatim: it is what `fetch_ohlcv` answers to.
    assert FEEDS["testcoin_usdt_usdt"].symbols["ccxt"][0].ticker == "TESTCOIN/USDT:USDT"


def test_registering_a_pair_turns_the_source_on():
    """Eleven synthetics were once registered, made tradable, and polled by
    nothing. A pair in the catalogue that no source collects is that bug."""
    from till_infinity.prices.config import bar_source_names, register_ccxt_feeds

    register_ccxt_feeds(["SOURCEON/USDT:USDT"])

    assert "ccxt" in bar_source_names()


def test_the_configured_thresholds_reach_the_filters():
    """Six settings were read from the environment into `Settings` and consulted
    by nothing."""
    from till_infinity.prices.crypto import filters_from

    class _S:
        ccxt_top = 250
        ccxt_min_volume = 1e6
        ccxt_min_days = 30.0
        ccxt_max_spread = 0.002
        ccxt_min_price = 0.01
        ccxt_min_range = 0.005
        ccxt_quotes = ("USDT",)
        ccxt_swaps_only = True

    got = filters_from(_S())

    assert got.top == 250
    assert got.max_spread == 0.002
    assert got.min_days == 30.0
    assert got.quotes == ("USDT",)
