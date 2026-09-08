# Three change detectors added, and only one of them is quiet

Built 2026-09-08. `river.drift.ADWIN` was already in production and consumed -
it discounts every level's accumulated history on a confirmed change - so the
question was which of the remaining families adds something, and what each
costs when it is wrong.

The cost of being wrong is the whole frame here, and `learning/drift.py` states
it: **a spurious drift throws away real evidence.** That is what made ADWIN
conservative once anything acted on it, and any detector added beside it
inherits the same bill. So all three below are wired to decide nothing.

## What each one is for

| | watches | catches what ADWIN cannot |
| --- | --- | --- |
| **KSWIN** | the price stream | a change in **distribution** with no change in mean |
| **DDM / EDDM** | a model's **error** stream | a model that has stopped working |
| **FOCuS** | the price stream | the exact best changepoint, and **where** it was |

ADWIN tests a change in the mean via a Hoeffding bound on two halves of its
window. A distribution that widens symmetrically leaves the mean where it was,
and on this desk that is the ordinary case rather than an exotic one - which is
the gap KSWIN fills. DDM and EDDM fill a different one entirely: nothing here
watched a *model*, and every model-decay finding in this folder was noticed by a
person running a measurement.

## The null, which is the only comparison that means anything

A detector is worth what it beats chance by, so each was run against a stream
with **no change in it**, where the right number of alarms is zero.

**DDM and EDDM, on a stationary binary error stream**, 3,000 observations,
averaged over five seeds:

| true error rate | DDM alarms | EDDM alarms |
| --- | --- | --- |
| 5% | 1.0 | 3.2 |
| 20% | 0.6 | 8.8 |
| 50% | 0.4 | **11.2** |

**EDDM alarms once every 270 to 940 observations on a model that has not
changed**, and its rate rises with the *error rate* rather than with any drift.
DDM is far better and still not zero.

**FOCuS, on a stationary Gaussian stream**, five runs of 3,000: **at most 5
alarms in total**, across all five, at the threshold it ships with.

Those two are **not directly comparable** - one watches binary errors and the
other a continuous signal - and saying otherwise would be the sort of
apples-to-oranges this folder exists to avoid. What is comparable is each
against its own null, and on that basis FOCuS is the only one of the three that
can be read as an alarm rather than as a counter.

## KSWIN, measured in production: silent

`Drift` has run ADWIN and KSWIN side by side since the KSWIN work, with the
counters read by nothing until `drift_tally` started logging them on
2026-09-08. The first hours:

    drift: adwin 27, kswin 0, both 0, kswin alone 0

**`kswin_alone` is the number this was built to produce, and it is zero.** So
is `kswin`. KSWIN has not fired once against ADWIN's 27.

**That is not yet a verdict on KSWIN.** `KS_ALPHA` here is 0.0005 against
River's default of 0.005 - ten times stricter, chosen to be conservative
because a false alarm discounts real evidence. A detector that never fires at
a tenth of the usual significance is telling you about the significance, not
about the detector.

So the honest reading is that **the experiment as configured cannot answer its
own question**, and there are two ways forward:

* Run it at River's 0.005 and see whether `kswin_alone` becomes non-zero. If it
  does, the question becomes whether those extra alarms are worth their false
  positives - which is a measurement, and this is the counter for it.
* Or accept that a second detector which is silent at the significance this
  desk is willing to act on is not earning its window, and take it out.

Either is defensible. Leaving it as it is - running, counted, and unable to
produce a non-zero reading - is not.

## So the readings mean different things

* **FOCuS** can be believed when it fires, and it says **where** the change
  started, which a threshold-crossing CUSUM cannot. `Cusum` accumulates until
  it trips; FOCuS maximises the likelihood ratio over every possible
  changepoint and reports the argmax.
* **KSWIN** is a counter. `Drift.watching()` reports `kswin_alone` - the times
  it fired when ADWIN did not - and that number decides whether it is worth
  listening to before anything listens.
* **DDM and EDDM** are counters that have to be read **against the stationary
  baseline for that model's error rate**, which is why `decay.Reading` carries
  `error_rate` beside the counts. "EDDM fired" means nothing on its own.

## FOCuS is written here rather than installed, and why

`changepoint-online` publishes the reference implementation and is **GPLv3**.
This repository is public, carries no licence file, and publishes a Docker
image to `ghcr.io` - so taking the package would put copyleft over the combined
work and settle a licensing question by accident. The algorithm is published in
the literature, and implementing a published algorithm is not a derivative of
somebody else's implementation, so `learning/focus.py` writes it out. Nothing
is copied from that package.

**What is claimed is exactness, not the complexity bound.** The statistic
returned equals the brute-force maximum over every changepoint, and
`tests/test_focus.py` asserts that against an O(n^2) reference **on every
step** rather than at the end. The pruning is the lower convex hull of the
partial sums, which is amortised O(1) to maintain; the literature's O(log n)
needs a sharper search over the hull than this does, and the honest word for
what is here is "pruned", not "logarithmic".

## What has not been done

None of the three is consumed. That is the same order `break_probability` was
introduced under - published for weeks before anything acted - and the reason is
in the first paragraph.

The next measurements, cheapest first:

1. **`kswin_alone` after a week of production.** If it is near zero, KSWIN sees
   nothing ADWIN missed and costs a window size for nothing.
2. **FOCuS against `Cusum` in the estimator harness** in
   [localising.md](localising.md), which already ranks change-point estimators
   by stability under an arbitrary sampling grid and scored `Cusum` at 0.205v
   against a fine-resolution transition's 0.124v. That table has a slot for
   this and a baseline to beat.
3. **DDM and EDDM pointed at the break model**, whose miscalibration is already
   established - so there is a known event to detect, which is the only way to
   tell a detector that works from one that is quiet.
