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

---

# Results, 2026-09-11

All four were run. The harnesses are `research/harness/cascade.py`,
`fractal.py`, `tails.py` and `reynolds.py`; all four read the research store on
the lab box rather than production, for the reason `starving.md` records.

**The data.** `research.db`: 3,954,447 one-minute bars over 60 days
(2026-07-12 to 2026-09-10), 53 feeds, seven intervals rather than the eight the
plan assumed - there is no 2h rung. Plus 6,950,687 quotes with bid and ask, on
all 53 feeds, covering **one 24-hour window** and no more, which is what test
four had to live inside. `journal.db` supplied the level outcomes for test four,
joined to the decisions that carried `forecast_ratio`.

Short version, before the detail:

| | |
|---|---|
| **One** | **Confirmed, and small.** Coarse leads fine at every one of fourteen scale pairs, survives the split in both halves, and is absent from its own surrogate. The effect is +0.01 to +0.03 of rank correlation on a base of 0.06 to 0.20. And it is **a real-market property**: synthetics score +0.004 where metals score +0.039 and crypto +0.046 |
| **Two** | **The discriminator does not work as specified, and 13 feeds answer anyway.** The structure-function estimator reads the *marginal*, not the cascade - an i.i.d. Student-t with `lambda^2 = 0` by construction scores 0.157, higher than any real instrument. What survives the control: the 12 Volatility indices and Step index are **exactly Brownian** - `lambda^2` within noise of zero, `H = 0.50`, 1m kurtosis 2.98 to 3.02. The Boom, Crash, Jump and Range Break indices are not, and are indistinguishable from the real book |
| **Three** | **Confirmed, and the constant is worse than feared.** Kurtosis falls 27.2 to 3.1 from 1m to 1d, but only 14 of 53 feeds decline at *every* step. `sigma / MAD` runs **1.546 at 1m against the code's 1.2533** - across all 53 feeds the constant is 23% low at 1m and 16% at 5m, and on FX alone **27% and 23%**. On the generated book it is right everywhere from 5m up, because those series are Gaussian, which drags the pooled median down |
| **Four** | **Null, as predicted, and for three reasons rather than one.** On 24 of 53 feeds the flow term is a constant by construction. On the level-holding target the sample is too small to resolve 5.1 points and the pooled ordering reverses in 8 of 10 strata. Where a signal does appear it is `intensity` alone - the liquidity denominator adds 0.004 of AUC - and it is beaten by `vol_stretch`, which is already published on every call |

## One: volatility cascades downward, by about one point of correlation

### What was measured, and why not the obvious thing

The proposition as written needs the two volatilities on one clock, and how
that is done decides the answer. A trailing-window reading - coarse as the last
hour, fine as the last five minutes - makes the coarse window *contain* the
fine one, and the asymmetry that produces is arithmetic.

So both readings are taken over **the same span** and differ only in resolution
(Muller et al., 1997). On the grid of coarse bars, with `m = c/f` fine returns
inside each:

    C_i = |sum of the m fine returns|      aggregate, then take the magnitude
    F_i = mean |fine return|               take the magnitude, then aggregate

Lags are whole coarse bars, so `C_i` and `F_{i+k}` share no data at any k >= 1.
Gaps are dropped rather than bridged: a weekend spanned by one return is the
largest observation in every FX series and it is not a market move, and the
coarse leg would swallow it where the fine leg would not.

`asym = corr(C_t, F_{t+k}) - corr(F_t, C_{t+k})`, Spearman, computed per feed
and averaged over the 53, with the standard error taken across feeds.

### The result

Fourteen scale pairs. 1d as the coarse leg was dropped: 60 days leaves fewer
than 60 complete daily buckets and the estimate would be reading a handful of
observations.

At lag 1, the extremes and the middle:

| pair | C→F | F→C | asym | SE | t | feeds positive | surrogate | reversed | first half | second half |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5m/1m | +0.1847 | +0.1742 | **+0.0105** | 0.0017 | +6.22 | 77.4% | −0.0001 | −0.0099 | +0.0100 | +0.0110 |
| 15m/1m | +0.2032 | +0.1841 | **+0.0191** | 0.0033 | +5.80 | 79.2% | +0.0013 | −0.0217 | +0.0176 | +0.0212 |
| 30m/1m | +0.1955 | +0.1775 | **+0.0180** | 0.0049 | +3.70 | 66.0% | −0.0002 | −0.0260 | +0.0197 | +0.0174 |
| 30m/15m | +0.1233 | +0.1206 | +0.0027 | 0.0033 | +0.83 | 50.9% | −0.0015 | −0.0083 | +0.0041 | +0.0011 |
| 1h/15m | +0.1347 | +0.1312 | +0.0035 | 0.0050 | +0.70 | 47.2% | +0.0022 | −0.0099 | +0.0031 | +0.0042 |
| 4h/5m | +0.0790 | +0.0552 | **+0.0238** | 0.0123 | +1.94 | 58.5% | −0.0198 | −0.0280 | +0.0265 | +0.0203 |

