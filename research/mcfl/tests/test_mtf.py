"""v2 item 10: multiple timeframes - the aggregator, CONTAINS_TF, ALIGN / CONFLICT, the desk's nested
zone as one production (NESTED) in its causal form, its exact reproduction of `zone_nested.py`'s
"inside_4h" in the research's non-causal form, the two forms disagreeing, and multi-timeframe CRT."""
from __future__ import annotations

import sys
from pathlib import Path

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.core import Dir
from mcfl.mtf import groups, nested_flags, parse_mtf
from mcfl.parse import flip, parse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ideas"))
import zone_nested as ZN  # noqa: E402

T0 = 1_700_006_400 - 1_700_006_400 % 86400  # a UTC midnight, so 4h periods align
H4 = 14400


def _walk(gen, seed, htf_bars=300):
    return F.with_time(gen(16 * htf_bars, seed=seed), 900, T0)


def test_aggregation_from_ltf_tokens():
    df = _walk(synth.garch, 1, 40)
    m = parse_mtf(df, htf_sec=H4, label="4h")
    assert m.htf.n == 40 and m.first[3] == 48 and m.last[3] == 63 and m.known[3] == 63
    h = m.htf_df
    seg = df.iloc[48:64]
    assert (h.loc[3, "open"], h.loc[3, "high"], h.loc[3, "low"], h.loc[3, "close"]) == (
        seg["open"].iloc[0], seg["high"].max(), seg["low"].min(), seg["close"].iloc[-1])
    assert h.loc[3, "ts"] == T0 + 3 * H4
    # the HTF CANDLE word is the HTF chart's own; CONTAINS_TF links it to the 16 LTF candles it was built from
    hc = [e for e in m.htf.of("CANDLE") if e.at == 3][0]
    kids = [r.dst for r in m.relations if r.kind == "CONTAINS_TF" and r.src == f"4h:{hc.id}"]
    assert sorted(kids) == sorted(e.id for e in sorted(m.ltf.of("CANDLE"), key=lambda e: e.at)[48:64])
    assert {r.known_at for r in m.relations if r.src == f"4h:{hc.id}"} == {63}


def test_incomplete_and_gapped_periods():
    df = _walk(synth.walk, 2, 10).iloc[:16 * 9 + 5]  # nine full 4h bars and five bars of the tenth
    assert len(groups(df, H4, None)) == 9
    gap = df.drop(index=[30, 31]).reset_index(drop=True)  # period 1 loses its last two bars
    g = groups(gap, H4, None)
    assert g[1][:3] == (16, 29, 30)  # known at the next period's first bar: the clock passed
    by_count = groups(df.drop(columns="ts"), None, 16)
    assert len(by_count) == 9 and by_count[0][:3] == (0, 15, 15)


def test_contains_on_demand_and_spans():
    m = parse_mtf(_walk(synth.walk, 3, 120), htf_sec=H4, label="4h")
    b = m.htf.of("BREAK")[0]
    a, z = m.span(b)
    p = int(b.get("origin").split(".")[2])
    assert (a, z) == (16 * p, 16 * b.at + 15)
    inside = [e for e in m.ltf.of("CANDLE") if a <= e.at <= z]
    assert all(m.contains(b, e) is not None for e in inside)
    assert m.contains(b, m.ltf.of("CANDLE")[z + 1]) is None


def test_align_conflict_are_causal():
    m = parse_mtf(_walk(synth.garch, 4, 200), htf_sec=H4, label="4h")
    ids = m.by_id()
    rel = [r for r in m.relations if r.kind in ("ALIGN", "CONFLICT")]
    assert {"ALIGN", "CONFLICT"} <= {r.kind for r in rel}
    for r in rel:
        lt, h = ids[r.src], ids[r.dst]
        assert m.known_ltf(h) <= lt.known_at == r.known_at
        if h.type == "BREAK":
            assert (r.kind == "ALIGN") == (h.dir is lt.dir)
        else:
            assert (r.kind == "ALIGN") == (h.get("to") == lt.dir.value)


def _research_inside(df: pd.DataFrame, dh: pd.DataFrame) -> dict[tuple[int, str], bool]:
    """zone_nested.py's "inside_4h", line for line: HTF breaks from zone_events, LTF zones that are
    qualified first returns filled at the near edge (body bound), and the leg test on timestamps."""
    d, _ = ZN.evs(dh, "4h", 0.0)
    hh = d.drop_duplicates(["p", "side"])[["p", "side", "V", "ts", "bos_ts", "bos_level", "atr_p"]].copy()
    dl, _ = ZN.evs(df, "15m", 0.0)
    f = dl[dl["filled"] & (dl["depth"] == "d0") & (dl["bound"] == "body") & (dl["ret"] == 1) & dl["V"]].copy()
    out = {}
    for r in f.itertuples():
        t0 = r.ts
        legs = hh[(hh["ts"] <= t0) & (t0 <= hh["bos_ts"] + ZN.SEC["4h"] - 1)]
        same = legs[legs["side"] == r.side]
        out[int(r.p), "UP" if r.side > 0 else "DOWN"] = len(same) > 0
    return out


