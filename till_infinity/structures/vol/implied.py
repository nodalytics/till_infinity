"""The options market's own volatility forecast, as a member of the ensemble.

## Why this is a member and not a knob

[research/implied.md](../../../research/implied.md) is the only positive result
in this project's research folder. Over 15 years, walk-forward with the fit
redone at every step, VIX beats a trailing realised estimate by **12 to 20
points of R-squared**, and beats the naive baseline - which has beaten GARCH,
HAR, the pooled tree and the factorisation machine - by **+0.26 to +0.43**.

Its sharpest finding decides the shape of this file: **`both` is not better than
`vix` alone.** The historical estimate adds nothing once VIX is present. That is
not "VIX helps", it is "VIX replaces", and a sizing multiplier bolted on the
side would not use that finding.

So it joins `consensus_vol.Ensemble`, which already converts members to one
convention, scores each against **what the next bar actually did**, and can
weight by that score. A scaler that is wrong sits there being wrong; a scored
member that is wrong loses its vote, and `Ensemble.standings()` says so without
anyone intervening.

## One series, four feeds

`implied.md` measured the matched indices and found them unnecessary: `own -
vix` is **+0.0014** for us100 at one day and **-0.0080** for us30, where plain
VIX is *better* than VXD. One feed to keep alive rather than four, and on us30
the matched series would have been worse.

## `1d` and `1w`, and why the scope is narrow on purpose

VIX is a **30-day** forward view published **daily**. Scaling it to a 1m bar by
root-time assumes a flat term structure and no intraday seasonality, and the
intraday U-shape is large and real. The other four members read actual bars and
have no such problem.

At `1d` the conversion is a division by `sqrt(252)` with no intraday assumption
at all. That is the reason for the scope rather than a consequence of it, and
`implied.md`'s own scope line agrees: *"the equity indices at a day and up"*.

**What this improves is the estimate daily and weekly levels and origins are
drawn from** - not the 1m-30m entries the desk fires on.

## 2026-09-11: the raw quote loses, the fitted one wins everywhere

`research/harness/vixseed.py` replayed every member over 20 years of daily and
weekly bars on all four indices, scoring each exactly as the live path does.
Accuracy is 1 - decayed relative error:

| feed | interval | best | `vix` |
| --- | --- | --- | --- |
| spx500 | 1d | har 0.816 | **0.635, last of five** |
| spx500 | 1w | har 0.811 | **0.708, last** |
| us100 | 1d | har 0.827 | 0.761, second |
| us100 | 1w | har 0.823 | 0.800, second |
| us2000 | 1d | har 0.802 | 0.735, second |
| us2000 | 1w | har 0.815 | 0.808, second |
| us30 | 1d | har 0.831 | **0.666, last** |
| us30 | 1w | har 0.813 | **0.693, last** |

**`har` wins everywhere and the raw `vix` is last on half the series.**

### Why this does not contradict `implied.md`

It measures a different quantity. `implied.md` regressed forward realised
volatility on VIX **walk-forward, refitting the coefficient at every step**, and
reported R-squared. This scores a **raw point forecast** with no coefficient at
all.

VIX systematically exceeds realised volatility - the variance risk premium - so
it is highly *informative* and badly *biased* as a point estimate. A regression
removes the bias and keeps the information; an ensemble of point forecasts keeps
both. Being second on us100 and us2000 while last on spx500 and us30 is exactly
what a premium that differs by index looks like.

### So the scale is fitted, and then it wins

`research/harness/vixvshar.py` ran the comparison nobody had: VIX against
**`har`**, the incumbent that actually won above, rather than against the
trailing estimate `implied.md` used. Twenty years, walk-forward, every
coefficient fitted only on bars strictly before the one predicted.

| feed | interval | `har` R2 | raw `vix` | **`vix_fit`** | `har`+`vix` |
| --- | --- | --- | --- | --- | --- |
| spx500 | 1d | 0.293 | **-0.484** | **0.489** | 0.401 |
| spx500 | 1w | 0.260 | -0.065 | **0.540** | 0.329 |
| us100 | 1d | 0.380 | 0.065 | **0.460** | 0.387 |
| us100 | 1w | 0.263 | 0.299 | **0.434** | 0.303 |
| us2000 | 1d | 0.231 | -0.002 | **0.376** | 0.284 |
| us2000 | 1w | 0.248 | 0.413 | **0.461** | 0.311 |
| us30 | 1d | 0.251 | **-0.531** | **0.488** | 0.419 |
| us30 | 1w | 0.253 | -0.139 | **0.531** | 0.327 |

Three things, and the middle one is the diagnosis confirmed:

**The raw quote scores below predicting the mean on four of eight series.** A
negative R-squared is the signature of a bias, not of noise - the number is
systematically too large, which is exactly what a variance risk premium is.

**One coefficient removes it, and the result beats `har` on every series** by
+0.10 to +0.28 R-squared, and on the ensemble's own relative-error metric 8 of 8.

**And `har` combined with `vix` is worse than `vix_fit` alone on all eight.**
That is `implied.md`'s original finding reproduced against a better incumbent:
it said `both` was no better than `vix` alone against a *trailing* estimate, and
this says the same against a *forecasting* one. **VIX does not add to HAR. It
replaces it.**

So `Fit` below is the member, and it ships on.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from ..state import Restorable

#: On, because the fitted form was measured and it wins. See the note below.
ENABLED = os.environ.get("STRUCTURES_IMPLIED", "1") not in ("0", "false", "no")

#: Observations before a fit may vote. A coefficient from thirty bars is a
#: number, not an estimate, and this member's whole content is that coefficient.
MIN_FIT = 250

#: The equity indices `implied.md` measured, keyed to this book's feed names.
IMPLIED_FEEDS: frozenset[str] = frozenset({"spx500", "us100", "us30", "us2000"})

#: Where VIX's own horizon roughly matches the bar. See the module note.
IMPLIED_INTERVALS: tuple[str, ...] = ("1d", "1w")

#: Trading days in a year and in a week. VIX is quoted as an annualised
#: percentage against the first.
YEAR_DAYS = 252.0
INTERVAL_DAYS: dict[str, float] = {"1d": 1.0, "1w": 5.0}

#: A reading older than this does not vote. If the feed dies, the last value
#: otherwise keeps voting with full confidence on every subsequent bar - which
#: is the failure mode that matters here, because a daily series looks alive
#: for a long time after it stops.
MAX_AGE = 3 * 86_400.0


def bps_for(vix: float, interval: str) -> float | None:
    """A VIX quote as this bar's standard deviation, in basis points.

    VIX 20 means 20% annualised sigma, so one trading day is `20 / sqrt(252)`
    percent - 125.99 bps - and a week is that times `sqrt(5)`.

    Returns a **sigma**. The ensemble is on the mean-absolute convention and
    converts anything named in its `sigma_scaled` set, so this must not do that
    conversion itself or it would be applied twice.
    """
    days = INTERVAL_DAYS.get(interval)
    if days is None or vix <= 0:
        return None
    return vix / math.sqrt(YEAR_DAYS) * math.sqrt(days) * 100.0


@dataclass(slots=True)
class Fit(Restorable):
    """`a + b * vix`, fitted online against what each bar actually did.

    **The coefficient is the member.** A raw VIX quote scores worse than
    predicting the mean on four of the eight series measured - R-squared of
    -0.484 on spx500 daily - because VIX systematically exceeds realised
    volatility. That gap is the variance risk premium, it is a bias rather than
    noise, and one number removes it.

    Least squares by accumulated sums rather than by keeping the rows: it is
    exact, it is O(1) per bar, and it persists as six floats instead of a
    history. Strictly causal - `predict` uses only what `observe` has already
    been given, so a bar never informs its own forecast.

    One fit per `(feed, interval)` and not one pooled fit, because the premium
    differs by index: raw VIX scores second on us100 and last on spx500, which
    is what a per-index bias looks like.
    """

    n: float = 0.0
    sx: float = 0.0
    sy: float = 0.0
    sxx: float = 0.0
    sxy: float = 0.0

    def observe(self, vix_bps: float, realised: float) -> None:
        if vix_bps <= 0 or realised <= 0:
            return
        self.n += 1.0
        self.sx += vix_bps
        self.sy += realised
        self.sxx += vix_bps * vix_bps
        self.sxy += vix_bps * realised

    def predict(self, vix_bps: float) -> float | None:
        """The de-biased reading, or None until the fit means anything."""
        if self.n < MIN_FIT or vix_bps <= 0:
            return None
        spread = self.n * self.sxx - self.sx * self.sx
        if spread <= 0:
            return None
        slope = (self.n * self.sxy - self.sx * self.sy) / spread
        intercept = (self.sy - slope * self.sx) / self.n
        got = intercept + slope * vix_bps
        # A fit may not predict a negative volatility, and a coefficient that
        # wants to is a fit that has gone wrong rather than a forecast of calm.
        return got if got > 0 else None


@dataclass(slots=True)
class Implied(Restorable):
    """The last VIX reading, and whether it is fresh enough to vote."""

    max_age: float = MAX_AGE
    level: float = 0.0
    at: float = 0.0

    def observe(self, vix: float, when: float) -> None:
        if vix > 0:
            self.level, self.at = float(vix), float(when)

    def fresh(self, now: float) -> bool:
        return self.level > 0 and (now - self.at) <= self.max_age

    def bps(self, interval: str, now: float) -> float | None:
        """This bar's implied sigma in bps, or None when it must not vote."""
        return bps_for(self.level, interval) if self.fresh(now) else None


#: How often the quote is re-read. VIX is published daily, so this is about
#: catching the day's close rather than tracking a tape - and about noticing
#: that the source has stopped, which a daily series hides for a long time.
POLL_SECONDS = float(os.environ.get("STRUCTURES_IMPLIED_POLL") or 3_600.0)

#: The one series. `implied.md` measured the matched indices and found them
#: unnecessary: `own - vix` is +0.0014 for us100 at a day and **-0.0080** for
#: us30, where plain VIX is better than VXD.
TICKER = os.environ.get("STRUCTURES_IMPLIED_TICKER") or "^VIX"


def latest(ticker: str = TICKER) -> float | None:
    """The most recent VIX close, or None if it cannot be read.

    Synchronous and blocking - yfinance does its own HTTP - so callers push it
    onto a thread, the way `prices/yahoo.py` does for the same reason.

    Never raises. A source that is unreachable must leave the last good reading
    in place and let `MAX_AGE` retire it, because an exception here would take
    down a service whose actual job is levels.
    """
    try:
        import yfinance as yf

        got = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
        for _when, row in reversed(list(got.iterrows())):
            close = row.get("Close")
            if close is not None and not math.isnan(close) and close > 0:
                return float(close)
    except Exception:
        return None
    return None
