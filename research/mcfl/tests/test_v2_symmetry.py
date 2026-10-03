"""v2 under the flip: parsing the flipped chart gives every v2 entity with its direction reversed,
its prices negated and its mirrored values swapped (HH and LL, EQUAL_HIGHS and EQUAL_LOWS, UP and
DOWN, BUY and SELL, a candlestick pattern and its twin) - on series with timestamps and volume."""
from __future__ import annotations

import pytest
from mcfl.core import V2_TYPES
from mcfl.parse import flip, parse
from test_symmetry import _fix_rule, mirror
from test_v2_causality import series


@pytest.mark.parametrize(("kind", "seed"), [("garch", 31), ("trend", 32), ("walk", 33)])
def test_flip_reverses_every_v2_entity(kind, seed):
    df = series(2500, seed, kind)
    a, b = parse(df), parse(flip(df))
    m = mirror(a)
    got, want = {_fix_rule(e) for e in m.entities}, set(b.entities)
    assert got == want, (sorted(map(str, got - want))[:2], sorted(map(str, want - got))[:2])
    assert set(m.relations) == set(b.relations)
    assert set(m.transitions) == set(b.transitions)
    have = {e.type for e in a.entities} & set(V2_TYPES)
    assert len(have) >= 10, have
