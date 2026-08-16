# Can a major turn be seen before it happens

Run: `python research/harness/turns.py`

[todo.md](../docs/todo.md) §6a asks for the reversal that matters over weeks
rather than the next touch, and asks for the falsification to be written before
the model — because major turns are rare, and a dozen observations will produce
a confident-looking number from anything.

**The answer is yes, weakly — and it took doubling the cross-section to see it.**

> **Re-measured on 2026-08-15.** The first reading of this document said no: on
> six instruments the purged walk-forward gave AUC 0.559 with an interval of
> 0.462–0.661, which contains 0.5. It also said the one cheap lever was to
> backfill the eight tracked feeds that had no daily bars. That was done — see
> [todo.md](../docs/todo.md) §0d — and it took the sample from 131 turns to
> **310**. The answer changed. This is the second reading; the first is in git.

On fourteen instruments the purged walk-forward gives **AUC 0.595, 95% interval
0.540 – 0.654**, which excludes 0.5. Two signals separate on their own. The
effect is small, it is the conventional one — old, extended, volatile trends
turn — and it is now measurable rather than merely plausible.

It is worth being precise about what changed. Nothing about the method: the
same universe, the same labels, the same purging, the same episode bootstrap.
Only the sample. A result that appears when you double the data and changes no
code is the most ordinary kind of finding there is, and the reason the first
reading could not see it was that 131 turns could not resolve an effect of this
size — which the first reading said, and was right about.

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

## 3. The sample is 310 turns

| feed | days | labelled | turns | | feed | days | labelled | turns |
|---|---|---|---|---|---|---|---|---|
| usdcnh | 1,485 | 348 | 47 | | usdjpy | 1,449 | 211 | 23 |
| usdchf | 956 | 256 | 32 | | us100 | 1,395 | 157 | 22 |
| gbpusd | 1,210 | 124 | 30 | | audusd | 1,032 | 133 | 20 |
| usdcad | 1,583 | 117 | 28 | | btc | 656 | 64 | 20 |
| eurusd | 1,310 | 135 | 24 | | gold | 1,297 | 64 | 19 |
| spx500 | 1,532 | 147 | 16 | | nzdusd | 846 | 71 | 13 |
| | | | | | eth | 329 | 40 | 10 |
| | | | | | sol | 136 | 6 | 6 |
| **total** | **15,216** | **1,873** | **310** | | | | | |

Base rate 12.3% of days. **222 of the 310 turns fall in a test fold** once the
folds are purged, against 94 before.

sol contributes six turns over 136 days and eth ten over 329; both are recent
listings with shallow daily history and neither is doing any work here.

## 4. Four signals separate, in sample

Ranked by AUC over the whole sample, unpurged. This is the most generous
reading any of them will get, so a signal flat here is dead:

| signal | AUC | 95% by episode | |
|---|---|---|---|
| `vol` — realised volatility now | 0.628 | 0.572 – 0.685 | separates |
| `extension` — how far the trend has carried | 0.583 | 0.526 – 0.643 | separates |
| `above_mean` — distance above the long mean | 0.580 | 0.523 – 0.642 | separates |
| `off_low` — how far off the 250-day low | 0.575 | 0.521 – 0.638 | separates |
| `since_low` | 0.531 | 0.476 – 0.591 | |
| `vol_ratio` | 0.527 | 0.477 – 0.580 | |
| `up_days` | 0.513 | 0.462 – 0.562 | |
| `efficiency` | 0.487 | 0.435 – 0.540 | |
| `decel` | 0.481 | 0.450 – 0.515 | |
| `drawdown` | 0.472 | 0.424 – 0.516 | |

Four separate, and they are not quite the four the smaller sample found.
`vol` strengthened from 0.606 to 0.628 and is now clearly the best single
signal. `above_mean` and `off_low` were flat before and separate now.
`since_low`, which was the *strongest* signal on six instruments at 0.616, has
faded to 0.531 — a good reminder of how much of a marginal ranking is noise.

What survives across both readings is the shape: **extended, volatile trends
turn.** What does not survive is any particular member of the set.

Two things still measure at chance and both are worth naming, because they are
what anyone would try first: **momentum deceleration** (`decel`, 0.481) and the
**efficiency ratio** (`efficiency`, 0.487) — the cycle labeller from
[cycles.md](cycles.md). How cleanly a trend has run says nothing about whether
it is ending.

## 5. And now it survives a leakage-free split

Walk-forward over purged folds, 222 turns in test:

| signals | AUC | 95% by episode | |
|---|---|---|---|
| **all ten** | **0.595** | **0.540 – 0.654** | separates |
| `vol` alone | 0.604 | 0.537 – 0.671 | separates |
| the four that separated | 0.595 | 0.535 – 0.659 | separates |
| `extension` alone | 0.589 | 0.520 – 0.652 | separates |
| age and extension | 0.580 | 0.513 – 0.645 | separates |
| `since_low` alone | 0.528 | 0.465 – 0.592 | |
| `vol_ratio` alone | 0.497 | 0.430 – 0.567 | |

