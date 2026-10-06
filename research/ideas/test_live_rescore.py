"""The two live-close formats (the closes export and the journal database) read the same closes, and
the rescore's SPRT trace is the frozen rule of `switch.states`.

Real-data checks run when the desk's files are present: TI_DATA=<checkout>/.data pytest ..."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import live_rescore as LR  # noqa: E402
import switch as S  # noqa: E402

DATA = Path(os.environ.get("TI_DATA", HERE.parents[1] / ".data"))


def _closes(n=60, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        strat = ("fade-to-value", "snap", "")[i % 3]
        ctx = {"profit": round(float(rng.normal(-1, 20)), 2), "feed": "gold", "interval": "1m", "seconds": 60}
        if strat:
            ctx["strategy"] = strat
        if i % 2:
            ctx["r_multiple"] = round(float(rng.normal(-0.1, 1)), 4)
        else:
            ctx["risk_money"] = 25.0
        out.append(dict(t=1.7877e9 + 600.0 * i + 0.123456, title=f"XAUUSD closed {ctx['profit']:+.2f} #{i}",
                        ctx=ctx, tags=[], src="unattributed" if i % 5 == 0 else "outcome"))
    return out


def _journal(path, closes, extra=True):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE entries (id TEXT PRIMARY KEY, time REAL NOT NULL, kind TEXT NOT NULL, "
                "actor TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, rationale TEXT NOT NULL DEFAULT '', "
                "context TEXT NOT NULL DEFAULT '{}', tags TEXT NOT NULL DEFAULT '[]', confidence REAL, "
                "parent TEXT NOT NULL DEFAULT '', written REAL NOT NULL)")
    for i, c in enumerate(closes):
        kind = "outcome" if c["src"] == "outcome" else "observation"
        con.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f"c{i}", c["t"], kind, "trading", c["title"], "", json.dumps(c["ctx"]), "[]", None, "", c["t"]))
    if extra:  # rows that are not closes: structures outcomes, trading entries without profit
        con.execute("INSERT INTO entries VALUES ('s1', 1.7877e9, 'outcome', 'structures', 'gold: reject', '', "
                    "'{\"outcome\": \"reject\"}', '[]', NULL, '', 1.7877e9)")
        con.execute("INSERT INTO entries VALUES ('o1', 1.7877e9, 'observation', 'trading', 'entered', '', "
                    "'{\"strategy\": \"snap\"}', '[]', NULL, '', 1.7877e9)")
    con.commit()
    con.close()


def test_journal_and_export_read_the_same_closes(tmp_path):
    closes = _closes()
    (tmp_path / "closes.json").write_text(json.dumps(closes))
    _journal(tmp_path / "journal.db", closes)
    a = S.read_closes(tmp_path / "closes.json")
    b = S.read_closes(tmp_path / "journal.db")
    assert len(b) == len(a)
    for x, y in zip(sorted(a, key=lambda r: r["t"]), b):
        assert abs(x["t"] - y["t"]) < 1e-6 and x["title"] == y["title"] and x["ctx"] == y["ctx"]
        assert x["src"] == y["src"]
    la, lb = S.live_streams(str(tmp_path / "closes.json")), S.live_streams(str(tmp_path / "journal.db"))
    pd.testing.assert_frame_equal(la.reset_index(drop=True), lb.reset_index(drop=True))


def test_merged_sources_count_each_close_once(tmp_path):
    closes = _closes()
    (tmp_path / "closes.json").write_text(json.dumps(closes[:40]))
    _journal(tmp_path / "journal.db", closes[25:])  # overlaps closes 25-39, then newer ones
    m = S.read_all_closes(f"{tmp_path / 'closes.json'},{tmp_path / 'journal.db'}")
    assert len(m) == len(closes)
    assert [r["title"] for r in m] == [r["title"] for r in closes]
    lm = S.live_streams(f"{tmp_path / 'closes.json'},{tmp_path / 'journal.db'}")
    (tmp_path / "all.json").write_text(json.dumps(closes))
    pd.testing.assert_frame_equal(lm.reset_index(drop=True), S.live_streams(str(tmp_path / "all.json")).reset_index(drop=True))


def test_sprt_trace_is_the_frozen_rule():
    rng = np.random.default_rng(3)
    for mu in (-0.5, -0.15, 0.0, 0.05, 0.2, 0.6):
        for n in (5, 30, 300):
            x = rng.normal(mu, 1.0, n)
            tr = LR.sprt_trace(x)
            assert (tr["on"] == S.states(x)["SPRT"][1:]).all()
    # hand check: 20 closes of -1R with sd 1 until the burn-in: each adds 0.1 * (-1.05) = -0.105, so the
    # LLR first reaches ln(0.2/0.95) = -1.558 at close 15 (-1.575)
    tr = LR.sprt_trace(np.full(20, -1.0))
    assert list(tr["event"]).index("kill") == 14
    assert abs(tr["llr_pre"][14] - 15 * -0.105) < 1e-12
    assert abs(LR.B - math.log(0.2 / 0.95)) < 1e-12 and abs(LR.A - math.log(0.8 / 0.05)) < 1e-12
    assert LR.verdict(tr["event"], tr["on"][-1]) == "kill"
    up = LR.sprt_trace(np.full(40, 1.0))
    assert LR.verdict(up["event"], up["on"][-1]) == "keep"
    assert LR.verdict(LR.sprt_trace(np.zeros(3))["event"], True) == "undecided"


def test_zero_edge_envelope_matches_the_switching_table():
    rng = np.random.default_rng(5)
    for n, ((m0, m1), _) in LR.DOC_HOT10.items():
        if n > 300:
            continue
        med = float(np.median(LR.zero_edge_best10(n, rng, paths=3000)))
        assert m0 - 0.06 <= med <= m1 + 0.06, (n, med)


def _real(name):
    p = DATA / name
    if not p.exists():
        pytest.skip(f"{p} not present")
    return p


def test_real_export_equals_its_journal():
    """`.data/closes.json` is the export of `.data/tmp/journal.db`: the same 688 closes."""
    js, db = _real("closes.json"), _real("tmp/journal.db")
    a = sorted(S.read_closes(js), key=lambda r: r["t"])
    b = S.read_closes(db)
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert abs(x["t"] - y["t"]) < 1e-3 and x["title"] == y["title"] and x["ctx"] == y["ctx"]
    pd.testing.assert_frame_equal(S.live_streams(str(js)).reset_index(drop=True),
                                  S.live_streams(str(db)).reset_index(drop=True))


def test_real_journals_agree_with_the_export_where_they_overlap():
    js = _real("closes.json")
    a = {(round(r["t"], 3), r["title"]): r["ctx"] for r in S.read_closes(js)}
    lo, hi = min(k[0] for k in a), max(k[0] for k in a)
    for name in ("journal/fresh.db", "journal/journal.db"):
        p = DATA / name
        if not p.exists():
            continue
        b = [r for r in S.read_closes(p) if lo <= r["t"] <= hi]
        for r in b:
            assert a[(round(r["t"], 3), r["title"])] == r["ctx"]
        # and the export holds every close the journal has inside the window
        assert len({(round(r["t"], 3), r["title"]) for r in b} - set(a)) == 0
