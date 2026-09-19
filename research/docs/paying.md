# Does the five-to-thirty-minute edge pay the spread?

[horizon.md](horizon.md) left one number standing. Everything inside five
minutes is a tautology, everything past thirty is a coin, and `300-1,800s` is
+16.44% of edge on 484 observations - about 4.5 standard errors, and the only
unambiguously real figure in the table.

Directional accuracy is not money. In volatility units a touch is worth

    (2 x accuracy - 1) x E|push|   -   cost to cross

Harness: [`harness/paying.py`](harness/paying.py), over every touch in the
record resolving in that band, per instrument. Accuracy is the **floor** -
`up_rate > 0.5` predicting the push direction - because it can be recomputed
for every touch. The kNN scores about 5.5 points better in this band, worth a
further +0.22v per touch, so every number here understates the live model on
purpose.

## The null passes, and that is the headline

| instrument | n | accuracy |
| --- | --- | --- |
| eurgbp | 125 | 86.4% |
| uk100 | 50 | 84.0% |
| usdcnh | 128 | 82.8% |
| eurusd | 57 | 77.2% |
| fra40 | 42 | 76.2% |
| gold | 53 | 75.5% |
| *…twenty more real instruments, 56–73%* | | |
| **volatility_10_index** | 61 | **55.7%** |
| **volatility_25_index** | 51 | **49.0%** |
| **volatility_100_index** | 47 | **44.7%** |
| **volatility_75_index** | 57 | **38.6%** |

**The synthetics score at chance and the real instruments do not.** A Deriv
synthetic is a generated process with no participants, no order flow and no
structure to find - which is exactly why this repository uses them as a null
([shelves.md](shelves.md)). Their mean here is 47%.

If the +16% at five-to-thirty minutes were an artefact of the method - a
leak, a selection effect, a subtler cousin of the tautology - **the synthetics
would show it too**. They do not. This is the first clean evidence in this
investigation that the level model is finding something real rather than
reproducing a definition.

## Cost decides which instruments, and it decides brutally

| instrument | n | acc | E\|push\| | gross | cost | **net** |
| --- | --- | --- | --- | --- | --- | --- |
| spx500 | 52 | 71.2% | 2.75 | 1.163 | 0.225 | **+0.938** |
| gold | 53 | 75.5% | 1.90 | 0.967 | 0.048 | **+0.919** |
| brent | 54 | 68.5% | 2.98 | 1.102 | 0.218 | **+0.884** |
| wti | 70 | 70.0% | 2.67 | 1.070 | 0.200 | **+0.869** |
| us100 | 50 | 72.0% | 1.91 | 0.841 | 0.085 | **+0.756** |
| us30 | 72 | 68.1% | 2.51 | 0.906 | 0.236 | **+0.669** |
| jp225 | 93 | 71.0% | 2.22 | 0.933 | 0.308 | **+0.624** |
| fra40 | 42 | 76.2% | 2.05 | 1.071 | 0.474 | +0.597 |
| us2000 | 108 | 67.6% | 2.45 | 0.863 | 0.464 | +0.400 |
| aus200 | 70 | 68.6% | 2.39 | 0.889 | 0.535 | +0.354 |
| silver | 116 | 71.6% | 1.66 | 0.715 | 0.364 | +0.351 |
| eth | 59 | 74.6% | 1.84 | 0.903 | 0.594 | +0.309 |
| eu50 | 104 | 72.1% | 2.29 | 1.015 | 0.749 | +0.266 |
| ger40 | 59 | 59.3% | 1.94 | 0.362 | 0.155 | +0.207 |
| volatility_10_index | 61 | 55.7% | 2.94 | 0.337 | 0.144 | +0.194 |
| gbpusd | 101 | 70.3% | 1.85 | 0.751 | 0.615 | +0.137 |
| uk100 | 50 | 84.0% | 1.97 | 1.341 | 1.214 | +0.127 |
| eurgbp | 125 | 86.4% | 2.00 | 1.456 | 1.335 | +0.120 |
| gbpjpy | 107 | 72.9% | 1.86 | 0.850 | 0.768 | +0.082 |
| btc | 56 | 57.1% | 2.03 | 0.289 | 0.282 | +0.008 |
| eurusd | 57 | 77.2% | 1.81 | 0.984 | 0.996 | −0.012 |
| eurjpy | 79 | 70.9% | 1.87 | 0.782 | 0.965 | −0.184 |
| audusd | 59 | 72.9% | 1.77 | 0.812 | 0.989 | −0.177 |
| usdjpy | 42 | 64.3% | 1.97 | 0.562 | 0.730 | −0.168 |
| usdcad | 87 | 71.3% | 1.65 | 0.701 | 1.172 | −0.471 |
| eurchf | 108 | 65.7% | 1.95 | 0.614 | 1.163 | −0.549 |
| chfjpy | 106 | 69.8% | 2.02 | 0.801 | 1.382 | −0.581 |
| audjpy | 68 | 55.9% | 2.17 | 0.256 | 0.918 | −0.662 |
| nzdusd | 70 | 64.3% | 2.55 | 0.728 | 1.772 | −1.044 |
| hk50 | 76 | 72.4% | 1.81 | 0.810 | 2.008 | −1.198 |
| **usdcnh** | 128 | **82.8%** | 1.75 | 1.151 | **5.814** | **−4.663** |

