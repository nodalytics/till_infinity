# Deriv variants: the published law beats the empirical envelope, and spikes stay memoryless

Harness: [`research/harness/derivvariants.py`](../harness/derivvariants.py). Lab run 2026-09-29, on
the seqlab snapshot to 2026-09-12 (3m, 15m and 1h, 50,000 bars each where available) and 60 days
of 1m bars from `research.db`.

## The question

Deriv's indices are a real market here: what is scored is the feed as served, not the brochure.
But Deriv publishes each index's generator law, and [`generators.md`](generators.md) found most of
it true. So can production's tools be built from the law instead of learned from history?

- **The envelope.** Production's next-N-bars envelope ([`envelope.md`](envelope.md),
  [`conformal.md`](conformal.md)) is empirical: a history of past moves in units of a live
  volatility estimate, corrected by AgACI. On an index whose law is published, is the law better,
  and does it help most on a cold start, where the empirical envelope has no history?
- **The spike hazard.** Boom, Crash and Jump are published as memoryless. Is a constant hazard
  calibrated, and does anything beat it? [`anomalies.md`](anomalies.md) found the shock
  forecaster at 0.45-0.52 on Deriv.

Every variant is a model tested against the feed. Walks we generate from each published law are the
controls: they show what "the feed matches its law" reads like.

## Method

**Envelope.** P10/P50/P90 of the N-bar log move, N = 5, 20, 50, scored on the last 40% of each
series by time. Five methods:

| method | what it is |
|---|---|
| `prod` | production's own `Envelope` class (empirical history, AgACI, the single-corrector handover), fed each bar's close and the production unit (`Ranges.ewma_tr_bps`) exactly as the engine feeds it, running from the series' start |
| `prod cold` | the same, started empty at the scored block: a newly followed index, over its first 1,000 bars |
| `law` | the published law. Volatility: GBM at the named σ with the Ito drift (`projection.py`). Jump: Gaussian at 1.32 × the name (`stated.JUMP_MULTIPLE`). Step: a fair ±0.1 coin at one tick a second |
| `iid` | the one-bar log return, fitted on the first 60%, convolved N times by Monte Carlo. Exact if the feed is memoryless; the only law-like method for Boom/Crash, DEX, Range Break and Drift Switch, which publish mechanics but no volatility |
| `hybrid` | the law (or `iid`) with its levels corrected online by AgACI |

The scores are coverage, pinball loss (log-return bps, summed over the three quantiles, reported
against `prod`), width against `prod`, P90 in the worst of twenty time slices, and P90 in the calm
and volatile thirds of the production unit.

**Spike hazard.** A spike bar is a Boom's high minus open, a Crash's open minus low, or a Jump's
|close − open|, above 10 × the median absolute bar move (5 × for Jump). P(a spike within N bars),
N = 1, 5, 20, comes from three sources:

- **published:** 1 − exp(−rate × time), at the rate in the name;
- **constant:** the training period's own rate;
- **model:** gradient boosting on time since the last spike, the gap before it, spikes in the last
  50 and 200 bars, the grind's volatility against its norm, the last 5 bars' grind, and the hour.

Everything is trained on the first 60%. Memorylessness is checked by the gap's CV and by the
next-bar hazard as a function of time since the last spike. Pre-registered: a model AUC above 0.55
with a CI above 0.5, in both halves, is evidence the feed departs from its published
memorylessness.

## Results

### The feed matches its law

| family | realised σ / published | one-bar kurtosis (3m → 1h) |
|---|---|---|
| Volatility 10-100, 15 series | **0.9919-1.0099** | 2.94-3.09 (Gaussian) |
| Jump 10-100 (at 1.32 × the name), 15 series | **0.9867-1.0141** | 6.2-6.7 → 3.1-3.2 (jumps, averaging out) |
| Step | law σ reproduced; real 6.9-7.3%, walks 6.5-7.5% | 3.02-3.06 |

This confirms `generators.md` on a second, longer sample, at every timeframe.

### Warm: the law is sharper than the empirical envelope, and flat across regimes

Real feeds, means over series and timeframes (3m, 15m, 1h):

