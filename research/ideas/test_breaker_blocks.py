"""What `breaker_blocks.py` would get wrong without these.

    uv run pytest research/ideas/test_breaker_blocks.py -q

Not in `testpaths`, like every other test under `research/ideas`. Each one pins
a published rule or a settlement convention, and each names the defect it stops:
the two bugs that decided `order-block-zones.md` were a mirrored frame that lost
its whole short side and a window that silently dropped every fast-breaking
setup, and the defect that decided `price-action.md` was a fill-bar convention.
"""

from __future__ import annotations

import numpy as np
import pytest

import research.ideas.breaker_blocks as B


def frame(bars: list[tuple[float, float, float, float]]) -> dict[str, np.ndarray]:
    """Bars as `(open, high, low, close)`, on a 1h grid, with no spread."""
    a = np.array(bars, float)
    return {"ts": np.arange(len(a), dtype=np.int64) * 3600,
            "open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3],
            "spread": np.zeros(len(a))}


def leg(swing: int = 3) -> dict[str, np.ndarray]:
    """A swing high, a dip whose lowest bar is the order block, and a close through it.

    Bar 7 is the lowest low of the leg and so is the order block; bars 0-6 put a
    pivot high at bar 3 with `swing` bars either side.
    """
    bars = [
        (1.00, 1.02, 0.99, 1.01),   # 0
        (1.01, 1.04, 1.00, 1.03),   # 1
        (1.03, 1.06, 1.02, 1.05),   # 2
        (1.05, 1.20, 1.04, 1.06),   # 3  pivot high at 1.20
        (1.06, 1.08, 1.04, 1.05),   # 4
        (1.05, 1.07, 1.03, 1.04),   # 5
        (1.04, 1.06, 1.02, 1.03),   # 6
        (1.03, 1.05, 0.90, 0.95),   # 7  the lowest low: the order block
        (0.95, 1.10, 0.94, 1.08),   # 8
        (1.08, 1.25, 1.07, 1.24),   # 9  closes above 1.20: the break
    ]
    return frame(bars)


def leg_long() -> dict[str, np.ndarray]:
    """`leg()` with twenty bars of warmup in front and a flip and a retest behind.

    **The warmup is not padding.** `atr(14)` is `nan` for its first fifteen bars,
    so on `leg()` every `emit` returns before it reaches a trade - which is how
    two tests here passed while asserting over an empty list, the shape
    `a-test-that-asserts-nothing` warns about. The ramp is strictly increasing so
    it contains no interior pivot high of its own.
    """
    ramp = [(0.80 + 0.01 * k, 0.805 + 0.01 * k, 0.795 + 0.01 * k, 0.802 + 0.01 * k)
            for k in range(20)]
    tail = [
        (1.24, 1.25, 0.84, 0.85),   # 30  min(close, open) through 0.90: the flip
        (0.85, 0.95, 0.84, 0.94),   # 31  high reaches 0.90: the sell limit fills
        (0.94, 0.95, 0.70, 0.72),   # 32
        (0.72, 0.73, 0.50, 0.52),   # 33  far enough for a 2R target
        (0.52, 0.53, 0.45, 0.47),   # 34
    ]
    a = np.array(ramp, float)
    base = np.array([
        (1.00, 1.02, 0.99, 1.01), (1.01, 1.04, 1.00, 1.03), (1.03, 1.06, 1.02, 1.05),
        (1.05, 1.20, 1.04, 1.06), (1.06, 1.08, 1.04, 1.05), (1.05, 1.07, 1.03, 1.04),
        (1.04, 1.06, 1.02, 1.03), (1.03, 1.05, 0.90, 0.95), (0.95, 1.10, 0.94, 1.08),
        (1.08, 1.25, 1.07, 1.24),
    ], float)
    return frame([*map(tuple, a), *map(tuple, base), *tail])


