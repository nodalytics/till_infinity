# Two relationships no pair screen can see, and the seven that were there

[The relationship screen](statespace-relationship-screen.md) and
[its episodic form](statespace-episodic-relationships.md) both test a
**contemporaneous spread between two legs**. Two classes of relationship are
invisible to that by construction, and the objection that prompted this was
that relationships were there regardless.

**They were.** The strongest readings in any of this work are here - `DF t` of
`-77.83` against a null best of `-4.49` - and they are arithmetic rather than
statistical. Both halves of that matter.

The harness is `research/ideas/lead_lag_and_baskets.py`.

## A lead is not a spread, and a basket is not a pair

If one instrument moves and another follows an hour later, the two are strongly
related and their same-bar spread is noise. Cointegration tests the level
difference *now*; a lead lives in `corr(d x_t, d y_{t+k})` for `k != 0`, and no
amount of windowing a spread will surface it. It is also the only relationship
shape here that would be **directly tradeable** rather than needing a spread
position, which matters on a desk that has found direction closed everywhere
else.

A basket needs three legs. A currency triangle is the standard case, and no
*pair* within one need be cointegrated at all.

## The planted arms, which is why the nulls below mean anything

| planted | same-bar corr | peak away from zero | at lag |
| --- | ---: | ---: | ---: |
| a lead of 0 bars | +0.9566 | 0.0211 | 9 |
| a lead of 1 bar | +0.0038 | **0.9569** | **1** |
| a lead of 3 bars | +0.0173 | **0.9565** | **3** |
| a lead of 6 bars | +0.0065 | **0.9570** | **6** |

A planted lead is **invisible to a same-bar measure and fully visible to this
one**, recovered at exactly the planted lag.

| planted | basket `t` | best **pair** among the same three legs |
| --- | ---: | ---: |
| a basket, noise 0.5 | **-63.53** | -1.22 |
| a basket, noise 2.0 | **-63.63** | -2.85 |

**That second column is the whole argument.** A stationary three-leg
combination whose best pair reads `-1.22` - a pairwise screen over that
universe reports nothing and is wrong. The blindness is not marginal, it is
total.

## Leads: a null, and the exceptions are structural

| | pairs | median peak away from zero | max |
| --- | ---: | ---: | ---: |
| traded | 190 | 0.0194 | 0.0418 |
| block-shuffled null | 570 | 0.0166 | 0.0307 |

6 of 190 exceed the null's maximum, which sounds like something until the
magnitudes are read: the largest is **0.0418**, about 0.2% of return variance.
Against a round trip of roughly 3.5% there is nothing there at any size.

And the six are explainable without a lead. Four are EUR crosses sharing a leg
with their peak at lag **±1** - `EURGBP/EURCHF`, `EURJPY/EURGBP`,
`EURUSD/EURGBP`, `EURCHF/EURAUD` - which is what non-synchronous bar closes
between instruments quoting a common currency produce. `XAUUSD/XAGUSD` peaks at
lag 8 with same-bar correlation of **0.7718**, so a 0.03 reading eight bars out
is a shadow of a strongly correlated pair rather than a lead.

**No instrument in this universe leads another by an hour or more.**

## Baskets: seven relationships, and all seven are identities

| | triples | best | 1st pct | median |
| --- | ---: | ---: | ---: | ---: |
| traded | 400 | **-77.83** | -69.37 | -1.56 |
| block-shuffled null | 1,200 | **-4.49** | -3.73 | -1.76 |

**7 of 400 beat the null's best, by a factor of 17**, and then it stops dead -
the eighth triple reads `-3.72`, below the null. A cliff that sharp is not a
distribution tail, it is two different kinds of object.

The seven, with the weights fitted on the first half:

| legs | w1 | w2 | residual sd | range/cost |
| --- | ---: | ---: | ---: | ---: |
| EURUSD/USDCHF/**EURCHF** | +1.000 | +1.000 | 1.4 bp | 0.040 |
| EURUSD/GBPUSD/**EURGBP** | +1.000 | -1.000 | 1.2 bp | 0.036 |
| EURUSD/AUDUSD/**EURAUD** | +1.000 | -0.999 | 1.5 bp | 0.042 |
| GBPUSD/USDJPY/**GBPJPY** | +1.000 | +1.000 | 0.8 bp | 0.023 |
| USDJPY/USDCHF/**CHFJPY** | +1.000 | -1.000 | 3.2 bp | 0.091 |
| USDJPY/AUDUSD/**AUDJPY** | +1.000 | +1.000 | 0.8 bp | 0.023 |
| EURUSD/USDJPY/**EURJPY** | +1.000 | +1.000 | 0.8 bp | 0.024 |
| *EURUSD/USDJPY/USDCAD* | *-0.675* | *+0.161* | *118.9 bp* | *3.396* |

**Every one is a currency triangle and every weight is exactly ±1.000.** In
logs `log(EURCHF) = log(EURUSD) + log(USDCHF)` is an identity, not a
relationship, and the residual standard deviation of **0.8 to 3.2 basis points**
is the bid-ask spread and price rounding. `range/cost` of 0.023 to 0.091 says
the residual moves 2% to 9% of a round trip; triangular arbitrage is also the
most competed trade in the asset class and does not survive to an hourly bar.

The last row is the contrast. `EURUSD/USDJPY/USDCAD` is not a triangle, so its
weights are fitted rather than forced (`-0.675`, `+0.161`), its residual is
**119 bp** - a hundred times larger - and its `t` of `-3.72` is below the null.

## What this is worth, which is not nothing

The screen found, in live data and without being told, the seven relationships
that **must** exist, recovered their coefficients to three decimal places, and
found nothing else. That is a positive control passing on real data rather than
on a simulation, and it is the strongest evidence in this whole line of work
that the method functions.

**Keep the triangles as a standing positive control.** Any future relationship
screen on an FX universe that does not return them at `t` past `-50` with
weights at ±1 is broken, and that is a far better test than a planted arm
because it uses the data the screen will actually be run on.

## What to use

The objection was right and the answer is still no. There were relationships
the pair screens could not see; they are definitional, they clear 2% to 9% of
their trading cost, and everything that is not an identity falls below a null
built from the same data with the dependence removed.

Three blind spots are now closed - the broken relationship, the lead, and the
basket - and the one still open is **timescale**: all of this is 1h bars. A
lead of a few minutes would not appear at this sampling, and that is the
remaining place for a relationship to hide.

## Related

* [The relationship screen](statespace-relationship-screen.md) - the pairwise
  form, the live-ratio defect, and the block-shuffled null reused here
* [N-leg spreads](statespace-n-leg-spreads.md) - the generalisation to widths
  two through five, where the cycle rule separates identities exactly and
  nothing else survives at any width
* [The episodic form](statespace-episodic-relationships.md) - the relationship
  that holds and then breaks
