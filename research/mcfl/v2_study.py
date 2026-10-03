"""MCFL v2's new alphabets against walks we generate.

As in v0 and v1 (`ngrams.py`, `candle_study.py`): for each source - an iid walk, a GARCH(1,1) walk
and an AR(1) momentum walk (phi 0.2) - the null is an iid Gaussian walk of the same length and
close-to-close volatility (`synth.matched_walk`). R + 1 null sets are drawn; the data is compared
with the pool of R and each null set with the pool of the others, so a divergence is read against
the null's own spread. Every series is given 15-minute timestamps and a tick volume (`synth.ticks`)
before it is parsed, so the session and volume words exist; the null walks get theirs the same way.

Per item, two kinds of comparison:
  streams   a v2 alphabet as a sentence (swing labels, structure shifts, void transitions, ...):
            KL against the null at orders 1-3 and next-token k = 1-2, with p = the share of null
            leave-one-out KLs at least as large (floored at 1 / (R + 2));
  rates     events per 1,000 bars, and outcome shares (a void filled, an escape that held, a pool
            taken, a CRT that distributed ...), each as a z against the R null sets.

  python research/mcfl/v2_study.py [--series 8] [--bars 5000] [--reps 10] [--items 1,11,...]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcfl import synth
from mcfl.core import Chart, Entity
from mcfl.ngrams import compare

OUT = Path(__file__).resolve().parent / "out"
SEC = 900
"""Every generated series is read as 15-minute bars."""
T0 = 1_700_006_400 - 1_700_006_400 % 86400
"""Their first bar's open: a UTC midnight (2023-11-15)."""

SOURCES = {
    "walk": lambda n, s: synth.walk(n, seed=s),
    "garch": lambda n, s: synth.garch(n, seed=s),
    "trend": lambda n, s: synth.trend(n, seed=s),
    "gapped": lambda n, s: synth.gapped(n, seed=s),
}
"""`gapped` is a walk whose bars open away from the last close (a session market); its null is the same
generator matched in volatility, since gaps alone make the Japanese vocabulary occur."""


def dress(df, seed: int):
    """Timestamps and a tick volume, as every series in this study gets them."""
    df = synth.ticks(df, seed=seed)
    return df.assign(ts=T0 + np.arange(len(df), dtype=np.int64) * SEC)


# ---------------------------------------------------------------- what each item measures

def _seq(ch: Chart, types: tuple[str, ...], text: Callable[[Entity], str]) -> list[str]:
    ents = sorted((e for e in ch.entities if e.type in types), key=lambda e: (e.known_at, e.at, e.id))
    return [text(e) for e in ents]


def item1(ch: Chart) -> dict:
    sw = ch.of("SWING")
    rates = Counter(f"SWING[{e.get('label')}]" for e in sw)
    rates.update(f"STRUCTURE_SHIFT[{e.get('from')}>{e.get('to')}]" for e in ch.of("STRUCTURE_SHIFT"))
    shares = {}
    # time spent in each state
    states = Counter()
    sh = sorted(ch.of("STRUCTURE_SHIFT"), key=lambda e: e.known_at)
    last, cur = 0, "MIXED"
    for e in sh:
        states[cur] += e.known_at - last
        last, cur = e.known_at, e.get("to")
    states[cur] += ch.n - last
    for k in ("UP", "DOWN", "MIXED"):
        shares[f"time in {k}"] = (states[k], ch.n)
    return {"streams": {"labels": _seq(ch, ("SWING",), lambda e: e.get("label")),
                        "states": _seq(ch, ("STRUCTURE_SHIFT",), lambda e: e.get("to"))},
            "rates": rates, "shares": shares}


def item11(ch: Chart) -> dict:
    br = ch.of("BREAK")
    rates = Counter(f"BREAK[{e.get('vs_structure')}]" for e in br)
    rates["CHARACTER_SHIFT"] = len(ch.of("CHARACTER_SHIFT"))
    n = len(br)
    shares = {f"breaks {k}": (rates[f"BREAK[{k}]"], n) for k in ("WITH", "AGAINST", "NONE")}
    # after a CHoCH, is the next BREAK in its direction?
    brs = sorted(br, key=lambda e: (e.known_at, e.at))
    nxt = Counter()
    for c in ch.of("CHARACTER_SHIFT"):
        later = [b for b in brs if b.at > c.at]
        if later:
            nxt[later[0].dir == c.dir] += 1
    shares["next BREAK after a CHoCH goes its way"] = (nxt[True], nxt[True] + nxt[False])
    return {"streams": {"breaks": _seq(ch, ("BREAK",), lambda e: f"{e.dir.arrow}{e.get('vs_structure')}")},
            "rates": rates, "shares": shares}


