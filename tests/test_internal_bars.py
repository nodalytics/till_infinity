"""Bars Nautilus builds from the tick stream, rather than bars the venue sends.

`node/desks.bar_type` pinned `LAST-EXTERNAL` for every desk, and its reason was
that MT5's tick stream is sampled - a 0.25s poll, from which internally
aggregated bars would be built out of a sample and would not match the venue's
own. The EA made that half false. `MT5/ea/TillTickFeed.mq5` pushes from
`OnTick`, which fires for every tick the terminal sees, so the stream is
complete for a symbol with a chart and an EA on it and still a poll for every
other. That is a per-feed property, which is why this is a switch
(`TRADING_BAR_SOURCE`) and not a new default.

**The thing being guarded here is one line in Nautilus.**
`data/engine.pyx:_subscribe_bar_aggregator` subscribes to **trade ticks** when
an internally aggregated bar type's price type is `LAST`, and to quote ticks
for anything else. The MT5 adapter publishes `QuoteTick` and never a
`TradeTick`, so `LAST-INTERNAL` subscribes to a stream nothing produces: no
bars, no error, no log line - a desk that is subscribed and inert, which is
indistinguishable from a market that is quiet.

So there is a test for the thing working and a test for the thing failing, and
the second is the one that gives the first its meaning. A suite that only
asserts bars arrive would pass on a bar type that cannot work, as long as
somebody had already chosen the right one.
"""

from __future__ import annotations

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig, BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.node import desks

VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
SECOND = 1_000_000_000


class CountConfig(ActorConfig, frozen=True):
    bar_type: BarType


class Counter(Actor):
    """Subscribes and counts. Nothing else, so a zero means the subscription."""

    def __init__(self, config: CountConfig) -> None:
        super().__init__(config)
        self.bars: list[Bar] = []

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        self.bars.append(bar)


def quotes(count: int) -> list[QuoteTick]:
    """One quote a second, drifting up by a point each time."""
    return [
        QuoteTick(
            instrument_id=EURUSD.id,
            bid_price=Price(1.09995 + i * 1e-05, 5),
            ask_price=Price(1.10000 + i * 1e-05, 5),
            bid_size=Quantity(1_000_000, 0),
            ask_size=Quantity(1_000_000, 0),
            ts_event=i * SECOND,
            ts_init=i * SECOND,
        )
        for i in range(count)
    ]


def count(spec: str, ticks: int = 120) -> list[Bar]:
    """Run `ticks` quotes past an actor subscribed to `spec`, return its bars."""
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(100_000, USD)],
    )
    engine.add_instrument(EURUSD)
    engine.add_data(quotes(ticks))
    counter = Counter(CountConfig(bar_type=BarType.from_str(f"{EURUSD.id}-{spec}")))
    engine.add_actor(counter)
    engine.run()
    return counter.bars


# -------------------------------------------------------------- the mechanism


def test_a_minute_bar_is_built_from_the_quotes():
    """The last bar's close is the mid of the last quote, which is the
    assertion that these were built from the ticks rather than arriving from
    somewhere else.

    **Three bars from two minutes of quotes, and the first is a stub.** A time
    aggregator emits on wall-clock boundaries, and this feed opens exactly on
    one - so the first bar holds the single tick at `t=0` and closes
    immediately. That is correct behaviour and it is a bias worth naming: the
    first bar of every internally aggregated run is partial, so a fold that
    takes it is folding one tick as though it were a minute. Discovery has to
    drop it, and `reproduce-the-baseline-before-an-increment` is what finding
    that out late costs.
    """
    bars = count("1-MINUTE-MID-INTERNAL", ticks=121)
    assert len(bars) == 3
    assert float(bars[0].open) == float(bars[0].close), "the first bar is one tick"
    assert float(bars[-1].close) == pytest.approx((1.09995 + 1.10000 + 2 * 120e-05) / 2, abs=1e-06)


def test_a_last_priced_internal_bar_never_arrives():
    """**The silent failure, asserted.** Same quotes, same clock, one word
    different - and Nautilus subscribes to trade ticks instead, of which this
    feed has none. Nothing raises and nothing logs: the actor is subscribed and
    the handler is never called.

    This is why `bar_type` chooses the price type rather than accepting one."""
    assert count("1-MINUTE-LAST-INTERNAL", ticks=121) == []


def test_a_tick_clock_closes_on_the_count_and_not_the_clock():
    """An activity clock is the point of internal aggregation: it is the one
    thing the venue cannot send, and the desk has measured that a clock driven
    by activity absorbs most of what its volatility clock does and still pays
    on top. Twenty quotes on a five-tick clock is four bars, whatever the
    wall clock did."""
    bars = count("5-TICK-MID-INTERNAL", ticks=20)
    assert len(bars) == 4


def test_the_venues_own_bars_are_not_built_from_ticks():
    """The control for the first test. An `EXTERNAL` bar type waits for the
    venue to publish bars, and this run publishes none - so a passing
    `INTERNAL` test is not just the engine handing back whatever it was fed."""
    assert count("1-MINUTE-LAST-EXTERNAL", ticks=121) == []


