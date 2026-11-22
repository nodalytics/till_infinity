"""Discovery: sweep the panel, keep the losers, and make the controls structural.

Asked for on 2026-11-01 - "statespace can also use these indicators or more
than itself, it can also use it in discovery mode to search for patterns and
edges too". This is that mode, and the whole design question is not *how to
search* - a grid is a grid - but **how to stop a search manufacturing an
edge**, because this desk's measured history is that an uncontrolled one does.

So the controls are not a step a caller may skip. They are parameters this
module **refuses to run without**, in the same spirit as
`node.metrics.DeflatedSharpe` refusing to report a number it was not given the
trials for, and `node.discovery.Proposal` refusing an origin it cannot state.

## The refusals, each paid for

**What `score` will not run at all** - these raise, because every one of them
produces a number that looks like a result:

| refused | the measurement behind it |
| --- | --- |
| a candidate with no arms | six artefacts passed DSR, PBO and SPA; surrogates caught them |
| an arm with no named property | Boom/Crash gained more than any traded class under one |
| an arm of neither kind | a third kind is skipped, and an empty arm reads as a pass |
| a separation below the forward window | direction AUC 0.79 collapsed to 0.51 de-overlapped |
| a reader that reads its own future | `drawing.gaps` emitted only *unfilled* gaps: +0.50R a trade |
| a question not in `QUESTIONS` | a trial that cannot say what it asked is unreadable |

**What it will not score** - these come back as a `Trial` carrying the reason,
so the candidate still counts toward the multiplicity:

| refused | why |
| --- | --- |
| too few events | a floor, before any arm is built |
| too few events **after the strata** | `node.metrics.moments` refuses fewer than four returns |
| a degenerate outcome spread | one btc trial read a Sharpe of -18.40 from a daily-boundary defect |

**What it will not call a survivor**:

| refused | why |
| --- | --- |
| a run whose placebo pool scored | a block of 8 found structure in 27 of 36 placebo pools |
| arms that disagree about the side | that is a statement about the arms, not an effect |
| every arm uninformative | no arm could judge it, so the pairing is wrong |

And one thing that is refused by having nowhere to put it: `Row` carries the
threshold, the event count and the **mean**, and no z. A z falls as the event
count falls, so a grid of z's has a maximum wherever the count stops paying for
the mean - which looks like a discovered threshold and is arithmetic.

## What is measured, and why it is size and not direction

The statistic is the **forward absolute move in trailing-standard-deviation
units**, within volatility strata. Three separate findings put it there.

`direction-is-closed-not-just-null`: the direction gate finds a *planted*
drift at z +2.90 and earns 2% of one spread. A signed statistic is still
offered - `question="direction"` - because refusing to compute it would hide
the result rather than report it, and `Candidate.question` records which was
asked so a reader can tell a size claim from a direction claim.

`nulls.trailing` is the denominator because nothing in this repository has
beaten it: a three-state HMM, a fifty-neighbour analogue on 0 of 20 cells, an
Ising susceptibility, a panel of stale forecasts at seven lags and a
rank-then-map model across five instruments all lost to it. Dividing by it
means a candidate is scored against the bar that is actually hard.

`auc-is-free-on-volatility-targets` is why the strata are not optional: 0.805
on a constant-volatility process against 0.525 within strata, and incumbents
alone read 0.74 to 0.78. A lift reported pooled is a lift reported on the
volatility level - and dividing by the trailing estimate is not enough on its
own, because the normalised outcome still falls with the volatility level:
measured on 2,400 bars of GARCH it runs **0.914** in the quietest stratum
against **0.677** in the busiest, so a detector that only fires when it is
quiet earns a pooled lift of +0.190 from the stratum and +0.092 within it.

**And the test is two-sided.** "This shape precedes an unusually quiet
stretch" is the same claim with the sign flipped and is just as tradable, so a
one-sided gate silently answers half the question.
`null-structure-claims-on-the-same-detector` asks for both sides and for the
reach to be swept, and both are here - `ArmResult.passes` is 0.005 per tail
and `shaping.reader` takes the reach.

## The seam, and why the reader is injected

A `Candidate` carries a **reader**: candles in, one float per candle out. It
does not carry a detector, and that is deliberate on two counts.

The engineering one: only `actor.py` in this package may import
`nautilus_trader`, and the 33 catalogued detectors are Nautilus `Indicator`s.
`actor.detector_reader` builds a reader from `indicators.build_detector`, so
the panel is reachable without this module knowing what a `Bar` is.

The measurement one, which matters more: a **series** arm re-runs *the same
reader* over null candles. That is what "null every candidate against a walk
through the same detector" means mechanically, and it only works if the
detector is a value the harness holds rather than a branch inside it. Four
alternating-detector readings came out level with a walk precisely because the
detector's own structure was in both arms.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from random import Random

from .nulls import block_shuffled, rotated, trailing

#: One bar as `(open, high, low, close)`. Floats, in the feed's own price.
#:
#: **Not a Nautilus `Bar`,** and not `indicators.candles.Bar` either. A tuple
#: because a series arm has to *manufacture* bars - `walk_with_bar_geometry`
#: resamples a bar's wick proportions - and manufacturing a fixed-precision
#: `Price` truncates the series before the detector sees it. btc at its
#: tradable two decimals moves a 1m reading by 3e-5 relative for that reason.
Candle = tuple[float, float, float, float]

#: Candles in, one reading per candle out. `nan` means "nothing yet" - a
#: detector still warming, or a bar whose reading needs a previous bar there
#: is not. Never zero for that case: a zero reading is evidence of stillness.
Reader = Callable[[Sequence[Candle]], Sequence[float]]

#: Bars of trailing increments the volatility unit is estimated over. 64 is
#: `nulls.LEAST_FOR_NULL`, which is the floor below which a shuffled arm is a
#: handful of points and its extreme is noise.
SPAN = 64

#: Quantile bands the volatility unit is stratified into. Five rather than ten
#: because a stratum needs enough events to have a mean: at 10 bands a sweep
#: that finds 200 events puts 20 in each, and `pool-events-before-a-per-feed-
#: guard` records a min-events guard dropping 141 of 146 feeds and turning 0.9
#: sigma into 4.8.
BANDS = 5

#: Forward bars the outcome is measured over, and the minimum separation
#: between two events. **These are one number on purpose.** A short skip rule
#: with a long forward window gave direction AUC 0.79 that collapsed to 0.51,
#: and the tell was the placebo and shuffled arms tracking the real one.
HORIZON = 4

#: Draws per arm. 200 puts the resolution of a one-sided p at 1/201, which is
#: finer than any threshold here reads.
DRAWS = 200

#: The least events a candidate needs before its lift is reported. Below this
#: the within-strata mean is one or two observations per band.
LEAST_EVENTS = 40

#: What a candidate claims. The same words as `node.discovery.Question`, as
#: strings rather than an enum - a second enum with the same members is a
#: second thing to keep in step, and this module only validates membership.
#:
#: `direction` is in the set and is **expected to fail**: it is the one
#: question measured closed here, so a sweep reporting a directional edge has
#: found a bug rather than a trade.
QUESTIONS = frozenset({"direction", "dispersion", "participation", "regime", "context"})

#: Arm kinds. A `series` arm manufactures a whole null series and the reader
#: runs again on it; an `anchors` arm keeps the data untouched and moves only
#: which bars were called events.
#:
#: **Both are needed and neither substitutes for the other.** A sign flip or a
#: shuffle removes the thing a geometric claim is about, so it reports a
#: confident failure either way; an anchor move cannot tell you what the
#: detector produces from bar geometry alone. `node.surrogates.for_shape` makes
#: the same split for the same reason.
SERIES = "series"
ANCHORS = "anchors"


@dataclass(frozen=True, slots=True)
class Arm:
    """One control, labelled with the property it removes.

    `removes` is required and must be non-empty, because
    `a-control-is-only-for-a-named-property` is a measured finding rather than
    a style rule: an arm whose property is unstated answers a question nobody
    asked, and Boom/Crash gained more than any traded class under one.
    """

    name: str
    #: The property this arm removes, in words. Goes in the report.
    removes: str
    kind: str
    #: `series`: `(candles, rng) -> candles`. `anchors`: `(length, events,
    #: rng) -> indices`, taking the real event indices so a distance-matched
    #: arm can keep their spacing.
    make: Callable[..., object] = field(repr=False, default=lambda *_a, **_k: ())

    def __post_init__(self) -> None:
        if not self.removes.strip():
            raise ValueError(
                f"arm {self.name!r} names no property. A control is only ever for a "
                f"named property - an unlabelled one still produces a number, and the "
                f"number looks like a comparison."
            )
        if self.kind not in {SERIES, ANCHORS}:
            raise ValueError(f"arm {self.name!r} has kind {self.kind!r}, not {SERIES} or {ANCHORS}")


@dataclass(frozen=True, slots=True)
class ArmResult:
    """One arm's verdict, in the shape `node.surrogates.Surrogate` takes.

    The field names are `name`, `observed` and `draws` deliberately:
    `as_surrogate()` returns exactly that mapping, so the node layer scores
    this with its own class rather than with a second implementation of the
    same percentile. `tests/test_statespace_searching.py` asserts the two
    agree, which is how the duplication stays a duplication of three lines of
    arithmetic rather than of a judgement.
    """

    name: str
    removes: str
    observed: float
    draws: tuple[float, ...]

    @property
    def percentile(self) -> float:
        if not self.draws:
            return 0.0
        return sum(1 for d in self.draws if d < self.observed) / len(self.draws)

    @property
    def p_value(self) -> float:
        """**Two-sided** permutation p, with the observed value included.

        The `+1` on both sides keeps p away from exactly zero, which it cannot
        be from a finite number of draws. Doubling the smaller tail is the
        two-sided form, and it is two-sided for the reason `passes` is.
        """
        n = len(self.draws)
        if n == 0:
            return 1.0
        above = sum(1 for d in self.draws if d >= self.observed)
        below = sum(1 for d in self.draws if d <= self.observed)
        return min(1.0, 2.0 * (min(above, below) + 1) / (n + 1))

    @property
    def uninformative(self) -> bool:
        """Did this arm fail to move the statistic at all?

        **A null that cannot affect the statistic reports a confident pass.**
        An anchors arm paired with a statistic that does not depend on which
        bars were chosen is the shape to watch for; so is a series arm whose
        reader ignores the series.
        """
        if len(self.draws) < 2:
            return True
        spread = max(self.draws) - min(self.draws)
        return spread / max(abs(self.observed), 1e-12) < 1e-9

    @property
    def side(self) -> int:
        """Which tail the observed value sits in. 0 at the median."""
        if self.percentile > 0.5:
            return 1
        return -1 if self.percentile < 0.5 else 0

    @property
    def evidence(self) -> float:
        """How far from the middle of this arm's own null, in 0..0.5.

        What ranks the arms under a two-sided test: an arm the observed value
        sits *below* every draw of is as informative as one it sits above, and
        a percentile of 0.5 is no evidence either way.
        """
        return abs(self.percentile - 0.5)

    @property
    def passes(self) -> bool:
        """Outside this arm's own 0.5% tails. **Two-sided, and that is the fix.**

        A one-sided test at the 99th percentile asks only whether the
        candidate's events precede *larger* moves. "This shape precedes an
        unusually quiet stretch" is the same claim with the sign flipped and is
        just as tradable - selling volatility is a trade - so a one-sided gate
        silently answers half the question.

        `null-structure-claims-on-the-same-detector` is explicit about it:
        walk through the same detector with the same bar geometry, **test both
        sides**, and sweep the reach. The level is halved to 0.005 on each tail
        so the size of the test is unchanged.
        """
        return not self.uninformative and (self.percentile >= 0.995 or self.percentile <= 0.005)

    def as_surrogate(self) -> dict[str, object]:
        """The keyword arguments `node.surrogates.Surrogate` is built from."""
        return {"name": self.name, "observed": self.observed, "draws": self.draws}

    def line(self) -> str:
        if self.uninformative:
            return (
                f"{self.name}: uninformative over {len(self.draws)} draws - removes {self.removes}"
            )
        return (
            f"{self.name}: percentile {self.percentile:.3f} p {self.p_value:.4f} "
            f"{'passes' if self.passes else 'fails'} - removes {self.removes}"
        )

    @property
    def tail(self) -> str:
        """Which side of the null, in words, for a report."""
        return "above" if self.side > 0 else ("below" if self.side < 0 else "at")


@dataclass(frozen=True, slots=True)
class Candidate:
    """One thing to try: a reader, a threshold, and what it claims.

    `reader` rather than a detector name, so the same value can be re-run over
    an arm's manufactured series. See the module docstring.
    """

    family: str
    name: str
    question: str
    threshold: float
    reader: Reader = field(repr=False, default=lambda _c: ())
    #: Which `indicators.Reading` the detector was fed, where it took one.
    source: str = ""
    params: tuple[tuple[str, float], ...] = ()
    #: Whether the reading at bar `t` can only be computed from bars after
    #: `t`. **A declaration, and `score` refuses it.** A triangle is only a
    #: triangle once it has broken out, so a "confirmed" shape carries the
    #: future in its definition unless its reader is explicit about when the
    #: definition completed.
    lookahead: bool = False

    def __post_init__(self) -> None:
        if self.question not in QUESTIONS:
            raise ValueError(
                f"{self.name!r} asks {self.question!r}, which is not one of "
                f"{sorted(QUESTIONS)}. A trial whose question is unrecorded cannot be "
                f"told from one that asked a question already closed."
            )

    @property
    def label(self) -> str:
        """A name a result can be asked for again by."""
        parts = [self.family, self.name]
        if self.source:
            parts.append(self.source)
        tail = ",".join(f"{k}={v:g}" for k, v in self.params)
        got = ":".join(parts)
        return f"{got}@{self.threshold:g}" + (f"[{tail}]" if tail else "")


@dataclass(frozen=True, slots=True)
class Trial:
    """One candidate, scored. **Kept whether it won or lost.**

    `node.metrics.trial_variance` takes the readings and not a number, because
    the spread of Sharpes across everything tried only exists if the search
    kept its losers. `returns` is the per-event series so the node layer can
    register a `DeflatedSharpe` from this without recomputing anything.
    """

    candidate: Candidate
    observed: float
    events: int
    arms: tuple[ArmResult, ...] = ()
    #: Per-event outcome, de-meaned inside its own volatility stratum. The
    #: mean of this is `observed`.
    returns: tuple[float, ...] = ()
    #: The bar indices this candidate fired on, de-overlapped, and how many
    #: bars the series held. Kept so `Sweep.effective_trials` can measure how
    #: much two candidates are the same candidate from the events themselves
    #: rather than from the positional alignment of two outcome series.
    at: tuple[int, ...] = ()
    span: int = 0
    #: Non-empty when this candidate was never scored, and why.
    refused: str = ""

    @property
    def scored(self) -> bool:
        return not self.refused and self.events > 0

    @property
    def sharpe(self) -> float:
        """Per-event Sharpe of the within-strata lift, or 0.0.

        The same `mean / sd` as `node.metrics.sharpe`, on the series this
        trial emits, so a trial set here deflates against the same scale.
        """
        if len(self.returns) < 2:
            return 0.0
        spread = statistics.pstdev(self.returns)
        return statistics.fmean(self.returns) / spread if spread > 0 else 0.0

    @property
    def claimed_sharpe(self) -> float:
        """`sharpe` in the direction this trial claims. **For a winner only.**

        The two-sided test means a survivor can sit *below* its null - a shape
        that precedes an unusually quiet stretch - and such a trial's lift and
        therefore its Sharpe are negative, while the trade it implies is short
        volatility and makes money. `node.metrics.deflated_sharpe` asks whether
        a Sharpe beats the best of N nothings, so it has to be handed the
        Sharpe of the trade rather than of the statistic.

        **Never use this for the variance term.** `trial_variance` wants the
        spread of Sharpes across everything the search tried, and orienting
        every trial by its own sign makes every one of them positive, shrinks
        that spread and inflates the deflated Sharpe - which is the defect the
        whole correction exists to prevent. `Sweep.sharpes` returns the
        unoriented ones for exactly that reason.
        """
        got = self.hardest
        side = got.side if got is not None else 1
        return self.sharpe * (side if side != 0 else 1)

    @property
    def informative(self) -> list[ArmResult]:
        """The arms that could judge this statistic at all."""
        return [a for a in self.arms if not a.uninformative]

    @property
    def hardest(self) -> ArmResult | None:
        """The arm with the **least** evidence - the one that decides.

        Not the mean of the arms and not the kindest: a result is only as
        established as its strongest control, and averaging over arms lets a
        weak one carry a finding.

        Ranked by `evidence` rather than by percentile, because the test is
        two-sided: an arm the observed value sits below every draw of is as
        informative as one it sits above, and ranking by percentile alone
        would make the first of those look like the weakest arm when it is the
        strongest.

        Uninformative arms are excluded rather than counted hardest: an arm
        that did not move the statistic leaves the observed value at
        percentile zero, so the arm that tested nothing would decide
        everything.
        """
        useful = self.informative
        return min(useful, key=lambda a: a.evidence) if useful else None

    @property
    def survives(self) -> bool:
        """Does it clear its **hardest** informative arm, on one side?

        False when every arm was uninformative, which is not a pass: it means
        no arm could judge this statistic, and the pairing has to be fixed
        before the number means anything.

        **And false when the arms disagree about the side.** A candidate above
        one arm's null and below another's has not found an effect - it has
        found that two arms remove different amounts of the same mechanical
        thing, which is a statement about the arms. The agreement costs nothing
        when there is a real effect and is the cheapest way to catch an arm
        that is matched on the wrong property.
        """
        got = self.hardest
        if not (self.scored and got is not None and got.passes):
            return False
        sides = {a.side for a in self.informative if a.evidence > 0.0}
        return len(sides) <= 1

    def line(self) -> str:
        if self.refused:
            return f"{self.candidate.label}: refused - {self.refused}"
        arms = "; ".join(a.line() for a in self.arms)
        return (
            f"{self.candidate.label} [{self.candidate.question}]: lift {self.observed:+.4f} "
            f"over {self.events} events, sharpe {self.sharpe:+.3f} - {arms}"
        )


# ────────────────────────────── the measurement ──────────────────────────────


def outcomes(
    candles: Sequence[Candle], *, horizon: int = HORIZON, span: int = SPAN, signed: bool = False
) -> list[float]:
    """Forward move over `horizon` bars in trailing-sd units, per bar.

    `nan` where the window runs off the end or the trailing estimate is not
    yet positive, so a caller cannot silently score a bar whose outcome does
    not exist.

    Divided by `sqrt(horizon)` as well as by the trailing standard deviation,
    so the same number means the same thing at two horizons - a four-bar move
    is twice a one-bar move under the null, and a statistic that did not
    divide it out would rank horizons rather than candidates.
    """
    closes = [c[3] for c in candles]
    scale = trailing(closes, span)
    root = math.sqrt(max(int(horizon), 1))
    out: list[float] = []
    for t in range(len(closes)):
        ahead = t + int(horizon)
        if ahead >= len(closes) or scale[t] <= 0.0:
            out.append(math.nan)
            continue
        move = closes[ahead] - closes[t]
        out.append((move if signed else abs(move)) / (scale[t] * root))
    return out


def strata(candles: Sequence[Candle], *, span: int = SPAN, bands: int = BANDS) -> list[int]:
    """Which volatility band each bar sits in, by rank over the sample.

    Ranked rather than cut at fixed levels, so the bands hold equal counts on
    a feed whose volatility distribution nobody measured - which is every
    feed a sweep has not seen before.
    """
    closes = [c[3] for c in candles]
    scale = trailing(closes, span)
    usable = [i for i, v in enumerate(scale) if v > 0.0]
    out = [-1] * len(closes)
    if not usable:
        return out
    order = sorted(usable, key=lambda i: scale[i])
    size = max(1, len(order) // max(1, int(bands)))
    for rank, i in enumerate(order):
        out[i] = min(int(bands) - 1, rank // size)
    return out


def events_from(reading: Sequence[float], threshold: float, *, separation: int) -> list[int]:
    """Bars whose reading is at or above `threshold`, de-overlapped.

    De-overlapping is not tidying. `overlapping-windows-inflate-permutation-
    nulls` records a level finding at p 0.015 that was anchor overlap, and the
    tell was the no-level control passing; `overlapping-outcome-windows-leak`
    records a direction AUC of 0.79 collapsing to 0.51. Two events closer than
    the forward window share most of their outcome, so counting both inflates
    the event count without adding information and shrinks every permutation
    null's spread.
    """
    keep: list[int] = []
    for t, value in enumerate(reading):
        if value is None or math.isnan(float(value)) or float(value) < threshold:
            continue
        if keep and t - keep[-1] < max(1, int(separation)):
            continue
        keep.append(t)
    return keep


def lift(
    values: Sequence[float], events: Sequence[int], bands: Sequence[int]
) -> tuple[float, list[float]]:
    """Within-strata lift, and the per-event series it is the mean of.

    Each event is compared to the mean of the **non-events in its own
    volatility band**, which is what makes this a lift rather than a level.
    Pooled, a detector that fires in volatile periods scores for that reason
    alone: 0.805 against 0.525 within strata on a constant-volatility process.

    Non-events rather than all bars, because including the events in their own
    reference attenuates the contrast by the event share - small, but it moves
    in the direction that flatters.
    """
    chosen = {int(t) for t in events}
    reference: dict[int, float] = {}
    pools: dict[int, list[float]] = {}
    for t, value in enumerate(values):
        if t in chosen or math.isnan(value) or t >= len(bands) or bands[t] < 0:
            continue
        pools.setdefault(bands[t], []).append(value)
    for band, pool in pools.items():
        if pool:
            reference[band] = statistics.fmean(pool)

    out: list[float] = []
    for t in sorted(chosen):
        if t >= len(values) or math.isnan(values[t]) or t >= len(bands):
            continue
        band = bands[t]
        if band < 0 or band not in reference:
            continue
        out.append(values[t] - reference[band])
    return (statistics.fmean(out) if out else math.nan), out


def statistic(
    candles: Sequence[Candle],
    events: Sequence[int],
    *,
    horizon: int = HORIZON,
    span: int = SPAN,
    bands: int = BANDS,
    signed: bool = False,
) -> tuple[float, list[float]]:
    """The within-strata lift of these events on these candles."""
    values = outcomes(candles, horizon=horizon, span=span, signed=signed)
    return lift(values, events, strata(candles, span=span, bands=bands))


# ───────────────────────────────── the arms ─────────────────────────────────


def walk_with_bar_geometry(candles: Sequence[Candle], rng: Random) -> list[Candle]:
    """A walk whose bars look like these ones. The **series** arm.

    Closes follow a walk resampled from this series' own increments; each
    bar's shape - its range, and where the open and close sit inside it - is
    resampled from the real bars. So the null has this market's wickiness and
    none of its path structure, and running the same reader over it says what
    the reader produces from bar geometry alone.

    **A generated process will not do.** Markets have fewer imbalances,
    wickier bars, kurtosis 47 to 74 and size autocorrelation 0.21, and no
    simple family measured here is closer than 210; Deriv synthetics read
    kurtosis 3.19 against 20.07 traded, so a synthetic-only arm judges a
    kurtosis-20 candidate against a kurtosis-3 reference.

    Deliberately the same construction as
    `node.surrogates.walk_with_bar_geometry`, whose signature differs only in
    taking `rng` as a keyword. `tests/test_statespace_searching.py` asserts
    that the node's function can be used as this arm unchanged, so the node
    layer's implementation is the one a real sweep should pass in.
    """
    if len(candles) < 2:
        return list(candles)
    steps = [candles[i][3] - candles[i - 1][3] for i in range(1, len(candles))]
    spans = [max(c[1] - c[2], 0.0) for c in candles]
    shapes: list[tuple[float, float]] = []
    for open_, high, low, close in candles:
        reach = high - low
        shapes.append((0.5, 0.5) if reach <= 0 else ((open_ - low) / reach, (close - low) / reach))

    out: list[Candle] = []
    price = candles[0][3]
    for _ in candles:
        price += rng.choice(steps)
        reach = rng.choice(spans)
        open_at, close_at = rng.choice(shapes)
        low = price - close_at * reach
        out.append((low + open_at * reach, low + reach, low, price))
    return out


def block_shuffled_candles(candles: Sequence[Candle], rng: Random) -> list[Candle]:
    """The same bar shapes on a block-reordered close path. A **series** arm.

    `nulls.block_shuffled` reorders the increments in blocks, which keeps the
    clustering inside a block and the tails exactly - EURUSD's return kurtosis
    reads 18.11 before and after - and destroys the ordering between blocks.
    The bar shapes are then re-hung on the new path in their original order,
    so this arm removes *when* and keeps *what*.
    """
    closes = [c[3] for c in candles]
    blocks = max(1, len(closes) // 24)
    order = list(range(len(closes) // max(1, blocks) + 1))
    rng.shuffle(order)
    moved = block_shuffled(closes, order, blocks=blocks)
    out: list[Candle] = []
    for i, price in enumerate(moved[: len(candles)]):
        open_, high, low, close = candles[i]
        reach = max(high - low, 0.0)
        at = 0.5 if reach <= 0 else (close - low) / reach
        base = price - at * reach
        open_at = 0.5 if reach <= 0 else (open_ - low) / reach
        out.append((base + open_at * reach, base + reach, base, price))
    return out


def rotated_candles(candles: Sequence[Candle], rng: Random) -> list[Candle]:
    """The same series at an offset. A **series** arm that removes alignment.

    Every marginal is kept *exactly* - it is the same data - and only the
    correspondence between a bar's position and the rest of the series goes.
    Preferred to a shuffle wherever the series' own time structure is what is
    under test, because a shuffle scores a volatility claim against a
    volatility-free reference and is significant by construction.
    """
    closes = [c[3] for c in candles]
    shift = rng.randrange(1, max(2, len(closes) - 1))
    moved = rotated(closes, shift)
    out: list[Candle] = []
    for i, price in enumerate(moved[: len(candles)]):
        open_, high, low, close = candles[i]
        reach = max(high - low, 0.0)
        at = 0.5 if reach <= 0 else (close - low) / reach
        base = price - at * reach
        open_at = 0.5 if reach <= 0 else (open_ - low) / reach
        out.append((base + open_at * reach, base + reach, base, price))
    return out


def placebo_anchors(length: int, events: Sequence[int], rng: Random) -> list[int]:
    """As many anchors as the detector found, placed at random. **Anchors.**

    The data is untouched and only the identification moves, which is the null
    a geometric claim actually needs: sign flips and shuffles remove the thing
    a geometric claim is about, so they fail it by construction. This is also
    the arm that did the work here - the displacement origin's 82% return rate
    was matched by a placebo on every class, and a walk reads 0.825.
    """
    if length <= 0 or not events:
        return []
    return sorted(rng.randrange(0, length) for _ in events)


def distance_matched(length: int, events: Sequence[int], rng: Random) -> list[int]:
    """Random anchors whose **spacing** matches the real ones. **Anchors.**

    The stronger form of the placebo above. A detector that fires in clusters
    has a different event spacing from a uniform draw, and spacing changes how
    much of the outcome two events share - so an unmatched placebo can lose for
    a reason that has nothing to do with the shape. `a-return-rate-is-geometry`
    is why distance has to be matched rather than merely random.
    """
    if length <= 0 or len(events) < 2:
        return placebo_anchors(length, events, rng)
    gaps = [int(events[i]) - int(events[i - 1]) for i in range(1, len(events))]
    rng.shuffle(gaps)
    total = sum(gaps)
    if total >= length:
        return placebo_anchors(length, events, rng)
    at = rng.randrange(0, length - total)
    out = [at]
    for gap in gaps:
        at += gap
        out.append(at)
    return out


def arms(*, series: Callable[..., object] | None = None) -> tuple[Arm, ...]:
    """The default battery, each arm labelled with what it removes.

    `series` replaces the bar-geometry walk, so a caller that has
    `node.surrogates.walk_with_bar_geometry` can pass it and run the node
    layer's implementation rather than this module's.

    Four arms and not one, because they remove different things and a result
    is only as established as its strongest control. The pairing matters as
    much as the count: the two anchor arms can judge a statistic that depends
    on *which* bars were chosen, and the two series arms can judge one that
    depends on the path - handing either the wrong statistic produces an
    uninformative arm, which `ArmResult.uninformative` reports rather than
    scoring as a pass.
    """
    walk = series or walk_with_bar_geometry
    return (
        Arm(
            name="walk through the same reader (same bar geometry)",
            removes="the path structure, keeping each bar's range and wick proportions",
            kind=SERIES,
            make=walk,
        ),
        Arm(
            name="block-reordered closes (same bar shapes)",
            removes="the ordering between blocks, keeping within-block clustering and the tails",
            kind=SERIES,
            make=block_shuffled_candles,
        ),
        Arm(
            name="placebo anchors (count matched)",
            removes="the reader's choice of bar, keeping the data exactly",
            kind=ANCHORS,
            make=placebo_anchors,
        ),
        Arm(
            name="distance-matched placebo (spacing matched)",
            removes="the reader's choice of bar, keeping the data and the event spacing",
            kind=ANCHORS,
            make=distance_matched,
        ),
    )


# ──────────────────────────────── the scoring ────────────────────────────────


def score(
    candidate: Candidate,
    candles: Sequence[Candle],
    battery: Sequence[Arm],
    *,
    horizon: int = HORIZON,
    separation: int = 0,
    span: int = SPAN,
    bands: int = BANDS,
    draws: int = DRAWS,
    seed: int = 0,
    least_events: int = LEAST_EVENTS,
) -> Trial:
    """One candidate against every arm, or a `Trial` saying why not.

    `separation` defaults to `horizon`, which is the only safe default: two
    events closer than the forward window share most of their outcome.
    Passing a smaller one raises rather than warning, because the failure it
    produces is a p-value that looks good.
    """
    if not battery:
        raise ValueError(
            f"{candidate.label} was given no arms. Six artefacts on this desk passed "
            f"DSR, PBO and SPA; what exposed them was rerunning on surrogates - so a "
            f"candidate scored without arms is a number with no comparison behind it."
        )
    if candidate.lookahead:
        raise ValueError(
            f"{candidate.label} declares itself lookahead: its reading at bar t needs "
            f"bars after t. `drawing.gaps` emitted only *unfilled* gaps and read +0.50R "
            f"a trade as a bias. Score a shape from the bar its definition completed on."
        )
    gap = int(separation) if separation else int(horizon)
    if gap < horizon:
        raise ValueError(
            f"separation {gap} is shorter than the {horizon}-bar forward window. "
            f"Overlapping outcome windows leak: a short skip rule with a long forward "
            f"window gave direction AUC 0.79 that collapsed to 0.51 de-overlapped."
        )

    reading = candidate.reader(candles)
    found = events_from(reading, candidate.threshold, separation=gap)
    signed = candidate.question == "direction"
    if len(found) < least_events:
        return Trial(
            candidate=candidate,
            observed=math.nan,
            events=len(found),
            refused=f"too few events: {len(found)} below {least_events}",
        )

    observed, series = statistic(
        candles, found, horizon=horizon, span=span, bands=bands, signed=signed
    )
    if math.isnan(observed):
        return Trial(
            candidate=candidate, observed=math.nan, events=len(found), refused="no outcome"
        )
    if len(series) < least_events:
        # **Counted after the strata, not before.** `lift` drops an event with
        # no outcome and one whose volatility band holds no non-event to
        # compare it with, so a candidate can clear the gate on 30 events and
        # be scored on three - and `node.metrics.moments` refuses fewer than
        # four returns outright, because a series that short has no skew or
        # kurtosis worth the name and therefore no PSR.
        return Trial(
            candidate=candidate,
            observed=observed,
            events=len(found),
            refused=f"too few events within strata: {len(series)} of {len(found)}",
        )
    degenerate = _degenerate(candles, series, horizon=horizon, span=span, signed=signed)
    if degenerate:
        return Trial(candidate=candidate, observed=observed, events=len(found), refused=degenerate)

    results: list[ArmResult] = []
    for index, arm in enumerate(battery):
        values: list[float] = []
        for draw in range(draws):
            rng = Random(seed * 1_000_003 + index * 7_919 + draw)
            try:
                got = _draw(arm, candidate, candles, found, rng, gap, horizon, span, bands, signed)
            except (ValueError, ZeroDivisionError, IndexError):
                continue
            if got is not None and not math.isnan(got):
                values.append(got)
        results.append(
            ArmResult(name=arm.name, removes=arm.removes, observed=observed, draws=tuple(values))
        )
    return Trial(
        candidate=candidate,
        observed=observed,
        events=len(found),
        arms=tuple(results),
        returns=tuple(series),
        at=tuple(found),
        span=len(candles),
    )


#: How far below the sample's own outcome spread a trial's per-event spread
#: may fall before the trial is refused. 0.10 is a tenfold collapse, which is
#: not a strong effect - it is a selection on something mechanical.
DEGENERATE = 0.10


def _degenerate(
    candles: Sequence[Candle],
    series: Sequence[float],
    *,
    horizon: int,
    span: int,
    signed: bool,
) -> str:
    """Why this trial's per-event outcomes cannot carry a Sharpe, or "".

    **Found rather than anticipated**, and worth the detail. `engulfing_up` on
    4,000 bars of btc 1h scored a lift of -0.5403 over 41 events at a Sharpe
    of **-18.40**, where every other trial on the panel sat between -0.14 and
    +0.23. The cause was not a short series: all 41 events were scored, and
    their outcomes ran 0.006 to 0.096 where the sample's own standard
    deviation is 0.82.

    The event indices were 4, 28, 52, 76, 202, 274 - **multiples of 24** - so
    the reader was firing at one hour of the day, and the median four-bar move
    after those bars is 4.98 against 44.75 over the sample. That is a defect
    in the stored feed at a daily boundary, not a market reading, and the
    harness had no way to say so: it produced a number, and the number went
    into `node.metrics.trial_variance`, whose job is the spread of the trial
    Sharpes, where one value of -18.40 inflates `expected_max_sharpe` enough
    to put the deflated Sharpe out of reach for every other candidate.

    So the guard is on the **property**: a per-event spread an order of
    magnitude below the sample's is a selection on something mechanical, and
    `node.metrics.moments` refuses a constant return series on the same
    grounds. The hour-of-day stratum is the control this wants next - a pair
    of bars suppresses two-bar statistics by 0.046 to 0.072 and half of that
    is the daily cycle.
    """
    if len(series) < 2:
        return "a single outcome has no spread"
    spread = statistics.pstdev(series)
    whole = [
        v for v in outcomes(candles, horizon=horizon, span=span, signed=signed) if not math.isnan(v)
    ]
    if len(whole) < 2:
        return ""
    reference = statistics.pstdev(whole)
    if reference <= 0.0 or spread >= DEGENERATE * reference:
        return ""
    return (
        f"degenerate outcome spread: {spread:.4g} against the sample's {reference:.4g}. "
        f"A tenfold collapse is a selection on something mechanical - check the event "
        f"spacing for a calendar period before reading the lift."
    )


def _draw(
    arm: Arm,
    candidate: Candidate,
    candles: Sequence[Candle],
    found: Sequence[int],
    rng: Random,
    gap: int,
    horizon: int,
    span: int,
    bands: int,
    signed: bool,
) -> float | None:
    """This arm's statistic on one draw, or None where the draw is empty."""
    if arm.kind == SERIES:
        null = arm.make(candles, rng)  # type: ignore[call-arg]
        reading = candidate.reader(null)  # type: ignore[arg-type]
        events = events_from(reading, candidate.threshold, separation=gap)
        if not events:
            return None
        got, _ = statistic(
            null,  # type: ignore[arg-type]
            events,
            horizon=horizon,
            span=span,
            bands=bands,
            signed=signed,
        )
        return got
    chosen = set(arm.make(len(candles), found, rng))  # type: ignore[call-arg, arg-type]
    marks = [1.0 if i in chosen else math.nan for i in range(len(candles))]
    # De-overlapped again after the move, because a random placement can put
    # two anchors inside one forward window and the real candidate's events
    # were de-overlapped - a null scored on overlapping windows is a null whose
    # spread is too narrow, which is the same error as scoring the real
    # candidate on them.
    #
    # The effect runs the **conservative** way and is worth stating: dropping
    # duplicates and near neighbours leaves the null with slightly fewer events
    # than the real candidate had, so its mean is slightly noisier and its
    # distribution slightly wider, which makes the arm harder to beat rather
    # than easier.
    placed = events_from(marks, 1.0, separation=gap)
    if not placed:
        return None
    got, _ = statistic(candles, placed, horizon=horizon, span=span, bands=bands, signed=signed)
    return got


