# Does a quantile-calibrated stop deliver the coverage it claims?

**Pre-registered 2026-11-03, before any panel ran.** Everything above the
results section was written first and is not edited afterwards; corrections go
in [Deviations](#deviations).

`till_infinity/risk/quantiles.py` (`8de2dd5b`) ships `student_stop`, an online
`Quantile` of the adverse excursion, and `affordable`. Its own tests settle two
things in a vacuum: the one-sided baseline is 1.51 units and not 1.08, and on
excursions drawn from `|t(4)|` the fixed t and the online estimator tie to a
thousandth, so **the only case for the adaptive estimator is a side whose
excursions run on a different scale**. Nothing has measured whether real
excursions are that case, and nothing on this desk has measured whether its
live stop delivers any stated probability at all.

This is a **calibration** study, not an edge study, and that is unusual here.
Almost every question in this folder asks whether something predicts and the
answer is no. This one asks whether a *stated probability is delivered*, which
can succeed, and the honest expectation written down in advance is that the
incumbent is miscalibrated and the t is close to right - so the interesting
readings are *by how much*, and whether the per-side asymmetry is large enough
to need the adaptive estimator at all.

Harness: [`research/ideas/stop_coverage.py`](../ideas/stop_coverage.py), panel
driver [`stop_coverage_run.py`](../ideas/stop_coverage_run.py), report
[`stop_coverage_report.py`](../ideas/stop_coverage_report.py), tests
[`test_stop_coverage.py`](../ideas/test_stop_coverage.py).

## The claim, in one line

A stop placed at the `tau` quantile of the adverse excursion should be reached
`1 - tau` of the time - per side, per instrument, scored one step ahead.

## What is frozen before the run

### The volatility unit

**A causal EWMA of squared log close-to-close returns at `lambda` 0.94, as a
sigma.** Not a choice: production computes `unit = vol_bps / 1e4 * entry` and
`risk = stop_vol * unit`, where `vol_bps` is a per-bar return sigma in basis
points, so the incumbent stop is `3.0` of *this* quantity. `student_stop` is
also in unit-variance sigma. Measuring excursions in anything else - an EWMA
bar *range*, say, which is 1.015x this on eurusd and 0.755x on gold - puts the
stop and the excursion in two units and both readings look fine. 0.94 is
`node/surrogates.EWMA_LAMBDA`, so the surrogate and the unit agree.

**Secondary unit, reported beside every primary reading:** the Parkinson range
estimator of the same sigma, `log(high/low) / (2 sqrt(ln 2))`, EWMA'd the same
way. `drive-q-from-the-range` is why it is here - the range-vs-close estimator
ratio carries within strata on FX and on 371 of 392 equities - and the measured
0.755 gap on gold is why it is a check rather than a footnote. **A coverage
reading that depends on which estimator is used is not a coverage reading.**

### The adverse excursion

In logs, so a stop is a fraction of price and gold at 4,000 and eurusd at 1.08
are the same quantity:

* long (`side` +1), adverse is down: `(log c[t] - min log low[t+1..t+H]) / sigma[t]`
* short (`side` -1), adverse is up: `(max log high[t+1..t+H] - log c[t]) / sigma[t]`

Clamped at zero, because price never moving against a trade is a real outcome
and `Quantile.observe` refuses a negative one by design. **The clamp count is
reported per cell**: a gap through the entry makes the raw value negative, and
a cell where that is common is a cell where the entry is not where the study
thinks it is.

### The horizon, and why this number

An adverse excursion does not exist without a holding period, and there is
nothing to inherit: [`level-bounce.md`](level-bounce.md) measured departures
with **no characteristic length** - S(8) above the hardest null in 0 of 167
cells - so any horizon is a choice and has to be declared and swept.

**Primary `H` = 20 bars at both intervals.** In bars, not in calendar time,
which is this repo's own convention and `indicators/levels.FORGET_BARS`'
argument: in bars a horizon is interval-independent. 20 is
`level_shield.SETTINGS["1d"]["horizon"]`, so it is not a new number, and it is
the only value in the sweep that leaves **250 non-overlapping anchors per side
per feed on both intervals** - the live rule's own 96-bar hold leaves 53 at
15m, where 76 days is all the store has. The power reason is stated in advance
rather than discovered afterwards.

**Secondary sweep `H` in {1, 5, 20, 48, 96}.** 96 is the live hold exactly (96
M15 bars = 24 hours) and 1 is the reproduction arm below. No reading in the
verdict may depend on the choice of 20; where it does, that is the finding.

**`H` = 1 is the reproduction arm and must pass or the harness is wrong.**
`no-gaussian-band-is-calibrated` measured a Student-t at dof 3-5 fixing the
one-bar band on 64 of 64 out-of-sample readings, and there is an exact reason
the same number should also be the one-bar *excursion* quantile: by the
reflection principle a driftless walk has `P(min <= -a) = 2 Phi(-a/sigma)`,
which is identically `P(|X| >= a)`, so the `tau` quantile of the one-sided
running minimum over one unit of time **equals** the `tau` quantile of the
two-sided endpoint - exactly what `student_stop` returns. If `t-fixed` is badly
calibrated at `H` = 1 the defect is in this harness, not in the module.

### Anchors, and the overlap rule

**Non-overlapping, step = `H`, after a 200-bar warm-up** for the EWMA. Dense
(step 1) readings are reported beside the *fixed* arms, with a **block
bootstrap** for the interval rather than a binomial one: overlapping anchors
share most of a window - 95 of 96 bars at `H` = 96 - so a binomial interval
over them describes a sample this study does not have.
`overlapping-windows-inflate-permutation-nulls` is the recorded failure, where
a level finding at p 0.015 was anchor overlap and the tell was the no-level
control passing too.

**The block is the overlap length in anchors, floored at one calendar day's
worth, and that is a correction to this folder's habit.** A day-block
bootstrap is right at 15m, where a day holds 96 bars - but on **daily** bars a
calendar day holds exactly one anchor, so grouping by day leaves every block a
single row and the bootstrap becomes an ordinary one over rows that are not
independent. Measured on a 48-bar dense stream: a day block reads **1.35x**
the binomial sd where the overlap block reads several times it.
`level_shield.race` groups by calendar day for the same purpose and inherits
the same limitation on its 1d panel.

**A non-overlapping stream carries at most 500 anchors**, thinned by an even
stride so it still spans the whole history rather than its oldest 500 bars.
Two reasons, both declared: the sweep would otherwise compare a 4,801-trade
stream at `H` = 1 with a 51-trade one at `H` = 96, which confounds the horizon
with how long the online estimator had to converge - and convergence is the
thing under test - and `Quantile.observe` costs **1.5 ms a call** for reasons
reported below. **The primary horizon's stream is 240-256 anchors and is not
capped**, so nothing in the verdict is subsampled.

**The online arm is never run on the dense stream.** At step 1 the excursion at
`t+1` shares `H - 1` of its `H` bars with the excursion at `t`, so letting the
estimator see `t`'s excursion before it sets `t+1`'s stop is a leak wearing
causality's clothes. `overlapping-outcome-windows-leak` is the recorded case: a
short skip rule with a long forward window gave direction AUC 0.79 that
collapsed to 0.51. The headline table is therefore the non-overlapping one for
all arms.

### Causality

For each anchor, in this order: read `Quantile.stop(side)`, compare the
excursion to the distance that was read, then call `Quantile.observe(side,
excursion)`. `observe` already scores before it steps, and the harness must not
feed it an excursion it has already used to set a stop. A test asserts the
order through the production object rather than restating it.

## The four arms, plus two declared additions

| arm | stop, in sigma units | horizon-aware | asked for |
|---|---|---|---|
| `vol-3` | **3.0** - the incumbent. `Intent.stop_vol` runs at a measured median of 3.0 | no | yes |
| `vol-3-N20` | `max(3.0, 20 * spread_vol[t])` - the incumbent with `smc_bos_c_L50|M15|N20`'s floor of 20 spreads | no | yes |
| `t-fixed` | `student_stop(0.90, 4.0)` = **1.5105** | no | yes |
| `quantile` | `Quantile(tau=0.90).stop(side)`, online, per side | learns it | yes |
| `t-sqrt-h` | `student_stop(0.90, 4.0) * sqrt(H)` | yes | **added** |
| `quantile-seated` | the same `Quantile`, started at `t-sqrt-h` | learns it | **added** |

**`t-sqrt-h` is an addition to the four arms the study was asked for, and the
reason is the reflection principle again:** `student_stop` carries no horizon,
so at `H` = 20 it is a one-bar quantity asked a twenty-bar question, and
beating it there is arithmetic rather than a finding. Under diffusive scaling
`P(min_H <= -a) = 2 Phi(-a / (sigma sqrt(H)))`, so `sqrt(H)` is the correction
the baseline is entitled to. **The adaptive estimator earns its state only by
beating `t-sqrt-h`.** The four pre-registered arms are reported unchanged
beside it.

**`quantile-seated` is a sixth arm and a fifth declared addition.** `GAIN` is
an **absolute** step in volatility units, so reaching a quantile of size `q`
from 1.51 takes about `(q - 1.51) / (gain * tau)` exceedances: at `H` = 20,
where the empirical quantile is 7-9 units, that is around 360 and the
non-overlapping daily stream has 250. The estimator can therefore read
miscalibrated for a reason that is about the step rule and not about any
market. `quantile-seated` is the same object started at `t-sqrt-h` instead of
at `student_stop` - `Quantile.stop`'s own docstring starts it at the baseline
"because that is a measured, well-calibrated starting point", and at `H` > 1
the measured well-calibrated starting point is `sqrt(H)` times larger.
`rate_late`, the hit rate over the second half of each stream, separates "not
converged" from "miscalibrated", and `GAIN` is swept over {0.02, 0.05, 0.10,
0.20} on the primary horizon as a declared secondary - reported as a grid on
the mean, never as the best cell with its z.

