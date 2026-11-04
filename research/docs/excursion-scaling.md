# The adverse excursion does scale as the square root, as far as this data can tell

**Measured 2026-11-03, pre-registered in
[excursion-scaling-prereg.md](excursion-scaling-prereg.md).** Harness:
[`research/ideas/excursion_scaling.py`](../ideas/excursion_scaling.py).

| criterion, frozen before the run | result |
|---|---|
| 1. `\|k - 0.5\|` beats the hardest surrogate on 3+ instruments | **NOT MET** — 0 of 7 |
| 2. the sign of `k - 0.5` agrees across instruments | **NOT MET** — 10 above, 4 below |
| 3. both generated walks return 0.5 | **MET** — 0.505, 0.513, 0.527, 0.508 |
| 4. `H^k` flattens the coverage drift on two thirds of feed-sides | **NOT MET** — 10/14 in sample, **5/14 out of sample** |

**`sqrt(H)` stands.** [stop-coverage.md](stop-coverage.md)'s square root was
derived rather than measured - from the reflection principle on a driftless
Gaussian walk - and the drift it leaves (realised coverage 0.133, 0.150, 0.170
at H of 1, 20, 48 against a 0.100 target) is real but is **not** explained by a
different scaling exponent.

The binding constraint is the data, not the market: **44 to 50 non-overlapping
windows per horizon** on 5,000 daily bars. The pre-registration assumed that
was enough and it is not.

## What was measured

For each feed and side, the `TAU` quantile of the adverse excursion -
`stop_coverage.excursions`, unchanged, so the two studies' numbers are the same
quantity - at horizons 1, 2, 5, 10, 20, 48 and 96 bars, non-overlapping. Then
`log q(H) = k log H + c` by least squares. A driftless walk gives `k = 0.5`.

Nine feeds (eight FX plus gold) at 1d, two sides, three arms from
`level_shield.py` at 16 draws each, two generated controls. **3,216 fits, zero
errors.**

## The exponents

| feed | side | k | \|k-0.5\| | hardest arm | windows |
|---|---|---|---|---|---|
| audusd | +1 | 0.5748 | 0.0748 | 0.1740 | 49 |
| audusd | -1 | 0.4845 | 0.0155 | 0.2020 | 49 |
| eurusd | +1 | 0.5550 | 0.0550 | 0.1713 | 50 |
| eurusd | -1 | 0.4980 | 0.0020 | 0.1800 | 50 |
| gbpusd | +1 | 0.5604 | 0.0604 | 0.1595 | 50 |
| gbpusd | -1 | 0.4799 | 0.0201 | 0.1621 | 50 |
| gold | +1 | 0.4745 | 0.0255 | 0.2748 | 50 |
| gold | -1 | 0.5105 | 0.0105 | 0.2147 | 50 |
| usdchf | +1 | 0.5106 | 0.0106 | 0.1696 | 49 |
| usdchf | -1 | 0.5157 | 0.0157 | 0.1628 | 49 |
| usdcnh | +1 | 0.5657 | 0.0657 | 0.2041 | 44 |
| usdcnh | -1 | 0.5660 | 0.0660 | 0.1715 | 44 |
| usdjpy | +1 | 0.5235 | 0.0235 | 0.1639 | 49 |
| usdjpy | -1 | 0.5398 | 0.0398 | 0.1581 | 49 |

Median `k` is 0.5196 over a range of 0.4745 to 0.5748. **Every real deviation
is smaller than its own hardest surrogate deviation, on every cell** - real
runs 0.002 to 0.085 while the surrogates run 0.158 to 0.275, so the null
produces two to a hundred times the effect. Shuffled bars manufacture a larger
apparent departure from 0.5 than any real feed shows. The placebo pair
(`nzdusd`, `usdcad`) beats nothing either.

## Criterion 4 was overfitting, and the split says so

