# Sequential volatility, and whether a pull origin can be called

**Measured 2026-11-17.** Five majors (EURUSD, GBPUSD, GOLD, USDJPY, AUDUSD) at
1h and 15m, 8 years, plus four Deriv synthetics at 1h. Harness:
[`research/ideas/persistence.py`](../ideas/persistence.py), grid in
[`persistence_run.py`](../ideas/persistence_run.py).

Three operator questions, measured on one machine because they are one question
with three labels - **does motion persist**.

| question | answer |
|---|---|
| can we predict **sequential volatility** - the next N candles moving with no or very little stalling? | **yes.** AUC **0.8886** within volatility strata at 15m, **0.6920** at 1h. Most of it on real markets is the session clock - inside the hour of day it falls to **0.6588**, or **0.7260** for the no-stall-at-all version - and on `Volatility 75`, which has no session, the recent-activity terms alone read **0.8522** |
| can we predict when a **pull origin** is about to reverse? | **no, beyond the arithmetic of the target.** The incumbent reads **0.7461 to 0.7596** within strata on 5 of 5 markets and the candle, approach, wick, path and hour add **nothing** - `full - base` is negative on 2 of 5 and positive on 0 of 5 |
| the **round trip**: price returns to the origin, does it bounce back to where it returned from? | **no, and it is slightly worse than fair.** It returns **64 to 68%** of the time, and from the return it reaches the old extreme **0.2049 to 0.2338** against a fair **0.2162 to 0.2524** - below fair on 5 of 5 |

