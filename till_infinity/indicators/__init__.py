"""The computations: a detector, a shape, a reading off a bar. No policy.

Everything here answers a question about market data and decides nothing.
`strategies` decides, `risk` sizes, `statespace` models - and all three read
this package, which is the whole reason it exists as a package.

## Why it is a package and not two copies

`statespace` was required to import nothing outside itself, so that it stayed
extractable in one move. The rule was honoured the only way it could be: by
**vendoring**. `statespace/accruing.py` held a field-for-field copy of FOCuS,
identical down to the threshold to the `Focus` that now lives in
`changepoint.py`, and the drift between them was caught by a *persistence
collision* rather than by review - the
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

**One of ours is an exact duplicate.** `trend.py`'s own `fit` returns a slope
and `r2` that agree with Nautilus's `trend.LinearRegression` to 1e-9, so prefer
the framework's for the fit. What `Channel` adds is the bands, `slope_vol` and
the vol-scaled readings, and that is the part worth keeping.

**One is the same indicator with a different edge.** `trend.py`'s own `atr` and
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

Seven modules. The names a config or a discovery sweep uses to ask for one
detector are not these - they are the keys of `BAR_DETECTORS`, `TICK_DETECTORS`
and `FRAMEWORK` below, and several of them live in the same module.

| module | what it answers | fed by |
|---|---|---|
| `bars` | which float a bar is, and what scales it | bars, ticks |
| `changepoint` | has the regime changed, and where did it start | bars |
| `momentum` | how far has price run, do the speeds agree, who is moving | bars, ticks |
| `trend` | trending or ranging, a walk or not, and on what line | bars, functions |
| `levels` | which prices are defended, where the leg came from, is the hole still there | bars |
| `candles` | did this bar reject a price | bars, functions |
| `spread` | what will this cost, over a rolling window | quotes |

Some of this is functions over a sequence of bars rather than an `Indicator`:
`candles`' shape tests, `trend`'s `ratio`, `fit` and `atr`, and `levels`'
`gaps` and `displacement`. An `Indicator` is for state the engine feeds; a
shape test over two bars has no state, and a window fit called with an explicit
list is clearer than one that reads a window it also maintains. The
`Displacement` and `Gaps` indicators are the incremental forms of those last
two, and exist because the live versions of those questions need a causal
answer: a gap list holding only *unfilled* gaps is lookahead the moment it is
read as of a time before the fill was known, which is a mistake this desk has
already paid +0.50R a trade for.

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
from .grouping import Group, cluster, common, crowding, modes, nearest, residual
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
    Sided,
    Structure,
    Swing,
    Visit,
    Zone,
)
from .momentum import Basis, Cusum, Ensemble, Event, SlopeMomentum, Speeds, TickMomentum
from .spread import RollingSpread
from .trend import Channel, Pivot, Trend, Trendline, Trendlines, VarianceRatio

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
    # **The same class under the name it is actually known by.** `Trend` *is*
    # Kaufman's efficiency ratio - net travel over gross - and a config that
    # wants an efficiency ratio should be able to say so and get ours rather
    # than reaching for `momentum.EfficiencyRatio`, which reports
    # `(period-1)/period` on a straight line where the answer is 1.0 by
    # definition. Deliberately absent from `FRAMEWORK` for that reason, and
    # named here so the absence does not read as an omission.
    "efficiency": (Trend, (Reading.CLOSE, Reading.TYPICAL)),
    "speeds": (Speeds, (Reading.LOG_RETURN, Reading.RETURN)),
    "displacement": (Displacement, (Reading.CLOSE,)),
    "gaps": (Gaps, (Reading.CLOSE,)),
    "trendlines": (Trendlines, (Reading.CLOSE,)),
    # The one trend statistic here with a **null**: VR = 1 under a random walk
    # by construction, so "is this trending" has a reference point rather than
    # a threshold somebody chose. `efficiency` is the readable heuristic;
    # this is what a claim is checked against.
    "variance_ratio": (VarianceRatio, (Reading.LOG_RETURN, Reading.RETURN)),
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


#: Detectors the engine feeds with **ticks** rather than bars, by name.
#:
#: Separate from `BAR_DETECTORS` because the registration call differs -
#: `register_indicator_for_quote_ticks` and
#: `register_indicator_for_trade_ticks` rather than `..._for_bars` - and a
#: catalogue that mixed them would need a flag per entry saying which.
#:
#: `spread` is **ours**, and the reason is the same as `efficiency`'s:
#: `SpreadAnalyzer.average` stops updating once its window fills, measured on
#: 1.221.0, because it appends a value and then subtracts the one it just
#: appended. So it is absent from `FRAMEWORK` and present here, and a config
#: that wants a rolling spread gets the one that keeps moving.
TICK_DETECTORS: dict[str, tuple[Callable[..., object], tuple[str, ...]]] = {
    "spread": (RollingSpread, ("quotes",)),
    # Quotes *and* trades: it signs by `aggressor_side` where a venue sends
    # trades and by which side of the quote moved where it does not.
    "ticks": (TickMomentum, ("quotes", "trades")),
}


#: The side words a declaration may use, and the field suffix each one names.
#:
#: `up` and `down` are this package's own vocabulary - `momentum.Event.side` is
#: already one of those two words, and a leaf of computations has no business
#: knowing what a desk does with a direction. `buy`, `sell`, `long` and `short`
#: are accepted because they are the spelling the desk's own side-keyed
#: configuration already uses: `risk/scaling.overshoot_for` prefers
#: `boom_500_index.sell` over `boom_500_index`, and `strategies/exits.py` reads
#: the same spelling. Two spellings for one idea across one config file would
#: be a second syntax, which is the thing `name:source` exists not to be.
SIDES: dict[str, str] = {
    "up": "up",
    "buy": "up",
    "long": "up",
    "down": "down",
    "sell": "down",
    "short": "down",
}


def declaration(rest: object) -> tuple[str | None, dict[str, float | int]]:
    """A detector's `name:` tail, split into the source and the parameters.

    **One syntax, extended rather than replaced.** `cusum:typical` and `rsi:7`
    reach here as `"typical"` and `"7"`, contain no `=`, and come back as the
    source they always were - the whole point of `name:source` is that "a
    strategy using both should not have to say which is which", so this does
    not fork into a second spelling.

    What is new is a comma list of parameters after the source, where a
    parameter may be **keyed by side**:

        cusum:typical,threshold.buy=1.2,threshold.sell=2.4

    `param.side` becomes `param_up` or `param_down` per `SIDES`, which is the
    suffix the detector declares the pair under. The source may be omitted -
    `cusum:,threshold.sell=2.4` - and a parameter needs no side at all, because
    a per-side parameter is just a second parameter and nothing here should
    make it a special case.

    Parsed here rather than in each registrar because `strategies/desk.py` and
    `statespace/actor.py` both hand `build_detector` the **whole** tail after
    the colon, so a grammar added here reaches both without either changing.
    """
    if rest is None:
        return None, {}
    source: str | None = None
    params: dict[str, float | int] = {}
    for position, part in enumerate(str(rest).split(",")):
        term = part.strip()
        if not term:
            continue
        if "=" not in term:
            if position or source is not None:
                raise ValueError(
                    f"{rest!r} names {term!r} where a parameter was expected. "
                    f"The source comes first and there is one of it: "
                    f"`source,param=value,param.side=value`."
                )
            source = term
            continue
        key, _, value = term.partition("=")
        field_name, dot, side = key.strip().partition(".")
        if not field_name:
            raise ValueError(f"{rest!r} has a value with no parameter name in {term!r}.")
        if dot:
            suffix = SIDES.get(side.strip().lower())
            if suffix is None:
                raise ValueError(
                    f"{term!r} names the side {side.strip()!r}, which is not a "
                    f"side. Known: {', '.join(sorted(SIDES))}."
                )
            field_name = f"{field_name}_{suffix}"
        params[field_name] = _number(term, value)
    return source, params


def _number(term: str, value: str) -> float | int:
    """A declared parameter's value, as an int where it was written as one.

    An int where the text has no point or exponent, because a window or a span
    is a count of bars and handing a dataclass `5.0` for one is a float that
    reads as an integer everywhere it is printed.
    """
    text = value.strip()
    try:
        return int(text) if text.lstrip("+-").isdigit() else float(text)
    except ValueError:
        raise ValueError(f"{term!r} has no number in it: {text!r} is not one.") from None


def _accepted(
    build: Callable[..., object], name: str, params: dict[str, object]
) -> dict[str, object]:
    """`params`, having refused any this detector does not take.

    Asked of the signature, like `_takes`, so a detector that gains or loses a
    per-side pair needs nothing updated here. A declared parameter the detector
    silently dropped would be a sweep reporting a null for a question it never
    asked - the same failure `Desk._register` raises on an unknown name for.
    """
    for key in params:
        if _takes(build, key):
            continue
        base, _, side = key.rpartition("_")
        if side in ("up", "down") and _takes(build, base):
            raise ValueError(
                f"{name} has one {base} for both sides, so {key!r} cannot be "
                f"declared. A per-side parameter needs the detector to hold a "
                f"{base}_up and a {base}_down - which doubles its search, so a "
                f"detector only grows them where the two sides were measured "
                f"to differ."
            )
        raise ValueError(f"{name} takes no {key!r}.")
    return params


def build_detector(name: str, source: object = None, **kwargs: object) -> object:
    """One catalogued detector on one source, scaled correctly for it.

    The single entry point a discovery sweep should use. Picking the unit here
    rather than at each call site is what stops a sweep spending a trial on a
    detector whose threshold is in the wrong units - and trials are the scarce
    thing: at a target Sharpe of 1.5, one month of data supports about one.

    `source` carries the whole tail a config wrote after the colon, so it may
    name parameters as well as the reading - see `declaration`. An explicit
    keyword argument wins over a declared one, because a caller holding the
    object is more specific than a string a config carried.
    """
    source, declared = declaration(source)
    kwargs = {**declared, **kwargs}
    if name in TICK_DETECTORS:
        if source is not None:
            raise ValueError(
                f"{name!r} is fed ticks and takes no `source`: a tick has no "
                f"high, low or close for a `Reading` to pick."
            )
        build, _ = TICK_DETECTORS[name]
        return build(**_accepted(build, name, kwargs))  # type: ignore[arg-type]
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
        if set(declared) - {"period"}:
            raise ValueError(
                f"{name!r} is one of Nautilus's indicators and takes a period "
                f"and nothing else, so {sorted(set(declared) - {'period'})} "
                f"cannot be declared on it. Its parameters are not ours to "
                f"add sides to."
            )
        return framework(name, kwargs.get("period"))  # type: ignore[arg-type]
    if name not in BAR_DETECTORS:
        raise ValueError(
            f"{name!r} is not a detector. Ours, on bars: "
            f"{sorted(BAR_DETECTORS)}. Ours, on ticks: "
            f"{sorted(TICK_DETECTORS)}. Nautilus's: {sorted(FRAMEWORK)}."
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
        return build(**_accepted(build, name, kwargs))  # type: ignore[arg-type]
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
    return build(**_accepted(build, name, kwargs))  # type: ignore[arg-type]


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
    "SIDES",
    "TICK_DETECTORS",
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
    "Group",
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
    "Sided",
    "SlopeMomentum",
    "Speeds",
    "Structure",
    "Swing",
    "TickMomentum",
    "Trend",
    "Trendline",
    "Trendlines",
    "VarianceRatio",
    "Visit",
    "Zone",
    "build_detector",
    "check_scale",
    "cluster",
    "common",
    "crowding",
    "declaration",
    "modes",
    "nearest",
    "read",
    "residual",
    "unit_for",
]
