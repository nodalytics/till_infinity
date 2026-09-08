"""Six online change-point detectors, ranked as origin locators on one population.

The question is the one `research/localising.md` already poses and this widens:
inside the coarse bar that carries a turn, which minute did the move start
from? Every method here answers with an index into the same 1m window, on the
same events, scored by the same metric - stability under an arbitrary sampling
grid, because this data has no ground-truth origin to compute an error against.

The methods, and why each is here:

* **FOCuS** - exact CUSUM likelihood ratio over every candidate start. The
  repository's own, and the number to beat.
* **MD-FOCuS** - the same statistic over a *vector*. High, low and close are
  co-dependent, so a change in the mean vector is a stronger event than a
  change in the close alone (arXiv 2104.00581).
* **BOCPD** - Adams & MacKay. Bayesian run-length posterior, which is the one
  method here that reports a *distribution* over where the change was rather
  than a point.
* **KCP** - kernel change point. Non-parametric: no Gaussian assumption, which
  matters because intraday returns are not.
* **RuLSIF** - relative density-ratio estimation between a reference and a test
  window. Catches changes in *shape*, not only in mean.
* **NEWMA** - two EMAs at different rates. The cheapest thing that could work,
  included so the expensive methods have to beat something.

Nothing is copied from `changepoint-online`, `densratio` or `ruptures`. The
repository is public and has no licence file, so a dependency is a decision
nobody has made yet; these are written from the papers.

**Not everything the feature-engineering argument asks for can be tested here.**
`bt1m.db` carries open, high, low and close and **no volume**, so the log-volume
stream - the liquidity half of the dual-stream idea - has no data in this
harness and is absent rather than faked. What can be built from these columns
is the log return and the candle spread `log(high/low)`, and both are.
"""

from __future__ import annotations

import bisect
import math
import os
import random
import sqlite3
import statistics as st
import sys

import numpy as np

from till_infinity.structures.drawing import origins
from till_infinity.structures.learning.focus import Focus
from till_infinity.structures.vol.volatility import Volatility

DB = "/app/.data/research/bt1m.db"
COARSE = int(os.environ.get("COARSE", "15"))


class _Bar:
    __slots__ = ("open", "high", "low", "close", "time")

    def __init__(self, ts, o, h, low, c):
        self.time, self.open, self.high, self.low, self.close = ts, o, h, low, c


def load(conn, feed):
    venue = conn.execute(
        "SELECT venue, COUNT(*) n FROM bars WHERE feed=? AND interval='1m' AND high > low "
        "GROUP BY venue ORDER BY n DESC LIMIT 1",
        (feed,),
    ).fetchone()
    if not venue:
        return []
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval='1m' "
        "AND venue=? ORDER BY ts",
        (feed, venue[0]),
    ).fetchall()
    return [_Bar(*r) for r in rows]