**And the biggest finding of the day is a measurement fault, not a market
fact.** Candle geometry read a **+0.15 AUC lift** over a volatility-only
incumbent on the pull question. It was the label's own arithmetic. That is
written up in [CLAUDE.md](../../CLAUDE.md#put-the-labels-own-arithmetic-in-the-incumbent)
and in the `finding-edges` skill, because it will happen again.

## Question 1: contiguous activity

A window is **continuous** when no more than `--allowed` of the next 16 bars
has a true range under `--stall` of the bar's own ATR. Defaults: one stalled
bar allowed, a stall is under half an ATR.

**That is deliberately not the same question as
[`expansion.md`](expansion.md).** Expansion calls volatility *expansion* from
compression at AUC 0.781 - the **sum** over a window. A window holding one
three-ATR bar and fifteen dead ones sums the same as one that moves on every
bar, and only the second is tradable, so this label is about the **longest
stalled run** and not the total.

Rows are taken every 16 bars, so no two forward windows overlap:
`overlapping-outcome-windows-leak` measured a direction AUC of 0.79 collapsing
to 0.51 once the windows stopped sharing outcomes.

### Four feature sets, and what separates them

| set | what is in it |
|---|---|
| `base` | the ATR quantile and ATR(30)/ATR(480) - the volatility level alone |
| `memory` | the last 16 bars' stalls, longest stalled run, travel, path efficiency, range dispersion and the last bar's range |
| `clock` | `base` plus the hour as a sine and cosine, and the weekday |
| `full` | all of it |

15m, pooled, **61,233 non-overlapping rows**, base rate 0.6122, tested on the
later half of the sample with the earlier half purged by the horizon:

| set | AUC | within volatility strata | within the hour of day |
|---|---:|---:|---:|
| `base` | 0.6627 | 0.5549 | 0.5956 |
| `memory` | 0.6985 | 0.7067 | **0.6121** |
| `clock` | 0.8873 | 0.8734 | **0.6456** |
| `full` | 0.8997 | **0.8886** | **0.6588** |

The permuted floor is **+/-0.0029 to +/-0.0070**, so none of this is sample
noise. `full - base` within strata is `[+0.3271, +0.3400]` on a day-block
bootstrap.

**The volatility level is not the predictor and the clock is.** `base` within
strata is 0.5549 - almost nothing, which is the whole point of measuring within
strata: pooled it reads 0.6627 and that difference is the definition at work,
since "no bar under half an ATR" is easier when the ATR is low.
`auc-is-free-on-volatility-targets` is the same lesson with a number on it:
0.805 pooled on a constant-volatility process against 0.525 within strata.

**Within the hour the answer is 0.659, and that is the number to carry.** The
clock and the memory terms are two readings of the same diurnal activity cycle;
on the real series the hour alone gets 0.873 and the memory terms add 0.015 on
top of it. What survives cutting inside the hour is real and large, and it is
the part that says something a calendar does not.

At 1h the same ladder reads `base` 0.5124, `clock` 0.6615, `full` 0.6920 within
strata on 15,194 rows - weaker, which is consistent with a diurnal mechanism:
one 1h bar spans a twelfth of the usable session where one 15m bar spans a
forty-eighth.

**And the strictest version of the question is the most predictable.** With
`--allowed 0` - no stalled bar at all in the next sixteen, which is the
operator's "no stalling" read literally - the pooled 15m figures are `base`
0.5439, `memory` 0.7365, `clock` 0.8577, `full` **0.8745** within volatility
strata and **0.7260 within the hour**, against 0.6588 for the one-stall
version on the same rows. Requiring every bar to move makes the label harder
(base rate 0.3668 against 0.6122) and the forecast better.

### The synthetics, and the control that reads nothing

| feed | base rate | `base` | `memory` | `clock` | `full` | `full` within the hour |
|---|---:|---:|---:|---:|---:|---:|
| Volatility 75 | 0.5235 | 0.5257 | **0.8522** | 0.5812 | **0.8814** | **0.8587** |
| Boom 1000 | 0.8945 | 0.6080 | 0.6211 | 0.6181 | 0.6860 | 0.7736 |
| Crash 1000 | 0.8097 | 0.5617 | 0.6466 | 0.5706 | 0.6840 | 0.7662 |
| Step Index | **0.9994** | - | - | - | - | - |

Three things fall out, and together they are the strongest evidence on this
page.

**Step Index reads nothing, by refusing to produce a number.** Deriv generates
it with a fixed step, so **99.94%** of its windows are continuous, the label
has no negative class, and every AUC comes back undefined. A harness that
manufactured a figure there would have been manufacturing it everywhere;
`clocks-must-pass-an-iid-control` records range time inventing clustering at
5.3x on a specified process, which is what this arm exists to catch. It also
confirms the label measures what it claims: a process with literally constant
activity scores 1.0.

**Volatility 75 is the clean demonstration, because it has no session.** Its
`clock` set reads 0.5812 and cutting inside the hour costs **nothing** -
0.8814 to 0.8587 - where the same cut on real FX takes 0.8886 to 0.6588. So
on a market with no diurnal cycle the activity-persistence reading stands on
its own at **0.8522 from the memory terms alone**, with the volatility level
contributing 0.5257. That is contiguity being forecast from contiguity, with
no calendar underneath it.

**And the synthetics' within-hour figures are *higher* than their within-strata
figures**, which is the same fact from the other side: there is no hour effect
to remove, so stratifying on it only costs sample. The real markets are the
only ones where that cut bites, and that is how we know what the 0.886 was.

### Where the day shuffle stops being a null

The day-block shuffle reorders whole days and keeps every bar's shape, which is
the right null for a level or a sequence rule. **For continuity at 15m it is
not a null at all**, and the measurement says so: on shuffled bars `memory`
reads **0.7854 within the hour** against the real arm's 0.6121, and `full`
reads 0.8073 against 0.6588. The shuffled market is the *more* predictable one.

Two reasons, both structural:

* the backward and forward windows are 16 bars either side of a decision inside
  a **96-bar preserved day**, so the shuffle barely perturbs the quantity;
* `shuffled` keeps the original timestamps while the prices come from a
  reordered day, so the hour is **decoupled** - which removes a confound rather
  than an effect, and leaves the within-day activity autocorrelation visible
  without the diurnal cycle on top of it.

So it is reported and not used as a verdict. `microscope.py` documents the same
limit for the same reason, and the arms that do decide this one are the
within-hour cut and the Step Index.

## Question 2: the pull origin

The operator's detector, supplied verbatim (bullish; bearish is the mirror):

1. **a real low** - the candle's low is the lowest of the 15 candles before it;
2. **price fell into it** - at least 1.5 ATR within the previous 24 candles;
3. **a strong move away** - within the next 24 candles price rises at least
   3 ATR from that low without going below it;
4. **the rise is directional** - it covers a good share of its own
   back-and-forth, or it includes a big strong-bodied displacement candle.

**Clauses 1 and 2 hold at the candle's close; 3 and 4 are the forward
confirmation**, which is why the supplied note says it confirms five or six
candles later. So the prediction question has an exact form: on the candidates
that clauses 1 and 2 define, can anything call clauses 3 and 4?

That universe matters. [`turns-fast.md`](turns-fast.md)'s better-looking first
attempt scored 0.66 with a gate that kept **94.1% of bars**, which is the
series and not a comparison set. Here the gate keeps a pivot with a hard
approach, and **16.1 to 18.2%** of those go on to make the 3 ATR rise.

**Clause 4 is nearly inert at these settings**: it rejects a further **2.75 to
3.33 percentage points** of the 16-18% that clause 3 passes. The directional
test is not what makes the detector selective; the 3 ATR rise is.

### The incumbent is the target's own arithmetic

At the decision bar price is at the candle's **close**, which is already above
the low. Call that distance the **cushion**; `remaining = 3 - cushion` is how
much of the target is left, and it needs no information about the future.

| reading, alone | AUC | within strata |
|---|---:|---:|
| `cushion` | **0.7648** | 0.7645 |
| `reject_wick` | 0.6530 | 0.6536 |
| `bar_size` | 0.6283 | 0.6269 |
| `pivot_strength` | 0.5365 | 0.5352 |
| `approach` (clause 2 as a size) | 0.5280 | 0.5245 |
| `past_travel` | 0.5385 | 0.5330 |
| `atr_q` | 0.5205 | 0.5285 |
| `close_in_range` | 0.4801 | 0.4805 |
| `past_efficiency` | 0.4299 | 0.4271 |

The long lower wick and the big bar are **cushion in disguise**: both mean the
candle closed a long way off its own low.

With `cushion` and `remaining` in the baseline, 8 years and five markets:

| market | `base` within strata | `full - base`, day-block 90% |
|---|---:|---:|
| EURUSD | 0.7558 | `[-0.0039, +0.0095]` |
| GBPUSD | 0.7461 | `[-0.0119, +0.0025]` |
| GOLD | 0.7596 | `[-0.0103, +0.0035]` |
| USDJPY | 0.7567 | `[-0.0196, -0.0026]` |
| AUDUSD | 0.7488 | `[-0.0154, -0.0003]` |

**Nought of five positive, two of five negative.** The candle shape, the
approach and its efficiency, the pivot strength, the rejection wick, the
position in the range, the distance to a round number, the recent path and the
hour, together, are worth less than nothing once the arithmetic is accounted
for.

### Where this goes blind

A null is worth nothing without a size, so an effect of known strength is
planted **on the columns `base` cannot see** - the candle, the approach, the
path, the position - as a readable function of a fixed random direction,
governing a given share of the rows. Pooled over the five markets, 32,005 test
rows:

| share of rows the planted effect governs | `full - base` within strata, day-block 90% |
|---:|---:|
| 0.00 | `[-0.0018, +0.0008]` |
| 0.02 | `[-0.0027, +0.0008]` |
| 0.05 | `[+0.0007, +0.0061]` |
| 0.10 | `[+0.0101, +0.0169]` |
| 0.20 | `[+0.0433, +0.0509]` |

So the null has a resolution: **an effect governing 2% of candidates is
invisible here, 5% is exactly at the threshold, and 10% is seen clearly.**
Pooled, that is - the per-instrument intervals are about six times wider
(`[-0.0196, -0.0026]` and the like), so one market alone would need something
nearer 20%.

What the measured nulls say, then, is not that the candle and the approach
carry nothing. It is that whatever they carry governs **under one candidate in
twenty**, and at that frequency it is both invisible to this harness and
marginal against a spread of 0.011 to 0.041 ATR.

On the continuity side the same plant barely registers - `[+0.3271, +0.3400]`
unplanted against `[+0.3347, +0.3459]` at a 20% plant - which is what a plant
does when the real effect already dominates it.

### And the thing that predicts it is the thing you pay for it

The cushion is the **risk**: a stop sits beyond the origin, so entering at the
close risks the distance already travelled. Gross, entering at the candidate's
close with the stop 0.25 ATR past the origin and the target where clause 3 puts
it:

| market | rows | mean R | day-block 90% | hit | fair |
|---|---:|---:|---:|---:|---:|
| EURUSD | 12,847 | +0.0361 | `[-0.0018, +0.0789]` | 0.2429 | 0.2404 |
| GBPUSD | 13,162 | -0.0101 | `[-0.0478, +0.0256]` | 0.2297 | 0.2359 |
| GOLD | 11,616 | -0.0517 | `[-0.0928, -0.0127]` | 0.2305 | 0.2445 |
| USDJPY | 12,260 | -0.0275 | `[-0.0642, +0.0103]` | 0.2226 | 0.2312 |
| AUDUSD | 13,167 | +0.0251 | `[-0.0132, +0.0624]` | 0.2228 | 0.2209 |

Fair here is `1/(1+N)` at each row's own reward-to-risk. The hit rate tracks it
within 0.014 everywhere, which is what a cushion buying its own probability
looks like. **Before costs**, which is the operator's standing instruction: a
rule with no side gross cannot have one net, and the median 15m spread on these
instruments is 0.011 to 0.041 ATR against risks of 0.25 to 1 ATR here.

## Question 3: the round trip

Of confirmed origins, how often does price come back to the origin, and from
there go back to the extreme it came from?

| market | confirmed | returned | median bars | closed past the stop | bounced | fair | taking it, R |
|---|---:|---:|---:|---:|---:|---:|---:|
| EURUSD | 1,960 | 0.6837 | 20 | 323 | 0.2301 | 0.2411 | -0.0420 |
| GBPUSD | 1,911 | 0.6719 | 21 | 313 | 0.2070 | 0.2382 | **-0.1658** |
| GOLD | 1,673 | 0.6432 | 21 | 261 | 0.2307 | 0.2524 | **-0.1295** |
| USDJPY | 1,696 | 0.6533 | 20 | 291 | 0.2338 | 0.2404 | -0.0790 |
| AUDUSD | 1,750 | 0.6646 | 22 | 265 | 0.2049 | 0.2162 | - |

**Below fair on five of five**, by 0.007 to 0.031, and negative in R on every
market with two intervals clear of zero. `a-return-rate-is-geometry` is the
standing result this agrees with: the 82% return rate that began the
fade-to-value family was matched by a distance-matched placebo on every asset
class, and a walk read 0.825.

**One in five returns is not a trade.** 261 to 323 of each market's returns -
about 22% - close *beyond* a stop a quarter-ATR behind the origin on the very
bar that touches it. Those are counted and dropped: scoring them divides a
three-ATR reward by a risk of almost nothing, and one row then carries an
instrument.

## Six faults found on the way, each bigger than any effect here

Written up in full in the `finding-edges` skill under *Race labels, and six
ways the accounting lies*. None was a coding error; all six were design faults
in the mapping from a trade to a number - four in the market measurement, two
in the power curve that was supposed to bound it.

1. **The label's arithmetic outside the incumbent** - candle geometry at +0.15
   AUC, which became a negative lift once `cushion` joined the baseline.
2. **A timeout scored as a stop** - read **-0.3440R** a trade where marking out
   at the window's close reads **+0.0309R**. Only 1.6% of rows timed out, but
   they averaged **+2.04R**.
3. **A control that was a copy** - a padded stop a quarter-ATR below an origin
   that the clause loop `break`s at is unreachable, so the padded arm was
   bit-identical to the unpadded one and read as perfect agreement.
4. **An entry already past its own stop** - 22% of returns, above.
5. **A power curve planted on the baseline's own columns** - the planted
   direction spanned the whole feature set, so both arms rose together and the
   difference under test stayed flat at every strength.
6. **A model fitted on one label and scored against another** - the planted
   sweep's interval was computed against the real label. At a plant governing
   20% of rows the AUCs read `base` 0.7008 and `full` 0.7466 while the interval
   printed `[-0.0481, -0.0258]`. Invisible at plant 0, so no published figure
   moved; the *power curve* was wrong in the direction that flatters a null.

## What this closes, and what it does not

**Closed:** that the operator's pull-origin confirmation can be called from the
candle, the approach or the clock beyond the distance already covered; that the
return to an origin bounces back at better than fair odds; that either is
tradable gross at this geometry.

**Open and measured positive:** contiguous activity over the next sixteen bars,
at **0.6588 within the hour of day** and 0.8886 within volatility strata. It
carries no side - it says *whether* the next sixteen bars will move, not where
- so what it is for is the clock on a trade: whether a target is reachable in
the time a desk is willing to hold, which is the quantity
[`hold-clock.md`](hold-clock.md) could not forecast and
[`structural-target.md`](structural-target.md) found a target cannot fix.

**Not attempted:** pricing the continuity forecast as a gate on an existing
rule. That is a duty-cycle question and `vol-gate.md` is explicit about the
trap - a volatility gate beat its same-keep-rate twin in 2,314 of 6,912 cells
while the day-shuffled walk beat its own twin in 2,544 of the same 6,912.
