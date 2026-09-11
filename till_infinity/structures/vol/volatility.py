"""How much this instrument moves, right now.

Everything about levels is measured in volatility units rather than price
units, and that is not a stylistic choice. A level held to within 5bps is
remarkable in a calm hour and meaningless in a violent one; a zone 20bps wide
is a hairline on gold in a crisis and a canyon on EURUSD overnight. Fixed
thresholds encode one market regime and quietly stop describing the next.

So this module is small and load-bearing. It produces one number per
instrument - the typical size of a move - and the rest of the package divides
by it.

Exponentially weighted rather than a rolling window, because a window has an
edge: a violent bar leaves the average abruptly N bars later, and a level's
zone would jump for no reason anyone could point at. An EW estimator forgets
smoothly, which is what "recent" actually means.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from river import stats

from ..state import Restorable
from .consensus_vol import MAD_TO_SIGMA, Ensemble
from .garch import Garch
from .har import Har
from .implied import ENABLED, IMPLIED_FEEDS, IMPLIED_INTERVALS, Fit, Implied, seeds
from .learned import Learned
from .ranges import Ranges

#: Bars of history before the estimate is trusted. Below this the variance of
#: the variance is larger than anything it would be used to decide.
WARMUP = 20

#: Half-life in bars. About an hour of 1m bars: long enough to survive a single
#: spike, short enough to notice a regime that has actually changed.
HALF_LIFE = 60.0

#: A floor, in basis points. Without one, an instrument that has not moved for
#: an hour gets a near-zero volatility and every subsequent tick looks like a
#: hundred-sigma event - division by something approaching zero.
#:
#: **Raised from 0.05 on 2026-08-28, on measurement.** Across live decisions
#: the lowest volatility ever seen was 0.517 bps and the median 2.47, so 0.05
#: sat an order of magnitude below anything real and did not prevent what it
#: was written to prevent: at that floor a normal brent move came out at
#: 10,229 volatility units. Half the observed minimum is high enough to bound
#: the arithmetic and low enough never to bind on an instrument that is
#: actually trading.
#:
#: The floor is the second line. `ready` is the first - a cold estimate should
#: not be used at all, rather than used with a safer denominator.
MIN_VOL_BPS = 0.25

#: Observations before the tick estimate is trusted. The minimum of three
#: samples is not a minimum.
TICK_WARMUP = 30

#: Where in the distribution of price changes the grid step is read off.
#:
#: Not the minimum, which is what this used to be. Both give the same answer on
#: clean data - identical on all eight instruments tested - but the minimum is
#: a one-observation estimator and behaves like one: a single spurious print a
#: seventh the size of a real tick collapsed it on **every** instrument, 0.01
#: to 0.0014, and that number widens a zone. The first percentile did not move
#: on any of them.
#:
#: An approximate GCD was tried too, on the grounds that the tick divides every
#: change. It matched on seven instruments, went degenerate on btc (0.000064,
#: which trivially divides everything) and collapsed under the same outlier.
TICK_QUANTILE = 0.01

#: Changes remembered for that quantile. Enough to place a percentile, few
#: enough to follow a re-tiering rather than the year.
TICK_WINDOW = 500

#: Distinct multiples of the smallest change that must be seen before the
#: estimate is believed to be a grid step at all.
#:
#: This is the discriminator, and the obvious one does not work. "The smallest
#: move must be small against a typical move" sounds right and rejects exactly
#: the instruments that need this most: on ADA the tick genuinely *is* most of
#: a typical move, which is the whole problem, so that test throws away the
#: worst case as if it were the degenerate one.
#:
#: What separates them is the spread of multiples. Price on a real grid moves
#: one step, then two, then five - many distinct multiples of the same base.
#: A series that only ever moves by one identical amount has not resolved a
#: grid at all; it has jumped, and its jump is not a tick.
TICK_MULTIPLES = 3

#: Readings kept for the regime percentile. Roughly a day of 1m bars: long
#: enough that "high for this instrument" means something, short enough that it
#: still describes the market you are in rather than the one from last month.
REGIME_WINDOW = 1_500

#: Percentiles tracked. The pair brackets "normal", so a reading outside them is
#: outside what this instrument has recently been doing.
REGIME_LOW, REGIME_HIGH = 0.15, 0.85


def _alpha(half_life: float) -> float:
    return 1.0 - math.exp(math.log(0.5) / max(half_life, 1.0))


@dataclass(slots=True)
class Volatility(Restorable):
    """Exponentially weighted volatility of returns, in basis points.

    Tracks the mean absolute return rather than the standard deviation: the
    question asked of it is "how big is a normal move", and for fat-tailed
    financial returns the mean absolute deviation answers that more stably
    than a variance a single outlier can dominate.
    """

    half_life: float = HALF_LIFE
    floor_bps: float = MIN_VOL_BPS
    warmup: int = WARMUP
    _mean_abs: float = 0.0
    _last: float = 0.0
    _seen: int = 0
    #: Rolling quantiles of the estimate itself. A number is not interpretable
    #: on its own - "25bps" says nothing without knowing what this instrument
    #: usually does - so the percentile is tracked alongside it.
    _low: stats.RollingQuantile = field(
        default_factory=lambda: stats.RollingQuantile(q=REGIME_LOW, window_size=REGIME_WINDOW)
    )
    _high: stats.RollingQuantile = field(
        default_factory=lambda: stats.RollingQuantile(q=REGIME_HIGH, window_size=REGIME_WINDOW)
    )
    _history: list[float] = field(default_factory=list)
    #: The smallest non-zero price change seen - the venue's tick, measured
    #: rather than configured. See `tick`.
    _tick: float = 0.0
    #: Distinct multiples of `_tick` observed, which is what tells a grid from
    #: a series that happens to move in equal jumps. Bounded: past a handful
    #: the answer does not change.
    _steps: set[int] = field(default_factory=set)
    #: The estimate itself: a low quantile of the changes rather than their
    #: minimum, so one bad print cannot move it. See `TICK_QUANTILE`.
    _grid: stats.RollingQuantile = field(
        default_factory=lambda: stats.RollingQuantile(q=TICK_QUANTILE, window_size=TICK_WINDOW)
    )
    #: The same series, read by a model that has somewhere to return to.
    #:
    #: **Additional, not a replacement.** `bps` is unchanged and every
    #: threshold in this package still divides by it. This is fed the same
    #: prices and kept alongside so the two can be recorded against outcomes
    #: and compared - given how much depends on this number, swapping it on the
    #: strength of the reasoning would be the mistake this repository keeps
    #: writing down. See `garch.py` for what it adds and why it is written on
    #: absolute returns rather than squared ones.
    _garch: Garch = field(default_factory=Garch)
    #: The same instrument read from whole bars rather than closes. Fed only
    #: from `observe_bar`, so it is coarser in time than the rest of this class
    #: and a fair comparison has to be made per bar rather than per update.
    #:
    #: **Not on the same scale as `bps`.** This class tracks a mean absolute
    #: deviation; the range estimators produce a standard deviation, and for a
    #: normal the two differ by a factor of sqrt(2/pi). Anything combining them
    #: has to reconcile that first - see `ranges.py`.
    _ranges: Ranges = field(default_factory=Ranges)
    #: A forecast rather than an estimate - what the next bar is expected to
    #: do, rather than what the last ones did. Fed the per-bar realised value
    #: from `_ranges`, so it inherits the whole-bar reading rather than the
    #: close-to-close one. Excluded from persistence: see `Har`.
    _har: Har = field(default_factory=Har)
    #: The four readings on one scale, scored against what each bar actually
    #: did, and combined equally. Used by nothing - see `consensus_vol.py`.
    _ensemble: Ensemble = field(default_factory=Ensemble)

    # `__setstate__` comes from `Restorable`, which fills in fields a saved
    # state predates. This class is why that exists: `_tick`, `_steps` and
    # `_grid` were added, the restore raised on the first quote, and the
    # throw landed inside the structures consumer - so the container stayed
    # healthy and simply stopped producing for four hours. See state.py.

    @property
    def tick(self) -> float:
        """The smallest price change this instrument has been seen to make.

        Every price on a venue sits on a grid and every change is a multiple of
        its step, so the smallest non-zero change observed *is* the step - once
        enough have gone past for the smallest to be a single step rather than
        the smallest jump that happened to occur. Measured rather than
        configured, because the tick table belongs to the venue and changes
        without notice, and because `structures` has no other route to it:
        `prices` sees the quotes and does not pass this on.

        **Zero unless the series has actually demonstrated a grid**, and the
        two guards matter more than the estimate.

        A series that only ever moves by one identical amount says nothing
        about the step: "the tick is that size" and "the tick is tiny and price
        is jumping" fit the data equally well, and taking the first would widen
        every zone on the instrument by that jump. So the estimate is withheld
        until price has been seen to move by several *different* multiples of
        it - one step, then two, then five - which is what a grid being
        resolved looks like and what a uniform jump never produces. See
        `TICK_MULTIPLES`, and note that the tempting test - "the tick should be
        small against a typical move" - rejects ADA, the instrument this exists
        for.

        It is also withheld until `TICK_WARMUP` observations, because the
        minimum of three samples is not a minimum.

        **The estimate is only ever an upper bound.** It is the smallest change
        that has *happened*, not the smallest that is possible, so an
        instrument whose prints are all several steps apart reads as coarser
        than it is. The error is always in that direction and it shrinks with
        data, never growing - but a consumer should bound what it does with the
        number rather than trust it early. `Level.zone` clamps it at
        `MAX_ZONE_VOL` for exactly this reason.

        Both failures return zero, so anything built on this falls back rather
        than inventing a number, and the estimate can only shrink with more
        data - biasing it towards the old behaviour rather than towards a
        spuriously wide band. That is the safe direction for a value whose job
        is to widen one.
        """
        if not self._tick or self._seen < TICK_WARMUP:
            return 0.0
        if len(self._steps) < TICK_MULTIPLES:
            return 0.0
        # The minimum decides *whether* there is a grid; the quantile decides
        # how wide it is. Separating them is what makes one bad print harmless:
        # it drags the minimum down, which only loosens the guard, while the
        # quantile it would have to move is defended by every other change.
        return float(self._grid.get() or self._tick)

    def update(self, price: float) -> float:
        """Take one price, return the current volatility estimate in bps."""
        if price <= 0:
            return self.bps
        if not self._last:
            self._last = price
            return self.bps
        step = abs(price - self._last)
        if step:
            if not self._tick or step < self._tick:
                # A smaller step rewrites the base, so what was counted as a
                # multiple of the old one says nothing about the new.
                self._tick = step
                self._steps = {1}
            elif len(self._steps) < 16:
                self._steps.add(round(step / self._tick))
            self._grid.update(step)
        move = step / self._last * 10_000
        self._last = price
        self._seen += 1
        alpha = _alpha(self.half_life)
        self._mean_abs = (
            move if self._seen == 1 else self._mean_abs + alpha * (move - self._mean_abs)
        )
        # Same input, second opinion. Cheap: three multiplications.
        self._garch.update(price)
        current = self.bps
        self._low.update(current)
        self._high.update(current)
        self._history.append(current)
        if len(self._history) > REGIME_WINDOW:
            del self._history[: len(self._history) - REGIME_WINDOW]
        return current

    @property
    def bps(self) -> float:
        return max(self._mean_abs, self.floor_bps)

    def observe_bar(
        self,
        open_: float,
        high: float,
        low: float,
        close: float,
        implied_bps: float | None = None,
    ) -> float:
        """Fold one whole bar into the range estimates. Closes go to `update`.

        Returns **this bar's own realised volatility** in bps - the number the
        ensemble scores every member against. Returned rather than recomputed
        by the caller so a second consumer cannot end up scoring against a
        subtly different target: `learned.py` is judged on the same bar, by the
        same measure, as `garch`, `range` and `har` are.
        """
        self._ranges.observe(open_, high, low, close)
        # One bar's own realised reading, not the windowed one: the forecaster
        # builds its own horizons and feeding it a smoothed series would give
        # it three averages of an average.
        single = Ranges(window=1, warmup=1)
        single.observe(open_, high, low, close)
        realised = single.rogers_satchell_bps
        self._har.observe(realised)

        # Score what everything said about this bar *before* folding it in, so
        # each member is judged on the forecast it actually had to make. Doing
        # it after would score them against a number they had already seen.
        self._ensemble.settle(realised / MAD_TO_SIGMA)
        members = {
            "ew": self.bps,
            "garch": self._garch.bps,
            "range": self._ranges.bps,
            "har": self._har.predict(),
        }
        # **The one member that is not a function of the past.** Absent rather
        # than zero when it is stale or out of scope, because the ensemble takes
        # whatever mapping it is given and a zero would be scored as a forecast.
        if implied_bps is not None and implied_bps > 0:
            members["vix"] = implied_bps
        self._ensemble.observe(
            members,
            # The range family reports a standard deviation, and so does VIX;
            # `ew` and `garch` are on the mean-absolute convention already.
            sigma_scaled=frozenset({"range", "har", "vix"}),
        )
        return realised

    @property
    def ensemble_bps(self) -> float:
        """All four readings on one scale, combined. Zero until there are some."""
        return self._ensemble.bps

    def standings(self) -> list[tuple[str, float]]:
        """Which estimator has been closest, best first."""
        return self._ensemble.standings()

    @property
    def forecast_bps(self) -> float:
        """What the next bar is expected to do, in bps. Naive until warm."""
        return self._har.predict()

    @property
    def forecast_ratio(self) -> float:
        """Forecast over the last realised value. 1.0 when there is no view.

        **Where volatility is going, not where it is.** Above one the next bar
        is expected to be livelier than the last, whatever level either sits
        at. `stretch` below is the other question - the current scale against
        its own long-run level - and the two are near independent: log
        correlation **+0.033** over 32,362 published touches. An instrument can
        be at twice its usual volatility and expected to stay exactly there.

        Of the two, this is the one that predicts anything. See `stretch`.
        """
        return self._har.ratio

    @property
    def range_bps(self) -> float:
        """Yang-Zhang over the recent bars, in bps. Zero-ish until warm."""
        return self._ranges.bps

    @property
    def range_warm(self) -> bool:
        return self._ranges.warm

    @property
    def garch_bps(self) -> float:
        """The mean-reverting estimate of the same quantity, in bps."""
        return self._garch.bps

    @property
    def stretch(self) -> float:
        """How far the current scale sits above its own long-run level.

        1.0 when there is no view yet. Above 1 the instrument is livelier than
        it usually is and the model expects that to fade. The exponentially
        weighted estimate cannot express this at all, because it has no usual.

        **Published as `vol_stretch` and measured to predict nothing.** Across
        32,362 decisive touches on 14 days a level held 84.6 / 83.4 / 83.6 /
        83.4 / 84.0 percent across its quintiles - flat to within 1.2 points,
        no shape. `forecast_ratio` on the same touches spans 5.1 points in an
        inverted U. Being in a violent regime says little about whether a level
        holds; being about to *leave* the current one says a good deal.

        Kept and still published: a null that has been measured is worth more
        than an absence, and this is the field a reader reaches for first when
        they want "the regime". `research/clustering.md` records the run.
        """
        return self._garch.stretch

    @property
    def warm(self) -> bool:
        """Whether enough bars have been seen for `bps` to mean anything.

        `WARMUP` was declared with a docstring saying why it matters - below it
        "the variance of the variance is larger than anything it would be used
        to decide" - and this property was written to express it. **Nothing
        consulted either.** The constant, the field, the counter and this
        property all existed and no code joined them to a decision.

        What that cost: a cold estimate returns `floor_bps`, every distance in
        this package is a price divided by it, and at the old floor of 0.05 a
        four-and-a-half point move on brent became an expected push of **10,229
        volatility units**. It reached trading, produced a target forty-three
        times the price of the instrument, and the broker refused the order -
        which is the only reason anybody saw it. `Engine` now declines to
        publish a call from an estimate that is not warm.
        """
        return self._seen >= self.warmup

    @property
    def regime(self) -> float:
        """Where the current estimate sits in its own recent history, in [0, 1].

        This is the number that is actually interpretable. "Volatility is 25bps"
        says nothing without knowing what this instrument usually does; "at the
        92nd percentile of the last day" says it immediately, and says it in a
        form gold and BTC can share.

        Returns 0.5 before there is enough history to place anything.
        """
        if len(self._history) < self.warmup:
            return 0.5
        current = self.bps
        below = sum(1 for value in self._history if value < current)
        return below / len(self._history)

    @property
    def calm(self) -> bool:
        """Below what this instrument has recently been doing."""
        low = self._low.get()
        return bool(low) and self.bps < low

    @property
    def violent(self) -> bool:
        """Above it. The half of the band that usually matters."""
        high = self._high.get()
        return bool(high) and self.bps > high

    def units(self, distance_bps: float) -> float:
        """Express a distance in volatility units. The project's common currency."""
        return distance_bps / self.bps

    def price_units(self, price: float, multiple: float) -> float:
        """`multiple` volatility units, as a price distance at `price`."""
        return price * (self.bps * multiple) / 10_000


