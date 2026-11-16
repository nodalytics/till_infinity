# Candles and the TSI, one decile at a time

**Measured 2026-11-15.** Five majors, 15m, eight years, ~1,000,000 rows. Each
feature cut into deciles, each decile reporting the forward 16-bar move in ATR
that followed it, with each instrument's own drift removed first.

## Two controls, and they answer different questions

**A permuted feature.** Shuffle the feature and keep the targets: this
destroys the association under test and nothing else, and what comes back is
how large a decile mean a million rows produce from nothing. For ten deciles
of about 100,000 rows that floor is **0.016 to 0.019 ATR**. Every number below
has to beat it.

**Day-shuffled bars.** Every wick, body and range exactly as the market made
it, only the order of days changed - so a reading that survives is a property
of bar shapes in isolation and one that vanishes needed the market's sequence.

**The day shuffle is the weaker null at this horizon, and it is worth saying
why.** A 16-bar forward window on 15m bars lies inside a single day, and
shuffling whole days leaves each day's internal sequence intact. So that arm
barely perturbs the quantity being measured, and reads as a near-copy of the
real one almost by construction. It answers "is this cross-day structure",
which is a real question, but it is not a floor.

## The readings

| feature | largest decile | permuted floor | ratio |
|---|---:|---:|---:|
| **tsi** | 0.0576 | 0.0169 | **3.41** |
| close_in_range | 0.0339 | 0.0164 | **2.07** |
| tsi_abs | 0.0336 | 0.0173 | 1.94 |
| tsi_slope | 0.0322 | 0.0189 | 1.70 |
| bar_size | 0.0307 | 0.0184 | 1.67 |
| lower_wick | 0.0254 | 0.0174 | 1.46 |
| wick_imbalance | 0.0205 | 0.0193 | 1.06 |
| body_ratio | 0.0182 | 0.0162 | 1.12 |
| upper_wick | 0.0186 | 0.0181 | 1.03 |

**The body ratio, the upper wick and the wick imbalance are at the floor.**
Those are the three the operator's pattern rule is built from - a small body
with a long tail - and as continuous readings they sort forward returns no
better than a random permutation of themselves. That is the same answer the
rule got at -0.271 a trade, arrived at without a rule.

**The TSI sorts, and then the day shuffle takes it back.** Its extreme
negative decile is followed by **-0.0576**, three and a half times the floor
and the largest reading in the table - and on day-shuffled bars the same
decile reads **-0.0496**, which is 86% of it. The sorting is real and it is a
property of bar shapes, not of the market's sequence. Its top decile is worse:
+0.0153 real against **+0.0360** shuffled.

**Where a bar closes in its range reverses, weakly.** d1, closing at the low,
is followed by +0.0339; d10, closing at the high, by -0.0244 - and shuffled
those are +0.0209 and -0.0224. Two thirds of a short-horizon reversal that is
already only twice its floor.

## The size of all of it

The largest effect anywhere in this table is **0.058 ATR**, and the median 15m
spread on these instruments is **0.011 to 0.041 ATR**. So the best reading
available is between one and five times the cost of acting on it, before any
exit, and most of the table is inside the cost.

That is the same conclusion [`atr-ml.md`](atr-ml.md) reached with two models:
there is sorting in bar geometry, it is small, it does not need the market's
sequence, and it sits at the scale of the spread.
