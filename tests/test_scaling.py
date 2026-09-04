"""Four ways to size a trade by something other than a fixed fraction.

Every one returns a multiplier and **none can enlarge a position**. That is the
property worth testing hardest: a sizing model that can size up is one that can
turn a measurement error into a margin call, and every input here rests on a
few hundred observations.
"""

from __future__ import annotations

import pytest

from till_infinity.trading import scaling
from till_infinity.trading.models import Side


def held(feed, side=Side.BUY):
    """One open trade, as `crowding` wants it: the feed and the side's sign."""
    return (feed, side.sign)


# ------------------------------------------------------------------ crowding


def test_a_shared_leg_reduces_the_second_position():
    """Long EURUSD and long GBPUSD is one dollar trade in two tickets - they
    will be right together and wrong together."""
    assert scaling.crowding("gbpusd", [held("eurusd")], 0.5) == pytest.approx(0.5)


def test_it_compounds_rather_than_adding():
    """Three positions all short the dollar are not three-halves of one trade,
    they are closer to three of it."""
    book = [held("eurusd"), held("audusd")]
    assert scaling.crowding("gbpusd", book, 0.5) == pytest.approx(0.25)


def test_an_unshared_leg_is_untouched():
    assert scaling.crowding("eurusd", [held("usdjpy", Side.BUY)], 0.5) == 1.0


def test_an_empty_book_changes_nothing():
    assert scaling.crowding("eurusd", [], 0.5) == 1.0


def test_it_is_off_at_zero_and_at_one():
    assert scaling.crowding("gbpusd", [held("eurusd")], 0.0) == 1.0
    assert scaling.crowding("gbpusd", [held("eurusd")], 1.0) == 1.0


def test_an_unmapped_instrument_is_not_penalised():
    """A feed with no exposure leg is unmeasured rather than uncrowded, and
    guessing either way would be inventing a number."""
    assert scaling.crowding("not_a_thing", [held("eurusd")], 0.5) == 1.0


# ---------------------------------------------------------------- volatility


def test_twice_the_volatility_is_half_the_size():
    assert scaling.by_volatility(20.0, 10.0) == pytest.approx(0.5)


def test_a_quiet_instrument_does_not_get_a_bigger_position():
    """Sizing up into calm is how a book discovers the calm was the beginning
    of something. The stop already widens with volatility, so the money at risk
    is constant either way."""
    assert scaling.by_volatility(2.0, 10.0) == 1.0


def test_it_is_off_without_a_target():
    assert scaling.by_volatility(50.0, 0.0) == 1.0


# ---------------------------------------------------------------------- edge


def test_full_size_at_the_full_edge():
    assert scaling.by_edge(0.9, 0.9) == pytest.approx(1.0)


def test_half_the_edge_is_half_the_size():
    assert scaling.by_edge(0.45, 0.9) == pytest.approx(0.5)


def test_a_measured_loss_falls_to_the_floor_rather_than_zero():
    """Refusing is `paying.md`'s job, not a sizing model's - usdcnh at -4.663v
    should be refused by the instrument list, not silently sized to nothing."""
    assert scaling.by_edge(-4.663, 0.9) == scaling.FLOOR


def test_an_unmeasured_instrument_is_not_a_measured_loss():
    assert scaling.by_edge(None, 0.9) == 1.0


def test_a_huge_edge_is_still_capped():
    """Linear and capped is the conservative end of the Kelly family. Full
    Kelly on an edge estimated from fifty touches is a way to be wiped out by
    an estimation error rather than by a market."""
    assert scaling.by_edge(50.0, 0.9) == 1.0


# ------------------------------------------------------------------ drawdown


def test_no_drawdown_is_full_size():
    assert scaling.by_drawdown(10_000.0, 10_000.0, 0.2) == 1.0
    assert scaling.by_drawdown(10_000.0, 11_000.0, 0.2) == 1.0


def test_it_tapers_as_the_drawdown_deepens():
    shallow = scaling.by_drawdown(10_000.0, 9_800.0, 0.2)
    deep = scaling.by_drawdown(10_000.0, 9_000.0, 0.2)
    assert 1.0 > shallow > deep > scaling.FLOOR


def test_the_first_losses_barely_register():
    """Square root rather than linear: a book that tapers hard on a 2% dip
    cannot recover, because it trades a quarter size exactly when the edge it
    was sized for is still there."""
    assert scaling.by_drawdown(10_000.0, 9_800.0, 0.2) > 0.9


def test_at_the_halt_it_is_the_floor():
    assert scaling.by_drawdown(10_000.0, 8_000.0, 0.2) == scaling.FLOOR


def test_it_is_off_without_a_halt():
    assert scaling.by_drawdown(10_000.0, 5_000.0, 0.0) == 1.0


# ------------------------------------------------------------------ together


def test_they_multiply():
    assert scaling.combined(0.5, 0.5) == pytest.approx(0.25)


def test_order_does_not_matter():
    assert scaling.combined(0.5, 0.8, 0.3) == pytest.approx(scaling.combined(0.3, 0.5, 0.8))


def test_nothing_can_enlarge_a_position():
    """The property that matters most. Every input rests on a few hundred
    observations, and a model that can size up can turn an estimation error
    into a margin call."""
    assert scaling.combined(5.0, 3.0) == 1.0


def test_it_never_reaches_zero():
    """A position sized to nothing is a refusal wearing a number, and the
    broker's volume step would round it away anyway."""
    assert scaling.combined(0.0, 0.0) == scaling.FLOOR


