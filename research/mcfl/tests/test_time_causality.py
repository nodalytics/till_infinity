"""The time core under the package's most important test: on a market calendar with closures and
weekends, every prefix parses to exactly the entities and relations of the full parse known by then
- spans, calendar anchors, windows, HTF closes, timeouts and first moves included - and each slower
time entity (warm-up baselines: TEMPO_STATE, LATE, EARLY, STALL, the time-of-day class) is present
at its known_at and absent one bar earlier. Also: an entity's interval never ends after it is known."""
from __future__ import annotations

import fixtures as F
import pytest
from mcfl import synth
from mcfl.core import TIME_TYPES
from mcfl.parse import parse

FRIDAY_NOON = F.WINTER_MONDAY + 4 * 86400 + 12 * 3600
EVERY_PREFIX = {"WINDOW", "WINDOW_CLOSE", "DAY_OPEN", "WEEK_OPEN", "HTF_CLOSE", "SESSION_FIRST_MOVE", "IN_WINDOW",
                "EPISODE", "TIMEOUT"}
SLOW = ("TEMPO_STATE", "LATE", "EARLY", "STALL", "MONTH_OPEN", "IN_WINDOW", "TIMEOUT", "EPISODE")


def _upto(chart, T):
    return {e for e in chart.entities if e.known_at <= T}, {r for r in chart.relations if r.known_at <= T}


def test_every_prefix_on_a_calendar_with_closures():
    df = F.with_calendar(synth.ticks(synth.garch(300, seed=101), seed=102), 900, FRIDAY_NOON, "index")
    full = parse(df)
    have = {e.type for e in full.entities}
    assert EVERY_PREFIX <= have, EVERY_PREFIX - have
    for T in range(len(df)):
        cut = parse(df.iloc[:T + 1])
        ents, rels = _upto(full, T)
        g = set(cut.entities)
        assert g == ents, f"T={T}: extra {sorted(map(str, g - ents))[:2]} missing {sorted(map(str, ents - g))[:2]}"
        assert set(cut.relations) == rels, T


@pytest.fixture(scope="module")
def long():
    df = F.with_calendar(synth.ticks(synth.garch(2200, seed=103), seed=104), 900, F.WINTER_MONDAY + 20 * 86400, "fx")
    return df, parse(df)


def test_slow_time_entities_at_their_known_at(long):
    df, full = long
    cache = {}

    def at(T):
        if T not in cache:
            cache[T] = set(parse(df.iloc[:T + 1]).entities)
        return cache[T]

    for kind in SLOW:
        ents = [e for e in full.entities if e.type == kind]
        assert ents, kind
        for e in (ents[0], ents[len(ents) // 2], ents[-1]):
            assert e in at(e.known_at), e.id
            assert e not in at(e.known_at - 1), e.id
    # the time-of-day class and the remaining time are on every CANDLE: a late one, out of warm-up
    c = [e for e in full.of("CANDLE") if e.get("tod_vol") != "WARMUP"][-1]
    assert c.get("tod_vol") in ("NORMAL", "UNUSUAL") and c in at(c.known_at)


def test_intervals_end_by_their_known_at(long):
    _, full = long
    types = {e.type for e in full.entities} & set(TIME_TYPES)
    assert len(types) == len(TIME_TYPES), set(TIME_TYPES) - types
    for e in full.entities:
        if e.type != "WINDOW":
            assert e.time.end <= e.known_at, e.id
            assert e.time.end_ts <= e.time.known_at_ts, e.id
