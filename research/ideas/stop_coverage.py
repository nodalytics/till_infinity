"""Does a stop at a measured quantile deliver the coverage it claims?

A stop distance is a claim about a tail - *price will not run this far against
me before this trade resolves, with probability `tau`* - and the only honest
test is whether that happens. `till_infinity/risk/quantiles.py` ships the
estimator and its self-checks; this measures it on real bars, against the stop
the desk actually places.

## The question is calibration, not edge

Unusual for this folder. Almost everything here asks whether something
predicts and the answer is no. This asks whether a **stated probability is
delivered**, which can succeed - and a well-calibrated stop is worth having
even where direction is closed, which `the-walk-is-the-best-calibrated-band`
says it is.

## Four arms the desk can actually choose between, and one the baseline needs

`vol-3` is the incumbent: `Intent.stop_vol` runs at a measured median of 3.0
volatility units. `vol-3-N20` adds `smc_bos_c_L50|M15|N20`'s floor of 20
spreads, which at 15m is **7.78 units on eurusd and 5.89 on gbpusd** - so the
floored incumbent is a different stop, not a rounding of the same one, and at
1d it is 0.078-0.535 units and cannot bind at all. `t-fixed` is
`student_stop(0.90, 4.0)` = 1.5105. `quantile` is the online estimator.

**`t-sqrt-h` is a fifth arm and the baseline is entitled to it.**
`student_stop` carries no horizon, so at `H` bars it is a one-bar quantity
answering a twenty-bar question. Under diffusive scaling the reflection
principle gives `P(min_H <= -a) = 2 Phi(-a / (sigma sqrt(H)))`, so `sqrt(H)` is
the correction, and "the empirical beats the fixed t at H = 20" without it is a
statement about a missing square root rather than about any market.

## The unit is the one production divides by

`statespace/deciding.py` computes `unit = vol_bps / 1e4 * entry` and `risk =
stop_vol * unit`, where `vol_bps` is a per-bar **return sigma**. So the unit
here is an EWMA of squared log close-to-close returns, as a sigma, at
`surrogates.EWMA_LAMBDA` = 0.94. An EWMA bar *range* would be a different
quantity - 1.015x this on eurusd and **0.755x on gold** - and putting the stop
and the excursion in two units is how both readings look fine. The Parkinson
range estimator of the same sigma is carried as a second unit for exactly that
reason; `drive-q-from-the-range` is why it is a serious alternative rather than
a straw man.

## Why the online estimator may lose for a reason that is not about markets

`GAIN` 0.02 is an **absolute** step in volatility units, so the number of
observations needed to reach a quantile is proportional to that quantile's
size. At `H` = 20 the empirical 0.90 excursion quantile is 7-9 units and the
estimator starts at 1.51, so it needs about `(8 - 1.51) / (0.02 * 0.90)` = 360
consecutive exceedances to arrive - more than the 250 non-overlapping anchors
19 years of daily bars provide. That is a property of the step rule, not of the
data, so two things are reported rather than one: `quantile` as it ships, and
`quantile-seated`, the same object started at `t-sqrt-h` instead of at
`student_stop`. `Quantile.stop`'s own docstring says it starts at the baseline
"because that is a measured, well-calibrated starting point"; at `H` > 1 the
measured well-calibrated starting point is `sqrt(H)` times larger.
`rate_late`, the coverage over the second half of each stream, separates "not
converged" from "miscalibrated".

## What is not measured here

Nothing on the 1d panel is priced - coverage is a hit rate in volatility units
and needs no spread. Anything priced comes from the six feeds with recorded
quotes at 15m, on the venue the quotes were measured on, and `us100` and
`spx500` are **not the venue the live desk trades**. No spread is invented.
"""

import hashlib
import math
import random
import sqlite3
import statistics as st
from dataclasses import dataclass

import numpy as np

import research.ideas.level_shield as L
from till_infinity.risk.quantiles import DOF, TAU, Coverage, Quantile, affordable, student_stop

#: The price store, read-only. Relative so the study runs wherever the repo is.
STORE = "file:.data/prices/prices.db?mode=ro"

#: The 1d panel: eight FX feeds plus gold. Venue by bar count, ties
#: alphabetically - `level_shield.venue_for`, a data-volume rule fixed before
#: any result rather than a venue that read better. Nothing here is priced, so
#: a feed without recorded quotes is admissible; `corpus.py` refuses to guess
#: a spread and so does this.
FEEDS_1D = (
    "eurusd",
    "gbpusd",
    "audusd",
    "nzdusd",
    "usdcad",
    "usdchf",
    "usdjpy",
    "usdcnh",
    "gold",
)

