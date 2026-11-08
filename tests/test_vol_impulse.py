"""`VI_M15_imp_H4sq`, and the two ways it could read the future.

This rule reads two clocks and a fitted model, and each of the three can leak
the future without raising anything:

* **the forecast could see its own bar.** `|r| / sigma` with `sigma` fitted on
  the bar being judged makes every bar an impulse of the same size and the
  trigger meaningless; shifted the wrong way it reads better, not worse.
* **the squeeze could read the bin the impulse is in.** A four-hour bin that
  included the impulse would be ranked with it, and a bin containing a 3-sigma
  bar is not a squeeze - so the gate would admit exactly the events it should
  refuse, and the rule would look like it had found something.
* **the HAR could be refitted.** The coefficients are frozen before 2026-02 by
  specification; a fit over the scored period is look-ahead with a likelihood
  attached. `test_the_frozen_har_reproduces_a_stored_forecast` is what makes an
  edited coefficient fail here rather than in a tally.

The first half of this file holds `Fold` to the property that shuts the first
two: **what the fold said at bar `n` does not change when bars after `n`
arrive**. The engine half runs the shipped composition end to end with the
squeeze wide open, because a squeeze that needs 750 four-hour bins is 12,000
bars and no test suite can afford one - which is why the gate itself is tested
in the fold, where it is exact and free.
"""

from __future__ import annotations

import math
from typing import ClassVar

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.strategies import leaves
from till_infinity.strategies.entries import EdgeEntry, EdgeEntryConfig
from till_infinity.strategies.exits import ManagedExit
from till_infinity.strategies.volimpulse import (
    HAR_LAGS,
    HOLD_BARS,
    IMPULSE_MULT,
    SLOW_SECONDS,
    SQUEEZE_ATR,
    SQUEEZE_BINS,
    SQUEEZE_SHARE,
    SQUEEZE_WINDOW,
    Fold,
    Har,
    VolImpulse,
    VolImpulseEdge,
    VolImpulseProfile,
)

INSTRUMENT = TestInstrumentProvider.default_fx_ccy("XAU/USD")
VENUE = INSTRUMENT.id.venue
DIGITS = INSTRUMENT.price_precision
SEC = 1_000_000_000
MINUTE = 60 * SEC
#: Fifteen one-minute bars to an M15 bar.
PER_WINDOW = 15
WICK = 0.01

#: A HAR with one component and no intercept, so `sigma` is exactly the mean
#: `|r|` over the two bars before the one being judged. A test whose
#: expectation needs three rolling windows and a smearing factor to state is a
#: test of arithmetic nobody can check by eye.
PLAIN = Har(const=0.0, weights=(1.0,), scale=1.0, lags=(2,), until="test")


def folded(
    closes: list[float],
    *,
    har: Har = PLAIN,
    step: int = SLOW_SECONDS,
    wick: float = 0.0,
    **kwargs: object,
) -> tuple[Fold, list]:
    """One bar per close, and every event the fold produced.

    `step` defaults to a whole four-hour bin per bar, so a sequence a test can
    read covers the bin machinery; `test_several_bars_share_one_four_hour_bin`
    is what stops that shortcut hiding the binning itself.
    """
    fold = Fold(har=har, **kwargs)  # type: ignore[arg-type]
    events = []
    for index, close in enumerate(closes):
        found = fold.update(index * step, close + wick, close - wick, close)
        if found is not None:
            events.append(found)
    return fold, events


def quiet(n: int, start: float = 100.0, drift: float = 0.01) -> list[float]:
    """`n` closes that alternate by `drift`, so every return is the same size.

    Alternating rather than rising: a monotone ramp makes the mean `|r|` and
    the four-day range the same quantity, so a squeeze and an impulse could not
    be planted independently of each other.
    """
    return [start + (drift if index % 2 else 0.0) for index in range(n)]


# -------------------------------------------------------------------- the fold