def item4(ch: Chart) -> dict:
    voids = ch.of("VOID")
    first: dict[str, dict[str, int]] = {}
    for t in ch.transitions:
        if t.zone.startswith("VOID."):
            first.setdefault(t.zone, {})[t.dst] = t.at
    shares = {}
    for st in ("PARTIAL", "FILLED", "INVERTED"):
        for h in (5, 50):
            ok = sum(1 for v in voids if v.at + h < ch.n)
            hit = sum(1 for v in voids if v.at + h < ch.n and first.get(v.id, {}).get(st, 10**9) <= v.at + h)
            shares[f"{st} within {h} bars"] = (hit, ok)
    filled = [v for v in voids if "FILLED" in first.get(v.id, {})]
    shares["INVERTED on the bar it FILLED, of filled"] = (
        sum(1 for v in filled if first[v.id].get("INVERTED") == first[v.id]["FILLED"]), len(filled))
    rates = Counter(e.type for e in ch.of("VOID_PARTIAL", "VOID_FILLED", "VOID_INVERTED"))
    # the transitions as a sentence, in the order they became known
    stream = [f"{t.dst}{'↑' if '.U.' in t.zone else '↓'}" for t in ch.transitions if t.zone.startswith("VOID.")]
    return {"streams": {"void life": stream}, "rates": rates, "shares": shares}


def item7(ch: Chart) -> dict:
    shares = {}
    for name, ents in (("RETRACE", ch.of("RETRACE")),
                       ("PULLBACK INSIDE", [e for e in ch.of("PULLBACK") if e.get("phase") == "INSIDE"]),
                       ("PULLBACK AFTER", [e for e in ch.of("PULLBACK") if e.get("phase") == "AFTER"])):
        for b in ("SHALLOW", "HALF", "DEEP", "BEYOND"):
            shares[f"{name} {b}"] = (sum(e.get("depth_bin") == b for e in ents), len(ents))
    br = len(ch.of("BREAK"))
    shares["BREAKs with a DAX50 (inside pullback >= 0.5)"] = (len(ch.of("DAX50")), br)
    rates = Counter(e.type for e in ch.of("RETRACE", "PULLBACK", "DAX50"))
    return {"streams": {"pullbacks": _seq(ch, ("PULLBACK",), lambda e: f"{e.get('phase')[0]}{e.get('depth_bin')}")},
            "rates": rates, "shares": shares}


def item6(ch: Chart) -> dict:
    taken = {e.get("pool"): e for e in ch.of("POOL_TAKEN")}
    pools = ch.of("POOL")
    shares = {}
    for h in (20, 100):
        ok = [p for p in pools if p.known_at + h < ch.n]
        shares[f"POOL taken within {h} bars"] = (sum(1 for p in ok if p.id in taken and taken[p.id].at <= p.known_at + h),
                                                 len(ok))
    tk = list(taken.values())
    shares["POOL_TAKEN closed back (swept)"] = (sum(1 for t in tk if t.get("closed_back")), len(tk))
    sw = ch.of("SWEEP_PROTECTED")
    shares["SWEEP_PROTECTED of swing lows/highs"] = (len(sw), len(ch.of("EXTREME")))
    # does the protected low hold for 20 bars after it is known?
    lo, hi = ch_bars(ch)
    held = 0
    ok = 0
    for s in sw:
        if s.known_at + 20 < ch.n:
            ok += 1
            seg = lo[s.known_at + 1:s.known_at + 21] if s.dir.value == "UP" else -hi[s.known_at + 1:s.known_at + 21]
            held += bool((seg >= (s.get("level") if s.dir.value == "UP" else -s.get("level"))).all())
    shares["protected level holds 20 bars"] = (held, ok)
    rates = Counter(e.type for e in ch.of("POOL", "POOL_TAKEN", "SWEEP_PROTECTED", "DAX_SETUP"))
    return {"streams": {"pools": _seq(ch, ("POOL", "POOL_TAKEN"), lambda e: e.type[5:6] + e.dir.arrow + (
        ("S" if e.get("closed_back") else "T") if e.type == "POOL_TAKEN" else str(min(e.get("count"), 3))))},
            "rates": rates, "shares": shares}


