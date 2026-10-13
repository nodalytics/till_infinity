# One shift is wrong for a one-sided feed, and the formulas are not

[`bounding.py`](../../till_infinity/structures/statespace/bounding.py) derives
the win probability and the expected duration of a two-barrier trade from a
symmetric driftless walk, with the Broadie-Glasserman-Kou constant `B = 0.5826`
added to each wall. The `Volatility_*` family is exactly that process -
[verified to spec](statespace-venue-spec.md) - but Boom, Crash and DEX are not:
[11 of 11 skew the advertised way](statespace-synthetic-exploits.md), with
`|skew|` from 0.28 to 1.16.

The obvious conclusion is that `P` is therefore wrong. **That conclusion is
itself wrong**, and getting it the right way round is what made the fix small.

The harness is `research/ideas/barrier_overshoot.py`.

## `P` and `T` survive the skew; the overshoot does not

`P = d/(u+d)` is **optional stopping** on a mean-zero martingale: at the
stopping time `E[X] = 0`, so `P*u - (1-P)*d = 0`. `T = u*d` is **Wald's second
identity**: `E[tau]*sigma^2 = E[X^2] = P*u^2 + (1-P)*d^2 = u*d`.

Neither derivation mentions symmetry, Gaussianity or any higher moment. They
need a martingale and a finite variance, and the drift measurements support the
premise - 0 of 11 spiking instruments carry a drift past `|t| = 2`.

What skew breaks is the **overshoot**. `B` exists because a barrier watched once
a bar can be crossed and recrossed inside the bar, so the effective barrier sits
further out than the stated one. A Boom index reaches its **upper** barrier in a
spike and overshoots it badly; it reaches its **lower** barrier in small
drifting steps and barely overshoots at all.

Optional stopping then still applies - to the stopped value *including* its
overshoot - so the same law holds with a different wall per side:

```
P = (down + B_down) / ((up + B_up) + (down + B_down))
```

### Which is checkable, and checks out to three decimals

A planted skewed martingale - rare large up-jumps paid for by a constant down
drift, so the mean is exactly zero - gives `B_up` near 2.9 and `B_down` near
0.33, and the formula predicts the measured crossing share:

| reach | predicted `P` | measured |
| ---: | ---: | ---: |
| 2 | 0.3224 | 0.3137 |
| 4 | 0.3715 | 0.3792 |
| 8 | **0.4538** | **0.4534** |
| 16 | **0.4718** | **0.4715** |

So the algebra in the module was never the problem. **The single defect was that
`SHIFT` was one number where it needs two.**

## The measured walls

Mean excess beyond the barrier at first crossing, in units of one bar's standard
deviation, on **non-overlapping** windows at reaches of 2, 4 and 8 sigma:

| family | B up | B down | ratio |
| --- | ---: | ---: | ---: |
| **Volatility** *(control)* | 0.5745-0.6002 | 0.5773-0.6058 | **0.948-1.024** |
| Boom | 0.631-0.673 | 0.489-0.533 | **1.226-1.319** |
| Crash | 0.462-0.527 | 0.598-0.676 | **0.767-0.849** |
| DEX_UP | 0.718-0.766 | 0.402-0.466 | **1.536-1.904** |
| DEX_DOWN | 0.427-0.481 | 0.700-0.741 | **0.610-0.653** |
| Step / Multi_Step / Skew_Step | 0.46-0.67 | 0.49-0.68 | **0.881-1.047** |

Three things make this believable rather than merely measured:

* **the control recovers the constant it replaces.** A Gaussian walk reads
  `0.5815` up and `0.5757` down at reach 2, and the `Volatility_*` family reads
  a ratio of 0.948 to 1.024. An estimator that could not reproduce `0.5826` has
  no business producing the rest;
