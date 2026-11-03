"""Anchored states and the next move's size: the data, the states, the arms.

Pre-registered in `research/docs/anchored-states-prereg.md` (commit 0d4234c5)
before any cell existed. This module is the harness that prereg specifies; it
decides nothing the prereg fixed.

The question, in one line: **given a state that is a reading of bars already
closed, does the magnitude of the next move differ across that state's levels
by more than the null arms produce, within volatility strata?**

## Why every state is pinned to something external

`definitions-cannot-be-states` is the recorded failure: a mixture centre left
as a free state **collapses onto the data**, and three members needed anchors
to stay distinct. So no threshold here is chosen against an outcome. Each
anchor is a quantity this desk already publishes, and the only cuts are
*distributional* - equal-mass bins of the state's own trailing distribution,
or the fixed thirds of a period that is 0..1 by construction.

**The bins are causal, not full-sample.** The prereg permitted full-sample
quantile edges for the stratification variable and declared them. They are
not used, for either the strata or the state cuts: a full-sample edge is not
computable at the decision bar, and the prereg's own causality rule is the
stronger constraint. Every cut here is the expanding empirical rank of the
reading among the readings of bars closed at or before the decision bar.

## Causality, which the pivot set is the only real risk in

`Pivots` publishes a period's set only once a bar from the *next* period has
arrived, so a forming period cannot be read. That is not enough on its own:
`node/corpus.py` records that the store's `ts` is probably the bar's **open**
rather than its close, so a set stamped at its source period's last `ts` would
be optimistic by one bar. Every set is therefore registered with
`strategies.timeframes.Frames` at `last ts + one interval` - the close under
the pessimistic reading - and read back through `Frames.ready`, which drops
any frame whose last close is after the decision moment. A set `ready` does
not return is a `nan`, never an approximation.

## The arms are log-space, and that is a correction

`level_shield.bar_shuffle` and `level_shield.walk_geometry` permute and
resample **absolute** close-to-close steps. Over 19 years of daily bars the
price level moves 2.06x on audjpy, 2.19x on nzdjpy and **8.45x on gold**, so an
absolute-step arm has the wrong relative volatility at one end of the sample -
`fear-greed.md`'s fifth defect, where an absolute-step arm and its log twin
disagreed by **more than the effect** (+0.142 against +0.236 on a real +0.213).
The outcome here is a *relative* magnitude, so the pre-registered arms are
built in log space and the absolute ones are carried at 1d as a diagnostic
rather than as a decision.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

import numpy as np

import research.ideas.level_shield as L
from till_infinity.indicators.pivots import PERIODS, Pivots, SESSION_HOURS, session_of
from till_infinity.indicators.sentiment import FearGreed
from till_infinity.strategies.timeframes import Frames

#: The price store. A flag on the runner points this at a copy on a bigger
#: box; the default runs anywhere the repo is checked out.
STORE = "file:.data/prices/prices.db?mode=ro"

#: Feeds carried, with one venue each chosen by bar count at that interval -
#: `level_shield.venue_for`, reused rather than re-decided.
FEEDS = L.FEEDS

#: **The placebo pair, fixed before any result.** Two instruments carried in
#: every table whose cells may not count towards a pass, and whose passing
#: rejects the finding (pass rule 3).
#:
#: The rule is result-blind and checkable: these are the only two feeds in
#: `FEEDS` that carry **no named prior claim** anywhere in
#: `research/docs/findings.md` or `research/docs/README.md`'s index, and both
#: have the full 19.2 years of daily history, so the placebo has the same power
#: as the decision set. A low-power placebo would be the anti-conservative
#: choice: pass rule 3 only bites when the placebo *can* pass.
#:
#: `carry-an-independent-placebo-pair` names two Deriv volatility indices for
#: this job. **The store has none** - no synthetic family appears in it at any
#: interval - so the pair is drawn from the carried feeds instead, which is a
#: weaker control and is recorded as such.
PLACEBO: tuple[str, str] = ("nzdusd", "usdcad")

#: Per interval, and every number in bars so the mapping between intervals is
#: stated rather than assumed.
#:
#: `horizon` is the prereg's `H`: 20 at 1d, 48 at 15m and 1h, matching
#: `level-bounce.md` so the two are comparable. Not swept.
#:
#: `pivot_period` is **weekly at 1d**: a daily pivot set on daily bars is
#: arithmetic on a one-bar "prior period", and `level-bounce.md` measured what
#: that does - 3,640 episodes over 20 distinct tags against `levels`' 960 over
#: 248. At 15m and 1h the daily set is the one everybody watches.
#:
#: `through_period` is **monthly at 1d** and is not the same choice, because
#: `through` is a position in a period rather than a price. Measured: thirds of
#: the *week* are not three states on daily bars. A weekday bar stamped at
#: midnight reaches at most 5/7 = 0.714 of the week, so the last third is only
#: ever the **Sunday** bar - gold, which has none, saw 2 of 3 levels and eurusd
#: saw a third level made entirely of the FX Sunday open, which this desk
#: already vetoes entries in. Thirds of a month are three buckets of about
#: seven trading days each and are what the prereg's "early / middle / late in
#: the period" means here.
#:
#: `jitter` is how many extra bars the de-overlapping stride may take, and it
#: exists for a collision between de-overlapping and the clock. At 15m and 1h
#: the lock is **exact**: 48 bars is exactly 12 hours and exactly 2 days, so a
#: fixed stride of `H` puts every anchor at one or two times of day. Measured:
#: with a fixed stride every 1h anchor fell in **one** hour of the day, so
#: `session` and `through` would have been states measured on one value, which
#: reads as a null without having been tested. The span is `H`, and the
#: cumulative stride then walks over the whole 96- and 24-bar day. Every gap is
#: still at least `H`, so the blocks stay disjoint; it costs about a third of
#: the rows.
#:
#: **At 1d it is 0, and that is measured rather than assumed.** 20 daily bars
#: is nearly four calendar weeks, which would pin the phase - but the store's
#: daily series has holiday gaps, so the drift accumulates: at a fixed stride
#: eurusd and gold both read **all three** monthly thirds (72/72/91 and
#: 81/76/78 of 235 anchors) and **all five** weekdays. A jitter here would cost
#: 10% of the rows at 1d, the one interval with 19 years in it, for nothing.
#: It is needed only where the lock is exact.
SETTINGS: dict[str, dict] = {
    "15m": {
        "horizon": 48,
        "unit_span": 48,
        "bars_per_day": 96,
        "jitter": 48,
        "pivot_period": "daily",
        "through_period": "daily",
        "bar_type": "15-MINUTE",
        "context": "1-DAY",
    },
    "1h": {
        "horizon": 48,
        "unit_span": 48,
        "bars_per_day": 24,
        "jitter": 48,
        "pivot_period": "daily",
        "through_period": "daily",
        "bar_type": "1-HOUR",
        "context": "1-DAY",
    },
    "1d": {
        "horizon": 20,
        "unit_span": 20,
        "bars_per_day": 1,
        "jitter": 0,
        "pivot_period": "weekly",
        "through_period": "monthly",
        "bar_type": "1-DAY",
        "context": "1-WEEK",
    },
}

#: Bars discarded before the first anchor. The binding constraint is not the
#: indicators - `FearGreed` warms in 20 bars and the volatility unit in a few
#: spans - it is the **expanding rank**: a causal quantile cut computed from
#: forty prior readings is a cut on forty readings, and the early anchors would
#: carry a different estimator from the late ones.
WARMUP = 300

#: The fewest prior readings an expanding rank will cut on.
RANK_FLOOR = 200

#: Compression strata. Quintiles, as pre-registered.
STRATA = 5

#: The six anchors and how many levels each has. Frozen in the prereg; the
#: counts are the prereg's "3-4 state levels" made exact.
#:
#: `session` has four, `compression` five (its bins are the quintiles the desk
#: already conditions on, read as a *level* rather than as the compression
#: ratio the strata use), and the rest three.
ANCHORS: dict[str, int] = {
    "session": 4,
    "through": 3,
    "compression": 5,
    "pivot_room": 3,
    "mood_vol": 3,
    "mood_dir": 3,
}

#: Anchors whose level is a function of the clock alone, so a price plant
#: cannot move the label. `fear-greed.md`'s sixth defect is why this matters:
#: a label-conditional plant **destroyed the association it planted**, because
#: reflecting the path changed the bars the labels were recomputed from (zero
#: cell +0.1412, hard walls -0.023, the wrong sign). The power sweep plants on
#: these, where the zero control is exact by construction.
CLOCK_ANCHORS = ("session", "through")

#: The session names, in the order their codes are assigned.
SESSIONS: tuple[str, ...] = tuple(SESSION_HOURS)


def seed_of(*parts: object) -> int:
    """A stable seed over the arm's parts.

    **Never `hash()`.** The builtin hash of a tuple containing a string is
    salted per process, so surrogate draws do not reproduce between runs.
    Three harnesses carried that bug in one session: `stop-anchor.md` had
    gold.15m's hardest null move +0.0267 to +0.0239 and flip a cell from fail
    to pass with no real reading moving, and `fear-greed.md` had audjpy's
    `bar-shuffle` read -0.172 locally and -0.266 on the panel while every real
    value matched to the digit.
    """
    raw = "|".join(repr(part) for part in parts).encode()
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")


# ───────────────────────────── the null arms ─────────────────────────────


def _shapes(series: L.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Each bar's range as a share of its close, and its wick proportions.

    Relative, so a bar's shape can be pasted onto a different price level
    without carrying that level's scale with it - which is the whole of the
    absolute-step correction this module makes.
    """
    close = np.maximum(series.close, 1e-12)
    span = series.high - series.low
    safe = np.maximum(span, 1e-12)
    rel = span / close
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)
    return rel, frac_o, frac_c