**`asym` is positive on all fourteen pairs at lag 1, and positive in both halves
of the split on all fourteen.** Pearson on logs agrees on thirteen of fourteen
(1h/15m goes to −0.0007, which is the pair the rank statistic also puts at
+0.0035, i.e. nothing).

### What the controls say

The null here is not zero, and assuming it were would have been the whole error.
Two were computed from each feed's own data before the numbers were seen:

* **Phase-randomised surrogate.** `log|r|` at 1m, Fourier phases randomised,
  amplitudes kept: the **same autocovariance of log volatility at every lag**,
  so identical persistence and identical long memory, but Gaussian, linear, and
  therefore time-reversible. This is precisely "volatility is simply shared".
  It scores between **−0.027 and +0.003** across all fourteen pairs - flat.
* **Shuffle.** The 1m returns permuted. Also flat, −0.013 to +0.031.
* **Time reversal**, which is a check on the harness rather than on the market:
  reversing time exchanges the two correlations by identity, and the reversed
  arm is negative at every pair at lag 1 where the real arm is positive.

So the asymmetry is not persistence, not long memory, and not the estimator.

### The part that was not predicted

**The cascade is a real-market property. On the generated book it is nearly
absent.** Averaged over all pairs at lag 1:

| class | feeds | asym |
| --- | --- | --- |
| crypto | 2 | **+0.0460** |
| metal | 2 | **+0.0389** |
| fx | 15 | +0.0230 |
| index | 8 | +0.0051 |
| **synthetic** | 26 | **+0.0042** |

`strata.compare` cut the two directions within every scale pair and every class
and reported **no reversals** - coarse→fine wins everywhere - but the size of
the win differs by a factor of ten between metals and synthetics. The book is
72% synthetics, so a pooled cascade feature would be fitted mostly on the
instruments that do not have one.

### The sub-prediction, which half holds

The proposition also says the gap widens with the separation of the scales. It
broadly does, with two dips:

| coarse/fine | 2 | 3 | 4 | 5 | 6 | 8 | 12 | 15 | 16 | 30 | 48 | 60 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| asym (lag 1) | +0.0062 | +0.0080 | +0.0077 | +0.0105 | +0.0144 | +0.0170 | +0.0081 | +0.0191 | +0.0172 | +0.0180 | +0.0238 | +0.0114 |

Rising from 2x to 48x, and not monotone. The 60x cell - 1h against 1m - is the
widest separation available and sits below the 15x cell.

### What this does not say

**It does not say the cascade is worth a feature.** +0.01 to +0.03 of rank
correlation is the effect, on base correlations of 0.06 to 0.20 - the coarse
reading leads the fine one by **five to fifteen percent of a correlation that is
itself small**. `similarity.md` and `learning.md` both record features of about
this size arriving at the model and buying nothing.

**It does not say the direction is causal.** `C` and `F` are computed from the
same returns; the asymmetry is between two summaries of one window, and "the
magnitude of the sum leads the sum of magnitudes" is a statement about
aggregation before it is a statement about energy.

**It does not transport to the traded intervals cleanly.** The two pairs where
`asym` is indistinguishable from zero are 30m/15m and 1h/15m - which is exactly
the region `by_interval` says the desk makes money in.

## Two: the test does not discriminate, and twelve instruments answer anyway

### The control fired first, which is why there is a result at all

`cascading.md` named the likely failure itself - "the estimates being too noisy
at our sample sizes to separate the two ... should be checked first on a
synthetic series with a known construction". Five control arms ran through the
identical estimator at n = 85,857, before any instrument was read:

