# sweep-aware's entries under its own exit and under ride's

`sweep-aware` is the best live performer on this book - **+104.40 over 18
closes** the day the strategy list changed - and it runs the **third-worst exit
policy** in the table `Ride` was built from: target at 1x the modelled push, no
trail, measured at **-0.041R** against ride's **+0.404R** over 31,820 replayed
touches.

That suggested its edge is the entry filter and its exit is a drag. It also
suggested a change that `Ride`'s own docstring warns against: *"the replay
models no spread, which is precisely what sinks fast entries live"* - and
sweep-aware trades from 1m.

Its own record cannot settle it. It has 30 closes and only **14 carry a stop
and a target**; the rest are unattributed. So this replays its **entry rule**
over the published call stream and charges the spread.

## The run

52,395 published calls over 7 days. sweep-aware's rule accepts 40,557 of them -
refusing 2,416 on interval, 9,200 for a stop standing in front of resting
liquidity, and 222 for a level run too often from that side. 30,875 had enough
1m history to walk forward.

| policy | n | mean R | median | win |
| --- | --- | --- | --- | --- |
| its own: target 1x push, no trail | 30,875 | **+0.099** | +0.467 | 61.6% |
| **ride's: trail 0.5v, target out of reach** | 30,875 | **+0.655** | +0.353 | 64.4% |
| its own, spread removed | 30,875 | +0.172 | +0.499 | 62.8% |

**Paired on the same trades: +0.556R mean, +0.500R median, and ride's exit is
better on 70.8% of them.**

The spread is real and does not reverse it: it costs the current policy 0.073R
a trade, which is 42% of what that policy makes.

## The shape of the win is the thing to notice

Ride's exit has a **lower median** (+0.353 against +0.467) and a far higher
mean. It wins by the right tail - fewer trades taken to a big number, more
given back from a good position - which is exactly what a trail does and
exactly what `Ride`'s docstring says about itself: *"the mean rides on the right
tail."*

That is a different risk profile, not only a better number. A book on ride's
exit has a worse typical trade and a better average one, and it needs the
patience to sit through the difference.

## What is not modelled

* **No queue position.** A resting entry is assumed filled the moment price
  touches the level. That flatters both policies and flatters the *current* one
  more, because it is the one that rests - `never filled` was 3.9% of
  sweep-aware's live attempts, and those are excluded here by construction.
* **Spread only where it is known** - 33 feeds, median 1.503bps. Everything
  else is charged zero, which biases the result optimistic on the instruments
  with no spread record.
* **No commission, no funding, no slippage beyond the spread.**
* **A 24-hour hold cap.** Ride's exit holds longer by design, so it commits
  capital for longer, and with `max_positions` at 10 that has an opportunity
  cost this replay cannot see.

## What it supports

Changing sweep-aware's exit is now the best-evidenced single change available
on this book: 30,875 paired observations, spread charged, better on 70.8% of
the same trades, and consistent with a table measured independently on 31,820
touches a month earlier.

**It is still a replay.** The book has watched replayed edges fail on contact -
`thesis-only` most recently - and the honest step is not to swap the exit but
to let `ride` and `sweep-aware` run side by side on the live stream, which the
current strategy list already does: `ride` is first and `sweep-aware` fourth.
The comparison will make itself, on real fills, in a few days.
