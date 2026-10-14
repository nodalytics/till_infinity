# ADWIN wins the planted test, and the only detector the real feed moves is the one that loses it

`river.drift` offers ADWIN, Page-Hinkley and KSWIN. This package has two
detectors of its own - `changepoint.Changepoint`, a Bayesian online changepoint
detector, and `accruing.OneSided`, a CUSUM - and none of the five had ever been
scored against another.

The harness is `research/ideas/drift_detectors.py`.

## Calibrated first, or it is a threshold contest

Every detector has a sensitivity dial, and one set looser always finds a change
sooner. Comparing raw delays at whatever each library shipped measures the
defaults, so each is swept until it fires about **once per 2,000 bars on
driftless data** and only then measured:

| detector | dial | false alarms / 1k |
| --- | ---: | ---: |
| ADWIN | `delta` 0.70 | 0.525 |
| Page-Hinkley | `threshold` 50 | 0.725 |
| KSWIN | `alpha` 1e-3 | 0.600 |
| BOCPD | run-length mass 0.60 | 0.625 |
| CUSUM | threshold 6.0 | 0.725 |

All five land between 0.525 and 0.725 against a target of 0.500, so the
comparison below is one of **power at equal size**.

ADWIN needed `delta = 0.70` to get there, against a conventional 0.002. At its
shipped sensitivity it fires far below this target on this data, which is worth
knowing before anyone drops it in at the default.

## The planted test, and ADWIN wins it

A unit-sigma series whose drift flips sign every 400 bars, swept over drift
strength, detection counted within 200 bars. Each cell is the median delay in
bars and the share of switches caught.

| detector | 0.02 | 0.05 | 0.10 | 0.20 | 0.40 |
| --- | ---: | ---: | ---: | ---: | ---: |
| **ADWIN** | 47 / 15% | 127 / 21% | 95 / **48%** | 47 / **89%** | 31 / **97%** |
| Page-Hinkley | 154 / 18% | 151 / 18% | 167 / 29% | 102 / 92% | 48 / 97% |
| KSWIN | 102 / 14% | 102 / 14% | 106 / 20% | 57 / 30% | 28 / 79% |
| BOCPD | 79 / 5% | 156 / 6% | 147 / 5% | 47 / 11% | 8 / 21% |
| CUSUM | 79 / 21% | 121 / 23% | 116 / 26% | 72 / 38% | 40 / 49% |

**ADWIN beats both of this desk's detectors and both of River's others**, and not
narrowly: at 0.20 sigma per bar it catches **89%** of switches where the CUSUM
catches 38% and the BOCPD 11%, at the same false-alarm rate. At 0.40 it catches
97% in a median 31 bars.

**And everything is blind below 0.10 sigma per bar** - nothing exceeds 48%, most
sit near 20% - which is the part `show-power-before-reporting-a-null` asks for:
the strength at which the test stops working is as much the result as the
strength at which it works.

## Then the real feed inverts the ranking

Deriv does not publish `Drift_Switch`'s switch times, so the real feed can only
be asked how often each detector fires on a series designed to switch drift
against one specified not to. A ratio above one is the weakest form of the right
answer.

| detector | `Drift_Switch_10` | `Volatility_75` | ratio |
| --- | ---: | ---: | ---: |
| ADWIN | 0.375 | 0.550 | 0.68 |
| Page-Hinkley | 0.563 | 0.650 | 0.87 |
| KSWIN | 0.450 | 0.750 | 0.60 |
| **BOCPD** | 0.751 | 0.375 | **2.00** |
| CUSUM | 0.676 | 1.175 | 0.57 |

**Four of the five fire *less* on the feed that switches drift**, and the only
one above one is the BOCPD - which came last on the planted test by catch rate.

That inversion is the finding rather than a contradiction, and the reason is
that the two arms test different changes. The planted series shifts the **mean
of the returns**, which is what ADWIN, Page-Hinkley and a CUSUM are built for.
The BOCPD is built for a change in a piecewise-constant **level**, and it is the
one the real feed moves.

So `Drift_Switch_Index_10` is evidently not presenting a return-mean shift large
enough for a mean-shift detector to see at this false-alarm rate - which the
planted table predicts, since nothing catches more than half below 0.10 sigma
per bar.

## What to take

## Production already uses ADWIN, and already measured half of this

Found after the run, and it changes what the result is a contribution to:
`structures/learning/drift.py` imports `river.drift` and runs **ADWIN** as its
regime detector, with **KSWIN** added to cover the mean-shift blind spot. Its
docstring also records the comparison - *"KSWIN had fired **zero times** against
ADWIN's 136"* - which the planted table reproduces independently, at 30% against
89% at 0.20 sigma per bar.

So "ADWIN beats KSWIN" is **prod's existing position**, arrived at before this
ran, and this study rediscovered it. What is new here is the rest: the
**calibration to matched false alarms**, which turns a firing count into a
comparison; the **planted sweep**, which says where every detector goes blind;
and the ranking against **statespace's own** two detectors, which nothing had
scored before.

It is also a correction to how this series has been framed. River is in **ten
production modules** - `cycles`, `store`, `vol/learned`, `vol/volatility`,
`vol/har`, `learning/regimes`, `anomaly`, `facto`, `drift`, `decay` - so "does
River improve statespace" is often really "does statespace improve on what
production already gets from River", which is a different question with the
burden of proof the other way round.

## What to take

**ADWIN is worth having in `statespace`, which does not have it** - though
production does. The conditional quantile band lost and failed
its gate; the online learners' 3.6x turned out to be 87% a mis-set `Q`. A
detector that catches 89% against a CUSUM's 38% at matched false alarms is a
different kind of result, and `statespace` has no equivalent.

**Two cautions it comes with.** It needs `delta` near 0.7 here rather than its
conventional 0.002, so dropping it in at the default gives a detector that
barely fires. And it detects a shift in the mean, which is **not** what the one
real feed with a designed regime appears to present - so a `statespace` drift
channel wanting to catch that feed needs the BOCPD as well, not instead.

**And nothing here is a trading result.** This measures detection of a planted
mean shift. `direction-is-closed-not-just-null` records that a gate which finds
a planted drift at `z + 2.90` still earns two per cent of a spread, so a better
detector finds the same regime sooner and does not make it payable.
