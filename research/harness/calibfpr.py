"""How often does this desk's own analysis report something that is not there?

`research/calibrating.md`. Runs the methods `spending.py` uses - the split, the
percentile bootstrap on return-on-risk, the reward-to-risk bands, the exit-kind
table, the by-strategy cut - on books drawn from `calibnull.py`'s world, where
the true return on risk is `-COST_R` for every strategy, every band, every feed
and every hour, because `deriving.md`'s theorem says so and `calibnull.py`
checks it to within a fifth of a standard error.

Every "edge" found here is a false positive by construction. The question is
how many there are, how large they get, and what shape they take.

## The statistic

`spending.py::on_risk` is `sum(profit) / sum(risk)` - a **ratio of sums** over a
skewed, heavy-tailed, bounded-below distribution, not a mean. Its 95% interval
is a percentile bootstrap on 20,000 resamples of the `(profit, risk)` pairs.
Nothing guarantees that interval covers at 95%, and at n=29 there is no reason
to expect it to. That is measurement one.

The bootstrap here is the same procedure, vectorised: 20,000 resamples of `n`
pairs are drawn as one `(20000, n)` index array and summed along each row, which
is the same draw as `spending.py`'s `random.choices` loop and several times
faster than either that or a multinomial. `[1]` checks the vectorised version
against
`spending.interval` itself on the live book and on null books, and refuses to
go on if they disagree.

## Two different questions wear the word "false positive"

**Excluding the truth** is the calibration question: a 95% interval should miss
the true value 5% of the time, whatever that value is. That is the number a
coverage claim is about, and it is the one `[2]` reports first.

**Excluding zero** is the desk's question, because "the interval excludes zero"
is what `spending.md` acts on. In this world the truth is `-COST_R`, which is
*not* zero, so an interval that sits entirely below zero is not wrong about the
sign - it is wrong about the size, by an order of magnitude, and it is what
turns a strategy off. Both rates are reported everywhere and never merged.

## What would have killed this, declared before any number was read

1. **A plain t-test on Gaussian data at n=133 must reject at 5%.** If the
   machinery cannot recover a false-positive rate that is known exactly, it
   cannot measure one that is not. Checked to within 3 standard errors of
   0.0500 over 40,000 trials before anything else runs.
2. **The vectorised bootstrap must agree with `spending.interval`.** A
   re-implementation judging its own re-implementation is judging nothing, so
   both endpoints are compared on the live 133 closes and on twenty null books.

   *Written as "to within 0.004 of risk", and that constant fired on the first
   smoke run - because `spending.interval` does not agree with **itself** to
   0.004: five seeds on the live book move its upper endpoint over 0.45 points
   and its lower over 0.23, and at n=29 the lower endpoint moves 0.72. A fixed
   tolerance was therefore a test of Monte Carlo noise rather than of
   agreement. The condition is restated - the vectorised bootstrap must not
   differ from `spending.interval` by more than `spending.interval` differs
   from itself across seeds, by more than half again - and the seed-to-seed
   spread is reported next to it, because it is the noise floor on every
   interval `spending.md` publishes. The original constant and the reason it
   was replaced are kept here rather than quietly edited out.*
3. **A rate landing on exactly 0.0500 or 0.5000** to four decimals is a bug
   until proved otherwise, per `research/README.md`. `exactly_null` is called
   on every headline rate and the hits are printed.
4. **If per-method coverage at n=133 is inside one standard error of nominal**,
   then the bootstrap is fine at the desk's sample size and the twelve-row
   result is a multiplicity result and nothing more - and must be reported that
   way rather than as a criticism of the bootstrap.
5. **If the corrected interval does not restore 5%**, the correction this page
   recommends does not work and must not be recommended.
6. **If power at the sample sizes `spending.md` quotes is near 80%**, then that
   page's sample-size arithmetic is right and this section has no content.
7. **If no other interval construction beats the percentile bootstrap at n=29**,
   the bootstrap is not what is wrong and the recommendation must be about
   multiplicity alone. Four are compared - percentile, BCa, studentised, and a
   t interval on the linearised ratio - on the same books and the same
   resamples, because a comparison across different draws is a comparison of
   seeds.
8. **If the twelve-row cut fires no more often than a single row does**, there
   is no multiplicity cost and `spending.md`'s `snap` row stands on its own.
9. **If the cheap bootstrap disagrees with the shipping one.** The coverage
   sweeps use `BDRAWS` resamples rather than `spending.py`'s 20,000, because
   two thousand books times twenty thousand draws is not affordable; the two
   are run head to head at n=29 and n=133 and must agree to within a standard
   error of the rate, or the sweeps are re-run at 20,000 and nothing else here
   is reported.
10. **The `t_crit` expansion must reproduce the published t quantiles** at
   15, 28 and 132 degrees of freedom to 1e-3. A wrong multiplier would flatter
   or condemn the interval it is used in.

The feature scan and its permutation control - the other method this desk runs -
are in `calibscan.py`, because they need entry features and this file needs
outcomes only.

Run on the lab, after `calibnull.py`:

    ./.secrets/lab.sh run research/harness/calibfpr.py BOOKS=2000
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import sys
import time
from statistics import NormalDist

import numpy as np

sys.path.insert(0, os.environ.get("REPO", os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import research.harness.calibnull as N  # noqa: E402
import research.harness.rebuildgen as G  # noqa: E402
import research.harness.spending as S  # noqa: E402
from till_infinity.shared.strata import compare  # noqa: E402

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/results"))
POOL = os.environ.get("POOL", os.path.join(OUT, "calibnull.npz"))
#: Disjoint null books per measurement. Disjoint rather than resampled: every
#: book anywhere in one sweep is a distinct block of a single permutation of the
#: pool, so the standard error on a rate is the binomial one and nothing has to
#: be argued.
BOOKS = int(os.environ.get("BOOKS", "2000"))
#: `spending.py` uses 20,000 resamples. The sweeps here use fewer, because the
#: coverage of an interval is not sensitive to the Monte Carlo noise on its
#: endpoints the way a single published figure is - and condition 9 checks that
#: claim rather than assuming it.
DRAWS = S.DRAWS
BDRAWS = int(os.environ.get("BDRAWS", "4000"))
TRIALS = int(os.environ.get("TRIALS", "40000"))
SEED = int(os.environ.get("SEED", "606"))
WORKERS = int(os.environ.get("WORKERS", str(min(60, os.cpu_count() or 8))))
#: Fork, explicitly. The pool arrays are handed to the workers by inheritance
#: rather than by pickling: sixty workers times two eight-megabyte arrays is a
#: gigabyte of copying per table, and `spawn` would do it every time.
CTX = mp.get_context("fork")

#: `spending.py::interval` refuses below this, so a row shorter than it prints
#: "too few to say" and cannot be a false positive. Half the twelve-row table
#: is below it, which is part of the answer.
MIN_INTERVAL_N = 8

#: Read by the workers after the fork. Set once, in `main`.
_W: dict[str, object] = {}

NORM = NormalDist()


def se_rate(p: float, n: int) -> float:
    return math.sqrt(max(p * (1 - p), 1e-12) / max(n, 1))


def fmt_rate(p: float, n: int) -> str:
    return f"{p * 100:5.2f}% +-{se_rate(p, n) * 100:4.2f}"


def t_crit(df: int, alpha: float = 0.05) -> float:
    """The two-sided `alpha` t quantile, by the Cornish-Fisher expansion.

    Four terms, which is 1e-4 at 28 degrees of freedom. Written out rather than
    imported because the lab venv carries numpy and not scipy, and a table
    would need an entry for every row size this file cuts.
    """
    z = NORM.inv_cdf(1.0 - alpha / 2)
    v = float(df)
    z3, z5, z7 = z ** 3, z ** 5, z ** 7
    return float(z
                 + (z3 + z) / (4 * v)
                 + (5 * z5 + 16 * z3 + 3 * z) / (96 * v * v)
                 + (3 * z7 + 19 * z5 + 17 * z3 - 15 * z) / (384 * v ** 3))


# ------------------------------------------------------------ the estimators --
def on_risk(profit: np.ndarray, risk: np.ndarray) -> float:
    tot = risk.sum()
    return float(profit.sum() / tot) if tot else 0.0


def ratio_se(profit: np.ndarray, risk: np.ndarray, theta: float | None = None) -> float:
    """The influence-function standard error of `sum(p) / sum(q)`.

    The residual of a close is `p_i - theta * q_i`: what it contributed beyond
    what its own risk predicted. This is the textbook ratio-estimator SE, and it
    is the quantity the studentised bootstrap divides by.
    """
    n = profit.size
    t = on_risk(profit, risk) if theta is None else theta
    res = profit - t * risk
    if n < 2:
        return 0.0
    return float(math.sqrt(n / (n - 1) * float((res * res).sum())) / risk.sum())


def draw_idx(n: int, draws: int, rng) -> np.ndarray:
    """`draws` resamples of `n` pairs with replacement, as row index arrays.

    The same draw as `rng.multinomial(n, 1/n, size=draws)` - a count vector and
    a list of `n` sampled indices are two spellings of one resample - and three
    to five times faster, which is the difference between this file finishing
    in an hour and not finishing.
    """
    return rng.integers(0, n, size=(draws, n))


#: Cells in one resample block. `n` closes by `draws` resamples is a dense
#: matrix, and at n=8,000 by 4,000 draws that is a quarter of a gigabyte in one
#: worker - sixty of those is how a research box dies. The draws are taken in
#: chunks instead, which changes nothing about the answer.
CHUNK_CELLS = 2_000_000


def resample_sums(arrays, draws: int, rng) -> list[np.ndarray]:
    """The resampled sum of each array, over one shared set of resamples."""
    n = arrays[0].size
    per = max(1, min(draws, CHUNK_CELLS // max(n, 1)))
    outs: list[list[np.ndarray]] = [[] for _ in arrays]
    left = draws
    while left > 0:
        m = min(per, left)
        idx = draw_idx(n, m, rng)
        for j, a in enumerate(arrays):
            outs[j].append(a[idx].sum(axis=1))
        left -= m
    return [np.concatenate(o) if len(o) > 1 else o[0] for o in outs]


def resample_ratios(profit: np.ndarray, risk: np.ndarray, draws: int, rng) -> np.ndarray:
    """`draws` bootstrap values of `sum(p)/sum(q)`, in bounded memory."""
    p_sum, q_sum = resample_sums([profit, risk], draws, rng)
    return p_sum / q_sum


def boot(profit: np.ndarray, risk: np.ndarray, rng, draws: int = BDRAWS):
    """`spending.interval`, vectorised: the percentile bootstrap the desk runs."""
    n = profit.size
    if n < MIN_INTERVAL_N:
        return None
    ratios = np.sort(resample_ratios(profit, risk, draws, rng))
    return float(ratios[int(draws * 0.025)]), float(ratios[int(draws * 0.975)])


def four_intervals(profit: np.ndarray, risk: np.ndarray, rng, draws: int = BDRAWS,
                   alpha: float = 0.05):
    """Percentile, BCa, studentised and t, on **one** set of resamples.

    Sharing the draws is the point: three of the four are different readings of
    the same bootstrap distribution, so any difference between them is the
    construction and not the seed.
    """
    n = profit.size
    if n < MIN_INTERVAL_N:
        return None
    theta = on_risk(profit, risk)
    se = ratio_se(profit, risk, theta)
    idx = draw_idx(n, draws, rng)
    pg, qg = profit[idx], risk[idx]
    p_sum, q_sum = pg.sum(axis=1), qg.sum(axis=1)
    ratios = p_sum / q_sum
    order = np.sort(ratios)
    lo_i, hi_i = int(draws * alpha / 2), int(draws * (1 - alpha / 2))
    out = {"percentile": (float(order[lo_i]), float(order[min(hi_i, draws - 1)]))}

    # BCa. `z0` is the bootstrap's median bias, `a` the jackknife skewness of
    # the influence values; the jackknife of a ratio of sums is closed form.
    share = float((ratios < theta).mean())
    share = min(max(share, 0.5 / draws), 1.0 - 0.5 / draws)
    z0 = NORM.inv_cdf(share)
    jack = (profit.sum() - profit) / (risk.sum() - risk)
    dev = jack.mean() - jack
    den = 6.0 * float((dev * dev).sum()) ** 1.5
    acc = float((dev ** 3).sum() / den) if den > 0 else 0.0
    ends = []
    for pr in (alpha / 2, 1.0 - alpha / 2):
        zq = NORM.inv_cdf(pr)
        adj = z0 + zq
        frac = NORM.cdf(z0 + adj / (1.0 - acc * adj)) if abs(acc * adj) < 0.999 else pr
        ends.append(float(order[int(np.clip(frac * draws, 0, draws - 1))]))
    out["bca"] = (ends[0], ends[1])

    # Studentised. The per-resample standard error is the same influence
    # formula, expanded so it is three more matrix products rather than a loop.
    s_pp = (pg * pg).sum(axis=1)
    s_pq = (pg * qg).sum(axis=1)
    s_qq = (qg * qg).sum(axis=1)
    num = s_pp - 2.0 * ratios * s_pq + ratios * ratios * s_qq
    se_b = np.sqrt(np.maximum(num, 0.0) * n / (n - 1)) / q_sum
    ok = se_b > 0
    if se > 0 and ok.sum() > 100:
        tstat = np.sort((ratios[ok] - theta) / se_b[ok])
        m = tstat.size
        out["studentised"] = (float(theta - tstat[int(m * (1 - alpha / 2))] * se),
                              float(theta - tstat[int(m * alpha / 2)] * se))
    else:
        out["studentised"] = out["percentile"]

    crit = t_crit(n - 1, alpha)
    out["t on the ratio"] = (theta - crit * se, theta + crit * se)
    return theta, out


METHODS = ("percentile", "bca", "studentised", "t on the ratio")


# ------------------------------------------------------------- null books ----
class World:
    """The pool, plus one permutation of it that every book is cut from."""

    def __init__(self, path: str):
        # `allow_pickle` is for the string name arrays this repo wrote in
        # `calibnull.py` on the same machine minutes earlier - not a foreign file.
        z = np.load(path, allow_pickle=True)
        self.r = z["r"].astype(np.float64)
        self.risk = z["risk_money"].astype(np.float64)
        self.rr = z["reward_to_risk"].astype(np.float64)
        self.exit = np.asarray(z["exit"])
        self.strategy = np.asarray(z["strategy"])
        self.truth = -float(z["cost_r"][0])
        self.names = [str(x) for x in z["strategy_names"]]
        self.by_strategy = {i: np.flatnonzero(self.strategy == i)
                            for i in range(len(self.names))}
        self.profit = self.r * self.risk

    def books(self, sizes: list[int], count: int, rng) -> list[np.ndarray]:
        """`count` books, each with `sizes[i]` closes drawn from strategy `i`."""
        picks = []
        for i, want in enumerate(sizes):
            idx = self.by_strategy[i].copy()
            rng.shuffle(idx)
            need = want * count
            if idx.size < need:
                reps = int(np.ceil(need / idx.size))
                idx = np.concatenate([rng.permutation(self.by_strategy[i])
                                      for _ in range(reps)])
            picks.append(idx[:need].reshape(count, want))
        return [np.concatenate([p[b] for p in picks]) for b in range(count)]


LIVE_SIZES = [n for _, n in N.LIVE_STRATEGIES]
LIVE_ORDER = [nm for nm, _ in N.LIVE_STRATEGIES]
#: `spending.py`'s exit-kind cut on the live book, and its banded cut.
LIVE_EXIT_SIZES = (("hold", 50), ("stop", 42), ("target", 17), ("unknown", 16), ("stale", 8))
LIVE_BAND_SIZES = (("below 1:1", 50), ("1:1 to 2:1", 53), ("2:1 and above", 30))
LIVE_FEED_SIZES = [n for _, n in N.LIVE_FEEDS]
LIVE_INTERVAL_SIZES = [n for _, n in N.LIVE_INTERVALS]
LIVE_HOUR_SIZES = [19, 13, 13, 11, 7, 7, 6, 6, 6, 5, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 2, 1]
#: The published book-wide figure, used as the truth of a second world in [3]:
#: when every strategy really does lose at the book's own rate, how often does a
#: twelve-row cut name one of them as the culprit?
LIVE_BOOK_ON_RISK = -0.2222
#: The published `snap` row, in the units it was published in.
SNAP_N, SNAP_ON_RISK = 29, -0.343


def _slices(per_book: int, books: int, shards: int) -> list[tuple[int, int]]:
    """Disjoint `(offset, count)` blocks of the shared permutation."""
    total = int(_W["order"].size)  # type: ignore[union-attr]
    fit = total // max(per_book, 1)
    take = min(books, fit)
    per = max(1, math.ceil(take / shards))
    out, at = [], 0
    while at < take:
        k = min(per, take - at)
        out.append((at * per_book, k))
        at += k
    return out


def _book(offset: int, k: int, n: int) -> np.ndarray:
    return np.asarray(_W["order"])[offset: offset + k * n].reshape(k, n)


# -------------------------------------------------------------- section one --
def calibrate_instrument(rng) -> list[dict]:
    """Recover rates and constants that are known exactly."""
    led: list[dict] = []
    print("\n[1] THE INSTRUMENT, CALIBRATED AGAINST THINGS THAT ARE KNOWN\n")

    worst = max(abs(t_crit(df) - ref) for df, ref in
                ((15, 2.13145), (28, 2.04841), (132, 1.97824)))
    print(f"  t quantile expansion vs the published table      worst gap {worst:.5f}")
    led.append({"test": "t_crit reproduces the published quantiles to 1e-3",
                "value": worst, "fired": worst > 1e-3})

    # A plain t-test on Gaussian data. If this is not 5%, nothing else counts.
    n = 133
    x = rng.standard_normal((TRIALS, n))
    t = x.mean(axis=1) / (x.std(axis=1, ddof=1) / math.sqrt(n))
    crit = t_crit(n - 1)
    hit = float((np.abs(t) > crit).mean())
    print(f"  t-test, Gaussian, n=133, {TRIALS} trials     rejects "
          f"{fmt_rate(hit, TRIALS)}   nominal  5.00%")
    led.append({"test": "t-test on Gaussian data rejects at 5%",
                "value": hit - 0.05, "fired": abs(hit - 0.05) > 3 * se_rate(0.05, TRIALS)})

    # The same question for the percentile bootstrap on a mean, which is the
    # procedure `spending.py` uses with the ratio replaced by a mean.
    small = 4000
    miss = 0
    r2 = np.random.default_rng(SEED + 1)
    ones = np.ones(n)
    for _ in range(small):
        v = r2.standard_normal(n)
        lo, hi = boot(v, ones, r2, draws=2000)
        miss += int(not (lo <= 0.0 <= hi))
    p = miss / small
    print(f"  percentile bootstrap on a mean, n=133      excludes "
          f"{fmt_rate(p, small)}   nominal  5.00%")
    led.append({"test": "percentile bootstrap on a Gaussian mean excludes at ~5%",
                "value": p - 0.05, "fired": abs(p - 0.05) > 4 * se_rate(0.05, small)})
    return led


def agrees_with_spending(world: World, rng) -> list[dict]:
    """The vectorised bootstrap against `spending.interval`, and against itself.

    Two gaps, on the same books. `self` is `spending.interval` run under two
    seeds - the Monte Carlo noise of the shipping procedure, which is also the
    noise floor on every interval `spending.md` publishes. `ours` is the
    vectorised version against it. The first bounds what the second can mean.
    """
    led: list[dict] = []
    cases = []
    live = _live_pairs()
    if live:
        cases.append(("the live book", live))
    books = world.books(LIVE_SIZES, 20, np.random.default_rng(SEED + 2))
    for i, b in enumerate(books):
        cases.append((f"null book {i}",
                      list(zip(world.profit[b].tolist(), world.risk[b].tolist(), strict=True))))
    self_gaps, our_gaps = [], []
    for label, pairs in cases:
        ref = S.interval(pairs, seed=3)
        alt = S.interval(pairs, seed=17)
        got = boot(np.array([p for p, _ in pairs]), np.array([q for _, q in pairs]),
                   rng, draws=DRAWS)
        if ref is None or got is None or alt is None:
            continue
        self_gaps.append(max(abs(ref[0] - alt[0]), abs(ref[1] - alt[1])))
        our_gaps.append(max(abs(ref[0] - got[0]), abs(ref[1] - got[1])))
        if label == "the live book":
            print(f"\n  the live 133 closes: spending.interval seed 3 "
                  f"[{ref[0] * 100:+.3f}%, {ref[1] * 100:+.3f}%], seed 17 "
                  f"[{alt[0] * 100:+.3f}%, {alt[1] * 100:+.3f}%],"
                  f"\n  vectorised [{got[0] * 100:+.3f}%, {got[1] * 100:+.3f}%]")
    worst_self, worst_ours = max(self_gaps), max(our_gaps)
    print(f"\n  over {len(our_gaps)} books: spending.interval against itself, worst endpoint"
          f" gap {worst_self * 100:.3f} points of risk (median"
          f" {float(np.median(self_gaps)) * 100:.3f});"
          f"\n  vectorised against it, worst {worst_ours * 100:.3f} points (median"
          f" {float(np.median(our_gaps)) * 100:.3f})")
    led.append({"test": "vectorised bootstrap is within 1.5x spending.interval's own seed noise",
                "value": worst_ours - worst_self,
                "fired": worst_ours > max(1.5 * worst_self, 0.004)})
    return led


def _live_pairs():
    for path in (os.environ.get("CLOSES_JSON", ""), ".data/closes.json",
                 os.path.expanduser("~/till_infinity/data/closes.json")):
        if path and os.path.exists(path):
            from pathlib import Path
            rows = S.load(Path(path))
            real = [r for r in rows if not S.generated(r.get("feed"))]
            return S.payable(real)
    return None


# -------------------------------------------------------------- section two --
def _coverage_job(args):
    n, offset, k, seed, draws = args
    rng = np.random.default_rng(seed)
    profit, risk, truth = _W["profit"], _W["risk"], _W["truth"]
    below = above = zlo = zhi = 0
    ests = np.empty(k)
    width = np.empty(k)
    for j, row in enumerate(_book(offset, k, n)):
        p, q = profit[row], risk[row]
        lo, hi = boot(p, q, rng, draws=draws)
        ests[j] = on_risk(p, q)
        width[j] = hi - lo
        if hi < truth:
            below += 1
        elif lo > truth:
            above += 1
        if hi < 0.0:
            zlo += 1
        elif lo > 0.0:
            zhi += 1
    return n, k, below, above, zlo, zhi, ests, width


def coverage(world: World, draws: int = BDRAWS, sizes=None, quiet: bool = False):
    """Does a 95% interval on return-on-risk cover the true value 95% of the time?"""
    if not quiet:
        print("\n[2] COVERAGE OF THE 95% BOOTSTRAP INTERVAL ON RETURN-ON-RISK\n")
        print("    the true value is the same everywhere in this world: "
              f"{world.truth * 100:+.2f}% of risk\n")
    sizes = sizes or (8, 16, 17, 23, 28, 29, 50, 100, 133, 300, 685, 1000)
    jobs = []
    for i, n in enumerate(sizes):
        for s, (off, k) in enumerate(_slices(n, BOOKS, WORKERS)):
            jobs.append((n, off, k, SEED + 31 * i + 7717 * s, draws))
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(_coverage_job, jobs)
    acc: dict[int, dict] = {}
    for n, k, below, above, zlo, zhi, ests, width in got:
        a = acc.setdefault(n, {"k": 0, "below": 0, "above": 0, "zlo": 0, "zhi": 0,
                               "ests": [], "width": []})
        a["k"] += k
        a["below"] += below
        a["above"] += above
        a["zlo"] += zlo
        a["zhi"] += zhi
        a["ests"].append(ests)
        a["width"].append(width)
    out = {}
    led: list[dict] = []
    if not quiet:
        print(f"  {'n':>6} {'books':>7} {'excl truth':>17} {'below':>7} {'above':>7} "
              f"{'excl 0 below':>17} {'excl 0 above':>13} {'median width':>13}")
    for n in sizes:
        a = acc[n]
        k = a["k"]
        fpr = (a["below"] + a["above"]) / k
        width = np.concatenate(a["width"])
        row = {"fpr": fpr, "n_books": k, "below": a["below"] / k, "above": a["above"] / k,
               "zero_lo": a["zlo"] / k, "zero_hi": a["zhi"] / k,
               "zero": (a["zlo"] + a["zhi"]) / k, "ests": np.concatenate(a["ests"]),
               "width": float(np.median(width))}
        out[n] = row
        if not quiet:
            print(f"  {n:6d} {k:7d} {fmt_rate(fpr, k):>17} {row['below'] * 100:6.2f}% "
                  f"{row['above'] * 100:6.2f}% {fmt_rate(row['zero_lo'], k):>17} "
                  f"{fmt_rate(row['zero_hi'], k):>13} {row['width'] * 100:12.1f}%")
    for n in (29, 133):
        if n in out:
            led.append({"test": f"coverage at n={n} is within 1 SE of nominal",
                        "value": out[n]["fpr"] - 0.05,
                        "fired": abs(out[n]["fpr"] - 0.05) <= se_rate(0.05, out[n]["n_books"])})
    for n, row in out.items():
        if G.exactly_null(row["fpr"], 0.05, places=4):
            led.append({"test": f"coverage at n={n} is not exactly 0.0500",
                        "value": row["fpr"] - 0.05, "fired": True})
    return out, led


def draws_agree(world: World, cov: dict) -> list[dict]:
    """Condition 9: the cheap bootstrap against the shipping 20,000."""
    print(f"\n  the same coverage at {DRAWS} resamples, at the two sizes that matter:\n")
    ref, _ = coverage(world, draws=DRAWS, sizes=(29, 133), quiet=True)
    led = []
    for n in (29, 133):
        a, b = cov[n], ref[n]
        gap = a["fpr"] - b["fpr"]
        tol = 2 * math.hypot(se_rate(a["fpr"], a["n_books"]), se_rate(b["fpr"], b["n_books"]))
        print(f"    n={n:4d}  {BDRAWS} draws {fmt_rate(a['fpr'], a['n_books'])}   "
              f"{DRAWS} draws {fmt_rate(b['fpr'], b['n_books'])}   gap {gap * 100:+.2f} points")
        led.append({"test": f"BDRAWS agrees with {DRAWS} draws at n={n}",
                    "value": gap, "fired": abs(gap) > tol})
    return led


# ------------------------------------------------------------ section three --
def _table_job(args):
    """One cut of `k` null books, returning per-row outcomes.

    `shift` moves the whole world's true return on risk without changing its
    shape: adding `shift * risk` to every profit moves the ratio of sums by
    exactly `shift`, on every book and every row of it. It is how the twelve-row
    cut is also run in a world that loses at the book's own rate.
    """
    sizes, offset, k, seed, shift, draws = args
    rng = np.random.default_rng(seed)
    profit, risk, truth = _W["profit"], _W["risk"], _W["truth"]
    if shift:
        profit = profit + shift * risk
        truth = truth + shift
    total = sum(sizes)
    any_truth = np.zeros(k, dtype=bool)
    any_zero = np.zeros(k, dtype=bool)
    per_truth = np.zeros((k, len(sizes)), dtype=bool)
    per_zero = np.zeros((k, len(sizes)), dtype=bool)
    ests = np.full((k, len(sizes)), np.nan)
    tested = np.zeros(len(sizes), dtype=np.int64)
    for b, block in enumerate(_book(offset, k, total)):
        at = 0
        for j, want in enumerate(sizes):
            sel = block[at:at + want]
            at += want
            p, q = profit[sel], risk[sel]
            ests[b, j] = on_risk(p, q)
            got = boot(p, q, rng, draws=draws)
            if got is None:
                continue
            tested[j] += 1
            if not (got[0] <= truth <= got[1]):
                per_truth[b, j] = True
                any_truth[b] = True
            if not (got[0] <= 0.0 <= got[1]):
                per_zero[b, j] = True
                any_zero[b] = True
    return k, any_truth, any_zero, per_truth, per_zero, ests, tested


def run_table(sizes, seed: int, books: int, shift: float = 0.0):
    total = sum(sizes)
    jobs = [(list(sizes), off, k, seed + 991 * s, shift, BDRAWS)
            for s, (off, k) in enumerate(_slices(total, books, WORKERS))]
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(_table_job, jobs)
    return {"books": sum(g[0] for g in got),
            "any_truth": np.concatenate([g[1] for g in got]),
            "any_zero": np.concatenate([g[2] for g in got]),
            "per_truth": np.concatenate([g[3] for g in got]),
            "per_zero": np.concatenate([g[4] for g in got]),
            "ests": np.concatenate([g[5] for g in got]),
            "tested": np.sum([g[6] for g in got], axis=0)}


def cost_of_cutting(world: World) -> tuple[dict, list[dict]]:
    print("\n[3] THE COST OF CUTTING - how often at least one row lights up\n")
    cuts = {
        "strategy (12 rows, live sizes)": LIVE_SIZES,
        "exit kind (5 rows, live sizes)": [n for _, n in LIVE_EXIT_SIZES],
        "reward-to-risk bands (3 rows)": [n for _, n in LIVE_BAND_SIZES],
        "interval (7 rows, live sizes)": LIVE_INTERVAL_SIZES,
        "hour (24 rows, live sizes)": LIVE_HOUR_SIZES,
        "feed (26 rows, live sizes)": LIVE_FEED_SIZES,
    }
    out = {}
    print(f"  {'cut':34} {'rows':>5} {'>=8':>4} {'books':>6} "
          f"{'>=1 excl truth':>16} {'>=1 excl zero':>16}")
    for label, sizes in cuts.items():
        got = run_table(sizes, SEED + 7 * len(label), BOOKS)
        out[label] = got
        wide = sum(1 for s in sizes if s >= MIN_INTERVAL_N)
        b = got["books"]
        print(f"  {label:34} {len(sizes):5d} {wide:4d} {b:6d} "
              f"{fmt_rate(float(got['any_truth'].mean()), b):>16} "
              f"{fmt_rate(float(got['any_zero'].mean()), b):>16}")

    # The whole page at once: every interval one `spending.py` run prints.
    page = (LIVE_SIZES + [n for _, n in LIVE_EXIT_SIZES] + [n for _, n in LIVE_BAND_SIZES])
    got = run_table(page, SEED + 4242, BOOKS)
    out["page"] = got
    wide = sum(1 for s in page if s >= MIN_INTERVAL_N)
    print(f"\n  {'one spending.py run (all three cuts)':34} {len(page):5d} {wide:4d} "
          f"{got['books']:6d} {fmt_rate(float(got['any_truth'].mean()), got['books']):>16} "
          f"{fmt_rate(float(got['any_zero'].mean()), got['books']):>16}")

    # How the rate grows as rows are added, in the live order (largest first).
    print("\n  the twelve-row table, row by row (cumulative, largest row first)\n")
    print(f"  {'rows':>5} {'name':16} {'n':>4} {'this row alone':>16} "
          f"{'>=1 so far':>16} {'>=1 excl zero':>16}")
    st = out["strategy (12 rows, live sizes)"]
    cum = np.zeros(st["books"], dtype=bool)
    cum_z = np.zeros(st["books"], dtype=bool)
    for j, (name, n) in enumerate(N.LIVE_STRATEGIES):
        cum = cum | st["per_truth"][:, j]
        cum_z = cum_z | st["per_zero"][:, j]
        alone = float(st["per_truth"][:, j].mean())
        print(f"  {j + 1:5d} {name:16} {n:4d} "
              f"{(fmt_rate(alone, st['books']) if n >= MIN_INTERVAL_N else 'too few to say'):>16} "
              f"{fmt_rate(float(cum.mean()), st['books']):>16} "
              f"{fmt_rate(float(cum_z.mean()), st['books']):>16}")

    # The second world: every row truly loses at the book's own rate. This is the
    # null `spending.md`'s reading actually needs, because the claim is not
    # "snap loses" - the whole book loses - it is "snap is the one that is
    # separately identifiable". A cut of a uniformly losing book will name a
    # culprit; the question is how often it names one that is not there.
    shift = LIVE_BOOK_ON_RISK - world.truth
    print(f"\n  the same cuts in a world where every row truly runs at the book's own")
    print(f"  {LIVE_BOOK_ON_RISK * 100:+.1f}% of risk - so every row that is named is named wrongly\n")
    print(f"  {'cut':34} {'books':>6} {'>=1 excl truth':>16} {'>=1 excl zero':>16} "
          f"{'>=1 <= -34.3% and excl 0':>25}")
    for label, sizes in list(cuts.items()) + [("one spending.py run (all three)", page)]:
        got2 = run_table(sizes, SEED + 31337 + len(label), BOOKS, shift=shift)
        out["book rate: " + label] = got2
        b = got2["books"]
        hit = float((((got2["ests"] <= SNAP_ON_RISK) & got2["per_zero"]).any(axis=1)).mean())
        print(f"  {label:34} {b:6d} {fmt_rate(float(got2['any_truth'].mean()), b):>16} "
              f"{fmt_rate(float(got2['any_zero'].mean()), b):>16} {fmt_rate(hit, b):>25}")
    got2 = out["book rate: strategy (12 rows, live sizes)"]
    b = got2["books"]
    first = float(got2["per_zero"][:, 0].mean())
    print(f"\n  in that world the 29-close row alone excludes zero {fmt_rate(first, b)}"
          f" of the time,\n  and reads <= {SNAP_ON_RISK * 100:.1f}% as well in "
          f"{fmt_rate(float(((got2['ests'][:, 0] <= SNAP_ON_RISK) & got2['per_zero'][:, 0]).mean()), b)}.")

    led = [{"test": "the twelve-row cut fires more often than one row does",
            "value": float(st["any_truth"].mean()) - float(st["per_truth"][:, 0].mean()),
            "fired": float(st["any_truth"].mean()) <= float(st["per_truth"][:, 0].mean())}]
    return out, led


# ------------------------------------------------------------- section four --
def magnitudes(world: World, cuts: dict, cov: dict) -> None:
    print("\n[4] HOW LARGE A FALSE EFFECT GETS\n")
    st = cuts["strategy (12 rows, live sizes)"]
    ests, flags = st["ests"], st["per_truth"]
    wide = [j for j, (_, n) in enumerate(N.LIVE_STRATEGIES) if n >= MIN_INTERVAL_N]
    print(f"  {'row':16} {'n':>4} {'all books, 95% of them':>26} "
          f"{'when it excludes the truth':>30}")
    for j in wide:
        name, n = N.LIVE_STRATEGIES[j]
        col = ests[:, j]
        sel = col[flags[:, j]]
        band = (f"[{np.percentile(sel, 2.5) * 100:+6.1f}%, "
                f"{np.percentile(sel, 97.5) * 100:+6.1f}%]" if sel.size > 20 else "too few")
        print(f"  {name:16} {n:4d} "
              f"[{np.percentile(col, 2.5) * 100:+6.1f}%, {np.percentile(col, 97.5) * 100:+6.1f}%]"
              f"   n={sel.size:5d} {band:>24}")

    j = 0
    col, flag = ests[:, j], st["per_zero"][:, j]
    hit = float(((col <= SNAP_ON_RISK) & flag).mean())
    print(f"\n  a null book's {SNAP_N}-close row reads <= {SNAP_ON_RISK * 100:.1f}% of risk"
          f" *and* excludes zero:  {fmt_rate(hit, st['books'])}")
    any_hit = float((((ests <= SNAP_ON_RISK) & st["per_zero"]).any(axis=1)).mean())
    print(f"  ... at least one of the twelve rows does:  {fmt_rate(any_hit, st['books'])}")
    worst = ests[:, wide].min(axis=1)
    print(f"  worst of the {len(wide)} rows that get an interval: median "
          f"{np.median(worst) * 100:+.1f}% of risk, 5th percentile "
          f"{np.percentile(worst, 5) * 100:+.1f}%, 1st {np.percentile(worst, 1) * 100:+.1f}%")
    best = ests[:, wide].max(axis=1)
    print(f"  best of the same rows:                     median "
          f"{np.median(best) * 100:+.1f}% of risk, 95th percentile "
          f"{np.percentile(best, 95) * 100:+.1f}%, 99th {np.percentile(best, 99) * 100:+.1f}%")

    # The book-wide figure, which is the one number on that page that was not a
    # cut, at the size it was measured at.
    row = cov.get(133)
    if row is not None:
        e = row["ests"]
        print(f"\n  the book-wide figure over 133 closes, which was not a cut: 95% of null"
              f" books\n  land in [{np.percentile(e, 2.5) * 100:+.1f}%,"
              f" {np.percentile(e, 97.5) * 100:+.1f}%] of risk, and"
              f" {float((e <= -0.2222).mean()) * 100:.2f}% of them read <= -22.2%.")
        print(f"  its interval excludes zero in {fmt_rate(row['zero'], row['n_books'])}"
              f" of books ({fmt_rate(row['zero_lo'], row['n_books'])} below,"
              f" {fmt_rate(row['zero_hi'], row['n_books'])} above).")


# ------------------------------------------------------------- section five --
def _reversal_job(args):
    """`spending.md`'s two monotone tables, rebuilt on null books.

    The bands are cut the way `spending.py::banded` cuts them - on each close's
    own `reward_to_risk`, at 1.0 and 2.0 - rather than at the live counts, so
    the row sizes vary between books exactly as they would on a real one.
    """
    offset, k, seed = args
    rng = np.random.default_rng(seed)
    profit, risk, rr, exk, truth = (_W["profit"], _W["risk"], _W["rr"], _W["exit"],
                                    _W["truth"])
    r = _W["r"]
    mono = mono_dir = mono_sig = kept_mono = both = 0
    counted = 0
    for block in _book(offset, k, 133):
        band = np.digitize(rr[block], [1.0, 2.0])
        vals, sig, ok = [], [], True
        for bi in (0, 1, 2):
            m = band == bi
            if m.sum() < MIN_INTERVAL_N:
                ok = False
                break
            p, q = profit[block][m], risk[block][m]
            vals.append(on_risk(p, q))
            got = boot(p, q, rng)
            sig.append(got is not None and not (got[0] <= truth <= got[1]))
        if not ok:
            continue
        counted += 1
        down = vals[0] > vals[1] > vals[2]
        up = vals[0] < vals[1] < vals[2]
        band_mono = up or down
        if band_mono:
            mono += 1
            if down:
                mono_dir += 1
            if sig[0] or sig[-1]:
                mono_sig += 1
        # The second table: exit kinds ordered by what they aimed at, scored on
        # the share of that aim they kept. `spending.md` reads the two tables
        # agreeing as independent corroboration.
        aims, keeps = [], []
        for kind in (0, 1, 2):
            m = exk[block] == kind
            if m.sum() < 5:
                aims = []
                break
            aim = float(np.median(rr[block][m]))
            aims.append(aim)
            keeps.append(float(np.median(r[block][m]) / aim) if aim else np.nan)
        if aims and not any(math.isnan(x) for x in keeps):
            order = np.argsort(aims)
            seq = [keeps[i] for i in order]
            if seq[0] > seq[1] > seq[2]:
                kept_mono += 1
                if band_mono:
                    both += 1
    return counted, mono, mono_dir, mono_sig, kept_mono, both


def reversals(world: World) -> None:
    print("\n[5] DOES THE NULL WORLD PRODUCE THE SHAPES THAT WERE READ AS FINDINGS\n")
    jobs = [(off, k, SEED + 55 * s) for s, (off, k) in enumerate(_slices(133, BOOKS, WORKERS))]
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(_reversal_job, jobs)
    take = sum(g[0] for g in got)
    mono, mono_dir, mono_sig, kept, both = (sum(g[i] for g in got) for i in range(1, 6))
    print(f"  133-close null books banded on their own reward-to-risk at 1.0 and 2.0,")
    print(f"  {take} of them with all three bands at n>=8")
    print(f"    monotone in return on risk, either direction: "
          f"{fmt_rate(mono / take, take)}   (chance is 33.33%)")
    print(f"    monotone *and* falling, as published:          "
          f"{fmt_rate(mono_dir / take, take)}   (chance is 16.67%)")
    print(f"    monotone *and* an end band excludes the truth: "
          f"{fmt_rate(mono_sig / take, take)}")
    print(f"\n  the second table - exit kinds ordered by what they aimed at, scored on")
    print(f"  what they kept - comes out monotone in a null book "
          f"{fmt_rate(kept / take, take)} of the time,")
    print(f"  and **both tables monotone at once** in {fmt_rate(both / take, take)}"
          f"   (independent would be {mono / take * kept / take * 100:.2f}%)")

    # strata.compare, at the sample size the desk has.
    print(f"\n  shared.strata.compare on {min(BOOKS, 400)} null books of 133 closes,")
    print(f"  bucketing by the reward-to-risk band and by feed, within strategy"
          f" and interval:\n")
    rng = np.random.default_rng(SEED + 99)
    ivals = np.repeat([nm for nm, _ in N.LIVE_INTERVALS], [n for _, n in N.LIVE_INTERVALS])
    strat = np.repeat(LIVE_ORDER, LIVE_SIZES)
    feeds = np.repeat([nm for nm, _ in N.LIVE_FEEDS], [n for _, n in N.LIVE_FEEDS])
    trials = min(BOOKS, 400)
    for bucket in ("band", "feed"):
        for min_n in (100, 25, 10):
            flagged = thin_all = 0
            for _ in range(trials):
                sel = rng.permutation(world.profit.size)[:133]
                rows = [{"r": float(world.r[i]),
                         "band": ("below 1:1" if world.rr[i] < 1
                                  else "1:1 to 2:1" if world.rr[i] < 2 else "2:1 and above"),
                         "strategy": strat[k], "interval": ivals[k], "feed": feeds[k]}
                        for k, i in enumerate(sel)]
                cmp_got = compare(rows, value="r", bucket=bucket, min_n=min_n)
                flagged += int(bool(cmp_got.reversals))
                thin_all += int(all(s.thin for s in cmp_got.strata.values()))
            print(f"    bucket={bucket:5} min_n={min_n:3d}  a reversal is flagged "
                  f"{fmt_rate(flagged / trials, trials)}   every stratum thin in "
                  f"{thin_all / trials * 100:5.1f}% of books")


# -------------------------------------------------------------- section six --
def _power_job(args):
    n, delta, seed, count, alpha = args
    rng = np.random.default_rng(seed)
    profit, risk, truth = _W["profit"], _W["risk"], _W["truth"]
    lift = delta - truth  # so the book's true return on risk is exactly `delta`
    lo_i = int(BDRAWS * alpha / 2)
    hits = 0
    for _ in range(count):
        sel = rng.integers(0, profit.size, n)
        p = profit[sel] + lift * risk[sel]
        q = risk[sel]
        if n < MIN_INTERVAL_N:
            continue
        ratios = np.sort(resample_ratios(p, q, BDRAWS, rng))
        if float(ratios[lo_i]) > 0.0:
            hits += 1
    return n, delta, alpha, count, hits


def power(world: World) -> list[dict]:
    print("\n[6] POWER - the other half\n")
    print("    a strategy whose true return on risk is +delta after costs; the test is")
    print("    the one the desk runs, a 95% bootstrap interval that excludes zero.\n")
    grid = (100, 250, 500, 1000, 2000, 4000, 8000)
    deltas = (0.02, 0.05, 0.10)
    alphas = (0.05, 0.05 / 5)
    trials = max(200, BOOKS // 4)
    per = max(20, trials // WORKERS)
    jobs = []
    for a in alphas:
        for d in deltas:
            for n in grid:
                for s in range(max(1, trials // per)):
                    jobs.append((n, d, SEED + 13 * s + int(d * 1000) + n + int(a * 1e5),
                                 per, a))
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(_power_job, jobs)
    acc: dict[tuple, list[int]] = {}
    for n, d, a, c, h in got:
        row = acc.setdefault((n, d, a), [0, 0])
        row[0] += c
        row[1] += h
    sd = float(world.r.std(ddof=1))
    led: list[dict] = []
    for a in alphas:
        label = "uncorrected 5%" if a == 0.05 else "Bonferroni over five rows (1%)"
        print(f"  -- {label}")
        print(f"  {'delta':>7} " + " ".join(f"{n:>8d}" for n in grid) + "    n for 80%, normal")
        for d in deltas:
            cells = [acc[(n, d, a)] for n in grid]
            row = " ".join(f"{h / c * 100:7.1f}%" for c, h in cells)
            z = NORM.inv_cdf(1 - a / 2)
            need = ((z + 0.8416) * sd / d) ** 2
            print(f"  {d * 100:6.0f}% {row}    {need:9.0f}")
            xs = [(n, h / c) for n, (c, h) in zip(grid, cells, strict=True)]
            emp = None
            for (n0, p0), (n1, p1) in zip(xs, xs[1:], strict=False):
                if p0 < 0.8 <= p1:
                    emp = math.exp(math.log(n0) + (0.8 - p0) / (p1 - p0)
                                   * (math.log(n1) - math.log(n0)))
                    break
            print(f"          empirical 80% point: "
                  f"{('%.0f closes' % emp) if emp else 'beyond ' + str(grid[-1])}")
            if d == 0.05 and a == 0.05:
                seen = acc[(1000, 0.05, 0.05)][1] / acc[(1000, 0.05, 0.05)][0]
                led.append({"test": "power at spending.md's quoted 1,000 closes for +5% is 80%",
                            "value": seen - 0.80, "fired": abs(seen - 0.80) > 0.05})
        print()
    print(f"  `spending.md` quotes about 1,000 closes for +5% and 250 for +10%, from")
    print(f"  n = (1.96 * sd / delta)^2 with sd = 0.805. That is the sample size at which")
    print(f"  the estimate sits 1.96 SE from zero *on average*, which is 50% power, not 80%.")
    return led


# ------------------------------------------------------------ section seven --
def _methods_job(args):
    n, offset, k, seed = args
    rng = np.random.default_rng(seed)
    profit, risk, truth = _W["profit"], _W["risk"], _W["truth"]
    miss = {m: [0, 0] for m in METHODS}   # below the truth, above it
    zero = {m: [0, 0] for m in METHODS}   # entirely below zero, entirely above
    width = {m: 0.0 for m in METHODS}
    done = 0
    for row in _book(offset, k, n):
        p, q = profit[row], risk[row]
        got = four_intervals(p, q, rng)
        if got is None:
            continue
        done += 1
        _, ivals = got
        for m in METHODS:
            lo, hi = ivals[m]
            if hi < truth:
                miss[m][0] += 1
            elif lo > truth:
                miss[m][1] += 1
            if hi < 0.0:
                zero[m][0] += 1
            elif lo > 0.0:
                zero[m][1] += 1
            width[m] += hi - lo
    return n, done, miss, zero, width


def methods(world: World) -> list[dict]:
    print("\n[7] IS IT THE BOOTSTRAP OR IS IT THE SAMPLE SIZE\n")
    print("    four intervals on the same books and the same resamples. The truth is"
          f" {world.truth * 100:+.2f}%.\n")
    sizes = (16, 29, 50, 133)
    jobs = []
    for i, n in enumerate(sizes):
        for s, (off, k) in enumerate(_slices(n, BOOKS, WORKERS)):
            jobs.append((n, off, k, SEED + 811 * i + 13 * s))
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(_methods_job, jobs)
    acc: dict[int, dict] = {}
    for n, done, miss, zero, width in got:
        a = acc.setdefault(n, {"done": 0, "miss": {m: [0, 0] for m in METHODS},
                               "zero": {m: [0, 0] for m in METHODS},
                               "width": dict.fromkeys(METHODS, 0.0)})
        a["done"] += done
        for m in METHODS:
            a["miss"][m][0] += miss[m][0]
            a["miss"][m][1] += miss[m][1]
            a["zero"][m][0] += zero[m][0]
            a["zero"][m][1] += zero[m][1]
            a["width"][m] += width[m]
    print(f"  {'n':>5} {'method':16} {'books':>7} {'excludes truth':>16} "
          f"{'below':>7} {'above':>7} {'excl 0':>15} {'mean width':>11}")
    best: dict[int, tuple[str, float]] = {}
    for n in sizes:
        a = acc[n]
        d = a["done"]
        for m in METHODS:
            lo, hi = a["miss"][m]
            fpr = (lo + hi) / d
            z = (a["zero"][m][0] + a["zero"][m][1]) / d
            print(f"  {n:5d} {m:16} {d:7d} {fmt_rate(fpr, d):>16} {lo / d * 100:6.2f}% "
                  f"{hi / d * 100:6.2f}% {fmt_rate(z, d):>15} {a['width'][m] / d * 100:10.1f}%")
            if n not in best or abs(fpr - 0.05) < best[n][1]:
                best[n] = (m, abs(fpr - 0.05))
        print()
    led = []
    for n in (29, 133):
        if n in best:
            print(f"  closest to nominal at n={n}: {best[n][0]}")
    pct = (acc[29]["miss"]["percentile"][0] + acc[29]["miss"]["percentile"][1]) / acc[29]["done"]
    alt = min((abs((acc[29]["miss"][m][0] + acc[29]["miss"][m][1]) / acc[29]["done"] - 0.05), m)
              for m in METHODS if m != "percentile")
    led.append({"test": "some other construction beats the percentile bootstrap at n=29",
                "value": abs(pct - 0.05) - alt[0], "fired": alt[0] >= abs(pct - 0.05)})
    return led


def studentised(profit: np.ndarray, risk: np.ndarray, rng, draws: int, alpha: float):
    """The bootstrap-t interval at an arbitrary alpha.

    `[7]` finds this is the construction that holds its nominal rate at the row
    sizes a strategy table has, so `[8]` asks what it does when the alpha is
    also corrected - which is the combination this page ends up recommending
    and therefore the one that has to be measured rather than assumed.
    """
    n = profit.size
    theta = on_risk(profit, risk)
    se = ratio_se(profit, risk, theta)
    if se <= 0:
        return None
    idx = draw_idx(n, draws, rng)
    pg, qg = profit[idx], risk[idx]
    q_sum = qg.sum(axis=1)
    ratios = pg.sum(axis=1) / q_sum
    num = (pg * pg).sum(axis=1) - 2.0 * ratios * (pg * qg).sum(axis=1) \
        + ratios * ratios * (qg * qg).sum(axis=1)
    se_b = np.sqrt(np.maximum(num, 0.0) * n / (n - 1)) / q_sum
    ok = se_b > 0
    if ok.sum() < 100:
        return None
    t = np.sort((ratios[ok] - theta) / se_b[ok])
    m = t.size
    hi_i = min(int(m * (1 - alpha / 2)), m - 1)
    return float(theta - t[hi_i] * se), float(theta - t[int(m * alpha / 2)] * se)


def _corrected_job(args):
    """The same cut at a corrected alpha, by one interval construction.

    Run at the shipping 20,000 resamples rather than `BDRAWS`: a Bonferroni
    alpha of 0.05/12 asks for the 0.21% quantile of the bootstrap distribution,
    and four thousand draws put sixteen of them below it. A correction judged on
    a quantile estimated from sixteen points is judging the draw count.
    """
    sizes, offset, k, seed, alpha, method = args
    rng = np.random.default_rng(seed)
    profit, risk, truth = _W["profit"], _W["risk"], _W["truth"]
    total = sum(sizes)
    lo_i, hi_i = int(DRAWS * alpha / 2), min(int(DRAWS * (1 - alpha / 2)), DRAWS - 1)
    any_out = np.zeros(k, dtype=bool)
    any_zero = np.zeros(k, dtype=bool)
    for b, block in enumerate(_book(offset, k, total)):
        at = 0
        for want in sizes:
            sel = block[at:at + want]
            at += want
            if want < MIN_INTERVAL_N:
                continue
            p, q = profit[sel], risk[sel]
            if method == "studentised":
                got = studentised(p, q, rng, DRAWS, alpha)
                if got is None:
                    continue
                lo, hi = got
            else:
                ratios = np.sort(resample_ratios(p, q, DRAWS, rng))
                lo, hi = float(ratios[lo_i]), float(ratios[hi_i])
            if not (lo <= truth <= hi):
                any_out[b] = True
            if not (lo <= 0.0 <= hi):
                any_zero[b] = True
    return k, int(any_out.sum()), int(any_zero.sum())


def correction(world: World) -> list[dict]:
    print("\n[8] DOES THE CORRECTION WORK\n")
    del world
    wide = sum(1 for n in LIVE_SIZES if n >= MIN_INTERVAL_N)
    alphas = {"uncorrected 5%": 0.05,
              f"Bonferroni over the {wide} rows that get an interval": 0.05 / wide,
              "Bonferroni over all 12 rows": 0.05 / 12,
              f"Sidak over {wide}": 1 - (1 - 0.05) ** (1 / wide)}
    led: list[dict] = []
    total = sum(LIVE_SIZES)
    print(f"  {'':52} {'percentile':>26}   {'studentised':>26}")
    for label, a in alphas.items():
        line = f"  {label:52}"
        for method in ("percentile", "studentised"):
            jobs = [(LIVE_SIZES, off, k, SEED + 17 * s + int(a * 1e6), a, method)
                    for s, (off, k) in enumerate(_slices(total, BOOKS, WORKERS))]
            with CTX.Pool(WORKERS) as pool:
                got = pool.map(_corrected_job, jobs)
            take = sum(g[0] for g in got)
            hit = sum(g[1] for g in got)
            zero = sum(g[2] for g in got)
            line += f" {fmt_rate(hit / take, take):>13} / 0:{fmt_rate(zero / take, take):>13}"
            if "Bonferroni over the" in label:
                led.append({"test": f"Bonferroni over the {wide} rows restores 5%, {method}",
                            "value": hit / take - 0.05,
                            "fired": hit / take > 0.05 + 3 * se_rate(0.05, take)})
        print(line)
    print("\n  each cell: how often at least one of the twelve rows excludes the truth,"
          "\n  then how often at least one excludes zero.")
    return led


def main() -> None:
    t0 = time.time()
    print("CALIBRATING THE DESK'S OWN ANALYSIS AGAINST A WORLD WITH NO EDGE IN IT")
    print(f"machine: {G.machine()}   pool {POOL}   books {BOOKS}   seed {SEED}"
          f"   draws {BDRAWS} (shipping {DRAWS})")
    world = World(POOL)
    print(f"pool: {world.r.size} closes, truth {world.truth * 100:+.3f}% of risk, "
          f"per-close sd {world.r.std(ddof=1):.4f}")
    rng = np.random.default_rng(SEED)
    _W.update({"profit": world.profit, "risk": world.risk, "r": world.r, "rr": world.rr,
               "exit": world.exit, "truth": world.truth,
               "order": np.random.default_rng(SEED + 5).permutation(world.r.size)})
    led = calibrate_instrument(rng)
    led += agrees_with_spending(world, rng)
    if any(x["fired"] for x in led):
        print("\n  ** the instrument did not calibrate. Nothing below is reported. **")
        for row in led:
            print(f"  {'FIRED ' if row['fired'] else 'held  '} {row['test']}")
        return
    cov, l2 = coverage(world)
    led += l2 + draws_agree(world, cov)
    cuts, l3 = cost_of_cutting(world)
    magnitudes(world, cuts, cov)
    reversals(world)
    led += l3 + power(world) + methods(world) + correction(world)
    print("\n[LEDGER] the conditions written down before the numbers\n")
    for row in led:
        print(f"  {'FIRED ' if row['fired'] else 'held  '} {row['test']:64} "
              f"{row['value']:+.4f}")
    print(f"\n  {sum(1 for x in led if x['fired'])} of {len(led)} fired"
          f"   ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
