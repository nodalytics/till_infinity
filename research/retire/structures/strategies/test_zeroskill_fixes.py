"""The two zero-skill fixes (`research/docs/zeroskill.md`): the policy departs only on a significant
lead over a scored default, and the cycles cap is judged against the same head on walks."""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.bus import Bus
from till_infinity.structures import cycles as cy
from till_infinity.trading.strategies import policy as pol
from till_infinity.trading.strategies.policy import DECAY, MARGIN_Z, PRIOR_SD, Policy, Score

# ------------------------------------------------------------------ the policy


def _feed(policy: Policy, arm: str, mean: float, n: int, rng: random.Random, sd: float = 0.75):
    for _ in range(n):
        policy.observe("gold", "5m", arm, rng.gauss(mean, sd))


def test_equal_arms_on_noise_leave_the_default_alone():
    """Nine arms with the same reward: the old rule departed in every warm context."""
    departed = 0
    for seed in range(40):
        rng = random.Random(seed)
        policy = Policy()
        for arm in policy.arms:
            _feed(policy, arm, -0.2, 300, rng)
        departed += policy.pick("gold", "5m")[0] != policy.fallback
    assert departed <= 2  # about 5% across the book by design; a few per cent here


def test_a_clearly_better_arm_still_wins():
    rng = random.Random(3)
    policy = Policy()
    fallback = policy.fallback.named()
    better = next(a for a in policy.arms if a != fallback)
    for arm in policy.arms:
        _feed(policy, arm, 0.6 if arm == better else -0.2, 300, rng)
    shape, why = policy.pick("gold", "5m")
    assert shape == policy.arms[better]
    assert "leads the default" in why


def test_no_arm_beats_a_default_that_has_not_been_measured():
    rng = random.Random(4)
    policy = Policy()
    fallback = policy.fallback.named()
    for arm in policy.arms:
        if arm != fallback:
            _feed(policy, arm, 1.0, 300, rng)
    shape, why = policy.pick("gold", "5m")
    assert shape == policy.fallback
    assert "cold" in why


def test_the_margin_is_z_standard_errors_of_the_difference():
    policy = Policy()
    fallback = policy.fallback.named()
    arm = next(a for a in policy.arms if a != fallback)
    for _ in range(100):
        policy.observe("gold", "5m", fallback, 0.0)
        policy.observe("gold", "5m", arm, 0.5)
    chosen = policy.choose("metals/oil|5m")
    assert chosen is not None  # constant rewards: no spread, any lead is real
    assert chosen[0] == arm
    assert chosen[2] == pytest.approx(0.0, abs=1e-6)
    assert pytest.approx(3.5) == MARGIN_Z


def test_the_memory_is_longer():
    assert pytest.approx(0.01) == DECAY
    assert pol.Ledger().decay == DECAY
    score = Score()
    for _ in range(1000):
        score.push(1.0, DECAY)
    assert score.effective() == pytest.approx((2 - DECAY) / DECAY, rel=1e-3)


def test_a_score_restored_without_its_spread_assumes_the_measured_one():
    old = Score.__new__(Score)
    old.__setstate__({"mean": 0.3, "seen": 400})  # written before `square` existed
    assert old.variance == pytest.approx(PRIOR_SD**2)


def test_a_restored_ledger_learns_at_the_current_decay(tmp_path):
    from tests.test_trading import settings
    from till_infinity.trading.service import Trader

    made = settings(state_dir=tmp_path)
    trader = Trader(Bus(), settings=made)
    trader.policy.ledger.decay = 0.05  # what an older state carried
    trader.policy.ledger.observe("gold:1h", "runner", -0.5)
    trader._remember_marks()
    after = Trader(Bus(), settings=made)
    after._recall_marks()
    assert after.policy.ledger.decay == DECAY
    assert after.policy.ledger.score("gold:1h", "runner") is not None


