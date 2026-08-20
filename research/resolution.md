# Two thirds of outcomes resolved before they could have happened

Run: the production journal, not a replay — that is the point of this one.

Every other document here replays stored bars. This one came from asking a
plain question of the live journal, "which resolved outcomes went well", and
getting an answer so good it had to be wrong.

## 1. The question that could not be asked

Scored naively, production looked extraordinary:

| outcome | share | mean \|push\| | a "level holds" trade |
|---|---|---|---|
| reject | 75.4% | 3.18 | +3.18 |
| trap | 16.9% | 1.60 | +1.60 |
| backcheck | 4.9% | 3.12 | +3.12 |
| break | 2.5% | 6.02 | −6.02 |

A 97% win rate — and it is **circular**. The outcome *label* determines the
sign of the push: a `reject` means price was pushed back, so a hold trade is
positive by construction, and a `break` is negative by construction. Scoring
outcomes that way re-reports the mix and calls it profit.

One number there is not definitional and is worth keeping: **breaks are 2.5% of
outcomes and nearly twice the size of everything else.**

## 2. What the timing said

| | share |
|---|---|
| resolved in **0 seconds** | **33.6%** |
| resolved in <= 2 seconds | **67.5%** |
| resolved in <= 60 seconds | 84.0% |

And it was the *coarse* timeframes, with 1m the only one behaving:

| interval | n | zero-duration |
|---|---|---|
| 3m | 13,794 | **41.9%** |
| 15m | 3,017 | 35.1% |
| 5m | 5,152 | 35.0% |
| 1h | 946 | **22.7%** |
| **1m** | 3,559 | **1.0%** |

A touch on an hourly level opening and resolving inside two seconds means price
travelled 1.5 volatility units in two seconds. Not a market move.

## 3. The first hypothesis was wrong

Recorded here because the wrong one was plausible and cost time. The suspicion
was that the resolution threshold, or the volatility it is denominated in, came
from the *finest* series rather than the level's own — touch detection had been
deliberately moved there, so resolution might have followed.

It had not. `check` reads `self.vol.of(feed, interval)`, the level's own.

## 4. What it actually was

`run_vol` — the length of the leg *into* the level — is **0.00 at the median,
at p90 and at the maximum** across all 8,897 zero-duration outcomes. Not one
ever recorded an approach. Meanwhile `push_vol` reads a median of 2.88
volatility units. A large move, no approach, no time.

The mechanism is the **bar wick**. `observe_bar` hands `low` and `high` to
`check`, which passes them to `Tracker.update` for whatever touch is open. A
quote opens a touch part way through a bar; the bar then arrives carrying a
range describing the *whole* period, including the seconds before that touch
existed. Applied to it, the touch resolves immediately on movement that
predates it.

Coarse intervals were worse because their bars cover more time, so more touches
open inside one. **1m being least affected is what made this legible at all** —
with every interval equally broken there would have been no contrast to notice.

The fix is one condition: a touch that began at or after the bar opened sees
only the close, and picks the wick up on the next bar it genuinely lives
through.

## 5. It worked

Production, before and after the fix:

| | before | after |
|---|---|---|
| zero-duration | 31.2% | **0.3%** |
| <= 2 seconds | 60.7% | **0.9%** |
| median duration | 1s | **94s** |

| interval | <=2s before | <=2s after |
|---|---|---|
| 1h | 80.4% | **0.0%** |
| 15m | 73.7% | **0.0%** |
| 3m | 73.4% | **0.3%** |
| 5m | 67.1% | **0.2%** |
| 1m | 2.9% | 1.3% |

Outcome volume fell by roughly 60%, which is the correct amount: the instant
resolutions *were* 60% of outcomes.

## 6. What is still broken

**Negative durations** — a resolution stamped before its own touch began. A
separate bug, and now the dominant one: 294 of them since the fix, worst −524s,
median −18s.

| interval | before | after |
|---|---|---|
| 1m | 8.1% | 10.7% |
| 3m | 1.8% | 5.8% |
| 5m | 1.5% | 4.1% |

Most of that rise is arithmetic rather than regression: removing 60% of
outcomes raises every remaining share, and 2.7% diluted by that alone becomes
about 6.8% against 8.6% observed. Some may be real. Either way it concentrates
on **1m**, the opposite interval from the instant resolutions, which is why it
was always a separate bug.

## Why this matters beyond itself

**No bars-only replay could have found it.** Without quotes, nothing opens a
touch part way through a bar. Every research document in this folder replays
bars, so the production journal and the harness were not measuring the same
system — which [edge.md](../docs/edge.md) has warned about since 2026-08-14
without a concrete instance until now.

**And it made the journal untrainable.** Asked whether it was time to fit
`facto` on 26,538 journalled outcomes, the sensitivity test is the answer:

| filter | kept | facto | logistic | holds |
|---|---|---|---|---|
| everything | 26,538 | 96.0% | 97.3% | 97.4% |
| positive duration only | 17,021 | 93.5% | 95.8% | 95.9% |
| **at least one of its own bars** | **3,179 (12%)** | **60.7%** | **77.1%** | **77.3%** |
| at least two of its own bars | 2,116 | 52.0% | 67.0% | 67.8% |

96% on the raw journal is the same shape as the 99.9% that
[edge.md](../docs/edge.md) exists to explain — not skill, but resolutions so
fast the label predicts itself. **The filter was the whole result.** Fitting on
everything would have produced a confident model of a bug.
