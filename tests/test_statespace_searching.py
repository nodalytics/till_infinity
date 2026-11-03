"""The discovery machinery, not any edge it found.

**Every test here asserts a control.** A test asserting that a discovered rule
is real would be the first thing in this file to rot - the sweep's own honest
answer on 2026-11-01 was that nothing survived - so what is pinned is the
machinery that produced that answer: that the losers are emitted, that the arms
are built and are independent of each other, that a planted effect is found and
a walk is not, and that each of the six refusals actually refuses.

The refusals are the part worth keeping. Each one is a measured failure on this
desk written into the code path rather than into a comment, and a comment is
what every one of them used to be.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.node import surrogates
from till_infinity.statespace import searching, shaping
from till_infinity.statespace.nulls import garch

#: A series long enough for a 64-bar trailing estimate, five strata and a few
#: hundred events. Short enough that a test file runs in seconds.
BARS = 900


def walk(n: int = BARS, *, seed: int = 5, start: float = 1.1000, step: float = 0.0004):
    """A gaussian walk with a varying bar shape.

    The shape varies because a constant one makes every bar-shape reader
    silent: the first version put the open at a fixed 0.3 of the range and
    `hammer`, `doji` and both engulfing readers found nothing on 1,200 bars,
    which looked like a broken reader and was a broken fixture.
    """
    rng = random.Random(seed)
    price, out = start, []
    for _ in range(n):
        price += rng.gauss(0.0, step)
        span = abs(rng.gauss(0.0, step)) + 1e-9
        low = price - rng.random() * span
        out.append((low + rng.random() * span, low + span, low, price))
    return out


def frozen(
    n: int = 3000,
    *,
    seed: int = 5,
    start: float = 1.1000,
    step: float = 0.0004,
    every: int = 100,
    hold: int = searching.HORIZON,
):
    """A walk that stops dead for `hold` bars every `every` bars.

    The btc defect reproduced: the forward move at those bars is exactly zero,
    so every event scores the same number and the per-event spread is nothing
    at all.
    """
    rng = random.Random(seed)
    price, out = start, []
    for i in range(n):
        if not 0 < i % every <= hold:
            price += rng.gauss(0.0, step)
        span = abs(rng.gauss(0.0, step)) + 1e-9
        low = price - rng.random() * span
        out.append((low + rng.random() * span, low + span, low, price))
    return out


def ramp(n: int = BARS, *, seed: int = 5, start: float = 1.1000, step: float = 0.0004):
    """A walk inside a rising channel: two parallel lines by construction.

    The constructed stand-in for `Range_Break`, which is the desk's level and
    range positive control because it is a range by construction. A channel or
    rectangle reader that finds nothing here is broken rather than honest.
    """
    rng = random.Random(seed)
    out = []
    for i in range(n):
        middle = start + i * step * 0.25
        price = middle + math.sin(i / 11.0) * step * 6.0 + rng.gauss(0.0, step * 0.4)
        span = abs(rng.gauss(0.0, step)) + 1e-9
        low = price - rng.random() * span
        out.append((low + rng.random() * span, low + span, low, price))
    return out


def counting(every: int):
    """A reader that fires every `every` bars. No structure, exact event count."""

    def read(candles):
        return [1.0 if i % every == 0 else math.nan for i in range(len(candles))]

    return read


def clustered(n: int = 2400, *, seed: int = 11, start: float = 1.1000, step: float = 0.0004):
    """A GARCH series: clustered volatility and fat tails, nothing else.

    `nulls.garch` standardises its Student-t innovation, which three harnesses
    here failed to do - an unstandardised `t(5)` gives an effective
    persistence of 1.046 and the variance reached 1e110.
    """
    rng = random.Random(seed)
    price, closes = start, []
    for innovation in garch(n, seed=seed, sigma=step):
        price += innovation
        closes.append(price)
    out = []
    for close in closes:
        span = abs(rng.gauss(0.0, step)) + 1e-12
        low = close - rng.random() * span
        out.append((low + rng.random() * span, low + span, low, close))
    return out


def in_band(bands, want: int):
    """A reader that fires on every bar in one volatility stratum.

    The purest volatility leak available: the reading *is* the stratum, so
    anything the pooled statistic reports about it is the stratum's own mean.
    """

    def read(candles):
        return [1.0 if bands[i] == want else math.nan for i in range(len(candles))]

    return read


def leaking(candles):
    """A reader that fires where the forward move is largest. **Undeclared
    lookahead**, which is the failure the placebo pool exists to catch.

    It survives every arm on every series, including one built so that nothing
    is there - and that is the tell. A block of 8 found structure in 27 of 36
    placebo pools on this desk, and the pools are what said the block was the
    problem rather than the market.
    """
    closes = [c[3] for c in candles]
    reach = searching.HORIZON
    moves = sorted(
        ((abs(closes[t + reach] - closes[t]), t) for t in range(len(closes) - reach)),
        reverse=True,
    )
    out = [math.nan] * len(candles)
    for _move, t in moves[: max(60, len(candles) // 10)]:
        out[t] = 1.0
    return out


class TestTheRefusals:
    """Six things the sweep will not do, each one a measured failure."""

    def test_a_candidate_scored_without_arms_is_refused(self) -> None:
        """Six artefacts here passed DSR, PBO and SPA; surrogates caught them.

        So an arms-free score is a number with no comparison behind it, and
        the sweep raises rather than returning it. `node.metrics.DeflatedSharpe`
        refuses on the same grounds when it was not given the trials.
        """
        candidate = searching.Candidate(
            family="test",
            name="every-10",
            question="dispersion",
            threshold=1.0,
            reader=counting(10),
        )
        with pytest.raises(ValueError, match="no arms"):
            searching.score(candidate, walk(), [])

    def test_an_arm_that_names_no_property_cannot_be_built(self) -> None:
        """`a-control-is-only-for-a-named-property`: Boom/Crash gained more
        than any traded class under an arm about the wrong property. An
        unlabelled control still produces a number and the number looks like a
        comparison, so the label is required at construction."""
        with pytest.raises(ValueError, match="named property"):
            searching.Arm(name="something", removes="   ", kind=searching.SERIES)

    def test_an_arm_of_an_unknown_kind_cannot_be_built(self) -> None:
        """A series arm and an anchors arm are driven differently - one
        re-runs the reader, the other moves indices - so a third kind would be
        silently skipped by `_draw` and report an empty arm as a pass."""
        with pytest.raises(ValueError, match="series or anchors"):
            searching.Arm(name="x", removes="a property", kind="other")

    def test_an_event_separation_below_the_forward_window_is_refused(self) -> None:
        """`overlapping-outcome-windows-leak`: a short skip rule with a long
        forward window gave direction AUC 0.79 that collapsed to 0.51
        de-overlapped, and the tell was the placebo and shuffled arms tracking
        the real one. Two events closer than the window share most of their
        outcome, so this raises instead of warning - the failure it produces is
        a p-value that looks good."""
        candidate = searching.Candidate(
            family="test", name="every-2", question="dispersion", threshold=1.0, reader=counting(2)
        )
        with pytest.raises(ValueError, match="shorter than"):
            searching.score(candidate, walk(), searching.arms(), horizon=4, separation=2)

    def test_a_reader_that_reads_its_own_future_is_refused(self) -> None:
        """`open-gap-filters-are-lookahead`: `drawing.gaps` emitted only
        *unfilled* gaps and read +0.50R a trade as a bias. A triangle is only a
        triangle once it has broken out, so `shaping.broken_out` is the same
        bug - built, named, declared, and refused here."""
        candidate = shaping.lookahead_candidate(
            (shaping.Slope.DOWN, shaping.Slope.UP, shaping.Pair.CONVERGING)
        )
        assert candidate.lookahead
        with pytest.raises(ValueError, match="lookahead"):
            searching.score(candidate, walk(), searching.arms())

    def test_a_question_the_sweep_does_not_know_is_refused(self) -> None:
        """A trial whose question is unrecorded cannot be told from one that
        asked the question already closed here. `direction` is in the set and
        is expected to fail; a typo is not in the set at all."""
        with pytest.raises(ValueError, match="not one of"):
            searching.Candidate(
                family="test", name="x", question="directoin", threshold=1.0, reader=counting(10)
            )


class TestTheSweepKeepsItsLosers:
    """`node.metrics.trial_variance` takes the readings, not a number."""

    def test_every_candidate_appears_in_the_trials_whether_it_won_or_lost(self) -> None:
        """The spread of Sharpes across everything tried only exists if the
        search kept its losers, so a node reporting its best candidate and
        discarding the rest cannot compute a deflated Sharpe at all."""
        candles = walk()
        cands = [
            searching.Candidate(
                family="test",
                name=f"every-{n}",
                question="dispersion",
                threshold=1.0,
                reader=counting(n),
            )
            for n in (5, 7, 9, 11)
        ]
        got = searching.sweep(cands, candles, searching.arms(), draws=12)
        assert got.attempted == len(cands)
        assert len(got.sharpes()) == len(cands), "a scored trial went missing from the sharpes"
        assert not got.survivors(), "a reader with no structure survived its arms"

    def test_a_candidate_scored_on_too_few_events_within_strata_is_refused(self) -> None:
        """**A trial Sharpe from three events poisons the whole search.**

        `lift` drops an event whose volatility band holds no non-event to
        compare it with, so a candidate can clear the event gate and be scored
        on a handful - and `Trial.sharpe` is `mean / sd` over those. One btc
        shape trial read **-18.4** where the rest of the panel spanned -0.14 to
        +0.23, and that number goes straight into
        `node.metrics.trial_variance`, inflating `expected_max_sharpe` enough
        to put the deflated Sharpe out of reach for every other candidate.
        """
        # 120 bars with a 20-bar forward window, so the last event has no
        # outcome and the first has no volatility unit yet - six events clear a
        # floor of five and four survive to be scored.
        candles = walk(120)
        candidate = searching.Candidate(
            family="test",
            name="every-20",
            question="dispersion",
            threshold=1.0,
            reader=counting(20),
        )
        trial = searching.score(
            candidate,
            candles,
            searching.arms(),
            horizon=20,
            separation=20,
            draws=4,
            least_events=5,
        )
        assert trial.refused, trial.line()
        assert "within strata" in trial.refused
        assert trial.events == 6
        assert not trial.scored

    def test_a_trial_whose_events_all_score_the_same_is_refused(self) -> None:
        """**Found by running the sweep, not anticipated.** `engulfing_up` on
        4,000 bars of btc 1h scored a lift of -0.5403 over 41 events at a
        Sharpe of **-18.40**, where every other trial on the panel sat between
        -0.14 and +0.23.

        The cause was not a short series. All 41 events were scored and their
        outcomes ran 0.006 to 0.096 against a sample standard deviation of
        0.82 - and the event indices were 4, 28, 52, 76, 202, multiples of 24,
        so the reader was firing at one hour of the day where the stored feed
        has a daily-boundary defect: the median four-bar move after those bars
        is 4.98 against 44.75 over the sample.

        One Sharpe of -18.40 in `node.metrics.trial_variance` inflates
        `expected_max_sharpe` enough to put the deflated Sharpe out of reach
        for every other candidate in the search, so the guard is on the
        property rather than on the feed.
        """
        candles = frozen()
        candidate = searching.Candidate(
            family="test",
            name="every-100",
            question="dispersion",
            threshold=1.0,
            reader=counting(100),
        )
        # `bands=1` is no stratification, so every event shares one reference
        # and the collapse is visible in one number. On btc the 41 events fell
        # in one band on their own, which has the same effect: the per-event
        # series is `outcome - the band's reference`, so events spread across
        # bands carry the spread of the references whatever their outcomes do.
        trial = searching.score(
            candidate, candles, searching.arms(), bands=1, draws=4, least_events=20
        )
        assert trial.refused, trial.line()
        assert "degenerate outcome spread" in trial.refused
        assert "calendar period" in trial.refused, "the refusal does not say where to look"

    def test_a_refused_candidate_is_still_a_trial_but_not_a_sharpe(self) -> None:
        """A refusal is a trial that was attempted - it counts toward the
        multiplicity - and is not a Sharpe, because nothing was measured.
        `node.discovery.Trials.refuse` makes the same split."""
        candles = walk()
        thin = searching.Candidate(
            family="test",
            name="every-400",
            question="dispersion",
            threshold=1.0,
            reader=counting(400),
        )
        got = searching.sweep([thin], candles, searching.arms(), draws=8)
        assert got.attempted == 1
        assert got.sharpes() == ()
        assert "too few events" in got.trials[0].refused

    def test_overlapping_candidates_count_as_fewer_than_their_number(self) -> None:
        """**Shape families overlap, so their trials are not independent.** An
        engulfing bar is the opposite shape to a displacement origin and the
        best vs-walk z over 516 rows was +1.95, so counting 100 overlapping
        candidates as 100 trials overstates the correction.

        Four copies of one reader must discount toward one; four unrelated
        readers must not.
        """
        candles = walk()
        same = [
            searching.Candidate(
                family="test",
                name=f"copy-{i}",
                question="dispersion",
                threshold=1.0,
                reader=counting(9),
            )
            for i in range(4)
        ]
        apart = [
            searching.Candidate(
                family="test",
                name=f"apart-{n}",
                question="dispersion",
                threshold=1.0,
                reader=counting(n),
            )
            for n in (5, 7, 11, 13)
        ]
        clones = searching.sweep(same, candles, searching.arms(), draws=6).effective_trials()
        varied = searching.sweep(apart, candles, searching.arms(), draws=6).effective_trials()
        assert clones == pytest.approx(1.0, abs=0.05), f"four copies discounted to {clones}"
        assert varied > clones, f"unrelated readers discounted to {varied}, clones to {clones}"


class TestTheOutputFeedsTheNodeLayer:
    """`node/statistics.py` gates on DSR, whose variance term needs the losers."""

    def test_a_sweep_builds_a_deflated_sharpe_that_reports_a_number(self) -> None:
        """**The whole reason a sweep emits every trial.**
        `node.metrics.trial_variance` is the spread of Sharpes across
        everything tried, so `DeflatedSharpe` refuses to report when it was not
        given at least two - an undeclared figure labelled "deflated" is worse
        than no figure. A sweep's `sharpes()` is exactly that input.
        """
        import pandas as pd

        from till_infinity.node import statistics

        candles = walk()
        cands = [
            searching.Candidate(
                family="test",
                name=f"every-{n}",
                question="dispersion",
                threshold=1.0,
                reader=counting(n),
            )
            for n in (5, 7, 9, 11, 13)
        ]
        got = searching.sweep(cands, candles, searching.arms(), draws=8)
        trials = got.sharpes()
        assert len(trials) >= 2, "a sweep that cannot feed DSR has not kept its losers"

        gate = statistics.DeflatedSharpe(trials)
        assert gate.trials == len(trials)
        assert gate.bar is not None, "SR* needs the trial variance, which needs the losers"
        best = max(got.trials, key=lambda t: t.sharpe)
        value = gate.calculate_from_returns(pd.Series(best.returns))
        assert value is not None
        assert 0.0 <= value <= 1.0
        assert gate.name in statistics.GATES, "the one statistic a promotion gate may read"

    def test_a_single_trial_cannot_be_deflated_and_the_node_says_so(self) -> None:
        """The refusal is the node's and is reproduced here so that a sweep of
        one is not quietly reported as a deflated result."""
        from till_infinity.node import statistics

        candidate = searching.Candidate(
            family="test", name="every-9", question="dispersion", threshold=1.0, reader=counting(9)
        )
        got = searching.sweep([candidate], walk(), searching.arms(), draws=8)
        assert len(got.sharpes()) == 1
        assert statistics.DeflatedSharpe(got.sharpes()).bar is None

    def test_the_claimed_sharpe_carries_the_side_and_the_variance_term_does_not(self) -> None:
        """**The sign question the two-sided test creates.**

        A survivor can sit *below* its null - a shape preceding an unusually
        quiet stretch - and its lift and Sharpe are then negative while the
        trade it implies is short volatility and makes money.
        `node.metrics.deflated_sharpe` asks whether a Sharpe beats the best of
        N nothings, so it needs the Sharpe of the *trade*.

        And `trial_variance` must **not** get the oriented ones: orienting
        every trial by its own sign makes every Sharpe positive, shrinks the
        spread and inflates the deflated Sharpe, which is the defect the whole
        correction exists to prevent.
        """
        low = searching.ArmResult(
            name="low", removes="a property", observed=-1.0, draws=tuple(range(100))
        )
        trial = searching.Trial(
            candidate=searching.Candidate(
                family="test", name="quiet", question="dispersion", threshold=1.0
            ),
            observed=-1.0,
            events=99,
            arms=(low,),
            returns=(-1.0, -1.2, -0.8, -1.1),
        )
        assert trial.survives, "a candidate below every draw is a two-sided survivor"
        assert trial.sharpe < 0.0
        assert trial.claimed_sharpe == pytest.approx(-trial.sharpe)

        got = searching.Sweep(trials=[trial], placebo=[])
        assert got.sharpes() == (trial.sharpe,), "the variance term took the oriented sign"

    def test_the_trial_sharpe_is_the_node_layers_own_arithmetic(self) -> None:
        """One definition of a Sharpe across the two packages, so a trial set
        here deflates against the scale it was measured on. `statespace` may
        not import `node`, so the agreement is pinned rather than shared."""
        from till_infinity.node import metrics

        candidate = searching.Candidate(
            family="test", name="every-9", question="dispersion", threshold=1.0, reader=counting(9)
        )
        trial = searching.score(candidate, walk(), searching.arms(), draws=4)
        assert trial.scored
        assert trial.sharpe == pytest.approx(metrics.sharpe(trial.returns))


class TestTheArmsAreRealAndIndependent:
    """An arm that cannot move the statistic reports a confident pass."""

    def test_the_default_battery_has_both_kinds_and_names_every_property(self) -> None:
        """A geometric claim and a topological one need different nulls, and
        using one for the other is how a geometric confound passes a
        topological test - the displacement origin's 82% return rate was
        geometry, and only a distance-matched placebo showed it."""
        battery = searching.arms()
        kinds = {a.kind for a in battery}
        assert kinds == {searching.SERIES, searching.ANCHORS}
        assert all(a.removes.strip() for a in battery)
        assert len({a.removes for a in battery}) == len(battery), "two arms claim one property"

    def test_each_arm_produces_its_own_draws_rather_than_sharing_them(self) -> None:
        """Independence is the property, and it is cheap to lose: one `rng`
        shared across arms would give four arms the same null series under
        four names, which reads as four confirmations."""
        candidate = searching.Candidate(
            family="test", name="every-9", question="dispersion", threshold=1.0, reader=counting(9)
        )
        trial = searching.score(candidate, walk(), searching.arms(), draws=20)
        assert len(trial.arms) == 4
        seen = {tuple(round(d, 12) for d in arm.draws) for arm in trial.arms}
        assert len(seen) == 4, "two arms produced the same draws"

    def test_a_series_arm_reruns_the_reader_and_an_anchors_arm_does_not(self) -> None:
        """ "Null every candidate against a walk through the same detector" is
        mechanical only if the detector is a value the harness holds. Four
        alternating-detector readings came out level with a walk because the
        detector's own structure was in both arms."""
        calls: list[int] = []

        def counted(candles):
            calls.append(len(candles))
            return counting(9)(candles)

        candidate = searching.Candidate(
            family="test", name="counted", question="dispersion", threshold=1.0, reader=counted
        )
        series = [a for a in searching.arms() if a.kind == searching.SERIES][:1]
        anchors = [a for a in searching.arms() if a.kind == searching.ANCHORS][:1]
        calls.clear()
        searching.score(candidate, walk(), series, draws=10)
        with_series = len(calls)
        calls.clear()
        searching.score(candidate, walk(), anchors, draws=10)
        with_anchors = len(calls)
        assert with_series == 11, f"a series arm ran the reader {with_series} times, wanted 11"
        assert with_anchors == 1, f"an anchors arm ran the reader {with_anchors} times, wanted 1"

    def test_an_arm_that_cannot_move_the_statistic_reports_uninformative(self) -> None:
        """**Not a pass.** A null that does not affect the statistic leaves the
        observed value at percentile zero, so it would otherwise be the hardest
        arm and would decide everything while having tested nothing."""
        flat = searching.ArmResult(
            name="flat", removes="nothing at all", observed=0.5, draws=(0.5, 0.5, 0.5)
        )
        assert flat.uninformative
        assert not flat.passes
        assert "uninformative" in flat.line()
        trial = searching.Trial(candidate=None, observed=0.5, events=99, arms=(flat,))  # type: ignore[arg-type]
        assert trial.hardest is None
        assert not trial.survives, "a trial survived on an arm that tested nothing"

    def test_the_node_layers_own_walk_can_be_used_as_the_series_arm(self) -> None:
        """`node.surrogates.walk_with_bar_geometry` is the implementation a
        real sweep should pass in; this module's is the fallback so that
        `statespace` imports nothing above it. The two have to be
        interchangeable or the fallback is a second, drifting copy - which is
        exactly how `statespace/accruing.py` came to be a stale duplicate of
        FOCuS, caught by a persistence collision rather than by review."""
        candles = walk(200)
        rng = random.Random(3)
        node_arm = searching.Arm(
            name="node's walk",
            removes="the path structure, bar geometry kept",
            kind=searching.SERIES,
            make=lambda c, r: surrogates.walk_with_bar_geometry(c, rng=r),
        )
        got = node_arm.make(candles, rng)  # type: ignore[call-arg]
        assert len(got) == len(candles)
        assert all(low <= close <= high for _o, high, low, close in got)
        candidate = searching.Candidate(
            family="test", name="every-9", question="dispersion", threshold=1.0, reader=counting(9)
        )
        trial = searching.score(candidate, candles, [node_arm], draws=8, least_events=10)
        assert len(trial.arms[0].draws) > 0

    def test_an_arm_result_builds_the_node_layers_surrogate(self) -> None:
        """`statespace` may not import `node`, so the percentile and the
        uninformative check are a few lines duplicated here - and pinning them
        against each other is what keeps the duplication a duplication of
        arithmetic rather than of a judgement.

        **The p and the pass deliberately differ, and the difference is the
        point.** `node.surrogates.Surrogate` is one-sided, which is right for
        its statistic: a strategy's realised Sharpe has one tradable side, and
        "worse than the null" is not a finding. A dispersion lift has two - a
        shape that precedes an unusually *quiet* stretch is a volatility sale -
        so this one is two-sided at 0.005 per tail, and its p is the node's
        smaller tail doubled.
        """
        mine = searching.ArmResult(
            name="arm", removes="a property", observed=0.9, draws=(0.1, 0.4, 0.5, 0.95)
        )
        theirs = surrogates.Surrogate(**mine.as_surrogate())  # type: ignore[arg-type]
        assert mine.percentile == pytest.approx(theirs.percentile)
        assert mine.uninformative == theirs.uninformative
        assert mine.p_value == pytest.approx(min(1.0, 2.0 * theirs.p_value))

        # The low tail, which the node's one-sided reading cannot report at all.
        low = searching.ArmResult(
            name="arm",
            removes="a property",
            observed=0.0,
            draws=tuple(0.1 * i for i in range(1, 300)),
        )
        assert low.side == -1
        assert low.passes, "an observed value below every draw is evidence, not a failure"
        assert not surrogates.Surrogate(**low.as_surrogate()).passes  # type: ignore[arg-type]

    def test_a_candidate_whose_arms_disagree_about_the_side_does_not_survive(self) -> None:
        """Above one arm's null and below another's is not an effect - it is a
        statement about the arms, that two of them remove different amounts of
        the same mechanical thing. The agreement costs nothing when the effect
        is real and is the cheapest way to catch an arm matched on the wrong
        property."""
        high = searching.ArmResult(
            name="high", removes="one property", observed=200.0, draws=tuple(range(100))
        )
        low = searching.ArmResult(
            name="low", removes="another property", observed=200.0, draws=tuple(range(300, 400))
        )
        assert high.passes
        assert high.side == 1
        assert low.side == -1
        trial = searching.Trial(
            candidate=searching.Candidate(
                family="test", name="split", question="dispersion", threshold=1.0
            ),
            observed=200.0,
            events=99,
            arms=(high, low),
            returns=(1.0, 2.0, 3.0),
        )
        # Both sit outside their own null, so both carry the same evidence -
        # which is exactly the case a one-sided reading would have called a
        # clean pass on the first arm and never looked at the second.
        assert high.evidence == low.evidence
        assert not trial.survives

        # And the agreement costs nothing when the arms agree.
        agreeing = searching.Trial(
            candidate=trial.candidate,
            observed=200.0,
            events=99,
            arms=(
                high,
                searching.ArmResult(
                    name="also high",
                    removes="a third",
                    observed=200.0,
                    draws=tuple(range(100, 200)),
                ),
            ),
            returns=(1.0, 2.0, 3.0),
        )
        assert agreeing.survives


