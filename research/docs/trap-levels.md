# After a trap, the new extreme is a worse level than a random price, and the midpoint only slightly better

Measured 2026-09-29 on the lab with [`traplevels.py`](../harness/traplevels.py): the lab's broker bars
at 15m and 1h for 15 FX pairs, XAU, XAG, BTC, ETH and SOL, with five Deriv random walks as the
control. Halves are by time.

**The control was widened to all twenty Volatility series on 2026-09-30 and the numbers below
are superseded in one respect** - the five-walk control's own spread was 4.7 points, wider than
the effects being read against it. With twenty it is 1.2, and the conclusions change: see
[the re-run](#re-run-2026-09-30-with-a-twentyfold-tighter-control-and-it-survives) at the
bottom. The *ranking* here survives; the reading of the midpoint as the best placement does not.

## The question

A **trap** (`structures/reactions.py`) is a break that failed: price closed 1.5 volatility units
through a level, then within six bars came back 0.5 on the original side. Today the level is kept as
it was, with its history intact and its price nudged only by the touch's origin
(`levels.Level.record`: "a trap is the level holding"). The trap's extreme, where the stops were
run, is not a level at all. The idea: once a trap occurs, label the newest minimum or maximum as the
level, or adjust the old one.

## How it was measured

The label is one that cannot flatter anyone: at a level's first retest within 96 bars, a symmetric
race of ±1 sigma from the level (for a support, up first counts as held). It reads 50% on a random
walk whatever the geometry, unlike the production outcome labels ([`skill.md`](skill.md)) - whose
null [`holdlabel.md`](holdlabel.md) measures at **55%**, all of it the ratcheting origin in
`reactions.py:1154`. That is why this study does not use them: a placement comparison read against
a 50% baseline on a 55% label would have credited five points to whichever candidate was measured
first.

**Levels** are 5-bar swing lows and highs (highs mirrored), and **traps** follow the production
thresholds. After each trap the candidates are:
- **new extreme:** the failed break's lowest low (for a support);
- **original level:** the level that was trapped;
- **adjusted:** halfway between the two;
- **placebo:** a random price in the same span, at least 0.3 sigma from all three.

Two further rows: fading the trap at the close that confirms it (a ±1 sigma race), and the retest,
from the other side, of a level that really broke (the flip).

## Results

Held at the first retest (15m / 1h); standard errors about 0.5 points for FX and 1-1.5 for metals
and crypto:

| | FX | metals | crypto | random walks |
| --- | --- | --- | --- | --- |
| **new extreme** | 52.8% / **49.2%** | 49.6% / **44.6%** | **47.4%** / **46.2%** | 48.5% / 50.4% |
| original level | 52.4% / 53.3% | 51.7% / 55.4% | 50.3% / 53.2% | 48.4% / 50.5% |
| **adjusted (midpoint)** | **53.5% / 53.5%** | **53.8% / 54.4%** | **54.7% / 55.3%** | 49.6% / 46.9% |
| placebo | 52.3% / 52.4% | 51.4% / 53.1% | 52.0% / 51.5% | 49.8% / 50.8% |
| fade the trap at confirmation | 49.0% / 48.6% | 50.7% / 49.9% | 51.1% / 49.9% | 48.5% / 51.1% |
| a real break's flip | 53.5% / 53.1% | 51.4% / 52.3% | 52.7% / 51.3% | 48.9% / 48.6% |

Traps are 18-24% of break attempts on real markets and 21% on the random walks. On real markets a
placebo level holds about 52% against 50% on the random walks; that is the general short-term
mean reversion measured in [`physics.md`](physics.md). Each candidate is therefore read against the
placebo, not against 50%.

- **The trap's extreme is a worse level than a random price.**
  - It holds at or below the placebo everywhere, and clearly below in metals and crypto at 1h
    (44.6% and 46.2% against 53.1% and 51.5%).
  - Price comes back to a swept low and takes it out again.
  - Labelling the extreme as the level would make the level set worse.
- **The midpoint is a little better than a random price in all six real-market cells**, by 1.1-3.8
  points. The random walks show nothing (-0.2 and -3.9). It is consistent, and small: about
  0.02-0.08 of a move per retest, against a 15m FX spread of about 0.46.
- **The original level after a trap is about the placebo** (+0.1 to +2.3 points).
- **The trap is not an entry.** Fading the failed break when it is confirmed wins 48.6-51.1% of
  symmetric races.
- **A real break's flip** holds about a point more than the placebo in FX. It is also tiny.

## Where between the level and the extreme: 14% to 86%

Asked for next: put the adjusted level at 80-86%. That is ambiguous about which end it is measured
from, so both readings were run with the fractions fixed before the run: 0.80 and 0.86 of the way from
the original level toward the extreme, and 0.14 and 0.20 (the same numbers measured from the
extreme). Held at the first retest, same race and placebo:

| 1h | original | 14% | 20% | 50% | 80% | 86% | extreme | placebo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FX | 53.3 | **54.7** | **54.6** | 53.5 | 51.7 | 50.9 | 49.2 | 51.6 |
| metals | 55.4 | **56.5** | **56.8** | 54.4 | 49.9 | 48.2 | 44.6 | 52.5 |
| crypto | 53.2 | 54.3 | 54.8 | 55.3 | 52.2 | 49.5 | 46.2 | 54.0 |
| random walks | 50.5 | 51.6 | 51.5 | 46.9 | 48.4 | 48.8 | 50.4 | 50.2 |

| 15m | original | 14% | 20% | 50% | 80% | 86% | extreme | placebo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FX | 52.4 | 52.2 | 52.9 | 53.5 | 52.8 | 52.9 | 52.8 | 51.7 |
| metals | 51.7 | 53.0 | 52.1 | 53.8 | 53.0 | 52.0 | 49.6 | 50.6 |
| crypto | 50.3 | 52.3 | 52.1 | 54.7 | 53.8 | 52.0 | 47.4 | 52.1 |
| random walks | 48.4 | 49.6 | 49.6 | 49.6 | 47.8 | 47.6 | 48.5 | 48.3 |

(percent held; standard errors about 0.5 for FX and 1.2-1.5 for metals and crypto)

- **80-86% toward the extreme: no.**
  - At 1h it is at or below the placebo in every market (metals 49.9% and 48.2% against 52.5%).
  - At 1h the hold rate falls steadily as the level moves toward the swept extreme (metals 55 → 57 →
    54 → 50 → 48 → 45).
  - At 15m it is about 1-2 points above the placebo, which almost any point in the span gets, and the
    midpoint does better.
- **80-86% back from the extreme, i.e. 14-20% past the original level: the best placement at 1h.**
  - FX 54.6-54.7% against 51.6%, metals 56.5-56.8% against 52.5%.
  - The random walks show +1.3 at the same placement, so the market's part is about +1.7 (FX) and +3
    (metals).
  - At 15m it is 0 to 2.4 points above the placebo, no better than the midpoint, and crypto at 1h
    barely clears the placebo.
- **Five placements x three markets x two intervals is thirty cells**, so a single 3-point cell is not
  strong evidence. The consistent part is the shape at 1h: close to the original level is best, and the
  swept extreme is worst.
- **It does not change the money.** The best cell is worth roughly 0.03-0.06 of a move per retest,
  below costs.

## What this settles

- **Do not relabel the level to the trap's extreme.**
- If a trapped level is moved at all, move it a little past the original, 14-20% of the way toward
  the extreme (80-86% back from it). That is the best of the placements tried at 1h, and the midpoint
  is the best at 15m. Near the extreme is the worst. It is a defensible change to how the level is
  drawn, and it will not change what trading it earns.
- A trap does not predict a reversal, so the trap label adds nothing as a trade trigger.

## Re-run 2026-09-30 with a twentyfold-tighter control, and it survives

The control above was five Volatility indices, and across the seven placements at 1h its
own hold rate ran **46.9% to 51.6%** - a 4.7 point spread on data with no structure in
it. The market effects being read off the same table were +1.7 (FX) and +3 (metals) after
subtracting it, so the noise floor was wider than the signal and no single cell could be
distinguished from it. That was the objection.

The lab holds **twenty** Volatility series at both 15m and 1h, not five - both the 2s and
the 1s families. All twenty belong to the one published family, and nothing else on the
venue does: [`twins.md`](twins.md) measures twelve of them as geometric Brownian motion at
the annualised sigma in their names, to within 0.5%, and [`deriving.md`](deriving.md)
derives from that. The other eight (5, 15, 30, 90 and their 1s twins) are the same
generator at sigmas nobody has checked, so they are included on the family's construction
rather than on a measurement - and the flat reading below is itself the check, since a
series that was not a driftless random walk would not land on 50%. Boom, Crash and Jump
stay excluded, each having a designed asymmetry or arrival. Same harness, same fractions,
same label; only the control changed.

*(`twins.md` also warns off `volatility_150_1s_index` for **tick** statistics, its price
grid being coarse against a tick. This study reads 15m and 1h bars, where a bar's sigma is
hundreds of grid steps, and the placement effect is differenced within each series.)*

**The control is now flat.** Across all seven placements: **48.9-50.1% at 1h** and
**48.8-50.1% at 15m** - a spread of 1.2 and 1.3 points against 4.7, on n = 8,500-16,300
per cell with standard errors of ±0.4-0.5.

Held at the first retest, as a **difference from that market's own placebo** (1h):

| 1h | original | 14% | 20% | 50% | 80% | 86% | extreme |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FX *(placebo 52.0)* | +1.3 | **+2.7** | +2.6 | +1.5 | -0.3 | -1.1 | **-2.8** |
| metals *(50.9)* | +4.5 | +5.6 | **+5.9** | +3.5 | -1.0 | -2.7 | **-6.3** |
| crypto *(53.0)* | +0.2 | +1.3 | +1.8 | +2.3 | -0.8 | -3.5 | **-6.8** |
| random walks *(49.3)* | +0.2 | +0.8 | +0.3 | -0.4 | +0.7 | +0.7 | +0.3 |

| 15m | original | 14% | 20% | 50% | 80% | 86% | extreme |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FX *(placebo 51.7)* | +0.7 | +0.5 | +1.2 | **+1.8** | +1.1 | +1.2 | +1.1 |
| metals *(50.6)* | +1.1 | +2.4 | +1.5 | **+3.2** | +2.4 | +1.4 | -1.0 |
| crypto *(52.1)* | -1.8 | +0.2 | 0.0 | **+2.6** | +1.7 | -0.1 | **-4.7** |
| random walks *(48.9)* | +0.5 | +0.9 | +0.7 | +0.3 | -0.1 | +0.1 | +1.2 |

### What the tight control changes

* **The positive finding survives, and the objection to it does not.** FX at 14% is +2.7
  over its placebo where the walks give +0.8, so about +1.9 of market against a difference
  standard error near 0.7 - roughly four standard errors. Metals at 20% is +5.9 against
  +0.3, about three. These are no longer inside the noise floor, because the noise floor
  moved.
* **The negative finding is now the strongest result in the study.** At 1h the extreme
  sits **6.3 points below placebo in metals and 6.8 in crypto**, against a control that is
  flat there (+0.3), and the decline is monotone across the whole span: metals 55.4 → 56.5
  → 56.8 → 54.4 → 49.9 → 48.2 → 44.6. Price returns to a swept low and takes it out again.
* **The timeframe disagreement is real and is not noise.** 14-20% is best at 1h in FX and
  metals; the **midpoint** is best at 15m in all three markets, and 14% is worth +0.5 to
  +2.4 there. A genuine geometric property of a trap should not relocate between
  intervals, so the optimum is **not identified** - what is identified is that somewhere
  between the original level and the midpoint beats both the original and the extreme.
* **Crypto never clears on its own.** +1.3 at 14% against a ±1.7 difference error at 1h.
  The 1h result is carried by FX and metals.

### What this means for the recommendation

The earlier conclusion - *if a trapped level is moved at all, move it 14-20% toward the
extreme* - **holds at 1h and overstates its precision.** The defensible statement is:

* **never relabel to the extreme**, which is worse than a random price by 6-7 points and
  is the one thing this study establishes beyond argument;
* **a shift between roughly 14% and 50% is better than leaving it**, by 2-6 points
  depending on market and interval;
* **the exact fraction is not identified**, differing between 15m and 1h by more than
  their errors, so any single number is a choice rather than a measurement;
* and **it still does not change the money** - 0.03-0.06 of a move per retest, below
  costs, exactly as first reported.

One correction to the record. The noise-floor objection was right about the five-series
control and wrong as a conclusion: it led to "keep the level at the original price", and
with the control tightened the shift is real. The lesson is the cheaper one - when a
control's own spread is wider than the effect, widen the control before drawing the
conclusion, because either answer was available from that table.
