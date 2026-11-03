"""Fear and greed in FX as risk-on / risk-off: the data, the crosses, the shapes.

**This is not a reimplementation of a published fear-and-greed index.** CNN's
is for US stocks and needs put/call ratios, market breadth, junk-bond demand,
safe-haven flows and a 125-day momentum of the S&P; the crypto one adds social
volume and Google Trends. None of those is computable from OHLCV and none of
them is in this store, so no number here should be compared to one. See the
module docstring of `till_infinity/indicators/sentiment.py`, which makes the
same point about the reading itself.

What *is* computable is the thing those indices proxy for, and in FX it has a
name and a literature. Fear is risk-off: money runs to JPY, CHF and gold and
out of AUD, NZD and CAD, so the carry crosses fall fast. Greed is risk-on and
rebuilds the carry trade slowly. **Brunnermeier, Nagel and Pedersen, *Carry
Trades and Currency Crashes* (2008)** is the published description of exactly
that asymmetry - up slowly, down fast - and 2008 is inside this store's window,
so the episode they describe is available as a positive control rather than as
an anecdote.

## The crosses are not in the store, so they are built

There is no `audjpy`, `nzdjpy`, `cadjpy`, `eurjpy` or `gbpjpy` at any interval
in `.data/prices/prices.db`. Every **leg** is there at 1d over 19.2 years, so
the crosses are synthesised:

    AUDJPY = AUDUSD x USDJPY      NZDJPY = NZDUSD x USDJPY
    CADJPY = USDJPY / USDCAD      AUDCHF = AUDUSD / USDCHF
    EURCHF = EURUSD / USDCHF

**A synthetic cross's bar extremes are bounds, not observations, and on the
JPY crosses the bound is loose enough to break every range-based detector.**
The product of two daily highs is the daily high of the product only if both
legs printed their high in the same instant. Measured rather than assumed:
median bar range over median absolute close-to-close move is **2.300 to 2.439
on all eight real instruments here** - a band 0.139 wide - against **4.03
audjpy, 4.10 nzdjpy, 3.59 cadjpy, 2.79 audchf, 2.45 eurchf**. Against the real
band's median of 2.340, the synthesised range is about **1.7x too wide on
AUDJPY and NZDJPY**, 1.5x on CADJPY, 1.19x on AUDCHF and 1.05x on EURCHF.

The direction follows from the quote convention and is why EURCHF escapes:
AUDUSD and USDJPY sit on opposite sides of the dollar, so AUDUSD's high and
USDJPY's high are two moves that never co-occurred and their product is a price
the cross never saw. EURUSD and USDCHF move together against the dollar, so a
*quotient* takes EURUSD's high over USDCHF's low - which is nearly the same
instant - and the bound is tight.

What it costs, measured on audjpy against audusd over the same 4,980 days:
median body-over-range falls from **0.463 to 0.268**, the share of bars
clearing `PUSH_BODY` 0.70 falls from **0.211 to 0.045**, and
`levels.chains` finds **4 displacement legs in 19 years instead of 83**. So a
displacement, a candle shape, a level book and an EWMA-of-range volatility unit
are all unusable on a JPY cross, and this study does not run them there:

* **close-exact on a cross** - `open`, `close`, every return, a swing
  decomposition on closes, a barrier race on closes, and `FearGreed`'s
  `pressure` and `skew`, both of which read returns only;
* **range-dependent, so real legs only** - the level books, `Displacement`,
  `Candles`, and `FearGreed`'s `position`, `conviction` and `expansion`.

That split is the reason the fear reading itself is built from the **real legs**
(`basket_risk_off`) rather than from a cross, and the crosses carry the trade
and the swing asymmetry, where the close path is exact.

## The venue rule, fixed before any result

**OANDA, at every interval.** It is the only venue in the store whose gold and
FX daily bars share a timestamp - SAXO stamps gold at 22:00 and FX at 21:00, so
their daily intersection is empty - and a cross built from two venues' legs is
two clocks multiplied together. OANDA carries 4,980 daily bars common to all
eight feeds (2007-05-16 to 2026-08-13, 19.25 years) against FX_IDC's and SAXO's
4,999 for the five cross legs alone, both of which have no usable gold. At 15m
it carries 4,760 common bars against SAXO's 4,792, a 0.7% difference.

Every series in the study is cut to the **timestamps common to all eight
feeds**, so a leg, a cross and gold are the same days and a per-day statistic
is comparable across them. `difference-before-aligning` is why the intersection
is taken once, up front, and every return is differenced inside it: aligning
after differencing turns each feed's own missing day into a fake one-bar return
on its neighbours.

## Costs

**Nothing here is priced and the primary result is gross.** Only `eurusd`,
`gbpusd` and `gold` among these feeds have enough recorded quotes for a median
spread; `audusd`, `nzdusd`, `usdcad`, `usdchf` and `usdjpy` have two or fewer,
so `node/corpus.py` skips them rather than guess. A synthetic cross is worse
than unpriced: **a cross's spread is not the product of its legs' spreads, it
is wider** - a dealer quoting AUDJPY carries both legs' risk plus the
correlation - and there is no recorded AUDJPY quote anywhere in this store to
measure it against. So no cost is charged and none is invented. What a costed
read would need is one thing: recorded AUDJPY/NZDJPY/CADJPY quotes from the
venue that would trade them.
"""

from __future__ import annotations

import collections
import datetime as dt
import math
import os
import random
import sqlite3
from dataclasses import dataclass, replace

import numpy as np

from till_infinity.indicators.levels import Candle, chains
from till_infinity.indicators.sentiment import HALVES, FearGreed
from till_infinity.indicators.trend import ratio

#: The price store. Relative by default so the study runs wherever the repo is
#: checked out; `FEARGREED_STORE` points it at a copy on a bigger box.
STORE = os.environ.get("FEARGREED_STORE") or "file:.data/prices/prices.db?mode=ro"

NANOS = 1_000_000_000

#: One venue for the whole study. See the module docstring: it is the only one
#: whose gold and FX daily bars share a stamp, and a cross built from two
#: venues is two clocks multiplied.
VENUE = os.environ.get("FEARGREED_VENUE") or "OANDA"

