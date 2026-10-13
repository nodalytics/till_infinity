# A band with no assumed shape, and a correction to how the old one was scored

`statespace-tail-shape.md` left the forecast-distribution question in a precise
state: **no Gaussian band is calibrated on real data**, with PIT flatness
running 18 to 461 against the 1.0 that calibration means, and a Student-t with
the mean and variance held fixed - so it can only reshape - **over-corrects**.
Two parametric shapes, two failures in opposite directions.

The remaining move is to stop assuming a shape: let the predictive CDF be the
empirical distribution of the residuals seen before `t`, which is conformal
prediction, and read the band off its quantiles.

The harness is `research/ideas/conformal_band.py`.

## The trap, stated before the measurement rather than after

**A conformal PIT is uniform almost by construction.** If the predictive CDF is
the empirical CDF of past residuals then the PIT of a new residual is its
**rank** among the old ones, and a rank among exchangeable draws is uniform by
definition. A flatness near 1.0 is therefore close to tautological and is **not**
evidence of a better forecast.

So the PIT is a *check* and **CRPS is the evidence**: a band can be perfectly
calibrated and useless by being wide. The question is whether a shape-free band
is calibrated *and no wider*.

## The planted arms, which bracket the answer

| planted | arm | flat | CRPS vs Gaussian |
| --- | --- | ---: | ---: |
| standard normal | conformal | 0.9 | **1.000** |
| standard normal | adaptive | 12.0 | 1.006 |
| Student-t, nu=3 | gaussian | 43.0 | 1.000 |
| Student-t, nu=3 | student | 6.8 | 0.980 |
| Student-t, nu=3 | **conformal** | **1.0** | **0.978** |

On normal draws the Gaussian is correct **by construction**, and conformal
matches it exactly - it costs nothing where the assumed shape is right. On `t`
draws it recovers the calibration the Gaussian cannot and improves CRPS
slightly. That is the behaviour wanted, and the pair is what makes the real rows
readable.

The adaptive arm is worse than plain conformal on both, which is theory rather
than a defect: adaptive conformal exists for **distribution shift**, and
planted i.i.d. draws have none, so the corrector only adds noise.

## The result at h=1, where there is no overlap to confound it

| | arm | flat | CRPS vs Gaussian |
| --- | --- | ---: | ---: |
| traded | gaussian | **73.3** | 1.000 |
| traded | student | 7.8 | 0.991 |
| traded | **conformal** | **1.5** | **0.991** |
| traded | rolling | 0.5 | 0.992 |
| generated | gaussian | 40.6 | 1.000 |
| generated | **student** | **108.8** | **1.009** |
| generated | **conformal** | **1.1** | 0.997 |

**A shape-free band closes the calibration gap at no width cost**: flatness 73.3
to 1.5 on traded and 40.6 to 1.1 on generated, with CRPS at 0.991 and 0.997.
That is what the open question asked for - reshaping without widening.

**And it settles the Student-t.** On the generated instruments, which are
verified constant-volatility GBM, the `t` reads flatness **108.8** against the
Gaussian's 40.6 and CRPS **1.009**: forcing a fat-tailed shape onto a Gaussian
process makes it worse on both axes. Conformal, assuming nothing, reads 1.1
there. A parametric reshape has to be right about the shape; a shape-free one
does not.

## The correction: the long-horizon flatness was mostly overlap

An adaptive arm read a CRPS of **0.815** at h=60 - an 18.5% improvement, which
would have been the largest result in this line of work. It was an artefact, and
the artefact is in how every arm here *and in `tail_shape.py`* was sampled.

`standardised` stepped the forward window **one bar at a time** while looking
`horizon` bars ahead, so at h=20 consecutive residuals share 19 of their 20
bars. An adaptive band chasing recent misses then looks excellent because the
next miss is nearly the same observation, while a real forecaster at that
horizon makes one forecast per 20 bars.

Stepped by the horizon instead:

| h=20 | flat, overlapping | **flat, non-overlapping** | CRPS, overlapping | **CRPS, non-overlapping** |
| --- | ---: | ---: | ---: | ---: |
| gaussian | 16.0 | **1.6** | 1.000 | 1.000 |
| conformal | 3.5 | 0.9 | 1.000 | 1.001 |
| **adaptive** | 40.9 | 1.8 | **0.944** | **1.007** |

The adaptive gain is gone, and so is most of the miscalibration: **the Gaussian
is already calibrated at h=20 once the windows do not overlap**, at a flatness
of 1.6 rather than 16.0.

**That is a correction to `statespace-tail-shape.md`.** It reports flatness
"running 18 to 461" as evidence that no Gaussian forecast is calibrated, and
`tail_shape.py` steps by one bar at every horizon. The h=1 figure stands - there
is no overlap to remove at a one-bar horizon, and it reads 73.3 here - but the
long-horizon end of that range is substantially the sampling and not the band.

h=60 cannot be measured this way at all: 20,000 bars give 333 non-overlapping
samples against the 370 the scorer needs, so the row is empty rather than
estimated.

## What to use

* **A shape-free band at h=1**, which is calibrated and no wider than the
  Gaussian. There is nothing to gain at h=20, because the Gaussian is already
  calibrated there once it is scored honestly.
* **Never sample a forward window by one bar at a horizon above one.** It
  inflates any arm that can exploit the autocorrelation overlap creates, and it
  inflated a published flatness.
* **Do not quote a Student-t on a process that might be Gaussian.** It costs
  CRPS and calibration on the generated instruments, where the Gaussian is
  right.
* **Read CRPS, not flatness, when comparing a shape-free band**; its flatness is
  a rank and is uniform by construction.

## Related

* [The tail shape](statespace-tail-shape.md) - the question this answers and
  the long-horizon flatness this corrects
* [Path ensembles](statespace-path-ensembles.md) - where "nothing beats the
  walk on CRPS" was established
