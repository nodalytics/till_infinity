# Two new clocks look better than volume time and both fail the control

*A Thousand Brains* supplies the instruction: the cortex builds its models in
**reference frames**, and "being an expert is mostly about finding a good
reference frame". This desk has twice found the frame mattered more than the
model - volume time absorbs three-quarters of the time-of-day volatility
profile, and the same ladder earns +191 to +547 in log-volatility space while
losing on 5 of 5 controls in price space.

So `research/ideas/reference_frames.py` tries the frames that had not been
tried. **Range time** closes a bar each time price has travelled a fixed
distance; **imbalance time** closes one each time the signed intra-bar pressure
from `statespace-orderflow-from-bars.md` has accumulated to a threshold.

**Both are artefacts, and only the control says so.**

## The score has to avoid what each clock fixes by construction

Range time holds each bar's travel constant, so any **range-based** volatility
measure is flat in it tautologically - the same trap as a conformal PIT, where
the rank of a residual among exchangeable residuals is uniform by definition.

So the score is **close-to-close** return behaviour, which no clock here fixes:
the **kurtosis** of standardised returns, and **clustering**, the lag-one
autocorrelation of their squares. Subordination's claim is that increments are
closer to i.i.d. Gaussian in the right frame, and kurtosis 3 with clustering 0
is what that looks like. Bar counts are matched across clocks, because a
kurtosis on 40,000 observations is not comparable with one on 4,000.

## The answer

Medians, as a ratio to the calendar clock on the same instrument.

| clock | traded kurtosis | ratio | traded clustering | ratio |
| --- | ---: | ---: | ---: | ---: |
| calendar | 9.84 | 1.00 | 0.1463 | 1.00 |
| volume | 6.60 | **0.65** | 0.0845 | **0.85** |
| **range** | 5.94 | **0.56** | 0.0564 | **0.53** |
| imbalance | 11.73 | 0.97 | 0.1552 | **1.54** |
| absreturn | 5.67 | **0.53** | 0.1152 | 0.79 |

On traded instruments alone, **range time is the best clock in the study** -
it nearly halves both kurtosis and clustering, beating volume time on each. And
`absreturn` is better still on kurtosis.

Now the controls, whose increments are specified:

| clock | generated kurtosis | ratio | generated clustering | ratio |
| --- | ---: | ---: | ---: | ---: |
| calendar | 2.98 | 1.00 | -0.0071 | 1.00 |
| **volume** | 2.98 | **1.00** | -0.0008 | 0.81 |
| range | 3.23 | **1.06** | **+0.0721** | **5.32** |
| imbalance | 2.79 | 0.92 | -0.0063 | 0.65 |
| absreturn | 2.57 | **0.85** | -0.0012 | 0.51 |

**Range time creates clustering out of nothing.** On processes whose increments
are independent by specification it produces a lag-one squared autocorrelation
of `+0.0721` where the calendar clock reads `-0.0071` - a factor of 5.3, from
no structure at all. It also raises their kurtosis above Gaussian.

The mechanism is a selection effect and it is not subtle once stated: closing a
bar when cumulative range reaches a threshold **conditions the sample on
realised volatility**, and conditioning an i.i.d. series on a function of its
own increments induces dependence between the sampled points. The clock is not
revealing subordination, it is sampling in a way that manufactures the thing
it then measures.

`absreturn` fails the same way more quietly, pushing generated kurtosis to
**0.85** of Gaussian - below 3, which an i.i.d. process cannot be. Same family
of artefact, which is exactly what that arm was carried to detect: if range
time worked only because a bar's range is a volatility proxy, the plain
absolute return would do the same job. It does, including the same way it
breaks.

**Imbalance time is refuted outright**, and needs no control to say so: it is
*worse* than the calendar clock on traded instruments, with clustering at 1.54
times the baseline.

## So volume time stands alone, and that is the result

`volume` is the only clock in the study that is **exactly inert** on the
controls - a kurtosis ratio of 1.00, to two places, on feeds whose tick count is
fixed by their generator, which is precisely what inertness there requires -
while improving both statistics on traded instruments.

That is not a new clock. It is the one `statespace-volume-clock.md` already
found, and this study's contribution is that **two clocks that look better than
it are measuring their own sampling rule**. Without the generated arm, range
time would have been reported as a 0.56 improvement on kurtosis and a better
frame than volume time, on eight of eight instruments.

The reference-frame search is therefore closed with one survivor rather than
three, and the frame that survives is the one with a mechanism behind it:
activity, which this desk has separately measured as worth +2197 nats when
driving `Q` directly.
