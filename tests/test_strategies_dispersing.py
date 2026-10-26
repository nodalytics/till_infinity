"""The statespace-native strategy: a surprise, entered on continuation.

The gate under test is **cost**. Every edge measured this month died on cost
rather than on significance - 57 cross-sectional cells whose best breakeven was
16.88 bp against a 74.91 bp spread - and the anomaly edge this strategy trades
is +0.1436R **gross**. So a refusal when the spread eats the edge is the part
of this strategy that does the work, and it is checked before the geometry.
"""

from __future__ import annotations

import pytest

from till_infinity.trading.config import MAGIC_ORDER, Settings, magic_for
from till_infinity.trading.models import Intent, Refusal, Side, SymbolSpec, Tick
from till_infinity.trading.strategies.dispersing import Dispersing

SPEC = SymbolSpec(symbol="EURUSD", digits=5, point=0.00001, tick_size=0.00001)


def _tick(bid: float = 1.10000, ask: float = 1.10002) -> Tick:
    return Tick(symbol="EURUSD", bid=bid, ask=ask)


def _proposal(**over) -> dict:
    features = {
        "vol_bps": 20.0,
        "surprise": 4.0,
        "stop_vol": 2.0,
        "target_r": 2.0,
        "probability": 0.4,
        "base_rate_up": 0.5,
    }
    features.update(over.pop("features", {}))
    payload = {
        "feed": "eurusd",
        "interval": "5m",
        "direction": 1,
        "shape": "statespace",
        "detail": "a big move just printed",
        "confluence": ("statespace:surprise",),
        "features": features,
    }
    payload.update(over)
    return payload


def _engine(**over) -> Dispersing:
    return Dispersing(Settings(**over))


def _consider(engine: Dispersing, payload: dict, tick: Tick | None = None):
    return engine.consider(payload, spec=SPEC, tick=tick or _tick(), equity=10_000.0)


class TestItReadsOnlyStatespaceProposals:
    def test_it_wants_the_statespace_shape_on_a_listed_feed(self) -> None:
        assert _engine().wants({"shape": "statespace", "feed": "eurusd"}) is True

    def test_the_shape_alone_is_not_enough(self) -> None:
        """A payload with no feed is not this strategy's. See `feeds`."""
        assert _engine().wants({"shape": "statespace"}) is False

    def test_it_ignores_every_structures_shape(self) -> None:
        engine = _engine()
        for shape in ("level", "drift", "agent", "trade", ""):
            assert engine.wants({"shape": shape, "feed": "eurusd"}) is False


class TestTheGates:
    def test_a_small_surprise_is_refused_under_its_own_gate(self) -> None:
        got = _consider(_engine(), _proposal(features={"surprise": 1.0}))
        assert isinstance(got, Refusal)
        assert got.gate == "surprise"

    def test_a_bar_with_no_side_is_refused(self) -> None:
        got = _consider(_engine(), _proposal(direction=0))
        assert isinstance(got, Refusal)
        assert got.gate == "direction"

    def test_a_wide_spread_is_refused_before_any_geometry(self) -> None:
        """**The gate that decides this strategy.**

        vol_bps 20 on a 1.10 price is a 0.00220 volatility unit, so a 2-sigma
        stop is 0.00440. A 0.00100 spread is 22.7% of that, over the 10% the
        edge can absorb.
        """
        got = _consider(_engine(), _proposal(), _tick(1.10000, 1.10100))
        assert isinstance(got, Refusal)
        assert got.gate == "cost"
        assert "22" in got.detail

    def test_a_tight_spread_passes_the_cost_gate(self) -> None:
        got = _consider(_engine(), _proposal(), _tick(1.10000, 1.10002))
        assert isinstance(got, Intent)

    def test_the_cost_gate_scales_with_volatility_not_with_price(self) -> None:
        """The same spread passes on a loud feed and fails on a quiet one."""
        wide = _tick(1.10000, 1.10020)
        quiet = _consider(_engine(), _proposal(features={"vol_bps": 2.0}), wide)
        loud = _consider(_engine(), _proposal(features={"vol_bps": 60.0}), wide)
        assert isinstance(quiet, Refusal)
        assert quiet.gate == "cost"
        assert isinstance(loud, Intent)

    def test_a_zero_volatility_is_refused_rather_than_dividing_by_it(self) -> None:
        got = _consider(_engine(), _proposal(features={"vol_bps": 0.0}))
        assert isinstance(got, Refusal)
        assert got.gate == "volatility"

    def test_features_that_are_not_a_dict_are_refused_not_crashed(self) -> None:
        got = _consider(_engine(), _proposal(features={}) | {"features": "nope"})
        assert isinstance(got, Refusal)
        assert got.gate == "features"

    def test_unparseable_numbers_do_not_raise(self) -> None:
        got = _consider(_engine(), _proposal(features={"surprise": "big"}))
        assert isinstance(got, Refusal)
        assert got.gate == "surprise"