#: The six feeds with enough recorded quotes to measure a median spread, and
#: **the venue the quotes were measured on**, which is where the bars come from
#: too. `venue_for` would pick FOREXCOM for eurusd 15m - one bar more than
#: DERIV - whose measured spread is 0.17 bps against DERIV's 1.04, a sixfold
#: cost difference for a one-bar data gain. The same instrument runs 0.17 to
#: 3.30 bps across venues, so a spread is never read off another venue.
#:
#: **`us100` and `spx500` are not the venue the live desk trades.** Every
#: priced number on them is labelled so rather than quietly pooled with the
#: four DERIV feeds.
COSTED: dict[str, str] = {
    "eurusd": "DERIV",
    "gbpusd": "DERIV",
    "gold": "DERIV",
    "btc": "DERIV",
    "us100": "FOREXCOM",
    "spx500": "PEPPERSTONE",
}

#: Venues the live desk actually trades, for labelling the priced rows.
LIVE_VENUES = frozenset({"DERIV"})

#: Horizons in bars. **Primary 20**, at both intervals: in bars a horizon is
#: interval-independent (`indicators/levels.FORGET_BARS` makes the same
#: argument), 20 is `level_shield.SETTINGS["1d"]["horizon"]` so it is not a new
#: number, and it is the only value in the sweep leaving 250 non-overlapping
#: anchors per side per feed on **both** intervals - the live rule's 96-bar
#: hold leaves 53 at 15m, where 76 days is all the store has.
#:
#: `level-bounce.md` measured departures with no characteristic length - S(8)
#: above the hardest null in 0 of 167 cells - so there is nothing to inherit
#: and the horizon has to be declared and swept. 96 is the live hold exactly
#: (96 M15 bars = 24 hours); 1 is the reproduction arm.
HORIZON = 20
HORIZONS = (1, 5, 20, 48, 96)

#: Bars before the first anchor. The EWMA needs its span, and a stop set off a
#: variance that is still its own initial value is not the stop under test.
WARMUP = 200

#: Most anchors a non-overlapping stream may carry, as an **evenly spaced**
#: subsample so it still spans the whole history.
#:
#: Two reasons, one scientific and one measured. The horizon sweep otherwise
#: compares a 4,801-trade stream at `H` = 1 with a 51-trade one at `H` = 96,
#: which confounds the horizon with how long the online estimator had to
#: converge - and convergence is the thing under test. And `Quantile.observe`
#: costs **1.5 ms a call**: `_side` passes `dict.setdefault` an eagerly built
#: default, so `student_stop`'s scipy `t.ppf` (629 us, measured) runs on every
#: observation rather than on the first, twice over. 500 keeps every horizon
#: in one order of magnitude of trade count and the panel inside a few
#: minutes. The **primary horizon is 240-256 anchors and is not capped**, so
#: nothing in the verdict is subsampled; the dense stream is uncapped and
#: carries the full-sample precision for the fixed arms.
ONLINE_CAP = 500

#: EWMA decay for the unit. `node/surrogates.EWMA_LAMBDA`, so the surrogate and
#: the unit are the same estimator rather than two models of one thing.
LAMBDA = 0.94

#: Range-to-sigma for the second unit estimator: Parkinson's constant, so
#: `log(high / low) / (2 sqrt(ln 2))` is an estimator of the same per-bar
#: return sigma as the close-to-close EWMA and not of a different quantity.
PARKINSON = 2.0 * math.sqrt(math.log(2.0))

#: The incumbent stop, in volatility units. Measured: `Intent.stop_vol` runs at
#: a median of 3.0 on the live book.
INCUMBENT = 3.0

#: Spreads the floored incumbent must clear - the `N20` in
#: `smc_bos_c_L50|M15|N20|time`, from `strategies/structure.SPREADS`.
N20 = 20.0

#: Reward to risk the secondary mean-R reading is solved for.
#: `statespace/deciding.TARGET_R`.
TARGET_R = 2.0

#: Gains swept for the online estimator. 0.02 is what ships
#: (`quantiles.GAIN`); the rest are here because the step is **absolute**, so
#: the time to reach a quantile grows with the quantile. Reported as a grid on
#: the mean, never as the best cell with its z - `sweep-thresholds-on-the-mean-
#: not-z` is the recorded failure, where a z grid faked a ridge at the chosen
#: threshold and the mean grid was monotone.
GAINS = (0.02, 0.05, 0.10, 0.20)