@dataclass(slots=True)
class Book(Restorable):
    """One volatility estimate per instrument **and timeframe**.

    Per timeframe, not merely per instrument, and that distinction is
    load-bearing. A typical 4h move on gold is tens of times a typical 5m move,
    so a single estimate - in practice dominated by whichever series updates
    most often - makes every threshold expressed in volatility units wrong for
    every timeframe but one.

    Concretely: with one estimate, gold's clustering tolerance came out at about
    $0.86 while the 4h window spanned seventy days over a $574 range. Swings at
    that scale essentially never clustered, so the higher timeframes produced
    almost no levels at all.

    An empty `interval` is the instrument's tick-level estimate, updated from
    quotes. That is the right denominator for cross-timeframe comparisons: it
    is the only one every level can be measured against on the same footing.
    """

    half_life: float = HALF_LIFE
    _by_key: dict[tuple[str, str], Volatility] = field(default_factory=dict)
    #: **One** learned forecaster for the whole book, not one per series.
    #: Everything about that choice - why it is legitimate, and why the box
    #: refuses the alternative - is in `learned.py`. It lives here rather than
    #: on `Volatility` because it is shared: a copy inside each of the ~424
    #: estimates would be persisted 424 times and would learn from a few
    #: hundred bars each instead of from all of them.
    _learned: Learned = field(default_factory=Learned)
    #: The options market's own forecast. One series for four feeds - see
    #: `implied.py` for why the matched indices are not needed.
    _implied: Implied = field(default_factory=Implied)
    #: `a + b * vix` per series. Per-key rather than pooled because the variance
    #: risk premium differs by index - raw VIX scores second on us100 and last
    #: on spx500, which is what a per-index bias looks like.
    _implied_fits: dict[tuple[str, str], Fit] = field(default_factory=dict)

    # `__setstate__` from `Restorable` too, and it matters more here: this
    # holds one estimate per instrument *and* timeframe, so one missing
    # field takes out every one of them at once.

    @property
    def implied(self) -> Implied:
        """The shared VIX reading. Lazily created for a state that predates it."""
        got = getattr(self, "_implied", None)
        if got is None:
            got = self._implied = Implied()
        return got

    def votes_implied(self, feed: str, interval: str) -> bool:
        """Whether VIX is a member here at all.

        Four feeds of fifty-three, at `1d` and `1w`. A property to assert rather
        than a convention to remember - see `implied.py` for why the scope is
        narrow on purpose.
        """
        return ENABLED and feed in IMPLIED_FEEDS and interval in IMPLIED_INTERVALS

    def implied_fit(self, feed: str, interval: str) -> Fit:
        """This series' own de-biasing coefficient."""
        key = (feed, interval)
        found = self._implied_fits.get(key)
        if found is None:
            found = self._implied_fits[key] = Fit()
        return found

    def implied_bps(self, feed: str, interval: str, now: float) -> float | None:
        """This bar's implied reading for one series, or None if it must not vote.

        **The fitted value, not the quote.** Measured over 20 years on all four
        indices, the raw quote loses to `har` on every one and scores *worse
        than predicting the mean* on four - R-squared -0.484 on spx500 daily.
        Fitted, it beats `har` on all eight series by +0.10 to +0.28 R-squared,
        and beats `har` combined with itself on all eight too. See `implied.py`.

        None until `MIN_FIT` bars have been seen, so the member is absent rather
        than guessing while its one parameter is still noise.
        """
        if not self.votes_implied(feed, interval):
            return None
        raw = self.implied.bps(interval, now)
        return self.implied_fit(feed, interval).predict(raw) if raw else None

    def seed_implied(self) -> int:
        """Give the implied member the scores and coefficient history measured.

        **Without this the member cannot speak for about a year.** `MIN_FIT` is
        250 observations and production gets one daily bar a day; `SCORE_WARMUP`
        is 60 more before its weight means anything. The seed is twenty years of
        public data, 6KB, shipped with the package.

        **Never overwrites what was learned live.** A seed applied on every
        restart would stop live observations accumulating past one container's
        lifetime - the fit would reset to its historical value every deploy, and
        on a day with ten deploys it would never learn anything at all. So a
        series whose fit already has more observations than the seed is left
        exactly as it is. Returns how many series were seeded.

        A seed is a **prior, not a floor**: `Score.record` decays toward what it
        is currently seeing and `Fit` accumulates on top, so live evidence that
        contradicts the seed wins - it just has to arrive first rather than
        wait a year to start.
        """
        seeded = 0
        for feed, intervals in seeds().items():
            for interval, part in intervals.items():
                if not self.votes_implied(feed, interval):
                    continue
                fit = self.implied_fit(feed, interval)
                numbers = part.get("fit") or {}
                if fit.n >= float(numbers.get("n") or 0):
                    continue  # live has already gone further than history
                for name in ("n", "sx", "sy", "sxx", "sxy"):
                    setattr(fit, name, float(numbers.get(name) or 0.0))
                ensemble = self.of(feed, interval)._ensemble
                for name, score in (part.get("scores") or {}).items():
                    ensemble.seed(
                        name, error=float(score.get("error", 1.0)), seen=float(score.get("seen", 0))
                    )
                seeded += 1
        return seeded

    def of(self, feed: str, interval: str = "") -> Volatility:
        key = (feed, interval)
        found = self._by_key.get(key)
        if found is None:
            found = self._by_key[key] = Volatility(
                half_life=self.half_life,
                _garch=Garch(half_life=self.half_life),
                _ranges=Ranges(),
                _har=Har(),
                # **Weighting only where VIX votes.** `Ensemble` is per
                # `(feed, interval)`, so a fifth member that should carry most
                # of the vote can earn it without changing how the other 49
                # instruments combine theirs. Equal weights are still the
                # default everywhere else, and the module note in
                # `consensus_vol` is still the reason.
                _ensemble=Ensemble(weighted=self.votes_implied(feed, interval)),
            )
        return found

    def observe_bar(
        self,
        feed: str,
        interval: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        when: float,
    ) -> float:
        """One bar for one series, with the implied member supplied if it votes."""
        series = self.of(feed, interval)
        realised = series.observe_bar(
            open_, high, low, close, implied_bps=self.implied_bps(feed, interval, when)
        )
        # **After the forecast, never before it.** The fit learns from this bar
        # only once the bar has been scored against it, which is the same rule
        # `Ensemble.settle` follows and for the same reason.
        if self.votes_implied(feed, interval):
            raw = self.implied.bps(interval, when)
            if raw:
                self.implied_fit(feed, interval).observe(raw, realised)
        return realised

    def update(self, feed: str, price: float, interval: str = "") -> float:
        return self.of(feed, interval).update(price)

    @property
    def learned(self) -> Learned:
        """The shared forecaster. Lazily created for a state that predates it.

        `Restorable.__setstate__` defaults a field a save predates, but this is
        reached from `learn` on the first bar after a deploy and a `None` there
        would be an `AttributeError` inside the structures consumer - which is
        precisely the failure that stopped this service for four hours and then
        again for eleven. Cheap guard, expensive absence.
        """
        found = getattr(self, "_learned", None)
        if found is None:
            found = self._learned = Learned()
        return found

    def learn(
        self,
        feed: str,
        interval: str,
        realised_bps: float,
        *,
        open_: float,
        high: float,
        low: float,
        close: float,
        hour: float = -1.0,
        weekday: float = -1.0,
        hour_share: float = 1.0,
        volume: float = 0.0,
        focus_nats: float = 0.0,
        changed: bool = False,
        interval_seconds: float = 0.0,
    ) -> None:
        """Fold one closed bar into the shared forecaster.

        Split from `Volatility.observe_bar` rather than called inside it,
        because the leading features live outside this package: the hour's
        volatility share comes from `context/sessions`, the changepoint
        evidence from `learning/focus`, and the volume from the bar payload.
        A per-series estimate has no route to any of them, and passing three
        collaborators into `Volatility` to get them there would put the whole
        engine inside an object that measures one number.

        Order is the part worth getting right, and it is the reverse of what
        reads naturally: the row is built from the state **before** this bar,
        handed to `observe` along with what the bar did, and only then does the
        state advance. Building the row first from updated state would give the
        model a feature set containing its own answer.
        """
        vol = self.of(feed, interval)
        if realised_bps <= 0 or not vol.warm:
            return
        # **Converted once, here, and everything inside `Learned` is then on one
        # scale.** `observe_bar` returns a Rogers-Satchell reading, which is a
        # standard deviation; `vol.bps` is a mean absolute deviation. They
        # differ by sqrt(pi/2), and `consensus_vol` is careful about it -
        # `observe_bar` itself settles the ensemble with `realised /
        # MAD_TO_SIGMA` for exactly this reason.
        #
        # This did not, and the cost was not subtle. The target was
        # log(sigma-scale realised / MAD-scale estimate), so it was centred on
        # log(1.25) rather than on zero; and in the scoreboard `har` and
        # `learned` were both converted to MAD while `naive` was compared
        # against the raw sigma-scale truth. Two of the three competitors were
        # shrunk by a quarter before the comparison, and the headline finding of
        # research/forecasting.md is that persistence beats both of them.
        #
        # Measured on 59,622 warm bars across ten feeds: realised / vol_bps has
        # a median of **1.43**, so the target was never near zero and the
        # published `learned_ratio` ran at 0.79.
        realised_bps = realised_bps / MAD_TO_SIGMA
        key = f"{feed}|{interval}"
        learned = self.learned
        row = learned.features(
            key,
            ew_bps=vol.bps,
            garch_bps=vol.garch_bps,
            range_bps=vol.range_bps,
            har_bps=vol.forecast_bps,
            stretch=vol.stretch,
            open_=open_,
            high=high,
            low=low,
            close=close,
            hour=hour,
            weekday=weekday,
            hour_share=hour_share,
            volume=volume,
            focus_nats=focus_nats,
            interval_seconds=interval_seconds,
        )
        learned.observe(
            key,
            realised_bps,
            row,
            ew_bps=vol.bps,
            har_bps=vol.forecast_bps,
            close=close,
            volume=volume,
            changed=changed,
        )

    def forget(self, keep: set[str]) -> int:
        """Drop every estimate for a feed not in `keep`. Returns how many went.

        The book held **5,416 estimates across 445 feeds** for a desk that
        trades 53 instruments, at 21KB each - 111MB of a 552MB state. See
        `engine.Engine.forget` for where those feeds came from and why bounding
        the price collector did not bound this.
        """
        gone = [key for key in self._by_key if key[0] not in keep]
        for key in gone:
            del self._by_key[key]
        learned = getattr(self, "_learned", None)
        if learned is not None:
            forget = getattr(learned, "forget", None)
            if callable(forget):
                forget(keep)
        return len(gone)

    def feeds(self) -> list[str]:
        return sorted({feed for feed, _ in self._by_key})

    def intervals(self, feed: str) -> list[str]:
        return sorted(interval for this, interval in self._by_key if this == feed and interval)