def _from_logs(series: L.Series, logs: np.ndarray, pick: np.ndarray) -> L.Series:
    """Rebuild a series from a log-price path and a choice of bar shapes."""
    rel, frac_o, frac_c = _shapes(series)
    close = np.exp(logs)
    width = close * rel[pick]
    low = close - frac_c[pick] * width
    return L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=low + frac_o[pick] * width,
        high=low + width,
        low=low,
        close=close,
    )


def bar_shuffle(series: L.Series, rng: random.Random) -> L.Series:
    """Each bar's own shape on a permuted **log** step. The no-memory floor.

    The marginal log-step distribution and every bar's wick-to-body proportion
    survive exactly; where price has been does not.
    """
    logc = np.log(np.maximum(series.close, 1e-12))
    steps = np.diff(logc)
    order = np.asarray(rng.sample(range(len(steps)), len(steps)))
    pick = np.asarray(rng.sample(range(len(logc)), len(logc)))
    logs = np.empty(len(logc))
    logs[0] = logc[0]
    logs[1:] = logc[0] + np.cumsum(steps[order])
    return _from_logs(series, logs, pick)


def walk_geometry(series: L.Series, rng: random.Random) -> L.Series:
    """`node/surrogates.walk_with_bar_geometry`'s construction, in log space.

    Log steps resampled i.i.d. with replacement, bar shapes resampled the same
    way: this market's wickiness and step distribution, none of its path
    structure and none of its clustering. The i.i.d. resampling is why
    `garch-bars` is also required.
    """
    logc = np.log(np.maximum(series.close, 1e-12))
    steps = np.diff(logc)
    n = len(logc)
    drawn = np.asarray([steps[rng.randrange(len(steps))] for _ in range(n - 1)])
    pick = np.asarray([rng.randrange(n) for _ in range(n)])
    logs = np.empty(n)
    logs[0] = logc[0]
    logs[1:] = logc[0] + np.cumsum(drawn)
    return _from_logs(series, logs, pick)