# ───────────────────────────────── the sweep ─────────────────────────────────


@dataclass(slots=True)
class Sweep:
    """Every trial a search tried, and whether its own harness can be trusted.

    Two pools, and the second is the one that decides whether to read the
    first. `the-placebo-arm-selects-the-null` is measured: a block of 8 found
    structure in 27 of 36 **placebo** pools, so a run whose placebo pool
    scores has a broken null and its survivors mean nothing. `blocked()` says
    so, and `verdict()` refuses to report survivors while it does.
    """

    trials: list[Trial] = field(default_factory=list)
    #: The same candidates on series where no effect exists by construction.
    placebo: list[Trial] = field(default_factory=list)

    @property
    def attempted(self) -> int:
        """Everything tried, refusals included. The multiplicity count."""
        return len(self.trials)

    def sharpes(self) -> tuple[float, ...]:
        """Every scored trial's Sharpe, winners and losers.

        **The input that is usually faked.** `node.metrics.trial_variance` is
        the spread of Sharpes across everything tried, so it only exists if
        the search kept its losers - a node that reports its best candidate
        and discards the rest cannot compute a deflated Sharpe, and a guessed
        variance makes the whole number decorative.

        **Unoriented**, which matters under a two-sided test: see
        `Trial.claimed_sharpe` for the one place the sign should be applied,
        and why applying it here would inflate the very number it feeds.
        """
        return tuple(t.sharpe for t in self.trials if t.scored)

    def survivors(self) -> list[Trial]:
        return [t for t in self.trials if t.survives]

    def placebo_survivors(self) -> list[Trial]:
        return [t for t in self.placebo if t.survives]

    def blocked(self) -> str:
        """Why this run cannot be read, or an empty string.

        Non-empty when the placebo pool scored at all. Not a ratio and not a
        threshold: a pool built so that nothing is there has no business
        producing a survivor, and one that does says the arms are too weak
        for this statistic rather than that the finding is marginal.

        **An empty placebo pool blocks the run too**, and that is the point of
        putting it here rather than in a caller's checklist. A guard with
        nothing to check reads as a pass, which is the vacuous-guard shape this
        repository has walked into three times in one day - and it is the
        cheapest of the three failures to make loud.
        """
        if not self.placebo:
            return (
                "no placebo pool: a guard with nothing to check reads as a pass. Carry "
                "series on which nothing is there by construction through the same code "
                "path - two Deriv volatility indices caught two leaks in one run here"
            )
        bad = self.placebo_survivors()
        if not bad:
            return ""
        return (
            f"{len(bad)} of {len(self.placebo)} placebo trials survived their own arms "
            f"({', '.join(t.candidate.label for t in bad[:4])}) - the harness found "
            f"structure where none was planted, so nothing in the real pool can be read"
        )

    def effective_trials(self) -> float:
        """Trials discounted by how much the candidates overlap.

        **Shape families overlap each other, so their trials are not
        independent and multiplicity cannot be counted as though they were.**
        An engulfing bar is the *opposite shape* to a displacement origin, and
        the best vs-walk z over 516 rows was +1.95. Counting 100 overlapping
        candidates as 100 trials overstates the correction; counting them as
        one understates it.

        `n / (1 + (n - 1) * rho)` with `rho` the mean pairwise correlation of
        the trials' per-event series over their shared events. The usual
        design-effect form: at `rho = 0` it is `n`, at `rho = 1` it is 1.
        """
        scored = [t for t in self.trials if t.scored and t.span > 0 and len(t.at) > 2]
        n = len(scored)
        if n < 2:
            return float(n)
        pairs: list[float] = []
        for i in range(n):
            for j in range(i + 1, n):
                got = _overlap(scored[i], scored[j])
                if got is not None:
                    pairs.append(got)
        rho = max(0.0, statistics.fmean(pairs)) if pairs else 0.0
        return n / (1.0 + (n - 1) * rho)

    def asked(self) -> dict[str, int]:
        """How many trials each question got, so a reader can see what was
        spent on the one already closed."""
        out: dict[str, int] = {}
        for t in self.trials:
            out[t.candidate.question] = out.get(t.candidate.question, 0) + 1
        return out

    def verdict(self) -> str:
        """What this run found, in words, with the arms that decided it."""
        stop = self.blocked()
        if stop:
            return f"unreadable: {stop}"
        kept = self.survivors()
        head = (
            f"{self.attempted} trials, {len(self.sharpes())} scored, "
            f"{self.effective_trials():.1f} effective, asked {self.asked()}"
        )
        if not kept:
            hard = [t for t in self.trials if t.scored and t.hardest is not None]
            if not hard:
                return f"{head}: nothing scored against an informative arm"
            best = max(hard, key=lambda t: t.hardest.evidence)  # type: ignore[union-attr]
            return (
                f"{head}: nothing survived. The closest was {best.candidate.label} "
                f"{best.hardest.tail} its null at percentile "  # type: ignore[union-attr]
                f"{best.hardest.percentile:.3f} against "  # type: ignore[union-attr]
                f"{best.hardest.name}"  # type: ignore[union-attr]
            )
        return f"{head}: {len(kept)} survived - " + "; ".join(t.line() for t in kept)


