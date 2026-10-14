# A touch carries about a fiftieth of a standard deviation, and only where the level is built in

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

On traded instruments it is not alive. Nineteen observables across the three
windows, on 6,902 touches over 1,164 non-overlapping matched pairs, produce
**nothing further than 0.006 from an AUC of 0.5**, family-wise p 0.828 - while a
planted shift of 0.02 standard deviations is caught at p 0.020.

The number that matters is not that one. Deriv's range-break processes are real
markets whose **generator has a range that breaks**, so a level exists there by
construction, and they were added as the positive control: a panel that cannot
see a touch at a level someone built is not evidence about levels. That control
is **also** family-wise null, p 0.239, but its marginal readings are all in the
direction a real level predicts and all sit at the same magnitude - about 0.02
standard deviations, which is its own detection floor at 203 pairs.

So the honest reading is narrower and more useful than a null: **the signature a
touch can carry is about a fiftieth of a standard deviation even when the level
is built into the generator**, and traded instruments show none of it with five
times the pairs.

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
| matched pairs | 1,164 | 353 |
| real-level touches | 6,902 | 2,221 |
| widest `\|AUC - 0.5\|` | **0.006** | 0.014 |
| marginal passes of 19 | **0** | 1 |
| family-wise p | **0.828** | 0.100 |
| first touch only, family-wise p | 0.993 | 0.077 |
| visits: real vs placebo | 5.93 vs 5.95, p 0.646 | 6.29 vs 6.33, p 0.698 |

Twelve feeds, 250 anchors apiece, anchors spaced a full horizon apart. The one
generated pass is `accel_turns` at 0.4862 - on processes with no levels at all,
which is what one pass in nineteen looks like.

**First touch only** is its own arm, with its own power sweep, because one event
a pair is a sixth of the sample and a null without power is not a result. On
traded: 1,164 fresh touches, family-wise p 0.993. It was called the arm that
makes sense, and it is - a level tested nine times is not what the question
means. It is also the arm where the control came closest, `overshoot` at 0.4631.

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

## The positive control, which is the only reason any of this is interpretable

| | every touch | first touch only |
| --- | ---: | ---: |
| pairs | 203 | 203 |
| family-wise p | 0.239 | 0.135 |
| `activity5` | **0.4865**, p 0.010 | 0.5049, p 0.711 |
| `retrace3` | 0.4876, p 0.052 | 0.5079, p 0.633 |
| `drift5` | **0.5125**, p 0.045 | 0.4943, p 0.661 |
| `overshoot` | 0.4980, p 0.818 | **0.4631**, p 0.045 |

Three of nineteen pass marginally on every touch and one on first touch, where
traded passes none of nineteen and the level-free volatility indices pass one.
The signs are what a real boundary predicts: **less** activity after the touch,
**less** retrace, **less** overshoot through, and **more** drift through - which
is right for a process whose range is going to break.

And they are the size the arm can just about see. `activity5` is 0.0135 of AUC
from 0.5 and -0.0204 in its own units, while the planted sweep on the same arm
needs 0.05 sd for p 0.002 and gives p 0.075 at 0.02 sd. The control's findings
sit exactly on its floor.

This is the asset to keep. Any new level observable can be put through this
control **before** it is believed on traded data, the same way an FX screen that
misses currency triangles is broken whatever else it reports.

What it also says is that 203 pairs is not enough to settle it. The control has
two feeds against traded's twelve, and matching its sample - more frames of the
same two processes - is what would turn its 0.239 into a verdict either way.

## What this closes, and the one door it leaves open

Closed **for these nineteen observables**: a touch at a 100-bar extreme on 1h is
indistinguishable from a touch at a matched arbitrary price, in approach, in the
touching bar, and in what follows - including every candle-orderflow reading
available without L2, and including the wick-volume combination. Fresh touches
too. Attraction too.

Not closed, and the distinction is the whole point: **levels**. The control says
a built-in level does leave a mark in this panel, barely, so the panel is
sensitive rather than blind - and a mark of 0.02 sd is not something to trade,
but it is something to measure a better observable against.

Open, and now the thing that matters: **the level definition**. This tested one
nomination - the lookback extreme - and `structures/drawing` runs fourteen
proposers, among them volume-profile nodes, range edges and displacement origins.
`statespace-ranging.md` refuted those as *nominations*, by asking whether price
holds there. It did not ask this question of them, and the harness takes any
price series and any price: pointing it at `drawing`'s own proposals is one
loop, and is the next thing worth doing.

What should not be done is re-running this panel on more **traded** instruments.
At 0.02 sd of power against 0.006 of observed effect, more FX buys precision on
a zero. More of the **control** is the opposite - that is the arm with 203 pairs
and findings on its floor.