@pytest.mark.parametrize(("gen", "seed"), [(synth.walk, 1), (synth.walk, 2), (synth.garch, 1), (synth.garch, 2)])
def test_research_form_reproduces_inside_4h_exactly(gen, seed):
    df = _walk(gen, seed)
    m = parse_mtf(df, htf_sec=H4, label="4h")
    ref = _research_inside(df, m.htf_df)
    ours = {(z.at, z.dir.value): v for z, v in ((m.by_id()[k], v) for k, v in nested_flags(m, "research").items())}
    assert len(ref) > 150 and sum(ref.values()) > 20
    assert {k: ours[k] for k in ref} == ref


def test_causal_and_research_forms_disagree():
    """The research flag counts HTF breaks the LTF zone could not have known. On these walks most
    flagged zones are flagged only that way."""
    n_research = n_causal = only_research = 0
    for seed in (1, 2):
        m = parse_mtf(_walk(synth.walk, seed), htf_sec=H4, label="4h")
        c, r = nested_flags(m, "causal"), nested_flags(m, "research")
        n_causal += sum(c.values())
        n_research += sum(r.values())
        only_research += sum(r[k] and not c[k] for k in c)
        ids = m.by_id()
        for e in m.entities:
            if e.type == "NESTED":
                z, h = ids[e.parts[0]], ids[e.parts[1]]
                assert m.known_ltf(h) <= z.known_at == e.known_at and c[z.id]
    assert only_research > 50 and n_causal < n_research / 5


def test_mtf_crt():
    rows = [(100.5, 100.8, 99.6, 100.0), (100.0, 101.0, 99.5, 100.6), (100.6, 100.9, 99.0, 99.4),
            (99.4, 100.2, 99.2, 100.1),                                   # HTF bar 5: 99 .. 101
            (100.1, 101.3, 100.0, 100.5),                                 # beyond 101, back inside: the purge
            (100.5, 100.6, 99.6, 99.8), (99.8, 99.9, 98.9, 99.1)]         # the mid, then under 99
    df = F.after(F.FINE, rows).drop(columns="volume")
    m = parse_mtf(df, factor=4, label="x")
    got = {e.id: e for e in m.entities}
    p = got["PURGE.U.24.x5"]
    assert p.parts == ("x:CANDLE.D.5", "CANDLE.U.24") and (p.get("upper_edge"), p.get("lower_edge")) == (101.0, 99.0)
    d = got["DISTRIBUTION.D.26.p24x"]
    assert (d.get("bars"), d.get("mid_bars"), d.known_at) == (2, 1, 26)
    assert got["CRT3.D.24.x5"].parts == ("x:CANDLE.D.5", p.id, d.id)
    flipped = parse_mtf(flip(df), factor=4, label="x")
    assert {"PURGE.D.24.x5", "DISTRIBUTION.U.26.p24x", "CRT3.U.24.x5"} <= {e.id for e in flipped.entities}


def _mirror_id(x):
    from test_symmetry import _sid
    if ":" in x:
        tf, rest = x.split(":", 1)
        return f"{tf}:{_sid(rest)}"
    return _sid(x)


def test_mtf_flip():
    df = _walk(synth.garch, 5, 150)
    a, b = parse_mtf(df, htf_sec=H4, label="4h"), parse_mtf(flip(df), htf_sec=H4, label="4h")
    ra = {(r.kind, _mirror_id(r.src), _mirror_id(r.dst), r.known_at) for r in a.relations}
    rb = {(r.kind, r.src, r.dst, r.known_at) for r in b.relations}
    assert ra == rb
    ea = {(e.type, _mirror_id(e.id), e.dir.flip(), e.at, e.known_at, tuple(_mirror_id(p) for p in e.parts)) for e in a.entities}
    eb = {(e.type, e.id, e.dir, e.at, e.known_at, e.parts) for e in b.entities}
    assert ea == eb and ea


def test_mtf_is_causal():
    df = _walk(synth.garch, 6, 48)
    full = parse_mtf(df, htf_sec=H4, label="4h")
    marks = sorted({x.known_at for x in full.entities} | {x.known_at - 1 for x in full.entities}
                   | {r.known_at for r in full.relations if r.kind != "CONTAINS_TF"} | set(range(100, len(df), 23)))
    assert full.entities and any(r.kind == "ALIGN" for r in full.relations)
    for T in marks:
        cut = parse_mtf(df.iloc[:T + 1], htf_sec=H4, label="4h")
        assert set(cut.entities) == {e for e in full.entities if e.known_at <= T}, T
        assert set(cut.relations) == {r for r in full.relations if r.known_at <= T}, T


def test_a_given_htf_chart():
    """parse_mtf can take the higher timeframe's own bars (here the same aggregation, built apart)."""
    df = _walk(synth.walk, 7, 60)
    own = parse_mtf(df, htf_sec=H4, label="4h")
    given = parse_mtf(df, htf_sec=H4, label="4h", htf=own.htf_df.copy())
    assert given.htf == own.htf and set(given.relations) == set(own.relations)
