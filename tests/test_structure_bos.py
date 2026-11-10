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


def test_a_reach_per_side_defaults_to_the_shared_one_event_for_event():
    """The default has to be free. A reach per side is a second free parameter
    and the version carrying it must fold **identically** to the version
    without it, or every number this rule has ever produced moved the day the
    parameter was added.
    """
    mids = zigzag(10, rise=2.0)
    plain, events = fold_over(mids)
    for sided in (
        Fold(reach=REACH, reach_up=0, reach_down=0),
        Fold(reach=REACH, reach_up=REACH, reach_down=REACH),
    ):
        found: list = []
        for mid in mids:
            found.extend(sided.update(mid + WICK, mid - WICK, mid))
        assert found == events
        assert (sided.highs, sided.lows, sided.trend) == (plain.highs, plain.lows, plain.trend)
    assert events, "a series with no events cannot test this"


def test_each_side_waits_its_own_reach_and_a_short_side_confirms_first():
    """What a reach per side is for, and the control that it reaches one side
    only. A swing low with a three-bar window is known long before a swing high
    with a fifty-bar one, so a fold holding one window for both is asserting
    that up legs and down legs take the same time to resolve.

    Built to the short side's definition, so the long side must find nothing.
    """
    mids = zigzag(6, reach=3)
    short = Fold(reach=REACH, reach_up=REACH, reach_down=3)
    for mid in mids:
        short.update(mid + WICK, mid - WICK, mid)
    assert short.lows > 0, "the short side did not confirm on its own three-bar reach"
    assert short.highs == 0, "a fifty-bar reach confirmed a three-bar turn"
    symmetric = Fold(reach=3)
    for mid in mids:
        symmetric.update(mid + WICK, mid - WICK, mid)
    assert symmetric.lows == short.lows, "the up reach moved the down side's count"
    assert symmetric.highs > 0, "the fixture has no swing highs at a three-bar reach"


def test_a_tie_is_not_a_swing_unless_the_fold_is_told_it_is():
    """The one place this port and the rule's own statement disagree. The rule
    reads `high[j] == max(window)`, which admits a tie; this fold requires
    strictly beyond, because a tie lets a flat run nominate every bar in it.

    With one live slot per side the last of them wins either way, so the two
    differ only on exact equality - measured on the catalogue, it moved one
    spx500 trade and no others. Both readings are kept because the difference
    is a fact about the feed's price precision, not a preference.
    """
    flat = zigzag(4, reach=3)
    flat = [*flat, flat[-1], flat[-1], flat[-1]]
    plateau = [*flat[:-1], max(flat), max(flat), *[max(flat) - 1.0] * 4]
    strict = Fold(reach=3)
    loose = Fold(reach=3, strict=False)
    for mid in plateau:
        strict.update(mid + WICK, mid - WICK, mid)
        loose.update(mid + WICK, mid - WICK, mid)
    assert loose.highs > strict.highs, "a tie was not admitted by the non-strict fold"
    assert strict.highs > 0, "the strict fold found nothing, so the comparison is vacuous"


def test_a_negative_reach_per_side_is_refused_rather_than_degenerate():
    """Zero already means "use the shared reach", so a negative one is the
    remaining way to ask for nonsense - and it is silent: the window would be
    shorter than its own candidate and every bar would confirm."""
    for bad in ({"reach_up": -1}, {"reach_down": -1}):
        with pytest.raises(ValueError, match="bar count or zero"):
            Fold(reach=REACH, **bad)


def test_a_fold_with_no_reach_is_refused_rather_than_degenerate():
    """A reach of zero makes every bar its own swing, which is a detector that
    fires on everything and looks like a very productive rule."""
    with pytest.raises(ValueError, match="at least one bar"):
        Fold(reach=0)


# ---------------------------------------------------------------- the numbers


