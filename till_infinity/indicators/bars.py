"""Which float a bar is, for the detectors in this package.

Every detector here takes a **float**. Nautilus hands a registered indicator a
`Bar`. Something has to say which float a bar is, and that is all this module
does - but it is not a detail, because the two choices it carries are the two
places a detector gets silently miscalibrated.

## The reading

A level detector fed returns and a change detector fed levels both run, both
report, and both answer nothing. `Reading` is named rather than passed as a
lambda so that a discovery sweep can record which one it used and be asked for
the same thing again.

## The scale, and why there is no default

`Cusum.push` and `Focus.update` divide by a volatility unit so that one
threshold means the same thing on gold and on BTC. A detector that quietly
used 1.0 would be measuring price rather than movement, and would look
calibrated on any instrument that happens to trade near 1.0 - which is exactly
how that bug survives a test suite. So `unit` or `unit_from` has to be said,
and saying neither fails when the indicator is built rather than inside a
handler on a live feed.

`unit_from=Reading.RANGE` is the one with evidence behind it: the bar range
beats the close-to-close estimator as a volatility driver by a ratio of 0.648
within strata on FX and on 371 of 392 equities, and the advantage grows as the
window shortens - which is the regime a one-bar scale is in.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

#: Nanoseconds in a second. `ts_event` on a Nautilus bar is the bar's
#: **close**, not its open - MT5 stamps the open, and the adapter adds the bar
#: length to correct it. Getting that backwards does not shift a reading, it
#: silences the monotonicity guard downstream.
NANOS = 1_000_000_000.0


class Reading(StrEnum):
    """Which float a bar is."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    #: `(high + low + close) / 3`, the usual typical price.
    TYPICAL = "typical"
    #: `(high + low) / 2`.
    MEDIAN = "median"
    #: `high - low`. Non-negative, so it is a scale and never a signal.
    RANGE = "range"
    #: `(high - low) / close`. The range as a fraction, which is what scales a
    #: return.
    RELATIVE_RANGE = "relative_range"
    #: `close - open`, signed.
    BODY = "body"
    VOLUME = "volume"
    #: `ln(close / previous close)`. Needs a previous bar.
    LOG_RETURN = "log_return"
    #: `close / previous close - 1`. Needs a previous bar.
    RETURN = "return"


#: The readings that cannot be taken from one bar alone.
NEEDS_PREVIOUS = frozenset({Reading.LOG_RETURN, Reading.RETURN})

#: The readings that can be a scale: non-negative by construction. A signed
#: reading used as a unit divides by something that passes through zero.
CAN_SCALE = frozenset({Reading.RANGE, Reading.RELATIVE_RANGE, Reading.VOLUME})


class Dimension(StrEnum):
    """What a reading is measured in.

    A unit divides a reading, so the two have to be in compatible units, and
    this is the one check here worth making mechanical. **At a price near 1.0 a
    relative standard deviation and a price distance are the same number**, so
    a log return divided by a price range reads perfectly calibrated on EURUSD
    and is wrong by a factor of the price on gold - which is how a scale bug
    gets through a test suite built on an FX pair.
    """

    #: A price.
    LEVEL = "level"
    #: A price difference. What scales a price or another price difference.
    DIFFERENCE = "difference"
    #: Dimensionless. What scales a return.
    RELATIVE = "relative"
    #: A quantity.
    COUNT = "count"


DIMENSION: dict[Reading, Dimension] = {
    Reading.OPEN: Dimension.LEVEL,
    Reading.HIGH: Dimension.LEVEL,
    Reading.LOW: Dimension.LEVEL,
    Reading.CLOSE: Dimension.LEVEL,
    Reading.TYPICAL: Dimension.LEVEL,
    Reading.MEDIAN: Dimension.LEVEL,
    Reading.RANGE: Dimension.DIFFERENCE,
    Reading.BODY: Dimension.DIFFERENCE,
    Reading.RELATIVE_RANGE: Dimension.RELATIVE,
    Reading.LOG_RETURN: Dimension.RELATIVE,
    Reading.RETURN: Dimension.RELATIVE,
    Reading.VOLUME: Dimension.COUNT,
}

#: The dimension a unit must have, per the dimension of what it scales. A
#: price is scaled by a price *distance*, never by another price.
SCALED_BY: dict[Dimension, Dimension] = {
    Dimension.LEVEL: Dimension.DIFFERENCE,
    Dimension.DIFFERENCE: Dimension.DIFFERENCE,
    Dimension.RELATIVE: Dimension.RELATIVE,
    Dimension.COUNT: Dimension.COUNT,
}


