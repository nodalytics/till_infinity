# Were the stopped trades wrong, or early?

Stops are the account. Of 120 closed trades:

| how it ended | trades | net | up |
| --- | --- | --- | --- |
| target | 20 | **+920.20** | 20 |
| hold | 40 | +12.67 | 21 |
| gone | 2 | +50.76 | 1 |
| stale | 6 | −5.01 | 3 |
| closed | 14 | −146.14 | 4 |
| **stop** | **38** | **−897.84** | **0** |

The targets pay for themselves almost exactly. Everything the desk has lost, it
lost through the stop - so the question worth asking is not whether to trade
less, it is whether those 38 trades were **wrong** or merely **early**. The two
call for opposite responses: early means the signal was right and the stop was
too tight for it; wrong means the stop saved money.

Harness: [`harness/stopped.py`](harness/stopped.py). For each stopped trade,
read the stored bars forward from its own entry over its own intended hold, and
ask whether price reached the target it was aiming at.

## What it says

    38 stopped out

       target reached inside the intended hold anyway :   7   (-187.33)
       target never reached                           :  20   (-456.89)
       stop and target inside one bar                 :   6   (order unknowable)
       no bars to judge                               :   5

       after the stop it took: median 68s, p25 22s, p75 108s

**Most stopped trades were simply wrong.** Twenty of the twenty-seven that can
be judged never reached their target at all, and they cost −456.89. On those the
stop did exactly what a stop is for.

**About a quarter were stopped early**, and they cost −187.33 - a fifth of the
total stop bill rather than the bulk of it. When price did come back it came
back *fast*: a median of 68 seconds after the stop, and three quarters of them
inside two minutes. That is the signature of noise rather than of a thesis
taking time to work.

## The correction, because the first number was wrong

The first version of this counted 13 early trades at −343.06, and it was
inflated. It looked forward from **entry**, so a bar whose high reached the
target and whose low reached the stop counted as "reached anyway" - but within
one bar the order of the two is unknowable from OHLC, and if the target really
came first the trade would have closed there.

Requiring the target to be reached **after** the close moved 6 of the 13 into an
"order unknowable" bucket and halved the money. Both numbers were computed from
the same data; the second is the one that answers the question that was asked.

They are reported separately rather than split by assumption, because assigning
them either way would move the conclusion by 22% of the stop bill.

## What follows from it

**Not "widen the stops".** Twenty trades that never reached target would have
lost more with a wider stop, and they outnumber the early ones three to one.
The measured cost of the early stops is −187 against −457 saved.

What the 68-second median does argue for is that the early stops are being taken
by noise on a timescale far shorter than the trade's own thesis - which is the
same conclusion `parked_stop_vol` and `entry_edge_vol` were shipped on, from the
other end. A better **entry** removes those stops without widening anything: the
entry moves toward the stop, the stop stays where the level put it, and the
distance the noise has to cover to reach it goes up while the risk goes down.
See [geometry.md](geometry.md).

## Caveats

* 33 judgeable trades. Enough to say "mostly wrong, not mostly early"; not
  enough to size a change.
* The forward window is the trade's own `expected_hold_s`, and where that was
  absent, three times the hold it actually got. A more generous window would
  find more targets and would be answering a different question - "would it have
  worked eventually" rather than "was the stop early".
* How far price went *past* the stop is still unmeasured. That would need bars
  after the close, and `_watch_shadows` already follows stopped trades for the
  narrower question of whether the target arrived.

## Now recorded: how much of the stop a trade actually uses

The gap this measurement ran into was that only the *favourable* extreme was
tracked. The trailing rules need it, so `_best` existed; nothing needed the
adverse one, so nobody wrote it down - and "how much heat does a winner take"
was not answerable from our own record.

`adverse_r` and `adverse_vol` are now on every trading outcome, beside `best_r`:

* **`adverse_r`** - the furthest a trade went against itself, in units of its
  own risk. On a trade that won, this is how much of the stop was used.
* **`adverse_vol`** - the same excursion in volatility units, because
  `adverse_r` is the right denominator for "was the stop used" and the wrong
  one for comparing instruments: a 4v stop and a 1v stop both read 1.0 when
  fully used.

