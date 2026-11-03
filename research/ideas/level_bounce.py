"""Does price bounce at a level, and is a level graded by how it bounced before?

Two questions, and the second is the one nothing here has asked.

1. **Does price bounce at all?** At a touch, does price travel one volatility
   unit back the way it came before one unit through - and does it do that more
   often than at a matched price that is not a level, or than at a level of the
   same kind found by the same detector on a surrogate?
2. **Is a level graded by how it bounced before?** The claim is that a level
   whose **previous** departures were sharp - a spike/crash or a trend run -
   holds its **next** touch more often than one price merely drifted away from.
   If true, bounce shape ranks a book of 24 levels and the five best are the
   ones worth placing against.

The second is causal only in that form. The shape of *this* bounce is known
only after it, so grading this touch by this touch is a lookahead by
construction; grading it by the strictly earlier episodes at the same level is
not. Only the second is measured here, and `grade` never reads an episode at or
after the one it is scoring.

## What is already closed, and why this is still a different claim

* **A level's own record carries nothing.** `statespace-conditional-holds.md`
  read tau 0.0109 over 279 levels against a simulated 0.0085, and
  `record-auc.md` put twelve configurations of the same-side record between
  0.4977 and 0.5104 with the placebo tracking within 0.003. So the *hold-rate*
  record is dead. **That is not this claim**: a hold rate is binary and
  shapeless, and the one reading that beat it was `|record - 0.5|` at 0.6006
  against the raw record's 0.5005 - a magnitude, not a direction. Bounce shape
  is a magnitude too, so it is a different variable and worth one measurement.
  Both of those grades are carried here as arms, which also means this harness
  **reproduces a known number or is wrong**.
* **A touch looks like any other touch.** `level-signatures.md` ran nineteen
  observables over 6,902 touches and found nothing further than 0.006 from an
  AUC of 0.5, family-wise p 0.828, while catching a planted 0.02-sigma shift at
  p 0.020. That study asked whether the touch *bar* differs at a real level. It
  did not ask whether the *departure* differs, nor whether one level's
  departures predict the next.
* **Levels hold slightly more than walk levels.** `tv-indicators.md`: 0.58-0.59
  first-touch hold against 0.565 for levels found by the same detector on a
  walk, and clustering added nothing. That is the number part 1 has to land
  near.
* **Levels, ranges and shapes restate volatility** (`topology.md`), and a level
  in the path does not suppress the move over 210 cells (`level-shield.md`).
  The prior is poor and a clean null is the valued result.

## The trap this question is built out of

A spike is a large bar, and large bars cluster. "Levels that bounced sharply"
is therefore partly "levels touched in a volatile stretch", and that would
produce a grade that predicts the next touch for a reason with nothing to do
with the level. Three things answer it, and none is optional:

* every comparison happens **within quintiles of trailing compression**, the
  same stratifier `level_shield.compression` supplies;
* the grade comparison is additionally **within bins of how many previous
  episodes the level has**, because a level with eight is an older level in a
  longer-lived regime and not the same object as one with two;
* the **shuffled twin** runs the whole pipeline. `bar-shuffle` keeps each bar's
  own shape and the marginal step distribution and destroys where price has
  been, so any grade that still works there is mechanical.
  `let-the-shuffled-twin-name-the-mechanical-observables` is why it is the arm
  that names the mechanical part, and `level-shield.md` is the instance - the
  blocked side of a mirror was reached *more* often on a shuffle, which would
  have made a barrier finding with the sign backwards.

## The nulls, reused rather than rebuilt

`level_shield.ARMS` is imported whole: `garch-bars` (clustering and fat tails
kept, path structure gone), `walk-geometry` (`node/surrogates.
walk_with_bar_geometry` - bar wickiness and the step distribution, no
clustering), `bar-shuffle` (no memory at all). Every arm goes through the
**same detector** over the same bar geometry, which is the whole discipline.

A fourth arm is local to this study and runs on the real series:
**`placebo`**, each level in the book displaced by a random offset of 1.5 to
3.0 volatility units, rejected if it lands within 0.70 units of any real level.
That is `a-return-rate-is-geometry` as a control - `fade-to-value`'s 82% return
rate was matched by a distance-matched placebo on every class and a walk reads
0.825, so a hold rate without this arm means nothing.

## The four kinds, and which one is the control

`pivots` is the control and that is its main purpose. It has no parameters, no
detector and nothing to fit, and a set is fully determined by the prior period.
**If the Kalman book does not beat pivots, the swing detection is not earning
its complexity.** Every kind is reported against it.

One asymmetry has to be stated rather than smoothed over: `levels`, `bjorgum`
and `pips` carry a **per-instance** history, so a level accumulates its own
episodes. A daily pivot does not - it exists for one period and is recomputed.
Its history is therefore **per name**: R1's record is R1's record across
periods. That is a different and better-sampled object, and it means part 2's
pivot column is not the same measurement as the other three. Part 1 is
comparable across all four.
"""

from __future__ import annotations

import os
import statistics as st
from dataclasses import dataclass

import numpy as np

from research.ideas.level_shield import (
    ARMS,
    BINS,
    ERAS,
    FEEDS,
    SETTINGS,
    STORE,
    STRATA,
    Series,
    _Bar,
    compression,
    load,
    units,
    venue_for,
)
from till_infinity.indicators import candles as C
from till_infinity.indicators import trend as T
from till_infinity.indicators.levels import (
    CHAIN_GAP,
    MERGE_VOL,
    PUSH_BODY,
    PUSH_MIN,
    BjorgumLevels,
    Candle,
    Levels,
    Pips,
    chains,
)
from till_infinity.indicators.pivots import PERIODS, Pivots

