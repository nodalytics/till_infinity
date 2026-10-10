"""The thesis as a state space: the shared model, the three subjects, and the rule.

`till_infinity/structures/statespace/` is built beside production rather than
inside it, and the thing most worth testing is not any one filter - it is that
the package stays separable. The import test at the bottom is the one that keeps
the whole directory deletable.
"""

from __future__ import annotations

import math

import pytest

from till_infinity.structures.statespace import (
    INSTRUMENT,
    LEVEL,
    RELATION,
    SUBJECTS,
    Gaussian,
    slope_per_bar,
    slope_per_hour,
)

HOUR = 3_600.0


# ------------------------------------------------------- I6: a rate per unit time


class TestRates:
    def test_a_straight_line_in_time_recovers_its_rate(self):
        """Two units an hour is two units an hour, whatever the sampling."""
        times = [0.0, 1 * HOUR, 2 * HOUR, 3 * HOUR, 4 * HOUR]
        got = slope_per_hour(times, [10.0 + 2.0 * i for i in range(5)])
        assert got is not None
        assert got.per_hour == pytest.approx(2.0)
        assert got.hours == pytest.approx(4.0)
        assert got.n == 5
        # An exact fit has no residual, so no standard error. That is not
        # certainty, and `confident` must not read it as any.
        assert got.variance == pytest.approx(0.0)
        assert got.confident is False

    def test_uneven_sampling_is_where_the_two_conventions_part(self):
        """**The whole of I6, in one assertion.**

        A session gap makes one index step three days. The time-regressed slope
        is unchanged because the price really did move at a steady rate; the
        index-regressed one changes because it thinks the gap was one bar.
        """
        rate = 3.0
        even = [i * HOUR for i in range(6)]
        gapped = [0.0, 1 * HOUR, 2 * HOUR, 74 * HOUR, 75 * HOUR, 76 * HOUR]

        for times in (even, gapped):
            vals = [100.0 + rate * (t / HOUR) for t in times]
            got = slope_per_hour(times, vals)
            assert got is not None
            assert got.per_hour == pytest.approx(rate), "time knows the gap was a gap"

        even_vals = [100.0 + rate * (t / HOUR) for t in even]
        gap_vals = [100.0 + rate * (t / HOUR) for t in gapped]
        assert slope_per_bar(even_vals) == pytest.approx(rate)
        # Index sees the weekend as one step, so its answer is inflated several
        # fold - and nothing in production's feature names says which it is.
        assert slope_per_bar(gap_vals) > 10.0 * rate

    def test_the_standard_error_falls_as_the_window_lengthens(self):
        """Noise around a line: the same rate, known better from more of it."""
        rng = __import__("random").Random(4)
        rate = 0.5

        def fit(n: int):
            times = [i * HOUR for i in range(n)]
            vals = [10.0 + rate * i + rng.gauss(0, 0.4) for i in range(n)]
            return slope_per_hour(times, vals)

        short, long = fit(8), fit(120)
        assert short is not None
        assert long is not None
        assert long.sd < short.sd
        assert long.per_hour == pytest.approx(rate, abs=0.05)
        assert long.confident is True

    def test_a_window_with_no_time_span_has_no_rate(self):
        """Every point at one instant. The index form happily returns a number."""
        assert slope_per_hour([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]) is None
        assert slope_per_bar([1.0, 2.0, 3.0]) != 0.0

    def test_two_points_are_refused(self):
        """A line through two points has no residual and so no standard error;
        reporting one would publish a certainty the data cannot support."""
        assert slope_per_hour([0.0, HOUR], [1.0, 2.0]) is None

    def test_a_non_finite_value_is_refused_rather_than_propagated(self):
        assert slope_per_hour([0.0, HOUR, 2 * HOUR], [1.0, float("nan"), 3.0]) is None
        assert slope_per_hour([0.0, float("inf"), 2 * HOUR], [1.0, 2.0, 3.0]) is None


# ----------------------------------------------- the model, in continuous time


class TestGaussian:
    def test_the_first_reading_becomes_the_state(self):
        g = Gaussian(jerk=1e-6, at=0.0)
        g.update(1.2345, noise=0.16, when=HOUR)
        assert g.value == pytest.approx(1.2345)
        assert g.p00 == pytest.approx(0.16)
        assert g.seen == 1

    def test_it_learns_a_rate_from_a_moving_quantity(self):
        """Measurements marching up at a known rate, read back as that rate."""
        g = Gaussian(jerk=1e-3, at=0.0)
        rate = 0.25  # units per hour
        for i in range(60):
            t = i * HOUR
            g.update(10.0 + rate * i, noise=0.04, when=t)
        assert g.rate == pytest.approx(rate, abs=0.05)
        assert g.rate_confident is True
        assert g.earned_rate is True

    def test_a_state_at_unix_time_zero_still_advances(self):
        """**The sentinel must not be a valid value of the field.**

        The first version used `if self.at` to mean "never advanced", so a state
        whose `at` was 0.0 read as one that had never been advanced: `predict`
        returned early every time, the covariance never grew and existence never
        decayed. Real timestamps are never zero, which is precisely what would
        have let that reach production unnoticed - it only shows up in a test
        that starts its clock at zero, which is the natural thing to do.
        """
        g = Gaussian(jerk=1e-3, at=0.0)
        assert g.at == 0.0
        g.update(1.0, noise=0.01, when=0.0)
        before = g.p00
        g.predict(48 * HOUR)
        assert g.p00 > before, "a state at unix zero must still widen with time"
        assert g.existence < 1.0

    def test_before_the_first_measurement_there_is_no_elapsed_time(self):
        """A fresh filter has no clock, so the first `predict` sets it rather
        than integrating from an arbitrary epoch."""
        g = Gaussian(jerk=1e3)
        assert g.at is None
        before = g.p00
        g.predict(1_700_000_000.0)
        assert g.at == 1_700_000_000.0
        assert g.p00 == pytest.approx(before), "nothing has elapsed yet"
        assert g.at_time(1_700_000_000.0 + 10 * HOUR) == pytest.approx(g.value)

    def test_uncertainty_grows_with_elapsed_time_and_never_shrinks(self):
        """`predict` may only ever widen the covariance."""
        g = Gaussian(jerk=1e-3, at=0.0)
        g.update(1.0, noise=0.01, when=HOUR)
        tight = g.p00
        g.predict(HOUR + 48 * HOUR)
        assert g.p00 > tight
        wide = g.p00
        # A step of zero or backwards is the same instant, not a sharpening.
        g.predict(HOUR + 48 * HOUR)
        assert g.p00 == pytest.approx(wide)
        g.predict(HOUR)
        assert g.p00 == pytest.approx(wide)

    def test_a_weekend_and_an_hour_are_not_the_same_gap(self):
        """The property `levels.Kalman` already has and `Engine._slope` does not."""
        a, b = Gaussian(jerk=1e-3, at=0.0), Gaussian(jerk=1e-3, at=0.0)
        a.update(1.0, noise=0.01, when=0.0)
        b.update(1.0, noise=0.01, when=0.0)
        a.predict(1 * HOUR)
        b.predict(72 * HOUR)
        assert b.p00 > a.p00 * 10

    def test_one_jerk_drives_all_three_rows(self):
        """The difference from the incumbent: three variances cannot drift apart
        because there is only one number to set."""
        slow = Gaussian(jerk=1e-8, at=0.0)
        fast = Gaussian(jerk=1e-2, at=0.0)
        for g in (slow, fast):
            g.update(1.0, noise=0.01, when=0.0)
            g.predict(24 * HOUR)
        assert fast.p00 > slow.p00
        assert fast.p11 > slow.p11
        assert fast.p22 > slow.p22

    def test_the_covariance_stays_symmetric_and_positive(self):
        """Held as six floats rather than nine, so this is the invariant that
        says the hand-written algebra is still the algebra."""
        rng = __import__("random").Random(11)
        g = Gaussian(jerk=1e-3, at=0.0)
        for i in range(200):
            g.update(5.0 + rng.gauss(0, 0.3), noise=0.09, when=i * HOUR * 0.5)
        for name in ("p00", "p11", "p22"):
            assert getattr(g, name) >= 0.0, name
        # Cauchy-Schwarz on every off-diagonal: |cov| <= sqrt(var_i * var_j).
        assert abs(g.p01) <= math.sqrt(g.p00 * g.p11) + 1e-9
        assert abs(g.p02) <= math.sqrt(g.p00 * g.p22) + 1e-9
        assert abs(g.p12) <= math.sqrt(g.p11 * g.p22) + 1e-9

    def test_a_rate_of_zero_variance_is_no_information_not_certainty(self):
        """The mistake `Kalman.var_slope` documents, asserted here."""
        g = Gaussian(jerk=0.0, at=0.0)
        g.rate = 5.0
        g.p11 = 0.0
        assert g.rate_confident is False
        assert g.turning is False

    def test_turning_needs_a_rate_that_was_earned(self):
        g = Gaussian(jerk=1e-3, at=0.0)
        rate = 0.4
        for i in range(60):
            g.update(10.0 + rate * i, noise=0.04, when=i * HOUR)
        assert g.earned_rate is True
        assert g.rate > 0

        # Drive it down until the rate crosses zero, and catch it on the bar it
        # crosses - `turning` is a sign change at the *last* measurement, which
        # is what `Kalman.turning` means too. A level that turned three touches
        # ago is not turning now.
        flipped = False
        for i in range(60, 200):
            g.update(g.value - 1.5, noise=0.04, when=i * HOUR)
            if g.turning:
                flipped = True
                break
        assert flipped, "a rate driven through zero has to report the crossing"
        assert g.rate < 0
        assert g.prev_rate > 0

        # And it stops reporting it once the move is established.
        for i in range(200, 240):
            g.update(g.value - 1.5, noise=0.04, when=i * HOUR)
        assert g.turning is False

    def test_a_non_finite_measurement_is_refused(self):
        """The lesson of the sixteen days: a `nan` is not a bad number, it is an
        unbounded structure waiting to happen."""
        g = Gaussian(jerk=1e-3, at=0.0)
        g.update(1.0, noise=0.01, when=0.0)
        snapshot = (g.value, g.p00, g.seen)
        for bad in (float("nan"), float("inf"), float("-inf")):
            g.update(bad, noise=0.01, when=HOUR)
        g.update(1.0, noise=float("nan"), when=HOUR)
        g.update(1.0, noise=-1.0, when=HOUR)
        assert (g.value, g.p00, g.seen) == snapshot

    def test_the_band_widens_with_time_and_the_projection_is_its_middle(self):
        g = Gaussian(jerk=1e-3, at=0.0)
        rate = 0.2
        for i in range(40):
            g.update(1.0 + rate * i, noise=0.04, when=i * HOUR)
        now = 39 * HOUR
        near = g.band(now)
        far = g.band(now + 240 * HOUR)
        assert (far[1] - far[0]) > (near[1] - near[0])
        middle = (far[0] + far[1]) / 2
        assert middle == pytest.approx(g.at_time(now + 240 * HOUR))

    def test_existence_decays_with_time_and_is_reinforced_by_evidence(self):
        g = Gaussian(jerk=1e-3, at=0.0)
        g.update(1.0, noise=0.01, when=0.0)
        assert g.existence == pytest.approx(1.0)
        g.predict(7 * 24 * HOUR)
        assert g.existence == pytest.approx(0.5, abs=0.01), "one half-life"
        g.update(1.0, noise=0.01)
        assert g.existence > 0.5
        assert g.existence <= 1.0


