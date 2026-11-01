"""The indicators layer: that it is Nautilus's, and that the traps stay shut.

Three kinds of test here, in order of how much they would cost to lose:

1. **The framework contract.** Every detector is a `nautilus_trader` `Indicator`
   and an `Actor` can register it. If that breaks, the engine stops feeding them
   and nothing fails loudly - the indicators never update.
2. **The two traps.** `reset` means Nautilus's thing and not `restart`, and a
   scale has to be in the right units. Both are silent when wrong.
3. **The readings.** That each detector measures what its research says it
   measures, on a stream built so the answer is known.
"""

from __future__ import annotations

import math

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity

import till_infinity.indicators as ind
from till_infinity.indicators.bars import DIMENSION, SCALED_BY, Dimension, Reading, read

BAR_TYPE = BarType.from_str("EURUSD.SIM-1-HOUR-LAST-EXTERNAL")
HOUR_NS = 3_600_000_000_000


def bar(open_: float, high: float, low: float, close: float, ts: int = 0) -> Bar:
    return Bar(
        BAR_TYPE,
        Price(open_, 5),
        Price(high, 5),
        Price(low, 5),
        Price(close, 5),
        Quantity(100, 0),
        ts_event=ts,
        ts_init=ts,
    )


def turning(n: int, *, seed: int = 5, start: float = 1.1000, step: float = 0.0004):
    """A deterministic random walk: turns at every scale, which `walk` has none of.

    `walk` superimposes a sine on a drift, and at any drift large enough to
    recover from a slope test the drift dominates - so no bar is the strict
    extreme of its neighbourhood and a pivot detector finds nothing. That is
    the detector being right, and it cost two failing tests to see: a 600-bar
    series with a 126-bar period still produced no pivot over Bjorgum's 36-bar
    window. A walk has local extremes at every window length.
    """
    import random

    rng = random.Random(seed)
    price, ts, out = start, 0, []
    for _ in range(n):
        price += rng.gauss(0.0, step)
        high = price + abs(rng.gauss(0.0, step / 2))
        low = price - abs(rng.gauss(0.0, step / 2))
        out.append(bar(price, high, low, price, ts))
        ts += HOUR_NS
    return out


def walk(n: int, *, drift: float = 0.0, wiggle: float = 0.0015, start: float = 1.1000):
    """A deterministic series, so a failure is reproducible rather than seeded."""
    out = []
    ts = 0
    for i in range(n):
        close = start + drift * i + wiggle * math.sin(i / 3.0)
        out.append(bar(close, close + 0.0004, close - 0.0004, close, ts))
        ts += HOUR_NS
    return out


# ------------------------------------------------------------ the framework


@pytest.mark.parametrize("name", sorted(ind.BAR_DETECTORS))
def test_every_detector_is_a_nautilus_indicator(name):
    """Not an object behind an adapter: the framework's own base class.

    This is what lets the engine drive them. An `Actor` carries the whole
    indicator API identically to a `Strategy` - which is why the statespace
    actor can hold detectors without pretending to be one.
    """
    detector = ind.build_detector(name)
    assert isinstance(detector, Indicator), f"{name} is not a Nautilus Indicator"
    assert detector.name == type(detector).__name__, (
        f"{name} has name {detector.name!r} - `Indicator.__init__` was never "
        f"called, so Nautilus has no parameters and no name for it."
    )
    assert detector.initialized is False
    assert detector.has_inputs is False


@pytest.mark.parametrize("name", sorted(ind.BAR_DETECTORS))
def test_an_actor_can_register_every_detector(name):
    """`Actor.register_indicator_for_bars`, which is the whole integration.

    Checked on a bare `Actor` rather than ours, so this fails if Nautilus moves
    the API rather than if our actor changes.
    """
    detector = ind.build_detector(name)
    actor = Actor()
    actor.register_indicator_for_bars(BAR_TYPE, detector)
    assert detector in actor.registered_indicators


@pytest.mark.parametrize("name", sorted(ind.BAR_DETECTORS))
def test_a_detector_warms_and_then_reports_initialized(name):
    """`indicators_initialized` is what a strategy gates on, so it has to arrive."""
    detector = ind.build_detector(name)
    stream = turning(600)
    for one in stream:
        detector.handle_bar(one)
    assert detector.has_inputs
    assert detector.initialized, f"{name} never initialized over {len(stream)} bars"


@pytest.mark.parametrize("name", sorted(ind.BAR_DETECTORS))
def test_reset_returns_a_detector_to_before_its_first_bar(name):
    """Nautilus's `reset` means *this has never seen anything*.

    The engine calls it on a rewind, so a detector that kept any state would
    report readings from the run before. Checked by feeding, resetting, and
    comparing against a fresh one fed the same stream - which catches a partial
    reset that leaves a field behind, where asserting `initialized is False`
    alone would not.
    """
    stream = walk(60, drift=0.0002)
    used = ind.build_detector(name)
    for one in stream:
        used.handle_bar(one)
    used.reset()
    assert used.has_inputs is False
    assert used.initialized is False

    fresh = ind.build_detector(name)
    for detector in (used, fresh):
        for one in stream:
            detector.handle_bar(one)
    assert repr(used) == repr(fresh) or _readings(used) == _readings(fresh), (
        f"{name} after reset does not match a fresh one fed the same bars"
    )


def _readings(detector) -> dict:
    """The public numbers a detector reports, for comparing two of them."""
    out = {}
    for attr in dir(type(detector)):
        if attr.startswith("_") or attr in {"name", "params"}:
            continue
        value = getattr(type(detector), attr, None)
        if isinstance(value, property):
            try:
                got = getattr(detector, attr)
            except Exception:
                continue
            if isinstance(got, int | float | str | bool | type(None)):
                out[attr] = got
    return out


