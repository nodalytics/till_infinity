# How much room a trade actually needs — measured 2026-09-04

Every stop in this system is placed from a rule: beyond the level, past the
origin's far edge, a multiple of volatility. None of it was placed from a
measurement of how far price goes against a trade that later wins, because that
number did not exist — `adverse_r` read exactly 0.0 on all 188 closes until the
`_reconcile` fix. It exists now.

The planned version of this document is superseded; the questions it set are
answered below in its order.

## The population, and the half that had to be thrown away

165 closed trades carry both `adverse_r` and `r_multiple`. **86 of them read
0.0 on both extremes, and those are missing data rather than readings of
zero** — a ticket `_mark_best` never saw is indistinguishable from a trade that
never moved.

The split is entirely temporal, which is what makes it safe to discard:

| | n | first close | last close |
|---|---|---|---|
| tracked | 79 | 2026-09-02 19:45 | 2026-09-04 18:54 |
| untracked | 86 | 2026-08-30 22:05 | **2026-09-03 07:16** |

Not one trade after 2026-09-03 07:16 is untracked. So this is the residue of
the bug [giveback.md](giveback.md) records — the extremes discarded on the line
above the code that reads them — and not evidence of an ongoing failure. Every
number below is from the 71 closes after that boundary, where tracking is
complete.

**Worth stating because I got it wrong first.** Split by instrument, tracked
and untracked appear in both columns for every symbol — Boom 500 is 6 and 15,
Wall Street 30 is 2 and 10. That looks like a live per-ticket fault and is not
one; it is two eras of the same instrument. An instrument breakdown of a
quantity that changed meaning halfway through the sample will show a
"difference between instruments" that is a difference between dates.

## 1. Winners barely use their stop

In units of each trade's own risk, over the 71 fully-tracked closes:

| | median | p75 | p90 | max |
|---|---|---|---|---|
| winners (27) | 0.059 | 0.197 | 0.333 | 0.883 |
| losers (44) | 0.228 | 0.808 | 1.267 | 1.434 |

**Nine winners in ten never went more than a third of the way to their stop.**
The planned document set the test in advance: *"If p90 is 0.6, stops at 1.0R
are wider than they need to be and the losses are coming from somewhere else.
If p90 is 0.95, the stop is sitting exactly where winners live."* At 0.333 the
first branch is not merely met, it is beaten by half.

The two distributions also separate — winners' p90 sits below losers' p75 —
which means adverse excursion is discriminating and not just noise around a
common mean.

## 2. Per instrument: not yet askable

Split by symbol, the largest winner group is five trades and most are three.
Nothing in that table survives its own error bars, and the gold question the
planned document wanted answered — 9 of 9 stopped trades reaching target
afterwards — has **two** tracked gold winners behind it. Left open rather than
reported.

## 3. What a tighter stop would have done

Computable from the two distributions without a replay, which is what the
planned document argued. A trade whose adverse excursion exceeded a candidate
stop `w` is capped at `-w`; every other trade keeps the outcome it actually
had.

```
  stop    winners kept   losers capped   total R    vs now
  0.2R    21 of 27        29            -5.20    +6.64
  0.3R    23 of 27        24            -5.92    +5.92
  0.4R    24 of 27        20            -6.96    +4.88
  0.5R    24 of 27        19            -8.89    +2.94
  0.6R    26 of 27        15            -8.04    +3.80
  0.8R    26 of 27        13           -10.49    +1.34
  1.0R    27 of 27        10           -11.60    +0.24   <- the book as it is
```

**Every width tested beats the current one**, by +1.34R to +6.64R over 71
trades. The direction is consistent across the whole range, which is the part
worth believing.

**The magnitude is not.** The curve is not monotonic — 0.5R is worse than 0.6R,
which cannot be true of a real relationship and is a plain statement that 27
winners are too few to choose a number from. Anyone reading a recommendation of
"0.2R" out of the top row is reading noise.

## 4. What the book keeps of what it gets

Over trades that ever went into profit, the share of the favourable excursion
actually captured has a **median of 0.698** — and `best_r` reaches a p90 of
2.23 against a median of 0.32. Eight trades reached 1R or better and still
lost, costing **-5.01R** between them, having peaked at a median of 2.54R.

That is an exit problem, not an entry or a stop problem, and it is the same
population [giveback.md](giveback.md) is about. Sections 1 and 3 say the stop is
three times wider than winners need; this section says the trades that go right
are not being held onto. Those are consistent: a book can be losing money with
its stop in the wrong place *and* its exit in the wrong place, and the second is
the larger number here.

## What this does not say

- **Not a recommendation to set the stop at 0.2R.** See section 3.
- **The counterfactual assumes the path to the stop is unchanged**, which is
  true of the stop itself and false of everything downstream: a trade stopped
  at 0.3R never reaches the level that would have turned it, so the winners
  "kept" are an upper bound.
- **It ignores the broker's floor.** `stops_level` is 300 points on Wall Street
  30 against a `min_stop_distance` of 3.0; a stop at 0.2R of a tight entry can
  simply be refused, and a rule that cannot be placed is not a rule.
- **A tighter stop is a larger position** for the same money at risk, so the
  same R costs the same but every point of slippage costs more of it.
  `research/paying.md` prices crossing; nothing here does.

## What would settle it

The measurement that would: hold the entry rule fixed, halve the stop, and let
the shadow record score both. That is what `_also_wanted` already does for
strategies and what [bandits.md](bandits.md) argues is the honest way to rank
anything here — the counterfactual is observable, so it should be observed
rather than modelled.
