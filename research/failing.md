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
2. ~~**A reward-to-risk floor.**~~ **Withdrawn the same day — the data says
   the opposite.** Cut by reward-to-risk at entry, the book's only positive
   bucket is RR **0.5-1.0** at +1.30 a close and a 62% win rate, and the worst
   by a distance is RR **1.5+** at -12.66 a close, a 21% win rate and t=-4.63
   over 57 closes. A floor pushes trades *into* the losing bucket. The
   mechanism is visible in the win rates: a high RR is a distant target, a
   distant target is rarely reached, and 21% x 1.5R loses to 62% x 0.75R. If
   anything the evidence argues for a **ceiling**, or for distrusting the
   modelled push at distance. See "What actually wins" below.
3. **Let `runner` run.** Four hours cannot harvest a tail. Raise its hold, or
   accept it is a fixed-target strategy with an unusually wide target.
4. **Gold.** Every scalp's worst instrument, −297.09 overall, and separately
   known to have stops so tight that 62% of its stopped trades reached target
   afterwards against 26% book-wide.
5. **Attribute the last five closes.** +44.73 sitting outside every table.

## What actually wins — 2026-09-02

182 closes, cut seven ways. Slicing a sample this size many ways and reporting
the best slice is how noise gets promoted to strategy, so: **none of the
positive cells below is significant.** The trustworthy results here are the
negative ones, because they are large effects with real n. What the book has is
not a proven winning combination; it is several proven losing ones.

**Discard the exit-kind cut first.** "Target exits win 100% of the time,
t=+7.20" is a tautology - a target exit *is* a win - in the same family as the
sub-60-second rejection that resolves upward 100% of the time. It measures the
definition, not the market.

### The stated probability is inverted at the top

| probability | n | per close | win | t |
| --- | ---: | ---: | ---: | ---: |
| 0.8-0.9 | 63 | -1.48 | 48% | -0.53 |
| 0.7-0.8 | 33 | -9.10 | 36% | -3.02 |
| **0.9-1.01** | 30 | **-12.27** | **27%** | **-3.67** |

The most confident calls are the worst. Trades the model rates above 0.9 win
27% of the time. That is not a small miscalibration, and at t=-3.67 over 30
closes it is not obviously noise either.

### So is reward-to-risk

| reward-to-risk | n | per close | win | t |
| --- | ---: | ---: | ---: | ---: |
| **0.5-1.0** | 37 | **+1.30** | **62%** | +0.49 |
| 0-0.5 | 50 | -2.49 | 52% | -1.23 |
| 1.0-1.5 | 38 | -4.24 | 32% | -1.11 |
| **1.5+** | 57 | **-12.66** | **21%** | **-4.63** |

### The rest

| cut | best | worst |
| --- | --- | --- |
| family | volatility +1.73 (71% win, t=+0.44) | boom -11.87 (14%), metals/oil -8.51 (t=-3.04) |
| interval | 15m -3.06 | 1m -8.09 (t=-2.27), 5m -5.87 |
| entry | parked -3.32, 50% win | market -5.51, 39% win |
| side | sell -4.82 | buy -5.78 |

Faster is worse and the ordering is nearly monotone, which supports the move
of 15m and 30m into scalp territory. Parked entries beat market entries per
trade and on win rate, on 20 closes against 162 - the first evidence in favour
of resting entries, and far too little of it.

**Side says nothing** (-4.82 against -5.78), which is the same message
`inverse` gives: this book is not losing because it picks the wrong direction.

### The combination, stated honestly

The best cell available is `thesis-only`, on volatility indices or indices,
entered on 15m, parked, at RR 0.5-1.0 and a stated probability of 0.8-0.9,
excluding boom. Every one of those is an in-sample selection on 182 closes and
none is individually significant.

What is defensible is the negative: **boom, metals/oil, RR above 1.5, stated
probability above 0.9, and 1m entries all lose with real n behind them.**
Removing losers is the move that survives this sample size. Finding a winner
does not.

## Separating the probability inversion from its geometry — 2026-09-02

"Calls rated above 0.9 win 27%" has two candidate causes: the probability is
simply wrong (calibration), or high-probability calls systematically carry a
distant target and RR 1.5+ is what loses (confounding). 130 closes carry both
numbers.

**They are entangled, and that half is confirmed.**

| stated probability | n | mean RR | median RR | share at RR 1.5+ |
| --- | ---: | ---: | ---: | ---: |
| 0.7-0.8 | 33 | 1.35 | 1.13 | 36% |
| 0.8-0.9 | 63 | 1.16 | 0.91 | 29% |
| **0.9+** | 30 | **1.59** | **1.51** | **53%** |

A call the model is most sure of gets a target half again as far away, and
more than half of those trades sit in the worst RR bucket on the book. That is
not a coincidence of sampling - `probability` and `expected_push_vol` are
driven by the same underlying strength estimate, so confidence and target
distance move together by construction. When the estimate is wrong, the
direction call and the geometry fail in the same trade.

**But the geometry does not explain it away.** Holding RR fixed, probability
still fails to order outcomes - there is no RR band in which the 0.9+ group is
the best group:

| RR band | p 0.7-0.8 | p 0.8-0.9 | p 0.9+ |
| --- | ---: | ---: | ---: |
| <0.5 | 71% [7] | 47% [19] | 75% [4] |
| 0.5-1.0 | 75% [8] | 62% [13] | 50% [4] |
| 1.0-1.5 | 0% [6] | 54% [13] | 17% [6] |
| 1.5+ | 8% [12] | 33% [18] | 12% [16] |

