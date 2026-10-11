# Counted events over time: spikes, wicks and pivots, and what they carry

Asked for on 2026-10-11: *"number of spiking candle bodies over time, number of
big wicks over time, pivots over time not bars"*, then *"emas over wicks and
spiking bodies, can add slopes too, can add distance"*. Then, correctly:
*"hope these inputs are tested to see if they contribute anything meaningful"*.

They were. They do not.

## What was built

Three event streams, in `inputs.py`:

* **spiking** - a bar whose body exceeds three times the series' own trailing
  mean body. Close-to-open where opens exist, close-to-close where they do not.
* **wicking** - a bar with either wick longer than twice its body, with the
  body floored at a thousandth of the range so a doji does not make every bar
  a rejection.
* **pivots** - a swing high or low, **marked where it is confirmed rather than
  where it happened**. A swing at bar `k` is only knowable at `k + span`, and
  marking it at `k` would be a feature that knows the future.

Each becomes a **rate per hour** over every resolvable window, plus an EMA of
that rate, plus hours since the last event, plus the distance to the last
confirmed swing in volatility units. 48 features.

Rates rather than counts because that is the package rule applied to counting:
"eleven spikes in the window" is eleven per 2.75 hours at 15m and eleven per
11 hours at 1h, which is two statements. A rate per hour is one.

## What they carry

1,020 cells - six instruments including BTC, two timeframes, two horizons,
every feature. Each scored against its own **rotated control** (the same
series shifted a quarter, a half and three quarters of the way round: same
distribution, same autocorrelation, no alignment) and then **net of a trailing
standard deviation**, which is the null nothing in this repository has beaten.

| family | cells | raw minus control | net of trailing sd |
|---|---|---|---|
| ema_pivots | 170 | -0.001 | +0.006 |
| ema_spikes | 170 | +0.005 | -0.006 |
| ema_wicks | 170 | -0.032 | -0.005 |
| pivots | 170 | -0.002 | -0.001 |
| spikes | 170 | +0.007 | -0.015 |
| wicks | 170 | -0.032 | -0.003 |

**Every family is within 0.032 of its own control, and within 0.015 of zero
net of a trailing standard deviation.** Nothing here carries information about
the size of the next move that the simplest possible estimator does not
already have.

The `wicks` and `ema_wicks` families read -0.032 against control, which is the
largest number in the table and still nothing: it is a *negative* edge of
three hundredths, and it vanishes to -0.003 once the trailing standard
deviation is removed - so what little it had was volatility wearing a
costume.

## So they are off by default

`Features(counted=True)` builds them; nothing does by default. Kept rather
than deleted, for two reasons: the measurement is worth more than the code,
and a null that is easy to re-run is a null that stays checked. Off rather
than on because 48 features widen the multiple-comparison surface for every
caller of `Features`, and a feature that measures nothing should not charge
that to everyone.

`to_swing_high` and `to_swing_low` are behind the same flag for a **different**
reason: they were added after the measurement and have not been scored. Not
null - untested.

## Three bugs found on the way, two of them mine and one older

* **A flat series had a pivot on every bar.** The swing test used `<=` and
  `>=`, so on a constant stretch every neighbour ties and every bar is both a
  swing high and a swing low - thirty consecutive pivots on a synthetic
  fixture. Strict comparison says what is true: a flat series has no swings.
* **The distance to a swing was a price over a log-return spread**, and read
  **267 volatility units** on a series whose swings are under a percent. The
  same unit mismatch that once reported a spread of 136 volatility units on a
  market that trades. In logs it reads a median of 2.09 and a 95th percentile
  of 8.83, which is what a distance to a swing should look like.
* **`math.sqrt` raised a domain error on a real series.** `rolling` keeps a
  running sum to stay linear, so a window of near-zero squares can cancel to
  `-1e-20` - and the square root of that is an exception rather than a small
  number. It had been latent since `rolling` was written and only surfaced
  when these features put `Features` on a code path with long flat stretches.
  Clamped at the five places a root is taken.

The second one is worth a note beyond itself. I diagnosed it twice from the
output and was wrong both times, because **the patch fixing it had silently
failed to apply** - the string it matched on had been reflowed by the
formatter. I spent three passes explaining a number that had no explanation
other than "the fix is not in the file". Checking that an edit landed is
cheaper than reasoning about why it did not work.
