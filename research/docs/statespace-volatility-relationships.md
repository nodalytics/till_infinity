# The relationships are real, large, and all of them contemporaneous

Every price screen in this line of work came back null: no pairwise
cointegration, nothing episodic, no lead at 1h or 3m, and nothing at widths two
through five beyond currency identities. The objection that relationships were
in there regardless was correct, and the reason the screens missed them is
structural rather than statistical.

**They were looking in price space.** This desk's standing result is that
volatility is forecastable and direction is not, so the prior should always have
been that any relationship here is between **volatilities**. A price screen
cannot see one: two instruments can share a single volatility process with
independent signs and show no cointegration, no correlation and no lead.

The harness is `research/ideas/volatility_relationships.py`.

## The planted arm, which shows the blindness is total

| planted | price `DF t` | return corr | **vol corr** | vol `DF t` |
| --- | ---: | ---: | ---: | ---: |
| shared volatility, free signs | -1.56 | -0.0140 | **+0.9746** | -23.06 |
| unrelated | -1.63 | -0.0044 | -0.0250 | -22.38 |

One AR(1) log-volatility process driving two independent sign streams. The price
screens read **nothing**; volatility space reads **0.97**. Every null in the
price work is consistent with a relationship of this shape being present
throughout.

## The null is a rotation, because a shuffle would destroy the process

The block shuffle used for the price work preserves marginal tails, which was
the right property there. **It is the wrong null here**: scrambling day-long
blocks destroys volatility clustering across them, so it would damage the very
process under test and make any vol relationship significant against a vol-free
null.

A **circular rotation** is correct - the identical series at a random offset, so
every autocorrelation, all clustering and all long memory survive exactly
because it *is* the same data, and only the cross-relationship is destroyed. The
offset avoids multiples of a day so shared time-of-day structure does not
survive it and get scored as a relationship.

## Volatilities co-move, and it is not close

| | pairs | max | 99th pct | median |
| --- | ---: | ---: | ---: | ---: |
| traded, vol correlation | 107 | +0.8970 | +0.8763 | **+0.5170** |
| rotation null | 321 | +0.3374 | +0.2849 | **-0.0015** |
| traded, vol rank correlation | 107 | +0.8545 | +0.8352 | +0.4769 |
| rotation null | 321 | +0.3624 | +0.3079 | +0.0022 |

**104 of 107 pairs exceed the null's maximum.** A median of 0.52 against a null
median of zero is not a tail finding that needs a multiplicity argument - it is
the typical pair.

### By class, including the synthetics as the control

| class | pairs | median corr | max | beat null |
| --- | ---: | ---: | ---: | ---: |
| crypto | 1 | **+0.8496** | +0.8496 | 1 |
| fx JPY crosses | 6 | **+0.8232** | +0.8970 | 6 |
| metals | 1 | **+0.6883** | +0.6883 | 1 |
| fx majors | 28 | **+0.6176** | +0.8464 | 25 |
| fx cross x JPY cross | 12 | +0.5146 | +0.7485 | 7 |
| fx cross x major | 24 | +0.5059 | +0.7507 | 18 |
| JPY cross x major | 32 | +0.4624 | +0.7894 | 19 |
| crypto x **synthetic** | 4 | +0.0693 | +0.1038 | **0** |
| major x **synthetic** | 10 | +0.0480 | +0.1203 | **0** |
| **synthetic x synthetic** | 12 | **-0.0133** | +0.1053 | **0** |
| JPY cross x **synthetic** | 4 | -0.0407 | -0.0178 | **0** |

The ordering is a factor structure: same-class highest - crypto 0.85, JPY
crosses 0.82, metals 0.69, majors 0.62 - and cross-class lower at 0.46 to 0.51.
Class-level drivers on top of a global one.

**Every generated pair reads zero**, against each other and against every real
class, and not one of 33 beats the null.

### What that control does and does not establish

It establishes that **the estimator does not manufacture correlation**. That is
what validates the 0.52: a procedure that returns zero on 33 pairs of processes
with no connection is not inventing the number it returns on real ones.

It does **not**, on its own, establish that the venue is not modulating
volatility across its book. Constant-volatility GBM has no volatility variation
beyond sampling noise, so two generated instruments have almost nothing *to*
correlate and a reading of zero is close to automatic. The evidence against
common modulation is the drift test in
[the venue spec check](statespace-venue-spec.md) - realised volatility scattering
across windows by no more than sampling permits - not this table.

## The tails co-move harder than the middles

| | pairs | max | 99th pct | median |
| --- | ---: | ---: | ---: | ---: |
| traded, lift at 0.99 | 190 | +0.6650 | +0.6350 | **+0.1275** |
| rotation null | 570 | +0.0566 | +0.0463 | **+0.0004** |