#: The legs loaded from the store. The intersection of their timestamps is the
#: study's calendar, so all eight are loaded even where only five are
#: multiplied: dropping gold to buy 19 more days would cost the one safe haven
#: that is not a currency.
LEGS: tuple[str, ...] = (
    "audusd",
    "nzdusd",
    "usdcad",
    "usdjpy",
    "usdchf",
    "eurusd",
    "gbpusd",
    "gold",
)

#: What each leg is, for the risk-on / risk-off reading. `haven` rises when
#: fear rises, `carry` falls. A USD-quoted pair carries the sign of its
#: *quote* convention, which is why `usdjpy` is marked `haven_inverse`: USDJPY
#: **falls** when JPY is bid, so its sign is the opposite of gold's.
ROLE: dict[str, str] = {
    "audusd": "carry",
    "nzdusd": "carry",
    "usdcad": "carry_inverse",
    "usdjpy": "haven_inverse",
    "usdchf": "haven_inverse",
    "gold": "haven",
    "eurusd": "neutral",
    "gbpusd": "neutral",
}


#: How each leg's own `FearGreed` reading enters the risk-off basket.
#:
#: **The signs are the quote convention and are fixed before the run.** Fear is
#: risk-off, and risk-off bids JPY, CHF and gold while selling AUD, NZD and
#: CAD - but a pair's *reading* is about the pair's own direction, so the sign
#: has to be written down rather than assumed. AUDUSD falls, so its fear is
#: risk-off and it enters negated. USDCAD **rises** when CAD is sold, so it
#: enters positive. USDJPY and USDCHF fall when the haven is bid, so they enter
#: negated. Gold rises, so it enters positive.
#:
#: `eurusd` and `gbpusd` are deliberately absent: neither is a haven nor a
#: carry currency over this window, and they are kept outside the basket so
#: they can be read as instruments the index should have least to say about.
RISK_OFF_SIGN: dict[str, float] = {
    "audusd": -1.0,
    "nzdusd": -1.0,
    "usdcad": +1.0,
    "usdjpy": -1.0,
    "usdchf": -1.0,
    "gold": +1.0,
}


@dataclass(frozen=True, slots=True)
class Recipe:
    """A synthetic cross: legs multiplied, legs divided, and what it is for.

    `kind` is `carry` for a high-yield-against-safe-haven cross, which is what
    the risk-on / risk-off claim is about, and `placebo` for one built the same
    way out of two low-yield currencies - `a-control-is-only-for-a-named-
    property`, the property being the carry differential and *not* the
    synthesis, which both arms share.
    """

    name: str
    over: tuple[str, ...]
    under: tuple[str, ...]
    kind: str


#: The crosses, as a 2x2 in the two legs the carry story needs: a high-yield
#: leg to be sold and a safe-haven leg to be bought. Every one is built by the
#: same arithmetic, so the synthesis itself is held constant and only the legs
#: vary - `a-control-is-only-for-a-named-property`, and the properties here are
#: `carry` and `haven` separately rather than one word for both.
#:
#: **`eurchf` is not a placebo and was relabelled after the control ran.** It
#: was pre-registered as one on the grounds that EUR and CHF were both
#: low-yield across this window, which is true about yields and wrong about
#: havens: CHF *is* a haven, and EURCHF duly fell 31.6% in the same 2008 window
#: where the carry crosses fell 32.6-44.5%. So it isolates the haven leg
#: instead, which is the more useful control, and `eurgbp` - neither leg a
#: haven, neither high-yield - is the placebo that was missing. The deviation
#: is recorded in `research/docs/fear-greed.md` rather than quietly fixed.
CROSSES: tuple[Recipe, ...] = (
    Recipe("audjpy", ("audusd", "usdjpy"), (), "carry+haven"),
    Recipe("nzdjpy", ("nzdusd", "usdjpy"), (), "carry+haven"),
    Recipe("cadjpy", ("usdjpy",), ("usdcad",), "carry+haven"),
    Recipe("audchf", ("audusd",), ("usdchf",), "carry+haven"),
    Recipe("eurchf", ("eurusd",), ("usdchf",), "haven"),
    Recipe("eurgbp", ("eurusd",), ("gbpusd",), "placebo"),
)

#: Per interval: the forward horizon in bars and the span of the EWMA bar range
#: that is the volatility unit. Taken from `level_shield.SETTINGS` unchanged,
#: so the two studies' distances mean the same thing.
#:
#: **Every parameter is in bars, and that is the mapping between intervals.** A
#: D1 rule is a different rule from a 15m one - the swing length, the unit and
#: the hold all scale with the bar - so the two are never pooled and are named
#: separately in the write-up.
SETTINGS: dict[str, dict[str, int]] = {
    "15m": {"horizon": 48, "unit_span": 48},
    "1h": {"horizon": 48, "unit_span": 48},
    "1d": {"horizon": 20, "unit_span": 20},
}

#: Calendar eras the 19.25 years are cut into, as `(label, first year, last
#: year)` inclusive. Fixed before the run and chosen by episode rather than by
#: equal length, because the question is whether the asymmetry is 2008 alone:
#: `strategy-rotation-is-not-timeable` and
#: `calendar-claims-need-the-weekday-control` are both about a pattern that was
#: one stretch of the sample wearing a rule's name.
ERAS: tuple[tuple[str, int, int], ...] = (
    ("2007-2009 GFC", 2007, 2009),
    ("2010-2012 euro", 2010, 2012),
    ("2013-2015", 2013, 2015),
    ("2016-2019", 2016, 2019),
    ("2020-2022 covid", 2020, 2022),
    ("2023-2026", 2023, 2026),
)

#: The window the carry crash is read in, and the one dropped to ask whether a
#: result is only that episode. Brunnermeier, Nagel and Pedersen (2008)
#: describe the unwind as running from the summer of 2008; the store's own
#: synthetic AUDJPY peaks 2008-07-21 and troughs 2008-10-26.
CRASH_FROM, CRASH_TO = "2008-08-01", "2009-03-31"
CRASH_DROP_FROM, CRASH_DROP_TO = "2008-01-01", "2009-06-30"