def ch_bars(ch: Chart) -> tuple[np.ndarray, np.ndarray]:
    """The bars' lows and highs, from the CANDLE lexemes."""
    c = sorted(ch.of("CANDLE"), key=lambda e: e.at)
    return np.array([e.get("low") for e in c]), np.array([e.get("high") for e in c])


def item5(ch: Chart) -> dict:
    rs = ch.of("RANGE")
    esc, fail = ch.of("ESCAPE"), ch.of("FAILED_ESCAPE")
    shares = {"excursions that ESCAPE": (len(esc), len(esc) + len(fail)),
              "ESCAPE up": (sum(e.dir.value == "UP" for e in esc), len(esc))}
    # the escape goes the way of the edge tested last before it?
    tests = sorted(ch.of("RANGE_TEST"), key=lambda e: e.at)
    same = known = 0
    for e in esc:
        prior = [t for t in tests if t.get("range") == e.get("range") and t.at < e.at]
        if prior:
            known += 1
            same += prior[-1].dir == e.dir
    shares["ESCAPE through the edge tested last"] = (same, known)
    # after an ESCAPE: does price reach one box height beyond the edge before closing back inside?
    lo, hi = ch_bars(ch)
    cl = np.array([e.get("close") for e in sorted(ch.of("CANDLE"), key=lambda e: e.at)])
    ids = ch.by_id()
    far = n_ok = 0
    for e in esc:
        r = ids[e.get("range")]
        hgt = r.get("high") - r.get("low")
        k = e.known_at + 1
        up = e.dir.value == "UP"
        for t in range(k, min(ch.n, k + 200)):
            if (cl[t] <= r.get("high")) if up else (cl[t] >= r.get("low")):
                n_ok += 1
                break
            if (hi[t] >= r.get("high") + hgt) if up else (lo[t] <= r.get("low") - hgt):
                n_ok += 1
                far += 1
                break
    shares["after ESCAPE, one box height on before closing back in"] = (far, n_ok)
    rates = Counter(e.type for e in ch.of("RANGE", "RANGE_TEST", "ESCAPE", "FAILED_ESCAPE"))
    return {"streams": {"range events": _seq(ch, ("RANGE", "RANGE_TEST", "ESCAPE", "FAILED_ESCAPE"),
                                             lambda e: e.type[:3] + e.dir.arrow)},
            "rates": rates, "shares": shares}


def item2(ch: Chart) -> dict:
    c = sorted(ch.of("CANDLE"), key=lambda e: e.at)
    r = {e.at: e for e in ch.of("BAR_RELATION")}
    rng = np.array([e.get("high") - e.get("low") for e in c])
    stream = []
    for e in c[10:]:
        ov = r[e.at].get("overlap")
        code = "W7" if e.get("WR7") else "N7" if e.get("NR7") else "N4" if e.get("NR4") else "-"
        stream.append(code + ("h" if ov >= 0.75 else "l" if ov <= 0.25 else "m"))
    shares = {}
    for k in ("NR4", "NR7", "WR7"):
        ts = [e.at for e in c if e.get(k) and e.at + 1 < ch.n]
        shares[f"after {k}, the next bar's range is wider"] = (sum(rng[t + 1] > rng[t] for t in ts), len(ts))
        shares[f"after {k}, the next 5 bars' mean range > this bar's"] = (
            sum(rng[t + 1:t + 6].mean() > rng[t] for t in ts if t + 5 < ch.n), sum(1 for t in ts if t + 5 < ch.n))
    shares["NR7 bars"] = (sum(1 for e in c if e.get("NR7")), len(c))
    shares["WR7 bars"] = (sum(1 for e in c if e.get("WR7")), len(c))
    rates = Counter(f"{e.type}{e.dir.arrow}" for e in ch.of("BALANCE", "IMBALANCE"))
    return {"streams": {"compression": stream}, "rates": rates, "shares": shares}