#: The arms that are built as a series, and whether the decision bar counts
#: them. `duty-twin` is not here: it needs no surrogate series, because it
#: keeps the state's own firing rate and times and permutes the outcome
#: against them, which `anchored_states_agg.duty_draws` does from the real
#: rows.
SERIES_ARMS: dict[str, object] = {
    "garch-bars": L.garch_bars,
    "walk-geometry": walk_geometry,
    "bar-shuffle": bar_shuffle,
}

#: Carried at 1d only, and **excluded from every decision**: the absolute-step
#: arms as `level_shield` wrote them, so the doc can state how far they differ
#: from their log twins over a sample where the price level moves up to 8.45x.
DIAGNOSTIC_ARMS: dict[str, object] = {
    "walk-geometry-abs": L.walk_geometry,
    "bar-shuffle-abs": L.bar_shuffle,
}

#: Arms whose hardest draw is the bar a cell has to clear. The prereg's four.
DECIDING_ARMS = ("garch-bars", "walk-geometry", "bar-shuffle", "duty-twin")


# ──────────────────────────── the state readings ────────────────────────────


@dataclass(slots=True)
class Readings:
    """Per-bar state readings, before any cut, plus the outcome's inputs.

    `nan` means "not knowable at this bar", never a guess. `session` is a code
    into `SESSIONS` and is the one reading with no distribution to cut.
    """

    session: np.ndarray
    through: np.ndarray
    compression: np.ndarray
    pivot_room: np.ndarray
    mood_vol: np.ndarray
    mood_dir: np.ndarray
    #: The stratification variable: `log(fast unit / slow unit)`.
    stratum_raw: np.ndarray
    #: The volatility unit as a share of price, which is the outcome's unit.
    rel_unit: np.ndarray
    #: How many bars had a pivot set that `Frames.ready` refused. A non-zero
    #: count here is the look-ahead guard doing its job and is reported.
    refused: int = 0
    #: How many bars `FearGreed` could not produce a reading for. **This is a
    #: production bug, not a property of the data**: `sentiment._expansion`
    #: guards `middle <= 0.0` but not `now <= 0.0`, so `math.log2(now/middle)`
    #: raises `ValueError: math domain error` when the last fifth of the
    #: trailing window is entirely dead bars - which gold's 1d history has.
    #: Reported rather than fixed here; those bars carry `nan` moods and their
    #: anchors are dropped.
    dead: int = 0


