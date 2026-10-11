# statespace: what signals a move, and what it is worth after costs

Extracted from `statespace/README.md` on 2026-10-11. Every attempt here to find a **direction** came back a coin; everything that worked was about **size**. The sections are in the order they were measured, and two of them are corrections of the one before.

The short version: the residual beats the covariance, speed beats both, nothing predicts sign, and three separate real effects turned out to be the size of the spread.

## Can these track where a trend changed, and what happens when price returns?

Asked 2026-10-10, about a specific case: the market trends up for five days,
stalls, bounces the other way - can the models find the exact turn, and what do
they say when price comes back to it? The answer is in three parts and only one
of them is a gap in this package.

**The stall is learnable and the reversal is not, and that is measured.** A trend
change is a sign change in the rate. On 999 eurusd 4h returns, **speed is 8.1x as
persistent as signed velocity** - the sum of the first five autocorrelations is
+0.381 against -0.047 - and consecutive directions agree 49.499% against 50%
+/- 3.102%. So "the trend stalled" is a statement about speed, which carries
structure; "and will bounce the other way" is a statement about direction, which
is a coin. A member tracking the signed rate is tracking the half with nothing
in it.

**No member can represent the turn itself.** `linear` integrates, `reverting`
pulls back, `selective` averages, `swarm` anchors - all purely decaying. They can
notice a turn *after* it has happened, as the old rate decays and a new one
builds, and none of them can produce one. That is D4 and it is the only gap in
the family that no pending member fills.

**The exact point is a level, and that machinery already exists.** A turn becomes
a level in `structures`, and `fade-to-value` already targets the displacement
origin - where its 82% figure is a target hit rate and not an entry signal. The
state space's job is not to find the turn; it is to say where that level is *now*
and how well it is known.

**What it says when price returns, which is the interesting half.** Four
quantities, and each answers a different question about a five-day-old turn:

| quantity | what it says on the return touch |
| --- | --- |
| `output()` | where the level is estimated to be now - it may have drifted, which is what `jerk` and `DRIFT_VOL_PER_HOUR` model |
| `band(when)` | how precisely, and it has **widened** over the five days |
| `existence` | whether it is still a level at all: a 7-day half-life puts a 5-day-old turn at about **0.63** |
| `last_standardised` | **the signal.** Did the touch land where the level was expected? |

That last row is the one worth building on. A return touch inside the band is the
level confirming its own position; a touch far outside it is either a level that
moved or a different level, and those are different trades. Bounding how much a
surprising touch moves the state is exactly what `robust` is for.

**And the "what does it do when it comes back" question is already answered
250,412 times.** `reactions.Episode` follows every touch for `EPISODE_BARS` both
ways and records `mfe_up_r`, `mfe_down_r`, `first`, `held_first`, `bars_up_*`,
`bars_down_*`, `bars_opposite` and a `kind` - `whipsaw` among its values. The
measurement is: condition those outcomes on the level's **age** and on its
`existence`, and ask whether a five-day-old turn behaves differently from a
five-hour-old one. No new data and no new member required, and it would settle
whether `existence`'s seven-day half-life is the right clock or a guess that
happens to match `engine.FORGET_FEED_SECONDS`.

## What the market does when the model is uncertain, and what signals a move

Measured 2026-10-10 on the 285,688 held-out points, conditioning the **next**
move on each quantity at the time. Asked as: what does the market do when
uncertainty is high or low, and what gives a signal that a movement - up or
down - is about to happen.

**One answer covers all of it: every quantity predicts the size of the next move
and none of them predicts its direction.**

Ratio of mean `|next move|` in the highest bucket against the lowest, over
quintiles of 71,374 points on the best-calibrated member:

| conditioned on | ratio | and the direction? |
| --- | ---: | --- |
| **`loglike_step`** - how surprised the model was | **2.18x** | coin |
| **`last_standardised`**, `\|z\|` | **2.02x** | coin |
| disagreement between the four members | 1.24x | coin |
| `sd` - the model's own prior uncertainty | 1.24x | coin |

`continue` - the next two moves sharing a sign - sat between **48.3% and 49.6%**
in every bucket of every cut. Including the signed test, which is the one that
would have been an edge: bucketed by **signed** `z`, the most negative quintile
and the most positive both give `|next|` near 1.5, with mean next moves of
`+0.034` and `-0.013`. A surprise above the model and a surprise below it are
followed by moves of the same size in no particular direction.

