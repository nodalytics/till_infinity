"""The level strategies' own tests, as they passed when the strategies retired.

Moved out of `tests/test_trading.py` on 2026-10-28 with `scalper.py`: `level-scalp`,
`cycle-scalp`, `confluence-scalp`, `momentum-scalp`, `snap`, `thesis-only`,
`inverse`, `sweep-aware`, and `LevelStrategy` itself - the base class every retired
strategy inherited, which is why this file went last.

These are tests **of the level geometry**: an anchored stop, a target held short of
the level, the two floors. The mechanics they used to carry - slots, exposure,
sizing, reconciliation, the journal - stayed in the suite on the vehicle in
`tests/mechanics.py`, which is why 400 tests did not move with them.

They need fixtures that stayed behind (`settings`, `signal`, `strategy`, `take`),
so reviving one means bringing those with it.
"""

def test_a_level_call_becomes_a_sized_trade():
    got = take("level-scalp")
    assert isinstance(got, Intent)
    assert got.side is Side.BUY
    assert got.stop == pytest.approx(4395.6)
    assert got.target == pytest.approx(4406.66)
    # 0.04 rather than 0.05 since 2026-09-22: `Settings.interval_weight` now
    # carries a measured default that brakes the sub-15m band to 0.8, because
    # every strategy's entries were widened down to 1m and the *live* record
    # for that band is -821.75 over 129 closes. The brake is deliberately
    # gentle - at 0.4 it stopped shrinking positions and started refusing them.
    assert got.volume == pytest.approx(0.04)
    assert got.reward_to_risk > 1.2


def test_a_down_call_sells_with_the_stop_above_the_level():
    got = take("level-scalp", signal(direction="down"))
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.stop > got.entry > got.target


def test_a_call_below_the_probability_floor_is_refused():
    got = take("level-scalp", signal(features={"probability": 0.51}))
    assert isinstance(got, Refusal)
    assert got.gate == "probability"


def test_a_call_with_no_volatility_unit_is_refused_not_guessed():
    """A stop from an assumed volatility is a stop in the wrong place, quietly."""
    got = take("level-scalp", signal(features={"vol_bps": 0.0}))
    assert isinstance(got, Refusal)
    assert got.gate == "volatility"


def test_a_call_with_no_direction_is_not_a_weak_buy():
    got = take("level-scalp", signal(direction=""))
    assert isinstance(got, Refusal)
    assert got.gate == "direction"


def test_a_timeframe_that_is_not_scalped_is_refused():
    got = take("level-scalp", signal(interval="1d"))
    assert isinstance(got, Refusal)
    assert got.gate == "interval"


def test_price_already_past_the_stop_is_not_a_trade_to_shrink():
    # A buy call at 4400 with the stop at 4395.6, but price is already at 4390.
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4389.5, ask=4390.5))
    assert isinstance(got, Refusal)
    assert got.gate == "through"


def test_confluence_scalp_refuses_a_level_no_higher_timeframe_sees():
    got = take("confluence-scalp", signal(confluence=["5m"]))
    assert isinstance(got, Refusal)
    assert got.gate == "unanchored"
    agreed = take("confluence-scalp", signal(confluence=["1h", "5m"]))
    assert isinstance(agreed, Intent)


def test_confluence_scalp_gives_the_stop_more_room():
    plain = take("level-scalp", signal(confluence=["1h", "5m"]))
    wider = take("confluence-scalp", signal(confluence=["1h", "5m"]))
    assert wider.stop < plain.stop  # a buy: further below the level


def test_confluence_scalp_carries_rides_exit():
    """It reached a mean peak of +1.401R over ten closes and realised -0.357R -
    the largest give-back on the book - while running no exit policy at all.

    These are the three numbers `ride` was measured to be best with over 31,820
    replayed touches, and the ones `sweep-aware` already carries."""
    engine = td.STRATEGIES["confluence-scalp"]
    assert engine.target_multiple == 6.0
    assert engine.trail_vol == 0.5
    assert engine.break_even_at == 1.0

    got = take("confluence-scalp", signal(confluence=["1h", "5m"]))
    assert isinstance(got, Intent)
    # The target has to be out where a trail, not a fixed level, ends the trade.
    plain = take("level-scalp", signal(confluence=["1h", "5m"]))
    assert got.target > plain.target


def test_confluence_scalp_wears_the_sweep_gate():
    """The presets table's own argument: `level-scalp` and `sweep-aware` are the
    same point apart from an entry gate, so a gate worth having is worth having
    here too."""
    near_pool = signal(
        confluence=["1h", "5m"],
        features={"liquidity_beyond_vol": 1.0, "risk_vol": 1.0},
    )
    got = take("confluence-scalp", near_pool)
    assert isinstance(got, Refusal)
    assert got.gate == "in_front"

    open_ground = signal(
        confluence=["1h", "5m"],
        features={"liquidity_beyond_vol": 20.0, "risk_vol": 1.0},
    )
    assert isinstance(take("confluence-scalp", open_ground), Intent)


def test_the_sweep_gate_judges_each_strategy_own_stop():
    """`confluence-scalp` stops 1.5x wider, so the same level can be open ground
    for `sweep-aware` and in front of the pool for this one. That is the gate
    working on the stop that would actually be placed, not an inconsistency."""
    from till_infinity.trading.strategies.scalper import ConfluenceScalp, SweepAware

    assert ConfluenceScalp.stop_multiple > SweepAware.stop_multiple

    # Sized so a 1.0x stop clears the pool and a 1.5x one does not.
    marginal = signal(
        confluence=["1h", "5m"],
        features={"liquidity_beyond_vol": 1.45, "risk_vol": 1.0},
    )
    assert isinstance(take("sweep-aware", marginal), Intent)
    refused = take("confluence-scalp", marginal)
    assert isinstance(refused, Refusal)
    assert refused.gate == "in_front"


def test_cycle_scalp_flips_to_the_clearer_side_when_the_pullback_extremes_are_worse():
    """The side with the cleaner pullback stop and trend-side target wins,
    even when the original signal called the other way."""
    engine = strategy("cycle-scalp")
    payload = signal(
        direction="up",
        features={
            "level": 4400.0,
            "zone_low": 4385.0,
            "zone_high": 4402.0,
            "origin_high": 4408.0,
            "origin_low": 4380.0,
            "risk_vol": 1.0,
            "expected_push_vol": 1.4,
            "vol_bps": 10.0,
            "probability": 0.72,
            "edge": 0.25,
            "base_rate_up": 0.47,
        },
    )
    got = engine.consider(
        payload,
        spec=GOLD,
        tick=Tick("XAUUSD", bid=4399.5, ask=4400.5),
        equity=10_000.0,
    )
    assert isinstance(got, Intent)
    assert got.side is Side.SELL
    assert got.stop == pytest.approx(4405.5)
    assert got.target == pytest.approx(4382.93)
    assert got.entry == pytest.approx(4399.5)


def test_momentum_scalp_refuses_a_call_fighting_its_own_context():
    engine = strategy("momentum-scalp")
    for _ in range(60):
        engine.observe(signal(features={"edge": 0.4}))
    got = engine.consider(
        signal(direction="down", features={"edge": -0.3}),
        spec=GOLD,
        tick=Tick("XAUUSD", bid=4399.5, ask=4400.5),
        equity=10_000.0,
    )
    assert isinstance(got, Refusal)
    assert got.gate == "momentum"


async def test_a_statespace_proposal_reaches_a_strategy(tmp_path):
    """The receipt itself: a proposal on the bus becomes a decision.

    This is the half that `test_proposals_are_a_declared_topic_and_subscribed_early`
    cannot prove. A topic can be subscribed and still reach no strategy, because
    `Strategy.wants` sorts on `shape` and every strategy but `statespace-surprise`
    wants a level this payload does not carry."""
    from till_infinity.bus import PROPOSALS

    bus = Bus()
    async with Journal(tmp_path / "journal.db") as book:
        # `settings()` pins `level-scalp`; this is the one test about the other
        # producer, so it names the one strategy written for that shape.
        chosen = settings(symbols=("eurusd",), strategies=("statespace-surprise",))
        trader = Trader(bus, settings=chosen, journal=book)
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "eurusd", "bid": 1.08500, "ask": 1.08505})
        )
        got = await trader.handle(Message(topic=PROPOSALS, payload=proposal()))

        assert trader.proposals == 1, "the message was not routed into on_signal"
        assert trader.received == 0, "a proposal is not a structures signal"
        assert got is not None, "the proposal reached no strategy at all"
        assert isinstance(got, Intent), f"reached a strategy and was refused: {got}"
        assert got.side is Side.BUY, "the side is the triggering bar's, not the readout's"


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


def test_the_arithmetic_strategies_stay_synchronous():
    """Making every strategy async would be a lie about what the others cost."""
    import inspect

    from till_infinity.trading.strategies.strategy import Strategy

    plain = td.STRATEGIES["level-scalp"]
    assert not inspect.iscoroutinefunction(plain.consider)
    # And the async door falls through to the sync one for them. `council` was
    # the one strategy that overrode it, and was retired on 2026-10-28, so
    # every strategy left is arithmetic - which is what this now asserts.
    assert plain.consider_async is Strategy.consider_async
    assert all(cls.consider_async is Strategy.consider_async for cls in td.STRATEGIES.values()), (
        "a strategy overriding consider_async needs its own case here"
    )


