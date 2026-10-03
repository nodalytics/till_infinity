"""v2 item 6: liquidity pools (EQUAL_HIGHS / EQUAL_LOWS), POOL_TAKEN with or without a close back
(BREACH_REVERT), the DAX course's SWEEP_PROTECTED - checked against `dax_smc.py` itself - and the
DAX checklist's first three steps as one production."""
from __future__ import annotations

import sys
from pathlib import Path

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import synth
from mcfl.core import Dir
from mcfl.parse import flip, parse
from mcfl.pools import POOL_EQ_ATR, SWEEP_BACK

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ideas"))
import dax_smc as D  # noqa: E402
import prims as P  # noqa: E402


def _spike(closes, bar):
    return pd.concat([F.bars(closes), pd.DataFrame([bar])], ignore_index=True)


def test_equal_highs_pool_and_its_take():
    ch = parse(F.bars(F.EQUAL_HIGHS))
    hi = ch.by_id()["POOL.U.32"]
    assert (hi.known_at, hi.get("kind"), hi.get("count"), hi.get("level")) == (35, "EQUAL_HIGHS", 2, 103.25)
    assert hi.parts == ("EXTREME.U.24", "EXTREME.U.32")
    lo = ch.by_id()["POOL.D.36"]
    assert (lo.get("kind"), lo.get("level")) == ("EQUAL_LOWS", 100.75)
    (t,) = ch.of("POOL_TAKEN")
    assert (t.id, t.known_at, t.get("closed_back"), t.get("breach_revert")) == ("POOL_TAKEN.U.41.p32", 41, False, 0)
    assert ("CROSS", "POOL_TAKEN.U.41.p32", "POOL.U.32") in {(r.kind, r.src, r.dst) for r in ch.relations}


def test_a_take_that_closes_back_is_a_sweep_and_links_breach_revert():
    closes = F.WARMUP + F.zig([100.5, 103, 101, 103, 101])
    ch = parse(_spike(closes, dict(open=101.0, high=103.5, low=100.9, close=102.8, volume=1.0)))
    (t,) = ch.of("POOL_TAKEN")
    assert t.get("closed_back") and t.get("breach_revert") == 2
    assert t.parts == ("POOL.U.32", "BREACH_REVERT.U.37.x24", "BREACH_REVERT.U.37.x32")
    assert t.get("depth_atr") > 0
    rels = {(r.kind, r.src, r.dst) for r in ch.relations}
    assert ("TOUCH", t.id, "POOL.U.32") in rels and ("LINK", t.id, "BREACH_REVERT.U.37.x24") in rels


def test_no_pool_when_unequal_or_traded_through_between():
    ch = parse(F.bars(F.WARMUP + F.zig([100.5, 103, 101, 103.5, 101])))  # 0.5 apart: > 0.1 ATR
    assert not [p for p in ch.of("POOL") if p.dir is Dir.UP]
    # equal highs, but a bar between them traded above both
    closes = F.WARMUP + F.zig([100.5, 103, 101]) + [101.5, 102, 104.5, 102.5, 102] + F.zig([102, 101, 103, 101])
    ch = parse(F.bars(closes))
    ups = [p for p in ch.of("POOL") if p.dir is Dir.UP]
    assert all("EXTREME.U.24" not in p.parts for p in ups)


def test_pool_flips():
    ch = parse(flip(F.bars(F.EQUAL_HIGHS)))
    p = ch.by_id()["POOL.D.32"]
    assert p.get("kind") == "EQUAL_LOWS" and p.get("level") == -103.25
    assert ch.of("POOL_TAKEN")[0].id == "POOL_TAKEN.D.41.p32"


SWEEP = F.WARMUP + F.zig([100.5, 98, 101, 98.5])
SWEEP_BAR = dict(open=98.5, high=98.6, low=97.5, close=98.25, volume=1.0)  # under 97.75, closes back above


def _sweep(bar):
    return pd.concat([F.bars(SWEEP), pd.DataFrame([bar]), F.bars([98.75, 99.25, 99.75, 100.25], first_open=98.25)],
                     ignore_index=True)


