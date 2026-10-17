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

    def observe_bar(self, payload: dict[str, Any]) -> Readout | None:
        """Fold one `prices.bars` payload. Returns what may be published.

        None covers four different things on purpose, because a caller wants
        none of them: out of scope, a malformed bar, a bar that cannot produce
        a variance, and a feed that has not warmed yet. Each is counted where
        it matters and logged nowhere, because on a busy bus any of them at
        debug level is the whole log.
        """
        feed = str(payload.get("feed") or "")
        interval = str(payload.get("interval") or "")
        if not feed or not interval or not self.settings.wants(feed, interval):
            return None
        close = payload.get("close")
        if not isinstance(close, int | float) or not close > 0:
            return None
        close = float(close)
        high = float(payload.get("high") or close)
        low = float(payload.get("low") or close)
        opened = float(payload.get("open") or close)
        when = float(payload.get("time") or time.time())
        value = dispersion(opened, high, low, close, self.estimator)
        if value is None:
            return None
        volume = payload.get("volume")
        volume = float(volume) if isinstance(volume, int | float) and volume > 0 else 0.0

        readout = self.desk.read(
            feed=feed,
            interval=interval,
            when=when,
            value=value,
            noise=self.settings.noise,
            volume=volume,
        )
        seen = self.progress.of(feed, interval)
        seen.bars += 1
        seen.at = when
        seen.value = float(readout.value)
        seen.spread = float(readout.spread)
        self.progress.folded += 1
        if seen.bars < self.settings.warm_bars:
            return None
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