# ───────────────────────────────── the series ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class Series:
    """One instrument's bars, real or synthesised.

    `synthetic` is carried rather than inferred from the name because every
    range-based reading on a synthetic cross is computed from **bounds** - see
    the module docstring - and a caller that cannot see which it has will
    report an inflated range as an observed one.
    """

    feed: str
    venue: str
    interval: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    synthetic: bool = False
    kind: str = "leg"

    @property
    def name(self) -> str:
        return f"{self.feed}.{self.venue}.{self.interval}"

    @property
    def years(self) -> float:
        return float(self.ts[-1] - self.ts[0]) / (86_400.0 * 365.25)

    def __len__(self) -> int:
        return len(self.close)


def _rows(con: sqlite3.Connection, interval: str) -> dict[str, dict[int, tuple]]:
    """Every bar at `interval` on `VENUE`, as `{feed: {ts: ohlc}}`.

    One scan. The store's only index is on `(source, venue, ticker, interval,
    ts)`, so a query filtering on `feed` cannot use it and one query per feed
    is one full scan per feed - which took over two minutes for eight feeds
    where this takes four seconds.
    """
    out: dict[str, dict[int, tuple]] = collections.defaultdict(dict)
    sql = (
        "select feed, ts, open, high, low, close from bars "
        "where interval=? and venue=? and closed=1"
    )
    for feed, ts, o, h, lo, c in con.execute(sql, (interval, VENUE)):
        out[feed][ts] = (o, h, lo, c)
    return out


def load(con: sqlite3.Connection, interval: str) -> dict[str, Series]:
    """Every leg and every cross at `interval`, on one shared calendar.

    The calendar is the timestamps common to all of `LEGS`, taken **before**
    anything is differenced. `difference-before-aligning`: a diff taken after
    an intersection makes every dropped day a fake one-bar return.
    """
    held = _rows(con, interval)
    missing = [f for f in LEGS if not held.get(f)]
    if missing:
        raise ValueError(f"{VENUE} has no {interval} bars for {missing}")
    common = sorted(set.intersection(*[set(held[f]) for f in LEGS]))
    if len(common) < 500:
        raise ValueError(f"{VENUE} {interval} has only {len(common)} bars common to {LEGS}")
    ts = np.asarray(common, dtype=float)
    cut: dict[str, np.ndarray] = {}
    for feed in LEGS:
        cut[feed] = np.asarray([held[feed][t] for t in common], dtype=float)

    out: dict[str, Series] = {}
    for feed in LEGS:
        arr = cut[feed]
        out[feed] = Series(
            feed=feed,
            venue=VENUE,
            interval=interval,
            ts=ts,
            open=arr[:, 0],
            high=arr[:, 1],
            low=arr[:, 2],
            close=arr[:, 3],
            synthetic=False,
            kind="leg",
        )
    for recipe in CROSSES:
        out[recipe.name] = synthesise(recipe, cut, ts, interval)
    return out


def synthesise(
    recipe: Recipe, cut: dict[str, np.ndarray], ts: np.ndarray, interval: str
) -> Series:
    """One synthetic cross from its legs.

    `open` and `close` are **exact**: a product of closes is the cross's close.
    `high` and `low` are **bounds**, because the product of two daily highs is
    the cross's high only if both legs printed their high in the same instant.
    The division legs invert, so a cross's upper bound divides by the
    denominator's *low*.
    """
    one = np.ones_like(ts)
    o = one.copy()
    c = one.copy()
    hi = one.copy()
    lo = one.copy()
    for feed in recipe.over:
        arr = cut[feed]
        o *= arr[:, 0]
        hi *= arr[:, 1]
        lo *= arr[:, 2]
        c *= arr[:, 3]
    for feed in recipe.under:
        arr = cut[feed]
        o /= arr[:, 0]
        hi /= arr[:, 2]
        lo /= arr[:, 1]
        c /= arr[:, 3]
    return Series(
        feed=recipe.name,
        venue=VENUE,
        interval=interval,
        ts=ts,
        open=o,
        high=hi,
        low=lo,
        close=c,
        synthetic=True,
        kind=recipe.kind,
    )


def triangle_check(held: dict[str, Series]) -> list[dict]:
    """The recorded positive control: an FX screen must see the triangles.

    `currency-triangles-are-the-positive-control` says a screen that misses the
    triangles at t past -50 with weights at +-1 is broken. For a cross built by
    multiplication the identity is exact in logs, so the regression this
    reports is not a discovery - it is an **alignment** test, and the one thing
    it can fail on is a shifted calendar. `fear_greed_control.plant_misalign`
    is the power arm for it: shift one leg by a bar and the weights collapse.

    Reports, per cross: the OLS weights of its log return on its legs' log
    returns, each weight's t, the R squared, and the largest absolute deviation
    of the reconstructed log price. The deviation is the sharper of the two -
    float noise is 1e-16 and anything else is an arithmetic fault.
    """
    out: list[dict] = []
    for recipe in CROSSES:
        cross = held[recipe.name]
        legs = list(recipe.over) + list(recipe.under)
        signs = [1.0] * len(recipe.over) + [-1.0] * len(recipe.under)
        y = np.diff(np.log(cross.close))
        X = np.column_stack([np.diff(np.log(held[f].close)) for f in legs])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        dof = max(1, len(y) - X.shape[1])
        s2 = float(resid @ resid) / dof
        cov = s2 * np.linalg.pinv(X.T @ X)
        se = np.sqrt(np.maximum(np.diag(cov), 1e-300))
        total = float(np.var(y)) or 1e-300
        built = np.zeros_like(cross.close)
        for sign, feed in zip(signs, legs, strict=True):
            built += sign * np.log(held[feed].close)
        out.append(
            {
                "cross": recipe.name,
                "kind": recipe.kind,
                "legs": legs,
                "signs": signs,
                "weights": [float(b) for b in beta],
                "t": [float(b / s) for b, s in zip(beta, se, strict=True)],
                "r2": 1.0 - float(np.var(resid)) / total,
                "log_price_dev": float(np.abs(np.log(cross.close) - built).max()),
                "n": int(len(y)),
            }
        )
    return out


# ──────────────────────────────── the null arms ────────────────────────────────


