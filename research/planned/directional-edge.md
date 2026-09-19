# Directional edge from the broker's own data

Status: **planned, not built.**

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