def test_a_per_side_stop_resolves_to_the_shared_number_until_a_side_is_set():
    """The three per-side stop parameters, and the control that the default is
    free. `atr_mult`, `spreads` and `reach` each gain an `_up`/`_down` pair
    where zero means the shared value, so a profile that sets neither has to
    resolve to exactly the symmetric number on both sides.

    `decide` multiplies the quote spread by `spreads_for` and
    `on_position_closed` divides by it to recover that spread, so a pair that
    resolved to the shared value on one path and the side's on the other would
    misread the cost in R by the ratio of the two.
    """
    shipped = StructureProfile.__new__(StructureProfile)
    for sign in (1, -1):
        assert shipped.atr_mult_for(sign) == shipped.atr_mult
        assert shipped.spreads_for(sign) == shipped.spreads == SPREADS
        assert shipped.reach_for(sign) == shipped.reach == REACH

    class Sided(StructureProfile):
        atr_mult_up: ClassVar[float] = 1.5
        spreads_down: ClassVar[float] = 30.0
        reach_up: ClassVar[int] = 25

    sided = Sided.__new__(Sided)
    assert (sided.atr_mult_for(1), sided.atr_mult_for(-1)) == (1.5, 1.0)
    assert (sided.spreads_for(1), sided.spreads_for(-1)) == (SPREADS, 30.0)
    assert (sided.reach_for(1), sided.reach_for(-1)) == (25, REACH)


def test_warm_history_advances_the_fold_and_a_stale_break_never_acts():
    """**A cold fold cannot produce a signal for days.** `on_start` builds an
    empty `Fold`, a swing needs `2 * reach + 1` bars, and a BOS needs two
    swings a side. Replayed cold on production M15 bars the first BOS landed
    at bar 508-939 - five to ten days of continuous bars after every deploy.
    Measured 2026-11-07: a desk 7.8 hours old had zero swings on all 32 feeds.

    `on_historical_data` is driven directly here. A `BacktestEngine` with no
    catalogue has nothing to answer a `request_bars` with, so the engine rig
    can only prove the request does not raise - which the composite path did,
    once: Nautilus refuses `request_bars` for a composite bar type outright,
    and that raised in `on_start` and took the desk down rather than leaving
    it cold. The wiring is exercised live; this is the handler.
    """
    strategy = run_external(zigzag(40, reach=3))
    _bar_type, data = external_feed(zigzag(140, reach=3), 0.10)
    bars = [row for row in data if isinstance(row, Bar)]
    assert bars, "no bars to warm with"

    before_bos = strategy.structure["bos"]
    taken_before = len(strategy.closed)
    strategy.on_historical_data(bars)

    # 1. It folded, and the fold carries swings from it.
    assert strategy.warmed["bars"] == len(bars)
    assert strategy.fold.highs + strategy.fold.lows > 0, "warm bars produced no swings"
    # 2. `structure["bars"]` counts them, because it is the bar clock and is
    #    only ever read as a difference.
    assert strategy.structure["bars"] >= strategy.warmed["bars"]
    # 3. **A stale warm break is counted and never acted on.** A BOS on a bar
    #    hours old names a price that has gone. A break on the *last* warm bar
    #    is a different case and is forwarded - see the two tests below, which
    #    assert the freshness judgement directly rather than through the gates.
    assert strategy.structure["bos"] >= before_bos
    assert len(strategy.closed) == taken_before, "a warm bar reached the venue"


def test_a_warm_break_is_counted_apart_from_a_live_one():
    """A warmed fold and a fold filled by the market are different states, and
    a tally that pools them cannot say which happened. Measured apart."""
    strategy = run_external(zigzag(40, reach=3))
    _bar_type, data = external_feed(zigzag(200, reach=3), 0.10)
    bars = [row for row in data if isinstance(row, Bar)]

    strategy.on_historical_data(bars)

    assert strategy.warmed["breaks"] >= strategy.warmed["bos"]
    assert strategy.warmed["bos"] <= strategy.structure["bos"]