__all__ = [
    "ARMS",
    "FEEDS",
    "KINDS",
    "SETTINGS",
    "STORE",
    "Rows",
    "Series",
    "book_path",
    "episodes",
    "load",
    "measure",
    "placebo_books",
    "venue_for",
]

#: The level kinds compared. `pivots` last because it is the control, and
#: `levels` first because it is the book a strategy here reads.
KINDS = ("levels", "bjorgum", "pips", "pivots")

#: Which pivot periods to publish per interval, and this is **not** the
#: indicator's default for a reason that would otherwise have broken the
#: control.
#:
#: `Pivots` defaults to `("daily", "weekly")`, which is right on intraday bars.
#: On **1d bars a daily session is one bar**, so the whole set would be
#: recomputed every bar from a single bar's high, low and close - `R2` would be
#: the prior *bar's* range rather than the prior period's, the ten prices would
#: move every bar, and a touch would be close to guaranteed. Measured on the
#: default: eurusd 1d gave **3,640 episodes over 20 tags** against `levels`'
#: 960 over 248, which is not a comparable object and would have made the
#: control look like it had more evidence when it had less structure.
#:
#: So the period is scaled with the bar: weekly and monthly at 1d - which the
#: `Pivots` docstring says 19 years of daily bars support - and daily and
#: weekly below it.
PIVOT_PERIODS = {
    "1d": ("weekly", "monthly"),
    "4h": ("daily", "weekly"),
    "1h": ("daily", "weekly"),
    "15m": ("daily", "weekly"),
}

#: Bars kept past a touch to read the departure's shape. Four, because the
#: user's trend run is "two or more bars moving consistently one way with at
#: most one or two small hiccups" - four bars is three steps, which admits two
#: with the sign and one against.
SHAPE_BARS = 4

#: How close a bar has to come to count as a touch, in volatility units. Not
#: zero: a level is a posterior mean and price does not have to print it to
#: have been there. `level-dispersion.md` fitted the touch scatter at 0.40
#: units over 22,402 levels, so 0.10 is well inside the noise the book itself
#: believes and does not manufacture touches.
TOUCH_VOL = 0.10

#: The symmetric race, in volatility units either side of the level. One unit
#: back the way price came against one unit through, which is **0.50 on a
#: walk by construction**. `trap-levels.md` settles its levels the same way.
#:
#: **This is descriptive and does not decide anything.** A bounce rate is
#: precisely the quantity that is geometry - `fade-to-value`'s 82% return rate
#: was matched by a distance-matched placebo on every class and a walk reads
#: 0.825 - so a rate was never going to be the finding. What decides is mean R
#: below, and a score that lowers the hit rate while raising expectancy is
#: still an edge.
RACE = 1.0

#: The protective stop, in volatility units **through the level** - so the
#: level has to break before the trade is wrong, which is the one thing
#: `level-shield.md` looked for and did not find, and is still the only
#: sensible place to put it when the trade is a bounce.
STOP_VOL = 1.0

#: How long a departure lasts, in bars: the **first return to the level**.
#:
#: This is the third quantity, independent of shape and of distance, and
#: `a-magnet-is-a-shared-reference` ends with the instruction it answers - *use
#: the time exponent, not the return rate*. Two bounces with identical hit
#: rates and identical R at a fixed target can have very different lengths, so
#: duration is reported beside those readings and never folded into them.
#:
#: **The null is exact, parameter-free and distribution-free.** By Sparre
#: Andersen's theorem the first-passage time of a symmetric random walk back
#: to a level has `P(T > t) ~ t^(-1/2)` *whatever the step distribution* - the
#: exponent is 1/2 for a Gaussian walk, a fat-tailed walk and this market's own
#: resampled steps alike. So the pre-registered null exponent is **0.5** and no
#: arm has to be fitted to supply it. A reading at 0.5 means duration is
#: geometry, which is `a-return-rate-is-geometry` in the time domain; a
#: departure from 0.5 is the finding.
#:
#: Duration is **right-censored** at the horizon and a mean over the
#: uncensored episodes is biased short - exactly the bias that would make a
#: short-lived bounce look universal. Nothing here reports a bare mean; the
#: estimator is Kaplan-Meier and the censored share travels with every cell.
DURATION_CENSORED = -1

#: Reward-to-risk ratios raced, as multiples of the **risk measured from the
#: entry**, not of the volatility unit. That distinction is the whole reason
#: the arithmetic is honest: with the target at `k` times the realised risk,
#: a driftless walk reaches it with probability `1/(1+k)` and the expected R
#: is exactly zero at every `k`, so any departure from zero is the finding and
#: no reward-to-risk can manufacture one. `risk-vol-is-not-the-stop-distance`
#: is the recorded error this avoids - the stop distance is from the entry.
TARGETS = (1.0, 2.0, 3.0)

#: A departure has happened when price is this far from the level, in units,
#: at the end of the shape window. Below it the bounce has not started and the
#: shape question is not yet asked.
RUN_MOVE = 0.50

#: Kaufman's efficiency a departure must clear to be a **trend run**.
#: `indicators.trend.ratio` is used rather than a hand-rolled consistency rule
#: because "net travel over gross travel" is exactly "one direction with
#: hiccups", and the repo's copy exists because Nautilus's own is biased by
#: `1 / period` and can never report a perfectly efficient move.
RUN_EFF = 0.60

