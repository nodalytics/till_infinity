# Compounding a small account: what the arithmetic demands

The owner's goal is a desk that trades on its own and turns a small account into
a large one. This is not another search for edge - `winning.py` and a dozen
harnesses beside it do that. This asks the question underneath: **given an edge
of size X with this book's shape, what risk fraction turns it into a multiple,
and what kills it?** The answer decides which edges are worth chasing and how
much size any of them may be given.

`research/harness/compounding.py`. Every path resamples the **live** R
distribution; nothing is drawn from a normal, because the weight of the left
tail and the thinness of the right one is precisely what a normal throws away
and precisely what decides this question.

## The answer, before the tables

**There is no edge to size.** Over 398 attributed closes the book's mean is
**-0.1354R**, with a bootstrap 95% interval of **[-0.2082, -0.0595]** that does
not touch zero. The growth-optimal fraction on that distribution is **exactly
zero**, in 100% of 2,000 bootstrap resamples. So the safe risk fraction at the
measured edge is *not* 0.25% or 0.1%; it is **nothing**, and the 0.25% that
ships is not a small bet on an edge, it is a slow bet against one: over 1,000
trades - forty days at the observed rate - the median path ends at **0.711x**.

Everything below therefore answers the question in its hypothetical form, which
is the useful one: *if* an edge of size X arrives, what may it be sized at. Two
results are worth stating before any table:

1. **A surprisingly small edge is enough.** A **broad +0.05R** a trade, held to
   a 5% chance of halving over any 1,000 trades, sizes at **f = 0.0129** and
   reaches 100x in a median **1.2 years** at 25 closes a day. The goal does not
   need a spectacular edge. It needs a real one.
2. **Knowing you have it is the expensive part.** +0.05R takes **1,600 trades**
   - 64 trading days - before an honest one-sided test can reject zero. The
   whole record is 398. And at +0.02R, which still compounds 100x in 4.5 years,
   the sample needed is **9,600 trades** - by which point, at the fraction that
   edge supports, the account has already **quadrupled** without the edge ever
   having been established.

## The record

| | n | share |
| --- | ---: | ---: |
| `kind='outcome'`, attributed to a decision | 398 | 57.8% |
| `observation` carrying `unattributed` | 290 | 42.2% |

R is reconstructed as `(exit - entry) * side / risk` on every row rather than
read from `r_multiple`, which 118 of the 398 outcomes predate. The two agree to
**5e-5** on the 280 rows carrying both, so the reconstruction is the same
quantity and not a proxy.

15 trading days, 2026-08-26 to 2026-09-11. `eef4912` landed at 12:37 on the last
of them, so only **2 of 290** unattributed closes carry R yet; a re-run in a week
answers the next section directly instead of by proxy.

## The missing 42% does not change the sign

The unattributed half cannot supply R, but both halves carry `profit`. Scaled by
the median implied money at risk per trade (**$20.70**, p25 $15.18, p75 $25.34,
over 301 rows carrying both profit and R - which puts the account near $8,300 at
the shipping 0.25%):

| | n | total | mean | on the R scale | win |
| --- | ---: | ---: | ---: | ---: | ---: |
| attributed | 398 | **-732.25** | -1.840 | **-0.089** [-0.224, +0.105] | 45.5% |
| unattributed | 290 | **-508.75** | -1.754 | **-0.085** [-0.173, +0.002] | 49.0% |
| union | 688 | **-1,241.00** | -1.804 | **-0.087** | 47.0% |

The two populations are **the same book**: -0.089 against -0.085 on one scale.
The bias in what goes missing is real and visible - median hold **508s against
1,207s**, and 13.8% over half an hour against 33.1% - but it is a bias in
*duration*, not in *outcome*. Including the missing half does not change the
sign, the magnitude, or any conclusion in this document.

## Days cluster, and the simulation has to

The desk runs up to four positions at once on instruments that share factors, so
a bad hour is several trades rather than one. That is testable: the between-day
sum of squares is **23.21** against a shuffled null of **7.99 ± 3.06**,
**p = 0.001**. Days cluster.