# ------------------------------------------------------------- the handover


def test_a_strategy_applies_all_four():
    import inspect

    from till_infinity.trading.strategy import Strategy

    source = inspect.getsource(Strategy.risk_scale)
    for name in ("crowding", "by_volatility", "by_edge", "by_drawdown"):
        assert name in source


def test_sizing_reads_it():
    import inspect

    from till_infinity.trading import scalper

    assert "self.risk_scale(" in inspect.getsource(scalper.LevelStrategy.consider)


def test_all_four_are_off_by_default():
    """Better sizing of a signal with no edge scales the loss rather than
    fixing it - see research/horizon.md - so these wait for that question."""
    from till_infinity.trading.config import Settings

    s = Settings()
    assert s.crowding_share == 0.0
    assert s.volatility_target_bps == 0.0
    assert s.edge_full_at == 0.0
    assert s.drawdown_halt_at == 0.0


# ------------------------------------------- the call the service actually makes


def test_every_strategy_accepts_what_the_service_passes():
    """The test that would have caught a two-hour outage.

    `FadeToValue` and `Council` override `consider` with their own signatures.
    Widening the base and the scalper left those two unchanged, and the service
    passes `positions` and `peak` to every strategy - so the trading service
    stopped with `FadeToValue.consider() got an unexpected keyword argument
    'positions'` while 1,653 tests passed, because none of them called it the
    way the service does.

    Signature-level, not behavioural: it asks whether each strategy can be
    *called*, which is exactly what broke.
    """
    import inspect

    import till_infinity.trading as td

    for name, cls in td.STRATEGIES.items():
        for method in ("consider", "consider_async"):
            found = getattr(cls, method, None)
            if found is None or method not in vars(cls):
                continue  # inherited, so the base's signature governs
            parameters = inspect.signature(found).parameters
            for wanted in ("positions", "peak"):
                assert wanted in parameters, f"{name}.{method} cannot take {wanted}"


def test_the_service_passes_them():
    """And the other half: a signature that accepts them is useless if the
    caller never sends them."""
    import inspect

    from till_infinity.trading import service

    source = inspect.getsource(service.Trader.on_signal)
    assert "positions=positions" in source
    assert "peak=self.peak_equity" in source


# ------------------------------------------ orders the broker holds and we forgot


class _Broker:
    """Enough of the execution port to answer `resting` and `withdraw`."""

    def __init__(self, resting):
        self._resting = list(resting)
        self.withdrawn = []

    async def resting(self):
        return list(self._resting)

    async def withdraw(self, ticket):
        self.withdrawn.append(ticket)


def _trader(**over):
    from till_infinity.bus import Bus
    from till_infinity.trading.config import Settings
    from till_infinity.trading.service import Trader

    made = {"entry_pending": True, "live": True}
    made.update(over)
    return Trader(Bus(), settings=Settings(**made))


@pytest.mark.asyncio
async def test_an_order_the_process_is_not_tracking_is_withdrawn():
    """`_waiting` is in-process memory and the broker's order book is not. A
    restart empties the first and leaves the second holding live orders that
    fill on setups this system stopped believing in hours ago."""
    trader = _trader()
    # `execution` is `paper or broker`, so setting the broker is how the real
    # thing is reached rather than patching a property.
    trader.broker = _Broker([111, 222])
    trader.paper = None
    await trader._orphans()
    assert trader.broker.withdrawn == [111, 222]


@pytest.mark.asyncio
async def test_an_order_it_is_tracking_is_left_alone():
    from till_infinity.trading.models import Side
    from till_infinity.trading.service import Waiting

    trader = _trader()
    trader._waiting["gold"] = Waiting(
        payload={}, feed="gold", trigger=4400.0, side=Side.BUY, until=0.0, ticket=111
    )
    trader.broker = _Broker([111, 222])
    trader.paper = None
    await trader._orphans()
    assert trader.broker.withdrawn == [222]


@pytest.mark.asyncio
async def test_it_does_nothing_when_resting_orders_are_off():
    """A deployment that never places one should never withdraw one either."""
    trader = _trader(entry_pending=False)
    trader.broker = _Broker([111])
    trader.paper = None
    await trader._orphans()
    assert trader.broker.withdrawn == []


@pytest.mark.asyncio
async def test_a_broker_that_will_not_answer_is_not_a_fault():
    """Sweeping is recovery, not machinery: it must not stop the heartbeat."""
    from till_infinity.trading.broker import BrokerError

    class Broken(_Broker):
        async def resting(self):
            raise BrokerError("no")

    trader = _trader()
    trader.broker = Broken([])
    trader.paper = None
    await trader._orphans()  # must not raise


def test_the_heartbeat_sweeps_them():
    """A recovery nothing calls is not a recovery."""
    import inspect

    from till_infinity.trading import service

    assert "await self._orphans()" in inspect.getsource(service.Trader.sweep)


# ------------------------------------------------ one ceiling per trading style


def _engine(name, **over):
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    return td.STRATEGIES[name](Settings(**over))


def test_a_swing_and_a_scalp_have_different_ceilings():
    """`max_hold` was never a global cap - `hold_for` read it only when a
    strategy named no hold of its own, so every swing was governed by a
    hardcoded ClassVar no deployment could reach."""
    assert _engine("swing-level").ceiling == 21_600.0
    assert _engine("level-scalp").ceiling == 1_800.0