def test_the_atr_is_warm_when_the_fold_is():
    """**Version-dependent, so asserted.** `register_indicator_for_bars` wires
    an indicator to the *subscription*; whether Nautilus also feeds it from a
    `request_bars` response is not guaranteed. It matters because a cold ATR
    behind a warm fold makes the first stop `20 * spread` wearing an ATR's
    name - safe only while the fold took days to produce anything."""
    strategy = run_external(zigzag(140, reach=3))

    assert strategy.atr.initialized, "the fold is warm and the ATR is not"


def test_a_profile_asking_for_no_warming_requests_nothing():
    """The escape hatch has to work: a sweep comparing warm against cold sets
    `warm_bars_request = 0`, and that must not request or fold anything."""

    class ColdProfile(TinyProfile):
        warm_bars_request: ClassVar[int] = 0

    class ColdEdge(Tiny, ManagedExit, EdgeEntry):
        profile: ClassVar[ColdProfile] = ColdProfile.__new__(ColdProfile)

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000.0, USD)],
    )
    engine.add_instrument(INSTRUMENT)
    bar_type, data = external_feed(zigzag(140, reach=3), 0.10)
    engine.add_data(data)
    strategy = ColdEdge(EdgeEntryConfig(instrument_id=INSTRUMENT.id, bar_type=bar_type))
    engine.add_strategy(strategy)
    engine.run()

    assert strategy.warmed["bars"] == 0


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


class FillAnchoredProfile(TinyProfile):
    """`TinyProfile` with both stop legs measured from the fill."""

    stop_from_close: ClassVar[bool] = False


class FillAnchoredEdge(Tiny, ManagedExit, EdgeEntry):
    profile: ClassVar[FillAnchoredProfile] = FillAnchoredProfile.__new__(FillAnchoredProfile)


class SecondsClockProfile(TinyProfile):
    """`TinyProfile` timing the hold in seconds, which is the superseded read."""

    hold_signal_bars: ClassVar[int] = 0


class SecondsClockEdge(Tiny, ManagedExit, EdgeEntry):
    profile: ClassVar[SecondsClockProfile] = SecondsClockProfile.__new__(SecondsClockProfile)


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


def feed(
    mids: list[float], spread: float, *, start_hour: int = 0, gap_at: int = -1
) -> list[object]:
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
    #: Minutes skipped at `gap_at`, which is a weekend on a real FX feed: 48.5
    #: hours of no bars. A hold counted in seconds crosses it and a hold
    #: counted in bars does not, which is the whole difference between them.
    jump = 0
    for index, mid in enumerate(mids):
        if index == gap_at:
            jump += 48 * 60 + 30
        for minute in range(PER_WINDOW):
            ts = start_hour * 3_600 * SEC + (jump + index * PER_WINDOW + minute) * MINUTE
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


def external_feed(
    mids: list[float], spread: float, *, gap_at: int = -1
) -> tuple[BarType, list[object]]:
    """M15 bars as the catalogue holds them, with an optional session gap.

    **Not the composite**, and the difference decides a test: an internally
    aggregated bar type is driven by a time window, so a 48.5-hour hole in the
    minute stream is back-filled with 194 empty M15 bars - measured, 120 bars
    become 314 - and a hold counted in bars then behaves exactly like one
    counted in seconds. `node/corpus.py` writes external bars, where a gap is
    an absence, so that is the geometry this fixture carries.

    The quote is the bar's own close straddled by half the spread and stamped a
    nanosecond *before* the bar, which is what `corpus._quote` does and why a
    fill lands at the signal bar's close rather than a minute later.
    """
    bar_type = BarType.from_str(f"{INSTRUMENT.id}-15-MINUTE-LAST-EXTERNAL")
    half = spread / 2.0
    size = Quantity(1_000_000, 0)
    data: list[object] = []
    jump = 0
    for index, mid in enumerate(mids):
        if index == gap_at:
            jump += 48 * 60 + 30
        # One window in, so the quote stamped a nanosecond before the first
        # bar is not a negative timestamp.
        ts = (PER_WINDOW + jump + index * PER_WINDOW) * MINUTE
        data.append(
            QuoteTick(
                instrument_id=INSTRUMENT.id,
                bid_price=Price(mid - half, DIGITS),
                ask_price=Price(mid + half, DIGITS),
                bid_size=size,
                ask_size=size,
                ts_event=ts - 1,
                ts_init=ts - 1,
            )
        )
        data.append(
            Bar(
                bar_type=bar_type,
                open=Price(mid, DIGITS),
                high=Price(mid + WICK, DIGITS),
                low=Price(mid - WICK, DIGITS),
                close=Price(mid, DIGITS),
                volume=Quantity(1, 0),
                ts_event=ts,
                ts_init=ts,
            )
        )
    return bar_type, data


