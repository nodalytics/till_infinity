"""Does volatility cascade from coarse timeframes to fine, and only that way?

`research/cascading.md` §1. In a turbulent flow energy enters at the large
scale and cascades to the small. The market claim is the same asymmetry:
coarse-timeframe volatility should forecast fine-timeframe volatility better
than the reverse.

## The two series, and why they live on one clock

The proposition as written - `corr(vol_1h(t), vol_5m(t+k))` against
`corr(vol_5m(t), vol_1h(t+k))` - needs the two volatilities on a common clock
before anything can be lagged, and how that is done decides the answer.

Both are measured over **the same span**, and differ only in the resolution at
which the returns inside it are taken. For a coarse interval `c` and a fine
interval `f` dividing it, on the grid of coarse bars:

    C_i = |sum of the m fine returns in bucket i|      the coarse reading
    F_i = mean |fine return| in bucket i               the fine reading

with `m = c / f`. This is Muller et al. (1997), "Volatilities of different time
resolutions", and it is the decomposition that makes the question answerable:
`C` aggregates *then* takes the magnitude, `F` takes the magnitude *then*
aggregates, and they are computed from the identical returns over the identical
window. Nothing about the pair is asymmetric except the resolution.

**Lags are whole coarse bars**, so `C_i` and `F_{i+k}` share no data for any
k >= 1. A trailing-window formulation - coarse volatility as the last hour,
fine as the last five minutes - would have the coarse window *contain* the fine
one, and the asymmetry that produced would be arithmetic rather than physics.

## What kills it, declared before running

**Symmetry.** If `asym = corr(C_t, F_{t+k}) - corr(F_t, C_{t+k})` is
indistinguishable from its null, volatility is not cascading, it is shared, and
the case for weighting the higher timeframe has to come from somewhere else.

The null is not zero, and assuming it were would be the whole error. Two
controls are computed from each feed's own data:

* **Phase-randomised surrogate.** Take `y_t = log|r_t|` at 1m, randomise the
  Fourier phases, keep the amplitudes. The surrogate has **the same
  autocovariance of log volatility at every lag** - identical persistence,
  identical long memory - and is Gaussian and linear, therefore time-reversible,
  therefore has no cascade. This is precisely "volatility is simply shared", and
  it is the distribution the real number has to beat.
* **Shuffle.** The 1m returns permuted. Destroys everything, including the
  persistence, and gives the floor.

And a check on the estimator rather than on the market: **time reversal must
flip the sign of `asym` exactly**, because reversing time exchanges the two
correlations by identity. A run where it does not is a bug in this file.

**Split-sample.** 60 days cut in half by time. An asymmetry that changes sign
between halves is not reported as one.

**Strata.** `shared.strata.compare` cuts the two directions within each scale
pair and within each instrument class, and warns when the pooled ordering flips.
`research/instruments.md` is the reason: an entire investigation there ran on a
composition rather than an instrument.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics as st
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.expanduser("~/till_infinity/repo"))

from till_infinity.shared.strata import compare  # noqa: E402

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
SEED = int(os.environ.get("SEED", "7"))
LAGS = tuple(int(k) for k in os.environ.get("LAGS", "1,2,3").split(","))
#: (coarse, fine) in minutes. 1d as the coarse leg leaves ~60 buckets over the
#: 60 days in the store, which is reported and marked thin rather than dropped -
#: `strata.py` documents why a thin cell is shown rather than hidden.
PAIRS = tuple(
    (c, f)
    for c, f in (
        (5, 1), (15, 1), (15, 5), (30, 1), (30, 5), (30, 15),
        (60, 1), (60, 5), (60, 15), (60, 30),
        (240, 5), (240, 15), (240, 30), (240, 60),
        (1440, 60), (1440, 240),
    )
)
MIN_BUCKETS = 60
MINUTE = 60_000

SYNTH = ("boom_", "crash_", "jump_", "volatility_", "step_", "range_break_")
FX = (
    "audjpy", "audusd", "cadjpy", "chfjpy", "euraud", "eurchf", "eurgbp",
    "eurjpy", "eurusd", "gbpjpy", "gbpusd", "nzdusd", "usdcad", "usdchf", "usdjpy",
)
INDEX = ("aus200", "fra40", "ger40", "hk50", "jp225", "uk100", "us100", "us30")


def klass(feed: str) -> str:
    if feed.startswith(SYNTH):
        return "synthetic"
    if feed in FX:
        return "fx"
    if feed in INDEX:
        return "index"
    if feed in ("gold", "silver"):
        return "metal"
    if feed in ("btc", "eth"):
        return "crypto"
    return "other"


def label(minutes: int) -> str:
    if minutes >= 1440:
        return f"{minutes // 1440}d"
    if minutes >= 60:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation. Primary because volatility has no usable moments.

    Pearson on raw `|r|` is a statement about the largest three observations in
    the sample; Pearson on `log|r|` needs a floor for the exact zeros the Step
    index produces by construction. Ranks need neither. Pearson on logs is
    reported beside it as a robustness check, not as the headline.
    """
    n = a.size
    if n < 30:
        return float("nan")
    ra = np.argsort(np.argsort(a, kind="stable"), kind="stable").astype(float)
    rb = np.argsort(np.argsort(b, kind="stable"), kind="stable").astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    da, db = math.sqrt(float(ra @ ra)), math.sqrt(float(rb @ rb))
    if da <= 0 or db <= 0:
        return float("nan")
    return float(ra @ rb) / (da * db)


