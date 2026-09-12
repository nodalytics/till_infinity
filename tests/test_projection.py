"""The forward cone is exact, so the only thing to test is whether it is honest.

`projection.py` fits nothing - the band is the published sigma read off a normal
at a quantile. What can still be wrong is the scoring: a calibration that says
"centred" when the forecast is off, or "the right width" when the bands are
twice too wide, would let a wrong drift convention be adopted and stay adopted.

So the load-bearing test here is `test_pit_is_uniform_when_the_convention_is_right`
and its partner `..._and_is_not_when_it_is_wrong`. Between them they prove the
instrument can tell the two conventions apart on a process whose truth is set in
the test, which is the only place on this book where that is possible.
"""

from __future__ import annotations

import itertools
import math
import random

import pytest

from till_infinity.structures.vol import projection


def test_an_unnamed_instrument_projects_nothing():
    """Real markets and the Boom, Crash and Step families publish no volatility.

    Inventing one for them is the failure `stated.py` exists to avoid, and this
    module inherits that decision rather than re-making it.
    """
    assert projection.project("XAUUSD", 2000.0, 3600.0) is None
    assert projection.project("boom_500_index", 1000.0, 3600.0) is None
    assert projection.sigma_for("step_index", 3600.0) is None
    assert projection.project("volatility_75_index", 1000.0, 3600.0) is not None


def test_the_band_widens_as_the_square_root_of_time():
    """Four times the horizon is twice the band, which is the part a single
    number hides and the reason `path` exists."""
    one = projection.sigma_for("volatility_75_index", 3600.0)
    four = projection.sigma_for("volatility_75_index", 4 * 3600.0)
    assert four == pytest.approx(2.0 * one, rel=1e-12)


def test_sigma_is_the_name_at_a_one_year_horizon():
    """The whole module rests on the name meaning what it says, so pin it."""
    year = projection.SECONDS_PER_YEAR
    assert projection.sigma_for("volatility_100_index", year) == pytest.approx(1.0)
    assert projection.sigma_for("volatility_75_index", year) == pytest.approx(0.75)


def test_jump_carries_the_measured_multiple_not_its_name():
    """Jump indices realise 1.32x their name over 60 days, in both halves.

    That is `stated.py`'s finding and it must survive the trip through here,
    because a cone built on the bare name would be 32% too narrow on five feeds.
    """
    year = projection.SECONDS_PER_YEAR
    assert projection.sigma_for("jump_25_index", year) == pytest.approx(0.25 * 1.322)


def test_the_two_conventions_differ_by_exactly_half_sigma_squared():
    """This gap is the whole identification argument; if it is not this, nothing
    downstream measures what it claims."""
    year = projection.SECONDS_PER_YEAR
    sigma = projection.sigma_for("volatility_100_index", year)
    ito = projection.drift_for("volatility_100_index", year, "ito")
    plain = projection.drift_for("volatility_100_index", year, "plain")
    assert plain == 0.0
    assert ito == pytest.approx(-0.5 * sigma * sigma)


def test_bands_are_symmetric_in_log_around_the_median():
    cone = projection.project("volatility_75_index", 1000.0, 3600.0)
    for level in projection.BANDS:
        low, high = cone.bands[level]
        assert math.log(cone.median / low) == pytest.approx(math.log(high / cone.median))


def test_wider_bands_nest():
    cone = projection.project("volatility_75_index", 1000.0, 3600.0)
    levels = sorted(projection.BANDS)
    for inner, outer in itertools.pairwise(levels):
        assert cone.bands[outer][0] < cone.bands[inner][0]
        assert cone.bands[outer][1] > cone.bands[inner][1]


def test_the_median_quantile_is_the_median():
    cone = projection.project("volatility_75_index", 1000.0, 3600.0)
    assert cone.quantile(0.5) == pytest.approx(cone.median, rel=1e-9)


def test_the_quantile_agrees_with_the_hardcoded_bands():
    """The bands use four hardcoded z values and `quantile` bisects the CDF.

    They are independent routes to the same number, so their agreement is a
    check on both - and on the four constants, which are otherwise unverified
    digits typed into a module.
    """
    cone = projection.project("volatility_75_index", 1000.0, 3600.0)
    for level in projection.BANDS:
        low, high = cone.bands[level]
        p = (1.0 - level / 100.0) / 2.0
        assert cone.quantile(p) == pytest.approx(low, rel=1e-6)
        assert cone.quantile(1.0 - p) == pytest.approx(high, rel=1e-6)


