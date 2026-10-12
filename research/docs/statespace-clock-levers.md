# Which lever the clock belongs on, and a correction to the number

`statespace-seasonal.md` measured a time-of-day profile driving `level_wander`
on a level-only member at +197 nats median, and left one question open: the
other members carry different process noises, and whether the clock belongs on
those was untested.

Two answers. **The clock belongs on the level's wander and nowhere else
tested** - and **the +197 was partly a rescaling, not a clock.** With each
lever's base fitted before the clock is applied, the level gain is +81 at the
median and negative on two of seven instruments.

## The correction first, because it is a correction to merged work

The earlier harness set the level's process noise from the series' one-step
spread and left it there. That is a reasonable base but not a fitted one, and
`Profile.at` averages one over the **cycle** rather than over the sample's
actual hours - so multiplying a slightly mis-set base by a profile whose mean
over the sample is not exactly one improves the fit partly by **rescaling the
base**, which has nothing to do with the clock.

This harness sweeps each lever over fourteen decades and picks the base on the
**matched null**, `clock=None`, before applying the clock. The clock then has
to beat the member at its own best setting.

| | earlier | with the base fitted first |
| --- | --- | --- |
| level, traded median | +197 | **+81** |
| level, positive cells | 10 of 10 | **5 of 7** |
| EURUSD | +142.5 | **-39.7** |
| GBPUSD | +154.8 | **-16.7** |
| BTCUSD | +298.7 | +194.7 |
| ETHUSD | +367.6 | +243.1 |

So the effect is real but roughly half the size, and it is not universal: on
EURUSD and GBPUSD a well-set constant `Q` beats a clock-driven one. The
earlier claim that it gained on *every* FX and metal cell does not survive the
base being fitted.

**The misalignment penalty is untouched and is still enormous** - sliding the
observations half a day against the stamps costs 362 to 1,283 nats. Both
readings hold together: the profile has a genuine 2.7-to-3.7-fold amplitude,
so applying it misaligned hurts a great deal, while applying it aligned to a
member whose base is already right adds much less than applying it to one
whose base is not.

## Why the dimensions were never the question

Three levers, three units, all **variance rates**:

| member | lever | units |
| --- | --- | --- |
| `Seasonal` level-only | `level_wander` | (value)^2 / hour |
| `linear.Gaussian` | `jerk` | (value)^2 / hour^5 |
| `reverting.Reverting` | `sigma2` | (value)^2 / hour^3 |

`Profile.factor` is the profile **squared**, which is correct for a variance
whatever the integration order - the propagation from a jerk's spectral
density to the position's variance is linear in that density, so the factor
passes through unchanged. The question was never whether the units fit.

## The answer, and the column that explains it

| lever | null loglike, EURUSD | clock gain, traded median | clock broken | generated |
| --- | --- | --- | --- | --- |
| **level** | **81,226** | **+81.1** | -529.5 | -0.7 |
| jerk | 39,496 | -0.6 | +0.8 | -0.0 |
| reverting | 39,434 | -12.1 | -26.4 | -0.1 |

The `null loglike` column is the whole explanation. **A plain level walk is
about forty thousand nats better than either `kalman` or `reverting`** at
describing a log-price series, on every instrument tested. A model losing by
that much has no room for a hundred-nat refinement, and the clock's effect on
both is inside the noise.

This is the session's central finding in its most direct form. `kalman`
carries integrated jerk, and fitted to price its jerk pins at **1e-10 to 1e-6
times** the dimensionally natural value - which is to say essentially zero, so
the member is a straight line plus measurement noise. **A lever driven to zero
cannot carry a profile, because zero times any factor is still zero.** The
clock has nothing to multiply.

`reverting` is the same story with an extra wrinkle: its gain is *negative*,
-12 at the median, and more negative still when the clock is broken. A
reverting member fitted to a near-random-walk sets its reversion weak and its
noise to absorb everything, and modulating that noise by the hour makes it
slightly worse at the job it has settled into.

## What to do with it

* **Keep the clock on the level's wander**, and fit the base. On BTC and ETH
  it is worth +195 and +243 and the misalignment penalty confirms it is the
  clock; on EURUSD and GBPUSD a fitted constant is better and the clock
  should be off.
* **Do not put it on `jerk` or `sigma2`.** Not because the units are wrong,
  but because those members are the wrong model for the series in the first
  place, by forty thousand nats.
* **The general lesson, which is the reusable part**: fit a lever's base
  before testing a multiplier on it. A multiplier whose mean over the sample
  is not exactly one will otherwise be credited with the rescaling it
  performs, and the credit grows with how badly the base was set. This is the
  same shape as the unfitted-`Walk` trap in `jpy-silver-pair.md` and the
  fitted-against-unfitted comparison in `statespace-fitting.md` - three
  instances now of the same mistake, which is a strong enough pattern to
  check for by default.

The harness is `research/ideas/clock_levers.py`.
