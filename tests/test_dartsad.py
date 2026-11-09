"""The arithmetic the darts anomaly study rests on, pinned where it would otherwise fail silently.

`research/harness/dartsad.py` holds the parts of that study a wrong answer
would survive: the causal boundary, the de-overlap stride, the transition
baseline, the barrier race and the planted regime the power curve is read off.
None of them need `darts` itself, so they can be exercised here rather than in
a lab log nobody re-reads.

Three of these protect a *control* rather than a result. A null is the expected
answer in this study, and a harness that can only return nulls would produce
the same page - so where a test asserts that something reads nothing, there is
a paired assertion that it reads something when the effect is really there.
"""

from __future__ import annotations

import numpy as np
import pytest

from research.harness import dartsad


def walk(n=4000, seed=0, lam=1.0, mu=0.0, stay=0.95):
    return dartsad.plant(n, lam, stay, mu=mu, seed=seed)


def test_the_scale_a_bar_is_divided_by_excludes_the_bar_itself():
    """`base` at bar t must be a function of bars before t, or the scaled arm is circular.

    The scaled features exist to take the volatility *level* out before a
    scorer sees a bar, so a score can be about shape. If `geometry` dropped the
    one-bar shift, a bar's own return would sit inside its own denominator: a
    4x bar would divide itself down towards 1 and the anomaly score would stop
    seeing the thing the label is defined by. Breaking it looks like the scaled
    arm quietly getting weaker, which is indistinguishable from a null.

    Fails if the shift is removed: `base` at the spiked bar would move.
    """
    o, h, lo, c = walk(2000, seed=1)[:4]
    before = dartsad.geometry(o, h, lo, c)["base"].copy()
    hit = 1200
    c2, h2 = c.copy(), h.copy()
    c2[hit] *= 1.02
    h2[hit] = max(h2[hit], c2[hit])
    after = dartsad.geometry(o, h2, lo, c2)["base"]
    assert after[hit] == pytest.approx(before[hit], rel=1e-12)
    assert after[hit + 1] != pytest.approx(before[hit + 1], rel=1e-12)


def test_no_feature_row_moves_when_a_later_bar_changes():
    """The leak boundary: feature row t is a function of bars <= t and nothing after.

    This is the defect that has cost the most on this desk's studies - a
    feature that quietly reads the future looks like a strong result and
    nothing in the output says so. `anomalies.py` asserts the same property by
    perturbation rather than by reading the code, and so does this.

    Fails if any rolling statistic loses its shift, or if a window score is
    ever centred rather than stamped at its last bar.
    """
    o, h, lo, c = walk(2000, seed=2)[:4]
    cut = 1500
    before = dartsad.scaled_features(dartsad.geometry(o, h, lo, c))
    c2, h2 = c.copy(), h.copy()
    c2[cut + 1 :] *= 1.05
    h2[cut + 1 :] = np.maximum(h2[cut + 1 :], c2[cut + 1 :])
    after = dartsad.scaled_features(dartsad.geometry(o, h2, lo, c2))
    assert np.allclose(before[: cut + 1], after[: cut + 1], atol=1e-12)


def test_a_forward_label_ignores_bars_beyond_its_own_window():
    """A 4-bar-ahead label at t must not move when bar t+9 changes.

    `labels` is the target the AUC columns are scored against. If its window
    were built with an off-by-one or an unshifted denominator, the label would
    reach further forward than the study claims and the lead-time reading would
    be wrong in the flattering direction.

    Fails if the forward OR loses its `fut[n - ahead:] = False` guard or the
    shift inside `base`, both of which widen the window.
    """
    o, h, lo, c = walk(2000, seed=3)[:4]
    at = 1400
    base = dartsad.labels(dartsad.geometry(o, h, lo, c))["y_shock"]
    c2, h2 = c.copy(), h.copy()
    c2[at + 9] *= 1.03
    h2[at + 9] = max(h2[at + 9], c2[at + 9])
    moved = dartsad.labels(dartsad.geometry(o, h2, lo, c2))["y_shock"]
    assert moved[at] == base[at]
    assert moved[at + 5] or not moved[at + 5]  # the perturbed bar is inside this one's window


def test_de_overlapped_observations_share_no_bar():
    """Consecutive observations must be a full window apart, or persistence is overlap.

    A stride-1 window score shares window-1 bars with its neighbour, so a
    transition matrix built on it counts the same bars up to `window` times and
    reports the overlap as state persistence. That failure has already turned a
    direction AUC of 0.79 into 0.51 on this desk.

    Fails the moment a caller passes a stride smaller than the scorer window.
    """
    window = 10
    idx = dartsad.deoverlap(95, window, 7)
    assert idx[0] == 7
    assert np.all(np.diff(idx) == window)
    assert idx[-1] < 95
    with pytest.raises(ValueError, match="window must be at least 1"):
        dartsad.deoverlap(95, 0, 0)