def item8(ch: Chart) -> dict:
    sess = {e.at: e.get("session") for e in ch.of("CANDLE")}
    rates = Counter(f"BREAK in {sess[e.at]}" for e in ch.of("BREAK"))
    rates.update(f"SESSION_EXTREME_TAKEN{e.dir.arrow} {e.get('session')}" for e in ch.of("SESSION_EXTREME_TAKEN"))
    shares = {}
    ext = ch.of("SESSION_EXTREME")
    taken = {e.get("extreme"): e for e in ch.of("SESSION_EXTREME_TAKEN")}
    for name in ("ASIA", "LONDON", "OVERLAP", "NY"):
        xs = [e for e in ext if e.get("session") == name]
        shares[f"{name} extremes taken before its next instance"] = (sum(e.id in taken for e in xs), len(xs))
        tk = [taken[e.id] for e in xs if e.id in taken]
        shares[f"{name} takes that closed back"] = (sum(t.get("closed_back") for t in tk), len(tk))
    # a fast return against a slow one: what ends the revisit
    rp = {(e.get("zone"), e.get("count")) for e in ch.of("REJECT_PATH")}
    for p in ("FAST", "NORMAL", "SLOW"):
        rv = [r for r in ch.of("REVISIT") if r.get("pace") == p]
        shares[f"REVISIT[pace={p}] then REJECT_PATH"] = (sum((r.get("zone"), r.get("count")) in rp for r in rv), len(rv))
    stream = _seq(ch, ("BREAK",), lambda e: f"{sess[e.at][:2]}{e.dir.arrow}")
    return {"streams": {"breaks by session": stream}, "rates": rates, "shares": shares}


def item9(ch: Chart) -> dict:
    cl = np.array([e.get("close") for e in sorted(ch.of("CANDLE"), key=lambda e: e.at)])
    rates = Counter(f"{e.type}{e.dir.arrow}" for e in ch.of("FOCUS", "FOCUS6", "CUSUM_IGNITION", "FOCUS_ZONE"))
    shares = {}
    for k in ("FOCUS", "FOCUS6", "CUSUM_IGNITION"):
        for h in (5, 20):
            ev = [e for e in ch.of(k) if e.known_at + h < ch.n]
            shares[f"{k}: the close {h} bars after the fire is further its way"] = (
                sum((cl[e.known_at + h] - cl[e.known_at]) * (1 if e.dir.value == "UP" else -1) > 0 for e in ev), len(ev))
    zs = ch.of("ZONE")
    shares["ZONEs with a FOCUS6 at the origin (FOCUS_ZONE)"] = (
        len({e.get("of_zone") for e in ch.of("FOCUS_ZONE") if e.get("threshold") == 6.0}), len(zs))
    return {"streams": {"changepoints": _seq(ch, ("FOCUS6", "CUSUM_IGNITION"), lambda e: e.type[0] + e.dir.arrow)},
            "rates": rates, "shares": shares}


def item3(ch: Chart) -> dict:
    c = sorted(ch.of("CANDLE"), key=lambda e: e.at)
    d = np.array([1 if e.dir.value == "UP" else -1 if e.dir.value == "DOWN" else 0 for e in c])
    shares = {}
    for k in ("ABSORPTION", "EASE", "AGREE", "NEUTRAL"):
        ts = [e.at for e in c if e.get("effort") == k and e.at + 1 < ch.n]
        shares[f"{k} bars"] = (len(ts), ch.n)
        shares[f"after {k}, the next bar goes the same way"] = (
            sum(d[t + 1] == d[t] for t in ts if d[t]), sum(1 for t in ts if d[t]))
    for k in ("BUY", "SELL"):
        ts = [e.at for e in c if e.get("taker") == k and e.at + 1 < ch.n]
        want = 1 if k == "BUY" else -1
        shares[f"after taker={k}, the next bar goes its way"] = (sum(d[t + 1] == want for t in ts), len(ts))
    stream = [{"ABSORPTION": "A", "EASE": "E", "AGREE": "G", "NEUTRAL": "N"}.get(e.get("effort"), "W")
              + {"UP": "+", "DOWN": "-", "NONE": "0"}[e.dir.value] for e in c[10:]]
    rates = Counter(f"effort {e.get('effort')}" for e in c)
    return {"streams": {"effort": stream}, "rates": rates, "shares": shares}


