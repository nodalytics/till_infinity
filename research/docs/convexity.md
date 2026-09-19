# Stop paying for accuracy: is this book's money in the tail

Asked as a thesis rather than a question: *every strategy on this desk is built
to be right often, `clustering.md` and `horizon.md` measured direction as close
to unforecastable at the horizon traded, and the book is net negative. So stop
paying for accuracy and buy convexity instead - lose small and often, win large
and rarely.* Three things in this folder point that way already: `exiting.md`'s
corrected edge of **+0.046R while being worse on 64% of the same trades**,
`giveback.md`'s **27% of the high-water mark kept**, and `instruments.md`'s
whole instrument ranking that turned out to be **one trade of +622.63**.

Three questions, and all three come back against the thesis.

1. **The money tail is real in dollars and is a sizing artefact.** The top 5%
   of closes carry **57.3%** of gross profit. Measured in **R** - the multiple
   of each trade's own risk, which is what the shape of a trade is - the same
   top 5% carry **35.7%**, and that is *inside* what a normal distribution with
   the same mean and variance produces. Re-price the book at one flat position
   size and the money figure collapses to **34.9%**. The largest close is
   **+622.63 at +0.703R**; the largest close in R, over 325 of them, is
   **+2.429**. There is no tail in the trades; there is dispersion in the
   position sizer.
2. **The tail is being cut, and not by the clock.** The 19 closes that got
   furthest in front peaked at a mean **+1.881R** and realised **+0.060R** -
   they kept **3.2%**. But the replay cannot reproduce the mechanism: it exits
   99% by stop where the live desk exits 39% by timeout, so removing the hold
   cap entirely - 30 bars to 2,880 - moves the replayed mean by **+0.002R**.
3. **A deliberately convex policy does not beat the one that ships.** It loses
   in the discovery half, wins in the verify half, and the size of both is the
   **stop denominator**: shrink the stop 3x and mean R moves 3.15x in verify,
   2.9x in discovery, 3.3x pooled - in whichever direction that window's drift
   already pointed. At a constant stop the convex *shape* is worth **+0.009R
   pooled and flips sign across the split**. Convexity here is not an edge. It
   is a magnifier, and there is nothing under it to magnify.

The one-sided synthetics say the same thing in a sharper way, and are the most
interesting result on the page - see §5.

## What was run

| | |
| --- | --- |
| [harness/convexbook.py](harness/convexbook.py) | the live journal: concentration, give-back, and what the tail winners share |
| [harness/convexity.py](harness/convexity.py) | the replay: a nine-rung hold ladder and twelve exit policies over 16,056 (gated) and 20,248 (ungated) trades |
| [harness/convexspike.py](harness/convexspike.py) | Boom and Crash with no strategy in the way - a fixed clock, both sides, four horizons, and a no-stop control |

All three run on the lab, never on the instance (`starving.md`). Every replay
uses the shared corrected walk in `till_infinity/shared/replay.py` - spread
charged on both legs, levels tested as they rested when the bar opened, a bar
opening through a level filled at the open. Every feature cut goes through
`shared/strata.compare`, which cuts within strategy, interval and feed class and
names the strata whose ordering disagrees with the pooled one.

**The number of comparisons is about 250**: 66 in each of two `convexity.py`
runs, 38 in `convexbook.py`, 72 in `convexspike.py`, plus the concentration
tables. Every one of them had its failure condition written into the harness
docstring before the run, and the largest surviving effect on the page is one
the harness itself identifies as a defect.

### The window, and the half that is missing

Everything live is the lab's journal snapshot, **2026-08-26 12:46 to 2026-09-10
09:36 UTC**. `winning.md` and `edge.md` were written against a fresher copy
holding 685 and 688 closes; this has 562, and production reads were not
available to this study. Where a figure here disagrees with one of those, theirs
is on more data.

| | n | window | median hold | over 1800s | exits |
| --- | ---: | --- | ---: | ---: | --- |
| `kind='outcome'` | 325 | 08-26 → 09-10 | 509s | 13.8% | hold 126, stop 78, target 77, stale 28 |
| unattributed observations | 237 | 09-01 → 09-10 | **1,201s** | **30.4%** | hold 90, target 71, stop 58, stale 18 |