# ------------------------------------------------------- one model, three subjects


class TestSubjects:
    def test_all_three_subjects_are_specified(self):
        """A subject that cannot say what its state means in words has not been
        specified, whatever its numbers are. I8 is this complaint."""
        assert len(SUBJECTS) == 3
        assert {s.name for s in SUBJECTS} == {"level", "instrument", "relation"}
        for s in SUBJECTS:
            assert s.quantity, s.name
            assert s.measurement, s.name
            assert s.units, s.name
            assert s.provenance, f"{s.name} must say where its numbers came from"
            assert s.jerk > 0, s.name
            assert s.noise > 0, s.name

    def test_every_placeholder_admits_to_being_one(self):
        """**The point of `provenance`.** `DRIFT_VOL_PER_HOUR = 0.02` was chosen,
        applied at every timeframe, and never fitted - and nothing said so. A
        number here either names its measurement or names itself a placeholder."""
        for s in SUBJECTS:
            assert "measured" in s.provenance or "placeholder" in s.provenance, s.name

    def test_the_levels_noise_is_the_one_number_that_is_measured(self):
        """`TOUCH_NOISE_VOL = 0.40`, 2026-10-09, two independent estimates."""
        assert LEVEL.noise == pytest.approx(0.40**2)
        assert "measured" in LEVEL.provenance
        assert "placeholder" in LEVEL.provenance, "its jerk is not measured"

    def test_the_other_two_claim_nothing(self):
        for s in (INSTRUMENT, RELATION):
            assert "placeholder" in s.provenance
            assert "measured" not in s.provenance.replace("never fitted", "")

    def test_one_model_serves_all_three(self):
        """The thesis's central claim, as an assertion: the same filter takes the
        same measurements for a level, an instrument and a relationship."""
        for s in SUBJECTS:
            g = s.filter(at=0.0)
            assert isinstance(g, Gaussian)
            assert g.jerk == s.jerk
            for i in range(30):
                g.update(1.0 + 0.1 * i, noise=s.noise, when=i * HOUR)
            assert math.isfinite(g.value)
            assert math.isfinite(g.rate)
            assert g.seen == 30

    def test_subjects_are_frozen(self):
        """A subject is a declaration, not state. Mutating one at runtime would
        make the provenance a lie."""
        with pytest.raises(AttributeError):
            LEVEL.jerk = 1.0  # type: ignore[misc]


# ---------------------------------------------------- the rule that keeps it separable