### The realised surprise beats the expected uncertainty, by about 2x

This is the finding worth building on. `sd` is what the model *thinks* it does
not know; `|z|` and `loglike_step` are what just surprised it. The residual is
nearly twice the signal that the covariance is - 2.0x against 1.24x - which is
volatility clustering stated in state-space terms: **what just happened predicts
the next move's size better than what the model expected to happen.**

So the usable signal here is **residual-based, not covariance-based**, and it is
direction-free, which matches what was asked for - "it could be an up or down
volatile movement". A reading the filter found surprising is followed by a move
1.8 vol units on average against 0.9 for an unsurprising one.

### A safety finding: two members are overconfident exactly when they claim precision

Coverage of the two-sigma band, by quintile of the member's own `sd`:

| member | lowest `sd` bucket | highest |
| --- | ---: | ---: |
| `linear` | **19.3%** | 87.9% |
| `reverting` | **34.0%** | 95.1% |
| S4D-Real LTI | 86.6% | 93.9% |

When `linear` is most confident its band fails **four times out of five**. That
is worse than useless to a desk that sizes on the band, and it is not visible in
an average - pooled, `linear` covers 68.6%. The failure is concentrated in
precisely the states where a caller would trust it most.

### The `existence` cut is confounded, and the confound is the lesson

Bucketing by `existence` sorted the points by **timeframe**: the median gap in
the five buckets came out 24.00h, 4.00h, 1.00h, 0.25h and 0.05h. Within a
regularly sampled bar series `existence` is nearly constant - it decays on the
clock and every bar restores it - so it varies mainly *between* timeframes. The
`|next|` and `continue` columns were identical across two different members,
which is the giveaway: they were properties of the data, not of the model.

**`existence` cannot be tested on bar data.** It needs genuinely irregular gaps,
which is the touch series - `reactions.Episode`, 250,412 of them - where a level
can go untouched for five days and then be hit. That is the measurement that
would say whether the seven-day half-life is right or is just
`engine.FORGET_FEED_SECONDS` borrowed.

### What else could signal a move, and is not yet tested

* **Speed rather than uncertainty.** Speed is 8.1x as persistent as signed
  velocity, and `rate` is on every member. Untested as a size predictor, and it
  is the obvious companion to `|z|`.
* **The band *narrowing*, not its level.** This measured the level of `sd`. A
  squeeze - `sd` contracting and then expanding - is the classic version and is
  a different variable. `linear` also exposes `sd_rate` and `sd_accel`, which
  are uncertainty about the *rate*, and neither has been looked at.
* **A rolling Ljung-Box breaking.** Residuals that suddenly correlate are a
  state equation that has just stopped describing the series, which is a regime
  change by definition. `diagnostics.residuals` already computes it; nothing
  calls it on a rolling window.
* **The wick subject.** Mazza's one directly usable result is that Dojis go with
  sharply *lower* high-low volatility and higher book liquidity, and this desk
  can compute spread, high-low and activity even without a book.

## Is the innovation's reversion bigger than the spread? Mostly no

`research/ideas/statespace_innovation_reversion.py`, 2026-10-10. The four-step
plan, executed in the order where the first step can kill the rest.

**1. The cost gate. 3m fails, eurusd 15m passes, and the sign is not stable.**
"Edge" is the predicted move for a two-sigma surprise divided by the median
spread, so below 1.0 the effect sits inside the cost of taking it.

| series | best t | edge, spreads | verdict |
| --- | ---: | ---: | --- |
| eurusd 3m | **-7.1** | 0.16 - 0.85 | **strongest effect, least tradeable** |
| eurusd 15m | -5.2 | 1.15 - **2.42** | clears the spread at h = 2, 5, 10 |
| eurusd 1h | -2.2 | up to 3.41 | weak t, wide bands |
| gbpusd 3m | -5.8 | - | same sign as eurusd |
| usdjpy 3m | **+5.8** | 0.13 - 1.00 | **sign flips: momentum, not reversion** |
| xauusd | -3.2 | 0.07 - 0.83 | nothing consistent, signs flip |

