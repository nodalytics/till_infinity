# Real levels emit nothing at a touch, down to a fiftieth of a standard deviation

`statespace-conditional-holds.md` closed the **per-level** question: `tau` over
279 levels came back at 0.0109 against a simulated null of 0.0085, so a level's
own record is sampling noise. The instruction on 2026-10-14 was that this is not
the whole question:

> real levels should emit or give some kind of signal before, during or after
> for us to know if they are real, it might just be a tiny signal

That is the right objection. `tau` asks whether level #47 differs from level
#48, and dies on a dozen touches per level. This asks whether a touch at a real
level **looks different from a touch at a price that is not one**, pooled over
every touch - thousands in one cell instead of a dozen per level, which is the
only place a tiny signal could still have been alive.

It is not alive. Nineteen observables across the three windows, on 2,782 touches
over 381 non-overlapping matched pairs, produce **nothing further than 0.005
from an AUC of 0.5**, family-wise p 0.963 - while a planted shift of 0.02
standard deviations is caught at p 0.020.

## The panel

Scale-free so instruments pool, each measured in units of the typical bar over
the preceding hundred (`research/ideas/level_signatures.py`):

| window | observables |
| --- | --- |
| before | approach speed, deceleration, range ramp, volume ramp, standoff a bar earlier, momentum turns, acceleration turns |
| during | wick on the touched side, body, rejection, overshoot past the price, range spike, volume spike, spread spike, `wick x volume` |
| after | retrace, activity, volume, drift through |

`wick x volume` is the CWRV combination from the reading given on 2026-10-14: a
long wick on heavy volume is absorption, the same wick on light volume is
nothing. No hold rate appears - the dead statistic is excluded on purpose.

## Three controls, because the detector defines half the panel

A real level here is a 100-bar extreme, so a touch at one is **by construction**
a visit to a price not exceeded in a hundred bars. Several `before` and `during`
measures would separate that from an arbitrary price on the definition alone.

1. **A distance-matched placebo**, at the same signed distance from the current
   close times a jitter of ±15%, walked forward through the identical detector.
2. **A block-shuffled copy of the same instrument** - the same bars in blocks of
   fifty, re-levelled in log space, each bar keeping its own open, high, low,
   volume and spread. Bar geometry, volatility clustering and the marginal
   return distribution survive; level structure does not. Extremes are
   re-detected there, so the shuffled arm carries the identical definitional
   advantage and no real levels.
3. **Deriv synthetics** - real markets with a known generator and no auction,
   including two independent volatility indices as the placebo pair this desk
   carries in every relationship harness.

The null flips the real/placebo label **within a matched pair**, all of that
pair's events together, four hundred times. The family-wise p is the fraction of
draws whose widest `|AUC - 0.5|` beats the observed widest, so nineteen chances
at 0.05 do not buy a finding.

## What the first read said, and why it was wrong

The first configuration spaced eighty anchors over each series and watched 1,500
bars forward from each, so **pairs overlapped six deep**. It reported:

| | traded | generated |
| --- | ---: | ---: |
| family-wise p | **0.015** | 0.152 |
| widest pass | `overshoot` 0.4880, p **0.002** | `retrace3` 0.4871, p 0.007 |

An AUC of 0.488 on overshoot, family-wise significant, absent from the shuffled
arm: touches at real levels poking through by less than touches at arbitrary
prices. It is a plausible mechanism and it would have shipped.

It was the overlap. A permutation that flips pair labels treats pairs as
independent, and pairs sharing bars are not, so the null was drawn too narrow -
which is why the **generated** feeds, whose processes have no levels at all,
produced a pass at p 0.007 in the same run. Spacing anchors at least one horizon
apart is the only change:

| | overlapping | spaced |
| --- | ---: | ---: |
| traded family-wise p | 0.015 | **0.499** |
| `overshoot` | 0.4880, p 0.002 | 0.4923, p 0.307 |

## The result

Spaced anchors, horizon shortened to 400 bars to buy back the pairs that spacing
costs:

| | traded | generated |
| --- | ---: | ---: |
| matched pairs | 381 | 174 |
| real-level touches | 2,782 | 1,467 |
| widest `\|AUC - 0.5\|` | **0.005** | 0.006 |
| marginal passes of 19 | **0** | 1 |
| family-wise p | **0.963** | 0.449 |
| first visit only, family-wise p | 0.885 | 0.591 |
| visits: real vs placebo | 7.30 vs 7.33, p 0.771 | 8.43 vs 8.45, p 0.955 |

Every one of the nineteen sits between 0.4946 and 0.5039 on traded. The one
generated pass is `sprd` at 0.4938, whose difference in its own units is
**-0.0004** on a ratio of 1.0 and whose only significant subgroup is the
placebos that landed *inside* the extreme.

**First visits only** is reported separately because a level tested nine times
is not what anyone means by the question; the first test is. 381 fresh touches,
family-wise p 0.885, widest `overshoot` at 0.5143 with p 0.322.

The visit counts are a consistency check on the magnet effect already refuted in
`docs/`, and they agree: a real level is touched no more often than a matched
price.

## What "tiny" would have to mean

A null is worth nothing without the size it could have seen, so a known shift
was planted on the real events only and swept:

| planted shift | 0.02 sd | 0.05 sd | 0.10 sd | 0.20 sd |
| --- | ---: | ---: | ---: | ---: |
| `wick` AUC | 0.5101 | 0.5202 | 0.5369 | 0.5692 |
| `wick` p | **0.020** | 0.002 | 0.002 | 0.002 |
| `retrace3` AUC | 0.5086 | 0.5198 | 0.5382 | 0.5746 |
| `retrace3` p | **0.015** | 0.002 | 0.002 | 0.002 |

So the design sees two hundredths of a standard deviation. The widest thing it
found was 0.005 of AUC, a quarter of what a 0.02 sd plant produces. For the
signal to be real and missed it would have to be smaller than 0.02 sd - which is
below anything a spread could be crossed for.

## What this closes, and the one door it leaves open

Closed: a touch at a 100-bar extreme on 1h is indistinguishable from a touch at
a matched arbitrary price, in approach, in the touching bar, and in what follows
- including every candle-orderflow reading available without L2, and including
the wick-volume combination. Fresh touches too. Attraction too.

Open, and the only thing left: **the level definition**. This tested one
nomination - the lookback extreme - and `structures/drawing` runs fourteen
proposers, among them volume-profile nodes, range edges and displacement origins.
`statespace-ranging.md` refuted those as *nominations*, by asking whether price
holds there. It did not ask this question of them, and the harness takes any
price series and any price: pointing it at `drawing`'s own proposals is one
loop, and is the next thing worth doing.

What should not be done is re-running this panel on more instruments or a finer
frame. At 0.02 sd of power and 0.005 of observed effect, more data buys
precision on a zero.