**Zero of the 237 carry R.** `eef4912` adds `r_multiple` and `best_r` to a
parentless close and is not in the running image, so every R figure below is the
attributed half - which is the *short* half, by a factor of 2.4 in median hold.
This study is about long-held tail trades, so that bias runs directly at the
question, and every money figure is therefore computed twice. It moves the
concentration and does not move the conclusion: the top 5% carry 57.3% of gross
profit on the attributed half and **45.4%** on both halves together, and the
single +622.63 trade is 30.2% of the first and 18.6% of the second.

## 1. Where the money comes from

Total profit is negative, so "share of total profit" is not a quantity. Every
share here is of **gross** profit - the winners' sum - with the mirror statistic
beside it, because a concentration figure with no loss-side mirror is a number,
not a shape.

| ranked by | n | net | top 1% | **top 5%** | top 10% | top 20% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| money, attributed | 325 | -871.08 | 36.1% | **57.3%** | 71.7% | 88.2% |
| money, both halves | 562 | -1351.56 | 26.0% | **45.4%** | 61.7% | 81.3% |
| **R, attributed** | 325 | -66.74R | 10.5% | **35.7%** | 55.2% | 79.9% |

and the same table for the losers, as a share of gross loss:

| ranked by | worst 1% | **worst 5%** | worst 10% | worst 20% | asymmetry at 5% |
| --- | ---: | ---: | ---: | ---: | ---: |
| money, attributed | 5.3% | 21.1% | 36.5% | 63.1% | **2.71x** |
| money, both halves | 6.4% | 23.3% | 40.2% | 67.3% | 1.95x |
| R, attributed | 4.3% | 16.5% | 29.5% | 55.3% | 2.16x |

So the answer to the question as asked is **57.3%**, and it is the wrong number
to act on. Three things say so.

**It is one trade.** The largest close is +622.63, which is 30.2% of all gross
profit on the book. Remove it and the attributed half goes from -871.08 to
-1,493.71. It is also the trade that makes `thesis-only` read **+185.08** in the
table below, against the **-441** recorded in `giveback.md`: strip that one row
and `thesis-only` is -437.55, which is the same strategy and the same verdict.

**It does not survive a split.** Cut the window 60/40 by time:

| half | n | money, top 5% | R, top 5% |
| --- | ---: | ---: | ---: |
| discovery | 195 | **60.2%** | 34.7% |
| verify | 130 | **26.0%** | 32.7% |

The money concentration collapses by more than half between the two; the R
concentration does not move. The first is one trade in the first half. The
second is the book.

**And it is position size, not trade shape.** R is the multiple of a trade's own
risk, and this desk sizes to risk - the journal carries `risk_money` beside
`risk_price` and `volume`. Re-price every close at one flat risk:

| | as traded | at one flat size |
| --- | ---: | ---: |
| top 5% share of gross profit | **62.4%** | **34.9%** |
| largest single close | **+622.63** | **+55.30** |

Risk per trade runs from a median 22.77 to a maximum 58.67 - a 2.6x spread -
and that 2.6x is most of the difference between a book that looks
lottery-shaped and one that does not. (Both columns are the **211** closes of
the 325 that carry `risk_money`, which is why the left one reads 62.4% where the
table above reads 57.3%; the comparison is within one population.)

### Is 35% a lot?

It needs a reference point, so: draw the same number of trades from a normal
distribution with the same mean and standard deviation - the thinnest-tailed
distribution with those moments - 2,000 times, and ask what share of gross
profit its top 5% carries.

| | observed | thin-tailed null | 95th percentile | |
| --- | ---: | ---: | ---: | --- |
| money | **57.3%** | 26.7% | 30.2% | **above the null** |
| **R** | **35.7%** | 32.1% | 36.7% | **inside the null** |

