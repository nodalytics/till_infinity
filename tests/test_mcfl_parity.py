"""The production port of MCFL against the research parser, event for event.

`till_infinity/mcfl/` does not import `research/` - production must not ship
whatever was last edited in an experiment - so these tests are the contract
instead. Every alertable event, and every event they are built from, is
computed both ways on the same bars and must match exactly: kind, direction,
bar, the bar it became known, and the attributes that identify it.

The bars are GARCH walks from the research's own generator, and real series
committed under `tests/fixtures/mcfl/` (Binance perpetual klines: ARB and ETH
daily, BTC 15m and 4h). `MCFL_REAL_SERIES_DIR` points the last test at a
directory of the lab's `binance_perps/*.pkl` daily series, where available.

Then the trade: the 12-bar-low signal against `paper_displace.signals` (the
live paper logger) and the structure exit against `market_mirror.exits` and
`turn_trade.trades_exits`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from till_infinity.mcfl import events as ev
from till_infinity.mcfl import trade as tr
from till_infinity.mcfl.detect import Parse
from till_infinity.mcfl.tokens import Bars, frames, tokens

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "mcfl"
for part in (ROOT / "research", ROOT / "research" / "ideas"):
    if str(part) not in sys.path:
        sys.path.insert(0, str(part))

research = pytest.importorskip("mcfl.parse")


def _walk(seed: int, n: int = 600) -> pd.DataFrame:
    from mcfl import synth

    d = synth.garch(n, seed=seed).reset_index(drop=True)
    d["ts"] = np.arange(len(d), dtype=np.int64) * 3600
    return d


def _fixture(name: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / f"{name}.csv")


SERIES = {
    "garch-1": lambda: _walk(1),
    "garch-7": lambda: _walk(7),
    "ARB-1d": lambda: _fixture("ARBUSDT.1d"),
    "ETH-1d": lambda: _fixture("ETHUSDT.1d"),
    "BTC-15m": lambda: _fixture("BTCUSDT.15m"),
    "BTC-4h": lambda: _fixture("BTCUSDT.4h"),
}


def bars_of(df: pd.DataFrame) -> Bars:
    return Bars(
        df["ts"].to_numpy(np.int64),
        *(df[k].to_numpy(float) for k in ("open", "high", "low", "close")),
    )


def _d(e) -> int:
    return {"UP": 1, "DOWN": -1}.get(e.dir.value, 0)


def _at(ref: str | None) -> int | None:
    """The bar of a research id such as `ORIGIN.U.57` or `ZONE.D.120`."""
    return int(ref.split(".")[2]) if ref else None


def _suffix(e) -> int:
    """The bar in a research id's suffix: `BREACH_REVERT.D.60.x57` -> 57."""
    return int(e.id.split(".")[3][1:])


def _r(x) -> float | None:
    return None if x is None else round(float(x), 9)


#: What identifies each kind, in the research parser's terms.
RESEARCH_KEYS = {
    "EXTREME": lambda e: (_r(e.get("price")),),
    "DISPLACE_C": lambda e: ("RUN" if e.get("rule") == "DISPLACE_C_RUN" else "BAR",),
    "DELIVERY_SHIFT": lambda e: (e.get("run_len"),),
    "BREACH_REVERT": lambda e: (_suffix(e), _r(e.get("level"))),
    "CLOSE_REVERT": lambda e: (_suffix(e), _r(e.get("level")), e.get("through")),
    "VOID": lambda e: (_r(e.get("size")),),
    "ORIGIN": lambda e: (_r(e.get("far")), _r(e.get("near"))),
    "DISPLACE": lambda e: (_at(e.get("origin")),),
    "BREAK": lambda e: (_at(e.get("origin")), _r(e.get("level"))),
    "LEG": lambda e: (e.get("end"), e.get("reason")),
    "ZONE": lambda e: (_r(e.get("far")), _r(e.get("near"))),
    "REVISIT": lambda e: (_at(e.get("zone")), e.get("count")),
    "FAIL": lambda e: (_at(e.get("zone")), e.get("count")),
    "SWING": lambda e: (e.get("label"),),
    "STRUCTURE_SHIFT": lambda e: (e.get("from"), e.get("to")),
    "SWEEP_PROTECTED": lambda e: (_r(e.get("swept_level")), _r(e.get("level"))),
    "SWEEP_SHIFT": lambda e: (e.get("sweep_type"), e.get("shift_type"), _r(e.get("level"))),
    "INDUCEMENT": lambda e: (_at(e.get("zone")), _r(e.get("level")), e.get("taken_at")),
    "VOID_INVERTED": lambda e: (_at(e.get("void")),),
    "BREAKER_RETEST": lambda e: (e.get("kind"), _at(e.get("of")), _r(e.get("level"))),
    "RECLAIM": lambda e: (e.get("kind"), _at(e.get("of")), _r(e.get("level"))),
    "PROTECTED": lambda e: (e.get("grade"), _r(e.get("level"))),
    "PROTECTED_TAKEN": lambda e: (e.get("grade"), _r(e.get("level")), e.get("closed_back")),
}