| day | n | mean R | | day | n | mean R |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| 08-26 | 10 | +0.076 | | 09-03 | 39 | -0.080 |
| 08-27 | 34 | **-0.666** | | 09-04 | 40 | -0.205 |
| 08-28 | 64 | -0.195 | | 09-05 | 11 | -0.164 |
| 08-30 | 13 | +0.354 | | 09-07 | 1 | -0.009 |
| 08-31 | 21 | -0.081 | | 09-08 | 6 | -0.210 |
| 09-01 | 14 | -0.408 | | 09-09 | 15 | -0.289 |
| 09-02 | 56 | -0.203 | | 09-10 | 14 | +0.030 |
| | | | | 09-11 | 60 | **+0.216** |

Day means average **-0.1223 ± 0.2468**.

Four days of fifteen are positive. So every ruin figure is reported three ways:

* **iid** - resample single trades. The optimistic bound, and what every
  textbook ruin formula silently assumes.
* **day** - resample whole days, each day's trades in order and together.
* **day + halt** - the same with the live 3% daily loss halt applied inside each
  day.

The day scheme resamples **fifteen numbers**. That is its limitation and it is
not a small one: it is the right shape of answer measured on a thin sample, and
the truth sits between the iid column and the day column rather than on either.

## The distribution

| | |
| --- | ---: |
| n | 398 |
| mean | **-0.1354R** |
| median | -0.0656R |
| sd | 0.7558 |
| skew | +0.684 |
| kurtosis | 4.86 |
| win rate | 45.5% |
| 95% CI on the mean | **[-0.2082, -0.0595]** |
| P(mean > 0) | 0.02% |

p5 = -1.07, p25 = -0.92, p50 = -0.07, p75 = +0.29, p95 = +1.00, p99 = +2.07.

The worst close on record is **-2.285R**. That is a hard ceiling on sizing that
has nothing to do with edge: **no risk fraction at or above 0.438 survives a
repeat of a trade that has already happened.** And full Kelly sits right against
that wall: for a +0.30R edge it is **0.500 against a ceiling of 0.541**, which
means one repeat of the worst close on record costs **92.6% of the account in a
single fill**. That is the first reason full Kelly is wrong here, and it is
arithmetic rather than temperament.

| strategy | n | mean | median | sd | win | 95% CI | Kelly |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| thesis-only | 190 | -0.1067 | -0.0088 | 0.668 | 49.5% | [-0.200, -0.012] | 0.000 |
| **sweep-aware** | 87 | **+0.0845** | +0.0553 | 0.891 | 56.3% | [-0.098, +0.276] | 0.119 |
| runner | 33 | -0.2646 | -0.1987 | 0.589 | 33.3% | [-0.462, -0.064] | 0.000 |
| snap | 29 | -0.3407 | -0.5542 | 0.792 | 27.6% | [-0.610, -0.044] | 0.000 |
| fade-to-value | 25 | -0.4377 | -1.0000 | 0.708 | 28.0% | [-0.700, -0.158] | 0.000 |
| confluence-scalp | 11 | -0.4189 | -0.0660 | 0.578 | 27.3% | [-0.740, -0.097] | 0.000 |
| inverse | 6 | -0.6389 | -1.0353 | 0.693 | 33.3% | [-1.086, -0.088] | 0.000 |

One strategy of seven has a positive point estimate and its interval covers
zero. It is sized further down, because that is the real question and refusing
to ask it is not the same as answering it.

## Ruin and growth, over 1,000 trades

Barrier is **first passage** to half the starting equity, not the endpoint: a
path that halves at trade 300 and recovers by trade 1,000 has ruined, because
the account would have been stopped by then - by the halt, by the broker, or by
the owner. Scoring the endpoint is the commonest way a compounding study
flatters itself.

**At the measured edge** (-0.1354R):

| f | iid | day | day+halt | median x | p5 x | g/trade |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **0.0025** (ships) | 0.00% | **0.10%** | 0.00% | **0.711** | 0.590 | -0.00034 |
| 0.0050 | 50.2% | **52.7%** | 0.59% | 0.503 | 0.346 | -0.00069 |
| 0.0100 | 99.9% | 95.2% | 11.0% | 0.250 | 0.118 | -0.00139 |
| 0.0200 | 100% | 99.5% | 9.1% | 0.059 | 0.013 | -0.00283 |
| 0.0500 | 100% | 100% | 11.4% | 0.001 | 0.000 | -0.00752 |

