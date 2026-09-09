# Change points across instruments, and the control that killed it

Run 2026-09-08. **Cross-asset agreement is not a result.** The effect is about
a volatility unit, the shuffled-label null is sometimes larger than the effect
itself, most of it disappears once the instrument's own timeframes are
conditioned on - and the synthetic control, where the true effect must be near
zero, shows a **larger** number than the real assets do.

That last one is the finding. It is why the control was built.

## The question

[agreeing.md](agreeing.md) measured that a change point calling on three or
more *timeframes* is followed by +7.92v a day out against -1.24v for one alone.
The obvious extension: does a change point on *other instruments* say anything
about this one?

Eight instruments - eurusd, usdcad, usdjpy, gbpusd, btc, eth, gold, silver -
from `prices.db`, 25 days of one-minute bars. `bt1m.db` has neither usdcad nor
silver, so a 423-feed extract was built to get them.

## The confound, which is worse here than it was across timeframes

**These instruments are not independent.** EURUSD, USDCAD and USDJPY are three
views of the dollar; gold and silver are one metal trade. Three of them calling
a change at the same moment may be *one event seen three times*. That is
exactly how MD-FOCuS failed in [localising.md](localising.md), where pooling
the co-dependent high, low and close made the estimate worse rather than
better.

So the peer count has to predict **beyond what the instrument's own timeframes
already say**, and every table is conditioned on `own` as well as on the
realised move. Peers that were not trading are excluded rather than counted as
a silent no - a shut market cannot have agreed or disagreed, and folding it in
would make every weekend look like calm consensus.

`peers_any` counts peers calling a change in **either** direction, because
EURUSD up and USDJPY up are opposite dollar moves and sign-aligning would need
a fitted correlation. `peers_same` is reported beside it.

## The real assets

4,064 events. Peers above the median against peers below, inside deciles of the
realised move:

| horizon | cut | low | high | gap | shuffled null |
| --- | --- | --- | --- | --- | --- |
| 1h | peers_any, all | -0.372v | 0.000v | 0.372v | 0.016v |
| 1h | peers_any \| own == 1 | -0.215v | -0.288v | **-0.073v** | -0.279v |
| 1h | peers_any \| own == 2 | -0.187v | -0.076v | 0.111v | **0.320v** |
| 4h | peers_any, all | 0.091v | 1.404v | 1.312v | -0.067v |
| 4h | peers_any \| own == 1 | 0.117v | 0.719v | 0.602v | **0.789v** |
| 4h | peers_any \| own == 2 | -0.478v | 2.462v | 2.940v | -0.412v |
| 1d | peers_any, all | -0.303v | 0.971v | 1.274v | **-1.598v** |
| 1d | peers_any \| own == 1 | -1.642v | -0.502v | 1.141v | 0.330v |
| 1d | peers_any \| own == 2 | 4.970v | 1.208v | **-3.762v** | -0.238v |

Read the null column. At 4h conditioned on `own == 1`, shuffling the peer
counts at random produces a **larger** gap (0.789v) than the real ones do
(0.602v). At a day unconditioned the null is -1.598v against a real +1.274v.
The signs flip between horizons within the same row family. `own >= 3` never
carried thirty events in enough deciles to be reported at all.

Compare with the cross-timeframe result, where the gap was 9.169v against a
null of -0.663v - a factor of fourteen. This is not that.

## The synthetic control, which is the actual finding

Deriv's synthetics are generated processes with no shared macro factor. Ten of
them - the volatility indices, boom, crash and step - were run as their own
group. The expected cross-asset effect is **near zero**.

| horizon | cut | low | high | gap | null |
| --- | --- | --- | --- | --- | --- |
| 1h | peers_any \| own == 1 | -0.565v | 0.182v | **0.747v** | 0.015v |
| 4h | peers_any \| own == 1 | -2.355v | 1.030v | **3.385v** | -0.228v |
| 1d | peers_any \| own == 1 | 0.759v | 4.097v | **3.338v** | -0.291v |

**The synthetics show a bigger effect than the real assets** - 3.385v against
0.602v at four hours, 3.338v against 1.141v at a day, on the same conditioning.
There is no channel by which crash_500 calling a change should predict
boom_500's next move. Generated processes that share no factor produced a
cleaner "cross-asset edge" than eight instruments that genuinely share the
dollar.

**This is not proof of a bug.** Independent processes still show windows of
apparent co-movement, and nine days is short enough for that to be a
sample-period coincidence rather than a fault. What it does establish is that
the real-asset number is **not measuring what it appears to measure**: whatever
produces 3.4v on instruments with no common factor is also available to produce
1.1v on instruments with one.

The likeliest mechanism, and it is a hypothesis rather than a measurement: the
peer count is a proxy for **broad volatility**. When many instruments are
moving, every instrument's forward move is larger in absolute terms; the
forward return here is signed by the direction of the change, and changes
cluster in volatile periods. Conditioning on the instrument's *own* realised
move does not control the cross-sectional volatility level, and nothing here
does.

## The Volatility 1s series could not be measured, and the reason is not the threshold

The five 1s indices produced **62 events between them** - 24 to 38 per index
over nine days - which is below every reporting threshold in the harness.

**An earlier version of this section drew the wrong conclusion from that**: that
a detector calibrated on FX and crypto is too strict for the 1s synthetics and
needs its own threshold there. Checked on 2026-09-09 across all twenty
synthetics on 1m bars, fires per day at 12 nats:

| feed | fires/day |
| --- | --- |
| volatility_10_index | 0.20 |
| **volatility_10_1s_index** | **0.34** |
| volatility_25_index | 1.02 |
| **volatility_25_1s_index** | **0.11** |
| volatility_75_index | 0.20 |
| **volatility_75_1s_index** | **0.57** |
| jump_10_index | 16.49 |
| range_break_100_index | 20.79 |
| crash_300_index | 42.37 |
| crash_1000_index | 57.70 |
| boom_500_index | 60.36 |

**The 1s series behave exactly like their standard counterparts.** The split is
not one-second against one-minute - it is **spiking generators against
diffusion generators**, and it is 300-fold.

Deriv's volatility indices are constant-volatility diffusions. There is no
regime change in them to find, so a change-point detector staying silent is the
detector being *right*, not being mis-set. Boom, Crash, Jump and Range Break
have spikes, jumps and breaks written into how they are generated, and FOCuS
finds them constantly.

Lowering the threshold on the volatility indices would not reveal anything. It
would manufacture alarms on a process with no changes - which is the failure
`CHANGE_THRESHOLD` already made once in `localising.md`, arrived at from the
opposite direction.

There is a real result buried in this: **the firing rate is a fair reading of
whether the generating process has regime changes at all.** That is a stronger
validation of the detector than anything measured on real prices, because here
the answer is known in advance.

## What this changes

1. **Nothing is published from this.** The cross-timeframe count shipped as a
   feature because it survived its null by a factor of fourteen. This did not
   survive its null at all.
2. **The next cross-asset attempt needs a volatility control**, not just a
   realised-move control - a cross-sectional measure of how much everything is
   moving, conditioned on alongside the instrument's own trigger.
3. **Keep the synthetic group.** It cost one extra run and it is the only thing
   in this document that settled anything. Any future claim of the form
   "instrument A's signal predicts instrument B" should be shown not to hold on
   Deriv's generated indices before it is believed.
4. **The 1s series wants its own threshold** before it is used for anything.