def units(series: Series, span: int) -> np.ndarray:
    """The volatility unit: a causal EWMA of the bar range.

    The range and not a close-to-close sigma, because `drive-q-from-the-range`
    is the measured choice - the range-vs-close estimator ratio reads 0.648
    within strata on FX and 0.667 on 371 of 392 equities. Identical to
    `level_shield.units`, so a distance means the same thing in both studies.

    **On a synthetic cross this unit is inflated**, because the range is a
    bound. Every distance on a cross is therefore in a slightly wider unit than
    the cross's own volatility, which makes a reach rate *lower* - a bias
    against finding anything, and measured in `fear_greed_bias.py`.
    """
    span = max(1, span)
    alpha = 2.0 / (span + 1.0)
    width = series.high - series.low
    out = np.empty(len(width))
    cur = 0.0
    for i, x in enumerate(width):
        cur = x if cur <= 0.0 else (1.0 - alpha) * cur + alpha * max(x, 0.0)
        out[i] = cur
    return out


def close_units(series: Series, span: int) -> np.ndarray:
    """The volatility unit from closes alone: a causal EWMA of |close - close|.

    **The unit every reading on a synthetic cross uses**, because the cross's
    range is a bound inflated about 1.7x on the JPY pairs (see the module
    docstring) and a distance measured in an inflated unit is a different
    distance. A close-to-close estimator is the noisier choice -
    `drive-q-from-the-range` measured the range-based one better at 0.648
    within strata on FX - and it is taken here because the better one is not
    available on this instrument, not because it is better.

    Scaled by the real instruments' own measured ratio so the two units are
    comparable in size: median range over median |dclose| is **2.300 to 2.439
    on all eight real instruments** in this store, so `RANGE_OVER_STEP`
    converts a close-step unit into something a range-unit threshold can be
    read against. Without it a distance of 2.0 units means two different
    distances on a leg and on a cross, and every cross would look like a
    quieter instrument.
    """
    span = max(1, span)
    alpha = 2.0 / (span + 1.0)
    step = np.empty(len(series.close))
    step[0] = abs(float(series.close[1] - series.close[0])) if len(series.close) > 1 else 0.0
    step[1:] = np.abs(np.diff(series.close))
    out = np.empty(len(step))
    cur = 0.0
    for i, x in enumerate(step):
        cur = x if cur <= 0.0 else (1.0 - alpha) * cur + alpha * x
        out[i] = cur
    return out * RANGE_OVER_STEP


#: Median bar range over median absolute close-to-close move, which converts a
#: close-step unit into something a range-unit threshold can be read against.
#:
#: Measured on all **eight** real instruments at 1d: nzdusd 2.300, eurusd
#: 2.319, gbpusd 2.322, usdcad 2.336, audusd 2.344, usdchf 2.356, gold 2.412,
#: usdjpy 2.439. A band **0.139 wide over eight instruments**, which is what
#: makes this a constant rather than a per-feed fit - and what makes a
#: synthetic cross's 2.79-4.10 readable as bound inflation rather than as a
#: property of the instrument.
#:
#: **2.39 is the value used and it is 2% above the band's median of 2.340.**
#: It was fixed from the first six instruments measured, before nzdusd, eurusd
#: and gbpusd were added, and is kept rather than re-centred: it scales every
#: distance on a synthetic cross by 2%, which is two orders of magnitude below
#: the effects in `research/docs/fear-greed.md`, and re-centring it would
#: invalidate every number already measured on it for no gain.
RANGE_OVER_STEP = 2.39


def unit_for(series: Series, span: int) -> np.ndarray:
    """The volatility unit this series can honestly supply.

    The range-based one on a real instrument, the close-based one on a
    synthetic cross. **One column, one unit** - the recorded failure is a
    feature that silently falls back to a different scale, which puts one
    column in two units and makes both readings look fine.
    """
    return close_units(series, span) if series.synthetic else units(series, span)


def range_trusted(series: Series) -> bool:
    """Whether a range-based detector may be run on this series.

    False on every synthetic cross. Not a judgement call: on audjpy the median
    body-over-range is 0.268 against audusd's 0.463 and `levels.chains` finds 4
    legs in 19 years against 83, so a displacement detector there is reporting
    the bound rather than the market.
    """
    return not series.synthetic


def _shaped(series: Series, close: np.ndarray, pick: np.ndarray) -> Series:
    """A series with a new close path and each bar's own wick proportions.

    Shared by every arm that keeps bar geometry, so the three cannot drift
    apart in how a bar is rebuilt.
    """
    span = series.high - series.low
    safe = np.maximum(span, 1e-12)
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)
    width = span[pick]
    low = close - frac_c[pick] * width
    return replace(
        series,
        open=low + frac_o[pick] * width,
        high=low + width,
        low=low,
        close=close,
    )


def bar_shuffle(series: Series, rng: random.Random) -> Series:
    """Each bar's own shape on a permuted close-to-close step. The memory floor.

    The arm that matters most here, and
    `let-the-shuffled-twin-name-the-mechanical-observables` says why: a crash
    bar is still a big down bar after a shuffle, and the **marginal return
    distribution survives exactly**, so its skewness does too. If "down moves
    are faster and deeper" is a fact about the distribution of one day's return
    rather than about the path, this arm reproduces it in full - and that is the
    whole of what Brunnermeier, Nagel and Pedersen's asymmetry would reduce to
    if it had no time structure.
    """
    n = len(series.close)
    steps = np.diff(series.close)
    order = np.asarray(rng.sample(range(n - 1), n - 1))
    pick = np.asarray(rng.sample(range(n), n))
    close = np.empty(n)
    close[0] = series.close[0]
    close[1:] = series.close[0] + np.cumsum(steps[order])
    return _shaped(series, close, pick)


