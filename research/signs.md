# When a feature's sign flips, look at the population

Two features in `structures/breaking.py` fitted against their own univariate
stories, and chasing that corrected three claims made earlier the same day.

## What looked wrong

* `approach_vol` fits **negative** in the multivariate model - faster arrivals
  break *less* - against the claim the model was built on, that "a fast arrival
  is likelier to break than a slow deep one".
* `interval_log`'s fitted sign flipped three times across learning rates and
  four times in consecutive live readings, despite a fortyfold univariate
  effect.

Three candidates: collinearity absorbing an effect, a sign convention misread,
or the univariate readings being confounded. Measured on 133,300 resolutions.

## Collinearity is not it

| | approach_vol | depth_vol | slowing | interval_log |
| --- | ---: | ---: | ---: | ---: |
| approach_vol | +1.000 | +0.004 | +0.044 | −0.035 |
| depth_vol | +0.004 | +1.000 | −0.069 | +0.118 |
| slowing | +0.044 | −0.069 | +1.000 | −0.006 |
| interval_log | −0.035 | +0.118 | −0.006 | +1.000 |

Every off-diagonal is below 0.12. The inputs are near-orthogonal, which is what
they should be, and nothing can be absorbing anything.

## `approach_vol` does not do what this model was built to believe

Break rate by quintile, low to high:

```
approach_vol    6.5%   7.6%   7.6%   6.6%   5.0%
```

Not monotone, and the **fastest fifth breaks least**. The multivariate negative
sign is not a fitting artefact - it is what the data says. The founding claim,
that arriving hard at a barely-entered level breaks it, does not hold across
the record.

**And it reverses with the timeframe**, which is the part worth keeping:

| interval | n | slow arrivals | fast arrivals | gap |
| --- | ---: | ---: | ---: | ---: |
| 1m | 103,725 | 7.5% | 6.3% | **−1.3** |
| 3m | 18,833 | 7.5% | 6.7% | −0.8 |
| 5m | 7,432 | 4.8% | 4.5% | −0.2 |
| 15m–30m | 1,226 | 1.1% | 2.1% | **+1.0** |
| 1h and slower | 2,084 | 0.3% | 0.9% | +0.5 |

Fast arrivals break *less* on fast timeframes and *more* on slow ones. **78% of
the sample is 1m**, so a pooled linear fit learns the 1m sign and reports it as
the effect. A linear model cannot represent that interaction at all.

## The interval effect is real but far smaller than reported

Within bands of `approach_vol`, slower timeframes break less every time - so
the sign is right and stable in the data:

| approach_vol band | n | fast timeframes | slow timeframes | gap |
| --- | ---: | ---: | ---: | ---: |
| 0.00–0.64 | 43,984 | 7.2% | 6.0% | −1.2 |
| 0.64–1.47 | 43,990 | 8.9% | 5.9% | **−2.9** |
| 1.47–40.76 | 45,326 | 6.2% | 4.7% | −1.5 |

**But that is one to three points, not fortyfold.** The 57.9%-at-1m against
1.4%-at-1h table was measured on touches lasting **five minutes or more**,
where the base break rate is 33.1%. Across all resolutions the base is **6.7%**
and the same effect is a couple of points.

`Breaks` learns from *every* resolution, so the population it trains on is the
second one. That is why `interval_log` contributes least of the six features by
`|weight| x sd` (0.036) despite being described here as the largest separator
on the book. **Both measurements are correct and they are about different
populations**, and the one that matters for this model is the weaker.

## Three corrections

1. **"The largest single separator on this book" was measured on a subset.**
   It holds for touches lasting five minutes or more and does not transfer to
   the population the break model trains on.
2. **`approach_vol`'s documented direction is wrong across the record**, right
   only above 15m, and the model has been learning the opposite sign for a
   reason rather than by accident.
3. **The unstable fitted signs were the learning rate, not the data.** The
   underlying effects are stably signed within every band; at 0.05 the fit
   simply never settled. See the rate sweep in `breaking.RATE`.

## What this suggests, unmeasured

The interaction is the interesting part: **arrival speed means opposite things
at different timeframes**, and a linear model is the wrong shape for it. The
cheap test is an interaction term - `approach_vol x interval_log` - scored the
same predict-then-update way. That has not been run.

The alternative reading is that the whole effect is a scale artefact: a "fast"
arrival on a 1m level is a small absolute move, and both features are partly
measuring the same thing about bar size. That has not been separated either.