def test_each_ceiling_is_settable():
    assert _engine("swing-level", max_hold_swing=7_200.0).ceiling == 7_200.0
    assert _engine("level-scalp", max_hold=600.0).ceiling == 600.0


def test_a_strategy_asking_for_longer_than_its_style_is_capped():
    """That is what makes these ceilings rather than defaults. `council` asks
    for 2,700s as a scalp and is held to 1,800."""
    engine = _engine("council")
    assert engine.hold_seconds > engine.ceiling
    assert engine.hold_for("1h") == engine.ceiling


def test_a_strategy_asking_for_less_keeps_what_it_asked_for():
    """`snap` wants 120 seconds and a ceiling must not lengthen a trade."""
    assert _engine("snap").hold_for("1h") == 120.0


def test_the_swing_ceiling_falls_back_to_the_scalp_one():
    """Zero means unset, not "no hold at all" - a swing with no ceiling of its
    own is capped like everything else rather than uncapped."""
    assert _engine("swing-level", max_hold_swing=0.0).ceiling == 1_800.0


def test_every_swing_entry_is_a_higher_timeframe():
    """The split is by declared style rather than by name, and this is what
    says the two agree: `approach-scalp` and `fade-to-value` are named like
    scalps and classed as swings because of what they hold."""
    import till_infinity.trading as td

    for name, cls in td.STRATEGIES.items():
        if cls.style != "swing" or not cls.entries:
            continue
        assert set(cls.entries) <= {"15m", "30m", "1h", "2h", "4h", "1d", "1w"}, name


# ------------------------------------- a close with no decision behind it


def _closed(ref: str):
    """Settle a position and return every journal call it made."""
    import asyncio

    import till_infinity.trading as td
    from till_infinity.bus import Bus
    from till_infinity.trading.config import Settings
    from till_infinity.trading.models import Intent, Side
    from till_infinity.trading.service import Live, Trader

    written = []

    class Book:
        async def write(self, entry):
            written.append(entry)
            return entry.id

    trader = Trader(Bus(), settings=Settings(live=False), journal=Book())
    live = Live(
        position=td.Position(
            ticket=5762684366, symbol="XAUUSD", side=Side.BUY, volume=0.05, price_open=4400.0
        ),
        intent=Intent(
            feed="gold",
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.05,
            entry=4400.0,
            stop=4395.0,
            target=4410.0,
        ),
        ref=ref,
        by="runner",
    )

    async def run():
        await trader._settle(live, price=4405.0, why="closed", profit=13.2)

    asyncio.run(run())
    return written


def test_a_close_with_a_decision_is_journalled_as_an_outcome():
    written = _closed("decision-123")
    kinds = [str(e.kind) for e in written]
    assert "outcome" in kinds


def test_a_close_with_no_decision_still_reaches_the_journal():
    """After a restart `self.open` is rebuilt from the broker and the ref lives
    in memory, so every position that outlived one closed without being
    recorded: twenty tickets closed in fourteen hours, six outcomes written."""
    written = _closed("")
    assert written, "an unattributed close must not vanish"
    assert any("unattributed" in str(e.title) for e in written)


def test_an_unattributed_close_is_an_observation_not_an_outcome():
    """`journal.outcome` refuses a parentless entry on purpose - an outcome is
    a label on a decision. Forcing one through would break that invariant to
    fix this."""
    written = _closed("")
    assert all(str(e.kind) != "outcome" for e in written)


def test_the_ticket_is_recorded():
    """The one identifier tying our books to the broker's, and the one thing
    that was not written down - a ticket from an alert could not be traced to
    its record at all."""
    for ref in ("decision-123", ""):
        written = _closed(ref)
        assert any(e.context.get("ticket") for e in written), ref


# ------------------------------- requiring a higher timeframe behind a scalp


def _scalp(**over):
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    return td.STRATEGIES["level-scalp"](Settings(**over))


def test_every_scalp_names_a_higher_timeframe_as_context():
    """The requirement is only meaningful if the context is actually higher -
    a 1m call confirmed by 3m is the same fast noise seen twice."""
    import till_infinity.trading as td

    fast = {"1m", "3m", "5m"}
    for name, cls in td.STRATEGIES.items():
        if cls.style != "scalp" or not cls.context:
            continue
        assert not (set(cls.context) & fast), name
        assert set(cls.context) <= {"15m", "30m", "1h", "2h", "4h", "1d", "1w"}, name


def test_every_strategy_wants_context():
    """The switch that staged this for scalps is gone: a trigger with nothing
    above it agreeing is a fast trade in no direction, whatever the style."""
    import till_infinity.trading as td

    for name, cls in td.STRATEGIES.items():
        assert cls.needs_context is True, name


def test_a_strategy_naming_no_context_is_not_gated():
    """`council` delegates to its members, which carry their own anchors.
    Asking it for agreement it never declared would refuse every call."""
    import till_infinity.trading as td

    engine = td.STRATEGIES["council"](_scalp().settings)
    assert engine.context == ()
    assert engine.anchors == ()


def test_the_gate_reads_both():
    import inspect

    from till_infinity.trading import scalper

    source = inspect.getsource(scalper.LevelStrategy.consider)
    assert "self.needs_context and bool(self.context)" in source


def test_origin_swing_analyses_on_the_same_frame_as_the_rest():
    """Was (4h, 1d) alone from 2026-09-01. Folded into the shared 1h-4h
    analysis frame on 2026-09-03: the break rate flattens past 30m - 2.8% at
    30m, 1.4% at 1h, 0.0% at 2h, 4.3% at 4h - so insisting on the daily buys
    nothing over 4h and costs most of the signals."""
    import till_infinity.trading as td

    assert td.STRATEGIES["origin-swing"].context == ("1h", "2h", "4h")


