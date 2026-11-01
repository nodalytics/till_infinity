"""`statespace` as a Nautilus Actor.

The whole adapter surface is `on_bar`: a Nautilus `Bar` becomes the payload
`Engine.observe_bar` already takes, and the reading it returns is published on
the message bus. Nothing in the package changed to make this work, which was
the question the spike asked.

**Measured against the old path rather than assumed equal.** Identical bars out
of `prices.db`, all eleven fields of every `Readout`, empty state on both
sides:

| feed | interval | result |
| --- | --- | --- |
| eurusd | 1m, 5m | identical, bit for bit |
| spx500 | 15m | identical, 2,941 readouts |
| gold | 5m | worst relative 9.4e-12 - float noise |
| btc | 15m | worst relative 5.7e-14 |
| btc | 1m | worst relative 3.2e-05 |

`research/baseline/` holds the implementation those numbers came from.

**Two conversions carry all the risk**, and both were found by getting them
wrong first:

`ts_event` on a Nautilus bar is the bar's **close**, and `observe_bar` wants
the bar's **open** - `prices` writes the open and `prices.db` stores it. The
subtraction below is that conversion. It is not a cosmetic difference:
`observe_bar` refuses a bar whose time is not strictly after the last one, so
feeding it closes where it expects opens does not shift the series by one bar,
it silences the series after the first.

`Price` and `Quantity` are fixed-precision, so the instrument's declared
precision truncates the input before the fold sees it. btc at its tradable two
decimals moves a 1m reading by 3e-5 relative while 15m stays at float noise,
because truncation matters in proportion to how small a bar's range is against
its tick size. And a volume precision of 0 rounded 701 of 3,000 btc volumes to
zero - they run 0.28, 0.45, 0.48 - which flipped `paced`, since `facade`
decides it as `paced and volume > 0`. That looked exactly like a knife-edge
threshold inside statespace and was the conversion throwing the volume away.
"""

from __future__ import annotations

from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.model.data import Bar, BarType

from till_infinity.utils import topics

#: How long a bar's aggregation unit lasts, in seconds.
#:
#: **Parsed from the `BarType`, not looked up per venue.** This used to import
#: the MT5 adapter's table, which made the Actor MT5-specific for the sake of
#: a constant - and `LAYERS` is right to forbid it: an actor that knows a venue
#: cannot be run against another one, or against a backtest catalogue. A bar
#: spec carries its own step and unit, so nothing here needs a venue.
UNIT_SECONDS: dict[str, float] = {
    "SECOND": 1.0,
    "MINUTE": 60.0,
    "HOUR": 3600.0,
    "DAY": 86_400.0,
    "WEEK": 604_800.0,
}

#: Nautilus aggregation -> the interval name `statespace` keys its state on.
#: Its settings default to `("1m", "5m")`, and those are also the only
#: intervals with no malformed bars in the store: close outside `[low, high]`
#: appears on about 1,200 daily and weekly bars and on none intraday.
INTERVALS: dict[str, str] = {
    "1-MINUTE": "1m",
    "5-MINUTE": "5m",
    "15-MINUTE": "15m",
    "30-MINUTE": "30m",
    "1-HOUR": "1h",
    "4-HOUR": "4h",
    "1-DAY": "1d",
}


class StatespaceConfig(ActorConfig, frozen=True):
    """What to fold, and where to publish it."""

    bar_types: tuple[str, ...] = ()
    #: The bus topic for a reading. Matches `statespace.service.PROPOSES` so a
    #: subscriber written against the old bus keeps working.
    topic: str = "statespace.dispersion"
    #: Map a Nautilus symbol to the feed name `statespace` keys state on, where
    #: they differ. An unmapped symbol is lowercased.
    feeds: dict[str, str] | None = None
    #: Detectors from `till_infinity.indicators` to register against every bar
    #: type, as `name` or `name:source` - the keys of
    #: `indicators.BAR_DETECTORS` and the `Reading` each one reads.
    #:
    #: Empty by default. An indicator that nothing reads still costs a fold per
    #: bar, and this actor's job is the dispersion reading; the detectors are
    #: here because a *discovery* run wants to sweep them over the same stream
    #: the model sees, not because the fold needs them.
    indicators: tuple[str, ...] = ()
    #: The topic trading proposals go on. **A second topic rather than a field
    #: on the reading**, for the reason `proposing.TOPIC` gives: two producers
    #: on a topic named after one of them is how a consumer loses track of
    #: which produced what, and a separate topic is one subscription to remove.
    proposals_topic: str = "statespace.proposals"
    #: Whether to publish them. Default on, matching
    #: `config.Settings.proposals`, and the same argument applies: the standing
    #: reason not to ship a producer switched off is `trading.turn_exit`, which
    #: "has never once run in production" while its end-to-end path passed
    #: every test.
    proposals: bool = True


