"""One bar in, one readout out, and the bookkeeping that makes it a service.

`facade.Desk` is already the numeric core - "one per process, holds a member
and an activity estimator per feed and interval, so a caller holds this and
nothing else". What it does not hold is the things that make a process a
service: which feeds are in scope, when to save, whether a feed has seen
enough to be worth publishing, and what to fold *from* a bar.

That last one is the only real decision here, and it is a measured one.

## What a bar contributes is its dispersion, not its close

Every member in this package is pointed at dispersion, because that is the half
that forecasts out of sample: median R2 of **+0.54 to +0.83** at 1h, h=20 on FX
and metals, against **-0.003 to -0.042** on constant-volatility synthetics and
-0.000 to -0.013 on shuffled targets. Direction, measured on the same desk, is
a coin.

So the observation is the bar's **log variance** from a range estimator, and
the estimator is not free to choose. On the same bars at fx_cross 1h h=20,
Garman-Klass reads **+0.575** and Parkinson +0.565, while Rogers-Satchell - the
drift-robust one - reads **-0.090**: removing the drift term removes nearly all
of the forecastable signal. `spanning.DEFAULT` is Garman-Klass for that reason
and this follows it rather than deciding again.

Log, not the variance itself, because that is the space the members were fitted
and scored in, and because a variance is bounded below at zero while a filter's
state is not.

## Volume goes in as volume

`Desk.read` takes it and decides for itself whether the feed's class says
activity carries anything - `pacing.Pace` goes inert on a feed whose generator
fixes its tick count, without being told. So this passes it through rather than
gating it, and the Q clock is worth having: **+1567** together with the loop
against +848 and +518 alone.
"""

from __future__ import annotations

import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .facade import Desk, Readout
from .spanning import DEFAULT, garman_klass, parkinson, rogers_satchell
from .state import Progress
from .store import load as _load
from .store import save as _save

log = logging.getLogger(__name__)

__all__ = ["Engine", "dispersion"]

#: Smallest variance that is folded. A bar whose high equals its low is a
#: feed that did not trade, not a bar with no volatility, and `log(0)` is not
#: a number a filter can take.
FLOOR = 1e-12


def dispersion(
    open_: float, high: float, low: float, close: float, estimator: str = DEFAULT
) -> float | None:
    """The bar's log variance, or None if the bar cannot produce one."""
    if estimator == "parkinson":
        var = parkinson(high, low)
    elif estimator == "rogers_satchell":
        var = rogers_satchell(open_, high, low, close)
    else:
        var = garman_klass(open_, high, low, close)
    if not math.isfinite(var) or var <= FLOOR:
        return None
    got = math.log(var)
    return got if math.isfinite(got) else None