def read(  # noqa: PLR0911 - a dispatch table reads better as one return each
    bar: Any, reading: Reading, previous: float | None = None
) -> float | None:
    """One float off one bar, or None when the reading needs a bar there is not.

    `previous` is the previous bar's close. `float()` is applied to Nautilus's
    `Price` and `Quantity`, which are **fixed-precision**: a declared precision
    truncates the feed long before this function sees it, so an instrument
    declared at two decimals reports a one-minute dispersion that is mostly its
    own rounding.
    """
    if reading is Reading.OPEN:
        return float(bar.open)
    if reading is Reading.HIGH:
        return float(bar.high)
    if reading is Reading.LOW:
        return float(bar.low)
    if reading is Reading.CLOSE:
        return float(bar.close)
    if reading is Reading.TYPICAL:
        return (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0
    if reading is Reading.MEDIAN:
        return (float(bar.high) + float(bar.low)) / 2.0
    if reading is Reading.RANGE:
        return float(bar.high) - float(bar.low)
    if reading is Reading.RELATIVE_RANGE:
        close = float(bar.close)
        return None if close == 0.0 else (float(bar.high) - float(bar.low)) / abs(close)
    if reading is Reading.BODY:
        return float(bar.close) - float(bar.open)
    if reading is Reading.VOLUME:
        return float(bar.volume)
    if previous is None or previous <= 0.0:
        return None
    close = float(bar.close)
    if close <= 0.0:
        return None
    if reading is Reading.LOG_RETURN:
        return math.log(close / previous)
    return close / previous - 1.0


def check_scale(name: str, source: Reading, unit: float, unit_from: Reading | None) -> None:
    """Refuse an indicator whose scale is missing or in the wrong units.

    Called from `__post_init__`, so both failures are at wiring time rather
    than inside a handler on a live feed. A fixed `unit` is taken on trust -
    there is nothing in a float that says what it measures - so the dimension
    check only applies to `unit_from`.
    """
    if unit <= 0.0 and unit_from is None:
        raise ValueError(
            f"{name} needs a scale: pass `unit` in price, or `unit_from` to "
            f"take one off each bar. A detector divides by its unit before "
            f"applying a threshold, so a guessed 1.0 would measure price "
            f"rather than movement, and would look calibrated on any "
            f"instrument trading near 1.0."
        )
    if unit_from is None:
        return
    if unit_from not in CAN_SCALE:
        raise ValueError(
            f"{name} cannot scale by {unit_from}: a unit divides, and that "
            f"reading is signed or passes through zero. Use {Reading.RANGE} "
            f"or a fixed `unit`."
        )
    wanted = SCALED_BY[DIMENSION[source]]
    got = DIMENSION[unit_from]
    if got is not wanted:
        raise ValueError(
            f"{name} reads {source} ({DIMENSION[source]}) and would scale it "
            f"by {unit_from} ({got}), which wants {wanted}. Dividing a "
            f"{DIMENSION[source]} by a {got} is a units error that is "
            f"invisible at a price near 1.0, where a relative spread and a "
            f"price distance are the same number, and is wrong by a factor of "
            f"the price everywhere else."
        )


#: The unit to scale each dimension by, as a reading off the same bar.
UNIT_FOR: dict[Dimension, Reading] = {
    Dimension.LEVEL: Reading.RANGE,
    Dimension.DIFFERENCE: Reading.RANGE,
    Dimension.RELATIVE: Reading.RELATIVE_RANGE,
    Dimension.COUNT: Reading.VOLUME,
}


def unit_for(source: Reading) -> Reading:
    """The per-bar unit that scales `source` without a dimension error.

    A detector carries one default `unit_from`, and a catalogue of sources it
    can read may span two dimensions - `BODY` is a price difference and
    `LOG_RETURN` is dimensionless, and both are changes a change-detector is
    about. One default cannot be right for both, so a sweep asks for the unit
    rather than inheriting it, and `check_scale` stays as the backstop for a
    pair assembled by hand.
    """
    return UNIT_FOR[SCALED_BY[DIMENSION[source]]]


def _alpha(span: int) -> float:
    """EWMA weight from a half-life in bars."""
    return 1.0 - 0.5 ** (1.0 / max(1, span))


def bar_input(indicator: Any, bar: Any) -> tuple[float | None, float]:
    """`(value, scale)` for one bar, advancing the indicator's bar state.

    Reads and writes `source`, `unit`, `unit_from`, `unit_span`, `_bar_prev`
    and `_bar_scale` on the indicator - declared as fields on each detector so
    they persist and restore with the rest of its state. `(None, scale)` means
    the bar carried no usable reading, and the caller returns without feeding.
    """
    value = read(bar, indicator.source, indicator._bar_prev)
    scale = _scale(indicator, bar)
    indicator._bar_prev = float(bar.close)
    if scale > 0.0:
        indicator._bar_scale = scale
    return value, scale


def _scale(indicator: Any, bar: Any) -> float:
    if indicator.unit > 0.0:
        return float(indicator.unit)
    if indicator.unit_from is None:
        return 0.0
    here = read(bar, indicator.unit_from, indicator._bar_prev)
    if here is None or here <= 0.0:
        # A doji, or a bar with no volume. Hold the running scale rather than
        # report zero, which would drop the reading entirely.
        return indicator._bar_scale
    if not indicator.unit_span or indicator._bar_scale <= 0.0:
        return here
    a = _alpha(indicator.unit_span)
    return (1.0 - a) * indicator._bar_scale + a * here


def reset_state(indicator: Any, config: frozenset[str]) -> None:
    """Every field that is not configuration, back to its initial value.

    Nautilus's `Indicator.reset` means *this indicator has never seen
    anything*, because it is called when the engine rewinds. Several detectors
    here already had a `reset` that meant something else - `Cusum` and `Focus`
    meant *a change has been acted on, accumulate from here*, which
    deliberately keeps `seen` and `total` because the stream did not restart.
    Those are now `restart`, and this is the engine's one.

    `config` is the field names that survive a reset. Naming them, rather than
    naming the state, means a field added later is treated as state by default:
    the failure mode is a reset that clears too much, which a test catches,
    rather than one that leaves a detector half-fresh, which nothing does.
    """
    from dataclasses import fields

    kept = {f.name: getattr(indicator, f.name) for f in fields(indicator) if f.name in config}
    fresh = type(indicator)(**kept)
    for f in fields(indicator):
        if f.name not in config:
            setattr(indicator, f.name, getattr(fresh, f.name))


def tick_price(tick: Any) -> float | None:
    """The one price a tick carries: a trade's price, or a quote's mid.

    The **mid** for a quote, because crossing the spread is not a price move:
    an alternating buy-side and sell-side print on an unchanged book would
    otherwise read as movement the width of the spread on every tick, which on
    an exotic is a whole bar range of fictional travel.
    """
    price = getattr(tick, "price", None)
    if price is not None:
        return float(price)
    bid = getattr(tick, "bid_price", None)
    ask = getattr(tick, "ask_price", None)
    if bid is None or ask is None:
        return None
    return (float(bid) + float(ask)) / 2.0


def tick_input(indicator: Any, tick: Any, *, relative: bool = False) -> tuple[float | None, float]:
    """`(value, scale)` for one tick, advancing the indicator's tick state.

    Reads and writes `tick_span`, `_tick_prev` and `_tick_scale`. The scale is
    an EWMA of how far the value moves between prints, because a tick has no
    range to take a unit from - there is no high and no low, only a print.

    **`relative` has to match what the detector is about**, exactly as
    `source` does on the bar path, and for the same reason. A detector that
    accumulates a *level* - `Cusum` - wants the price, scaled by a typical
    price step. A detector that tests for a shift in the *mean of what it is
    fed* - `Focus`, `Changepoint` - wants the change, scaled by a typical
    change: feeding it the level makes it test whether the mean price has
    shifted, which it has, every time price moves. `relative=True` returns a
    log change with a dimensionless scale, which keeps the pair in the same
    units that `check_scale` enforces on bars.

    **A detector calibrated on bars is not calibrated on ticks.** The threshold
    is in volatility units and so is scale-free, but the *arrival rate* is not:
    at tick rate the same threshold is crossed far more often per hour, so a
    rate measured on bars does not transfer. And on MT5 the tick stream is
    **sampled** - the terminal keeps what it chooses - so a tick-rate reading
    there is partly a measurement of the sampling.
    """
    price = tick_price(tick)
    if price is None:
        return None, indicator._tick_scale
    previous = indicator._tick_prev
    indicator._tick_prev = price
    value: float | None = price
    step: float | None = None
    if previous is not None:
        if relative:
            value = math.log(price / previous) if price > 0.0 and previous > 0.0 else None
            step = abs(value) if value is not None else None
        else:
            step = abs(price - previous)
    elif relative:
        # No previous print, so there is no change yet. Not zero: a zero change
        # would fold "we have not seen two ticks" in as evidence of stillness.
        value = None
    if step is not None:
        if indicator._tick_scale <= 0.0:
            indicator._tick_scale = step
        else:
            a = _alpha(indicator.tick_span)
            indicator._tick_scale += a * (step - indicator._tick_scale)
    return value, indicator._tick_scale


def check_feed(indicator: Any, kind: str) -> None:
    """Refuse a second kind of feed on one instance, loudly.

    A detector has one set of accumulators. Registering the same instance for
    bars *and* ticks pushes both into them, so it accumulates two clocks at
    once: the tick path crosses the threshold on its own and the bar path
    arrives into an accumulator it did not fill. Nothing about the result looks
    wrong - it is a number, in volatility units, from a detector reporting
    inputs - which is why this raises instead of logging.

    Reads and writes `_fed`.
    """
    if indicator._fed and indicator._fed != kind:
        raise RuntimeError(
            f"{type(indicator).__name__} was fed {indicator._fed} and is now "
            f"being fed {kind}. One instance has one set of accumulators, so "
            f"two feeds interleave two clocks into them and the result is a "
            f"plausible-looking number from neither. Register one instance "
            f"per feed."
        )
    indicator._fed = kind