#: Swept around `RUN_EFF`, and the whole grid is reported with its mean rather
#: than the best cell with its z - `sweep-thresholds-on-the-mean-not-z` is
#: recorded because a z grid faked a ridge at the chosen threshold where the
#: mean grid was monotone.
RUN_EFFS = (0.45, 0.60, 0.75, 0.90)

#: A **spike/crash** needs a bar this many volatility units wide. The "body a
#: large share of range" half comes from `Candle.impulsive`, which is the
#: desk's own `PUSH_BODY` 0.70 and not a new constant; this is the "large range
#: relative to a causal ATR" half.
SPIKE_RANGE = 1.5

#: Bars from the touch within which a spike or a leg has to start. Two, so the
#: touch bar itself or the one after it counts and a bar three later does not -
#: that is a different event, and admitting it would let a shape found at the
#: end of the window be read as the reaction to the touch.
SHARP_WITHIN = 2

#: Episodes at one level must be at least this many bars apart to both be
#: scored. The forward window itself, so two scored episodes never share an
#: outcome bar: `overlapping-outcome-windows-leak` is a direction AUC of 0.79
#: that collapsed to 0.51, and `overlapping-windows-inflate-permutation-nulls`
#: is a level finding at p 0.015 that was anchor overlap.
#: `None` means the interval's horizon.
GAP_BARS: int | None = None

#: Shrinkage on a level's record, in pseudo-episodes toward the **causally
#: running** pooled rate. Two, so a level with one previous episode is scored
#: a third on its own evidence rather than wholly on it. The pooled rate is a
#: running mean over episodes strictly earlier in the same series, never the
#: whole-sample rate, which would be a lookahead through the back door.
PRIOR_K = 2.0

#: Bins on how many previous episodes a level has, as right-open edges. The
#: grade comparison happens inside these as well as inside the compression
#: quintiles, because an eight-episode level is an older level in a
#: longer-lived regime and not the same object as a two-episode one.
AGE_EDGES = (1, 2, 3, 5)

#: Shape bits. Recorded as a mask and not a partition, because
#: `smc-primitives-overlap-and-are-closed` is measured here - an engulf is the
#: opposite shape to a displacement origin and the primitives overlap. A
#: harness that forced a partition would hide the overlap and pick a winner by
#: the order of its own `elif` chain.
#:
#: `SPIKE` and `LEG` are separate because the one-bar and multi-bar readings of
#: "sharp" are **two orders of magnitude apart in firing rate** and pooling
#: them would have hidden that. Measured on 1d before the run was frozen: a
#: `chains` leg pointing away within `SHARP_WITHIN` bars fires on 1.0% of
#: eurusd episodes and 3.3% of gold's, where a single impulsive bar away fires
#: on 12.0% and 20.1%. A class that fires on one episode in a hundred cannot
#: carry a grade, and a conjunction of it with a width gate fires on 0.2% -
#: which is what the first version of this file measured, and is no test at
#: all. Both are kept and reported apart: `LEG` is `indicators.Displacement`'s
#: own primitive and belongs in the record even where it is rare.
REJECT, SPIKE, LEG, RUN, DRIFT, THROUGH, STALL = 1, 2, 4, 8, 16, 32, 64

#: The grade's numerator: a sharp reversal bar, a displacement leg, a trend
#: run, or a rejection candle. Pre-registered as the union before the run, with
#: every bit also reported separately so the union cannot hide which one
#: carried it - or that none did.
SHARP = REJECT | SPIKE | LEG | RUN

#: The grades compared. Each is a level's own **previous** episodes only.
#:
#: `sharp_share` is the claim as the user put it: either shape counts.
#:
#: `run_share` and `bar_share` split it, because the two halves differ in a way
#: that matters for reading the answer. `RUN` **entails departure** by
#: construction - it requires the net move away to clear `RUN_MOVE` - so a
#: grade built on it is partly a grade on the previous episode's outcome, and
#: that is the half most at risk of restating `hold_share`. `REJECT`, `SPIKE`
#: and `LEG` are one- and few-bar shapes that do not require the departure to
#: hold, so `bar_share` is shape uncontaminated by outcome. Reporting only the
#: union would leave "which one carried it" unanswerable, which is the
#: complaint `smc-primitives-overlap-and-are-closed` records against pooled
#: primitives.
#:
#: `hold_share` is the raw same-side record, which `record-auc.md` measured
#: between 0.4977 and 0.5104 across twelve configurations - carried so this
#: harness either reproduces a known number or is known to be wrong, which is
#: the strongest evidence in `level-shield.md` and the cheapest to get.
#: `hold_dev` is `|hold_share - 0.5|`, the decisiveness reading that scored
#: 0.6006 against the raw record's 0.5005 and is the reason a magnitude grade
#: is worth testing at all.
GRADES = ("sharp_share", "run_share", "bar_share", "long_share", "hold_share", "hold_dev")

#: `bar_share`'s numerator: the sharp shapes that do **not** require the
#: departure to have held.
SHARP_BAR = REJECT | SPIKE | LEG