#: Null draws per arm. **Sixteen, not four.** `fear-greed.md` measured a
#: hardest-of-N test at four draws to be anti-conservative on an arm whose own
#: sd is 0.09-0.12: two cells read +0.093 and +0.047 at four draws and -0.037
#: and +0.021 at sixteen.
DRAWS = 16

#: Plant strengths. Each sweep starts at its own zero control, and a plant
#: whose zero cell reads an effect is rejected rather than reported -
#: `level-bounce.md`'s pure-order plant failed exactly that way at z -4.76.
DRIFTS = (0.0, 0.02, 0.05, 0.10, 0.20)
ASYMS = (1.0, 1.1, 1.2, 1.3, 1.5)
SCALES = (1.0, 2.0, 10.0)


def seed_for(*parts: object) -> int:
    """A reproducible seed from the cell's own identity.

    `hash()` of a tuple holding a string is salted by `PYTHONHASHSEED`, so a
    surrogate seeded from one differs in every process. `fear-greed.md`
    measured the consequence rather than guessing it: a panel's `bar-shuffle`
    arm read -0.266 where a local run on the same code and data read -0.172,
    while every real value matched to the digit. A surrogate range that moves
    between runs cannot be what a verdict is scored against.
    """
    text = "|".join(repr(x) for x in parts)
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


# ─────────────────────────────── the data ───────────────────────────────


def load(con, feed: str, interval: str, venue: str | None = None) -> L.Series | None:
    """Bars for one feed at one interval, on a named venue or the fullest one.

    `level_shield.Series` rather than a local type, so this harness and the
    null arms cannot disagree about what a series is.
    """
    venue = venue or L.venue_for(con, feed, interval)
    if venue is None:
        return None
    rows = con.execute(
        "select ts, open, high, low, close from bars where feed=? and venue=? "
        "and interval=? and closed=1 order by ts",
        (feed, venue, interval),
    ).fetchall()
    if len(rows) < WARMUP + 2 * max(HORIZONS):
        return None
    arr = np.asarray(rows, dtype=float)
    return L.Series(
        feed=feed,
        venue=venue,
        interval=interval,
        ts=arr[:, 0],
        open=arr[:, 1],
        high=arr[:, 2],
        low=arr[:, 3],
        close=arr[:, 4],
    )


def spread_bps(con, feed: str, venue: str) -> float:
    """The median recorded spread for this feed on this venue, in bps.

    `node/corpus.spread_bps` by the same query, per venue and never pooled.
    Returns 0.0 where there are no quotes, which is how a feed ends up
    geometry-only rather than priced off a guess.
    """
    rows = con.execute(
        "select bid, ask from quotes where feed=? and venue=? and bid>0 and ask>bid",
        (feed, venue),
    ).fetchall()
    if not rows:
        return 0.0
    return st.median((ask - bid) / ((ask + bid) / 2.0) * 1e4 for bid, ask in rows)


# ─────────────────────────────── the unit ───────────────────────────────


def returns(series: L.Series) -> np.ndarray:
    """Log close-to-close returns, with a leading zero so indices line up."""
    logc = np.log(np.maximum(series.close, 1e-12))
    out = np.empty(len(logc))
    out[0] = 0.0
    out[1:] = np.diff(logc)
    return out


def sigma_close(series: L.Series, lam: float = LAMBDA) -> np.ndarray:
    """Causal EWMA of squared log returns, as a per-bar sigma.

    **The unit production divides by.** `deciding.py` computes `unit = vol_bps
    / 1e4 * entry` with `vol_bps` a folded log variance in basis points, so the
    incumbent's `stop_vol` 3.0 is three of *this*. `sigma[i]` uses returns
    strictly before bar `i`, so a stop set from it at bar `i` is causal - the
    whole study is a one-step-ahead claim and an in-sample sigma would make the
    coverage unreadable.
    """
    r = returns(series)
    out = np.empty(len(r))
    var = float(np.var(r[1 : WARMUP + 1])) or 1e-12
    for i in range(len(r)):
        out[i] = math.sqrt(max(var, 1e-24))
        var = lam * var + (1.0 - lam) * r[i] * r[i]
    return out