def test_the_anchor_must_be_higher_not_merely_another_timeframe():
    """A 1m call confirmed by 3m is the same fast noise seen twice.

    `confluence-scalp` used to accept any other timeframe at all, which is a
    weaker claim than the one its name makes.
    """
    made = settings()
    engine = td.STRATEGIES["confluence-scalp"](made)

    fast_only = signal(interval="1m", confluence=["1m", "3m"])
    engine.observe(fast_only)
    got = engine.consider(
        fast_only, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "unanchored"

    anchored = signal(interval="5m", confluence=["5m", "1h"])
    engine.observe(anchored)
    assert isinstance(
        engine.consider(
            anchored, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
        ),
        Intent,
    )


def test_anchors_are_read_from_the_signal_not_recomputed():
    """structures has already grouped the price into a zone across timeframes."""
    made = settings()
    engine = td.STRATEGIES["level-scalp"](made)
    assert engine.anchored(signal(interval="5m", confluence=["5m", "1h", "4h"])) == ("1h", "4h")
    # The entry's own timeframe is not its own context.
    assert engine.anchored(signal(interval="5m", confluence=["5m"])) == ()
    # A timeframe outside this strategy's anchors does not count.
    assert engine.anchored(signal(interval="5m", confluence=["5m", "1w"])) == ()


def test_configuration_can_narrow_a_strategy_but_never_widen_one():
    """The effective set is the intersection, so a scalper cannot be
    configured onto weekly levels by an over-broad TRADING_INTERVALS."""
    narrow = settings(intervals=("1m", "5m"))
    assert td.STRATEGIES["level-scalp"](narrow).intervals == ("1m", "5m")

    everything = settings(intervals=("1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"))
    scalper = td.STRATEGIES["level-scalp"](everything)
    assert "1w" not in scalper.intervals
    assert scalper.intervals == ("1m", "3m", "5m", "15m", "30m")


def test_higher_timeframes_reach_a_scalper_as_confluence_not_as_a_trade():
    """A 1h level raises the probability of a fast call; it does not become a
    slow trade of its own."""
    got = take("level-scalp", signal(interval="1h"))
    assert isinstance(got, Refusal)
    assert got.gate == "interval"

    # The same structure, seen on 5m and confirmed by 1h, is tradable.
    confirmed = take("level-scalp", signal(interval="5m", confluence=["1h", "5m"]))
    assert isinstance(confirmed, Intent)
    assert "1h" in confirmed.confluence


async def test_refusals_are_counted_per_gate_so_silence_can_be_explained():
    bus = Bus()
    trader = Trader(bus, settings=settings())
    await trader.start()
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    # A call on a timeframe this trader does not act on.
    await trader.handle(Message(topic=SIGNALS, payload=signal(interval="1d")))
    await trader.handle(Message(topic=SIGNALS, payload=signal(interval="1d")))

    assert trader.passed_over.get("level-scalp:interval") == 2
    assert "interval" in trader.summary()


def test_a_level_that_is_usually_run_is_refused():
    """A level run four times in ten is telling you about itself directly."""
    got = take("sweep-aware", signal(features={"sweep_rate": 0.5, "sweep_n": 10.0}))
    assert isinstance(got, Refusal)
    assert got.gate == "swept_often"


def test_a_high_sweep_rate_with_no_history_behind_it_is_not_believed():
    """Two interactions cannot establish a rate."""
    got = take("sweep-aware", signal(features={"sweep_rate": 1.0, "sweep_n": 2.0}))
    assert isinstance(got, Intent)


def test_a_stop_in_front_of_resting_liquidity_is_refused():
    """A run at those orders takes this one on the way."""
    got = take(
        "sweep-aware",
        signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 1.0}),
    )
    assert isinstance(got, Refusal)
    assert got.gate == "in_front"


def test_a_stop_in_open_ground_is_allowed():
    got = take(
        "sweep-aware",
        signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 6.0}),
    )
    assert isinstance(got, Intent)


def test_nothing_within_reach_is_not_a_reason_to_refuse():
    """Zero means no target, which is the good case rather than a missing one."""
    got = take("sweep-aware", signal(features={"liquidity_beyond_vol": 0.0}))
    assert isinstance(got, Intent)


def test_sweep_aware_refuses_rather_than_widening_the_stop(monkeypatch):
    """Widening would keep the trade and change what it costs.

    The control used to be `level-scalp`, on the grounds that it did not wear
    the gate. From 2026-10-10 every level strategy does, so the control is now
    the opt-out itself - which keeps the claim this test was making and also
    pins the flag, the one line that turns the gate off again.
    """
    call = signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 1.0})
    monkeypatch.setattr(td.STRATEGIES["level-scalp"], "sweep_gated", False)
    plain = take("level-scalp", call)
    guarded = take("sweep-aware", call)
    assert isinstance(plain, Intent)
    assert isinstance(guarded, Refusal)
    assert guarded.gate == "in_front"


def test_the_gate_judges_the_stop_the_trade_will_actually_get(monkeypatch):
    """`thesis-only`'s width comes from its floor, not from its multiple.

    `distances` places `max(risk_vol * stop_multiple, stop_floor_vol(interval))`.
    Reading only the first arm described a 1.00v stop on a trade risking 4.00v
    and so cleared 209 of 450 calls it had never really looked at; this is the
    `max`. The strategy keeps `stop_multiple = 1.0`, so a test that went
    through the multiple would pass either way - which is why this uses the one
    geometry where the two arms differ by 4x, and forces the gate on to get at
    it. That `thesis-only` ships with the gate *off* is the next test; this one
    is about the arithmetic, not about who wears it.
    """
    engine = td.STRATEGIES["thesis-only"](settings())
    assert engine.stop_multiple == 1.0
    assert engine.stop_floor_vol("5m") == 4.0

    monkeypatch.setattr(td.STRATEGIES["thesis-only"], "sweep_gated", True)
    # Liquidity 3v beyond: the multiple arm alone reaches 33% of the way to it
    # and clears the 80% limit, while the stop actually placed reaches 133%.
    call = signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 3.0})
    got = take("thesis-only", call)
    assert isinstance(got, Refusal)
    assert got.gate == "in_front"
    assert "4.00v" in got.detail


def test_thesis_only_keeps_its_circuit_breaker_and_nothing_else_does():
    """The gate would refuse 63% of this strategy's calls, so it does not wear it.

    A 4v stop is nearly always in front of the liquidity a sweep is aimed at,
    and the record cannot justify the cut: the refused trades made
    -0.066 +/-0.040 R each, inside their own standard error, while this
    strategy's profit comes from a handful of large winners. Every other level
    strategy wears it - `inverse` is the one where the refused trades lose three
    standard errors from zero.
    """
    assert td.STRATEGIES["thesis-only"].sweep_gated is False
    others = {
        name: cls.sweep_gated
        for name, cls in td.STRATEGIES.items()
        if name != "thesis-only" and hasattr(cls, "sweep_gated")
    }
    assert others, "no other strategy carries the flag"
    assert all(others.values()), f"unexpectedly ungated: {[k for k, v in others.items() if not v]}"

    # And the exemption is the flag, not the geometry: the same call it now
    # takes is one the gate would refuse.
    call = signal(features={"risk_vol": 1.0, "liquidity_beyond_vol": 3.0})
    assert isinstance(take("thesis-only", call), Intent)


def test_the_stop_is_floored_at_one_volatility_unit():
    """Fair value is a distribution and volatility is its width.

    A stop closer than one unit sits inside the estimate it is protecting and
    is taken by ordinary movement rather than by the thesis failing. The first
    two live trades carried risk_vol of 0.53 and 0.61.
    """
    made = settings()
    engine = td.STRATEGIES["level-scalp"](made)
    # The losing trade's own numbers.
    stop, _ = engine.distances(
        level=4624.97, entry=4624.97, vol_bps=3.72354, risk_vol=0.609921, push_vol=1.158286
    )
    unit = 4624.97 * 3.72354 / 10_000
    assert stop / unit == pytest.approx(1.0, abs=0.01)
    assert stop > 1.05  # wider than the stop that was actually placed


def test_a_model_asking_for_a_wide_stop_still_gets_it():
    """The floor only ever widens: it is a minimum, not a target."""
    made = settings()
    engine = td.STRATEGIES["level-scalp"](made)
    stop, _ = engine.distances(level=4400.0, entry=4400.0, vol_bps=10.0, risk_vol=3.0, push_vol=2.0)
    unit = 4400.0 * 10.0 / 10_000
    assert stop / unit == pytest.approx(3.0, abs=0.01)


def test_widening_the_stop_shrinks_the_size_rather_than_the_risk():
    """The budget is fixed, so a wider stop buys fewer lots. That is the trade
    being sized correctly, not being penalised."""
    tight = settings(min_stop_vol=0.5)
    wide = settings(min_stop_vol=2.0)
    small = take("level-scalp", equity=10_000.0)
    assert isinstance(small, Intent)

    engine_wide = td.STRATEGIES["level-scalp"](wide)
    engine_wide.observe(signal())
    big_stop = engine_wide.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(big_stop, Intent)
    assert big_stop.volume < small.volume
    assert big_stop.risk_money == pytest.approx(small.risk_money, rel=0.35)
    assert abs(tight.min_stop_vol - wide.min_stop_vol) > 0


def test_a_trade_that_cannot_afford_a_real_stop_is_refused():
    """A stop inside the noise is not a cheaper trade, it is a worse one."""
    got = take("level-scalp", equity=200.0, min_stop_vol=4.0)
    assert isinstance(got, Refusal)
    assert got.gate == "size"


def test_a_magic_does_not_move_when_the_strategy_list_changes():
    """The number lands on a position held at a broker and outlives the run.

    Deriving it from the configured list would renumber every open position
    the moment TRADING_STRATEGIES was edited, and a restart mid-trade could
    not say who owned what.
    """
    base = td.DEFAULT_MAGIC
    alone = td.magic_for(base, "sweep-aware")
    assert td.magic_for(base, "sweep-aware") == alone
    # The same name, asked for in a differently-ordered world.
    assert td.MAGIC_ORDER.index("sweep-aware") == td.MAGIC_ORDER.index("sweep-aware")
    assert alone != td.magic_for(base, "level-scalp")


async def test_the_order_carries_the_strategys_magic():
    bus = Bus()
    made = settings(live=True)
    venue = RecordingBroker(made)
    trader = Trader(bus, settings=made, broker=venue)
    await trader.start()

    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    got = await trader.handle(Message(topic=SIGNALS, payload=signal()))

    assert isinstance(got, Intent)
    assert len(venue.sent) == 1
    sent = venue.sent[0]
    assert sent.magic == td.magic_for(made.magic, "level-scalp")
    assert sent.magic != made.magic
    assert td.strategy_for(made.magic, sent.magic) == "level-scalp"


async def test_a_strategy_listed_where_it_can_never_trade_is_reported(caplog):
    """The failure nobody finds by looking.

    `sweep-aware` is `level-scalp` plus extra refusals, so behind it there is
    nothing left for it to take. It loads, it reports as enabled, and it books
    no trades forever - every signal except its own results says it is working.
    """
    bus = Bus()
    made = settings(strategies=("level-scalp", "sweep-aware"))
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    with caplog.at_level("WARNING"):
        await trader.start()

    said = " ".join(r.getMessage() for r in caplog.records)
    assert "sweep-aware" in said
    assert "never trade" in said