def log_shuffle(series: Series, rng: random.Random) -> Series:
    """A permutation of the **log** returns, each bar keeping its relative shape.

    **The hardest memory-free arm on a 19-year series, and the one that
    disagrees with `bar_shuffle`.** `bar_shuffle` and `walk_geometry` permute
    and resample *absolute* close-to-close steps, which is what
    `level_shield.py` does and is sound there - 76 days of 15-minute bars move
    a few percent. Over this study's window the level moves by a factor of
    2.06 on audjpy, 2.19 on nzdjpy and **8.45 on gold**, so permuting absolute
    steps mixes a 2026 gold step into a 2007 gold price and the surrogate's own
    volatility structure is not the market's.

    Measured consequence, audjpy at `reach` 10: the duration gap reads
    **+0.188** on an absolute-step shuffle and **+0.020** on this one, against
    a real +0.213. The two arms disagree by more than the effect, so the
    absolute-step arm cannot be the one a verdict rests on. The speed gap is
    unaffected - both read about -0.23 against a real -0.285 - which is why
    the two statistics get different verdicts in `fear-greed.md`.

    Returns are the scale-free quantity, so the log marginal is preserved
    exactly and the range is carried as a share of price rather than in price.
    """
    n = len(series.close)
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    order = np.asarray(rng.sample(range(n - 1), n - 1))
    close = np.empty(n)
    close[0] = float(series.close[0])
    close[1:] = close[0] * np.exp(np.cumsum(rets[order]))
    return _shaped_relative(series, close, np.asarray(rng.sample(range(n), n)))


def log_walk(series: Series, rng: random.Random) -> Series:
    """An i.i.d. resample of the log returns. `log_shuffle` with replacement.

    Carried beside `log_shuffle` for the same reason `walk_geometry` is carried
    beside `bar_shuffle`: a permutation holds the realised sample exactly, a
    resample holds only the distribution, and a statistic sensitive to the
    exact multiset would separate them.
    """
    n = len(series.close)
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    draw = np.asarray([rng.randrange(n - 1) for _ in range(n - 1)])
    close = np.empty(n)
    close[0] = float(series.close[0])
    close[1:] = close[0] * np.exp(np.cumsum(rets[draw]))
    return _shaped_relative(series, close, np.asarray([rng.randrange(n) for _ in range(n)]))


def _shaped_relative(series: Series, close: np.ndarray, pick: np.ndarray) -> Series:
    """`_shaped`, with each bar's range carried as a **share of its own close**.

    The difference from `_shaped` is the whole point of the log arms: a range
    pasted on in price units puts a 2026 gold bar's $40 range on a 2007 gold
    bar at $650, and the surrogate's wickiness then varies with the level
    rather than with the market.
    """
    span = series.high - series.low
    safe = np.maximum(span, 1e-12)
    rel = np.where(series.close > 0, span / np.maximum(series.close, 1e-12), 0.0)
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)
    width = close * rel[pick]
    low = close - frac_c[pick] * width
    return replace(
        series,
        open=low + frac_o[pick] * width,
        high=low + width,
        low=low,
        close=close,
    )


def walk_geometry(series: Series, rng: random.Random) -> Series:
    """An i.i.d. resample of the steps, each bar keeping its own shape.

    `node/surrogates.walk_with_bar_geometry` in array form rather than through
    the function, because that one builds a list of tuples per bar and this
    study calls it 13 instruments x 4 draws deep. The property is the same:
    this market's step distribution and wickiness, no path structure and no
    clustering.
    """
    n = len(series.close)
    steps = np.diff(series.close)
    draw = np.asarray([rng.randrange(n - 1) for _ in range(n - 1)])
    pick = np.asarray([rng.randrange(n) for _ in range(n)])
    close = np.empty(n)
    close[0] = series.close[0]
    close[1:] = series.close[0] + np.cumsum(steps[draw])
    return _shaped(series, close, pick)


def fit_garch(returns: np.ndarray) -> tuple[float, float, float]:
    """GARCH(1,1) by a coarse grid on (alpha, beta), omega from the variance.

    Coarse on purpose, and identical to `level_shield.fit_garch`. The arm
    exists to supply **clustering of about the right strength**, not to be the
    best model of the series: `a-control-is-only-for-a-named-property` is the
    rule, the property is clustering, and a grid landing near the FX consensus
    (alpha about 0.08, beta about 0.90) keeps it.

    It is a **Gaussian** innovation, which is the point of carrying it beside
    `bar-shuffle`: it has clustering and *no return skewness*, where the
    shuffle has skewness and no clustering. Between them the two name which
    half of the market an asymmetry came from.
    """
    r = returns - returns.mean()
    var = float(np.var(r)) or 1e-12
    best = (0.08, 0.90, -1e18)
    for alpha in (0.02, 0.05, 0.08, 0.12, 0.18):
        for beta in (0.70, 0.80, 0.88, 0.93, 0.96):
            if alpha + beta >= 0.999:
                continue
            omega = var * (1.0 - alpha - beta)
            sigma2 = var
            total = 0.0
            for x in r:
                total += -0.5 * (math.log(sigma2) + x * x / sigma2)
                sigma2 = omega + alpha * x * x + beta * sigma2
            if total > best[2]:
                best = (alpha, beta, total)
    alpha, beta, _ = best
    return var * (1.0 - alpha - beta), alpha, beta


def garch_bars(series: Series, rng: random.Random, fitted=None) -> Series:
    """Clustering kept, path structure and return skewness removed.

    A GARCH(1,1) close path with each bar's range scaled to the simulated
    volatility and its wick proportions resampled from the real bars. Same
    construction as `level_shield.garch_bars`.
    """
    n = len(series.close)
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    omega, alpha, beta = fitted or fit_garch(rets)
    span = series.high - series.low
    rel = np.where(series.close > 0, span / np.maximum(series.close, 1e-12), 0.0)
    scale = float(np.median(np.abs(rets))) or 1e-9
    ratio_ = rel / scale
    safe = np.maximum(span, 1e-12)
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)

    sigma2 = float(np.var(rets)) or 1e-12
    close = np.empty(n)
    low = np.empty(n)
    high = np.empty(n)
    open_ = np.empty(n)
    price = float(series.close[0])
    close[0] = low[0] = high[0] = open_[0] = price
    idx = len(ratio_)
    for i in range(1, n):
        sigma = math.sqrt(max(sigma2, 1e-18))
        step = rng.gauss(0.0, 1.0) * sigma
        sigma2 = omega + alpha * step * step + beta * sigma2
        price *= math.exp(step)
        k = rng.randrange(idx)
        width = max(price * ratio_[k] * sigma, price * 1e-9)
        bottom = price - frac_c[k] * width
        close[i], low[i], high[i] = price, bottom, bottom + width
        open_[i] = bottom + frac_o[k] * width
    return replace(series, open=open_, high=high, low=low, close=close)


