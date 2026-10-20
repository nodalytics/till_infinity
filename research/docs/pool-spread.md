# The published spread was over-confident for two reasons, and neither was Q

**2026-10-20. [`research/ideas/pool_calibration.py`](../ideas/pool_calibration.py),
`pooling.Pooled`, `facade.Desk.read`.**

[`dispersion-noise.md`](dispersion-noise.md) measured the estimator's sampling
variance at **0.265**, found that on real bars the filter needs `R` near 1.0
for its one-step innovations to have unit variance while the constant-sigma
control needs 0.28, called the excess latent movement `Q` was not absorbing,
and named a `Q` sweep as the next run.

**That sweep would have swept a lever that already moves itself.** Every member
in `Pooled` is wrapped in `adapting.Adapting` in matching mode by default,
whose entire job is to drive the exponentially weighted square of its
standardised innovation to 1.0. So before sweeping anything, the premise had to
be measured: is each member matched, and is the pool?

## The premise, measured - and it is not what either docstring implied

`E[z^2]` per member at `R = 0.265`, median across three instruments per class:

| frame | class | kalman | reverting | robust | **pool** |
|---|---|---:|---:|---:|---:|
| 15m | fx_cross | 3.12 | 2.00 | 2.58 | **3.39** |
| 15m | fx_major | 2.96 | 1.94 | 2.50 | **3.23** |
| 15m | metal | 2.82 | 1.65 | 2.53 | **3.05** |
| 15m | **volatility** *(sigma fixed, so nothing to disagree about)* | **1.03** | **1.01** | **1.02** | **1.08** |
| 1h | fx_cross | 2.16 | 1.08 | 2.02 | **2.99** |
| 1h | fx_major | 2.17 | 1.07 | 2.02 | **3.00** |
| 1h | metal | 2.30 | 1.07 | 2.17 | **3.21** |
| 1h | **volatility** *(as above)* | **0.99** | **1.00** | **0.99** | **1.03** |

**The members are not matched on markets, and they are matched exactly on the
control, at both frames.** `Adapting` hits its target of one to within 1-3%
where the latent variance is constant by construction, and misses it by two to
three fold where it moves. `reverting` is the exception at 1h, where it reads
1.07-1.08 against `kalman`'s 2.16-2.30 - so the miss is member-specific as well
as frame-specific, and whatever is wrong is not wrong uniformly. That is the whole finding, and it rules out both of the explanations
that were on the table: it is not `Q` being too small in a way a sweep could
fix, because the lever that sets `Q` is already closing its own loop and
succeeds when the process is stationary; and it is not only the pooling rule,
because the individual members are already at 2 to 3 before anything is pooled.

The mechanism this suggests is a composition effect rather than a broken lever.
An exponentially weighted match converges on the periods it spends most of its
time in, and the unconditional second moment of a series whose conditional
variance clusters exceeds one even when every local window is matched. That is
testable and cheap, and it is the next run: **score `E[z^2]` within strata of
current volatility.** If it reads near one inside strata and three
unconditionally, the lever is locally honest and the excess is composition, and
the fix belongs in how `Adapting` weights its history rather than in its
target.

## The pooling rule carries part of it, and no rule dominates

`pooling.py` chooses `shrinking` and records the alternative being rejected:
`mixture` is the law of total variance, "cannot fall below the members' own
disagreement", and **lost by up to threefold on CRPS**. Measured here on log
variance at the shipped `R = 0.670`:

| frame | class | `shrinking` var z / CRPS / breach .90 | `mixture` | `argmax` |
|---|---|---|---|---|
| 15m | fx_cross | 1.374 / 0.5393 / 0.1003 | **1.133** / 0.5386 / 0.1050 | 1.247 / 0.5465 / 0.1024 |
| 15m | fx_major | 1.302 / 0.5286 / **0.0990** | **1.075** / 0.5282 / 0.1049 | 1.167 / 0.5319 / 0.1009 |
| 15m | metal | 1.250 / 0.5246 / 0.1012 | **1.058** / 0.5245 / 0.1058 | 1.063 / **0.5127** / 0.1064 |
| 1h | fx_cross | 1.205 / 0.5242 / **0.1072** | 0.948 / 0.5242 / 0.1165 | **1.032** / **0.5146** / 0.1099 |
| 1h | fx_major | **1.204** / **0.5400** / **0.1091** | 0.815 / 0.5402 / 0.1304 | 1.013 / 0.5418 / 0.1158 |
| 1h | metal | 1.236 / 0.5524 / **0.1080** | 0.903 / 0.5532 / 0.1308 | **1.011** / **0.5420** / 0.1163 |
| 1h | volatility *(sigma fixed)* | 0.401 / 0.2933 / 0.1014 | 0.399 / 0.2933 / 0.1016 | 0.401 / 0.2932 / 0.1012 |

