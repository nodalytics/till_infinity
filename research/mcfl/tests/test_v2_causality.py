"""v2 under the package's most important test: every prefix of a series parses to exactly the
entities, relations, failures and transitions of the full parse known by then - now on series with
timestamps and volume, so the session, volume and every other v2 entity is exercised - and each
rarer v2 entity is present at its known_at and absent one bar earlier."""
from __future__ import annotations

import fixtures as F
import pytest
from mcfl import synth
from mcfl.parse import parse

#: the v2 types each prefix test must see (so the test cannot pass by finding nothing)
COMMON = {"SWING", "STRUCTURE_SHIFT", "VOID_PARTIAL", "VOID_FILLED", "VOID_INVERTED"}
#: rarer ones, checked entity by entity on a longer series
RARE = {"CHARACTER_SHIFT"}


def series(n: int, seed: int, kind: str = "garch"):
    df = {"garch": synth.garch, "walk": synth.walk, "trend": synth.trend}[kind](n, seed=seed)
    return F.with_time(df, 900, start=1_700_000_000 - 1_700_000_000 % 86400)


def _upto(chart, T):
    return ({e for e in chart.entities if e.known_at <= T}, {r for r in chart.relations if r.known_at <= T},
            {f for f in chart.failures if f.known_at <= T}, {t for t in chart.transitions if t.known_at <= T})


def _all(chart):
    return set(chart.entities), set(chart.relations), set(chart.failures), set(chart.transitions)


@pytest.mark.parametrize(("kind", "seed"), [("garch", 21), ("trend", 22)])
def test_every_prefix_is_the_full_parse_up_to_it(kind, seed):
    df = series(320, seed, kind)
    full = parse(df)
    have = {e.type for e in full.entities}
    assert COMMON <= have, COMMON - have
    for T in range(len(df)):
        got, want = _all(parse(df.iloc[:T + 1])), _upto(full, T)
        for name, g, w in zip(("entities", "relations", "failures", "transitions"), got, want):
            assert g == w, f"T={T} {name}: extra {sorted(map(str, g - w))[:2]} missing {sorted(map(str, w - g))[:2]}"


def test_rare_v2_entities_at_their_known_at():
    df = series(2500, 23)
    full = parse(df)
    cache = {}

    def at(T):
        if T not in cache:
            cache[T] = parse(df.iloc[:T + 1])
        return cache[T]

    for kind in sorted(RARE):
        ents = [e for e in full.entities if e.type == kind]
        assert ents, kind
        for e in ents[:4]:
            assert e in set(at(e.known_at).entities), e.id
            assert e not in set(at(e.known_at - 1).entities), e.id
