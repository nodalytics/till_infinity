# Banded labels: asking whether a move happens, not which way

Measured 2026-09-20, from two papers on candlestick pattern recognition:

* Ba, *Learning Predictive Candlestick Patterns: Vision Transformers for
  Technical Analysis*, CS231n Spring 2025 course report (unrefereed). ViT-Tiny
  on 50,000 chart images, 10 US equities, 5-minute bars, Jan 2020 - Jun 2025.
* Uzun, Lobachev, Kharchenko, Schöler & Lobachev, *Candlestick Pattern
  Recognition in Cryptocurrency Price Time-Series Data Using Rule-Based Data
  Analysis Methods*, Computation 12(7):132, 2024. Abstract only - MDPI's WAF
  refuses this host, so nothing here rests on its contents.

Neither method is worth porting. The first is a course project whose visual
pipeline needs a GPU this desk does not have, and whose claim that images beat
numerical OHLC rests on an LSTM baseline scoring 0.05 and 0.03 recall, which is
a broken baseline rather than evidence. **The labelling is the transferable
part, and it exposed a gap in what had been measured here.**

## The gap

The horizon sweep in `../planned/directional-edge.md` labelled the **sign** of
the forward return, so a 0.1bp drift and a 50bp move counted as the same event.
Every horizon came back at 50.5%. The ViT paper instead labels Up / Flat / Down
against a magnitude threshold - 0.5% over 25 minutes - and its "flat" class is
80% of its data.

That implies a question the sign label cannot answer: **when the market actually
moved enough to pay for the spread, was the call on the right side?**

## Flat dominates, and direction is still absent

28,208 level calls on the 33 core instruments, labelled against a 4bp band -
twice the stated round-trip spread, so only moves that could pay for a trade
count as movement:

| horizon | flat (no 4bp move) | moved | hit rate *given* it moved | t | shuffled \|t\| beats it |
|---|---|---|---|---|---|
| 1m | **86.0%** | 3,958 | 49.3% | -0.86 | 42.2% |
| 5m | 68.3% | 8,948 | 49.7% | -0.55 | 61.8% |
| 15m | 53.9% | 13,023 | 50.1% | 0.27 | 81.8% |
| 1h | 34.9% | 18,286 | 50.7% | 1.80 | 7.0% |
| 4h | 20.9% | 21,939 | 50.4% | 1.15 | 24.2% |
| 1d | 6.8% | 21,037 | 47.7% | -6.54 | 0.0% |

The hypothesis is **false**. Conditioning on a real move does not reveal a
direction that costs were hiding: the call is 49.3-50.7% at every horizon out to
four hours. The 1h cell at p = 0.07 is one marginal result from six tests. The
1d row is the overlapping-window artifact already documented - the same windows
that gave t = -8.31 overlapping and t = -0.94 at one call per instrument per day.

**86.0% flat at one minute** is the useful number, and it is the same shape the
ViT paper reports as its own limitation: its models "did much better at
predicting no movement than they did up/down".

## Whether a move is coming is mildly predictable. It does not help.

Walk-forward, five time-ordered folds, the horizon purged with a 30-minute
embargo, target "move exceeds 1.5x this instrument's own median move" so it is
dimensionless:

| | AUC |
|---|---|
| within one instrument, all features | **0.573** |
| the same harness on a **shuffled** target | 0.511 |
| `vol_bps` alone, pooled | 0.533 |

So there is a real but small signal, which is unsurprising: volatility is
forecastable where direction is not, and the desk already runs GARCH, HAR and an
ensemble that forecast it.

**It does not produce a profitable filter.** A filter that identifies which
signals precede a move does not improve the 50/50 on which way the move goes, so
a trade it admits still pays the spread for a coin flip. Since direction is
absent at every horizon measured, the better action on a flat signal and on a
moving one is the same: don't take it. The only uses of this forecast are
**position sizing**, which improves risk-adjusted return with no directional
edge at all, and trading volatility as an asset, which a CFD account cannot do.

## Three ways this measurement was wrong before it was right

Recorded because each would have shipped as a finding.

1. **AUC 1.000.** `train.csv.gz` still carried `ret_60`, `ret_300`, `ret_900`
   from the meta-model work. `ret_900` *is* the 15-minute move. The drop list
   filtered names containing price words and these contain none.
2. **A single-feature AUC scan did not find it.** `ret_900` is signed while the
   target is absolute magnitude, so the relationship is non-monotonic and ROC
   AUC - which sees only monotonic ones - ranked it below `vol_bps` at 0.624. A
   tree splits both tails and reconstructs the answer exactly. **Screening for
   leakage by single-feature AUC is blind to precisely the leak a tree exploits
   first.**
3. **AUC 0.947 pooled** was read as the feature set fingerprinting the
   instrument, since "moves 4bp in 15 minutes" is largely "is it crypto". That
   guess was wrong - per-instrument base rates are a uniform 31-37% - and the
   within-instrument test that was meant to confirm it returned 0.999, which is
   what forced the search that found the real cause.

What settled it was running the identical harness on a shuffled target: 0.521
against 1.000, which proved the harness sound and the data leaky, in one step
that should have come first.
