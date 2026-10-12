# Allan variance: two solid findings and one I nearly over-sold

Asked whether chronometry and horology have anything for this package. Most of
the field does not, and that is worth saying first: there is no mechanism by
which relativistic or quantum time affects a price series, and this desk's
record with physics metaphors is **six nulls from six** - the Landau cubic, the
SOC Gini, Kuramoto, laminarity, Lempel-Ziv and the displacement family.

**One piece fits without any analogy.** A clock's state is `(phase,
frequency)`; this package's two-state members carry `(value, rate)`. Same state
space. So clock metrology's noise-identification tool is not a metaphor being
imported, it is the same estimator applied to the same object.

The harness is `research/ideas/allan_variance.py`.

## The estimator

The overlapping Allan variance of a phase series at averaging interval `m`:

    sigma2_y(m) = mean (x[k+2m] - 2 x[k+m] + x[k])^2 / (2 m^2)

Its log-log slope names the noise: `-2` white phase, `-1` white frequency -
which is **a random walk in the phase** - `0` flicker or `1/f`, `+1`
random-walk frequency, `+2` drift.

It exists because the sample variance **does not converge** for `1/f` noise,
which turns out to be the regime this desk's volatility is in - so the tool was
built for exactly the problem that is here.

## Finding 1: on log price it reads the walk and nothing else

Slopes of `-0.86` to `-1.12` across every interval band from 1 bar to 336, on
all thirteen series including the constant-volatility controls. No deviation
anywhere, and `dip@24` straddles 1.0 on both groups.

Already known - the walk is the best-calibrated band here - so this is a
confirmation from a new direction rather than a finding. It also says the
useful series is not this one.

## Finding 2: on log volatility it separates completely, and confirms long memory

Allan variance measures the noise of a **rate**, so the series it is given has
to be the integral of the quantity of interest. Log price is the integral of
returns; the right second series is the integral of log volatility.

| | cells | median slope 1-8 | median slope 48-336 |
| --- | ---: | ---: | ---: |
| **traded** | 9 | **+0.77** (range +0.72 to +0.93) | **-0.32** (range -0.06 to -0.46) |
| **constant volatility** | 4 | **+0.53** (range +0.53 to +0.55) | **-0.97** (range -0.94 to -1.04) |

**Neither column overlaps.** Thirteen cells, two clean separations.

**The control's long-interval `-1.00` is the calibration that makes this
readable.** White frequency noise means the log-volatility "phase" is a pure
random walk, which is what an *uncorrelated* estimate produces - exactly right
for a feed whose volatility is constant and whose every estimated deviation is
noise. Their `+0.53` at short intervals is the smoothing's own floor, not
structure.

**The traded feeds read `-0.32` where the controls read `-1.00`.** A slope near
zero is flicker, `1/f`, **long memory** - and that is an independent
confirmation of the rough-volatility result already measured here by a
completely different estimator (`H` of log volatility at 0.022 against a
known-0.5 process's 0.141). Two unrelated tools, same conclusion, with the
generated feeds calibrating both.

## Finding 3: the period finder works on planted data and does *not* establish on real

This is the one I nearly reported as a result, and the correction is the useful
part of this document.

Averaging over exactly one period of a periodic component cancels it, so the
Allan variance **dips** at that interval. That would make the estimator a
model-free period finder - which is precisely what `seasonal.PERIODS`
currently has to be told, and what the ladder measurement had to guess at.

**Planted, it works.** Brownian increments whose scale cycles at a known
period, dip measured against the geometric trend of its neighbours:

| planted period | dip@12 | dip@24 | dip@48 | dip@72 |
| ---: | ---: | ---: | ---: | ---: |
| 12 | **0.876** | 0.949 | 1.064 | 1.116 |
| 24 | 1.309 | **0.890** | 0.883 | 1.045 |
| 48 | 1.085 | 1.144 | **0.718** | 1.845 |
| 72 | 1.009 | 1.052 | 1.177 | **0.516** |

Dips land on the planted period **and its integer multiples** - row 24 also
dips at 48 - and never at sub-multiples: row 48 does *not* dip at 24. Both are
correct, because averaging over two whole periods cancels a cycle and
averaging over half of one does not.

**On real data it does not separate.**

| | cells | median dip@24 | share below 1.0 |
| --- | ---: | ---: | ---: |
| traded | 9 | **0.966** | **1.00** |
| constant volatility | 4 | 0.996 | **0.75** |

All nine traded feeds dip - and **three of the four controls dip too.** A
0.03 gap in the median with the control on the same side of 1.0 is not a
result.

### And the first pass looked much better, for a reason worth keeping

A scratch probe gave traded 0.659 to 0.915 against generated 1.028 to 1.071 -
complete separation, and I was ready to call it a model-free period finder.
**The difference was the interval grid, not the data.** That probe used a
sparse ladder where the rungs either side of 24 were 12, 16, 32 and 48, so the
trend baseline was measured far from the feature. The proper harness has rungs
at 18, 20, 22, 26, 28 - all inside the dip's own width - so the "trend" it is
compared against is partly the dip.

Reporting the sparse version would have been **picking the grid that
flattered the claim**, and nothing in the first output said which grid was
right. The dense one is right, and the honest number is 0.966 against 0.996.

### Why it is buried, which ties the findings together

The planted series has *white* log volatility plus a clean 45% cycle. A real
feed has the `1/f` component Finding 2 measures, and that component contributes
variance at **every** interval. So the long memory the slope detects is what
hides the period from the dip: the cycle is there - the `seasonal` clock is
worth +1055 nats on these same instruments - and the Allan variance cannot see
it past the flicker noise.

That is a coherent story rather than two separate results, and it means the
period finder would need the `1/f` component removed first, which is a
different piece of work.

## What this is worth

* A **second, independent confirmation of long-memory volatility**, with a
  perfect 13-cell separation and the controls calibrating it.
* A **noise-type classifier** that needs no fitting: the slope says which
  member's noise structure a series has, and on log price it says "random
  walk" everywhere, which is the same wall every member reaches.
* An estimator **designed for `1/f`**, which is the regime this desk's
  volatility is in - so `allan` is the right variance to quote for a
  log-volatility quantity, where the sample variance does not converge.

What it is not is a period finder on real data, and it is not an argument for
importing anything else from the physics of time.

## The one chronometry idea still untested

**The volume clock.** Chronology's real contribution is that the ordering of
events need not be indexed by calendar time, and the subordination literature
holds that returns are closer to i.i.d. Gaussian when sampled in equal-volume
or equal-tick increments. The cache carries a `volume` column and every
measurement in this package is in calendar time.

That makes a sharp question: **does sampling in volume time make the `Q` clock
unnecessary?** The clock is worth +1055 nats precisely by modelling how
variance varies with the calendar hour, and a volume clock would absorb that
automatically. If it does, the +1055 is a calendar artefact and the fix is a
sampling change rather than a member. If it does not, the pattern is in time
and not in activity, which is a stronger statement than the clock currently
makes.