def aggregate(fine, size, offset):
    out, bucket = [], []
    for bar in fine:
        if bucket and ((bar.time // 60) - offset) % size == 0:
            out.append(_Bar(
                bucket[0].time, bucket[0].open,
                max(b.high for b in bucket), min(b.low for b in bucket), bucket[-1].close,
            ))
            bucket = []
        bucket.append(bar)
    if bucket:
        out.append(_Bar(
            bucket[0].time, bucket[0].open,
            max(b.high for b in bucket), min(b.low for b in bucket), bucket[-1].close,
        ))
    return out


def warmed(bars):
    vol = Volatility()
    for b in bars:
        vol.update(float(b.close))
        vol.observe_bar(b.open, b.high, b.low, b.close)
    return vol


# --------------------------------------------------------------------------
# The detectors. Each takes the window's closes (and for the multivariate one,
# the bars) plus which way the impulse went, and returns an index into the
# window: **where the move started from**, which is what an origin is.
# --------------------------------------------------------------------------


def _diffs(values):
    return [values[i] - values[i - 1] for i in range(1, len(values))]


def at_focus(window, down):
    """Exact CUSUM likelihood ratio, argmax over every start.

    One-sided: for a drop the detector looks for a fall and for a rally a rise,
    which is the repository's own convention and the reason `focus.py` refuses
    to collapse the two into one alarm.
    """
    closes = [b.close for b in window]
    detector = Focus(threshold=math.inf, up=not down)
    best, where = 0.0, 0
    for step in _diffs(closes):
        detector.update(step, scale=1.0)
        if detector.statistic > best:
            best, where = detector.statistic, detector.at
    return where


def at_mdfocus(window, down):
    """Multivariate Gaussian FOCuS over the (close, high, low) log-return vector.

    The user's point and the paper's: those three are one object seen three
    ways, so a change in the *mean vector* is better evidence than a change in
    any one of them. The per-dimension statistic at a shared candidate start
    is summed, which is the exact multivariate statistic - the paper's hull
    pruning is a way to compute this quickly and is not needed on a window of
    fifteen minutes, so it is brute-forced and therefore exact.

    Log returns rather than prices, because the three series live at different
    levels and a mean shift in an un-normalised vector is dominated by
    whichever component is largest.
    """
    streams = []
    for pick in (lambda b: b.close, lambda b: b.high, lambda b: b.low):
        values = [math.log(max(pick(b), 1e-12)) for b in window]
        streams.append(_diffs(values))
    n = len(streams[0])
    if n < 2:
        return 0
    sums = [np.concatenate(([0.0], np.cumsum(s))) for s in streams]
    scales = [float(np.std(s)) or 1.0 for s in streams]
    best, where = 0.0, 0
    for tau in range(n):
        total = 0.0
        for cumulative, scale in zip(sums, scales):
            gap = n - tau
            diff = (cumulative[n] - cumulative[tau]) / scale
            if not down:
                diff = -diff
            # One-sided per dimension, the same way the univariate one is: a
            # dimension moving the other way is not evidence for this impulse
            # and must not be allowed to cancel one that is.
            if diff < 0:
                total += diff * diff / (2.0 * gap)
        if total > best:
            best, where = total, tau
    return where


def at_bocpd(window, down, hazard=0.1):
    """Adams & MacKay's run-length posterior, Gaussian with an unknown mean.

    The one method here that returns a *distribution* over where the change
    was. The point estimate taken is the MAP run length at the end of the
    window, which places the change `r*` observations back - the standard
    retrospective read of an online filter.

    Direction is ignored on purpose: BOCPD as published is two-sided, and
    making it one-sided would be a different algorithm wearing its name.
    """
    steps = _diffs([b.close for b in window])
    n = len(steps)
    if n < 2:
        return 0
    sigma = float(np.std(steps)) or 1.0
    var0 = sigma * sigma
    run = np.array([1.0])
    means = np.array([0.0])
    counts = np.array([0.0])
    for x in steps:
        # Predictive probability of x under each surviving run length.
        spread = np.sqrt(var0 + var0 / np.maximum(counts, 1.0))
        pred = np.exp(-0.5 * ((x - means) / spread) ** 2) / (spread * math.sqrt(2 * math.pi))
        grown = run * pred * (1.0 - hazard)
        started = float(np.sum(run * pred * hazard))
        run = np.concatenate(([started], grown))
        total = float(np.sum(run))
        run = run / total if total > 0 else np.ones_like(run) / len(run)
        # Sufficient statistics, one per run length: a run of length r has
        # seen the last r observations and nothing before them.
        counts = np.concatenate(([0.0], counts + 1.0))
        means = np.concatenate(([0.0], (means * (counts[1:] - 1.0) + x) / counts[1:]))
    return max(0, min(n, n - int(np.argmax(run))))


def _gram(points):
    diff = points[:, None, :] - points[None, :, :]
    square = np.sum(diff * diff, axis=2)
    off = square[np.triu_indices(len(points), 1)]
    width = float(np.median(off)) if off.size else 1.0
    return np.exp(-square / (2.0 * (width or 1.0)))


def _features(window):
    """The engineered streams: the log return and the candle spread.

    Two phenomena, not one. A change in the mean of the log return is a turn;
    a change in the mean of `log(high/low)` is the range widening, which is
    the volatility half. The liquidity half wants log volume and this database
    has none, so it is absent rather than invented.
    """
    out = []
    for i in range(1, len(window)):
        before, bar = window[i - 1], window[i]
        ret = math.log(max(bar.close, 1e-12) / max(before.close, 1e-12))
        spread = math.log(max(bar.high, 1e-12) / max(bar.low, 1e-12))
        out.append((ret, spread))
    return np.array(out) if out else np.zeros((0, 2))


def at_kcp(window, down):
    """Kernel change point, one split, Gaussian kernel with the median width.

    Non-parametric: it asks whether the two segments look like they came from
    different distributions, without assuming either is Gaussian. Run on the
    engineered features rather than raw prices, because a kernel on a
    non-stationary level measures the level.
    """
    points = _features(window)
    n = len(points)
    if n < 4:
        return 0
    kernel = _gram(points)
    diagonal = float(np.trace(kernel))
    best, where = math.inf, 0
    for tau in range(1, n):
        left = kernel[:tau, :tau].sum() / tau
        right = kernel[tau:, tau:].sum() / (n - tau)
        cost = diagonal - left - right
        if cost < best:
            best, where = cost, tau
    return where


def at_rulsif(window, down, alpha=0.1, ridge=0.1):
    """Relative density-ratio estimation, argmax Pearson divergence over the split.

    Catches a change in the *shape* of the distribution, which the mean-shift
    methods cannot. The relative ratio - `alpha` mixing the test density into
    the denominator - is what keeps the estimate bounded on the tiny samples a
    fifteen-minute window gives it, and that boundedness is the whole reason
    RuLSIF exists rather than plain uLSIF.
    """
    points = _features(window)
    n = len(points)
    if n < 6:
        return 0
    best, where = -math.inf, 0
    for tau in range(2, n - 1):
        reference, test = points[:tau], points[tau:]
        centres = test
        both = np.vstack((reference, test))
        diff = both[:, None, :] - centres[None, :, :]
        square = np.sum(diff * diff, axis=2)
        off = square[square > 0]
        width = float(np.median(off)) if off.size else 1.0
        phi = np.exp(-square / (2.0 * (width or 1.0)))
        phi_ref, phi_test = phi[: len(reference)], phi[len(reference) :]
        left = alpha * (phi_test.T @ phi_test) / len(test)
        left += (1 - alpha) * (phi_ref.T @ phi_ref) / len(reference)
        right = phi_test.mean(axis=0)
        try:
            theta = np.linalg.solve(left + ridge * np.eye(len(centres)), right)
        except np.linalg.LinAlgError:
            continue
        pe = (
            -alpha / 2 * float(np.mean((phi_test @ theta) ** 2))
            - (1 - alpha) / 2 * float(np.mean((phi_ref @ theta) ** 2))
            + float(np.mean(phi_test @ theta))
            - 0.5
        )
        if pe > best:
            best, where = pe, tau
    return where


def at_newma(window, down, fast=0.5, slow=0.1):
    """Two EMAs at different rates; the change is where they part company most.

    The cheapest thing in this file, here so the expensive methods have to beat
    something. On the engineered features, and two-sided by construction - the
    norm of a difference has no direction.
    """
    points = _features(window)
    if len(points) < 2:
        return 0
    quick = slowly = points[0]
    best, where = -1.0, 0
    for i, row in enumerate(points):
        quick = (1 - fast) * quick + fast * row
        slowly = (1 - slow) * slowly + slow * row
        gap = float(np.linalg.norm(quick - slowly))
        if gap > best:
            best, where = gap, i
    return where


METHODS = {
    "focus": at_focus,
    "mdfocus": at_mdfocus,
    "bocpd": at_bocpd,
    "kcp": at_kcp,
    "rulsif": at_rulsif,
    "newma": at_newma,
}
#: Blends of the two estimators that actually work. `fine` finds the extreme
#: and `focus` finds the change point, and they agree on half the events; the
#: question is whether anything is gained by mixing them rather than choosing.
BLENDS = ("mid", "lean", "gated")
NAMES = ("baseline", "fine", *METHODS, *BLENDS)


def estimate(found, coarse, fine, fine_times, size):
    at = {b.time: i for i, b in enumerate(coarse)}
    out = {n: [] for n in NAMES}
    for origin in found:
        index = at.get(float(origin.when))
        if index is None or index + 1 >= len(coarse):
            continue
        turn = coarse[index]
        down = origin.launched == "down"
        start = bisect.bisect_left(fine_times, turn.time)
        stop = bisect.bisect_left(fine_times, turn.time + size * 60)
        window = fine[start:stop]
        if len(window) < 4:
            continue
        picked = max(window, key=lambda b: b.close) if down else min(
            window, key=lambda b: b.close
        )
        out["baseline"].append(origin.price)
        out["fine"].append(picked.close)
        for name, method in METHODS.items():
            try:
                where = method(window, down)
            except Exception:
                where = None
            out[name].append(
                window[where].close if where is not None and 0 <= where < len(window)
                else origin.price
            )
        # The two that beat the baseline, mixed three ways.
        extreme, change = out["fine"][-1], out["focus"][-1]
        span = max(b.high for b in window) - min(b.low for b in window)
        near = abs(extreme - change) <= 0.25 * span if span > 0 else True
        out["mid"].append((extreme + change) / 2)
        out["lean"].append(0.75 * extreme + 0.25 * change)
        # Take the extreme where the change point confirms it, and split the
        # difference where it does not - the one place the second opinion has
        # anything to add, since it is the worse estimator everywhere else.
        out["gated"].append(extreme if near else (extreme + change) / 2)
    return out


def find(bars, unit):
    return origins.Origins().observe(
        [b.time for b in bars], [b.close for b in bars], unit, bars_at=bars
    )


def gaps(a, b, unit):
    if not a or not b or unit <= 0:
        return []
    return [min(abs(x - y) for y in b) / unit for x in a]


def run(feeds, seed=3):
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60.0)
    shifted = {n: [] for n in NAMES}
    nulls = {n: [] for n in NAMES}
    print(f"COARSE={COARSE}m, so each window is {COARSE} one-minute observations.\n")
    print(f"{'feed':10s} {'events':>7s} " + " ".join(f"{n:>9s}" for n in NAMES))
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) < 5_000:
            continue
        fine_times = [b.time for b in fine]
        base_bars = aggregate(fine, COARSE, 0)
        vol = warmed(base_bars)
        unit = vol.price_units(st.median([b.close for b in base_bars]), 1.0)
        if unit <= 0:
            continue
        base = estimate(find(base_bars, unit), base_bars, fine, fine_times, COARSE)
        if len(base["baseline"]) < 5:
            continue
        lo = min(b.low for b in base_bars)
        hi = max(b.high for b in base_bars)
        per = {}
        for offset in range(1, COARSE):
            other_bars = aggregate(fine, COARSE, offset)
            other = estimate(
                find(other_bars, warmed(other_bars).price_units(
                    st.median([b.close for b in other_bars]), 1.0
                ) or unit),
                other_bars, fine, fine_times, COARSE,
            )
            for n in NAMES:
                got = gaps(base[n], other[n], unit)
                shifted[n] += got
                per.setdefault(n, []).extend(got)
                nulls[n] += gaps(
                    base[n],
                    sorted(rng.uniform(lo, hi) for _ in range(max(1, len(other[n])))),
                    unit,
                )
        print(
            f"{feed:10s} {len(base['baseline']):7d} "
            + " ".join(f"{st.median(per[n]) if per.get(n) else 0:8.3f}v" for n in NAMES)
        )
    print()
    print(f"{'method':10s} {'n':>7s} {'median':>9s} {'null':>9s} {'ratio':>7s} {'<0.25v':>8s}")
    for n in NAMES:
        xs, ns = shifted[n], nulls[n]
        if not xs:
            continue
        m, nm = st.median(xs), st.median(ns)
        near = len([x for x in xs if x <= 0.25]) / len(xs)
        print(f"{n:10s} {len(xs):7d} {m:8.3f}v {nm:8.3f}v {nm / m if m else 0:6.1f}x {near:8.1%}")


if __name__ == "__main__":
    run(sys.argv[1].split(","))