def test_restart_is_not_reset_on_the_accumulating_detectors():
    """The trap this layer was built around.

    `Cusum.restart` and `Focus.restart` mean *a change has been acted on,
    accumulate from here*, and deliberately keep the stream's history.
    Nautilus's `reset` means *never seen anything*. Wiring one to the other
    gives a detector reporting a fresh statistic over a total it never
    cleared - indistinguishable from fresh at every surface a caller has.
    """
    focus = ind.Focus()
    for i in range(400):
        focus.update(1.0 if i > 200 else 0.0, 1.0)
    seen, total = focus.seen, focus.total
    assert seen > 0
    assert total != 0.0

    focus.restart()
    assert focus.statistic == 0.0, "restart clears the statistic"
    assert focus.seen == seen, "restart keeps the stream's history"
    assert focus.total == total, "restart keeps the stream's history"

    focus.reset()
    assert focus.seen == 0, "reset is Nautilus's: the stream is gone too"
    assert focus.total == 0.0

    cusum = ind.Cusum()
    for i in range(50):
        cusum.push(1.1000 + 0.0005 * i, 0.0004, float(i), i)
    assert cusum.started
    cusum.restart()
    assert cusum.up == 0.0
    assert cusum.down == 0.0
    assert cusum.started, "restart keeps the price series"
    cusum.reset()
    assert cusum.started is False


# ----------------------------------------------------------------- the scale


def test_a_detector_refuses_to_be_built_without_a_scale():
    """At wiring time, not inside a handler on a live feed."""
    with pytest.raises(ValueError, match="needs a scale"):
        ind.Focus(unit=0.0, unit_from=None)


def test_a_detector_refuses_a_unit_in_the_wrong_dimension():
    """The bug that is invisible on EURUSD.

    At a price near 1.0 a relative spread and a price distance are the same
    number, so a log return divided by a price range reads perfectly calibrated
    there and is wrong by a factor of the price on gold. This caught itself
    during development: `unit_from=RANGE` was the default on a `LOG_RETURN`
    source.
    """
    with pytest.raises(ValueError, match="units error"):
        ind.Focus(source=Reading.LOG_RETURN, unit_from=Reading.RANGE)
    with pytest.raises(ValueError, match="units error"):
        ind.Cusum(source=Reading.CLOSE, unit_from=Reading.RELATIVE_RANGE)


def test_a_signed_reading_cannot_be_a_unit():
    """A unit divides, so it must not pass through zero."""
    with pytest.raises(ValueError, match="signed or passes through zero"):
        ind.Cusum(source=Reading.CLOSE, unit_from=Reading.BODY)


@pytest.mark.parametrize("name", sorted(ind.BAR_DETECTORS))
def test_every_catalogued_default_is_dimensionally_sound(name):
    """A sweep built from `BAR_DETECTORS` cannot produce a unit error by accident.

    Every listed source, against the detector's own default unit. If one of
    these pairs is wrong the sweep spends trials on a miscalibrated detector,
    and trials are the scarce thing - at a target Sharpe of 1.5 one month of
    data supports about one.
    """
    _, sources = ind.BAR_DETECTORS[name]
    # `pips` and `bjorgum` list none: they read bars directly rather than one
    # selectable reading, so their cells here are empty on purpose.
    for source in sources:
        detector = ind.build_detector(name, source)
        assert detector.source is source
        if getattr(detector, "unit_from", None) is None:
            continue
        assert SCALED_BY[DIMENSION[source]] is DIMENSION[detector.unit_from], (
            f"{name} on {source} got a {detector.unit_from} unit"
        )


def test_the_relative_range_is_the_range_over_the_close():
    """And that the two range readings differ by exactly the price."""
    one = bar(1.1000, 1.1050, 1.1000, 1.1020)
    assert read(one, Reading.RANGE) == pytest.approx(0.0050)
    assert read(one, Reading.RELATIVE_RANGE) == pytest.approx(0.0050 / 1.1020)
    assert DIMENSION[Reading.RANGE] is Dimension.DIFFERENCE
    assert DIMENSION[Reading.RELATIVE_RANGE] is Dimension.RELATIVE


def test_a_reading_that_needs_a_previous_bar_says_so_rather_than_guessing():
    """None, not zero. A zero return would read as "price did not move"."""
    one = bar(1.1000, 1.1050, 1.1000, 1.1020)
    assert read(one, Reading.LOG_RETURN, None) is None
    assert read(one, Reading.LOG_RETURN, 1.1000) == pytest.approx(math.log(1.1020 / 1.1000))


# ---------------------------------------------------------- the displacement


def _push(ts0: int = 0) -> list[Bar]:
    """An origin candle, two impulsive up candles, a pause, one more impulsive.

    Built to the rule in `zone-rules.md`: bodies at 70%+ of their range, each
    closing past the one before, and one ordinary candle in the middle that
    `CHAIN_GAP` of 1 lets the leg step over.
    """
    spec = [
        (1.1000, 1.1012, 1.0995, 1.1005),  # the origin: a small body
        (1.1005, 1.1040, 1.1004, 1.1038),  # impulsive
        (1.1038, 1.1075, 1.1037, 1.1073),  # impulsive
        (1.1073, 1.1080, 1.1065, 1.1070),  # the pause
        (1.1070, 1.1110, 1.1069, 1.1107),  # impulsive again
    ]
    ts = ts0
    out = []
    for o, h, low, c in spec:
        out.append(bar(o, h, low, c, ts))
        ts += HOUR_NS
    return out


def test_the_origin_is_the_candle_before_the_chain():
    """The desk's search order: find the impulse, then the candle before it.

    *"look for impulsive candles, then candle before this impulsive candle"* -
    so the origin ranks last, furthest from where price is now, and that is
    the one a fade aims at.
    """
    detector = ind.Displacement()
    for one in _push():
        detector.handle_bar(one)
    assert len(detector.legs) == 1
    assert detector.side == 1
    origin = detector.origin
    assert origin is not None
    assert origin.low == pytest.approx(1.0995)
    assert origin.high == pytest.approx(1.1012)
    assert origin.line == pytest.approx(1.1005), "the line is where the origin closed"
    assert origin.rank == max(o.rank for o in detector.origins)