def test_the_order_block_is_the_lowest_low_bar_between_the_swing_and_its_break():
    """LuxAlgo's construction, which is the whole reason this is testable.

    Without it the zone is drawn at whichever bar a reader liked, and
    `order-block-zones.md` could not settle the flip precisely because no rule
    said which bar it was.
    """
    f = leg()
    ph, _pl = B.pivot_flags(f["high"], f["low"], 3, 3)
    zs = B.order_blocks(f["open"], f["high"], f["low"], f["close"], ph, swing=3, band="range")
    assert len(zs) == 1
    ob_bar, btm, top, brk = zs[0]
    assert ob_bar == 7
    assert btm == pytest.approx(0.90)
    assert top == pytest.approx(1.05)
    assert brk == 9


def test_the_body_band_is_the_body_and_the_range_band_is_the_whole_bar():
    """Both are run because a reader who draws the block wick to wick gets a
    different entry and a different stop; neither is a presentation choice."""
    f = leg()
    ph, _ = B.pivot_flags(f["high"], f["low"], 3, 3)
    args = (f["open"], f["high"], f["low"], f["close"], ph)
    (_, _, top_range, _), = B.order_blocks(*args, swing=3, band="range")
    (_, _, top_body, _), = B.order_blocks(*args, swing=3, band="body")
    assert top_range == pytest.approx(1.05)   # the bar's high
    assert top_body == pytest.approx(1.03)    # max(open, close)


def test_a_wick_through_the_far_edge_is_not_a_breaker_and_a_body_close_is():
    """`min(close, open)` closes through the far edge - LuxAlgo's condition.

    A zone that flipped on a wick would flip on nearly every retest, which would
    make "flipped" mean "touched" and the study measure the refuted claim again.
    """
    c = np.array([1.00, 1.00, 1.00])
    mn = np.array([1.00, 0.95, 0.80])   # bar 1's body stays above 0.90, bar 2's does not
    piv = (np.array([], int), np.array([], float))
    flip, _dead, _conf = B.lifecycle(c, mn, *piv, 0.90, 1.05, 0)
    assert flip == 2


def test_a_breaker_is_deleted_when_a_close_clears_its_near_edge():
    """For a flipped demand zone the near edge is its top, so a close above the
    top ends it. Without a death the zone is tradeable forever and the firing
    rate stops meaning anything."""
    c = np.array([1.00, 0.85, 0.95, 1.10, 1.20])
    mn = np.array([1.00, 0.85, 0.95, 1.10, 1.20])
    piv = (np.array([], int), np.array([], float))
    flip, dead, _conf = B.lifecycle(c, mn, *piv, 0.90, 1.05, 0)
    assert (flip, dead) == (1, 3)


def test_confirmation_is_charged_the_swing_lookback_in_bars():
    """EmreKb's confirmation is a fresh swing inside the broken band, and a swing
    is only known `swing` bars after it prints. Returning the pivot's own bar
    would be look-ahead worth the whole delay."""
    n = 30
    c = np.full(n, 0.80)
    c[0] = 1.00
    mn = c.copy()
    piv_bars = np.array([10], int)
    piv_px = np.array([0.95], float)      # inside [0.90, 1.05]
    flip, _dead, conf = B.lifecycle(c, mn, piv_bars, piv_px, 0.90, 1.05, 0, swing=4)
    assert flip == 1
    assert conf == 14


def test_a_pivot_outside_the_band_does_not_confirm():
    n = 30
    c = np.full(n, 0.80)
    c[0] = 1.00
    piv_bars, piv_px = np.array([10], int), np.array([0.50], float)
    _flip, _dead, conf = B.lifecycle(c, c.copy(), piv_bars, piv_px, 0.90, 1.05, 0, swing=4)
    assert conf == -1


def test_the_stop_wins_when_both_barriers_are_reachable_in_one_bar():
    """There are no ticks to break the tie, so the bar is read against the trade.

    `a-martingale-cannot-pay`: settling a 2R race on the fill bar the other way
    won 0.470 against a required 0.333.
    """
    # a long from 1.00, stop 0.99, target 1.02; bar 1 spans both
    o = np.array([1.00, 1.00, 1.00])
    h = np.array([1.00, 1.05, 1.00])
    lo = np.array([1.00, 0.95, 1.00])
    c = np.array([1.00, 1.00, 1.00])
    r, why, _bars = B.settle(o, h, lo, c, 0, +1, 1.00, 0.99, 2.0, hold=3)
    assert why == "stop"
    assert r == pytest.approx(-1.0)


