# What makes a trade win, and can winning be made consistent

Asked directly: *"what patterns make our trades win, and how do we make winning
consistent?"*

Answered from the live journal rather than a replay, because
[specs/2026-09-11-live-crosscheck-design.md](specs/2026-09-11-live-crosscheck-design.md)
records why: the only harness that could simulate this exits 98% by stop where
the desk exits 13%, and [exiting.md](exiting.md) records two look-aheads that
moved a replayed answer tenfold in a single morning. The live record is small.
It is also the only thing here that has not been caught lying.

`research/harness/winning.py`. **685 closes: 397 journal `outcome` rows and 288
`unattributed` observations.**

**The short answer is a null.** Nothing the desk knows at the moment it places
an order separates its winners from its losers, once the scan is measured
against its own noise floor. One thing does — how much of the trade's own risk
the spread eats — and that was written down *before* this run, by a replay, and
has already been gated away by the desk's own settings. What is left is not a
pattern but arithmetic: stops at 21.9% of closes costing −1.059R against
targets at 20.4% paying +0.661R, and **54% of the book ending at approximately
zero**.

## Two populations, and the one that is missing its arithmetic

A close reaches the journal as an `outcome` if the position still had its
`_refs` link to the decision that opened it, and as an `unattributed`
observation if it did not — which happens when the position outlives a restart.

| | n | carries |
| --- | ---: | --- |
| `kind='outcome'` | 397 | entry, stop, target, and every level feature the trade was born from |
| `unattributed` observations | 288 | profit, seconds, exit kind, strategy, feed |

**`eef4912` was supposed to fix the second row and is not running.** It adds
`r_multiple`, `best_r`, `entry`, `stop` and `exit_kind` to a parentless close.
The production image is `0afa0ca`, one commit behind it, so **zero of the 288
carry R**. The harness checks this and says so at the top of its output rather
than assuming the enrichment landed. Every R figure below is therefore the
attributed half; every money figure is reported both ways.

The loss is not random and the size of it has grown since it was first
measured. Over the window where both kinds exist:

| | n | median hold | over 1800s | exit mix |
| --- | ---: | ---: | ---: | --- |
| attributed | 249 | 690s | 14% | hold 53% target 21% stop 16% stale 10% |
| **unattributed** | **288** | **1216s** | **33%** | hold 42% target 25% stop 25% stale 8% |

**54% of closes in that window are unattributed** — worse than the 43% recorded
on one day in [giveback.md](giveback.md). Reading only the attributed half is
reading the short trades, and §4 is what that costs.

R is **recomputed** rather than read: `r_multiple` is absent on 118 of the 397
rows, and on the 279 that carry it the field equals
`(exit − entry) × side / risk_price` to within 5×10⁻⁵. `profit / risk_money` is
*not* the same quantity — it carries slippage, commission and swap, and differs
by a median 0.042R — so it is used for money and never for R.

## 1. The book is arithmetic, not selection

| exit | share | mean | median | contributes |
| --- | ---: | ---: | ---: | ---: |
| hold (the timeout) | 45.1% | −0.022R | −0.010R | −0.010R |
| stop | 21.9% | **−1.059R** | −1.025R | **−0.232R** |
| target | 20.4% | **+0.661R** | +0.460R | **+0.135R** |
| stale | 8.6% | −0.225R | −0.137R | −0.019R |
| unrecorded | 4.0% | −0.237R | −1.000R | −0.010R |
| | | | | **−0.136R** |

That is the whole book. Targets and stops happen at almost the same rate and
the stop is 1.6 times the size, and more than half of everything ends within
noise of zero after paying the spread to get there.

It also sets the scale of any fix. To flatten the book you need **52 of the 87
stops to become timeouts, or 79 of the 179 timeouts to become targets.** Not a
threshold tweak — 60% and 44% of those populations respectively.

## 2. The scan, and what its own noise floor says

