# ZMA with machine learning on top: the model learns the z-score back, and nothing more

Measured 2026-09-29 on the lab with [`zmaml.py`](../harness/zmaml.py). Production
`structures.zma.Zma` was run bar by bar on closes at 15m and 1h over three universes:
- **positive control:** Ornstein-Uhlenbeck series at reversion speed theta 0.02, 0.05 and 0.15, three
  seeds each, 20,000 bars;
- **random walks:** Deriv Volatility 10/25/50/75/100 and Step;
- **real markets:** 15 FX pairs, XAU, XAG, BTC, ETH and SOL, about 700,000 bars.

Models are fit on each universe's first 60% by time and scored on the last 40%.

## The question

[`zma.md`](zma.md) measured ZMA's hand-built rules: it detects reversion where there is some and
finds none on this desk's outright prices. Would a model that learns how to combine its outputs
find what the rules miss? The candidates:
- **rule -z:** the continuous stretch;
- **rule agrees:** ZMA's firing call;
- **logistic:** on ZMA's outputs (z, slope, thresholds, flags);
- **GBM zma+ctx:** gradient boosting on those plus context (returns over 1/5/20 bars, the
  volatility ratio, the hour);
- **GBM ctx only:** the same context without ZMA.

## Where reversion exists, the model learns the z-score back

OU positive control, direction over the next 8 bars, test AUC:

| theta | rule -z | rule agrees | logistic on ZMA | GBM zma+ctx | GBM ctx only |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.02 | 0.550 | 0.502 | 0.551 | 0.555 | 0.545 |
| 0.05 | 0.620 | 0.507 | 0.620 | 0.614 | 0.603 |
| **0.15** | **0.741** | 0.520 | **0.741** | 0.736 | 0.707 |

- **ML adds nothing to the plain z-score even where the signal is real.** The logistic regression
  reproduces -z to the third decimal. Boosting with context does no better and, at the strongest
  reversion, slightly worse.
- **ZMA's firing rule (`agrees`) throws most of the signal away:** 0.520 where the continuous stretch
  it is built from scores 0.741. That agrees with `adapting.md`'s finding that the continuous call
  beats `agrees`.
- **On the random walks every model scores 0.498-0.504** at both horizons and both intervals, so the
  pipeline is clean.

## On real markets ZMA adds nothing to plain returns

Test AUC, real markets, pooled:

| | next bar, 15m | next 8 bars, 15m | next bar, 1h | next 8 bars, 1h |
| --- | ---: | ---: | ---: | ---: |
| rule -z | 0.517 | 0.525 | 0.514 | 0.515 |
| rule agrees | 0.502 | 0.501 | 0.501 | 0.499 |
| logistic on ZMA | 0.518 | 0.525 | 0.515 | 0.513 |
| GBM zma+ctx | 0.528 | 0.542 | 0.534 | 0.522 |
| **GBM ctx only** | 0.527 | 0.540 | 0.535 | 0.524 |

Traded (top and bottom training decile of each score, 8 bars, non-overlapping, net of spread,
in baseline moves):

| | 15m net (halves) | 1h net (halves) |
| --- | --- | --- |
| rule -z | -0.488 (-0.324 / -0.653) | -0.181 (-0.149 / -0.213) |
| rule agrees | -0.477 (-0.477 / -0.477) | -0.228 (-0.162 / -0.296) |
| logistic on ZMA | -0.414 | -0.175 |
| GBM zma+ctx | -0.184 (-0.267 / -0.085) | +0.011 (-0.019 / +0.037) |
| GBM ctx only | -0.226 (-0.312 / -0.130) | +0.030 (+0.002 / +0.056) |

- **Removing ZMA from the model costs nothing:** 0.540 against 0.542 at 15m, and 0.524 against
  0.522 at 1h. Whatever the boosted model finds, it finds in the returns, the volatility ratio and
  the hour, not in ZMA.
- **ZMA's own rules lose** after costs at both intervals.
- **The boosted models' AUC of 0.52-0.54 is not a directional edge yet.**
  - At 15m it loses after costs. At 1h it nets +0.01 to +0.03 of a move with one half near zero,
    and that is before a shifted null.
  - It is pooled across 20 instruments whose test period includes strongly trending gold. A
    feature that says which instrument it is looking at (the hour distribution, the volatility
    level) buys AUC from the instruments' different drifts.
  - The hour feature may also be picking up the published time-of-day pattern in FX (a currency
    tends to weaken during its own market's hours; Ranaldo 2009). That is a separate, specific
    hypothesis worth its own test, not a reason to trust this pooled number.

## What this settles

- **Adding ML to ZMA does not help.** On a series that truly reverts, a model learns the z-score
  back and adds nothing. On real markets, the same model does as well without ZMA as with it.
- **If ZMA is ever given a vote** (on the constructed spreads `zma.md` found, the one place it pays),
  it should be the continuous -z and not the `agrees` rule, which discards most of the signal.
- **Follow-up, separately:** the FX time-of-day drift, tested per currency against its own
  session hours with a shifted null.
