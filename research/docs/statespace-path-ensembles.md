# The walk wins the forecast distribution, and the open problem is the tail shape

Asked whether the members can **simulate** what comes next well enough to be
useful - draw an ensemble of continuations, see which one the market took,
recalibrate on the answer.

The harness is `research/ideas/path_ensembles.py`. Three things had to be
settled before any of it was measurable, and the first turned out to be the
most interesting.

## There is no bug in `paths.simulate`, and that is the finding

The standing note called `simulate`'s increments broken: lag-1 autocorrelation
of **+0.999** where every real series reads 0.00. They are not broken.
`simulate` draws from a **triple integrator driven by white jerk**, which is
`linear.Gaussian`'s own model, and the increments of a thrice-integrated
process *must* be nearly perfectly autocorrelated - a step is dominated by
`rate * dt`, and the rate barely moves between steps. `paths.py`'s docstring
already says it is "not a market simulator".

Measured, it is sharper than that:

| jerk | measurement noise | lag-1 of increments |
| ---: | ---: | ---: |
| 1e-2 | 1e-4 | **0.9994** |
| 1e-4 | 1e-4 | 0.9994 |
| 1e-6 | 1e-4 | 0.9994 |
| 1e-8 | 1e-4 | 0.9994 |
| 1e-10 | 1e-4 | 0.9987 |
| **exactly 0** | 1e-4 | **-0.4879** |
| | **real series** | **-0.014 to +0.004** |

**There is no jerk at which this looks like a market.** It reads `+0.999` for
every positive jerk down to `1e-10`, and `-0.488` at exactly zero - the latter
being differenced white noise, whose lag-1 is `-0.5` by construction. Real
series sit at `0.00`, **between the two and reachable by neither.**

The reason is the `t^5`: a triple integrator's value variance grows as
`jerk * t^5 / 20`, so over a long series the smooth latent motion dominates
the measurement noise *however small the jerk is made*. **A random walk is not
in `linear.Gaussian`'s family at any parameter setting.**

That is a stronger statement than the fitted jerk landing on its grid floor,
which this desk has observed many times without a mechanism. The floor is the
fit reaching toward the `-0.5` corner, which is still wrong - only less wrong
than `+1`.

## "Which path did it take" is the wrong question

The maximum over `N` draws grows without limit in `N`, so "the highest path"
is a statement about the sample size. And the realised path is one draw from a
distribution, so asking which ensemble member it matched scores the ensemble
on a coin flip.

The answerable question is whether the forecast **distribution** is
calibrated: does the realised value land uniformly across the predicted
quantiles? That is the probability integral transform, and it is what decides
whether a band can be trusted for a stop.

Every member here carries a **Gaussian** predictive marginal, so the quantiles
and the continuous ranked probability score are read in closed form -
`CRPS(N(mu, sigma), y) = sigma [ z(2 Phi(z) - 1) + 2 phi(z) - 1/sqrt(pi) ]` -
and the whole comparison is exact with no Monte Carlo error. Sampling paths
would have added estimation noise for nothing.

## The answer

PIT flatness is a chi-square per degree of freedom against uniform, so **1.0
is calibrated**. Coverage should read 0.500 and 0.900. CRPS below 1.0 beats
the walk.

| arm | horizon | PIT flat | cover 50 | cover 90 | CRPS vs walk |
| --- | ---: | ---: | ---: | ---: | ---: |
| **walk**, generated | 1 | **1.4** | **0.500** | **0.897** | 1.000 |
| **walk**, generated | 5 | **1.9** | 0.491 | 0.895 | 1.000 |
| **walk**, generated | 20 | 4.5 | 0.478 | 0.892 | 1.000 |
| **walk**, generated | 60 | 13.0 | 0.499 | 0.898 | 1.000 |
| `reverting`, generated | 5 | 300.7 | 0.730 | 0.994 | **1.154** |
| `reverting`, generated | 60 | 672.4 | 0.856 | 1.000 | **1.217** |
| walk, traded | 1 | 91.3 | 0.626 | 0.915 | 1.000 |
| walk, traded | 60 | **18.1** | 0.528 | 0.887 | 1.000 |
| `reverting`, traded | 1 | 134.7 | 0.517 | 0.819 | **1.055** |
| `reverting`, traded | 60 | 144.3 | 0.510 | 0.826 | **1.031** |
| `kalman`, traded | 1 | 461.1 | **0.325** | 0.638 | **2.638** |
| `kalman`, traded | 60 | 315.0 | 0.715 | 0.955 | **58.196** |

**The generated rows validate the method.** On feeds whose generator *is* a
walk, the walk arm reads a PIT flatness of **1.4** and coverage of
**0.500 / 0.897** against a nominal 0.500 / 0.900 - essentially exactly
calibrated - while `reverting` reads 300 to 672 and loses 15% to 22% of CRPS
on the same data. A member that cannot match a walk where a walk is the truth
was never going to beat it elsewhere.

**Nothing beats the walk at any horizon, on either group.** The closest
anything gets is `reverting` at 1.031, which is 3% worse.

**`kalman` is catastrophic, and in the way arm 1 predicts.** Its band is far
too **narrow** at one bar - coverage 0.325 against a nominal 0.500 - and far
too **wide** at sixty - 0.715 - so it is wrong in both directions depending on
the horizon, which is exactly the `t^5` variance growth. CRPS runs 2.6 times
the walk at one bar and **58 times** at sixty.

## The open problem is the shape, not the drift

**No Gaussian forecast is calibrated on real data at all.** PIT flatness runs
18 to 461 on traded feeds against the 1.0 that calibration means - and that
includes the walk, whose best reading is 18.1. The walk is not calibrated
there, it is merely *least* miscalibrated.

The two failure modes differ, which is the useful detail:

* the **walk** is too wide in the middle and right in the tails - coverage
  0.626 at the 50% level against 0.915 at the 90%;
* **`reverting`** is right in the middle and too narrow in the tails - 0.517
  against 0.819.

So neither has the right *shape*, and they are wrong in opposite ways. That is
the third route to a conclusion this desk has reached twice before by other
means: conditioning on volatility makes the 3-sigma band worse, the members'
2-sigma bands under-cover after conditioning, and no rescaling repairs
`Paired`'s false-alarm rate. **It is the conditional shape, not the scale.**

## What this says to do

**Use the walk's band for a stop**, which this desk already concluded and now
has a forecast-scoring argument for rather than a coverage count.

**The ensemble idea is answered and is not the next piece of work.** Drawing
paths adds nothing a closed-form Gaussian marginal does not already give, and
the thing that would improve the forecast is not more draws or a better drift
- it is a **non-Gaussian predictive distribution**. `robust.py` is the member
in this package that addresses exactly that, and scoring it on CRPS and PIT
against the walk is the measurement this result nominates.

What is *not* worth building is the continuous recalibration loop the question
started from. The filter already recalibrates - its innovation is an error
signal and its gain is a derived learning rate - and
`statespace-online-learning.md` measures what adding a parameter loop on top
is worth. The gap is the tail, and no amount of recalibrating a Gaussian makes
it fat-tailed.
