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
    assert toks[-2:] == ["REVISIT↑", "REJECT_PATH↑"]
    z = f"ZONE.U.{F.ORIGIN_BAR}"
    assert episode(ch, z)[:7] == ["ORIGIN↑", "DISPLACE↑", "VOID↑", "VOID↑", "BREAK↑", "REVISIT↑", "REJECT_PATH↑"]
    binned = tokens(ch, bins=True)
    assert "BREAK↑[force:strong,age:mid,took:1]" in binned  # magnitude 4.5 ATR, level 10 bars old
    assert "REVISIT↑[n:1]" in binned
    ks = [e.known_at for e in sentence(ch)]
    assert ks == sorted(ks)
    assert to_text(ch).split() == toks
    assert "BREAK.U.32.o28" in to_text(ch, verbose=True)


def test_bar_sentence_and_interleaved_view():
    from mcfl.serialise import bar_words, interleaved, interleaved_text
    ch = parse(F.bars(F.ZONE_UP))
    ws = bar_words(ch)
    assert len(ws) == ch.n
    assert ws[0].startswith("NONE(W){b:-,u:-,l:-,q2}") and "/" not in ws[0]  # warm-up, no previous bar
    assert all("/" in w for w in ws[1:])
    import re
    word = re.compile(r"^(BULL|BEAR|NONE)\((W|(N|VS|S|M|L|VL|XL),(N|S|M|L|T),(N|S|M|L),(N|S|M|L))\)"
                      r"\{b:[-WMSD],u:[-NWMSD],l:[-NWMSD],q[1-4]\}(/(IN|OUT|HH|LL)(\+E)?)?(\|[a-z=<>,]+)?$")
    assert all(word.match(w) for w in ws), [w for w in ws if not word.match(w)]
    seq = interleaved(ch)
    i = seq.index("ZONE↑")
    assert seq[i - 3:i] == [ws[F.ORIGIN_BAR + 4], "VOID↑", "BREAK↑"]  # after the word of the break bar
    assert [x for x in seq if "(" in x] == ws  # the bar words in order, events between them
    assert interleaved_text(ch).splitlines()[F.ORIGIN_BAR + 4].split()[2:] == ["VOID↑", "BREAK↑", "ZONE↑"]


def test_derivation_reaches_the_candle_words():
    from mcfl.serialise import derivation
    ch = parse(F.bars(F.ZONE_UP))
    tree = derivation(ch, f"ZONE.U.{F.ORIGIN_BAR}").splitlines()
    assert tree[0].startswith("ZONE↑")
    heads = [ln.strip().split()[0] for ln in tree if ln.startswith("  ") and not ln.startswith("    ")]
    assert heads == ["ORIGIN↑", "DISPLACE↑", "VOID↑", "VOID↑", "BREAK↑"]
    assert tree[2].strip().startswith("EXTREME↓")  # ORIGIN -> EXTREME -> the seven candles it was read from
    leaves = [ln for ln in tree if "[CANDLE." in ln]
    assert len([ln for ln in tree[3:10] if "[CANDLE." in ln]) == 7
    assert all(ln.strip().split()[0][:4] in ("BULL", "BEAR", "NONE") for ln in leaves)


def test_json_round_trip_keeps_the_tokens():
    ch = parse(synth.garch(600, seed=4))
    back = loads(dumps(ch))
    assert back == ch
    c = [e for e in back.entities if e.type == "CANDLE"][300]
    r = [e for e in back.entities if e.type == "BAR_RELATION"][300]
    assert isinstance(c.get("within"), tuple) and isinstance(r.get("named"), tuple)
    assert len(r.get("points")) == 16 and len(c.get("inner")) == 16
    assert {e.type for e in back.entities} >= {"CANDLE", "BAR_RELATION", "PIN", "ENGULF", "DELIVERY_SHIFT"}
