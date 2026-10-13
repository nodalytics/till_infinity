# Does the venue deliver the process it advertises, and is it stable

This desk trades Deriv's synthetic indices with real money, and the venue
**generates** the price process rather than quoting someone else's. That makes
one question verification rather than suspicion: does the delivered process
match the published specification, and does it stay matched?

It is answerable because the specification is unusually explicit. A
`Volatility_N_Index` is advertised as geometric Brownian motion at `N` percent
annualised volatility, which pins four measurable things: the level, the shape,
the independence, and - the sharpest of them - the **absence of volatility
clustering**, which constant-volatility GBM cannot have and every real market
does.

The harness is `research/ideas/venue_spec_check.py`.

## The level is delivered to within half a percent

| instrument | advertised | realised | ratio | window sd | noise permits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Volatility_100_1s_Index | 1.000 | 1.001 | **1.001** | 0.0284 | 0.0264 |
| Volatility_100_Index | 1.000 | 1.003 | **1.003** | 0.0297 | 0.0264 |
| Volatility_10_1s_Index | 0.100 | 0.099 | **0.995** | 0.0293 | 0.0264 |
| Volatility_10_Index | 0.100 | 0.100 | **0.999** | 0.0268 | 0.0264 |
| Volatility_150_1s_Index | 1.500 | 1.497 | **0.998** | 0.0244 | 0.0264 |
| Volatility_15_1s_Index | 0.150 | 0.151 | **1.004** | 0.0257 | 0.0264 |

Correct across a **fifteen-fold range of volatility levels**, which is a
stronger statement than any single row: an estimator or an annualisation that
was wrong would not be wrong by the same factor at 10% and at 150%.

It also fixes the time convention as a by-product. Ratios land on 1.000 only
when annualising on continuous time, `365 x 24`; a 252-day convention would read
1.20 throughout.

## And it does not drift

`window sd` is the scatter of log realised volatility across 27 monthly windows;
`noise permits` is `1/sqrt(2n)`, what sampling alone gives. The ratios run
**0.92 to 1.13**. A specification is a constant, so a process being adjusted
would scatter more than sampling allows, and these do not.

**This is the evidence against venue-side modulation**, not the fact that
generated volatilities are mutually uncorrelated - a constant-volatility process
has almost no volatility variation to correlate, so that reading is close to
automatic and establishes only that the estimator is honest.

## The clustering test separates a specification from a market

| class | median kurtosis | median log-vol autocorrelation |
| --- | ---: | ---: |
| generated | **3.116** | **+0.0182** |
| traded | **17.366** | **+0.4022** |

Gaussian kurtosis is 3.0 and constant-volatility GBM has **no** clustering. The
generated side reads 3.12 and +0.018 with return autocorrelations between
`-0.022` and `+0.006`; the traded side, on the identical estimator, reads 17.4
and +0.40.

**That is the specification confirmed on its sharpest term**, and it has a
consequence worth stating plainly: the desk's own edge is volatility
forecasting, and **there is no volatility variation to forecast on this family.**
A constant is not a forecasting problem.

## Nothing happens to all of them at once

The last arm asks whether instruments deviate from their own specification in
the *same* windows. Drift is independent across independent generators; a
venue-level event - an outage, a feed fault, an engine change - is not.

Across 27 windows the share of instruments past two standard errors runs
**0.059 to 0.265** with a median of 0.179, and the median `z` per window stays
between `-0.44` and `+0.67`. **No window stands out.**

The baseline is higher than the 0.046 a two-sigma threshold implies, uniformly,
which matches the window-to-noise ratio of 1.08 above: the noise formula is
slightly optimistic. A uniform excess is a miscalibrated denominator. An event
is one window.

## What to use

**The synthetics are delivered to specification**, at the advertised level,
without drift, with the advertised shape, and with no coincident deviation. For
a desk trading a venue-generated product that is worth re-running rather than
assuming, and it is cheap.

**Re-run it before trusting the synthetics as controls**, which is the other use.
Their value as a control rests on them being the process they claim to be, and
this is the check that says so.

## Related

* [What is left to exploit in the synthetics](statespace-synthetic-exploits.md) -
  the families whose published spec contains a non-martingale feature
* [Volatility relationships](statespace-volatility-relationships.md) - where the
  synthetics are the control, and what that control does and does not prove
