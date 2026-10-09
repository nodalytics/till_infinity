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


# ---------------------------------------------------------------- depth, not size
#
# The cap above bounds the tree's **bytes**. It does not bound the **depth** of
# the structures inside it, and that is what took `structures` off the air: from
# 2026-09-23 11:53 until 2026-10-09 every `store.save` raised
# `RecursionError: maximum recursion depth exceeded`, 16 days in which nothing the
# desk learned was ever written down. Measured on the last file it managed to
# write: graph depth 333, of which 332 is one chain under
# `engine.vol._learned._model`, and 293 of that chain's 293 nodes hold `nan`.


def test_round_cannot_tame_a_nan():
    """Why a non-finite feature is different in kind, not degree.

    `TEBSTSplitter` bounds itself by rounding - `digits=1` - so a finite feature
    can only ever produce as many nodes as it has distinct rounded values. That
    bound is the whole reason the splitter is "truncated", and `nan` walks
    straight through it: rounding does nothing, and no comparison against it is
    ever true, so every observation is treated as a value never seen before.
    """
    import math

    from river.tree.splitter import TEBSTSplitter

    assert math.isnan(round(float("nan"), 1))
    assert TEBSTSplitter().digits == 1

    def right_spine(splitter) -> int:
        """Nodes down the right-hand chain, which is what pickle recurses over."""
        node, n = splitter._root, 0
        while node is not None:
            node, n = node._right, n + 1
        return n

    rng = random.Random(11)
    values = [rng.uniform(0.0, 5.0) for _ in range(2_000)]
    distinct = len({round(v, 1) for v in values})

    finite = TEBSTSplitter()
    for v in values:
        finite.update(v, 1.0, 1.0)
    # Bounded by how many distinct rounded values exist, not by how many
    # observations arrived - 2,000 bars, at most 51 of them can be new.
    assert distinct <= 51
    assert right_spine(finite) <= distinct

    poisoned = TEBSTSplitter()
    for _ in range(2_000):
        poisoned.update(float("nan"), 1.0, 1.0)
    assert right_spine(poisoned) == 2_000, "one node per observation, forever"


def test_a_non_finite_feature_makes_the_state_unpicklable():
    """The production failure in miniature, at the default recursion limit.

    This is the whole outage: a linked list one node long per observation, and
    `pickle` recurses once per node. Nothing here is about how much memory the
    tree uses, which is why the cap above could be correct and the save still
    fail every five minutes for a fortnight.
    """
    import pickle
    import sys

    from river.tree.splitter import TEBSTSplitter

    poisoned = TEBSTSplitter()
    for _ in range(1_200):
        poisoned.update(float("nan"), 1.0, 1.0)

    assert sys.getrecursionlimit() >= 1_000
    try:
        pickle.dumps(poisoned, protocol=pickle.HIGHEST_PROTOCOL)
    except RecursionError:
        pass
    else:  # pragma: no cover - the point of the test is that this raises
        raise AssertionError("1,200 nan observations should outrun the recursion limit")


def _row(**kwargs):
    """One feature row from a series with just enough history to produce one."""
    from till_infinity.structures.vol.learned import Learned

    learned = Learned()
    seen = learned._recent("eurusd|5m")
    seen.realised.extend([9.0, 11.0, 12.0])
    seen.close = 1.1000
    seen.log_volume = 5.0
    args = {
        "ew_bps": 10.0,
        "open_": 1.1000,
        "high": 1.1020,
        "low": 1.0990,
        "close": 1.1005,
        "hour": 3.0,
        "weekday": 2.0,
        "volume": 100.0,
        "interval_seconds": 300.0,
    }
    args.update(kwargs)
    return learned.features("eurusd|5m", **args)


