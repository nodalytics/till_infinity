# The magnet effect, tested

Practitioners say key levels and round numbers **pull** price toward them.
[behaviours.md](behaviours.md) §3 filed that as the one claim on the list that
could be settled cheaply, because the baseline it has to beat is already
written down: [timing.py](../till_infinity/structures/timing.py) says how long a
driftless walk takes to cover a distance, and therefore how often it covers it
inside a horizon. Attraction means arrivals beat that. No attraction means they
do not.

This is the run. **They do not.** Across six instruments and 22,219 evaluation
bars, price reaches a level within twenty bars slightly *less* often than it
reaches an arbitrary price the same distance away - 44.9% against 49.5% - and
round numbers behave the same way. Hold the day fixed and the gap shrinks to
nine-tenths of a point and stops being distinguishable from zero, which is the
honest form of the answer: **not attraction, and not repulsion either.**

Nothing here supports an attraction term, and the proposal in behaviours.md §3
should be closed rather than built.

The rest of this documents how, because a null is only worth anything if the
design could have found the effect.

## 1. What the claim has to beat, and why a placebo decides it

The diffusion baseline alone is not a sufficient control, and leaning on it
would have produced a confident wrong answer. Markets are not Brownian, so a
gap between realised arrivals and the square-root law measures every way in
which they are not - fat tails, clustering, trend - and attributes all of it to
levels.

The control that actually separates the claim is a **placebo**: an arbitrary
price the same distance away with no level at it. If levels attract, a level is
reached more often than a placebo at that distance. If they do not, the two
match and everything else in the picture is diffusion. Everything the baseline
gets wrong, it gets wrong for both.

Round numbers are tested separately, because they are the variant that needs no
volume data and because they might behave differently from swing levels.

## 2. Reaching a price is reaching a distance

The reduction that shapes the whole test, and it is worth stating before the
numbers because it says what could and could not have been found.

"Did price touch P above" is exactly "did the highest high in the horizon reach
P", which is exactly "was the largest upward excursion at least the distance to
P". So **the hit is a deterministic function of the day and the distance** -
there is nothing about the target in it. Two targets the same distance away on
the same day, on the same side, are hit or missed together, always.

An attraction effect therefore cannot show up as "this price was special". It
can only show up one way: **on days when a level sits at distance d, the
excursion distribution is shifted so that covering d is more likely than on
days when nothing sits there.** That is a real, testable claim, it is the
honest translation of "levels pull price", and it is what is measured below.

It also means the comparison is necessarily *between days*, so which days each
target population is drawn from is not a detail - it is the only thing that can
move the answer. §5 looks at it directly.

## 3. The measurement

Daily bars from `.data/prices/prices.db`, six instruments, as the **consensus**
median across every venue that reported the bar, with the engine's own
three-venue quorum - the series it forms levels on rather than one venue's
opinion of it.

| instrument | venue-bars | consensus bars |
|---|---|---|
| btc | 22,842 | 4,343 |
| eurusd | 29,945 | 4,985 |
| gbpusd | 30,915 | 5,001 |
| gold | 29,549 | 4,952 |
| spx500 | 21,800 | 2,545 |
| us100 | 20,898 | 2,313 |

Once the warm-up and the trailing horizon are removed that leaves **22,219
evaluation bars**, spanning 2008 to 2026 on gold and the FX pairs, 2015 on BTC
and 2016 on the indices - several regimes each rather than one market.

The production [engine](../till_infinity/structures/engine.py) is replayed bar
by bar over each history. At every bar, once volatility is warm and 300 bars
have passed:

- **Levels** are whatever `engine.levels(feed, "1d")` holds - formed by the
  ordinary path from `pips.as_of` confirmed swings, merged across re-formings,
  pruned. Distance is `Level.distance_vol` against the bar's close. Anything
  closer than 0.5v, further than 8v, or inside its own zone is skipped.
- **Placebos** are a grid of distances from 0.5v to 8v in 0.25v steps, both
  sides, kept only when at least 1.0v - the clustering tolerance - from every
  level, every confirmed swing in the window, and every round number. A price
  with nothing on it.
- **Round numbers** are the decimal grid whose spacing is at least 2.5v, chosen
  from current price and current volatility so that "round" adapts from 0.01 on
  EURUSD to 10,000 on late BTC without being told which is which. Finer than
  that and every price is on the grid, so roundness would stop meaning
  anything and no placebo could be placed between two of them.