`vol-3-N20` needs a spread and is therefore reported only on the costed feeds.
On the 1d panel 20 spreads is 0.078-0.535 units against a 3.0-unit stop, so the
floor cannot bind; at 15m it is 7.78 units on eurusd and 5.89 on gbpusd, so it
binds hard and the floored incumbent is a different stop from the incumbent.
Those four numbers are measured, from the store, before the run.

## Pass rules, written before the results

1. **Calibrated** on a cell iff the realised rate's 95% interval contains
   `1 - tau`, where the interval is the **wider** of the binomial
   `1.96 sqrt(0.10 * 0.90 / n)` - +-0.037 at n = 250 - and 1.96 block
   bootstrap sds. `Coverage.enough` (n >= 30) is the floor below which a rate
   is reported and not acted on.
2. **Ranking is by `|excess|`**, `Coverage.excess` signed so the direction of
   the correction is visible - positive means the stop is too tight.
3. "The online quantile is better calibrated than the incumbent" needs
   `|excess|` smaller on **at least two thirds of cells** and on **both sides
   of at least two thirds of feeds**. Per side and per instrument, never only
   pooled.
4. **The adaptive estimator earns its state** only if it also beats
   `t-sqrt-h` by that rule.
5. **Per-side asymmetry**, which is the question that decides whether anything
   adaptive is needed: the real per-side stop ratio `stop(-1) / stop(+1)` must
   fall outside **all 16 draws** of the hardest null arm. Counted against the
   1/17 chance rate per cell and put through Benjamini-Hochberg over every
   cell. `fear-greed.md` is why 16 and not 4: a hardest-of-N test at four
   draws is anti-conservative and turned +0.093 into -0.037 on the same data.
