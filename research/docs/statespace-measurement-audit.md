# Three audits of this session's own measurements

Each arm takes a number this desk has reported and asks whether it survives a
resampling or a reconditioning it was never subjected to. None is about markets.

The harnesses are `research/ideas/measurement_audit.py` and
`research/ideas/relates_to.py`.

## The tail lift is estimable, and the objection confused two things

`statespace-volatility-relationships.md` reports a tail lift at the 99th
percentile with 177 of 190 pairs beating the null, and that result carries the
session's risk conclusion. The concentration audit then measured the traded tail
index at `alpha` 2.4 to 3.4, so the **fourth moment does not exist** - and the
fourth-quadrant argument says a tail quantity cannot be estimated from data.

Each pair's lift recomputed on **four disjoint slices**, with the quantiles
refitted inside each so every slice is an independent estimate:

| edge | pairs | whole | across-slice spread | **spread / effect** | sign agrees |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.90 | 45 | +0.2233 | 0.0248 | **0.11** | **1.000** |
| 0.95 | 45 | +0.2313 | 0.0337 | **0.15** | **1.000** |
| 0.99 | 45 | +0.2300 | 0.0616 | **0.27** | **1.000** |

Below 1 the quantity is estimable. At the 99th percentile the spread is 27% of
the effect and **all four slices agree on sign for every one of 45 pairs**.

**The objection conflated two different things, and the distinction is the
lesson.** Kurtosis is a **moment** and genuinely has no population value at
`alpha` near 3 - which is why it ranges 12.5 to 36.2 across instruments. The
tail lift is a **conditional probability**, bounded in `[-1, 1]`, with no moment
to diverge. The fourth quadrant applies to the first and not the second, so the
risk conclusion stands and the kurtosis figure is the one that needed
withdrawing.

## Survivorship cannot be bounded here, which is itself the answer

`statespace-panel-volatility.md` reports `+4.3%` on equities from the "best 21
by coverage", which selects **long-lived listings**.

**There is no second group to compare against: 21 is all that clear the
4,000-bar floor at 1h**, out of 439 equities in the cache. And delisted names are
absent entirely, so the comparison that would bound the bias cannot be built
from this data.

So the figure stands as measured **on survivors, with an unknown bias rather
than a bounded one**. That is a weaker statement than the original and it is the
honest one. Removing it needs a cache with delisted names in it.

## The turkey is not a live failure mode here

Every fit in this session trains on a first half and scores a second. A quiet
first half makes a confident and wrong fit.

| instrument | train/test sd | degradation |
| --- | ---: | ---: |
| USDCHF | 0.913 | 1.0025 |
| EURUSD | 0.968 | 1.0012 |
| GBPUSD | 1.044 | 1.0005 |
| USDJPY | 1.119 | 1.0002 |
| EURJPY | 1.250 | 1.0016 |

Degradation is the out-of-sample error against an **oracle refitted on the test
half**, so 1.0 is no loss from having trained earlier. It runs **1.0002 to
1.0031** - at worst 0.31% worse.

The correlation with the training half's relative quietness is **-0.3594**,
which is the turkey's *direction*, but on ten instruments that is `|t|` near 1.1
and the magnitude is negligible either way. **The split discipline is not
exposed to it**, which is worth knowing because it underwrites the panel
estimator, the slope wander and the exploit search alike.

## And what relates to USDCAD

Asked because `USDCAD` was the one instrument whose mean flipped in the
concentration audit. The first thing to report is what is missing: **CAD is the
oil currency and there is no oil in this cache** - 523 instruments, all FX
six-character pairs, equities as Reuters codes, and Deriv synthetics. No energy,
no softs, no indices. The strongest candidate for this target is **untestable
here rather than absent**.

| instrument | vol corr | split `t` | |
| --- | ---: | ---: | --- |
| **AUDUSD** | **+0.6781** | -0.92 | volatility |
| EURUSD | +0.6565 | -3.48 | volatility |
| NZDUSD | +0.6146 | -3.69 | volatility |
| GBPUSD | +0.5908 | -3.69 | volatility |
| *rotation null, maximum* | *+0.1906* | *-2.97* | |
| Boom_50_Index *(control)* | +0.1203 | -2.87 | nothing |

**14 of 14 FX pairs share volatility with it**, median `0.5351`, led by
`AUDUSD` - the other commodity currency - with `NZDUSD` third. The generated
control reads 0.09 to 0.12 and clears nothing.

**No cointegration, and this harness's own flags have to be overridden.** Four
pairs beat its local rotation null of `-2.97`, but the established bar for a
traded-against-traded pair is **`-4.07`**, from the two-real-leg block-shuffled
null over 570 draws in `statespace-n-leg-spreads.md`. None of the four clears
that, and a 32-draw local null is simply weaker. A screen that reported them
would be refuted by this desk's own earlier work.

**And no equity relates to it**: every one of the top twenty rows is FX, none of
the 21 equities.

## What to use

* **Distinguish a moment from a probability** before applying a
  heavy-tail objection. The same `alpha` that invalidates a kurtosis leaves a
  conditional probability estimable.
* **Quote the established null, not the local one.** A harness that builds its
  own small null will clear it and contradict a better-nulled result elsewhere.
* **Say "on survivors" where it applies.** The equity panel result cannot be
  separated from survivorship with this cache, and pretending otherwise would be
  cheaper than saying so.

## Related

* [P&L concentration](statespace-pnl-concentration.md) - the `alpha` measurement
  that prompted the tail audit, and the kurtosis figure it withdrew
* [Volatility relationships](statespace-volatility-relationships.md) - the tail
  lift this confirms as estimable
* [The panel estimator](statespace-panel-volatility.md) - the equity result this
  qualifies
* [N-leg spreads](statespace-n-leg-spreads.md) - where the `-4.07` bar comes from
