# Borrowed physics: susceptibility predicts volatility **falling**, and fatigue has the wrong sign

Run: `python research/harness/susceptibility.py`, `research/harness/vol_sign.py`

**Measured 2026-09-23.** Two concepts taken from a retired in-house detector suite, at the desk's
suggestion that they might improve the volatility and breakout models. One produced a reproducible
positive result; the other is refuted in the direction it was stated.

| borrowed idea | verdict |
| --- | --- |
| `chi = var(M)` forecasts the volatility **level** | **null** - 2-5x worse than a trailing sigma, incremental R-squared 0.0008-0.0085 |
| `chi` is a **leading** indicator of a volatility *rise* | **refuted, and inverted** |
| high `chi` predicts volatility **falling** | **holds** - +5 to +9 points on 5 of 7 instruments, through a decile control |
| `chi` predicts *which side* the volatility lands on | **null** |
| trend up + expected volatility resolves **downward** | **null** |
| "fatigue": more touches means readier to break | **refuted** - monotone in the opposite direction, 5x |

## The quantity, and why it deserved a harness

The borrowed detector defines a **magnetization** `M = net signed returns / total absolute returns`
over a rolling window and a **susceptibility** `chi = var(M)`, claiming `chi` spikes *before* a
regime change.

**`M` is already in production here under another name.** It is exactly `trend.py`'s efficiency
ratio, measured over 54,143 resolutions, whose top decile breaks 1.4% of the time against the chop's
11.3%. So the borrowed idea is not the order parameter - it is **the variance of it**, which we did
not have.

And that is a theorem rather than an analogy. In the Ising model the susceptibility `chi = dM/dh`
diverges at the critical point, and the fluctuation-dissipation theorem makes it proportional to the
variance of the order parameter. "The variance of `M` peaks at a phase transition" is that statement.
Whether a market *has* a critical point is a separate question, and the harness does not assume one -
it asks only whether `var(M)` today says anything about volatility tomorrow.

## The level: null, and a lesson in effect size

`chi` scored against a trailing standard deviation - the baseline that has beaten a three-state HMM,
a 50-neighbour analogue on 0 of 20 cells, and persistence landscapes:

| instrument | horizon | r(chi, forward vol) | QLIKE chi | QLIKE trailing | beta chi | t | dR-squared |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| btcusd | 5 | 0.028 | 1.8668 | **0.9274** | +0.0410 | 5.2 | 0.0008 |
| xauusd | 20 | −0.030 | 1.9566 | **0.4056** | −0.0466 | −18.4 | 0.0025 |
| eurusd | 20 | −0.042 | 2.1014 | **0.3383** | −0.0643 | −29.8 | 0.0056 |
| gbpusd | 5 | 0.061 | 2.1923 | **0.7655** | +0.1134 | **31.8** | 0.0085 |

`chi` alone is two to five times worse than 100 bars of arithmetic, its correlation with forward
volatility never exceeds 0.061, and adding it to the baseline moves R-squared by at most **0.0085**.

**Keep that last row.** A t-statistic of **31.8** beside an incremental R-squared of **0.0085** is
the clearest illustration in this folder of why effect sizes are computed here and p-values are not.
At 100,000 rows almost anything is significant; the coefficient also **changes sign with the
horizon** (+0.11 at 5 bars, −0.07 at 20, −0.03 at 60), and a coefficient whose sign depends on the
horizon is not a mechanism. The intervals are worse than stated, too: overlapping forward windows
make the rows dependent and the plain standard error understates by roughly the square root of the
horizon.

## The inversion, which is the result

The claim was that `chi` rises *before* volatility. It does the opposite, and consistently. Asked in
the form the claim was made - does volatility **rise** after a loud `chi`? - the lift is *negative*
at 20 and 60 bars on three of four instruments.

The desk's response was the right one: *"which we can use too."* A forecast that volatility will
**fall** is a forecast. But there is an obvious way for it to be nothing:

> **`chi` is built from returns, is large in choppy stretches, and chop follows violence. So "high
> `chi` then falling volatility" might be no more than "volatility is high and volatility
> mean-reverts" - which a trailing sigma already knows.**

So the lift is reported twice: raw, and **within deciles of trailing volatility**, where a quantity
that is merely a proxy for the level scores zero by construction.

| instrument | horizon | vol fell, raw | vol fell, **within deciles** |
| --- | ---: | ---: | ---: |
| usdcad | 20 | +9.7% | **+9.1%** |
| gbpusd | 20 | +9.0% | **+8.3%** |
| eurusd | 20 | +7.5% | **+7.0%** |
| xagusd | 60 | +7.4% | **+6.6%** |
| xauusd | 20 | +6.1% | **+5.3%** |
| usdjpy | 20 | +3.2% | +2.4% |
| btcusd | 20 | +0.7% | −0.2% |
| **volatility_75_index** | 20 | −1.0% | **−1.1%** |
| **volatility_100_index** | 20 | +0.3% | **+0.3%** |
| **boom_1000_index** | 20 | −0.4% | **−0.1%** |
| **crash_1000_index** | 20 | +0.4% | **+0.1%** |

**The control removes almost nothing** - 0.5 to 0.8 points of a 5 to 9 point effect - so this is not
volatility mean reversion. It survives on five of seven real instruments, fails on btcusd, and is
weak on usdjpy.