def test_a_stop_that_overshoots_gives_back_the_size_it_overshot_by():
    """Boom 500 stops came back at -1.25R where they were placed at 1R, so a
    trade sized to risk one unit risked a quarter more than it authorised.
    0.8 size restores what the plan said."""
    from till_infinity.trading import scaling

    assert scaling.by_slippage(1.25) == pytest.approx(0.8)
    assert scaling.by_slippage(1.79) == pytest.approx(1 / 1.79)


def test_a_stop_that_behaves_is_left_alone():
    from till_infinity.trading import scaling

    assert scaling.by_slippage(1.0) == 1.0
    assert scaling.by_slippage(0.0) == 1.0


def test_a_stop_that_comes_back_better_than_1r_never_enlarges():
    """An instrument whose stops beat their price is not a reason to trade it
    bigger; it is a reason to distrust five observations."""
    from till_infinity.trading import scaling

    assert scaling.by_slippage(0.5) == 1.0


def test_an_unlisted_instrument_is_unscaled():
    """Every other feed must size exactly as it did before this existed."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings(stop_overshoot=(("boom_500_index", 1.25),))
    engine = td.STRATEGIES["level-scalp"](made)
    assert engine.risk_scale("gold", {"vol_bps": 10.0}) == 1.0
    assert engine.risk_scale("boom_500_index", {"vol_bps": 10.0}) == pytest.approx(0.8)


def test_the_pairs_survive_a_typo():
    """A malformed entry costs the correction, not the desk."""
    from till_infinity.trading.config import _overshoot

    assert _overshoot("boom_500_index=1.25") == (("boom_500_index", 1.25),)
    assert _overshoot("boom_500_index=oops,gold=1.1") == (("gold", 1.1),)
    assert _overshoot("") == ()


# ------------------------------------------- one strategy instead of nine


def test_opportunity_is_registered_and_attributable():
    """A strategy without a slot in MAGIC_ORDER stamps a hashed magic with no
    inverse, so every position it opens closes as "unattributed" and it cannot
    be scored. Two strategies have already run live that way."""
    import till_infinity.trading as td
    from till_infinity.trading.config import MAGIC_ORDER, magic_for

    assert "opportunity" in td.STRATEGIES
    assert "opportunity" in MAGIC_ORDER
    magics = {n: magic_for(777700, n) for n in td.STRATEGIES}
    assert len(set(magics.values())) == len(magics)


def test_opportunity_has_no_clock_of_its_own():
    """91 closes ended on the clock rather than a barrier, and replaying them
    without it turned -10.58R into -0.91R. `hold_seconds` 0 means the
    deployment ceiling and nothing tighter."""
    import till_infinity.trading as td

    engine = td.STRATEGIES["opportunity"](_scalp().settings)
    assert engine.hold_seconds == 0.0
    assert engine.hold_for("1m") == engine.ceiling
    assert engine.hold_for("4h") == engine.ceiling


def test_opportunity_will_not_trigger_below_fifteen_minutes():
    """A floor on the level, not on the trade. How long it is *held* is still
    left to the barriers - `hold_seconds` is 0. Which timeframe **drew** the
    level is a different question, and the largest quality signal on the book:
    1m levels break 57.9% of the time against 1.4% at 1h."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings(intervals=("1m", "5m", "15m", "30m", "1h", "1d"))
    engine = td.STRATEGIES["opportunity"](made)
    assert "1m" not in engine.intervals
    assert "5m" not in engine.intervals
    # Entry below the hour: the trigger fixes the stop, the analysis does not.
    assert engine.intervals == ("15m", "30m")
    # The hold is untouched: seconds to days, decided by the barriers.
    assert engine.hold_seconds == 0.0