def item12(ch: Chart) -> dict:
    from mcfl.crt import CRT_N
    c = sorted(ch.of("CANDLE"), key=lambda e: e.at)
    hi = np.array([e.get("high") for e in c])
    lo = np.array([e.get("low") for e in c])
    cl = np.array([e.get("close") for e in c])
    pur = ch.of("PURGE")
    dist = {d.get("purge"): d for d in ch.of("DISTRIBUTION")}
    ok = [p for p in pur if p.at + CRT_N < ch.n]
    shares = {"PURGE then DISTRIBUTION (CRT3) within 3": (sum(p.id in dist for p in ok), len(ok))}
    ds = [dist[p.id] for p in ok if p.id in dist]
    shares["... of those, the mid reached on an earlier bar"] = (sum(not d.get("mid_same_bar") for d in ds), len(ds))
    shares["... distributed on the next candle"] = (sum(d.get("bars") == 1 for d in ds), len(ds))
    # the baseline: a candle that closed inside the previous range WITHOUT a purge - how often does the
    # following 3 reach the previous range's low (or high, for the mirror)?
    base = hit = 0
    for t in range(11, ch.n - CRT_N):
        if lo[t - 1] <= cl[t] <= hi[t - 1] and hi[t] <= hi[t - 1] and lo[t] >= lo[t - 1]:
            base += 2
            hit += (lo[t + 1:t + CRT_N + 1] <= lo[t - 1]).any() + (hi[t + 1:t + CRT_N + 1] >= hi[t - 1]).any()
    shares["baseline: an inside candle, the range's low (or high) within 3"] = (hit, base)
    rates = Counter(f"{e.type}{e.dir.arrow}" for e in ch.of("PURGE", "DISTRIBUTION", "CRT3"))
    return {"streams": {"crt": _seq(ch, ("PURGE", "DISTRIBUTION"), lambda e: e.type[0] + e.dir.arrow)},
            "rates": rates, "shares": shares}


def item10(m) -> dict:
    from mcfl.mtf import nested_flags
    ch = m.ltf
    zs = {z.id: z for z in ch.of("ZONE")}
    # how each zone's first revisit ended: REJECT_PATH (1 ATR back out) before a FAIL?
    first: dict[str, str] = {}
    for e in sorted(ch.of("REVISIT", "REJECT_PATH", "FAIL", "ACCEPT"), key=lambda e: (e.known_at, e.at)):
        z = e.get("zone")
        if e.type == "REVISIT":
            first.setdefault(z, "open")
        elif first.get(z) == "open" and e.get("count") == 1:
            first[z] = e.type
    shares = {}
    rates = Counter()
    for mode in ("causal", "entry", "leg", "research"):
        fl = nested_flags(m, mode)
        flagged = [k for k, v in fl.items() if v]
        rates[f"ZONE nested ({mode})"] = len(flagged)
        done = [k for k in flagged if first.get(k) in ("REJECT_PATH", "FAIL")]
        shares[f"nested ({mode}): first revisit REJECT_PATH before FAIL"] = (
            sum(first[k] == "REJECT_PATH" for k in done), len(done))
        shares[f"share of zones nested ({mode})"] = (len(flagged), len(zs))
    done = [k for k in zs if first.get(k) in ("REJECT_PATH", "FAIL")]
    shares["all zones: first revisit REJECT_PATH before FAIL"] = (sum(first[k] == "REJECT_PATH" for k in done), len(done))
    rates.update(r.kind for r in m.relations if r.kind in ("ALIGN", "CONFLICT"))
    pur = [e for e in m.entities if e.type == "PURGE"]
    dist = {e.get("purge") for e in m.entities if e.type == "DISTRIBUTION"}
    shares["4h CRT: LTF-seen purge then distribution within 3 HTF bars"] = (sum(p.id in dist for p in pur), len(pur))
    rates["4h PURGE seen on 15m"] = len(pur)
    al = [r for r in m.relations if r.kind in ("ALIGN", "CONFLICT") and r.src.startswith("ZONE") and "BREAK" in r.dst]
    stream = [("A" if r.kind == "ALIGN" else "C") for r in sorted(al, key=lambda r: r.known_at)]
    return {"streams": {"zone vs 4h legs": stream}, "rates": rates, "shares": shares}


R_LEVELS = (1, 2, 4, 10)
HORIZON = 500
"""P(N R): bars a pattern's trade is followed for, at most."""


