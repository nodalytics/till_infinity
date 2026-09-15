"""Constructed spreads: the arithmetic, and the four ways it could lie.

The arithmetic is checked against a quantity with an independent answer -
`ln(EURUSD) - ln(GBPUSD)` is `ln(EURGBP)` exactly, so a constructed cross can be
compared with the ratio it must equal rather than with itself.

The four failure modes each have a test because each was a decision:

* **Forward-filling a missing leg** manufactures a spread move that never
  happened, on a series whose whole content is the difference between two
  nearly equal numbers.
* **Pairing the legs' extremes** assumes they peaked together. `high` is built
  from a finer interval where one exists and is `max(open, close)` where none
  does, which understates rather than invents.
* **Mixing two providers** mixes two clocks: every timestamp stored here is our
  own receive clock, so a cross-source spread carries the skew as if it were
  price.
* **Calling an unholdable series tradeable.** Two legs at two venues is two
  accounts. This desk has one.
"""

from __future__ import annotations

import math
import sqlite3

import pytest

from till_infinity.prices import spreads as sp

SCHEMA = """
CREATE TABLE bars (
    source TEXT NOT NULL, feed TEXT NOT NULL, venue TEXT NOT NULL,
    ticker TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume REAL, closed INTEGER NOT NULL DEFAULT 1, updated INTEGER NOT NULL,
    PRIMARY KEY (source, feed, venue, ticker, interval, ts)
) WITHOUT ROWID
"""


