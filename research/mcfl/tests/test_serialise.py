from __future__ import annotations

import fixtures as F
from mcfl import synth
from mcfl.parse import parse
from mcfl.serialise import dumps, episode, loads, sentence, to_text, tokens


def test_json_round_trip_is_exact():
    ch = parse(synth.garch(1500, seed=2))
    s = dumps(ch)
    back = loads(s)
    assert back == ch
    assert dumps(back) == s
    assert ch.relations and ch.failures and ch.transitions and any(e.force for e in ch.entities)


def test_sentence_order_and_bins():
    ch = parse(F.bars(F.ZONE_UP + [103.5, 102.5, 101.5, 100.5, 99.5, 100.5]))
    toks = tokens(ch)
    assert toks[:2] == ["EXTREME↑", "DISPLACE↓"]
    i = toks.index("ZONE↑")
    assert toks[i - 2:i + 1] == ["VOID↑", "BREAK↑", "ZONE↑"]  # observation before interpretation
    assert toks[-2:] == ["REVISIT↑", "REJECT↑"]
    z = f"ZONE.U.{F.ORIGIN_BAR}"
    assert episode(ch, z) == ["ORIGIN↑", "DISPLACE↑", "VOID↑", "VOID↑", "BREAK↑", "REVISIT↑", "REJECT↑"]
    binned = tokens(ch, bins=True)
    assert "BREAK↑[force:strong]" in binned  # magnitude 4.5 ATR
    assert "REVISIT↑[n:1]" in binned
    ks = [e.known_at for e in sentence(ch)]
    assert ks == sorted(ks)
    assert to_text(ch).split() == toks
    assert "BREAK.U.32.o28" in to_text(ch, verbose=True)