def test_a_path_widens_and_never_narrows():
    cones = projection.path("volatility_75_index", 1000.0, 3600.0, steps=8)
    assert len(cones) == 8
    widths = [c.bands[95][1] - c.bands[95][0] for c in cones]
    assert widths == sorted(widths)


def _simulate(feed: str, seconds: float, convention: str, n: int, seed: int):
    """Draw `n` outcomes from the generator that `convention` describes."""
    rng = random.Random(seed)
    sigma = projection.sigma_for(feed, seconds)
    drift = projection.drift_for(feed, seconds, convention)
    return [1000.0 * math.exp(drift + sigma * rng.gauss(0.0, 1.0)) for _ in range(n)]


def test_pit_is_uniform_when_the_convention_is_right():
    """The load-bearing test. Score the truth with its own convention and the
    PIT must be uniform: mean 0.5, variance 1/12, dispersion 1."""
    feed, seconds = "volatility_100_index", projection.SECONDS_PER_YEAR
    cal = projection.Calibration(convention="ito")
    cone = projection.project(feed, 1000.0, seconds, convention="ito")
    for actual in _simulate(feed, seconds, "ito", 20_000, seed=11):
        cal.record(cone, actual)

    assert cal.warm
    assert cal.mean == pytest.approx(0.5, abs=0.02)
    assert cal.variance == pytest.approx(1.0 / 12.0, abs=0.005)
    assert cal.dispersion == pytest.approx(1.0, abs=0.05)
    assert abs(cal.bias_sigma()) < 3.0, "a correct forecast must not read as biased"


def test_pit_is_not_uniform_when_the_convention_is_wrong():
    """And the partner: score the same truth with the other convention and the
    instrument must notice. If this passes trivially the identification is
    worthless."""
    feed, seconds = "volatility_100_index", projection.SECONDS_PER_YEAR
    cal = projection.Calibration(convention="plain")
    cone = projection.project(feed, 1000.0, seconds, convention="plain")
    for actual in _simulate(feed, seconds, "ito", 20_000, seed=11):
        cal.record(cone, actual)

    # Truth drifts down by sigma^2/2 = 0.5 while `plain` centres at zero, so the
    # outcomes land low in `plain`'s CDF and the mean PIT sits near Phi(-0.5).
    assert cal.mean < 0.45
    assert abs(cal.bias_sigma()) > 10.0


def test_coverage_matches_the_nominal_band():
    feed, seconds = "volatility_100_index", projection.SECONDS_PER_YEAR
    cal = projection.Calibration(convention="ito")
    cone = projection.project(feed, 1000.0, seconds, convention="ito")
    for actual in _simulate(feed, seconds, "ito", 20_000, seed=5):
        cal.record(cone, actual)
    for level in projection.BANDS:
        assert cal.coverage(level) == pytest.approx(level / 100.0, abs=0.02)


def test_dispersion_reports_bands_that_are_too_tight():
    """A forecast at half the true sigma must read as too tight, not merely as
    biased - the two failures need different fixes.

    **Pinned to the closed form rather than to a threshold**, because the
    intuitive answer is wrong and a loose bound would hide that. Scoring with
    `sigma/2` makes the PIT `u = Phi(2 Z)`, and for `u = Phi(a Z)` the variance
    is `arcsin(rho) / (2 pi)` with `rho = a^2 / (1 + a^2)`. At `a = 2` that is
    `arcsin(0.8) / (2 pi) = 0.14758`, so dispersion is
    `sqrt((1/12) / 0.14758) = 0.7515` - **not the 0.5 that halving sigma
    suggests.** Dispersion is a variance ratio of a bounded transform, not a
    ratio of sigmas, and anyone reading it as the latter will misjudge by a
    third.
    """
    feed, seconds = "volatility_100_index", projection.SECONDS_PER_YEAR
    cone = projection.project(feed, 1000.0, seconds, convention="ito")
    narrow = projection.Cone(
        feed=feed,
        seconds=seconds,
        price=1000.0,
        sigma=cone.sigma / 2.0,
        drift=cone.drift,
        convention="ito",
        bands=dict(cone.bands),
    )
    cal = projection.Calibration(convention="ito")
    for actual in _simulate(feed, seconds, "ito", 20_000, seed=3):
        cal.record(narrow, actual)

    exact = math.sqrt((1.0 / 12.0) / (math.asin(0.8) / (2.0 * math.pi)))
    assert exact == pytest.approx(0.7515, abs=1e-4), "the closed form itself"
    assert cal.dispersion == pytest.approx(exact, abs=0.01)
    assert cal.dispersion < 1.0, "too-tight bands must read below one"