def test_a_leg_steps_over_one_ordinary_candle():
    """`CHAIN_GAP`, and why consecutive-only was not enough.

    One ordinary candle in the middle of a leg ended the displacement and the
    whole setup was dropped, however obvious the move looked. Here the pause
    becomes rank 1 - the nearest zone - rather than ending the chain.
    """
    detector = ind.Displacement()
    for one in _push():
        detector.handle_bar(one)
    ranks = {o.rank: o for o in detector.origins}
    assert ranks[1].low == pytest.approx(1.1065), "rank 1 is the pause nearest the end"
    assert detector.bars == 4, "the leg spans the pause"

    strict = ind.Displacement(chain_gap=0)
    for one in _push():
        strict.handle_bar(one)
    assert strict.bars < detector.bars, "chain_gap=0 stops at the pause"


def test_a_single_strong_candle_is_not_a_displacement():
    """`PUSH_MIN` of 2, and 1 is refused rather than silently allowed."""
    with pytest.raises(ValueError, match="not a displacement"):
        ind.Displacement(push_min=1)


def test_toward_names_where_to_look_and_not_which_way_to_trade():
    """The sign convention, because reversing it is a reversed target."""
    detector = ind.Displacement()
    for one in _push():
        detector.handle_bar(one)
    below = detector.toward(1.1107, -1)
    assert below is not None
    assert below.high < 1.1107
    assert detector.toward(1.1107, 1) is None, "nothing above the high of the leg"


# ------------------------------------------------------------------- the gaps


def test_a_gap_closes_on_the_bar_that_fills_it():
    """Causality, which is the whole reason this is incremental.

    A gap list holding only *unfilled* gaps is lookahead the moment it is read
    as of a time before the fill was known - the desk measured +0.50R a trade
    doing that, which was a measurement of its own lookahead.
    """
    detector = ind.Gaps()
    ts = 0
    for one in _push():
        detector.handle_bar(one)
    ts = 5 * HOUR_NS
    assert detector.opened > 0
    assert detector.count == detector.opened, "nothing has filled yet"
    assert detector.fill_rate == 0.0

    live = detector.live[0]
    assert live.live
    assert live.filled_at is None
    # A bar that trades back through the nearest gap.
    detector.handle_bar(bar(1.1107, 1.1108, live.low - 0.0001, live.low, ts))
    assert detector.filled_total >= 1
    assert live.filled_at is not None, "the gap records when it closed"
    assert live.live is False


def test_a_fill_rate_counts_the_gaps_that_are_still_open():
    """Over the closed ones alone it is 1.0 by construction."""
    detector = ind.Gaps()
    for one in _push():
        detector.handle_bar(one)
    rate = detector.fill_rate
    assert rate is not None
    assert rate == pytest.approx(detector.filled_total / detector.opened)
    assert rate < 1.0, "live gaps are in the denominator"


def test_a_bar_cannot_both_open_a_gap_and_fill_it():
    """Fills are applied before new gaps, so a gap is never filled by its own
    forming bar - which it would appear to be if the order were reversed."""
    detector = ind.Gaps()
    for one in _push():
        detector.handle_bar(one)
    assert detector.live, "no gap formed, so the ordering is untested"
    for gap in detector.live:
        assert gap.filled_at is None or gap.filled_at > gap.when


def test_the_gap_floor_is_in_volatility_units():
    """Without a scale the floor is in price and the count measures the tick size."""
    tight = ind.Gaps(min_gap_vol=1000.0)
    for one in _push():
        tight.handle_bar(one)
    assert tight.opened == 0, "a floor of 1000 volatility units admits nothing"


# -------------------------------------------------------------- the trendlines


def test_a_pivot_is_confirmed_after_it_happened_and_both_times_are_kept():
    """The one way a trendline is drawn dishonestly.

    A line through pivots marked where they *happened* rather than where they
    were *confirmed* could not have been drawn at the time, and every touch it
    reports is a touch of a line from the future.
    """
    detector = ind.Trendlines()
    for one in walk(80, drift=0.0002):
        detector.handle_bar(one)
    assert detector.highs
    assert detector.lows
    for pivot in (*detector.highs, *detector.lows):
        assert pivot.confirmed > pivot.when, "a pivot cannot be known when it printed"
        assert pivot.lag == pytest.approx(detector.reach, abs=0.01)


def test_the_two_lines_are_fitted_independently_from_the_top_and_the_bottom():
    """A single line collapses them, and the useful reading is often that they
    disagree. On a planted drift both should recover its gradient."""
    detector = ind.Trendlines()
    for one in walk(80, drift=0.0002):
        detector.handle_bar(one)
    assert detector.resistance is not None
    assert detector.support is not None
    assert detector.resistance.side == 1
    assert detector.support.side == -1
    for line in (detector.resistance, detector.support):
        assert line.per_hour() == pytest.approx(0.0002, rel=0.35)
    assert detector.inside is True


def test_a_break_is_a_close_and_it_has_to_hold():
    """A wick through and back is the shape the line describes, not a break.

    And the holding is where most of a break goes: of 889 closes past a 20-bar
    high, only 515 held - so reporting the crossing alone overstates it by two
    thirds.
    """
    detector = ind.Trendlines()
    stream = walk(80, drift=0.0002)
    for one in stream:
        detector.handle_bar(one)
    assert detector.broke == 0
    assert detector.extent_vol is None, "no break is None, not a zero extent"

    ts = len(stream) * HOUR_NS
    line = detector.resistance.at(detector.when)
    # A wick through the line, closing back inside. Small, because a large one
    # confirms as a pivot high and redraws the line - which is its own test.
    detector.handle_bar(
        bar(detector.price, line + 0.0005, detector.price - 0.0004, detector.price, ts)
    )
    assert detector.broke == 0, "a wick through the line is not a break"

    held = []
    for _ in (1, 2, 3):
        ts += HOUR_NS
        close = detector.resistance.at(detector.when) + 0.0030
        detector.handle_bar(bar(close, close + 0.0004, close - 0.0004, close, ts))
        held.append((detector.broke, detector.held))
    assert held == [(1, 1), (1, 2), (1, 3)]
    assert detector.extent_vol is not None
    assert detector.extent_vol > 0.0


