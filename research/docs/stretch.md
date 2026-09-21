# Over-stretched extremes on higher timeframes — measured 2026-09-21

By `research/harness/stretch.py`, on three separate instrument sets: the Boom/Crash synthetics,
the FX majors, and sixteen indices, crosses, energy and crypto instruments. Five timeframes,
six stretch measures, six triggers, scored by decile.

The hypothesis, in the operator's words: markets that have **stretched too long** and are
**currently stalling or trying to reject**, with the stretch belonging on higher timeframes
rather than lower ones.

**Verdict: not supported as stated, with one partial exception that does not clear its cost.**

## Why the test was set up as an ablation

The hypothesis joins two claims that are different in kind, and one already had evidence
against it.

`breakout-runs.md` measured the hazard of reversal against how long a run had lasted and found
it **steps up after two bars and is then flat** - 0.243, then 0.362, 0.365, 0.323. A flat hazard
is memorylessness: runs do not exhaust with age. "Stretched too long" is an age claim, so that
result speaks directly against it.

**Stalling and rejecting are not age claims.** They are conditions on the present bar, nothing
here had tested them, and that was the genuinely open part.

## No cutoff was chosen

"Over-stretched" needs a threshold, and picking one is how a study finds what it went looking
for. Instead each measure is converted to a **causal percentile** - rank against the previous
250 values of its own history, never the whole series - and reported per decile.

The reading is therefore whether the top deciles beat the bottom ones **monotonically**. A
single strong cell in the middle of a decile ladder is noise, and a threshold test cannot see
the difference.

## Result one: the synthetics say nothing

Boom 1000 and Crash 1000, 816 cells:

| tf | d0 | d3 | d5 | d7 | d9 |
|---|---|---|---|---|---|
| 1h | +1.01% | +0.08% | +0.02% | +0.50% | −0.56% |
| 4h | +0.84% | +0.05% | +0.07% | −0.50% | +0.32% |
| 1d | −0.74% | −0.16% | +1.65% | +0.76% | **−0.86%** |

No gradient, and on daily the **most** stretched decile is the worst of the ten. The best
single cells were `since_turn` at deciles 5 and 7 - middle of the ladder, which is the shape
noise takes.

## Result two: the FX majors say nothing, and say it clearly

xauusd, eurusd, gbpusd, usdjpy, 1501 cells:

| tf | d0 | d3 | d5 | d7 | d9 |
|---|---|---|---|---|---|
| 1h | −0.36% | −0.30% | +0.47% | −0.18% | −0.85% |
| 8h | −0.34% | −0.04% | +0.49% | +0.69% | −1.05% |
| 2d | −0.76% | −0.15% | −0.23% | +0.25% | −1.25% |

The most stretched decile is the worst on three of five timeframes. **The single best cell of
all 1501 was `from_fit` at decile 0 with trigger `none`** - the least stretched bar with no
stall and no rejection, which is the precise inverse of the hypothesis. When the top of a
sorted list of 1501 cells is the opposite of what you predicted, the list is noise.

## Result three: a real gradient on 4h and 8h, and it is not enough

Sixteen indices, crosses, energy and crypto instruments, 1536 cells. This is the one set that
points the operator's way:

| tf | d0 | d1 | d2 | d3 | d4 | d5 | d6 | d7 | d8 | d9 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1h | −1.02% | −0.24% | −0.60% | −0.29% | −0.39% | −0.03% | +0.08% | −0.09% | −0.33% | −0.41% |
| 4h | −0.61% | −0.23% | −0.14% | −0.04% | +0.07% | +0.05% | −0.11% | **+0.75%** | +0.39% | +0.13% |
| 8h | −1.40% | −0.69% | −1.04% | −0.45% | −0.28% | −0.18% | +0.40% | **+0.94%** | +0.23% | −0.11% |
| 1d | +0.33% | −0.38% | −1.92% | −1.21% | −1.06% | −0.14% | −0.41% | +0.31% | −0.18% | +0.46% |

Two things here are worth taking seriously.

**The 4h and 8h ladders rise**, roughly monotonically from d0 to d7, by +1.4 and +2.3 points
respectively. That is the shape the hypothesis predicts, and it is the only place in three runs
where it appears.

**1h is uniformly negative on every decile**, in this set and in both others. So the operator's
specific claim that *the stretch belongs on higher timeframes and not lower ones* is the part
that holds up best - 1h genuinely behaves differently from 4h and 8h here.

What stops it being a result:

* **d9 falls back** on both 4h and 8h. A real exhaustion effect should be strongest at the
  extreme, not peak at the eighth decile and decline.
* **1d and 2d are U-shaped**, with both ends positive and the middle deeply negative
  (−1.92% and −2.20% at d2). That is a different shape from the 4h/8h ladder, and a mechanism
  that reverses sign between 8h and 1d is not a mechanism.
* **1536 cells means about 77 clear a two-sigma bar by chance**, which is roughly how many did.
* **The gradient is below the cost hurdle**, which is the decisive objection.

## The cost hurdle, which settles it

With stop and target both one true range, charging the measured live slippage of 0.063 TR on
losers and 0.020 TR of spread, the break-even hit rate is

    p (1) - (1 - p)(1.063) - 0.020 = 0    ->    p = 1.083 / 2.063 = 52.5%

The unconditional counter-trend trade sits near 50%, so a cell needs about **+2.5 points of
excess** to pay for itself. The 4h/8h decile gradient tops out at +0.94 points. **It is a
third of what it needs**, before any allowance for having searched 1536 cells to find it.

Individual top cells do print 53.6-54.1% and are therefore net positive as printed - but those
are the extreme of a sorted list of 1536, and the decile means are what the gradient argument
rests on.

## What this leaves

* **"Stretched too long" is not supported.** `since_turn`, the direct measure of duration, shows
  no gradient anywhere, which is consistent with the flat reversal hazard in
  `breakout-runs.md`. That result now holds for daily and two-day extremes as well as hourly
  ones.
* **"Stalling or rejecting" is not supported either.** No trigger beat `all` consistently, and
  in the FX set the best cell carried trigger `none`.
* **"On higher timeframes, not lower" is the part with support.** 1h is worse than 4h and 8h in
  all three runs. That is a real difference in behaviour and worth remembering, but it is a
  statement about where an effect would be if there were one.
* **Nothing goes to the structures or trading service.** The operator asked whether this applies
  to both; on this evidence it applies to neither, and shipping a 0.94-point gradient against a
  2.5-point hurdle would lose money with extra steps.

## What would change the answer

The 4h/8h gradient is the only live thread and it is underpowered rather than refuted. Two
things would settle it, in order of value:

* **Hold out the instruments.** The gradient appeared in one of three sets. Splitting the
  sixteen into halves and asking whether the ladder survives on the half not used to find it is
  a stronger test than any resampling, and costs one run.
* **Score the gradient itself, not its cells.** The honest statistic is the rank correlation
  between decile and excess, bootstrapped over instruments, which gives one number per
  timeframe instead of 1536 comparisons. That is what should have been computed first, and it
  is the change to make before this is run again.
