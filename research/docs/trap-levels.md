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

## What this settles

- **Do not relabel the level to the trap's extreme.**
- Moving a trapped level toward the midpoint of the level and the extreme matches the data slightly
  better than leaving it. It is a defensible change to how the level is drawn, and it will not
  change what trading it earns.
- A trap does not predict a reversal, so the trap label adds nothing as a trade trigger.
