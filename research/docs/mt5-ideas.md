# Eight MT5 strategy ideas, triaged: two tested, four already answered, two out of reach

Eight ideas were proposed on 2026-10-14, four scalping and four swing. Testing
all eight would have been wasteful - four already have measured answers in this
repository, and two need data the cache does not hold. The two that were both
novel and computable were tested.

## Already answered here

**Tick velocity bursts.** The volatility half is measured and it loses.
`vol/projection.py` scored tick-count conditioning against calendar time on
**1,498,858 bars over twenty feeds and eight timeframes**: conditioning on a
bar's own tick count is right in expectation and wrong in practice by
**Jensen's inequality**, `E[sqrt(n)] < sqrt(E[n])`, so `sigma * sqrt(n/N)`
understates the band systematically - dispersion below one at **all eight**
timeframes, which is exactly that signature. The directional half is not
computable at all: the cache holds OHLCV bars, not millisecond tick arrivals.

**Liquidity sweeps.** `drawing/sweeps.py` already reduces this claim to
something measurable, and its docstring states the problem better than the idea
does: being wrong and being swept are different events that look identical to
an account.

**Volume profile and the point of control.** `drawing/profile.py` and
`statespace/ranging.py` both build profiles, and `statespace-ranging.md`
refuted seventeen level constructions - of which profile nodes are one.

**Break and retest.** `outcome-prediction.md` measured the retest directly:
`backcheck` is 7 to 10% of touches and **`confluence_n` predicts it at 0.6140**,
the strongest clean signal in the journal. The specific "30% lower volume on
the retest" condition is untested and is the part worth adding.

## Out of reach on data

**Gold against the dollar as a yield proxy**, and the **currency strength
matrix**, are both computable in principle - the cache even carries
`EUR_Basket`, `GBP_Basket` and `USD_Basket`. But both are **lagged** relationship
claims, and `relationships-are-contemporaneous` records that vol and tails are
large while every lagged measure here is null. Neither is refuted; both need the
null fitted on a training half, because an adaptive ratio gives a
Dickey-Fuller t of -29 from noise and -3.46 once the fit is honest.

## Tested: CTVD divergence carries nothing

`candle-screen.md` had tested volume **correlations** and volume **trends** for
direction and found all four null. A cumulative signed delta is a different
object - an integral rather than a correlation - so it earned its own test:

    CTVD = sum(tick volume * sign(close - open))

read as a divergence: price makes a lower low while CTVD makes a higher low,
which the idea calls absorption. 15m bars, 20-bar swings, decisions spaced 20
bars so no two share an outcome bar.

| arm | feeds | calls | up rate | AUC | sign agreement |
| --- | ---: | ---: | ---: | ---: | --- |
| real | 8 | 3,583 | 0.519 | **0.5188** | 88% of 8 |
| block-shuffled | 8 | 3,585 | 0.538 | **0.5172** | 88% of 8 |

The same AUC on bars whose ordering has been destroyed, and the same 88%
agreement in both arms. A signed cumulative volume delta carries no directional
information that survives shuffling.

The cache's `volume` is MT5 tick volume - median 827 per 15m bar on EURUSD, a
count of price changes rather than lots - so the input is the one the idea
assumes.

## Tested: the triangle converges, and the convergence is smaller than its cost

`EURUSD / GBPUSD` and `EURGBP` are the same number, so the deviation between
them **must** converge. That is why currency triangles are this desk's positive
control for a relationship screen rather than a trade: a screen that misses
them is broken.

So the question is never whether it converges. It is whether the deviation
exceeds what collecting it costs - **three legs, three spreads**:

| triangle | bars | median deviation | p99 | three spreads | deviation beats cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| EURUSD/GBPUSD/EURGBP | 39,905 | 0.000021 | 0.000568 | 0.000800 | **0.02%** |
| EURUSD/AUDUSD/EURAUD | 39,904 | 0.000057 | 0.001354 | 0.001200 | **0.04%** |

Read the first row carefully. The **99th percentile** deviation, 0.000568, is
*below* the three-spread cost of 0.000800. So it is not that the opportunity is
rare - on this triangle a one-in-a-hundred dislocation **still does not pay**.
The second triangle crosses the line on four bars in ten thousand.

`spread` is in **points**, not price. Reading it as price once produced a 476%
round trip on EURUSD and reordered every instrument by cost, so the conversion
is explicit here and a JPY cross divides by 100 rather than 10,000.