def test_a_refit_can_end_a_break_without_price_moving():
    """And that is correct, not a glitch.

    A newly confirmed pivot high redraws resistance; if the redrawn line is
    above price, price is no longer past it. Carrying the old break forward
    would be a reading about a line that no longer exists. Found by a test that
    planted a tall wick, which then confirmed as a pivot and moved the line
    over price - so the behaviour is pinned here rather than worked around.
    """
    detector = ind.Trendlines()
    stream = walk(80, drift=0.0002)
    for one in stream:
        detector.handle_bar(one)
    ts = len(stream) * HOUR_NS
    tall = detector.resistance.at(detector.when) + 0.0100
    detector.handle_bar(bar(detector.price, tall, detector.price - 0.0004, detector.price, ts))
    before = detector.resistance.at(detector.when)
    for _ in (1, 2, 3, 4):
        ts += HOUR_NS
        close = before + 0.0030
        detector.handle_bar(bar(close, close + 0.0004, close - 0.0004, close, ts))
    after = detector.resistance.at(detector.when)
    assert after > before, "the tall wick confirmed as a pivot and lifted the line"
    assert detector.broke == 0, "price is no longer past the redrawn line"


def test_a_span_too_short_to_confirm_a_pivot_is_refused():
    """Otherwise both lines stay None forever and nothing says why."""
    with pytest.raises(ValueError, match="cannot hold a pivot"):
        ind.Trendlines(reach=5, span=6)


# ------------------------------------------------------------------ the ticks


class _Trade:
    def __init__(self, side: int) -> None:
        self.aggressor_side = side


class _Quote:
    def __init__(self, bid: float, ask: float) -> None:
        self.bid_price = bid
        self.ask_price = ask


def test_tick_momentum_is_signed_by_who_crossed_the_spread():
    """And follows the package convention: -1..+1, 0 neutral, +1 bullish."""
    detector = ind.TickMomentum(half_life=5)
    for _ in range(40):
        detector.handle_trade_tick(_Trade(1))
    assert detector.basis is ind.Basis.TRADES
    assert detector.momentum == pytest.approx(1.0, abs=0.01)
    for _ in range(40):
        detector.handle_trade_tick(_Trade(2))
    assert detector.momentum == pytest.approx(-1.0, abs=0.01)


def test_a_trade_without_an_aggressor_is_dropped_and_not_counted_as_neutral():
    """Folding it in as zero makes the average report how often the venue is
    uninformative, wearing the shape of a reading about the market."""
    detector = ind.TickMomentum(half_life=5)
    for _ in range(40):
        detector.handle_trade_tick(_Trade(1))
    before, ticks = detector.momentum, detector.ticks
    for _ in range(20):
        detector.handle_trade_tick(_Trade(0))
    assert detector.momentum == before
    assert detector.ticks == ticks


def test_quote_revisions_are_used_where_there_are_no_trades():
    """Which is MT5: `last` and `volume` read 0 or a constant 5000 there, and
    the one directional thing in the stream is which side moved."""
    detector = ind.TickMomentum(half_life=5)
    bid, ask = 1.1000, 1.1002
    for _ in range(40):
        bid, ask = bid + 0.0001, ask + 0.0001
        detector.handle_quote_tick(_Quote(bid, ask))
    assert detector.basis is ind.Basis.QUOTES
    assert detector.momentum > 0.9
    assert detector.spread == pytest.approx(0.0002)


def test_one_sided_revisions_are_counted_separately():
    """22.8% on this desk's terminal, so a reading far from it says something
    about the feed before it says anything about the market."""
    detector = ind.TickMomentum(half_life=5)
    bid, ask = 1.1000, 1.1002
    detector.handle_quote_tick(_Quote(bid, ask))
    for _ in range(40):
        bid += 0.0001  # the bid alone moves
        detector.handle_quote_tick(_Quote(bid, ask))
    assert detector.one_sided > 0.9


def test_a_trade_feed_wins_over_a_quote_feed():
    """An aggressor side is a fact; a revision is an inference about one."""
    detector = ind.TickMomentum(half_life=5)
    for _ in range(20):
        detector.handle_trade_tick(_Trade(1))
    before = detector.momentum
    bid, ask = 1.1000, 1.1002
    for _ in range(20):
        bid, ask = bid - 0.0005, ask - 0.0005
        detector.handle_quote_tick(_Quote(bid, ask))
    assert detector.basis is ind.Basis.TRADES
    assert detector.momentum == before, "quotes do not move a trade-based reading"


# ------------------------------------------------- the framework's own faults


def test_the_framework_efficiency_ratio_is_biased_and_ours_is_not():
    """Pins an upstream bug, so a fix shows up as a failure rather than a drift.

    `indicators.momentum.EfficiencyRatio` takes its numerator over one fewer
    step than its denominator. On a straight line - every step the same way,
    ratio 1.0 by definition - it reports `(period - 1) / period`, so it is
    bounded above by that and biased low by `1 / period`, worst exactly where a
    short window is wanted.

    If this test starts failing, upstream has fixed it: check whether
    `trend.ratio` can now be replaced, and remember that the replacement
    changes every number measured on the old one.
    """
    from nautilus_trader.indicators.momentum import EfficiencyRatio

    from till_infinity.indicators.trend import ratio

    line = [float(i) for i in range(60)]
    assert ratio(line) == pytest.approx(1.0), "ours is 1.0 on a straight line"
    for period in (2, 3, 5, 10, 20):
        theirs = EfficiencyRatio(period)
        for price in line:
            theirs.update_raw(price)
        assert theirs.initialized
        assert theirs.value == pytest.approx((period - 1) / period), (
            f"EfficiencyRatio({period}) on a straight line"
        )
        assert theirs.value < 1.0, "it can never report a perfectly efficient move"


def test_the_framework_swings_tracks_a_running_extreme_not_a_confirmed_pivot():
    """Why `Trendlines` detects its own pivots instead of using `Swings`.

    On a rising series `Swings.since_high` is 0: the high it reports is this
    bar's. A line fitted through running extremes is refitted every time price
    makes a new high, which is a line from the future.
    """
    from nautilus_trader.indicators.trend import Swings

    swings = Swings(3)
    stream = walk(60, drift=0.0002)
    for one in stream:
        swings.handle_bar(one)
    assert swings.since_high == 0, "the reported high is the current bar's"

    ours = ind.Trendlines()
    for one in stream:
        ours.handle_bar(one)
    for pivot in ours.highs:
        assert pivot.confirmed > pivot.when


