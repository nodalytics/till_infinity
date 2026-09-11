"""Can the next tick be predicted before it prints?

Not its distribution - that is settled - but the value. This is the last route by
which the generated 72% of this book could ever pay, and the prior is strongly
that it closes negative: Deriv is regulated, audits its generator, and a
cryptographic source is unpredictable from its outputs by construction. So the
job here is to write that null *well*, with the sample size named, and to be
explicit about which attacks the data had the power to run and which it did not.
"We found nothing" and "we could not have found anything" are different
sentences and this page separates them.

Five rungs, in increasing ambition.

1. **Structure in k-tuples.** The empirical spectral test from
   `rebuildjudge.py`, pushed to k = 2, 3, 4 with a wider integer search. A sound
   generator shows nothing; a linear congruential source puts its k-tuples on a
   small family of hyperplanes and the projection finds them. The controls are
   already calibrated - RANDU reads 2,616x where numpy's PCG64 reads 2.11.
2. **Mersenne Twister state recovery.** MT19937 is not cryptographically secure:
   624 consecutive 32-bit outputs determine the state exactly, by untempering.
   **This requires whole words.** Section one computes how many bits a tick
   actually carries, and if that is under 32 the attack is impossible rather
   than merely unsuccessful - which is the honest thing to report.
3. **Truncated LCG recovery.** The realistic case: each tick shows only the top
   few bits of whatever was drawn, because the quote is quantised. Truncated
   LCGs fall to lattice reduction on consecutive outputs, and the number of
   outputs needed is about `modulus bits / observed bits`. Rung 1 is the
   detector for a *grossly* broken source and no more: its own positive control
   says so. RANDU reads 2,616x there, and a 48-bit LCG truncated to ten bits -
   the realistic case - reads 2.84 against numpy's 1.54, which is inside the 3x
   bar. **A clean rung 1 therefore does not exclude the family rung 3 attacks**,
   which is why rung 3 is run rather than argued away.
   The attack runs against a catalogue of nine published parameter sets and needs
   the *leading bits of the draw*, not a rank - so the observed word is read off
   the exact inverse-normal interval the quote pins the uniform to, and a tick
   whose interval straddles a bit boundary is discarded rather than guessed.
4. **The joint stream, which is the angle specific to this venue.**
   `twins.md` found **all sixteen synthetics publish on one clock to within
   9ms**. If one stream feeds all sixteen then consecutive draws from it appear
   as *different feeds at the same tick index*, so a cross-feed tuple is a
   k-tuple of the underlying generator and the spectral test applies directly.
   Sixteen feeds is sixteen times the bits per unit time, and the cross-feed
   structure is itself the signature.
5. **A held-out forward prediction**, which is the only claim that counts. Fit on
   a prefix, predict the sign of the next tick on a held-out suffix, and report
   the AUC with its interval against the 0.5 null - both from a feed's own past
   and from all sixteen feeds at the same instant.

## What would count as failure, written before any number was looked at

1. **The null dies** if any k-tuple lattice ratio on a real feed exceeds **3x**
   what numpy's PCG64 produces on the same sample size, at k = 2, 3 or 4.
2. **The null dies** if the cross-feed test finds structure: a pairwise
   correlation of uniformised increments outside `+-4/sqrt(n)` on more pairs
   than chance allows, a two-dimensional grid chi-square below `0.001/pairs`
   after Bonferroni, or a cross-feed lattice ratio past the same 3x bar.
3. **The null dies** if the held-out classifier's AUC interval excludes 0.5 on
   the sign of the next tick, from either feature set.
4. **The null dies** if any parameter set in rung 3's catalogue recovers a real
   feed's generator state and that state then reproduces the observed words.
5. **The run is void** if the positive control is missed: a feed synthesised from
   a truncated LCG, quantised exactly as the real feed is, must be caught by
   rung 1, must be *recovered* by rung 3, and must be predicted above 0.5 by
   rung 5. A battery that cannot see a generator known to be broken says nothing
   about one that might be sound. Rung 3's control is run **per parameter set**,
   because the reduction's precision decides which moduli are attackable at all.
6. **The run is void** if an AUC lands on exactly 0.5000 or a lattice ratio on
   exactly its control's value - both are dead columns rather than nulls.
7. **A rung 5 AUC past 0.5 is not a finding on its own.** Range Break is a
   bounded walk and a bounded walk mean-reverts, so its next tick is partly
   predictable from its own past by construction. Every target is therefore run
   twice - once on the feed and once on the same family driven by numpy's PCG64 -
   and only an AUC clear of the rebuild's counts.
8. **Any rung the data cannot support is reported as untested**, with the
   arithmetic that says so, and is not counted as a pass.

## One thing this page will not do

If a rung bites, it is a finding about the product and about counterparty risk,
not a trading rule. Every set of terms permits voiding trades made against a
defective generator, so a position built on one is not bankable, and a venue
whose generator is predictable will discover it. The write-up is the deliverable
and the decision is the desk's.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuildgen as G
import rebuildjudge as J
import rebuildstep as S
import rebuildvol as V

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildpredict.json"))
SEED = int(os.environ.get("SEED", "20260912"))
KLAGS = int(os.environ.get("KLAGS", "8"))
TREES = int(os.environ.get("TREES", "150"))
MAXROW = int(os.environ.get("MAXROW", "80000"))

SYNTH = list(V.NOMINAL) + list(V.JUMP_NOMINAL) + [
    "boom_300_index", "boom_500_index", "boom_1000_index",
    "crash_300_index", "crash_500_index", "crash_1000_index",
    "step_index", "range_break_100_index", "range_break_200_index",
]


def bits_per_tick(mid: np.ndarray, grid: float) -> dict:
    """How much of the underlying draw a single quote reveals.

    A discretised variate of standard deviation `s` lattice units carries about
    `log2(s * sqrt(2*pi*e))` bits. That number decides rungs 2 and 3 before
    either is run: untempering MT19937 needs whole 32-bit words, and a truncated
    LCG of an `n`-bit modulus needs roughly `n / bits` consecutive outputs.
    """
    d = np.diff(mid)
    if grid > 0:
        d = d / grid
    s = float(np.std(d))
    nz = float((d != 0).mean())
    bits = math.log2(s * math.sqrt(2 * math.pi * math.e)) if s > 0 else 0.0
    return {"sd_lattice": s, "bits": bits, "nonzero_frac": nz,
            "mt_words_needed": 624, "mt_ticks_needed": float("inf") if bits < 32
            else 624.0, "lcg48_ticks": 48.0 / bits if bits > 0 else float("inf")}


def trunc_lcg(n: int, bits_out: int, mod_bits: int = 48, a: int = 25214903917,
              c: int = 11, seed: int = 1) -> np.ndarray:
    """java.util.Random's LCG, truncated to `bits_out` observable bits.

    The positive control for rungs 1, 3 and 5: a generator that is known to be
    breakable, quantised the way a real quote is.
    """
    m = 1 << mod_bits
    x = seed
    out = np.empty(n, dtype=np.float64)
    shift = mod_bits - bits_out
    for i in range(n):
        x = (a * x + c) % m
        out[i] = (x >> shift) / (1 << bits_out)
    return out


#: Published LCG parameter sets, as (name, multiplier, increment, modulus bits).
#: Rung 3 attacks a *named* generator: recovering the multiplier as well as the
#: seed from truncated outputs is a different and much harder problem, and rung 1
#: is the detector for the family as a whole. So a clean rung 3 excludes these
#: nine and not every LCG there is.
LCG_CATALOGUE = [
    ("java.util.Random", 25214903917, 11, 48),
    ("glibc TYPE_0", 1103515245, 12345, 31),
    ("MINSTD (16807)", 16807, 0, 31),
    ("MINSTD (48271)", 48271, 0, 31),
    ("Numerical Recipes", 1664525, 1013904223, 32),
    ("Borland C", 22695477, 1, 32),
    ("MSVC", 214013, 2531011, 32),
    ("RANDU", 65539, 0, 31),
    ("MMIX (Knuth)", 6364136223846793005, 1442695040888963407, 64),
]


def _gso(b: np.ndarray):
    n = b.shape[0]
    bs = np.zeros_like(b)
    mu = np.zeros((n, n))
    nrm = np.zeros(n)
    for i in range(n):
        v = b[i].copy()
        for j in range(i):
            if nrm[j] > 0:
                mu[i, j] = float(b[i] @ bs[j]) / nrm[j]
                v = v - mu[i, j] * bs[j]
        bs[i] = v
        nrm[i] = float(v @ v)
    return bs, mu, nrm


def lll(basis: np.ndarray, delta: float = 0.99, max_steps: int = 4000) -> np.ndarray:
    """Lenstra-Lenstra-Lovasz reduction, in whatever float type it is handed.

    Called with `np.longdouble` for a 64-bit modulus, where float64's 53-bit
    mantissa loses the reduction outright - the MMIX entry in the catalogue is
    *not* recovered in double precision and is in extended, which is why the
    positive control is run per parameter set rather than once.
    """
    b = np.array(basis, dtype=basis.dtype)
    n = b.shape[0]
    bs, mu, nrm = _gso(b)
    k, steps = 1, 0
    while k < n and steps < max_steps:
        steps += 1
        for j in range(k - 1, -1, -1):
            r = np.round(mu[k, j])
            if r:
                b[k] = b[k] - r * b[j]
                bs, mu, nrm = _gso(b)
        if nrm[k] >= (delta - mu[k, k - 1] ** 2) * nrm[k - 1]:
            k += 1
        else:
            b[[k, k - 1]] = b[[k - 1, k]]
            bs, mu, nrm = _gso(b)
            k = max(k - 1, 1)
    return b


def babai(basis: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Nearest plane: the lattice vector closest to `target`."""
    bs, _mu, nrm = _gso(basis)
    n = basis.shape[0]
    w = np.array(target, dtype=basis.dtype)
    out = np.zeros(n, dtype=basis.dtype)
    for i in range(n - 1, -1, -1):
        if nrm[i] <= 0:
            continue
        r = np.round(float(w @ bs[i]) / nrm[i])
        w = w - r * basis[i]
        out = out + r * basis[i]
    return out