The question it exists to answer: median `stop_vol` is **4.0v**. If winners
rarely spend more than a third of that, the stop is protection nobody reaches -
bought by sizing every position at a fraction of what the same money at risk
would otherwise allow. That is a sizing decision worth several times what the
seven early stops cost, and it needs a few dozen closed trades carrying the
field before it can be read.

## Per strategy: is the stop being wicked into?

A stop hit *and then reversed through* is a different failure from a stop that
was right, and pooling four strategies with different geometry hides it -
`fade-to-value` in particular enters at a discount to fair value, so its entry
is away from the level its stop is anchored to.

Harness: [`harness/wicked.py`](harness/wicked.py). Forward from each stopped
trade's own close, over the hold it had left.

| strategy | stops | came back through entry | reached target | money |
| --- | --- | --- | --- | --- |
| snap | 11 | 6/10 60% | 4/10 40% | −260.89 |
| fade-to-value | 6 | 4/6 67% | 3/6 50% | −155.16 |
| runner | 7 | 2/5 40% | 1/5 20% | −132.59 |
| inverse | 4 | 4/4 100% | 2/4 50% | −107.90 |
| sweep-aware | 3 | 3/3 100% | 2/3 67% | −99.09 |
| thesis-only | 4 | 3/4 75% | 2/4 50% | −76.16 |

**Supported and not distinguishing.** Two thirds of `fade-to-value`'s stops were
revisited, which is consistent with the stop sitting inside the noise - but
`inverse` and `sweep-aware` are at 100% and every cell is single digits. Pooled,
25 of 35 judgeable stops were revisited, so *most* stops are being traded back
through and no strategy separates from that yet.

Read against the section above rather than instead of it. This test is more
permissive - a wider forward window, and it does not exclude the bars where the
stop and the target are both inside one candle - so its 40% "reached target"
against the 21% above is the same data under a looser rule. The truth is
between them, and the direction both agree on is that a better *entry* is worth
more than a wider stop.

## Gold is the counter-example, and it cost a setting

Gold is 29 of 128 closed trades and **−315.25 of the account**, nearly half the
total loss. It is also, by every touch-level measure, the best instrument on
the board: the highest net edge in [paying.md](paying.md) at +0.919v, and the
cheapest spread in the book at 0.048v. Those cannot both be describing the same
thing, and the stopped trades say which is which.

| | stops | came back through entry | reached target anyway |
| --- | --- | --- | --- |
| **gold** | 9 | **7/8 (88%)** | **5/8 (62%)** |
| pooled, above | 27 | 25/35 | 7/27 (26%) |

**Gold inverts the pooled finding.** Across the book most stops were right - 20
of 27 judgeable trades never reached target. Gold's are mostly *early*: 62%
reached target after being stopped out, and those nine stops are −237.54 of its
−315.25.

### What it is not

**Not that gold wicks unusually far.** The obvious explanation is that it is a
spiky instrument needing more room, and that is false: by median wick past the
level it ranks **24th of 39** instruments. It is calmer than most of the book.

### The setting that was working against it

`parked_stop_vol` halves the stop on a parked fill held under
`PARKED_STOP_HOLD` (300s). **Gold's median hold is 95 seconds**, so gold trades
qualify - and gold's problem is stops that are already too tight.

It was shipped this session on a pooled measurement: halving the risk for the
same target doubles reward-to-risk and doubles the size for the same money at
stake. That arithmetic is correct and it is the wrong arithmetic for an
instrument whose stops are being clipped. **Turned off.**

The general lesson is the one this repository keeps paying for: a setting
justified by a pooled number can be actively harmful on the instrument that
number was averaged over.

### What is still unresolved

Gold has the best touch-level edge, the cheapest spread, and a 95-second median
hold against an edge measured at 300-1,800s. **The trade never survives to
where the edge is.** Two mechanisms fit and one measurement separates them:

* **the stop is too close for the hold** - 95 seconds is not long enough for a
  five-to-thirty-minute thesis, so the stop is sized for a trade that is not
  being allowed to happen;
* **the entries are in the tautology band** - 20 of gold's 29 trades are on 1m
  and 3m, where [horizon.md](horizon.md) finds the signal definitional rather
  than real.

`adverse_r` now records how much of its stop a *winner* actually used. A few
dozen gold trades carrying it will separate these: if winners spend most of the
stop, it is too tight; if they barely touch it, the entries are wrong.