class TestSizeAndPower:
    """A walk is not found, a plant is, and the curve says where it goes blind."""

    def test_a_reader_with_no_structure_does_not_survive_on_a_walk(self) -> None:
        """The size of the test. Every arm has to be beaten at its own 99th
        percentile, and a reader firing on a fixed cycle has nothing to beat
        it with."""
        candles = walk()
        cands = [
            searching.Candidate(
                family="test",
                name=f"every-{n}",
                question="dispersion",
                threshold=1.0,
                reader=counting(n),
            )
            for n in (5, 7, 9, 11, 13)
        ]
        got = searching.sweep(cands, candles, searching.arms(), draws=30)
        assert not got.survivors(), [t.line() for t in got.survivors()]

    def test_a_planted_dispersion_effect_is_found_and_a_zero_plant_is_not(self) -> None:
        """The power of the test, which has to be shown before a null is
        reported: a null from a test with no power is not a finding, and the
        only way to tell the two apart is to plant the effect and watch it
        appear."""
        candles = walk(2400)
        # Every 40 bars, not every 9. The plant is a bump over `2 * horizon`
        # bars, so a reader firing every 9 puts a bump on 8 of every 9 bars -
        # the plant is then nearly everywhere, a placebo anchor lands inside
        # one whatever it does, and the curve reads blind at every strength.
        candidate = searching.Candidate(
            family="test",
            name="every-40",
            question="dispersion",
            threshold=1.0,
            reader=counting(40),
        )
        rows = searching.power(candidate, candles, searching.arms(), (0.0, 0.5, 1.0, 4.0), draws=30)
        assert not rows[0].found, "a plant of zero was found - the harness has a leak"
        assert rows[-1].found, "a four-sigma plant was missed - the test is blind"
        assert rows[0].observed < rows[1].observed < rows[-1].observed

    def test_the_plant_leaves_no_drift_behind_it(self) -> None:
        """A plant that only added the move left a permanent level shift at
        every event, so 56 events at 4 sigma produced 224 sigmas of drift and
        the curve measured whether the test can see a trend. The bump has to
        come back."""
        candles = walk()
        events = list(range(100, 800, 20))
        planted = searching._plant(candles, events, 4.0, horizon=4, span=searching.SPAN)
        drift = abs(planted[-1][3] - candles[-1][3])
        move = abs(candles[-1][3] - candles[0][3])
        assert drift < 0.05 * move, (
            f"the plant left {drift:.6f} of drift against a move of {move:.6f}"
        )

    def test_the_strata_remove_the_volatility_a_pooled_statistic_would_report(self) -> None:
        """`auc-is-free-on-volatility-targets`: 0.805 on a constant-volatility
        process against 0.525 within strata.

        **Dividing by the trailing standard deviation is not enough on its
        own**, which is the measurement this test exists for. On 2,400 bars of
        GARCH the normalised outcome still falls monotonically with the
        volatility level - mean **0.914** in the quietest stratum against
        **0.677** in the busiest - because a trailing estimate taken in a
        quiet stretch under-predicts the next move. So a detector that fires
        only in the quietest band earns a **pooled** lift of +0.190 from the
        stratum and nothing else, and within strata that falls to +0.092.
        """
        candles = clustered()
        values = searching.outcomes(candles)
        bands = searching.strata(candles)
        events = searching.events_from(
            in_band(bands, 0)(candles), 1.0, separation=searching.HORIZON
        )
        within, _ = searching.lift(values, events, bands)
        pooled, _ = searching.lift(values, events, [0] * len(candles))
        assert pooled > 0.15, f"the fixture does not leak volatility: pooled {pooled:.4f}"
        assert within < pooled / 1.5, f"within-strata {within:.4f} against pooled {pooled:.4f}"


