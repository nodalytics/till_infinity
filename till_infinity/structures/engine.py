"""The level engine: bars in, levels and directional calls out.

Ties the pieces together. Bars arrive from the bus; the engine keeps a rolling
window per instrument, re-forms levels from the perceptually important points
in it, tracks price against those levels, and produces a call whenever price
comes into one.

Two things it is careful about, because both are easy to get wrong in ways that
do not show up until the results are being trusted:

**Levels are formed only from confirmed swings.** A turning point is not
knowable as one until the bars after it have printed, so `pips.as_of` filters
to what was visible. Without that the engine would draw levels through swings
nobody could have seen and then congratulate itself for respecting them.

**Levels persist across re-forming.** Re-deriving from a window would discard
the touch history that makes a level worth anything, so new candidates are
merged into the existing set rather than replacing it. A level rediscovered is
evidence about an old level, not a new one.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics
import time
from collections import deque
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from ..logging import get_logger
from ..shared import effects
from . import breaks as bk
from . import cycles as cy
from . import levels as lv
from . import reactions
from . import spreadquotes as sq
from . import zma as zm
from .config import DEFAULT_FORMATION
from .context import sessions
from .context.character import Character
from .drawing import (
    confluence,
    equals,
    gaps,
    origin_points,
    origins,
    pips,
    pivots,
    profile,
    rounds,
    runs,
    sweeps,
    vwap,
)
from .learning import focus, patterns, regimes
from .learning.focus import Focus
from .models import Shape, Signal
from .state import Restorable
from .vol import projection as pj
from .vol.volatility import Book as VolBook
from .vol.volatility import Volatility

# Declared at import, where the flag is read, so a feature that is on and never
# reached still has a record. Declaring at the call site would make an unreached
# feature an undeclared one, which is exactly the blind spot.
effects.declare("structures.projection", enabled=pj.ENABLED)


@dataclass(frozen=True, slots=True)
class _OriginBar(Restorable):
    """The four prices `origins.zone_of` reads, and nothing else.

    Restorable although it is never persisted - it lives for one call and is
    discarded. The walk that enforces that invariant does not know the
    difference, and satisfying a guard that exists for a real reason is
    cheaper than teaching it about exceptions.
    """

    open: float
    high: float
    low: float
    close: float


log = get_logger(__name__)

#: Sigmas of wick spread a stop has to clear beyond the level's own average.
#:
#: One would be roughly the depth 84% of sweeps stay inside if the depths were
#: normal, which they are not - they are bounded below at zero with a long
#: right tail, so real coverage at one sigma is higher than that. Two produces
#: stops wide enough that the size the risk budget then allows is uninteresting
#: on the tighter instruments. This is the setting most worth measuring against
#: outcomes rather than reasoning about.
SWEEP_SIGMAS = 1.0


#: Bars kept per instrument, per timeframe.
#:
#: **Raised from 500 on 2026-09-10, and the reason is that 500 bars is a
#: different amount of history at every timeframe.** As a count it looks
#: uniform; as a duration it is not:
#:
#: | interval | 500 bars | 1,000 bars |
#: | --- | --- | --- |
#: | 1m | 8.3 hours | 16.7 hours |
#: | 5m | 41 hours | 3.5 days |
#: | 1h | 20.8 days | 41.7 days |
#: | 4h | 83 days | 166 days |
#: | 1d | 500 days | 2.7 years |
#:
#: At the coarse end that is the binding constraint on what a swing strategy
#: can see: a 4h level from four months ago was outside the window, so the
#: levels drawn there came from a short memory whatever their timeframe
#: implied. At the fine end the constraint is different and sharper - see
#: `FINE_WINDOW`.
#:
#: **This costs memory and that has a history here.** Six deques per `Series`
#: at roughly 32 bytes an entry is about 94KB per series at 500, and the
#: container was OOM-killed nineteen times in nine days for reasons of exactly
#: this kind (`research/starving.md`). It is therefore settable from the
#: environment, so it can be tuned or reverted without a deploy - which is the
#: property the previous incident most wanted and did not have.
#:
#: **1,000 is a floor set by the box, not by what is useful.** TradingView
#: serves 5,000 bars per timeframe on an ordinary plan, which is a fair
#: statement of how much history a chart is expected to carry. 5,000 here is
#: about 960KB a series and roughly 790MB across the book - more than the
#: container has spare beside a 195MB state file. If the instance grows, this
#: is the number to raise first, and the environment variable is why that does
#: not need a code change.
WINDOW = int(os.environ.get("STRUCTURES_WINDOW") or 1_000)

#: A feed silent for this long has its accumulated state dropped by
#: `Engine.forget`. Seven days rather than three, because the rule is measured
#: **per feed** across all its intervals - any live instrument's 1m series
#: updates continuously - so the only thing a long threshold protects is a feed
#: that genuinely stopped, and the only thing a short one risks is dropping an
#: instrument over a holiday weekend. The universe filter is what reclaims
#: quickly; this is the bound that holds when there is no universe to filter on.
FORGET_FEED_SECONDS = float(os.environ.get("STRUCTURES_FORGET_FEED") or 7 * 86_400)

#: Bars kept for the **fine** series, which is the one everything else is
#: refined against.
#:
#: `_capture_fine` needs the 1m series to still cover a coarse bar at the
#: moment that bar closes, so this is not a preference, it is arithmetic: a 4h
#: bar is 240 minutes and a 1d bar is 1,440. At 500 the daily could never be
#: refined and said so - `refinement_tally` reported 18.6% of refinable origins
#: with the whole daily contribution missing.
#:
#: 1,500 covers the day with room for the gaps a real feed leaves. A week is
#: 10,080 minutes and is not reachable this way; refining weekly origins needs
#: a different mechanism, not a bigger deque.
FINE_WINDOW = int(os.environ.get("STRUCTURES_FINE_WINDOW") or 1_500)


def window_for(interval: str) -> int:
    """How many bars to keep for this timeframe."""
    return FINE_WINDOW if interval == FINE_INTERVAL else WINDOW


#: Ceiling on `Engine._slowing`, which is an unbounded ratio. See `_slowing`.
SLOWING_CAP = 10.0


def _interval_log(interval: str) -> float:
    """Natural log of the timeframe's seconds, or 0.0 for one we do not know.

    See `structures-engine.md` in research/docs.
    """
    from .levels import SECONDS

    seconds = SECONDS.get((interval or "").strip().lower(), 0.0)
    return math.log(seconds) if seconds > 0 else 0.0


#: Perceptually important points pulled from the window. Roughly one per ten
#: bars: fewer and real swings are missed, more and noise becomes a level.
PIP_COUNT = 50

#: Re-form levels this often, in bars. Every bar would be wasted work - the
#: swings barely change - and never would let the set go stale.
REFORM_EVERY = 20

#: Bars after a shape completes before its outcome is counted. Long enough for
#: the move to develop, short enough that it is still attributable to the shape.
SHAPE_HORIZON = 12

#: The timeframes levels are built on. Defined in `confluence` and used here so
#: there is one list rather than two that drift - which they did: confluence
#: spanned 4h while the engine never built it, so combining across timeframes
#: was quietly looking for something that never existed.
LEVEL_INTERVALS: tuple[str, ...] = confluence.TIMEFRAMES

#: Venues that must report a bar before its consensus close is usable. Below
#: this the "median" is one venue's opinion wearing a median's clothes.
MIN_VENUES = 3

#: Quotes kept per instrument for the spread median.
SPREAD_WINDOW = 128

#: Bars read per (instrument, interval) when warming from the store. One window
#: is all the engine can hold; more would be read and immediately discarded.
SEED_BARS = WINDOW

#: The series `_remember_origins` refines against. The finest the engine
#: carries, because the refinement's whole value is resolution - and it is
#: named rather than inlined so the one place it is chosen is findable.
FINE_INTERVAL = "1m"

#: The timeframes the cross-timeframe change count reads.
#:
#: **Measured before it was published.** A change point calling on three or more
#: of these is followed by **+7.92v** a day out; one calling on a single
#: timeframe by **-1.24v**, at a matched realised move
#: (`research/agreeing.md`, 8 instruments). Those are not the same event at two
#: strengths - they point opposite ways, which is why the *count* is the
#: reading rather than "did anything fire".
#:
#: 4h is absent and the research asked for it: 24 days of one-minute bars is
#: 144 four-hour bars, fewer than a warmup. 30m stands in until there is data,
#: and adding 4h here without re-running that measurement would be publishing a
#: number nobody has checked.
CHANGE_INTERVALS = ("5m", "15m", "30m", "1h")

#: How much more evidence a *faster* timeframe must show, per e-fold of bar
#: count, before its change counts.
#:
#: **A threshold in nats is scale-free across instruments and not across
#: timeframes.** A 5m series gets 288 chances a day where a daily gets one, and
#: the running maximum of a likelihood ratio grows with the number of chances
#: it has had. Measured on 8 instruments at a fixed 3 nats, the fire rate runs
#: **16.96 a day on 5m against 0.20 on 4h** - an 83.7x spread - so the fast
#: rungs are permanently calling and the count built from them is not a count
#: of anything. Every rung has to be a comparable event or agreement measures
#: noise.
#:
#: `threshold(tf) = base + k * ln(slowest / tf)` fixes it. The theory gives
#: `k = 1` if the statistic's tail falls like `exp(-h)`; measured, a nat buys
#: about a third of a log-unit of firing rate, and **k = 3** is what flattens
#: the spread to 7.0x. k = 4 over-corrects, back to 9.8x. The same sweep on
#: step-shuffled series behaves identically, which says this is arithmetic
#: about bar counts rather than market structure. See `research/focusing.md`.
CHANGE_K = 3.0

#: How long a change call stands, in seconds.
#:
#: **One window for every timeframe, not each timeframe's own bar length.** The
#: first version of the measurement gave a 5m call five minutes to be agreed
#: with and the 60m call an hour, which made agreement an artefact of the
#: fastest clock rather than a fact about the market. An hour for all four is
#: what a person means by "these timeframes are saying the same thing".
CHANGE_WINDOW = 3600.0

#: An untouched level this far from price, in volatility units, is not going to
#: be tested soon and is only crowding the set. Touched levels are kept
#: regardless of distance - a level price has reacted at is worth remembering
#: precisely because price left it.
KEEP_VOL = 8.0

#: Resolutions held for a consumer that may not be draining them.
MAX_RESOLVED = 500

#: Bars of its own timeframe an instrument may go without printing before it is
#: treated as closed rather than quiet. Four, matching `GAP_FACTOR`, which makes
#: the same judgement about a touch that spans a closure: long enough that an
#: ordinary thin session still counts as trading, short enough that a weekend
#: does not. Quotes are no use for this - venues keep answering polls with
#: Friday's price all weekend, which is what let a shut market alert.
STALE_BARS = 4.0

#: The fewest price steps that must fit inside a level's zone before the pair
#: is modelled at all.
#:
#: A level is a band price is meant to **enter**, react inside, and leave. That
#: only means something if price can be *inside* it. When the venue's tick is a
#: large fraction of a typical move, price cannot enter - it jumps across - and
#: every crossing becomes a touch. Measured on the instance: `sol 3m` fits 2.5
#: ticks in a zone and `audusd 1m` fits 2.7, against `btc 5m`'s 170. It is not
#: a crypto problem; coarse pip quoting does the same thing a cheap coin does.
#:
#: Four, because `depth_vol` - how far into the zone price pushed - is a
#: feature, and a feature with two distinguishable values is not one. Four
#: steps is the least that gives it any resolution, and it is also where the
#: measurement separates: 2.5, 2.7, 2.7 and 3.5 on one side, 4.1 and up on the
#: other.
#:
#: Judged on the **floor** zone rather than the observed one, which is the
#: conservative direction and deliberate. Wicks widen a real zone as touches
#: accumulate, so an established level is roomier than this - but a *new* level
#: gets the floor, and the question here is whether to form one at all.
#:
#: It declines eight of fifteen sampled pairs, which is more than the observed
#: widths alone would suggest: sol at 1m, 3m and 5m, and audusd, nzdusd,
#: eurusd, usdcad and usdchf at 1m. sol keeps 15m and coarser. The FX ones were
#: assessed over a weekend, when those markets are shut and their measured
#: behaviour says nothing, so they want re-checking on a weekday - see todo.md.
#:
#: Erring toward declining is the right direction here even so. Losing a good
#: pair costs some alerts, visibly. Keeping a bad one poisons the sample: sol
#: alone was half of every outcome in the journal, which is what gates `fit`.
#:
#: Both ends of this are bad and only one is fixed by `GRID_ZONE_VOL`. That
#: bounds a zone from becoming absurdly *wide* on a coarse grid, which was
#: making everything a touch. What remains is a zone two or three ticks
#: *across*, which is the failure `MIN_ZONE_TICKS` was added for. There is no
#: width that works, so the pair is declined instead - the same shape as
#: `trading()`: refuse rather than produce something meaningless.
MIN_TICKS_PER_ZONE = 4.0

#: Ceiling per (instrument, interval), strongest kept. Without one a long
#: history accrues a level every few basis points, and at that density every
#: price is "at a level" and the model predicts nothing. Fifteen is roughly
#: what a person marks on one chart, which is the right order of magnitude -
#: the constraint is attention, not storage.
MAX_LEVELS = 15

#: How many points one formation needs in a cluster before it is a level.
#:
#: `levels.form` defaults to three and is right to: a cluster of observed turns
#: is three independent times price turned at one price, and two is not evidence
#: because any two points define a line.
#:
#: **`round` is not that kind of formation and the default made it inert.** Its
#: grid is a power of ten at least `rounds.STEP_VOL` = 5 volatility units wide,
#: halved, so the closest two round numbers it can ever emit are **2.5
#: volatility units apart** against a clustering tolerance of 1.0. Every round
#: point is therefore its own cluster of exactly one, and a minimum of three
#: dropped every one of them - at every instrument, at every volatility, for the
#: whole life of the setting. Measured 2026-09-11: 1 point drawn, 1 turn
#: surviving `as_of`, 0 levels formed, and the arithmetic says that is not a
#: sample but a proof.
#:
#: One is right for it because a round number is an **assertion, not a sample**.
#: Three observations of one price is evidence; asking a grid to assert the same
#: price three times is asking it to repeat itself. The density argument the
#: default protects against does not apply either: the grid is 2.5 units apart
#: by construction, which is sparser than anything the other passes produce.
FORMATION_MIN_SWINGS: dict[str, int] = {"round": 1}


def _widen_to_origin(low: float, high: float, origin: dict) -> tuple[float, float]:
    """Extend a level's zone to cover the origin it sits in.

    See `structures-engine.md` in research/docs.
    """
    if not origin or not origin.get("in_origin"):
        return low, high
    edge_low = origin.get("origin_low")
    edge_high = origin.get("origin_high")
    if not isinstance(edge_low, int | float) or not isinstance(edge_high, int | float):
        return low, high
    if not edge_low or not edge_high or edge_low > edge_high:
        return low, high
    return min(low, float(edge_low)), max(high, float(edge_high))


@dataclass(slots=True)
class Consensus(Restorable):
    """Median bar across venues, per instrument and interval.

    See `structures-engine.md` in research/docs.
    """

    #: Feeds carried by a single source, which need no agreement because there
    #: is none to be had.
    #:
    #: `MIN_VENUES` exists because a median of two is one venue's opinion
    #: wearing a median's clothes. That argument does not reach an instrument
    #: only one place quotes: a synthetic has no underlying, so the broker is
    #: not *a* source for it, it is the *only* source, and the price it gives
    #: is the instrument by definition.
    #:
    #: Without this the block was total and silent - nine synthetics quoted,
    #: were selected in the terminal, published onto the bus, and produced not
    #: one level between them, because a lone venue never reached three.
    single_source: frozenset[str] = frozenset()

    #: (feed, interval) -> ts -> venue -> (high, low, close)
    _bars: dict[tuple[str, str], dict[int, dict[str, tuple[float, float, float]]]] = field(
        default_factory=dict
    )

    def observe(
        self, feed: str, interval: str, venue: str, when: int, high: float, low: float, close: float
    ) -> tuple[float, float, float] | None:
        """Fold one venue's bar in. Returns the consensus once enough agree."""
        key = (feed, interval)
        bars = self._bars.setdefault(key, {})
        at = bars.setdefault(when, {})
        at[venue] = (high, low, close)
        # Only the bars still being filled are worth keeping.
        if len(bars) > 4:
            for stale in sorted(bars)[:-4]:
                del bars[stale]
        if len(at) < (1 if feed in self.single_source else MIN_VENUES):
            return None
        return (
            statistics.median([h for h, _, _ in at.values()]),
            statistics.median([low for _, low, _ in at.values()]),
            statistics.median([c for _, _, c in at.values()]),
        )


