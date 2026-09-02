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


def test_origin_swing_anchors_on_the_high_timeframes_alone():
    """Asked for on 2026-09-01: the space between two origins is only worth
    trading when 4h or 1d says the far one is real."""
    import till_infinity.trading as td

    assert td.STRATEGIES["origin-swing"].context == ("4h", "1d")


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


def test_opportunity_triggers_on_any_timeframe():
    """There is no scalping and no swing trading, only opportunities. Empty
    `entries` means whatever the deployment allows."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings(intervals=("1m", "5m", "1h", "1d"))
    engine = td.STRATEGIES["opportunity"](made)
    assert engine.entries == ()
    assert engine.intervals == ("1m", "5m", "1h", "1d")


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
