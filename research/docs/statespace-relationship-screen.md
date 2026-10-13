# A relationship screen, and the hedge ratio that manufactured its answer

A stat-arb state space is supposed to be handed a set of assets and come back
with the pairs. `relating.Relating` already carries a hedge ratio as a
**state** rather than a fitted constant, so the per-pair machinery existed;
what was missing was the search.

This is the search, and the useful part turned out to be what the null
revealed about the method rather than which pairs it ranked.

**The answer is a null.** Against a threshold measured from independent pairs
whose legs have the same fat tails as the candidates, **0 of 190 traded pairs
are cointegrated**, and
the pairs that come closest revert over a fraction of their round-trip cost.

**Read that with its scope.** One ratio and one `t` test for a *time-invariant*
relationship, and that test has **no power past 80% tied**: a pair genuinely
tracking for 60% of its out-of-sample life reads `-2.29` here and never clears
the bar, while the same data read in windows reads `-14.74`. So "0 of 190"
means no pair is *constantly* cointegrated, not that no pair is related.
[The episodic form](statespace-episodic-relationships.md) is the test that can
tell those apart - and on this universe it is also a null, with traded pairs
reverting in 30.8% of windows against the shuffled null's 30.8%.

Two separate defects had to be removed to see that: a hedge ratio that
manufactured the statistic, and a null whose legs were Gaussian-tailed where the
candidates' are not.

The harness is `research/ideas/relationship_screen.py`.

## Screening N squared pairs needs a null the procedure itself generates

20 traded instruments is 190 pairs. At the conventional 5% that is ten
"significant" relationships from nothing, and the usual answer - a
Dickey-Fuller critical value - assumes independent random walks and says
nothing about the screen's own multiplicity or its own machinery.

**The Deriv synthetics supply a better one.** Separate engines, so
cross-family pairs are draws from "no relationship" through the identical
pipeline: the same `Relating` filter, the same bar count, the same
Dickey-Fuller arithmetic. 553 cross-family null pairs against 190 live ones.

### The assumption was checked rather than made

The first version asserted the synthetics are mutually independent. That is
plausible across families and suspicious within them: `DEX_600_UP_Index` and
`DEX_600_DOWN_Index` are **named as a pair**, `Volatility_10` through
`Volatility_100` are one process at different volatilities, and
`Volatility_75_Index` and `Volatility_75_1s_Index` are plausibly one path at
two rates. Any of those inside the null would set a bar nothing could beat,
and the screen would report no relationships *while looking rigorous* - a
false negative dressed as discipline.

So the null is partitioned and the extremes printed by name. **It does not
bite:** all ten of the most reverting null pairs are cross-family, and
same-family pairs are *weaker*.

| partition | best | 1st pct | median |
| --- | ---: | ---: | ---: |
| cross-family, live ratio | **-29.39** | -24.84 | -3.12 |
| same-family, live ratio | -20.33 | -20.33 | -2.33 |
| **cross-family, split ratio** | **-3.46** | **-3.16** | -1.60 |

## The live hedge ratio manufactures the statistic

`Boom_50_Index` against `Skew_Step_Index_4_Down` - two unrelated generated
processes - reads a Dickey-Fuller `t` of **-29.39**. The best real-market pair
reads **-18.19**. The textbook augmented-Dickey-Fuller 1% value is about
**-3.4**.

**So the pipeline produces more apparent cointegration from noise than from
markets**, and under that arm **0 of 190 traded pairs beat the null.** The
correct reading is not "there are no relationships" but "this screen cannot
detect them".

The mechanism is that `Relating` adapts its ratio to every reading, so a spread
formed against it is stationary by construction - the ratio absorbs whatever
the two series jointly do. Lagging it one bar, which is what a desk holding the
filter would have, is **no lag at all**: the ratio barely moves in a bar.

## The split arm is a valid test, and its null says so

One ratio fitted by least squares on the first half and held fixed over the
second cannot absorb what it has not seen. Its null lands at **-3.46 best and
-3.16 at the first percentile**, which is the textbook critical value - and
that value was **derived from 553 independent pairs rather than assumed**. A
test whose empirical null matches theory on data with nothing in it is a test.

**17 of 190 traded pairs beat it**, against the roughly 0.34 chance expects at
a threshold set by the minimum of 553 draws. That reads as a real excess - and
the next section withdraws it, because this null is not the right one.

## The variable is the tails, not independence

The first version of this claimed a traded-against-synthetic pair was "the only
null with guaranteed independence". **That is wrong, and it matters.** Two
cross-family synthetics are independent too - `Boom_50_Index` and
`Skew_Step_Index_4_Down` have no more connection to each other than either has
to EURUSD. Swapping one leg for a real market changes nothing about
independence. It changes the **leg distribution**, and that is the whole effect.

Which is measurable, so it should be measured rather than argued:

| legs | median kurtosis | 1st pct | max |
| --- | ---: | ---: | ---: |
| 20 traded instruments | **20.07** | 10.74 | 57.88 |
| 36 Deriv synthetics | **3.19** | 2.48 | 10.09 |

Gaussian kurtosis is 3.0. **The synthetics are Gaussian-tailed and the traded
universe is not, by a factor of six.** A Dickey-Fuller statistic on a spread of
two kurtosis-20 series does not have the distribution it has on two kurtosis-3
series, so a synthetic-only null judges the candidates against the wrong
reference however independent it is.

### So the null is partitioned by how many legs are real

Three partitions, all independent by construction - synthetics across families,
a synthetic against a market its engine never sees, and a market against
**another market's returns in day-long blocks placed in a scrambled order.**
The last one is the key: a block shuffle is a permutation, so it preserves each
leg's tails *exactly* - EURUSD's kurtosis is 18.11 before and 18.11 after - and
its within-day clustering, while destroying any relationship between the legs.

| real legs | pairs | split best | 1st pct | median |
| --- | ---: | ---: | ---: | ---: |
| 0 - synthetic x synthetic | 553 | -3.46 | -3.16 | -1.60 |
| 1 - traded x synthetic | 720 | -3.94 | -3.47 | -1.76 |
| **2 - traded x shuffled traded** | 570 | **-4.07** | -3.79 | -2.17 |

**The threshold is monotone in the number of real legs** and the whole
distribution shifts, not just the extreme - the median moves -1.60 to -2.17.
Independence is constant across all three rows, so the tails are the only thing
that could be producing it.

### Which erases the excess

Against the bar whose legs are distributed like the pairs being screened,
**0 of 190 traded pairs beat -4.07.** 17 beat the synthetic-only -3.46. The
best traded pair on the honest statistic is USDJPY/XAGUSD at **-3.37**, short
of even the one-real-leg bar.

So the apparent excess was a null that was too easy, and the live-ratio defect
was the same mistake in a different place: **a reference distribution that does
not share the properties of what it is judging.** The first failed on the
procedure, the second on the tails.

The live arm moves the *opposite* way across the partitions - -29.39, -28.31,
-18.88 - which is a second confirmation of the first defect. A shuffled leg has
no co-movement left for an adaptive ratio to absorb, so the live statistic
deflates by 10 points of `t` the moment the joint dynamics are removed. It was
never measuring cointegration.

### And the reverse reading, which is reassuring

A traded-against-synthetic pair showing a genuine relationship would mean
Deriv's engine is seeded from market data. **None does.** The synthetics are
independent of the traded universe, as documented, and remain usable as
controls - with the caveat this section establishes: they are a good control
for *structure* and a poor one for *tails*.

## What the cost gate does to the survivors

`range/cost` is the spread's own standard deviation over a round trip in both
legs. Below 1 there is nothing to trade however good the `t`.

* the pairs that **are** significant read **0.2 to 0.5** - they revert over
  less than it costs to trade them;
* the pairs that clear the cost gate are the gold-against-JPY-cross cluster -
  EURJPY/XAUUSD at 18.5, AUDJPY/XAUUSD 10.7, GBPJPY/XAUUSD 10.6,
  CHFJPY/XAUUSD 6.7 - and **none of them is significant**, with split `t` of
  -1.74, -0.95, -2.53 and -1.53.

Statistically real but too small to trade; large enough to trade but not real.
That is the same wall as the directional work, the barrier work and the
forecast work, reached by a fourth route.

## Gold against USDCHF, which is the pair that prompted this

**Split `t` of -3.19, rank 37 of 190, beating none of the three nulls -
-3.46, -3.94 or the -4.07 bar.**
The hedge ratio's **sign is right** - `-0.013` fixed and `-0.176` live, and
gold rising with USDCHF falling is the same weak dollar seen twice - so the
economic intuition holds. But `range/cost` is **0.1**: the spread's standard
deviation is a tenth of a round trip, so there is nothing to trade even if the
reversion were significant.

Worth noting for scale: the desk's own hand-studied USDJPY/XAGUSD pair ranks
**163 of 190** on the live arm and **26 of 190** on the split one, and
gold/silver ranks 128 and 166. Hand-picking found a pair the live screen
dislikes and the valid screen rates highly - which is an argument for the
screen in its split form rather than against the pair.

## What to use

**Never form a cointegration spread from `Relating`'s live ratio.** It is the
right object for *holding* a hedge - that is what it was built for - and the
wrong one for *testing* whether a hedge exists, by a factor of 8.5 in the test
statistic.

The split form works and has an empirically verified threshold. **Measure that
threshold on pairs whose legs are distributed like the candidates** - here
block-shuffled real markets, not synthetics. It costs 0.6 of a point of `t` and
is the difference between 17 survivors and none.

Its answer on this universe is that **no traded pair is cointegrated beyond
what the screen produces from independent processes, and the ones that come
closest revert over a fraction of their own trading cost.** Both halves have to
fail for a stat-arb book to be worth running, and both do.