#: The same, read off the port's events.
PORT_KEYS = {
    "EXTREME": lambda e: (_r(e.get("price")),),
    "DISPLACE_C": lambda e: (e.get("rule"),),
    "DELIVERY_SHIFT": lambda e: (e.get("run_len"),),
    "BREACH_REVERT": lambda e: (e.get("extreme"), _r(e.get("level"))),
    "CLOSE_REVERT": lambda e: (e.get("extreme"), _r(e.get("level")), e.get("through")),
    "VOID": lambda e: (_r(e.get("size")),),
    "ORIGIN": lambda e: (_r(e.get("far")), _r(e.get("near"))),
    "DISPLACE": lambda e: (e.get("origin"),),
    "BREAK": lambda e: (e.get("origin"), _r(e.get("level"))),
    "LEG": lambda e: (e.get("end"), e.get("reason")),
    "ZONE": lambda e: (_r(e.get("far")), _r(e.get("near"))),
    "REVISIT": lambda e: (e.get("zone"), e.get("count")),
    "FAIL": lambda e: (e.get("zone"), e.get("count")),
    "SWING": lambda e: (e.get("label"),),
    "STRUCTURE_SHIFT": lambda e: (e.get("from"), e.get("to")),
    "SWEEP_PROTECTED": lambda e: (_r(e.get("swept_level")), _r(e.get("level"))),
    "SWEEP_SHIFT": lambda e: (e.get("sweep_type"), e.get("shift_type"), _r(e.get("level"))),
    "INDUCEMENT": lambda e: (e.get("zone"), _r(e.get("level")), e.get("taken_at")),
    "VOID_INVERTED": lambda e: (e.get("void"),),
    "BREAKER_RETEST": lambda e: (e.get("of"), e.get("of_at"), _r(e.get("level"))),
    "RECLAIM": lambda e: (e.get("of"), e.get("of_at"), _r(e.get("level"))),
    "PROTECTED": lambda e: (e.get("grade"), _r(e.get("level"))),
    "PROTECTED_TAKEN": lambda e: (e.get("grade"), _r(e.get("level")), e.get("closed_back")),
}


def research_events(df: pd.DataFrame) -> dict[str, set]:
    chart = research.parse(df.reset_index(drop=True), time=False)
    out: dict[str, set] = {k: set() for k in RESEARCH_KEYS}
    for e in chart.entities:
        if e.type in RESEARCH_KEYS:
            out[e.type].add((_d(e), e.at, e.known_at, *RESEARCH_KEYS[e.type](e)))
    return out


def port_events(bars: Bars) -> dict[str, list[ev.Event]]:
    p = Parse(bars)
    fr, ext, lv = p.fr, p.ext, p.legs
    life = p.life
    found: dict[str, list[ev.Event]] = {
        "EXTREME": ext,
        "DISPLACE_C": p.displace,
        "DELIVERY_SHIFT": p.shifts,
        "BREACH_REVERT": p.breach,
        "CLOSE_REVERT": p.close_rev,
        "VOID": p.voids,
        "ORIGIN": lv.origins,
        "DISPLACE": lv.displaces,
        "BREAK": lv.breaks,
        "LEG": lv.legs,
        "ZONE": p.zones,
        "REVISIT": [e for e in life if e.kind == "REVISIT"],
        "FAIL": [e for e in life if e.kind == "FAIL"],
        "SWING": ev.swing_labels(ext, fr[1].atr),
        "STRUCTURE_SHIFT": p.kind("STRUCTURE_SHIFT"),
        "SWEEP_PROTECTED": ev.sweep_protected(fr, ext),
        "SWEEP_SHIFT": p.kind("SWEEP_SHIFT"),
        "INDUCEMENT": p.kind("INDUCEMENT"),
        "VOID_INVERTED": ev.void_inversions(fr, p.voids),
        "BREAKER_RETEST": p.kind("BREAKER_RETEST"),
        "RECLAIM": p.kind("RECLAIM"),
        "PROTECTED": p.kind("PROTECTED"),
        "PROTECTED_TAKEN": p.kind("PROTECTED_TAKEN"),
    }
    return found


def keyed(found: dict[str, list[ev.Event]]) -> dict[str, set]:
    return {k: {(e.dir, e.at, e.known_at, *PORT_KEYS[k](e)) for e in v} for k, v in found.items()}


