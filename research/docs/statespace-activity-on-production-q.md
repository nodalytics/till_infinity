# Activity helps the production filter too, at exponent 1 rather than 2

`statespace-activity-on-q.md` measured activity on `Q` at **+2197 nats** median
against the clock's +675, on 8 of 8 traded instruments, and said the next step
was a shadow arm rather than a swap. Looking for somewhere to put one turned up
two facts worth recording before any measurement.

**Nothing in production runs a `statespace` member.** The package is imported
once outside itself, by `shared/codec.py`, and only so `CODEC_UNPERSISTED` can
be discovered. There is no member in the live desk to shadow - which is by
design, since the package is deliberately standalone and deletable.

**But production has its own Kalman, and its process noise is already a
per-call argument.** `levels.Kalman.predict(when, drift_per_hour)` adds
`drift_per_hour ** 2 * elapsed` to the variance, and exactly one call site
supplies it:

    # levels.py:1244
    self.filter.predict(when, vol.price_units(self.price, DRIFT_VOL_PER_HOUR))

So the wiring is a one-line multiply at a single call site with no change to
the filter at all. **That is not a reason to do it.** The measurement that
motivates it was taken on a different object - `level_wander` on a log-price
member tracking price itself, not a filter tracking a *level* that price visits
and leaves - and three things differ enough that the result cannot be assumed
to carry: the production filter is `(price, slope)` rather than a random walk,
its observations are **touches** arriving irregularly rather than a close every
bar, and `DRIFT_VOL_PER_HOUR` is 0.02 volatility units per hour, so a
multiplier on a nearly-frozen filter is not a multiplier on a lively one.

## It does carry, and the exponent is different

`research/ideas/production_q.py`, on the production `levels.Kalman` itself.
Per observation, held-out half, drift refitted on the undriven arm.

| exponent | traded median | positive on | generated median |
| ---: | ---: | :---: | ---: |
| **1** | **+0.0513** | **7 of 8** | -0.0002 |
| 2 | -0.0880 | - | -0.0002 |
| 3 | -0.5886 | - | -0.0001 |

**Exponent 1, not 2.** The price member's sweep turned at 2 on every instrument
and this one is negative there, which is the substantive result: the two filters
want different exponents, and that is exactly why it needed measuring instead of
assuming. A level filter with a constant-velocity transition is not a price
member, and the activity multiplier that suits one over-drives the other.

`US_Oil` is the one instrument that loses at exponent 1, at `-0.1532`.

The multiplier enters as a **square root**, because `drift_per_hour` is a
spread and the activity factor is a variance ratio - the same exponent trap
`Profile.factor` documents, in the other direction.

### The controls are inert, and exactly so

The generated feeds read `-0.0002` to `+0.0014` per observation with a realised
mean factor of **1.000** at every exponent. Their tick count is fixed by their
generator, so `Pace` has nothing to work with and reports nothing - without
being told, which is the property that makes the control group free.

### One defect and one mis-set baseline, both caught before the result was read

**`levels.Kalman.update` returns the Kalman gain, not a log density.**
Accumulating what it returns and calling it a likelihood would have scored a
quantity that rises *mechanically* with the process noise - a larger variance
gives a larger gain - so the drift sweep would have chosen the top of its grid
and the activity arm would have won for the same reason. The density is formed
in the harness from the predictive state before each observation is folded in.

**And the first run pinned the drift at the top of its grid on every single
instrument.** `DRIFT_VOL_PER_HOUR` is tuned for a filter fed occasional
touches; fed a close every bar it wants orders of magnitude more process noise,
and a baseline sitting at the edge of its own grid has not been fitted. The
grid now runs to 16,384 times the constant and nothing pins.

## What this justifies, and what is deliberately not done here

The measurement justifies the one-line change at `levels.py:1244`, at
**exponent 1**:

    # what the measurement supports, not applied in this PR
    factor = pace.factor(bar_volume)          # mean one, exponent 1
    drift = vol.price_units(self.price, DRIFT_VOL_PER_HOUR) * math.sqrt(factor)
    self.filter.predict(when, drift)

**It is not applied.** Scaling a level filter's process noise widens its
posterior, which widens the zone, which moves stops and therefore changes what
the live desk trades. That is a behaviour change to a running trading system,
not a shadow, and the word "shadow" in the original note was doing real work: a
shadow computes and records without acting, and there is nothing to compute
alongside here because the production path *is* the only path.

Two things would make it a genuine shadow rather than a swap, and both are
larger than this study: journalling the factor and the width it would have
implied without using it, so the two can be compared on real touches; or
`behaving.drives_q`, which already says the mechanism is inert on a feed whose
activity does not vary, gating it per instrument.

The prerequisite is also worth stating plainly: `Pace` needs a **volume** at
that call site, and `levels.py` currently receives a price and a volatility.