class StatespaceActor(Actor):
    """Folds bars into a dispersion reading and publishes it.

    Also the place indicators get registered, when asked for. **`Actor` carries
    the whole indicator API** - `register_indicator_for_bars`,
    `register_indicator_for_quote_ticks`, `register_indicator_for_trade_ticks`,
    `registered_indicators` and `indicators_initialized` - identically to
    `Strategy`, which adds nothing to it. So an actor can hold detectors
    without pretending to be a strategy, and the engine feeds them: no handler
    here calls `handle_bar`, and `on_bar` runs *after* Nautilus has updated
    every registered indicator for that bar.

    That is what makes this the right home for a discovery sweep. The sweep
    reads the same bars the model folded, through detectors the engine warmed,
    with no second copy of the stream to drift from the first.
    """

    def __init__(self, config: StatespaceConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self._engine: Any = None
        self._seconds: dict[str, float] = {}
        #: `(bar type, detector name, source)` -> the indicator, so a reader
        #: can find one without matching on `registered_indicators` order.
        self.detectors: dict[tuple[str, str, str], Any] = {}

    def on_start(self) -> None:
        # Imported here, not at module scope: `statespace` is a separate
        # distribution, and `stack.py` has the same import inside its runner
        # for the same reason - a deleted directory should fail one supervised
        # task rather than the whole node.
        from . import config as ss_config
        from . import service as ss_service  # noqa: F401 - topic parity
        from .engine import Engine

        self._engine = Engine(settings=ss_config.Settings.from_env())
        self._engine.restore()

        for raw in self._cfg.bar_types:
            bar_type = BarType.from_str(raw)
            self._seconds[str(bar_type)] = _seconds(bar_type)
            self._register(bar_type)
            self.subscribe_bars(bar_type)
            self.log.info(f"folding {bar_type}")

    def _register(self, bar_type: BarType) -> None:
        """Build the configured detectors and hand them to Nautilus.

        Registration happens **before** `subscribe_bars`, so an indicator
        cannot miss the first bar of the subscription. The two orders are
        indistinguishable on a live feed, which arrives milliseconds later, and
        differ on a backtest, which delivers the first bar immediately.

        An unknown name raises here rather than being skipped. A detector the
        config asked for and the actor quietly did not build is a sweep that
        reports a null for a question it never asked.
        """
        from till_infinity.indicators import BAR_DETECTORS, build_detector

        for entry in self._cfg.indicators:
            name, _, wanted = entry.partition(":")
            if name not in BAR_DETECTORS:
                raise ValueError(
                    f"{entry!r} is not a known detector. "
                    f"`indicators.BAR_DETECTORS` has {sorted(BAR_DETECTORS)}."
                )
            # `build_detector` picks the unit that matches the source's
            # dimension, so a config naming a source cannot produce a
            # miscalibrated detector.
            indicator = build_detector(name, wanted or None)
            source = indicator.source
            self.register_indicator_for_bars(bar_type, indicator)
            self.detectors[str(bar_type), name, str(source)] = indicator
            self.log.info(f"registered {name} on {source} for {bar_type}")

    def on_stop(self) -> None:
        """Cancellation saves.

        A service stopped cleanly that comes back having forgotten the last
        five minutes is a service whose counters cannot be trusted to say
        whether it was running.
        """
        if self._engine is not None:
            self._engine.save(force=True)

    def on_bar(self, bar: Bar) -> None:
        if self._engine is None:
            return
        payload = self._payload(bar)
        readout = self._engine.observe_bar(payload)
        if readout is None:
            return  # out of scope, unwarmed, or no variance - all expected
        self._engine.save()
        topics.publish(self, self._cfg.topic, _as_dict(readout))
        proposal = self._propose(readout, payload)
        if proposal is not None:
            topics.publish(self, self._cfg.proposals_topic, proposal)

    def _propose(self, readout: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
        """The trading proposal this bar is, or `None`. **Does not publish.**

        **This was the gap in the Nautilus port.** `service.py` published on
        `PROPOSES` and the actor did not, so `config.Settings.proposals` was on
        and nothing came out of the actor path - a producer whose own tally
        counts what it sent, which is the bug that hid `statespace.proposals`
        for weeks.

        **The bar carries the sign, not the readout.** This service folds log
        variance, so a side taken from the reading would be the side of a
        *volatility* move published as a price claim - the category error
        already corrected twice in this package. `proposing.direction_of`
        takes it from the triggering bar's own body, which is continuation.

        Returning the payload rather than sending it keeps the decision
        testable: `Actor.msgbus` is a read-only Cython attribute, so an actor
        built without its engine cannot be handed a bus, and a method that
        both decides and publishes can only be tested with one.
        """
        if not self._cfg.proposals:
            return None
        from . import proposing

        return proposing.proposal_for(readout, payload)

    def _payload(self, bar: Bar) -> dict[str, Any]:
        bar_type = str(bar.bar_type)
        symbol = bar.bar_type.instrument_id.symbol.value
        feeds = self._cfg.feeds or {}
        return {
            "feed": feeds.get(symbol, symbol.lower()),
            "interval": _interval(bar.bar_type),
            # ts_event is the close; the fold wants the open.
            "time": (bar.ts_event / 1e9) - self._seconds.get(bar_type, 0.0),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            # Nautilus only delivers a bar once it has closed, so this is
            # always true here - stated rather than omitted, because
            # `observe_bar` fails *open* on a missing key and a future source
            # that does deliver forming bars would be folded silently.
            "closed": True,
        }


#: The one reading per catalogued detector that a sweep thresholds on, as the
#: attribute to take off the warmed indicator.
#:
#: **This table is here and not in `indicators/` on purpose.** A detector
#: exposes several readings - `Trendlines` alone has `spread_vol`,
#: `converging`, `broke`, `held` and `extent_vol` - and *which one is the
#: candidate* is a decision about the search, not a property of the detector.
#: Putting it in the catalogue would make `indicators` carry a search's
#: opinion; putting it here means a sweep that wants a different reading
#: passes `read=` and records that it did.
#:
#: A signed reading is taken as a **magnitude** for a dispersion question, and
#: that is recorded rather than quietly done: the statistic is a forward
#: *absolute* move, so a signed trigger would be asking a direction question
#: under a dispersion label - and direction is the one question measured closed
#: here. `searching.Candidate.question` is what distinguishes them, and a
#: caller asking the direction question should pass a signed `read`.
READINGS: dict[str, str] = {
    "changepoint": "changepoint",
    "cusum": "pressure",
    "focus": "statistic",
    "trend": "efficiency",
    "efficiency": "efficiency",
    "variance_ratio": "z",
    "slope": "change_z",
    "trendlines": "spread_vol",
    # How many swings in the window are not yet confirmed: the honest measure
    # of how much of the current shape is still provisional, and the only
    # reading on `Pips` that is not a structure label. The labels themselves
    # are swept properly by `shaping.word_reader`, which fires at a swing's
    # confirmation index rather than at its extreme.
    "pips": "provisional",
    "displacement": "size_vol",
    # Gaps **open as of this bar**, which is the causal count. `Gaps` is the
    # incremental form for exactly this reason: a gap list holding only
    # *unfilled* gaps is lookahead the moment it is read as of a time before
    # the fill was known, and that mistake read +0.50R a trade as a bias.
    "gaps": "count",
    # ── Nautilus's own, and only the ones whose reading is scale-free ──
    #
    # **The rest of `FRAMEWORK` is absent for a units reason, not an oversight.**
    # `bars.check_scale` refuses one of ours whose threshold would be in the
    # instrument's own units - a reading divided by the wrong dimension "reads
    # perfectly calibrated at a price near 1.0, where a relative spread and a
    # price distance are the same number, and is wrong by a factor of the price
    # everywhere else". It cannot refuse one of Nautilus's, because theirs take
    # no `unit_from`: `AverageTrueRange.value` is a price distance, `sma` and
    # `bollinger` are prices, `obv` and `vwap` carry volume. A sweep
    # thresholding any of those puts a gold threshold on EURUSD.
    #
    # These three are **bounded** by construction - `rsi` runs 0 to 1, `aroon`
    # and `value_k` run to 100 - so one threshold means the same thing on every
    # instrument. A caller that wants `atr` can still have it through `read=`,
    # by dividing by something, and that division is the decision the absence
    # is making visible.
    #
    # `roc` is deliberately not here although it is dimensionless. A rate of
    # change is a return, so it has no units - but its *scale* is the
    # instrument's volatility, and the 90th percentile of a 14-bar EURUSD
    # return is 0.00126 where BTC's is two orders of magnitude larger. A
    # dimensionless reading is not a scale-free one, and only the second is
    # safe to threshold across a panel.
    "rsi": "value",
    "aroon": "value",
    "stochastics": "value_k",
}


def detector_reader(
    name: str,
    source: str | None = None,
    *,
    bar_type: str = "SWEEP.SIM-1-HOUR-LAST-EXTERNAL",
    precision: int = 8,
    read: Any = None,
    signed: bool = False,
    **kwargs: Any,
) -> Any:
    """A `searching.Reader` for one catalogued detector on one source.

    **The seam between the panel and the sweep, and it lives here because this
    is the only file in `statespace` that may import `nautilus_trader`.** The
    33 detectors reachable through `indicators.build_detector` are Nautilus
    `Indicator`s, and `searching.py` must not know what a `Bar` is - so this
    turns a name into a function from candles to one float per candle, and the
    sweep holds that function as a value.

    Holding it as a value is what makes the null arms work: a **series** arm
    manufactures candles and the sweep re-runs *the same reader* over them,
    which is what "null every candidate against a walk through the same
    detector" means mechanically. Four alternating-detector readings came out
    level with a walk because the detector's own structure was in both arms,
    and that only shows up if the detector really is re-run.

    `precision=8` is deliberately **not** a tradable precision. `Price` is
    fixed-precision, so an instrument's declared precision truncates the feed
    before the detector sees it - btc at its tradable two decimals moves a 1m
    reading by 3e-5 relative, and a volume precision of 0 rounded 701 of 3,000
    btc volumes to zero. A sweep measures the series rather than a fill, so it
    takes the series undamaged and the fill cost is applied downstream.

    `read` overrides `READINGS`: a callable taking the indicator and returning
    a float, for a detector whose candidate reading is not the table's.
    """
    from nautilus_trader.model.objects import Price, Quantity

    from till_infinity.indicators import BAR_DETECTORS, FRAMEWORK, Reading, build_detector

    if read is None:
        if name not in READINGS:
            known = sorted(set(BAR_DETECTORS) | set(FRAMEWORK))
            raise ValueError(
                f"{name!r} has no catalogued sweep reading. `READINGS` covers "
                f"{sorted(READINGS)}; the detectors are {known}. Pass `read=` with the "
                f"reading this trial is about - a detector exposes several and which "
                f"one is the candidate is a decision about the search."
            )
        attribute = READINGS[name]

        def take(indicator: Any) -> float:
            return float(getattr(indicator, attribute))
    else:
        take = read

    wanted = Reading(source) if source else None
    kind = BarType.from_str(bar_type)
    volume = Quantity(1, 0)

    def reader(candles: Any) -> list[float]:
        indicator = build_detector(name, wanted, **kwargs)
        step = int(_seconds(kind) * 1_000_000_000)
        out: list[float] = []
        for i, (open_, high, low, close) in enumerate(candles):
            indicator.handle_bar(
                Bar(
                    kind,
                    Price(open_, precision),
                    Price(high, precision),
                    Price(low, precision),
                    Price(close, precision),
                    volume,
                    ts_event=(i + 1) * step,
                    ts_init=(i + 1) * step,
                )
            )
            try:
                got = take(indicator)
            except (AttributeError, TypeError, ValueError):
                out.append(float("nan"))
                continue
            out.append(float("nan") if got is None else (got if signed else abs(float(got))))
        return out

    return reader


def _interval(bar_type: BarType) -> str:
    spec = str(bar_type.spec)
    for key, name in INTERVALS.items():
        if spec.startswith(key):
            return name
    raise ValueError(f"{bar_type} has no statespace interval - known: {sorted(INTERVALS.values())}")


def _seconds(bar_type: BarType) -> float:
    """The bar's length, from its own spec.

    `str(spec)` is `<step>-<unit>-<price type>`, so `4-HOUR-LAST` is four
    hours. Multiplying rather than tabulating means a step this desk has never
    used - 3-MINUTE, 2-HOUR - works without an edit.
    """
    parts = str(bar_type.spec).split("-")
    if len(parts) < 2 or not parts[0].isdigit() or parts[1] not in UNIT_SECONDS:
        raise ValueError(
            f"{bar_type} has no length this actor can read - units: {sorted(UNIT_SECONDS)}"
        )
    return int(parts[0]) * UNIT_SECONDS[parts[1]]


def _as_dict(readout: Any) -> dict[str, Any]:
    """A `Readout` as the payload the `statespace.dispersion` contract declares."""
    return {
        "feed": readout.feed,
        "interval": readout.interval,
        "at": float(readout.at),
        "value": float(readout.value),
        "spread": float(readout.spread),
        "family": readout.family,
        "absorbs": readout.absorbs,
        "paced": bool(readout.paced),
        "pace_factor": float(readout.pace_factor),
        "walls": [float(w) for w in readout.walls],
        "quantiles": [[float(q), float(v)] for q, v in readout.quantiles],
    }
