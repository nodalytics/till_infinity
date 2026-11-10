"""The four priceaction.com patterns as trade rules: detectors, fills, settlement.

The rules as the sources state them are frozen in
`research/docs/price-action-rules.md`, written before this file, with the
parameter below that encodes each clause and an explicit mark where the sources
specify nothing. The result is `research/docs/price-action.md`.

Run it with `price_action_run.py`; this module holds no driver.

## What is new here, and what is deliberately not measured

Four patterns - inside bar, pin bar, fakey, inside-pin combo - plus a
confluence factor count. The **rate** at which an inside bar occurs is already
measured in `inside-bars.md` and is not re-measured; what is new is the trade,
because the inside-bar page is the only one of fourteen that states both an
entry and a stop and nothing on this desk has priced it.

**No source states a target.** Not one of the fourteen pages. So the target is
`k` times the realised risk, `k` in `TARGETS`, where a driftless walk reaches
it with probability `1/(1+k)` and the expected R is **exactly zero at every
k** - which means no reward-to-risk can manufacture a result and the study
measures the entry and the stop the sources *do* specify. `patterns.md` had the
opposite situation: the books there supply a measured move, so a pattern could
be refused on its own geometry against `(1 + cost) / (1 + R:R)`. Here there is
no geometry to refuse.

## Three defects this file is shaped around

**The race starts on the bar after the fill.** `smc-conjunctions.md` reported
+0.432R on a driftless walk before this was fixed, which is impossible - a
walk is a martingale - because settling on the fill bar uses that bar's *other*
extreme, which may have printed before the entry touch. Measured there: 0.470
of 2R races won against a required 0.333. `settle` therefore starts at
`fill + 1`, and a tie inside one bar goes to the stop.

**A generated walk is not a sufficient null for a two-bar statistic.**
`inside-bars.md` measured it: ordering suppresses the inside-bar rate by
0.046-0.072 on an absolute rate of 0.15, and between a third and a half of
that is the deterministic hour-of-day cycle, which a generated series has none
of. `calendar_shuffle` is the arm that answers it and is not optional.

**A pattern is usually its own geometry.** `patterns.md`: the double bottom's
58% hit rate was matched by a placebo at 57.6% on the same stop and target
distances entered at a random bar. `matched` is that control, and it doubles as
the duty-cycle control because the comparison is mean R at a matched trade
count.
"""

from __future__ import annotations

import math
import os
import random
import statistics as st
from dataclasses import dataclass

import numpy as np

from research.ideas.level_shield import (
    ARMS as SHIELD_ARMS,
)
from research.ideas.level_shield import (
    COSTED,
    book_path,
    FEEDS,
    STORE,
    STRATA,
    Series,
    compression,
    units,
    venue_for,
)
from research.ideas.level_shield import (
    load as _shield_load,
)
from till_infinity.indicators import candles as C

try:
    from till_infinity.indicators import fuzzy as FZ
except ImportError:  # pragma: no cover - the graded arm needs #358
    #: `indicators/fuzzy.py` arrived in #358. The graded encoding is skipped
    #: rather than approximated where it is absent: a local copy of the
    #: grading would measure a different rule from the one that would trade,
    #: which is `reproduce-the-baseline-before-an-increment` exactly.
    FZ = None
from till_infinity.strategies.structure import Fold

__all__ = [
    "ARMS",
    "COSTED",
    "FEEDS",
    "PATTERNS",
    "SETTINGS",
    "STORE",
    "Trade",
    "calendar_shuffle",
    "cost_r",
    "desk_pin",
    "graded_pin",
    "SHAPES",
    "fakeys",
    "inside",
    "level_touch",
    "origin_agreement",
    "duplicate_share",
    "load",
    "placebo_trades",
    "pin",
    "retrace_band",
    "settle",
    "setups",
    "spread_bps",
    "trend_and_legs",
    "units",
    "venue_for",
]

#: Per interval: the forward horizon in bars, the span of the EWMA bar range
#: that is the volatility unit, and the calendar bucket the shuffle preserves.
#:
#: The horizon is `level_shield.SETTINGS`' so the two studies' races are the
#: same object. The bucket is the point of difference: at 1d an hour-of-day
#: profile does not exist, so what is preserved is the **weekday**, which is
#: the only deterministic cycle a daily bar has.
SETTINGS = {
    "15m": {"horizon": 48, "unit_span": 48, "bucket": "hour", "per_day": 96},
    "1h": {"horizon": 48, "unit_span": 48, "bucket": "hour", "per_day": 24},
    "4h": {"horizon": 30, "unit_span": 30, "bucket": "hour", "per_day": 6},
    "1d": {"horizon": 20, "unit_span": 20, "bucket": "weekday", "per_day": 1},
}

#: Targets as multiples of the **realised risk**, measured from the fill and
#: not from the pattern (`risk-vol-is-not-the-stop-distance`). A walk pays
#: exactly zero at every one of them, so a departure from zero is the finding.
TARGETS = (1.0, 2.0, 3.0)

#: The tail as a share of the **bar range**. The sources' own number is 2/3 -
#: LTTM's "the pin bar tail be two/thirds the total pin bar length or more" -
#: and priceaction.com gives none at all, so it is swept and the whole grid is
#: reported with its mean rather than the best cell with its z
#: (`sweep-thresholds-on-the-mean-not-z`).
TAIL_SHARES = (0.50, 0.60, 2.0 / 3.0, 0.75)

#: The method's own value, marked so a table can say which column is the
#: source's and which is this desk sweeping around it.
TAIL_SOURCE = 2.0 / 3.0

#: How many bars a pending stop or limit order stays live, counted from the
#: bar after the signal. **Neither source says**, and the strictest reading of
#: "when price breakouts above or below the mother bar, your entry order is
#: filled" is the next bar only. Swept.
EXPIRIES = (1, 2, 3)

#: The pad beyond the tail extreme, in volatility units. LTTM says "1 pip
#: below the low of the tail"; one pip is 0.01-0.02 of a daily volatility unit
#: on the majors, which is below the resolution this harness works in, so it
#: is encoded as a small unit pad and swept to zero rather than quoted as a
#: pip count the study cannot honour.
PIP_PADS = (0.0, 0.02)

#: The minimum risk a trade may carry, in volatility units. A near-zero-risk
#: entry is the recorded fill artefact in `walks-and-edge.md`, and the 50%
#: entries are exactly where it would appear. Refusals are counted, never
#: silently dropped.
MIN_RISK_VOL = 0.25

