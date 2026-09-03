# Bjorgum key levels, measured

Source of the idea: **Bjorgum Key Levels**, by Bjorgum on TradingView —
https://www.tradingview.com/script/CapG3ivf-Bjorgum-Key-Levels/ — reached here
through the Pine-to-Python port in `dq/terminal/sage`. Ported to
[harness/bjorgum.py](harness/bjorgum.py) to be *tested*, not traded; the model
over its features is [harness/bjorgum_model.py](harness/bjorgum_model.py).

Nothing here is in production.

## Why it was looked at

A human reading gold's 4h chart named 4324.26 and 4333.94 as the levels. The
desk bought at 4385.94 with a 3.7-point stop, which looked like a level-making
failure. It was not:

* **we had the level.** Gold 4h: **4333.5**, within 0.44 of the human's price.
* **the trade was a different idea entirely** — `level 4387.27, interval 1m`.
* **the slow level was drowned.** Over 48 hours gold published 96 level rows on
  1m and **one** on 4h.

The same held for usdcad, where the human named 1.39049 and 1.39329: our 30m
carried 1.39063 and our 1h carried 1.39343, each **1.4 pips** away, and 5m's
range topped out at 1.39329 exactly. Two instruments, four human levels, all
found. **The gap is selection, not detection**, which is what
[timeframes.md](timeframes.md) now sizes.

## What the port takes

1. **Role flipping.** A zone remembers which side price was on and counts the
   changes; original role against current role gives `flipped`.
2. **Separate-visit counting.** A run of consecutive bars inside a zone counts
   **once** — price sitting in a level for nine bars is one test of it, not
   nine.
3. **ATR-scaled bands with a percent ceiling, and merging.** Overlapping
   same-side zones fold together: one level price found twice is not two
   levels.

## Levels mean something, and this is the cleanest statement of it

A zone's base break rate, same construction, same code:

| | 15m | 1h | 4h |
| --- | ---: | ---: | ---: |
| real instruments | **33.9%** | 37.7% | 37.3% |
| synthetic control | 81.3% | 85.0% | 80.5% |

Real market zones hold roughly two thirds of the time; on a generated process
with no structure to find, the same zones hold a fifth. That gap is the whole
argument for trading levels at all, and it had not previously been stated in
one number.

## Freshness predicts a **break**, not a hold

Break rate by which visit this is, against each family's own base:

| visit | 15m | 1h | 4h | control (4h) |
| --- | ---: | ---: | ---: | ---: |
| **first — fresh** | **+27.4** | **+18.6** | **+28.1** | +6.2 |
| second | +8.8 | +11.8 | −4.0 | −9.2 |
| third to fifth | −1.6 | −7.2 | **−12.0** | −1.6 |
| sixth or later | −5.0 | −8.6 | −10.5 | +3.0 |

Consistent at every timeframe measured and far outside the control. At 4h an
untested zone fails its first test **65.4%** of the time against **25.3%** for
one tested three to five times — a forty-point spread.

**This contradicts the human's reasoning, and usefully.** Two claims were
bundled together: *"it proved itself — price dipped and bounced"* and *"the
zone was fresh"*. The first is doing all the work. The second points the other
way at every timeframe, and a strategy written from the description as given
would have taken the wrong half.

## Role flipping is a 15m effect and does not survive

| | 15m | 1h | 4h |
| --- | ---: | ---: | ---: |
| never flipped | +23.6 | +12.3 | +5.0 |
| flipped | −5.5 | −4.8 | −2.5 |
| *control, never flipped* | +0.9 | **+5.6** | −0.0 |

Convincing at 15m, where the control shows about one point against the real
market's twenty-four. At 1h the control shows +5.6 of its own, which is half
the real effect, and at 4h the real effect is +5.0 and the control is zero on
481 visits. **Reported here as unproven above 15m.** It was called "the
strongest single discriminator" on the 15m numbers alone, before the slower
timeframes were run, and that was too early.

## A model over the features, and what actually carries it

Predict-then-update in time order, so every score is out of sample. 15m:

| feature alone | real market | control |
| --- | ---: | ---: |
| visit number | 0.5474 | 0.4468 |
| fresh | 0.5530 | 0.4695 |
| flipped | 0.5250 | 0.4673 |
| crossings | 0.6508 | 0.4707 |
| **zone width** | **0.7602** | 0.5417 |
| age | 0.4646 | 0.4483 |
| **all together** | **0.7838** | 0.5794 |

**Zone width dominates everything bjorgum is known for.** Alone it scores
0.7602, above `structures/breaking.py` with all five of its own features
(0.6408), and the six other zone features together add only 0.024 on top of it.