**20 of 37 instruments clear their own spread**, and the mean across all of
them is −0.091v - dragged there almost entirely by `usdcnh`.

**The instruments that pay are the indices, the energies and gold.** Every one
of the top seven is a cheap, liquid, dollar-quoted market: spx500 at 0.225v,
us100 at 0.085v, wti at 0.200v, gold at 0.048v. The pattern is not subtle -
they combine a large typical move with a small spread, and the FX crosses do
the opposite.

`usdcnh` is the instructive row: **82.8% accuracy and the worst net on the
board.** A near-five-sixths hit rate cannot pay 5.814 volatility units to
cross. Accuracy without a cost check is not a result, and this row is why the
check exists.

### The first version of this table was wrong, and usefully so

It reported 11 of 26 clearing their spread and a mean of −0.314v. Nine
instruments were unpriced because the harness tried each alias **verbatim**:
`INSTRUMENTS` writes `US TECH 100` and the terminal answers to `US Tech 100`.
Resolving aliases case-insensitively against the broker's own symbol list
priced all nine - and they were *the best rows on the board*, seven of the top
eight.

The same case-sensitivity once reported all nine synthetics as unavailable. A
missing row looks like an instrument nobody trades, which is why it did not
look like a bug.

## What this does not establish

**These are touches, not trades.** A touch is what the model fires on; whether
the desk takes it depends on gates this measurement ignores. The 120 closed
trades netting −688 are not contradicted by this - they were taken under a
1,800s hold, at a horizon [horizon.md](horizon.md) shows carries nothing.

**The costs are London-session.** Measured around 08:45 UTC, which is the
cheapest hour for FX. [catalogue.md](catalogue.md) took the same measurement at
21:00 UTC and got much worse numbers - eurusd 0.825v then against 0.923v now is
close, but the thin-hour readings for the crosses were far higher. The
synthetics are unaffected: they run 24/7 at a stable spread.

**Costs move between runs.** `eurusd` read +0.061 on one pass and −0.012 on
the next, because the spread moved from 0.923v to 0.996v in the minutes
between. Every FX row within about 0.1v of zero should be read as "too close to
call", not as a sign.

## What follows

The choice in [horizon.md](horizon.md) - shorten the hold or give up - was
wrong in a useful way. There is a real edge at five to thirty minutes, it
survives the spread on about a dozen instruments, and it is largest on the two
cheapest liquid things in the book.

What that argues for, in order:

1. **A hold matched to the band**, not `max_hold` of 1,800s. The edge is
   measured over 300-1,800s and the current hold runs to the far end of it.
2. **An instrument list decided by net rather than by gross.** `usdcnh` at
   82.8% is a trap, and nothing currently stops the desk taking it. The list
   that pays is the indices, the energies and the metals - not the FX book,
   where fifteen of nineteen rows are negative or inside the noise.
3. **Re-measure the costs across sessions** before acting on any FX row. The
   indices, energies, gold and the synthetics do not depend on that; the
   crosses do, and they are the rows sitting closest to zero.
