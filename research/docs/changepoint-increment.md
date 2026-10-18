# The change-point adds nothing; the variance it infers adds a great deal

`cusum.md` measured BOCPD's three readings adding **+0.035 to +0.043** to HAR
on 1h FX forward log Parkinson variance and left two questions open. Both are
now answered, and the first answer changes what that number meant.
Harness: `research/ideas/dispersion_changepoint.py`, run 2026-10-17.

`Changepoint` publishes three numbers, and they are not the same kind of claim:

* **`cp`** - `changepoint` (posterior mass on a run younger than `FRESH_HOURS`)
  and `log1p(run_length)`. *When did the regime turn.*
* **`sd`** - the predictive standard deviation, marginalised over run lengths,
  which this member **infers** rather than being told. *How wide is the next
  observation.* That is a volatility estimate of the quantity being forecast.

Each half is fitted on its own, crossed with two baselines: HAR's three
backward averages, and the 48 raw lags `dispersion_ml` calls `lin48`.

## Measured, 1h, median out-of-sample R2 across instruments

Increments are over the baseline to their left.

| cell | har | +cp | +sd | lin48 | +cp | +sd | shuffled |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fx_cross h=1 | +0.0468 | -0.0010 | +0.0492 | +0.0898 | -0.0114 | **+0.2253** | -0.0000 |
| fx_cross h=5 | +0.0838 | +0.0021 | +0.0547 | +0.1489 | -0.0171 | **+0.2072** | -0.0000 |
| fx_cross h=20 | +0.1214 | +0.0018 | +0.0580 | +0.2009 | -0.0320 | **+0.2277** | -0.0002 |
| fx_major h=1 | +0.0306 | +0.0004 | +0.0445 | +0.0840 | -0.0016 | **+0.2391** | +0.0000 |
| fx_major h=5 | +0.0516 | +0.0089 | +0.0456 | +0.1353 | -0.0010 | **+0.2057** | -0.0000 |
| fx_major h=20 | +0.0930 | +0.0106 | +0.0408 | +0.1617 | -0.0129 | **+0.0820** | -0.0000 |
| metal h=20 | +0.7921 | +0.0010 | -0.0007 | +0.8269 | +0.0002 | -0.0010 | -0.0005 |
| volatility h=20 | -0.0008 | -0.0027 | +0.0002 | -0.0051 | -0.0040 | +0.0002 | -0.0002 |

And 4h, where both baselines are much stronger to begin with:

| cell | har | +cp | +sd | lin48 | +cp | +sd |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fx_cross h=5 | +0.4203 | +0.0038 | +0.0045 | +0.4885 | +0.0020 | +0.0019 |
| fx_major h=20 | +0.4563 | +0.0051 | +0.0004 | +0.4978 | +0.0032 | +0.0010 |

## The two answers

**1. The change-point carries nothing.** `+cp` reads -0.0010 to +0.0106 on
HAR, and **negative in six of six** 1h FX cells on top of `lin48`. A run-length
posterior added to a model that already sees forty-eight bars makes it worse.
`+all` is also consistently *smaller* than `+sd` alone - +0.0356 against
+0.0492 on fx_cross h=1 - so the change-point columns dilute the one that
works, which is what adding noise to a ridge does.

**2. The increment was always the variance.** `+sd` reproduces the whole of
`cusum.md`'s +0.035 to +0.043 on HAR, and then **grows fourfold on top of
`lin48`**: +0.2057 to +0.2391 on five of six 1h FX cells. On fx_cross 1h h=20
it takes a 48-lag ridge from +0.2009 to **+0.4286**, which sits between the
shelf's `lin48` (+0.198) and its ESN (+0.572) - one nonlinear feature buying
about half of what a 48-state nonlinear model buys.

Both controls hold throughout: the Deriv volatility family, whose generator
fixes sigma, reads **+0.0002** where FX reads +0.23, and the shuffled target
reads zero everywhere.

## What this is, and what it is not

It is **not** evidence that regime changes are detectable or tradeable. The
feature that works is a predictive standard deviation of the same quantity
being forecast, produced by a filter that has seen the same bars. The finding
is that **BOCPD is a markedly better log-variance filter than HAR or a 48-lag
ridge**, and that its usefulness here has nothing to do with the run-length
posterior it was added for.

The mechanism is worth naming because it suggests the control that comes next.
In a Normal-Inverse-Gamma conjugate model the predictive scale tracks the
magnitude of recent residuals about the posterior mean; on log variance, level
and residual magnitude co-move. So `sd` may be a nonlinear summary of recent
log variance that a plain exponentially-weighted mean of squared residuals
would also supply. **Until that arm is run, the honest claim is "a
better-filtered volatility estimate helps a lot", not "BOCPD specifically
helps".** That is one feature and one run.

Where it does not help is where the baseline is already saturated: metals at
1h h=20 reads +0.7921 on HAR alone and `+sd` adds -0.0007.

## A lookahead in the reference lag design, and what it is worth

`dispersion_ml` builds `lin48` as `logvar[i - k]` for `k` up to 47, starting at
`i = max(LAGS) = 22`. The index goes negative and Python wraps it to the **end
of the series**, so the first `SIZE - start = 26` rows of a twelve-thousand-row
training design contain values from the test half.

It was kept as its own arm rather than assumed harmless, and it is worth
**+0.0001 to -0.0008** across every cell - nothing, as expected, and now a
number. The honest design in this harness starts where every lag exists, and
drops those rows from *all* arms rather than only from the one that cannot fill
them, so no arm is scored on rows another never saw.