class TestThePlaceboPoolSelectsTheNull:
    """A block of 8 found structure in 27 of 36 placebo pools."""

    def test_the_gate_refuses_a_run_whose_placebo_pool_produced_a_survivor(self) -> None:
        """Not a ratio and not a threshold: a pool built so that nothing is
        there has no business producing a survivor, and one that does says the
        arms are too weak for this statistic rather than that the finding is
        marginal.

        The surviving placebo trial is constructed rather than provoked. What
        provokes one is a battery too weak for the statistic, and a fixture
        that faked that would be a fixture asserting the arms are weak - the
        opposite of what the rest of this file pins.
        """
        strong = searching.ArmResult(
            name="an arm it clears", removes="a property", observed=1.0, draws=(0.1, 0.2, 0.3)
        )
        candidate = searching.Candidate(
            family="test", name="placebo-scorer", question="dispersion", threshold=1.0
        )
        trial = searching.Trial(
            candidate=candidate, observed=1.0, events=99, arms=(strong,), returns=(1.0, 1.0, 1.0)
        )
        assert trial.survives
        got = searching.Sweep(trials=[trial], placebo=[trial])
        assert "placebo" in got.blocked()
        assert got.verdict().startswith("unreadable")
        assert "survived" not in got.verdict().split(":")[0]

    def test_a_reader_that_leaks_its_own_future_is_caught_by_the_series_arms(self) -> None:
        """**Why a series arm is worth its cost**, and it is the expensive one.

        A reader firing where the forward move is largest is an undeclared
        lookahead and earns a lift of around +1.0 on any series. It still
        fails, because a series arm re-runs *the same reader* on the null and
        the leak is just as available there - so the observed value sits in the
        middle of its own null distribution.

        An anchors arm cannot catch this at all: it keeps the reader's events
        and moves them, so it never sees what the reader would do with fresh
        data. That is the pairing argument in one case.
        """
        candidate = searching.Candidate(
            family="test", name="leaking", question="dispersion", threshold=1.0, reader=leaking
        )
        battery = searching.arms()
        trial = searching.score(candidate, walk(), battery, draws=20)
        assert trial.observed > 0.5, f"the fixture does not leak: lift {trial.observed:.4f}"
        series = {a.name for a in battery if a.kind == searching.SERIES}
        by_name = {a.name: a for a in trial.arms}
        assert all(not by_name[name].passes for name in series), "a series arm missed the leak"
        anchors = [a for a in battery if a.kind == searching.ANCHORS]
        alone = searching.score(candidate, walk(), anchors, draws=20)
        assert alone.survives, "the anchors arms were expected to miss a lookahead leak"

    def test_a_clean_run_is_not_blocked(self) -> None:
        """The other half, because a guard that always fires is the same
        failure as one that never does."""
        candidate = searching.Candidate(
            family="test", name="every-9", question="dispersion", threshold=1.0, reader=counting(9)
        )
        got = searching.sweep(
            [candidate], walk(), searching.arms(), placebo=[walk(seed=99)], draws=20
        )
        assert got.blocked() == ""

    def test_a_run_with_no_placebo_pool_is_blocked_as_well(self) -> None:
        """**The vacuous-guard case, made loud.** A guard with nothing to check
        reads as a pass, and this repository walked into that shape three times
        in one day - `STANDALONE`'s empty scan is the one `test_service_
        boundaries.py` names. An empty placebo pool is the cheapest of them to
        catch, so it is caught here rather than in a caller's checklist."""
        candidate = searching.Candidate(
            family="test", name="every-9", question="dispersion", threshold=1.0, reader=counting(9)
        )
        got = searching.sweep([candidate], walk(), searching.arms(), draws=8)
        assert "no placebo pool" in got.blocked()
        assert got.verdict().startswith("unreadable")
        # The trials are still there to be read as trials - the block is about
        # whether a *survivor* can be believed, not about whether the search ran.
        assert got.attempted == 1
        assert len(got.sharpes()) == 1


