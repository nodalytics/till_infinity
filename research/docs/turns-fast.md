# Turns do not port to an hourly clock, and the daily result needs re-reading

Run: `python research/harness/turns_fast.py`

**Measured 2026-09-23** on seven instruments at 1h, 100,000 bars each. The question was whether
`turns.md`'s result - the strongest **unbuilt** signal in this folder, AUC **0.595 [0.540, 0.654]**
over 310 turns - survives a change of clock, because its 60-**day** horizon is unusable on a desk
that now enters between 1m and 30m.

It does not port. And chasing why turned up something about the original.

## The answer to the question asked

Keep every clause and change only the bar clock: in an established uptrend near its highs, will
price fall 20 of its own move units within 60 **hourly** bars?

| symbol | n test | base | universe | AUC | 95% episode |
| --- | ---: | ---: | ---: | ---: | --- |
| btcusd | 1,443 | 0.5% | 16.0% | 0.6836 | [0.502, 0.826] |
| xauusd | 9,504 | 2.2% | 34.4% | 0.5665 | [0.441, 0.698] |
| xagusd | 5,550 | 1.2% | 20.0% | **0.4236** | [0.326, 0.657] |
| eurusd | 14,615 | 2.3% | 48.7% | 0.4947 | [0.410, 0.597] |
| gbpusd | 14,445 | 2.5% | 48.2% | 0.5409 | [0.444, 0.662] |
| usdjpy | 16,152 | 5.7% | 53.8% | 0.6460 | [0.542, 0.725] |
| usdcad | 9,817 | 1.0% | 54.5% | 0.4648 | [0.244, 0.820] |

**Mean AUC 0.5457, and 2 of 7 episode intervals exclude 0.5.** Two instruments sit *below* it. The
btcusd 0.684 is the one to distrust rather than to quote: 1,443 test rows at a 0.5% base rate is
about seven positive events, and its interval runs to 0.826 accordingly.

So trend exhaustion does not look scale-free. `break-trade.md` found the break hazard crossing even
money at four to seven bars of the level's own timeframe across a thirtyfold span, and
`breakout-runs.md` found excursion scale-invariant at every quantile - **turns are not that kind of
object.** The daily result should stay on the daily, which means it stays unbuilt, because this desk
has no 60-day horizon.

## The part that matters more: what the original was probably measuring

The first version of this harness scored **0.6612** on eurusd and **0.6556** on gold, both intervals
excluding 0.5 - *better* than the daily. That was the tell, not the result, and two things were
wrong.

**The gate was not gating.** It kept **94.1%** of eurusd bars. The original is explicit that the
label is only interesting against *moments that looked the same and continued*, and warns that a
model which learns to tell a bull market from a bear market "has answered an easier question and
would score well doing it". A gate admitting almost everything guarantees exactly that. Tightened to
1% of the trailing high plus a minimum trend age, the universe falls to 16-55%.

**And the label was answerable from volatility alone.** This is the substantive finding.

The drop threshold is *20 of the instrument's own move units*, where a move unit is the **median
absolute return over the whole sample** - one number per instrument. That makes the threshold a
**fixed distance**, and then current volatility predicts reaching it almost by construction: a
20-unit fall is easy in a loud stretch and hard in a quiet one, whatever the trend is doing.

Measured directly, with the same model and the same universe, against the original's fixed-threshold
label:

| symbol | model AUC | **`vol` alone** |
| --- | ---: | ---: |
| btcusd | 0.337 | **0.679** |
| xauusd | 0.465 | **0.673** |
| xagusd | 0.558 | **0.649** |
| eurusd | 0.413 | **0.637** |
| gbpusd | 0.518 | **0.636** |
| usdjpy | 0.403 | **0.608** |
| usdcad | 0.351 | **0.670** |

**Volatility alone scores 0.608 to 0.679 on every one of the seven, and beats the full model on all
seven.** A single feature that beats the model everywhere, on a label whose threshold it mechanically
governs, is not a signal - it is the label leaking into the feature set.

And `auditing.md` records of the daily original: *"`vol` alone at 0.604 is the top of a ten-signal
scan"*. **0.604 is the same number in the same place.** So the daily 0.595 is very likely
substantially this artefact rather than a measurement of trend exhaustion.

Once the threshold is scaled by **trailing** volatility - "twenty sigma as sigma stands now", so
volatility can no longer answer by knowing its own size - the effect falls to the 0.546 mean in the
first table.

## What this does and does not establish

**It does not refute `turns.md`.** That result has a purged walk-forward, an episode bootstrap and
310 turns behind it, and this is a different clock, a different universe gate and a different label
normalisation. Two of its own three named features - age and extension - are not implicated: on the
vol-scaled label here they score 0.353-0.731 and 0.402-0.754 with no consistent ordering, which is
uninformative rather than damning.

**What it does establish** is that the fixed-threshold label admits an artefact large enough to
produce the original's effect size on its own, on seven instruments, at a different frequency. That
is enough that the daily number should not be built on until it has been re-run with the threshold
scaled by contemporaneous volatility. `turns.md` now carries a pointer to this page.

The cheap version of that re-run is one line in the original harness: replace the per-instrument
median move unit with the trailing standard deviation at each bar. If the 0.595 survives it, the
signal is real and the only problem left is the clock. If it does not, the strongest unbuilt result
in this folder was a volatility proxy.

## Method notes

* the interval is an **episode bootstrap** over contiguous blocks of at least the horizon: two bars
  an hour apart share 59 of their 60 forward bars, and resampling rows would return an interval
  several times too narrow, which is how an overlapping-window study manufactures significance;
* the split is chronological with a **purge** of `HORIZON` bars, so no training row's forward window
  reaches into the test block;
* **three features, named in advance** - age, extension, volatility - because `auditing.md`'s
  complaint about the original is that its best number is the top of a ten-signal scan, and a scan
  reporting its maximum needs a correction this avoids by not scanning;
* base rates run 0.5% to 5.7%, so these are rare-event AUCs and the per-instrument counts matter
  more than the pooled mean.