# ----------------------------------------------------------------- the spread


def test_the_rolling_spread_keeps_updating_once_its_window_fills():
    """Which is the upstream bug it exists for.

    `nautilus_trader.indicators.SpreadAnalyzer.average` freezes once its window
    fills - measured on 1.221.0 - because it appends and then subtracts the
    value it just appended.
    """
    detector = ind.RollingSpread(4)
    seen = []
    for i in range(1, 9):
        detector.handle_quote_tick(_Quote(1.1000, 1.1000 + 0.0001 * i))
        seen.append(detector.average)
    assert len(set(seen[-4:])) == 4, "the average moved on every one of the last four"
    assert detector.initialized


def test_a_crossed_quote_from_the_engine_is_counted_and_dropped():
    """A bid above an ask is a bad tick, not a wide spread, and folding it in
    makes the average read *tighter* than the truth."""
    detector = ind.RollingSpread(4)
    detector.handle_quote_tick(_Quote(1.1000, 1.1002))
    detector.handle_quote_tick(_Quote(1.1005, 1.1000))
    assert detector.crossed == 1
    assert detector.count == 1
    assert detector.average == pytest.approx(0.0002)


# ----------------------------------------------------------------- the speeds


def test_speeds_keys_itself_by_bar_type():
    """One `Speeds` holds many feeds, which is what the class is for.

    The same instrument at 1m and at 1h is two series, and a shared previous
    close would make every return the gap between whichever two feeds arrived
    next to each other.
    """
    other = BarType.from_str("GBPUSD.SIM-1-HOUR-LAST-EXTERNAL")
    detector = ind.Speeds()
    for one in walk(40, drift=0.0005):
        detector.handle_bar(one)
    assert detector.ready(str(BAR_TYPE))
    assert not detector.ready(str(other)), "an unseen feed is not warm"
    # A planted upward drift: all three half-lives see it, so agreement holds
    # one way and not the other. An unseen feed agrees with nothing, which is
    # what stops a second instrument reading off this one's series.
    assert detector.agree(str(BAR_TYPE), 1) is True
    assert detector.agree(str(BAR_TYPE), -1) is False
    assert detector.agree(str(other), 1) is False
    assert detector.agree(str(other), -1) is False


# ------------------------------------------------------------- slope momentum


def test_slope_momentum_recovers_a_planted_gradient_and_its_change():
    """A slope difference is an acceleration, so a constant drift gives zero."""
    straight = ind.SlopeMomentum(window=20, lag=1)
    for one in walk(80, drift=0.0002, wiggle=0.0):
        straight.handle_bar(one)
    assert straight.slope == pytest.approx(0.0002, rel=1e-6)
    assert straight.change == pytest.approx(0.0, abs=1e-12), "a constant slope has no acceleration"
    assert straight.turning == 0


def test_slope_momentum_says_whether_its_windows_overlap():
    """Consecutive rolling slopes share all but one bar, which is the whole
    difficulty: the difference is driven by the two bars that moved."""
    overlapping = ind.SlopeMomentum(window=20, lag=1, stride=1)
    assert overlapping.overlapping is True
    assert overlapping.shared_bars == 19

    clean = ind.SlopeMomentum(window=20, lag=1, stride=20)
    assert clean.overlapping is False
    assert clean.shared_bars == 0

    also_clean = ind.SlopeMomentum(window=20, lag=4, stride=5)
    assert also_clean.overlapping is False


def test_slope_momentum_reports_a_change_in_units_of_its_own_error():
    """And the error is the independent one, which over-states it on
    overlapping windows - conservative, which is the right direction."""
    detector = ind.SlopeMomentum(window=20, lag=1)
    for one in walk(80, drift=0.0002):
        detector.handle_bar(one)
    assert detector.slope_se > 0.0
    assert detector.change_se == pytest.approx(detector.slope_se * math.sqrt(2.0))
    assert detector.change_z == pytest.approx(detector.change / detector.change_se)


def test_a_two_point_slope_window_is_refused():
    """Two points are a chord with no residual, so there is no standard error."""
    with pytest.raises(ValueError, match="not a slope"):
        ind.SlopeMomentum(window=2)


# --------------------------------------------------------------------- ticks


def test_cusum_focus_and_changepoint_all_take_ticks():
    """A tick is a price, which is what these accumulate - on a faster clock."""

    class Quote:
        def __init__(self, bid, ask, ts):
            self.bid_price, self.ask_price, self.ts_event = bid, ask, ts

    def stream(n=500):
        price, ts = 1.10000, 0
        for i in range(n):
            price += (0.000006 if i > 250 else 0.0) + (0.000012 if i % 2 else -0.000012)
            yield Quote(price - 0.00001, price + 0.00001, ts)
            ts += 1_000_000_000

    for build in (ind.Cusum, ind.Focus, ind.Changepoint):
        detector = build(tick_span=50)
        for quote in stream():
            detector.handle_quote_tick(quote)
        assert detector.has_inputs, build.__name__
        assert detector.initialized, build.__name__
        assert detector._tick_scale > 0.0, build.__name__


def test_a_detector_refuses_to_be_fed_two_clocks_at_once():
    """One set of accumulators, so two feeds interleave two clocks into them
    and the result is a plausible-looking number from neither."""

    class Quote:
        def __init__(self, bid, ask, ts):
            self.bid_price, self.ask_price, self.ts_event = bid, ask, ts

    one = bar(1.1000, 1.1005, 1.0995, 1.1002)
    for build in (ind.Cusum, ind.Focus, ind.Changepoint):
        detector = build()
        detector.handle_quote_tick(Quote(1.1001, 1.1003, 0))
        with pytest.raises(RuntimeError, match="interleave two clocks"):
            detector.handle_bar(one)


