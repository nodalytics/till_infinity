# Four public BOCPD designs, priced: the increment is the inferred variance and the estimator, not the recursion

**2026-10-20. [`research/ideas/hazard_arms.py`](../ideas/hazard_arms.py),
1h, three instruments per class, median increment to a 48-lag ridge
forecasting forward log variance.**

[`indicator-libraries.md`](indicator-libraries.md) judged eight public sources
on paper and named three portable ideas and one refusal. This turns each into a
number on the metric [`changepoint-increment.md`](changepoint-increment.md)
established - what a change-point member's inferred predictive standard
deviation adds to `lin48` - and **two of the paper verdicts do not survive it.**

The baseline reproduces before anything is read: fx_cross h=20 `lin48` at
**0.2268** and `+sd` at 0.4036, against the published +0.2009 and +0.4286 on a
larger instrument sample.

## The table

h=1, increments over `lin48`:

| arm | fx_cross | fx_major | metal | volatility *(no regime to detect)* |
|---|---:|---:|---:|---:|
| `lin48` baseline | 0.1051 | 0.0920 | 0.6775 | -0.0082 |
| ours, hazard x0.25 | +0.1970 | +0.2268 | +0.0000 | -0.0000 |
| **ours, fixed (shipped)** | **+0.2028** | **+0.2306** | +0.0000 | +0.0000 |
| ours, hazard x4 | +0.2065 | +0.2335 | +0.0003 | +0.0000 |
| ours, adaptive hazard | +0.2058 | +0.2317 | +0.0002 | -0.0000 |
| ours, adaptive (any-fall rule) | +0.2054 | +0.2323 | +0.0008 | -0.0001 |
| ours, adaptive (AE-SHIFT's rule) | +0.2050 | +0.2310 | +0.0002 | -0.0000 |
| **ours, on close-to-close** | **-0.0074** | **-0.0030** | -0.0002 | -0.0001 |
| theirs, AE-SHIFT plug-in | +0.0003 | +0.0000 | -0.0000 | +0.0000 |
| theirs, AE-SHIFT conjugate | +0.0002 | -0.0025 | +0.0000 | +0.0000 |
| theirs, score-driven variance | +0.0003 | +0.0009 | +0.0000 | +0.0000 |
| theirs, AE-BCP | +0.0002 | +0.0001 | +0.0000 | +0.0000 |
| entropy, binary (as published) | -0.0007 | -0.0107 | -0.0000 | -0.0000 |
| entropy, ternary (as published) | +0.0005 | -0.0000 | +0.0006 | -0.0000 |
| entropy, transition | -0.0004 | -0.0119 | +0.0000 | -0.0000 |
| entropy, 3-gram block | -0.0005 | -0.0001 | +0.0000 | -0.0000 |

h=20 moves nothing qualitatively: `lin48` 0.2268 / 0.1451 / 0.8548 / -0.0032,
ours fixed **+0.1768 / +0.0832**, the hazard sweep spanning +0.1694 to +0.1802,
every `theirs` arm inside +0.0049, close-to-close **-0.0205 / -0.0021**, and the
entropy arms from -0.0374 to +0.0005. Metals is saturated at both horizons, as
[`changepoint-increment.md`](changepoint-increment.md) already found, and the
constant-sigma family reads +-0.0001 on all sixteen arms - a control for
exactly one property, that there is no regime to find, which is the thing a
change-point arm has to be measured against and the only thing this family
licenses a claim about.

## 1. The hazard is not what limits this member

A **sixteen-fold** sweep of the fixed hazard moves the increment by 0.007, and
the ordering flips with the horizon: `x4` is best at h=1 and `x0.25` is best at
h=20. An adaptive hazard lands between them, +-0.001 of fixed in every traded
cell. There was nothing for it to find.

That control is why this is a finding rather than a null. An adaptive parameter
that matches the best fixed value has saved a parameter; one that matches
*every* fixed value across a sixteen-fold range is reporting that the parameter
does not bind.

Part A says the same from the other side. On a planted series with a **known**
regime spacing of 20, 60 or 200 bars - where the shipped hazard of one change
per 240 bars is wrong by up to twelvefold - every arm reads +0.0000 to -0.0001
over a `lin48` of 0.1224 to 0.2791. **The plant has no power for this metric at
all**, which is itself worth recording: if the +0.20 on real bars were
piecewise-constant regimes in log variance, a piecewise-constant log variance
would show it. It does not, so whatever `sd` captures on a market is not that.

## 2. The learned hazard is a property of the detector, not of the series

| rule | fx_cross | fx_major | metal | planted 20 / 60 / 200 |
|---|---|---|---|---|
| any fall in run length | 1/6.3h | 1/6.2h | 1/5.0h | 1/5h / 1/5h / 1/5h |
| run length halved | 1/85.0h | 1/69.2h | 1/93.5h | 1/181h / 1/138h / 1/202h |
| halved, then AE-SHIFT's signal gate | 1/144.2h | 1/122.8h | 1/275.1h | - |

The any-fall rule learns one change per five to six hours on every traded class
**and on every planted spacing from 20 to 200 bars**. It is reporting its own
trigger rate. The halved rule is monotone in the planted spacing at high
signal-to-noise and flat at the ratio real log variance has, so at realistic
noise a reset detector cannot measure regime spacing - there is nothing to
learn from even in principle.

**AE-SHIFT's flaw is confirmed in the predicted direction and costs nothing.**
Learning the spacing only from *fired signals* - which need a detection, a
direction and an alternating side - biases the learned run length **1.5x to 3x
longer** (1/123h to 1/275h against 1/69h to 1/94h). The bias is real; it is
harmless here only because nothing rides on the hazard.

## 3. The recursion carries nothing. The inferred variance does.

**This is the finding, and it corrects the critique
[`indicator-libraries.md`](indicator-libraries.md) made on paper.** A faithful
reimplementation of AE-SHIFT's recursion - per-hypothesis Welford statistics
that travel with the run length, growth and change-point mass, normalisation -
fed the *same observation* as ours, adds **+0.0003** where ours adds **+0.20**.

The paper critique was that its plug-in sample variance is over-confident at a
reset, where the conjugate predictive carries `1 + 1/n`. That arm is here:
swapping the plug-in for the conjugate inflation and changing nothing else
reads **+0.0002**. The defect is real and it is not what matters, because the
recursion is not what is paying.

What is left, once the hazard and the conjugate inflation are both measured
inert, is the **variance scale**: ours infers its measurement variance from the
data (the only member in the package that does), while theirs adds a fixed
`obs_var` to a floored sample variance, so its mixture predictive spread barely
varies and carries little information to regress on. That is now the one live
candidate rather than an assumption, and **one arm settles it** - give the
reimplementation an inferred `obs_var` and see whether it moves from +0.000
toward +0.20. Until that runs, the honest claim is "the recursion is not what
pays, and the inferred scale is the remaining difference".

## 4. The estimator is the other half of the effect

`ours.on close-to-close` is our own member, unchanged, fed `log(r^2)` instead of
log Parkinson. It reads **-0.0074** at h=1 and **-0.0205** at h=20.

So AE-BCP's observation choice does not degrade the effect, it **erases** it,
and [`dispersion-noise.md`](dispersion-noise.md) gives the mechanism as a
number: the sampling variance of `log(r^2)` is **4.93** against **0.265** for
log Garman-Klass, 18.6x noisier per bar. `theirs.aebcp` reads +0.0002 for that
reason compounded by a standardisation that removes the variance it might
otherwise have inferred.

A one-line change to the observation is the difference between +0.20 and
nothing. That is the most portable thing on this page and it travels in the
opposite direction to the one expected - **out** to those scripts, not in.

## 5. Two paper verdicts retracted

**Score-driven variance is not worth porting.** Implemented as the paper gives
it - linear in the score, not `RegimeLib`'s quartic - it reads **+0.0003 to
+0.0049**, best case about two per cent of the shipped member's increment.
`indicator-libraries.md` called it the one component worth taking from
RegimeLib. On this metric it is not.

**The entropy idea is closed in all four forms.** Part 0 proved arithmetically
that the two published statistics cannot see order: on one window with every
count held fixed and 200 permutations, binary entropy reads 1.0000 both ways
and ternary 0.9169 both ways, with a spread of **0.000000**. The sequence
versions do see order - transition separates ordered from shuffled 0.6249 to
0.9917, block entropy 0.4964 to 0.9726 - and as dispersion features they read
**-0.0119 and -0.0167 (transition)** and **-0.0172 (block)** on fx_cross and
fx_major. Negative, because a ridge pays for a noise column. The form I argued
was "the only form the idea was ever worth" is measured, and it is worth less
than nothing.

## What the member should be judged on now

Everything that is not the observation or the inferred scale has been measured
inert: the hazard over sixteenfold, the hazard's adaptivity, the detector that
would drive it, the conjugate inflation, score-driven variance, and four
entropies. Two things remain, and both are already named - the `Q` sweep in
[`dispersion-noise.md`](dispersion-noise.md), and the EWMA control in the
regression frame that [`statespace-anomaly.md`](statespace-anomaly.md) left
open after closing it for classification.