**In R, this book's profit concentration is indistinguishable from Gaussian.**
The largest R on 325 closes is +2.429 against a stop at -1. That is not a
convex book that is being cut off; it is a book with no tail in it at all, whose
dollar figures wear one borrowed from the position sizer.

| strategy | n | mean R | median | win | top 5% of gross R | $ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| thesis-only | 190 | -0.107 | -0.009 | 49.5% | 32.8% | +185.08 |
| runner | 33 | -0.265 | -0.199 | 33.3% | 40.5% | -151.31 |
| snap | 29 | -0.341 | -0.554 | 27.6% | 24.8% | -210.38 |
| fade-to-value | 25 | -0.438 | -1.000 | 28.0% | 29.8% | -302.38 |
| sweep-aware | 16 | -0.404 | -1.000 | 25.0% | 44.5% | -130.78 |
| confluence-scalp | 11 | -0.419 | -0.066 | 27.3% | 58.9% | -112.24 |

## 2. Is the tail being cut off

### Live: yes, and the give-back is worst exactly where the peak is largest

97 closes carry a non-zero high-water mark. `best_r` was a constant until
2026-09-02, which is why it is 97 and not 325 - `giveback.md` records why.
Split into fifths by peak:

| peak fifth | n | mean peak | mean realised | keeps | ends on the clock | stopped | target |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **top** | 19 | **+1.881** | **+0.060** | **3.2%** | 42.1% | 21.1% | 36.8% |
| 2 | 19 | +0.709 | +0.052 | 7.3% | 47.4% | 10.5% | 42.1% |
| 3 | 19 | +0.337 | +0.209 | 62.1% | 36.8% | 0.0% | 63.2% |
| 4 | 19 | +0.238 | +0.003 | 1.2% | 68.4% | 0.0% | 31.6% |
| 5 | 19 | +0.119 | -0.261 | - | 68.4% | 15.8% | 15.8% |

**The trades that go furthest in front give back the most.** The top fifth
peaked at nearly 2R and banked six hundredths of one. That is a stronger
statement than `giveback.md`'s book-wide 27%, and it is the shape a desk would
have if it were systematically destroying its own right tail.

The ten largest peaks individually:

| when | symbol | strategy | peak | kept | exit |
| --- | --- | --- | ---: | ---: | --- |
| 09-03 16:19 | Volatility 50 | confluence-scalp | +4.319 | **-1.005** | stop |
| 09-04 02:42 | US Tech 100 | confluence-scalp | +3.043 | -0.066 | hold |
| 09-04 02:42 | US Tech 100 | confluence-scalp | +3.042 | -0.065 | hold |
| 09-04 05:31 | Volatility 10 | confluence-scalp | +2.752 | **-1.076** | stop |
| 09-04 18:00 | Wall Street 30 | thesis-only | +2.330 | **-1.026** | stop |
| 09-04 18:00 | Wall Street 30 | thesis-only | +2.254 | -0.928 | hold |
| 09-03 17:40 | Crash 1000 | thesis-only | +2.231 | +2.223 | target |
| 09-02 22:00 | Volatility 25 | thesis-only | +1.770 | +1.359 | hold |
| 09-03 10:02 | Boom 500 | thesis-only | +1.618 | +0.367 | hold |
| 09-04 06:33 | Germany 40 | thesis-only | +1.494 | +0.725 | target |

Three trades that were between 2.3R and 4.3R in front came back and paid a full
stop. **That is the book's entire right tail, and it is handed back through the
stop rather than through the clock.**

Which is also what ends the trades that *do* realise a big number:

| | n | hold | target | stop | stale | median hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| top decile by R | 32 | 18.8% | **71.9%** | 0.0% | 0.0% | 376s |
| the rest | 293 | 41.0% | 18.4% | 26.6% | 9.6% | 536s |

So the declared failure condition - *the biggest winners do not end on the hold
timeout* - **is met**. They end on the target, seven times in ten, and they are
*shorter* than the book's median, not longer. The clock is not what cuts this
tail.

### Replayed: the hold cap is worth +0.002R, and the replay cannot see the problem

