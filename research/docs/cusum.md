# CUSUM: the side carries nothing, the change-point carries less than more lags

LuxAlgo's "Change-Point Detection (CUSUM)" indicator, reproduced from its Pine
source and put to two questions on 2026-10-17. Harness:
`research/ideas/cusum_regime.py`.

    z    = (logret - sma(logret, L)) / stdev(logret, L)
    sPos = max(0, sPos + z - k)
    sNeg = min(0, sNeg + z + k)
    fire = sPos > h (up) or sNeg < -h (down)   then both reset to 0
    trend := changeUp ? 1 : (changeDn ? -1 : trend)

Defaults L=50, h=4.0, k=0.5. The last line is the one that decides the test:
the indicator colours a regime line green or red and **carries that side
forward until the next fire**, so it is not proposing a fixed-hold trade. The
arm that matches the published claim holds each regime to the next
change-point.

## Part A: the side is null

Pooled over 16 instruments at the published settings, mean forward return in
dispersion units, trades pooled rather than per-instrument means averaged:

| arm | hold 40, 6,778 fires |
| --- | ---: |
| signal | **+0.058 +/- 0.127** |
| placebo | within noise of zero |
| shuffled | within noise of zero |

The regime arm across the six traded cells reads **+0.32, -0.46, -0.42, -0.11,
+0.62, +0.60** - three of six positive, and sign-inconsistent between 1h and 4h
on the same instruments. Regime length runs a median of 71 to 126 bars. The
barrier race never beats `1/(1+r)` at any reward.

### The sweep is monotone in 1/n, which is the tell

| fires | signal at hold 40 | t |
| ---: | ---: | ---: |
| 67,402 | -0.0355 +/- 0.0351 | -1.0 |
| 16,302 | +0.0557 +/- 0.0727 | 0.8 |
| 6,778 (published) | +0.0582 +/- 0.1267 | 0.5 |
| 706 | +1.0416 +/- 0.4471 | 2.3 |
| 691 | +0.9173 +/- 0.4473 | 2.1 |
| 616 | +1.4051 +/- 0.6113 | 2.3 |

The mean grows as the sample shrinks while the t-stat stays pinned near 2.
Every reading above ten thousand fires is zero or negative. A grid that is
monotone in its own sample size and not in `(L, k, h)` is noise, and twenty-
seven correlated cells produce a t of 2.3 somewhere by construction.

One cell disqualifies itself outright: on fx_cross 4h the **placebo** read
+1.07 against the signal's +0.98. A null arm that finds structure selects the
null, so the cell says nothing.

## Part B: the change-point adds, but BOCPD's does and CUSUM's does not

Increment in median out-of-sample R2 over HAR on forward log Parkinson
variance, same frames, classes and procedure as `dispersion-forecast.md`.

| cell | har | +cusum_ret | +cusum_disp | +bocpd | shuffled |
| --- | ---: | ---: | ---: | ---: | ---: |
| fx_cross 1h h=1 | +0.0468 | +0.0294 | +0.0328 | **+0.0373** | -0.0000 |
| fx_cross 1h h=5 | +0.0836 | +0.0038 | +0.0071 | **+0.0374** | +0.0000 |
| fx_cross 1h h=20 | +0.1208 | -0.0003 | -0.0011 | **+0.0428** | -0.0001 |
| fx_major 1h h=1 | +0.0306 | +0.0294 | +0.0628 | **+0.0433** | -0.0002 |
| fx_major 1h h=5 | +0.0516 | +0.0027 | -0.0088 | **+0.0375** | -0.0000 |
| fx_major 1h h=20 | +0.0929 | -0.0227 | -0.0192 | **+0.0346** | -0.0000 |
| metal 1h h=20 | +0.7910 | +0.0047 | +0.0058 | +0.0004 | -0.0009 |
| fx_cross 4h h=20 | +0.3144 | -0.0019 | +0.0438 | +0.0043 | -0.0001 |
| fx_major 4h h=20 | +0.4572 | +0.0029 | +0.0167 | +0.0060 | -0.0000 |
| metal 4h h=20 | +0.4065 | -0.0479 | -0.0328 | +0.0659 | +0.0003 |
| volatility 1h h=20 | -0.0008 | -0.0060 | -0.0065 | -0.0022 | -0.0002 |
| volatility 4h h=20 | -0.0004 | +0.0009 | -0.0045 | -0.0051 | -0.0005 |