The first row is the lesson. eurusd 3m has the best statistics in the whole
table and the worst cost ratio, because the 3m spread is **0.343 volatility
units** - a third of a typical bar. A statistical effect that lives inside the
spread is microstructure, and the fact that it is strongest where the spread is
widest relative to the move is the signature of bid-ask bounce rather than of a
view about price.

**And the sign is not stable across symbols**: eurusd and gbpusd revert at 3m,
usdjpy trends, xauusd does neither consistently. That is not one phenomenon. The
search covered roughly 150 cells - five symbols by three timeframes by five
horizons by clipped and raw - so eurusd 15m surviving is **a candidate, not an
edge**, and it needs a different period before it is anything.

**2. Robustifying works, and for the predicted reason.** Clipping the innovation
at 2.5 sigma strengthens reversion where it exists - eurusd 3m `t` from -4.6 to
-6.1 at h=1 and -5.6 to -7.1 at h=5, eurusd 15m h=10 edge from 1.58 to 2.42 -
and **kills momentum where that is what is there**: usdjpy 3m from `t = +5.8` to
`+1.6`. So **large innovations carry continuation and small ones carry
reversion**, and the Huber gate separates them. That is exactly what `robust`
was written for and this is the first measurement of it doing the job.

**3. Ten bars beats one, confirmed.** On eurusd 15m the clipped edge runs 0.92,
1.30, 1.54, **2.42**, 0.98 across h = 1, 2, 5, 10, 20. It accrues to ten bars
and then decays, so the natural horizon there is about two and a half hours and
not a bar.

**4. Cross-resolution confirmation buys nothing, and the first version of that
test was invalid.** With the 15m innovation correctly lagged by one 15m bar, the
"3m and 15m agreeing" slope has the same sign and a *weaker* `t` than 3m alone -
-2.2 against -4.8 on eurusd - because only 58-61% of bars agree and the sample
shrinks. Requiring confirmation costs more than it buys.

**The version before the lag reported slopes of +0.43 to +0.73 at `t` of +14.5
to +20.8, uniformly positive on all five symbols including the synthetic
generator.** A 15m bar stamped at T does not close until T+15m, so attaching its
innovation to 3m bars from T onward used up to twelve minutes of the future. An
effect that strong, that uniform, and present on a generated series is the
signature of leakage - and the agreement rate falling from 73% to 59% once the
lag was added is how much was leaking.

### And the unit error before it, which is the same kind of mistake

The first run of this harness reported the median spread as **136 volatility
units** on usdjpy 3m. A spread 136 times the typical bar move would mean the
market is untradeable, which is how it announced itself: `spread` in the seqlab
npz is in **points**, not price, and dividing as though it were price inflated
the cost by `1/tick` - a factor of 100,000 on EURUSD. `tick_size` now infers it
from the series as the smallest non-zero absolute change, which recovers 1e-5
for EURUSD, 1e-3 for USDJPY and 1e-2 for XAUUSD and the synthetics.

**Both mistakes were caught by the result being physically absurd rather than by
reading the code.** That is worth keeping as a habit: a number that cannot be
true about a market is a faster check than a review.

## Fade the slope, or follow it? Follow, on the daily - and the fades were an artefact

`research/ideas/slope_fade.py`, 2026-10-11. Asked for: forecast volatility and
**invert** the recent slope, try a one-to-two week lookback, size by
`1/forecast vol`, filter on overstretch above one standard deviation, add an EMA
over slopes and an EMA over z-scores, and check by volatility regime.

1,800 cells - five symbols by four timeframes by five lookbacks by three signal
flavours by three horizons - of which **4.9 are expected above `|t| = 3` by
chance**. So the list matters less than whether the survivors cluster.

### The correction that changed the answer

The first run found fading a one-to-two week slope on 15m bars with
`t = -10.8`, on usdjpy **and on v75**. A generated series showing the same
effect as a market is the synthetic control doing its job, and the cause was
overlapping windows: at `look = 960` and `h = 50`, consecutive observations
share 1,010 bars out of 1,010, so ten thousand of them are nothing like ten
thousand independent draws. Overstating `t` by about `sqrt(overlap)` is how this
kind of test manufactures significance.

`independent()` now steps by the horizon and keeps one observation per
non-overlapping window. **Every long-lookback fade disappeared.** The table still
prints the overlapping `t` beside it, because the gap between the two is the
most instructive number in the harness.

