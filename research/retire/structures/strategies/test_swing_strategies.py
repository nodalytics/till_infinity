"""The swing strategies' own tests, as they passed when the strategies retired.

Moved out of `tests/test_trading.py` on 2026-10-28 with `swing.py`:
`approach-scalp`, `runner`, `swing-level`, `origin-swing` and `fade-to-value`.
They import `till_infinity.trading.strategies.swing`, which lives beside this file,
so they do not run as they stand - and they lean on fixtures that stayed in
`tests/test_trading.py` (`settings`, `signal`, `strategy`), so reviving one means
bringing those with it.

`test_fade_to_value_is_still_exempt_from_the_chase_gate` is the one worth reading:
chasing means filling far from the level a call was measured at, and being far from
fair value was that strategy's entire premise, so the gate would have refused every
trade it ever wanted.
"""

def test_approach_scalp_asks_for_longer_than_the_default_hold():
    """The desk's observation is that it takes twenty to thirty minutes."""
    assert td.ApproachScalp.hold_seconds > td.Settings().max_hold


def test_every_strategy_clears_the_same_gates():
    """One of them was not, and it was the one taking most of the trades.

    `FadeToValue` overrides `consider` entirely and therefore ran none of the
    shared chain - so the probability floor, the per-direction percentile, the
    edge floor and the base-rate floor applied to three strategies and not to
    the fourth. The exemption was invisible from the configuration, which read
    as though every gate protected every strategy.
    """
    weak = signal(features={"probability": 0.30, "base_rate_up": 0.20})
    for name in ("level-scalp", "sweep-aware", "approach-scalp", "fade-to-value"):
        got = take(name, weak, min_probability=0.75, min_base_rate=0.55)
        assert isinstance(got, Refusal), f"{name} took a call it should have refused"


def test_the_shared_gates_live_in_one_place():
    """A copied block is two implementations that can drift; this is one."""
    import inspect

    from till_infinity.trading.strategies.scalper import LevelStrategy
    from till_infinity.trading.strategies.swing import FadeToValue

    assert hasattr(LevelStrategy, "quality")
    # Both paths call it rather than repeating it.
    assert "self.quality(" in inspect.getsource(LevelStrategy.consider)
    assert "self.quality(" in inspect.getsource(FadeToValue.consider)


def test_fade_to_value_is_still_exempt_from_the_chase_gate():
    """Not an oversight. Chasing means filling far from the level the call was
    measured at, and being far from fair value is this strategy's entire
    premise - the gate would refuse every trade it ever wanted."""
    import inspect

    from till_infinity.trading.strategies.swing import FadeToValue

    assert "_chasing(" not in inspect.getsource(FadeToValue.consider)


def _swing():
    from till_infinity.trading.strategies.swing import SwingLevel

    return SwingLevel(settings())


def test_the_swing_targets_the_far_side_of_the_range():
    """Every other strategy aims at a multiple of the modelled push, which is a
    distance the sizer chose. This aims where the next agreed level actually
    is."""
    swing = _swing()
    feats = {"swing_room_up_vol": 6.0, "swing_room_down_vol": 1.0}

    _stop, target = swing.distances(
        4400.0, 4400.0, 10.0, risk_vol=1.0, push_vol=1.0, features=feats, side=Side.BUY
    )
    # 6.0v to the ceiling beats the 2.5x1.0 the push multiple would have given.
    assert target == pytest.approx(price_distance(4400.0, 10.0, 6.0))


def test_a_short_aims_at_the_floor_not_the_ceiling():
    swing = _swing()
    feats = {"swing_room_up_vol": 6.0, "swing_room_down_vol": 5.0}

    _stop, target = swing.distances(
        4400.0, 4400.0, 10.0, risk_vol=1.0, push_vol=1.0, features=feats, side=Side.SELL
    )

    assert target == pytest.approx(price_distance(4400.0, 10.0, 5.0))


def test_a_bound_nearer_than_the_push_does_not_cut_the_trade_short():
    """The far side is a floor, not a replacement. A target inside what the
    model already expects price to reach is leaving the move on the table."""
    swing = _swing()
    feats = {"swing_room_up_vol": 0.5, "swing_room_down_vol": 9.0}

    _stop, target = swing.distances(
        4400.0, 4400.0, 10.0, risk_vol=1.0, push_vol=2.0, features=feats, side=Side.BUY
    )

    # 2.0 push x 2.5 multiple = 5.0v, which beats the 0.5v bound.
    assert target == pytest.approx(price_distance(4400.0, 10.0, 5.0))


def test_an_open_side_falls_back_to_the_push():
    """`room_up_vol` is absent when that side of the range is open air, and
    open air is not a target."""
    swing = _swing()

    _stop, target = swing.distances(
        4400.0,
        4400.0,
        10.0,
        risk_vol=1.0,
        push_vol=2.0,
        features={"room_down_vol": 3.0},
        side=Side.BUY,
    )

    assert target == pytest.approx(price_distance(4400.0, 10.0, 5.0))


def test_no_features_at_all_is_the_old_behaviour():
    """An older signal carries no range, and the strategy must still trade."""
    swing = _swing()

    _stop, target = swing.distances(4400.0, 4400.0, 10.0, risk_vol=1.0, push_vol=2.0)

    assert target == pytest.approx(price_distance(4400.0, 10.0, 5.0))


def test_the_swing_still_trails_past_the_bound():
    """Aiming at the next level would be a worse strategy if it closed there.
    The trail is what lets a move that keeps going keep going."""
    swing = _swing()

    assert swing.trail_vol >= 4.0
    assert swing.pullback_fraction == 1.0


def test_the_swing_will_not_buy_in_the_middle_of_its_range():
    """A range trade is a bet that a wall holds, so there has to be a wall.
    Anywhere in between is a directional trade wearing a range trade's stop."""
    swing = _swing()

    middle = swing.at_the_right_place("gold", Side.BUY, {"swing_range_position": 0.5})
    floor = swing.at_the_right_place("gold", Side.BUY, {"swing_range_position": 0.05})

    assert middle is not None
    assert middle.gate == "range"
    assert floor is None


def test_the_swing_sells_at_the_ceiling_not_the_floor():
    swing = _swing()

    assert swing.at_the_right_place("gold", Side.SELL, {"swing_range_position": 0.95}) is None
    assert swing.at_the_right_place("gold", Side.SELL, {"swing_range_position": 0.05}) is not None


def test_no_range_is_not_evidence_against_the_trade():
    """One side open air, or an older signal with no `swing_*` readings at all.
    Refusing on a missing structure would make the strategy quietly dependent
    on a feature that is often absent."""
    swing = _swing()

    assert swing.at_the_right_place("gold", Side.BUY, {}) is None
    assert swing.at_the_right_place("gold", Side.BUY, {"range_position": 0.5}) is None