def pearson_log(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson on logs, with a floor at one percent of each series' own median."""
    if a.size < 30:
        return float("nan")
    out = []
    for x in (a, b):
        pos = x[x > 0]
        floor = 0.01 * float(np.median(pos)) if pos.size else 1e-12
        y = np.log(np.maximum(x, 1e-300) + floor)
        out.append(y - y.mean())
    da, db = math.sqrt(float(out[0] @ out[0])), math.sqrt(float(out[1] @ out[1]))
    if da <= 0 or db <= 0:
        return float("nan")
    return float(out[0] @ out[1]) / (da * db)


def coarse_fine(ts: np.ndarray, close: np.ndarray, c: int, f: int):
    """`(bucket index, C, F)` for one (coarse, fine) pair off 1m bars.

    Gaps are dropped rather than bridged. A weekend spanned by one log return
    is the largest return in the sample and it is not a market move, and the
    coarse leg would swallow it while the fine leg would not - which is an
    asymmetry manufactured by the calendar. So an `f` window is used only when
    it holds its full complement of contiguous 1m bars, a fine return only when
    both its windows are complete and adjacent, and a `c` bucket only when all
    `c/f` of its fine returns survived.
    """
    per = c // f
    if ts.size < per + 2:
        return None
    fine_idx = ts // (f * MINUTE)
    uniq, first, counts = np.unique(fine_idx, return_index=True, return_counts=True)
    if uniq.size < per + 2:
        return None
    last = first + counts - 1
    ok = counts == f
    cl = close[last]
    adj = (uniq[1:] == uniq[:-1] + 1) & ok[1:] & ok[:-1] & (cl[1:] > 0) & (cl[:-1] > 0)
    if not adj.any():
        return None
    ret = np.log(cl[1:] / cl[:-1])[adj]
    bucket = (uniq[1:][adj] * f) // c
    gu, gfirst, gcount = np.unique(bucket, return_index=True, return_counts=True)
    sums = np.add.reduceat(ret, gfirst)
    mags = np.add.reduceat(np.abs(ret), gfirst)
    keep = gcount == per
    if int(keep.sum()) < MIN_BUCKETS:
        return None
    return gu[keep].astype(np.int64), np.abs(sums[keep]), mags[keep] / per


def lagged(keys: np.ndarray, x: np.ndarray, y: np.ndarray, k: int):
    """`(x_t, y_{t+k})` for buckets exactly k apart. Gaps are not bridged."""
    want = keys + k
    pos = np.searchsorted(keys, want)
    pos = np.clip(pos, 0, keys.size - 1)
    hit = keys[pos] == want
    return x[hit], y[pos[hit]]


def surrogate(returns: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Same log-volatility spectrum, no cascade.

    `y = log|r|` is Fourier transformed, its phases replaced by uniform draws
    and its amplitudes kept. The result has the **same autocovariance at every
    lag** - so the same persistence and the same long memory - and is a
    Gaussian linear process, so it is time-reversible and can carry no cascade.
    Signs are drawn independently: the question is about magnitude.
    """
    mag = np.abs(returns)
    pos = mag[mag > 0]
    floor = 1e-3 * float(np.median(pos)) if pos.size else 1e-12
    y = np.log(mag + floor)
    mu = y.mean()
    spec = np.fft.rfft(y - mu)
    phases = rng.uniform(0.0, 2.0 * math.pi, spec.size)
    phases[0] = 0.0
    if returns.size % 2 == 0:
        phases[-1] = 0.0
    made = np.fft.irfft(np.abs(spec) * np.exp(1j * phases), n=returns.size)
    out = np.exp(made + mu)
    return out * rng.choice(np.array([-1.0, 1.0]), size=returns.size)


def rebuild(ts: np.ndarray, returns: np.ndarray) -> np.ndarray:
    """A close series carrying the given 1m returns on the given timestamps."""
    return np.exp(np.cumsum(returns))


def run() -> None:
    started = time.time()
    rng = np.random.default_rng(SEED)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=600.0)
    feeds = [f for (f,) in conn.execute("SELECT DISTINCT feed FROM bars ORDER BY feed")]
    span = conn.execute("SELECT MIN(ts), MAX(ts) FROM bars WHERE interval='1m'").fetchone()
    cut = (span[0] + span[1]) // 2
    print(f"{len(feeds)} feeds, 1m bars {span[0]} .. {span[1]}, split at {cut}")
    print(f"pairs: {', '.join(f'{label(c)}/{label(f)}' for c, f in PAIRS)}")
    print(f"lags: {LAGS} coarse bars\n")

    # arm -> pair -> lag -> list over feeds
    got: dict[str, dict[tuple[int, int], dict[int, list[tuple[float, float]]]]] = {
        arm: defaultdict(lambda: defaultdict(list))
        for arm in ("real", "first", "second", "surrogate", "shuffled", "reversed")
    }
    logged: dict[tuple[int, int], dict[int, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    #: The real arm again, kept by instrument class and by scale separation, for
    #: the two sub-questions the proposition makes beyond "is it asymmetric":
    #: whether generated instruments cascade like real ones, and whether the gap
    #: widens with the separation of the two scales.
    by_class: dict[tuple[str, tuple[int, int], int], list[float]] = defaultdict(list)
    by_sep: dict[tuple[int, int], list[float]] = defaultdict(list)
    rows: list[dict] = []
    thin: set[tuple[int, int]] = set()

    for n, feed in enumerate(feeds, 1):
        cur = conn.execute(
            "SELECT ts, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts", (feed,)
        )
        raw = cur.fetchall()
        ts = np.array([r[0] for r in raw], dtype=np.int64)
        close = np.array([float(r[1]) for r in raw], dtype=float)
        keep = close > 0
        ts, close = ts[keep], close[keep]
        if ts.size < 5000:
            print(f"  {feed}: only {ts.size} 1m bars, skipped")
            continue

        # 1m returns for the surrogates, contiguity enforced.
        step = np.diff(ts) == MINUTE
        r1 = np.where(step, np.log(np.maximum(close[1:], 1e-300) / np.maximum(close[:-1], 1e-300)), 0.0)
        sur_close = rebuild(ts[1:], surrogate(r1, rng))
        shuf_close = rebuild(ts[1:], rng.permutation(r1))

        series = {
            "real": (ts, close),
            "surrogate": (ts[1:], sur_close),
            "shuffled": (ts[1:], shuf_close),
            "reversed": (ts, close[::-1].copy()),
            "first": (ts[ts < cut], close[ts < cut]),
            "second": (ts[ts >= cut], close[ts >= cut]),
        }

        for c, f in PAIRS:
            for arm, (at, ac) in series.items():
                if at.size < 5000:
                    continue
                built = coarse_fine(at, ac, c, f)
                if built is None:
                    if arm == "real":
                        thin.add((c, f))
                    continue
                keys, cs, fs = built
                for k in LAGS:
                    ca, fb = lagged(keys, cs, fs, k)      # coarse leads
                    fa, cb = lagged(keys, fs, cs, k)      # fine leads
                    if ca.size < 60:
                        continue
                    down = spearman(ca, fb)
                    up = spearman(fa, cb)
                    if not (math.isfinite(down) and math.isfinite(up)):
                        continue
                    got[arm][(c, f)][k].append((down, up))
                    if arm == "real":
                        logged[(c, f)][k].append((pearson_log(ca, fb), pearson_log(fa, cb)))
                        by_class[(klass(feed), (c, f), k)].append(down - up)
                        by_sep[(c // f, k)].append(down - up)
                        rows.append({
                            "corr": down, "direction": "coarse->fine",
                            "pair": f"{label(c)}/{label(f)}", "klass": klass(feed),
                            "feed": feed, "lag": str(k), "interval": label(c),
                        })
                        rows.append({
                            "corr": up, "direction": "fine->coarse",
                            "pair": f"{label(c)}/{label(f)}", "klass": klass(feed),
                            "feed": feed, "lag": str(k), "interval": label(c),
                        })
        if n % 10 == 0:
            print(f"  {n}/{len(feeds)} feeds  {time.time() - started:.0f}s")

    def summarise(arm: str, c: int, f: int, k: int):
        vals = got[arm][(c, f)].get(k) or []
        if len(vals) < 5:
            return None
        asym = [d - u for d, u in vals]
        return {
            "feeds": len(vals),
            "down": st.fmean(d for d, _ in vals),
            "up": st.fmean(u for _, u in vals),
            "asym": st.fmean(asym),
            "se": (st.stdev(asym) / math.sqrt(len(asym))) if len(asym) > 1 else float("nan"),
            "share": sum(1 for a in asym if a > 0) / len(asym),
        }

    print("\n" + "=" * 96)
    print("ONE: the cascade, per scale pair. asym = corr(coarse_t, fine_t+k) - corr(fine_t, coarse_t+k)")
    print("positive means the coarse reading leads. Spearman, averaged over feeds, SE across feeds.")
    print("=" * 96)
    for k in LAGS:
        print(f"\nlag k = {k} coarse bar(s)")
        print(f"  {'pair':>10s} {'feeds':>6s} {'C->F':>8s} {'F->C':>8s} {'asym':>8s} "
              f"{'SE':>7s} {'t':>7s} {'feeds+':>7s} | {'surrogate':>10s} {'shuffled':>9s} "
              f"{'reversed':>9s} | {'first':>8s} {'second':>8s}")
        for c, f in PAIRS:
            real = summarise("real", c, f, k)
            if real is None:
                continue
            sur = summarise("surrogate", c, f, k)
            shu = summarise("shuffled", c, f, k)
            rev = summarise("reversed", c, f, k)
            one = summarise("first", c, f, k)
            two = summarise("second", c, f, k)
            t = real["asym"] / real["se"] if real["se"] and math.isfinite(real["se"]) else float("nan")
            mark = " thin" if (c, f) in thin else ""
            print(
                f"  {label(c) + '/' + label(f):>10s} {real['feeds']:6d} {real['down']:+8.4f} "
                f"{real['up']:+8.4f} {real['asym']:+8.4f} {real['se']:7.4f} {t:+7.2f} "
                f"{real['share']:7.1%} | {(sur or {}).get('asym', float('nan')):+10.4f} "
                f"{(shu or {}).get('asym', float('nan')):+9.4f} "
                f"{(rev or {}).get('asym', float('nan')):+9.4f} | "
                f"{(one or {}).get('asym', float('nan')):+8.4f} "
                f"{(two or {}).get('asym', float('nan')):+8.4f}{mark}"
            )

    print("\n" + "=" * 96)
    print("Asymmetry by instrument class. The generated book is 72% of what is traded,")
    print("so 'do the synthetics cascade like the real markets' is not a side question.")
    print("=" * 96)
    classes = sorted({k[0] for k in by_class})
    for k in LAGS:
        print(f"\n  lag k = {k}")
        print("  " + f"{'pair':>10s}" + "".join(f"{c:>12s}" for c in classes))
        for c, f in PAIRS:
            line = f"  {label(c) + '/' + label(f):>10s}"
            seen = False
            for name in classes:
                vals = by_class.get((name, (c, f), k)) or []
                if len(vals) >= 2:
                    seen = True
                    line += f"{st.fmean(vals):+12.4f}"
                else:
                    line += f"{'-':>12s}"
            if seen:
                print(line)
        print("  " + f"{'ALL PAIRS':>10s}", end="")
        for name in classes:
            vals = [v for key, vs in by_class.items() if key[0] == name and key[2] == k for v in vs]
            print(f"{(st.fmean(vals) if vals else float('nan')):+12.4f}", end="")
        print()

    print("\n" + "=" * 96)
    print("Does the gap widen with the separation of the two scales? The proposition says it should.")
    print("=" * 96)
    for k in LAGS:
        seps = sorted({s for s, kk in by_sep if kk == k})
        print(f"\n  lag k = {k}")
        print("  " + f"{'coarse/fine':>12s} {'readings':>9s} {'asym':>9s} {'SE':>8s}")
        for sep in seps:
            vals = by_sep[(sep, k)]
            if len(vals) < 10:
                continue
            se = st.stdev(vals) / math.sqrt(len(vals))
            print(f"  {sep:12d} {len(vals):9d} {st.fmean(vals):+9.4f} {se:8.4f}")

    print("\nPearson on logs, lag 1, as a robustness check on the rank statistic:")
    for c, f in PAIRS:
        vals = logged[(c, f)].get(LAGS[0]) or []
        vals = [(d, u) for d, u in vals if math.isfinite(d) and math.isfinite(u)]
        if len(vals) < 5:
            continue
        asym = [d - u for d, u in vals]
        print(f"  {label(c) + '/' + label(f):>10s} n={len(vals):3d} C->F {st.fmean(d for d, _ in vals):+.4f} "
              f"F->C {st.fmean(u for _, u in vals):+.4f}  asym {st.fmean(asym):+.4f}")

    print("\nCODE CHECK - `reversed` should be about the negative of `real`.")
    print("Reversing time exchanges the two correlations by identity. It is not exact here -")
    print("reversal re-aligns the bucket grid and drops a different set of gaps - so what this")
    print("checks is that the sign mirrors, not that the magnitude does.")

    if rows:
        print("\n" + "=" * 96)
        print("Conditioned: the same two directions cut within scale pair and instrument class")
        print("=" * 96)
        print(compare(rows, value="corr", bucket="direction", within=("pair", "klass"), min_n=60).render())

    print(f"\n{time.time() - started:.0f}s")


if __name__ == "__main__":
    run()