| arm | `lambda^2` | sd | known | what it is |
| --- | --- | --- | --- | --- |
| gaussian | −0.00090 | 0.0041 | 0.000 | i.i.d. normal random walk |
| **iid-t3** | **+0.15688** | 0.0600 | **0.000** | i.i.d. Student-t(3): fat marginal, no cascade |
| **shuffled** | **+0.09586** | 0.0675 | **0.000** | each feed's own returns, order destroyed |
| mrw-0.02 | +0.01772 | 0.0052 | 0.020 | multifractal random walk, Gaussian innovations |
| mrw-0.05 | +0.02983 | 0.0129 | 0.050 | the same, stronger |
| **mrw-t3-0.05** | **+0.14488** | 0.0369 | **0.050** | a real cascade under a fat marginal |

Read the second and third rows. **A series with `lambda^2 = 0` by construction
scores 0.157 because its marginal is fat.** Read the last: a genuine cascade of
0.05 under the same marginal scores 0.145, which is within noise of the series
that has no cascade at all.

So the structure-function estimator, at 60 days of 1m bars, measures **how fast
a heavy marginal Gaussianises under aggregation** and only incidentally measures
scaling. That is not noise - the Gaussian arm is tight at ±0.004 - it is bias,
and it runs in the direction that manufactures multifractality.

The shuffle is the sharpest version because it is per feed and holds the
marginal exactly fixed. **Not one of the 27 real-market feeds exceeds its own
shuffle.** Nor does the estimate fail the split: `lambda^2` agrees in sign
between the two halves of the 60 days on 47 of 53 feeds, and on 15 of 15 in FX.

### What survives: thirteen feeds are provably Brownian

Where the marginal is *thin*, the estimator is decisive, because there is
nothing for it to confuse the cascade with. Thirteen feeds have both their own
`lambda^2` and their own shuffle inside three standard deviations of the
Gaussian arm:

| feed | `lambda^2` | H | kurtosis at 1m |
| --- | --- | --- | --- |
| volatility_10_index | −0.00168 | 0.4949 | 3.02 |
| volatility_25_index | +0.00677 | 0.5064 | 3.00 |
| volatility_50_index | −0.00138 | 0.5108 | 3.00 |
| volatility_75_index | −0.00350 | 0.4985 | 2.98 |
| volatility_100_index | +0.00175 | 0.4958 | 3.02 |
| the seven (1s) variants | −0.0057 to +0.0037 | 0.4935 to 0.5049 | 2.98 to 3.02 |
| step_index | −0.00752 | 0.5011 | 2.98 |

`H = 0.50`, kurtosis 3.00, no intermittency, and a shuffle that changes nothing.
**These are geometric Brownian motion.** The hypothesis was right about them.

It is wrong about the other half of the generated book. Boom, Crash, Jump and
Range Break sit at `lambda^2` 0.055 to 0.186, interleaved with the real
instruments - `range_break_200_index` at 0.186 is the highest reading in the
study, above usdcad at 0.156 and gold at 0.135.

### The one clean discriminator, which is the sign rather than the level

`lambda^2` minus the feed's own shuffle removes the marginal and leaves
something that separates:

| | feeds | mean delta | share above their own shuffle |
| --- | --- | --- | --- |
| **real** | 27 | **−0.042** | **0 of 27** |
| generated | 26 | −0.002 | 10 of 26 |

Every real instrument sits *below* its own shuffle, by 0.03 to 0.05; the
generated book sits on it. The sign is the opposite of the naive expectation and
that is the point: volatility clustering keeps aggregated returns fat for
longer, which makes the high moments grow *faster* with `dt` and the exponent
curve *less*. What the delta detects is clustering, not multifractality, and it
detects it in every real market and in almost no generated one. `strata.compare`
on the delta finds no reversals within class.

### What this means for the pooled learner, which is less than hoped

The argument in `learned.py` is that scale-free features make eurusd at 5m and
volatility_75_index at 4h the same learning problem. This test cannot convict it
and does not acquit it:

* For **12 of 53 feeds** - the Volatility indices - the argument is now measured
  to be wrong in a specific way. Those series are Brownian with a fixed `H` and
  no intermittency. There is no scaling structure for a shared model to learn
  from them, and no scaling structure they can contribute to anything else.
  Whatever the pooled learner gets from those rows, it is not multifractal
  scaling, because there is none.
* For the other 40 the test is silent, because the statistic that would answer
  is confounded by the marginal.

**It is not the awkward finding the plan hoped for.** The awkward version would
have been "the synthetics are monofractal and the real markets are not, so the
pooling averages two processes". What is true is narrower: *some* of the
synthetics are monofractal, about half are not, and the ones that are happen to
be the ones whose returns are Gaussian, which test three then finds independently
from a completely different statistic.

