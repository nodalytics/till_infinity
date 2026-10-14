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

## What is left worth running

The retest volume condition, because the retest itself is already the most
predictable outcome in the journal and the volume filter is the one part of
that idea nobody here has measured.