The shipping fraction is the only one on this table that does not destroy the
account inside forty days, and it still ends at 0.711x at the median. **Double
it and the book halves more often than not.** That is what "better sizing of a
signal with no edge scales the loss rather than fixing it" - `scaling.py`'s own
docstring - looks like with a number on it. All four multipliers in that module
are still correctly off.

**At a hypothetical broad +0.05R**, the same table:

| f | f/Kelly | iid | day | day+halt | median x | p5 x |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0025 | 0.03 | 0.00% | 0.00% | 0.00% | 1.130 | 0.937 |
| 0.0100 | 0.11 | 0.00% | 1.4% | 0.00% | 1.597 | 0.756 |
| 0.0200 | 0.22 | 0.25% | 13.7% | 0.00% | 2.411 | 0.542 |
| 0.0500 | 0.55 | 14.2% | 46.6% | 0.38% | 5.979 | 0.144 |
| 0.1000 | 1.10 | 50.6% | 68.3% | 8.3% | 9.223 | 0.005 |

**And at a broad +0.10R:**

| f | f/Kelly | iid | day | day+halt | median x | p5 x |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0025 | 0.01 | 0.00% | 0.00% | 0.00% | 1.281 | 1.062 |
| 0.0100 | 0.05 | 0.00% | 0.10% | 0.00% | 2.623 | 1.249 |
| 0.0200 | 0.11 | 0.00% | 2.6% | 0.00% | 6.500 | 1.478 |
| 0.0500 | 0.27 | 1.0% | 22.0% | 0.18% | 70.99 | 1.768 |
| 0.1000 | 0.54 | 13.1% | 40.2% | 3.7% | 1,299 | 0.826 |

**A shade over half Kelly puts a 40% chance of halving inside forty days.** That
is the second reason, and it is the one that matters at realistic fractions: at
f/K = 0.54 the median path is a 1,299x and the 5th percentile is 0.826x. That is
not a strategy, it is a lottery ticket with a good expectation, and the owner
only gets to buy one.

### The daily halt is a brake at small f and a ratchet at large f

Read the `day+halt` column carefully. It is not monotone - at the measured edge
it goes 11.0%, 9.1%, 11.4% across f = 0.01, 0.02, 0.05 - and the mechanism
matters. A 3% daily halt cannot refuse a trade it has already taken: at f = 0.05
a single -1R close is -5%, which breaches the limit on the *first* loss and
stands the desk down for the rest of the day. It banks the loss and forfeits the
recovery. `plans.standard` is built around **twelve losses to a halt**
(0.03 / 0.0025); at f = 0.03 that number is one, and the halt stops protecting
and starts cutting days short after the loss and before the rebound.

## The same mean, broad or in a tail

`research/exiting.md` (2026-09-11) found that once two look-aheads came out of
the replay, ride's exit beat the shipping one by **+0.432R → +0.046R**, its
median fell from **+0.498R to +0.133R**, and it was **worse on 64% of the same
trades** - an edge living entirely in a thin right tail. That is a different risk
object from a broad edge of the same mean, and here is how different.

`tail s` takes the edge off *every* trade and gives it back only to the best `s`
of them, so `1 - s` of trades are worse than having no edge at all and the mean
is unchanged. `s = 0.36` is exiting.md's shape.

**At +0.10R per trade, every row:**

| shape | sd | median R | win | Kelly | ruin @0.02 | ruin @0.05 | median x @0.02 | p5 @0.02 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **broad** | 0.756 | +0.170 | 59.5% | **0.186** | **2.6%** | 22.1% | 6.60 | 1.416 |
| tail 0.36 | 0.972 | -0.030 | 47.7% | 0.112 | 10.0% | 38.1% | 6.14 | 0.916 |
| tail 0.10 | 1.222 | -0.030 | 47.7% | 0.078 | 15.3% | 49.3% | 5.37 | 0.671 |
| tail 0.02 | 1.876 | -0.030 | 47.7% | **0.040** | **38.8%** | 74.3% | 3.64 | 0.237 |

**The same +0.10R mean is worth a 0.186 Kelly fraction broadly and a 0.040 one in
a 2% tail - a factor of 4.6.** At a fixed f = 0.02 the chance of halving inside
forty days goes from 2.6% to 38.8%, fifteen times worse, at *identical expected
return per trade*. At +0.20R the gap is wider still: Kelly 0.374 broad against
0.032 at `tail 0.02`, and the 5th-percentile path at f = 0.02 falls from 10.4x
to 0.16x.