Win rate, n in brackets. The cells are thin and only the RR-1.5+ row carries
real weight, but in three of four bands the 0.8-0.9 group beats the 0.9+ one.

**The calibration table is the one to trust**, at n=130 across four bands:

| band | n | said | won | reached target | stopped |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.7-0.8 | 33 | 77% | 36% | 24% | 30% |
| 0.8-0.9 | 63 | 85% | 48% | 14% | 24% |
| **0.9+** | 30 | **93%** | **27%** | **10%** | **53%** |

Said 93%, won 27%, and **stopped out 53% of the time** - more than double the
next band. Higher confidence also means a *lower* target-hit rate, 10% against
24%, which is the distance showing through.

### The honest verdict: one mechanism, not two

It is not calibration *or* geometry. Confidence and target distance come from
the same estimate, so a confident call buys a further target and a stop that
is proportionally nearer the noise. The trade then loses in the way the table
shows: rarely reaching a target it was never close to, and stopping out at
twice the rate.

**One caveat that matters.** `probability` is the model's estimate that the
*level holds*, not that the *trade wins*. Those are different questions, and
comparing 93% to 27% is not a calibration test in the strict sense. A level
can hold while an excursion takes the stop first - which is exactly what gold
does, where 62% of stopped trades reached target *after* being stopped against
26% book-wide.

**So the deciding measurement has not been taken.** On the 0.9+ trades that
stopped out, did price subsequently reach the target? If it did, the
probability is fine and the stop placement is the whole problem. If it did
not, the estimate is genuinely broken. Everything above is consistent with
either, and they need opposite fixes.

## The post-stop replay: it is the stop, not the call — 2026-09-02

The journal stops recording when the trade does, so this walks `quotes.db`
forward from each stop and asks whether price went on to reach the target it
was aiming at. 56 stopped trades carry a feed, side and target; 55 have quotes
after the stop.

| reached target within | n | share |
| --- | ---: | ---: |
| 30m | 14 / 55 | 25% |
| 2h | 31 / 55 | 56% |
| 4h | 38 / 55 | 69% |
| 24h | 45 / 55 | **82%** |

**And it is flat across the probability bands:**

| stated probability | reached target after being stopped |
| --- | ---: |
| 0.7-0.8 | 9 of 10 — 90% |
| 0.8-0.9 | 13 of 15 — 87% |
| **0.9+** | **14 of 16 — 88%** |

That comparison is the clean one. All three bands share the same horizon, so
whatever inflates the absolute number inflates all of them equally. A call the
model rated above 0.9 and which stopped out was still going the right way 88%
of the time - exactly as often as one it rated 0.7. **The direction was not
wrong. The trade was closed before it was right.**

So of the two candidate causes, the evidence favours stop placement. The
probability's contribution is indirect and already measured: it buys a further
target (53% of 0.9+ trades sit at RR 1.5+ against 29% at 0.8-0.9), and a
further target at the same risk fraction means an excursion that was always
going to be survived on the way to a win instead takes the stop.

### The caveat that stops this being conclusive

**There is no null here.** Given 24 hours, a driftless process will touch a
level roughly one risk-unit away most of the time, so "82% eventually reached
target" is partly a statement about prices moving rather than about these
calls. The 30m figure (25%) and the 2h figure (56%) are the ones near the
trade's own horizon and are the ones worth weighing.

What would settle it is the same replay from **random entry times on the same
feeds** - if random entries also reach a target-distance level 82% of the time
in 24h, this measures nothing. That has not been run.

Also: widening or removing a stop is not free. The 18% that never came back
would run much further than they did, and this measurement says nothing about
how far.

### One instrument breaks the pattern, and it is the one already flagged

| instrument | recovered after stop |
| --- | ---: |
| XAUUSD | 9 of 9 — **100%** |
| Wall Street 30 | 8 of 9 — 89% |
| US Small Cap 2000 | 4 of 4 — 100% |
| UK 100 / Germany 40 / US Tech 100 | 3 of 3 each — 100% |
| **Boom 500 Index** | **2 of 5 — 40%** |

Gold at 9 of 9 confirms the older finding from a second direction: its stops
are too tight, full stop. **Boom 500 is the opposite** - when it stops you out,
price genuinely does not come back, 40% against ~90% everywhere else. Its stops
are firing correctly and the instrument is simply hostile. That is independent
support for treating boom as an instrument problem rather than a stop problem,
which is what `by_slippage` does.

## Boom 1000 does not stop out at all

Asked because its losses kept arriving. All five of its closes:

| when | profit | R | exit | held | RR |
| --- | ---: | ---: | --- | ---: | ---: |
| 09-02 03:18 | −5.65 | −0.31 | hold | 549s | 0.30 |
| 09-02 03:18 | −4.90 | −0.31 | hold | 536s | 0.30 |
| 09-02 05:52 | −7.96 | −0.37 | stale | 1203s | 0.26 |
| 09-02 10:20 | −12.71 | −0.65 | stale | 1213s | 0.43 |
| 09-02 10:29 | −16.16 | −0.94 | hold | 1811s | 0.43 |

**Not one stop.** Three timed out on `hold`, two went `stale`, every one of
them underwater but none at −1R. It loses by sitting in a losing trade until
the clock ends it, on targets that were already close (RR 0.26-0.43).

That is a different failure from Boom 500's and needs a different answer - a
size cut for stop slippage would do nothing here, because nothing is slipping.
The candidates are a longer hold or not carrying the instrument, and five
closes on one day cannot choose between them.

**Unrelated but noticed:** `adverse_r` and `best_r` read 0.0 on the outcomes
inspected, so the heat tracking is still not populating. Scoring it was already
outstanding.
