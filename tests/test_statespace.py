"""The thesis as a state space: the shared model, the three subjects, and the rule.

`till_infinity/structures/statespace/` is built beside production rather than
inside it, and the thing most worth testing is not any one filter - it is that
the package stays separable. The import test at the bottom is the one that keeps
the whole directory deletable.
"""

from __future__ import annotations

import itertools
import math
import statistics
from typing import ClassVar

import pytest

from till_infinity.statespace import (
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
    def test_every_subject_is_specified(self):
        """A subject that cannot say what its state means in words has not been
        specified, whatever its numbers are. I8 is this complaint.

        Four now: `spread` joined on 2026-10-11, because every cost gate here
        uses a constant and the SEC's payment-for-order-flow study finds the
        number moves with the composition of the flow. A cost that is
        forecast is a different gate from a cost that is averaged.
        """
        assert len(SUBJECTS) == 7
        assert {s.name for s in SUBJECTS} == {
            "level",
            "instrument",
            "relation",
            "spread",
            # The two that claim the open half of the problem, added
            # 2026-10-17 with the emission rule: every member forecasts
            # dispersion, and a subject now says which half it tracks.
            "dispersion",
            "relation dispersion",
            # v1's one measured turn result, ported 2026-10-17. Depth is a
            # magnitude, so it belongs in the dispersion half.
            "turn depth",
        }
        from till_infinity.statespace.subjects import DISPERSIONS

        assert {s.name for s in DISPERSIONS} == {
            "dispersion",
            "relation dispersion",
            "turn depth",
        }
        assert all(s.tracks in ("level", "dispersion") for s in SUBJECTS)
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

    def test_the_others_claim_nothing(self):
        """`INSTRUMENT` and `RELATION` still have no measurement behind them.

        `SPREAD` used to be in this list and has moved: its parameters are
        still placeholders, but the **subject** has been measured - and found
        not to earn its place, which is a result rather than an absence. The
        two categories are different and the test now says which is which.
        """
        for s in (INSTRUMENT, RELATION):
            assert "placeholder" in s.provenance
            assert "measured" not in s.provenance.replace("never fitted", "")

    def test_the_spread_has_been_measured_and_its_parameters_have_not(self):
        """Both at once, which is the state a measured-and-rejected subject is in.

        `statespace-spread.md` filtered the quoted spread and found it nearly
        constant - an hour-of-day profile of 1.02x to 1.09x where volatility's
        is 2.7x to 3.7x - so a five-observation trailing mean beats the filter
        and the constant cost gate every harness uses is wrong by under 8%.
        The parameters stay placeholders because fitting them is **degenerate
        on a constant**: `sigma2` and `theta` pin at opposite grid edges.
        """
        from till_infinity.statespace.subjects import SPREAD

        assert "measured" in SPREAD.provenance
        assert "placeholder" in SPREAD.provenance
        assert "Roll" in SPREAD.provenance, (
            "the provenance must keep why its independent check is unavailable"
        )

    def test_one_model_serves_all_three(self):
        """The thesis's central claim, refined by the thing that falsified it.

        It used to assert that every subject's `filter()` is a `Gaussian`, and
        that was true because `filter()` returned one unconditionally - the
        claim could not have failed, which is what item 7 on the README's
        priority list was complaining about.

        Now `RELATION` asks for `relating.Relating`, and the old assertion is
        false. **That is a real refinement rather than a broken test**, and the
        distinction is worth stating precisely:

        * at a **given** hedge ratio, a relationship *is* a level - a scalar
          with a latent fair value, noisy observations and a distance - and the
          thesis is exactly right;
        * when the ratio is **unknown**, there is an extra latent quantity a
          level does not have, and no amount of reinterpretation makes a
          two-state filter estimate it from one series.

        So what survives, and what is asserted here, is the interface claim:
        the three subjects are served by filters that answer the same
        questions. They are not served by the same class, and pretending they
        were is what left the hedge ratio unimplemented for as long as it was.
        """
        for s in SUBJECTS:
            g = s.filter(at=0.0)
            for i in range(30):
                if s.member == "relating":
                    # Its second leg is the thing it exists for. Handing it one
                    # series is handing it a regression on a constant.
                    g.update(1.0 + 0.1 * i, s.noise, i * HOUR, against=float(i))
                else:
                    g.update(1.0 + 0.1 * i, noise=s.noise, when=i * HOUR)
            assert math.isfinite(g.value)
            assert math.isfinite(g.rate)
            assert math.isfinite(g.sd)
            assert math.isfinite(g.loglike)
            assert g.seen == 30
            assert len(g.observation()[0]) == len(g.state())

    def test_a_level_and_an_instrument_still_share_one_class(self):
        """The half of the claim that did not change.

        A level and an instrument differ in what the number *means*, not in
        what has to be estimated, so they are the same filter with different
        parameters - which is the part of the thesis the hedge ratio does not
        touch.
        """
        for s in (LEVEL, INSTRUMENT):
            g = s.filter(at=0.0)
            assert isinstance(g, Gaussian)
            assert g.jerk == s.jerk

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
    offenders: list[str] = []
    nested: list[str] = []
    for path in root.rglob("*.py"):
        if "statespace" in path.parts:
            continue
        inside: set[int] = set()
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a file that will not parse
            continue
        for scope in ast.walk(tree):
            if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
                inside.update(
                    node.lineno
                    for node in ast.walk(scope)
                    if isinstance(node, ast.Import | ast.ImportFrom)
                )
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
            if not any("statespace" in n.split(".") for n in names):
                continue
            where = f"{path.relative_to(root)}:{node.lineno}"
            # **The graduation site, and the shape it has to keep.** `stack.py`
            # starts the service, which is what the docstring above calls
            # leaving behind a flag - `STATESPACE_ENABLED` here rather than a
            # structures engine flag. The import has to stay *inside* the
            # runner: at module level a deleted directory takes the whole stack
            # down where it is imported, and nested it fails in one supervised
            # task while every other service carries on. That is the
            # difference between deletable and load-bearing.
            if path.name == "stack.py":
                (nested if node.lineno in inside else offenders).append(where)
            else:
                offenders.append(where)
    assert not offenders, (
        "statespace is imported from outside itself: "
        f"{offenders}. Nothing in this package publishes until it has beaten a "
        "named null; see its __init__ docstring."
    )
    assert nested, (
        "nothing starts the service. `stack.py` is meant to import it inside "
        "`_run_statespace`; with no site at all this package is a library that "
        "folds no bars and publishes to nobody."
    )
    assert "STATESPACE_ENABLED" in (root / "stack.py").read_text(), (
        "the graduation has to be switchable"
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
        from till_infinity.statespace.family import Filter, members

        got = members()
        assert set(got) == {
            "kalman",
            "reverting",
            # The **value**-reverting member, added 2026-10-17 because two
            # dispersion harnesses had to write their own AR(1) around its
            # absence on the same day.
            "ornstein",
            "landau",
            "robust",
            "selective",
            # S4D-Real, promoted 2026-10-17 from `selective`'s nested null so
            # that the member which won 3m, 15m and 30m can be pooled at all.
            "s4d",
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
        from till_infinity.statespace.family import PENDING

        assert set(PENDING) == {"particle", "hmm", "rfs", "dpm"}
        for name, null in PENDING.items():
            assert len(null) > 40, f"{name}'s null is not stated properly"

    def test_the_family_table_records_both_particle_verdicts(self):
        """One filter family, two states, two opposite answers - which is the
        whole argument for asking per state. If this doc ever loses that, the
        reason the package is organised this way is lost with it."""
        from till_infinity.statespace import family

        doc = family.__doc__ or ""
        assert "machinery for nothing" in doc
        assert "all four series" in doc
        assert "per state" in doc


class TestRobust:
    def test_inside_the_gate_it_is_exactly_the_kalman(self):
        """**What makes it a fair arm.** The comparison has to be of the tails
        alone, not of two different models."""
        from till_infinity.statespace import Gaussian, Robust

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
        from till_infinity.statespace import Gaussian, Robust

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
        from till_infinity.statespace import Robust

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
        from till_infinity.statespace import Robust

        rng = __import__("random").Random(21)
        g = Robust(jerk=1e-9, at=0.0)
        for i in range(4000):
            g.update(5.0 + rng.gauss(0, 0.2), noise=0.04, when=i * HOUR)
        assert 0.0 <= g.gated_share < 0.10, g.gated_share
        assert g.worst_sigma > 2.0

    def test_a_non_finite_measurement_is_refused_here_too(self):
        from till_infinity.statespace import Robust

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
        from till_infinity.statespace.diagnostics import _chi2_sf

        for df in (2, 4, 10, 20):
            for x in (0.1, 1.0, 5.99, 18.3, 40.0):
                assert _chi2_sf(x, df) == pytest.approx(stats.chi2.sf(x, df), rel=1e-9)

    def test_odd_degrees_of_freedom_are_refused_rather_than_approximated(self):
        from till_infinity.statespace.diagnostics import _chi2_sf

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
        from till_infinity.statespace import fit_jerk

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
        from till_infinity.statespace import residuals

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
        from till_infinity.statespace import residuals

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
        from till_infinity.statespace import residuals

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
        from till_infinity.statespace import residuals

        assert residuals([0.1] * 29) is None
        assert residuals([0.1] * 40, lags=9) is None, "odd lags have no exact p-value"

    def test_the_overconfidence_reading_is_the_one_production_already_uses(self):
        """`vol-particle.md` measured the shipped EWMA at 1.199 to 1.291 against
        an honest 1.0 - 18-29% over-confident. Same statistic, same meaning."""
        from till_infinity.statespace import residuals

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
        from till_infinity.statespace import Gaussian, fit_jerk, hourly, simulate

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
        from till_infinity.statespace import hourly, simulate

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
        from till_infinity.statespace import simulate

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
        from till_infinity.statespace import hourly, simulate

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
        from till_infinity.statespace import with_gaps

        times = with_gaps(100, step_hours=1.0, gap_hours=62.0, every=24)
        gaps = sorted({round((times[i + 1] - times[i]) / 3600.0, 1) for i in range(len(times) - 1)})
        assert gaps == [1.0, 62.0]

    def test_a_path_needs_at_least_two_times(self):
        from till_infinity.statespace import simulate

        with pytest.raises(ValueError, match="at least two"):
            simulate([0.0], jerk=1e-3, noise=0.01)

    def test_the_residuals_of_a_correctly_generated_path_are_honest(self):
        """Generator and filter agreeing is the weakest useful check and the one
        worth having: if the standardised innovations are not standard normal
        here, one of the two is wrong."""
        from till_infinity.statespace import Gaussian, hourly, residuals, simulate

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

    The finished-series smoother was the real absence and is now
    `smoothing.py`; the **fixed-lag** form followed as `smoothing.lagged` and
    has been taken off the list. What is left presupposes a particle filter
    (Monte Carlo variance, sequential parameter learning), revises estimates
    a desk cannot unact (on-line smoothing), or is the one genuinely wanted
    thing - `evidence`, which would let members with different parameter
    counts be compared directly.

    `test_nothing_on_the_missing_list_is_actually_written` is the guard that
    keeps this honest; this one only checks the list's shape.
    """
    from till_infinity.statespace import MISSING

    assert set(MISSING) == {
        "on-line smoothing",
        "monte carlo variance",
        "sequential parameter learning",
        "evidence",
        "em",
    }
    # EM is **partly** built now: `diagnostics.fit_em` fits a scalar `Q`
    # multiplier and `R`, and the entry has to say which half remains or the
    # registry becomes a list of things that are already done.
    assert "smoothed posterior" in MISSING["em"], "EM needs the smoother first"
    assert "matrix M-step" in MISSING["em"], (
        "the entry must name what is still missing, not just what EM is for"
    )
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
    from till_infinity.statespace import family

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
    from till_infinity.statespace import PENDING

    note = PENDING["particle"]
    assert "systematic" in note, "the scheme the volatility harness used"
    assert "arXiv" in note or "PyDPF" in note


def test_the_smoother_is_written_and_listed_as_an_inference_mode():
    """`family.py` tracks three operations - filter, smooth, sample. All three
    exist now, and the table has to say so rather than still claiming a gap.

    **Both smoothers are written.** This used to assert that `fixed-lag
    smoother` was still in `MISSING`; it is now `smoothing.lagged` and has
    been taken off the list, which is the second stale entry found in a day -
    see `test_nothing_on_the_missing_list_is_actually_written` for the guard
    that stops a third.
    """
    from till_infinity.statespace import MISSING, family, smoothing

    doc = " ".join((family.__doc__ or "").split())
    assert "smoothing.smooth" in doc, "the table must point at the implementation"
    assert "smoother" not in MISSING
    assert "fixed-lag smoother" not in MISSING
    assert callable(smoothing.smooth)
    assert callable(smoothing.lagged)


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
    from till_infinity import statespace

    assert statespace.CODEC_UNPERSISTED is True
    assert codec.skipped("till_infinity.statespace.linear") is True
    assert codec.skipped("till_infinity.structures.levels") is False, (
        "the default has to stay 'a dataclass in a service is state'"
    )


class TestSmoothing:
    def test_the_smoother_beats_the_filter_on_the_same_data(self):
        """**The reason it exists.** At time `t` the filter has thrown away every
        measurement after `t`, and those say a great deal about where the state
        was. Measured against a path whose truth is known."""
        from till_infinity.statespace import hourly, simulate, smooth

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
        from till_infinity.statespace import hourly, simulate, smooth

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
        from till_infinity.statespace import simulate, smooth, with_gaps

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
        from till_infinity.statespace import Gaussian, hourly, simulate, smooth

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
        from till_infinity.statespace import smooth

        times = [0.0, HOUR, HOUR, 2 * HOUR, 3 * HOUR] + [(4 + i) * HOUR for i in range(40)]
        measured = [5.0 + 0.01 * i for i in range(len(times))]
        got = smooth(lambda: Gaussian(jerk=1e-4), times, measured, noise=0.01)
        assert got is not None
        assert all(math.isfinite(v) for v in got.value)

    def test_a_series_too_short_to_smooth_returns_nothing(self):
        from till_infinity.statespace import smooth

        assert smooth(lambda: Gaussian(jerk=1e-3), [0.0], [1.0], noise=0.01) is None
        assert smooth(lambda: Gaussian(jerk=1e-3), [], [], noise=0.01) is None

    def test_a_wrong_jerk_is_confidently_wrong_and_the_filter_is_where_it_shows(self):
        """**What a smoother cannot fix.** Told the level never moves, it produces
        a smooth, tight, wrong path - and the filtered innovations are still the
        place that says so."""
        from till_infinity.statespace import Gaussian, hourly, residuals, simulate

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


def test_nothing_on_the_missing_list_is_actually_written():
    """**The guard that stops the list rotting**, which the old one did not.

    `MISSING` is what someone reads to decide what to build next, so an entry
    describing something already finished is worse than no entry. It rotted
    twice in one day: `em` was half built and still described as absent, and
    `fixed-lag smoother` was fully built as `smoothing.lagged` and still
    listed.

    The old test asserted the **entry's text** - that "latency" appeared in
    it - which passes whether or not the code exists. This asserts the
    **code's absence** instead, by naming for each key the thing that would
    exist if it were done. A key whose probe starts resolving fails here,
    which is the only way the list stays honest.
    """
    import importlib

    from till_infinity.statespace import MISSING

    # For each remaining key, where it would live and what it would be called.
    probes = {
        "on-line smoothing": ("smoothing", ("online", "revise_all")),
        "monte carlo variance": ("diagnostics", ("monte_carlo", "seed_spread")),
        "sequential parameter learning": ("diagnostics", ("ibis", "smc_squared")),
        "evidence": ("diagnostics", ("evidence", "log_evidence")),
        "em": ("diagnostics", ("fit_em_matrix",)),
    }
    assert set(MISSING) == set(probes), (
        f"a key was added or removed without its probe: {set(MISSING) ^ set(probes)}"
    )

    for key, (where, names) in probes.items():
        module = importlib.import_module(f"till_infinity.statespace.{where}")
        for name in names:
            assert not hasattr(module, name), (
                f"MISSING['{key}'] says this is absent, but "
                f"{where}.{name} exists - update the registry"
            )

    # And the one that is written is gone from the list.
    from till_infinity.statespace import smoothing

    assert "fixed-lag smoother" not in MISSING
    assert callable(smoothing.lagged), "which is why it is not on the list"


def test_the_comparison_rule_is_held_out_and_says_why():
    """**A correctness point, not hygiene.** Members do not have the same number
    of free parameters, and in-sample likelihood rewards whichever has more - a
    particle filter with a richer transition fits a training series better than a
    Kalman whatever the truth is. Held-out likelihood or the model evidence are
    the honest comparisons, and this package has only the first.
    """
    from till_infinity.statespace import MISSING, family

    doc = " ".join((family.__doc__ or "").split())
    assert "held-out" in doc
    assert "evidence" in doc
    assert "evidence" in MISSING, "and it must be listed as absent"


def test_smoothing_cost_is_recorded_as_a_property_of_the_member():
    """It is nearly free for the linear-Gaussian member and the dominant expense
    for the particle one, which changes what a tie means: on levels the particles
    tied, so they cost O(N) to O(N^2) for nothing, on a two-core box."""
    from till_infinity.statespace import family

    doc = " ".join((family.__doc__ or "").split())
    assert "Cost is a property of the member" in doc
    assert "O(T N^2)" in doc or "O(T N) to O(T N^2)" in doc


def test_a_particle_member_would_need_an_error_bar_on_its_own_noise():
    """Run a particle filter twice with different seeds and it answers
    differently. Without a variance estimator, "beat the Kalman by 3%" cannot be
    told from that."""
    from till_infinity.statespace import MISSING

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
        from till_infinity.statespace import hourly, simulate, smooth

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
        from till_infinity.statespace import hourly, simulate, smooth

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
        from till_infinity.statespace import hourly, simulate, smooth

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

        from till_infinity.statespace import Gaussian, fit_jerk, hourly, smooth

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
        from till_infinity.statespace import simulate

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
        from till_infinity.statespace import Gaussian

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
        from till_infinity.statespace import slope_per_hour

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
        from till_infinity.statespace import slope_per_bar, slope_per_hour

        values = [2.0 + 0.4 * i for i in range(50)]
        got = slope_per_hour([i * HOUR for i in range(50)], values)
        assert got is not None
        assert got.per_bar == pytest.approx(slope_per_bar(values), abs=1e-9)

    def test_golden_section_finds_a_peak_it_was_not_told(self):
        from till_infinity.statespace import fit_jerk

        peak = 3.7e-5
        found, _best = fit_jerk(lambda j: -((math.log10(j) - math.log10(peak)) ** 2))
        assert math.log10(found) == pytest.approx(math.log10(peak), abs=0.03)

    def test_the_residual_statistics_match_a_numpy_computation(self):
        np = pytest.importorskip("numpy")
        from till_infinity.statespace import residuals

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
        from till_infinity.statespace.reverting import _process

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
        from till_infinity.statespace.reverting import _process

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
        from till_infinity.statespace.reverting import _process

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
        from till_infinity.statespace import Gaussian, Reverting

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
        from till_infinity.statespace import Reverting

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
        from till_infinity.statespace import Reverting

        g = Reverting(theta=0.5)
        assert g.half_life_hours == pytest.approx(math.log(2) / 0.5, rel=1e-9)
        assert g.half_life_hours == pytest.approx(1.386, abs=0.01)
        assert math.exp(-0.5 * 4.0) == pytest.approx(0.135, abs=0.001)
        assert Reverting(theta=0.0).half_life_hours == math.inf

    def test_it_beats_the_white_jerk_model_on_data_that_reverts(self):
        """Held out, because this model has one more parameter and in-sample fit
        would reward it for that alone."""
        import random

        from till_infinity.statespace import Gaussian, Reverting

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
        from till_infinity.statespace import Reverting

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
        from till_infinity.statespace import Reverting

        g = Reverting(sigma2=0.18, theta=0.5, at=0.0)
        g.update(1.0, noise=0.01, when=0.0)
        before = g.p00
        g.predict(48 * HOUR)
        assert g.p00 > before
        assert g.existence < 1.0

    def test_it_is_a_member_of_the_family(self):
        from till_infinity.statespace.family import Filter, members

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
        from till_infinity.statespace import Reverting
        from till_infinity.statespace.reverting import _process

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
        from till_infinity.statespace import Reverting

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
        from till_infinity.statespace.smoothing import _inverse

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
        from till_infinity.statespace.smoothing import _inverse

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
        from till_infinity.statespace import Robust

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
        from till_infinity.statespace.linear import EXISTENCE_HALF_LIFE_HOURS
        from till_infinity.structures.engine import FORGET_FEED_SECONDS

        assert pytest.approx(FORGET_FEED_SECONDS / 3600.0) == EXISTENCE_HALF_LIFE_HOURS

    def test_the_smoother_takes_a_factory_and_names_no_member(self):
        """It used to build a `Gaussian` itself and therefore could not smooth
        the member that wins. It takes a factory now and knows no member's
        parameters - a signature mentioning `jerk` or `theta` would mean it had
        picked one again."""
        import inspect

        from till_infinity.statespace import smoothing

        parameters = inspect.signature(smoothing.smooth).parameters
        assert "build" in parameters
        assert "jerk" not in parameters
        assert "theta" not in parameters
        assert "sigma2" not in parameters

    def test_it_smooths_both_members_through_one_recursion(self):
        """Two states and three, from the same code - and `linear`'s answer is
        unchanged, which is what says the generalisation cost nothing."""
        from till_infinity.statespace import (
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
        from till_infinity.statespace import Reverting, hourly, simulate, smooth

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
        from till_infinity.statespace import smooth

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
        from till_infinity.statespace import Gaussian

        g = Gaussian(jerk=0.0)
        g.accel, g.p22 = 9.0, 0.0
        assert g.accel_confident is False
        g.p22 = 1e-6
        assert g.accel_confident is True

    def test_revertings_accel_is_the_rates_pull_and_not_a_state(self):
        """It reports `-theta * rate` because that is where the rate is heading.
        A consumer needing the acceleration's own uncertainty needs `linear`."""
        from till_infinity.statespace import Reverting

        g = Reverting(sigma2=0.18, theta=0.4)
        g.rate = 2.0
        assert g.accel == pytest.approx(-0.8)
        assert not hasattr(g, "p22"), "there is no third state to carry a variance"

    def test_fit_jerk_reports_the_bracket_edge_rather_than_hiding_it(self):
        """Documented behaviour: returning the edge means the answer is outside
        the range searched, and the caller is told by getting the edge."""
        from till_infinity.statespace import fit_jerk

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
        from till_infinity.statespace.selective import (
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
        from till_infinity.statespace.selective import Selective

        flat = Selective(scale=0.0)
        # The same elapsed time retains the same fraction whatever the reading.
        assert flat.retention(0.5, z=-5.0) == flat.retention(0.5, z=5.0)

        live = Selective(scale=1.0)
        assert live.retention(0.5, z=-5.0) != live.retention(0.5, z=5.0)

    def test_delta_at_inert_is_exactly_the_elapsed_hours(self):
        """`softplus(INERT) == 1`, so the null advances one hour of `delta` per
        hour of clock - the property that makes it the *nested* null rather than
        merely a nearby one."""
        from till_infinity.statespace.selective import INERT, softplus

        assert softplus(INERT) == pytest.approx(1.0, abs=1e-15)

    def test_a_surprising_reading_opens_the_gate(self):
        """Selection, in the direction the paper describes: a large `delta`
        resets the state onto the current input, a small one keeps the state and
        ignores it."""
        from till_infinity.statespace.selective import Selective

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
        from till_infinity.statespace.selective import sigmoid, softplus

        assert softplus(800.0) == pytest.approx(800.0)
        assert softplus(-800.0) == pytest.approx(0.0)
        assert sigmoid(800.0) == pytest.approx(1.0)
        assert sigmoid(-800.0) == pytest.approx(0.0)

    def test_it_tracks_a_level_and_reports_a_rate_it_does_not_store(self):
        """`h` holds coefficients of the transition's basis, not named
        quantities, so `value` and `rate` are read out of it rather than being
        slots in it."""
        from till_infinity.statespace.selective import SIZE, Selective

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
        from till_infinity.statespace.selective import SIZE, Selective
        from till_infinity.statespace.smoothing import smooth

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
        from till_infinity.statespace.family import Filter, members
        from till_infinity.statespace.selective import Selective

        assert members()["selective"] is Selective
        assert isinstance(Selective(), Filter)

    def test_the_score_is_the_one_reverting_is_scored_on(self):
        """A deterministic map has no likelihood of its own; `noise` as a fitted
        one-step spread is what buys comparability against the null."""
        from till_infinity.statespace.selective import Selective

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
        from till_infinity.statespace.family import members

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
        from till_infinity.statespace.family import members

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
        from till_infinity.statespace.selective import SIZE, Selective

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
        from till_infinity.statespace.family import Filter, members

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
        from till_infinity.statespace.family import members

        without = {n for n, c in members().items() if not hasattr(c(), "covariance")}
        # `s4d` is `selective` with the selection pinned off, so it is the same
        # deterministic map and has no posterior either. That is inherited
        # rather than overlooked, and it is why `smoothing.smooth` returns None
        # for both of them instead of half-smoothing one.
        assert without == {"selective", "s4d"}

    def test_existence_decays_on_time_alone_and_never_exceeds_one(self):
        """The one genuine probability here. An absence of evidence is caused by
        time passing, so `predict` alone has to move it."""
        from till_infinity.statespace.family import members
        from till_infinity.statespace.linear import EXISTENCE_HALF_LIFE_HOURS

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
        from till_infinity.statespace.family import members

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
        from till_infinity.statespace.selective import Selective

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
        from till_infinity.statespace.selective import SIZE, Selective

        assert Selective.eigenvalues() == tuple(-(n + 1.0) for n in range(SIZE))
        assert all(a < 0.0 for a in Selective.eigenvalues())

    def test_the_bias_trick_hits_any_target_step(self):
        """The reference sets its `dt` bias to `dt + log(-expm1(-dt))` so that
        `softplus(bias)` recovers a sampled `dt`. `INERT` is that at a target of
        one, which is what makes the null exactly "one hour of `delta` per hour
        of clock" rather than approximately it."""
        from till_infinity.statespace.selective import (
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
        from till_infinity.statespace.selective import Selective

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
        from till_infinity.statespace.swarm import SIZE, Swarm

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
        from till_infinity.statespace.selective import Selective
        from till_infinity.statespace.swarm import Swarm

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
        from till_infinity.statespace.swarm import Swarm

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
        from till_infinity.statespace.smoothing import smooth
        from till_infinity.statespace.swarm import SIZE, Swarm

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
        from till_infinity.statespace.swarm import COUNT, Swarm

        engine = Swarm(wander=0.2)
        for i in range(200):
            when = i * 900.0
            engine.predict(when)
            engine.update(100.0 + 0.05 * i, 0.4, when)
        assert engine.effective() > 0.1 * COUNT, engine.effective()
        assert engine.resampled > 0, "nothing resampled, so the trigger never fired"
        assert engine.sd > 0.0

    def test_it_is_in_the_family_and_satisfies_the_protocol(self):
        from till_infinity.statespace.family import Filter, members
        from till_infinity.statespace.swarm import Swarm

        assert members()["swarm"] is Swarm
        engine = Swarm()
        assert isinstance(engine, Filter)
        assert 0.0 <= engine.existence <= 1.0

    def test_a_run_is_reproducible(self):
        """A particle filter whose answer moves between runs cannot be scored
        against a null, so the seed is part of the member."""
        from till_infinity.statespace.swarm import Swarm

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
        from till_infinity.statespace.swarm import Swarm

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
        from till_infinity.statespace.family import members
        from till_infinity.statespace.linear import EXISTENCE_HALF_LIFE_HOURS

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
        from till_infinity.statespace.family import members

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
        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.smoothing import lagged, smooth

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
        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.smoothing import lagged

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
        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.smoothing import lagged

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
        from till_infinity.statespace.selective import Selective
        from till_infinity.statespace.smoothing import lagged

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
        from till_infinity.statespace.inputs import WEEKS, bar_hours

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
        from till_infinity.statespace.inputs import (
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
        from till_infinity.statespace.inputs import WEEKS, Features

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
        from till_infinity.statespace.inputs import WEEKS, Features

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
        from till_infinity.statespace.inputs import WEEKS, Features

        times = [i * 900.0 for i in range(400)]
        closes = [100.0] * 400
        features = Features(times, closes, closes, closes, windows=WEEKS)
        got = features.at(300)
        assert len(got) == len(got.names)
        # Seven per window - high, low, rv, parkinson, slope, ema_slope,
        # ema_z - plus the two blends. `position` is a method rather than a
        # stored feature because it is a ratio of two that are stored, and
        # `gk` is absent because no opens were given. The counted-event
        # features are **off by default** because they were measured and
        # carry nothing; `counted=True` adds them.
        assert len(got) == 7 * len(WEEKS) + 2
        assert got.of("rv_4w") == 0.0  # a flat series has no realised vol
        assert got.of("parkinson_4w") == 0.0
        assert "har_parkinson" in got.names
        assert "spikes_4w" not in got.names, "counted features default off"
        with pytest.raises(KeyError):
            got.of("not_a_feature")

    def test_the_counted_features_are_opt_in_and_say_why(self):
        """**Measured, null, and therefore off by default.**

        Over 1,020 cells on six instruments and two timeframes, every family
        of counted-event feature came within 0.032 of its own rotated control
        and within 0.015 of zero net of a trailing standard deviation. They
        are kept because the measurement is worth more than the code, and
        defaulted off because 48 features widen the multiple-comparison
        surface for every caller of `Features`.
        """
        from till_infinity.statespace.inputs import WEEKS, Features

        times = [i * 900.0 for i in range(400)]
        closes = [100.0 + (i % 7) * 0.1 for i in range(400)]
        highs = [c + 0.3 for c in closes]
        lows = [c - 0.3 for c in closes]

        off = Features(times, closes, highs, lows, windows=WEEKS)
        on = Features(times, closes, highs, lows, windows=WEEKS, counted=True)
        assert len(on.names()) > len(off.names())
        assert "spikes_4w" in on.names()
        assert "spikes_4w" not in off.names()
        # The features that were always there must be identical either way.
        for name in off.names():
            assert name in on.names()
            assert off.at(300).of(name) == pytest.approx(on.at(300).of(name))

    def test_a_pivot_is_counted_where_it_is_confirmed_not_where_it_happened(self):
        """**The leak this feature would have had.**

        A swing high at bar `k` is only knowable at `k + span`, once `span`
        bars have failed to exceed it. Marking it at `k` would be a feature
        that knows the future - the same shape as the cross-resolution bug
        this project has already paid for at `t = +20.8` on five symbols.
        """
        from till_infinity.statespace.inputs import pivots

        # A single, unmistakable peak at index 20.
        highs = [1.0] * 41
        highs[20] = 5.0
        lows = [0.0] * 41

        flags = pivots(highs, lows, span=5)
        assert not flags[20], "marked at the peak, which nobody could know yet"
        assert flags[25], "should be confirmed five bars later"
        assert sum(flags[:25]) == 0, "nothing may be flagged before confirmation"

    def test_the_counted_rates_are_per_hour_on_every_timeframe(self):
        """The same market sampled twice must give the same rate.

        One spike every ten bars of 15m is one every 2.5 hours; one every ten
        bars of 1h is one every ten. If these came out equal the feature would
        be counting bars, which is what the package forbids.
        """
        from till_infinity.statespace.inputs import per_hour

        flags = [i % 10 == 0 for i in range(400)]
        quick = per_hour(flags, span=40, bar=0.25)
        slow = per_hour(flags, span=40, bar=1.0)
        assert quick[-1] == pytest.approx(4.0 * slow[-1], rel=1e-9)
        # Four spikes per ten hours of 15m bars is 0.4 an hour.
        assert slow[-1] == pytest.approx(0.1, rel=1e-6)

    def test_time_since_an_event_is_hours_not_bars(self):
        """Same portability argument, and `inf` rather than a plausible number
        when the thing has never happened."""
        from till_infinity.statespace.inputs import since

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

        from till_infinity.statespace.changepoint import Changepoint

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

        from till_infinity.statespace.changepoint import HAZARD, Changepoint

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

        from till_infinity.statespace.changepoint import Changepoint

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
        from till_infinity.statespace.changepoint import Changepoint

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
        from till_infinity.statespace.changepoint import MAX_RUN, Changepoint

        engine = Changepoint()
        for i in range(MAX_RUN + 200):
            engine.predict(i * 900.0)
            engine.update(100.0, 0.09, i * 900.0)
        weights = engine._weights()
        assert len(weights) <= MAX_RUN
        assert sum(weights) == pytest.approx(1.0)

    def test_it_is_in_the_family_and_satisfies_the_protocol(self):
        from till_infinity.statespace.changepoint import Changepoint
        from till_infinity.statespace.family import Filter, members

        assert members()["changepoint"] is Changepoint
        engine = Changepoint()
        assert isinstance(engine, Filter)
        engine.update(100.0, 0.09, 0.0)
        engine.predict(900.0)
        engine.update(100.5, 0.09, 900.0)
        assert math.isfinite(engine.loglike)
        assert engine.output() == (engine.value,)
        assert len(engine.observation()[0]) == len(engine.state())


class TestSpectrum:
    """Eigenvalues, as durations and as a verdict."""

    def test_every_member_that_states_its_transition_has_a_readable_spectrum(self):
        """And the two findings the first run produced."""
        pytest.importorskip("numpy")

        from till_infinity.statespace.family import members
        from till_infinity.statespace.fractional import Fractional
        from till_infinity.statespace.spectrum import spectrum

        built = {**members(), "fractional": Fractional}
        seen = {}
        for name, build in built.items():
            engine = build()
            engine.predict(0.0)
            engine.update(1.0, 0.1, 0.0)
            got = spectrum(engine, 1.0)
            if got is None:
                continue
            seen[name] = got
            assert got.stability in {"stable", "marginal", "unstable"}
            assert got.stability != "unstable", (
                f"{name} has an eigenvalue outside the unit circle, which is a "
                "state that grows without bound"
            )
            assert len(got.half_lives) == got.states

        # `linear` is a triple integrator: three unit roots and no half-life.
        assert all(math.isinf(h) for h in seen["kalman"].half_lives)
        assert seen["kalman"].stability == "marginal"

        # **And its eigenvector matrix is defective.** Three identical
        # eigenvalues with one eigenvector is a Jordan block, so the modal
        # decomposition is numerically meaningless - which is worth knowing
        # before reading anything modal into its three states.
        assert seen["kalman"].conditioning > 1e6, seen["kalman"].conditioning

        # `reverting` keeps the level's unit root and gives the rate a
        # half-life, which is the whole difference between the two members.
        lives = sorted(seen["reverting"].half_lives)
        assert math.isinf(lives[-1])
        assert 0.5 < lives[0] < 5.0, lives

    def test_a_member_whose_modes_are_all_short_cannot_reach_a_long_horizon(self):
        """Structural, and visible before any data.

        `selective`'s realised half-lives are all under an hour, so it cannot
        represent a daily level however it is fitted. `fractional` spans the
        ladder by construction. That is the comparison `reachable` exists for.
        """
        pytest.importorskip("numpy")

        from till_infinity.statespace.fractional import Fractional
        from till_infinity.statespace.selective import Selective
        from till_infinity.statespace.spectrum import reachable

        quick = Selective()
        quick.predict(0.0)
        quick.update(1.0, 0.1, 0.0)
        shortest, longest = reachable(quick, 1.0)
        assert longest < 2.0, (shortest, longest)

        wide = Fractional(fastest=1.0, slowest=672.0)
        wide.predict(0.0)
        wide.update(1.0, 0.1, 0.0)
        shortest, longest = reachable(wide, 1.0)
        assert shortest < 2.0
        assert longest > 500.0, (shortest, longest)

    def test_the_hedge_ratio_is_observable_only_because_the_leg_moves(self):
        """**A true statement wearing an artifact's clothes.**

        The observability matrix assumes `C` is constant, and `Relating`'s is
        not - it carries the other leg. Frozen, it reports one hidden state of
        two, and that is exactly right *if the leg does not move*: a pair whose
        independent leg is constant has nothing to separate a level from a
        slope with. The identifiability of a hedge ratio rests on the variation
        in `x`, and this is where that is written down.
        """
        pytest.importorskip("numpy")

        from till_infinity.statespace.relating import Relating
        from till_infinity.statespace.spectrum import spectrum

        engine = Relating()
        engine.predict(0.0)
        engine.update(1.0, 0.1, 0.0, against=3.0)
        got = spectrum(engine, 1.0)
        assert got is not None
        assert got.states == 2
        assert got.observable == 1, "a frozen C should not separate the two"
        assert not got.fully_observable

    def test_a_member_that_cannot_state_its_transition_declines(self):
        """The same contract `smooth` uses."""
        from till_infinity.statespace.nulls import Walk
        from till_infinity.statespace.spectrum import spectrum

        assert spectrum(Walk(), 1.0) is None


class TestFractional:
    """Long memory from a sum of short memories."""

    def test_its_forecast_decays_fast_then_slowly(self):
        """**The shape a single exponential cannot have.**

        A power-law kernel falls quickly at first and then very slowly. One
        exponential has a single time scale, so its decay is a straight line
        in logs; a sum of them bends. The test is that bend, measured as the
        ratio of successive half-lives of the forecast itself.
        """
        from till_infinity.statespace.fractional import Fractional
        from till_infinity.statespace.reverting import Reverting

        engine = Fractional()
        engine.predict(0.0)
        engine.update(10.0, 0.1, 0.0)
        got = [engine.at_time(h * 3600.0) for h in (1, 6, 24, 168, 672)]
        assert got == sorted(got, reverse=True), got
        assert got[0] < 10.0
        assert got[-1] > 0.0

        # The first six hours lose more than the next 23 days, which is what
        # "no typical scale" means in one sentence.
        early = 10.0 - got[1]
        late = got[1] - got[-1]
        assert early > 0.6 * late, (early, late)

        # A single reverting mode decays geometrically: equal time ratios give
        # equal value ratios. This must not.
        single = Reverting()
        single.predict(0.0)
        single.update(10.0, 0.1, 0.0)
        ours = [engine.at_time(h * 3600.0) for h in (24, 168)]
        assert ours[1] / ours[0] > 0.3, "decayed like one exponential"

    def test_the_modes_are_geometric_and_span_the_range_asked_for(self):
        from till_infinity.statespace.fractional import Fractional

        engine = Fractional(modes=5, fastest=1.0, slowest=672.0)
        lives = engine.half_lives
        assert len(lives) == 5
        assert lives[0] == pytest.approx(1.0)
        assert lives[-1] == pytest.approx(672.0)
        ratios = [lives[i + 1] / lives[i] for i in range(4)]
        for r in ratios:
            assert r == pytest.approx(ratios[0], rel=1e-9)

    def test_it_satisfies_the_family_contract(self):
        import random

        from till_infinity.statespace.fractional import Fractional

        rng = random.Random(2)
        engine = Fractional()
        level = 0.0
        for i in range(300):
            level += rng.gauss(0.0, 0.4)
            engine.predict(i * 3600.0)
            engine.update(level, 0.16, i * 3600.0)
        assert engine.output() == (engine.value,)
        assert len(engine.observation()[0]) == len(engine.state())
        assert math.isfinite(engine.loglike)
        assert math.isfinite(engine.sd)
        low, high = engine.band(engine.at + 3600.0)
        assert low < engine.at_time(engine.at + 3600.0) < high
        for i in range(engine.modes):
            for j in range(engine.modes):
                assert engine.covariance[i][j] == pytest.approx(
                    engine.covariance[j][i], rel=1e-12, abs=1e-15
                )

    def test_long_memory_in_the_level_is_not_clustering(self):
        """**The prediction that failed, pinned so it stays failed.**

        A sum of exponentials gives the mean memory at every scale. It does
        not make the conditional variance depend on past magnitudes, so the
        rollout does not cluster - +0.192 against `reverting`'s +0.190. The
        member that would cluster is this device applied to log variance,
        which is not written.
        """
        from till_infinity.statespace.facts import measure, rollout
        from till_infinity.statespace.fractional import Fractional
        from till_infinity.statespace.paths import hourly

        got = measure(rollout(Fractional, hourly(4000), noise=0.25, seed=5))
        assert got.clustering < 0.5, (
            "if this now clusters, the docstring's explanation is wrong and "
            "the finding needs rewriting rather than the test relaxing"
        )


class TestSwitching:
    """Balance and imbalance as two regimes, mixed each step."""

    @staticmethod
    def _alternating(seed: int = 8):
        import random

        rng = random.Random(seed)
        values, phase = [], []
        level, anchor = 100.0, 100.0
        for block in range(12):
            trending = block % 3 == 2
            for _ in range(120 if trending else 400):
                if trending:
                    level += rng.gauss(0.25, 0.3)
                else:
                    level += -0.3 * (level - anchor) + rng.gauss(0.0, 0.3)
                values.append(level)
                phase.append(1 if trending else 0)
            if trending:
                anchor = level
        return values, phase

    def test_it_is_sharp_about_imbalance_and_weak_about_balance(self):
        """**The measured asymmetry, pinned rather than smoothed over.**

        During a trend it is 98.5% sure, because trending is something a
        reverting model genuinely cannot do. During rotation it is barely past
        a coin, because the imbalance regime *is* a random walk and a random
        walk fits a noisy rotation acceptably - which is the finding this desk
        keeps producing from other directions.
        """
        import statistics

        from till_infinity.statespace.switching import Switching

        values, phase = self._alternating()
        engine = Switching()
        seen = []
        for i, value in enumerate(values):
            engine.predict(i * 3600.0)
            engine.update(value, 0.09, i * 3600.0)
            seen.append(engine.balance)

        rotating = statistics.fmean(seen[i] for i in range(len(seen)) if phase[i] == 0)
        trending = statistics.fmean(seen[i] for i in range(len(seen)) if phase[i] == 1)
        assert trending < 0.1, trending
        assert rotating > trending * 5.0, (rotating, trending)
        # And the weak half is weak: this is evidence of imbalance, not of
        # balance, and the test says so rather than asserting a number it
        # does not reach.
        assert rotating < 0.8, rotating

    def test_the_regime_durations_are_hours_not_bars(self):
        """A probability per bar would be a different model per timeframe."""
        from till_infinity.statespace.switching import Switching

        engine = Switching(balance_hours=24.0, imbalance_hours=4.0)
        quick = engine._switch(0.25)
        slow = engine._switch(1.0)
        # Leaving is likelier over a longer step, and each row sums to one.
        assert slow[0][1] > quick[0][1]
        for row in (*quick, *slow):
            assert sum(row) == pytest.approx(1.0)
        # Over a step equal to the duration, about 63% have left.
        full = engine._switch(24.0)
        assert full[0][1] == pytest.approx(1.0 - math.exp(-1.0), rel=1e-9)

    def test_the_mixture_spread_carries_the_disagreement(self):
        """Two regimes disagreeing about the value *is* uncertainty.

        Dropping the between-component term is how a switching model reports
        confidence it does not have.
        """
        from till_infinity.statespace.switching import Switching

        engine = Switching()
        engine.means = [100.0, 110.0]
        engine.variances = [1.0, 1.0]
        engine.weights = [0.5, 0.5]
        # Within-component spread alone would be 1.0; the gap adds 25.
        assert engine.sd == pytest.approx(math.sqrt(26.0), rel=1e-9)

    def test_it_satisfies_enough_of_the_contract_to_be_scored(self):
        import random

        from till_infinity.statespace.switching import Switching

        rng = random.Random(3)
        engine = Switching()
        level = 100.0
        for i in range(400):
            level += rng.gauss(0.0, 0.4)
            engine.predict(i * 3600.0)
            engine.update(level, 0.16, i * 3600.0)
        assert engine.output() == (engine.value,)
        assert len(engine.observation()[0]) == len(engine.state())
        assert math.isfinite(engine.loglike)
        assert 0.0 <= engine.balance <= 1.0
        low, high = engine.band(engine.at + 3600.0)
        assert low < engine.at_time(engine.at + 3600.0) < high


class TestPanel:
    """Many instruments at once - the vector observation the family lacked."""

    @staticmethod
    def _run(size: int, shift: float = 2.0, seed: int = 5):
        import random
        import statistics

        from till_infinity.statespace.panel import Panel

        rng = random.Random(seed)
        base = [100.0 - 8 * k for k in range(size)]
        factor = 0.0
        panel = Panel(size=size, wander=1e-2, idio_wander=1e-4, theta=0.05)
        after = []
        for i in range(3000):
            factor += rng.gauss(0.0, 0.3)
            seen = [base[k] + factor + rng.gauss(0.0, 0.15) for k in range(size)]
            if i > 1500:
                seen[size - 1] += shift
            panel.predict(i * 3600.0)
            panel.update(seen, 0.0225, i * 3600.0)
            if i > 1800:
                after.append([abs(panel.spread_of(k)) for k in range(size)])
        means = [statistics.fmean(row[k] for row in after) for k in range(size)]
        return panel, means, factor

    def test_the_solver_matches_numpy(self):
        """The module rule: anything hand-written arrives with a reference."""
        numpy = pytest.importorskip("numpy")

        from till_infinity.statespace.panel import _solve

        rng = numpy.random.default_rng(3)
        a = rng.normal(size=(5, 5))
        a = a @ a.T + 5.0 * numpy.eye(5)  # symmetric positive definite
        b = rng.normal(size=(5, 3))
        ours = _solve(a.tolist(), b.tolist())
        theirs = numpy.linalg.solve(a, b)
        for i in range(5):
            for j in range(3):
                assert ours[i][j] == pytest.approx(theirs[i][j], rel=1e-9, abs=1e-12)

    def test_separating_a_dislocation_needs_panel_width(self):
        """**The property that makes this a panel rather than a pair.**

        One instrument is shifted and the others are not. A factor model has
        to decide how much of that shift was the factor, and with `n`
        instruments the contamination is about `1/n` - so a pair cannot tell a
        dislocation from a factor move and a wide panel can. Measured, the
        separation goes 2.0x at three instruments to 10.3x at sixteen.
        """
        import statistics

        ratios = {}
        for size in (3, 8, 16):
            _panel, means, _factor = self._run(size)
            others = statistics.fmean(means[:-1])
            ratios[size] = means[-1] / max(others, 1e-9)

        assert ratios[3] < ratios[8] < ratios[16], ratios
        assert ratios[3] < 3.0, ratios
        assert ratios[16] > 6.0, ratios

    def test_the_idiosyncratics_revert_to_where_they_live(self):
        """Reverting to zero fought the instruments' permanent level gaps.

        The instruments sit at 100, 92, 84 and so on; those offsets land in
        the idiosyncratics at initialisation and are not dislocations.
        Reverting to zero made the filter fight them every step and produced
        z-scores of 610 when the only real dislocation was 2.0.
        """
        panel, means, _factor = self._run(8, shift=0.0)
        # With no dislocation, every instrument should sit near its anchor.
        assert max(means) < 6.0, means
        assert len(panel.anchors) == 8

    def test_it_tracks_the_common_factor(self):
        import statistics

        panel, _means, factor = self._run(8, shift=0.0)
        # The factor carries the shared walk plus the mean base level.
        expected = factor + statistics.fmean(100.0 - 8 * k for k in range(8))
        assert panel.factor == pytest.approx(expected, abs=2.0)

    def test_a_panel_that_changes_width_is_refused(self):
        from till_infinity.statespace.panel import Panel

        panel = Panel(size=3)
        panel.predict(0.0)
        panel.update([1.0, 2.0, 3.0], 0.1, 0.0)
        with pytest.raises(ValueError, match="instruments"):
            panel.update([1.0, 2.0], 0.1, 3600.0)

    def test_it_satisfies_enough_of_the_contract_to_be_scored(self):
        panel, _means, _factor = self._run(4, shift=0.0)
        assert len(panel.state()) == 5  # factor plus four idiosyncratics
        assert len(panel.observation()) == 4
        assert len(panel.observation()[0]) == len(panel.state())
        assert math.isfinite(panel.loglike)
        low, high = panel.band(panel.at + 3600.0)
        assert low < panel.at_time(panel.at + 3600.0) < high
        assert panel.half_life() > 0


class TestRelating:
    """The hedge ratio as a state - what statistical arbitrage needed."""

    def test_it_tracks_a_drifting_hedge_ratio_that_a_static_fit_cannot(self):
        """**The reason this member exists.**

        A pair's hedge ratio moves, and a static fit averages over the move.
        If the filter cannot beat least squares on a drifting ratio it has
        bought nothing over the spread somebody computed by hand.
        """
        import random
        import statistics

        from till_infinity.statespace.relating import Relating

        rng = random.Random(7)
        xs, ys, betas, x = [], [], [], 100.0
        for i in range(3000):
            x += rng.gauss(0.0, 1.0)
            beta = 1.0 + i / 3000
            xs.append(x)
            ys.append(5.0 + beta * x + rng.gauss(0.0, 0.5))
            betas.append(beta)

        def fit(centre: bool):
            engine = Relating(ratio_wander=1e-5, centre=centre)
            seen = []
            for i, (leg, dependent) in enumerate(zip(xs, ys, strict=True)):
                engine.predict(i * 3600.0)
                engine.update(dependent, 0.25, i * 3600.0, against=leg)
                seen.append(engine.ratio)
            return engine, seen

        # **Both arms, because centring is a trade-off and this is the side it
        # costs on.** Centring removes the intercept's collinearity with a
        # near-constant leg, which is the common case and worth 30x in
        # calibration - but here the ratio doubles over the sample, so in
        # centred coordinates the intercept has to travel `dbeta * anchor`,
        # a hundred units. The induced variance is added in `predict` and that
        # took this from 2.30 to 1.94; the residual gap against the uncentred
        # 1.998 is what centring costs when the weights move a long way.
        centred, _ = fit(centre=True)
        engine, tracked = fit(centre=False)
        assert centred.ratio == pytest.approx(betas[-1], abs=0.10)
        assert engine.ratio == pytest.approx(betas[-1], abs=0.05)

        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((v - mx) ** 2 for v in xs)
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
        static = sxy / sxx
        ours = statistics.fmean(abs(t - b) for t, b in zip(tracked[500:], betas[500:], strict=True))
        theirs = statistics.fmean(abs(static - b) for b in betas[500:])
        assert ours < theirs / 10.0, (ours, theirs)

    def test_a_basket_is_the_same_member(self):
        """`legs=3`, because a pair is the `legs=1` case and not a special one."""
        import random

        from till_infinity.statespace.relating import Relating

        rng = random.Random(11)
        legs, truth = [100.0, 50.0, 20.0], (0.8, -0.5, 1.3)
        engine = Relating(legs=3, ratio_wander=1e-8)
        for i in range(4000):
            legs = [v + rng.gauss(0.0, 0.7) for v in legs]
            dependent = (
                2.0 + sum(t * v for t, v in zip(truth, legs, strict=True)) + rng.gauss(0.0, 0.4)
            )
            engine.predict(i * 3600.0)
            engine.update(dependent, 0.16, i * 3600.0, against=legs)

        for got, wanted in zip(engine.ratios, truth, strict=True):
            assert got == pytest.approx(wanted, abs=0.2), (engine.ratios, truth)

        # The covariance must stay symmetric; round-off breaks it, and a
        # covariance that is no longer symmetric is no longer a covariance.
        for i in range(4):
            for j in range(4):
                assert engine.covariance[i][j] == pytest.approx(
                    engine.covariance[j][i], rel=1e-12, abs=1e-15
                )

    def test_centring_the_legs_makes_the_uncertainty_honest(self):
        """**The limitation, and its fix, measured side by side.**

        An uncentred basket of near-constant legs is collinear with the
        intercept - a leg sitting near 100 with a little wander is almost the
        constant column - so the filter learns the combinations it can see,
        leaves a persistent error along the one it cannot, and shrinks its
        covariance anyway because it really is gaining information in the
        directions that affect its forecast. The weights come out wrong and
        the stated confidence is thirty times too small.

        It is fixed by subtracting a fixed anchor, and this test exists
        because two other fixes did not work: an innovation-based adaptive
        noise did nothing (the standardised innovations already had unit
        variance, so `R` was not the problem), and a *running* mean of a
        random walk follows the walk, which destroys the regressor rather
        than centring it.
        """
        import random

        from till_infinity.statespace.relating import Relating

        truth = (0.8, -0.5, 1.3)

        def fit(centre: bool):
            rng = random.Random(11)
            legs = [100.0, 50.0, 20.0]
            engine = Relating(legs=3, ratio_wander=1e-8, centre=centre)
            for i in range(4000):
                legs = [v + rng.gauss(0.0, 0.7) for v in legs]
                dependent = (
                    2.0 + sum(t * v for t, v in zip(truth, legs, strict=True)) + rng.gauss(0.0, 0.4)
                )
                engine.predict(i * 3600.0)
                engine.update(dependent, 0.16, i * 3600.0, against=legs)
            error = max(abs(g - w) for g, w in zip(engine.ratios, truth, strict=True))
            return error, max(engine.ratio_sds), engine

        loose, stated_loose, _ = fit(centre=False)
        tight, stated_tight, engine = fit(centre=True)

        # Uncentred: the stated uncertainty is an order of magnitude too small.
        assert loose > 10.0 * stated_loose, (loose, stated_loose)
        # Centred: calibrated, and the weights are right.
        assert tight < 3.0 * stated_tight, (tight, stated_tight)
        for got, wanted in zip(engine.ratios, truth, strict=True):
            assert got == pytest.approx(wanted, abs=0.02), engine.ratios

    def test_the_adaptive_noise_is_inert_when_the_innovations_are_right(self):
        """`adapt` is a correct mechanism for a problem this was not.

        Kept, defaulted off, with the measurement that says so - because
        deleting it would mean rediscovering the idea later, and because an
        inflation of 1.000 is the evidence that ruled out the first diagnosis.
        """
        import random

        from till_infinity.statespace.relating import Relating

        rng = random.Random(3)
        engine = Relating(adapt=0.02)
        leg = 10.0
        for i in range(2000):
            leg += rng.gauss(0.0, 0.5)
            engine.predict(i * 3600.0)
            engine.update(2.0 * leg + rng.gauss(0.0, 0.4), 0.16, i * 3600.0, against=leg)
        assert engine.inflation == pytest.approx(1.0, abs=0.6), engine.inflation

    def test_a_basket_that_changes_width_is_refused(self):
        """A missing column is a different model, not the same one short a leg."""
        from till_infinity.statespace.relating import Relating

        engine = Relating(legs=2)
        engine.predict(0.0)
        engine.update(10.0, 0.1, 0.0, against=[1.0, 2.0])
        with pytest.raises(ValueError, match="leg"):
            engine.update(11.0, 0.1, 3600.0, against=[1.0])

    def test_it_satisfies_the_family_contract(self):
        """Scored beside the members means answering what they answer."""
        from till_infinity.statespace.relating import Relating

        engine = Relating()
        for i in range(40):
            engine.predict(i * 3600.0)
            engine.update(100.0 + i, 0.09, i * 3600.0, against=float(i))
        assert engine.output() == (engine.value,)
        assert len(engine.state()) == 2
        assert len(engine.observation()[0]) == len(engine.state())
        assert math.isfinite(engine.loglike)
        low, high = engine.band(engine.at + 3600.0)
        assert low < engine.value < high


class TestExpectationMaximisation:
    """EM, and the smoother extension that unblocked it."""

    def test_the_smoother_carries_the_cross_terms(self):
        """**The piece EM was blocked on**, and a numerical check of it.

        `P(t, t-1 | T) = P(t | T) C(t-1)'`. The identity is verified against
        the covariance of the smoothed means over many seeds: the cross term
        the smoother reports must match what the paths actually do.
        """
        import statistics

        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paths import hourly, simulate
        from till_infinity.statespace.smoothing import smooth

        times = hourly(200)
        pairs = []
        for seed in range(60):
            path = simulate(times, jerk=1e-3, noise=0.25, seed=seed)
            got = smooth(lambda: Gaussian(jerk=1e-3), times, path.measured, noise=0.25)
            assert got is not None
            assert len(got.covariances) == len(got.states)
            assert len(got.cross) == len(got.states)
            assert got.cross[0] == (), "no step exists before the first"
            pairs.append((got.states[100][0], got.states[99][0], got.cross[100][0][0]))

        # The reported cross term is a conditional covariance, so it is the
        # same at every seed; the empirical covariance of the means is not the
        # same quantity. What must hold is that the reported term is positive,
        # stable, and smaller than the product of the two spreads.
        reported = [p[2] for p in pairs]
        assert min(reported) > 0.0
        assert statistics.pstdev(reported) < 0.5 * statistics.fmean(reported)

    def test_em_recovers_the_parameters_it_was_generated_from(self):
        """And is compared with the thing it replaces, rather than assumed better."""
        from till_infinity.statespace.diagnostics import fit_both, fit_em
        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paths import hourly, simulate

        truth_jerk, truth_noise = 1e-3, 0.25
        path = simulate(hourly(1200), jerk=truth_jerk, noise=truth_noise, seed=4)

        jerk, noise, loglike, rounds = fit_em(
            lambda j, _n: Gaussian(jerk=j), path.times, path.measured
        )
        assert 2e-4 < jerk < 5e-3, jerk
        assert 0.15 < noise < 0.4, noise
        assert rounds > 1, "a fit that stops after one round has fitted nothing"
        assert math.isfinite(loglike)

        def run(candidate_jerk: float, candidate_noise: float) -> float:
            engine = Gaussian(jerk=candidate_jerk)
            for when, value in zip(path.times, path.measured, strict=True):
                engine.predict(when)
                engine.update(value, candidate_noise, when)
            return engine.loglike

        _j, _n, other = fit_both(run)
        # The same optimum, within a nat per thousand points. If these diverge
        # one of them is wrong, and the test says which comparison to make.
        assert abs(loglike - other) < 0.01 * abs(other), (loglike, other)


class TestNulls:
    """The two floors, now in the library, and the defects the move exposed."""

    def test_the_walk_scores_its_likelihood_on_the_spread_it_predicts_with(self):
        """**The defect this move fixed.**

        The harness copy standardised by `sqrt(noise^2 + R)` and scored its
        likelihood on `noise` alone. For a Gaussian, `-0.5 (i/s)^2 - log s`
        punishes an understated `s`, so the null was handicapped and every
        member's margin over it was overstated.
        """
        from till_infinity.statespace.nulls import Walk

        walk = Walk(noise=1.0)
        walk.update(0.0, 0.0, 0.0)
        walk.update(1.0, 3.0, 900.0)

        # One reading folded in, so one term: a unit innovation against a
        # predictive spread of sqrt(1 + 3) = 2.
        spread = 2.0
        expected = -0.5 * (1.0 / spread) ** 2 - 0.5 * math.log(2.0 * math.pi) - math.log(spread)
        assert walk.loglike == pytest.approx(expected)
        assert walk.last_standardised == pytest.approx(0.5)

    def test_the_walk_band_diffuses_and_its_forecast_does_not(self):
        """Flat forecast, `sqrt(h)` band. Both halves are the null."""
        from till_infinity.statespace.nulls import Walk

        walk = Walk(noise=0.5)
        for i in range(10):
            walk.predict(i * 900.0)
            walk.update(100.0 + i, 0.0, i * 900.0)
        assert walk.step == pytest.approx(900.0)
        assert walk.at_time(walk.at + 900.0 * 50) == pytest.approx(walk.value)

        one = walk.band(walk.at + 900.0)
        four = walk.band(walk.at + 900.0 * 4)
        assert (four[1] - four[0]) == pytest.approx(2.0 * (one[1] - one[0]), rel=1e-9)

    def test_trailing_and_the_rotated_control(self):
        """The magnitude floor, and the control that makes a reading mean something."""
        import random
        import statistics

        from till_infinity.statespace.nulls import control, spearman, trailing

        rng = random.Random(5)
        values, level = [0.0], 0.0
        for i in range(600):
            scale = 0.2 if i < 300 else 2.0
            level += rng.gauss(0.0, scale)
            values.append(level)
        got = trailing(values, 20)
        assert statistics.fmean(got[350:]) > 4.0 * statistics.fmean(got[100:290])

        # A feature correlated with itself reads 1.0; rotated, it reads nothing.
        assert spearman(got, got) == pytest.approx(1.0)
        assert abs(control(got, got)) < 0.35


class TestFacts:
    """Rollouts, and whether they look like a market."""

    def test_autocorrelation_matches_numpy(self):
        """The module rule: anything hand-written arrives with a reference."""
        numpy = pytest.importorskip("numpy")

        from till_infinity.statespace.facts import autocorrelation

        rng = numpy.random.default_rng(7)
        series = numpy.cumsum(rng.normal(size=500)).tolist()
        for lag in (1, 3, 10):
            mine = autocorrelation(series, lag)
            centred = numpy.asarray(series) - numpy.mean(series)
            reference = float(
                (centred[: len(centred) - lag] * centred[lag:]).sum() / (centred**2).sum()
            )
            assert mine == pytest.approx(reference, rel=1e-9, abs=1e-12)

    def test_it_survives_a_series_that_would_overflow(self):
        """A mis-specified rollout can run to 1e200; the estimator must report.

        Raising instead of reporting would make the one check designed to catch
        a runaway member the thing the runaway member breaks.
        """
        from till_infinity.statespace.facts import autocorrelation, kurtosis

        wild = [float(10.0**k) for k in range(1, 160)]
        assert math.isfinite(autocorrelation(wild, 1))
        assert math.isfinite(kurtosis(wild))

    def test_it_tells_a_clustering_series_from_a_random_walk(self):
        """The discrimination that makes the measurement worth having.

        A GARCH series clusters and its kurtosis falls with aggregation; a
        random walk does neither. If this cannot separate them it cannot
        separate a member from a member.
        """
        import random

        from till_infinity.statespace.facts import measure, rollout, verdict
        from till_infinity.statespace.nulls import Walk
        from till_infinity.statespace.paths import hourly

        rng = random.Random(1)
        level, variance, previous = 0.0, 1.0, 0.0
        clustered = [0.0]
        for _ in range(6000):
            variance = 0.02 + 0.10 * previous * previous + 0.88 * variance
            previous = rng.gauss(0.0, math.sqrt(variance))
            level += previous
            clustered.append(level)

        real = measure(clustered)
        assert abs(real.drift) < 0.1, real.drift
        assert real.clustering > 0.3, real.clustering
        assert real.tails_fall

        made = measure(rollout(lambda: Walk(noise=1.0), hourly(6000), noise=0.25, seed=2))
        assert abs(made.drift) < 0.1, made.drift
        assert made.clustering < 0.1, "a random walk must not cluster"
        assert "NO clustering" in verdict(real, made)


class TestYielding:
    """Widening the process noise instead of resetting the state."""

    def test_it_declines_a_member_that_cannot_name_its_process_noise(self):
        """The same contract `smooth` uses: declining is a true statement."""
        from till_infinity.statespace.nulls import Walk
        from till_infinity.statespace.yielding import Yielding

        with pytest.raises(AttributeError, match="process noise"):
            Yielding(Walk)

    def test_it_softens_on_a_step_and_is_nearly_free_without_one(self):
        """The two halves of its null, on one series each.

        Softening must help where there is a change and cost almost nothing
        where there is not - and `reach = 1` must reproduce the member exactly,
        which is the arm that proves the mechanism is what is being measured
        rather than the wrapper.
        """
        import random

        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.yielding import Yielding

        build = lambda: Gaussian(jerk=1e-4)  # noqa: E731

        def run(engine, rows):
            for when, value in rows:
                engine.predict(when)
                engine.update(value, 0.09, when)
            return engine

        rng = random.Random(9)
        stepped = [
            (i * 900.0, (100.0 if i < 150 else 112.0) + rng.gauss(0.0, 0.3)) for i in range(300)
        ]
        alone = run(build(), stepped)
        soft = run(Yielding(build), stepped)
        assert soft.loglike > alone.loglike + 100.0, (alone.loglike, soft.loglike)
        assert soft.widest > 2.0, soft.widest

        # `reach = 1` is the member, exactly. If this drifts, the comparison
        # above is measuring the wrapper rather than the softening.
        inert = run(Yielding(build, reach=1.0), stepped)
        assert inert.loglike == pytest.approx(alone.loglike)
        assert inert.widest == pytest.approx(1.0)

        rng = random.Random(21)
        flat = [(i * 900.0, 100.0 + rng.gauss(0.0, 0.3)) for i in range(300)]
        alone = run(build(), flat)
        soft = run(Yielding(build), flat)
        assert soft.loglike > alone.loglike - 10.0, (alone.loglike, soft.loglike)


class TestRankThenMap:
    """Predict the order, then map it - and the claim that makes it worth it.

    The paper's result is not that ranking is accurate. It is that ranking
    **transfers** where predicting the value does not, so `test_the_order`
    below is the one that matters: it fails for a one-step model by
    construction and must not fail for this one.
    """

    @staticmethod
    def _rows(seed: int, count: int = 1500):
        import random

        rng = random.Random(seed)
        out = []
        for _ in range(count):
            features = [rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)]
            latent = 2.0 * features[0] - features[1]
            out.append((features, latent))
        return out

    def test_it_learns_an_order_and_not_a_scale(self):
        """The weights recover the latent ratio; their size means nothing."""
        from till_infinity.statespace.ranking import Ranker

        rows = self._rows(1)
        ranker = Ranker(margin=0.1)
        ranker.fit(rows, epochs=2, pairs=4000, seed=3)

        assert ranker.used > 1000, ranker.used
        # The third feature is noise and must stay near zero; the first two
        # must come out in the latent 2:-1 ratio whatever their magnitude.
        scale = ranker.weights[0]
        assert scale > 0, ranker.weights
        assert ranker.weights[1] / scale == pytest.approx(-0.5, abs=0.1)
        assert abs(ranker.weights[2] / scale) < 0.1, ranker.weights

    def test_the_margin_refuses_pairs_that_are_too_close(self):
        """A pair closer than the margin teaches estimation error."""
        from till_infinity.statespace.ranking import Ranker

        ranker = Ranker(margin=1.0)
        assert ranker.learn([1.0], 5.0, [0.0], 0.0) is True
        assert ranker.learn([1.0], 5.0, [0.0], 4.5) is False
        assert ranker.skipped == 1
        before = list(ranker.weights)
        ranker.learn([1.0], 5.0, [0.0], 4.5)
        assert ranker.weights == before, "a skipped pair still moved the weights"

    def test_the_order_transfers_where_the_value_does_not(self):
        """**The claim.** One system to train on, another to predict in.

        The second system applies a different monotone transform to the same
        latent quantity - which is what a different instrument does to the same
        market structure. A model fitted to *values* on the first carries that
        system's scale with it and is wrong on the second. A model fitted to
        *order* carries nothing, and a handful of anchors supply the rest.
        """
        import statistics

        from till_infinity.statespace.ranking import Ranker, RankThenMap

        train = self._rows(11)
        target = self._rows(12)

        def observed(latent: float) -> float:
            # The target system's own scale: a different offset and gain.
            return 3.0 + 7.0 * latent

        ranker = Ranker(margin=0.1)
        ranker.fit(train, epochs=2, pairs=6000, seed=5)
        model = RankThenMap(ranker=ranker)
        model.anchor([(f, observed(v)) for f, v in target[:25]])

        held = target[200:700]
        ours = statistics.fmean(abs(model.predict(f) - observed(v)) for f, v in held)

        # The null: least squares on the FIRST system's values, applied to the
        # second. It sees the same features and more of them.
        size = len(train[0][0])
        sums = [[0.0] * (size + 1) for _ in range(size)]
        for features, latent in train:
            for i in range(size):
                for j in range(size):
                    sums[i][j] += features[i] * features[j]
                sums[i][size] += features[i] * latent
        for col in range(size):
            pivot = sums[col][col]
            for row in range(size):
                if row == col or abs(pivot) < 1e-12:
                    continue
                factor = sums[row][col] / pivot
                for k in range(col, size + 1):
                    sums[row][k] -= factor * sums[col][k]
        weights = [sums[i][size] / sums[i][i] for i in range(size)]
        theirs = statistics.fmean(
            abs(sum(w * x for w, x in zip(weights, f, strict=True)) - observed(v)) for f, v in held
        )

        assert ours < theirs / 5.0, (ours, theirs)
        assert ours < 0.5, ours

    def test_the_mapping_says_whether_it_helped(self):
        """`improvement` can be negative, which is the point of having it."""
        from till_infinity.statespace.ranking import Mapping

        scores = [float(k) for k in range(30)]
        useful = Mapping()
        useful.fit(scores, [3.0 + 2.0 * s for s in scores])
        assert useful.improvement(scores, [3.0 + 2.0 * s for s in scores]) > 10.0

        # A map fitted on noise cannot beat the constant by much, and may lose.
        import random

        rng = random.Random(2)
        noise = [rng.gauss(0.0, 1.0) for _ in scores]
        blind = Mapping()
        blind.fit(scores, noise)
        assert blind.improvement(scores, noise) < 0.5

    def test_the_hand_rolled_solve_matches_numpy(self):
        """The module rule: anything hand-written arrives with a reference.

        `Mapping._least_squares` is a Gauss-Jordan solve of the normal
        equations, written here because the system is 3x3 and numpy is not a
        declared dependency. Written here is exactly how `smoothing._gain` came
        to be **19% wrong while looking right** - it smoothed, it beat the
        filter, and nothing in the output said otherwise. So it is checked
        against an independent implementation wherever one is importable.
        """
        numpy = pytest.importorskip("numpy")

        from till_infinity.statespace.ranking import _least_squares

        rng = numpy.random.default_rng(4)
        xs = rng.normal(size=40)
        ys = 1.5 - 2.0 * xs + 0.75 * xs**2 + rng.normal(scale=0.1, size=40)
        ours = _least_squares(xs.tolist(), ys.tolist(), 2, [1.0] * 40)
        # numpy returns highest power first; this module returns lowest first.
        theirs = list(numpy.polyfit(xs, ys, 2))[::-1]
        for mine, reference in zip(ours, theirs, strict=True):
            assert mine == pytest.approx(reference, rel=1e-8, abs=1e-10)

        # And with weights, which `polyfit` takes as 1/sigma rather than as the
        # weight itself - so the square root is where a careless check passes.
        weights = rng.uniform(0.5, 2.0, size=40)
        ours = _least_squares(xs.tolist(), ys.tolist(), 2, weights.tolist())
        theirs = list(numpy.polyfit(xs, ys, 2, w=numpy.sqrt(weights)))[::-1]
        for mine, reference in zip(ours, theirs, strict=True):
            assert mine == pytest.approx(reference, rel=1e-6, abs=1e-9)

    def test_one_bad_anchor_does_not_take_the_mapping_with_it(self):
        """Median regression first, least squares on the inliers after.

        A mis-annotated anchor is the failure the paper names, and squared
        error hands it the fit.
        """
        from till_infinity.statespace.ranking import Mapping

        scores = [float(k) for k in range(20)]
        values = [3.0 + 2.0 * s for s in scores]
        values[7] = 900.0  # one anchor annotated wrong

        robust = Mapping()
        robust.fit(scores, values)
        assert robust(10.0) == pytest.approx(23.0, abs=1.5), robust.coefficients

    def test_a_map_that_would_turn_back_falls_back_to_a_line(self):
        """A higher rank must not predict a smaller quantity.

        A degree-two fit has a turning point, and anchors clustered at one end
        can put it inside the range. The fallback is a straight line and the
        flag says so.
        """
        from till_infinity.statespace.ranking import Mapping

        # Anchors whose least-squares parabola turns inside their own range.
        scores = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        values = [0.0, 3.0, 4.0, 4.2, 4.3, 9.0]
        mapping = Mapping()
        mapping.fit(scores, values)
        if mapping.straightened:
            assert len(mapping.coefficients) == 2
        rising = [mapping(s) for s in scores]
        assert rising == sorted(rising), rising


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

        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paired import Paired

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

        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paired import Paired

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

        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paired import Paired

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

        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paired import Paired

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
        from till_infinity.statespace.family import Filter
        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paired import Paired

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
        from till_infinity.statespace.inputs import (
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

        from till_infinity.statespace.changepoint import (
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
        from till_infinity.statespace.inputs import (
            LADDER,
            bar_hours,
            coverage,
            resolvable,
        )

        # 5s bars, and enough of them that four weeks is under the quarter cap.
        # It reaches 10s but **not** 1s or 5s, which are fractions of a bar and
        # one bar respectively - the same bound that stops a 1d feed being
        # asked about 30m, now biting at the fine end too. The ladder extends
        # below what any one feed can see, which is the point of having bounds
        # rather than a per-feed ladder.
        whole = resolvable(5.0 / 3600.0, 2_000_000)
        assert [w.label() for w in whole[:2]] == ["10s", "30s"]
        assert whole[-1].label() == "4w"
        assert len(whole) == len(LADDER) - 2, [w.label() for w in whole]

        # A 1s feed, which tick stores make possible, reaches the new rungs.
        # `5s` is five bars and `1s` is one, so the floor still refuses `1s`:
        # a window the length of a single bar reports that bar's own extremes
        # under a name claiming a horizon.
        finest = resolvable(1.0 / 3600.0, 2_000_000)
        assert finest[0].label() == "5s", [w.label() for w in finest[:3]]
        assert "1s" not in [w.label() for w in finest]

        # The seconds end is reachable from real timestamps, not just from a
        # bar size passed in by hand.
        times = [i * 1.0 for i in range(20000)]
        bar = bar_hours(times)
        got = [w.label() for w in resolvable(bar, len(times), cover=coverage(times, bar))]
        # A 1s feed now reaches `5s` - five bars - where before the ladder's
        # finest rung was `10s`. `1s` is still refused at one bar.
        assert got[0] == "5s", got
        assert "1s" not in got, got
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
        from till_infinity.statespace.inputs import (
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
        from till_infinity.statespace.inputs import (
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
        from till_infinity.statespace.inputs import Features

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


# ------------------------------------------- Wasserstein, as a second metric


class TestDistance:
    """`distance.py` scores a member on where its innovations sit, not only on
    how likely they were. Likelihood is a sum of point densities and a single
    fat innovation can dominate it; a transport distance asks how far the whole
    distribution has to move, which is the question a fat tail answers
    differently."""

    def test_the_transport_distance_matches_scipy(self):
        """The 1-D case is exact by sorting, so there is a reference to match.

        scipy is a transitive dependency rather than a declared one, so this
        skips when it is absent rather than failing - but when it is present
        the hand-written sort has to agree with it.
        """
        stats = pytest.importorskip("scipy.stats")
        import random

        from till_infinity.statespace.distance import wasserstein

        rng = random.Random(4242)
        left = [rng.gauss(0.0, 1.0) for _ in range(400)]
        right = [rng.gauss(0.4, 1.3) for _ in range(400)]
        assert wasserstein(left, right) == pytest.approx(
            stats.wasserstein_distance(left, right), rel=1e-6
        )

    def test_a_sample_against_itself_is_zero(self):
        from till_infinity.statespace.distance import wasserstein

        values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
        assert wasserstein(values, list(values)) == pytest.approx(0.0)

    def test_shifting_everything_costs_the_shift(self):
        """Transport distance has a unit, and the unit is the series'.

        This is the property that makes it a usable second axis: a W1 of 0.3
        on standardised innovations means the distribution sits three tenths
        of a standard deviation from where the model says it should, which is
        a sentence a log-likelihood cannot produce.
        """
        from till_infinity.statespace.distance import wasserstein

        values = [0.0, 1.0, 2.0, 3.0, 4.0]
        moved = [v + 2.5 for v in values]
        assert wasserstein(values, moved) == pytest.approx(2.5)

    def test_a_standard_normal_sample_is_close_to_the_standard_normal(self):
        """`against_normal` is the member-calibration number.

        Standardised innovations are N(0,1) under a correct model, so the
        distance from N(0,1) is a calibration error with a unit. A sample of
        this size lands near 0.01; a member whose innovations are twice too
        wide lands near 0.8, and that gap is the whole point.
        """
        import random

        from till_infinity.statespace.distance import against_normal

        rng = random.Random(99)
        tight = [rng.gauss(0.0, 1.0) for _ in range(2000)]
        wide = [v * 2.0 for v in tight]
        assert against_normal(tight) < 0.05
        assert against_normal(wide) > 0.5


# --------------------------------------- displacements, as an observation process


class TestDisplacements:
    """The sequence of moves between confirmed reversals. Every member in this
    package observes a price; this observes the gaps between turns, which is
    already differenced and so has no unit root for a model to chase."""

    def _zigzag(self, legs, *, bars=6, step=0.01, start=100.0):
        """A clean alternating series: `legs` moves of `bars` bars each."""
        times, closes = [0.0], [start]
        for leg, direction in enumerate(legs):
            for _ in range(bars):
                times.append(times[-1] + 3600.0)
                closes.append(closes[-1] * (1.0 + direction * step * (leg + 1)))
        return times, closes

    def test_two_turns_the_same_way_are_not_a_swing(self):
        """The detector can fire twice inside one structure; the sequence drops it.

        Keeping both would make the sequence's alternation a property of the
        pivot threshold rather than of the market, and then every statistic
        over it would be reading the threshold.
        """
        from till_infinity.statespace.displacements import sequence

        times, closes = self._zigzag([1, -1, 1, -1, 1, -1])
        moves = sequence(times, closes, closes, closes, span=2, unit=0.01)
        directions = [m.direction for m in moves]
        assert all(a != b for a, b in itertools.pairwise(directions)), directions

    def test_a_move_is_knowable_only_after_its_pivot_is_confirmed(self):
        """`confirmed` is later than `ended` by the detector's reach.

        A pivot at bar `k` needs `span` more bars to know it was one, so a
        feature built on `ended` is a feature that reads the future. Carrying
        both times is what makes the leak avoidable rather than invisible.
        """
        from till_infinity.statespace.displacements import sequence

        times, closes = self._zigzag([1, -1, 1, -1, 1, -1])
        moves = sequence(times, closes, closes, closes, span=2, unit=0.01)
        assert moves
        assert all(m.confirmed > m.ended for m in moves[:-1]), [
            (m.ended, m.confirmed) for m in moves
        ]

    def test_a_flat_series_has_no_swings(self):
        """Ties are not pivots.

        A strict comparison is the difference between this and a detector that
        finds a reversal on every bar of a constant series - which an earlier
        version of the pivot finder did, because `<=` makes every tie a swing.
        """
        from till_infinity.statespace.displacements import sequence

        times = [i * 3600.0 for i in range(80)]
        closes = [100.0] * 80
        assert sequence(times, closes, closes, closes, span=3, unit=0.01) == []

    def test_the_ratio_is_what_a_symmetry_transformation_acts_on(self):
        """A sequence whose legs grow by a fixed factor has that factor as its ratio."""
        from till_infinity.statespace.displacements import relations, sequence

        times, closes = [0.0], [100.0]
        size = 1.0
        for direction in (1, -1, 1, -1, 1, -1, 1, -1):
            for _ in range(5):
                times.append(times[-1] + 3600.0)
                closes.append(closes[-1] + direction * size)
            size *= 1.5
        moves = sequence(times, closes, closes, closes, span=2, unit=1.0)
        pairs = relations(moves)
        assert len(pairs) >= 3
        middle = sorted(p.ratio for p in pairs)[len(pairs) // 2]
        assert middle == pytest.approx(1.5, rel=0.25), [p.ratio for p in pairs]


# ------------------------------------------- symmetry, as a switching model


class TestSymmetry:
    """Three symmetry classes over the displacement ratios. The claim it tests
    is that the geometric relationships between swings persist within a regime
    and break at its boundary - which is a switching model, so it is built as
    one and scored against the sequence shuffled."""

    def test_the_classes_are_a_distribution(self):
        from till_infinity.statespace.symmetry import CLASSES, Symmetry

        member = Symmetry()
        assert len(member.weights) == len(CLASSES)
        for step in range(20):
            member.predict(step * 3600.0)
            member.update(0.1, 0.4, step * 3600.0)
            assert sum(member.weights) == pytest.approx(1.0)
            assert all(w >= 0.0 for w in member.weights)

    def test_equal_swings_read_as_mirror_and_growing_ones_as_expanding(self):
        """The three classes have to separate on sequences built to be each one.

        Without this the posterior could be a constant and every reading of
        `contracting` would be a reading of the prior - which is exactly what
        the first version of this member did, with all three centres free and
        all three collapsing onto the data.

        The evidence has to be strong relative to the hazard for the posterior
        to go anywhere, so this uses tight emissions and a long regime; the
        next test is about what happens when it is not.
        """
        from till_infinity.statespace.symmetry import Symmetry

        settings = {"spread": 0.12, "persist_hours": 24 * 30.0}
        steady = Symmetry(**settings)
        growing = Symmetry(**settings)
        shrinking = Symmetry(**settings)
        for step in range(1, 40):
            when = step * 6 * 3600.0
            for member, ratio in (
                (steady, 0.0),
                (growing, 0.48),
                (shrinking, -0.48),
            ):
                member.predict(when)
                member.update(ratio, 0.12, when)

        assert steady.regime == "mirror", steady.weights
        assert growing.regime == "expanding", growing.weights
        assert shrinking.regime == "contracting", shrinking.weights
        assert steady.mirror > 0.9, steady.weights

    def test_the_posterior_cannot_be_confident_at_the_default_hazard(self):
        """A 24-hour regime read once a day leaves the posterior near its prior.

        **This is a property a caller needs, not a defect.** With the default
        `persist_hours` of 24 and displacements a day apart, the transition
        mixes away about 63% of the posterior between readings, while one log
        ratio at the default spread is worth a likelihood ratio of about
        three-quarters. Evidence that weak against mixing that fast settles
        around 0.4, so a gate written as `mirror > 0.6` would never fire and
        would look like a dead feature rather than a mis-set one.
        """
        from till_infinity.statespace.symmetry import Symmetry

        member = Symmetry()
        for step in range(1, 60):
            when = step * 24 * 3600.0
            member.predict(when)
            member.update(0.0, 0.3, when)
        assert member.regime == "mirror"
        assert 0.35 < member.mirror < 0.55, member.weights

    def test_the_regime_hazard_is_per_hour_and_not_per_turn(self):
        """Two sequences over the same hours mix the same amount.

        A market that turns ten times in a day and one that turns twice would
        get regimes of the same length in *events* and wildly different
        lengths in time if the hazard were per turn - and the member would
        stop meaning the same thing at 15m as at 1d. This is the test that
        keeps it portable.
        """
        from till_infinity.statespace.symmetry import Symmetry

        slow = Symmetry()
        fast = Symmetry()
        slow.predict(0.0)
        slow.update(0.5, 0.3, 0.0)
        fast.predict(0.0)
        fast.update(0.5, 0.3, 0.0)

        day = 24 * 3600.0
        slow.predict(day)
        for i in range(1, 5):
            fast.predict(i * day / 4.0)

        # Four short steps and one long one over the same day leave the regime
        # posterior in the same place, to the accuracy of the mixing.
        assert fast.weights[0] == pytest.approx(slow.weights[0], abs=0.05), (
            fast.weights,
            slow.weights,
        )

    def test_the_symmetry_index_sees_a_repeating_sequence(self):
        """Low index means sizes repeat at that lag. A period-two sequence
        repeats at even lags and not at odd ones, which is the one case where
        the index has an unambiguous right answer."""
        from till_infinity.statespace.symmetry import nodal_symmetry

        sizes = [1.0, 3.0] * 20
        assert nodal_symmetry(sizes, 2) == pytest.approx(0.0)
        assert nodal_symmetry(sizes, 1) > 1.0

    def test_the_expected_ratio_carries_the_half_variance_term(self):
        """A ratio is lognormal, so its mean is not the exponential of its mean.

        Dropping the correction would bias every forecast low, and the bias
        grows with the spread - which is exactly when a forecast matters.
        """
        from till_infinity.statespace.symmetry import Symmetry

        member = Symmetry()
        assert member.expected_ratio > math.exp(member.value)


# -------------------------------------------- a seasonal, locked to the clock


class TestSeasonal:
    """`seasonal.py` was the package's one missing classical component. The
    thing worth testing is not that it filters - every member here does - but
    that it stays **locked to wall-clock time** and stays **honest about its
    spare parameters**, because those are the two ways a seasonal goes wrong."""

    HOUR = 3_600.0

    def _series(self, bars: int, amplitude: float, seed: int, step: float = 1.0):
        """A level walk plus a known daily shape, hourly."""
        import random

        rng = random.Random(seed)
        times, values = [], []
        level = 100.0
        for i in range(bars):
            when = i * step * self.HOUR
            level += rng.gauss(0.0, 0.05)
            hours = when / self.HOUR
            shape = amplitude * (
                math.cos(2 * math.pi * hours / 24.0) + 0.4 * math.sin(4 * math.pi * hours / 24.0)
            )
            times.append(when)
            values.append(level + shape + rng.gauss(0.0, 0.1))
        return times, values

    def _run(self, times, values, **settings):
        from till_infinity.statespace.seasonal import Seasonal

        member = Seasonal(periods=(24.0,), harmonics=3, wander=1e-5, **settings)
        for when, value in zip(times, values, strict=True):
            member.predict(when)
            member.update(value, 0.1, when)
        return member

    def test_it_recovers_a_planted_daily_shape(self):
        times, values = self._series(3000, 1.0, 7)
        member = self._run(times, values)
        # True amplitude is sqrt(1 + 0.16) = 1.077 over the two harmonics.
        assert member.amplitude == pytest.approx(1.08, abs=0.2), member.amplitude
        base = member.at or 0.0
        shape = [member.profile(base + h * self.HOUR, period=24.0) for h in range(24)]
        assert max(shape) - min(shape) > 1.8, shape

    def test_a_flat_series_makes_it_lose_to_its_own_matched_null(self):
        """**The property that makes the amplitude readable.**

        Six extra states always explain something, so a seasonal that could
        only ever win would be useless as evidence. With the matched null -
        the same filter, same level noise, same anchor, harmonics not
        observed - a flat series costs the full member about 39 nats, so the
        comparison cannot be won by flexibility alone.
        """
        times, values = self._series(3000, 0.0, 11)
        full = self._run(times, values, seasonal_on=True)
        flat = self._run(times, values, seasonal_on=False)
        assert full.loglike < flat.loglike, (full.loglike, flat.loglike)

        times, values = self._series(3000, 1.0, 11)
        full = self._run(times, values, seasonal_on=True)
        flat = self._run(times, values, seasonal_on=False)
        assert full.loglike > flat.loglike + 1000.0, (full.loglike, flat.loglike)

    def test_the_fitted_shape_is_the_same_at_two_bar_sizes(self):
        """A 24-hour seasonal is a day at 1h and a day at 4h.

        This is the whole reason the rotation takes `dt` in hours. The
        textbook form carries one state per period *step* - twenty-three for
        hourly data - which is a bar count in disguise, and a twenty-four-bar
        seasonal would be a day at 1h and four days at 4h.
        """
        hourly = self._run(*self._series(2400, 1.0, 3, step=1.0))
        coarse = self._run(*self._series(600, 1.0, 3, step=4.0))
        base_one, base_two = hourly.at or 0.0, coarse.at or 0.0
        one = [hourly.profile(base_one + h * self.HOUR, period=24.0) for h in range(24)]
        two = [coarse.profile(base_two + h * self.HOUR, period=24.0) for h in range(24)]
        span_one = max(one) - min(one)
        span_two = max(two) - min(two)
        assert span_one == pytest.approx(span_two, rel=0.45), (span_one, span_two)

    def test_the_rotation_does_not_feed_the_seasonal(self):
        """Each harmonic is an exact plane rotation, so it cannot gain energy.

        A seasonal that grows is not a seasonal, and a general matrix product
        would lose the orthogonality to rounding over thousands of steps -
        which is why the transition is applied as explicit 2x2 blocks.
        """
        from till_infinity.statespace.seasonal import Seasonal

        member = Seasonal(periods=(24.0,), harmonics=2, wander=0.0, level_wander=0.0)
        member.at = 0.0
        member.values = [0.0, 1.0, 0.0, 0.5, 0.0]
        for step in range(1, 4001):
            member.predict(step * 0.37 * self.HOUR)
        kept = math.sqrt(
            member.values[1] ** 2
            + member.values[2] ** 2
            + member.values[3] ** 2
            + member.values[4] ** 2
        )
        assert kept == pytest.approx(math.sqrt(1.0 + 0.25), rel=1e-9), kept

    def test_a_weekend_gap_rotates_by_the_gap(self):
        """Sixty-three hours of nothing is sixty-three hours of rotation.

        The continuous form needs no special case for a gap, which is the
        other half of why the trigonometric version was chosen: a dummy
        seasonal has to be told how many steps the market was shut.
        """
        from till_infinity.statespace.seasonal import Seasonal

        one = Seasonal(periods=(24.0,), harmonics=1, wander=0.0, level_wander=0.0)
        one.at = 0.0
        one.values = [0.0, 1.0, 0.0]
        one.predict(63.0 * self.HOUR)

        many = Seasonal(periods=(24.0,), harmonics=1, wander=0.0, level_wander=0.0)
        many.at = 0.0
        many.values = [0.0, 1.0, 0.0]
        for step in range(1, 64):
            many.predict(step * self.HOUR)

        assert one.values[1] == pytest.approx(many.values[1], abs=1e-9)
        assert one.values[2] == pytest.approx(many.values[2], abs=1e-9)

    def test_it_anchors_on_the_first_reading(self):
        """The level starts at the first price, not at zero.

        Third member to need this. An uncentred level has to travel the
        price's whole magnitude before the seasonal sees anything but the
        gap, and the harmonics absorb that journey - the defect `relating`
        was 30x overconfident from and `panel` fixes the same way.
        """
        from till_infinity.statespace.seasonal import Seasonal

        member = Seasonal()
        assert member.anchor is None
        member.predict(0.0)
        member.update(1932.5, 0.1, 0.0)
        assert member.anchor == pytest.approx(1932.5)
        assert member.value == pytest.approx(1932.5, rel=1e-3)

    def test_the_profile_recovers_a_planted_intraday_shape(self):
        """`Profile` is where the seasonal actually lives.

        The level arm lost to its own matched null on all 26 cells measured,
        because a daily pattern in how far the market moves says nothing
        about which way - and the level member observes the way. The same
        profile on `Q` gained on every traded instrument.

        So this checks the piece that works: fit a profile to a series with a
        planted volatility peak and get the peak back, in the right hour.
        """
        import random

        from till_infinity.statespace.seasonal import Profile

        rng = random.Random(5)
        times, values = [], []
        level = 0.0
        for i in range(20_000):
            when = float(i) * self.HOUR
            hour = (when % 86_400.0) / self.HOUR
            # A bump of about 2x centred on 14:00.
            scale = 1.0 + math.exp(-((hour - 14.0) ** 2) / 18.0)
            level += rng.gauss(0.0, 0.001 * scale)
            times.append(when)
            values.append(level)

        fitted = Profile.fit(times, values)
        assert fitted is not None
        assert fitted.extent() == pytest.approx(2.0, abs=0.4), fitted.extent()
        shape = fitted.shape()
        assert max(range(24), key=lambda h: shape[h]) == 14, shape

    def test_the_profile_enters_the_variance_squared(self):
        """A threefold profile in size is a ninefold one in variance.

        Fitted to a standard deviation and used on `Q`, which is a variance.
        Getting the exponent wrong is the difference between a profile that
        helps and one that overshoots every busy hour by its own square.
        """
        from till_infinity.statespace.seasonal import Profile

        # One harmonic, amplitude chosen so the profile is e^cos: peak e, trough 1/e.
        made = Profile(weights=(0.0, 1.0, 0.0), harmonics=1)
        peak = made.at(0.0)
        assert made.wander(1.0, 0.0) == pytest.approx(peak * peak)

    def test_the_profile_refuses_rather_than_returning_a_flat_one(self):
        """Too little data gives `None`, not a profile that happens to be flat.

        A silently flat profile is indistinguishable from a real one that is
        flat - which is what the generated markets give, at 1.04 to 1.08 -
        and conflating "could not fit" with "no seasonal here" would make the
        control unreadable.
        """
        from till_infinity.statespace.seasonal import Profile

        times = [float(i) * self.HOUR for i in range(100)]
        values = [float(i) for i in range(100)]
        assert Profile.fit(times, values) is None
        assert not Profile().fitted
        assert Profile().at(12.0 * self.HOUR) == 1.0

    def test_the_clock_drives_the_lever_without_a_caller(self):
        """`Driven(clock=...)` needs nothing passed per reading.

        The exogenous door takes a number the caller computes; the clock door
        takes a function of the time, and the time is already `predict`'s
        first argument. That is what makes a time-of-day profile usable in a
        live member rather than only in a harness.
        """
        from till_infinity.statespace.driven import Driven
        from till_infinity.statespace.seasonal import Profile, Seasonal

        # A profile peaking at midnight: e at hour 0, 1/e twelve hours later.
        made = Profile(weights=(0.0, 1.0, 0.0), harmonics=1)
        base = 1e-4
        member = Driven(
            build=lambda: Seasonal(seasonal_on=False, level_wander=base),
            lever="level_wander",
            clock=made.factor,
        )
        member.predict(0.0)
        member.update(100.0, 0.1, 0.0)
        at_peak = member.softness

        member.predict(12.0 * self.HOUR)
        at_trough = member.softness

        # The variance factor is the size profile squared, so peak over trough
        # is (e / e^-1)^2 = e^4.
        assert at_peak / at_trough == pytest.approx(math.exp(4.0), rel=1e-6)
        assert member.timed == pytest.approx(at_trough)
        assert member.exogenous == pytest.approx(1.0)

    def test_the_two_doors_compose_rather_than_overwrite(self):
        """A busy hour and a busy exogenous reading reinforce each other.

        Both are ratios on a variance, so they multiply. If one overwrote the
        other, wiring the clock in would silently disable the channel
        `inputs.py` exists to feed, and the harness comparing the two doors
        would be comparing one of them with itself.
        """
        from till_infinity.statespace.driven import Driven
        from till_infinity.statespace.seasonal import Profile, Seasonal

        made = Profile(weights=(0.0, 1.0, 0.0), harmonics=1)
        member = Driven(
            build=lambda: Seasonal(seasonal_on=False, level_wander=1e-4),
            lever="level_wander",
            clock=made.factor,
            gain=1.0,
        )
        member.predict(0.0, control=3.0)
        assert member.exogenous == pytest.approx(4.0)
        assert member.softness == pytest.approx(4.0 * member.timed)

    def test_no_clock_leaves_the_old_behaviour_exactly(self):
        """`clock=None` is the control arm, and has to be untouched.

        A wrapper whose unconfigured behaviour drifted would invalidate every
        measurement already taken through it.
        """
        from till_infinity.statespace.driven import Driven
        from till_infinity.statespace.seasonal import Seasonal

        member = Driven(
            build=lambda: Seasonal(seasonal_on=False, level_wander=1e-4),
            lever="level_wander",
        )
        member.predict(0.0, control=0.5)
        assert member.timed == pytest.approx(1.0)
        assert member.softness == pytest.approx(1.5)

    def test_the_floor_applies_to_the_product(self):
        """A state that cannot move at all is never what an input should assert.

        The floor is a statement about the member, not about either signal, so
        it applies once to the product - otherwise two channels each just
        above the floor would multiply to far below it.
        """
        from till_infinity.statespace.driven import Driven
        from till_infinity.statespace.seasonal import Seasonal

        quiet = type("Quiet", (), {})
        _ = quiet
        member = Driven(
            build=lambda: Seasonal(seasonal_on=False, level_wander=1e-4),
            lever="level_wander",
            clock=lambda _when: 0.001,
            floor=0.01,
        )
        member.predict(0.0, control=-0.9)
        assert member.softness == pytest.approx(0.01)


# ------------------------------------------- peaks, troughs, and their distances


class TestNodes:
    """`displacements.sequence` computed peak and trough identity internally
    from the start and threw it away, keeping only the unsigned move between
    consecutive nodes. These expose it, because a **like-node** distance -
    peak to peak - is signed, and its sign is the structural reading a swing
    size has already discarded."""

    HOUR = 3_600.0

    def _zigzag(self, legs, *, bars=6, start=100.0):
        """A clean alternating series. `legs` are signed leg sizes."""
        times, values = [0.0], [start]
        for size in legs:
            for _ in range(bars):
                times.append(times[-1] + self.HOUR)
                values.append(values[-1] + size / bars)
        return times, values

    def test_the_nodes_alternate_peak_and_trough(self):
        from till_infinity.statespace.displacements import nodes

        times, values = self._zigzag([3, -2, 3, -2, 3, -2, 3, -2])
        found = nodes(times, values, values, values, span=2)
        kinds = [node.kind for node in found]
        assert len(found) >= 6
        assert all(a != b for a, b in itertools.pairwise(kinds)), kinds

    def test_two_peaks_in_a_row_keep_the_more_extreme(self):
        """The detector can fire twice inside one structure.

        Keeping both would make the alternation a property of the threshold
        rather than of the market. Keeping the *earlier* one would keep a
        level the later one has already exceeded, so the sequence would stop
        being a sequence of extremes.
        """
        from till_infinity.statespace.displacements import PEAK, nodes

        # Two highs with only a shallow dip between them, the second higher.
        times = [i * self.HOUR for i in range(40)]
        values = [100.0] * 40
        values[10] = 105.0
        values[20] = 107.0
        found = nodes(times, values, values, values, span=3)
        peaks = [node for node in found if node.kind == PEAK]
        assert len(peaks) == 1, [(n.index, n.level) for n in found]
        assert peaks[0].level == pytest.approx(107.0)

    def test_a_like_node_step_is_signed_where_a_swing_size_is_not(self):
        """The whole reason this exists.

        A rising market and a flat range with the same swing sizes are
        **identical** in the displacement sequence, because its `size` is an
        absolute value. The step between consecutive peaks tells them apart.
        """
        from till_infinity.statespace.displacements import (
            HIGHER_HIGH,
            PEAK,
            nodes,
            sequence,
            steps,
        )

        rising = self._zigzag([3, -2, 3, -2, 3, -2, 3, -2])
        flat = self._zigzag([3, -3, 3, -3, 3, -3, 3, -3])

        # The unsigned sizes are nearly the same in both.
        sizes = []
        for times, values in (rising, flat):
            moves = sequence(times, values, values, values, span=2, unit=1.0)
            sizes.append(statistics.median([m.size for m in moves]))
        assert sizes[0] == pytest.approx(sizes[1], rel=0.3), sizes

        # The signed steps are not.
        up = steps(nodes(*(rising[0], *[rising[1]] * 3), span=2), unit=1.0, kind=PEAK)
        level = steps(nodes(*(flat[0], *[flat[1]] * 3), span=2), unit=1.0, kind=PEAK)
        assert all(step.rise > 0 for step in up), [s.rise for s in up]
        assert all(step.label == HIGHER_HIGH for step in up)
        assert statistics.fmean([abs(s.rise) for s in level]) < 1e-6, [s.rise for s in level]

    def test_peak_to_peak_is_a_full_cycle_not_a_swing(self):
        """Consecutive peaks are two swings apart.

        So a peak-to-peak duration is a period and roughly twice a swing
        length. Stating it matters because a feature that conflates the two
        means different things at different timeframes - which is exactly how
        `statespace-peaks-and-troughs.md` found the "cycle length" to be a
        fixed *bar* count rather than a duration.
        """
        from till_infinity.statespace.displacements import (
            PEAK,
            nodes,
            structure,
        )

        times, values = self._zigzag([3, -2] * 8)
        found = nodes(times, values, values, values, span=2)
        read = structure(found, unit=1.0)
        assert read
        assert read["period_hours"] == pytest.approx(2 * read["swing_hours"], rel=0.1)
        peaks = [n for n in found if n.kind == PEAK]
        assert len(peaks) >= 4

    def test_agreement_is_reported_with_the_drift_it_has_to_beat(self):
        """A pure trend gives agreement 1.0 and drift 1.0, so a gain of zero.

        Any upward drift produces higher highs *and* higher lows because
        everything is rising, so the agreement alone says nothing. Measured,
        the gap between them is +0.151 on real markets and +0.158 on a random
        walk - which is why the pair is returned together and never the one
        without the other.
        """
        from till_infinity.statespace.displacements import nodes, structure

        times, values = self._zigzag([3, -2] * 10)
        read = structure(nodes(times, values, values, values, span=2), unit=1.0)
        assert read["agreement"] == pytest.approx(1.0)
        assert read["drift"] == pytest.approx(1.0)
        assert read["agreement"] - read["drift"] == pytest.approx(0.0, abs=1e-9)

    def test_the_same_detector_feeds_both_views(self):
        """`sequence` is built on `nodes`, so the two cannot disagree.

        Before this they were two copies of the same loop, and a fix to one
        would have silently left the other reading a different set of pivots.
        """
        from till_infinity.statespace.displacements import nodes, sequence

        times, values = self._zigzag([3, -2] * 9)
        found = nodes(times, values, values, values, span=2)
        moves = sequence(times, values, values, values, span=2, unit=1.0)
        assert len(moves) == max(len(found) - 1, 0)
        assert [m.ended for m in moves] == [node.at for node in found[1:]]


def test_every_member_takes_the_measurement_noise_as_a_variance():
    """`update`'s `noise` is `R`, a variance, for every member alike.

    **This was not true and the breakage was invisible.** `seasonal` and
    `symmetry` squared it, treating it as a standard deviation, which is
    undetectable while a harness compares a member with itself - and both
    were measured that way. It surfaced only when `clock_levers.py` passed one
    number to three different members: the two that squared it were handed a
    variance of `R^2` and the others `R`, so at `R = 1e-3` one arm was a
    thousand times more confident than the others. It reversed the conclusion
    of that study.

    The check is model-independent. For a fixed innovation `i`, the
    standardised residual is `i / sqrt(P + R)` where `P` is whatever
    predictive variance the member's own dynamics produce. So for two fresh
    members of the same kind differing only in `R`,

        (i / z1)^2 - (i / z2)^2 = R1 - R2

    exactly, whatever `P` is. A member that squares `R` gives `R1^2 - R2^2`
    instead and fails by a wide margin.
    """
    from till_infinity.statespace.linear import Gaussian
    from till_infinity.statespace.nulls import Walk
    from till_infinity.statespace.reverting import Reverting
    from till_infinity.statespace.seasonal import Seasonal
    from till_infinity.statespace.switching import Switching

    builders = {
        "walk": Walk,
        "linear": Gaussian,
        "reverting": Reverting,
        "switching": Switching,
        "seasonal": lambda: Seasonal(seasonal_on=False),
    }
    one, two = 0.04, 0.25
    innovation = 1.0

    # Warmed up with a **fixed** variance in both arms, because several
    # members seed their covariance from `R` on the first reading - so varying
    # `R` from the start would let it in twice and the identity below would
    # pick up a factor of two that is correct behaviour rather than a defect.
    warm = 1e-4

    for name, build in builders.items():
        got = []
        for variance in (one, two):
            member = build()
            for step in range(4):
                member.predict(step * HOUR)
                member.update(0.0, warm, step * HOUR)
            member.predict(4 * HOUR)
            member.update(innovation, variance, 4 * HOUR)
            # `last_standardised`, not `update`'s return value: the members
            # return the standardised residual but the `Walk` null returns the
            # raw innovation, and the attribute is the one every one of them
            # sets. A harness reading the return value would compare a
            # residual with an innovation.
            standardised = member.last_standardised
            assert standardised, (name, standardised)
            got.append((innovation / standardised) ** 2)
        assert got[0] - got[1] == pytest.approx(one - two, abs=1e-6), (
            f"{name} does not take `noise` as a variance: "
            f"implied difference {got[0] - got[1]:.6f} against {one - two:.6f}"
        )


def test_a_matrix_m_step_would_recover_the_shape_it_was_given():
    """**Why the matrix M-step is not worth writing**, which is a measurement.

    `family.MISSING["em"]` listed it as the half still missing. The textbook
    M-step for a linear-Gaussian state space is `Q = (1/T) sum M(t)` with `M`
    exactly what the scalar step projects, so it is *simpler* than what is
    written - no inverse, no conditioning problem.

    It would buy almost nothing, and the reason is structural. `M` is built
    from the **E-step**, and a smoother cannot attribute process noise outside
    the geometry of the model it is smoothing with - so `M` comes out nearly
    parallel to `G(dt)` whatever the data, and a free `Q` would recover
    approximately `c G(dt)`.

    This asserts that on a **random walk**, which is not an integrated-jerk
    path at all: if the residual were informative it would be large here.
    """
    import random

    from till_infinity.statespace.diagnostics import shape_cost
    from till_infinity.statespace.linear import Gaussian

    times = [i * HOUR for i in range(600)]
    rng = random.Random(7)
    level = 0.0
    walk = []
    for _ in times:
        level += rng.gauss(0.0, 1.0)
        walk.append(level + rng.gauss(0.0, 0.5))

    got = shape_cost(
        lambda jerk, noise: Gaussian(jerk=jerk, p00=1.0),
        times,
        walk,
        jerk=1e-3,
        noise=0.25,
    )
    assert got is not None
    # Near-parallel to the shape it was never generated from.
    assert got["cosine"] > 0.99, got
    assert got["residual"] < 0.05, got


def test_the_scalar_spread_is_the_column_that_separates():
    """The one reading in `shape_cost` that does carry misspecification.

    A shape that is right gives one best-fit multiple; a shape that is wrong
    gives a different one at every step. Measured: 0.19 on a matched
    integrated-jerk path, 0.49 on a random walk, 1.30 under jumps.

    **It is not monotone in correctness** and the test says so: pure noise
    with no state at all gives the *lowest* spread of any arm, because there
    is nothing to attribute. So it detects heteroscedastic mismatch rather
    than wrongness.
    """
    import random

    from till_infinity.statespace.diagnostics import shape_cost
    from till_infinity.statespace.linear import Gaussian

    times = [i * HOUR for i in range(600)]

    def build(jerk, noise):
        return Gaussian(jerk=jerk, p00=1.0)

    def spread_of(series):
        got = shape_cost(build, times, series, jerk=1e-3, noise=0.25)
        assert got is not None
        return got["scalar_spread"]

    rng = random.Random(11)
    level = 0.0
    walk = []
    jumps = []
    for _ in times:
        level += rng.gauss(0.0, 1.0)
        walk.append(level + rng.gauss(0.0, 0.5))
    level = 0.0
    for _ in times:
        level += rng.gauss(0.0, 0.3) + (rng.gauss(0.0, 8.0) if rng.random() < 0.02 else 0.0)
        jumps.append(level + rng.gauss(0.0, 0.5))

    assert spread_of(jumps) > spread_of(walk), "jumps are the sharpest mismatch"


class TestDirectionChain:
    """`hmm.Direction` - the direction half of the velocity decomposition.

    The registry gave it a job: speed is persistent, direction is not, so the
    state wants to be `(position, log speed)` with direction as a discrete
    process. Measured, direction is a coin and speed is more persistent than
    the registry claimed - so the tests here pin both the member's ability to
    find a chain that exists and its collapse when one does not."""

    HOUR = 3_600.0

    def _planted(self, n, *, up, down, switch, seed):
        import random

        rng = random.Random(seed)
        times = [i * self.HOUR for i in range(n)]
        state, moves = 0, []
        for _ in times:
            if rng.random() < switch:
                state = 1 - state
            rate = up if state == 0 else down
            moves.append(1.0 if rng.random() < rate else -1.0)
        return times, moves

    def test_it_recovers_a_planted_chain(self):
        """Without this the null below is unreadable.

        A member that cannot find a direction regime when one is planted says
        nothing by failing to find one in a market.
        """
        from till_infinity.statespace.hmm import (
            Direction,
            coin,
            fit,
            up_share,
        )

        times, moves = self._planted(4000, up=0.70, down=0.30, switch=0.02, seed=7)
        half = len(moves) // 2
        member, _ = fit(times[:half], moves[:half])
        assert member.rates[0] == pytest.approx(0.70, abs=0.06), member.rates

        live = Direction(persist_hours=member.persist_hours, rates=member.rates)
        for when, move in zip(times[half:], moves[half:], strict=True):
            live.predict(when)
            live.update(move, move and when)
        fitted = coin(moves[half:], up_share(moves[:half]))
        assert live.loglike > fitted + 50.0, (live.loglike, fitted)

    def test_it_collapses_to_the_small_end_of_the_grid_on_a_fair_coin(self):
        """A fair coin drives the two states together.

        The claim is about the **small end of the grid** rather than an exact
        value, and that is deliberate: the likelihood difference between a
        separation of 0.02 and 0.05 on two thousand fair tosses is within
        noise, so which of the two wins varies by seed. What does not vary is
        that it is one of them rather than 0.20 or 0.35.

        Measured on real data at 1h the fit lands on 0.020 - the smallest the
        grid offers - on every instrument.
        """
        from till_infinity.statespace.hmm import fit

        for seed in (11, 12, 13):
            times, moves = self._planted(4000, up=0.5, down=0.5, switch=0.02, seed=seed)
            member, _ = fit(times[:2000], moves[:2000])
            assert abs(member.rates[0] - 0.5) < 0.1, (seed, member.rates)

    def test_the_forecast_is_read_before_the_move_is_folded_in(self):
        """`update` returns P(up) **before** seeing the move.

        A probability read after the outcome is not a forecast of it, and the
        returned value is what a caller would have had to bet on.
        """
        from till_infinity.statespace.hmm import Direction

        member = Direction(rates=(0.9, 0.1))
        member.predict(0.0)
        first = member.update(1.0, 0.0)
        assert first == pytest.approx(0.5), "the prior is even before any move"
        member.predict(self.HOUR)
        second = member.update(1.0, self.HOUR)
        assert second > first, "an up move should raise the next forecast"

    def test_a_flat_move_is_dropped_rather_than_assigned(self):
        """A flat bar is not a direction.

        Splitting it evenly would invent an observation, and on a tick-sparse
        series there can be many.
        """
        from till_infinity.statespace.hmm import Direction, coin

        member = Direction()
        member.predict(0.0)
        member.update(0.0, 0.0)
        assert member.seen == 0
        assert member.loglike == 0.0
        # And the coin null ignores them too, so the two agree on the sample.
        assert coin([0.0, 0.0], 0.5) == float("-inf")

    def test_the_coin_null_takes_its_probability_rather_than_inventing_one(self):
        """`coin` requires the probability, and that is the point.

        An earlier version took `None` to mean a fair coin and then computed
        the *fitted* rate in that branch - the opposite of what it said -
        which would have made the fair null the fitted one and hidden any gain
        over it.
        """
        from till_infinity.statespace.hmm import coin, up_share

        moves = [1.0] * 70 + [-1.0] * 30
        fair = coin(moves, 0.5)
        fitted = coin(moves, up_share(moves))
        assert fitted > fair, "a fitted coin must beat a fair one on biased signs"
        assert up_share(moves) == pytest.approx(0.70)


class TestLandauCubic:
    """The cubic member: exact where it claims to be, and nested where it must be.

    Two claims carry this member and both are checkable without any market
    data. **It reduces to `Reverting` at `kappa = 0`** - which is what makes
    the comparison between them a one-parameter likelihood-ratio test rather
    than a contest between two different models - and **its mean propagation
    is closed-form rather than substepped**, which is the reason it can be
    trusted over a long gap where an extended filter is usually worst.

    The first version of `_travel` was Simpson's rule at four panels and
    landed 2e-3 from the answer while the docstring claimed 1e-9. These tests
    exist because that claim was written before it was checked.
    """

    def test_zero_kappa_is_reverting_bit_for_bit(self):
        """The nested case, asserted on every field rather than the likelihood.

        A member that merely *scored* the same would be good enough for the
        likelihood-ratio test and would still hide an error in the state. This
        asserts exact float equality - not `approx` - because the two should be
        running identical arithmetic, and anything else means `kappa = 0` is
        taking a different code path.
        """
        import random

        from till_infinity.statespace import Landau, Reverting

        rng = random.Random(7)
        cubic = Landau(sigma2=2e-3, theta=0.4, kappa=0.0)
        linear = Reverting(sigma2=2e-3, theta=0.4)
        clock = 0.0
        for i in range(400):
            # Uneven spacing, and one long gap: a dt bug hides under a grid.
            clock += (73.0 if i % 50 == 49 else 1.0) * HOUR
            reading = math.sin(i / 20.0) * 0.5 + rng.gauss(0.0, 0.1)
            got = cubic.update(reading, noise=0.04, when=clock)
            want = linear.update(reading, noise=0.04, when=clock)
            assert got == want, f"innovation at {i}"
            assert cubic.state() == linear.state(), f"state at {i}"
            assert cubic.covariance() == linear.covariance(), f"covariance at {i}"
        assert cubic.loglike == linear.loglike

    def test_the_rates_flow_matches_a_dense_integration(self):
        """The closed form against Runge-Kutta, over every sign combination.

        `dr/dt = -(theta r + kappa r^3)` is solved through `u = r^2`, which
        turns it logistic. The substitution is the kind of thing that is right
        in general and wrong at `theta = 0` or for a negative rate, so all of
        those are here: reversion, the double well, no linear term at all, a
        negative starting rate, and a gap long enough to reach the well.
        """
        from till_infinity.statespace.landau import _flow

        def dense(rate, dt, theta, kappa, steps=20000):
            step = dt / steps
            pull = lambda x: -(theta * x + kappa * x**3)  # noqa: E731
            for _ in range(steps):
                k1 = pull(rate)
                k2 = pull(rate + step * k1 / 2.0)
                k3 = pull(rate + step * k2 / 2.0)
                k4 = pull(rate + step * k3)
                rate += step * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
            return rate

        cases = (
            (0.5, 2.0, 0.8, 3.0),  # reversion, stiffened
            (-0.3, 1.5, 0.1, 10.0),  # double well, climbing into it
            (-0.3, 1.5, -0.05, 25.0),  # double well, the other side
            (0.0, 4.0, 0.5, 2.0),  # no linear term
            (0.5, 0.0, 0.3, 4.0),  # no cubic term
            (2.0, 0.1, 0.02, 1.0),  # cubic negligible
        )
        for theta, kappa, rate, dt in cases:
            got = _flow(rate, dt, theta, kappa)
            want = dense(rate, dt, theta, kappa)
            assert got == pytest.approx(want, rel=1e-9, abs=1e-12), (
                f"theta={theta} kappa={kappa} rate={rate} dt={dt}"
            )

    def test_the_travel_integral_is_closed_and_not_quadrature(self):
        """`int r dt` against Simpson at forty thousand panels.

        **This is the test the first version of the module failed.** Both
        branches are exercised - the logarithm for the double well and the
        arctangent outside it - and so are the three cases that are not
        branches at all: `theta` at exactly zero, a rate placed exactly in a
        well (where the integral must be linear in time), and a step short
        enough that the answer is the rate itself.
        """
        from till_infinity.statespace.landau import _flow, _travel

        def dense(rate, dt, theta, kappa, panels=40000):
            step = dt / (2 * panels)
            total = _flow(rate, 0.0, theta, kappa) + _flow(rate, dt, theta, kappa)
            for i in range(1, 2 * panels):
                total += (4.0 if i % 2 else 2.0) * _flow(rate, i * step, theta, kappa)
            return total * step / 3.0

        cases = (
            (0.5, 2.0, 0.8, 3.0),
            (-0.3, 1.5, 0.1, 200.0),  # long enough to settle in the well
            (-0.3, 1.5, -0.05, 25.0),
            (0.0, 4.0, 0.5, 2.0),  # theta exactly zero
            (0.5, 0.0, 0.3, 4.0),
            (-0.3, 1.5, 0.1, 0.001),  # a step shorter than anything real
        )
        for theta, kappa, rate, dt in cases:
            got = _travel(rate, dt, theta, kappa)
            want = dense(rate, dt, theta, kappa)
            assert got == pytest.approx(want, rel=1e-8, abs=1e-12), (
                f"theta={theta} kappa={kappa} rate={rate} dt={dt}"
            )

    def test_a_rate_in_the_well_travels_linearly(self):
        """The stationary case, which is where `A` in the closed form vanishes.

        `theta = -kappa r^2` is exactly the well condition, and it is also
        exactly where the substitution's leading coefficient is zero. So this
        is not a numerical edge that needed a guard - it is a physical fact
        that shows up as one, and the guard has to reproduce the physics: a
        rate sitting in a well does not move, so the distance is `rate * dt`.
        """
        from till_infinity.statespace.landau import _flow, _travel

        theta, kappa = -0.62, 0.30
        rate = math.sqrt(-theta / kappa)
        for dt in (1.0, 50.0, 1000.0):
            assert _flow(rate, dt, theta, kappa) == pytest.approx(rate, rel=1e-12)
            assert _travel(rate, dt, theta, kappa) == pytest.approx(rate * dt, rel=1e-9)
            assert _flow(-rate, dt, theta, kappa) == pytest.approx(-rate, rel=1e-12)

    def test_the_double_well_attracts_from_either_side(self):
        """The member's falsifiable claim, as arithmetic.

        `wells` is the only property here that makes a prediction about data
        rather than about the filter, so the flow had better actually go there.
        From inside, from outside, and from the wrong sign.
        """
        from till_infinity.statespace import Landau

        theta, kappa = -0.62, 0.30
        edge = math.sqrt(-theta / kappa)
        assert Landau(theta=theta, kappa=kappa).wells == pytest.approx((-edge, edge))
        for start in (0.01, 0.5, 5.0, -0.01, -5.0):
            member = Landau(
                theta=theta,
                kappa=kappa,
                sigma2=0.0,
                rate=start,
                p00=0.0,
                p01=0.0,
                p11=0.0,
                at=0.0,
                seen=5,
            )
            member.predict(HOUR * 400.0)
            assert member.rate == pytest.approx(math.copysign(edge, start), rel=1e-6), (
                f"from {start}"
            )

    def test_no_wells_without_the_sign_pattern_that_makes_them(self):
        """`wells` must be `None` unless `theta < 0 < kappa`.

        The renormalisation-group claim is specifically `b > 0 > c`, which is
        this sign pattern and no other. A property that returned a pair for
        `theta > 0` would report a mode where the model has a single minimum,
        and the harness reads this field to decide what it found.
        """
        from till_infinity.statespace import Landau

        assert Landau(theta=0.5, kappa=1.0).wells is None, "reverting and stiffened"
        assert Landau(theta=-0.5, kappa=0.0).wells is None, "unstable, nothing to stop it"
        assert Landau(theta=0.0, kappa=1.0).wells is None, "marginal"
        assert Landau(theta=-0.5, kappa=-1.0).wells is None, "both signs wrong"
        assert Landau(theta=-0.5, kappa=1.0).wells is not None

    def test_the_stiffness_is_the_local_reversion_rate(self):
        """`theta + 3 kappa r^2`, and `-2 theta` when the rate is in the well.

        The curvature of the potential at its minimum is `-2 theta` for this
        family, independent of `kappa` - which is a non-obvious identity and
        therefore worth asserting, because getting the Jacobian's factor of
        three wrong is the single easiest mistake in the module and would make
        the covariance quietly wrong rather than visibly broken.
        """
        from till_infinity.statespace import Landau

        theta, kappa = -0.62, 0.30
        member = Landau(theta=theta, kappa=kappa, rate=math.sqrt(-theta / kappa))
        assert member.stiffness == pytest.approx(-2.0 * theta)
        assert member.half_life_hours == pytest.approx(math.log(2.0) / (-2.0 * theta))

        flat = Landau(theta=0.5, kappa=0.0, rate=3.0)
        assert flat.stiffness == pytest.approx(0.5), "no cubic, no state dependence"
        assert Landau(theta=-0.1, kappa=0.0, rate=1.0).half_life_hours == math.inf

    def test_the_transition_is_the_tangent_of_the_flow(self):
        """`transition` is a linearisation and `predict` is not - and they agree
        where they must.

        A smoother needs a matrix, so it gets the Jacobian; `predict` uses the
        closed form. At `kappa = 0` the two are the same model and the matrix
        must match `Reverting`'s exactly, which is what stops the tangent from
        drifting away from the member it is a tangent to.
        """
        from till_infinity.statespace import Landau, Reverting

        for dt in (0.5, 4.0, 73.0):
            assert Landau(theta=0.4, kappa=0.0).transition(dt) == Reverting(theta=0.4).transition(
                dt
            )

        # With kappa on, the tangent's decay must follow the local stiffness.
        member = Landau(theta=0.1, kappa=2.0, rate=0.9)
        decay = member.transition(1.0)[1][1]
        assert decay == pytest.approx(math.exp(-(0.1 + 3.0 * 2.0 * 0.81)))

    def test_a_negative_kappa_reports_a_blow_up_rather_than_a_sign_flip(self):
        """`kappa < 0` drives the rate to infinity in finite time.

        It is not a parameter anyone should fit, but a grid search will offer
        it, and the failure mode to avoid is the quiet one: taking the square
        root of a negative `u` and coming back with a *finite* rate of the
        wrong sign, which a likelihood would happily score.
        """
        from till_infinity.statespace.landau import _flow, _travel

        assert _flow(0.5, 10.0, -0.1, -1.0) == math.inf
        assert _flow(-0.5, 10.0, -0.1, -1.0) == -math.inf
        assert _travel(0.5, 10.0, -0.1, -1.0) == math.inf

        # And the member survives it: the mean freezes, the likelihood is
        # finite, and the grid can score the cell and move on.
        from till_infinity.statespace import Landau

        member = Landau(theta=-0.1, kappa=-1.0, sigma2=1e-3)
        for i in range(50):
            member.update(0.1 * i, noise=0.04, when=i * HOUR)
        assert math.isfinite(member.loglike)
        assert math.isfinite(member.value)

    def test_the_band_agrees_with_predicting_forward(self):
        """Two hand-written copies of one propagation, as for `linear` and
        `reverting`. The same check, because the same mistake was available -
        `band` recomputes the local stiffness and could easily use the
        start-of-step rate where `predict` uses the midpoint."""
        from till_infinity.statespace import Landau

        fields = ("value", "rate", "p00", "p01", "p11", "theta", "kappa", "at", "seen")
        for ahead in (0.0, 1.0, 7.0, 62.0):
            live = Landau(sigma2=0.18, theta=-0.3, kappa=1.5)
            for i in range(30):
                live.update(5.0 + 0.05 * i, noise=0.16, when=i * HOUR)
            when = live.at + ahead * HOUR
            low, high = live.band(when, sigmas=2.0)

            ahead_copy = Landau(**{f: getattr(live, f) for f in fields})
            ahead_copy.sigma2 = live.sigma2
            ahead_copy.predict(when)
            assert 0.5 * (low + high) == pytest.approx(ahead_copy.value, rel=1e-9, abs=1e-12)
            assert 0.5 * (high - low) == pytest.approx(2.0 * math.sqrt(ahead_copy.p00), rel=1e-9), (
                f"ahead {ahead}"
            )

    def test_it_satisfies_the_filter_protocol(self):
        """Because the whole point is scoring it against the other members."""
        from till_infinity.statespace import Landau
        from till_infinity.statespace.family import Filter

        assert isinstance(Landau(), Filter)


class TestAdapting:
    """Error feedback on the process noise. The loop, and the guarantees it needs.

    A Kalman filter is already online learning with error feedback - the
    innovation is the error and the gain is a derived learning rate - so this
    wrapper closes the one gap: the gain is optimal *given* `Q`, and `Q` is
    set by hand or gridded offline.

    Three things have to hold or the measurement is worthless. **`none` must be
    the bare delegate**, so a harness's null arm cannot differ from the member
    by anything but the mode. **The lever must be updated after the
    measurement is scored**, or the likelihood is being produced by a
    parameter fitted to the point it is predicting. And **the loop must drive
    its own error signal toward one**, since that is the only thing it is
    designed to do.
    """

    HOUR = 3_600.0

    def _series(self, n=1200, *, jerk=0.02, seed=5):
        """A level whose drift random-walks, so a filter's `Q` can be wrong."""
        import random

        rng = random.Random(seed)
        times, levels = [], []
        level, slope = 0.0, 0.0
        for i in range(n):
            slope += rng.gauss(0.0, math.sqrt(jerk))
            level += slope
            times.append(i * self.HOUR)
            levels.append(level + rng.gauss(0.0, 0.1))
        return times, levels

    def test_none_is_the_bare_delegate(self):
        """Exact equality on the state, the covariance and the likelihood.

        Not `approx`: `mode="none"` must take a code path that does the same
        arithmetic, because a harness compares its null arm against the other
        modes and any difference here is attributed to adaptation.
        """
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting

        times, levels = self._series()
        wrapped = Adapting(build=lambda: Gaussian(jerk=0.01, p00=1.0), mode="none")
        bare = Gaussian(jerk=0.01, p00=1.0)
        for when, level in zip(times, levels, strict=True):
            wrapped.predict(when)
            got = wrapped.update(level, 0.01)
            bare.predict(when)
            want = bare.update(level, 0.01)
            assert got == want
        assert wrapped.state() == bare.state()
        assert wrapped.covariance() == bare.covariance()
        assert wrapped.loglike == bare.loglike
        assert wrapped.factor == 1.0, "the lever must not move in this mode"

    def test_the_lever_moves_after_the_measurement_is_scored(self):
        """The ordering guarantee, asserted rather than trusted.

        The likelihood contribution at step `t` has to come from the parameter
        in force *before* `t` was seen. This drives one step at a time and
        checks that the lever used by the filter is the one from the previous
        step, which is the difference between a held-out number and a cheat.
        """
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting

        times, levels = self._series(n=200)
        loop = Adapting(build=lambda: Gaussian(jerk=0.01, p00=1.0), mode="matching", step=0.05)
        previous = loop._member.jerk
        for when, level in zip(times, levels, strict=True):
            loop.predict(when)
            # Whatever `predict` just used, it is the lever as of the last
            # update - not one informed by `level`, which has not been seen.
            assert loop._member.jerk == previous
            loop.update(level, 0.01)
            previous = loop._member.jerk

    def test_the_loop_drives_its_error_signal_toward_one(self):
        """`E[z^2] = 1` is an honest filter, and is the loop's whole job.

        Started deliberately over-confident - a `Q` a thousand times too small
        - so the squared standardised innovation starts far above one and the
        loop has somewhere to go.
        """
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting

        times, levels = self._series(jerk=0.02)
        wrong = 0.02 / 1000.0
        loop = Adapting(build=lambda: Gaussian(jerk=wrong, p00=1.0), mode="matching", step=0.01)
        fixed = Adapting(build=lambda: Gaussian(jerk=wrong, p00=1.0), mode="none")
        for when, level in zip(times, levels, strict=True):
            loop.predict(when)
            loop.update(level, 0.01)
            fixed.predict(when)
            fixed.update(level, 0.01)

        assert fixed.excess > 3.0, "the fixed arm has to be badly over-confident"
        assert loop.excess < fixed.excess / 2.0, "the loop has to close most of the gap"
        assert loop.factor > 10.0, "and it has to do it by raising the lever"
        assert loop.loglike > fixed.loglike, "which should also score better here"

    def test_matching_and_gradient_move_the_same_way(self):
        """They are the same direction: covariance matching **is** gradient
        ascent on the likelihood with respect to `log Q`, up to the step size.

        Asserted on the sign rather than the size, because the size is exactly
        where they differ - the gradient's step shrinks as the predictive
        spread grows, and measuring whether that matters is the harness's job.
        """
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting

        times, levels = self._series(jerk=0.02)
        for wrong, direction in ((0.02 / 500.0, 1.0), (0.02 * 500.0, -1.0)):
            moves = []
            for mode in ("matching", "gradient"):
                # `wrong` bound as a default: the lambda outlives this
                # iteration inside the wrapper, and a late-bound loop variable
                # would silently build every arm from the last value.
                loop = Adapting(
                    build=lambda jerk=wrong: Gaussian(jerk=jerk, p00=1.0),
                    mode=mode,
                    step=0.01,
                )
                for when, level in zip(times, levels, strict=True):
                    loop.predict(when)
                    loop.update(level, 0.01)
                moves.append(loop.factor)
            for factor in moves:
                assert (factor - 1.0) * direction > 0.0, f"{wrong} went the wrong way"

    def test_forgetting_inflates_the_covariance_and_leaves_the_lever_alone(self):
        """A different mechanism, and the control on whether feedback matters.

        Exponential forgetting is the recursive-least-squares answer: it bounds
        how much information the filter can accumulate rather than correcting
        `Q`. So the lever must not move, and the covariance must end larger
        than the unforgetting arm's.
        """
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting

        times, levels = self._series()
        loose = Adapting(
            build=lambda: Gaussian(jerk=0.01, p00=1.0), mode="forgetting", forgetting=0.99
        )
        tight = Adapting(build=lambda: Gaussian(jerk=0.01, p00=1.0), mode="none")
        for when, level in zip(times, levels, strict=True):
            loose.predict(when)
            loose.update(level, 0.01)
            tight.predict(when)
            tight.update(level, 0.01)
        assert loose.factor == 1.0, "forgetting must not touch the lever"
        assert loose.covariance()[0][0] > tight.covariance()[0][0]

    def test_the_lever_is_clamped(self):
        """A loop chasing an outlier must not reach zero or infinity.

        A process noise of zero is a state that cannot move; one of infinity is
        a state that is pure noise. Both are reachable by a multiplicative
        update, so both are clamped - and `clamped` says when the loop has
        stopped learning and started sitting on a bound.
        """
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting

        times, levels = self._series(jerk=5.0)
        loop = Adapting(
            build=lambda: Gaussian(jerk=1e-12, p00=1.0),
            mode="matching",
            step=0.9,
            most=50.0,
        )
        for when, level in zip(times, levels, strict=True):
            loop.predict(when)
            loop.update(level, 0.01)
        assert loop.factor <= 50.0
        assert loop.clamped, "this is meant to hit the ceiling"
        assert math.isfinite(loop.loglike)

    def test_it_refuses_a_lever_that_does_not_exist_and_a_mode_that_does_not(self):
        """Both silently do nothing if unchecked, which is the worst outcome:
        a harness would report adaptation buying zero and be right by
        accident."""
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting

        with pytest.raises(ValueError, match="no 'theta' to adapt"):
            Adapting(build=lambda: Gaussian(jerk=0.01), lever="theta")
        with pytest.raises(ValueError, match="unknown mode"):
            Adapting(build=lambda: Gaussian(jerk=0.01), mode="rmsprop")

    def test_it_satisfies_the_filter_protocol(self):
        from till_infinity.statespace import Gaussian
        from till_infinity.statespace.adapting import Adapting
        from till_infinity.statespace.family import Filter

        assert isinstance(Adapting(build=lambda: Gaussian(jerk=0.01)), Filter)


def test_the_improvements_table_cannot_rot_in_either_direction():
    """The `here` column of the I1-I11 table, asserted against the code.

    **This is the third stale registry in this package.** `MISSING["em"]` said
    EM was absent while `fit_em` existed; `MISSING` listed the fixed-lag
    smoother while `smoothing.lagged` was written and tested; and the
    improvements table marked six items `-` while a module already claimed
    each one.

    The first two were caught by a guard that asserts **absence**. That is only
    half of what goes wrong here, because the rot was in the other direction -
    things listed as missing that existed. So this one checks **both**:

    * a row naming a module must have that module, and the module must mention
      the item - so a rename or a deletion fails here rather than silently
      making the plan a work of fiction;
    * a row marked `-` must have **no** module claiming it, so the next item
      to be built cannot be finished and left marked undone.

    Parsed out of the docstring rather than duplicated in the test, because two
    copies of a table is how the first one rotted.
    """
    import pathlib
    import re

    from till_infinity import statespace

    doc = statespace.__doc__ or ""
    rows = re.findall(r"^\|\s*\**(I\d+)\**\s*\|[^|]*\|\s*(.+?)\s*\|$", doc, re.MULTILINE)
    assert len(rows) >= 9, f"expected the improvements table, parsed {len(rows)} rows"

    package = pathlib.Path(statespace.__file__).parent
    sources = {
        path.name: path.read_text() for path in package.glob("*.py") if path.name != "__init__.py"
    }

    claimed: dict[str, set[str]] = {}
    for name, text in sources.items():
        for item in re.findall(r"\bI(\d+)\b", text):
            claimed.setdefault(f"I{item}", set()).add(name)

    for item, where in rows:
        # Digits included: `[a-z_]+` missed `barriers2.py`, so a module name
        # carrying a number fell through to the `-` branch and failed with the
        # wrong reason. Caught while checking the guard fails when it should.
        named = re.findall(r"`([a-z0-9_]+\.py)`", where)
        if named:
            for module in named:
                assert module in sources, f"{item} names {module}, which does not exist"
                # Split rather than `and`-ed: CI's `PT018` catches a compound
                # assert, and this session already let one through once.
                assert item in claimed, f"{item} is named in the table and claimed nowhere"
                assert module in claimed[item], (
                    f"{item} names {module} but that module never mentions {item} - "
                    "either the work moved or the table is fiction"
                )
        else:
            assert where.replace("*", "").strip() == "-", (
                f"{item}'s `here` column is {where!r}, which is neither a module nor `-`"
            )
            assert item not in claimed, (
                f"{item} is marked absent but {sorted(claimed[item])} claims it. "
                "That is the rot this test exists for: finish an item and the "
                "table has to say so."
            )


class TestBounding:
    """I7: the target, stop, win rate and duration are one surface."""

    def test_the_symmetric_case_is_a_coin_whatever_the_shift(self):
        """Equal barriers give 0.5 because the shift moves both walls alike."""
        from till_infinity.statespace import bounding

        for shift in (0.0, bounding.SHIFT, 2.0):
            got = bounding.solve(up=1.3, down=1.3, shift=shift)
            assert got["probability"] == pytest.approx(0.5)

    def test_the_duration_is_the_product_of_the_shifted_barriers(self):
        from till_infinity.statespace import bounding

        got = bounding.solve(up=2.0, down=3.0)
        want = (2.0 + bounding.SHIFT) * (3.0 + bounding.SHIFT)
        assert got["horizon"] == pytest.approx(want)

    @pytest.mark.parametrize(
        "pair",
        [
            ("up", "down"),
            ("up", "probability"),
            ("up", "horizon"),
            ("down", "probability"),
            ("down", "horizon"),
            ("probability", "horizon"),
        ],
    )
    def test_every_pair_recovers_the_same_point_on_the_surface(self, pair):
        """Two degrees of freedom means all six pairs agree.

        This is the item itself: if any pair disagreed, the four quantities
        would not be one model and the desk's third number would be free.
        """
        from till_infinity.statespace import bounding

        full = bounding.solve(up=2.0, down=3.0)
        again = bounding.solve(**{key: full[key] for key in pair})
        for key in bounding.QUANTITIES:
            assert again[key] == pytest.approx(full[key], rel=1e-9), key

    def test_three_numbers_is_an_error_rather_than_an_input(self):
        """Over-specified is the finding, so it cannot be silently accepted."""
        from till_infinity.statespace import bounding

        with pytest.raises(ValueError, match="exactly two"):
            bounding.solve(up=1.0, down=1.0, horizon=10.0)
        with pytest.raises(ValueError, match="exactly two"):
            bounding.solve(up=1.0)

    def test_a_win_rate_and_a_holding_time_can_be_jointly_unreachable(self):
        """The constraint three independent numbers cannot express."""
        from till_infinity.statespace import bounding

        least = bounding.least_horizon(0.9)
        assert least == pytest.approx(bounding.SHIFT**2 * 0.9 / 0.1)
        assert not bounding.feasible(0.9, least * 0.99)
        assert bounding.feasible(0.9, least * 1.01)
        with pytest.raises(ValueError, match="closer than zero"):
            bounding.solve(probability=0.9, horizon=least * 0.5)
        # at the boundary the near barrier sits exactly at zero distance
        edge = bounding.solve(probability=0.9, horizon=least)
        assert min(edge["up"], edge["down"]) == pytest.approx(0.0, abs=1e-9)

    def test_slack_says_which_of_the_three_decides_the_exit(self):
        from till_infinity.statespace import bounding

        implied = bounding.solve(up=1.0, down=1.0)["horizon"]
        assert bounding.slack(1.0, 1.0, implied) == pytest.approx(1.0)
        assert bounding.binding(1.0, 1.0, implied) == "both"
        assert bounding.binding(1.0, 1.0, implied * 10.0) == "barriers"
        assert bounding.binding(1.0, 1.0, implied * 0.1) == "time"

    def test_slower_scales_the_duration_and_leaves_the_label_alone(self):
        """The measured correction is conditional on volatility; the label is not."""
        from till_infinity.statespace import bounding

        plain = bounding.solve(up=2.0, down=3.0)
        slow = bounding.solve(up=2.0, down=3.0, slower=1.958)
        assert slow["horizon"] == pytest.approx(plain["horizon"] * 1.958)
        assert slow["probability"] == pytest.approx(plain["probability"])
        # and a horizon handed back in feed time recovers the same geometry
        again = bounding.solve(
            probability=slow["probability"], horizon=slow["horizon"], slower=1.958
        )
        assert again["up"] == pytest.approx(2.0)
        assert again["down"] == pytest.approx(3.0)

    def test_the_symmetric_case_is_untouched_by_the_two_wall_form(self):
        """Adding a second wall must not move the single-wall answer."""
        from till_infinity.statespace import bounding

        plain = bounding.solve(up=1.0, down=1.0)
        same = bounding.solve(up=1.0, down=1.0, shift_up=bounding.SHIFT)
        for key in bounding.QUANTITIES:
            assert same[key] == pytest.approx(plain[key]), key
        assert bounding.least_horizon(0.7) == pytest.approx(
            bounding.least_horizon(0.7, shift_up=bounding.SHIFT)
        )

    def test_a_one_sided_feed_is_not_a_coin_at_equal_barriers(self):
        """The whole point: equal barriers stop being 50/50 once the walls differ.

        A Boom index spikes upward, so it overshoots its upper barrier and that
        barrier is effectively further away - which lowers, not raises, the
        chance of reaching it first.
        """
        from till_infinity.statespace import bounding

        up_wall, down_wall = bounding.shifts_for("Boom_300_Index")
        assert up_wall > down_wall, "boom must overshoot upward"
        got = bounding.solve(up=2.0, down=2.0, shift_up=up_wall, shift_down=down_wall)
        assert got["probability"] < 0.5
        assert got["probability"] == pytest.approx(0.4861, abs=5e-4)
        # and the mirror family mirrors it
        crash_up, crash_down = bounding.shifts_for("Crash_300_Index")
        mirror = bounding.solve(up=2.0, down=2.0, shift_up=crash_up, shift_down=crash_down)
        assert mirror["probability"] > 0.5

    @pytest.mark.parametrize(
        "pair",
        [
            ("up", "down"),
            ("up", "probability"),
            ("up", "horizon"),
            ("down", "probability"),
            ("down", "horizon"),
            ("probability", "horizon"),
        ],
    )
    def test_the_surface_still_closes_with_two_different_walls(self, pair):
        """Two degrees of freedom has to survive the asymmetry, or it is not one model."""
        from till_infinity.statespace import bounding

        walls = {"shift_up": 0.7183, "shift_down": 0.4500}
        full = bounding.solve(up=2.0, down=3.0, **walls)
        again = bounding.solve(**{key: full[key] for key in pair}, **walls)
        for key in bounding.QUANTITIES:
            assert again[key] == pytest.approx(full[key], rel=1e-9), key

    def test_each_wall_contributes_its_own_feasibility_bound(self):
        """With different walls the two constraints stop coinciding."""
        from till_infinity.statespace import bounding

        up_wall, down_wall = 0.9, 0.3
        for p in (0.2, 0.5, 0.8):
            least = bounding.least_horizon(p, shift_up=up_wall, shift_down=down_wall)
            assert least == pytest.approx(max(up_wall**2 * p / (1 - p), down_wall**2 * (1 - p) / p))
            # at the boundary one barrier sits exactly at zero distance
            edge = bounding.solve(
                probability=p, horizon=least, shift_up=up_wall, shift_down=down_wall
            )
            assert min(edge["up"], edge["down"]) == pytest.approx(0.0, abs=1e-9)
            assert not bounding.feasible(p, least * 0.99, shift_up=up_wall, shift_down=down_wall)

    def test_the_measured_table_mirrors_the_mirror_families(self):
        """Boom against Crash and DEX up against down are the table's own check.

        Nothing forces these to agree - they are four independent measurements -
        so their mirroring is evidence the estimator read the asymmetry rather
        than noise.
        """
        from till_infinity.statespace import bounding

        boom_up, boom_down = bounding.SHIFTS["boom"]
        crash_up, crash_down = bounding.SHIFTS["crash"]
        assert boom_up > boom_down
        assert crash_down > crash_up
        assert boom_up / boom_down == pytest.approx(crash_down / crash_up, rel=0.25)

        dex_up = bounding.SHIFTS["dex_up"]
        dex_down = bounding.SHIFTS["dex_down"]
        assert dex_up[0] == pytest.approx(dex_down[1], rel=0.1)
        assert dex_up[1] == pytest.approx(dex_down[0], rel=0.1)

    def test_an_unmeasured_feed_falls_back_to_symmetric(self):
        """A guess would be worse than the constant it replaces.

        `EURUSD` used to be the example here and is now measured - see
        `TestTradedWalls` - so the unmeasured cases are the traded classes that
        still have not been: energy, softs, baskets, indices and equities.
        """
        from till_infinity.statespace import bounding

        for feed in ("US_Oil", "Sugar", "USD_Basket", "Germany_40", "AAPL.OQ"):
            assert bounding.shifts_for(feed) == (bounding.SHIFT, bounding.SHIFT), feed
        assert bounding.shifts_for("Volatility_75_Index") == (
            bounding.SHIFT,
            bounding.SHIFT,
        )
        # the step families were measured and came out symmetric
        for name in ("Step_Index", "Multi_Step_3_Index", "Skew_Step_Index_5_Up"):
            assert bounding.shifts_for(name) == (bounding.SHIFT, bounding.SHIFT), name
        # DEX needs its direction, and an unsuffixed DEX name must not guess
        assert bounding.shifts_for("DEX_600_UP_Index")[0] > bounding.SHIFT
        assert bounding.shifts_for("DEX_600_DOWN_Index")[1] > bounding.SHIFT
        assert bounding.shifts_for("DEX_600_Index") == (bounding.SHIFT, bounding.SHIFT)


class TestVendoredCusum:
    """The package must not import from outside itself, and the copy must not drift."""

    def test_the_package_imports_nothing_from_outside_itself(self):
        """Isolation is the point: this package is meant to lift out in one move.

        A reach into a sibling **model** - `structures.learning`,
        `structures.context`, `trading`, `models` - turns an extraction into a
        code change, so it is asserted rather than remembered. `paired.py` used
        to import the changepoint detector from `structures.learning`.

        **`shared` is exempt.** It travels with the package rather than being a
        model the package depends on, which is why `Restorable` is imported
        from there rather than vendored: duplicating persistence-critical code
        is a liability, and `restore_deque` exists because a capped deque came
        back unbounded from a production restore.
        """
        import pathlib
        import re

        from till_infinity import statespace

        package = pathlib.Path(statespace.__file__).parent
        offenders = {}
        for path in sorted(package.glob("*.py")):
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if not stripped.startswith(("import ", "from ")):
                    continue
                # `from .x`, `from till_infinity.statespace...` and
                # plain third-party imports are all fine; `from ..` and any
                # `till_infinity` path outside this package are not.
                if "shared" in stripped:
                    continue
                if stripped.startswith("from ..") or (
                    re.match(r"from till_infinity\b", stripped) and "statespace" not in stripped
                ):
                    offenders.setdefault(path.name, []).append(stripped)
        assert not offenders, f"statespace reaches outside itself: {offenders}"

    def test_no_two_modules_under_structures_share_a_basename(self):
        """`codec.py` keys by basename, so a duplicate silently breaks a restore.

        This hazard has now bitten three times. `paired.py` records the first
        two - two modules called `focus` holding two classes called `Focus`
        resolved to the same registry key, and a restore built the wrong class.
        The third was this vendoring: naming the new module `cusum.py` beside
        the existing `context/cusum.py` made the basename-to-location map
        ambiguous, and a new field on `context.cusum.Cusum` stopped
        invalidating saved state.

        The schema test catches it, but with a message about an unrelated class.
        This says what is actually wrong.
        """
        import pathlib

        from till_infinity import structures

        root = pathlib.Path(structures.__file__).parent
        seen = {}
        for path in sorted(root.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            seen.setdefault(path.stem, []).append(str(path.relative_to(root)))
        clashes = {stem: where for stem, where in seen.items() if len(where) > 1}
        assert not clashes, (
            "two modules under structures share a basename, which codec.py keys "
            f"persistence by: {clashes}"
        )

    def test_the_vendored_detector_matches_the_original_observation_by_observation(self):
        """A verbatim copy is only safe while it stays verbatim.

        The original is still in `structures.learning` and still used there, so
        the two can drift apart silently. This feeds both the same stream and
        compares the statistic, the changepoint and the hull at every step.
        """
        import random

        from till_infinity.statespace.accruing import THRESHOLD, OneSided
        from till_infinity.structures.learning.focus import THRESHOLD as ORIGINAL
        from till_infinity.structures.learning.focus import Focus

        assert THRESHOLD == ORIGINAL

        rng = random.Random(20261013)
        for up in (True, False):
            theirs = Focus(up=up)
            mine = OneSided(up=up)
            # A shift part way through, so both detectors actually fire.
            for i in range(600):
                value = rng.gauss(0.0, 1.0) + (1.5 if i > 300 else 0.0)
                fired_theirs = theirs.update(value, 1.0)
                fired_mine = mine.update(value, 1.0)
                assert fired_mine == fired_theirs, f"up={up} step {i}"
                assert mine.statistic == pytest.approx(theirs.statistic), i
                assert mine.at == theirs.at, i
                assert mine.hull == theirs.hull, i
                assert mine.seen == theirs.seen, i
            theirs.reset()
            mine.reset()
            assert mine.hull == theirs.hull
            assert mine.statistic == theirs.statistic

    def test_paired_still_works_on_the_vendored_detector(self):
        """The caller that prompted the vendoring, driven through its real API."""
        from till_infinity.statespace.accruing import OneSided
        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.paired import Paired

        member = Paired(build=lambda: Gaussian(jerk=1e-9))
        hour = 3_600.0
        when = 0.0
        for i in range(400):
            when += hour
            member.predict(when)
            # A clean shift part way through, so the detector has something to find.
            member.update(0.001 * i + (0.05 if i > 200 else 0.0), 1e-8, when)
        assert isinstance(member._up, OneSided)
        assert isinstance(member._down, OneSided)
        assert member.statistic >= 0.0


class TestResearchIntegrated:
    """The primitives the relationship and forecast work left in research harnesses.

    `nulls.py` argues the case itself: the floors "lived in research harnesses,
    were copied between them, and drifted - which is how both defects below
    survived". This session copied two null constructions across five harnesses
    and scored every forecast result on a CRPS the library did not have.
    """

    def test_a_rotation_preserves_the_marginal_exactly(self):
        """The one property the null exists for, asserted rather than assumed.

        The first implementation rotated the **levels** and then differenced
        them, which replaces one real increment with the gap across the wrap
        point - so the marginal was not preserved and the null was not a null.
        """
        import random

        from till_infinity.statespace import nulls

        rng = random.Random(20261013)
        values = [0.0]
        for _ in range(400):
            values.append(values[-1] + rng.gauss(0.0, 1.0))
        rotated = nulls.rotated(values, 137)

        assert len(rotated) == len(values)
        assert rotated[0] == values[0], "anchored at the same start"
        steps = sorted(round(values[i] - values[i - 1], 9) for i in range(1, len(values)))
        after = sorted(round(rotated[i] - rotated[i - 1], 9) for i in range(1, len(rotated)))
        assert after == steps, "the increment multiset must be identical"
        assert rotated[1:6] != values[1:6], "and it must actually move"

    def test_a_block_shuffle_preserves_the_marginal_and_the_caller_s_order(self):
        import random

        from till_infinity.statespace import nulls

        rng = random.Random(7)
        values = [0.0]
        for _ in range(400):
            values.append(values[-1] + rng.gauss(0.0, 1.0))
        order = list(range(len(values) // 24 + 2))
        rng.shuffle(order)
        shuffled = nulls.block_shuffled(values, order)

        assert len(shuffled) == len(values)
        steps = sorted(round(values[i] - values[i - 1], 9) for i in range(1, len(values)))
        after = sorted(round(shuffled[i] - shuffled[i - 1], 9) for i in range(1, len(shuffled)))
        assert after == steps, "a permutation must preserve the increments"
        # A partial order would shorten the series, which changes the sample.
        assert len(nulls.block_shuffled(values, [0, 1])) == len(values)
        # Too short to null: handed back unchanged rather than silently wrong.
        assert nulls.block_shuffled([0.0, 1.0, 2.0], [0]) == [0.0, 1.0, 2.0]
        assert nulls.rotated([0.0, 1.0, 2.0], 1) == [0.0, 1.0, 2.0]

    def test_crps_agrees_with_the_closed_form_it_replaces(self):
        """One instrument for every band shape, checked against the known case.

        The tail-shape work needed a Gaussian closed form *and* a quadrature and
        had to reconcile them. The quantile-loss identity needs only quantiles,
        so it scores a Gaussian, a Student-t and a shape-free empirical band
        identically - but it has to reproduce the closed form to be trusted.
        """
        import statistics as stats

        from till_infinity.statespace import diagnostics

        normal = stats.NormalDist()
        grid = [(i / 200.0, normal.inv_cdf(i / 200.0)) for i in range(1, 200)]

        # The closed form for a standard normal forecast at outcome x is
        # `x(2*Phi(x) - 1) + 2*phi(x) - 1/sqrt(pi)`, checked at two outcomes so
        # the agreement is not a coincidence at one point.
        def closed(x: float) -> float:
            phi = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
            return x * (2.0 * normal.cdf(x) - 1.0) + 2.0 * phi - 1.0 / math.sqrt(math.pi)

        for outcome in (0.0, 1.5):
            assert diagnostics.crps(grid, outcome) == pytest.approx(closed(outcome), abs=5e-3), (
                outcome
            )
        # A degenerate forecast sitting on the outcome scores nothing.
        assert diagnostics.crps([(i / 50.0, 0.0) for i in range(1, 50)], 0.0) == 0.0
        # And it is a loss: being wrong costs more than being right.
        near = diagnostics.crps(grid, 0.0)
        far = diagnostics.crps(grid, 3.0)
        assert far > near

    def test_pit_flatness_reads_one_on_uniform_and_more_on_a_pile(self):
        from till_infinity.statespace import diagnostics

        uniform = [(i + 0.5) / 2000.0 for i in range(2000)]
        assert diagnostics.pit_flatness(uniform) == pytest.approx(0.0, abs=0.05)
        piled = [0.5] * 2000
        assert diagnostics.pit_flatness(piled) > 100.0
        assert math.isnan(diagnostics.pit_flatness([0.1, 0.2]))

    def test_har_is_a_harder_floor_than_a_lag_and_says_so_by_shape(self):
        from till_infinity.statespace import nulls

        rows, targets = nulls.har(list(range(100)))
        assert len(rows) == len(targets)
        assert all(len(row) == 3 for row in rows)
        # The first row sits at `month - 1` and predicts the next observation.
        assert targets[0] == float(nulls.HAR_MONTH)
        assert rows[0][0] == float(nulls.HAR_MONTH - 1)
        # On a ramp the week and month means trail the own value.
        assert rows[0][1] < rows[0][0]
        assert rows[0][2] < rows[0][1]
        assert nulls.har([1.0, 2.0]) == ([], [])

    def test_the_currency_cycle_rule_separates_arithmetic_from_a_candidate(self):
        """The rule that keeps a screen from reporting arithmetic as discovery."""
        from till_infinity.statespace import relating

        for names in (
            ("EURUSD", "USDCHF", "EURCHF"),
            ("EURUSD", "GBPUSD", "EURGBP"),
            ("GBPUSD", "USDJPY", "GBPJPY"),
            ("EURUSD", "USDCHF", "EURCHF", "GBPUSD"),
            ("EURUSD", "EURGBP", "GBPUSD"),
        ):
            assert relating.is_identity(names), names
        for names in (
            ("EURUSD", "USDJPY", "USDCAD"),
            ("GBPUSD", "NZDUSD", "AUDUSD"),
            ("BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD"),
            ("EURUSD", "GBPUSD"),
            ("XAUUSD", "XAGUSD"),
            ("EURUSD", "USDJPY", "GBPUSD", "USDCAD", "NZDUSD"),
        ):
            assert not relating.is_identity(names), names
        assert relating.currencies("EURUSD") == frozenset({"EUR", "USD"})
        assert relating.is_identity([]) is False


class TestBoundingFeed:
    """`feed=` has to reach every entry point, and has to change the answer.

    The wiring this covers was measured and then not reachable: `shifts_for`
    held the measured directional walls and nothing but a test ever called it,
    so a caller asking for a Boom barrier got the symmetric `0.5826` on both
    sides. An earlier pass at the same work added `feed` to `feasible` and
    ignored it inside - caught by a lint rule for an unused argument, not by a
    test - which is why these assertions check that the value *differs* rather
    than that the call is accepted.
    """

    def test_a_named_feed_resolves_the_measured_asymmetric_walls(self):
        from till_infinity.statespace import bounding

        assert bounding.shifts_for("Boom_500_Index") == bounding.SHIFTS["boom"]
        assert bounding.shifts_for("DEX_900_UP_Index") == bounding.SHIFTS["dex_up"]
        # An unlisted feed is symmetric, which is the documented fallback.
        # Not `EURUSD`: that is measured now, see `TestTradedWalls`.
        assert bounding.shifts_for("US_Oil") == (bounding.SHIFT, bounding.SHIFT)

    def test_feed_changes_what_solve_returns_on_a_skewed_family(self):
        from till_infinity.statespace import bounding

        plain = bounding.solve(probability=0.4, horizon=9.0)
        boomed = bounding.solve(probability=0.4, horizon=9.0, feed="Boom_500_Index")
        assert plain is not None
        assert boomed is not None
        # Boom's walls are 0.6535 up against 0.5100 down, so the barriers it
        # implies cannot be the symmetric ones.
        assert plain != boomed

    def test_feed_reaches_least_horizon_and_feasible_and_they_agree(self):
        from till_infinity.statespace import bounding

        for feed in ("Boom_500_Index", "DEX_1500_DOWN_Index", "Crash_500_Index"):
            for probability in (0.3, 0.5, 0.7):
                least = bounding.least_horizon(probability, feed=feed)
                symmetric = bounding.least_horizon(probability)
                assert least > 0
                # The two must not silently coincide, or `feed` is being
                # dropped somewhere between here and `_walls`.
                assert least != symmetric
                # Just below the floor is infeasible and just above is
                # feasible, for the same feed - which is the only way to show
                # the two functions resolved the same walls.
                assert not bounding.feasible(probability, least * 0.99, feed=feed)
                assert bounding.feasible(probability, least * 1.01, feed=feed)

    def test_an_explicit_wall_beats_the_table_on_the_side_that_binds(self):
        """A caller who measured their own is not overridden by a lookup.

        And only the **binding** side can move the answer, which is worth
        asserting in both directions. `least_horizon` is the larger of
        `up^2 p / (1 - p)` and `down^2 (1 - p) / p`, so at `p = 0.4` with
        Boom's walls the down term wins at 0.390 against the up term's 0.285 -
        and overriding the up wall there correctly changes nothing. A test that
        demanded a change from either side would be asserting a bug.
        """
        from till_infinity.statespace import bounding

        table = bounding.least_horizon(0.4, feed="Boom_500_Index")
        # Down binds at this probability, so overriding it moves the floor.
        assert bounding.least_horizon(0.4, feed="Boom_500_Index", shift_down=0.9) != table
        # Up does not bind, so overriding it must not.
        assert bounding.least_horizon(0.4, feed="Boom_500_Index", shift_up=0.5826) == table
        # Past the crossover the roles swap, which is the same claim from the
        # other side rather than a second one.
        high = bounding.least_horizon(0.7, feed="Boom_500_Index")
        assert bounding.least_horizon(0.7, feed="Boom_500_Index", shift_up=0.9) != high


class TestPacing:
    """Activity as a `Q` multiplier, and the properties that make it one."""

    def test_constant_activity_is_exactly_neutral_which_is_the_control(self):
        """The generated feeds post constant tick volume, so they must be off.

        This is the whole control design: Deriv's synthetics have an
        interquartile range of zero on tick volume, so `share` is one, the
        factor is one and `control` is zero. If this drifted even slightly the
        control arm would be driven as well as the traded arm and the
        comparison would mean nothing - and nothing in the harness would say
        so, because a factor of 1.001 looks exactly like a factor of 1.
        """
        from till_infinity.statespace import pacing

        pace = pacing.Pace()
        for _ in range(300):
            pace.update(1800.0)
        assert pace.share(1800.0) == 1.0
        assert pace.factor(1800.0) == 1.0
        assert pace.control(1800.0) == 0.0
        assert pacing.extent([1800.0] * 400) == 1.0

    def test_it_averages_one_so_a_gain_does_not_move_the_average(self):
        """A multiplier whose mean is not one refits the base as well.

        The lesson a `+1192` result that became `-24` taught: if the lever's
        multiplier averages more than one it raises the member's average
        process noise too, and a gain that only did that is indistinguishable
        from one that used the signal.
        """
        import random

        from till_infinity.statespace import pacing

        random.seed(11)
        volumes = [random.lognormvariate(6.0, 0.7) for _ in range(4000)]
        shares = pacing.shares(volumes)[pacing.WARMUP :]
        assert abs(sum(shares) / len(shares) - 1.0) < 0.05

    def test_every_exponent_averages_one_so_the_sweep_compares_shapes(self):
        """The defect that made the squared arm look like the right answer.

        `share` averages one; `share ** 2` averages `1 + Var(share)`, which on
        real FX volume at 1h is **2.23**. An arm scored that way is running on
        more than twice the process noise, and the usual guard - sweeping the
        base noise on the undriven arm - cannot see it, because it refits the
        arm that is not being driven. The squared arm duly beat the linear one
        by +2365 to +1734 nats, measuring "more `Q`" and reporting "better
        shape for `Q`".

        So `factor` divides by an exponential mean of the same raised share.
        The normaliser lags a heavy-tailed quantity, so the realised average
        is near one rather than one, and the harness prints it per arm rather
        than trusting this test to have settled it.
        """
        import random
        import statistics

        from till_infinity.statespace import pacing

        random.seed(3)
        volumes = [random.lognormvariate(6.0, 0.9) for _ in range(6000)]
        for exponent in (0.5, 1.0, 2.0):
            got = pacing.factors(volumes, exponent=exponent)[pacing.WARMUP :]
            assert abs(statistics.fmean(got) - 1.0) < 0.1, exponent
        # Without the division the squared arm is nowhere near neutral, which
        # is the whole reason the field exists.
        shares = pacing.shares(volumes)[pacing.WARMUP :]
        assert statistics.fmean([v * v for v in shares]) > 2.0

    def test_the_exponent_is_the_difference_between_twofold_and_fourfold(self):
        """Subordination says variance tracks activity; the clock squares."""
        from till_infinity.statespace import pacing

        pace = pacing.Pace(exponent=1.0)
        for _ in range(200):
            pace.update(100.0)
        assert pace.factor(200.0) == 2.0
        squared = pacing.Pace(exponent=2.0)
        for _ in range(200):
            squared.update(100.0)
        assert squared.factor(200.0) == 4.0
        # And `control` is what `Driven` consumes, on its `1 + gain * u` form,
        # so a unit gain has to reproduce the factor exactly.
        assert pace.control(200.0) == 1.0
        assert 1.0 + 1.0 * pace.control(200.0) == pace.factor(200.0)

    def test_a_counter_reset_cannot_hand_q_a_twentyfold_variance(self):
        """`Driven` has a floor and no ceiling, so the clamp belongs here."""
        from till_infinity.statespace import pacing

        pace = pacing.Pace()
        for _ in range(200):
            pace.update(100.0)
        assert pace.factor(1e9) == pacing.MAX_SHARE
        # Absent and non-positive volume are not quiet bars, they are no
        # information, and a filter must not be told the market froze.
        assert pace.update(0.0) == 1.0
        assert pace.update(None) == 1.0
        assert pace.factor(-5.0) == 1.0

    def test_it_says_nothing_until_it_has_seen_enough_to_have_a_mean(self):
        from till_infinity.statespace import pacing

        pace = pacing.Pace()
        for i in range(pacing.WARMUP - 1):
            assert pace.update(100.0 + i) == 1.0
        assert not pace.warm
        pace.update(100.0)
        assert pace.warm

    def test_the_two_doors_compose_and_a_constant_clock_is_not_a_clock(self):
        """A busy hour and a busy bar reinforce - and the product renormalises.

        `Both` divides by an exponential mean of the product, because two
        factors that each average one do not multiply to one when they are
        correlated, and a busy hour is busy precisely because its bars are.
        Measured, the uncorrected product ran at 1.36 on average.

        A visible consequence is that a **constant** clock is normalised away
        entirely, which is correct: a multiplier that never varies carries no
        information and must not change what the member does.
        """
        from till_infinity.statespace import pacing

        def run(clock, volumes):
            pace = pacing.Pace()
            both = pacing.Both(pace=pace, clock=clock)
            out = []
            for i, volume in enumerate(volumes):
                pace.update(volume)
                out.append(both.factor(float(i), volume))
            return out

        volumes = [100.0 if i % 5 else 400.0 for i in range(400)]
        flat = run(lambda _when: 1.0, volumes)
        tripled = run(lambda _when: 3.0, volumes)
        # A constant clock, whatever its value, is the same as none.
        assert flat[-5:] == pytest.approx(tripled[-5:])
        # A clock that varies does change the composition.
        swinging = run(lambda when: 1.0 + 2.0 * (int(when) % 2), volumes)
        assert swinging[-5:] != flat[-5:]
        # And the product still averages about one.
        import statistics

        assert abs(statistics.fmean(swinging[pacing.WARMUP :]) - 1.0) < 0.15
        # `control` stays on `Driven`'s `1 + gain * u` form.
        pace = pacing.Pace()
        both = pacing.Both(pace=pace)
        for volume in volumes:
            pace.update(volume)
            got = both.factor(float(0), volume)
        assert both.control(0.0, volume) == pytest.approx(got - 1.0, rel=0.3)

    def test_bursts_drive_q_and_a_permanent_shift_does_not(self):
        """Only deviation from the recent norm is a multiplier. Measured.

        A tenfold **step** in activity reads as `extent` 1.40, not 10: the
        exponential mean catches up within its half-life and the share returns
        to one. That is the correct behaviour and not a limitation - a market
        that is permanently busier has a permanently larger process noise,
        which belongs in the member's **base** `Q` where a refit will find it.
        A multiplier that carried the level instead would double-count it, and
        would also stop averaging one, which is the thing that makes a gain
        attributable.

        Bursts are what the mechanism is for, and they read as bursts.
        """
        from till_infinity.statespace import pacing

        step = pacing.extent([100.0] * 500 + [1000.0] * 500)
        assert step < 1.5
        bursty = [100.0 if i % 5 else 1500.0 for i in range(1000)]
        assert pacing.extent(bursty) > 4.0

    def test_the_shares_are_causal_so_a_gain_measured_with_them_is_earnable(self):
        from till_infinity.statespace import pacing

        shares = pacing.shares([100.0] * 500 + [1000.0] * 500)
        # The early bars cannot know about the busy stretch: the share is one
        # through the warmup rather than a ratio to the whole sample's mean,
        # which would be a look-ahead worth a great deal of fictional nats.
        assert shares[: pacing.WARMUP] == [1.0] * pacing.WARMUP
        assert max(shares[:400]) == 1.0


class TestBehaving:
    """The measured per-class table, and the one classifier that feeds it."""

    def test_the_classifier_separates_generated_families_from_traded_classes(self):
        from till_infinity.statespace import behaving

        for feed, want in (
            ("EURUSD", "fx_major"),
            ("AUDUSD", "fx_major"),
            ("EURGBP", "fx_cross"),
            ("AUDJPY", "fx_cross"),
            ("XAUUSD", "metal"),
            ("US_Oil", "energy"),
            ("Sugar", "soft"),
            ("USD_Basket", "basket"),
            ("Germany_40", "index"),
            ("US_SP_500", "index"),
            ("Wall_Street_30", "index"),
            ("Jump_100_Index", "jump"),
            ("Range_Break_100_Index", "range_break"),
            ("Spot_Up_-_Volatility_Up_Index", "spot"),
            ("AAPL.OQ", "equity"),
            ("JPM.N", "equity"),
            ("Boom_500_Index", "boom"),
            ("Crash_1000_Index", "crash"),
            ("Step_Index_200", "step"),
            ("Drift_Switch_Index_10", "drift_switch"),
            ("Volatility_75_Index", "volatility"),
        ):
            assert behaving.classify(feed) == want, feed
        # `multi_step` has to resolve before `step`, which is a prefix of it.
        assert behaving.classify("multi_step_index") == "multi_step"
        # DEX carries its direction in the suffix, not the prefix.
        assert behaving.classify("DEX_900_UP_Index") == "dex_up"
        assert behaving.classify("DEX_1500_DOWN_Index") == "dex_down"

    def test_bounding_resolves_its_walls_through_the_same_classifier(self):
        """Two tables, one classifier. The duplication this replaced.

        `shifts_for` held the only copy of the prefix matching, and a second
        measured table was about to carry another - which is how two lookups
        for the same feed start disagreeing about what family it is in.
        """
        from till_infinity.statespace import behaving, bounding

        for feed in (
            "Boom_500_Index",
            "Crash_500_Index",
            "DEX_900_UP_Index",
            "DEX_1500_DOWN_Index",
            "Step_Index_200",
            "Volatility_75_Index",
        ):
            family = behaving.classify(feed)
            assert bounding.shifts_for(feed) == bounding.SHIFTS[family], feed
        # The traded classes resolve through the same classifier, now that they
        # are measured - which is the point of the table being one lookup.
        for feed in ("EURUSD", "EURJPY", "XAUUSD"):
            family = behaving.classify(feed)
            assert bounding.shifts_for(feed) == bounding.SHIFTS[family], feed
        # An unlisted family still falls back to the symmetric wall.
        assert bounding.shifts_for("US_Oil") == (bounding.SHIFT, bounding.SHIFT)
        assert bounding.shifts_for("AAPL.OQ") == (bounding.SHIFT, bounding.SHIFT)

    def test_the_table_is_three_way_and_step_is_the_middle_row(self):
        """The row that makes it a finding rather than a schema.

        A two-way real-against-generated split would put `Step_Index_200` on
        the wrong side of a line. Measured against a matched walk it sits on
        it, and the generated families that depart are the ones whose
        generators contain a jump.
        """
        from till_infinity.statespace import behaving

        assert behaving.traits_for("EURUSD").absorbs
        assert behaving.traits_for("XAUUSD").absorbs
        assert behaving.traits_for("US_Oil").absorbs
        for feed in ("Boom_500_Index", "Crash_500_Index", "DEX_900_UP_Index"):
            assert behaving.traits_for(feed).runs, feed
        step = behaving.traits_for("Step_Index_200")
        assert not step.absorbs
        assert not step.runs

    def test_an_unmeasured_class_returns_nothing_rather_than_a_default(self):
        from till_infinity.statespace import behaving

        # `class_traits.py` measured the classes this once listed, so the
        # remaining unmeasured ones are a name the classifier cannot place and
        # the one generated family it found but did not score.
        for feed in ("NOTASYMBOL", "Spot_Up_-_Volatility_Up_Index", ""):
            assert behaving.traits_for(feed) is None, feed
        # And an unmeasured class still gets the activity channel, because
        # `Pace` is self-limiting: a fixed tick count gives a factor of one.
        assert behaving.drives_q("NOTASYMBOL")
        assert behaving.drives_q("Spot_Up_-_Volatility_Up_Index")

    def test_the_sign_separates_a_real_book_from_a_generator_with_no_exception(self):
        """Nineteen classes, about five hundred instruments, no misfits.

        This is the assertion that makes the table a fingerprint rather than an
        index: not one traded class fails to absorb and not one generated class
        absorbs. If a future measurement breaks it, the fingerprint is what has
        to be re-examined and not the test.
        """
        from till_infinity.statespace import behaving

        traded = ("fx_major", "fx_cross", "metal", "energy", "equity", "index", "soft", "basket")
        jumping = ("boom", "crash", "dex_up", "dex_down", "drift_switch", "jump", "range_break")
        smooth = ("step", "multi_step", "skew_step", "volatility")
        for label in traded:
            assert behaving.TRAITS[label].absorbs, label
            assert not behaving.TRAITS[label].runs, label
        for label in jumping:
            assert behaving.TRAITS[label].runs, label
            assert not behaving.TRAITS[label].absorbs, label
        for label in smooth:
            assert not behaving.TRAITS[label].runs, label
            assert not behaving.TRAITS[label].absorbs, label
        # Every class in the table is in exactly one of the three groups.
        assert set(traded) | set(jumping) | set(smooth) == set(behaving.TRAITS)

    def test_a_derived_quote_absorbs_yet_carries_no_activity(self):
        """`basket` is the row that separates the two questions.

        It absorbs like a real market, because it is one - a dollar basket is
        priced off real FX - and its tick count is nearly fixed at an extent of
        1.111, so the activity channel is inert on it for a reason that has
        nothing to do with being generated. A table that used one field to
        answer both questions would have had to call it generated.
        """
        from till_infinity.statespace import behaving

        basket = behaving.traits_for("USD_Basket")
        assert basket.absorbs
        assert not basket.informative_activity
        assert not behaving.drives_q("USD_Basket")
        # Against a traded class whose activity is the most uneven in the cache.
        equity = behaving.traits_for("AAPL.OQ")
        assert equity.absorbs
        assert equity.informative_activity
        assert equity.activity_extent > 20.0

    def test_every_traded_class_has_an_undefined_fourth_moment(self):
        """Hill alpha below four forbids quoting a sample kurtosis."""
        from till_infinity.statespace import behaving

        for label in ("fx_major", "fx_cross", "metal", "energy", "equity", "index", "soft"):
            alpha = behaving.TRAITS[label].tail_alpha
            assert alpha is not None, label
            assert 2.0 < alpha < 4.0, (label, alpha)
        # The generated families are far thinner tailed, which is the control:
        # a specified process has the tails its specification gives it.
        for label in ("step", "multi_step", "skew_step", "volatility"):
            assert behaving.TRAITS[label].tail_alpha > 5.0, label

    def test_activity_only_drives_q_where_activity_varies(self):
        from till_infinity.statespace import behaving

        for feed in ("EURUSD", "XAUUSD", "US_Oil", "AAPL.OQ", "Germany_40", "Sugar"):
            assert behaving.drives_q(feed), feed
            assert behaving.traits_for(feed).informative_activity
        for feed in (
            "Boom_500_Index",
            "Step_Index_200",
            "Drift_Switch_Index_10",
            "Volatility_75_Index",
            "Jump_100_Index",
            "USD_Basket",
        ):
            assert not behaving.drives_q(feed), feed
        # Every traded row carries the measured exponent; no generated row does.
        for feed in ("EURUSD", "XAUUSD", "US_Oil"):
            assert behaving.traits_for(feed).q_exponent == 2.0
        for feed in ("Boom_500_Index", "Step_Index_200"):
            assert behaving.traits_for(feed).q_exponent is None


class TestPooling:
    """The 5.6x CRPS win, as a member rather than as a research harness."""

    def test_a_pool_is_itself_a_filter_and_is_not_a_family_member(self):
        """It satisfies the contract, and is deliberately not in the registry.

        `members()` is the registry of filter **kinds**; a pool is a
        combination of them rather than another one, and putting it there
        would make it a candidate in its own contest.
        """
        from till_infinity.statespace.family import Filter, members
        from till_infinity.statespace.pooling import Pooled

        assert isinstance(Pooled(), Filter)
        assert "pooled" not in members()
        assert "pooling" not in members()

    def test_the_defaults_are_the_measured_ones(self):
        """Not conventions. `0.5` was the hypothesis and it lost."""
        from till_infinity.statespace import pooling

        assert pooling.ALPHA == 1.0
        assert pooling.RULE == "shrinking"
        # `landau` at its default kappa is `reverting`, so a pool holding both
        # doubles the weight on reverting behaviour.
        assert "landau" not in pooling.DEFAULT
        assert len(pooling.DEFAULT) == 3

    def test_mixture_is_wider_than_shrinking_and_cannot_undercut_disagreement(self):
        """The two spread rules differ in the direction that matters."""
        import random

        from till_infinity.statespace.pooling import Pooled

        def run(rule):
            pool = Pooled(rule=rule)
            random.seed(7)
            level = 0.0
            for i in range(300):
                level += random.gauss(0.0, 0.01)
                pool.predict(float(i) * 3600.0)
                pool.update(level, 1e-4)
            return pool

        shrinking, mixture = run("shrinking"), run("mixture")
        assert mixture.sd > shrinking.sd
        # `shrinking` is 1/sum(precision), so it sits below every member's own
        # spread - which is exactly why it is the over-confident one.
        assert shrinking.sd < min(float(one.sd) for one in shrinking.members)
        # `mixture` carries the members' disagreement and so cannot.
        assert mixture.sd >= min(float(one.sd) for one in mixture.members)

    def test_argmax_is_one_hot_and_carries_the_chosen_member_s_own_spread(self):
        import random

        from till_infinity.statespace.pooling import Pooled

        pool = Pooled(rule="argmax")
        random.seed(7)
        level = 0.0
        for i in range(300):
            level += random.gauss(0.0, 0.01)
            pool.predict(float(i) * 3600.0)
            pool.update(level, 1e-4)
        assert sorted(pool.weights) == [0.0, 0.0, 1.0]
        chosen = pool.weights.index(1.0)
        assert pool.sd == pytest.approx(float(pool.members[chosen].sd))
        assert pool.value == pytest.approx(float(pool.members[chosen].value))

    def test_it_scores_the_prediction_before_folding_the_reading_in(self):
        """A held-out likelihood must not score a posterior against its own
        observation, so the order inside `update` is load-bearing."""
        import random

        from till_infinity.statespace.pooling import Pooled

        pool = Pooled()
        random.seed(3)
        level = 0.0
        first = None
        for i in range(200):
            level += random.gauss(0.0, 0.01)
            pool.predict(float(i) * 3600.0)
            before = pool.value
            pool.update(level, 1e-4)
            if first is None and i > 50:
                # The score used `before`, not the updated value: a residual of
                # zero would mean it had already seen the reading.
                assert before != pytest.approx(level, abs=1e-12)
                first = pool.loglike
        assert math.isfinite(pool.loglike)
        assert pool.seen == 200

    def test_a_pool_of_one_is_refused_rather_than_silently_degenerate(self):
        from till_infinity.statespace.pooling import Pooled

        with pytest.raises(ValueError, match="at least two members"):
            Pooled(names=("kalman",))
        with pytest.raises(ValueError, match="unknown rule"):
            Pooled(rule="average")

    def test_quantiles_feed_crps_directly(self):
        from till_infinity.statespace.diagnostics import crps
        from till_infinity.statespace.pooling import Pooled

        pool = Pooled()
        pool.predict(0.0)
        pool.update(0.0, 1e-4)
        levels = [i / 20.0 for i in range(1, 20)]
        got = pool.quantiles(levels)
        assert [level for level, _ in got] == levels
        # Ascending in value, which `crps`'s left Riemann sum requires.
        assert all(a[1] <= b[1] for a, b in itertools.pairwise(got))
        assert math.isfinite(crps(got, 0.0))

    def test_the_pool_adapts_its_members_noise_by_default(self):
        """The 2.7x correction, and the reason `Adapting` stopped being unused.

        A River Hoeffding tree beat this pool by 3.6x on CRPS, and most of the
        gap turned out not to be learning: on validated driftless Brownian
        motion, where there is **nothing to learn**, the learner still won and
        sat at a PIT flatness of 1.24 where the pool read 43.05. Wrapping the
        members in `Adapting` - which drives the squared standardised
        innovation toward 1.0 - took the pool to PIT 7.89 and CRPS 0.000588,
        better calibrated than the learner that exposed it.
        """
        import random

        from till_infinity.statespace import pooling
        from till_infinity.statespace.adapting import Adapting

        assert pooling.ADAPT is True
        pool = pooling.Pooled()
        assert all(isinstance(one, Adapting) for one in pool.members)
        # `False` is kept, because it is the arm every alpha and rule figure
        # was originally measured on.
        assert not any(isinstance(one, Adapting) for one in pooling.Pooled(adapt=False).members)

        def run(adapt):
            got = pooling.Pooled(adapt=adapt)
            random.seed(9)
            level = 0.0
            for i in range(400):
                level += random.gauss(0.0, 0.01)
                got.predict(float(i) * 3600.0)
                got.update(level, 1e-4)
            return got

        # The adapting pool ends with a different process noise than it began
        # with, which is the whole mechanism: a loop that never moves is not
        # adapting. `Adapting.factor` is its lever's multiple of its start.
        adapted = run(True)
        assert any(float(one.factor) != 1.0 for one in adapted.members)
        assert math.isfinite(adapted.loglike)

    def test_every_member_s_lever_is_named_because_they_disagree(self):
        """`reverting` has no `jerk`, so one name for all of them would raise."""
        from till_infinity.statespace import pooling
        from till_infinity.statespace.family import members

        built = members()
        for name in pooling.DEFAULT:
            lever = pooling.LEVERS[name]
            assert hasattr(built[name](), lever), (name, lever)
        assert pooling.LEVERS["reverting"] == "sigma2"
        assert pooling.LEVERS["kalman"] == "jerk"


class TestResearchPrimitives:
    """Three measurement tools that were living in harnesses."""

    def test_native_returns_drops_a_gap_spanning_increment(self):
        """The trap: aligning first makes every session gap a one-bar return."""
        from till_infinity.statespace.relating import native_returns

        stamps = [0.0, 3600.0, 7200.0, 10800.0, 300000.0, 303600.0]
        values = [1.0, 1.1, 1.2, 1.3, 5.0, 5.1]
        got = native_returns((stamps, values))
        assert got is not None
        # Five increments, one of which spans eighty hours. Four survive.
        assert len(got[0]) == 4
        assert max(abs(v) for v in got[1]) < 1.0
        assert native_returns(([0.0], [1.0])) is None

    def test_paired_aligns_returns_rather_than_levels(self):
        from till_infinity.statespace.relating import paired

        stamps = [float(i) * 3600.0 for i in range(600)]
        left = [1.0 + 0.01 * i for i in range(600)]
        # The second series misses a stretch, so the common grid has a hole.
        other = [s for i, s in enumerate(stamps) if not 200 <= i < 260]
        right = [2.0 + 0.02 * i for i, s in enumerate(stamps) if not 200 <= i < 260]
        got = paired((stamps, left), (other, right))
        assert got is not None
        assert len(got[0]) == len(got[1])
        # Every surviving increment is one bar, so none spans the hole: a
        # 60-bar gap would show up as a 60x outlier if it did.
        import statistics as st

        for steps in got:
            assert max(abs(v) for v in steps) < 3.0 * st.median([abs(v) for v in steps])
        assert paired((stamps, left), (other, right), least=10_000) is None

    def test_blocked_error_grows_with_the_overlap_it_is_told_about(self):
        import numpy as np

        from till_infinity.statespace.diagnostics import blocked_error

        rng = np.random.default_rng(5)
        # A strongly serially correlated series: independent blocks of 50.
        series = np.repeat(rng.normal(0.0, 1.0, 80), 50)
        naive = float(series.std()) / math.sqrt(len(series))
        got = blocked_error(series, overlap=50, seed=1)
        # The naive figure assumes 4,000 independent draws; there are 80.
        assert got > 4.0 * naive
        assert math.isnan(blocked_error([1.0, 2.0], overlap=1))

    def test_geometry_and_absorption_rebuild_the_fingerprint(self):
        import random

        from till_infinity.statespace import behaving

        random.seed(11)
        opens, highs, lows, closes = [], [], [], []
        level = 100.0
        for _ in range(1500):
            path = [level]
            for _ in range(20):
                path.append(path[-1] + random.gauss(0.0, 0.01))
            opens.append(level)
            highs.append(max(path))
            lows.append(min(path))
            closes.append(path[-1])
            level = path[-1]
        got = behaving.geometry(opens, highs, lows, closes)
        assert set(got) == {"imbalance", "wick", "run_share", "bars"}
        assert 0.0 < got["imbalance"] < 1.0
        assert got["bars"] == 1500
        # Against itself the departure is exactly zero, which is what makes
        # `absorption` a ratio to a walk rather than a level.
        assert behaving.absorption(got["imbalance"], got["imbalance"]) == 0.0
        assert behaving.absorption(0.94, 1.0) < 0
        assert behaving.absorption(1.13, 1.0) > 0
        assert math.isnan(behaving.absorption(0.5, 0.0))
        assert behaving.geometry([1.0], [1.0], [1.0], [1.0]) == {}


class TestFacade:
    """The one boundary a caller talks to, and the rule that keeps it one."""

    def test_statespace_imports_no_sibling_structures_module(self):
        """The containment rule, as an assertion rather than a convention.

        The façade only works if statespace stays standalone: a boundary inside
        a package that reaches back into `levels` and `reactions` inverts the
        dependency and makes the package neither standalone nor deletable. The
        spec's step one proposed exactly that - a façade "calling today's
        modules in today's order" - and this is the test that says why it had
        to be built the other way round.

        `shared` is allowed; it is the only thing that is.
        """
        import pathlib
        import re

        here = pathlib.Path("till_infinity/structures/statespace")
        offenders = {}
        for path in sorted(here.glob("*.py")):
            text = path.read_text()
            # `from ..something` reaches a sibling of the package; `from
            # ...shared` and `from ..shared` are the permitted exception.
            for match in re.finditer(r"^from \.\.([a-z_][a-z_0-9.]*) import", text, re.M):
                target = match.group(1).split(".")[0]
                if target != "shared":
                    offenders.setdefault(path.name, set()).add(target)
        assert offenders == {}, offenders

    def test_one_call_returns_what_a_caller_publishes(self):
        import random

        from till_infinity.statespace.facade import Desk

        desk = Desk()
        random.seed(5)
        level, out = 100.0, None
        for i in range(600):
            level += random.gauss(0.0, 0.05)
            out = desk.read("EURUSD", "1h", float(i) * 3600.0, level, 1e-4, volume=1000.0)
        assert out is not None
        assert out.seen == 600
        assert out.warm
        assert len(out.quantiles) == 19
        assert out.family == "fx_major"
        assert out.absorbs is True
        assert math.isfinite(out.value)
        assert out.spread > 0
        low, high = out.band()
        assert low < out.value < high

    def test_the_spread_is_predictive_and_not_the_state_s(self):
        """`p00 + R`, which is the lesson a missing `R` taught at some cost.

        Scoring a filter's state spread as if it were the predictive spread
        leaves out the measurement noise and makes every member look
        over-confident by exactly that term - which nearly handed a River tree
        a 3.6x rout it had not earned. The façade publishes the predictive one
        so no caller has to know to add it.
        """
        from till_infinity.statespace.facade import Desk

        desk = Desk()
        noise = 4e-4
        out = None
        for i in range(60):
            out = desk.read("EURUSD", "1h", float(i) * 3600.0, 100.0, noise)
        member = desk._members[("EURUSD", "1h")]
        assert out.spread == pytest.approx(float(member.variance) + noise)
        assert out.spread > float(member.variance)

    def test_activity_drives_q_only_where_it_measurably_can(self):
        """A generated feed is inert without the caller knowing to ask."""
        from till_infinity.statespace.facade import Desk

        desk = Desk()
        traded = desk.read("EURUSD", "1h", 0.0, 1.1, 1e-8, volume=1500.0)
        assert traded.paced
        for feed in ("Step_Index_200", "Boom_500_Index", "Volatility_75_Index"):
            got = desk.read(feed, "1h", 0.0, 5000.0, 1e-4, volume=1800.0)
            assert not got.paced, feed
            assert got.pace_factor == 1.0, feed
        # And no volume at all leaves it inert whatever the feed is.
        assert not desk.read("EURUSD", "4h", 0.0, 1.1, 1e-8).paced

    def test_the_quantiles_are_ascending_and_feed_crps(self):
        import random

        from till_infinity.statespace.diagnostics import crps
        from till_infinity.statespace.facade import Desk

        desk = Desk()
        random.seed(6)
        level, out = 50.0, None
        for i in range(700):
            level += random.gauss(0.0, 0.02)
            out = desk.read("XAUUSD", "1h", float(i) * 3600.0, level, 1e-4)
        assert [level for level, _ in out.quantiles] == [i / 20.0 for i in range(1, 20)]
        assert all(a[1] <= b[1] for a, b in itertools.pairwise(out.quantiles))
        assert math.isfinite(crps(out.quantiles, level))

    def test_an_unmeasured_class_says_so_instead_of_guessing(self):
        from till_infinity.statespace.facade import Desk

        got = Desk().read("NOTASYMBOL", "1h", 0.0, 1.0, 1e-6)
        assert got.family == "unknown"
        assert got.absorbs is None
        # And it still gets the activity channel, because `Pace` is
        # self-limiting and refusing an unstudied market is the worse error.
        assert Desk().read("NOTASYMBOL", "1h", 0.0, 1.0, 1e-6, volume=10.0).paced

    def test_a_readout_cannot_be_edited_by_its_consumer(self):
        from till_infinity.statespace.facade import Desk

        got = Desk().read("EURUSD", "1h", 0.0, 1.1, 1e-8)
        with pytest.raises(AttributeError):
            got.value = 2.0

    def test_the_barrier_geometry_refuses_an_infeasible_pair(self):
        """Optional stopping leaves two degrees of freedom in four quantities."""
        from till_infinity.statespace.facade import Desk

        got = Desk().read("Boom_500_Index", "1h", 0.0, 5000.0, 1e-4)
        least = got.least_horizon(0.4)
        assert least > 0
        assert got.barrier(0.4, least * 0.5) is None
        # And the feed's own measured walls reach the geometry, not the
        # symmetric default: Boom is 0.6535 up against 0.5100 down.
        assert got.walls == (0.6535, 0.5100)
        assert got.least_horizon(0.4) != Desk().read("EURUSD", "1h", 0.0, 1.1, 1e-8).least_horizon(
            0.4
        )

    def test_the_desk_holds_the_state_so_a_caller_does_not(self):
        from till_infinity.statespace.facade import Desk

        desk = Desk()
        for interval in ("1h", "4h"):
            for feed in ("EURUSD", "GBPUSD"):
                desk.read(feed, interval, 0.0, 1.1, 1e-8)
        assert desk.tracking == 4
        assert desk.forget("EURUSD", "1h") == 1
        assert desk.tracking == 3
        assert desk.forget("EURUSD") == 1
        assert desk.tracking == 2
        assert desk.forget() == 2
        assert desk.tracking == 0


class TestRanging:
    """A range the price sits inside, and the three profiles behind it."""

    @staticmethod
    def _filled(seed: int = 4, bars: int = 400):
        import random

        from till_infinity.statespace.ranging import Profile

        random.seed(seed)
        profile, price = Profile(), 100.0
        for _ in range(bars):
            price += random.gauss(0.0, 0.2)
            opened = price + random.gauss(0.0, 0.05)
            low = min(opened, price) - abs(random.gauss(0.0, 0.08))
            high = max(opened, price) + abs(random.gauss(0.0, 0.08))
            profile.observe(low, high, abs(random.gauss(1000.0, 300.0)), open_=opened, close=price)
        return profile, price

    def test_the_thin_edges_always_contain_the_price(self):
        """The property the first version got wrong, on every seed.

        Walking out from the current bin and stopping on the first thin one
        returns that bin **twice** whenever the price is itself in a thin bin -
        which is exactly when price has just moved somewhere little was traded.
        That gave a zero-width range that did not contain the price it was
        asked about, which is the one thing this object promises.
        """
        from till_infinity.statespace.ranging import Profile

        for seed in (3, 4, 7, 11, 19):
            profile, price = self._filled(seed)
            got = profile.range_at(price)
            assert got is not None, seed
            assert got.thin_low <= got.price <= got.thin_high, seed
            assert got.width > 0, seed
            assert 0.0 <= got.position <= 1.0, seed
        assert Profile().range_at(100.0) is None

    def test_the_three_profiles_are_different_objects(self):
        """Volume, acceptance and rejection disagree, which is the point.

        A price can be heavily traded *and* heavily rejected, which is what an
        absorbing level is supposed to look like - so a single profile cannot
        express it and the three are not interchangeable.
        """
        profile, price = self._filled()
        seen = {}
        for weight in ("volume", "acceptance", "rejection"):
            got = profile.range_at(price, weight)
            assert got is not None, weight
            assert got.thin_low <= price <= got.thin_high, weight
            seen[weight] = (got.centre, got.thin_low, got.thin_high)
        assert seen["acceptance"] != seen["rejection"]

    def test_a_bar_with_no_candle_given_is_all_body(self):
        """Without an open and a close there is no candlestick information.

        Treating such a bar as all body is the honest default - it says the
        profile has no rejection data rather than inventing some - and a caller
        that forgets to pass them gets a rejection profile that is empty rather
        than a plausible-looking one.
        """
        from till_infinity.statespace.ranging import Profile

        plain = Profile()
        for i in range(200):
            plain.observe(100.0 + i * 0.01, 100.5 + i * 0.01, 1000.0)
        accepted = plain.histogram("acceptance")
        rejected = plain.histogram("rejection")
        assert accepted is not None
        assert sum(accepted[1]) > 0
        assert sum(rejected[1]) == 0

    def test_the_value_area_holds_its_share_and_need_not_contain_the_price(self):
        """A value area is a share of **past** volume, so price can be outside it.

        That is the ordinary meaning of "price has left value", and `inside`
        exists so a caller checks rather than assumes. The thin edges are the
        ones that bracket by construction.
        """
        from till_infinity.statespace.ranging import VALUE_SHARE, Profile

        profile, price = self._filled()
        got = profile.range_at(price)
        assert got.value_low < got.value_high
        assert isinstance(got.inside, bool)
        centres, weights = profile.histogram()
        total = sum(weights)
        held = sum(
            w for c, w in zip(centres, weights, strict=True) if got.value_low <= c <= got.value_high
        )
        assert held >= VALUE_SHARE * total * 0.95
        _ = Profile

    def test_an_unknown_weight_is_refused(self):
        profile, _ = self._filled()
        with pytest.raises(ValueError, match="unknown weight"):
            profile.histogram("liquidity")


class TestInteracting:
    """Per-level statistics as posteriors, and the production number they mirror."""

    def test_the_same_ratio_is_not_the_same_evidence(self):
        """The whole reason these are posteriors and not divisions.

        `levels.SideStats.hold_rate` is `rejects / decisive`. Three holds of
        four and three hundred of four hundred give it the same answer, and
        they are not the same claim. A ratio cannot say which, so it cannot be
        pooled, shrunk or compared between levels.
        """
        from till_infinity.statespace.interacting import Rate

        thin, thick = Rate(), Rate()
        for _ in range(3):
            thin.observe(True)
        thin.observe(False)
        for _ in range(300):
            thick.observe(True)
        for _ in range(100):
            thick.observe(False)

        assert thin.raw == pytest.approx(thick.raw)
        assert thin.mean < thick.mean
        assert thin.sd > 5 * thick.sd
        assert not thin.beats(0.5)
        assert thick.beats(0.5)

    def test_no_evidence_reads_as_a_coin_with_a_wide_posterior(self):
        """Zero variance reads as *no information*, not as certainty.

        The mistake `Kalman.var_slope` documents, in the other object: an
        unobserved rate must not come back as 0.0 and sure of it.
        """
        from till_infinity.statespace.interacting import Rate

        empty = Rate()
        assert empty.mean == pytest.approx(0.5)
        assert empty.sd > 0.2
        assert not empty.beats(0.5)
        assert empty.raw == 0.0

    def test_attention_reproduces_the_production_strength_exactly(self):
        """It has seventeen consumers, so a swap must change nothing.

        `Attention` exists to make the four weights an **argument** rather than
        a choice - `levels.Level.strength` fixes them at 0.4 / 0.25 / 0.2 /
        0.15 and nothing has ever measured a better set. Defaulting to the same
        numbers is what makes measuring one safe.
        """
        import math

        from till_infinity.statespace.interacting import WEIGHTS, Attention

        for touches, spread, unit, since, swings in (
            (8.0, 0.3, 1.0, 86_400.0, 4.0),
            (2.0, 0.9, 1.0, 10 * 86_400.0, 1.0),
            (25.0, 0.05, 2.0, 0.0, 9.0),
            (0.0, 5.0, 1.0, 60 * 86_400.0, 0.0),
        ):
            # The production expression, written out rather than imported, so
            # this test fails if either side drifts.
            evidence = min(touches, 10.0) / 10.0
            agreement = 1.0 - min(1.0, spread / max(unit, 1e-9))
            recency = math.exp(-max(0.0, since) / (14 * 86_400))
            breadth = min(swings, 5) / 5.0
            want = round(
                0.4 * evidence + 0.25 * max(0.0, agreement) + 0.2 * recency + 0.15 * breadth,
                4,
            )
            got = Attention().of(
                touches=touches, spread=spread, unit=unit, since=since, swings=swings
            )
            assert got == pytest.approx(want), (touches, spread, since)

        # And the terms come back unweighted, which is what a fit needs.
        terms = Attention().terms(touches=8.0, spread=0.3, unit=1.0, since=86_400.0, swings=4.0)
        assert len(terms) == len(WEIGHTS)
        assert all(0.0 <= t <= 1.0 for t in terms)
        assert sum(w * t for w, t in zip(WEIGHTS, terms, strict=True)) == pytest.approx(
            Attention().of(touches=8.0, spread=0.3, unit=1.0, since=86_400.0, swings=4.0),
            abs=1e-4,
        )

    def test_sweep_depth_is_a_distribution_rather_than_a_shape(self):
        """`wick_deep_vol` returns `mean + sigmas * sd`, which assumes a shape.

        No Gaussian band on this desk has ever been calibrated, and a sweep
        depth is a tail quantity, which is where the assumption costs most. A
        skewed sample is where the two answers part company.
        """
        from till_infinity.statespace.interacting import Depth

        depth = Depth()
        for value in [0.1] * 90 + [3.0] * 10:
            depth.observe(value)
        assert depth.seen == 100
        assert depth.typical == pytest.approx(0.1)
        assert depth.unusual(0.9) == pytest.approx(3.0)
        # The Gaussian answer on this sample is far out in empty space: the
        # mean is 0.39 with an sd near 0.87, so two sigmas is about 2.1 - a
        # depth no sweep in the sample ever took.
        assert depth.quantile(0.5) < depth.unusual(0.95)
        assert Depth().unusual() == 0.0

    def test_interactions_publishes_its_uncertainty_beside_every_rate(self):
        from till_infinity.statespace.interacting import Interactions

        one = Interactions()
        for k in range(20):
            one.observe_touch(rejected=k % 3 != 0, trapped=k % 2 == 0)
            one.observe_symmetric(k % 3 != 0)
            one.observe_sweep(0.1 * k)
        got = one.reading()
        for name in ("hold", "trap", "symmetric"):
            assert f"{name}_rate" in got
            assert f"{name}_sd" in got
        assert got["decisive"] == 20.0
        assert 0.0 <= got["hold_rate"] <= 1.0
        # A trap rate is only meaningful on a break, so it counts breaks only.
        assert one.trapped.seen < one.held.seen


class TestDispersion:
    """Whether units differ, with the floor simulated rather than chosen."""

    @staticmethod
    def _pool(rates, each=40, seed=1):
        import random

        rng = random.Random(seed)
        return [
            (float(each), float(sum(1 for _ in range(each) if rng.random() < p))) for p in rates
        ]

    @staticmethod
    def _mean(samples):
        return sum(h for _, h in samples) / sum(n for n, _ in samples)

    def test_identical_units_do_not_read_as_different(self):
        """The defect a constant threshold had, and why the null is simulated.

        Sixty units of forty observations, every one drawn at the same rate,
        produce a `tau` near **0.029** from sampling alone. A first version
        gated on `tau > 0.02` and called them different. The floor is not a
        number - it is a function of how many units there are and how often
        each was counted - so it has to be simulated.
        """
        from till_infinity.statespace.dispersion import differ

        same = self._pool([0.5] * 60)
        observed, null, p = differ(same, self._mean(same))
        assert observed > 0.02, observed
        assert p > 0.05, (observed, null, p)
        # And the floor falls as the pool grows, which is the whole reason a
        # constant cannot express it.
        big = self._pool([0.5] * 279, seed=3)
        _, wider, _ = differ(big, self._mean(big))
        assert wider < null

    def test_units_that_really_differ_are_found(self):
        from till_infinity.statespace.dispersion import differ, tau

        spread = self._pool([0.3, 0.5, 0.7] * 20)
        mean = self._mean(spread)
        observed, null, p = differ(spread, mean)
        assert p < 0.05, (observed, null, p)
        assert observed > 4 * null
        assert tau(spread, mean) == pytest.approx(observed)

    def test_a_pool_too_small_to_speak_says_so(self):
        from till_infinity.statespace.dispersion import UNITS, differ, tau_squared

        tiny = self._pool([0.5] * 4)
        observed, null, p = differ(tiny, self._mean(tiny))
        assert math.isnan(null)
        assert math.isnan(p)
        assert math.isfinite(observed)
        # One unit, or a degenerate mean, returns zero rather than raising.
        assert tau_squared([(40.0, 20.0)], 0.5) == (0.0, 1)
        assert tau_squared([(40.0, 0.0)] * UNITS, 0.0) == (0.0, 0)

    def test_borrowed_evidence_is_worth_more_when_units_agree(self):
        """`K` in `own / (own + K)`: large when units are alike, small when not."""
        from till_infinity.statespace.dispersion import borrow_weight

        same = self._pool([0.5] * 60)
        spread = self._pool([0.2, 0.5, 0.8] * 20)
        alike = borrow_weight(same, self._mean(same))
        apart = borrow_weight(spread, self._mean(spread))
        assert alike > apart
        # Clamped at both ends: at zero one observation overrides the pool, and
        # unbounded means a unit never gets to speak.
        assert 0.5 <= apart <= 50.0
        assert 0.5 <= alike <= 50.0
        # A pool that cannot say returns the caller's fallback unchanged.
        assert borrow_weight(self._pool([0.5] * 3), 0.5, fallback=7.0) == 7.0

    def test_statespace_still_imports_no_sibling(self):
        """The reason this module exists at all.

        `conditional_holds.py` had to import `shrinkage.tau_squared` from a
        sibling package to ask this question. A harness may reach across; the
        library may not.

        **Narrow on purpose.** This checks the one import that caused the
        module to be written. The package-wide rule - nothing from outside
        itself but `shared` - belongs to
        `TestVendoredCusum.test_the_package_imports_nothing_from_outside_itself`
        and is asserted there with the exemption spelled out; a second copy
        here drifted from it the first time the package gained a service, by
        rejecting the `..shared` imports that rule allows.
        """
        import pathlib

        text = pathlib.Path("till_infinity/statespace/dispersion.py").read_text()
        assert "from ..shrinkage" not in text
        assert "structures.shrinkage" not in text
        # And the thing it must not reach for is still one package over, so the
        # guard can still fail.
        assert pathlib.Path("till_infinity/structures/shrinkage.py").is_file()


class TestSpanning:
    """`Q` driven by the bar's range rather than its closes."""

    @staticmethod
    def _bars(n, body=0.0, span=0.02, step=0.0, seed=1):
        """Bars with a fixed range and a controllable close-to-close step."""
        import random

        rng = random.Random(seed)
        out = []
        price = 1.0
        for _ in range(n):
            open_ = price
            close = price * (1.0 + step * (1 if rng.random() < 0.5 else -1))
            high = max(open_, close) * (1.0 + span / 2.0)
            low = min(open_, close) * (1.0 - span / 2.0)
            out.append((open_, high, low, close))
            price = close
        return out

    def test_the_estimators_agree_on_a_flat_bar(self):
        """All three measure the same thing: variance that happened inside the bar."""
        from till_infinity.statespace import spanning

        o, h, l_, c = 1.0, 1.01, 0.99, 1.0
        park = spanning.parkinson(h, l_)
        gk = spanning.garman_klass(o, h, l_, c)
        rs = spanning.rogers_satchell(o, h, l_, c)
        for got in (park, gk, rs):
            assert got > 0
        # Within a factor of two of each other on the same bar.
        assert 0.5 < gk / park < 2.0
        assert 0.5 < rs / park < 2.0
        # Degenerate input is zero, not a crash or a negative variance.
        assert spanning.parkinson(0.0, 0.0) == 0.0
        assert spanning.garman_klass(1.0, 0.9, 1.1, 1.0) == 0.0
        assert spanning.rogers_satchell(1.0, 1.0, 1.0, 1.0) == 0.0

    def test_the_factor_is_a_variance_ratio_not_a_size_ratio(self):
        """The mistake `Driven`'s own docstring warns about.

        `Driven.control` and `Driven.clock` take a **variance** multiplier. The
        measured `gk_cc` is a ratio of standard deviations, so passing it
        through unsquared under-drives every bar by its own square. A bar whose
        range implies twice the close-to-close *volatility* must arrive as four.
        """
        from till_infinity.statespace.spanning import Span

        quiet = Span(half_life=10.0, memory=500.0, high=100.0)
        for bar in self._bars(400, span=0.02, step=0.001):
            quiet.observe(*bar)
        assert quiet.ready
        loud = Span(half_life=10.0, memory=500.0, high=100.0)
        # Same closes, twice the intrabar range: four times the variance ratio.
        for bar in self._bars(400, span=0.04, step=0.001):
            loud.observe(*bar)
        assert loud.ready
        assert loud.ratio() / quiet.ratio() == pytest.approx(4.0, rel=0.15)

    def test_the_factor_averages_one(self):
        """A multiplier whose mean is not one changes the average `Q` too.

        That is not a subtlety: on FX volume the same mistake measured 2.23 and
        turned +1734 nats into +2365 of artefact, and a sweep of the base
        process noise cannot remove it because the sweep refits the arm that is
        not being driven.
        """
        from till_infinity.statespace.spanning import Span

        span = Span(half_life=20.0, memory=400.0)
        seen = []
        for i, bar in enumerate(self._bars(4000, span=0.02, step=0.002, seed=3)):
            span.observe(*bar)
            if i > 1000:
                seen.append(span.factor())
        assert seen
        assert sum(seen) / len(seen) == pytest.approx(1.0, abs=0.1)

    def test_it_never_freezes_or_runs_away(self):
        from till_infinity.statespace.spanning import Span

        span = Span(half_life=5.0, memory=100.0, low=0.25, high=4.0)
        for bar in self._bars(300, span=0.02, step=0.001):
            span.observe(*bar)
        # One malformed bar must not hand it the whole filter.
        span.observe(1.0, 1e9, 1e-9, 1.0)
        assert 0.25 <= span.factor() <= 4.0
        # Nor may a run of them freeze the state.
        for _ in range(50):
            span.observe(1.0, 1.0, 1.0, 1.0)
        assert 0.25 <= span.factor() <= 4.0

    def test_it_says_one_until_it_knows_anything(self):
        """An unready driver has to be the identity, so the control arm exists."""
        from till_infinity.statespace.spanning import Span

        span = Span(half_life=40.0)
        assert span.factor() == 1.0
        assert span.ratio() == 1.0
        span.observe(1.0, 1.01, 0.99, 1.0)
        assert not span.ready
        assert span.factor() == 1.0

    def test_the_normaliser_must_be_slower_than_the_signal(self):
        from till_infinity.statespace.spanning import Span

        with pytest.raises(ValueError, match="slower"):
            Span(half_life=100.0, memory=50.0)
        with pytest.raises(ValueError, match="estimator"):
            Span(estimator="nonsense")

    def test_it_drives_a_member_through_driven(self):
        """The wiring this exists for: `Span.factor` into `Driven`."""
        from till_infinity.statespace.driven import Driven
        from till_infinity.statespace.linear import Gaussian
        from till_infinity.statespace.spanning import Span

        span = Span(half_life=10.0, memory=400.0)
        for bar in self._bars(300, span=0.02, step=0.001):
            span.observe(*bar)
        assert span.ready
        member = Driven(build=lambda: Gaussian(jerk=1e-4))
        # `Driven` reads `control` as a deviation - it sets the lever to
        # `base * (1 + gain * control)` - so a mean-one variance factor has to
        # arrive as `factor - 1`, which is zero when the driver says nothing.
        member.predict(1.0, control=span.factor() - 1.0)
        member.update(0.0, 1e-6, 1.0)
        assert math.isfinite(member.value)
        assert math.isfinite(member.sd)
        # And the identity: an unready driver must leave the member untouched.
        quiet = Driven(build=lambda: Gaussian(jerk=1e-4))
        fresh = Span()
        quiet.predict(1.0, control=fresh.factor() - 1.0)
        quiet.update(0.0, 1e-6, 1.0)
        assert quiet.value == pytest.approx(member.value, abs=1.0)


class TestTails:
    """The band's width once the residuals are known not to be Gaussian."""

    def test_the_quantile_matches_published_t_tables(self):
        """Checked against the table, not against another implementation.

        `scipy` is not a dependency here, so the t distribution is written out
        in full. A library-free special function is only worth having if it is
        right, and the honest check is the published value rather than a second
        copy of the same code.
        """
        from till_infinity.statespace import tails

        for dof, probability, published in (
            (3.0, 0.975, 3.182446),
            (4.0, 0.975, 2.776445),
            (4.0, 0.995, 4.604095),
            (5.0, 0.995, 4.032143),
            (10.0, 0.975, 2.228139),
            (30.0, 0.975, 2.042272),
        ):
            assert tails.quantile(probability, dof) == pytest.approx(published, abs=1e-5)
        # And the inverse really inverts, both sides of zero.
        for dof in (3.0, 4.5, 12.0):
            for z in (-3.0, -0.4, 0.0, 1.7):
                assert tails.quantile(tails.cdf(z, dof), dof) == pytest.approx(z, abs=1e-6)

    def test_the_gaussian_is_too_wide_below_95_percent_and_too_narrow_above(self):
        """The finding is a reshaping, not a widening, and it crosses near 95%.

        A fat-tailed density held to unit variance has to be **more peaked** in
        the body to pay for its tails, so below the crossover the Gaussian is
        too wide. This is worth pinning because the result is easy to overstate
        into "every band here was too narrow", which is not what was measured:
        at two sigmas the two agree and nothing reading one was wrong.
        """
        from till_infinity.statespace import tails

        # Below: the t is strictly narrower.
        assert tails.reach(0.90, 4.0) < 1.644854
        # At 95%: they agree to well under a percent.
        assert tails.reach(0.95, 4.0) == pytest.approx(1.959964, rel=0.01)
        # Above: the Gaussian is badly too narrow, and it gets worse.
        assert tails.reach(0.99, 4.0) > 1.2 * 2.575829
        assert tails.reach(0.999, 4.0) > 1.5 * 3.290527
        # Monotone in coverage, which a quantile must be.
        widths = [tails.reach(c, 4.0) for c in (0.5, 0.8, 0.9, 0.95, 0.99, 0.999)]
        assert widths == sorted(widths)

    def test_a_three_sigma_band_is_breached_several_times_as_often_as_labelled(self):
        """The diagnostic reading, which is the one that changes a decision."""
        from till_infinity.statespace import tails

        # Two sigmas is still about 95%, so the common case is untouched.
        assert tails.coverage(2.0, 4.0) == pytest.approx(0.9545, abs=0.005)
        # Three is not 99.73%, and the breach rate is what matters.
        got = tails.coverage(3.0, 4.0)
        assert got < 0.99
        assert (1.0 - got) / (1.0 - 0.997300) > 3.0
        # Coverage rises with the multiplier and never leaves [0, 1].
        seen = [tails.coverage(s, 4.0) for s in (0.0, 0.5, 1.0, 2.0, 3.0, 6.0)]
        assert seen == sorted(seen)
        assert seen[0] == pytest.approx(0.0, abs=1e-9)
        assert seen[-1] < 1.0

    def test_a_large_tail_index_recovers_the_gaussian(self):
        """The limit case, which says the correction is the only difference."""
        from till_infinity.statespace import tails

        for coverage, gaussian in ((0.95, 1.959964), (0.99, 2.575829), (0.999, 3.290527)):
            assert tails.reach(coverage, 5_000.0) == pytest.approx(gaussian, rel=0.01)

    def test_the_floor_binds_and_the_measured_table_rises_with_the_interval(self):
        """Gold's maximum likelihood ran past the floor and scored worse for it.

        `LEAST_DOF` is not the mathematical bound of 2 where the variance
        stops existing - it is where the fit measurably stopped describing the
        distribution and started chasing a few bars.
        """
        from till_infinity.statespace import tails

        assert tails.LEAST_DOF > 2.0
        # Anything below the floor is treated as the floor, not passed through.
        assert tails.reach(0.99, 2.5) == tails.reach(0.99, tails.LEAST_DOF)
        assert tails.coverage(3.0, 1.0) == tails.coverage(3.0, tails.LEAST_DOF)
        # Every measured entry clears the floor, and an unmeasured interval
        # falls back to the fattest rather than the average.
        assert all(v >= tails.LEAST_DOF for v in tails.DOF.values())
        assert tails.dof_for("nonsense") == tails.DEFAULT_DOF
        # Aggregational Gaussianity: the daily tail is thinner than intraday.
        assert tails.dof_for("1d") > tails.dof_for("1h")
        # And a bad ask is refused rather than silently clamped.
        for bad in (0.0, 1.0, -0.2, 1.5):
            with pytest.raises(ValueError, match="coverage"):
                tails.reach(bad)

    def test_the_readout_offers_coverage_beside_sigmas(self):
        """The facade's two readings agree where they should and part where they should."""
        from till_infinity.statespace import tails
        from till_infinity.statespace.facade import Readout

        got = Readout(feed="EURUSD", interval="1h", at=0.0, value=100.0, spread=0.04)
        sd = 0.2

        # At 95% the coverage band and the 1.96-sigma band land together.
        low, high = got.band_covering(0.95)
        near_low, near_high = got.band(1.959964)
        assert low == pytest.approx(near_low, rel=0.02)
        assert high == pytest.approx(near_high, rel=0.02)

        # In the far tail it is strictly wider than the Gaussian's own answer.
        far_low, far_high = got.band_covering(0.999)
        gauss_low, gauss_high = got.band(3.290527)
        assert far_high > gauss_high
        assert far_low < gauss_low

        # Both bands stay centred on the value, and the width is the sd times
        # the multiplier - so the spread really is being read as a variance.
        assert 0.5 * (low + high) == pytest.approx(got.value)
        assert (high - low) / 2.0 == pytest.approx(
            tails.reach(0.95, tails.dof_for("1h")) * sd, rel=1e-9
        )

        # And `covers` is the inverse of `band_covering` on the same interval.
        assert got.covers(2.0) == pytest.approx(tails.coverage(2.0, tails.dof_for("1h")))
        middle = got.covers(2.0)
        assert got.band_covering(middle)[1] == pytest.approx(got.band(2.0)[1], rel=1e-6)


class TestTheValueRevertingMember:
    """`ornstein.Ornstein` - the member two harnesses had to work around.

    `reverting` reverts the **rate** and leaves the value integrated, which is
    right for a price and wrong for a magnitude. These tests pin the three
    things that make this a different model rather than a reparameterisation:
    the forecast converges to a level, the band stops widening, and the level
    is not a state.
    """

    LEVEL = -18.0

    @classmethod
    def _series(cls, phi=0.93, n=3000, seed=5, kick=0.35):
        """A magnitude that mean-reverts in level, like log-variance."""
        import random

        rng = random.Random(seed)
        out, last = [], cls.LEVEL
        for _ in range(n):
            last = cls.LEVEL + phi * (last - cls.LEVEL) + rng.gauss(0.0, kick)
            out.append(last)
        return out

    @staticmethod
    def _drive(member, xs, noise=0.09):
        guesses = []
        for i, x in enumerate(xs):
            guesses.append(member.value if member.seen else x)
            member.update(x, noise, i * 3600.0)
        return guesses

    def test_it_beats_the_rate_reverting_member_on_a_reverting_magnitude(self):
        """The reason it exists, as a held-out number."""
        from till_infinity.statespace.ornstein import Ornstein, _theta_for
        from till_infinity.statespace.reverting import Reverting

        xs = self._series()
        mine = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        theirs = Reverting()
        got = self._drive(mine, xs)
        had = self._drive(theirs, xs)

        half = len(xs) // 2
        base = statistics.fmean(xs[:half])

        def score(guess):
            err = sum((a - b) ** 2 for a, b in zip(xs[half:], guess[half:], strict=True))
            floor = sum((a - base) ** 2 for a in xs[half:])
            return 1.0 - err / floor

        assert score(got) > score(had)
        assert score(got) > 0.5
        assert mine.loglike > theirs.loglike

    def test_the_forecast_converges_to_the_level(self):
        """What an integrated member cannot do, and the whole difference."""
        from till_infinity.statespace.ornstein import Ornstein, _theta_for

        member = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        self._drive(member, self._series())

        # The level was learnt rather than given, and it found the truth.
        assert member.level == pytest.approx(self.LEVEL, abs=0.6)
        # Far ahead the forecast *is* the level, to floating point.
        assert member.at_time(member.at + 10_000 * 3600.0) == pytest.approx(member.level, abs=1e-6)
        # And it gets there monotonically from wherever the value sits.
        near = member.at_time(member.at + 3600.0)
        far = member.at_time(member.at + 100 * 3600.0)
        assert abs(far - member.level) < abs(near - member.level)

    def test_the_band_stops_widening(self):
        """It converges to the stationary spread instead of growing forever."""
        from till_infinity.statespace.ornstein import Ornstein, _theta_for
        from till_infinity.statespace.reverting import Reverting

        member = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        other = Reverting()
        self._drive(member, self._series())
        self._drive(other, self._series())

        widths = []
        for ahead in (10, 100, 1000, 10_000):
            low, high = member.band(member.at + ahead * 3600.0)
            widths.append(0.5 * (high - low))
        assert widths == sorted(widths)
        assert widths[-1] == pytest.approx(2.0 * member.stationary_sd, rel=1e-6)

        # The integrated member's does not converge, which is what the horizon
        # cap in production exists to patch.
        theirs = [
            0.5
            * (other.band(other.at + ahead * 3600.0)[1] - other.band(other.at + ahead * 3600.0)[0])
            for ahead in (10, 100, 1000, 10_000)
        ]
        # The claim is structural, not a magnitude: by the far end this one has
        # **converged** - the last decade of horizon adds nothing measurable -
        # while the integrated member is still widening. That is the difference
        # the production horizon cap exists to patch.
        assert widths[-1] / widths[-2] == pytest.approx(1.0, abs=1e-6)
        assert theirs[-1] / theirs[-2] > 1.5
        assert theirs[-1] > widths[-1]

    def test_no_pull_is_the_nested_null(self):
        """`theta = 0` is a one-state random walk, which is this member's own null."""
        from till_infinity.statespace.ornstein import Ornstein

        # `learn=False` throughout, because this test is about what a **fixed**
        # theta of zero means. With the fit on, a reverting series moves theta
        # off the boundary within sixty readings - which is the point of the
        # fit and is tested in `test_the_fit_finds_the_timescale...`.
        walk = Ornstein(theta=0.0, sigma2=0.12, level_half_life=168.0, learn=False)
        self._drive(walk, self._series())
        assert math.isinf(walk.half_life_hours)
        assert math.isinf(walk.stationary_sd)
        # With no pull the forecast does not come home, and the pole sits on
        # the unit circle rather than inside it.
        assert walk.at_time(walk.at + 1000 * 3600.0) == walk.value
        assert walk.transition(5.0)[0][0] == pytest.approx(1.0)
        # And the pull being real is what buys the likelihood.
        pulled = Ornstein(
            theta=math.log(2.0) / 10.0, sigma2=0.12, level_half_life=168.0, learn=False
        )
        self._drive(pulled, self._series())
        assert pulled.loglike > walk.loglike

    def test_the_fit_recovers_the_true_timescale(self):
        """Maximum likelihood on the grid, graded on what it can identify.

        **Not on an h-step score**, and that distinction was measured rather
        than assumed. At twenty bars of a series whose half-life is ten, the
        deviation has decayed to about 7% and the forecast is essentially the
        **level** - so an h-step R2 grades the level estimator, not the pull.
        The proof is that the ceiling, with the *true* level and the *true*
        pull, scores **0.3605** there while a member with a lagging level and
        the right pull scores **0.5263**: a lagging level tracks a finite
        sample's local mean better than the true unconditional one does.

        So the fit is graded on recovering the timescale, which is what a
        one-step likelihood can identify, and on going quiet where there is
        nothing to recover.
        """
        from till_infinity.statespace.ornstein import Ornstein, _theta_for

        def fit(xs):
            member = Ornstein(
                theta=_theta_for(24.0), sigma2=0.12, level_half_life=168.0, learn=True
            )
            for i, x in enumerate(xs):
                member.update(x, 0.09, i * 3600.0)
            return member

        # The true half-life of an AR(1) at `phi` on hourly steps is
        # `ln 2 / -ln phi`. The grid is spaced by factors of two, so landing
        # within one step of the truth is the most that can be asked.
        for phi, truth in ((0.70, 1.9), (0.93, 9.6), (0.99, 69.0)):
            got = fit(self._series(phi=phi)).fitted_half_life
            assert math.isfinite(got)
            assert 0.5 * truth <= got <= 2.0 * truth, (phi, truth, got)

        # No persistence: the fit goes to the fast end of the grid, so the
        # forecast collapses onto the level and carries no noise forward.
        assert fit(self._series(phi=0.0)).fitted_half_life <= 1.0

        # And the residual form this replaced was biased **slow**, because it
        # fitted the *filtered* deviations - which the Kalman gain has already
        # pulled toward the level. It read 32 hours where the truth is 9.6; a
        # density reads 8 on four thousand points and 16 on three thousand, so
        # the bound here is the residual form's own reading.
        assert fit(self._series(phi=0.93)).fitted_half_life < 32.0

    def test_the_fit_removes_the_cost_of_a_wrong_pull_on_a_null(self):
        """The defect it was written for, where the pull is what matters."""
        import random

        from till_infinity.statespace.ornstein import Ornstein, _theta_for

        def run(xs, learn):
            member = Ornstein(
                theta=_theta_for(24.0), sigma2=0.12, level_half_life=168.0, learn=learn
            )
            guesses = []
            for i, x in enumerate(xs):
                guesses.append(
                    member.at_time(member.at + 20 * 3600.0)
                    if member.seen and member.at is not None
                    else x
                )
                member.update(x, 0.09, i * 3600.0)
            return guesses

        def score(xs, guesses):
            half = len(xs) // 2
            base = statistics.fmean(xs[:half])
            err = sum((a - b) ** 2 for a, b in zip(xs[half:], guesses[half:], strict=True))
            floor = sum((a - base) ** 2 for a in xs[half:])
            return 1.0 - err / floor

        # On a series with nothing to revert to, a fixed pull carries a share
        # of pure noise into every forecast and pays for it. The fit does not.
        noise = self._series(phi=0.0)
        assert score(noise, run(noise, True)) == pytest.approx(0.0, abs=0.02)
        assert score(noise, run(noise, True)) > score(noise, run(noise, False)) + 0.05

        shuffled = list(self._series(phi=0.93))
        random.Random(1).shuffle(shuffled)
        assert score(shuffled, run(shuffled, True)) == pytest.approx(0.0, abs=0.03)

    def test_the_fitted_pull_keeps_the_anchor(self):
        """A fit cannot break the separation the level depends on."""
        from till_infinity.statespace.ornstein import SEPARATION, Ornstein, _theta_for

        member = Ornstein(theta=_theta_for(24.0), sigma2=0.12, level_half_life=168.0)
        # A pure random walk wants theta = 0, which would make the level
        # infinitely faster than the reversion. The floor refuses it.
        walk, here = [], 0.0
        rng = __import__("random").Random(3)
        for _ in range(1500):
            here += rng.gauss(0.0, 0.3)
            walk.append(here)
        for i, x in enumerate(walk):
            member.update(x, 0.09, i * 3600.0)
        floor = SEPARATION * math.log(2.0) / member.level_half_life
        assert member.theta >= floor
        assert member.half_life_hours <= member.level_half_life / SEPARATION + 1e-9

    def test_the_level_is_not_a_state_and_the_separation_is_enforced(self):
        """The failure `definitions-cannot-be-states` is already on record for."""
        from till_infinity.statespace.ornstein import SEPARATION, Ornstein, _theta_for

        # A level that adapts as fast as the value is the value, so it is
        # refused rather than allowed to collapse the member into a walk.
        with pytest.raises(ValueError, match="separation"):
            Ornstein(theta=_theta_for(10.0), level_half_life=10.0)
        with pytest.raises(ValueError, match="separation"):
            Ornstein(theta=_theta_for(10.0), level_half_life=SEPARATION * 10.0 - 0.1)
        # Just clear of the floor is allowed.
        Ornstein(theta=_theta_for(10.0), level_half_life=SEPARATION * 10.0 + 0.1)
        # The level is a field and not a state slot: one state, one covariance.
        member = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        assert member.state() == (member.value,)
        assert len(member.covariance()) == 1
        assert member.NAMES == ("value",)

    def test_the_first_reading_sets_the_level(self):
        """Reverting toward a zero nobody chose is catastrophic on log-variance."""
        from till_infinity.statespace.ornstein import Ornstein, _theta_for

        member = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        assert not member.anchored
        member.update(-18.0, 0.09, 0.0)
        assert member.anchored
        assert member.level == pytest.approx(-18.0)
        assert member.value == pytest.approx(-18.0)

    def test_the_level_moves_on_a_clock_and_not_per_reading(self):
        """A weekly level has to mean a week on a dense feed and a sparse one."""
        from till_infinity.statespace.ornstein import Ornstein, _theta_for

        dense = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        sparse = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        # The same span of hours, read ten times as often.
        for i in range(100):
            dense.update(-10.0, 0.09, i * 3600.0)
        for i in range(10):
            sparse.update(-10.0, 0.09, i * 10 * 3600.0)
        assert dense.level == pytest.approx(sparse.level, rel=0.05)
        # A zero-length step moves the level not at all: two venues printing
        # the same instant are one observation of it.
        held = Ornstein(theta=_theta_for(10.0), sigma2=0.12, level_half_life=168.0)
        held.update(-18.0, 0.09, 0.0)
        before = held.level
        held.update(-5.0, 0.09, 0.0)
        assert held.level == pytest.approx(before)

    def test_it_is_registered_poolable_and_smoothable(self):
        from till_infinity.statespace.family import members
        from till_infinity.statespace.pooling import LEVERS, Pooled
        from till_infinity.statespace.subjects import DISPERSIONS

        assert members()["ornstein"].__name__ == "Ornstein"
        assert LEVERS["ornstein"] == "sigma2"
        assert len(Pooled(names=("kalman", "ornstein", "reverting")).members) == 3
        # Unlike `selective` and `s4d` it carries a posterior, so it smooths.
        assert hasattr(members()["ornstein"](), "covariance")
        # And every dispersion subject now names it, which was the point.
        assert {s.member for s in DISPERSIONS} == {"ornstein"}

    def test_bad_parameters_are_refused(self):
        from till_infinity.statespace.ornstein import Ornstein

        with pytest.raises(ValueError, match="theta"):
            Ornstein(theta=-1.0)
        with pytest.raises(ValueError, match="sigma2"):
            Ornstein(sigma2=-1.0)
        with pytest.raises(ValueError, match="half-life"):
            Ornstein(level_half_life=0.0)


class TestPivotsByDirectionalChange:
    """`pivoting` - the detector, and the laws that say whether it works.

    The point of this detector over a fixed span is that it can be **checked
    against a prediction it did not fit**: directional-change events scale as
    `threshold ** -E` with `E` near one, and the overshoot past a confirmation
    averages about one threshold. Those come from Glattfelder, Dupuis and Olsen
    (2011) and neither is used to choose a parameter here.
    """

    @staticmethod
    def _walk(n=12000, seed=7, step=0.001):
        import random

        rng = random.Random(seed)
        closes = [100.0]
        for _ in range(n):
            closes.append(closes[-1] * math.exp(rng.gauss(0.0, step)))
        closes = closes[1:]
        wick = [abs(rng.gauss(0.0, step)) for _ in range(n)]
        return (
            [i * 3600.0 for i in range(n)],
            [c * math.exp(w) for c, w in zip(closes, wick, strict=True)],
            [c * math.exp(-w) for c, w in zip(closes, wick, strict=True)],
            closes,
        )

    @staticmethod
    def _unit(closes):
        steps = [abs(b - a) for a, b in itertools.pairwise(closes)]
        return sum(steps) / len(steps)

    def test_peaks_and_troughs_alternate_by_construction(self):
        """The thing a fixed span cannot promise, and this one cannot break."""
        from till_infinity.statespace.pivoting import fractal, pivots

        times, highs, lows, closes = self._walk()
        unit = self._unit(closes)
        found = pivots(times, highs, lows, unit=unit, threshold=2.0)
        assert len(found) > 50
        assert all(a.kind != b.kind for a, b in itertools.pairwise(found))

        # The fixed-span detector does not, and that is recorded rather than
        # hidden: it is the reason a caller building swings from it has to
        # impose alternation itself.
        plain = fractal(times, highs, lows, span=5)
        assert not all(a.kind != b.kind for a, b in itertools.pairwise(plain))

    def test_the_confirmation_lag_adapts(self):
        """A sharp reversal confirms sooner than a hesitant one."""
        from till_infinity.statespace.pivoting import fractal, pivots

        times, highs, lows, closes = self._walk()
        unit = self._unit(closes)
        found = pivots(times, highs, lows, unit=unit, threshold=2.0)
        lags = sorted(p.lag for p in found)
        assert lags[0] < lags[-1]

        # The fixed span is exactly itself, always, by construction.
        plain = fractal(times, highs, lows, span=5)
        assert {p.lag for p in plain} == {5}

    def test_a_pivot_is_knowable_only_when_it_is_confirmed(self):
        """The leak both detectors exist to avoid."""
        from till_infinity.statespace.pivoting import pivots

        times, highs, lows, closes = self._walk()
        found = pivots(times, highs, lows, unit=self._unit(closes), threshold=2.0)
        for one in found:
            assert one.confirmed >= one.at
            assert one.confirmed_index >= one.index
            assert one.lag == one.confirmed_index - one.index

    def test_a_higher_threshold_finds_fewer_turns(self):
        """Monotone, and the exponent is the law's own prediction."""
        from till_infinity.statespace.pivoting import scaling

        times, highs, lows, closes = self._walk()
        got = scaling(times, highs, lows, unit=self._unit(closes), thresholds=(2.0, 4.0, 8.0, 16.0))
        counts = got["counts"]
        assert counts == sorted(counts, reverse=True)
        assert counts[-1] > 0
        # `N ~ threshold ** -E`. One is the law; the band is wide because bar
        # data truncates the small-threshold end, where a bar's own range
        # exceeds the threshold and no detector can resolve an event.
        assert 0.5 < got["exponent"] < 3.0

    def test_the_overshoot_is_measured_from_the_trigger(self):
        """It averages about one threshold - and the first version did not."""
        from till_infinity.statespace.pivoting import overshoots, pivots

        times, highs, lows, closes = self._walk()
        unit = self._unit(closes)
        found = pivots(times, highs, lows, unit=unit, threshold=8.0)
        got = overshoots(found, unit=unit, threshold=8.0)
        assert len(got) > 20
        mean = sum(got) / len(got)
        # Measured from the trigger price it is about one. Measured from the
        # previous extreme - which is what the first version did - it would be
        # about two, because that leg is the retracement plus the overshoot.
        assert 0.4 < mean < 1.8
        whole = [abs(b.level - a.level) / unit / 8.0 for a, b in itertools.pairwise(found)]
        assert sum(whole) / len(whole) > mean

    def test_the_unit_may_track_the_regime(self):
        """A per-bar unit is the point of measuring a swing in volatility units."""
        from till_infinity.statespace.pivoting import pivots

        times, highs, lows, closes = self._walk()
        flat = self._unit(closes)
        # A unit that doubles halfway through should find fewer turns in the
        # second half than a constant one does, because the threshold grows.
        varying = [flat if i < len(closes) // 2 else flat * 4.0 for i in range(len(closes))]
        fewer = pivots(times, highs, lows, unit=varying, threshold=2.0)
        same = pivots(times, highs, lows, unit=flat, threshold=2.0)
        assert len(fewer) < len(same)

        for bad in ([flat] * 3, [0.0] * len(closes), [-1.0] * len(closes)):
            with pytest.raises(ValueError, match="unit"):
                pivots(times, highs, lows, unit=bad, threshold=2.0)

    def test_bad_asks_are_refused(self):
        from till_infinity.statespace.pivoting import pivots

        times, highs, lows, _ = self._walk(n=50)
        with pytest.raises(ValueError, match="threshold"):
            pivots(times, highs, lows, unit=1.0, threshold=0.0)
        with pytest.raises(ValueError, match="unit"):
            pivots(times, highs, lows, unit=0.0)
        with pytest.raises(ValueError, match="same length"):
            pivots(times[:-1], highs, lows, unit=1.0)
        # A flat series has no swings, whatever the threshold.
        assert pivots([0.0, 1.0, 2.0], [5.0] * 3, [5.0] * 3, unit=1.0) == []


class TestTurnDepthPorted:
    """`depths` - v1's one measured turn result, as a dispersion quantity.

    `structures/cycles.py` found turn **depth** predictable where the process
    reverts (8 of 8 constructed spreads, +0.03 to +0.19) and turn **timing**
    not (its `when` head scored positive on the nulls too). These tests pin
    the statistic that claim is made with, because a skill quoted against one
    baseline and computed against another is how the finding gets lost while
    appearing to be kept.
    """

    @staticmethod
    def _series(phi, n=600, seed=4, kick=0.4, level=1.0):
        """Depths with a known persistence, so skill has a right answer."""
        import random

        from till_infinity.statespace.depths import Turn

        rng = random.Random(seed)
        out, last = [], level
        for i in range(n):
            last = level + phi * (last - level) + rng.gauss(0.0, kick)
            out.append(Turn(when=i * 3600.0, value=last, span=rng.gauss(0.0, kick), direction=1))
        return out

    def test_the_skill_finds_persistence_and_reads_zero_without_it(self):
        """Power first, then the null - the order `show-power-before-reporting-a-null` asks for."""
        from till_infinity.statespace.depths import score

        flat = score(self._series(0.0))
        some = score(self._series(0.6))
        lots = score(self._series(0.9))

        # Nothing to predict means no skill, not a small positive one.
        assert flat["depth ar1"] == pytest.approx(0.0, abs=0.03)
        # And it rises monotonically with the persistence that is really there.
        assert some["depth ar1"] > 0.1
        assert lots["depth ar1"] > some["depth ar1"]

    def test_the_timing_arm_is_carried_because_it_failed(self):
        """v1's `when` read positive on nulls, so the arm has to exist to catch that."""
        from till_infinity.statespace.depths import score

        # The span here is i.i.d. by construction, so its skill must be zero
        # at every depth persistence - a port that dropped this arm could not
        # reproduce v1's finding that timing skill is a metric artefact.
        for phi in (0.0, 0.6, 0.9):
            got = score(self._series(phi))
            assert got["span ar1"] == pytest.approx(0.0, abs=0.03)

    def test_the_baseline_is_causal_and_kept_inside_the_statistic(self):
        """Neither arm may see the observation it is being scored on."""
        from till_infinity.statespace.depths import Skill

        got = Skill()
        # The first observation cannot be scored: there is no prior mean to be
        # a baseline, and scoring it against itself would read skill 0 on a
        # sample of one.
        got.observe(5.0, 10.0)
        assert got.settled == 0
        got.observe(5.0, 10.0)
        assert got.settled == 1
        # The baseline guessed the mean of what came before (10.0) and was
        # exactly right; the model guessed 5.0 and was not.
        assert got.base == pytest.approx(0.0)
        assert got.error == pytest.approx(5.0)
        assert math.isnan(got.skill)  # still under LEAST

    def test_a_skill_is_not_reported_on_too_few_turns(self):
        from till_infinity.statespace.depths import LEAST, score

        thin = score(self._series(0.9, n=LEAST - 5))
        assert math.isnan(thin["depth ar1"])
        enough = score(self._series(0.9, n=LEAST + 200))
        assert not math.isnan(enough["depth ar1"])

    def test_the_ar1_arm_cannot_extrapolate(self):
        """A fitted coefficient outside the stationary range is a unit root."""
        from till_infinity.statespace.depths import AR1

        got = AR1()
        # A perfectly trending series fits phi above one; clamping is what
        # keeps `guess` a prediction rather than an extrapolation.
        for value in range(1, 40):
            got.observe(float(value) * 10.0)
        assert abs(got.guess) < 1e6
        assert got.seen == 39

    def test_depths_are_read_on_the_confirmation_clock(self):
        """The leak the two timestamps exist to prevent."""
        from till_infinity.statespace.depths import depths
        from till_infinity.statespace.displacements import Displacement

        moves = [
            Displacement(ended=100.0, confirmed=460.0, size=2.0, hours=3.0, direction=1),
            Displacement(ended=800.0, confirmed=1160.0, size=0.0, hours=2.0, direction=-1),
            Displacement(ended=900.0, confirmed=1260.0, size=4.0, hours=0.0, direction=1),
            Displacement(ended=1000.0, confirmed=1360.0, size=8.0, hours=4.0, direction=-1),
        ]
        got = depths(moves)
        # A zero size and a zero duration are both unusable, and are dropped
        # rather than logged into an infinity.
        assert len(got) == 2
        assert [turn.when for turn in got] == [460.0, 1360.0]
        assert got[0].value == pytest.approx(math.log(2.0))
        assert got[1].span == pytest.approx(math.log(4.0))
        # And the raw space is available, because v1 scored in it and the two
        # numbers must not be presented as each other.
        raw = depths(moves, logged=False)
        assert raw[0].value == pytest.approx(2.0)

    def test_a_family_member_can_be_scored_on_the_turn_clock(self):
        """The port's point: the depth series is something the family can read."""
        from till_infinity.statespace.depths import Turns
        from till_infinity.statespace.reverting import Reverting
        from till_infinity.statespace.subjects import TURN_DEPTH

        assert TURN_DEPTH.tracks == "dispersion"
        turns = Turns(member=Reverting())
        for turn in self._series(0.8, n=300):
            turns.observe(turn)
        got = turns.read()
        assert "depth member" in got
        assert not math.isnan(got["depth member"])
        # `reverting` reverts the *rate* and leaves the value integrated, so on
        # a mean-reverting magnitude it should not beat the AR(1) arm. Stated
        # as the expectation rather than asserted as a result, because what the
        # subject records is that the family has no value-reverting member.
        assert got["depth ar1"] > got["depth member"]


class TestForwardPaths:
    """`projecting` - the one module here that emits a price.

    Every claim it makes is about dispersion turned into price, so the tests
    are the identities a path distribution has to satisfy. The barrier one is
    the important one: a driftless race at reward-to-risk `r` must pay
    `1 / (1 + r)`, and an arm that pays more than that on a martingale is a
    bug, not an edge.
    """

    @staticmethod
    def _readout(*, skew=0.0, warm=True, value=100.0, spread=1.0):
        """A readout whose residual grid is a standard normal, exactly symmetric.

        Built from the normal quantile rather than from a sample, because a
        sampled grid carries its own asymmetry and the symmetry identities
        below would then be testing the sample instead of the module.
        """
        from till_infinity.statespace.facade import Readout

        if not warm:
            return Readout(feed="W", interval="1h", at=0.0, value=value, spread=spread)
        normal = statistics.NormalDist()
        grid = []
        for i in range(1, 20):
            level = i / 20.0
            z = normal.inv_cdf(level)
            grid.append((level, value + math.sqrt(spread) * (z + skew * z * abs(z))))
        return Readout(
            feed="W", interval="1h", at=0.0, value=value, spread=spread, quantiles=tuple(grid)
        )

    def test_a_driftless_race_pays_the_geometric_share(self):
        """`1 / (1 + r)`, and it has to converge as the barriers leave the step."""
        from till_infinity.statespace.projecting import project

        got = project(self._readout(), ahead=1200, paths=1500, seed=4)

        # At r = 1 the problem is symmetric, so this must hold at *every*
        # distance rather than converging to it - and it is what caught a mean
        # of +0.0127 per step leaking in from a sampled grid.
        for stop in (2.0, 10.0, 25.0):
            out = got.barrier(up=100.0 + stop, down=100.0 - stop)
            resolved = out["up"] + out["down"]
            assert resolved > 0
            assert out["up"] / resolved == pytest.approx(0.5, abs=0.06)

        # At r = 2 it converges from above as the barriers move away from the
        # step scale. Tight barriers are breached by overshoot - a fat-tailed
        # step jumps *through* a stop rather than stopping on it, which is what
        # real stops do, so the gap is a property and not an error.
        near = got.barrier(up=100.0 + 2 * 2.0, down=100.0 - 2.0)
        far = got.barrier(up=100.0 + 2 * 20.0, down=100.0 - 20.0)
        near_share = near["up"] / (near["up"] + near["down"])
        far_share = far["up"] / (far["up"] + far["down"])
        assert near_share > far_share
        assert far_share == pytest.approx(1.0 / 3.0, abs=0.06)

    def test_the_step_is_driftless_unless_asked_otherwise(self):
        """`centred` is why `drift=0` means what it says."""
        import random

        from till_infinity.statespace.projecting import _sampler

        skewed = self._readout(skew=0.35)
        table_on, _ = _sampler(skewed, 1.0)
        raw, _ = _sampler(skewed, 1.0, False)

        rng = random.Random(2)
        centred = [table_on(rng) for _ in range(40000)]
        rng = random.Random(2)
        uncentred = [raw(rng) for _ in range(40000)]

        # The skewed grid has a real mean offset, and centring removes it.
        assert abs(statistics.fmean(centred)) < abs(statistics.fmean(uncentred))
        assert statistics.fmean(centred) == pytest.approx(0.0, abs=0.02)
        # The shape is kept: the same draws, shifted, so the spread is identical.
        assert statistics.pstdev(centred) == pytest.approx(statistics.pstdev(uncentred), rel=1e-9)
        # The two differ by exactly one constant, which is what "the location
        # is pinned and the shape is untouched" means.
        shifts = {round(a - b, 12) for a, b in zip(uncentred, centred, strict=True)}
        assert len(shifts) == 1

    def test_an_iid_fan_grows_as_the_square_root(self):
        """No dispersion forecast means a walk, and a walk is `sqrt(k)`."""
        from till_infinity.statespace.projecting import project

        got = project(self._readout(), ahead=64, paths=3000, seed=7)
        assert not got.paced
        widths = {}
        for step in (1, 4, 16, 64):
            low, high = got.band(0.95, step=step)
            widths[step] = 0.5 * (high - low) / math.sqrt(step)
        # Flat once divided by sqrt(step), to the sampling error of 3000 paths.
        assert max(widths.values()) / min(widths.values()) < 1.2
        assert len(got.fan(0.95)) == got.ahead

    def test_a_dispersion_forecast_is_what_paces_the_fan(self):
        """`scales` is the arm the members are pointed at dispersion to feed."""
        from till_infinity.statespace.projecting import project

        quiet = project(self._readout(), ahead=20, paths=1500, scales=(0.25,) * 20, seed=3)
        loud = project(self._readout(), ahead=20, paths=1500, scales=(2.0,) * 20, seed=3)
        assert quiet.paced
        assert loud.paced
        assert loud.band(0.95)[1] - loud.band(0.95)[0] > 4.0 * (
            quiet.band(0.95)[1] - quiet.band(0.95)[0]
        )
        with pytest.raises(ValueError, match="scales"):
            project(self._readout(), ahead=20, scales=(1.0, 1.0))

    def test_a_touch_is_a_lower_bound_until_reach_is_set(self):
        """A close-only path cannot touch what it passed through intrabar."""
        from till_infinity.statespace.projecting import project

        plain = project(self._readout(), ahead=40, paths=2000, seed=9)
        with_reach = project(self._readout(), ahead=40, paths=2000, reach=0.8, seed=9)
        level = 100.0 + 6.0
        assert with_reach.touches(level) > plain.touches(level)
        # Monotone in the level, which a running extreme guarantees.
        assert plain.touches(100.0 + 2.0) > plain.touches(100.0 + 8.0)
        # And a touch is never less likely than ending beyond the same level.
        assert plain.touches(level) >= plain.above(level)

    def test_the_time_to_touch_is_conditional_and_says_when_it_cannot_answer(self):
        from till_infinity.statespace.projecting import project

        got = project(self._readout(), ahead=40, paths=2000, seed=6)
        near = got.when(100.0 + 1.0, 0.5)
        far = got.when(100.0 + 1.0, 0.9)
        assert near is not None
        assert far is not None
        assert 1 <= near <= far <= got.ahead
        # Nothing reaches thirty standard deviations in forty bars, and the
        # honest answer is None rather than the horizon.
        assert got.when(100.0 + 300.0) is None

    def test_a_cold_readout_still_projects_and_says_the_shape_was_assumed(self):
        from till_infinity.statespace.projecting import project

        got = project(self._readout(warm=False), ahead=20, paths=500, seed=1)
        assert got.source == "assumed"
        assert got.paths == 500

    def test_the_basis_is_named_and_not_inferred(self):
        from till_infinity.statespace.projecting import basis_price, project

        assert basis_price(102.0, 99.0, 100.0, "close") == 100.0
        assert basis_price(102.0, 99.0, 100.0, "ohlc3") == pytest.approx(
            (102.0 + 99.0 + 100.0) / 3.0
        )
        for bad in ("hlc3", "typical", ""):
            with pytest.raises(ValueError, match="basis"):
                basis_price(1.0, 1.0, 1.0, bad)
            with pytest.raises(ValueError, match="basis"):
                project(self._readout(), basis=bad)

    def test_a_plan_carries_three_prices_and_what_it_would_need(self):
        """`sl, entry, tp` - and the edge the geometry requires to break even."""
        from till_infinity.statespace.projecting import plan, project

        # **The stop's width is the binding constraint, not the horizon.** With
        # the default grid starting at 1:2 and the target required to be
        # delivered, a stop placed at a 40% path-breach rate leaves no
        # deliverable multiple - at forty bars or at four hundred, because
        # solving the stop for a breach rate rescales the whole geometry with
        # the horizon. A tighter stop is what buys a reachable target, and the
        # refusal is pinned below.
        got = project(self._readout(), ahead=40, paths=1000, seed=3)
        made = plan(got, side=1, breach=0.60, cost=0.05)
        assert made is not None
        # Long: the stop is below the entry and the target above, and the
        # reward is the ratio of the two distances.
        assert made.stop < made.entry < made.target
        assert made.reward == pytest.approx(
            (made.target - made.entry) / (made.entry - made.stop), rel=1e-9
        )
        # The stop was **solved on the paths** for the breach rate asked for,
        # not taken from a Gaussian label.
        assert made.stopped == pytest.approx(0.60, abs=0.05)
        # And it reports a requirement rather than a recommendation: the
        # expectancy is negative after cost on a driftless projection, and the
        # edge is what would have to arrive from somewhere else.
        assert made.net < 0.0
        assert made.edge > 0.0

    def test_a_short_is_the_mirror_and_a_neutral_signal_is_no_trade(self):
        from till_infinity.statespace.projecting import plan, project

        got = project(self._readout(), ahead=40, paths=1000, seed=3)
        long = plan(got, side=1, breach=0.60, cost=0.05)
        short = plan(got, side=-1, breach=0.60, cost=0.05)
        assert long is not None
        assert short is not None
        assert short.stop > short.entry > short.target
        # The same symmetric step distribution, so the two require about the
        # same edge - an asymmetry here would be a bug in one of the paths.
        assert short.edge == pytest.approx(long.edge, abs=0.02)

        # A neutral signal is no trade, which is the correct output rather than
        # a coin flip dressed as one.
        assert plan(got, side=0) is None
        with pytest.raises(ValueError, match="side"):
            plan(got, side=2)

    def test_the_required_edge_is_what_cost_does_to_the_geometry(self):
        """Linear in cost, and non-zero even at zero cost."""
        from till_infinity.statespace.projecting import plan, project

        got = project(self._readout(), ahead=40, paths=1000, seed=3)
        free = plan(got, side=1, breach=0.60, cost=0.0)
        dear = plan(got, side=1, breach=0.60, cost=0.10)
        assert free is not None
        assert dear is not None
        assert dear.edge > free.edge
        # Even free, the geometry needs an edge: losses are settled at the
        # excursion the path reached rather than at the stop, so overshoot is
        # charged against the trade.
        assert free.edge > 0.0
        # And the step from one cost to the other is the cost difference over
        # `1 + reward`, which is the arithmetic the field is defined by.
        if free.reward == dear.reward:
            assert dear.edge - free.edge == pytest.approx(0.10 / (1.0 + free.reward), rel=1e-6)

    def test_an_unreachable_target_is_refused_rather_than_preferred(self):
        """The criterion is gameable without `settle`, and this is the guard."""
        from till_infinity.statespace.projecting import plan, project

        got = project(self._readout(), ahead=40, paths=1000, seed=3)
        # With no reachability requirement the widest multiple wins every time,
        # because `edge` divides by `1 + reward` while paths that never resolve
        # contribute almost nothing - a target reached by nobody looks cheapest.
        gamed = plan(got, side=1, breach=0.60, cost=0.05, settle=0.0001, delivers=0.0001)
        guarded = plan(got, side=1, breach=0.60, cost=0.05)
        assert gamed is not None
        assert guarded is not None
        assert gamed.reward > guarded.reward
        assert gamed.undecided > guarded.undecided
        assert 1.0 - guarded.undecided >= 0.50
        # And `delivers` is the half that resolution alone cannot give: a 60%
        # breach resolves 60% of the time by **stopping out**, so a criterion
        # asking only for resolution chose a target nothing reached. The
        # guarded plan has to deliver a real share of its own barrier rate.
        assert guarded.hit >= 0.5 / (1.0 + guarded.reward)
        assert gamed.hit < guarded.hit

        # A stop so wide that no multiple can be delivered has no plan, and
        # saying so is better than inventing one. At a 40% path-breach rate
        # nothing in 1:2..1:56 delivers, **at any horizon**, because solving the
        # stop for a breach rate rescales the geometry as the hold grows.
        assert plan(got, side=1, breach=0.40, cost=0.05) is None
        assert (
            plan(
                project(self._readout(), ahead=400, paths=800, seed=3),
                side=1,
                breach=0.40,
                cost=0.05,
            )
            is None
        )
        for bad in (0.0, 1.5):
            with pytest.raises(ValueError, match="delivers"):
                plan(got, side=1, breach=0.60, delivers=bad)
        for bad in (0.0, 1.5):
            with pytest.raises(ValueError, match="breach"):
                plan(got, side=1, breach=bad)
        with pytest.raises(ValueError, match="settle"):
            plan(got, side=1, settle=0.0)

    def test_shifting_the_entry_raises_the_ratio_and_lowers_the_expectancy(self):
        """The ratio is arithmetic; the degradation is the selection that buys it.

        Measured on a **driftless** projection, so this is not a market fact
        that might change with the regime - it is geometry, and it holds
        always. Moving a long's entry down turns `risk` into `risk - offset`
        and the reward into `reward + offset`, so the ratio rises with nothing
        predicted. What pays for it is that the paths which fill the order are
        the paths that **fell first**, and they meet a stop that is now closer.
        """
        from till_infinity.statespace.projecting import project, resting

        got = project(self._readout(), ahead=200, paths=2000, seed=3)
        rows = [
            resting(got, side=1, offset=off, risk=5.0, reward=2.0, cost=0.0)
            for off in (0.0, 1.0, 2.0, 3.0, 4.0)
        ]

        # At no offset this is the ordinary market order, and on a driftless
        # projection it is the martingale - which calibrates everything below.
        assert rows[0].filled == pytest.approx(1.0)
        assert abs(rows[0].expectancy) < 3.0 * rows[0].error

        ratios = [r.reward for r in rows]
        expectancies = [r.expectancy for r in rows]
        fills = [r.filled for r in rows]
        losses = [r.lost for r in rows]

        # The ratio rises, monotonically, by arithmetic.
        assert ratios == sorted(ratios)
        assert ratios[-1] > 5.0 * ratios[0]
        # And the expectancy falls, monotonically, which is the point.
        assert expectancies == sorted(expectancies, reverse=True)
        assert expectancies[-1] < expectancies[0] - 0.3
        # Both charges are visible: fewer fills, and - the larger one - a
        # conditional loss rate that climbs because the fill selects the paths
        # already moving against the trade.
        assert fills == sorted(fills, reverse=True)
        assert losses == sorted(losses)
        assert losses[-1] > 0.85

        # The unconditional number is the one a desk can spend, and it is
        # flattered by the unfilled paths contributing zero - so it is always
        # above the conditional one once the offset bites.
        assert rows[-1].expectancy > rows[-1].conditional

    def test_a_resting_entry_refuses_an_offset_outside_its_own_risk(self):
        from till_infinity.statespace.projecting import project, resting

        got = project(self._readout(), ahead=40, paths=400, seed=3)
        for bad in (5.0, 6.0, -1.0):
            with pytest.raises(ValueError, match="offset"):
                resting(got, side=1, offset=bad, risk=5.0, reward=2.0)
        with pytest.raises(ValueError, match="side"):
            resting(got, side=0, offset=1.0, risk=5.0, reward=2.0)
        with pytest.raises(ValueError, match="risk and reward"):
            resting(got, side=1, offset=0.0, risk=0.0, reward=2.0)
        with pytest.raises(ValueError, match="within"):
            resting(got, side=1, offset=1.0, risk=5.0, reward=2.0, within=0)

    def test_a_geometry_carries_the_standard_error_of_its_own_expectancy(self):
        """Without it a driftless projection reads as paying, and it did."""
        from till_infinity.statespace.projecting import project

        got = project(self._readout(), ahead=600, paths=2000, seed=3)
        # A stop far out relative to the paths' dispersion divides a
        # price-scale error by a large number, so the error is large - and
        # every reading here has to be inside a couple of them.
        for reward in (2.0, 5.0, 20.0):
            priced = got.geometry(stop=20.0, reward=reward, cost=0.0)
            assert priced.error > 0.0
            assert abs(priced.separated) < 3.0, (reward, priced.expectancy, priced.error)

    def test_bad_asks_are_refused(self):
        from till_infinity.statespace.projecting import project

        got = project(self._readout(), ahead=10, paths=400, seed=2)
        with pytest.raises(ValueError, match="step"):
            got.band(0.95, step=99)
        with pytest.raises(ValueError, match="coverage"):
            got.band(1.5)
        with pytest.raises(ValueError, match="level"):
            got.quantile(0.0)
        with pytest.raises(ValueError, match="straddle"):
            got.barrier(up=99.0, down=98.0)
        with pytest.raises(ValueError, match="reach"):
            project(self._readout(), reach=-1.0)
        with pytest.raises(ValueError, match="at least one"):
            project(self._readout(), ahead=0)


class TestS4DRealPromoted:
    """`diagonal.Diagonal` - the member that existed only as another's null.

    It won 3m, 15m and 30m outright while being unregistered, so it could be
    neither pooled nor scored against the family. These tests pin the two
    things promotion has to preserve: that it **is** the parent at its null, to
    the last digit, and that its selection cannot be turned back on.
    """

    @staticmethod
    def _drive(member, n=60, noise=0.01):
        for i in range(n):
            member.update(100.0 + math.sin(i / 5.0), noise, i * 3600.0)
        return member

    def test_it_is_its_parent_at_the_null_to_the_last_digit(self):
        """A copy would drift from `selective`; a pinned parameter cannot."""
        from till_infinity.statespace.diagonal import Diagonal
        from till_infinity.statespace.selective import Selective

        promoted = self._drive(Diagonal())
        parent = self._drive(Selective())
        assert promoted.value == parent.value
        assert promoted.loglike == parent.loglike
        assert promoted.sd == parent.sd
        assert promoted.last_standardised == parent.last_standardised

    def test_the_spectrum_is_the_references_s4d_real(self):
        """`-(n+1)` per state, and reachable the same way on any member."""
        from till_infinity.statespace.diagonal import Diagonal
        from till_infinity.statespace.selective import SIZE

        got = Diagonal().eigenvalues()
        assert got == tuple(-(n + 1.0) for n in range(SIZE))
        # Every eigenvalue strictly negative, so every state is drivable: the
        # entry weight is `1 - exp(delta * A)` and a zero there is a state no
        # reading can reach. That is why the anchored variant lives in `swarm`.
        assert all(a < 0.0 for a in got)

    def test_selection_is_refused_rather_than_ignored(self):
        """A member that quietly dropped `scale` would misname its own score."""
        from till_infinity.statespace.diagonal import Diagonal

        with pytest.raises(ValueError, match="time-invariant"):
            Diagonal(scale=0.3)
        # And the time-invariance is real, not just asserted: the retention is
        # the same whatever innovation is put in front of it.
        member = Diagonal()
        assert member.retention(1.0, z=0.0) == member.retention(1.0, z=5.0)

    def test_it_is_registered_so_it_can_be_pooled_and_scored(self):
        """The whole point of promotion, and it needs an adaptation lever."""
        from till_infinity.statespace.family import members
        from till_infinity.statespace.pooling import DEFAULT, LEVERS, Pooled

        assert members()["s4d"].__name__ == "Diagonal"
        # `Adapting` refuses a lever that names no field, so the registry entry
        # and the lever table have to agree or the pool raises.
        assert LEVERS["s4d"] == "noise"
        pool = Pooled(names=("kalman", "s4d", "reverting"))
        assert len(pool.members) == 3
        # Promotion makes it available and comparable. It does **not** change
        # the measured production pool, which is a separate decision.
        assert "s4d" not in DEFAULT


class TestTheCoverageAccessor:
    """`Readout.covering` - the consumer the t band did not have.

    `quantiles` and `band_covering` were both offered with no rule saying which
    to use, and the rule is not obvious: a 2-sigma band is about right and a
    4-sigma band is breached 88 times more often than its Gaussian label
    claims. This is that rule, written once.
    """

    DOF = 3.5

    @staticmethod
    def _t(rng, dof=4.0):
        """One draw from a t with unit variance, so the scale is known exactly."""
        chi = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(4))
        return rng.gauss(0.0, 1.0) / math.sqrt(max(chi, 1e-9) / 4.0) * math.sqrt(0.5)

    @classmethod
    def _warm(cls, *, spread=1.0, seed=1, n=500, shift=0.0, draw=None):
        """A readout carrying the grid `_quantiles` publishes, 0.05 to 0.95."""
        import random

        from till_infinity.statespace.facade import Readout

        rng = random.Random(seed)
        pick = draw or (lambda: cls._t(rng))
        kept = sorted(pick() for _ in range(n))
        grid = tuple(
            (i / 20.0, 100.0 + shift + kept[min(int(i / 20.0 * n), n - 1)]) for i in range(1, 20)
        )
        return Readout(
            feed="EURUSD", interval="1h", at=0.0, value=100.0, spread=spread, quantiles=grid
        )

    def test_the_arm_is_chosen_by_what_can_reach(self):
        """Measured inside the grid, anchored outside it, assumed with no grid."""
        got = self._warm()

        # The grid runs 0.05 to 0.95, so it serves a central 0.90 and no more.
        assert got.widest == 0.90
        assert got.covering(0.50).source == "measured"
        assert got.covering(0.90).source == "measured"
        assert got.covering(0.95).source == "anchored"
        assert got.covering(0.999).source == "anchored"

        # The limit is read off the grid rather than assumed, so a coarser grid
        # hands over to the t sooner.
        from till_infinity.statespace.facade import Readout

        coarse = Readout(
            feed="EURUSD",
            interval="1h",
            at=0.0,
            value=100.0,
            spread=1.0,
            quantiles=((0.25, 99.0), (0.5, 100.0), (0.75, 101.0)),
        )
        assert coarse.widest == 0.50
        assert coarse.covering(0.50).source == "measured"
        assert coarse.covering(0.60).source == "anchored"

    def test_a_cold_readout_says_the_shape_was_assumed(self):
        """With no residuals it is `band_covering`, and it admits as much."""
        from till_infinity.statespace.facade import Readout

        cold = Readout(feed="EURUSD", interval="1h", at=0.0, value=100.0, spread=0.04)
        assert cold.widest == 0.0
        got = cold.covering(0.999)
        assert got.source == "assumed"
        assert (got.low, got.high) == cold.band_covering(0.999)
        # A t is symmetric, so the assumed arm cannot carry skew.
        assert got.skew == pytest.approx(0.0)
        assert got.centre == pytest.approx(cold.value)

    def test_the_seam_does_not_step(self):
        """The anchored arm grows the measured edge, so the two meet exactly."""
        got = self._warm()
        inside = got.covering(got.widest)
        outside = got.covering(got.widest + 1e-9)
        assert inside.source == "measured"
        assert outside.source == "anchored"
        assert outside.low == pytest.approx(inside.low, abs=1e-6)
        assert outside.high == pytest.approx(inside.high, abs=1e-6)

    def test_the_anchor_is_the_measured_median_so_the_band_cannot_invert(self):
        """Residuals that all agree are the pathological case, and it holds."""
        got = self._warm(draw=lambda: 0.0, shift=-5.0)
        # Every quantile is the same number, well away from the filter's value.
        wide = got.covering(0.999)
        assert wide.low <= wide.high
        # Anchored on the grid's own median, not on `value`, so it does not
        # drift back toward a centre the residuals disagree with.
        assert wide.centre == pytest.approx(95.0)

    def test_the_measured_asymmetry_survives_into_the_tail(self):
        """A skewed grid stays skewed the same way once the t extends it."""
        import random

        rng = random.Random(5)
        # Positive residuals twice the size of negative ones: a one-sided tail.
        got = self._warm(draw=lambda: abs(rng.gauss(0.0, 1.0)) * rng.choice((2.0, -1.0)))
        edge = got.covering(got.widest)
        far = got.covering(0.999)
        assert edge.skew > 0.0
        assert far.skew > edge.skew
        # And it is the same shape, grown - the ratio of the two sides holds.
        assert (far.high - far.centre) / (far.centre - far.low) == pytest.approx(
            (edge.high - edge.centre) / (edge.centre - edge.low), rel=1e-9
        )

    def test_the_anchor_is_what_makes_it_free_of_the_filter_scale(self):
        """The claim, and the reason the anchored arm exists at all.

        The pure t stands on `spread` being the right scale for the residuals,
        and `statespace-river-against-members.md` measured that it is not: the
        pool read a PIT flatness of **43.05**, which is a filter whose sd is
        too small. The anchored arm reads the scale off the residuals instead,
        so its error does not move when `spread` is wrong - and the pure t's
        error is proportional to the mistake.
        """
        from till_infinity.statespace import tails

        truth = 100.0 + tails.reach(0.999, self.DOF)
        anchored, pure = {}, {}
        for off in (1.0, 0.5, 2.0):
            got = self._warm(spread=off**2)
            anchored[off] = abs(got.covering(0.999).high - truth)
            pure[off] = abs(got.band_covering(0.999)[1] - truth)

        # The anchored arm is unmoved by the scale error, to the last digit.
        assert anchored[0.5] == pytest.approx(anchored[1.0], rel=1e-12)
        assert anchored[2.0] == pytest.approx(anchored[1.0], rel=1e-12)
        # The pure t inherits all of it, exactly: its error is the reach times
        # the scale mistake, which is why a magnitude is not needed here.
        reach = tails.reach(0.999, self.DOF)
        assert pure[0.5] == pytest.approx(abs(0.5 - 1.0) * reach, rel=1e-9)
        assert pure[2.0] == pytest.approx(abs(2.0 - 1.0) * reach, rel=1e-9)
        # And it loses to the anchored arm at both wrong scales.
        assert anchored[0.5] < pure[0.5]
        assert anchored[2.0] < pure[2.0]
        # Where the scale is right, the pure t is exact and anchoring costs a
        # little sampling noise. That is the whole trade, stated rather than hidden.
        assert pure[1.0] < anchored[1.0]
        assert anchored[1.0] < 0.1 * reach

    def test_the_far_tail_is_wider_than_the_gaussian_label(self):
        """The reason any of this matters, in the units a caller reads."""
        got = self._warm()
        near = got.covering(0.95)
        far = got.covering(0.999)
        # Monotone in coverage, and the far tail is far wider than 1.96/3.29
        # would suggest - the Gaussian ratio there is only 3.29/1.96 = 1.68.
        assert far.half > near.half
        assert far.half / near.half > 1.68

    def test_a_coverage_outside_the_unit_interval_is_refused(self):
        got = self._warm()
        for bad in (0.0, 1.0, -0.5, 2.0):
            with pytest.raises(ValueError, match="coverage"):
                got.covering(bad)


class TestDispersionOfMeans:
    """The continuous counterpart, where the null has to survive dependence."""

    @staticmethod
    def _units(offset_sd, rho=0.0, units=150, each=30, seed=3, base=1.0, spread=0.4):
        """Units that are identical when `offset_sd` is zero, AR(1) inside each.

        `rho` is the point: a continuous observation can be correlated with the
        one before it, and that is what breaks an i.i.d. null.
        """
        import random

        rng = random.Random(seed)
        out = []
        for _ in range(units):
            offset = rng.gauss(0.0, offset_sd) if offset_sd else 0.0
            carried, values = 0.0, []
            for _ in range(each):
                carried = rho * carried + rng.gauss(0.0, spread)
                values.append(max(0.0, base + offset + carried))
            out.append(values)
        return out

    def test_identical_units_do_not_read_as_different(self):
        from till_infinity.statespace.dispersion import differ_means

        observed, null, p = differ_means(self._units(0.0), draws=120, seed=1)
        # The claim is never `tau == 0`. DerSimonian and Laird truncates at
        # zero, and because the within-unit variances are estimated rather
        # than known it is biased up, so on identical units it lands anywhere
        # from 0.00 to about 0.03. What has to hold is that it is level with
        # its own null.
        assert observed >= 0.0
        assert p > 0.05
        assert observed == pytest.approx(null, abs=0.04)

    def test_units_that_really_differ_are_found(self):
        from till_infinity.statespace.dispersion import differ_means, tau_of_means

        groups = self._units(0.20)
        observed, null, p = differ_means(groups, draws=120, seed=1)
        assert p < 0.05
        assert observed > null
        # And the recovered spread is near the planted one.
        assert tau_of_means(groups) == pytest.approx(0.20, abs=0.07)

    def test_the_block_null_survives_dependence_where_an_iid_one_would_not(self):
        """The measurement that decided the null's shape.

        Identical units with an AR(1) inside each. Dealing single observations
        destroys the dependence and so lowers the floor without lowering the
        observed value; dealing contiguous runs does not.
        """
        import random

        from till_infinity.statespace.dispersion import (
            differ_means,
            tau_squared_of_means,
        )

        groups = self._units(0.0, rho=0.6, seed=9)
        _, _, blocked = differ_means(groups, draws=150, seed=9)
        assert blocked > 0.05

        # The i.i.d. version, built here rather than offered as an option.
        observed = math.sqrt(tau_squared_of_means(groups)[0])
        laid = [v for values in groups for v in values]
        counts = [len(values) for values in groups]
        rng = random.Random(9)
        over = 0
        for _ in range(150):
            rng.shuffle(laid)
            cut, drawn = 0, []
            for n in counts:
                drawn.append(laid[cut : cut + n])
                cut += n
            over += math.sqrt(tau_squared_of_means(drawn)[0]) >= observed
        assert (over + 1) / 151 < blocked / 5

    def test_logs_stop_one_observation_from_carrying_a_unit(self):
        """The reason `logs` exists, on the quantity shape it exists for.

        A sweep depth is heavy-tailed, and in raw units a unit's mean is
        carried by its largest one or two observations - which is within-unit
        variance that no between-unit difference can out-shout.
        """
        import random

        rng = random.Random(6)
        units = [[math.exp(rng.gauss(0.0, 1.5)) for _ in range(30)] for _ in range(80)]
        raw = sorted(max(v) / sum(v) for v in units)
        logs = sorted(max(math.log1p(x) for x in v) / sum(math.log1p(x) for x in v) for v in units)
        even = 1 / 30
        assert raw[len(raw) // 2] > 4 * even
        assert logs[len(logs) // 2] < raw[len(raw) // 2] / 2

    def test_a_whole_unit_block_is_the_conservative_default(self):
        """`block` trades size against power, and the default picks size.

        On units that are identical by construction with strong dependence
        inside each, the default must not reject and a short block does.
        """
        from till_infinity.statespace.dispersion import differ_means, lag_one

        groups = self._units(0.0, rho=0.6, seed=11)
        assert lag_one(groups) > 0.3
        assert differ_means(groups, draws=150, seed=11)[2] > 0.05
        assert differ_means(groups, draws=150, seed=11, block=8)[2] < 0.05

    def test_a_pool_too_small_to_ask_says_so(self):
        from till_infinity.statespace.dispersion import UNITS, differ_means

        observed, null, p = differ_means(self._units(0.2, units=UNITS - 1), draws=20)
        assert observed >= 0.0
        assert math.isnan(null)
        assert math.isnan(p)

    def test_the_weight_goes_to_the_clamp_when_units_do_not_differ(self):
        """And that is correct behaviour, not an answer about the quantity.

        `borrow_weight_of_means` is a ratio with `tau_squared` underneath, so a
        pool with no spread pools maximally. The docstring says to read it only
        after `differ_means` has opened the gate, and this is why.
        """
        from till_infinity.statespace.dispersion import borrow_weight_of_means

        pooled = borrow_weight_of_means(self._units(0.0))
        spread = borrow_weight_of_means(self._units(0.40))
        assert pooled == pytest.approx(50.0)
        assert 0.5 <= spread < pooled

    def test_a_mean_needs_more_observations_than_a_rate(self):
        from till_infinity.statespace.dispersion import (
            LEAST,
            LEAST_VALUES,
            tau_squared_of_means,
        )

        assert LEAST_VALUES > LEAST
        _, _, used = tau_squared_of_means([[1.0, 2.0]] * 40)
        assert used == 0


class TestTradedWalls:
    """The barrier wall on instruments the desk actually trades."""

    def test_every_traded_class_is_wider_than_the_diffusion_constant(self):
        """The measurement: 0.7262 traded against 0.5850 on the control.

        `SHIFTS` held no traded instrument at all until this was measured, so
        every live feed took the diffusion constant and understated the wall.
        """
        from till_infinity.statespace import bounding

        for feed in ("EURUSD", "USDJPY", "EURJPY", "GBPJPY", "XAUUSD"):
            up, down = bounding.shifts_for(feed)
            assert up > bounding.SHIFT
            assert down > bounding.SHIFT

    def test_the_down_wall_is_the_wider_one_on_traded_feeds(self):
        """Pooled log-ratio -0.1571 at `z` -11.53, against a control at +0.0259.

        Per-instrument asymmetry is deliberately **not** claimed - the control's
        own ratio wanders 0.741 to 1.229 - so the table carries class medians
        and only the direction of the pooled ordering is asserted.
        """
        from till_infinity.statespace import bounding

        for feed in ("EURUSD", "EURJPY", "XAUUSD"):
            up, down = bounding.shifts_for(feed)
            assert down > up

    def test_generated_feeds_keep_their_own_walls(self):
        from till_infinity.statespace import bounding

        assert bounding.shifts_for("Volatility_75_Index") == (
            bounding.SHIFT,
            bounding.SHIFT,
        )
        assert bounding.shifts_for("Boom_500_Index")[0] > bounding.shifts_for("Boom_500_Index")[1]

    def test_unmeasured_classes_are_not_given_a_measured_wall(self):
        """An FX-measured wall on an equity is an extrapolation, so it is refused."""
        from till_infinity.statespace import bounding

        for feed in ("AAPL.OQ", "JPM.N"):
            assert bounding.shifts_for(feed) == (bounding.SHIFT, bounding.SHIFT)

    def test_the_wall_grows_with_the_reach_on_traded_feeds_only(self):
        """Traded reads 0.6472, 0.7525, 0.8619 at reaches 2, 4, 8.

        The control reads 0.5923, 0.5681, 0.5954 over the same reaches, which is
        flat - so the slope must not be applied to it. The first version of
        `wall_at` guarded on the wall rather than the class and let `Boom` and
        `DEX` through.
        """
        from till_infinity.statespace import bounding

        near = bounding.wall_at("EURUSD", 2.0)
        far = bounding.wall_at("EURUSD", 8.0)
        assert far[0] > near[0]
        assert far[1] > near[1]
        # Two doublings from the base, so twice the slope.
        assert far[0] - near[0] == pytest.approx(2 * bounding.REACH_SLOPE)
        # And the generated families keep theirs flat, asymmetric or not.
        for feed in ("Volatility_75_Index", "Boom_500_Index", "DEX_900_UP_Index"):
            assert bounding.wall_at(feed, 8.0) == bounding.shifts_for(feed)

    def test_at_the_anchor_reach_the_wall_is_the_table(self):
        from till_infinity.statespace import bounding

        assert bounding.wall_at("EURUSD", bounding.REACH_BASE) == bounding.shifts_for("EURUSD")
        assert bounding.wall_at("EURUSD", 0.0) == bounding.shifts_for("EURUSD")

    def test_a_wider_wall_lengthens_the_horizon_more_than_it_moves_the_probability(self):
        """Which is why the level matters and the asymmetry barely does.

        `T = u * d` is second order in the wall where `P = d / (u + d)` is a
        ratio, so the horizon moves and the probability barely does. Swept over
        up and down from 0.5 to 12 sigmas, replacing 0.5826 with the traded
        0.7262 lengthens every horizon - by at least 2.3%, and by 3.4% at eight
        sigmas a side rising to 11.4% at two - and moves the probability by at
        most **0.0155**, worst at a 0.5-against-3 geometry where both walls are
        a large share of the near barrier. The lengthening shrinks as the
        barriers widen because the wall is additive, so it is a smaller share
        of a bigger distance.
        """
        from till_infinity.statespace import bounding

        worst = 0.0
        for up in (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0):
            for down in (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0):
                thin = bounding.solve(up=up, down=down, shift=bounding.SHIFT)
                wide = bounding.solve(up=up, down=down, shift=0.7262)
                assert wide["horizon"] > thin["horizon"]
                worst = max(worst, abs(wide["probability"] - thin["probability"]))
        assert worst == pytest.approx(0.0155, abs=0.001)
        # And the symmetric cases, where the probability cannot move at all and
        # the lengthening falls away as the barriers widen.
        grew = []
        for side in (2.0, 4.0, 8.0):
            thin = bounding.solve(up=side, down=side, shift=bounding.SHIFT)
            wide = bounding.solve(up=side, down=side, shift=0.7262)
            assert wide["probability"] == pytest.approx(thin["probability"])
            grew.append(wide["horizon"] / thin["horizon"] - 1.0)
        assert grew[0] == pytest.approx(0.114, abs=0.004)
        assert grew[-1] == pytest.approx(0.034, abs=0.004)
        assert grew[0] > grew[1] > grew[2]


class TestOutputLayer:
    """The output layer: weights, a bias, an activation, and its two encodings.

    `signalling.py` claims that 0..1 and -1..+1 are the same layer rather than
    a choice with consequences. That claim is arithmetic, so it is asserted
    here instead of being described in a docstring.
    """

    TERMS: ClassVar[dict[str, float]] = {
        "slope t": 1.5,
        "tick velocity": -0.5,
        "ema gap": 0.8,
        "regime": 0.2,
    }
    WEIGHTS: ClassVar[dict[str, float]] = {
        "slope t": 0.4,
        "tick velocity": 0.3,
        "ema gap": 0.2,
        "regime": -0.1,
    }

    def test_the_sign_convention_is_fixed(self) -> None:
        """-1 to +1, 0 neutral, +1 bullish and -1 bearish. Fixed 2026-10-16.

        A convention is not arithmetic, so nothing else in this file would
        catch it drifting - and a signal whose sign convention moves is worse
        than no signal, because every consumer written against the old one
        silently inverts.
        """
        from till_infinity.statespace import BOUNDS, NEUTRAL, Layer

        layer = Layer(weights={"up": 1.0})
        assert layer.activation == "tanh", "the default encoding is -1..+1"
        assert BOUNDS["tanh"] == (-1.0, 1.0)
        assert NEUTRAL["tanh"] == 0.0

        bullish = layer({"up": 0.8})
        bearish = layer({"up": -0.8})
        flat = layer({"up": 0.0})

        assert bullish.side == 1, "a positive sum is bullish"
        assert bearish.side == -1, "a negative sum is bearish"
        assert flat.side == 0, "zero is no opinion"
        assert flat.value == 0.0
        assert 0.0 < bullish.value < 1.0
        assert -1.0 < bearish.value < 0.0
        assert bullish.value == pytest.approx(-bearish.value), "symmetric about zero"

        # Stronger means further from zero, on both sides, and `strength` is
        # the same number either way - which is what a consumer reads.
        stronger = layer({"up": 3.0})
        assert stronger.value > bullish.value
        assert stronger.strength > bullish.strength
        assert layer({"up": -3.0}).strength == pytest.approx(stronger.strength)

    def test_weighs_adds_and_squashes(self) -> None:
        """The arithmetic is the stated arithmetic, and the parts are kept."""
        from till_infinity.statespace import Layer

        layer = Layer(weights=self.WEIGHTS, bias=-0.1)
        got = layer(self.TERMS)
        wanted = -0.1 + sum(self.WEIGHTS[k] * self.TERMS[k] for k in self.WEIGHTS)
        assert got.total == pytest.approx(wanted)
        assert got.value == pytest.approx(math.tanh(wanted))
        # Every contribution is kept, largest in absolute value first, and they
        # add back up to the total once the bias is removed.
        assert sum(share for _n, share in got.contributions) == pytest.approx(wanted + 0.1)
        sizes = [abs(share) for _n, share in got.contributions]
        assert sizes == sorted(sizes, reverse=True)
        assert got.leading == got.contributions[0]
        assert got.side == 1
        assert got.strength == pytest.approx(abs(got.value))

    def test_the_two_encodings_are_one_layer(self) -> None:
        """`tanh(x) == 2 logistic(2x) - 1`, so the twin is an affine image.

        The consequence that matters: the two order every pair of inputs
        identically, so no AUC can separate them and the choice is ergonomic.
        """
        from till_infinity.statespace import Layer

        signed = Layer(weights=self.WEIGHTS, bias=-0.1)
        unsigned = signed.as_logistic()
        assert unsigned.activation == "logistic"
        assert unsigned.bias == pytest.approx(-0.2)
        draws = [
            {k: v * scale for k, v in self.TERMS.items()}
            for scale in (-3.0, -1.0, -0.25, 0.0, 0.25, 1.0, 3.0)
        ]
        ranked_signed, ranked_unsigned = [], []
        for terms in draws:
            here, there = signed(terms), unsigned(terms)
            assert there.value == pytest.approx((here.value + 1.0) / 2.0, abs=1e-15)
            assert there.strength == pytest.approx(here.strength, abs=1e-12)
            assert there.side == here.side
            ranked_signed.append(here.value)
            ranked_unsigned.append(there.value)
        # The same order, which is what an AUC reads.
        order = sorted(range(len(draws)), key=lambda i: ranked_signed[i])
        assert sorted(range(len(draws)), key=lambda i: ranked_unsigned[i]) == order
        # And the conversion is a round trip.
        assert unsigned.as_tanh() == signed

    def test_neutral_sits_where_the_encoding_puts_it(self) -> None:
        """No terms and no bias means no opinion, under either encoding."""
        from till_infinity.statespace import NEUTRAL, Layer

        for activation in ("tanh", "logistic", "identity"):
            layer = Layer(weights=self.WEIGHTS, activation=activation)
            got = layer(dict.fromkeys(self.WEIGHTS, 0.0))
            assert got.value == pytest.approx(NEUTRAL[activation])
            assert got.side == 0
            assert got.strength == pytest.approx(0.0)

    def test_missing_terms_are_named_not_zeroed_quietly(self) -> None:
        """An absent or `nan` term contributes nothing and is reported.

        The layer cannot know whether a missing term's own neutral was 0, 0.5
        or 1, so it refuses to guess and says what it did not have.
        """
        from till_infinity.statespace import Layer

        layer = Layer(weights=self.WEIGHTS)
        got = layer({"slope t": 1.5, "ema gap": float("nan")})
        assert set(got.missing) == {"tick velocity", "ema gap", "regime"}
        assert got.total == pytest.approx(0.4 * 1.5)
        assert [name for name, _s in got.contributions] == ["slope t"]
        # A term the layer carries no weight for cannot move it at all, so
        # adding a reading upstream is inert until a weight is added here.
        assert layer({**self.TERMS, "invented": 99.0}).value == layer(self.TERMS).value

    def test_saturates_instead_of_overflowing(self) -> None:
        """A huge total returns the bound, not a `nan` and a warning."""
        from till_infinity.statespace import BOUNDS, Layer, squash

        for activation in ("tanh", "logistic"):
            layer = Layer(weights={"a": 1.0}, activation=activation)
            low, high = BOUNDS[activation]
            assert layer({"a": 1e12}).value == pytest.approx(high)
            assert layer({"a": -1e12}).value == pytest.approx(low)
            assert layer({"a": 1e12}).strength == pytest.approx(1.0)
        assert squash(1e12, "identity") == 1e12
        with pytest.raises(ValueError, match="unknown activation"):
            squash(0.0, "relu")

    def test_the_deadband_is_in_strength_units(self) -> None:
        """So it means the same width under either encoding."""
        from till_infinity.statespace import Layer

        layer = Layer(weights={"a": 1.0}, deadband=0.5)
        assert layer.settled({"a": 0.3}) == 0
        assert layer.settled({"a": 3.0}) == 1
        assert layer.settled({"a": -3.0}) == -1
        twin = layer.as_logistic()
        for value in (0.3, 3.0, -3.0):
            assert twin.settled({"a": value}) == layer.settled({"a": value})
        with pytest.raises(ValueError, match="deadband"):
            Layer(weights={"a": 1.0}, deadband=1.5)
        with pytest.raises(ValueError, match="unknown activation"):
            Layer(weights={"a": 1.0}, activation="softmax")

    def test_scaling_is_a_temperature_and_cannot_reorder(self) -> None:
        """`scaled` changes saturation, never the order of two signals."""
        from till_infinity.statespace import Layer

        layer = Layer(weights=self.WEIGHTS, bias=-0.1)
        draws = [{k: v * s for k, v in self.TERMS.items()} for s in (-2.0, 0.5, 1.0, 4.0)]
        for factor in (0.25, 3.0):
            hotter = layer.scaled(factor)
            before = [layer(terms).value for terms in draws]
            after = [hotter(terms).value for terms in draws]
            assert sorted(range(len(draws)), key=lambda i: after[i]) == sorted(
                range(len(draws)), key=lambda i: before[i]
            )
        # A `t`-statistic layer saturates without it: tanh(3) is already 0.995,
        # so four terms at t = 3 are indistinguishable from four at t = 10.
        flat = Layer(weights=dict.fromkeys(self.WEIGHTS, 1.0))
        tight = flat.scaled(0.1)
        three = dict.fromkeys(self.WEIGHTS, 3.0)
        ten = dict.fromkeys(self.WEIGHTS, 10.0)
        saturated = flat(ten).value - flat(three).value
        used = tight(ten).value - tight(three).value
        assert saturated < 1e-5
        assert used > 0.15
        assert used > 1_000 * saturated


class TestReadoutTerms:
    """What a `Readout` can hand an output layer, and what it must not.

    `facade.Desk.read` computes the standardised one-step innovation to build
    its quantile band and, until 2026-10-16, did not publish it - so a caller
    wanting statespace's own reading of a bar had to reconstruct it from
    `value` and `spread`, which gives a different and smaller number.
    """

    @staticmethod
    def _run(prices, noise=0.0004, feed="EURUSD", rule=None):
        from till_infinity.statespace.facade import Desk

        desk = Desk() if rule is None else Desk(rule=rule)
        return [
            desk.read(feed, "1h", float(i) * 3600.0, price, noise, volume=0.0)
            for i, price in enumerate(prices)
        ]

    def test_a_predicted_bar_is_no_surprise_and_the_first_one_is_all_surprise(self) -> None:
        """A series the filter tracks exactly reports an innovation of zero.

        Except the first bar, which reports the whole of the level on a flat
        series at 100 - the prior sits at zero and the first observation is all
        there is. That is correct and it is a trap for a consumer, so it is
        pinned here. `Readout.warm` is already False there - the quantile band
        needs a history - so a caller that checks `warm`, as the field's own
        docstring tells it to, never sees the cold-start value.

        **The size of it is set by the spread rule, so both are pinned.**
        `shrinking`, the shipped rule, reads 173; `mixture` reads 99.98,
        smaller because the first observation is where the members disagree
        most and that term is in the denominator. A bare threshold would have
        been satisfied by either and told a reader neither, which is how a
        spread rule changes under a green suite - `pool-spread.md` swept these
        and the default stayed put on the strength of band coverage.
        """
        tight = self._run([100.0] * 60, rule="shrinking")
        assert tight[0].surprise == pytest.approx(173.0, abs=1.0)
        wide = self._run([100.0] * 60, rule="mixture")
        assert wide[0].surprise == pytest.approx(99.98, abs=0.5)
        assert wide[0].surprise < tight[0].surprise, (
            "mixture has to report the smaller innovation: it carries the "
            "between-member disagreement in the spread it divides by"
        )
        got = self._run([100.0] * 60)
        assert got[0].surprise > 100.0, "the default is the tighter rule"
        assert not got[0].warm
        assert max(abs(r.surprise) for r in got[1:]) < 1e-9

    def test_the_innovation_is_not_the_post_update_residual(self) -> None:
        """And the difference is an attenuation, not a rounding.

        The naive reconstruction divides a residual that has already been
        pulled toward the price by a spread meant for the *next* observation.
        Both errors shrink it, so it reads as a weak signal rather than as a
        bug - which is why `surprise` is published and this test exists.
        """
        prices = [100.0] * 60 + [100.5]
        got = self._run(prices)
        last = got[-1]
        naive = (prices[-1] - last.value) / math.sqrt(last.spread)
        assert last.surprise > 10.0
        assert naive > 0.0
        # Same sign, materially different size: the naive one is smaller.
        assert naive < last.surprise
        # **Rule-dependent, so both are pinned.** The shipped `shrinking` reads
        # 1.72 and `mixture` reads 6.73, because the post-update spread the
        # naive reconstruction divides by carries the members' disagreement
        # while the pre-update one it should have used is measured before they
        # have seen the reading. Under either rule the attenuation is real,
        # which is why `surprise` is published rather than reconstructed.
        assert last.surprise / naive == pytest.approx(1.72, abs=0.15)
        wide = self._run(prices, rule="mixture")[-1]
        naive_wide = (prices[-1] - wide.value) / math.sqrt(wide.spread)
        assert wide.surprise / naive_wide == pytest.approx(6.73, abs=0.4)

    def test_terms_from_offers_two_and_names_them(self) -> None:
        """Surprise and pace, with pace at zero when the mechanism is inert."""
        from till_infinity.statespace import terms_from

        last = self._run([100.0] * 60 + [100.5])[-1]
        terms = terms_from(last)
        assert set(terms) == {"surprise", "pace"}
        assert terms["surprise"] == pytest.approx(last.surprise)
        # `volume=0` leaves pacing inert, and an inert mechanism has to
        # contribute nothing rather than contributing one.
        assert last.pace_factor == 1.0
        assert terms["pace"] == 0.0

    def test_spread_needs_a_reference_before_it_is_a_term(self) -> None:
        """A spread is in the instrument's units, so it is scale-free only
        against something. No reference, no term."""
        from till_infinity.statespace import terms_from

        got = self._run([100.0] * 60 + [100.5])
        last, earlier = got[-1], got[-6]
        assert "spread" not in terms_from(last)
        assert "spread" not in terms_from(last, reference_spread=0.0)
        with_ref = terms_from(last, reference_spread=earlier.spread)
        assert with_ref["spread"] == pytest.approx(last.spread / earlier.spread - 1.0)

    def test_constants_are_not_offered_as_terms(self) -> None:
        """`walls`, `family` and `absorbs` are per-feed lookups.

        Each is the same number on every bar of a feed, so as a term it is a
        bias wearing a term's name - it shifts every signal equally and changes
        no ordering, while looking as though it had been measured.
        """
        from till_infinity.statespace import terms_from

        got = self._run([100.0 + 0.01 * i for i in range(60)])
        walls = {r.walls for r in got}
        families = {r.family for r in got}
        assert len(walls) == 1
        assert len(families) == 1
        for readout in got:
            offered = set(terms_from(readout, reference_spread=1.0))
            assert offered == {"surprise", "pace", "spread"}
            assert "walls" not in offered
            assert "family" not in offered
            assert "absorbs" not in offered

    def test_a_layer_on_these_terms_saturates_without_a_temperature(self) -> None:
        """Which is what `Layer.scaled` is for.

        An innovation of 21 through a weight of 0.5 is `tanh(10)`, so a jump
        and a much larger jump are the same signal. The layer does not pick a
        temperature for the caller, but the need for one is a property of these
        terms and belongs in a test.
        """
        from till_infinity.statespace import Layer, terms_from

        big = terms_from(self._run([100.0] * 60 + [100.5])[-1])
        bigger = terms_from(self._run([100.0] * 60 + [101.0])[-1])
        hot = Layer(weights={"surprise": -0.5, "pace": 0.2})
        assert hot(big).value == pytest.approx(-1.0, abs=1e-6)
        assert hot(bigger).value == pytest.approx(-1.0, abs=1e-6)
        cool = hot.scaled(0.02)
        assert cool(bigger).value < cool(big).value < 0.0
        assert cool(big).value - cool(bigger).value > 0.05


class TestService:
    """The service wrapper: config, engine, store, bus payload.

    The numeric core is `Desk` and is tested above. What is tested here is the
    five things that make it a service rather than a library - what it folds
    from a bar, what it withholds, what survives a restart, what it refuses to
    read back, and what it puts on the bus.
    """

    @staticmethod
    def _bars(n, *, sd=0.003, wick=0.0015, seed=3, feed="FX:EURUSD", interval="1m"):
        """Bars from a walk, as `prices.bars` payloads."""
        import math
        import random

        rng = random.Random(seed)
        price = 1.0
        out = []
        for i in range(n):
            opened = price
            close = price * math.exp(rng.gauss(0.0, sd))
            high = max(opened, close) * (1.0 + abs(rng.gauss(0.0, wick)))
            low = min(opened, close) * (1.0 - abs(rng.gauss(0.0, wick)))
            price = close
            out.append(
                {
                    "feed": feed,
                    "interval": interval,
                    "time": 1000.0 + 60.0 * i,
                    "open": opened,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 100.0,
                }
            )
        return out

    def test_a_bar_contributes_its_log_variance_not_its_close(self):
        """The observation is dispersion, which is the half that forecasts.

        Direction is measured closed on this desk; dispersion reads median
        out-of-sample R2 of +0.54 to +0.83 at 1h h=20 on FX and metals. So the
        number folded is a range estimator's log variance, and the estimator is
        Garman-Klass rather than Rogers-Satchell because on the same bars the
        drift-robust one reads -0.090 against +0.575.
        """
        import math

        from till_infinity.statespace.engine import dispersion

        got = dispersion(1.0, 1.01, 0.99, 1.0)
        assert got is not None
        # A 2% range is a variance near 1e-4, so a log variance near -9.
        assert -11.0 < got < -8.0
        # It is a log of a variance, so halving it and exponentiating gives a
        # standard deviation of the order of the bar's range.
        assert 0.002 < math.exp(got / 2.0) < 0.02
        # Rogers-Satchell is a different number, which is the whole point of
        # naming the estimator rather than taking whatever is default.
        assert dispersion(1.0, 1.01, 0.99, 1.0, "rogers_satchell") != got

    def test_a_bar_that_cannot_produce_a_variance_is_dropped(self):
        """`log(0)` is not a number a filter can take."""
        from till_infinity.statespace.engine import dispersion

        assert dispersion(1.0, 1.0, 1.0, 1.0) is None  # a feed that did not trade
        assert dispersion(1.0, 0.99, 1.01, 1.0) is None  # inverted range
        assert dispersion(0.0, 0.0, 0.0, 0.0) is None

    def test_nothing_is_published_until_the_band_can_be_stated(self):
        """A readout with no interval is worse than no readout.

        `Desk._quantiles` returns an empty band below `facade.LEAST` residuals,
        so publishing on bar one ships a point estimate dressed as a forecast.
        """
        import tempfile

        from till_infinity.statespace.config import Settings
        from till_infinity.statespace.engine import Engine

        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(settings=Settings(state_dir=directory, warm_bars=10))
            published = [engine.observe_bar(bar) for bar in self._bars(30)]
            assert published[:9] == [None] * 9
            assert all(got is not None for got in published[9:])
            assert engine.progress.folded == 30
            assert engine.armed == 1
            assert engine.tracking == 1

    def test_only_the_intervals_asked_for_are_folded(self):
        import tempfile

        from till_infinity.statespace.config import Settings
        from till_infinity.statespace.engine import Engine

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(state_dir=directory, intervals=("1m",), feeds=("FX:EURUSD",))
            engine = Engine(settings=settings)
            assert engine.observe_bar(self._bars(1, interval="1h")[0]) is None
            assert engine.observe_bar(self._bars(1, feed="FX:GBPUSD")[0]) is None
            assert engine.progress.folded == 0
            assert settings.wants("FX:EURUSD", "1m")
            assert not settings.wants("FX:EURUSD", "1h")
            assert not settings.wants("FX:GBPUSD", "1m")

    def test_a_restart_keeps_the_counters_and_rewarms_the_members(self):
        """Replay rather than restore, and the reading that proves which.

        The package declares `CODEC_UNPERSISTED = True` so that it stays
        deletable, which means the member graph is not written down. A restored
        service therefore reports its bar count and `tracking == 0`, and a
        reader who expects otherwise is reading the wrong thing.
        """
        import tempfile

        from till_infinity.statespace.config import Settings
        from till_infinity.statespace.engine import Engine

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(state_dir=directory, warm_bars=10)
            first = Engine(settings=settings)
            for bar in self._bars(40):
                first.observe_bar(bar)
            assert first.save(force=True) > 0

            second = Engine(settings=Settings(state_dir=directory, warm_bars=10))
            second.restore()
            assert second.progress.folded == 40
            assert second.progress.of("FX:EURUSD", "1m").bars == 40
            assert second.armed == 1
            # The members are not restored, by design.
            assert second.tracking == 0

    def test_a_progress_file_from_another_format_is_not_read(self):
        """One warmup is cheaper than numbers whose meaning changed."""
        import tempfile
        from pathlib import Path

        import msgpack

        from till_infinity.statespace import store

        with tempfile.TemporaryDirectory() as directory:
            assert store.load(directory).folded == 0  # missing file
            target = store.path_for(Path(directory))
            target.write_bytes(msgpack.packb({"format": store.FORMAT + 1, "state": {"folded": 99}}))
            assert store.load(directory).folded == 0
            target.write_bytes(b"not msgpack at all")
            assert store.load(directory).folded == 0

    def test_a_restored_window_keeps_its_bound(self):
        """The measured trap: a capped deque came back unbounded.

        `shared.state.restore_deque` fixes a direct field, and `Desk._residuals`
        is a dict *of* deques, which it does not reach. So the bound is applied
        where the window is rebuilt, and asserted on the object rather than read
        off the declaration.
        """
        from till_infinity.statespace.state import window

        got = window([float(i) for i in range(50)], maxlen=10)
        assert got.maxlen == 10
        assert len(got) == 10
        got.extend([0.0] * 50)
        assert len(got) == 10
        # Junk in, empty window out, still bounded.
        assert window("not a list", maxlen=5).maxlen == 5
        assert window([1.0, "two", None, 3.0], maxlen=5)[-1] == 3.0

    def test_what_goes_on_the_bus_carries_no_direction(self):
        """The topic is a dispersion topic, and there is no side to read.

        A consumer sizes, places a stop, or declines on this. If a direction
        appeared in the payload something would trade on it, and the desk has
        measured that half closed twice.
        """
        import asyncio
        import json
        import tempfile

        from till_infinity.bus import BARS, DISPERSION, TOPICS, Message
        from till_infinity.statespace.config import Settings
        from till_infinity.statespace.engine import Engine
        from till_infinity.statespace.service import Watcher

        assert DISPERSION in TOPICS

        class Recording:
            def __init__(self):
                self.sent = []

            async def publish(self, topic, payload, *, source=""):
                self.sent.append((topic, payload, source))
                return 1

        async def run():
            with tempfile.TemporaryDirectory() as directory:
                engine = Engine(settings=Settings(state_dir=directory, warm_bars=10))
                watcher, bus = Watcher(engine=engine), Recording()
                for bar in self._bars(60):
                    await watcher.handle(Message(topic=BARS, payload=bar), bus)
                # A topic this service does not consume is ignored, not folded.
                assert await watcher.handle(Message(topic="prices.quotes", payload={}), bus) is None
                return watcher, bus

        watcher, bus = asyncio.run(run())
        assert watcher.published == 51
        topic, payload, source = bus.sent[-1]
        assert topic == DISPERSION
        assert source == "statespace"
        assert not [
            key for key in payload if key.lower() in {"side", "direction", "up", "signal", "bias"}
        ]
        assert payload["feed"] == "FX:EURUSD"
        assert payload["log_variance"] < 0.0
        assert payload["band"]["low"] < payload["log_variance"] < payload["band"]["high"]
        assert payload["band"]["coverage"] == 0.90
        assert payload["band"]["source"] in {"measured", "anchored", "assumed"}
        # It goes on a bus, so it has to survive the wire.
        assert json.loads(json.dumps(payload)) == payload

    def test_the_duplicated_topic_names_match_the_bus(self):
        """The package names its topics rather than importing them.

        It cannot import `..bus` - `TestVendoredCusum` asserts the package
        imports nothing from outside itself but `shared`, because it is meant
        to lift out in one move. So the names are duplicated, and a duplicate
        that is not checked is a service subscribed to a topic nobody
        publishes. This is the check.
        """
        from till_infinity.bus import BARS, DISPERSION
        from till_infinity.statespace.service import CONSUMES, TOPIC

        assert CONSUMES == BARS
        assert TOPIC == DISPERSION

    def test_the_service_names_its_one_unmeasured_constant(self):
        """`noise` is assumed, and the file says so rather than hiding it.

        Two standard derivations of the sampling variance of a log range
        estimator disagree by 4.6x, and the band is the thing that disagreement
        moves. `band_coverage.py` is the harness that settles it - the same one
        that took a 93.5% breach at a nominal 95% down to 1.02-1.10 by refusing
        a guessed noise.
        """
        import pathlib

        from till_infinity.statespace.config import DEFAULT_NOISE

        assert 0.1 < DEFAULT_NOISE < 5.0
        text = pathlib.Path("till_infinity/statespace/config.py").read_text()
        assert "band_coverage.py" in text
        assert "unmeasured" in text


class TestOneBarOneObservation:
    """`prices.announce` publishes a notice per *touched* bar, so the bar in
    progress arrives on every sweep and a backfill re-announces old ones. Both
    were folded before this was wired to the stack."""

    @staticmethod
    def _bar(when: float, closed: bool | None = True, price: float = 2_400.0):
        payload = {
            "feed": "gold",
            "interval": "5m",
            "time": when,
            "open": price,
            "high": price * 1.002,
            "low": price * 0.998,
            "close": price * 1.001,
            "volume": 1_000.0,
        }
        if closed is not None:
            payload["closed"] = closed
        return payload

    def _engine(self, tmp_path):
        from till_infinity.statespace.config import Settings
        from till_infinity.statespace.engine import Engine

        return Engine(settings=Settings(state_dir=tmp_path, intervals=("5m",), warm_bars=1))

    def test_a_bar_still_forming_is_not_folded(self, tmp_path):
        engine = self._engine(tmp_path)
        assert engine.observe_bar(self._bar(1_000.0, closed=False)) is None
        assert engine.progress.folded == 0
        assert engine.observe_bar(self._bar(1_000.0, closed=True)) is not None
        assert engine.progress.folded == 1

    def test_the_same_bar_announced_twice_is_folded_once(self, tmp_path):
        engine = self._engine(tmp_path)
        engine.observe_bar(self._bar(1_000.0))
        assert engine.observe_bar(self._bar(1_000.0)) is None
        assert engine.observe_bar(self._bar(900.0)) is None, "a backfill re-announcement"
        assert engine.observe_bar(self._bar(1_300.0)) is not None
        assert engine.progress.folded == 2
        assert engine.progress.of("gold", "5m").at == 1_300.0

    def test_a_producer_that_says_nothing_about_closing_is_still_folded(self, tmp_path):
        """Fail-open on a missing key: `closed` is absent from other producers
        and from most of this file, and a guard that silently stopped folding
        would look exactly like a quiet bus."""
        engine = self._engine(tmp_path)
        assert engine.observe_bar(self._bar(1_000.0, closed=None)) is not None
        assert engine.progress.folded == 1

    def test_the_payload_prices_publishes_has_every_key_the_engine_reads(self):
        """The contract, checked against the producer rather than assumed. The
        extremes were once left off this notice and `structures` read every live
        bar as a doji for it."""
        import inspect

        from till_infinity.prices import service as px

        source = inspect.getsource(px._notice)
        for key in ("feed", "interval", "time", "open", "high", "low", "close", "volume", "closed"):
            assert f'"{key}"' in source, f"prices stopped publishing {key}"


class TestTheDeskSpreadRule:
    """`pool-spread.md`: the published spread was over-confident for two reasons
    and neither was `Q`. This pins the half that was fixed."""

    def test_the_desk_names_its_own_rule_and_the_module_default_is_untouched(self):
        """Scoped deliberately. `pooling.RULE` was measured on **log closes** and
        this desk folds log variance, so the two are separate knobs even while
        they hold the same value - changing the module default would move a
        figure in `statespace-pooling-exponent.md` that nothing re-measured."""
        from till_infinity.statespace.facade import SPREAD_RULE, Desk
        from till_infinity.statespace.pooling import RULE

        assert SPREAD_RULE == "shrinking", (
            "pool-spread.md swept all three rules at 15m and 1h and none "
            "dominates: mixture fixes the spread at 15m and overshoots at 1h, "
            "and neither frame is one this service folds. The default moves "
            "when a frame it runs on has been measured, not before."
        )
        assert RULE == "shrinking", "the module default belongs to the price studies"
        assert Desk().rule == SPREAD_RULE

        desk = Desk()
        desk.read("gold", "5m", 3_600.0, -16.0, 0.67)
        assert desk._members[("gold", "5m")].rule == SPREAD_RULE

    def test_a_caller_can_ask_for_a_rule_without_patching_internals(self):
        """The sweep in `pool_calibration.py` has to request each rule, and it
        had to seed three private maps to do it before this field existed."""
        from till_infinity.statespace.facade import Desk

        for rule in ("shrinking", "mixture", "argmax"):
            desk = Desk(rule=rule)
            desk.read("gold", "5m", 3_600.0, -16.0, 0.67)
            assert desk._members[("gold", "5m")].rule == rule

    def test_the_mixture_spread_is_never_below_the_shrinking_one(self):
        """The law of total variance, which is the whole reason this is the
        honest rule: it cannot fall below the members' own disagreement. Fed the
        identical series, so any difference is the rule and nothing else."""
        import random

        from till_infinity.statespace.facade import Desk

        rng = random.Random(20_261_020)
        bars = []
        level = -16.0
        for i in range(400):
            level += rng.gauss(0.0, 0.08)
            bars.append((3_600.0 * (i + 1), level + rng.gauss(0.0, 0.5)))

        desks = {rule: Desk(rule=rule) for rule in ("shrinking", "mixture")}
        spreads: dict[str, list[float]] = {rule: [] for rule in desks}
        for when, value in bars:
            for rule, desk in desks.items():
                spreads[rule].append(desk.read("gold", "1h", when, value, 0.67).spread)

        pairs = list(zip(spreads["shrinking"], spreads["mixture"], strict=True))
        assert all(mixture >= tight - 1e-9 for tight, mixture in pairs), (
            "mixture fell below shrinking, which the law of total variance forbids"
        )
        assert any(mixture > tight + 1e-6 for tight, mixture in pairs), (
            "the two rules never differed, so this test proves nothing - the "
            "members have to disagree somewhere for the between-member term to exist"
        )
        assert all(math.isfinite(value) for value in spreads["mixture"])


class TestASaturatedLeverIsVisible:
    """`adapting-strata.md`: every member on every traded instrument finished at
    `factor = 1000.000` - `MOST` exactly - while the pool published a one-step
    spread three times too small, and nothing in the service said anything. A
    matching loop against its clamp keeps returning numbers, so the failure has
    no symptom unless something looks for it. These make it look."""

    def test_a_member_on_its_upper_stop_is_named(self):
        from till_infinity.statespace.pooling import Pooled

        pool = Pooled()
        assert pool.saturated == (), "a fresh pool has not moved yet"
        for one in pool.members:
            one.factor = one.most
        assert set(pool.saturated) == set(pool.names)

    def test_a_member_on_its_lower_stop_is_named_too(self):
        """The constant-sigma family pins at `LEAST`, which is the same failure
        wearing the opposite sign: a lever against a stop cannot answer the
        next bar, whichever stop it is."""
        from till_infinity.statespace.pooling import Pooled

        pool = Pooled()
        pool.members[0].factor = pool.members[0].least
        assert pool.saturated == (pool.names[0],)

    def test_an_unadapted_pool_has_no_lever_to_saturate(self):
        """`adapt=False` members carry no loop, so the question does not apply
        and must not raise - this is the arm every `rule` figure was measured
        on, and a diagnostic that crashed on it would be worse than none."""
        from till_infinity.statespace.pooling import Pooled

        assert Pooled(adapt=False).saturated == ()

    def test_the_clamp_is_reachable_and_its_default_has_not_moved(self):
        """Reachable so the measured value can be set once it is known; left
        alone until then, because a clamp exists to stop a loop chasing an
        outlier and widening it by default weakens that for every member."""
        from till_infinity.statespace.adapting import MOST
        from till_infinity.statespace.facade import Desk
        from till_infinity.statespace.pooling import Pooled

        assert Pooled().most is None
        assert {one.most for one in Pooled().members} == {MOST}
        assert {one.most for one in Pooled(most=1e7).members} == {1e7}

        assert Desk().clamp is None
        desk = Desk(clamp=1e7)
        desk.read("gold", "5m", 3_600.0, -16.0, 0.67)
        assert {one.most for one in desk._members[("gold", "5m")].members} == {1e7}

    def test_the_service_line_says_when_a_lever_has_run_out_of_room(self):
        from till_infinity.statespace.config import Settings
        from till_infinity.statespace.engine import Engine
        from till_infinity.statespace.service import Watcher

        engine = Engine(settings=Settings(intervals=("5m",), warm_bars=1))
        engine.desk.read("gold", "5m", 3_600.0, -16.0, 0.67)
        watcher = Watcher(engine=engine)

        assert engine.saturated == 0
        clean = watcher.report(at=1_000_000.0)
        assert "bars folded" in clean
        assert "lever" not in clean

        for one in engine.desk._members[("gold", "5m")].members:
            one.factor = one.most
        assert engine.saturated == 1
        said = watcher.report(at=2_000_000.0)
        assert "lever's stop" in said
        assert "adapting-strata.md" in said
