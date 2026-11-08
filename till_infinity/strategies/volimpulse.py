"""`VI_M15_imp_H4sq` - a 15-minute impulse out of a four-hour squeeze.

The rule as specified, and nothing else:

1. **The squeeze.** On four-hour calendar bins, the range of the last 24
   finished bins - four days - divided by the four-hour ATR, must sit in the
   bottom 20% of the last 750 bins of the same statistic. 750 four-hour bins
   is 125 calendar days.
2. **The impulse.** A 15-minute bar whose close-to-close move is at least
   `3.0` times the size a **frozen** HAR model forecast for it. The
   coefficients in `HAR` were fitted on bars before 2026-02 and never refitted;
   a HAR refitted over the period it is scored on is look-ahead with a
   likelihood attached.
3. **Entry.** The impulse's own direction, at market, so the fill lands on the
   first minute after the M15 close - at the ask on a buy and the bid on a
   sell. No fill in the cut-off hours.
4. **Exit.** On the clock alone: 16 M15 bars, four hours. **No stop and no
   target**, which is why `protective_stop` is off - see `Profile`.
5. **Markets.** The five the rule names, which are the keys of `HAR`.
6. **Scoring.** 1R is the trigger distance, `3.0 * sigma`, so the trade is
   sized against one further impulse-sized step and `realised / risk_money` is
   R in the unit the rule is written in.

## What is already known about this, before any of it is run

[`research/docs/impulse-vol.md`](../../research/docs/impulse-vol.md) measured
the conditional mean of exactly this conditioning over 8 markets and
198,529-294,533 bars each, and reported that **the multi-timeframe version
adds nothing**: a four-hour squeeze with a 15-minute impulse reads `d_rv`
+0.225 where no condition at all reads +0.226. That sentence is about the
**volatility** channel, which is the one this desk can already forecast. On the
direction channel the same study read USDCAD at **-0.228** of a forecast unit
at trigger 3 over 12 bars - a *reversion*, against the continuation this rule
takes - with its own interval containing its quoted round trip.

So this module claims nothing. It exists so that the rule can be measured as a
**trade** - a fill at a real spread, a time exit, one position at a time, R
denominated in the trigger - which that study explicitly did not do: "this is a
conditional mean, not a trade. There is no stop, no target and no fill model".

## Why the squeeze is a switch and not a constant

`Fold.require_squeeze` is the one arm that decides the rule's central claim: if
the impulse alone reads the same, the squeeze contributes nothing and the rule
is the single-timeframe one wearing a longer name. It is a field on the
production fold rather than a copy in a harness so that the arm and the rule
run through the same detector - the one thing every expensive mistake on this
desk has been a version of.

## Warm-up, which is long enough to be an operational fact

The rank needs 750 finished four-hour bins, so a cold desk cannot fire for
**12,000 M15 bars - 125 calendar days** of continuous history. The catalogue
`node/corpus.py` fills holds about 76 days, so a backtest over it produces
**zero** signals by construction and that is not a null. `warm_bars_request`
asks for the full window; what arrives is whatever the venue has.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, ClassVar

from nautilus_trader.model.data import Bar

from ..domain import costs
from ..domain.models import Intent, Refusal, Side
from .entries import EdgeEntry
from .exits import ManagedExit
from .profile import Profile

#: Finished four-hour bins the squeeze range is measured over - four days.
SQUEEZE_BINS = 24
#: Finished four-hour bins the range statistic is ranked inside - 125 days.
#: A **trailing** rank: a global quantile would label the past with the future.
SQUEEZE_WINDOW = 750
#: The share of that window the statistic must sit below. The rule's "bottom
#: 20%", read as `rank <= 0.20` with the current bin inside the window.
SQUEEZE_SHARE = 0.20
#: Four-hour bins the "normal ATR" the range is divided by is averaged over.
#:
#: **The specification is ambiguous here and this is the reading taken.** "The
#: range of the last 24 four-hour bars ... after adjusting for normal ATR"
#: admits at least three denominators - a textbook ATR(14), a long-run normal,
#: and none at all - and they are not the same gate: divide by an ATR over the
#: same 24 bins and the adjustment cancels the thing being measured, while an
#: ATR over the whole 750-bin window is constant inside it and so changes no
#: rank at all. 14 is the textbook period, on the four-hour clock. The other
#: two readings are carried as arms in the measurement rather than argued about
#: here.
SQUEEZE_ATR = 14
#: Multiples of the forecast a bar must move to be an impulse, and the
#: denominator of 1R.
IMPULSE_MULT = 3.0
#: M15 bars a position is held. Four hours.
HOLD_BARS = 16
#: Seconds in a four-hour calendar bin. Bins, never a difference of aligned
#: closes: aligning first and differencing after turns every session gap into a
#: fabricated one-bar return.
SLOW_SECONDS = 4 * 3_600
#: The HAR components, as M15 bar counts: one hour, one day, one week.
#:
#: **Reused, not invented.** The specification says "a HAR volatility model"
#: and names no components. `research/harness/vol_gate.py` already fits one on
#: this desk's 15-minute bars with exactly these three - `har1h` over 4 bars,
#: `har1d` over 96 and `har1w` over 480 - so taking them keeps this rule's
#: denominator comparable with the one study that has measured a HAR here, and
#: `reproduce-the-baseline-before-an-increment` is the reason that matters: a
#: HAR on this desk once read +0.036 against a shelf's +0.110 and the cause was
#: the data window rather than the model.
HAR_LAGS = (4, 96, 480)


def _number(value: Any) -> float:
    """A float, or zero. A feature that is absent and one that is unparseable
    are the same thing to a threshold, and neither is a reason to raise."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True, slots=True)