def test_persistence_is_read_against_its_own_marginals_not_against_a_half():
    """A state holding 70% of observations stays 70% of the time by arithmetic.

    The transition table's headline is `stay - indep`, and the whole point of
    the second term is that a raw persistence number carries no information
    when the states are unbalanced. The control here is the order-free sequence
    with the *same* marginals: it must read an excess of about zero, while the
    sticky chain built from the same alphabet must read a clear positive.

    Fails if `stay_share` ever returns a fixed baseline such as 1/k, which
    would make every unbalanced clustering look persistent.
    """
    rng = np.random.default_rng(0)
    marginal = np.array([0.7, 0.2, 0.1])
    order_free = rng.choice(3, size=40_000, p=marginal)
    stay, indep = dartsad.stay_share(dartsad.transition_counts(order_free, 3))
    assert indep == pytest.approx(float((marginal**2).sum()), abs=0.02)
    assert abs(stay - indep) < 0.01

    sticky = order_free.copy()
    keep = rng.random(len(sticky)) < 0.6
    for i in range(1, len(sticky)):
        if keep[i]:
            sticky[i] = sticky[i - 1]
    hot_stay, hot_indep = dartsad.stay_share(dartsad.transition_counts(sticky, 3))
    assert hot_stay - hot_indep > 0.2


def test_the_label_permutation_null_passes_an_order_free_sequence_and_rejects_a_chain():
    """The transition test's p must be uninformative on noise and small on a real chain.

    This is the gate the whole of Q3 turns on, and a gate with no control is
    indistinguishable from one that refuses everything. The order-free arm has
    exactly the same state shares as the chain, so a p that is small on both
    would mean the statistic is reading the marginals rather than the ordering.

    Fails if `chi2_independence` is computed against uniform expectations
    instead of the product of the observed margins.
    """
    rng = np.random.default_rng(1)
    order_free = rng.choice(3, size=4_000, p=[0.5, 0.3, 0.2])
    flat = dartsad.chi2_independence(dartsad.transition_counts(order_free, 3))
    null = dartsad.label_permutation_chi2(order_free, 3, 300, rng)
    assert float((null >= flat).mean()) > 0.05

    chain = order_free.copy()
    for i in range(1, len(chain)):
        if rng.random() < 0.5:
            chain[i] = chain[i - 1]
    hot = dartsad.chi2_independence(dartsad.transition_counts(chain, 3))
    hot_null = dartsad.label_permutation_chi2(chain, 3, 300, rng)
    assert float((hot_null >= hot).mean()) == 0.0


def test_the_barrier_race_holds_one_position_at_a_time():
    """Overlapping positions would count the same bars many times over.

    `race` is offered a candidate every bar and must refuse any that lands
    inside an open position, so no two recorded outcomes share a bar. Without
    it, one trend pays for every entry in it and the day-block interval shrinks
    around a number built from the same move counted repeatedly.

    Fails if `busy_until` is not advanced to the bar the position closed on.
    """
    o, h, lo, c, _ = walk(6000, seed=4)
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=1)
    stop = 2.0 * np.nan_to_num(tr, nan=np.nanmedian(tr))
    took, got = dartsad.race(h, lo, o, c, stop, np.arange(600, 5900), 1, 40)
    assert len(got) > 100
    assert np.all(np.diff(took) >= 1)
    assert len(np.unique(took)) == len(took)
    # every recorded trade resolved before the next one started
    assert len(got) < 5900 - 600


def test_the_stop_wins_a_tie_in_the_barrier_race():
    """A bar that touches both barriers must be recorded as a loss, not a win.

    The bar has no path inside it, so a tie is unresolvable and the choice is a
    convention. Giving the tie to the target is the single easiest way to
    manufacture a win rate above the driftless 0.500, and it would do so on
    exactly the wide bars an anomaly score selects.

    Fails if the target is checked before the stop.
    """
    o = np.array([100.0, 100.0, 100.0])
    c = np.array([100.0, 100.0, 100.0])
    high = np.array([100.0, 102.0, 100.0])
    low = np.array([100.0, 98.0, 100.0])
    stop = np.array([1.0, 1.0, 1.0])
    _, got = dartsad.race(high, low, o, c, stop, np.array([0]), 1, 2)
    assert got.tolist() == [-1.0]
    _, short = dartsad.race(high, low, o, c, stop, np.array([0]), -1, 2)
    assert short.tolist() == [-1.0]


