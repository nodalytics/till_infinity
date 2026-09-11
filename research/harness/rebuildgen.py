"""The five Deriv generators, written from the derived specification, plus the
statistical battery the real feeds were characterised by.

This module holds no results and states no failure conditions - it is the
*apparatus*. Every study harness (`rebuildvol.py`, `rebuildstep.py`,
`rebuildspike.py`, `rebuildpower.py`) imports the generators and the battery
from here so that the identical estimator runs on the real feed and on the
rebuild. A rebuild judged by a second implementation of the same statistic is
judging the implementation.

Three things in here are load-bearing and easy to get wrong.

**A bar is not the process.** The real rows in `research.db` are one-minute bars
built from a tick stream, so every generator below emits *ticks* and
`bars_from_stream` aggregates them with one rule: a bar's open, high, low and
close are the first, extreme and last of the `tpb` ticks that fall inside it,
and the previous bar's close is *not* a candidate for its high or low.
`derivegbm.py` established that this is the convention the data matches - taking
the range over `p_0..p_n` instead of `p_1..p_n` overstates the Parkinson ratio
by two points.

**The quote grid is part of the observation.** Deriv publishes a rounded price.
A continuous-valued simulation and a discretely quoted feed differ in their
tick-return distribution at the first decimal place, which a two-sample KS test
on 80,000 points sees immediately and which has nothing to do with whether the
generator is right. `decimals()` reads the grid off the real quotes and the
generators round to it, while the *state* they carry forward is unrounded.

**The 0.5826 constant is not applied anywhere in here.** It is the
Broadie-Glasserman-Kou discrete-monitoring correction that `deriving.md`
derives, and the point of simulating ticks and aggregating them is that the
correction should *emerge* - if the rebuild has to be told about it, it is not a
rebuild.
"""

from __future__ import annotations

import math
import os
import sqlite3

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))

MINUTES_PER_YEAR = 365 * 24 * 60
SECONDS_PER_YEAR = MINUTES_PER_YEAR * 60
MINUTE_MS = 60_000
#: -zeta(1/2)/sqrt(2*pi); quoted for reference only, never applied below.
BETA = 0.5825971579

#: Structure-function ladder, copied from `fractal.py` so the Hurst exponent the
#: rebuild is scored on is the estimator that read H = 0.50 off the real feeds.
SCALES = (1, 2, 4, 8, 16, 32, 64, 128, 256)
QS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
MIN_WINDOWS = 150

LAGS = (1, 2, 3, 5, 10, 20, 60)
VR_Q = (2, 5, 10, 30, 60)


# ------------------------------------------------------------------ loaders --
def connect():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def real_bars(feed: str, interval: str = "1m") -> dict:
    conn = connect()
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval=? ORDER BY ts ASC",
        (feed, interval),
    ).fetchall()
    conn.close()
    keep = [r for r in rows if None not in r and r[1] > 0 and r[2] > 0 and r[3] > 0 and r[4] > 0]
    if not keep:
        return {"feed": feed, "n": 0}
    a = np.array(keep, dtype=float)
    return {"feed": feed, "n": len(a), "ts": a[:, 0].astype(np.int64),
            "open": a[:, 1], "high": a[:, 2], "low": a[:, 3], "close": a[:, 4]}


def real_ticks(feed: str) -> dict:
    conn = connect()
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    conn.close()
    keep = [r for r in rows if r[1] is not None and r[2] is not None and r[1] > 0]
    if not keep:
        return {"feed": feed, "n": 0}
    a = np.array(keep, dtype=float)
    mid = (a[:, 1] + a[:, 2]) / 2.0
    span = (a[-1, 0] - a[0, 0]) / 1000.0
    return {"feed": feed, "n": len(a), "ts": a[:, 0].astype(np.int64),
            "mid": mid, "spread": a[:, 2] - a[:, 1],
            "per_sec": len(a) / span if span > 0 else float("nan")}