6. **Cost is a gate on the conclusion, not a footnote.** A conclusion holds for
   an arm only where `affordable(stop_vol, spread_vol)` is empty on the costed
   feeds. `stop-anchor.md` found a level-anchored stop at 0.169-0.198 of risk
   against the 0.16 limit, outside the envelope on 3 of 6 feeds before any edge
   was tested.
7. **Every plant has a zero control that must read nothing.** If the zero cell
   reads an effect the test is rejected and the question is left *untested*
   rather than null - `level-bounce.md`'s pure-order plant failed exactly this
   way (-0.180 at z -4.76 with nothing planted) and the honest outcome was to
   discard the arm.

## The nulls, and what each must produce

Sixteen draws of each of `garch-bars`, `walk-geometry` and `bar-shuffle`, taken
from [`level_shield.py`](../ideas/level_shield.py) unchanged - `walk-geometry`
is `node/surrogates.walk_with_bar_geometry`, so this harness and the module
cannot disagree about what the arm is. Seeds are `blake2b` over the cell
identity, never `hash()`: `fear-greed.md` records a panel whose surrogate arms
read -0.266 where a local run read -0.172 because `hash()` is salted by
`PYTHONHASHSEED`, while every real value matched to the digit.

**Every arm's first draw runs the whole horizon sweep and both unit
estimators; the deeper draws run the primary horizon on the primary unit.**
The 16 draws exist to bound the statistic the verdict is scored against, which
is at the primary horizon; the sweep's job is to show that the *real* reading
does not depend on `H`. Declared rather than discovered, because it is a
budget decision and a reader has to be able to see it was made in advance.

