# The one unmeasured constant, measured: neither derivation was right, and the gap is Q

**2026-10-18. [`research/ideas/dispersion_noise.py`](../ideas/dispersion_noise.py),
`statespace/config.py`, `facade.Desk.read`.**

`statespace/config.py` has said since it was written that `noise` is the one
unmeasured constant in the service. Every member takes a measurement
*variance*; the service's observation is `log(garman_klass(o, h, l, c))`; and
the two standard derivations of that quantity's sampling variance disagree by
4.6x:

* a close-to-close square is one chi-square degree of freedom, so
  `Var(log r^2) = pi^2 / 2 = 4.9348`, divided by Garman-Klass's efficiency of
  about 7.4 gives **0.6669** - the value shipped;
* the estimator itself is chi-square with `2e = 14.8` degrees of freedom, so
  `Var(log GK) = trigamma(7.4)` gives **0.1447**.

Both are delta-method arguments about a quantity nobody had sampled.

## Part A: the constant, where the truth is known

A driftless Gaussian walk at fixed sigma has a constant latent log variance, so
every wobble in `log GK` is measurement error, and `log(GK / sigma^2)` does not
depend on sigma - one simulation answers it for every instrument. The only
thing it depends on is how many ticks the bar was built from, which is a
property of the feed rather than a nuisance.

40,000 bars per row. `bias` is `E[log(estimate / truth)]` and `var` is the `R`
being looked for:

| ticks/bar | GK bias | **GK var** | Parkinson bias | Parkinson var | RS bias | RS var | RS zeros |
|---|---:|---:|---:|---:|---:|---:|---:|
| 12 | -0.7917 | 0.5002 | -0.6413 | 0.5551 | -0.8397 | 0.9052 | 8.2% |
| 30 | -0.5350 | 0.3885 | -0.4657 | 0.4502 | -0.5986 | 0.6985 | 3.3% |
| 60 | -0.4075 | 0.3479 | -0.3731 | 0.4103 | -0.4744 | 0.6219 | 1.7% |
| 240 | -0.2651 | 0.2946 | -0.2733 | 0.3605 | -0.3217 | 0.4953 | 0.5% |
| 1,440 | -0.1823 | 0.2702 | -0.2134 | 0.3443 | -0.2294 | 0.4194 | 0.1% |
| 5,760 | -0.1528 | **0.2651** | -0.1902 | 0.3364 | -0.1960 | 0.3919 | 0.0% |

**The harness proves itself first.** A close-to-close square has a closed form
with no tick dependence at all - `Var = pi^2 / 2 = 4.9348` and
`bias = digamma(0.5) + log 2 = -1.2704` - and the control column returns
-1.264 to -1.281 and 4.86 to 4.99, flat across every row. Without that column
none of the rest would be worth reading.

**Neither derivation is right.** The continuous limit is **0.265**: 2.5x below
the shipped 0.67 and 1.8x above the alternative's 0.145. Inverting it,
`trigamma(nu/2) = 0.265` gives about 8.5 degrees of freedom where the second
derivation assumed 14.8 - Garman-Klass's efficiency *in log space* is near 4,
not 7.4, which is why dividing `pi^2/2` by 7.4 was never going to land.

**And the bias is large.** `log GK` under-states log variance by 0.15 at a
dense bar and 0.79 at a twelve-tick bar. That lands as a constant offset on
every published `log_variance`, so a consumer turning it into a per-bar sigma
with `exp(log_variance / 2)` is reading a number 7% to 33% low. Rogers-Satchell
additionally returns exactly zero on 8.2% of thin bars, where the estimator is
unusable rather than noisy.

## Part B: which R the published band actually wants

On real bars the latent log variance moves, so the operational question is not
the estimator's sampling variance but which `R` makes the service's own output
honest. Each candidate is scored one step ahead against the **next** bar's
observation, through `Desk.read` and `Readout.covering` - the same path the
service publishes from. `var z` is the variance of the standardised innovation,
which is 1 exactly when the predictive spread is the right scale.

**15m, median across four instruments per class:**

| R | fx_cross var z | fx_major var z | metal var z | volatility var z *(sigma fixed by its generator)* |
|---|---:|---:|---:|---:|
| 0.145 | 6.33 | 6.00 | 5.51 | 2.15 |
| 0.250 | 3.70 | 3.50 | 3.23 | **1.22** |
| 0.400 | 2.33 | 2.20 | 2.04 | 0.70 |
| 0.670 *(shipped)* | 1.41 | 1.34 | 1.25 | 0.42 |
| 1.000 | **1.07** | **1.03** | **1.01** | 0.28 |