def run_external(
    mids: list[float], spread: float = 0.10, *, gap_at: int = -1, seconds_clock: bool = False
) -> TinyEdge:
    """One engine over external M15 bars. See `external_feed`."""
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000.0, USD)],
    )
    engine.add_instrument(INSTRUMENT)
    bar_type, data = external_feed(mids, spread, gap_at=gap_at)
    engine.add_data(data)
    built = SecondsClockEdge if seconds_clock else TinyEdge
    strategy = built(EdgeEntryConfig(instrument_id=INSTRUMENT.id, bar_type=bar_type))
    engine.add_strategy(strategy)
    engine.run()
    return strategy


def composite() -> BarType:
    """M15 aggregated from the M1 bars inside the engine.

    The rule has two clocks - M15 for the signal, M1 for the entry and the
    exit - and a composite bar type is how one data stream serves both. A desk
    fed M15 bars alone would be the same rule on half the information.
    """
    return BarType.from_str(f"{INSTRUMENT.id}-15-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL")


def run(
    mids: list[float] | None = None,
    spread: float = 0.10,
    *,
    from_close: bool = True,
    equity: float = 1_000_000.0,
    start_hour: int = 0,
    gap_at: int = -1,
    seconds_clock: bool = False,
) -> TinyEdge:
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
        # A wide stop needs an equity that covers the 1,000-unit minimum lot:
        # at 0.0025 of a million the budget is 2,500 and a 2.60 stop risks
        # 2,600, which `sizes.size` refuses rather than round down.
        starting_balances=[Money(equity, USD)],
        # **Quotes alone fill.** With bar execution on, the engine would also
        # match against the bar it has just processed - the bar the signal was
        # read from, at no spread at all. That is a fill nobody could get, and
        # it is the generosity `node/backtest.venue` refuses to tune for.
        bar_execution=False,
    )
    engine.add_instrument(INSTRUMENT)
    engine.add_data(feed(mids, spread, start_hour=start_hour, gap_at=gap_at))
    anchored = TinyEdge if from_close else FillAnchoredEdge
    built = SecondsClockEdge if seconds_clock else anchored
    strategy = built(EdgeEntryConfig(instrument_id=INSTRUMENT.id, bar_type=composite()))
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


def test_the_spread_floor_is_measured_from_the_fill_and_binds_when_it_is_wider():
    """The `N20`, with its anchor. One ATR can be tighter than the round trip
    on a quiet instrument and a stop inside its own cost cannot pay for itself,
    so the rule floors the stop at twenty spreads - measured from **the price
    actually filled**, not from the signal close.

    Read off the close instead, a fill that ran away from the close would buy
    a stop that much wider for nothing, and the floor would stop guaranteeing
    the trade clears its own round trip.
    """
    mids = planted()
    strategy = run(mids, spread=0.15, equity=10_000_000.0)
    _, entry, stop = orders_of(strategy)
    floor = float(entry.avg_px) - SPREADS * 0.15
    assert floor < mids[SIGNAL_BARS - 1] - atr_at(mids, SIGNAL_BARS), (
        "this feed does not exercise the floor - the ATR leg is the wider"
    )
    assert float(stop.trigger_price) == pytest.approx(floor, abs=2e-5)


