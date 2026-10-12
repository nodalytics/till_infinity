# The Q clock is three-quarters an activity clock

`seasonal.Profile` on `Q` is worth **+1055 nats** median on traded instruments
at 1h, by modelling how an hourly increment's variance depends on the hour. The
subordination literature - Clark 1973, Ane-Geman 2000 - says that is not about
*time*: returns are closer to i.i.d. Gaussian in equal increments of
**activity**, and 14:00 UTC simply contains more activity than 02:00.

So: **does sampling in volume time make the clock unnecessary?** Measured, it
does not - but it absorbs about three-quarters of it, which explains *why* the
clock works and predicts that it will keep working.

The harness is `research/ideas/volume_clock.py`.

## The variable is the right one and the control checks the method

MT5's `volume` on these feeds is **tick volume** - the count of price changes -
which is the trade-count variable the subordination literature actually uses
rather than a notional stand-in.

The Deriv generated feeds have **exactly constant** tick volume:
`Volatility_75` posts 90 ticks per 3m bar and 1800 per hour, interquartile
range **zero**. For those feeds volume time *is* calendar time by
construction, so the two clocks must agree - which makes them a test of the
harness before they are a control on its answer.

That is also prior support for the hypothesis: constant activity, constant
volatility, which is what those feeds show.

## Likelihoods cannot be compared across clocks

Resampling changes the observation set, so a density over volume bars and one
over calendar bars are different quantities and their log-likelihoods cannot be
subtracted. Every comparison here is therefore **scale-free** - `extent` is
peak over trough, kurtosis is a ratio of moments, clustering is a correlation -
or **internal to one clock**, with the clock's gain over a flat arm fitted on
the same observation set and reported per bar.

`extent` is the headline because it measures the thing directly: how much an
increment's variance depends on the hour it fell in. One means no profile.

## The answer

Eight traded instruments and four controls, both clocks built from the same 3m
window so they cover the same span, with the volume threshold set from that
window's own total so the bar counts match:

| | cells | extent calendar | extent volume | clock/bar calendar | clock/bar volume | kurtosis cal | kurtosis vol | clustering cal | clustering vol |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **traded** | 8 | **2.99** | **1.72** | **+0.0229** | **+0.0096** | **12.1** | **7.9** | **0.124** | **0.075** |
| **constant volume** | 4 | 1.30 | 1.32 | -0.0014 | -0.0007 | 3.2 | 3.0 | -0.004 | 0.012

**The controls agree between clocks on every statistic**, as constant volume
requires, and their bar counts agree to within one. The method is sound.

Their `extent` of **1.30 rather than 1.00 is the noise floor** of fitting a
four-harmonic profile on this sample length, and is what the traded figures
have to be read against. So:

* **extent: 2.99 to 1.72 against a floor of 1.31**, which is `1.68` of excess
  falling to `0.41` - **76% of the seasonality absorbed**, and it falls on
  **8 of 8** instruments (2.55 to 1.58, 2.94 to 1.86, 2.07 to 1.45, 3.03 to
  1.52, 3.39 to 2.18, 3.22 to 1.82, 3.08 to 1.80, 1.76 to 1.64).
* **the clock still pays in volume time**: +0.0096 per bar, which is 58% off
  the calendar figure but still **14x the controls' magnitude.** Volume time is
  not a substitute.
* **kurtosis 12.1 to 7.9**, so 46% of the excess over a Gaussian's 3 is
  absorbed - on 8 of 8 - but **returns are not Gaussian in volume time.**
  Subordination's strongest claim is partly right and not right.
* **clustering 0.124 to 0.075**: activity explains about 40% of volatility
  clustering.

## What it means for the desk

**Keep the clock.** The finding is not that it should be replaced - it is that
the clock is largely a *proxy for activity*, which is a mechanistic explanation
of a result that previously just worked. Three consequences:

1. It predicts the clock keeps working, because the mechanism is the trading
   day's activity profile rather than a fitted coincidence.
2. It predicts where the clock will **fail**: on a feed whose activity profile
   changes - a venue shifting hours, a holiday, a new session - the calendar
   profile goes stale while an activity-based one would not. The session
   profile measured as stable over nine years (`r` 0.94 to 0.99), so this has
   not bitten, and now there is a reason to expect it eventually could.
3. Switching the whole package to volume sampling would capture ~3/4 of the
   clock, cut kurtosis by 46% and clustering by 40% **for free** - but it
   changes the sampling basis of every measurement in the repository, and the
   residual clock gain says it would still want the profile on top. That is a
   large change for the last quarter of an effect already captured.

## Two corrections this harness needed, both caught by the controls

**The spans did not match.** The first version read the calendar arm from the
`1h` file and the volume arm from the `3m` file, both capped at the same row
count - so one covered thirteen years and the other about eight months. The
controls caught it: their two clocks must agree and `extent` came back 1.06
against 1.37. Building both arms from one fine series fixed it, and it had
inflated the apparent kurtosis absorption from `12.1 to 7.9` into
`27.7 to 11.8`.

**The bar counts did not match.** The threshold was the median of the `1h`
file's volume, which spans years at different tick rates, so XAGUSD came back
with 2,511 calendar bars against **14,813** volume ones. Taking the window's
own total volume over its calendar bar count makes them agree by construction -
necessary for the per-bar figures to mean anything.

Both were found by a control whose answer was known in advance, and neither
would have been visible in the traded rows alone. The second one moved the
kurtosis conclusion from "barely changes" to "falls on 8 of 8".