def sigma_range(series: L.Series, lam: float = LAMBDA) -> np.ndarray:
    """The same sigma, estimated from the bar range instead of the close.

    Parkinson: `log(high / low) / (2 sqrt(ln 2))` is an estimator of the
    per-bar return sigma, so this is a second estimator of **one** quantity
    rather than a different quantity. `drive-q-from-the-range` is why it is
    carried - the range-vs-close estimator ratio holds within strata on FX and
    on 371 of 392 equities - and the measured 0.755 gap on gold against 1.015
    on eurusd is why a coverage reading has to be shown not to depend on it.
    """
    span = np.log(np.maximum(series.high, 1e-12) / np.maximum(series.low, 1e-12)) / PARKINSON
    out = np.empty(len(span))
    var = float(np.mean(span[:WARMUP] ** 2)) or 1e-12
    for i in range(len(span)):
        out[i] = math.sqrt(max(var, 1e-24))
        var = lam * var + (1.0 - lam) * span[i] * span[i]
    return out


UNITS = {"close": sigma_close, "range": sigma_range}


# ───────────────────────────── the excursion ─────────────────────────────


@dataclass(frozen=True, slots=True)
class Excursions:
    """Adverse excursions at every anchor, per side, in volatility units.

    `up` is adverse for a short (`side` -1) and `dn` for a long (`side` +1).
    `clamped` counts the anchors where the raw value came out negative - price
    gapped away from the entry and never traded back through it inside the
    window. Those are real outcomes and go in as zeros, which is what
    `Quantile.observe` accepts and why it refuses a negative one; the count is
    reported because a cell where it is common is a cell where the entry is not
    where this study thinks it is.
    """

    anchors: np.ndarray
    dn: np.ndarray
    up: np.ndarray
    day: np.ndarray
    clamped_dn: int
    clamped_up: int
    #: Consecutive anchors whose windows overlap, which is the bootstrap block.
    #: `horizon / step`, floored at one calendar day's worth of anchors because
    #: trades cluster in days as well as in windows.
    block: int

    def side(self, side: int) -> np.ndarray:
        return self.dn if side > 0 else self.up

    def clamped(self, side: int) -> int:
        return self.clamped_dn if side > 0 else self.clamped_up