def test_sweep_protected_passes():
    ch = parse(_sweep(SWEEP_BAR))
    (s,) = ch.of("SWEEP_PROTECTED")
    assert (s.id, s.known_at, s.get("swept"), s.get("swept_level"), s.get("level")) == (
        "SWEEP_PROTECTED.U.36", 39, "EXTREME.D.24", 97.75, 97.5)
    assert s.parts == ("EXTREME.D.24", "EXTREME.D.36") and s.get("origin") == "ORIGIN.U.36"


def test_sweep_protected_fails_without_the_close_back():
    """The same sweep closing under 97.75, and the next bar too: not protected (one of the two
    closes back is enough - the next bar closing at 97.8 makes it protected again)."""
    def df(c2):
        return pd.concat([F.bars(SWEEP), pd.DataFrame([{**SWEEP_BAR, "close": 97.6},
                                                       dict(open=97.6, high=97.85, low=97.55, close=c2, volume=1.0)]),
                          F.bars([98.75, 99.25, 99.75], first_open=c2)], ignore_index=True)
    assert not parse(df(97.7)).of("SWEEP_PROTECTED")
    assert parse(df(97.8)).of("SWEEP_PROTECTED")[0].id == "SWEEP_PROTECTED.U.36"


def test_sweep_flips():
    ch = parse(flip(_sweep(SWEEP_BAR)))
    (s,) = ch.of("SWEEP_PROTECTED")
    assert s.id == "SWEEP_PROTECTED.D.36" and s.get("level") == -97.5


def _dax_step1(df: pd.DataFrame) -> set[int]:
    """`dax_smc.long_setups` step 1, verbatim: the protected lows of the chart."""
    a = P.atr(df, 14)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    ph, pl = P.pivots(h, l, D.L, D.L)
    out = set()
    for known_s, s, low_s in pl:
        if not a[s] > 0:
            continue
        prior = [x for x in pl if s - D.SWEEP_BACK <= x[1] < s and x[0] <= s]
        if not prior:
            continue
        _, q, q_px = prior[-1]
        if not (low_s < q_px and l[q + 1:s].min(initial=np.inf) >= q_px and c[s:s + 2].max() > q_px):
            continue
        out.add(s)
    return out


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_sweep_protected_is_dax_smc_step_one(seed):
    assert SWEEP_BACK == D.SWEEP_BACK
    for gen in (synth.walk, synth.garch):
        df = gen(3000, seed=seed)
        ch = parse(df)
        ours = {(e.at, e.dir) for e in ch.of("SWEEP_PROTECTED")}
        want = {(s, Dir.UP) for s in _dax_step1(df)} | {(s, Dir.DOWN) for s in _dax_step1(D.Z.flip(df))}
        assert ours == want and len(want) > 40
        # and every protected low of the course's full setups is one of ours
        st = D.setups(df, P.atr(df, 14))
        prot = {(int(r.protected), Dir.UP if r.side > 0 else Dir.DOWN) for r in st.itertuples()}
        assert prot and prot <= ours


@pytest.mark.parametrize("seed", [0, 1])
def test_pools_on_walks(seed):
    df = synth.walk(3000, seed=seed)
    ch = parse(df)
    ids = ch.by_id()
    a = P.atr(df, 14)
    assert ch.of("POOL") and ch.of("POOL_TAKEN")
    for p in ch.of("POOL"):
        px = [ids[m].get("price") for m in p.parts]
        last = ids[p.parts[-1]]
        assert p.at == last.at and p.known_at == last.known_at and p.get("count") == len(px) >= 2
        assert all(abs(x - px[-1]) <= POOL_EQ_ATR * a[last.at] for x in px)
        assert p.get("level") == (max(px) if p.dir is Dir.UP else min(px))
    for t in ch.of("POOL_TAKEN"):
        p = ids[t.get("pool")]
        x = df["high"].to_numpy() if p.dir is Dir.UP else -df["low"].to_numpy()
        lvl = p.get("level") * (1 if p.dir is Dir.UP else -1)
        assert t.at == p.at + 1 + int(np.flatnonzero(x[p.at + 1:] > lvl)[0])
        assert bool(t.get("breach_revert")) <= t.get("closed_back") and t.get("breach_revert") == len(t.parts) - 1
    for s in ch.of("DAX_SETUP"):
        sw, b, pb = (ids[x] for x in s.parts)
        assert b.get("origin") == sw.get("origin") and pb.get("break") == b.id and pb.get("depth") >= 0.5