So the sizing that is safe for one is emphatically not safe for the other, and
the mean alone is not enough information to size a trade. **An edge should be
reported with the share of trades that carry it**, or it cannot be sized.

## What the goal costs, in trades and in calendar

First passage to a multiple, 25 closes a day, 252 days a year. `ruin1st` is the
share of paths that halved *before* ever touching the target.

| edge | f | f/K | 10x: trades / yrs | 100x: trades / yrs | 1000x: trades / yrs | ruin first |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +0.02 | 0.0025 | 0.07 | 41,416 / 6.6 | 55,348 / 8.8 (3.5% reach) | - | 0.9% |
| +0.02 | 0.0089 | 0.25 | 12,000 / 1.9 | 25,842 / 4.1 | 37,950 / 6.0 | **26.4%** |
| +0.05 | 0.0025 | 0.03 | 18,244 / 2.9 | 36,850 / 5.8 | 53,332 / 8.5 | 0.0% |
| +0.05 | 0.0228 | 0.25 | 1,922 / 0.3 | 4,171 / 0.7 | 6,335 / 1.0 | **24.6%** |
| +0.10 | 0.0025 | 0.01 | 9,182 / 1.5 | 18,446 / 2.9 | 27,702 / 4.4 | 0.0% |
| +0.10 | 0.0466 | 0.25 | 495 / 0.1 | 1,062 / 0.2 | 1,613 / 0.3 | **19.9%** |
| +0.10 | 0.0931 | 0.50 | 267 / 0.0 | 562 / 0.1 | 832 / 0.1 | **38.8%** |
| +0.20 | 0.0936 | 0.25 | 138 / 0.0 | 273 / 0.0 | 413 / 0.1 | 14.0% |

**Quarter Kelly loses half the account before reaching the target between one
time in four and one time in twelve** - 26.4% at +0.02R, 24.6% at +0.05R, 19.9%
at +0.10R, 14.0% at +0.20R, 8.3% at +0.30R. The fraction scales with the edge, so
most of the extra edge is spent buying size rather than safety. Half Kelly runs
one in two to one in five. The shipping 0.25% never ruins on any of these
distributions and reaches 100x in 1.0 to 8.8 years depending on the edge.

That is the compounding arithmetic in one table, and it is why the median path
is not a plan. At +0.05R and quarter Kelly the median reaches 100x in eight
months; a quarter of those accounts are half gone first.

## How many trades before this record can decide anything

Power to reject "mean R ≤ 0" at 95% one-sided, resampling the measured shape.

| edge | shape | sd | normal n | resampled n (80% power) | days at 25/day |
| ---: | --- | ---: | ---: | ---: | ---: |
| +0.02 | broad | 0.756 | 8,833 | **9,600** | 384 |
| +0.05 | broad | 0.756 | 1,413 | **1,600** | 64 |
| +0.10 | broad | 0.756 | 353 | **400** | 16 |
| +0.20 | broad | 0.756 | 88 | 100 | 4 |
| +0.05 | tail 0.10 | 0.971 | 2,332 | 2,400 | 96 |
| +0.10 | tail 0.36 | 0.972 | 584 | 600 | 24 |
| +0.10 | tail 0.10 | 1.222 | 923 | **1,200** | 48 |
| +0.10 | tail 0.02 | 1.876 | 2,178 | 2,400 | 96 |
| +0.20 | tail 0.02 | 3.222 | 1,605 | 1,600 | 64 |

**The variance that made a tail edge dangerous to size is the same variance that
hides it.** A +0.10R edge is confirmable in 400 trades if it is broad and needs
1,200 if a tenth of trades carry it - so the shape penalises twice, once in what
may be risked and once in how long before anyone may risk it.

The record is **398 attributed closes**. It can, just, detect a broad +0.10R. It
cannot detect anything smaller, and it certainly cannot detect a tail-shaped
edge of any realistic size.

## The one strategy with a positive point estimate, sized

`sweep-aware`: **n = 87 over 5 days, mean +0.0845R, sd 0.891**, Kelly on the
point estimate **0.119**.