### What survives

**Following the slope on daily bars, on usdjpy, in nine neighbouring cells:**

| signal | look | h | follow R | independent t | after cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| slope | 10 | 5 | +0.151 | +3.9 | +0.102 |
| slope | 20 | 5 | +0.177 | +4.9 | +0.129 |
| ema slope | 5 | 5 | +0.137 | +4.1 | +0.089 |
| ema slope | 10 | 5 | +0.157 | **+4.7** | +0.109 |
| ema slope | 20 | 5 | +0.156 | +4.3 | +0.108 |
| ema zscore | 5 | 5 | +0.138 | +3.9 | +0.089 |
| ema zscore | 10 | 5 | +0.158 | +4.5 | +0.110 |
| ema zscore | 20 | 5 | +0.166 | +4.6 | +0.118 |

All three signal flavours, all three lookbacks, the same horizon, the same sign,
and **positive after one spread**. That is the pattern a real effect makes and an
isolated square does not. eurusd 1d agrees on two cells, `t` +3.1 and +3.4.

**The EMA variants are the best of the three**, slightly: `ema slope` and
`ema zscore` reach `t = +4.7` where the raw slope reaches +4.9 at one lookback
and +3.9 at another. Smoothing helps a little and standardising before smoothing
helps about as much as smoothing alone, which is worth knowing because the
z-score version is the more expensive one to compute.

**v75 produced no survivors at all**, which is the control working: the
surviving effects are on markets and not on a generator.

### The one surviving fade is exactly eaten by the spread

gbpusd 15m, `ema slope` and `ema zscore`, `look` 5 and 10 at `h = 5`:
`follow` is -0.113 to -0.147 at independent `t` of -3.0 to -3.2, so fading earns
that much gross. The 15m spread there is 0.113 volatility units. **The edge and
the cost are the same number**, which is the third time in this file that a real
effect has turned out to be the size of the spread.

### Volatility regime: no structure, and the claim is not supported

"Fading breaks in high-vol breakouts" is testable and does not hold here. On
eurusd 15m the fade is **strongest in the quietest regime** - `follow` -0.166 at
`t = -4.0` - and also negative in the fastest, -0.181, with the `fast` bucket
*positive* at +0.106. eurusd 1h runs the other way: positive in the two quiet
buckets, negative in `fast`. The sign flips across regimes and timeframes without
order.

### How wide does it get in N bars - the useful table

The full range travelled inside the window, in volatility units. This is the
number a stop and a target actually need and it was the easiest of the four
questions to answer:

| series | N | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| eurusd 15m | 5 | 3.45 | 8.37 | 17.65 | 44.71 |
| eurusd 15m | 20 | 8.75 | 19.26 | 35.72 | 66.57 |
| eurusd 15m | 50 | 15.57 | 31.70 | 58.43 | 88.95 |
| eurusd 1h | 50 | 20.07 | 37.48 | 62.33 | 127.40 |
| eurusd 4h | 50 | 19.99 | 37.29 | 62.39 | 90.06 |

**A trade held 50 bars on eurusd 15m sits through 15.6 volatility units of
wandering at the median and 58 at the 99th percentile.** Against that, the
scalper strategies' `max_against_vol = 1.5` and `trail_vol = 0.5` are sized for
a completely different horizon - which is consistent, since those are scalps,
and is worth having written down the moment anyone proposes holding one longer.

The range grows faster than `sqrt(N)`: the ratio runs 1.54, 1.96, 2.20 at 15m
across N of 5, 20, 50. A random walk's expected range is about `1.6*sqrt(N)`
times the per-step size, so 15m is near that and the longer timeframes sit
above it.

### What this says about the proposal

**Invert the slope: no.** The fades either vanish under the overlap correction or
are the size of the spread. The direction that survives is **follow**, which is
consistent with the diffusion measurement that preceded it - this series travels
at 1.00 to 1.07 times a `sqrt(h)` walk, faintly *trending*, and a fade wants the
opposite.

**Forecast volatility: yes, and it was never the doubtful half.** Speed predicts
the next move's size with a 3.12x spread at one bar and 2.03x at fifty, which is
what makes `1/sigma` sizing and the overstretch ratio meaningful.

