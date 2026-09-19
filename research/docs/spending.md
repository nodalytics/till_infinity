# Where the book spends its trades

The desk has two halves and they are not the same business. One is the
instruments the venue generates; the other is real markets. They are traded by
the same strategies, sized by the same rules and scored in the same journal,
and almost every figure this folder quotes pools them.

This page separates them, and the separation changes what the problem is.

Run `.venv/bin/python research/harness/spending.py` against the closes export.
688 closes, 2026-08-30 to 2026-09-11.

## The split

| | closes | P&L |
| --- | ---: | ---: |
| generated | 294 | **+167.94** |
| real markets | 394 | **−1,408.94** |

**43% of the trades are on instruments where a theorem says there is nothing to
find.** [deriving.md](deriving.md) establishes that a predictable position on a
martingale has zero gross expectancy, so `E[net] = −(c/2) × turnover` for every
stop, target, trail, entry filter and sizing rule. The synthetics are
martingales to the precision anything here can measure. The only reachable
improvement on that half is to trade it less.

## Put in units of what was risked, one half survives the check and one does not

A P&L compares position sizes. `risk_money` - what the trade stood to lose at
its stop - is on the close record, and P&L over risk deployed is the comparable
figure. It is present on 264 of the 688 closes, which is a big enough
restriction that the honest thing is to report both halves with and without it:

| | | closes | P&L | on risk of | = |
| --- | --- | ---: | ---: | ---: | ---: |
| **generated** | every close | 294 | +167.94 | | |
| | with a risk figure | 131 | **+462.04** | 2,635.50 | +17.5% |
| | without one | 163 | **−294.10** | | |
| **real markets** | every close | 394 | −1,408.94 | | |
| | with a risk figure | 133 | **−673.27** | 3,029.73 | **−22.2%** |
| | without one | 261 | **−735.67** | | |

The generated half's sign **flips** with the restriction: the closes that carry
a risk figure made +462 and the ones that do not lost 294. So `+17.5% of risk`
is a statement about which closes carry that field, not about those
instruments, and it is quoted here only to be withdrawn. This is the third time
today a result has turned out to be a property of a selection.

The real-market half does not flip. It loses on the restricted set (−673), on
the complement (−736) and on everything (−1,409), in roughly the proportion the
counts predict. **−22.2% of risk deployed, 95% studentised bootstrap [−36.4%, −6.6%]**, and
the interval excludes zero.

It is not five closes either. The five worst lost 172.90 between them; drop all
five and it is still **−17.2%**.

## The geometry, which is the actual finding

On those 133 real-market closes:

| | n | mean, as a share of the risk |
| --- | ---: | ---: |
| wins | 54 | **+54.4%** |
| losses | 79 | **−78.2%** |

Hit rate **40.6%**. Realised payoff **0.70:1**. Break-even at that payoff needs
**59.0%**, so the book is **18.4 points short**.

Now the same arithmetic against the payoff it *aimed* for. `reward_to_risk` is
written at entry, and its median across the same 133 is **1.36:1**. A book with
a 1.36:1 payoff breaks even at 42.3%.

**It hits 40.6%. At the payoff it plans, it is short by 1.7 points.**

That is the whole result. The entries are within noise of adequate. The exits
realise **half** the payoff the entries were sized for - 0.70 against 1.36 -
and that halving is the entire loss. A win comes in at 54% of its risk where a
loss comes in at 78% of it, so the book keeps four tenths of what it plans to
win and pays eight tenths of what it plans to lose.

### Which is not the give-back, and the difference matters

[giveback.md](giveback.md) is about a trade that reaches +2R and closes at its
original stop, and that was real, was traced to `_best` being thrown away
across a restart, and was fixed on 2026-09-04. This is a different thing and it
survives that fix: a book whose average win is 0.54R is not mostly giving back
open profit, it is mostly never getting far enough in front to have any.

## How trades ended

| exit | n | on risk |
| --- | ---: | ---: |
| hold | 50 | +7.5% |
| stop | 42 | **−102.7%** |
| target | 17 | **+81.5%** |
| stale | 8 | −9.4% |
| unknown | 16 | −24.5% |

Two things to read off this and one trap.

**Stops cost what a stop should.** −102.7% against a nominal −100%, which is
2.7 points of slippage and spread, on real markets. That is the number
[generators.md](generators.md) found to be 10-19R on the spike side of Boom and
Crash; nothing like it happens here.

