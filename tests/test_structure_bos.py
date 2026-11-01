"""`smc_bos_c_L50|M15|N20|time`, and the causality that is its whole claim.

Variant `a` of this rule read swing timestamps from a library that dates a
swing to the bar it printed on rather than to the bar that confirmed it, so a
backtest knew at 09:00 what only 21:30 could tell it. Variant `b` moved the
signal to when it was knowable and still erased the order blocks that later
failed, so the losers left the sample with hindsight. Both read far better than
the causal version and neither could be traded.

A port of `c` can reintroduce either by accident, and neither shows up as an
error - it shows up as a better number. So the first half of this file holds
`Fold` to the property that separates them:
**what the fold said at bar `n` does not change when bars after `n` arrive.**
`test_every_prefix_produces_the_events_the_full_series_produced` is that test,
and it is the one variant `a` fails.

The fold is exercised at the shipped reach of 50, because that is the number
the rule names and it costs nothing in pure Python. The engine tests use a
three-bar reach so a whole sequence - two swing highs, two swing lows, a trend
label and a break - fits in a feed a test suite can afford, and
`test_the_shipped_rule_runs_the_numbers_its_name_states` is what stops that
shrinking from hiding a changed parameter.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, OrderStatus
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.domain.models import Side
from till_infinity.strategies import leaves
from till_infinity.strategies.entries import EdgeEntry, EdgeEntryConfig
from till_infinity.strategies.exits import ManagedExit
from till_infinity.strategies.structure import (
    HOLD_MINUTES,
    REACH,
    SPREADS,
    Fold,
    Structure,
    StructureEdge,
    StructureProfile,
)

INSTRUMENT = TestInstrumentProvider.default_fx_ccy("XAU/USD")
VENUE = INSTRUMENT.id.venue
DIGITS = INSTRUMENT.price_precision
SEC = 1_000_000_000
MINUTE = 60 * SEC
#: Fifteen one-minute bars to an M15 bar.
PER_WINDOW = 15
WICK = 0.1

# ------------------------------------------------------------------- the fold


def zigzag(
    turns: int, reach: int = REACH, amp: float = 5.0, rise: float = 2.0, start: float = 100.0
) -> list[float]:
    """A rising zigzag whose turns are strict extremes of `reach` bars a side.

    Each leg is `reach + 1` strictly monotone bars, so every turn has `reach`
    bars rising into it and `reach` falling out of it - the fold's definition,
    planted rather than hoped for. `rise` lifts each successive turn, so the
    highs and the lows both climb and the label the rule derives is an uptrend.
    """
    mids = [start]
    level = start
    up = True
    for _ in range(turns):
        target = level + amp if up else level - (amp - rise)
        step = (target - level) / (reach + 1)
        mids.extend(level + step * i for i in range(1, reach + 2))
        level = target
        up = not up
    return mids


def fold_over(mids: list[float], reach: int = REACH) -> tuple[Fold, list]:
    """One bar per mid: a doji with a wick each side, so the close is the mid.

    The shape matters. With the close pinned to the mid, "an M15 candle must
    close beyond the swing" is a claim about a number this helper chose, and
    the wick is a number it chose separately - so a fold that broke on a wick
    is caught here rather than hidden by a close that moved with it.
    """
    fold = Fold(reach=reach)
    events: list = []
    for mid in mids:
        events.extend(fold.update(mid + WICK, mid - WICK, mid))
    return fold, events


def test_a_swing_is_known_fifty_bars_after_it_printed_and_not_before():
    """The `c`. A swing high is the highest of the 50 bars on each side, so the
    earliest moment it can be asserted is the close of the fiftieth bar after
    it - and a fold that nominated it any earlier would be claiming a bar that
    had not printed."""
    mids = [100.0 + i for i in range(REACH)] + [200.0] + [100.0 - i for i in range(REACH)]
    fold = Fold()
    for mid in mids[:-1]:
        fold.update(mid + WICK, mid - WICK, mid)
    assert fold.highs == 0, "the swing was confirmed before its last bar closed"
    assert len(fold.window) == 2 * REACH, "one bar short of a full window"

    fold.update(mids[-1] + WICK, mids[-1] - WICK, mids[-1])
    assert fold.highs == 1
    assert fold.high == pytest.approx(200.0 + WICK), "a swing high is the bar's high"


def test_a_wick_through_the_swing_is_not_a_break_and_a_close_is():
    """Step 3, and the cheapest way to turn this rule into a different one.

    A wick beyond a level is the most common event on a chart and the rule
    excludes it deliberately. A fold comparing highs rather than closes would
    trade several times as often, which reads as a more productive rule rather
    than as a bug.
    """
    fold, events = fold_over(zigzag(6))
    assert fold.trend == 1, f"the planted zigzag is an uptrend, not {fold.trend}"
    assert fold.high_live, "the test needs an unbroken swing to break"
    before = list(events)

    inside = fold.high - 0.01
    assert fold.update(fold.high + 5.0, inside - WICK, inside) == []
    assert fold.high_live, "the swing was spent on a wick"

    beyond = fold.high + 0.01
    broke = fold.update(beyond + WICK, beyond - WICK, beyond)
    assert [event.kind for event in broke] == ["bos"]
    assert broke[0].side is Side.BUY
    assert events == before, "an earlier event changed under a later bar"


def test_one_swing_triggers_once_however_many_closes_clear_it():
    """Each swing may only trigger once. Without the latch, a trend that keeps
    going opens a position on every bar of it - which is a different rule
    wearing this one's name and several times its trade count."""
    fold, _ = fold_over(zigzag(6))
    swing = fold.high
    first = fold.update(swing + 1.1, swing + 0.9, swing + 1.0)
    second = fold.update(swing + 2.1, swing + 1.9, swing + 2.0)
    assert [event.kind for event in first] == ["bos"]
    assert second == [], "the same swing triggered twice"


