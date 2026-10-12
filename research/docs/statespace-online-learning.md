# Online learning and error feedback: the clock and the loop compose

**A Kalman filter already is online learning with error feedback.** The
innovation `z - C x` is an error signal, the gain `K = P C' (C P C' + R)^-1` is
a learning rate, and that rate is *optimal by construction* - derived from the
uncertainty rather than tuned. So asking to "add online learning" to a member
in this package is mostly a category error, and the useful question is the
sharper one: **what is the filter not learning?**

Its own parameters. The gain is optimal *given* `(Q, R)`, and `Q` is set by
hand or gridded offline over a whole series. `statespace/adapting.py` closes
the cheap part of that for the scalar process-noise lever; the harness is
`research/ideas/online_learning.py`.

## The control answer and the machine-learning answer are the same answer

Two schemes were built expecting them to be rivals, and they are not.

**Covariance matching** is the control-theory rule: track an exponentially
weighted mean of the squared standardised innovation `z^2 = i^2/s`, note that
an honest filter has `E[z^2] = 1`, and inflate `Q` when it runs above one.

**Stochastic gradient ascent on `log Q`** is the machine-learning rule:

```
d/d(log Q) [-0.5 (log s + i^2/s)]  =  0.5 (z^2 - 1) * (dQ s) / s
```

which is positive exactly when `z^2 > 1`. **So covariance matching *is*
gradient ascent on the likelihood with respect to `log Q`, up to the step
size.** The only real difference is that the gradient's step shrinks as the
predictive spread `s` grows, and matching's does not. That is a real
difference and it is measurable, but it is a difference of step size rather
than of idea - which is worth knowing before anyone builds an optimiser to
"learn" what a covariance-matching loop already does.

## The step size has a stability bound, and it is derivable

The loop is **negative feedback through a lagged estimate**: inflating `Q`
inflates `s`, which lowers `z^2`, which deflates `Q` again - and the lag is
the exponentially weighted mean's `memory`. A delayed negative feedback
oscillates and then diverges once the loop gain exceeds the delay, roughly

```
step * memory > 1    =>    at memory 64, step must stay below about 0.016
```

Measured, that bound is real. On the planted series `step = 0.08` moved the
lever over **18,000x** and `0.02` moved it 695x; both are above the bound.

**And it is too generous for real innovations.** At `step = 0.015` - inside
the Gaussian bound - the lever ran to its clamp on XAUUSD and XAGUSD, `moved`
of 1e6. Fat tails make the squared-innovation mean far noisier than
`sqrt(2/memory)` predicts, so the usable step is well below the derived bound
and the grid has to reach down to where the lever stays interior.

## The planted arm: the loop tracks a real change

A level whose process noise **steps up 25x** halfway through. The null is `Q`
gridded on the first (quiet) half, so it is wrong by construction on the
second - `z^2` of **6.48**, wildly over-confident:

| arm | step | held out | vs fitted | `z^2` | lever moved |
| --- | ---: | ---: | ---: | ---: | ---: |
| fitted (null) | - | 382.9 | +0.0 | **6.48** | 1.0 |
| matching | 0.015 | 6790.6 | **+6407.7** | 1.19 | 1072x |
| gradient | 0.015 | 6810.1 | **+6427.2** | 1.13 | 1140x |
| **forgetting** | - | 432.1 | **+49.1** | **6.45** | 1.0 |

Six thousand four hundred nats, and `matching` and `gradient` land in the same
place as the algebra says they must.

**Exponential forgetting does almost nothing**, and the reason is worth
keeping. It is the recursive-least-squares answer: inflate `P` by `1/lambda`
each step so the filter cannot become over-confident. But `P` returns to its
`Q`-determined steady state within a few steps, so inflating it buys a
transient and not a correction. `z^2` goes 6.48 to 6.45. **Bounding
confidence is not a substitute for getting `Q` right.**

## Real markets: the loop wins, and costs where there is nothing to track

Eight traded instruments at 1h and three Deriv indices whose `Q` is **constant
by construction**. Every arm starts from the same offline-fitted `Q` - what
the desk does now - and is only allowed to move it.

| | cells | matching | gradient | forgetting | clock | **clock + loop** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **traded** | 8 | **+848** | +659 | +13 | **+518** | **+1567** |
| **constant `Q`** | 3 | **-933** | -1045 | +11 | **-2** | -935 |

Three readings, in order of how much they change what the desk should do.