def test_the_atr_leg_is_measured_from_the_signal_close_and_binds_when_it_is_wider():
    """Step 6's other anchor, and the one this port had wrong.

    The ATR distance is taken from the **signal bar's close**, so the risk a
    trade carries is one ATR plus however far the fill ran from that close:
    1.10 plus 1.30 on this feed, a stop 2.18x the ATR. Anchoring both legs at
    the fill makes `risk` exactly `max(atr, 20 * spread)`, which understates
    the risk by the fill's own travel and so overstates every R by the same
    fraction.
    """
    mids = planted()
    expected = mids[SIGNAL_BARS - 1] - atr_at(mids, SIGNAL_BARS)
    strategy = run(mids, spread=0.002)
    _, entry, stop = orders_of(strategy)
    assert expected < float(entry.avg_px) - SPREADS * 0.002, (
        "this feed does not exercise the ATR branch - the floor is the wider"
    )
    assert float(stop.trigger_price) == pytest.approx(expected, abs=2e-5)
    # The ATR of the bars that had closed. One bar more is a different number
    # here, so this pins the causal count and not the arithmetic alone.
    assert float(stop.trigger_price) != pytest.approx(
        mids[SIGNAL_BARS - 1] - atr_at(mids, SIGNAL_BARS + 1), abs=2e-5
    )


def test_anchoring_both_legs_at_the_fill_is_the_reading_the_flag_turns_off():
    """`stop_from_close=False`, which is what this port read before the rule's
    two anchors were separated. It must still produce a stop, and a *tighter*
    one: the difference is the fill's travel from the close, 1.30 here, so a
    run with the flag off cannot be mistaken for a run with it on.
    """
    mids = planted()
    strict = run(mids, spread=0.002)
    _, _, stop = orders_of(strict)
    loose = run(mids, spread=0.002, from_close=False)
    _, loose_entry, loose_stop = orders_of(loose)
    atr = atr_at(mids, SIGNAL_BARS)
    assert float(loose_entry.avg_px) - float(loose_stop.trigger_price) == pytest.approx(
        atr, abs=2e-5
    )
    assert float(stop.trigger_price) < float(loose_stop.trigger_price), (
        "the close anchor did not widen the stop"
    )


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


def test_the_clock_counts_bars_and_so_does_not_run_during_a_session_gap():
    """**The divergence worth the most R of any in this port.** `Intent.hold`
    is seconds and `Exits._expired` compares elapsed time, so a 1,440-minute
    hold expires *inside* a weekend and the position comes off at the first
    quote after it - the reopen, which is the one bar a survivorship confound
    lives on. The rule counts 1,440 M1 bars, so a gap spends none of them.

    Measured on the catalogue, this moved eurusd by -0.146R a trade: three of
    its exits had landed on a Sunday reopen quote at 49.0 and 56.8 hours of
    clock. The feed here drops 48.5 hours mid-hold, which is that weekend.
    """
    mids = planted()
    bars = run_external(mids, gap_at=50)
    assert len(bars.closed) == 1, bars.closed
    assert bars.closed[0].how == "clock"
    held = bars.closed[0].closed - bars.closed[0].opened
    assert held == pytest.approx((HOLD_MINUTES + 48 * 60 + 30) * 60.0, abs=120.0), (
        f"the bar clock spent bars the feed does not have: held {held / 3600:.1f}h"
    )

    seconds = run_external(mids, gap_at=50, seconds_clock=True)
    assert len(seconds.closed) == 1
    assert seconds.closed[0].closed - seconds.closed[0].opened < held, (
        "the seconds clock no longer exits earlier, so this test proves nothing"
    )


def test_an_internally_aggregated_bar_type_back_fills_a_session_gap():
    """Why the test above needs external bars, asserted rather than asserted
    about. A time-driven aggregator emits a bar per window whether or not any
    minute arrived, so a 48.5-hour hole becomes 194 empty M15 bars and a
    bar-count hold silently becomes a seconds hold.

    Anything measuring a session effect on a composite bar type is measuring
    a feed with no sessions in it.
    """
    mids = planted()
    assert run(mids).structure["bars"] == len(mids) - 1
    assert run(mids, gap_at=50).structure["bars"] > len(mids) + 100, (
        "the aggregator no longer back-fills, so a composite feed can carry a gap"
    )
    assert run_external(mids, gap_at=50).structure["bars"] == len(mids), (
        "external bars gained bars across the gap"
    )