**BOCPD's three readings add +0.035 to +0.043 on 1h FX at every horizon** - six
cells, both FX classes, h=1, 5 and 20, with the constant-sigma control at
-0.005 to +0.001 and the shuffled target at zero.

> **Relabelled, 2026-10-17.** `changepoint-increment.md` split the three
> readings. The whole of this increment is the **predictive standard
> deviation** the member infers, not the change-point: the change-point pair
> reads -0.0010 to +0.0106 on HAR and negative on top of a 48-lag baseline. The
> number reproduces; it is simply not about change-points.

**CUSUM's accumulators do not.** `+cusum_disp` is +0.0328 then +0.0071 then
-0.0011 across horizons on the same instruments, and `+cusum_ret` costs metals
**-0.17** at 4h h=1. Sign-inconsistent across horizons on the same cell is the
shape of noise, and the agreement counts for `cusum_disp` are 2 to 4 of 6.

### The caveat that decides whether this is worth building on

**More lags beat it, and by more than twice.** On fx_cross 1h h=20 the shelf's
48-lag ridge reads **+0.198** against HAR's +0.110, so plain extra history adds
**+0.088** where BOCPD's features add +0.0428.

**Answered, and not the way it was framed.** `changepoint-increment.md` split
the three readings and crossed them with the 48-lag baseline: the change-point
pair goes **negative in six of six** 1h FX cells on top of `lin48`, and the
inferred predictive standard deviation adds **+0.2057 to +0.2391**. Extra
history and a change-point posterior were never alternatives for the same
information, because the posterior was not supplying the information. The whole
of the increment below is the variance the member infers.

### Why BOCPD and not CUSUM, mechanically

The two detectors are not the same object. A CUSUM carries two scalar
accumulators and a threshold; `statespace/changepoint.py` carries a posterior
over the **run length**, and publishes three numbers from it - `changepoint`
(mass on a run younger than `FRESH_HOURS`), `run_length`, and `sd`, the
predictive standard deviation it **infers** rather than being told. The third
is a volatility estimate in its own right, which is the quantity being
forecast, so part of the increment may be that rather than the change-point.
Separating them is part of the same next run.

## Three harness faults, and the one worth remembering

The first lab run printed mean forward reads of **10^27 dispersion units**.

1. **A dimensional error the synthetic could not catch.** A price difference
   was divided by a *relative* log-return standard deviation, and the same
   relative number was subtracted from a price to place the stop. On a
   synthetic starting at 1.0 those coincide and every local test passed; on
   gold at 2600 it is wrong by six orders of magnitude.
2. **Dead bars poisoning the unit.** `parkinson` floors a non-positive range
   at `log(1e-300)`, so one untraded bar drags a hundred-bar mean of log
   variance by -6.9 and `exp(mean/2)` collapses.
3. **A shuffled control that was an impossible market.** Block-shuffling
   returns while leaving each bar's high and low in place gave bars whose range
   did not contain their own open and close - a standard error of 5.55 units
   where the other arms read 0.35.

And one reporting fault that mattered as much: **the baseline did not
reproduce.** HAR first read +0.0364 where the shelf has +0.110, because this
harness used every bar `load` returns where `dispersion_ml` cuts to the last
12,000. Every increment was being measured against a baseline three times
weaker than the published one. With the cut restored, metals at 1h h=20 reads
**+0.7910** against the shelf's **+0.791**, and the increments above are
against a baseline that reproduces.

The guard that caught it was written before the run: a line that prints a
warning when a traded class at h=20 reads below +0.05. It fired on two cells
and the result was not reported until it stopped.
