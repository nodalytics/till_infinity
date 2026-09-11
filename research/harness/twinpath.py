"""Are `volatility_75_index` and `volatility_75_1s_index` the same path?

Deriv publishes each volatility index twice: a standard series that prints
about every two seconds and a `_1s_` series that prints every second. If those
are one path sampled at two rates, the fast quote is a higher-resolution view
of the slow one and you can see where the slow one is going before it prints.
That is not an edge, it is a free lunch, so the prior against it is enormous -
which is exactly why it is worth ten minutes of a 64-core machine to kill.

`research/generated.md` already killed the *minute-bar* version of this: 325
pairs at seven lags, twins at |corr| 0.0085 against strangers reaching 0.0129.
So a wall-clock identical path is already dead - it would have shown up at 1m
as a correlation near one. What that study could not see, and this one can:

* a **lead of seconds**, which a one-minute bar averages into nothing;
* a **tail** relationship - shared jumps without a correlated body;
* a shared **tick-index** alignment, which is what a shared PRNG stream
  consumed at two different rates would look like in *index* space rather
  than in wall-clock space.

This file measures those three on the tick table. The bar-level questions -
the volatility clock and whether the stated 75%-annualised law is even true -
are in `twinclock.py`, which has 60 days rather than this one's 24 hours.

## The control decides the test

Every statistic here is computed identically on three kinds of pair:

* **twin**     - `volatility_75_index` / `volatility_75_1s_index`
* **mismatch** - `volatility_75_index` / `volatility_100_1s_index`, and every
                 other volatility pair that is not a twin. Same generator
                 family, same tick-rate mixture, no claimed relationship.
* **stranger** - a volatility index against Boom, Crash, Jump, Step.

A twin is only interesting if it stands outside what the mismatches do. Taking
the maximum over 1,201 lags is a search over 1,201 chances, and the largest of
1,201 noise draws is not small - so the mismatches are maximised over the same
1,201 lags, and the comparison is like for like. This is the discipline
`research/generated.md` recorded: the single largest correlation in that study
was between two *unrelated* instruments.

## And a positive control on the machinery itself

Two failures on this project were tables that were arithmetic rather than
results (`research/forecasting.md`), and one was a statistic that landed on
exactly its null because the column was dead (`research/giveback.md`). So
before any pair is measured, the estimator is handed a series that is a known
lag and a known correlation away from a real one, and has to recover both. If
the planted pair does not come back, no null on this page means anything.
"""

from __future__ import annotations

import math
import os
import sqlite3
import time
from collections import Counter
from itertools import combinations

import numpy as np
from scipy import signal

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))

#: Seconds either side of zero to scan. Ten minutes each way: far past any
#: plausible "the fast feed leads the slow one" story, and the width is the
#: point - a narrow window cannot tell a peak from a trend.
MAXLAG = int(os.environ.get("MAXLAG", "600"))
#: Percentile cuts for the tail test, and the co-jump windows in seconds.
TAIL_QS = (99.5, 99.9)
TAIL_WINDOWS = (1, 2, 5)
#: Rotations used to build the co-jump null from the data rather than assume it.
ROTATIONS = int(os.environ.get("ROTATIONS", "200"))
SEED = int(os.environ.get("SEED", "20260911"))

PARAMS = ("10", "25", "50", "75", "100")
SLOW = [f"volatility_{p}_index" for p in PARAMS]
FAST = [f"volatility_{p}_1s_index" for p in PARAMS]
EXTRA_FAST = ["volatility_150_1s_index", "volatility_250_1s_index"]
STRANGERS = ["boom_500_index", "crash_500_index", "jump_25_index", "step_index"]
FEEDS = SLOW + FAST + EXTRA_FAST + STRANGERS

COMPARISONS = Counter()


def bump(name: str, n: int = 1) -> None:
    """Every number this file looks at, counted, so the write-up can hold
    results to the size of the search that produced them."""
    COMPARISONS[name] += n


def kind(a: str, b: str) -> str:
    va, vb = a.startswith("volatility"), b.startswith("volatility")
    if not (va and vb):
        return "stranger"
    pa = a.replace("_1s_", "_").replace("volatility_", "").replace("_index", "")
    pb = b.replace("_1s_", "_").replace("volatility_", "").replace("_index", "")
    fa, fb = "_1s_" in a, "_1s_" in b
    if pa == pb and fa != fb:
        return "twin"
    return "mismatch"


# ---------------------------------------------------------------- loading