| family | N | method | P10 / P90 | pinball vs prod | width vs prod | P90 calm / volatile |
|---|---|---|---|---|---|---|
| Volatility | 5 | prod | 10.0 / 90.0 | 1.000 | 1.000 | 88.5 / 91.8 |
| | 5 | **law** | 10.1 / 90.0 | **0.990** | 0.988 | **90.0 / 90.4** |
| | 20 | prod | 10.0 / 89.9 | 1.000 | 1.000 | 88.6 / 91.5 |
| | 20 | **law** | 10.2 / 90.1 | **0.968** | 0.968 | **90.1 / 90.4** |
| | 50 | prod | 10.3 / 89.9 | 1.000 | 1.000 | 88.4 / 91.4 |
| | 50 | **law** | 10.3 / 90.4 | **0.934** | 0.943 | **90.2 / 90.5** |
| | 50 | hybrid | 11.4 / 88.7 | 0.975 | 0.933 | 88.6 / 89.0 |
| Jump | 20 | prod / **law** | 10.0 / 90.0 both | 1.000 / **0.966** | 1.000 / 0.971 | 88.0 / 92.0 → **89.8 / 90.3** |
| | 50 | prod / **law** | 10.1 / 89.8 both | 1.000 / **0.931** | 1.000 / 0.930 | 87.9 / 91.8 → **89.6 / 90.1** |
| Step | 50 | prod / **law** | 10.2 / 89.9 → 11.2 / 90.7 | 1.000 / **0.932** | 1.000 / 0.935 | 88.4 / 91.8 → 90.9 / 90.6 |
| Boom / Crash | 20 | prod / **iid** | 10.3 / 89.7 → 10.3 / 89.8 | 1.000 / **0.962** | 1.000 / 0.964 | 87.1 / 92.5 → **89.6 / 90.1** |
| | 50 | prod / **iid** | 10.2 / 89.7 → 10.5 / 89.9 | 1.000 / **0.923** | 1.000 / 0.923 | 87.0 / 92.4 → **89.9 / 90.2** |
| DEX, Range Break, Drift Switch, Step | 50 | prod / **iid** | 10.2 / 89.9 → 10.7 / 89.3 | 1.000 / **0.941** | 1.000 / 0.929 | 88.4 / 91.8 → 89.5 / 89.5 |

Our walks from the same laws read the same way: Volatility at N = 50 has law pinball 0.921 against
prod, calm/volatile 88.6/91.7 against prod's 86.4/92.3.

**Why the law wins.** On a constant-σ generator the only thing that varies bar to bar is the
production unit's *estimate* of σ. An envelope in units of that estimate breathes with its noise,
so it is too narrow when the estimate reads low and too wide when it reads high. That is the
88/92 calm/volatile split, the 3-7% extra width, and the 3-7% worse pinball at 20-50 bars. A
constant band has none of it. This is the envelope-level form of `generators.md`'s "no volatility
clustering": there is no regime to adapt to, so adapting only adds error.

**What the law does not beat.** The P90 worst slice is no better (Volatility at N = 50: law 79.5%,
prod 81.3%). The walks have the same worst slices (77.0 against 76.8), so this is the sampling noise
of overlapping 50-bar moves in one twentieth of a series, not a fault of either method.

**Correcting the law makes it worse.** Hybrid's P10 drifts to 11.2-11.8% at N = 50, and its pinball
is between prod's and the law's. There is nothing for AgACI to correct, so it chases noise.

### Cold: the law is calibrated from bar zero; the empirical envelope is not

The first 1,000 scored bars, for an index the envelope has never seen:

| family | N | prod cold P10 / P90, worst slice | law (or iid) P10 / P90, worst slice | pinball law vs prod cold |
|---|---|---|---|---|
| Volatility | 20 | 10.8 / 87.8, 40.0% | 9.3 / 89.8, 53.7% | **0.914** |
| Volatility | 50 | **14.0 / 84.9**, 9.9% | 9.1 / 89.6, 36.7% | **0.846** |
| Jump | 50 | 12.5 / 86.7, 16.7% | 12.1 / 89.6, 26.8% | **0.835** |
| Boom / Crash (iid) | 50 | 10.8 / 84.6, 6.3% | 11.8 / 89.4, 37.4% | **0.828** |

A cold production envelope is silent for its first 200 resolved moves. Over the next 800 its 50-bar
P90 held 85-87%, and some twentieths of the block held under 10%. The published law holds 89.6%
from the first bar. For Boom/Crash and the other mechanics-only families, `iid` has the same
advantage only because it was fitted on the training history, so it is not truly cold.

### Spikes: memoryless, as published, on every series

1m bars, 60 days, 86,411 bars each:

| series | spike every | gap CV | next-bar hazard, from just after a spike to over 2 mean gaps since | model AUC, spike within 20 bars [95%], halves |
|---|---|---|---|---|
| Boom 300 | 53.2 min | 1.011 | 0.019 → 0.018 | 0.506 [0.480, 0.535], 0.516 / 0.495 |
| Boom 500 | 25.6 min | 0.983 | 0.040 → 0.038 | 0.508 [0.484, 0.530], 0.528 / 0.489 |
| Boom 1000 | 26.3 min | 0.993 | 0.039 → 0.038 | 0.508 [0.486, 0.532], 0.512 / 0.504 |
| Crash 300 | 53.2 min | 0.982 | 0.018 → 0.020 | 0.500 [0.474, 0.522], 0.471 / 0.530 |
| Crash 500 | 25.6 min | 1.001 | 0.040 → 0.038 | 0.486 [0.461, 0.506], 0.483 / 0.490 |
| Crash 1000 | 27.2 min | 0.977 | 0.036 → 0.037 | 0.502 [0.485, 0.521], 0.501 / 0.504 |
| Jump 10 / 50 / 100 | 51-54 min | 1.018-1.041 | 0.020 → 0.018 | 0.485-0.498, CIs span 0.5 |
| **walks we generate** (Boom 1000, Crash 500, Jump 50) | 21-52 min | 0.984-1.002 | flat | 0.506-0.519 |

- **No series departs from memorylessness.** Every AUC is within 0.486-0.508, every interval spans
  0.5, and every Brier skill against the constant hazard is negative (−0.0001 to −0.03). The walks
  we generate read the same. The pre-registered test is not met anywhere. 3m agrees wherever it
  finds enough spikes.
- **The published rate cannot be quoted from bars.** The name gives one spike per N *ticks*. A bar
  detector sees 9-63% of that at 1m, fewer at 3m, and its count moves with the threshold (Boom 1000
  at 1m: 4,084 / 3,282 / 1,758 at 5× / 10× / 20×). `generators.md` measured the published rate at
  tick level. On bars, only the feed's own constant hazard is calibrated: Boom 1000 1m, a spike
  within 20 bars, realised 0.528 against 0.544.

## What this means

- **On the named indices, the law beats the envelope, and the reason is structural.** Volatility,
  Jump and Step have a published constant scale. An envelope measured in a noisy live estimate of
  that scale is 3-7% wider, 3-7% worse on pinball at 20-50 bars, and splits 88/92 between calm and
  volatile regimes that the generator does not have. The law is flat at 90/90 and needs no history.
- **The mechanics-only families win the same way, from their own history.** Boom/Crash, DEX, Range
  Break and Drift Switch have no published scale. The convolved one-bar law, fitted once, beats the
  live-unit envelope by the same margins (pinball 0.92-0.94 at N = 50), because the feeds are
  memoryless. It needs a history, so it does not fix their cold start.
- **The spike hazard is a constant, and nothing times it.** A card could say "a spike within the
  next 20 bars: 53%" for Boom 1000 at 1m, and that would be true. It would be the same number on
  every card, because nothing about the recent past moves it.
- **AgACI is right for real markets and wrong for these.** Hybrid loses to the plain law everywhere.
- **Caveat:** the Boom/Crash control in the envelope part was mis-built (Crash 300 simulated as a
  Boom, realised σ in the thousands of percent). It is excluded above. The hazard part's own
  Boom/Crash controls are correct and read as the feeds do.

## For production

1. **Quote the envelope from the published law on Volatility, Jump and Step indices.** In
   `structures/vol/envelope.py`: where `projection.sigma_for` returns a σ (Volatility, Jump with
   its 1.32 × multiple), quote the Gaussian N-bar band at the Ito drift instead of the empirical
   history. Add Step's ±0.1 coin. No AgACI on these. Keep the realised-cover line on the card; it
   now monitors the generator rather than the model, which is `projection.py`'s own view of
   calibration. Expected: calibrated from bar zero, 3-7% narrower at 20-50 bars, and no
   calm/volatile skew.
2. **Optionally, for Boom/Crash, DEX, Range Break and Drift Switch:** a fixed per-instrument N-bar
   quantile table from the convolved one-bar law, refreshed by the retraining pipeline, rather than
   the live-unit envelope. It is the same gain on a warm feed, but it is one more frozen model to
   maintain.
3. **A spike line on Boom/Crash cards is optional and static.** "Spike within N bars: X%" from the
   feed's own recent rate. It is true, but it never changes with conditions, so it tells the reader
   the risk and not the timing. The shock forecaster's Deriv readings (0.45-0.52) should stay off
   these cards.
4. **Nothing here trades.** A constant band and a constant hazard are the honest answers on a
   memoryless generator. Their value is sizing and stop distance.