**1. They compose, and more than additively.** `848 + 518 = 1366` against an
actual **+1567**, and the super-additivity is consistent per cell: EURUSD
873 against 1238, GBPUSD 1686 against 1897, USDCAD 2531 against 2764, XAGUSD
5100 against 5172. One lever is a **time-of-day pattern** and the other is a
**reaction to what just happened**, and they do not overlap - the clock cannot
see a shock and the loop cannot anticipate an hour.

**2. Composing rescues the cells where the loop alone fails.** The loop loses
on two of eight traded instruments - USDJPY **-955**, USDCHF **-1147** - and
with the clock underneath them those become **-1** and **-80**. The clock
supplies most of the needed variation deterministically, leaving the loop less
to chase.

**3. The clock is the safer lever on its own.** +518 against the loop's +848
on traded, but **-2 against -933** on the controls. The loop is actively
harmful when there is nothing to track; the clock is free. On a desk that
cannot know in advance which regime it is in, that asymmetry matters more than
the 330-nat difference in the win.

### Why the loop loses where it loses

Both losing cells have the **worst-calibrated fixed `Q`** - `z^2` of 1.96 and
1.73 - and the loop improves their calibration (1.96 to 1.48) while losing
likelihood. That looks contradictory and is not.

**Covariance matching targets the *mean* of `z^2`, and the likelihood is
optimised closer to its typical value.** With fat-tailed innovations the mean
sits far above the median, so matching to the mean over-inflates `Q` relative
to what most observations want, and the `log s` penalty on every quiet
observation outweighs the gain on the rare large one. The clock does not have
this failure mode because it models a deterministic pattern rather than
reacting to realised squares.

That also explains why **`matching` beats `gradient` on real data** (+848
against +659) while tying on the planted series. The gradient's step scales as
`1/(1 + s)`, which damps adaptation exactly when the predictive spread has
grown - and the spread grew *because* volatility rose, which is when
adaptation is most needed.

## What it does reliably, everywhere

Calibration. `z^2` on the held-out half, fixed `Q` against the loop:

| | fixed `Q` | with the loop |
| --- | ---: | ---: |
| traded, range | 0.72 to 1.96 | **0.97 to 1.48** |
| constant `Q`, range | 1.32 to 1.44 | **1.01 to 1.18** |

It drives the filter's own confidence toward honest on every cell including
the controls, and that is the one thing it does without exception. Note the
fixed arm is *under*-confident on three traded cells (0.72, 0.78, 0.81) and
over-confident on the rest - so a single hand-set `Q` is not merely
imprecise, it is wrong in both directions depending on the instrument.

## Three bugs, and one of them is the kind this package exists to catch

**The selection leaked.** `fit` maximised the value `run` returned, and that
value was the **held-out** half - so the null chose its parameter by looking
at the data it would be judged on. On the planted arm this made the null
already correct for the regime it was supposed to be wrong about, and the loop
appeared to *lose* 195 nats while fixing the calibration. Selection now reads
the training half and only the report reads the held-out one. The planted
result went from **-195 to +6408**.

**The compose arm set the lever after `predict`.** The jerk is read by
`predict` when it builds `Q(dt)`, and `update` writes it again at the end of
every step, so a value set between the two is never used and is then
overwritten. The arm returned numbers **identical to `matching` on all eleven
cells** - and identical columns are a bug, not a finding that two levers
agree.

**The step size was called `rate`.** `family.Filter` requires `rate`, and
there it means **the state's drift**. A wrapper using that name for a learning
rate hands every consumer a step size where it expected a velocity, and both
are floats, so nothing complains. The protocol test caught it; nothing else
would have. It also turned up a missing `existence` and a `seen` that counted
wrapper steps rather than the member's readings.

A fourth, smaller: the error signal was only tracked in the adapting modes, so
the null arm always reported a perfect `E[z^2] = 1.0` and the comparison it
existed to provide was unavailable. It is tracked in every mode now, including
`none` - it is a diagnostic, and only the *lever* is mode-dependent.

## What this is, and what is still missing

**Covariance matching on `Q` from an exponentially weighted mean of squared
innovations is a volatility model.** Not a disguised one - that is what it is.
This desk already knows volatility clustering is real and large, so the +848
is expected rather than novel; the novel parts are the composition with the
clock and the asymmetric cost on the controls.

`family.MISSING["sequential parameter learning"]` is updated rather than
closed. What is built is a **point estimate** of one scalar. What is missing is
the **posterior** - IBIS or SMC^2, a distribution over parameters updated as
measurements arrive - and the -933 on the constant-`Q` controls is the
argument for it: a posterior would widen rather than wander when there is
nothing to learn, and so would not pay for adaptation it does not need.

That still needs a particle filter, which is still unbuilt.
