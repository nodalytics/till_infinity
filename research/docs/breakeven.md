# The payoff ratio is the binding constraint, and the trigger question is not yet answerable

Run: `python research/harness/breakeven.py --closes <closes.jsonl.gz>`

**Measured 2026-09-26** over **1,198 closed trades** from the live journal - 1,202 records,
four of them discarded for an implausible `best_r`. See `MAX_CREDIBLE_BEST_R`.

| question | answer |
| --- | --- |
| is the win rate the problem | **no** - 47.5%, and break-even needs a 1.105 payoff against 0.890 |
| what is the desk's actual expectancy | **-0.0709R per trade**, -84.9R over 1,198 trades |
| how many trades reach the 1.0R trigger | **16.9%**, so five in six get no protection at all |
| does a lower break-even trigger help | **cannot be answered from this record**, and the bound spans zero |
| why not | the journal recorded *how far* each way and not *in what order* |
| what shipped | the ordering, on the close path that was missing it |

## The desk loses, and it loses on the payoff ratio

| | |
| --- | --- |
| win rate | **47.5%** |
| mean win | **+0.617R** |
| mean loss | **-0.693R** |
| payoff ratio | **0.890**, against a break-even requirement of **1.105** |
| total | **-84.9R** |
| expectancy | **-0.0709R per trade** |

It wins nearly half its trades and still loses, because the winners are smaller than
the losers. That is a payoff problem, not a signal problem, and it is the thing worth
attacking first: no improvement in entry quality fixes a book whose winners are cut
and whose losers run.

**This corrects an earlier reading of the same question.** A sample of the 25 most
recent closes carrying a money field gave a 56.0% win rate, a 0.80 payoff and an
expectancy of **+0.0584 per trade** - a desk marginally in front. Over the full 1,198
it is 47.5%, 0.890 and **-0.0709R**. Twenty-five trades was not a sample, it was an
anecdote, and it pointed the wrong way.

## Almost no trade reaches the trigger

Break-even and scale-out both arm at **1.0R**:

| reached | trades | share |
| --- | ---: | ---: |
| 0.25R | 598 | **49.9%** |
| 0.50R | 412 | 34.4% |
| 0.75R | 287 | 24.0% |
| **1.00R** | **202** | **16.9%** |
| 1.50R | 108 | 9.0% |

Median maximum excursion is **+0.247R**. So at the production setting, **83.1% of
trades never arm any protection**, which is why the live desk showed zero stop moves
across 24 hours while naming excursions of +0.36R, -0.18R and -0.66R against a 1.00R
trigger.

**And scale-out cannot fire at all**, for a reason unrelated to the trigger: the desk
trades 0.31 lots against a 0.2 lot minimum, and 0.31 does not split into two halves
above 0.2. That explains the standing note that `scale_out_at` "has been 1.0 for the
life of this desk and not one scale-out has fired" - it is arithmetically unavailable
below about 0.4 lots, not mistuned.

## The trigger question, and why this record cannot settle it

Lowering the trigger arms more trades. The gain is exact: an armed loser exits at
zero and cannot do worse. The cost is that a winner which comes back to entry **after**
arming is scratched at zero instead of running on.

`adverse_r` bounds that cost usefully - a trade that never traded below entry cannot
be scratched by a stop sitting there - so armed winners split into untouchable and
exposed:

| trigger | armed losers | armed winners | exposed | gain | at risk | worst case | scratch% |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.25 | 208 | 390 | 326 | **+129.1** | -204.2 | -160.0 | 63% |
| 0.50 | 118 | 294 | 244 | +79.2 | -179.0 | -184.7 | 44% |
| 0.75 | 87 | 200 | 162 | +64.1 | -142.9 | -163.7 | 45% |
| 1.00 | 66 | 136 | 109 | +51.3 | -112.5 | -146.1 | 46% |
| 1.50 | 39 | 69 | 53 | +29.5 | -75.0 | -130.3 | 39% |

