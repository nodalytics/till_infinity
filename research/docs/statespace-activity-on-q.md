# Activity on `Q` is worth three times the clock, and makes it redundant

`seasonal.Profile` drives the process noise from the **clock** and is the
strongest single lever this desk has measured on a state-space member.
`statespace-volume-clock.md` then showed the clock is mostly a proxy for
something else: resampling into **volume time** absorbs about three-quarters of
the time-of-day profile, which is the subordination result of Clark 1973 and
Ane-Geman 2000. 14:00 UTC is not special, it is busy.

That study could not turn the observation into a gain, because resampling
changes the observation set and a density over volume bars cannot be subtracted
from one over calendar bars. `statespace.pacing` closes that gap: it turns each
bar's own tick volume into a variance multiplier on the **same calendar bars**,
so every arm is a density over identical observations and the likelihoods
subtract.

The harness is `research/ideas/activity_clock.py`, on the `level_wander` lever
at 1h, base process noise refitted on the undriven arm, scored on the held-out
second half.

## The answer

| arm | traded median | generated median |
| --- | ---: | ---: |
| clock, `Profile.factor` | +675 | -2.5 |
| clock, level subsidy removed | +553 | -3.4 |
| activity, exponent 0.5 | +977 | 0.0 |
| activity, exponent 1 | +1630 | +0.1 |
| **activity, exponent 2** | **+2197** | **+0.1** |
| activity, exponent 3 | +2009 | +0.1 |
| activity, exponent 4 | +639 | 0.0 |
| clock x activity, best | +1547 | -4.4 |

Three things, in order of how much they change what the library should do.

**Activity beats the clock by better than three to one, on 8 of 8 traded
instruments.** Nothing marginal: EURUSD +2661 against +785, USDJPY +2815
against +628, gold +2234 against +681.

**The clock is redundant once activity is in.** The best composed arm beats the
better of the two alone on **0 of 8** cells. Activity does not absorb
three-quarters of the clock, as volume-time resampling suggested - on this
measurement it absorbs all of it and the clock then subtracts, because a
time-of-day profile raises `Q` at 14:00 on a holiday and activity does not.

**The exponent is 2, not 1, and the sweep has a turn in it.** 0.5 to 1 to 2
rises, 3 and 4 fall, on every traded instrument. That matters because an
exponent that improved monotonically would mean the statistic was being carried
by its largest few bars and the clamp that bounds them, rather than by a shape.

### Why 2 is interesting rather than just a number

Subordination predicts **1**: a bar is the sum of its price changes, so its
variance should scale with how many there are. Exponent 2 says the *standard
deviation* scales with the count - the bar's move grows **linearly** in the
number of ticks, not as its square root.

Linear growth is what a **trending** sequence of increments gives; the square
root is what independent ones give. So the measured exponent says the price
changes inside a busy bar are not independent draws but a directional run,
which is a claim about microstructure rather than about this filter. It is
offered as the reading that fits, not as something this study established.

## Three normalisation defects, found one after another

A multiplier on `Q` whose average is not one hands the member more process
noise **as well as** varying it. Sweeping the base noise on the undriven arm -
the standard guard here, and the one that caught a `+1192` that became a `-24`
once the base was refitted - cannot remove it, because the sweep refits the arm
that is *not* being driven. Three instances turned up in this one study:

| multiplier | mean factor, uncorrected | why |
| --- | ---: | --- |
| `share ** 2` | **2.23** | `E[x^2] > E[x]^2` for any spread |
| clock x activity | **1.36** | `E[XY] = E[X]E[Y] + Cov(X, Y)`, and the two are correlated by construction |
| `Profile.factor` itself | **1.21** | `Profile.at` normalises on the **log** scale, so its *geometric* mean is one, and `factor` squares it |

The first made the squared arm beat the linear one by +2365 to +1734 before it
was corrected, which is the result above with its cause removed and nothing
else changed. `Pace.factor` and `Both.factor` now divide by an exponential mean
of the quantity they return, and the harness **prints every arm's realised
mean factor** rather than trusting that to have worked - all the activity arms
land between 0.95 and 1.00.

