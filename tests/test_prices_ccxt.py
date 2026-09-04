"""Choosing which crypto pairs are worth carrying."""

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
