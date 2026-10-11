# Displacement sequences: three shapes built, seven numbers refuted

`statespace-borrowed-claims.md` ended by keeping three ideas from a family of
in-house write-ups, on the grounds that they were **shapes rather than
claims**: displacement sequences between reversal points as an observation
process, symmetry detection as a switching model over that sequence, and
Wasserstein as a second metric beside likelihood.

All three are now built. Four more write-ups from the same family arrived while
they were being built, and between them they assert seven numbers about the
sequence of moves between reversals. Every one of the seven is measurable on
the observation process, so every one was measured.

**All seven came back null, and six have a mechanism** - the measurement says
not just that the number is wrong but what produces the number that was
reported instead. The seventh, the one claim that survived a first pass,
reversed when its control was split properly.

## What was built

| module | what it observes | scored against |
| --- | --- | --- |
| `displacements.py` | the move between confirmed reversals: size in volatility units, duration in hours, direction | nothing - it is an observation process |
| `symmetry.py` | `log(size(t)/size(t-1))`, as three symmetry classes | the same sequence shuffled, and a walk's sequence |
| `distance.py` | where a distribution sits, not how likely a point was | `scipy.stats.wasserstein_distance`, to 1e-6 |

`displacements.py` is the piece that was missing. Every other member in this
package observes a **price**, and asks where the level is going. A displacement
sequence is a different series on a different clock: it advances when price
turns rather than when the clock ticks, and its elements are already
differences, so the unit root is gone before any model sees it.

Two details carry the weight. Each displacement records **both** when the move
ended and when it became knowable, which differ by the pivot's confirmation
reach - conflating them is the leak the whole construction exists to avoid.
And two same-direction swings in a row are dropped, because a detector firing
twice inside one structure would make the sequence's alternation a property of
the threshold rather than of the market.

### `symmetry.py` and a defect worth recording

The member began with the three class centres as free states, on the reading
that "the geometric relationships persist within a regime" is a claim about a
level that holds for a while. That version is **a single Gaussian wearing
three hats**: all three centres start with the same variance, so they take the
same gain, so they walk to the same place. The means collapse, the three
densities become one, and the posterior sits at exactly one third forever. A
test caught it reporting `[0.333, 0.333, 0.333]` with `means` all at 1.2e-38.

Anchoring the centres with a reversion only slowed it: the measurement update
still dragged every centre toward the observation, and the expanding class's
0.48 arrived at 0.095 inside forty readings.

The fix is to stop treating a definition as a parameter. **Mirror *means* the
ratio is one.** A mirror class whose centre has drifted to 1.4 is not a
better-fitted mirror, it is a mislabelled expansion - and then every reading of
`contracting` is a reading of where the centres happened to drift. So the
member is a hidden Markov model with known emissions: three fixed hypotheses,
scored by likelihood, mixed by a hazard per hour.

This is the third member to need the same fix. `relating` was 30x overconfident
until its anchor was fixed at the first reading, and `panel` fixes its anchors
for the same reason. The pattern: **a quantity that defines what a component
means cannot also be a state the component estimates.**

## The seven numbers

51 cells: 17 instruments across 1h, 4h and 1d, run in the lab. Nine are
auction markets - FX, metals, indices, BTC, ETH - and eight are Deriv
synthetics.

### The synthetics are the strongest arm here

They are real markets. Real spreads, real fills, real money, and this desk
trades them. What they do not have is an **auction**: the price comes from a
specified stochastic process rather than from participants crossing orders,
and the process is known rather than inferred.

That makes them a better control than any simulation, because every claim in
this family is a claim about auction structure - accumulation, distribution,
phases, exhaustion, buyers absorbing supply. A claim that holds just as well on
`Volatility_75_Index` is a claim about the detector, and it has been refuted on
data the desk actually trades rather than on a surrogate someone could wave
away.

`Range_Break_100_Index` earns a special mention. It is a generated index whose
whole design is to sit in a range and then break out of it - the exact
phenomenon the rotation-counting framework claims to count down to. Its
correction factor is 0.997, its branching ratio is 1.95, and its hazard has
the same parity as everything else.

### 1 and 2: the correction factor

The original asserts `alpha = |K|/R = 0.86` universally, and warns correctly
that every formula downstream depends on it. The revision rejects that and
reports 0.73 on EURUSD, 0.62 on BTC, 0.58 on the S&P.

Measured, as the median ratio of consecutive swing sizes:

| | asserted | revised | measured |
| --- | --- | --- | --- |
| EURUSD | 0.86 | 0.73 | **0.97 - 1.00** |
| BTCUSD | 0.86 | 0.62 | **0.89 - 0.94** |
| S&P | 0.86 | 0.58 | **0.99 - 1.01** |
| eight generated markets | - | - | **0.96 - 1.02** |