def test_a_forecast_never_sees_the_bar_it_is_judging():
    """`sigma` is built from bars before the one being scored.

    Planted rather than read off the code: the same prefix is folded twice with
    a different final bar, and the impulse ratio of that bar has to be the
    ratio of its own move to **one** forecast. A `sigma` that included the bar
    would grow with it and the two ratios would be nearly equal, which is the
    shape of the bug - the trigger stops meaning anything and nothing raises.
    """
    prefix = quiet(12)
    small, large = 100.02, 100.40
    _, one = folded([*prefix, small], share=1.0, window=2, bins=1, atr_bins=1)
    _, two = folded([*prefix, large], share=1.0, window=2, bins=1, atr_bins=1)
    assert not one, "a bar the size of its neighbours is not an impulse"
    assert len(two) == 1, "a twenty-fold bar is"
    # The same denominator for both: the forecast is a function of the prefix.
    moved = abs(math.log(large) - math.log(prefix[-1]))
    assert two[0].impulse == pytest.approx(moved / two[0].sigma)
    # `PLAIN` is a two-bar mean of `|r|` with no intercept, so the forecast is
    # a number this test can state rather than one it reads back.
    assert two[0].sigma == pytest.approx(
        (abs(math.log(prefix[-1] / prefix[-2])) + abs(math.log(prefix[-2] / prefix[-3]))) / 2.0
    )


def test_every_prefix_produces_the_events_the_full_series_produced():
    """The causality property, and the one test a fold that peeked would fail.

    Variant `a` of this desk's BOS rule read swing timestamps dated to the bar
    that printed rather than the bar that confirmed, and it did not show up as
    an error - it showed up as a better number. The same mistake here is a
    squeeze ranked with the impulse inside it.
    """
    closes = [*quiet(40), 100.5, *quiet(10, 100.5), 99.6, *quiet(10, 99.6)]
    _, whole = folded(closes, window=6, bins=2, atr_bins=2, share=1.0)
    for cut in range(5, len(closes)):
        _, prefix = folded(closes[:cut], window=6, bins=2, atr_bins=2, share=1.0)
        assert [e.at for e in prefix] == [e.at for e in whole if e.at <= cut], cut
        for early, late in zip(prefix, whole, strict=False):
            assert early == late, f"bar {early.at} changed when bar {cut} arrived"


