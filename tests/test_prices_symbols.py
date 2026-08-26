import pytest

from till_infinity.prices import (
    DEFAULT_SYMBOLS,
    TRADINGVIEW,
    YAHOO,
    Symbol,
    resolve_feeds,
    resolve_symbols,
)


def test_the_defaults_are_the_tracked_instruments():
    tracked = {
        "eurusd",
        "gbpusd",
        "usdjpy",
        "audusd",
        "usdcad",
        "usdchf",
        "nzdusd",
        "silver",
        "usdcnh",
        "gold",
        "btc",
        "eth",
        "sol",
        "us100",
        "spx500",
    }
    assert {feed.name for feed in resolve_symbols(None)} == tracked
    assert set(DEFAULT_SYMBOLS) == tracked


@pytest.mark.parametrize(
    ("typed", "feed"),
    [
        ("us100", "us100"),
        ("nas100", "us100"),
        ("nasdaq", "us100"),
        ("NDX", "us100"),
        ("spx500", "spx500"),
        ("us500", "spx500"),
        ("sp500", "spx500"),
        ("S&P500", "spx500"),
        ("SPX", "spx500"),
    ],
)
def test_an_index_answers_to_every_name_people_use(typed, feed):
    """Indices go by more names than anything else, and each is somebody's first."""
    (found,) = resolve_symbols([typed])
    assert found.name == feed


def test_an_index_is_quoted_by_several_venues_like_everything_else():
    """The whole thesis is cross-venue disagreement; one feed would defeat it."""
    for name in ("us100", "spx500"):
        (feed,) = resolve_symbols([name])
        assert len(feed.for_source(TRADINGVIEW)) >= 4
        assert len(feed.for_source(YAHOO)) >= 1


def test_only_venues_that_carry_the_index_are_listed():
    """SAXO and DERIV do not, and asking would log a symbol_error every sweep."""
    (us100,) = resolve_symbols(["us100"])
    venues = {symbol.venue for symbol in us100.for_source(TRADINGVIEW)}
    assert "SAXO" not in venues
    assert "DERIV" not in venues


@pytest.mark.parametrize("name", ["gold", "GOLD", "xauusd", "XAU"])
def test_an_instrument_alias_brings_every_broker(name):
    (feed,) = resolve_symbols([name])
    assert feed.name == "gold"
    assert Symbol("OANDA", "XAUUSD") in feed.for_source(TRADINGVIEW)
    assert Symbol("YAHOO", "GC=F") in feed.for_source(YAHOO)


@pytest.mark.parametrize("name", ["btc", "bitcoin", "btcusdt"])
def test_btc_aliases(name):
    assert resolve_symbols([name])[0].name == "btc"


@pytest.mark.parametrize(
    ("typed", "feed"),
    [
        ("eth", "eth"),
        ("ETH", "eth"),
        ("ether", "eth"),
        ("ethereum", "eth"),
        ("ethusdt", "eth"),
        ("sol", "sol"),
        ("SOL", "sol"),
        ("solana", "sol"),
        ("solusdt", "sol"),
    ],
)
def test_eth_and_sol_answer_to_what_people_call_them(typed, feed):
    assert resolve_symbols([typed])[0].name == feed


@pytest.mark.parametrize(
    ("typed", "feed"),
    [
        ("usdjpy", "usdjpy"),
        ("jpy", "usdjpy"),
        ("yen", "usdjpy"),
        ("aussie", "audusd"),
        ("loonie", "usdcad"),
        ("swissy", "usdchf"),
        ("kiwi", "nzdusd"),
        ("cnh", "usdcnh"),
        ("yuan", "usdcnh"),
    ],
)
def test_the_majors_answer_to_their_desk_names(typed, feed):
    """Nobody asks for USDJPY out loud."""
    assert resolve_symbols([typed])[0].name == feed


def test_the_onshore_yuan_resolves_to_the_offshore_feed():
    """USDCNY is carried by one venue of ours, which is below the quorum.

    A consensus bar needs three venues, so a `usdcny` feed would form no levels
    and would do it silently - the failure that looks exactly like a quiet
    market. CNH is what the six venues actually quote.
    """
    (feed,) = resolve_symbols(["usdcny"])
    assert feed.name == "usdcnh"
    tickers = {symbol.ticker for symbol in feed.for_source(TRADINGVIEW)}
    assert tickers == {"USDCNH"}
    assert len(feed.for_source(TRADINGVIEW)) >= 3


def test_every_major_is_quoted_by_enough_venues_to_reach_quorum():
    """Three venues before a consensus close is usable; below that, nothing forms."""
    for name in ("usdjpy", "audusd", "usdcad", "usdchf", "nzdusd", "usdcnh"):
        (feed,) = resolve_symbols([name])
        assert len(feed.for_source(TRADINGVIEW)) >= 3, name
        assert len(feed.for_source(YAHOO)) >= 1, name


def test_the_crypto_feeds_carry_the_same_venues():
    """One venue would defeat the cross-venue consensus the whole model rests on.

    Every symbol here was checked against the live socket before being listed,
    including Bybit - which quotes BTC and ETH in both USD and USDT but SOL
    only in USDT, so USDT is what all three share.
    """
    for name in ("btc", "eth", "sol"):
        (feed,) = resolve_symbols([name])
        venues = {symbol.venue for symbol in feed.for_source(TRADINGVIEW)}
        assert {"BINANCE", "BYBIT", "COINBASE", "BITSTAMP", "KRAKEN", "DERIV"} <= venues
        assert len(feed.for_source(YAHOO)) >= 1

    (sol,) = resolve_symbols(["sol"])
    assert Symbol("BYBIT", "SOLUSDT") in sol.for_source(TRADINGVIEW)
    assert Symbol("BYBIT", "SOLUSD") not in sol.for_source(TRADINGVIEW)


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
