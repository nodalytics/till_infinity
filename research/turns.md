# Can a major turn be seen before it happens

Run: `python research/harness/turns.py`

[todo.md](../docs/todo.md) §6a asks for the reversal that matters over weeks
rather than the next touch, and asks for the falsification to be written before
the model — because major turns are rare, and a dozen observations will produce
a confident-looking number from anything.

**The answer is: do not build it, and the reason is not the one §6a expected.**
Four signals separate turns from non-turns in sample, consistently and in the
same direction across twenty years. None of it survives a leakage-free split,
and the sample needed to tell a real effect this size from noise is several
times larger than anything this project can hold.

That is a different verdict from [cycles.md](cycles.md), where nothing pointed
anywhere at all. Here something does, and it still is not enough.

## 1. The question, stated so it can be wrong

    On a day when the instrument is in an established uptrend near its highs,
    will it fall by 20 of its own daily move units within 60 trading days?

Every clause is load-bearing.

**"Near its highs, in an uptrend"** is the universe, and it is what makes this a
question about *turns* rather than about declines. §6a asks whether a signal
"separates it from the far more numerous moments that looked similar and
continued", so the comparison set has to be moments that looked similar. A model
that learns to tell a bull market from a bear market has answered an easier
question and would score well doing it.

**Units, not percent.** btc moves 1.48% on a median day, eurusd 0.31%. One
percentage threshold would mean "a routine fortnight" for the first and "a
generational move" for the second, and pooling them would pool two questions.
Twenty units is about 11% for the median instrument here.

**A forward drawdown, not a swing pivot.** A zigzag pivot is only *confirmed*
some days after the extreme — a median of 29 days at this size — so a model
trained on pivot labels is being asked when a pivot will be *confirmed*, which
is not when the turn happened. The forward drawdown has no confirmation lag and
no ambiguity about which day the turn was.

## 2. The refusal, designed first

Three things here manufacture a good answer from nothing.

**Overlapping windows.** Two days a week apart share 53 of their 60 forward
days. 691 labelled days are nowhere near 691 observations. Everything is
counted and resampled in **episodes** — contiguous runs of the label — and the
bootstrap resamples whole episodes rather than days. This is the single most
important choice in the script: resampling days would have returned intervals
several times too narrow, and every result below would have looked significant.

**Leakage across the split.** A training day at t and a test day at t+10 share
most of a forward window, so an ordinary time split leaks the answer backwards.
Training rows within `HORIZON` days of the test set are **purged**.

**One instrument carrying it.** Reported leave-one-instrument-out.

## 3. The sample is 131 turns

| feed | universe days | labelled | turns |
|---|---|---|---|
| gbpusd | 1,210 | 124 | 30 |
| eurusd | 1,310 | 135 | 24 |
| us100 | 1,395 | 157 | 22 |
| btc | 656 | 64 | 20 |
| gold | 1,297 | 64 | 19 |
| spx500 | 1,532 | 147 | 16 |
| **total** | **7,400** | **691** | **131** |

This is more than §6a assumed — it guessed "tens" — because the daily history
runs 12 to 20 years, not the six months the touch data covers. It is still
small, and 94 of the 131 fall in a test fold once the folds are purged.

## 4. Four signals separate, in sample

Ranked by AUC over the whole sample, unpurged. This is the most generous
reading any of them will get, so a signal flat here is dead:

| signal | AUC | 95% by episode | |
|---|---|---|---|
| `since_low` — how long since the 250-day low | 0.616 | 0.535 – 0.694 | separates |
| `vol` — realised volatility now | 0.606 | 0.521 – 0.695 | separates |
| `extension` — how far the trend has carried | 0.593 | 0.511 – 0.671 | separates |
| `vol_ratio` — volatility expanding | 0.583 | 0.518 – 0.650 | separates |
| `off_low` | 0.508 | 0.429 – 0.589 | |
| `above_mean` | 0.494 | 0.414 – 0.574 | |
| `efficiency` | 0.489 | 0.396 – 0.574 | |
| `drawdown` | 0.483 | 0.411 – 0.552 | |
| `decel` | 0.479 | 0.427 – 0.534 | |
| `up_days` | 0.458 | 0.374 – 0.544 | |

All four point the same way, and the way is the conventional one: **old,
extended, volatile trends turn.** Nothing about *deceleration* survives, which
is mildly surprising — the folk model of a turn is momentum fading, and momentum
fading is the one thing here that measures at chance.

Notably `efficiency`, which is the cycle labeller from [cycles.md](cycles.md),
is flat at 0.489. How cleanly a trend has run says nothing about whether it is
about to end.

