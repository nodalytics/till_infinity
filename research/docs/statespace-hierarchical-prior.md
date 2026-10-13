# A hierarchical prior over member parameters, and why it has nothing to borrow

Prod shrinks per-level statistics toward a pooled mean, and that idea kept
recurring this session: a live hedge ratio that absorbed its own residual, a
`probability_up` that was twice as confident as it should be, a `PRIOR_WEIGHT`
of `4.0` that was never estimated. All four are the same defect - an estimate
trusted more than its own precision warrants - so the obvious import was a
hierarchical prior over the state-space members' own parameters, fitting each
instrument while borrowing strength from the rest.

It does not work here, and the reason is specific enough to be a rule.

The harness is `research/ideas/hierarchical_prior.py`.

## The estimator, and the two arms that check it before it is trusted

Each instrument's `jerk` is fitted on the first half of its history by grid
search over seven decades. The curvature of the log-likelihood at the winner
gives the standard error directly:

```
s^2 = -h^2 / (ll[i-1] - 2*ll[i] + ll[i+1])        h = log(10)
```

`tau^2` - the genuine between-instrument spread, with sampling noise subtracted
- comes from DerSimonian-Laird, and each instrument is pulled toward the pooled
estimate by

```
B_i = tau^2 / (tau^2 + s_i^2)
```

`B = 1` keeps the own fit, `B = 0` pools completely. A grid edge sets
`variance = inf` and so `B = 0`, which is the right behaviour: an unreadable
curvature means an untrustworthy fit, and it should defer.

Two arms establish that the machinery answers correctly before the traded
universe is asked anything:

**Arm 1, heterogeneity known by construction.** `Volatility_10` through
`Volatility_100` are the same process at five volatilities, so the fits must
differ and pooling must hurt. Observed spread of log estimates **2.969**,
`tau^2` **3.718**, every `B` **1.00**, and the fitted values come out ordered
`1e-07` to `1e-05` with the volatility. Median held-out gain from shrinking
**+0.0**; from pooling completely **-251.5**.

**Arm 2, agreement known by construction.** `Volatility_75_Index` and
`Volatility_75_1s_Index` are plausibly the same path at two sampling rates, as
are the two 25s. The estimator **reproduces the pairing it was never told
about**: both 75s fit `1e-05`, both 25s fit `1e-06`. Pooling across all four
still costs **-320.1**, because it pools 75 with 25.

So the estimator separates processes that differ, agrees on processes that
match, and refuses to pool across a real gap. It works.

## On the traded universe every weight is 1.00

14 instruments, all with readable curvature, no grid edges:

| | own fit | sd(log) | B | shrink gain | pool gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| FX majors and crosses | 1e-07 | 0.04-0.05 | 1.00 | | |
| EURGBP | 1e-08 | 0.05 | 1.00 | | |
| XAUUSD, XAGUSD, BTCUSD | 1e-06 | 0.05 | 1.00 | | |
| ETHUSD | 1e-05 | 0.05 | 1.00 | | |
| **median over all 14** | | | **1.00** | **-0.2** | **-373.7** |

Observed spread **2.597**, `tau^2` **2.859**, pooled estimate `2.05e-07`.
**Shrinking helps 3 of 14; pooling completely helps 0 of 14.** The prior is a
null: there is nothing to borrow.

## Why, and this is the transferable part

`sd(log)` is **0.04 to 0.05 on all 23 instruments in all three arms**,
regardless of the fitted value. That constancy is the explanation rather than a
bug. For a scale parameter,

```
sd(log q) ~= sqrt(2/n)
```

which depends on the **sample size and not on the parameter**. Every instrument
here carries a comparable number of bars, so every one is estimated to
comparable precision - and `0.05` against a between-instrument spread of `2.6`
in log units, a factor of 13, gives `tau^2/s^2` of about **1100** and so
`B = 0.999` everywhere.

**My stated motivation was wrong, and the curvature is what showed it.** The
argument for importing this was that per-instrument fits are noisy, because
grid edges kept appearing all session. The curvature says the opposite: the
fits are sharp, the parameters genuinely differ by an order of magnitude, and
the earlier edges were in other parameters and at smaller effective sample
sizes, not in `jerk` at 1h.

## This rescues prod's shrinkage rather than refuting it

The import failed for a reason that leaves the original intact. Prod pools
**levels**, each touched a handful of times; this pooled **instruments**, each
fitted on tens of thousands of bars. The per-group sample sizes are three
orders of magnitude apart, and `sqrt(2/n)` is the whole difference.

**A hierarchical prior pays when the per-group sample is small. Check the
per-group `n` before importing one.** A member parameter estimated from a full
price history is not a small sample, and no amount of borrowing improves it.

That also sharpens where the shrinkage argument does still apply among the four
instances. The live hedge ratio and `probability_up` are both estimated from
plenty of data, so neither is a small-sample problem either - the hedge ratio's
defect is that it absorbs its own residual, and `probability_up`'s is
calibration. Only prod's levels, and prod's unestimated `PRIOR_WEIGHT`, are
genuinely about borrowing strength. **The four instances were not one defect;
they were two defects that look alike.**

## What to use

Nothing, for member parameters. Fit `jerk` per instrument and keep it.

The estimator itself is worth keeping for the case it was built for: it returns
`tau^2`, the per-instrument `B`, and whether the fit sat on a grid edge, so it
answers "should these be pooled" with a number. Run it before pooling anything
whose groups are small - levels, sessions, per-regime fits - and believe `B`.

## Related

* [The forecast distribution](statespace-tail-shape.md) - where the remaining
  open problem is the tail shape rather than the parameters
* [The relationship screen](statespace-relationship-screen.md) - the live hedge
  ratio, which is the same family of defect and a different member of it
* [Episode replay](statespace-episode-replay.md) - `probability_up`'s
  calibration, measured on 291,699 prod episodes
