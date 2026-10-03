"""MCFL v1's candle layer against walks we generate.

Part 1 - bar words. For each source the null is, as in v0, an iid Gaussian walk of the same length
and close-to-close volatility (`synth.matched_walk`); R + 1 null sets, the data compared with the
pool of R, each null set with the pool of the others. Six alphabets (`candles.stream`): the fuzzy
word with and without strength, a coarse word with and without strength, the coarse word with the
bar relation, and the set of named point relations. Also, per bar: how often each named point
relation and each candle production occurs, against the same null, and how often the next bar goes
the pattern's way.

The momentum source, `synth.trend`, builds its bars differently from `synth.walk` (the bar's
return is spread evenly over its sub-steps, plus within-bar noise that sums to zero), so its candle
shapes differ from a walk's even with no momentum. `trend0` is that generator with phi = 0: its
distance from the walk is the construction's, not momentum's. `trend|trend0` compares momentum with
its own generator at phi = 0, matched in volatility - the comparison that isolates momentum.

Part 2 - full parses: REJECT (candle) against REJECT_PATH (v0's), DISPLACE_C against v0's ATR
DISPLACE, and how often a DELIVERY_SHIFT confirms a revisit.

  python research/mcfl/candle_study.py [--series 8] [--bars 5000] [--reps 10]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcfl import candles, synth
from mcfl.core import COMPOSITE_POINTS, NAMED_POINTS
from mcfl.grammar import words
from mcfl.ngrams import compare

OUT = Path(__file__).resolve().parent / "out"
TOP = 8
"""Rows of each table of largest differences."""
NAMES = tuple(NAMED_POINTS) + tuple(COMPOSITE_POINTS)
PATTERNS = ("PIN", "ENGULF", "INSIDE_BREAK", "STAR", "DISPLACE_C", "DELIVERY_SHIFT")

SOURCES = {
    "walk": lambda n, s: synth.walk(n, seed=s),
    "garch": lambda n, s: synth.garch(n, seed=s),
    "trend": lambda n, s: synth.trend(n, seed=s),
    "trend0": lambda n, s: synth.trend(n, phi=0.0, seed=s),
}
NULLS = {"walk": "walk", "garch": "walk", "trend": "walk", "trend0": "walk", "trend|trend0": "trend0"}
"""Each comparison: data source (before the bar) against the null generator."""


def _null(src: str, kind: str, n: int, s: int, rep: int):
    base = SOURCES[src](n, s)
    seed = 1_000_003 * (rep + 1) + s
    if kind == "walk":
        return synth.matched_walk(base, seed=seed)
    sigma = float(np.std(np.diff(base["close"].to_numpy(float))))
    return synth.trend(n, sigma=sigma, phi=0.0, seed=seed)


def _measure(df) -> dict:
    T = candles.table(df)
    cid, rid = candles.ids(T)
    out = {"streams": {a: candles.stream(T, a) for a in candles.ALPHABETS}, "bars": len(cid)}
    valid = T["rel_valid"] & (T["size"] != candles.WARMUP)
    out["names"] = {k: int((T[k] & valid).sum()) for k in NAMES}
    out["name_bars"] = int(valid.sum())
    ev = [e for e in words(T, cid, rid) if e.type in PATTERNS]
    out["patterns"] = Counter(f"{e.type}{e.dir.arrow}" for e in ev)
    nxt = Counter()
    for e in ev:  # does the next bar go the pattern's way?
        t = e.known_at + 1
        if t < len(cid):
            want = "BULL" if e.dir.value == "UP" else "BEAR"
            nxt[f"{e.type}{e.dir.arrow}", T["dir"][t] == want] += 1
    out["next"] = nxt
    return out


def _job(job: tuple) -> dict:
    kind, src, n, s, rep = job
    df = SOURCES[src](n, s) if kind == "data" else _null(src, kind, n, s, rep)
    return _measure(df)


def _z(x: float, xs: list[float]) -> float:
    sd = float(np.std(xs, ddof=1))
    return (x - float(np.mean(xs))) / sd if sd > 0 else 0.0


def _rates(data: list[dict], nulls: list[list[dict]], key: str, per: str, keys) -> list[tuple]:
    """Rate per 1,000 (bars, or name_bars) in the data against each null set's."""
    def rate(group: list[dict], k: str) -> float:
        return 1000 * sum(g[key][k] for g in group) / sum(g[per] for g in group)
    rows = []
    for k in keys:
        x, xs = rate(data, k), [rate(g, k) for g in nulls[1:]]
        rows.append((k, x, float(np.mean(xs)), _z(x, xs)))
    return rows


def _next(data: list[dict], nulls: list[list[dict]], k: str) -> tuple[float, float, int]:
    def p(group):
        a = sum(g["next"][k, True] for g in group)
        b = sum(g["next"][k, False] for g in group)
        return a / (a + b) if a + b else float("nan"), a + b
    x, m = p(data)
    return x, float(np.nanmean([p(g)[0] for g in nulls[1:]])), m


