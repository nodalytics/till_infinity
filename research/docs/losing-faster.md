# Losing faster on 2026-10-08, and what actually changed

Asked on 2026-10-09 as "we have been losing terribly in the last 24 to 48
hours". The answer is that **the per-trade edge did not change at all** - the
desk simply did twice as much of it - and that the losing half of the book is
separable by entry timeframe.

Read from the journal on production (`trading` outcomes joined to the
`trading` decisions that produced them, by `parent`), 12 days, 473 closed
positions. **Scored in money rather than R**, which matters here: one
2026-10-02 record carries an `r_multiple` of about 2,380 and distorts every
R-weighted total in the window. Money is the broker's own number and has no
such hole.

## The edge did not move; the volume did

|  | trades/day | per trade | per day |
|---|---:|---:|---:|
| prior 7 days | 35.1 | -0.0973R | -3.42R |
| last 48 hours | **76.0** | **-0.0869R** | **-6.60R** |

A permutation test on the difference in per-trade R returns **p = 0.53**: the
last 48 hours are indistinguishable from the week before them, and if anything
very slightly better. The daily bleed roughly doubled because the trade count
roughly doubled - 2.16x - and for no other reason.

What that rules out is the first thing worth ruling out. No model degraded, no
feed broke, nothing started mispricing on 2026-10-08. A long-standing negative
edge was simply run at twice the rate.

Money per day, for scale:

| day | closes | money |
|---|---:|---:|
| 10-05 | 49 | +62.04 |
| 10-06 | 91 | +17.95 |
| 10-07 | 87 | +65.56 |
| **10-08** | 67 | **-123.18** |
| **10-09** (part) | 18 | **-92.54** |

## The losing half is separable by entry timeframe

| interval | closes | money | per trade |
|---|---:|---:|---:|
| 3m | 130 | **-94.92** | -0.73 |
| 1m | 138 | **-89.88** | -0.65 |
| 30m | 25 | -5.77 | -0.23 |
| 15m | 43 | +22.05 | +0.51 |
| 5m | 137 | **+117.91** | **+0.86** |

It is monotonic from 1m to 5m and it has a mechanism: a roughly fixed
per-trade cost - spread, plus a stop that fills past itself - against a stop
distance that shrinks with the timeframe. The same cost is a larger fraction of
a smaller stop.

Splitting there:

| | closes | money |
|---|---:|---:|
| as traded | 473 | **-50.61** |
| drop 1m and 3m | 205 | **+134.19** |
| drop 1m, 3m and `inverse` | 178 | **+146.28** |

And on the two days in question, where it matters most:

| day | as traded | 5m and above, no `inverse` |
|---|---:|---:|
| 10-07 | +65.56 | +46.71 |
| **10-08** | **-123.18** | **+7.47** |
| **10-09** | **-92.54** | **+0.61** |

The cut gives up real upside - 09-28 goes +38.42 to -3.82 - and this is an
**in-sample** split, so the magnitudes are optimistic. What is not in-sample
flattery is the sign and the consistency: 1m and 3m lose on 268 of 473 closes
across twelve days, and the mechanism predicts it.

## Stops fill past themselves, steadily

Mean realised stop over the last 48 hours is **-1.082R** rather than -1.000,
and it has sat between -1.03R and -1.10R every day for nine days. That is
**5.43R of the window's 13.21R loss** from slippage alone. It is a constant
tax, not a new fault, and it is the same fixed cost the timeframe table is
measuring from the other side.

Decided trades - those that reached a stop or a target, ignoring time exits -
need **36.5%** targets to break even at the observed 1.886R win against 1.082R
loss. They got **30.5%**.

## The control says the direction is not the problem

`inverse` takes the same call the other way. It is a control, not a conviction,
and it exists to separate "the model points the wrong way" from "the model
points the right way and the execution eats it". Since it began on 2026-10-05:

| | closes | per trade |
|---|---:|---:|
| `inverse` | 58 | -0.102R |
| everything else | 260 | -0.071R |

**Both lose.** Taking the exact same signals in the opposite direction does not
make money either, which is what it looks like when the cost rather than the
direction is what is wrong. It agrees with the timeframe table and with the
stop overshoot, and all three say the same thing.

In money `inverse` is **+54.90** over the twelve days against -5.93R, because
its gains sit at 1m where the positions are small. Inside the 5m-and-above book
it is **-12.09**, so it comes off with the fast timeframes rather than instead
of them.

## The edge and probability gates do not predict money

Both were live at `0.0`, and raising them was the obvious lever. It does not
survive contact with the record:

| decision field | Spearman rho vs money | permutation p |
|---|---:|---:|
| `edge` | +0.0220 | 0.628 |
| `probability` | +0.0569 | 0.218 |
| `strength` | +0.0121 | 0.800 |
| `reward_to_risk` | -0.0787 | 0.085 |

None of them ranks outcomes. The deciles say it more plainly than the
correlation does - `probability` 0.8027-0.8211 is **-84.21** and the decile
immediately above it, 0.8211-0.8328, is **+101.70**.

