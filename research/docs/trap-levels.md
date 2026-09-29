# After a trap, the new extreme is a worse level than a random price, and the midpoint only slightly better

Measured 2026-09-29 on the lab with [`traplevels.py`](../harness/traplevels.py): the lab's broker bars
at 15m and 1h for 15 FX pairs, XAU, XAG, BTC, ETH and SOL, with five Deriv random walks as the
control. Halves are by time.

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
walk whatever the geometry, unlike the production outcome labels ([`skill.md`](skill.md)).

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
  - At 15m it is about the placebo, and crypto at 1h barely clears it.
- **Five placements x three markets x two intervals is thirty cells**, so a single 3-point cell is not
  strong evidence. The consistent part is the shape: close to the original level is best, the swept
  extreme is worst.
- **It does not change the money.** The best cell is worth roughly 0.03-0.06 of a move per retest,
  below costs.

## What this settles

- **Do not relabel the level to the trap's extreme.**
- If a trapped level is moved at all, move it a little past the original, 14-20% of the way toward
  the extreme (80-86% back from it). That is the best of the placements tried at 1h, and the midpoint
  is the best at 15m. Near the extreme is the worst. It is a defensible change to how the level is drawn, and it will not
  change what trading it earns.
- A trap does not predict a reversal, so the trap label adds nothing as a trade trigger.