`vol` alone very nearly matches all ten, which is the pattern
[features.md](features.md) found with `side` and this project keeps finding:
one signal does the work and the rest are decoration.

Leave-one-instrument-out is genuinely mixed, and this is the weakest part of
the result:

| held out | AUC | 95% by episode | turns |
|---|---|---|---|
| btc | 0.753 | 0.537 – 0.919 | 20 |
| gold | 0.711 | 0.540 – 0.842 | 19 |
| eurusd | 0.698 | 0.529 – 0.843 | 24 |
| usdchf | 0.636 | 0.449 – 0.796 | 32 |
| sol | 0.633 | 0.331 – 0.892 | 6 |
| gbpusd | 0.631 | 0.466 – 0.809 | 30 |
| usdcnh | 0.576 | 0.438 – 0.716 | 47 |
| audusd | 0.572 | 0.402 – 0.749 | 20 |
| eth | 0.564 | 0.344 – 0.755 | 10 |
| us100 | 0.554 | 0.373 – 0.803 | 22 |
| usdjpy | 0.537 | 0.280 – 0.711 | 23 |
| spx500 | 0.537 | 0.304 – 0.789 | 16 |
| nzdusd | 0.464 | 0.193 – 0.709 | 13 |
| usdcad | 0.447 | 0.293 – 0.688 | 28 |

Twelve of fourteen above chance, three separating individually, and **two below
0.5**. Every interval is at least 0.25 wide. Held-out generalisation is
directionally supported and nowhere near established.

## 6. Is it the same relationship in every era

Across four eras of 3,804 days each:

| signal | 2007– | 2015– | 2019– | 2023– | spread |
|---|---|---|---|---|---|
| **`vol`** | **0.670** | **0.625** | **0.613** | **0.585** | **0.085** |
| `extension` | 0.604 | 0.648 | 0.603 | **0.441** | 0.206 |
| `vol_ratio` | 0.543 | **0.434** | 0.583 | 0.540 | 0.148 |
| `since_low` | 0.534 | 0.554 | 0.518 | 0.513 | 0.041 |

**`vol` is the only one above 0.5 in every era with a narrow spread**, and it
is also the best single signal purged. That is two independent reasons to
prefer it, and it is why the recommendation is to build on `vol` alone if
anything is built at all.

It is also **monotonically decaying** — 0.670, 0.625, 0.613, 0.585. The effect
is real and getting weaker, which is what one would expect of anything this
obvious in a market that people trade.

`extension` and `vol_ratio` each drop below 0.5 in one era. On the six-instrument
sample every signal stayed above 0.5 everywhere; with more data two of them
turn out not to. More sample made the individual rankings *less* flattering
while making the pooled result significant, which is the honest shape of a
small real effect emerging from noise.

The base rate also falls, though less steeply than the first reading suggested:
**15.2% of days in the first era, 9.6% in the last**. Turns of this size have
become less common; the later folds carry the fewest turns and the most noise.

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

1. **Surface it as context, not as a call.** AUC 0.595 is a real effect and a
   weak one. "This trend is extended and volatility is rising" is a sentence
   worth putting in front of an analyst; it is not a signal worth acting on,
   and the gap between those two things is the whole discipline here. The
   nearest home is [todo.md](../docs/todo.md) §6 — the score — as context on
   the number rather than a term in it.
2. **If anything is built, build it on `vol` alone.** It scores 0.604 purged
   against 0.595 for all ten, so nine of the ten signals are decoration. This
   is the same shape [features.md](features.md) found with `side` and
   [models.md](models.md) found with a 1KB logistic regression: in this
   project, the small thing keeps winning.
3. **Do not reach for a bigger model.** Ten correlated signals over 310 turns
   still overfits; a forest over the same 310 will produce a better in-sample
   number and the same out-of-sample one.
4. **Hold-out generalisation is the weak point, not the headline.** Two of
   fourteen instruments come in below chance and every interval is at least
   0.25 wide. Before this is trusted across instruments it needs either more
   turns per instrument or an honest admission that it is a pooled effect.
5. **Note what did not work, so it is not retried.** Momentum deceleration
   (0.481) and the efficiency ratio (0.487) both measure at chance — the two
   things most likely to be tried first by anyone picking this up. And
   `since_low`, the strongest signal on six instruments, faded to chance on
   fourteen; a marginal ranking is mostly noise.
6. **The lever that changed this answer was a collection run**, not a better
   model. Worth remembering the next time a result reads as "nothing here".