Every cell sits near one, including every generated market. Neither number is
right, and the quantity has no instrument-specific value to find, because
**a median ratio of one is what any exchangeable size sequence gives.** If
`size(t)` and `size(t-1)` are draws from the same distribution then their
ratio is as likely to exceed one as to fall below it, by symmetry, whatever
the distribution is. The measurement is the detector's alternation, read back.

### 3: the correction factor is serially correlated, so predictable

This one is true in sign and magnitude and still carries nothing.

| | measured |
| --- | --- |
| lag-1 Spearman, median over 51 cells | **-0.451** |
| the same with the swing sizes shuffled | **-0.477** |
| what the arithmetic alone predicts | **-0.500** |
| rotated control | **-0.01** |

`alpha(n)` is `s(n)/s(n-1)` and `alpha(n+1)` is `s(n+1)/s(n)`. They **share
`s(n)`**, once above the line and once below it, and that shared term alone
gives a correlation of exactly minus one half between the two logs for
exchangeable sizes. The market sits at -0.451, slightly *weaker* than the
shuffle's -0.477, both on top of the arithmetic.

So the serial structure is real, strong, consistent across every instrument,
and entirely a property of writing a ratio of consecutive terms. The revision
reads it as persistence - "instruments tend to have characteristic correction
depths that persist for many cycles" - and the sign is the other way: it is
anti-persistence, and it is not in the market.

The same arithmetic explains the member's forecast correlation: -0.417 median
raw against the next log ratio, 0.000 rotated. Strong, consistent, wrong-signed
and mechanical.

### 4: each swing holds about 3.2 sub-swings, between 2.3 and 4.1

Measured as fine pivots nested inside each coarse swing, at reaches of 2 and 5:

* **1.92 to 2.35 across all 51 cells**, with the per-swing mean and the ratio
  of the two scales' pivot counts agreeing to two decimals everywhere.
* Not one cell reaches 2.4. The asserted range's *floor* is above the measured
  ceiling.
* The generated markets give 1.92 to 2.35, the same interval.

The revision gets the direction of its own critique right - the branching
ratio is not a law - and then reports a number that is not the one the data
gives.

### 5: a range sustains `(N*2)+1` rotations and then breaks

This is the find of the run, and it kills the counting family outright.

Three write-ups make a counting claim: that a phase sustains a characteristic
number of internal rotations and is then exhausted. Whatever the arithmetic,
the claim needs the hazard to **rise** with the count - exhaustion means a
phase becomes more likely to end the longer it has run. So the reading is not
the mean count but the hazard by count: the chance a swing ends at its `k`-th
sub-swing given it got there.

| k | swings reaching k | ends at k | a random walk |
| --- | --- | --- | --- |
| 1 | 103,883 | **0.601** | 0.558 |
| 2 | 41,416 | **0.021** | 0.000 |
| 3 | 40,545 | **0.671** | 0.646 |
| 4 | 13,336 | **0.019** | 0.000 |
| 5 | 13,080 | **0.690** | 0.659 |
| 6 | 4,059 | **0.022** | 0.000 |
| 7 | 3,970 | **0.699** | 0.659 |
| 8 | 1,196 | **0.016** | 0.000 |

The hazard does not rise. It **alternates by parity**: odd counts end a swing
six or seven times in ten, even counts almost never. And a Gaussian random
walk reproduces the pattern essentially exactly.

The mechanism is geometry, not energy. A parent swing runs from one coarse
pivot to the next, and the two are opposite in kind - a high then a low. The
fine pivots inside also alternate. Getting from a high to a low across an
alternating sequence **requires an odd number of intermediate turns**. The
count is forced odd by the nesting, so an even count means the sequence has
not finished, and that is the whole of the 0.02.

Which retro-explains the practitioner's formulas. `(N*2)+1` is odd for every
`N`. `(N*2)-1` is odd for every `N`. The framework discovered that nested
alternating pivot counts are odd, and then fitted `N` to whichever odd number
a chart showed. There is nothing left once the parity is removed: the hazard
within each parity class is flat to within 0.1 across k=1 to 7, which is a
renewal process, and a renewal process has no "due".

### 6: a low symmetry index means a structured, tradeable market

The index is the mean absolute log ratio of swing sizes across a lag - how far
a swing is, multiplicatively, from the one `k` back. Low means sizes repeat.
Swept over lags 1 to 6 against two controls:

| | median gain over a shuffle of the same sizes |
| --- | --- |
| the real series | **0.136** |
| a GARCH(1,1) t(5) surrogate | **1.864** |

The index does measure something: real sequences are more self-similar at
short lags than a shuffle of themselves, which is swing-size clustering and
is the slowly-decaying absolute-return autocorrelation this desk already
records as a stylized fact in `facts.py`.