#: How close a bar has to come to a level to count as touching it, in
#: volatility units. `level_bounce.TOUCH_VOL`, unchanged, so the confluence
#: arm's level factor is the same object `level-bounce.md` measured.
TOUCH_VOL = 0.10

#: The placebo level's displacement from the real one, in volatility units,
#: and how close it may come to any real level. `level_bounce.placebo_books`'
#: numbers. `a-return-rate-is-geometry`: without this arm a hold rate means
#: nothing.
PLACEBO_LO, PLACEBO_HI, PLACEBO_CLEAR = 1.5, 3.0, 0.70

#: The EMA pair LTTM names: "I use the 8 and 21 day EMAs on the daily charts".
EMA_FAST, EMA_SLOW = 8, 21

#: The retrace band LTTM names: "I personally watch the 50% to 61.8% retrace
#: levels for another factor of confluence."
RETRACE_LO, RETRACE_HI = 0.50, 0.618

#: Swing reach for `Fold`, whose `trend` label is LTTM's HH/HL rule exactly.
#: Reused rather than re-derived: a second HH/HL definition would make these
#: numbers incomparable with the rule the desk trades, which is the whole of
#: `structure.md` and `bos-predict.md`. The reach is **unspecified by the
#: sources** and is swept.
REACHES = (2, 3, 5)

#: Confluence factor counts required. PA says only "the more confluent factors
#: behind a signal the higher-probability it is considered"; LTTM's filter page
#: gives "at least two supporting factors". Swept, with the census printed for
#: every count whether or not it scores - `smc-conjunctions.md`'s correction is
#: that a table which only prints cells reaching 200 setups silently contains
#: primitives while claiming to have tested conjunctions.
FACTOR_COUNTS = (0, 1, 2, 3)

#: Factor bits. A mask and not a partition: trend and the retrace band overlap
#: by construction, and `smc-primitives-overlap-and-are-closed` is why a
#: harness must not force them apart.
F_TREND, F_EMA, F_LEVEL, F_RETRACE = 1, 2, 4, 8

#: The patterns measured. `false_break` is absent on purpose: priceaction.com
#: gives it no bar count, no close-back requirement and no reference level, and
#: admits versions with no pattern in them, so it is refused as unspecified
#: rather than reported as null. Its one codeable clause - "wait for price to
#: close outside of the range for two days or more" - is the fakey's
#: `CLOSE_BACK` sweep.
PATTERNS = ("inside", "pin", "fakey", "combo")

#: Entry styles per pattern, each one a clause from a source rather than a
#: variant invented here. See `price-action-rules.md` for which source.
ENTRIES = {
    "inside": ("stop_mother",),
    "pin": ("market", "stop_nose", "limit50_bar", "limit50_tail"),
    "fakey": ("stop_back",),
    "combo": ("stop_mother", "stop_inside"),
}

#: Stop styles per pattern. `mother_50` is priceaction.com's own alternative
#: ("near the mother bar halfway point"); `fakey`'s two are a sweep because
#: **neither source states a fakey stop at all**.
STOPS = {
    "inside": ("mother_far", "mother_50"),
    "pin": ("tail",),
    "fakey": ("break_extreme", "mother_far"),
    "combo": ("mother_far", "inside_far"),
}

#: Sides taken. An inside bar is **sideless** - the sources give its direction
#: from the trend or from a level, never from the pattern - so long and short
#: are separate cells and `straddle` takes whichever fires first. A pin bar and
#: a fakey carry their own side and are measured only on it.
SIDES = {
    "inside": ("long", "short", "straddle", "with_trend"),
    "pin": ("own",),
    "fakey": ("own",),
    "combo": ("own", "with_trend"),
}


def load(con, feed: str, interval: str) -> Series | None:
    """`level_shield.load`, with duplicate timestamps collapsed.

    **Half of two feeds' daily history is printed twice**, and reading `n` as a
    claim about the world is what found it. `spx500` and `us100` at 1d on
    YAHOO - the venue the bar-count rule picks for both - carry **6,005 and
    6,008 rows over 3,006 and 3,009 distinct timestamps**, so 2,999 bars of
    each appear twice in a row. The tell was 503 bars a year on a daily series
    for an index that trades about 252 days: `slope_fade.py` is the recorded
    instance of the same check, where `n = 3159` on daily bars meant the file
    began in 1971. At 1h the same two feeds carry 6 duplicates each, which is
    negligible and is collapsed anyway.

    A duplicated bar is not a harmless repeat. The volatility unit is an EWMA
    over bars, so a doubled series halves its effective span; a 20-bar horizon
    covers ten real days; `Fold` confirms swings over doubled windows; and a
    first-passage search can resolve on the copy. Every statistic downstream is
    quoted in a unit that is not the one it names.

    **One accidental protection is worth recording**: `inside` refuses a pair
    with the same high *and* the same low, which is priceaction.com's own
    clause - "two bars with the same high and low ... is generally not
    considered an inside bar" - so the inside-bar detector was the one thing
    the duplicates could not fool.

    `level_shield.load` is **not** changed. It is the loader
    [`level-shield.md`](../docs/level-shield.md),
    [`level-bounce.md`](../docs/level-bounce.md) and
    [`stop-coverage.md`](../docs/stop-coverage.md) read, and changing it under
    them would silently alter three published panels; that those three read the
    same contaminated series on those two feeds at 1d is reported rather than
    fixed here.
    """
    got = _shield_load(con, feed, interval)
    if got is None:
        return None
    keep = np.concatenate(([True], np.diff(got.ts) > 0))
    if keep.all():
        return got
    return Series(
        feed=got.feed,
        venue=got.venue,
        interval=got.interval,
        ts=got.ts[keep],
        open=got.open[keep],
        high=got.high[keep],
        low=got.low[keep],
        close=got.close[keep],
    )


def duplicate_share(con, feed: str, interval: str) -> float:
    """What share of this feed's rows are a repeated timestamp.

    Printed per feed beside its bar count, because a bar count is a claim about
    the world and this is the claim's error bar.
    """
    got = _shield_load(con, feed, interval)
    if got is None or not len(got.ts):
        return float("nan")
    return 1.0 - len(np.unique(got.ts)) / len(got.ts)


# ───────────────────────────── the extra null arm ─────────────────────────────


