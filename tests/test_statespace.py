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
        assert set(got) == {
            "kalman",
            "reverting",
            "robust",
            "selective",
            "swarm",
            "changepoint",
        }
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
        got = smooth(lambda: Gaussian(jerk=truth), path.times, path.measured, noise=noise)
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
        got = smooth(lambda: Gaussian(jerk=1e-3), path.times, path.measured, noise=0.04)
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
        got = smooth(lambda: Gaussian(jerk=1e-4), times, path.measured, noise=0.04)
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
        got = smooth(lambda: Gaussian(jerk=1e-3), path.times, path.measured, noise=0.04)
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
        got = smooth(lambda: Gaussian(jerk=1e-4), times, measured, noise=0.01)
        assert got is not None
        assert all(math.isfinite(v) for v in got.value)

    def test_a_series_too_short_to_smooth_returns_nothing(self):
        from till_infinity.structures.statespace import smooth

        assert smooth(lambda: Gaussian(jerk=1e-3), [0.0], [1.0], noise=0.01) is None
        assert smooth(lambda: Gaussian(jerk=1e-3), [], [], noise=0.01) is None

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
        mine = smooth(lambda: Gaussian(jerk=truth), path.times, path.measured, noise=noise)
        assert mine is not None

        for name, column, got in (
            ("value", 0, mine.value),
            ("rate", 1, mine.rate),
            ("accel", 2, mine.component("accel")),
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

            def run(jerk: float, path=path) -> float:
                # `path` bound as a default: a closure over the loop variable is
                # the late-binding trap, and ruff is right to refuse it.
                got = smooth(lambda: Gaussian(jerk=jerk), path.times, path.measured, noise=noise)
                return rmse(got.value, path.truth)

            at_truth = run(truth)
            best_wrong = min(run(truth / 3), run(truth * 3))
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
        got = smooth(lambda: Gaussian(jerk=truth), path.times, path.measured, noise=noise)
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
        got = smooth(lambda: Gaussian(jerk=jerk), times, meas, noise=noise)
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

    def test_the_matrix_inverse_matches_numpy_at_both_dimensions(self):
        """The smoother's gain divides by this. Gauss-Jordan with partial
        pivoting, general in the dimension because `linear` carries three states
        and `reverting` two - it replaced a 3x3 cofactor expansion that could
        only ever serve one of them."""
        np = pytest.importorskip("numpy")
        from till_infinity.structures.statespace.smoothing import _inverse

        rng = np.random.default_rng(31)
        for size in (2, 3):
            for _ in range(40):
                root = rng.normal(size=(size, size))
                full = root @ root.T + np.eye(size) * 0.4  # symmetric, positive definite
                got = _inverse(full.tolist())
                assert got is not None
                want = np.linalg.inv(full)
                for r in range(size):
                    for c in range(size):
                        assert got[r][c] == pytest.approx(float(want[r, c]), rel=1e-9, abs=1e-12), (
                            size,
                            r,
                            c,
                        )

        # And it inverts an asymmetric matrix too, which the cofactor version
        # could not be asked: the gain's argument is symmetric, but a general
        # solve should not quietly depend on that.
        a = [[1.0, 2.0, 3.0], [0.0, 1.0, 4.0], [5.0, 6.0, 0.0]]
        got = _inverse(a)
        assert got is not None
        product = np.array(a) @ np.array(got)
        assert np.allclose(product, np.eye(3), atol=1e-12)

    def test_a_singular_matrix_is_refused_rather_than_inverted(self):
        from till_infinity.structures.statespace.smoothing import _inverse

        # Rank one: every row a multiple of the first.
        assert _inverse([[1.0, 1.0], [1.0, 1.0]]) is None
        assert _inverse([[1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [3.0, 3.0, 3.0]]) is None
        assert _inverse([[0.0, 0.0], [0.0, 0.0]]) is None

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

    def test_the_smoother_takes_a_factory_and_names_no_member(self):
        """It used to build a `Gaussian` itself and therefore could not smooth
        the member that wins. It takes a factory now and knows no member's
        parameters - a signature mentioning `jerk` or `theta` would mean it had
        picked one again."""
        import inspect

        from till_infinity.structures.statespace import smoothing

        parameters = inspect.signature(smoothing.smooth).parameters
        assert "build" in parameters
        assert "jerk" not in parameters
        assert "theta" not in parameters
        assert "sigma2" not in parameters

    def test_it_smooths_both_members_through_one_recursion(self):
        """Two states and three, from the same code - and `linear`'s answer is
        unchanged, which is what says the generalisation cost nothing."""
        from till_infinity.structures.statespace import (
            Gaussian,
            Reverting,
            hourly,
            simulate,
            smooth,
        )

        truth, noise = 1e-3, 0.09
        path = simulate(hourly(400), jerk=truth, noise=noise, seed=5)

        def rmse(got):
            return math.sqrt(
                sum((a - b) ** 2 for a, b in zip(got, path.truth, strict=True)) / len(path)
            )

        three = smooth(lambda: Gaussian(jerk=truth), path.times, path.measured, noise=noise)
        two = smooth(
            lambda: Reverting(sigma2=0.3, theta=0.1), path.times, path.measured, noise=noise
        )
        assert three is not None
        assert two is not None
        assert three.names == ("value", "rate", "accel")
        assert two.names == ("value", "rate")
        for got in (three, two):
            assert rmse(got.value) < rmse(got.filtered), got.names
            assert all(s <= f + 1e-9 for s, f in zip(got.sd, got.filtered_sd, strict=True))

    def test_asking_a_two_state_member_for_an_acceleration_fails(self):
        """`reverting` has no third state, so a zero would read like a
        measurement. `KeyError`, naming what it does have."""
        from till_infinity.structures.statespace import Reverting, hourly, simulate, smooth

        path = simulate(hourly(60), jerk=1e-3, noise=0.09, seed=2)
        got = smooth(
            lambda: Reverting(sigma2=0.3, theta=0.1), path.times, path.measured, noise=0.09
        )
        assert got is not None
        assert len(got.component("rate")) == len(got)
        with pytest.raises(KeyError, match="accel"):
            got.component("accel")

    def test_a_member_that_cannot_state_its_transition_declines_to_be_smoothed(self):
        """How a future member opts out, rather than being half-smoothed."""
        from till_infinity.structures.statespace import smooth

        class Opaque:
            at = None
            seen = 0

            def predict(self, when):
                pass

            def update(self, measured, noise, when=None):
                return 0.0

        assert smooth(Opaque, [0.0, HOUR, 2 * HOUR], [1.0, 1.0, 1.0], noise=0.01) is None

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


class TestSelective:
    """S6, the neural family member - Mamba's recurrence without its training."""

    def test_theorem_one_holds_exactly_and_only_where_it_claims_to(self):
        """`1 - exp(-softplus(z)) == sigmoid(z)`, which is why a one-state
        selective SSM is an exponential average with an input-dependent decay.

        Pinned because that identity is the one piece of the paper worth reusing
        even if the member loses its comparison, and because an earlier
        docstring here claimed it held at the default `drift`, where it does
        not."""
        from till_infinity.structures.statespace.selective import (
            INERT,
            Selective,
            sigmoid,
        )

        for z in (-8.0, -3.0, -0.5, 0.0, 0.5, 2.0, 7.0, 12.0):
            gate = Selective(drift=0.0, scale=1.0).gate(1.0, z)
            assert gate == pytest.approx(sigmoid(z), abs=1e-15), z

        # And not at the null's `drift`, where `delta` is the elapsed hours.
        assert Selective(drift=INERT, scale=1.0).gate(1.0, 0.0) != pytest.approx(
            sigmoid(0.0), abs=0.01
        )

    def test_the_null_is_nested_so_a_loss_is_about_selection(self):
        """`scale = 0` stops `delta` depending on the input, which makes the
        member time-invariant. Without that the comparison against `reverting`
        would confound selection with every other difference."""
        from till_infinity.structures.statespace.selective import Selective

        flat = Selective(scale=0.0)
        # The same elapsed time retains the same fraction whatever the reading.
        assert flat.retention(0.5, z=-5.0) == flat.retention(0.5, z=5.0)

        live = Selective(scale=1.0)
        assert live.retention(0.5, z=-5.0) != live.retention(0.5, z=5.0)

    def test_delta_at_inert_is_exactly_the_elapsed_hours(self):
        """`softplus(INERT) == 1`, so the null advances one hour of `delta` per
        hour of clock - the property that makes it the *nested* null rather than
        merely a nearby one."""
        from till_infinity.structures.statespace.selective import INERT, softplus

        assert softplus(INERT) == pytest.approx(1.0, abs=1e-15)

    def test_a_surprising_reading_opens_the_gate(self):
        """Selection, in the direction the paper describes: a large `delta`
        resets the state onto the current input, a small one keeps the state and
        ignores it."""
        from till_infinity.structures.statespace.selective import Selective

        calm = Selective(drift=0.0, scale=1.0).gate(1.0, 0.0)
        surprised = Selective(drift=0.0, scale=1.0).gate(1.0, 4.0)
        ignored = Selective(drift=0.0, scale=1.0).gate(1.0, -4.0)
        assert ignored < calm < surprised
        assert surprised > 0.98
        assert ignored < 0.02

    def test_softplus_and_sigmoid_survive_their_tails(self):
        """Both are written in halves because the naive forms overflow, and an
        overflow here turns a large `delta` into an exception rather than into a
        reset state."""
        from till_infinity.structures.statespace.selective import sigmoid, softplus

        assert softplus(800.0) == pytest.approx(800.0)
        assert softplus(-800.0) == pytest.approx(0.0)
        assert sigmoid(800.0) == pytest.approx(1.0)
        assert sigmoid(-800.0) == pytest.approx(0.0)

    def test_it_tracks_a_level_and_reports_a_rate_it_does_not_store(self):
        """`h` holds coefficients of the transition's basis, not named
        quantities, so `value` and `rate` are read out of it rather than being
        slots in it."""
        from till_infinity.structures.statespace.selective import SIZE, Selective

        f = Selective(scale=1.0)
        for i in range(60):
            t = i * 900.0
            f.predict(t)
            f.update(100.0, 0.4, t)
        assert f.seen == 60
        assert f.value == pytest.approx(100.0, rel=0.05)
        assert len(f.state()) == SIZE
        assert isinstance(f.rate, float)

    def test_it_states_its_transition_but_cannot_be_smoothed(self):
        """A member can state `F` and still not be smoothable. The missing piece
        is the covariance: a selective SSM is a deterministic map, so there is
        no posterior to run backwards, and `smooth` returning None is a true
        statement about the member."""
        from till_infinity.structures.statespace.selective import SIZE, Selective
        from till_infinity.structures.statespace.smoothing import smooth

        f = Selective()
        rows = f.transition(0.25)
        assert len(rows) == SIZE
        # Diagonal, because `A` is.
        assert all(rows[i][j] == 0.0 for i in range(SIZE) for j in range(SIZE) if i != j)
        assert not hasattr(f, "covariance")

        times = tuple(i * 900.0 for i in range(12))
        measured = tuple(100.0 + 0.1 * i for i in range(12))
        assert smooth(lambda: Selective(scale=1.0), times, measured, noise=0.4) is None

    def test_it_is_in_the_family_and_satisfies_the_protocol(self):
        """The registry is what a harness reaches for, so a member that is not
        in it is a member nothing can score."""
        from till_infinity.structures.statespace.family import Filter, members
        from till_infinity.structures.statespace.selective import Selective

        assert members()["selective"] is Selective
        assert isinstance(Selective(), Filter)

    def test_the_score_is_the_one_reverting_is_scored_on(self):
        """A deterministic map has no likelihood of its own; `noise` as a fitted
        one-step spread is what buys comparability against the null."""
        from till_infinity.structures.statespace.selective import Selective

        f = Selective(noise=1.0)
        exact = f.predictive(f.value)
        off = f.predictive(f.value + 2.0)
        assert exact > off
        # A Gaussian density, so the gap is the usual -z^2/2.
        assert exact - off == pytest.approx(2.0, abs=1e-9)


class TestOutputEquation:
    """`y = C h`. The observable half, written down rather than implied."""

    def test_every_member_reports_an_output_that_tracks_its_value(self):
        """`value` and `y[0]` are the same quantity reached two ways, so they
        have to agree after a run or one of them is lying.

        They are kept separate because `value` is a convenience and `C h` is the
        model: for `linear` and `reverting` the observed quantity happens to be
        the first state slot, and for `selective` there is no such slot at all -
        its state holds basis coefficients and its output is their weighted sum.
        """
        from till_infinity.structures.statespace.family import members

        for name, cls in members().items():
            engine = cls()
            for i in range(40):
                when = i * 900.0
                engine.predict(when)
                engine.update(100.0 + 0.01 * i, 0.4, when)
            y = engine.output()
            assert len(y) == len(engine.OUTPUTS), name
            assert y[0] == pytest.approx(engine.value, rel=1e-9, abs=1e-9), name

    def test_c_has_a_column_for_every_state(self):
        """A `C` that does not line up with the state is the one bug this
        abstraction can introduce, and it would be silent: `zip` without
        `strict` would truncate and report a plausible number."""
        from till_infinity.structures.statespace.family import members

        for name, cls in members().items():
            engine = cls()
            width = len(engine.state())
            rows = engine.observation()
            assert rows, name
            for row in rows:
                assert len(row) == width, f"{name}: C row of {len(row)} against {width} states"

    def test_selectives_output_is_not_a_state_slot(self):
        """The case that makes the distinction worth having.

        **Under a constant reading this is invisible**, which is worth recording
        because the first version of this test asserted it there and failed:
        every state is an exponential average of the same input, so they all
        converge to it and each one equals the output. The states separate only
        while the input is moving, which is where a slow slot and a fast slot
        mean different things - and where pointing at one of them as "the value"
        would be a choice rather than a reading.
        """
        from till_infinity.structures.statespace.selective import SIZE, Selective

        engine = Selective(scale=1.0)
        for i in range(40):
            when = i * 900.0
            engine.update(100.0 + 3.0 * i, 0.4, when)  # a ramp, so the rates separate

        rows = engine.observation()
        assert rows[0] == tuple([1.0 / SIZE] * SIZE)

        state = engine.state()
        spread = max(state) - min(state)
        # 0.425 as measured: the eigenvalues are -1 to -4 against a 0.25h step,
        # so every state is a fast average and they separate by little. The
        # threshold is deliberately well under that rather than near it - this
        # test is about the states being distinct, not about how distinct.
        assert spread > 0.1, f"states should separate under a ramp, got {state}"

        # The output is their weighted sum and equals no single one of them.
        y = engine.output()[0]
        assert y == pytest.approx(sum(state) / SIZE)
        assert all(abs(h - y) > 1e-9 for h in state), state


class TestTheFourQuantities:
    """Prediction, uncertainty, log density and existence - reachable from
    outside, on every member, without knowing which member it is."""

    def test_all_four_are_on_the_contract(self):
        """Asked directly - can they all be accessed from outside - and the
        answer was no until this was written: the three Kalman members answered
        `loglike`, `last_standardised` and `existence` and `selective` answered
        none of them, naming its density `predictive` instead. Same concept,
        different word, which is how two members stop being comparable."""
        from till_infinity.structures.statespace.family import Filter, members

        for name, cls in members().items():
            engine = cls()
            assert isinstance(engine, Filter), name
            # the prediction
            assert isinstance(engine.value, float), name
            assert isinstance(engine.output(), tuple), name
            assert isinstance(engine.at_time(900.0), float), name
            # the uncertainty
            assert isinstance(engine.sd, float), name
            low, high = engine.band(900.0)
            assert low <= high, name
            # the log density
            assert isinstance(engine.loglike, float), name
            assert isinstance(engine.last_standardised, float), name
            # the probability
            assert 0.0 <= engine.existence <= 1.0, name

    def test_the_covariance_is_the_one_optional_capability(self):
        """`selective` has no posterior to report, so it does not pretend to.
        A caller must ask, and `smooth` is the caller that does.

        **It is now the only member without one.** `swarm` carries an ensemble
        and reports its sample covariance, which is the point of that member:
        the same recurrence with an inferred spread instead of an asserted one.
        So this asserts the exception rather than a list, and a new member that
        quietly cannot answer will fail here.
        """
        from till_infinity.structures.statespace.family import members

        without = {n for n, c in members().items() if not hasattr(c(), "covariance")}
        assert without == {"selective"}

    def test_existence_decays_on_time_alone_and_never_exceeds_one(self):
        """The one genuine probability here. An absence of evidence is caused by
        time passing, so `predict` alone has to move it."""
        from till_infinity.structures.statespace.family import members
        from till_infinity.structures.statespace.linear import EXISTENCE_HALF_LIFE_HOURS

        half_life = EXISTENCE_HALF_LIFE_HOURS * 3600.0
        for name, cls in members().items():
            engine = cls()
            engine.update(100.0, 0.4, 0.0)
            assert engine.existence == pytest.approx(1.0), name
            engine.predict(half_life)
            assert engine.existence == pytest.approx(0.5, rel=1e-6), name
            # And folding a reading back in cannot push belief past certainty.
            for i in range(20):
                engine.update(100.0, 0.4, half_life + (i + 1) * 900.0)
            assert engine.existence <= 1.0, name

    def test_loglike_is_a_density_and_accumulates_negatively_here(self):
        """Not a probability: any sign, and summed over the run. It is the
        quantity every comparison in this package is made on."""
        from till_infinity.structures.statespace.family import members

        for name, cls in members().items():
            engine = cls()
            assert engine.loglike == 0.0, name
            for i in range(40):
                when = i * 900.0
                engine.predict(when)
                engine.update(100.0 + 0.05 * i, 0.4, when)
            assert math.isfinite(engine.loglike), name
            assert engine.loglike < 0.0, name

    def test_selective_does_not_advance_its_state_twice(self):
        """The bug a protocol audit found. `predict` used to decay `h` toward
        zero *and* `update` applied the same decay from the last reading, so
        every step advanced twice: a level held near 101 was tracked to 65.8
        with a standardised innovation of 164. Both arms were individually
        defensible, which is why only seeing them together caught it."""
        from till_infinity.structures.statespace.selective import Selective

        engine = Selective(scale=1.0)
        for i in range(40):
            when = i * 900.0
            engine.predict(when)
            engine.update(500.0, 0.4, when)
        assert engine.value == pytest.approx(500.0, rel=0.01)
        assert abs(engine.last_standardised) < 1.0

        # And `predict` on its own leaves the state where it was.
        before = engine.state()
        engine.predict(40 * 900.0 + 7200.0)
        assert engine.state() == before


class TestAgainstTheReferenceImplementation:
    """Checked against `state-spaces/mamba` rather than against the paper.

    The paper says what the model is; the implementation says what the authors
    actually ran, and the two differ in one place that matters here.
    """

    def test_the_eigenvalues_are_the_references_s4d_real(self):
        """`mamba_simple.py` builds `A = arange(1, d_state + 1)`, stores
        `A_log = log(A)` and uses `A = -exp(A_log)` in forward - so the
        eigenvalues are `-1, -2, ... -N`. This member's are too, and that is now
        checked against the code and not inferred from a table in the paper."""
        from till_infinity.structures.statespace.selective import SIZE, Selective

        assert Selective.eigenvalues() == tuple(-(n + 1.0) for n in range(SIZE))
        assert all(a < 0.0 for a in Selective.eigenvalues())

    def test_the_bias_trick_hits_any_target_step(self):
        """The reference sets its `dt` bias to `dt + log(-expm1(-dt))` so that
        `softplus(bias)` recovers a sampled `dt`. `INERT` is that at a target of
        one, which is what makes the null exactly "one hour of `delta` per hour
        of clock" rather than approximately it."""
        from till_infinity.structures.statespace.selective import (
            INERT,
            REFERENCE_DELTA,
            inverse_softplus,
            softplus,
        )

        for target in (1e-4, 0.001, 0.01, 0.1, 1.0, 5.0, 50.0):
            assert softplus(inverse_softplus(target)) == pytest.approx(target, rel=1e-12)

        assert pytest.approx(inverse_softplus(1.0)) == INERT
        assert pytest.approx(math.log(math.e - 1.0)) == INERT
        low, high = REFERENCE_DELTA
        assert low < high

    def test_the_entry_weight_is_exact_zoh_only_at_minus_one(self):
        """The correction the implementation forced. Exact zero-order hold is
        `(e^{dA} - 1) / A`; this member uses `1 - e^{dA}`, which coincides at
        `A = -1` and is `|A|` times larger elsewhere. The reference uses neither
        - it uses `delta * B`, Euler - so "ZOH, as Mamba uses" was wrong twice
        over, and this test is here so the claim cannot drift back."""
        from till_infinity.structures.statespace.selective import Selective

        step = 0.5
        engine = Selective(drift=0.0, scale=0.0)
        # `scale = 0` and `drift = 0` make softplus(0) = log(2), so delta is
        # that times the hours; ask for the retention directly instead.
        for a in Selective.eigenvalues():
            mine = 1.0 - math.exp(a * step)
            exact_zoh = (math.exp(a * step) - 1.0) / a
            if a == -1.0:
                assert mine == pytest.approx(exact_zoh)
            else:
                assert mine == pytest.approx(abs(a) * exact_zoh)
                assert mine > exact_zoh

        # And the normalisation is what the read-out depends on: weights summing
        # to one mean every state converges to the reading.
        engine = Selective(scale=0.0)
        for i in range(400):
            engine.update(77.0, 0.4, i * 900.0)
        assert all(h == pytest.approx(77.0, rel=1e-6) for h in engine.state())
        assert engine.output()[0] == pytest.approx(77.0, rel=1e-6)


class TestSwarm:
    """The anchored particle member: `selective`'s two trade-offs, fixed elsewhere."""

    def test_the_spectrum_has_an_anchor(self):
        """`(0, -1, -2, -3)`. The zero is the whole design: one component does
        not decay, so it holds the level while the others track movement."""
        from till_infinity.structures.statespace.swarm import SIZE, Swarm

        eigen = Swarm.eigenvalues()
        assert len(eigen) == SIZE
        assert eigen[0] == 0.0
        assert all(a < 0.0 for a in eigen[1:])
        # The anchor's retention is exactly one, at any horizon.
        engine = Swarm()
        for hours in (0.0, 1.0, 100.0):
            assert engine.retention(hours)[0] == 1.0

    def test_extrapolation_goes_to_the_anchor_not_to_zero(self):
        """`selective`'s worst trade-off, and the reason this member exists.

        There the state summarises readings that arrived, so with none it
        decays to nothing - useless for a level, whose character is sitting
        still. Here the deviations decay and the anchor stays.
        """
        from till_infinity.structures.statespace.selective import Selective
        from till_infinity.structures.statespace.swarm import Swarm

        level = 500.0
        swarm = Swarm(wander=0.1)
        selective = Selective()
        for i in range(60):
            when = i * 900.0
            for engine in (swarm, selective):
                engine.predict(when)
                engine.update(level, 0.4, when)

        far = 60 * 900.0 + 72 * 3600.0
        assert swarm.at_time(far) == pytest.approx(level, rel=0.02)
        assert swarm.at_time(far) == pytest.approx(swarm.anchor, rel=1e-6)
        # And the member it was written to improve on does decay away.
        assert abs(selective.at_time(far)) < 0.5 * level

    def test_the_band_widens_because_the_anchor_wanders(self):
        """`selective.sd` is a fitted parameter, so its band cannot widen in a
        gap. This one is the ensemble's spread plus the anchor's own process
        noise over the interval - inferred, not asserted.

        The first version of this member got it wrong in the same way it was
        written to fix: `band` read the *current* spread at every horizon, so
        +48h was exactly as narrow as now.
        """
        from till_infinity.structures.statespace.swarm import Swarm

        engine = Swarm(wander=0.3)
        for i in range(60):
            when = i * 900.0
            engine.predict(when)
            engine.update(100.0, 0.4, when)

        now = 59 * 900.0
        widths = []
        for ahead in (0.0, 1.0, 6.0, 48.0):
            low, high = engine.band(now + ahead * 3600.0)
            widths.append(high - low)
        assert widths == sorted(widths), widths
        assert widths[-1] > 4.0 * widths[0]

    def test_it_reports_a_posterior_and_can_be_smoothed(self):
        """The capability `selective` lacks. A covariance from the ensemble
        means `smooth` has what it needs, where that member returns None."""
        from till_infinity.structures.statespace.smoothing import smooth
        from till_infinity.structures.statespace.swarm import SIZE, Swarm

        engine = Swarm()
        for i in range(40):
            when = i * 900.0
            engine.predict(when)
            engine.update(100.0 + 0.1 * i, 0.4, when)

        cov = engine.covariance()
        assert len(cov) == SIZE
        assert all(len(row) == SIZE for row in cov)
        # Symmetric, and the diagonal is non-negative - it is a covariance.
        for i in range(SIZE):
            assert cov[i][i] >= 0.0
            for j in range(SIZE):
                assert cov[i][j] == pytest.approx(cov[j][i], abs=1e-12)

        times = tuple(i * 900.0 for i in range(20))
        measured = tuple(100.0 + 0.1 * i for i in range(20))
        assert smooth(Swarm, times, measured, noise=0.4) is not None

    def test_the_ensemble_does_not_collapse(self):
        """A particle filter whose weights concentrate on one particle has
        silently become a point estimate, and its `sd` has stopped meaning
        anything. Resampling is what prevents it, and `effective` is how you
        would know."""
        from till_infinity.structures.statespace.swarm import COUNT, Swarm

        engine = Swarm(wander=0.2)
        for i in range(200):
            when = i * 900.0
            engine.predict(when)
            engine.update(100.0 + 0.05 * i, 0.4, when)
        assert engine.effective() > 0.1 * COUNT, engine.effective()
        assert engine.resampled > 0, "nothing resampled, so the trigger never fired"
        assert engine.sd > 0.0

    def test_it_is_in_the_family_and_satisfies_the_protocol(self):
        from till_infinity.structures.statespace.family import Filter, members
        from till_infinity.structures.statespace.swarm import Swarm

        assert members()["swarm"] is Swarm
        engine = Swarm()
        assert isinstance(engine, Filter)
        assert 0.0 <= engine.existence <= 1.0

    def test_a_run_is_reproducible(self):
        """A particle filter whose answer moves between runs cannot be scored
        against a null, so the seed is part of the member."""
        from till_infinity.structures.statespace.swarm import Swarm

        def run():
            engine = Swarm(wander=0.2)
            for i in range(50):
                when = i * 900.0
                engine.predict(when)
                engine.update(100.0 + 0.03 * i, 0.4, when)
            return engine.value, engine.sd, engine.loglike

        assert run() == run()


class TestSwarmLikelihood:
    """The score has to be on the same scale as the Kalman members' or the
    comparison between them is meaningless."""

    def test_one_point_ensemble_reproduces_the_plain_gaussian(self):
        """A non-circular check, and the one that caught a real bug.

        With a negligible seed spread every particle holds the same state, so
        the ensemble's weighted mean predictive density **is** the ordinary
        Gaussian density of the reading. Anything else means the log-sum-exp is
        wrong - and it was: the stabilising `-= logw.max()` shift was never
        added back, so every step's score was too high by `0.5*min(error**2)`.
        """
        from till_infinity.structures.statespace.swarm import Swarm

        spread = 0.5
        variance = spread * spread  # `noise` is a variance, per the contract
        engine = Swarm(noise=1e-9, wander=0.0, drift=0.0, scale=0.0)
        engine.update(100.0, variance, 0.0)  # seeds, scores nothing
        assert engine.loglike == 0.0

        # One further reading, offset so the density is not at its peak.
        engine.update(101.0, variance, 3600.0)
        expected = (
            -0.5 * ((101.0 - 100.0) / spread) ** 2
            - 0.5 * math.log(2.0 * math.pi)
            - math.log(spread)
        )
        assert engine.loglike == pytest.approx(expected, abs=1e-6)


class TestExistenceMeansOneThing:
    """`existence` has two halves and every member must implement both."""

    def test_time_removes_belief_and_readings_return_it(self):
        """The rule, and the test that found it missing.

        `existence` is not a function of elapsed time alone - that claim was
        made and it was wrong. Time decays it in `predict`; **a reading pulls
        it back toward one** in `update`, because a level being touched is a
        level that still exists. `swarm` implemented only the decay, and over
        6,000 bars it finished at 0.045 against every other member's 0.998.

        This is the shape of test the README now asks for whenever an accessor
        is added to `Filter`: that it means the same thing on every member,
        not merely that each one answers.
        """
        from till_infinity.structures.statespace.family import members
        from till_infinity.structures.statespace.linear import EXISTENCE_HALF_LIFE_HOURS

        gap = EXISTENCE_HALF_LIFE_HOURS * 3600.0
        for name, cls in members().items():
            engine = cls()
            engine.update(100.0, 0.4, 0.0)

            # Time alone takes it down.
            engine.predict(gap)
            assert engine.existence == pytest.approx(0.5, rel=1e-6), name

            # A reading brings it back up, and cannot push past certainty.
            engine.update(100.0, 0.4, gap)
            assert engine.existence > 0.5, name
            assert engine.existence <= 1.0, name

    def test_a_long_run_of_readings_keeps_every_member_near_certain(self):
        """The symptom that exposed the bug, as a regression test: a level
        touched every fifteen minutes for days is not a level we have stopped
        believing in."""
        from till_infinity.structures.statespace.family import members

        for name, cls in members().items():
            engine = cls()
            for i in range(400):
                when = i * 900.0
                engine.predict(when)
                engine.update(100.0, 0.4, when)
            assert engine.existence > 0.9, f"{name}: {engine.existence}"


class TestFixedLagSmoothing:
    """`lagged` - the smoother a live desk could run, where `smooth` cannot."""

    def test_it_converges_on_the_whole_series_smoother(self):
        """The only honest check of it.

        Fixed-lag smoothing conditions on `lag` future measurements where
        `smooth` conditions on all of them, so the two are **not** equal at a
        given point - that is the definition rather than a shortfall. What must
        hold is that the gap closes as the lag grows, and it does: 0.337 at
        lag 1 down to 0.00064 at lag 100 on this series.
        """
        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.smoothing import lagged, smooth

        times = tuple(i * 900.0 for i in range(120))
        values = tuple(100.0 + 0.05 * i + (1.5 if i % 23 == 0 else 0.0) for i in range(120))
        build = lambda: Gaussian(jerk=1e-4)  # noqa: E731

        full = smooth(build, times, values, noise=0.16)
        assert full is not None

        gaps = []
        for lag in (1, 3, 10, 30, 100):
            got = lagged(build, times, values, noise=0.16, lag=lag)
            assert got is not None
            by_time = {round(row.when): row.value for row in got}
            gaps.append(
                max(
                    abs(by_time[round(t)] - full.states[i][0])
                    for i, t in enumerate(times)
                    if round(t) in by_time
                )
            )
        # Monotone, and tiny by the time the lag covers the series.
        assert gaps == sorted(gaps, reverse=True), gaps
        assert gaps[-1] < 1e-3, gaps

    def test_every_measurement_gets_an_estimate_with_its_own_delay(self):
        """Output aligned to input, and `delay` says how late each one is.

        The first `lag` points have less future to use and the last has none at
        all, so they come back with the delay that was actually available
        rather than being dropped - a caller zipping the two would otherwise
        silently misalign.
        """
        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.smoothing import lagged

        times = tuple(i * 900.0 for i in range(60))
        values = tuple(100.0 + 0.1 * i for i in range(60))
        got = lagged(lambda: Gaussian(jerk=1e-4), times, values, noise=0.16, lag=8)
        assert got is not None
        assert len(got) == len(times)
        assert [row.when for row in got] == sorted(row.when for row in got)
        assert max(row.delay for row in got) == 8
        assert min(row.delay for row in got) == 0

    def test_the_revision_is_what_hindsight_moved(self):
        """`revision` is the quantity worth watching: a revision much larger
        than the filter's own standard deviation means the filter was
        confidently wrong, which is a statement about the process noise."""
        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.smoothing import lagged

        times = tuple(i * 900.0 for i in range(80))
        # A level that steps, so hindsight has something to correct.
        values = tuple(100.0 if i < 40 else 103.0 for i in range(80))
        got = lagged(lambda: Gaussian(jerk=1e-4), times, values, noise=0.16, lag=10)
        assert got is not None
        for row in got:
            assert row.revision == pytest.approx(row.value - row.filtered)
        # The step is where hindsight helps most.
        worst = max(got, key=lambda r: abs(r.revision))
        assert 30 * 900.0 <= worst.when <= 50 * 900.0, worst.when

    def test_a_member_that_cannot_state_its_transition_declines(self):
        """Same contract as `smooth`: None rather than a half-smoothed answer."""
        from till_infinity.structures.statespace.selective import Selective
        from till_infinity.structures.statespace.smoothing import lagged

        times = tuple(i * 900.0 for i in range(30))
        values = tuple(100.0 + 0.1 * i for i in range(30))
        # `selective` has no covariance, so it cannot be smoothed either way.
        assert lagged(Selective, times, values, noise=0.16, lag=5) is None


class TestInputsAreMeasuredInTime:
    """`inputs.py` - the `u` half of the channel `I1` says is missing."""

    def test_a_window_is_the_same_horizon_on_every_timeframe(self):
        """The reason windows are hours and not bars.

        "200 bars" is a horizon times a timeframe - ten hours at 3m, eight
        months at 1d - so a feature defined that way means something different
        on every series. One week has to be one week.
        """
        from till_infinity.structures.statespace.inputs import WEEKS, bar_hours

        week = WEEKS[0]
        got = {}
        for minutes, label in ((3, "3m"), (15, "15m"), (60, "1h"), (1440, "1d")):
            times = [i * minutes * 60.0 for i in range(3000)]
            hours = bar_hours(times)
            got[label] = week.bars(hours)
            # The bar count differs; the horizon it covers does not.
            assert got[label] * hours == pytest.approx(week.hours, rel=0.01), label
        assert got["3m"] > got["15m"] > got["1h"] > got["1d"]
        # A continuous clock trades all seven days, so a week is seven daily
        # bars. The next test is the five-day case.
        assert got["1d"] == 7

    def test_a_week_is_five_days_on_fx_and_seven_on_crypto(self):
        """The calendar, inferred rather than hardcoded.

        The first version made a week five days flat, which is right for FX and
        **wrong for crypto and the Deriv synthetics, which trade all seven** -
        it silently shortened every crypto window by two sevenths. So the
        window is calendar hours and `coverage` converts, which gets both right
        without a per-symbol table.

        Measured on the real files: EURUSD and GBPUSD come back at 0.711,
        against 5/7 = 0.714, and Volatility_75 and Volatility_25 at exactly
        1.000.
        """
        from till_infinity.structures.statespace.inputs import (
            WEEKS,
            bar_hours,
            coverage,
        )

        # An FX-shaped clock: 15m bars that stop for 48 hours every five days.
        fx: list[float] = []
        t = 0.0
        for _week in range(12):
            for _bar in range(5 * 24 * 4):
                fx.append(t)
                t += 900.0
            t += 48 * 3600.0
        crypto = [i * 900.0 for i in range(len(fx))]

        fx_cover = coverage(fx)
        crypto_cover = coverage(crypto)
        assert 0.68 < fx_cover < 0.76, fx_cover
        assert crypto_cover == pytest.approx(1.0)

        week = WEEKS[0]
        fx_bars = week.bars(bar_hours(fx), fx_cover)
        crypto_bars = week.bars(bar_hours(crypto), crypto_cover)
        # Seven days of 15m bars is 672; five is 480.
        assert crypto_bars == 672
        assert 440 < fx_bars < 510, fx_bars
        assert crypto_bars > fx_bars

    def test_it_cannot_see_the_bar_it_is_computed_for(self):
        """The off-by-one that decides whether this leaks.

        A window including the current bar leaks the present into a prediction
        of the present, and the cross-resolution test has already shown what
        that produces: `t = +20.8` on five symbols, one of them generated.
        """
        from till_infinity.structures.statespace.inputs import WEEKS, Features

        times = [i * 900.0 for i in range(500)]
        closes = [100.0 + i * 0.01 for i in range(500)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        highs[300] = 999.0  # one unmistakable spike

        # Windows passed explicitly: the default is now whatever the series
        # resolves, and a 500-bar 15m series does not resolve a week.
        features = Features(times, highs, lows, closes, windows=WEEKS)
        assert features.at(300).of("high_1w") < 500.0, "bar 300 saw itself"
        assert features.at(301).of("high_1w") == 999.0, "bar 301 should see it"

    def test_position_is_unit_free_so_it_travels_across_symbols(self):
        """A raw high is in the instrument's units and a position is not, which
        is what lets xauusd and eurusd sit in one table."""
        from till_infinity.structures.statespace.inputs import WEEKS, Features

        times = [i * 900.0 for i in range(600)]
        for scale in (1.0, 1000.0):
            closes = [scale * (1.0 + 0.0001 * i) for i in range(600)]
            highs = [c * 1.001 for c in closes]
            lows = [c * 0.999 for c in closes]
            built = Features(times, highs, lows, closes, windows=WEEKS)
            where = built.position(500, WEEKS[0])
            assert 0.0 <= where <= 1.0
            # Rising series: the last close sits near the top of its range.
            assert where > 0.8, scale

    def test_naming_the_components_rather_than_their_order(self):
        """`of()` by name, `KeyError` for anything else - the mistake
        `frozen.vector` exists to prevent one layer down."""
        from till_infinity.structures.statespace.inputs import WEEKS, Features

        times = [i * 900.0 for i in range(400)]
        closes = [100.0] * 400
        features = Features(times, closes, closes, closes, windows=WEEKS)
        got = features.at(300)
        assert len(got) == len(got.names)
        # Seven per window - high, low, rv, parkinson, slope, ema_slope,
        # ema_z - plus the two blends. `position` is a method rather than a
        # stored feature because it is a ratio of two that are stored, and
        # `gk` is absent because no opens were given.
        assert len(got) == 7 * len(WEEKS) + 2
        assert got.of("rv_4w") == 0.0  # a flat series has no realised vol
        assert got.of("parkinson_4w") == 0.0
        assert "har_parkinson" in got.names
        with pytest.raises(KeyError):
            got.of("not_a_feature")

    def test_time_since_an_event_is_hours_not_bars(self):
        """Same portability argument, and `inf` rather than a plausible number
        when the thing has never happened."""
        from till_infinity.structures.statespace.inputs import since

        flags = [i == 250 for i in range(500)]
        assert since(flags, 300, 0.25) == pytest.approx(12.5)
        assert since(flags, 300, 1.0) == pytest.approx(50.0)
        assert since([False] * 10, 5, 1.0) == math.inf


class TestChangepoint:
    """BOCPD: a posterior over how long the quantity has held."""

    def test_it_finds_a_step_and_says_so(self):
        """The event nothing else in the family detects.

        A level holds at 100 for sixty readings then jumps to 107. The run
        length should collapse and `changepoint` should fire on the reading it
        happens, not after a decay.
        """
        import random

        from till_infinity.structures.statespace.changepoint import Changepoint

        rng = random.Random(7)
        engine = Changepoint()
        before: list[float] = []
        during: list[float] = []
        runs: list[float] = []
        for i in range(100):
            truth = 100.0 if i < 60 else 107.0
            engine.predict(i * 900.0)
            engine.update(truth + rng.gauss(0.0, 0.3), 0.09, i * 900.0)
            if 40 <= i < 59:
                before.append(engine.changepoint)
            if 60 <= i <= 61:
                during.append(engine.changepoint)
            runs.append(engine.run_length)

        assert max(before) < 0.1, max(before)
        assert min(during) > 0.8, during
        # The run length collapses at the step and rebuilds afterwards.
        assert runs[59] > 40.0
        assert runs[60] < 5.0
        assert runs[95] > 20.0
        # And it finds the new level.
        assert engine.value == pytest.approx(107.0, abs=0.5)

    def test_the_mass_at_exactly_zero_is_useless_as_a_detector(self):
        """The pathology that made `changepoint` `P(r <= 2)` rather than `P(r = 0)`.

        Both arms of the recursion multiply by the **same** predictive, so the
        ratio of the change arm to the growth arm is `hazard / (1 - hazard)`
        whatever the data does - a reading that obliterates every existing run
        scales both arms down together. So `P(r = 0)` sits near the hazard rate
        before, during and after a change, which is the worst kind of defect:
        a detector that looks like it works and never fires.
        """
        import random

        from till_infinity.structures.statespace.changepoint import HAZARD, Changepoint

        rng = random.Random(11)
        engine = Changepoint()
        at_zero: list[float] = []
        for i in range(90):
            truth = 100.0 if i < 50 else 112.0
            engine.predict(i * 900.0)
            engine.update(truth + rng.gauss(0.0, 0.2), 0.04, i * 900.0)
            weights = engine._weights()
            at_zero.append(weights[0] if weights else 0.0)

        # Flat, and near the hazard rate, straight through a twelve-unit step.
        assert max(at_zero[40:70]) < 20.0 * HAZARD, max(at_zero[40:70])
        # While the published detector does fire on the same series.
        assert engine.run_length < 45.0

    def test_it_learns_the_variance_rather_than_being_told(self):
        """The one member that infers `R`. Every other is handed it."""
        import random

        from till_infinity.structures.statespace.changepoint import Changepoint

        rng = random.Random(3)
        quiet = Changepoint()
        loud = Changepoint()
        for i in range(200):
            when = i * 900.0
            quiet.predict(when)
            quiet.update(100.0 + rng.gauss(0.0, 0.1), 1.0, when)
            loud.predict(when)
            loud.update(100.0 + rng.gauss(0.0, 2.0), 1.0, when)
        # Both were told the same prior variance and reached different ones.
        assert loud.sd > 3.0 * quiet.sd, (quiet.sd, loud.sd)

    def test_it_refuses_to_report_a_rate(self):
        """A change-point model claims the quantity is piecewise constant, so a
        rate is not part of what it asserts - the same refusal
        `reverting.accel` makes about acceleration."""
        from till_infinity.structures.statespace.changepoint import Changepoint

        engine = Changepoint()
        for i in range(40):
            engine.predict(i * 900.0)
            engine.update(100.0 + 2.0 * i, 0.09, i * 900.0)  # a strong trend
        assert engine.rate == 0.0
        # And its forecast is flat, which is the same claim.
        now = 39 * 900.0
        assert engine.at_time(now + 100 * 3600.0) == pytest.approx(engine.value)

    def test_the_posterior_is_bounded_and_normalised(self):
        """Truncation folds the tail into the last kept run length rather than
        dropping it - a posterior that quietly sums to less than one is the
        kind of error that looks like a model result."""
        from till_infinity.structures.statespace.changepoint import MAX_RUN, Changepoint

        engine = Changepoint()
        for i in range(MAX_RUN + 200):
            engine.predict(i * 900.0)
            engine.update(100.0, 0.09, i * 900.0)
        weights = engine._weights()
        assert len(weights) <= MAX_RUN
        assert sum(weights) == pytest.approx(1.0)

    def test_it_is_in_the_family_and_satisfies_the_protocol(self):
        from till_infinity.structures.statespace.changepoint import Changepoint
        from till_infinity.structures.statespace.family import Filter, members

        assert members()["changepoint"] is Changepoint
        engine = Changepoint()
        assert isinstance(engine, Filter)
        engine.update(100.0, 0.09, 0.0)
        engine.predict(900.0)
        engine.update(100.5, 0.09, 900.0)
        assert math.isfinite(engine.loglike)
        assert engine.output() == (engine.value,)
        assert len(engine.observation()[0]) == len(engine.state())


class TestPaired:
    """A member watched by the FOCuS detector that `learning/focus.py` holds.

    **The detector's own tests live in `test_focus.py`** and check it against an
    `O(n^2)` brute-force reference, which is why this module uses it rather than
    carrying a second implementation. The second one collided with it in the
    persistence registry - both resolved to `focus.Focus` - and two CI tests
    caught that. What is tested here is the pairing.
    """

    def test_it_runs_both_directions_and_keeps_the_hulls_small(self):
        """Two one-sided detectors, and the cost claim made observable.

        `learning/focus.py` is one-sided on purpose, so a signed innovation
        needs both. And FOCuS is worth preferring over an `O(R)` posterior
        entirely because of the pruning: a hull that grew linearly would still
        give the right statistic while quietly being the naive algorithm.
        """
        import random

        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.paired import Paired

        rng = random.Random(13)
        pair = Paired(lambda: Gaussian(jerk=1e-4))
        sizes = []
        for i in range(4000):
            when = i * 900.0
            pair.predict(when)
            pair.update(100.0 + rng.gauss(0.0, 0.3), 0.09, when)
            if i in (100, 1000, 3999):
                sizes.append(pair.candidates)
        assert sizes[-1] < 4 * sizes[0], sizes
        assert sizes[-1] < 100, sizes
        assert pair.side in (-1, 0, 1)

    def test_pairing_helps_on_a_step_and_costs_nothing_without_one(self):
        """The null for `Paired` is the member alone, on the **same** series.

        The first version of this comparison drew fresh randoms for each run,
        which is not a comparison at all - the numbers below are on one series.
        """
        import random

        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.paired import Paired

        build = lambda: Gaussian(jerk=1e-4)  # noqa: E731

        rng = random.Random(9)
        stepped = [
            (i * 900.0, (100.0 if i < 150 else 112.0) + rng.gauss(0.0, 0.3)) for i in range(300)
        ]
        alone, paired = build(), Paired(build)
        for when, value in stepped:
            alone.predict(when)
            alone.update(value, 0.09, when)
            paired.predict(when)
            paired.update(value, 0.09, when)
        assert paired.detections == 1, paired.detections
        assert paired.loglike > alone.loglike + 500.0, (alone.loglike, paired.loglike)

        # And with nothing to find, the pair must be free rather than merely cheap.
        rng = random.Random(21)
        flat = [(i * 900.0, 100.0 + rng.gauss(0.0, 0.3)) for i in range(300)]
        alone, paired = build(), Paired(build)
        for when, value in flat:
            alone.predict(when)
            alone.update(value, 0.09, when)
            paired.predict(when)
            paired.update(value, 0.09, when)
        assert paired.detections == 0
        assert paired.loglike == pytest.approx(alone.loglike)

    def test_the_triggering_reading_is_not_thrown_away(self):
        """Reset happens *after* the member has used the reading that caused
        it. Resetting first would discard the evidence there was anything to
        reset for, and the rebuilt member would start from nothing."""
        import random

        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.paired import Paired

        rng = random.Random(4)
        paired = Paired(lambda: Gaussian(jerk=1e-4))
        for i in range(260):
            when = i * 900.0
            truth = 100.0 if i < 120 else 130.0
            paired.predict(when)
            paired.update(truth + rng.gauss(0.0, 0.2), 0.04, when)
        assert paired.detections >= 1
        # A member reset to nothing would sit near zero, not near the new level.
        assert paired.value == pytest.approx(130.0, abs=1.0)

    def test_it_reports_how_long_the_model_has_stood_in_hours(self):
        """Hours, not readings - the same portability argument as the windows
        and the hazard."""
        import random

        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.paired import Paired

        rng = random.Random(6)
        paired = Paired(lambda: Gaussian(jerk=1e-4))
        for i in range(100):
            when = i * 900.0
            paired.predict(when)
            paired.update(100.0 + rng.gauss(0.0, 0.2), 0.04, when)
        # 99 bars of 15 minutes is 24.75 hours, and nothing was detected.
        assert paired.detections == 0
        assert paired.hours_since_reset == pytest.approx(24.75, abs=0.3)

    def test_paired_satisfies_the_contract_it_delegates(self):
        """So it can be scored against the member alone without a special case."""
        from till_infinity.structures.statespace.family import Filter
        from till_infinity.structures.statespace.linear import Gaussian
        from till_infinity.structures.statespace.paired import Paired

        paired = Paired(lambda: Gaussian(jerk=1e-4))
        assert isinstance(paired, Filter)
        paired.predict(0.0)
        paired.update(100.0, 0.09, 0.0)
        paired.predict(900.0)
        paired.update(100.4, 0.09, 900.0)
        assert paired.output() == (paired.value,)
        assert len(paired.observation()[0]) == len(paired.state())
        assert math.isfinite(paired.at_time(1800.0))
        low, high = paired.band(1800.0)
        assert low <= high

    def test_every_series_resolves_the_rungs_it_can_and_no_others(self):
        """One ladder from seconds to weeks, and each series picks its own.

        A fixed set of windows cannot suit every timeframe - a week is 2,400
        bars at 3m and five at 1d, and a minute is a fifth of a bar at 5m. So
        the ladder spans the range and `resolvable` applies two bounds: at
        least two bars, or the "window" is just that bar's own high and low
        under a name claiming a horizon; and at most a quarter of the series,
        or there are too few independent observations of it - which is the
        mistake the slope-fade harness made before the overlap correction.
        """
        from till_infinity.structures.statespace.inputs import (
            LADDER,
            bar_hours,
            resolvable,
        )

        picked = {}
        for minutes, label in ((3, "3m"), (15, "15m"), (60, "1h"), (1440, "1d")):
            times = [i * minutes * 60.0 for i in range(6000)]
            got = resolvable(bar_hours(times), len(times))
            picked[label] = [w.label() for w in got]
            assert got, label
            # Every rung spans at least two bars and at most a quarter.
            for window in got:
                span = window.bars(bar_hours(times))
                assert 2 <= span <= 1500, (label, window.label(), span)

        # The fast series reach down the ladder and the slow ones reach up.
        assert "5m" in picked["3m"]
        assert "4w" not in picked["3m"]
        assert "3d" in picked["1d"]
        assert "30m" not in picked["1d"]
        assert len(picked["15m"]) > 3
        # And nothing resolves a rung shorter than its own bar.
        assert "10s" not in picked["3m"]
        assert all(len(v) <= len(LADDER) for v in picked.values())

    def test_bocpd_measures_freshness_and_its_memory_in_time(self):
        """`changepoint` and the truncation are durations, not counts.

        Both were counts and both were wrong for the same reason. "The run is
        at most two readings old" is half an hour at 15m and two days at 1d, and
        the class had already decided that was wrong when it added `run_hours`.
        And the cap of 300 components was justified as the point where the
        geometric tail is negligible - true at 1d, where it is 300 days against
        a ten-day regime, and false at 15m, where it is **three**, so the
        posterior sat against the cap permanently while `run_hours` looked like
        an estimate.
        """
        import random

        from till_infinity.structures.statespace.changepoint import (
            FRESH_LEAST,
            MAX_RUN,
            Changepoint,
        )

        # The memory, in components, must depend on the spacing.
        kept = {}
        for spacing, label in ((0.25, "15m"), (1.0, "1h"), (24.0, "1d")):
            rng = random.Random(4)
            engine = Changepoint()
            for i in range(400):
                when = i * spacing * 3600.0
                engine.predict(when)
                engine.update(100.0 + rng.gauss(0.0, 0.2), 0.04, when)
            kept[label] = engine._keep()
        assert kept["15m"] > kept["1h"] > kept["1d"], kept
        assert kept["1d"] < MAX_RUN, kept
        # Three expected regimes of ten days is 720 hours: 30 bars at 1d.
        assert 20 <= kept["1d"] <= 45, kept

        # And freshness covers a window of time, so on a fast series it spans
        # more components than the statistical floor alone.
        rng = random.Random(7)
        engine = Changepoint()
        for i in range(300):
            when = i * 0.25 * 3600.0
            engine.predict(when)
            engine.update(100.0 + rng.gauss(0.0, 0.2), 0.04, when)
        floor = sum(engine._weights()[: FRESH_LEAST + 1])
        assert engine.changepoint > floor, (engine.changepoint, floor)
        assert 0.0 <= engine.changepoint <= 1.0

        # `saturated` says when the run length is a lower bound rather than an
        # estimate. On a quiet series far shorter than the memory it is not.
        assert engine.saturated is False

    def test_the_ladder_reaches_from_seconds_to_weeks(self):
        """Seconds to weeks, on one series, from one ladder.

        The range is the package's claim and this is what makes it checkable.
        A feed fine enough and long enough resolves **every** rung - and the
        two bounds are what decide which slice any particular feed gets, so
        the slice is a property of the data rather than of the library:

        * a 1s feed of twenty thousand bars reaches `10s` but not `4h`, because
          four hours is more than a quarter of five and a half hours of data;
        * a 1d feed reaches `4w` but not `30m`, which is a fraction of a bar.

        Neither is a gap in the ladder. A feed cannot be asked about a horizon
        it has not observed, and asking anyway is what the bounds prevent.
        """
        from till_infinity.structures.statespace.inputs import (
            LADDER,
            bar_hours,
            coverage,
            resolvable,
        )

        # 5s bars, and enough of them that four weeks is under the quarter cap.
        whole = resolvable(5.0 / 3600.0, 2_000_000)
        assert len(whole) == len(LADDER), [w.label() for w in whole]
        assert whole[0].label() == "10s"
        assert whole[-1].label() == "4w"

        # The seconds end is reachable from real timestamps, not just from a
        # bar size passed in by hand.
        times = [i * 1.0 for i in range(20000)]
        bar = bar_hours(times)
        got = [w.label() for w in resolvable(bar, len(times), cover=coverage(times, bar))]
        assert got[0] == "10s", got
        assert "1h" in got, got
        assert "4h" not in got, got

        # And the weeks end, from a daily series.
        times = [i * 86400.0 for i in range(6000)]
        bar = bar_hours(times)
        got = [w.label() for w in resolvable(bar, len(times), cover=coverage(times, bar))]
        assert "4w" in got, got
        assert not any(g.endswith("s") or g == "30m" for g in got), got

    def test_a_window_is_resolved_on_trading_bars_not_calendar_ones(self):
        """`resolvable` must count the bars a window really holds.

        Its first bound exists so that no rung is shorter than two bars - below
        that it clamps to one and reports a single bar's own high and low under
        a name claiming a horizon. **That bound was computed without
        `coverage`**, so on a market that closes it counted calendar bars and
        admitted rungs the series could not build, which is the failure the
        bound was written to prevent.

        A five-day week makes the test concrete. On 15m bars that only exist on
        weekdays, half an hour is two bars of calendar and about **one** bar of
        trading, so the `30m` rung must drop out - and under the old conversion
        it did not.
        """
        from till_infinity.structures.statespace.inputs import (
            LEAST_BARS,
            bar_hours,
            coverage,
            resolvable,
        )

        # Six thousand 15m bars, weekends removed.
        times, when = [], 0.0
        while len(times) < 6000:
            day = int(when // 86400) % 7
            if day < 5:
                times.append(when)
            when += 900.0
        bar = bar_hours(times)
        cover = coverage(times, bar)
        assert 0.5 < cover < 0.95, cover

        got = resolvable(bar, len(times), cover=cover)
        assert got
        for window in got:
            # Every rung holds at least two bars of *this* series, which is the
            # only sense in which it is a window at all.
            assert window.bars(bar, cover) >= LEAST_BARS, (window.label(), cover)

        # And the correction bites: a rung that the calendar count would have
        # admitted is gone, because the series does not hold it.
        labels = {w.label() for w in got}
        naive = {w.label() for w in resolvable(bar, len(times))}
        assert "30m" in naive, "fixture no longer exercises the boundary"
        assert "30m" not in labels, (
            "a 30m window is one trading bar of a weekday 15m series, so it is "
            "not a window - the conversion is ignoring coverage again"
        )

    def test_the_estimators_moved_out_of_the_harnesses(self):
        """HAR-Parkinson and the causal EMA now live in the library.

        Both were stranded in `research/ideas/`, which is excluded from lint,
        has no tests, and is documented as experiments to be thrown away once
        the question is answered - a poor home for the two things that actually
        worked: the blend took the volatility forecast from 64% of achievable
        to 79%, and the EMA signals were the only slope variants to survive the
        overlap correction.
        """
        from till_infinity.structures.statespace.inputs import (
            Features,
            ema,
            garman_klass,
            har,
            parkinson,
            rolling,
        )

        # Parkinson is a per-bar variance from the range alone.
        flat = parkinson([101.0] * 5, [99.0] * 5)
        assert all(v == pytest.approx(flat[0]) for v in flat)
        assert flat[0] > 0.0
        # A wider bar is a larger variance.
        assert parkinson([110.0], [90.0])[0] > flat[0]
        # Degenerate bars give zero rather than a domain error.
        assert parkinson([0.0], [0.0])[0] == 0.0
        assert garman_klass([0.0], [0.0], [0.0], [0.0])[0] == 0.0

        # The EMA lags and the rolling mean is exact.
        source = [float(i) for i in range(10)]
        assert rolling(source, 3)[-1] == pytest.approx(8.0)
        assert ema(source, 3)[-1] < 9.0
        # HAR averages three spans, so it sits between the shortest and longest.
        blended = har(source, (2, 3, 5))[-1]
        assert rolling(source, 5)[-1] <= blended <= rolling(source, 2)[-1]

        # And they arrive as features, over the windows the series resolves.
        times = [i * 900.0 for i in range(2000)]
        closes = [100.0 + 0.01 * i for i in range(2000)]
        built = Features(
            times,
            [c + 0.5 for c in closes],
            [c - 0.5 for c in closes],
            closes,
            opens=[c - 0.01 for c in closes],
        )
        names = built.names()
        assert "har_parkinson" in names
        assert any(n.startswith("parkinson_") for n in names)
        assert any(n.startswith("ema_z_") for n in names)
        # Garman-Klass only when the open was given, never faked from the close.
        assert any(n.startswith("gk_") for n in names)
        without = Features(times, closes, closes, closes)
        assert not any(n.startswith("gk_") for n in without.names())

    def test_the_slope_is_a_rate_per_hour_not_per_bar(self):
        """The package rule applies to rates as much as to horizons.

        `rolling(moves, span)` is the mean log move per *bar*, which is a slope
        in bars and so not comparable across timeframes. Divided by the bar
        length it is a log return an hour, and the same drift then measures the
        same on every series: 2.977e-04 at 15m against 2.980e-04 at 1h.
        """
        from till_infinity.structures.statespace.inputs import Features

        got = {}
        for minutes, label in ((15, "15m"), (60, "1h")):
            bars = int(60 / minutes * 24 * 40)
            times = [i * minutes * 60.0 for i in range(bars)]
            closes = [100.0 * (1.0 + 0.01 * (i * minutes / 1440.0)) for i in range(bars)]
            built = Features(
                times,
                [c * 1.001 for c in closes],
                [c * 0.999 for c in closes],
                closes,
            )
            tag = built.windows[0].label()
            got[label] = built.at(bars - 1).of(f"slope_{tag}")

        # Different bar sizes, different windows, the same rate.
        assert got["15m"] == pytest.approx(got["1h"], rel=0.05), got
        assert got["15m"] > 0.0
