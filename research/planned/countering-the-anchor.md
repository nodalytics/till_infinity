# Countering the anchor

Status: **not built, not measured.** Nothing here exists in the code.

The proposal: when a daily-or-higher signal fires, open the *opposite* side -
scalping the pullback back toward the price the daily call would have entered
at, rather than riding the daily call itself.

The reasoning is that a daily buy is a statement about where price is going
over days, and says nothing about the next hour. Price rarely leaves in a
straight line; the counter-move to the anchor's own entry is a shorter, denser
trade than the anchor, and it has a natural target that does not have to be
guessed - the anchor's entry price.

## Why this is not the same as `inverse`

`inverse` already exists and is "the same call, taken the other way. A control,
not a conviction." It inverts everything, on every timeframe, and it is a null
baseline rather than a thesis.

This is narrower in three ways, and the difference is the whole idea:

- It fires **only** on daily and above, where the horizon mismatch between the
  signal and a scalp is largest.
- It has a **defined target** - the anchor's entry - rather than an inverted
  one. That makes the reward leg a measured distance rather than a mirror of a
  stop.
- It is a **scalp against a position-scale signal**, so it should be sized and
  held as a scalp regardless of what the anchor's own strategy would do.

`inverse`'s record is therefore not evidence for or against this, and should
not be read as such.

## What has to be answered

1. **Does the pullback happen, and how far?** Of daily+ calls, what fraction
   retrace to the entry price before continuing, and what is the distribution
   of the maximum adverse excursion *for the counter-trade* - which is the
   anchor's move going the way it was called. That number is the stop.
2. **How long does it take?** If the median retrace takes eleven hours, this is
   not a scalp and the 45-minute ceiling makes it untradeable.
3. **What happens when the anchor is right immediately?** The tail risk sits
   entirely here: a daily buy that never looks back is a short held into a
   trend. The stop has to be sized for that case and the measurement has to
   report it separately rather than averaging it away.

## Where the data already is

`Forward` records the signed return after a touch at fixed horizons, and the
levels book carries the interval a call was published on. The retrace question
is answerable against stored history for daily and weekly levels without
writing any new instrumentation - and daily and weekly are denominated in the
*reference* volatility rather than their own, which any analysis has to account
for before pooling. See `structures/reactions.py`.

## What would falsify it

- The retrace to entry happens in fewer than half of daily+ calls.
- The median time to retrace is longer than a scalp can hold.
- Maximum adverse excursion on the counter-trade is wider than the retrace is
  deep, so the stop that survives the trade is larger than the target.