#: A venue that has not quoted for this long is no longer part of the picture.
#: Without it a venue that stops publishing holds its last mid in the median
#: for ever, and on a fast move the consensus lags behind every live venue.
QUOTE_STALE = 30.0


@dataclass(slots=True)
class Quotes(Restorable):
    """Median mid across venues, per instrument.

    See `structures-engine.md` in research/docs.
    """

    #: feed -> venue -> (when, mid)
    _mids: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)

    def observe(self, feed: str, venue: str, when: float, mid: float) -> float:
        """Fold one venue's quote in and answer with what the venues agree on."""
        seen = self._mids.setdefault(feed, {})
        seen[venue] = (when, mid)
        fresh = [value for last, value in seen.values() if when - last <= QUOTE_STALE]
        # One venue quoting is not a disagreement, and a median of nothing is an
        # error - either way its own mid is the best answer available.
        return statistics.median(fresh) if fresh else mid


@dataclass(slots=True)
class Series(Restorable):
    """A rolling window of one instrument at one interval."""

    feed: str
    interval: str
    times: deque[int] = field(default_factory=lambda: deque(maxlen=WINDOW))
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    highs: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    lows: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    #: Kept for `origins`, which needs a body to fall back on when a bar is
    #: mostly wick. Everything else here works from closes and extremes.
    opens: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    #: Bar time -> the lowest and highest **fine** close inside that bar, for
    #: the bars where they could be captured.
    #:
    #: **This exists because of when, not what.** The refinement that uses them
    #: was first attempted at origin *detection* time and refined one 4h origin
    #: in 924: an origin does not exist until its impulse breaks structure,
    #: hours to days after the turn on 4h, by which point the 1m window holding
    #: eight hours has moved on. A bar's minutes are certainly present exactly
    #: once - when the bar itself closes - so that is when they are recorded.
    #:
    #: **A dict rather than two deques**, and the reason is measured: as dense
    #: arrays these were **99.6% nan** and 35% of a Series' bytes - 27MB across
    #: 3,058 series, storing nothing. The state file grew 114MB to 170MB and
    #: the container was OOM-killed once. Sparse also removes the alignment
    #: this file got wrong twice: a deque parallel to `closes` has to be padded
    #: on restore and shifted on eviction, and both of those were bugs.
    fine: dict[int, tuple[float, ...]] = field(default_factory=dict)
    #: Whatever the venue called volume, per bar, and `nan` where it said
    #: nothing. **Not comparable across venues or instruments** - on most feeds
    #: here it is tick count rather than size, and spot FX has no consolidated
    #: volume at all, which `context/activity.py` sets out at length. Kept
    #: because a *weight* does not need to be comparable: within one series it
    #: says which bars carried more business than their neighbours, which is
    #: all `profile` and a VWAP ask of it.
    volumes: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    since_reform: int = 0

    #: The deques above are built by a `default_factory`, which runs before the
    #: instance exists and so cannot see `interval` - it can only close over the
    #: module constant. `retune` is what applies the per-interval window, and it
    #: is called on construction **and on every lookup**, because a `Series`
    #: restored from a save carries the `maxlen` it was written with. Widening
    #: only on construction would leave every existing series at the old size
    #: and the change would appear to do nothing, which is precisely the shape
    #: `Analogue.memory` failed in earlier the same day.

    def __post_init__(self) -> None:
        self.retune()

    def retune(self) -> None:
        """Resize the windows to this interval's, keeping what is in them."""
        want = window_for(self.interval)
        if self.times.maxlen == want:
            return
        for name in ("times", "closes", "highs", "lows", "opens", "volumes"):
            held = getattr(self, name, None)
            if held is not None:
                setattr(self, name, deque(held, maxlen=want))

    def add(
        self,
        when: int,
        high: float,
        low: float,
        close: float,
        open_: float | None = None,
        volume: float | None = None,
    ) -> bool:
        """Fold a bar in. True if it is a new one rather than a correction.

        The answer matters to anything *accumulating* rather than storing: see
        the volatility update in `observe_bar`.
        """
        # A bar arriving for a time already held is a correction, not a new bar.
        opening = close if open_ is None else float(open_)
        if self.times and when == self.times[-1]:
            self.highs[-1], self.lows[-1], self.closes[-1] = high, low, close
            if self.opens:
                self.opens[-1] = opening
            if len(self.volumes) == len(self.closes):
                self.volumes[-1] = math.nan if volume is None else float(volume)
            return False
        self.times.append(when)
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
        # Guarded: a Series restored from before this field existed has an
        # empty deque while the others are full, and appending blindly would
        # misalign every bar against its own open from then on.
        if len(self.opens) == len(self.closes) - 1:
            self.opens.append(opening)
        # Sparse, so there is no pairing to keep and nothing to pad: a bar
        # with no entry has no minutes, which is what the absence means.
        # See `structures-engine.md` in research/docs.
        if len(self.fine) > window_for(self.interval) and self.times:
            oldest = self.times[0]
            self.fine = {k: v for k, v in self.fine.items() if k >= oldest}
        while len(self.volumes) < len(self.closes) - 1:
            self.volumes.append(math.nan)
        if len(self.volumes) == len(self.closes) - 1:
            self.volumes.append(math.nan if volume is None else float(volume))
        self.since_reform += 1
        return True

    def note_fine(
        self,
        when: float,
        low: float,
        high: float,
        down: float = math.nan,
        up: float = math.nan,
    ) -> None:
        """Record the fine extremes of the bar at `when`.

        See `structures-engine.md` in research/docs.
        """
        self.fine[int(when)] = (low, high, down, up)

    def fine_at(self, when: float) -> tuple[float, float, float, float]:
        """The bar's fine extremes and change points, or `nan` where unknown.

        `(low, high, down, up)`. Entries written before the change points
        existed hold two numbers, so the answer is **padded rather than
        indexed**: a save from last week would otherwise raise on the third
        element, inside the try that swallows it, and every origin feature
        would go quietly missing after a deploy. That is the shape
        `_remember_origins` was already bitten by once, on `_origins` itself.
        """
        got = self.fine.get(int(when))
        if not got:
            return (math.nan, math.nan, math.nan, math.nan)
        padded = tuple(got) + (math.nan,) * (4 - len(got))
        return padded[0], padded[1], padded[2], padded[3]

    @property
    def ready(self) -> bool:
        return len(self.closes) >= pips.MIN_POINTS * 4

    @property
    def due(self) -> bool:
        return self.since_reform >= REFORM_EVERY


def _cycle_context(series) -> dict:
    """The nested-timeframe reading, for the journal and an alert's context.

    Handed in for the same reason `_zma_context` is: `to_signal` is a method on
    the call and has no engine to ask. Everything it returns is a float, because
    `Signal.to_dict` rounds the whole features dict.
    """
    if series is None or not cy.ENABLED:
        return {}
    try:
        return series.reading()
    except Exception:  # a reading nothing gates on must not raise
        return {}


def _zma_context(zma) -> dict:
    """The z reading for the journal and for an alert's context.

    See `structures-engine.md` in research/docs.
    """
    if zma is None or not zm.ENABLED:
        return {}
    try:
        if zma.seen < 3:
            return {}
        return {
            "zma_z": round(zma.z_score, 4),
            # The threshold rather than the word for it. `features` is
            # `dict[str, float]` and `Signal.to_dict` rounds every value, so a
            # string here raises on publication - which is what
            # `test_no_published_feature_is_constant` caught. Carrying the
            # threshold is strictly more information than the label anyway:
            # `state` is a comparison of these two, and a consumer that wants
            # "how far past" can only get it this way.
            "zma_strong": round(zma.strong, 4),
            "zma_agrees": float(zma.agrees),
            # **Displacement alone, published beside the agreement.** The two
            # are different calls with different records: `agrees` waits for
            # See `structures-engine.md` in research/docs.
            "zma_stretched": float(zma.stretched),
            "zma_rising": float(zma.rising),
            # The scored record travels with the reading, as counts rather than
            # a rate: a rate has to be `nan` before there are any calls, and a
            # `nan` in a published feature is a number that every comparison
            # downstream silently answers False to. A consumer that wants the
            # rate can divide, and can see the denominator while it does.
            "zma_calls": float(zma.calls),
            "zma_right": float(zma.right),
            "zma_edge_calls": float(zma.edge_calls),
            "zma_edge_right": float(zma.edge_right),
        }
    except Exception:  # a reading nothing gates on must not raise
        return {}


def _break_context(found, when: float) -> dict:
    """The last change of character on this series, for the journal and a gate.

    See `structures-engine.md` in research/docs.
    """
    if found is None:
        return {}
    try:
        return {
            "break_price": round(float(found.price), 8),
            "break_side": float(found.side),
            # Both ages, because they answer different questions: how long the
            # line stood before it failed says how much agreement it carried,
            # and how long ago it failed says whether this is still the market
            # the break happened in.
            "break_held": float(found.held_for),
            "break_age": max(0.0, float(when) - float(found.broke)),
        }
    except Exception:  # a reading nothing gates on must not raise
        return {}


def _anchor_context(zma) -> dict:
    """The **mother cycle's** scored record, whatever bar this call arrived on.

    See `structures-engine.md` in research/docs.
    """
    if zma is None or not zm.ENABLED:
        return {}
    try:
        return {
            "zma_anchor_edge_calls": float(zma.edge_calls),
            "zma_anchor_edge_right": float(zma.edge_right),
        }
    except Exception:  # a reading nothing gates on must not raise
        return {}


