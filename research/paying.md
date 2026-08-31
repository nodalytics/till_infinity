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
| gold | 53 | 75.5% | 1.90 | 0.967 | 0.048 | **+0.919** |
| spx500 | 51 | 70.6% | 2.72 | 1.119 | 0.223 | **+0.897** |
| silver | 116 | 71.6% | 1.66 | 0.715 | 0.373 | **+0.342** |
| eth | 59 | 74.6% | 1.84 | 0.903 | 0.597 | **+0.306** |
| volatility_10_index | 61 | 55.7% | 2.94 | 0.337 | 0.144 | +0.193 |
| eurgbp | 125 | 86.4% | 2.00 | 1.456 | 1.328 | +0.128 |
| uk100 | 50 | 84.0% | 1.97 | 1.341 | 1.214 | +0.127 |
| gbpusd | 101 | 70.3% | 1.85 | 0.751 | 0.676 | +0.075 |
| gbpjpy | 106 | 72.6% | 1.84 | 0.834 | 0.769 | +0.065 |
| eurusd | 57 | 77.2% | 1.81 | 0.984 | 0.923 | +0.061 |
| btc | 56 | 57.1% | 2.03 | 0.289 | 0.281 | +0.009 |
| eurjpy | 79 | 70.9% | 1.87 | 0.782 | 0.920 | −0.139 |
| euraud | 128 | 68.8% | 2.07 | 0.775 | 0.944 | −0.169 |
| audusd | 59 | 72.9% | 1.77 | 0.812 | 1.085 | −0.273 |
| usdcad | 87 | 71.3% | 1.65 | 0.701 | 1.170 | −0.469 |
| chfjpy | 106 | 69.8% | 2.02 | 0.801 | 1.381 | −0.580 |
| nzdusd | 70 | 64.3% | 2.55 | 0.728 | 1.770 | −1.042 |
| **usdcnh** | 128 | **82.8%** | 1.75 | 1.151 | **5.886** | **−4.736** |

**11 of 26 clear their own spread**, and the mean across all of them is
**−0.314v**. The losers lose far more than the winners win, because a wide
spread is a certainty and an edge is not.

`usdcnh` is the instructive one: **82.8% accuracy and the worst net on the
board.** A near-five-sixths hit rate cannot pay 5.886 volatility units to
cross. Accuracy without a cost check is not a result, and this row is why the
check exists.

Gold and spx500 are the standouts by an order of magnitude over the next tier,
and for the same reason: a high hit rate on a *large* move at a *small* spread.
Gold at 0.048v is the cheapest real instrument in the book.

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

**Four instruments are still unpriced** - jp225, hk50, us30, wti, aus200,
ger40, us100, brent, fra40 - because no alias in `INSTRUMENTS` matched a symbol
the broker answers to. Several have gross edges above 1.0v, so the positive
list is incomplete rather than complete.

## What follows

The choice in [horizon.md](horizon.md) - shorten the hold or give up - was
wrong in a useful way. There is a real edge at five to thirty minutes, it
survives the spread on about a dozen instruments, and it is largest on the two
cheapest liquid things in the book.

What that argues for, in order:

1. **A hold matched to the band**, not `max_hold` of 1,800s. The edge is
   measured over 300-1,800s and the current hold runs to the far end of it.
2. **An instrument list decided by net rather than by gross.** `usdcnh` at
   82.8% is a trap, and nothing currently stops the desk taking it.
3. **Re-measure the costs across sessions** before acting on the FX rows. Gold,
   spx500, silver and the synthetics do not depend on that; the crosses do.