def test_the_presets_recover_the_named_strategies():
    """The nine are points in this space, not separate things. If a preset
    drifts from the class it names, the map is a lie."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings()
    for name, shape in td.PRESETS.items():
        engine = td.STRATEGIES[name](made)
        assert engine.stop_multiple == shape.stop, name
        assert engine.target_multiple == shape.target, name
        assert engine.trail_vol == shape.trail, name
        assert engine.break_even_at == shape.protect, name
        assert engine.hold_seconds == shape.hold, name
        assert engine.pullback_fraction == shape.pullback, name
        assert engine.stop_floor_vol("5m") == shape.floor, name


def test_two_named_strategies_are_the_same_point():
    """`level-scalp` and `sweep-aware` have identical exits and differ only in
    an extra entry gate, which is the argument for this module in one line."""
    import till_infinity.trading as td

    assert td.PRESETS["level-scalp"] == td.PRESETS["sweep-aware"]


def test_the_shape_matches_the_class_it_configures():
    """`shape_of` and the ClassVars are two statements of one thing."""
    import till_infinity.trading as td

    cls = td.STRATEGIES["opportunity"]
    shape = cls.shape_of
    assert cls.stop_multiple == shape.stop
    assert cls.target_multiple == shape.target
    assert cls.trail_vol == shape.trail
    assert cls.break_even_at == shape.protect
    assert cls.hold_seconds == shape.hold
    assert cls.pullback_fraction == shape.pullback


# ------------------------------------- feedback on the arms nobody pulled


def _untaken(side="buy", entry=100.0, stop=99.0, target=103.0, hold=600.0):
    from till_infinity.trading.models import Side
    from till_infinity.trading.service import Untaken

    return Untaken(
        feed="gold",
        by="level-scalp",
        side=Side.BUY if side == "buy" else Side.SELL,
        entry=entry,
        stop=stop,
        target=target,
        interval="5m",
        fill_by=1_000.0,
        hold=hold,
        placed_at=0.0,
    )


async def _walk(shade, quotes):
    """Push quotes at one intent and return (finished, journalled rows)."""
    from till_infinity.bus import Bus
    from till_infinity.trading.models import Tick
    from till_infinity.trading.service import Trader

    trader = Trader(Bus(), settings=_scalp().settings)
    rows = []

    async def catch(_journal, title, **kw):
        rows.append(kw.get("context") or {})

    import till_infinity.trading.service as svc

    real, svc.observe = svc.observe, catch
    try:
        for when, bid, ask in quotes:
            if await trader._step_untaken(shade, Tick("XAUUSD", bid=bid, ask=ask, time=when)):
                return True, rows
    finally:
        svc.observe = real
    return False, rows


@pytest.mark.asyncio
async def test_an_untaken_intent_scores_when_its_target_arrives():
    """The feedback channel for an arm nobody pulled."""
    shade = _untaken()
    done, rows = await _walk(
        shade,
        [(10.0, 99.9, 100.0), (20.0, 101.0, 101.1), (30.0, 103.5, 103.6)],
    )
    assert done
    assert rows
    assert rows[-1]["resolved"] == "target"
    assert rows[-1]["reward_r"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_an_untaken_intent_that_never_fills_scores_nothing_rather_than_zero():
    """An absent trade is not a zero-reward trade. Averaging it in would
    flatter strategies that rest their entry out of reach."""
    shade = _untaken(entry=90.0)
    done, rows = await _walk(shade, [(10.0, 99.9, 100.0), (1_001.0, 99.9, 100.0)])
    assert done
    assert rows[-1]["resolved"] == "never filled"
    assert rows[-1]["reward_r"] is None
    assert rows[-1]["filled"] is False


@pytest.mark.asyncio
async def test_an_untaken_intent_takes_the_stop_at_minus_one():
    shade = _untaken()
    done, rows = await _walk(shade, [(10.0, 99.9, 100.0), (20.0, 98.5, 98.6)])
    assert done
    assert rows[-1]["resolved"] == "stop"
    assert rows[-1]["reward_r"] == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_an_untaken_intent_that_resolves_neither_way_is_marked_to_market():
    """Exactly as the live trade would have been by its own clock."""
    shade = _untaken(hold=100.0)
    done, rows = await _walk(
        shade, [(10.0, 99.9, 100.0), (20.0, 100.5, 100.6), (200.0, 100.5, 100.6)]
    )
    assert done
    assert rows[-1]["resolved"] == "timeout"
    assert rows[-1]["reward_r"] == pytest.approx(0.5, abs=0.01)


def test_untaken_intents_are_bounded_per_feed():
    """Strategies times signals grows quickly and nothing else evicts it."""
    from till_infinity.bus import Bus
    from till_infinity.trading.models import Intent, Side
    from till_infinity.trading.service import Trader

    trader = Trader(Bus(), settings=_scalp().settings)
    intent = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        entry=100.0,
        stop=99.0,
        target=103.0,
        volume=0.1,
    )
    for _ in range(trader.MAX_UNTAKEN + 25):
        trader._remember_untaken("gold", "level-scalp", intent, "5m", 600.0, 0.0)
    assert len(trader._untaken["gold"]) == trader.MAX_UNTAKEN
    # Counted, not dropped silently: an eviction is a missing observation, and
    # the ones it drops are the slowest to resolve.
    assert trader._spilled == 25


def test_the_cap_is_sized_for_a_day_long_hold():
    """`opportunity` holds to the 24h ceiling and roughly sixteen intents an
    hour arrive per busy feed, so a cap of 60 would evict most of them - and
    evict the slow ones, which biases every mean it feeds."""
    from till_infinity.trading.service import Trader

    assert Trader.MAX_UNTAKEN >= 384


# ----------------------------------------- choosing a shape from the record


def test_a_cold_policy_returns_the_measured_default_not_a_guess():
    """A policy that acts on four observations is how a five-stop sample became
    an instrument-wide sizing rule."""
    from till_infinity.trading.policy import Policy

    policy = Policy()
    shape, why = policy.pick("gold", "5m")
    assert shape == policy.fallback
    assert "cold" in why


def test_an_arm_cannot_win_until_it_has_been_seen_enough():
    from till_infinity.trading.policy import Policy

    policy = Policy()
    arm = next(iter(policy.arms))
    for _ in range(policy.MIN_SEEN - 1):
        policy.observe("gold", "5m", arm, 2.0)
    assert policy.pick("gold", "5m")[0] == policy.fallback
    policy.observe("gold", "5m", arm, 2.0)
    assert policy.pick("gold", "5m")[0] == policy.arms[arm]


def test_context_backs_off_rather_than_deciding_on_three_observations():
    """A thin cell falls back to the broader one. The family split is the one
    research/failing.md measures as actually separating."""
    from till_infinity.trading.policy import Policy, context_of

    assert context_of("boom_500_index", "5m") == ("boom|5m", "boom", "")
    assert context_of("gold", "1h")[1] == "metals/oil"
    assert context_of("volatility_75_index", "3m")[1] == "volatility"

    policy = Policy()
    arm = next(iter(policy.arms))
    # Warm at the family level only.
    for _ in range(policy.MIN_SEEN):
        policy.observe("boom_500_index", "1h", arm, 1.5)
    # A different interval on the same family still gets an answer.
    shape, why = policy.pick("boom_1000_index", "5m")
    assert shape == policy.arms[arm]
    assert why.startswith("boom")


def test_a_malformed_reward_cannot_own_the_policy():
    """Five intents of 1,757 carried an implied RR up to 30,338, and one of
    them touching produced +23R a trade across the whole book."""
    from till_infinity.trading.policy import CLIP, Policy

    policy = Policy()
    arm = next(iter(policy.arms))
    for _ in range(policy.MIN_SEEN):
        policy.observe("gold", "5m", arm, 30_338.0)
    score = policy.ledger.score("metals/oil|5m", arm)
    assert score is not None
    assert score.mean <= CLIP[1]


def test_the_same_point_under_two_names_is_one_arm():
    """`level-scalp` and `sweep-aware` are identical vectors. Crediting them
    separately would split one arm's evidence in half."""
    import till_infinity.trading as td
    from till_infinity.trading.policy import Policy

    policy = Policy()
    assert td.PRESETS["level-scalp"].named() == td.PRESETS["sweep-aware"].named()
    assert td.PRESETS["level-scalp"].named() in policy.arms