def sign_flip(series: Series, rng: random.Random) -> Series:  # noqa: ARG001
    """The same path with every log return negated and every bar mirrored.

    **Not a null and not a surrogate: the mirror.** It is deterministic, takes
    `rng` only so the arm table can call every arm the same way, and it exists
    for one question - *is the up/down asymmetry a property of the return
    distribution's sign?* If it is, this arm reproduces the asymmetry with the
    sign reversed and the magnitude unchanged. If the asymmetry survives with
    its own sign, the measurement is reading something about the level process
    rather than about direction, which would be a defect in the statistic.
    """
    rets = -np.diff(np.log(np.maximum(series.close, 1e-12)))
    close = np.empty(len(series.close))
    close[0] = float(series.close[0])
    close[1:] = close[0] * np.exp(np.cumsum(rets))
    span = series.high - series.low
    safe = np.maximum(span, 1e-12)
    # Mirrored within the bar: the share of the range above the close becomes
    # the share below it, so a long lower wick becomes a long upper one.
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    rel = np.where(series.close > 0, span / np.maximum(series.close, 1e-12), 0.0)
    width = close * rel
    low = close - (1.0 - frac_c) * width
    return replace(
        series,
        open=low + (1.0 - frac_o) * width,
        high=low + width,
        low=low,
        close=close,
    )


def drift_free(series: Series, rng: random.Random) -> Series:  # noqa: ARG001
    """The same path with the mean log return removed. Deterministic.

    Separates drift from skew. A trending series has longer up swings for an
    arithmetic reason that has nothing to do with a crash, and 19 years of
    AUDJPY is not drift-free, so an asymmetry that disappears here was the
    trend.
    """
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    rets = rets - rets.mean()
    close = np.empty(len(series.close))
    close[0] = float(series.close[0])
    close[1:] = close[0] * np.exp(np.cumsum(rets))
    rel = np.where(series.close > 0, (series.high - series.low) / series.close, 0.0)
    span = series.high - series.low
    safe = np.maximum(span, 1e-12)
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)
    width = close * rel
    low = close - frac_c * width
    return replace(
        series,
        open=low + frac_o * width,
        high=low + width,
        low=low,
        close=close,
    )


#: The arms, weakest control to strongest, plus the two deterministic mirrors.
#:
#: `real` is the series. The three surrogates each remove one property and are
#: drawn repeatedly; `sign-flip` and `drift-free` are deterministic
#: transformations of the real series and are drawn once, which the runner
#: enforces through `DRAWN`.
ARMS = {
    "real": None,
    "garch-bars": garch_bars,
    "walk-geometry": walk_geometry,
    "bar-shuffle": bar_shuffle,
    "log-walk": log_walk,
    "log-shuffle": log_shuffle,
    "sign-flip": sign_flip,
    "drift-free": drift_free,
}

#: The arms worth more than one draw. The rest are deterministic.
DRAWN = frozenset(
    {"garch-bars", "walk-geometry", "bar-shuffle", "log-walk", "log-shuffle"}
)

#: The arms a finding has to beat. `sign-flip` and `drift-free` are diagnostic
#: - they say *what* an effect is - and are deliberately not in the set a
#: result is scored against, because beating a mirror of yourself is not a
#: test.
#:
#: **The log arms are in here and they are the binding ones on this window.**
#: An absolute-step shuffle over 19 years mixes steps across a 2x to 8.45x
#: level range; see `log_shuffle`, where the two kinds of shuffle disagree on
#: the duration gap by more than the effect being measured.
NULL_ARMS = tuple(DRAWN)


# ───────────────────────────── the fear/greed path ─────────────────────────────


@dataclass(frozen=True, slots=True)
class Mood:
    """`FearGreed` read bar by bar over a whole series.

    Three arrays per reading rather than one composite, because
    `sentiment.py`'s whole design is that **a claim on the composite cannot say
    which half it rests on**. `volatile` is the half measured large here
    (`relationships-are-contemporaneous`); `directional` is the half measured
    closed (`direction-is-closed-not-just-null`). `parts` carries the five
    components so a result can be attributed to one.

    `nan` before the indicator's warm-up, never 0.0 - `absent-is-not-zero`,
    and a 0.0 in a bounded -1..+1 reading is a legitimate value that a mask
    cannot tell from a missing one.
    """

    reading: np.ndarray
    volatile: np.ndarray
    directional: np.ndarray
    parts: dict[str, np.ndarray]


def mood_path(series: Series, *, span: int = 0, warmup: int = 0) -> Mood:
    """`FearGreed` folded over every bar, as arrays.

    Driven through `update_raw`, which is the indicator's own public entry
    point, so what is measured here is what a registered indicator would
    publish. Defaults mean the module's defaults - `SPAN` 60, `WARMUP` 20 -
    and are **not tuned**: a window swept for a result is a cell count, and the
    pre-registration fixes them.
    """
    kwargs: dict[str, int] = {}
    if span:
        kwargs["span"] = span
    if warmup:
        kwargs["warmup"] = warmup
    fg = FearGreed(**kwargs)
    n = len(series.close)
    reading = np.full(n, np.nan)
    vol = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    parts = {name: np.full(n, np.nan) for name in HALVES}
    for i in range(n):
        fg.update_raw(
            float(series.open[i]),
            float(series.high[i]),
            float(series.low[i]),
            float(series.close[i]),
            float(series.ts[i]),
        )
        if not fg.initialized:
            continue
        reading[i] = fg.reading
        vol[i] = fg.volatile
        direction[i] = fg.directional
        for name, value in fg.parts.items():
            parts[name][i] = value
    return Mood(reading=reading, volatile=vol, directional=direction, parts=parts)


#: `FearGreed` components computed from closes alone, so exact on a synthetic
#: cross. The other three read the bar's range and are only meaningful on a
#: real instrument. Derived from `sentiment.py`'s own arithmetic: `pressure` is
#: a share of up and down closes, `skew` is downside against upside realised
#: volatility, and both see only the close series.
CLOSE_EXACT_PARTS = frozenset({"pressure", "skew"})