def _overlap(left: Trial, right: Trial) -> float | None:
    """How much two trials are the same trial, from their event sets.

    The phi coefficient of the two 0/1 event indicators over the series - an
    ordinary correlation on binary vectors, which is 1.0 for two candidates
    firing on identical bars and about zero for two that fire independently.

    **Taken from the indices and not from the outcome series.** The first
    version correlated the two per-event series positionally, which is only
    meaningful where the events coincide: two candidates sharing half their
    events give a number that depends on how the two sorted lists happen to
    line up. The indices are exact, and the overlap is what
    `effective_trials` needs - `efficiency` and `trend` in the detector panel
    are the *same class* under two names and read identical lifts, so a
    measure that could not see that would count them as two trials.
    """
    if left.span != right.span or left.span < 3:
        return None
    here, there = set(left.at), set(right.at)
    n = left.span
    both = len(here & there)
    # phi = (n*both - |a||b|) / sqrt(|a|(n-|a|)|b|(n-|b|))
    size_a, size_b = len(here), len(there)
    if size_a in (0, n) or size_b in (0, n):
        return None
    top = n * both - size_a * size_b
    bottom = math.sqrt(size_a * (n - size_a) * size_b * (n - size_b))
    return abs(top / bottom) if bottom > 0 else None


def run(
    candidates: Sequence[Candidate],
    candles: Sequence[Candle],
    battery: Sequence[Arm],
    **kwargs: object,
) -> list[Trial]:
    """Score every candidate on one series, refusals kept as trials."""
    return [score(c, candles, battery, **kwargs) for c in candidates]  # type: ignore[arg-type]