### What would make the test work

Not more data of this kind. The bias is in the estimator, not in `n`. The
methods that separate scaling from the marginal - magnitude cumulants, wavelet
leaders, or comparing against per-feed surrogates as here - all require the
comparison to be **against the feed's own shuffle rather than against zero**,
which the plan did not specify and which is the single correction this run
contributes.

## Three: tails thin, and the Gaussian constant is 23% wrong where it is used

Medians across 53 feeds, with a Gaussian arm drawn at each interval's own sample
size so the estimator can be read against a known answer:

| interval | median n | kurtosis | Hill | p99/median | **sigma / MAD** | gaussian kurtosis | gaussian ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1m | 85,778 | 27.20 | 0.349 | 7.35 | **1.5461** | 3.000 | 1.2533 |
| 5m | 17,117 | 9.49 | 0.302 | 6.61 | **1.4489** | 3.002 | 1.2534 |
| 15m | 5,748 | 7.59 | 0.290 | 6.46 | 1.4166 | 2.997 | 1.2532 |
| 30m | 2,875 | 7.11 | 0.280 | 6.28 | 1.4087 | 2.995 | 1.2534 |
| 1h | 1,437 | 7.19 | 0.286 | 6.27 | 1.4080 | 2.997 | 1.2521 |
| 4h | 359 | 4.58 | 0.205 | 5.29 | 1.3682 | 2.975 | 1.2539 |
| 1d | 59 | 3.08 | — | 3.84 | 1.2750 | 2.967 | 1.2539 |

The Gaussian arm returns 3.00 and 1.2533 at every sample size down to n = 59, so
none of the decline below is small-sample bias.

**The prediction holds end to end and fails step by step.** 48 of 53 feeds are
thinner at 1d than at 1m by kurtosis and 47 of 53 by p99/median; 41 of 53 are
thinner at 4h than at 1m by Hill, which stops at 4h because its top five percent
of 59 daily bars is three observations. But only **14 of 53 decline at every
step**, 5 of 53 by Hill and 2 of 53 by p99/median, and the median profile itself
turns back up between 30m and 1h. "Monotone decline from 1m to 1d" is true of
the book and false of most of its instruments.

### The constant

`consensus_vol.MAD_TO_SIGMA` is `sqrt(pi/2) = 1.25331`, and
`context/timing.MAD_TO_SIGMA` is its reciprocal for the other direction. Both
are the Gaussian ratio. The measured ratio:

| class | 1m | 5m | 15m | 30m | 1h | 4h | 1d |
| --- | --- | --- | --- | --- | --- | --- | --- |
| crypto | 1.638 | 1.593 | 1.598 | 1.617 | 1.624 | 1.650 | 1.537 |
| fx | 1.596 | 1.543 | 1.521 | 1.522 | 1.517 | 1.512 | 1.393 |
| index | 1.526 | 1.465 | 1.453 | 1.459 | 1.451 | 1.423 | 1.281 |
| metal | 1.500 | 1.449 | 1.446 | 1.435 | 1.412 | 1.362 | 1.264 |
| **synthetic** | 1.347 | **1.257** | **1.256** | **1.255** | **1.257** | **1.257** | **1.255** |

**The constant is exactly right for the generated book from 5m up and wrong by a
fifth to a quarter on everything else**, which is the same fact test two found by
a different route: those series are Gaussian. Against the median over all 53
feeds the error is +23.4% at 1m, +15.6% at 5m, +13.0% at 15m, +12.3% at 1h,
+9.2% at 4h and +1.7% at 1d - and that median is dragged down by the 26 generated
feeds sitting on the constant. **On FX alone it is +27.3% at 1m, +23.1% at 5m and
still +20.7% at 4h.** It is in one direction throughout, always understating
sigma for a given MAD.

It varies by timeframe, which is the failure mode the plan worried about: the
constant is right at one horizon and wrong at the others, so it cannot be
absorbed by whatever thresholds were tuned against it. `strata.compare` on fast
(1m-15m) against slow (30m-1d) intervals finds the fast ratio higher in every
class, no reversals: 1.515 against 1.391.

It is also stable. Between the two halves of the 60 days the median absolute
change in the ratio is 0.009 at 1m rising to 0.056 at 4h - an order of magnitude
smaller than the 0.29 it sits above the Gaussian value at 1m.

