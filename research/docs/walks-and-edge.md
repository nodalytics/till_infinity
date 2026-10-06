# What the random-walk control means, and what it does not

**A note on method, 2026-10-04.** It came from a correction by the desk. Several studies had called a
pattern's improvement "an artefact" or "geometry" because the same pattern did as well on matched
random walks. That was the wrong word.

## The lesson

"Artefact" was the wrong word. It is kept only for genuine measurement bugs (look-ahead, fill errors,
cost scaling). **Matching the walks does not make a pattern fake.** Markets are close to random walks,
so most patterns *should* look similar on both. A walk produces the same shapes: displacement, sweeps,
breaks, origins, returns. The walk is not there to call a pattern false. It is the yardstick for
whether trading the pattern can make money.

## Why the walk is still the yardstick

On a random walk, every exit rule has the same expected value: zero before costs, whatever its
reward:risk. The chance of reaching +N R before −1R is exactly 1/(N+1):

| target | P(win) on a walk | expected value |
|---|---|---|
| 1R | 50% | 0.50 × 1 − 0.50 × 1 = 0 |
| 4R | 20% | 0.20 × 4 − 0.80 × 1 = 0 |
| 10R | 9.1% | 0.091 × 10 − 0.909 × 1 = 0 |

A high-R:R rule on a walk pays for its big winners with a lower hit rate, exactly. After the spread it
is slightly negative ([deriving.md](deriving.md): `E[net] = −(c/2) × turnover`). **R:R alone cannot
make money. What makes money is beating 1/(N+1).**

So when a pattern "matches the walks", say it plainly. Its trades reach high R no more often than
randomness allows, so its expected value before costs is zero. That says nothing about whether the
pattern is real. It only says this trade on it has no edge.

## What the desk is looking for

A pattern, rare or common, whose P(≥ N R) at large N (4, 5, 10, 20) **exceeds both 1/(N+1) and the
same pattern on matched walks**, on data it was not found on. One that fires twice a month and
reaches 10R 15% of the time, against 9% on walks, is a real edge. The best strategies are often the
simple ones, and an edge in the tail is enough.

The method is built to catch exactly that. Every study reports P(N R) against 1/(N+1) and against
the walks, and leads with the tail. Examples so far:

- **DISPLACE_C at a 12-bar low** ([turning-points.md](turning-points.md), fresh coins) reached 4R
  3.7% of the time, against 1.2% on walks: three times the random rate in the tail. It is the one
  result that has survived a frozen test on unseen data. It is thin and not yet confirmed (a second
  set gave +0.032R [−0.013, +0.080]).
- **The turn trade with market exits.** Its lift over "buy every low" also showed up on walks, and
  its P(N R) curve sat on the walk's. That means zero edge before costs, not a broken pattern.

*Update, 2026-10-06:* DISPLACE_C's edge turned out to be the crypto market factor, timed
([pca-residuals.md](pca-residuals.md)). Traded on BTC as the market mirror, it passed again on 274
unseen perps ([turn-follow-ups.md](turn-follow-ups.md) §6). See
[desk-summary-2026-10.md](desk-summary-2026-10.md).

## Models that read chart shape: the chart reader and the crowd

*Added 2026-10-06, from a point the desk raised while starting the FX and metals ML study.* When a
model trained on real charts scores as well on matched walks, it is reading chart shape. That may
mean it sees the chart the way retail traders do. The walk control is the tool that separates what
that view contains from what people do with it. Report every such model in three parts:

| part | measured as | what it means |
|---|---|---|
| **1. What the chart shows** | the model's skill on matched walks | The information any chart's shape carries, with nobody trading it. A walk has slopes, swings, breaks and channels too. This is real and measured; it is not "nothing". |
| **2. Behavioural skill** | real skill minus walk skill | The only place an effect of people trading those shapes can appear. If retail behaviour around shapes (stops under swings, entries at breaks, crowding at round levels) moves price, real exceeds walk here. |
| **3. Whether it pays** | the trade translation after costs, P(N R) against 1/(N+1) and against walks | Behavioural skill can be real and still too small to pay a spread. |

**How to read the result:**
- **Real equals walk:** the model sees the chart the way a chart reader does, and that view holds the
  same information on a random walk. People acting on it don't move price enough to show. That is a
  finding about the crowd, not "the model learned nothing".
- **Real above walk:** behavioural skill. It is the candidate edge, and the thing to confirm on unseen
  data and then price after costs.
- **Real below walk:** the market punishes the chart-reader's view, for instance stop runs beyond the
  obvious swings. That too is behaviour, and the opposite side becomes a hypothesis for its own frozen
  test.

**Measuring the crowd directly.** Where retail positioning data exists (the long/short share of
traders), add it as a feature block frozen before the run. That measures the crowd directly instead of
inferring it from the real-minus-walk gap.

**So far on this desk** the gap has been small or zero wherever it was measured:
- break prediction: side AUC 0.75 on real and 0.755–0.757 on walks ([bos-predict.md](bos-predict.md));
- fuzzy rules: direction AUC 0.508 against walks at 0.499 ([fuzzy-logic.md](fuzzy-logic.md));
- level holds: 0.58–0.60 against 0.565 ([tv-indicators.md](tv-indicators.md), [lrc-retest.md](lrc-retest.md)).

Level holds are the clearest behavioural signal found so far: real levels hold slightly more often
than walk levels, consistent with people defending them. The gap is too small to pay a stop and a
spread. The FX and metals ML study (`fx-metals-ml.md`, in progress) reports behavioural skill as a
named quantity per class and timeframe.

## Where "artefact" still applies

The word is kept for measurement bugs that make a result unreal on the market as served. Examples from
these studies:
- **Fill errors on jump instruments.** A bar replay fills a jumped stop at −1R, while the tick fill
  averages −7.8R. Range Break's "+3.7R" was this ([range-break-100.md](range-break-100.md)).
- **Bid-bar opens at the FX reopen**, which turned a +0.46R gap fade into −0.41R
  ([mean-reversion.md](mean-reversion.md)).
- **Look-ahead in a conditioning flag**, such as a trend read from the bar that contains the spike
  ([boomcrash-trend.md](boomcrash-trend.md)).
- **Cost scaling bugs** and **near-zero-risk entries** (minimum risk is 0.25 ATR).

A pattern that matches its walks is none of these.

## How to report it

- **Lead with tail excess:** real P(≥ N R) minus the walk's, and against 1/(N+1), at the N the trade
  is built for.
- **Say "matches the walk: no edge before costs"**, not "artefact" or "only geometry".
- **For models, report three parts:** skill on walks (what the chart shows), real minus walk
  (behavioural skill), and the after-cost trade.
- **Keep the walk null.** Without it, a 1:10 rule winning 9% of the time looks like a strategy.
- **Use walks that keep what real markets have** (GARCH for volatility clustering, the hour-of-day
  profile, the same calendar). Then any excess is about the side, not the volatility.
- **Confirm on data the pattern was not found on.** A tail picked out of many cells will look good
  by chance.
