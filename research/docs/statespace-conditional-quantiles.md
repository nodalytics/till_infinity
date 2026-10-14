# A conditional band does not beat an unconditional one, and the shape stays open

`no-gaussian-band-is-calibrated` records the open problem precisely: nothing
beats the walk on CRPS, and what is unresolved is the **tail shape**. A
shape-free band - the empirical distribution of past residuals - takes PIT
flatness from 73.3 to **1.5** on traded instruments and improves CRPS only to
**0.991**. The band got honest and did not get sharper.

River fits a separate linear model per quantile level under the pinball loss,
online, which is a **conditional** quantile function - and conditional is
exactly what the incumbent is not. The empirical band uses the same shape
whatever the market is doing now; if the shape of the next return depends on the
recent path, a conditional band should beat it and an unconditional one cannot
express it however well calibrated it is.

The harness is `research/ideas/quantile_band.py`.

## Every arm shares the point forecast and the width

The point forecast is the last value - the walk - for every arm, so nothing here
is a point-forecast contest. And the **width** is shared too: each arm predicts
quantiles of `z = return / sigma` with the same exponential mean of squared
returns, and the band is `sigma` times those quantiles.

That separation is the question rather than a convenience. The width of the next
return is a volatility forecast, which this desk has studied exhaustively and
which every arm should share; the **shape** is what is open. A difference
between arms is then a difference in shape and nothing else.

## The answer

| arm | traded CRPS | PIT | generated CRPS | PIT |
| --- | ---: | ---: | ---: | ---: |
| gaussian | 1.0000 | 22.95 | 1.0000 | 1.26 |
| **conformal**, unconditional | **0.9899** | 0.37 | 1.0019 | 0.22 |
| river, conditional | 1.0017 | 0.14 | **1.0137** | 0.10 |
| river, monotone | 1.0009 | 0.14 | 1.0135 | 0.10 |

**The conditional band loses.** It is marginally worse than the Gaussian on
traded instruments - 1.0009 against 1.0000 - where the unconditional band is
0.9899. Nineteen online quantile regressions on the last eight standardised
returns extract nothing the empirical distribution of those returns did not
already have.

**And it fails the gate.** On the generated feeds the true shape *is* Gaussian -
kurtosis 3.00, Jarque-Bera p 0.40 to 0.95 on 86,411 bars - so the correct score
there is 1.0000 and the unconditional band's 1.0019 is the standard. The
conditional arm reads **1.0137**, which is a band fitting structure that is not
there and paying for it.

Enforcing monotonicity helps a little and changes nothing: 1.0017 to 1.0009. It
is kept because it has to be - the models are fitted independently, so nothing
stops the 60th percentile landing below the 40th, and `crps` integrates a left
Riemann sum over ascending levels. A crossing would not raise; it would quietly
score a thing that is not a distribution.

**The PIT column confirms nothing, as the conformal work already warned.** Both
shape-free arms sit below 1.0, and a band built from the empirical quantiles of
its own past residuals is uniform close to by construction. CRPS was always
going to be the evidence here.

## So the tail shape is still the open problem

This closes one route to it. The shape of the next standardised return is not
predictable from the last eight of them, by a linear quantile model, at 1h, on
this universe - and the honest reading is that the shape may simply not be
conditional on the recent path. `robust.py`'s generalised Gaussian remains the
untested lever that `no-gaussian-band-is-calibrated` names, and it is a
different kind of answer: a **parametric** shape with a fitted exponent rather
than a conditional one.

## The first run was a scale bug, and it is the same lesson twice

Fed raw log returns, which are of order `1e-4`, the quantile models never left
the origin: a linear model under pinball loss with a default step size cannot
reach a target that small, so every quantile came back near zero, the band had
no width, and CRPS read **26.8 times** the Gaussian with a PIT of 664. That is
not a conditional band losing, it is a regression that never started.

Standardising the target fixed it, and it is the same lesson as
`the-ladder-belongs-on-log-volatility`: the units decide whether a method can
work at all, and a method scored in the wrong ones produces a number rather than
an answer. It is also the second time in two studies that River's first reading
was an artefact of the harness rather than a property of River -
`statespace-river-against-members.md` was the first, where a missing `R` nearly
handed it a rout it had not earned.