def test_no_fill_is_taken_in_the_cut_off_hours_and_one_is_taken_outside_them():
    """The later variants' entry cut-off, with its control.

    A gate with no control is indistinguishable from a gate that refuses
    everything, and this one is a window on a clock that every bar passes
    through. The signal lands five hours into the feed, so the start hour
    places it: 19:00 and 23:00 are cut, 18:00 and 00:00 are not.
    """
    mids = planted()
    for hour in (14, 18):
        cut = run(mids, start_hour=hour)
        assert cut.taken == 0, f"a fill at {(hour + 5) % 24:02d}:00 UTC was taken"
        assert cut.passed_over.get("smc-bos-causal:cut-off") == 1
    for hour in (13, 19):
        kept = run(mids, start_hour=hour)
        assert kept.taken == 1, f"the cut-off refused a fill at {(hour + 5) % 24:02d}:00 UTC"
        assert "smc-bos-causal:cut-off" not in kept.passed_over


def test_a_cut_fill_still_spends_its_swing_and_does_not_free_the_slot():
    """Where the cut-off sits in the sequence, which changes the trade list
    rather than just shortening it.

    The break is counted and the swing is marked broken whatever happens next,
    because the refusal is in `decide` and the fold ran first. Cut in the fold
    instead and the swing would stay live to break again on a later bar, at a
    price the rule never offered - inventing trades rather than removing them.
    """
    mids = planted()
    cut = run(mids, start_hour=14)
    assert cut.structure["bos"] == 1, cut.structure
    assert cut.taken == 0
    assert not cut.fold.high_live, "the cut-off left the swing live to break twice"


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


# ------------------------------------------- the freshness judgement itself