def test_the_bin_an_impulse_is_inside_cannot_rank_the_squeeze_that_admitted_it():
    """The second leak, planted: a 3-sigma bar inside the newest bin.

    With several bars to a bin the impulse's own bar is in the bin still being
    filled, and a fold that ranked the open bin would be ranking a bin that
    contains a 3-sigma move - so the squeeze would be widest exactly where it
    is supposed to refuse. The fold's `stats` must not move on the bar that
    fires.
    """
    closes = [*quiet(200, drift=0.001), 100.4]
    fold, events = folded(closes, step=SLOW_SECONDS // 8, window=4, bins=2, atr_bins=2, share=1.0)
    assert len(events) == 1, events
    # The newest finished bin's statistic is the one the event read, and the
    # bar that fired is not in it: refolding without that bar gives the same
    # statistic.
    quietly, _ = folded(
        closes[:-1], step=SLOW_SECONDS // 8, window=4, bins=2, atr_bins=2, share=1.0
    )
    assert list(fold.stats) == list(quietly.stats)
    assert events[0].squeeze == pytest.approx(quietly.stats[-1])


def test_several_bars_share_one_four_hour_bin():
    """The bin is a calendar bin, so sixteen M15 bars make one of it.

    Every other fold test steps a whole bin per bar, which is a shortcut that
    would hide a fold counting bars instead of cutting on the clock.
    """
    fold, _ = folded(quiet(96), step=900, window=20, bins=1, atr_bins=1, share=1.0)
    # 96 bars of 15 minutes is 24 hours: six bins, five of them finished.
    assert len(fold.slow) <= 6
    assert fold.counts["bars"] == 96
    assert len(fold.stats) == 4, "six bins, five finished, two needed before the first statistic"


def test_a_session_gap_is_a_short_bin_and_not_a_fabricated_bar():
    """A hole in the feed skips bins rather than inventing returns.

    The slow leg is cut on the clock, so a weekend is bins that never existed.
    A leg built by differencing aligned closes would turn the gap into one
    enormous four-hour return and rank a squeeze off it.
    """
    closes = quiet(12)
    fold = Fold(har=PLAIN, window=20, bins=1, atr_bins=1, share=1.0)
    stamps = [index * SLOW_SECONDS for index in range(6)]
    stamps += [stamps[-1] + 48 * 3_600 + index * SLOW_SECONDS for index in range(6)]
    for stamp, close in zip(stamps, closes, strict=True):
        fold.update(stamp, close, close, close)
    assert len(fold.slow) <= fold.slow.maxlen
    # Eleven bin changes over twelve bars, whatever the size of the hole.
    assert len(fold.stats) == 11 - max(fold.bins, fold.atr_bins + 1) + 1


def test_an_impulse_under_the_multiple_does_not_fire_and_one_over_it_does():
    """The trigger, with the control the repo's test rules ask for.

    A gate with no control is indistinguishable from a gate that refuses
    everything, which is why both halves are one test.
    """
    prefix = quiet(12, drift=0.01)
    unit = abs(math.log(prefix[-1] / prefix[-2]))
    for multiple, fires in ((IMPULSE_MULT * 0.9, False), (IMPULSE_MULT * 1.1, True)):
        close = prefix[-1] * math.exp(multiple * unit)
        _, events = folded(
            [*prefix, close], window=2, bins=1, atr_bins=1, share=1.0, mult=IMPULSE_MULT
        )
        assert bool(events) is fires, f"{multiple:.2f}x should fire={fires}"


def test_the_squeeze_refuses_an_expansion_and_the_arm_without_it_admits_one():
    """`require_squeeze`, both ways, which is the rule's central claim as code.

    The null arm that decides whether the slow leg contributes anything is a
    field on this fold rather than a copy in a harness, so this test is also
    what proves the arm and the rule are the same detector. Without the second
    half, "the squeeze refuses" would be indistinguishable from "the fold
    cannot fire at all".
    """
    # Forty chopping bins and then four that step the same way: the four-bin
    # range is one bin's worth of travel in the chop and three in the trend,
    # against the same ATR, so the newest statistic is the window's maximum -
    # the opposite of a squeeze - and the impulse arrives after it.
    closes = [*quiet(40), 100.02, 100.03, 100.04, 100.05]
    closes.append(100.05 * math.exp(0.001))
    gated, refused = folded(closes, window=10, bins=4, atr_bins=4, share=SQUEEZE_SHARE)
    opened, admitted = folded(
        closes, window=10, bins=4, atr_bins=4, share=SQUEEZE_SHARE, require_squeeze=False
    )
    assert not refused, "an expansion is not a squeeze"
    assert gated.counts["no-squeeze"] >= 1, gated.counts
    assert admitted, "the impulse alone has to be admitted, or the arm measures nothing"
    assert opened.counts["no-squeeze"] == 0


def test_the_raw_range_and_the_atr_adjusted_readings_are_different_gates():
    """The specification's ambiguity, made visible rather than argued about.

    "The range of the last 24 four-hour bars ... after adjusting for normal
    ATR" admits a denominator and no denominator, and this shows they rank
    differently - which is why the measurement carries both as arms and why
    `SQUEEZE_ATR` says which one ships.
    """
    closes = [100.0 + math.sin(index / 3.0) * (1.0 + index / 20.0) for index in range(60)]
    adjusted, _ = folded(closes, window=10, bins=2, atr_bins=4, share=1.0)
    raw, _ = folded(closes, window=10, bins=2, atr_bins=4, share=1.0, raw_range=True)
    assert list(adjusted.stats) != list(raw.stats)
    order = [sorted(f.stats).index(f.stats[-1]) for f in (adjusted, raw)]
    assert order[0] != order[1], "the two readings put the newest bin in the same place"


def test_a_cold_window_is_counted_apart_from_a_quiet_market():
    """The branch counters, because a zero is a reading and can be of nothing.

    A single `None` covering "no bins yet", "no model yet" and "nothing fired"
    is a scope bug nobody can tell from a quiet market - three defects on this
    desk read as *the strategy declined to trade*. The denominator of a firing
    rate is `bars` minus the cold branches, and it has to be recoverable.
    """
    fold, events = folded(quiet(8), window=50, bins=1, atr_bins=1)
    assert not events
    assert fold.counts["bars"] == 8
    assert fold.counts["cold-return"] == 1, "the first bar has no return"
    assert fold.counts["cold-har"] == 2, "two bars before the two-bar component fills"
    assert fold.counts["cold-squeeze"] == 5, fold.counts
    assert fold.counts["no-impulse"] == 0, "nothing was judged, so nothing was refused"


def test_a_fold_with_no_model_can_never_fire_and_says_which_branch():
    """A feed absent from `HAR` folds and refuses, rather than inventing one.

    Absent is not zero: a rule with no frozen model for its feed must read as
    *no model*, not as a market that never moved.
    """
    fold, events = folded([*quiet(40), 140.0], har=None, window=2, bins=1, atr_bins=1)
    assert not events
    assert fold.counts["cold-har"] == 40, fold.counts


def test_the_frozen_har_reproduces_a_stored_forecast():
    """The arithmetic of the frozen model, pinned against numbers by hand.

    This is the test an edited coefficient has to fail. The smearing factor is
    part of it deliberately: a HAR fitted on `log|r|` and exponentiated without
    one forecasts the geometric mean, which runs low, and a trigger divided by
    a forecast that runs low fires too often - a silent change to the rule's
    event rate with nothing in the diff that looks like one.
    """
    har = Har(const=-0.5, weights=(0.5, 0.3, 0.2), scale=1.1, lags=(2, 4, 8), until="2026-02-01")
    parts = (0.001, 0.002, 0.004)
    by_hand = 1.1 * math.exp(
        -0.5 + 0.5 * math.log(0.001) + 0.3 * math.log(0.002) + 0.2 * math.log(0.004)
    )
    assert har.forecast(parts) == pytest.approx(by_hand)
    assert har.forecast((0.001, 0.0, 0.004)) == 0.0, "a zero component has no logarithm"
    assert har.forecast((0.001, 0.002)) == 0.0, "the wrong number of components is not a forecast"


def test_a_har_whose_weights_do_not_match_its_lags_is_refused():
    """Refused at construction, not silently truncated.

    A weight dropped off a pasted coefficient row would otherwise reweight the
    model and keep running, and the only symptom would be a different firing
    rate on a feed nobody was watching.
    """
    with pytest.raises(ValueError, match="needs 3 weights"):
        Har(const=0.0, weights=(1.0, 1.0), scale=1.0, lags=(4, 96, 480))
    with pytest.raises(ValueError, match="multiplier"):
        Har(const=0.0, weights=(1.0,), scale=0.0, lags=(4,))


def test_a_degenerate_fold_is_refused_rather_than_silently_empty():
    """A window or a trigger of zero is a configuration error, not a quiet desk."""
    for kwargs, why in (
        ({"window": 0}, "squeeze needs bins"),
        ({"bins": 0}, "squeeze needs bins"),
        ({"share": 0.0}, "quantile"),
        ({"mult": 0.0}, "multiple of the forecast"),
    ):
        with pytest.raises(ValueError, match=why):
            Fold(har=PLAIN, **kwargs)  # type: ignore[arg-type]


def test_the_shipped_rule_runs_the_numbers_its_name_states():
    """The constants, pinned where a tiny profile cannot hide a changed one.

    Every engine test below shrinks the squeeze so a sequence fits in a suite,
    and this is what stops that shrinking from being how the shipped rule got
    smaller.
    """
    profile = VolImpulseProfile
    assert (SQUEEZE_BINS, SQUEEZE_WINDOW, SQUEEZE_SHARE) == (24, 750, 0.20)
    assert (SQUEEZE_ATR, IMPULSE_MULT, HOLD_BARS) == (14, 3.0, 16)
    assert HAR_LAGS == (4, 96, 480), "one hour, one day and one week at 15 minutes"
    assert SLOW_SECONDS == 4 * 3_600
    assert profile.interval == "15m"
    assert profile.hold_signal_bars == 16, "sixteen M15 bars is the four-hour hold"
    assert profile.no_fill_hours == (19, 20, 21, 22), "19:00-23:00 UTC, half open"
    assert profile.protective_stop is False, "the rule exits on the clock alone"
    assert profile.require_squeeze is True, "the arm is off in the shipped rule"
    assert profile.feeds == frozenset({"eurusd", "usdjpy", "gbpusd", "usdcad", "xauusd"})
    # The warm-up is an operational fact and not a knob: 750 four-hour bins is
    # 12,000 M15 bars, so a desk asking for fewer could never rank anything.
    assert profile.warm_bars_request >= SQUEEZE_WINDOW * 16


def test_the_registry_lists_the_rule_on_the_edge_entry_and_nowhere_else():
    """Registered, and refused by name on the two entries the rule does not say.

    `TRADING_STRATEGIES=vol-impulse` has to resolve or the rule cannot be
    measured at all; a desk set silently smaller than the one asked for is the
    shape of bug the registry exists for.
    """
    assert leaves.leaf("vol-impulse", "edge") is VolImpulseEdge
    assert "vol-impulse" in leaves.RULES
    for entry in ("resting", "arrival"):
        with pytest.raises(ValueError, match="no 'vol-impulse' desk"):
            leaves.leaf("vol-impulse", entry)


# ------------------------------------------------------------------ the engine


class TinyProfile(VolImpulseProfile):
    """The shipped rule with the squeeze wide open, so a feed fits in a suite.

    `share = 1.0` admits every state. **That is not the rule**, and it is the
    right shrinking for these tests: the squeeze needs 750 four-hour bins -
    12,000 M15 bars - and what the engine half is for is the order, the fill,
    the clock, the cut-off and the cost. The gate itself is exercised in the
    fold tests above, where it is exact and free, and
    `test_the_shipped_rule_runs_the_numbers_its_name_states` is what stops this
    class being how the shipped rule got smaller.
    """

    squeeze_window: ClassVar[int] = 2
    squeeze_bins: ClassVar[int] = 1
    squeeze_atr: ClassVar[int] = 1
    squeeze_share: ClassVar[float] = 1.0
    #: No warm request: a backtest with no catalogue answers one with nothing,
    #: and `test_the_shipped_rule_runs_the_numbers_its_name_states` pins the
    #: number the live desk asks for.
    warm_bars_request: ClassVar[int] = 0


class Tiny(VolImpulse):
    profile: ClassVar[TinyProfile] = TinyProfile.__new__(TinyProfile)


class TinyEdge(Tiny, ManagedExit, EdgeEntry):
    """`VolImpulseEdge` with the squeeze open. Everything else is the rule."""


class ProtectedProfile(TinyProfile):
    """`TinyProfile` that does send a stop - the control for the flag."""

    protective_stop: ClassVar[bool] = True


class ProtectedEdge(Tiny, ManagedExit, EdgeEntry):
    profile: ClassVar[ProtectedProfile] = ProtectedProfile.__new__(ProtectedProfile)


#: The M15 bar the impulse lands on. Late enough that three four-hour bins have
#: finished - 48 M15 bars - and early enough that sixteen more bars fit after
#: it, which is what lets the clock close the trade inside the feed.
AT = 70


#: The alternating step the quiet bars take, in price. Large enough that a
#: round trip of 0.02 is inside the rule's own cost gate at a gold-scale price:
#: 1R is `3 * sigma * price` and `sigma` here is `log(1 + DRIFT / 100)`, so a
#: smaller step would make every engine test a cost refusal - which is what the
#: first run of this file was.
DRIFT = 0.1


def planted(at: int = AT, jump: float = 0.005, after: int = 24) -> list[float]:
    """Quiet alternating bars, one impulse, then quiet bars around the new level.

    The tail alternates around the price the jump left rather than around the
    old one, and it steps on its **first** bar: a tail that repeated the
    impulse's close would make the fill price and the signal price the same
    number, and `test_the_entry_fills_at_the_quote_after_the_m15_close...`
    would pass without the fill being a minute late.
    """
    closes = quiet(at, drift=DRIFT)
    level = closes[-1] * math.exp(jump)
    tail = [level + (0.0 if index % 2 else DRIFT) for index in range(after)]
    return [*closes, level, *tail]


def feed(mids: list[float], spread: float, *, start_hour: int = 0) -> list[object]:
    """The M1 bars and quotes that aggregate to `mids` on the M15 clock.

    **The quote for a minute is stamped at its open and the bar at its close.**
    That ordering is step 3: the M15 bar closes, the rule decides, and the next
    thing the venue sees is the quote opening the following minute - so a market
    order fills there, at a price that did not exist when the decision was made.
    Lifted from `tests/test_structure_bos.py`, which needs the same geometry for
    the same reason.
    """
    bar_type = BarType.from_str(f"{INSTRUMENT.id}-1-MINUTE-LAST-EXTERNAL")
    half = spread / 2.0
    size = Quantity(1_000_000, 0)
    data: list[object] = []
    for index, mid in enumerate(mids):
        for minute in range(PER_WINDOW):
            ts = start_hour * 3_600 * SEC + (index * PER_WINDOW + minute) * MINUTE
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
            reach = WICK if minute == 0 else 0.0
            data.append(
                Bar(
                    bar_type=bar_type,
                    open=Price(mid, DIGITS),
                    high=Price(mid + reach, DIGITS),
                    low=Price(mid - reach, DIGITS),
                    close=Price(mid, DIGITS),
                    volume=Quantity(1, 0),
                    ts_event=ts + MINUTE - 1,
                    ts_init=ts + MINUTE - 1,
                )
            )
    return data


def composite() -> BarType:
    """M15 aggregated from the M1 bars inside the engine.

    The rule has two clocks - M15 for the signal, M1 for the entry and the exit
    - and a composite bar type is how one data stream serves both.
    """
    return BarType.from_str(f"{INSTRUMENT.id}-15-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL")


def run(
    mids: list[float] | None = None,
    spread: float = 0.02,
    *,
    start_hour: int = 0,
    protected: bool = False,
    model: Har | None = PLAIN,
) -> TinyEdge:
    """One engine, one desk, the planted feed. Nothing is driven by hand.

    `model` is written into the module's own `HAR` table and removed again, so
    what the test exercises is the production lookup - a desk whose feed has no
    frozen model is a real state and `test_a_feed_with_no_frozen_model...` is
    the case that reads it.
    """
    mids = planted() if mids is None else mids
    import till_infinity.strategies.volimpulse as module

    previous = module.HAR.get("xauusd")
    if model is None:
        module.HAR.pop("xauusd", None)
    else:
        module.HAR["xauusd"] = model
    try:
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
            # **Quotes alone fill.** With bar execution on, the engine would
            # also match against the bar the signal was read from, at no spread
            # at all - a fill nobody could get.
            bar_execution=False,
        )
        engine.add_instrument(INSTRUMENT)
        engine.add_data(feed(mids, spread, start_hour=start_hour))
        built = ProtectedEdge if protected else TinyEdge
        strategy = built(EdgeEntryConfig(instrument_id=INSTRUMENT.id, bar_type=composite()))
        engine.add_strategy(strategy)
        engine.run()
        return strategy
    finally:
        if previous is None:
            module.HAR.pop("xauusd", None)
        else:
            module.HAR["xauusd"] = previous