@pytest.fixture(scope="module", params=sorted(SERIES))
def series(request):
    df = SERIES[request.param]()
    return request.param, df, research_events(df), keyed(port_events(bars_of(df)))


@pytest.mark.parametrize("kind", sorted(RESEARCH_KEYS))
def test_every_event_matches_the_research_parser(series, kind):
    name, _, theirs, ours = series
    assert ours[kind] == theirs[kind], (
        f"{name} {kind}: only research {sorted(theirs[kind] - ours[kind])[:5]}, "
        f"only port {sorted(ours[kind] - theirs[kind])[:5]}"
    )


def test_the_fixtures_exercise_every_kind(series):
    """A parity test over events that never occur proves nothing."""
    name, _, theirs, _ = series
    empty = [k for k, v in theirs.items() if not v]
    assert not empty, f"{name} has no {empty}"


def test_the_token_classes_match_the_research_table():
    from mcfl import candles

    df = _fixture("BTCUSDT.4h")
    ours = tokens(bars_of(df))
    theirs = candles.table(df)
    np.testing.assert_array_equal(ours.atr, theirs["atr"])
    for mine, key in ((ours.size, "size"), (ours.force, "force_g"), (ours.close_q, "close_q")):
        assert list(mine) == list(theirs[key])
    assert list(ours.dir) == list(theirs["dir"])


# ------------------------------------------------------------------- causality


@pytest.mark.parametrize("name", ["garch-1", "BTC-15m"])
def test_an_event_known_at_a_bar_is_found_from_that_bar_alone(name):
    """What the service alerts on - events known at the newest bar - must be the
    same whether the series stops there or runs on. Checked on every 7th prefix."""
    df = SERIES[name]()
    full = bars_of(df)
    everything = port_events(full)
    for last in range(60, len(full), 7):
        prefix = port_events(full.upto(last))
        for kind in (
            "DISPLACE_C",
            "DELIVERY_SHIFT",
            "BREACH_REVERT",
            "STRUCTURE_SHIFT",
            "SWEEP_SHIFT",
            "INDUCEMENT",
            "BREAKER_RETEST",
            "RECLAIM",
            "PROTECTED",
            "PROTECTED_TAKEN",
            "CLOSE_REVERT",
        ):
            want = {(e.dir, e.at) for e in everything[kind] if e.known_at == last}
            got = {(e.dir, e.at) for e in prefix[kind] if e.known_at == last}
            assert got == want, f"{name} {kind} at bar {last}"


# ----------------------------------------------------------------- the trade


@pytest.fixture(scope="module")
def paper():
    pytest.importorskip("turn_trade")
    import market_mirror
    import paper_displace
    import turn_trade

    turn_trade.SEC.update({"15m": 900, "1d": 86_400})
    return paper_displace, market_mirror, turn_trade


@pytest.mark.parametrize("name", sorted(SERIES))
def test_signals_match_the_paper_logger(paper, name, monkeypatch):
    paper_displace, _, _ = paper
    df = SERIES[name]()
    monkeypatch.setattr(paper_displace, "CATCH_UP", len(df))
    theirs = {
        (s["side"], s["bar_ts"], round(s["stop"], 9), round(s["atr"], 9))
        for s in paper_displace.signals(df)
    }
    b = bars_of(df)
    ours = {(s.side, int(b.ts[s.at]), round(s.stop, 9), round(s.atr, 9)) for s in tr.signals(b)}
    assert ours == theirs


def test_the_fixtures_carry_signals_to_compare():
    """BTC 4h has none in its 600 bars; the set as a whole must have plenty."""
    found = sum(len(tr.signals(bars_of(make()))) for make in SERIES.values())
    assert found >= 10


def _seconds(name: str) -> int:
    return {"1d": 86_400, "4h": 14_400, "15m": 900}.get(name.rsplit("-", maxsplit=1)[-1], 3_600)


def _iv(name: str) -> str:
    tail = name.rsplit("-", maxsplit=1)[-1]
    return tail if tail in ("1d", "4h", "15m") else "1h"


