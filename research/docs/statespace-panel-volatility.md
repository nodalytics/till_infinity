# Borrowing other instruments' volatility, which is what a factor is for

The relationship work found volatility co-movement that is large and
[contemporaneous](statespace-volatility-relationships.md): median
cross-instrument correlation of log-volatility `0.5170` against a rotation
null's `-0.0015`, with residuals after three principal components still
correlated up to `0.9422` along currency lines.

That report said contemporaneous structure cannot be turned into a directional
bet, which is true, and then **let it imply the structure cannot be used at
all, which is false.**

The harness is `research/ideas/panel_volatility.py`.

## Denoising a state is not predicting a relationship

A contemporaneous relationship improves the estimate of **now**. Own realised
volatility at `t` is a noisy measurement of an instrument's true volatility; a
cross-sectional factor is a *less* noisy measurement of the part it shares.
Volatility is persistent, so a better estimate of `t` is a better forecast of
`t+1` - **without the factor carrying any information beyond the
contemporaneous**.

This matters more than a relationship would, because every measured win on this
desk runs through `Q`: the `Q` clock at `+1055`, the clock and loop together at
`+1567`, the log-volatility ladder at `+191` to `+547` on 7 of 7 markets. And
unlike every trading result in this line of work, **an estimator improvement has
no cost gate** - it is not a trade, so there is no spread to clear.

## The baseline is HAR and the factor is leave-one-out

Beating an AR(1) on realised volatility is easy and means nothing. The baseline
is **HAR** - the own value, the own five-span mean, the own twenty-two-span mean
- which captures the long memory that makes volatility forecastable at all. The
panel arm is that model plus one term, so the comparison is three parameters
against four, scored out of sample.

Every factor excludes the instrument being forecast, or it would predict itself.
Standardisation uses training-half statistics only. Spans are cut from **aligned
bars**, not from each instrument's own index - taking every 24th bar separately
puts the span boundaries on different wall-clock windows whenever two
instruments keep different sessions, which is how the first run reported "not
enough common spans" on a universe sharing 13,000 bars.

## The planted arm says where the test has power, and the null is not zero

| planted loading | median gain | pooled `t` |
| --- | ---: | ---: |
| dominant (3.0) | -0.0003 | -0.12 |
| **strong (1.5)** | **+0.0056** | **+3.15** |
| common (0.8) | +0.0008 | +0.16 |
| weak (0.4) | -0.0007 | -1.03 |
| **none (0.0)** | -0.0032 | **-4.07** |

Two things here decide how everything below is read.

**The response is not monotone, and that is the mechanism rather than a defect.**
At a dominant loading own volatility *is* the factor - `own = 3*common + idio` -
so HAR already carries it and a cross-sectional term adds nothing. At a weak
loading there is nothing to borrow. The factor pays in a middle band where own
volatility is a noisy but not dominant proxy.

**And the null is negative, not zero.** With no factor the extra parameter costs
a pooled `t` near `-4` out of sample. So every arm is judged against a rotation
null carrying the identical penalty.

## Each universe has a working specification, and they are different ones

| universe | factor | median gain | pooled `t` | rotation null |
| --- | --- | ---: | ---: | ---: |
| **equities (21)** | **nearest-5** | **+0.0427** | **+4.85** | -3.19 |
| equities (21) | global | +0.0186 | -1.39 | -4.05 |
| traded FX (20) | nearest-5 | -0.0096 | **-5.30** | -0.37 |
| traded FX (20) | global | +0.0043 | -3.30 | -2.00 |
| **FX crosses, 6 or fewer neighbours** | **currency label** | **+0.0314** | **+2.73** | +0.27 |
| FX, more than 6 neighbours | currency label | -0.0081 | -4.61 | -8.11 |
| generated (36) | global | -0.0029 | -5.86 | - |

### A label-based neighbourhood beats a measured one on FX

The currency factor - the mean over instruments sharing a currency - is a
different regressor per instrument, which is what residual correlations of 0.94
along currency lines imply. Twenty instruments spanning eleven currencies have
about eleven drivers, not one.

Its gain falls with the neighbour count exactly as the mechanism predicts -
**linear `-0.4682`, rank `-0.3414` over all 20 instruments, nothing chosen** -
because a USD pair shares a currency with 14 to 16 others and its "currency"
factor is the global one again, while a cross shares with 6 and gets something
specific. The split at six was decided by that mechanism before the result, and
each half is nulled separately.

**Selecting neighbours by correlation is actively harmful on FX**: `-5.30`
against a rotation null of `-0.37`, worse than its own null. Picking the top five
by training-half correlation *overstates* those correlations, so the fit
over-trusts the factor and it fails out of sample; under rotation the selection
picks noise, the fit shrinks the weight, and little harm is done. **A label
cannot overfit**, which is the same lesson the exploit search reached from the
other direction: no search rule beat stating the mechanism.

### And a measured neighbourhood wins on equities, which was predicted wrongly

The prediction recorded before this ran was that equities share one dominant
market factor, so a global mean would be their right basis. **The opposite
happened**: nearest-5 reads `+4.85` and global reads `-1.39`.

The explanation is the one that also explains FX, which is why it is worth
keeping rather than patching. **Equity volatility correlations are homogeneous
and high**, so taking the top five of twenty is barely a selection and the
factor is a *cleaner* estimate of the same market driver than a twenty-one-name
mean, which dilutes it with weak loadings. **FX correlations are heterogeneous**,
from 0.46 to 0.90 depending on the pair, so the same top-five rule is a real
selection and overfits.

So the rule is not "labels beat measurement" but **"measurement beats labels only
where the candidates are interchangeable"**, and the correlation spread tells you
which case you are in before you fit anything.

### The synthetics are the control and read nothing

`-0.0029` median and a pooled `-5.86` on 36 generated instruments, whose
log-volatility correlation is `-0.0133` with 0 of 12 pairs beating a rotation
null. There is no factor to borrow and the panel earns the bare parameter
penalty - on the same pipeline, the same bars and the same estimator as the arms
that do work.

## What to use

* **On equities, a nearest-five volatility factor**, for `+4.3%` of the
  out-of-sample log-volatility forecast MSE at a pooled `t` of `+4.85`.
* **On FX crosses, the currency-label factor**, for `+3.1%` at `+2.73` - and
  **not** on USD majors or metals, where it costs `-4.61`.
* **Never select the neighbourhood by correlation on a heterogeneous universe.**
  Check the spread of candidate correlations first; it decides which rule
  applies.
* **Judge against a rotation null, never against zero.** The extra parameter
  costs about `-4` in pooled `t` on its own.

## What this does not establish

The equity arm rests on **21 instruments**, because only 21 of 439 in the cache
clear the 4,000-bar floor at 1h. The direction and the null separation are
clear; the width of the universe is not.

**And there are no commodities in this cache** - no sugar, cocoa, coffee, oil,
gas or copper at any frame. Softs and energies would test the same mechanism on
a third correlation structure, and they would have to be fetched first rather
than stood in for by the metals.

Whether a `+3%` to `+4%` reduction in volatility-forecast error moves the clock,
the ladder or sizing is **not measured here.** It is free of trading cost, which
is why it is worth measuring, and it is not the same claim as measuring it.

## Related

* [Volatility relationships](statespace-volatility-relationships.md) - the
  contemporaneous structure this borrows from, and the currency-line residuals
* [Turning a relationship into a bet](statespace-exploiting-relationships.md) -
  the directional route, which failed, and the selection lesson this repeats