Predictions, written now:

* **`vol-3` and `t-fixed` should be about as miscalibrated on a walk as on the
  market.** Their error is a horizon-and-scale mistake, not a market fact, and
  a null that reproduces it says so.
* **`quantile` must deliver about 0.10 on every arm, walks included.** It is an
  estimator, not a signal. An estimator that cannot calibrate a random walk is
  broken, and this is the arm where a null *passing* is the good outcome - the
  opposite of every other study here.
* **A per-side asymmetry at long `H` is most likely drift.** `walk-geometry`
  resamples close-to-close steps i.i.d. and so keeps the mean step;
  `garch-bars` draws zero-mean Gaussian innovations and so does not. If gold's
  pre-run 1.19x at `H` = 20 and 1.64x at `H` = 96 is drift, it survives in
  `walk-geometry` and vanishes in `garch-bars`, and the adaptive estimator is
  tracking a drift rather than a volatility asymmetry.

## Power, before any null is reported

Three plants, each with its zero control:

1. **`drift`** - add `mu * sigma` per bar, `mu` in {0, 0.02, 0.05, 0.10, 0.20}.
   The direct mechanism for a per-side excursion gap. `mu` = 0 is the control.
2. **`asym`** - multiply the negative log returns by `f`, `f` in {1.0, 1.1,
   1.2, 1.3, 1.5}. This is the case `test_the_empirical_wins_where_the_scale_
   differs` builds by hand at 1.3x, planted into bars instead of into draws.
   `f` = 1.0 is the control.
3. **`scale`** - multiply **every** log return by `f`. **This one must read
   exactly nothing at every `f`**, because the excursion is divided by a sigma
   estimated from the same returns, so the measurement is scale-equivariant by
   construction. It is the control that must come back empty rather than
   smaller, which is the kind that catches what the other kind does not: a
   lookahead in the unit, or a price-level dependence of the sort
   `a-synthetic-at-price-one-hides-scale-bugs` records.

Plants go on the **returns**, never on the excursions. Planting an excursion
directly bypasses the unit and measures arithmetic.

## The data

**Coverage is a hit rate in volatility units and needs no spread**, so power
comes from 1d and cost from 15m.

* **1d, nine feeds** - eight FX plus gold, venue by bar count with ties
  alphabetically, fixed before any result. 4,477-5,009 bars over 15.5-19.9
  years.
* **15m, the six costed feeds** - `eurusd`, `gbpusd`, `gold`, `btc` on
  **DERIV**, `us100` on **FOREXCOM**, `spx500` on **PEPPERSTONE**. The bars come
  from the same venue as the quotes, because a spread measured on one venue is
  not a spread on another: the same instrument runs 0.17 to 3.30 bps across
  venues, a nineteenfold range. **`us100` and `spx500` are not the venue the
  live desk trades** and every number on them is labelled so.
* **No spread is invented.** The other eight feeds carry geometry only, which
  is sound precisely because nothing is priced on them.
* **Synthetic crosses are excluded outright** - a synthesised cross's range
  reads about 1.7x too wide (`fear-greed.md`: median body/range 0.463 to 0.268,
  `levels.chains` 83 legs to 4), which is a measurement of the construction,
  not of a market. None is in the store at either interval, so the exclusion
  costs nothing and is stated so a later run cannot quietly add one.

## Secondary: mean R, and the confound that decides how to read it