| f | iid | day | median x | p5 x | g/trade |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0025 | 0.00% | 0.00% | 1.238 | 1.058 | +0.00021 |
| 0.0100 | 0.00% | 0.08% | 2.280 | 1.219 | +0.00082 |
| 0.0200 | 0.07% | 3.2% | 4.811 | 1.374 | +0.00157 |
| 0.0500 | 6.8% | 24.4% | 29.01 | 1.241 | +0.00337 |
| 0.1000 | 35.3% | 51.2% | 141.5 | 0.242 | +0.00495 |

Read against the bottom of its own interval: **the 5th percentile of the
bootstrap mean is -0.0673R**, where Kelly is **0.000** and **f = 0.01 halves the
account 56.9% of the time over 1,000 trades**.

That is the whole study in one strategy. The same 87 closes support either
f = 0.119 or f = 0, and the downside branch destroys the account at a twelfth of
the upside branch's fraction. **87 trades cannot size anything.** At its own mean
and its own spread the sample needed is about **800 closes** - nine times the
record, and about two months at its own recent rate of 17 closes a day. That is
the whole prescription for it: leave it alone and let it run.

### Why this reads +0.0845R where edge.md reads +0.154R

[edge.md](edge.md) measures the same strategy at **+0.154R over 77 closes**.
Both numbers are right and the difference is exactly reconstructible: that 77 is
the 75 attributed closes carrying a stored `r_multiple` plus the 2 unattributed
ones that now carry it. Their mean is +0.1536, which rounds to edge.md's figure.

The 12 closes it leaves out are the ones that predate the `r_multiple` field.
They are all from **08-26 and 08-27** - the first two days on the record, and
08-27 is the worst day the book has had at -0.666R - and they average
**-0.444R**. Reconstructing R from prices recovers them, which is why this page
reads 87 closes and a lower mean.

Neither reading is a correction of the other. One is the strategy since its
third day, the other is the strategy since its first, and **the interval covers
zero on both**. That two defensible readings of the same record differ by 0.07R
- half the distance from the whole book to break-even - is the point.

(The `day + halt` column is omitted for `sweep-aware`: with five day-blocks the
halted day outcomes are five fixed numbers, and the column reads 100% at
f ≥ 0.10 for that reason rather than for a market one.)

## The table to act on

The largest risk fraction whose probability of halving over 1,000 trades stays
inside a budget, found by bisection on the day-block scheme, and what that
fraction then buys. **This is the deliverable.**

**Ruin budget: P(halve within 1,000 trades) ≤ 5%**

| edge | Kelly | safe f | f/Kelly | g/trade | median x (1,000 trades) | p5 x | 100x in |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **measured (-0.135R)** | 0.000 | **none** | - | - | - | - | **never** |
| 0.00R | 0.000 | **none** | - | - | - | - | never |
| +0.02R | 0.036 | 0.0094 | 0.26 | +0.00016 | 1.16 | 0.58 | 4.5 yr |
| +0.05R | 0.091 | **0.0129** | 0.14 | +0.00060 | 1.79 | 0.69 | **1.2 yr** |
| +0.10R | 0.186 | 0.0234 | 0.13 | +0.00219 | 8.67 | 1.53 | 0.33 yr |
| +0.15R | 0.282 | 0.0398 | 0.14 | +0.00552 | 238 | 12.6 | 0.13 yr |
| +0.20R | 0.374 | 0.0562 | 0.15 | +0.01032 | 28,480 | 465 | 0.07 yr |

**Ruin budget: ≤ 1%** - the same shape, a third smaller:

| edge | safe f | f/Kelly | 100x in |
| --- | ---: | ---: | ---: |
| +0.02R | 0.0070 | 0.20 | 5.8 yr |
| +0.05R | 0.0082 | 0.09 | 1.9 yr |
| +0.10R | 0.0152 | 0.08 | 0.50 yr |
| +0.20R | 0.0305 | 0.08 | 0.13 yr |

**The safe fraction is about an eighth to a quarter of Kelly, not a half.** That
ratio is stable across every edge size, which makes it the one number to
remember: the literature's "half Kelly is conservative" is calibrated on iid
draws from a thin-tailed distribution, and this book is neither. Every figure
above should be cut again if the edge turns out to be tail-shaped: a `tail 0.10`
edge sizes at **63% of its broad equivalent at +0.05R, 42% at +0.10R and 23% at
+0.20R** - the penalty grows with the edge, because a larger mean squeezed into
the same thin tail is a larger variance.