def mfe_r(ch: Chart, e: Entity, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray) -> float | None:
    """The most R a PATTERN reached its way before its stop: entry the close of its last bar, stop the
    far end of its bars (the lowest low for UP, the highest high for DOWN), each later bar's stop
    checked before its extreme. None without risk or a following bar."""
    ats = [int(p.split(".")[2]) for p in e.parts if p.startswith("CANDLE.")]
    t, s = e.known_at, (1 if e.dir.value == "UP" else -1)
    if t + 1 >= ch.n:
        return None
    entry = cl[t]
    stop = min(lo[a] for a in ats) if s > 0 else max(hi[a] for a in ats)
    risk = s * (entry - stop)
    if not risk > 0:
        return None
    best = 0.0
    for k in range(t + 1, min(ch.n, t + 1 + HORIZON)):
        if (lo[k] <= stop) if s > 0 else (hi[k] >= stop):
            break
        best = max(best, s * ((hi[k] if s > 0 else lo[k]) - entry) / risk)
    return best


def item13(ch: Chart) -> dict:
    c = sorted(ch.of("CANDLE"), key=lambda e: e.at)
    hi = np.array([e.get("high") for e in c])
    lo = np.array([e.get("low") for e in c])
    cl = np.array([e.get("close") for e in c])
    rates = Counter()
    shares = {}
    by: dict[str, list[float]] = {}
    for e in ch.of("PATTERN"):
        name = f"{e.get('name')}{e.dir.arrow}"
        rates[name] += 1
        if e.dir.value != "NONE":
            m = mfe_r(ch, e, hi, lo, cl)
            if m is not None:
                by.setdefault(name, []).append(m)
    for name in sorted(by):
        xs = by[name]
        for N in R_LEVELS:
            shares[f"{name} P(>={N}R) [1/(N+1) = {1 / (N + 1):.3f}]"] = (sum(x >= N for x in xs), len(xs))
    return {"streams": {"patterns": _seq(ch, ("PATTERN",), lambda e: f"{e.get('name')}{e.dir.arrow}")},
            "rates": rates, "shares": shares}


ITEMS: dict[str, Callable[[Chart], dict]] = {"13": item13, "10": item10, "12": item12, "3": item3, "9": item9, "8": item8, "2": item2, "1": item1, "11": item11, "4": item4, "7": item7, "6": item6,
                                             "5": item5}
TITLES = {"13": "the candlestick vocabulary: frequency and P(N R) against walks", "10": "multiple timeframes (15m against 4h): NESTED, ALIGN / CONFLICT, 4h CRT", "12": "candle range theory (single timeframe)", "3": "volume: effort against result, taker skew", "9": "changepoints: FOCuS and CUSUM", "8": "sessions, session anchors and tempo", "2": "compression and expansion (NR4, NR7, WR7, overlap, BALANCE, IMBALANCE)", "1": "swing labels and STRUCTURE", "11": "vs_structure and CHARACTER_SHIFT", "4": "the VOID lifecycle",
          "7": "retracement depth", "6": "liquidity pools and the protected sweep",
          "5": "RANGE: boxes, tests and escapes"}


# ---------------------------------------------------------------- runs

def _measure(job: tuple) -> dict:
    from mcfl.parse import parse
    kind, src, n, s, rep, items = job
    base = SOURCES[src](n, s)
    if kind == "null":
        nseed = 1_000_003 * (rep + 1) + s
        if src == "gapped":
            sd = float(np.std(np.diff(base["close"].to_numpy(float))))
            df = synth.gapped(n, sigma=sd / np.sqrt(1 + 0.5 ** 2), seed=nseed)
        else:
            df = synth.matched_walk(base, seed=nseed)
        seed = 7_000_001 * (rep + 1) + s
    else:
        df, seed = base, s
    df = dress(df, seed)
    if "10" in items:
        from mcfl.mtf import parse_mtf
        m = parse_mtf(df, htf_sec=14400, label="4h", changepoints=True)
        ch = m.ltf
    else:
        m, ch = None, parse(df, changepoints=True)
    return {k: (ITEMS[k](m) if k == "10" else ITEMS[k](ch)) for k in items} | {"_bars": ch.n}


def _z(x: float, xs: list[float]) -> float:
    sd = float(np.std(xs, ddof=1))
    return (x - float(np.mean(xs))) / sd if sd > 0 else 0.0