def part1(series: int, bars: int, reps: int, ex: ProcessPoolExecutor) -> list[str]:
    L = [f"== Part 1: bar words against the null - {series} series x {bars} bars, R = {reps}", ""]
    for comp, nk in NULLS.items():
        src = comp.split("|")[0]
        seeds = [10_000 * (list(SOURCES).index(src) + 1) + i for i in range(series)]
        data = list(ex.map(_job, [("data", src, bars, s, 0) for s in seeds]))
        nulls = [list(ex.map(_job, [(nk, src, bars, s, r) for s in seeds])) for r in range(reps + 1)]
        L.append(f"-- {comp} against matched {nk} (null)")
        L.append("   alphabet   symbols   KL n=1 [null median / max] p     n=2 [..] p      n=3 p    k=1 p   k=2 p")
        reps_ = {}
        for a in candles.ALPHABETS:
            big = a in ("full", "full+s", "points")  # thousands of words: KL only, orders 1-2
            rep = compare([d["streams"][a] for d in data], [[g["streams"][a] for g in nl] for nl in nulls],
                          max_n=2 if big else 3, max_k=1 if big else 2, top=not big)
            reps_[a] = rep
            syms = len({x for d in data for x in d["streams"][a]})
            r1, r2 = rep["n"][1], rep["n"][2]
            p3 = f"{rep['n'][3]['p']:.3f}" if 3 in rep["n"] else "  -  "
            pk2 = f"{rep['k'][2]['p']:.3f}" if 2 in rep["k"] else "  -  "
            L.append(f"   {a:<9} {syms:>6}   {r1['kl']:.5f} [{np.median(r1['null_kl']):.5f}/{max(r1['null_kl']):.5f}] "
                     f"{r1['p']:.3f}   {r2['kl']:.4f} [{np.median(r2['null_kl']):.4f}/{max(r2['null_kl']):.4f}] "
                     f"{r2['p']:.3f}   {p3}   {rep['k'][1]['p']:.3f}   {pk2}")
        for a in ("coarse", "coarse+s", "rel"):
            rep = reps_[a]
            for n in (1, 2, 3):
                L.append(f"   [{a}] largest {n}-gram differences (per 1,000 words: data / null / z)")
                for g, x, m, z in rep["n"][n]["top"][:TOP]:
                    L.append(f"     {g:<44} {x:8.2f} {m:8.2f} {z:+7.1f}")
            L.append(f"   [{a}] largest P(next | last 1) differences (data / null / z)")
            for ctx, t, x, m, z in rep["k"][1]["top"][:TOP]:
                L.append(f"     {ctx:<20} -> {t:<14} {x:6.3f} {m:6.3f} {z:+7.1f}")
        rows = _rates(data, nulls, "names", "name_bars", NAMES)
        L.append("   named point relations, per 1,000 bars (data / null / z):")
        for k, x, m, z in rows:
            L.append(f"     {k:<24} {x:8.1f} {m:8.1f} {z:+7.1f}")
        keys = sorted({k for d in data + [g for nl in nulls for g in nl] for k in d["patterns"]})
        L.append("   candle productions per 1,000 bars (data / null / z), and P(next bar goes its way): data / null [n]")
        for k, x, m, z in _rates(data, nulls, "patterns", "bars", keys):
            px, pm, cnt = _next(data, nulls, k)
            L.append(f"     {k:<18} {x:8.2f} {m:8.2f} {z:+7.1f}     {px:.3f} / {pm:.3f} [{cnt}]")
        L.append("")
        print(f"  part 1: {comp} done", flush=True)
    return L


# ---------------------------------------------------------------- part 2: full parses

def _parse_job(job: tuple) -> dict:
    from mcfl.parse import parse
    src, n, s = job
    ch = parse(SOURCES[src](n, s))
    ids = ch.by_id()
    rev = ch.of("REVISIT")
    rej = {e.get("revisit") for e in ch.of("REJECT")}
    path = {(e.get("zone"), e.get("count")) for e in ch.of("REJECT_PATH")}
    fail_after = {}
    for e in ch.of("FAIL", "ACCEPT"):
        fail_after[e.get("zone"), e.get("count")] = e.type
    tab = Counter()
    for r in rev:
        a = r.id in rej
        b = (r.get("zone"), r.get("count")) in path
        tab[a, b] += 1
        tab["end", a, fail_after.get((r.get("zone"), r.get("count")), "none")] += 1
    # DISPLACE_C against v0's DISPLACE: each covered by the other, and the share of bars covered
    disp = ch.of("DISPLACE")
    dc = ch.of("DISPLACE_C")
    spans = {d: set() for d in ("UP", "DOWN")}
    for e in disp:
        o = ids[e.get("origin")]
        spans[e.dir.value].update(range(o.at, e.at + 1))
    dc_at = {d: {e.at for e in dc if e.dir.value == d} for d in ("UP", "DOWN")}
    disp_hit = sum(any(t in dc_at[e.dir.value] for t in range(ids[e.get("origin")].at, e.at + 1)) for e in disp)
    dc_hit = sum(e.at in spans[e.dir.value] for e in dc)
    conf = sum(t.dst == "CONFIRMED" for t in ch.transitions)
    return {"tab": tab, "n": ch.n, "disp": len(disp), "disp_bars": len({(e.dir, e.at) for e in disp}),
            "dc": len(dc), "disp_hit": disp_hit, "dc_hit": dc_hit,
            "cover": (len(spans["UP"]) + len(spans["DOWN"])) / (2 * ch.n), "revisits": len(rev), "confirmed": conf,
            "dc_rules": Counter(e.get("rule") for e in dc)}