def excursions(
    series: L.Series,
    sigma: np.ndarray,
    horizon: int,
    *,
    step: int | None = None,
    cap: int | None = None,
) -> Excursions:
    """Adverse excursion over `horizon` bars at each anchor, both sides.

    In logs, so a stop is a fraction of price and gold at 4,000 and eurusd at
    1.08 are the same quantity. Divided by `sigma[t]`, which is causal, so the
    stop is fixed before the window opens.

    **`step` defaults to the horizon, which is the non-overlapping stream and
    the headline.** At step 1 the window at `t+1` shares `horizon - 1` of its
    bars with the window at `t`, so an online estimator updated on `t` before
    setting `t+1`'s stop has seen most of the outcome it is about to be scored
    on. `overlapping-outcome-windows-leak` is the recorded case: a short skip
    rule with a long forward window gave direction AUC 0.79 that collapsed to
    0.51, and the tell was the placebo arm tracking it.

    `cap` thins the anchors by an even stride rather than truncating them. A
    truncation would hand `H` = 1 its oldest 500 bars - a single regime out of
    nineteen years - and a stride keeps the span while keeping the windows
    disjoint, because a stride larger than one only moves them further apart.
    """
    step = horizon if step is None else step
    logc = np.log(np.maximum(series.close, 1e-12))
    logl = np.log(np.maximum(series.low, 1e-12))
    logh = np.log(np.maximum(series.high, 1e-12))
    n = len(logc)
    reach = n - horizon
    if reach <= WARMUP:
        empty = np.zeros(0)
        return Excursions(
            np.zeros(0, dtype=np.int64), empty, empty, np.zeros(0, dtype=np.int64), 0, 0, 1
        )
    windows_low = np.lib.stride_tricks.sliding_window_view(logl[1:], horizon)[:reach]
    windows_high = np.lib.stride_tricks.sliding_window_view(logh[1:], horizon)[:reach]
    anchors = np.arange(WARMUP, reach, step, dtype=np.int64)
    if cap is not None and len(anchors) > cap:
        anchors = anchors[:: -(-len(anchors) // cap)]
    scale = np.maximum(sigma[anchors], 1e-24)
    raw_dn = (logc[anchors] - windows_low[anchors].min(axis=1)) / scale
    raw_up = (windows_high[anchors].max(axis=1) - logc[anchors]) / scale
    day = (series.ts[anchors] // 86_400).astype(np.int64)
    per_day = -(-len(anchors) // max(1, len(np.unique(day))))
    return Excursions(
        anchors=anchors,
        dn=np.maximum(raw_dn, 0.0),
        up=np.maximum(raw_up, 0.0),
        day=day,
        clamped_dn=int((raw_dn < 0.0).sum()),
        clamped_up=int((raw_up < 0.0).sum()),
        block=max(1, -(-horizon // step), per_day),
    )


# ──────────────────────────────── the arms ────────────────────────────────


@dataclass(frozen=True, slots=True)
class Reading:
    """One stop arm on one side of one series: the coverage it delivered.

    `excess` is `Coverage.excess`, signed so the direction of the correction is
    visible - **positive means the stop is too tight**. `rate_late` is the hit
    rate over the second half of the stream, which separates an online
    estimator that has not converged from one that is miscalibrated.
    """

    arm: str
    side: int
    n: int
    hits: int
    rate: float
    excess: float
    enough: bool
    calibrated: bool
    stop_median: float
    stop_first: float
    stop_last: float
    rate_late: float
    binds: float
    afford: str
    #: Block bootstrap sd of `rate`, in blocks of the overlap length. The
    #: honest interval on the dense stream, where a binomial one assumes rows
    #: that share 95 of 96 bars are independent.
    sd_block: float


def block_sd(hit: np.ndarray, block: int, *, draws: int = 200, seed: int = 0) -> float:
    """Block bootstrap sd of the hit rate, in blocks of `block` anchors.

    **The interval an overlapping stream needs and a binomial one cannot
    give.** Overlapping anchors share most of their window, so a binomial
    interval over them is far too narrow:
    `overlapping-windows-inflate-permutation-nulls` is the recorded failure,
    where a level finding at p 0.015 was anchor overlap and the tell was the
    no-level control passing too.

    **The block is the overlap length in anchors, not a calendar day, and that
    correction was measured here rather than reasoned about.** A day-block
    bootstrap is the habit in this folder and it is right at 15m, where a day
    holds 96 bars - but on **daily** bars a calendar day holds exactly one
    anchor, so grouping by day leaves every block a single row and the
    bootstrap becomes an ordinary one over rows that are not independent. On a
    48-bar dense stream it read 1.35x the binomial sd where it should read
    several times it. `level_shield.race` groups by calendar day for the same
    purpose and inherits the same limitation on its 1d panel.

    Resampled as per-block `(hits, count)` pairs rather than by concatenating
    rows, so the cost does not grow with the block size.
    """
    if not len(hit) or block < 1:
        return 0.0
    starts = np.arange(0, len(hit), block)
    sums = np.add.reduceat(hit.astype(float), starts)
    counts = np.diff(np.append(starts, len(hit))).astype(float)
    if len(starts) < 2:
        return 0.0
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(starts), size=(draws, len(starts)))
    rates = sums[pick].sum(axis=1) / np.maximum(counts[pick].sum(axis=1), 1e-12)
    return float(np.std(rates))


def calibrated(rate: float, n: int, tau: float = TAU, sd_block: float = 0.0) -> bool:
    """Whether the realised rate's 95% interval holds `1 - tau`.

    Pre-registered as the binomial interval and n-aware on purpose: at n = 250
    and a target of 0.10 that is +-0.037, so a fixed tolerance would call the
    same reading calibrated on one panel and not on another.

    **The wider of the binomial and the block-bootstrap interval**, which is a
    correction to the pre-registration rather than the rule as written. A
    binomial interval assumes independent rows, and on the dense stream they
    share most of a window - at `H` = 96 and step 1, 95 of 96 bars - so the
    binomial interval there is a number that describes a sample this study does
    not have. Recorded in the Deviations section.
    """
    if n <= 0:
        return False
    target = 1.0 - tau
    sd = max(math.sqrt(target * (1.0 - target) / n), sd_block)
    return abs(rate - target) <= 1.96 * sd


def _reading(
    arm: str,
    side: int,
    exc: np.ndarray,
    stops: np.ndarray,
    *,
    tau: float,
    spread_vol: float,
    binds: float = 0.0,
    block: int = 1,
) -> Reading:
    """Score an array of excursions against the stop that was set for each."""
    hit = exc >= stops
    n = len(exc)
    half = n // 2
    cover = Coverage(target=tau, hits=int(hit.sum()), n=n)
    sd_block = block_sd(hit, block, seed=seed_for(arm, side) % 2**31)
    return Reading(
        arm=arm,
        side=side,
        n=n,
        hits=cover.hits,
        rate=cover.rate,
        excess=cover.excess,
        enough=cover.enough,
        calibrated=calibrated(cover.rate, n, tau, sd_block),
        stop_median=float(np.median(stops)) if n else 0.0,
        stop_first=float(stops[0]) if n else 0.0,
        stop_last=float(stops[-1]) if n else 0.0,
        rate_late=float(hit[half:].mean()) if n - half else 0.0,
        binds=binds,
        afford=affordable(float(np.median(stops)) if n else 0.0, spread_vol),
        sd_block=sd_block,
    )


def fixed_arms(
    exc: Excursions,
    horizon: int,
    *,
    side: int,
    spread_vol: np.ndarray | None,
    tau: float = TAU,
    dof: float = DOF,
) -> list[Reading]:
    """The arms whose stop does not depend on anything that happened.

    `vol-3-N20` is omitted where there is no measured spread rather than
    computed off a guessed one, which is the one result that looks like a
    measurement and is not.
    """
    values = exc.side(side)
    n = len(values)
    out = [
        _reading(
            "vol-3",
            side,
            values,
            np.full(n, INCUMBENT),
            tau=tau,
            spread_vol=_median_or_zero(spread_vol, exc.anchors),
            block=exc.block,
        ),
        _reading(
            "t-fixed",
            side,
            values,
            np.full(n, student_stop(tau, dof)),
            tau=tau,
            spread_vol=_median_or_zero(spread_vol, exc.anchors),
            block=exc.block,
        ),
        _reading(
            "t-sqrt-h",
            side,
            values,
            np.full(n, student_stop(tau, dof) * math.sqrt(horizon)),
            tau=tau,
            spread_vol=_median_or_zero(spread_vol, exc.anchors),
            block=exc.block,
        ),
    ]
    if spread_vol is not None:
        floor = N20 * spread_vol[exc.anchors]
        stops = np.maximum(INCUMBENT, floor)
        out.append(
            _reading(
                "vol-3-N20",
                side,
                values,
                stops,
                tau=tau,
                spread_vol=_median_or_zero(spread_vol, exc.anchors),
                binds=float((floor > INCUMBENT).mean()) if n else 0.0,
                block=exc.block,
            )
        )
    return out


def _median_or_zero(spread_vol: np.ndarray | None, anchors: np.ndarray) -> float:
    if spread_vol is None or not len(anchors):
        return 0.0
    return float(np.median(spread_vol[anchors]))


def online_arm(
    exc: Excursions,
    horizon: int,
    *,
    side: int,
    name: str,
    seated: bool,
    gain: float,
    spread_vol: np.ndarray | None,
    tau: float = TAU,
    dof: float = DOF,
) -> Reading:
    """`risk.quantiles.Quantile`, scored one step ahead through its own API.

    The order is the whole point and is asserted in the tests: read
    `stop(side)`, score the excursion against the distance that was read, then
    `observe(side, excursion)`. `observe` scores before it steps, so the
    coverage it reports is one-step-ahead by construction; this harness must
    not hand it an excursion it has already used to set a stop, and it does not
    - one anchor, one read, one observe.

    `seated` starts the estimate at `t-sqrt-h` rather than at `student_stop`.
    **Not a tuning knob - a fix for a convergence budget.** `GAIN` is an
    absolute step, so reaching a quantile of size `q` from 1.51 takes about
    `(q - 1.51) / (gain * tau)` exceedances: at `H` = 20, where the empirical
    quantile is 7-9 units, that is around 360 and the non-overlapping stream
    has 250. `Quantile.stop`'s docstring starts the estimator at the baseline
    "because that is a measured, well-calibrated starting point"; at `H` > 1
    the measured well-calibrated starting point is `sqrt(H)` times larger.
    """
    found = Quantile(tau=tau, gain=gain, dof=dof)
    if seated:
        found.state[side] = {
            "q": student_stop(tau, dof) * math.sqrt(horizon),
            "hits": 0.0,
            "flat": 0.0,
            "n": 0.0,
        }
    values = exc.side(side)
    stops = np.empty(len(values))
    for i, value in enumerate(values):
        stops[i] = found.stop(side)
        found.observe(side, float(value))
    return _reading(
        name,
        side,
        values,
        stops,
        tau=tau,
        spread_vol=_median_or_zero(spread_vol, exc.anchors),
        block=exc.block,
    )


def all_arms(
    exc: Excursions,
    horizon: int,
    *,
    spread_vol: np.ndarray | None,
    tau: float = TAU,
    dof: float = DOF,
    gain: float = 0.02,
) -> list[Reading]:
    """Every arm, both sides. Per side always - a pooled stop is a sixth arm."""
    out: list[Reading] = []
    for side in (1, -1):
        out.extend(
            fixed_arms(exc, horizon, side=side, spread_vol=spread_vol, tau=tau, dof=dof)
        )
        for name, seated in (("quantile", False), ("quantile-seated", True)):
            out.append(
                online_arm(
                    exc,
                    horizon,
                    side=side,
                    name=name,
                    seated=seated,
                    gain=gain,
                    spread_vol=spread_vol,
                    tau=tau,
                    dof=dof,
                )
            )
    return out


def side_ratio(readings: list[Reading], arm: str) -> float | None:
    """`stop(-1) / stop(+1)` for one arm: the per-side asymmetry it learned.

    **The statistic that decides whether anything adaptive is needed at all.**
    `fear-greed.md` measured down moves faster and deeper than up moves, stable
    across 6 of 6 eras - and the module's own tests show the fixed t only loses
    where a side's scale differs, at 1.3x. This is the measurement of that
    factor, and it is compared against the null arms rather than against 1.0,
    because a one-sided drift produces it with no asymmetry in the volatility
    at all.
    """
    up = next((r.stop_median for r in readings if r.arm == arm and r.side == -1), None)
    dn = next((r.stop_median for r in readings if r.arm == arm and r.side == 1), None)
    if up is None or dn is None or dn <= 0.0:
        return None
    return up / dn


# ──────────────────────────────── the plants ────────────────────────────────


def _rebuild(series: L.Series, logret: np.ndarray, geometry: np.ndarray) -> L.Series:
    """A series with a new close path and each bar's own shape, in logs.

    `geometry` is `(n, 3)` of `log(open/close)`, `log(high/close)`,
    `log(low/close)` - each bar's shape as multiplicative offsets from its own
    close, so a plant that moves the path keeps the wickiness and a plant that
    scales a bar scales all of it.
    """
    logc = np.log(max(float(series.close[0]), 1e-12)) + np.cumsum(logret)
    close = np.exp(logc)
    return L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=close * np.exp(geometry[:, 0]),
        high=close * np.exp(geometry[:, 1]),
        low=close * np.exp(geometry[:, 2]),
        close=close,
    )


def geometry_of(series: L.Series) -> np.ndarray:
    """Each bar's shape as log offsets from its own close."""
    logc = np.log(np.maximum(series.close, 1e-12))
    return np.column_stack(
        [
            np.log(np.maximum(series.open, 1e-12)) - logc,
            np.log(np.maximum(series.high, 1e-12)) - logc,
            np.log(np.maximum(series.low, 1e-12)) - logc,
        ]
    )


def plant_drift(series: L.Series, mu: float) -> L.Series:
    """Add `mu` sigma of drift per bar. The direct mechanism for a side gap.

    A drift makes the adverse excursion deeper on one side and shallower on the
    other with no asymmetry in the volatility, which is the hypothesis for
    gold's pre-run 1.19x at `H` = 20 growing to 1.64x at 96. `mu` = 0 is the
    zero control and must read nothing.
    """
    r = returns(series)
    sigma = float(np.std(r[1:])) or 1e-12
    out = r.copy()
    out[1:] += mu * sigma
    return _rebuild(series, out, geometry_of(series))


def plant_asym(series: L.Series, factor: float) -> L.Series:
    """Scale every down bar - its return and its whole shape - by `factor`.

    The case `test_the_empirical_wins_where_the_scale_differs` builds by hand
    at 1.3x, planted into bars rather than into draws so the detector runs on
    planted data and the unit moves with the plant. The whole bar is scaled and
    not just the close step, because a plant that leaves the wicks alone is a
    plant a stop cannot see: a stop is reached by the extreme.
    """
    r = returns(series)
    down = r < 0.0
    out = r.copy()
    out[down] *= factor
    geometry = geometry_of(series)
    geometry[down] *= factor
    return _rebuild(series, out, geometry)


def plant_scale(series: L.Series, factor: float) -> L.Series:
    """Scale every return and every bar shape by `factor`.

    **The control that must read exactly nothing.** The excursion is divided by
    a sigma estimated from the same returns, so the whole measurement is
    scale-equivariant by construction and a pure scale change cannot move a
    coverage. A reading here means a lookahead in the unit or a price-level
    dependence of the kind `a-synthetic-at-price-one-hides-scale-bugs` records,
    where relative sd and price offset coincide at price 1.0. A control that
    *must* come back empty catches what a control that should come back smaller
    does not.
    """
    r = returns(series)
    out = r.copy()
    out[1:] *= factor
    return _rebuild(series, out, geometry_of(series) * factor)


PLANTS = {
    "drift": (plant_drift, DRIFTS),
    "asym": (plant_asym, ASYMS),
    "scale": (plant_scale, SCALES),
}


# ───────────────────────── the secondary: mean R ─────────────────────────


@dataclass(frozen=True, slots=True)
class Priced:
    """One arm's mean R, and the same P&L in a unit common to all arms.

    **`mean_r` is not comparable across arms and `per_sigma` is.**
    `widestop.md` measured mean R at `m` times the stop to be the 1x mean
    divided by `m` in every row, with price P&L in units of the base risk not
    moving (+0.180 at 1x, +0.177 at 3x). The arms here span 1.51 to about 8
    units, a factor of five, so a mean-R ranking is a ranking of 1/width.
    `per_sigma` is the same P&L divided by one volatility unit instead of by
    the arm's own risk, which is the number that can be compared.
    """

    arm: str
    side: int
    n: int
    stopped: float
    targeted: float
    expired: float
    mean_r: float
    sd_r: float
    per_sigma: float
    sd_per_sigma: float
    cost_share: float


def race(
    series: L.Series,
    sigma: np.ndarray,
    exc: Excursions,
    stops: np.ndarray,
    *,
    arm: str,
    side: int,
    horizon: int,
    spread_vol: np.ndarray,
    target_r: float = TARGET_R,
    draws: int = 200,
    seed: int = 0,
) -> Priced | None:
    """Stop against target over `horizon` bars, with the spread charged.

    A tie inside one bar goes to the **stop**: bar-level first passage cannot
    say which barrier a bar touched first, so the conservative rule is the only
    honest one, and it is a bias against the target that is biggest where the
    stop is tight - which is the arm comparison here, so it is stated rather
    than buried. An expiring window is scored at the close, not as a stop-out.

    Day-block bootstrap for the sd, because trades cluster in days and an
    ordinary standard error over overlapping daily anchors is far too narrow.
    """
    logc = np.log(np.maximum(series.close, 1e-12))
    logl = np.log(np.maximum(series.low, 1e-12))
    logh = np.log(np.maximum(series.high, 1e-12))
    anchors, n = exc.anchors, len(exc.anchors)
    if n < 50:
        return None
    r_out = np.empty(n)
    kind = np.zeros(n, dtype=np.int8)
    for i, t in enumerate(anchors):
        risk = stops[i] * sigma[t]
        if risk <= 0.0:
            r_out[i] = 0.0
            continue
        cost = spread_vol[t] * sigma[t]
        stop_px = logc[t] - side * risk
        target_px = logc[t] + side * target_r * risk
        hit_stop = hit_target = horizon + 1
        for k in range(t + 1, min(len(logc), t + horizon + 1)):
            if side > 0:
                if logl[k] <= stop_px and hit_stop > horizon:
                    hit_stop = k - t
                if logh[k] >= target_px and hit_target > horizon:
                    hit_target = k - t
            else:
                if logh[k] >= stop_px and hit_stop > horizon:
                    hit_stop = k - t
                if logl[k] <= target_px and hit_target > horizon:
                    hit_target = k - t
            if min(hit_stop, hit_target) <= horizon:
                break
        if hit_stop <= horizon and hit_stop <= hit_target:
            gross, kind[i] = -risk, 1
        elif hit_target <= horizon:
            gross, kind[i] = target_r * risk, 2
        else:
            last = min(len(logc) - 1, t + horizon)
            gross, kind[i] = side * (logc[last] - logc[t]), 3
        r_out[i] = (gross - cost) / risk
    per_sigma = r_out * stops
    day = exc.day
    keys = sorted(set(day.tolist()))
    chunks_r = {k: r_out[day == k] for k in keys}
    chunks_s = {k: per_sigma[day == k] for k in keys}
    rng = random.Random(seed)
    boot_r: list[float] = []
    boot_s: list[float] = []
    for _ in range(draws):
        pick = [keys[rng.randrange(len(keys))] for _ in keys]
        boot_r.append(float(np.concatenate([chunks_r[k] for k in pick]).mean()))
        boot_s.append(float(np.concatenate([chunks_s[k] for k in pick]).mean()))
    return Priced(
        arm=arm,
        side=side,
        n=n,
        stopped=float((kind == 1).mean()),
        targeted=float((kind == 2).mean()),
        expired=float((kind == 3).mean()),
        mean_r=float(r_out.mean()),
        sd_r=st.pstdev(boot_r) if len(boot_r) > 5 else 0.0,
        per_sigma=float(per_sigma.mean()),
        sd_per_sigma=st.pstdev(boot_s) if len(boot_s) > 5 else 0.0,
        cost_share=float(np.median(spread_vol[anchors] / np.maximum(stops, 1e-12))),
    )
