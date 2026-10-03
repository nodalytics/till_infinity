"""Count MCFL sentences and compare them with the same counts on walks we generate.

For each source series, the null is an iid Gaussian walk of the same length and the same
close-to-close volatility (`synth.matched_walk`), parsed the same way. R + 1 independent null sets
are drawn. The data is compared with the pool of R of them; each null set is compared with the
pool of the other R, which is how big the divergence is when there is nothing to find. A KL
divergence is only read against that spread - with sparse 4-grams it is never zero.

Reported per order n = 1..4 and per context length k = 1..3:
  KL(data || null pool) in bits, the null's own leave-one-out KLs, and the share of them at least
  as large (an empirical p, floored at 1 / (R + 1));
  the n-grams and next-token probabilities furthest from the null, as z-scores against the spread
  of the R null sets.

  python research/mcfl/ngrams.py [--series 8] [--bars 5000] [--reps 10] [--bins]
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcfl import synth
from mcfl.parse import parse
from mcfl.serialise import tokens

OUT = Path(__file__).resolve().parent / "out"
ALPHA = 0.5
"""Additive smoothing for KL over the union of n-grams seen anywhere (Jeffreys' prior)."""
MIN_COUNT = 30
"""An n-gram or context is ranked only with at least this many in the data plus the null mean."""
TOP = 12
"""Rows of each table of largest differences."""

Stream = list[str]


# ---------------------------------------------------------------- counting

def ngrams(streams: Iterable[Stream], n: int) -> Counter:
    """n-grams inside each stream; none spans two series."""
    c: Counter = Counter()
    for s in streams:
        for i in range(len(s) - n + 1):
            c[tuple(s[i:i + n])] += 1
    return c


def next_counts(streams: Iterable[Stream], k: int) -> dict[tuple, Counter]:
    """For each context of the last k tokens, the counts of the token that followed."""
    out: dict[tuple, Counter] = {}
    for g, m in ngrams(streams, k + 1).items():
        out.setdefault(g[:-1], Counter())[g[-1]] += m
    return out


def next_probs(streams: Iterable[Stream], k: int) -> dict[tuple, dict[str, float]]:
    """P(next token | last k tokens), by counting."""
    return {ctx: {t: m / sum(c.values()) for t, m in c.items()} for ctx, c in next_counts(streams, k).items()}


def kl(p: Counter, q: Counter, alpha: float = ALPHA, support: set | None = None) -> float:
    """KL(p || q) in bits between two count tables, smoothed over their joint support."""
    keys = set(p) | set(q) if support is None else support
    if not keys:
        return 0.0
    np_, nq = sum(p.values()) + alpha * len(keys), sum(q.values()) + alpha * len(keys)
    out = 0.0
    for x in keys:
        px = (p[x] + alpha) / np_
        if px > 0:  # 0 log 0 = 0
            out += px * math.log2(px / ((q[x] + alpha) / nq))
    return float(out)


def cond_kl(p: dict[tuple, Counter], q: dict[tuple, Counter], alpha: float = ALPHA) -> float:
    """Sum over contexts of P_data(context) * KL(next | context): how differently sentences continue."""
    tokens_ = {t for c in list(p.values()) + list(q.values()) for t in c}
    total = sum(sum(c.values()) for c in p.values())
    if not total:
        return 0.0
    return sum(sum(c.values()) / total * kl(c, q.get(ctx, Counter()), alpha, tokens_) for ctx, c in p.items())


def pool(groups: Sequence[list[Stream]]) -> list[Stream]:
    return [s for g in groups for s in g]


# ---------------------------------------------------------------- the comparison

def compare(data: list[Stream], nulls: list[list[Stream]], max_n: int = 4, max_k: int = 3) -> dict:
    """`nulls` is R + 1 null sets, each matched to `data` series for series."""
    R = len(nulls) - 1
    pool_d = pool(nulls[1:])
    rep: dict = {"R": R, "tokens": sum(map(len, data)), "null_tokens": sum(map(len, pool_d)) / R, "n": {}, "k": {}}
    for n in range(1, max_n + 1):
        d = ngrams(data, n)
        reps = [ngrams(g, n) for g in nulls]
        obs = kl(d, ngrams(pool_d, n))
        loo = [kl(reps[i], sum((reps[j] for j in range(R + 1) if j != i), Counter())) for i in range(R + 1)]
        rep["n"][n] = {"kl": obs, "null_kl": loo, "p": (1 + sum(x >= obs for x in loo)) / (R + 2),
                       "top": _top_ngrams(d, reps[1:], sum(map(len, data)), [sum(map(len, g)) for g in nulls[1:]])}
    for k in range(1, max_k + 1):
        d = next_counts(data, k)
        reps = [next_counts(g, k) for g in nulls]

        def merged(idx: Iterable[int]) -> dict[tuple, Counter]:
            out: dict[tuple, Counter] = {}
            for i in idx:
                for ctx, c in reps[i].items():
                    out.setdefault(ctx, Counter()).update(c)
            return out
        obs = cond_kl(d, merged(range(1, R + 1)))
        loo = [cond_kl(reps[i], merged(j for j in range(R + 1) if j != i)) for i in range(R + 1)]
        rep["k"][k] = {"kl": obs, "null_kl": loo, "p": (1 + sum(x >= obs for x in loo)) / (R + 2),
                       "top": _top_next(d, reps[1:])}
    return rep


def _z(x: float, xs: list[float], floor: float) -> float:
    sd = max(float(np.std(xs, ddof=1)), floor)
    return (x - float(np.mean(xs))) / sd


def _top_ngrams(d: Counter, reps: list[Counter], nd: int, nr: list[int]) -> list[tuple]:
    """Rate per 1,000 tokens in the data against the null sets' rates."""
    rows = []
    for g in set(d) | {g for r in reps for g in r}:
        rates = [1000 * r[g] / t for r, t in zip(reps, nr)]
        mean_count = float(np.mean([r[g] for r in reps]))
        if d[g] + mean_count < MIN_COUNT:
            continue
        x = 1000 * d[g] / nd
        floor = 1000 * math.sqrt(max(mean_count, 1.0)) / float(np.mean(nr))  # Poisson, when the reps agree
        rows.append((" ".join(g), x, float(np.mean(rates)), _z(x, rates, floor)))
    return sorted(rows, key=lambda r: -abs(r[3]))


def _top_next(d: dict[tuple, Counter], reps: list[dict[tuple, Counter]]) -> list[tuple]:
    """P(next | context) in the data against the null sets', for contexts seen often enough."""
    rows = []
    for ctx, c in d.items():
        nc = sum(c.values())
        if nc < MIN_COUNT:
            continue
        for t in c.keys() | {t for r in reps for t in r.get(ctx, {})}:
            ps = [r.get(ctx, Counter())[t] / max(sum(r.get(ctx, Counter()).values()), 1) for r in reps]
            x = c[t] / nc
            pbar = (x + float(np.mean(ps))) / 2
            floor = math.sqrt(max(pbar * (1 - pbar), 1 / nc) / nc)  # binomial, when the reps agree
            rows.append((" ".join(ctx), t, x, float(np.mean(ps)), _z(x, ps, floor)))
    return sorted(rows, key=lambda r: -abs(r[4]))[:TOP]


# ---------------------------------------------------------------- runs

SOURCES = {
    "walk": lambda n, s: synth.walk(n, seed=s),
    "garch": lambda n, s: synth.garch(n, seed=s),
    "trend": lambda n, s: synth.trend(n, seed=s),
}


def _stream(job: tuple) -> Stream:
    kind, n, seed, bins = job
    if kind == "null":
        src, s, rep = seed
        df = synth.matched_walk(SOURCES[src](n, s), seed=1_000_003 * (rep + 1) + s)
    else:
        df = SOURCES[kind](n, seed)
    return tokens(parse(df), bins=bins)


def run(sources: Sequence[str], series: int, bars: int, reps: int, bins: bool, workers: int = 8) -> dict:
    out = {}
    with ProcessPoolExecutor(workers) as ex:
        for src in sources:
            seeds = [10_000 * (list(SOURCES).index(src) + 1) + i for i in range(series)]
            data = list(ex.map(_stream, [(src, bars, s, bins) for s in seeds]))
            nulls = [list(ex.map(_stream, [("null", bars, (src, s, r), bins) for s in seeds])) for r in range(reps + 1)]
            out[src] = compare(data, nulls)
            print(f"  {src}: {out[src]['tokens']} tokens", flush=True)
    return out


def report(res: dict, series: int, bars: int, bins: bool) -> str:
    L = [f"MCFL v0 n-grams against matched iid walks: {series} series x {bars} bars per source, "
         f"bins={'on' if bins else 'off'}", ""]
    for src, rep in res.items():
        L.append(f"== {src}  (data {rep['tokens']} tokens, each null set {rep['null_tokens']:.0f}; R = {rep['R']})")
        L.append("   order   KL data||null (bits)   null LOO KL median [max]   p")
        for n, r in rep["n"].items():
            L.append(f"   n={n}     {r['kl']:.5f}               {np.median(r['null_kl']):.5f} [{max(r['null_kl']):.5f}]"
                     f"        {r['p']:.3f}")
        for k, r in rep["k"].items():
            L.append(f"   k={k}|    {r['kl']:.5f}               {np.median(r['null_kl']):.5f} [{max(r['null_kl']):.5f}]"
                     f"        {r['p']:.3f}")
        L.append("   unigram rates per 1,000 tokens (data / null mean / z):")
        for g, x, m, z in sorted(rep["n"][1]["top"], key=lambda r: r[0]):
            L.append(f"     {g:<28} {x:8.2f} {m:8.2f} {z:+7.1f}")
        for n in (2, 3, 4):
            L.append(f"   largest {n}-gram differences (rate per 1,000 tokens, data / null / z):")
            for g, x, m, z in rep["n"][n]["top"][:TOP]:
                L.append(f"     {g:<60} {x:8.2f} {m:8.2f} {z:+7.1f}")
        for k in (1, 2):
            L.append(f"   largest P(next | last {k}) differences (data / null / z):")
            for ctx, t, x, m, z in rep["k"][k]["top"][:TOP]:
                L.append(f"     {ctx:<40} -> {t:<18} {x:6.3f} {m:6.3f} {z:+7.1f}")
        L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", type=int, default=8)
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--bins", action="store_true")
    ap.add_argument("--sources", default="walk,garch,trend")
    a = ap.parse_args()
    res = run(a.sources.split(","), a.series, a.bars, a.reps, a.bins)
    text = report(res, a.series, a.bars, a.bins)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"ngrams{'_bins' if a.bins else ''}.txt"
    path.write_text(text + "\n")
    print(text)
    print(f"written {path}")


if __name__ == "__main__":
    main()