**Coverage is the primary reading and a mean R must not displace it.** A better
calibrated stop can lose money and a worse one can make it.

Costed feeds at 15m only. Per anchor: stop at the arm's median distance,
target at `TARGET_R` = 2.0 times it, time exit at `H` scored at the close, one
spread charged as the round trip, and a tie inside one bar given to the
**stop** - bar-level first passage cannot say which barrier a bar touched
first, so the conservative rule is the only honest one, and it is a bias
against the target that is biggest where the stop is tight, which is exactly
the arm comparison here.

**[`widestop.md`](widestop.md) already measured the confound and it is large:**
mean R at `m` times the stop is the 1x mean divided by `m` in every row, and
price P&L in units of the base risk does not move (+0.180 at 1x, +0.177 at 3x).
The arms here span 1.51 to about 8 units, a factor of five, so **mean R across
arms is dominated by 1/width and is not a comparison**. Both are therefore
reported: mean R in each arm's own risk, and mean P&L in units of **one sigma**,
which is common to all arms and is the number that can be compared. Day-block
bootstrap for both, because trades cluster in days.

## Two defects in `risk/quantiles.py`, one of them a blocker

### It makes the desk depend on `scipy`, which this project does not declare

**`8de2dd5b` turns the suite red and it is red before any of this study's
work.** `uv run pytest -q` on `anchored-states` reads **1 failed, 2,676
passed, 7 skipped**, and the one failure is
`tests/test_service_boundaries.py::test_every_third_party_import_is_declared`:

```
imported but not declared: {'scipy': ['quantiles.py']}
```