The same trades, the same exit rules, only the hold cap moved. 16,056 replayed
`sweep-aware` entries, every one with 2,880 bars of runway after it so that
every rung is the same trades and nothing is scored as having timed out when it
merely ran out of data.

| hold (1m bars) | shipping mean R | timed out | `live_wick` mean R | timed out | convex mean R | timed out |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **30** (ships) | **-0.026** | 0.5% | -0.031 | 4.4% | -0.062 | 20.6% |
| 120 | -0.024 | 0.0% | -0.030 | 0.9% | -0.046 | 7.0% |
| 480 | -0.024 | 0.0% | -0.031 | 0.1% | -0.045 | 1.0% |
| 1440 | -0.024 | 0.0% | -0.031 | 0.0% | -0.038 | 0.1% |
| 2880 | -0.024 | 0.0% | -0.031 | 0.0% | -0.038 | 0.0% |

Removing the clock entirely - a 96-fold increase in the hold - is worth
**+0.002R** under the shipping exit and **0.000R** under the wick-widened trail
the service actually applies. On the ungated population (20,248 trades) it is
+0.053 to +0.055 and +0.046 to +0.047. The reason is in the two `timed out`
columns: **the replay times out on 0.5% of trades where the live desk times out
on 39% of them** (126 of 325), and on 81% of `sweep-aware`'s closes in
`giveback.md`. A clock can only bind on a trade that would otherwise still be
open, and in this replay almost nothing is.

`exiting.md` reached the same wall from the other side and drew the right
conclusion: *a replay that disagrees with the live exit mix that badly is
evidence about the harness.* Adding the `live_wick` policy - which reproduces
`manage.stop_for`'s uncapped wick widening rather than the 0.5v the class asks
for - moves the timeout share from 0.5% to only 4.4%, so it is not the trail
width either. **The question "what would these trades have made with no hold cap
at all" is not answerable by this replay**, and the honest version of the answer
is the live table above: the trades that reach a big peak lose it to their stop,
long before any clock.

## 3. Would a deliberately convex policy do better

Twelve policies on the same trades, paired, spread charged, split 60/40 by time.
Everything but the exit is held constant - entry, direction, level and the risk
the position is sized against. `convex` is the shape the question asks for: stop
at **half** the modelled risk, no reachable target, a trail three R behind the
peak, no break-even, and a day to run. `concave` is the deliberate opposite and
is the control that matters.

**Ungated population, 20,248 trades.** The gated one (16,056) is in the log and
tells the identical story one notch lower.

| policy | mean R | median | win | **p95** | p99 | vs ships | better on | -best |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| convex_tighter (0.33 stop) | **+0.174** | -0.739 | 43.3% | **+9.44** | +17.73 | +0.121 | 38.7% | +0.165 |
| convex (0.5 stop) | +0.125 | -1.000 | 38.0% | **+7.58** | +14.29 | +0.072 | 30.6% | +0.119 |
| convex_trail_late | +0.124 | -1.000 | 39.1% | +7.63 | +14.42 | +0.070 | 31.5% | +0.117 |
| convex_break_even | +0.119 | -0.135 | 33.1% | +7.24 | +13.86 | +0.066 | 27.0% | +0.113 |
| convex_full_stop (1.0 stop) | +0.063 | -1.000 | 30.8% | +5.69 | +11.34 | +0.009 | 22.7% | +0.059 |
| let_it_run | +0.057 | +0.224 | 58.2% | +2.45 | +4.98 | +0.003 | 0.8% | +0.054 |
| **shipping_30** | **+0.053** | +0.224 | 58.2% | **+2.44** | +4.96 | - | - | +0.050 |
| live_wick_30 | +0.046 | +0.144 | 54.6% | +2.67 | +5.36 | -0.007 | 8.8% | +0.043 |
| **concave** | +0.008 | +0.207 | **75.6%** | **+1.01** | +2.12 | -0.045 | 43.1% | +0.006 |
| convex_no_trail | -0.193 | -1.155 | **6.0%** | +5.23 | **+43.55** | -0.246 | 6.2% | -0.226 |