**At 15m `mixture` looked like a free fix and at 1h it overshoots.** It takes
`var z` to 1.06-1.13 at 15m - an honest spread, at a CRPS a hair better - and
then to **0.815-0.948** at 1h, which is over-wide, while its band breaches the
0.90 ask at **0.117-0.131** against `shrinking`'s 0.107-0.109. One frame would
have shipped it. Two frames say the between-member term grows with the bar:
at 1h there are fewer and more informative observations, so the members diverge
more per reading and the term that fixed 15m overcorrects.

`argmax` is the most consistent arm - `var z` 1.01-1.03 at 1h and 1.06-1.25 at
15m, and the best CRPS in three of six traded cells - at a band cost of +0.001
to +0.009 over `shrinking`. It is the one worth revisiting, and it is not a
dominance.

**`shrinking` has the best band coverage in every traded cell at both frames**,
and the band is the output a consumer reads through `covering`. The
constant-sigma family cannot tell the three rules apart (0.399 to 0.401)
because there the members have nothing to disagree about - a control for that
one property, which is what makes the traded rows readable. It is not a control
for the tails, for the spread, or for anything else in this table.

## So the default does not move, and the reason is a frame nobody has measured

`facade.SPREAD_RULE` gains a name and keeps its value. Picking `mixture` on the
15m rows would have been choosing against the 1h rows; picking `argmax` would
be choosing on CRPS against band coverage.

**And the frames measured are not the frames that run.** `config.py` folds
**1m and 5m**; this harness, [`dispersion-noise.md`](dispersion-noise.md) and
[`band-coverage.md`](band-coverage.md) are all at 15m or longer, because the
lab cache holds nothing shorter - the noise run printed "5m: nothing loaded"
and moved on. So the service publishes on two intervals where the measurement
variance, the band coverage and the spread rule have **all three** been
measured somewhere else, and the two places they have been measured disagree
about the rule.

That is the blocking gap, and it has two exits. Either 5m bars go into the
cache and this sweep is re-run where it matters, or the service is pointed at
`15m` and `1h`, where everything it publishes has been measured. The second is
a one-line change to `DEFAULT_INTERVALS` and is not made here, because nothing
consumes the topic yet and the choice deserves to be made on what the first
consumer needs rather than on what is convenient to measure.

## What stays, and why `R` cannot move yet

**`DEFAULT_NOISE` stays at 0.67, now for a second reason.** With `mixture` at
the measured `R = 0.265` the pool still reads `var z` of 1.64 to 2.37 - 2.16 to
2.37 at 15m and 1.64 to 1.72 at 1h - because the members are individually
over-confident before any rule is applied. So no
configuration at the physically correct `R` is honest, and
[`dispersion-noise.md`](dispersion-noise.md)'s plan - pin `R` at 0.265 and
raise `Q` - cannot work until `Adapting` matches on a market. The `R` of 0.67
has been doing two jobs at once: absorbing the dropped between-member term, and
absorbing the members' own unmatched scale.

**`Adapting` earns its place regardless.** The un-adapted pool at the shipped
`R` reads CRPS 0.5807 / 0.6034 / 0.5538 against the adapted 0.5393 / 0.5286 /
0.5246 - **4% to 12% worse** - so the mechanism is doing real work even though
it is not reaching its stated target. That is worth saying plainly: the lever
is valuable and mis-calibrated, which are not alternatives.

**The band is nearly insensitive at 15m and not at 1h**, which is the one
place this run disagrees with [`dispersion-noise.md`](dispersion-noise.md)'s
finding that `covering` absorbs everything. Across `R` from 0.02 to 2.5 it did.
Across the spread *rule* it does at 15m - 0.0990-0.1012 to 0.1049-0.1058 - and
at 1h `mixture` pushes it to 0.1165-0.1308. `Readout.covering` serves its body
from measured surprise quantiles standardised by the same spread, so it absorbs
a constant mis-scaling and not a change in the *shape* of what it standardises
by. A rule that adds a spiky between-member term changes that shape.
