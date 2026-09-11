"""Does a field carry anything, and does anybody ask.

`run_vol` and `pivot` are identically zero across 20,000 production outcomes -
published on every level call, journalled on every outcome, and fed to models
that weight them. Nothing noticed until somebody cut by them by hand.
"""

import pytest

from till_infinity.shared.liveness import assert_alive, survey


def rows(**columns):
    """Rows from columns, so a fixture reads as the thing being asserted."""
    length = max(len(v) for v in columns.values())
    return [{k: v[i] for k, v in columns.items() if i < len(v)} for i in range(length)]


def test_a_constant_field_is_reported_constant():
    """`run_vol` as it actually is in production: present, numeric, always zero."""
    got = survey(rows(run_vol=[0.0] * 50, edge=[i / 50 for i in range(50)]))

    assert got["run_vol"].constant == 0.0
    assert got["run_vol"].distinct == 1
    assert got["edge"].constant is None
    assert got["edge"].distinct > 1


def test_an_absent_key_is_not_the_same_fault_as_a_zero_one():
    """A key nobody publishes and a key published as zero look identical in
    every cut this project makes, and they have different fixes."""
    got = survey(rows(pivot=[0.0] * 30, edge=[1.0] * 30))

    assert "pivot" in got
    assert got["pivot"].constant == 0.0
    assert "backcheck" not in got, "an absent key is absent, not constant"


def test_a_nearly_constant_field_is_the_shape_of_one_that_is_dying():
    """99.5% one value is alive by the letter and useless in practice."""
    values = [0.0] * 199 + [1.0]
    got = survey(rows(backcheck=values))

    assert got["backcheck"].constant is None, "it does vary"
    assert got["backcheck"].near_constant is True
    assert got["backcheck"].share_top == pytest.approx(0.995, abs=0.001)


def test_assert_alive_raises_and_names_the_dead_key():
    """A harness about to cut by a column gets a loud failure rather than a
    flat table it will then try to explain."""
    data = rows(run_vol=[0.0] * 20, edge=list(range(20)))

    assert_alive(data, "edge")
    with pytest.raises(ValueError, match="run_vol"):
        assert_alive(data, "run_vol", "edge")


def test_a_field_dead_in_one_producer_is_alive_overall():
    """The shape `run_vol` would have if only one producer were broken - and
    the pooled survey would call it alive and be useless."""
    data = [
        *[{"actor": "structures", "run_vol": 0.0} for _ in range(40)],
        *[{"actor": "trading", "run_vol": float(i)} for i in range(40)],
    ]

    pooled = survey(data)
    assert pooled["run_vol"].constant is None, "alive when the producers are mixed"

    per_actor = survey(data, within="actor")
    assert per_actor["structures"]["run_vol"].constant == 0.0
    assert per_actor["trading"]["run_vol"].constant is None


def test_non_numeric_fields_are_left_alone():
    """This asks one question - does a number vary - and a string column is not
    it. Reporting `side` as 'constant' when every row is a buy would bury the
    numeric answers under noise."""
    got = survey(rows(side=["buy"] * 20, edge=[1.0] * 20))

    assert "side" not in got
    assert got["edge"].constant == 1.0


def test_booleans_are_not_numbers_here():
    """`True` is an `int` in Python and a flag is not a measurement; a flag that
    is always true is a different conversation from a feature that is always
    zero."""
    got = survey(rows(actionable=[False] * 20, edge=[1.0] * 20))

    assert "actionable" not in got
