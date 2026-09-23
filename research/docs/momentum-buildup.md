# Momentum Bar Build-Up: the test the paper could not run

Run: `python research/harness/momentum_buildup.py`

**Measured 2026-09-23.** The desk supplied
[`momentum_bar_buildup_research_paper.docx`](momentum_bar_buildup_research_paper.docx), which
specifies the hypothesis, the ablation, the universe and the validation protocol - and marks its own
empirical component **pending**, for a reason worth quoting in full:

> *I attempted to retrieve executable raw OHLCV files for the proposed cross-asset test, but the
> execution environment could not resolve the external raw-data host. Because the raw observations
> were not actually available to the analysis runtime, this document intentionally does not fabricate
> accuracy, Sharpe, drawdown, p-values, or regression coefficients. [...] a research paper containing
> invented backtest statistics is not a research paper. It is fan fiction wearing statistics.*

This desk has the data. So this is that test, on the universe the paper asked for, with the ablation
it specified and none of the parameters tuned.

## The claim, kept narrow

> *Momentum velocity and acceleration may provide incremental predictive information about future
> returns after controlling for the current momentum level and standard trend measures.*

    M = (weighted return sum) / sigma             momentum level
    V = M(t) - M(t-k)                             velocity
    A = V(t) - V(t-k) = M(t) - 2M(t-k) + M(t-2k)  acceleration

The paper is careful that regression slope is a standard trend statistic and the novelty, if any, is
in the **derivatives of a normalised momentum process**. That framing is preserved: `M`, sigma and a
price-regression slope are all controls, and the question is only what `V` and `A` add on top.

## The answer

Null, on every instrument and every horizon.

| symbol | h | R²(B6) − R²(B4) | net bp | block floor |
| --- | ---: | ---: | ---: | ---: |
| eurusd | 1 | −0.00002 | −3.93 | −4.06 |
| eurusd | 5 | +0.00007 | −4.05 | −4.44 |
| eurusd | 20 | −0.00007 | −4.28 | −5.87 |
| btcusd | 1 | −0.00112 | −4.67 | −5.57 |
| btcusd | 5 | −0.00375 | −7.79 | −11.53 |
| btcusd | 20 | −0.00160 | −14.69 | −27.44 |
| xauusd | 1 | −0.00003 | −3.73 | −4.01 |
| xauusd | 5 | −0.00013 | −2.48 | −3.46 |
| xauusd | 20 | **+0.00024** | **+0.67** | −2.53 |
| xagusd | 1 | +0.00001 | −3.86 | −4.40 |
| xagusd | 5 | −0.00007 | −3.71 | −5.54 |
| xagusd | 20 | −0.00007 | −3.50 | −9.94 |

**Nine of twelve incremental R-squareds are negative** out of sample - the full MBB state does
*worse* than `M + sigma` - and the three positives are +0.00001, +0.00007 and +0.00024. Eleven of
twelve lose money net of a 4bp round trip, and lose by roughly the spread, which is what a signal
carrying no information looks like when it is made to trade.

**The one cell that makes money is the one to be most careful about.** Gold at twenty bars nets
**+0.67bp** with an incremental R-squared of +0.00024 - and its block-bootstrap interval reaches
down to **−2.53**, so it does not clear its own floor. One positive cell in twelve is what chance
produces; at `alpha = 0.05` the expectation is 0.6 of them. **0 of 12 cells have both a positive
incremental R-squared and a net above its own bootstrap floor**, which is the conjunction the
harness reports and the only one worth reading.

The full ablation on eurusd at one bar, which is the shape everywhere:

| model | OOS R² | ΔR² | IC | hit | net bp |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 sign(recent) | −0.00006 | — | 0.004 | 51.0% | −3.79 |
| B1 M | 0.00000 | +0.00007 | 0.002 | 49.9% | −4.20 |
| B2 MA fast−slow | −0.00001 | −0.00001 | 0.002 | 50.4% | −4.27 |
| B3 slope | −0.00002 | −0.00001 | 0.002 | 50.3% | −4.04 |
| B4 M + sigma | 0.00002 | +0.00004 | 0.007 | 49.9% | −4.19 |
| B5 M + V + sigma | −0.00009 | −0.00006 | 0.001 | 51.0% | −3.80 |
| B6 full MBB | 0.00005 | +0.00013 | 0.008 | 50.3% | −4.05 |

**B5 minus B4 prices velocity and B6 minus B5 prices acceleration**, which is the sequence the paper
insists on - *"if B6 works but B4 already explains nearly all of the improvement, then the
acceleration story is weaker than it initially appears."* Velocity comes out at −0.00006. There is no
improvement for acceleration to explain a share of.

Hit rates sit between 49.9% and 51.0% across every model and horizon, which is the band this folder
has measured a dozen other directional candidates into.

## Why this is not a surprise, and where the idea does work

`a-theory-from-ohlc.md` records that the signed series is near-unpredictable past a few minutes while
**absolute** returns carry long memory. A momentum trajectory is built from signed returns and aimed
at a signed target, so it is pointed at the half that does not predict.

**But the MBB idea has a positive precedent here, and it is worth being precise about it.**
`slopes.md` measured `slope` *and* `prior_slope` together as worth **+0.030 AUC** on hold-versus-break
over 10,869 touches, and gave exactly the MBB argument for why the pair is needed and neither half
works alone:

> *a flat approach means one thing after quiet and another after a run, and only the prior window
> tells them apart*

That pair **is** a velocity term - `slope(t) − slope(t−1)` is `V` computed on a price regression
rather than on a normalised momentum - and it is fitted and shipped in `learning/breaking.py` today.

So the trajectory of momentum carries information about **whether a level gives way** and none about
**which way price goes next**. That is the same split `break-features.md` found for the calendar,
which moves volatility by 2.42x and moves break rates not at all, and the same split `breaking.py`
opens with for `up_rate`. Three different quantities, three times the same lesson: direction is the
question this data does not answer, and the questions adjacent to it sometimes are.

## What was done to avoid finding a false positive

The paper's protocol asked for most of this and it is all structural rather than asserted:

* **one parameter set, chosen once, applied everywhere** - lookback 20, derivative step 5, fit window
  10, across four instruments and three horizons. The paper's own warning: *"do not optimize every
  parameter independently for every market and timeframe - that would create a parameter-mining
  machine wearing a lab coat"*;
* **chronological hold-out**, the last 30% of each series, **purged by the horizon** so no training
  row's target overlaps a test row;
* **block-bootstrap intervals**, because overlapping forward windows make neighbouring rows
  dependent - the flaw that turns an IC of 0.01 into a t-statistic of 30;
* **features at bar `t` use bars at or before `t`**, and the forward return starts at `t+1`;
* **costs charged** at 4bp round trip, from `spread_cost.py`;
* **per-asset results**, not a pooled number, and the grid size stated up front so a single cell
  clearing a bar means nothing.

## What is not tested here

The paper asks for a 15m/1h/4h/1d grid; this is 1h only, because that is the resolution this desk
holds deep history for on all four instruments. A parameter sweep over the lookback, the derivative
interval and the fit window is also untested and deliberately so - it is a separate study with a much
larger data-snooping correction attached, and the paper is explicit that a high-performing backtest
selected from a large search space *"is not persuasive unless the search process itself is accounted
for."*

Given nine of twelve negative incremental R-squareds at the pre-specified point, and no cell
clearing both bars, a sweep that found something would need to explain why the effect exists only
away from the point the hypothesis was stated at.
