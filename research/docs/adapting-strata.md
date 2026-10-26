# The matching loop against its clamp - and why that does not describe production

**2026-10-20. [`research/ideas/adapting_strata.py`](../ideas/adapting_strata.py),
[`normalised_input.py`](../ideas/normalised_input.py),
[`student_t_target.py`](../ideas/student_t_target.py),
[`pool_calibration.py`](../ideas/pool_calibration.py).**

**Read the last section first if you only read one.** Everything here was
measured with `R` pinned at **0.265**, the estimator's physically correct
sampling variance from [`dispersion-noise.md`](dispersion-noise.md) - and that
page's own conclusion was *not* to ship that value. At the `R` the service
actually runs, 0.670, most of what follows does not happen.

## What was found at R = 0.265

[`pool-spread.md`](pool-spread.md) measured `E[z^2]` per member at 2.0 to 3.1
on traded instruments against 1.01 to 1.03 on a constant-sigma generator. The
cause turned out to be a clamp:

| class, 1h | clamp | kalman | reverting | robust | pool |
|---|---|---:|---:|---:|---:|
| fx_cross | 1e3 *(shipped)* | 2.16 | 1.08 | 2.02 | 2.99 |
| fx_cross | 1e7 | **1.05** | **1.02** | **1.05** | 2.05 |
| fx_major | 1e3 | 2.17 | 1.07 | 2.02 | 3.00 |
| fx_major | 1e7 | **1.04** | **1.02** | **1.04** | 2.04 |
| metal | 1e3 | 2.30 | 1.07 | 2.17 | 3.21 |
| metal | 1e7 | **1.03** | **1.01** | **1.03** | 2.03 |

Every member finished at `factor = 1000.000` - `adapting.MOST` exactly - with
the loop's own `excess` reading what the sample reads (2.413 against 2.227). It
knew how wrong it was and was not allowed to move. Released, the lever
converges at a factor of **1.3 to 4.2 million** and the members reach their
target; the pool then reads 2.05 under `shrinking`, which is the between-member
term that rule drops by construction.

**A loop on its clamp had no symptom.** It returns a number for every bar, so
nothing in the service logged anything unusual for the whole run. `saturated`
and the count in `Watcher.report` exist because of that, and they are the one
part of this page that is worth having whatever `R` is set to.

## Four explanations tested, three killed

**Composition - killed.** An exponentially weighted match converges on the
periods a series spends most of its time in, so the unconditional second moment
of a clustered-variance series could exceed one with every local window
matched. Four planted mechanisms say no: a constant latent level, an AR(1)
level, the same level observed through **simulated bars** so the estimator's
real error shape is present, and a **deterministic daily cycle** at 3x in
variance - the `seasonality-belongs-on-q` mechanism - all read `E[z^2]` of
**1.02 to 1.09**. The cycle arm drove the lever to 464x and 442x, so the loop
absorbs a cycle; it simply had the room to.

Part B agrees from the other side: `E[z^2]` is **flat across every decile** of
the trailing level (3.31 to 2.82) and of the previous bar's `|z|` (3.18 to
3.22). A clamp is a constant, so the error is constant in every regime - which
is what a uniform scale error looks like and composition does not.

**Lag - killed.** Memory from 16 to 1,024 observations moves the unconditional
average by 0.004 (2.994, 2.991, 2.990, 2.991). The memory governs how fast the
lever travels and it was parked at the ceiling.

**The time axis - killed.** Folding the real stamps against a uniform hourly
clock on the same bars gives 2.991 against 3.109, with gaps rare (0.9% over
2h, max 50h). Weekend inflation of `Q` is not it.

**Units - killed, and this one looked like a free fix.** Six orders of
magnitude between a price's `jerk` and a log variance's is a unit problem on
its face, so a fixed affine transform of the input - estimated on bars nobody
scores, with `R` normalised alongside it - should have removed the need for the
clamp. It moves `E[z^2]` by **at most 0.015 anywhere** and leaves the lever
wanting millions. `Adapting`'s lever is a multiple of the member's **own**
starting value, so rescaling the input rescales the state and `Q` together.

**Heavy tails - killed, and it had the best prior of the four.** For a
Student-t innovation at `nu` degrees of freedom a filter reporting its *scale*
correctly reads `E[z^2] = nu/(nu-2)`: 1.67 at `nu = 5`, which is the range
`kalman` and `robust` sat at on 15m, and
[`one-bar-band.md`](one-bar-band.md) independently measured `nu` of 3 to 5 for
the price band. Fitted by maximum likelihood here, `nu` comes back at **12 to
50** with a likelihood gap over a Gaussian of **+0.001 to +0.006 a bar**, and
the implied `nu/(nu-2) * c^2` tracks the sample to three decimals - so the fit
is recovering the sample variance rather than finding a tail. The
constant-sigma family reads `nu = 200` with a *negative* gap. These innovations
are near-Gaussian, and `tails.py`'s `nu` belongs to the price band.

## And now the part that reframes all of it

**At the shipped `R = 0.670` the clamp does not bind**, so none of the above
describes the running service:

| class, 1h, R = 0.670 | var z | CRPS | breach .90 |
|---|---:|---:|---:|
| fx_cross, clamp 1e3 *(shipped)* | 1.205 | 0.5242 | 0.1072 |
| fx_cross, clamp 1e7 | 1.200 | 0.5238 | 0.1077 |
| fx_major, clamp 1e3 | 1.204 | 0.5400 | 0.1091 |
| fx_major, clamp 1e7 | 1.197 | 0.5399 | 0.1093 |
| metal, clamp 1e3 | 1.236 | 0.5524 | 0.1080 |
| metal, clamp 1e7 | 1.227 | 0.5523 | 0.1089 |

Releasing a clamp that was pinned at 0.265 changes `var z` by **0.009** at
0.670. The reason is mechanical: at the larger `R` the measurement variance
dominates the predictive spread, so the loop never needs a million-fold `Q` and
never reaches its ceiling.

So **the published spread is not three times too small. It is 1.20 to 1.24** -
twenty per cent low in variance, ten per cent in standard deviation - and the
band breaches the 0.90 ask at 0.107 to 0.109 rather than 0.100.

That is a much smaller problem than this page spent a day diagnosing, and the
diagnosis was of a configuration the service does not run. The lesson is the
generalisable part: **pin the parameter at the value that ships, not at the
value that is correct**, or the failure being chased may not exist where it
matters. [`dispersion-noise.md`](dispersion-noise.md) had already concluded
that 0.265 should not be shipped; pinning it there anyway to isolate one effect
produced a real finding about a hypothetical desk.

## What is worth taking

* `saturated` and the report count, which make a clamped loop visible whatever
  `R` is - the condition had no symptom and now has one;
* `Pooled(most=)` and `Desk(clamp=)`, reachable without patching internals;
* the four refutations above, which close composition, lag, units and tails for
  this quantity and save the next person the runs;
* **no change to `MOST`, to the rule, or to `R`**, because at the shipped
  configuration there is a twenty per cent discrepancy and no arm in the grid
  improves it without making the band worse.
