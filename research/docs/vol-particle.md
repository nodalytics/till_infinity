# A particle filter on volatility: better calibrated at 1h, and not always better

**Measured 2026-10-09** with [`vol_particle.py`](../ideas/vol_particle.py),
frozen before any real-data run. Asked because **I9** says the desk's
`Volatility` is an EWMA with no variance that parameterises every level update
as if it were exact, and a filter would give it the posterior the cascade
needs.

## The headline, which is the calibration and not the sharpness

**The shipped EWMA is over-confident at 1h by 18% to 29%.** The standardised
residual `z = r / sigma` should have a spread of 1 if the predictive band is
honest. It does not:

| series | EWMA `z` sd | its 90% band actually covers |
| --- | ---: | ---: |
| eurusd 1h | **1.199** | 88.1% |
| gold 1h | **1.207** | 89.1% |
| spx500 1h | **1.291** | 87.3% |
| eurusd 1d | 1.048 | 89.6% |

A spread above 1 means the realised move is wider than the band predicted - the
estimator is surer of itself than it has earned. At 1d it is nearly honest; at
1h it is not, on all three instruments.

**That is I9's defect, measured.** A level's zone is built from this number,
and a level cannot be better calibrated than the unit it is measured in.

## Does a particle filter fix it? On two of three, yes

Out-of-sample on the second half, every arm's parameters fitted on the first:

| data | arm | NLL | MAE | cover90 | z sd |
| --- | --- | ---: | ---: | ---: | ---: |
| eurusd 1h | ewma | -5.7954 | 0.000355 | 0.881 | 1.199 |
| eurusd 1h | kalman | -5.8084 | 0.000353 | 0.890 | 1.165 |
| eurusd 1h | **particle** | **-5.8334** | 0.000372 | **0.910** | **1.060** |
| gold 1h | **ewma** | **-4.1915** | 0.001739 | **0.891** | **1.207** |
| gold 1h | kalman | -4.1171 | 0.001637 | 0.860 | 1.380 |
| gold 1h | particle | -4.1404 | **0.001639** | 0.864 | 1.350 |
| spx500 1h | ewma | -4.2764 | 0.001584 | 0.873 | 1.291 |
| spx500 1h | kalman | -4.2366 | **0.001512** | 0.852 | 1.388 |
| spx500 1h | **particle** | **-4.3163** | 0.001666 | **0.897** | **1.178** |
| eurusd 1d | ewma | -3.9690 | **0.002291** | 0.896 | 1.048 |
| eurusd 1d | kalman | -3.9702 | 0.002334 | **0.908** | **1.010** |
| eurusd 1d | particle | **-3.9717** | 0.002308 | 0.906 | 1.025 |

**Mixed, and the mixture is the result.** The particle filter wins on eurusd 1h
and spx500 1h - better log-likelihood and much better calibration - ties at 1d
where there was little to fix, and **loses on gold**, where the EWMA is both
sharper and better calibrated than either filter.

Note also that MAE and NLL disagree repeatedly. The arms with the best MAE are
often the worst calibrated: `kalman` has the lowest MAE on spx500 and the
widest `z` spread of the three. Point accuracy and honest uncertainty are not
the same property, and only the second is what I9 asked for.

## Unlike levels, the non-Gaussianity is real

`level-filters.md` settled the particle question for levels with a middle arm:
the same filter with a heavier-tailed likelihood and no particles came out
identical to four decimals, so there was no tail to exploit. The same arm here
says the opposite.

`particle` beats `kalman` on all four series - by 0.025 nats on eurusd 1h,
0.080 on spx500, 0.023 on gold. The linearised Gaussian approximation leaves
something on the table that the particles pick up. **That is a different answer
from the levels study, and it is why the arm is worth including every time
rather than assumed.**

## The nulls, which passed, and the one they missed

| | ewma | kalman | particle |
| --- | ---: | ---: | ---: |
| constant volatility, NLL | -3.1919 | -3.1909 | -3.1913 |
| true SV process, NLL | -3.0467 | -3.0537 | **-3.0678** |

All three tie where volatility is constant, so the particles cost nothing when
there is nothing to find; the particle filter wins where the generating process
really is stochastic volatility, so the test is not too blunt to read a null
from. Both are necessary and both passed.

**And both missed a bug that only real data exposed.** The first run reported a
negative log-likelihood of **1.15e17** for the Kalman arm on eurusd with a `z`
spread of 4.8e11 - a blown-up filter, not a bad model. `log(r^2)` goes to minus
infinity as a return approaches zero, and a quiet hour on a pair quoted to five
decimals rounds to exactly no move; flooring `r^2` at 1e-300 turned those into
observations near -690, a hundred standard deviations from the state, which the
filter chased.

The lesson is about the nulls rather than the arithmetic. **Both synthetic
nulls draw returns from a Gaussian, which never produces a rounded-to-zero
bar**, so neither could have caught this. A null built to test the *model* did
not test the *data*, and the failure surfaced only against a real series - one
step before it would have been written up as a result.

## What this changes

* **I9's premise is confirmed and quantified.** The EWMA is 18-29% over-confident
  at 1h. A cascade that passes volatility down as exact is passing down a
  number that is wrong about its own error by about a fifth.
* **Replacing the estimator is not the obvious next step.** It loses on gold,
  and the desk trades metals. A filter that is better on two instruments and
  worse on a third is not a drop-in.
* **The cheap version may be enough for I9.** What the cascade needs is *a*
  variance, not the best possible one. The EWMA's own `z` spread is measurable
  per series and could inflate the level's observation noise directly, with no
  new filter at all. That is a smaller change than this study was built to
  evaluate, and this study is the evidence for it.