* **the mirror families mirror.** Boom reads `0.65 / 0.51` where Crash reads
  `0.51 / 0.60`; `DEX_UP` reads `0.72 / 0.45` where `DEX_DOWN` reads
  `0.47 / 0.72`. Four independent measurements, nothing forcing them to agree;
* **the signs follow the published spec** rather than being fitted to it.

The practical size: a Boom index on a symmetric `+/-2` sigma geometry wins
**0.4861** of the time, not half.

## Two of my own errors the controls caught

**The windows overlapped.** The first version stepped entries every 24 bars
against windows of `4*reach^2`, so at reach 16 consecutive samples overlapped by
98% while the standard error assumed independence. It read a share-up of
**0.4816 at an apparent `z` of -3.2 on a driftless Gaussian walk**, and the
`Volatility_*` control drifted to `z = -6.83`, which I briefly read as an Ito
drift term. Non-overlapping windows return the control to `+0.05, -0.96, -1.06`.
**The entire effect was the overlap.** Reach 16 is also dropped: it needs 1,024
bar windows, which leaves 19 independent samples in 20,000 bars.

**DEX_UP and DEX_DOWN were pooled.** They are mirror constructions, so averaging
them averages opposite asymmetries and reports a symmetric process - the pooled
"DEX" read a ratio of 0.719 where the two halves read 1.904 and 0.648.

## The step indices are a lattice, and it does not help

`Step_Index` is advertised as a fixed-size step with 50/50 direction, which is a
**lattice** rather than a diffusion - and on a lattice a barrier placed at an
exact multiple of the step is *landed on* rather than crossed, so the correction
should vanish entirely.

The lattice is real. In **price** - not log, where the first attempt looked and
found nothing, because the logarithm of a price grid is not a grid -
`Step_Index` takes **149 distinct bar-return magnitudes** against 7,000 to
14,000 for the diffusion families, on a grid of exactly `0.1`:

| instrument | grid `h` | bar sd | `h`/sd | distinct |
| --- | ---: | ---: | ---: | ---: |
| Step_Index | 0.1000 | 6.025 | **0.0166** | 149 |
| Step_Index_200 | 0.2000 | 12.080 | **0.0166** | 150 |
| Multi_Step_2_Index | 0.0200 | 8.898 | 0.0022 | 201 |
| Skew_Step_Index_5_Up | 0.1000 | 20.231 | 0.0049 | 615 |

**And it buys nothing, for a reason that is a number:** the grid spacing is
`0.0166` of one bar's standard deviation, so alignment can remove at most 2.8%
of a `0.5826` shift. The monitoring correction comes from within-bar path
behaviour, not from grid granularity, and at bar resolution the grid is far too
fine to touch it. Their measured overshoot is symmetric at 0.46-0.68 - the
standard constant - and `Skew_Step` is symmetric too, despite the name.

Recorded in `SHIFTS` as symmetric *because measured*, so it is not re-derived.

## What to use

* **`bounding.shifts_for(feed)`** returns the pair, and falls back to
  `(SHIFT, SHIFT)` for anything unmeasured - a guess would be worse than the
  constant it replaces.
* **`solve`, `slack`, `binding`, `feasible` and `least_horizon`** all take
  `shift_up` and `shift_down`; `shift` remains the symmetric shorthand and the
  symmetric answers are unchanged.
* **Each wall now carries its own feasibility bound.** `least_horizon` is
  `max(B_up^2 * P/(1-P), B_down^2 * (1-P)/P)`, which collapses to the old form
  when the walls are equal.
* **Do not reach for a skew term in `P` or `T`.** They are martingale identities
  and the asymmetry belongs entirely in the wall.

## Related

* [I7 in `bounding.py`](../../till_infinity/structures/statespace/bounding.py) -
  the surface this corrects
* [What is left to exploit in the synthetics](statespace-synthetic-exploits.md) -
  where the skew was found and flagged
* [The venue spec check](statespace-venue-spec.md) - why the `Volatility_*`
  family is a valid control for this
