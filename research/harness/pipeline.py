"""The deterministic middle of Deriv's synthetic-quote pipeline, identified.

A generator of this kind is a chain, and only its two ends have been looked at:

    CSPRNG -> uniform u -> inverse-normal Phi^-1(u) -> recursion -> quantise -> publish
    \\_____ rebuildpredict.py _____/                                \\_ frac_zero, n_distinct _/

[`rebuildpredict.py`](rebuildpredict.py) attacked the source - k-tuple spectral
tests, MT19937 untempering, truncated-LCG lattice reduction - and found nothing,
which is what a regulated venue should look like. The **middle three stages have
never been identified, and they are deterministic**, which makes them a
categorically softer target than a cryptographic source. This file identifies
what can be identified and states, with arithmetic, what cannot.

Six questions, each with the sample it would take to answer written *before* the
number is read.

1. **Is the increment distribution continuous, or does it live on a finite set?**
   If the inverse-normal is a lookup table or a limited-precision approximation,
   the achievable log-increments are finite and enumerable, and `rebuildpredict.py`
   rung 3 becomes a search over a small set instead of a lattice reduction.
2. **Which drift convention does the recursion use** - `exp(-sigma^2/2 dt + sigma dW)`
   or `exp(sigma dW)`? `structures/vol/projection.py` scores both live; this
   answers it offline by pooling the whole family's history.
3. **What exactly is the quantiser** - the grid per feed, and the rounding rule.
4. **Does the quantisation error accumulate**, or is the internal state
   full-precision and the rounding only for display?
5. **What is `dt`, exactly**, and is it the same clock on every feed?
6. **How many bits of the underlying uniform survive to the published quote?**

## The trap this page is built around, stated before any test

**Quote quantisation alone produces a discrete set of observable price
differences.** Every published increment on `Volatility 75 Index` is an exact
multiple of 0.01, so "the increments take finitely many values" is *true by
construction* and says nothing whatever about the inverse-normal. The null for
question 1 is therefore **"discrete because the price grid is discrete"**, not
"continuous", and a test that fails to separate those two produces a spectacular
false positive - the most likely single failure mode of this whole arm.

Three things follow, and all three are enforced in code rather than argued:

* Every statistic is computed on the **implied pre-quantisation** variate `z`,
  reconstructed from the published quotes, and the reconstruction's own
  resolution `eps = 1 / (sqrt(6) * sigma_Y)` is carried alongside it. `sigma_Y`
  is the per-tick move in lattice units, and it is the single number that
  decides how much of the middle of the pipeline is visible at all.
* Every positive claim is run against a simulator - [`pipesim.py`](pipesim.py) -
  whose stages are **known**, at the real feed's own price, grid, sigma and
  sample size, through the identical code path. The **recovery rate** on that
  simulator is reported beside every result.
* Every test is *also* run against a simulator built the honest way - a
  continuous inverse-normal, quantised exactly as the real feed is. A test that
  fires there is broken, and its **false-positive rate** is reported beside the
  recovery rate. That check is worth as much as the other one.

## What would count as failure, written before any number was looked at

1. **Question 1 dies** - the increments are not continuous - if the atom battery
   exceeds, on a real feed, the bar set by the **calibration half** of the
   continuous controls at the same sample size, grid and price. Three legs: the
   extreme-value cap on `|z|`, the empirical characteristic function scanned for
   a lattice in `z`, and the `u`-space test standardised per bit width and
   maximised over them.
2. **The run is void** if the battery cannot recover a lookup table it is shown:
   a table of `2**k` entries, quantised exactly as the real feed is, must be
   caught at every `k` the arithmetic says is reachable. A battery that cannot
   see a generator known to be coarse says nothing about one that might be fine.
3. **The false-positive rate is measured out of sample, on the half of the
   continuous controls that did not set the bar,** and is quoted beside every
   result. It is *not* optional and it is not allowed to be in-sample: the first
   version of this battery set one bar per bit width at the control maximum and
   reported zero false positives, which was true in sample and meaningless - a
   fresh continuous draw cleared a nineteen-fold maximum two runs in six, and
   the battery duly "detected" a 32-bit uniform. A test that fires on data drawn
   from a perfect inverse normal is worse than no test, because it produces a
   finding.
4. **Question 2 is reported as unresolved** unless the pooled separation between
   the two conventions exceeds 3 standard errors. The separation is
   `sqrt(sum of sigma_i^2 T_i) / 2` and depends on **calendar span, not bar
   count** - see the note under section 4, which is a correction to
   `projection.py`'s `RESOLVES_AT`.
5. **Question 3 is reported as unidentifiable** if the simulator shows the five
   rounding modes producing the same published statistics to within Monte Carlo
   error. That is a theorem before it is a measurement and the measurement is
   run anyway, because a theorem with a typo in it is a wrong answer.
6. **Question 4 dies either way.** Both answers are real facts about the
   architecture, so there is no null here to defend - only a pair of predictions
   that must bracket the observed value, or the test is uninformative.
7. **Any question the data cannot support is reported as untested**, with the
   sample it would take, and is not counted as an answer.

## Two things this page will not do

It will not turn into a trade. A predictable quote would be a defect in a
product whose terms permit voiding trades made against it, which is
[`twins.md`](../twins.md)'s conclusion and is unchanged here. And it will not
re-run `rebuildpredict.py`'s rungs: where this page's bit count bears on them it
says so and stops.

    ./.secrets/lab.sh run research/harness/pipeline.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from scipy.special import ndtr, ndtri

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipesim as SIM  # noqa: E402
from research.harness import feed, seqlab  # noqa: E402

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/pipeline.json"))
CACHE = Path(os.environ.get("PIPE_CACHE", os.path.expanduser("~/till_infinity/data/pipeline")))
SEED = int(os.environ.get("SEED", "20260912"))

#: How many ticks to pull for the feeds the atom battery runs on. The route
#: hands back 400,000 per call and walks forward from a stamp, so this is
#: chunks, not one transfer - see `pull`.
WANT = int(os.environ.get("WANT", "3000000"))
#: A smaller target for the feeds that are only there for the lattice table.
WANT_SMALL = int(os.environ.get("WANT_SMALL", "250000"))
#: Replicates of each control. 64 is the resolution of every "max over the
#: control" bar on this page: one exceedance in 64 is p = 0.016.
REPS = int(os.environ.get("REPS", "64"))
#: Replicates of each *recovery* control. Fewer, because a recovery rate of 8/8
#: and one of 64/64 say the same thing and the second costs eight times as much.
REPS_POS = int(os.environ.get("REPS_POS", "8"))
#: How many feeds get the deep pull. Chosen from the measured `sigma_Y` in
#: section 1 rather than named here: the atom battery's resolution is
#: `1 / (sqrt(6) sigma_Y)` and picking the feeds by hand would be picking the
#: answer. Two, because the deep pull is the expensive thing on the page.
N_ATOM = int(os.environ.get("N_ATOM", "2"))

#: The whole Volatility family, by the broker's own spelling. `Spot Up` is in
#: because the drift test only needs sigma to be *measurable*, not constant, and
#: it is flagged in the table rather than silently pooled.
FAMILY = (
    "Volatility 5 Index", "Volatility 10 Index", "Volatility 15 Index",
    "Volatility 25 Index", "Volatility 30 Index", "Volatility 50 Index",
    "Volatility 75 Index", "Volatility 90 Index", "Volatility 100 Index",
    "Volatility 5 (1s) Index", "Volatility 10 (1s) Index", "Volatility 15 (1s) Index",
    "Volatility 25 (1s) Index", "Volatility 30 (1s) Index", "Volatility 50 (1s) Index",
    "Volatility 75 (1s) Index", "Volatility 90 (1s) Index", "Volatility 100 (1s) Index",
    "Volatility 150 (1s) Index", "Volatility 250 (1s) Index",
    "Spot Up - Volatility Up Index", "Spot Up - Volatility Down Index",
)

#: One or two members of every other synthetic family. They are in section 1
#: and section 2 only - the grid and the clock are questions about the *quote*
#: and apply to any feed, where sections 3, 4 and 6 are about a diffusion and
#: would be reading a compound Poisson or a fixed-size coin through the wrong
#: model. "Tick size per family" in the brief is this table.
OTHERS = (
    "Jump 25 Index", "Jump 100 Index", "Boom 500 Index", "Crash 500 Index",
    "Step Index", "Step Index 200", "Range Break 100 Index", "Range Break 200 Index",
    "Drift Switch Index 30", "DEX 900 UP Index",
)

#: Nominal publication interval in seconds, from the name. Tested, not assumed -
#: section 2 measures it and section 5 asks whether the generator's `dt` is the
#: same object as the publisher's.
def nominal_dt(symbol: str) -> float:
    """Seconds between publications, from the name. Tested in section 2, not trusted.

    The Volatility family splits 2s / 1s on the `(1s)` tag. Every other synthetic
    on this book publishes once a second, which `generators.md` measured at
    0.500/s and 0.995/s for the two Volatility rates and which section 2 checks
    here for the rest rather than inheriting.
    """
    if "(1s)" in symbol:
        return 1.0
    return 2.0 if symbol.startswith("Volatility") or symbol.startswith("Spot Up") else 1.0


def named_sigma(symbol: str) -> float | None:
    """The annualised sigma the name claims, as a fraction. None when it claims nothing."""
    if "Spot Up" in symbol:
        return None
    for part in symbol.replace("(1s)", "").split():
        if part.isdigit():
            return float(part) / 100.0
    return None


# ------------------------------------------------------------------ the feed --
def pull(symbol: str, want: int, *, refresh: bool = False) -> dict[str, np.ndarray]:
    """`want` ticks for `symbol`, walked forward in chunks and kept on disk.

    **Why chunks and why forward.** `/symbols/ticks/{sym}/from` returns the
    *first* `count` ticks after a stamp and caps out at 400,000, which on a
    two-second feed is nine days. Asking for three million in one call returns
    400,000 and no error, which reads as a short feed rather than as a capped
    route - the same shape of failure `seqlab.tick_cache` was written around for
    a different reason. So the lookback is sized from the tick rate, the first
    chunk is taken from the far end, and each subsequent chunk starts where the
    last one stopped.

    The atom battery's power goes as the tail count, which goes as `n`, so this
    is the single most expensive thing on the page and the one most worth
    caching: a re-run that re-pulls twelve million ticks is an hour of a shared
    terminal that the live desk also trades through.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    slug = symbol.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "")
    path = CACHE / f"{slug}_{want}.npz"
    if path.exists() and not refresh:
        got = np.load(path)
        return {k: got[k] for k in got.files}

    dt = nominal_dt(symbol)
    hours = want * dt / 3600.0 * 1.25 + 2.0
    was, feed.TIMEOUT = feed.TIMEOUT, 1200.0
    rows: list[dict[str, float]] = []
    seen: set[float] = set()
    back = hours
    try:
        for _ in range(24):
            try:
                chunk = feed.ticks(symbol, 400_000, hours_back=back)
            except Exception as exc:  # noqa: BLE001 - a dropped chunk is not a dropped feed
                print(f"    {symbol}: chunk failed {type(exc).__name__} {str(exc)[:50]}", flush=True)
                break
            fresh = [r for r in chunk if r["time"] not in seen]
            if not fresh:
                break
            for r in fresh:
                seen.add(r["time"])
            rows.extend(fresh)
            if len(rows) >= want:
                break
            newest = max(r["time"] for r in chunk)
            back = max(0.02, (time.time() - newest) / 3600.0)
    finally:
        feed.TIMEOUT = was
    rows.sort(key=lambda r: r["time"])
    # `feed.ticks` keeps a row when *either* side is positive, so a one-sided
    # quote survives it with a zero on the other side. Every statistic here goes
    # through `log(bid)`, where a zero is not a small number but a `-inf` that
    # propagates into a standard deviation four frames away.
    rows = [r for r in rows if r["bid"] > 0 and r["ask"] > 0]
    rows = rows[-want:]
    cols = {k: np.asarray([r[k] for r in rows], dtype=float) for k in ("time", "bid", "ask")}
    cols["mid"] = (cols["bid"] + cols["ask"]) / 2.0
    if len(rows) > 1000:
        np.savez_compressed(path, **cols)
    return cols


