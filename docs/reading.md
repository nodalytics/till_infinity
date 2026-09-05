# Reading a signal

Everything published says the same three things: **what happened**, **how
unusual that is for this venue**, and **what it is being compared against**.
The last one is the part most signals leave out.

### Cross-venue signals

```
stale        BINANCE btc      has not moved in 67s while 4 other venues have
spread       FOREXCOM gold    2.4x the group at 2.11bps, wide even for this venue
dislocation  DERIV btc        +3.93bps from consensus, outside anything this venue normally does
```

| | what it means | needs a human? |
|---|---|---|
| `stale` | this venue stopped updating while the others carried on | **yes, now** - a dead feed needs no interpretation |
| `spread` | its spread is wide for the group *and* for its own history | only with context |
| `dislocation` | its price is away from where the others agree | only with context |
| `drift` | the volatility regime itself changed | it invalidates thresholds |

"Wide even for this venue" is doing real work. A venue quoting BTC at 20bps is
not wide; EURUSD at 3bps is. Each venue is scored against its own distribution,
so one number never has to be right for both.

### Level signals

A level is a price the market has turned at before. What it produces looks like:

```
us100 1h  29618   tested   from above 7.6x +1.87v   from below 6.6x -1.52v   strength 0.94
us100 1h  29391   tested   from above 17.3x +1.57v  from below 6.1x -1.71v   strength 0.88
```

Read left to right: the instrument and timeframe, the price, its state, then
**what it did to price arriving from each side** and how much evidence there is.

- **`7.6x`** - effective touches, decayed by age. Ten touches last quarter count
  for less than three this week, and the number already accounts for that.
- **`+1.87v`** - the average push in **volatility units**: `1v` is one typical
  move for that instrument on that timeframe. On gold 5m that is about $0.75;
  on gold weekly, about $52. It is the same number on BTC and EURUSD, which is
  the point.
- **`from above` / `from below`** - kept apart because they are different
  objects. At 29618 price arriving from above gets pushed **up** and arriving
  from below gets pushed **down**: that is a level holding both ways, and an
  average over the two would show roughly nothing.

### When price arrives

```
gold arriving at 4405.5
  · 4405.5  (from above, ~4.2h)  ↑ 59% vs 47% base   push +0.42v
  ! 4401.3  (from above, ~3.2d)  ↑ 80% vs 47% base   push +1.78v
```

**`vs 47% base` is the whole thing.** 59% sounds like an edge until you see the
unconditional rate is 47%; 80% against the same 47% is one. A level whose
probability matches the base rate has told you nothing, and you will see that
rather than a confident-looking number. `!` marks the ones clearing all three
bars - enough evidence, enough separation from the base rate, and a move big
enough to be worth the risk.

`~4.2h` is how long price typically takes to get there, from the distance and
current volatility. Time goes as the **square** of distance, so a level twice as
far away is four times as long, not twice.

### The three things that happen at a level

| | |
|---|---|
| **break** | through, and it stayed through - provisional until it survives |
| **false breakout** | through, then given back. Recorded with the push it *ended* on |
| **back check** | broke, pulled back, held, carried on - the stop is the flipped level |

Told apart because a model with only "held" and "broke" scores a trap as a
break that worked. On the stored history **27 of 70 breakout attempts were
false**.

### What is not claimed

No performance figures, and none until there are enough resolved outcomes to
compute them honestly. The system records every call with the state it was made
from and attaches what followed, so that question becomes answerable - it is
not answerable yet.

Deeper on the machinery behind these: **[structures.md](structures.md)**
for the online models and cross-venue scoring, **[levels.md](levels.md)**
for how a level is found, tracked and scored per approach side.
