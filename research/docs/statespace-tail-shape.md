# The shape is the problem, a Student-t is not the answer, and `nu` depends on the horizon

`statespace-path-ensembles.md` closed with a precise open question. Nothing
beats the walk's forecast distribution on CRPS at any horizon, and **no
Gaussian forecast is calibrated on real data at all** - the probability
integral transform's flatness runs 18 to 461 against the 1.0 that calibration
means, the walk included. The two failure modes are opposite, so neither has
the right *shape*.

That document nominated `robust.py` as the lever. **That was wrong and is
worth correcting plainly.** `robust` inflates the measurement variance when an
innovation is surprising, which changes the **gain** - how far one outlier
moves the state - and leaves the predictive density Gaussian. It cannot move a
PIT flatness, because the PIT is a statement about the shape of the forecast
density and `robust` does not change that shape.

What does change it is quoting the band as a Student-t. The harness is
`research/ideas/tail_shape.py`.

## The test holds the mean and the variance fixed

The predictive is written

    y ~ mu + sigma * sqrt((nu - 2)/nu) * T_nu

with `mu` and `sigma` from the walk - the best-performing arm - and only `nu`
fitted. A standard `T_nu` has variance `nu/(nu-2)`, so that scale factor leaves
the predictive variance at **exactly `sigma^2`** whatever `nu` is.

So the mean is unchanged, the variance is unchanged, and the **t arm cannot win
by widening** - only by reshaping. If it wins it is shape and nothing else.

## The quadrature is checked before anything is read off it

The Gaussian CRPS has a closed form and the Student-t's involves Beta
functions, so both are computed by quadrature on the quantile grid instead.
On twenty thousand standard normals the quadrature reads **0.563827** against
the closed form's **0.563725** - a gap of `1e-4`. A score computed two ways
that agree is a score.

## The answer

| | cells | median `nu` | flat Gaussian | **flat t** | cover 90 g | cover 90 t | CRPS t/g |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **generated**, h=1 | 3 | **200** *(edge)* | 1.5 | 1.4 | 0.896 | 0.896 | **1.000** |
| generated, h=5 | 3 | 100 | 2.1 | 2.2 | 0.896 | 0.896 | **1.000** |
| generated, h=20 | 3 | 100 | 4.9 | 5.6 | 0.890 | 0.890 | **1.000** |
| generated, h=60 | 3 | 40 | 13.0 | 13.7 | 0.897 | 0.896 | **1.000** |
| **traded, h=1** | 8 | **3.0** | **91.7** | **16.9** | 0.914 | 0.871 | 1.023 |
| traded, h=5 | 8 | 3.5 | **57.3** | **12.0** | 0.906 | 0.878 | 1.021 |
| traded, h=20 | 8 | 5.5 | 31.6 | 20.3 | 0.896 | 0.880 | 1.015 |
| **traded, h=60** | 8 | **8.0** | 18.1 | **22.5** | 0.884 | 0.878 | 1.014 |

**The generated rows are a perfect calibration check.** Their increments are
Gaussian by construction, `nu` fits at 200 - the grid's own edge, meaning
"effectively normal" - then 100, 100 and 40, and the CRPS ratio sits at
**1.000 to three decimals at every horizon.** The t buys exactly nothing where
a normal is the truth, which is what makes the traded column readable.

### Confirmed: the shape is a large part of the miscalibration

PIT flatness at one bar falls from **91.7 to 16.9**, a factor of 5.4, and at
five bars from 57.3 to 12.0. So the shape was carrying most of the
miscalibration at short horizons, and the nomination in the previous document
was right about the *diagnosis* even though it was wrong about the lever.

### But a Student-t is not the right shape either

Three reasons, and the third is the useful one.

**It is still badly miscalibrated.** 16.9 against the 1.0 calibration means is
a seventeenfold rejection of uniformity. The t is much less wrong, not right.

**It costs CRPS.** The ratio runs 1.014 to 1.023, so the t is 1.4% to 2.3%
*worse* on the proper score while being far better calibrated. That is the
same tension measured in `statespace-online-learning.md`, where covariance
matching improved `E[z^2]` and lost likelihood: **matching a moment is not
maximising a score**, and with fat tails the two pull apart.

**It over-corrects at the band a desk would actually use.** Coverage at the 90%
interval goes from the Gaussian's 0.914 to the t's **0.871** against a nominal
0.900 - so the normal is slightly too wide there and the t slightly too narrow.
A `nu` of 3 puts the extra mass far out in the extreme tail and takes it from
the 90% boundary, which is the wrong place to take it from for a stop.

### And the real finding is that `nu` depends on the horizon

`nu` rises **3.0, 3.5, 5.5, 8.0** across horizons of 1, 5, 20 and 60 bars - a
clean dose-response on eight instruments, which is far stronger evidence than
any single value. That is aggregational Gaussianity, a stylised fact of
returns, measured here as a parameter rather than asserted.

It also explains the one place the t makes things **worse**: at sixty bars
flatness goes 18.1 to 22.5, because by then `nu` is 8 and the distribution is
close enough to normal that reshaping costs more than it buys.

**Nothing in this package currently makes the band's shape depend on the
horizon**, and this says it should: a one-bar stop wants `nu` near 3 and a
sixty-bar hold wants `nu` near 8 or a plain normal.

## What to do with it

**For a stop, keep the walk's Gaussian band and shorten the horizon rather
than reshape it.** The t's gain is in calibration and its cost is in CRPS and
in the 90% coverage, which is the number a stop is set from. The honest summary
is that at one bar the Gaussian band's tails are wrong by a factor that
*matters* and a t fixes the diagnosis without fixing the band.

**What would fix it** is a shape with a horizon-dependent parameter and more
freedom than one degree: `nu` fitted per horizon is the minimum, and the
coverage column says the right family needs to add mass at two to three sigma
without taking it from one to two - which a Student-t cannot do, since its
single parameter controls both.

That is a concrete specification rather than a direction, and it is the first
time this question has had one.
