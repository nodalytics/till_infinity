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
}


def dress(df, seed: int):
    """Timestamps and a tick volume, as every series in this study gets them."""
    df = synth.ticks(df, seed=seed) if hasattr(synth, "ticks") else df
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


ITEMS: dict[str, Callable[[Chart], dict]] = {"1": item1, "11": item11, "4": item4, "7": item7, "6": item6}
TITLES = {"1": "swing labels and STRUCTURE", "11": "vs_structure and CHARACTER_SHIFT", "4": "the VOID lifecycle",
          "7": "retracement depth", "6": "liquidity pools and the protected sweep"}


# ---------------------------------------------------------------- runs

def _measure(job: tuple) -> dict:
    from mcfl.parse import parse
    kind, src, n, s, rep, items = job
    base = SOURCES[src](n, s)
    if kind == "null":
        df = synth.matched_walk(base, seed=1_000_003 * (rep + 1) + s)
        seed = 7_000_001 * (rep + 1) + s
    else:
        df, seed = base, s
    ch = parse(dress(df, seed))
    return {k: ITEMS[k](ch) for k in items} | {"_bars": ch.n}


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
    skeys = list(d0[0].get("shares", {}))
    if skeys:
        L.append("   shares (data / null mean / z [data n]):")
        for k in skeys:
            a = sum(d["shares"][k][0] for d in d0)
            b = sum(d["shares"][k][1] for d in d0)
            xs = []
            for nl in ns[1:]:
                na, nb = sum(g["shares"][k][0] for g in nl), sum(g["shares"][k][1] for g in nl)
                xs.append(na / nb if nb else float("nan"))
            x = a / b if b else float("nan")
            L.append(f"     {k:<48} {x:7.3f} {np.nanmean(xs):7.3f} {_z(x, [v for v in xs if v == v]):+6.1f} [{b}]")
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