class Har:
    """A frozen HAR forecast of the next bar's **mean absolute** return.

    Mean absolute and not a standard deviation, because the two differ by 1.25
    for a normal and `research/harness/vol.py` records that this desk has
    already made that substitution once. The regression is on `log|r|`, so the
    exponential of its fit is a forecast of the *geometric* mean; `scale` is
    `mean(|r|) / mean(exp(fit))` over the fitting sample, frozen with the
    coefficients, and without it the forecast runs low and the trigger fires
    too often.

    `weights` is one coefficient per entry in `lags`, in the same order.
    """

    const: float
    weights: tuple[float, ...]
    scale: float
    lags: tuple[int, ...] = HAR_LAGS
    #: The last timestamp in the fitting sample, as an ISO date. Carried so a
    #: reader can see that the model was frozen before the period it is scored
    #: on rather than take it on trust.
    until: str = ""

    def __post_init__(self) -> None:
        if len(self.weights) != len(self.lags):
            raise ValueError(
                f"a HAR with {len(self.lags)} lags needs {len(self.lags)} weights, "
                f"not {len(self.weights)}"
            )
        if self.scale <= 0.0:
            raise ValueError(f"the HAR scale is a multiplier, not {self.scale}")

    def forecast(self, parts: tuple[float, ...]) -> float:
        """The forecast from the lagged mean absolute returns, or 0.0.

        Zero means *no forecast*, which happens when a component is zero - a
        run of identical closes, which this venue does produce on a quiet
        synthetic - and `log(0)` is not a number a threshold can use. Returning
        zero rather than raising keeps the caller's "unwarmed" and "no
        variance" branches separate, which `finding-edges` records as a silent
        `None` meaning four things.
        """
        if len(parts) != len(self.lags) or any(part <= 0.0 for part in parts):
            return 0.0
        total = self.const + sum(w * math.log(p) for w, p in zip(self.weights, parts, strict=True))
        return self.scale * math.exp(total)


#: The frozen HAR per feed, fitted on 15-minute bars **before 2026-02** by
#: `research/harness/vol_impulse.py` and pasted here.
#:
#: Written down rather than fitted at start-up for the reason the date is in
#: the rule at all: a model refitted on the period it trades is look-ahead, and
#: a model refitted at every deploy is a different rule on every deploy.
#: `tests/test_vol_impulse.py` pins the forecast against a stored fixture, so a
#: coefficient edited by hand fails there rather than in a tally.
#:
#: Fitted on 270,969 to 271,717 bars per feed (2015-01-02 to 2026-02-01), R2 on
#: `log|r|` of 0.109 to 0.143. The smearing factor runs 1.59 to 1.69; without it
#: the forecast is the geometric mean of `|r|`, which is 1.6 times too small,
#: so a trigger of 3.0 would be an effective 1.9 and the rule would be a
#: different one. A feed whose entry is absent cannot trade - `FEEDS` below - and
#: absent is not zero.
HAR: dict[str, Har] = {
    "eurusd": Har(
        const=-0.993985, weights=(0.480183, 0.164227, 0.281414), scale=1.591974, until="2026-02-01"
    ),
    "usdjpy": Har(
        const=-1.051027, weights=(0.387861, 0.365304, 0.165887), scale=1.594576, until="2026-02-01"
    ),
    "gbpusd": Har(
        const=-1.055897, weights=(0.502547, 0.143602, 0.272333), scale=1.692497, until="2026-02-01"
    ),
    "usdcad": Har(
        const=-1.099654, weights=(0.445277, 0.168905, 0.300033), scale=1.619267, until="2026-02-01"
    ),
    "xauusd": Har(
        const=-0.908968, weights=(0.400155, 0.322289, 0.214609), scale=1.640173, until="2026-02-01"
    ),
}

