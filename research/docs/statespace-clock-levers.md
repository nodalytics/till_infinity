# Which lever the clock belongs on, and the convention bug that hid the answer

`statespace-seasonal.md` measured a time-of-day profile driving `level_wander`
on a level-only member and left one question open: the other members carry
different process noises, and whether the clock belongs on those was untested.

The first answer this study produced was **wrong**, and wrong because of a
defect in two members this desk had already merged. Both the defect and the
corrected answer are below, because the defect is the more useful of the two.

## The bug: two members took a standard deviation where everything else took a variance

The `Filter` contract says `update`'s `noise` argument is the measurement
**variance** `R`, and `linear`, `reverting`, `switching` and the `Walk` null
all read it that way. `seasonal` and `symmetry` **squared it**, treating it as
a standard deviation.

That is undetectable while a harness compares a member with itself, which is
how both were measured. It surfaced the first time one number was passed to
three different members: at `R = 1e-3` the squaring member was handed a
variance of `1e-6` and the others `1e-3`, so one arm was **a thousand times
more confident in every reading** than the others.

What it produced, and what was briefly believed:

| claimed from the broken run | actually |
| --- | --- |
| a level walk is ~40,000 nats better than `kalman` or `reverting` | they are within ~2,000 nats of each other, and `reverting` is marginally *best* |
| `kalman`'s jerk pins at 1e-10 times its natural value, i.e. zero | it fits at **1e-2**, a sane interior value |
| "a lever driven to zero cannot carry a profile" | the lever was never at zero; its measurement variance was a thousandfold too large, so the filter trusted its state and wanted no process noise |
| the clock belongs on the level's wander and nowhere else | it belongs on **all three**, and most on `jerk` |

A test now pins the convention across five members. It is model-independent:
for a fixed innovation the standardised residual is `i / sqrt(P + R)`, so two
fresh members differing only in `R` satisfy `(i/z1)^2 - (i/z2)^2 = R1 - R2`
exactly, whatever `P` their dynamics produce. A member that squares `R` fails
it by a wide margin.

### And two more inconsistencies the same test found

* **`switching` divided a prior innovation by a posterior spread**, and one
  that excluded `R` altogether - so its standardised residual *shrank* as the
  measurement noise grew, which is backwards. A residual is a pre-update
  quantity. It now divides by the mixture's predictive spread, which carries
  the variance within the components, the spread between them, and `R`.
  `symmetry` had the same defect in a milder form and is fixed the same way.
* **`Walk.update` returns the raw innovation where every member returns the
  standardised residual.** Harnesses should read `last_standardised`, which
  all of them set, and the test does.

None of these is visible in a single-member study. All three corrupt any
comparison *between* members, which is the only kind this package exists to
make.

## The corrected answer

Each lever's base is swept over fourteen decades and chosen on the **matched
null**, `clock=None`, before the clock is applied - so the clock has to beat
the member at its own best setting rather than being credited with a
rescaling.

| instrument | level | jerk | reverting |
| --- | --- | --- | --- |
| EURUSD | -39.7 | **+195.4** | +18.2 |
| GBPUSD | -16.7 | **+187.7** | +22.8 |
| USDJPY | +81.1 | **+109.0** | +27.1 |
| XAUUSD | +87.1 | **+180.6** | +103.2 |
| XAGUSD | +4.7 | **+155.8** | +75.1 |
| BTCUSD | **+194.7** | +77.2 | +104.3 |
| ETHUSD | **+243.1** | +94.1 | +125.9 |
| **traded median** | +81.1 | **+155.8** | +75.1 |
| **clock broken** | -529.5 | -113.2 | -256.1 |
| **generated markets** | -0.7 | +0.2 | -0.2 |

**The `null loglike` column above is specific to this study's measurement
variance and should not be read as a general ranking.** `statespace-backtest.md`
measures the same members at a smaller `R` - a quarter of a bar move rather
than a whole one - and the walk then leads `kalman` by about 33,000 nats on
EURUSD rather than two thousand. A small `R` forces the filter to explain the
movement with its dynamics and so penalises bad dynamics heavily; a large one
lets measurement noise absorb the error and the models converge. An absolute
likelihood gap between two members means nothing without the `R` beside it.
The *clock* gains in this table are unaffected, because each lever's two arms
share an `R`.

* **The clock helps on all three levers**, in 19 of 21 traded cells. The two
  exceptions are the level on EURUSD and GBPUSD, where a well-set constant
  beats a clock-driven one.
* **It helps most on `kalman`'s jerk** - +155.8 at the median and positive on
  all seven instruments, which is the one lever that was dismissed before the
  fix.
* **Breaking the clock hurts on all three**, so the gain is alignment and not
  amplitude.
* **The generated markets gain nothing on any lever**, which is the control
  doing its job: they are real markets the desk trades, and what they lack is
  a session.

## The other correction, which stands

The earlier +197 on the level was measured with the process noise set from the
series' one-step spread rather than fitted. With the base swept first it is
**+81 at the median and negative on two of seven**. That correction is
independent of the convention bug - both arms there were the same member -
and it holds.

So two things were wrong with the original number in opposite directions: it
was too high for the level because the base was not fitted, and the lever
conclusion drawn from it was too narrow because the comparison was broken.

## What to do

* **Put the clock on `jerk`** if it goes anywhere: best median, positive
  everywhere, and the smallest misalignment penalty.
* **Fit the lever's base first**, every time. A multiplier whose sample mean
  is not exactly one is otherwise credited with the rescaling it performs.
* **Never compare two members without checking they read `noise` the same
  way.** The test is cheap, it is now in the suite, and it caught three
  separate inconsistencies on its first run.

The reusable lesson is the last one. This desk has now hit the
fitted-against-unfitted mistake three times - a walk's noise gaining +14,563
in `statespace-fitting.md`, an uncalibrated `Walk` handing out +99,444 in
`jpy-silver-pair.md`, and a rescaling credited to a clock here - and the
convention mistake once, with a much larger effect. Both are invisible without
a cross-member check.

The harness is `research/ideas/clock_levers.py`.