def orders_of(strategy: TinyEdge) -> list:
    return list(strategy.cache.orders(strategy_id=strategy.id))


def test_an_impulse_reaches_the_venue_as_one_order_with_no_stop_and_no_target():
    """Step 4 at the venue: the exit is a clock, so nothing defends the trade.

    The whole point of `Profile.protective_stop`. Without it the only way to
    express "no stop" was `Intent.stop = 0`, which `sizes.size` refuses as
    unsized - so the rule would have been deployable only with a stop it does
    not have, and a stop at 1R both changes the hit rate and improves the
    number. One entry order and nothing else is the assertion that catches a
    protective leg creeping back in.
    """
    strategy = run()
    orders = orders_of(strategy)
    assert strategy.fold.counts["fired"] == 1, strategy.fold.counts
    assert strategy.taken == 1, strategy.passed_over
    guards = [o for o in orders if getattr(o, "trigger_price", None) is not None]
    assert not guards, "the rule exits on the clock, so no stop may reach the venue"
    # Two market orders and no third: the entry, and the clock closing it.
    assert [o.side for o in orders] == [OrderSide.BUY, OrderSide.SELL], orders


def test_the_same_rule_with_a_protective_stop_sends_two_orders():
    """The control for the flag, which a one-sided test cannot give.

    "It sends no stop" is indistinguishable from "it sends no orders" without
    this, and a flag read off the wrong object would look identical.
    """
    strategy = run(protected=True)
    orders = orders_of(strategy)
    guards = [o for o in orders if getattr(o, "trigger_price", None) is not None]
    assert strategy.taken == 1, strategy.passed_over
    assert len(guards) == 1, orders
    assert guards[0].side is OrderSide.SELL, "a stop closes, so it is the other side"