def test_the_projector_picks_the_convention_that_generated_the_data():
    """End to end: hand a `Projector` outcomes from the `ito` generator and its
    standings must put `ito` first."""
    feed, seconds = "volatility_100_index", projection.SECONDS_PER_YEAR
    projector = projection.Projector(feed=feed)
    for actual in _simulate(feed, seconds, "ito", 5_000, seed=17):
        projector.settle(1000.0, seconds, actual)
    standings = projector.standings()
    assert standings, "both conventions should be warm after 5,000 settlements"
    assert standings[0][0] == "ito"
    assert standings[0][1] < standings[1][1]


def test_resolved_is_false_until_the_sample_can_actually_decide():
    """`warm` and `resolved` are different claims and conflating them is how a
    convention gets adopted on noise."""
    cal = projection.Calibration(convention="ito")
    cone = projection.project("volatility_75_index", 1000.0, 3600.0)
    for actual in _simulate("volatility_75_index", 3600.0, "ito", 300, seed=2):
        cal.record(cone, actual)
    assert cal.warm
    assert not cal.resolved
    assert cal.information < projection.RESOLVES_AT


def test_more_bars_over_the_same_span_buy_no_resolution():
    """The defect this pins cost a wrong flag in production.

    `resolved` was a bar count, `n >= 50_000`. But the information about a drift
    is **calendar span, not sample size**: the log returns telescope to
    `log(S_end / S_start)`, so a year of hourly bars says no more about it than
    a year of daily ones. Counting rows raised the flag at about a fifth of the
    separation it promised at hourly spacing - `research/pipeline.md` measured
    it. Here the hourly series has **24x the rows and the same information**.
    """
    feed = "volatility_75_index"
    day = projection.SECONDS_PER_YEAR / 365.0
    hour = day / 24.0

    daily = projection.Calibration(convention="ito")
    cone_d = projection.project(feed, 1.0, day, convention="ito")
    for actual in _simulate(feed, day, "ito", 365, seed=4):
        daily.record(cone_d, actual / 1000.0)

    hourly = projection.Calibration(convention="ito")
    cone_h = projection.project(feed, 1.0, hour, convention="ito")
    for actual in _simulate(feed, hour, "ito", 365 * 24, seed=5):
        hourly.record(cone_h, actual / 1000.0)

    assert hourly.n == 24 * daily.n
    assert hourly.information == pytest.approx(daily.information, rel=1e-9)
    assert hourly.separation == pytest.approx(daily.separation, rel=1e-9)


def test_separation_is_the_square_root_of_the_information():
    """`sqrt(sum sigma^2 T) / 2` is the whole criterion; pin it to the form."""
    feed = "volatility_100_index"
    seconds = projection.SECONDS_PER_YEAR
    cal = projection.Calibration(convention="ito")
    cone = projection.project(feed, 1.0, seconds, convention="ito")
    for actual in _simulate(feed, seconds, "ito", 40, seed=6):
        cal.record(cone, actual / 1000.0)
    assert cal.information == pytest.approx(40 * cone.sigma**2)
    assert cal.separation == pytest.approx(math.sqrt(cal.information) / 2.0)
    assert cal.resolved is (cal.information >= projection.RESOLVES_AT)


def test_touch_defers_to_barriers():
    """First-passage has one home and it carries the continuity correction."""
    from till_infinity.trading import barriers

    assert projection.touch(2.0, 1.0) == pytest.approx(barriers.probability(2.0, 1.0))


def test_a_degenerate_outcome_is_dropped_not_counted():
    """A non-positive price cannot be logged; it must not silently become a PIT."""
    cal = projection.Calibration(convention="ito")
    cone = projection.project("volatility_75_index", 1000.0, 3600.0)
    cal.record(cone, 0.0)
    cal.record(cone, -5.0)
    assert cal.n == 0