# ------------------------------------------------------------- what it is named


def test_the_default_is_still_the_venues_own_bars(monkeypatch):
    """Unchanged, deliberately. `OnTick` fires only for the symbol its chart is
    on, so the pushed stream covers part of the book and the poll covers the
    rest - and bars built from a 0.25s sample would not match the venue's own
    on the feeds where the EA is not attached."""
    monkeypatch.delenv("TRADING_BAR_SOURCE", raising=False)
    assert str(desks.bar_type("EURUSD", "MT5", "15m")) == "EURUSD.MT5-15-MINUTE-LAST-EXTERNAL"


def test_the_switch_changes_the_source_and_the_price_type_together(monkeypatch):
    """They cannot be set independently, which is the whole lesson of
    `test_a_last_priced_internal_bar_never_arrives`: a deploy that could ask
    for `INTERNAL` and keep `LAST` would get a desk that subscribes to nothing
    on this venue."""
    monkeypatch.setenv("TRADING_BAR_SOURCE", "internal")
    assert str(desks.bar_type("EURUSD", "MT5", "15m")) == "EURUSD.MT5-15-MINUTE-MID-INTERNAL"


def test_an_activity_clock_is_internal_whatever_the_setting_says(monkeypatch):
    """No venue publishes a tick bar, so `external` is not a choice that exists
    for one. Overriding it silently is right here and would not be for a time
    clock: nothing but `spec_for` can produce an activity clock, so a deploy
    that named one has already asked for Nautilus to build it."""
    monkeypatch.setenv("TRADING_BAR_SOURCE", "external")
    assert str(desks.bar_type("EURUSD", "MT5", "500tick")) == "EURUSD.MT5-500-TICK-MID-INTERNAL"


def test_a_volume_clock_is_refused_with_the_measurement_that_refuses_it():
    """Nautilus will build `VOLUME` and `VALUE` bars and this venue cannot feed
    them. `adapters/mt5/data.py` records why: an MT5 tick's trade fields read 0
    or a constant 5000, so the adapter publishes a placeholder size and never a
    trade tick.

    **The refusal matters more than it looks.** The bars would arrive - a
    500-volume bar on constant sizes is a 500-tick bar with a scale factor -
    and the fold would run, and the result would be read as the volume clock
    the desk measured on the lab's cached data. A clock that is quietly a
    different clock is worse than a missing one."""
    with pytest.raises(ValueError, match="constant 5000"):
        desks.bar_type("EURUSD", "MT5", "500vol")
    with pytest.raises(ValueError, match="VALUE"):
        desks.bar_type("EURUSD", "MT5", "250value")


def test_an_unknown_clock_names_both_forms_it_could_have_taken():
    """A deploy that names an interval this node cannot subscribe to runs
    nothing, and three deploys on record came up, tagged themselves, passed a
    health check and ran none of the code they claimed."""
    with pytest.raises(ValueError, match="500tick"):
        desks.bar_type("EURUSD", "MT5", "7m")


def test_a_bad_source_is_refused_rather_than_defaulted(monkeypatch):
    """`TRADING_BAR_SOURCE=internl` defaulting to external would be a deploy
    measuring one thing and believing it measured another."""
    monkeypatch.setenv("TRADING_BAR_SOURCE", "internl")
    with pytest.raises(ValueError, match="not a bar source"):
        desks.bar_type("EURUSD", "MT5", "15m")


# ------------------------------------------------------------- and the backtest


def test_an_internal_run_is_fed_quotes_rather_than_bars():
    """The half of this that only shows up in a backtest. A data config loading
    `Bar` for an internally aggregated run would hand the aggregator the output
    it exists to produce: no bars, no trades, and a result computed from
    nothing that still prints."""
    from till_infinity.node import backtest

    internal = backtest.data("EURUSD.SIM", "15-MINUTE-MID-INTERNAL")
    assert [config.data_cls for config in internal] == [QuoteTick]
    assert internal[0].bar_spec is None


def test_an_external_run_is_fed_the_quotes_as_well_as_the_bars():
    """**And every desk refused every proposal until it was.**

    `Desk._undealable` refuses on a missing quote and `Surprise.decide`
    refuses earlier still on its own, so a run fed bars alone has
    `cache.quote_tick()` returning `None` throughout - measured on a ten-bar
    probe: ten bars delivered, zero with a cached quote. `desk_config()` at its
    default spec therefore built the production desks over a stream they could
    not trade and printed a result computed from no trades.

    A catalogue with no quotes in it still produces no trades. The difference
    is that the config asked for them, so their absence is visible rather than
    nobody having asked.
    """
    from till_infinity.node import backtest

    external = backtest.data("EURUSD.SIM", "15-MINUTE-LAST-EXTERNAL")
    assert [config.data_cls for config in external] == [Bar, QuoteTick]
    assert external[0].bar_spec == "15-MINUTE-LAST-EXTERNAL"
    assert external[1].bar_spec is None
