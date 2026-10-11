# Simulated forward, not one member looks like a market

Two measurements, both from ideas taken out of papers this week, both run on
2026-10-11. Harness: `research/ideas/rollouts_and_yielding.py`.

## 1. The stylized facts of each member's own rollout

TradeFM judges a generative model on whether its **rollouts reproduce stylized
facts**. This package had scored every member on held-out likelihood and never
on whether simulating it forward produces something market-shaped, which is a
different question: a member can be the best one-step density in the family and
still be a false description of the series.

`statespace/facts.py` rolls any member out through the `Filter` protocol - ask
for its predictive distribution at the next time, draw from it, feed the draw
back - after warming it on the first half of the real series.

eurusd 15m, 8,000 bars. `drift` is the lag-1 autocorrelation of increments,
`clustering` the summed autocorrelation of their absolute values, `kurtosis` at
aggregations of 1, 5 and 20:

| | drift | clustering | kurtosis |
|---|---|---|---|
| **the real series** | -0.035 | **+0.877** | 35.4 / 8.8 / 6.6 |
| kalman | +0.003 | +0.016 | **880** / 170 / 37 |
| robust | +0.004 | +0.020 | **900** / 173 / 37 |
| reverting | **-0.493** | +0.262 | -0.04 / +0.21 / -0.20 |
| changepoint | **-0.495** | +0.277 | -0.02 / +0.21 / -0.06 |
| selective | **-0.407** | +0.186 | -0.02 / -0.01 / +0.22 |
| swarm | **+0.948** | +4.269 | 210 / 205 / 153 |
| walk | +0.009 | +0.073 | 0.00 / -0.21 / +0.38 |

**Not one of them reproduces the market**, and the three failure modes are
distinct enough to diagnose rather than merely report.

**`drift = -0.5` means the state is not moving at all.** That number is not
arbitrary: if a series is a constant plus independent noise, `x_t = m + e_t`,
then its increments are `e_t - e_{t-1}` and their lag-1 autocorrelation is
**exactly -0.5**. So `reverting`, `changepoint` and `selective`, rolled forward,
generate observation noise around a level that barely moves. Their process noise
is small enough relative to `R` that the simulated series is almost pure
measurement error - which is a true statement about those members at these
parameters, and the opposite of the complaint usually made about a Kalman
filter.

**`swarm` at +0.948 has the opposite problem**: its state moves so much relative
to the observation noise that the rollout is a smooth trending line. A market
with a lag-1 increment autocorrelation of +0.95 would be trivially tradeable.

**`kalman` and `robust` generate kurtosis of 880** against the real series' 35.
The integrated-jerk state random-walks the acceleration, so a long rollout
occasionally produces an excursion with no bound, and the unconditional
distribution is far fatter than anything a market does.

Only `walk` gets `drift` right, and it has no clustering by construction - which
is the null behaving as a null.

**What this does not say.** None of these members was fitted on this series for
this run; they use their defaults, and a fitted `jerk` would change the kurtosis
numbers. What it does say is that the failure is *structural* and visible
without fitting: nothing in the family generates volatility clustering except by
accident, and this desk's own measurements say volatility clustering is the one
forecastable thing here. A family whose members cannot generate the only
forecastable feature of the data is a family of local approximations.

## 2. Widening the process noise against resetting the state

Two fluid-dynamics papers independently prescribe the diffuse treatment: Fluids
11:251 gates the PDE term where the differential form is invalid, and Processes
14:3253's whole phase-field branch exists because a diffuse interface behaves
better than a sharp one. `statespace/yielding.py` applies that here - widen the
process noise in proportion to `Changepoint.changepoint`, which was computed and
consumed by nothing - and its null is two-sided: beat the member alone, **and**
beat `Paired`, which resets.

Log-likelihood on eurusd 15m, and the pattern is the same on every series:

| member | alone | **paired (reset)** | reach=1 | reach=3 | reach=10 | reach=30 |
|---|---|---|---|---|---|---|
| kalman | -541,089 | **-37,608** | -541,089 | -476,743 | -406,291 | -345,905 |
| robust | -156,183 | **-21,587** | -156,183 | -145,816 | -134,899 | -127,387 |

**Softening works, monotonically, and loses by an order of magnitude.** Every
increase in `reach` improves the likelihood - so the mechanism does what it
claims - and even at thirty times the process noise it is nowhere near the
reset. Reproduced on xauusd and gbpusd at both timeframes.

The `reach = 1` column is the control and it reproduces `alone` **exactly**,
which is what makes the rest of the row a measurement of the softening rather
than of the wrapper.

### Why the analogy failed, which is the useful part

A shock in a conservation law is a **localised** failure of an otherwise valid
model: the equation holds everywhere except on a surface, so gating it there and
keeping it elsewhere is right. The member here is not in that situation. At
-541,089 over 8,000 bars it is losing **68 nats a bar**, continuously - the
prior is not wrong at the changes, it is wrong all the time, and widening the
process noise at the moments a detector fires addresses a few percent of the
readings while leaving the rest untouched. Resetting wins because it
re-anchors the state to the current level constantly, which is a crude way of
saying the state should have been following the data much more closely from the
start.

So the transplant fails for a reason worth keeping: **the diffuse-interface
argument presupposes the model is right away from the interface.** Before
borrowing a numerical remedy for a localised failure, check that the failure is
localised - and `loglike` per reading is how you check.

`yielding.py` stays, because it is the only consumer of `Changepoint.changepoint`
and because its measured result is the finding above. It is not in `members()`
and nothing reads it.