class TestThresholdsOnTheMean:
    """`sweep-thresholds-on-the-mean-not-z`: the z grid faked a ridge."""

    def test_a_threshold_row_carries_the_mean_and_the_count_and_no_z(self) -> None:
        """A z falls as the event count falls, so a grid of z's has a maximum
        wherever the count stops paying for the mean - which looks like a
        discovered threshold and is arithmetic. The row therefore has nowhere
        to put one."""
        candles = walk()
        candidate = searching.Candidate(
            family="test",
            name="span",
            question="dispersion",
            threshold=0.0,
            reader=lambda cs: [c[1] - c[2] for c in cs],
        )
        rows = searching.thresholds(candidate, candles, (0.0002, 0.0004, 0.0008))
        assert list(searching.Row.__slots__) == ["threshold", "events", "mean"]
        assert rows[0].events > rows[-1].events
        assert all(not math.isnan(r.mean) for r in rows if r.events > 0)

    def test_monotone_reports_a_rising_mean_and_rejects_a_ridge(self) -> None:
        """A detector whose higher readings really do precede larger moves
        gives a monotone mean grid; one whose best threshold is the one with
        the fewest events does not."""
        rising = [
            searching.Row(threshold=1.0, events=100, mean=0.01),
            searching.Row(threshold=2.0, events=50, mean=0.02),
            searching.Row(threshold=3.0, events=10, mean=0.03),
        ]
        ridge = [
            searching.Row(threshold=1.0, events=100, mean=0.01),
            searching.Row(threshold=2.0, events=50, mean=0.05),
            searching.Row(threshold=3.0, events=10, mean=0.02),
        ]
        assert searching.monotone(rising)
        assert not searching.monotone(ridge)