def test_the_trend_needs_both_a_higher_high_and_a_higher_low():
    """Step 2, including the half that is a non-event.

    A higher high with a *lower* low is a widening range, and the rule says so
    by keeping the previous label. A port reading the high alone would call
    every expansion an uptrend and trade its breaks as continuation.
    """
    fold = Fold(reach=2)
    # Highs of 110 then 112 and lows of 100 then 98: a higher high and a lower
    # low, which is neither of the two patterns that set a label.
    for mid in (105, 106, 110, 106, 105, 101, 100, 101, 105, 108, 112, 108, 104, 99, 98, 99, 103):
        fold.update(mid + WICK, mid - WICK, float(mid))
    assert (fold.highs, fold.lows) == (2, 2)
    assert (fold.high_step, fold.low_step) == (1, -1)
    assert fold.trend == 0, "a higher high with a lower low is not a trend"


def test_a_break_against_the_trend_is_a_choch_that_is_not_traded():
    """Step 4. The flip happens whether or not anything acts on the event, or
    the next break is judged against a label the market has already left."""
    fold, _ = fold_over(zigzag(6))
    assert fold.trend == 1
    low = fold.low
    broke = fold.update(low - 0.9, low - 1.1, low - 1.0)
    assert [event.kind for event in broke] == ["choch"]
    assert broke[0].side is Side.SELL
    assert fold.trend == -1, "a change of character did not change the label"


def test_a_break_before_any_trend_is_neither_a_bos_nor_a_choch():
    """The first swings arrive before any label can exist, and a break then is
    not a continuation of anything. Counted under its own name rather than
    folded into either, because a port that guessed would guess in the
    direction of more trades."""
    fold = Fold(reach=2)
    for mid in (100, 101, 105, 101, 100, 102):
        fold.update(mid + WICK, mid - WICK, float(mid))
    assert (fold.highs, fold.trend) == (1, 0)
    assert [event.kind for event in fold.update(106.1, 105.9, 106.0)] == ["unlabelled"]


def test_a_monotone_ramp_confirms_no_swings_at_all():
    """The control for every test above. A series with no interior extreme has
    no swings, so a fold reporting one would be reporting its own window
    boundary - which is what a detector reading the first or last bar of its
    buffer does."""
    fold, events = fold_over([100.0 + i for i in range(400)])
    assert (fold.highs, fold.lows, events) == (0, 0, [])