The worst individual cells at 5m are the yen crosses - usdjpy at **2.055**
(+64% on the constant, kurtosis 237), eurjpy 2.007, gbpjpy 1.912 - and
`range_break_200_index` at 2.485. The yen kurtoses are large enough to be worth
a separate look at whether they are market or feed.

### What this changes, and what it does not

`timing.py` already records the one place the constant was checked against
reality: "the realised median excursion of 3.75 implies a per-bar sigma of 1.24
against this factor's 1.253". That check was run on excursions over bars, which
is a different quantity from the return ratio measured here, and it came out
Gaussian. Both can be true. What this says is that **`bars_to_reach` and
`probability_within` are converting with a factor that is 23% low at 1m on the
non-generated book**, in the direction of understating how far price reaches -
which is the same direction as the error `timing.py` documents itself having had
before.

It does not say what the replacement is. A per-class, per-interval table of the
measured ratio exists above and could be dropped in, and it should not be, until
somebody measures whether the thresholds downstream were tuned on the wrong
constant and therefore already absorb it. That is the `giveback.md` failure in
another costume.

## Four: no Reynolds number, for three separate reasons

Run, and null, as the plan predicted. The three reasons are worth separating
because only the first is about the analogy.

### The flow term does not exist on most of the book

Before anything was predicted with it. Over the 24-hour quote window, the
coefficient of variation of the per-minute quote count:

| feed | quotes | per minute | cv of the rate | cv of the spread |
| --- | --- | --- | --- | --- |
| gold | 607,786 | 442.0 | 0.397 | 0.348 |
| gbpjpy | 470,532 | 327.0 | 0.514 | 1.911 |
| eurusd | 174,553 | 121.3 | 0.595 | 1.662 |
| hk50 | 72,831 | 52.7 | 0.992 | 0.826 |
| **range_break_100_index** | **86,400** | **60.0** | **0.023** | **0.002** |
| **jump_25_index** | 86,358 | 59.9 | **0.023** | **0.000** |
| **step_index** | 86,393 | 60.0 | **0.023** | **0.001** |

**24 of 53 feeds - every generated instrument - emit a quote a second and quote
a fixed spread.** `Re = flow / liquidity` on those is a constant divided by a
constant. On 72% of the book the proposed quantity does not vary at all, so any
pooled reading of it is 72% composed of instruments where it cannot say
anything.

### On the target the proposition names, the sample cannot answer

834 decisive touches fall inside the 24-hour quote window on feeds carrying
quotes, against the 32,362 `clustering.md` used. The power was computed before
the numbers: **167 touches a quintile, a 1.9-point standard error on a cell,
about 5.4 points the smallest peak-minus-tail difference this sample could call
real - and the incumbent's separation is 5.1.**

| quintile | `Re` | `forecast_ratio` | `intensity` | `1/spread` |
| --- | --- | --- | --- | --- |
| lowest | 95.2% | 90.4% | 95.2% | 95.8% |
| 2nd | 95.2% | 91.6% | 93.0% | 94.6% |
| middle | 91.0% | 92.8% | 93.2% | 88.6% |
| 4th | 91.6% | 96.4% | 92.9% | 92.2% |
| highest | 93.4% | 95.2% | 92.2% | 95.2% |
| peak − tail | 4.2 | 6.0 | 3.0 | 7.2 |

Every one of these is at or under the resolution floor, so none of them is a
result - including the 7.2 on `1/spread`, which is a V with no shape. And
`strata.compare` on the `Re` buckets settles it: **the pooled ordering does not
hold in 8 of 10 strata**, by interval and by class. The 4.2 points is a
composition.

(The base held rate here is 93.3% against `clustering.md`'s ~84% because this
follows the `force.py` convention - `reject`, `backcheck` and `trap` all count
as held - rather than reject-against-break. The comparison is internally
consistent; the two numbers are not comparable to each other.)

### On a target with power, `Re` is `intensity`, and loses to a field already published

71,658 feed-minutes, AUC, asking two questions of the next 30 minutes against
the last 30: does the volatility scale *change* by more than usual, and does it
*rise*. Everything is conditioned inside quintiles of `vol_bps` per feed,
because scoring a challenger conditioned against an unconditioned incumbent is
not a comparison, and because busy markets are volatile markets.