def test_the_swing_strategies_declare_the_exemption():
    """Declared per strategy rather than derived from the hold, so a new
    strategy has to say what kind of thing it is instead of inheriting an
    exemption from a number it happened to pick."""
    from till_infinity.trading.strategies.scalper import LevelScalp, SweepAware
    from till_infinity.trading.strategies.swing import (
        FadeToValue,
        OriginSwing,
        Runner,
        SwingLevel,
    )

    for engine in (SwingLevel, OriginSwing, Runner, FadeToValue):
        assert engine.stale_exempt is True, engine.name

    for engine in (LevelScalp, SweepAware):
        assert engine.stale_exempt is False, engine.name


def test_origin_swing_holds_for_three_days_and_the_ceiling_allows_it():
    """`hold_for` takes `min(hold_seconds, ceiling)`, so a declaration above
    `max_hold_swing` is silently clamped - which is how a strategy ends up
    configured for one thing and running as another. Both have to move."""
    from till_infinity.trading.strategies.swing import OriginSwing

    assert OriginSwing.hold_seconds == 72 * 3600.0

    made = settings(max_hold_swing=72 * 3600.0)
    engine = OriginSwing(made)
    assert engine.hold_for("30m") == pytest.approx(72 * 3600.0)

    # And the clamp is real, so the env change is not decoration.
    tight = OriginSwing(settings(max_hold_swing=24 * 3600.0))
    assert tight.hold_for("30m") == pytest.approx(24 * 3600.0)




def test_approach_scalp_buys_up_to_the_level_above():
    engine = strategy("approach-scalp")
    # A level above, and the confirming call at the one price is standing on.
    engine.observe(swing(features={"level": 4410.0}))  # 2.2v above the fill
    engine.observe(swing())
    got = engine.consider(
        swing(),
        spec=GOLD,
        tick=Tick("XAUUSD", bid=4399.5, ask=4400.5),
        equity=10_000.0,
    )
    assert isinstance(got, Intent)
    # Short of 4410 by the quarter-unit buffer (0.25 * 4.40 = 1.10), because
    # the last stretch into the zone is the part magnet.md says nothing about.
    assert got.target == pytest.approx(4408.9)
    # The stop is still anchored beyond the confirming level, not the target.
    assert got.stop == pytest.approx(4395.6)
    assert got.hold == pytest.approx(4 * 3_600.0)