async def test_the_right_order_is_not_complained_about(caplog):
    bus = Bus()
    made = settings(strategies=("sweep-aware", "level-scalp"))
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    with caplog.at_level("WARNING"):
        await trader.start()

    said = " ".join(r.getMessage() for r in caplog.records)
    assert "never trade" not in said


def test_the_stop_clears_the_fill_not_just_the_level():
    """The failure this was written after.

    `distances` floors the stop at `min_stop_vol` from the **level**, and
    sizing measures from the **fill**. A fill that lands most of the way to a
    level-anchored stop is therefore sized as a short-distance trade - a large
    one - and taken out by ordinary movement. Live: a gold buy filled 1.0v
    above a stop sitting 5.9v below the level, sized 0.18 lots, stopped in
    minutes for -26.64.
    """
    # Price well above the level at 4400, so the level-anchored stop is far
    # below the level but close underneath the fill.
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4399.0, ask=4400.0), min_stop_vol=2.0)
    assert isinstance(got, Intent)
    unit = price_distance(4400.0, 10.0, 1.0)
    assert abs(got.entry - got.stop) >= 2.0 * unit - 1e-9


def test_widening_the_stop_to_clear_the_fill_shrinks_the_position():
    """It can only cost size, never add it - same money over a longer stop."""
    tight = take("level-scalp", tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), min_stop_vol=0.5)
    wide = take("level-scalp", tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), min_stop_vol=3.0)
    assert isinstance(tight, Intent)
    assert isinstance(wide, Intent)
    assert abs(wide.entry - wide.stop) > abs(tight.entry - tight.stop)
    # A longer stop for the same money can only mean fewer lots. Not asserting
    # equal risk_money: the lot step is coarse and the minimum lot is a floor,
    # so the money actually at risk moves around under rounding.
    assert wide.volume <= tight.volume


def test_the_fill_floor_never_rescues_an_invalidated_trade():
    """Order of operations, not a detail.

    A fill on the far side of the level-anchored stop is a trade that has
    already been invalidated. Applying the fill floor before the `through`
    check would rebase the stop below such a fill and turn the refusal into a
    position - which is what happened on the first attempt at this.
    """
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4389.5, ask=4390.5))
    assert isinstance(got, Refusal)
    assert got.gate == "through"
    # Note the floor cannot be turned up to probe this in isolation:
    # `min_stop_vol` feeds the level-anchored distance in `distances` as well,
    # so raising it moves the anchored stop down past the fill and the trade
    # stops being invalidated at all. The ordering is what protects this, not
    # the size of the floor.


def test_a_wide_market_refuses_the_trade():
    made = settings()
    ctx = Context(wide_venues=3, wide_pause=300.0, wide_warmup=0.0)
    guard = Guard(made, context=ctx)
    guard.roll(10_000.0)
    for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
        ctx.observe_signal(_wide("gold", venue, 100.0))

    got = take("level-scalp")
    assert isinstance(got, Intent)
    stopped = guard.allows(got, positions=[], tick=None, now=150.0)
    assert stopped is not None
    assert stopped.gate == "wide"


def test_a_wide_market_on_another_instrument_does_not_refuse_this_one():
    made = settings()
    ctx = Context(wide_venues=3, wide_pause=300.0, wide_warmup=0.0)
    guard = Guard(made, context=ctx)
    guard.roll(10_000.0)
    for venue in ("OANDA", "CAPITALCOM", "FOREXCOM"):
        ctx.observe_signal(_wide("btc", venue, 100.0))

    got = take("level-scalp")
    assert isinstance(got, Intent)
    assert guard.allows(got, positions=[], tick=None, now=150.0) is None


def test_the_stop_clears_the_sweep_zone_not_the_touch_zone():
    """A stop at the average sweep depth is exceeded by about half of sweeps.

    The touch zone's far edge is built from the mean wick, which is the right
    centre for "is price at this level" and the wrong edge for "how far past it
    does price go". From the account the difference looks like being stopped
    out and then watching the move happen.
    """
    shallow = take("level-scalp", signal(features={"zone_low": 4396.0}))
    deep = take(
        "level-scalp",
        signal(features={"zone_low": 4396.0, "sweep_low": 4392.0}),
    )
    assert isinstance(shallow, Intent)
    assert isinstance(deep, Intent)
    assert deep.stop < shallow.stop, "the wider band should push the stop further out"
    # And the size comes down to keep the money at risk the same.
    assert deep.volume <= shallow.volume


def test_an_older_signal_without_a_sweep_zone_still_works():
    """A producer that predates the wider band degrades to the previous
    behaviour rather than to no zone at all."""
    got = take("level-scalp", signal(features={"zone_low": 4396.0}))
    assert isinstance(got, Intent)
    assert got.stop < 4400.0


def test_a_fill_that_has_left_the_level_behind_is_refused():
    """The call was measured at the level and the push runs from there, so a
    fill well past it has already spent part of the move."""
    # Level at 4400, price 3v past it in the trade's direction.
    got = take(
        "level-scalp",
        tick=Tick("XAUUSD", bid=4412.0, ask=4413.0),
        max_chase_vol=1.0,
    )
    assert isinstance(got, Refusal)
    assert got.gate in {"chase", "through"}


def test_arriving_before_the_level_is_not_a_chase():
    """Price short of the level is the setup behaving as advertised."""
    got = take("level-scalp", tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), max_chase_vol=1.0)
    assert isinstance(got, Intent)


def test_the_stop_floor_scales_with_how_long_it_must_last():
    """`vol_bps` is one bar of the entry interval; the trade lives for many.

    Volatility grows with the square root of time - measured on our own
    instruments at 1.04, 1.12 and 0.89 of sqrt(t) on gold, 0.99 and 0.98 on the
    Dow - so a one-bar stop on a thirty-bar trade sits inside the noise it has
    to survive.
    """
    flat = take("level-scalp", stop_hold_scaling=0.0)
    scaled = take("level-scalp", stop_hold_scaling=1.0, max_stop_scale=3.0)
    assert isinstance(flat, Intent)
    assert isinstance(scaled, Intent)
    assert abs(scaled.entry - scaled.stop) > abs(flat.entry - flat.stop)
    # Same money at risk over a longer stop means fewer lots.
    assert scaled.volume <= flat.volume


def test_the_scaling_is_capped():
    """Uncapped, a thirty-bar hold asks for a stop 5.5x wider and a position
    5.5x smaller, and reward_to_risk then refuses nearly everything."""
    small = take("level-scalp", stop_hold_scaling=1.0, max_stop_scale=1.5)
    big = take("level-scalp", stop_hold_scaling=1.0, max_stop_scale=3.0)
    assert isinstance(small, Intent)
    assert isinstance(big, Intent)
    assert abs(big.entry - big.stop) > abs(small.entry - small.stop)


def test_the_hold_is_expressed_in_bars_of_the_entry_interval():
    """Thirty minutes is thirty bars to a 1m strategy and two to a 15m one."""
    from till_infinity.trading.strategies.scalper import LevelScalp

    engine = LevelScalp(settings())
    LevelScalp.hold_bars = 20.0
    try:
        assert engine.hold_for("1m") == pytest.approx(1200.0)
        # Capped by wall clock, because twenty 15m bars is five hours.
        assert engine.hold_for("15m") == pytest.approx(1800.0)
        assert engine.hold_bars_for("1m") == pytest.approx(20.0)
        assert engine.hold_bars_for("15m") == pytest.approx(2.0)
    finally:
        LevelScalp.hold_bars = 0.0


def test_no_hold_bars_leaves_the_seconds_behaviour_alone():
    from till_infinity.trading.strategies.scalper import LevelScalp

    engine = LevelScalp(settings())
    assert engine.hold_for("1m") == pytest.approx(engine.hold_seconds or 1800.0)


def test_the_stop_clears_the_brokers_own_minimum():
    """`stops_level` is not a suggestion - a closer stop is refused outright,
    and the refusal arrives after the decision has been made.

    Live: Wall Street 30 asks for 300 points - 3.00 in price - against gold's
    20, and our stops on it landed near 2.7, so orders were accepted or
    rejected depending on where volatility happened to be. A refusal is not a
    safer trade, it is no trade.
    """
    wide = td.SymbolSpec(
        symbol="XAUUSD",
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        contract_size=100.0,
        stops_level=300.0,  # 3.00 in price, like the Dow
    )
    got = take("level-scalp", spec=wide)
    assert isinstance(got, Intent)
    assert abs(got.entry - got.stop) >= 3.0, "the stop has to clear the broker's floor"
    # And the order the broker would see is one it will accept.
    assert not td.sizing.respects_stops_level(wide, got.entry, got.stop, got.target)


def test_a_level_that_does_not_usually_hold_is_refused():
    """The losses concentrate below this line.

    Over the first nineteen closed trades, the eight with a directional base
    rate under 0.55 produced one winner and -6.74R. A level that does not
    usually hold is not made trustworthy by a model claiming something unusual
    about it.
    """
    weak = take("level-scalp", signal(features={"base_rate_up": 0.40}), min_base_rate=0.55)
    assert isinstance(weak, Refusal)
    assert weak.gate == "base_rate"

    strong = take("level-scalp", signal(features={"base_rate_up": 0.70}), min_base_rate=0.55)
    assert isinstance(strong, Intent)


def test_the_base_rate_is_read_in_the_direction_claimed():
    """`base_rate_up` is always the *up* rate, so a sell has to flip it.

    Comparing it raw across a set that is mostly sells describes the direction
    mix rather than the levels - a mistake made once already while reading
    these numbers.
    """
    # A 0.30 up-rate is a 0.70 down-rate: weak for a buy, strong for a sell.
    buy = take("level-scalp", signal(features={"base_rate_up": 0.30}), min_base_rate=0.55)
    assert isinstance(buy, Refusal)
    assert buy.gate == "base_rate"

    sell = take(
        "level-scalp",
        signal(direction="down", features={"base_rate_up": 0.30}),
        min_base_rate=0.55,
    )
    assert isinstance(sell, Intent)


