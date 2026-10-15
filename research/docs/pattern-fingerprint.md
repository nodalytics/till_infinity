# Pattern fingerprints: the matcher works, and no simple process describes a market

**Measured 2026-10-15.** Code:
[`pattern_fingerprint.py`](../ideas/pattern_fingerprint.py). Sixteen scale-free
statistics, ten process families, ten replicates of 20,000 bars each, against
every instrument in the cache at 1h and 4h.

Every pattern study here ends the same way: the pattern is found exactly and it
occurs at the rate a walk produces it. That is a dead end as a search for edge
and a starting point as a measurement - if pattern rates are set by the
generating process, the **vector** of pattern rates is a fingerprint of that
process, and an instrument can be matched to the family whose fingerprint it
reproduces.

Two uses, neither a trading signal: a **better null per instrument**, since
testing a pattern against a generic Gaussian walk is testing it against the
wrong process; and a **targeted residual**, since where an instrument departs
from its best-fit family is where the structure is.

## The bars are generated, not decorated

Pattern rates depend on wick structure, so OHLC cannot be a close series with
wicks bolted on - that choice would decide the answer. Every family is
simulated at **sub-bar resolution** (24 steps) and aggregated, so the high and
low emerge from the same process that makes the close.

Calibrating the families took one correction worth recording. An AR(1) at the
sub-bar level with a coefficient of 0.25 leaves a **bar-level** autocorrelation
of +0.003 - a momentum family indistinguishable from Gaussian, which would have
appeared as a confusion in the matrix rather than as the parameterisation
mistake it was. Swept: 0.50 gives +0.028, 0.70 gives +0.050, 0.85 gives +0.176,
0.90 gives +0.244. And the mirror does not mirror - -0.90 reaches only -0.099,
because alternating sub-steps cancel inside a bar instead of accumulating.

## The control: 97 of 100

Each family is simulated ten times, the library is rebuilt without one
replicate, and the held-out one is matched back.

| | recovered |
|---|---:|
| gaussian, garch, ou, momentum, reversal, regime, lattice | 10/10 |
| student_t, jump, drift | 9/10 |
| **total** | **97/100 against 0.10 by chance** |

The three errors are the two fat-tailed families swapping once each and one
drift read as Gaussian - the confusions a correct matcher should make. So the
fingerprint identifies, and what follows can be read.

## No family describes a traded instrument

`distance` is the mean squared z-gap to the best family, scaled by that
family's own replicate-to-replicate spread. **A distance near 1 means the
instrument sits inside the family's own scatter.**

| class | feeds | best family | distance |
|---|---:|---|---:|
| boom, crash, dex | 3-7 | student_t | **20-23** |
| drift_switch | 3 | student_t | 27 |
| jump | 5 | student_t | 63 |
| step, skew_step, multi_step | 2-4 | ou | 108-117 |
| volatility | 20 | student_t | 115 |
| soft | 5 | student_t | 211 |
| **fx majors** | 7 | student_t | **235** |
| basket | 3 | garch | 250 |
| **fx crosses** | 16 | student_t | **334** |
| energy | 3 | garch | 358 |
| **metals** | 4 | garch | 376 |
| **indices** | 14 | garch | 385 |
| equity | 1 | student_t | 458 |

The generated feeds land at 20 to 130, which is what actual diffusions should
do against simulated ones. **Every traded class lands between 210 and 460**, so
the family labels above are not matches - they are the least-bad of ten poor
options, and no process in this library is a description of a market.

## How markets differ, and it is the same four statistics everywhere

This is the useful output. For each class, the statistics carrying most of the
distance from its own best family:

| statistic | traded instruments | best family | direction |
|---|---:|---:|---|
| **imbalance** (3-bar gap rate) | 0.18-0.25 | 0.28-0.32 | markets have **fewer** gaps |
| **body share** (body / range) | 0.43-0.50 | 0.55 | markets are **wickier** |
| **kurtosis** | 47-74 | 3.5 | an order of magnitude fatter |
| **size ac** (volatility clustering) | 0.21 | 0.00-0.13 | beyond GARCH at these constants |
| **inside bar** rate | 0.16-0.21 | 0.11 | more compression |

Four of the five recur on fx majors, fx crosses, metals, indices, energy, soft
and baskets alike, and **in the same direction every time**. Two of them are
new here: markets leave *fewer* three-bar imbalances than any simple process,
and their bars carry *more wick per unit of range*. The other two are known
qualitatively and are now sized - a kurtosis of 47 to 74 against 3.5 for a
t(4)-driven diffusion, and a volatility-clustering autocorrelation of 0.21
where GARCH at `statespace/nulls.py`'s constants gives 0.13.

**That is the transferable statement.** A null generator fit to be a real
market's twin has to reproduce those five numbers; none of the ten standard
families does, and the fingerprint says exactly which dials are wrong rather
than that something is.

## Two incidental findings

**`Range_Break_*` carries a kurtosis of 14,255 and a skew of -92.25** at 1h,
which is one observation dominating 40,000 bars. That is a data artefact or a
generator reset rather than a process property, and it is worth knowing before
that family is used as a control anywhere - it is the level positive control in
`range-break-is-the-level-positive-control`.

**Two of the sixteen statistics carry nothing.** `wick tilt` reads 0.000 on
every family, because the median upper and lower wick are equal for any
symmetric process; and `inside bar` tracks `engulf` almost exactly on the
simulated families, since for a symmetric process the two have the same
probability. They separate on **real** data - inside bars run 0.16-0.21 against
an engulf rate near 0.10 - which is itself an asymmetry worth keeping, but as
family discriminators they are dead weight.

## What this does not do

It does not fit the families. The parameters are fixed - `t` at four degrees of
freedom, GARCH at 0.02/0.10/0.88, a jump intensity of 0.002 - so "no family
describes a market" is a statement about **this library**, not about the
families in general. A GARCH fitted per instrument would land much closer, and
the proper version of this is indirect inference: fit each family's parameters
to each instrument, then compare the best achievable fits. The five statistics
above are what such a fit would have to hit.