- **The outcome** is whether the highs and lows of the next twenty consensus
  bars reached that price.

74% of evaluation bars carry at least one level in the band, a median of two
and never more than six - which is the density `MAX_LEVELS` and the pruner were
tuned for, and the reason the level counts below are in the thousands rather
than the hundreds of thousands the placebo grid produces.

**Point-in-time correctness is the engine's, not a reimplementation of it.**
Levels come out of `engine.levels` after the bar has been fed and before any
later bar exists, so the `as_of` guard that [levels.md](levels.md) §2 exists to
protect is the one doing the work. The forward test never begins earlier than
the bar after the one it is measured from.

Placebos are matched to levels on **distance bucket and side** before anything
is compared. Levels are not spread uniformly over distance and the placebo grid
is, so an unweighted difference would mostly measure where levels happen to
sit.

Intervals are wide because the counts are not independent: horizons overlap and
several targets share a day. Every interval quoted is a **block bootstrap**
over blocks of forty consecutive evaluation bars per instrument, which keeps
that dependence inside one resampling unit. A binomial interval on 32,181 rows
would have been fiction.

**Two deviations from the engine's defaults**, both forced and both explained
in §8: the quorum median is computed outside the engine and fed in as a single
row per bar, so that the volatility estimate is per bar rather than per venue
row; and the touch tracker's horizon is raised from an hour to twenty days, so
that touches on daily bars can resolve at all. Nothing in the repository was
changed - the run lives entirely in a scratch script driving the ordinary
`Engine`.

## 4. The result

**Swing levels**, 32,181 targets against 259,350 placebos:

| distance | n | level | placebo | difference | diffusion, as written |
|---|---|---|---|---|---|
| 0.5-1v | 409 | 0.892 | 0.902 | −0.010 | 0.853 |
| 1-2v | 3,749 | 0.770 | 0.812 | −0.042 | 0.735 |
| 2-3v | 4,087 | 0.631 | 0.687 | −0.056 | 0.577 |
| 3-4v | 4,179 | 0.524 | 0.570 | −0.046 | 0.436 |
| 4-5v | 4,233 | 0.413 | 0.455 | −0.042 | 0.316 |
| 5-6v | 3,840 | 0.321 | 0.371 | −0.050 | 0.220 |
| 6-8v | 8,477 | 0.210 | 0.257 | −0.047 | 0.121 |
| **all** | **32,181** | **0.449** | **0.495** | **−0.046** | 0.376 |

95% block bootstrap on the difference: **[−0.073, −0.027]**.

**Round numbers**, 68,161 targets against the same placebos:

| distance | n | round | placebo | difference | diffusion, as written |
|---|---|---|---|---|---|
| 0.5-1v | 3,448 | 0.885 | 0.908 | −0.023 | 0.867 |
| 1-2v | 8,024 | 0.779 | 0.814 | −0.035 | 0.738 |
| 2-3v | 8,012 | 0.652 | 0.688 | −0.036 | 0.577 |
| 3-4v | 7,833 | 0.536 | 0.569 | −0.034 | 0.435 |
| 4-5v | 7,955 | 0.425 | 0.453 | −0.028 | 0.315 |
| 5-6v | 8,012 | 0.332 | 0.370 | −0.038 | 0.219 |
| 6-8v | 18,047 | 0.226 | 0.257 | −0.031 | 0.121 |
| **all** | **68,161** | **0.478** | **0.510** | **−0.032** | 0.396 |

95% block bootstrap: **[−0.049, −0.018]**.

**The sign is negative at every distance, in both tests.** The claim needed it
positive. There is no distance at which a level or a round number is reached
more often than an arbitrary price beside it, and the effect the folklore
describes would have to be somewhere in this range to be worth a feature.

## 5. The negative is the day mix, not repulsion

Reading −4.6 points as *repulsion* would be the same mistake in the other
direction, and §2 says exactly where to look instead: the days each population
is drawn from.

Median excursion over the twenty bars, measured on the days each target
existed:

| distance | levels | how far price went | placebos | how far price went | ratio |
|---|---|---|---|---|---|
| 0.5-1v | 767 | 3.35v | 14,046 | 4.01v | 0.83 |
| 1-2v | 4,324 | 3.52v | 27,914 | 4.06v | 0.87 |
| 2-3v | 4,686 | 3.45v | 29,099 | 4.09v | 0.84 |
| 3-4v | 4,726 | 3.61v | 30,919 | 4.10v | 0.88 |
| 4-5v | 4,820 | 3.58v | 32,263 | 3.97v | 0.90 |
| 5-6v | 4,381 | 3.61v | 33,629 | 4.00v | 0.90 |
| 6-8v | 8,477 | 3.74v | 91,480 | 4.08v | 0.92 |

**A level exists on days when price subsequently travels eight to seventeen
per cent less far**, in volatility units, at every distance. A placebo, by
construction, requires the neighbourhood to be *empty* - of levels, of swings,
of round numbers - and that emptiness is itself a fact about the market, not a
neutral baseline. Since the hit is a step function of the excursion, a shift
that size is more than enough to produce the whole deficit.

So the honest reading of the negative is **selection, not repulsion**, and the
finding is a null rather than a reversal.

### The control that removes the day entirely

A placebo cannot sit at the same distance on the same side as a level - it is
excluded for being too close to one, which is what makes it a placebo. The
opposite side at the same distance is available, and it holds the day, and
therefore the day's volatility, completely fixed. What is left is the up/down
asymmetry, measured from placebo pairs alone and corrected for.

| | pairs | target | mirror placebo | difference | 95% |
|---|---|---|---|---|---|
| levels | 4,558 | 0.389 | 0.398 | **−0.009** | [−0.062, +0.038] |
| round numbers | 12,261 | 0.480 | 0.501 | **−0.021** | [−0.044, −0.001] |

Placebos run 0.562 up against 0.478 down over 36,633 pairs, and both target
populations are 50% above price, so the skew correction is negligible.

**With the day held fixed the level effect is nine-tenths of a point and
indistinguishable from zero.** That is the cleanest statement this design can
make, and it is a two-sided one: the interval rules out attraction above about
four points as firmly as it rules out repulsion below six. Round numbers stay
slightly negative and only just clear zero.

**What the mirror cannot separate**, and it should be said: the side with a
level at distance d is often the side where the recent range ends, and the
other side at the same distance may be interior to it. So the mirror
under-states nothing but may over-state the deficit for a reason that has
nothing to do with attraction - which only reinforces the null, since the
deficit is already negligible.

## 6. Where an effect would most plausibly have hidden, and did not

The obvious place is level strength - a price that has turned price back a
dozen times is what the folklore is loudest about. Splitting by effective
touches, on the same within-day control:

| level strength | pairs | level | mirror placebo | difference | 95% |
|---|---|---|---|---|---|
| under 1 effective touch | 1,105 | 0.399 | 0.401 | −0.002 | [−0.077, +0.081] |
| 1 to 3 touches | 1,655 | 0.431 | 0.435 | −0.004 | [−0.086, +0.079] |
| 3 or more touches | 1,798 | 0.344 | 0.363 | −0.019 | [−0.082, +0.045] |

All three straddle zero and the ordering runs the wrong way - the most-tested
levels come out furthest from attraction, not closest to it. On roughly 1,500
pairs each these intervals are wide enough that the split is better read as
"nothing here" than as evidence of a gradient.

## 7. How many cuts were tried

Stated because it is what makes any survivor interpretable, and there was no
survivor.

Two pre-specified tests - swing levels and round numbers, each against the
placebo and each with the within-day mirror - then **fourteen named cuts**,
**twelve per-instrument breakdowns**, **seven distance bands per test**, and
**three level-strength bands**. The named cuts:

| cut | n | target | placebo | difference | 95% |
|---|---|---|---|---|---|
| 1. all levels | 32,181 | 0.449 | 0.495 | −0.046 | [−0.072, −0.027] |
| 2. ≥1 effective touch | 25,332 | 0.443 | 0.494 | −0.051 | [−0.077, −0.031] |
| 3. ≥2 effective touches | 17,855 | 0.433 | 0.488 | −0.055 | [−0.085, −0.032] |
| 4. formed from ≥4 swings | 28,725 | 0.441 | 0.491 | −0.050 | [−0.077, −0.031] |
| 5. above price, resistance | 16,056 | 0.453 | 0.515 | −0.062 | [−0.098, −0.029] |
| 6. below price, support | 16,125 | 0.444 | 0.475 | −0.031 | [−0.071, +0.009] |
| 7. calm regime | 17,529 | 0.459 | 0.496 | −0.037 | [−0.065, −0.015] |
| 8. violent regime | 14,652 | 0.436 | 0.493 | −0.058 | [−0.089, −0.032] |
| 9. first half of each history | 15,789 | 0.451 | 0.505 | −0.054 | [−0.092, −0.022] |
| 10. second half of each history | 16,392 | 0.446 | 0.484 | −0.038 | [−0.072, −0.009] |
| 11. all round numbers | 68,161 | 0.478 | 0.510 | −0.032 | [−0.048, −0.017] |
| 12. round, no level on it | 54,915 | 0.477 | 0.506 | −0.029 | [−0.045, −0.015] |
| 13. round, above price | 34,140 | 0.510 | 0.531 | −0.022 | [−0.044, +0.003] |
| 14. round, below price | 34,021 | 0.447 | 0.489 | −0.042 | [−0.070, −0.016] |

Per instrument, levels against placebo:

| instrument | n | level | placebo | difference | 95% |
|---|---|---|---|---|---|
| btc | 4,738 | 0.438 | 0.486 | −0.048 | [−0.121, +0.007] |
| eurusd | 8,449 | 0.438 | 0.478 | −0.040 | [−0.084, +0.006] |
| gbpusd | 8,950 | 0.465 | 0.492 | −0.027 | [−0.067, +0.028] |
| gold | 6,125 | 0.458 | 0.530 | −0.072 | [−0.128, −0.033] |
| spx500 | 2,030 | 0.428 | 0.462 | −0.034 | [−0.112, +0.048] |
| us100 | 1,889 | 0.437 | 0.492 | −0.055 | [−0.148, +0.022] |

Per instrument, round numbers against placebo:

| instrument | n | round | placebo | difference | 95% |
|---|---|---|---|---|---|
| btc | 14,547 | 0.481 | 0.504 | −0.023 | [−0.062, +0.012] |
| eurusd | 13,422 | 0.458 | 0.495 | −0.037 | [−0.076, +0.003] |
| gbpusd | 9,286 | 0.483 | 0.507 | −0.025 | [−0.057, +0.016] |
| gold | 15,097 | 0.485 | 0.545 | −0.060 | [−0.092, −0.034] |
| **spx500** | 7,587 | 0.485 | 0.477 | **+0.008** | [−0.033, +0.050] |
| us100 | 8,222 | 0.483 | 0.513 | −0.030 | [−0.077, +0.021] |

That is **forty-five point estimates in all** - fourteen distance bands,
fourteen named cuts, twelve per-instrument breakdowns, two mirrors and three
strength bands - of which **forty-four are negative and one is positive**. The
one is round numbers on spx500 at **+0.8 points, with an interval straddling
zero at five times the estimate's own width**, which is what one slice in
forty-five looks like when nothing is there. Leading with it would be exactly
the search this section exists to disclose.

## 8. Three things found on the way, all worth someone's attention

None of them is about magnets. All three changed this experiment's numbers, so
all three are recorded here rather than lost.

### The diffusion null is off by a constant, and the constant is known

`probability_within` applies the reflection principle to `distance_vol`. But
`distance_vol` is denominated in the project's volatility unit, which
[levels.md](levels.md) §4 defines as the **mean absolute** return - and the
reflection principle wants a **standard deviation**. For a normal the two
differ by a factor of `sqrt(2/pi) = 0.798`, so every distance handed to the
formula is a quarter too large and every arrival probability comes out too low.

Realised arrival within twenty bars over all 44,438 excursions, against the
formula as written and against the same formula with the distance converted:

| distance | realised | as written | distance × √(2/π) |
|---|---|---|---|
| 0.5v | 0.920 | 0.911 | 0.929 |
| 1v | 0.849 | 0.823 | 0.858 |
| 2v | 0.712 | 0.655 | 0.721 |
| 3v | 0.587 | 0.502 | 0.592 |
| 4v | 0.473 | 0.371 | 0.475 |
| 5v | 0.373 | 0.264 | 0.372 |
| 6v | 0.291 | 0.180 | 0.284 |
| 7v | 0.224 | 0.118 | 0.212 |
| 8v | 0.174 | 0.074 | 0.153 |