## 5. None of it survives a leakage-free split

Walk-forward over purged folds:

| signals | AUC | 95% by episode |
|---|---|---|
| all ten | 0.559 | 0.462 – 0.661 |
| `extension` alone | 0.574 | 0.463 – 0.676 |
| `vol` alone | 0.536 | 0.439 – 0.639 |
| `since_low` alone | 0.503 | 0.417 – 0.593 |
| `vol_ratio` alone | 0.463 | 0.396 – 0.533 |
| the four that separated | 0.472 | 0.379 – 0.570 |

**Every interval contains 0.5.** `since_low`, the strongest signal in sample at
0.616, lands at 0.503 out of sample — chance to three decimals.

Leave-one-instrument-out is the same story with wider intervals: five of six
above 0.5, one (gold, 0.418) below, and only spx500 separating — on sixteen
turns, which is not a result.

| held out | AUC | 95% by episode | turns |
|---|---|---|---|
| spx500 | 0.727 | 0.509 – 0.910 | 16 |
| us100 | 0.652 | 0.473 – 0.851 | 22 |
| btc | 0.629 | 0.416 – 0.858 | 20 |
| eurusd | 0.616 | 0.472 – 0.756 | 24 |
| gbpusd | 0.534 | 0.380 – 0.697 | 30 |
| gold | 0.418 | 0.275 – 0.624 | 19 |

## 6. Why in-sample and out-of-sample disagree

Not because the relationship reverses. Across four eras of five thousand days
each, every one of the four signals stays on the same side of 0.5 in almost
every era:

| signal | 2007– | 2016– | 2020– | 2024– | spread |
|---|---|---|---|---|---|
| `since_low` | 0.543 | 0.715 | 0.552 | 0.689 | 0.172 |
| `vol` | 0.691 | 0.561 | 0.655 | 0.615 | 0.129 |
| `extension` | 0.600 | 0.720 | 0.585 | 0.501 | 0.220 |
| `vol_ratio` | 0.541 | 0.480 | 0.747 | 0.732 | 0.267 |

The *sign* is stable; the *magnitude* swings by up to 0.27, which is larger than
the effect itself. A model fitted on one era and applied to the next is fitting
a coefficient that has already moved.

The base rate moves too, and a long way: **12.9% of days in the first era,
5.4% in the last.** Turns of this size have become markedly rarer over twenty
years. That does not break a rank measure like AUC directly, but it means the
later folds — the ones being tested on — carry the fewest turns and the most
noise.

## 7. What sample would settle it

Measured rather than assumed, by subsampling episodes:

| turns | median half-width of the 95% interval |
|---|---|
| 23 | 0.189 |
| 47 | 0.145 |
| 94 | 0.124 |

Only the downward direction is valid. Resampling *more* episodes than exist
duplicates the ones there are and adds no information — the curve flattens for
a reason that has nothing to do with statistics, which is worth stating because
the flat part looks exactly like convergence.

The interval narrows more slowly than 1/sqrt(n), because episodes are
themselves correlated and unequal in size. Reaching a half-width of 0.05 —
enough to call 0.56 apart from 0.50 — therefore needs **several hundred**
out-of-sample turns against the 94 available, and probably more than the
square-root law suggests.

**Eight tracked feeds have no daily bars at all** — audusd, eth, nzdusd, sol,
usdcad, usdchf, usdcnh, usdjpy. Backfilling them would take the cross-section
from six instruments to fourteen, which is the one lever available that costs
nothing but a collection run. It would roughly double the turns. It would not
be enough on its own, and saying so now is cheaper than finding out later.

## Recommendations, in order

1. **Do not build a turn model.** Nothing survives a purged split, and §6a
   asked for the refusal to be designed first precisely so this could be a
   decision rather than a disappointment.
2. **Backfill daily bars for the eight feeds that have none.** It is the only
   cheap lever on the sample, it helps [cycles.md](cycles.md) too — which
   failed for want of exactly this span — and it costs a collection run.
3. **Keep the four signals as context, not as a call.** "Old, extended,
   volatile trend" is a real description of the moments that turn, at an
   in-sample AUC of about 0.6. That is worth surfacing to an analyst as a
   sentence and is nowhere near worth trading.
4. **Do not reach for a bigger model.** Ten correlated signals over 131 turns
   already overfits; a forest or a neural net over the same 131 will produce a
   better in-sample number and the same out-of-sample one. This is the finding
   [models.md](models.md) reached from the other direction.
5. **Note what did not work, so it is not retried.** Momentum deceleration
   measures at chance, and so does the efficiency ratio — the two things most
   likely to be tried first by anyone picking this up.