def test_no_base_rate_floor_leaves_every_call_alone():
    got = take("level-scalp", signal(features={"base_rate_up": 0.10}))
    assert isinstance(got, Intent)


def test_agreement_never_moves_a_stop_closer_or_a_target_further():
    """It can only ever make the trade safer, never more flattering."""
    bus = Bus()
    made = settings(live=True, evaluate_all=True, consensus_min=2)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    base = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4393.0,
        target=4406.0,
    )
    # An agreeing strategy with a tighter stop and a further target.
    others = [("level-scalp", replace(base, stop=4398.0, target=4420.0))]
    built, agreed = trader._agree(base, others)
    assert agreed == ["level-scalp"]
    assert built.stop == pytest.approx(4393.0), "kept the wider stop"
    assert built.target == pytest.approx(4406.0), "kept the nearer target"


def test_a_consensus_threshold_of_zero_means_off():
    """It meant "always on", and shipped that way.

    The guard was `len(agreed) + 1 < consensus_min`, which with zero is never
    true - so a setting documented as disabling the feature enabled it
    unconditionally, and it fired in production within minutes of being
    deployed disabled.
    """
    bus = Bus()
    base = Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4396.0,
        target=4410.0,
    )
    others = [("sweep-aware", replace(base, stop=4390.0, target=4404.0))]

    for off in (0, 1):
        made = settings(live=True, evaluate_all=True, consensus_min=off)
        trader = Trader(bus, settings=made, broker=RecordingBroker(made))
        built, agreed = trader._agree(base, others)
        assert agreed == [], f"consensus_min={off} should disable it"
        assert built is base, "the trade must be untouched when it is off"

    made = settings(live=True, evaluate_all=True, consensus_min=2)
    trader = Trader(bus, settings=made, broker=RecordingBroker(made))
    built, agreed = trader._agree(base, others)
    assert agreed == ["sweep-aware"]
    assert built.stop == pytest.approx(4390.0)


def test_thesis_only_still_has_a_circuit_breaker():
    """Not stopless. A genuinely stopless trade on a leveraged account is how
    accounts die, and `lots` derives size from the stop - with no stop there is
    no size."""
    got = take("thesis-only")
    assert isinstance(got, Intent)
    assert got.stop > 0
    assert got.volume > 0
    assert got.risk_money > 0


def test_thesis_only_risks_the_same_money_as_the_others():
    """The comparison is only fair if the bet is the same size."""
    normal = take("level-scalp")
    roomy = take("thesis-only")
    assert isinstance(normal, Intent)
    assert isinstance(roomy, Intent)
    # Within lot-rounding of each other - the stop distance changes, the money
    # does not.
    assert roomy.risk_money == pytest.approx(normal.risk_money, rel=0.5)


def test_snap_holds_for_as_long_as_the_interaction_lasts():
    """Measured over 53,372 resolutions: the median touch resolves in 18
    seconds, 53% inside 30 and 72% inside 120. Every other strategy holds for
    a fraction of an hour, which is about a hundred times the event."""
    from till_infinity.trading.strategies.scalper import LevelScalp, Snap

    made = settings()
    fast, slow = Snap(made), LevelScalp(made)
    assert fast.hold_seconds == pytest.approx(120.0)
    assert fast.hold_for("1m") < slow.hold_for("1m") / 10


def test_snap_differs_from_level_scalp_in_exactly_one_respect():
    """The comparison only says something if one thing changes."""
    from till_infinity.trading.strategies.scalper import LevelScalp, Snap

    assert Snap.entries == LevelScalp.entries
    assert Snap.context == LevelScalp.context
    # Same stop, same target, same size - only the clock is different.
    quick = take("snap")
    usual = take("level-scalp")
    assert isinstance(quick, Intent)
    assert isinstance(usual, Intent)
    assert quick.stop == pytest.approx(usual.stop)
    assert quick.target == pytest.approx(usual.target)
    assert quick.volume == pytest.approx(usual.volume)
    assert quick.hold < usual.hold


def test_a_fast_strategy_protects_faster_than_a_slow_one():
    """A bar runs almost to the target, stops short, and gives it back.

    The global numbers are built for a half-hour thesis - a 1R threshold and a
    2v trail - and on a two-minute trade that is most of its life spent
    unprotected, missing exactly the case a fast strategy exists for.
    """
    from till_infinity.trading.strategies.scalper import LevelScalp, Snap

    assert Snap.break_even_at < 1.0
    assert Snap.trail_vol < 2.0
    # **`level-scalp` declared none until 2026-10-08**, taking whatever the
    # deployment configured - which in production is 1.0R and 2v, the numbers
    # this test's own docstring calls "built for a half-hour thesis", against a
    # median hold of 470 seconds. It won 56% of its trades and lost money
    # anyway, because its average loss was 1.8x its average win.
    #
    # So it declares them now, and the ordering is what is pinned: faster than
    # the deployment default, slower than `snap`, which is the same call on a
    # shorter clock and should still be the quickest to protect.
    assert 0.0 < LevelScalp.break_even_at < 1.0
    assert 0.0 < LevelScalp.trail_vol < 2.0
    assert Snap.break_even_at < LevelScalp.break_even_at
    assert Snap.trail_vol < LevelScalp.trail_vol

    quick = take("snap")
    assert isinstance(quick, Intent)
    # Break-even is taken as declared: it is in R, and R already carries the
    # horizon through the stop.
    assert quick.break_even_at == pytest.approx(Snap.break_even_at)
    # The trail is *derived*, not taken flat - stretched by the hold and then
    # capped against the move it protects, so it no longer equals the constant
    # the strategy declares. What must hold is that a fast strategy still
    # trails tighter than a slow one.
    slow = take("level-scalp")
    assert isinstance(slow, Intent)
    assert 0 < quick.trail_vol <= Snap.trail_vol * 3.0
    # `<=`, not `<`, and the reason is `TRAIL_SHARE`. Both trails are capped
    # against the move they protect, so at an ordinary expected push the two
    # declared values - 0.75 and 1.0 - are capped to the *same* number and the
    # declared gap does nothing. It bites only where the push is large enough
    # that the cap does not bind, which is the case the trail exists for.
    assert quick.trail_vol <= slow.trail_vol or slow.trail_vol == 0.0


def test_every_registered_strategy_has_a_magic_slot():
    """A strategy without one still trades and cannot be scored.

    It stamps a hashed magic from the tail of the band, and the hash has no
    inverse - so every position it opens reads as "unattributed" on close.
    `snap` and `thesis-only` ran live for an hour that way, and their trades
    are unattributable in the record.
    """
    from till_infinity.trading.strategies.strategy import STRATEGIES

    missing = [n for n in STRATEGIES if n not in td.MAGIC_ORDER]
    assert not missing, f"no magic slot for {missing} - their trades cannot be attributed"
    for name in STRATEGIES:
        magic = td.magic_for(td.DEFAULT_MAGIC, name)
        assert td.strategy_for(td.DEFAULT_MAGIC, magic) == name


def test_inverse_flips_the_side():
    from till_infinity.trading.strategies.scalper import Inverse, LevelScalp

    assert Inverse(settings()).orient(Side.BUY) is Side.SELL
    assert Inverse(settings()).orient(Side.SELL) is Side.BUY
    # And nothing else does, or every strategy would be a control.
    assert LevelScalp(settings()).orient(Side.BUY) is Side.BUY


def test_inverse_gates_on_the_side_the_call_named():
    """It must select the same signals to be a comparison.

    Gating on the flipped side would pick a different set of calls, and then
    a difference in results would say nothing about direction.
    """
    import inspect

    from till_infinity.trading.strategies.scalper import LevelStrategy

    source = inspect.getsource(LevelStrategy.consider)
    gate = source.index("self.quality(")
    flip = source.index("self.orient(")
    assert gate < flip, "the gates must run before the side is flipped"


def test_a_scalper_still_defers_to_the_deployment():
    from till_infinity.trading.strategies.scalper import LevelScalp

    assert LevelScalp(settings()).pullback_fraction == 0.0


def test_strategies_that_did_not_ask_are_unaffected():
    """It is a filter strategies opt into, not a new global gate."""
    from till_infinity.trading.strategies.scalper import LevelScalp

    engine = LevelScalp(settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0))
    assert engine.max_against_vol == 0.0
    features = {"probability": 0.9, "edge": 1.0, "pressure_vol": -99.0}
    assert engine.quality("gold", features, Side.BUY) is None


def test_the_inverse_control_carries_the_filter():
    """Fading a live run is the worst version of what it does, and would
    confound the direction test it exists for."""
    from till_infinity.trading.strategies.scalper import Inverse

    assert Inverse(settings()).max_against_vol > 0


def test_an_unknown_context_is_not_refused():
    """A feed without enough history trades as it did before this existed -
    silence is not evidence of chop."""
    from till_infinity.trading.strategies.scalper import LevelScalp

    engine = LevelScalp(
        settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0, min_efficiency=0.3)
    )
    assert engine.quality("gold", {"probability": 0.9, "edge": 1.0}, Side.BUY) is None


def test_sizing_scales_the_fraction_so_every_cap_still_binds():
    """Applied to `risk_fraction`, not to the lot count. A multiplier that
    bypassed `max_risk_money` would be a way to exceed the risk budget through
    a setting nobody reads as a risk setting.
    """
    import inspect

    from till_infinity.trading.strategies.scalper import LevelStrategy

    source = inspect.getsource(LevelStrategy.consider)
    # Every size factor multiplies the *fraction*, never the lot count, so
    # `max_risk_money`, the volume step and the broker limits all still bind.
    assert "settings.risk_fraction" in source
    assert "self.trend_scale(features)" in source
    assert "self.momentum_scale(features, side)" in source
    assert "sized.volume *" not in source


def test_an_absurd_push_is_refused():
    """A brent call arrived claiming 10,229v against a measured p99 of 9.55v,
    and became a target of 3850 on an entry of 88 - 43 times the price of the
    instrument. The broker refused it, which is the only reason it was seen.
    """
    got = take("level-scalp", signal(features={"expected_push_vol": 10_229.7}))
    assert isinstance(got, Refusal)
    assert got.gate == "push"