def test_structures_does_not_import_the_state_space_package():
    """**The rule, asserted rather than trusted.**

    The import direction is one-way: this package may read `structures`, and
    `structures` may not read this. That is what makes the whole directory
    deletable if the thesis loses, and it is the thing a well-meaning edit breaks
    first. When something graduates, it leaves by being called from `engine.py`
    behind a flag - and this test is where that gets noticed and argued about,
    which is the point.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "till_infinity"
    offenders = []
    for path in root.rglob("*.py"):
        if "statespace" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a file that will not parse
            continue
        # **Real imports, parsed - not the string anywhere in the file.** The
        # first version grepped, and `shared/codec.py` names this package in the
        # comment explaining why it opts out of the persistence schema. Prose
        # about a package is not a dependency on it, and a test that cannot tell
        # the difference gets switched off the first time it is wrong.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(a.name for a in node.names)]
            else:
                continue
            if any("statespace" in n.split(".") for n in names):
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not offenders, (
        "statespace is imported from outside itself: "
        f"{offenders}. Nothing in this package publishes until it has beaten a "
        "named null; see its __init__ docstring."
    )


def test_nothing_in_the_package_reaches_for_the_live_engine():
    """The other half of the same rule. Reading `structures` is allowed; reaching
    into the running engine is how a parallel model stops being parallel."""
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parent.parent / "till_infinity/structures/statespace"
    for path in pkg.rglob("*.py"):
        text = path.read_text()
        for banned in ("import engine", "from ..engine", "from ..service", "import service"):
            assert banned not in text, f"{path.name} reaches for {banned}"


# ------------------------------------------- the family, and which member fits where


class TestFamily:
    def test_every_written_member_satisfies_the_interface(self):
        """The interface cannot drift away from its implementations silently."""
        from till_infinity.structures.statespace.family import Filter, members

        got = members()
        assert set(got) == {"kalman", "reverting", "robust"}
        for name, cls in got.items():
            # Constructed with no arguments on purpose: a member whose defaults
            # do not produce a usable filter cannot be scored against another
            # one without someone choosing its parameters first.
            instance = cls()
            assert isinstance(instance, Filter), name
            for attr in ("predict", "update", "at_time", "band", "sd", "value", "rate"):
                assert hasattr(instance, attr), f"{name} is missing {attr}"
            # And every one of them must take the same call.
            instance.update(1.0, noise=0.04, when=0.0)
            instance.update(1.1, noise=0.04, when=HOUR)
            assert instance.seen == 2, name
            assert math.isfinite(instance.at_time(2 * HOUR)), name
            low, high = instance.band(2 * HOUR)
            assert low <= high, name

    def test_every_unwritten_member_already_names_the_null_it_must_beat(self):
        """**The rule that made both prior results conclusive.** A particle filter
        scored against nothing can only be argued about; scored against the
        linearisation of the same model it answered cleanly, twice, in opposite
        directions."""
        from till_infinity.structures.statespace.family import PENDING

        assert set(PENDING) == {"particle", "hmm", "rfs", "dpm"}
        for name, null in PENDING.items():
            assert len(null) > 40, f"{name}'s null is not stated properly"

    def test_the_family_table_records_both_particle_verdicts(self):
        """One filter family, two states, two opposite answers - which is the
        whole argument for asking per state. If this doc ever loses that, the
        reason the package is organised this way is lost with it."""
        from till_infinity.structures.statespace import family

        doc = family.__doc__ or ""
        assert "machinery for nothing" in doc
        assert "all four series" in doc
        assert "per state" in doc


class TestRobust:
    def test_inside_the_gate_it_is_exactly_the_kalman(self):
        """**What makes it a fair arm.** The comparison has to be of the tails
        alone, not of two different models."""
        from till_infinity.structures.statespace import Gaussian, Robust

        plain = Gaussian(jerk=1e-3, at=0.0)
        tough = Robust(jerk=1e-3, at=0.0)
        rng = __import__("random").Random(8)
        for i in range(120):
            # Well inside 2.5 sigma of a 0.3-sd measurement.
            z = 5.0 + rng.gauss(0, 0.05)
            plain.update(z, noise=0.09, when=i * HOUR)
            tough.update(z, noise=0.09, when=i * HOUR)
        assert tough.gated == 0
        assert tough.value == pytest.approx(plain.value)
        assert tough.p00 == pytest.approx(plain.p00)
        assert tough.rate == pytest.approx(plain.rate)

    def test_one_bad_print_moves_it_far_less_than_the_kalman(self):
        from till_infinity.structures.statespace import Gaussian, Robust

        plain = Gaussian(jerk=1e-6, at=0.0)
        tough = Robust(jerk=1e-6, at=0.0)
        for i in range(60):
            for g in (plain, tough):
                g.update(5.0, noise=0.01, when=i * HOUR)
        settled = plain.value
        assert tough.value == pytest.approx(settled)

        # A stale venue quote, twenty sigma out.
        plain.update(25.0, noise=0.01, when=61 * HOUR)
        tough.update(25.0, noise=0.01, when=61 * HOUR)
        moved_plain = abs(plain.value - settled)
        moved_tough = abs(tough.value - settled)
        assert tough.gated == 1
        assert moved_tough < moved_plain / 2, (moved_plain, moved_tough)

    def test_it_is_slow_to_be_convinced_and_not_incapable_of_it(self):
        """A single bad print must not move a level; a real re-levelling must.
        A filter that only rejected outliers would fail the second half."""
        from till_infinity.structures.statespace import Robust

        g = Robust(jerk=1e-4, at=0.0)
        for i in range(60):
            g.update(5.0, noise=0.01, when=i * HOUR)
        for i in range(60, 160):
            g.update(9.0, noise=0.01, when=i * HOUR)
        assert g.value == pytest.approx(9.0, abs=0.2), "it has to follow a real move"
        assert g.gated > 0, "and it should have found the first few surprising"

    def test_the_gated_share_is_the_number_that_says_whether_it_earns_anything(self):
        """Under a true Gaussian at 2.5 sigma this is about 1.2%. Far above and
        the tails are real; at or below it the gate is doing nothing."""
        from till_infinity.structures.statespace import Robust

        rng = __import__("random").Random(21)
        g = Robust(jerk=1e-9, at=0.0)
        for i in range(4000):
            g.update(5.0 + rng.gauss(0, 0.2), noise=0.04, when=i * HOUR)
        assert 0.0 <= g.gated_share < 0.10, g.gated_share
        assert g.worst_sigma > 2.0

    def test_a_non_finite_measurement_is_refused_here_too(self):
        from till_infinity.structures.statespace import Robust

        g = Robust(jerk=1e-3, at=0.0)
        g.update(1.0, noise=0.01, when=0.0)
        snap = (g.value, g.p00, g.seen, g.gated)
        for bad in (float("nan"), float("inf")):
            g.update(bad, noise=0.01, when=HOUR)
        assert (g.value, g.p00, g.seen, g.gated) == snap


# ----------------------------------- what the two references were actually worth


class TestAgainstTheStandardDiscretisation:
    def test_the_hand_written_transition_is_the_zero_order_hold_one(self):
        """**Checks the algebra against the library rather than against itself.**

        `linear.Gaussian.predict` applies `F(dt) = [[1,dt,dt^2/2],[0,1,dt],[0,0,1]]`,
        which is the claim that this is a continuous triple integrator sampled by
        zero-order hold - `control.StateSpace`'s `dt = 0` plus `sample('zoh')`.
        That is a checkable claim, so it is checked. scipy is a transitive
        dependency here and may be absent; the test skips rather than pretends.
        """
        np = pytest.importorskip("numpy")
        signal = pytest.importorskip("scipy.signal")

        # Continuous: value' = rate, rate' = accel, accel' = jerk noise.
        # Upper case because that is what these matrices are called everywhere
        # this was taken from, and renaming them would make the comparison with
        # the reference harder to read for no gain.
        a = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]])
        b = np.array([[0.0], [0.0], [1.0]])
        for dt in (0.25, 1.0, 7.5):
            discrete, *_ = signal.cont2discrete((a, b, np.eye(3), np.zeros((3, 1))), dt)
            mine = np.array([[1.0, dt, 0.5 * dt * dt], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
            assert np.allclose(discrete, mine), (dt, discrete, mine)

    def test_predict_moves_the_state_by_that_same_transition(self):
        """And the matrix above is what the code actually applies."""
        g = Gaussian(jerk=0.0, at=0.0)
        g.value, g.rate, g.accel = 2.0, 0.5, 0.1
        g.seen = 5
        dt = 3.0
        g.predict(dt * HOUR)
        assert g.value == pytest.approx(2.0 + 0.5 * dt + 0.5 * 0.1 * dt * dt)
        assert g.rate == pytest.approx(0.5 + 0.1 * dt)
        assert g.accel == pytest.approx(0.1)

    def test_the_chi_squared_survival_function_matches_scipy(self):
        """The closed form for even degrees of freedom, checked rather than trusted."""
        stats = pytest.importorskip("scipy.stats")
        from till_infinity.structures.statespace.diagnostics import _chi2_sf

        for df in (2, 4, 10, 20):
            for x in (0.1, 1.0, 5.99, 18.3, 40.0):
                assert _chi2_sf(x, df) == pytest.approx(stats.chi2.sf(x, df), rel=1e-9)

    def test_odd_degrees_of_freedom_are_refused_rather_than_approximated(self):
        from till_infinity.structures.statespace.diagnostics import _chi2_sf

        with pytest.raises(ValueError, match="even df"):
            _chi2_sf(1.0, 3)


class TestLikelihood:
    def test_the_likelihood_comes_free_from_the_filter(self):
        """It accumulates, it is finite, and it is a sum of log **densities** -
        so it is positive when the variances are small, which is not a bug and
        was my first wrong assertion about it."""
        g = Gaussian(jerk=1e-4, at=0.0)
        for i in range(50):
            g.update(1.0, noise=0.01, when=i * HOUR)
        assert g.seen == 50
        assert math.isfinite(g.loglike)

        # The property that carries the fit: the same data is *less* likely under
        # a filter told the measurements are noisier than they are.
        loose = Gaussian(jerk=1e-4, at=0.0)
        for i in range(50):
            loose.update(1.0, noise=4.0, when=i * HOUR)
        assert loose.loglike < g.loglike

    def test_the_burn_in_excludes_the_diffuse_prior(self):
        """**What the burn-in is actually for.** A diffuse prior makes the first
        innovations enormous relative to a variance nobody chose, so those terms
        say more about the prior than the data. Statsmodels calls the same thing
        `loglikelihood_burn` and drops one term per diffuse state.

        Shown on a genuinely diffuse start - a wide `p00` with the state already
        seeded, so the first-reading shortcut does not fire and the early terms
        are the badly-informed ones they are meant to be.
        """

        def diffuse(burn: int) -> float:
            g = Gaussian(jerk=1e-6, at=0.0, burn=burn)
            g.value, g.p00, g.seen = 0.0, 1e6, 1  # no idea where it is
            for i in range(40):
                g.update(5.0, noise=0.01, when=i * HOUR)
            return g.loglike

        with_prior = diffuse(0)
        without = diffuse(3)
        assert with_prior != without
        # Dropping terms dominated by a prior nobody chose raises the likelihood,
        # because those are the ones the model was always going to fit badly.
        assert without > with_prior

        # It drops them one at a time, and the state is seeded with `seen = 1`,
        # so `burn = 1` excludes nothing.
        assert diffuse(1) == pytest.approx(with_prior)
        # `burn = 2` excludes the single term the diffuse prior ruins.
        assert diffuse(2) > with_prior
        # **And more is worse, which is why the default is one per diffuse state
        # rather than a comfortable margin.** Past the badly-informed terms the
        # burn-in is just discarding data, and the likelihood says so.
        assert diffuse(3) < diffuse(2)
        assert diffuse(5) < diffuse(3)

    def test_maximum_likelihood_recovers_a_jerk_it_was_not_told(self):
        """**The headline gain from the statsmodels reading.** Every `jerk` in
        `subjects.py` is a placeholder; this is the procedure that stops it being
        one, and it needs no data the filter is not already given.
        """
        from till_infinity.structures.statespace import fit_jerk

        rng = __import__("random").Random(17)
        truth = 1e-3
        noise = 0.04

        # A path generated by the model itself, so the right answer is known.
        times, obs = [], []
        value, rate, accel = 10.0, 0.0, 0.0
        for i in range(600):
            dt = 1.0
            accel += rng.gauss(0, math.sqrt(truth * dt))
            rate += accel * dt
            value += rate * dt
            times.append(i * HOUR)
            obs.append(value + rng.gauss(0, math.sqrt(noise)))

        def run(jerk: float) -> float:
            g = Gaussian(jerk=jerk, at=0.0)
            for t, z in zip(times, obs, strict=True):
                g.update(z, noise=noise, when=t)
            return g.loglike

        got, best = fit_jerk(run)
        assert math.isfinite(best)
        # Within an order of magnitude is the honest bar for one variance from
        # 600 points; the point is that it finds the scale, not the digit.
        assert truth / 10 < got < truth * 10, got
        # And it beats both ends of the bracket it searched.
        assert best > run(1e-12)
        assert best > run(1e2)


class TestSpecification:
    def test_a_correctly_specified_filter_has_honest_residuals(self):
        from till_infinity.structures.statespace import residuals

        rng = __import__("random").Random(5)
        truth, noise = 1e-4, 0.04
        g = Gaussian(jerk=truth, at=0.0)
        z = []
        value, rate, accel = 3.0, 0.0, 0.0
        for i in range(900):
            accel += rng.gauss(0, math.sqrt(truth))
            rate += accel
            value += rate
            g.update(value + rng.gauss(0, math.sqrt(noise)), noise=noise, when=i * HOUR)
            if g.seen > g.burn:
                z.append(g.last_standardised)

        got = residuals(z)
        assert got is not None
        assert got.n > 800
        assert abs(got.sd - 1.0) < 0.35, f"spread {got.sd}"
        assert got.autocorrelated is False

    def test_a_jerk_set_far_too_small_shows_up_as_autocorrelation(self):
        """**The informative failure.** A filter told the world is calmer than it
        is treats real drift as noise, and the drift it ignored is still there in
        the residuals, in order.
        """
        from till_infinity.structures.statespace import residuals

        rng = __import__("random").Random(9)
        truth, noise = 1e-2, 0.01
        g = Gaussian(jerk=1e-12, at=0.0)  # told the level never moves
        z = []
        value, rate, accel = 3.0, 0.0, 0.0
        for i in range(600):
            accel += rng.gauss(0, math.sqrt(truth))
            rate += accel
            value += rate
            g.update(value + rng.gauss(0, math.sqrt(noise)), noise=noise, when=i * HOUR)
            if g.seen > g.burn:
                z.append(g.last_standardised)

        got = residuals(z)
        assert got is not None
        assert got.autocorrelated is True, got.ljung_box_p
        assert got.sd > 1.0, "and it is over-confident, which is the same fault"

    def test_fat_tails_show_up_as_non_normality_not_autocorrelation(self):
        """The case `robust.py` is the cheap arm for - and a better test of it
        than counting how often a gate fired."""
        from till_infinity.structures.statespace import residuals

        rng = __import__("random").Random(13)
        noise = 0.04
        g = Gaussian(jerk=1e-9, at=0.0)
        z = []
        for i in range(900):
            # A steady quantity, with one print in forty badly wrong.
            bad = rng.random() < 0.025
            obs = 5.0 + rng.gauss(0, math.sqrt(noise)) + (rng.choice([-3.0, 3.0]) if bad else 0.0)
            g.update(obs, noise=noise, when=i * HOUR)
            if g.seen > g.burn:
                z.append(g.last_standardised)

        got = residuals(z)
        assert got is not None
        assert got.non_normal is True, got.jarque_bera_p
        assert got.kurtosis > 3.0, "fat tails, which is what non-normal means here"

    def test_too_few_residuals_is_no_answer_rather_than_a_weak_one(self):
        from till_infinity.structures.statespace import residuals

        assert residuals([0.1] * 29) is None
        assert residuals([0.1] * 40, lags=9) is None, "odd lags have no exact p-value"

    def test_the_overconfidence_reading_is_the_one_production_already_uses(self):
        """`vol-particle.md` measured the shipped EWMA at 1.199 to 1.291 against
        an honest 1.0 - 18-29% over-confident. Same statistic, same meaning."""
        from till_infinity.structures.statespace import residuals

        rng = __import__("random").Random(3)
        tight = [rng.gauss(0, 1.25) for _ in range(2000)]
        got = residuals(tight)
        assert got is not None
        assert got.overconfident == pytest.approx(got.sd)
        assert 1.15 < got.overconfident < 1.35


class TestPaths:
    def test_a_generated_path_is_recoverable_by_the_filter_that_assumes_it(self):
        """**The honest version of the earlier recovery test.** It hand-rolled a
        generator; this one uses the model's own, so "recover a parameter" cannot
        quietly be testing a different process than the filter assumes."""
        from till_infinity.structures.statespace import Gaussian, fit_jerk, hourly, simulate

        truth = 1e-3
        path = simulate(hourly(500), jerk=truth, noise=0.04, seed=3)
        assert len(path) == 500
        assert path.jerk == truth

        def run(jerk: float) -> float:
            g = Gaussian(jerk=jerk, at=0.0)
            for t, z in zip(path.times, path.measured, strict=True):
                g.update(z, noise=path.noise, when=t)
            return g.loglike

        got, _best = fit_jerk(run)
        assert truth / 10 < got < truth * 10, got

    def test_the_measurement_noise_is_what_separates_truth_from_measured(self):
        from till_infinity.structures.statespace import hourly, simulate

        noise = 0.25
        path = simulate(hourly(2000), jerk=0.0, noise=noise, seed=7)
        # jerk of zero: the latent value never moves off its start.
        assert max(abs(v - path.truth[0]) for v in path.truth) == pytest.approx(0.0)
        errors = [m - t for m, t in zip(path.measured, path.truth, strict=True)]
        spread = math.sqrt(sum(e * e for e in errors) / len(errors))
        assert spread == pytest.approx(math.sqrt(noise), rel=0.08)

    def test_a_weekend_gap_injects_a_weekend_of_variance(self):
        """**The generator-side form of I6.** A scheme that adds a fixed amount
        of noise per *sample* would make these two paths identical, and a filter
        fitted on it would learn a jerk that is wrong by the ratio of the gaps.
        """
        from till_infinity.structures.statespace import simulate

        tight = tuple(i * HOUR for i in range(60))
        loose = tuple(i * 62.0 * HOUR for i in range(60))

        a = simulate(tight, jerk=1e-3, noise=0.0, seed=5)
        b = simulate(loose, jerk=1e-3, noise=0.0, seed=5)
        # Same number of samples, same seed, same jerk - 62x the elapsed time.
        assert len(a) == len(b)
        travelled_a = max(abs(v - a.truth[0]) for v in a.truth)
        travelled_b = max(abs(v - b.truth[0]) for v in b.truth)
        assert travelled_b > travelled_a * 100, (travelled_a, travelled_b)

    def test_the_jerk_increment_is_correlated_across_the_three_states(self):
        """Drawing the three independently would generate a process this filter
        is not a filter for. With `jerk` driving only the third state, the value
        and the rate move together."""
        from till_infinity.structures.statespace import hourly, simulate

        path = simulate(hourly(400), jerk=1e-2, noise=0.0, seed=11)
        # The rate is the derivative of the value, so differences of the value
        # should track the rate rather than being independent of it.
        diffs = [path.truth[i + 1] - path.truth[i] for i in range(len(path) - 1)]
        mids = [path.rates[i] for i in range(len(path) - 1)]
        n = len(diffs)
        md, mm = sum(diffs) / n, sum(mids) / n
        cov = sum((d - md) * (m - mm) for d, m in zip(diffs, mids, strict=True)) / n
        sd_d = math.sqrt(sum((d - md) ** 2 for d in diffs) / n)
        sd_m = math.sqrt(sum((m - mm) ** 2 for m in mids) / n)
        assert cov / (sd_d * sd_m) > 0.9, "the value's increments must follow its rate"

    def test_gapped_times_have_the_shape_this_desk_actually_produces(self):
        from till_infinity.structures.statespace import with_gaps

        times = with_gaps(100, step_hours=1.0, gap_hours=62.0, every=24)
        gaps = sorted({round((times[i + 1] - times[i]) / 3600.0, 1) for i in range(len(times) - 1)})
        assert gaps == [1.0, 62.0]

    def test_a_path_needs_at_least_two_times(self):
        from till_infinity.structures.statespace import simulate

        with pytest.raises(ValueError, match="at least two"):
            simulate([0.0], jerk=1e-3, noise=0.01)

    def test_the_residuals_of_a_correctly_generated_path_are_honest(self):
        """Generator and filter agreeing is the weakest useful check and the one
        worth having: if the standardised innovations are not standard normal
        here, one of the two is wrong."""
        from till_infinity.structures.statespace import Gaussian, hourly, residuals, simulate

        truth, noise = 1e-4, 0.04
        path = simulate(hourly(1200), jerk=truth, noise=noise, seed=19)
        g = Gaussian(jerk=truth, at=0.0)
        z = []
        for t, m in zip(path.times, path.measured, strict=True):
            g.update(m, noise=noise, when=t)
            if g.seen > g.burn:
                z.append(g.last_standardised)

        got = residuals(z)
        assert got is not None
        assert abs(got.sd - 1.0) < 0.3, f"spread {got.sd}"
        assert got.autocorrelated is False
        assert got.non_normal is False


def test_the_missing_inference_modes_are_named_rather_than_left_out():
    """A gap that is written down can be argued about; one that is not just looks
    like the package does not need it.

    The finished-series smoother was the real absence and is now `smoothing.py`;
    what is left is the **fixed-lag** form, which is the only one with bounded
    latency, and EM.
    """
    from till_infinity.structures.statespace import MISSING

    assert set(MISSING) == {
        "fixed-lag smoother",
        "on-line smoothing",
        "monte carlo variance",
        "sequential parameter learning",
        "evidence",
        "em",
    }
    assert "smoothed posterior" in MISSING["em"], "EM needs the smoother first"
    for name, note in MISSING.items():
        assert len(note) > 40, f"{name} is listed without saying what it unlocks"


def test_a_member_is_identified_by_which_of_three_distributions_changes():
    """**The decomposition that makes "which filter" answerable.**

    A state-space model is `PX0` (where the state starts), `PX` (how it moves)
    and `PY` (how it is observed). Choosing a family member is then a question
    about which of the three is wrong, not a judgement call - and it places
    `robust.py` exactly: it changes `PY` alone, so it is a claim about the
    measurement and the innovations' *normality* tests it, while the dynamics
    and therefore their *autocorrelation* are untouched.
    """
    from till_infinity.structures.statespace import family

    # Whitespace-normalised: a docstring assertion that breaks when the prose is
    # rewrapped is testing the formatter, not the claim.
    doc = " ".join((family.__doc__ or "").split())
    for part in ("PX0", "PX(t, x_prev)", "PY(t, x_prev, x)"):
        assert part in doc, part
    assert "heavy-tailed" in doc, "robust must be placed as a PY change"
    assert "nonlinear" in doc, "I4 must be placed as a PX question"
    # And the set layer sits outside the factoring, which is why it is its own
    # phase rather than another member.
    assert "number of states" in doc


def test_the_particle_entry_records_what_it_will_need():
    """Resampling is a choice and fitting through a particle filter needs a
    differentiable one. Recorded now so it is not rediscovered later."""
    from till_infinity.structures.statespace import PENDING

    note = PENDING["particle"]
    assert "systematic" in note, "the scheme the volatility harness used"
    assert "arXiv" in note or "PyDPF" in note


def test_the_smoother_is_written_and_listed_as_an_inference_mode():
    """`family.py` tracks three operations - filter, smooth, sample. All three
    exist now, and the table has to say so rather than still claiming a gap."""
    from till_infinity.structures.statespace import MISSING, family

    doc = " ".join((family.__doc__ or "").split())
    assert "smoothing.smooth" in doc, "the table must point at the implementation"
    assert "smoother" not in MISSING
    assert "fixed-lag smoother" in MISSING


def test_the_package_is_not_in_the_state_files_persistence_schema():
    """**The coupling the one-way import test could not catch.**

    `shared.codec.registry` builds the schema by walking every module under
    `structures` and collecting every dataclass - by *discovery*, not by import.
    So this package landed in production's 128MB persistence fingerprint the
    moment it existed, and a field added here would have been a schema change on
    state none of it is in. `tests/test_structures.py` caught it by a different
    route and the tempting fix - making these classes `Restorable` - would have
    declared them persistable, which is false.
    """
    import till_infinity.structures as pkg
    from till_infinity.shared import codec

    schema = codec.registry(pkg)
    assert schema, "the registry should still find the real persisted classes"
    leaked = sorted(k for k, cls in schema.items() if "statespace" in cls.__module__)
    assert not leaked, f"statespace is in the persistence schema: {leaked}"

    # And the opt-out is what keeps it out, declared where the walk can see it.
    from till_infinity.structures import statespace

    assert statespace.CODEC_UNPERSISTED is True
    assert codec.skipped("till_infinity.structures.statespace.linear") is True
    assert codec.skipped("till_infinity.structures.levels") is False, (
        "the default has to stay 'a dataclass in a service is state'"
    )


class TestSmoothing:
    def test_the_smoother_beats_the_filter_on_the_same_data(self):
        """**The reason it exists.** At time `t` the filter has thrown away every
        measurement after `t`, and those say a great deal about where the state
        was. Measured against a path whose truth is known."""
        from till_infinity.structures.statespace import hourly, simulate, smooth

        truth, noise = 1e-3, 0.09
        path = simulate(hourly(500), jerk=truth, noise=noise, seed=5)
        got = smooth(path.times, path.measured, jerk=truth, noise=noise)
        assert got is not None
        assert len(got) == 500

        def rmse(a, b):
            return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) / len(a))

        filtered = rmse(got.filtered, path.truth)
        smoothed = rmse(got.value, path.truth)
        assert smoothed < filtered, (smoothed, filtered)
        # Not marginally: using the future is worth a third of the error here.
        assert smoothed < filtered * 0.8

    def test_the_smoothed_uncertainty_is_never_worse_than_the_filtered(self):
        """Conditioning on more data cannot widen a posterior. The property that
        says the backward pass is the backward pass and not a smoother-looking
        average."""
        from till_infinity.structures.statespace import hourly, simulate, smooth

        path = simulate(hourly(300), jerk=1e-3, noise=0.04, seed=8)
        got = smooth(path.times, path.measured, jerk=1e-3, noise=0.04)
        assert got is not None
        for i, (s, f) in enumerate(zip(got.sd, got.filtered_sd, strict=True)):
            assert s <= f + 1e-9, f"point {i}: smoothed {s} > filtered {f}"
        # And the last point is conditioned on exactly what the filter had.
        assert got.sd[-1] == pytest.approx(got.filtered_sd[-1])

    def test_it_tracks_a_known_path_through_a_weekend_gap(self):
        """Uneven sampling is the case the whole package is about, and a backward
        pass that assumed even steps would come apart here."""
        from till_infinity.structures.statespace import simulate, smooth, with_gaps

        times = with_gaps(240, step_hours=1.0, gap_hours=62.0, every=24)
        path = simulate(times, jerk=1e-4, noise=0.04, seed=12)
        got = smooth(times, path.measured, jerk=1e-4, noise=0.04)
        assert got is not None
        assert all(math.isfinite(v) for v in got.value)
        assert all(math.isfinite(v) for v in got.sd)

        def rmse(a, b):
            return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) / len(a))

        assert rmse(got.value, path.truth) < rmse(got.filtered, path.truth)

    def test_the_likelihood_is_the_forward_passs_and_is_carried_through(self):
        """A smoother has no innovations of its own - it has already used every
        measurement - so the likelihood is the filter's, reported here to save
        running the forward pass twice."""
        from till_infinity.structures.statespace import Gaussian, hourly, simulate, smooth

        path = simulate(hourly(200), jerk=1e-3, noise=0.04, seed=4)
        got = smooth(path.times, path.measured, jerk=1e-3, noise=0.04)
        assert got is not None

        g = Gaussian(jerk=1e-3)
        for t, z in zip(path.times, path.measured, strict=True):
            g.update(z, noise=0.04, when=t)
        assert got.loglike == pytest.approx(g.loglike)

    def test_two_measurements_at_one_instant_do_not_break_it(self):
        """Two venues reporting the same bar is routine, and it makes the step
        between them zero - which has no gain to compute. Falling back to the
        filtered estimate there is right; raising would not be."""
        from till_infinity.structures.statespace import smooth

        times = [0.0, HOUR, HOUR, 2 * HOUR, 3 * HOUR] + [(4 + i) * HOUR for i in range(40)]
        measured = [5.0 + 0.01 * i for i in range(len(times))]
        got = smooth(times, measured, jerk=1e-4, noise=0.01)
        assert got is not None
        assert all(math.isfinite(v) for v in got.value)

    def test_a_series_too_short_to_smooth_returns_nothing(self):
        from till_infinity.structures.statespace import smooth

        assert smooth([0.0], [1.0], jerk=1e-3, noise=0.01) is None
        assert smooth([], [], jerk=1e-3, noise=0.01) is None

    def test_a_wrong_jerk_is_confidently_wrong_and_the_filter_is_where_it_shows(self):
        """**What a smoother cannot fix.** Told the level never moves, it produces
        a smooth, tight, wrong path - and the filtered innovations are still the
        place that says so."""
        from till_infinity.structures.statespace import Gaussian, hourly, residuals, simulate

        path = simulate(hourly(600), jerk=1e-2, noise=0.01, seed=6)
        g = Gaussian(jerk=1e-12)
        z = []
        for t, m in zip(path.times, path.measured, strict=True):
            g.update(m, noise=0.01, when=t)
            if g.seen > g.burn:
                z.append(g.last_standardised)
        got = residuals(z)
        assert got is not None
        assert got.autocorrelated is True, "the misspecification shows in the forward pass"


def test_the_fixed_lag_form_is_what_is_still_missing():
    """`smooth` needs the whole series, so its latency is the series. The
    fixed-lag form bounds it by the lag and is the only version a desk could
    read - and even then probably should not."""
    from till_infinity.structures.statespace import MISSING

    assert "fixed-lag smoother" in MISSING
    assert "smoother" not in MISSING, "the finished-series smoother is written now"
    assert "latency" in MISSING["fixed-lag smoother"]


def test_the_comparison_rule_is_held_out_and_says_why():
    """**A correctness point, not hygiene.** Members do not have the same number
    of free parameters, and in-sample likelihood rewards whichever has more - a
    particle filter with a richer transition fits a training series better than a
    Kalman whatever the truth is. Held-out likelihood or the model evidence are
    the honest comparisons, and this package has only the first.
    """
    from till_infinity.structures.statespace import MISSING, family

    doc = " ".join((family.__doc__ or "").split())
    assert "held-out" in doc
    assert "evidence" in doc
    assert "evidence" in MISSING, "and it must be listed as absent"


def test_smoothing_cost_is_recorded_as_a_property_of_the_member():
    """It is nearly free for the linear-Gaussian member and the dominant expense
    for the particle one, which changes what a tie means: on levels the particles
    tied, so they cost O(N) to O(N^2) for nothing, on a two-core box."""
    from till_infinity.structures.statespace import family

    doc = " ".join((family.__doc__ or "").split())
    assert "Cost is a property of the member" in doc
    assert "O(T N^2)" in doc or "O(T N) to O(T N^2)" in doc


def test_a_particle_member_would_need_an_error_bar_on_its_own_noise():
    """Run a particle filter twice with different seeds and it answers
    differently. Without a variance estimator, "beat the Kalman by 3%" cannot be
    told from that."""
    from till_infinity.structures.statespace import MISSING

    note = MISSING["monte carlo variance"]
    assert "seeds" in note
    assert "Olsson" in note or "Chan and Lai" in note


class TestSmootherAgainstADenseReference:
    """**The check that was missing, and the bug it would have caught.**

    The hand-written transition matrix was verified against `scipy`'s
    zero-order hold. The smoother was verified against nothing, and it was
    wrong: `_gain` built the columns of `P F'` in reverse, which produced a
    plausible answer - it still smoothed, still beat the filter, and was 19%
    worse than it should have been.

    What exposed it was not inspection but a property: a *wrong* `jerk` beat the
    true one on 25 seeds out of 25. The RTS mean is the minimum-mean-square
    estimator at the true parameters, so anything beating it is a bug rather
    than a discovery.
    """

    @staticmethod
    def _reference(times, meas, q, r, burn=3):
        """Dense RTS in numpy, matching `Gaussian`'s conventions exactly."""
        np = pytest.importorskip("numpy")

        def transition(dt):
            return np.array([[1, dt, 0.5 * dt * dt], [0, 1, dt], [0, 0, 1]], float)

        def process(dt):
            d2, d3 = dt * dt, dt**3
            return q * np.array(
                [
                    [d3 * d2 / 20, d2 * d2 / 8, d3 / 6],
                    [d2 * d2 / 8, d3 / 3, d2 / 2],
                    [d3 / 6, d2 / 2, dt],
                ],
                float,
            )

        obs = np.array([[1.0, 0.0, 0.0]])
        n = len(times)
        x, cov = np.zeros(3), np.diag([1.0, 0.0, 0.0])
        posts, preds, dts, seen = [], [], [], 0
        for i in range(n):
            dt = 0.0 if i == 0 else (times[i] - times[i - 1]) / HOUR
            dts.append(dt)
            if i > 0 and dt > 0:
                x = transition(dt) @ x
                cov = transition(dt) @ cov @ transition(dt).T + process(dt)
            preds.append((x.copy(), cov.copy()))
            if seen == 0 and cov[0, 0] >= 1.0:
                x, cov, seen = np.array([meas[i], 0.0, 0.0]), np.diag([r, 0.0, 0.0]), 1
            else:
                s = float(cov[0, 0] + r)
                gain = (cov @ obs.T / s).ravel()
                x = x + gain * (meas[i] - x[0])
                cov = cov - np.outer(gain, cov[0, :])
                seen += 1
            posts.append((x.copy(), cov.copy()))

        sx = [p[0].copy() for p in posts]
        sp = [p[1].copy() for p in posts]
        for i in range(n - 2, -1, -1):
            dt = dts[i + 1]
            if dt <= 0:
                continue
            pred_cov = preds[i + 1][1]
            c = posts[i][1] @ transition(dt).T @ np.linalg.inv(pred_cov)
            sx[i] = posts[i][0] + c @ (sx[i + 1] - preds[i + 1][0])
            sp[i] = posts[i][1] + c @ (sp[i + 1] - pred_cov) @ c.T
        return sx, sp

    def test_it_matches_the_reference_on_state_and_covariance(self):
        from till_infinity.structures.statespace import hourly, simulate, smooth

        truth, noise = 1e-3, 0.09
        path = simulate(hourly(250), jerk=truth, noise=noise, seed=5)
        ref_x, ref_p = self._reference(list(path.times), list(path.measured), truth, noise)
        mine = smooth(path.times, path.measured, jerk=truth, noise=noise)
        assert mine is not None

        for name, column, got in (
            ("value", 0, mine.value),
            ("rate", 1, mine.rate),
            ("accel", 2, mine.accel),
        ):
            worst = max(abs(r[column] - m) for r, m in zip(ref_x, got, strict=True))
            assert worst < 1e-8, f"{name} diverges by {worst:.3e}"
        worst_sd = max(
            abs(math.sqrt(max(r[0, 0], 0.0)) - m) for r, m in zip(ref_p, mine.sd, strict=True)
        )
        assert worst_sd < 1e-9, f"sd diverges by {worst_sd:.3e}"

    def test_the_true_parameters_cannot_be_beaten_by_wrong_ones(self):
        """**The property that found the bug.** The RTS mean is the MMSE estimator
        at the true parameters, so a wrong `jerk` should win only by sampling
        luck. It won 25 times out of 25 while `_gain` was wrong."""
        from till_infinity.structures.statespace import hourly, simulate, smooth

        truth, noise = 1e-3, 0.09

        def rmse(a, b):
            return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) / len(a))

        beaten = 0
        trials = 20
        for seed in range(trials):
            path = simulate(hourly(300), jerk=truth, noise=noise, seed=400 + seed)
            at_truth = rmse(
                smooth(path.times, path.measured, jerk=truth, noise=noise).value, path.truth
            )
            best_wrong = min(
                rmse(smooth(path.times, path.measured, jerk=j, noise=noise).value, path.truth)
                for j in (truth / 3, truth * 3)
            )
            beaten += best_wrong < at_truth
        assert beaten <= trials // 3, (
            f"a wrong jerk beat the true one on {beaten}/{trials} seeds - that is "
            "systematic, not sampling noise, and means the recursion is wrong"
        )

    def test_it_is_as_uncertain_as_it_is_wrong(self):
        """Calibration, which is the other face of the same property: at the true
        parameters the posterior standard deviation should match the realised
        error. It read 0.715 while `_gain` was wrong."""
        from till_infinity.structures.statespace import hourly, simulate, smooth

        truth, noise = 1e-3, 0.09
        path = simulate(hourly(600), jerk=truth, noise=noise, seed=5)
        got = smooth(path.times, path.measured, jerk=truth, noise=noise)
        assert got is not None

        err = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(got.value, path.truth, strict=True)) / len(got)
        )
        stated = math.sqrt(sum(s * s for s in got.sd) / len(got))
        assert 0.8 < err / stated < 1.25, f"rmse/sd = {err / stated:.3f}"

    def test_a_misspecified_model_is_over_confident_and_that_is_the_signal(self):
        """What a smoother cannot fix. Given a mean-reverting rate - not a triple
        integrator - the best-fit `jerk` produces a smooth, tight, wrong path,
        and the ratio above goes the other way. This is I3's marginal stability
        showing up as a number."""
        import random

        from till_infinity.structures.statespace import Gaussian, fit_jerk, hourly, smooth

        rng = random.Random(3)
        noise = 0.09
        times = hourly(500)
        value, rate, truth, meas = 0.0, 0.0, [], []
        for _ in times:
            rate = 0.9 * rate + rng.gauss(0, 0.05)
            value += rate
            truth.append(value)
            meas.append(value + rng.gauss(0, math.sqrt(noise)))

        def run(jerk: float) -> float:
            g = Gaussian(jerk=jerk)
            for t, z in zip(times, meas, strict=True):
                g.update(z, noise=noise, when=t)
            return g.loglike

        jerk, _ = fit_jerk(run)
        got = smooth(times, meas, jerk=jerk, noise=noise)
        assert got is not None
        err = math.sqrt(sum((a - b) ** 2 for a, b in zip(got.value, truth, strict=True)) / len(got))
        stated = math.sqrt(sum(s * s for s in got.sd) / len(got))
        assert err / stated > 1.15, (
            f"rmse/sd = {err / stated:.3f} - a model this wrong should be visibly over-confident"
        )