@dataclass(slots=True)
class Engine:
    """The service's state: a desk, what it has seen, and when it last saved."""

    settings: Settings = field(default_factory=Settings)
    desk: Desk = field(default_factory=Desk)
    progress: Progress = field(default_factory=Progress)
    estimator: str = DEFAULT
    #: Why a bar produced no readout, per reason. **Not persisted**: it
    #: describes this process's run, and a count restored from disk would read
    #: as activity that did not happen in it. A field rather than something set
    #: in `restore`, which is a method and is not always called.
    #:
    #: `observe_bar` returns `None` for six different reasons and a caller
    #: wants none of them, so one zero at the consumer cannot say which. With
    #: 693 bars published and no decision recorded for seven days, the honest
    #: answer to "where did the number die" was that nobody had counted.
    #: `bars` is every payload offered and `readouts` is what came out; the
    #: other keys sum to the difference.
    tally: Counter[str] = field(default_factory=Counter)

    #: Bars folded **in this process**, per feed and interval. Deliberately not
    #: persisted and deliberately not part of `Progress`: it exists to be zero
    #: after a restart, because the members are zero after a restart.
    _here: Counter[tuple[str, str]] = field(default_factory=Counter)

    #: Feeds that have delivered a bar past the last one the progress file
    #: records. Until one does, the feed is replaying history and old bars
    #: warm the member; afterwards they are refused as duplicates.
    _live: set[tuple[str, str]] = field(default_factory=set)
    _last_save: float = 0.0

    def restore(self) -> Progress:
        """Read the progress file. The members are not restored - see `state`."""
        self.progress = _load(self.settings.state_dir)
        if self.progress.seen:
            log.info(
                "statespace: progress restored - %d feed-intervals, %d bars folded before this "
                "process, %d armed at %d bars. Members warm by replay, so `tracking` is 0 until "
                "bars arrive.",
                len(self.progress.seen),
                self.progress.folded,
                self.progress.armed(self.settings.warm_bars),
                self.settings.warm_bars,
            )
        return self.progress

    def save(self, *, at: float | None = None, force: bool = False) -> int:
        """Write progress if the save interval has elapsed. Bytes written."""
        now = time.time() if at is None else float(at)
        if not force and now - self._last_save < self.settings.save_seconds:
            return 0
        self._last_save = now
        return _save(self.progress, self.settings.state_dir, at=now)

    @property
    def tracking(self) -> int:
        """Feed-intervals with a live member. Zero after a restart, by design."""
        return self.desk.tracking

    @property
    def armed(self) -> int:
        """Feed-intervals with enough bars folded to publish."""
        return self.progress.armed(self.settings.warm_bars)

    @property
    def saturated(self) -> int:
        """Feed-intervals with a member against its lever's stop. See `Desk`."""
        return len(self.desk.saturated)

    def observe_bar(self, payload: dict[str, Any]) -> Readout | None:
        """Fold one `prices.bars` payload. Returns what may be published.

        None covers **six** different things, because a caller wants none of
        them: out of scope, a bar still forming, a malformed close, a bar that
        cannot produce a variance, a bar already folded, and a feed that has
        not warmed yet.

        **Each is now counted, in `self.tally`.** The docstring used to claim
        they were "counted where it matters" and nothing counted them
        anywhere - so on 2026-11-04, with 693 bars published and no decision
        recorded for seven days, there was no way to say which of the six was
        swallowing them. A single `None` meaning six things eventually means
        the wrong one, and the only defence is to count the branches even
        though none of them is logged.
        """
        feed = str(payload.get("feed") or "")
        interval = str(payload.get("interval") or "")
        self.tally["bars"] += 1
        if not feed or not interval or not self.settings.wants(feed, interval):
            self.tally["out_of_scope"] += 1
            return None
        # **A forming bar is a different measurement, not an early one.**
        # `prices.announce` publishes a notice per *touched* bar, so the bar in
        # progress arrives again on every sweep - and folding it each time both
        # multiplies the observation count and feeds a range that is still
        # growing. `dispersion-noise.md` prices that: the sampling variance of
        # `log(garman_klass)` runs 0.265 on a bar built from thousands of ticks
        # and 0.50 on one built from twelve, with the bias going from -0.15 to
        # -0.79. A tenth-formed bar is not a noisy reading of this bar's
        # variance, it is an accurate reading of a tenth of it.
        #
        # `closed` is absent from some producers and from most tests, so the
        # rule is fail-open on a missing key and fail-closed on an explicit
        # `False`. The second guard is for what `closed` cannot catch: a
        # backfill re-announcing bars the service has already folded.
        if payload.get("closed") is False:
            self.tally["still_forming"] += 1
            return None
        close = payload.get("close")
        if not isinstance(close, int | float) or not close > 0:
            self.tally["bad_close"] += 1
            return None
        close = float(close)
        high = float(payload.get("high") or close)
        low = float(payload.get("low") or close)
        opened = float(payload.get("open") or close)
        when = float(payload.get("time") or time.time())
        value = dispersion(opened, high, low, close, self.estimator)
        if value is None:
            self.tally["no_variance"] += 1
            return None
        volume = payload.get("volume")
        volume = float(volume) if isinstance(volume, int | float) and volume > 0 else 0.0

        seen = self.progress.of(feed, interval)
        key = (feed, interval)
        # **A bar already folded still warms a member that is cold.**
        #
        # The members are not restored - `restore()` says so - so after a
        # restart the model is empty while the progress file remembers
        # hundreds of bars. Refusing everything at or before `seen.at` then
        # throws away exactly the history that would warm it, and the feed
        # waits `warm_bars` *live* bars instead: at 15m and 60 bars, fifteen
        # hours before the desk may act on it.
        #
        # So until a *live* bar arrives - one past the last the file records -
        # a replayed bar is folded. It never becomes a readout: history is not
        # news, and a proposal from a bar hours old would name a price that
        # has gone. It never advances the persisted progress either, which
        # would double-count it across restarts.
        #
        # The phase ends at the first live bar rather than at `warm_bars`.
        # Stopping at the count would warm the member on the **oldest** bars
        # of the replay and refuse the rest - a 250-bar request with
        # `warm_bars` of 60 would leave the model holding the oldest sixty and
        # discarding the recent hundred and ninety, which is worse than not
        # warming it at all. After that first live bar the guard is back, and
        # a feed re-announcing what it has already sent is refused as before.
        replay = bool(seen.bars) and when <= seen.at
        if replay and key in self._live:
            self.tally["already_folded"] += 1
            return None

        readout = self.desk.read(
            feed=feed,
            interval=interval,
            when=when,
            value=value,
            noise=self.settings.noise,
            volume=volume,
        )
        self._here[key] += 1
        if replay:
            # Warmed, and deliberately silent: the progress file already
            # counts this bar, and a readout for it would be a decision about
            # a price that is no longer there.
            self.tally["replayed"] += 1
            return None
        self._live.add(key)
        seen.bars += 1
        seen.at = when
        seen.value = float(readout.value)
        seen.spread = float(readout.spread)
        self.progress.folded += 1
        # **Warm on what *this* process folded, not on what a file remembers.**
        #
        # `restore()` reads the progress file and says so in its own docstring:
        # "The members are not restored." So after a restart `seen.bars` is in
        # the hundreds while the member it gates was created empty seconds ago
        # - the gate passes on the first bar and the readout is a cold model
        # scoring its first observation.
        #
        # Measured on the live desk on 2026-11-05, on the first bar after a
        # deploy: `readouts=21 proposals=20` across 21 feeds, against a trigger
        # of 3 sigma that `band-coverage.md` prices at 0.0006 to 0.0018. Every
        # deploy therefore opened a position on nearly every symbol, with the
        # side taken from that one bar's body - which is why two correlated
        # pairs were entered in opposite directions.
        #
        # `seen.bars` still counts across processes, because progress is what
        # it is for; what gates a readout is this member's own history.
        if self._here[key] < self.settings.warm_bars:
            self.tally["unwarmed"] += 1
            return None
        self.tally["readouts"] += 1
        return readout

    def forget(self, feed: str = "", interval: str = "") -> int:
        """Drop member state and the progress that counted it."""
        dropped = self.desk.forget(feed, interval)
        for key in [
            k
            for k, s in list(self.progress.seen.items())
            if (not feed or s.feed == feed) and (not interval or s.interval == interval)
        ]:
            self.progress.seen.pop(key, None)
        return dropped
