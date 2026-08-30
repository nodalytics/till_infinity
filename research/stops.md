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
