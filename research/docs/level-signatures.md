# A touch carries nothing, and the one observable that looked like a signal is a tautology

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

Deriv's range-break processes are real markets whose **generator has a range
that breaks**, so a level exists there by construction, and they were added as
the positive control: a panel that cannot see a touch at a level someone built
is not evidence about levels.

That control did light up - family-wise p **0.017** on first touches, carried by
`overshoot` at 0.4699, meaning the touching bar poked through a real boundary by
less than it poked through a matched price. It is a tautology. To overshoot a
100-bar extreme, price must set a **new** 100-bar extreme; a placebo inside the
recent range faces no such barrier. The block-shuffled arm proves it, because it
reads the same thing at **p 0.005 over 2,784 pairs** with no level structure left
in the series at all.

Drop that one observable - named by the shuffled arm, not by taste - and the
control's 0.017 becomes **0.781**. Every arm is then null, and the answer to the
question is that a touch carries nothing: not on traded instruments, and not
where the level is written into the generator.

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
| matched pairs | 2,719 | 793 |
| real-level touches | 10,100 | 3,013 |
| widest `\|AUC - 0.5\|` | **0.006** | 0.011 |
| marginal passes of 19 | 1 | 0 |
| family-wise p, all 19 | **0.342** | 0.763 |
| family-wise p, 18 non-mechanical | **0.783** | 0.741 |
| first touch only, 18 non-mechanical | 0.783 | 0.868 |
| visits: real vs placebo | 5.93 vs 5.95, p 0.646 | 6.29 vs 6.33, p 0.698 |

Twelve feeds, anchors spaced a full horizon apart, fifty thousand bars each. The
one traded pass is `retrace3` at 0.5038, p 0.032 - one in nineteen, and the
family-wise p says so.

**First touch only** is its own arm, with its own power sweep, because one event
a pair is a quarter of the sample and a null without power is not a result. On
traded: 2,719 fresh touches, family-wise p 0.783 over the eighteen. It was called
the arm that makes sense, and it is - a level tested nine times is not what the
question means - and it is also the arm where the tautology surfaced, which is
its own argument for keeping the shuffled twin at the same sample size.

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

## The one observable that separated, and why it is not a finding

| arm | pairs | family-wise p, all 19 | `overshoot` | after dropping it |
| --- | ---: | ---: | ---: | ---: |
| control, first touch | 465 | **0.017** | 0.4699, p 0.012 | **0.781** |
| control, every touch | 465 | 0.586 | 0.4980, p 0.818 | 0.643 |
| traded, first touch | 2,719 | 0.858 | - | 0.783 |
| traded, every touch | 2,719 | 0.342 | 0.4957, p 0.085 | - |
| **shuffled traded** | 2,784 | **0.007** | **0.4920, p 0.005** | - |

The last row is the whole argument. A block-shuffled series has no levels - its
blocks are fifty bars long and re-levelled in log space - and `overshoot` still
separates real extremes from matched placebos there, at a p the control never
reached, with five times the pairs. So the effect belongs to the **definition of
an extreme**, not to a level.

The harness now learns that set rather than being told it: the highest-powered
shuffled arm names every observable that separates on shuffled bars, and each
arm prints a second family-wise p with those dropped. This is why traded runs
first.

## The positive control, which is the only reason any of this is interpretable

At 465 pairs, with a horizon of a hundred bars so that a fresh touch is a level
formed in the last hundred and tested within the next hundred, the control's
marginal readings were all in the direction a real boundary predicts: less
activity after, less retrace, less overshoot through, more drift through a range
about to break. It was the tautology above, and nothing else of it survived.

This control is still the asset to keep, and its value does not depend on it
finding anything. Any new level observable goes through it **before** it is
believed on traded data - the same rule that says an FX screen missing currency
triangles is broken whatever else it reports - and it now also supplies, through
its shuffled twin, the list of observables that separate for definitional
reasons.

## What this closes, and the one door it leaves open

Closed **for these nineteen observables**: a touch at a 100-bar extreme on 1h is
indistinguishable from a touch at a matched arbitrary price, in approach, in the
touching bar, and in what follows - including every candle-orderflow reading
available without L2, and including the wick-volume combination. Fresh touches
too. Attraction too.

The control says the same, which is the sentence that makes it a result rather
than a failure: where the level is in the generator, a touch at it still looks
like a touch anywhere else, once the one definitional observable is removed.

Open, and now the thing that matters: **the level definition**. This tested one
nomination - the lookback extreme - and `structures/drawing` runs fourteen
proposers, among them volume-profile nodes, range edges and displacement origins.
`statespace-ranging.md` refuted those as *nominations*, by asking whether price
holds there. It did not ask this question of them, and the harness takes any
price series and any price: pointing it at `drawing`'s own proposals is one
loop, and is the next thing worth doing.

What should not be done is re-running this panel on anything. At 0.02 sd of
power against 0.006 of observed effect, and with the control's only reading
accounted for, more data buys precision on a zero.