**And the synthetics confirm it.** `deriving.md` establishes that a Volatility index is GBM at a
published constant sigma, so **there is no volatility there to forecast** - and the method duly finds
nothing, reading −1.1% to +0.3%. A harness that reported skill there would be broken. It reports skill
on real markets and none on processes that have none, which is the control passing in both
directions.

So: after a loud susceptibility, the next twenty to sixty bars are quieter than the current level
implies, five to nine percentage points more often than otherwise. That is a sizing input - a
volatility-scaled stop set from trailing volatility is wider than it needs to be in exactly those
windows - and it is not a direction.

**What is not established**: no interval is computed on the per-instrument lifts, and overlapping
windows make the rows dependent. The evidence is the **cross-sectional consistency** - five
instruments agreeing in sign and magnitude while four synthetics read zero - not any single number.
A block bootstrap is the next thing this needs, before it is sized on.

## The asymmetry measure works, and finds nothing here

Up and down volatility separated by realised semivariance - Barndorff-Nielsen's decomposition, the
sum of squared returns split by each return's sign, with `A = (RS+ − RS−) / (RS+ + RS−)`.

**The measure validates cleanly on instruments with a designed asymmetry:**

| synthetic | mean A at 20 | at 60 |
| --- | ---: | ---: |
| boom_1000_index | **+0.136** | **+0.184** |
| crash_1000_index | **−0.136** | **−0.188** |
| volatility_75_index | −0.002 | −0.002 |
| volatility_100_index | −0.002 | −0.003 |

Boom is built to spike upward against a slow grind down and Crash is its mirror; the decomposition
recovers that with the right sign, near-identical magnitude on both mirrors, and **zero** on the
symmetric indices. That is as clean a positive control as this folder has.

With the measure validated, the answers are negative:

* **`chi` does not predict which side.** `r(chi, A)` runs −0.022 to +0.018 across every instrument
  and horizon;
* **`chi` adds nothing to either side's level.** Incremental R-squared on up-semivariance and
  down-semivariance separately: 0.0000 to 0.0062;
* **the desk's directional hypothesis does not hold.** *Trend up plus expected volatility resolves
  downward* was tested as the lift on "the down side carried the variance", conditional on a loud
  `chi` and a positive `M`, within volatility deciles. It comes out **−3.2% to +2.7%**, inconsistent
  in sign across instruments and horizons. The mirror case is the same. There is no pattern.

## Fatigue: refuted in its stated direction, and the untested variant named

The second borrowed concept is **fatigue** - an exponentially decayed touch count on a level,
`score = score * 0.95 + touched`, with a "tired" threshold and the stated claim that *higher fatigue
means tested more, so readier to break*.

Our `experience` is the same quantity without the decay - a log-compressed raw touch count. Over
**320,811 resolved touches**:

| experience quintile | n | mean | break rate |
| ---: | ---: | ---: | ---: |
| 1 | 64,162 | 0.058 | **15.0%** |
| 2 | 64,162 | 0.273 | 12.1% |
| 3 | 64,162 | 0.439 | 11.3% |
| 4 | 64,162 | 0.611 | 8.8% |
| 5 | 64,163 | 1.090 | **2.9%** |

Monotone across all five, a **fivefold** spread, AUC 0.3728 - which read the right way round is
**0.6272**, one of the strongest separators in this repository. **More-tested levels break less**,
which is the opposite of the claim.

The mechanism is survivorship and it is worth stating because it is not a defect: **a level
accumulates touches only by holding.** Once it breaks it stops accruing them. So a high count is
conditionally selected on not having broken yet - which does not invalidate the prediction, since the
count is known at decision time, but it does explain why the direction is what it is.

**And it means the decayed variant is not refuted by this.** "Tested five times in the last hour" and
"tested five times over a month" are different states, and only the second is what `experience`
measures. That question is currently **untestable here**: reconstructing a per-level decayed count
needs a level identifier, and the journal's `outcome` entries do not carry one - `level_price` and
`price` are both absent from all 323,712 rows. It would need a join to the level-call entries through
the `_awaiting` reference, which is a larger extraction than this study warranted.

Recorded so that whoever tries it knows the shape of the disagreement: the raw count settles the
sign, the decay is a different question, and the data to ask it has to be assembled first.

## Two concepts noted and not tested

Also in the borrowed suite, and worth recording rather than pursuing now:

**A CFAR threshold** - constant false-alarm rate, from radar detection: set the detection threshold
from the local noise estimate so the false-alarm rate is held fixed as conditions change. This
repository arrived at the same idea independently and from a different direction: `changepoint.py`'s
homeostatic LIF neuron regulates its own firing rate against a target, and `detectors.md` measured
why it had to - a *fixed* threshold fired 0.06 times per thousand bars in a quiet stretch and 43.16
in a loud one, seven hundredfold, while the rate-regulated one held near 2. CFAR is the signal-
processing name for that, and the convergence is a point in favour of both.

**`cisd`** - a change in state of delivery - is already covered by `delivering.md`, which found it to
be one object with ZigZag pivots, FOCuS change points and perceptually important points under
several names, at 2 to 4 points over matched-random on real outrights.