def lcg_recover(y, bits_out: int, a: int, c: int, mod_bits: int, dtype=np.float64):
    """Recover an LCG's state from the top `bits_out` bits of consecutive outputs.

    `x_i = A_i x_0 + C_i (mod m)` with `A_i`, `C_i` known, and each observation
    pins `x_i` to a window of `2^s`. Eliminating `x_0` in favour of
    `u = x_1 - (centre of its window)` leaves the hidden number problem
    `D_i u - S_i = small (mod m)`, whose lattice has every unknown the same size -
    which is what lets Babai on an LLL-reduced basis find it. Returns the
    recovered seed, or None, and **None is only meaningful beside a positive
    control on the same parameter set**: a failure can be the precision of the
    reduction rather than the soundness of the source.
    """
    m = 1 << mod_bits
    s = mod_bits - bits_out
    k = len(y)
    if k < 3 or s < 1:
        return None
    A, C = [], []
    ai, ci = 1, 0
    for _ in range(k):
        ai = (ai * a) % m
        ci = (ci * a + c) % m
        A.append(ai)
        C.append(ci)
    half = 1 << (s - 1)
    T = [(((int(y[i]) << s) + half) - C[i]) % m for i in range(k)]
    try:
        inv1 = pow(A[0], -1, m)
    except ValueError:
        return None
    D = [(A[i] * inv1) % m for i in range(k)]
    Sv = [(T[i] - D[i] * T[0]) % m for i in range(1, k)]
    basis = np.zeros((k, k), dtype=dtype)
    for j in range(k - 1):
        basis[j, j] = dtype(m)
    for i in range(1, k):
        basis[k - 1, i - 1] = dtype(D[i])
    basis[k - 1, k - 1] = dtype(1)
    tgt = np.array([dtype(x) for x in Sv] + [dtype(0)], dtype=dtype)
    u = int(round(float(babai(lll(basis), tgt)[-1])))
    for shift in (0, m, -m):
        x0 = ((T[0] + u + shift) % m) * inv1 % m
        x = x0
        ok = True
        for i in range(k):
            x = (a * x + c) % m
            if (x >> s) != int(y[i]):
                ok = False
                break
        if ok:
            return x0
    return None