def decimals(vals: np.ndarray, maxd: int = 10) -> int | None:
    """Smallest `d` with every value an exact multiple of 10**-d.

    Read off the real quotes so the rebuild is rounded the way the feed is. A
    feed whose quotes carry more precision than the simulator would fail a KS
    test on its tick returns for a reason that is nothing to do with the law.
    """
    v = np.asarray(vals, dtype=float)
    if v.size > 200_000:
        v = v[:: max(1, v.size // 200_000)]
    for d in range(maxd + 1):
        s = v * (10.0 ** d)
        if np.all(np.abs(s - np.round(s)) < 1e-4):
            return d
    return None


def quote_grid(mid: np.ndarray) -> float:
    """The lattice the feed is actually quoted on.

    Decimal precision alone is not enough: `twins.md` section 6 quarantined
    `volatility_150_1s_index` and `volatility_250_1s_index` for a *coarse* quote
    grid, and a feed that moves in steps of five while printing no decimals has
    a grid of 5, not of 1. So the decimals fix the scale and the greatest common
    divisor of the tick moves fixes the spacing. Getting this wrong makes a
    correct generator fail a tick-level KS test for a reason that has nothing to
    do with the law.
    """
    d = decimals(mid)
    if d is None:
        return 0.0
    scale = 10.0 ** d
    diffs = np.abs(np.diff(np.asarray(mid, dtype=float)))
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return float(10.0 ** -d)
    ints = np.round(diffs * scale).astype(np.int64)
    ints = ints[ints > 0]
    if ints.size == 0:
        return float(10.0 ** -d)
    g = int(np.gcd.reduce(ints[: min(ints.size, 200_000)]))
    return float(max(g, 1)) / scale


# -------------------------------------------------------------- aggregation --
def bars_from_stream(stream, tpb: int, n_bars: int, keep_ticks: int = 0):
    """Consume a stream of consecutive tick prices into `n_bars` OHLC bars.

    open/high/low/close are the first / max / min / last of the `tpb` ticks
    inside the bar. The previous close is not in the range - see the module
    docstring.
    """
    o = np.empty(n_bars)
    hi = np.empty(n_bars)
    lo = np.empty(n_bars)
    cl = np.empty(n_bars)
    kept: list[np.ndarray] = []
    nkept = 0
    filled = 0
    buf = np.empty(0)
    for chunk in stream:
        if keep_ticks and nkept < keep_ticks:
            take = min(keep_ticks - nkept, chunk.size)
            kept.append(chunk[:take].copy())
            nkept += take
        buf = chunk if buf.size == 0 else np.concatenate([buf, chunk])
        k = min(buf.size // tpb, n_bars - filled)
        if k > 0:
            m = buf[: k * tpb].reshape(k, tpb)
            o[filled:filled + k] = m[:, 0]
            hi[filled:filled + k] = m.max(axis=1)
            lo[filled:filled + k] = m.min(axis=1)
            cl[filled:filled + k] = m[:, -1]
            filled += k
            buf = buf[k * tpb:]
        if filled >= n_bars:
            break
    ts = np.arange(filled, dtype=np.int64) * MINUTE_MS
    ticks = np.concatenate(kept) if kept else np.empty(0)
    return {"n": filled, "ts": ts, "open": o[:filled], "high": hi[:filled],
            "low": lo[:filled], "close": cl[:filled], "ticks": ticks}


# ------------------------------------------------------------- generators ----
LATTICE_MODES = ("price", "bump", "resample")


def lattice_walk(px: np.ndarray, price: float, grid: float, mode: str,
                 sigma_tick: float, rng) -> np.ndarray:
    """Put a continuous price path onto the venue's quote lattice.

    Three rules, and the whole of `rebuildladder.py`'s ladder is which one. None
    of them costs a parameter - see `gen_gbm` for what each is and which are
    refuted. Shared so the deliberately wrong generators in `rebuildvol.py` are
    quantised the same way as the honest one: a control that differs from the
    rebuild in the law *and* in the lattice rule is measuring both at once.
    """
    if not grid:
        return px
    if mode == "price":
        return np.round(px / grid) * grid
    d = np.diff(np.concatenate([[price], px]))
    dl = np.round(d / grid)
    idx = np.flatnonzero(dl == 0)
    if idx.size and mode == "bump":
        sgn = np.sign(d[idx])
        sgn[sgn == 0] = np.where(rng.random(int((sgn == 0).sum())) < 0.5, -1.0, 1.0)
        dl[idx] = sgn
    elif idx.size:
        # Redraw until the quote changes. The accepted increment is then a
        # rounded Gaussian *conditioned on being nonzero*, which spreads the zero
        # bin over every other bin in proportion rather than onto the one-unit
        # bin alone - and the feed's own increment histogram says in proportion.
        # The local price sd is `px * sigma_tick` because the process is
        # geometric.
        s_loc = px * sigma_tick
        for _ in range(64):
            nl = np.round(rng.standard_normal(idx.size) * s_loc[idx] / grid)
            dl[idx] = nl
            idx = idx[nl == 0]
            if not idx.size:
                break
        if idx.size:  # a grid coarser than 64 rejections can clear
            dl[idx] = np.where(rng.random(idx.size) < 0.5, -1.0, 1.0)
    return price + np.cumsum(dl) * grid


def lattice_mode(value) -> str:
    m = {True: "bump", False: "price", None: "price"}.get(value, value)
    if m not in LATTICE_MODES:
        raise ValueError(f"lattice must be one of {LATTICE_MODES}, got {value!r}")
    return m


def gen_gbm(n_ticks: int, sigma_ann: float, tick_seconds: float, p0: float,
            grid: float, rng, chunk: int = 2_000_000, lattice="price"):
    """Driftless geometric Brownian motion in the log price.

    The only parameters are the annualised volatility in the instrument's name
    and the publication rate. `sigma_tick = (N/100) * sqrt(dt_years)`; the drift
    is zero in the log, which is one of the two conventions `deriving.md` section
    two showed sixty days cannot separate (they are 0.537 combined SE apart).

    `lattice` is the rung of the discriminator ladder in `rebuildladder.py` and
    it is the *only* thing that differs between them - no rung adds a parameter:

    * ``"price"`` rounds the accumulated price onto the quote grid. Refuted:
      the fraction of zero tick moves separated it from the feed at AUC 0.689
      against a floor of 0.499.
    * ``"bump"`` rounds the *increment* and moves one unit where it would have
      rounded to nothing. Refuted in turn: it puts the whole of the zero bin
      into the one-unit bin, which is 45% too many minimum-size moves.
    * ``"resample"`` rounds the increment and redraws a zero until the quote
      changes, which spreads the zero bin over every nonzero bin in proportion.
      That is what the feed's own increment histogram shows.
    """
    mode = lattice_mode(lattice)
    sigma_tick = (sigma_ann / 100.0) * math.sqrt(tick_seconds / SECONDS_PER_YEAR)
    logp = math.log(p0)
    price = p0
    done = 0
    while done < n_ticks:
        m = min(chunk, n_ticks - done)
        path = logp + np.cumsum(rng.standard_normal(m) * sigma_tick)
        logp = float(path[-1])
        px = np.exp(path)
        out = lattice_walk(px, price, grid, mode, sigma_tick, rng)
        price = float(out[-1])
        yield out
        done += m


def gen_jump(n_ticks: int, sigma_ann: float, tick_seconds: float,
             jump_rate_per_min: float, jump_log_size: float, p0: float,
             grid: float, rng, chunk: int = 2_000_000):
    """Jump index: diffusion at the *name* plus symmetric jumps on top.

    `generators.md` measured 1.322x the name on all five and read it as a
    convention - "the name is the diffusive volatility and the jumps are extra",
    leaving `1.322**2 - 1 = 0.7477` of the diffusive variance for the jumps. That
    fixes the jump size once the rate is known:

        E[J^2] = 0.7477 * sigma_min^2 * (minutes per jump)

    so `jump_log_size` is derived rather than fitted. The alternative reading -
    diffusion already at 1.322x with jumps on top of *that* - is a different
    generator and `rebuildvol.py` tests both against the data.
    """
    sigma_tick = (sigma_ann / 100.0) * math.sqrt(tick_seconds / SECONDS_PER_YEAR)
    p_jump = jump_rate_per_min * tick_seconds / 60.0
    logp = math.log(p0)
    done = 0
    while done < n_ticks:
        m = min(chunk, n_ticks - done)
        steps = rng.standard_normal(m) * sigma_tick
        nj = rng.poisson(p_jump * m)
        if nj:
            pos = rng.integers(0, m, nj)
            amp = jump_log_size * rng.choice(np.array([-1.0, 1.0]), size=nj)
            np.add.at(steps, pos, amp)
        path = logp + np.cumsum(steps)
        logp = float(path[-1])
        px = np.exp(path)
        yield np.round(px / grid) * grid if grid else px
        done += m


def gen_step(n_ticks: int, step: float, p_up: float, p0: float, rng,
             chunk: int = 2_000_000):
    """Step Index: a fixed increment and a fair coin.

    Accumulated as integers and multiplied by the step at the end, so the
    "99.9988% of ticks are exactly 0.1" concentration is not decided by floating
    point. `p0` is snapped to the lattice for the same reason.
    """
    base = round(p0 / step)
    pos = 0
    done = 0
    while done < n_ticks:
        m = min(chunk, n_ticks - done)
        s = np.where(rng.random(m) < p_up, 1, -1).astype(np.int64)
        walk = pos + np.cumsum(s)
        pos = int(walk[-1])
        yield (base + walk) * step
        done += m


def _fold(x: np.ndarray, m: int) -> np.ndarray:
    """Triangle-wave fold of a free walk into [0, m].

    A simple symmetric walk that *bounces* off both ends of [0, m] - a step that
    would leave the band is taken back inside - is exactly the image of the free
    walk under this map, so the confined walk costs one cumsum rather than a
    Python loop over fifty million ticks.
    """
    y = np.mod(x, 2 * m)
    return np.where(y <= m, y, 2 * m - y)


def gen_rangebreak(n_ticks: int, step: float, band: int, mean_break_ticks: float,
                   break_jump: float, p0: float, rng, jump_pool=None,
                   anchor: str = "edge", mean_quiet_ticks: float | None = None,
                   band_pool=None):
    """Range Break: a bounded +-1 walk, and a memoryless break that re-ranges.

    `band` is the full width of the range in steps, the walk bounces off both
    edges, the break arrives memorylessly at `mean_break_ticks`, and at a break
    the price jumps by `break_jump` (or a draw from `jump_pool`) with a random
    sign. `anchor` says where the new range sits relative to where the break
    landed:

    * `edge` - the break point becomes the new range's near edge, so a break up
      opens a range above it and a break down opens one below. The price then
      has the whole range to travel across, which makes the displacement
      accumulated inside a range four times more variable than under `centre`
      at the same width.
    * `edge_far` - the break *overshoots* and the new range opens behind it, so a
      break up leaves the price at the top of its new range and the next move is
      back into it. This is the one that adds mean reversion immediately after a
      break without touching the long-horizon plateau.
    * `centre` - the new range is centred on the break point.

    The two are different generators and they predict different variance-ratio
    curves, so `rebuildstep.py` builds both and reports both.

    `deriving.md` publishes only the break rate. The band width, the jump size
    and this anchoring rule are **not** in the specification - that page says so
    explicitly ("the actual range rule - how wide, how it resets, what counts as
    a bounce - is unknown"). They are what `rebuildstep.py` has to supply, and
    the width is estimated from the *visited* range rather than from the
    variance ratio so that the variance-ratio curve stays a prediction.
    """
    lo_edge = round(p0 / step)
    off = band // 2
    emitted = 0
    # `band_pool` draws a width per range instead of holding one. The feed says
    # to: the *visited* range between breaks on `range_break_100_index` has a
    # median of 40 steps, a 90th percentile of 93 and a maximum of 259, which a
    # fixed width cannot produce. A mixture is also the only thing tried here
    # that can confine early and carry a high plateau at once, because the
    # narrow ranges do the first and the wide ones the second.
    def _next_band(cur: int) -> int:
        if band_pool is None:
            return cur
        return max(4, int(round(float(band_pool[rng.integers(0, len(band_pool))]))))
    # Two event types where `mean_quiet_ticks` is given: a *break*, which jumps
    # the price and opens a new range, and a *quiet re-range*, which opens a new
    # range around where the price already is and moves nothing. The second is
    # what a one-band model cannot do - it lets the range be narrow enough to
    # confine early while the price still diffuses between range centres, which
    # is the only way to get a deep dip at twenty minutes and a plateau at 0.28
    # out of the same process. It also keeps every tick at exactly one unit,
    # which any additive second component would destroy.
    if mean_quiet_ticks and mean_quiet_ticks > 0:
        rate = 1.0 / mean_break_ticks + 1.0 / mean_quiet_ticks
        mean_event = 1.0 / rate
        p_break = (1.0 / mean_break_ticks) / rate
    else:
        mean_event, p_break = mean_break_ticks, 1.0
    while emitted < n_ticks:
        seg = int(rng.exponential(mean_event)) + 1
        seg = min(seg, n_ticks - emitted)
        free = np.cumsum(np.where(rng.random(seg) < 0.5, 1, -1).astype(np.int64))
        lattice = lo_edge + _fold(off + free, band)
        yield lattice * step
        emitted += seg
        if emitted >= n_ticks:
            break
        if rng.random() < p_break:
            amp = (float(jump_pool[rng.integers(0, len(jump_pool))])
                   if jump_pool is not None else break_jump)
            sign = 1 if rng.random() < 0.5 else -1
        else:
            amp, sign = 0.0, 1 if rng.random() < 0.5 else -1
        landed = int(lattice[-1]) + sign * round(amp)
        band = _next_band(band)
        if anchor == "centre":
            lo_edge, off = landed - band // 2, band // 2
        elif anchor == "edge_far":
            lo_edge = landed - band if sign > 0 else landed
            off = band if sign > 0 else 0
        else:
            lo_edge = landed if sign > 0 else landed - band
            off = 0 if sign > 0 else band


def gen_softbox(n_ticks: int, step: float, band: int, mean_break_ticks: float,
                break_jump: float, p0: float, rng, k: float = 0.25, q: float = 4.0,
                batch: int = 200):
    """Range Break with a *soft* edge instead of a reflecting wall.

    The walk still moves exactly one step a tick - anything additive would
    destroy the 99.98% concentration on one magnitude that `generators.md`
    measured - but its up-probability is pushed back towards the centre by

        p_up(x) = 0.5 - k * (|x| / half) ** q * sign(x)

    which is a reflecting box as `q -> inf` and a harmonic well at `q = 1`. The
    bias is state-dependent so the folding trick does not apply and the walk has
    to be stepped; it is stepped for `batch` independent range interiors at once,
    which turns a loop over fifty million ticks into a loop over one range's
    length with a vector inside it.

    This exists to test one reading of the residual `rebuildstep.py` is left
    with - too confined at one minute, too free at twenty, which is what a hard
    wall looks like against something smoother. It is a candidate, not the
    specification.
    """
    half = band / 2.0
    price = round(p0 / step)
    emitted = 0
    tmax = int(6 * mean_break_ticks)
    while emitted < n_ticks:
        sign = 1 if rng.random() < 0.5 else -1
        x = np.full(batch, -sign * half)
        paths = np.empty((batch, tmax), dtype=np.int64)
        for t in range(tmax):
            u = np.minimum(np.abs(x) / half, 1.0) ** q
            pr = 0.5 - k * u * np.sign(x)
            x = x + np.where(rng.random(batch) < pr, 1.0, -1.0)
            paths[:, t] = x
        for i in range(batch):
            seg = min(int(rng.exponential(mean_break_ticks)) + 1, tmax,
                      n_ticks - emitted)
            if seg <= 0:
                break
            piece = price + paths[i, :seg]
            yield piece * step
            emitted += seg
            if emitted >= n_ticks:
                return
            jsign = 1 if rng.random() < 0.5 else -1
            price = int(piece[-1]) + jsign * round(break_jump)


def gen_boomcrash(n_ticks: int, lam: float, grind_mean: float, grind_cv: float,
                  jump_mean: float, jump_median: float, side: int, p0: float,
                  grid: float, rng, grind_pool=None, jump_pool=None,
                  chunk: int = 2_000_000):
    """Boom and Crash as the compound Poisson process `deriving.md` section five
    specifies: `-g` with probability `1 - 1/lambda`, `+J` with probability
    `1/lambda`, `side = +1` for Boom (spikes up).

    With `grind_pool`/`jump_pool` omitted the marginals are built from the five
    published numbers alone - a gamma of the stated mean and CV for the grind,
    and a lognormal matched to the stated mean *and* median for the jump, which
    is exactly the information `deriving.md`'s table carries. That is the test
    that matters: does the published parameter set re-instantiate the feed, or
    does it need the empirical marginal?

    The closure `E[J] = lambda * E[g]` is *not* imposed - the published `E[J]`
    and `E[g]` are used as given, and whether the rebuilt path closes is then a
    check rather than a tautology.
    """
    p = 1.0 / lam
    k = 1.0 / (grind_cv ** 2)
    theta = grind_mean / k
    # lognormal matched to mean and median: median = exp(mu), mean = exp(mu+s^2/2)
    mu = math.log(jump_median)
    s2 = 2.0 * math.log(jump_mean / jump_median)
    s = math.sqrt(max(s2, 1e-12))
    price = p0
    done = 0
    while done < n_ticks:
        m = min(chunk, n_ticks - done)
        isj = rng.random(m) < p
        d = np.empty(m)
        ng = int((~isj).sum())
        nj = int(isj.sum())
        if ng:
            g = (grind_pool[rng.integers(0, grind_pool.size, ng)] if grind_pool is not None
                 else rng.gamma(k, theta, size=ng))
            d[~isj] = -side * g
        if nj:
            j = (jump_pool[rng.integers(0, jump_pool.size, nj)] if jump_pool is not None
                 else rng.lognormal(mu, s, size=nj))
            d[isj] = side * j
        path = price + np.cumsum(d)
        price = float(path[-1])
        yield np.round(path / grid) * grid if grid else path
        done += m


# ------------------------------------------------------------------ battery --
def logrets(close: np.ndarray, ts: np.ndarray | None = None) -> np.ndarray:
    """Log returns between adjacent minutes only - a gap is skipped, not logged
    as a one-minute move (`genvol.py`)."""
    r = np.log(close[1:] / close[:-1])
    if ts is None:
        return r[np.isfinite(r)]
    keep = (np.diff(ts) == MINUTE_MS) & np.isfinite(r)
    return r[keep]


def ann_vol(r: np.ndarray) -> float:
    if r.size < 100:
        return float("nan")
    return float(r.std(ddof=0) * math.sqrt(MINUTES_PER_YEAR) * 100.0)


def ann_vol_se(r: np.ndarray) -> float:
    """Standard error of the annualised figure. For iid normal returns the
    relative SE of the sample sd is 1/sqrt(2n)."""
    if r.size < 100:
        return float("nan")
    return ann_vol(r) / math.sqrt(2.0 * r.size)


def kurtosis(x: np.ndarray) -> float:
    if x.size < 100:
        return float("nan")
    m = x.mean()
    s = x.std(ddof=0)
    if s == 0:
        return float("nan")
    return float((((x - m) / s) ** 4).mean())


def kurtosis_se(n: int) -> float:
    return math.sqrt(24.0 / n) if n > 10 else float("nan")


def acf(x: np.ndarray, lag: int) -> float:
    n = x.size
    if n <= lag + 10:
        return float("nan")
    m = x.mean()
    a = x - m
    den = float((a * a).sum())
    if den == 0:
        return float("nan")
    return float((a[:-lag] * a[lag:]).sum() / den)


def variance_ratio(r: np.ndarray, q: int) -> float:
    """Identical to `genvol.py`: non-overlapping q-sums over q times the
    one-period variance. 1.0 is a martingale."""
    n = r.size
    if n < q * 50:
        return float("nan")
    v1 = r.var(ddof=0)
    agg = r[: (n // q) * q].reshape(-1, q).sum(axis=1)
    if agg.size < 30 or v1 == 0:
        return float("nan")
    return float(agg.var(ddof=0) / (q * v1))


def variance_ratio_se(r: np.ndarray, q: int) -> float:
    """SE of the variance ratio from the number of non-overlapping windows.

    For Gaussian increments Var(s^2)/s^4 = 2/k with k windows, so the relative
    SE is sqrt(2/k) - which at q=1000 on 86,410 bars is 15%, and is the reason
    a variance ratio of 4.7 against 4.2 is not a difference.
    """
    k = r.size // q
    if k < 5:
        return float("nan")
    return math.sqrt(2.0 / k)


def parkinson_ratio(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> float:
    ok = (high > 0) & (low > 0) & (close > 0)
    h, lo, c = high[ok], low[ok], close[ok]
    r = np.diff(np.log(c))
    sig_c = float(np.sqrt((r ** 2).mean()))
    rng = np.log(h / lo)
    sig_p = float(math.sqrt((rng ** 2).mean() / (4.0 * math.log(2.0))))
    return sig_p / sig_c if sig_c else float("nan")


def _aggregate_contiguous(ts: np.ndarray, close: np.ndarray, dt: int) -> np.ndarray:
    """`fractal.py`'s aggregator: dt-minute log returns from complete contiguous
    windows only."""
    step = np.diff(ts) == MINUTE_MS
    r = np.log(close[1:] / close[:-1])
    keep = step & np.isfinite(r)
    r, rts = r[keep], ts[1:][keep]
    if r.size < dt * 3:
        return np.array([])
    idx = rts // (dt * MINUTE_MS)
    uniq, first, counts = np.unique(idx, return_index=True, return_counts=True)
    if uniq.size < 3:
        return np.array([])
    sums = np.add.reduceat(r, first)
    return sums[counts == dt]


def hurst(ts: np.ndarray, close: np.ndarray) -> dict:
    """Structure-function H and cascade curvature, the `fractal.py` estimator
    that read H = 0.50 and lambda^2 ~ 0 off the twelve Volatility indices."""
    exps = {}
    used = 0
    for dt in SCALES:
        a = np.abs(_aggregate_contiguous(ts, close, dt))
        if a.size < MIN_WINDOWS:
            continue
        used += 1
        for q in QS:
            s = float((a ** q).mean())
            if s > 0 and math.isfinite(s):
                exps.setdefault(q, []).append((math.log(dt), math.log(s)))
    if used < 5:
        return {"H": float("nan"), "lam2": float("nan"), "scales": used}
    slopes = {}
    for q in QS:
        pts = exps.get(q, [])
        if len(pts) < 5:
            return {"H": float("nan"), "lam2": float("nan"), "scales": used}
        x = np.array([a for a, _ in pts])
        y = np.array([b for _, b in pts])
        slopes[q] = float(np.polyfit(x, y, 1)[0])
    qs = np.array(QS)
    design = np.column_stack([qs, -0.5 * (qs * qs - qs)])
    (h, lam2), *_ = np.linalg.lstsq(design, np.array([slopes[q] for q in QS]), rcond=None)
    return {"H": float(h), "lam2": float(lam2), "scales": used,
            "zeta": {q: slopes[q] for q in QS}}


def runs_z(signs: np.ndarray) -> float:
    """Wald-Wolfowitz, as `genstep.py` wrote it."""
    s = signs[signs != 0]
    n = s.size
    if n < 100:
        return float("nan")
    npos = int((s > 0).sum())
    nneg = n - npos
    if npos == 0 or nneg == 0:
        return float("nan")
    runs = 1 + int((s[1:] != s[:-1]).sum())
    mu = 2.0 * npos * nneg / n + 1.0
    var = (mu - 1) * (mu - 2) / (n - 1)
    return (runs - mu) / math.sqrt(var) if var > 0 else float("nan")


# --------------------------------------------------------- distribution tests --
def ks2(a: np.ndarray, b: np.ndarray, cap: int = 400_000, rng=None):
    """Two-sample Kolmogorov-Smirnov, subsampled to `cap` a side.

    D and its asymptotic p, plus the critical D at alpha = 0.05 for these two
    sizes, so a pass can be read as "the discrepancy is below this" rather than
    as a bare p-value.
    """
    from scipy.stats import ks_2samp
    if rng is not None:
        if a.size > cap:
            a = rng.choice(a, cap, replace=False)
        if b.size > cap:
            b = rng.choice(b, cap, replace=False)
    r = ks_2samp(a, b, method="asymp")
    na, nb = a.size, b.size
    dcrit = 1.3581 * math.sqrt((na + nb) / (na * nb))
    return {"D": float(r.statistic), "p": float(r.pvalue), "n_a": na, "n_b": nb,
            "D_crit_05": dcrit, "reject": bool(r.pvalue < 0.05)}


def ad2(a: np.ndarray, b: np.ndarray, cap: int = 120_000, rng=None):
    """Two-sample Anderson-Darling - weights the tails where KS weights the
    middle, which is the half of the distribution a jump generator lives in."""
    from scipy.stats import anderson_ksamp
    if rng is not None:
        if a.size > cap:
            a = rng.choice(a, cap, replace=False)
        if b.size > cap:
            b = rng.choice(b, cap, replace=False)
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = anderson_ksamp([a, b])
        return {"A2": float(r.statistic), "p": float(r.pvalue),
                "reject": bool(r.pvalue < 0.05)}
    except Exception as exc:  # heavy ties defeat the k-sample form
        return {"A2": float("nan"), "p": float("nan"), "reject": None,
                "error": str(exc)[:80]}


def chi2_hist(a: np.ndarray, b: np.ndarray, nbin: int = 60):
    """Two-sample chi-square on shared quantile bins.

    The right test where KS is compromised by ties - the tick returns of every
    one of these feeds live on a quote lattice.
    """
    from scipy.stats import chi2
    edges = np.unique(np.quantile(a, np.linspace(0, 1, nbin + 1)))
    if edges.size < 5:
        return {"chi2": float("nan"), "df": 0, "p": float("nan"), "reject": None}
    edges[0], edges[-1] = -np.inf, np.inf
    ca = np.histogram(a, edges)[0].astype(float)
    cb = np.histogram(b, edges)[0].astype(float)
    na, nb = ca.sum(), cb.sum()
    tot = ca + cb
    ok = tot > 10
    ca, cb, tot = ca[ok], cb[ok], tot[ok]
    ea = tot * na / (na + nb)
    eb = tot * nb / (na + nb)
    stat = float(((ca - ea) ** 2 / ea).sum() + ((cb - eb) ** 2 / eb).sum())
    df = int(ok.sum()) - 1
    p = float(chi2.sf(stat, df)) if df > 0 else float("nan")
    return {"chi2": stat, "df": df, "p": p, "reject": bool(p < 0.05)}


QQ_P = (0.0001, 0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999, 0.9999)


def qq(a: np.ndarray, b: np.ndarray, probs=QQ_P) -> list[dict]:
    qa = np.quantile(a, probs)
    qb = np.quantile(b, probs)
    out = []
    for p, x, y in zip(probs, qa, qb, strict=False):
        out.append({"p": p, "real": float(x), "sim": float(y),
                    "ratio": float(y / x) if x != 0 else float("nan")})
    return out


def auc_nstar(test: dict, floor: dict, z: float = 1.96) -> float:
    """Rows per class at which a discriminator arm would clear its own floor.

    An arm separates when the test AUC's lower bound clears the floor's upper
    bound. Both are bootstrap intervals on a held-out sample, so their
    half-widths shrink as `1/sqrt(n)` while the gap between the two AUCs does
    not, which gives

        n* = n * (z * (se_test + se_floor) / (auc_test - auc_floor))**2

    Two things this does not claim. The gap is held fixed and in practice it
    *grows* with n, because a boosted ensemble handed more rows finds more - so
    `n*` is an upper bound on the separating sample for this classifier rather
    than an estimate of it. And an arm already at or below its floor returns
    infinity, which means "not separable by this battery", not "identical".
    `rebuildladder.py` section five checks the `1/sqrt(n)` half empirically.
    """
    if not test or not floor or test.get("skipped") or floor.get("skipped"):
        return float("nan")
    if "lo" not in test or "lo" not in floor:
        return float("nan")
    delta = test["auc"] - floor["auc"]
    if delta <= 0:
        return float("inf")
    se = (test["hi"] - test["lo"]) / (2 * z) + (floor["hi"] - floor["lo"]) / (2 * z)
    return float(test["n"] * (z * se / delta) ** 2)


def nstar(d: float, alpha_c: float = 1.3581) -> float:
    """Sample size at which a two-sample KS at alpha = 0.05 separates two
    distributions whose true sup-distance is `D`.

    Equal-sized samples reject when `D > c*sqrt(2/n)`, so `n* = 2c^2/D^2`. This
    is the number the whole study reduces to: it turns "indistinguishable" into
    "indistinguishable below n, separable above it".
    """
    if not (d > 0) or not math.isfinite(d):
        return float("inf")
    return 2.0 * (alpha_c ** 2) / (d ** 2)


def spread_across(vals) -> dict:
    v = np.array([x for x in vals if not (isinstance(x, float) and math.isnan(x))],
                 dtype=float)
    if v.size == 0:
        return {"mean": float("nan"), "sd": float("nan"), "min": float("nan"),
                "max": float("nan"), "n": 0}
    return {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if v.size > 1 else 0.0,
            "min": float(v.min()), "max": float(v.max()), "n": int(v.size)}


def exactly_null(value: float, null: float, places: int = 6) -> bool:
    """`research/README.md`'s dead-column check: a statistic landing on exactly
    its null to `places` decimals is a constant column until proved otherwise."""
    return (not math.isnan(value)) and round(value, places) == round(null, places)


def machine() -> str:
    try:
        return f"{os.cpu_count()} cores"
    except Exception:
        return "unknown"


# ------------------------------------------------------------ discrimination --
#: The strongest statement a rebuild can earn is that nothing can tell it from
#: the feed, so the primary criterion here is an adversarial one: train the best
#: classifier available on real-against-rebuilt and read its held-out AUC. That
#: number is meaningless on its own - it has to be read against the AUC the same
#: pipeline scores on real-against-*real*, which is the floor this data actually
#: supports. Everything below is that machinery.
#:
#: There is no scikit-learn in this environment, so the learner is a small
#: histogram gradient-boosted tree ensemble written here: quantile-binned
#: features, depth-limited trees, second-order (Newton) leaf weights. It is the
#: XGBoost/LightGBM core and nothing more. Its power is not asserted - every
#: study that uses it runs it against deliberately wrong generators first, and
#: reports what it caught.

def _quantile_bins(x: np.ndarray, nbins: int) -> np.ndarray:
    qs = np.quantile(x, np.linspace(0.0, 1.0, nbins + 1)[1:-1])
    return np.unique(qs)


class _Booster:
    """Histogram gradient boosting for binary logistic loss."""

    def __init__(self, n_trees=150, depth=3, lr=0.1, nbins=32, min_leaf=20,
                 l2=1.0, subsample=0.8, seed=0):
        self.n_trees, self.depth, self.lr = n_trees, depth, lr
        self.nbins, self.min_leaf, self.l2 = nbins, min_leaf, l2
        self.subsample = subsample
        self.rng = np.random.default_rng(seed)
        self.edges: list[np.ndarray] = []
        self.trees: list[list] = []
        self.base = 0.0
        self.gain = None

    def _bin(self, x: np.ndarray, fit: bool) -> np.ndarray:
        if fit:
            self.edges = [_quantile_bins(x[:, j], self.nbins) for j in range(x.shape[1])]
        out = np.empty(x.shape, dtype=np.int16)
        for j in range(x.shape[1]):
            out[:, j] = np.searchsorted(self.edges[j], x[:, j], side="left")
        return out

    def _grow(self, xb, g, h, rows, depth):
        """One node: pick the split with the best second-order gain, recurse."""
        gs, hs = g[rows].sum(), h[rows].sum()
        if depth == 0 or rows.size < 2 * self.min_leaf:
            return ("leaf", -gs / (hs + self.l2))
        best = None
        parent = gs * gs / (hs + self.l2)
        for j in range(xb.shape[1]):
            b = xb[rows, j]
            nb = int(self.edges[j].size) + 1
            gh = np.bincount(b, weights=g[rows], minlength=nb)
            hh = np.bincount(b, weights=h[rows], minlength=nb)
            cnt = np.bincount(b, minlength=nb)
            gl, hl, cl = np.cumsum(gh), np.cumsum(hh), np.cumsum(cnt)
            gr, hr, cr = gs - gl, hs - hl, rows.size - cl
            ok = (cl >= self.min_leaf) & (cr >= self.min_leaf)
            if not ok.any():
                continue
            gain = gl * gl / (hl + self.l2) + gr * gr / (hr + self.l2) - parent
            gain = np.where(ok, gain, -np.inf)
            k = int(np.argmax(gain))
            if best is None or gain[k] > best[0]:
                best = (float(gain[k]), j, k)
        if best is None or best[0] <= 1e-9:
            return ("leaf", -gs / (hs + self.l2))
        _gain, j, k = best
        self.gain[j] += _gain
        left = rows[xb[rows, j] <= k]
        right = rows[xb[rows, j] > k]
        return ("split", j, k, self._grow(xb, g, h, left, depth - 1),
                self._grow(xb, g, h, right, depth - 1))

    @staticmethod
    def _apply(node, xb, rows, out):
        if node[0] == "leaf":
            out[rows] = node[1]
            return
        _, j, k, lt, rt = node
        m = xb[rows, j] <= k
        _Booster._apply(lt, xb, rows[m], out)
        _Booster._apply(rt, xb, rows[~m], out)

    def fit(self, x, y):
        xb = self._bin(x, fit=True)
        self.gain = np.zeros(x.shape[1])
        p = float(y.mean())
        p = min(max(p, 1e-6), 1 - 1e-6)
        self.base = math.log(p / (1 - p))
        f = np.full(x.shape[0], self.base)
        n = x.shape[0]
        for _ in range(self.n_trees):
            pr = 1.0 / (1.0 + np.exp(-f))
            g = pr - y
            h = np.maximum(pr * (1 - pr), 1e-6)
            rows = np.arange(n)
            if self.subsample < 1.0:
                rows = rows[self.rng.random(n) < self.subsample]
            tree = self._grow(xb, g, h, rows, self.depth)
            step = np.zeros(n)
            self._apply(tree, xb, np.arange(n), step)
            f += self.lr * step
            self.trees.append(tree)
        return self

    def decision(self, x):
        xb = self._bin(x, fit=False)
        f = np.full(x.shape[0], self.base)
        for tree in self.trees:
            step = np.zeros(x.shape[0])
            self._apply(tree, xb, np.arange(x.shape[0]), step)
            f += self.lr * step
        return f


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Mann-Whitney AUC, ties counted at a half."""
    n1 = int(label.sum())
    n0 = label.size - n1
    if n0 == 0 or n1 == 0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(score.size, dtype=float)
    s = score[order]
    i = 0
    while i < s.size:
        j = i
        while j + 1 < s.size and s[j + 1] == s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[label == 1].sum() - n1 * (n1 + 1) / 2.0) / (n0 * n1))


def discriminate(xa: np.ndarray, xb: np.ndarray, names: list[str], seed: int = 0,
                 block: int = 64, boots: int = 400, **kw) -> dict:
    """Can a classifier tell sample A from sample B?

    Rows are assigned to train and test in alternating *blocks* rather than at
    random, so that anything shared between neighbouring rows - a slow drift, a
    window overlap - cannot leak across the split. Classes are balanced by
    truncation, because an AUC on unbalanced classes is partly the prior.

    Returns the held-out AUC with a bootstrap interval, the same AUC for a plain
    logistic regression on the standardised features, and the per-feature
    univariate AUC, which is the diagnostic that says *what* separates rather
    than *whether*.
    """
    n = min(xa.shape[0], xb.shape[0])
    if n < 200:
        return {"n": n, "auc": float("nan"), "error": "too few rows"}
    xa, xb = xa[:n], xb[:n]
    x = np.vstack([xa, xb])
    y = np.concatenate([np.zeros(n), np.ones(n)])
    blk = (np.arange(n) // block) % 2
    test = np.concatenate([blk == 1, blk == 1])
    train = ~test
    # A window whose scale is degenerate - a Step Index window of sixty identical
    # magnitudes, say - makes a ratio feature enormous. Clipping keeps the tree
    # splits (which are rank-based anyway) and stops the standardised linear
    # baseline overflowing.
    x = np.clip(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0), -1e12, 1e12)
    model = _Booster(seed=seed, **kw).fit(x[train], y[train])
    s = model.decision(x[test])
    yt = y[test]
    a = auc(s, yt)
    rng = np.random.default_rng(seed + 1)
    idx = np.arange(s.size)
    boot = []
    for _ in range(boots):
        take = rng.choice(idx, idx.size, replace=True)
        v = auc(s[take], yt[take])
        if v == v:
            boot.append(v)
    lo, hi = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))) \
        if boot else (float("nan"), float("nan"))
    # a linear baseline, so a tree ensemble's advantage can be read
    mu, sd = x[train].mean(axis=0), x[train].std(axis=0) + 1e-12
    zs = (x - mu) / sd
    w = np.zeros(x.shape[1])
    b = 0.0
    for _ in range(200):
        f = zs[train] @ w + b
        p = 1.0 / (1.0 + np.exp(-f))
        gr = zs[train].T @ (p - y[train]) / train.sum() + 1e-3 * w
        gb = float((p - y[train]).mean())
        w -= 0.5 * gr
        b -= 0.5 * gb
    lin = auc(zs[test] @ w + b, yt)
    uni = []
    for j, nm in enumerate(names):
        uni.append((nm, auc(x[test][:, j], yt)))
    uni.sort(key=lambda t: -abs(t[1] - 0.5))
    return {"n": int(n), "n_test": int(test.sum()), "auc": a, "lo": lo, "hi": hi,
            "auc_linear": lin,
            "gain": {names[j]: float(model.gain[j]) for j in range(len(names))},
            "univariate": uni}
