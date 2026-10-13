# Pooling members is worth 5.6x on CRPS, and quadratic voting is not why

`family.py` frames the thesis as a measurement between two imports - "which
filter does this state need" is asked per state. It never asked the next
question: nothing in the package **combined** members, so every comparison had
one winner and the losers were discarded.

`research/ideas/pooling_exponent.py` asks it, with a specific mechanism on
trial. *Radical Markets* describes **quadratic voting**, where influence is the
**square root** of the credits spent, so a strong preference costs
disproportionately more and one loud voice cannot carry the room. As a pooling
rule that is `w = precision ** 0.5` rather than `w = precision`, and this desk
has a measured defect it appeared to fit: `probability_up` reaches AUC 0.6365
while being about **twice as confident as it should be**, patched with a fitted
shrink of 0.47.

Standard inverse-variance pooling weights a member by its precision, which
rewards exactly the member that has understated its own uncertainty. So the
exponent was swept rather than assumed.

## Pooling is a large win, and it is not close

Six traded instruments at 1h, scored on the held-out half.

| arm | loglike/bar | PIT | **CRPS** |
| --- | ---: | ---: | ---: |
| `kalman` alone | 4.9207 | 168.34 | 0.009039 |
| `robust` alone | 4.9225 | 168.14 | 0.009007 |
| `reverting` alone | 2.9734 | 2591.38 | 0.005432 |
| **pool, shrinking, alpha 1.0** | **5.0862** | **56.18** | **0.001601** |
| pool, shrinking, alpha 1.5 | 5.0847 | 56.01 | 0.001598 |

**CRPS improves 5.6-fold** over the best single member, and PIT flatness
improves threefold. Nothing in the package did this before, and the finding is
that the discarded losers were carrying information.

## But the exponent the data wants is 1, not 0.5

| alpha | CRPS, shrinking | PIT |
| ---: | ---: | ---: |
| 0.00 | 0.002082 | 77.98 |
| 0.25 | 0.001806 | 64.60 |
| **0.50** | **0.001661** | **58.70** |
| 0.75 | 0.001610 | 56.99 |
| **1.00** | **0.001601** | **56.18** |
| 1.50 | 0.001598 | 56.01 |

CRPS falls monotonically in `alpha` and `0.5` is beaten by `1.0` on both
metrics. **Quadratic voting is refuted as a weighting rule here**, and the
reason it was attractive turns out to be the wrong diagnosis: the
over-confidence this desk measured is not caused by the weights.

### It was the spread rule, and the conservative choice is the worse one

| alpha | CRPS shrinking | CRPS mixture |
| ---: | ---: | ---: |
| 0.50 | **0.001661** | 0.004798 |
| 1.00 | **0.001601** | 0.002389 |
| 1.50 | **0.001598** | 0.001800 |

`shrinking` is `1 / sum(precision)`, which sits **below every member's own
spread** and is correct only if the members are independent. `mixture` is the
law of total variance, `sum(w (sigma^2 + (mu - mubar)^2))`, which cannot fall
below the members' own disagreement.

The conservative rule loses everywhere, by up to threefold on CRPS, and that is
informative rather than merely negative: **the members disagree far more than
their individual uncertainties justify.** The between-member term is therefore a
liability and not a safeguard - it is carrying a disagreement that the data
says is mostly one member being wrong rather than genuine uncertainty. Raising
`alpha` improves `mixture` dramatically, from 1928 to 180 on PIT, because
concentrating weight on the precise member is how that term gets suppressed.

## The control inverts every conclusion, which is how the gain is identified

Two generated feeds, whose processes are specified:

| arm | PIT | CRPS |
| --- | ---: | ---: |
| `kalman` alone | **50.74** | **0.003551** |
| pool, shrinking, alpha 0 | 157.64 | 0.003311 |
| pool, shrinking, alpha 1.5 | 221.04 | 0.003702 |

**On a specified process, pooling loses and a higher `alpha` makes it worse** -
the exact reverse of the traded table on both counts. A single correctly
specified model has nothing to gain from company, and a weighting rule that
helps on real markets hurts here.

