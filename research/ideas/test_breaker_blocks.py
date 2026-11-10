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


def test_the_geometry_walk_is_demeaned_and_the_drifted_twin_is_not():
    """The leak this file found in itself.

    Resampling `diff(close)` i.i.d. keeps the series' realised drift, and a
    drifting series cuts far more demand blocks than supply ones, so the long
    arm comes out net long and is handed the drift. The first run read
    **+0.1155R on the traded fade arm and +0.1839R on the synthetics** that way
    - a positive expectancy on a resampled walk, which cannot happen.
    """
    n = 20_000
    drift = 1e-4
    c = 100.0 + drift * np.arange(n) + np.cumsum(np.random.default_rng(2).normal(0, 1e-3, n))
    real = {"ts": np.arange(n, dtype=np.int64) * 3600, "spread": np.zeros(n),
            "open": c, "close": c, "high": c + 1e-3, "low": c - 1e-3}
    flat = B.geom_bars(real, seed=1)
    kept = B.geomdrift_bars(real, seed=1)
    per_bar = np.diff(real["close"]).mean()
    assert per_bar == pytest.approx(drift, rel=0.25)   # the noise adds its own endpoint
    # A demeaned draw still has a realised drift of order sd / sqrt(n) - that is
    # the null's own sampling spread, not the series' drift, and it is why the
    # walk arms are averaged over several draws and many instruments.
    se = np.diff(real["close"]).std(ddof=1) / np.sqrt(n - 1)
    assert abs(np.diff(flat["close"]).mean()) < 4 * se
    assert np.diff(kept["close"]).mean() == pytest.approx(per_bar, abs=4 * se)
    assert per_bar > 10 * se   # the planted drift is the larger quantity