def sweep(
    candidates: Sequence[Candidate],
    candles: Sequence[Candle],
    battery: Sequence[Arm],
    *,
    placebo: Sequence[Sequence[Candle]] = (),
    **kwargs: object,
) -> Sweep:
    """The real pool and the placebo pool, scored by the same code path.

    `placebo` is series on which no effect exists by construction. **Not
    optional in practice**: `carry-an-independent-placebo-pair` records two
    Deriv volatility indices catching two leaks in one run, and an empty
    placebo pool makes `blocked()` vacuously quiet - the shape of a guard that
    permits everything while reading as though it checks.
    """
    got = Sweep(trials=run(candidates, candles, battery, **kwargs))
    for series in placebo:
        got.placebo.extend(run(candidates, series, battery, **kwargs))
    return got


# ─────────────────────── thresholds, power and strata ───────────────────────


@dataclass(frozen=True, slots=True)
class Row:
    """One threshold's reading. **No z, deliberately.**

    `sweep-thresholds-on-the-mean-not-z` is the finding: a z grid faked a
    ridge at the chosen threshold where the mean grid was monotone. A z falls
    as the event count falls, so a grid of z's has a maximum wherever the
    count stops paying for the mean - which looks like a discovered threshold
    and is arithmetic.
    """

    threshold: float
    events: int
    mean: float