def load_ticks(conn, feed: str):
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    if not rows:
        return np.empty(0, dtype=np.int64), np.empty(0), np.empty(0)
    arr = np.asarray(rows, dtype=np.float64)
    ts = arr[:, 0].astype(np.int64)
    bid = arr[:, 1]
    mid = (arr[:, 1] + arr[:, 2]) / 2.0
    ok = np.isfinite(mid) & (mid > 0)
    return ts[ok], mid[ok], bid[ok]


def quote_decimals(px: np.ndarray) -> int:
    """How many decimals the broker actually quotes this feed in.

    The first version of the repeat test below quantised every feed to two
    decimals, which for `volatility_250_1s_index` - quoted in the hundreds with
    three decimals of movement below the second - rounded **every** step to the
    same integer and reported a single-step collision probability of exactly
    1.00. That is the failure mode this project has published before: a number
    sitting on its null because the column underneath it was dead, not because
    the world was. So the resolution is measured from the quotes.
    """
    for k in range(0, 9):
        s = px * (10.0**k)
        if np.max(np.abs(s - np.rint(s))) < 1e-3:
            return k
    return 8


def on_grid(ts: np.ndarray, mid: np.ndarray, t0: int, t1: int, step_s: int):
    """Last mid at or before each grid second. Forward-filled, so a feed that
    prints every two seconds contributes a zero return on the seconds it did
    not print. That attenuates any correlation; it cannot manufacture one, and
    the same treatment is applied to every pair including the controls."""
    grid = np.arange(t0, t1 + 1, step_s * 1000, dtype=np.int64)
    idx = np.searchsorted(ts, grid, side="right") - 1
    good = idx >= 0
    out = np.full(grid.shape, np.nan)
    out[good] = mid[idx[good]]
    fresh = np.zeros(grid.shape, dtype=bool)
    fresh[1:] = idx[1:] != idx[:-1]
    return grid, out, fresh


def logret(x: np.ndarray) -> np.ndarray:
    r = np.diff(np.log(x))
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


# ------------------------------------------------------------ estimators


def xcorr(x: np.ndarray, y: np.ndarray, maxlag: int) -> np.ndarray:
    """corr(x[t], y[t+L]) for L in -maxlag..+maxlag.

    A positive lag means **y leads**: y at t+L moves with x at t, so knowing
    x today tells you about y later. Normalised by the whole-sample norms
    rather than per-lag, which is standard and, with maxlag 600 against
    n 86,400, differs in the fourth decimal.
    """
    x = x - x.mean()
    y = y - y.mean()
    nx, ny = float(np.sqrt((x * x).sum())), float(np.sqrt((y * y).sum()))
    if nx <= 0 or ny <= 0:
        return np.full(2 * maxlag + 1, np.nan)
    full = signal.correlate(y, x, mode="full", method="fft")
    zero = len(x) - 1                      # full[zero] == sum x[t]*y[t]
    lo, hi = zero - maxlag, zero + maxlag + 1
    return full[lo:hi] / (nx * ny)


def peak(c: np.ndarray, maxlag: int) -> tuple[float, int, float]:
    if not np.isfinite(c).any():
        return float("nan"), 0, float("nan")
    k = int(np.nanargmax(np.abs(c)))
    return float(c[k]), k - maxlag, float(c[maxlag])


def selftest() -> bool:
    """Plant a lag and a correlation and demand them back."""
    rng = np.random.default_rng(SEED)
    n, planted_lag, planted_rho = 86_400, 37, 0.25
    x = rng.standard_normal(n)
    y = np.empty(n)
    noise = rng.standard_normal(n)
    # y[t + lag] carries rho of x[t]
    y[planted_lag:] = planted_rho * x[: n - planted_lag] + math.sqrt(
        1 - planted_rho**2
    ) * noise[planted_lag:]
    y[:planted_lag] = noise[:planted_lag]
    c = xcorr(x, y, MAXLAG)
    best, lag, at0 = peak(c, MAXLAG)
    ok = lag == planted_lag and abs(best - planted_rho) < 0.02 and abs(at0) < 0.02
    print(f"  planted lag {planted_lag:+d} rho {planted_rho:.2f}  ->  "
          f"recovered lag {lag:+d} rho {best:+.4f} (lag0 {at0:+.4f})   "
          f"{'PASS' if ok else 'FAIL'}")
    # And the converse: two independent series must not produce a peak that
    # looks like the planted one.
    z = rng.standard_normal(n)
    nb, nl, _ = peak(xcorr(x, z, MAXLAG), MAXLAG)
    print(f"  independent pair over {2*MAXLAG+1} lags  ->  max |corr| "
          f"{abs(nb):.4f} at lag {nl:+d}   (1/sqrt(n) = {1/math.sqrt(n):.4f})")
    return ok