`risk/quantiles.py:113` does `from scipy import stats` and `scipy` appears
**nowhere** in `pyproject.toml`. It runs here only because `river` pulls it in
transitively, which is precisely the failure that test was written for - its
docstring records `rich` working because the desk happened to pull it in, and
breaking when something unrelated was removed. Four modules in this package
say so in as many words: `statespace/__init__.py` ("Neither library is a
dependency. `scipy` is present here only transitively"),
`statespace/diagnostics.py`, `statespace/distance.py` and `node/metrics.py`
("Hand-rolled rather than taking scipy, which would be a dependency for one").

**And the function already exists, dependency-free, in this repo.**
`statespace/tails.py` holds the t distribution in full - the regularised
incomplete beta by continued fraction, the CDF from it, the quantile by
bisection - written that way for this exact reason, and derived from
`one-bar-band.md`, which is the study `student_stop`'s own docstring cites.
`tails.reach(coverage, dof)` is `quantile(0.5 * (1 + coverage), dof) *
sqrt((dof - 2) / dof)`, and `student_stop(tau, dof)` is
`t.ppf((1 + tau) / 2, dof) / sqrt(dof / (dof - 2))`. **They are the same
function**, verified here to 5e-13 over `tau` in {0.80, 0.90, 0.95, 0.99}
crossed with `dof` in {3, 4, 5} - 1.5074433191 both ways at the shipped
setting.

So the recommended change is to call `tails.reach`, and it is **one change
with the next defect, not two**, because `tails.reach` is **1,696 us** a call
against scipy's 629 us: the swap on its own makes `Quantile.observe` nearly
three times worse. Caching is what makes either implementation free.

One behaviour difference to carry across deliberately: `tails.reach` clamps
`dof` to `LEAST_DOF` 3.0 where `student_stop` raises below 2. Inside the
measured 3-to-5 range they agree; outside it they do not, and
`test_a_t_without_finite_variance_is_refused` pins the raising behaviour.

**Does it block this study?** Not the measurement - `scipy` is installed here,
and every number in this document is computed through the production
`student_stop` and `Quantile`. It blocks `quantiles.py` reaching production,
and it means this branch's suite cannot be called green until it is fixed. It
is reported rather than fixed because `till_infinity/` is not this study's to
change.

### `Quantile.observe` costs 1.5 ms a call and should cost nothing

**`Quantile.observe` costs 1.5 ms a call and should cost nothing.** `_side`
passes `dict.setdefault` an eagerly constructed default whose `"q"` is
`student_stop(self.tau, self.dof)`, and Python evaluates that default on
**every** call rather than only when the key is absent - so a scipy
`t.ppf`, measured at **629 us**, runs once there and once more in the `flat`
comparison, on every observation, for a number that never changes. Measured
with 2,000 calls of each: `student_stop` 629 us, `observe` 1,499 us, a ratio
of 2.38.

It is a runtime defect and not a correctness one - the value is right - so it
does not block this study on its own. The fix is to compute the baseline once
(`functools.lru_cache` on `student_stop`, or a field set in `__post_init__`),
it would make this panel about three times faster, and it is **required** by
the `tails.reach` change above rather than merely desirable: the dependency-free
implementation is 1,696 us a call. On the live path this is 1.5 ms per decision
for a number that never changes.

Two smaller observations on the same module, neither blocking:

* **`Quantile` cannot be seated at a horizon.** The only way to start it
  anywhere but `student_stop` is to write `state[side]` directly, which this
  harness does for the `quantile-seated` arm. A `start` or `horizon` argument
  would make the horizon-aware baseline a supported starting point rather than
  a reach into a field.
* **`GAIN` is an absolute step, so its convergence time scales with the
  quantile it is converging to.** A step proportional to the current estimate
  would be scale-free, which is what the rest of the module is.

## How it is run

One invocation, 60 jobs - the 15 feed-intervals crossed with the four
surrogate arms (`real`, `garch-bars`, `walk-geometry`, `bar-shuffle`), because
the feed-intervals alone leave a 64-core box 49 cores idle and the expensive
part is per arm. Every job writes a disjoint set of rows, so nothing is
duplicated and the real arm is computed once.

```sh
uv run python -m research.ideas.stop_coverage_run --out <dir> --workers 60
uv run python -m research.ideas.stop_coverage_report <dir>/stop_coverage.jsonl
```

**Not on this box and not on the production instance.** Two cores and a 2.6GB
limit there, shared with the live desk, and research on it has OOM-killed the
desk three times.

## Results

*Pending the panel run.*

## Deviations

*Recorded here as they happen, against the pre-registration above.*

1. **Four additions, all declared before the run**, each with its reason in
   the body above and each marked as an addition throughout. The four arms the
   study was asked for are reported unchanged beside them.
   * **`t-sqrt-h`**, because at `H` > 1 the four requested arms contain no
     fairly scaled parametric baseline, so "the empirical beats the t" would
     be a statement about a missing square root rather than about any data.
   * **`quantile-seated`**, because `GAIN`'s absolute step cannot reach a
     twenty-bar quantile inside the trade count the data holds, so the
     requested `quantile` arm would be measuring a convergence budget.
   * **the 500-anchor cap** on a non-overlapping stream, so the horizon sweep
     compares horizons at a comparable trade count. The primary horizon is
     240-256 anchors and is not capped.
   * **the narrowing of the deeper null draws** to the primary horizon and the
     primary unit, because the 16 draws exist to bound the statistic the
     verdict is scored against.
2. **The 1d panel is 4,477-5,009 bars over 15.5-19.9 years, not 4,980-5,009
   over 19.2-19.9.** `usdcnh` is the eighth FX feed and its best venue carries
   4,477 bars over 17.2 years; the brief's range covers the other eight cells.
   Reported per feed, so no pooled span hides it.
3. **The pass rule takes the wider of the binomial and the block-bootstrap
   interval**, where the pre-registration said the binomial one. A binomial
   interval assumes independent rows and the dense stream's rows share most of
   a window, so the rule as written would have called a dense reading
   calibrated or not on an interval of +-0.008 that no part of this data
   supports. On the non-overlapping stream the two agree, so the headline
   table is unaffected and the correction only bites where it should. The
   block length itself is a second correction, caught by its own test: a
   calendar-day block, which is what the rest of this folder uses, reads
   **1.35x** the binomial sd on a 48-bar dense daily stream, because a daily
   calendar day holds one anchor and the overlap is between days.
4. **The 15m venues are the quote venues, not the bar-count venues.**
   `venue_for` would pick FOREXCOM for eurusd 15m (5,136 bars against DERIV's
   5,135) whose measured spread is 0.17 bps rather than DERIV's 1.04 - a
   sixfold cost difference on a one-bar data gain. Anything priced uses the
   venue whose quotes are measured.