def test_the_entry_fills_at_the_quote_after_the_m15_close_and_not_at_it():
    """Step 3: the fill is the first minute after the signal bar closed.

    A fill at the signal bar's own close is the generosity a bar-execution
    backtest hands out for free, and on this rule it would be the impulse bar's
    close - the single most favourable price in the series.
    """
    mids = planted()
    spread = 0.02
    strategy = run(mids, spread)
    entry = next(o for o in orders_of(strategy) if getattr(o, "trigger_price", None) is None)
    filled = float(entry.avg_px)
    signal = mids[AT]
    following = mids[AT + 1]
    assert filled == pytest.approx(following + spread / 2.0, abs=10**-DIGITS)
    assert filled != pytest.approx(signal + spread / 2.0, abs=10**-DIGITS), (
        "the fill landed on the signal bar's own close"
    )


def test_the_trade_comes_off_sixteen_bars_later_on_the_clock():
    """Step 4, and the only thing in this rule that closes a position."""
    strategy = run()
    assert len(strategy.closed) == 1, strategy.closed
    record = strategy.closed[0]
    assert record.how == "clock", "nothing but the clock may close this rule's trade"
    assert strategy.passed_over.get("(exit):closed") == 1, strategy.passed_over
    # Opened on the bar after the signal and closed sixteen signal bars later.
    assert not strategy.opened_on, "the clock has to forget the position it closed"