#: `FearGreed` components whose sign follows the pair's **quote convention**,
#: so the basket has to flip them per leg.
#:
#: `expansion` is the one that does not, and getting that wrong cancels the
#: basket. Ranges widen in a panic on **every** leg whichever way it is quoted,
#: so `expansion` goes negative on all six at once; flipping it by
#: `RISK_OFF_SIGN` would make audusd's and gold's contributions equal and
#: opposite, and the index would read a range explosion as zero. The other four
#: do flip: USDJPY closes near its trailing low in a panic where gold closes
#: near its high, and both are the same event.
FLIPS_WITH_QUOTE = frozenset({"position", "pressure", "conviction", "skew"})


@dataclass(frozen=True, slots=True)
class Basket:
    """The risk-off index, from the six real basket legs.

    **Every field is positive in risk-off, which is the opposite polarity to
    `FearGreed.reading`**, where -1 is fear. The names carry `_off` for that
    reason: a polarity confusion between an index and its own components is a
    bug that produces a plausible number, and `carry-the-sign` records this
    desk shipping `efficiency` unsigned and noting afterwards that the obvious
    way to trade it would have had the sign backwards.

    Built from real legs only, so every component has a true high and low and
    none of the synthetic-cross bound problem reaches the reading. That is the
    whole reason the index is a basket rather than a cross's own `FearGreed`.

    `volatile_off` and `directional_off` are kept apart for the reason
    `sentiment.py` keeps them apart, with one correction:
    `direction-is-closed-not-just-null` measured direction closed **as a
    standalone gate** and is not a result about direction conditioned on a
    volatility state. That conditioning is this study's open question, and this
    desk's own volatility-space results do pay - `the-clock-and-the-loop-
    compose` reads +1567 together against +848 and +518 apart - so the two are
    never averaged into one array here.

    `breadth` is how many of the six legs read risk-off at once, which is the
    one thing a published fear index has that a single instrument cannot:
    +0.4 on six legs is a different event from +0.4 on one.
    """

    risk_off: np.ndarray
    volatile_off: np.ndarray
    directional_off: np.ndarray
    breadth: np.ndarray
    legs: tuple[str, ...]


def basket_risk_off(moods: dict[str, Mood]) -> Basket:
    """The basket index: each component oriented to risk-off, then averaged.

    A `nanmean` over the legs present rather than a sum, so a leg short of
    warm-up reduces the denominator instead of pulling the index toward zero -
    `absent-is-not-zero`, and a zero in a bounded -1..+1 index is a real value.
    """
    legs = tuple(f for f in RISK_OFF_SIGN if f in moods)
    if not legs:
        raise ValueError(f"none of the basket legs {sorted(RISK_OFF_SIGN)} was read")
    oriented: dict[str, np.ndarray] = {}
    for part in HALVES:
        rows = []
        for feed in legs:
            sign = RISK_OFF_SIGN[feed] if part in FLIPS_WITH_QUOTE else -1.0
            rows.append(sign * moods[feed].parts[part])
        oriented[part] = np.vstack(rows)

    direction = [n for n, half in HALVES.items() if half == "direction"]
    volatility = [n for n, half in HALVES.items() if half == "volatility"]
    out = {
        "risk_off": _mean_over(oriented, list(HALVES)),
        "volatile_off": _mean_over(oriented, volatility),
        "directional_off": _mean_over(oriented, direction),
    }
    # Breadth counts legs, so each leg's own five components are averaged
    # first and the count is over legs - not over the 30 leg-component cells,
    # which would read a single leg's five agreeing parts as five legs.
    legwise = np.vstack(
        [_mean_over({n: oriented[n][i : i + 1] for n in HALVES}, list(HALVES)) for i in range(len(legs))]
    )
    good = np.isfinite(oriented["pressure"]).any(axis=0)
    breadth = (legwise > 0).sum(axis=0).astype(np.int8)
    for value in out.values():
        value[~good] = np.nan
    breadth[~good] = -1
    return Basket(breadth=breadth, legs=legs, **out)


def _mean_over(oriented: dict[str, np.ndarray], names: list[str]) -> np.ndarray:
    """Mean over legs and components, leaving an all-nan column as nan.

    Counted rather than handed to `np.nanmean`, which warns on an all-nan
    slice and returns nan anyway. The warm-up columns are all-nan by design,
    so the warning would fire on every series and train a reader to ignore
    one that mattered.
    """
    stack = np.vstack([np.atleast_2d(oriented[n]) for n in names])
    known = np.isfinite(stack)
    total = np.where(known, stack, 0.0).sum(axis=0)
    count = known.sum(axis=0)
    return np.where(count > 0, total / np.maximum(count, 1), np.nan)


# ────────────────────────────── the shape labels ──────────────────────────────

#: The label codes. `NEITHER` is kept rather than dropped so the four shares
#: are reportable: a label that fires on 2% of levels is a different object
#: from one that fires on 40%, and a harness that emits only its two arms hides
#: that.
CRASH, SPIKE, RUN, NEITHER = -1, 1, 2, 0

LABELS: dict[int, str] = {CRASH: "crash", SPIKE: "spike", RUN: "run", NEITHER: "neither"}

#: The efficiency a stretch needs to count as an along-trend run: net travel at
#: least half of gross travel over `trend.WINDOW` closes. Kaufman's ratio, via
#: `indicators.trend.ratio` - **not** `momentum.EfficiencyRatio`, whose
#: arithmetic reports `(period-1)/period` on a straight line.
RUN_EFFICIENCY = 0.50

#: Bars of Kaufman ratio behind the bar being labelled. `trend.WINDOW`.
RUN_WINDOW = 12

#: Bars of displacement window. `levels.SPAN` for `Displacement`, so a leg here
#: is the leg that indicator would publish.
SHAPE_SPAN = 40

