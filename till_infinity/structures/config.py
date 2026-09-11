"""Settings for the online models.

Nothing here needs an API key. That is the point of keeping `structures` out of
`agents`: the numeric layer runs continuously, on a laptop or a box with no
credentials at all, and is never held up by a provider being down.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..shared.env import number as _float
from ..shared.env import whole as _int
from .state import Restorable

DEFAULT_STATE_DIR = ".data/structures"
DEFAULT_JOURNAL_DB = ".data/journal/journal.db"
DEFAULT_PRICES_DB = ".data/prices/prices.db"
DEFAULT_NEWS_DB = ".data/news/news.db"

#: Named once, because the field default and the environment fallback had
#: drifted apart: the dataclass said all three passes and `from_env` said one,
#: so a deployment that set nothing got a formation the documentation beside
#: the field denied it had.
DEFAULT_FORMATION = "pip,run,origin,profile"

#: Only fast data. Above five minutes a "cross-venue disagreement" is mostly
#: different bar boundaries, not different opinions about the price.
INTERVALS: tuple[str, ...] = ("1m", "5m")

#: Timeframes the drift detector watches. Wider than INTERVALS on purpose: a
#: regime change now discounts every level's history, so it has to be confirmed
#: across timeframes rather than declared by whichever one is noisiest.
DRIFT_INTERVALS: tuple[str, ...] = ("5m", "15m", "1h", "4h")

#: Seconds between saves. An online model that resets on every restart has
#: learned nothing, so persistence is not optional - only its frequency is.
DEFAULT_SAVE_SECONDS = 300.0

#: A deviation this large is not a market opinion, it is a broken quote, so it
#: goes straight to `alerts` without waiting for an agent. Nothing on the
#: economic calendar moves one venue 100bps while five others hold still.
DEFAULT_DIRECT_DEV_BPS = 100.0

#: One signal per (shape, feed, venue) per this many seconds. A venue that
#: stays stale for an hour is one situation, not three thousand.
DEFAULT_COOLDOWN = 900.0


@dataclass(slots=True)
class Settings(Restorable):
    """How the models are tuned, where their state lives."""

    state_dir: Path = field(default_factory=lambda: Path(DEFAULT_STATE_DIR))
    journal_db: Path = field(default_factory=lambda: Path(DEFAULT_JOURNAL_DB))
    #: Read-only, and only to warm the level windows on start.
    prices_db: Path = field(default_factory=lambda: Path(DEFAULT_PRICES_DB))
    #: Read-only, and only for the monetary-policy series. Same argument as
    #: `prices_db`: the collector owns the file and this reads it.
    news_db: Path = field(default_factory=lambda: Path(DEFAULT_NEWS_DB))
    warm: bool = True
    journalling: bool = True
    warmup: int = 60
    quantile: float = 0.999
    sigma: float = 4.0
    save_seconds: float = DEFAULT_SAVE_SECONDS
    direct_dev_bps: float = DEFAULT_DIRECT_DEV_BPS
    cooldown: float = DEFAULT_COOLDOWN
    alert_direct: bool = True
    #: Whether an actionable level call reaches a person without an agent in
    #: between. On by default, because it is the thing the system is *for* -
    #: with it off and agents disabled, level calls are published to a topic
    #: nobody is subscribed to and the channel receives only feed faults.
    alert_levels: bool = True
    #: Whether the measured spread is charged against every level call before
    #: it is judged. On by default: a push that has not had the cost of taking
    #: it deducted is a gross number, and the gap between gross and net is the
    #: whole difference between a figure and a decision.
    #:
    #: Turning it off is for comparison, not for production - run the same
    #: history both ways and the difference is exactly what the cost is worth.
    #: Worth knowing before doing so: the charge is not uniform, running from
    #: 0.003v on btc to 2.5v on gbpusd intraday, so switching it off does not
    #: loosen one gate evenly. See levels.md, "What the cost actually comes to".
    charge_spread: bool = True

    #: Whether to run the learned volatility forecaster (`vol/learned.py`) -
    #: one pooled online tree forecasting realised volatility over the next
    #: five bars, from twenty dimensionless features shared across the book.
    #:
    #: **Its standing is under re-measurement and gates nothing either way.**
    #:
    #: It was reported as beating `har.py` in every cell of a split-sample test
    #: and as losing, with `har`, to the naive last-realised-value baseline.
    #: Both claims were measured while `Book.learn` mixed the mean-absolute and
    #: standard-deviation conventions, and the mixing was asymmetric: `har` was
    #: shrunk by sqrt(pi/2) against an unconverted truth, while the learner was
    #: shrunk *and* trained on a target centred on log(1.25), two errors that
    #: cancelled. On a small aligned re-run `har` beats `naive` at all four
    #: horizons and the learner is last at every one - the reverse of both.
    #:
    #: The conversion now happens once, at the boundary in `Book.learn`. The
    #: full re-run is owed. `research/forecasting.md` carries the account,
    #: including the two earlier wrong conclusions and what caused each.
    #:
    #: On, it costs about 0.2% of one core and 1.2MB, publishes `learned_bps`
    #: and `learned_ratio` on every call, and logs a head-to-head each save.
    #: The feeds this engine keeps state for. Empty means "whatever arrives",
    #: which is what it did before and what let the state grow to 349 feeds for
    #: a 53-instrument book - see `engine.Engine.forget`. Set it to the desk's
    #: own symbol list and the accumulated residue is dropped on the next save.
    feeds: tuple[str, ...] = ()
    vol_learner: bool = False

    #: How swings are found: `pip` takes bar extremes by prominence, `run` the
    #: boundaries between volatility runs, `origin` the turns whose impulse set
    #: a new running extremum, `profile` the price bands where the most
    #: activity happened, and `both` runs pip and run as separate passes and
    #: merges them.
    #:
    #: A setting because it was not one, and the `origin` formation shipped
    #: unreachable: `Engine` took the argument, nothing passed it, and the
    #: default won. Every level in production was drawn by `pip` while the
    #: other two sat there looking available.
    #:
    #: The point is to run them over one history and let the outcome machinery
    #: say which price gets respected, which needs the choice to be reachable
    #: from a deployment rather than from a keyword argument nobody sets.
    #:
    #: **All four by default**, because they find different prices and merging
    #: is additive - a pass that draws nothing costs a little work and removes
    #: no level. `origin` alone draws none at all on gold at 1m, 5m or 15m, so
    #: selecting it instead of `pip` would have stopped that instrument
    #: trading; selecting it *alongside* cannot.
    #:
    #: `profile` is included although it fails the test it was built for - a
    #: node is reached no more often than an arbitrary price the same distance
    #: away, pooled across instruments (see research/shelves.md). That refutes
    #: it as a *source* of levels and says nothing about it as a **vote**: the
    #: question here is whether a price four independent methods agree on is
    #: respected more than a price one found, and a pass that is useless alone
    #: can still carry information about a price something else already drew.
    #:
    #: Which is why `drawn_by_n` is published on every level call. Four passes
    #: that agree is a claim; it is recorded now, and gated only if the outcome
    #: machinery says it is worth something.
    formation: str = DEFAULT_FORMATION

    #: Whether monetary policy is folded onto level calls and emitted as its
    #: own shape. On by default and cheap: the series are already collected,
    #: the features decide nothing, and a macro call is published for the
    #: outcome machinery to judge rather than acted on.
    #:
    #: Off is for a deployment with no `news` service, where the database it
    #: reads does not exist - though that case already degrades to silence, so
    #: the setting is for saying so deliberately rather than for avoiding a
    #: fault.
    macro: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            state_dir=Path(os.environ.get("STRUCTURES_DIR") or DEFAULT_STATE_DIR),
            journal_db=Path(os.environ.get("JOURNAL_DB") or DEFAULT_JOURNAL_DB),
            prices_db=Path(os.environ.get("PRICES_DB") or DEFAULT_PRICES_DB),
            news_db=Path(os.environ.get("NEWS_DB") or DEFAULT_NEWS_DB),
            warm=os.environ.get("STRUCTURES_WARM", "1") not in ("0", "false", "no"),
            journalling=os.environ.get("JOURNAL", "1") not in ("0", "false", "no"),
            warmup=_int("STRUCTURES_WARMUP", 60),
            quantile=_float("STRUCTURES_QUANTILE", 0.999),
            sigma=_float("STRUCTURES_SIGMA", 4.0),
            save_seconds=_float("STRUCTURES_SAVE_S", DEFAULT_SAVE_SECONDS),
            direct_dev_bps=_float("STRUCTURES_DIRECT_DEV_BPS", DEFAULT_DIRECT_DEV_BPS),
            cooldown=_float("STRUCTURES_COOLDOWN_S", DEFAULT_COOLDOWN),
            alert_direct=os.environ.get("STRUCTURES_DIRECT", "1") not in ("0", "false", "no"),
            alert_levels=os.environ.get("STRUCTURES_ALERT_LEVELS", "1") not in ("0", "false", "no"),
            charge_spread=os.environ.get("STRUCTURES_CHARGE_SPREAD", "1")
            not in ("0", "false", "no"),
            formation=os.environ.get("STRUCTURES_FORMATION") or DEFAULT_FORMATION,
            macro=os.environ.get("STRUCTURES_MACRO", "1") not in ("0", "false", "no"),
            vol_learner=os.environ.get("STRUCTURES_VOL_LEARNER", "0") not in ("0", "false", "no"),
            # `SYMBOLS` is the desk's own list and is already set everywhere, so
            # this defaults to it rather than inventing a second place to keep
            # the same names in step. `STRUCTURES_FEEDS` overrides it for a
            # replay that wants the whole corpus.
            feeds=tuple(
                name.strip()
                for name in (
                    os.environ.get("STRUCTURES_FEEDS") or os.environ.get("SYMBOLS") or ""
                ).split(",")
                if name.strip()
            ),
        )
