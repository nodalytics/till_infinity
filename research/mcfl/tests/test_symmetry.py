"""Flip the chart (prices negated, highs and lows swapped) and MCFL must say the same thing with
every direction reversed and every price negated."""
from __future__ import annotations

import pytest
from mcfl import synth
from mcfl.core import Chart, Entity, Failure, Relation, Transition, flip_value, swap_key
from mcfl.parse import flip, parse


def _sid(x):
    if not isinstance(x, str) or x.count(".") < 2:
        return x
    head, d, rest = x.split(".", 2)
    return f"{head}.{'D' if d == 'U' else 'U' if d == 'D' else d}.{rest}"


def _mirror_attrs(attrs):
    """Attribute names and values as the flipped chart has them (`core.swap_key`, `core.flip_value`:
    the flip tables, tested on their own in test_candles.py), with ids mapped by direction."""
    return tuple(sorted((swap_key(k), _sid(flip_value(k, v))) for k, v in attrs))


def mirror(ch: Chart) -> Chart:
    ents = tuple(Entity(_sid(e.id), e.type, e.dir.flip(), e.at, e.known_at,
                        _mirror_attrs(e.attrs), e.force,
                        tuple(_sid(p) for p in e.parts)) for e in ch.entities)
    return Chart(ch.n, ents,
                 tuple(Relation(r.kind, _sid(r.src), _sid(r.dst), r.known_at) for r in ch.relations),
                 tuple(Failure(_sid(f.candidate), f.rule.replace("_UP", "_X").replace("_DOWN", "_UP").replace("_X", "_DOWN"),
                               f.slot, f.clause, f.known_at) for f in ch.failures),
                 tuple(Transition(_sid(t.zone), t.src, t.dst, t.at, t.known_at, _sid(t.event)) for t in ch.transitions),
                 tuple((_sid(z), s) for z, s in ch.states), tuple(_sid(p) for p in ch.pending))


def _fix_rule(e: Entity) -> Entity:
    if e.type != "ZONE":
        return e
    return Entity(e.id, e.type, e.dir, e.at, e.known_at,
                  tuple((k, f"ZONE_{e.dir.value}" if k == "rule" else v) for k, v in e.attrs), e.force, e.parts)


@pytest.mark.parametrize("seed", [1, 4])
def test_flip_reverses_every_direction(seed):
    df = synth.garch(1500, seed=seed)
    a, b = parse(df), parse(flip(df))
    m = mirror(a)
    assert {_fix_rule(e) for e in m.entities} == set(b.entities)
    assert set(m.relations) == set(b.relations)
    assert set(m.failures) == set(b.failures)
    assert set(m.transitions) == set(b.transitions)
    assert dict(m.states) == dict(b.states)
    assert set(m.pending) == set(b.pending)
    ups = sum(e.dir.value == "UP" for e in a.entities)
    assert ups == sum(e.dir.value == "DOWN" for e in b.entities)