def observed_words(mid: np.ndarray, grid: float, sigma_tick: float, bits: int):
    """The top `bits` bits of the draw behind each tick, where they are certain.

    The attack needs the leading bits of the generator's *output*, not a rank.
    If the venue draws one uniform and maps it through the inverse normal - which
    is the assumption, and Box-Muller or a ziggurat breaks it - then an observed
    lattice increment `k` says only that the uniform lay in
    `[Phi((k-0.5)g/s), Phi((k+0.5)g/s)]`. The leading bits are determined exactly
    when that interval lies inside one `2^-bits` cell, and the tick is discarded
    when it straddles a boundary. This is what makes the rung testable at all:
    a rank transform recovers the uniform only to `O(1/sqrt(n))` and its leading
    bits are then wrong about a third of the time, which fails the positive
    control and would have been read as a clean feed.
    """
    from scipy.special import ndtr
    d = np.diff(np.asarray(mid, dtype=float))
    sl = np.asarray(mid[:-1], dtype=float) * sigma_tick
    kk = np.round(d / grid)
    lo = ndtr((kk - 0.5) * grid / np.maximum(sl, 1e-300))
    hi = ndtr((kk + 0.5) * grid / np.maximum(sl, 1e-300))
    scale = float(1 << bits)
    wl = np.floor(lo * scale)
    wh = np.floor(hi * scale)
    ok = (wl == wh) & (wl >= 0) & (wl < scale)
    return wl.astype(np.int64), ok