def test_opportunity_wears_the_shape_it_was_given():
    """And only the dimensions the engine reads - varying one nothing honours
    is a policy that appears to work and does not."""
    import till_infinity.trading as td
    from till_infinity.trading.opportunity import Shape

    engine = td.STRATEGIES["opportunity"](_scalp().settings)
    engine._wear(Shape(stop=2.0, target=1.25, trail=0.5, protect=0.25, hold=99.0, pullback=0.0))
    assert engine.stop_multiple == 2.0
    assert engine.target_multiple == 1.25
    assert engine.trail_vol == 0.5
    assert engine.break_even_at == 0.25
    assert engine.hold_seconds == 99.0
    assert engine.pullback_fraction == 0.0


def test_the_service_hands_its_policy_to_whatever_reads_one():
    from till_infinity.bus import Bus
    from till_infinity.trading.config import Settings
    from till_infinity.trading.service import Trader

    made = Settings(symbols=("gold",), strategies=("thesis-only", "opportunity"))
    trader = Trader(Bus(), settings=made)
    wearing = [e for e in trader.strategies if getattr(e, "policy", None) is not None]
    assert wearing, "nothing was given the policy"
    assert all(e.policy is trader.policy for e in wearing)


def test_an_untaken_intent_waits_exactly_as_long_as_a_real_resting_entry():
    """The first version gave every intent up to 24 hours to fill, where a real
    resting entry gets `pullback_bars` bars of its own interval and is
    withdrawn. That credited fills the live system would never have seen, to
    exactly the strategies that rest their entry furthest out of reach."""
    from till_infinity.bus import Bus
    from till_infinity.structures.levels import SECONDS
    from till_infinity.trading.service import Trader

    trader = Trader(Bus(), settings=_scalp().settings)
    bars = trader.settings.pullback_bars
    for interval in ("1m", "5m", "1h"):
        assert trader._fill_window(interval, 86_400.0) == SECONDS[interval] * bars
    # A 5m call gets fifty minutes, not a day.
    assert trader._fill_window("5m", 86_400.0) == 3_000.0
    # An unknown interval falls back to the hold, which is a real bound.
    assert trader._fill_window("", 86_400.0) == 86_400.0


def test_the_fill_window_matches_the_one_park_uses():
    """Two expressions of one rule drift. This asserts they are one."""
    import inspect

    from till_infinity.trading import service

    parked = inspect.getsource(service.Trader._park)
    window = inspect.getsource(service.Trader._fill_window)
    shared = "self.settings.pullback_bars if bars else"
    assert shared in parked
    assert shared in window


# ------------------------------------------- sizing by the entry timeframe


def test_the_entry_timeframe_sizes_the_trade():
    """Sub-15m is -821.75 over 129 closes; 15m and above is +35.03 over 21,
    and the ordering is monotone across every band between."""
    from till_infinity.trading import scaling

    weights = (("1m", 0.3), ("3m", 0.5), ("15m", 0.7))
    assert scaling.by_interval("1m", weights) == 0.3
    assert scaling.by_interval("15m", weights) == 0.7


def test_an_unlisted_timeframe_sizes_at_full():
    """Every interval must size exactly as it did before this existed unless
    somebody named it."""
    from till_infinity.trading import scaling

    assert scaling.by_interval("4h", (("1m", 0.3),)) == 1.0
    assert scaling.by_interval("1m", ()) == 1.0
    assert scaling.by_interval("", (("1m", 0.3),)) == 1.0


def test_the_interval_weight_never_enlarges():
    """Same rule as every other model here: a sizing input that can size up is
    one that turns an estimation error into a margin call."""
    from till_infinity.trading import scaling

    assert scaling.by_interval("1m", (("1m", 4.0),)) == 1.0
    assert scaling.by_interval("1m", (("1m", -2.0),)) == scaling.FLOOR


def test_it_is_off_until_somebody_sets_it():
    from till_infinity.trading.config import Settings

    assert Settings().interval_weight == ()