The in-sample reading looked like the result: fitting `k` and scoring the
coverage spread on the same windows flattened the drift on **10 of 14**
feed-sides, with gbpusd going 0.084 to 0.036 and usdjpy 0.076 to 0.033.

Fit `k` on the first half and score the coverage on the second and it
**reverses to 5 of 14** - worse than a coin:

| feed | side | sqrt | fitted | delta |
|---|---|---|---|---|
| gbpusd | -1 | 0.0300 | **0.1651** | +0.1351 |
| usdchf | -1 | 0.0433 | 0.1267 | +0.0833 |
| eurusd | +1 | 0.1058 | 0.1379 | +0.0320 |
| gold | -1 | 0.3770 | 0.2170 | -0.1600 |
| gbpusd | +1 | 0.1283 | 0.0783 | -0.0500 |

The largest in-sample winner, `gbpusd -1`, becomes **five times worse** out of
sample. The one large remaining gain, `gold -1`, sits on the cell with by far
the worst baseline spread, which is where noise lives.

This is `fit-on-the-edge-not-the-raw-score` in its own terms: a parameter that
improves the thing the desk consumes while being indistinguishable from the
null inside its own surrogate spread is fitting its scoring windows. The
same note records fitted weights beating hand-tuned ones on AUC 0.604 against
0.556 while losing on edge, +0.002 against +0.019.

The half-split also disagrees on sign for `gbpusd -1` (A 0.4252, B 0.5346),
which is the feed with the largest apparent in-sample gain.

## The controls failed three times and every failure was real

This is the useful part of the study. Each failure was caught **before any
market data was read**, which is what a control that must return a known value
is for.

| run | k, where a walk must read 0.5 | cause |
|---|---|---|
| 6,000 bars | 0.396 / 0.419 | 62 windows at H = 96; the fitted curve came out **non-monotone** - `5:5.3398` then `10:5.2423`, a quantile *falling* as the horizon doubled |
| 200,000 bars | 0.424 / 0.446 | curve clean, but `q(H) / sqrt(H)` fell smoothly from 2.39 to 1.76 |
| path-aggregated bars | **0.505 / 0.513** | fixed |

The second failure is `a-control-is-only-for-a-named-property` exactly. The
generator set `high = max(open, close) + |N(0,1)| * sigma` - an **independent
wick**, which makes the series a walk *plus noise* rather than a walk seen at
bar resolution. That extra term inflates a one-bar excursion far more than a
ninety-six-bar one, so it biased the slope down. A control built to isolate the
scaling had smuggled in a second effect.

Bars are now twenty aggregated path steps, so the high and the low are the
path's own extremes - which is what a venue's bar is. Residuals fell to 0.007
to 0.017.

**The fat-tailed arm agreeing is the other half of the control.** `gen_fat` has
Student-t innovations at the same variance and reads 0.527 and 0.508, so the
estimator is not responding to kurtosis - the exponent is a property of the
dependence, as the pre-registration required. Had it moved, the harness would
have been measuring `how-markets-differ-from-every-simple-process` again.

## What would change the answer

**More windows.** At 44 to 50 per horizon the surrogate spread is an order of
magnitude wider than the effect being looked for, and nothing about the
estimator is at fault - the 200,000-bar control resolves 0.5 to three decimals.
Either a longer history, a finer clock, or a shorter maximum horizon would
narrow the null; the first two are the real options, because dropping H = 96
removes the horizons where a wrong exponent costs the most.

The reachability note from the pre-registration still holds and is worth
keeping: at H = 48, `H^0.5` is 6.93 units and `H^0.45` is 5.76, a 17% change in
stop distance, while at H = 5 the same exponent gap moves the stop by 4%. So
even a confirmed exponent would be a claim about **long holds only**.

## Gross throughout

No spread is applied. This is a calibration study about where a stop sits, not
a P&L study, and `exotic-spreads-are-a-whole-bar-range` is why nothing here is
quoted as a trade.