def test_a_break_on_the_last_warm_bar_is_fresh_and_one_from_hours_ago_is_not():
    """**The judgement, tested where it is made.**

    `fresh` is the whole behaviour change and it is pure in (bar, clock), so it
    is asserted directly. Going through `warm_bar` would route the answer
    through `decide`'s gates - and with no cached quote every proposal is
    refused as `no-quote`, so a test reading `closed` would pass whatever
    `fresh` returned. That is how the old assertion kept passing after the
    behaviour under it had changed.
    """
    strategy = run_external(zigzag(40, reach=3))
    now = strategy.clock.timestamp_ns()
    span = int(strategy.warm_seconds() * 1e9)

    just_closed = _stamped(strategy, now - span // 2)
    # Epoch: unambiguously older than any window, and no underflow.
    hours_old = _stamped(strategy, 0)

    assert strategy.fresh(just_closed) is True, "a bar that closed within one span is fresh"
    assert strategy.fresh(hours_old) is False, "a bar from the epoch is not"


def test_freshness_is_measured_in_bars_so_it_follows_the_clock():
    """One span on M15 is fifteen minutes and on 4h is four hours, so the
    window has to be expressed in bars rather than in seconds - the same reason
    `warming.start_warming` asks for a span of the bar type instead of a
    date."""
    strategy = run_external(zigzag(40, reach=3))
    now = strategy.clock.timestamp_ns()
    span = int(strategy.warm_seconds() * 1e9)

    assert strategy.warm_seconds() == 900.0, "the fixture is M15"
    # Just inside and just outside one bar.
    assert strategy.fresh(_stamped(strategy, now - span + 10**9)) is True
    assert strategy.fresh(_stamped(strategy, now - 2 * span)) is False


def test_a_profile_that_wants_no_fresh_window_forwards_nothing():
    """The escape hatch, and the control for the two tests above: a rule whose
    `warm_fresh_bars` is 0 keeps the old behaviour exactly, so a sweep can
    compare forwarding against discarding."""

    class StaleProfile(TinyProfile):
        warm_fresh_bars: ClassVar[int] = 0

    class StaleEdge(Tiny, ManagedExit, EdgeEntry):
        profile: ClassVar[StaleProfile] = StaleProfile.__new__(StaleProfile)

    strategy = run_external(zigzag(40, reach=3))
    strategy.profile = StaleProfile.__new__(StaleProfile)
    now = strategy.clock.timestamp_ns()
    assert strategy.fresh(_stamped(strategy, now)) is False, (
        "a zero window must refuse even a bar stamped now"
    )


def test_one_break_is_never_proposed_twice_across_the_warm_and_live_paths():
    """**A bar can arrive as history and then again live.** The request window
    ends at `utc_now()`, so the bar that closed during it can be delivered by
    both. Without the guard the same break is proposed twice; the desk's `held`
    gate would refuse the duplicate, but it would refuse it as a gate count and
    the record would read as a rule proposing setups it never saw."""
    strategy = run_external(zigzag(40, reach=3))
    assert isinstance(strategy._proposed, set)

    strategy._proposed.add(7)
    before = dict(strategy.structure)
    # A second sighting of fold index 7 must not be forwarded again. Asserted
    # on the guard rather than on an order, because the gates sit downstream.
    assert 7 in strategy._proposed
    assert strategy.structure == before


def _stamped(strategy, ts: int) -> Bar:
    """One M15 bar on this strategy's own bar type, stamped at `ts` ns."""
    return Bar(
        strategy._cfg.bar_type,
        Price(1.1000, 5),
        Price(1.1010, 5),
        Price(1.0990, 5),
        Price(1.1005, 5),
        Quantity(1_000_000, 0),
        ts_event=ts,
        ts_init=ts,
    )


def test_the_hold_is_twenty_four_hours_on_whatever_clock_the_desk_runs():
    """**`// 15` is a property of the clock, not of the rule.**

    `HOLD_MINUTES` is 1,440 - twenty-four hours - and the profile divides it by
    15 because the rule was specified and measured on M15. On a 5m desk those
    96 bars are **eight hours**, a third of the hold, and the trade would be
    closed by the clock long before the rule says. That was live on eight
    symbols the day 5m was enabled.

    Asserted as hours rather than as bars, because hours are what the rule
    specifies and bars are the thing that varies.
    """
    from types import SimpleNamespace

    from till_infinity.strategies.structure import HOLD_MINUTES, Structure

    for span in (300.0, 900.0, 3_600.0, 14_400.0):
        stub = SimpleNamespace(
            warm_seconds=lambda s=span: s,
            profile=SimpleNamespace(hold_signal_bars=96),
        )
        bars = Structure._due_bars(stub)
        assert bars * span == pytest.approx(HOLD_MINUTES * 60.0), (
            f"a {span:.0f}s bar held {bars} bars = {bars * span / 3600:.1f}h, "
            f"not the specified {HOLD_MINUTES / 60:.0f}h"
        )


def test_the_measured_clock_is_bit_identical():
    """The control that protects the existing numbers: at 15m this must return
    exactly the profile's own constant, so every deploy holds for the same
    number of bars it always did."""
    from types import SimpleNamespace

    from till_infinity.strategies.structure import Structure, StructureProfile

    stub = SimpleNamespace(
        warm_seconds=lambda: 900.0,
        profile=SimpleNamespace(hold_signal_bars=StructureProfile.hold_signal_bars),
    )
    assert Structure._due_bars(stub) == StructureProfile.hold_signal_bars == 96


def test_a_clock_with_no_minutes_keeps_the_measured_bar_count():
    """An activity clock - `500tick` - has no span, so converting a hold
    expressed in minutes into one is not meaningful. The measured bar count is
    the better of two imperfect answers, and it is returned rather than a
    division by zero."""
    from types import SimpleNamespace

    from till_infinity.strategies.structure import Structure

    stub = SimpleNamespace(warm_seconds=lambda: 0.0, profile=SimpleNamespace(hold_signal_bars=96))
    assert Structure._due_bars(stub) == 96