def test_one_r_is_the_trigger_distance_and_not_a_stop_this_module_chose():
    """Step 6: 1R is `3.0 * sigma` at the decision quote, stated by hand.

    Recorded on the intent rather than derived afterwards, because every later
    question about this rule's R begins with that derivation and it can be got
    wrong quietly - and because the sizing distance and the scoring unit being
    the same number is what makes `money / risk_money` R in the rule's own unit
    rather than in a stop's.

    The expectation is built from the planted feed: `PLAIN` is a two-bar mean of
    `|r|`, the two bars before the impulse both move by `log(1.0001)`, and the
    quote the decision reads is the one stamped inside the signal bar's last
    minute - *not* the one the fill lands on, which is a minute later.
    """
    mids = planted()
    spread = 0.02
    strategy = run(mids, spread)
    record = strategy.closed[0]
    sigma = abs(math.log(mids[AT - 1] / mids[AT - 2]))
    decided_at = mids[AT] + spread / 2.0
    assert record.risk_px == pytest.approx(IMPULSE_MULT * sigma * decided_at, rel=1e-3)
    assert record.risk_money > 0.0, "an unsized intent cannot be scored in R"
    assert record.spread_px == pytest.approx(spread, abs=10**-DIGITS)
    # Cost in R is the spread over the trigger and nothing else - the number
    # `vol-gate.md` makes the first thing to look at on a 15-minute book.
    assert record.spread_px / record.risk_px == pytest.approx(
        spread / (IMPULSE_MULT * sigma * decided_at), rel=1e-3
    )