**One-to-two weeks: on daily bars it is the 5-10 bar lookback**, which is where
following works. On 15m it is 480-960 bars, where the apparent effect was the
overlap artefact.

## Deliberate lookahead: the machinery works, and 87% of the volatility is on the table

`research/ideas/lookahead_oracle.py`, 2026-10-11. Asked for as a diagnostic, and
it is the right one: every null result so far has two explanations that the
measurements cannot separate - **there is no signal**, or **the models cannot use
it**. Handing them the future on purpose separates them.

### 1. Given the answer, the models report it. The machinery is sound.

The leak dial feeds a member `k` bars past the decision point before asking it to
forecast `h` ahead. RMSE, eurusd:

| h | leak=0 | leak=1 | leak=2 | leak=5 | leak=20 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 20 (15m) | 7.28 | 7.11 | 6.94 | 6.38 | **0.99** |
| 20 (1h) | 9.34 | 9.09 | 8.83 | 8.09 | **0.51** |
| 20 (1d) | 7.12 | 6.95 | 6.79 | 6.25 | **0.01** |

**The error collapses exactly when the leak reaches the horizon** - when the
member has seen the bar it is being asked about - and it collapses to 0.01 on
daily bars. Beyond that it rises again, because the state has moved past the
target. So the filters can represent and report the value when they have it: the
null results are **not** a broken implementation.

### 2. Perfect direction is worth 7 to 800 spreads. Cost is not the constraint.

The ceiling on any directional strategy, as a multiple of the spread it would
pay:

| series | h=1 | h=5 | h=20 |
| --- | ---: | ---: | ---: |
| eurusd 15m | 7.2 | 15.5 | 31.9 |
| eurusd 1h | 29.2 | 68.2 | 143.3 |
| eurusd 1d | **174.9** | **411.5** | **798.3** |
| v75 15m | 2.3 | 5.2 | 10.5 |

**This reframes every "inside the spread" conclusion in this file.** The effects
found were spread-sized; the *prize* is 7 to 800 times the spread. So the honest
statement is not "nothing is worth trading here" - it is **"we found nothing
worth trading, and the search is justified by a large ceiling"**. The binding
constraint is signal, not cost.

### 3. The volatility forecast captures about a tenth of what is achievable

Ranking by recent speed against ranking by the realised future move, which is
the ceiling:

| series | h | recent speed | perfect foresight | captured |
| --- | ---: | ---: | ---: | ---: |
| eurusd | 1 | 5.73x | 45.32x | **10.7%** |
| eurusd | 5 | 4.77x | 29.13x | 13.4% |
| eurusd | 20 | 4.00x | 26.15x | 11.9% |
| v75 | 1 | 1.04x | 13.65x | **0.3%** |

**This is the most actionable number in the session.** Volatility is the one
thing measured as forecastable here, and the simplest possible forecast - a
twenty-bar mean absolute move - captures roughly **an eighth** of the available
dispersion. There is a seven-to-nine-fold improvement available in the one
quantity that is known to be predictable, which is a far better place to spend
effort than another attempt at direction.

### 4. v75 has no volatility clustering, so it is the wrong control for this

Recent speed captures **0.3%** of the ceiling on v75 against 10.7% on eurusd,
while the oracle still shows 13.65x of dispersion to forecast. The generator's
volatility varies and **does not autocorrelate**.

That is useful twice over. It explains why v75 produced no slope-fade survivors -
there is no volatility structure there to be mistaken for direction. And it
disqualifies v75 as a control for volatility work: it is a control for *direction*
only, and a volatility model that fails on it is not necessarily wrong.

### The flaw in the smoother arm, which measured the wrong target

The filter-against-smoother comparison reported ratios **below 1.0** - 0.62 on
v75 1h - which reads as hindsight making the estimate worse. It cannot, and the
test is at fault: it compares each estimate to the **measurement**, and a
smoother's job is to be *further* from a noisy reading than the filter is. Being
closer to the reading is what a member that simply copies it achieves - which is
exactly what `swarm` scored, 0.056 against the reading and a 1.00x ratio.

Comparing against the latent truth is the only version that means anything, and
the truth is unobservable on real data. `paths.simulate` generates a path with
known states, so the honest form of this arm runs there. **Not fixed, recorded** -
the arm is marked in the harness as measuring the wrong quantity rather than
left to be read as a result.