# ------------------------------------------------------------------- runs


def section_grid(ticks: dict, t0: int, t1: int, step_s: int,
                 label: str = "24h", quiet: bool = False) -> None:
    print(f"\n=== 1. wall-clock cross-correlation, {step_s}s grid, "
          f"{label}, lags {-MAXLAG}..{MAXLAG}s ===")
    rets, live = {}, {}
    for feed, (ts, mid, _bid) in ticks.items():
        _, m, fresh = on_grid(ts, mid, t0, t1, step_s)
        if not np.isfinite(m).all():
            first = int(np.argmax(np.isfinite(m)))
            m = m[first:]
            fresh = fresh[first:]
        r = logret(m)
        rets[feed] = r
        live[feed] = (float(fresh[1:].mean()), float(np.mean(r != 0)), float(r.std()))

    if not quiet:
        print(f"  {'feed':26s} {'n':>7s} {'fresh%':>7s} {'nonzero%':>9s} {'sd':>10s}")
    for feed in FEEDS:
        if feed not in rets:
            continue
        f, nz, sd = live[feed]
        if not quiet:
            print(f"  {feed:26s} {len(rets[feed]):7d} {100*f:7.1f} {100*nz:9.1f} "
                  f"{sd:10.2e}")
        if sd <= 0 or nz < 0.01:
            print(f"    {feed}: DEAD COLUMN - any statistic against it is meaningless")

    rows = []
    for a, b in combinations([f for f in FEEDS if f in rets], 2):
        n = min(len(rets[a]), len(rets[b]))
        c = xcorr(rets[a][:n], rets[b][:n], MAXLAG)
        bump(f"xcorr_{step_s}s", 2 * MAXLAG + 1)
        best, lag, at0 = peak(c, MAXLAG)
        rows.append((kind(a, b), a, b, at0, best, lag, n))

    report_pairs(rows, f"{step_s}s grid, {label}")


def report_pairs(rows: list, label: str, nlags: int = None,
                 unit: str = "s") -> None:
    nlags = 2 * MAXLAG + 1 if nlags is None else nlags
    print(f"\n  --- {label}: |corr| at the best of {nlags} lags ---")
    print(f"  {'kind':>9s} {'pairs':>6s} {'mean|r|':>9s} {'max|r|':>9s}   largest")
    order = {"twin": 0, "mismatch": 1, "stranger": 2}
    ctrl = [abs(r[4]) for r in rows if r[0] != "twin"]
    for k in sorted({r[0] for r in rows}, key=lambda k: order.get(k, 9)):
        got = [r for r in rows if r[0] == k]
        mags = [abs(r[4]) for r in got]
        w = max(got, key=lambda r: abs(r[4]))
        print(f"  {k:>9s} {len(got):6d} {np.mean(mags):9.4f} {max(mags):9.4f}   "
              f"{w[1]} / {w[2]} = {w[4]:+.4f} @ {w[5]:+d}{unit}")
    if ctrl:
        mu, sd = float(np.mean(ctrl)), float(np.std(ctrl))
        mm = [abs(r[4]) for r in rows if r[0] == "mismatch"]
        print(f"\n  control (mismatch+stranger) max|r|: mean {mu:.4f} sd {sd:.4f}"
              f"  n={len(ctrl)}")
        print(f"  mismatch only - the like-for-like control, same marginals as a"
              f" twin: mean {np.mean(mm):.4f} sd {np.std(mm):.4f} max {max(mm):.4f}")
        print(f"  {'twin pair':>46s} {'lag0':>9s} {'best':>9s} {'lag':>6s} "
              f"{'z vs control':>13s}")
        for k, a, b, at0, best, lag, n in rows:
            if k != "twin":
                continue
            z = (abs(best) - mu) / sd if sd > 0 else float("nan")
            print(f"  {a + ' / ' + b:>46s} {at0:+9.4f} {best:+9.4f} "
                  f"{str(lag) + unit:>6s} {z:+13.2f}")
        hi = max(ctrl)
        over = [r for r in rows if r[0] == "twin" and abs(r[4]) > hi]
        print(f"  twins exceeding the largest control ({hi:.4f}): "
              f"{len(over)} of {sum(1 for r in rows if r[0]=='twin')}")