def part2(series: int, bars: int, ex: ProcessPoolExecutor) -> list[str]:
    L = [f"== Part 2: full parses - {series} series x {bars} bars", ""]
    for src in ("walk", "garch", "trend"):
        seeds = [10_000 * (list(SOURCES).index(src) + 1) + i for i in range(series)]
        res = list(ex.map(_parse_job, [(src, bars, s) for s in seeds]))
        tab = sum((r["tab"] for r in res), Counter())
        nrev = sum(r["revisits"] for r in res)
        a11, a10, a01, a00 = tab[True, True], tab[True, False], tab[False, True], tab[False, False]
        agree = (a11 + a00) / nrev
        pa, pb = (a11 + a10) / nrev, (a11 + a01) / nrev
        pe = pa * pb + (1 - pa) * (1 - pb)
        kappa = (agree - pe) / (1 - pe) if pe < 1 else float("nan")
        L.append(f"-- {src}: {nrev} revisits")
        L.append(f"   REJECT (candle) vs REJECT_PATH:  both {a11}  REJECT only {a10}  REJECT_PATH only {a01}  "
                 f"neither {a00}")
        L.append(f"   agreement {agree:.3f}, Cohen's kappa {kappa:.3f}; P(REJECT_PATH | REJECT) "
                 f"{a11 / max(a11 + a10, 1):.3f} vs P(REJECT_PATH | no REJECT) {a01 / max(a01 + a00, 1):.3f}")
        for a in (True, False):
            ends = {k[2]: v for k, v in tab.items() if isinstance(k, tuple) and len(k) == 3 and k[1] == a}
            tot = sum(ends.values())
            L.append(f"   after a revisit {'with' if a else 'without'} a REJECT: " + ", ".join(
                f"{k} {v / tot:.3f}" for k, v in sorted(ends.items())) + f"  [{tot}]  (FAIL/ACCEPT of that revisit)")
        nb = sum(r["n"] for r in res)
        disp, dc = sum(r["disp"] for r in res), sum(r["dc"] for r in res)
        L.append(f"   DISPLACE (v0, 2 ATR from an origin): {disp} events on {sum(r['disp_bars'] for r in res)} bars "
                 f"({1000 * sum(r['disp_bars'] for r in res) / nb:.1f} per 1,000 bars); DISPLACE_C: {dc} "
                 f"({1000 * dc / nb:.1f} per 1,000 bars; rules {dict(sum((r['dc_rules'] for r in res), Counter()))})")
        L.append(f"   share of DISPLACEs whose leg (origin..displace bar) holds a same-direction DISPLACE_C: "
                 f"{sum(r['disp_hit'] for r in res) / max(disp, 1):.3f}")
        L.append(f"   share of DISPLACE_Cs inside a same-direction DISPLACE leg: {sum(r['dc_hit'] for r in res) / max(dc, 1):.3f}"
                 f"  (those legs cover {np.mean([r['cover'] for r in res]):.3f} of bars per direction)")
        L.append(f"   revisits CONFIRMED by a DELIVERY_SHIFT: {sum(r['confirmed'] for r in res)} of {nrev}")
        L.append("")
        print(f"  part 2: {src} done", flush=True)
    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", type=int, default=8)
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--parts", default="1,2")
    a = ap.parse_args()
    with ProcessPoolExecutor(a.workers) as ex:
        lines = [f"MCFL v1 candle layer against generated walks: {a.series} series x {a.bars} bars", ""]
        if "1" in a.parts:
            lines += part1(a.series, a.bars, a.reps, ex)
        if "2" in a.parts:
            lines += part2(a.series, a.bars, ex)
    text = "\n".join(lines)
    OUT.mkdir(exist_ok=True)
    path = OUT / ("candles.txt" if a.parts == "1,2" else f"candles_part{a.parts.replace(',', '')}.txt")
    path.write_text(text + "\n")
    print(text)
    print(f"written {path}")


if __name__ == "__main__":
    main()
