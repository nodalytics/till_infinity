# A band asked for by coverage, and the two different ways the old ones were wrong

**2026-10-17. `research/ideas/band_coverage.py`, `facade.Readout.covering`.**

`statespace/tails.py` has been measured and shipped since `one-bar-band.md` - a
Student-t with 3 to 5 degrees of freedom beat a Gaussian on PIT flatness **and**
on CRPS on 64 of 64 out-of-sample feed-frames - and **nothing had ever called
it**. `Readout.quantiles` and `Readout.band_covering` sat beside each other with
no rule saying which to use, and the rule is not guessable: a 2-sigma band is
about right and a 4-sigma band is breached 88 times more often than its
Gaussian label promises.

`Readout.covering(coverage)` is that rule, written once. The measured quantiles
serve the body, the fitted t serves the tail, and the tail is **anchored** to
the measured edge: each side of the widest central interval the grid holds is
grown by the ratio of the t's reach at the asked-for coverage to its reach at
that edge. The counted part sets the scale and the assumed part sets only the
shape.

## The harness, and the control that caught the first version

Every arm is asked for the same central coverage on the same bar and scored
against the **next** close, so nothing is in-sample. Three arms: `covering`,
`pure t` (`band_covering`, the fitted t over the filter's own sd) and
`gaussian` (`band(z)` at the Gaussian multiplier for the same coverage). The
control is a **Gaussian random walk** through the identical path, where the
Gaussian arm has to win and both t arms have to come out too wide.

**The first version of this harness was broken and the control is what said
so.** `noise` is the filter's measurement variance `R`, and it was set to 5% of
a typical bar move - which tells the filter it knows each close to a twentieth
of a bar. The gain goes to one, the filter sits exactly on price, and the
one-step predictive spread collapses. A nominal 0.95 band was breached **93.5%
of the time on a Gaussian random walk**, which is impossible for a correct
one-step predictive and is exactly the reading the control exists to produce.

So `R` is not guessed in the fixed version either. The walk has a known right
answer, so phase one sweeps `R` against it and reports which value calibrates:

| R, as a share of a typical bar move | gaussian `x` at 0.95, on the walk |
| ---: | ---: |
| 0.25 | 14.06 |
| 0.50 | 9.12 |
| 1.00 | 3.29 |
| **2.00** | **1.18** |
| 4.00 | 0.53 |

`x` is realised breach over wanted breach, so 1.00 is calibrated. A
level-tracking filter wants `R` at about **twice** a typical bar move, and the
panel then runs there and either side.

## Measured, fx_major 1h, 54,600 scored asks per cell

At the calibrated `R`:

| target | `covering` | pure t | gaussian |
| ---: | ---: | ---: | ---: |
| 0.950 | **1.02** | 1.34 | 1.28 |
| 0.990 | **1.02** | 1.41 | 3.07 |
| 0.995 | **1.03** | 1.35 | 4.84 |
| 0.999 | **1.10** | 1.52 | **14.80** |

And on fx_cross, where it is far more decisive - 62,400 asks:

| target | `covering` | pure t | gaussian |
| ---: | ---: | ---: | ---: |
| 0.950 | **1.14** | 3.65 | 3.58 |
| 0.990 | **1.08** | 10.26 | 13.22 |
| 0.995 | **1.17** | 16.82 | 24.22 |
| 0.999 | **1.91** | 50.62 | **103.75** |

**The two failures are different and they separate cleanly.** The Gaussian's
error grows with **coverage** at fixed `R` - 1.28 to 14.80 - which is the
shape being wrong, and it is worst exactly where stops and risk limits live.
The pure t's error is roughly flat in coverage and scales with **`R`** - 1.34
to 1.52 at `R = 2`, 9.15 to 60.38 at `R = 0.5` - which is the scale being
wrong, inherited whole from the filter. That is the PIT flatness of **43.05**
on record in `statespace-river-against-members.md` appearing as a number a
caller can feel.

## The whole sweep, which is what makes it not a cherry-pick

`x` at 0.999 on fx_major 1h, across every `R` the panel ran:

| R | `covering` | pure t | gaussian |
| ---: | ---: | ---: | ---: |
| 0.50 | 13.10 | 60.38 | 245.79 |
| 1.00 | 2.18 | 8.44 | 67.44 |
| **2.00** | **1.10** | 1.52 | 14.80 |
| 4.00 | 1.01 | 0.68 | 3.50 |

`covering` is the best-calibrated arm in **every** cell of this table and of
the 0.95, 0.99 and 0.995 ones beside it. At and above the calibrated `R` it is
flat - 1.10 then 1.01 - while the Gaussian moves 14.80 to 3.50 and the pure t
overshoots to 0.68.

**The walk control behaves, which is what licenses reading any of this.** The
gaussian arm reads 1.30, 1.27, 1.31, 1.28 across the four targets - flat and
near-calibrated, as a Gaussian band on Gaussian data must be - and both t arms
come out **too wide** there, at 0.00 to 1.38. Neither t arm is winning by being
arbitrarily wide.

## The honest limit: the immunity is one-directional

The unit tests pin the mechanism in a vacuum: hand the accessor a correct
residual grid and a wrong `spread`, and its error does not move while the pure
t's error is **proportional** to the mistake. On real bars that holds in one
direction only. At `R = 4`, twice too wide, `covering` reads 0.91 to 1.01 and is
still calibrated. At `R = 0.5`, twice too narrow, it reads 4.78 to 13.10 and is
not.

The reason is worth stating because it is not a bug to fix. The published grid
is built from the filter's own residuals, and a filter with too small an `R`
over-fits price, so the moves it is scored against have **already been absorbed
into its state**. The residual history then understates future dispersion, and
anchoring cannot repair a grid that is itself too narrow - it can only repair a
shape that is wrong. So the accessor is calibrated provided `R` is not set too
small, and phase one is how to tell.

## What this does not claim

It does not claim a direction. Every number here is a statement about
**dispersion** - how far the next close falls from where the filter is, at a
stated probability - and the desk's own record is that direction is a coin in
every test. A calibrated interval is worth having for stops, for barrier
geometry and for sizing, and for nothing that needs to know which way price
goes.