def test_a_large_but_real_push_is_not_refused():
    """The job is to catch a broken number, not to second-guess a large one.
    A 12v push is rare and real - p99 is 9.55v."""
    got = take(
        "level-scalp",
        signal(features={"expected_push_vol": 12.0}),
        min_probability=0.0,
        min_edge=0.0,
        min_base_rate=0.0,
    )
    assert not isinstance(got, Refusal), getattr(got, "detail", got)


def test_the_push_ceiling_can_be_switched_off():
    got = take(
        "level-scalp",
        signal(features={"expected_push_vol": 10_229.7}),
        max_push_vol=0.0,
        min_probability=0.0,
        min_edge=0.0,
        min_base_rate=0.0,
    )
    assert not (isinstance(got, Refusal) and got.gate == "push")


def test_the_tight_parked_stop_only_applies_to_a_short_hold():
    """The grid behind it was scored over resolutions with a median life of
    eighteen seconds. Applied to a trade held for half an hour it is half a
    bar against roughly 5.5 units of wandering - which is how five gold sells
    were stopped inside a point and a half on a day gold fell twenty-eight.
    """
    fast = strategy("snap", parked_stop_vol=0.5)
    slow = strategy("level-scalp", parked_stop_vol=0.5)
    parked = {"after_pullback": 1.0}
    assert fast._parked_stop(parked, 4400.0, 10.0, "1m") > 0
    assert slow._parked_stop(parked, 4400.0, 10.0, "1m") == 0.0


def test_the_stop_floor_grows_with_the_hold_when_scaling_is_on():
    """One volatility unit is one bar of the entry interval, and a trade held
    for thirty of them wanders about 5.5 units. A one-bar stop on a thirty-bar
    hold is taken by ordinary movement whatever the direction does."""
    off = strategy("level-scalp", stop_hold_scaling=0.0, min_stop_vol=1.0)
    on = strategy("level-scalp", stop_hold_scaling=1.0, min_stop_vol=1.0)
    assert on.stop_floor_vol("1m") > off.stop_floor_vol("1m")


def test_the_scaled_floor_is_capped():
    """`max_stop_scale` bounds it: a wider stop cannot create edge, so this is
    for not paying spread to be stopped by noise, not a licence to widen."""
    on = strategy("level-scalp", stop_hold_scaling=1.0, min_stop_vol=1.0, max_stop_scale=3.0)
    assert on.stop_floor_vol("1m") <= 3.0 * 1.0 + 1e-9


def test_the_trail_stays_inside_the_move_it_protects():
    """Scaling 2v by the horizon gives 6v, while the measured push
    distribution has a median of 2.24v and a p90 of 4.93v. A trail further
    from price than the entire move can never beat the stop already in place,
    so `manage.advance` never applies it - the protection is absent, silently.

    Driven through `momentum-scalp` rather than `level-scalp` from 2026-10-08.
    The vehicle has to be a strategy that declares **no** trail of its own, so
    that the `trail_vol` passed here is the one being scaled; `level-scalp`
    now declares 1.0 and overrides it, which would make this a test of that
    constant rather than of the arithmetic.
    """
    uncapped = _trail("momentum-scalp", 0.0)
    assert uncapped == pytest.approx(6.0)
    assert _trail("momentum-scalp", 1.3) < 1.3
    assert _trail("momentum-scalp", 2.24) < 2.24


def test_a_bigger_expected_move_earns_a_wider_trail():
    assert _trail("level-scalp", 5.0) > _trail("level-scalp", 1.3)


def test_the_cap_never_widens_a_trail():
    """It is a ceiling. A huge push must not stretch the trail past what the
    horizon already allowed."""
    assert _trail("level-scalp", 999.0) == pytest.approx(_trail("level-scalp", 0.0))


def test_break_even_is_still_untouched_by_the_push():
    """It is in R, and R is measured against a stop this reasoning already
    widened - scaling or capping it here would count the horizon twice."""
    engine = strategy("level-scalp", break_even_at=1.0, trail_vol=2.0)
    assert engine.protection("1m", 1.3)[0] == engine.protection("1m", 99.0)[0]


def test_the_agreement_gate_is_off_for_the_scalps():
    for name in ("level-scalp", "snap", "confluence-scalp"):
        assert strategy(name).min_momentum_agree == 0.0


def test_the_target_can_be_pulled_short_of_where_it_aimed():
    """A target sitting exactly where everyone else is watching fills last.
    Price stalls *at* a level rather than through it."""
    engine = strategy("level-scalp", target_buffer_vol=0.25)
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    plain = strategy("level-scalp").consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert isinstance(plain, Intent)
    # One volatility unit is 4.40 here, so a quarter of one is 1.10 - and that
    # is how far the buffer pulled the target in while `reward_floor` was 1.0.
    #
    # **At 1.2 the floor bounds it, and that is the floor working.** The buffer
    # would put this trade at 1.033 reward-to-risk; the floor will not go below
    # 1.2, so the target stops there and the pull-in is 0.28 rather than 1.10.
    # Written as the relation rather than the distance: the buffer still moves
    # the target in, and the floor decides how far it may go.
    assert got.target < plain.target
    risk = abs(got.entry - got.stop)
    assert abs(got.target - got.entry) / risk == pytest.approx(engine.reward_floor, abs=0.01)
    # and the unbuffered trade is above the floor on its own, so it is untouched
    plain_risk = abs(plain.entry - plain.stop)
    assert abs(plain.target - plain.entry) / plain_risk > engine.reward_floor


def test_the_buffer_never_pulls_the_target_past_the_entry():
    """A buffer larger than the move would invert the trade, and a target
    behind the fill is not a smaller target."""
    engine = strategy("level-scalp", target_buffer_vol=50.0)
    got = engine.consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.target > got.entry
    # At most half the move is given up.
    assert (got.target - got.entry) >= 0.0


