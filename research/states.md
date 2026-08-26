# Does a level's behaviour change over its life

Run: `python research/harness/states.py`

`Inference.probability_up` pools every touch a level has ever had, equally. A
support that held six times and then broke is **averaged with itself**: the
level's behaviour changed and the statistic cannot say so. The proposal was a
per-level state model - `{respected, breaking, flipped}` with transitions - so
that "it has flipped" becomes a discrete, reportable event with a probability
attached.

The sample-size objection was raised with it, and it is the right one: levels
carry a handful of touches, and a two-state transition matrix estimated from
six observations is noise fitted confidently. The honest form is hierarchical -
one transition model pooled across every level, per-level state inferred - and
that is a real modelling project.

**So the premise was measured first, because the premise is cheap and the
project is not. The premise is false.** Levels are stationary, recency predicts
*worse* than pooling, and the flip does not exist.

## 0. Levels have more history than expected

861 level-sides with at least four touches, 10,602 touches between them.

| | touches |
|---|---|
| p50 | 10 |
| p75 | 16 |
| p90 | 22 |
| p100 | 47 |

Better than the 4-20 assumed, and still thin: a two-state transition matrix
needs four counts estimated, and the median level has ten observations to
spread across them.

## 1. Behaviour is stationary

Splitting each level's touches in half by time:

| | held |
|---|---|
| first half | 73.5% of 5,102 |
| second half | 74.1% of 5,500 |
| **mean within-level change** | **-0.011** |

Eleven thousandths, on the wrong side of zero. The median *absolute* change is
0.182, which is what five touches a half produces from a fair coin - dispersion
without direction.

## 2. Recency predicts worse than pooling

The direct test of the premise. If a level had state, its recent touches would
describe it better than all of them averaged:

| predictor | n | right |
|---|---|---|
| **always "it holds"** | 7,158 | **74.4%** |
| pooled - what the code does | 7,158 | 70.1% |
| the last three | 7,158 | 67.5% |
| the last one only | 7,158 | 63.4% |

**The ordering is exactly backwards from the hypothesis.** More recency is
monotonically worse: pooled beats the last three, which beats the last one. A
level's history is best read as one long average, which is what pooling already
does.

And the trivial rule beats all of them again, by four points. That is the fifth
document in which it has done so.

## 3. Runs are longer than chance, and that is not state

| | |
|---|---|
| consecutive touches that differ | 37.5% of 9,741 |
| expected from independent coins | 39.1% |

A 1.6-point gap on 9,741 observations is about three standard errors, so the
run structure is real. **It is also not evidence for state**, and the
distinction is the whole point of this document.

The null "independent coins" uses the *pooled* hold rate of 73.4%. But levels
differ from each other: one that holds 90% of the time and one that holds 60%
will together alternate less often than a single 73.4% coin would, without
either of them ever changing. Longer runs are what a population of **stationary
levels with different rates** produces.

Heterogeneity between levels and state within a level make the same prediction
here, and §1 and §2 separate them: within-level change is -0.011 and recency
predicts worse. So it is heterogeneity.

## 4. There is no flip

The sharpest test, and the clearest answer:

| state | n | next one holds | 95% |
|---|---|---|---|
| after two holds | 5,048 | **74.9%** | 73.7% - 76.1% |
| after two failures | 561 | **74.9%** | 71.1% - 78.3% |
| pooled | 11,104 | 73.4% | |

**Identical to the decimal.** A level that has just failed twice in a row is
exactly as likely to hold on its next touch as one that has just held twice.
The intervals overlap almost completely, and both sit above the pooled rate for
the ordinary reason that a level with a run of any kind is a level with
history.

If "flipped" were a state a level enters, this is the row where it would show,
on 561 observations of levels that had every appearance of having entered it.

## What this saves

**Do not build the state model.** Not because it is hard - because there is
nothing for it to find. A hierarchical HMM would infer states over a process
that §1 says does not drift, §2 says is best described by its long-run average,
and §4 says has no absorbing failure mode. It would produce state probabilities,
they would look plausible, and they would be a re-parameterisation of the
pooled rate.

Three things worth keeping from it:

1. **The defect named at the outset is real but harmless.** Pooling *does* mix
   a level's early and late behaviour, and that is the right thing to do here,
   because the behaviour does not change. The statistic is not hiding a
   transition; there is no transition.
2. **"Runs are longer than chance" is a trap.** It is true, it is significant,
   and it is produced by stationary levels differing from one another. Any
   future state model will find it and be encouraged by it. It is not evidence.
3. **The premise test cost one replay.** The model it declined would have cost
   weeks and produced a confident answer. Measuring the premise first is the
   cheapest guard this project has.