def test_no_fill_is_taken_in_the_cut_off_hours_and_one_is_taken_outside_them():
    """The entry cut, judged on the signal bar's close stamp.

    Both halves in one test: a cut that refused every hour would read the same
    as a rule that never fires.
    """
    outside = run(start_hour=0)
    inside = run(start_hour=2)
    assert outside.taken == 1, outside.passed_over
    assert inside.taken == 0, inside.passed_over
    assert inside.fold.counts["fired"] == 1, "the impulse still has to be counted"
    assert inside.passed_over.get("vol-impulse:cut-off") == 1, inside.passed_over


def test_a_round_trip_over_the_cost_limit_is_refused_and_a_tighter_one_is_not():
    """The one cost gate, charged on the **quoted** spread.

    Nothing here reads the per-bar `spread` column: it is zero on 7-35% of bars
    on this feed and its median runs three to eight times below the terminal's
    quote, and `impulse-vol.md` records that every direction cell in that study
    is profitable at the column's number and almost none at the quote's.
    """
    cheap = run(spread=0.02)
    dear = run(spread=1.0)
    assert cheap.taken == 1, cheap.passed_over
    assert dear.taken == 0, dear.passed_over
    assert dear.passed_over.get("vol-impulse:spread_risk") == 1, dear.passed_over


