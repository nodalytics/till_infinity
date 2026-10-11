# USDJPY against XAGUSD: no pair, no lead, and a session pattern that is the dollar

Asked on 2026-10-11: can the two be paired, does one rise when the other
falls, how long does it take, and is any of it seasonal.

Short answers: **the correlation is -0.21 and three quarters of it is the
shared dollar leg; the hedged spread is not stationary, so there is no pair;
there is no lead-lag at any horizon from one hour to two days; the directional
claim fails in a way that identifies it as a drift rather than a response; and
the hourly pattern is real, large, and mostly the dollar becoming dominant
during the London and New York sessions.**

## The confound, stated first because it decides most of the result

Both instruments are quoted in dollars. USDJPY rises when the dollar
strengthens against the yen; XAGUSD *falls* when the dollar strengthens
against silver. So a dollar move alone pushes them in opposite directions, and
**any** two dollar-quoted instruments will show a relationship that is nothing
but the shared leg.

So every arm is run twice: raw, and on the residual after a dollar factor
built from EURUSD, GBPUSD, AUDUSD, USDCHF and USDCAD - each signed so a rise
means a stronger dollar, and with both legs under test excluded, because a
factor containing them would remove the thing being measured.

| frame | n | raw | rotated | net of dollar | rotated |
| --- | --- | --- | --- | --- | --- |
| 1h | 47,351 | **-0.212** | -0.000 | **-0.038** | -0.002 |
| 4h | 24,931 | **-0.207** | 0.003 | **-0.074** | 0.004 |
| 1d | 4,850 | **-0.211** | -0.004 | **-0.063** | -0.004 |
| two generated indices, 1h | 50,000 | 0.005 | 0.001 | 0.005 | 0.001 |

The raw relationship is real - stable at -0.21 across three timeframes, with
every rotated control at zero - and **64% to 82% of it disappears with the
dollar.** What survives is -0.04 to -0.07, consistent in sign, and small.

The dollar removal uses one full-sample regression, which over-removes rather
than under-removes, so the net column is a **lower bound** on the pair's own
relationship.

## Can they be paired? No.

Correlation is not the question. A tradeable pair needs the hedged combination
to **come back** when it wanders; otherwise it is two directional bets paying
two spreads. So the test is a Dickey-Fuller `t` on the spread, against a
critical value simulated from random walks of the same length rather than read
off a table.

| frame | hedge ratio | Dickey-Fuller t | 5% critical | half-life |
| --- | --- | --- | --- | --- |
| 1h | -0.075 | **-1.90** | -2.72 | 2,294 h (96 days) |
| 4h | -0.077 | **-0.17** | -2.72 | 137,884 h (16 years) |
| 1d | -0.062 | **-0.23** | -2.72 | 115,930 h (13 years) |
| two generated indices, 1h | 0.013 | -2.43 | -2.72 | 3,621 h |

**Fails at every frame**, and the hedge ratio is a fixed one fitted on the
first half of the sample and held through the second - the only form a trade
could use, because a hedge ratio has to be known before the position opens.

The half-lives are the same answer in different units. A spread that halves
its dislocation in thirteen years does not come back.

The generated pair is the check that the test has the right size: two
independent processes also fail, and its 1h `t` of -2.43 is *more* negative
than the real pair's at 4h and 1d.

## Two leaks this arm had first, and the control that caught both

Worth recording, because both would have produced a confident wrong answer.

**The live hedge ratio.** The first version built the spread as
`y - r(t)*x` with `r` a live state from `Relating`. That filter adapts `r` to
keep the current residual small, so the residual is stationary *by
construction of the filter*, whatever the pair does. The arm reported a
Dickey-Fuller `t` of **-40** on the pair - and **-8.95 on two independent
generated indices**, which cannot be cointegrated. Lagging the ratio by one
reading does not fix it: the ratio still comes from the whole history and
still tracks the level.

**An unfitted null.** The version before that scored `Reverting` against
`Walk` on held-out likelihood and found a gain of +128,194 on the pair - and
**+99,444 on the placebo.** `Walk`'s step size was never calibrated to the
series, so the gain measured calibration rather than reversion. This desk has
recorded the same trap once before, when fitting a walk's noise gained it
+14,563 in `statespace-fitting.md`.

In both cases the arithmetic was right and the comparison was rigged. **The
placebo was the only thing that showed it** - a pair of Deriv volatility
indices, independent by construction, where any method that reports a
relationship is reporting its own bias. It cost nothing to include and it
caught two separate defects in one run.

## How long does it take? It does not take any time.

Cross-correlation across lags in hours, so the answer is the same at 1h and
4h:

| lag, hours | -48 | -24 | -12 | -6 | -3 | -1 | **0** | 1 | 3 | 6 | 12 | 24 | 48 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| correlation | -0.005 | 0.002 | 0.007 | 0.003 | -0.002 | -0.000 | **-0.212** | 0.004 | -0.006 | -0.008 | 0.005 | -0.000 | -0.009 |
| rotated | -0.001 | 0.000 | 0.002 | -0.002 | 0.001 | 0.001 | -0.000 | 0.003 | -0.004 | 0.001 | -0.004 | -0.005 | -0.002 |