### The policy does exactly what convexity is supposed to do

That part is not in doubt. Reading down the table, win rate falls from 75.6% to
6.0% while the 95th percentile climbs from +1.01R to +9.44R, and where the money
comes from moves with it:

| policy | top 5% of gross profit | worst 5% of gross loss | best | worst |
| --- | ---: | ---: | ---: | ---: |
| concave | 29.5% | 36.1% | +29.70R | -47.35R |
| shipping_30 | 34.2% | 37.9% | +59.40R | -94.69R |
| convex | **41.6%** | **31.3%** | +123.62R | -189.38R |
| convex_no_trail | **98.0%** | 23.8% | **+652.31R** | -189.38R |

`convex_no_trail` - tiny stop, no target, nothing trailing, hold a day - is the
purest lottery ticket available: it wins **6.0%** of the time, takes **98.0%** of
its gross profit from its top 5%, and its single largest trade is **+652R**. It
also loses **-0.193R** a trade. Convexity is purchasable here. It is priced.

### And the gain is the stop denominator, not the shape

Two rows decompose it. `convex_full_stop` is the convex *shape* at the **same**
risk as what ships - no target, no break-even, a 3R trail - and the three
`convex` rows differ from it only in the stop multiplier.

| | discovery | verify | pooled |
| --- | ---: | ---: | ---: |
| shipping_30 | -0.040 | +0.193 | +0.053 |
| convex_full_stop (1.0x risk) | -0.056 | +0.241 | +0.063 |
| convex (0.5x risk) | -0.068 | +0.414 | +0.125 |
| convex_tighter (0.33x risk) | **-0.115** | **+0.607** | **+0.174** |

Read the columns, not the rows.

* **The shape at constant risk is worth nothing.** `convex_full_stop` beats what
  ships by +0.009R pooled, -0.016R in discovery and +0.048R in verify. It flips
  sign across the split, which is the definition of noise on this desk.
* **The stop multiplier is worth exactly what arithmetic says it is worth.**
  Divide the stop by three and the mean moves 2.9x in discovery, 3.15x in
  verify and 3.3x pooled - **in whichever direction that window was already
  going.** R is the move divided by the risk; shrink the denominator and you
  scale the numerator's sign along with it.
* **And the sign is not stable.** The whole convex family loses in the discovery
  half and wins in the verify half, on both populations, at every stop width.
  The declared failure condition was *no verify-half win over what ships*; what
  happened instead is worse than that - a **reversal**, where the proposing half
  says one thing and the disposing half says the opposite, which is a period
  effect wearing a policy's name.

It does not survive the Simpson check cleanly either. On the ungated verify
half `convex` beats what ships by +0.44R at 5m, +0.30R at 30m, +0.30R at 15m and
+0.08R at 1m, and is flat at 3m (-0.003R); on the gated population the same cut
**loses by -0.14R at 3m** while winning by +0.35R at 5m. One entry timeframe in
five disagrees with the other four, and which way it disagrees depends on which
population is replayed.

Removing the single best replayed trade moves nothing (+0.125 → +0.119), which
is the one discipline this section passes cleanly: at 20,248 trades these are
not one accident, unlike §1.

**So: a deliberately convex policy does not beat the shipping one.** What it
does is lever it. On a book whose entry has no measured directional edge -
`clustering.md`, `horizon.md`, and now `winning.md`'s null on 43 features -
levering it is a way to arrive at the same place with more variance and twice
the spread bill.

## 4. What the tail winners have in common

Nothing, twice, against a control built for the question.

**Live**, top decile by `best_r` (10 of the 97 closes carrying one) and by
realised R (32 of 325), against 19 decision-time features - 16 and 18 of them
respectively had enough rows on both sides of the cut to be scored. The control
is the largest standardised gap a **random** decile of the same closes
produces, because that is what a reader's eye picks out of a table of nineteen.

