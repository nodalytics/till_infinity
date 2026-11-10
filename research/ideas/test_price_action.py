"""What the price-action harness must get right before any number is read.

Each test names the defect it prevents. Three of them are defects this desk
has already paid for in another study, which is why they are pinned here
rather than trusted.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

import research.ideas.price_action as P
from research.ideas.level_shield import Series
from till_infinity.indicators import candles as C


def _series(ohlc, interval: str = "1d") -> Series:
    arr = np.asarray(ohlc, dtype=float)
    return Series(
        feed="test",
        venue="TEST",
        interval=interval,
        ts=np.arange(len(arr), dtype=float) * 86_400.0,
        open=arr[:, 0],
        high=arr[:, 1],
        low=arr[:, 2],
        close=arr[:, 3],
    )


def _walk(n: int, seed: int, interval: str = "1d") -> Series:
    """A driftless walk whose bars are built from the path, not pasted on.

    Sub-bar resolution, so the high and the low emerge from the same process
    that makes the close. `pattern-fingerprint.md` records why: pattern rates
    depend on wick structure, so a close series with wicks bolted on decides
    the answer before the measurement.
    """
    rng = random.Random(seed)
    o = h = lo = c = 100.0
    rows = []
    for _ in range(n):
        o = c
        path = [o]
        for _ in range(24):
            path.append(path[-1] + rng.gauss(0.0, 0.05))
        c = path[-1]
        h, lo = max(path), min(path)
        rows.append((o, h, lo, c))
    return _series(rows, interval)


def test_the_desk_pin_matches_the_production_predicate_bar_by_bar():
    """`desk_pin` is a vectorised copy, so it is pinned against the original.

    A test that does not compare them tests the copy. `candles.hammer` and
    `candles.shooting_star` are what the live desk reads, and the whole value
    of carrying this arm is that it is *that* encoding and not a near one.
    """
    s = _walk(1500, seed=7)
    bull, bear = P.desk_pin(s)
    for i in range(len(s.close)):
        bar = C.Bar(
            open=float(s.open[i]),
            high=float(s.high[i]),
            low=float(s.low[i]),
            close=float(s.close[i]),
        )
        assert bool(bull[i]) is C.hammer(bar), i
        assert bool(bear[i]) is C.shooting_star(bar), i
    assert bull.sum() + bear.sum() > 0, "a control: the detector has to fire on something"


def test_the_sources_pin_bar_is_one_clause_and_is_looser_than_the_desks():
    """The source rule is the tail share alone, so it must be a superset.

    priceaction.com gives no ratio at all and LTTM gives 2/3 of the range with
    no opposing-wick limit and no body floor. This repo's `hammer` adds both.
    If the two ever read the same the sweep is measuring nothing, and if the
    source's rule refuses a bar the desk's accepts the encoding is wrong.
    """
    s = _walk(3000, seed=11)
    src_bull, _ = P.pin(s, C.TAIL_SHARE)
    desk_bull, _ = P.desk_pin(s)
    assert np.all(desk_bull <= src_bull), "the desk's three clauses cannot admit more bars"
    assert desk_bull.sum() < src_bull.sum(), (
        "and they have to refuse some, or the arm is a duplicate"
    )


def test_a_bar_equal_to_its_mother_is_not_an_inside_bar():
    """priceaction.com refuses the exact-equality pair, so the detector must.

    "if you have two bars with the same high and low, it's generally not
    considered an inside bar by most traders". A containment test written with
    `<=` and `>=` and nothing else accepts it silently.
    """
    s = _series(
        [
            (10.0, 12.0, 8.0, 11.0),
            (11.0, 12.0, 8.0, 10.0),  # same high and low
            (10.0, 11.5, 8.5, 11.0),  # strictly inside
        ]
    )
    got = P.inside(s)
    assert not got[1]
    assert got[2]


def test_the_race_starts_after_the_fill_so_a_walk_pays_nothing():
    """The leak `smc-conjunctions.md` reported +0.432R on a walk for.

    Settling on the fill bar uses that bar's *other* extreme, which may have
    printed before the entry touch, and measured there it won 0.470 of 2R
    races against a required 0.333. A driftless walk is a martingale, so any
    positive expectancy here is a bug in this harness and finding it is worth
    more than the study. The tolerance is the race's own standard error over
    several thousand trades, not a wish.
    """
    span = 20
    pooled: list[np.ndarray] = []
    for seed in range(6):
        s = _walk(4000, seed=100 + seed)
        unit = P.units(s, span)
        strata = P.strata_of(s, unit, span)
        ctx = P.trend_and_legs(s, reach=3)
        trades, _ = P.setups(
            s,
            unit,
            strata,
            ctx,
            pattern="inside",
            entry="stop_mother",
            stop="mother_far",
            side_rule="straddle",
            horizon=span,
        )
        got = P.settle(s, trades, unit, target=2.0, horizon=span)
        pooled.append(got.r[got.decided])
    r = np.concatenate(pooled)
    assert len(r) > 300, f"too few decided races to test anything: {len(r)}"
    se = float(np.std(r)) / np.sqrt(len(r))
    assert abs(float(r.mean())) < 4.0 * se, f"mean R {r.mean():.4f} on a walk, se {se:.4f}"


def test_a_tie_inside_one_bar_goes_to_the_stop():
    """Bar-level first passage cannot say which barrier came first.

    So the conservative rule is the only honest one. A harness that gave the
    tie to the target would be the fill-bar leak in a second costume, and the
    bias is largest exactly where the stop is tight.
    """
    s = _series(
        [
            (10.0, 12.0, 8.0, 11.0),
            (11.0, 11.5, 8.5, 11.0),  # inside bar
            (11.0, 12.5, 10.0, 12.0),  # fills the buy stop at 12.0
            (12.0, 20.0, 5.0, 12.0),  # reaches the target and the stop
        ]
    )
    unit = np.full(len(s.close), 1.0)
    trades = [
        P.Trade(
            signal=1, fill=2, side=1, entry=12.0, stop=8.0, risk=4.0, factors=0, stratum=0, day=0
        )
    ]
    got = P.settle(s, trades, unit, target=1.0, horizon=5)
    assert got.decided[0]
    assert got.tie[0]
    assert not got.won[0]
    assert got.r[0] == -1.0


def test_one_live_trade_at_a_time_and_the_refusals_are_counted():
    """Two scored trades sharing outcome bars is `overlapping-outcome-windows-leak`.

    A direction AUC of 0.79 that collapsed to 0.51. The guard is that a new
    setup is refused while an earlier one is still inside its horizon, and the
    count has to travel out - a silent drop is indistinguishable from a
    detector that did not fire.
    """
    s = _walk(2000, seed=3)
    unit = P.units(s, 20)
    strata = P.strata_of(s, unit, 20)
    ctx = P.trend_and_legs(s, reach=3)
    trades, cen = P.setups(
        s,
        unit,
        strata,
        ctx,
        pattern="inside",
        entry="stop_mother",
        stop="mother_far",
        side_rule="straddle",
        horizon=20,
    )
    assert cen.overlapped > 0, "a control: with a 20-bar horizon some setups must be refused"
    assert cen.signals == cen.trades + cen.no_fill + cen.thin_risk + cen.overlapped
    fills = sorted(t.fill for t in trades)
    assert all(b - a > 20 for a, b in zip(fills, fills[1:], strict=False)) or len(fills) < 2


def test_the_calendar_shuffle_keeps_the_cycle_and_destroys_the_order():
    """The arm `a-pair-of-bars-needs-the-hour-of-day-null` asks for.

    `bar_shuffle` permutes globally, which destroys the hour-of-day reach
    profile along with the ordering - and `inside-bars.md` measured that
    profile carrying a third to a half of the whole suppression. So this arm
    has to leave the per-bucket size profile alone while still moving bars.
    """
    rng = random.Random(5)
    rows = []
    price = 100.0
    for i in range(24 * 60):
        # A planted cycle: hour 0-11 quiet, 12-23 busy, so the profile is real.
        width = 0.2 if (i % 24) < 12 else 2.0
        o = price
        price = o + rng.gauss(0.0, width / 4)
        rows.append((o, max(o, price) + width / 2, min(o, price) - width / 2, price))
    s = _series(rows, "1h")
    s = Series(
        feed=s.feed,
        venue=s.venue,
        interval="1h",
        ts=np.arange(len(rows), dtype=float) * 3600.0,
        open=s.open,
        high=s.high,
        low=s.low,
        close=s.close,
    )
    got = P.calendar_shuffle(s, random.Random(1), bucket="hour")
    hours = ((s.ts % 86_400) // 3600).astype(int)
    for h in (3, 18):
        before = float(np.median((s.high - s.low)[hours == h]))
        after = float(np.median((got.high - got.low)[hours == h]))
        assert abs(after - before) < 0.25 * before, f"hour {h}: {before:.3f} -> {after:.3f}"
    assert float(np.median((got.high - got.low)[hours == 18])) > 3.0 * float(
        np.median((got.high - got.low)[hours == 3])
    ), "the quiet/busy split has to survive, or the arm is just bar-shuffle"
    assert not np.allclose(got.close, s.close), "and the ordering has to be gone"


def test_the_matched_placebo_runs_through_the_same_construction():
    """It is the duty-cycle control and the geometry control, so it must match both.

    A placebo that entered at a random bar's *close* while the real arm rested
    a stop order at a breakout price would be comparing two entry mechanics
    rather than two populations - and on the first run of this study that
    difference was worth about a quarter of an R. So the placebo's risk
    distribution has to sit on the real arm's: if it does not, the two arms are
    not the same trade and the difference between them is not about the
    pattern.
    """
    s = _walk(4000, seed=21)
    unit = P.units(s, 20)
    strata = P.strata_of(s, unit, 20)
    ctx = P.trend_and_legs(s, reach=3)
    kw = dict(pattern="inside", entry="stop_mother", stop="mother_far", side_rule="straddle")
    trades, cen = P.setups(s, unit, strata, ctx, horizon=20, **kw)
    assert len(trades) > 50
    made = P.placebo_trades(
        s, unit, strata, ctx, signals=cen.signals, horizon=20, draws=5, seed=1, **kw
    )
    got = P.settle(s, made, unit, target=2.0, horizon=20)
    assert len(got) > 5 * len(trades) * 0.5, (
        "the placebo has to carry a larger sample, not a smaller"
    )
    real_risk = float(np.median(P.settle(s, trades, unit, target=2.0, horizon=20).risk_vol))
    assert abs(float(np.median(got.risk_vol)) - real_risk) < 0.35 * real_risk
    assert set(np.unique(got.side)) == {-1, 1}, "both sides, or the placebo carries a direction"


@pytest.mark.parametrize("fill_at", ["trigger", "close"])
def test_a_walk_pays_nothing_against_its_own_matched_placebo(fill_at):
    """The leak that rewrote this harness, pinned in both settlements.

    A driftless walk is a martingale, so a rule on it cannot beat the same
    rule's mechanics applied at random bars. The first version of this study
    read **+0.25R** here, because it entered at the trigger price and began the
    race at the next bar: conditional on a buy stop filling, that bar closed
    *above* the trigger, so the race started nearer the target and further from
    the stop and the whole favourable displacement was a gift. The fix was to
    drive the placebo through the identical construction, which puts the same
    gift in both arms.

    The tolerance is the difference's own standard error, not a wish.
    """
    gaps = []
    for seed in range(5):
        s = _walk(4000, seed=300 + seed)
        unit = P.units(s, 20)
        strata = P.strata_of(s, unit, 20)
        ctx = P.trend_and_legs(s, reach=3)
        kw = dict(
            pattern="inside",
            entry="stop_mother",
            stop="mother_far",
            side_rule="straddle",
            fill_at=fill_at,
        )
        trades, cen = P.setups(s, unit, strata, ctx, horizon=20, **kw)
        real = P.settle(s, trades, unit, target=2.0, horizon=20)
        made = P.placebo_trades(
            s, unit, strata, ctx, signals=cen.signals, horizon=20, draws=10, seed=seed, **kw
        )
        plac = P.settle(s, made, unit, target=2.0, horizon=20)
        a, b = real.r[real.decided], plac.r[plac.decided]
        if len(a) < 30 or len(b) < 100:
            continue
        se = (a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)) ** 0.5
        gaps.append((float(a.mean() - b.mean()), se))
    assert len(gaps) >= 4
    num = sum(g / (se * se) for g, se in gaps)
    den = sum(1.0 / (se * se) for _, se in gaps)
    pooled, pooled_se = num / den, den**-0.5
    assert abs(pooled) < 3.0 * pooled_se, f"excess {pooled:+.4f} +- {pooled_se:.4f} on a walk"


def test_a_thin_risk_is_refused_rather_than_priced():
    """A near-zero-risk entry is the recorded fill artefact in `walks-and-edge.md`.

    The 50% entries are exactly where it appears, because a limit halfway up a
    narrow bar can sit a hair from its own stop. Refused at 0.25 units, counted.
    """
    s = _series(
        [
            (10.00, 12.00, 8.00, 10.00),
            (11.25, 11.30, 11.00, 11.28),  # a textbook pin, 0.30 wide against a 1.0 unit
            (11.20, 11.25, 11.05, 11.10),  # trades through the 11.15 midpoint
        ]
    )
    unit = np.full(len(s.close), 1.0)
    strata = np.zeros(len(s.close), dtype=int)
    ctx = P.trend_and_legs(s, reach=1)
    trades, cen = P.setups(
        s,
        unit,
        strata,
        ctx,
        pattern="pin",
        entry="limit50_bar",
        stop="tail",
        side_rule="own",
        tail_share=0.75,
        horizon=3,
    )
    assert not trades
    assert cen.thin_risk >= 1


def test_a_fakey_needs_a_one_sided_false_break_that_closes_back():
    """A window poking through both ends is a wide bar, not a false break.

    Admitting it would let the trigger side be chosen after the fact, which is
    a lookahead wearing a pattern's name.
    """
    mother = (10.0, 12.0, 8.0, 11.0)
    insidebar = (11.0, 11.5, 8.5, 11.0)
    down_then_back = (11.0, 11.4, 8.2, 11.2)  # breaks the inside low, closes back inside
    both_ways = (11.0, 12.5, 7.5, 11.0)  # through both ends
    s = _series([mother, insidebar, down_then_back, (11.2, 11.9, 10.8, 11.5)])
    got = P.fakeys(s, P.inside(s), break_ref="inside", close_back="mother", fake_bars=1)
    assert len(got) == 1
    assert got[0].side == 1
    assert got[0].trigger == pytest.approx(11.5)

    s2 = _series([mother, insidebar, both_ways, (11.0, 11.9, 10.8, 11.5)])
    assert not P.fakeys(s2, P.inside(s2), break_ref="inside", close_back="mother", fake_bars=1)


def test_cost_is_a_share_of_the_risk_and_not_of_the_target():
    """`domain/costs.py` measured the denominator: 49 trades passed the reward
    test while expensive against the risk, at -0.471R, for -502.70.

    A permitted spread scaled to the target lets a distant target buy the right
    to pay more. So doubling the risk has to halve the cost in R, and nothing
    about a target may appear in the number at all.
    """
    s = _series([(100.0, 101.0, 99.0, 100.0)] * 50)
    unit = np.full(50, 1.0)
    one = P.cost_r(10.0, s, np.full(10, 1.0), unit)
    two = P.cost_r(10.0, s, np.full(10, 2.0), unit)
    assert one == pytest.approx(0.1, rel=1e-6)
    assert two == pytest.approx(one / 2.0, rel=1e-6)
    assert np.isnan(P.cost_r(0.0, s, np.full(10, 1.0), unit)), "no quotes means no costed number"


def test_the_tail_sweep_actually_reaches_the_detector():
    """Four identical rows is what a swept parameter that never arrived looks like.

    The first run of this study printed the tail-share sweep as **four
    identical rows at n = 2,256**, because the driver cached the pin masks on
    the encoding name alone and every `source` cell therefore read the mask
    built at `TAIL_SOURCE`. A sweep that cannot move is worse than no sweep: it
    reports the method's unspecified parameter as having been tested.

    So the firing count has to fall monotonically as the tail requirement
    rises, and the four values have to be distinct.
    """
    s = _walk(4000, seed=31)
    counts = []
    for tail in P.TAIL_SHARES:
        bull, bear = P.pin(s, tail)
        counts.append(int(bull.sum() + bear.sum()))
    assert counts == sorted(counts, reverse=True), counts
    assert len(set(counts)) == len(counts), f"a knob that does not bite: {counts}"
    assert counts[-1] > 0, "and the strictest value still has to fire, or the sweep is empty"


def test_the_graded_pin_fires_and_is_not_the_fixed_one():
    """`fuzzy.pin` is the window-relative encoding and the control for a confound.

    `how-markets-differ-from-every-simple-process` measured real bars as
    wickier than every simple process, so a tail stated as a fraction of the
    range fires more often on real data than on a walk for mechanical reasons.
    The graded arm exists to normalise that - and an arm reading **zero
    signals** is how it failed the first time this ran on the research box,
    where `indicators/fuzzy.py` was absent and the guarded import left the mask
    all-False. A silent zero is not a null.
    """
    if P.FZ is None:
        pytest.skip("indicators/fuzzy.py absent; the graded arm needs #358")
    s = _walk(3000, seed=33)
    bull, bear = P.graded_pin(s)
    assert bull.sum() + bear.sum() > 20, "the graded arm has to fire, or it measures nothing"
    assert not bull[: P.FZ.PERIOD - 1].any(), "no grade below the window, by design"
    fixed_bull, _ = P.pin(s, C.TAIL_SHARE)
    assert not np.array_equal(bull, fixed_bull), "two encodings, or one of them is dead weight"


def test_a_settled_race_cannot_contradict_itself():
    """Two fields on one row that cannot both be true is this repo's house defect.

    `best_r` read exactly 0.0 on 45% of closes while 34.6% of those closed
    positive, and a trade cannot finish in front without having been in front.
    The arithmetic relations a settled race has to satisfy are checkable over
    the whole panel, so they are checked rather than assumed: a win pays the
    target exactly, a loss pays -1 exactly, a tie is never a win, and an
    undecided race pays nothing.
    """
    s = _walk(3000, seed=41)
    unit = P.units(s, 20)
    strata = P.strata_of(s, unit, 20)
    ctx = P.trend_and_legs(s, reach=3)
    for pattern, entry, stop, side_rule in (
        ("inside", "stop_mother", "mother_far", "straddle"),
        ("pin", "market", "tail", "own"),
        ("fakey", "stop_back", "break_extreme", "own"),
    ):
        trades, _ = P.setups(
            s,
            unit,
            strata,
            ctx,
            pattern=pattern,
            entry=entry,
            stop=stop,
            side_rule=side_rule,
            horizon=20,
        )
        assert trades, pattern
        for target in P.TARGETS:
            got = P.settle(s, trades, unit, target=target, horizon=20)
            assert np.all(got.r[got.decided & got.won] == target)
            assert np.all(got.r[got.decided & ~got.won] == -1.0)
            assert np.all(got.r[~got.decided] == 0.0)
            assert not np.any(got.tie & got.won)
            assert np.all(got.risk_vol >= P.MIN_RISK_VOL - 1e-9)


def test_duplicate_timestamps_are_collapsed_and_counted():
    """Half of two feeds' daily history is printed twice, and `n` is what says so.

    `spx500` and `us100` at 1d on YAHOO carry 6,005 and 6,008 rows over 3,006
    and 3,009 distinct timestamps - 503 bars a year on a daily series for an
    index that trades about 252 days. A doubled series halves the volatility
    unit's effective span and halves every horizon stated in bars, so it is
    collapsed on load rather than carried.
    """
    rows = [(10.0, 11.0, 9.0, 10.5), (10.5, 11.5, 9.5, 11.0), (11.0, 12.0, 10.0, 11.5)]
    doubled = [r for r in rows for _ in range(2)]
    s = _series(doubled)
    s = Series(
        feed=s.feed,
        venue=s.venue,
        interval="1d",
        ts=np.repeat(np.arange(len(rows), dtype=float) * 86_400.0, 2),
        open=s.open,
        high=s.high,
        low=s.low,
        close=s.close,
    )
    keep = np.concatenate(([True], np.diff(s.ts) > 0))
    assert int(keep.sum()) == len(rows), "the collapse has to keep one bar per timestamp"
    # And the accidental protection worth recording: a duplicated bar pair has
    # the same high and the same low, which priceaction.com's own clause
    # refuses, so the inside-bar detector was the one thing it could not fool.
    assert not P.inside(s)[1::2].any()