def section_index(ticks: dict) -> None:
    """Shared PRNG stream test: alignment in tick *index*, not wall clock.

    If the fast series is the slow one's generator run at twice the rate, the
    two need not line up in wall-clock time at all - but the n-th draw of one
    would line up with the n-th or the 2n-th of the other. Returns are
    z-scored so that the two instruments' different scales cannot matter.
    """
    print("\n=== 2. tick-index alignment (shared draw stream) ===")
    z = {}
    for feed, (ts, mid, _bid) in ticks.items():
        r = logret(mid)
        s = r.std()
        z[feed] = (r - r.mean()) / s if s > 0 else r * 0.0

    K = 60
    rows = []
    for a, b in combinations([f for f in FEEDS if f in z], 2):
        for mapping in ("1:1", "1:2"):
            x, y = z[a], z[b]
            if mapping == "1:2":
                # pair up consecutive fast draws: two 1s ticks ~ one 2s tick
                if len(y) < len(x):
                    x, y = y, x
                m = (len(y) // 2) * 2
                y = y[:m].reshape(-1, 2).sum(axis=1) / math.sqrt(2)
            n = min(len(x), len(y))
            if n < 5000:
                continue
            c = xcorr(x[:n], y[:n], K)
            bump("index_align", 2 * K + 1)
            best, lag, at0 = peak(c, K)
            rows.append((kind(a, b), a, b, mapping, at0, best, lag, n))

    for mapping in ("1:1", "1:2"):
        got = [r for r in rows if r[3] == mapping]
        if not got:
            continue
        ctrl = [abs(r[5]) for r in got if r[0] != "twin"]
        mu, sd = float(np.mean(ctrl)), float(np.std(ctrl))
        print(f"\n  --- index map {mapping}, offsets {-K}..{K} ---")
        print(f"  control max|r| mean {mu:.4f} sd {sd:.4f} max {max(ctrl):.4f} "
              f"n={len(ctrl)}")
        for k, a, b, _m, at0, best, lag, n in got:
            if k != "twin":
                continue
            zz = (abs(best) - mu) / sd if sd > 0 else float("nan")
            print(f"  {a + ' / ' + b:>46s} off0 {at0:+.4f} best {best:+.4f} "
                  f"@ {lag:+d}  n={n}  z {zz:+.2f}")


def section_tails(ticks: dict, t0: int, t1: int) -> None:
    """Do the twins share their big moves, even if the body is uncorrelated?"""
    print("\n=== 3. shared tails: co-jumps within a few seconds ===")
    rng = np.random.default_rng(SEED)
    span = t1 - t0

    events = {}
    for q in TAIL_QS:
        for feed, (ts, mid, _bid) in ticks.items():
            r = logret(mid)
            a = np.abs(r)
            thr = np.percentile(a, q)
            sel = a >= thr
            events[(feed, q)] = ts[1:][sel]

    print(f"  {'feed':26s} " + "  ".join(f"n@{q}" for q in TAIL_QS))
    for feed in FEEDS:
        if feed not in ticks:
            continue
        print(f"  {feed:26s} " + "  ".join(
            f"{len(events[(feed, q)]):6d}" for q in TAIL_QS))

    for q in TAIL_QS:
        for w in TAIL_WINDOWS:
            rows = []
            for a, b in combinations([f for f in FEEDS if f in ticks], 2):
                ea, eb = events[(a, q)], events[(b, q)]
                if len(ea) < 20 or len(eb) < 20:
                    continue
                obs = coincidences(ea, eb, w)
                # null from the data: rotate b's event times around the day
                null = np.empty(ROTATIONS)
                for i in range(ROTATIONS):
                    shift = int(rng.integers(1, span))
                    rot = t0 + ((eb - t0 + shift) % span)
                    rot.sort()
                    null[i] = coincidences(ea, rot, w)
                mu, sd = float(null.mean()), float(null.std())
                z = (obs - mu) / sd if sd > 0 else float("nan")
                bump("cojump", 1)
                rows.append((kind(a, b), a, b, obs, mu, z))
            summarise_tails(rows, q, w)


def coincidences(ea: np.ndarray, eb: np.ndarray, w_s: int) -> int:
    """How many of a's events have at least one b event within +/- w seconds."""
    if len(ea) == 0 or len(eb) == 0:
        return 0
    w = w_s * 1000
    lo = np.searchsorted(eb, ea - w, side="left")
    hi = np.searchsorted(eb, ea + w, side="right")
    return int(np.count_nonzero(hi > lo))


def summarise_tails(rows: list, q: float, w: int) -> None:
    if not rows:
        return
    ctrl = [r[5] for r in rows if r[0] != "twin" and r[5] == r[5]]
    tw = [r for r in rows if r[0] == "twin"]
    mu, sd = (float(np.mean(ctrl)), float(np.std(ctrl))) if ctrl else (float("nan"),) * 2
    print(f"\n  --- q{q} threshold, +/-{w}s window ---")
    print(f"  control z: mean {mu:+.2f} sd {sd:.2f} max {max(ctrl):+.2f} "
          f"min {min(ctrl):+.2f}  n={len(ctrl)}")
    for k, a, b, obs, exp, z in tw:
        print(f"  {a + ' / ' + b:>46s} obs {obs:5d} exp {exp:8.1f} z {z:+.2f}")


def section_repeats(ticks: dict) -> None:
    """Exact repeats: does any feed replay a subsequence it has printed before?

    Windows of L consecutive mid-price *differences*, quantised to the quote's
    own two decimals so that this is exact integer equality, not a float
    comparison. Under independence the chance two windows agree is p1**L where
    p1 is the single-step collision probability, measured from the same data.
    """
    print("\n=== 4. exact repeated subsequences (PRNG period / reused seed) ===")
    print(f"  {'feed':26s} {'dp':>3s} {'n':>7s} {'p1':>9s} " +
          "  ".join(f"{'L=%d obs/exp' % L:>18s}" for L in (5, 10, 20)) +
          f"{'longest repeat':>16s}")
    for feed in FEEDS:
        if feed not in ticks:
            continue
        _ts, mid, bid = ticks[feed]
        dp = quote_decimals(bid)
        d = np.rint(np.diff(mid) * (10.0**dp)).astype(np.int64)
        if np.all(d == d[0]):
            print(f"  {feed:26s} DEAD - every quantised step identical, skipping")
            continue
        n = len(d)
        cnt = Counter(d.tolist())
        p1 = sum((c / n) ** 2 for c in cnt.values())
        cells = []
        for L in (5, 10, 20):
            if n <= L:
                cells.append("  n/a")
                continue
            view = np.lib.stride_tricks.sliding_window_view(d, L)
            keys = [w.tobytes() for w in view]
            c = Counter(keys)
            obs = sum(v - 1 for v in c.values() if v > 1)
            exp = (len(keys) * (len(keys) - 1) / 2) * (p1**L)
            bump("repeat_window", 1)
            cells.append(f"{obs:8d} / {exp:8.2e}")
        longest = longest_repeat(d)
        bump("repeat_window", 1)
        print(f"  {feed:26s} {dp:3d} {n:7d} {p1:9.2e} "
              + "  ".join(f"{c:>18s}" for c in cells) + f"{longest:16d}")


def section_tickacf(ticks: dict) -> None:
    """Tick-level autocorrelation. A GBM's returns are independent at every
    lag; anything else is a fact about the generator."""
    print("\n=== 5. tick-level autocorrelation of log returns ===")
    LAGS = (1, 2, 3, 5, 10, 20, 50)
    print(f"  {'feed':26s} {'n':>7s} " + "".join(f"{'r%d' % L:>9s}" for L in LAGS)
          + f"{'2/sqrt(n)':>11s}{'zero%':>7s}{'r1|even dt':>11s}{'n even':>8s}")
    for feed in FEEDS:
        if feed not in ticks:
            continue
        ts, mid, _bid = ticks[feed]
        r = logret(mid)
        dt = np.diff(ts) / 1000.0
        r = r - r.mean()
        den = float((r * r).sum())
        cells = []
        for L in LAGS:
            ac = float((r[:-L] * r[L:]).sum()) / den if den > 0 else float("nan")
            bump("tick_acf", 1)
            cells.append(f"{ac:+9.4f}")
        # r1 restricted to consecutive pairs whose two intervals are both the
        # feed's own usual spacing. A feed the collector dropped ticks from can
        # show autocorrelation that belongs to the gaps and not the generator.
        med = float(np.median(dt))
        even = (np.abs(dt - med) < 0.25 * med)
        both = even[:-1] & even[1:]
        x, y = r[:-1][both], r[1:][both]
        if len(x) > 100 and x.std() > 0 and y.std() > 0:
            rc = float(np.corrcoef(x, y)[0, 1])
            bump("tick_acf", 1)
        else:
            rc = float("nan")
        print(f"  {feed:26s} {len(r):7d} " + "".join(cells)
              + f"{2/math.sqrt(len(r)):11.4f}{100*np.mean(r == 0):7.2f}"
              + f"{rc:+11.4f}{len(x):8d}")


def longest_repeat(d: np.ndarray, cap: int = 64) -> int:
    """Longest window of quantised steps this feed prints twice.

    Monotone in the length - a repeat of length L contains one of length L-1 -
    so a binary search is exact rather than a heuristic. A generator with a
    short period or a reused seed would show a long one; discretisation alone
    shows a short one that the expected-collision column beside it explains.
    """
    n = len(d)

    def has(L: int) -> bool:
        if L < 1 or L > n:
            return False
        view = np.lib.stride_tricks.sliding_window_view(d, L)
        seen = set()
        for w in view:
            b = w.tobytes()
            if b in seen:
                return True
            seen.add(b)
        return False

    lo, hi = 1, min(cap, n - 1)
    if not has(lo):
        return 0
    if has(hi):
        return hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if has(mid):
            lo = mid
        else:
            hi = mid
    return lo


def section_spacing(ticks: dict) -> None:
    """How the two tick rates actually behave, which decides what the grids
    above can and cannot see."""
    print("\n=== 0b. tick spacing ===")
    print(f"  {'feed':26s} {'ticks':>7s} {'median dt':>10s} {'p10':>7s} {'p90':>7s} "
          f"{'gaps>3s':>8s} {'spread':>10s} {'sd/tick':>10s} {'sd/sqrt(s)':>11s}"
          f" {'ann %':>7s}")
    for feed in FEEDS:
        if feed not in ticks:
            continue
        ts, mid, bid = ticks[feed]
        dt = np.diff(ts) / 1000.0
        r = logret(mid)
        sd = float(r.std())
        med = float(np.median(dt))
        # Per-tick sd divided by sqrt(seconds per tick) is the per-second
        # volatility. If a twin pair is the same law at two tick rates these
        # two columns disagree by sqrt(2) and the last one agrees exactly.
        per_s = sd / math.sqrt(med)
        print(f"  {feed:26s} {len(ts):7d} {med:10.3f} "
              f"{np.percentile(dt, 10):7.3f} {np.percentile(dt, 90):7.3f} "
              f"{np.mean(dt > 3.0):8.4f} {np.median((mid - bid) * 2):10.4f} "
              f"{sd:10.3e} {per_s:11.3e} "
              f"{100 * per_s * math.sqrt(365 * 86400):7.1f}")


def section_absgrid(ticks: dict, t0: int, t1: int, step_s: int) -> None:
    """The tail question with the whole sample behind it.

    Counting co-jumps above a 99.9th percentile leaves ten events a day and no
    power at all. Correlating |return| keeps every observation and asks the
    same thing: when one twin is moving hard, is the other? A shared variance
    process shows here even when the signed returns are independent.
    """
    print(f"\n=== 3b. |return| cross-correlation, {step_s}s grid, "
          f"lags {-MAXLAG}..{MAXLAG}s ===")
    print("  READ SECTION 0c FIRST. Feeds sharing a publication clock share "
          "their\n  grid zeros, which correlates |r| by itself. 3d is the "
          "grid-free version.")
    a_rets = {}
    for feed, (ts, mid, _bid) in ticks.items():
        _, m, _f = on_grid(ts, mid, t0, t1, step_s)
        first = int(np.argmax(np.isfinite(m)))
        r = np.abs(logret(m[first:]))
        a_rets[feed] = r
    rows = []
    for a, b in combinations([f for f in FEEDS if f in a_rets], 2):
        n = min(len(a_rets[a]), len(a_rets[b]))
        c = xcorr(a_rets[a][:n], a_rets[b][:n], MAXLAG)
        bump(f"absxcorr_{step_s}s", 2 * MAXLAG + 1)
        best, lag, at0 = peak(c, MAXLAG)
        rows.append((kind(a, b), a, b, at0, best, lag, n))
    report_pairs(rows, f"|r| on the {step_s}s grid")


def section_exceed(ticks: dict, t0: int, t1: int, step_s: int = 2) -> None:
    """Conditional exceedance: when A makes its 500 largest moves of the day,
    how large is B around the same moment?

    The statistic is mean max|z_B| within +/-W of an A event, divided by the
    same thing at random times. Its null comes from rotating B's series around
    the day, not from a formula, because these are grid returns with a known
    zero-inflation and no textbook covers that.
    """
    K = 500
    rng = np.random.default_rng(SEED)
    z = {}
    for feed, (ts, mid, _bid) in ticks.items():
        _, m, _f = on_grid(ts, mid, t0, t1, step_s)
        first = int(np.argmax(np.isfinite(m)))
        r = logret(m[first:])
        sd = r.std()
        z[feed] = np.abs(r) / sd if sd > 0 else r * 0.0

    for w in (1, 5):
        rows = []
        for a, b in combinations([f for f in FEEDS if f in z], 2):
            n = min(len(z[a]), len(z[b]))
            za, zb = z[a][:n], z[b][:n]
            ev = np.argsort(za)[-K:]
            obs = local_max(zb, ev, w)
            null = np.empty(ROTATIONS)
            for i in range(ROTATIONS):
                null[i] = local_max(np.roll(zb, int(rng.integers(1, n))), ev, w)
            mu, sd = float(null.mean()), float(null.std())
            bump("exceed", 1)
            rows.append((kind(a, b), a, b, obs, mu,
                         (obs - mu) / sd if sd > 0 else float("nan")))
        ctrl = [r[5] for r in rows if r[0] != "twin"]
        mm = [r[5] for r in rows if r[0] == "mismatch"]
        print(f"\n=== 3c. conditional exceedance, top {K} moves, "
              f"+/-{w} steps of {step_s}s ===")
        print(f"  control z: mean {np.mean(ctrl):+.2f} sd {np.std(ctrl):.2f} "
              f"max {max(ctrl):+.2f} min {min(ctrl):+.2f}  n={len(ctrl)}   "
              f"(mismatch only: max {max(mm):+.2f})")
        for k, a, b, obs, exp, zz in rows:
            if k == "twin":
                print(f"  {a + ' / ' + b:>46s} obs {obs:.4f} exp {exp:.4f} "
                      f"z {zz:+.2f}")


def local_max(zb: np.ndarray, ev: np.ndarray, w: int) -> float:
    n = len(zb)
    acc = np.zeros(len(ev))
    for off in range(-w, w + 1):
        acc = np.maximum(acc, zb[(ev + off) % n])
    return float(acc.mean())


def section_publish(ticks: dict) -> None:
    """When do these feeds print, relative to each other?

    This is not a curiosity. Section 3b below correlates |return| on a fixed
    grid, and on a one-second grid a two-second feed contributes a zero on
    every other step. If two feeds print on the *same* clock their zeros line
    up, and |r| correlates strongly between them for reasons that have nothing
    to do with their values. Measuring the clock first is what tells a shared
    driver from a shared timetable.
    """
    print("\n=== 0c. publication clock: how closely do feeds print together? ===")
    feeds = [f for f in FEEDS if f in ticks]
    print(f"  median |t_A - nearest t_B|, ms.  Independent 2s clocks would give"
          f" ~500ms; one shared clock gives single-digit ms.")
    print(f"  {'pair kind':>10s} {'pairs':>6s} {'median offset ms':>18s} "
          f"{'min':>8s} {'max':>8s}")
    buckets = {}
    for a, b in combinations(feeds, 2):
        ta, tb = ticks[a][0], ticks[b][0]
        idx = np.clip(np.searchsorted(tb, ta), 1, len(tb) - 1)
        d = np.minimum(np.abs(ta - tb[idx]), np.abs(ta - tb[idx - 1]))
        bump("publish_offset", 1)
        rate_a = "2s" if "_1s_" not in a else "1s"
        rate_b = "2s" if "_1s_" not in b else "1s"
        key = "same rate" if rate_a == rate_b else "1s vs 2s"
        buckets.setdefault(key, []).append((float(np.median(d)), a, b))
    for key, got in buckets.items():
        meds = [g[0] for g in got]
        print(f"  {key:>10s} {len(got):6d} {np.median(meds):18.1f} "
              f"{min(meds):8.1f} {max(meds):8.1f}")
    worst = min((g for gs in buckets.values() for g in gs), key=lambda g: g[0])
    print(f"  closest pair of all: {worst[1]} / {worst[2]} at {worst[0]:.1f}ms")
    print("  phase, ms into each 2-second slot (median):")
    for feed in feeds:
        ts = ticks[feed][0]
        print(f"    {feed:26s} {float(np.median(ts % 2000)):8.1f}")


def section_tickclock(ticks: dict, t0: int, t1: int, label: str = "24h") -> None:
    """The volatility clock at tick resolution, without a grid.

    Realised variance per minute, computed from each feed's own ticks and
    divided by that minute's tick count so a feed that printed fewer times is
    not thereby quieter. No forward fill, no zero inflation, so nothing here
    can be the sampling artefact that section 3b has.
    """
    print(f"\n=== 3d. volatility clock from ticks, {label}: per-minute realised variance ===")
    minute = 60_000
    edges = np.arange(t0, t1 + minute, minute, dtype=np.int64)
    lv = {}
    for feed, (ts, mid, _bid) in ticks.items():
        r2 = logret(mid) ** 2
        who = np.searchsorted(edges, ts[1:], side="right") - 1
        ok = (who >= 0) & (who < len(edges) - 1)
        tot = np.bincount(who[ok], weights=r2[ok], minlength=len(edges) - 1)
        cnt = np.bincount(who[ok], minlength=len(edges) - 1)
        good = cnt >= 10
        lv[feed] = (np.log(np.maximum(tot / np.maximum(cnt, 1), 1e-300)), good)
    common = None
    for _v, g in lv.values():
        common = g if common is None else (common & g)
    print(f"  {int(common.sum())} minutes with at least 10 ticks on every feed")
    series = {f: v[common] for f, (v, _g) in lv.items()}
    rows = []
    for a, b in combinations([f for f in FEEDS if f in series], 2):
        c = xcorr(series[a], series[b], 10)
        bump("tickclock", 21)
        best, lag, at0 = peak(c, 10)
        rows.append((kind(a, b), a, b, at0, best, lag, int(common.sum())))
    report_pairs(rows, f"log RV per minute, from ticks, {label}", 21, "m")


def section_quantisation(ticks: dict) -> None:
    """Is a feed's tick-level autocorrelation its generator or its rounding?

    A price stored on a grid coarse relative to its own step size has
    differences that carry the rounding error twice, once with each sign, and
    that alone produces a negative first-order autocorrelation. So the step
    size is measured against the move size before any of it is called a
    generator artefact.
    """
    print("\n=== 5b. quote grid against step size ===")
    print(f"  {'feed':26s} {'price':>12s} {'quote step':>11s} {'sd(dstep)':>10s} "
          f"{'sd/step':>8s} {'distinct':>9s}")
    for feed in FEEDS:
        if feed not in ticks:
            continue
        _ts, mid, bid = ticks[feed]
        dp = quote_decimals(bid)
        step = 10.0 ** (-dp)
        d = np.diff(mid)
        print(f"  {feed:26s} {float(np.median(mid)):12.4f} {step:11.5f} "
              f"{float(d.std()):10.5f} {float(d.std())/step:8.2f} "
              f"{len(np.unique(np.rint(d / step))):9d}")


def run() -> None:
    t_start = time.time()
    print("=== 0. positive control on the estimator ===")
    if not selftest():
        print("  estimator failed its own planted lag - stopping, because a")
        print("  null from a broken estimator is worse than no null at all.")
        return

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=900.0)
    ticks, spans = {}, []
    for feed in FEEDS:
        ts, mid, bid = load_ticks(conn, feed)
        if len(ts) < 10_000:
            print(f"  SKIP {feed}: {len(ts)} ticks")
            continue
        ticks[feed] = (ts, mid, bid)
        spans.append((int(ts[0]), int(ts[-1])))
    t0 = max(s[0] for s in spans)
    t1 = min(s[1] for s in spans)
    print(f"\nloaded {len(ticks)} feeds, common window "
          f"{(t1-t0)/3_600_000:.2f}h, {sum(len(v[0]) for v in ticks.values()):,} ticks")

    section_spacing(ticks)
    section_publish(ticks)
    section_grid(ticks, t0, t1, 1)
    section_grid(ticks, t0, t1, 2)
    section_index(ticks)
    section_tails(ticks, t0, t1)
    section_absgrid(ticks, t0, t1, 1)
    section_absgrid(ticks, t0, t1, 2)
    section_tickclock(ticks, t0, t1)
    section_exceed(ticks, t0, t1, 2)

    # Split-sample. One day cannot be split far, but a result that only holds
    # in one half of it is not a result, and saying so costs one more pass.
    mid_t = (t0 + t1) // 2
    for name, (a, b) in (("first 12h", (t0, mid_t)), ("second 12h", (mid_t, t1))):
        section_grid(ticks, a, b, 2, name, quiet=True)
        section_tickclock(ticks, a, b, name)
    section_repeats(ticks)
    section_tickacf(ticks)
    section_quantisation(ticks)

    print("\n=== comparisons made ===")
    for k, v in sorted(COMPARISONS.items()):
        print(f"  {k:18s} {v:9d}")
    print(f"  {'TOTAL':18s} {sum(COMPARISONS.values()):9d}")
    print(f"\nelapsed {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    run()
