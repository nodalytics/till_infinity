# The convexity bias was never a bug, and its sign is the result

`research/ideas/volatility_convexity.py` carries a check with real authority:
**every barrier geometry's gross expectancy must be zero**, because optional
stopping says so for any bounded stopping time on a martingale, and the harness
credits the actual exit price rather than the stated barrier. Three real
defects were caught by that check - a drift, an overshoot, and a long/short
pairing that only worked where it was not needed.

A residual of `-0.0706` on `(4, 1)` and `+0.0706` on `(1, 4)` survived them and
blocked the line. It is now explained, and the explanation is not a fourth
defect.

## Two of the four rows cannot say anything

This is arithmetic, and it was making the check look four times stronger than
it is.

**`(2, 2)` is identically zero.** The long and the short share the same two
barriers and stop at the same instant, so `long_pay` is exactly `-short_pay`
and their average is `0.0000` whatever the data does. It reads zero to four
places on real instruments, on a martingale and on a clustered walk alike - not
as confirmation but by construction.

**`(1, 4)` is identically minus `(4, 1)`.** The concave long carries `(+1, -4)`,
which is the convex short mirrored, and the concave short carries `(-1, +4)`,
the convex long mirrored. So `gross` on one row is minus `gross` on the other,
exactly, and the measured `-0.0706` against `+0.0706` is that identity rather
than a coincidence worth noting.

**Four rows, one independent number**, and it is `(4, 1)`'s.

## The method is sound, measured against a process that cannot lie

`generated()` runs the identical `trades()` over a walk that is a martingale by
construction, which answers the only question worth asking first: is the fault
in the method or in the data?

| process | geometry | gross | se | **z** | kept |
| --- | --- | ---: | ---: | ---: | ---: |
| constant sigma | convex | +0.0161 | 0.0198 | **+0.81** | 1.000 |
| constant sigma | wide convex | -0.0214 | 0.0412 | **-0.52** | 1.000 |
| clustered sigma | convex | +0.0280 | 0.0260 | **+1.08** | 0.991 |
| clustered sigma | wide convex | -0.0139 | 0.0545 | **-0.25** | 0.959 |
| **real, 8 instruments** | **convex** | **-0.0706** | **0.0231** | **-3.06** | - |

`trades()` reads zero on a martingale, within its own error, on both a constant
volatility and a clustered one. **Volatility clustering does not bias it** -
which was the leading suspect, since the harness demeans in price units while
placing its barriers in local sigma units. `kept` is 1.000 on the constant arm,
so censoring of unresolved trades is ruled out as well.

### The standard error is the thing the check never had

A residual looks like a defect for exactly as long as it takes to compute one
number. `blocked_error` is a moving-block bootstrap over entry order with
blocks longer than `PATIENCE / STRIDE`, so two blocks cannot share a trade.

It is worth saying what a naive overlap correction gets wrong here. Entries are
24 bars apart and patience is 500, so trades look about 21-fold overlapped, and
dividing the sample by 21 gives `se = 0.085` and a reassuring `z = -0.83`. That
is **wrong**: about three quarters of trades stop at the near barrier within a
few dozen bars, so the mean duration is nowhere near the patience window and
the true overlap is slight. The bootstrap measures it instead of assuming it,
and returns `0.0231`.

## So the residual is a property of the market

At `z = -3.06`, a convex geometry - a far target with a near stop - **loses
0.071 sigma gross** on this universe where a martingale loses nothing. The long
leg alone loses 0.108 sigma.

That is a result rather than an obstacle, and its sign is the useful part: it
runs **against** the strategy the convexity line was built to look for. Buying a
distant target and stopping out close is not a free option on a market that
cannot drift; it is a position whose geometry costs 0.07 sigma before the 0.072
sigma round trip is paid.

The consequence for the harness is a change of baseline. **`gross` must read
zero on a martingale and must not be expected to on real data.** The convexity
question is `real minus matched walk`, which is how every other comparison on
this desk is framed, and framing it against zero was the last thing standing
between this file and an answer.

## What is still open

The mechanism behind the `-3.06`. Volatility clustering is ruled out above, and
the two candidates left are both testable with what is already here:

* the **leverage effect** - returns correlate negatively with future volatility
  on metals and crypto, so barriers set from trailing sigma are systematically
  too narrow after a fall and too wide after a rise, which a near stop collects
  differently from a far target;
* **overshoot asymmetry** beyond the measured `0.5` to `0.7` sigma of
  `statespace-barrier-overshoot.md`, which the exit-price credit handles in the
  mean but not necessarily in its dependence on which barrier was hit.

Neither blocks the convexity measurement now that the baseline is the walk.
