"""What the intra-bar reconstruction changes in numbers this desk already trades on.

`research/quantising.md` section three established that reconstructing a bar's
interior from `(O, H, L, C)` removes 39-48% of the interior variance that linear
interpolation leaves, measured against a known true tick path. That is a
statement about a harness. This asks the only question that matters next:
**which quantities the book already computes from bars actually move, and by how
much.**

The desk holds far more bar history than tick history, so every volatility
estimate, wick statistic, level touch and replay is computed from bars. If the
interior is a quarter to a half better than what those computations implicitly
assume, the improvement propagates. If it does not, that is the more useful
sentence and this page says it.

## The bound, stated before any measurement, because it removes most of the claim

**`H` and `L` are the maximum and the minimum over the bar, exactly.** So any
statistic that is a pure function of the extremes over a window whose ends are
bar boundaries is **already exact from bars** and cannot be improved by any
reconstruction whatever. That covers more of the desk than it is comfortable to
admit:

* `levels.observe_wick` takes `done.extreme`, the extreme price of a touch. Over
  a whole number of bars that is `max(highs)` and is exact;
* `shared/replay.py` tests `low <= stop` and `high >= target`. A single-barrier
  hit test over a bar is settled by `H` and `L` and is exact;
* `Ranges.parkinson`, `garman_klass` and `rogers_satchell` are functions of
  `(O, H, L, C)` and see everything there is to see of the extremes.

Section 0 checks that claim numerically rather than asserting it, because if it
is wrong every number below is measured against the wrong baseline.

What is left for a reconstruction is the part of the path that is **not** an
extreme, and there are exactly three kinds of it on this desk:

1. **How much the price moved**, which is a sum over the interior and not a
   function of its endpoints - the realised volatility that `volatility.py`
   consumes;
2. **In which order** the interior visited the extremes - `replay.py`'s Rule 3
   says "the stop is checked first, so a bar touching both is a stop", which is
   a convention and not a measurement;
3. **How many times** the interior crossed a level, which is a local time and is
   invisible to `(O, H, L, C)` entirely.

## The classical control for each, which is not linear interpolation

`quantising.md`'s control was linear interpolation, because the question there
was "where was price". Here the question is different for each section and so is
the control:

* for **volatility**, the control is the desk's own range family - Parkinson,
  Garman-Klass and Rogers-Satchell in `structures/vol/ranges.py`. Those exist
  for exactly this job and beating linear interpolation would be meaningless;
* for **ordering**, the control is the shipping convention, "always the stop";
* for **crossings**, the control is what a bar implies on its own, which is one
  crossing if the level is inside `[L, H]` and none otherwise.

## The one prediction worth making before the numbers

The bridge returns a **conditional mean** path. A conditional mean is the right
object for "where was price" and the **wrong** object for "how far did price
move", because `Var(E[X])` is not `E[Var(X)]` - a posterior mean is smoother
than its posterior. So the reconstruction should improve section 3's ordering,
where the question is about the order of events and not their magnitude, and
should **understate** realised volatility and crossing counts in sections 1 and
4. That is written here before the harness was run, and if the volatility
section comes back positive it should be read as a surprise rather than a
confirmation.

## Power: whose numbers, and why not mine

`research/calibrating.md` has already measured what this book can detect, on a
world where the true edge is known. Its rule is that the 95% interval on
return-on-risk over `n` closes is about **330 / sqrt(n) points of risk**, and its
table gives the closes needed for a claim to be visible: ~270 for a 20-point
effect, ~1,100 for 10 points, 2,400-2,600 closes for a genuine +5% of risk at
80% power. Those numbers are used here as published. Any improvement this page
finds is quoted **against that floor** and is called undetectable when it sits
below it, which is most of the interesting cases.

## What would count as failure, written before any number is printed

1. **The bound is wrong** if the extremes computed from coarse bars differ at all
   from the extremes of the fine path they contain. Exactly zero difference is
   required, not a small one; anything else means the loaders are misaligned and
   nothing below can be read.
2. **The volatility claim dies** if the reconstruction does not beat the best of
   Parkinson, Garman-Klass and Rogers-Satchell at estimating the fine-scale
   realised volatility from the coarse bar. Those are the desk's existing tools
   for this exact job.
3. **The `mad_to_sigma` claim dies** if the reconstructed path does not reproduce
   the fine path's own `sqrt(E[r^2])/E[|r|]` better than linear interpolation.
   Linear interpolation is predicted to return exactly 1.0, because a straight
   line has identical sub-returns, and `volatility.py` clamps the ratio at 1.0 -
   so if that prediction is right the desk currently cannot measure this
   constant from a reconstructed interior at all.
4. **The ordering claim is worthless regardless of accuracy** if under 1% of
   resolved bars touch both barriers, because then Rule 3 cannot matter however
   wrong it is.
5. **The ordering claim dies** if the reconstruction's call on which barrier came
   first is not more accurate than the shipping "always the stop" convention,
   scored against the fine path.
6. **Any improvement is not actionable** unless it clears `calibrating.md`'s
   floor at the `n` the desk has. This is a reporting condition rather than a
   test - a number below the floor is reported as undetectable and not as an
   improvement.
7. **The live-cost claim dies** if one bar's reconstruction costs more than a
   millisecond, which is the point past which a per-bar package change stops
   being free against a 60-second bar on a few dozen feeds.
8. **The run is void** if any estimator reproduces its target exactly, or if two
   estimators that are not the same estimator return identical numbers.

## The data

Coarse bars and the fine bars that compose them. On the lab that is
`research.db`'s one-minute synthetic bars aggregated into fifteen-minute bars -
where the fine bars' own highs and lows are tick extremes, so the coarse high is
a true extreme and the fine bar carrying it is identifiable - and `prices.db`'s
real fifteen-minute and one-minute bars for the real instruments. Both are run,
because the synthetics are the process the construction assumes and the real
instruments are the harder test.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quantbridge as QB  # noqa: E402

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
PRICES = os.environ.get("PRICES", os.path.join(DATA, "prices.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/quantdesk.json"))
SEED = int(os.environ.get("SEED", "20260912"))
#: Fine bars in a coarse bar. Fifteen one-minute bars in a fifteen-minute bar,
#: which is the pair the desk actually holds most of.
NSUB = int(os.environ.get("NSUB", "15"))
#: Price-grid cells for the forward-backward. `quantbridge` uses 161 and the
#: ordering recursion here carries five copies of the grid, so it is kept the
#: same rather than widened.
NCELL = int(os.environ.get("NCELL", "161"))
#: Stop distances to test Rule 3 at, in units of the coarse bar's own range.
BARRIERS = tuple(float(v) for v in os.environ.get("BARRIERS", "0.25,0.35").split(","))
#: Target distance as a multiple of the stop distance, which is what decides
#: whether a single bar can touch both at all.
#:
#: `shared/replay.py` defaults `target_mult` to **6.0**, so a fresh entry has its
#: target six times further away than its stop and a bar has to span seven stop
#: widths to be ambiguous. That is rare, and the honest reading is that Rule 3
#: barely matters for a fresh entry. It matters enormously once the stop has
#: moved: the same file raises the stop to break-even at `protect_r` and then
#: trails it `_trail_step` behind the running best, so a position in profit is
#: carrying a stop a fraction of a bar range away from price while the target is
#: still out at six. **1.0 is the trailing regime and 6.0 is the fresh entry**,
#: and both are swept because they are different questions with different answers.
MULTS = tuple(float(v) for v in os.environ.get("MULTS", "1.0,2.0,6.0").split(","))

SYNTH = (
    "volatility_75_index",
    "volatility_100_index",
    "step_index",
    "range_break_100_index",
    "boom_500_index",
    "jump_75_index",
)
#: Real instruments, as `(feed, venue)`. The venue is named rather than pooled:
#: `prices.db` carries the same instrument from up to seven venues and leaving it
#: out interleaves them into one series whose "fine bars" come from different
#: books, which would make the section 0 bound fail for a reason that has nothing
#: to do with reconstruction. DERIV is the desk's own broker, and btc carries a
#: second venue because `quantising.md` found Binance and Deriv agree there.
REAL = (
    ("btc", "DERIV"),
    ("btc", "BINANCE"),
    ("gold", "DERIV"),
    ("eurusd", "DERIV"),
    ("gbpusd", "DERIV"),
    ("us100", "PEPPERSTONE"),
)


# --------------------------------------------------------------------------
# Loading: coarse bars plus the FINE bars' full OHLC, not just their closes
# --------------------------------------------------------------------------


def _group(ts, op, hi, lo, cl, factor):
    """Reshape contiguous runs of fine bars into coarse bars."""
    n = (len(ts) // factor) * factor
    if n < factor * 50:
        return None
    ts, op, hi, lo, cl = (v[:n].reshape(-1, factor) for v in (ts, op, hi, lo, cl))
    dts = np.diff(ts.ravel())
    unit = int(np.median(dts[dts > 0])) if np.any(dts > 0) else 60
    ok = (np.diff(ts, axis=1) == unit).all(axis=1)
    ts, op, hi, lo, cl = (v[ok] for v in (ts, op, hi, lo, cl))
    if len(op) < 50:
        return None
    return {
        "o": op[:, 0],
        "c": cl[:, -1],
        "hi": hi.max(axis=1),
        "lo": lo.min(axis=1),
        "fine_o": op,
        "fine_h": hi,
        "fine_l": lo,
        "fine_c": cl,
    }


def load_fine(dbpath: str, feed: str, interval: str, venue: str | None, factor: int):
    """Coarse bars built from `factor` fine bars, keeping every fine bar's OHLC.

    `quantbridge.load_aggregated` keeps only the interior closes, which is all a
    reconstruction score needs. Sections 3 and 4 need the fine **highs and lows**
    as well, because the question there is which fine bar carried the coarse
    bar's extreme, and a close does not reach an extreme.
    """
    if not os.path.exists(dbpath):
        return None
    conn = sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True)
    q = "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval=?"
    args: list = [feed, interval]
    if venue:
        q += " AND venue=?"
        args.append(venue)
    rows = conn.execute(q + " ORDER BY ts", args).fetchall()
    conn.close()
    rows = [r for r in rows if None not in r and float(r[2]) > float(r[3])]
    if len(rows) < factor * 50:
        return None
    cols = [np.array([float(r[i]) for r in rows]) for i in range(5)]
    return _group(np.array([int(r[0]) for r in rows]), *cols[1:], factor)


# --------------------------------------------------------------------------
# The desk's own range estimators, transcribed from structures/vol/ranges.py
# --------------------------------------------------------------------------


def parkinson(o, h, low, c):
    """`structures/vol/ranges.py::parkinson`. High-low only."""
    return np.sqrt(np.log(h / low) ** 2 / (4.0 * math.log(2.0)))


def garman_klass(o, h, low, c):
    """`structures/vol/ranges.py::garman_klass`."""
    hl = np.log(h / low) ** 2
    co = np.log(c / o) ** 2
    return np.sqrt(np.maximum(0.5 * hl - (2.0 * math.log(2.0) - 1.0) * co, 0.0))


def rogers_satchell(o, h, low, c):
    """`structures/vol/ranges.py::rogers_satchell`. Drift-independent."""
    t = np.log(h / c) * np.log(h / o) + np.log(low / c) * np.log(low / o)
    return np.sqrt(np.maximum(t, 0.0))


# --------------------------------------------------------------------------
# Ordering: which extreme came first, as a five-state forward-backward
# --------------------------------------------------------------------------


def order_probability(o, c, lo, hi, sigma_sub, nsub, ncell=NCELL, nbucket=24):
    """P(the high was attained before the low), given `(O, H, L, C)`.

    This is the one question on this page that `(O, H, L, C)` genuinely cannot
    answer and a reconstruction genuinely can, and it is what `replay.py`'s Rule
    3 currently answers with a convention.

    `quantbridge.bridge_attained` already carries an ancilla with the two bits
    "has the running maximum reached `H`" and the same for `L`, but it collapses
    both routes into one "both touched" state because all it needs is the
    conditional mean. Separating the routes needs **five** states - none,
    high-only, low-only, both-reached-high-first, both-reached-low-first - and
    then the terminal mass in the last two is the answer. Same kernel, same
    touch probabilities from the bridge maximum law, one more copy of the grid.
    """
    n = len(o)
    rng_hl = hi - lo
    good = (rng_hl > 0) & (sigma_sub > 0)
    s = np.where(good, sigma_sub / np.maximum(rng_hl, 1e-12), 0.1)
    s = np.clip(s, 1.5 / ncell, 1.0)
    edges = np.exp(np.linspace(math.log(s.min() * 0.999), math.log(s.max() * 1.001), nbucket + 1))
    which = np.clip(np.searchsorted(edges, s, side="right") - 1, 0, nbucket - 1)

    p_high_first = np.full(n, np.nan)
    xg = (np.arange(ncell) + 0.5) / ncell
    for b in range(nbucket):
        idx = np.flatnonzero(which == b)
        if idx.size == 0:
            continue
        sb = math.exp(0.5 * (math.log(edges[b]) + math.log(edges[b + 1])))
        k = QB._kernel_matrix(ncell, sb)
        gx, gy = xg[:, None], xg[None, :]
        ph = np.exp(-2.0 * np.maximum(1.0 - gx, 0.0) * np.maximum(1.0 - gy, 0.0) / (sb * sb))
        pl = np.exp(-2.0 * np.maximum(gx, 0.0) * np.maximum(gy, 0.0) / (sb * sb))
        ph[:, -1] = 1.0
        pl[:, 0] = 1.0
        # Transitions out of "neither touched".
        k00 = k * (1 - ph) * (1 - pl)
        k0h = k * ph * (1 - pl)
        k0l = k * pl * (1 - ph)
        # Touching both inside one sub-step is a tie and is split evenly; it
        # needs a sub-step range of a whole H-L and is negligible at these
        # widths, but it has to go somewhere and a coin is the honest place.
        k0b = k * ph * pl
        kh_h = k * (1 - pl)
        kh_b = k * pl
        kl_l = k * (1 - ph)
        kl_b = k * ph

        u0 = np.clip((o[idx] - lo[idx]) / rng_hl[idx], 0.0, 1.0)
        u1 = np.clip((c[idx] - lo[idx]) / rng_hl[idx], 0.0, 1.0)
        i0 = np.clip((u0 * ncell).astype(int), 0, ncell - 1)
        i1 = np.clip((u1 * ncell).astype(int), 0, ncell - 1)
        m = idx.size
        a00 = np.zeros((m, ncell))
        ah = np.zeros((m, ncell))
        al = np.zeros((m, ncell))
        abh = np.zeros((m, ncell))
        abl = np.zeros((m, ncell))
        row = np.arange(m)
        a00[row, i0] = 1.0
        ah[row, i0] = (i0 == ncell - 1) * 1.0
        al[row, i0] = (i0 == 0) * 1.0
        a00[row, i0] -= ah[row, i0] + al[row, i0]
        for _ in range(nsub - 1):
            n00 = a00 @ k00
            nh = ah @ kh_h + a00 @ k0h
            nl = al @ kl_l + a00 @ k0l
            nbh = abh @ k + ah @ kh_b + 0.5 * (a00 @ k0b)
            nbl = abl @ k + al @ kl_b + 0.5 * (a00 @ k0b)
            tot = np.maximum(
                n00.sum(axis=1)
                + nh.sum(axis=1)
                + nl.sum(axis=1)
                + nbh.sum(axis=1)
                + nbl.sum(axis=1),
                1e-300,
            )[:, None]
            a00, ah, al, abh, abl = n00 / tot, nh / tot, nl / tot, nbh / tot, nbl / tot
        # Only paths that reached both are admissible, and they land on C.
        wh = abh[row, i1]
        wl = abl[row, i1]
        tot = wh + wl
        p_high_first[idx] = np.where(tot > 0, wh / np.maximum(tot, 1e-300), np.nan)
    return p_high_first


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------


def logratio(est, truth):
    """Bias and dispersion of an estimator, on the log scale where vol lives."""
    ok = (est > 0) & (truth > 0) & np.isfinite(est) & np.isfinite(truth)
    if ok.sum() < 20:
        return float("nan"), float("nan"), 0
    r = np.log(est[ok] / truth[ok])
    return float(np.mean(r)), float(np.std(r)), int(ok.sum())


def detectable(points_of_risk: float) -> str:
    """`calibrating.md`'s floor: a 95% interval is about 330/sqrt(n) points."""
    if not np.isfinite(points_of_risk) or points_of_risk <= 0:
        return "no effect to detect"
    n = (330.0 / points_of_risk) ** 2
    if n > 1e7:
        return f"needs n > 10,000,000 closes - not detectable by this book"
    return f"needs n ~ {n:,.0f} closes to clear 330/sqrt(n)"


