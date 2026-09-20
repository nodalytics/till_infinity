# Directional edge from the broker's own data

Status: **the horizon question is measured (2026-09-20). Nothing else is
built.** The answer is at the end: no edge in the level calls out to a day,
and the reason 1-5 minutes cannot work is arithmetic rather than signal.

The desk can now read the broker directly through the MT5 bridge. This asks
what that makes possible that was not possible before, and where a
directional edge is worth looking for - informed by everything that was
measured *not* to work on 2026-09-19.

## What the bridge gives that the desk did not have

| | why it matters |
|---|---|
| the broker's own OHLC (`/symbols/rates/pos`) | the price actually traded, not a consensus of other venues; long history on request - 20,000 bars pulled in one call |
| per-tick bid and ask | the **real, time-varying spread**, which on every test below was the entire result |
| `swap_long` / `swap_short` in the symbol spec | the carry on each instrument, directly |
| session hours per instrument | already learned at startup - 15 of 42 never close |
| our own fills | slippage, measured rather than assumed |

## What has already been ruled out

Every one of these was measured, out of sample, on 2026-09-19:

* **Deriv synthetics.** Volatility indices are random walks (variance ratio
  about 1.0 on every horizon); Crash and Boom are memoryless, with the drift
  exactly paying for the spike; ZMA scores 50.2-51.3% on them out of sample.
  No directional edge exists in them by construction. See
  `research/docs/coinbase-premium.md` for the method.
* **The desk's level calls.** A coin flip at 1, 5 and 15 minutes on 28,208
  real-market calls; a meta-model on all 59 recorded features scores AUC
  0.506. See `meta-labelling.md`.
* **The Coinbase premium.** No edge once overlapping windows are removed.

And the pattern across all of them: at 1-5 minutes the **gross** return is
zero and the **net** return is minus the spread. The spread, 1.5-3bp a round
trip, is not a detail at this horizon - it is the whole outcome.

## Where to look, and why the horizon comes first

The directional effects with the strongest published evidence live at
horizons long enough to clear costs:

1. **Time-series momentum** (Moskowitz, Ooi & Pedersen, *Time Series
   Momentum*, JFE 2012): an instrument's own past 1-12 month return predicts
   the next month, across FX, equity indices and commodities - the three
   classes the desk trades. Among the most replicated effects in the
   literature. Daily to monthly.
2. **FX carry**: long the higher-yielding currency, short the lower. The
   swap in the MT5 symbol spec *is* the carry, so this needs no new data
   source. Documented, with a known crash risk to size against.
3. **Intraday seasonality**: returns and volatility around session opens and
   closes. The desk already records `hour`. Worth measuring directly rather
   than through the level calls, which averaged it away.
4. **Cross-sectional momentum and reversal** across the 33 core instruments -
   ranking, not predicting, which removes the common market move.
5. **Volatility, not direction.** Volatility is forecastable where direction
   is not, and sizing to a forecast improves risk-adjusted return even with
   no directional edge at all. The desk already runs GARCH and an ensemble.

The first question is therefore not *which signal* but *at what horizon the
first edge clears the spread*. The desk is built to scalp 1-5 minutes; if
the evidence says edges start at a day, that is the finding, and it says
what to build.

## Method - the lessons of 2026-09-19, made rules

* **The broker's own bars and the broker's own spread.** Measured from
  ticks, not assumed per market class.
* **Walk-forward only**, with the label horizon purged and an embargo past
  it. Never shuffled cross-validation.
* **Against a null.** Every claim must beat the same test run on a shuffled
  or random-walk series. On 2026-09-19 the shuffled control reached t = 2.42
  by itself.
* **Non-overlapping windows** when the horizon exceeds the sampling step.
  Overlap turned a nothing into t = 4.55 on the Coinbase premium.
* **Count the tests.** Twenty cells at p < 0.05 produce one false edge; say
  how many were run.
* **Net of cost, always.** A gross edge smaller than the spread is not an
  edge.

## What would falsify it

* No candidate beats its shuffled null out of sample, net of the broker's
  spread, at any horizon the account can hold.
