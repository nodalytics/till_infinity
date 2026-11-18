# RSI and moving averages crossed with momentum, over one week

**Measured 2026-11-18**, asked for directly: *"give me rsi + momentum
combinations from 1m-15m that has worked in the last 7 days"*, then the same
for moving averages. Harness:
[`research/ideas/rsi_momentum.py`](../ideas/rsi_momentum.py).

| | answer |
|---|---|
| what led | **trend confirmation at 2R** - `ma_trend`, `ma_pullback` and `trend_confirmed` take the whole top ten at 15m, at **+0.2365 to +0.3171R** net on 184 to 313 trades, t +2.75 to +3.27 |
| did it work | **no.** **Nought of the top ten** was positive in the preceding 30 days; every one read **-0.0293 to -0.0759R** there, on four to five times the sample |
| against chance | **the grid loses to its own shuffle.** The best single-market cell on day-shuffled bars reads **+0.5679R** at 15m and **+0.6689R** at 5m, against real pooled leaders of +0.3171 and +0.1690 |
| the 1m end | **not measurable here.** The deep catalogue is 5-minute; the production store holds under six days of 1m and is gated; the lab was refusing SSH. 5m is the finest clock below |

## What was run

414 cells. Two families, each with four readings and both sides:

    oversold_falling   RSI below the threshold while momentum is still negative
    oversold_turning   RSI below it while momentum has turned up - a divergence
    trend_confirmed    RSI above 50 and momentum positive
    trend_pullback     RSI below 50 and momentum positive - a dip in an uptrend

    ma_trend           close above the average, momentum positive
    ma_pullback        close above it, momentum negative - a dip while above
    ma_cross           a **fresh** fast-over-slow cross, momentum agreeing
    ma_stretch         price `k` ATR from the average, momentum turning back

RSI 7/14/21, averages 20/50/100 with the fast line a quarter of the slow,
momentum over 5/10/20 bars **in ATR**, thresholds 20/25/30/35, stretch
1.0-2.5 ATR, reward 1R and 2R on a 1 ATR stop, 48 bars of patience. Five
majors, 5m and 15m.

Exit is a barrier race, the near barrier charged when one bar touches both.
**Signals that fire while a race is open are skipped**, so no two outcome
windows share a bar - `overlapping-outcome-windows-leak` measured a direction
AUC of 0.79 collapsing to 0.51 once they stopped sharing outcomes. Cost is one
spread charged in R as `spread / stop distance`, from the median recorded
spread per feed: 2 points on EURUSD, 15 on gold, never pooled.

**`ma_pullback`, `ma_trend` and `ma_cross` do not read the stretch**, so
sweeping it for them produced four bit-identical copies of every cell. The
first run of this grid did that, which quadrupled it and filled the leaderboard
with the same row four times. Only `ma_stretch` varies it now.

## The ranking, 15m, pooled over five markets

| combination | n | net R | t | prior n | prior net R |
|---|---:|---:|---:|---:|---:|
| `ma_pullback` ma50 mom5 R2 | 184 | **+0.3171** | +2.91 | 914 | -0.0293 |
| `ma_pullback` ma100 mom5 R2 | 198 | +0.2969 | +2.83 | 990 | -0.0521 |
| `ma_trend` ma50 mom5 R2 | 295 | +0.2821 | +3.27 | 1,378 | -0.0669 |
| `trend_confirmed` rsi21 mom5 25 R2 | 275 | +0.2799 | +3.13 | 1,394 | -0.0694 |
| `trend_confirmed` rsi21 mom20 25 R2 | 291 | +0.2736 | +3.16 | 1,474 | -0.0718 |
| `trend_confirmed` rsi21 mom5 20 R2 | 295 | +0.2718 | +3.15 | 1,414 | -0.0724 |
| `ma_trend` ma100 mom20 R2 | 301 | +0.2701 | +3.17 | 1,345 | -0.0582 |
| `ma_trend` ma50 mom20 R2 | 313 | +0.2488 | +2.98 | 1,480 | -0.0759 |
| `trend_confirmed` rsi21 mom20 20 R2 | 311 | +0.2472 | +2.95 | 1,487 | -0.0702 |
| `ma_trend` ma100 mom5 R2 | 294 | +0.2365 | +2.75 | 1,276 | -0.0366 |

