"""`opportunity`, `ride` and the shape policy, as they passed when retired.

Moved out of `tests/test_scaling.py` on 2026-10-28 with `opportunity.py` and
`policy.py`. `opportunity` was a **parameter space** rather than a point in one -
`PRESETS` mapped each named strategy to a `Shape`, and the policy chose between
shapes from what each had been worth. `research/docs/zeroskill.md` is why the
departure rule and the scored default exist.

These need fixtures that stayed in `tests/test_scaling.py`, so reviving one means
bringing those with it.
"""

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


def test_opportunity_triggers_across_the_fast_band_but_not_at_the_hour():
    """**The 15m floor was removed on 2026-09-22.**

    Its stated reason was "1m levels break 57.9% of the time against 1.4% at
    1h". That ladder was measured only on resolutions lasting five minutes or
    more, and the median 1m touch resolves in 120 seconds - unconditionally the
    1m rate is 13.4%. The ordering survives; the level of it does not, and it
    was the level that justified refusing the timeframe. See
    research/break-trade.md.

    The trade is now braked instead of refused, by `Settings.interval_weight`.
    What still holds: the trigger stays below the hour, because 1h is where
    this strategy's analysis frame starts.
    """
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings(intervals=("1m", "5m", "15m", "30m", "1h", "1d"))
    engine = td.STRATEGIES["opportunity"](made)
    assert "1m" in engine.intervals
    assert "5m" in engine.intervals
    # Still below the hour: the trigger fixes the stop, the analysis does not.
    assert "1h" not in engine.intervals
    assert "1d" not in engine.intervals
    # The hold is untouched: seconds to days, decided by the barriers.
    assert engine.hold_seconds == 0.0


def test_the_presets_recover_the_named_strategies():
    """The nine are points in this space, not separate things. If a preset
    drifts from the class it names, the map is a lie.

    **`PRESETS` still names strategies that retired on 2026-10-28**, so this
    checks the ones still registered. That is a real loose end rather than a
    tidy-up: a map whose keys do not resolve is the same defect this test was
    written to catch, pointing the other way. `PRESETS` lives in
    `strategies/opportunity.py` and goes when that does - see
    `docs/specs/2026-10-28-services-layout-design.md`.
    """
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings

    made = Settings()
    live = {n: s for n, s in td.PRESETS.items() if n in td.STRATEGIES}
    assert live, "no preset resolves at all, which is not a narrowing but a break"
    for name, shape in live.items():
        engine = td.STRATEGIES[name](made)
        assert engine.stop_multiple == shape.stop, name
        assert engine.target_multiple == shape.target, name
        assert engine.trail_vol == shape.trail, name
        assert engine.break_even_at == shape.protect, name
        assert engine.hold_seconds == shape.hold, name
        assert engine.pullback_fraction == shape.pullback, name
        assert engine.stop_floor_vol("5m") == shape.floor, name


def test_two_named_strategies_share_an_entry_and_differ_only_in_the_exit():
    """They *were* the same point, which was the argument for this module in
    one line. `sweep-aware` took `ride`'s exit on 2026-09-09 - measured at
    +0.556R a trade over 30,875 paired replays with spread charged - so the
    pair now differs in exactly the dimensions that measurement moved, and in
    no others."""
    import till_infinity.trading as td

    plain, swept = td.PRESETS["level-scalp"], td.PRESETS["sweep-aware"]
    ride = td.PRESETS["ride"]

    # The exit is ride's.
    assert (swept.target, swept.trail, swept.protect) == (ride.target, ride.trail, ride.protect)
    # The entry is still level-scalp's - stop, resting behaviour, size.
    assert (swept.stop, swept.floor, swept.pullback) == (plain.stop, plain.floor, plain.pullback)
    assert swept != plain


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


def test_the_cap_is_sized_for_a_day_long_hold():
    """`opportunity` holds to the 24h ceiling and roughly sixteen intents an
    hour arrive per busy feed, so a cap of 60 would evict most of them - and
    evict the slow ones, which biases every mean it feeds."""
    from till_infinity.trading.service import Trader

    assert Trader.MAX_UNTAKEN >= 384


def test_a_cold_policy_returns_the_measured_default_not_a_guess():
    """A policy that acts on four observations is how a five-stop sample became
    an instrument-wide sizing rule."""
    from till_infinity.trading.strategies.policy import Policy

    policy = Policy()
    shape, why = policy.pick("gold", "5m")
    assert shape == policy.fallback
    assert "cold" in why