#: `long_share` grades a level on how long its **previous** departures lasted,
#: against the duration running median of the series so far - the third
#: quantity, and the one `a-magnet-is-a-shared-reference` points at.
#:
#: **A censored previous episode counts as long**, which is the only treatment
#: that is not a lie: it lasted at least the horizon, and the horizon is above
#: any median the series can produce. Dropping censored episodes from the grade
#: would delete exactly the long ones and make the grade measure "this level's
#: bounces ended quickly", which is the opposite of the claim.
#:
#: The grade is carried under no illusions about its power. The committed power
#: sweep drives the hold rate from 0.714 to 0.882 with a planted barrier and
#: moves the per-level R grade by nothing at any strength, because with a few
#: hundred episodes over hundreds of level tags a level has two to four
#: previous episodes and the grade is mostly prior. The **pooled** duration
#: statistics are where the power is, and they are the primary reading.


# ─────────────────────────────── the books ───────────────────────────────


def _tagger():
    """A stable integer per level object, holding a reference so ids are not reused.

    `indicators.levels.Level` and `Zone` are mutated in place across bars and a
    merge keeps one of the two objects, so object identity *is* the book's own
    answer to "were these one level". `id()` alone is not enough: a dropped
    level's address can be handed to a new one, which would silently splice two
    levels' episode histories into one record and inflate exactly the grade
    under test. Keeping a reference makes that impossible.
    """
    tags: dict[int, int] = {}
    held: list[object] = []

    def tag(obj: object) -> int:
        key = id(obj)
        got = tags.get(key)
        if got is None:
            got = len(held)
            tags[key] = got
            held.append(obj)
        return got

    return tag


def book_path(
    series: Series, kind: str, *, unit_span: int, interval: str | None = None
) -> list[list[tuple[int, float]]]:
    """The book as of each bar's close, as `(tag, price)` per level.

    The repo's own indicators, bar by bar, so what is measured is what a
    strategy would read. Causal by construction in all four: `trend.pivots`
    only returns a turn once the window holds `reach` bars past it, `Pips.
    points` filters to what is knowable as of the last bar, `BjorgumLevels`
    updates each zone from the bar in hand, and a `Pivots` set is emitted only
    when a bar from the next period arrives.

    The price read per kind, and why:

    * `levels` - the posterior mean, `Level.at(when)`.
    * `bjorgum` - `Zone.level`, the pivot price, **not the band**. The band's
      width is the feature `bjorgum.md` found was half label leakage, and
      `Zone.near` exists precisely so a touch test does not enter through the
      thing under test.
    * `pips` - the confirmed turns only, `Pips.turns`.
    * `pivots` - every published name in every period from `PIVOT_PERIODS`,
      tagged by `(period, name)` so a record accumulates per name. See the
      module docstring: that is a per-name history, not a per-instance one.
    """
    tag = _tagger()
    out: list[list[tuple[int, float]]] = []
    if kind == "levels":
        book = Levels(unit_span=unit_span)
        read = lambda: [(tag(lv), lv.at(book.when)) for lv in book.levels]  # noqa: E731
    elif kind == "bjorgum":
        book = BjorgumLevels()
        read = lambda: [(tag(z), z.level) for z in book.zones]  # noqa: E731
    elif kind == "pips":
        book = Pips()
        read = lambda: [(int(p.time), p.price) for p in book.turns]  # noqa: E731
    elif kind == "pivots":
        book = Pivots(periods=PIVOT_PERIODS.get(interval or series.interval, PERIODS))
        names: dict[tuple[str, str], int] = {}
        read = lambda: [  # noqa: E731
            (names.setdefault((period, name), len(names)), price)
            for period, levels in book.sets.items()
            for name, price in levels.items()
        ]
    else:
        raise ValueError(f"{kind} is not one of {', '.join(KINDS)}.")
    for i in range(len(series.close)):
        book.handle_bar(
            _Bar(
                float(series.open[i]),
                float(series.high[i]),
                float(series.low[i]),
                float(series.close[i]),
                float(series.ts[i]),
            )
        )
        out.append(read())
    return out


#: The placebo's displacement, in volatility units, drawn uniformly from this
#: band on each side. Far enough that it is not the same level and near enough
#: that the distances price has to travel are the same scale.
SHIFT_LO, SHIFT_HI = 1.5, 3.0

#: A placebo landing this close to any real level in the book is refused and
#: redrawn on the other side, then dropped. A placebo that is a level is not a
#: placebo, and `MERGE_VOL` is the distance at which the book itself calls two
#: prices one level - twice it is the honest clearance.
CLEAR_VOL = 2.0 * MERGE_VOL


def placebo_books(
    books: list[list[tuple[int, float]]],
    unit: np.ndarray,
    rng: np.random.Generator,
) -> list[list[tuple[int, float]]]:
    """Each level displaced, with its tag kept so a placebo has a history too.

    The offset is drawn **once per tag**, not once per bar, which is the whole
    point: a placebo level has to persist so that its own previous episodes can
    grade its next one. Redrawing per bar would give every placebo an empty
    record and the part 2 comparison would have no control at all.

    It is stored **in price**, fixed at first sight, not in volatility units
    re-multiplied each bar. A unit offset held constant is a price that wanders
    as volatility changes, and a wandering level is reached more often in a
    volatile stretch - which is precisely the confound the compression strata
    exist to remove, re-introduced inside the control. Stored in price, the
    placebo tracks its real level's own drift plus a constant, so the two books
    move together and differ only in where they sit.
    """
    offsets: dict[int, float] = {}
    out: list[list[tuple[int, float]]] = []
    for i, book in enumerate(books):
        scale = float(unit[i])
        here: list[tuple[int, float]] = []
        reals = [p for _, p in book]
        for ident, price in book:
            off = offsets.get(ident)
            if off is None:
                if scale <= 0.0:
                    continue
                sign = 1.0 if rng.random() < 0.5 else -1.0
                offsets[ident] = off = float(rng.uniform(SHIFT_LO, SHIFT_HI)) * sign * scale
            moved = price + off
            if scale > 0.0 and any(abs(moved - p) < CLEAR_VOL * scale for p in reals):
                continue
            here.append((ident, moved))
        out.append(here)
    return out


