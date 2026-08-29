"""The broker's own book as a price source.

Every other source is somebody else's opinion of the price. This one is the
book we deal on, and it is the only way to reach instruments no consensus venue
carries - synthetics above all, which have no underlying and so no other source
by construction.
"""

import os

import pytest

from till_infinity.prices.config import (
    BROKER,
    FEEDS,
    broker_feeds,
    register_broker_feeds,
)
from till_infinity.prices.quotes import (
    DEFAULT_QUOTE_SOURCES,
    QUOTE_SOURCES,
    BrokerQuotes,
)


def test_the_broker_source_is_off_unless_asked_for():
    """It needs a bridge that only exists where a terminal is reachable, and a
    deployment without one should not be failing on every symbol."""
    assert BROKER in QUOTE_SOURCES
    assert BROKER not in DEFAULT_QUOTE_SOURCES


def test_it_polls_because_there_is_no_stream():
    """The bridge publishes no websocket and no SSE. Its only `subscribe` is
    market depth, which is still read by polling."""
    assert BrokerQuotes.streaming is False


def test_a_broker_symbol_keeps_its_own_name():
    """`Volatility 75 Index`, not a guess at what it might be called
    elsewhere - the broker's name is the only one that resolves."""
    made = broker_feeds(["Volatility 75 Index"])
    feed = made["volatility_75_index"]
    assert feed.symbols[BROKER][0].ticker == "Volatility 75 Index"


def test_feed_names_are_slugs_because_they_travel():
    """Feed names go through journal keys and log lines, where spaces are a
    nuisance."""
    made = broker_feeds(["Boom 1000 Index", "Step Index"])
    assert sorted(made) == ["boom_1000_index", "step_index"]


def test_blank_and_duplicate_names_are_dropped():
    made = broker_feeds(["", "  ", "Step Index", "step index"])
    assert list(made) == ["step_index"]


def test_registering_does_not_clobber_an_existing_feed():
    """`FEEDS` is what every alias lookup reads. A broker symbol that collides
    with a configured feed must not replace it."""
    before = FEEDS["gold"]
    added = register_broker_feeds(["gold"])
    assert added == ()
    assert FEEDS["gold"] is before


def test_registering_adds_the_feed_to_the_catalogue():
    added = register_broker_feeds(["Test Only Index"])
    try:
        assert added == ("test_only_index",)
        assert "test_only_index" in FEEDS
    finally:
        FEEDS.pop("test_only_index", None)


async def test_it_will_not_start_without_a_bridge():
    """Loud rather than quietly returning nothing: a source that cannot reach
    its transport has no business pretending to poll."""
    source = BrokerQuotes(settings=None)
    was = os.environ.pop(BrokerQuotes.URL_VAR, None)
    try:
        with pytest.raises(RuntimeError, match=BrokerQuotes.URL_VAR):
            await source.__aenter__()
    finally:
        if was is not None:
            os.environ[BrokerQuotes.URL_VAR] = was


async def test_a_symbol_must_be_selected_before_it_will_quote():
    """MT5 only streams ticks for symbols in Market Watch. An unselected one
    answers with `bid 0.0, ask 0.0, time 0` - HTTP 200, well-formed and empty -
    so skipping this would poll happily and publish nothing.

    Measured against the live bridge: `Volatility 75 Index` read zero, and
    51418.35/51436.01 one second after a select.
    """
    from till_infinity.prices.models import QuoteKey, Symbol

    picked: list[str] = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def post(self, path):
            picked.append(path)
            return FakeResponse()

    source = BrokerQuotes(settings=None)
    source._client = FakeClient()
    keys = [
        QuoteKey(BROKER, "volatility_75_index", Symbol("BROKER", "Volatility 75 Index")),
        QuoteKey(BROKER, "step_index", Symbol("BROKER", "Step Index")),
    ]

    await source.prepare(keys)

    assert picked == [
        "/api/v1/symbols/select/Volatility 75 Index",
        "/api/v1/symbols/select/Step Index",
    ]


async def test_an_empty_quote_is_no_quote():
    """`bid 0.0, ask 0.0` is what an unselected or shut symbol returns, and it
    is not a price."""
    from till_infinity.prices.models import Symbol

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"bid": 0.0, "ask": 0.0, "time": 0}

    class FakeClient:
        async def get(self, path):
            return FakeResponse()

    source = BrokerQuotes(settings=None)
    source._client = FakeClient()
    assert await source.quote(Symbol("BROKER", "Boom 1000 Index")) is None
