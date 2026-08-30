# What each level made or lost

```bash
uv run till-infinity journal levels              # every level, best and worst
uv run till-infinity journal levels --min-trades 2
```

## A level's price is not its name

This looks like a reporting feature and started as a bug.

Asked which levels had been profitable, the record answered: **117 levels, 119
trades, one traded more than once.** Read literally that says the desk almost
never trades the same price twice, which would be a striking fact about the
strategy. It is not a fact about anything. It is what happens when you group a
number that moves.

A `Level` holds its price in a Kalman filter, which updates every time the level
learns something - a touch resolving folds that touch's price into the estimate.
So a level traded on Monday and again on Wednesday is journalled at two
different prices, and grouping by price turns one level with two trades into two
levels with one trade each. Two rows in that first report read `gold 4602.05 5m`
and `gold 4602.35 5m`, thirty cents apart on gold, which is well inside a single
volatility unit. One level, counted twice, with its record split down the middle.

## The identity

`Level.id` is minted once at formation and carried through everything that moves
a level:

* **`merge`** - a rediscovered level is evidence about an old one, not a new
  one, so the surviving level keeps its own id and absorbs the other's history.
  That is the same rule merge already applied to touches.
* **`dedupe`** - two levels whose zones converge fold together; the
  better-evidenced one survives, with its name.
* **the filter** - the price moves, the id does not. That is the whole point.

It reaches the signal (`Signal.level_id`), the intent (`Intent.level_id`) and
every journalled decision and outcome, so a closed trade can be added up against
the level that produced it.

### It is not `origin`

`Level.origin` says *which formations found this level* - `pip+run+origin`.
`Level.id` says *which level this is*. They answer different questions and
conflating them would lose one: two levels drawn the same way are not the same
level, and one level found by three passes is not three levels.

## What the ledger reports

Per level: net, trade count, wins, the instrument, the timeframe, the price as
it last stood, and how its trades ended. Sorted by what they made.

Two totals matter more than the ranking:

* **how many levels carry an id** - trades taken before this existed do not, and
  they are grouped under `unnamed` rather than folded into one enormous level or
  silently dropped. The first would be a lie and the second would make the
  totals not add up.
* **how many were traded more than once** - because that is the number that was
  wrong, and it is the one that says whether a level's record is a record or an
  anecdote. A level with one trade has no PnL worth reading; it has a trade.

## What it cannot tell you yet

Whether a level was *good*. 119 trades across 117 prices is one observation
each, and a ranking of those is a ranking of individual trades wearing a price
as a label. Level quality has to come from the touch record - 15,507 resolutions
and counting - where the sample is three orders of magnitude larger and does not
depend on the desk having chosen to trade.

What this answers is the narrower question the touch record cannot: of the
levels we *acted* on, which ones cost money. That is a question about the
strategy rather than about the level, and it needed an identity before it could
be asked at all.