* Edges appear only at horizons far longer than the desk is built for -
  which would be a finding rather than a failure, because it names what to
  build instead.

## Result: the horizon sweep, 2026-09-20

The corrected entry-referenced label from `meta-labelling.md`, extended from 1
minute to 1 day on 28,208 level calls against 1,008,930 stored bars for the 33
core instruments. The exit tolerance widens with the horizon, so that calls
made before a market shuts are not silently dropped at the long end.

| horizon | n | call right | gross | mean absolute move | net raw | best constant rule |
|---|---|---|---|---|---|---|
| 1m | 26,682 | 50.5% | -0.01bp | **2.1bp** | -2.07 | -2.04 |
| 5m | 27,734 | 50.5% | -0.02 | 4.7 | -2.08 | -2.03 |
| 15m | 27,953 | 50.5% | -0.08 | 8.0 | -2.13 | -1.98 |
| 1h | 27,977 | 50.8% | -0.14 | 16.1 | -2.19 | -1.91 |
| 4h | 27,661 | 50.7% | -1.05 | 32.1 | -3.11 | -1.00 |
| 1d | 22,557 | 48.0% | -8.29 | 89.5 | -10.38 | **+6.20** |

### The 1-day row is overlap, not edge

It is the only row that looks like anything, and it does not survive the rule
this document already set. 22,557 daily windows drawn from 33 instruments over
23 days re-count the same day of return up to 35 times. Taking one call per
instrument per day instead:

| | n | mean | t |
|---|---|---|---|
| overlapping | 22,557 | -8.29bp | **-8.31** |
| non-overlapping | 635 | -4.83bp | **-0.94** |

Shuffling which side each call took reproduces an absolute t of 0.94 or more in
**34.5% of 400 runs**, so the non-overlapping result is what chance returns a
third of the time. 21 of 33 instruments favour inverting and 12 favour the raw
call, spread from brent at -86bp to us100 at +39bp - the shape of 635 noisy
observations, not of a shared effect. The `+6.20bp` in the table is also a rule
chosen on the test data, which is a second reason to discard it.

### The sign label was the wrong label, and the better one agrees

Checked 2026-09-20 against the labelling used by two candlestick-pattern papers:
Up / Flat / Down against a magnitude band, rather than the sign of the return.
The sign label counts a 0.1bp drift and a 50bp move as the same event, so it
could have been hiding a direction that costs ate.

It was not. Against a 4bp band - twice the round trip - **86.0% of one-minute
calls never move enough to pay for a trade**, and conditional on the market
actually moving, the call is still 49.3% to 50.7% at every horizon to four
hours. Whether a move is coming is mildly forecastable (AUC 0.573
within-instrument against a 0.511 shuffled null), which buys position sizing and
not a filter, because filtering a coin flip leaves a coin flip. Full result,
including three leakage errors made on the way, in
`../docs/banded-labels.md`.

### What the sweep does establish

The cost geometry, and this part is not a statistical claim:

| horizon | mean absolute move | round trip as a share of it |
|---|---|---|
| 1m | 2.1bp | ~100% |
| 15m | 8.0bp | ~25% |
| 1h | 16.1bp | ~12% |
| 4h | 32.1bp | ~6% |
| 1d | 89.5bp | ~2% |

**The desk scalps the one horizon where the spread cannot be cleared.** A
genuine 55% edge earns about 0.1bp gross at a minute against 2bp of cost; the
same 55% earns about 9bp at a day. No signal fixes a minute, and a mediocre
signal is enough at a day. That is what names what to build: the candidates
listed above are all daily-to-monthly, and that is not a coincidence.

Caveat carried forward: spreads here are the stated per-class figures (1.5bp FX
to 3bp crypto and energy), not measured per trade from the bridge's ticks. The
conclusion does not lean on them, because the gross column is already zero at
every horizon short of a day.

Tests run for this result: 6 horizons x 1 label, plus 1 non-overlapping
re-test and a 400-run shuffle. One cell of 6 crossed p < 0.05 naively and it is
the one the overlap test rejects.
