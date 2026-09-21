# Is 4h the king of timeframes?

The claim, as put by the operator: **4h rules.** A signal on a timeframe above or
below it that disagrees with 4h is likely to lose.

Measured twice - six instruments and then nine, the second set including
synthetics - on roughly 650,000 hourly trades per cell, 2010-2026, from the broker's
own bars. **It does not hold**, and neither does the one alternative the sweep threw
up: a `zma` context filter looked consistent on the narrower panel, then lost two
thirds of its size out of sample and was beaten by its own block-shuffled null 29%
of the time.

Harness: `research/harness/anchor.py`.

## Why the test sweeps ten timeframes instead of testing 4h

Testing 4h alone cannot answer the question. Alignment with *any* slower timeframe
helps if trends persist at all, so a positive result for 4h would establish that
trend agreement helps - which nobody doubts - and nothing whatsoever about four
hours.

So ten anchors are measured identically, and the ladder is deliberately dense
either side of 4h: **if four hours is the special number, 2h, 3h, 6h and 8h have to
be visibly worse.** That is the only version of the claim that can fail.

## What is measured

No signal model, because testing a rule conditional on the anchor would confound
the rule with the anchor. The anchor does the whole job:

    at every bar, what happens to a long, and to a short,
    when the anchor says up, and when the anchor says down?

The outcome is first passage of a symmetric barrier at one true range, which is what
a stop and a target actually resolve against. If an anchor carries direction, longs
must resolve better when it points up. The **gap** between aligned and opposed is the
anchor's edge in R.

Cost cancels in that gap - it is subtracted from both sides - so none of what follows
rests on the cost assumption. Both barriers inside one bar resolve as the stop, since
a bar does not record which extreme arrived first, which biases every number
downward. The anchor is read only from bars that had already closed.

## Four readings, because "aligns with 4h" is ambiguous

| reading    | question                                                  |
|------------|-----------------------------------------------------------|
| `trend`    | is this timeframe's close above its previous close         |
| `pivot`    | is price above the last closed bar's `(H+L+C)/3`           |
| `zma`      | is the desk's own `Zma` sloping up on this timeframe       |
| `momentum` | which way did the desk's own `Cusum` last break on it      |

`zma` and `momentum` call the real classes the desk runs, not reimplementations, so a
result here is a statement about this desk. `pivot` is a *level* rather than a slope,
which is how the rule is usually stated out loud.

## 4h is not special

Mean gap in R, six instruments:

```
reading          2h        3h        4h        6h        8h
trend       -0.0185   -0.0113   -0.0167   -0.0115   -0.0058
pivot       -0.0166   -0.0190   -0.0148   -0.0054   -0.0006
zma         +0.0099   +0.0126   +0.0123   +0.0103   +0.0139
momentum    -0.0058   +0.0047   +0.0064   +0.0084   +0.0045
```

4h is best at nothing. Under `trend` it is worse than 3h, 6h *and* 8h; under `pivot`
worse than 6h and 8h; under `zma` level with 3h and below 8h; under `momentum` below
6h. It is middling in all four. **The number four is doing no work.**

An earlier, narrower run of the same test - one reading, five instruments, 483,000
trades - put 4h *last* of six anchors at -0.0115R against 12h leading at +0.0023R.
Both runs agree on the direction of the answer.

## Why the belief is easy to form anyway

4h signals are rare. Of 199,978 journal decisions carrying an interval, **728 are 4h
- 0.4%**, the rarest real timeframe:

| interval | decisions | share | bars/day | decisions per bar |
|----------|----------:|------:|---------:|------------------:|
| tick     |   108,752 | 54.4% |        - |                 - |
| 1m       |    34,025 | 17.0% |    1,440 |              23.6 |
| 5m       |    20,494 | 10.2% |      288 |              71.2 |
| 15m      |     8,463 |  4.2% |       96 |              88.2 |
| 1h       |     2,577 |  1.3% |       24 |             107.4 |
| 2h       |     1,290 |  0.6% |       12 |             107.5 |
| **4h**   |   **728** |**0.4%**|    **6**|         **121.3** |

The last column is the point: **per bar, 4h produces more decisions than 1h or 2h.**
Nothing is filtering it out - there are simply six 4h bars a day against 1,440 at 1m.
Rare signals feel significant, and 728 observations is a small enough base for an
impression of reliability to form that half a million trades does not support.

(Also visible in that tally: `daily`/`1d` and `weekly`/`1w` both appear as separate
labels for the same timeframe, which will split any per-timeframe count.)

## The one candidate, and how it died

On the first panel - six instruments, all FX and metals plus one micro duplicate -
`zma/8h` (+0.0139R) and `zma/6h` (+0.0103R) were the only two cells agreeing across
every instrument, and this document originally wrote them up as a live hypothesis.
They were interesting because `structures/zma.py` records the same indicator at AUC
0.485-0.515 as an *entry signal* on these instruments: slower-timeframe **context**
is a different job from entry timing, and this looked like where it might earn
something.

It did not survive either of the two tests it was given.

**Out of sample.** Rerun on nine instruments including Boom, Crash and the
volatility indices - generated processes with no macro driver, so agreement across
them is much harder to explain away - both cells lost two thirds of their size:

| cell     | 6 FX/metals | 9 incl. synthetics |
|----------|------------:|-------------------:|
| `zma/8h` |    +0.0139R |            +0.0039R |
| `zma/6h` |    +0.0103R |            +0.0063R |

And the *winner moved*, to `zma/1h` at +0.0084R. A leader that changes between
samples is the signature of the best of forty rather than of an effect. The spread
across all cells fell from 0.0358R to 0.0179R, and no cell reached 9/9.

**Against its own null.** 200 block-shuffled repetitions per cell per instrument -
1,800 in total - permuting the anchor reading in blocks long enough to keep its runs
of up and down intact, so only the alignment with what price did next is destroyed:

| cell     | mean gap | shuffles matching or beating it |
|----------|---------:|--------------------------------:|
| `zma/1h` | +0.0084R |            530/1800 = **29.4%** |
| `zma/6h` | +0.0063R |                645/1800 = 35.8% |
| `zma/8h` | +0.0039R |                671/1800 = 37.3% |

A real effect is beaten by its null a few percent of the time. These are beaten a
third of the time. **There is nothing here.**

What remains true, and much weaker than it first looked: `zma` cells are positive at
six of ten anchors while `trend` is negative at eight of ten, so *how* a timeframe is
read still separates more than *which* timeframe it is. That is a statement about the
shape of the noise until something clears a null.

## A defect found while writing this, worth recording

The first version folded anchors out of the **signal's own bars**. With a daily
signal that puts one daily bar in each 4h bucket, so the 4h, 8h, 12h and 1d anchors
all returned +0.0090R on 7/7 symbols, identical to four decimal places.

Four columns showing one series - and it reads as remarkable agreement across
timeframes rather than as the same number printed four times. Anchors now come from a
separate, finer series, and any anchor finer than that source is skipped rather than
faked.
