# Absorption and compression, graded

Items 1 and 2 of [behaviours.md](behaviours.md), taken as far as the outcome
machinery can take them. Both were written as falsifiable claims, which is the
whole reason they were worth writing, and both have now been run against the
store.

**Neither separates.** Compression separates weakly and in the *opposite*
direction to the practitioner claim, and the separation turns out not to be
about levels at all. Absorption does not separate on any formulation tried.

That is the smaller half of the result. The larger half is what the measurement
had to walk through to get there: three defects in the outcome machinery, all
found by looking at the resolutions rather than at the code, one of which
silently removes 97.5% of every break this system has ever detected from
everything downstream of the engine - including the number written down in
[levels.md](levels.md) §7c.

## What was run

One `Engine`, seeded from `.data/prices/prices.db` through the ordinary replay
path, with wrappers around `Tracker.begin`, `Tracker.update`, `Tracker._close`
and `Tracker.expire` that record the state of the approach at first contact and
the state of the level's touch history at the same moment. Nothing in the
package was modified.

The replay must be drained as it runs, or `MAX_RESOLVED` caps the queue at 500
and truncates the rest without saying so:

```python
engine = Engine()
engine.seed(
    DB, feeds=FEEDS, bars=BARS, on_progress=lambda done, total: collect(engine.drain_resolved())
)
```

Draining is necessary but not sufficient, which is the first finding below:
what the queue holds is not what the tracker resolved.

| | |
|---|---|
| bars replayed | 423,496 |
| instruments | btc, eurusd, gbpusd, gold, spx500, us100 |
| timeframes | 1m, 5m, 15m, 1h, 4h, 1d, 1w (3m is configured; the store has none) |
| distinct levels touched | 3,020 |
| interactions resolved | **4,386** |
| of those, lasting more than one instant | 2,952 |
| of those, at a level with ≥3 prior resolved touches | 2,325 |
| (feed, timeframe) cells with ≥20 repeat touches | 24 |

The replay is *not* exactly reproducible: two runs of the same code over the
same store produced 4,382 and 4,386 resolutions. The cause is the second defect
below, and the fact that a four-touch difference exists at all is a small piece
of evidence for it.

### Provenance, and which tables to trust

These numbers were produced against `2fc8a68`. `18e95c0` landed during the run
and it matters here: `vol.update` was being called once per venue row rather
than once per bar, so the volatility estimate folded in the same close several
times with a run of zero returns between, and read **`vol.bps` divided by
(venues − 2)** - four times too small on EURUSD and GBPUSD, three on gold, two
on btc, and correct on spx500 at exactly quorum. `distance_vol` divides by that
number, so every distance in volatility units read two to four times too large,
**by a factor that differs per instrument**.

That splits this document in two, and the split is worth stating before any of
the tables rather than after:

- **Sound.** Anything computed *within* a (feed, timeframe) cell, and anything
  that is a rate rather than a distance - outcome shares, chop shares, break
  shares, and the p-values throughout, which come from shuffling labels inside
  the same cells and so carry whatever scale that cell has on both sides of the
  comparison.
- **Suspect.** Every table marked *pooled*. A quartile taken across feeds mixed
  units inflated fourfold on FX with units at face value on spx500, so a
  "tight" bucket may be selecting an instrument rather than selecting
  compression. They are kept because each is shown to demonstrate a confound,
  not to support a conclusion - but they had a second confound nobody knew
  about, which only sharpens the point.
- **Not comparable across feeds, even within cells.** The magnitude of a pooled
  *difference* in volatility units - the `departure` and `fwd_range` columns -
  is a weighted average over cells whose units differ by up to 4x. The sign and
  the significance survive; the size does not mean one thing.

Every verdict below rests on the sound half.

### The order-flow caveat, restated because it is load-bearing

Absorption is a claim about limit orders soaking up market orders. This project
has mid, bid, ask and OHLC bars - no depth, no prints, no reliable size. Every
quantity below is a **geometric proxy** and is named as one. The proxy used for
"how far this press got past the level" is the wick's furthest penetration
beyond the level in volatility units, which is written as `press` throughout.

That proxy had to be built, because the quantity behaviours.md nominates -
`excursion_vol` - is **zero on 82.7% of all resolved touches**. It is only ever
assigned once price has gone a full `resolve_vol` (1.5 units) through the level,
so it describes breaks and says nothing at all about a sequence of presses that
never break, which is exactly the sequence absorption is made of. See "What to
do" below; this is the one concrete gap worth closing regardless of everything
else here.