class TestEveryHandWrittenFormula:
    """**The audit the smoother bug prompted, kept as tests.**

    `_gain` was wrong and nothing caught it because it was checked against
    nothing. These are every other place in the package where matrix algebra,
    a discretisation or a statistic was written out by hand, each against an
    independent reference. All of them passed on 2026-10-10; they are here so
    that stays true rather than so it can be claimed.
    """

    def test_the_generators_increments_have_the_covariance_it_claims(self):
        """`paths.simulate` draws correlated `(value, rate, accel)` increments
        from a hand-written Cholesky of `Q(dt)`. It is load-bearing for every
        recovery result in this file, so it is checked empirically."""
        np = pytest.importorskip("numpy")
        from till_infinity.structures.statespace import simulate

        q, dt = 1e-2, 1.5
        incs = []
        for seed in range(4000):
            drawn = simulate([0.0, dt * HOUR], jerk=q, noise=0.0, seed=seed)
            incs.append([drawn.truth[1] - drawn.truth[0], drawn.rates[1] - drawn.rates[0]])
        d2, d3 = dt * dt, dt**3
        want = q * np.array([[d3 * d2 / 20, d2 * d2 / 8], [d2 * d2 / 8, d3 / 3]])
        emp = np.cov(np.array(incs).T)
        rel = float(np.max(np.abs(emp - want) / np.maximum(np.abs(want), 1e-12)))
        assert rel < 0.12, f"increment covariance is off by {rel:.3f} relative"

    def test_band_agrees_with_actually_predicting_forward(self):
        """`band` propagates the covariance to a future time with its own copy of
        `F P F' + Q`. Two hand-written versions of one formula is exactly the
        shape `_gain` failed in, so they are compared."""
        from till_infinity.structures.statespace import Gaussian

        fields = (
            "value",
            "rate",
            "accel",
            "p00",
            "p01",
            "p02",
            "p11",
            "p12",
            "p22",
            "jerk",
            "at",
            "seen",
        )
        for ahead_hours in (0.0, 1.0, 7.0, 72.0):
            a = Gaussian(jerk=1e-3, at=0.0)
            for i in range(30):
                a.update(5.0 + 0.1 * i, noise=0.04, when=i * HOUR)
            when = a.at + ahead_hours * HOUR
            low, high = a.band(when, sigmas=1.0)
            b = Gaussian(**{k: getattr(a, k) for k in fields})
            b.predict(when)
            assert (high - low) / 2.0 == pytest.approx(b.sd, abs=1e-9), ahead_hours
            assert a.at_time(when) == pytest.approx(b.value, abs=1e-9), ahead_hours

    def test_the_slope_and_its_variance_match_ordinary_least_squares(self):
        np = pytest.importorskip("numpy")
        from till_infinity.structures.statespace import slope_per_hour

        rng = np.random.default_rng(4)
        times = np.sort(rng.uniform(0, 400, 120)) * HOUR
        hours = times / HOUR
        vals = 3.0 + 0.7 * hours + rng.normal(0, 2.0, 120)

        got = slope_per_hour(times.tolist(), vals.tolist())
        assert got is not None
        fit = np.polyfit(hours, vals, 1)
        assert got.per_hour == pytest.approx(float(fit[0]), abs=1e-9)

        rss = float(np.sum((vals - np.polyval(fit, hours)) ** 2))
        sxx = float(np.sum((hours - hours.mean()) ** 2))
        assert got.variance == pytest.approx((rss / (len(hours) - 2)) / sxx, rel=1e-9)

    def test_per_bar_equals_the_incumbent_when_the_bars_are_even(self):
        """A claim made in a comment - that the two conventions differ by exactly
        the bar length in hours - and therefore worth asserting."""
        from till_infinity.structures.statespace import slope_per_bar, slope_per_hour

        values = [2.0 + 0.4 * i for i in range(50)]
        got = slope_per_hour([i * HOUR for i in range(50)], values)
        assert got is not None
        assert got.per_bar == pytest.approx(slope_per_bar(values), abs=1e-9)

    def test_golden_section_finds_a_peak_it_was_not_told(self):
        from till_infinity.structures.statespace import fit_jerk

        peak = 3.7e-5
        found, _best = fit_jerk(lambda j: -((math.log10(j) - math.log10(peak)) ** 2))
        assert math.log10(found) == pytest.approx(math.log10(peak), abs=0.03)

    def test_the_residual_statistics_match_a_numpy_computation(self):
        np = pytest.importorskip("numpy")
        from till_infinity.structures.statespace import residuals

        rng = np.random.default_rng(4)
        # Deliberately autocorrelated, so the statistic is not near zero where
        # any two implementations would agree by accident.
        z = np.convolve(rng.normal(0, 1, 800), [1.0, 0.6], mode="same")
        got = residuals(z.tolist(), lags=10)
        assert got is not None

        centred = z - z.mean()
        n = len(centred)
        var = float(np.mean(centred * centred))
        rhos = [float(np.sum(centred[k:] * centred[:-k]) / (var * n)) for k in range(1, 11)]
        want_q = n * (n + 2) * sum(r * r / (n - k) for k, r in zip(range(1, 11), rhos, strict=True))
        assert got.ljung_box == pytest.approx(want_q, rel=1e-9)

        want_skew = float(np.mean(centred**3) / np.std(z) ** 3)
        want_kurt = float(np.mean(centred**4) / np.var(z) ** 2)
        assert got.skew == pytest.approx(want_skew, abs=1e-9)
        assert got.kurtosis == pytest.approx(want_kurt, abs=1e-9)
        assert got.jarque_bera == pytest.approx(
            n / 6.0 * (want_skew**2 + 0.25 * (want_kurt - 3.0) ** 2), rel=1e-9
        )