# ────────────────────────────── the shapes ──────────────────────────────


def _candles(series: Series, lo: int, hi: int) -> list[Candle]:
    return [
        Candle(
            high=float(series.high[k]),
            low=float(series.low[k]),
            open=float(series.open[k]),
            close=float(series.close[k]),
            when=float(series.ts[k]),
        )
        for k in range(lo, hi)
    ]


def _ohlc(series: Series, k: int) -> C.Bar:
    return C.Bar(
        open=float(series.open[k]),
        high=float(series.high[k]),
        low=float(series.low[k]),
        close=float(series.close[k]),
        time=float(series.ts[k]),
    )


def shape_at(
    series: Series,
    i: int,
    price: float,
    away: int,
    scale: float,
    *,
    run_eff: float = RUN_EFF,
) -> int:
    """The departure's shape as a bit mask, from bar `i` where the touch was.

    `away` is the direction a bounce goes: -1 when price rose into the level
    (it is resistance) and +1 when price fell into it. The sign is carried
    explicitly because `efficiency` went into this repo unsigned once and the
    note says the obvious way to trade it would have had the sign backwards.

    Every bit is decided by code that already exists:

    * `REJECT` - `candles.confirms`, which is a hammer, a shooting star or an
      engulfing bar that **touched the level and closed away from it**. That
      last check is the one most easily left out and the most important: a
      hammer whose tail pierces support and whose close is still below it is
      support breaking, not support holding.
    * `SPIKE` - within `SHARP_WITHIN` bars, a bar that is `Candle.impulsive`
      (the desk's `PUSH_BODY` 0.70 - body a large share of range), at least
      `SPIKE_RANGE` units wide, pointing `away` **and closing on the away side
      of the level**. All three of the user's conditions, each from code that
      already exists.
    * `LEG` - the same, as `indicators.levels.chains`' multi-candle
      displacement leg at `PUSH_MIN` 2 / `PUSH_BODY` 0.70 / `CHAIN_GAP` 1. Rare
      on daily bars (1.0-3.3% of episodes, measured before the freeze) and kept
      because it is `Displacement`'s own primitive.
    * `RUN` - `trend.ratio` of the closes over `SHAPE_BARS` at or above
      `run_eff`, with the net move `away` clearing `RUN_MOVE` units. Efficiency
      alone is direction-blind: a clean run **through** the level is just as
      efficient, so the move condition is what makes it a bounce.
    * `DRIFT` - departed by `RUN_MOVE` units and none of the above. The
      residual, which is what the question compares against.
    * `THROUGH` / `STALL` - did not depart, and ended on the far side of the
      level or did not. Reported rather than dropped: 62% of 1d episodes do not
      depart within four bars, and a harness that emitted only its interesting
      classes would hide that the question is about a third of its own touches.
    """
    n = len(series.close)
    end = i + SHAPE_BARS
    if end > n or scale <= 0.0:
        return 0
    mask = 0
    tol = TOUCH_VOL * scale

    if i >= 1 and C.confirms([_ohlc(series, i - 1), _ohlc(series, i)], price, away > 0, tol):
        mask |= REJECT

    window = _candles(series, max(0, i - 1), end)
    lead = 1 if i >= 1 else 0
    for candle in window[lead : lead + SHARP_WITHIN]:
        if (
            candle.sign == away
            and candle.impulsive(PUSH_BODY)
            and candle.span >= SPIKE_RANGE * scale
            and (candle.close - price) * away > 0
        ):
            mask |= SPIKE
            break
    for leg in chains(window, push_min=PUSH_MIN, push_body=PUSH_BODY, chain_gap=CHAIN_GAP):
        if leg.side == away and leg.origin < lead + SHARP_WITHIN:
            mask |= LEG
            break

    moved = (float(series.close[end - 1]) - price) * away / scale
    eff = T.ratio([float(x) for x in series.close[i:end]])
    if moved >= RUN_MOVE and eff is not None and eff >= run_eff:
        mask |= RUN
    if moved < RUN_MOVE:
        return mask | (THROUGH if moved < 0 else STALL)
    return mask or DRIFT


# ───────────────────────────── the episodes ─────────────────────────────


