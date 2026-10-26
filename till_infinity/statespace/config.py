"""Settings for the statespace service.

Nothing here needs an API key, for the same reason `structures.config` says it
does not: the numeric layer runs continuously and must never be held up by a
provider being down. It needs prices on the bus and a directory to persist to.

**The one unmeasured constant is `noise`.** Every member in this package takes
a measurement *variance*, and what this service measures is a per-bar range
estimator of log variance - so the number wanted here is the sampling variance
of `log(garman_klass(...))`, which nothing on this desk has measured. The two
standard derivations disagree by a factor of four: treating a close-to-close
square as one chi-square degree of freedom gives `pi^2 / 2 = 4.93` and divides
by the estimator's efficiency (~7.4 for Garman-Klass) for **0.67**, while
treating the estimator itself as chi-square with `2e` degrees of freedom gives
`psi'(7.4)` and **0.145**.

That gap is the whole band. `band_coverage.py` already does the sweep that
settles it - it refuses to accept a guessed noise and lets a walk control pick
the value, which is how the one-bar band was calibrated from a 93.5% breach at
a nominal 95% down to 1.02-1.10. Until that harness is pointed at this
estimator, `DEFAULT_NOISE` is the conservative end of the two: a noise that is
too large makes the filter slow and its band wide, and a noise that is too
small makes it confident and wrong, and only one of those is recoverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..shared.env import flag as _flag
from ..shared.env import names as _names
from ..shared.env import number as _float
from ..shared.env import whole as _int
from ..shared.state import Restorable

DEFAULT_STATE_DIR = ".data/statespace"

#: Bar intervals this service folds. Two, for the same reason
#: `structures.config.INTERVALS` is two: every interval is a separate member
#: per feed, and the cost is linear in the product.
DEFAULT_INTERVALS: tuple[str, ...] = ("1m", "5m")

#: See the module docstring. The conservative end of two derivations that
#: disagree by 4.6x, pending `band_coverage.py`.
DEFAULT_NOISE = 0.67

#: Seconds between saves. `structures` uses 300 and this is cheaper to write.
DEFAULT_SAVE_SECONDS = 300.0

#: Bars a feed must contribute before its readout is published. The members
#: themselves need no warmup to return a number, but `Desk._quantiles` returns
#: an empty band until it has `facade.LEAST` residuals, so publishing earlier
#: ships a readout whose interval is missing rather than wide.
DEFAULT_WARM_BARS = 60

#: Standardised innovation above which a bar is a **break** worth announcing.
#: 3.0 rather than 2.0 because `band-coverage.md` measured the 0.99 interval
#: breaching at 0.0006 to 0.0018 - a 3-sigma reading is genuinely rare here,
#: where on a Gaussian assumption it would not be.
DEFAULT_SIGNAL_SURPRISE = 3.0

#: Log change in the published band's width that counts as a widening or a
#: quieting. 0.5 is a 65% change in width, which is large enough that a
#: consumer sizing off it would act differently.
DEFAULT_SIGNAL_WIDTH = 0.5

#: Hours a feed-interval stays quiet after announcing the same kind. **The
#: whole reason this topic exists separately from `DISPERSION`**: production
#: runs 207 armed feed-intervals at 1m, so a per-bar topic would be twelve
#: thousand messages an hour and no consumer could tell which mattered.
DEFAULT_SIGNAL_QUIET_HOURS = 6.0


@dataclass(slots=True)
class Settings(Restorable):
    """What the service reads from the environment."""

    state_dir: Path = field(default_factory=lambda: Path(DEFAULT_STATE_DIR))
    intervals: tuple[str, ...] = DEFAULT_INTERVALS
    feeds: tuple[str, ...] = ()
    noise: float = DEFAULT_NOISE
    save_seconds: float = DEFAULT_SAVE_SECONDS
    #: Whether to announce transitions on `statespace.signals`. On, because a
    #: topic with no traffic teaches a consumer nothing - but every reading is
    #: still on `DISPERSION`, so turning this off loses only the notice.
    signals: bool = True
    signal_surprise: float = DEFAULT_SIGNAL_SURPRISE
    signal_width: float = DEFAULT_SIGNAL_WIDTH
    signal_quiet_hours: float = DEFAULT_SIGNAL_QUIET_HOURS
    warm_bars: int = DEFAULT_WARM_BARS
    publish: bool = True
    #: Whether a readout also carries its cohort's pooled reading. On, because
    #: it adds fields to a message already being sent rather than traffic of its
    #: own, and the reading a consumer needs most - how many independent bets a
    #: set of simultaneous positions amounts to - cannot be derived downstream
    #: from one feed's payload. See `cohort.py`.
    cohorts: bool = True
    #: Whether to publish trading proposals on `bus.PROPOSALS`. **On**, and
    #: nothing consumes it: `proposing.py` says why the desk's gates would
    #: refuse them today, and `trading.turn_exit` is the standing reason not to
    #: ship a producer switched off - it "has never once run in production"
    #: while its end-to-end path passed every test.
    proposals: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        """Read `STATESPACE_*` from the environment.

        `feeds` empty means every feed on the bus, which is the useful default
        for a service whose cost is one small filter per feed and interval.
        """
        return cls(
            state_dir=Path(_names("STATESPACE_STATE_DIR", (DEFAULT_STATE_DIR,))[0]),
            intervals=_names("STATESPACE_INTERVALS", DEFAULT_INTERVALS),
            feeds=_names("STATESPACE_FEEDS", ()),
            noise=_float("STATESPACE_NOISE", DEFAULT_NOISE),
            save_seconds=_float("STATESPACE_SAVE_SECONDS", DEFAULT_SAVE_SECONDS),
            warm_bars=_int("STATESPACE_WARM_BARS", DEFAULT_WARM_BARS),
            publish=_flag("STATESPACE_PUBLISH", True),
            signals=_flag("STATESPACE_SIGNALS", True),
            cohorts=_flag("STATESPACE_COHORTS", True),
            proposals=_flag("STATESPACE_PROPOSALS", True),
            signal_surprise=_float("STATESPACE_SIGNAL_SURPRISE", DEFAULT_SIGNAL_SURPRISE),
            signal_width=_float("STATESPACE_SIGNAL_WIDTH", DEFAULT_SIGNAL_WIDTH),
            signal_quiet_hours=_float("STATESPACE_SIGNAL_QUIET_HOURS", DEFAULT_SIGNAL_QUIET_HOURS),
        )

    def wants(self, feed: str, interval: str) -> bool:
        """Whether this feed and interval are in scope."""
        if interval not in self.intervals:
            return False
        return not self.feeds or feed in self.feeds
