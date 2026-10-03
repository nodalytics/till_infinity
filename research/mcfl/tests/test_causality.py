"""The most important test in the package: nothing MCFL emits may depend on a bar after its
`known_at`, and `known_at` must be the first bar it could be known.

For every bar T, parsing the series cut at T must give exactly the entities (and relations,
failures and transitions) of the full parse whose known_at is at most T - identical, attribute for
attribute. Something the cut parse misses was using the future; something it has extra means the
full parse dropped or changed it with hindsight. Checking every T means each entity is checked at
its own known_at (present) and at known_at - 1 (absent), which pins known_at exactly.
"""
from __future__ import annotations

import pytest
from mcfl import synth
from mcfl.parse import parse

SERIES = [
    ("walk", synth.walk(360, seed=3)),
    ("garch", synth.garch(360, seed=5)),
    ("trend", synth.trend(360, seed=7)),
]


def _upto(chart, T):
    return (
        {e for e in chart.entities if e.known_at <= T},
        {r for r in chart.relations if r.known_at <= T},
        {f for f in chart.failures if f.known_at <= T},
        {t for t in chart.transitions if t.known_at <= T},
    )


def _all(chart):
    return set(chart.entities), set(chart.relations), set(chart.failures), set(chart.transitions)


@pytest.mark.parametrize(("name", "df"), SERIES, ids=[s[0] for s in SERIES])
def test_every_prefix_is_the_full_parse_up_to_it(name, df):
    full = parse(df)
    assert len(full.of("ZONE")) > 0, "the fixture should exercise the grammar"
    assert len([e for e in full.entities if e.type in ("REVISIT", "FAIL", "ACCEPT", "REJECT")]) > 0
    for T in range(len(df)):
        cut = parse(df.iloc[:T + 1])
        got, want = _all(cut), _upto(full, T)
        for kind, g, w in zip(("entities", "relations", "failures", "transitions"), got, want):
            assert g == w, f"{name} T={T} {kind}: extra {sorted(map(str, g - w))[:3]} missing {sorted(map(str, w - g))[:3]}"


def test_each_entity_reparses_identically_at_its_known_at():
    """The brief's form of the check, entity by entity, on a longer series: cut at known_at, the
    identical entity is there; cut one bar earlier, it is not."""
    df = synth.garch(900, seed=11)
    full = parse(df)
    cache = {}

    def at(T):
        if T not in cache:
            cache[T] = set(parse(df.iloc[:T + 1]).entities)
        return cache[T]

    for e in full.entities:
        assert e in at(e.known_at), f"{e.id} not reproduced at its known_at {e.known_at}"
        if e.known_at > 0:
            assert e not in at(e.known_at - 1), f"{e.id} already known before its known_at"


def test_break_reference_known_before_the_break():
    full = parse(synth.walk(2000, seed=2))
    ids = full.by_id()
    for b in full.of("BREAK"):
        ref = ids[b.get("ref")]
        assert ref.known_at < b.at
        assert b.known_at >= b.at