def calendar_shuffle(series: Series, rng: random.Random, *, bucket: str = "hour") -> Series:
    """Bars permuted **within their calendar bucket**, so the daily cycle lives.

    The arm `a-pair-of-bars-needs-the-hour-of-day-null` asks for, and the one
    `level_shield.ARMS` does not have. `bar_shuffle` permutes globally, which
    destroys the hour-of-day reach profile along with the ordering; measured in
    `inside-bars.md`, that profile carries **0.018 to 0.028 of the 0.046 to
    0.072** suppression of the inside-bar rate - between a third and a half of
    the whole effect, and a term that is deterministic and knowable before the
    bar opens.

    So the inside bar, the fakey and the combo are compared against a null that
    keeps the cycle and nothing else. Each bar's own shape travels with it
    exactly, as in `bar_shuffle`, and the close path is rebuilt by chaining the
    permuted steps - the construction `inside-bars.md` used, where a bar's
    geometry is never altered and only its position is.

    `bucket` is "hour" on intraday bars and "weekday" at 1d, because a daily
    bar has no hour-of-day profile and the weekday is the only deterministic
    cycle it has.
    """
    n = len(series.close)
    steps = np.diff(series.close)
    span = series.high - series.low
    safe = np.maximum(span, 1e-12)
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)

    key = _bucket_key(series.ts, bucket)
    # Permute the step order and the shape order inside each bucket
    # independently, so a bar keeps its own time of day and loses its place in
    # the sequence.
    order = np.arange(n - 1)
    shapes = np.arange(n)
    for which, arr, keys in ((0, order, key[1:]), (1, shapes, key)):
        del which
        for b in np.unique(keys):
            at = np.flatnonzero(keys == b)
            picked = at.copy()
            rng.shuffle(picked)
            arr[at] = arr[picked]

    close = np.empty(n)
    close[0] = series.close[0]
    close[1:] = series.close[0] + np.cumsum(steps[order])
    width = span[shapes]
    low = close - frac_c[shapes] * width
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=low + frac_o[shapes] * width,
        high=low + width,
        low=low,
        close=close,
    )