@dataclass(slots=True)
class Call(Restorable):
    """A directional call at a level, with everything behind it."""

    feed: str
    interval: str
    level: lv.Level
    inference: reactions.Inference
    price: float
    time: float
    #: What the origin model says about this level, or an empty dict. Computed
    #: at construction because the engine has the series and the Call does not,
    #: and merged into the published features below.
    origin: dict = field(default_factory=dict)
    #: Readings about the instrument rather than about this level - currently
    #: how many timeframes are calling a change. Kept apart from `origin`
    #: because they answer different questions and a consumer reading one
    #: should not have to know the other is in the same dictionary. Merged into
    #: the features the same way.
    context: dict = field(default_factory=dict)
    #: How this touch was described to the kNN - the same `reactions.Features`
    #: the tracker keeps on the touch.
    #:
    #: **Carried because the publish site had no way to reach it.**
    #: `service._level_calls` scores the break model with
    #: `getattr(call, "features", None) or {}`, and this is a slotted
    #: dataclass, so before this field existed the attribute could never be
    #: set and the `or {}` fired on every call ever made. `Breaks.inputs` then
    #: read six missing keys as zeros, so the model scored one vector -
    #: `[0, 0, 0, 0, 0, 0]` - for every level on every instrument, and
    #: `break_probability` moved only as the standardiser's running mean
    #: drifted. Measured on a fixture of 426 published calls: **one distinct
    #: input vector across all of them.**
    #:
    #: It did not read as a dead field, which is why nothing caught it. A
    #: constant input through a continuously-learning model produces a number
    #: that varies plausibly and carries nothing about the call - the same
    #: shape as the stale-file monitor in research/inert.md that reported a
    #: model SETTLED because it was comparing one snapshot with itself.
    features: reactions.Features | None = None

    def to_signal(
        self,
        vol,
        zma=None,
        cycles=None,
        clock=None,
        peers=None,
        busy: float = 1.0,
        market: str = "",
        venue: str = "consensus",
        anchor=None,
        broke=None,
    ) -> Signal:
        # `probability`, not `probability_up`: quoting P(up) beside a *down*
        # call reads as the confidence in down when it is the confidence
        # against it. The base rate flips with it or the pair is not a
        # comparison. See reactions.Inference.probability.
        swept, swept_n = sweeps.sweep_rate(self.level, self.inference.side)
        beyond_vol, beyond_n = (
            sweeps.liquidity_beyond(self.level, peers, self.inference.side, vol)
            if peers
            else (0.0, 0)
        )

        push_vol, capped_why = self.inference.expected_push, ""
        if cycles is not None:
            try:
                push_vol, capped_why = cycles.capped_push(self.inference.expected_push)
            except Exception:  # a reading nothing gates on must not raise
                push_vol, capped_why = self.inference.expected_push, ""

        zone_low, zone_high = self.level.zone(vol)
        zone_low, zone_high = _widen_to_origin(zone_low, zone_high, self.origin)
        # The wider band a stop has to clear. See `Level.sweep_zone`: the touch
        # zone is built from the average wick, and a stop at the average sweep
        # depth is exceeded by about half of all sweeps by construction.
        sweep_low, sweep_high = self.level.sweep_zone(vol, SWEEP_SIGMAS)
        sweep_low, sweep_high = _widen_to_origin(sweep_low, sweep_high, self.origin)
        unit = vol.price_units(self.level.price, 1.0) or 1.0
        wick_below = (self.level.price - zone_low) / unit
        wick_above = (zone_high - self.level.price) / unit
        # How *spread out* the wicks are, not only how deep on average.
        #
        # `SideStats` has tracked this since the sweep zone was built and it
        # has never left the object: only the mean reached a consumer, so
        # anything asking "how far does this level get pushed" got a number
        # that half of pushes exceed. A consumer waiting for a retracement
        # needs the spread to know whether the mean means anything.
        below = self.level.sides.get(lv.Side.ABOVE)
        above = self.level.sides.get(lv.Side.BELOW)
        wick_below_sd = below.wick_sd_vol if below else 0.0
        wick_above_sd = above.wick_sd_vol if above else 0.0

        if clock is not None:
            hour_hold, hour_n = clock.hold_rate(self.feed, self.time)
            _, hour_vol_share = clock.volatility(self.feed, self.time)
        else:
            hour_hold, hour_n, hour_vol_share = 0.0, 0.0, 1.0

        detail = (
            f"{self.inference.direction} from {self.inference.side} at "
            f"{self.level.price:,.6g} - p={self.inference.probability:.0%} "
            f"vs {self.inference.base_rate:.0%} base, "
            f"push {self.inference.expected_push:+.2f}v"
        )
        structure_code = {
            "HH": 1.0,
            "LH": 2.0,
            "HL": 3.0,
            "LL": 4.0,
        }
        high_structure = structure_code.get(str(self.level.high_structure or "").upper(), 0.0)
        low_structure = structure_code.get(str(self.level.low_structure or "").upper(), 0.0)
        return Signal(
            shape=Shape.LEVEL,
            feed=self.feed,
            # **Not always "consensus", and the difference is a claim.** A
            # synthetic has exactly one source: the broker is not one opinion
            # among several, it is the instrument - which `single_source_feeds`
            # already says in as many words while this labelled the signal as
            # an agreement between venues that cannot exist. The caller knows
            # which feeds those are and passes the honest name.
            venue=venue,
            score=abs(self.inference.edge),
            detail=detail,
            # By identity, not by price - the price moves under the filter, so
            # a record grouped by it splits one level across several rows.
            level_id=self.level.id,
            features={
                "level": self.level.price,
                "last_high_structure": high_structure,
                "last_low_structure": low_structure,
                "probability_up": self.inference.probability_up,
                "probability": self.inference.probability,
                # **Possibly pulled in front of a predicted turn.** Unchanged
                # unless `STRUCTURES_CYCLES_ACT` is on, the feed's own depth
                # head is warm and beating the running mean, and the claim
                # reaches past where that head expects this leg to end. It can
                # only ever shrink - see `cycles.Series.capped_push`.
                "expected_push_vol": push_vol,
                # The raw figure, and only when the cap actually moved it.
                # **Absent rather than zero**, which is the rule the rest of
                # this dict follows: a missing key is a missing reading
                # downstream, where a constant zero is a published feature that
                # does nothing - and `tests/test_published.py` is the gate that
                # says so. Two fields here were caught by it in exactly this
                # state before they shipped.
                **({"expected_push_raw": self.inference.expected_push} if capped_why else {}),
                "base_rate_up": self.inference.base_rate_up,
                "edge": self.inference.edge,
                "own_touches": float(self.inference.own_touches),
                "neighbours": float(self.inference.neighbours),
                # How many of those the answer actually rests on. See
                # `Inference.comparable`: the count itself is `k` and therefore
                # the same number on every card ever sent.
                "comparable": float(self.inference.comparable),
                "strength": self.level.strength(self.time, vol),
                "risk_vol": self.inference.risk_vol,
                # Where a violent move began, and whether this level sits in
                # one. A level that coincides with unfilled interest is better
                # evidenced than the same level in open space - see
                # `structures/origins.py`. Recorded for now: nothing gates or
                # sizes on it, and the journal is what will say whether it
                # separates.
                **self.origin,
                # How many timeframes are calling a change right now, and which
                # way. Recorded on the same terms as the origin fields above:
                # nothing gates on it. The measurement behind it is large -
                # +7.92v against -1.24v a day out - and it was taken on 24 days
                # with overlapping forward windows, so what it has earned is a
                # place in the journal and not a place in a gate.
                **self.context,
                # The volatility unit itself, in basis points. Everything else
                # here is measured in multiples of it, so a consumer that only
                # sees the published signal - `trading` reads them off the bus
                # and never touches this engine - cannot turn `risk_vol` or
                # `expected_push_vol` into a price without it. Carrying the
                # multiples without the unit made those two fields unusable
                # outside this process.
                "vol_bps": vol.bps,
                # The same quantity read by a mean-reverting model, and how far
                # the current scale sits above its own long-run level. Recorded
                # rather than used: nothing divides by these yet, and the point
                # of carrying them is that the journal can say whether they
                # would have been the better number. See `garch.py`.
                "garch_bps": vol.garch_bps,
                "vol_stretch": vol.stretch,
                # Read from whole bars rather than closes, and a forecast of
                # the next bar rather than a reading of the last ones. Both
                # recorded and used by nothing - see `ranges.py` and `har.py`.
                "range_bps": vol.range_bps,
                # **The one sizing reads.** A decaying average of true range,
                # which measured better than every other figure here at the
                # horizons they were each built for - including GARCH at one bar
                # against return variance, its own quantity. See
                # `research/docs/volatility-estimators.md` and `ranges.TR_ALPHA`.
                "ewma_tr_bps": vol.ewma_tr_bps,
                "forecast_bps": vol.forecast_bps,
                "forecast_ratio": vol.forecast_ratio,
                # Recorded so the directional question can be settled from the
                # journal rather than argued. `zma_agrees` is the strict form -
                # displacement and momentum pointing the same way - and is the
                # only one worth cutting by.
                **_zma_context(zma),
                **_anchor_context(anchor),
                **_break_context(broke, self.time),
                **_cycle_context(cycles),
                # All four on one scale, combined equally. Recorded so the
                # journal can say whether the combination beat the estimate
                # already in use - see `consensus_vol.py`.
                "ensemble_bps": vol.ensemble_bps,
                # The level's own hold rate on the side price arrived from,
                # and the decisive interactions behind it. The strongest
                # See `structures-engine.md` in research/docs.
                "record_hold": self.inference.record_hold,
                "record_n": self.inference.record_n,
                # When, which nothing in this package has ever conditioned on.
                # The hour is stamped unconditionally so the journal can pair
                # it with outcomes; `hour_hold` and `hour_n` are what the clock
                # has learned about it so far, shrunk, and are near the
                # instrument's base rate until an hour has earned otherwise.
                "hour": float(sessions.hour_of(self.time)),
                "hour_hold": hour_hold,
                "hour_n": hour_n,
                "hour_vol_share": hour_vol_share,
                # The level is a **range**, and an asymmetric one: the origin
                # is where the leg in met the leg out, and each edge extends by
                # how far the wick ran past it on that side. Published because
                # a consumer that only sees `level` will place a stop inside
                # the band where wicks routinely reach - which is the difference
                # between being wrong and being swept.
                "zone_low": zone_low,
                "zone_high": zone_high,
                "wick_below_vol": wick_below,
                "wick_above_vol": wick_above,
                "wick_below_sd": wick_below_sd,
                "wick_above_sd": wick_above_sd,
                # How many wicks are behind those two numbers. A mean and a
                # spread from one observation are not a mean and a spread, and
                # a consumer cannot tell without being told.
                "wick_n": float(below.wick_n if below else 0.0),
                # And the wider band a **stop** has to clear. The two are not
                # the same question: the touch zone is built from the average
                # wick, which is the right centre for "is price at this level"
                # and the wrong edge for "how far past it does price go" - a
                # stop there is exceeded by about half of all sweeps by
                # construction. See `Level.sweep_zone`.
                "sweep_low": sweep_low,
                "sweep_high": sweep_high,
                # Whether this level has a history of being run rather than
                # respected, and what is resting beyond it for price to run it
                # toward. Neither gates anything here: they go to the journal
                # beside the outcome so the question can be answered from our
                # own resolutions. See `sweeps`.
                "sweep_rate": swept,
                "sweep_n": swept_n,
                "liquidity_beyond_vol": beyond_vol,
                "liquidity_beyond_n": float(beyond_n),
                # How busy the market was, as a share of this instrument's own
                # typical bar on this timeframe. A ratio because the underlying
                # count is tick volume on most feeds and absent on some, so
                # only "relative to normal" means the same thing everywhere.
                "activity": busy,
            },
            direction=self.inference.direction,
            market=market,
            interval=self.interval,
            time=self.time,
        )


def _bar_query(feeds: Sequence[str], intervals: Sequence[str]) -> tuple[str, list[object]]:
    """The window-function query both readers share, and its parameters."""
    marks = ",".join("?" * len(intervals))
    where = f"interval IN ({marks})"
    params: list[object] = list(intervals)
    if feeds:
        where += f" AND feed IN ({','.join('?' * len(feeds))})"
        params.extend(feeds)
    return where, params


def _bar_span(
    database: Path | str,
    feeds: Sequence[str],
    intervals: Sequence[str],
    bars: int,
) -> tuple[int, dict[str, float]]:
    """How many bars the warm will replay, and the earliest time per interval.

    Both are aggregates, so they come from SQLite rather than from a list of
    rows in this process. `_eras` only ever needed the earliest timestamp per
    interval - reading three hundred thousand rows to find six numbers was the
    expensive half of a cold start.
    """
    where, params = _bar_query(feeds, intervals)
    with closing(sqlite3.connect(f"file:{Path(database)}?mode=ro", uri=True, timeout=10.0)) as conn:
        rows = conn.execute(
            "SELECT interval, COUNT(*), MIN(ts) FROM ("
            "  SELECT interval, ts,"
            "         ROW_NUMBER() OVER (PARTITION BY feed, interval ORDER BY ts DESC) AS rn"
            f"  FROM bars WHERE {where}"
            ") WHERE rn <= ? GROUP BY interval",
            (*params, bars * 8),
        ).fetchall()
    total = sum(int(n) for _, n, _ in rows)
    first = {str(interval): float(start) for interval, _, start in rows if interval}
    return total, first