def test_every_prefix_produces_the_events_the_full_series_produced():
    """**The test variant `a` fails.**

    Fold over the first `n` bars and over all of them, and the events inside
    the first `n` must be identical. A fold that dated a swing to the bar it
    printed on rather than to the bar that confirmed it would emit the same
    events at different bars in the two runs - and nothing else here would
    notice, because the counts would agree and the money would be better.
    """
    mids = zigzag(10, rise=2.0)
    _, whole = fold_over(mids)
    assert whole, "a series with no events cannot test causality"
    for cut in (len(mids) // 3, len(mids) // 2, len(mids) - 1):
        _, prefix = fold_over(mids[:cut])
        assert prefix == [event for event in whole if event.at <= cut], f"prefix {cut} disagrees"


def test_a_fold_with_no_reach_is_refused_rather_than_degenerate():
    """A reach of zero makes every bar its own swing, which is a detector that
    fires on everything and looks like a very productive rule."""
    with pytest.raises(ValueError, match="at least one bar"):
        Fold(reach=0)


# ---------------------------------------------------------------- the numbers


def test_the_shipped_rule_runs_the_numbers_its_name_states():
    """`L50|M15|N20|time`, read off the profile a deploy would build.

    The engine tests below shrink the reach to keep a feed affordable, so this
    is the assertion that the shipped rule is still the one the name describes:
    a port measured at a reach of three and deployed at a reach of five is two
    rules with one set of results.
    """
    assert (StructureProfile.reach, StructureProfile.spreads) == (50, 20.0)
    assert (REACH, SPREADS, HOLD_MINUTES) == (50, 20.0, 1_440)
    assert StructureProfile.interval == "15m"
    assert StructureProfile.hold_seconds == 1_440 * 60.0
    assert StructureProfile.description == "smc_bos_c_L50|M15|N20|time"
    assert leaves.LEAVES[("smc-bos-causal", "edge")] is StructureEdge
    assert "smc-bos-causal" in leaves.RULES
    # One entry mechanism, because the rule says "at market": a rest at a named
    # price and a wait for an arrival are different rules rather than
    # configurations of this one, and `leaf` refuses them by name.
    for entry in ("resting", "arrival"):
        with pytest.raises(ValueError, match="smc-bos-causal"):
            leaves.leaf("smc-bos-causal", entry)


def test_the_rule_declines_a_reading_that_is_not_its_own():
    """Every desk subscribes to one proposals topic, so a statespace reading
    reaches this rule too. It is not this rule's to judge - `wants` is checked
    before `decide` so an unlisted shape costs nothing and is not counted as a
    refusal."""
    strategy = StructureEdge.__new__(StructureEdge)
    assert strategy.wants({"shape": "structure"})
    assert not strategy.wants({"shape": "statespace"})
    assert not strategy.wants({})


# ----------------------------------------------------------------- the engine


class TinyProfile(StructureProfile):
    """The shipped rule at a reach of three, so a sequence fits in a test."""

    reach: ClassVar[int] = 3


class Tiny(Structure):
    profile: ClassVar[TinyProfile] = TinyProfile.__new__(TinyProfile)


class TinyEdge(Tiny, ManagedExit, EdgeEntry):
    """`StructureEdge` with a three-bar reach. Everything else is the rule."""


def planted(*, after: list[float] | None = None) -> list[float]:
    """The M15 mids: a rising zigzag that breaks, then whatever follows it.

    Truncated at the bar whose close breaks the live swing high - which the
    prefix test above is what licenses - plus one more window, so the price
    the entry fills at is a *different number* from the signal bar's close.
    That is what gives the fill-price test its teeth.

    `after` defaults to enough flat windows to outlast the clock, so nothing
    resolves the trade but the clock itself.
    """
    mids = zigzag(5, reach=TinyProfile.reach)
    tail = after if after is not None else [mids[-1]] * (HOLD_MINUTES // PER_WINDOW + 4)
    return mids + tail


def feed(mids: list[float], spread: float) -> list[object]:
    """The M1 bars and quotes that aggregate to `mids` on the M15 clock.

    **The quote for a minute is stamped at its open and the bar at its close.**
    That ordering is step 5: the M15 bar closes, the rule decides, and the next
    thing the venue sees is the quote opening the following minute - so a
    market order fills there, at a price that did not exist when the decision
    was made.
    """
    bar_type = BarType.from_str(f"{INSTRUMENT.id}-1-MINUTE-LAST-EXTERNAL")
    half = spread / 2.0
    size = Quantity(1_000_000, 0)
    volume = Quantity(1, 0)
    data: list[object] = []
    for index, mid in enumerate(mids):
        for minute in range(PER_WINDOW):
            ts = (index * PER_WINDOW + minute) * MINUTE
            data.append(
                QuoteTick(
                    instrument_id=INSTRUMENT.id,
                    bid_price=Price(mid - half, DIGITS),
                    ask_price=Price(mid + half, DIGITS),
                    bid_size=size,
                    ask_size=size,
                    ts_event=ts,
                    ts_init=ts,
                )
            )
            # The wick is on the window's first minute only, so the M15 high
            # and low are the planted numbers and every other bar is flat.
            reach = WICK if minute == 0 else 0.0
            data.append(
                Bar(
                    bar_type=bar_type,
                    open=Price(mid, DIGITS),
                    high=Price(mid + reach, DIGITS),
                    low=Price(mid - reach, DIGITS),
                    close=Price(mid, DIGITS),
                    volume=volume,
                    ts_event=ts + MINUTE - 1,
                    ts_init=ts + MINUTE - 1,
                )
            )
    return data


def composite() -> BarType:
    """M15 aggregated from the M1 bars inside the engine.

    The rule has two clocks - M15 for the signal, M1 for the entry and the
    exit - and a composite bar type is how one data stream serves both. A desk
    fed M15 bars alone would be the same rule on half the information.
    """
    return BarType.from_str(f"{INSTRUMENT.id}-15-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL")


def run(mids: list[float] | None = None, spread: float = 0.10) -> TinyEdge:
    """One engine, one desk, the planted feed. Nothing is driven by hand."""
    mids = planted() if mids is None else mids
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        # **Quotes alone fill.** With bar execution on, the engine would also
        # match against the bar it has just processed - the bar the signal was
        # read from, at no spread at all. That is a fill nobody could get, and
        # it is the generosity `node/backtest.venue` refuses to tune for.
        bar_execution=False,
    )
    engine.add_instrument(INSTRUMENT)
    engine.add_data(feed(mids, spread))
    strategy = TinyEdge(EdgeEntryConfig(instrument_id=INSTRUMENT.id, bar_type=composite()))
    engine.add_strategy(strategy)
    engine.run()
    return strategy


#: M15 bars that have closed when the planted BOS is decided. The signal is
#: the twentieth bar's close, so the ATR the rule reads is the one over those
#: twenty and not over twenty-one.
SIGNAL_BARS = 20


def atr_at(mids: list[float], bars: int) -> float:
    """One M15 ATR after `bars` of the planted series, independently folded.

    The expectation for the stop's ATR branch. Built here from the bars the
    feed is constructed to produce, so what the test checks is this port's
    arithmetic around the ATR - the side, the multiple and the `max` - rather
    than Nautilus's ATR against itself.
    """
    atr = AverageTrueRange(TinyProfile.atr_period)
    standard = composite().standard()
    for index, mid in enumerate(mids[:bars]):
        atr.handle_bar(
            Bar(
                bar_type=standard,
                open=Price(mid, DIGITS),
                high=Price(mid + WICK, DIGITS),
                low=Price(mid - WICK, DIGITS),
                close=Price(mid, DIGITS),
                volume=Quantity(PER_WINDOW, 0),
                ts_event=index * PER_WINDOW * MINUTE,
                ts_init=index * PER_WINDOW * MINUTE,
            )
        )
    return float(atr.value)


def orders_of(strategy: TinyEdge):
    """The entry and the stop the venue is holding."""
    orders = strategy.cache.orders(strategy_id=strategy.id)
    entry = next(o for o in orders if o.side is OrderSide.BUY)
    stop = next(o for o in orders if getattr(o, "trigger_price", None) is not None)
    return orders, entry, stop


def test_the_engine_aggregates_the_m15_signal_from_the_m1_feed():
    """The composite, asserted on the thing that depends on it.

    `test_internal_bars.py` records the silent half: an internally aggregated
    bar type priced `LAST` subscribes to trade ticks, and a feed of quotes
    produces no bars, no error and no log line. This feed is M1 **bars** and
    the aggregation is bar to bar, so a count of zero here would say the
    composite never subscribed - and the desk would report a result computed
    from no trades.
    """
    mids = planted()
    strategy = run(mids)
    counted = strategy.structure
    # One short of the planted windows: the final M15 bar is still open when
    # the feed ends, and an aggregator that emitted it would be emitting a
    # partial bar - which is the whole failure this rule's `c` is named for.
    assert counted["bars"] == len(mids) - 1, "the M15 clock did not run"
    assert (counted["swing_highs"], counted["swing_lows"]) == (2, 2), counted
    assert (counted["bos"], counted["choch"], counted["unlabelled"]) == (1, 0, 1), counted
    assert strategy.taken == 1
    assert strategy.refused == 0, strategy.passed_over


def test_a_bos_reaches_the_venue_as_an_entry_and_a_stop_and_no_target():
    """Steps 5 and 6 at the venue, and the absence in step 7.

    **No target is the rule**, so `EdgeEntry` takes its unbracketed path: the
    entry alone, and the stop attached from the fill. A port that invented a
    target to get a bracket would be a rule with a reward-to-risk nobody
    measured - and the bracket is the easier code path, which is why this is
    asserted rather than assumed.
    """
    strategy = run()
    orders, entry, stop = orders_of(strategy)
    assert len([o for o in orders if o.side is OrderSide.BUY]) == 1, [str(o) for o in orders]
    assert entry.status == OrderStatus.FILLED
    assert stop.is_reduce_only
    assert stop.side is OrderSide.SELL, "the stop closes, so it is the other side"
    assert not [o for o in orders if getattr(o, "price", None) is not None], (
        "a limit order at the venue means something placed a target"
    )


def test_the_entry_fills_at_the_quote_after_the_m15_close_and_not_at_it():
    """**The look-ahead assertion at the execution end.**

    The planted feed steps a whole quarter-point between M15 windows, so the
    signal bar's close and the price one minute later are different numbers.
    The fill has to be the later one: an entry filled at the close of the bar
    that produced the signal is a fill at a price that existed before the
    decision, which is variant `a` arriving through the venue rather than
    through the detector.
    """
    mids = planted()
    strategy = run(mids)
    _, entry, _ = orders_of(strategy)
    #: The window whose close breaks the swing, and the one the fill lands in.
    signal, filled = 19, 20
    assert mids[filled] > mids[signal], "the feed does not step between the two"
    assert float(entry.avg_px) == pytest.approx(mids[filled] + 0.05, abs=1e-6), (
        "the fill is not the ask of the first minute after the signal bar"
    )
    assert float(entry.avg_px) != pytest.approx(mids[signal] + 0.05), (
        "the fill is the signal bar's own ask - the venue filled in the past"
    )
    assert entry.ts_last >= filled * PER_WINDOW * MINUTE


def test_the_stop_takes_the_twenty_spread_floor_when_it_is_the_wider():
    """The `N20`. One ATR can be tighter than the round trip on a quiet
    instrument, and a stop inside its own cost is a trade that cannot pay for
    itself - so the rule floors it at twenty spreads. This feed is built so the
    floor wins: a 0.10 spread floors the stop at 2.00 against an ATR of about
    1.2."""
    mids = planted()
    strategy = run(mids, spread=0.10)
    _, entry, stop = orders_of(strategy)
    assert atr_at(mids, SIGNAL_BARS) < SPREADS * 0.10, "this feed does not exercise the floor"
    distance = abs(float(entry.avg_px) - float(stop.trigger_price))
    assert distance == pytest.approx(SPREADS * 0.10, abs=2e-5)


def test_the_stop_takes_one_atr_when_that_is_the_wider():
    """The other branch of the same `max`, and the one a port is likelier to
    drop: with a tight spread the ATR binds, and a rule that only ever read the
    floor would be `N20` with an ATR in its name."""
    mids = planted()
    strategy = run(mids, spread=0.002)
    expected = atr_at(mids, SIGNAL_BARS)
    assert expected > SPREADS * 0.002, "this feed does not exercise the ATR branch"
    _, entry, stop = orders_of(strategy)
    distance = abs(float(entry.avg_px) - float(stop.trigger_price))
    assert distance == pytest.approx(expected, abs=2e-5)
    # **And it is the ATR of the bars that had closed.** One bar more is a
    # different number here, so this pins the causal count rather than the
    # arithmetic alone: an ATR folded one bar late is the same look-ahead the
    # swing confirmation is careful about, arriving through the stop distance.
    assert distance != pytest.approx(atr_at(mids, SIGNAL_BARS + 1), abs=2e-5)


def test_a_change_of_character_places_nothing_and_still_flips_the_label():
    """Step 4 at the venue, which is where it costs money to get wrong.

    A CHoCH is the *other* half of the break the rule already trades, so a
    port that traded it would roughly double the trade count and look like a
    more complete implementation. The feed takes the trend up, breaks the
    swing high once - the one order this run is allowed - and then closes
    below the live swing low, which is a change of character and is not a
    trade.
    """
    mids = planted(after=[zigzag(5, reach=TinyProfile.reach)[-1] - 20.0] * 3)
    strategy = run(mids, spread=0.10)
    counted = strategy.structure
    assert counted["choch"] == 1, counted
    assert counted["bos"] == 1, counted
    assert strategy.taken == 1, "the change of character was traded"
    entries = [
        order
        for order in strategy.cache.orders(strategy_id=strategy.id)
        if getattr(order, "trigger_price", None) is None
    ]
    assert len(entries) == 1, [str(order) for order in entries]
    assert entries[0].side is OrderSide.BUY, "a sell means the CHoCH reached the venue"
    assert strategy.fold.trend == -1, "the label did not flip"


def test_the_trade_comes_off_on_the_clock_when_the_stop_is_never_hit():
    """Step 7, with its own number. The feed goes flat after the entry, so
    nothing resolves the trade but the clock - and 1,440 one-minute bars is
    where it has to come off.

    The hold is carried on the `Intent` for the reason that field states: by
    the time a position is being timed out, the strategy that opened it is a
    name in a log line. `Settings.max_hold` is 1,800s and deliberately *not*
    folded in, so a rule that set no hold would be held for ever and a rule
    that sets one is the only thing the clock can read.
    """
    strategy = run()
    assert len(strategy.closed) == 1, strategy.closed
    trade = strategy.closed[0]
    assert trade.how == "clock", "the trade did not come off on its own clock"
    assert trade.closed - trade.opened == pytest.approx(HOLD_MINUTES * 60.0, abs=120.0)
    assert strategy.passed_over.get("(exit):closed") == 1
    assert not strategy.cache.positions_open(strategy_id=strategy.id)


def test_a_stop_out_is_recorded_as_one_and_costs_about_a_whole_r():
    """The other exit, and the classification that tells them apart.

    `how` reads the closing latch, which only a rule-driven close writes - so a
    stop-out is the *absence* of a reason rather than a reason of its own.
    Getting that backwards would label every stop-out a timeout, and the mix of
    the two is what says whether the clock is doing anything at all.
    """
    mids = planted()
    falling = [mids[-1] - 1.0 * (step + 1) for step in range(8)]
    strategy = run(planted(after=falling), spread=0.10)
    assert strategy.structure["bos"] == 1, strategy.structure
    assert len(strategy.closed) == 1
    trade = strategy.closed[0]
    assert trade.how == "stop"
    assert trade.reward < -0.5, f"a stop-out that cost {trade.reward:+.2f}R"