def frames_for(series: L.Series, interval: str) -> Frames:
    """The signal frame and the pivot period's frame, ordered by the module.

    `Frames.__post_init__` refuses a context frame that is not strictly
    coarser than the signal, which is why 1d reads a **weekly** pivot set: a
    daily set on a daily signal would be the same clock, and `Frames` says so
    rather than letting it through.
    """
    settings = SETTINGS[interval]
    stem = f"{series.feed.upper()}.{series.venue}"
    return Frames(
        signal=f"{stem}-{settings['bar_type']}-LAST-EXTERNAL",
        context=(f"{stem}-{settings['context']}-LAST-EXTERNAL",),
    )


def read(series: L.Series, interval: str) -> Readings:
    """Drive the production indicators bar by bar and record every reading.

    One pass, so nothing can read a bar the previous reading had not seen.
    `Pivots` and `FearGreed` are the shipped indicators rather than
    reimplementations: a test that reimplements the logic tests the
    reimplementation, and the same argument applies to a study.
    """
    settings = SETTINGS[interval]
    period = settings["pivot_period"]
    elapsed = settings["through_period"]
    step, grain = settings["bar_type"].split("-")
    span = float(step) * {"MINUTE": 60.0, "HOUR": 3_600.0, "DAY": 86_400.0}[grain]
    unit = L.units(series, settings["unit_span"])
    stratum_raw = L.compression(unit, settings["unit_span"])
    close = np.maximum(series.close, 1e-12)

    pv = Pivots(periods=tuple(dict.fromkeys((period, elapsed, *PERIODS))))
    fg = FearGreed()
    frames = frames_for(series, interval)
    context = frames.context[0]

    n = len(series.close)
    out = Readings(
        session=np.full(n, -1, dtype=np.int64),
        through=np.full(n, np.nan),
        compression=np.full(n, np.nan),
        pivot_room=np.full(n, np.nan),
        mood_vol=np.full(n, np.nan),
        mood_dir=np.full(n, np.nan),
        stratum_raw=stratum_raw,
        rel_unit=unit / close,
    )
    published = 0
    for i in range(n):
        when = float(series.ts[i])
        pv.update_raw(float(series.high[i]), float(series.low[i]), float(series.close[i]), when)
        # `FearGreed._expansion` raises on an all-dead last fifth of its
        # window (see `Readings.dead`). The deques are appended before the
        # parts are recomputed, so the indicator's window survives the
        # exception intact and only this bar's reading is missing - which is
        # recorded as `nan` rather than as the previous bar's stale value.
        mood = True
        try:
            fg.update_raw(
                float(series.open[i]),
                float(series.high[i]),
                float(series.low[i]),
                float(series.close[i]),
                when,
            )
        except ValueError:
            mood = False
            out.dead += 1
        if pv.published != published:
            published = pv.published
            source = pv.sources.get(period)
            if source is not None:
                # `+ span`: the store's `ts` is probably the bar's open, so a
                # set stamped at its source period's last `ts` would be
                # knowable one bar before it is. The pessimistic close is the
                # only stamp that cannot be optimistic.
                frames.observe(context, float(source.end) + span, period)
        out.session[i] = SESSIONS.index(session_of(when))
        out.through[i] = pv.through(elapsed)
        out.compression[i] = out.rel_unit[i]
        if context in frames.ready(when):
            room = pv.room(float(series.close[i]), period)
            if room is not None and out.rel_unit[i] > 0.0:
                out.pivot_room[i] = min(room) / (out.rel_unit[i] * float(series.close[i]))
        elif pv.sets.get(period):
            out.refused += 1
        if mood and fg.initialized:
            out.mood_vol[i] = fg.volatile
            out.mood_dir[i] = fg.directional
    return out