#: How many bars back a displacement leg may have **ended** and still label
#: this bar. 5 at 1d.
#:
#: **Not zero, and the reason is a measurement.** Requiring the leg to cover
#: the bar itself labels 1.0% of audusd bars a crash and 1.0% a spike, and the
#: level books publish about 300 levels over 4,980 days - so the strict rule
#: gave **zero** crash-formed levels with a touch on audusd. The cause is not
#: rarity but anti-correlation: a level forms at a *pivot* and a displacement
#: is a *run*, so the two shapes avoid each other, which is
#: `smc-primitives-overlap-and-are-closed` from the other side. "A level formed
#: at a crash" means the crash left the level behind, so the leg has to have
#: just **finished**, and `reach` 3 pivot confirmation puts that within about
#: five bars. At 5 the classes reach 2.6-5.4% (crash) and 5.1-7.7% (spike) of
#: bars across audusd, usdjpy and gold, with under 0.3% labelled both.
#:
#: 0, 3 and 10 are reported as a sensitivity in the write-up, so the choice is
#: visible rather than implicit.
LABEL_REACH = 5


def shape_labels(series: Series, *, reach: int = LABEL_REACH) -> np.ndarray:
    """One label per bar: crash, spike, along-trend run, or neither.

    **The label is a property of the bar shape, not of any sentiment source.**
    There is no sentiment feed in this store, so the proxy is shape, and the
    three shapes are the user's: a spike, a crash and an along-trend run.

    * `CRASH` / `SPIKE` - a confirmed `Displacement` leg running down or up
      **ended within `reach` bars**. `levels.chains` at `push_min` 2,
      `push_body` 0.70, `chain_gap` 1, the module defaults untouched. Causal:
      the window is the trailing `SHAPE_SPAN` bars, so a leg is only seen once
      its last impulsive candle has printed.
    * `RUN` - no leg ended in reach, and Kaufman's ratio over the trailing
      `RUN_WINDOW` closes is at least `RUN_EFFICIENCY`: consistently one
      direction with hiccups, which is what an along-trend run is.
      `indicators.trend.ratio`, **not** `momentum.EfficiencyRatio`, which
      reports `(period-1)/period` on a straight line where the answer is 1.0.
    * `NEITHER` - the rest.

    A bar reached by both a down and an up leg is labelled `CRASH`, which is
    the rarer class (under 0.3% of bars are both), so the tie cannot inflate
    the class the claim is about.
    """
    n = len(series.close)
    out = np.full(n, NEITHER, dtype=np.int8)
    window: collections.deque[Candle] = collections.deque(maxlen=SHAPE_SPAN)
    ends = np.zeros(n, dtype=np.int8)
    for i in range(n):
        window.append(
            Candle(
                high=float(series.high[i]),
                low=float(series.low[i]),
                open=float(series.open[i]),
                close=float(series.close[i]),
                when=float(series.ts[i]),
            )
        )
        here = len(window) - 1
        for leg in chains(list(window)):
            if leg.end == here:
                ends[i] = leg.side
                break
    for i in range(n):
        recent = ends[max(0, i - reach) : i + 1]
        if (recent < 0).any():
            out[i] = CRASH
            continue
        if (recent > 0).any():
            out[i] = SPIKE
            continue
        if i + 1 >= RUN_WINDOW:
            eff = ratio(series.close[i + 1 - RUN_WINDOW : i + 1])
            if eff is not None and eff >= RUN_EFFICIENCY:
                out[i] = RUN
    return out


#: The fear/greed sign a label carries. A crash-formed level is a fear level, a
#: spike-formed one a greed level, and a run or neither is **not** a sentiment
#: statement, so both are 0 and are reported as their own classes.
SENTIMENT: dict[int, int] = {CRASH: -1, SPIKE: +1, RUN: 0, NEITHER: 0}


# ──────────────────────────────── the calendar ────────────────────────────────


def years(ts: np.ndarray) -> np.ndarray:
    """The calendar year of each bar, as an int array."""
    return np.asarray(
        [dt.datetime.fromtimestamp(t, tz=dt.UTC).year for t in ts], dtype=np.int32
    )


def days(ts: np.ndarray) -> np.ndarray:
    """The UTC day index of each bar. The block unit for every bootstrap here.

    Days and not bars, because trades and regime labels cluster inside a day
    and an ordinary standard error over overlapping bar anchors is far too
    narrow - the failure recorded in `overlapping-windows-inflate-permutation-
    nulls`.
    """
    return (ts // 86_400.0).astype(np.int64)


def era_of(ts: np.ndarray) -> np.ndarray:
    """The index into `ERAS` of each bar, or -1 outside every era."""
    year = years(ts)
    out = np.full(len(ts), -1, dtype=np.int8)
    for i, (_, lo, hi) in enumerate(ERAS):
        out[(year >= lo) & (year <= hi)] = i
    return out


def window_mask(ts: np.ndarray, start: str, end: str) -> np.ndarray:
    """Bars inside `[start, end]`, both `YYYY-MM-DD` and both inclusive."""
    lo = dt.datetime.fromisoformat(start).replace(tzinfo=dt.UTC).timestamp()
    hi = dt.datetime.fromisoformat(end).replace(tzinfo=dt.UTC).timestamp() + 86_400.0
    return (ts >= lo) & (ts < hi)


def strata(values: np.ndarray, count: int = 5) -> np.ndarray:
    """Quintiles of `values`, as `0..count-1`, with `nan` going to -1.

    Per arm and per cell, never pooled across arms: the arms have different
    volatility processes, so edges fitted on the real series and applied to a
    surrogate would misalign the bins and the control would be comparing
    different regimes.
    """
    out = np.full(len(values), -1, dtype=np.int8)
    good = np.isfinite(values)
    if good.sum() < count:
        return out
    edges = np.quantile(values[good], np.linspace(0.0, 1.0, count + 1)[1:-1])
    out[good] = np.searchsorted(edges, values[good], side="right").astype(np.int8)
    return out


def compression(series: Series, unit_span: int) -> np.ndarray:
    """Trailing compression: the volatility unit over its own longer average.

    The stratifier. Conditioning on a spike or a crash **selects on
    volatility**, because large bars cluster, so every gap in this study is
    reported within quintiles of this and never pooled alone -
    `topology-restates-volatility` and `auc-is-free-on-volatility-targets` are
    both that failure. Low means compressed.
    """
    unit = units(series, unit_span)
    slow = units(series, unit_span * 5)
    return np.where(slow > 0, unit / np.maximum(slow, 1e-300), np.nan)