def test_a_target_on_the_fill_bar_needs_a_close_beyond_it():
    """A resting limit is filled from the far side, so that bar's target-side
    extreme most likely printed before the fill. Only a close proves otherwise -
    the convention `mt5bt.engine.walk` uses and the one `price-action.md` paid
    +0.2234R on a walk for getting the other way round."""
    o = np.array([1.00, 1.00])
    h = np.array([1.03, 1.00])   # reaches the 1.02 target on the fill bar
    lo = np.array([0.995, 1.00])
    c_short = np.array([1.00, 1.00])   # ... but closes below it
    r, why, _ = B.settle(o, h, lo, c_short, 0, +1, 1.00, 0.99, 2.0, hold=2)
    assert why != "target"
    c_long = np.array([1.025, 1.00])   # closes beyond it
    r, why, _ = B.settle(o, h, lo, c_long, 0, +1, 1.00, 0.99, 2.0, hold=2)
    assert (why, r) == ("target", pytest.approx(2.0))


def test_a_gap_through_the_target_pays_more_than_the_target():
    """The only way a trade prints beyond its own target, and the only place the
    exit price is not one of the two barriers."""
    o = np.array([1.00, 1.05])
    h = np.array([1.00, 1.06])
    lo = np.array([1.00, 1.04])
    c = np.array([1.00, 1.05])
    r, why, _ = B.settle(o, h, lo, c, 0, +1, 1.00, 0.99, 2.0, hold=2)
    assert why == "target_gap"
    assert r == pytest.approx(5.0)


def test_a_trade_that_reaches_neither_barrier_is_unresolved_not_a_loss():
    """`1/(1+N)` is the infinite-horizon rate. With a finite `HOLD` a timed-out
    trade reached neither barrier, so a walk reads *below* the arithmetic rate
    and the comparison has to be made on the resolved trades."""
    o = h = lo = c = np.full(5, 1.00)
    r, why, _ = B.settle(o, h, lo, c, 0, +1, 1.00, 0.99, 2.0, hold=5)
    assert why == "time"
    assert r == pytest.approx(0.0)


def test_a_limit_on_the_wrong_side_of_the_market_is_refused():
    """`min(close, open) < btm` can be satisfied by an up-closing bar's open
    alone, which leaves the sell limit at or below the market. Filling it would
    make the entry a market order wearing a limit's settlement rules."""
    f = leg_long()
    unit = B.atr(f["high"], f["low"], f["close"])
    rows, tally = B.zones_and_trades(f, unit, False, 0.0, swing=3, targets=(2.0,))
    assert tally["zones"] == 1
    assert tally["flipped"] == 1
    flips = [r for r in rows if r["arm"] == "flip"]
    assert len(flips) == 1, "the fixture must produce the breaker trade being tested"
    assert flips[0]["side"] == -1          # a flipped demand zone is traded short
    assert flips[0]["fill"] == 31          # the first bar whose high reaches 0.90
    assert tally["wrong_side"] == 0        # the flip bar closed below the entry
    # ... and the same zone with the order on the wrong side is refused: declare
    # the flip on a bar that closes back above the entry and nothing is emitted.
    g = dict(f)
    g["close"] = f["close"].copy()
    g["close"][30] = 0.95                  # above btm = 0.90, so no resting limit
    rows2, tally2 = B.zones_and_trades(g, unit, False, 0.0, swing=3, targets=(2.0,))
    assert tally2["flipped"] == 1          # `min(close, open)` still flipped it
    assert not [r for r in rows2 if r["arm"] == "flip"]
    assert tally2["wrong_side"] >= 1


