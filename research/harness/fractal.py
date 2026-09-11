"""Are the generated series monofractal where the real markets are not?

`research/cascading.md` §2. Turbulent velocity increments are strongly
non-Gaussian at small separations and approach Gaussian at large ones, and the
rate at which that happens is not a single exponent - the scaling is
*multifractal*. Financial returns have been found to behave the same way.

The book is **72% synthetics** - Volatility indices, Boom, Crash, Jump, Step,
Range Break - and these are generated processes with known constructions. There
is no reason a generator should reproduce the multifractal scaling of a real
market.

## The measurement

Structure functions. For each series and each aggregation `dt`,

    S_q(dt) = mean(|log return over dt| ^ q)

fitted as `S_q(dt) ~ dt^zeta(q)` by least squares on the logs. `zeta` linear in
`q` is monofractal - one exponent describes every moment. Curved is
multifractal.

Curvature is reported as the **intermittency coefficient** of the lognormal
cascade, which is the standard one-number summary and the one with a known
value under the null:

    zeta(q) = q*H - (lambda^2 / 2) * (q^2 - q)

`lambda^2 = 0` is monofractal. It is fitted by least squares over the q ladder,
so it is a description of the curvature rather than a claim that the lognormal
cascade is the right model.

## The controls, which decide whether any of this can be read

`cascading.md` names the likely failure itself: "the estimates being too noisy
at our sample sizes to separate the two ... should be checked first on a
synthetic series with a *known* construction, where the answer is already
known." So four control arms run through the identical estimator at matched
sample size, before any instrument is read:

* **gaussian** - an i.i.d. Gaussian random walk. `lambda^2 = 0` exactly. What
  this arm returns is the estimator's **bias and noise floor**, and any
  instrument inside it is not distinguishable from monofractal.
* **shuffled** - each feed's own 1m returns, permuted. Same marginal
  distribution, all time structure destroyed, so `lambda^2 = 0` by
  construction. This is the sharper null: it holds the fat tails fixed and
  removes only the clustering, which is what separates "fat-tailed" from
  "multifractal".
* **mrw-0.02**, **mrw-0.05** - a multifractal random walk (Bacry, Delour and
  Muzy) built with a **known** `lambda^2`. An estimator that cannot recover
  these at our n cannot be trusted to report them on an instrument, and the
  whole test is void.
* **iid-t3** - i.i.d. Student-t with three degrees of freedom. `lambda^2 = 0`
  by construction and the marginal is as fat as a real 1m return. This is the
  arm that separates "multifractal" from "merely fat-tailed", which is the
  confusion the whole measurement is exposed to: a heavy marginal Gaussianises
  under aggregation, and a **crossover** in how fast that happens reads as
  curvature in `zeta(q)` whether or not anything is cascading.
* **mrw-t3-0.05** - the same multifractal random walk driven by t(3)
  innovations instead of Gaussian ones: known `lambda^2 = 0.05` *and* a fat
  marginal. Read against `iid-t3` it says how much of a reading is the cascade
  and how much is the tail.

**Split-sample.** 60 days cut in half by time; `lambda^2` is reported on each
half. A curvature that does not survive the split is not reported as one.

**Strata.** `shared.strata.compare` cuts `lambda^2` by instrument class and by
which half it came from.

## What kills it

Everything coming out multifractal; or the two `mrw` arms not separating from
the `gaussian` arm, which would mean the sample is too small to answer at all;
or the synthetics and the real markets landing on top of each other.
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
SEED = int(os.environ.get("SEED", "11"))
MINUTE = 60_000
#: Aggregations in minutes. Stops at 256 (about four hours): beyond that a 60-day
#: sample holds too few non-overlapping windows for a fourth moment to mean
#: anything, and the fit would be reading one or two observations. The two
#: split halves lose the top rung on the gappier feeds, so their ladder is
#: shorter than the whole sample's and their `lambda^2` is compared for sign
#: rather than for level.
SCALES = tuple(int(s) for s in os.environ.get("SCALES", "1,2,4,8,16,32,64,128,256").split(","))
#: Moments. Stops at 4: `S_5` on 80,000 points is a statement about the largest
#: two returns in the sample, which is why the control arms exist.
QS = tuple(float(q) for q in os.environ.get("QS", "0.5,1,1.5,2,2.5,3,4").split(","))
MIN_WINDOWS = 150
MIN_BARS = 20_000
REPEATS = int(os.environ.get("REPEATS", "3"))

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


def aggregate(ts: np.ndarray, close: np.ndarray, dt: int) -> np.ndarray:
    """Log returns over `dt` minutes, from complete contiguous windows only.

    Built by summing 1m returns rather than by dividing two closes, so a window
    spanning a weekend cannot appear: a 1m return counts only between adjacent
    minutes, and a `dt` window counts only when all `dt` of its returns
    survived. At `q = 4` a single weekend gap decides `S_q`, so this is not
    fussiness.
    """
    step = np.diff(ts) == MINUTE
    r = np.log(close[1:] / close[:-1])
    keep = step & np.isfinite(r)
    r, rts = r[keep], ts[1:][keep]
    if r.size < dt * 3:
        return np.array([])
    idx = rts // (dt * MINUTE)
    uniq, first, counts = np.unique(idx, return_index=True, return_counts=True)
    if uniq.size < 3:
        return np.array([])
    sums = np.add.reduceat(r, first)
    return sums[counts == dt]


def zeta(ts: np.ndarray, close: np.ndarray) -> dict | None:
    """`zeta(q)` over the scale ladder, plus the fitted curvature."""
    logs: dict[float, list[tuple[float, float]]] = {q: [] for q in QS}
    used = []
    for dt in SCALES:
        r = np.abs(aggregate(ts, close, dt))
        if r.size < MIN_WINDOWS:
            continue
        used.append((dt, r.size))
        for q in QS:
            s = float(np.mean(r ** q))
            if s > 0 and math.isfinite(s):
                logs[q].append((math.log(dt), math.log(s)))
    if len(used) < 5:
        return None
    exps: dict[float, float] = {}
    fits: dict[float, float] = {}
    for q in QS:
        pts = logs[q]
        if len(pts) < 5:
            return None
        x = np.array([a for a, _ in pts])
        y = np.array([b for _, b in pts])
        slope, intercept = np.polyfit(x, y, 1)
        exps[q] = float(slope)
        pred = slope * x + intercept
        ss = float(np.sum((y - y.mean()) ** 2))
        fits[q] = 1.0 - float(np.sum((y - pred) ** 2)) / ss if ss > 0 else 0.0
    # zeta(q) = q*H - (lam2/2)(q^2 - q)  ->  least squares in (H, lam2).
    qs = np.array(QS)
    design = np.column_stack([qs, -0.5 * (qs * qs - qs)])
    target = np.array([exps[q] for q in QS])
    (h, lam2), *_ = np.linalg.lstsq(design, target, rcond=None)
    pred = design @ np.array([h, lam2])
    ss = float(np.sum((target - target.mean()) ** 2))
    return {
        "zeta": exps,
        "H": float(h),
        "lam2": float(lam2),
        "r2": 1.0 - float(np.sum((target - pred) ** 2)) / ss if ss > 0 else 0.0,
        "linear_r2": min(fits.values()),
        "scales": len(used),
        "n_small": used[0][1],
        # The plainest statement of curvature, free of any cascade model: the
        # difference between the exponent implied by the second moment and by
        # the fourth. Zero for a monofractal of any H.
        "bend": float(exps[2.0] / 2.0 - exps[4.0] / 4.0) if 2.0 in exps and 4.0 in exps else float("nan"),
    }


def mrw(n: int, lam2: float, rng: np.random.Generator, corr_len: int = 4096,
        heavy: bool = False) -> np.ndarray:
    """A multifractal random walk with a **known** intermittency coefficient.

    Bacry, Delour and Muzy: `r_t = eps_t * exp(omega_t)` with `omega` Gaussian
    and `cov(omega_i, omega_j) = lambda^2 * ln(T / (|i-j| + 1))` out to the
    integral scale `T`, and `E[omega] = -var(omega)` so the variance is fixed.
    The **logarithmic** covariance is the whole construction: it is what makes
    the scaling non-linear in `q`, and it is why this is a positive control
    rather than merely a fat-tailed series.

    Built by circulant embedding over a grid at least twice the series length,
    so there are no block boundaries at which the long-range correlation would
    silently reset - the failure that would make a positive control read as a
    weaker one. Negative eigenvalues from the embedding are clipped, which is
    the standard approximation and the only one here.

    The fitted convention is `zeta(q) = qH - (lambda^2/2)(q^2 - q)`, the same
    one the report fits. If the two disagree by a constant the control says so:
    a recovered value that is a fixed multiple of the known one is a convention
    mismatch and is read as a calibration, not as a failure.
    """
    t = min(corr_len, max(n // 4, 8))
    lags = np.arange(t, dtype=float)
    cov = lam2 * np.log(t / (lags + 1.0))
    cov[cov < 0] = 0.0
    size = 1
    while size < 2 * n:
        size *= 2
    circ = np.zeros(size)
    circ[:t] = cov
    circ[size - t + 1:] = cov[1:][::-1]
    eig = np.fft.fft(circ).real
    eig[eig < 0] = 0.0
    z = rng.normal(size=size) + 1j * rng.normal(size=size)
    omega = np.fft.fft(np.sqrt(eig / size) * z).real[:n]
    omega = omega - float(np.var(omega))
    eps = rng.standard_t(3.0, size=n) if heavy else rng.normal(size=n)
    return eps * np.exp(omega)


def walk(returns: np.ndarray) -> np.ndarray:
    """A positive close series carrying the given 1m returns."""
    scale = float(np.std(returns))
    if scale <= 0 or not math.isfinite(scale):
        scale = 1e-4
    r = returns / scale * 1e-4
    return np.exp(np.cumsum(np.clip(r, -0.5, 0.5)))


def run() -> None:
    started = time.time()
    rng = np.random.default_rng(SEED)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=600.0)
    feeds = [f for (f,) in conn.execute("SELECT DISTINCT feed FROM bars ORDER BY feed")]
    span = conn.execute("SELECT MIN(ts), MAX(ts) FROM bars WHERE interval='1m'").fetchone()
    cut = (span[0] + span[1]) // 2
    print(f"scales (minutes): {SCALES}")
    print(f"moments q: {QS}")
    print(f"{len(feeds)} feeds, split at {cut}\n")

    per_feed: list[dict] = []
    rows: list[dict] = []
    control: dict[str, list[float]] = defaultdict(list)
    control_h: dict[str, list[float]] = defaultdict(list)
    control_bend: dict[str, list[float]] = defaultdict(list)
    deltas: list[dict] = []
    zeta_mean: dict[str, dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))

    for n, feed in enumerate(feeds, 1):
        raw = conn.execute(
            "SELECT ts, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts", (feed,)
        ).fetchall()
        ts = np.array([r[0] for r in raw], dtype=np.int64)
        close = np.array([float(r[1]) for r in raw], dtype=float)
        keep = close > 0
        ts, close = ts[keep], close[keep]
        if ts.size < MIN_BARS:
            print(f"  {feed}: {ts.size} bars, skipped")
            continue

        whole = zeta(ts, close)
        if whole is None:
            print(f"  {feed}: no fit")
            continue
        first = zeta(ts[ts < cut], close[ts < cut])
        second = zeta(ts[ts >= cut], close[ts >= cut])

        step = np.diff(ts) == MINUTE
        r1 = np.where(step, np.log(close[1:] / close[:-1]), 0.0)
        shuffled = zeta(ts[1:], walk(rng.permutation(r1)))
        live = r1[step]
        dev = live - live.mean()
        sd = float(np.sqrt(np.mean(dev * dev)))
        kurt = float(np.mean(dev ** 4) / sd ** 4) if sd > 0 else float("nan")

        per_feed.append({
            "feed": feed, "klass": klass(feed), "n": int(ts.size),
            "H": whole["H"], "lam2": whole["lam2"], "bend": whole["bend"],
            "r2": whole["r2"], "linear_r2": whole["linear_r2"],
            "first": first["lam2"] if first else float("nan"),
            "second": second["lam2"] if second else float("nan"),
            "shuffled": shuffled["lam2"] if shuffled else float("nan"),
            "delta": (whole["lam2"] - shuffled["lam2"]) if shuffled else float("nan"),
            "kurt": kurt,
        })
        for q in QS:
            zeta_mean[klass(feed)][q].append(whole["zeta"][q])
        if shuffled:
            deltas.append({
                "delta": whole["lam2"] - shuffled["lam2"], "klass": klass(feed),
                "feed": feed, "interval": "1m",
                "generated": "generated" if klass(feed) == "synthetic" else "real",
            })
        rows.append({
            "lam2": whole["lam2"], "klass": klass(feed), "feed": feed,
            "generated": "generated" if klass(feed) == "synthetic" else "real",
            "interval": "1m", "half": "whole",
        })
        if first:
            rows.append({"lam2": first["lam2"], "klass": klass(feed), "feed": feed,
                         "generated": "generated" if klass(feed) == "synthetic" else "real",
                         "interval": "1m", "half": "first"})
        if second:
            rows.append({"lam2": second["lam2"], "klass": klass(feed), "feed": feed,
                         "generated": "generated" if klass(feed) == "synthetic" else "real",
                         "interval": "1m", "half": "second"})
        if shuffled:
            control["shuffled"].append(shuffled["lam2"])
            control_bend["shuffled"].append(shuffled["bend"])
        if n % 10 == 0:
            print(f"  {n}/{len(feeds)} feeds  {time.time() - started:.0f}s")

    # The control arms, at the sample size the instruments actually have.
    n_typ = int(st.median([r["n"] for r in per_feed])) if per_feed else 80_000
    grid = np.arange(n_typ, dtype=np.int64) * MINUTE
    print(f"\ncontrol arms at n = {n_typ:,} 1m bars, {REPEATS} draws each")
    for _ in range(REPEATS):
        for name, made in (
            ("gaussian", rng.normal(size=n_typ)),
            ("iid-t3", rng.standard_t(3.0, size=n_typ)),
            ("mrw-0.02", mrw(n_typ, 0.02, rng)),
            ("mrw-0.05", mrw(n_typ, 0.05, rng)),
            ("mrw-t3-0.05", mrw(n_typ, 0.05, rng, heavy=True)),
        ):
            got = zeta(grid, walk(made))
            if got:
                control[name].append(got["lam2"])
                control_h[name].append(got["H"])
                control_bend[name].append(got["bend"])

    print("\n" + "=" * 92)
    print("TWO: control arms first. If mrw does not separate from gaussian, nothing below is readable.")
    print("=" * 92)
    print(f"  {'arm':>12s} {'draws':>6s} {'lambda^2':>10s} {'sd':>8s} {'known':>8s} {'bend':>9s}")
    known = {"gaussian": 0.0, "iid-t3": 0.0, "shuffled": 0.0,
             "mrw-0.02": 0.02, "mrw-0.05": 0.05, "mrw-t3-0.05": 0.05}
    floor = None
    for name in ("gaussian", "iid-t3", "shuffled", "mrw-0.02", "mrw-0.05", "mrw-t3-0.05"):
        vals = control.get(name) or []
        if not vals:
            continue
        sd = st.stdev(vals) if len(vals) > 1 else float("nan")
        bend = st.fmean(control_bend[name]) if control_bend.get(name) else float("nan")
        print(f"  {name:>12s} {len(vals):6d} {st.fmean(vals):10.5f} {sd:8.5f} "
              f"{known[name]:8.3f} {bend:9.5f}")
        if name == "shuffled":
            floor = (st.fmean(vals), sd)
    if floor:
        print(f"\n  the readable floor is the shuffled arm: {floor[0]:.5f} +/- {floor[1]:.5f}.")
        print("  An instrument inside it is not distinguishable from monofractal at this n.")
        print("  The shuffled arm is monofractal BY CONSTRUCTION - same returns, order destroyed -")
        print("  so whatever it scores above zero is what this estimator reads off the marginal")
        print("  distribution alone. Read every instrument against its OWN shuffle, not against 0.")

    print("\n" + "=" * 92)
    print("Per instrument. lambda^2 = 0 is monofractal; larger is more curved.")
    print("=" * 92)
    print(f"  {'feed':>24s} {'class':>10s} {'bars':>8s} {'H':>7s} {'lambda^2':>9s} "
          f"{'shuffled':>9s} {'delta':>9s} {'first':>8s} {'second':>8s} {'kurt 1m':>9s} {'fit r2':>7s}")
    for r in sorted(per_feed, key=lambda r: -r["lam2"]):
        print(f"  {r['feed']:>24s} {r['klass']:>10s} {r['n']:8,d} {r['H']:7.4f} "
              f"{r['lam2']:9.5f} {r['shuffled']:9.5f} {r['delta']:+9.5f} {r['first']:8.5f} "
              f"{r['second']:8.5f} {r['kurt']:9.1f} {r['r2']:7.4f}")

    print("\nby class:")
    print(f"  {'class':>10s} {'feeds':>6s} {'lambda^2':>10s} {'sd':>8s} {'H':>8s} "
          f"{'delta':>9s} {'split agrees':>13s} {'above shuffle':>14s}")
    for name in sorted({r["klass"] for r in per_feed}):
        part = [r for r in per_feed if r["klass"] == name]
        vals = [r["lam2"] for r in part]
        agree = [r for r in part if math.isfinite(r["first"]) and math.isfinite(r["second"])]
        same = sum(1 for r in agree if (r["first"] > 0) == (r["second"] > 0))
        above = sum(1 for r in part if math.isfinite(r["shuffled"]) and r["lam2"] > r["shuffled"])
        dlt = [r["delta"] for r in part if math.isfinite(r["delta"])]
        print(f"  {name:>10s} {len(part):6d} {st.fmean(vals):10.5f} "
              f"{(st.stdev(vals) if len(vals) > 1 else float('nan')):8.5f} "
              f"{st.fmean(r['H'] for r in part):8.4f} "
              f"{(st.fmean(dlt) if dlt else float('nan')):+9.5f} "
              f"{same}/{len(agree):<12d} {above}/{len(part)}")

    print("\nmean zeta(q) by class - linear in q is monofractal:")
    head = "  " + f"{'class':>10s}" + "".join(f"{('q=' + str(q)):>9s}" for q in QS)
    print(head)
    for name in sorted(zeta_mean):
        line = f"  {name:>10s}"
        for q in QS:
            vals = zeta_mean[name][q]
            line += f"{(st.fmean(vals) if vals else float('nan')):9.4f}"
        print(line)

    print("\n" + "=" * 92)
    print("The verdict that survives the shuffle control: which feeds are FLAT, meaning both the")
    print("instrument and its own shuffle sit inside the Gaussian arm's noise. Those are the only")
    print("series this measurement can call monofractal without arguing about the marginal.")
    print("=" * 92)
    gauss = control.get("gaussian") or [0.0]
    edge = max(abs(st.fmean(gauss)) + 3.0 * (st.stdev(gauss) if len(gauss) > 1 else 0.003), 0.01)
    print(f"  threshold |lambda^2| < {edge:.5f}, three sd of the Gaussian arm")
    flat = [r for r in per_feed if abs(r["lam2"]) < edge and abs(r.get("shuffled") or 1) < edge]
    print(f"  {len(flat)} of {len(per_feed)} feeds are flat:")
    for r in sorted(flat, key=lambda r: r["feed"]):
        print(f"    {r['feed']:>24s} {r['klass']:>10s} lambda^2 {r['lam2']:+8.5f} "
              f"H {r['H']:.4f}  kurtosis(1m) {r['kurt']:7.2f}")
    rest = [r for r in per_feed if r not in flat]
    print(f"  not flat, by class: " + ", ".join(
        f"{k} {sum(1 for r in rest if r['klass'] == k)}/{sum(1 for r in per_feed if r['klass'] == k)}"
        for k in sorted({r['klass'] for r in per_feed})))

    if rows:
        print("\n" + "=" * 92)
        print("Conditioned: lambda^2 for generated against real, cut within class and within half")
        print("=" * 92)
        print(compare(rows, value="lam2", bucket="generated",
                      within=("klass", "half"), min_n=8).render())
    if deltas:
        print("\n" + "=" * 92)
        print("Conditioned again, on the quantity the control says is readable: lambda^2 minus the")
        print("feed's own shuffle. Zero means the reading is the marginal and nothing else.")
        print("=" * 92)
        print(compare(deltas, value="delta", bucket="generated",
                      within=("klass",), min_n=8).render())

    print(f"\n{time.time() - started:.0f}s")


if __name__ == "__main__":
    run()