## What the replay produced

Three different populations, and the difference between them is the point:

| population | n | chop | reject | break | trap |
|---|---:|---:|---:|---:|---:|
| every resolution | 4,386 | 29.0% | 53.2% | 8.2% | 9.1% |
| only what a consumer sees (`drain_resolved`) | 3,215 | 13.9% | 72.6% | **0.3%** | 12.4% |
| every resolution that lasted more than an instant | 2,952 | 43.0% | 31.4% | 12.1% | 13.0% |

Every table after this uses the third population. The first is contaminated by
touches that open and close at the same timestamp; the second is what
production actually records, and it is wrong in a way described under "Three
things found on the way".

Chop is overwhelmingly a function of the level's timeframe:

| level timeframe | n | chop | reject | break | trap |
|---|---:|---:|---:|---:|---:|
| 1m | 897 | 5.1% | 54.7% | 13.7% | 26.4% |
| 5m | 338 | 3.3% | 57.1% | 14.2% | 25.4% |
| 15m | 200 | 1.0% | 51.0% | 14.0% | 28.5% |
| 1h | 422 | 37.2% | 28.9% | 32.7% | 1.2% |
| 4h | 304 | 89.1% | 6.6% | 4.3% | 0.0% |
| 1d | 641 | **98.9%** | 0.0% | 1.1% | 0.0% |
| 1w | 150 | **99.3%** | 0.0% | 0.7% | 0.0% |

`Tracker.horizon` is 3,600 seconds for every timeframe, so a touch on a daily
level is chop unless it resolves inside a single hour. This is not a subtle
effect and it dominates any comparison that pools timeframes - which is why
every result below is computed **inside** a (feed, timeframe) cell and then
pooled, with the p-value from shuffling the group labels within cells.

## 1. Compression on approach

The ratio behaviours.md proposes: mean true range over the last few bars before
contact, over mean true range over the last fifty, both in basis points, so it
is scale-free. Below one is compressed. Measured on the series carrying the
touch check and again on the level's own series; the contact bar is excluded
from both, because in a replay it is already complete when the check runs and
including it would let the reaction describe its own approach.

The ratio itself is one set of true ranges over another, both in basis points,
so it never touches `vol.bps` and is unaffected by the estimate being wrong.
The feature is clean; only the targets it is measured against carry the units.

**It is a genuinely new number.** Across variants its correlation with
`approach_vol` runs 0.12-0.16 and with `regime` 0.13-0.15 - behaviours.md is
right that speed and contraction are different quantities, and this is not a
restatement of anything already in `Features`.

Tightest third against widest third, **within (feed, timeframe)** - the sound
form - n ≈ 960 a side.
`fwd_range` is the range realised over the twenty bars after contact in the
volatility units of the moment of contact - a target that owes nothing to the
outcome vocabulary, since `push_vol` is close to a constant per outcome by
construction:

| variant | chop | break | \|push\| | departure | fwd_range |
|---|---:|---:|---:|---:|---:|
| contraction, 5 bars, touch series | +0.013 | −0.023 | −0.047 | **−0.166** (p=0.006) | −0.285 |
| contraction, 5 bars, level series | +0.004 | −0.034 (p=0.02) | +0.001 | **−0.162** (p=0.009) | **−1.467** (p=0.002) |
| contraction, 10 bars, touch series | +0.001 | +0.001 | −0.064 | −0.050 | −0.227 |
| overlap, 5 bars, touch series | −0.020 | +0.039 (p=0.01) | −0.033 | +0.115 | +0.811 |

Unmarked figures have p > 0.05. Read the signs before the stars: **on all three
contraction variants, every significant number says a compressed approach
precedes a *smaller* move** - smaller departure from the level, smaller realised
range afterwards, fewer breaks. The claim in behaviours.md was larger `push_vol`
and fewer `CHOP` outcomes; `push_vol` is flat (p=0.99 on the level series) and
chop is flat (p=0.79) on every variant.

The fourth row is the exception and deserves its own sentence, because it is the
only figure anywhere here that points the practitioner's way: measuring
*overlap* rather than size - the span of the last five bars against the sum of
their true ranges, so a low value means candles covering the same ground - the
most overlapping third breaks 3.9 points more often than the least (p=0.010). It
is one number out of twenty-four in this table, it does not carry departure or
forward range with it, and one p of 0.01 in twenty-four tests is what chance
looks like. It is worth a second dataset and nothing more.