def test_the_mirrored_frame_produces_the_mirrored_trade():
    """The bug that cost `order-block-zones.md` its entire supply side: every
    predicate must stay long-logic and the side must come from the frame.

    Negating a frame bar for bar must give the same trade with the opposite
    reported side and the same R, because R is scale-free and the rules are
    symmetric.
    """
    f = leg_long()
    neg = {"ts": f["ts"], "spread": f["spread"], "open": -f["open"], "close": -f["close"],
           "high": -f["low"], "low": -f["high"]}
    unit = B.atr(f["high"], f["low"], f["close"])
    unit_neg = B.atr(neg["high"], neg["low"], neg["close"])
    assert unit[~np.isnan(unit)] == pytest.approx(unit_neg[~np.isnan(unit_neg)])
    a, _ = B.zones_and_trades(f, unit, False, 0.0, swing=3, targets=(2.0,))
    b, _ = B.zones_and_trades(neg, unit_neg, True, 0.0, swing=3, targets=(2.0,))
    assert a, "the fixture produced no trades, so the comparison below is vacuous"
    assert [r["arm"] for r in a] == [r["arm"] for r in b]
    assert [r["R_gross"] for r in a] == pytest.approx([r["R_gross"] for r in b])
    assert [r["side"] for r in a] == [-r["side"] for r in b]


def test_the_placebo_never_sits_on_an_order_block_bar():
    """The property the placebo removes is named: *this geometry with no order
    block*. A placebo drawn at order blocks measures the claim twice and
    `the-placebo-arm-selects-the-null` is what that costs."""
    rng = np.random.default_rng(3)
    bars = B._bars_from_steps(rng.standard_t(4.0, (4000, 32)) * 1e-4 / np.sqrt(32), 1.10)
    bars["ts"] = np.arange(4000, dtype=np.int64) * 3600
    bars["spread"] = np.zeros(4000)
    unit = B.atr(bars["high"], bars["low"], bars["close"])
    ph, _pl = B.pivot_flags(bars["high"], bars["low"], B.SWING, B.SWING)
    zs = B.order_blocks(bars["open"], bars["high"], bars["low"], bars["close"], ph)
    ob_bars = {p for p, *_ in zs}
    rows, tally = B.zones_and_trades(bars, unit, False, 0.0, targets=(2.0,))
    anchors = {r["anchor"] for r in rows if r["arm"] == "placebo"}
    assert anchors
    assert not (anchors & ob_bars)
    assert tally["placebo_pool"] >= len(anchors)


def test_the_placebo_matches_the_breaker_on_zone_height_and_duty_cycle():
    """Distance-matched and rate-matched, which are two different controls.

    Without the height match the placebo is a different trade geometry and
    `a-return-rate-is-geometry` explains any gap; without the count match the
    two standard errors are not comparable and an arm that trades less reads
    better on a net-negative book for no other reason.
    """
    rng = np.random.default_rng(5)
    n = 20_000
    bars = B._bars_from_steps(rng.standard_t(4.0, (n, 32)) * 1e-4 / np.sqrt(32), 1.10)
    bars["ts"] = np.arange(n, dtype=np.int64) * 3600
    bars["spread"] = np.zeros(n)
    unit = B.atr(bars["high"], bars["low"], bars["close"])
    rows, _ = B.zones_and_trades(bars, unit, False, 0.0, targets=(2.0,))
    flip = [r["height_u"] for r in rows if r["arm"] == "flip"]
    plc = [r["height_u"] for r in rows if r["arm"] == "placebo"]
    assert len(plc) >= 0.8 * len(flip)
    assert np.median(plc) == pytest.approx(np.median(flip), rel=0.25)


def test_a_driftless_walk_pays_nothing_through_every_arm():
    """The leak guard. Any positive expectancy on a martingale is a bug, and on
    this desk finding one has repeatedly been worth more than the study."""
    rng = np.random.default_rng(9)
    n = 40_000
    bars = B._bars_from_steps(rng.standard_t(4.0, (n, 64)) * 1e-4 / np.sqrt(64), 1.10)
    bars["ts"] = np.arange(n, dtype=np.int64) * 3600
    bars["spread"] = np.zeros(n)
    unit = B.atr(bars["high"], bars["low"], bars["close"])
    rows = []
    for mirror in (False, True):
        part, _ = B.zones_and_trades(bars, unit, mirror, 0.0, targets=(2.0,))
        rows += part
    for arm in ("flip", "fade", "placebo"):
        x = np.array([r["R_gross"] for r in rows if r["arm"] == arm])
        assert len(x) > 100, arm
        se = x.std(ddof=1) / np.sqrt(len(x))
        assert x.mean() < 3 * se, f"{arm} pays {x.mean():+.4f} +-{se:.4f} on a walk"