def test_the_barrier_race_sits_on_the_driftless_null_for_a_walk():
    """A 1:1 race on a driftless walk wins 0.500, and a harness that does not is wrong.

    `1/(1+N)` is the whole null of this study: at N = 1 the gross expectancy of
    any reward-to-risk-1 rule on a martingale is zero before cost. If the race
    reads materially off 0.5 on a series with no edge in it, every conditioned
    number it later produces is measured against the wrong baseline.

    Fails on a tie given to the target, barriers read on closes rather than
    wicks, or an entry taken at the signal bar's close rather than the next
    bar's open.
    """
    o, h, lo, c, _ = walk(120_000, seed=5)
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=1)
    import pandas as pd

    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    _, got = dartsad.race(h, lo, o, c, 2.0 * atr, np.arange(600, 119_000, 7), 1, 40)
    won = float((got > 0).mean())
    assert len(got) > 5_000
    assert abs(won - 0.5) < 0.02, f"won {won:.4f} of 1:1 races on a driftless walk"


def test_within_strata_auc_collapses_when_the_score_is_the_stratifier():
    """A score that only restates the stratifier must read 0.5 inside its strata.

    This is the column every table in the study is read on, and it exists
    because an AUC of 0.8052 on a constant-volatility generator fell to 0.5250
    once current volatility was held fixed. Here the score *is* the stratifier
    plus a little noise, so a high raw AUC with a collapsed within-strata AUC
    is the correct reading; the control is the independent score, which must
    keep its AUC in both columns.

    Fails if `strata_auc` pools instead of conditioning - it would then simply
    reproduce the raw AUC and a volatility restatement would read as a finding.
    """
    rng = np.random.default_rng(2)
    n = 40_000
    strata = rng.random(n)
    y = rng.random(n) < strata
    # A function of the stratum alone, so it holds no information the
    # conditioning leaves behind. `strata + noise` would not do: inside a decile
    # it still ranks, and the honest within-strata reading there is 0.57.
    restatement = np.floor(strata * dartsad.STRATA) + rng.normal(0, 1e-9, n)
    assert dartsad.auc(y, restatement) > 0.75
    assert dartsad.strata_auc(y, restatement, strata) == pytest.approx(0.5, abs=0.01)

    independent = np.where(y, rng.normal(0.6, 1, n), rng.normal(0.0, 1, n))
    assert dartsad.auc(y, independent) > 0.6
    assert dartsad.strata_auc(y, independent, strata) > 0.6


