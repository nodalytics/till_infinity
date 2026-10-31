"""The z-score on constructed spreads, fed from quotes instead of bars.

`research/constructing.md` measured AUC 0.6985 against 0.5031 on cross-venue
spreads - the only positive directional result in that folder - on **1-minute
bars**. What those spreads revert by is arbitrage between two venues, which
operates in seconds, so a 1m close samples the process once and misses most of
it.

The danger in reading it live is precise and easy to commit: a spread is the
difference between two nearly equal numbers, so **pairing a fresh quote with a
stale one manufactures a move that never happened**. It is the same defect
`prices/spreads.py` refuses at the bar level by dropping a bucket where a leg
is missing, arriving in a form where nothing about the arithmetic complains.
"""

from __future__ import annotations

import pytest

from till_infinity.structures import spreadquotes as sq


def watcher() -> sq.Watcher:
    return sq.Watcher(pairs=(sq.Pair("btc_binance_coinbase", "btc", "BINANCE", "btc", "COINBASE"),))


class TestParsing:
    def test_it_reads_a_pair(self):
        got = sq.parse("btc_a_b=btc@BINANCE-btc@COINBASE")
        assert len(got) == 1
        assert got[0].name == "btc_a_b"
        assert (got[0].feed_a, got[0].venue_a) == ("btc", "BINANCE")
        assert (got[0].feed_b, got[0].venue_b) == ("btc", "COINBASE")

    def test_nothing_configured_watches_nothing(self):
        assert sq.parse("") == []
        assert sq.parse("   ") == []

    def test_a_malformed_entry_is_skipped_not_raised(self, caplog):
        """A diagnostic reading nothing gates on must not stop a desk starting."""
        got = sq.parse("good=btc@BINANCE-btc@KRAKEN,nonsense,also=bad")
        assert [p.name for p in got] == ["good"]

    def test_several_pairs(self):
        got = sq.parse("a=btc@X-btc@Y, b=eth@X-eth@Y")
        assert [p.name for p in got] == ["a", "b"]


class TestPricing:
    def test_the_published_price_carries_the_spread_as_its_log_return(self):
        """`BASE * exp(ln a - ln b)`, the same map `prices/spreads.py` uses, so
        the quote series and the bar series describe one quantity on one scale."""
        pair = sq.Pair("x", "a", "V", "b", "V")
        import math

        got = pair.price(62_000.0, 61_995.0)
        assert math.log(got / sq.BASE) == pytest.approx(math.log(62_000.0) - math.log(61_995.0))

    def test_a_leg_at_zero_prices_nothing(self):
        pair = sq.Pair("x", "a", "V", "b", "V")
        assert pair.price(0.0, 100.0) is None
        assert pair.price(100.0, -1.0) is None


class TestStaleness:
    def test_simultaneous_quotes_produce_a_reading(self):
        w = watcher()
        w.observe({"feed": "btc", "venue": "BINANCE", "mid": 62_000.0, "time": 1000.0})
        got = w.observe({"feed": "btc", "venue": "COINBASE", "mid": 61_995.0, "time": 1000.4})
        assert [n for n, _ in got] == ["btc_binance_coinbase"]

    def test_a_stale_partner_produces_nothing_and_is_counted(self):
        """**The rule this module exists for.** A fresh quote against one ten
        seconds old is a manufactured move on a difference of two nearly equal
        numbers."""
        w = watcher()
        w.observe({"feed": "btc", "venue": "BINANCE", "mid": 62_000.0, "time": 1000.0})
        got = w.observe({"feed": "btc", "venue": "COINBASE", "mid": 61_995.0, "time": 1020.0})
        assert got == []
        assert w.stale == 1

    def test_one_leg_alone_produces_nothing(self):
        w = watcher()
        assert w.observe({"feed": "btc", "venue": "BINANCE", "mid": 62_000.0, "time": 1.0}) == []

    def test_a_pair_that_skips_most_ticks_says_so(self):
        """A pair skipping most of its ticks is not a spread - it is two
        instruments that rarely quote together, and the counter is how anybody
        would find out."""
        w = watcher()
        for i in range(10):
            w.observe({"feed": "btc", "venue": "BINANCE", "mid": 62_000.0, "time": i * 100.0})
            w.observe({"feed": "btc", "venue": "COINBASE", "mid": 61_995.0, "time": i * 100.0 + 50})
        assert w.emitted == 0
        assert w.stale > 0
        assert w.to_dict()["skipped_stale"] == w.stale


class TestIsolation:
    def test_an_unrelated_feed_is_ignored(self):
        w = watcher()
        assert w.observe({"feed": "gold", "venue": "OANDA", "mid": 4400.0, "time": 1.0}) == []

    def test_a_quote_with_no_mid_is_ignored(self):
        w = watcher()
        assert w.observe({"feed": "btc", "venue": "BINANCE", "time": 1.0}) == []
        assert w.observe({"feed": "btc", "venue": "BINANCE", "mid": 0.0, "time": 1.0}) == []

    def test_readings_land_under_their_own_interval(self):
        """Two records, scored apart: one about a minutely close and one about
        a quote. Merged they would describe neither, and it is the bar record
        `TRADING_ZMA_GATE` reads."""
        from till_infinity.structures.zma import Book

        book = Book()
        w = watcher()
        w.observe({"feed": "btc", "venue": "BINANCE", "mid": 62_000.0, "time": 1000.0})
        for name, price in w.observe(
            {"feed": "btc", "venue": "COINBASE", "mid": 61_995.0, "time": 1000.1}
        ):
            book.observe(name, sq.INTERVAL, price)
        assert ("btc_binance_coinbase", "tick") in book._by_key
        assert ("btc_binance_coinbase", "1m") not in book._by_key

    def test_it_does_nothing_when_no_pairs_are_configured(self):
        w = sq.Watcher()
        assert w.observe({"feed": "btc", "venue": "BINANCE", "mid": 1.0, "time": 1.0}) == []
        assert w.emitted == 0