**1h, median across four instruments per class:**

| R | fx_cross var z | fx_major var z | metal var z | volatility var z *(sigma fixed)* |
|---|---:|---:|---:|---:|
| 0.145 | 6.36 | 5.50 | 5.80 | 2.39 |
| 0.250 | 3.76 | 3.25 | 3.44 | **1.13** |
| 0.400 | 2.38 | 2.06 | 2.18 | 0.67 |
| 0.670 *(shipped)* | 1.41 | 1.22 | 1.26 | 0.40 |
| 1.000 | **1.08** | **1.00** | **0.97** | 0.27 |

**The control lands on Part A, and that is the cross-check this harness was
built for.** The Deriv volatility family is a control here **for one named
property and nothing else**: its generator holds sigma fixed, so there is no
latent movement for `Q` to absorb and the innovation test should return the
measurement noise alone. It is a real market, tradeable and spread-bearing -
what makes it usable here is that its generator is *published*, not that it is
synthetic, and it is a poor control for anything tail-shaped (kurtosis 3.19
against 20.07 traded). It crosses one at **R near 0.30**, against
0.265 simulated and 0.295 at a 240-tick bar. Two independent measurements, one
synthetic and one on real quoted bars, agree.

It reads 0.30 at 15m and **0.28 at 1h** - two timeframes, one answer, and the
answer is the simulated constant.

**On traded classes it crosses at 1.0, on all three of them, at both
timeframes.** The extra is not
measurement noise - Part A measured that, twice - it is latent movement the
filter's `Q` is not modelling: about **0.73 of the 1.0**, so roughly three
quarters of what a one-step forecast of this quantity has to be uncertain about
on a real market is regime movement rather than estimator error. On a generator
with no regime movement the same filter is correctly specified. That is
[`how-markets-differ-from-every-simple-process`](how-markets-differ-from-every-simple-process.md)
restated in the filter's own currency, and it is a **`Q` finding, not an `R`
one**.

## What this changes, and what it does not

**The band is insensitive to all of it, which is why nothing looked wrong.**
Realised breach at the 0.90 ask sits at 0.093 to 0.104 at *every* candidate `R`
from 0.02 to 2.5, because `Readout.covering` serves the body from the measured
quantiles of past surprises - and those surprises are standardised by the same
spread that `R` inflates. The band self-normalises against a wrong `R`. So
`covering` was safe to ship on a guessed constant, and the two outputs that
were not safe are the ones a consumer reads directly: `spread` and `surprise`.

**At 0.95 and 0.99 the band is too wide, not too narrow.** Breach runs 0.033
to 0.041 against the 0.05 asked and 0.0014 to 0.006 against 0.01 - a ratio of
0.65 to 0.82 at 0.95. The anchored tail over-covers, which is the safe
direction for a stop and the wrong direction for a trade gate that is waiting
for a quiet market.

**CRPS and `var z` disagree at 15m and agree at 1h, which is the frame that
matters.** At 15m CRPS prefers the smallest `R` on traded classes, because it
is dominated by how well the *level* is tracked and a small `R` follows the
level faster. At 1h it picks **0.67 on fx_major and 1.0 on metal** - the same
region `var z` points at. So on the frame this desk forecasts dispersion on,
the proper score and the innovation test agree, and they agree on a value near
the one already shipped.

**`DEFAULT_NOISE` stays at 0.67, and it is now vindicated rather than
tolerated.** It is *not* the estimator's sampling variance - that is 0.265 -
but at 1h it is the lowest-CRPS value on fx_major and within one grid step of
it on metal, and it gives `var z` of 1.22 to 1.41 where 0.265 would give 3.2 to
3.8. Shipping the physically correct constant without touching `Q` would make
the one field a consumer reads *worse* calibrated by a factor of three. The
constant was chosen as the conservative end of two wrong derivations and landed
within a grid step of the operational optimum, which is luck worth recording as
luck.

The honest change is not to `R` at all: pin it at the measured 0.265 and raise
`Q` until `var z` reaches one. That is a sweep with a target rather than a
guess.

## The named next run

Sweep `Q` with `R` pinned at the measured 0.265, scored on the same three
columns, and check two things: that `var z` reaches one on traded classes
without the control's going below one, and that CRPS does not get worse while
it happens. If both hold, `DEFAULT_NOISE` becomes 0.265, the `Q` lever moves,
and the published `spread` means what it says for the first time. If the
control breaks, the movement being absorbed is not regime movement and the
0.73 belongs somewhere else.
