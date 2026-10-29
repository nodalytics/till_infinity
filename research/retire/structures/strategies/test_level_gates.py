"""Gates that lived on the retired level strategies.

Moved out of `tests/test_scaling.py`, `tests/test_breaking.py` and
`tests/test_invariants.py` on 2026-10-29, when `scalper.py` and `LevelStrategy`
retired. Each asserts something about a method on that base class - the break-risk
gate in `quality`, the zma veto, that `consider` calls `risk_scale` - so none of
them has a subject any more.

The *break model itself* stays live in `structures` until that retires; what went
is the trading-side gate that read it.
"""


# From tests/test_scaling.py: asserts LevelStrategy.consider calls risk_scale - a claim about the retired base class

def test_sizing_reads_it():
    import inspect

    from till_infinity.trading.strategies import scalper

    assert "self.risk_scale(" in inspect.getsource(scalper.LevelStrategy.consider)


def test_the_gate_reads_both():
    import inspect

    from till_infinity.trading.strategies import scalper

    source = inspect.getsource(scalper.LevelStrategy.consider)
    assert "self.needs_context and bool(self.context)" in source


def test_the_strategy_passes_the_interval_through():
    """A weighting the sizing call never receives is a weighting that appears
    to work and does not - which is the defect this repository keeps finding."""
    import inspect

    import till_infinity.trading as td
    from till_infinity.trading.config import Settings
    from till_infinity.trading.strategies import scalper

    assert "interval" in inspect.signature(td.Strategy.risk_scale).parameters
    assert "positions, equity, peak, interval" in inspect.getsource(scalper.LevelStrategy.consider)

    made = Settings(interval_weight=(("1m", 0.25),))
    engine = td.STRATEGIES[mechanics.NAME](made)
    assert engine.risk_scale("gold", {"vol_bps": 10.0}, interval="1m") == 0.25
    assert engine.risk_scale("gold", {"vol_bps": 10.0}, interval="1h") == 1.0




# From tests/test_breaking.py: the break-risk gate, which lived in LevelStrategy.quality

def _gate(risk=None, ceiling=0.42):
    """Run the shared quality gate with a break estimate on the call."""
    import till_infinity.trading as td
    from till_infinity.trading.config import Settings
    from till_infinity.trading.models import Side

    engine = td.STRATEGIES["level-scalp"](
        Settings(max_break_risk=ceiling, min_probability=0.0, min_edge=0.0, min_base_rate=0.0)
    )
    features = {"probability": 0.9, "edge": 0.5, "base_rate_up": 0.5}
    if risk is not None:
        features["break_probability"] = risk
    return engine.quality("gold", features, Side.BUY, "5m")


def test_the_gate_is_off_by_default():
    """A gate that refuses trades is turned on deliberately - and the numbers
    behind this one were wrong once already."""
    from till_infinity.trading.config import Settings

    assert Settings().max_break_risk == 0.0
    assert _gate(risk=0.99, ceiling=0.0) is None


def test_every_strategy_runs_it_rather_than_one():
    """`quality` exists because `FadeToValue` overrode `consider` entirely and
    therefore ran none of the gates - the exemption was invisible from the
    configuration and the exempt strategy was taking most of the trades."""
    import inspect

    from till_infinity.trading.strategies import scalper

    assert "max_break_risk" in inspect.getsource(scalper.LevelStrategy.quality)


def test_the_learning_rate_favours_a_stable_gate():
    """Swept over the whole record: 0.05 scored 0.7304 AUC at 2.751 drift per
    100 observations, 0.02 scored 0.7206 at 1.110. Accuracy saturates long
    before stability does, and `max_break_risk` acts on this model's output -
    at the old rate the live weights moved 1.652, 1.174, 1.840 and 1.441 in
    four consecutive half-hours."""
    from till_infinity.structures.learning.breaking import RATE, Breaks

    assert RATE == 0.02
    assert Breaks().model.rate == RATE
    # And a restart uses the same one rather than a second copy of the number.
    model = Breaks()
    model.recipe = "something older"
    model.observe(Touch(approach_vol=1.0), "reject")
    assert model.model.rate == RATE




# From tests/test_invariants.py: the zma gate on cycle-scalp

def test_the_z_score_veto_can_only_remove_a_trade_and_only_when_earned(calls, rate, z, side):
    from till_infinity.trading.strategies.scalper import CycleScalp, zma_gate

    s = Settings()
    right = calls * rate
    features = {"zma_z": z, "zma_strong": 1.0, "zma_edge_calls": calls, "zma_edge_right": right}
    got = zma_gate(CycleScalp(settings=s), {"direction": side, "feed": "v75"}, features)
    assert got is None or got.gate == "zma_against"
    if not s.zma_earned(calls, right):
        assert got is None




# And the users of `_gate`, which followed its definition.

def test_a_level_likely_to_give_way_is_refused():
    """The top fifth by this estimate breaks 43.2% of the time against the
    bottom fifth's 16.9%, so the call is right 56.8% there against 83.1%."""
    got = _gate(risk=0.62)
    assert got is not None
    assert got.gate == "break_risk"
    assert "62%" in got.detail


def test_a_level_below_the_ceiling_passes():
    assert _gate(risk=0.20) is None


def test_a_call_with_no_estimate_is_not_refused():
    """Silence is the honest state until the model has 200 resolutions behind
    it. A level call with no break reading is not one with a low reading."""
    assert _gate(risk=None) is None




# From tests/test_scaling.py: `snap` declared `hold_seconds = 120` and this asserted
# that a ceiling cannot lengthen a trade past what the strategy asked for. The rule
# is still live on `Strategy.hold_for`; the 120 was snap's own number.

def test_a_strategy_asking_for_less_keeps_what_it_asked_for():
    """`snap` wants 120 seconds and a ceiling must not lengthen a trade."""
    assert _engine("snap").hold_for("1h") == 120.0