def store(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT INTO bars(source, feed, venue, ticker, interval, ts,"
        " open, high, low, close, volume, closed, updated)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,NULL,1,0)",
        rows,
    )
    conn.commit()
    return conn


def _counter(steps):
    """A progress handler that tallies engine steps and never aborts."""

    def tick():
        steps[0] += 1

    return tick


def series(feed, venue, prices, *, source="tradingview", interval="1m", step=60, start=0):
    """One leg, one bar per price, open and close both at that price."""
    return [
        (source, feed, venue, feed.upper(), interval, start + i * step, p, p, p, p)
        for i, p in enumerate(prices)
    ]


class TestArithmetic:
    def test_a_cross_equals_the_ratio_it_implies(self):
        """`ln(EURUSD) - ln(GBPUSD) = ln(EURGBP)`, with no residual."""
        eur, gbp = [1.0850, 1.0862, 1.0841], [1.2700, 1.2688, 1.2715]
        conn = store(series("eurusd", "DERIV", eur) + series("gbpusd", "DERIV", gbp))
        spread = sp.Spread(
            "eurgbp_deriv",
            (sp.Leg("eurusd", "DERIV", 1.0), sp.Leg("gbpusd", "DERIV", -1.0)),
            kind="cross",
        )
        built = sp.construct(conn, spread, "1m")
        assert len(built.bars) == 3
        for bar, e, g in zip(built.bars, eur, gbp, strict=True):
            assert bar.close / sp.BASE == pytest.approx(e / g, rel=1e-12)

    def test_the_published_log_returns_are_the_spread_s_own_increments(self):
        """The reason the map is `BASE * exp(s)` and not `BASE + s * 100`.

        Every estimator downstream reads log returns, so the published series
        has to have the spread's increments *as* its log returns - exactly, not
        approximately.
        """
        a, b = [100.0, 104.0, 101.0], [50.0, 51.0, 53.0]
        conn = store(series("x", "V", a) + series("y", "V", b))
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        closes = [bar.close for bar in sp.construct(conn, spread, "1m").bars]
        for i in range(len(closes) - 1):
            published = math.log(closes[i + 1]) - math.log(closes[i])
            actual = (math.log(a[i + 1]) - math.log(b[i + 1])) - (math.log(a[i]) - math.log(b[i]))
            assert published == pytest.approx(actual, rel=1e-12)

    def test_a_leg_at_zero_or_below_produces_no_bar(self):
        conn = store(series("x", "V", [100.0, 100.0]) + series("y", "V", [50.0, 50.0]))
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        assert spread.price([100.0, 0.0]) is None
        assert spread.price([-1.0, 50.0]) is None
        assert sp.construct(conn, spread, "1m").bars

    def test_a_weighting_that_overflows_is_refused_rather_than_priced(self):
        spread = sp.Spread("silly", (sp.Leg("x", "V", 400.0),))
        assert spread.price([100.0]) is None


class TestMissingLegs:
    def test_a_bucket_with_one_leg_is_dropped_not_filled(self):
        """The single most dangerous thing this module could do."""
        conn = store(
            series("x", "V", [100.0, 101.0, 102.0])
            # `y` is missing its middle bar.
            + [r for i, r in enumerate(series("y", "V", [50.0, 50.0, 50.0])) if i != 1]
        )
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        built = sp.construct(conn, spread, "1m")
        assert [bar.time for bar in built.bars] == [0, 120]
        assert built.dropped == 1

    def test_no_overlap_at_all_builds_nothing(self):
        conn = store(
            series("x", "V", [100.0, 101.0], start=0) + series("y", "V", [50.0, 50.0], start=10_000)
        )
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        assert sp.construct(conn, spread, "1m").bars == []

    def test_a_leg_with_no_bars_at_all_builds_nothing(self):
        conn = store(series("x", "V", [100.0, 101.0]))
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        assert sp.construct(conn, spread, "1m").bars == []


class TestRange:
    def test_the_finest_interval_reports_its_range_as_inexact(self):
        conn = store(series("x", "V", [100.0, 101.0]) + series("y", "V", [50.0, 50.0]))
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        built = sp.construct(conn, spread, "1m")
        assert built.exact_range is False
        for bar in built.bars:
            assert bar.high == max(bar.open, bar.close)
            assert bar.low == min(bar.open, bar.close)

    def test_aggregating_from_a_finer_interval_finds_the_real_extremes(self):
        """A move that happens inside the bucket and comes back is invisible at
        the coarse interval and is exactly what a range estimator is for."""
        inside = [100.0, 130.0, 100.0, 100.0]
        conn = store(series("x", "V", inside) + series("y", "V", [50.0] * 4))
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        built = sp.aggregate(conn, spread, "5m", base="1m", seconds=300)
        assert built.exact_range is True
        assert built.built_from == "1m"
        assert len(built.bars) == 1
        bar = built.bars[0]
        assert bar.open == pytest.approx(bar.close)
        assert bar.high > bar.open, "the excursion inside the bucket is the whole point"
        assert bar.high / bar.open == pytest.approx(1.3, rel=1e-9)

    def test_the_aggregate_bar_takes_its_endpoints_from_the_bucket_s_endpoints(self):
        conn = store(
            series("x", "V", [100.0, 110.0, 120.0, 130.0, 140.0]) + series("y", "V", [50.0] * 5)
        )
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        bar = sp.aggregate(conn, spread, "5m", base="1m", seconds=300).bars[0]
        assert bar.open / sp.BASE == pytest.approx(100.0 / 50.0)
        assert bar.close / sp.BASE == pytest.approx(140.0 / 50.0)

    def test_a_spread_carries_no_volume(self):
        conn = store(series("x", "V", [100.0, 101.0]) + series("y", "V", [50.0, 50.0]))
        spread = sp.Spread("xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        assert all(bar.volume is None for bar in sp.construct(conn, spread, "1m").bars)


class TestDiscovery:
    @pytest.fixture
    def conn(self):
        return store(
            series("btc", "BINANCE", [100.0] * 5)
            + series("btc", "KRAKEN", [100.0] * 5)
            + series("btc", "YAHOO", [100.0] * 5, source="yahoo")
            + series("eurusd", "DERIV", [1.08] * 5)
            + series("gbpusd", "DERIV", [1.27] * 5)
        )

    def test_same_source_pairs_only_by_default(self, conn):
        found = sp.venue_pairs(conn, min_shared=1)
        names = {s.name for s in found}
        assert names == {"btc_binance_kraken"}, "YAHOO is a different provider and clock"

    def test_cross_source_is_opt_in(self, conn):
        found = sp.venue_pairs(conn, min_shared=1, cross_source=True)
        assert len(found) == 3

    def test_every_discovered_leg_can_use_the_index(self, conn):
        for spread in sp.venue_pairs(conn, min_shared=1, cross_source=True):
            assert all(leg.indexed for leg in spread.legs)

    def test_a_thin_leg_is_not_paired(self, conn):
        assert sp.venue_pairs(conn, min_shared=100) == []

    def test_crosses_come_from_the_catalogue_and_one_venue(self, conn):
        found = sp.crosses(conn, min_shared=1)
        assert [s.name for s in found] == ["eurgbp_deriv"]
        assert {leg.venue for leg in found[0].legs} == {"DERIV"}

    def test_catalogue_refuses_a_kind_it_does_not_have(self, conn, caplog):
        assert sp.catalogue(conn, kinds=("nonsense",), min_shared=1) == []
        assert "no such spread kind" in caplog.text


class TestTradeable:
    def test_two_venues_is_two_accounts(self):
        spread = sp.Spread(
            "btc_binance_kraken",
            (sp.Leg("btc", "BINANCE", 1.0), sp.Leg("btc", "KRAKEN", -1.0)),
        )
        assert spread.tradeable is False

    def test_one_venue_the_desk_trades_is_holdable(self):
        spread = sp.Spread(
            "eurgbp_deriv",
            (sp.Leg("eurusd", "DERIV", 1.0), sp.Leg("gbpusd", "DERIV", -1.0)),
        )
        assert spread.tradeable is True

    def test_one_venue_the_desk_does_not_trade_is_not(self):
        """An observable series at a single venue is still not a position."""
        spread = sp.Spread(
            "eurgbp_binance",
            (sp.Leg("eurusd", "BINANCE", 1.0), sp.Leg("gbpusd", "BINANCE", -1.0)),
        )
        assert spread.tradeable is False


class TestRegistration:
    def test_a_registered_spread_becomes_an_ordinary_feed(self):
        from till_infinity.prices.config import FEEDS

        spread = sp.Spread("test_spread_xy", (sp.Leg("x", "V", 1.0), sp.Leg("y", "V", -1.0)))
        try:
            assert sp.register([spread]) == ("test_spread_xy",)
            assert FEEDS["test_spread_xy"].for_source(sp.SOURCE) == (spread.symbol,)
            assert sp.definition("test_spread_xy") is spread
            assert sp.register([spread]) == (), "registering twice adds nothing"
        finally:
            FEEDS.pop("test_spread_xy", None)
            sp._CONSTRUCTED.pop("test_spread_xy", None)

    def test_an_ordinary_feed_has_no_definition(self):
        assert sp.definition("gold") is None


class TestNamedPairs:
    """Discovery is right for "what could be built" and wrong for "build these".

    `btc` alone yields ten venue pairs from five venues and the whole book
    yields hundreds; adding those to the store and to whatever `structures` is
    admitting is a decision rather than a side effect. A spec names what is
    wanted.

    **The syntax is the one `STRUCTURES_SPREAD_QUOTES` takes**, deliberately,
    so one spread's bar series and quote series are configured alike - the
    comparison between them is the whole reason both exist, and it would be
    undermined by having to check whether two configs mean the same pair.
    """

    SPEC = "a=btc@BINANCE-btc@COINBASE,b=btc@COINBASE-btc@KRAKEN"

    def test_it_parses_what_it_is_given(self):
        got = sp.named(self.SPEC)
        assert [s.name for s in got] == ["a", "b"]
        assert [(leg.feed, leg.venue) for leg in got[0].legs] == [
            ("btc", "BINANCE"),
            ("btc", "COINBASE"),
        ]

    def test_the_weights_make_it_a_difference(self):
        got = sp.named("a=btc@X-btc@Y")[0]
        assert [leg.weight for leg in got.legs] == [1.0, -1.0]

    def test_a_malformed_entry_is_skipped_not_raised(self):
        """A typo in one pair should not stop a collector starting."""
        assert [s.name for s in sp.named("good=btc@X-btc@Y,rubbish,half=btc@X")] == ["good"]

    def test_nothing_named_is_nothing_built(self):
        assert sp.named("") == []

    def test_a_named_pair_wins_over_discovery(self):
        conn = store(
            series("btc", "BINANCE", [100.0] * 5)
            + series("btc", "KRAKEN", [100.0] * 5)
            + series("eurusd", "DERIV", [1.08] * 5)
            + series("gbpusd", "DERIV", [1.27] * 5)
        )
        # Discovery would find the eurgbp cross; the spec asks for something else.
        got = sp.catalogue(conn, pairs="x=btc@BINANCE-btc@KRAKEN", min_shared=1)
        assert [s.name for s in got] == ["x"]

    def test_a_named_leg_is_addressed_through_the_index(self):
        """Without `(source, ticker)` the leg query cannot use `bars_series_ts`
        and scans a table that is 22GB on production."""
        conn = store(series("btc", "BINANCE", [100.0] * 5) + series("btc", "KRAKEN", [100.0] * 5))
        got = sp.catalogue(conn, pairs="x=btc@BINANCE-btc@KRAKEN", min_shared=1)
        assert all(leg.indexed for leg in got[0].legs)

    def test_a_pair_naming_a_venue_with_no_bars_builds_nothing(self):
        conn = store(series("btc", "BINANCE", [100.0] * 5))
        assert sp.catalogue(conn, pairs="x=btc@BINANCE-btc@NOWHERE", min_shared=1) == []

    def test_resolving_named_legs_does_not_depend_on_how_much_is_stored(self):
        """The cost of "where does this leg live" must not scale with the store.

        Answering it from a census of every stored series is a full pass over
        `bars`, which is 23GB on production. Taken at the top of the collector,
        before its first `await`, that pass held the event loop every actor
        shares and the desk wrote no quotes for as long as it ran.
        """
        spec = "x=btc@BINANCE-btc@KRAKEN"
        rows = series("btc", "BINANCE", [100.0] * 5) + series("btc", "KRAKEN", [100.0] * 5)
        done = []
        for decoys in (2, 60):
            noise = []
            for i in range(decoys):
                noise += series(f"junk{i}", "DERIV", [1.0] * 40)
            conn = store(rows + noise)
            # Steps of the query engine itself, which is what a scan spends and
            # a seek does not - counting statements would not tell them apart.
            steps = [0]
            conn.set_progress_handler(_counter(steps), 10)
            assert [s.name for s in sp.catalogue(conn, pairs=spec, min_shared=1)] == ["x"]
            conn.set_progress_handler(None, 0)
            done.append(steps[0])
        assert done[1] <= done[0] * 1.2, f"the lookup read the whole store: {done}"

    def test_the_longest_running_ticker_wins_when_a_venue_carries_two(self):
        """Two legs of the same asset at the same venue is not a spread, so one
        of the tickers has to win - and the one with history is the one worth
        building from."""
        deep = [
            ("tradingview", "btc", "BINANCE", "BTCUSDT", "1m", i * 60, 100.0, 100.0, 100.0, 100.0)
            for i in range(50)
        ]
        shallow = [
            ("tradingview", "btc", "BINANCE", "BTCUSD", "1m", i * 60, 100.0, 100.0, 100.0, 100.0)
            for i in range(3)
        ]
        conn = store(deep + shallow + series("btc", "KRAKEN", [100.0] * 50))
        got = sp.catalogue(conn, pairs="x=btc@BINANCE-btc@KRAKEN", min_shared=1)
        assert [leg.ticker for leg in got[0].legs] == ["BTCUSDT", "BTC"]