## What edge the goal actually requires

Put the pieces together.

* A **broad, sustained +0.05R per trade**, sized at **f = 0.0129** - about five
  times the shipping 0.25% - compounds 100x in a median 1.2 years at 25 closes a
  day, with a 5% chance of halving in any 1,000-trade stretch. That is the
  threshold at which the goal stops being hopeful and becomes arithmetic.
* The book is at **-0.1354R**. The distance to that threshold is **+0.185R per
  trade**, not +0.05R. That is the number the search for edge is actually
  chasing, and it is worth writing down: it is **four times** exiting.md's
  corrected +0.046R, which is the best-evidenced change this folder has produced.
* The best-evidenced single improvement on record is exiting.md's corrected
  **+0.046R** - a quarter of the gap - and it is `tail 0.36` shaped, so it would
  carry about **three quarters** of the size a broad edge of the same mean could
  (Kelly 0.070 against 0.091 at +0.05R).
* **Even at +0.05R the sample is the binding constraint, not the edge.** 1,600
  trades to confirm it, against 398 on the whole record; 64 trading days at the
  current rate, and that assumes the strategy list and the exits stop changing
  underneath the sample, which in this record they never have.

So the honest reading is that the goal is **reachable at a modest edge and
unreachable on this evidence**, and the binding constraint is neither sizing nor
ambition. It is that the desk has never run one configuration long enough to
measure it. **The single highest-value change available is not a better edge or
a better fraction - it is holding the strategy list, the exits and the risk
settings still for 1,600 closes.** Until then every sizing question has the same
answer, which is the shipping 0.25% or less, and every table above is a
contingency plan.

## What is not modelled

* **Simultaneity.** Trades inside a day are compounded in sequence. With
  `max_positions = 4` the real book has up to four positions against the same
  equity at once, which is worse than sequential and not captured beyond what
  the day blocks carry.
* **Fifteen days.** The day scheme resamples fifteen numbers, and the halt
  variant resamples fifteen deterministic halted-day outcomes. The clustering
  is real (p = 0.001); its magnitude is measured on a thin sample.
* **A stationary edge.** Every hypothetical shifts the measured *shape* to a new
  mean and holds it there for up to 60,000 trades. The record is 15 trading days
  and the strategy list changed inside it more than once.
* **Sizing friction.** `lots()` rounds to the broker's volume step and
  `min_stop_vol`, `max_spread_fraction` and the currency cap refuse trades, so
  realised risk is not exactly `f` of equity. `sizing.py` already inflates the
  stop distance by a measured 0.087 slippage; that is inside the realised R here
  and is not double-counted.
* **The barrier is a fixed fraction of starting equity**, not a high-water-mark
  drawdown. A book that triples and then loses 60% is not counted as ruined.
* **The money-scale comparison** assumes a constant implied risk per trade.
  `risk_money` is 0.0 on 134 of 398 outcomes and equity moved over the period.
* **The journal copy.** The research machine's replica lagged production by a
  day - 325 attributed closes against 398, missing the day `sweep-aware` went
  from 16 closes to 87. Both were run. The replica reads mean **-0.2054R** where
  the fresh copy reads -0.1354R; every conclusion here holds on both, and the
  mean moving by 0.07R on one extra day of data is itself the best argument in
  this document for holding a configuration still and letting the sample grow.

## Related

* [edge.md](edge.md) - does this desk have an edge and what sign is it. The
  sizing question this page answers is downstream of that one, and the two read
  `sweep-aware` differently for a reason worth knowing.
* [exiting.md](exiting.md) - where the tail-shaped edge comes from, and the two
  look-aheads that inflated it tenfold.
* [convexity.md](convexity.md) - the tail of this same book measured directly,
  rather than imposed on it as a hypothetical shape.
* [giveback.md](giveback.md) - the live `best_r` record, and the unattributed
  population this document re-reads.
* [horizon.md](horizon.md) - no demonstrated directional edge at the horizon the
  desk trades, which is the premise the ruin tables measure the cost of.
* `till_infinity/trading/scaling.py` - four sizing multipliers, all off. This
  document is the arithmetic behind keeping them off.