def test_a_short_pulls_its_target_the_other_way():
    engine = strategy("level-scalp", target_buffer_vol=0.25)
    down = signal(direction="down")
    got = engine.consider(
        down, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    plain = strategy("level-scalp").consider(
        down, spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert isinstance(plain, Intent)
    assert got.side is Side.SELL
    # A sell target sits below the fill, so pulling it short raises it.
    assert got.target > plain.target


def test_no_buffer_changes_nothing():
    """Off by default, so the setting has to be asked for."""
    assert settings().target_buffer_vol == 0.0
    plain = strategy("level-scalp").consider(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(plain, Intent)


def test_a_fill_a_full_unit_past_the_level_is_refused_by_the_tight_stop():
    """The cost of the tighter stop, recorded rather than discovered later.

    `entry_edge_vol` parks 1.5v better than the market and the median entry
    sits 0.91v from its level, so a typical rest fills about 0.6v past it and
    is fine. The quartile already close to its level fills past a full unit,
    where the level-anchored 0.5v stop is above a long's fill - and that trade
    is declined rather than taken with a stop already behind price.
    """
    unit = 4400.0 * 10.0 / 10_000
    payload = signal()
    payload["features"]["after_pullback"] = 1.0
    deep = Tick("XAUUSD", bid=4400.0 - unit - 0.5, ask=4400.0 - unit + 0.5)
    common = {"min_probability": 0.0, "min_edge": 0.0, "min_base_rate": 0.0}

    refused = take("snap", payload, tick=deep, parked_stop_vol=0.5, **common)
    assert isinstance(refused, Refusal)
    assert refused.gate == "through"

    # And the same fill is taken when the stop is left wide, which is what
    # makes this a trade-off rather than a fault.
    taken = take("snap", payload, tick=deep, parked_stop_vol=0.0, **common)
    assert isinstance(taken, Intent)


def test_the_tight_stop_halves_the_risk_on_an_ordinary_rest():
    """The reason to turn it on. Half the risk for the same target doubles the
    ratio and doubles the size for the same money at stake."""
    unit = 4400.0 * 10.0 / 10_000
    payload = signal()
    payload["features"]["after_pullback"] = 1.0
    ordinary = Tick("XAUUSD", bid=4400.0 - 0.6 * unit - 0.5, ask=4400.0 - 0.6 * unit + 0.5)
    common = {"min_probability": 0.0, "min_edge": 0.0, "min_base_rate": 0.0}

    wide = take("snap", payload, tick=ordinary, parked_stop_vol=0.0, **common)
    tight = take("snap", payload, tick=ordinary, parked_stop_vol=0.5, **common)
    assert isinstance(wide, Intent)
    assert isinstance(tight, Intent)
    assert abs(tight.entry - tight.stop) == pytest.approx(abs(wide.entry - wide.stop) / 2, rel=0.1)
    assert tight.reward_to_risk > wide.reward_to_risk * 1.8
    assert tight.volume > wide.volume


def test_the_reward_floor_only_ever_pushes_a_target_further_out():
    """It raises a target the push model put too close and never pulls one in."""
    from till_infinity.trading.strategies.scalper import LevelStrategy

    aim = LevelStrategy._aim  # unbound, so a stub can stand in for `self`

    class _Near:
        target_multiple = 1.0
        reward_floor = 1.0

    class _Off:
        target_multiple = 1.0
        reward_floor = 0.0

    # A 1.5v push against a 4v stop is the measured case: raised to the stop.
    assert aim(_Near(), 1.5, 4.0) == 4.0
    # A push already beyond the floor is left exactly where it was.
    assert aim(_Near(), 6.0, 4.0) == 6.0
    # And with no floor set, nothing moves.
    assert aim(_Off(), 1.5, 4.0) == 1.5


def test_the_speeds_warm_at_a_threshold_the_book_can_actually_reach():
    """48 observations was unreachable and the strategy never traded.

    Read off the live state on 2026-09-10: `momentum-scalp` tracked 253 feeds
    and the busiest had **seven** observations, so `ready` was false everywhere
    and 99.2% of its refusals were `warmup`, every day it had run. These count
    published level calls rather than bars, and the book produces single digits
    per feed per week.
    """
    speeds = Speeds()
    assert speeds.warmup < speeds.half_lives[-1], "the slowest half-life is not reachable here"

    for i in range(int(speeds.warmup) - 1):
        speeds.observe("eurusd", 0.1 * (i + 1))
    assert not speeds.ready("eurusd")
    speeds.observe("eurusd", 0.1)
    assert speeds.ready("eurusd")


async def test_an_unattributed_close_still_records_what_it_knows():
    """**43% of one day's closes reached the journal carrying almost nothing.**

    45 of 104 on 2026-09-11 - including a gold trade that made +$32.82 at
    +8.40R, which the alert reported and the journal did not. The observation
    branch had the `Live` in its hand the whole time: entry, stop, the tracked
    extremes, everything the attributed branch writes except the parent
    decision.

    Losing the *link* is unavoidable when a position outlives the ref. Losing
    the *arithmetic* was a choice nobody made on purpose, and it biased every
    figure taken from the journal - what goes missing is exactly the trades that
    lived long enough to span a deploy."""
    made = settings()
    trader = Trader(Bus(), settings=made, journal=None)
    intent = _intent()

    live = mock.Mock()
    live.intent = intent
    live.ref = ""  # no decision on record: this is the unattributed case
    live.by = "sweep-aware"
    live.position = mock.Mock(
        ticket=5772381834,
        symbol="XAUUSD",
        magic=777707,
        age=1000.0,
        profit=32.82,
        price_open=intent.entry,
    )

    got = trader._unattributed_context(live, price=intent.target or intent.entry, why="closed")

    # The arithmetic the attributed branch records, on a close with no parent.
    for key in ("r_multiple", "best_r", "adverse_r", "entry_wanted", "entry_filled", "exit_kind"):
        assert key in got, key
    assert got["unattributed"] == 1.0, "still flagged, so the two are separable"
    assert got["strategy"] == "sweep-aware"
    assert got["ticket"] == 5772381834


async def test_parallel_lets_every_wanting_strategy_take_the_trade():
    """The running order stops deciding *who* trades and decides only who is first.

    The point is comparability: with one taker, each strategy is scored on the
    slice of the stream it happened to be offered, and two records built that
    way cannot be put beside each other.
    """
    made = settings(parallel=True)
    made.strategies = ("level-scalp", "thesis-only", "sweep-aware")
    trader = Trader(Bus(), settings=made)
    await trader.start()
    # **`max_per_symbol` is 1 by default and is the binding constraint.** It
    # exists to stop two strategies holding one idea, so parallel execution is
    # inert until it is raised - the code change alone does nothing, which is
    # worth a test of its own below. Set after `start`, because the risk plan
    # is applied there and puts the plan's value back over an assignment made
    # before it.
    trader.settings.max_per_symbol = 5
    trader.guard.settings.max_per_symbol = 5

    took: list[str] = []
    real_take = trader.take

    async def counting(intent, by=""):
        took.append(by)
        return await real_take(intent, by)

    trader.take = counting  # type: ignore[method-assign]
    # A quote first: without a tick the signal is undealable and nothing is
    # taken, which would make this pass for the wrong reason.
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.on_signal(signal())

    assert len(took) == len(set(took)), f"a strategy took the same signal twice: {took}"
    assert len(took) > 1, f"only {took} took it - the others were not given the chance"


async def test_parallel_is_still_bounded_by_the_per_symbol_cap():
    """**The cap is what keeps this from being unbounded, so it stays.**

    Turning parallel on does not remove a limit; it lets several strategies
    reach one. With `max_per_symbol` at its default of 1 the second strategy
    is refused `already_open`, which means enabling parallel without also
    raising the cap changes nothing - and silently changing nothing is the
    failure this asserts against.
    """
    made = settings(parallel=True)
    made.strategies = ("level-scalp", "thesis-only", "sweep-aware")
    assert made.max_per_symbol == 1, "the default is what makes this test meaningful"
    trader = Trader(Bus(), settings=made)
    await trader.start()

    took: list[str] = []
    real_take = trader.take

    async def counting(intent, by=""):
        took.append(by)
        return await real_take(intent, by)

    trader.take = counting  # type: ignore[method-assign]
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
    )
    await trader.on_signal(signal())

    assert len(took) == 1, f"the per-symbol cap should hold at 1, got {took}"


class TestOneStoppedTradeMustNotStallEveryFeed:
    """**Nothing was traded from 2026-09-17 to 2026-09-19, and this is why.**

    A shadow follows a stopped trade to see whether its target arrived anyway.
    The gate that decides whether a quote needs a broker round trip read
    `or self._shadows` - true for *every* feed once one shadow existed - while
    `_watch_shadows` itself only looks at shadows on the quote's own feed. So
    one stopped trade made every quote on every traded feed cost a broker call,
    serially, in the loop that also delivers signals. Signals queued behind
    quotes that never drained. The shadow was on a feed that stopped quoting,
    so it never retired and was restored on every restart.
    """

    def _shadow(self, feed: str):
        import time

        from till_infinity.trading.service import Shadow

        return Shadow(
            feed=feed,
            side=Side.BUY,
            entry=100.0,
            stop=99.0,
            target=102.0,
            ref="",
            by="level-scalp",
            until=time.time() + 86_400,
        )

    async def _trader_counting_ticks(self):
        trader = Trader(Bus(), settings=settings())
        await trader.start()
        asked: list[str] = []
        real = trader._tick

        async def counting(symbol):
            asked.append(str(symbol))
            return await real(symbol)

        trader._tick = counting  # type: ignore[method-assign]
        return trader, asked

    async def test_a_shadow_on_another_feed_costs_this_quote_nothing(self):
        trader, asked = await self._trader_counting_ticks()
        trader._shadows = {1: self._shadow("somewhere-else")}
        asked.clear()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        assert not asked, (
            f"a shadow on another feed sent this quote to the broker: {asked} - "
            "one stopped trade was costing every feed a round trip"
        )

    async def test_a_shadow_on_this_feed_is_still_followed(self):
        """The fix must narrow the gate, not remove it."""
        trader, asked = await self._trader_counting_ticks()
        trader._shadows = {1: self._shadow("gold")}
        asked.clear()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        assert asked, "a shadow on this very feed was not followed"


def test_zero_on_a_limit_means_the_deployments_own():
    """The idiom the rest of the module already uses, so a strategy that names
    nothing is governed exactly as it was before any of this existed."""
    from till_infinity.trading.risk import Limits

    guard = Guard(settings(loss_cooldown=900.0))
    guard.roll(10_000.0, now=1_000.0)
    guard.record("gold", -20.0, 9_980.0, now=1_000.0)

    named_nothing = Limits(by="level-scalp")
    assert (
        guard.allows(intent(), positions=[], now=1_100.0, limits=named_nothing).gate == "cooldown"
    )
    # Identical to passing no limits at all.
    assert guard.allows(intent(), positions=[], now=1_100.0).gate == "cooldown"


def test_the_daily_stop_still_measures_the_whole_account():
    """Whatever a strategy asks for, the halt is the account's."""
    from till_infinity.trading.risk import Limits

    guard = Guard(settings(daily_loss_fraction=0.03))
    guard.roll(10_000.0, now=1_000.0)
    guard.record("gold", -400.0, 9_600.0, now=1_100.0)

    greedy = Limits(by="cycle-scalp", loss_cooldown=1.0)
    stopped = guard.allows(intent(), positions=[], now=1_200.0, limits=greedy)
    assert stopped is not None
    assert stopped.gate == "halted", stopped.gate


def test_ageing_the_break_risk_is_on_by_default_and_can_be_turned_off():
    """On by default because a stale number in a live gate is the defect. Overridable without a
    deploy because the effect is large: against a 0.35 ceiling a 20% reading at open is refused
    once the wait passes about three bars, and `pullback_bars` is 10.0 - so the ceiling itself
    wants re-tuning against the corrected input."""
    import inspect

    assert settings().age_break_risk is True
    assert settings(age_break_risk=False).age_break_risk is False
    # And the wake path honours it rather than correcting unconditionally.
    assert "age_break_risk" in inspect.getsource(Trader._arrived)


#: Every strategy whose live geometry argued for a reward floor, and the
#: measured median reward-to-risk that argued for it. See
#: `Strategy.reward_floor`.
#:
#: Entries left with the swing and cycle strategies on 2026-10-28, and their
#: medians stayed with them in
#: `research/retire/structures/strategies/` - a median that argued for a floor
#: is a measurement about a strategy that ran, not a fact about this table.
FLOORED = {
    "thesis-only": 0.40,
    "level-scalp": 0.55,
    "inverse": 0.60,
    "momentum-scalp": 0.61,
    "snap": 0.94,
    "cycle-scalp": 1.03,
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

#: **There is no longer a shaped set.** `opportunity` and `ride` took their
#: floor from `opportunity.Shape` rather than a class attribute, because they
#: were a parameter space rather than a point in one. Both retired on
#: 2026-10-28, so every strategy left declares its own floor on its class and
#: the partition below has one fewer part.


def test_the_last_exemption_was_ended_by_its_own_premise():
    """`sweep-aware` was the one strategy without a floor. The exemption was
    argued on the floor barely touching it - "it would bind on 5% of its calls"
    - and the live record confirms that premise exactly and then overturns the
    conclusion drawn from it.

    Of 206 closed trades at a median reward-to-risk of 2.96, **eleven** sit
    under 1.10. Those eleven win 45% and lose 0.181 R each, -1.99 R in all. The
    tail the floor would touch is the part that loses, "barely touches it" is a
    reason the change is harmless rather than a reason it is wrong, and
    `floored_target` can only move a target out - so the entire downside is
    those eleven trades.

    Kept as a test because "we left the good one alone" is the kind of decision
    that gets re-read later as "the good one did not need it".
    """
    made = settings()
    engine = td.STRATEGIES[EXEMPT](made)
    assert engine.reward_floor == pytest.approx(1.50)
    # Its own breakeven at a 48.3% win rate, shrunk toward the desk's, is 1.09,
    # and it is set above that on purpose: everything under 1.5 is cumulatively
    # negative for it (14 trades, -1.78 R) while 1.5-3.0 is where it earns.
    assert engine.reward_floor >= (1 - 0.478) / 0.478
    # **And it has a ceiling.** Above 1.5 the floor would start pushing
    # profitable trades out of the 1.5-3.0 band into the 3.0+ one, where its win
    # rate falls from 61-63% to 45%. 2.0 would touch 33 trades worth +1.88 R.
    assert engine.reward_floor <= 2.0, "a floor past where the strategy is good"

    # Nothing is exempt now: every strategy either carries a floor or shapes its
    # own geometry, and none inherits the zero default.
    bare = [n for n, cls in td.STRATEGIES.items() if cls(made).reward_floor <= 0]
    assert bare == [], f"no floor and no shape: {bare}"




# The floors partition, which only described retired strategies once `scalper.py`
# went: FLOORED named seven of them and EXEMPT was `sweep-aware`. The one live
# entry, `statespace-surprise`, has its floor asserted in
# tests/test_strategies_dispersing.py against its own measured breakeven.

def test_the_unmeasured_floors_are_named_rather_than_quietly_included():
    """These five have no live decisions to quote, so a reader should be able to
    tell which floors rest on a measurement and which on the arithmetic."""
    made = settings()
    for name in FLOORED_UNMEASURED:
        assert name in td.STRATEGIES, name
        assert td.STRATEGIES[name](made).reward_floor >= 1.0, name
    assert not set(FLOORED) & set(FLOORED_UNMEASURED)
    assert set(FLOORED) | set(FLOORED_UNMEASURED) | {EXEMPT} == set(td.STRATEGIES)


# Tests of two LevelStrategy methods - `momentum_scale` and `_parked_stop` - and the
# fixtures that reach them. Both methods retired with the class, so these are level
# machinery rather than service mechanics.

def _parked_engine(**over):
    """`snap` rather than `level-scalp`: the tighter parked stop now applies
    only to a hold short enough for the grid that produced it, and snap's 120
    seconds is that horizon. See `PARKED_STOP_HOLD`."""
    made = {"min_probability": 0.0, "min_edge": 0.0, "min_base_rate": 0.0}
    made.update(over)
    return strategy(mechanics.NAME, **made)


def _momentum_size(pressure, side=Side.BUY, share=0.5):
    engine = strategy(mechanics.NAME, unconfirmed_size=share)
    features = {} if pressure is None else {"pressure_vol": pressure}
    return engine.momentum_scale(features, side)


def test_a_parked_entry_gets_the_tighter_stop():
    engine = _parked_engine(parked_stop_vol=0.5)
    got = engine._parked_stop({"after_pullback": 1.0}, 4400.0, 10.0, "1m")
    assert got == pytest.approx(price_distance(4400.0, 10.0, 0.5))


def test_a_market_entry_does_not():
    """The replay's tight stop is measured from the level, and a market entry
    is not there. Applied to one it would be the mistake `min_stop_vol` was
    written to prevent."""
    engine = _parked_engine(parked_stop_vol=0.5)
    assert engine._parked_stop({}, 4400.0, 10.0, "1m") == 0.0


def test_the_tighter_stop_is_off_by_default():
    engine = _parked_engine()
    assert engine._parked_stop({"after_pullback": 1.0}, 4400.0, 10.0, "1m") == 0.0


def test_momentum_with_the_trade_takes_full_size():
    assert _momentum_size(1.2) == 1.0
    assert _momentum_size(-1.2, side=Side.SELL) == 1.0


def test_momentum_not_confirming_takes_less():
    """Between the two yes-or-no gates sits a case neither covers: momentum
    flat, which is weaker than a turn and stronger than opposition. A smaller
    trade is the honest response to weaker evidence."""
    assert _momentum_size(0.0) == 0.5
    assert _momentum_size(-1.2) == 0.5


def test_no_reading_is_not_the_same_as_no_confirmation():
    """A feed whose accumulator has not warmed sizes as it did before this
    existed, rather than being punished for silence."""
    assert _momentum_size(None) == 1.0


def test_the_momentum_size_is_off_by_default():
    assert _momentum_size(-5.0, share=1.0) == 1.0


def test_it_can_only_reduce():
    """A setting named for reducing exposure must have no path that raises it."""
    for pressure in (-5.0, 0.0, 5.0):
        assert _momentum_size(pressure) <= 1.0


async def test_a_fill_already_better_than_the_rest_is_taken():
    """On a fast move there is nothing to improve, and waiting would only risk
    the trade."""
    trader = Trader(Bus(), settings=settings(entry_edge_vol=0.25, pullback_fraction=0.0))
    await trader.start()
    # The quote is far below the level, so the buy is already better off.
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4380.0, "ask": 4380.5})
    )
    got = await trader.on_signal(signal())
    assert not (isinstance(got, Refusal) and got.gate == "waiting")




