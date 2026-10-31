"""Mapping a headline's symbols onto the instruments we price."""

from __future__ import annotations

from till_infinity.news.symbols import feed_for, feeds_for


def test_the_venue_half_is_ignored():
    """The same instrument arrives under whichever venue the publisher cited."""
    for symbol in ("BITSTAMP:BTCUSD", "BINANCE:BTCUSDT", "COINBASE:BTC-USD", "BTCUSD"):
        assert feed_for(symbol) == "btc", symbol
    for symbol in ("FX:EURUSD", "FX_IDC:EURUSD", "BITSTAMP:EURUSD"):
        assert feed_for(symbol) == "eurusd", symbol


def test_venue_decorations_are_stripped():
    """Settlement suffixes, simulated feeds and continuous futures."""
    assert feed_for("FTMO_OANDA:EURUSD.SIM") == "eurusd"
    assert feed_for("RUS:EURUSD_TOD") == "eurusd"
    assert feed_for("RUS:EURUSDTDTM") == "eurusd"
    assert feed_for("TVC:GOLD") == "gold"


def test_an_instrument_we_do_not_price_maps_to_nothing():
    """The correct answer, not a gap.

    Mapping `USDINR` to `usdjpy` because both are dollar pairs would invent a
    relationship. A headline about something unpriced cannot be joined to
    anything, and saying so is the honest outcome.
    """
    for symbol in ("BITSTAMP:XRPUSD", "ICEUS:DXY", "NASDAQ:COIN", "FX_IDC:USDINR"):
        assert feed_for(symbol) == "", symbol


def test_a_near_miss_is_not_a_match():
    """A shared prefix is not a match, however much of the alphabet is shared.

    This used to use EURJPY, EURGBP and EURCHF as the near misses, and they are
    tracked instruments now - so the examples moved to crosses that are still
    not carried rather than the assertion being softened. `eurusd` is the one
    they must not be mistaken for.
    """
    assert feed_for("FX:EURSEK") == ""
    assert feed_for("FX:EURNOK") == ""
    assert feed_for("FX:EURMXN") == ""
    # And the ones that are tracked resolve to themselves, not to eurusd.
    assert feed_for("FX:EURJPY") == "eurjpy"
    assert feed_for("FX:EURGBP") == "eurgbp"


def test_a_short_ticker_cannot_claim_a_longer_one():
    """Prefix matching below six characters collides with far too much."""
    assert feed_for("TVC:SPXSOMETHINGELSE") == ""


def test_one_instrument_tagged_twice_is_one_instrument():
    assert feeds_for(["FX:EURUSD", "BITSTAMP:EURUSD", "FX_IDC:EURUSD"]) == ["eurusd"]


def test_a_headline_about_several_instruments_returns_all_of_them():
    assert feeds_for(["FX:EURUSD", "BITSTAMP:BTCUSD", "ICEUS:DXY"]) == ["btc", "eurusd"]


def test_nothing_in_is_nothing_out():
    assert feeds_for(None) == []
    assert feeds_for([]) == []
    assert feed_for("") == ""


def test_the_map_comes_from_prices_rather_than_a_second_list():
    """A table written here would go stale the first time a venue was added."""
    from till_infinity.prices.config import FEEDS

    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for symbol in group:
                assert feed_for(f"ANYVENUE:{symbol.ticker}") == name, symbol.ticker