@dataclass(slots=True)
class Rows:
    """One row per scored touch episode. Flat, so an aggregation is a mask."""

    #: Which level, stable across bars. See `_tagger`.
    tag: np.ndarray
    bar: np.ndarray
    #: The bootstrap block: at least one outcome window and at least one day.
    block: np.ndarray
    #: +1 when a bounce goes up (the level is support), -1 when it goes down.
    away: np.ndarray
    #: Compression quintile crossed with era, so `0 <= stratum < BINS`.
    stratum: np.ndarray
    #: `shape_at`'s bit mask for this episode's own departure. **Not usable as
    #: a grade for this episode** - that is the lookahead the study is about.
    shape: np.ndarray
    #: Travelled `RACE` units away before `RACE` units through. **Descriptive
    #: only** - a bounce rate is geometry and decides nothing here.
    held: np.ndarray
    #: Whether that race resolved inside the horizon. `held` is meaningless
    #: where this is false; the R columns are not, which is why they are not
    #: gated on it.
    decided: np.ndarray
    #: Both boundaries inside one bar, resolved against the trade.
    tie: np.ndarray
    #: Signed forward excursion at the horizon, in units, positive `away`.
    excursion: np.ndarray
    #: R per reward-to-risk in `TARGETS`, stop one unit through the level.
    #: **Zero on a driftless walk at every target**, which is what makes these
    #: the deciding numbers rather than the hit rate.
    r: dict[float, np.ndarray]
    #: R marked to market at the horizon with no target at all. Lower variance
    #: than a barrier race and immune to the tie rule, so it is the arm to
    #: trust when the two disagree.
    r_mtm: np.ndarray
    #: Bars from the touch to the **first return to the level** - how long the
    #: departure lasted. `DURATION_CENSORED` where the touch bar closed on the
    #: through side, so there was no departure to time.
    duration: np.ndarray
    #: Price had not come back by the horizon, so `duration` is a lower bound
    #: and not a value. Kaplan-Meier is what makes these usable.
    censored: np.ndarray
    #: Bars from the touch to the furthest point reached away from the level.
    #: Censored in its own way - a departure still extending at the horizon
    #: peaks at the horizon - so it is descriptive beside `duration`.
    peak_at: np.ndarray
    #: Episodes at this level strictly before this one.
    n_prev: np.ndarray
    #: The grades, each from strictly earlier episodes at this level only.
    sharp_share: np.ndarray
    run_share: np.ndarray
    bar_share: np.ndarray
    long_share: np.ndarray
    hold_share: np.ndarray
    hold_dev: np.ndarray
    #: Touches that passed the de-overlap and were still not scored because the
    #: touch bar **closed more than `STOP_VOL` units through the level** - the
    #: stop was already behind the entry, so there is no trade to price.
    #:
    #: **This is a selection and it is counted rather than hidden.** It drops
    #: the episodes where the level broke hardest, which tilts the surviving
    #: population in favour of the bounce. It is applied identically to every
    #: arm, so the arm comparison is unaffected; the absolute hold rate and
    #: mean R are conditioned on it and that has to be read with them.
    skipped: int = 0
    #: Touches dropped because nothing was decided inside the horizon.
    undecided: int = 0

    def __len__(self) -> int:
        return len(self.bar)


