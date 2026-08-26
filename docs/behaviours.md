# What price does at a level, and which of it we model

A catalogue of the behaviours practitioners describe at key levels, checked
against what the code actually represents. Written because three of the common
five are already modelled under different names, and the three that are not
suggest models worth building rather than features worth bolting on.

Source of the descriptions: the practitioner vocabulary collected at
[priceaction.com](https://priceaction.com/). The mapping, the gaps and the
proposals below are ours, and none of the proposals has been tested.

## The honest constraint, stated once

Several of these behaviours are **order-flow** claims. "Aggressive orders are
absorbed by opposing limit orders" is a statement about a book we cannot see:
this project has mid, bid, ask and OHLC bars, and no depth, no trade prints, and
no reliable volume on the CFD and FX feeds where tick count stands in for size.

That does not make them unusable. It means every one of them can only be
approached as a **proxy inferred from price geometry**, and a proxy needs to be
graded rather than believed. The outcome machinery in
[journal.md](journal.md) already grades things exactly this way, so the test is
available whenever a proxy is written.

Where a proposal below needs data we do not have, it says so.

## Already modelled, under our own names

| behaviour | what we call it | where |
|---|---|---|
| Clean rejection / bounce | `REJECT`, with the wick kept separately from the origin | [levels.md](levels.md) §5b, §7 |
| Liquidity sweep / stop raid | `TRAP` - a break taken back inside `TRAP_WINDOW` | [levels.md](levels.md) §7b |
| Back check of a broken level | `BACKCHECK` | [levels.md](levels.md) §7c |

Two of these are worth spelling out, because the correspondence is exact and
was arrived at independently.

**The rejection wick is already separated from the level.** `observe_wick` keeps
the extreme apart from the origin precisely because the long wick in a pin bar
is liquidity taken a fraction beyond the level at a price nobody traded around,
while the origin is where the leg in ended. Drawing the level at the wick is the
mistake the split exists to avoid.

**The sweep is not only detected, its depth is recorded.** `excursion_vol` is
documented as "what a breakout entry would have been offered before it was taken
back", which is the stop-raid description restated as a measurement. That number
is already in every journalled outcome and nothing yet reads it.

## Not modelled, and worth it

### 1. Absorption, and the label it is currently hiding under

**The behaviour.** Price presses against the level repeatedly without bouncing
or breaking, contacts coming closer together and each excursion shorter, until
the level gives way with unusual force.

**What we do now.** `CHOP`, which means "nothing happened" and exists so the
model is shown non-events. Absorption is emphatically not a non-event - it is
the state that most reliably precedes an expansion - and merging the two teaches
the model that a build-up is noise.

**The model.** Absorption is a *sequence* property, and every touch is currently
scored alone. The quantities are already recorded:

- contacts at one level within a window - the count is in the tracker;
- the trend in `excursion_vol` across those contacts, which should be falling;
- the trend in the gap between them, which should be shortening.

A level whose last k touches show excursion decaying and contacts accelerating is
in build-up. That is three regressions over numbers we already have, and it
produces a feature the FM can cross with `strength` and `regime`.

**Why this one is first.** It is the only proposal here that costs no new data,
no new dependency and no new collection, and it plausibly separates the single
most valuable state from the one labelled "nothing".

**A caution that is specific to us.** A grind produces *many touches at one
level in a short time*, which is exactly the shape of the double-counting bug
that produced 171 touches on a 3m gold level. Before absorption can be measured,
the counting has to be trustworthy, or the feature will fire hardest wherever
the bug is worst. See [handoff.md](handoff.md), "Why the channel is silent".

### 2. Compression on approach

**The behaviour.** Tighter, overlapping candles beneath the level - the opposing
side exhausting before a momentum push.

**What we do now.** `approach_vol` is the *speed* of arrival. Compression is
about the **contraction of range** on the way in, which is a different quantity:
price can arrive slowly and widely, or slowly and tightly, and those are opposite
setups.

**The model.** A ratio, in the units everything else here uses - recent true
range over that timeframe's typical range, measured across the last few bars
before contact. Below one is compressed. It is scale-free by construction, so it
travels across instruments the way the other features do, and it is one more
number in `Features`.

**Falsifiable immediately.** If compression carries information, touches with a
low ratio should show larger `push_vol` and fewer `CHOP` outcomes. The journal
answers that without any new collection.

### 3. The magnet effect, which is a claim we can actually test

**The behaviour.** Price is drawn toward round numbers and heavy volume nodes.

**What we do now.** [timing.py](../till_infinity/structures/timing.py) answers
*when* price will reach a level **given that it does**, as quantiles over a
diffusion where time goes as the square of distance. It says nothing about
whether arrival is more likely than drift alone implies.

**The model, and it is a test before it is a feature.** The diffusion baseline
is already written down, so the magnet claim is directly falsifiable: compare
the realised arrival rate within a horizon against what the square-root law
predicts for that distance. If levels attract, arrivals beat the baseline; if
they do not, this whole idea dies cheaply and correctly.

Only if it survives is there a feature - an attraction term per level, probably
strongest for round numbers, which is the one variant testable without volume
data we do not have.

## Two structural ideas these suggest

### The touch is a state machine, and that is where an HMM belongs

Read as a list, the five behaviours are really **states in one lifecycle**:
approach → contact → (absorb | reject | sweep | break) → resolution. We model
the endpoint and ignore the path.

This is the honest home for the hidden Markov model discussed in
[structures.md](structures.md) - not as a regime detector competing with BOCPD,
but as a model of the *touch* itself, where the states are few, named in advance,
and interpretable. The same look-ahead caution applies and applies harder: only
the **filtered** estimate is admissible, because a smoothed one labels the
approach using the resolution that followed it, which is the outcome we are
trying to predict.

### Touch arrivals are self-exciting, which has a standard model

"Contacts coming closer together" is the definition of a self-exciting point
process. A Hawkes process over touch arrivals at a level would give the grind a
single fitted parameter - the excitation decay - rather than a hand-rolled
trend over the last k gaps.

Filed as an idea rather than a proposal. It needs the arrival series to be
trustworthy first, which returns to the counting problem above, and the
hand-rolled version in §1 should be tried before a fitted one is justified.

## Order of work

1. **Absorption**, once touch counting is trusted. No new data, and it separates
   build-up from "nothing happened".
2. **Compression on approach.** One ratio, one feature, immediately gradeable.
3. **The magnet test.** Cheap, and the answer is interesting either way - a null
   result removes a piece of folklore from consideration.
4. **Touch-lifecycle HMM.** Only after 1 and 2 say the path carries information
   the endpoint does not.
5. **Hawkes.** Only if the hand-rolled excitation trend earns it.

Everything above is unbuilt and ungraded. The reason to write it down is that
the outcome machinery can settle each one, and an idea that can be settled is
worth more than an idea that sounds right.