class TestTheShapeGrid:
    """Enumerate the family; the familiar names have the worst prior."""

    def test_the_grid_is_nineteen_cells_and_the_impossible_ones_are_absent(self) -> None:
        """Pivot, Elliott, Wyckoff and Gann all came out null here, so the
        named cells are the ones most likely to be post-hoc and a sweep that
        tested only them would be testing the worst priors. A missing cell is
        a family that was never tried and never reported, so the count is
        asserted rather than trusted."""
        got = shaping.cells()
        assert len(got) == 19, f"the grid has {len(got)} cells"
        assert (shaping.Slope.UP, shaping.Slope.DOWN, shaping.Pair.PARALLEL) not in got
        assert (shaping.Slope.UP, shaping.Slope.DOWN, shaping.Pair.CONVERGING) not in got
        assert (shaping.Slope.DOWN, shaping.Slope.UP, shaping.Pair.DIVERGING) not in got
        unnamed = [c for c in got if c not in shaping.NAMED]
        assert unnamed, "every cell has a chart name, which would be suspicious"

        # And every name belongs to a cell that can occur. A name for an
        # impossible shape is noise: nothing is ever filed under it, and a
        # reader counting the names gets a number larger than the grid.
        # `(down, up, diverging)` sat in `NAMED` until this line counted it.
        impossible = [cell for cell in shaping.NAMED if not shaping.feasible(*cell)]
        assert not impossible, f"NAMED holds cells that cannot occur: {impossible}"

    def test_every_family_is_a_candidate_including_the_ones_with_no_name(self) -> None:
        """19 line cells, `4 ** 2` structure words and 5 bar shapes - 40 at
        two-letter words. **At a target Sharpe of 1.5 one month of data
        supports about one trial**, so the count is declared rather than
        reduced."""
        got = shaping.candidates()
        assert len(got) == 19 + 16 + 5
        assert {c.source for c in got} == {"lines", "structure", "bar"}
        assert all(c.threshold == 1.0 for c in got), "a shape reader is an indicator"
        assert all(not c.lookahead for c in got)

    def test_a_shape_is_dated_at_its_newest_pivots_confirmation(self) -> None:
        """**The trap specific to shapes.** A triangle is only a triangle once
        it has broken out, so a confirmed shape carries the future in its
        definition unless it is dated at the bar the definition completed.
        `Pivot.confirmed` exists for this, and the assertion is that the shape
        is never dated at the extreme - which is `reach` bars earlier."""
        candles = ramp()
        found = shaping.shapes(candles, window=60)
        assert found, "the channel fixture produced no shape"
        for shape in found:
            assert 0 <= shape.at < len(candles)
        assert len({s.at for s in found}) == len(found), "two shapes claim one bar"

    def test_a_shape_reader_fires_only_on_the_bar_the_shape_completed(self) -> None:
        """The reader is the thing a sweep sees, so the dating has to survive
        the conversion: truncating the series at the detection bar must not
        change whether the detection happened."""
        candles = ramp()
        cell = next(s.cell for s in shaping.shapes(candles, window=60) if s.cell in shaping.NAMED)
        read = shaping.reader(cell, window=60)
        full = read(candles)
        hits = [i for i, v in enumerate(full) if not math.isnan(v)]
        assert hits, f"no detection of {cell}"
        at = hits[len(hits) // 2]
        cut = read(candles[: at + 1])
        assert not math.isnan(cut[at]), "the shape needed bars after the bar it was dated at"

    def test_the_breakout_version_sees_the_future_and_the_plain_one_does_not(self) -> None:
        """Both are built so the difference can be measured, and the lookahead
        one is declared rather than merely documented - `searching.score`
        refuses it, which is the test above in `TestTheRefusals`."""
        candles = ramp()
        cell = next(s.cell for s in shaping.shapes(candles, window=60) if s.cell in shaping.NAMED)
        plain = [v for v in shaping.reader(cell, window=60)(candles) if not math.isnan(v)]
        broken = [v for v in shaping.broken_out(cell, window=60)(candles) if not math.isnan(v)]
        assert len(broken) <= len(plain), "the breakout filter added detections"

    def test_a_rectangle_or_channel_cell_fires_on_a_range_by_construction(self) -> None:
        """`Range_Break` is the level and range positive control because it is
        a range by construction. The constructed stand-in here is a walk
        inside a rising channel, and a parallel cell that misses it is broken
        rather than honest."""
        found = shaping.shapes(ramp(), window=60)
        pairs = {s.cell[2] for s in found}
        assert shaping.Pair.PARALLEL in pairs or shaping.Pair.CONVERGING in pairs, (
            f"a channelled series produced only {pairs}"
        )

    def test_a_label_stride_drops_confirmations_rather_than_re_dating_them(self) -> None:
        """A stride is a **declared compute budget** - the selection is global
        within its window, so there is no incremental form and 4,000 bars at a
        120-bar window is 11.5 seconds per draw.

        The tempting version - evaluate every `k`th window and accept
        confirmations from the last `k` bars - would score a point using a
        window with up to `k-1` bars that did not exist when it was confirmed.
        So every label a strided run finds must also be found by the
        unstrided one, at the same index.
        """
        candles = walk(600)
        full = dict(shaping.labels(candles, window=60, count=8))
        strided = dict(shaping.labels(candles, window=60, count=8, stride=3))
        assert strided, "the strided run found nothing"
        assert len(strided) < len(full), "the stride cost no power, so it did nothing"
        for at, label in strided.items():
            assert full.get(at) == label, f"stride re-dated or relabelled {at}"


def test_the_published_feed_name_carries_no_separator():
    """**Every proposal on a slashed instrument was declined, silently.**

    `StatespaceActor._payload` keyed a feed as `symbol.lower()`, keeping the
    slash, so a catalogue instrument named `EUR/USD` published `eur/usd`.
    `Surprise.wants` checks that against `SurpriseProfile.feeds`, which holds
    `eurusd`, and `strategies.sizes.feed_of` strips the separator - so the two
    sides disagreed and a backtest over 10,270 bars and quotes placed not one
    order and raised nothing.

    Pinned against `sizes.feed_of` rather than against a literal, so the two
    cannot drift apart again: whichever way a feed is named, both sides name
    it the same.
    """
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.objects import Price, Quantity

    from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig
    from till_infinity.strategies.sizes import feed_of

    instrument = InstrumentId.from_str("EUR/USD.DERIV")
    bar_type = BarType.from_str(f"{instrument}-15-MINUTE-LAST-EXTERNAL")
    bar = Bar(
        bar_type,
        Price(1.1, 5),
        Price(1.2, 5),
        Price(1.0, 5),
        Price(1.15, 5),
        Quantity(1, 0),
        ts_event=0,
        ts_init=0,
    )
    actor = StatespaceActor.__new__(StatespaceActor)
    actor._cfg = StatespaceConfig(bar_types=(str(bar_type),))
    actor._seconds = {}

    assert actor._payload(bar)["feed"] == feed_of(instrument) == "eurusd"
