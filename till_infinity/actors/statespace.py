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

from till_infinity.adapters.mt5.data import TIMEFRAMES

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


class StatespaceActor(Actor):
    """Folds bars into a dispersion reading and publishes it."""

    def __init__(self, config: StatespaceConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self._engine: Any = None
        self._seconds: dict[str, float] = {}

    def on_start(self) -> None:
        # Imported here, not at module scope: `statespace` is a separate
        # distribution, and `stack.py` has the same import inside its runner
        # for the same reason - a deleted directory should fail one supervised
        # task rather than the whole node.
        from statespace import config as ss_config
        from statespace import service as ss_service  # noqa: F401 - topic parity
        from statespace.engine import Engine

        self._engine = Engine(settings=ss_config.Settings.from_env())
        self._engine.restore()

        for raw in self._cfg.bar_types:
            bar_type = BarType.from_str(raw)
            self._seconds[str(bar_type)] = _seconds(bar_type)
            self.subscribe_bars(bar_type)
            self.log.info(f"folding {bar_type}")

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
        readout = self._engine.observe_bar(self._payload(bar))
        if readout is None:
            return  # out of scope, unwarmed, or no variance - all expected
        self._engine.save()
        self.publish_data_dict(self._cfg.topic, _as_dict(readout))

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


def _interval(bar_type: BarType) -> str:
    spec = str(bar_type.spec)
    for key, name in INTERVALS.items():
        if spec.startswith(key):
            return name
    raise ValueError(f"{bar_type} has no statespace interval - known: {sorted(INTERVALS.values())}")


def _seconds(bar_type: BarType) -> float:
    spec = str(bar_type.spec)
    for key, (_name, seconds) in TIMEFRAMES.items():
        if spec.startswith(key):
            return seconds
    raise ValueError(f"{bar_type} has no known bar length")


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