The pooled version of that table looks much more impressive and is the trap -
**suspect, shown as an example of one**:

| level-series contraction, *pooled across feeds* | n | chop | break | departure | fwd_range |
|---|---:|---:|---:|---:|---:|
| tightest quarter | 721 | 39.3% | 9.0% | 1.15 | 13.45 |
| widest quarter | 722 | 36.6% | 14.7% | 1.50 | 17.76 |

Most of that spread is the timeframe mix rather than compression, and the two
right-hand columns additionally mix volatility units that differed per
instrument by up to fourfold. The verdict on compression is the within-cell
table above, not this one.

### And it is not a fact about the level

The relation survives stratification, so it is real. The question is whether it
is real *about levels*. The same ratio can be measured at bars where nothing was
touched, with identical machinery - same true ranges, same `Volatility`, same
forward window, and the thirds taken within (feed, timeframe) as above - and
the answer is that it is stronger where there is no level at all:

| sampled bars | n per side | fwd_range, tightest third − widest third |
|---|---:|---:|
| every sampled bar | 8,036 | −1.818 |
| bars that opened a touch | 856 | −0.883 |
| bars that did not | 7,149 | **−1.915** |

Compression is a volatility forecast wearing a level feature's clothes. Quiet
approaches are followed by quiet markets, at levels and away from them, and
slightly *less* so at levels. Adding it to `Features` would add a
volatility-persistence term to a feature set whose entire design is to divide
volatility out.

## 2. Absorption

Defined as behaviours.md defines it, over the level's own last k resolved
touches, evaluated at the moment of the next contact and using only what was
knowable then: **presses decaying** and **gaps between contacts shortening**.

The touch sequence used here is *more complete than production's*. Resolutions
that never reach a consumer were captured anyway (see below), so absorption was
given a repaired history rather than the one the running system has.

Within (feed, timeframe) - the sound form - build-up against everything else,
k = 3:

| target | build-up (n=449) vs rest (n=1,677) | p |
|---|---:|---:|
| chop | +0.008 | 0.61 |
| break | −0.034 | 0.08 |
| \|push_vol\| | +0.053 | 0.51 |
| departure_vol | −0.054 | 0.52 |
| fwd_range | +0.123 | 0.84 |
| fwd_abs | −0.082 | 0.85 |

Nothing. And nothing across every reasonable variation of how to write the two
trends down:

| variant | n | chop | break | departure | fwd_range |
|---|---:|---:|---:|---:|---:|
| k=3, first vs last, press | 449 | +0.008 (0.61) | −0.034 (0.08) | −0.054 (0.50) | +0.123 (0.81) |
| k=4, first vs last, press | 408 | −0.018 (0.25) | +0.024 (0.22) | +0.065 (0.41) | +0.590 (0.29) |
| k=5, first vs last, press | 355 | −0.020 (0.26) | −0.027 (0.21) | +0.061 (0.49) | +0.519 (0.40) |
| k=4, OLS slope, press | 477 | −0.014 (0.38) | −0.007 (0.70) | +0.034 (0.66) | −0.351 (0.53) |
| k=4, OLS slope, \|push\| | 342 | −0.009 (0.63) | +0.024 (0.29) | −0.196 (0.05) | −0.576 (0.39) |

Twenty tests, smallest p = 0.05, no sign consistency. Conditioning on
compression - asking whether build-up says anything among tight approaches or
among wide ones separately - produces nothing either (smallest p = 0.10).

### The version that looked real, and why it was not

Pooled across timeframes and feeds - suspect, and shown for that reason - the
2×2 is striking:

| *pooled* | n | chop | departure | fwd_range |
|---|---:|---:|---:|---:|
| build-up (both) | 470 | **28.9%** | 1.44 | **17.12** |
| press decaying only | 345 | 51.9% | 1.07 | 16.65 |
| gaps shortening only | 528 | 53.2% | 0.96 | 14.60 |
| neither | 982 | 40.7% | 1.21 | 13.79 |

Chop 28.9% against 40.7% at p<0.001, forward range 17.1 against 13.8 at
p<0.001. It is also non-monotone - both single conditions are *worse* than
neither - which is the tell, and the cause is mix. The build-up group is 38% 1m
and 7% 1d; the control is 32% 1m and 20% 1d. Since 1d levels chop 98.9% of the
time for reasons that have nothing to do with price, any group leaning
fine-grained shows less chop. Within cells the difference is +0.008.