def _floor_for(spread, margin=1.25, anchored=0.85750):
    """The stop a buy at 0.85754 ends up with, given a near-entry anchor."""
    from till_infinity.trading.strategies.scalper import LevelScalp

    engine = LevelScalp(settings(stops_level_margin=margin, min_stop_vol=0.0))
    return engine._floored_stop(EURGBP, Side.BUY, 0.85754, anchored, unit=1e-05, spread=spread)


def _momentum(pressure, side=Side.BUY, limit=1.5):
    """The gate's verdict for this much accumulated pressure."""
    from till_infinity.trading.strategies.scalper import SweepAware

    engine = SweepAware(settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0))
    assert engine.max_against_vol == limit
    features = {"probability": 0.9, "edge": 1.0, "pressure_vol": pressure}
    return engine.quality("gold", features, side)


def _chop(ratio, floor=0.3):
    from till_infinity.trading.strategies.scalper import LevelScalp

    engine = LevelScalp(
        settings(min_probability=0.0, min_edge=0.0, min_base_rate=0.0, min_efficiency=floor)
    )
    return engine.quality("gold", {"probability": 0.9, "edge": 1.0, "efficiency": ratio}, Side.BUY)


def _scale(ratio, span=0.3):
    from till_infinity.trading.strategies.scalper import LevelScalp

    engine = LevelScalp(settings(trend_sizing=span))
    return engine.trend_scale({} if ratio is None else {"efficiency": ratio})




async def test_a_trade_records_what_it_cost_and_whether_it_was_waited_for(tmp_path):
    """Questions we could not answer, asked of trades already taken.

    Three gates judge spread and none wrote down the number they judged.
    Parked and unparked fills were indistinguishable once filled, so the
    pullback could not be evaluated at all. And the stop in volatility units
    had to be re-derived from entry, stop and vol_bps every time.
    """
    bus = Bus()
    made = settings(live=True)
    venue = RecordingBroker(made)
    async with Journal(tmp_path / "j.db") as book:
        trader = Trader(bus, settings=made, journal=book, broker=venue)
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        got = await trader.handle(Message(topic=SIGNALS, payload=signal()))
        assert isinstance(got, Intent)

    entries = [e for e in read(tmp_path / "j.db") if (e.context or {}).get("strategy")]
    assert entries
    ctx = entries[0].context
    assert ctx["spread_at_entry"] == pytest.approx(1.0), "the quoted spread, written down"
    assert ctx["waited"] is False, "this one was taken at market"
    assert ctx["stop_vol"] > 0, "the stop in the units the rules are written in"
    assert ctx["stop_scale"] >= 1.0
    assert ctx["hold_seconds"] > 0


def test_scale_out_waits_for_the_r_multiple():
    """Nothing comes off a trade that has not reached the level it banks at."""
    got = manage.partial(
        position(volume=1.0),
        intent(volume=1.0),
        GOLD,
        _scaling(),
        best=4402.0,  # 0.3R in front of a 4.9-wide stop
    )
    assert got is None


def test_scale_out_banks_part_once_it_is_there():
    take = manage.partial(
        position(volume=1.0),
        intent(volume=1.0),
        GOLD,
        _scaling(),
        best=4405.5,  # past 1R
    )
    assert take is not None
    assert take.volume == pytest.approx(0.5)


def test_scale_out_falls_back_to_best_when_no_current_price_is_given():
    """`current` is what it deals at; `best` is only the fallback.

    The docstring this replaced claimed the opposite - that reading the current
    price would let a retracement cancel a partial the trade had earned. That
    argument lost to a us30 position which logged "banking 50% at 1.5R" and
    booked -1.14, because a high-water mark is a gain that *was* there.
    """
    live = position(volume=1.0, price_current=4400.1)
    assert manage.partial(live, intent(volume=1.0), GOLD, _scaling(), best=4405.5) is not None


def test_scale_out_never_closes_the_whole_position():
    """A minimum-lot position cannot be halved, so it must run whole.

    The failure this guards against is not a refusal - it is a broker asked to
    close 0.005 of a 0.01 lot closing the lot instead, which turns a scale-out
    into a full exit that still looks like a scale-out in the log.
    """
    spec = replace(GOLD, volume_min=0.01, volume_step=0.01)
    got = manage.partial(position(volume=0.01), intent(volume=0.01), spec, _scaling(), best=4405.5)
    assert got is None


def test_scale_out_leaves_a_tradeable_remainder():
    """Both halves have to survive the volume step, not just the one banked."""
    spec = replace(GOLD, volume_min=0.02, volume_step=0.01)
    got = manage.partial(position(volume=0.03), intent(volume=0.03), spec, _scaling(), best=4405.5)
    assert got is None


def test_scale_out_rounds_down_to_the_volume_step():
    """Never up: the two halves together cannot exceed the position."""
    spec = replace(GOLD, volume_min=0.01, volume_step=0.01)
    take = manage.partial(position(volume=0.07), intent(volume=0.07), spec, _scaling(), best=4405.5)
    assert take is not None
    assert take.volume == pytest.approx(0.03)
    assert take.volume + 0.04 <= 0.07 + 1e-9


def test_scale_out_off_by_default():
    assert manage.partial(position(), intent(), GOLD, settings(), best=4405.5) is None


def test_scale_out_refuses_a_fraction_that_is_not_a_fraction(fraction):
    """At 1.0 it is a target, not a scale-out - there is no remainder to run."""
    got = manage.partial(
        position(volume=1.0),
        intent(volume=1.0),
        GOLD,
        _scaling(scale_out_fraction=fraction),
        best=4405.5,
    )
    assert got is None


async def test_a_scaled_trade_is_never_stale():
    """Part is already banked, so the thing this protects against is handled."""
    trader = _stale_trader()
    live = _live(scaled=True)
    trader._best[live.position.ticket] = 4400.4
    assert await trader._stale(live, age=900.0) is False


def test_the_stop_clears_the_broker_minimum_by_more_than_a_rounding():
    """The refusal that prompted this: 22 points against a 20-point floor.

    A 1.1 multiple of a 20-point minimum is two points of clearance, and the
    minimum is checked against the price when the order *lands*, not when it
    was built. Two points is what a quiet cross moves in between.
    """
    stop = _floor_for(spread=1e-05)
    clearance = (0.85754 - stop) / EURGBP.min_stop_distance
    assert clearance > 1.2, f"only {clearance:.2f}x the broker minimum"