def test_a_feed_with_no_frozen_model_fires_nothing_and_says_which_branch():
    """A desk on a feed absent from `HAR` is inert, and the counter says why.

    On 2026-11-07 twenty-six of thirty-two desks on this node were inert by
    construction and nothing said so. A rule with no model for its feed must
    read as *no model* rather than as a quiet market.
    """
    strategy = run(model=None)
    assert strategy.taken == 0
    assert strategy.fold.counts["fired"] == 0
    assert strategy.fold.counts["cold-har"] == strategy.fold.counts["bars"] - 1


def test_the_rule_declines_a_reading_that_is_not_its_own():
    """`PROPOSALS` is one topic, so a statespace reading reaches this desk too.

    Not a refusal: it was never this rule's to decline, and counting it as one
    would make a busy bus read as a rule refusing trades.
    """
    strategy = run()
    assert strategy.wants({"shape": "vol-impulse", "feed": "xauusd"}) is True
    assert strategy.wants({"shape": "statespace", "feed": "xauusd"}) is False
    assert strategy.wants({"shape": "vol-impulse", "feed": "btcusd"}) is False


def test_the_shipped_models_cover_the_five_markets_and_forecast_a_live_scale():
    """The frozen table, pinned on what a fit cannot be allowed to drift into.

    Not the coefficients themselves - those are a measurement and
    `research/docs/vol-impulse-trade.md` holds them - but the three things an
    edited or re-pasted row could get wrong without raising: a feed going
    missing, a smearing factor dropped (which makes the forecast the geometric
    mean of `|r|`, so a 3.0 trigger becomes an effective 1.9), and a forecast off
    by an order of magnitude, which would move the firing rate without moving
    anything a reader would look at.
    """
    from till_infinity.strategies.volimpulse import FEEDS, HAR

    assert set(FEEDS) == {"eurusd", "usdjpy", "gbpusd", "usdcad", "xauusd"}
    assert set(HAR) == set(FEEDS), "the allowlist and the coefficient table disagree"
    for feed, har in HAR.items():
        assert har.lags == HAR_LAGS, feed
        assert har.until == "2026-02-01", f"{feed} was not frozen on the rule's own date"
        # The Jensen correction, which is part of the model: a fit in logs
        # exponentiates to a forecast that runs low, and 1.0 would mean it was
        # dropped on the way in.
        assert 1.3 < har.scale < 2.0, f"{feed} scale {har.scale}"
        # A 15-minute mean absolute return on these markets is 2 to 10 basis
        # points. Fed a 3bp component at every scale the forecast has to land
        # in that decade - two orders of magnitude is what a units slip looks
        # like, and it would change the event rate and nothing else.
        got = har.forecast((3e-4,) * len(HAR_LAGS))
        assert 5e-5 < got < 2e-3, f"{feed} forecasts {got:.3g} for a 3bp state"
