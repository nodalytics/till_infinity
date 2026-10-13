# Volatility turns as events: levels, slopes, and the candlestick

The relationship work tested volatility spillover as a **linear
cross-correlation of log-volatility changes** and read
[0 of 106](statespace-volatility-relationships.md) against its null. That left an
event-shaped hole: a turn is an **event with a timestamp**, and a turn that
leads by a few spans with a varying magnitude smears out of a correlation
entirely. Linear dependence and event synchrony are different questions and only
the first was asked.

This asks the second, with three independent definitions of a turn and the
desk's own detector.

The harness is `research/ideas/volatility_turns.py`.

## The three definitions, and why each is worth a column

* **a CUSUM on the log-volatility level**, from `accruing.OneSided` - the exact
  likelihood ratio over all changepoints, run as a pair because "moves got
  bigger" and "moves got smaller" are different events;
* **a close beyond the previous bar's range**, which is the **levels** version:
  the previous high is a level and the event is the close crossing it, by more
  than a threshold in trailing true ranges;
* **a contested candle** - a bar whose range is well past its trailing average
  with a **body that is a small share of it**. A bar is a summary of the order
  flow in its interval: the body is how much of the move was net directional,
  the wicks are what was offered and rejected, and the settle is where the flow
  finished. A wide bar with a small body is size traded both ways with neither
  side winning, which is the bar shape a regime turns on.

A statistic on closes alone discards all of the third and most of the second.

## Four specification errors, all caught before the result

This took four passes and every one of them was a measurement fault rather than
a finding, which is worth recording because each would have produced a
confident null.

**The CUSUM was fed increments.** Log-volatility *increments* are near-white, so
a detector looking for a sustained mean shift in them finds nothing: it returned
a median of **0** turns per instrument over 2,246 spans. A turn is a shift in the
**level**, so it now sees the level's deviation from a trailing mean.

**The excess was normalised by a quantity that bounds it.** `close - previous
high` cannot much exceed the *current* bar's true range, because that range
already contains `|high - previous close|`. Scaled that way, 86% of spans
counted as events at a threshold of 0.25 and **none** at 1.0 - a scale with no
room for the question. Against a trailing average range the sweep runs 58.6% at
0.5, 22.3% at 1, **4.2% at 2** and 1.4% at 3.

**Two modules disagreed about the span.** `panel_volatility` carries its own
`SPAN` and its `aligned` cuts the matrix with it, so calling it from a harness
with `SPAN = 6` silently returned 24-bar spans while every turn index assumed 6.

**And a rate needs events.** With two turns a coincidence rate can only be 0,
0.5 or 1, and the first rotation null read a maximum of `+0.9911` off exactly
that. Instruments now need 15 turns before they are scored, and the threshold is
6 nats rather than the 12 `accruing` ships - 12 is calibrated for a false-alarm
rate, not for producing enough dated events to form a rate.

## Turns coincide, and the regime is what coincides

| detector | pairs | median | 99th pct | max | turns |
| --- | ---: | ---: | ---: | ---: | ---: |
| **traded, CUSUM on log-vol** | 110 | **+0.1541** | +0.6805 | +0.6879 | 16 |
| rotation null | 640 | **-0.0058** | +0.1386 | +0.4203 | 16 |
| traded, close beyond prev range | 380 | +0.0080 | +0.4510 | +0.5426 | 138 |
| traded, contested candle | 380 | **-0.0129** | +0.3152 | +0.3853 | 204 |
| shifted null, same definition | 2,280 | -0.0358 | +0.0612 | +0.2337 | - |

**21 of 110 traded pairs exceed the rotation null's maximum**, and the medians
separate cleanly: `+0.1541` against `-0.0058`.

**But only for the regime definition.** Gap events read `+0.0080` and contested
candles `-0.0129` against a shifted null of `-0.0358` - a difference of 0.023,
trivial beside 0.16. So **the volatility regime co-moves and individual
bar-level events do not.** Regime is a slow shared thing, consistent with a
cross-instrument volatility correlation of 0.52 and eleven currency drivers;
order flow in one hour is instrument-specific.

The candlestick arm earns its place by being the one that could have shown
otherwise. If order flow were shared across instruments, a wide contested bar is
exactly where it would appear.

## And nothing leads, under any definition

**0 of 110 ordered pairs** beat the rotation null's best lead rate of `0.3333`.
The best real reading is `GBPJPY` to `USDJPY` at `0.2105`, three spans back,
which is below a null that scans the same sixteen lags.

So the event-based route reaches the same conclusion as the linear one, by a
method that **could have overturned it**: contemporaneous, never predictive.
That is worth more than the original null was, because the original could not
have seen a lead of this shape and this one can.

## What to use

* **Define a volatility turn on the level, not the increment**, and give the
  detector enough events to form a rate - 15 per instrument, at a threshold
  chosen for event frequency rather than false-alarm rate.
* **Scale a level excess by a trailing range**, never by the bar's own.
* **Expect the regime to be shared and the bar not to be.** Cross-instrument
  information tells you what regime you are in, not what just happened
  somewhere else.
* **Do not look for a lead again without a new shape.** Price at 1h, price at
  3m, volatility changes, and now volatility turns as dated events are four
  independent attempts, all null against matched nulls, each with a planted arm
  proving the detector works.

## Related

* [Volatility relationships](statespace-volatility-relationships.md) - the
  linear spillover test this fills the hole in
* [The panel estimator](statespace-panel-volatility.md) - the forecasting use of
  the same contemporaneous structure
* [Levels](statespace-displacement-sequences.md) - the reversal-point sequence
  idea, which is the price-side version of an anchored event
