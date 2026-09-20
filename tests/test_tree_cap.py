"""The pooled volatility tree is a memory floor, and it is now capped.

Dumps minutes apart and across two separate process runs gave byte-identical
counts - 482,886 `Mean`, 473,605 `EBSTNode`, 77,966 `TEBSTSplitter` - so the tree
reaches a size and stays there. About 282MB by river's own accounting, inside a
2.6GB container that has been OOM-killed 63 times.
"""

from __future__ import annotations

import random

from till_infinity.structures.vol.learned import MAX_TREE_MB, MEMORY_CHECK_EVERY, _model


def stream(n: int, seed: int = 7):
    rng = random.Random(seed)
    for _ in range(n):
        x = {f"f{i}": rng.gauss(0, 1) for i in range(16)}
        yield x, sum(x.values()) / 4 + rng.gauss(0, 0.5)


def test_the_production_model_carries_both_settings():
    """**Both were needed, and fixing one would have changed nothing.**

    River checks `max_size` only every `memory_estimate_period` learns, which at
    1,000,000 is 8.9 days at this desk's rate and had never once run. And the
    default cap is 500MB, so even when it ran it would not have fired against a
    282MB tree.
    """
    reg = _model()[-1]
    assert reg.max_size == MAX_TREE_MB == 32.0
    assert reg.memory_estimate_period == MEMORY_CHECK_EVERY == 5_000


def test_the_default_would_not_have_fired():
    """Recorded so the reasoning cannot quietly rot: 282MB is under 500MB."""
    from river import tree

    plain = tree.HoeffdingTreeRegressor(grace_period=50)
    assert plain.max_size == 500.0
    assert plain.memory_estimate_period == 1_000_000
    assert plain.max_size > 282.0, "the live tree sat under the default ceiling"


def test_a_cap_is_respected_and_the_model_still_predicts():
    """River deactivates its least promising leaves rather than refusing to grow,
    so a capped tree keeps predicting. A cap that silenced the model would be
    worse than the memory it saved."""
    from river import preprocessing, tree

    tight = preprocessing.StandardScaler() | tree.HoeffdingTreeRegressor(
        grace_period=50, max_size=2.0, memory_estimate_period=2_000
    )
    rows = list(stream(30_000))
    for x, y in rows:
        tight.learn_one(x, y)
    reg = tight[-1]
    used = getattr(reg, "_raw_memory_usage", 0) / 1e6
    assert used <= 2.0 * 1.6, f"cap of 2MB not respected: {used:.2f}MB"

    # And it still answers, with something finite and not a constant.
    said = [tight.predict_one(x) for x, _y in rows[:200]]
    assert all(isinstance(v, float) for v in said)
    assert len({round(v, 6) for v in said}) > 1, "a capped tree went mute"


def test_the_cap_actually_reduces_the_structure():
    """The point of the change. Same stream, capped against uncapped."""
    from river import preprocessing, tree

    rows = list(stream(30_000))
    sizes = {}
    for label, kwargs in (
        ("uncapped", {"grace_period": 50}),
        ("capped", {"grace_period": 50, "max_size": 2.0, "memory_estimate_period": 2_000}),
    ):
        m = preprocessing.StandardScaler() | tree.HoeffdingTreeRegressor(**kwargs)
        for x, y in rows:
            m.learn_one(x, y)
        sizes[label] = getattr(m[-1], "_raw_memory_usage", 0)
    assert sizes["capped"] < sizes["uncapped"], sizes