### Contact density, which is the other half of the claim

"Contacts accelerating" has a simpler form: how many contacts this level has had
recently. Pooled - suspect again - it separates hard and in the wrong direction:
0 prior contacts in the last twenty bars gives a forward range of 18.06 against
11.07 for 6 or more. Within cells that shrinks to −0.94 (p=0.038), still
negative: a level hit repeatedly precedes *smaller* moves, not larger.
This is the same volatility-persistence story as compression. Price grinds at a
level when the market is quiet, and the market stays quiet.

## 3. Three things found on the way

### Twenty-seven percent of resolutions reach nothing

`Engine.check` calls `self.tracker.expire(when)` and discards the return value.
It is the only caller. A touch resolved there is added to the kNN `Memory` and
**nothing else** - no `level.record`, so the level's own per-side statistics
never see it; no `observe_touch`, so the Kalman position never moves; no
`level.broke_at`, so no back check can ever be linked to it; and no append to
`_resolved`, so `service._record_outcomes` never journals it and `facto` never
trains on it.

| resolved by | chop | break | reject | trap | backcheck | total |
|---|---:|---:|---:|---:|---:|---:|
| `Tracker.update` → drained | 448 | **9** | 2,334 | 400 | 24 | 3,215 |
| `Tracker.expire` → dropped | 822 | **349** | - | - | - | 1,171 |

The asymmetry is the damage. `expire` is where a break that got through and then
went quiet is resolved - which is what a *successful* break looks like - so
**349 of 358 breaks, 97.5%, are invisible to everything downstream of the
engine**. The observed break rate in the journal is 0.3%; the real one is 8.2%.

This has consequences already written down elsewhere. levels.md §7c reports 43
breaks recorded and one back check, and reasons about the ceiling on back
checks from there. Those 43 are whatever survived this filter - a different
store and a live path rather than a replay, so the 2.5% here is not a scaling
factor to apply to them, but the count is a floor and the reasoning built on it
needs redoing once breaks are delivered. It is also the direct obstacle to
grading absorption honestly: the outcome absorption exists to predict is the one
outcome the system almost never records.

### A third of touches resolve at the instant they open

1,434 of 4,386 (32.7%) - and 44.6% of the drained stream - have
`resolved == started`. Their outcomes are 1,406 rejects, 15 traps, 13 back
checks, and no chop or breaks at all. They are not reactions; the answer is
fixed before any time passes. Two mechanisms, both measurable:

**The zone can be wider than the resolution distance, by construction.**
`MAX_ZONE_VOL` is 3.0 and `Tracker.resolve_vol` is 1.5, so a zone may legally
extend to twice the distance that counts as the interaction being over. A touch
born in the outer half of its own zone is already resolved: 461 of those 1,434
began ≥1.5 volatility units from the level, and the next update closes them as
rejections whose `push_vol` is the depth they arrived at. This has nothing to do
with the volatility bug above - the two constants disagree at any scale.

**The consensus close jitters within one bar timestamp.** `Consensus.observe`
returns a median as soon as `MIN_VENUES` = 3 have reported, and every later
venue on the same bar re-runs the whole touch check against a recomputed median.
That median moves, and on some instruments it moves a great deal relative to the
bar:

| | venues per bar | typical 1m move | quorum-median vs full-median jitter | in volatility units |
|---|---:|---:|---:|---:|
| spx500 | 6 | 0.51 bps | 2.26 bps | **4.40** |
| eurusd | 7 | 0.30 bps | 0.17 bps | 0.57 |
| btc | 6 | 1.60 bps | 0.22 bps | 0.13 |

On spx500 the consensus close wanders several volatility units inside a single
bar purely as a function of which venues have reported, and spx500 has the
highest instant-resolution rate of any instrument at 41.2%. This is not the
double-counting bug of [handoff.md](../research/handoff.md) - the re-arm rule holds, and
only two timestamps in the replay carry more than one touch at one level -
but it is the same family, and it is why two runs of the same replay disagree.

This one does not depend on the replay at all: checked independently against
the **production journal**, 46% of recorded outcomes resolve at or before the
moment they open, 97% of those were already past `resolve_vol` at contact, and
their median push is 2.30 volatility units. Whatever else is uncertain here,
this is happening on the running system.

### One horizon for eight timeframes