def thresholds(
    candidate: Candidate,
    candles: Sequence[Candle],
    grid: Sequence[float],
    *,
    horizon: int = HORIZON,
    span: int = SPAN,
    bands: int = BANDS,
) -> list[Row]:
    """The within-strata mean at each threshold, and the count behind it."""
    reading = candidate.reader(candles)
    signed = candidate.question == "direction"
    out: list[Row] = []
    for level in grid:
        found = events_from(reading, level, separation=horizon)
        if not found:
            out.append(Row(threshold=float(level), events=0, mean=math.nan))
            continue
        got, _ = statistic(candles, found, horizon=horizon, span=span, bands=bands, signed=signed)
        out.append(Row(threshold=float(level), events=len(found), mean=got))
    return out


def monotone(rows: Sequence[Row]) -> bool:
    """Does the mean rise with the threshold, allowing ties?

    The reading that tells a real relationship from a ridge: a detector whose
    higher readings really do precede larger moves gives a monotone mean grid,
    and one whose best threshold is the one with the fewest events does not.
    """
    seen = [r.mean for r in rows if r.events > 0 and not math.isnan(r.mean)]
    return all(b >= a - 1e-12 for a, b in pairwise(seen))


@dataclass(frozen=True, slots=True)
class Power:
    """One planted strength, and whether the harness saw it."""

    strength: float
    observed: float
    percentile: float
    found: bool


