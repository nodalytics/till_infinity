# Trading against a live higher timeframe costs 2.5 to 4.1 points, on two rungs out of nine

A 15m long on `jump_10_index` was stopped for **-18.26** on 2026-09-10 while the
4h was calling *down* with p=0.79 and an expected push of -2.37v. One trade
settles nothing, but it names a question the record can answer: when a fine
timeframe disagrees with a coarse one that is still live, does the fine call do
worse?

Run over **72,070 directional calls across 21 days**, joined to the 171,596
decisive outcomes attached to them.
`research/harness/against.py` is the harness.

Each call is put in one of three buckets by what a *coarser* rung was saying at
the time, where a call stands for an hour - the same `CHANGE_WINDOW` that
`engine.changing` uses, and for the reason `agreeing.md` gives: letting each
timeframe stand for its own bar length makes agreement a fact about the fastest
clock rather than about the market.

* **aligned** - a coarser call in the same direction was live
* **opposed** - a coarser call in the opposite direction was live
* **none** - no coarser call was live

## The pooled answer is wrong, and wrong in an instructive way

| bucket | touches | held |
| --- | --- | --- |
| aligned | 8,323 | 82.4% |
| **none** | 17,912 | **85.1%** |
| opposed | 7,406 | 81.2% |

Read as it stands, this says agreement *hurts* - `none` beats `aligned` by 2.7
points - and that having any coarse call at all is the bad sign.

**It is Simpson's paradox, and this is the third time this project has been
caught by it.** `none` is heavily over-represented on the coarse rungs (at 5m
there are 5,177 `none` against 1,210 `aligned`), and coarse rungs hold better
regardless of agreement. Pooling therefore smuggles the interval effect in
wearing the agreement effect's clothes.

The breakdown below exists in the harness for exactly this reason, written
before the numbers were seen. That is the only defence that works: the previous
two instances were both caught after a conclusion had been written down.

## Holding the interval fixed

| interval | aligned | none | opposed | aligned − opposed |
| --- | --- | --- | --- | --- |
| 1m | 79.6% (5,065) | 79.3% (6,725) | 79.7% (4,922) | **+0.0** |
| 3m | 83.6% (1,681) | 82.8% (2,985) | 81.1% (1,337) | **+2.5** |
| 5m | 88.7% (1,210) | 87.0% (5,177) | 84.6% (915) | **+4.1** |
| 15m | 94.2% (274) | 95.3% (1,620) | 97.1% (172) | **-2.9** |
| 30m+ | too few in the outer buckets to report | | | |

Three different answers on three parts of the ladder.

**1m: nothing.** 79.6 against 79.7 on nearly seventeen thousand touches. This is
the largest sample on the page and it is flat. Whatever the higher timeframe is
saying, a 1m level does not care.

**3m and 5m: real.** Aligned beats opposed by 2.5 and 4.1 points, and `none`
sits *between* them in both. That ordering matters more than the gap: an
"activity" effect - where merely having a coarse call live is what predicts -
would put `none` at one end. Sitting in the middle is what a genuine agreement
effect looks like.

**15m: reversed.** Opposed holds best, at 97.1%. On 172 touches, which is not
enough to believe and not enough to dismiss.

## What follows

An alignment gate is justified **at 5m and nowhere else**. At 1m it would refuse
trades for nothing; at 15m the evidence points the other way. 2.5 to 4.1 points
of held rate is worth having and is not transformative.

**Corrected 2026-09-12: 3m does not survive.** This section said "3m and 5m",
and `research/auditing.md` recomputed both rungs from this page's own counts:
3m is **z = +1.78, p = 0.074** and 5m is **z = +2.73**. The 3m rung is not
significant at the conventional bar *before* any correction for having tested
four rungs, and with one it is not close. Nothing gates on this today - the
paragraph below held it pending a split against closes - so the cost is a
recommendation that would have been acted on, not a live refusal.

Worth naming why it read as a finding: four rungs were tested and the two that
pointed the same way were reported together, which is the maximum-of-K null that
`auditing.md` finds is the one systematic gap in this folder's discipline. 5m
would survive a correction for four comparisons; 3m never cleared one.

**Held rate is not profit.** [reachable.md](reachable.md) is the standing
reminder that a level holding and a trade paying are different events, and this
measures the first. Before anything gates on it, the same split wants running
against closes rather than touches - the trading sample is a few hundred rather
than seventy thousand, which is why it is not on this page yet.

And the trade that prompted the question sits in the one bucket that argues
against the gate: it was **15m** against a 4h, and 15m is the rung where
opposing the higher timeframe did better. That is not a reason to dismiss the
finding, and it is a reason not to cite that trade as evidence for it.