def test_an_arm_cannot_win_until_it_has_been_seen_enough():
    from till_infinity.trading.strategies.policy import Policy

    policy = Policy()
    fallback = policy.fallback.named()
    arm = next(a for a in policy.arms if a != fallback)
    for _ in range(policy.MIN_SEEN):
        policy.observe("gold", "5m", fallback, -1.0)
    for _ in range(policy.MIN_SEEN - 1):
        policy.observe("gold", "5m", arm, 2.0)
    assert policy.pick("gold", "5m")[0] == policy.fallback
    policy.observe("gold", "5m", arm, 2.0)
    assert policy.pick("gold", "5m")[0] == policy.arms[arm]


def test_context_backs_off_rather_than_deciding_on_three_observations():
    """A thin cell falls back to the broader one. The family split is the one
    research/failing.md measures as actually separating."""
    from till_infinity.trading.strategies.policy import Policy, context_of

    assert context_of("boom_500_index", "5m") == ("boom|5m", "boom", "")
    assert context_of("gold", "1h")[1] == "metals/oil"
    assert context_of("volatility_75_index", "3m")[1] == "volatility"

    policy = Policy()
    fallback = policy.fallback.named()
    arm = next(a for a in policy.arms if a != fallback)
    # Warm at the family level only, the default included.
    for _ in range(policy.MIN_SEEN):
        policy.observe("boom_500_index", "1h", arm, 1.5)
        policy.observe("boom_500_index", "1h", fallback, -1.0)
    # A different interval on the same family still gets an answer.
    shape, why = policy.pick("boom_1000_index", "5m")
    assert shape == policy.arms[arm]
    assert why.startswith("boom")


def test_a_malformed_reward_cannot_own_the_policy():
    """Five intents of 1,757 carried an implied RR up to 30,338, and one of
    them touching produced +23R a trade across the whole book."""
    from till_infinity.trading.strategies.policy import CLIP, Policy

    policy = Policy()
    arm = next(iter(policy.arms))
    for _ in range(policy.MIN_SEEN):
        policy.observe("gold", "5m", arm, 30_338.0)
    score = policy.ledger.score("metals/oil|5m", arm)
    assert score is not None
    assert score.mean <= CLIP[1]


def test_each_distinct_point_is_its_own_arm():
    """`level-scalp` and `sweep-aware` were one vector under two names, and the
    ledger credited them as a single arm - which is what stopped one arm's
    evidence being split in half.

    Giving `sweep-aware` `ride`'s exit separates them, and that separation has
    a price: it is now a distinct arm and starts cold, so the learner knows
    nothing about it until it has its own thirty observations. That is a real
    cost of the change and it is asserted here rather than discovered later."""
    import till_infinity.trading as td
    from till_infinity.trading.strategies.policy import Policy

    policy = Policy()
    plain, swept = td.PRESETS["level-scalp"].named(), td.PRESETS["sweep-aware"].named()

    assert plain != swept
    assert plain in policy.arms
    assert swept in policy.arms


def test_opportunity_wears_the_shape_it_was_given():
    """And only the dimensions the engine reads - varying one nothing honours
    is a policy that appears to work and does not."""
    import till_infinity.trading as td
    from till_infinity.trading.strategies.opportunity import Shape

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


def test_it_now_carries_a_measured_default_that_brakes_without_blocking():
    """**It was off until 2026-09-22 and is now on**, because every strategy's
    entries were widened down to 1m and the *live* record for that band is
    -821.75 over 129 closes. Widening without the brake would have put six more
    strategies into the worst band on the book at full size.

    The values are gentle for a measured reason rather than a timid one: at 0.4
    the brake stopped shrinking positions and started **refusing** them - 0.4 of
    the risk budget no longer covers the broker's minimum 0.01 lot. A refusal is
    a different policy, and a biased one, since it lands on exactly the marginal
    trades and skews the sample the brake exists to protect.
    """
    from till_infinity.trading.config import Settings
    from till_infinity.trading.scaling import by_interval

    weights = Settings().interval_weight
    assert weights, "the default was emptied without a note"
    held = dict(weights)
    # A real reduction on the band the live record condemns...
    assert held["1m"] < 1.0
    assert held["5m"] < 1.0
    # ...and nothing at or above 30m is touched.
    assert by_interval("30m", weights) == 1.0
    assert by_interval("1h", weights) == 1.0
    # Gentle enough that a position shrinks rather than vanishing.
    assert min(held.values()) >= 0.5


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