def test_a_relative_detector_gets_a_relative_tick_scale():
    """`Focus` is fed the tick-to-tick change, not the level: the mean of a
    price series shifts whenever price does."""
    from till_infinity.indicators.bars import tick_input

    class Tick:
        def __init__(self, price):
            self.price = price

    class Holder:
        tick_span = 10
        _tick_prev = None
        _tick_scale = 0.0

    holder = Holder()
    assert tick_input(holder, Tick(100.0), relative=True) == (None, 0.0)
    value, scale = tick_input(holder, Tick(101.0), relative=True)
    assert value == pytest.approx(math.log(101.0 / 100.0))
    assert scale == pytest.approx(abs(value)), "a relative reading gets a relative scale"


# ---------------------------------------------------------------------- pips


def test_pips_publishes_only_what_was_knowable():
    """A PIP found in a window including later bars was not knowable when it
    formed, and a level built from one is a level nobody could have drawn."""
    detector = ind.Pips(count=8, span=120)
    stream = [
        bar(c, c + 0.0006, c - 0.0006, c, i * HOUR_NS)
        for i, c in enumerate(1.1000 + 0.00002 * i + 0.0040 * math.sin(i / 7.0) for i in range(150))
    ]
    for one in stream:
        detector.handle_bar(one)
    assert detector.turns, "an oscillating series has turns"
    for point in detector.points:
        assert point.confirmed <= detector.when * 1e9
    for point in detector.turns:
        assert point.confirmed > point.time, "a turn cannot be known when it printed"


def test_pips_labels_a_structure_sequence():
    """HH, LH, HL, LL against the previous swing of the same kind."""
    detector = ind.Pips(count=8, span=120)
    for i in range(150):
        close = 1.1000 + 0.00002 * i + 0.0040 * math.sin(i / 7.0)
        detector.handle_bar(bar(close, close + 0.0006, close - 0.0006, close, i * HOUR_NS))
    labels = {p.structure for p in detector.labelled if p.structure}
    assert labels, "a drifting oscillation produces structure labels"
    assert labels <= {
        ind.Structure.HIGHER_HIGH,
        ind.Structure.HIGHER_LOW,
        ind.Structure.LOWER_HIGH,
        ind.Structure.LOWER_LOW,
    }


def test_a_monotone_series_has_no_pip_turns():
    """Every point sits on a straight run, so `EDGE` is the right answer and
    not a failure to classify."""
    detector = ind.Pips(count=8, span=120)
    for i in range(150):
        close = 1.1000 + 0.0002 * i
        detector.handle_bar(bar(close, close + 0.0001, close - 0.0001, close, i * HOUR_NS))
    assert detector.points
    assert detector.turns == []


def test_pips_refuses_a_count_with_nothing_to_select():
    with pytest.raises(ValueError, match="nothing to select"):
        ind.Pips(count=3)


# ------------------------------------------------------------------- bjorgum


def _gold(n=900, seed=11):
    import random

    rng = random.Random(seed)
    price, out = 2400.0, []
    for i in range(n):
        price += rng.gauss(0, 1.2) + 2.0 * math.sin(i / 60.0)
        high, low = price + abs(rng.gauss(0, 0.8)), price - abs(rng.gauss(0, 0.8))
        out.append(
            Bar(
                BarType.from_str("XAUUSD.SIM-15-MINUTE-LAST-EXTERNAL"),
                Price(price, 2),
                Price(high, 2),
                Price(low, 2),
                Price(price, 2),
                Quantity(1, 0),
                ts_event=i * 900_000_000_000,
                ts_init=i * 900_000_000_000,
            )
        )
    return out


def test_bjorgum_breaks_at_the_control_rate_on_a_walk():
    """The strongest available check that this matches the measured harness.

    `bjorgum.md` reports the **synthetic control** breaking at 80.5-85% where
    real instruments break at 33.9-37.7%. A Gaussian walk is that control, so a
    break rate in the control's range is the construction reproducing the
    study's own null - and a rate down at the real-market figure would mean
    this had found structure in noise.
    """
    detector = ind.BjorgumLevels()
    for one in _gold():
        detector.handle_bar(one)
    rate = detector.break_rate()
    assert rate is not None
    assert 0.6 <= rate <= 0.95, f"a walk should break near the control's rate, got {rate:.3f}"


def test_the_two_bjorgum_labels_use_different_thresholds():
    """The width-free one is the point: a visit scored at the band's far edge
    lets a wider zone have a further edge, which halved the width effect.

    Asserted on the thresholds rather than on the two rates. The rates *can*
    coincide on a given sample - with the script's four zones a side there are
    few visits - and a test that required them to differ would be testing the
    sample. What has to hold is that the edge threshold moves with the band and
    the ATR one does not.
    """
    narrow = ind.Zone(top=100.5, bottom=99.5, level=100.0, atr=4.0, at=0, when=0.0, resistance=True)
    wide = ind.Zone(top=104.0, bottom=96.0, level=100.0, atr=4.0, at=0, when=0.0, resistance=True)
    # Same level, same ATR, different bands. The ATR break is the same price
    # for both; the edge break is not.
    from till_infinity.indicators.levels import BREAK_ATR

    assert narrow.level == wide.level
    assert narrow.level - BREAK_ATR * narrow.atr == wide.level - BREAK_ATR * wide.atr
    assert narrow.bottom != wide.bottom, "the edge threshold moves with the band"
    # And the width-free touch test ignores the band entirely.
    assert narrow.near(100.9, 100.9) == wide.near(100.9, 100.9)
    assert narrow.holds(100.9, 100.9) != wide.holds(103.0, 103.0)


def test_a_run_of_bars_inside_a_zone_is_one_visit():
    """Price sitting in a level for nine bars is one test of it, not nine."""
    detector = ind.BjorgumLevels()
    for one in _gold():
        detector.handle_bar(one)
    visited = [z for z in detector.zones if z.tested]
    assert visited, "the walk visits its own zones"
    for zone in visited:
        starts = [v.started for v in zone.visits]
        assert len(starts) == len(set(starts)), "two visits started on one bar"
        assert all(
            zone.visits[i + 1].started > zone.visits[i].started for i in range(len(starts) - 1)
        )


