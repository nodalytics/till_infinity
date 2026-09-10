# Volatility as a cascade: four tests borrowed from turbulence

**Nothing here has been run.** This is a list of falsifiable propositions with
the harness each one needs, written down so they can be tested rather than
admired. Every claim below is a hypothesis about *our* instruments and is
expected to be wrong at least once.

## Where this comes from, stated plainly

The prompt was a history of the Navier-Stokes equation - two hundred years of
fluid dynamics, no market content whatsoever. What is worth borrowing is not
the equation but the **field it opened**, because turbulence and volatility
have been observed to share statistical signatures for thirty years: the same
cascade of energy from large scales to small, the same intermittency, the same
non-Gaussian increments that become Gaussian as the interval lengthens.

The analogy is **empirical, not mechanical**. Markets have no continuity
equation, no conservation law and no fixed geometry, so nothing here follows
*from* fluid dynamics. What follows is that a set of measurements which turned
out to be informative about one system are cheap to run on the other, and this
repository already has the shape they need - eight timeframes per instrument,
already in volatility units.

## One: does volatility cascade downward, and only downward?

In a turbulent flow energy enters at the large scale and cascades to the small.
The market claim is the same asymmetry: **coarse-timeframe volatility should
forecast fine-timeframe volatility better than the reverse.**

This is the sharpest of the four because it is *directional* and because a
symmetric result kills it outright. It also bears on something already
believed here on other grounds - `by_interval` measures sub-15m trading at
-821.75 against +35.03 at 15m and above, and the desk weights higher-timeframe
calls more heavily. Neither of those is evidence of a cascade; they are
consistent with one.

**The test.** For each instrument, take realised volatility per bar on each of
the eight timeframes. Compute the lead-lag correlation between coarse and fine
in both directions. The cascade predicts

    corr(vol_1h(t), vol_5m(t+k)) > corr(vol_5m(t), vol_1h(t+k))

for k > 0, and predicts the gap widens with the separation of the two scales.

**What kills it.** Symmetry. If the two correlations are the same within noise,
volatility is not cascading, it is simply shared - and the case for weighting
the higher timeframe has to come from somewhere else.

**What it would change.** `learned.py` currently gets `log_bar` - which
timeframe a row came from - and nothing about what the *other* timeframes are
doing at the same moment. If the cascade is real, the coarse-scale reading is a
leading feature for every finer series, and that is a feature this system can
actually compute: `Book` already holds an estimate per (feed, interval).

## Two: are the synthetics monofractal where the real markets are not?

Turbulent velocity increments are strongly non-Gaussian at small separations
and approach Gaussian at large ones, and the rate at which that happens is not
a single exponent - the scaling is *multifractal*. Financial returns have been
found to behave the same way.

The interesting version here is a discriminator rather than a description.
**The book is 72% synthetics** - Volatility indices, Boom, Crash, Jump, Step,
Range Break - and these are *generated processes with known constructions*.
There is no reason a generator should reproduce the multifractal scaling of a
real market, and good reason to think several of them will not.

**The test.** Structure functions. For each series compute

    S_q(dt) = mean(|log return over dt| ^ q)

across a range of `dt` and several `q`, fit `S_q(dt) ~ dt^zeta(q)`, and look at
whether `zeta(q)` is linear in `q`. Linear is monofractal - one exponent
describes every moment. Curved is multifractal.

**Why it matters more than it sounds.** `learned.py` pools every series into
one model on the argument that scale-free features make eurusd at 5m and
volatility_75_index at 4h "the same learning problem". If the synthetics are
monofractal and the real markets are not, that argument is **wrong for most of
the book**, and the pooling is averaging two different processes. The pooled
design was justified partly by necessity - a tree per series costs 525MB - so
finding this would be genuinely awkward rather than convenient.

**What kills it.** Everything coming out multifractal, or the estimates being
too noisy at our sample sizes to separate the two. The second is the likelier
failure and should be checked first on a synthetic series with a *known*
construction, where the answer is already known.

## Three: intermittency - fat tails should thin as the interval lengthens

The weakest of the four, in the sense that it is nearly certain to be true and
therefore says little. It is here because it is nearly free and because it
tests an assumption the volatility code makes without stating.

**The test.** Kurtosis of log returns by timeframe, per instrument. The
prediction is monotone decline from 1m to 1d.

**What it would change.** `volatility.py` chose mean absolute deviation over
standard deviation because "for fat-tailed financial returns the mean absolute
deviation answers that more stably". `MAD_TO_SIGMA` then converts between the
two using **sqrt(pi/2), which is the Gaussian ratio**. If tails vary by
timeframe, that constant is right at one horizon and wrong at the others - and
this repository has just spent a day on the consequences of applying that
constant inconsistently, so its *value* deserves the same scrutiny its
application got.

## Four: a Reynolds number for a market

Turbulence begins when inertial forces overwhelm viscous ones, and the
threshold is a dimensionless ratio rather than a speed. The market analogue
would be a ratio of order flow to the liquidity absorbing it - and unlike the
first three, this one is **speculative and has no established literature behind
it**. It is included because the ingredients are already on the bus: quote
arrival rate, spread, and the depth proxies in `sweeps`.

**The test.** Build `flow / liquidity` per instrument - quote intensity over
spread, as a first guess - and ask whether it precedes regime transitions
better than the volatility level does. `forecast_ratio` is the incumbent: it
separates level-holding by 5.1 points where the regime *level* separates it by
1.2, so anything proposed here has to beat 5.1 points to matter.

**What kills it.** Not beating `forecast_ratio`. And the honest prior is that
it will not, because the first three tests are borrowed from a literature with
thirty years of results behind them and this one is an analogy I constructed.

## The order to run them in

One first: it is the sharpest, the cheapest, and a positive result changes the
feature set immediately. Two second, because a negative result there undermines
the pooled learner and that is worth knowing early. Three is nearly free and
can ride along. Four last, or not at all.

All four read stored bars rather than the live path, so none of them depends on
the service being up - which matters given it spent nine days being OOM-killed
every two and a half hours ([starving.md](starving.md)).