#: The feeds this rule may run on: the five the specification names. Derived
#: from `HAR` rather than written twice, so the allowlist and the coefficient
#: table cannot disagree about which markets the rule has a model for -
#: `tests/test_vol_impulse.py` pins that the set is the five the rule names.
FEEDS: tuple[str, ...] = tuple(HAR)


@dataclass(frozen=True, slots=True)
class Event:
    """One impulse, with the state that let it through.

    `side` is the bar's own direction, which is also the trade's: step 3 is
    "trade the impulse's direction" and there is no other side in this rule.
    """

    side: Side
    #: The bar's close-to-close log return, signed.
    move: float
    #: The frozen HAR's forecast for this bar, made from bars before it.
    sigma: float
    #: `|move| / sigma`, so the trigger is `>= IMPULSE_MULT`.
    impulse: float
    #: The squeeze statistic for the last finished bin and its trailing rank.
    squeeze: float
    rank: float
    #: The four-day range and the four-hour ATR it was divided by, in price.
    span: float
    atr: float
    #: Bars since the fold started, counting this one.
    at: int
    #: The UTC hour this bar closed in, which is the hour the fill lands in
    #: except in its last minute.
    hour: int


@dataclass(slots=True)
class Fold:
    """The causal reading: a frozen HAR, four-hour bins, and the impulses.

    Fed one closed M15 bar at a time and never anything else, so everything it
    answers is a function of bars it has already been given. The two ways this
    rule could read the future are both shut here rather than asserted:

    * the HAR components are the bars **before** the one being judged, so a
      forecast never sees its own bar;
    * the squeeze is read off the last **finished** four-hour bin, and a bin
      finishes when a bar in a later bin arrives - so the bin the impulse is
      inside never contributes to the rank that admitted it.

    `tests/test_vol_impulse.py` runs every prefix of a series through this and
    requires the events in the first `n` bars to be the ones the full series
    produced, which is the property a fold that peeked would fail.
    """

    har: Har | None = None
    bins: int = SQUEEZE_BINS
    window: int = SQUEEZE_WINDOW
    share: float = SQUEEZE_SHARE
    atr_bins: int = SQUEEZE_ATR
    mult: float = IMPULSE_MULT
    #: False drops the squeeze gate and leaves the impulse alone, which is the
    #: null arm that decides whether the slow leg contributes anything. A
    #: switch on the production fold and not a copy in a harness, so the arm
    #: and the rule are the same detector.
    require_squeeze: bool = True
    #: True ranks the raw four-day range instead of the ATR-adjusted one - the
    #: second reading of the specification's "after adjusting for normal ATR".
    #: See `SQUEEZE_ATR`.
    raw_range: bool = False

    #: `|r|` for the last `max(HAR_LAGS)` bars, oldest first.
    moves: deque[float] = field(default_factory=deque)
    #: Finished four-hour bins as `(high, low, close)`, and the statistic each
    #: one produced. Two deques because the statistic needs `bins` of geometry
    #: and the rank needs `window` of statistics.
    slow: deque[tuple[float, float, float]] = field(default_factory=deque)
    stats: deque[float] = field(default_factory=deque)

    previous: float = 0.0
    #: The bin being filled: its id, high, low and close, and whether this bar
    #: is the first in it. The flag exists because `_finish` runs before the
    #: bar is judged and `_fill` after it, so the two need to agree about
    #: whether the bin was just started - and a high of zero is not a safe
    #: stand-in for "empty" on an instrument that can quote zero.
    bin_id: int = -1
    bin_high: float = 0.0
    bin_low: float = 0.0
    bin_close: float = 0.0
    bin_fresh: bool = True

    bars: int = 0
    #: Why a bar produced nothing, counted apart. A single `None` covering
    #: "unwarmed", "no squeeze" and "no impulse" is a scope bug nobody can tell
    #: from a quiet market, which `finding-edges` records as a defect that cost
    #: an afternoon three times over.
    counts: dict[str, int] = field(default_factory=dict)

    #: The branches `counts` keeps apart, in the order `_impulse` applies them.
    BRANCHES: ClassVar[tuple[str, ...]] = (
        "bars",
        "cold-return",
        "cold-har",
        "cold-squeeze",
        "no-impulse",
        "no-squeeze",
        "flat",
        "fired",
    )

    def __post_init__(self) -> None:
        if self.bins < 1 or self.window < 1:
            raise ValueError(f"a squeeze needs bins and a window, not {self.bins}/{self.window}")
        if not 0.0 < self.share <= 1.0:
            raise ValueError(f"the squeeze share is a quantile, not {self.share}")
        if self.mult <= 0.0:
            raise ValueError(f"an impulse is a multiple of the forecast, not {self.mult}")
        lags = HAR_LAGS if self.har is None else self.har.lags
        self.moves = deque(self.moves, maxlen=max(lags))
        self.slow = deque(self.slow, maxlen=max(self.bins, self.atr_bins + 1))
        self.stats = deque(self.stats, maxlen=self.window)
        for name in self.BRANCHES:
            self.counts.setdefault(name, 0)

    def update(self, ts: int, high: float, low: float, close: float) -> Event | None:
        """One closed M15 bar. The impulse it produced, or None.

        `ts` is the bar's close in whole seconds UTC, which is what the
        four-hour bin is cut on.
        """
        self.bars += 1
        self.counts["bars"] += 1
        self._finish(int(ts) // SLOW_SECONDS)
        found = self._impulse(ts, close)
        self._fill(high, low, close)
        self.previous = close
        return found

    # ------------------------------------------------------------- the slow leg

    def _finish(self, bin_id: int) -> None:
        """Close the four-hour bin this bar has left, and score it.

        Called **before** the bar is judged, so the statistic the impulse reads
        belongs to a bin that ended before this bar opened; and before the bar
        is folded in, so the bar cannot contribute to the bin that admits it.
        """
        if self.bin_id < 0:
            self.bin_id = bin_id
            self.bin_fresh = True
            return
        if bin_id == self.bin_id:
            return
        self.slow.append((self.bin_high, self.bin_low, self.bin_close))
        self.bin_id = bin_id
        self.bin_fresh = True
        if len(self.slow) < max(self.bins, self.atr_bins + 1):
            return
        span = self._span()
        if self.raw_range:
            self.stats.append(span)
            return
        atr = self._atr()
        if atr > 0.0:
            self.stats.append(span / atr)

    def _span(self) -> float:
        """The range of the last `bins` finished four-hour bins, in price."""
        rows = list(self.slow)[-self.bins :]
        return max(high for high, _, _ in rows) - min(low for _, low, _ in rows)

    def _atr(self) -> float:
        """The mean true range over the last `atr_bins` finished bins.

        A simple mean rather than Wilder's smoothing: the window is what the
        rule names, and a smoothed average is a different lookback wearing the
        same number.
        """
        rows = list(self.slow)[-(self.atr_bins + 1) :]
        if len(rows) < 2:
            return 0.0
        total = 0.0
        for index in range(1, len(rows)):
            high, low, _ = rows[index]
            previous = rows[index - 1][2]
            total += max(high - low, abs(high - previous), abs(low - previous))
        return total / (len(rows) - 1)

    def _fill(self, high: float, low: float, close: float) -> None:
        """Fold this bar into the bin it belongs to."""
        if self.bin_fresh:
            self.bin_high, self.bin_low = high, low
            self.bin_fresh = False
        else:
            self.bin_high = max(self.bin_high, high)
            self.bin_low = min(self.bin_low, low)
        self.bin_close = close

    # -------------------------------------------------------------- the impulse

    def _impulse(self, ts: int, close: float) -> Event | None:
        """This bar's impulse, if it is one and the state admits it.

        The gates are applied in the order `BRANCHES` lists them, so
        `bars - cold-return - cold-har - cold-squeeze` is the number of bars
        the rule was actually able to judge - the denominator of a firing rate.
        An order that refused an impulse before saying the window was cold
        would make that denominator unrecoverable.
        """
        if self.previous <= 0.0 or close <= 0.0:
            self.counts["cold-return"] += 1
            return None
        move = math.log(close) - math.log(self.previous)
        parts = self._parts()
        self.moves.append(abs(move))
        sigma = self.har.forecast(parts) if self.har is not None and parts else 0.0
        if sigma <= 0.0:
            self.counts["cold-har"] += 1
            return None
        if len(self.stats) < self.window:
            self.counts["cold-squeeze"] += 1
            return None
        impulse = abs(move) / sigma
        if impulse < self.mult:
            self.counts["no-impulse"] += 1
            return None
        stat = self.stats[-1]
        rank = sum(1 for value in self.stats if value <= stat) / len(self.stats)
        if self.require_squeeze and rank > self.share:
            self.counts["no-squeeze"] += 1
            return None
        if move == 0.0:
            # Unreachable while the trigger is positive, and kept because the
            # trigger is a field: a `mult` of zero would otherwise take a side
            # on a bar that expressed none.
            self.counts["flat"] += 1
            return None
        self.counts["fired"] += 1
        return Event(
            side=Side.BUY if move > 0.0 else Side.SELL,
            move=move,
            sigma=sigma,
            impulse=impulse,
            squeeze=stat,
            rank=rank,
            span=self._span(),
            atr=self._atr(),
            at=self.bars,
            hour=(int(ts) // 3_600) % 24,
        )

    def _parts(self) -> tuple[float, ...]:
        """The HAR components: mean `|r|` over each lag, **excluding** this bar.

        Empty where the longest lag is not yet filled. The deque holds the bars
        before this one because `_impulse` reads it before appending.
        """
        lags = self.har.lags if self.har is not None else HAR_LAGS
        if len(self.moves) < max(lags):
            return ()
        rows = list(self.moves)
        return tuple(sum(rows[-lag:]) / lag for lag in lags)


@dataclass(slots=True)
class Closed:
    """One finished trade, as this rule's own record of it.

    Kept because the question a port has to answer is *what did the engine do*
    - how many ran out of clock and what each was worth in R - and a position
    in the cache carries the money without the budget it was sized against.

    `risk_px` is the trigger distance, `3.0 * sigma * price`, which is this
    rule's 1R; `spread_px` is the quote at the decision. The cost of a trade in
    R is the second over the first and nothing else, so recording both is what
    lets that be read off a run rather than guessed from the mean.
    """

    feed: str
    side: Side
    reward: float
    money: float
    risk_money: float
    how: str
    opened: float
    closed: float
    risk_px: float = 0.0
    spread_px: float = 0.0


class VolImpulseProfile(Profile):
    """The numbers the rule names, and nothing it does not."""

    name: ClassVar[str] = "vol-impulse"
    description: ClassVar[str] = "VI_M15_imp_H4sq"
    #: Its own shape, so a statespace proposal on the shared topic is skipped
    #: rather than judged - this rule reads bars and nothing else.
    shape: ClassVar[str] = "vol-impulse"
    #: Four hours on a 15-minute trigger is a swing by `Profile.style`'s own
    #: test - "a swing either holds an hour or more" - whatever the trigger's
    #: clock suggests.
    style: ClassVar[str] = "swing"
    #: The clock the signal is read on. Stated so a desk built on another one
    #: is visible rather than quietly measuring a different rule.
    interval: ClassVar[str] = "15m"
    #: Signal-clock bars the trade is held. **A bar count and not
    #: `hold_seconds`**: the two differ by whatever the feed's gaps are worth,
    #: and `structure.py` records three FX exits that landed on the Sunday
    #: reopen quote because a seconds deadline fell inside a weekend.
    hold_signal_bars: ClassVar[int] = HOLD_BARS
    hold_bars: ClassVar[float] = float(HOLD_BARS)
    #: Bars of history to fold before trading, and **not a tuning knob**: the
    #: rank needs 750 finished four-hour bins, which is 12,000 M15 bars. See
    #: the module docstring on what a shorter catalogue produces.
    warm_bars_request: ClassVar[int] = 12_100
    #: The squeeze, the impulse and the hold, from the module's constants so
    #: that a profile and a fold cannot disagree about the rule.
    squeeze_bins: ClassVar[int] = SQUEEZE_BINS
    squeeze_window: ClassVar[int] = SQUEEZE_WINDOW
    squeeze_share: ClassVar[float] = SQUEEZE_SHARE
    squeeze_atr: ClassVar[int] = SQUEEZE_ATR
    impulse_mult: ClassVar[float] = IMPULSE_MULT
    #: False is the null arm, not a setting a deploy should reach for. See
    #: `Fold.require_squeeze`.
    require_squeeze: ClassVar[bool] = True
    raw_range: ClassVar[bool] = False
    #: **No protective order.** Step 4 is "exit on time only", so `Intent.stop`
    #: here is a *sizing distance* - the trigger, which is 1R - and nothing is
    #: sent to the venue to defend it. A stop placed at 1R would be a different
    #: rule with a different hit rate, and it would be the better-looking one.
    protective_stop: ClassVar[bool] = False
    #: UTC hours in which no fill is taken, read off the signal bar's close
    #: stamp - the same hour as the fill except in its last minute.
    #:
    #: The rule says "no entries 19:00-23:00 UTC", which is read here as the
    #: half-open window `[19:00, 23:00)`: four hours, not five.
    #: `structure.py`'s own cut is `(19, 20, 21, 22, 23)` and the difference is
    #: one constant; the measurement reports the firing rate under both.
    no_fill_hours: ClassVar[tuple[int, ...]] = (19, 20, 21, 22)
    #: The share of 1R a round trip may cost before the trade is not one.
    #:
    #: `domain/costs.MAX_SPREAD_RISK_FRACTION` is 0.16 of the risk and is the
    #: desk's one measured cost limit, so it is used unchanged rather than a
    #: number invented here. On this rule the risk *is* the trigger, so the
    #: gate reads "a round trip may not exceed 16% of one impulse".
    cost_share: ClassVar[float] = costs.MAX_SPREAD_RISK_FRACTION
    #: The feeds the rule names. `FEEDS` and `HAR` are the same set by
    #: construction - a feed with no frozen model cannot trade, and absent is
    #: not zero.
    feeds: ClassVar[frozenset[str]] = frozenset(FEEDS)


class VolImpulse:
    """Trade a 15-minute impulse out of a four-hour squeeze, for four hours.

    A mixin with no base, composed with an entry from `entries.py` and an exit
    from `exits.py` - see `leaves.py`. Like `Structure` and unlike `Surprise`
    it reads **bars** rather than a published reading, so `on_bar` is where the
    signal is made; everything after that is the shared gate sequence in
    `Desk.consider`.
    """

    profile: ClassVar[VolImpulseProfile] = VolImpulseProfile.__new__(VolImpulseProfile)

    #: **The thesis is duration, so the stale rule does not apply.** The rule
    #: exists because a level touch resolves in eighteen seconds at the median,
    #: and that premise is false of a trade whose exit *is* a four-hour clock.
    stale: ClassVar[bool] = False

    # ----------------------------------------------------------- the lifecycle

    def on_start(self) -> None:
        """Build the fold for this feed's frozen model, then start the desk.

        A feed with no entry in `HAR` gets a fold with no model, which can
        never fire. Said out loud here rather than refused, for the reason
        `Surprise.on_start` gives: a rule that is not allowed on its feed and a
        feed that is quiet read identically in a log, and on 2026-11-07
        twenty-six of thirty-two desks were inert by construction with nothing
        saying so.
        """
        feed = self._feed_name()
        self.fold = Fold(
            har=HAR.get(feed),
            bins=self.profile.squeeze_bins,
            window=self.profile.squeeze_window,
            share=self.profile.squeeze_share,
            atr_bins=self.profile.squeeze_atr,
            mult=self.profile.impulse_mult,
            require_squeeze=self.profile.require_squeeze,
            raw_range=self.profile.raw_range,
        )
        #: The signal-bar index a position opened on, for the bar clock. Here
        #: rather than on `Held` because the clock is this rule's own: a bar
        #: count is not a duration and `Exits._expired` reads seconds.
        self.opened_on: dict[Any, int] = {}
        #: Finished trades, in the order they closed.
        self.closed: list[Closed] = []
        #: Bars folded from requested history, counted apart from live ones: a
        #: fold warmed by replay and a fold filled by the market are different
        #: states and a trade count of zero does not tell them apart.
        self.warmed: dict[str, int] = {"bars": 0, "fired": 0}
        super().on_start()
        if feed not in self.profile.feeds or HAR.get(feed) is None:
            self.log.warning(
                f"{self.profile.description} has no frozen HAR for {feed}; this desk "
                f"can never fire. Modelled: {sorted(self.profile.feeds)}"
            )
        if not str(self._cfg.bar_type.spec).startswith("15-MINUTE"):
            # Said out loud rather than refused: a sweep may deliberately run
            # the rule on another clock, and a deploy that did so by accident
            # is the failure this names - the HAR's lags are 1, 16 and 96 bars
            # of whatever this clock is, and the hold is 16 of them.
            self.log.error(
                f"{self.profile.description} is an M15 rule and this desk is on "
                f"{self._cfg.bar_type}: every lag and the hold are in bars of that clock."
            )
        if self.profile.warm_bars_request <= 0:
            return
        span = timedelta(seconds=self._bar_seconds() * self.profile.warm_bars_request)
        start = self.clock.utc_now() - span
        # **A composite bar type cannot be requested.** Nautilus refuses
        # `request_bars` for one outright and this rule is configured both
        # ways: a live desk runs the standard external M15, a backtest
        # aggregates M15 from an M1 feed.
        if self._cfg.bar_type.is_composite():
            self.request_aggregated_bars(
                [self._cfg.bar_type],
                start,
                limit=self.profile.warm_bars_request,
                include_external_data=False,
            )
        else:
            self.request_bars(self._cfg.bar_type, start, limit=self.profile.warm_bars_request)

    def _bar_seconds(self) -> float:
        """This bar type's interval in seconds, for the warm request's span."""
        spec = self._cfg.bar_type.spec
        step = float(spec.step)
        unit = str(spec.aggregation)
        if "SECOND" in unit:
            return step
        if "MINUTE" in unit:
            return step * 60.0
        if "HOUR" in unit:
            return step * 3_600.0
        if "DAY" in unit:
            return step * 86_400.0
        return step * 900.0

    def _tally_extra(self) -> str:
        """The fold's state on the desk's tally line.

        **A trade count of zero cannot tell "no setups" from "no window
        yet".** This rule needs 750 finished four-hour bins before it can rank
        anything, which is 125 days of bars, so the number that reads a cold
        fold at a glance is the one worth a line.
        """
        counts = self.fold.counts
        return (
            f" bars={counts['bars']}"
            f" warm={self.warmed['bars']}"
            f" bins={len(self.fold.stats)}/{self.profile.squeeze_window}"
            f" impulses={counts['no-squeeze'] + counts['fired']}"
            f" fired={counts['fired'] - self.warmed['fired']}+{self.warmed['fired']}w"
        )

    def on_historical_data(self, data: Any) -> None:
        """Fold requested history, which warms and never acts.

        **The fold advances; `on_data` is not called.** An impulse on a bar
        hours old names a price that has gone, so a warm firing is counted and
        nothing is proposed.
        """
        rows = data if isinstance(data, list | tuple) else [data]
        for row in rows:
            if not isinstance(row, Bar):
                continue
            self.warmed["bars"] += 1
            found = self.fold.update(
                int(row.ts_event // 1_000_000_000),
                float(row.high),
                float(row.low),
                float(row.close),
            )
            if found is not None:
                self.warmed["fired"] += 1

    def on_bar(self, bar: Bar) -> None:
        """One closed M15 bar through the fold, and any impulse it produced.

        **Called with closed bars only.** Nautilus delivers an aggregated bar
        when the interval ends, so the close this reads is final; a partial bar
        would be a forecast of its own bar.
        """
        super().on_bar(bar)
        self._clock()
        found = self.fold.update(
            int(bar.ts_event // 1_000_000_000), float(bar.high), float(bar.low), float(bar.close)
        )
        if found is None:
            return
        # Through `on_data` and not `consider` directly, because that is where
        # the desk counts what it took, places it, and follows what it
        # declined. A dict is one of the two shapes it accepts.
        self.on_data(self._payload(found, bar))

    def _clock(self) -> None:
        """Close anything that has run out of bars.

        **Step 4, as a bar count.** Run before the fold's own event so the slot
        a closing trade holds is free for an impulse on this bar, which is what
        a greedy one-position rule does - and which is the only way the
        measurement's non-overlap and the desk's agree.
        """
        due = self.profile.hold_signal_bars
        if due <= 0:
            return
        for position_id, opened in list(self.opened_on.items()):
            held = self.fold.bars - opened
            if held < due:
                continue
            if self._close(position_id, f"held {held} bars and its rule allows {due}"):
                self._count("(exit):closed")

    def on_position_opened(self, event: Any) -> None:
        """Stamp the bar the position opened on, for `_clock`."""
        self.opened_on[event.position_id] = self.fold.bars
        super().on_position_opened(event)

    def _payload(self, found: Event, bar: Bar) -> dict[str, Any]:
        """The impulse as the payload `Desk.consider` reads.

        Handed straight to `on_data` rather than published on `PROPOSALS`: the
        bus would deliver this reading to every other desk subscribed to that
        topic, each of which would count it as unwanted.
        """
        return {
            "feed": self._feed_name(),
            "shape": self.profile.shape,
            "interval": self.profile.interval,
            "direction": found.side.sign,
            "features": {
                # Named for the rule, so a later score can find them, and
                # **not** named `vol_bps`: that column is a folded log variance
                # elsewhere on this desk and a HAR forecast of a log return in
                # it would put one journal column in two units.
                "vi_sigma": found.sigma,
                "vi_impulse": found.impulse,
                "vi_move": found.move,
                "vi_rank": found.rank,
                "vi_squeeze": found.squeeze,
                "vi_span": found.span,
                "vi_atr": found.atr,
                "vi_close": float(bar.close),
                "vi_hour": float(found.hour),
            },
        }

    # ------------------------------------------------------------ the decision

    def wants(self, payload: dict[str, Any]) -> bool:
        """Its own readings, on a feed it has a model for.

        The feed is checked as well as the shape because `TRADING_SYMBOLS` is
        global: naming the rule would otherwise put it on every instrument the
        node carries, and a fold with no frozen HAR would sit there firing
        nothing while looking like a quiet market.
        """
        if str(payload.get("shape") or "") != self.profile.shape:
            return False
        return str(payload.get("feed") or "").lower() in self.profile.feeds

    def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """A trade, or the reason there is not one. Never raises on a payload.

        There is no threshold of this module's invention: the squeeze and the
        impulse both happened in the fold. What is left is the hour cut, the
        cost, and the geometry - which for this rule is one distance.
        """
        feed = str(payload.get("feed") or "")
        tick = self._tick()
        if tick is None:
            # `Desk.consider` has already refused a missing quote, so this is a
            # second line rather than the only one.
            return Refusal(gate="no-quote", detail=f"no quote for {feed}", feed=feed)

        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal(gate="features", detail="no features on the proposal", feed=feed)

        side_raw = int(_number(payload.get("direction")))
        if side_raw == 0:
            return Refusal(gate="direction", detail="the bar took no side", feed=feed)
        side = Side.BUY if side_raw > 0 else Side.SELL

        hour = int(_number(features.get("vi_hour")))
        if hour in self.profile.no_fill_hours:
            # Refused here and not in the fold, so the impulse is still
            # counted: a cut trade must not read as a market that was quiet.
            return Refusal(gate="cut-off", detail=f"no fill at {hour:02d} UTC", feed=feed)

        entry = tick.ask if side is Side.BUY else tick.bid
        if entry <= 0.0:
            return Refusal(gate="bad-quote", detail=f"{feed} quoted {entry}", feed=feed)

        # 1R is the trigger: `impulse_mult` forecast units, as a price distance
        # at the fill. `vi_sigma` is a log return, so the distance is
        # `sigma * price` - and nothing here reads the per-bar `spread` column,
        # whose conversion is a measured 476% error and which is zero on 7-35%
        # of bars.
        sigma = _number(features.get("vi_sigma"))
        risk = self.profile.impulse_mult * sigma * entry
        if risk <= 0.0:
            return Refusal(gate="volatility", detail=f"sigma {sigma:.3g}", feed=feed)

        cost = tick.ask - tick.bid
        if dear := costs.too_expensive(cost, risk, self.profile.cost_share):
            return Refusal(gate="spread_risk", detail=dear, feed=feed)

        return Intent(
            feed=feed,
            symbol=self._cfg.instrument_id.symbol.value,
            side=side,
            # Zero: `Desk.consider` sizes it. Two places computing a size is
            # how they come to disagree.
            volume=0.0,
            entry=entry,
            # **A sizing distance, not a stop**: `protective_stop` is False, so
            # no order defends it and `risk_money` is the budget one impulse of
            # adverse movement would spend. That is what makes `money /
            # risk_money` R in the unit the rule states.
            stop=entry - side.sign * risk,
            # **No target, which is the rule.** A target invented here would be
            # a different rule with better arithmetic.
            target=0.0,
            reason=(
                f"impulse {_number(features.get('vi_impulse')):.2f}x "
                f"{'up' if side is Side.BUY else 'down'} out of a squeeze at "
                f"rank {_number(features.get('vi_rank')):.3f} on {feed}"
            ),
            interval=self.profile.interval,
            features={k: _number(v) for k, v in features.items()}
            | {"vi_risk_px": risk, "vi_spread_px": cost},
            # Step 4 is `hold_signal_bars` and `_clock` runs it, so no seconds
            # hold: the two would race and the seconds one wins across a
            # session gap.
            hold=0.0 if self.profile.hold_signal_bars > 0 else self.profile.hold_seconds,
        )

    # -------------------------------------------------------------- the record

    def on_position_closed(self, event: Any) -> None:
        """Record what the trade was worth before the exit book forgets it.

        Read here rather than from the cache afterwards because R needs the
        budget the trade was *sized* against, and that lives on the intent:
        `ExitMechanism.on_position_closed` pops it, so this has to run first.
        """
        self.opened_on.pop(event.position_id, None)
        held = self.exits.held(event.position_id)
        position = self.cache.position(event.position_id)
        if held is not None and position is not None:
            money = float(position.realized_pnl) if position.realized_pnl is not None else 0.0
            risk = float(held.intent.risk_money or 0.0)
            self.closed.append(
                Closed(
                    feed=held.intent.feed,
                    side=held.intent.side,
                    # Zero risk money cannot happen on a sized intent, and a
                    # division that invented an R would be worse than a zero.
                    reward=money / risk if risk > 0.0 else 0.0,
                    money=money,
                    risk_money=risk,
                    # Nothing but the clock closes this rule. A `stop` here
                    # would mean a protective order reached the venue, which
                    # `protective_stop` says it must not.
                    how="clock" if held.closing else "other",
                    opened=held.opened,
                    closed=self.clock.timestamp(),
                    risk_px=_number(held.intent.features.get("vi_risk_px")),
                    spread_px=_number(held.intent.features.get("vi_spread_px")),
                )
            )
        super().on_position_closed(event)


class VolImpulseEdge(VolImpulse, ManagedExit, EdgeEntry):
    """The impulse, taken at market. The only pairing the rule names.

    Step 3 is "at the next 1-minute open", so a resting limit or a wait for an
    arrival would be a different rule - which is why `leaves.py` lists this
    rule for the edge entry and for nothing else, and `desks.build` refuses the
    others by name rather than skipping them.
    """