**The counterfactuals are the trap, and they are worth writing down because
they look so good.** Cutting at `probability >= 0.85` keeps 43% of the trades
and returns +66.05; `edge >= 0.3` keeps 23% and returns +67.76. Both are what
you get by discarding half a sample on a variable with no relationship to it:
the total moves a long way and means nothing. A threshold there would cut the
profitable 5m flow at the same rate as everything else, for a gain that is
indistinguishable from having cut at random.

The timeframe split is a different kind of claim. It is not the best cut found
by searching cuts - it is one variable, chosen because a fixed cost against a
shrinking stop predicts exactly this shape, and then measured.

## What was changed

On production, 2026-10-09:

    TRADING_INTERVALS=5m,15m,30m,1h,2h,4h,1d,1w      (was 1m,3m,5m,...)
    TRADING_STRATEGIES=...                            (`inverse` removed)

`TRADING_INTERVALS` narrows every strategy by intersection with its own
`entries` (`strategies/strategy.py`), so no strategy needed editing and none
can be widened past the data its reasoning was built on. Removing a name from
`TRADING_STRATEGIES` is safe for attribution because `MAGIC_ORDER` is a fixed
append-only table rather than a view of the configured list - which is the
whole reason it is written that way.

`TRADING_MIN_EDGE` and `TRADING_MIN_PROBABILITY` were **left at 0.0**, on the
evidence above.

## What this does not explain

The per-trade edge is negative at every timeframe on a long enough window; 5m
being positive over twelve days is not the same as 5m having an edge. This
change removes the half of the book that is reliably worse, which is a
different and smaller claim than fixing it. The costs that the timeframe table
and the stop overshoot are both measuring are still there at 5m - they are
just a smaller fraction of a wider stop.

## The warm cap does not bind, measured 2026-10-09

> **Void, 2026-10-10.** This whole section measured a constant that was not in
> the running process. The image carried the new source at `/app/till_infinity`
> and an old installed package in its venv - `uv sync --no-editable` had
> reinstalled a wheel cached from an older tree - and the venv is what Python
> imports. `SEED_NEW_BARS` never shipped, so a bar count that did not change is
> what a missing constant looks like rather than a cap that does not bind. The
> conclusion below is **untested**, not refuted. See
> [`sixteen-days-without-a-save.md`](sixteen-days-without-a-save.md).


A change shipped that afternoon halved the rows the warm reads per
`(feed, interval)` - `SEED_NEW_BARS`, 500 against `SEED_BARS`' 1000 - on the
reasoning that `bars * 8 / 12` venue series lands on the 333 that
`DEFAULT_RETAIN_BARS` names as the seed's requirement.

**It changed almost nothing, and the measurement is unambiguous:**

| | bars replayed | warm duration |
| --- | ---: | ---: |
| cap 8,000 rows per series | 749,590 | 84 min |
| cap 4,000 rows per series | **747,871** | 56 min |

**0.2%.** 747,871 bars over twenty feeds and about ten intervals is roughly
3,740 rows per `(feed, interval)` - below both caps. The store never held
enough bars for either limit to apply, so lowering it could not help.

The arithmetic behind the change was correct and about an inactive mechanism.
**The error was validating the number without checking whether the limit was
ever reached**, which is the same mistake as reading a constant-zero feature as
a judged one, made in production code rather than in a study.

**The duration fell from 84 minutes to 56 and that is not attributable to the
change.** The 84-minute warm ran on a box recovering from an OOM kill with a
prune competing for I/O; the 56-minute one ran on a quiet box. Same work,
different conditions, and the bar count is the controlled quantity.

### Where the time actually goes

747,871 bars in 56 minutes is about **220 bars a second through
`observe_bar`**. The cost is per row *replayed*, not per row *read*, so a read
cap was never going to touch it. Three things would:

* **replay fewer intervals.** The warm touches from `1w` down to `1m`; whether
  a weekly series needs seeding from bars at all is a question nobody has
  asked.
* **make `observe_bar` cheaper on the seed path**, where most of what it does -
  calls, signals, journalling - is discarded.
* **do not re-warm these feeds.** The same twenty warm on every restart
  although `_series` is pickled and `__setstate__` restores it, and `spx500`
  appears in both the restored list and the warm list - so its deepest series
  comes back with fewer than `WARM_MIN_BARS` closes. **Answering that removes
  the warm rather than trimming it**, and it is the only one of the three worth
  doing first.

**Answered the same day, and not where this section looks for it.** `spx500` was
not thin in the restored state, it was **absent**: `structures` had not written
a state file since 2026-09-23, because a `nan` feature had grown a linked list
inside the volatility tree that `pickle` could not recurse over. Every restart
restored a nineteen-day-old file holding 31 feeds against a 51-symbol universe,
and the twenty missing ones re-warmed by definition. The warm was a symptom
throughout - see [`sixteen-days-without-a-save.md`](sixteen-days-without-a-save.md).