def _read_bars(
    database: Path | str,
    feeds: Sequence[str],
    intervals: Sequence[str],
    bars: int,
) -> Iterator[dict]:
    """Stored bars as bus-shaped payloads, oldest first, **streamed**.

    See `structures-engine.md` in research/docs.
    """
    path = Path(database)
    if not path.exists() or not intervals:
        return

    where, params = _bar_query(feeds, intervals)
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)) as conn:
            conn.row_factory = sqlite3.Row
            # Oldest first, and grouped so every venue on one bar arrives
            # together - the consensus needs them adjacent to reach a quorum on
            # See `structures-engine.md` in research/docs.
            held = {row[1] for row in conn.execute("PRAGMA table_info(bars)")}
            columns = ["feed", "venue", "interval", "ts", "high", "low", "close"]
            columns += [name for name in ("open", "volume") if name in held]
            picked = ", ".join(columns)
            found = conn.execute(
                f"SELECT {picked} FROM ("
                f"  SELECT {picked},"
                "         ROW_NUMBER() OVER (PARTITION BY feed, interval ORDER BY ts DESC) AS rn"
                f"  FROM bars WHERE {where}"
                ") WHERE rn <= ? ORDER BY ts, feed, interval",
                (*params, bars * 8),
            )
            for row in found:
                yield {**row, "time": row["ts"]}
    except sqlite3.Error as exc:
        log.warning("levels: could not warm from %s: %s", path, exc)
        return