class TestRevertingRate:
    """I3: a rate that pulls back instead of running away.

    Written because it was measured first - on eurusd 4h, held out, it beat the
    white-jerk model by 0.96 nats per point and took the innovation spread from
    1.294 to 0.985. It arrives with its reference, which is the rule the
    `_gain` bug bought.
    """

    def test_the_discretisation_matches_a_numerical_integration(self):
        """`Q(dt)` for an integrated Ornstein-Uhlenbeck, against the integral it
        is a closed form of: `Q = int_0^dt e^As Qc e^A's ds`, by quadrature.

        **Quadrature rather than van Loan, and that is a finding.** The
        matrix-exponential construction was the obvious reference and it is the
        *less* accurate one here: at `theta = 0.5`, `dt = 62` - a weekend gap,
        so not an exotic case - `scipy.linalg.expm` of the 4x4 block gives
        42.47009 where quadrature over 200,001 points, an independently derived
        analytic form, and this implementation all give 42.48000000. The block
        matrix has norm 62 and `expm` loses the digits.

        So the reference needed guarding, not the code. Van Loan is still
        checked below, where its argument is small enough to trust.
        """
        np = pytest.importorskip("numpy")
        linalg = pytest.importorskip("scipy.linalg")
        integrate = pytest.importorskip("scipy.integrate")
        from till_infinity.structures.statespace.reverting import _process

        sigma2 = 0.18
        for theta in (0.02, 0.5, 3.0):
            for dt in (0.25, 1.0, 4.0, 62.0):
                a = np.array([[0.0, 1.0], [0.0, -theta]])
                qc = np.array([[0.0, 0.0], [0.0, sigma2]])
                grid = np.linspace(0.0, dt, 4001)
                stack = np.empty((grid.size, 2, 2))
                for index, point in enumerate(grid):
                    moved = linalg.expm(a * point)
                    stack[index] = moved @ qc @ moved.T
                want = np.array(
                    [
                        [integrate.simpson(stack[:, r, c], x=grid) for c in range(2)]
                        for r in range(2)
                    ]
                )

                q00, q01, q11 = _process(dt, sigma2, theta)
                assert q00 == pytest.approx(want[0, 0], rel=1e-6), (theta, dt, "q00")
                assert q01 == pytest.approx(want[0, 1], rel=1e-6), (theta, dt, "q01")
                assert q11 == pytest.approx(want[1, 1], rel=1e-6), (theta, dt, "q11")

    def test_van_loan_agrees_where_its_argument_is_small_enough_to_trust(self):
        """The construction is right; it is the arithmetic that degrades. Kept
        as a second reference over the range where it holds, so that a future
        change to `_process` has two independent checks rather than one."""
        np = pytest.importorskip("numpy")
        linalg = pytest.importorskip("scipy.linalg")
        from till_infinity.structures.statespace.reverting import _process

        sigma2 = 0.18
        for theta, dt in ((0.02, 1.0), (0.5, 4.0), (3.0, 1.0), (0.1, 10.0)):
            assert theta * dt <= 12.0, "beyond this expm is the inaccurate one"
            a = np.array([[0.0, 1.0], [0.0, -theta]])
            qc = np.array([[0.0, 0.0], [0.0, sigma2]])
            block = np.zeros((4, 4))
            block[:2, :2] = a * dt
            block[:2, 2:] = qc * dt
            block[2:, 2:] = -a.T * dt
            exp = linalg.expm(block)
            want = exp[:2, 2:] @ exp[:2, :2].T
            want = (want + want.T) / 2.0

            q00, q01, q11 = _process(dt, sigma2, theta)
            assert q00 == pytest.approx(want[0, 0], rel=1e-8), (theta, dt, "q00")
            assert q01 == pytest.approx(want[0, 1], rel=1e-8), (theta, dt, "q01")
            assert q11 == pytest.approx(want[1, 1], rel=1e-8), (theta, dt, "q11")

    def test_it_reduces_to_white_acceleration_as_reversion_vanishes(self):
        """**Where the cancellation bites.** The exact `q00` is
        `dt - 2(1-e^-u)/theta + (1-e^-2u)/(2 theta)`, whose first two orders in
        `u` cancel identically - so a naive evaluation loses eight significant
        figures at `u = 1e-4` and the series is used instead. A discretisation
        wrong only in the limit is wrong exactly where it matters: a long gap."""
        from till_infinity.structures.statespace.reverting import _process

        dt, sigma2 = 2.0, 0.3
        for theta in (1e-9, 1e-7, 1e-5, 1e-4):
            q00, q01, q11 = _process(dt, sigma2, theta)
            # The *true* value departs from the limit at first order in
            # `theta * dt` - `g(u) = u^3/3 - u^4/4`, so q00 is low by about
            # `0.75 * theta * dt` - and asserting the limit more tightly than
            # that would be asserting the physics away. At theta = 1e-4 this is
            # 1.5e-4 relative, which is what a tolerance of 1e-4 rejected.
            room = max(1e-9, 2.0 * theta * dt)
            assert q00 == pytest.approx(sigma2 * dt**3 / 3.0, rel=room), theta
            assert q01 == pytest.approx(sigma2 * dt * dt / 2.0, rel=room), theta
            assert q11 == pytest.approx(sigma2 * dt, rel=room), theta
        # And with no reversion at all it is integrated Brownian motion exactly.
        assert _process(dt, sigma2, 0.0) == (
            pytest.approx(sigma2 * dt**3 / 3.0),
            pytest.approx(sigma2 * dt * dt / 2.0),
            pytest.approx(sigma2 * dt),
        )

    def test_the_projection_is_bounded_where_the_other_one_runs_away(self):
        """**The whole of I3 in one assertion.** A reverting rate contributes at
        most `rate / theta` however far ahead you ask, so a horizon cap becomes
        unnecessary rather than merely unused."""
        from till_infinity.structures.statespace import Gaussian, Reverting

        rev = Reverting(sigma2=0.18, theta=0.5)
        jerk = Gaussian(jerk=1e-3)
        for i in range(40):
            rev.update(5.0 + 0.05 * i, noise=0.16, when=i * HOUR)
            jerk.update(5.0 + 0.05 * i, noise=0.16, when=i * HOUR)

        near = rev.at_time(rev.at + 1_000 * HOUR)
        far = rev.at_time(rev.at + 1_000_000 * HOUR)
        assert far == pytest.approx(near, abs=1e-6), "reverting must converge"
        assert abs(far - rev.value) <= abs(rev.rate / rev.theta) + 1e-9

        # The marginally stable one does not, which is the defect.
        assert abs(jerk.at_time(jerk.at + 1_000_000 * HOUR)) > 1e6

    def test_uncertainty_still_grows_with_time(self):
        """Stable dynamics bound the *mean*, not the variance. A level untouched
        for a month is still a guess."""
        from till_infinity.structures.statespace import Reverting

        g = Reverting(sigma2=0.18, theta=0.5)
        for i in range(30):
            g.update(5.0, noise=0.16, when=i * HOUR)
        tight = g.p00
        g.predict(g.at + 72 * HOUR)
        assert g.p00 > tight

    def test_the_half_life_says_what_the_model_claims(self):
        """theta = 0.5 per hour is a 1.39-hour half-life, so a 4h bar retains
        13.5% of its drift. The best-fitting model of a level's drift is one in
        which that drift is very nearly noise - which is where every other
        result on this desk that survived a control has landed."""
        from till_infinity.structures.statespace import Reverting

        g = Reverting(theta=0.5)
        assert g.half_life_hours == pytest.approx(math.log(2) / 0.5, rel=1e-9)
        assert g.half_life_hours == pytest.approx(1.386, abs=0.01)
        assert math.exp(-0.5 * 4.0) == pytest.approx(0.135, abs=0.001)
        assert Reverting(theta=0.0).half_life_hours == math.inf

    def test_it_beats_the_white_jerk_model_on_data_that_reverts(self):
        """Held out, because this model has one more parameter and in-sample fit
        would reward it for that alone."""
        import random

        from till_infinity.structures.statespace import Gaussian, Reverting

        rng = random.Random(7)
        noise, theta = 0.16, 0.3
        times = [i * HOUR for i in range(900)]
        value, rate, meas = 0.0, 0.0, []
        for _ in times:
            rate = math.exp(-theta) * rate + rng.gauss(0, 0.25)
            value += rate
            meas.append(value + rng.gauss(0, math.sqrt(noise)))

        half = len(times) // 2
        best = {}
        for label, build in (
            ("jerk", lambda p: Gaussian(jerk=p)),
            ("reverting", lambda p: Reverting(sigma2=p, theta=theta)),
        ):
            scored = []
            for power in range(-8, 2):
                f = build(10.0**power)
                for t, z in zip(times[:half], meas[:half], strict=True):
                    f.update(z, noise=noise, when=t)
                scored.append((f.loglike, 10.0**power))
            chosen = max(scored)[1]
            f = build(chosen)
            for t, z in zip(times, meas, strict=True):
                f.update(z, noise=noise, when=t)
            # Held out: re-run and take only the second half's contribution.
            warm = build(chosen)
            for t, z in zip(times[:half], meas[:half], strict=True):
                warm.update(z, noise=noise, when=t)
            before = warm.loglike
            for t, z in zip(times[half:], meas[half:], strict=True):
                warm.update(z, noise=noise, when=t)
            best[label] = warm.loglike - before

        assert best["reverting"] > best["jerk"], best

    def test_a_non_finite_measurement_is_refused(self):
        from till_infinity.structures.statespace import Reverting

        g = Reverting(sigma2=0.18, theta=0.5)
        g.update(1.0, noise=0.01, when=0.0)
        snap = (g.value, g.p00, g.seen)
        for bad in (float("nan"), float("inf")):
            g.update(bad, noise=0.01, when=HOUR)
        g.update(1.0, noise=float("nan"), when=HOUR)
        assert (g.value, g.p00, g.seen) == snap

    def test_a_state_at_unix_time_zero_still_advances(self):
        """The same sentinel trap `linear` had, asserted here too rather than
        assumed not to have been copied."""
        from till_infinity.structures.statespace import Reverting

        g = Reverting(sigma2=0.18, theta=0.5, at=0.0)
        g.update(1.0, noise=0.01, when=0.0)
        before = g.p00
        g.predict(48 * HOUR)
        assert g.p00 > before
        assert g.existence < 1.0

    def test_it_is_a_member_of_the_family(self):
        from till_infinity.structures.statespace.family import Filter, members

        got = members()
        assert "reverting" in got
        assert isinstance(got["reverting"](), Filter)


