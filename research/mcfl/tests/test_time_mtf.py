"""HTF_CLOSE as the shared clock of every multi-timeframe relation (time core item 4, retrofitted onto
v2's `mtf`): an HTF fact may be read only at or after the LTF bar of the HTF_CLOSE that makes it
knowable. The check here reads the closes off the LTF chart, independently of `MTF.known`, and a
multi-timeframe chart whose closes are moved one bar early is shown to fail it."""
from __future__ import annotations

import dataclasses

import fixtures as F
from mcfl import synth
from mcfl.mtf import align, crt, nested, parse_mtf

H4 = 14400


def _mtf(seed: int = 121, htf_bars: int = 200):
    df = F.with_calendar(synth.garch(16 * htf_bars, seed=seed), 900, F.WINTER_MONDAY, "fx")
    return df, parse_mtf(df, htf_sec=H4, label="4h")


def early_reads(m, rels, ents) -> list[str]:
    """Every output that read an HTF entity before that entity's HTF bar had closed on the LTF chart."""
    closes = {e.get("period_ts"): e.known_at for e in m.ltf.of("HTF_CLOSE") if e.get("tf") == "4h"}
    hts = m.htf_df["ts"].to_numpy()
    hid = {f"4h:{e.id}": e for e in m.htf.entities}

    def close_of(h) -> int:
        return closes[int(hts[h.known_at])]

    bad = []
    for r in rels:
        if r.dst in hid and close_of(hid[r.dst]) > r.known_at:
            bad.append(f"{r.kind} {r.src} -> {r.dst}")
    for e in ents:
        for p in e.parts:
            if p in hid and close_of(hid[p]) > e.known_at:
                bad.append(f"{e.id} <- {p}")
    return bad


def test_known_is_the_htf_close():
    df, m = _mtf()
    closes = sorted((e for e in m.ltf.of("HTF_CLOSE") if e.get("tf") == "4h"), key=lambda e: e.at)
    assert [e.known_at for e in closes] == list(m.known)
    assert [e.at for e in closes] == list(m.last) and [e.time.start for e in closes] == list(m.first)
    for j in (0, 5, len(m.known) - 1):
        h = m.htf_df.iloc[j]
        c = closes[j]
        assert (c.get("open"), c.get("high"), c.get("low"), c.get("close")) == (h["open"], h["high"], h["low"], h["close"])


def test_no_htf_fact_is_read_before_its_close():
    _, m = _mtf()
    rels = [r for r in m.relations if r.kind in ("ALIGN", "CONFLICT", "CONTAINS_TF")]
    assert rels and any(e.type == "PURGE" for e in m.entities)
    assert early_reads(m, rels, m.entities) == []


def test_reading_early_is_caught():
    """The same relations computed from an MTF whose HTF closes are moved an hour (four LTF bars) early:
    the check above, which knows only the LTF chart's HTF_CLOSE events, finds the early reads."""
    _, m = _mtf()
    leaky = dataclasses.replace(m, known=tuple(max(0, k - 4) for k in m.known))
    bad = early_reads(m, align(leaky), nested(leaky) + crt(leaky))
    assert len(bad) > 5
    h = m.htf.of("BREAK")[0]
    assert m.visible(h, m.known_ltf(h)) and not m.visible(h, m.known_ltf(h) - 1)


def test_counted_periods_have_their_own_closes():
    df = synth.garch(16 * 40, seed=122)
    m = parse_mtf(df, factor=16, label="x")
    closes = sorted((e for e in m.entities if e.type == "HTF_CLOSE"), key=lambda e: e.at)
    assert len(closes) == 40 and [e.known_at for e in closes] == list(m.known) == [16 * j + 15 for j in range(40)]
    assert closes[3].get("high") == df["high"].iloc[48:64].max() and closes[3].parts[0] == m.ltf.of("CANDLE")[48].id