class Engine:
    """Levels and directional calls for every instrument at once."""

    def __init__(
        self,
        *,
        window: int = WINDOW,
        pip_count: int = PIP_COUNT,
        intervals: tuple[str, ...] = LEVEL_INTERVALS,
        horizon: float = 3600.0,
        shape_horizon: int = SHAPE_HORIZON,
        charge_spread: bool = True,
        # The one named default, not a third copy of it. This literal had
        # already drifted from the two in `config` once - see DEFAULT_FORMATION
        # - and a constructor default that disagrees with the setting is a
        # deployment drawing something nobody chose.
        formation: str = DEFAULT_FORMATION,
        run_threshold: float = runs.RUN_SWING_VOL,
        single_source: frozenset[str] = frozenset(),
    ) -> None:
        #: How swings are found: `pip` selects bar extremes, `run` takes the
        #: boundaries between runs of volatility. An experiment, not a setting
        #: to tune in production - the point is to run both over one history
        #: and let the outcome machinery say which price respects more.
        #: The passes to run, merged. Composing them is the point rather than a
        #: fallback: a formation that draws nothing is not a neutral choice, it
        #: is silence. `origin` alone draws no levels at all on gold at 1m, 5m
        #: or 15m - the timeframes carrying nearly every signal - so selecting
        #: it on its own would stop that instrument trading, quietly.
        self.passes: tuple[str, ...] = ()
        self.formation = ""
        self.draw_with(formation)
        self.run_threshold = run_threshold
        #: Whether the quoted spread is charged against every level call. On by
        #: default, because an uncharged edge is a gross number and acting on
        #: one is the mistake the cost exists to prevent.
        #:
        #: Off is for answering "what would this have said without the cost" -
        #: the two runs are directly comparable, since nothing else changes. It
        #: is deliberately not a threshold to tune: the cost is measured, and
        #: something measured is either charged or it is not.
        self.charge_spread = charge_spread
        self.shape_horizon = shape_horizon
        self.window = window
        self.pip_count = pip_count
        self.intervals = intervals
        self.vol = VolBook()
        self.projection = pj.Book()
        #: Recorded and scored, not voting - see `structures/zma.py`. It is
        #: measured at 0.50 on this desk's instruments and worse than that on
        #: Boom and Crash, so it keeps a record until the record says otherwise.
        self.zma = zm.Book()
        #: The streaming z-score across nested timeframes, with a turn model.
        #: Recorded and scored like `zma`, and for the same reason - see
        #: `structures/cycles.py`, which is explicit that two of the three
        #: things it adds were measured at nothing.
        self.cycles = cy.Book()
        #: Constructed spreads read from live quotes rather than from bars.
        #: Empty unless `STRUCTURES_SPREAD_QUOTES` names pairs - see
        #: `structures/spreadquotes.py`.
        self.spread_quotes = sq.from_env()
        self.tracker = reactions.Tracker(horizon=horizon)
        #: Pivots come from completed sessions, so they need no confirmation
        #: delay and exist before price has ever turned there.
        self.sessions = pivots.Sessions()
        #: Bars are per venue; levels are not. This makes them one series.
        self.consensus = Consensus(single_source=single_source)
        #: (feed, interval, venue) already reported as arriving with no
        #: high/low. Warned once each rather than per bar - the condition is a
        #: property of the producer, so it either happens always or never, and
        #: per-bar it would be thousands of identical lines a day.
        self._flat_bars: set[tuple[str, str, str]] = set()
        #: What kind of market this is, learned online. Labels only - it
        #: records and does not decide. See `regimes.py`.
        self.regimes = regimes.Regimes()
        #: And quotes are per venue for exactly the same reason, which they were
        #: not given until the bar fix made the omission visible.
        self.quotes = Quotes()
        #: Shapes seen before and what followed. Independent of levels: a level
        #: is a price, a shape is not, so a double top repeats across
        #: instruments and prices where a level cannot.
        self.shapes = patterns.Library()
        #: Open shape instances, waiting for the horizon to say what followed.
        self._pending: dict[tuple[str, str], tuple[int, float, int]] = {}
        self._series: dict[tuple[str, str], Series] = {}
        #: How long a feed may go without a bar before `forget` drops what it
        #: accumulated. Zero disables the staleness rule and leaves only the
        #: universe filter. Measured per feed, not per series - see `forget`.
        self.forget_feed: float = FORGET_FEED_SECONDS
        #: Pairs already told about, so `supports` says so once rather than on
        #: every reform. Not persisted: it is a log-noise guard, and saying it
        #: again after a restart is correct.
        self._declined: set[tuple[str, str]] = set()
        self._levels: dict[tuple[str, str], list[lv.Level]] = {}
        #: The latest change of character per series. **Derived and not
        #: persisted**, deliberately: it is recomputed from confirmed swings
        #: every time levels reform, and a break restored from before a restart
        #: would be a claim about structure that the swings behind it no longer
        #: support. See `structures/breaks.py`.
        self._breaks: dict[tuple[str, str], bk.Break] = {}
        #: feed and interval -> the origins found there, kept rather than
        #: recomputed. See `_remember_origins`: this dict is the place a
        #: refined band can live, and it is worth +0.23R a trade to have one.
        self._origins: dict[tuple[str, str], origins.Origins] = {}
        #: The timestamp of the bar being processed. Held so that "what was
        #: knowable" is answerable at any point, including from a test.
        self._now: float = 0.0
        #: Touches that have resolved since anyone last looked, with the level
        #: they resolved at. Queued rather than pushed because the engine has
        #: no journal and should not grow one - a resolution is a fact about
        #: price, and who wants to record it is not the engine's business.
        self._resolved: list[tuple[lv.Level, reactions.Touch]] = []
        #: Recent quoted spreads per instrument, in basis points - the cost of
        #: taking any edge found here, measured all along and never charged.
        #: A window rather than a running value, so the cost can be a *median*.
        self._spread: dict[str, deque[float]] = {}
        #: Which interval carries the touch check, as history advances. Set
        #: only while replaying: `[(from_time, interval), ...]`, oldest first.
        #: Empty means "the finest series seen so far", which is right live.
        self._touch_eras: list[tuple[float, str]] = []
        self.calls = 0
        if not charge_spread:
            # Said out loud, once, because a disabled charge and an unarmed one
            # both record `cost_vol` of 0.0 and are indistinguishable in the
            # journal afterwards. A zero that was configured should not be
            # readable as a zero that went wrong.
            log.warning(
                "structures: spread costs disabled - every level call will be "
                "judged on its gross push, and cost_vol will read 0.0 for that "
                "reason rather than for want of quotes"
            )

    # --------------------------------------------------------------- levels

    def forget(self, keep: Collection[str] | None, now: float = 0.0) -> dict[str, int]:
        """Drop every per-feed store for a feed this desk no longer follows.

        See `structures-engine.md` in research/docs.
        """
        keep_set = {str(f) for f in keep} if keep is not None else None
        if keep_set is None and not (now and self.forget_feed > 0):
            return {}

        last: dict[str, float] = {}
        for (feed, _interval), series in self._series.items():
            times = series.times
            if times:
                last[feed] = max(last.get(feed, 0.0), float(times[-1]))

        def doomed(feed: str) -> bool:
            if keep_set is not None and feed not in keep_set:
                return True
            if not (now and self.forget_feed > 0):
                return False
            seen = last.get(feed)
            # A feed with no bar at all is residue by definition, but only
            # judge it once the engine has been running long enough to have
            # asked for one.
            return seen is None or (now - seen) > self.forget_feed

        gone = {feed for feed in {f for f, _ in self._series} | set(last) if doomed(feed)}
        gone |= {f for f, _ in self._levels if doomed(f)}
        gone |= {f for f, _ in self._origins if doomed(f)}
        gone |= {f for f in self._spread if doomed(f)}
        if not gone:
            return {}

        counts = {"feeds": len(gone)}

        def sweep(name: str, store: Any, at: int = 0) -> None:
            if not isinstance(store, dict | set):
                return
            doomed_keys = [
                k for k in store if (k[at] if isinstance(k, tuple) and len(k) > at else k) in gone
            ]
            for k in doomed_keys:
                store.discard(k) if isinstance(store, set) else store.pop(k, None)
            if doomed_keys:
                counts[name] = len(doomed_keys)

        sweep("series", self._series)
        sweep("levels", self._levels)
        sweep("origins", self._origins)
        # Lazily created, so asked for by name. An attribute that does not
        # exist yet holds nothing to forget.
        sweep("changes", getattr(self, "_changes", None))
        sweep("pending", self._pending)
        sweep("spread", self._spread)
        sweep("flat_bars", self._flat_bars)
        sweep("declined", self._declined)
        sweep("consensus", getattr(self.consensus, "_bars", None))
        sweep("touches", getattr(self.tracker, "_open", None))
        counts["vol"] = self.vol.forget({f for f, _ in self.vol._by_key if f not in gone})
        held = getattr(self, "projection", None)
        if held is not None:
            counts["projection"] = held.forget({f for f in held.feeds() if f not in gone})
        # `getattr` for the same reason as `projection`: a restored engine
        # pickled before this book existed has no attribute to sweep, and the
        # schema hash only invalidates state it can see.
        zbook = getattr(self, "zma", None)
        if zbook is not None:
            counts["zma"] = zbook.forget({f for f, _ in zbook._by_key if f not in gone})
        cbook = getattr(self, "cycles", None)
        if cbook is not None:
            counts["cycles"] = cbook.forget({f for f in cbook._by_feed if f not in gone})
        return {k: v for k, v in counts.items() if v}

    def series(self, feed: str, interval: str) -> Series:
        key = (feed, interval)
        found = self._series.get(key)
        if found is None:
            found = self._series[key] = Series(feed, interval)
        else:
            # Restored series carry the `maxlen` they were saved with, and a
            # deploy that changes the window would otherwise only reach series
            # created after it. Cheap: one integer comparison per lookup.
            found.retune()
        return found

    def origins_bracketing(
        self, feed: str, interval: str, price: float, vol: Volatility
    ) -> tuple[float | None, float | None]:
        """The near edges of the origins above and below `price`, or None.

        See `structures-engine.md` in research/docs.
        """
        found = self._origin_at(feed, interval, price, vol)
        below = found.get("origin_below_high")
        above = found.get("origin_above_low")
        return (
            float(below) if isinstance(below, int | float) else None,
            float(above) if isinstance(above, int | float) else None,
        )

    def _note_change(self, feed: str, interval: str, series: Series, vol) -> None:
        """Feed this timeframe's newest step to its own change detectors.

        See `structures-engine.md` in research/docs.
        """
        if interval not in CHANGE_INTERVALS or not vol.warm:
            return
        closes = series.closes
        if len(closes) < 2:
            return
        unit = float(closes[-1]) * vol.bps / 10_000.0 if vol.bps else 0.0
        if unit <= 0:
            return
        # **A restore from a save that predates these has neither dict.** The
        # engine is persisted whole and is not a `Restorable` dataclass, so
        # nothing fills in a new attribute for it - this is the same guard
        # `_remember_origins` needed for `_origins`, and it is needed for the
        # same reason.
        held = getattr(self, "_changes", None)
        if held is None:
            held = self._changes = {}
        stamps = getattr(self, "_change_at", None)
        if stamps is None:
            stamps = self._change_at = {}
        key = (feed, interval)
        pair = held.get(key)
        if pair is None:
            # The slowest timeframe in the ladder keeps the shipped threshold
            # and every faster one is asked for more, so a 5m call and a 1h
            # call are comparably rare and the count means something.
            slowest = max(lv.SECONDS.get(name, 0.0) for name in CHANGE_INTERVALS)
            mine = lv.SECONDS.get(interval, 0.0)
            lift = CHANGE_K * math.log(slowest / mine) if 0 < mine <= slowest else 0.0
            nats = focus.THRESHOLD + lift
            pair = held[key] = (Focus(threshold=nats), Focus(threshold=nats, up=False))
        step = float(closes[-1]) - float(closes[-2])
        was_up, was_down = stamps.get(key, (0.0, 0.0))
        up, down = pair
        up_fired = bool(up.update(step, scale=unit))
        if up_fired:
            up.reset()
            was_up = self._now
        down_fired = bool(down.update(step, scale=unit))
        if down_fired:
            down.reset()
            was_down = self._now
        stamps[key] = (was_up, was_down)
        self._note_character(feed, interval, up_fired, down_fired)

    def _note_character(self, feed: str, interval: str, up_fired: bool, down_fired: bool) -> None:
        """Is this instrument still behaving like itself?

        A monitor, not a signal - see `structures-context-character.md`. Kept in its own
        method so a fault in it cannot reach the detectors above, and `getattr`-guarded
        for the same reason `_changes` is: the engine is persisted whole and is not a
        `Restorable` dataclass, so nothing fills in a new attribute on restore and this
        runs on the first bar after a deploy.
        """
        held = getattr(self, "_character", None)
        if held is None:
            held = self._character = {}
        key = (feed, interval)
        watch = held.get(key)
        if watch is None:
            watch = held[key] = Character()
        watch.observe(up_fired, down_fired)
        for said in watch.alarms():
            # A warning, because it needs a person and there is nothing to do
            # automatically: whether a changed instrument should still be traded is not
            # a decision this process is entitled to make.
            log.warning("structures: %s %s - %s", feed, interval, said)

    def character(self, feed: str, interval: str) -> dict:
        """This series' character reading, or an empty dict if it has none yet."""
        held = getattr(self, "_character", None)
        watch = held.get((feed, interval)) if held else None
        return watch.to_dict() if watch is not None else {}

    def _learn_vol(
        self,
        feed: str,
        interval: str,
        when: float,
        open_: float,
        high: float,
        low: float,
        close: float,
        reported: object,
        realised_bps: float,
    ) -> None:
        """Hand one closed bar to the shared volatility learner.

        See `structures-engine.md` in research/docs.
        """
        if realised_bps <= 0:
            return
        hour = float(sessions.hour_of(when))
        weekday = float(time.gmtime(when).tm_wday) if when > 0 else -1.0

        # The clock lives on the service, which owns the learned session
        # record; the engine is handed a reference at startup. `getattr`
        # because a restore from a save predating it has no such attribute and
        # this runs on the first bar after a deploy.
        share = 1.0
        clock = getattr(self, "clock", None)
        if clock is not None:
            try:
                _, share = clock.volatility(feed, when)
            except Exception:  # a clock with nothing on this feed yet
                share = 1.0

        # Changepoint evidence from the detectors `_note_change` just fed. The
        # larger of the two directions: the learner is being told how much
        # reason there is to stop trusting the past, which is a magnitude
        # question rather than a directional one.
        nats = 0.0
        fired = False
        held = getattr(self, "_changes", None)
        if held is not None:
            pair = held.get((feed, interval))
            if pair is not None:
                nats = max(float(pair[0].statistic), float(pair[1].statistic))
        stamps = getattr(self, "_change_at", None)
        if stamps is not None:
            got = stamps.get((feed, interval))
            if got is not None:
                fired = self._now > 0 and self._now in got

        self.vol.learn(
            feed,
            interval,
            realised_bps,
            open_=open_,
            high=high,
            low=low,
            close=close,
            hour=hour,
            weekday=weekday,
            hour_share=share,
            volume=float(reported) if isinstance(reported, int | float) and reported > 0 else 0.0,
            focus_nats=nats,
            changed=fired,
            interval_seconds=lv.SECONDS.get(interval, 0.0),
        )

    def _observe_cycles(self, feed: str, interval: str, close: float) -> None:
        """One closed bar into the nested-timeframe book.

        See `structures-engine.md` in research/docs.
        """
        if not cy.ENABLED:
            return
        try:
            self.cycles.observe(feed, interval, close)
        except Exception as exc:
            log.debug("structures: no cycle reading for %s %s: %s", feed, interval, exc)

    def _observe_zma(self, feed: str, interval: str, close: float) -> None:
        """Feed the z-score one closed bar, and let it score its own last call.

        Swallows its own failures like every other reading on this path that
        nothing gates on: two outages this month were a fault in here taking the
        whole structures service down.
        """
        if not zm.ENABLED:
            return
        try:
            self.zma.observe(feed, interval, close)
        except Exception as exc:
            log.debug("structures: no zma reading for %s %s: %s", feed, interval, exc)

    def _settle_projection(self, feed: str, interval: str, opened: float, close: float) -> None:
        """Score both drift conventions against one closed bar.

        See `structures-engine.md` in research/docs.
        """
        if not pj.ENABLED:
            return
        try:
            effects.fired("structures.projection")
            seconds = lv.SECONDS.get(interval, 0.0)
            if seconds > 0 and opened > 0 and close > 0:
                self._projection().settle(feed, float(opened), seconds, close)
        except Exception as exc:
            log.debug("structures: no projection for %s %s: %s", feed, interval, exc)

    def _projection(self) -> pj.Book:
        """The projection book, created on demand.

        Asked for by name rather than assumed, for the reason `forget` gives
        about `_changes`: an `Engine` restored from a snapshot written before
        this field existed never ran `__init__`, and an attribute access there
        raises inside a bar update on a live desk.
        """
        found = getattr(self, "projection", None)
        if found is None:
            found = self.projection = pj.Book()
        return found

    def _learned_at(self, feed: str, interval: str) -> dict[str, float]:
        """The learned forecast for this series, for the journal.

        **Absent rather than 1.0 while the model is cold**, which is the rule
        `LevelRange.features` and `changing` both follow: a missing key is a
        missing reading downstream, and a ratio of one is the claim that the
        model looked and expected no change. Those are different, and the
        journal is the only thing that can eventually tell them apart.
        """
        try:
            learned = self.vol.learned
            if not learned.warm:
                return {}
            key = f"{feed}|{interval}"
            got = learned.predict(key)
            if got <= 0:
                return {}
            return {"learned_bps": round(got, 4), "learned_ratio": round(learned.ratio(key), 4)}
        except Exception:  # never let a published extra stop a call
            return {}

    def changing(self, feed: str, when: float = 0.0) -> dict[str, float]:
        """How many timeframes are calling a change on this instrument.

        See `structures-engine.md` in research/docs.
        """
        stamps = getattr(self, "_change_at", None)
        if not stamps:
            return {}
        now = float(when) or self._now
        floor = now - CHANGE_WINDOW
        up = down = 0
        watched = 0
        for interval in CHANGE_INTERVALS:
            got = stamps.get((feed, interval))
            if got is None:
                continue
            watched += 1
            was_up, was_down = got
            # `> 0` as well as inside the window. A detector that has never
            # fired stores 0.0, and on a live clock that is nineteen thousand
            # days in the past so it never matters - but a replay starting at
            # the epoch puts 0.0 *inside* the window and every silent timeframe
            # reports a change. A test caught it; production would have
            # produced a journal full of confident nonsense on the next
            # backtest and nothing on the live path to say so.
            up += 1 if was_up > 0 and floor < was_up <= now else 0
            down += 1 if was_down > 0 and floor < was_down <= now else 0
        if not watched:
            return {}
        return {
            "change_up_tf": float(up),
            "change_down_tf": float(down),
            # How many were in a position to say anything, so a count of one
            # out of four can be told from one out of one. A restart warms the
            # timeframes at different speeds and the two look identical
            # without this.
            "change_watched_tf": float(watched),
        }

    def _capture_fine(self, feed: str, interval: str, series: Series) -> None:
        """Record the fine extremes of `series`' most recently *completed* bars.

        See `structures-engine.md` in research/docs.
        """
        if interval == FINE_INTERVAL or not series.times:
            return
        span = lv.SECONDS.get(interval, 0.0)
        fine = self._series.get((feed, FINE_INTERVAL))
        if not span or fine is None or not fine.times:
            return
        times, closes = list(fine.times), list(fine.closes)
        # **Why a capture failed, counted per interval.** The first fix here was
        # aimed at a boundary tolerance and moved nothing on 4h, which is the
        # timeframe that matters - so the reason is worth measuring rather than
        # inferred a second time. `left` is the fine series starting after the
        # coarse bar did; `right` is it ending before the bar did; `short` is
        # too few bars to work with at all.
        book = getattr(self, "_capture_why", None)
        if book is None:
            book = self._capture_why = {}
        tally = book.setdefault(interval, {"ok": 0, "left": 0, "right": 0, "short": 0, "none": 0})
        for when in list(series.times)[-2:]:
            got = origins.extremes_in(times, closes, float(when), span)
            if got is None:
                start = float(when)
                if len(times) < 2:
                    tally["short"] += 1
                elif times[0] > start:
                    tally["left"] += 1
                elif times[-1] < start + span:
                    tally["right"] += 1
                else:
                    tally["none"] += 1
            else:
                tally["ok"] += 1
            if got is not None:
                # The change points are computed here for the same reason the
                # extremes are: this is the one moment the bar's minutes are
                # certainly still in the window. Both directions, because
                # which one matters is not knowable until the impulse breaks
                # structure, hours to days later. `None` where the bar is too
                # short to have one, and the extremes are still recorded.
                shift = origins.change_in(times, closes, float(when), span)
                series.note_fine(float(when), *got, *(shift or (math.nan, math.nan)))

    def _remember_origins(
        self,
        feed: str,
        interval: str,
        fresh: list,
        unit: float = 0.0,
    ) -> list:
        """Keep origins across calls, refining each one the first time it is seen.

        See `structures-engine.md` in research/docs.
        """
        # **A restore from a save that predates this field has no `_origins`.**
        # The engine is persisted whole and is not a `Restorable` dataclass, so
        # nothing fills in a new attribute for it - the first call after a
        # deploy would raise, inside the try that swallows it, and every origin
        # feature would go quietly missing. Asked for rather than assumed.
        kept_all = getattr(self, "_origins", None)
        if kept_all is None:
            kept_all = self._origins = {}
        key = (feed, interval)
        kept = kept_all.get(key)
        if kept is None:
            kept = kept_all[key] = origins.Origins()
        # `self.series` **creates** the entry, and `touch_source` picks the
        # finest interval that has one - so asking for 1m here would silently
        # move the touch check onto a series that has never received a bar.
        # Three tests caught it; production would have stopped touching levels.
        # The extremes were captured when each bar closed, so this is a
        # lookup rather than a scan of a 1m series that has moved on.
        series = self._series.get((feed, interval))
        return kept.remember(
            fresh,
            (lambda o: series.fine_at(o.when)) if series else None,
            unit=unit,
        ) or list(fresh)

    def _origin_at(self, feed: str, interval: str, price: float, vol: Volatility) -> dict:
        """What the origin model says about a level, as published features.

        See `structures-engine.md` in research/docs.
        """
        try:
            unit = price * vol.bps / 10_000.0 if vol.bps else 0.0
            if unit <= 0:
                return {}
            series = self.series(feed, interval)
            closes = list(series.closes)
            if len(closes) < 12:
                return {}
            bars = None
            if len(series.opens) == len(closes):
                bars = [
                    _OriginBar(o, h, lo, c)
                    for o, h, lo, c in zip(
                        series.opens, series.highs, series.lows, closes, strict=False
                    )
                ]
            fresh = origins.Origins().observe(list(series.times), closes, unit, bars_at=bars)
            found = self._remember_origins(feed, interval, fresh, unit)
            if not found:
                return {}
            nearest = min(found, key=lambda o: abs(o.price - price))
            inside = any(o.holds(price) for o in found)
            # The pair that brackets the current price. A swing that runs from
            # one origin to the other needs both ends: the near one is where it
            # See `structures-engine.md` in research/docs.
            above = [(o.low, o) for o in found if o.low > price]
            below = [(o.high, o) for o in found if o.high < price]
            inside = [o for o in found if o.low <= price <= o.high]
            above += [(o.high, o) for o in inside if o.high > price]
            below += [(o.low, o) for o in inside if o.low < price]
            holding = min(inside, key=lambda o: o.high - o.low, default=None)
            bracket: dict[str, float] = {}
            if above:
                edge, zone = min(above, key=lambda pair: pair[0])
                bracket["origin_above_low"] = edge
                bracket["origin_above_vol"] = (edge - price) / unit
                # The far side of that zone, which is where a stop belongs -
                # inside it is where the wicks are. The same number whether
                # price is below the band or standing in it: going up, the wall
                # this move finally meets is the band's high either way.
                bracket["origin_above_high"] = zone.high
                bracket["origin_above_revisits"] = float(zone.revisits)
            if below:
                edge, zone = max(below, key=lambda pair: pair[0])
                bracket["origin_below_high"] = edge
                bracket["origin_below_vol"] = (price - edge) / unit
                bracket["origin_below_low"] = zone.low
                bracket["origin_below_revisits"] = float(zone.revisits)
            if holding is not None:
                # Which zone price is standing in, kept apart from the bounds.
                # A level inside an origin is a different object from one in
                # open space, and `in_origin` has said so for months without
                # anything being able to say *which* origin.
                bracket["origin_holding_low"] = holding.low
                bracket["origin_holding_high"] = holding.high
                bracket["origin_holding_revisits"] = float(holding.revisits)
            return {
                **bracket,
                "origin_distance_vol": abs(nearest.price - price) / unit,
                "origin_size_vol": nearest.size_vol,
                # How decisively the impulse cleared the extremum it broke.
                # Both this and the size have a floor below which the origin
                # holds *worse* than a generated process - see origins.py - so
                # a consumer that wants to be stricter than the detector can.
                "origin_extremum_vol": nearest.extremum_vol,
                "origin_revisits": float(nearest.revisits),
                # Whether an independent change-point estimate agrees with
                # where the refinement put this origin. Measured: the refined
                # See `structures-engine.md` in research/docs.
                "origin_confirmed": 1.0 if nearest.confirmed else 0.0,
                "in_origin": 1.0 if inside else 0.0,
                # The zone itself, in prices. The four fields above describe an
                # origin without saying where it is, which is enough to score a
                # level and not enough to enter at one: a consumer that wants
                # to rest an order at the edge of the zone needs the edge.
                # `origin_distance_vol` is an absolute distance and cannot be
                # turned back into a price - it has lost the direction.
                "origin_price": nearest.price,
                "origin_low": nearest.low,
                "origin_high": nearest.high,
            }
        except Exception as exc:
            log.debug("structures: no origin reading for %s %s: %s", feed, interval, exc)
            return {}

    FORMATIONS: ClassVar[tuple[str, ...]] = (
        "pip",
        # `pip` drawn from the extremes rather than the closes - two passes,
        # highs for peaks and lows for troughs. See `pips.extremes`.
        "wick",
        # Volume-weighted average price, where there is volume to weight with.
        "vwap",
        "run",
        "origin",
        "profile",
        # Defined by equality rather than by prominence: two extremes at one
        # price, which is a different claim from two significant turns.
        "equal",
        # Defined by trade that did not happen - the only one here that is.
        "gap",
        # Defined by nothing that happened at all, which is why it is measured
        # rather than assumed.
        "round",
    )

    def draw_with(self, formation: str) -> tuple[str, ...]:
        """Set which passes draw levels, validating the name. Returns the passes.

        See `structures-engine.md` in research/docs.
        """
        wanted = (
            ("pip", "run")
            if formation == "both"
            else tuple(n.strip() for n in formation.split(",") if n.strip())
        )
        if not wanted or [n for n in wanted if n not in self.FORMATIONS]:
            raise ValueError(
                f"unknown formation {formation!r} - use {', '.join(self.FORMATIONS)}, "
                "'both', or a comma list of them"
            )
        self.passes = wanted
        self.formation = formation
        return wanted

    def feeds(self) -> set[str]:
        """Every instrument this engine has bars for, whatever the interval.

        From the series rather than from the levels: an instrument that has
        printed bars but not yet formed a level is one this engine is watching,
        and a consumer asking "what am I following" wants it in the answer.
        """
        return {feed for feed, _ in self._series}

    def levels(self, feed: str, interval: str = "") -> list[lv.Level]:
        if interval:
            return list(self._levels.get((feed, interval), []))
        return [
            level
            for (this_feed, _), found in self._levels.items()
            if this_feed == feed
            for level in found
        ]

    def break_of(self, feed: str, interval: str) -> bk.Break | None:
        """The latest change of character on this series, if there was one."""
        return self._breaks.get((feed, interval))

    def swings(self, series: Series, vol: Volatility) -> list[pips.Point]:
        """The turning points levels are drawn at - by whichever formation.

        Pluggable so the two can be *compared* rather than argued about. Both
        return the same `Point`, carrying `confirmed`, so everything downstream
        - `as_of`, `form`, the whole outcome machinery - is indifferent to
        which produced them. See [levels.md], "A level spans periods too".
        """
        return self._points(self.passes[0], series, vol)

    def _form(self, series: Series, visible: Sequence[pips.Point], vol: Volatility):
        """Cluster the visible swings into candidate levels.

        See `structures-engine.md` in research/docs.
        """
        if len(self.passes) == 1:
            return lv.form(
                series.feed,
                series.interval,
                [point for point, _ in pips.structure(pips.turns(visible))],
                vol,
                origin=self.passes[0],
                min_swings=FORMATION_MIN_SWINGS.get(self.passes[0], lv.MIN_SWINGS),
            )
        made: list = []
        for name in self.passes:
            found = lv.form(
                series.feed,
                series.interval,
                [
                    point
                    for point, _ in pips.structure(
                        pips.turns(pips.as_of(self._points(name, series, vol), self._now))
                    )
                ],
                vol,
                origin=name,
                min_swings=FORMATION_MIN_SWINGS.get(name, lv.MIN_SWINGS),
            )
            made = found if not made else lv.merge(made, found, vol)
        return made

    def _points(self, name: str, series: Series, vol: Volatility) -> list[pips.Point]:
        """One pass's turning points.

        A table rather than a chain of returns, because the chain had grown to
        nine and every new formation made it one longer - and because the table
        is the honest picture of what a formation *is* here: a name and a way
        of turning one series into points, with nothing downstream able to tell
        which of them found a level.
        """
        times, closes = list(series.times), list(series.closes)
        stamps = [float(t) for t in times]
        highs, lows = list(series.highs), list(series.lows)
        draw: dict[str, Callable[[], list[pips.Point]]] = {
            "run": lambda: runs.points(times, closes, vol, threshold=self.run_threshold),
            "origin": lambda: origin_points.points(stamps, closes, vol),
            # **`weights` has been accepted by `profile` since it was written
            # and never once passed.** A volume profile drawn without volume
            # weights every bar the same, which is a fair fallback and was
            # never meant to be the only mode. `Series.volumes` is what it was
            # waiting for.
            "profile": lambda: profile.points(stamps, closes, vol, weights=list(series.volumes)),
            "equal": lambda: equals.points(stamps, closes, vol, count=self.pip_count),
            # An imbalance is a relationship between one bar's high and
            # another's low, which closes cannot express.
            "gap": lambda: gaps.points(stamps, highs, lows, closes, vol),
            "round": lambda: rounds.points(stamps, closes, vol),
            # The only pass drawn from where price actually **reached** rather
            # than where it settled. A swing high is a high; a close series
            # puts the level wherever the bar happened to finish after being
            # turned away, which is a price nobody defended.
            "wick": lambda: pips.extremes(times, highs, lows, self.pip_count),
            "vwap": lambda: vwap.points(stamps, highs, lows, closes, list(series.volumes), vol),
        }
        found = draw.get(name)
        return found() if found else pips.points(times, closes, self.pip_count)

    def supports(self, feed: str, interval: str) -> bool:
        """Can this instrument carry a level at this resolution?

        Judged on how many ticks fit inside a zone - see `MIN_TICKS_PER_ZONE`.
        Silent about what it cannot judge: an estimate that is not warm, or an
        instrument that has not yet printed a single-step move, is missing
        evidence rather than evidence of a problem, and suppressing on that
        would decline every instrument for its first hour.
        """
        vol = self.vol.of(feed, interval)
        series = self._series.get((feed, interval))
        if not vol.warm or series is None or not series.closes or not vol.tick:
            return True
        price = series.closes[-1]
        if not price or not vol.bps:
            return True
        tick_vol = (vol.tick / price * 10_000) / vol.bps
        if tick_vol <= 0:
            return True
        # The zone this pair would actually get, by the same rule `Level.zone`
        # uses, so the answer tracks the geometry rather than a second copy of
        # it. Wicks can widen a real zone further, which only helps.
        zone_vol = max(lv.MIN_ZONE_VOL, min(tick_vol * lv.MIN_ZONE_TICKS, lv.GRID_ZONE_VOL))
        return zone_vol / tick_vol >= MIN_TICKS_PER_ZONE

    def drop_unsupported(self) -> int:
        """Decline every pair whose grid is too coarse, now rather than later.

        See `structures-engine.md` in research/docs.
        """
        dropped = 0
        for feed, interval in sorted(self._levels):
            if self.supports(feed, interval):
                continue
            self._levels.pop((feed, interval), None)
            self._declined.add((feed, interval))
            dropped += 1
            log.info(
                "levels: %s %s declines a level - the grid is too coarse for a "
                "zone to be entered rather than crossed",
                feed,
                interval,
            )
        return dropped

    def reform(self, series: Series, when: float) -> list[lv.Level]:
        """Re-derive levels from the confirmed swings in the window."""
        key = (series.feed, series.interval)
        if not self.supports(series.feed, series.interval):
            # Said once per pair, because it is a property of the instrument
            # and the venue rather than an event, and repeating it every reform
            # would bury everything else.
            if key not in self._declined:
                self._declined.add(key)
                log.info(
                    "levels: %s %s declines a level - the grid is too coarse "
                    "for a zone to be entered rather than crossed",
                    series.feed,
                    series.interval,
                )
            # Anything already formed here was formed on the same bad geometry.
            self._levels.pop(key, None)
            series.since_reform = 0
            return []
        self._declined.discard(key)
        vol = self.vol.of(series.feed, series.interval)
        found = self.swings(series, vol)
        visible = pips.as_of(found, when)
        candidates = self._form(series, visible, vol)
        merged = lv.merge(self._levels.get(key, []), candidates, vol)
        self._levels[key] = self.prune(merged, series.closes[-1], vol, when)
        series.since_reform = 0
        self._record_shape(series, visible)
        return self._levels[key]

    def prune(self, levels: list[lv.Level], price: float, vol, when: float) -> list[lv.Level]:
        """Drop levels that are not earning their place.

        See `structures-engine.md` in research/docs.
        """
        touched = [level for level in levels if level.touches >= 1.0]
        fresh = [
            level
            for level in levels
            if level.touches < 1.0 and abs(level.distance_vol(price, vol)) <= KEEP_VOL
        ]
        fresh.sort(key=lambda level: level.strength(when, vol), reverse=True)
        room = max(0, MAX_LEVELS - len(touched))
        kept = touched + fresh[:room]
        dropped = len(levels) - len(kept)
        if dropped:
            log.debug("levels: dropped %d untested levels", dropped)
        return kept

    # -------------------------------------------------------------- shapes

    def _record_shape(self, series: Series, visible: list[pips.Point]) -> None:
        """Note the shape the last few confirmed swings make.

        Only confirmed swings, for the same reason levels use only confirmed
        swings: a shape whose last point has not settled is a shape nobody
        could have recognised yet.
        """
        turns = [point for point, _ in pips.structure(pips.turns(visible))]
        key = (series.feed, series.interval)
        # **Before the shape returns early.** The break is a different question
        # from the shape and answering it must not depend on there being enough
        # points for one - the early return below is about `Shape`, and a
        # sequence too short to name a pattern can still have changed
        # character.
        found = bk.last_break(turns)
        if found is not None:
            self._breaks[key] = found
        elif key in self._breaks:
            # Swings that no longer contain the flip mean the structure was
            # redrawn under it. Silence is the honest answer then.
            del self._breaks[key]
        if len(turns) < patterns.SHAPE_POINTS:
            return
        shape = patterns.Shape.of(turns[-patterns.SHAPE_POINTS :], series.feed, series.interval)
        if shape is None or shape.flat:
            return
        if key in self._pending:
            return  # one open shape per series; overlapping ones are the same episode
        handle = self.shapes.add(shape)
        if handle >= 0:
            self._pending[key] = (handle, series.closes[-1], len(series.closes))

    def match_shape(self, feed: str, interval: str) -> patterns.Match | None:
        """What the library says about the shape currently forming here."""
        series = self._series.get((feed, interval))
        if series is None or not series.ready:
            return None
        found = pips.points(list(series.times), list(series.closes), self.pip_count)
        turns = [point for point, _ in pips.structure(pips.turns(pips.as_of(found, self._now)))]
        if len(turns) < patterns.SHAPE_POINTS:
            return None
        shape = patterns.Shape.of(turns[-patterns.SHAPE_POINTS :], feed, interval)
        return self.shapes.match(shape) if shape else None

    def _resolve_shapes(self, series: Series, vol) -> None:
        """Close out any shape whose horizon has passed.

        The move is measured in volatility units from where the shape completed,
        so a pattern that "works" in a violent week and one that works in a calm
        one are the same observation.
        """
        key = (series.feed, series.interval)
        pending = self._pending.get(key)
        if pending is None:
            return
        handle, price, at_bar = pending
        if len(series.closes) - at_bar < self.shape_horizon:
            return
        moved = (series.closes[-1] - price) / price * 10_000 if price else 0.0
        self.shapes.resolve(handle, moved / vol.bps)
        self._pending.pop(key, None)

    # -------------------------------------------------------------- feeding

    def __setstate__(self, state: dict) -> None:
        """Restore a pickled engine, including one written by an older build.

        See `structures-engine.md` in research/docs.
        """
        self.__dict__.update({**Engine().__dict__, **state})

    def touch_interval(self, feed: str = "", when: float | None = None) -> str:
        """Which interval's bars carry the touch check for all the others.

        See `structures-engine.md` in research/docs.
        """
        if self._touch_eras:
            at = self._now if when is None else when
            found = self._touch_eras[0][1]
            for start, interval in self._touch_eras:
                if start > at:
                    break
                found = interval
            return found
        seen = {interval for (this, interval) in self._series if not feed or this == feed}
        candidates = seen or set(self.intervals)
        return min(candidates, key=confluence.rank, default="")

    @staticmethod
    def _eras_from(first: dict[str, float]) -> list[tuple[float, str]]:
        """Era boundaries from the earliest time per interval.

        The half of `_eras` that does the work. Split out because the other
        half - finding those earliest times - was reading three hundred
        thousand rows to produce six numbers, and SQLite can answer it with a
        GROUP BY.
        """
        eras: list[tuple[float, str]] = []
        best = ""
        for interval, start in sorted(first.items(), key=lambda kv: kv[1]):
            if not best or confluence.rank(interval) < confluence.rank(best):
                best = interval
                eras.append((start, best))
        return eras

    @staticmethod
    def _eras(rows: Sequence[dict]) -> list[tuple[float, str]]:
        """When each finer series starts, so a replay can hand the check over.

        The finest interval available only ever gets finer as time runs
        forward, so this is one pass over the earliest timestamp per interval,
        keeping the improvements.
        """
        first: dict[str, float] = {}
        for row in rows:
            interval = str(row.get("interval") or "")
            when = float(row.get("time") or 0.0)
            if interval and (interval not in first or when < first[interval]):
                first[interval] = when

        return Engine._eras_from(first)

    def observe_bar(self, payload: dict) -> list[Call]:
        """One `prices.bars` message. Returns any calls it produced.

        See `structures-engine.md` in research/docs.
        """
        feed = str(payload.get("feed") or "")
        interval = str(payload.get("interval") or "")
        if not feed or interval not in self.intervals:
            return []
        close = payload.get("close")
        if not isinstance(close, int | float) or not close:
            return []
        when = int(payload.get("time") or time.time())
        high = float(payload.get("high") or close)
        low = float(payload.get("low") or close)
        venue = str(payload.get("venue") or "")
        # A bar with no extremes is a doji as far as everything below is
        # concerned, and a doji has no leg in and no leg out - which is what an
        # See `structures-engine.md` in research/docs.
        if high == low == close:
            key = (feed, interval, venue)
            if key not in self._flat_bars:
                self._flat_bars.add(key)
                log.warning(
                    "structures: %s %s from %s carries no high/low - levels on "
                    "this series are forming from closes alone",
                    feed,
                    interval,
                    venue or "an unnamed venue",
                )

        # The open was on the payload and read by nothing. Range estimators
        # need all four prices, and Yang-Zhang needs the open specifically -
        # it is the only one of them unbiased across an opening gap, and the
        # gap is exactly what the open measures.
        opened = float(payload.get("open") or close)

        agreed = self.consensus.observe(feed, interval, venue, when, high, low, float(close))
        if agreed is None:
            return []  # not enough venues on this bar yet
        high, low, close = agreed

        self._now = max(self._now, when)
        series = self.series(feed, interval)
        reported = payload.get("volume")
        fresh = series.add(
            when,
            high,
            low,
            float(close),
            opened,
            float(reported) if isinstance(reported, int | float) and reported > 0 else None,
        )
        # **Every time, not only when the bar is new.** A bar arrives repeatedly
        # while it forms, and only the last of those calls has the whole bar's
        # minutes behind it - so capturing once on `fresh` would store the
        # extremes of a bar's first few minutes and keep them.
        self._capture_fine(feed, interval, series)
        # This timeframe's own volatility: a typical 4h move is not a typical
        # 5m move, and one estimate for both makes every threshold expressed in
        # volatility units wrong for all but whichever series updates most.
        vol = self.vol.of(feed, interval)
        # Once per *bar*, not once per venue row. `Consensus.observe`
        # deliberately answers again on every venue that reports a bar, so the
        # See `structures-engine.md` in research/docs.
        if fresh:
            vol.update(float(close))
            # Whole-bar estimates, once per bar rather than once per venue -
            # same reasoning as the line above.
            # Through the book rather than the series, so the implied member is
            # supplied where it votes. Four feeds at 1d and 1w; everywhere else
            # this is exactly what it was. See `vol/implied.py`.
            realised = self.vol.observe_bar(
                feed, interval, opened, high, low, float(close), when=self._now or time.time()
            )
            # And this timeframe's change detectors, after the volatility so
            # they are scaled by an estimate that has seen this bar. Wrapped
            # because a reading nobody gates on must not be able to stop the
            # engine - two outages this month were a fault in here taking the
            # whole structures service down.
            try:
                self._note_change(feed, interval, series, vol)
            except Exception as exc:
                log.debug("structures: no change reading for %s %s: %s", feed, interval, exc)
            # The learned forecaster, last, because it reads the changepoint
            # evidence the line above just produced. Wrapped for the same
            # reason, and it matters more here: this is the newest thing in the
            # bar path and the one most likely to raise on a shape nobody
            # anticipated. Off unless asked for - see `config.vol_learner`.
            if getattr(self, "learn_vol", False):
                try:
                    self._learn_vol(
                        feed, interval, when, opened, high, low, float(close), reported, realised
                    )
                except Exception as exc:
                    log.debug("structures: no learned reading for %s %s: %s", feed, interval, exc)
            # The forward cone, settled against the bar that just closed. Its
            # own method so that `observe_bar` stays inside the branch ceiling
            # and so the flag it is gated by sits next to the work it gates.
            self._settle_projection(feed, interval, opened, float(close))
            self._observe_zma(feed, interval, float(close))
            self._observe_cycles(feed, interval, float(close))
        # Pivots are session structures priced at today's scale, so they use the
        # reference estimate rather than the bar interval that happened to
        # deliver them - a 4h bar completing a day does not make it a 4h level.
        self._roll_sessions(feed, when, high, low, float(close), self.reference(feed))
        self._resolve_shapes(series, vol)
        if not series.ready:
            return []
        if series.due or not self._levels.get((feed, interval)):
            self.reform(series, when)

        # Formed. Whether this bar also *touches* is a separate question, and
        # the answer is no unless it is the finest series this instrument has -
        # otherwise the same interaction would be counted once here and again
        # when the fine bars arrive.
        if interval != self.touch_interval(feed, when):
            return []
        if not fresh:
            # ...and once per bar, for the same reason the volatility estimate
            # is. `Consensus.observe` answers again on every venue row, and the
            # See `structures-engine.md` in research/docs.
            return []
        calls: list[Call] = []
        # A bar is stamped with its **open** time, but it is not knowable until
        # it closes - and quotes carry wall clock. Feeding both to one tracker
        # See `structures-engine.md` in research/docs.
        observed = min(when + lv.SECONDS.get(interval, 0.0), time.time())
        for other in self.intervals_for(feed):
            # `when` is the bar's *open*, which is what says whether a touch
            # lived through the range this bar is about to hand over.
            calls += self.check(feed, other, float(close), observed, low, high, since=when)
        return calls

    def observe_quote(self, payload: dict) -> list[Call]:
        """A quote moves price against existing levels without re-forming them.

        Quotes are what make a touch detectable in time to matter - waiting for
        a 5m bar to close means reporting the interaction after it happened.
        """
        feed = str(payload.get("feed") or "")
        mid = payload.get("mid")
        if not feed or not isinstance(mid, int | float) or not mid:
            return []
        # The constructed spreads, priced from this quote and its partner's.
        # Before anything else in this method, because it concerns a different
        # instrument entirely - a failure here must not cost the level path its
        # quote.
        try:
            for name, price in self.spread_quotes.observe(payload):
                self.zma.observe(name, sq.INTERVAL, price)
        except Exception as exc:
            log.debug("structures: no spread quote reading: %s", exc)
        when = float(payload.get("time") or time.time())
        spread = payload.get("spread_bps")
        if isinstance(spread, int | float) and spread > 0:
            self._spread.setdefault(feed, deque(maxlen=SPREAD_WINDOW)).append(float(spread))
        # What the venues agree on, not whichever one published last. See
        # `Quotes`: the raw mid made a change of publisher look like a move of
        # three and a half volatility units on spx500, which is past the
        # distance that resolves a touch.
        agreed = self.quotes.observe(feed, str(payload.get("venue") or ""), when, float(mid))
        # Quotes feed the tick-level estimate, which is the common denominator
        # every timeframe's levels are ranked against - so it takes the agreed
        # price too, or the disagreement between venues is counted as movement
        # and inflates the very denominator everything else is divided by.
        vol = self.vol.of(feed)
        vol.update(agreed)
        calls: list[Call] = []
        # Pivot levels live under their session name, so quotes must check
        # every interval this instrument has levels at, not just the bar ones.
        for interval in self.intervals_for(feed):
            calls += self.check(feed, interval, agreed, when)
        return calls

    # ------------------------------------------------------------- touching

    def cost_of(self, feed: str, vol: Volatility | None = None) -> float:
        """What crossing the spread costs here, in volatility units.

        See `structures-engine.md` in research/docs.
        """
        if not self.charge_spread:
            return 0.0
        seen = self._spread.get(feed)
        if not seen or vol is None or not vol.bps:
            return 0.0
        return statistics.median(seen) / vol.bps

    def intervals_for(self, feed: str) -> list[str]:
        """Every interval this instrument has levels at, pivots included."""
        return sorted({interval for (this, interval) in self._levels if this == feed})

    def _deliver(
        self, level: lv.Level, done: reactions.Touch, vol: Volatility, when: float
    ) -> None:
        """Everything downstream of a resolved touch, wherever it resolved.

        Both ways a touch can end have to arrive here. `update` closing one on
        a price and `expire` closing one on the clock are the same event to a
        level, to the journal and to `facto`, and only the first was being
        delivered.
        """
        # The origin, not the extreme. The extreme is a wick - liquidity taken
        # a fraction beyond the level at a price nobody traded around - while
        # the origin is where the leg in ended and the leg out began, which is
        # the price the level is actually drawn at.
        level.observe_touch(done.origin or done.extreme, vol, when)
        # The wick is the zone's far edge, not noise to discard.
        level.observe_wick(done.features.side, done.origin or done.extreme, done.extreme, vol)
        log.debug("level %s %.5g resolved %s", level.feed, level.price, done.outcome)
        self._resolved.append((level, done))
        # Bounded: a consumer that stops draining must not become a slow memory
        # leak in a service designed to run for months.
        if len(self._resolved) > MAX_RESOLVED:
            del self._resolved[: len(self._resolved) - MAX_RESOLVED]

    def trading(self, feed: str, when: float) -> bool:
        """Is this instrument's market open, or have its bars simply stopped?

        See `structures-engine.md` in research/docs.
        """
        interval = self.touch_interval(feed, when)
        series = self._series.get((feed, interval))
        if series is None or not series.times:
            return True
        return (when - series.times[-1]) <= lv.SECONDS.get(interval, 60.0) * STALE_BARS

    def _drain_expired(self, when: float) -> None:
        """Deliver the touches `expire` closed on the clock rather than a price.

        See `structures-engine.md` in research/docs.
        """
        expired = self.tracker.expire(when)
        if not expired:
            return
        known = {
            (level.feed, level.interval, round(level.price, 8)): level
            for levels in self._levels.values()
            for level in levels
        }
        for touch in expired:
            level = known.get((touch.feed, touch.interval, round(touch.level_price, 8)))
            if level is None:
                # The level was re-formed or pruned while the touch was open.
                # Nothing to credit it to; the kNN memory already has it.
                continue
            # `expire` cannot do this itself - it has the touch, not the level.
            level.record(touch.features.side, touch.outcome, touch.push_vol, when)
            if touch.outcome is lv.Outcome.BREAK and touch.broke_at:
                level.broke_at = touch.broke_at
            # Held back, which the resolving path does and this one did not.
            # A touch that expired did so because price sat at the level and
            # See `structures-engine.md` in research/docs.
            level.waiting = True
            self._deliver(level, touch, self.vol_for(touch.feed, touch.interval), when)

    def vol_for(self, feed: str, interval: str) -> Volatility:
        """The estimate a level at this interval is measured against.

        See `structures-engine.md` in research/docs.
        """
        if interval in pivots.PERIODS:
            return self.reference(feed)
        return self.vol.of(feed, interval)

    def check(
        self,
        feed: str,
        interval: str,
        price: float,
        when: float,
        low: float | None = None,
        high: float | None = None,
        since: float | None = None,
    ) -> list[Call]:
        """Advance every open interaction, and open one where price has arrived.

        See `structures-engine.md` in research/docs.
        """
        vol = self.vol_for(feed, interval)
        if not vol.warm:
            return []
        calls: list[Call] = []
        for level in self._levels.get((feed, interval), []):
            # Before anything decides whether this level is interesting. A
            # forward return is measured *after* its touch resolved, so the
            # one place it must not live is inside a branch that only runs
            # while the touch is open - see `ReactionTracker.carry`.
            self.tracker.carry(level, price, vol, when)
            open_touch = self.tracker.open_touch(level)
            if open_touch is not None:
                # The wick belongs to this touch only if the touch was already
                # open when the bar carrying it opened.
                within = since is not None and open_touch.started >= since
                done = self.tracker.update(
                    level,
                    price,
                    vol,
                    when,
                    None if within else low,
                    None if within else high,
                )
                if done is not None:
                    # The origin, not the extreme. The extreme is a wick -
                    # liquidity taken a fraction beyond the level at a price
                    # nobody traded around - while the origin is where the leg
                    # in ended and the leg out began, which is the price the
                    # level is actually drawn at.
                    self._deliver(level, done, vol, when)
                    # Only hold the level back if price is *still* in the zone.
                    # An interaction that resolved by price leaving has already
                    # done the leaving, and making it wait for a second exit
                    # would drop the next genuine approach.
                    level.waiting = level.contains(price, vol)
                continue

            if not level.contains(price, vol):
                # Out of the zone is not the same as away from the level. Price
                # sitting on the edge crosses it constantly, and re-arming on
                # each crossing counts a consolidation as dozens of turns - the
                # residue of the same bug the `waiting` flag was added for,
                # which the flag alone did not reach.
                if abs(level.distance_vol(price, vol)) >= lv.REARM_VOL:
                    level.waiting = False
                continue

            # Inside the zone, but this is the same visit that just resolved.
            if level.waiting:
                continue
            # ...or the market is shut and this is Friday's price, still being
            # answered to every poll. Checked here rather than at the top of
            # `check` on purpose: an open touch must still be advanced, so that
            # GAP_FACTOR can discard it, and levels must still be formed. It is
            # only *opening* one that a closed market makes meaningless.
            if not self.trading(feed, when):
                continue
            side = self._approach(level, price)
            features = reactions.features_for(
                level,
                side,
                price,
                vol,
                approach_vol=self._speed(feed, interval, vol),
                run_vol=self._run(feed, interval, vol),
                # Whether price is easing off into the level or still coming.
                # Orthogonal to the speed above it - see `_slowing`.
                slowing=self._slowing(feed, interval),
                # The regression slope into the level, and the one before it.
                # See `_slope`: the pair separates a level approached flat
                # because nothing is happening from one approached flat after a
                # run, and those break at very different rates.
                **dict(
                    zip(("slope", "prior_slope"), self._slope(feed, interval, vol), strict=True)
                ),
                # Which timeframe drew this level, as a number. The largest
                # single effect measured on this book - see `_interval_log`.
                interval_log=_interval_log(interval),
                when=when,
            )
            touch = self.tracker.begin(level, price, features, when)
            inference = reactions.infer(
                level,
                side,
                features,
                self.tracker.memory,
                vol,
                price=price,
                cost_vol=self.cost_of(feed, vol),
            )
            # Kept on the touch so the resolution can be scored against what
            # was believed at the time - including the touches that were never
            # published, which is the half of the distribution nothing has ever
            # been able to look at. See `Touch.edge`.
            touch.edge = inference.edge
            touch.probability_up = inference.probability_up
            touch.base_rate_up = inference.base_rate_up
            touch.actionable = inference.actionable
            # A call is priced entirely in volatility units, so an estimate
            # that has not warmed makes every number on it meaningless rather
            # than merely uncertain. See `Volatility.warm`: the guard existed
            # and nothing asked it, and a brent call went out claiming a push
            # of 10,229 volatility units.
            if not vol.warm:
                continue
            calls.append(
                Call(
                    feed=feed,
                    interval=interval,
                    level=level,
                    inference=inference,
                    price=price,
                    time=when,
                    origin=self._origin_at(feed, interval, level.price, vol),
                    context={**self.changing(feed, when), **self._learned_at(feed, interval)},
                    # The same object the tracker put on the touch, so the
                    # break model is scored on this touch rather than on zeros.
                    # See `Call.features`.
                    features=features,
                )
            )
            self.calls += 1
        self._drain_expired(when)
        return calls

    def _roll_sessions(
        self, feed: str, when: int, high: float, low: float, close: float, vol
    ) -> None:
        """Turn completed sessions into pivot levels for the next one.

        Pruned like any other level, and that is not optional: a session adds
        ten pivots and sessions keep completing, so without it a fortnight of
        history accrues a hundred and forty of them and nothing ever removes
        one. Yesterday's pivots are watched; the ones from twelve days ago are
        not, unless price actually reacted at them.
        """
        for session in self.sessions.observe(feed, when, high, low, close):
            key = (feed, session.period)
            built = pivots.build(feed, session, vol)
            merged = lv.merge(self._levels.get(key, []), built, vol)
            self._levels[key] = self.prune(merged, close, vol, float(when))

    def regime_changed(self, feed: str, severity: float = 0.5) -> int:
        """Discount every level's history for this instrument.

        See `structures-engine.md` in research/docs.
        """
        touched = 0
        for (this_feed, _), found in self._levels.items():
            if this_feed != feed:
                continue
            for level in found:
                level.regime_changed(severity)
                touched += 1
        if touched:
            log.info(
                "levels: discounted %d %s levels, severity %.0f%%", touched, feed, severity * 100
            )
        return touched

    def _approach(self, level: lv.Level, price: float) -> lv.Side:
        """Which side price came from - the previous bar, not the current one.

        Using the current price would be circular: inside the zone, price is by
        definition next to the level, and the question is where it came *from*.
        """
        series = self._series.get((level.feed, level.interval))
        if series is not None and len(series.closes) >= 2:
            return level.side_of(series.closes[-2])
        return level.side_of(price)

    def reference(self, feed: str) -> Volatility:
        """The estimate levels from every timeframe are compared against.

        Cross-timeframe questions - which level is nearest, is this one worth
        acting on - need one denominator, or "three volatility units away" means
        something different for each level and they cannot be ranked.
        """
        tick = self.vol.of(feed)
        if tick.warm:
            return tick
        # Before any quotes have arrived, the finest timeframe with data is the
        # closest thing to a tick estimate.
        for interval in self.intervals:
            found = self.vol.of(feed, interval)
            if found.warm:
                return found
        return tick

    def _speed(self, feed: str, interval: str, vol) -> float:
        """How fast price is moving, in volatility units per bar."""
        series = self._series.get((feed, interval))
        if series is None or len(series.closes) < 2:
            return 0.0
        previous, latest = series.closes[-2], series.closes[-1]
        if not previous:
            return 0.0
        return abs((latest - previous) / previous * 10_000) / vol.bps

    #: Bars in the rolling regression. Twenty is the window every number in
    #: research/slopes.md was measured on; a result that exists only at one
    #: arbitrary window is one to distrust, and this is that window until
    #: somebody checks another.
    SLOPE_BARS: ClassVar[int] = 20

    def _slope(self, feed: str, interval: str, vol) -> tuple[float, float]:
        """The regression slope into this bar, and the one a window earlier.

        See `structures-engine.md` in research/docs.
        """
        series = self._series.get((feed, interval))
        bars = self.SLOPE_BARS
        if series is None or len(series.closes) < bars * 2 or not vol.bps:
            return 0.0, 0.0
        closes = list(series.closes)[-bars * 2 :]

        def fit(window: list[float]) -> float:
            # sum((i - mean) * x) / sum((i - mean)^2), with the denominator a
            # constant for a fixed window length.
            n = len(window)
            middle = (n - 1) / 2
            spread = sum((i - middle) ** 2 for i in range(n))
            if not spread:
                return 0.0
            rise = sum((i - middle) * x for i, x in enumerate(window))
            price = window[-1]
            if not price:
                return 0.0
            # Price per bar -> basis points per bar -> volatility units per bar.
            return (rise / spread) / price * 10_000 / vol.bps

        return fit(closes[bars:]), fit(closes[:bars])

    def _run(self, feed: str, interval: str, vol: Volatility, bars: int = 20) -> float:
        """How far the leg arriving here has already travelled, in vol units.

        See `structures-engine.md` in research/docs.
        """
        series = self._series.get((feed, interval))
        if series is None or len(series.closes) < 2 or vol.bps <= 0:
            return 0.0
        closes = list(series.closes)[-bars:]
        here = closes[-1]
        # The side the leg came from: distance from whichever extreme is
        # further, so an approach from below and one from above read alike.
        travelled = max(abs(here - min(closes)), abs(here - max(closes)))
        unit = here * vol.bps / 10_000.0
        return round(travelled / unit, 4) if unit > 0 else 0.0

    def _slowing(self, feed: str, interval: str, near: int = 3, far: int = 3) -> float:
        """Speed over the last `near` bars, over the speed of the `far` before.

        See `structures-engine.md` in research/docs.
        """
        series = self._series.get((feed, interval))
        if series is None or len(series.closes) < near + far + 1:
            return 0.0
        closes = list(series.closes)[-(near + far + 1) :]
        early, late = closes[: far + 1], closes[far:]
        before = abs(early[-1] - early[0]) / max(len(early) - 1, 1)
        after = abs(late[-1] - late[0]) / max(len(late) - 1, 1)
        if before <= 0:
            return 0.0
        # Clamped, and the number is why. `slowing` is a ratio, so a near-zero
        # denominator sends it to infinity - a guard on `before <= 0` catches
        # See `structures-engine.md` in research/docs.
        return min(after / before, SLOWING_CAP)

    # ---------------------------------------------------------------- state

    # ------------------------------------------------------------- warming

    def seed(
        self,
        database: Path | str,
        *,
        feeds: Sequence[str] = (),
        intervals: Sequence[str] = (),
        bars: int = SEED_BARS,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Warm the windows from stored history. Returns bars replayed.

        See `structures-engine.md` in research/docs.
        """
        wanted = tuple(intervals) or self.intervals
        if not Path(database).exists():
            return 0
        # Both are aggregates, so the count and the era boundaries come from
        # SQLite rather than from a list of rows held in this process. The rows
        # themselves are then streamed: materialising them cost 410MB on a
        # 908MB host and OOM-killed every cold start it attempted.
        total, first_seen = _bar_span(database, feeds, wanted, bars)
        if not total:
            return 0

        # Worked out before the replay starts, so the first bar is judged by the
        # same rule as the last rather than by whichever series happened to have
        # arrived.
        eras = self._eras_from(first_seen)
        replayed = 0
        feeds_seen: set[str] = set()
        # A cold start replays six-figure bar counts and says nothing until it
        # finishes, which is minutes of a service that looks hung - and the one
        # thing this project keeps relearning is that silence has to say which
        # kind it is. `on_progress` lets a terminal draw a bar; without one the
        # log carries it, because that is where a running service is read from.
        beat = max(1, total // 100)
        spoken = max(1, total // 10)
        self._touch_eras = eras
        try:
            for row in _read_bars(database, feeds, wanted, bars):
                self.observe_bar(row)  # calls discarded on purpose
                replayed += 1
                feeds_seen.add(str(row["feed"]))
                if on_progress is not None:
                    if replayed % beat == 0 or replayed == total:
                        on_progress(replayed, total)
                elif replayed % spoken == 0 and replayed != total:
                    log.info(
                        "levels: warming, %d%% (%s of %s bars)",
                        round(100 * replayed / total),
                        f"{replayed:,}",
                        f"{total:,}",
                    )
        finally:
            self._touch_eras = []
        log.info(
            "levels: warmed from %d stored bars across %s, touching from %s",
            replayed,
            ", ".join(sorted(feeds_seen)) or "nothing",
            " then ".join(interval for _start, interval in eras) or "nothing",
        )
        return replayed

    def drain_resolved(self) -> list[tuple[lv.Level, reactions.Touch]]:
        """Take the touches that have resolved since the last call.

        Draining rather than reading, because each resolution should be
        recorded once: a consumer that read without clearing would journal the
        same outcome on every message.
        """
        found, self._resolved = self._resolved, []
        return found

    def drain_followed(self) -> list[reactions.Forward]:
        """The forward returns finished since the last call. See `Forward`."""
        return self.tracker.drain_followed()

    def summary(self) -> list[dict]:
        """What the engine knows, for `structures levels`."""
        rows = []
        for (feed, interval), found in sorted(self._levels.items()):
            vol = self.vol.of(feed, interval)
            for level in sorted(found, key=lambda level: level.price):
                rows.append(level.to_dict(vol))
                rows[-1]["interval"] = interval
        return rows