**Two reasons not to celebrate yet.** Width is `(top - bottom) / mid` derived
from ATR at the pivot, so it is substantially **a volatility measure** — and
volatility predicting a break may be the same fact as
[slopes.md](slopes.md) finding slope predicts movement, wearing different
clothes. And a wide zone is mechanically easier to be inside, which could bias
the visit labelling that produces the label. Neither is checked.

## Width is not volatility — but the test has a hole in it

Chased on 2026-09-03 with [harness/width.py](harness/width.py), 1,103 visits at
15m. Raw AUC against a break, where below 0.5 means the feature predicts a
**hold**:

| predictor | real market | control |
| --- | ---: | ---: |
| **zone width** | **0.1863** | 0.5262 |
| volatility now | 0.4591 | 0.5777 |
| volatility then | 0.4749 | 0.5749 |
| width / volatility now | 0.2124 | 0.4386 |

**Wide zones hold** — 0.1863 is 0.8137 read the other way, and the earlier
"0.7602" was the fitted model having learned the sign. Volatility on its own is
0.4591, which is nothing.

And it survives conditioning. Break rate by width *within* volatility bands:

| volatility now | n | narrow | wide | gap |
| --- | ---: | ---: | ---: | ---: |
| lowest quarter | 276 | 40.3% | 14.0% | **−26.3** |
| second | 275 | 72.8% | 10.9% | **−61.9** |
| third | 276 | 55.2% | 5.3% | **−50.0** |
| highest | 276 | 40.8% | 11.2% | **−29.7** |

Every band, and the control gives −16.4 / +0.9 / +0.7 / −2.9. The correlation
tells the same story from another side: in the control, width and volatility
correlate **+0.832** — on a generated process the band *is* the volatility and
nothing else. On real instruments it is **+0.238**, so width carries something
volatility does not.

**The hole, and it may be the whole finding.** A visit is scored as a break
when price closes beyond the *far edge of the zone* — and a wider zone has a
further far edge. Wide zones may hold for the same reason a wider net catches
more: geometry, not structure. That is exactly the shape of the sub-minute
tautology in [failing.md](failing.md), where a touch resolving in seconds is a
rejection by definition of the label.

### Run, and the answer is "half of it was geometry"

[harness/atrbreak.py](harness/atrbreak.py) takes the width out of **both** ends
of the label: a touch is price within 0.25x ATR of the level, a break is a close
1.0x ATR beyond it, identical for every zone whatever band it would have had.
779 visits at 15m, base break rate 34.5%:

| width band | n | break | vs base |
| --- | ---: | ---: | ---: |
| narrowest quarter | 175 | 50.3% | **+15.8** |
| second | 182 | 42.3% | +7.8 |
| third | 226 | 23.9% | -10.6 |
| widest | 196 | 25.5% | -9.0 |
| *first visit (fresh)* | 118 | **60.2%** | **+25.6** |

Width's AUC falls from **0.1863 to 0.3849** - 0.814 to 0.615 read in the hold
direction. **So about half the effect was the label seeing the width**, exactly
as suspected, and about half is real: a 25-point spread survives, roughly
monotone, where the control gives an AUC of **0.4988** and no ordering at all
(+0.6 / +3.9 / -8.2 / +3.2).

**Freshness is untouched** - 60.2% against a 34.5% base, +25.6, against +6.1 in
the control. It never depended on the band.

Standing position: freshness is the solid finding, width is real at half the
size first reported, and flipping is 15m-only. The suspicion was worth acting
on - it halved a number that would otherwise have entered a gate at twice its
true strength.

## The bandit question, answered against this repository's own test

[bandits.md](bandits.md): *if you would have learned the outcome anyway,
whatever you chose, it is not a bandit problem.* Every zone visit resolves on
the stored bars whether or not anything traded it, so every arm reports on
every decision. That is full information; exponential weights or plain
supervised learning is the right family, and a bandit would pay exploration for
a counterfactual already in hand.

The bandit shape survives in exactly one place and this cannot settle it:
**whether a resting order at a zone actually fills, and at what spread.** Bars
say where price went, not what fill you would have been given. That is the
`Shape.PENDING` half of the decision surface and it is only ever observed by
trading.

## What to do with it

1. **Do not use freshness as a hold signal.** It is a break signal, at every
   timeframe measured, and the intuition it came from is backwards.
2. **"Proven" is the half worth keeping** — three to five prior visits is the
   best cell on the book at 4h, at 25.3% against a 37.3% base.
3. ~~**Chase zone width against `vol_bps`.**~~ Done, and it is *not*
   volatility: it survives conditioning inside every volatility band, and the
   control shows width and volatility are the same thing there (+0.832) while
   real instruments show +0.238. But the label is width-dependent, so re-run it
   with a break defined in ATR from the level before believing any of it.
4. **Flip needs 4h data it does not have.** Not refuted, not established.
