# Fitted, a process describes a synthetic and not a market - until the bar reverses inside

**Measured 2026-10-15.** Code: [`family_fits.py`](../ideas/family_fits.py).
Ten families fitted by simulated method of moments to eleven asset classes on
sixteen pattern statistics.

[`pattern-fingerprint.md`](pattern-fingerprint.md) left one objection open. It
found every traded class sitting 210 to 460 from its nearest process family,
where in-family scatter is about 1 - but the families had **fixed** parameters,
so that was a statement about the library rather than about the families. A
GARCH fitted to EURUSD would obviously land closer than a GARCH fitted to
nothing. This fits them.

## Common random numbers, which is what makes a fit possible

The objective is a simulation, so it carries simulation noise, and a noisy
surface cannot be searched - a grid would be reading its own variance. The
innovations are therefore **drawn once as uniforms** and mapped through each
family's inverse distribution for whatever parameters are being tried, so
changing the degrees of freedom moves the objective smoothly instead of
redrawing a new world. The same uniforms serve every family, so two families
are compared on the same underlying randomness.

## The control: two of three

A known series is fitted first, at parameters held back, with its own
independent draws:

| planted | best fit | distance | runner-up | fitted parameters |
|---|---|---:|---|---|
| `garch(0.12, 0.85)` | **garch** | 4.4 | regime (8.0) | (0.18, 0.80) |
| `regime(0.01, 0.05, 8)` | **regime** | 5.6 | garch (82.3) | (0.01, 0.05, 12.0) |
| `student_t(3.0)` | jump | 5.6 | garch (8.6) | (0.01, 12.0) |

Two recover their own family with roughly the right parameters. The third does
not, and the failure is interpretable rather than alarming: **the fingerprint
does not separate fat-tailed i.i.d. families from each other.** A jump process
with rare large jumps and a Student-t both produce an i.i.d. fat-tailed return
with no clustering, and after aggregating sixteen sub-steps into a bar there is
little left to tell them apart. Read "fat-tailed i.i.d." wherever either name
appears below, and do not read a distinction between them.

## Fitted, the synthetics are described and the markets are not

Distance each family reaches at its best parameters, lower being closer:

| class | best family | fitted | distance | gaussian | student_t |
|---|---|---|---:|---:|---:|
| volatility | reversal | (−0.6) | **7.0** | 304 | 148 |
| step | reversal | (−0.6) | **6.1** | 301 | 143 |
| jump (Deriv) | reversal | (−0.3) | 15.4 | 81 | 80 |
| boom | garch | (0.30, 0.60) | 26.7 | 296 | 90 |
| soft | garch | (0.18, 0.80) | 70.2 | 926 | 325 |
| energy | garch | (0.18, 0.80) | 89.4 | 56,696 | 390 |
| **indices** | garch | (0.18, 0.80) | **94.2** | 44,614 | 398 |
| **fx majors** | garch | (0.18, 0.80) | **109.0** | 2,738 | 427 |
| baskets | garch | (0.18, 0.80) | 114.3 | 4,709 | 449 |
| **metals** | garch | (0.18, 0.80) | **130.3** | 12,075 | 490 |
| **fx crosses** | garch | (0.18, 0.80) | **130.9** | 8,642 | 475 |

Fitting does a great deal - fx crosses go from 334 unfitted to 131, metals from
376 to 130, indices from 385 to 94. **And a Deriv volatility index reaches 7.0
where no traded class gets below 70.** That contrast is the result: a fitted
process from this library is a fair description of a generated feed and is not
a description of a market.

Every traded class picks **GARCH at the same point**, (0.18, 0.80). That the
seven agree is worth more than the figure, which sits near the top of a coarse
grid and should be read as "high shock weight, high memory" rather than as an
estimate.

## The three statistics no parameterisation reaches

For each traded class, what the fitted GARCH still misses:

| statistic | class | fitted GARCH | `z` |
|---|---:|---:|---:|
| **imbalance**, 3-bar gap rate | 0.188-0.245 | 0.328 | 17.7-29.7 |
| **body share**, body / range | 0.438-0.470 | 0.576 | 18.0-23.5 |
| **CRT**, sweep and reclaim rate | 0.352-0.382 | 0.296 | 12.3-18.7 |

The same three, in the same direction, on fx majors, fx crosses, metals,
indices, energy, softs and baskets. Tails and volatility clustering are
**reachable** - a fitted GARCH matches a kurtosis of 47 and a size
autocorrelation of 0.21, which the unfitted library could not - and these three
are not.