`Tracker.horizon` defaults to 3,600 seconds and the engine never varies it, so
"nothing happened within an hour" is the chop test for a weekly level and a
one-minute level alike. 98.9% of daily touches and 99.3% of weekly ones resolve
as chop. Those 826 rows are not observations about levels; they are observations
about the constant.

## What this says about `CHOP`

behaviours.md's worry was that chop is hiding absorption, and that relabelling
would have consequences. On this evidence it is not.

Chop is hiding two other things, and both are cheaper to fix than a new label.
The first is the horizon: **1,054 of 1,270** chop resolutions are on 4h, 1d and
1w levels, where an hour was never long enough for anything else. The
second is the missing 822 chops from `expire`, which the model is not shown at
all - so the one label that exists specifically to teach the model about
non-events is itself two-thirds absent from training.

Fix those and the chop rate becomes a measurement rather than an artefact. Then
ask again whether what remains contains a build-up state, on a sequence of
touches that is complete and a break label that exists.

## What to do

In order, and the first three are repairs rather than features.

1. **Deliver what `expire` resolves.** Either route it through `_close` so a
   level records it, or have `Engine.check` append it to `_resolved`. Until then
   the journal's outcome mix is not the system's outcome mix, back checks cannot
   be found, and no experiment about breaks means anything. This is the single
   highest-value line in this document.
2. **Record the press depth on every touch, not only on breaks.** One field
   beside `excursion_vol`, maintained in `Tracker.update` from the wick the same
   way `extreme` already is: the furthest this touch got *past* the level, in
   volatility units, whether or not it ever became a break. Among interactions
   that lasted more than an instant, the proxy is non-zero on 68.8% against
   `excursion_vol`'s 25.2% - nearly three times the coverage, for one line of
   state, and it is what made this test possible outside the package.
3. **Make the horizon a function of the timeframe**, or stop opening touches on
   timeframes whose bars are longer than the horizon. Either is defensible; the
   present arrangement is not, because it labels 99% of weekly touches by the
   clock rather than by price.
4. **Reconcile `MAX_ZONE_VOL` with `resolve_vol`.** 3.0 against 1.5 means a
   touch can be born already resolved, and roughly a third of them are. Either
   the zone ceiling comes down to the resolve distance, or resolution is
   measured from where the touch *started* rather than from the level. The
   second is probably the right answer - "how far price went from where it met
   the level" is the quantity a consumer thinks they are reading - but it
   changes what `push_vol` means and would need saying out loud.
5. **Do not add an absorption feature.** It has been graded and it separates
   nothing. If it is revisited after 1-4, it should be re-run through the same
   harness rather than argued about - the whole replay is about three minutes on
   an idle machine.
6. **Do not add a compression feature to `Features` either.** It separates, but
   it is a volatility forecast and it separates more strongly where there is no
   level. If the forward-volatility information is wanted, it should be taken
   for what it is and used where volatility forecasts belong, not smuggled into
   a kNN distance that exists to make instruments comparable by dividing
   volatility out.

And one incidental: `Touch.energy` divides by `approach_vol` with no floor.
`approach_vol` reaches 1.49e−11 in this sample and `energy` reaches 4.6e10, so
any average over it is meaningless. It is documented as a headline reading of
the reaction and nothing consumes it yet, which is the only reason this has not
already produced a nonsense number in front of someone.

## What could not be measured

- **Absorption as order flow.** Everything here is price geometry. A level
  genuinely absorbing supply would show it in the book, and there is no book. A
  null on the proxy is not a null on the behaviour, and it should not be quoted
  as one.
- **Whether the build-up state exists on a repaired system.** The measurement
  was made against the machinery as it stands. Three of its defects are
  material, and two of them (the missing breaks, the instant resolutions) touch
  exactly the outcomes absorption is about.
- **Anything about crypto beyond btc, or about sol, eth and the rest of the
  fourteen instruments in production.** The local store holds six.
- **Sub-bar behaviour.** The replay is bar-driven. Live, `observe_quote` runs
  the touch check at tick resolution, where an approach has a shape a 1m bar
  cannot show. Compression in particular deserves a second look on quotes before
  it is called dead, though the placebo result suggests the answer will be the
  same.
- **Any of this out of sample.** These are 4,386 resolutions over one store,
  and the compression result - the only thing that separated at all - was found
  after looking at several variants. It is a hypothesis for a second dataset,
  not a finding.