def test_the_spread_is_part_of_the_clearance():
    """A buy fills at the ask and its stop is measured against the bid, so one
    spread of the margin is gone before the market has moved at all."""
    tight = 0.85754 - _floor_for(spread=0.0)
    wide = 0.85754 - _floor_for(spread=5e-05)
    assert wide > tight
    assert wide - tight == pytest.approx(5e-05, abs=1e-06)


def test_the_clearance_is_configurable_and_scales():
    near = 0.85754 - _floor_for(spread=0.0, margin=1.1)
    far = 0.85754 - _floor_for(spread=0.0, margin=1.5)
    assert far > near


def test_the_floor_never_pulls_a_wide_stop_in():
    """It may only push the stop away from the fill. A floor that tightened a
    stop would raise the position size for the same money at risk."""
    wide = 0.85000  # far below anything the floor would ask for
    assert _floor_for(spread=1e-05, anchored=wide) == wide


def test_a_buy_is_refused_while_price_is_still_falling():
    """Taking the other side of a run that has not finished is how a correct
    level becomes a stopped trade."""
    got = _momentum(pressure=-3.0, side=Side.BUY)
    assert got is not None
    assert got.gate == "momentum"


def test_a_sell_is_refused_while_price_is_still_rising():
    got = _momentum(pressure=3.0, side=Side.SELL)
    assert got is not None
    assert got.gate == "momentum"


def test_momentum_with_the_trade_is_not_refused():
    """The gate is about the run being *against* the trade. A buy into upward
    pressure is the level and the flow agreeing."""
    assert _momentum(pressure=3.0, side=Side.BUY) is None


def test_a_small_run_against_is_tolerated():
    """Some movement against is what arriving at a level looks like. The gate
    is for a run still in progress, not for any adverse tick."""
    assert _momentum(pressure=-0.5, side=Side.BUY) is None


async def test_a_candle_confirms_when_momentum_has_not():
    """Either witness is enough. Requiring both would refuse a clean rejection
    for happening inside one bar rather than across several."""
    hammer = [_candle(4400, 4401, 4399, 4400.5), _candle(4400, 4400.5, 4394, 4400.2)]
    trader = _confirming(candles=hammer, require_turn_vol=0.5, require_candle=True)
    assert await trader._rejected_at(_asks(pressure=-1.0)) is None


async def test_momentum_confirms_when_no_candle_has():
    """And the other way: a fast turn is not refused for lacking a bar to show
    for itself yet."""
    dull = [_candle(4400, 4401, 4399, 4400.5), _candle(4400.5, 4402, 4400, 4401.5)]
    trader = _confirming(candles=dull, require_turn_vol=0.5, require_candle=True)
    assert await trader._rejected_at(_asks(pressure=1.0)) is None


def test_chop_is_refused():
    got = _chop(0.05)
    assert got is not None
    assert got.gate == "chop"


def test_a_trend_is_not_refused():
    assert _chop(0.9) is None


def test_the_chop_gate_is_off_by_default():
    assert _chop(0.01, floor=0.0) is None


def test_size_leans_with_the_trend():
    assert _scale(1.0) == pytest.approx(1.3)
    assert _scale(0.0) == pytest.approx(0.7)
    assert _scale(0.5) == pytest.approx(1.0)


def test_size_is_unchanged_without_a_reading_or_a_span():
    assert _scale(None) == 1.0
    assert _scale(1.0, span=0.0) == 1.0


def test_the_scale_out_reads_the_price_that_exists_now():
    """A us30 position logged "banking 50% at 1.5R" and booked -1.14, because
    the trigger read a high-water mark while the close executed at market. The
    point of banking is to capture a gain that is there.
    """
    live = position(volume=1.0, price_open=4400.0)
    # Touched well past 1R, then fell back through the entry.
    got = manage.partial(live, intent(volume=1.0), GOLD, _scaling(), best=4410.0, current=4399.0)
    assert got is None


def _trail(name, push, **over):
    made = {"break_even_at": 1.0, "trail_vol": 2.0, "max_hold": 1800.0, "max_stop_scale": 3.0}
    made.update(over)
    return strategy(name, **made).protection("1m", push)[1]


async def test_the_momentum_threshold_follows_the_feeds_own_push():
    """Sized from the pushes the instrument actually makes, so a quiet one is
    not held to a loud one's bar."""
    trader = Trader(Bus(), settings=settings())
    await trader.start()
    trader._ensemble["gold"] = td_cusum.Ensemble()

    for _ in range(200):
        trader._note_push("gold", signal(features={"expected_push_vol": 2.75}))
    loud = trader._ensemble["gold"].threshold

    trader._push_vol.clear()
    trader._ensemble["gold"] = td_cusum.Ensemble()
    for _ in range(200):
        trader._note_push("gold", signal(features={"expected_push_vol": 1.66}))
    quiet = trader._ensemble["gold"].threshold

    assert quiet < loud
    assert quiet >= td_cusum.FLOOR


async def test_the_turn_asked_for_scales_with_the_instrument():
    """A turn worth 0.5v is most of a eurusd move and a fifth of a brent one,
    so one number asks two different questions."""
    trader = Trader(Bus(), settings=settings(require_turn_vol=0.5))
    await trader.start()

    quiet = trader._turn_wanted("gold")  # nothing learned yet
    assert quiet == 0.5

    for _ in range(300):
        trader._note_push("gold", signal(features={"expected_push_vol": 2.75}))
    loud = trader._turn_wanted("gold")
    assert loud > quiet


async def test_momentum_against_the_trade_earns_it_nothing():
    trader, live = await _motionless()
    group = td_cusum.Ensemble(intervals=("1m", "3m", "5m"))
    price = 100.0
    for step in range(0, 3600, 30):
        price -= 0.5
        group.push(price, unit=1.0, when=float(step))
    trader._ensemble["gold"] = group

    assert group.agreement < 0
    assert trader._still_building(live) is False


def test_heat_in_volatility_units_scales_by_the_stop_width():
    """`adverse_r` is in units of this trade's risk, which is the wrong
    denominator for comparing instruments - a 4v stop and a 1v stop both read
    1.0 when fully used."""
    trader = Trader(Bus(), settings=settings())
    live = _live(intent=intent(stop_vol=4.0))
    risk = abs(live.intent.entry - live.intent.stop)
    _heated(trader, live, [live.position.price_open - risk / 2])
    assert trader._heat_vol(live) == pytest.approx(2.0, abs=0.1)


def test_the_scale_out_names_the_reason_it_declined():
    """`scale_out_at` has been 1.0 for the life of this desk and not one
    scale-out has fired. `partial` declined from five places and every one
    returned a bare `None`, so there was no way to ask which."""
    from till_infinity.trading import manage

    made = settings(scale_out_at=1.0, scale_out_fraction=0.5)
    spec = td.SymbolSpec(symbol="XAUUSD", volume_min=0.01, volume_step=0.01, tick_size=0.01)
    pos = position(volume=1.0, price_open=4400.0, side=Side.BUY)
    want = intent(entry=4400.0, stop=4395.0)

    # Short of the trigger: the reason says by how much, in the unit the
    # trigger is set in.
    assert manage.partial(pos, want, spec, made, best=4402.0, current=4401.0) is None
    assert "short of the 1.00R trigger" in manage.why_no_bank()
    assert "+0.20R" in manage.why_no_bank()

    # Off entirely.
    manage.partial(pos, want, spec, settings(scale_out_at=0.0), best=4410.0, current=4410.0)
    assert manage.why_no_bank() == "scale_out_at is off"


def test_the_regime_scaler_is_off_until_a_band_is_set():
    """Every scaler here is off unless configured, and this one is not measured
    well enough to be on: seven days is the window in which a volatility
    conditional is most likely to be a period effect."""
    from till_infinity.trading import scaling

    assert scaling.by_regime(1.0, 0.0) == 1.0
    assert scaling.by_regime(5.0, 0.0) == 1.0
    assert scaling.by_regime(None, 0.35) == 1.0


def test_the_regime_scaler_cuts_both_tails_and_not_the_middle():
    """An inverted U, not a slope. Levels hold 86.4% when the next bar is
    expected to be the size of the last, and about 81.3% at *either* extreme,
    so a linear reading of the ratio would have the sign wrong on one whole
    side.

    The ratio is expected *change* of scale, not the regime level - the level
    is `vol_stretch` and it is flat across its quintiles."""
    from till_infinity.trading import scaling

    # Normal volatility keeps full size.
    assert scaling.by_regime(1.0, 0.35) == 1.0
    assert scaling.by_regime(1.2, 0.35) == 1.0

    quiet = scaling.by_regime(0.35, 0.35)
    loud = scaling.by_regime(3.0, 0.35)

    assert quiet < 1.0, "a compressed regime was not reduced"
    assert loud < 1.0, "a violent regime was not reduced"


def test_the_regime_scaler_treats_half_and_double_alike():
    """Log distance, because a ratio is multiplicative. Read additively, the
    quiet tail is bounded below by zero and would look far closer than the
    loud one."""
    from till_infinity.trading import scaling

    assert scaling.by_regime(0.5, 0.2) == pytest.approx(scaling.by_regime(2.0, 0.2))


def test_the_regime_scaler_never_enlarges_and_never_reaches_zero():
    from till_infinity.trading import scaling

    for ratio in (0.01, 0.5, 1.0, 2.0, 50.0):
        got = scaling.by_regime(ratio, 0.35, floor=0.5)
        assert 0.5 <= got <= 1.0, f"{ratio} gave {got}"


def test_a_feed_with_no_volatility_unit_publishes_nothing_rather_than_another_scale():
    """`features` falls back to its own ATR without a unit, which is a good
    number in a different scale. Publishing it under the same keys would put one
    journal column in two units, and both readings would look fine."""
    trader = _with_bars(_rising())
    # Deliberately not setting `_vol_bps`, which is a feed nothing has quoted.
    intent = _trend_intent()
    asyncio.run(trader._read_the_trend(intent))
    assert not [k for k in intent.features if k.startswith("regression_")]