# From tests/test_trading.py: the Shape floor and naming tests.

def test_every_plan_survives_a_similar_losing_run():
    """The plans differ in size and selectivity, not in shape."""
    for plan in tp.PLANS.values():
        assert 10 <= plan.losses_to_halt <= 14


def test_thesis_only_gives_the_trade_room_and_takes_less_of_it():
    """Six of twelve stopped trades later reached their target, so either the
    stops are wrong or the theses are. Every fix so far has assumed the first.
    This tests it by taking the stop out of the decision."""
    normal = take("level-scalp")
    roomy = take("thesis-only")
    assert isinstance(normal, Intent)
    assert isinstance(roomy, Intent)

    assert abs(roomy.entry - roomy.stop) > abs(normal.entry - normal.stop) * 3
    # The same money at risk over a wider stop buys proportionally fewer lots.
    assert roomy.volume < normal.volume
    # **The target used to be held still here, and holding it still was the
    # defect.** This test took the stop out of the decision by keeping the
    # target fixed, which is a clean experiment and also a 0.37 reward-to-risk
    # trade: `thesis-only` won 45.9% needing 73%, and lost 441 units over 159
    # trades while its targets earned 639 - recorded in `opportunity.Shape`
    # against a shape this class never read. Its live median reward-to-risk was
    # 0.40 over 361 decisions.
    #
    # So the answer to the docstring is neither: it was the *ratio*. Both
    # strategies now carry a per-strategy `reward_floor`, and a wider stop
    # buys a proportionally further target rather than the same one.
    # Not three times, and the shortfall is the interesting part: `level-scalp`
    # already aimed 1.26 times its own stop here, so the floor never fired for
    # it and only `thesis-only` moved. 18.10 against 6.16 is 2.94.
    assert abs(roomy.target - roomy.entry) > abs(normal.target - normal.entry) * 2.5
    for got in (roomy, normal):
        assert got.reward_to_risk >= 1.0 - 1e-6, f"{got.symbol} {got.side}: {got.reward_to_risk}"
    # `thesis-only` lands exactly on the floor, which is what a floor that binds
    # looks like; `level-scalp` is above it on its own merits.
    # Read off the class rather than written as a literal: the floors have moved
    # three times in a day and are now per strategy, so a literal would be stale
    # by the next reading of the broker record.
    assert roomy.reward_to_risk == pytest.approx(td.STRATEGIES["thesis-only"].reward_floor)
    # `level-scalp` aims 1.257 of its own stop and its floor is 1.05, so the
    # floor does not fire and it keeps its own geometry.
    want = max(1.257, td.STRATEGIES["level-scalp"].reward_floor)
    assert normal.reward_to_risk == pytest.approx(want, abs=0.01)


def test_a_stop_floor_no_longer_leaves_the_target_behind():
    """The defect that cost 441 units over 159 trades.

    The stop comes from the call's risk estimate and a floor; the target came
    from the modelled push, and nothing related them. So a floor that widened
    the stop to 4 volatility units against a 1.5v push placed the trade at 0.37
    reward to risk - a geometry needing a 73% win rate, taken by a strategy
    winning 46%.
    """
    from till_infinity.trading.strategies.opportunity import PRESETS

    shape = PRESETS["thesis-only"]

    assert shape.floor == 4.0
    assert shape.reward_floor >= 1.0, "a floored stop with no matching target"


def test_shapes_without_a_reward_floor_are_unchanged():
    """Every other preset must place exactly what it placed before."""
    from till_infinity.trading.strategies.opportunity import PRESETS

    for name, shape in PRESETS.items():
        if name == "thesis-only":
            continue
        assert shape.reward_floor == 0.0, f"{name} silently gained a reward floor"


def test_the_shape_name_only_changes_for_shapes_that_use_the_floor():
    """These names land in the journal; one that changes for everyone breaks
    every comparison against what came before."""
    from till_infinity.trading.strategies.opportunity import PRESETS

    plain = PRESETS["level-scalp"].named()
    floored = PRESETS["thesis-only"].named()

    assert plain.startswith("stop1f1/target1/")
    assert "target1r1/" in floored


