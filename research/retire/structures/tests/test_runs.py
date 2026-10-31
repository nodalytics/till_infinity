"""Swings as run boundaries - the formation experiment in `runs.py`.

What is worth pinning is the point-in-time discipline and the claim that
motivates the whole idea: a run boundary is the same price whichever
resolution watched it, where a bar extreme is not.
"""

from __future__ import annotations

import random

from till_infinity.structures.drawing import pips, runs
from till_infinity.structures.drawing.pips import Swing
from till_infinity.structures.vol.volatility import Volatility


def _vol(bps: float = 20.0) -> Volatility:
    vol = Volatility()
    price = 100.0
    for _ in range(60):
        price *= 1 + bps / 10_000
        vol.update(price)
    return vol


def _leg(prices: list[float], to: float, steps: int = 10) -> None:
    start = prices[-1]
    prices.extend(start + (to - start) * step / steps for step in range(1, steps + 1))


def _zigzag() -> tuple[list[int], list[float]]:
    prices = [100.0]
    for target in (101.0, 100.0, 101.5, 100.5):
        _leg(prices, target)
    return list(range(len(prices))), prices


def test_a_run_boundary_is_the_extreme_between_two_runs():
    times, prices = _zigzag()
    found = runs.points(times, prices, _vol())

    assert [point.swing for point in found] == [Swing.HIGH, Swing.LOW, Swing.HIGH]
    assert [round(point.price, 3) for point in found] == [101.0, 100.0, 101.5]


def test_confirmation_is_the_retracement_rather_than_a_bar_count():
    """A PIP waits a fixed number of bars; a run waits for the proof.

    The retracement past the threshold is what establishes the turn, so the
    bar that completes it is when the boundary became knowable - earlier on a
    sharp reversal, later on a slow one, which is the honest answer in both.
    """
    times, prices = _zigzag()
    found = runs.points(times, prices, _vol())

    for point in found:
        assert point.confirmed > point.time, "a boundary cannot be known as it happens"
        # And it is a real bar in the series, not an offset from one.
        assert point.confirmed in {float(t) for t in times}


def test_an_unfinished_run_is_never_emitted():
    """The trailing-swing look-ahead, which `pips.confirmed` exists to prevent.

    The last leg here is still running: its extreme may yet be exceeded, so
    emitting it would be claiming a turn nobody could have seen.
    """
    prices = [100.0]
    for target in (101.0, 100.0, 103.0):  # the final leg never reverses
        _leg(prices, target)
    times = list(range(len(prices)))

    found = runs.points(times, prices, _vol())

    assert all(point.index < len(prices) - 1 for point in found)
    assert 103.0 not in [round(point.price, 3) for point in found]


def test_a_pause_is_not_a_departure():
    """One observation that fails to extend is noise, not a turn."""
    prices = [100.0]
    _leg(prices, 101.0)
    prices.append(100.99)  # a tick back, far under the threshold
    _leg(prices, 102.0)
    times = list(range(len(prices)))

    found = runs.points(times, prices, _vol())

    assert not found, "a run ended on a pause rather than on a reversal"


def test_a_boundary_holds_its_price_across_resolutions():
    """The claim the whole idea rests on.

    One path, observed on two sampling grids. A run boundary should be the
    same price on both - the runs differ in length, the meeting point does not
    - where a bar extreme is whichever bar happened to be picked.

    Both are measured against **one** volatility, so the threshold is the same
    *price* move at each resolution. Without that control the finer series
    simply gets a finer threshold and the two are not comparable at all.
    """
    random.seed(7)
    fine = [100.0]
    for step in range(1200):
        drift = 0.9 * (1 if (step // 150) % 2 == 0 else -1)
        fine.append(fine[-1] * (1 + (drift + random.gauss(0, 2)) / 10_000))
    coarse = fine[::4]

    shared = Volatility()
    for price in coarse:
        shared.update(price)

    fine_runs = runs.points(list(range(len(fine))), fine, shared)
    coarse_runs = runs.points(list(range(0, len(fine), 4)), coarse, shared)
    fine_pips = pips.turns(pips.points(list(range(len(fine))), fine, 20))
    coarse_pips = pips.turns(pips.points(list(range(0, len(fine), 4)), coarse, 20))

    def agreement(fine_set, coarse_set) -> float:
        if not coarse_set:
            return 0.0
        hits = sum(
            any(abs(c.price - f.price) / f.price * 100 <= 0.02 for f in fine_set)
            for c in coarse_set
        )
        return hits / len(coarse_set)

    by_run = agreement(fine_runs, coarse_runs)
    by_pip = agreement(fine_pips, coarse_pips)

    assert by_run > by_pip, f"runs {by_run:.0%} did not beat pips {by_pip:.0%}"
    assert by_run >= 0.9


def test_the_two_formations_are_interchangeable_downstream():
    """Both produce `Point`, so `as_of`, `turns` and `form` cannot tell them apart.

    That is what makes the comparison possible at all: everything after
    formation is indifferent to which produced the swings.
    """
    times, prices = _zigzag()
    found = runs.points(times, prices, _vol())

    assert pips.turns(found) == [p for p in found if p.swing in (Swing.HIGH, Swing.LOW)]
    assert pips.as_of(found, found[0].confirmed) == [found[0]]


def test_an_origin_records_every_formation_that_found_it():
    """Agreement is the reason to merge rather than choose, so it must survive.

    A level both passes find has been confirmed by two methods that fail
    differently, and that is measurably stronger - 81.7% against 77.1% for
    run-only over 726 decisive interactions. None of that is visible unless the
    origin keeps both names.
    """
    from till_infinity.structures import levels as lv

    assert lv.agree("pip", "run") == "pip+run"
    # Order-independent: an origin that depended on which pass ran first would
    # be a fact about the code rather than about the level.
    assert lv.agree("run", "pip") == lv.agree("pip", "run")
    assert lv.agree("pip", "pip") == "pip"
    # And it accumulates rather than replacing.
    assert lv.agree(lv.agree("pip", "run"), "pivot:PP") == "pip+pivot:PP+run"


def test_merging_a_rediscovery_records_both_origins():
    from till_infinity.structures import levels as lv
    from till_infinity.structures.levels import Kalman, Level

    vol = _vol()
    found_by_pip = Level(feed="gold", interval="5m", filter=Kalman(mean=4400.0, variance=0.5))
    found_by_run = Level(
        feed="gold", interval="5m", filter=Kalman(mean=4400.05, variance=0.5), origin="run"
    )

    (merged,) = lv.merge([found_by_pip], [found_by_run], vol)

    assert merged.origin == "pip+run"
    assert merged is found_by_pip, "the rediscovery should fold in, not replace"


def test_it_refuses_a_series_too_short_to_have_a_run():
    vol = _vol()
    assert runs.points([1, 2], [100.0, 101.0], vol) == []
    assert runs.points([], [], vol) == []
