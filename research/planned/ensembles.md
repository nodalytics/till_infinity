# Ensembles — not built

**Status: designed, not built.** Nothing in this document exists in the code.

The operator's point, and it is the right one: *individual signals might be weak but the
ensemble of them might be strong.* This sets out when that is true, when it is wishful, and
why - after `power-and-sizing.md` - it is now the single best experiment available here.

## Why this is the natural successor to the power audit

`power-and-sizing.md` graded fifteen studies against the effect each could have detected. Seven
were **blind**: their smallest detectable effect exceeded the cost hurdle, so a real edge of the
size that would matter was invisible to them.

| study | n/cell | cells | detection floor | hurdle |
|---|---|---|---|---|
| regression_channel | 2,673 | 144 | 4.27% | 1.99% |
| smc, sweep | 1,500 | 18 | 4.95% | 1.99% |
| displacement, ALL THREE | 1,200 | 8 | 5.16% | 1.99% |
| changepoint, spike alone | 1,266 | 7 | 4.96% | 1.62% |
| stretch, typical cell | 800 | 1536 | 8.83% | 1.99% |
| stopfree, fade ON spike | 247 | 300 | 14.66% | 1.62% |

**Their nulls do not mean those signals are zero.** They mean nobody looked hard enough. An
ensemble attacks exactly that, and it does so twice over:

* **one hypothesis instead of many.** Testing a single combined score is one comparison, so the
  Bonferroni inflation disappears. `stretch.py` paid a factor of 1.73 on its detection floor for
  1536 cells before any data existed; an ensemble pays nothing.
* **every bar is a sample.** A conjunction rule fires rarely - `displacement`'s three-condition
  cell had 1,200 trades out of hundreds of thousands. A *score* is defined on every bar, so the
  sample is the whole series rather than the intersection.

Together those take the detection floor from 5-15 points down to under 1, which is below the
hurdle for the first time.

## When ensembling works, and when it cannot

The honest arithmetic, because this idea is easy to oversell.

Averaging `k` signals with mean `mu` each and pairwise correlation `rho` gives a mean of `mu`
and a standard error scaled by `sqrt((1 + (k-1) rho) / k)`. So:

* **it raises the signal-to-noise ratio, not the mean.** An ensemble of `k` signals each with a
  true mean of zero has a true mean of zero. Combining nothing yields nothing, however many
  times it is combined.
* **the gain is `sqrt(k)` only when the signals are independent.** At `rho = 0.5` and `k = 8`
  the effective count is 1.87, not 8. Correlated signals barely help, and most of the
  candidates here read the same price series through similar windows.
* **so correlation must be measured before combining, not after.** A pairwise correlation matrix
  of the candidate signals is the first output, and any pair above about 0.7 contributes one
  signal between them.

**The distinction that decides whether this is worth running.** A measured mean of zero on a
*well-powered* study is a real zero and ensembling it is pointless. A measured mean of zero on a
*blind* study is an absence of evidence, and ensembling is the right response. So the ensemble
is built **only from the underpowered candidates**, and deliberately excludes the signals that
were measured properly and found flat - gaps as levels, premium/discount, chart patterns - since
those contribute known zeros and would dilute.

## What to combine

Candidates, each already implemented and each individually underpowered or marginal:

| signal | source | direction it points |
|---|---|---|
| spike fade | `changepoint.py` | against a detected jump |
| displacement conjunction | `displacement.py` | with the move |
| liquidity sweep | `smc.py` | against the sweep |
| break of structure | `smc.py` | with the break |
| order block return | `smc.py` | with the block |
| channel revert | `regression_channel.py` | to the line |
| stretch decile on 4h/8h | `stretch.py` | against the stretch |
| two-bar momentum persistence | `breakout-runs.md` | with the break, briefly |

The last is the only one in the list with a *well-measured* positive: the reversal hazard steps
from 0.243 to 0.362 after two bars, so a fresh break is genuinely less likely to fail
immediately. It belongs in the ensemble as the one component that is known not to be zero.

## How to combine — three, in increasing order of how much they can fool you

**Sum of signs.** Each signal votes -1, 0 or +1; the score is the sum. No fitting at all, so
nothing to overfit and no train/test split needed for the combination itself. This is the
version to run first, and if it fails there is nothing here.

**Inverse-variance weights.** Each signal weighted by `1 / variance` of its own excess,
estimated on the training fold only. One parameter per signal, all of them estimated causally.

**A learned combiner.** Logistic regression or a shallow tree on the signal vector, inside the
existing purged walk-forward with embargo from `splits.py`. This is the one that can fool you:
`k` signals plus a learner is `k` free parameters against a hurdle of two points, and the
block-shuffled null from `splits.block_shuffle` is what keeps it honest.

**Run them in that order and stop at the first that fails.** If sum-of-signs is flat, a learner
finding something is much more likely to be fitting than finding.

## What would count as a result

The same bar every other study here has had to clear, and no lower:

* stop and target one true range apart, so fair odds is 50% and no geometry can explain it;
* the measured costs charged - **0.063 TR of slippage** from 305 live fills and the spread from
  `spread_cost.py` - giving a break-even of 52.0% on FX and 51.6% on the synthetics;
* purged, embargoed walk-forward, scored against the block-shuffled null;
* **the minimum detectable effect computed and stated before the run**, which is the discipline
  `power.py` exists to enforce and which nothing here has previously done.

And one test specific to ensembles: **the score must be monotone in the outcome.** If the top
decile of the score beats the bottom decile and the deciles in between line up, that is an
ensemble. If only the extreme decile separates, it is one signal wearing seven coats, and the
correlation matrix will say which.

## Why it might still fail, stated in advance

The costs are 0.08 TR and the individual effects, where they exist at all, are 0.03 TR or
smaller. Ensembling `k` independent signals multiplies the *t-statistic* by `sqrt(k)` but leaves
the per-trade expectancy where it was. **A stronger claim of significance is not more money.**
Eight independent signals each worth +0.5 points combine to about +1.4 points at best, which is
still under the 2.0-point hurdle on FX.

So the realistic outcome is a statistically clear signal that does not pay, and the run should
be designed to report expectancy net of cost as the headline rather than a p-value. If it
reports a t-statistic and buries the expectancy, it has been written to flatter itself.