def power(
    candidate: Candidate,
    candles: Sequence[Candle],
    battery: Sequence[Arm],
    strengths: Sequence[float],
    *,
    horizon: int = HORIZON,
    separation: int = 0,
    span: int = SPAN,
    bands: int = BANDS,
    draws: int = 60,
    seed: int = 0,
) -> list[Power]:
    """Plant an effect at the reader's own events and sweep its strength.

    **Report where the test goes blind, before reporting a null.** A null from
    a test with no power is not a finding, and the only way to know which one
    was produced is to plant the effect and watch it appear.

    The planting inflates the forward move at each real event by `strength`
    trailing standard deviations. The arms are rebuilt on the planted series,
    so a series arm sees the plant at *different* events and gains nothing
    from it, which is the property that makes this a power curve rather than a
    tautology.

    **The plant goes out and comes back**, and that matters more than it
    looks. A plant that only added the move left a permanent level shift at
    every event, so a sweep with 56 events at 4 sigma produced 224 sigmas of
    drift and the curve measured whether the test can see a trend. A bump that
    returns over the following `horizon` bars leaves the series' long-run
    character alone and inflates only the forward move the statistic reads.
    """
    gap = int(separation) if separation else int(horizon)
    reading = candidate.reader(candles)
    found = events_from(reading, candidate.threshold, separation=gap)
    out: list[Power] = []
    for strength in strengths:
        planted = _plant(candles, found, float(strength), horizon=horizon, span=span)
        trial = score(
            candidate,
            planted,
            battery,
            horizon=horizon,
            separation=gap,
            span=span,
            bands=bands,
            draws=draws,
            seed=seed,
            least_events=1,
        )
        hard = trial.hardest
        out.append(
            Power(
                strength=float(strength),
                observed=trial.observed,
                percentile=hard.percentile if hard is not None else math.nan,
                found=trial.survives,
            )
        )
    return out