**Targets pay, and they are the smallest group.** +81.5% on 17 closes, and the
median *planned* payoff on those particular trades was 0.574R against a
realised median of 0.628R - a ratio of **1.089**. Targets deliver slightly more
than they promise. There are just 17 of them against 42 stops.

The trap is the `hold` row: +7.5% on 50 closes, the largest group. A hold exit
is a clock running out, and on this book that is mildly positive. It is not an
edge - it is what is left of a trade that neither reached its target nor its
stop, and its mean sits near zero because that is what "neither" means.

## The far targets are the loss, and the near ones are the only thing working

Split the same 133 real-market closes by the reward-to-risk each trade was
**planned** at, which is written on the order:

| planned | n | hit rate | on risk | 95% |
| --- | ---: | ---: | ---: | --- |
| below 1:1 | 50 | 62.0% | **−2.1%** | [−19.5%, +14.3%] |
| 1:1 to 2:1 | 53 | 30.2% | −21.9% | [−47.0%, +8.3%] |
| 2:1 and above | 30 | 23.3% | **−53.3%** | **[−83.2%, −3.7%]** |

**This is the reverse of the obvious reading, and the obvious reading was
about to be shipped as a gate.** A trade whose target sits closer than its stop
looks like the thing to remove: it needs a hit rate above two thirds to pay.
It gets one - 62.0% against the 66.9% its median plan needs - and it is the
only group on the book that is not losing. The trades aiming at two-to-one and
better hit 23.3% against the 26.2% *they* need, which is nearly adequate, and
still lose more than half the risk they deploy.

The hit rates are all close to what each group needs. What separates them is
what the winners actually collect:

| planned | median plan | win, of risk | loss, of risk | realised payoff |
| --- | ---: | ---: | ---: | ---: |
| below 1:1 | 0.494 | +32.5% | −56.4% | 0.577 |
| 1:1 to 2:1 | 1.504 | +86.4% | −78.2% | 1.105 |
| 2:1 and above | 2.818 | +78.2% | **−96.1%** | **0.813** |

A trade planned at 2.8:1 realises 0.81:1. It pays a near-full stop when it is
wrong and collects less than an R when it is right.

### What fires instead of the target

| exit | n | median planned | median realised | kept |
| --- | ---: | ---: | ---: | ---: |
| target | 17 | +0.574R | +0.628R | **109%** |
| hold | 50 | +1.167R | +0.058R | **5%** |
| stop | 42 | +1.546R | −0.989R | −64% |
| stale | 8 | +0.859R | −0.040R | −5% |

Ordered by the distance the trade was aiming at, and monotone in it. **Trades
that aimed at 0.57R hit it and collected 109% of it. Trades that aimed at 1.17R
ran out of clock at 5% of it. Trades that aimed at 1.55R paid the stop.**

So the exit that fires is chosen by the target's distance, and only the nearest
band ever reaches the rule it was sized for. On the 35 closes since 2026-09-03
where the peak is trustworthy, the median trade reaches **38.5%** of its own
target and a quarter of them reach under 10% of it.

### Where the far targets come from

Not from a strategy asking for one. The stop distance is flat across all three
bands - 1.47, 1.26 and 1.23 volatility units - so a high planned ratio is a
**far target**, not a tight stop. Targets are placed at structure, so the ratio
is set by how far the next level happens to be, and a trade entered in front of
a distant level is handed a flattering reward-to-risk it has no better chance
of reaching. `fade-to-value` and `sweep-aware` supply nine each of the thirty,
on gold eleven times.

That is the actionable shape: **the planned reward-to-risk is an output of the
level geometry, not a decision, and the book sizes and selects on it as though
it were a decision.**

### How far to trust this

Three bands is three comparisons, not forty, and the bands were chosen before
the numbers at the natural boundaries. But `winning.md` ran 43 entry features
against a 300-permutation control on this same book and **nothing cleared the
noise floor**, so any cut of this data that is not pre-registered should be
assumed to be inside it. Cuts by stop distance, by feed and by hour were run
and are not reported here: every interval spanned zero and reporting the
largest would be the scan `winning.md` already refuted.

What survives is the ordering, because it is monotone across three bands in
two independent tables - the payoff one and the exit one - and because the
2:1-and-above interval excludes zero on its own.

## By strategy, on real markets only