397 closes, 43 decision-time features with enough coverage to tercile, split
**60/40 by time** — propose on the first 238, dispose on the last 159. Bucket
edges are set on the discovery half only, so the verify half never touches the
cut that describes it. Three directional fields (`edge`, `expected_push_vol`,
`probability_up`) are re-expressed relative to the trade, because their median
is +0.32 on a buy and −0.28 on a sell: a tercile of the raw field is a tercile
of `side`.

**Declared before the run.** A feature is reported only if (1) its discovery
gap beats what the control produces for the *best* of the same features on
shuffled outcomes, (2) its ordering survives into verify, (3)
`strata.compare` flags no reversal within strategy or interval, and (4) it
survives removal of the single best trade. A null was the expected result.

**The control is the whole scan on shuffled outcomes, 300 times.** What matters
is not one feature's gap but the largest gap across all of them, because that
is what the eye picks out — the lesson of [generated.md](generated.md), where
the biggest correlation in a 325-pair study was between two unrelated
instruments.

| target | biggest real gap | control median | control p95 | control max | clears |
| --- | ---: | ---: | ---: | ---: | --- |
| R | 0.433 (`break_probability`) | 0.374 | 0.544 | 0.683 | **none** |
| P(stop) | 0.358 (`spread_over_risk`) | 0.203 | 0.297 | 0.382 | `spread_over_risk`, `stop_vol` |
| P(R>0) | 0.302 (`confluence_n`) | 0.245 | 0.345 | 0.427 | **none** |

And the second control, which is the more damning one. 24 of 43 features held
the sign of their discovery ordering into the verify half. **Shuffled outcomes
produce a median of 22 and a p95 of 28.** Surviving a split sample is what a
feature does by chance here; 24 is not evidence of anything.

On R — the quantity the desk is actually paid in — **nothing clears**. The
largest gap in the whole feature set is smaller than the median gap the same
scan finds in pure noise.

### And the ones that looked best do not survive conditioning either

`strata.compare` within strategy and interval, on the four largest by R:

| feature | pooled reads | reversed in |
| --- | --- | ---: |
| `break_probability` | high > mid | **3 of 5** |
| `liquidity_beyond_n` | mid > high | 2 of 5 |
| `liquidity_beyond_vol` | high > mid | 2 of 5 |
| `confluence_n` | high > mid | 0 of 4 |

`confluence_n` is the only one that holds its ordering, and its gap (0.356) is
below the noise floor's median (0.374). A pattern that only exists pooled is a
composition; a pattern that survives conditioning and not the control is noise
that happened to be consistent.

`stop_vol`, which cleared the P(stop) control, **reverses in 4 of 5 strata** and
is dropped. It is also Spearman −0.46 against the one thing that does survive,
for a mechanical reason: a narrow stop makes the spread a larger share of the
risk. It is the same finding read off a different axis.

## 3. The one hypothesis that was written down first

[exiting.md](exiting.md) decomposed a replay and concluded, before any of this:
*"Refuse a setup whose spread is too large a share of what it is reaching
for."* That is a pre-registered contrast, so it is not judged against the
max-of-43 null, which is the wrong test for a hypothesis nobody went looking
for.

`spread_at_entry / risk_price`, by decile of the live book:

| decile | ≤ | n | mean | median | stopped |
| --- | ---: | ---: | ---: | ---: | ---: |
| d1–d8 | 0.162 | 304 | −0.060R | +0.012R | 16% |
| **d9** | 0.290 | 38 | **−0.396R** | −0.545R | **42%** |
| **d10** | 1.181 | 38 | **−0.473R** | −1.000R | **55%** |

It is a threshold, not a gradient. Below ~0.16 there is no ordering worth
reading; above it the stop rate triples.

**Cheap minus expensive: +0.369R.** Permuted *within feed* 2,000 times — so an
effect that is really an instrument cannot survive as an effect about trades —
the null's p95 is +0.273 and p99 is +0.314. **p < 0.001.**

What it survives:

| | |
| --- | ---: |
| as measured | +0.369R |
| minus the +622.63 trade | +0.366R |
| minus the best R (+3.73) | +0.356R |
| minus the worst R (−2.28) | +0.376R |
| minus every gold trade | +0.295R |
| non-synthetic book only (n=168) | +0.374R |