def align(feeds: list[str], slot_ms: int) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Line the feeds up by publication slot.

    `twins.md` measured all sixteen synthetics publishing on one clock to within
    9ms, so flooring the timestamp to the slot is enough to put the same draw
    index beside itself across feeds. Only slots where every feed printed are
    kept, which is what makes a cross-feed tuple a tuple of one stream if there
    is one stream.
    """
    per = {}
    for f in feeds:
        t = G.real_ticks(f)
        if not t.get("n"):
            continue
        slot = t["ts"] // slot_ms
        uniq, first = np.unique(slot, return_index=True)
        per[f] = (uniq, t["mid"][first])
    if len(per) < 2:
        return [], np.empty((0, 0)), np.empty(0)
    common = None
    for f, (u, _m) in per.items():
        common = u if common is None else np.intersect1d(common, u, assume_unique=True)
    rows = []
    names = []
    for f, (u, m) in per.items():
        idx = np.searchsorted(u, common)
        rows.append(m[idx])
        names.append(f)
    return names, np.array(rows), common


def forward_auc(x: np.ndarray, y: np.ndarray, names: list[str], seed: int,
                frac: float = 0.6, boots: int = 400) -> dict:
    """Fit on the first `frac` of time, predict the rest. Nothing else will do.

    The generic `discriminate` splits by interleaved blocks of *row index*, which
    is right for telling two samples apart and wrong for a forecast: the two
    label groups interleave in time, so a block split puts a test row between two
    training rows minutes away and any local structure leaks straight across it.
    The first version of this harness did that and read 0.4938 with an interval
    excluding 0.5, which is the leak rather than a prediction.
    """
    n = x.shape[0]
    if n < 2000 or y.sum() < 200 or (n - y.sum()) < 200:
        return {"n": n, "auc": float("nan"), "skipped": "too few rows or one-sided"}
    cut = int(n * frac)
    tr, te = slice(0, cut), slice(cut, n)
    if y[te].sum() < 100 or (y[te].size - y[te].sum()) < 100:
        return {"n": n, "auc": float("nan"), "skipped": "test side one-sided"}
    x = np.clip(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0), -1e12, 1e12)
    model = G._Booster(seed=seed, n_trees=TREES).fit(x[tr], y[tr])
    sc = model.decision(x[te])
    a = G.auc(sc, y[te])
    rng = np.random.default_rng(seed + 1)
    idx = np.arange(sc.size)
    boot = [G.auc(sc[t], y[te][t]) for t in
            (rng.choice(idx, idx.size, replace=True) for _ in range(boots))]
    boot = [v for v in boot if v == v]
    lo, hi = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))) \
        if boot else (float("nan"), float("nan"))
    uni = sorted(((names[j], G.auc(x[te][:, j], y[te])) for j in range(len(names))),
                 key=lambda t: -abs(t[1] - 0.5))
    return {"n": int(n), "n_test": int(sc.size), "auc": a, "lo": lo, "hi": hi,
            "univariate": uni[:5]}


def rebuild_ticks(feed: str, n: int, seed: int) -> np.ndarray:
    """The same family, driven by numpy's PCG64 - the control rung 5 needs.

    An AUC above 0.5 on the sign of the next tick is not evidence of a
    predictable generator until the same test is run on a stream whose source is
    unpredictable by construction. Range Break is a bounded walk and a bounded
    walk mean-reverts, so its next tick *is* partly predictable from its own past
    and always was: that is the published mechanism, not a leak. Without this
    control the first version of this section reported a Range Break AUC of
    0.5191 as though it said something about the RNG.
    """
    rb, rt = G.real_bars(feed), G.real_ticks(feed)
    if not rb.get("n") or not rt.get("n"):
        return np.empty(0)
    p0 = float(rb["close"][0])
    if feed in V.NOMINAL:
        tpb = V.ticks_per_bar(feed)
        bb = V.simulate_vol(feed, V.NOMINAL[feed], p0, G.quote_grid(rt["mid"]),
                            max(rb["n"], n // tpb + 4), seed, keep_ticks=n + 4)
        return bb["ticks"]
    if feed == "step_index":
        return S.sim_step(max(rb["n"], n // S.TPB + 4), 0.5, seed, p0)["ticks"]
    if feed in V.JUMP_NOMINAL:
        nom = V.JUMP_NOMINAL[feed]
        d = np.diff(rt["mid"])
        jmed = float(np.median(np.abs(d[d != 0])))
        idx = np.flatnonzero(np.abs(d) > 10 * jmed)
        span = (rt["ts"][-1] - rt["ts"][0]) / 60000.0
        rate = max(idx.size / span, 1e-6)
        sig = (nom / 100.0) / math.sqrt(G.MINUTES_PER_YEAR)
        js = math.sqrt(0.7477 * sig ** 2 / rate)
        return G.bars_from_stream(
            G.gen_jump(n + 120, nom, 1.0, rate, js, p0, G.quote_grid(rt["mid"]),
                       np.random.default_rng([seed, G.feed_seed(feed)])),
            60, max(rb["n"], n // 60 + 4), keep_ticks=n + 4)["ticks"]
    if feed.startswith("range_break"):
        d = np.diff(rt["mid"])
        stp = float(np.median(np.abs(d[d != 0])))
        brk = S.break_stats(rb, stp)
        vis = S.visited_ranges(rb, stp)
        mbt = brk["minutes_per_break"] * S.TPB
        band, _m, _k = S.fit_band(vis, mbt, brk["_jump"], p0, stp, seed)
        return S.sim_rb(max(rb["n"], n // S.TPB + 4), band, mbt, brk["_jump"], seed,
                        p0, stp, "edge")["ticks"]
    return np.empty(0)


def sign_features(u: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Rows of `k` past increments, label = the sign of the next one."""
    d = np.diff(u)
    n = d.size - k
    if n < 500:
        return np.empty((0, 0)), np.empty(0), []
    x = np.lib.stride_tricks.sliding_window_view(d[:-1], k)[:n]
    y = (d[k:k + n] > 0).astype(float)
    return np.ascontiguousarray(x), y, [f"lag{i}" for i in range(k, 0, -1)]