def test_the_strategy_passes_the_interval_through():
    """A weighting the sizing call never receives is a weighting that appears
    to work and does not - which is the defect this repository keeps finding."""
    import inspect

    import till_infinity.trading as td
    from till_infinity.trading import scalper
    from till_infinity.trading.config import Settings

    assert "interval" in inspect.signature(td.Strategy.risk_scale).parameters
    assert "positions, equity, peak, interval" in inspect.getsource(scalper.LevelStrategy.consider)

    made = Settings(interval_weight=(("1m", 0.25),))
    engine = td.STRATEGIES["level-scalp"](made)
    assert engine.risk_scale("gold", {"vol_bps": 10.0}, interval="1m") == 0.25
    assert engine.risk_scale("gold", {"vol_bps": 10.0}, interval="1h") == 1.0


# --------------------------------------- momentum leads, the candle confirms


def test_every_higher_timeframe_strategy_lets_momentum_lead():
    """Asked for on 2026-09-03. On a higher timeframe a bar takes hours to
    close, so a trade taken on the candle alone is taken on evidence that has
    already happened."""
    import till_infinity.trading as td

    for name, cls in td.STRATEGIES.items():
        if cls.style == "swing":
            assert cls.momentum_leads is True, name


def test_the_scalps_are_left_alone():
    """The disjunction is right for a scalp: it cannot wait four hours for a
    bar and would refuse a clean fast turn for having no candle yet."""
    import till_infinity.trading as td

    for name, cls in td.STRATEGIES.items():
        if cls.style == "scalp":
            assert cls.momentum_leads is False, name


def test_a_leading_momentum_makes_the_turn_compulsory():
    """The leak this closes: the turn is read only *after a pullback*, so on
    any other entry it is an absent witness rather than an unsatisfied one -
    and the candle was then the only thing asked, carrying the trade alone."""
    import inspect

    from till_infinity.trading import service

    source = inspect.getsource(service.Trader._rejected_at)
    # Asked for even without a pullback, once momentum leads.
    assert 'intent.features.get("after_pullback") or leads' in source
    # And its absence refuses rather than falling through to the candle.
    assert "elif leads:" in source
    assert '"momentum leads here and has not turned' in source


def test_leading_momentum_still_wants_the_candle():
    """It is confirmation, not a replacement: a hammer is a momentum reversal
    compressed into one bar, which is worth having in that order."""
    import inspect

    from till_infinity.trading import service

    source = inspect.getsource(service.Trader._rejected_at)
    assert "both = both or leads" in source


def test_the_chosen_arm_is_written_onto_the_decision():
    """`opportunity` is a parameter vector, not a fixed set of numbers, so
    "opportunity lost 15.90" says nothing without knowing which shape it wore.
    Its first five trades were recorded with the arm absent."""
    import inspect

    from till_infinity.bus import Bus
    from till_infinity.trading.config import Settings
    from till_infinity.trading.service import Trader

    source = inspect.getsource(Trader)
    assert '"arm": self._arm_of(by)' in source

    made = Settings(symbols=("gold",), strategies=("thesis-only", "opportunity"))
    trader = Trader(Bus(), settings=made)
    engine = next(e for e in trader.strategies if e.name == "opportunity")
    engine.arm = "stop1/target3/trail1"
    assert trader._arm_of("opportunity") == "stop1/target3/trail1"
    # A strategy that chooses no shape reports none rather than guessing.
    assert trader._arm_of("thesis-only") == ""
    assert trader._arm_of("nothing-by-this-name") == ""


# ------------------------------------ keeping the fast timeframes off the wire


def _filter(**kw):
    from till_infinity.notifications.filters import Filter

    return Filter(**kw)


def test_a_fast_interval_is_kept_off_the_channel():
    """Sub-15m is where the noise and the losses both are: 129 closes and
    -821.75 below fifteen minutes against 21 closes and +35.03 at or above it.
    On the wire the imbalance is worse - gold published 96 level rows on 1m in
    48 hours against one on 4h."""
    got = _filter(floor="15m")
    assert "below the 15m floor" in got.rejects({"shape": "level", "interval": "1m"})
    assert "below the 15m floor" in got.rejects({"shape": "level", "interval": "5m"})


def test_the_floor_itself_and_anything_slower_gets_through():
    got = _filter(floor="15m")
    assert got.rejects({"shape": "level", "interval": "15m"}) == ""
    assert got.rejects({"shape": "level", "interval": "1h"}) == ""
    assert got.rejects({"shape": "level", "interval": "1d"}) == ""


def test_an_alert_carrying_no_interval_is_kept():
    """A trade opening and a service fault carry none, and dropping those would
    be the opposite of the point."""
    got = _filter(floor="15m")
    assert got.rejects({"shape": "trade"}) == ""
    assert got.rejects({"shape": "level", "interval": ""}) == ""


def test_an_unknown_interval_is_kept_rather_than_guessed():
    """A filter that silently drops what it cannot parse goes quiet for reasons
    nobody can see."""
    got = _filter(floor="15m")
    assert got.rejects({"shape": "level", "interval": "7m"}) == ""
    assert _filter(floor="nonsense").rejects({"shape": "level", "interval": "1m"}) == ""


def test_it_reads_the_interval_from_the_alert_fields_too():
    """Trade alerts nest their metadata under `fields`."""
    got = _filter(floor="15m")
    assert "below the 15m floor" in got.rejects({"shape": "level", "fields": {"interval": "3m"}})


def test_no_floor_accepts_every_timeframe():
    got = _filter()
    assert got.rejects({"shape": "level", "interval": "1m"}) == ""


