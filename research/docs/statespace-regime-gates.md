# Five regime gates, and the duty cycle that explains two of them

Five ideas from the reading pile have the same shape - **one scalar computed on
a rolling window, proposed as a switch for when to trade** - so they got one
harness and one control. `research/ideas/regime_gates.py`.

| statistic | the claim |
| --- | --- |
| Lempel-Ziv complexity of binarised returns | low LZ means repeating patterns, so "deploy momentum aggressively" |
| Gini of absolute returns | converges to a **universal 0.84 +/- 0.03** in self-organised critical systems; deviations mean-revert and signal transitions |
| Kuramoto order parameter | phase synchronisation across scales; `R -> 1` is a crisis |
| RQA laminarity | drops sharply as the market goes coherent-to-chaotic, "the structural crack before the break" |
| Wasserstein drift between consecutive windows | a distributional change detector, to be raced against a fitted chain |

## The control is the whole harness

A gate that halves the time in the market changes the result whether or not it
knows anything. Each gate takes the claimed tercile of its statistic and is
scored against **400 random subsets of exactly the same size**; what is
reported is the real gate's z-score inside that distribution. Inside `+/- 2`
is a duty-cycle effect wearing a physics hat.

That is not a general scruple. Every pause rule this desk has tested matched
random pausing at the same duty cycle, and nothing here deserved a weaker test
than those got.

Two targets, because one of them is already known to be findable. **Direction**
- does the next bar continue the last one - would be new. **Magnitude** - does
the next bar beat the window's median absolute move - is already predictable
here, and most of these statistics are volatility-sensitive, so this column
exists to catch a gate claiming a directional edge it is getting from
clustering.

## The verdict: five nulls on direction, two magnitude effects, one of them explained

| statistic | traded, median z | generated, median z | traded magnitude | generated magnitude |
| --- | ---: | ---: | ---: | ---: |
| Lempel-Ziv | -0.87 | -0.97 | -0.25 | -0.88 |
| Gini | +0.10 | -0.58 | **+1.97** | **+1.86** |
| Kuramoto | +0.34 | +0.31 | **+2.08** | +0.23 |
| laminarity | -0.36 | -0.39 | -0.95 | +0.32 |
| Wasserstein | +0.39 | +0.09 | -0.04 | +0.34 |

**On direction every one is null** - median z from -0.87 to +0.39 across 14
traded cells, and the share of cells past `|z| > 2` runs 0.00 to 0.14 against
the 0.05 chance expects. No gate selects windows in which direction is more
predictable than a random selection of the same size does.

**The Gini gate's magnitude effect is explained by its own control.** +1.97 on
traded markets and **+1.86 on known-generator markets with no regime to find**.
It is reading volatility clustering: the Gini of a window's absolute returns is
high when one move dominates it, a window with one dominant move is in a
volatility expansion, and the next bar is larger. The gate works and it knows
nothing.

**Kuramoto is the only one that separates** - +2.08 traded against +0.23
generated, on magnitude only. That separation is real and it is also not worth
having: magnitude is already modelled here by the log-volatility ladder, which
is worth +191 to +547 nats on 7 of 7 traded markets. A 2-sigma gate adds
nothing to a model that size.

## The Gini anchor, tested twice, dead both times

`0.84 +/- 0.03` is an absolute number, so it can simply be computed. The Gini
of the absolute values of a **Gaussian** is `2 Phi(1/sqrt 2) - 1 = 0.520`
analytically, so 0.84 is a real constraint and not an artefact of taking
absolute values.

| | per-bar Gini | **per-avalanche Gini** | avalanche duration Gini |
| --- | ---: | ---: | ---: |
| real markets | 0.483 - 0.511 | 0.528 - 0.621 | 0.309 - 0.325 |
| `Volatility_*`, `Step`, `Jump` | 0.408 - 0.416 | 0.445 - 0.458 | 0.325 - 0.337 |
| claimed | **0.84 +/- 0.03** | **0.84 +/- 0.03** | |

**Zero of roughly 50,000 windows across 22 cells landed inside 0.84 +/- 0.03.**

The second column is the repair, and it matters that it was run. In a sandpile
the 0.84 is the Gini of *event* sizes - one toppling cascade, integrated over
however many time steps it lasts - and "the distribution of absolute returns"
silently replaces the event with a single sample of it. A maximal run of
same-signed returns is the nearest thing a price series has to a cascade: it
starts, it builds, it stops. Measured properly the number rises from 0.49 to
0.53, in the right direction and nowhere near far enough. **So the claim fails
in its own terms, not only in a careless translation of it.**

**And the duration column says why there is nothing there.** A Gini of 0.31 on
avalanche *lengths* means runs are short and all much the same length - which
is what a near-fair coin produces, and which is exactly the independently
measured result that direction is a coin. A sandpile has power-law avalanche
durations and a far more unequal distribution. There are no cascades in a price
series' sign sequence to have a universal Gini; there are coin flips.

The real-against-generated gap is consistent throughout - 0.49 against 0.41 per
bar, 0.53 against 0.45 per avalanche - so real markets *are* more concentrated
than Brownian ones, by about 0.08 of Gini. That is the fat tails, it is a real
difference, and it is a fifth of the way to the claim.

## Laminarity was implemented from a corrected definition

The source describes laminarity as counting **diagonal** lines in the
recurrence matrix. That is determinism. Laminarity counts **vertical** lines -
states that stay put, rather than states that repeat a trajectory. The
implementation here uses the vertical definition, as the mean length of runs
during which the series stays within half a standard deviation of where the run
began, which is what a vertical line is and costs one pass instead of `n^2`.

Worth recording because a statistic implemented from a wrong definition tests
nothing, and the wrong definition was the one in print.

## Kuramoto was implemented without EMD, deliberately

The prescription is EMD into intrinsic modes, Hilbert phase of each, then
`R = |mean(exp(i theta))|`. EMD's modes are data-dependent and not reproducible
across windows, which makes the statistic **incomparable between windows** -
the opposite of what a gate needs, since a gate's whole job is to compare now
against then. The modes here are fixed band-pass filters at periods 4, 8, 16
and 32, with the quadrature pair taken from the filtered series and its own
difference.

If someone wants the EMD version measured, the finding to beat is +0.34 on
direction, and the first question to answer is how its modes are made
comparable across windows.