**They are one phenomenon, not three.** A bar with a smaller body relative to
its range is a bar whose path went somewhere and came back. That same
behaviour takes out the previous bar's extreme and closes back inside it, which
is the CRT rate going up, and it fills the space a clean three-bar gap would
have needed, which is the imbalance rate going down. All three say that **the
path inside a real bar reverses more than the path inside any of these
processes' bars.**

That is a statement about microstructure, and it is one the construction makes
unreachable: every family here is a random walk at sub-bar resolution, with
dependence imposed only on the returns. Bid-ask bounce, liquidity provision and
market-making all act *within* the bar and none of them is represented.

## The prediction, tested

The section below was written before the test and is left as it stood. The
prediction had two halves: that a mean-reverting sub-bar term would close most
of the distance, and that it would do so by moving the three shape statistics
and **not** the tails. **The first half is confirmed and the second is
refuted.**

Three new families, all with a stationary term added to the price that does not
accumulate. `bounce` is the Roll model - an i.i.d. sign times a half spread -
on top of the fitted GARCH. `micro` replaces that sign with an
Ornstein-Uhlenbeck noise carrying its own reversion rate. `joint` fits the
efficient process and the bounce **together**.

| class | garch (previous best) | bounce | micro | joint | now best |
|---|---:|---:|---:|---:|---|
| fx majors | 109.0 | 16.3 | **4.8** | 6.9 | micro (1.0, 0.6) |
| baskets | 114.3 | 14.3 | **6.6** | 9.4 | micro (1.0, 0.6) |
| fx crosses | 130.9 | 18.8 | **6.9** | 11.2 | micro (1.0, 0.6) |
| energy | 89.4 | 46.1 | 18.3 | **7.4** | joint (0.38, 0.60, 0.7) |
| indices | 94.2 | 52.9 | 20.9 | **7.6** | joint (0.38, 0.60, 0.7) |
| metals | 130.3 | 33.5 | 11.0 | **8.5** | joint (0.38, 0.60, 0.7) |
| softs | 70.2 | 50.1 | 27.3 | **25.4** | joint (0.38, 0.60, 0.4) |

**Traded markets now fit as well as the generated feeds do.** Four point eight
to 8.5 against the Deriv families' own 6.1 to 9.9, where before the gap was 70
to 131 against 6 to 27. One mechanism and one or two parameters account for an
order of magnitude.

### The half that was wrong, and why it mattered

Adding stationary noise to a fat-tailed walk **thins the tails**: holding the
efficient price at the fitted GARCH, kurtosis fell from 17.0 to 13.8 at an
amplitude of 1 and to 1.7 at 4, because a sum of a fat-tailed term and an
independent bounded one is less heavy-tailed than the first alone. So the
efficient process has to be **fatter than it needed to be on its own** to
survive the dilution, which is why `joint` exists and why it wins wherever the
tails matter most. At (0.38, 0.60) the shock weight is twice what plain GARCH
wanted.

The prediction said this mechanism would leave the tails alone. It does not -
it trades them off, and reading the two parameters separately would have been
wrong.

### Two microstructures, not one

FX majors, crosses and baskets prefer `micro`: an Ornstein-Uhlenbeck noise at
amplitude 1.0 with a reversion rate of 0.6, on a GARCH already fitted. Metals,
indices and energy prefer `joint`: a fatter efficient process with a plain
i.i.d. bounce. That split is consistent across three classes each and is the
kind of thing worth re-testing rather than explaining now.

### What is left

The three statistics that no parameterisation could reach are gone from the
residuals. `body share` survives on only two classes, `imbalance` on none of
the traded ones, and `CRT` at `z` of 3.5 to 4.5. **The new leading residual is
`inside bar` on every traded class**, at `z` of 4.9 to 13.7: markets read 0.149
to 0.194 where the fitted families give 0.126 to 0.135.

An inside bar is a bar whose whole range sits within the previous bar's, which
is compression - a quiet bar following a wide one. That is a
volatility-of-volatility story rather than a microstructure one, and it is a
different mechanism from the one just added. It is also much smaller: a `z` of
13.7 on the worst class against the 18 to 30 the shape statistics carried
before.

## The prediction this makes

A family with **mean-reverting sub-bar dynamics** - a diffusive component plus
an Ornstein-Uhlenbeck microstructure term at tick level - should close most of
the remaining distance, and should do it by moving exactly those three
statistics and not the tails. That is a falsifiable prediction with a named
mechanism and a named signature, which is a better place to stop than a list of
distances.

It also says something about every synthetic null this desk builds: generating
returns and assembling bars from them produces bars whose **shape** is wrong in
a consistent, measurable way, however well the return distribution is matched.
Where a study depends on candle shape - engulfings, sweeps, inside bars,
imbalances - a return-level null is not conservative, it is mis-specified.