### The third one is about an existing result, and it survives

`seasonal.Profile.factor` has been running at a mean of 1.21, worst 1.58, which
means the documented clock gain has carried a level subsidy the base refit
never removed. Scored with that subsidy stripped by a wrapper, the clock earns
**+553 against +675** - so roughly a fifth of it was level and four fifths were
shape. **The clock's measured gain stands**, and `Profile` has not been changed:
the wrapper exists so the question could be asked without altering a member
that is in production.

## The controls, and a correction to what was claimed about them

`statespace-volume-clock.md` says the generated feeds post **exactly constant**
tick volume. That was measured at 3m and does not survive the move to 1h: a
survey of all **553** cached feeds at 1h found **none** with an activity extent
of exactly 1.000. The synthetics come in at 1.001 to 1.016 against 2.7 to 9.4
for traded instruments.

So the control is a **bound rather than an identity**, and the first version of
this harness was wrong to assert exact inertness - it failed on a feed that was
behaving correctly. Stated as a bound, the controls are decisive:

| feed | activity extent | largest activity arm |
| --- | ---: | ---: |
| `Step_Index_200` | 1.0006 | +0.1 |
| `Boom_500_Index` | 1.0076 | +2.1 |
| `Crash_500_Index` | 1.0084 | +2.7 |
| `DEX_900_UP_Index` | 1.0089 | +1.3 |
| `Drift_Switch_Index_10` | 1.0155 | **-8.2** |

Two nats against two thousand. And `Drift_Switch_Index_10` is the useful one:
it has the most varying activity of the controls and that variation is noise,
so driving `Q` with it **loses** likelihood, and loses more as the exponent
rises. The mechanism is not a free parameter that can only help.

## A peer's activity is real information, and redundant

The obvious extension crosses this desk's two largest measured effects:
cross-instrument volatility correlation runs at a median **+0.5170** and is
contemporaneous, and activity drives variance at **+2197**. So a *peer's*
activity should carry information about this instrument's variance.

It does, and it is worth nothing. `research/ideas/peer_activity.py`, on seven
named pairs chosen for relationships this desk has already measured:

| arm | median nats |
| --- | ---: |
| the instrument's own activity | **+1666** |
| a peer's activity instead | +1343 |
| the same peer, **rotated in time** | **-917** |
| both, as a normalised product | +539 |

**The peer arm beats its rotation on 7 of 7**, so peer activity genuinely
predicts this instrument's variance - a third independent confirmation that
relationships here are contemporaneous and live in variance, this time through
activity rather than realised volatility.

**And `both` beats `own` alone on 0 of 7.** The peer is a noisy copy of the
instrument's own activity, so the product over-drives and loses a thousand
nats. A member should **not** reach outside its own feed for this, which is a
cheap negative to have: the cross-feed plumbing was the expensive part.

The rotated arm is the useful detail. It is not near zero, it is **-917** -
driving `Q` with real activity that is misaligned in time is substantially
worse than not driving it at all. The mechanism is not a free parameter that
can only help.

The controls are exact. A **generated peer** - `Boom_500_Index`,
`Step_Index_200` - contributes `-0.0` and `0.0`, as a fixed tick count
requires. And a **generated target** cannot be helped by anything: its own
activity earns 0, and a real instrument's activity driving it scores **-2333**.

## What is wired, and what is not

`statespace.pacing` is self-contained: `Pace` for the multiplier, `Both` for the
composition, `Levelled` to renormalise any factor, and `shares`, `factors` and
`extent` for harnesses. It imports nothing outside the package, and it is not
`Restorable` - see `CODEC_UNPERSISTED`.

It is **not** wired into any production member. The measurement says it should
displace the clock rather than join it, which is a larger change than this
study is licensed to make: it would mean a live member's process noise starts
depending on a volume field, and `context.activity` already clamps that field
because venues reset counters. The next step is a shadow arm, not a swap.
