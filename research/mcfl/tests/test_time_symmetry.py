"""The time core under the flip: parsing the flipped chart gives every entity mirrored, and every time
attribute - spans, known_at_ts, hour rates, calendar words, windows, anchors - unchanged."""
from __future__ import annotations

import fixtures as F
import pytest
from mcfl import synth
from mcfl.core import TIME_TYPES
from mcfl.parse import flip, parse
from test_symmetry import _fix_rule, _sid, mirror

TIME_WORDS = ("hour", "minute", "wom", "month", "quarter", "month_end", "holiday", "session", "killzone", "macro",
              "left_session", "left_4h", "prog_4h", "tod_vol", "tod_ratio")


@pytest.mark.parametrize(("kind", "market", "seed"), [("garch", "fx", 111), ("trend", "index", 112)])
def test_flip_keeps_time(kind, market, seed):
    gen = {"garch": synth.garch, "trend": synth.trend}[kind]
    df = F.with_calendar(synth.ticks(gen(2200, seed=seed), seed=seed + 1), 900, F.WINTER_MONDAY + 20 * 86400, market)
    a, b = parse(df), parse(flip(df))
    m = mirror(a)  # carries each entity's time unchanged
    got, want = {_fix_rule(e) for e in m.entities}, set(b.entities)
    assert got == want, (sorted(map(str, got - want))[:2], sorted(map(str, want - got))[:2])
    assert set(m.relations) == set(b.relations)
    by = {e.id: e for e in b.entities}
    for e in a.entities:
        assert by[_sid(e.id)].time == e.time
    ca, cb = {e.at: e for e in a.of("CANDLE")}, {e.at: e for e in b.of("CANDLE")}
    for t in range(0, len(df), 17):
        assert all(ca[t].get(k) == cb[t].get(k) for k in TIME_WORDS)
    have = {e.type for e in a.entities} & set(TIME_TYPES)
    assert len(have) >= len(TIME_TYPES) - 1, set(TIME_TYPES) - have