def _blocks(series: Series, interval: str, horizon: int) -> np.ndarray:
    """Bootstrap blocks at least as long as the outcome window and as a day.

    `level_shield_agg` resamples calendar days, which is right at 15m where a
    day is 96 bars against a 48-bar horizon. At 1d a calendar day is one bar
    and the horizon is 20, so a day block would resample units that share
    nineteen of their twenty outcome bars and the standard error would be far
    too narrow. One rule covers both: block by `max(horizon, bars per day)`.
    """
    per_day = {"15m": 96, "1h": 24, "4h": 6, "1d": 1}.get(interval, 1)
    width = max(horizon, per_day)
    return (np.arange(len(series.close)) // width).astype(np.int64)


def _race(series: Series, i: int, price: float, away: int, scale: float, horizon: int):
    """The symmetric race and the R of each reward-to-risk, from bar `i + 1`.

    The touch bar is excluded from both. Its own range straddles the level by
    definition, so letting it decide anything would settle the outcome out of
    the event that defined it - and nothing could be traded on it either, since
    the touch is only known once that bar has closed. Entry is therefore
    `close[i]`, which is also what makes the risk real: the stop sits
    `STOP_VOL` units through the **level**, so a touch bar that closed a long
    way away buys a wider stop and a worse R, exactly as it would live.

    Returns `None` only when the touch bar closed further through the level
    than the stop - there is no trade there, and pricing one would invent a
    position taken at a loss already. An **undecided** descriptive race is not
    a `None`: the second element of the result says whether it resolved, and
    the R columns are reported either way.

    A bar whose range covers both barriers is resolved **against** the trade,
    and the tie share is reported: `level-shield.md` found ties at 0.04-0.8% of
    decided races, an order of magnitude too small to carry a result, and a
    rule explicit about its direction can be argued with.
    """
    entry = float(series.close[i])
    stop = price - away * STOP_VOL * scale
    risk = away * (entry - stop)
    if risk <= 0.0:
        return None
    last = min(i + horizon, len(series.close) - 1)
    reach = RACE * scale
    up, down = price + reach, price - reach
    held: bool | None = None
    tie = False
    pending: dict[float, float | None] = dict.fromkeys(TARGETS)
    for j in range(i + 1, last + 1):
        hi, lo = float(series.high[j]), float(series.low[j])
        if held is None:
            if hi >= up and lo <= down:
                held, tie = False, True
            elif hi >= up:
                held = away > 0
            elif lo <= down:
                held = away < 0
        hit_stop = (lo <= stop) if away > 0 else (hi >= stop)
        for k in TARGETS:
            if pending[k] is not None:
                continue
            target = entry + away * k * risk
            hit_target = (hi >= target) if away > 0 else (lo <= target)
            # Each reward-to-risk is its own trade: the 1R target can fill on
            # bar 3 while the 3R trade is still live and stops on bar 7. One
            # shared "stopped" flag would close them all at the first stop and
            # charge the 1R trade for a loss it had already banked out of.
            if hit_target and not hit_stop:
                pending[k] = k
            elif hit_stop:
                pending[k] = -1.0
        if held is not None and all(v is not None for v in pending.values()):
            break
    # The R series is **not** gated on the descriptive race resolving. An
    # episode where price stayed inside one unit of the level for the whole
    # horizon has no hold/break answer but it does have an R - a small one -
    # and dropping it would discard the quiet, near-zero outcomes and inflate
    # the variance of every arm's mean. `decided` carries the distinction so
    # the hold rate can exclude them and the R cannot.
    mtm = away * (float(series.close[last]) - entry) / risk
    # The open arm's denominator is the **level's** one unit, not the entry's
    # risk. Measured: with the entry risk it reads a per-trade sd of 10.3 on
    # eurusd 1d and 20.6 on pivots, because a touch bar closing just through
    # the level leaves a risk near zero and the ratio explodes. Flooring or
    # dropping those would be worse than either - they are the episodes where
    # the level already failed, so excluding them selects in favour of the
    # bounce. A fixed denominator keeps every episode and makes this arm the
    # forward excursion in units, which is bounded like the bar range is.
    open_r = away * (float(series.close[last]) - entry) / (STOP_VOL * scale)
    return (
        bool(held),
        held is not None,
        tie,
        {k: (mtm if v is None else v) for k, v in pending.items()},
        open_r,
    )


def _duration(series: Series, i: int, price: float, away: int, horizon: int):
    """`(bars to the first return to the level, censored, bars to the MFE)`.

    The duration of the departure, which is the first-passage time back to
    `price` starting from the touch bar's close. Measured from bar `i + 1`, so
    the touch bar - whose range contains the level by definition - cannot end
    the departure it started.

    `censored` is true when price had not come back by the horizon, and the
    duration is then the horizon itself as a **lower bound**, not a value.
    `level-bounce.md` reports the censored share per cell for that reason: a
    mean over the uncensored episodes alone is biased short, and that bias
    points the same way as the finding a short bounce would be.

    `None` when the touch bar closed on the **through** side of the level.
    There is no departure to time there, and timing one would measure the
    level failing and call it a bounce that ended quickly.
    """
    entry = float(series.close[i])
    if away * (entry - price) <= 0.0:
        return None
    last = min(i + horizon, len(series.close) - 1)
    best, best_at = 0.0, 0
    for j in range(i + 1, last + 1):
        hi, lo = float(series.high[j]), float(series.low[j])
        reach = away * ((hi if away > 0 else lo) - price)
        if reach > best:
            best, best_at = reach, j - i
        if lo <= price <= hi:
            return j - i, False, best_at
    return last - i, True, best_at


def episodes(
    series: Series,
    books: list[list[tuple[int, float]]],
    unit: np.ndarray,
    stratum: np.ndarray,
    *,
    interval: str,
    horizon: int,
    run_eff: float = RUN_EFF,
    gap_bars: int | None = GAP_BARS,
) -> Rows:
    """Every de-overlapped touch episode, its departure shape and its outcome.

    A touch at bar `i` reads the book as of bar `i - 1`, so the level existed
    before the bar that reached it. An episode is scored only when the previous
    bar did not also touch that level and no earlier episode at that level was
    scored within `gap_bars` - the forward window itself, so two scored
    episodes never share an outcome bar.

    The grades are filled in one forward pass at the end, from strictly earlier
    episodes at the same level, against a pooled rate that is itself a running
    mean over strictly earlier episodes. Nothing in a row's grade comes from
    the row or from any row after it.
    """
    gap = horizon if gap_bars is None else int(gap_bars)
    blocks = _blocks(series, interval, horizon)
    last_touch: dict[int, int] = {}
    last_scored: dict[int, int] = {}
    found: list[dict] = []
    skipped = undecided = 0
    for i in range(1, len(series.close) - SHAPE_BARS):
        scale = float(unit[i - 1])
        if scale <= 0.0:
            continue
        tol = TOUCH_VOL * scale
        hi, lo = float(series.high[i]), float(series.low[i])
        prev_close = float(series.close[i - 1])
        for ident, price in books[i - 1]:
            if not (lo - tol <= price <= hi + tol):
                continue
            was = last_touch.get(ident, -(10**9))
            last_touch[ident] = i
            if was == i - 1 or i - last_scored.get(ident, -(10**9)) < gap:
                continue
            away = -1 if prev_close < price else 1
            stop = price - away * STOP_VOL * scale
            if away * (float(series.close[i]) - stop) <= 0.0:
                skipped += 1
                continue
            raced = _race(series, i, price, away, scale, horizon)
            if raced is None:
                skipped += 1
                continue
            held, decided, tie, rs, mtm = raced
            undecided += not decided
            timed = _duration(series, i, price, away, horizon)
            last_scored[ident] = i
            far = min(i + horizon, len(series.close) - 1)
            found.append(
                {
                    "tag": ident,
                    "bar": i,
                    "block": int(blocks[i]),
                    "away": away,
                    "stratum": int(stratum[i - 1]),
                    "shape": shape_at(series, i, price, away, scale, run_eff=run_eff),
                    "held": held,
                    "decided": decided,
                    "tie": tie,
                    "excursion": (float(series.close[far]) - price) * away / scale,
                    "r": rs,
                    "r_mtm": mtm,
                    "duration": DURATION_CENSORED if timed is None else timed[0],
                    "censored": bool(timed[1]) if timed else False,
                    "peak_at": timed[2] if timed else 0,
                }
            )

    found.sort(key=lambda row: row["bar"])
    bits = {"sharp_share": SHARP, "run_share": RUN, "bar_share": SHARP_BAR}
    seen: dict[int, list[tuple[int, bool, bool]]] = {}
    pooled: dict[str, float] = dict.fromkeys(("hold", "long", *bits), 0.0)
    pooled_n = 0
    # The duration median is **running**, over episodes strictly earlier in
    # this series, so `long_share` never reads a threshold computed from the
    # future. A whole-sample median would be the same lookahead the grades
    # exist to avoid, arriving through the threshold instead of the history.
    durations: list[int] = []
    for row in found:
        history = seen.get(row["tag"], ())
        n_prev = len(history)
        row["n_prev"] = n_prev
        for grade, bit in bits.items():
            base = pooled[grade] / pooled_n if pooled_n else 0.5
            hits = sum(1 for mask, _, _ in history if mask & bit)
            row[grade] = (hits + PRIOR_K * base) / (n_prev + PRIOR_K)
        base_hold = pooled["hold"] / pooled_n if pooled_n else 0.5
        held_prev = sum(1 for _, held, _ in history if held)
        row["hold_share"] = (held_prev + PRIOR_K * base_hold) / (n_prev + PRIOR_K)
        row["hold_dev"] = abs(row["hold_share"] - 0.5)
        base_long = pooled["long"] / pooled_n if pooled_n else 0.5
        long_prev = sum(1 for _, _, long in history if long)
        row["long_share"] = (long_prev + PRIOR_K * base_long) / (n_prev + PRIOR_K)
        # Censored counts as long: it lasted at least the horizon, which is
        # above any running median. Dropping censored episodes would delete
        # the long ones and invert what the grade means.
        mid = st.median(durations) if durations else 0.0
        is_long = row["censored"] or (
            row["duration"] > mid and row["duration"] != DURATION_CENSORED
        )
        seen.setdefault(row["tag"], []).append((row["shape"], row["held"], is_long))
        for grade, bit in bits.items():
            pooled[grade] += 1.0 if row["shape"] & bit else 0.0
        pooled["hold"] += 1.0 if row["held"] else 0.0
        pooled["long"] += 1.0 if is_long else 0.0
        pooled_n += 1
        if row["duration"] != DURATION_CENSORED:
            durations.append(row["duration"])

    def col(name: str, dtype):
        return np.asarray([row[name] for row in found], dtype=dtype)

    return Rows(
        tag=col("tag", np.int64),
        bar=col("bar", np.int64),
        block=col("block", np.int64),
        away=col("away", np.int64),
        stratum=col("stratum", np.int64),
        shape=col("shape", np.int64),
        held=col("held", bool),
        decided=col("decided", bool),
        tie=col("tie", bool),
        excursion=col("excursion", float),
        r={k: np.asarray([row["r"][k] for row in found], dtype=float) for k in TARGETS},
        r_mtm=col("r_mtm", float),
        duration=col("duration", np.int64),
        censored=col("censored", bool),
        peak_at=col("peak_at", np.int64),
        n_prev=col("n_prev", np.int64),
        sharp_share=col("sharp_share", float),
        run_share=col("run_share", float),
        bar_share=col("bar_share", float),
        long_share=col("long_share", float),
        hold_share=col("hold_share", float),
        hold_dev=col("hold_dev", float),
        skipped=skipped,
        undecided=undecided,
    )


def strata_of(unit: np.ndarray, span: int, *, eras: int = ERAS) -> np.ndarray:
    """Compression quintile crossed with era, in `[0, BINS)`.

    Quintiles of each arm's **own** distribution, because the arms have
    different volatility processes and real edges applied to a null arm would
    misalign the bins - `level_shield` makes the same choice for the same
    reason.
    """
    comp = compression(unit, span)
    edges = np.quantile(comp, np.linspace(0.0, 1.0, STRATA + 1)[1:-1])
    quint = np.searchsorted(edges, comp, side="right").astype(np.int64)
    if eras <= 1:
        return quint
    era = np.minimum((np.arange(len(comp)) * eras) // len(comp), eras - 1)
    return quint * eras + era


@dataclass(slots=True)
class Measured:
    kind: str
    arm: str
    draw: int
    rows: Rows
    bars: int
    levels: int


def measure(
    series: Series,
    kind: str,
    *,
    interval: str,
    settings: dict,
    books: list[list[tuple[int, float]]] | None = None,
    unit: np.ndarray | None = None,
    run_eff: float = RUN_EFF,
) -> Measured:
    """One (series, kind) pass: build the book, find the episodes, score them."""
    span = int(settings["unit_span"])
    scale = units(series, span) if unit is None else unit
    book = (
        book_path(series, kind, unit_span=span, interval=interval) if books is None else books
    )
    rows = episodes(
        series,
        book,
        scale,
        strata_of(scale, span),
        interval=interval,
        horizon=int(settings["horizon"]),
        run_eff=run_eff,
    )
    return Measured(
        kind=kind,
        arm="real",
        draw=0,
        rows=rows,
        bars=len(series.close),
        levels=len({int(t) for t in rows.tag}),
    )


#: Set to point the study at a copy of the store on a bigger box. The default
#: is `level_shield.STORE`, which is relative so this runs anywhere the repo is.
BOUNCE_STORE = os.environ.get("BOUNCE_STORE") or STORE

__all__ += ["BINS", "Measured", "SHARP", "shape_at", "strata_of"]
