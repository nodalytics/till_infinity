# The spread as a subject: measured, and it does not earn its place

`subjects.SPREAD` has existed since the package began, with
`member="reverting"` and both parameters marked placeholder, and nothing had
ever measured it. Meanwhile **every cost gate in the repository uses a
constant** - 1.5 spreads, times one number per instrument - and the SEC
order-flow paper's whole finding is that the number moves with the composition
of the flow.

Tick stores make this measurable for the first time: the broker's own bid and
ask, rather than a spread averaged into a bar.

The answer is negative and the consequence is **reassuring**, which is worth
stating plainly because this was queued as "directly actionable" on the
expectation that it would change something.

## 1. The spread is nearly constant

Hour-of-day profile, peak to trough, from the median quoted spread per
ten-second interval:

| | quoted spread | profile | peak hour |
| --- | --- | --- | --- |
| XAUUSD | 0.34 bp | **1.02x** | 12 |
| BTCUSD | 0.31 bp | **1.09x** | 15 |
| `Volatility_75_Index` | 3.51 bp | 1.00x | 11 |
| `Volatility_100_Index` | 4.31 bp | 1.00x | 23 |
| `Step_Index` | 0.13 bp | 1.00x | 0 |
| `Boom_500_Index` | 0.14 bp | 1.01x | 15 |

**A five percent variation over the day**, against the volatility profile's
**2.7x to 3.7x** in `statespace-seasonal.md`. The two quantities a cost gate
combines behave completely differently: one swings by a factor of three over
the session and the other does not move.

## 2. Nothing beats a trailing mean, and a constant is barely wrong

`reverting` on the log spread - logged because a spread cannot be negative and
moves multiplicatively - against trailing means and a constant, all
forecasting the next observation, all scored on the held-out second half. The
error is `mean |forecast/actual - 1|`, so 0.030 means the forecast missed by
three percent of the spread.

| | XAUUSD | BTCUSD | median, traded |
| --- | --- | --- | --- |
| the filter | 0.000 | 0.062 | 0.031 |
| **trailing 5** | 0.000 | **0.060** | **0.030** |
| trailing 10 | 0.000 | 0.061 | 0.030 |
| trailing 240 | 0.000 | 0.062 | 0.031 |
| a constant | 0.006 | 0.072 | 0.039 |

**On XAUUSD every forecaster scores 0.000** and a constant is wrong by 0.6%:
its quoted spread is flat enough that there is nothing to forecast. The
generated markets are the same. **Only BTCUSD has a forecastable spread at
all**, and there a five-observation trailing mean beats the filter, 0.060
against 0.062, with a constant at 0.072.

So the subject does not earn its place, and `nulls.py`'s description of the
trailing statistic as "the one nothing here has beaten" survives another
attempt.

### What the fitted parameters say, and why they stay placeholders

`theta` fits at **200 an hour on both traded pairs** - a half-life of twelve
seconds - which is the fit saying the spread is a **constant plus noise**
rather than a process with dynamics. And on the generated markets `sigma2` and
`theta` pin at **opposite grid edges**, which is what fitting a reverting
model to an exactly constant series does: infinite measurement noise and
infinite reversion explain a constant equally well.

So the subject's parameters remain placeholders, and the reason is now
measured rather than assumed. A first run with narrower grids had `theta`
pinned on every instrument, which is the grid-edge defect
`statespace-clock-levers.md` records three instances of; the grids here span
thirteen decades of `sigma2` and seven of `theta`, and the pinning is printed
per cell rather than hidden.

## 3. Roll's estimator cannot do what the provenance asked

The subject's own provenance named the independent check:

> Roll's implied spread from the serial covariance of price changes is the
> independent estimate, and the disagreement between the two is itself a
> measurement.

**It cannot be computed from this data, and the reason is structural.** Roll's
estimator infers the spread from **bid-ask bounce in transaction prices**: an
observed trade sits at the bid or the ask, so consecutive price changes are
negatively covariant and the size of that covariance implies the spread. A
**mid-quote has no bounce by construction** - it is the average of the two
sides - so applied to mids the estimator reads whatever serial covariance the
*price* has, which is price dynamics.

The numbers show it plainly. On BTCUSD the implied spread is **12.06 times**
the quoted one at sixty-second intervals and **1.39 times** at ten-second
intervals, on the same data. A spread estimate that changes by a factor of
nine when the sampling interval changes is not estimating a spread. And on
XAUUSD, `Volatility_75_Index`, `Step_Index` and `Boom_500_Index` the
covariance is **positive**, so the estimator is undefined and returns nothing
- which is the honest output, since a version clamping to zero would report a
tight spread exactly where it had broken.

Doing this properly needs **trade prices**, which this desk does not store.
That is now written in the subject rather than left as a suggestion.

## What this changes

* **Keep the constant cost gate.** It is wrong by 0.6% on XAUUSD and 7.2% on
  BTCUSD, so **no cost-gated conclusion in the repository changes** - which
  retroactively supports every result that used one, including the backtest's
  "0 of 28 cells clear cost" and the seconds note's cost floor.
* **If a time-varying cost is ever wanted, use a five-observation trailing
  mean**, not a filter. It is better and it is three lines.
* **The spread and volatility do not share a profile**, so a gate that scales
  cost with volatility would be wrong: volatility triples over the session and
  the spread does not move.
* **Trade prices would be worth storing** if the effective cost is ever to be
  separated from the quoted one. The quoted spread is what the desk is
  charged, so this is a second-order question - but it is the only route to
  the check the subject was designed around.

## Limits

The spans are about five hours for XAUUSD and ten for BTCUSD, over one or two
days in September 2026, so this is a statement about those venues in that
period rather than about spreads in general. EURUSD's tick store is corrupt.
And a quoted spread is not a paid spread: slippage and rejection are not in
this data at all.

The harness is `research/ideas/spread_subject.py`.
