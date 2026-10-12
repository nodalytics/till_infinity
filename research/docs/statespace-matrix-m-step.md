# The matrix M-step: measured not to be worth writing

`family.MISSING["em"]` listed it as the half of EM still missing. `fit_em`
fits a **scalar** multiplier on `Q(dt) = jerk * G(dt)` by Frobenius
projection, plus `R`; a full M-step would fit the covariance's **entries**.

It is not worth writing, and the reason is worth more than the implementation
would have been.

## It would be simpler, not harder

The textbook M-step for a linear-Gaussian state space is

    Q = (1/T) sum M(t),    M = S11 - S10 F' - F S10' + F S00 F'

and `M` is exactly what `diagnostics._bracket` already returns and what the
scalar step projects. **No inverse, no conditioning problem** - simpler than
what is written. The `tr(G^-1 M)` disaster recorded in `fit_em`'s docstring,
which drove the jerk to 1e-12 and the likelihood to -2.5e9, came from
projecting onto the one-parameter family, not from the matrix step.

So the question is not whether it can be done. It is what it would buy.

## What it would buy, measured

`diagnostics.shape_cost` fits `M ~ c G(dt)` per step and reports the relative
residual `||M - cG||_F / ||M||_F` - what the one-parameter family cannot
represent, and therefore exactly what a free `Q` would add. Six seeds each,
900 points, over five data-generating processes:

| the data | residual | cosine | scalar spread |
| --- | --- | --- | --- |
| an integrated-jerk path, **matched** | 0.0095 | 0.99995 | 0.190 |
| a random walk | 0.0145 | 0.99990 | 0.490 |
| a mean-reverting OU | 0.0148 | 0.99989 | 0.484 |
| a jump process | 0.0110 | 0.99994 | **1.304** |
| pure noise, no state at all | 0.0095 | 0.99995 | 0.121 |

**The residual is one to one and a half percent and the cosine is above
0.9999 on every one of them.** A free matrix `Q` would recover approximately
`c G(dt)` from data as different as a matched path, a random walk, an OU, a
jump process and white noise.

## Why, and this is the part that generalises

Not because the shape is right. **`M` is built from the E-step**, and a
smoother cannot attribute process noise outside the geometry of the model it
is smoothing with. Hand the smoother an integrated-jerk model and the process
noise it infers is an integrated-jerk-shaped quantity, because that is the
only shape its state space has. So the residual is near zero **by
construction** and carries no information about whether the shape fits the
data.

That is a general caution about EM diagnostics: a statistic computed from the
E-step's output cannot test the model that produced it. The honest test of a
shape is held-out likelihood against a different shape, which is what every
member comparison in this package already is.

### And a free `Q` is only well posed on a regular grid

A second reason, independent of the first. `Q` here is a function of `dt`: a
continuous-time model sampled at irregular times has a different `Q` at every
step, and `Q(dt) = jerk * G(dt)` is what ties them together with one
parameter. A free matrix `Q` asserts that every step is the same length,
which is the per-bar assumption `I6` exists to reject - and averaging `M(t)`
across steps of different `dt` estimates nothing in particular.

So on this package's own terms the scalar is not a compromise. It is the
correct consequence of the model being continuous-time.

## The one column that does carry something

The **step-to-step spread of the fitted scalar**. A shape that is right gives
one best-fit multiple; a shape that is wrong gives a different one at every
step. It ranks the mismatches: 0.19 matched, 0.48 to 0.49 on a walk or an OU,
**1.30 under jumps** - which is what a jump should do, demanding an enormous
`Q` at one step and a tiny one at the next.

**It is not monotone in correctness** and that limit is in the test rather
than only in prose: pure noise with no state at all gives the *lowest* spread
of any arm, 0.12, because there is nothing to attribute. So it detects
**heteroscedastic** mismatch specifically, not wrongness, and it should be
read as "this model's process noise does not want to be one number" rather
than as a goodness-of-fit statistic.

## What this changes

* **The registry entry is corrected.** `MISSING["em"]` no longer says the
  matrix M-step is the half missing; it says what was measured and why the
  item is closed.
* **`shape_cost` stays**, for its third column. A scalar spread above about
  one is a member whose process noise is being asked to cover jumps, which is
  a reason to reach for `robust` or `driven` rather than to re-fit.
* **The thing EM still lacks** is not an M-step. It is a reason to prefer it:
  `fit_em`'s own docstring measures it as twelve times slower than coordinate
  ascent for the same likelihood, buying a closer parameter and nothing else.

The measurement is `diagnostics.shape_cost`.