And the conditioning. `strata.compare` on three buckets flags reversals in 2 of
5 strata — but in both cases the reversal is between `low` and `mid`, which are
0.008R apart pooled, while `high` is the worst bucket in **5 of 5**. On the
binary cut that was actually proposed, **cheap beats expensive in 9 of 9 strata
with five trades on each side**, and in 4 of 5 days with five on each side.

### The gate that ships measures the wrong denominator

`risk.py` refuses an entry when `spread / reward` exceeds
`max_spread_fraction`, which is 0.25 in production. The damage is measured
against the **risk**. Those are different trades:

| | n | mean | stopped | money |
| --- | ---: | ---: | ---: | ---: |
| passes the gate, cheap against risk | 292 | −0.065R | 17% | +30.71 |
| **passes the gate, expensive against risk** | **49** | **−0.471R** | **53%** | **−502.70** |
| over the gate, cheap against risk | 11 | +0.070R | 9% | +17.72 |
| over the gate, expensive against risk | 28 | −0.356R | 39% | −211.72 |

**49 trades passed the live gate and sat in the damaging group, for −502.70.**
The mechanism is not subtle: the gate scales the permitted spread with the
*target*, so a distant target buys the right to pay more — and a spread that is
half the stop distance is half the stop distance regardless of where the target
is.

### Why this changes almost nothing going forward

Threshold set on the discovery half alone (p80 = 0.2026) and applied out of
sample:

| | over the line | under | gap |
| --- | --- | --- | ---: |
| discovery | n=45, −0.435R | n=183, −0.155R | +0.280R |
| verify | **n=4**, −0.120R | n=148, −0.020R | +0.100R |

**The verify half cannot test it, because the population is gone.** Expensive
trades were 79%, 50% and 67% of closes on 08-27, 08-28 and 08-31, and 5% of the
last seven days. The desk stopped taking them — a settings change, an
instrument list that moved toward synthetics, or both. So this is a **confirmed
diagnosis of a historical loss, not a live edge**, and the only thing to act on
is the denominator.

## 4. The trap: holding time, and what the missing half does to it

This is the part worth reading, because it went wrong first.

Holding time looks like the strongest cohort separator on the book, and it gets
*stronger* when the unattributed half is added:

| | 0–2m | 2–10m | 10–30m | 30m+ |
| --- | ---: | ---: | ---: | ---: |
| attributed, R | −0.366 | −0.118 | −0.150 | **+0.070** |
| attributed, money | −5.40 | −1.22 | −3.96 | +0.18 |
| **union, money** | −7.46 | −2.54 | −3.21 | **+1.77** |

Against a within-strategy permutation null, 30m+ beats the rest by **+0.239R
(p=0.0010)** on the attributed half and by **+5.01 a close (p<0.0005)** on the
union. On money it is *only* significant on the union — the attributed half
alone gives p=0.115 — because the attributed half holds 14% long trades where
the unattributed half holds 33%. Within every one of the six days with enough
closes, the 30m+ bucket beats the rest.

It is entirely the stop.

| exit | 0–2m | 2–10m | 10–30m | 30m+ |
| --- | ---: | ---: | ---: | ---: |
| stop | −1.125 | −1.064 | −1.075 | −0.376 |
| target | +0.654 | +0.484 | +0.739 | +1.448 |
| hold | −0.224 | +0.017 | −0.002 | −0.060 |

**Remove the stops and the ordering reverses: 30m+ minus the rest is −0.033R,
p=0.63.** Short trades lose because a stop is what closes a trade quickly. The
clock was the stop rate wearing a duration's name — the fifth time a pooled
figure has reversed on this project, after `aligning`, `forecasting`,
`trapping` and `instruments`, and the first one where the missing half made the
composition look *more* significant rather than less.

Duration is co-determined with the outcome, so it is a description of winners
and not a lever. The lever it suggests — raise `max_hold` — cannot be tested
from this record at all, because a trade that closed at thirty minutes would
have to be walked forward, and that is the replay whose exit mix does not match
the desk.