def test_a_counterfactual_default_credits_the_shape_ledger_only(tmp_path):
    from tests.test_trading import settings
    from till_infinity.trading.service import Trader

    trader = Trader(Bus(), settings=settings(state_dir=tmp_path))
    fallback = trader.policy.fallback.named()
    trader._credit("opportunity", "gold", "5m", 0.7, arm=fallback, entries=False)
    assert trader.policy.ledger.score("metals/oil|5m", fallback).seen == 1
    assert not trader.entries.ledger.cells
    # and the arm recorded at decision time wins over whatever the strategy wears now
    trader._credit("opportunity", "gold", "5m", 0.2, arm="some-shape")
    assert trader.policy.ledger.score("metals/oil|5m", "some-shape").seen == 1
    assert trader.entries.ledger.cells


# ------------------------------------------------------------------ the cycles cap


def test_the_walk_baseline_is_deterministic():
    a = cy.walk_skill(("1m", "15m"), bars=3000, seeds=1)
    cy._walk_skill.clear()
    b = cy.walk_skill(("1m", "15m"), bars=3000, seeds=1)
    assert a == b
    assert math.isfinite(a)


def test_skill_equal_to_the_walks_does_not_earn_the_cap(monkeypatch):
    monkeypatch.setattr(cy, "walk_skill", lambda intervals: 0.29)
    turns = cy.Turns()
    turns.settled = cy.WARM
    turns.depth_base_error = 100.0
    turns.depth_error = 100.0 * (1 - 0.30)  # skill 0.30: past the old bar, not past the walks
    assert turns.depth_skill > cy.MIN_SKILL
    assert not cy.earned(turns, ("1m", "15m", "1h"))
    turns.depth_error = 100.0 * (1 - 0.40)  # 0.11 beyond the walks
    assert cy.earned(turns, ("1m", "15m", "1h"))
    turns.settled = cy.WARM - 1
    assert not cy.earned(turns, ("1m", "15m", "1h"))


def test_scoring_the_default_leaves_the_engine_as_the_policy_set_it(monkeypatch, tmp_path):
    import till_infinity.trading as td
    from tests.test_trading import settings
    from till_infinity.trading.strategies.opportunity import Opportunity

    engine = td.STRATEGIES["opportunity"](settings(state_dir=tmp_path))
    policy = Policy()
    engine.policy, engine.arm = policy, "some-shape"
    seen = []
    parent = Opportunity.__mro__[1]
    monkeypatch.setattr(
        parent, "consider", lambda self, payload, **kw: seen.append(self.target_multiple) or "pass"
    )
    got = engine.consider_as(policy.fallback, {}, spec=None, tick=None, equity=1.0)
    assert got == "pass"
    assert seen == [policy.fallback.target]  # decided wearing the default
    assert engine.policy is policy
    assert engine.arm == "some-shape"


def test_no_counterfactual_where_the_policy_already_chose_the_default(tmp_path):
    import till_infinity.trading as td
    from tests.test_trading import settings
    from till_infinity.trading.service import Trader

    made = settings(state_dir=tmp_path)
    trader = Trader(Bus(), settings=made)
    engine = td.STRATEGIES["opportunity"](made)
    engine.policy, engine.arm = trader.policy, trader.policy.fallback.named()
    trader._score_default(engine, {"feed": "gold", "interval": "5m"}, None, None)
    assert not trader._untaken


def test_the_mean_rests_on_what_it_has_seen_not_on_its_first_reward():
    """A plain EWMA started at its first reward keeps 61% of its weight there after 50 at decay
    0.01 - the effective sample the margin assumed was 50, and was under three."""
    score = Score()
    for i in range(50):
        score.push(1.0 if i == 0 else 0.0, DECAY)
    assert score.mean == pytest.approx(1 / 50)
    assert score.effective() == pytest.approx(50.0)


def test_a_restored_score_rests_on_no_more_than_the_old_decay_allowed():
    old = Score.__new__(Score)
    old.__setstate__({"mean": 0.3, "seen": 400})
    assert old.effective() == pytest.approx(pol.LEGACY_EFFECTIVE)
    old.push(0.3, DECAY)  # and it carries on learning without raising
    assert old.seen == 401