def test_the_feature_row_is_finite_even_when_its_inputs_are_not():
    """**No non-finite value may reach the model.** The row is the boundary.

    Every clipped feature in `features` already survives this - `stretch`,
    `hour_share`, `focus_nats` and the guarded ratios. The `rel` family did not,
    and `har_rel` is the one that took the saves down: a `nan` estimate passed
    its `value <= 0` guard, because that comparison is false for `nan`.
    """
    import math

    for bad in (float("nan"), float("inf"), float("-inf")):
        for field in ("har_bps", "garch_bps", "range_bps", "stretch", "focus_nats"):
            row = _row(**{field: bad})
            assert row is not None, f"{field}={bad} should still produce a row"
            offenders = {k: v for k, v in row.items() if not math.isfinite(v)}
            assert not offenders, f"{field}={bad} leaked {offenders}"


def test_a_non_finite_scale_produces_no_row_at_all():
    """`ew_bps` is the denominator of the whole row, so `nan` there is not a
    feature fault - there is simply nothing to say about this bar."""
    assert _row(ew_bps=float("nan")) is None
    assert _row(ew_bps=0.0) is None


def test_the_damage_already_in_a_restored_tree_is_pruned():
    """`_finite` stops new ones; this clears the ones already written down.

    Deleting the entry is the documented way back - river rebuilds a splitter
    on `KeyError` - so the feature keeps being observed from the next bar. The
    test checks both halves: the chain is gone, and the model still learns the
    feature afterwards.
    """
    from till_infinity.structures.vol.learned import Learned

    learned = Learned()
    rng = random.Random(3)
    for _ in range(600):
        row = {"har_rel": float("nan"), "noise": rng.random(), "r1": rng.uniform(0.5, 2.0)}
        learned._model.learn_one(row, rng.uniform(5.0, 15.0))

    reg = learned._model[-1]

    def worst_chain() -> int:
        deepest, stack = 0, [reg._root]
        while stack:
            node = stack.pop()
            if node is None:
                continue
            kids = getattr(node, "children", None)
            if kids:
                stack.extend(k for k in kids if k is not None)
                continue
            for sp in (getattr(node, "splitters", None) or {}).values():
                cur, n = getattr(sp, "_root", None), 0
                while cur is not None:
                    cur, n = cur._right, n + 1
                deepest = max(deepest, n)
        return deepest

    # Well past anything a finite feature can reach - the rounding caps those
    # at the number of distinct values, which `test_round_cannot_tame_a_nan`
    # pins under 40. Production's worst chain was 293.
    before = worst_chain()
    assert before > 60, f"the fixture should be damaged, chain was {before}"

    went = learned.prune_nonfinite()
    assert went["splitters"] >= 1
    assert went["nodes"] >= 60
    assert worst_chain() < 40, "the non-finite chain should be gone"

    # And the feature is still observed - the splitter comes back.
    for _ in range(200):
        learned._model.learn_one(
            {"har_rel": rng.uniform(0.8, 1.2), "noise": rng.random(), "r1": 1.0},
            rng.uniform(5.0, 15.0),
        )
    rebuilt = any("har_rel" in (getattr(n, "splitters", None) or {}) for n in _every_leaf(reg))
    assert rebuilt, "deleting the entry must not stop the feature being observed"


def _every_leaf(regressor):
    stack, out = [regressor._root], []
    while stack:
        node = stack.pop()
        if node is None:
            continue
        kids = getattr(node, "children", None)
        if kids:
            stack.extend(k for k in kids if k is not None)
        else:
            out.append(node)
    return out


def test_pruning_a_clean_tree_changes_nothing():
    """It has to be safe to run on every restore, including the ones with
    nothing wrong - which, after the fix, is all of them."""
    from till_infinity.structures.vol.learned import Learned

    learned = Learned()
    rng = random.Random(5)
    for _ in range(600):
        row = {"har_rel": rng.uniform(0.5, 2.0), "noise": rng.random()}
        learned._model.learn_one(row, rng.uniform(5.0, 15.0))

    assert learned.prune_nonfinite() == {"splitters": 0, "nodes": 0}