# ──────────────────────────── anchors and cuts ────────────────────────────


def anchors_for(series: L.Series, interval: str) -> np.ndarray:
    """De-overlapped decision bars, **the same set for every arm and draw**.

    One outcome per non-overlapping block of `H` bars, as pre-registered:
    `overlapping-outcome-windows-leak` is the refutation, where a short skip
    rule with a long forward window gave a direction AUC of 0.79 that
    collapsed to 0.51 and the tell was the placebo and shuffled arms tracking
    it.

    The gap is `H + U{0..jitter-1}`, so blocks are still disjoint - every gap
    is at least `H` - while the anchor's phase on the clock is not pinned. It
    is the only way the two clock anchors are measurable at 15m and 1h, where
    48 bars is exactly 12 hours and exactly 2 days; at 1d the jitter is 0,
    because the store's holiday gaps already break the phase there.

    Seeded on `(feed, interval)` and nothing else, so every arm and every draw
    walks the identical anchors over the identical day structure.
    """
    settings = SETTINGS[interval]
    horizon = settings["horizon"]
    n = len(series.close)
    rng = random.Random(seed_of("anchors", series.feed, interval) & 0xFFFFFFFF)
    out: list[int] = []
    t = WARMUP
    while t + horizon < n:
        out.append(t)
        t += horizon + (rng.randrange(settings["jitter"]) if settings["jitter"] else 0)
    return np.asarray(out, dtype=np.int64)


def causal_levels(raw: np.ndarray, anchors: np.ndarray, bins: int) -> np.ndarray:
    """Equal-mass bins of each anchor's **trailing** distribution.

    The reading's rank among the readings of bars closed at or before the
    decision bar, cut into `bins`. So the cut is computable at the decision
    bar, which a full-sample quantile edge is not - and no edge is chosen
    against an outcome, which is what `definitions-cannot-be-states` is about.

    -1 where the reading is missing or fewer than `RANK_FLOOR` prior readings
    exist, which is a dropped row and never bin 0.
    """
    out = np.full(len(anchors), -1, dtype=np.int64)
    finite = np.isfinite(raw)
    for row, t in enumerate(anchors):
        here = raw[t]
        if not np.isfinite(here):
            continue
        prior = raw[: t + 1][finite[: t + 1]]
        if len(prior) < RANK_FLOOR:
            continue
        share = float(np.count_nonzero(prior <= here)) / len(prior)
        out[row] = min(bins - 1, int(share * bins))
    return out


def thirds(raw: np.ndarray, anchors: np.ndarray) -> np.ndarray:
    """Fixed thirds of a 0..1 quantity. For `through`, which needs no cut.

    `Pivots.through` is already a share of the period, so early / middle /
    late are the period's own thirds and not a quantile of anything. Nothing
    here is estimated, so nothing here can be fitted.
    """
    here = raw[anchors]
    live = np.isfinite(here)
    safe = np.where(live, here, 0.0)
    return np.where(live, np.minimum(2, (safe * 3.0).astype(np.int64)), -1).astype(np.int64)


# ───────────────────────────── the measurement ─────────────────────────────


@dataclass(slots=True)
class Rows:
    """One row per de-overlapped anchor. Flat, so a statistic is a mask."""

    anchor: np.ndarray
    day: np.ndarray
    stratum: np.ndarray
    size: np.ndarray
    signed: np.ndarray
    #: Level per anchor name, -1 where the state is not knowable.
    levels: dict[str, np.ndarray]
    refused: int = 0
    dead: int = 0

    def __len__(self) -> int:
        return len(self.anchor)