**As written it says 7.4% where the truth is 17.4%.** With the one conversion
it tracks the realised curve to within a point or two from 0.5v to 6v, drifting
under only in the far tail where fat tails are expected to show. The realised
median excursion of 3.75v implies a per-bar sigma of **1.24 volatility units**
against a theoretical `sqrt(pi/2) = 1.253`.

That is a much better result for `timing.py` than this experiment was looking
for: the Brownian null is *right*, once the unit is the one the formula assumes.
It is stated as a measurement, not as a patch - the fix belongs with whoever
owns that module, and it moves every `within_window` and `soon` the engine
reports.

### The per-timeframe volatility is updated once per venue, not once per bar

`Engine.observe_bar` calls `vol.update` for every venue row that reaches
quorum. Six venues on one daily bar therefore fold one real move and five
near-zero ones into the estimate, and shorten its effective memory by the same
factor. Replaying gold's daily history both ways:

| gold, 1d | volatility |
|---|---|
| one update per venue row, as the engine does it | 63.25bps |
| one update per consensus bar | 125.80bps |

The second matches a hand-rolled EWMA of the same series exactly. The first is
the number in [levels.md](levels.md) §10b, which reads 63.17bps - so the
documented per-timeframe table was measured through the same path.

**A factor of two on the denominator moves everything expressed in volatility
units**: clustering tolerance, zone widths, `KEEP_VOL` pruning, every distance
in this document. This experiment feeds the engine one consensus row per bar
for that reason, and the first run of it - before the cause was found - put the
realised median excursion at 6.85v instead of 3.75v and made the diffusion null
look catastrophically wrong rather than merely mis-scaled.

Measured on the replay path only. Live, bars are republished as they update, so
the count of updates per bar is a property of the sweep rate rather than of the
instrument, which is the part that would want checking before anything is
changed.

### A touch on a daily bar could never resolve

`Engine`'s tracker `horizon` is in **seconds** and defaults to 3,600. On daily
bars every open touch is older than an hour by the next bar and is discarded
before it can resolve, so a daily replay produces a level set carrying **zero
touches** - which is what the first run of §6 found, and why that cut initially
could not be asked at all. Raising the horizon to twenty days produced a mean
of 3.19 effective touches per level and made the strength split possible. Live,
touches are checked on 1m bars where an hour is sixty of them, so this is a
property of replaying coarse history rather than of the running service.

## 9. What this does not test

- **Volume nodes.** The louder half of the folklore is about heavy-volume
  prices, and this project has no reliable volume on the CFD and FX feeds. Only
  the swing-level and round-number variants are testable here, which
  behaviours.md said in advance.
- **Intraday.** Everything above is daily bars over a twenty-bar horizon. A
  magnet that operates over minutes into a round number - the stop-run
  behaviour people describe around 1.1000 - would not appear at this
  resolution. One timeframe was tested, not a sweep of them.
- **The moment of expiry.** Options and futures expiries are the one mechanism
  with a documented pinning story, and no expiry calendar is joined here.
- **Path shape.** Only *whether* price arrived, never how. `timing.py` already
  answers *when* given that it does, and this says nothing about that question
  being right or wrong beyond the calibration in §8.
- **Whether a level is worth anything.** This tests arrival, not reaction. What
  price does once it gets there is the whole of levels.md §7 and is unaffected
  by any of this.

## 10. Verdict

**The magnet effect does not survive.** Arrival at a level is not more likely
than diffusion implies; it is very slightly less likely, and the deficit is
explained by which days a level can exist on rather than by anything the level
does. With the day held fixed the effect is nine-tenths of a point and
indistinguishable from zero. Round numbers behave the same way, a little more
weakly. Level strength does not rescue it. Forty-four of forty-five estimates
came out negative and the forty-fifth is noise.

So behaviours.md §3 is answered: **no attraction term, and no feature.** The
proposal was written as a test before it was a feature precisely so that this
outcome would cost a day rather than a subsystem, and that is what it cost.

What it bought, apart from removing a piece of folklore from consideration, is
the calibration in §8 - which is a real correction to a module the engine uses
in production, found only because the null had to be trusted before it could be
beaten.

## Reading

- [behaviours.md](behaviours.md) §3, the proposal this settles.
- [levels.md](levels.md) §7d, the first-passage arithmetic, and §2, the
  point-in-time guard the design leans on.
- [timing.py](../till_infinity/structures/timing.py), `probability_within`.