def test_sweep_aware_carries_rides_exit_and_its_own_entry():
    """Measured: +0.556R a trade on 30,875 paired replays with spread charged.

    Only the exit moves. The stop and the entry behaviour are what the replay
    held constant, and changing them would make it a different trade rather
    than the same trade with a better exit.
    """
    from till_infinity.trading.strategies.opportunity import PRESETS

    sweep, ride = PRESETS["sweep-aware"], PRESETS["ride"]

    assert (sweep.target, sweep.trail, sweep.protect) == (ride.target, ride.trail, ride.protect)
    # ...and the entry side is still sweep-aware's own, not ride's.
    assert sweep.pullback == 0.0
    assert ride.pullback == 1.0
    assert sweep.stop == 1.0


def test_the_floor_never_compounds_the_two_estimates():
    """The first version added the clock to the model in log-odds, which assumes they are
    conditionally independent - and they are not, since both describe the same touch. It took a
    20% prior to 87% at ten bars. A floor assumes nothing: the result is either the model's own
    number or the clock's, never a product of both."""
    from till_infinity.structures.context.registry import clock_odds

    now = time.time()
    payload, features = _payload_at(now - 10 * 900)
    Trader._age_break_risk(payload, features, now)
    assert features["break_probability"] == pytest.approx(round(clock_odds(10.0), 5))
    # A model already more worried than the clock keeps its own reading.
    payload, features = _payload_at(now - 10 * 900, probability=0.95)
    Trader._age_break_risk(payload, features, now)
    assert features == {"break_probability": 0.95}


#: Every strategy whose live geometry argued for a reward floor, and the
#: measured median reward-to-risk that argued for it. See
#: `Strategy.reward_floor`.
#:
#: **Four entries left with the swing and cycle strategies on 2026-10-28** -
#: `approach-scalp` 0.51, `fade-to-value` 1.27, `runner` 1.49 and the two
#: cycle-turns. The medians were measured and are in
#: `research/retire/structures/strategies/test_swing_strategies.py` with the
#: tests that used them, because a median that argued for a floor is a
#: measurement about a strategy that ran, not a fact about this table.
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

#: The two that take their floor from `opportunity.Shape` instead of a class
#: attribute, because they are a parameter space rather than a point in one.
SHAPED = ("opportunity", "ride")


def test_every_strategy_carries_a_floor_except_the_parameter_space():
    """It was first set only on the seven with a sub-1.0 *median*, which left it
    off `sweep-aware` - the strategy that placed the 0.22 EURUSD short the floor
    was written for. A median above 1.0 says nothing about the tail, and the
    floor cannot cost a sound trade anything because it only moves a target out.

    `opportunity` and `ride` are excluded because `_wear` assigns theirs from
    `Shape.reward_floor`, which is the knob's original home.
    """
    made = settings()
    missing = {
        name: cls(made).reward_floor
        for name, cls in td.STRATEGIES.items()
        if name not in SHAPED and cls(made).reward_floor <= 0
    }
    assert missing == {}
    for name in SHAPED:
        assert td.STRATEGIES[name](made).reward_floor == 0.0, name
    # **`sweep-aware` is no longer exempt**, as of 2026-10-08. The exemption
    # rested on the floor barely touching it, which the record confirms - 11 of
    # 206 trades sit under 1.10 - and then overturns, because those eleven win
    # 45% and lose 0.181 R each. Its own breakeven is 1.09. It is floored like
    # everything else and the table has no hand-made exception left in it.
    assert td.STRATEGIES[EXEMPT](made).reward_floor == pytest.approx(1.50)


def test_no_floor_means_the_target_is_returned_untouched():
    # `opportunity` rather than a named strategy: it is the only family left
    # with a zero class default, because `_wear` assigns its floor per shape.
    engine = strategy("opportunity")
    assert engine.reward_floor == 0.0
    assert engine.floored_target(GOLD, td.Side.SELL, 100.0, 110.0, 99.99) == 99.99


def test_the_opportunity_space_still_sets_its_own_floor_over_the_class_default():
    """`Shape.reward_floor` is assigned as an instance attribute in `_wear`,
    exactly like the six knobs beside it. Declaring the field on `Strategy`
    must not take that away."""
    engine = strategy("opportunity")
    engine._wear(td.strategies.opportunity.Shape(stop=1.0, target=1.0, reward_floor=2.5))
    assert engine.reward_floor == 2.5