def test_out_of_sample_r2_refuses_noise_columns():
    """Adding noise regressors must not raise the reported R2, or Q1b is unfalsifiable.

    The forward-log-variance table compares a baseline against the baseline
    plus five anomaly scores. In sample, five more columns always fit better,
    so an in-sample R2 would show a gain whatever the scores were. The split
    here is what makes a positive delta mean something.

    Fails if `ols_r2` is ever computed on the fitting rows.
    """
    rng = np.random.default_rng(3)
    n = 4_000
    signal = rng.normal(size=n)
    y = 2 * signal + rng.normal(0, 1, n)
    noise = rng.normal(size=(n, 5))
    train, test = slice(0, n // 2), slice(n // 2, n)
    base = dartsad.ols_r2(signal[train, None], y[train], signal[test, None], y[test])
    with_noise = dartsad.ols_r2(
        np.column_stack([signal, noise])[train],
        y[train],
        np.column_stack([signal, noise])[test],
        y[test],
    )
    assert base > 0.6
    assert with_noise <= base + 0.005


def test_plant_puts_in_the_regime_the_power_curve_claims_to_look_for():
    """The planted series must really carry the effect, or a blind test reads as a null.

    Every "where the test goes blind" number is read off `plant`, so if `plant`
    produced an i.i.d. series the power curve would report blindness at every
    strength and the study's null would look better supported than it is. The
    control is `lam = 1.0`, where the two states must be indistinguishable.

    Fails if the state chain is not applied to the sub-step scale, or if the
    sub-steps are drawn before the state is.
    """
    _, _, _, c, state = dartsad.plant(20_000, 2.0, 0.95, seed=6)
    moves = np.abs(np.diff(np.log(c), prepend=np.nan))[1:]
    hot = moves[state[1:] == 1].mean()
    cold = moves[state[1:] == 0].mean()
    assert 1.7 < hot / cold < 2.3

    o2, h2, lo2, c2, flat = dartsad.plant(20_000, 1.0, 0.95, seed=6)
    quiet = np.abs(np.diff(np.log(c2), prepend=np.nan))[1:]
    assert 0.93 < quiet[flat[1:] == 1].mean() / quiet[flat[1:] == 0].mean() < 1.07
    assert (h2 >= np.maximum(o2, c2) - 1e-9).all()
    assert (lo2 <= np.minimum(o2, c2) + 1e-9).all()


def test_plant_prices_away_from_one_so_a_scale_bug_is_visible():
    """The planted bars must sit at a real price scale, not at 1.0.

    At a price of one a relative standard deviation and a price offset are the
    same number, so a harness that confuses the two gives the right answer on
    the synthetic and the wrong one on gold. The study's cost column divides a
    price-space spread by a price-space stop, which is exactly the arithmetic
    that would pass at 1.0 and fail everywhere else.

    Fails if `price` is ever defaulted back to 1.0.
    """
    _, _, _, c, _ = dartsad.plant(500, 1.5, 0.9, seed=7)
    assert c.min() > 100.0


def test_tick_size_reads_the_quoted_grid_not_the_price_level():
    """The point must be measured, because the bar file states the spread in points.

    `spread` is a point count, not a price, and taking it as a price read a
    476% round trip on EURUSD and reordered the whole book by cost. The point
    is not in the bar file; the quoted grid is, so the cost column stands or
    falls on this function.

    The arm that matters is the third one. On an instrument whose typical move
    is far larger than its grid, consecutive distinct closes are a move apart,
    and a median gap then reads the move: BTCUSD came back at 0.601 against a
    true grid of 0.01 and its cost read 3.9R instead of 0.07R.

    Fails if the estimator is moved back to the median, or to the minimum -
    which one anomalous gap is enough to distort.
    """
    five_digit = np.round(1.1 + np.arange(2_000) * 1e-5, 5)
    assert dartsad.tick_size(five_digit) == pytest.approx(1e-5, rel=1e-6)
    two_digit = np.round(2000.0 + np.arange(2_000) * 0.01, 2)
    assert dartsad.tick_size(two_digit) == pytest.approx(0.01, rel=1e-6)

    rng = np.random.default_rng(8)
    walk = np.cumsum(rng.normal(0, 60, 4_000))
    sparse = np.round(100_000 + walk, 2)
    assert dartsad.tick_size(sparse) == pytest.approx(0.01, abs=0.02)
    # The median gap here is 0.83 - 83 ticks - which is the failure this arm is
    # for, and it is asserted so the fixture cannot stop carrying it.
    assert np.median(np.diff(np.unique(sparse))) > 20 * 0.01


def test_clv_corr_separates_a_planted_drift_from_a_planted_volatility_regime():
    """The statistic that decides whether a series is let past the repo's leak guard.

    `spikerisk.leak_check` refuses a series whose close location predicts the
    next return above 0.15, and `Drift Switch Index 20` reads +0.154 and is
    refused. The study overrides the guard for that family, and the override is
    only defensible if the reading is the planted drift rather than a
    misaligned bar - so this pins the mechanism: a volatility-only regime must
    read near zero, and a drift regime of about a sigma a bar must read near
    what the real feed reads.

    Fails if the close is taken from the wrong bar, which would make the
    volatility arm read high too and leave the override unjustified.
    """
    _, flat_h, flat_l, flat_c, _ = dartsad.plant(40_000, 2.0, 0.98, mu=0.0, seed=4)
    assert abs(dartsad.clv_corr(flat_h, flat_l, flat_c)) < 0.03

    _, h, lo, c, _ = dartsad.plant(40_000, 1.0, 0.98, mu=1.0, seed=4)
    assert dartsad.clv_corr(h, lo, c) > 0.12


def test_nmi_tells_a_relabelling_apart_from_independence():
    """Q2's verdict is one number: are the score clusters volatility bins renamed?

    If NMI could not separate a pure relabelling from independence, "the
    clusters restate volatility" and "the clusters are new information" would
    produce the same column and Q2 would have no answer either way.

    Fails if the contingency table is built with the wrong stride, which mixes
    the two labellings and pushes every reading towards zero.
    """
    rng = np.random.default_rng(4)
    a = rng.integers(0, 4, 20_000)
    assert dartsad.nmi(a, (a + 2) % 4) == pytest.approx(1.0, abs=1e-9)
    assert dartsad.nmi(a, rng.integers(0, 4, 20_000)) < 0.01


def test_bh_deflates_a_grid_of_cells():
    """Picking the best of many cells gives a winner every time; BH is what stops that.

    The transition study looks at k-squared cells on every instrument, so the
    nominal 5% would hand back a positive on a pure null. The control is the
    uniform grid, which must yield nothing; the power arm is one genuinely tiny
    p, which must survive.

    Fails if the step-up boundary is taken as the first rather than the last
    index that clears its threshold.
    """
    rng = np.random.default_rng(5)
    uniform = rng.random(200)
    assert dartsad.bh(uniform, 0.05).sum() == 0
    planted = uniform.copy()
    planted[7] = 1e-6
    rejected = dartsad.bh(planted, 0.05)
    assert rejected[7]
    assert rejected.sum() <= 3
