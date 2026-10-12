# How big an ordering would have to be, and what the nulls therefore mean

`paths.simulate` was used for parameter recovery and nothing else, and the
question it could answer is the one behind most of this session's results:
when a harness returns null, is that because **the market has no ordering** or
because **the method cannot find one**?

A null does not distinguish them. **Power** does: plant an ordering of known
size, run the same harness, find the smallest size it detects. The null then
stops being "nothing is there" and becomes "anything there is smaller than
this", which is a quantity.

Two things came out, and the second was not what this was set up to find.

## 1. The detection threshold, and the cost threshold beside it

An AR(1) in the returns, `r(t) = phi * r(t-1) + noise`, standardised so the
series' variance does not change with `phi`. One parameter, and the one this
desk has actually looked for: `research/harness/statespace_fx.py` reports a
Kalman AR(1) drift with `phi` of -0.02 to -0.04 on EURUSD, 13 of 96 cells past
Benjamini-Hochberg.

8,000 observations, 20 seeds per cell, detection meaning the raw lag-1 reading
beats its own rotated control by 0.05:

| planted `phi` | raw | control | detected |
| --- | --- | --- | --- |
| 0.00 | -0.001 | 0.000 | **0.00** |
| -0.01 | -0.010 | 0.001 | 0.00 |
| -0.02 | -0.020 | 0.001 | 0.00 |
| -0.04 | -0.039 | 0.001 | 0.05 |
| **-0.08** | -0.077 | 0.001 | **1.00** |
| -0.16 | -0.154 | 0.001 | 1.00 |

**The detection threshold is `|phi| = 0.08`**, and it is sharp - 0.05 of seeds
at 0.04, all of them at 0.08. The false-positive rate at `phi = 0` is zero,
so the margin is not generous.

**The claim that survived in this repository sits below that threshold.** A
`phi` of -0.02 to -0.04 is where this detector has 0 to 5% power, which is
consistent with it being 13 of 96 cells rather than a clean result.

### And the cost threshold is a `phi` too

Trading the sign of the last return earns `|phi|` of a typical move per trade,
so against a round trip of 1.5 spreads the edge pays only when
`|phi| * (move in spreads) > 1.5`. The move in spreads is measured, not
assumed - `statespace-seconds.md` has the table:

| horizon | move / spread | `phi` needed to pay | which binds |
| --- | --- | --- | --- |
| 10s | 2.87 | **0.523** | cost |
| 30s | 5.27 | **0.285** | cost |
| 1m | 8.00 | **0.188** | cost |
| 3m | 16.13 | **0.093** | cost |
| 15m | 37.92 | 0.040 | detection |

**Below about three minutes the cost threshold is the higher of the two.** So
a directional null at those horizons is neither a detection failure nor an
absence - it is the statement that whatever is there **cannot pay for the
spread**, and no better detector changes that. At 15m and above the ordering
flips and a null does mean "not findable", which leaves room for something
smaller than 0.08 to be real and unprofitable.

Those are three different sentences and the session's directional nulls have
been quoted as if they were one. The backtest's "0 of 28 cells profitable,
and the whole loss is the cost" is the first of them; it is the one that holds
below three minutes.

## 2. What `paths.simulate`'s own path looks like

This began as a second base - plant the same ordering on the triple-integrator
path the package's model assumes, and compare the power. It detected an
ordering at `phi = 0` in 90% of seeds, which killed the arm and replaced it
with something better.

The base already had an ordering:

| `jerk` | measured increments' lag-1 | spread over seeds | truth's lag-1 |
| --- | --- | --- | --- |
| 1e-9 | 0.076 | **0.412** | 0.999 |
| 1e-6 | **0.981** | 0.026 | 0.999 |
| 1e-3 | **0.999** | 0.000 | 0.999 |
| 1 | **0.999** | 0.000 | 0.999 |

**The increments of the process this package assumes have a lag-1
autocorrelation of +0.999.** Real series sit at 0.00 - the walk arm above
reads -0.001, and every instrument measured here has a level Hurst of 0.489
to 0.506.

That is the session's central finding stated from the generator's side rather
than the fit's. It is not that the members fit badly; it is that a triple
integrator driven by white jerk produces paths **nothing like the data**, and
far smoother. And it explains two separate observations that were reported
without a mechanism:

* **`statespace-clock-levers.md` found a fitted jerk landing at 1e-10 to 1e-6
  times its natural value.** The table says why: 1e-9 is the only row where
  the generator stops looking like itself. Fitting drives the jerk to the one
  place the model can imitate a random walk, which is where its own dynamics
  are switched off.
* **`statespace-backtest.md` reads `kalman`'s residual autocorrelation at
  -0.45.** A model whose increments want to be +0.999 correlated, fitted to
  data whose increments are uncorrelated, over-extrapolates - and an
  over-extrapolating filter leaves residuals that alternate.

At 1e-9 the reading is **unstable** rather than market-like: 0.076 with a
spread of 0.412 across eight seeds, because the truth is nearly frozen and
whether measurement noise or residual drift dominates varies run to run. So
there is no setting of `jerk` at which this generator is a good model of a
price series - only one at which it is a bad model of anything.

## What to do

* **Quote which threshold binds** with any directional null. Below three
  minutes it is cost, and that conclusion is robust to improving the method.
* **A better detector is worth building only above three minutes**, where
  detection is the binding constraint and the gap between 0.040 and 0.08
  leaves room for something real.
* **`paths.simulate` is the wrong generator for a market-like null**, and
  saying so is more useful than keeping it for one. For planting orderings,
  the walk base is the right one; `simulate` remains correct for what it was
  written for, which is recovering a member's own parameters from a path that
  member actually assumes.

The harness is `research/ideas/planted_ordering.py`.
