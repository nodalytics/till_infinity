import pytest

from till_infinity.prices import (
    DEFAULT_SYMBOLS,
    TRADINGVIEW,
    YAHOO,
    Symbol,
    resolve_feeds,
    resolve_symbols,
)


def test_defaults_are_eurusd_gbpusd_gold_and_btc():
    assert {feed.name for feed in resolve_symbols(None)} == {"eurusd", "gbpusd", "gold", "btc"}
    assert DEFAULT_SYMBOLS == ("eurusd", "gbpusd", "gold", "btc")


@pytest.mark.parametrize("name", ["gold", "GOLD", "xauusd", "XAU"])
def test_an_instrument_alias_brings_every_broker(name):
    (feed,) = resolve_symbols([name])
    assert feed.name == "gold"
    assert Symbol("OANDA", "XAUUSD") in feed.for_source(TRADINGVIEW)
    assert Symbol("YAHOO", "GC=F") in feed.for_source(YAHOO)


@pytest.mark.parametrize("name", ["btc", "bitcoin", "btcusdt"])
def test_btc_aliases(name):
    assert resolve_symbols([name])[0].name == "btc"


def test_venue_ticker_targets_one_tradingview_series():
    (feed,) = resolve_symbols(["oanda:xauusd"])
    assert feed.for_source(TRADINGVIEW) == (Symbol("OANDA", "XAUUSD"),)
    assert feed.for_source(YAHOO) == ()


def test_a_bare_ticker_goes_to_yahoo():
    (feed,) = resolve_symbols(["AAPL"])
    assert feed.for_source(YAHOO) == (Symbol("YAHOO", "AAPL"),)
    assert feed.for_source(TRADINGVIEW) == ()


def test_an_explicit_yahoo_venue_is_honoured():
    (feed,) = resolve_symbols(["YAHOO:GC=F"])
    assert feed.for_source(YAHOO) == (Symbol("YAHOO", "GC=F"),)
    assert feed.name == "gc_f"


def test_same_instrument_from_two_venues_merges_into_one_feed():
    (feed,) = resolve_symbols(["OANDA:XAUUSD", "PEPPERSTONE:XAUUSD", "OANDA:XAUUSD"])
    assert feed.for_source(TRADINGVIEW) == (
        Symbol("OANDA", "XAUUSD"),
        Symbol("PEPPERSTONE", "XAUUSD"),
    )


def test_tracked_and_ad_hoc_symbols_mix():
    feeds = {feed.name: feed for feed in resolve_symbols(["gold", "NASDAQ:AAPL", "BTC-USD"])}
    assert set(feeds) == {"gold", "aapl", "btc_usd"}
    assert feeds["aapl"].for_source(TRADINGVIEW) == (Symbol("NASDAQ", "AAPL"),)


def test_resolve_feeds_still_looks_up_by_configured_name():
    assert resolve_feeds(("gold",))[0].name == "gold"
    with pytest.raises(ValueError, match="unknown feed"):
        resolve_feeds(("xauusd",))  # an alias, not a feed name