def test_the_book_keeps_one_projector_per_feed():
    book = projection.Book()
    assert book.of("volatility_75_index") is book.of("volatility_75_index")
    assert book.of("volatility_25_index") is not book.of("volatility_75_index")


def test_the_book_forgets_instruments_the_desk_dropped():
    """Unbounded growth is the failure mode here. `volatility.Book` grew to
    5,416 keys across 445 feeds for a desk that trades a few dozen."""
    book = projection.Book()
    for feed in ("volatility_75_index", "volatility_25_index", "volatility_10_index"):
        book.of(feed)
    dropped = book.forget({"volatility_75_index"})
    assert dropped == 2
    assert book.feeds() == ["volatility_75_index"]


def test_the_book_pools_the_convention_across_feeds():
    """The convention is a property of the generator, not of an instrument, so
    a verdict that one long-lived feed could carry alone would be worth less."""
    book = projection.Book()
    seconds = projection.SECONDS_PER_YEAR
    for seed, feed in enumerate(("volatility_100_index", "volatility_75_index"), start=31):
        for actual in _simulate(feed, seconds, "ito", 3_000, seed=seed):
            book.settle(feed, 1000.0, seconds, actual)
    standings = book.standings()
    assert standings, "both conventions should be warm across two feeds"
    assert standings[0][0] == "ito"
    assert len(book.feeds()) == 2


def test_the_book_ignores_instruments_that_publish_no_volatility():
    """A feed with no named sigma must accumulate nothing rather than a zero."""
    book = projection.Book()
    book.settle("XAUUSD", 2000.0, 3600.0, 2010.0)
    assert book.standings() == []


def _drive(engine, feed: str, bars: int = 40) -> None:
    price = 1000.0
    for i in range(bars):
        price *= 1.0 + (0.001 if i % 2 else -0.0009)
        engine.observe_bar(
            {
                "feed": feed,
                "interval": "5m",
                "venue": "DERIV",
                "time": 1_700_000_000 + i * 300,
                "open": price * 0.999,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
            }
        )


def test_the_engine_actually_settles_a_closed_bar(monkeypatch):
    """Drives the engine and checks the calibration moved.

    **This replaces a test that only grepped the source.** That one passed
    while the hook sat somewhere it could never fire, which is precisely the
    reassurance an inert feature does not deserve.
    """
    import till_infinity.structures as sx

    monkeypatch.setattr(projection, "ENABLED", True)
    feed = "volatility_75_index"
    engine = sx.Engine(intervals=("5m",), single_source=frozenset({feed}))
    _drive(engine, feed)

    assert engine.projection.feeds() == [feed]
    for convention in projection.CONVENTIONS:
        assert engine.projection.of(feed)._cal[convention].n > 0


def test_the_engine_settles_nothing_when_the_flag_is_off(monkeypatch):
    import till_infinity.structures as sx

    monkeypatch.setattr(projection, "ENABLED", False)
    feed = "volatility_75_index"
    engine = sx.Engine(intervals=("5m",), single_source=frozenset({feed}))
    _drive(engine, feed)
    assert engine.projection.feeds() == []


def test_projection_does_not_depend_on_the_volatility_learner(monkeypatch):
    """The regression this pins cost a deploy.

    The hook first went in beside `self.vol.learn` inside `_learn_vol`, which
    runs only when `STRUCTURES_VOL_LEARNER` is set. Projection has nothing to do
    with that model, so turning the learner off would have silently stopped this
    accumulating while `STRUCTURES_PROJECTION` still read `1` - a feature that is
    inert while its own flag says otherwise, which is the failure mode this desk
    hit twice on 2026-09-12.
    """
    import till_infinity.structures as sx

    monkeypatch.setattr(projection, "ENABLED", True)
    feed = "volatility_75_index"
    engine = sx.Engine(intervals=("5m",), single_source=frozenset({feed}))
    engine.learn_vol = False
    _drive(engine, feed)
    assert engine.projection.of(feed)._cal["ito"].n > 0, (
        "projection must accumulate with the volatility learner off"
    )


def test_an_unnamed_feed_accumulates_nothing_through_the_engine(monkeypatch):
    import till_infinity.structures as sx

    monkeypatch.setattr(projection, "ENABLED", True)
    engine = sx.Engine(intervals=("5m",), single_source=frozenset({"gold"}))
    _drive(engine, "gold")
    assert engine.projection.feeds() == []
