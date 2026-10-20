# The statespace service against the anomaly incumbents: a thin increment, and not where it was expected

**2026-10-18/20. [`research/ideas/statespace_anomaly.py`](../ideas/statespace_anomaly.py),
on [`anomalies.py`](../harness/anomalies.py)'s own labels, features, split and controls.**

[`anomalies.md`](anomalies.md) measured shocks and range blowouts at AUC
**0.76-0.81** an hour or more ahead on real markets, with the Deriv generators
dead flat, and named what carries it: the 14-bar EWMA of true range over its
500-bar mean (0.60-0.77 alone) and `tr_percentile` (0.60-0.73). Those are
incumbents with no model in them.

The statespace service publishes a filtered log variance, a one-step predictive
spread, a coverage-addressed band and a standardised innovation, and **nothing
had ever scored them against those incumbents**. Until this run, "statespace
can see expansions coming" rested on the band holding its coverage, which is a
calibration claim rather than a skill claim.

## Four arms, and the second number in each pair is the claim

`base` is `anomalies.py`'s feature set unchanged. `+ss` adds the service's four
outputs, `+ewma` adds an exponentially-weighted mean of log Garman-Klass and an
EWMA standard deviation of its residuals, and `+bocpd` adds the inferred
predictive standard deviation alone - the column that carried +0.21 to +0.24 on
a 48-lag dispersion ridge in [`changepoint-increment.md`](changepoint-increment.md).

Raw test-block AUC, then AUC **within deciles of `trpct`**, because
[`candle-screen.md`](candle-screen.md) is the standing rule - an AUC of 0.805
appeared there on a process whose generator holds volatility constant:
an arm that restates the volatility the model already sees gains in the first
column and vanishes in the second.

| cell | base (within strata) | +ss | +ewma | +bocpd |
|---|---:|---:|---:|---:|
| fx shock, 15m | 0.7344 | **+0.0117** | +0.0065 | +0.0023 |
| fx range, 15m | 0.7089 | **+0.0155** | +0.0070 | +0.0030 |
| fx shock, 1h | 0.7176 | +0.0067 | +0.0034 | +0.0021 |
| fx range, 1h | 0.7445 | +0.0016 | +0.0011 | +0.0011 |
| metals shock, 15m | 0.7400 | +0.0039 | +0.0049 | +0.0018 |
| metals range, 15m | 0.7282 | -0.0046 | -0.0149 | -0.0036 |
| metals range, 1h | 0.7929 | -0.0001 | -0.0090 | +0.0011 |
| crypto shock, 15m | 0.7104 | +0.0055 | -0.0002 | -0.0003 |
| crypto range, 15m | 0.7188 | -0.0096 | -0.0015 | -0.0021 |
| crypto shock, 1h | 0.7354 | -0.0032 | -0.0049 | -0.0029 |
| **volatility** *(moves published memoryless)* | 0.5442 | **-0.0356** | -0.0230 | -0.0545 |
| **jump** *(jumps published memoryless)* | 0.4985 | -0.0123 | +0.0050 | +0.0047 |
| **boom/crash range, 15m** *(spike timing memoryless - but carries vol-of-vol, see below)* | 0.5875 | **+0.0814** | +0.0627 | +0.0757 |

## What it does not support

**A gate.** The best cell is FX at 15m, where `+ss` adds **+0.012 to +0.016**
AUC within strata - about twice the EWMA control and five times BOCPD's `sd` -
and that is the ceiling. Metals and crypto are flat or negative, and the whole
effect halves going from 15m to 1h.

**The band, the spread and the innovation carry almost nothing on their own.**
Single-feature AUC: `ss_spread` 0.50-0.57, `ss_width` 0.50-0.62, `ss_abs`
0.50-0.55, against the incumbent `lvol` at 0.64-0.77 and `trpct` at 0.61-0.73.
The only statespace column that is competitive is `ss_logvar` at 0.60-0.69 -
and that is still *below* the EWMA of true range it would be replacing. The
filtered level is a slightly weaker version of what the anomaly model already
holds; the band and the surprise are near chance for this question.

**And the largest gain in the whole table is on a control.** Boom/Crash range
at 15m goes from 0.5884 to 0.6676, `+0.0814` - more than any traded cell, on a
generator whose spike timing is **published as memoryless**. The singles say
why: `ss_logvar` reads 0.657 and `ew_logvar` 0.667 there, where `lvol` reads
0.507.

That is not a leak, and the explanation matters for how the FX number should be
read. The label is "range above **4x its trailing 500-bar mean**", so anything
that estimates where volatility sits *relative to that mean* predicts the label
better - and on a two-state generator (a one-signed grind punctuated by spikes)
a log-variance filter separates the two states far better than an EWMA of true
range does. The arms are improving the estimate of the label's own denominator.
`anomalies.md` had already seen the edge of this: it recorded range on
Boom/Crash at 15m as "the one exception (0.588, volatility of volatility),
which is small". It is not small once a filter is pointed at it.

So the honest reading of FX's +0.012 is the same mechanism rather than new
information about shocks: a better-filtered volatility level against a label
defined as a ratio to a volatility level. The standing lesson applies: let the
strongest control name the mechanical part of a label before reading any arm as
information. The control did not fail here - it named the mechanism.

## What it does support

**The controls behave, which makes the table worth reading at all.** The Deriv
volatility family reads **-0.036 to -0.055** on every arm, and `jump` sits
within noise of zero. Where a generator has no regime structure, nothing here
invents any.

**Each of those is a control for one named property, and the names matter**,
because the third of them gained more than any traded class. Volatility and
Jump control for *anomaly timing published memoryless* - nothing seen
beforehand can anticipate one - and that is the only inference they license.
Boom/Crash controls for the same property and **fails as a control for this
label**, because it has a real volatility-of-volatility structure that the
label's trailing-mean denominator is sensitive to. A family is never a control
in general; `synthetics-are-a-poor-tail-control` is the standing version of the
same point, measured on kurtosis 3.19 against 20.07 traded.

**The first consumer was the right one.** `statespace.dispersion` is recorded
on the decision card and read by nothing in `risk.py` or `sizing.py`. This run
is the measurement that would have had to justify a gate, and it does not: a
+0.012 AUC increment over an incumbent the trading service does not even
consult, largest on the one family whose spikes are memoryless, is not a reason
to stand a trade aside.

**And the EWMA control answers the open question from
[`changepoint-increment.md`](changepoint-increment.md) - for this frame only.**
There, BOCPD's inferred `sd` was worth +0.21 to +0.24 R2 on a 48-lag ridge
forecasting log variance, and the named next control was whether a plain EWMA
would supply the same thing. Here, for *classifying* an imminent 4x bar,
`+ewma`, `+bocpd` and `+ss` are all within 0.01 of each other and of nothing.

Those two results are not in tension, and the difference is the question rather
than the method: forecasting the **level** of log variance is a regression where
a better filter is worth a great deal, and ranking **which bars will exceed a
trailing-mean multiple** is a classification an EWMA of true range already
answers. The money on this desk is in the first one - it sizes and places
stops - so the regression result stands and the classification result closes a
door that was never load-bearing.

## The next run this does not do

The regression frame's EWMA control is still open, and it is now the only
version of that question worth running: `lin48 + ewma_sd` against
`lin48 + bocpd_sd` on forward log variance, which is one arm on the harness in
[`changepoint-increment.md`](changepoint-increment.md). This page tested them
as classifiers and found both null; that says nothing about the +0.22.