class TestTheRestAgainstAReference:
    """The components that had no independent check, now that one has bitten.

    `smoothing._gain` was wrong because it was verified against nothing. These
    close the same gap everywhere else it was still open - most urgently for
    `reverting.py`, which is new and whose filter path was checked only one
    piece at a time.
    """

    def test_the_reverting_filter_matches_a_dense_reference(self):
        """**The gap `_gain` taught me to close before shipping, not after.**

        `_process` was checked against quadrature, but the predict-and-update
        path around it - `F P F' + Q`, the gain, the covariance update - was
        only ever checked against its own arithmetic. This runs the whole filter
        against a dense numpy implementation built from the matrix definitions.
        """
        np = pytest.importorskip("numpy")
        from till_infinity.structures.statespace import Reverting
        from till_infinity.structures.statespace.reverting import _process

        sigma2, theta, noise = 0.18, 0.5, 0.16
        rng = np.random.default_rng(23)
        # Uneven on purpose: even spacing would hide a dt bug.
        times, clock = [], 0.0
        for i in range(120):
            clock += (62.0 if i % 24 == 23 else 1.0) * HOUR
            times.append(clock)
        meas = (5.0 + np.cumsum(rng.normal(0, 0.3, 120))).tolist()

        mine = Reverting(sigma2=sigma2, theta=theta)
        x = np.zeros(2)
        cov = np.diag([1.0, 0.0])
        obs = np.array([[1.0, 0.0]])
        seen = 0

        for i, (t, z) in enumerate(zip(times, meas, strict=True)):
            if i:
                dt = (t - times[i - 1]) / HOUR
                decay = math.exp(-theta * dt)
                carry = -math.expm1(-theta * dt) / theta
                trans = np.array([[1.0, carry], [0.0, decay]])
                q00, q01, q11 = _process(dt, sigma2, theta)
                x = trans @ x
                cov = trans @ cov @ trans.T + np.array([[q00, q01], [q01, q11]])
            if seen == 0 and cov[0, 0] >= 1.0:
                x, cov, seen = np.array([z, 0.0]), np.diag([noise, 0.0]), 1
            else:
                s = float(cov[0, 0] + noise)
                gain = (cov @ obs.T / s).ravel()
                x = x + gain * (z - x[0])
                cov = cov - np.outer(gain, cov[0, :])
                seen += 1
            mine.update(z, noise=noise, when=t)

            assert mine.value == pytest.approx(float(x[0]), abs=1e-10), f"value at {i}"
            assert mine.rate == pytest.approx(float(x[1]), abs=1e-10), f"rate at {i}"
            assert mine.p00 == pytest.approx(float(cov[0, 0]), abs=1e-12), f"p00 at {i}"
            assert mine.p01 == pytest.approx(float(cov[0, 1]), abs=1e-12), f"p01 at {i}"
            assert mine.p11 == pytest.approx(float(cov[1, 1]), abs=1e-12), f"p11 at {i}"

    def test_revertings_band_agrees_with_predicting_forward(self):
        """Two hand-written copies of one propagation, as in `linear`. Same
        check, because the same mistake was available."""
        from till_infinity.structures.statespace import Reverting

        fields = ("value", "rate", "p00", "p01", "p11", "sigma2", "theta", "at", "seen")
        for ahead in (0.0, 1.0, 7.0, 62.0):
            a = Reverting(sigma2=0.18, theta=0.5)
            for i in range(30):
                a.update(5.0 + 0.05 * i, noise=0.16, when=i * HOUR)
            when = a.at + ahead * HOUR
            low, high = a.band(when, sigmas=1.0)
            b = Reverting(**{k: getattr(a, k) for k in fields})
            b.predict(when)
            assert (high - low) / 2.0 == pytest.approx(b.sd, abs=1e-10), ahead
            assert a.at_time(when) == pytest.approx(b.value, abs=1e-10), ahead

    def test_the_three_by_three_inverse_matches_numpy(self):
        """The smoother's gain divides by this. Hand-written cofactors and a
        determinant, with no check until now."""
        np = pytest.importorskip("numpy")
        from till_infinity.structures.statespace.smoothing import _symmetric_3x3_inverse

        rng = np.random.default_rng(31)
        for _ in range(40):
            root = rng.normal(size=(3, 3))
            full = root @ root.T + np.eye(3) * 0.4  # symmetric positive definite
            got = _symmetric_3x3_inverse(
                full[0, 0], full[0, 1], full[0, 2], full[1, 1], full[1, 2], full[2, 2]
            )
            assert got is not None
            want = np.linalg.inv(full)
            places = ((0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2))
            for value, (r, c) in zip(got, places, strict=True):
                assert value == pytest.approx(float(want[r, c]), rel=1e-9, abs=1e-12)

    def test_a_singular_matrix_is_refused_rather_than_inverted(self):
        from till_infinity.structures.statespace.smoothing import _symmetric_3x3_inverse

        # Rank one: every row a multiple of the first.
        assert _symmetric_3x3_inverse(1.0, 1.0, 1.0, 1.0, 1.0, 1.0) is None
        assert _symmetric_3x3_inverse(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) is None

    def test_the_robust_influence_is_bounded_and_not_vanishing(self):
        """**The property that found the exponent was wrong.**

        Huber means *bounded* influence: outside the gate the gain falls as
        `1/sigma` while the innovation grows as `sigma`, so the movement settles
        to a constant. Measured across an eightfold range of surprise it does -
        0.0404 at four sigma to 0.0440 at thirty-two.

        The first implementation squared the ratio, which makes the movement
        fall as `1/sigma`: a sixteen sigma reading moved the state **less** than
        a four sigma one, 0.0071 against 0.0266. That is Tukey's redescending
        shape, not Huber's, and it is the wrong one for a level - the more a
        reading disagrees the less a redescending filter listens, which is
        backwards for a level that has genuinely broken. A real break arrives as
        a run of large innovations and the filter has to be able to follow them.
        """
        from till_infinity.structures.statespace import Robust

        moved = {}
        for surprise in (4.0, 8.0, 16.0, 32.0):
            g = Robust(jerk=1e-9, gate=2.5)
            for i in range(80):
                g.update(5.0, noise=0.01, when=i * HOUR)
            settled, spread = g.value, math.sqrt(g.p00 + 0.01)
            g.update(settled + surprise * spread, noise=0.01, when=81 * HOUR)
            moved[surprise] = abs(g.value - settled)

        # Bounded: eight times the surprise moves it within a fifth as much again.
        assert moved[32.0] < 1.2 * moved[4.0], moved
        # Not vanishing: a redescending estimator would move it *less*.
        assert moved[32.0] > moved[4.0], moved
        # And nowhere near linear, which would be eight times as far.
        assert moved[32.0] < 2.0 * moved[4.0], moved

    def test_existence_decays_on_the_same_clock_as_a_forgotten_feed(self):
        """Documented and therefore worth asserting: a quantity the desk has
        stopped seeing evidence for and a feed it has stopped seeing bars from
        are the same kind of absence, so they must not decay on two clocks."""
        from till_infinity.structures.engine import FORGET_FEED_SECONDS
        from till_infinity.structures.statespace.linear import EXISTENCE_HALF_LIFE_HOURS

        assert pytest.approx(FORGET_FEED_SECONDS / 3600.0) == EXISTENCE_HALF_LIFE_HOURS

    def test_the_smoother_is_linear_only_and_that_is_a_known_gap(self):
        """`smooth` builds a `Gaussian` itself, so it cannot smooth a
        `Reverting` - which matters, because `reverting` is the member that now
        wins. Asserted so the limitation is recorded rather than discovered."""
        import inspect

        from till_infinity.structures.statespace import smoothing

        source = inspect.getsource(smoothing.smooth)
        assert "Gaussian(" in source, "if this changes, the gap below is closed"
        signature = inspect.signature(smoothing.smooth)
        assert "jerk" in signature.parameters
        assert "theta" not in signature.parameters, (
            "a smoother that takes theta would smooth the reverting member too"
        )

    def test_accel_confidence_reads_no_information_as_no_information(self):
        """The same trap `rate_confident` avoids, on the third state."""
        from till_infinity.structures.statespace import Gaussian

        g = Gaussian(jerk=0.0)
        g.accel, g.p22 = 9.0, 0.0
        assert g.accel_confident is False
        g.p22 = 1e-6
        assert g.accel_confident is True

    def test_revertings_accel_is_the_rates_pull_and_not_a_state(self):
        """It reports `-theta * rate` because that is where the rate is heading.
        A consumer needing the acceleration's own uncertainty needs `linear`."""
        from till_infinity.structures.statespace import Reverting

        g = Reverting(sigma2=0.18, theta=0.4)
        g.rate = 2.0
        assert g.accel == pytest.approx(-0.8)
        assert not hasattr(g, "p22"), "there is no third state to carry a variance"

    def test_fit_jerk_reports_the_bracket_edge_rather_than_hiding_it(self):
        """Documented behaviour: returning the edge means the answer is outside
        the range searched, and the caller is told by getting the edge."""
        from till_infinity.structures.statespace import fit_jerk

        # Monotone increasing in jerk, so the maximum is at the top edge.
        found, _best = fit_jerk(math.log10, low=-6.0, high=-2.0)
        assert math.log10(found) == pytest.approx(-2.0, abs=0.02)
        found, _best = fit_jerk(lambda j: -math.log10(j), low=-6.0, high=-2.0)
        assert math.log10(found) == pytest.approx(-6.0, abs=0.02)
