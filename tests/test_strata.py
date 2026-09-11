"""Cutting within strata by default, because the rule has failed four times.

`aligning.md`, `forecasting.md`, `trapping.md` and `instruments.md` each had a
pooled figure reverse when conditioned. The lesson was written down every time,
and the next cut was pooled again - which is the signature of a rule that needs
to be mechanical rather than remembered.
"""

import pytest

from till_infinity.shared.strata import compare


def row(bucket, value, **over):
    got = {"bucket": bucket, "r": value, "strategy": "alpha", "interval": "5m"}
    got.update(over)
    return got


def test_a_reversal_in_every_stratum_is_named():
    """Pooled says low is best. Both strategies say high is best. The pooled
    ordering is an artefact of one strategy holding most of the rows."""
    # Simpson's shape: the stratum that scores well is concentrated in `low`,
    # and the one that scores badly in `high`, so the pooled ranking is carried
    # by *who is in each bucket* rather than by the buckets.
    #
    #   pooled low  = (50 x -0.5 + 400 x 2.0) / 450 = +1.722
    #   pooled high = (400 x -0.2 + 50 x 2.4) / 450 = +0.089
    #
    # while inside each stratum `high` is the better bucket, by 0.3 and by 0.4.
    rows = [
        *[row("low", -0.5, strategy="alpha") for _ in range(50)],
        *[row("high", -0.2, strategy="alpha") for _ in range(400)],
        *[row("low", 2.0, strategy="beta") for _ in range(400)],
        *[row("high", 2.4, strategy="beta") for _ in range(50)],
    ]
    got = compare(rows, value="r", bucket="bucket", within=("strategy",))

    assert got.pooled_best == "low"
    assert got.reversals, "both strata prefer high; the pooled figure does not"
    assert {name for name, _ in got.reversals} == {"alpha", "beta"}
    assert "REVERSED" in got.render()


def test_an_ordering_that_holds_everywhere_raises_nothing():
    rows = [
        *[row("low", 0.1, strategy=s) for s in ("alpha", "beta") for _ in range(200)],
        *[row("high", 0.9, strategy=s) for s in ("alpha", "beta") for _ in range(200)],
    ]
    got = compare(rows, value="r", bucket="bucket", within=("strategy",))

    assert got.pooled_best == "high"
    assert not got.reversals
    assert "REVERSED" not in got.render()


def test_a_thin_stratum_is_reported_and_not_counted_as_a_reversal():
    """`sweep-aware` at n=4 on Boom is exactly this - and it carried the
    finding. Hiding it reproduces the original error with an extra step;
    counting it as a reversal makes every noisy cell shout."""
    rows = [
        *[row("low", -0.5, strategy="alpha") for _ in range(300)],
        *[row("high", -0.2, strategy="alpha") for _ in range(300)],
        # Four rows, pointing the other way.
        *[row("low", 3.0, strategy="tiny") for _ in range(2)],
        *[row("high", -3.0, strategy="tiny") for _ in range(2)],
    ]
    got = compare(rows, value="r", bucket="bucket", within=("strategy",), min_n=100)

    assert not got.reversals, "four rows is not evidence of a reversal"
    rendered = got.render()
    assert "tiny" in rendered, "but it must still be visible"
    assert "below min_n" in rendered


def test_rows_missing_the_stratum_key_are_named_not_dropped():
    """A row silently dropped from a comparison is the failure this exists to
    prevent, so an absent key groups under a name rather than vanishing."""
    rows = [
        *[row("low", 0.1, strategy="alpha") for _ in range(150)],
        *[row("high", 0.5, strategy="alpha") for _ in range(150)],
        *[{"bucket": "low", "r": 0.1} for _ in range(150)],
        *[{"bucket": "high", "r": 0.5} for _ in range(150)],
    ]
    got = compare(rows, value="r", bucket="bucket", within=("strategy",))

    assert "unknown" in got.strata
    assert sum(s.n for s in got.strata.values()) == len(rows)


def test_the_boom_shape_reproduced_from_the_measured_numbers():
    """The real case, 2026-09-11. `Boom 1000` reported -0.595R as an instrument.
    36 of its 48 closes were `thesis-only` at -0.595R - the same number, because
    that strategy *was* the sample - while `sweep-aware` ran +1.134R on it.

    The pooled instrument cut is a composition of populations that disagree, and
    the warning is what would have said so before three measurements were spent
    on it."""
    rows = [
        *[row("boom", -0.595, strategy="thesis-only") for _ in range(36)],
        *[row("boom", 1.134, strategy="sweep-aware") for _ in range(4)],
        *[row("crash", 0.111, strategy="thesis-only") for _ in range(18)],
        *[row("crash", -0.284, strategy="sweep-aware") for _ in range(4)],
    ]
    got = compare(rows, value="r", bucket="bucket", within=("strategy",), min_n=10)

    assert got.pooled_best == "crash", "pooled: boom is the bad instrument"
    # thesis-only agrees with the pooled reading; it is most of the sample.
    # sweep-aware is below min_n at 4, so it is shown and not counted.
    assert "sweep-aware" in got.render()
    assert got.strata["thesis-only"].n == 54


def test_a_callable_bucket_works_as_well_as_a_key():
    rows = [row("x", float(i % 3)) for i in range(600)]
    got = compare(
        rows,
        value="r",
        bucket=lambda r: "big" if r["r"] >= 1 else "small",
        within=(),
        min_n=10,
    )

    assert set(got.buckets) == {"big", "small"}
    assert got.buckets["big"].mean > got.buckets["small"].mean


def test_the_value_must_carry_information():
    """Straight through to the liveness check - a comparison of a constant is a
    flat table somebody will then try to explain."""
    rows = [row("low", 0.0) for _ in range(200)] + [row("high", 0.0) for _ in range(200)]
    with pytest.raises(ValueError, match="r"):
        compare(rows, value="r", bucket="bucket", within=())