def test_a_planted_edge_is_recovered_in_the_currency_it_was_planted_in():
    """The power plant has to be a control as well as a plant: `plant=g` adds
    `g` R over the holding window and the measured mean must move with it, or
    the power curve is a reading of nothing."""
    rng = np.random.default_rng(13)
    n = 20_000
    bars = B._bars_from_steps(rng.standard_t(4.0, (n, 32)) * 1e-4 / np.sqrt(32), 1.10)
    bars["ts"] = np.arange(n, dtype=np.int64) * 3600
    bars["spread"] = np.zeros(n)
    unit = B.atr(bars["high"], bars["low"], bars["close"])
    means = []
    for g in (0.0, 0.5, 1.0):
        rows, _ = B.zones_and_trades(bars, unit, False, 0.0, targets=(2.0,), plant=g)
        x = np.array([r["R_gross"] for r in rows if r["arm"] == "flip"])
        means.append(x.mean())
    assert means[0] < means[1] < means[2]


def test_folding_never_puts_two_sessions_in_one_bar():
    """`arange(n) // k` folds by index and walks across the weekend, putting
    Friday's close in the same bar as Monday's open. A timestamp bucket just
    yields fewer bars."""
    ts = np.array([0, 900, 1800, 2700, 3600, 1_000_000], dtype=np.int64)
    bars = {"ts": ts, "open": np.arange(6, dtype=float), "high": np.arange(6, dtype=float) + 1,
            "low": np.arange(6, dtype=float) - 1, "close": np.arange(6, dtype=float),
            "spread": np.zeros(6)}
    got = B.fold(bars, 3600)
    assert list(got["ts"]) == [0, 3600, (1_000_000 // 3600) * 3600]
    assert len(got["ts"]) == 3
    assert got["close"][0] == 3.0   # the first hour's last bar
    assert got["open"][1] == 4.0


def test_duplicate_timestamps_are_dropped_and_counted(tmp_path):
    """A duplicate bar doubles a detector's firing rate in silence, which is the
    shape of the `spx500`/`us100` daily defect found on 2026-11-10: 6,005 rows
    over 3,006 timestamps."""
    path = tmp_path / "DUPE.15m.npz"
    t = np.array([0, 900, 900, 1800], dtype=np.int64)
    np.savez(path, time=t, open=np.ones(4), high=np.ones(4), low=np.ones(4),
             close=np.ones(4), volume=np.zeros(4), spread=np.zeros(4))
    bars, dupes = B.read(path)
    assert dupes == 1
    assert list(bars["ts"]) == [0, 900, 1800]


def contiguous_bars(n: int = 4000, seed: int = 11) -> dict[str, np.ndarray]:
    """Bars that open **exactly** at the previous close, as 58-83% of the
    broker's 1h bars do, with varying shapes.

    The shapes have to vary: the planted gap is what happens when bar A's
    open-inside-its-range is applied at a level set by bar B's close, so a
    fixture whose bars all have the same shape reproduces itself and hides it.
    """
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.10, n))
    open_ = np.r_[100.0, close[:-1]]
    up = np.abs(rng.normal(0.0, 0.08, n)) * rng.choice([0.2, 1.0, 3.0], n)
    dn = np.abs(rng.normal(0.0, 0.08, n)) * rng.choice([0.2, 1.0, 3.0], n)
    return {"ts": np.arange(n, dtype=np.int64) * 3600, "spread": np.zeros(n),
            "open": open_, "close": close,
            "high": np.maximum(open_, close) + up, "low": np.minimum(open_, close) - dn}