But a surrogate with clustered volatility and no geometry whatsoever scores
**thirteen times the gain**. The index cannot tell a market from a specified
process, and telling those apart is the only thing it was offered to do. The
gain also barely decays from lag 1 to lag 6, which is what a volatility
reading looks like and not what a periodicity at lag `k` looks like.

### 7: geometric structure is more stable than price levels

The one claim that survived a first pass, and the reversal is instructive.

Pooled over all 136 instrument pairs, the swing-ratio distributions are much
closer to each other (W1 0.076) than the standardised return distributions are
(0.126), which reads as support. Split by arm:

| pairs | n | W1 ratios | W1 returns | |
| --- | --- | --- | --- | --- |
| auction with auction | 36 | 0.0709 | 0.0728 | **tied** |
| generated with generated | 28 | 0.0708 | 0.0284 | returns travel better |
| one of each | 72 | 0.0800 | 0.1704 | ratios travel better |

The pooled result came entirely from the **mixed** pairs. A `Step_Index` is a
two-valued move and `Boom` and `Crash` carry one-sided jumps, so their
standardised returns are far from a currency's by construction, while a ratio
of consecutive swing sizes is invariant to all of that. Comparing across the
two populations, the ratio statistic looks stable because it has discarded the
difference.

Within auction markets - the claim's actual scope - the two are tied, 0.0709
against 0.0728. The swing-ratio distribution is no more alike across
instruments than the standardised return distribution is.

**The general lesson is about pooling.** A median over a pooled set of pairs
drawn from two populations can report the opposite of what every subgroup
says, and the direction of the error is not guessable in advance - here the
pooled answer agreed with the paper and both subgroups did not.

## The member's own verdict

`Symmetry` against its two nulls, in held-out log-likelihood:

* **Against a walk's displacement sequence**: wins everywhere, by 300 to 600
  nats. The walk is the weak null and this says only that swing ratios are
  not those of a walk.
* **Against the same sequence shuffled**: wins in 33 of 51 cells and loses in
  18, with every loss at 1h. The wins are **+0.7 to +25 nats over two to four
  thousand readings** - about 0.009 nats each.
* **The generated markets win against the shuffle too**, by +0.7 to +9.5.

An advantage that is tiny, changes sign with the timeframe, and appears on
markets with a known generator is not a reading of market geometry. The
sequence's order is worth almost nothing to a model that assumes its regimes
persist - which the lag-1 result already predicted, since the sequence
anti-persists at -0.45 and a persistent-regime model is the wrong shape for
that.

## Wasserstein, as a second axis

`distance.py` is kept whatever happens to the rest, because it answers a
question likelihood cannot. A log-likelihood is a sum of point densities, and
one fat innovation can dominate it; a transport distance asks how far the
whole distribution has to move. `against_normal` is the member-calibration
number - standardised innovations are N(0,1) under a correct model - and it
comes with a unit: a reading of 0.3 means the innovations sit three tenths of
a standard deviation from where the member claims, which is a sentence a
likelihood cannot produce.

Verified against `scipy.stats.wasserstein_distance` to 1e-6, and against the
cases with known answers: a sample against itself is 0, a shift of 2.5 costs
2.5, N(0,1) against N(0,1) gives 0.014 at this sample size, and doubling the
innovations' width gives 0.79.

## What this run is worth

Seven numbers, seven nulls, six mechanisms, and one new general lesson about
pooling. The three shapes were worth building: two of them produced the
measurements that refuted the claims, which is what an observation process and
a second metric are *for*.

What is not worth more time is the family itself. Every claim in it reduces,
when measured, to one of three things: the pivot detector's alternation, the
arithmetic of a ratio of consecutive terms, or volatility clustering. The
remaining untested item in the family - Point Z's three structural criteria -
rests on the same 0.86 that measured at 0.99, so its depth constraint is the
first thing that would have to be swept, and a lone threshold that works at
one value and nowhere else is a fit rather than a finding.

The harness is `research/ideas/displacement_symmetry.py`. It reads the pulled
broker cache under either spelling and falls back to the local files, so it
runs whether or not the bridge is up.

**Since this was written, the obvious explanation for these nulls was tested
and is wrong.** The displacement `size` is an absolute value, so a trend and a
range with the same swing sizes are identical in it - which looked like reason
enough for the ratios to carry nothing. `statespace-peaks-and-troughs.md`
builds the **signed** like-node distance, peak to peak and trough to trough,
and it is null too: the peak-to-peak separation's spread matches a random
walk's, the higher-high-with-higher-low agreement gains +0.151 over its drift
where a walk gains +0.158, and 3 of 312 forward cells clear cost at a largest
|t| of 0.64.

What these quantities share is not that they discard direction. It is that
they are arithmetic rearrangements of an **alternating sequence produced by a
thresholded detector**, which has strong structure of its own. Null the next
one against a walk before reasoning about it.