# --------------------------------------------------------------- the lattice --
def decimals(v: np.ndarray, maxd: int = 10) -> int | None:
    """Smallest `d` with every quote an exact multiple of `10**-d`."""
    x = np.asarray(v, dtype=float)
    if x.size > 300_000:
        x = x[:: max(1, x.size // 300_000)]
    for d in range(maxd + 1):
        s = x * (10.0**d)
        if np.all(np.abs(s - np.round(s)) < 1e-4):
            return d
    return None


def grid_of(v: np.ndarray) -> tuple[float, int | None]:
    """The lattice the quotes actually move on, and the decimals they print to.

    Decimal precision is not the grid. `twins.md` quarantined
    `Volatility 150 (1s)` for a *coarse* grid, and a feed that prints five
    decimals but moves in steps of ten of them has a grid ten times the
    printed resolution. So the decimals fix the scale and the greatest common
    divisor of the moves fixes the spacing - `rebuildgen.quote_grid`'s argument,
    reproduced here because this file is run on feeds that one was not.
    """
    d = decimals(v)
    if d is None:
        return 0.0, None
    scale = 10.0**d
    diffs = np.abs(np.diff(np.asarray(v, dtype=float)))
    ints = np.round(diffs[diffs > 0] * scale).astype(np.int64)
    if ints.size == 0:
        return float(10.0**-d), d
    g = int(np.gcd.reduce(ints[: min(ints.size, 400_000)]))
    return float(max(g, 1)) / scale, d


def bits_per_tick(sigma_lat: float) -> float:
    """How much of the underlying draw one published quote reveals.

    A variate of standard deviation `s` lattice units carries about
    `log2(s * sqrt(2 pi e))` bits once discretised - the differential entropy of
    the Gaussian less `log2` of the cell. That number decides
    `rebuildpredict.py`'s rungs 2 and 3 before either is run, and it is the
    reason this file reports it per feed rather than once.
    """
    return math.log2(sigma_lat * math.sqrt(2 * math.pi * math.e)) if sigma_lat > 0 else 0.0


# ----------------------------------------------------------------- the clock --
def clock(t: np.ndarray, nominal: float) -> dict:
    """The publication timetable: period, jitter, missing slots, doubled slots.

    The slot index is `round(t / nominal)` and the offset is what is left. If
    the venue publishes on a fixed schedule the offsets are a tight distribution
    about one value and the slot indices are consecutive; if it publishes on
    completion the offsets random-walk. The distinction decides whether `dt` is
    the nominal period or the realised gap, which section 5 then tests directly
    against the variance of the increment.
    """
    ms = np.round(np.asarray(t) * 1000.0).astype(np.int64)
    per = int(round(nominal * 1000))
    gaps = np.diff(ms)
    slot = ms // per
    off = ms - slot * per
    span = int(slot[-1] - slot[0]) + 1
    uniq = np.unique(slot).size
    return {
        "n": int(ms.size),
        "hours": float((ms[-1] - ms[0]) / 3.6e6),
        "gap_mean_ms": float(gaps.mean()),
        "gap_median_ms": float(np.median(gaps)),
        "gap_mode_ms": int(np.bincount(np.clip(gaps, 0, 20_000)).argmax()),
        "gap_p01_ms": float(np.quantile(gaps, 0.01)),
        "gap_p99_ms": float(np.quantile(gaps, 0.99)),
        "offset_mean_ms": float(off.mean()),
        "offset_sd_ms": float(off.std()),
        "offset_p01_ms": float(np.quantile(off, 0.01)),
        "offset_p99_ms": float(np.quantile(off, 0.99)),
        "slots_spanned": span,
        "slots_filled": int(uniq),
        "slots_empty": int(span - uniq),
        "slots_doubled": int(ms.size - uniq),
        "empty_frac": float((span - uniq) / max(span, 1)),
        "period_from_slots_ms": float((ms[-1] - ms[0]) / max(span - 1, 1)),
    }


def variance_vs_gap(x: np.ndarray, gaps_ms: np.ndarray, nominal: float) -> dict:
    """Does the increment know about the clock's jitter, or only about the slot?

    A sharp question and the only one that separates "`dt` is the published
    period" from "`dt` is the realised gap". If the generator steps once per slot
    then a tick that arrives 50ms late carries the same variance as one on time;
    if it integrates real time then the variance is proportional to the gap and
    a 2.5% longer gap carries 2.5% more variance.

    Reported as the regression of `x^2` on the gap, in units of "fraction of the
    variance per nominal period", so 1.0 means the generator runs on the wall
    clock and 0.0 means it runs on the slot counter. Its standard error is
    `sqrt(2 / n) / (sd(gap) / nominal)`, which is what makes this answerable at
    all: a million ticks and a 66ms spread on a 2s period resolve it to 0.04.
    """
    g = np.asarray(gaps_ms, dtype=float) / (nominal * 1000.0)
    keep = (g > 0.5) & (g < 1.5)
    g, y = g[keep], np.asarray(x, dtype=float)[keep] ** 2
    if g.size < 1000 or g.std() < 1e-9:
        return {"n": int(g.size), "slope": float("nan"), "se": float("nan"), "z": float("nan")}
    gc = g - g.mean()
    slope = float((gc * y).sum() / (gc * gc).sum()) / float(y.mean())
    se = float(math.sqrt(2.0 / g.size) / g.std())
    return {"n": int(g.size), "slope": slope, "se": se, "z": float(slope / se),
            "gap_sd_rel": float(g.std())}


def shared_jitter(a: dict, b: dict, nominal_a: float, nominal_b: float) -> dict:
    """Whether two feeds' publication offsets move together within the same slot.

    `twins.md` found all sixteen synthetics printing within 8-9ms of each other
    and read it as a shared timetable. This asks the next question: is the
    *jitter* shared too? A correlation near 1 says one publisher stamps them all
    and the jitter is the publisher's; near 0 says the timetable is shared and
    the jitter is per-feed transport. Only the common period is used, so a 1s
    feed and a 2s feed are compared on the 2s slots they both print in.
    """
    per = int(round(max(nominal_a, nominal_b) * 1000))
    out = {}
    for name, d in (("a", a), ("b", b)):
        ms = np.round(d["time"] * 1000.0).astype(np.int64)
        out[name] = (ms // per, ms % per)
    sa, oa = out["a"]
    sb, ob = out["b"]
    common, ia, ib = np.intersect1d(sa, sb, return_indices=True)
    if common.size < 1000:
        return {"n": int(common.size), "corr": float("nan")}
    x, y = oa[ia].astype(float), ob[ib].astype(float)
    c = float(np.corrcoef(x, y)[0, 1])
    return {"n": int(common.size), "corr": c, "median_abs_ms": float(np.median(np.abs(x - y))),
            "sd_a_ms": float(x.std()), "sd_b_ms": float(y.std())}


# ------------------------------------------------------- the implied variate --
def implied_z(px: np.ndarray, t: np.ndarray, nominal: float, grid: float) -> dict:
    """The pre-quantisation variate, reconstructed, with its own resolution beside it.

    `z = (log P_t - log P_{t-1}) / sigma_tick`, standardised on the sample's own
    second moment rather than on the instrument's name - the atom tests are
    about the *shape* of the achievable set and must not inherit a 0.5% error in
    sigma as a 0.5% rescaling of it.

    **Only consecutive pairs one nominal period apart are kept.** A pair that
    straddles a missing tick is two draws, not one, and mixing the two puts a
    scale mixture into a test whose whole subject is whether the scale takes one
    value or several. This is the single most important line in the file.

    `eps` is the resolution: the published quote pins the internal price to
    +-grid/2, so the increment carries additive noise of standard deviation
    `grid/sqrt(6)` in price, which is `1 / (sqrt(6) sigma_Y)` in `z`. **No atom
    finer than `eps` is visible from published quotes, at any sample size**, and
    that bound is what turns "we found nothing" into "we could not have found
    anything" for every table below it.
    """
    ms = np.round(np.asarray(t) * 1000.0).astype(np.int64)
    slot = ms // int(round(nominal * 1000))
    ok = np.diff(slot) == 1
    lp = np.log(np.asarray(px, dtype=float))
    x = np.diff(lp)[ok]
    price = float(np.median(px))
    sd = float(x.std())
    z = (x - x.mean()) / sd
    sigma_lat = sd * price / grid if grid > 0 else float("inf")
    return {
        "z": z,
        "x": x,
        "n": int(z.size),
        "kept_frac": float(ok.mean()),
        "sd_rel": sd,
        "price": price,
        "sigma_lat": sigma_lat,
        "eps": 1.0 / (math.sqrt(6.0) * sigma_lat) if sigma_lat > 0 else float("inf"),
        "bits": bits_per_tick(sigma_lat),
    }


# ------------------------------------------------------------ atom battery A --
def cap_test(z: np.ndarray, eps: float) -> dict:
    """The largest `|z|` the feed produced, against the cap a `k`-bit uniform imposes.

    If `u` is drawn as a `k`-bit integer over `2**k` then the largest reachable
    normal is `Phi^-1(1 - 2**-k)` **exactly** - a hard ceiling, not a tail
    property - while `n` draws from a continuous normal reach about
    `Phi^-1(1 - 1/(2n))`. So a feed whose extreme sits where continuity predicts
    excludes every `k` whose ceiling is below it, and the excluded range is
    `k <= log2(2n)` and no further. That bound is the honest ceiling on this
    leg and it is reported rather than implied.

    Robust to a mis-specified sigma in a way the other two legs are not: a 0.5%
    error in the scale moves the observed maximum by 0.5% where the gap between
    adjacent `k` ceilings is 5-15%.
    """
    m = float(np.max(np.abs(z)))
    n = int(z.size)
    expect = float(ndtri(1.0 - 1.0 / (2.0 * n)))
    excluded = []
    for k in range(4, 53):
        ceiling = float(ndtri(1.0 - 2.0**-k))
        if ceiling + 5.0 * eps < m:
            excluded.append(k)
    return {
        "max_abs_z": m,
        "n": n,
        "expected_max": expect,
        "ratio": m / expect,
        "bits_excluded_upto": max(excluded) if excluded else 0,
        "reach": math.log2(2.0 * n),
    }


# ------------------------------------------------------------ atom battery B --
def ecf_scan(z: np.ndarray, w_hi: float, *, w_lo: float = 10.0, dz: float = 1e-4,
             pad: int = 1 << 21, exclude: tuple[tuple[float, float], ...] = ()) -> dict:
    """The empirical characteristic function of `z`, scanned for a lattice.

    A variate confined to a lattice of spacing `h` has `|phi(2 pi / h)| = 1`
    exactly; a continuous one has `|phi(w)| = exp(-w^2/2)`, which is `1e-9` by
    `w = 6.5`. So any magnitude at high frequency is an atom, and the frequency
    names the spacing. Reconstruction noise damps the peak by
    `exp(-(w eps)^2 / 2)`, which is why the scan stops at `w_hi`: past
    `3 / eps` there is nothing left to see whatever is there.

    Computed as an FFT of a fine histogram rather than a direct sum. A direct
    sum over three million points at ten thousand frequencies is `3e10`
    exponentials; the histogram costs one pass and the FFT is milliseconds, and
    the only price is the bin's own transform, which is divided back out.

    **The quote lattice is in here too, and it is the one thing that could be
    mistaken for the finding.** Published increments are integer multiples of
    the grid, so `z` sits near a lattice of spacing `1 / sigma_Y` and would ring
    at `w = 2 pi sigma_Y` and its harmonics - were it not smeared by the price's
    own drift across the sample, which changes that spacing by several percent.
    Those windows are therefore **excluded from the search and reported
    separately**: a peak inside one of them cannot be attributed, and the honest
    statement is that a `z`-lattice whose spacing is within a few percent of the
    quote grid's own is a blind spot of this test at any sample size.
    """
    z = np.asarray(z, dtype=float)
    lim = float(np.abs(z).max()) + 4 * dz
    nb = int(2 * lim / dz) + 2
    h, edges = np.histogram(z, bins=nb, range=(-lim, -lim + nb * dz))
    n = h.sum()
    if pad < nb:
        pad = 1 << int(math.ceil(math.log2(nb)))
    spec = np.fft.rfft(h.astype(np.float64), n=pad)
    w = 2.0 * math.pi * np.arange(spec.size) / (pad * dz)
    mag = np.abs(spec) / n
    # Divide out the histogram bin's own transform, so a peak is the variate's.
    arg = w * dz / 2.0
    sinc = np.ones_like(w)
    nz = arg > 0
    sinc[nz] = np.sin(arg[nz]) / arg[nz]
    mag = mag / np.maximum(sinc, 1e-3)
    band = (w >= w_lo) & (w <= w_hi)
    for lo, hi in exclude:
        band &= ~((w >= lo) & (w <= hi))
    if not band.any():
        return {"max": float("nan"), "at_w": float("nan"), "n": int(n), "w_hi": w_hi,
                "_w": w, "_mag": mag}
    i = int(np.argmax(mag[band]))
    wb, mb = w[band], mag[band]
    return {"max": float(mb[i]), "at_w": float(wb[i]), "spacing": float(2 * math.pi / wb[i]),
            "n": int(n), "w_lo": w_lo, "w_hi": w_hi, "floor": float(1.0 / math.sqrt(n)),
            "excluded": [list(e) for e in exclude], "_w": w, "_mag": mag}


def lattice_peak(scan: dict, sigma_lat: float) -> float:
    """The magnitude at the quote lattice's own frequency - the machinery's check."""
    w, mag = scan.get("_w"), scan.get("_mag")
    if w is None:
        return float("nan")
    target = 2.0 * math.pi * sigma_lat
    i = int(np.argmin(np.abs(w - target)))
    lo, hi = max(0, i - 40), min(w.size, i + 40)
    return float(np.max(mag[lo:hi]))


# ------------------------------------------------------------ atom battery C --
def u_bits(z: np.ndarray, eps: float, *, ks=range(8, 33), tail: float = 2.5,
           eta: float = 3e-3, n_eta: int = 241) -> dict:
    """How many bits the uniform carries, tested in `u` space with a matched filter.

    If `u = j / 2**k` then `Phi(z)` lies on a lattice of spacing `2**-k` and
    `|phi_u(2 pi 2**k)| = 1`. Three things shape this into a tail test with
    weights rather than a plain average, and all three are arithmetic:

    * **the reconstruction noise in `u` is `phi(z) * eps`**, which at `z = 0` is
      `0.4 eps` and at `z = 4.5` is `1.6e-5 eps` - four decades smaller. So a
      high-`k` lattice survives only in the extreme tail, and a plain average
      over the tail *dilutes* it: nine thousand points each contributing
      nothing swamp fifty that carry the whole signal. Each point is therefore
      weighted by its own surviving amplitude `a_j = exp(-(w phi(z_j) eps)^2/2)`,
      which is the matched filter for this problem and turns the effective
      sample size into `sum a_j^2` - the number reported as `n_eff`;
    * **the scale of `z` is known only to `1/sqrt(2n)`**. A scale error is
      harmless in `z` space, where a lattice stays a lattice, and fatal in `u`
      space because `Phi` is non-linear. So the scale is scanned over the range
      its own standard error allows, and the scan's cost is paid honestly: the
      identical scan runs on the continuous controls and their maximum is the
      bar;
    * **a `k` whose `n_eff` is below 9 is untested, not passed.** Reporting an
      unreachable hypothesis as excluded is the failure this whole file is
      written against.
    """
    z = np.asarray(z, dtype=float)
    zt = z[np.abs(z) >= tail]
    if zt.size < 20:
        return {"n_tail": int(zt.size), "per_k": {}, "note": "tail too thin",
                "best_mag": float("nan"), "best_k": None, "best_eta": None}
    dens = np.exp(-0.5 * zt * zt) / math.sqrt(2 * math.pi)
    out: dict[int, dict] = {}
    best = (0.0, None, None)
    for k in ks:
        w = 2.0 * math.pi * (2.0**k)
        a = np.exp(-0.5 * np.minimum((w * dens * eps) ** 2, 1400.0))
        live = a > 1e-3
        n_eff = float((a * a).sum())
        # How many lattice cells the surviving points span. A sample confined
        # inside one cell returns |phi| = 1 for any data at all, which is an
        # artefact of the window and not an atom, and it is the single thing
        # most likely to be misread as a finding on this leg.
        if live.any():
            uu = ndtr(zt[live])
            cells = float((uu.max() - uu.min()) * (2.0**k))
        else:
            cells = 0.0
        reachable = bool(n_eff >= 9.0 and cells >= 20.0 and live.sum() >= 20)
        if not reachable:
            out[k] = {"max_mag": float("nan"), "n_eff": n_eff, "cells": cells,
                      "n_live": int(live.sum()), "reachable": False}
            continue
        al, zl = a[live], zt[live]
        denom = al.sum()
        # How finely the scale has to be scanned is set by `k` and by the live
        # points, not by taste: a scale shift `e` moves `u` by `z phi(z) e`, and
        # the lattice cell is `2**-k`, so anything finer than
        # `2**-(k+1) / max(z phi(z))` is scanning inside one cell. At k = 10
        # that is the whole range and three points do; at k = 20 it is a
        # hundredth of it. Fixing one resolution for every k spends almost all
        # of the run's time on the widths where it buys nothing.
        slope = float(np.max(np.abs(zl) * np.exp(-0.5 * zl * zl) / math.sqrt(2 * math.pi)))
        need = (2.0 ** -(k + 1)) / max(slope, 1e-12)
        n_e = int(min(max(math.ceil(2.0 * eta / need) + 1, 3), n_eta))
        es = np.linspace(-eta, eta, n_e)
        mags = np.empty(n_e)
        for i, e in enumerate(es):
            u = ndtr(zl * (1.0 + e))
            mags[i] = abs((al * np.exp(2j * math.pi * (2.0**k) * u)).sum()) / denom
        m = float(mags.max())
        out[k] = {"max_mag": m, "n_eff": n_eff, "cells": cells, "n_live": int(live.sum()),
                  "reachable": True, "n_eta": n_e, "eta": float(es[int(mags.argmax())])}
        if m > best[0]:
            best = (m, k, out[k]["eta"])
    return {"n_tail": int(zt.size), "tail": tail, "per_k": out,
            "best_mag": best[0], "best_k": best[1], "best_eta": best[2]}


# ------------------------------------------------- the accumulation question --
def accumulation(px: np.ndarray, t: np.ndarray, nominal: float, grid: float,
                 ks=(1, 2, 4, 8, 16, 32, 64)) -> dict:
    """Does the rounding residual random-walk into the path, or not?

    Two architectures, two predictions, and they are not close:

    * **display rounding** - the generator keeps a full-precision internal price
      and rounds only to publish. The published increment is
      `dY - (r_t - r_{t-1})` for a bounded residual `r`, so consecutive
      increments share a term with opposite signs: the lag-1 autocorrelation is
      about `-Var(r) / (Var(dY) + 2 Var(r))`, and the residual **cancels** on
      aggregation, so the variance of a `k`-tick move approaches `k Var(dY)`
      from below and the variance ratio falls toward `1 / (1 + 2 Var(r)/Var(dY))`;
    * **feedback rounding** - the rounded price *is* the state. There is no
      residual difference term, so the lag-1 autocorrelation is zero, and the
      rounding variance is added afresh every tick, so the variance ratio is
      **exactly 1 at every `k`**.

    Both are read here and neither is read alone: the ratio is the one that
    scales with the aggregation and is therefore hard to imitate, and the
    autocorrelation is the one with the tighter standard error.

    The whole thing has power only where the grid is coarse relative to the
    move. At `sigma_Y = 900` the predictions differ in the fifth decimal and
    this section is **untested** on that feed however many ticks it is given;
    at `sigma_Y = 0.7` they differ by a quarter. The feed decides, not the
    sample, which is why `sigma_Y` is printed beside every row.
    """
    ms = np.round(np.asarray(t) * 1000.0).astype(np.int64)
    slot = ms // int(round(nominal * 1000))
    lp = np.log(np.asarray(px, dtype=float))
    d = np.diff(lp)
    good = np.diff(slot) == 1
    d1 = d[good]
    v1 = float(d1.var())
    rho = float(np.corrcoef(d1[:-1], d1[1:])[0, 1]) if d1.size > 100 else float("nan")
    # Aggregate on the *slot* index so a missing tick does not shorten a window.
    out_vr = {}
    base = slot[:-1]
    for k in ks:
        if k == 1:
            out_vr[k] = 1.0
            continue
        blk = (base - base[0]) // k
        # Only blocks that are complete and gap-free contribute: a block with a
        # missing tick in it is a shorter window wearing a longer one's label,
        # and this statistic is entirely about how variance scales with length.
        sums = np.bincount(blk, weights=np.where(good, d, 0.0))
        cnt = np.bincount(blk, weights=good.astype(float))
        full = cnt == k
        if full.sum() < 50:
            out_vr[k] = float("nan")
            continue
        out_vr[k] = float(sums[full].var() / (k * v1))
    return {"n": int(d1.size), "var_1": v1, "rho1": rho,
            "rho1_se": float(1.0 / math.sqrt(max(d1.size, 1))),
            "vr": {int(k): float(v) for k, v in out_vr.items()}}


# ------------------------------------------------------- the drift question --
def drift_row(symbol: str, interval: str = "1d") -> dict | None:
    """One feed's contribution to the convention test: its endpoints and its sigma.

    **The sample size here is calendar span, not bar count**, and that is worth
    a paragraph because it contradicts the obvious reading of
    `projection.py`'s `RESOLVES_AT`. For iid Gaussian log returns the sum
    telescopes, so the maximum-likelihood estimate of `mu` over a window is
    `log(P_last / P_first) / T` **whatever the bar size** - a year of one-minute
    bars and a year of daily bars carry exactly the same information about the
    drift convention. What buys resolution is a longer calendar span or a larger
    sigma, and nothing else. Pooling twenty-two feeds works because they are
    independent draws, which `generated.md` established.

    Sigma is measured from the same bars rather than taken from the name. Under
    Gaussianity the sample mean and the sample variance are independent, so this
    does not contaminate the estimate it is used to weight, and it covers the
    two `Spot Up` members whose name claims no sigma at all.
    """
    try:
        bars = seqlab.load(symbol, interval)
    except Exception as exc:  # noqa: BLE001
        print(f"    {symbol} {interval}: {type(exc).__name__} {str(exc)[:60]}", flush=True)
        return None
    close = np.asarray(bars["close"], dtype=float)
    tm = np.asarray(bars["time"], dtype=float)
    if close.size < 200:
        return None
    r = np.diff(np.log(close))
    years = float((tm[-1] - tm[0]) / SIM.SECONDS_PER_YEAR)
    if years <= 0:
        return None
    per_year = close.size / years
    sigma = float(r.std() * math.sqrt(per_year))
    # A reset or a rescale would put a huge return in the series and corrupt the
    # endpoint estimate, which is the one statistic this section has. Screened
    # rather than trusted: report the worst return in sigma units.
    worst = float(np.max(np.abs(r)) / max(r.std(), 1e-12))
    return {
        "feed": symbol, "interval": interval, "bars": int(close.size), "years": years,
        "sigma": sigma, "named": named_sigma(symbol), "x": float(math.log(close[-1] / close[0])),
        "worst_z": worst, "first": float(close[0]), "last": float(close[-1]),
    }


def drift_pool(rows: list[dict]) -> dict:
    """The convention parameter `c` in `mu = -c sigma^2 / 2`, pooled.

    `c = 1` is the Ito convention - price a martingale, median drifting down.
    `c = 0` is the plain one - log price a martingale, price drifting up. The
    weighted least-squares estimate is `c = -2 sum(x_i) / sum(sigma_i^2 T_i)`
    with standard error `2 / sqrt(sum(sigma_i^2 T_i))`, so the separation
    between the two hypotheses is `sqrt(sum(sigma_i^2 T_i)) / 2` standard
    errors and that number is reported *first*. Below three it is unresolved and
    the estimate is printed as a number with an interval and not as a winner.
    """
    s = sum(r["sigma"] ** 2 * r["years"] for r in rows)
    x = sum(r["x"] for r in rows)
    if s <= 0:
        return {"n_feeds": len(rows), "separation": 0.0}
    c = -2.0 * x / s
    se = 2.0 / math.sqrt(s)
    return {
        "n_feeds": len(rows), "sum_sigma2_T": s, "sum_x": x,
        "c_hat": c, "se": se, "separation": math.sqrt(s) / 2.0,
        "z_vs_ito": (c - 1.0) / se, "z_vs_plain": (c - 0.0) / se,
        "resolved": bool(math.sqrt(s) / 2.0 >= 3.0),
        "total_years": sum(r["years"] for r in rows),
    }


def internal_sigma(sd_rel: float, grid: float, price: float, dt: float,
                   state: str = "continuous") -> float:
    """The annualised sigma a *control* must run at to match a measured feed.

    **Not the same number as the feed's realised sigma, and the difference is
    the whole of section 6.** What is observed is the log increment of the
    *published* quote, which carries the rounding residual as well as the draw:
    under display rounding the published variance is `sigma^2 + 2 Var(r)` in
    lattice units and under feedback it is `sigma^2 + Var(r)`, with
    `Var(r) = 1/12`. Handing a control the observed sigma therefore runs it at a
    larger internal sigma than the feed has, which *flattens* the very
    autocorrelation the control exists to predict - on a coarse feed by a fifth
    of it, which is enough to move a verdict. So the residual variance is taken
    off before the control is built, per architecture, and the control is
    matched to the feed on the observable rather than on a parameter.
    """
    if grid <= 0 or price <= 0:
        return sd_rel * math.sqrt(SIM.SECONDS_PER_YEAR / dt)
    cell = grid / price
    extra = (1.0 / 6.0 if state == "continuous" else 1.0 / 12.0) * cell * cell
    inner = max(sd_rel * sd_rel - extra, (0.05 * sd_rel) ** 2)
    return math.sqrt(inner) * math.sqrt(SIM.SECONDS_PER_YEAR / dt)


# ------------------------------------------------------------- the battery ---
def battery(px: np.ndarray, t: np.ndarray, nominal: float, grid: float) -> dict:
    """All three atom legs on one price series, real or simulated, one code path.

    One function for both because a test that takes real data one way and
    simulated data another is graded on a different object from the one it is
    used on, and the recovery rate it then reports is about the plumbing.
    """
    got = implied_z(px, t, nominal, grid)
    z, eps, sl = got["z"], got["eps"], got["sigma_lat"]
    if z.size < 1000:
        return {"n": int(z.size), "thin": True}
    # The band runs to where reconstruction noise leaves nothing to find, and
    # the quote lattice's own frequency and first harmonic are cut out of it -
    # see `ecf_scan`. Cutting rather than stopping short is what lets the scan
    # reach a z-lattice *finer* than the quote grid, which is most of the range
    # worth looking at.
    w_hi = 3.0 / max(eps, 1e-12)
    q = 2.0 * math.pi * sl
    scan = ecf_scan(z, w_hi=w_hi, exclude=((0.93 * q, 1.07 * q), (1.86 * q, 2.14 * q)))
    peak = lattice_peak(scan, sl)
    ub = u_bits(z, eps)
    scan.pop("_w", None)
    scan.pop("_mag", None)
    return {
        "n": got["n"], "kept_frac": got["kept_frac"], "sd_rel": got["sd_rel"],
        "price": got["price"], "sigma_lat": sl, "eps": eps, "bits": got["bits"],
        "cap": cap_test(z, eps), "ecf": scan, "quote_lattice_peak": peak,
        "u": {"n_tail": ub["n_tail"], "best_mag": ub["best_mag"], "best_k": ub["best_k"],
              "reachable_k": [k for k, v in ub["per_k"].items() if v["reachable"]],
              "mag_k": {int(k): float(v["max_mag"]) for k, v in ub["per_k"].items()},
              "per_k": {str(k): {"max_mag": round(float(v["max_mag"]), 5),
                                 "n_eff": round(v["n_eff"], 2), "cells": round(v["cells"], 1),
                                 "reachable": v["reachable"]} for k, v in ub["per_k"].items()}},
    }


def control_bank(spec: dict, n: int, reps: int, *, seed: int, **over) -> list[dict]:
    """`reps` runs of the battery on a simulator matched to a measured feed."""
    out = []
    for r in range(reps):
        sim = SIM.ticks(
            n, price=spec["price"], sigma=spec["sigma"], dt=spec["dt"], grid=spec["grid"],
            jitter_ms=spec.get("jitter_ms", 0.0), drop=spec.get("drop", 0.0),
            seed=seed + 1009 * r, **over,
        )
        out.append(battery(sim["bid"], sim["time"], spec["dt"], spec["grid"]))
    return out


def legs(b: dict) -> dict:
    """The three legs the atom verdict is made of, pulled out of a battery run."""
    return {
        "ecf": b["ecf"]["max"],
        "cap_ratio": b["cap"]["ratio"],
        "u_k": b["u"]["mag_k"],
    }


def calibrate(control: list[dict], ks) -> dict:
    """Per-bit-width mean and spread of the `u` leg, from the calibration half.

    The null is **not the same at every `k`** and that is the whole reason this
    exists. At a low bit width every tail point falls inside one lattice cell
    and the magnitude is large from any data whatever; at a high one the
    matched filter keeps fifty points out of forty thousand and the magnitude is
    large from noise. A single bar across all `k` would be set by whichever end
    is loudest and the leg would be blind everywhere else.

    Standardising per `k` fixes that, and then the *maximum over `k`* is one
    scalar whose null can be calibrated honestly - which is the second half of
    the fix. The first version of this page used the control maximum per `k` as
    nineteen separate bars and reported a false-positive rate of zero, which was
    true in sample and meaningless: a fresh draw clears a nineteen-fold maximum
    about two runs in five. The control set is therefore **split**, half to set
    the bar and half to measure how often a generator known to be sound clears
    it, and that second number is the one quoted.
    """
    out = {}
    for k in ks:
        vals = [c["u_k"].get(k, float("nan")) for c in control]
        vals = [v for v in vals if math.isfinite(v)]
        if len(vals) < 4:
            continue
        out[int(k)] = {"mean": float(np.mean(vals)), "sd": float(np.std(vals, ddof=1)),
                       "n": len(vals), "max": float(max(vals))}
    return out


def u_stat(run: dict, cal: dict) -> tuple[float, int | None, dict[int, float]]:
    """The `u` leg as one number: the largest standardised magnitude over `k`.

    Returns the statistic, the bit width it came from, and the whole profile -
    the profile is what says *which* width, and a lattice at `2**-k` is also a
    lattice at every finer width, so the **smallest** firing `k` is the estimate
    and the run of widths above it is the confirmation.
    """
    z = {}
    for k, c in cal.items():
        v = run["u_k"].get(k, float("nan"))
        if math.isfinite(v) and c["sd"] > 0:
            z[int(k)] = (v - c["mean"]) / c["sd"]
    if not z:
        return float("nan"), None, {}
    kbest = max(z, key=lambda k: z[k])
    return z[kbest], kbest, z


# ------------------------------------------------- the rounding-mode theorem --
def rounding_identifiability(spec: dict, n: int, seed: int, reps: int = 8) -> dict:
    """Whether the published quotes can tell the five rounding rules apart.

    They cannot, and the reason is one line of algebra rather than a sample-size
    problem. Four of the five rules are `Q(x) = grid * floor(x/grid + c)` for a
    constant `c` - floor is `c = 0`, round-half-up is `c = 1/2`, truncate is
    floor on a positive price, ceil is the limit `c -> 1`. Changing `c` shifts
    the lattice's *phase* relative to the internal price, and when the internal
    price is continuous it is uniform modulo the grid, so the phase is uniform
    and **the joint law of the published increments does not depend on `c` at
    all**. Round-half-even is not of that form but differs from round-half-up
    only on exact ties, which a continuous internal price hits with probability
    zero.

    So the rounding mode is identifiable only where the internal price is *not*
    uniform modulo the grid - which is exactly the feedback architecture of
    section 6, where floor and ceil put a `+-grid/2` drift into every tick and
    are excluded on sight. This function is the measurement that goes with the
    theorem: five modes, one seed, and the spread across them against the
    spread across seeds. **A mode-spread smaller than the seed-spread is the
    result**, and it is a negative result of the second kind - not "we found
    nothing" but "nothing could have been found".
    """
    keys = ("mean", "sd", "rho1", "frac_zero", "p_even_last")

    def stat(sim) -> dict:
        d = np.diff(sim["bid"]) / spec["grid"]
        units = np.round(sim["bid"] / spec["grid"]).astype(np.int64)
        return {"mean": float(d.mean()), "sd": float(d.std()),
                "rho1": float(np.corrcoef(d[:-1], d[1:])[0, 1]),
                "frac_zero": float((d == 0).mean()),
                "p_even_last": float((units % 2 == 0).mean())}

    #: Paired on the seed, which is what makes this decisive rather than
    #: suggestive: every mode sees the *same* continuous path and differs only
    #: in how that path is put on the lattice, so the difference between two
    #: modes is measured without the path's own variance in the way. An
    #: unpaired comparison needs a hundred times the sample to say the same
    #: thing, and on one statistic here - the parity of the last digit, which
    #: is a phase statistic and wanders - it says the wrong thing at this one.
    seeds = [seed + 7919 * (i + 1) for i in range(reps)]
    per: dict[str, list[dict]] = {m: [] for m in SIM.MODES}
    for sd in seeds:
        for mode in SIM.MODES:
            per[mode].append(stat(SIM.ticks(
                n, price=spec["price"], sigma=spec["sigma"], dt=spec["dt"],
                grid=spec["grid"], mode=mode, seed=sd)))
    ref = "half_even"
    out: dict[str, dict] = {}
    for mode in SIM.MODES:
        if mode == ref:
            continue
        row = {}
        for k in keys:
            diff = np.array([per[mode][i][k] - per[ref][i][k] for i in range(reps)])
            se = float(diff.std(ddof=1) / math.sqrt(reps)) if reps > 1 else float("nan")
            # `half_up` and `half_even` differ only on exact ties, which a
            # continuous internal price never produces, so every paired
            # difference is *bit-identical zero* rather than small. Reported as
            # a zero z rather than as a nan from a zero standard error: the
            # distinction between "identical" and "could not be computed" is
            # exactly what this section is about.
            z = 0.0 if float(np.abs(diff).max()) == 0.0 else (
                float(diff.mean() / se) if se > 0 else float("nan"))
            row[k] = {"mean_diff": float(diff.mean()), "se": se, "z": z,
                      "bit_identical": bool(float(np.abs(diff).max()) == 0.0)}
        out[mode] = row
    means = {m: {k: float(np.mean([r[k] for r in per[m]])) for k in keys} for m in SIM.MODES}
    worst = {k: float(max(abs(out[m][k]["z"]) for m in out if math.isfinite(out[m][k]["z"])))
             if any(math.isfinite(out[m][k]["z"]) for m in out) else float("nan") for k in keys}
    return {"n": n, "reps": reps, "means": means, "paired_vs_half_even": out,
            "worst_abs_z": worst,
            "identifiable": {k: bool(math.isfinite(worst[k]) and worst[k] > 4.0) for k in keys}}


# ----------------------------------------------------------------- the main --
def _fmt(x: float, w: int = 10, p: int = 4) -> str:
    return f"{x:{w}.{p}g}" if isinstance(x, float) and math.isfinite(x) else f"{'-':>{w}}"


def save(report: dict) -> None:
    """Dump what has been measured so far, after every section.

    Not tidiness. The deep tick pulls are half an hour of a shared terminal and
    the whole run is an hour; a drop in section five that loses sections one
    through four costs the pulls again. `rebuildpredict.py` writes once at the
    end and has been re-run for that reason.
    """
    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(report, fh, indent=1, default=float)


def main() -> None:
    began = time.time()
    report: dict = {"seed": SEED, "want": WANT, "reps": REPS}
    rng_note = f"reps={REPS} want={WANT:,}"
    print(f"pipeline: identifying the middle of Deriv's chain  ({rng_note})\n", flush=True)

    # ---------------------------------------------------------- section 1 ----
    print("=" * 108)
    print("1. THE QUOTE LATTICE, PER FEED - grid, sigma_Y, and the bits one tick carries")
    print("=" * 108, flush=True)
    print(f"{'feed':30s} {'n':>9s} {'dec':>4s} {'grid':>10s} {'price':>11s} "
          f"{'sd_rel':>10s} {'sigma_Y':>9s} {'bits':>6s} {'spread/g':>9s} {'fzero':>7s}")
    lattice: dict[str, dict] = {}
    ticks_by_feed: dict[str, dict] = {}
    for sym in FAMILY + OTHERS:
        if sym in OTHERS and sym == OTHERS[0]:
            print(f"{'-' * 40} the other families {'-' * 40}", flush=True)
        try:
            d = pull(sym, WANT_SMALL if sym in FAMILY else WANT_SMALL // 2)
        except Exception as exc:  # noqa: BLE001
            print(f"{sym:30s} pull failed: {type(exc).__name__} {str(exc)[:50]}", flush=True)
            continue
        if d["bid"].size < 5000:
            print(f"{sym:30s} thin: {d['bid'].size} ticks", flush=True)
            continue
        grid, dec = grid_of(d["bid"])
        if not grid or dec is None:
            print(f"{sym:30s} no lattice found (decimals={dec}, grid={grid}) - skipped", flush=True)
            continue
        ticks_by_feed[sym] = d
        nominal = nominal_dt(sym)
        got = implied_z(d["bid"], d["time"], nominal, grid)
        sp = d["ask"] - d["bid"]
        dm = np.diff(d["bid"])
        lattice[sym] = {
            "n": int(d["bid"].size), "decimals": dec, "grid": grid, "price": got["price"],
            "sd_rel": got["sd_rel"], "sigma_lat": got["sigma_lat"], "bits": got["bits"],
            "eps": got["eps"], "kept_frac": got["kept_frac"],
            "spread_med": float(np.median(sp)), "spread_sd": float(sp.std()),
            "spread_units": float(np.median(sp) / grid) if grid else float("nan"),
            "frac_zero": float((dm == 0).mean()),
            "named_sigma": named_sigma(sym), "nominal_dt": nominal,
            "diffusion": sym in FAMILY,
            "grid_ask": grid_of(d["ask"])[0],
            "hours": float((d["time"][-1] - d["time"][0]) / 3600.0),
        }
        L = lattice[sym]
        print(f"{sym:30s} {L['n']:>9,} {str(dec):>4s} {_fmt(grid, 10, 4)} "
              f"{_fmt(L['price'], 11, 6)} {_fmt(L['sd_rel'], 10, 4)} {_fmt(L['sigma_lat'], 9, 4)} "
              f"{_fmt(L['bits'], 6, 3)} {_fmt(L['spread_units'], 9, 4)} "
              f"{_fmt(L['frac_zero'], 7, 3)}", flush=True)
    report["lattice"] = lattice
    save(report)
    print(f"\n  bits per tick is log2(sigma_Y sqrt(2 pi e)) - the information a single quote\n"
          f"  carries about the draw behind it. MT19937 untempering needs whole 32-bit words.",
          flush=True)

    # ---------------------------------------------------------- section 2 ----
    print("\n" + "=" * 108)
    print("2. THE CLOCK - is dt exactly constant, and is the jitter shared?")
    print("=" * 108, flush=True)
    print(f"{'feed':30s} {'nom':>5s} {'gap_mean':>9s} {'mode':>6s} {'off_mean':>9s} "
          f"{'off_sd':>7s} {'empty%':>7s} {'double':>7s} {'slot_per':>9s}")
    clocks: dict[str, dict] = {}
    for sym, d in ticks_by_feed.items():
        c = clock(d["time"], nominal_dt(sym))
        clocks[sym] = c
        print(f"{sym:30s} {nominal_dt(sym):5.0f} {c['gap_mean_ms']:9.3f} {c['gap_mode_ms']:6d} "
              f"{c['offset_mean_ms']:9.2f} {c['offset_sd_ms']:7.2f} "
              f"{100 * c['empty_frac']:7.4f} {c['slots_doubled']:7d} "
              f"{c['period_from_slots_ms']:9.4f}", flush=True)
    report["clock"] = clocks

    print("\n  does the increment know about the jitter, or only about the slot?")
    print(f"  {'feed':28s} {'n':>9s} {'slope':>9s} {'se':>8s} {'z':>8s}   1.0 = wall clock, 0.0 = slot counter")
    vg: dict[str, dict] = {}
    for sym, d in ticks_by_feed.items():
        grid = lattice[sym]["grid"]
        nominal = nominal_dt(sym)
        ms = np.round(d["time"] * 1000.0).astype(np.int64)
        lp = np.log(d["bid"])
        x, g = np.diff(lp), np.diff(ms).astype(float)
        r = variance_vs_gap(x, g, nominal)
        vg[sym] = r
        print(f"  {sym:28s} {r['n']:>9,} {_fmt(r['slope'], 9, 3)} {_fmt(r['se'], 8, 3)} "
              f"{_fmt(r['z'], 8, 3)}", flush=True)
    report["variance_vs_gap"] = vg
    print("\n  recovery: the same regression on simulators whose clock is known")
    vgc = {}
    for wall in (False, True):
        got = []
        for r in range(REPS_POS):
            s = SIM.ticks(WANT_SMALL, price=1000.0, sigma=0.75, dt=2.0, grid=0.0,
                          jitter_ms=46.0, wall_clock=wall, seed=SEED + 211 * r)
            ms = np.round(s["time"] * 1000.0).astype(np.int64)
            got.append(variance_vs_gap(np.diff(np.log(s["bid"])), np.diff(ms).astype(float), 2.0)
                       ["slope"])
        vgc["wall" if wall else "slot"] = {"mean": float(np.mean(got)), "sd": float(np.std(got))}
        print(f"    truth={'wall clock' if wall else 'slot counter':13s} "
              f"slope {np.mean(got):+.3f} +- {np.std(got):.3f} "
              f"(the truth is {1.0 if wall else 0.0:.1f})", flush=True)
    report["variance_vs_gap_control"] = vgc

    print("\n  is the publication jitter shared across feeds?")
    pairs = [("Volatility 75 Index", "Volatility 100 Index"),
             ("Volatility 75 Index", "Volatility 10 Index"),
             ("Volatility 75 Index", "Volatility 250 (1s) Index"),
             ("Volatility 100 (1s) Index", "Volatility 250 (1s) Index")]
    sj = {}
    for a, b in pairs:
        if a in ticks_by_feed and b in ticks_by_feed:
            r = shared_jitter(ticks_by_feed[a], ticks_by_feed[b], nominal_dt(a), nominal_dt(b))
            sj[f"{a} | {b}"] = r
            print(f"  {a:28s} vs {b:28s} n={r['n']:>8,} corr={_fmt(r.get('corr', float('nan')), 7, 3)} "
                  f"median|dt|={_fmt(r.get('median_abs_ms', float('nan')), 6, 3)}ms", flush=True)
    report["shared_jitter"] = sj
    save(report)
    print(f"\n  elapsed {time.time() - began:.0f}s", flush=True)

    # ---------------------------------------------------------- section 3 ----
    print("\n" + "=" * 108)
    print("3. THE ATOM BATTERY - is the increment distribution continuous, or a finite set?")
    print("=" * 108, flush=True)
    ranked = sorted(((k, v) for k, v in lattice.items() if v["diffusion"]),
                    key=lambda kv: -kv[1]["sigma_lat"])
    atom_feeds = [k for k, _ in ranked[:N_ATOM]]
    print(f"  the battery's resolution is eps = 1/(sqrt(6) sigma_Y), so the feeds are chosen")
    print(f"  by sigma_Y and not by hand. Deepest two: {', '.join(atom_feeds)}")
    print(f"  (best eps = {ranked[0][1]['eps']:.3g} z-units; nothing finer is visible from quotes"
          f" at any n)", flush=True)

    atoms: dict[str, dict] = {}
    for sym in atom_feeds:
        nominal, grid = nominal_dt(sym), lattice[sym]["grid"]
        print(f"\n  --- {sym} ---", flush=True)
        d = pull(sym, WANT)
        if d["bid"].size < 20_000:
            # A dropped chunk on a flaky terminal comes back as a short array
            # rather than as an error. Sections 4, 5 and 6 do not depend on this
            # one, so a thin pull costs this feed and not the run.
            print(f"  thin pull: {d['bid'].size:,} ticks - skipped", flush=True)
            continue
        ticks_by_feed[sym] = d
        real = battery(d["bid"], d["time"], nominal, grid)
        if real.get("thin"):
            print(f"  battery has {real['n']} usable pairs - skipped", flush=True)
            continue
        spec = {"price": real["price"], "grid": grid, "dt": nominal,
                "sigma": internal_sigma(real["sd_rel"], grid, real["price"], nominal),
                "drop": clocks.get(sym, {}).get("empty_frac", 0.0),
                "jitter_ms": clocks.get(sym, {}).get("offset_sd_ms", 0.0)}
        n = real["n"] + 2
        print(f"  n={real['n']:,} kept={100 * real['kept_frac']:.2f}%  sigma_Y={real['sigma_lat']:.4g}"
              f"  eps={real['eps']:.3g}  bits/tick={real['bits']:.3f}", flush=True)

        print(f"  running {REPS} continuous controls at the same price, grid, sigma and n;")
        print(f"  half of them SET the bar and half MEASURE how often a sound generator "
              f"clears it...", flush=True)
        neg = control_bank(spec, n, REPS, seed=SEED, inverse="continuous")
        half = REPS // 2
        calib_runs, valid_runs = neg[:half], neg[half:]
        cl = [legs(b) for b in calib_runs]
        vl = [legs(b) for b in valid_runs]
        ks = sorted(real["u"]["mag_k"].keys())
        cal = calibrate(cl, ks)
        bar = {"ecf": max(v["ecf"] for v in cl),
               "cap_lo": min(v["cap_ratio"] for v in cl),
               "u_T": max(u_stat(v, cal)[0] for v in cl)}
        rl = legs(real)
        rT, rk, rz = u_stat(rl, cal)
        fired = {"ecf": bool(rl["ecf"] > bar["ecf"]),
                 "u": bool(math.isfinite(rT) and rT > bar["u_T"]),
                 "cap": bool(rl["cap_ratio"] < bar["cap_lo"])}
        fp = {"ecf": sum(v["ecf"] > bar["ecf"] for v in vl),
              "u": sum(u_stat(v, cal)[0] > bar["u_T"] for v in vl),
              "cap": sum(v["cap_ratio"] < bar["cap_lo"] for v in vl)}
        fp["any"] = sum((v["ecf"] > bar["ecf"]) or (u_stat(v, cal)[0] > bar["u_T"])
                        or (v["cap_ratio"] < bar["cap_lo"]) for v in vl)
        print(f"  {'leg':24s} {'real':>10s} {'bar':>10s} {'calib mean':>11s} {'fires?':>7s} "
              f"{'false pos':>10s}")
        print(f"  {'ecf lattice scan':24s} {rl['ecf']:10.5f} {bar['ecf']:10.5f} "
              f"{np.mean([v['ecf'] for v in cl]):11.5f} {str(fired['ecf']):>7s} "
              f"{fp['ecf']:>6d}/{len(vl):<3d}")
        print(f"  {'max|z| / expected':24s} {rl['cap_ratio']:10.5f} {bar['cap_lo']:10.5f} "
              f"{np.mean([v['cap_ratio'] for v in cl]):11.5f} {str(fired['cap']):>7s} "
              f"{fp['cap']:>6d}/{len(vl):<3d}   (fires BELOW the bar)")
        print(f"  {'u-space max over k':24s} {rT:10.5f} {bar['u_T']:10.5f} "
              f"{np.mean([u_stat(v, cal)[0] for v in cl]):11.5f} {str(fired['u']):>7s} "
              f"{fp['u']:>6d}/{len(vl):<3d}   (at k = {rk})")
        print(f"  {'ANY leg':24s} {'':>10s} {'':>10s} {'':>11s} "
              f"{str(any(fired.values())):>7s} {fp['any']:>6d}/{len(vl):<3d}", flush=True)
        print(f"  quote-lattice peak at w = 2 pi sigma_Y (excluded from the scan band): "
              f"real {real['quote_lattice_peak']:.5f}, control mean "
              f"{np.mean([b['quote_lattice_peak'] for b in calib_runs]):.5f}", flush=True)
        print(f"  ecf band w in [{real['ecf']['w_lo']:.0f}, {real['ecf']['w_hi']:.0f}] - "
              f"z-lattice spacings from {2 * math.pi / real['ecf']['w_hi']:.2e} to "
              f"{2 * math.pi / real['ecf']['w_lo']:.3f}, minus the quote-lattice windows; "
              f"peak at spacing {real['ecf'].get('spacing', float('nan')):.3e}", flush=True)
        print(f"  max|z| = {real['cap']['max_abs_z']:.4f} against {real['cap']['expected_max']:.4f} "
              f"expected from continuity at n={real['n']:,}; a k-bit uniform is excluded up to "
              f"k = {real['cap']['bits_excluded_upto']} (arithmetic ceiling "
              f"log2(2n) = {real['cap']['reach']:.1f})", flush=True)
        print(f"\n  u leg, per bit width, in calibration standard deviations. A lattice at 2^-k")
        print(f"  is also a lattice at every finer width, so the SMALLEST firing k is the answer")
        print(f"  and the run above it is the confirmation. A k with no calibration is UNTESTED.")
        print(f"    {'k':>4s} {'real mag':>9s} {'calib mean':>11s} {'calib sd':>9s} {'z':>8s} "
              f"{'n_eff':>9s} {'cells':>9s}")
        for k in ks:
            info = real["u"]["per_k"][str(k)]
            c = cal.get(int(k))
            v = rl["u_k"].get(k, float("nan"))
            print(f"    {k:>4d} {_fmt(v, 9, 4)} "
                  f"{_fmt(c['mean'] if c else float('nan'), 11, 4)} "
                  f"{_fmt(c['sd'] if c else float('nan'), 9, 3)} "
                  f"{_fmt(rz.get(int(k), float('nan')), 8, 3)} "
                  f"{info['n_eff']:>9.2f} {info['cells']:>9.1f}", flush=True)

        ident_real = sorted(k for k, v in rl["u_k"].items() if math.isfinite(v) and v > 0.3)
        print(f"\n  smallest bit width whose raw magnitude exceeds 0.3 on the real feed: "
              f"{ident_real[0] if ident_real else 'none'}   (the identification, as against "
              f"the detection above)", flush=True)
        print(f"\n  recovery: the same battery on generators whose inverse-normal IS coarse "
              f"({REPS_POS} reps each)", flush=True)
        print(f"  {'truth':26s} {'ecf':>9s} {'>bar':>6s} {'u_T':>9s} {'>bar':>6s} "
              f"{'cap':>8s} {'<bar':>6s} {'caught':>7s} {'fires@k':>5s} {'is@k':>5s}")
        recovery = {}
        cases = [("table 2^8", dict(inverse="table", entries=1 << 8)),
                 ("table 2^10", dict(inverse="table", entries=1 << 10)),
                 ("table 2^12", dict(inverse="table", entries=1 << 12)),
                 ("table 2^14", dict(inverse="table", entries=1 << 14)),
                 ("table 2^16", dict(inverse="table", entries=1 << 16)),
                 ("table 2^20", dict(inverse="table", entries=1 << 20)),
                 ("table 2^12 interp", dict(inverse="table_interp", entries=1 << 12)),
                 ("bits 12", dict(inverse="bits", bits=12)),
                 ("bits 16", dict(inverse="bits", bits=16)),
                 ("bits 20", dict(inverse="bits", bits=20)),
                 ("bits 22", dict(inverse="bits", bits=22)),
                 ("bits 24", dict(inverse="bits", bits=24)),
                 ("bits 32", dict(inverse="bits", bits=32)),
                 ("bits 53 (float64)", dict(inverse="bits", bits=52)),
                 ("z stored to 0.01", dict(inverse="z_round", zstep=1e-2)),
                 ("z stored to 0.002", dict(inverse="z_round", zstep=2e-3)),
                 ("z stored to 0.001", dict(inverse="z_round", zstep=1e-3))]
        for name, over in cases:
            pos = control_bank(spec, n, REPS_POS, seed=SEED + 31, **over)
            pl = [legs(b) for b in pos]
            ts = [u_stat(v, cal) for v in pl]
            hit_e = sum(v["ecf"] > bar["ecf"] for v in pl)
            hit_u = sum(t[0] > bar["u_T"] for t in ts)
            hit_c = sum(v["cap_ratio"] < bar["cap_lo"] for v in pl)
            caught = sum((pl[i]["ecf"] > bar["ecf"]) or (ts[i][0] > bar["u_T"])
                         or (pl[i]["cap_ratio"] < bar["cap_lo"]) for i in range(len(pl)))
            # Two different questions and two different columns. "Fires" is a
            # detection and the standardised z answers it. "Which bit width" is
            # an identification, and the z does NOT answer it: for a lattice at
            # `2**-k0` the magnitude at a *coarser* k is a sum over roots of
            # unity whose fluctuation statistics differ from the continuous
            # case, so a low k can clear the bar without the lattice being
            # there. The raw magnitude does answer it - it goes to near one at
            # `k0` and stays there - so identification reads the magnitude.
            smallest, ident = [], []
            for i, (_, _, z) in enumerate(ts):
                fk = sorted(k for k, v in z.items() if v > bar["u_T"])
                if fk:
                    smallest.append(fk[0])
                ik = sorted(k for k, v in pl[i]["u_k"].items()
                            if math.isfinite(v) and v > 0.3)
                if ik:
                    ident.append(int(ik[0]))
            recovery[name] = {"ecf": hit_e, "u": hit_u, "cap": hit_c, "caught": caught,
                              "reps": REPS_POS, "smallest_k": smallest, "identified_k": ident,
                              "ecf_mean": float(np.mean([v["ecf"] for v in pl])),
                              "u_T_mean": float(np.mean([t[0] for t in ts])),
                              "cap_mean": float(np.mean([v["cap_ratio"] for v in pl]))}
            print(f"  {name:26s} {recovery[name]['ecf_mean']:9.5f} {hit_e:>3d}/{REPS_POS:<2d} "
                  f"{recovery[name]['u_T_mean']:9.3f} {hit_u:>3d}/{REPS_POS:<2d} "
                  f"{recovery[name]['cap_mean']:8.4f} {hit_c:>3d}/{REPS_POS:<2d} "
                  f"{caught:>3d}/{REPS_POS:<2d}  "
                  f"{min(smallest) if smallest else '-':>4} "
                  f"{min(ident) if ident else '-':>5}", flush=True)

        atoms[sym] = {"real": real, "bar": bar, "fired": fired, "false_positive": fp,
                      "u_T": rT, "u_T_at_k": rk, "u_z": {str(k): v for k, v in rz.items()},
                      "calibration": {str(k): v for k, v in cal.items()},
                      "recovery": recovery, "n_calib": len(cl), "n_valid": len(vl),
                      "identified_k": ident_real,
                      "control_mean": {k: float(np.mean([v[k] for v in cl]))
                                       for k in ("ecf", "cap_ratio")},
                      "spec": spec}
        report["atoms"] = atoms
        save(report)
    report["atoms"] = atoms

    # ---------------------------------------------------------- section 4 ----
    print("\n" + "=" * 108)
    print("4. THE DRIFT CONVENTION - exp(-sigma^2/2 dt + sigma dW) or exp(sigma dW)?")
    print("=" * 108, flush=True)
    print("  the sample size here is CALENDAR SPAN, not bar count: for iid Gaussian log")
    print("  returns the sum telescopes, so a year of 1m bars and a year of 1d bars carry")
    print("  exactly the same information about mu. Separation = sqrt(sum sigma_i^2 T_i)/2.")
    print(f"\n  {'feed':30s} {'tf':>3s} {'bars':>7s} {'years':>7s} {'sigma':>8s} {'named':>7s} "
          f"{'first':>11s} {'last':>11s} {'log P1/P0':>10s} {'worst z':>8s} {'sigma^2 T':>10s}")
    rows = []
    for sym in FAMILY:
        # 1d first because 50,000 daily bars is 137 years and therefore returns
        # whatever history exists; 1h caps at 5.7 years and is the fallback only.
        r = drift_row(sym, "1d") or drift_row(sym, "1h")
        if r is None:
            continue
        rows.append(r)
        print(f"  {sym:30s} {r['interval']:>3s} {r['bars']:>7,} {r['years']:>7.2f} "
              f"{r['sigma']:>8.4f} "
              f"{'-' if r['named'] is None else format(r['named'], '.2f'):>7s} "
              f"{r['first']:>11.5g} {r['last']:>11.5g} "
              f"{r['x']:>10.4f} {r['worst_z']:>8.2f} {r['sigma'] ** 2 * r['years']:>10.4f}",
              flush=True)
    pooled = drift_pool(rows)
    report["drift"] = {"rows": rows, "pooled": pooled}
    save(report)
    if rows:
        print(f"\n  pooled over {pooled['n_feeds']} feeds, {pooled['total_years']:.1f} feed-years:")
        print(f"    sum sigma^2 T          = {pooled['sum_sigma2_T']:.4f}")
        print(f"    separation between the conventions = {pooled['separation']:.2f} standard errors")
        print(f"    c_hat (1 = Ito, 0 = plain)         = {pooled['c_hat']:+.3f} "
              f"+- {pooled['se']:.3f}")
        print(f"    z vs Ito   = {pooled['z_vs_ito']:+.2f}")
        print(f"    z vs plain = {pooled['z_vs_plain']:+.2f}")
        print(f"    resolved at the pre-registered 3-sigma bar: {pooled['resolved']}", flush=True)
        need = (3.0 * 2.0) ** 2
        have = pooled["sum_sigma2_T"]
        print(f"    to resolve it needs sum sigma^2 T >= {need:.1f}; this sample has {have:.1f}, "
              f"a factor of {need / max(have, 1e-9):.2f}", flush=True)

    print(f"\n  recovery: the same estimator on simulated feeds whose convention is known")
    for truth in SIM.CONVENTIONS:
        hits = 0
        cs = []
        for r in range(REPS_POS * 2):
            sim_rows = []
            for fi, row in enumerate(rows):
                nb = max(int(row["years"] * 365), 50)
                s = SIM.ticks(nb, price=1000.0, sigma=row["sigma"],
                              dt=SIM.SECONDS_PER_YEAR / 365.0, grid=0.0,
                              convention=truth, seed=SEED + 9973 * r + 101 * fi)
                lp = np.log(s["mid"])
                sim_rows.append({"sigma": row["sigma"], "years": row["years"],
                                 "x": float(lp[-1] - lp[0])})
            p = drift_pool(sim_rows)
            cs.append(p["c_hat"])
            want_c = 1.0 if truth == "ito" else 0.0
            hits += abs(p["c_hat"] - want_c) < abs(p["c_hat"] - (1.0 - want_c))
        print(f"    truth={truth:6s}  c_hat mean {np.mean(cs):+.3f} sd {np.std(cs):.3f}  "
              f"picked correctly {hits}/{REPS_POS * 2}", flush=True)
    print(f"\n  elapsed {time.time() - began:.0f}s", flush=True)

    # ---------------------------------------------------------- section 5 ----
    print("\n" + "=" * 108)
    print("5. THE QUANTISER - the grid is measured, the rounding mode is a phase")
    print("=" * 108, flush=True)
    print("  Four of the five rules are Q(x) = grid * floor(x/grid + c): floor is c=0,")
    print("  round-half-up is c=1/2, truncate is floor on a positive price, ceil is c->1.")
    print("  c shifts the lattice's PHASE against the internal price. When the internal price")
    print("  is continuous it is uniform modulo the grid, so the phase is uniform and the law")
    print("  of the published increments does not depend on c at all. Round-half-even differs")
    print("  from round-half-up only on exact ties, which a continuous price hits with")
    print("  probability zero. The measurement below is the theorem's receipt.\n", flush=True)
    ident_feed = ranked[0][0] if ranked else FAMILY[0]
    ispec = {"price": lattice[ident_feed]["price"], "grid": lattice[ident_feed]["grid"],
             "dt": nominal_dt(ident_feed),
             "sigma": internal_sigma(lattice[ident_feed]["sd_rel"], lattice[ident_feed]["grid"],
                                     lattice[ident_feed]["price"], nominal_dt(ident_feed))}
    ident = rounding_identifiability(ispec, min(WANT_SMALL, 400_000), SEED)
    report["rounding"] = {"feed": ident_feed, "spec": ispec, "identifiability": ident}
    print(f"  simulator at {ident_feed}'s price, grid and sigma, n={ident['n']:,} x "
          f"{ident['reps']} paired seeds:")
    print(f"  {'mode':12s} {'mean(d)/g':>12s} {'sd(d)/g':>10s} {'rho1':>11s} {'frac_zero':>11s} "
          f"{'p(even)':>9s}")
    for mode, st in ident["means"].items():
        print(f"  {mode:12s} {st['mean']:>12.6f} {st['sd']:>10.5f} {st['rho1']:>11.6f} "
              f"{st['frac_zero']:>11.6f} {st['p_even_last']:>9.5f}")
    print(f"\n  paired difference from round-half-even, in standard errors of the pair:")
    print(f"  {'mode':12s} " + " ".join(f"{k:>13s}" for k in
                                        ("mean", "sd", "rho1", "frac_zero", "p_even_last")))
    for mode, row in ident["paired_vs_half_even"].items():
        print(f"  {mode:12s} " + " ".join(f"{row[k]['z']:>+13.2f}" for k in
                                          ("mean", "sd", "rho1", "frac_zero", "p_even_last")))
    print(f"  {'identifiable':12s} " + " ".join(f"{str(ident['identifiable'][k]):>13s}" for k in
                                                ("mean", "sd", "rho1", "frac_zero", "p_even_last")))
    print("\n  a paired difference consistent with zero is the result: the published quotes do not")
    print("  contain the rounding mode. What IS measured is the grid, per feed, in section 1,")
    print("  and the bid/ask geometry below.\n", flush=True)
    print(f"  {'feed':30s} {'grid(bid)':>11s} {'grid(ask)':>11s} {'spread/grid':>12s} "
          f"{'sd(spread)':>11s} {'mid on half-grid':>17s}")
    ba = {}
    for sym, d in ticks_by_feed.items():
        g = lattice[sym]["grid"]
        halves = float(np.mean(np.abs(np.round(d["mid"] / (g / 2.0)) * (g / 2.0) - d["mid"]) < 1e-9))
        ba[sym] = {"grid_bid": g, "grid_ask": lattice[sym]["grid_ask"],
                   "spread_units": lattice[sym]["spread_units"],
                   "spread_sd": lattice[sym]["spread_sd"], "mid_half_grid": halves}
        print(f"  {sym:30s} {g:>11.6g} {lattice[sym]['grid_ask']:>11.6g} "
              f"{lattice[sym]['spread_units']:>12.4f} {lattice[sym]['spread_sd']:>11.4g} "
              f"{halves:>17.4f}", flush=True)
    report["bid_ask"] = ba
    save(report)

    # ---------------------------------------------------------- section 6 ----
    print("\n" + "=" * 108)
    print("6. DOES THE QUANTISATION ERROR ACCUMULATE?")
    print("=" * 108, flush=True)
    print("  display rounding keeps a full-precision internal price: the residual is bounded,")
    print("  consecutive increments share it with opposite signs (rho1 < 0), and it CANCELS on")
    print("  aggregation, so the variance ratio falls toward 1/(1 + (1/6)/sigma_Y^2).")
    print("  feedback rounding makes the rounded price the state: rho1 = 0 and the variance")
    print("  ratio is exactly 1 at every k. The two differ by sigma_Y^-2, so this section is")
    print("  UNTESTED on a fine-grid feed however many ticks it is given.\n", flush=True)
    print(f"  {'feed':30s} {'sigma_Y':>9s} {'n':>9s} {'rho1':>9s} {'+-':>7s} {'pred disp':>10s} "
          f"{'VR(8)':>8s} {'VR(64)':>8s} {'VR inf disp':>12s}")
    acc: dict[str, dict] = {}
    for sym, d in ticks_by_feed.items():
        if not lattice[sym]["diffusion"]:
            continue  # a compound Poisson or a fixed-size coin read through a diffusion
        g, nominal = lattice[sym]["grid"], nominal_dt(sym)
        a = accumulation(d["bid"], d["time"], nominal, g)
        sl = lattice[sym]["sigma_lat"]
        # Both in terms of the OBSERVED per-tick spread in lattice units, which
        # is what `sigma_lat` is. Writing them in terms of the *internal* spread
        # would need it deconvolved first and would be the same numbers by a
        # longer route: `Var(D_1) = Var(dY) + 2 Var(r)` is the observed second
        # moment, `Cov(D_t, D_t+1) = -Var(r)`, and `Var(r) = 1/12`, so
        # `rho1 = -(1/12) / sigma_Y^2` and the aggregated variance ratio tends
        # to `1 - (1/6) / sigma_Y^2`. Under feedback both are exactly zero and
        # one - the residual is added afresh each tick and never cancels.
        pred_rho = -(1.0 / 12.0) / (sl * sl)
        pred_vr = 1.0 - (1.0 / 6.0) / (sl * sl)
        a["sigma_lat"], a["pred_rho1_display"], a["pred_vr_inf_display"] = sl, pred_rho, pred_vr
        acc[sym] = a
        print(f"  {sym:30s} {sl:>9.4g} {a['n']:>9,} {a['rho1']:>9.5f} {a['rho1_se']:>7.4f} "
              f"{pred_rho:>10.5f} {a['vr'].get(8, float('nan')):>8.5f} "
              f"{a['vr'].get(64, float('nan')):>8.5f} {pred_vr:>12.5f}", flush=True)
    report["accumulation"] = acc
    save(report)

    coarse = [k for k, _ in sorted(((k, v) for k, v in lattice.items() if v["diffusion"]),
                                   key=lambda kv: kv[1]["sigma_lat"])[:3]]
    print(f"\n  controls on the three coarsest feeds - the only ones where the two architectures")
    print(f"  are far enough apart to be told apart at all:\n")
    accctl = {}
    for sym in coarse:
        g, nominal = lattice[sym]["grid"], nominal_dt(sym)
        n = acc[sym]["n"] + 2
        spec = {"price": lattice[sym]["price"], "grid": g, "dt": nominal,
                "drop": clocks[sym]["empty_frac"],
                "jitter_ms": clocks[sym]["offset_sd_ms"]}
        got = {}
        for state in ("continuous", "feedback"):
            # Each architecture is matched to the feed's *observed* second
            # moment under its own residual arithmetic - see `internal_sigma`.
            sig = internal_sigma(lattice[sym]["sd_rel"], g, lattice[sym]["price"], nominal, state)
            rs, v8, v64 = [], [], []
            for r in range(REPS_POS):
                s = SIM.ticks(n, price=spec["price"], sigma=sig, dt=spec["dt"], grid=g,
                              state=state, drop=spec["drop"], jitter_ms=spec["jitter_ms"],
                              seed=SEED + 131 * r)
                a = accumulation(s["bid"], s["time"], nominal, g)
                rs.append(a["rho1"]); v8.append(a["vr"].get(8, float("nan")))
                v64.append(a["vr"].get(64, float("nan")))
            got[state] = {"rho1": float(np.mean(rs)), "rho1_sd": float(np.std(rs)),
                          "vr8": float(np.mean(v8)), "vr8_sd": float(np.std(v8)),
                          "vr64": float(np.mean(v64)), "vr64_sd": float(np.std(v64)),
                          "rho1_lo": float(np.min(rs)), "rho1_hi": float(np.max(rs)),
                          "vr64_lo": float(np.min(v64)), "vr64_hi": float(np.max(v64)),
                          "sigma_internal": sig}
        real = acc[sym]
        d_d = abs(real["rho1"] - got["continuous"]["rho1"])
        d_f = abs(real["rho1"] - got["feedback"]["rho1"])
        verdict = ("display" if d_d < d_f else "feedback") if math.isfinite(real["rho1"]) else "-"
        accctl[sym] = {"control": got, "verdict_rho1": verdict}
        print(f"  {sym}  (sigma_Y = {lattice[sym]['sigma_lat']:.4g}, n = {real['n']:,})")
        print(f"    {'':20s} {'rho1':>12s} {'[min,max]':>20s} {'VR(64)':>10s} {'[min,max]':>20s}")
        print(f"    {'REAL':20s} {real['rho1']:>12.5f} {'':>20s} "
              f"{real['vr'].get(64, float('nan')):>10.5f}")
        for state in ("continuous", "feedback"):
            c = got[state]
            label = "display rounding" if state == "continuous" else "feedback rounding"
            print(f"    {label:20s} {c['rho1']:>12.5f} "
                  f"[{c['rho1_lo']:+.5f},{c['rho1_hi']:+.5f}] {c['vr64']:>10.5f} "
                  f"[{c['vr64_lo']:.5f},{c['vr64_hi']:.5f}]")
        print(f"    nearer to: {verdict}\n", flush=True)
    report["accumulation_controls"] = accctl
    save(report)
    print(f"\nwrote {OUT}   total {time.time() - began:.0f}s", flush=True)


if __name__ == "__main__":
    main()