def test_the_mean_gap_cannot_see_the_defect_and_the_distribution_can():
    """**The statistic was chosen after the question, twice, and this pins both.**

    The identity `close[i] - close[i-1] = (open[i] - close[i-1]) +
    (close[i] - open[i])` forces `mean(gap) = -mean(body)` for any series whose
    bars close above their opens with nil close-to-close drift. So a contiguous
    market and a gap-at-every-bar surrogate agree on the mean, and this study
    once withdrew a correct finding on that agreement. The median, the share of
    bars with no gap and the p90 separate them immediately.
    """
    real = contiguous_bars()
    fake = B.shipped_geom_bars(real, seed=3)
    r = B._gap_shape(real["open"], real["high"], real["low"], real["close"])
    f = B._gap_shape(fake["open"], fake["high"], fake["low"], fake["close"])

    # the market side of the fixture: contiguous by construction
    assert r["gap_zero"] == 1.0
    assert r["gap_median"] == 0.0
    # the surrogate gaps on essentially every bar, by a large share of a range
    assert f["gap_zero"] < 0.01, f
    assert f["gap_median"] > 0.3, f
    assert f["gap_p90"] > 10 * max(r["gap_p90"], 1e-9), (r, f)
    # ... and the two arms that fix it do
    for make in (B.contopen_bars, B.path_bars):
        g = make(real, seed=3)
        shape = B._gap_shape(g["open"], g["high"], g["low"], g["close"])
        assert shape["gap_zero"] == 1.0, make.__name__
        assert shape["gap_median"] == 0.0, make.__name__


def test_the_bridge_arm_opens_at_the_previous_close_and_owns_its_extremes():
    """`path_bars` is the arm of record because it fixes **both** defects.

    The open gap is the first; the second is that a surrogate which resamples
    highs and lows independently of the close path fires a stop where the path
    never went. A bar whose high and low are the running extremes of its own
    bridge cannot do that, and must contain its own open and close.
    """
    real = contiguous_bars()
    g = B.path_bars(real, seed=5)
    o, h, l_, c = (g[k] for k in ("open", "high", "low", "close"))
    assert o[1:] == pytest.approx(c[:-1], abs=1e-12)        # continuous
    assert np.all(h >= np.maximum(o, c) - 1e-12)            # the extremes contain the bar
    assert np.all(l_ <= np.minimum(o, c) + 1e-12)
    assert np.all(h > l_)
    # the one-bar step distribution is the real one, resampled and demeaned
    assert np.std(np.diff(c)) == pytest.approx(np.std(np.diff(real["close"])), rel=0.1)
    se = np.std(np.diff(real["close"])) / np.sqrt(len(c) - 1)
    assert abs(np.mean(np.diff(c))) < 4 * se


def test_the_bridge_arm_pays_nothing_through_every_trade_arm():
    """The leak check that matters for the arm of record.

    `shipped` pays the long-entry arm +0.1013R on this trade and that is the
    planted gap. An arm offered as the fix has to read at or below zero through
    the same settlement, or it is not a fix.
    """
    real = contiguous_bars(n=30_000, seed=17)
    frame = B.path_bars(real, seed=4)
    unit = B.atr(frame["high"], frame["low"], frame["close"])
    rows = []
    for mirror in (False, True):
        part, _ = B.zones_and_trades(frame, unit, mirror, 0.0, targets=(2.0,))
        rows += part
    for arm in ("flip", "fade", "placebo"):
        x = np.array([r["R_gross"] for r in rows if r["arm"] == arm])
        assert len(x) > 50, arm
        se = x.std(ddof=1) / np.sqrt(len(x))
        assert x.mean() < 3 * se, f"{arm} pays {x.mean():+.4f} +-{se:.4f} on the bridge"


def test_the_shipped_arm_draws_span_and_shape_independently():
    """`walk_with_bar_geometry` calls `r.choice(spans)` and `r.choice(shapes)`
    separately, so a bar's size and its body share are independent there.

    The first version of `shipped_geom_bars` drew both with one index, which
    **preserved a link the package breaks** - so it was not the shipped arm it
    claimed to be. A faithful copy must lose the correlation between a bar's
    range and its body share.
    """
    n = 20_000
    rng = np.random.default_rng(33)
    # A series where a wide bar always has a large body share and a narrow one
    # a small one, so the correlation is unmistakable in the source.
    span = np.where(rng.random(n) < 0.5, 1e-3, 1e-2)
    share = np.where(span > 5e-3, 0.9, 0.1)
    close = 1.0 + np.cumsum(rng.normal(0, 1e-3, n))
    open_ = close - share * span
    real = {"ts": np.arange(n, dtype=np.int64) * 3600, "spread": np.zeros(n),
            "open": open_, "close": close,
            "high": np.maximum(open_, close) + 0.05 * span,
            "low": np.minimum(open_, close) - 0.05 * span}

    def corr(f):
        sp = f["high"] - f["low"]
        ok = sp > 0
        return float(np.corrcoef(sp[ok], np.abs(f["close"] - f["open"])[ok] / sp[ok])[0, 1])

    assert abs(corr(real)) > 0.5                       # the source carries it
    assert abs(corr(B.shipped_geom_bars(real, seed=2))) < 0.2   # the package breaks it