def test_the_floor_is_read_from_the_environment():
    import os

    from till_infinity.notifications.filters import Filter

    os.environ["NOTIFY_MIN_INTERVAL"] = "30m"
    try:
        assert Filter.from_env().floor == "30m"
    finally:
        del os.environ["NOTIFY_MIN_INTERVAL"]


def test_a_level_alert_carries_its_timeframe():
    """`NOTIFY_MIN_INTERVAL` reads the interval off the alert. It was absent,
    so the floor was silently inert - configured, describing itself correctly,
    passing its own tests, and dropping nothing. The filter's rule that a
    missing interval is *kept* is right for a trade or a fault, and was exactly
    what hid this."""
    import inspect

    from till_infinity.structures import service

    source = inspect.getsource(service)
    i = source.index('"instrument": signal.feed')
    block = source[i : i + 900]
    assert '"interval": signal.interval' in block


def test_the_floor_actually_bites_on_an_alert_shaped_payload():
    """The earlier check used a payload the filter reads differently - shape
    lives under `fields`, so everything was rejected on shape and the floor was
    never reached."""
    from till_infinity.notifications.filters import Filter

    made = Filter(shapes=frozenset({"level"}), floor="15m")

    def alert(iv):
        return {"fields": {"shape": "level", "instrument": "gold", "interval": iv}}

    assert "below the 15m floor" in made.rejects(alert("1m"))
    assert "below the 15m floor" in made.rejects(alert("5m"))
    assert made.rejects(alert("15m")) == ""
    assert made.rejects(alert("4h")) == ""


def test_every_swing_analyses_slow_and_enters_fast():
    """Asked for on 2026-09-03: analysis on 1h-4h, entry below the hour, the
    exit horizon at an hour or more. It is what `swing-level` already argued
    for - the slow frame says *whether*, the fast one says *when* - and it was
    only true of the context, never of the entries."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings()
    for name, cls in td.STRATEGIES.items():
        if cls.style != "swing":
            continue
        engine = cls(made)
        assert engine.entries == ("15m", "30m"), name
        assert engine.context == ("1h", "2h", "4h"), name
        # Nothing enters at or above the hour any more.
        assert all(iv in ("15m", "30m") for iv in engine.entries), name
        # And the exit horizon stays at an hour or more.
        assert engine.hold_for("15m") >= 3600.0, name


# ------------------------------- the trail-only exit, beside the target one


def test_ride_is_opportunity_with_the_target_out_of_reach():
    """The pair is a comparison: same entry, same frame, same gates, only the
    exit differs. Measured on 31,820 replayed touches before it was written -
    trail 0.5v with no target scored +0.404R against -0.041R for the best fixed
    target, and every fixed target lost."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings()
    ride = td.STRATEGIES["ride"](made)
    opp = td.STRATEGIES["opportunity"](made)

    assert ride.entries == opp.entries
    assert ride.context == opp.context
    assert ride.stop_multiple == opp.stop_multiple
    assert ride.hold_seconds == opp.hold_seconds == 0.0
    # Only the exit moves.
    assert ride.trail_vol == 0.5
    assert ride.target_multiple == 6.0
    assert ride.target_multiple > opp.target_multiple
    assert ride.trail_vol < opp.trail_vol


def test_the_target_is_moved_rather_than_removed():
    """`lots` and the reward-to-risk gate both need a target to exist: a trade
    with no stated objective cannot be sized or refused."""
    import till_infinity.trading as td

    assert td.STRATEGIES["ride"].target_multiple > 0


def test_ride_is_attributable_and_is_an_arm():
    """A strategy without a MAGIC_ORDER slot closes every position as
    "unattributed" and cannot be scored - two have run live that way."""
    import till_infinity.trading as td
    from till_infinity.trading.config import MAGIC_ORDER, magic_for

    assert "ride" in MAGIC_ORDER
    magics = {n: magic_for(777700, n) for n in td.STRATEGIES}
    assert len(set(magics.values())) == len(magics)
    # And the policy can pick its shape.
    assert "ride" in td.PRESETS
    assert td.PRESETS["ride"].trail == 0.5


def test_both_exits_are_scored_on_the_same_signals():
    """`_also_wanted` scores every strategy that did not take a signal, so
    listing them together is what makes the comparison settle itself."""
    import till_infinity.trading as td

    assert {"opportunity", "ride"} <= set(td.STRATEGIES)


def test_the_manage_loop_says_why_it_skipped_a_position():
    """Four trades reached 2.75R to 4.32R in front and closed at their original
    stop for -68.71, with break-even, trailing and scale-out all configured.
    This loop had produced two stop moves in 181,039 log lines and no
    scale-outs, with no errors: every position fell through a guard and nothing
    recorded which one."""
    import inspect

    from till_infinity.trading import service

    source = inspect.getsource(service.Trader._manage)
    # The two guards report separately - "no spec" and "no best" need different
    # fixes, and one message for both would not distinguish them.
    assert 'skipped[f"no spec for {live.intent.feed!r}"]' in source
    assert 'skipped["no best price tracked"]' in source
    # And a loop that reached `advance` and moved nothing says so too, which is
    # the third possibility and the one a guard count alone would hide.
    assert "managed nothing across" in source
    assert "proposed no better stop" in source


def test_a_quiet_book_is_not_reported_as_a_fault():
    """`looked and not moved` - with no open positions there is nothing to
    manage, and logging that every minute would bury the case that matters."""
    import inspect

    from till_infinity.trading import service

    assert "if looked and not moved:" in inspect.getsource(service.Trader._manage)