def measure(series: L.Series, interval: str, anchors: np.ndarray | None = None) -> Rows:
    """States and outcomes at every de-overlapped anchor.

    The outcome is the prereg's: `size` is the absolute log move from the
    decision bar's close to the close `H` bars later, in volatility units of
    the decision bar, and `signed` is the same with its sign. The unit is a
    causal EWMA of the bar **range**, per `drive-q-from-the-range` - the
    range-vs-close estimator ratio reads 0.648 within strata on FX and 0.667
    on 371 of 392 equities.
    """
    settings = SETTINGS[interval]
    horizon = settings["horizon"]
    if anchors is None:
        anchors = anchors_for(series, interval)
    got = read(series, interval)
    close = np.maximum(series.close, 1e-12)
    move = np.log(close[anchors + horizon] / close[anchors])
    rel = got.rel_unit[anchors]
    with np.errstate(divide="ignore", invalid="ignore"):
        signed = np.where(rel > 0.0, move / rel, np.nan)
    levels = {
        "session": got.session[anchors],
        "through": thirds(got.through, anchors),
        "compression": causal_levels(got.compression, anchors, ANCHORS["compression"]),
        "pivot_room": causal_levels(got.pivot_room, anchors, ANCHORS["pivot_room"]),
        "mood_vol": causal_levels(got.mood_vol, anchors, ANCHORS["mood_vol"]),
        "mood_dir": causal_levels(got.mood_dir, anchors, ANCHORS["mood_dir"]),
    }
    return Rows(
        anchor=anchors,
        day=(series.ts[anchors] // 86_400).astype(np.int64),
        stratum=causal_levels(got.stratum_raw, anchors, STRATA),
        size=np.abs(signed),
        signed=signed,
        levels=levels,
        refused=got.refused,
        dead=got.dead,
    )


def blocks_for(interval: str) -> int:
    """Bootstrap block length in **rows**, from the prereg's bar rule.

    "Block at least `max(H, bars per day)`" is a length in bars; the rows are
    at least `H` bars apart, so the block in rows is that length divided by
    the minimum stride. `level-bounce.md` is the precedent and the reason:
    one-bar calendar-day blocks at 1d would share 19 of 20 outcome bars.
    """
    settings = SETTINGS[interval]
    want = max(settings["horizon"], settings["bars_per_day"])
    return max(1, math.ceil(want / settings["horizon"]))


# ───────────────────────────── the planted effect ─────────────────────────────


def plant_magnitude(
    series: L.Series,
    interval: str,
    anchors: np.ndarray,
    picked: np.ndarray,
    strength: float,
) -> L.Series:
    """Scale the forward move after each picked anchor by `1 + strength`.

    **A planted effect for a magnitude reading has to widen the ranges**, not
    only the closes: `fear-greed.md`'s planted crash was a smooth drift that
    never widened a range, and it validated the direction half while reading
    0 of 4 on the volatility half at depth 0.45. So the bar's range is scaled
    with its step and the wick proportions are kept.

    The windows of de-overlapped anchors do not overlap, so no bar is scaled
    twice and `strength` 0 returns the input unchanged - which is the zero
    control, and `fear-greed.md`'s sixth defect is why it is asserted rather
    than assumed: a plant whose zero cell reads -0.180 at z -4.76 is a broken
    arm, not a weak effect.
    """
    horizon = SETTINGS[interval]["horizon"]
    logc = np.log(np.maximum(series.close, 1e-12))
    steps = np.diff(logc)
    factor = np.ones(len(steps))
    for row, t in enumerate(anchors):
        if picked[row]:
            factor[t : t + horizon] *= 1.0 + strength
    rel, frac_o, frac_c = _shapes(series)
    widen = np.ones(len(logc))
    widen[1:] = factor
    logs = np.empty(len(logc))
    logs[0] = logc[0]
    logs[1:] = logc[0] + np.cumsum(steps * factor)
    close = np.exp(logs)
    width = close * rel * widen
    low = close - frac_c * width
    return L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=low + frac_o * width,
        high=low + width,
        low=low,
        close=close,
    )
