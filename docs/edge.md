# The 0.08 gate, measured

`|edge| >= 0.08` decides whether a level call is said out loud. `edge` is
`probability_up - base_rate_up`: how far the conditional sits from the
unconditional, in probability. The number was never derived from anything — not
in the commit that introduced it, not in the docs.

[todo.md](todo.md) has carried "derive it from the journal" for a while, and the
attempt failed for a reason worth repeating: on pre-fix data the direction was
called correctly **99.9% of the time at every level of |edge|**, because
inflated touch counts made a level's history and its next outcome the same move
counted twice. A gate cannot be placed on a measurement that says everything
works.

The counting bugs behind that were fixed on 2026-08-14. This is the experiment
re-run, and it reaches three conclusions, one of which contradicts what todo.md
proposed.

## What was run

200,240 stored bars replayed through the engine across 1m, 5m, 15m and 1h on
six instruments, pairing **every call with the outcome of the touch it opened**
— 2,003 pairs. A call claims a direction through the sign of `edge`; the
outcome is the sign of the realised `push_vol`. "Direction" below is how often
those agree; "mean push" is the realised push in volatility units, signed
positive when the call was right.

**Bars only.** Production also drives touches from quotes, and today's evidence
is that the two paths differ in ways that matter — the instant-resolution fix
looked complete on a bars-only replay and was still 42.9% wrong on production
because the quote path had no consensus. Treat everything here as the level
machinery rather than the whole system.

## 0. The blocker is gone

**Direction called correctly 71.1%** of 1,990 decided calls, against 99.9%
before. That is a plausible number rather than a broken one, and it is the
finding that makes the rest of this document possible at all.

## 1. Bigger edge, better call — and the gate is below the step

| \|edge\| band | n | direction | mean push |
|---|---|---|---|
| 0.00 - 0.06 | 468 | 54.3% | 0.16 |
| 0.06 - 0.08 | 134 | 59.0% | 0.29 |
| **0.08 - 0.11** | **212** | **60.8%** | **0.28** |
| 0.11 - 0.14 | 190 | 75.3% | 0.82 |
| 0.14 - 0.20 | 391 | 75.2% | 0.79 |
| 0.20 + | 595 | 86.7% | 1.37 |

Below roughly 0.11 everything sits between 54% and 61% — a coin flip with a
push near zero. At 0.11 it steps to 75% and a push of 0.82, and the band above
it repeats that almost exactly, which is what a real boundary looks like rather
than one bin of noise.

**0.08 is inside the flat region.** The band it admits, 0.08 to 0.11, performs
like the bands below it and nothing like the bands above it.

It is also no longer where it was thought to be. The earlier note in
[levels.md](levels.md) put it near the 97.7th percentile of its own input, with
2.3% of calls reaching it. On corrected data the median |edge| is **0.1373**, so
0.08 sits *below the median* and passes **69.6%** of calls. The distribution
moved under it when the counting was fixed.

### It is not one instrument carrying it

| feed | below 0.11 | at or above 0.11 |
|---|---|---|
| us100 | 51.6% (n=223) | 76.3% (n=224) |
| spx500 | 58.4% (n=197) | 74.0% (n=196) |
| btc | 58.6% (n=111) | 84.0% (n=231) |
| eurusd | 61.0% (n=105) | 87.8% (n=230) |
| gbpusd | 63.4% (n=112) | 81.4% (n=172) |
| gold | 48.5% (n=66) | 82.1% (n=123) |

Six of six, same ordering, none of them marginal. This is the strongest
evidence here.

## 2. A rolling quantile is **worse** than a constant

[todo.md](todo.md) proposed making the gate "a rolling quantile of realised
edges rather than a constant — the same instinct as [score.md](score.md)'s
thresholds". **That was wrong, and the measurement is not close.** Each rolling
rule is compared against the constant that lets exactly the same number of
calls through, on the same calls:

| rule | passed | share | direction | mean push |
|---|---|---|---|---|
| no gate | 2,003 | 100% | 71.1% | 0.73 |
| rolling q0.70 | 348 | 17.4% | 82.3% | 1.28 |
| **constant 0.2489** | 349 | 17.4% | **89.6%** | **1.70** |
| rolling q0.80 | 247 | 12.3% | 82.3% | 1.32 |
| **constant 0.2745** | 248 | 12.4% | **91.9%** | **1.86** |
| rolling q0.90 | 146 | 7.3% | 82.6% | 1.33 |
| **constant 0.3128** | 147 | 7.3% | **93.2%** | **1.92** |
| rolling q0.95 | 94 | 4.7% | 87.1% | 1.62 |
| **constant 0.3343** | 95 | 4.7% | **91.5%** | **1.98** |

The constant wins by four to ten points of direction at identical volume, in
all four comparisons.

**Why, and why the instinct was reasonable but misapplied.** score.md's
thresholds are on quantities in instrument-specific units, where a constant
cannot mean the same thing on gold and EURUSD and a quantile is the only
honest form. `edge` is *already* scale-free: it is a difference of two
probabilities, and 0.11 means the same thing everywhere by construction.
Normalising it per cell therefore destroys the comparability it already had —
promoting the best of a weak cell and demoting a genuinely strong call in a
cell that often has strong ones.

There is a practical objection as well: **9 of 24 cells never accumulate the
50 calls the rolling rule needs**, covering 17.8% of all calls. On a fourteen
instrument by seven timeframe grid that fraction would be far larger.

## 3. What is *not* established

The threshold's **level** does not transport, only its ordering. Splitting the
calls in half by time:

| band | train | test |
|---|---|---|
| 0.11 - 0.14 | 63.3% | 88.0% |
| 0.20 + | 74.2% | 91.4% |

Every band is far better in the second half, and the top band holds 163 calls
in the first half against 432 in the second. That is the engine warming up
during the replay — levels accumulating history, base rates settling — not a
market regime. The step at 0.11 appears in **both** halves (54.8% to 63.3% in
the first, 71.4% to 88.0% in the second), so the boundary is real; the absolute
accuracy either side of it is not a number to quote.

Also unmeasured: whether any of this survives the quote path, what it does to
alert volume after `actionable`'s other gates, and whether the reward-to-risk
gate already removes most of what moving the threshold would remove.

## What to do

1. **Move the constant from 0.08 to 0.11**, and keep it a constant. It is the
   one change the evidence supports directly: the band being admitted today
   performs like noise on every instrument tested.
2. **Do not build the rolling quantile.** Record why, because the instinct will
   recur — and it is right for anything measured in volatility units, which is
   most of this project. It is wrong here precisely because `edge` is not.
3. **Re-derive on production once there are enough post-fix outcomes**, on the
   quote path rather than a bars-only replay, before treating 0.11 as settled.
   The counter for that restarts from the 2026-08-14 fixes, same as
   [todo.md](todo.md) item 4.
