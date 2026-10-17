# Seventeen kinds of bias, and the only one that reproduces is a veto

**2026-10-17. `research/ideas/setups.py`.** 1h entries at directional-change
pivots, structural stops at the invalidating swing, rewards 1:1 to 1:5, a
120-bar hold, cost 0.05 of the stop. Six classes, twenty instruments each, each
series split in half.

A **bias** determines one thing: the **side**. Not the entry price, not the
size, not the stop, not whether to trade. So a bias is aimed squarely at the
one quantity this desk has measured closed - direction is a coin in every test,
Kronos reads 0.50 across 112,429 rows, a GRU's held-out R2 is -0.0026 and an
ESN's direction AUC is 0.4981 to 0.5295. This page is what happens when
seventeen of them are asked the same question with the same null.

## The null is the flip, and two earlier nulls were wrong

**Zero is not the null.** A structural stop sits at the swing price has only
just left, so it is nearer recent action than its mirror - enough to make
`bos 4h` and its flip differ by **0.17** on a generated walk with no market in
the data.

**The walk is not the null either.** Scored against it, a rule *and* its mirror
both came out ahead - `slope 4h` at +0.11 and its flip at +0.07 - because the
walk is unmatched on **resolution**: its win rate at 1:1 reads 0.363 against a
geometric 0.500, so it resolves far less often than real bars and the two
populations are not comparable.

**The flip on the same bars is matched on everything.** Same entries, same
geometry, only the side reversed. Every number below is `real - flip`.

## Two calibration arms, both reading null

| arm | half 0 | half 1 |
| --- | ---: | ---: |
| `structure` - an entry with **no bias at all** | -0.0015, 2/6 | -0.0073, 2/6 |
| `session` - hour of day, a **known** null | +0.0036, 3/6 | -0.0132, 2/6 |

`seasonality-belongs-on-q` is explicit that the intraday pattern is in
volatility and drives `Q` rather than `R`, so `session` has to read nothing. It
is here because a panel with no known-null arm cannot tell a dead detector from
a dead effect, and after ten rules had been added this one needed the check.

## The geometry costs 0.13R before any bias

`structure` reads **-0.127** and **-0.131** a trade. That is the conservative
settlement: overshoot charged on every loss, a bar reaching both barriers
charged against the trade, and 0.05R of cost. Every bias is then trying to
recover 0.13R.

## Null

| rule | half 0 | half 1 | classes + |
| --- | ---: | ---: | --- |
| **ma200 4h** | -0.0135 | -0.0061 | 2/6, 3/6 |
| skew 4h | +0.0006 | -0.0011 | 3/6, 3/6 |
| slope 4h | -0.0007 | -0.0031 | 3/6, 3/6 |
| **fvg 4h** | -0.0091 | -0.0085 | 2/6, 2/6 |
| engulf 4h | -0.0072 | -0.0107 | 3/6, 1/6 |
| gap 4h | -0.0007 | -0.0128 | 3/6, 0/6 |
| range 4h | +0.0004 | -0.0206 | 3/6, 2/6 |
| wick 4h | -0.0101 | -0.0174 | 1/6, 0/6 |
| streak 4h | -0.0317 | -0.0166 | 2/6, 1/6 |
| sweep | -0.0097 | -0.0105 | 1/6, 1/6 |
| agree | -0.0053 | -0.0092 | 2/6, 1/6 |

**`ma200 4h` is the one to notice.** Price above or below its own 200-period
average is the most widely used bias in retail trading, and `magnets.md` had
already measured that average as a *magnet* - does price get drawn back to it -
and found it indistinguishable from the previous bar's high. *Above it means
up* is a **different claim**, and it needed its own test. It reads -0.014 and
-0.006 at 2 and 3 of six classes.

## Regimes - a sign flip between the halves

| rule | half 0 | half 1 |
| --- | ---: | ---: |
| displace 4h | **-0.0280** (0/6) | **+0.0195** (6/6) |
| slope+displace 4h | -0.0286 (0/6) | +0.0256 (5/6) |
| slope 1d | -0.0092 (1/6) | +0.0146 (4/6) |

A rule that is 0 of 6 classes in one half and 6 of 6 in the other has found a
regime, not an edge. `displace 4h` - the two-push displacement origin - is the
cleanest instance, and it was the rule most expected to work.

## The only thing that reproduces, and it is an inversion

| rule | R gap | half 0 | half 1 | best side, net of cost |
| --- | ---: | ---: | ---: | ---: |
| bos 4h | -0.20 | 1/6 | 0/6 | -0.053 / -0.034 |
| bos 4h+loud | -0.32 | 0/6 | 1/6 | +0.014 / -0.010 |
| engulf+bos 4h | -0.27 | 1/6 | 1/6 | **-0.027 / -0.010** |

**Trading *with* a 4h break of structure loses reliably.** -0.246 and -0.249 a
trade against -0.053 and -0.034 for fading the same break: a 0.20R gap holding
in both halves and in 11 of 12 class-halves. The dispersion gate widens it to
0.32R, which is the gate correctly finding when a bad bias hurts most, and the
strongest version is an engulfing **agreeing** with the break.

**And it is not a trade.** 35 of 36 `best net` figures are negative; the single
positive, +0.014, reads -0.010 in the other half. The best side anywhere is
-0.010R. So the directional information is real, worth about 0.08R of the
0.13R the geometry costs, and 0.05R short.

That makes it a **veto**: `signalling` should refuse the with-break side. A veto
is the only useful shape a directional finding can take when the base rate is a
coin, because being wrong about it costs nothing - the trade simply is not
taken.

## A +0.50R result that was a lookahead, and why it was caught

`fvg 4h` first read a win gap of **+0.31** and **+0.50R a trade**, in both
halves and every class. Nothing else in the panel was within 0.3R, and that is
what prompted a check rather than a celebration: **a panel where everything is
null is a panel where one large number is a bug.**

`drawing.gaps.gaps()` ends with

    top, bottom = _remaining(highs, lows, i + 2, low, high, open_share)
    if top - bottom < (high - low) * open_share:
        continue

so it scans **forward** and emits a gap only if it is **still unfilled**. That
is right for its own job - drawing the gaps open *now* - and a lookahead inside
a loop over history, where "now" is the end of the series. The rule was being
handed *a strong move happened **and price never came back to fill it***, and
the second half is the future: a gap that stays unfilled is one where price
kept going.

Replaced with the bare three-bar condition, knowable at `i + 1` and filtered on
nothing later, it reads **-0.0091 and -0.0085** - the baseline. The **void** and
**volume imbalance** kinds were dropped rather than patched, because neither has
a causal definition: both are defined by what later price did.

## What this says about where to look

A bias determines **side**, and side is the closed half. Every quantity this
desk can forecast answers a different question - how far (R2 to 0.85), how wide
at a stated breach rate (1.02 to 1.10 calibrated), how soon (C-index 0.63 to
0.69) - and none of them needs a bias at all. They feed the stop, the target's
reachability and the size.

So the useful reading of this page is not that seventeen rules failed. It is
that the category was pointed at the dead half, and the one survivor is useful
precisely because it refuses a side rather than selecting one.