| strategy | n | on risk | 95% |
| --- | ---: | ---: | --- |
| snap | 29 | −34.3% | **[−64.7%, +6.9%]** |
| thesis-only | 28 | −1.0% | [−25.4%, +22.0%] |
| sweep-aware | 23 | −25.1% | [−67.7%, +41.0%] |
| runner | 17 | −5.6% | [−39.6%, +28.5%] |
| fade-to-value | 16 | −38.7% | [−82.2%, +15.3%] |
| inverse | 6 | −72.4% | too few |
| approach-scalp | 3 | −83.4% | too few |

**`snap`'s interval no longer excludes zero, and that is a retraction.** The
rows above are **studentised**; they were percentile when this page was first
written, and `research/calibrating.md` measured those endpoints over-rejecting
at **7.05%** against a nominal 5% at exactly this n. On the corrected interval
`snap` reads **[−64.7%, +6.9%]** and no strategy row separates from zero.
`research/auditing.md` makes the same correction independently and adds that it
never needed the twelve-row multiplicity argument to fall - the interval
construction alone was enough.

What stands is the arithmetic, not the interval: −34.3% over 29 closes,
27.6% hit rate against the 52.2% its own payoff needs, median hold **114
seconds**, on gold, us30, silver, ger40, us100 and btc. Its shape is
`stop=1.0, target=1.0, hold=120s` - a 1:1 with two minutes to find it, which
charges the spread on both legs of every attempt and needs better than a coin
to clear it. It does not have better than a coin.

Everything else is unresolved. `thesis-only` is flat at −1.0% over 28.
`sweep-aware` reads −25.1% on real markets against the +0.154R it shows
book-wide, and the difference is that its book-wide figure is mostly generated
instruments - the same pooling this page exists to undo.

## What would have killed this

Written into `spending.py` before the numbers were read:

| condition | outcome |
| --- | --- |
| the real half's sign moves under the risk-figure restriction | **survived** - −673, −736, −1,409, all the same sign |
| the loss is five closes | **survived** - −17.2% with the five worst removed |
| one strategy carries it | **partly fired** - `snap` is a third of it and is named separately |
| the bootstrap interval includes zero | **survived** - [−36.4%, −6.6%] |

And one that fired against the other half: the generated result did move under
the restriction, so it is withdrawn rather than reported.

## What follows

1. **Turn `snap` off on its mechanism, not on this table.** Its interval does
   not exclude zero once studentised, so this page is not evidence against it.
   The mechanism is, and `trading/barriers.py` now prices it: a symmetric pair is
   a coin however finely watched, discrete monitoring costs it 0.053R in
   overshoot foregone on the wins, and the spread is charged twice - a drag
   needing a **57.7% to 67.7%** hit rate from the signal alone, against the 27.6%
   observed. That argument does not depend on 29 closes.
2. **The exits are the problem, not the entries.** A 40.6% hit rate is 1.7
   points off break-even at the payoff the book plans and 18.4 points off at the
   payoff it realises. Every further point of hit rate is worth about a fifth of
   what closing the payoff gap is worth, so work on the exit before the signal.
3. **Stop selecting on planned reward-to-risk, and consider capping it.** The
   ratio is an output of where the next level sits rather than a choice, the
   2:1-and-above band loses **−53.3% [−84.6%, −19.0%]**, and the band that looks
   worst on paper is the only one near flat. A target beyond about 1R is not
   reached: it is replaced by the clock at 5% of its value or by the stop at a
   full one. Either shorten the target to what the hold can deliver, or lengthen
   the hold to what the target needs - the present pairing does neither.
4. **Decide what the generated half is for.** 43% of closes are on instruments
   that cannot pay in expectation. If they are there to exercise the machinery
   cheaply, that is a defensible answer and should be written down as the
   reason. If they are there to make money, `deriving.md` has already settled it.
5. **Do not quote a pooled book figure again.** Every number on this page
   changes sign, size or significance depending on which half it is drawn from.

## What this does not say

It does not say the real-market entries work. "Within 1.7 points of break-even
at the planned payoff" is not an edge, it is an absence of a large negative, and
1.7 points on 133 closes is far inside the noise.

It does not measure costs separately. The −22.2% is net of spread and swap, and
nothing here says how much of it is cost rather than direction.

And 133 closes is small. The per-close return on risk has a standard
deviation of **0.805**, so separating a genuine +5% of risk from zero at 95%
needs about **1,000 closes** and +10% needs about **250**. The −22.2% measured
here needs 51, which is why that one interval closes and nothing else on the
page does. What is established is the *shape*: which half the money goes to,
and that the gap between planned and realised payoff is several times the gap
between the hit rate and break-even.
