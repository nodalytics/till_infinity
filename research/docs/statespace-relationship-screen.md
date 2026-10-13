# A relationship screen, and the hedge ratio that manufactured its answer

A stat-arb state space is supposed to be handed a set of assets and come back
with the pairs. `relating.Relating` already carries a hedge ratio as a
**state** rather than a fitted constant, so the per-pair machinery existed;
what was missing was the search.

This is the search, and the useful part turned out to be what the null
revealed about the method rather than which pairs it ranked.

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
a threshold set by the minimum of 553 draws. That is a real excess.

### And the two arms rank almost orthogonally

| pair | live `t` | split `t` | range/cost |
| --- | ---: | ---: | ---: |
| EURGBP/XAUUSD | **-18.19** *(live rank 1)* | -2.37 | 0.1 |
| EURUSD/XAUUSD | -12.54 | **-3.67** | 0.5 |
| GBPUSD/EURJPY | -9.59 | **-3.61** | 0.2 |
| GBPUSD/XAUUSD | -9.77 | **-3.50** | 0.3 |
| **USDCHF/XAUUSD** | **+0.22** *(live rank 185)* | **-3.19** *(split rank 37)* | 0.1 |
| USDJPY/XAGUSD | -0.80 *(live rank 163)* | -3.37 *(split rank 26)* | 2.2 |

The live arm's top pair is not significant under the valid test, and its
185th-of-190 is 37th. **So the live ratio does not merely inflate the
statistic, it reorders it** - which is worse, because a reordering looks like
a finding.

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

**Split `t` of -3.19, rank 37 of 190, and it does not beat the -3.46 null.**
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

The split form works, has an empirically verified threshold, and its answer on
this universe is that 17 pairs are real and none of them pays.
