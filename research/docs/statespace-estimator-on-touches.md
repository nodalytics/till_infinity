# Step two says do not swap the estimator: the Kalman is 18x sharper on touches

`docs/specs/2026-10-14-statespace-as-the-structures-library.md` made this step
two rather than step five, on the argument that the estimator is what every
later step hangs off, and it wrote down the risk explicitly:

> If `Pooled` on **touch-spaced** observations does not beat `levels.Kalman`,
> step 2 fails and steps 3 and 4 lose most of their value... That is a cheap
> thing to find out and it is why it is step 2 rather than step 5.

It fails. The spec was right to ask first.

The harness is `research/ideas/estimator_on_touches.py`.

## Why closes were the wrong test

`Pooled` was measured at **5.6x** on CRPS over the best single member and
**2.7x** again from `Adapting`, both on a close every bar. A level is observed
only when price **comes to it** - irregular, bursty, separated by hours or
days - and what carries a filter across a gap is its process noise. That is a
different question, and `statespace-activity-on-production-q.md` had already
hinted the answer would differ: the production filter wanted a process noise
**16,384 times** its constant when fed closes, which is the symptom of a filter
tuned for sparse observations being handed dense ones.

Touches are reconstructed from bars rather than replayed, because the journal's
`closes` extract is 1,202 rows of **closed trades** - a selected sample far too
thin to fit a filter on. A level is a rolling extreme taken once and held; a
touch is a bar whose range contains it; the observation is that bar's close.
170 levels on six traded instruments, a median of 147 touches each.

## The answer

Everything in **log price**, so a CRPS is a relative error. The Kalman gets a
grid refit of its process noise - its best case; `Pooled` gets none, because
`Adapting` is meant to find its own.

| | arm | loglike/touch | PIT | **CRPS** |
| --- | --- | ---: | ---: | ---: |
| **traded**, 170 levels | `levels.Kalman`, best grid | **4.9355** | 89.15 | **0.000853** |
| | `Pooled(adapt=False)` | 3.2370 | 16.76 | 0.037951 |
| | `Pooled(adapt=True)` | 3.8413 | **6.66** | 0.015137 |
| **generated**, 60 levels | `levels.Kalman`, best grid | **3.5421** | 2.77 | **0.003716** |
| | `Pooled(adapt=False)` | 2.9814 | 6.99 | 0.026631 |
| | `Pooled(adapt=True)` | 3.2063 | **1.35** | 0.013594 |

**The production filter wins by 18x on CRPS** on traded levels and 3.7x on
generated. The 5.6x that `Pooled` earned on dense closes does not merely shrink
on touch spacing - it **reverses**, and by a larger factor than it ever won by.

The reason is visible in what the two models are. `levels.Kalman` is a
`(price, slope, acceleration)` constant-velocity model built for a slowly
drifting quantity observed at irregular intervals, and it was given its best
process noise over a wide grid. The pool's members are price members whose
measured gains were all on dense series. Asked the question it was designed for,
the incumbent is far better - which is the ordinary result and the one worth
having before a migration step, not after.

## But the split is not uniform, and the other half is actionable

**`Pooled(adapt=True)` is 13x better calibrated**: a PIT flatness of **6.66**
against the Kalman's **89.15** on traded, and **1.35** against 2.77 on
generated, where 1.0 is calibrated.

So the two models fail in opposite directions. The Kalman is much **sharper**
and badly over-confident; the pool is much **wider** and nearly honest. CRPS
penalises both and the sharpness wins it, because an 18x advantage in width
swamps a 13x advantage in calibration.

That decomposition is the useful output of this step, because it says the
cheaper change is not a replacement:

**Keep `levels.Kalman` and fix its calibration.** It is at 89 where 1.0 is
calibrated, and the façade already publishes the instrument that fixes that -
the shape-free band from a filter's own standardised residuals, measured at CRPS
0.9899 against a Gaussian's 1.0000 and at a PIT of 1.5 where no Gaussian band
on this desk has ever been calibrated. Wrapping the incumbent's point forecast
in that band keeps the 18x sharpness and removes the over-confidence, which is
a smaller change than swapping the estimator and is supported by two
measurements rather than one.

**And `Adapting` helps here too**, which is now four for four. `adapt=True`
beats `adapt=False` on every figure in the table - CRPS 0.015 against 0.038,
PIT 6.66 against 16.76 - so whatever else is true, a member that fits its own
process noise beats one that does not, on dense closes and on sparse touches
alike.

## What it does to the spec

**Step 2 is answered no, and steps 3 to 5 keep their value rather than losing
it** - which is the opposite of what the spec predicted would follow from a
failure, and worth correcting there.

The spec's reasoning was that the band, the barrier probabilities and the
activity channel all improve a thing that is only as good as the estimator
underneath. That holds - but the estimator underneath is now measured as the
**incumbent**, not as a thing that needs replacing first. So:

* **step 3, the band, becomes the most valuable step rather than the third**,
  because the measurement above says the incumbent's weakness is calibration
  and the band is what fixes calibration;
* **step 4, activity on `Q`**, is unaffected: it was already measured on
  `levels.Kalman` itself at +0.0513 per observation on 7 of 8 instruments;
* **step 5, `bounding`**, is unaffected;
* and the façade needs no change. `Desk.read` publishes a pool because that is
  what statespace has; a caller tracking a level should keep using its own
  filter and take the band, the walls and the gating from here.

## One defect, and it is the same one twice

The first run was in **raw price** and read a CRPS of 170 on the generated feeds
against 0.0012 on traded - which is a comparison of quote conventions, since
CRPS is in the units of the thing forecast and gold is quoted at 2,000 while
EURUSD is at 1.1. The medians across a mixed group were meaningless, in both
groups.

`statespace-conditional-quantiles.md` needed the identical correction a few
hours earlier, where feeding River raw returns of order `1e-4` produced a band
with no width. Working in the units where the quantity is of order one is not a
detail of either study; it is the thing that decides whether either produces an
answer.