def main() -> None:
    rng = np.random.default_rng(SEED)
    ledger: list[dict] = []
    payload: dict = {}
    print("=" * 120)
    print("CAN THE NEXT TICK BE PREDICTED BEFORE IT PRINTS?")
    print(f"  seed {SEED}   {G.machine()}")
    print("=" * 120)

    # ------------------------------------------------- how many bits a tick is --
    print("\n[1] HOW MUCH OF THE DRAW A TICK SHOWS - this decides which rungs are possible")
    print("    A discretised variate of sd `s` lattice units carries log2(s*sqrt(2*pi*e))")
    print("    bits. MT19937 untempering needs whole 32-bit words; a truncated LCG of an")
    print("    n-bit modulus needs about n/bits consecutive outputs.")
    print(f"{'feed':26s} {'grid':>10s} {'sd (lattice)':>13s} {'bits/tick':>10s} "
          f"{'ticks for a 48-bit LCG':>23s} {'MT possible':>12s}")
    bits = {}
    for feed in SYNTH:
        t = G.real_ticks(feed)
        if not t.get("n"):
            continue
        grid = G.quote_grid(t["mid"])
        b = bits_per_tick(t["mid"], grid)
        bits[feed] = b
        print(f"{feed:26s} {grid:10.6g} {b['sd_lattice']:13.2f} {b['bits']:10.2f} "
              f"{b['lcg48_ticks']:23.1f} {'no' if b['bits'] < 32 else 'yes':>12s}")
    payload["bits"] = bits
    best = max(bits.values(), key=lambda b: b["bits"]) if bits else {"bits": 0}
    print(f"\n    the richest feed carries {best['bits']:.2f} bits a tick, against the 32 a")
    print("    Mersenne Twister untempering needs. **Rung 2 is impossible on this data**")
    print("    and is reported as untested rather than as a pass.")
    print(f"    A 48-bit truncated LCG would need about {48 / max(best['bits'], 1e-9):.0f} "
          "consecutive ticks, which the sample has many times over - so rung 3's")
    print("    hypothesis is testable, and rung 1 is its detector.")
    ledger.append({"test": "rung 2 (MT untempering) is possible on this data",
                   "feed": "all", "value": best["bits"], "fired": False,
                   "note": "untested - needs 32 bits a tick"})

    # ------------------------------------------------------- rung 1: lattices --
    print("\n[2] RUNG 1 - k-TUPLE LATTICE STRUCTURE IN EACH FEED'S OWN INCREMENTS")
    print("    Ratio is the largest empty band in a projected k-tuple grid, in units of")
    print("    the ln(n)/n a genuine uniform stream gives. Controls first.")
    ctl_u = rng.random(200_000)
    ctl_randu = J.randu(200_000)
    ctl_lcg = trunc_lcg(200_000, 10)
    rows = []
    for name, u in (("CONTROL numpy PCG64", ctl_u),
                    ("CONTROL RANDU", ctl_randu),
                    ("CONTROL 48-bit LCG, top 10 bits", ctl_lcg)):
        rows.append({"name": name, "n": u.size,
                     "lat": {k: J.lattice_gap(u, k, 12 if k == 2 else 10 if k == 3 else 6)
                             for k in (2, 3, 4)}})
    for feed in SYNTH:
        t = G.real_ticks(feed)
        if not t.get("n"):
            continue
        inc = np.diff(t["mid"]).astype(float)
        u = J.to_uniform(inc, rng)
        rows.append({"name": feed, "n": u.size,
                     "lat": {k: J.lattice_gap(u, k, 12 if k == 2 else 10 if k == 3 else 6)
                             for k in (2, 3, 4)}})
    pcg = rows[0]
    print(f"{'stream':32s} {'n':>8s} {'k=2':>9s} {'k=3':>9s} {'k=4':>9s} {'verdict':>10s}")
    for r in rows:
        vals = [r["lat"][k].get("ratio", float("nan")) for k in (2, 3, 4)]
        base = [pcg["lat"][k].get("ratio", 1.0) for k in (2, 3, 4)]
        hit = any(v > 3 * b for v, b in zip(vals, base, strict=False) if v == v)
        print(f"{r['name']:32s} {r['n']:8d} " + " ".join(f"{v:9.2f}" for v in vals)
              + f" {'STRUCTURE' if hit else '-':>10s}")
        if not r["name"].startswith("CONTROL"):
            ledger.append({"test": "no k-tuple lattice past 3x the PCG64 control",
                           "feed": r["name"], "value": max(v for v in vals if v == v),
                           "fired": hit})
    randu_hit = any(rows[1]["lat"][k].get("ratio", 0) > 3 * pcg["lat"][k].get("ratio", 1)
                    for k in (2, 3, 4))
    lcg_hit = any(rows[2]["lat"][k].get("ratio", 0) > 3 * pcg["lat"][k].get("ratio", 1)
                  for k in (2, 3, 4))
    ledger.append({"test": "VOID unless RANDU is caught", "feed": "control",
                   "value": rows[1]["lat"][3].get("ratio", 0), "fired": not randu_hit})
    ledger.append({"test": "VOID unless the truncated LCG is caught", "feed": "control",
                   "value": rows[2]["lat"][2].get("ratio", 0), "fired": not lcg_hit})
    payload["lattice"] = json.loads(json.dumps(rows, default=float))

    # ------------------------------------------------ rung 3: lattice recovery --
    print("\n[3] RUNG 3 - TRUNCATED-LCG RECOVERY BY LATTICE REDUCTION")
    print("    The budget first. Each tick shows the leading bits of one draw, and a")
    print("    truncated LCG of an n-bit modulus falls to lattice reduction on about")
    print("    n/bits consecutive outputs - so the attack is cheap if the bits are real.")
    print("    They are only real under one assumption, stated before any number: that")
    print("    the venue draws ONE uniform per tick and maps it through the inverse")
    print("    normal. Box-Muller or a ziggurat breaks that map and this rung then says")
    print("    nothing, which is why every parameter set carries its own positive")
    print("    control built the same way.")
    from scipy.special import ndtri

    def _synth(a, c, mod_bits, n, grid, sigma_tick, p0, seed=12345):
        """A feed whose every increment is one LCG draw through the inverse normal."""
        m = 1 << mod_bits
        x = seed % m
        price = p0
        out = np.empty(n)
        for i in range(n):
            x = (a * x + c) % m
            u = (x + 0.5) / m
            d = ndtri(u) * price * sigma_tick
            price += round(d / grid) * grid
            out[i] = price
        return out

    def _runs(ok, k, limit):
        idx, i, n = [], 0, ok.size
        while i + k <= n and len(idx) < limit:
            if ok[i:i + k].all():
                idx.append(i)
                i += k
            else:
                i += 1
        return idx

    bits_obs = int(os.environ.get("LCG_BITS", "8"))
    n_win = int(os.environ.get("LCG_WINDOWS", "40"))
    ref = "volatility_25_1s_index"
    rt = G.real_ticks(ref)
    ref_grid = G.quote_grid(rt["mid"])
    ref_sig = (25.0 / 100.0) / math.sqrt(G.MINUTES_PER_YEAR * 60)
    ref_p0 = float(np.median(rt["mid"]))
    print(f"\n    {'parameter set':22s} {'mod bits':>8s} {'k needed':>8s} "
          f"{'control recovered':>18s} {'usable windows':>15s} {'ms/attempt':>11s}")
    ctl_ok = {}
    for name, a, c, mb in LCG_CATALOGUE:
        k = max(6, math.ceil(mb / bits_obs) + 2)
        dt = np.longdouble if mb > 48 else np.float64
        syn = _synth(a, c, mb, 4000, ref_grid, ref_sig, ref_p0)
        w, ok = observed_words(syn, ref_grid, ref_sig, bits_obs)
        idx = _runs(ok, k, 6)
        t0 = time.time()
        hit = any(lcg_recover(w[i:i + k], bits_obs, a, c, mb, dt) is not None for i in idx)
        ms = 1000 * (time.time() - t0) / max(len(idx), 1)
        ctl_ok[name] = hit
        print(f"    {name:22s} {mb:8d} {k:8d} {str(hit):>18s} "
              f"{f'{len(idx)} of 6':>15s} {ms:11.1f}")
        ledger.append({"test": "VOID unless the LCG control is recovered", "feed": name,
                       "value": float(hit), "fired": not hit})
    live = [n for n, ok2 in ctl_ok.items() if ok2]
    print(f"\n    {len(live)} of {len(LCG_CATALOGUE)} parameter sets are attackable at "
          f"{bits_obs} observed bits on this")
    print("    machine's arithmetic; the rest are reported as untested rather than clean.")
    print(f"\n    {'feed':26s} {'bits/tick':>9s} {'usable windows':>14s} "
          f"{'sets tried':>10s} {'recovered':>10s}")
    # the Volatility family only: the attack maps one uniform through the inverse
    # normal, and a Jump index's marginal is a mixture, so its words would be
    # wrong for a reason that is about the marginal rather than about the source
    targets = [f for f in V.NOMINAL if bits.get(f, {}).get("bits", 0) >= 10.0]
    for feed in targets:
        t = G.real_ticks(feed)
        grid = G.quote_grid(t["mid"])
        nom = V.NOMINAL.get(feed) or V.JUMP_NOMINAL.get(feed)
        if not nom:
            continue
        sig = (nom / 100.0) / math.sqrt(G.MINUTES_PER_YEAR * V.ticks_per_bar(feed))
        w, ok = observed_words(t["mid"], grid, sig, bits_obs)
        found, tried, nwin = [], 0, 0
        for name, a, c, mb in LCG_CATALOGUE:
            if not ctl_ok[name]:
                continue
            k = max(6, math.ceil(mb / bits_obs) + 2)
            dt = np.longdouble if mb > 48 else np.float64
            idx = _runs(ok, k, n_win)
            nwin = max(nwin, len(idx))
            tried += 1
            for i in idx:
                if lcg_recover(w[i:i + k], bits_obs, a, c, mb, dt) is not None:
                    found.append((name, int(i)))
                    break
        print(f"    {feed:26s} {bits[feed]['bits']:9.2f} {nwin:14d} {tried:10d} "
              f"{len(found):10d}")
        ledger.append({"test": "no catalogue LCG recovers a real feed's state",
                       "feed": feed, "value": float(len(found)), "fired": bool(found)})
        payload.setdefault("rung3", {})[feed] = {"windows": nwin, "sets": tried,
                                                 "found": found}

    # --------------------------------------------------- rung 4: joint stream --
    from scipy.stats import chi2 as _chi2
    print("\n[4] RUNG 4 - THE JOINT STREAM, WHICH IS THE ANGLE SPECIFIC TO THIS VENUE")
    print("    twins.md: all sixteen synthetics publish on one clock to within 9ms. If one")
    print("    stream feeds them all, consecutive draws appear as different feeds at the")
    print("    same slot, and a cross-feed tuple is a k-tuple of that stream.")
    one_sec = [f for f in SYNTH if "_1s_" in f or f in
               ("step_index", "range_break_100_index", "range_break_200_index")
               or f.startswith("jump_")]
    names, mat, common = align(one_sec, 1000)
    if mat.size:
        inc = np.diff(mat, axis=1)
        n = inc.shape[1]
        uu = np.array([J.to_uniform(inc[i], rng) for i in range(inc.shape[0])])
        print(f"    {len(names)} feeds aligned on {n:,} common one-second slots")
        c = np.corrcoef(uu)
        iu = np.triu_indices(len(names), 1)
        band = 4.0 / math.sqrt(n)
        npast = int((np.abs(c[iu]) > band).sum())
        print(f"    pairwise correlation of uniformised increments at the same slot:")
        print(f"      largest |r| {np.abs(c[iu]).max():.5f}, mean {np.abs(c[iu]).mean():.5f}, "
              f"{npast} of {len(iu[0])} past +-4/sqrt(n) = {band:.5f} "
              f"(expected {0.0000633 * len(iu[0]):.2f})")
        # The grid chi-square needs a variable the rank transform can actually
        # make uniform. Step Index and the two Range Breaks move by exactly one
        # unit, so their increments are two atoms and an 8x8 grid rejects on the
        # marginal rather than on any dependence - it read p = 0 on exactly that
        # pair in the first run. Those feeds get a sign contingency test instead,
        # which is the right test for a binary stream.
        rich = [i for i in range(len(names))
                if np.unique(inc[i]).size >= 64]
        worst_p, worst_pair = 1.0, None
        pairs = [(a, b) for a in rich for b in rich if a < b]
        nb = max(2, len(pairs))
        for a, b in pairs:
            g = J.grid_chi2(np.column_stack([uu[a], uu[b]]).ravel(), 2, 8)
            if g.get("p", 1.0) < worst_p:
                worst_p, worst_pair = g["p"], (names[a], names[b])
        print(f"      worst 2-D grid chi-square over {nb} pairs of the {len(rich)} feeds")
        print(f"      with 64+ distinct increments: p = {worst_p:.3g} on {worst_pair}, "
              f"Bonferroni bar {0.001 / nb:.3g}")
        lat_idx = [i for i in range(len(names)) if i not in rich]
        worst_s, worst_sp = 1.0, None
        for a in lat_idx:
            for b in range(len(names)):
                if b == a:
                    continue
                sa = (inc[a] > 0).astype(np.int64)
                sb = (inc[b] > 0).astype(np.int64)
                tab = np.bincount(sa * 2 + sb, minlength=4).reshape(2, 2).astype(float)
                tot = tab.sum()
                exp = np.outer(tab.sum(1), tab.sum(0)) / tot
                st = float(((tab - exp) ** 2 / np.maximum(exp, 1e-9)).sum())
                pv = float(_chi2.sf(st, 1))
                if pv < worst_s:
                    worst_s, worst_sp = pv, (names[a], names[b])
        print(f"      the lattice feeds by sign contingency instead: worst p = "
              f"{worst_s:.3g} on {worst_sp}")
        # the cross-feed tuple: feeds in order at one slot, as a k-tuple
        flat = uu.T.ravel()
        cross = {k: J.lattice_gap(flat, k, 12 if k == 2 else 10 if k == 3 else 6)
                 for k in (2, 3, 4)}
        pcgr = [pcg["lat"][k].get("ratio", 1.0) for k in (2, 3, 4)]
        cv = [cross[k].get("ratio", float("nan")) for k in (2, 3, 4)]
        print(f"      cross-feed tuples read as one stream, lattice ratio: "
              + " ".join(f"k={k}:{v:.2f}" for k, v in zip((2, 3, 4), cv, strict=False))
              + f"  (PCG64 {pcgr[0]:.2f}/{pcgr[1]:.2f}/{pcgr[2]:.2f})")
        hit = any(v > 3 * b for v, b in zip(cv, pcgr, strict=False) if v == v)
        # THE CONTROL. Only 46,757 of 86,400 one-second slots survive the
        # intersection over fifteen feeds, so more than half of these aligned
        # increments are sums of two or more real increments - and *which* ones
        # is shared by every feed, because the mask is the intersection. That
        # manufactures dependence in |increment| and, on the lattice feeds, in
        # the sign indicator, with no shared state whatever. `twins.md` already
        # measured the same artefact as a faked +0.19 in |return|. So the same
        # two tests are run on fifteen independent PCG64 rebuilds sampled on the
        # *same* slot lattice: whatever they report is the mask, not the venue.
        base = int(common[0])
        need = int(common[-1] - base) + 4
        sim_rows, sim_names = [], []
        for f in names:
            tk = rebuild_ticks(f, need, SEED + 77)
            if tk.size < need:
                continue
            sim_rows.append(tk[(common - base).astype(np.int64)])
            sim_names.append(f)
        ctl_chi = ctl_sign = float("nan")
        if len(sim_rows) >= 2:
            sinc = np.diff(np.array(sim_rows), axis=1)
            su = np.array([J.to_uniform(sinc[i], rng) for i in range(sinc.shape[0])])
            srich = [i for i in range(len(sim_names)) if np.unique(sinc[i]).size >= 64]
            ctl_chi = 1.0
            for a in srich:
                for b in srich:
                    if a >= b:
                        continue
                    g = J.grid_chi2(np.column_stack([su[a], su[b]]).ravel(), 2, 8)
                    ctl_chi = min(ctl_chi, g.get("p", 1.0))
            slat = [i for i in range(len(sim_names)) if i not in srich]
            ctl_sign = 1.0
            for a in slat:
                for b in range(len(sim_names)):
                    if b == a:
                        continue
                    sa = (sinc[a] > 0).astype(np.int64)
                    sb = (sinc[b] > 0).astype(np.int64)
                    tab = np.bincount(sa * 2 + sb, minlength=4).reshape(2, 2).astype(float)
                    exp = np.outer(tab.sum(1), tab.sum(0)) / tab.sum()
                    st = float(((tab - exp) ** 2 / np.maximum(exp, 1e-9)).sum())
                    ctl_sign = min(ctl_sign, float(_chi2.sf(st, 1)))
        print(f"      CONTROL - {len(sim_rows)} independent PCG64 rebuilds on the same "
              f"{n:,} slots,")
        print(f"      {100 * (1 - n / ((common[-1] - common[0]) or 1)):.0f}% of which are "
              f"gaps shared by every feed: worst grid p = {ctl_chi:.3g}, "
              f"worst sign p = {ctl_sign:.3g}")
        payload.setdefault("joint_control", {}).update(
            {"n_feeds": len(sim_rows), "grid_p": ctl_chi, "sign_p": ctl_sign})
        ledger.append({"test": "cross-feed dependence beyond what the shared slot mask "
                               "makes on independent rebuilds", "feed": "joint",
                       "value": math.log10(max(worst_p, 1e-300))
                       - math.log10(max(ctl_chi, 1e-300)),
                       "fired": worst_p < 0.01 * ctl_chi if ctl_chi == ctl_chi else False})
        ledger.append({"test": "no cross-feed correlation past the band",
                       "feed": "joint", "value": float(np.abs(c[iu]).max()),
                       "fired": npast > 3})
        ledger.append({"test": "no cross-feed 2-D dependence after Bonferroni",
                       "feed": "joint", "value": worst_p,
                       "fired": worst_p < 0.001 / nb})
        ledger.append({"test": "no cross-feed sign dependence on the lattice feeds",
                       "feed": "joint", "value": worst_s,
                       "fired": worst_s < 0.001 / max(len(lat_idx) * len(names), 1)})
        ledger.append({"test": "no lattice in the cross-feed tuple", "feed": "joint",
                       "value": max(v for v in cv if v == v), "fired": hit})
        payload["joint"] = {"feeds": names, "n": int(n),
                            "max_abs_corr": float(np.abs(c[iu]).max()),
                            "n_past_band": npast, "worst_chi2_p": worst_p,
                            "cross_lattice": json.loads(json.dumps(cross, default=float))}
    else:
        print("    could not align the feeds - skipped")

    # ---------------------------------------- rung 5: held-out forward prediction --
    print("\n[5] RUNG 5 - A HELD-OUT FORWARD PREDICTION, WHICH IS THE ONLY CLAIM THAT COUNTS")
    print("    Predict the sign of the next tick. Two feature sets: a feed's own last")
    print(f"    {KLAGS} increments, and all aligned feeds at the current slot.")
    print("    The split is by *time* - fit the first 60%, predict the last 40%. A")
    print("    block split on row index leaks, because the two label groups interleave.")
    print(f"{'target':28s} {'features':28s} {'n':>8s} {'AUC':>8s} {'95% CI':>17s} "
          f"{'verdict':>10s}")
    for feed in ("volatility_75_1s_index", "step_index", "range_break_100_index",
                 "boom_500_index"):
        t = G.real_ticks(feed)
        if not t.get("n"):
            continue
        x, y, nm = sign_features(t["mid"].astype(float), KLAGS)
        if not x.size:
            continue
        r = forward_auc(x, y, nm, SEED)
        if r.get("skipped"):
            print(f"{feed:28s} {'own last ' + str(KLAGS):28s} {r['n']:8d} "
                  f"{'':>8s} {r['skipped']:>17s}")
            continue
        ok = r["lo"] <= 0.5 <= r["hi"]
        print(f"{feed:28s} {'own last ' + str(KLAGS):28s} {r['n']:8d} {r['auc']:8.4f} "
              f"[{r['lo']:.4f},{r['hi']:.4f}] {'-' if ok else 'PREDICTS':>10s}")
        # the control: the same test on the same family driven by PCG64
        ctl = rebuild_ticks(feed, t["n"], SEED)
        rc = {"auc": float("nan"), "lo": float("nan"), "hi": float("nan")}
        if ctl.size > 2000:
            xc, yc, nc = sign_features(ctl.astype(float), KLAGS)
            if xc.size:
                rc = forward_auc(xc, yc, nc, SEED)
        beyond = (not ok) and not (rc.get("lo", 0) <= r["auc"] <= rc.get("hi", 1))
        if rc.get("auc") == rc.get("auc"):
            print(f"{'  ^ PCG64 rebuild':28s} {'same test, sound source':28s} "
                  f"{rc['n']:8d} {rc['auc']:8.4f} [{rc['lo']:.4f},{rc['hi']:.4f}] "
                  f"{'BEYOND' if beyond else 'same as rebuild':>10s}")
        if not ok:
            print(f"{'':28s} {'top features':28s} " + ", ".join(
                f"{n2}={a2:.3f}" for n2, a2 in r["univariate"][:3]))
        ledger.append({"test": "next-tick sign AUC interval contains 0.5", "feed": feed,
                       "value": r["auc"] - 0.5, "fired": not ok})
        ledger.append({"test": "next-tick sign AUC is no higher than a PCG64 rebuild's",
                       "feed": feed, "value": r["auc"] - (rc.get("auc") or 0.5),
                       "fired": bool(beyond)})
        payload.setdefault("predict", {})[feed] = {"own": r, "pcg64_control": rc}
    if mat.size and mat.shape[0] > 2:
        tgt = 0
        d = np.diff(mat, axis=1)
        y = (d[tgt, 1:] > 0).astype(float)
        x = np.ascontiguousarray(d[:, :-1].T)
        nm = [f"f{i}" for i in range(x.shape[1])]
        r = forward_auc(x, y, nm, SEED)
        ok = r.get("skipped") is None and r["lo"] <= 0.5 <= r["hi"]
        if r.get("skipped"):
            print(f"{names[tgt]:28s} {'all feeds':28s} {r['n']:8d} {r['skipped']:>26s}")
        else:
            print(f"{names[tgt]:28s} {'all ' + str(len(names)) + ' feeds, same slot':28s} "
                  f"{r['n']:8d} {r['auc']:8.4f} [{r['lo']:.4f},{r['hi']:.4f}] "
                  f"{'-' if ok else 'PREDICTS':>10s}")
        ledger.append({"test": "next-tick sign AUC interval contains 0.5",
                       "feed": names[tgt] + " from all feeds",
                       "value": r["auc"] - 0.5, "fired": not ok})
        payload.setdefault("predict", {})["joint"] = r
    # the positive control: a feed whose source is a breakable LCG
    lu = trunc_lcg(300_000, 10, seed=7)
    lmid = np.cumsum(np.round((lu - 0.5) * 200)) + 10000.0
    x, y, nm = sign_features(lmid, KLAGS)
    r = forward_auc(x, y, nm, SEED)
    seen = not (r["lo"] <= 0.5 <= r["hi"])
    print(f"{'CONTROL truncated LCG':28s} {'own last ' + str(KLAGS):28s} {r['n']:8d} "
          f"{r['auc']:8.4f} [{r['lo']:.4f},{r['hi']:.4f}] "
          f"{'PREDICTS' if seen else 'missed':>10s}")
    ledger.append({"test": "VOID unless the LCG control is predicted", "feed": "control",
                   "value": r["auc"] - 0.5, "fired": not seen})
    payload.setdefault("predict", {})["control_lcg"] = r

    print("\n[6] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':58s} {'cells':>6s} {'fired':>6s} {'worst cell':>32s}")
    nf = 0
    for name, es in sorted(by.items()):
        f2 = [e for e in es if e["fired"]]
        nf += len(f2)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:58s} {len(es):6d} {len(f2):6d} "
              f"{str(worst['feed'])[:24] + ' ' + format(worst['value'], '.4g'):>32s}")
    print(f"\n    {len(ledger)} pre-registered comparisons, {nf} fired.")
    payload["ledger"] = ledger

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
