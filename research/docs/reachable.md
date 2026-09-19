# Can `origin-swing` ever fire?

It had never appeared in the journal. That is two different problems wearing
one face: a rare setup is worth waiting for, an unreachable one is a strategy
that will never produce evidence either way.

Harness: [`harness/reachable.py`](harness/reachable.py). A funnel over the
signals `trading` actually saw, applying the strategy's conditions in order, so
the first one that empties the set is the one that matters.

## It empties at the first condition

Over 2,123 signals:

| condition | left | share |
| --- | --- | --- |
| every signal seen | 2,123 | 100% |
| **on the 1h entry interval** | **2** | **0.09%** |
| a compulsory timeframe agrees | 0 | 0% |

Nothing else was ever reached. The five conditions after the entry interval -
the bracket, the reach, freshness, the momentum ensemble, both witnesses - have
never been asked a question.

## The constraint is supply, not the strategy

What `trading` sees, against what `structures` resolves:

| interval | signals seen | resolutions |
| --- | --- | --- |
| 1m | 878 | 15,847 |
| 3m | 667 | 4,734 |
| 5m | 459 | 1,682 |
| 15m | 92 | 574 |
| 1h | **2** | 132 |
| 4h | 0 | 116 |

Slow levels exist and resolve - 132 touches on 1h, 116 on 4h - so this is not a
missing timeframe. They are simply rare by construction: a 1h level is touched a
hundred times less often than a 1m one, and fewer of those touches clear
`actionable`.

`INTERVALS = ("1m", "5m")` in `structures/config.py` is about cross-venue
disagreement, not level formation, and `LEVEL_INTERVALS` spans all nine - so
the slow end is built. It just does not produce many calls.

## What this means for the swing contract

Every swing strategy entered on 1h from the day the contract was written. On
this supply that is roughly two chances per two thousand signals, before any of
their own conditions apply - so `swing-level`'s ten decisions and
`origin-swing`'s zero are the expected outcome rather than a surprise.

Three ways out, and they are not equivalent:

1. **Widen the entry to 15m and 1h.** 94 signals rather than 2, a 47-fold
   change, while keeping the slow context and the slow hold. The entry interval
   fixes the stop, and 15m buys a tighter one for the same idea - which is the
   argument `swing-level` already makes for triggering below its anchor.
2. **Leave it.** A swing that fires twice a month is not broken, but it cannot
   be measured this year either, and every parameter on it stays a guess.
3. **Loosen `actionable` on slow timeframes.** The largest change and the one
   with the most ways to be wrong: those gates were measured on fast data.

This measurement does not choose. It says the choice is about supply, and that
tuning anything downstream of the entry interval is tuning something that has
never run.