def test_the_contopen_arm_breaks_the_body_to_wick_joint():
    """Its body **is** the close-to-close step and its wicks are resampled
    independently of it, so where a market's bodies and wicks move together the
    body-to-range ratio is rebuilt from marginals rather than carried.

    The shipped arm carries it exactly - body share is `|close_frac -
    open_frac|`, a function of the shape pair, and the pair travels. So a
    detector grading an order block by body share (`zones.ob_zones` at
    `PUSH_BODY` 0.70 and `ORIGIN_BODY` 0.45, and this file's `BAND=body`) is
    mis-nulled by `contopen` and better served by `shipped`; the reverse holds
    for a detector reading a bar's own move against its own shape. Neither arm
    is right for both, which is why both are reported.

    **The fixture has to carry the joint, or the assertion is empty**: a first
    version drew body and wicks independently, and there `contopen` reproduced
    the body share to 1% because rebuilding from marginals is correct when the
    marginals are all there is. These bars come in two regimes - a wide body
    with thin wicks, or a thin body with wide wicks - so a surrogate that
    crosses them is visible.
    """
    n = 20_000
    rng = np.random.default_rng(34)
    wide = rng.random(n) < 0.6                     # 60%, so the median is well defined
    body = np.where(wide, 1e-2, 1e-4) * rng.choice([-1.0, 1.0], n)
    wick = np.where(wide, 1e-5, 5e-3)
    close = 1.0 + np.cumsum(body)                  # open[i] == close[i-1]: step == body
    open_ = np.r_[1.0, close[:-1]]
    real = {"ts": np.arange(n, dtype=np.int64) * 3600, "spread": np.zeros(n),
            "open": open_, "close": close,
            "high": np.maximum(open_, close) + wick, "low": np.minimum(open_, close) - wick}

    def share(f):
        sp = f["high"] - f["low"]
        ok = sp > 0
        return float(np.median(np.abs(f["close"] - f["open"])[ok] / sp[ok]))

    base = share(real)
    assert base > 0.9, "the fixture must put its median bar in the wide-body regime"
    assert share(B.shipped_geom_bars(real, seed=3)) == pytest.approx(base, rel=0.05)
    crossed = share(B.contopen_bars(real, seed=3))
    assert crossed < 0.75, f"contopen should cross the regimes, read {crossed:.4f}"


def test_the_drifted_twin_keeps_the_drift_the_demeaned_one_removes():
    """`contdrift` exists so "the market's unconditional drift reaches none of
    these arms" is a measurement rather than prose."""
    n = 20_000
    drift = 1e-4
    c = 100.0 + drift * np.arange(n) + np.cumsum(np.random.default_rng(2).normal(0, 1e-3, n))
    real = {"ts": np.arange(n, dtype=np.int64) * 3600, "spread": np.zeros(n),
            "open": c, "close": c, "high": c + 1e-3, "low": c - 1e-3}
    per_bar = np.diff(real["close"]).mean()
    # A demeaned draw still has a realised drift of order sd / sqrt(n) - that is
    # the null's own sampling spread, not the series' drift, and it is why the
    # walk arms are averaged over several draws and many instruments.
    se = np.diff(real["close"]).std(ddof=1) / np.sqrt(n - 1)
    assert per_bar > 10 * se
    assert abs(np.diff(B.contopen_bars(real, seed=1)["close"]).mean()) < 4 * se
    assert np.diff(B.contdrift_bars(real, seed=1)["close"]).mean() == pytest.approx(
        per_bar, abs=4 * se)


