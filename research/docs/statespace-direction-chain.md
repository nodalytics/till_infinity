# The direction chain: a coin, and the half that is not

`family.PENDING["hmm"]` has named this member since the package began, with a
specific job rather than a wish for a discrete state:

> velocity is two variables and only one of them is learnable. Measured on
> eurusd 4h, **speed is 8.1x as persistent as the signed rate** - the sum of
> the first five autocorrelations is +0.381 against -0.047 - and direction
> agrees with its predecessor 49.5% of the time against 50% +/- 3.1%. So the
> state wants to be `(position, log speed)` with direction as a separate
> discrete process, which is a switching model, and the HMM is the direction
> half of it.

Both halves are now built and measured. **The direction half is a coin and
the speed half is real and larger than the number above.**

## The prediction, written before running it

The paragraph motivating the decomposition already says direction agrees with
its predecessor 49.5% of the time against 50% +/- 3.1%. So the chain is being
asked to model a fair coin and should collapse to one: two states converging
on the same up-rate, and no gain over a single fitted coin.

Building it anyway was worth the hour. The item had been open since the
package began, the prediction was sharp enough to be wrong, and a measured
null closes it where an argument would not.

## It finds a chain that is really there

Without this the null is unreadable. On a planted series with up-rates of
0.70 and 0.30 and fifty-bar regimes, `fit` recovers **exactly 0.70/0.30** and
the chain beats a fitted coin by **101 nats** out of sample.

## And on real data it is null

Held-out log-likelihood over the **signs** of the second half. A density over
signs cannot be compared with `linear`'s density over a level, so the nulls
are the ones in the same space: a fair coin, a coin fitted on the training
half, and the chain run on the same signs **reordered**.

| | 1h fitted rates | vs fitted coin | **vs shuffled** |
| --- | --- | --- | --- |
| EURUSD | 0.52/0.48 | +5.8 | **-1.0** |
| GBPUSD | 0.52/0.48 | +7.8 | **-0.6** |
| XAUUSD | 0.52/0.48 | +6.2 | **-0.2** |
| XAGUSD | 0.52/0.48 | +23.9 | **+2.5** |
| BTCUSD | 0.52/0.48 | +9.9 | **-1.4** |
| ETHUSD | 0.52/0.48 | +5.3 | **-1.1** |
| `Volatility_75_Index` | 0.52/0.48 | +5.0 | +0.6 |
| **traded median** | | **+5.5** | **-0.1** |

**The shuffled column is the one that decides it.** The chain gains +5.5 nats
at the median over a fitted coin and **-0.1 over the same signs reordered**,
so what it gained was the marginal rather than the sequence. The generated
markets gain the same +5.0 to +9.7 over the coin, which confirms that gain is
an artefact: a two-state mixture gives a slightly heavier-tailed predictive
distribution for the up-share than a single point estimate, and that helps in
any order.

**And the states collapse.** At 1h the fit lands on 0.52/0.48 - the smallest
separation the grid offers - on **every instrument tested**, traded and
generated alike. The median fitted separation is 0.020 either side of a half,
where zero would be literally one coin.

Some 4h cells fit 0.70/0.30, the *largest* separation in the grid, and those
same cells have a shuffled gain of +1.8 to -2.3. A parameter at the top of its
grid buying nothing is the pattern this session has recorded four times.

## The other half, confirmed and larger

The decomposition's premise, measured on fourteen traded cells rather than the
one eurusd 4h series it was found on. Sum of the first five autocorrelations:

| | speed | signed rate | ratio |
| --- | --- | --- | --- |
| EURUSD 1h | 0.789 | -0.023 | 34.9 |
| GBPUSD 1h | 0.957 | -0.024 | 40.5 |
| XAUUSD 1h | 1.047 | 0.003 | 358.9 |
| XAGUSD 1h | 1.221 | -0.042 | 29.2 |
| ETHUSD 4h | 1.915 | -0.062 | 31.0 |
| **traded median** | **+0.787** | **-0.012** | |
| `Volatility_75_Index` | **0.008** | -0.021 | 0.4 |
| `Step_Index` | **0.002** | -0.019 | 0.1 |

The registry quoted +0.381 against -0.047, a ratio of 8.1, from one series.
Across fourteen the median is **+0.787 against -0.012** - twice as large - and
it holds on every traded instrument.

**The generated markets give 0.002 to 0.054 for speed**, which is the control
that makes this a market property rather than a property of the statistic. A
constant-volatility process has no persistent speed, and these are measured
with the same code on the same frames.

## What this closes

* **`(position, log speed)` is the state worth having.** The speed half is
  real, large and present on every traded instrument.
* **The discrete direction process is not worth carrying.** It is built, it
  works on data that has a chain, and on markets it collapses to one coin.
  `hmm.Direction` stays in the package as the measurement rather than as a
  member - it is deliberately not a `Filter`, because naming it one would
  invite a comparison with `linear` that cannot be made.
* **The registry entry is updated** with both results rather than left
  pending.

What is *not* closed is the member that would use the speed half. `switching`
carries a regime posterior and `linear` carries a signed rate; a member whose
second state is `log|rate|` rather than `rate` is the thing the measurement
argues for, and it does not exist. That is the next item this line of work
suggests, and it is a different one from the item that was on the list.

The harness is `research/ideas/direction_chain.py`; the member is
`till_infinity/structures/statespace/hmm.py`.