| tail definition | largest gap | feature | control 95th | over? |
| --- | ---: | --- | ---: | --- |
| by `best_r` | +0.735 | `risk_vol` | 1.078 | no |
| by realised R | +0.565 | `reward_to_risk` | 0.612 | no |

Nothing clears it, and `risk_vol` **reverses within `thesis-only`**, which is
76 of the 97 rows.

**Replayed**, where the sample is not the constraint: the top decile by
`convex` R - a policy with no target and a 3R trail exits near its own peak, so
its top decile is the closest thing a forward walk can produce to a `best_r`
decile - against 25 decision-time features, cut on the discovery half and
carried into verify.

| feature | discovery gap | verify gap | control 95th |
| --- | ---: | ---: | ---: |
| `wick_ahead` | +0.102 | **-0.079** | 0.101 |
| `probability_up` | -0.090 | -0.030 | 0.101 |
| `edge` | -0.088 | -0.034 | 0.101 |

The largest of 25 clears the control by 0.001, **flips sign in the verify
half**, and `strata.compare` reverses it in 3 of 7 strata. That is three
independent ways of saying the same thing.

**The tail cannot be selected for.** Which matters more than it looks: "trade
for the tail" is only a strategy if the tail is predictable at order time. It is
not, here, and that is consistent with `winning.md`'s null over 43 features on
the live record and with `clustering.md` and `horizon.md` before it.

## 5. The one-sided generators, and the best result on this page

Boom grinds down and spikes up; Crash grinds up and spikes down. A position held
in the spike direction has a bounded cost and an unbounded gain, which is the
structurally convex bet on this book, and `instruments.md` had the desk on the
wrong side of it - before **withdrawing** the finding, because the replayed
buy-minus-sell gap came out with the *same* sign on both families and the
hypothesis requires opposite signs.

Re-run here through `sweep-aware`'s ungated call stream, that withdrawal holds
under every policy: boom buy-minus-sell **+0.142R**, crash **+0.098R**, and
everything non-synthetic **-0.050R**. Same sign. Not a spike effect.

So `convexspike.py` removes the strategy entirely. Entries on a fixed clock,
every `hold`-th bar so none overlap, both sides, a stop `sqrt(hold)` average
1-minute ranges wide so it scales with the horizon, spread charged. Three rows:
**no_stop** is held to the horizon with nothing truncating it; **flat** has the
stop; **convex** halves it. `symmetric` is the Volatility and Step indices -
same broker, same generator family, no one-sided jump - and is the control.

Buy minus sell, so the hypothesis needs **boom positive and crash negative**:

| horizon | row | boom | crash | symmetric |
| ---: | --- | ---: | ---: | ---: |
| 30 bars, n=8,616 | no_stop | **-0.040** | **+0.034** | -0.003 |
| | flat | **-0.316** | **+0.340** | +0.000 |
| | convex | **-0.937** | **+0.917** | +0.009 |
| 120 bars, n=2,154 | no_stop | -0.073 | +0.055 | -0.006 |
| | flat | -0.196 | +0.187 | -0.013 |
| | convex | -0.502 | +0.590 | -0.000 |
| 1440 bars, n=177 | no_stop | -0.196 | +0.097 | -0.032 |
| | convex | -0.726 | +0.230 | -0.047 |

Two things here, and the second is the finding.

**First: the signs are opposite, and they are the wrong way round.** Boom
prefers the **sell** and Crash prefers the **buy** - both the *grind* side, both
the side the spike runs **against**. The convex bet, held in the spike
direction, is the losing side of both. The control is flat to three decimals at
every horizon, so this is not a harness direction bias.

**Second, and this kills it: the effect is manufactured by the stop.** At 30
bars the raw drift asymmetry with no stop is **0.04R**. Put a stop on it and it
is **0.32R**. Halve the stop and it is **0.94R** - *twenty-three times* the
quantity being measured. That is not how an edge behaves under a risk rule. It
is exactly how an **unfillable stop** behaves: selling Boom with a stop is being
short a jump whose loss the replay caps at -1R, filled *at the stop price*,
which is a price a one-tick spike never offered. The tighter the cap, the larger
the phantom.