def _bucket_key(ts: np.ndarray, bucket: str) -> np.ndarray:
    """Hour of day, or weekday, as an integer per bar."""
    if bucket == "weekday":
        return ((ts // 86_400) % 7).astype(int)
    return ((ts % 86_400) // 3600).astype(int)


def _calendar_arm(series: Series, rng: random.Random) -> Series:
    return calendar_shuffle(series, rng, bucket=SETTINGS[series.interval]["bucket"])


#: `level_shield.ARMS` plus the calendar-preserving shuffle. Imported whole
#: rather than re-listed so this harness and `level-shield.md` cannot drift
#: apart on what an arm is.
ARMS = {**SHIELD_ARMS, "calendar-shuffle": _calendar_arm}


# ───────────────────────────────── detectors ─────────────────────────────────


def inside(series: Series) -> np.ndarray:
    """Bars contained completely within the prior bar's high-low range.

    `high[i] <= high[i-1] and low[i] >= low[i-1]`, refusing the exact-equality
    pair: priceaction.com's inside-bar page says "if you have two bars with the
    same high and low, it's generally not considered an inside bar by most
    traders".
    """
    hi, lo = series.high, series.low
    out = np.zeros(len(hi), dtype=bool)
    if len(hi) < 2:
        return out
    contained = (hi[1:] <= hi[:-1]) & (lo[1:] >= lo[:-1])
    same = (hi[1:] == hi[:-1]) & (lo[1:] == lo[:-1])
    out[1:] = contained & ~same
    return out


def pin(series: Series, tail_share: float) -> tuple[np.ndarray, np.ndarray]:
    """`(bullish, bearish)` pin bars, as the **sources** define one.

    One clause and one number: the rejection tail is at least `tail_share` of
    the bar's **range**. That is LTTM's rule verbatim - "the pin bar tail be
    two/thirds the total pin bar length or more", with "the rest" being
    "one/third the total pin bar length or less" - and the two halves are one
    statement, not two thresholds.

    Its other clause, "the open and close of the pin bar are near one end of
    the bar", follows arithmetically: a lower tail of 2/3 of the range leaves
    the whole body inside the top third. So it is **not** a second parameter,
    and encoding it as one would be this desk inventing a rule.

    Neither source states an opposing-wick limit or a body-size floor. This
    repo's `candles.hammer` does, and it is carried as a separate arm in
    `desk_pin` rather than substituted here: `smc-primitives-overlap-and-
    are-closed` is measured on this desk and two detectors with the same name
    are usually two detectors.
    """
    raw_bull, raw_bear = _pin_raw(series, tail_share)
    # A bar firing both ways has no side the rule can trade, which can only
    # happen at `tail_share <= 0.5` on a bar with no body. Dropped from both,
    # and the count travels out of `setups` as `Census.ambiguous`.
    both = raw_bull & raw_bear
    return raw_bull & ~both, raw_bear & ~both


def _pin_raw(series: Series, tail_share: float) -> tuple[np.ndarray, np.ndarray]:
    """The tail clause alone, before a two-sided bar is removed."""
    rng_ = series.high - series.low
    body_hi = np.maximum(series.open, series.close)
    body_lo = np.minimum(series.open, series.close)
    live = rng_ > 0
    bull = live & ((body_lo - series.low) >= tail_share * rng_)
    bear = live & ((series.high - body_hi) >= tail_share * rng_)
    return bull, bear


def desk_pin(series: Series) -> tuple[np.ndarray, np.ndarray]:
    """`(hammer, shooting_star)` as `indicators/candles.py` defines them.

    The desk's own encoding, carried as an arm so the source's one-clause rule
    and this repo's three-clause rule are visible side by side instead of one
    standing in for the other. `test_price_action.py` pins this against
    `candles.hammer` and `candles.shooting_star` bar by bar, because a
    vectorised copy of a production predicate is a reimplementation and a test
    that does not compare them tests the copy.
    """
    rng_ = series.high - series.low
    body_hi = np.maximum(series.open, series.close)
    body_lo = np.minimum(series.open, series.close)
    lower = body_lo - series.low
    upper = series.high - body_hi
    live = rng_ > 0
    bull = (
        live
        & (lower >= rng_ * C.TAIL_SHARE)
        & (upper <= rng_ * C.STUB_SHARE)
        & ((series.high - body_lo) <= rng_ * C.BODY_THIRD)
    )
    bear = (
        live
        & (upper >= rng_ * C.TAIL_SHARE)
        & (lower <= rng_ * C.STUB_SHARE)
        & ((body_hi - series.low) <= rng_ * C.BODY_THIRD)
    )
    return bull, bear


def graded_pin(
    series: Series,
    *,
    tail: int | None = None,
    stub: int | None = None,
    body: int | None = None,
    period: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """`(bullish, bearish)` pin bars graded **against the bar's own window**.

    `indicators/fuzzy.pin` over `fuzzy.grade_window`, which drives Nautilus's
    `FuzzyCandlesticks.update_raw` - the framework's own entry point, so this
    is the arithmetic the live indicator runs rather than a copy of it.

    **This arm is the control for a confound the fixed-fraction rule inherits.**
    `how-markets-differ-from-every-simple-process` measured real bars as
    *wickier* than every simple process - a body share of 0.43-0.50 against
    0.55 for the best-fitting families - so a tail threshold stated as a
    fraction of the range fires more often on real data than on a walk for
    mechanical reasons, and a rule built on one inherits that as an apparent
    edge. A grade relative to the last `period` bars' own mean and standard
    deviation is normalised against exactly that. Both encodings are run: if
    the fixed one beats its walk and the graded one does not, the finding is
    the confound.

    It also dissolves the threshold no source states. The knobs are **ordinals
    with four values each** rather than a continuum, so the multiplicity the
    sweep costs is small and countable.

    Two behaviours inherited from the module and worth stating because they
    change the population: the grade is `None` below `period` bars, so the
    first `period` bars can never fire; and a bar whose open equals its close
    is a `candles.hammer` but **not** a graded pin, because `direction` is 0
    and a bar with no direction has no side for a rejection to be on.
    """
    n = len(series.close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)
    if FZ is None:
        return bull, bear
    kw = {
        "tail": FZ.PIN_TAIL if tail is None else tail,
        "stub": FZ.PIN_STUB if stub is None else stub,
        "body": FZ.PIN_BODY if body is None else body,
    }
    span = FZ.PERIOD if period is None else period
    rows = list(
        zip(
            series.open.tolist(),
            series.high.tolist(),
            series.low.tolist(),
            series.close.tolist(),
            strict=True,
        )
    )
    for i in range(span - 1, n):
        grade = FZ.grade_window(rows[i - span + 1 : i + 1], period=span)
        if grade is None:
            continue
        bull[i] = FZ.pin(grade, True, **kw)
        bear[i] = FZ.pin(grade, False, **kw)
    return bull, bear


#: The pin-bar encodings compared. `source` is the one clause the sources
#: state (a tail share of the range, LTTM's 2/3); `desk` is this repo's
#: `candles.hammer`, which adds an opposing-wick limit and a body position the
#: sources never mention; `graded` is `fuzzy.pin`, window-relative.
#:
#: Three encodings and not one, because `smc-primitives-overlap-and-are-closed`
#: is measured on this desk and two detectors with the same name are usually
#: two detectors - and because the fixed-fraction forms carry a known
#: confound the graded one does not.
SHAPES = ("source", "desk", "graded")

#: Graded knobs swept, as ordinals. `fuzzy.WICK_*` and `fuzzy.BODY_*` are the
#: enum values; the numbers are repeated here only so this module imports
#: without #358 present.
GRADED_TAILS = (1, 2, 3)
GRADED_STUBS = (0, 1, 2)
GRADED_BODIES = (1, 2, 3)


@dataclass(frozen=True, slots=True)
class Fake:
    """One fakey: the inside bar, the false break, and the trigger price."""

    #: The inside bar's index; its mother is `at - 1`.
    at: int
    #: The last bar of the false break - the one that closed back inside.
    done: int
    #: +1 for a bullish fakey (the false break was **down**).
    side: int
    #: The price the entry order rests at.
    trigger: float
    #: The extreme the false break reached, for the `break_extreme` stop.
    extreme: float


def fakeys(
    series: Series,
    inside_mask: np.ndarray,
    *,
    break_ref: str = "inside",
    close_back: str = "mother",
    fake_bars: int = 1,
) -> list[Fake]:
    """False breaks of an inside bar that close back inside.

    priceaction.com: "if an inside bar pattern breaks out briefly but then
    reverses and closes back within the range of the mother bar", and the entry
    is "as price breaks back past the inside bar or mother bar low or high".
    The source says **"or"** in both places, so `break_ref` and `close_back`
    are swept over `inside` and `mother` rather than chosen.

    `fake_bars` is 1 or 2: the page allows a one-bar false break and "a two-bar
    pattern" where "the subsequent bar completes the false-break by closing
    back within the range".

    The trigger is the **opposite** extreme of `break_ref` from the false
    break, which is what "breaks back past" means - a false break down is
    entered long on a move up through the inside bar's (or mother bar's) high.
    """
    hi, lo, close = series.high, series.low, series.close
    out: list[Fake] = []
    at_ = np.flatnonzero(inside_mask)
    for i in at_:
        if i < 1:
            continue
        m = i - 1
        ref_hi = hi[i] if break_ref == "inside" else hi[m]
        ref_lo = lo[i] if break_ref == "inside" else lo[m]
        back_hi = hi[m] if close_back == "mother" else hi[i]
        back_lo = lo[m] if close_back == "mother" else lo[i]
        j = i + fake_bars
        if j >= len(hi):
            continue
        window = slice(i + 1, j + 1)
        broke_dn = bool(np.any(lo[window] < ref_lo))
        broke_up = bool(np.any(hi[window] > ref_hi))
        # One side only. A window that poked through both ends is not a false
        # break, it is a wide bar, and admitting it would let the trigger be
        # chosen after the fact.
        if broke_dn == broke_up:
            continue
        closed_back = back_lo <= close[j] <= back_hi
        if not closed_back:
            continue
        if broke_dn:
            out.append(
                Fake(
                    at=int(i),
                    done=int(j),
                    side=1,
                    trigger=float(ref_hi),
                    extreme=float(np.min(lo[window])),
                )
            )
        else:
            out.append(
                Fake(
                    at=int(i),
                    done=int(j),
                    side=-1,
                    trigger=float(ref_lo),
                    extreme=float(np.max(hi[window])),
                )
            )
    return out


# ──────────────────────────── the context readings ────────────────────────────


@dataclass(slots=True)
class Context:
    """The causal readings a confluence factor is counted from.

    Every array is a function of bars strictly at or before its own index.
    """

    trend: np.ndarray
    ema_lo: np.ndarray
    ema_hi: np.ndarray
    #: The 50-61.8% retrace band of the last confirmed swing leg, as
    #: `(low, high)`; NaN before a leg exists.
    retr_lo: np.ndarray
    retr_hi: np.ndarray


def trend_and_legs(series: Series, reach: int) -> Context:
    """`Fold`'s trend label and the retrace band of its last confirmed leg.

    `Fold` is this repo's own causal HH/HL reading - LTTM's "an uptrend if it
    is making Higher Highs and Higher Lows (HH, HL)" with a swing detector
    attached, since the source gives none. Reused rather than re-derived
    because a second derivation would make this study's trend filter
    incomparable with the one `structure.md` and `bos-predict.md` measured and
    the desk trades.
    """
    n = len(series.close)
    fold = Fold(reach=reach)
    trend = np.zeros(n, dtype=int)
    retr_lo = np.full(n, np.nan)
    retr_hi = np.full(n, np.nan)
    ema_lo = np.empty(n)
    ema_hi = np.empty(n)
    fast = slow = float(series.close[0])
    a_f = 2.0 / (EMA_FAST + 1.0)
    a_s = 2.0 / (EMA_SLOW + 1.0)
    for i in range(n):
        fold.update(float(series.high[i]), float(series.low[i]), float(series.close[i]))
        trend[i] = fold.trend
        if fold.high > 0.0 and fold.low > 0.0 and fold.high > fold.low:
            leg = fold.high - fold.low
            if fold.trend >= 0:
                # An up leg retraces downward from its high.
                retr_lo[i] = fold.high - RETRACE_HI * leg
                retr_hi[i] = fold.high - RETRACE_LO * leg
            else:
                retr_lo[i] = fold.low + RETRACE_LO * leg
                retr_hi[i] = fold.low + RETRACE_HI * leg
        fast += a_f * (float(series.close[i]) - fast)
        slow += a_s * (float(series.close[i]) - slow)
        ema_lo[i] = min(fast, slow)
        ema_hi[i] = max(fast, slow)
    return Context(trend=trend, ema_lo=ema_lo, ema_hi=ema_hi, retr_lo=retr_lo, retr_hi=retr_hi)


def level_touch(
    series: Series, unit: np.ndarray, *, placebo: bool = False, seed: int = 0
) -> np.ndarray:
    """Whether the level book **as of the previous bar** reaches into this bar.

    `level_bounce.TOUCH_VOL` 0.10 units, and the book read at `i - 1` so the
    level existed before the bar that touched it. The static horizontal
    support-and-resistance factor from LTTM's confluence list, measured through
    `level_shield.book_path` - the repo's own `Levels`, bar by bar - so this
    study does not invent a fifth definition of a level and its numbers stay
    comparable with `level-bounce.md`'s.

    `placebo` displaces every level by a random 1.5-3.0 units, rejecting any
    displacement landing within 0.70 units of a real level. Without that arm a
    touch rate is geometry: `fade-to-value`'s 82% return was matched by a
    distance-matched placebo on every class, and `a-return-rate-is-geometry` is
    the recorded form of it. `the-placebo-arm-selects-the-null` is the reading
    rule - a null whose placebo arm itself finds structure is rejected.
    """
    n = len(series.close)
    out = np.zeros(n, dtype=bool)
    books = book_path(series, unit_span=int(SETTINGS[series.interval]["unit_span"]))
    rng = random.Random(seed)
    for i in range(1, n):
        prices = [p for p, _ in books[i - 1]]
        if not prices:
            continue
        u = max(float(unit[i]), 1e-12)
        if placebo:
            moved = []
            for p in prices:
                sign = 1.0 if rng.random() < 0.5 else -1.0
                q = p + sign * rng.uniform(PLACEBO_LO, PLACEBO_HI) * u
                if all(abs(q - r) > PLACEBO_CLEAR * u for r in prices):
                    moved.append(q)
            prices = moved
        tol = TOUCH_VOL * u
        lo, hi = float(series.low[i]) - tol, float(series.high[i]) + tol
        out[i] = any(lo <= p <= hi for p in prices)
    return out


def retrace_band(ctx: Context, series: Series, i: int) -> bool:
    """Whether this bar's range reaches the 50-61.8% retrace band."""
    lo, hi = ctx.retr_lo[i], ctx.retr_hi[i]
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return False
    return bool(series.low[i] <= hi and series.high[i] >= lo)


# ────────────────────────────── the trade itself ──────────────────────────────


@dataclass(frozen=True, slots=True)
class Trade:
    """One trade, as entered and as stopped - before any outcome is known."""

    signal: int
    fill: int
    side: int
    entry: float
    stop: float
    risk: float
    factors: int
    stratum: int
    day: int


@dataclass(slots=True)
class Census:
    """Why a setup did not become a trade. Printed whether or not a cell scores.

    `smc-conjunctions.md`'s correction: its first table printed only cells
    reaching 200 setups, so the arms the study existed for produced no rows and
    the document claimed to have tested conjunctions it had never reached. The
    binding constraint there was one filter firing 3 times in 16 cells, and the
    only way to see that is to count.
    """

    signals: int = 0
    ambiguous: int = 0
    no_fill: int = 0
    thin_risk: int = 0
    overlapped: int = 0
    trades: int = 0


def setups(
    series: Series,
    unit: np.ndarray,
    strata: np.ndarray,
    ctx: Context,
    *,
    pattern: str,
    entry: str,
    stop: str,
    side_rule: str,
    tail_share: float = TAIL_SOURCE,
    expiry: int = 3,
    pip_pad: float = 0.02,
    shape: str = "source",
    break_ref: str = "inside",
    close_back: str = "mother",
    fake_bars: int = 1,
    at_level: np.ndarray | None = None,
    pins: tuple[np.ndarray, np.ndarray] | None = None,
    anchors: np.ndarray | None = None,
    fill_at: str = "trigger",
    horizon: int = 20,
) -> tuple[list[Trade], Census]:
    """Every trade one (pattern, entry, stop, side) rule produces on one series.

    **One live trade at a time per cell.** A desk cannot hold two of the same
    setup, and two scored trades sharing outcome bars is the leak
    `overlapping-outcome-windows-leak` records - a direction AUC of 0.79 that
    collapsed to 0.51. The refusals are counted in `Census.overlapped` rather
    than dropped in silence.

    **`fill_at` is the leak this file was rewritten for, and the bug is worth
    the paragraph.** The sources' entries are resting *stop* orders - "place a
    buy stop or sell stop at the high or low of the mother bar" - so a fill
    happens mid-bar at the trigger price while bar-level data cannot say where
    in the bar. The first version of this harness entered at the trigger and
    began the race at `fill + 1`, which hands the trade the whole favourable
    displacement from the trigger to that bar's close for free: conditional on
    a buy stop filling, the bar closed *above* the trigger on average, so the
    race starts nearer the target and further from the stop. On a martingale
    that is an edge out of nothing, and measured on a driftless walk built at
    sub-bar resolution it is **+0.2234R +- 0.0541 over 743 races at a 2R
    target** - the figure
    `test_a_walk_pays_nothing_against_its_own_matched_placebo` pins. On the
    markets it read about +0.25R against a random entry at a bar's close while
    their own surrogates read -0.24R, and that sign flip between a market and
    its own GARCH twin was the tell, since no ordering property can produce
    one.

    So two settlements are carried and both are reported:

    * `trigger` - the sources' rule as stated, which is only readable against
      a placebo entered **through the same mechanics** (see `matched`);
    * `close` - entry at the fill bar's close, which is leak-free because the
      entry price and the first bar of the race are the same instant. It is
      [`level-bounce.md`](../docs/level-bounce.md)'s choice for the same
      reason, and it is a different and worse trade: a bar that ran a long way
      past the trigger buys a wider stop and a worse R, as it would live
      (`risk-vol-is-not-the-stop-distance`).

    `anchors` replaces the detector with a given set of bars, which is how
    `matched` runs the placebo through this exact construction instead of a
    second implementation of it.
    """
    cen = Census()
    out: list[Trade] = []
    n = len(series.close)
    inside_mask = inside(series)
    if pins is not None:
        # Precomputed by the caller, because `graded_pin` rebuilds a
        # `FuzzyCandlesticks` per bar and a series carries several cells.
        bull, bear = pins
        cen.ambiguous = 0
    elif shape == "desk":
        bull, bear = desk_pin(series)
        cen.ambiguous = 0
    elif shape == "graded":
        bull, bear = graded_pin(series)
        cen.ambiguous = 0
    else:
        raw_bull, raw_bear = _pin_raw(series, tail_share)
        both = raw_bull & raw_bear
        bull, bear = raw_bull & ~both, raw_bear & ~both
        cen.ambiguous = int(both.sum())
    if anchors is not None:
        # The placebo arm: the same entry mechanics at given bars. Substituting
        # the detector's own masks is what makes it the same code path, so the
        # real arm and its placebo cannot differ by their construction.
        picked = np.zeros(n, dtype=bool)
        at = anchors[(anchors >= 1) & (anchors < n - 1)]
        picked[at] = True
        sides = np.zeros(n, dtype=int)
        sides[at] = np.where(np.arange(len(at)) % 2 == 0, 1, -1)
        inside_mask = picked
        bull = picked & (sides > 0)
        bear = picked & (sides < 0)
        cen.ambiguous = 0
    day = (series.ts // 86_400).astype(int)
    busy_until = -1

    def factors_at(i: int, s: int) -> int:
        got = 0
        if ctx.trend[i] == s:
            got |= F_TREND
        if series.low[i] <= ctx.ema_hi[i] and series.high[i] >= ctx.ema_lo[i]:
            got |= F_EMA
        if at_level is not None and at_level[i]:
            got |= F_LEVEL
        if retrace_band(ctx, series, i):
            got |= F_RETRACE
        return got

    def emit(i: int, s: int, trigger: float, protect: float, kind: str) -> None:
        """One candidate: find its fill, check its risk, record it or why not."""
        nonlocal busy_until
        cen.signals += 1
        if i <= busy_until:
            cen.overlapped += 1
            return
        got = _fill(series, i, s, trigger, kind, expiry)
        if got is None:
            cen.no_fill += 1
            return
        j, price = got
        if fill_at == "close":
            price = float(series.close[j])
        risk = abs(price - protect)
        if risk < MIN_RISK_VOL * float(unit[i]):
            cen.thin_risk += 1
            return
        f = factors_at(i, s)
        out.append(
            Trade(
                signal=int(i),
                fill=int(j),
                side=s,
                entry=float(price),
                stop=float(protect),
                risk=float(risk),
                factors=f,
                stratum=int(strata[i]),
                day=int(day[i]),
            )
        )
        cen.trades += 1
        busy_until = j + horizon

    if pattern in ("inside", "combo"):
        at_ = np.flatnonzero(inside_mask)
        for i in at_:
            if i < 1 or i + 1 >= n:
                continue
            if pattern == "combo" and not (bull[i] or bear[i]):
                continue
            m = i - 1
            mid = 0.5 * (series.high[m] + series.low[m])
            wants: list[int] = []
            if pattern == "combo":
                wants = [1 if bull[i] else -1]
                if side_rule == "with_trend" and ctx.trend[i] != wants[0]:
                    continue
            elif side_rule == "long":
                wants = [1]
            elif side_rule == "short":
                wants = [-1]
            elif side_rule == "straddle":
                wants = [1, -1]
            elif side_rule == "with_trend":
                if ctx.trend[i] == 0:
                    continue
                wants = [int(ctx.trend[i])]
            for s in wants:
                if entry == "stop_inside":
                    trigger = float(series.high[i] if s > 0 else series.low[i])
                else:
                    trigger = float(series.high[m] if s > 0 else series.low[m])
                if stop == "mother_50":
                    protect = float(mid)
                elif stop == "inside_far":
                    protect = float(series.low[i] if s > 0 else series.high[i])
                else:
                    protect = float(series.low[m] if s > 0 else series.high[m])
                emit(i, s, trigger, protect, "stop")
    elif pattern == "pin":
        # Over the firing bars, not over every bar. The placebo arm runs this
        # twenty times per cell, so an `n`-long Python loop here was the whole
        # cost of the panel: a 5,000-bar series at 92 cells and 17 arm-draws is
        # 156 million iterations a job, and the run had produced no output at
        # all after fifteen minutes on 26 cores.
        for i in np.flatnonzero(bull | bear):
            s = 1 if bull[i] else -1
            if i + 1 >= n:
                continue
            pad = pip_pad * float(unit[i])
            tail_end = float(series.low[i] - pad if s > 0 else series.high[i] + pad)
            if entry == "market":
                trigger, kind = float(series.close[i]), "market"
                protect = tail_end
            elif entry == "stop_nose":
                trigger, kind = float(series.high[i] if s > 0 else series.low[i]), "stop"
                protect = tail_end
            elif entry == "limit50_bar":
                trigger = 0.5 * float(series.high[i] + series.low[i])
                kind = "limit"
                protect = float(series.low[i] if s > 0 else series.high[i])
            else:
                body = float(
                    min(series.open[i], series.close[i])
                    if s > 0
                    else max(series.open[i], series.close[i])
                )
                trigger = 0.5 * (body + float(series.low[i] if s > 0 else series.high[i]))
                kind = "limit"
                protect = float(series.low[i] if s > 0 else series.high[i])
            emit(i, s, trigger, protect, kind)
    else:
        found = (
            _anchor_fakes(series, inside_mask, bull)
            if anchors is not None
            else fakeys(
                series,
                inside_mask,
                break_ref=break_ref,
                close_back=close_back,
                fake_bars=fake_bars,
            )
        )
        for fk in found:
            if fk.done + 1 >= n:
                continue
            protect = (
                fk.extreme
                if stop == "break_extreme"
                else float(series.low[fk.at - 1] if fk.side > 0 else series.high[fk.at - 1])
            )
            emit(fk.done, fk.side, fk.trigger, protect, "stop")
    return out, cen


def _anchor_fakes(series: Series, picked: np.ndarray, bull: np.ndarray) -> list[Fake]:
    """A fakey's geometry at given bars, for the placebo arm.

    The bar itself stands in for the whole three-bar pattern: its own extreme
    is the trigger and its opposite extreme the false break. That keeps the
    entry mechanics, the stop placement and the expiry identical to the real
    arm, which is the only property the placebo has to have.
    """
    out: list[Fake] = []
    for i in np.flatnonzero(picked):
        if i < 1 or i + 1 >= len(series.close):
            continue
        side = 1 if bull[i] else -1
        out.append(
            Fake(
                at=int(i),
                done=int(i),
                side=side,
                trigger=float(series.high[i] if side > 0 else series.low[i]),
                extreme=float(series.low[i] if side > 0 else series.high[i]),
            )
        )
    return out


def _fill(
    series: Series, i: int, side: int, trigger: float, kind: str, expiry: int
) -> tuple[int, float] | None:
    """`(fill bar, fill price)` for a resting order, or None if it never filled.

    A stop order fills at its trigger unless the bar opened past it, in which
    case it fills at the open - which is the honest reading of a gap and the
    one that charges the trade for it. A limit fills at its price, because a
    bar that traded through a resting limit filled it there.
    """
    if kind == "market":
        return i, float(series.close[i])
    for j in range(i + 1, min(i + 1 + expiry, len(series.close))):
        if kind == "stop":
            if side > 0 and series.high[j] >= trigger:
                return j, float(max(trigger, series.open[j]))
            if side < 0 and series.low[j] <= trigger:
                return j, float(min(trigger, series.open[j]))
        else:
            if side > 0 and series.low[j] <= trigger:
                return j, float(min(trigger, series.open[j]))
            if side < 0 and series.high[j] >= trigger:
                return j, float(max(trigger, series.open[j]))
    return None


# ────────────────────────────── the barrier test ──────────────────────────────


@dataclass(frozen=True, slots=True)
class Settled:
    """One cell's races, flat so aggregation is a mask."""

    r: np.ndarray
    won: np.ndarray
    decided: np.ndarray
    tie: np.ndarray
    day: np.ndarray
    stratum: np.ndarray
    side: np.ndarray
    factors: np.ndarray
    risk_vol: np.ndarray

    def __len__(self) -> int:
        return len(self.r)


def settle(
    series: Series, trades: list[Trade], unit: np.ndarray, *, target: float, horizon: int
) -> Settled:
    """Did the target arrive before the stop, **starting the bar after the fill**.

    This is the one line `smc-conjunctions.md` paid for. Its first run reported
    +0.432R on a driftless walk, which cannot happen - a walk is a martingale -
    because the race began on the fill bar, and that bar's *other* extreme may
    have printed before the entry touch. Measured there: a 2R race won 0.470 of
    the time against a required 0.333, and 0.251 against 0.250 once fixed.

    A tie inside one bar goes to the **stop**. Bar-level first passage cannot
    say which barrier a bar reached first, so the conservative rule is the only
    honest one, and it biases against the target hardest where the stop is
    tight. `tie` travels out so any pattern across stop widths is read against
    it.

    An undecided race - neither barrier inside the horizon - is **dropped**
    rather than scored a loss, which is `level_bounce.race`'s rule and
    `Visit.broke_edge`'s argument: a vertical barrier that expires is not a
    stop-out.
    """
    r = np.zeros(len(trades))
    won = np.zeros(len(trades), dtype=bool)
    decided = np.zeros(len(trades), dtype=bool)
    tie = np.zeros(len(trades), dtype=bool)
    day = np.zeros(len(trades), dtype=int)
    stratum = np.zeros(len(trades), dtype=int)
    side = np.zeros(len(trades), dtype=int)
    factors = np.zeros(len(trades), dtype=int)
    risk_vol = np.zeros(len(trades))
    hi, lo = series.high, series.low
    for k, t in enumerate(trades):
        day[k], stratum[k], side[k], factors[k] = t.day, t.stratum, t.side, t.factors
        risk_vol[k] = t.risk / max(float(unit[t.signal]), 1e-12)
        goal = t.entry + t.side * target * t.risk
        start, end = t.fill + 1, min(t.fill + 1 + horizon, len(hi))
        if start >= end:
            continue
        up = hi[start:end]
        dn = lo[start:end]
        if t.side > 0:
            hit_t = np.flatnonzero(up >= goal)
            hit_s = np.flatnonzero(dn <= t.stop)
        else:
            hit_t = np.flatnonzero(dn <= goal)
            hit_s = np.flatnonzero(up >= t.stop)
        first_t = int(hit_t[0]) if len(hit_t) else 10**9
        first_s = int(hit_s[0]) if len(hit_s) else 10**9
        if first_t == 10**9 and first_s == 10**9:
            continue
        decided[k] = True
        tie[k] = first_t == first_s
        won[k] = first_t < first_s
        r[k] = target if won[k] else -1.0
    return Settled(
        r=r,
        won=won,
        decided=decided,
        tie=tie,
        day=day,
        stratum=stratum,
        side=side,
        factors=factors,
        risk_vol=risk_vol,
    )


def placebo_trades(
    series: Series,
    unit: np.ndarray,
    strata: np.ndarray,
    ctx: Context,
    *,
    signals: int,
    horizon: int,
    draws: int = 20,
    seed: int = 0,
    **kw,
) -> list[Trade]:
    """The same rule's **mechanics** at random bars. The arm that decides.

    `patterns.md` is why a placebo is not optional: the double bottom's 58% hit
    rate was matched by a placebo at **57.6%** on the same stop and target
    distances taken at an arbitrary bar, and the whole of that number was a
    0.87:1 payoff doing arithmetic. Twenty draws per setup, because one draw
    was that study's first version and was too noisy to carry the comparison
    everything rests on.

    **It runs through `setups`, not beside it**, which is the correction the
    first version of this file needed. A placebo that entered at a random
    bar's close while the real arm rested a stop order at a breakout price was
    comparing two entry *mechanics*, not two *populations* - and the mechanic
    is worth about a quarter of an R on its own, because a stop order that
    fills mid-bar is handed that bar's remaining favourable move for free.
    Driving the identical construction at random anchors means the mechanic
    appears in both arms and cancels in the difference, so what is left is the
    only thing the study is about: whether the **pattern** selected the bar.

    It is also the **duty-cycle control**. On a net-negative book any rule that
    trades less shows a profit improvement, so the comparison is mean R per
    trade; the placebo's larger sample buys it a tighter error bar and nothing
    else.
    """
    n = len(series.close)
    rng = np.random.default_rng(seed)
    out: list[Trade] = []
    low, high = 20, max(21, n - horizon - 2)
    for _ in range(draws):
        anchors = rng.integers(low, high, size=max(signals, 1))
        trades, _ = setups(
            series, unit, strata, ctx, anchors=np.sort(anchors), horizon=horizon, **kw
        )
        out.extend(trades)
    return out


def origin_agreement(
    series: Series, ctx: Context, unit: np.ndarray, *, tolerances=(0.10, 0.25, 0.50), look: int = 20
) -> dict:
    """Is "the 50% retrace of the last major move" the displacement origin?

    The brief's question, measured rather than assumed. LTTM offers "the 50%
    retrace of the last major move" as a confluence factor;
    [`displacement-origin.md`](../docs/displacement-origin.md) defines the
    displacement origin as the halfway mark of the **displacing body** and the
    fade to it is closed - 0 of 105 cells with a positive lower bound, and the
    82% return rate is a statement about *distance*, matched by a price-matched
    placebo on every class.

    They are different constructions by definition: a swing leg spans many
    bars, a displacing body is one. So this reports how often they are
    nevertheless the **same price**, within a tolerance in volatility units,
    against two readings of the origin:

    * `body_mid` - the midpoint of the impulsive bar's body, which is the
      object the 82% was measured on;
    * `close` - where the origin candle closed, which is what production's
      `Origin.line` actually is and a different object again, as that write-up
      says in its own words.

    A third column is the control the comparison needs: the agreement rate a
    **random prior bar's** body midpoint achieves at the same distance. Two
    prices computed off the same series agree at some rate for free, and
    without that column a high agreement rate says nothing.
    """
    n = len(series.close)
    rng_ = series.high - series.low
    body = np.abs(series.close - series.open)
    impulsive = (rng_ > 0) & (body / np.maximum(rng_, 1e-12) >= 0.70)
    body_mid = 0.5 * (series.open + series.close)
    picker = np.random.default_rng(0)
    out: dict = {"tolerances": list(tolerances), "n": 0, "agree": {}, "control": {}}
    hits = {t: 0 for t in tolerances}
    ctrl = {t: 0 for t in tolerances}
    close_hits = {t: 0 for t in tolerances}
    total = 0
    for i in range(look, n):
        retr = 0.5 * (ctx.retr_lo[i] + ctx.retr_hi[i])
        if not math.isfinite(retr):
            continue
        window = np.flatnonzero(impulsive[max(0, i - look) : i]) + max(0, i - look)
        if not len(window):
            continue
        j = int(window[-1])
        total += 1
        u = max(float(unit[i]), 1e-12)
        other = int(picker.integers(max(1, i - look), i))
        for t in tolerances:
            hits[t] += abs(retr - body_mid[j]) <= t * u
            close_hits[t] += abs(retr - series.close[j]) <= t * u
            ctrl[t] += abs(retr - body_mid[other]) <= t * u
    out["n"] = total
    if total:
        out["agree"] = {str(t): hits[t] / total for t in tolerances}
        out["agree_close"] = {str(t): close_hits[t] / total for t in tolerances}
        out["control"] = {str(t): ctrl[t] / total for t in tolerances}
    return out


# ─────────────────────────────── cost, in R ───────────────────────────────


def spread_bps(con, feed: str, venue: str) -> float:
    """The median recorded bid/ask for this feed on this venue, in basis points.

    `node/corpus.spread_bps` by the same query, **per venue and never pooled**:
    the same instrument runs 0.17 to 3.30 bps across six venues, a nineteenfold
    range, and `pooled-medians-invert-subgroups` is the recorded lesson. Zero
    where there are no quotes, which is how a feed ends up geometry-only rather
    than priced off a guess.
    """
    rows = con.execute(
        "select bid, ask from quotes where feed=? and venue=? and bid>0 and ask>bid",
        (feed, venue),
    ).fetchall()
    if not rows:
        return 0.0
    return st.median((ask - bid) / ((ask + bid) / 2.0) * 1e4 for bid, ask in rows)


def cost_r(bps: float, series: Series, risk_vol: np.ndarray, unit: np.ndarray) -> float:
    """A round trip as a share of the risk, which is the denominator that binds.

    `round_trip / stop`, from `domain/costs.py`: a permitted spread scaled to
    the *target* lets a distant target buy the right to pay more, and the
    desk's measured limit is **0.16 of the risk**. `a-shorter-clock-multiplies-
    cost-in-r` is why this is reported per clock - the same spread is 19x
    dearer at 15m than at 1d - and the whole point of reporting gross beside
    net is that "signals work better on higher timeframes" and "costs eat
    signals on lower timeframes" are different claims with one symptom.

    The round trip is one full spread: the trade crosses half of it in and half
    of it out.
    """
    if bps <= 0.0 or not len(risk_vol):
        return float("nan")
    px = float(np.median(series.close)) * bps / 1e4
    risk_px = float(np.median(risk_vol)) * float(np.median(unit))
    return px / risk_px if risk_px > 0 else float("nan")


def strata_of(series: Series, unit: np.ndarray, span: int) -> np.ndarray:
    """Quintiles of trailing compression, of **this arm's own** distribution.

    Per arm, because the arms have different volatility processes and shared
    edges would misalign the bins - `level_shield.STRATA`'s reason, unchanged.
    """
    comp = compression(unit, span)
    edges = np.quantile(comp[np.isfinite(comp)], np.linspace(0, 1, STRATA + 1)[1:-1])
    return np.clip(np.searchsorted(edges, comp), 0, STRATA - 1)


def store_path() -> str:
    return os.environ.get("PA_STORE") or STORE