Every leader is a **trend-confirmation** reading at **2R**, and the two
families agree: `ma_trend` and `trend_confirmed` are the same rule written
twice, and both are in there because that agreement is the finding. The week
trended, so a rule that buys strength and holds for two units of risk paid.

**And the right-hand columns are the answer to the question as asked.** "Has
worked" is a claim about the future and the only cheap test of it is the past
window: on the thirty days before, with four to five times the trades, all ten
lose. `strategy-switching.md` is the same shape at the strategy level - no
pause rule tested here beat its own random twin.

## The ranking, 5m, pooled

Weaker, and only one cell clears a t of 2:

| combination | n | net R | t | prior n | prior net R |
|---|---:|---:|---:|---:|---:|
| `ma_pullback` ma100 mom20 R2 | 369 | +0.1690 | +2.22 | 1,834 | -0.0407 |
| `ma_stretch` ma20 mom20 1atr R2 | 84 | +0.1456 | +0.90 | 418 | -0.0874 |
| `ma_pullback` ma100 mom10 R2 | 491 | +0.1168 | +1.77 | 2,387 | -0.0373 |
| `ma_trend` ma100 mom20 R2 | 892 | +0.0564 | +1.16 | 4,092 | -0.0814 |

Ten of ten negative in the prior window again.

## Why the grid cannot answer this, with the number attached

**The shuffled arm beats the real one.** The same 414 cells over day-shuffled
bars - whole days reordered, every bar's shape intact - give a best
single-market cell of **+0.5679R at 15m** and **+0.6689R at 5m**, with the mean
of the five markets' bests at +0.4179 and +0.5763. The real pooled leaders are
+0.3171 and +0.1690. **A reordered market's best-of-414 is larger than the real
market's**, which is what a leaderboard over a week of data is: an order
statistic.

Benjamini-Hochberg says 136 of 294 cells survive at 15m, and that number is
worth printing only to be dismissed: the cells share the same bars and many are
near-duplicates, so the p-values are nowhere near independent and BH is
anti-conservative here. The shuffled best-of-grid is the control that works.

## The cost ladder, which is the other reason to distrust the 1m end

Cost in R per trade, from the median per-feed spread on a 1 ATR stop:

| frame | cost in R | relative |
|---|---:|---:|
| 15m | 0.033 to 0.043 | 1.0x |
| 5m | 0.067 to 0.091 | **2.2x** |
| 1m | not measured | about 2x again on the same scaling |

That is `a-shorter-clock-multiplies-cost-in-r` showing up directly: the same
spread over a smaller ATR. At 15m the spread is 3 to 4% of risk and does not
decide anything; extrapolated to 1m it is around 15%, which would take a
genuine +0.15R edge down to nothing. **So the 1m end of the request is the end
where costs matter most and where this desk has the least data** - under six
days of 1m bars in the production store, and the catalogue note in
[CLAUDE.md](../../CLAUDE.md) is explicit that the store settles mechanics and
cost sensitivity and **cannot settle an edge**.

## What this closes, and what it does not

**Closed:** that a seven-day leaderboard over an RSI-or-average times momentum
grid identifies anything. Its leaders lose over the previous month on five
times the sample, and a day-shuffled market's best cell beats them.

**Not closed, and not tested here:** that trend confirmation at 2R works *when
the regime is known*. Every leader is the same rule and `a-regime-split-is-
information-not-a-verdict` is the operator's own standing position - a rule
that pays in one regime and loses in the other is a bet on the regime. What
this run says is that **last week was that regime and the month before was
not**, which is a statement about the week, not about the rule. Making it a
rule would need something observable that says which regime is on, measured
without using the week it is being tested on.

**Available cheaply if wanted:** the same grid at 1m once the lab answers, and
the leaders carried forward week by week to see how often the ranking survives
seven days - which is the duty-cycle-style control this question really wants.