And the phantom scales with the size of the jump it is truncating:

| feed, convex at 30 bars | grind side | mean R |
| --- | --- | ---: |
| boom_1000_index | sell | **+1.490** |
| boom_500_index | sell | +0.721 |
| boom_300_index | sell | +0.464 |
| crash_1000_index | buy | **+1.565** |
| crash_500_index | buy | +0.732 |
| crash_300_index | buy | +0.418 |
| step_index / volatility_* | either | ±0.05 |

Boom 1000 spikes least often and largest; Boom 300 most often and smallest.
**The apparent edge is monotone in the spike size**, identical in both families,
absent on every symmetric feed, and eight to twenty-three times smaller the
moment the stop is removed. `spikeside.py` and `instruments.md` were right to
withdraw; this is the mechanism they were missing.

The no-stop rows do leave a small asymmetry in the grind's favour - about
0.04R at 30 bars, growing to 0.20R at a day - against a symmetric control that
sits at -0.003R on twice the sample. It may be real; it is small, it is the
*opposite* of the convex side, and the only way to collect it is to be short the
jump, which is the position whose cost this replay has just been caught refusing
to price. It is not a reason to trade Boom or Crash. It is a reason to believe
the generator is close to fair, which is what a house-designed process should
be.

## What this does not say

* **It does not say convexity is wrong in general.** It says it does not add an
  edge *to this population*. A magnifier on a zero is a zero.
* **It does not price holding.** Every long-hold policy here occupies a slot
  against `max_positions=10` for up to 48 times as long, and the replay cannot
  see that. If a convex policy did win by a tenth of an R it would still have to
  pay that bill.
* **It does not model queue position, commission, funding or slippage beyond
  the spread**, and §5 is a demonstration of what the last of those is worth.
  `never filled` was 3.9% of live attempts and is excluded here by construction.
* **The live half is small and half-missing.** 325 scored closes, 237 more with
  no R at all, and the missing ones are the long ones. `eef4912` fixes that
  going forward and this page should be re-run when it has been shipping for a
  week - §1 and §2 are the sections that would move.
* **`best_r` is 97 rows.** The give-back table in §2 is the strongest thing here
  and rests on 19 closes in its top cell.

## The answer

**Is this book's money in the tail?** In dollars, yes - 57.3% of gross profit in
the top 5% of closes, 45.4% counting the half the journal was losing, and 30.2%
of it in one trade. In R, no: 35.7%, which is inside what a *normal*
distribution with the same moments produces, and the largest R on the book is
+2.429. The dollar tail is the position sizer, not the trades. Re-price the same
book at one flat size and the top 5% carry 34.9%.

**Is the tail being cut off?** The little of it that exists, yes - the 19 closes
that got furthest in front peaked at +1.881R and kept **3.2%** of it, and three
trades between 2.3R and 4.3R in front came back and paid a full stop. But it is
not the clock: the biggest realised winners end on their **target** 71.9% of the
time and are shorter than the book's median, and removing the hold cap in the
replay is worth +0.002R. The give-back happens through the stop, in front of the
target, which is where `giveback.md` and `exiting.md` already pointed - and both
already record the two arithmetic fixes the live distribution supports.

**Would a deliberately convex policy do better?** No. It loses in the discovery
half, wins in the verify half, reverses within one of five entry timeframes, and
its entire magnitude is the stop denominator: divide the stop by three and the
mean moves by three, in whichever direction that window already pointed. At a
constant stop the convex shape is worth +0.009R pooled and flips sign across the
split. The shape change it buys is real and large - the 95th percentile goes
from +2.44R to +9.44R and the win rate from 58% to 38% - and it is priced at
fair value or slightly worse, because the tail cannot be selected for at order
time and the spread on a half-width stop is charged twice.

**The thesis was that this desk is paying for accuracy it cannot buy. That is
right.** The correction proposed - buy convexity instead - assumes there is a
directional edge to be shaped, and the measurement on this page says there is
not one to shape. Convexity is a lever, not an engine. The desk's problem is
still the engine.