def main() -> None:  # noqa: PLR0915
    rng = np.random.default_rng(SEED)
    out: dict = {}
    print("=" * 98)
    print("WHAT THE RECONSTRUCTION CHANGES IN NUMBERS THIS DESK ALREADY TRADES ON")
    print("=" * 98)

    # ---- load ----
    books: dict[str, dict] = {}
    for feed in SYNTH:
        d = load_fine(DB, feed, "1m", None, NSUB)
        if d:
            books[f"synth:{feed}"] = d
    for feed, venue in REAL:
        d = load_fine(PRICES, feed, "1m", venue, NSUB)
        if d:
            books[f"real:{feed}"] = d
    if not books:
        print("\n  no data reachable - nothing below is run.")
        return
    print(f"\n  {len(books)} books loaded, {NSUB} fine bars to a coarse bar")
    for name, d in books.items():
        print(f"    {name:32s} {len(d['o']):6d} coarse bars")

    # ---- 0: the bound ----
    print("\n[0] THE BOUND: WHAT A RECONSTRUCTION CANNOT TOUCH")
    print("    H and L are the max and min over the bar, exactly, so any statistic that")
    print("    is a pure function of window extremes is already exact from bars. Checked")
    print("    rather than asserted, because everything below is measured against it.")
    worst = 0.0
    for d in books.values():
        worst = max(
            worst,
            float(np.max(np.abs(d["hi"] - d["fine_h"].max(axis=1)))),
            float(np.max(np.abs(d["lo"] - d["fine_l"].min(axis=1)))),
        )
    print(f"\n    max |coarse extreme - extreme of the fine bars inside|: {worst:.3e}")
    print("    -> wick depth, single-barrier hit tests and the range family see")
    print("       everything there is to see. None of them can be improved.")
    out["bound_max_abs_diff"] = worst

    # ---- 1: realised volatility ----
    print("\n[1] REALISED VOLATILITY AT THE FINE SCALE, FROM THE COARSE BAR")
    print("    What volatility.py consumes. Truth is the root-mean-square of the fine")
    print("    log-returns inside the bar. The control is the desk's OWN range family,")
    print("    not linear interpolation - Parkinson, Garman-Klass and Rogers-Satchell")
    print("    exist for exactly this job and beating linear would mean nothing.")
    vol_rows: dict = {}
    for name, d in books.items():
        o, c, hi, lo = d["o"], d["c"], d["hi"], d["lo"]
        fine = np.column_stack([d["fine_c"]])
        path = np.column_stack([o, fine])
        r = np.diff(np.log(np.maximum(path, 1e-12)), axis=1)
        truth = np.sqrt(np.mean(r * r, axis=1))
        sig = np.abs(np.log(np.maximum(c, 1e-12) / np.maximum(o, 1e-12)))
        sig = np.where(sig > 0, sig, np.median(sig[sig > 0]) if np.any(sig > 0) else 1e-6)
        sub_sigma = (hi - lo) / math.sqrt(max(NSUB, 1)) / 4.0
        est = {
            "parkinson": parkinson(o, hi, lo, c) / math.sqrt(NSUB),
            "garman_klass": garman_klass(o, hi, lo, c) / math.sqrt(NSUB),
            "rogers_satchell": rogers_satchell(o, hi, lo, c) / math.sqrt(NSUB),
            "close-to-close": np.abs(np.log(c / o)) / math.sqrt(NSUB),
        }
        lin = QB.linear_interior(o, c, NSUB)
        bm, _ = QB.bridge_interior(o, c, lo, hi, sub_sigma, NSUB, ncell=NCELL)
        am, _ = QB.bridge_attained(o, c, lo, hi, sub_sigma, NSUB, ncell=NCELL)
        for label, interior in (("linear", lin), ("bridge", bm), ("bridge+attain", am)):
            p = np.column_stack([o, interior, c])
            rr = np.diff(np.log(np.maximum(p, 1e-12)), axis=1)
            est[label] = np.sqrt(np.nanmean(rr * rr, axis=1))
        vol_rows[name] = {
            k: dict(zip(("bias", "sd", "n"), logratio(v, truth), strict=False))
            for k, v in est.items()
        }
    hdr = (
        "parkinson",
        "garman_klass",
        "rogers_satchell",
        "close-to-close",
        "linear",
        "bridge",
        "bridge+attain",
    )
    print(f"\n    mean log(estimate/truth) - zero is unbiased, negative understates")
    print(f"    {'book':32s} " + " ".join(f"{h[:13]:>13s}" for h in hdr))
    for name, row in vol_rows.items():
        print(f"    {name:32s} " + " ".join(f"{row[h]['bias']:+13.4f}" for h in hdr))
    print(f"\n    sd of log(estimate/truth) - lower is a tighter estimator")
    print(f"    {'book':32s} " + " ".join(f"{h[:13]:>13s}" for h in hdr))
    for name, row in vol_rows.items():
        print(f"    {name:32s} " + " ".join(f"{row[h]['sd']:13.4f}" for h in hdr))
    out["volatility"] = vol_rows

    # ---- 2: mad_to_sigma ----
    print("\n[2] MAD_TO_SIGMA, WHICH volatility.py MEASURES PER SERIES")
    print("    sqrt(E[r^2]) / E[|r|] of the fine returns. cascading.md measured 1.546 at")
    print("    1m across 53 feeds against the Gaussian sqrt(pi/2) = 1.2533, so the")
    print("    shipping constant is 23% low. Can a desk holding only coarse bars recover")
    print("    the fine constant from a reconstructed interior?")

    def ratio_of(path):
        r = np.diff(np.log(np.maximum(path, 1e-12)), axis=1)
        ma = np.mean(np.abs(r))
        return float(math.sqrt(np.mean(r * r)) / ma) if ma > 0 else float("nan")

    mad_rows: dict = {}
    for name, d in books.items():
        o, c, hi, lo = d["o"], d["c"], d["hi"], d["lo"]
        sub_sigma = (hi - lo) / math.sqrt(max(NSUB, 1)) / 4.0
        truth = ratio_of(np.column_stack([o, d["fine_c"]]))
        lin = QB.linear_interior(o, c, NSUB)
        bm, _ = QB.bridge_interior(o, c, lo, hi, sub_sigma, NSUB, ncell=NCELL)
        am, _ = QB.bridge_attained(o, c, lo, hi, sub_sigma, NSUB, ncell=NCELL)
        mad_rows[name] = {
            "truth": truth,
            "linear": ratio_of(np.column_stack([o, lin, c])),
            "bridge": ratio_of(np.column_stack([o, bm, c])),
            "bridge+attain": ratio_of(np.column_stack([o, am, c])),
            "gaussian": math.sqrt(math.pi / 2.0),
        }
    print(
        f"\n    {'book':32s} {'TRUTH (fine)':>13s} {'linear':>10s} {'bridge':>10s} "
        f"{'+attain':>10s} {'Gaussian':>10s}"
    )
    for name, r in mad_rows.items():
        print(
            f"    {name:32s} {r['truth']:13.4f} {r['linear']:10.4f} {r['bridge']:10.4f} "
            f"{r['bridge+attain']:10.4f} {r['gaussian']:10.4f}"
        )
    out["mad_to_sigma"] = mad_rows

    # ---- 3: Rule 3 ----
    print("\n[3] replay.py RULE 3 - 'THE STOP IS CHECKED FIRST, SO A BAR TOUCHING BOTH")
    print("    IS A STOP'. That is a convention. The interior decides it, and this is")
    print("    the one question on this page that (O,H,L,C) cannot answer at all.")
    print("    Truth: which fine bar carried the coarse high, against which carried the")
    print("    coarse low. The stop sits a fraction of the bar's own range below the open")
    print("    and the target `mult` times that above it, so the sweep runs from the")
    print("    trailing regime (mult 1, a stop dragged up near price) to replay.py's own")
    print("    default for a fresh entry (mult 6).")
    ord_rows: dict = {}
    for name, d in books.items():
        o, c, hi, lo = d["o"], d["c"], d["hi"], d["lo"]
        sub_sigma = (hi - lo) / math.sqrt(max(NSUB, 1)) / 4.0
        i_hi = np.argmax(d["fine_h"], axis=1)
        i_lo = np.argmin(d["fine_l"], axis=1)
        per_f: dict = {}
        for frac in BARRIERS:
            for mult in MULTS:
                up = o + mult * frac * (hi - lo)
                dn = o - frac * (hi - lo)
                touched_both = (hi >= up) & (lo <= dn)
                both = touched_both & (i_hi != i_lo)
                share = float(np.mean(touched_both))
                key = f"{frac}x{mult}"
                if int(both.sum()) < 30:
                    per_f[key] = {
                        "share_both": share,
                        "mult": mult,
                        "n": int(both.sum()),
                        "note": "too few to score",
                    }
                    continue
                truth_high_first = i_hi[both] < i_lo[both]
                p = order_probability(
                    o[both], c[both], lo[both], hi[both], sub_sigma[both], NSUB, ncell=NCELL
                )
                call = p > 0.5
                ok = np.isfinite(p)
                acc_bridge = float(np.mean(call[ok] == truth_high_first[ok]))
                # The shipping convention: the stop always fires first. For a
                # long the stop is below, so it asserts low-first every time.
                acc_rule3 = float(np.mean(~truth_high_first))
                # And the coin, because a convention worse than a coin is a
                # different finding from one that is merely not the best.
                acc_coin = 0.5
                # What the misordering is worth, which is the only form of the
                # answer a desk can act on. The stop is -1R and the target
                # +`mult`R, so calling the wrong one costs `1 + mult` R. What
                # matters is not the error rate but whether the errors cancel:
                # Rule 3 always says "stop", so its error is a one-sided BIAS on
                # every backtest that uses it, while the reconstruction's errors
                # go both ways and mostly cancel in the mean.
                resolving = (hi >= up) | (lo <= dn)
                share_res = float(np.mean(both) / max(np.mean(resolving), 1e-12))
                t = truth_high_first[ok]
                cl = call[ok]
                loss = 1.0 + mult
                err_rule3 = float(np.mean(np.where(t, -loss, 0.0)))
                err_bridge = float(np.mean(np.where(t & ~cl, -loss, np.where(~t & cl, loss, 0.0))))
                rms_rule3 = float(np.sqrt(np.mean(np.where(t, loss * loss, 0.0))))
                rms_bridge = float(np.sqrt(np.mean(np.where(t != cl, loss * loss, 0.0))))
                per_f[key] = {
                    "share_both": share,
                    "mult": mult,
                    "share_of_resolving": share_res,
                    "n": int(ok.sum()),
                    "truth_high_first": float(np.mean(truth_high_first)),
                    "acc_bridge": acc_bridge,
                    "acc_rule3": acc_rule3,
                    "acc_coin": acc_coin,
                    "mean_p": float(np.nanmean(p)),
                    # Per RESOLVED trade, in points of risk, so it reads straight
                    # against calibrating.md's 330/sqrt(n) floor.
                    "bias_rule3_points": 100.0 * share_res * err_rule3,
                    "bias_bridge_points": 100.0 * share_res * err_bridge,
                    "rms_rule3_points": 100.0 * share_res * rms_rule3,
                    "rms_bridge_points": 100.0 * share_res * rms_bridge,
                }
        ord_rows[name] = per_f
    print(
        f"\n    {'book':26s} {'stop x mult':>11s} {'both%':>7s} {'n':>6s} {'P(hi 1st)':>10s} "
        f"{'bridge':>8s} {'Rule 3':>8s} {'gain':>8s}"
    )
    for name, per_f in ord_rows.items():
        for frac, r in per_f.items():
            if "acc_bridge" not in r:
                print(
                    f"    {name:26s} {frac:>11s} {100 * r['share_both']:6.2f}% "
                    f"{r['n']:6d}  {r.get('note', '')}"
                )
                continue
            print(
                f"    {name:26s} {frac:>11s} {100 * r['share_both']:6.2f}% {r['n']:6d} "
                f"{r['truth_high_first']:10.3f} {r['acc_bridge']:8.3f} {r['acc_rule3']:8.3f} "
                f"{r['acc_bridge'] - r['acc_rule3']:+8.3f}"
            )
    print("\n    WHAT THE MISORDERING IS WORTH, PER RESOLVED TRADE, IN POINTS OF RISK.")
    print("    The stop is -1R and the target +multR, so calling the wrong one costs")
    print("    (1 + mult) R. Rule 3 always says 'stop', so its error is a ONE-SIDED BIAS")
    print("    on every backtest that uses it; the reconstruction's errors go both ways")
    print("    and largely cancel in the mean, which is the difference that matters.")
    print("    The last column is calibrating.md's floor: the closes needed before an")
    print("    effect that size clears a 330/sqrt(n) interval.")
    print(
        f"\n    {'book':22s} {'stop x mult':>11s} {'both|resolve':>13s} {'Rule 3 bias':>12s} "
        f"{'bridge bias':>12s} {'Rule 3 rms':>11s} {'detectable at':>28s}"
    )
    for name, per_f in ord_rows.items():
        for frac, r in per_f.items():
            if "bias_rule3_points" not in r:
                continue
            print(
                f"    {name:22s} {frac:>11s} {100 * r['share_of_resolving']:12.1f}% "
                f"{r['bias_rule3_points']:+12.1f} {r['bias_bridge_points']:+12.1f} "
                f"{r['rms_rule3_points']:11.1f}   {detectable(abs(r['bias_rule3_points'])):>26s}"
            )
    out["ordering"] = ord_rows

    # ---- 4: crossings ----
    print("\n[4] LEVEL CROSSINGS INSIDE A BAR, WHICH ARE A LOCAL TIME AND NOT AN EXTREME")
    print("    From (O,H,L,C) a bar implies one crossing if the level is inside [L,H].")
    print("    The fine path crosses as often as it likes. This is what a replay counting")
    print("    level touches from bars is implicitly assuming.")
    cross_rows: dict = {}
    for name, d in books.items():
        o, c, hi, lo = d["o"], d["c"], d["hi"], d["lo"]
        sub_sigma = (hi - lo) / math.sqrt(max(NSUB, 1)) / 4.0
        lvl = (hi + lo) / 2.0
        fine_path = np.column_stack([o, d["fine_c"]])
        tru = np.sum(np.diff(np.sign(fine_path - lvl[:, None]), axis=1) != 0, axis=1)
        bm, _ = QB.bridge_interior(o, c, lo, hi, sub_sigma, NSUB, ncell=NCELL)
        bpath = np.column_stack([o, bm, c])
        bri = np.sum(np.diff(np.sign(bpath - lvl[:, None]), axis=1) != 0, axis=1)
        lin = QB.linear_interior(o, c, NSUB)
        lpath = np.column_stack([o, lin, c])
        li = np.sum(np.diff(np.sign(lpath - lvl[:, None]), axis=1) != 0, axis=1)
        bar_implied = np.where((lo <= lvl) & (hi >= lvl), 1, 0)
        cross_rows[name] = {
            "truth": float(np.mean(tru)),
            "bar_implied": float(np.mean(bar_implied)),
            "linear": float(np.mean(li)),
            "bridge": float(np.mean(bri)),
        }
    print(f"\n    {'book':32s} {'TRUTH':>9s} {'bar implies':>12s} {'linear':>9s} {'bridge':>9s}")
    for name, r in cross_rows.items():
        print(
            f"    {name:32s} {r['truth']:9.3f} {r['bar_implied']:12.3f} "
            f"{r['linear']:9.3f} {r['bridge']:9.3f}"
        )
    out["crossings"] = cross_rows

    # ---- 5: cost ----
    print("\n[5] WHAT IT COSTS TO RUN, WHICH DECIDES RESEARCH TOOL AGAINST PACKAGE CHANGE")
    nb = 4096
    o = np.full(nb, 100.0)
    c = 100.0 + rng.normal(0, 0.5, nb)
    hi = np.maximum(o, c) + np.abs(rng.normal(0, 0.5, nb))
    lo = np.minimum(o, c) - np.abs(rng.normal(0, 0.5, nb))
    ss = (hi - lo) / math.sqrt(NSUB) / 4.0
    cost: dict = {}
    for label, fn in (
        ("bridge (containment)", QB.bridge_interior),
        ("bridge (attainment)", QB.bridge_attained),
    ):
        t0 = time.perf_counter()
        fn(o, c, lo, hi, ss, NSUB, ncell=NCELL)
        cost[label] = (time.perf_counter() - t0) / nb * 1e3
    t0 = time.perf_counter()
    order_probability(o, c, lo, hi, ss, NSUB, ncell=NCELL)
    cost["ordering (five-state)"] = (time.perf_counter() - t0) / nb * 1e3
    t0 = time.perf_counter()
    QB.linear_interior(o, c, NSUB)
    cost["linear interpolation"] = (time.perf_counter() - t0) / nb * 1e3
    print(f"\n    {nb:,} bars, batched, milliseconds per bar")
    for label, ms in cost.items():
        print(f"    {label:28s} {ms:9.5f} ms/bar")
    print("\n    Batched is the number that matters: these are matrix recursions over a")
    print("    shared price grid, so the per-bar cost falls by orders of magnitude when")
    print("    bars are processed together. A per-bar-at-a-time caller pays the bucket")
    print("    setup every time and should not be written.")
    out["cost_ms_per_bar"] = cost

    # ---- 6: ledger ----
    print("\n[6] THE PRE-REGISTERED KILL CONDITIONS")
    ledger: list = []

    def fire(name: str, cond: bool, detail: str) -> None:
        ledger.append({"condition": name, "fired": bool(cond), "detail": detail})
        print(f"    [{'FIRED' if cond else ' ok  '}] {name}")
        print(f"             {detail}")

    fire(
        "1. the bound is wrong - a coarse extreme differs from the fine bars' extreme",
        worst > 0.0,
        f"max absolute difference {worst:.3e} over {sum(len(d['o']) for d in books.values()):,} bars",
    )
    best_range = {}
    for name, row in vol_rows.items():
        rngbest = min(
            ("parkinson", "garman_klass", "rogers_satchell"), key=lambda h: abs(row[h]["bias"])
        )
        best_range[name] = (rngbest, abs(row[rngbest]["bias"]), abs(row["bridge+attain"]["bias"]))
    loses = [n for n, (_, rb, bb) in best_range.items() if bb >= rb]
    fire(
        "2. the reconstruction does not beat the desk's own range family on volatility",
        bool(loses),
        "; ".join(
            f"{n}: best range {best_range[n][0]} |bias| {best_range[n][1]:.4f} against "
            f"bridge+attain {best_range[n][2]:.4f}"
            for n in list(loses)[:4]
        )
        or "the reconstruction is closer to unbiased than every range estimator, everywhere",
    )
    lin_ratios = [r["linear"] for r in mad_rows.values()]
    bad_mad = [
        n
        for n, r in mad_rows.items()
        if abs(r["bridge+attain"] - r["truth"]) >= abs(r["linear"] - r["truth"])
    ]
    fire(
        "3. the reconstruction does not recover mad_to_sigma better than linear",
        bool(bad_mad),
        f"linear returns {min(lin_ratios):.4f} to {max(lin_ratios):.4f}; "
        + (
            "worse on " + ", ".join(bad_mad[:4])
            if bad_mad
            else "closer to the fine truth on every book"
        ),
    )
    shares = [
        r["share_both"] for per_f in ord_rows.values() for r in per_f.values() if "share_both" in r
    ]
    fire(
        "4. Rule 3 cannot matter - under 1% of bars touch both barriers",
        bool(shares) and max(shares) < 0.01,
        f"share of bars touching both runs {100 * min(shares):.2f}% to {100 * max(shares):.2f}%"
        if shares
        else "not evaluated",
    )
    beat = [
        (n, f, r["acc_bridge"] - r["acc_rule3"])
        for n, per_f in ord_rows.items()
        for f, r in per_f.items()
        if "acc_bridge" in r
    ]
    losers = [(n, f, g) for n, f, g in beat if g <= 0]
    fire(
        "5. the reconstruction's ordering call is no better than the shipping convention",
        bool(losers),
        "; ".join(f"{n} at {f}: {g:+.3f}" for n, f, g in losers[:5])
        if losers
        else f"better on all {len(beat)} cells, by {min(g for _, _, g in beat):+.3f} to "
        f"{max(g for _, _, g in beat):+.3f}",
    )
    biases = [
        abs(r["bias_rule3_points"])
        for per_f in ord_rows.values()
        for r in per_f.values()
        if "bias_rule3_points" in r
    ]
    fire(
        "6. REPORTING - the ordering correction sits below calibrating.md's detection floor",
        bool(biases) and max(biases) < 330.0 / math.sqrt(8000.0),
        f"Rule 3's one-sided bias runs {min(biases):.1f} to {max(biases):.1f} points of risk "
        f"per resolved trade; the largest {detectable(max(biases))}"
        if biases
        else "not evaluated",
    )
    slow = [k for k, v in cost.items() if "bridge" in k or "ordering" in k]
    worst_ms = max(cost[k] for k in slow)
    fire(
        "7. one bar's reconstruction costs more than a millisecond",
        worst_ms > 1.0,
        f"worst of the three recursions is {worst_ms:.5f} ms/bar batched",
    )
    vals = [round(v, 10) for row in vol_rows.values() for v in (row[h]["bias"] for h in hdr)]
    fire(
        "8. void - an estimator reproduces its target exactly, or two agree exactly",
        len(vals) != len(set(vals)) or any(v == 0.0 for v in vals),
        f"{len(set(vals))} distinct bias values across {len(vals)} cells",
    )
    out["ledger"] = ledger
    print(f"\n    {sum(1 for x in ledger if x['fired'])} of {len(ledger)} fired.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