def test_an_unresolved_visit_is_not_counted_as_a_hold():
    """A visit whose outcome is not yet known is not a visit that held, and
    recording it as one makes a hold rate a measure of the window running out.

    **The length is load-bearing, and it was wrong.** At 200 bars this
    construction produces one zone and *no* visits at all, so both loops below
    were empty, `break_rate` was None and the guard on it skipped the only
    remaining assertion - the test asserted nothing and passed. 400 is the
    shortest run that leaves a visit still open at the end, which is the
    situation being described, so the counts are asserted before they are
    used rather than left to a conditional.
    """
    detector = ind.BjorgumLevels()
    for one in _gold(n=400):
        detector.handle_bar(one)

    open_visits = [v for z in detector.zones for v in z.visits if v.broke_atr is None]
    assert open_visits, "no unresolved visit, so the claim is untested"
    for visit in open_visits:
        assert visit.broke_edge is None or visit.broke_edge is True

    rate = detector.break_rate()
    counted = [v for z in detector.zones for v in z.visits if v.broke_atr is not None]
    assert rate is not None, "no resolved visit, so there is no rate to check"
    # Over the resolved visits alone, so the open one is in neither half of
    # the fraction - which is what stops the rate drifting towards whatever
    # the window happened to cut off.
    assert rate == pytest.approx(sum(1 for v in counted if v.broke_atr) / len(counted))


def test_bjorgum_features_are_absent_rather_than_zero():
    """A zero in the width column would read as "the zone had no width"."""
    detector = ind.BjorgumLevels()
    for one in _gold():
        detector.handle_bar(one)
    assert detector.features(None) == {}
    zone = detector.zones[0]
    got = detector.features(zone)
    assert set(got) == {
        "bjorgum_width",
        "bjorgum_visits",
        "bjorgum_fresh",
        "bjorgum_flipped",
        "bjorgum_crossings",
        "bjorgum_age",
        "bjorgum_distance_atr",
    }
    assert got["bjorgum_width"] > 0.0


# -------------------------------------------------------------------- levels


