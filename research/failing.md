# Where each strategy fails, and how

Measured from the live journal on 2026-09-02. Closes, not positions — partial
profit taking splits one position into several — so `n` here exceeds the entry
count for anything that takes profit in halves.

Two caveats up front. `r_multiple` is only present on the newer outcomes, so
the scale-free columns cover `thesis-only`, `runner` and `fade-to-value` and
nobody else. And five closes worth +44.73 are still `unattributed` — closes the
process never tied back to a decision — so every table below is missing a
little.

## The headline: the calls are not the problem

`inverse` exists to answer exactly this. It takes the same entries, the same
anchors, the same gates and the same stop as `level-scalp`, and trades the
**other side**. If the level model had negative directional skill, inverting it
would print money.

It loses too — −99.86 over 6 closes, −16.64 each, a 33% win rate, worse per
trade than the strategy it inverts.

Both directions losing is not a statement about direction. It is a statement
about everything that is the same in both: the cost to cross, where the stop
goes, and when the trade is given up on. That is where the rest of this
document looks.

## Every strategy, by how it exits

| strategy | entries | closes | net | per close | win |
| --- | ---: | ---: | ---: | ---: | ---: |
| thesis-only | 55 | 79 | −148.35 | **−1.88** | 53% |
| runner | 27 | 28 | −194.87 | −6.96 | 32% |
| snap | 34 | 29 | −210.38 | −7.25 | 28% |
| fade-to-value | 23 | 19 | −159.96 | −8.42 | 37% |
| sweep-aware | 19 | 12 | −122.27 | −10.19 | 25% |
| inverse | 8 | 6 | −99.86 | −16.64 | 33% |
| approach-scalp | 2 | 2 | −35.52 | −17.76 | 0% |
| confluence-scalp | 1 | 1 | −19.92 | −19.92 | 0% |

`thesis-only` is the **best** per trade by a factor of three and the only one
above a 50% win rate. It reads as the worst because it trades three times as
much as anything else and dominates the live feed.

## thesis-only: right more often than not, and paid too little for it

| exit | n | net | mean R |
| --- | ---: | ---: | ---: |
| target | 28 | +402.57 | **+0.66** |
| stop | 20 | −498.19 | **−1.12** |
| hold | 23 | −28.87 | −0.22 |

It wins 28 decisive exits against 20 losing ones — 58.3%. At +0.66R a win and
−1.12R a loss it needs **62.9%** to break even. It is 4.6 points short, and the
23 timed-out holds take another 5R off the top.

**This is a payoff-ratio failure, not an accuracy failure.** The target sits at
the modelled push, which is a *median* estimate, while the stop sits at the
level. That asymmetry is the design. `min_reward_to_risk` is overridden to 0 in
the running plan, so nothing refuses a trade for it — a live example on
2026-09-02 was taken at RR **0.418**, risking 3.35 to make 1.40, on an 83%
stated probability.

Two things would close a 4.6-point gap, and they are cheaper than finding more
accuracy:

* **Stops that cost 1R.** They cost 1.12R. Boom 500 is most of that overshoot
  (see `.secrets/instruments.md`), and removing boom entirely takes
  `thesis-only` from −148.35 to **+5.05 over 66 closes** — breakeven.
* **A reward-to-risk floor.** At −1.00R stops the breakeven win rate falls to
  60.2%, which is still above the 58.3% delivered. Refusing the RR-0.4 tail is
  the other half.

## runner: the tail it was built for never arrives

| exit | n | net | mean R |
| --- | ---: | ---: | ---: |
| hold | 16 | −61.84 | −0.22 |
| stop | 9 | −152.34 | −1.02 |
| target | 1 | +20.01 | +0.57 |

The design is explicit: the target is moved out to three times the modelled
push — near the p90 of what touches actually reach — so that the **trail** ends
the trade and catches the right tail. The replay behind it returned +8.4R
against +1.7R for the same entries closed at a fixed target.

Live, **16 of 26 exits are the clock**. `hold_seconds` is four hours. A tail
that a replay measured over a resolution horizon cannot be harvested in four
hours, so the mechanism the strategy exists for is cut off before it operates,
and what is left is a wide target that rarely fills and a stop that still does.

Its one target exit paid **+0.57R**, not the ~3R the target multiple implies.
That is inconsistent with the design and is the first thing to check: either
the recorded `target` exits are not the moved-out target, or something closes
before it.

Note also `runner`'s stops come back at −1.02R — normal. Its problem is not
execution.

## snap, fade-to-value, sweep-aware: too few decisive exits to separate

`snap` is the worst of the high-volume set at −7.25 per close and a 28% win
rate: 11 stops for −260.89 against 4 targets for +79.95. `fade-to-value` loses
−155.16 across six stops — −25.86 each, the largest average stop on the book.
`sweep-aware` has the healthiest shape of the three (3 stops at −33 each
against 2 targets at +45) but seven of its twelve closes carry no exit kind at
all, so its table is more gap than data.

For all three the worst instrument is the same: **XAUUSD**, which is −125 for
`sweep-aware`, −76 for `snap`, −39 for `fade-to-value`, −46 for `inverse`. Gold
is the book's largest hole at −297.09 over 30 closes and has been since it was
first measured.

## The two that never trade, and they fail differently

| strategy | refusals | the top four |
| --- | ---: | --- |
| origin-swing | 608 | interval 397, **momentum 120**, not_at_origin 69, stale_origin 17 |
| swing-level | 466 | **interval 404**, chase 32, unanchored 15, stops_level 6 |

**`swing-level` fails upstream.** 87% of its refusals are `interval`: it
triggers only on 1h and above, and most level calls form faster. It is not
being rejected on its merits, it is rarely being offered anything it can look
at. It does place orders — on 2026-09-02 at 09:04 it rested `sell usdcad 0.2
lots @ 1.3941`, ticket #5763662208, left with the broker — they just have never
filled.

**`origin-swing` fails on its own confirmations.** Past the interval filter,
`momentum` refuses 120 and `not_at_origin` 69. It is the only strategy with
`needs_both_witnesses`: the 4h rejection candle *and* the sub-hour momentum
ensemble must agree. That conjunction is the design — a swing can afford to
wait, and an origin merely touched is not an origin that rejected — and it is
also why nothing gets through. Narrowing its context to 4h/1d on 2026-09-01
made it stricter still.

`council` and `momentum-scalp` have also never traded.

## What this says to do next, in order

1. **Stops that cost what they say.** 1.12R on `thesis-only` is most of its
   gap, and boom is most of the 1.12. `by_slippage` now sizes boom 500 at 0.8;
   the same measurement should be re-taken for the rest of the family.
2. **A reward-to-risk floor.** Nothing currently refuses an RR-0.4 trade.
   Setting `min_reward_to_risk` is a one-line change with a directly computable
   effect on the breakeven win rate.
3. **Let `runner` run.** Four hours cannot harvest a tail. Raise its hold, or
   accept it is a fixed-target strategy with an unusually wide target.
4. **Gold.** Every scalp's worst instrument, −297.09 overall, and separately
   known to have stops so tight that 62% of its stopped trades reached target
   afterwards against 26% book-wide.
5. **Attribute the last five closes.** +44.73 sitting outside every table.