class TestTheGeometry:
    def test_the_stop_is_the_proposed_volatility_distance(self) -> None:
        got = _consider(_engine(), _proposal())
        assert isinstance(got, Intent)
        # vol_bps 20 at 1.10002 -> unit 0.00220, 2 sigma -> 0.00440.
        unit = 20.0 / 1e4 * got.entry
        assert abs(got.entry - got.stop) == pytest.approx(2.0 * unit, rel=1e-9)

    def test_the_target_is_the_proposed_reward_to_risk(self) -> None:
        got = _consider(_engine(), _proposal())
        assert isinstance(got, Intent)
        risk = abs(got.entry - got.stop)
        assert abs(got.target - got.entry) == pytest.approx(2.0 * risk, rel=1e-6)

    def test_a_long_enters_at_the_ask_with_the_stop_below(self) -> None:
        got = _consider(_engine(), _proposal(direction=1))
        assert isinstance(got, Intent)
        assert got.side is Side.BUY
        assert got.entry == pytest.approx(1.10002)
        assert got.stop < got.entry < got.target

    def test_a_short_enters_at_the_bid_with_the_stop_above(self) -> None:
        got = _consider(_engine(), _proposal(direction=-1))
        assert isinstance(got, Intent)
        assert got.side is Side.SELL
        assert got.entry == pytest.approx(1.10000)
        assert got.target < got.entry < got.stop

    def test_it_fires_on_either_sign_of_the_variance_surprise(self) -> None:
        """`surprise` is signed and the gate is on its magnitude.

        The side comes from `direction`, which is the **bar's** body, not from
        the sign of a log-variance innovation. A negative surprise with an up
        bar is a long, and that is the point rather than an oddity.
        """
        got = _consider(_engine(), _proposal(features={"surprise": -4.0}, direction=1))
        assert isinstance(got, Intent)
        assert got.side is Side.BUY

    def test_the_reason_and_features_are_carried_for_the_journal(self) -> None:
        got = _consider(_engine(), _proposal())
        assert isinstance(got, Intent)
        assert got.reason == "a big move just printed"
        assert got.features["vol_bps"] == 20.0
        assert got.features["surprise"] == 4.0
        assert got.confluence == ("statespace:surprise",)


class TestItCanBeScored:
    def test_it_has_an_invertible_magic_slot(self) -> None:
        """Without one, every close reads "unattributed" for ever.

        `MAGIC_ORDER`'s own comment records two strategies that ran live for an
        hour without a slot; their trades cannot be attributed in the record.
        """
        from till_infinity.trading.config import strategy_for

        assert "statespace-surprise" in MAGIC_ORDER
        base = 777_701
        magic = magic_for(base, "statespace-surprise")
        # **The round trip, not the formula.** Asserting `base + index` is how
        # this test first failed, by exactly the off-by-one that
        # `judge-the-desk-on-the-broker-not-the-journal` records as relabelling
        # every strategy as its neighbour. Invertibility is the property.
        assert strategy_for(base, magic) == "statespace-surprise"
        assert magic != base

    def test_build_resolves_it_by_name(self) -> None:
        from till_infinity.trading.strategies.strategy import build

        built = build(["statespace-surprise"], Settings())
        assert [s.name for s in built] == ["statespace-surprise"]

    def test_it_is_not_in_the_default_strategy_list(self) -> None:
        """Registered and not configured: it does not trade until asked."""
        assert "statespace-surprise" not in Settings().strategies


class TestTheFeedRestriction:
    """`TRADING_SYMBOLS` is global, so the restriction has to be in the class.

    Naming the strategy in `TRADING_STRATEGIES` makes it eligible on every
    configured symbol. On a wide feed `cost_share` would refuse nearly every
    proposal anyway - `exotic-spreads-are-a-whole-bar-range` measured round
    trips of 0.40 to 0.97 bar-ranges - but an incidental refusal and a
    deliberate exclusion read the same in a tally and mean different things.
    """

    def test_it_takes_the_fx_majors(self) -> None:
        engine = _engine()
        for feed in ("eurusd", "gbpusd", "usdjpy", "usdcad", "usdchf", "audusd", "nzdusd"):
            assert engine.wants({"shape": "statespace", "feed": feed}), feed

    def test_it_takes_the_fx_crosses(self) -> None:
        engine = _engine()
        for feed in ("eurgbp", "eurjpy", "gbpjpy", "eurchf", "audjpy", "chfjpy", "euraud"):
            assert engine.wants({"shape": "statespace", "feed": feed}), feed

    def test_it_declines_everything_else_on_the_desk(self) -> None:
        """The other 18 configured symbols, including the ones it would lose on."""
        engine = _engine()
        for feed in (
            "gold",
            "silver",
            "btc",
            "eth",
            "sol",
            "spx500",
            "us100",
            "us30",
            "us2000",
            "ger40",
            "uk100",
            "fra40",
            "eu50",
            "aus200",
            "hk50",
            "wti",
            "brent",
            "usdcnh",
        ):
            assert not engine.wants({"shape": "statespace", "feed": feed}), feed

    def test_the_feed_check_is_case_insensitive(self) -> None:
        engine = _engine()
        assert engine.wants({"shape": "statespace", "feed": "EURUSD"})

    def test_an_unlisted_feed_is_not_counted_as_a_refusal(self) -> None:
        """`wants` is the pre-filter, so `seen` never moves on another feed.

        A proposal on `btcusd` was never this strategy's to decline, and
        counting it would make the cost gate's own tally unreadable - a gate
        that fires constantly is mis-set, and that only means anything if
        everything it counts was actually eligible.
        """
        engine = _engine()
        before = engine.seen
        assert not engine.wants({"shape": "statespace", "feed": "btcusd"})
        assert engine.seen == before

    def test_the_restriction_is_not_in_the_environment(self) -> None:
        """It is a measurement about spreads, not an operator preference."""
        assert isinstance(Dispersing.feeds, frozenset)
        assert len(Dispersing.feeds) == 14