| target | `Re` | `intensity` | `1/spread` | `forecast_ratio` | `vol_bps` | `vol_stretch` | `Re` shuffled |
| --- | --- | --- | --- | --- | --- | --- | --- |
| change, pooled | 0.4840 | 0.4808 | 0.4910 | 0.4961 | 0.4950 | 0.4915 | 0.5004 |
| change, within `vol_bps` | 0.4824 | 0.4853 | 0.4900 | 0.4940 | 0.5041 | 0.5005 | 0.4999 |
| rise, pooled | 0.4932 | 0.4891 | 0.4981 | 0.4915 | 0.4727 | **0.3356** | 0.5037 |
| **rise, within `vol_bps`** | **0.5437** | **0.5384** | 0.5152 | 0.4864 | 0.4095 | **0.3831** | 0.4985 |

Read the last row. `Re` reaches 0.544 and does beat `forecast_ratio` at 0.486 -
and **0.538 of that 0.544 is `intensity` on its own.** The liquidity
denominator, which is the entire content of the Reynolds analogy, contributes
0.004 of AUC. What was built is a dimensionless ratio; what predicts is the
quote count.

And it loses to what is already on the bus. `vol_stretch` scores 0.383 inverted
on the same rows - 0.117 of separation against `Re`'s 0.044 - which is the
mean reversion of the volatility scale and is published on every call today.
`vol_bps` scores 0.410, also inverted, also free.

There is a small aside in that table worth recording: `clustering.md` measured
`vol_stretch` as predicting **nothing** about whether a level holds, and it is
the strongest thing here about whether the next half hour is livelier. Those are
different questions and there is no contradiction, but "the field with nothing in
it" is now a field with something in it, on a target nobody was asking it about.

### What test four does not say

**Not that flow over liquidity is a dead idea.** It says that *this* proxy, on
*this* data, is the quote count wearing a ratio. The spread on a retail CFD feed
is largely a posted number rather than a measurement of depth - the generated
feeds quote it to three decimal places and never move it - so the denominator
was never going to carry information here. `sweeps` depth would be the honest
denominator and it is not in the research store.

**Not that the level-holding comparison was made.** It was attempted and the
sample refused it. A real test needs quotes stored for weeks rather than a day,
which is a collector change and not an analysis.

## What all four share, and what limits them

**60 days, one store, bars and quotes only.** No touches were replayed; tests
one to three read stored bars and nothing else. The README's standing caveat
applies - production drives touches from quotes too, and that difference has
twice overturned a bars-only result.

**The controls were written into the harness before the numbers were seen**, and
in two of the four they are the finding. Test two exists only because the
shuffle arm scored 0.096 where zero was expected; test four's headline is the
quote-rate table, which was printed before any prediction was made. On this
project that is the minimum and not a virtue - `generated.md` says the same
thing about the same discipline.

**The split-sample survived in three of four.** One: sign agrees in both halves
on 14 of 14 pairs. Two: sign agrees on 47 of 53 feeds. Three: the ratio moves by
0.009 to 0.056 between halves against a 0.29 effect. Four: the split is half a
day against half a day and is confounded with the session, which is stated rather
than solved - the synthetics, which have no session, are the part of the book
where the confound is absent, and they are also the part where `Re` is a
constant.

**`strata.compare` was run on all four and fired once**, on test four, at 8 of 10
strata. That is the fifth time on this project a pooled figure has been a
composition, and it was caught before it was written up rather than after.

## What any of it would change

**One.** A coarse-scale volatility reading is a leading feature for every finer
series, `Book` already holds one per (feed, interval), and the wiring is
cheap. The measured size - five to fifteen percent of a small correlation, and
near zero on 72% of the book - says build it for the real instruments or not at
all, and says the honest prior is that it arrives at the model and buys nothing,
which is what happened to the last three features of this size.

**Two.** Nothing yet, except a correction to how the measurement must be made.
The narrow finding - 12 Volatility indices and Step are exactly Brownian - is
worth carrying next to `learned.py`'s pooling argument as a known limit rather
than as a refutation.

**Three.** This is the one with a concrete consequence. `MAD_TO_SIGMA` is 27%
low at 1m and 23% at 5m on FX, and low at every interval up to 1d, in the
direction of understating reach, and the error is systematic rather than noisy.
Fixing it means measuring what downstream was tuned against it first.

**Four.** Nothing. The analogy was constructed rather than borrowed and it did
not survive, which is what the document that proposed it predicted in writing.
