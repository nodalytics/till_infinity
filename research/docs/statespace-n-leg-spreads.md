# N-leg spreads, where the degrees of freedom are the adversary

Two legs found nothing.
[Three legs](statespace-leads-and-baskets.md) found seven relationships and all
seven were currency-triangle identities. The generalisation to `N` is not more
of the same, because two things change with width and **both of them flatter the
result**.

The harness is `research/ideas/n_leg_spreads.py`.

## Every extra leg buys stationarity, and most baskets inherit a triangle

A spread of `N` legs fits `N-1` weights, and more weights mean more ways to make
a residual look stationary. So a threshold measured at one width says nothing at
another, and every width here gets its own null.

The second problem is larger. `{EURUSD, USDCHF, EURCHF, GBPUSD}` contains the
`EURCHF` triangle, so it inherits `t = -77` without anything new being true.
Past three legs the identities dominate **by count**, and a table that does not
separate them is a table of identities wearing different names.

### Identity is exactly computable, not a judgement

Treat each instrument as an edge between its two currencies. The log prices
satisfy an exact linear relation if and only if the edge set contains a
**cycle**:

```
edges > nodes - components
```

`EURUSD/USDCHF/EURCHF` is three edges on three connected nodes, so `3 > 2` and
it is an identity. `EURUSD/USDJPY/USDCAD` is three edges on four nodes, so
`3 = 3` - a tree, no cycle, and not an identity.

**The rule is structural and the weights are measured, so their agreement is the
evidence that the rule is the right one:**

| legs | identity? | max \|w\| | min \|w\| | `DF t` |
| --- | ---: | ---: | ---: | ---: |
| EURUSD/USDCHF/EURCHF | **yes** | 1.000 | 1.000 | **-77.83** |
| EURUSD/GBPUSD/EURGBP | **yes** | 1.000 | 1.000 | **-77.78** |
| EURUSD/USDJPY/USDCAD | no | 0.675 | 0.161 | -3.72 |
| GBPUSD/NZDUSD/AUDUSD | no | 0.595 | 0.424 | -0.04 |

Nothing told the regression which sets were identities, and it put every
identity weight at exactly ±1.000.

## Nothing survives at any width

| width | identities | best non-identity | its own null | survivors |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 0 | -3.70 | -3.77 | **0 of 190** |
| 3 | 5 | -3.72 | -4.43 | **0 of 495** |
| 4 | 21 | -3.63 | -4.24 | **0 of 479** |
| 5 | 39 | -3.82 | -4.33 | **0 of 461** |

**1,625 non-identity baskets across four widths and not one beats its own
null.** Every basket that does is a currency identity.

The identity count rising `0, 5, 21, 39` is why the classification was worth
building. Without it the four- and five-leg tables are 21 and 39 rows of `-77`,
and the screen reports as discoveries the relationships it has merely restated.

## Two predictions the measurement corrected

**The bar does not keep rising with width.** It reads `-3.77`, `-4.43`, `-4.24`,
`-4.33`: the degrees-of-freedom inflation **saturates after the third leg**. The
first extra weight costs half a point of `t` and the next two cost nothing.
Measuring a null per width was still the right call, but not for the reason
given for it - the reason was that the bar would climb, and it plateaus.

**An identity dilutes with width.** Three-leg identities have a median of
`-71.59`; five-leg identities have a best of `-77.84` and a median of `-2.38`.
The regression fits the last leg on the others, so when the dependent leg is not
part of the cycle the identity sits *among the regressors* and the residual is
not stationary. The cycle test flags the set correctly; whether the fit
**recovers** the identity depends on which leg happens to be dependent. The
exclusion is therefore conservative in the right direction - some excluded
baskets were never strong - rather than concealing anything.

## Cost scales with legs, which closes the escape route

An `N`-leg spread is opened and closed in every leg, so it clears a crossing of
each one. `range/cost` divides the residual's standard deviation by a round trip
across all the legs, each weighted by how much of it the fit holds, using the
legs' **own measured relative spreads** rather than a constant. A wide
combination therefore cannot look attractive merely by having a small residual.

The question never arose here - nothing reached the cost gate, because nothing
cleared its null - so the conclusion above does not rest on the cost basis. It
is stated correctly because the next harness does rest on it.

## What to use

The relationship question is closed on this universe, at widths two through
five, at two sampling rates, and for three relationship shapes:

* a **constant** pairwise spread - 0 of 190 against a null with matched tails;
* an **episodic** one that holds and breaks - 30.8% of windows reverting against
  the null's 30.8%, and a planted arm proving the detector would have found it;
* a **lead** - peak cross-correlation 0.0418 at 1h and 0.0413 at 3m, both inside
  what shared legs and non-synchronous closes produce;
* an **N-leg** combination - 0 of 1,625, with every survivor an identity.

**Keep the cycle rule.** It is four lines, it is exact, and it is the difference
between a null and 39 rows of spurious discovery at five legs. Keep the
identities too, as the standing positive control: any screen on an FX universe
that does not return them at `t` past `-50` with weights at ±1 has a bug
upstream of its conclusion.

## Related

* [Leads and baskets](statespace-leads-and-baskets.md) - three legs, the lead
  arm, and the triangles as a positive control
* [The relationship screen](statespace-relationship-screen.md) - the pairwise
  form, the live-ratio defect, and the block-shuffled null reused at every width
* [The episodic form](statespace-episodic-relationships.md) - the relationship
  that holds and then breaks