`lift` is `P(|y| past its 99th percentile | |x| past its own)` less the
unconditional rate, so zero is independence. **177 of 190 exceed the null's
maximum.**

The class breakdown agrees with the volatility one. Real classes run +0.09 to
+0.17 at the median - fx crosses 0.1700, cross x JPY 0.1625, major x metal
0.1396, crypto x major 0.0921 - while **synthetic x synthetic reads +0.0011
over 45 pairs and crypto x synthetic reads -0.0000 over 30, with 0 of 165
generated pairs beating the null.** Given one instrument in its worst 1% of moves, the median other
instrument is 13 points more likely to be there too, and `NZDUSD/AUDUSD` is 67
points more likely.

**This is the quantity that decides whether diversification survives the day it
is needed, and the answer is that it does not.**

## Three factors are the wrong basis, and the residuals say which is right

Three principal components carry **63.2%** of return variance. After removing
them the residual correlations are still enormous - up to **0.9422** against a
rotation null's maximum of **0.0263**, with **174 of 190 exceeding it**.

Every one of the strongest residual pairs shares a currency:

| pair | \|residual corr\| |
| --- | ---: |
| EURAUD/AUDJPY | 0.9422 |
| AUDUSD/AUDJPY | 0.9091 |
| GBPUSD/GBPJPY | 0.8990 |
| USDCHF/CHFJPY | 0.8741 |

So the natural factors are **the currencies, not the components** - the same
node-and-edge structure the currency-identity rule exposed at three legs. A
20-instrument book spanning eleven currencies has roughly eleven drivers, and a
three-factor model leaves nine of them in the residual.

## And every lagged measure is null

| measure | kind | result |
| --- | --- | ---: |
| volatility correlation | **contemporaneous** | **104 of 107 beat the null's max** |
| tail co-dependence | **contemporaneous** | **177 of 190** |
| post-factor residuals | **contemporaneous** | **174 of 190** |
| volatility spillover | *lagged* | **0 of 106** |
| price lead-lag at 1h | *lagged* | 0 of 190 |
| price lead-lag at 3m | *lagged* | 0 of 190 |
| cointegration, widths 2-5 | *lagged* | 0 of 1,625 |

Spillover peaks at a median `0.1688` against the null's `0.1101` and **0 of 106
exceed the null's maximum of `0.4552`**. Every peak sits at lag ±1, immediately
beside a same-span correlation of 0.56 to 0.81, which is leakage from the
contemporaneous relationship rather than a lead.

**Everything contemporaneous is enormous and everything lagged is null.** That
is one finding, not six, and it is the reason the directional work could not
succeed: a directional bet needs a *lead*, and there is none in price at two
sampling rates or in volatility.

## What this is worth, which is not a trade

These are **risk** relationships, not **forecast** relationships, and they
cannot be converted into directional bets - a contemporaneous relationship says
what is happening now, not what happens next.

They are still economically live, on the sizing side rather than the entry side:

* a tail lift of 0.13 to 0.67 means **the book's legs go wrong together**, so
  any risk estimate assuming independence understates ruin at exactly the
  moment it matters;
* a vol correlation of 0.52 means the same for ordinary position sizing;
* eleven currency drivers behind twenty instruments means the book's real
  exposure is far more concentrated than its instrument count suggests.

The growth-optimal fraction on this book is currently **zero**, so there is no
edge for better sizing to scale. What this changes is the denominator: risk
removed is compounding gained, and it needs no new signal to collect.

**And there is a forecast use, which this section first missed.** A
contemporaneous relationship cannot predict direction, but it can improve the
estimate of *now* - and volatility is persistent, so a less noisy estimate of
today is a better forecast of tomorrow without the factor carrying any
predictive information of its own.
[The panel estimator](statespace-panel-volatility.md) measures it: `+4.3%` of
out-of-sample log-volatility forecast error removed on equities at a pooled `t`
of `+4.85`, and `+3.1%` on the FX crosses with few currency neighbours. Unlike
every trading result here, an estimator change has **no cost gate**.

## What to use

**Screen relationships in volatility space, not price space**, and use a
rotation null rather than a shuffle whenever the marginal's own time structure
is part of the hypothesis.

**Treat a currency basis as the factor model.** Three components is
demonstrably too few by a factor of three, and the residual tells you the
missing structure is per-currency.

**Do not look for a lead again without a reason.** Price at 1h, price at 3m and
volatility at daily spans are three independent attempts, all null against
matched nulls, with planted arms proving each detector works.

## Related

* [N-leg spreads](statespace-n-leg-spreads.md) - the price side, widths two to
  five, and the currency-identity rule this result reuses
* [Leads and baskets](statespace-leads-and-baskets.md) - the price lead arm and
  the triangles as a positive control
* [The relationship screen](statespace-relationship-screen.md) - where the
  pairwise work started, and the cost correction