@pytest.mark.parametrize("kind", list(ind.Kind))
def test_every_level_estimator_finds_the_same_shelf(kind):
    """The estimator choice changes the zone width, not where the level is."""
    book = ind.Levels(kind=kind)
    for i in range(200):
        close = 1.1000 + 0.0040 * (1 if (i // 11) % 2 else 0) + 0.0003 * math.sin(i / 2.0)
        book.handle_bar(bar(close, close + 0.0005, close - 0.0005, close, i * HOUR_NS))
    assert book.initialized
    assert book.strongest is not None
    assert book.strongest.touches >= 5


def test_the_level_forget_clocks_agree_where_they_should():
    """12 hours and 720 minutes are the same horizon; bars are not, and that
    is the point - only bars ignore a market being shut."""

    def run(forget):
        book = ind.Levels(forget=forget)
        for i in range(200):
            close = 1.1000 + 0.0040 * (1 if (i // 11) % 2 else 0) + 0.0003 * math.sin(i / 2.0)
            book.handle_bar(bar(close, close + 0.0005, close - 0.0005, close, i * HOUR_NS))
        return book.count, book.dropped

    assert run(ind.Forget(12, ind.Clock.HOURS)) == run(ind.Forget(720, ind.Clock.MINUTES))
    assert run(500) == run(ind.Forget(500, ind.Clock.BARS))


def test_a_zero_forget_horizon_is_refused():
    with pytest.raises(ValueError, match="forgets every level immediately"):
        ind.Forget(0, ind.Clock.BARS)


def test_a_forgotten_level_stays_forgotten():
    """`pivots` rescans the window each bar, so a dropped level's own pivots
    would re-fold and resurrect it forever."""
    book = ind.Levels(forget=ind.Forget(6, ind.Clock.BARS), span=240)
    for i in range(40):
        close = 1.1000 + 0.0003 * math.sin(i / 2.0)
        book.handle_bar(bar(close, close + 0.0005, close - 0.0005, close, i * HOUR_NS))
    for i in range(40, 100):
        close = 1.2000 + 0.0003 * math.sin(i / 2.0)
        book.handle_bar(bar(close, close + 0.0005, close - 0.0005, close, i * HOUR_NS))
    assert not [x for x in book.levels if x.at(book.when) < 1.15]


def test_an_event_restarts_the_accumulators_without_wiping_the_detector():
    """The reset/restart trap, caught in a real engine run and pinned here.

    `Cusum.push` zeroes its accumulators when an event fires - *accumulate
    from here*, keeping `last` and `started` because the price series did not
    restart. After `reset` was given Nautilus's meaning (*never seen
    anything*), these two internal call sites still pointed at it, so **every
    event wiped the whole detector**: `has_inputs` and `initialized` went back
    to False and the filter never accumulated past its first event.

    It was invisible in isolation - a single `handle_bar` looks fine - and
    showed up only as `has_inputs=False` after a 120-bar engine run, beside a
    `Trend` on the same bar type reading True. The module docstring warned
    about this exact confusion, which is why the test is here and not the
    warning.
    """
    detector = ind.Cusum()
    stream = [
        bar(
            1.1000 + 0.0002 * i,
            1.1003 + 0.0002 * i,
            1.0997 + 0.0002 * i,
            1.1000 + 0.0002 * i,
            i * HOUR_NS,
        )
        for i in range(120)
    ]
    for one in stream:
        detector.handle_bar(one)

    assert len(detector.events) > 1, "a steady climb must fire more than once"
    assert detector.has_inputs, "an event wiped the detector"
    assert detector.initialized
    assert detector.started, "the price series did not restart"
    assert detector.last > 0.0, "`last` is history and an event does not clear it"

    # And the two meanings stay apart.
    detector.restart()
    assert detector.up == 0.0
    assert detector.started is True
    detector.reset()
    assert detector.started is False
    assert detector.has_inputs is False


# ------------------------------------------------------- the variance ratio


def _series(kind: str, n: int = 400, seed: int = 3) -> list[Bar]:
    """A walk, a walk with drift, or a reverting series, as bars."""
    import random

    rng = random.Random(seed)
    price, out, ts = 1.1000, [], 0
    for _ in range(n):
        step = rng.gauss(0.0, 0.0004)
        if kind == "drift":
            step += 0.00025
        elif kind == "reverting":
            step -= 0.5 * (price - 1.1000)
        price += step
        out.append(bar(price, price + 0.0004, price - 0.0004, price, ts))
        ts += HOUR_NS
    return out


def _vr(kind: str, **kwargs):
    detector = ind.VarianceRatio(window=200, **kwargs)
    for one in _series(kind):
        detector.handle_bar(one)
    return detector


def test_the_variance_ratio_reads_one_on_a_random_walk():
    """**The null is exact, not conventional.** Under a walk the variance of a
    sum is the sum of the variances, so VR = 1 by construction - which is what
    makes this the one trend statistic here that can be tested rather than
    thresholded."""
    detector = _vr("walk")
    assert detector.value == pytest.approx(1.0, abs=0.15), detector.value
    assert abs(detector.z) < 2.0
    assert detector.regime == "walk"


def test_it_finds_reversion_and_says_how_strongly():
    detector = _vr("reverting")
    assert detector.value < 0.6, detector.value
    assert detector.z < -2.0
    assert detector.regime == "reverting"


def test_a_drift_too_small_to_detect_is_reported_as_a_walk():
    """Not a failure - the null doing its job.

    A drift of 0.00025 against a 0.0004 step is real and is *not* detectable
    at this sample size: `z` comes out inside two, so the statistic says it
    cannot tell. An indicator that called it a trend would be claiming evidence
    it does not have, which is the whole reason to prefer a statistic with a
    null over one with a threshold.

    No assertion on the *direction* of the point estimate, and that is
    deliberate: on one seed it came out at 1.11 and on another at 0.98. A test
    that pinned the sign would be pinning the seed.
    """
    detector = _vr("drift")
    assert abs(detector.z) < 2.0, "the evidence does not clear two"
    assert detector.regime == "walk"


def test_a_short_sample_reads_none_rather_than_one():
    """One is the *null*. Returning it for "no data" would make an unwarmed
    indicator look like a confident finding of a random walk."""
    detector = ind.VarianceRatio(window=200)
    for one in _series("walk")[:20]:
        detector.handle_bar(one)
    assert detector.value is None
    assert detector.z is None
    assert detector.regime == "walk", "the honest default, with no claim attached"
    assert not detector.initialized


def test_the_ratio_can_be_swept_over_horizons_within_its_usable_range():
    """Which is how the desk's own measurement was taken: 0.980 falling to
    0.924 *across horizons* on traded closes against 1.000 on an i.i.d.
    control.

    The range is bounded by `q/n`, not by taste. `at` returns None beyond
    `window / VR_LEAST` rather than a biased number, because the residual bias
    is about `q/n` and at 0.1 a pure random walk reads 0.908.
    """
    from till_infinity.indicators.trend import VR_LEAST

    detector = _vr("walk")
    usable = detector.window // VR_LEAST
    got = {q: detector.at(q) for q in (2, 5, usable)}
    assert all(v is not None for v in got.values()), got
    assert all(0.8 < v < 1.25 for v in got.values()), got
    # Beyond it, None rather than a number nobody can trust.
    assert detector.at(usable * 4) is None


def test_a_sweep_beyond_the_usable_range_returns_nothing():
    """**The artefact this guard exists for.** With the naive estimator and a
    `q/n` of 0.1, a 200-observation random walk read 0.440 - strong mean
    reversion, from overlap alone. Lo and MacKinlay's correction took the
    average to 0.908, which is better and still 9% low, so the range is capped
    rather than corrected further.
    """
    detector = _vr("walk")
    assert detector.at(detector.window // 2) is None
    assert detector.at(detector.window) is None


def test_a_horizon_of_one_is_refused_because_it_is_one_by_construction():
    with pytest.raises(ValueError, match="1 by construction"):
        ind.VarianceRatio(horizon=1)


def test_a_window_too_short_for_its_horizon_is_refused():
    """The bias is measured, so the guard quotes it.

    A `q/n` of 0.25 - which the first version of this guard allowed - reads a
    pure random walk as strongly mean reverting.
    """
    with pytest.raises(ValueError, match="residual bias is about q/n"):
        ind.VarianceRatio(horizon=20, window=40)
    with pytest.raises(ValueError, match="residual bias is about q/n"):
        ind.VarianceRatio(horizon=20, window=200)
    # And the measured bound is reachable.
    assert ind.VarianceRatio(horizon=20, window=400).horizon == 20


def test_the_ratio_is_scale_free():
    """A ratio of variances of the same series, so any common scaling cancels -
    which is what lets it compare a currency with gold without a unit."""
    small = ind.VarianceRatio(window=200)
    large = ind.VarianceRatio(window=200)
    for one in _series("reverting"):
        small.handle_bar(one)
    for one in _series("reverting"):
        # The same path at a thousand times the price.
        large.handle_bar(
            bar(
                float(one.open) * 1000,
                float(one.high) * 1000,
                float(one.low) * 1000,
                float(one.close) * 1000,
                one.ts_event,
            )
        )
    assert small.value == pytest.approx(large.value, rel=1e-6)


def test_efficiency_and_the_variance_ratio_are_kept_apart_on_purpose():
    """One is a readable heuristic with no null; the other is a statistic with
    one. `efficiency` names ours rather than the framework's, which reports
    `(period-1)/period` on a straight line."""
    assert ind.BAR_DETECTORS["efficiency"][0] is ind.Trend
    assert ind.BAR_DETECTORS["variance_ratio"][0] is ind.VarianceRatio
    assert "EfficiencyRatio" not in str(ind.FRAMEWORK)
    assert "SpreadAnalyzer" not in str(ind.FRAMEWORK)
    # And ours is reachable under the name the broken one has.
    assert ind.TICK_DETECTORS["spread"][0] is ind.RollingSpread