## 5. What the missing half changes, and what it does not

Money per close over the window both exist, attributed against union:

| strategy | attributed n | attributed | union n | union |
| --- | ---: | ---: | ---: | ---: |
| **runner** | 9 | **+4.15** (best) | 23 | **−2.71** (third) |
| sweep-aware | 74 | +2.11 (2nd) | 146 | **+1.76** (best) |
| thesis-only | 139 | −3.13 | 309 | −2.29 |
| fade-to-value | 7 | −21.83 (worst) | 12 | −16.16 |
| level-scalp | 2 | −18.62 | 5 | −16.89 (worst) |

**Changed by including it:** `runner` goes from the book's best strategy to its
third-worst on 14 more closes. The hold-time result goes from suggestive to
significant — and it was wrong either way, which is its own lesson about what
significance buys.

**Unchanged:** `sweep-aware` is the only strategy positive in either view and is
positive in both. The exit-kind mix differs by at most 11 points on any kind,
against the 25-point threshold the cross-check spec sets, so the
missing half is not a different machine — it is the same machine, sampled
longer. And the `spread_over_risk` result cannot be checked against it at all,
because the unattributed rows carry no entry and no risk.

**The outlier still outweighs the attribution gap.** The attributed book is
−733.29, of which a single `thesis-only` trade on Volatility 75 is **+622.63**
— the trade [instruments.md](instruments.md) already flagged. Without it the
attributed book is −1,355.92 and the union is −1,862.11. That one row moves the
money book by more than the entire 288-close missing half does to any
conclusion here. In R it is +0.70 and utterly ordinary, which is the argument
for reading the R column first, again.

## What this does not say

* **It does not say the features are useless.** It says 397 closes cannot
  resolve a 0.2R effect in a distribution whose standard deviation is 0.756R.
  Discovery buckets hold ~79 trades; the standard error on a bucket mean is
  ~0.09R and on a gap ~0.13R. Anything real and smaller than about 0.4R is
  invisible here, and most real effects are smaller than that.
* **It does not say the exit is fine.** [giveback.md](giveback.md) and
  [exiting.md](exiting.md) show the trail and break-even sitting above the
  distribution they are meant to act on. This asks a different question —
  whether the *entry* can be selected better — and answers no.
* **It cannot see the trades that were refused.** Everything here is closes.
  The risk gates refuse a large population before it becomes a trade, which is
  exactly why the live mean R is not the replayed mean R, and a selection rule
  fitted on survivors is fitted on the wrong sample.
* **The unattributed half is conditioned on surviving a restart**, which is not
  a random event and clusters in time with deploys. Comparing it to the
  attributed half compares eras as much as trades.
* **Money is not normalised.** Position size moved several times over the
  window, so every union figure — which must use money, because the missing
  half has no R — carries the book's sizing history inside it.

## What it would change if acted on

1. **Change the spread gate's denominator.** `risk.py` tests
   `spread / reward`; the measured damage is `spread / risk`. Testing both, at
   0.25 of the reward and roughly 0.16 of the risk, would have refused the 49
   trades that passed the gate and lost 0.471R each. This is the only change
   here with a pre-registered hypothesis, a within-feed null at p<0.001, and
   9-of-9 strata behind it. It is also worth little going forward: the
   population is down from 79% of closes to 5%.
2. **Stop looking for an entry filter in this feature set at this sample size.**
   Three targets, 43 features, a split sample and 300 permutations found
   nothing on R. The next thing that would change the answer is more closes, not
   more features — and at ~40 closes a day, a 0.2R effect needs something like
   1,500 of them.
3. **Deploy `eef4912`.** Not because it changes a conclusion — it did not get
   the chance to — but because the half of the book with the long holds
   currently has no arithmetic at all, and §4 is exactly the kind of question
   that needs it. The next re-run of this page should be able to compute R on
   685 closes rather than 397.
4. **Nothing about holding time.** The strongest-looking result on the page is
   the stop rate, and acting on the clock would be acting on a composition.

Run it:

    JOURNAL=/app/.data/journal/journal.db python research/harness/winning.py