def _plant(
    candles: Sequence[Candle],
    events: Sequence[int],
    strength: float,
    *,
    horizon: int,
    span: int,
) -> list[Candle]:
    """Inflate the move over the `horizon` bars after each event, then undo it.

    The whole bar is shifted by the planted amount so the close path carries
    it and the bar shapes do not change - a plant that widened the ranges
    would be detectable by a range reader and the curve would measure that
    instead.

    The bump rises over `horizon` bars and decays over the next `horizon`, so
    the cumulative shift returns to zero and the series gains no drift. See
    `power` for what the drifting version cost.
    """
    closes = [c[3] for c in candles]
    scale = trailing(closes, span)
    reach = max(1, int(horizon))
    adds: dict[int, float] = {}
    for t in events:
        unit = scale[t] if t < len(scale) else 0.0
        if unit <= 0.0:
            continue
        per = strength * unit / reach
        for k in range(t + 1, min(t + 1 + reach, len(candles))):
            adds[k] = adds.get(k, 0.0) + per
        for k in range(t + 1 + reach, min(t + 1 + 2 * reach, len(candles))):
            adds[k] = adds.get(k, 0.0) - per
    shift = [0.0] * len(candles)
    running = 0.0
    for i in range(len(candles)):
        running += adds.get(i, 0.0)
        shift[i] = running
    return [
        (c[0] + shift[i], c[1] + shift[i], c[2] + shift[i], c[3] + shift[i])
        for i, c in enumerate(candles)
    ]
