# Changepoint detection and spiking neurons, and why the threshold had to adapt

Measured 2026-09-21 by `research/harness/changepoint.py` on 65,000-90,000 hourly bars per
instrument.

Two questions that arrived separately turned out to be one: can a changepoint detector
find the moment a series changes character, and can a biologically-inspired spiking neuron
detect spikes up and down in a series. Both are detectors, both were tested against the
same ground truth, and both fed the same conditioning experiment.

## The rare luxury: a detector question with a known answer

Almost nothing in this research has ground truth. This does. **Boom indices are built with
sudden upward spikes against a slow grind down, and Crash indices are the mirror.** So
before any trading question, a spike detector has a right answer: the up-channel must fire
far more on Boom than on Crash, the down-channel the reverse, and a symmetric synthetic
must come out symmetric.

| instrument | ON per 1000 | OFF per 1000 | ON − OFF |
|---|---|---|---|
| boom_1000_index | 3.8 | 0.1 | **+3.7** |
| crash_1000_index | 0.2 | 3.8 | **−3.6** |
| boom_500_index | 3.5 | 0.4 | +3.2 |
| crash_500_index | 0.6 | 3.3 | −2.8 |
| volatility_75_index | 2.2 | 1.7 | +0.5 |

Boom fires ON thirty-eight times more often than OFF, Crash mirrors it almost exactly, and
Volatility 75 - which has no built-in asymmetry - comes out symmetric. The detector
recovers a property the broker designed into the instrument, which is the strongest
validation available anywhere in this repository.

## The threshold had to be adaptive, and this is the evidence

The first version used a fixed threshold, calibrated carefully against 200,000 draws of
Gaussian noise: false alarms per 1000 bars ran 6.1 at a threshold of 3, 1.3 at 4, 0.20 at
5 and 0.01 at 6, so 5 was chosen as about one false spike per 5000 bars.

**On real data that detector fires essentially never** - the fixed columns read 0.0 for
every instrument above. The calibration was worthless, because real returns standardised
by true range do not have the scale the Gaussian calibration assumed. A carefully
justified constant produced a dead detector.

The replacement is **homeostatic plasticity**, which is what real neurons use to hold a
firing rate as input statistics change: fire more often than the set point and the
threshold rises, less often and it falls, multiplicatively so it stays positive.

    floor <- floor * exp(ETA * (fired - target))

This replaces an arbitrary voltage with an interpretable research budget - how many events
per 1000 bars the study is willing to look at - and it survives a change of regime, which
a constant cannot. Tested against a deliberate volatility shift:

| ON spikes per 1000 bars | quiet σ=1 | loud σ=4 | quiet σ=1 |
|---|---|---|---|
| fixed threshold | 0.06 | **43.16** | 0.20 |
| homeostatic | 1.96 | 2.24 | 1.86 |

A fixed threshold fires **700 times more often** in the loud regime. It is not detecting
events, it is detecting volatility. The adaptive one holds its rate flat through a
four-fold volatility change. For an ever-changing series this is not a tidiness
preference; it is the difference between measuring events and measuring variance.

### The trap inside the fix

The obvious implementation gives **each cell its own homeostatic threshold**, and it would
have silently destroyed the experiment. If the ON cell and the OFF cell each regulate to
the same set point, they fire equally often on every instrument by construction, and the
ground-truth table above would read zero everywhere.

So the regulated threshold is **shared** between the two cells: the pair holds its combined
rate while the up/down split stays free. Spike-frequency adaptation stays per-cell, as a
fast offset above the shared floor, because that mechanism is about not double-counting one
event and has nothing to do with rate.

### Tonic inhibition, which came first

An earlier version fired every thirty bars on pure noise, and the arithmetic explains it:
rectified unit-variance noise has mean `1/sqrt(2π) = 0.399`, and a leak of `exp(-1/6) =
0.846` accumulates that to `0.399 / (1 − 0.846) = 2.6` - a whisker under a threshold of 3.
The membrane sat permanently near firing. Real ON cells solve this with a maintained
inhibitory baseline adapted to prevailing contrast, so each cell now subtracts a slow EWMA
of its own drive and the potential floors at rest.

## FoCuS, and where it is exact

FoCuS - functional pruning CUSUM - keeps the exact maximum-likelihood CUSUM statistic over
every candidate changepoint by pruning those that can never become the maximiser. For a
Gaussian change in mean with known pre-change mean, the log-likelihood ratio is

    Q(t, θ) = θ (S_n − S_t) − (θ²/2)(n − t)

and maximising over `θ` gives `(S_n − S_t)² / (2(n − t))`, whose maximiser over `t` is
always a **vertex of the lower convex hull of the partial-sum path**. So the pruning is a
convex hull maintained by monotone chain, which is what is implemented and is exact.

Not implemented: the unknown-pre-change-mean case, whose pruning is two-dimensional. The
mean is estimated per segment and the detector restarts after each detection, so this is
**FoCuS0 with restarts, not full FoCuS**.

On planted signals it is excellent - three isolated spikes and a mean shift at bar 1500,
recovered as detections at 400, 900, 1534 and 2400 with no false positives. On real data
its fixed threshold has the same disease as the neuron's did: it fires 0.1 times per 1000
bars, never reaching the 300-sample floor, so **it contributed no usable conditioned cell
at all**. Giving FoCuS the same homeostatic treatment is the obvious next step and has not
been done.

## The conditioning experiment, which failed in an interesting direction

The hypothesis from `imbalance.md` was that gaps are weak as a population because most are
noise, and that gaps marking a genuine change - fresh imbalance - would be stronger. Every
trade uses stop and target one true range apart, so fair odds is 50% for every row and
geometry cannot explain a result.

| cell | n | hit | excess |
|---|---|---|---|
| gap alone | 390,603 | 50.4% | +0.41% |
| gap, no spike | 375,565 | 50.5% | +0.47% |
| **gap + spike** | 15,038 | **48.8%** | **−1.21%** |
| spike alone, against it | 1,266 | 52.4% | +2.45% (±2.81) |
| spike alone, with it | 1,266 | 47.6% | −2.45% |

**A gap that forms at a detected spike performs worse than one that does not.** The
hypothesis is not merely unsupported, it is backwards: conditioning on a genuine change
subtracts 1.6 points rather than adding. Reading it charitably, a gap torn open by a spike
is a level price has already demonstrated it will go through, while a gap formed in
ordinary conditions is one it stopped at.

Fading a spike is the only cell above the fair-odds line at 52.4%, and its error bar is
±2.81 so it does not clear. It points the same way as the Boom/Crash short asymmetry,
which is at least consistent.

All of these are gross figures. `costs.md` measures stop overshoot at 0.17-0.29 R across
these same instruments, which is larger than every number in the table, so none of them is
reachable regardless.

## What stands

* The spiking detector **works**, validated against broker-designed ground truth, and is
  the most reliable instrument built in this research.
* **Adaptive beats calibrated, decisively** - the fixed threshold was dead on arrival and
  the same fix is owed to FoCuS.
* The conditioning hypothesis is **refuted**, with gap-plus-spike measurably worse than
  gap alone across 390,000 trades.
* A detector being good is not an edge. This one recovers the instrument's construction
  precisely and still yields nothing tradable.