**Everything is at lag zero.** Every non-zero lag sits inside its own rotated
control, from one hour out to two days in both directions. The relationship is
simultaneous and nothing about one leg is knowable from the other beforehand.

The Lévy area agrees independently. It is the signed area the two-asset path
encloses and its sign says which leg leads - an asymmetry a correlation cannot
express. Against a null from fifteen rotations the pair scores z of -0.24,
-0.66 and -0.66 across the three frames, and the placebo +0.25 to +0.43. **No
asymmetry at any frame**, by either method.

*(A first version normalised the Lévy area by `sd(x)*sd(y)*n` and reported it
directly. The placebo caught that too: independent indices returned 0.26 to
0.64 where the pair returned 0.21 to 0.73. The Lévy area of two independent
paths is not near zero - it is the classical stochastic area, mean zero with a
spread growing like the sample length - so one reading of it is noise and it
needs its own null.)*

## If XAGUSD falls, does USDJPY rise?

No, and the way it fails is more informative than the failure.

After a silver move past 1.5 trailing standard deviations, USDJPY's mean
forward log return over the next 1 to 120 hours:

| trigger | 1h | 3h | 6h | 12h | 24h | 48h | 120h |
| --- | --- | --- | --- | --- | --- | --- | --- |
| silver **fell** | 0.00000 | 0.00011 | 0.00017 | 0.00015 | 0.00024 | 0.00045 | 0.00115 |
| silver **rose** | -0.00003 | 0.00003 | 0.00006 | 0.00003 | 0.00020 | 0.00047 | 0.00104 |

Three readings, each sufficient on its own:

* **The two rows have the same sign.** If silver falling made USDJPY rise, the
  `rose` row would be negative. It is positive and nearly identical. What is
  being measured is USDJPY's own drift over the window, present whichever way
  silver moved.
* **Every cell is under cost.** The round-trip gate is 0.0288 in log terms at
  1h; the largest conditional mean is 0.00115, forty times smaller.
* **No cell has a usable t.** The largest is 1.66 across fourteen cells, where
  one above two is the expectation from chance alone. The t values are already
  corrected for the overlap the rolling horizons create.

## Seasonality: real, and mostly the dollar

The hourly pattern is the largest effect in the study, and it is not noise -
every rotated control is at zero.

| hour, UTC | 00 | 03 | 07 | 09 | 11 | **12** | 13 | 15 | 18 | 19 | **21** | 23 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| raw | -0.145 | -0.057 | -0.208 | -0.237 | -0.292 | **-0.394** | -0.324 | -0.246 | -0.378 | -0.358 | **-0.054** | -0.111 |
| net of dollar | -0.009 | 0.028 | -0.076 | -0.111 | -0.169 | -0.092 | -0.065 | 0.007 | -0.081 | -0.105 | -0.063 | -0.040 |

The raw correlation ranges from **-0.054 at 21:00 to -0.394 at 12:00**, a span
of 0.340, and it tracks the sessions: deepest through the London morning and
the London-New York overlap, shallowest in the Asian hours.

Net of the dollar the span falls to 0.205 and the deepest cell is -0.169.
**About 60% of the hourly variation is the dollar** becoming dominant when
dollar price discovery happens. What survives keeps the same shape - the
London and overlap hours remain the deepest - so there is a residual channel
beyond the dollar that is concentrated in those hours, which is what a
risk-sentiment story would predict for a funding currency against a risk
asset.

It is still not tradeable, because the conditional arm above found nothing
following from the relationship at any horizon, at any size above cost. A
contemporaneous correlation that is stronger at midday is a statement about
when the two move together, not a statement about which moves first.

By weekday the range is -0.159 to -0.250 across Monday to Friday, net -0.021
to -0.065, with no cell standing out. Sunday has 644 points and is ignored.
Four of thirty cells sit more than 0.1 beyond the pooled correlation, which
for 29 nominal cells is the expectation.

## What would change the answer

* **A longer horizon than this tests.** Everything here runs to 120 hours. A
  risk-sentiment channel could operate over weeks, and the 1d frame has only
  4,850 bars, so a monthly test needs more history than the cache holds.
* **Conditioning on the dollar rather than removing it.** The residual
  relationship is concentrated in the session hours; whether it is stronger
  when the dollar itself is quiet is a different question, and `panel.py`
  would answer it by carrying the factor rather than regressing it away.
* **A third leg.** The pair fails as a pair, but USDJPY, XAGUSD and XAUUSD
  together might hold a stationary combination where no two of them do. That
  is `relating` with two independent legs, which it already supports, and it
  is the natural next test.

The harness is `research/ideas/jpy_silver.py`. `LEFT` and `RIGHT` are
environment variables, so any other pair is one run away, and the placebo arm
travels with it.
