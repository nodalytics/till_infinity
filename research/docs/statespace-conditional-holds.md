# A level's own record says nothing about its next interaction

`statespace-ranging.md` tested seventeen ways of **nominating** a price that
should act as support and found every one inside the noise. That refuted level
**constructions**, which have no history, and left the conditional question
open: *has **this** level, from **this** side, turned price before, and does
that predict the next time?*

`levels.SideStats` has been accumulating the answer in production since
`engine.py:2759`, as `sym_hold_rate`, and nothing has ever read it. The
instruction on 2026-10-14 was to test it without deferring to the 0.5 floor in
its own docstring.

**It is sampling noise.** Two arms say so independently, and the second says it
in a way that cannot be explained by a bad estimator.

## Arm 1: levels do not differ

If every level's true hold rate is the same number, a level's record is noise
and no estimator can predict from it. That is a dispersion question, and
production already owns the tool: `shrinkage.tau_squared`, DerSimonian and
Laird's method of moments, which **subtracts each level's own binomial noise**
from the observed spread - the step its docstring calls the whole point,
because it separates "levels differ" from "levels were counted few times".

| | pooled hold | `tau` | levels |
| --- | ---: | ---: | ---: |
| traded, real levels | 0.493 | **0.0109** | 279 |
| traded, placebo prices | 0.489 | **0.0000** | 279 |
| generated, real levels | 0.492 | 0.0227 | 94 |
| generated, **placebo prices** | 0.490 | **0.0408** | 94 |

`tau` is the between-level standard deviation of the **true** rates. On traded
instruments it is **0.0109** - about one percentage point of spread on a rate of
0.493 - which is as close to "every level is the same" as a finite sample can
report.

**And the generated row is the one that settles it.** There, a placebo price
shows **more** dispersion than a real level - 0.0408 against 0.0227. On feeds
whose generator has no levels at all, the method still finds a spread, and finds
a larger one at random prices than at rolling extremes. That is the measurement
telling you what its own noise floor looks like.

## Arm 2: every estimator loses to the base rate

At each touch past the fifth, each arm predicts from that level's **prior**
touches only.

| arm | Brier | vs base rate | AUC | placebo Brier |
| --- | ---: | ---: | ---: | ---: |
| base rate | **0.25000** | - | - | 0.25000 |
| raw ratio, as `levels.py` computes it | 0.25868 | **-0.00868** | 0.5058 | 0.25921 |
| Beta posterior, prior 1 | 0.25667 | -0.00667 | 0.5058 | 0.25710 |
| Beta posterior, prior 2 | 0.25546 | -0.00546 | 0.5058 | 0.25583 |
| Beta posterior, prior 5 | 0.25358 | **-0.00358** | 0.5056 | 0.25385 |
| shrunk toward the base rate | 0.25546 | -0.00546 | 0.5058 | 0.25583 |

19,346 scored interactions. **Every arm is worse than predicting the pooled base
rate for every level**, and the ordering is the tell: the *more* an estimator
shrinks, the *less* it loses. Prior 5 loses 0.0036 where the raw ratio loses
0.0087. An estimator that improves monotonically as it ignores more of its input
is an estimator whose input is noise.

AUC sits at **0.5056 to 0.5058** - no ordering power - and the placebo Briers
match the real ones to within 0.0005 in every row.

**So the posterior version is not the fix.** `interacting.Rate` was built to say
that three holds of four and three hundred of four hundred are not the same
evidence, and it does - but when the underlying rates are identical, knowing
your uncertainty better only tells you more precisely that you know nothing.
Shrinking harder is the right response and the limit of it is the base rate.

## What this closes, and what it does not

**`sym_hold_rate` should not be wired to anything.** It has been faithfully
accumulating a quantity with no between-level variance, and a consumer reading
it would be reading its own sampling noise. That is worth knowing about a field
that looked like the most promising unused number in `levels.py`.

**It does not refute the level machinery's other outputs.** The sweep-depth
distribution, the push distribution and the trap rate are different quantities
measuring different things, and only the hold rate was tested here. In
particular a **depth** is continuous, where a hold rate is one bit per
interaction - and one bit per touch, over a median of a few dozen touches, may
simply be too little information for any method, which is a statement about the
measurement rather than about levels.

That distinction is the honest limit of this study: it shows the hold rate
carries nothing, and it does not show that nothing about a level carries
anything.

**And "the hold rate" here is one event, not the only one.** `strength.md`
reports a level's same-side record at AUC 0.648 against a *different* outcome -
whether price gets through the level at all, with a trap counted as getting
through, at a base rate near 81% on the production book - where the race settled
above is symmetric by construction at a base rate near 0.49. The two do not
contradict each other. [`record-auc.md`](record-auc.md) separates them and shows
that the three mechanisms which could have reconciled the gap arithmetically -
tie handling, pooling across feeds, and overlapping races - are each worth under
0.005 on this event, so the difference is the event itself.

The two continuous quantities this study named as untested, the sweep-depth and
push distributions, were measured afterwards in
[`level-shrinkage.md`](level-shrinkage.md) and are null in the same way, with
the test resolving a 5% between-level spread. The trap rate is still untested.

## A defect in the table above

`auc` ranks by sorted position and **does not handle ties**, so the constant
base-rate arm - where every pair ties, and whose AUC is 0.5 by definition -
reads **1.0000**, because a stable sort puts every positive last. It is printed
as a dash instead. The other arms' predictions vary, so their figures stand, and
the implementation is left rather than fixed because nothing else here needs a
mid-rank AUC - but an unflagged 1.0 in a results table is exactly the kind of
number that gets quoted.