def test_approach_scalp_sells_down_to_the_level_below():
    engine = strategy("approach-scalp")
    engine.observe(swing(features={"level": 4390.0}))  # 2.2v below the fill
    down = swing(direction="down")
    engine.observe(down)
    got = engine.consider(
        down, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.target == pytest.approx(4391.1)  # 4390 + the buffer


def test_approach_scalp_refuses_when_it_knows_of_no_level_to_aim_at():
    engine = strategy("approach-scalp")
    engine.observe(swing())
    got = engine.consider(
        swing(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "no_target"


def test_approach_scalp_refuses_a_level_too_far_to_reach_in_the_hold():
    engine = strategy("approach-scalp")
    engine.observe(swing(features={"level": 4700.0}))  # ~68 volatility units
    engine.observe(swing())
    got = engine.consider(
        swing(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "too_far"


# ------------------------------------------------------- scoring what it did


async def a_closed_trade(
    book, *, strategy="level-scalp", profit=10.0, risk=20.0, feed="gold", at=4400.5
):
    """Write the decision/outcome pair the trader writes.

    `at` varies the entry price, and it has to. Journal entries are
    content-addressed on `(time, actor, title)` and written INSERT OR IGNORE,
    so two trades with the same title inside one clock tick are deliberately
    one entry. A fixture that wrote ten identical titles therefore produced six
    rows on a fast machine and ten on a slow one - which is the journal working
    as documented, and a test that had not noticed real titles carry the volume
    and the fill price.
    """
    from till_infinity.journal import decide, outcome

    ref = await decide(
        book,
        f"paper: buy 0.05 {feed} @ {at:.5g}",
        rationale="up from above",
        actor="trading",
        context={
            "strategy": strategy,
            "mode": "paper",
            "feed": feed,
            "side": "buy",
            "risk_money": risk,
            "reward_to_risk": 1.4,
        },
        tags=(feed, "buy", strategy, "paper"),
    )
    await outcome(
        book,
        ref,
        f"{feed} closed {profit:+.2f} from {at:.5g}",
        actor="trading",
        context={"profit": profit, "seconds": 300, "reason": "target", "exit_source": "broker"},
    )
    return ref


async def test_a_closed_trade_is_scored_in_r_not_money(tmp_path):
    """40 won risking 20 and 40 won risking 200 are not the same result."""
    async with Journal(tmp_path / "j.db") as book:
        await a_closed_trade(book, profit=40.0, risk=20.0)
    found = tr.trades(tmp_path / "j.db")
    assert len(found) == 1
    assert found[0].r == pytest.approx(2.0)
    assert found[0].won


async def test_a_trade_open_across_a_restart_is_still_scored(tmp_path):
    """A position this process did not open is rebuilt by `_intent_from`, which
    has the broker's position and no sizing to state - so its `risk_money` is the
    dataclass default and the close record spreads that zero over the figure the
    decision recorded.

    The trade was then dropped entirely rather than scored badly: 839 of 1,486
    closed trades in the live journal carried this zero on 2026-10-04, so 56% of
    the record was invisible to every report.
    """
    from till_infinity.journal import decide, outcome

    async with Journal(tmp_path / "j.db") as book:
        ref = await decide(
            book,
            "paper: buy 0.05 eurusd @ 1.1",
            rationale="up from above",
            actor="trading",
            context={
                "strategy": "level-scalp",
                "mode": "paper",
                "feed": "eurusd",
                "side": "buy",
                "risk_money": 20.0,
                "reward_to_risk": 1.4,
            },
        )
        await outcome(
            book,
            ref,
            "eurusd closed +40.00 from 1.1",
            actor="trading",
            context={
                "profit": 40.0,
                "seconds": 300,
                "reason": "target",
                "exit_source": "broker",
                # What a rebuilt intent spreads over the decision's own figure.
                "risk_money": 0.0,
            },
        )
    found = tr.trades(tmp_path / "j.db")
    assert len(found) == 1
    assert found[0].risk_money == pytest.approx(20.0)
    assert found[0].r == pytest.approx(2.0)


async def test_a_trade_with_no_risk_anywhere_is_still_skipped(tmp_path):
    """The fallback reaches for the decision's figure, not for any figure: a
    trade neither record sized is still not scoreable, and counting it at zero
    risk would land as an infinite R."""
    from till_infinity.journal import decide, outcome

    async with Journal(tmp_path / "j.db") as book:
        ref = await decide(
            book,
            "paper: buy 0.05 eurusd @ 1.1",
            rationale="up from above",
            actor="trading",
            context={"strategy": "level-scalp", "mode": "paper", "feed": "eurusd", "side": "buy"},
        )
        await outcome(
            book,
            ref,
            "eurusd closed +40.00 from 1.1",
            actor="trading",
            context={"profit": 40.0, "seconds": 300, "reason": "target", "risk_money": 0.0},
        )
    assert tr.trades(tmp_path / "j.db") == []


async def test_a_small_sample_is_refused_rather_than_characterised(tmp_path):
    """A 70% win rate over ten trades is a coin that came up heads seven times."""
    async with Journal(tmp_path / "j.db") as book:
        for index in range(10):
            await a_closed_trade(book, profit=10.0 if index < 7 else -20.0, at=4400.0 + index)
    report = tr.build(tmp_path / "j.db")
    assert report.overall.count == 10
    assert not report.enough
    assert "too few to characterise" in report.overall.verdict()


async def test_a_large_enough_sample_is_characterised(tmp_path):
    async with Journal(tmp_path / "j.db") as book:
        for index in range(tr.ENOUGH + 5):
            await a_closed_trade(book, profit=10.0 if index % 2 else -20.0, at=4400.0 + index)
    report = tr.build(tmp_path / "j.db")
    assert report.enough
    assert "won" in report.overall.verdict()
    assert "R mean" in report.overall.verdict()


async def test_trades_are_grouped_by_strategy(tmp_path):
    async with Journal(tmp_path / "j.db") as book:
        await a_closed_trade(book, strategy="level-scalp", profit=20.0, at=4400.0)
        await a_closed_trade(book, strategy="approach-scalp", profit=-20.0, at=4401.0)
    report = tr.build(tmp_path / "j.db")
    assert report.by_strategy["level-scalp"].total_r == pytest.approx(1.0)
    assert report.by_strategy["approach-scalp"].total_r == pytest.approx(-1.0)


async def test_a_trade_with_no_risk_recorded_is_skipped_not_counted_as_zero(tmp_path):
    """Counting it would land as an infinite R or a silent zero."""
    from till_infinity.journal import decide, outcome

    async with Journal(tmp_path / "j.db") as book:
        ref = await decide(
            book,
            "paper: buy 0.05 gold",
            rationale="adopted",
            actor="trading",
            context={"strategy": "level-scalp", "feed": "gold", "risk_money": 0.0},
        )
        await outcome(book, ref, "closed", actor="trading", context={"profit": 5.0})
    assert tr.trades(tmp_path / "j.db") == []


async def test_declines_are_tallied_per_gate(tmp_path):
    """A gate that never fires does nothing; one that always fires is mis-set."""
    from till_infinity.journal import observe

    async with Journal(tmp_path / "j.db") as book:
        # Distinct titles for the same reason `a_closed_trade` varies its
        # price: two identical titles in one tick are one journal entry.
        for index, gate in enumerate(("news", "news", "exposure")):
            await observe(
                book,
                f"declined buy gold @ {4400 + index} ({gate})",
                rationale=gate,
                actor="trading",
                context={"gate": gate, "strategy": "level-scalp"},
            )
    counted = tr.declines(tmp_path / "j.db")
    assert counted["news"] == 2
    assert counted["exposure"] == 1


async def test_paper_and_live_are_not_averaged_together(tmp_path):
    """Simulated fills and real ones describe different things."""
    from till_infinity.journal import decide, outcome

    async with Journal(tmp_path / "j.db") as book:
        await a_closed_trade(book, profit=20.0)
        ref = await decide(
            book,
            "live: buy 0.05 gold",
            rationale="up",
            actor="trading",
            context={"strategy": "level-scalp", "mode": "live", "feed": "gold", "risk_money": 20.0},
        )
        await outcome(book, ref, "closed", actor="trading", context={"profit": -20.0})

    assert tr.build(tmp_path / "j.db", mode="paper").overall.count == 1
    assert tr.build(tmp_path / "j.db", mode="live").overall.count == 1
    assert tr.build(tmp_path / "j.db").overall.count == 2


def test_a_strategy_separates_where_it_triggers_from_where_its_bias_comes_from():
    """Entry fixes the stop; context says whether the trigger is worth taking.

    The gap between them is the point. A swing anchored on the daily does not
    have to enter on the daily - dropping to 15m buys a tighter stop for the
    same idea, which is risk reduction rather than a different trade.
    """
    made = settings()
    swing = td.STRATEGIES["swing-level"](made)
    # Triggers below the hour, judged on 1h-4h. The gap is the whole point.
    assert swing.intervals == ("1m", "3m", "5m", "15m", "30m")
    assert swing.anchors == ("1h", "2h", "4h")
    # Its lowest trigger is well below its highest anchor.
    assert swing.intervals[0] not in ("1d", "1w")
    assert swing.hold_seconds > td.STRATEGIES["level-scalp"](made).hold_seconds


def test_a_strategy_that_needs_an_anchor_refuses_without_one():
    made = settings()
    swing = td.STRATEGIES["swing-level"](made)

    # Entered on 15m with only 15m agreeing: nothing on 1h-4h sees it.
    lonely = signal(interval="15m", confluence=["15m"])
    swing.observe(lonely)
    got = swing.consider(
        lonely, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "unanchored"


def test_a_strategy_declares_its_own_timeframes():
    """The limit belongs to the strategy, not to the module.

    Restricting the service restricts every strategy at once, which is a blunt
    instrument: a scalper has no business on a 1w level, and a panel of agents
    can be told the timeframe and asked to weigh it.
    """
    made = settings()
    assert td.STRATEGIES["level-scalp"](made).intervals == ("1m", "3m", "5m", "15m", "30m")
    # approach-scalp is a swing, and swings now enter across the fast band too -
    # widened 2026-09-22, see research/break-trade.md. It still stops below 1h,
    # because 1h is where its context starts.
    assert td.STRATEGIES["approach-scalp"](made).intervals == ("1m", "3m", "5m", "15m", "30m")


def fade(**over):
    return td.STRATEGIES["fade-to-value"](settings(**over))


def test_agreement_rebuilds_the_trade_rather_than_sizing_it_up():
    """Two strategies on one signal is one idea found twice.

    Sizing up on agreement doubles a position on a single thesis, which is what
    the per-instrument limit exists to prevent. What agreement buys is a
    better-built trade: the furthest stop any of them wanted, because being
    stopped before the move arrived is the failure measured most, and the
    nearest target, because unreached targets are what a wide stop costs.
    """
    bus = Bus()
    made = settings(live=True, evaluate_all=True, consensus_min=2)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))

    base = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4396.0,
        target=4410.0,
        risk_money=20.0,
    )
    others = [
        # Agrees, and would have used a wider stop and a nearer target.
        ("sweep-aware", replace(base, stop=4393.0, target=4406.0)),
        # Disagrees on side - must be ignored entirely.
        ("fade-to-value", replace(base, side=Side.SELL, stop=4404.0, target=4390.0)),
    ]
    built, agreed = trader._agree(base, others)
    assert agreed == ["sweep-aware"], "only the side that agreed counts"
    assert built.stop == pytest.approx(4393.0), "the safest stop on offer"
    assert built.target == pytest.approx(4406.0), "the most reachable target"
    # Deliberately the worst reward-to-risk of the versions available, which
    # min_reward_to_risk then judges on its merits.
    assert (built.target - built.entry) / (built.entry - built.stop) < (
        (base.target - base.entry) / (base.entry - base.stop)
    )


def _htf():
    """`swing-level`, which absorbed `high-timeframe` when it was removed as a
    near-duplicate: they shared entries, context and the requirement that a
    higher timeframe agree, and the resting entry and horizon-scaled
    protection moved across."""
    return strategy("swing-level")


def test_style_both_changes_nothing():
    """The default. Whatever TRADING_STRATEGIES selected is what runs."""
    engines = td_strategy.build(["snap", "swing-level", "runner"], settings())
    kept, dropped = td_strategy.by_style(engines, "both")
    assert [e.name for e in kept] == ["snap", "swing-level", "runner"]
    assert dropped == []


def test_style_picks_one_kind_at_a_time():
    engines = td_strategy.build(
        ["snap", "level-scalp", "swing-level", "runner", "fade-to-value"], settings()
    )
    scalps, _ = td_strategy.by_style(engines, "scalp")
    swings, _ = td_strategy.by_style(engines, "swing")
    assert sorted(e.name for e in scalps) == ["level-scalp", "snap"]
    assert sorted(e.name for e in swings) == ["fade-to-value", "runner", "swing-level"]


def test_style_none_stands_everything_down():
    engines = td_strategy.build(["snap", "swing-level"], settings())
    kept, dropped = td_strategy.by_style(engines, "none")
    assert kept == []
    assert sorted(e.name for e in dropped) == ["snap", "swing-level"]


def test_a_typo_in_the_style_runs_everything_rather_than_nothing():
    """A mis-set base-rate floor once refused 99 signals of 99 and stopped all
    trading. An environment typo must not be able to do that again."""
    engines = td_strategy.build(["snap", "swing-level"], settings())
    kept, dropped = td_strategy.by_style(engines, "scalps")
    assert sorted(e.name for e in kept) == ["snap", "swing-level"]
    assert dropped == []


def test_the_names_do_not_decide_the_style():
    """approach-scalp and fade-to-value both hold forty-five minutes, longer
    than max_hold, and are swings wearing a scalp's name."""
    engines = {e.name: e for e in td_strategy.build(None, settings())} or {}
    for name in ("approach-scalp", "fade-to-value"):
        made = td_strategy.build([name], settings())[0]
        assert made.style == "swing", name
        assert made.hold_seconds > settings().max_hold
    del engines


async def test_running_no_strategies_is_announced_not_silent():
    """A service that connects, warms every estimator and takes nothing looks
    identical to a fault unless it says so."""
    trader = Trader(Bus(), settings=settings(style="none"))
    await trader.start()
    assert trader.strategies == []
    assert sorted(e.name for e in trader.stood_down)


async def test_a_scalp_only_service_takes_no_swings():
    trader = Trader(
        Bus(),
        settings=settings(style="scalp", strategies=("level-scalp", "swing-level", "runner")),
    )
    await trader.start()
    assert [e.name for e in trader.strategies] == ["level-scalp"]
    assert sorted(e.name for e in trader.stood_down) == ["runner", "swing-level"]


def test_the_origin_swing_needs_both_ends():
    """One origin gives an entry with no structural target, which is the
    ordinary push trade every other strategy here already takes."""
    engine = strategy("origin-swing")
    only_one = _bracketed()
    del only_one["features"]["origin_above_low"]
    got = engine.consider(
        only_one, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "no_bracket"


def test_price_between_the_origins_is_not_yet_a_trade():
    """The trade is taken *at* an origin, not in the space between them."""
    engine = strategy("origin-swing")
    got = engine.consider(
        _bracketed(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "not_at_origin"


def test_reaching_the_lower_origin_is_a_long_to_the_upper_one():
    engine = strategy("origin-swing")
    call = _bracketed(features={"origin_below_vol": 0.1})
    got = engine.consider(
        call, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.BUY
    # The far edge of the origin above, not a multiple of the modelled push.
    assert got.target == pytest.approx(4410.0)


def test_reaching_the_upper_origin_is_a_short_to_the_lower_one():
    engine = strategy("origin-swing")
    call = _bracketed(features={"origin_above_vol": 0.1})
    got = engine.consider(
        call, spec=GOLD, tick=Tick("XAUUSD", bid=4409.5, ask=4410.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.target == pytest.approx(4391.0)


def test_the_side_comes_from_the_origin_not_the_published_direction():
    """The published direction is about the level, and this strategy is not
    trading the level."""
    engine = strategy("origin-swing")
    call = _bracketed(direction="down", features={"origin_below_vol": 0.1})
    got = engine.consider(
        call, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.BUY


def test_the_facing_side_does_not_leak_into_the_next_call():
    """`quality` runs before `orient` and resets it, so a refused call cannot
    hand its side to the one after."""
    engine = strategy("origin-swing")
    at_low = _bracketed(features={"origin_below_vol": 0.1})
    engine.consider(at_low, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0)
    assert engine._facing is Side.BUY
    engine.consider(
        _bracketed(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert engine._facing is None


def test_the_origin_swing_enters_fast_and_judges_slow():
    engine = strategy("origin-swing")
    assert engine.style == "swing"
    assert engine.intervals == ("1m", "3m", "5m", "15m", "30m")
    assert engine.context == ("1h", "2h", "4h")
    assert engine.candle_interval == "4h"
    assert engine.needs_both_witnesses is True
    assert engine.needs_context is True


def test_the_stop_clears_the_origin_it_is_trading():
    """Inside the zone is where the wicks are. A stop placed there is taken out
    by the very rejection the trade exists to trade.

    Anchoring on the level instead put the stop on the wrong side of the fill
    outright: a long at the lower origin, 2v under the level, got a stop above
    its own entry and was refused as already through.
    """
    engine = strategy("origin-swing")
    call = _bracketed(features={"origin_below_vol": 0.1})
    got = engine.consider(
        call, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    # Below the zone's far edge (4386) by half a unit of clearance (0.5 * 4.40).
    assert got.stop < 4386.0
    assert got.stop == pytest.approx(4383.8)
    assert got.stop < got.entry < got.target


def test_the_short_stop_clears_the_upper_origin():
    engine = strategy("origin-swing")
    call = _bracketed(features={"origin_above_vol": 0.1})
    got = engine.consider(
        call, spec=GOLD, tick=Tick("XAUUSD", bid=4409.5, ask=4410.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.stop > 4415.0
    assert got.target < got.entry < got.stop


async def test_the_ensemble_reading_lands_where_strategies_look():
    """Into `features`, not the top level. `_features` reads
    `payload["features"]` and nothing else, so a top-level key is invisible to
    every strategy - the gate reads zero and refuses nothing while looking
    configured. That has happened here before, with `pressure_vol`."""
    trader = Trader(Bus(), settings=settings())
    await trader.start()
    # The volatility unit comes from the last signal for this feed, so the
    # accumulators are inert until one has arrived.
    trader._vol_bps["gold"] = 10.0
    price = 4400.0
    for step in range(0, 3600, 30):
        price += 1.0
        await trader.handle(
            Message(
                topic=QUOTES,
                payload={
                    "feed": "gold",
                    "bid": price - 0.5,
                    "ask": price + 0.5,
                    "time": NOW + step,
                },
            )
        )
    payload = signal()
    trader._hand_over_pressure("gold", payload)

    assert "momentum_agree" in payload["features"]
    assert "momentum_agree" not in payload
    assert payload["features"]["momentum_ready"] > 0


def test_the_swing_refuses_a_trade_the_timeframes_disagree_with():
    """One timeframe moving alone is what a touch looks like."""
    engine = strategy("origin-swing")
    against = _bracketed(
        features={
            "origin_below_vol": 0.1,
            "momentum_ready": 5.0,
            "momentum_agree": -1.0,  # every sub-hour timeframe pointing down
        }
    )
    got = engine.consider(
        against, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "momentum"


def test_the_swing_takes_a_trade_the_timeframes_are_behind():
    engine = strategy("origin-swing")
    behind = _bracketed(
        features={
            "origin_below_vol": 0.1,
            "momentum_ready": 5.0,
            "momentum_agree": 1.0,
        }
    )
    got = engine.consider(
        behind, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.BUY


def test_a_cold_ensemble_does_not_refuse_anything():
    """A gate that refuses because the reading is missing is a gate that stops
    all trading on a fresh container, which has happened here once already."""
    engine = strategy("origin-swing")
    cold = _bracketed(features={"origin_below_vol": 0.1})
    assert "momentum_ready" not in cold["features"]
    got = engine.consider(
        cold, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Intent)


def test_a_stale_origin_is_refused():
    """Measured over 3,412 returns: the first holds 63.5%, the second 55.6%.
    Freshness helps, so the swing prefers a fresh origin."""
    engine = strategy("origin-swing")
    worn = _bracketed(features={"origin_below_vol": 0.1, "origin_below_revisits": 4.0})
    got = engine.consider(
        worn, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "stale_origin"


def test_a_first_return_still_trades():
    engine = strategy("origin-swing")
    fresh = _bracketed(features={"origin_below_vol": 0.1, "origin_below_revisits": 1.0})
    got = engine.consider(
        fresh, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Intent)


def test_an_unknown_revisit_count_is_not_a_stale_origin():
    """A missing count is an unknown origin, not a worn one. Refusing on it
    would stand the strategy down on every feed whose origins have not been
    published yet."""
    engine = strategy("origin-swing")
    unknown = _bracketed(features={"origin_below_vol": 0.1})
    del unknown["features"]["origin_below_revisits"]
    got = engine.consider(
        unknown, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0
    )
    assert isinstance(got, Intent)


def test_a_refused_stale_origin_does_not_leak_its_side():
    engine = strategy("origin-swing")
    worn = _bracketed(features={"origin_below_vol": 0.1, "origin_below_revisits": 9.0})
    engine.consider(worn, spec=GOLD, tick=Tick("XAUUSD", bid=4390.5, ask=4391.5), equity=10_000.0)
    assert engine._facing is None


def test_swing_level_aims_past_the_push_and_is_given_time_to_get_there():
    """Asked for on 2026-09-02: wider take-profit and trail.

    The hold moves with them. `runner` is the worked example of the failure
    this avoids - it aims past the push and then closes 16 of 26 trades on a
    four-hour clock, so the target it exists for is never reached.
    """
    import till_infinity.trading as td

    engine = td.STRATEGIES["swing-level"](settings())
    assert engine.target_multiple == 2.5
    assert engine.trail_vol == 4.0
    assert engine.hold_seconds == 24 * 3_600.0
    # Still distinguishable from `runner`, which pushes the same idea further.
    assert engine.target_multiple < td.STRATEGIES["runner"].target_multiple


def test_a_wider_target_is_useless_past_the_ceiling():
    """The hold has to survive `max_hold_swing`, or the clock undoes the aim."""
    import till_infinity.trading as td

    engine = td.STRATEGIES["swing-level"](settings(max_hold_swing=48 * 3_600.0))
    assert engine.hold_for("1h") == 24 * 3_600.0
    cramped = td.STRATEGIES["swing-level"](settings(max_hold_swing=2 * 3_600.0))
    assert cramped.hold_for("1h") == 2 * 3_600.0


def test_the_learned_ranking_survives_a_restart(tmp_path):
    """The only genuinely *learned* state in this service. Pressure and trend
    rebuild from the market in minutes; a ranking of the strategies against
    each other does not."""
    made = settings(state_dir=tmp_path)
    trader = Trader(Bus(), settings=made)
    trader.policy.ledger.observe("gold:1h", "thesis-only", 1.25)
    trader.policy.ledger.observe("gold:1h", "runner", -0.5)
    before = trader.policy.ledger.score("gold:1h", "thesis-only")
    trader._remember_marks()

    after = Trader(Bus(), settings=made)
    after._recall_marks()

    got = after.policy.ledger.score("gold:1h", "thesis-only")
    assert got is not None
    assert got.mean == pytest.approx(before.mean)


def test_an_untaken_intent_carries_the_regime_it_was_found_in():
    """`research/choosing.md` measured 536 of these and found the strategies
    indistinguishable pooled - -0.172, -0.179, -0.190R. The interesting
    question is conditional, and it could not be asked because `regime` is on
    every level call and was dropped here."""
    trader = Trader(Bus(), settings=settings())
    trader._remember_untaken(
        "gold", "runner", intent(volume=1.0), "15m", 3600.0, 100.0, regime=2.0, market="trending"
    )

    kept = trader._untaken["gold"][-1]
    assert kept.regime == 2.0
    assert kept.market == "trending"


def test_an_untaken_intent_without_a_regime_defaults_rather_than_raising():
    """The classifier is not warm on a fresh feed, and a counterfactual is
    still worth keeping."""
    trader = Trader(Bus(), settings=settings())
    trader._remember_untaken("gold", "runner", intent(volume=1.0), "15m", 3600.0, 100.0)

    assert trader._untaken["gold"][-1].regime == 0.0


def test_the_stale_clock_respects_a_strategy_own_horizon():
    """`origin-swing` declares a four-hour hold and was being closed `stale` at
    the 1,200s floor - **8% of the horizon it was opened for**. Its first live
    trade closed at 1,249s having peaked at 0.007R.

    A trade that has not moved after a third of its own intended hold is going
    nowhere. After 8% of it, nobody knows yet."""
    from till_infinity.trading.service import STALE_SHARE

    made = settings(stale_after=1200.0)
    trader = Trader(Bus(), settings=made)

    swing = mock.Mock()
    swing.intent = replace(_intent(), hold=4 * 3600.0)
    scalp = mock.Mock()
    scalp.intent = replace(_intent(), hold=1800.0)

    assert trader._stale_after(swing) == pytest.approx(4 * 3600.0 * STALE_SHARE)
    assert trader._stale_after(swing) > 4000, "eighty minutes, not twenty"
    # A fast strategy's third is below the floor, so the floor still wins and
    # nothing that was working changes.
    assert trader._stale_after(scalp) == pytest.approx(1200.0)


def test_a_strategy_may_set_its_own_cooldown_without_touching_the_deployment():
    """**One global cooldown cannot fit a 120-second scalp and a day-long swing.**

    900s against a scalp that holds two minutes is a seven-to-one throttle; the
    same number against a swing is nothing at all.
    """
    from till_infinity.trading.risk import Limits

    guard = Guard(settings(loss_cooldown=900.0))
    guard.roll(10_000.0, now=1_000.0)
    guard.record("gold", -20.0, 9_980.0, now=1_000.0)

    # The deployment's 900s still refuses at +100s.
    assert guard.allows(intent(), positions=[], now=1_100.0).gate == "cooldown"
    # A strategy naming 60s of its own is free by then.
    quick = Limits(by="snap", loss_cooldown=60.0)
    assert guard.allows(intent(), positions=[], now=1_100.0, limits=quick) is None
    # And one naming a longer wait is still held.
    slow = Limits(by="swing-level", loss_cooldown=3_600.0)
    assert guard.allows(intent(), positions=[], now=1_100.0, limits=slow).gate == "cooldown"


def test_the_share_reaches_the_real_sizing_path():
    """**Behaviour, not just a constant.**

    The three sizing call sites all multiply by `risk_scale`, so folding the
    share in there is what makes it real. Two live strategies of different
    styles, the same empty features so every other multiplier is off, must now
    differ - and by exactly their styles' ratio.
    """
    from till_infinity.trading.strategies.strategy import RISK_SHARE_BY_STYLE, build

    made = {s.name: s for s in build(["level-scalp", "swing-level"], settings())}
    scalp, swing = made["level-scalp"], made["swing-level"]
    assert scalp.style == "scalp", scalp.style
    assert swing.style == "swing", swing.style

    args = {
        "feed": "gold",
        "features": {},
        "positions": (),
        "equity": 10_000.0,
        "peak": 10_000.0,
        "interval": "15m",
        "side": Side.BUY,
    }
    fast, slow = scalp.risk_scale(**args), swing.risk_scale(**args)

    assert slow < fast, (fast, slow)
    want = RISK_SHARE_BY_STYLE["swing"] / RISK_SHARE_BY_STYLE["scalp"]
    assert abs((slow / fast) - want) < 1e-9, (slow / fast, want)


def test_each_strategy_reports_limits_naming_itself():
    """`Guard` is handed these per decision, so the name has to be right or a
    refusal is attributed to the wrong strategy."""
    from till_infinity.trading.strategies.strategy import build

    for engine in build(["level-scalp", "swing-level", "snap"], settings()):
        assert engine.limits.by == engine.name, (engine.limits.by, engine.name)


def test_fade_to_value_enters_at_the_hour_and_is_judged_above_it():
    """The swing contract this class states at the top: "entry on 1h; 2h, 4h ...
    are compulsory context". 1h was added as an entry on 2026-10-04 and left the
    context set the same day, so the two halves still do different jobs."""
    fade = td.STRATEGIES["fade-to-value"]
    assert "1h" in fade.entries
    assert fade.context == ("2h", "4h")


#: Every strategy whose live geometry argued for a reward floor, and the
#: measured median reward-to-risk that argued for it. See
#: `Strategy.reward_floor`.
FLOORED = {
    "thesis-only": 0.40,
    "approach-scalp": 0.51,
    "level-scalp": 0.55,
    "inverse": 0.60,
    "momentum-scalp": 0.61,
    "snap": 0.94,
    "cycle-scalp": 1.03,
    "fade-to-value": 1.27,
    "runner": 1.49,
    "confluence-scalp": 2.69,
}

#: The one strategy left without a floor on purpose. It placed the 0.22 EURUSD
#: short, so this is not an exemption for good behaviour - it is the only
#: profitable strategy of size, the floor would bind on 5% of its calls, and the
#: live record does not support the claim that raising reward-to-risk improves
#: outcomes. See `Strategy.reward_floor`.
EXEMPT = "sweep-aware"

#: Registered, and with no live decisions in the journal to quote a median
#: from, so their floor rests on the arithmetic alone.
FLOORED_UNMEASURED = (
    # Its floor comes from a harness rather than from arithmetic - a 38.1% win
    # rate over 905 trades implies a breakeven of 1.625 - but it has no live
    # decisions in the journal either, which is what this table is about.
    "statespace-surprise",
)

#: The two that take their floor from `opportunity.Shape` instead of a class
#: attribute, because they are a parameter space rather than a point in one.
SHAPED = ("opportunity", "ride")


def test_the_strategies_with_broken_geometry_carry_a_floor():
    """**1.2 since 2026-10-08, and the number is not arbitrary.** Over 2,014
    closed positions from 2026-09-07 the desk wins 46.6%, which needs a
    reward-to-risk of **1.14** to break even - so the old floor of 1.0 was
    binding on most trades and pinning them at a ratio that loses. The live
    record shows it binding: the share of decisions at RR >= 1.0 went 54.9% to
    88.6% when the floor landed, and the floored strategies sit at a median of
    exactly 1.000.

    It stops at 1.2 deliberately. The breakeven table holds the win rate fixed
    and a further target lowers it, so this clears 1.14 with a margin and goes
    no further than the arithmetic supports.
    """
    made = settings()
    # **Per strategy from 2026-10-08**, each from its own win rate shrunk toward
    # the desk's. Pinned as the relation rather than a table of literals: every
    # floor must clear the ratio at which that strategy's own hit rate breaks
    # even, once the rate is shrunk toward the house figure.
    desk, prior = 0.467, 150.0
    live = {
        "fade-to-value": (118, 0.407),
        "cycle-scalp": (970, 0.439),
        "inverse": (116, 0.448),
        "snap": (57, 0.491),
        "confluence-scalp": (66, 0.515),
        "thesis-only": (303, 0.535),
        "level-scalp": (41, 0.561),
    }
    for name, (n, p) in live.items():
        shrunk = (n * p + prior * desk) / (n + prior)
        need = (1 - shrunk) / shrunk
        got = td.STRATEGIES[name](made).reward_floor
        assert got >= need - 0.05, f"{name}: floor {got} under its breakeven {need:.3f}"
        # and not wildly over it - a floor is a floor, not a target policy
        assert got <= need + 0.20, f"{name}: floor {got} far above its breakeven {need:.3f}"
    for name, measured in FLOORED.items():
        engine = td.STRATEGIES[name](made)
        assert engine.reward_floor > 0.0, f"{name} (median RR {measured})"
    # The desk's own breakeven is what sets it, so pin that relation too: a
    # floor under 1.14 would be a floor that loses at the measured hit rate.
    # `thesis-only` wins 53.5%, so its own breakeven is 0.87 and it is the one
    # strategy whose floor is *below* the desk's. That is the per-strategy table
    # working, not a floor that slipped.
    assert td.STRATEGIES["fade-to-value"](made).reward_floor > (1 - 0.466) / 0.466


def test_a_floor_moves_the_target_out_to_meet_the_real_risk():
    engine = strategy("fade-to-value")
    # A sell: entry 100, stop 110, so the risk is 10 whatever was proposed.
    # Risk 10, floor 1.2, so the target lands 12 away - not 10. Written off the
    # declared floor so it moves with it rather than pinning a stale literal.
    floor = engine.reward_floor
    got = engine.floored_target(GOLD, td.Side.SELL, 100.0, 110.0, 98.0)
    assert got == pytest.approx(100.0 - 10.0 * floor)
    # And a buy, the other way.
    got = engine.floored_target(GOLD, td.Side.BUY, 100.0, 90.0, 102.0)
    assert got == pytest.approx(100.0 + 10.0 * floor)


def test_a_floor_never_pulls_a_target_in():
    """The one thing it must not do. A target already past the floor is a
    strategy's own reading of how far price goes, and a *floor* that shortened
    it would be a cap wearing the wrong name."""
    engine = strategy("fade-to-value")
    assert engine.floored_target(GOLD, td.Side.SELL, 100.0, 110.0, 80.0) == 80.0
    assert engine.floored_target(GOLD, td.Side.BUY, 100.0, 90.0, 130.0) == 130.0


def test_a_floor_measures_risk_from_the_fill_and_not_the_proposed_stop():
    """The whole reason this runs late.

    `fade-to-value` sold EURUSD on 2026-10-05 at 1.11870 with its stop at
    1.12311 and its target at 1.11772: 44.1 pips of risk against 9.8 of
    reward, 0.22, needing an 82% win rate. The stop was proposed at 1.69
    volatility units and the level's zone widened it to 21.7, so anything that
    floored against the *proposed* stop would have called that trade fine.
    """
    engine = strategy("fade-to-value")
    entry, stop, target = 1.11870, 1.12311, 1.11772
    assert abs(target - entry) / abs(entry - stop) == pytest.approx(0.222, abs=0.001)
    got = engine.floored_target(EURGBP, td.Side.SELL, entry, stop, target)
    floor = engine.reward_floor
    assert abs(got - entry) / abs(entry - stop) == pytest.approx(floor, abs=0.001)
    # Below the old target, because this is a sell.
    assert got == pytest.approx(entry - abs(entry - stop) * floor, abs=1e-5)
    assert got < target


def test_a_zero_risk_geometry_is_left_alone_rather_than_divided_by():
    engine = strategy("fade-to-value")
    assert engine.floored_target(GOLD, td.Side.SELL, 100.0, 100.0, 99.0) == 99.0


def test_a_magic_resolves_through_strategy_for_and_not_by_hand():
    """The arithmetic that cost a day.

    `magic_for` is `base + 1 + MAGIC_ORDER.index(name)` and `DEFAULT_MAGIC` is
    777701, so reading a magic against 777700 shifts **every** strategy to its
    neighbour in `MAGIC_ORDER` - and because every neighbour is a real strategy
    name, the resulting attribution table reads as a finding rather than as a
    bug. A whole per-strategy broker breakdown was reported that way on
    2026-10-05: `sweep-aware`'s positions were labelled `fade-to-value`,
    `cycle-scalp`'s were labelled `cycle-turn`, and so on down the list.
    """
    from till_infinity.trading.config import DEFAULT_MAGIC, magic_for, strategy_for

    assert DEFAULT_MAGIC == 777_701
    # Round-trips for every named strategy, which is the only check that
    # matters and the one a hand-written base cannot pass.
    for name in td.STRATEGIES:
        magic = magic_for(DEFAULT_MAGIC, name)
        assert strategy_for(DEFAULT_MAGIC, magic) == name, name
    # And the off-by-one is not a near miss: it names a *different* strategy.
    wrong = strategy_for(777_700, magic_for(DEFAULT_MAGIC, "sweep-aware"))
    assert wrong == "fade-to-value"
    assert wrong != "sweep-aware"




def test_fair_value_is_the_best_evidenced_level_not_the_nearest():
    """An estimate that moved every time price drifted would not be an estimate."""
    engine = fade()
    # A nearby level nobody has traded, and a far one with real history.
    engine.observe(signal(features={"level": 4402.0, "record_n": 2.0}))
    engine.observe(signal(features={"level": 4380.0, "record_n": 40.0}))
    unit = 4400.0 * 10.0 / 10_000
    value = engine.fair_value("gold", unit, 4400.0)
    assert value is not None
    assert value.price == 4380.0


def test_a_price_below_fair_value_is_a_long():
    engine = fade()
    engine.observe(swing(features={"level": 4425.0, "record_n": 40.0}))
    engine.observe(swing())
    got = engine.consider(
        swing(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.BUY
    assert got.target < 4425.0  # short of fair value
    assert "below fair value" in got.reason


def test_a_price_above_fair_value_is_a_short():
    engine = fade()
    engine.observe(swing(features={"level": 4375.0, "record_n": 40.0}))
    engine.observe(swing())
    got = engine.consider(
        swing(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.target > 4375.0
    assert "above fair value" in got.reason


def test_a_price_at_fair_value_has_nothing_to_say():
    """Inside one volatility unit the distance is the noise of the estimate."""
    engine = fade()
    engine.observe(swing(features={"level": 4402.0, "record_n": 40.0}))
    engine.observe(swing())
    got = engine.consider(
        swing(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "at_value"


def test_a_level_with_too_little_history_is_not_a_valuation():
    engine = fade()
    # The only level it knows of has been touched once, so there is nothing to
    # price against. The triggering call is deliberately not observed either.
    engine.observe(swing(features={"level": 4425.0, "record_n": 1.0}))
    got = engine.consider(
        swing(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "no_value"


def test_the_fade_stop_sits_beyond_the_level_price_is_standing_at():
    """That is where this reading of value is wrong."""
    engine = fade()
    engine.observe(swing(features={"level": 4425.0, "record_n": 40.0}))
    engine.observe(swing())
    got = engine.consider(
        swing(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    # The triggering level is 4400; the stop is below it, not below fair value.
    assert got.stop < 4400.0
    assert got.stop > 4375.0 - 40


def test_the_side_is_arithmetic_once_the_valuation_exists():
    """Nothing is forecast: the same signal gives opposite sides on the
    valuation alone."""
    up, down = fade(), fade()
    up.observe(swing(features={"level": 4425.0, "record_n": 40.0}))
    down.observe(swing(features={"level": 4375.0, "record_n": 40.0}))
    for engine in (up, down):
        engine.observe(swing())
    tick = Tick("XAUUSD", bid=4399.5, ask=4400.5)
    long = up.consider(swing(), spec=GOLD, tick=tick, equity=10_000.0)
    short = down.consider(swing(), spec=GOLD, tick=tick, equity=10_000.0)
    assert long.side is Side.BUY
    assert short.side is Side.SELL
    # Identical signal, identical direction field on it: only the valuation differs.
    assert swing()["direction"] == "up"


def test_the_swing_trade_requires_a_high_timeframe():
    """Not a preference. A 15m trigger held for hours on nothing but 15m
    agreement is a fast trade wearing a swing's patience.

    The analysis frame narrowed to 1h-4h on 2026-09-03: the break rate flattens
    past 30m, so 1d and 1w cost signals without buying reliability."""
    engine = _htf()
    assert engine.needs_context is True
    assert all(t in ("1h", "2h", "4h") for t in engine.context)
    # And the trigger sits strictly below every timeframe that judges it.
    assert all(SECONDS[e] < min(SECONDS[c] for c in engine.context) for e in engine.entries)


def test_a_fast_swing_trigger_still_needs_its_stop_scaled_to_the_hold():
    """**This test used to assert a 15m floor, and the floor is gone.**

    It was removed on 2026-09-22: the figure it rested on - "1m levels break
    57.9% of the time" - is a selection effect, measured only on resolutions
    lasting five minutes or more, and unconditionally the rate is 13.4%. See
    research/break-trade.md.

    But the *other* reason this test gave is untouched by that correction, and
    it is the one worth keeping: **the stop comes from the entry interval while
    the hold comes from the context**, so a 1m trigger on a multi-hour thesis
    gets a one-minute stop against a four-hour noise budget. Volatility grows
    like sqrt(t), so 240 bars of hold wants a stop about 15x one bar - and
    `max_stop_scale` caps the compensation at 3.0.

    So the residual risk is real and is **not** closed by the widening. What
    this now pins is that the machinery which mitigates it exists and is
    reachable, so the gap cannot be silently lost.
    """
    engine = _htf()
    fast = {"1m", "3m", "5m"}
    # The floor is deliberately gone.
    assert fast & set(engine.entries), "the fast band was re-floored without a note"
    # And the hold does not shrink to match, which is exactly why the stop has
    # to be scaled instead - see test_the_stop_floor_scales_with_how_long_it_must_last.
    assert engine.hold_for("1m") == engine.hold_for("4h")


def test_the_swing_hold_does_not_shrink_with_a_fast_trigger():
    """The thesis lives on the context timeframe, so bars of the *entry* would
    close a four-hour idea minutes after opening it."""
    engine = _htf()
    assert engine.hold_bars == 0.0
    # A 15m trigger gets the same hold a 4h trigger does.
    assert engine.hold_for("15m") == engine.hold_for("4h")


def test_the_swing_trade_is_not_capped_by_the_scalpers_hold():
    """max_hold is 1800s because that suits a one-minute thesis. Applied here
    it would close the trade inside the first bar.

    `hold_for` no longer takes a ceiling at all, which is the stronger form of
    this: a caller cannot hand a swing the scalp ceiling by mistake, and every
    caller used to.
    """
    engine = _htf()
    assert engine.hold_for("4h") > 1_800.0
    assert engine.ceiling > 1_800.0


def test_the_swing_trade_rests_its_entry_whatever_the_deployment_says():
    """Stated by the strategy, so it does not become a market order because a
    global happened to be zeroed."""
    assert _htf().pullback_fraction == 1.0




# From tests/test_scaling.py: the swing/scalp ceiling split and the preset recovery,
# which name the retired strategies directly.

def test_a_swing_and_a_scalp_have_different_ceilings():
    """`max_hold` was never a global cap - `hold_for` read it only when a
    strategy named no hold of its own, so every swing was governed by a
    hardcoded ClassVar no deployment could reach."""
    assert _engine("swing-level").ceiling == 21_600.0
    assert _engine("level-scalp").ceiling == 1_800.0


def test_each_ceiling_is_settable():
    assert _engine("swing-level", max_hold_swing=7_200.0).ceiling == 7_200.0
    assert _engine("level-scalp", max_hold=600.0).ceiling == 600.0


def test_the_swing_ceiling_falls_back_to_the_scalp_one():
    """Zero means unset, not "no hold at all" - a swing with no ceiling of its
    own is capped like everything else rather than uncapped."""
    assert _engine("swing-level", max_hold_swing=0.0).ceiling == 1_800.0


def test_every_swing_enters_strictly_below_the_frame_that_judges_it():
    """**This asserted a 15m floor on swing entries until 2026-09-22.**

    The floor is gone - the break-rate figure behind it was a selection effect,
    see research/break-trade.md - but the invariant that replaced it is the one
    that was doing the real work all along: a swing's trigger has to sit
    strictly below every timeframe in its `context`, or the gap that makes it a
    swing rather than a fast trade wearing a swing's patience has collapsed.

    That is also why the band stops at 30m and not at 1h: swing context starts
    at 1h, so a 1h entry would tie rather than clear.
    """
    import till_infinity.trading as td
    from till_infinity.shared.intervals import SECONDS

    for name, cls in td.STRATEGIES.items():
        if cls.style != "swing" or not cls.entries or not cls.context:
            continue
        slowest_trigger = max(SECONDS[e] for e in cls.entries)
        fastest_judge = min(SECONDS[c] for c in cls.context)
        assert slowest_trigger < fastest_judge, name


def test_origin_swing_analyses_on_the_same_frame_as_the_rest():
    """Was (4h, 1d) alone from 2026-09-01. Folded into the shared 1h-4h
    analysis frame on 2026-09-03: the break rate flattens past 30m - 2.8% at
    30m, 1.4% at 1h, 0.0% at 2h, 4.3% at 4h - so insisting on the daily buys
    nothing over 4h and costs most of the signals."""
    import till_infinity.trading as td

    assert td.STRATEGIES["origin-swing"].context == ("1h", "2h", "4h")


def test_every_higher_timeframe_strategy_lets_momentum_lead():
    """Asked for on 2026-09-03. On a higher timeframe a bar takes hours to
    close, so a trade taken on the candle alone is taken on evidence that has
    already happened."""
    import till_infinity.trading as td

    for name, cls in td.STRATEGIES.items():
        if cls.style == "swing":
            assert cls.momentum_leads is True, name


def test_every_swing_analyses_slow_and_enters_fast():
    """Asked for on 2026-09-03: analysis on the slow frames, entry on the fast
    ones, the exit horizon at an hour or more. It is what `swing-level` already
    argued for - the slow frame says *whether*, the fast one says *when* - and
    it was only true of the context, never of the entries.

    Written as the literal tuples, which made the two impossible to move
    together: `fade-to-value` was asked for a 1h entry on 2026-10-05, and a 1h
    entry is only coherent if its context starts at 2h. So the claim here is
    now the **relation** - every entry strictly faster than the fastest context
    frame - which is what "slow says whether, fast says when" actually means,
    and which the old literal only happened to satisfy.
    """
    import till_infinity.trading as td
    from till_infinity.shared.intervals import SECONDS
    from till_infinity.trading.config import Settings

    made = Settings()
    #: Allowed to enter at or above the hour. Named rather than skipped, so a
    #: second strategy widening that far trips this test and has to argue for
    #: it: 1h entries are the slowest band `swing` has, and the measurement
    #: behind the one exception is in research/docs/lrc-retest.md.
    at_the_hour = {"fade-to-value"}
    for name, cls in td.STRATEGIES.items():
        if cls.style != "swing":
            continue
        engine = cls(made)
        assert engine.entries, name
        assert engine.context, name
        slowest_entry = max(SECONDS[iv] for iv in engine.entries)
        fastest_context = min(SECONDS[iv] for iv in engine.context)
        assert slowest_entry < fastest_context, name
        # Widened below 15m on 2026-09-22 - see research/break-trade.md.
        assert "15m" in engine.entries, name
        if name not in at_the_hour:
            assert slowest_entry < SECONDS["1h"], name
            assert engine.entries == ("1m", "3m", "5m", "15m", "30m"), name
            assert engine.context == ("1h", "2h", "4h"), name
        # And the exit horizon stays at an hour or more, on every frame it
        # enters on - not just the one the old test happened to sample.
        for interval in engine.entries:
            assert engine.hold_for(interval) >= 3600.0, f"{name} on {interval}"


