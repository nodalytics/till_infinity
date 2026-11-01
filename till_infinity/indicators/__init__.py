"""The computations: a detector, a shape, a reading off a bar. No policy.

Everything here answers a question about market data and decides nothing.
`strategies` decides, `risk` sizes, `statespace` models - and all three read
this package, which is the whole reason it exists as a package.

## Why it is a package and not two copies

`statespace` was required to import nothing outside itself, so that it stayed
extractable in one move. The rule was honoured the only way it could be: by
**vendoring**. `statespace/accruing.py` held a field-for-field copy of FOCuS,
identical to `strategies/focus.py` down to the threshold, and the drift between
them was caught by a *persistence collision* rather than by review - the
registry keys state on module basename and class name (`utils/codec.py`), so
two modules called `focus` holding two classes called `Focus` resolved to one
key and one silently shadowed the other.

A leaf package fixes that without giving up what the rule protected.
`test_indicators_import_nothing_but_utils` pins the leaf: nothing here imports
from the desk except `utils`, so extracting statespace is still one move - it
takes one more directory with it.

## Checked against what Nautilus already ships

Audited 2026-10-31, module by module, because "nautilus first" is only a
principle if somebody looks. `nautilus_trader.indicators` is not thin -
`averages` has nine moving averages and a factory, `momentum` has RSI,
stochastics, rate of change, CCI, Chande and the efficiency ratio, `trend` has
linear regression, MACD, Aroon, directional movement and swings, `volatility`
has ATR, Bollinger, Donchian and Keltner, `volume` has OBV, VWAP, Klinger and
pressure, and `fuzzy_candlesticks` grades candle body, size and wicks into
categories.

What that audit found, for each thing here.

**Two of theirs are arithmetically wrong, and ours replace them.**
`momentum.EfficiencyRatio` is Kaufman's ratio, the same statistic as
`trend.ratio` - but fed a straight line, where the ratio is 1.0 by definition,
it reports `(period - 1) / period`: 0.8 at period 5, 0.95 at 20. It takes the
numerator over one fewer step than the denominator, so it is bounded below 1
and biased low by `1 / period`, worst where a short window is wanted.
`SpreadAnalyzer.average` stops updating once its window fills, because it
appends a value and then subtracts the one it just appended. Both are pinned by
tests, so an upstream fix shows up as a failure rather than as a silent change
of meaning.

**One of ours is an exact duplicate.** `regression.fit`'s slope and `r2` agree
with `trend.LinearRegression` to 1e-9, so prefer the framework's for the fit.
What `Channel` adds is the bands, `slope_vol` and the vol-scaled readings, and
that is the part worth keeping.

**One is the same indicator with a different edge.** `regression.atr` and
`volatility.AverageTrueRange(n, SIMPLE)` differ by about 0.015%, which is a
window convention. Replaceable - but the swap changes every number measured on
the old one, so it is a re-measurement and not a refactor.

**One cannot be expressed in their parameters.** `ExponentialMovingAverage`
takes an integer `period`; `Speeds` is parameterised by half-life in
*observations*, and a half-life of 12 maps to period 34.63. The half-lives are
measured, so changing them to land on an integer is the tail wagging the dog.

**Two answer a nearby but different question.** `trend.Swings` reports the
running extreme - on a rising series `since_high` is 0, so the high it names is
this bar's - and holds one high and one low; a trendline needs two *confirmed*
pivots per side. `volume.OnBalanceVolume` and `volume.Pressure` sign by close
direction off bars; `TickMomentum` reads `aggressor_side` where a venue sends
trades and quote revisions where it does not, which is all MT5 sends.

**One is complementary and should be used together.** `fuzzy_candlesticks`
grades body, size and wicks against a rolling window, which is a better size
judgement than `candles`' fixed fractions. What it has no notion of is the
level: `confirms(bars, level, want_up)` is the question this desk asks, and
that part is ours.

**And five have nothing comparable.** Changepoint detection, exact CUSUM, the
displacement-and-origin reading, causal fair value gaps and pivot trendlines
are not in the framework.

**So: take a moving average, an ATR, a linear regression, an RSI or a fuzzy
candle from Nautilus.** Two of its indicators are arithmetically wrong and both
are documented here with a test. The rest of this package is what the framework
does not have.

## Nautilus first

These are `nautilus_trader.indicators.base.Indicator` subclasses, not objects
behind adapters. An `Actor` can register them exactly as a `Strategy` can -
`register_indicator_for_bars`, `register_indicator_for_quote_ticks`,
`register_indicator_for_trade_ticks` are on both classes and `Strategy` adds
nothing - so the engine feeds them and nothing here re-implements a bus, a
clock or a warmup.

Two things that follows from, worth knowing before using one:

**`reset` means Nautilus's thing.** `Cusum` and `Focus` had a `reset` that
meant *a change has been acted on, accumulate from here*, which deliberately
keeps `seen` and `total` because the stream did not restart. Nautilus's `reset`
means *this has never seen anything*, because the engine calls it on a rewind.
The first is now `restart`; wiring one to the other gives a detector reporting
a fresh statistic over a total it never cleared, which is indistinguishable
from fresh at every surface a caller can see.

**A scale is required and its units are checked.** A detector divides by a
volatility unit so one threshold means the same thing on gold and on BTC.
`bars.check_scale` refuses an indicator that was not told its unit, and refuses
one whose unit is in the wrong dimension - a log return scaled by a price range
reads perfectly calibrated at a price near 1.0, where a relative spread and a
price distance are the same number, and is wrong by a factor of the price
everywhere else.

## What is here

| module | what it answers | fed by |
|---|---|---|
| `changepoint` | has the regime changed, and how long has this one held | bars |
| `cusum` | how far has price run since the last event | bars |
| `focus` | of every place a change could have started, the best evidence | bars |
| `trend` | is this trending through here, or ranging inside it | bars |
| `speeds` | three EWMAs per feed, and whether they agree | bars, keyed |
| `displacement` | where the last leg came from | bars |
| `gaps` | is that hole still there | bars |
| `trendlines` | what lines the pivots make, top and bottom, and breaks | bars |
| `ticks` | who is moving, from trades or from quote revisions | ticks |
| `spread` | what will this cost, over a rolling window | quotes |
| `candles` | did this bar reject a price | functions |
| `impulse` | how far and how fast, over a window | functions |
| `regression` | what line is price on | functions |

`candles`, `impulse` and `regression` stay as functions over a sequence of
bars. An `Indicator` is for state the engine feeds; a shape test over two bars
has no state, and a window fit called with an explicit list is clearer than one
that reads a window it also maintains. `displacement` and `gaps` are the
incremental forms of what `impulse` computes in a batch, and exist because the
live versions of those two questions need a causal answer: a gap list holding
only *unfilled* gaps is lookahead the moment it is read as of a time before the
fill was known, which is a mistake this desk has already paid +0.50R a trade
for.

## Speed

These are scalar O(1)-per-bar updates, so pure Python is not the bottleneck.
The exception is `Changepoint`, whose run-length posterior is O(MAX_RUN) per
reading and carries that ceiling as a declared compute budget. If it ever is
the bottleneck, Cython is the path - Nautilus's own indicators are Cython, and
subclassing `Indicator` means a port there is a translation rather than a
redesign.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable

from .bars import (
    CAN_SCALE,
    DIMENSION,
    NEEDS_PREVIOUS,
    SCALED_BY,
    Dimension,
    Reading,
    check_scale,
    read,
    unit_for,
)
from .candles import Candles
from .changepoint import Changepoint, Focus
from .levels import (
    BjorgumLevels,
    Clock,
    Detect,
    Displacement,
    Forget,
    Gap,
    Gaps,
    Imbalance,
    Kind,
    Leg,
    Level,
    Levels,
    Origin,
    Pips,
    PivotSource,
    Point,
    Structure,
    Swing,
    Visit,
    Zone,
)
from .momentum import Basis, Cusum, Ensemble, Event, SlopeMomentum, Speeds, TickMomentum
from .spread import RollingSpread
from .trend import Channel, Pivot, Trend, Trendline, Trendlines

#: What a discovery sweep may instantiate, and on which sources.
#:
#: The sources listed per detector are the ones its question is *about*. A
#: level detector fed returns and a change detector fed levels both run, both
#: report and both answer nothing - and each costs a trial, which is the
#: scarce thing: at a target Sharpe of 1.5 one month of data supports about
#: **one** trial, so a sweep that spends them on dimensionally pointless
#: combinations has spent its whole budget before it starts.
#:
#: A sweep records the name and the source it chose so a result can be asked
#: for again. `bars.check_scale` refuses the combinations that are unit errors,
#: so a sweep that builds from this table cannot produce one by accident.
#: A source may need a different unit from the detector's default - `BODY` is
#: a price difference and `LOG_RETURN` is dimensionless, and a change detector
#: is about both - so build through `bars.unit_for` rather than letting a
#: source inherit whatever default the class carries. `build_detector` below
#: does that, and the catalogue is swept through it.
BAR_DETECTORS: dict[str, tuple[Callable[..., object], tuple[Reading, ...]]] = {
    "changepoint": (Changepoint, (Reading.LOG_RETURN, Reading.RETURN, Reading.BODY)),
    "cusum": (Cusum, (Reading.CLOSE, Reading.TYPICAL, Reading.MEDIAN)),
    "focus": (Focus, (Reading.LOG_RETURN, Reading.RETURN, Reading.BODY)),
    "trend": (Trend, (Reading.CLOSE, Reading.TYPICAL)),
    "speeds": (Speeds, (Reading.LOG_RETURN, Reading.RETURN)),
    "displacement": (Displacement, (Reading.CLOSE,)),
    "gaps": (Gaps, (Reading.CLOSE,)),
    "trendlines": (Trendlines, (Reading.CLOSE,)),
    "slope": (SlopeMomentum, (Reading.CLOSE, Reading.TYPICAL)),
    "levels": (Levels, (Reading.CLOSE,)),
    # No `source`: these read a bar's whole shape rather than one float off it.
    # `build_detector` only passes what a constructor takes.
    "pips": (Pips, ()),
    "bjorgum": (BjorgumLevels, ()),
}


#: The framework's own indicators, by a short name a config can carry.
#:
#: **Take these rather than writing them.** The audit above found two of
#: Nautilus's arithmetically wrong and the rest sound, so a strategy wanting a
#: moving average, an RSI, an ATR, a Bollinger band or a fuzzy candle should
#: name one here. The tuple is the default arguments; a config may override the
#: first with `name:n`, which is the period for every one of them.
#:
#: `EfficiencyRatio` and `SpreadAnalyzer` are deliberately absent - they are
#: the two that are wrong, and `trend.ratio` and `spread.RollingSpread` replace
#: them.
FRAMEWORK: dict[str, tuple[str, str, tuple]] = {
    # name          module                  class                     defaults
    "sma": ("averages", "SimpleMovingAverage", (20,)),
    "ema": ("averages", "ExponentialMovingAverage", (20,)),
    "hma": ("averages", "HullMovingAverage", (20,)),
    "rsi": ("momentum", "RelativeStrengthIndex", (14,)),
    "roc": ("momentum", "RateOfChange", (14,)),
    "stochastics": ("momentum", "Stochastics", (14, 3)),
    "atr": ("volatility", "AverageTrueRange", (14,)),
    "bollinger": ("volatility", "BollingerBands", (20, 2.0)),
    "donchian": ("volatility", "DonchianChannel", (20,)),
    "keltner": ("volatility", "KeltnerChannel", (20, 2.0)),
    "macd": ("trend", "MovingAverageConvergenceDivergence", (12, 26)),
    "linreg": ("trend", "LinearRegression", (20,)),
    "swings": ("trend", "Swings", (5,)),
    "aroon": ("trend", "AroonOscillator", (14,)),
    "obv": ("volume", "OnBalanceVolume", ()),
    "vwap": ("volume", "VolumeWeightedAveragePrice", ()),
    "fuzzy": ("fuzzy_candlesticks", "FuzzyCandlesticks", (10,)),
}


def framework(name: str, period: int | None = None) -> object:
    """One of Nautilus's own indicators, by short name.

    `period` replaces the first default argument, which is the period for every
    entry in `FRAMEWORK`. An indicator taking none - `vwap`, `obv` with its
    default - ignores it rather than raising, because a config that names a
    period for something periodless has made a harmless mistake and should not
    stop a node.
    """
    if name not in FRAMEWORK:
        raise ValueError(
            f"{name!r} is not a framework indicator. Known: {', '.join(sorted(FRAMEWORK))}."
        )
    module, cls_name, defaults = FRAMEWORK[name]
    cls = getattr(importlib.import_module(f"nautilus_trader.indicators.{module}"), cls_name)
    args = list(defaults)
    if period is not None and args:
        args[0] = period
    return cls(*args)


def build_detector(name: str, source: Reading | None = None, **kwargs: object) -> object:
    """One catalogued detector on one source, scaled correctly for it.

    The single entry point a discovery sweep should use. Picking the unit here
    rather than at each call site is what stops a sweep spending a trial on a
    detector whose threshold is in the wrong units - and trials are the scarce
    thing: at a target Sharpe of 1.5, one month of data supports about one.
    """
    if name in FRAMEWORK:
        # **The framework's, where it has one.** A strategy may use ours and
        # Nautilus's as it wishes, and one entry point resolving both means a
        # config names an indicator without naming where it came from.
        if source is not None:
            raise ValueError(
                f"{name!r} is one of Nautilus's indicators and takes no "
                f"`source`: it reads the bar the engine gives it. A period "
                f"goes in the name, as {name}:20."
            )
        return framework(name, kwargs.get("period"))  # type: ignore[arg-type]
    if name not in BAR_DETECTORS:
        raise ValueError(
            f"{name!r} is not a detector. Ours: {sorted(BAR_DETECTORS)}. "
            f"Nautilus's: {sorted(FRAMEWORK)}."
        )
    build, sources = BAR_DETECTORS[name]
    if not sources:
        # A shape detector: no `Reading` applies, so there is nothing to pick.
        if source is not None:
            raise ValueError(
                f"{name} takes no source: it reads a bar's whole shape - the "
                f"open, high, low and close together - rather than one float "
                f"off it, so there is nothing for a `Reading` to select."
            )
        return build(**kwargs)
    chosen = sources[0] if source is None else Reading(source)
    if chosen not in sources:
        raise ValueError(
            f"{name} does not read {chosen}: its question is about "
            f"{', '.join(sources)}. A level detector fed returns runs, reports, "
            f"answers nothing, and costs a trial."
        )
    if "unit" not in kwargs and "unit_from" not in kwargs and _takes(build, "unit_from"):
        kwargs["unit_from"] = unit_for(chosen)
    if _takes(build, "source"):
        kwargs["source"] = chosen
    elif source is not None:
        raise ValueError(
            f"{name} takes no source: it reads a bar's whole shape - the open, "
            f"high, low and close together - rather than one float off it, so "
            f"there is nothing for a `Reading` to select."
        )
    return build(**kwargs)


def _takes(build: Callable[..., object], name: str) -> bool:
    """Whether this detector's constructor accepts `name`.

    Asked of the signature rather than listed in a table, so a detector that
    gains or loses a parameter does not need a second place updated to match.

    Two real cases. `Speeds` takes no scale, on purpose: `agree` is a test of
    three signs and a sign has no units, so there is nothing for a unit to
    divide. `Pips` and `BjorgumLevels` take no `source`, because they read a
    bar's whole shape rather than one float off it.
    """
    return name in inspect.signature(build).parameters


__all__ = [
    "BAR_DETECTORS",
    "CAN_SCALE",
    "DIMENSION",
    "NEEDS_PREVIOUS",
    "SCALED_BY",
    "Basis",
    "BjorgumLevels",
    "Candles",
    "Changepoint",
    "Channel",
    "Clock",
    "Cusum",
    "Detect",
    "Dimension",
    "Displacement",
    "Ensemble",
    "Event",
    "Focus",
    "Forget",
    "Gap",
    "Gaps",
    "Imbalance",
    "Kind",
    "Leg",
    "Level",
    "Levels",
    "Origin",
    "Pips",
    "Pivot",
    "PivotSource",
    "Point",
    "Reading",
    "RollingSpread",
    "SlopeMomentum",
    "Speeds",
    "Structure",
    "Swing",
    "TickMomentum",
    "Trend",
    "Trendline",
    "Trendlines",
    "Visit",
    "Zone",
    "build_detector",
    "check_scale",
    "read",
    "unit_for",
]