Against a baseline of **-84.9R**, a 0.25R trigger runs between **-160.0R and +44.2R**.
**The interval spans zero at every trigger**, so this is a null: there is no evidence
here for changing the trigger, in either direction.

The reason the bound is so wide is one number: **84% of armed winners traded below
entry at some point** (326 of 390 at 0.25R). Nearly every winner dipped. Whether
those dips came before or after the trigger armed decides the whole result, and
`best_r` and `adverse_r` are scalars over the trade's whole life - a trade that went
+1.2R, fell to -0.3R and recovered to +1.7R is indistinguishable from one that dipped
first and then ran.

**So the honest conclusion is: do not move the trigger on this evidence.**

## What shipped, and why the study was blocked by two fields

`_unattributed_context` has always carried **`best_after`** and **`worst_after`** -
seconds from the open to each extreme - with a comment stating exactly why: *"the
order is the whole question for a break-even rule: a dip before the peak is harmless,
a dip after it is the winner being cut."*

The **ordinary** close path did not carry them. So across all 1,198 closed trades,
**not one record holds either field** - the fields existed, on the fallback path used
only when no decision is on record, which almost never fires. Somebody wrote precisely
the right instrument for precisely this question and wired it to the wrong branch.

Both are now on the ordinary path. Once trades accumulate, the ordering test is a
filter rather than an assumption: a winner is a scratch candidate only when
`worst_after > best_after`, and the bound above collapses to an estimate.

Also fixed while there: `_best_at` and `_worst_at` were written on every marked tick
and popped nowhere, growing by one entry per trade for the life of the process. They
now go with `_best` and `_worst` in `_forget_path`.

## Where the deficit actually sits

Split by how each trade ended, the loss is not spread across the book:

| exit | trades | share | total R |
| --- | ---: | ---: | ---: |
| `stop` | 282 | 23.5% | **-298.7** |
| `target` | 252 | 21.0% | +214.1 |
| `hold` | 599 | **49.8%** | +15.0 |
| `stale` | 69 | 5.7% | -15.7 |

Two things follow. **The hold timer is roughly neutral** - half of all exits, +15.0R
in total - so the suspicion that it cuts winners short is not supported here. And the
whole deficit is at the stop.

Sharper still: **66 trades that reached at least 1R in front and ended at or below
zero account for -51.3R of the -84.9R total.** Five and a half percent of the trades
carry sixty percent of the loss, their median peak was +1.70R, and they are precisely
the population a break-even at 1.0R would arm. That is the prize, and it is why the
ordering fields were worth shipping rather than guessing around.

*(66 trades at -51.3R rather than 68 at -53.4R, because two carried a `best_r` above
10R - a broken input rather than a trade that went sixteen times its risk in front.
`best_r` reaches **1,771** at worst on this record, from a malformed target
`test_basket.py` already documents, and four trades exceed 10R. Since a trade is
**armed** on `best_r`, an inflated value arms one that never qualified, so
`MAX_CREDIBLE_BEST_R` excludes them throughout. It is a guard, not a rescue: every
figure on this page moved by less than a percent.)*

## What this does not say

* **Nothing here is out of sample.** It is the desk's own history scored against a
  counterfactual, on one account, over one period. A trigger chosen on it would be
  chosen on the same data it was measured on.
* **It assumes a scratched trade exits at exactly 0R.** Slippage and spread make a
  break-even exit slightly negative, so every `gain` above is a little optimistic.
* **The 0.2 lot minimum is this broker's.** The scale-out arithmetic changes on an
  account with finer granularity, and that is a venue question rather than a tuning
  one.
* **The exit split is not a counterfactual.** `stop` totalling -298.7R is where the
  losses are booked, not proof that a different stop would have booked less. A wider
  stop moves trades from `stop` into `hold`, and what they would have done there is
  not in this record.
* **The hold timer was the other candidate and it is now measured**, so the caveat
  this bullet used to carry is discharged: half of all exits, +15.0R in total, roughly
  neutral. It is not why winners are small.