def market_shaped(n: int = 3000, seed: int = 7) -> dict[str, np.ndarray]:
    """Bars with a drift, fat tails and wicks either side - not a flat fixture.

    `check_matches_package` has to run on input that exercises every branch the
    two implementations have: non-zero spans, bodies of both signs, and a close
    that is not the previous open.
    """
    rng = np.random.default_rng(seed)
    close = 1.10 + np.cumsum(1e-3 * rng.standard_t(4, n) + 2e-5)
    open_ = np.r_[1.10, close[:-1]]
    wick = np.abs(rng.normal(0, 8e-4, (n, 2)))
    return {"ts": np.arange(n, dtype=np.int64) * 3600, "spread": np.zeros(n),
            "open": open_, "close": close,
            "high": np.maximum(open_, close) + wick[:, 0],
            "low": np.minimum(open_, close) - wick[:, 1]}


def test_the_vectorised_copy_is_the_package_function_to_the_last_bit():
    """**A vectorised re-implementation is a second implementation.**

    `two-definitions-of-one-concept` is the house defect and this file produced
    it: the copy drew `span` and the shape pair with one index where
    `walk_with_bar_geometry` draws them with two independent `r.choice` calls,
    so the arm labelled shipped was not it, and the difference was worth 0.0229R
    on the long-entry arm. Nothing flagged it, because a surrogate that is wrong
    in a plausible way looks exactly like a surrogate. The only check that would
    have is this one: run the original beside the copy and assert **equality**.
    """
    worst = B.check_matches_package(market_shaped())
    assert set(worst) == {"open", "high", "low", "close"}
    assert max(worst.values()) == 0.0, worst


def test_the_faithfulness_check_fails_on_the_copy_it_was_written_for():
    """The control for the check above: it has to be able to fail.

    A check that cannot fail for its own reason is worse than none. Drawing the
    span and the shape with **one** index is the exact defect this file had, so
    reproducing it here must trip `check_matches_package`.
    """
    import random

    bars = market_shaped()

    def single_index(real, seed, pyrng=None):
        rng = np.random.default_rng(seed)
        o, h, l_, c = real["open"], real["high"], real["low"], real["close"]
        n = len(c)
        span = h - l_
        denom = np.where(span > 0, span, 1.0)
        of = np.where(span > 0, (o - l_) / denom, 0.5)
        cf = np.where(span > 0, (c - l_) / denom, 0.5)
        steps = np.diff(c)
        pick = rng.integers(0, n, n)           # the defect: one index for both
        price = float(c[0]) + np.cumsum(steps[rng.integers(0, len(steps), n)])
        sp = span[pick]
        low = price - cf[pick] * sp
        return {"ts": real["ts"], "spread": real["spread"], "low": low, "high": low + sp,
                "open": low + of[pick] * sp, "close": price}

    original, B.shipped_geom_bars = B.shipped_geom_bars, single_index
    try:
        with pytest.raises(AssertionError, match="differs from the package"):
            B.check_matches_package(bars)
    finally:
        B.shipped_geom_bars = original
    assert max(B.check_matches_package(bars).values()) == 0.0  # and back to clean


def test_no_two_instruments_share_a_null_realisation():
    """Two identical rows in a control arm is the cheapest tell there is.

    A `default_rng(SEED)` inside a per-instrument loop hands every instrument the
    same draw, and an N-instrument control arm becomes one realisation counted N
    times. The seeds here are `zlib.crc32(sym)`-derived for that reason, and this
    pins it: two different symbols must not produce the same surrogate, and the
    same symbol with a different draw index must not either.
    """
    bars = market_shaped(n=1200)
    seeds = [B.zlib.crc32(s.encode()) for s in ("EURUSD", "GBPUSD", "XAUUSD")]
    assert len(set(seeds)) == 3
    for make in (B.shipped_geom_bars, B.contopen_bars, B.iid_bars):
        closes = [make(bars, seed=s)["close"] for s in seeds]
        for i in range(len(closes)):
            for j in range(i + 1, len(closes)):
                assert not np.array_equal(closes[i], closes[j]), make.__name__
        a = make(bars, seed=seeds[0] + 1_000_003)
        assert not np.array_equal(a["close"], closes[0]), make.__name__