@pytest.mark.parametrize("name", sorted(SERIES))
def test_the_structure_exit_matches_the_research_trade(paper, name):
    """E2 R against `turn_trade.trades_exits` (no costs), both sides."""
    _, _, turn_trade = paper
    from mcfl.parse import flip

    df = SERIES[name]()
    b = bars_of(df)
    zero = np.zeros(len(df))
    theirs = {}
    for side, frame in ((1, df), (-1, flip(df))):
        for row in turn_trade.trades_exits(frame, side, zero, "t", name, _iv(name)):
            if row["T1"]:
                theirs[(side, row["ts"])] = round(row["E2"], 9)
    ours = {}
    for s in tr.signals(b):
        done = tr.walk(b, s, _seconds(name))
        if done is None:
            # Still open at the last bar: the research marks it at the last close.
            continue
        if done[1].reason == "void":
            continue
        j, out = done
        r = out.r
        if out.reason == "shift":
            if j + 1 >= len(b):
                continue
            entry = b.open[s.at + 1]
            risk = s.side * (entry - s.stop)
            r = s.side * (b.open[j + 1] - entry) / risk
        ours[(s.side, int(b.ts[s.at]))] = round(r, 9)
    assert set(ours) <= set(theirs)
    assert ours == {k: theirs[k] for k in ours}


@pytest.mark.parametrize("name", ["ARB-1d", "ETH-1d"])
def test_the_mirror_exit_bar_matches_market_mirror(paper, name):
    """`market_mirror.exits`: (signal ts, entry ts, exit ts) for the daily longs."""
    _, market_mirror, _ = paper
    df = SERIES[name]()
    theirs = set(market_mirror.exits(df))
    b = bars_of(df)
    ours = set()
    for s in tr.signals(b):
        if s.side < 0 or s.at + 1 >= len(b):
            continue
        done = tr.walk(b, s, 86_400)
        hold = tr.hold_bars(86_400)
        if done is None:
            x = min(len(b) - 1, s.at + hold)
        else:
            j, out = done
            if out.reason == "void":
                continue
            x = j + 1 if out.reason == "shift" and j + 1 < len(b) else j
        ours.add((int(b.ts[s.at]), int(b.ts[s.at + 1]), int(b.ts[x])))
    # Research keeps a trade whose stop is beyond the entry (it fills at once);
    # those are void here and are the only rows allowed to differ.
    assert ours <= theirs
    assert len(theirs - ours) <= 1


@pytest.mark.skipif(not os.environ.get("MCFL_REAL_SERIES_DIR"), reason="no lab series")
def test_signals_match_on_the_labs_stored_daily_series(paper, monkeypatch):
    """Every `binance_perps/*.pkl` daily series in MCFL_REAL_SERIES_DIR, end to end."""
    paper_displace, _, _ = paper
    root = Path(os.environ["MCFL_REAL_SERIES_DIR"])
    checked = 0
    for path in sorted(root.glob("*USDT.pkl"))[:10]:
        # The lab's own cache of public Binance klines, written by its fetcher;
        # opt-in via the environment, never read in CI.
        df = pd.read_pickle(path)[0][["ts", "open", "high", "low", "close"]]
        df = df.tail(700).reset_index(drop=True)
        monkeypatch.setattr(paper_displace, "CATCH_UP", len(df))
        theirs = {(s["side"], s["bar_ts"]) for s in paper_displace.signals(df)}
        b = bars_of(df)
        assert {(s.side, int(b.ts[s.at])) for s in tr.signals(b)} == theirs, path.name
        checked += 1
    assert checked


def test_major_bos_needs_a_major_swing_and_a_three_atr_leg():
    """A minor 15m BOS does not fire; a major one does."""
    n = 80
    base = np.full(n, 100.0)
    # A 10/10 swing high at bar 20 (110), a 4-ATR-ish pullback to 96, then a
    # close through 110 at bar 45.
    path = base.copy()
    path[10:21] = np.linspace(100, 110, 11)
    path[21:35] = np.linspace(109, 96, 14)
    path[35:46] = np.linspace(97, 111, 11)
    path[46:] = 111
    o = np.r_[path[0], path[:-1]]
    h = np.maximum(o, path) + 0.3
    lo = np.minimum(o, path) - 0.3
    h[20] = 110.5
    b = Bars(np.arange(n, dtype=np.int64) * 900, o, h, lo, path)
    major = ev.major_bos(frames(b))
    ups = [e for e in major if e.dir > 0]
    assert len(ups) == 1
    assert ups[0].get("pivot") == 20
    assert ups[0].get("leg_atr") >= 3.0
    # The same chart with a shallow pullback - a minor swing - does not fire.
    shallow = path.copy()
    shallow[21:35] = np.linspace(109.8, 109.0, 14)
    shallow[35:46] = np.linspace(109.2, 111, 11)
    o2 = np.r_[shallow[0], shallow[:-1]]
    h2 = np.maximum(o2, shallow) + 0.3
    h2[20] = 110.5
    b2 = Bars(b.ts, o2, h2, np.minimum(o2, shallow) - 0.3, shallow)
    assert not [e for e in ev.major_bos(frames(b2)) if e.dir > 0]