def report_item(key: str, data: list[dict], nulls: list[list[dict]]) -> list[str]:
    L = []
    d0 = [d[key] for d in data]
    ns = [[g[key] for g in nl] for nl in nulls]
    for name in d0[0]["streams"]:
        rep = compare([d["streams"][name] for d in d0], [[g["streams"][name] for g in nl] for nl in ns],
                      max_n=3, max_k=2, top=True)
        syms = len({x for d in d0 for x in d["streams"][name]})
        ps = " ".join(f"n={n}:{rep['n'][n]['p']:.3f}" for n in (1, 2, 3)) + " " + " ".join(
            f"k={k}:{rep['k'][k]['p']:.3f}" for k in (1, 2))
        L.append(f"   stream {name:<14} {rep['tokens']:>7} tokens, {syms:>3} symbols   p: {ps}")
        for n in (1, 2):
            for g, x, m, z in rep["n"][n]["top"][:4]:
                if abs(z) >= 3:
                    L.append(f"      {n}-gram {g:<40} {x:8.2f} {m:8.2f} {z:+6.1f}  (per 1,000 tokens: data / null / z)")
    bars = sum(d["_bars"] for d in data)
    keys = sorted({k for d in d0 for k in d["rates"]} | {k for nl in ns for g in nl for k in g["rates"]})
    if keys:
        L.append("   per 1,000 bars (data / null mean / z):")
        for k in keys:
            x = 1000 * sum(d["rates"][k] for d in d0) / bars
            xs = [1000 * sum(g["rates"][k] for g in nl) / sum(g["_bars"] for g in nl_full)
                  for nl, nl_full in zip(ns[1:], nulls[1:])]
            L.append(f"     {k:<40} {x:9.2f} {np.mean(xs):9.2f} {_z(x, xs):+6.1f}")
    skeys = list(dict.fromkeys(k for d in d0 for k in d.get("shares", {})))
    if skeys:
        L.append("   shares (data / null mean / z [data n / null n per set]):")
        z0 = (0, 0)
        for k in skeys:
            a = sum(d["shares"].get(k, z0)[0] for d in d0)
            b = sum(d["shares"].get(k, z0)[1] for d in d0)
            xs, nbs = [], []
            for nl in ns[1:]:
                na = sum(g["shares"].get(k, z0)[0] for g in nl)
                nb = sum(g["shares"].get(k, z0)[1] for g in nl)
                xs.append(na / nb if nb else float("nan"))
                nbs.append(nb)
            x = a / b if b else float("nan")
            fin = [v for v in xs if v == v]
            m = float(np.mean(fin)) if fin else float("nan")
            L.append(f"     {k:<48} {x:7.3f} {m:7.3f} {_z(x, fin) if len(fin) > 1 else 0.0:+6.1f} "
                     f"[{b} / {np.mean(nbs):.0f}]")
    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", type=int, default=8)
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--items", default=",".join(ITEMS))
    ap.add_argument("--sources", default="walk,garch,trend")
    a = ap.parse_args()
    items = tuple(a.items.split(","))
    lines = [f"MCFL v2 alphabets against matched iid walks: {a.series} series x {a.bars} bars per source, "
             f"R = {a.reps}; 15m timestamps and tick volume on every series", ""]
    res = {}
    with ProcessPoolExecutor(a.workers) as ex:
        for src in a.sources.split(","):
            seeds = [20_000 * (list(SOURCES).index(src) + 1) + i for i in range(a.series)]
            data = list(ex.map(_measure, [("data", src, a.bars, s, 0, items) for s in seeds]))
            nulls = [list(ex.map(_measure, [("null", src, a.bars, s, r, items) for s in seeds]))
                     for r in range(a.reps + 1)]
            res[src] = (data, nulls)
            print(f"  {src} parsed", flush=True)
    for key in items:
        lines.append(f"== item {key}: {TITLES[key]}")
        for src, (data, nulls) in res.items():
            lines.append(f"-- {src} against its matched walks")
            lines += report_item(key, data, nulls)
        lines.append("")
    text = "\n".join(lines)
    OUT.mkdir(exist_ok=True)
    path = OUT / ("v2.txt" if a.items == ",".join(ITEMS) else f"v2_items_{a.items.replace(',', '_')}.txt")
    path.write_text(text + "\n")
    print(text)
    print(f"written {path}")


if __name__ == "__main__":
    main()