## Tested: the weekend gap is the one that survives, and it is FX-only

The claim came with a number - *over 80% filled within 24 to 48 hours* - which
makes it falsifiable rather than vague. It is true, and it beats its placebo,
which nothing else in this file does.

A gap is the Sunday open against Friday's close; filled is price trading back
through that close, measured from the bar **after** the gap. The placebo is a
price the same distance on the **other** side of the open, so the comparison is
reversion against continuation at equal distance.

| family | gaps | fill 24h | placebo | edge |
| --- | ---: | ---: | ---: | ---: |
| fx | 1,904 | **0.856** | 0.611 | **+0.245** |
| index | 696 | 0.733 | 0.647 | +0.086 |
| energy | 440 | 0.561 | 0.614 | **-0.053** |
| crypto, 24/7 | **0** | - | - | the control |

**Crypto returning zero gaps is the detector validating itself.** BTCUSD and
ETHUSD trade continuously, so there are no weekend gaps to find, and a detector
that invented them there would have been the finding instead.

The effect is **FX-specific**. Indices show a third of it and energy leans the
other way, so "Major FX Pairs, GER40/US30" is half right: an index has a daily
auction that already prices overnight information, while a weekend FX open is a
dealer-set price nobody has traded against.

### And it is not generic post-jump reversion

Filling a gap is mean reversion while its placebo is continuation, so the whole
thing could have been the ordinary reversion after any jump. The control is
**intraday moves of the same size**, scored identically, with bars adjacent to a
time break excluded so a weekend cannot appear twice:

| size, typical bars | weekend fill / placebo | intraday fill / placebo |
| --- | --- | --- |
| 0.5-1 | 0.914 / 0.736 | 0.839 / **0.857** |
| 1-2 | 0.859 / 0.572 | 0.719 / **0.743** |
| 2-4 | **0.738 / 0.349** | 0.543 / **0.566** |
| 4+ | 0.469 / 0.198 | 0.292 / **0.338** |

An intraday jump has **no reversion asymmetry at any size** - its fill rate sits
at or slightly below its own placebo throughout. A weekend gap of the same size
reverts 2.1 to 2.4 times more often than it continues. The weekend is the story,
not the jump.

One defect was fixed on the way. The first version measured the weekend fill
from the gap bar itself while the intraday control measured from the bar after
its jump, which would have handed the weekend arm a fill the control could not
have. Symmetric, it costs about one point - 0.924 becomes 0.914 - so the
asymmetry was not the effect, but the comparison was the whole test.

## Tested: volume climax is null, on its own named targets

A daily volume spike beyond 2.5 standard deviations at a 20-day extreme, read
as exhaustion. Measured on gold, oil, crypto and indices as well as FX:
reversal rate **0.489** against a block-shuffled **0.492**, and the AUC of the
spike size for reversal **0.4959** against 0.5108. 9,854 non-overlapping calls.
A bigger spike does not reverse more.

## Tested: lead-lag is refuted with its mechanism in view

The relationship is fitted on the first half and scored on the second, because
an adaptive ratio gives a Dickey-Fuller t of -29 from noise:

| leader to follower | lag 1 | lag 2 | lag 6 | lag 12 | contemporaneous r |
| --- | ---: | ---: | ---: | ---: | ---: |
| XAUUSD to AUDUSD | 0.4965 | 0.4942 | 0.4969 | 0.4986 | **+0.401** |
| US_Oil to USDCAD | 0.4970 | - | - | - | +0.052 |

Gold and the Australian dollar are correlated at **0.40** and carry **no**
lagged information at one, two, six or twelve hours. This is
`relationships-are-contemporaneous` demonstrated as cleanly as the data allows:
the covariation is large and simultaneous, and nothing survives a lag.

Worth noting separately that oil against the Canadian dollar reads r = 0.052.
The premise that oil drives CAD barely holds **contemporaneously** on this data,
let alone with a lag.

## What is left worth running

Nothing from these lists. The retest volume condition was the last candidate
and it is null once its target is unconfounded - see
`research/docs/displacement-origin.md`.

The weekend gap is the one result to take forward, and the next question about
it is not statistical but practical: a 0.245 edge over continuation at a median
gap of under one typical bar has to be weighed against the spread at the Sunday
open, which is the widest of the week and is exactly the condition this desk
has been caught by before.