So the 5.6x is **model uncertainty**, not noise averaging. Real markets do not
have a correct member in the pool and generated ones do, which is also why the
best traded single member is three times worse calibrated than the best
generated one.

## Winner takes all is within 5% of the best blend, and switching is the point

*A Thousand Brains* argues the cortex's columns vote and **one interpretation
wins at a time** - the evidence it cites is the illusions, a vase or a face and
never a blend. As a rule here that is `alpha` at infinity: all the weight on
whichever member currently has the most precision, carrying **its own** spread
rather than the pool's.

Two nulls are built in from the start, because a blend comparison on this desk
has been read wrong once already - the rotation null scored +104.4 against the
real +35.6. `random` picks a member uniformly at random **each step**, and
`sticky` picks one at random for the **whole run**, which separates picking the
right member from picking a member at all.

| arm | loglike/bar | PIT | **CRPS** |
| --- | ---: | ---: | ---: |
| blend, shrinking, alpha 1.0 | 5.0862 | 56.18 | **0.001601** |
| **argmax**, winner takes all | 4.9450 | 169.00 | **0.001688** |
| `random`, a member per step | 4.2773 | 561.15 | 0.007854 |
| `sticky`, one member throughout | 4.9225 | 168.14 | 0.009007 |

Three things, and the third is the interesting one.

**Winner-take-all is genuinely selecting.** It beats a member chosen at random
each step by **4.7-fold** on CRPS. That null exists because an `argmax` arm
that could not beat it would not be selecting anything, it would merely be
being one member at a time.

**Blending wins, but only by 5%** - 0.001601 against 0.001688. So the
architecture that book describes is a **near-optimal approximation** here, at
much lower cost: no weights to compute, no spread rule to choose, and one
member's own posterior carried forward. For a 5% CRPS difference that is a
reasonable thing to prefer.

**And the value is in switching, not in model choice.** `sticky` holds one good
member and never changes its mind; `argmax` holds the same members and switches
between them. The gap is **5.3-fold on CRPS** - larger than the gap between
`argmax` and the best blend. Whatever the pool is worth, it is worth it for
changing its mind rather than for averaging.

### The control says exactly what it should

On the generated feeds, `argmax` reads `3.9100 / 50.74 / 0.003551` - **the same
three figures as `kalman` alone, exactly**. On a specified process there *is* a
correct member, winner-take-all finds it and never leaves it, and the selection
collapses to that member. That is the behaviour the rule should have and it is
not something the harness was arranged to produce.

`random` on the same feeds is worse at 0.004270, so even there the selection is
doing something. And the best generated arm overall is `mixture` at `alpha 1.0`
with a PIT of **25.52** - the only cell in the whole study to come within
twenty-five of calibrated, on the only processes whose shape is known.

## What this does not fix

**Nothing here is calibrated.** The best PIT flatness in the study is 56
against the 1.0 of a calibrated band, and
`statespace-conformal-band.md` reaches **1.5** at one bar with a shape-free
empirical predictive. Pooling is a **sharpness** win and not a calibration fix,
and the conformal band remains the only calibrated forecast this desk has.

The two are not in competition - a pooled point forecast with a conformal band
around it uses each for what it measurably does - and that is the arm this
leaves open.

## A harness defect the control arm caught

The first version pooled four members and reported `landau` scoring
`2.9734 / 2591.38 / 0.005432`, **identical to `reverting` in all three figures
to four decimal places**. That is not a coincidence and not a bug in either
member: `Landau` at its default `kappa = 0` *is* `Reverting` - the same state,
the same covariance, the same likelihood - which its own docstring states as
the thing that makes it a nested one-parameter test.

So the four-member pool was putting **twice the weight on reverting behaviour**
and calling it four members. It was found only because the single-member arm
was added, which was itself added because a table of pooled PIT values in the
tens and hundreds cannot be read without knowing whether a single member does
better.

`robust` is kept despite scoring within 0.002 of `kalman`: it subclasses
`Gaussian` and departs from it only when an innovation is large enough to
trigger the redescending weight, so a near-identical median is expected and the
member differs where a pooled band is actually for - the tails.
