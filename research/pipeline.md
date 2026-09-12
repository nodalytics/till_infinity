# The middle of Deriv's generator, identified as far as published quotes allow

A synthetic quote is the output of a chain, and until now only its two ends had
been looked at:

    CSPRNG -> uniform u -> inverse-normal Phi^-1(u) -> price recursion -> quantise -> publish
    \______ rebuildpredict.py ______/                                    \_ frac_zero, n_distinct _/

[`rebuildpredict.py`](harness/rebuildpredict.py) attacked the source - k-tuple
spectral tests, MT19937 untempering, truncated-LCG lattice reduction over nine
published parameter sets - and found nothing, which is what a regulated venue
should look like. The three stages in between are **deterministic**, which makes
them a far softer target, and none of them had ever been identified.

This page identifies what can be identified from published quotes, and states
with arithmetic what cannot. Harness: [`pipeline.py`](harness/pipeline.py), and
the generator it is graded against, [`pipesim.py`](harness/pipesim.py), whose
every stage - inverse-normal precision, drift convention, grid, rounding rule,
internal-state architecture, clock - is a parameter with a known value.

## Where this page stands, 2026-09-12

The harness is complete and every test on it is characterised against a
generator whose stages are known. The **authoritative run against all thirty-two
feeds did not complete**: the research lab was unreachable for almost the whole
of the session that produced this page - `No route to host`, with one window
long enough to launch and not long enough to read a log - and the deep tick
pulls it needs are half an hour of a terminal that was not there. That is a
statement about the lab, not about the questions, and the distinction is the
same one this folder insists on everywhere else.

So this page is in two halves, and they are labelled:

| question | status |
| --- | --- |
| 1. is the increment distribution continuous, or a finite set? | battery built, **characterised to 24 bits**, not yet pointed at real feeds |
| 2. which drift convention? | arithmetic settled, estimator validated, **`projection.py` corrected**; pooled history not yet read |
| 3. tick size per feed | **measured**, six feeds |
| 3. rounding mode | **answered: not identifiable**, and that is a theorem |
| 4. does quantisation error accumulate? | predictions derived and validated; **decidable only below `sigma_Y` ~ 4**; real feeds not yet read |
| 5. what is `dt`? | **answered: exactly 2000 ms**, 46 ms jitter, 222 ms offset |
| 6. bits per tick | **measured**, six feeds; rung 2 of `rebuildpredict.py` closed by arithmetic |

One command finishes the other half:

    ./.secrets/lab.sh run research/harness/pipeline.py OMP_NUM_THREADS=8

It takes about an hour, of which half is the terminal, and it writes
`~/till_infinity/logs/pipeline.json` after every section. `WANT=1500000` halves
the tick pull at the cost of about two bits of the atom battery's reach, which
is the trade to make if the lab is flaky again.

## The trap this page is built around, stated before any number

**Quote quantisation alone makes the increment distribution discrete.** Every
published increment on `Volatility 75 Index` is an exact multiple of 0.01, so
"the increments take finitely many values" is true *by construction* and says
nothing whatever about the inverse-normal. The null for question one is
therefore **"discrete because the price grid is discrete"**, not "continuous",
and a test that cannot separate those two produces a spectacular false positive.

Three things follow, all enforced in code rather than argued:

* every statistic is computed on the **implied pre-quantisation** variate `z`,
  reconstructed from the published quotes, with its own resolution carried
  beside it. A published quote pins the internal price to `+- grid/2`, so the
  reconstructed increment carries additive noise of standard deviation
  `grid / sqrt(6)`, which in `z` units is

      eps = 1 / (sqrt(6) * sigma_Y),      sigma_Y = per-tick move in lattice units

  and **no atom finer than `eps` is visible from published quotes at any sample
  size**. `sigma_Y` is the single number that decides how much of the middle of
  this pipeline is visible at all, and it is printed beside every feed;
* every claim is graded on the simulator at the real feed's own price, grid,
  sigma, clock and sample size, **through the identical code path**;
* the continuous-inverse-normal control is run at the same size, **half of it
  sets the bar and the other half measures how often a generator known to be
  sound clears that bar.** That out-of-sample number is quoted beside every
  result.

### The version of the test that was thrown away, and why it is recorded here

The first atom battery set nineteen separate bars - one per bit width - at the
control maximum, and reported a false-positive rate of **zero**. That was true
in sample and meaningless: a fresh continuous draw clears a nineteen-fold
maximum about two runs in six, which the recovery table exposed by "detecting" a
**32-bit uniform**, a generator that is continuous at this resolution by four
decades. The fix is one standardised maximum over bit widths with the null
calibrated on one half of the controls and validated on the other. It is on the
page rather than quietly corrected because a reader is entitled to know which
version of a test produced a number, and because the failure is the exact one
the brief warned about.

## What would have counted as failure, written before any number was looked at

1. **Question 1 dies** - the increments are not continuous - if any leg of the
   atom battery exceeds, on a real feed, the bar set by 32 continuous controls
   at the same price, grid, sigma and sample size.
2. **The run is void** if the battery cannot recover a coarse inverse-normal it
   is shown at every precision the arithmetic says is reachable.
3. **The run is void** if the out-of-sample false-positive rate on the
   validation half is large enough that a firing leg means nothing.
4. **Question 2 is unresolved** unless the pooled separation between the two
   conventions exceeds 3 standard errors, where the separation is
   `sqrt(sum sigma_i^2 T_i) / 2` and depends on **calendar span, not bar count**.
5. **Question 3 is unidentifiable** if the simulator shows the five rounding
   modes producing the same published statistics on paired paths.
6. **Question 4 has no null to defend.** Both architectures are real facts, so
   the requirement is that the two predictions bracket the observation - if they
   do not, the section is uninformative rather than surprising.
7. **Any question the data cannot support is reported as untested**, with the
   sample it would take, and is not counted as an answer.

---

## One: is the increment distribution continuous, or does it live on a finite set?

This is the question the arm exists for. If Deriv's inverse-normal is a lookup
table or a limited-precision approximation then the set of achievable
log-increments is finite and enumerable, and `rebuildpredict.py`'s rung 3 stops
being a lattice reduction and becomes a search over a small set.

Three legs, because the hypothesis has three different shapes and no single
statistic covers them:

* **the cap.** If `u` is a `k`-bit integer over `2**k` then the largest
  reachable normal is `Phi^-1(1 - 2**-k)` **exactly** - a ceiling, not a tail
  property - while `n` continuous draws reach about `Phi^-1(1 - 1/2n)`. The one
  leg a scale error cannot move, and it can only exclude `k <= log2(2n)`.
* **the characteristic function.** A variate on a lattice of spacing `h` has
  `|phi(2 pi / h)| = 1` exactly, where a continuous one is at `1e-9` by
  `w = 6.5`. Scanned by FFT over a fine histogram rather than summed directly -
  three million points at ten thousand frequencies is `3e10` exponentials - with
  the **quote lattice's own frequency and first harmonic cut out of the band**,
  because a peak there cannot be attributed and a `z`-lattice within a few
  percent of the quote grid's own spacing is a blind spot of this leg at any
  sample size.
* **`u`-space, per bit width, with a matched filter.** `Phi(z)` is on a lattice
  of spacing `2**-k` if `u` is `k`-bit. The reconstruction noise in `u` is
  `phi(z) * eps` - four decades smaller at `z = 4.5` than at `z = 0` - so a
  plain average over the tail *dilutes* the signal and each point is weighted by
  its own surviving amplitude instead. The scale of `z` is known only to
  `1/sqrt(2n)` and a scale error is harmless in `z` and fatal in `u`, so the
  scale is scanned, and the scan's cost is paid in the control.

## The recovery and false-positive rates, which are what make the rest readable

Every number below is from [`pipesim.py`](harness/pipesim.py) at
`Volatility 75 Index`'s measured lattice - price 49,288, grid 0.01, `dt` 2s,
46ms of clock jitter, 0.04% of ticks dropped - at **n = 3,000,000 ticks**, which
gives `sigma_Y = 793`, `eps = 5.2e-4` z-units and a tail of 37,382 ticks past
`|z| = 2.5`. 64 continuous replicates: **32 set the bar, 32 measure the false
positives.**

| the generator shown to the battery | ecf leg | u leg | cap leg | caught | width named |
| --- | --- | --- | --- | --- | --- |
| lookup table, 2^8 entries | 6/6 | 6/6 | 6/6 | **6/6** | **8** |
| lookup table, 2^10 | 6/6 | 6/6 | 6/6 | **6/6** | **10** |
| lookup table, 2^12 | 6/6 | 6/6 | 6/6 | **6/6** | **12** |
| lookup table, 2^14 | 0/6 | 6/6 | 6/6 | **6/6** | **14** |
| lookup table, 2^16 | 0/6 | 6/6 | 6/6 | **6/6** | **16** |
| lookup table, 2^20 | 0/6 | 6/6 | 0/6 | **6/6** | **20** |
| lookup table 2^12, linearly interpolated | 0/6 | 6/6 | 6/6 | **6/6** | 19-20, **wrong** |
| 12-bit uniform | 6/6 | 6/6 | 6/6 | **6/6** | **12** |
| 16-bit uniform | 0/6 | 6/6 | 6/6 | **6/6** | **16** |
| 20-bit uniform | 0/6 | 6/6 | 6/6 | **6/6** | **20** |
| 22-bit uniform | 0/6 | 6/6 | 0/6 | **6/6** | **22** |
| 24-bit uniform | 0/6 | 6/6 | 0/6 | **6/6** | **24** |
| **32-bit uniform** | 0/6 | 1/6 | 0/6 | **1/6** | 24-25 = the floor |
| **52-bit uniform** | 0/6 | 0/6 | 0/6 | **0/6** | 24-25 = the floor |
| `z` stored to 0.01 | 6/6 | 6/6 | 0/6 | **6/6** | spacing **0.01000** |
| `z` stored to 0.002 | 6/6 | 3/6 | 0/6 | **6/6** | spacing **0.002001** |
| `z` stored to 0.001 | 3/6 | 0/6 | 0/6 | **3/6** | - |
| **continuous (the false-positive leg)** | 0/32 | 2/32 | 0/32 | **2/32** | 24-25 = the floor |

Detection is the standardised statistic against the calibration half's maximum;
the width is named separately by the raw magnitude, because the two are
different questions and the standardised statistic does **not** answer the
second - a lattice at `2**-k0` makes the magnitude at a *coarser* `k` a sum over
roots of unity whose fluctuation statistics differ from the continuous case, so
a low `k` can clear the bar without the lattice being there. The raw magnitude
does answer it: it jumps to 0.6 at the true width and stays there (a lattice at
`2**-k0` is also a lattice at every finer width). The `z`-lattice rows are named
by the characteristic-function leg instead, which reports the spacing directly
and gets it to four figures.

Read four things off it.

**The battery's reach is about 24 bits and stops there.** Every lookup table and
every truncated uniform from 8 bits to 24 is caught six times out of six **and
named correctly**. At 32 bits it is caught once in six against a false-positive
rate of two in thirty-two, and the width it "names" is 24-25, which is exactly
what the continuous control names - that is not a detection, it is the floor.
**So a clean result on real data excludes a lookup table or a limited-precision
uniform up to 24 bits and says nothing at all about 32.** The bound is the
reconstruction resolution, not the sample: at `z = 4.5` the `u`-space resolution
is `phi(4.5) * eps = 8.2e-9` against `2^-24 = 6.0e-8`, so 24 is the last width
with anything left above the noise, and one more bit costs four times the tail.

**A linearly interpolated table is caught but mis-named.** The
characteristic-function leg misses it entirely - interpolation removes the
lattice in `z` that leg exists to find - while the cap and `u` legs catch it six
times in six, and the `u` leg then reports a width of 19-20 for a table of
**2^12** entries. So the honest statement about interpolation is "detected,
width not recovered", and it matters: interpolation is what a real
implementation does, and a battery built only from the pure-lookup picture would
have had one working leg instead of two.

**The false-positive rate is 2 in 32, not 0.** It is quoted that way everywhere
below: one leg firing on one feed is a 6% event.

**The cap leg is the robust one and the weakest one.** It is the only leg a 0.5%
error in sigma cannot move - the gap between adjacent bit ceilings is 5 to 15%
where a scale error is a fraction of one - and it runs out at 22 bits, because
`n` draws from a continuous normal reach `Phi^-1(1 - 1/2n)` and a `k`-bit
uniform is capped at `Phi^-1(1 - 2^-k)`, so it can only exclude `k <= log2(2n)`.

### On the real feeds

**Not yet run** - see the status table. What the run will produce, and the only
thing it is entitled to claim: on the two feeds with the largest `sigma_Y`,
three million ticks each, either a leg clears the calibration half's bar or none
does. A clean result **excludes a lookup table or a truncated uniform of 24 bits
or fewer** and is silent above that. A firing leg is a 6% event under the null
and would need the width it names to be consistent across both feeds before it
was worth the word "finding".

The other three questions have their own controls, in their own sections.

---

## Three: the quantiser. The grid is measured; the rounding mode is a phase and cannot be

This one is a theorem before it is a measurement.

Four of the five rules a quote pipeline plausibly uses are one function with one
constant moved:

    Q_c(x) = grid * floor(x / grid + c)

`c = 0` is floor, `c = 1/2` is round-half-up, `c -> 1` is ceil, and truncate is
floor again on a positive price. Changing `c` shifts the lattice's **phase**
against the internal price. If the internal price is continuous it is uniform
modulo the grid, so the phase is uniform and **the joint law of the published
increments does not depend on `c` at all**. Round-half-even is not of that form,
but it differs from round-half-up only on exact ties, which a continuous
internal price hits with probability zero.

The measurement that goes with the theorem runs all five modes on the **same**
paths, so the difference between two modes is a paired difference with the
path's own variance removed - an unpaired version needs a hundred times the
sample and, on the last statistic in the table, gets the wrong answer at this
one. Ten paired seeds of 400,000 ticks, at both a fine and a coarse grid:

| paired vs round-half-even | mean | sd | rho1 | frac zero | p(last digit even) |
| --- | --- | --- | --- | --- | --- |
| **fine grid**, `sigma_Y` 915 | | | | | |
| floor | -0.56 | -0.10 | -0.89 | +0.81 | -1.44 |
| ceil | -0.56 | -0.10 | -0.89 | +0.81 | +0.47 |
| truncate | -0.56 | -0.10 | -0.89 | +0.81 | -1.44 |
| round-half-up | **0 exactly** | **0 exactly** | **0 exactly** | **0 exactly** | **0 exactly** |
| **coarse grid**, `sigma_Y` 0.81 | | | | | |
| floor | -0.56 | +1.22 | -0.76 | -0.80 | -0.20 |
| ceil | -0.56 | +1.22 | -0.76 | -0.80 | +0.98 |
| truncate | -0.56 | +1.22 | -0.76 | -0.80 | -0.20 |
| round-half-up | **0 exactly** | **0 exactly** | **0 exactly** | **0 exactly** | **0 exactly** |

In standard errors of the paired difference. **Nothing reaches 1.5 anywhere**,
and round-half-up against round-half-even is not merely statistically
indistinguishable - it is **bit-identical**, because the two differ only on ties
and there are none.

**The two obvious tests are the two the phase argument kills, and both were run
rather than argued away.** The distribution of the **last digit** is the first:
it is uniform under every mode, because `floor(y + c)` is even with probability
one half whenever `y` is uniform modulo two, and the table above measures that
directly - `p(even)` sits at 0.4998 to 0.5004 on every mode at both grids, and
the paired differences are inside one standard error. The **sign of the residual
against a fitted continuous path** is the second, and it fails for a different
reason: the published quote pins the internal price to `+- grid/2` and the
residual *is* that interval, so the sign of the residual is exactly the quantity
the quantiser destroyed. Fitting a continuous path to the quotes recovers the
path to `grid/sqrt(6)` and no better, which is the same `eps` question one runs
into and is larger than the thing being measured by construction.

So: **the rounding mode is not in the published quotes.** This is a negative
result of the second kind - not "we looked and found nothing" but "there is
nothing there to find". No sample size changes it, and an arm that spends ticks
on it is spending them on a question the data cannot answer.

**What would make it answerable**, and it is the only thing that would: an
internal price that is *not* uniform modulo the grid. That is exactly section
six's feedback architecture, where the rounded price is the state - and there
floor and ceil put a systematic `-grid/2` and `+grid/2` into **every tick**,
which is a drift of the order of ten percent a day on a feed like
`Volatility 100` and is excluded on sight by the realised drift. The two
questions are therefore coupled, and that coupling is the section's real
content: **the rounding mode is identifiable only if the quantiser feeds back,
and it does not.**

---

## Four: does the quantisation error accumulate?

Two architectures, two predictions, and they are not close. Write `sigma_Y` for
the per-tick move in lattice units **as published**, and `r` for the rounding
residual, uniform on a cell with `Var(r) = 1/12`.

**Display rounding** - a full-precision internal price, rounded only to publish.
The published increment is `dY - (r_t - r_{t-1})`, so consecutive increments
share that term with opposite signs, and the residual enters a `k`-tick move at
its two ends and nowhere else:

    rho1  = -(1/12) / sigma_Y^2          VR(k) -> 1 - (1/6) / sigma_Y^2

**Feedback rounding** - the rounded price *is* the state. There is no residual
difference term and the rounding variance is added afresh every tick:

    rho1  = 0                            VR(k) = 1 for every k

Both are written in observables, so neither needs a deconvolution to state. They
differ by `sigma_Y^-2`, and that is the whole story about where this question
can be answered. Eight replicates of 400,000 ticks per row:

| `sigma_Y` | predicted `rho1` | display `rho1` | feedback `rho1` | display VR(64) | feedback VR(64) | separation |
| --- | --- | --- | --- | --- | --- | --- |
| 0.65 | -0.2001 | -0.1985 +- 0.0009 | +0.0002 +- 0.0013 | 0.604 | 1.004 | **124 sd** |
| 0.82 | -0.1247 | -0.1239 +- 0.0011 | -0.0003 +- 0.0010 | 0.754 | 1.000 | **83 sd** |
| 1.08 | -0.0715 | -0.0720 +- 0.0006 | +0.0001 +- 0.0015 | 0.857 | 0.996 | **46 sd** |
| 1.55 | -0.0345 | -0.0347 +- 0.0011 | -0.0000 +- 0.0011 | 0.930 | 1.000 | **22 sd** |
| 3.03 | -0.0091 | -0.0092 +- 0.0010 | -0.0001 +- 0.0012 | 0.979 | 0.998 | **5.7 sd** |
| 6.01 | -0.0023 | -0.0026 +- 0.0011 | -0.0003 +- 0.0011 | 0.993 | 0.997 | 1.4 sd |
| 13.0 | -0.0005 | -0.0007 +- 0.0011 | -0.0003 +- 0.0012 | 0.996 | 0.997 | 0.3 sd |
| 30.0 | -0.0001 | -0.0004 +- 0.0012 | -0.0003 +- 0.0012 | 0.997 | 0.997 | 0.1 sd |
| 100 | -0.00001 | -0.0003 +- 0.0011 | -0.0003 +- 0.0012 | 0.997 | 0.997 | **0.0 sd** |

### On the real feeds

**Not yet run.** The table above is the map of which feeds can answer it: from
the six feeds already probed, `Volatility 100` sits at `sigma_Y = 13.7` and
`Volatility 75` at 907, both far inside the undecidable region, so the answer
has to come from the coarse members of the family - `Volatility 150 (1s)`, which
[`twins.md`](twins.md) measured at `Delta/sigma = 1.40`, and whichever of the
low-numbered members turn out to sit beside it. That feed's published lag-1
autocorrelation was **-0.0705** in `twins.md`, against **-0.125** predicted by
display rounding and **0** by feedback, which is suggestive and is not a result:
`twins.md` was not correcting for the missing ticks that section reports (7.85%
of its gaps exceed three seconds), and a gap-straddling pair is two draws
wearing one draw's label.

The closed form tracks the simulator to the fourth decimal across three decades.
**The question is decidable below `sigma_Y` of about 4 and undecidable above
it**, at any sample size - at `sigma_Y = 100` the two architectures differ in the
fifth decimal of a quantity whose standard error is 0.001, and 400,000 ticks is
already more than the family publishes in five days. So this section is answered
on the coarse-grid feeds and is **untested** on the fine ones, and the sample
that would change that does not exist: closing the gap at `sigma_Y = 30` needs
`10^4` times the ticks, which is three hundred years of a two-second feed.

---

## Two: the drift convention, and a correction to `projection.py`

`till_infinity/structures/vol/projection.py` carries both conventions and scores
them live by the probability integral transform. The arithmetic behind its
`RESOLVES_AT` deserves a correction, because the obvious reading of it is wrong
in a way that matters.

**For iid Gaussian log returns the sum telescopes.** The maximum-likelihood
estimate of `mu` over a window is `log(P_last / P_first) / T` *whatever the bar
size*, so a year of one-minute bars and a year of daily bars carry **exactly the
same information about the drift convention**. What buys resolution is calendar
span and sigma, and nothing else. Pooling `N` independent feeds - and
[`generated.md`](generated.md) established that they are independent - the
convention parameter `c` in `mu = -c sigma^2 / 2` has

    c_hat = -2 sum(x_i) / sum(sigma_i^2 T_i)        se = 2 / sqrt(sum sigma_i^2 T_i)

so the separation between Ito (`c = 1`) and plain (`c = 0`) is
`sqrt(sum sigma_i^2 T_i) / 2` standard errors. Verified on the simulator, 40
pools of 20 feeds each, convention known:

| pooled span | `sum sigma^2 T` | separation | `c_hat` when the truth is Ito | when it is plain | picked correctly |
| --- | --- | --- | --- | --- | --- |
| 1 year each | 14.1 | 1.88 sd | +1.049 +- 0.508 | +0.052 +- 0.508 | 33/40, 33/40 |
| 2 years each | 28.2 | 2.66 sd | +1.017 +- 0.363 | +0.018 +- 0.363 | 36/40, 36/40 |
| 4 years each | 56.5 | 3.76 sd | +0.948 +- 0.268 | -0.052 +- 0.268 | 38/40, 39/40 |
| 6 years each | 84.7 | 4.60 sd | +1.005 +- 0.202 | +0.006 +- 0.202 | 39/40, 40/40 |

### On the real feeds

**Not yet run.** What it needs is the 1-day bar history of all twenty-two
members, which the terminal returns in full because 50,000 daily bars is 137
years. The answer is `sum sigma_i^2 T_i` over whatever span those bars cover,
and the separation is its square root over two - so the run reports that number
*first* and the estimate second, and prints "unresolved" rather than a winner if
it lands under three.

The estimator is unbiased and its spread matches the closed form, so the
separation column can be read as a power curve: **the family needs about four
years of pooled history before the answer is worth printing.**

### The correction

The PIT statistic `projection.Calibration.bias_sigma` is a near-optimal reader
of the same quantity. For `Z ~ N(delta, 1)`, `E[Phi(Z)] = Phi(delta / sqrt 2)`,
so the mean PIT moves by `phi(0)/sqrt(2) = 0.2821` per unit `delta` and the
statistic reaches `0.4886 * sigma * sqrt(T_total)` against the estimator's
`0.5 * sigma * sqrt(T_total)` - **97.7% efficient**, which is a good result for a
statistic chosen for other reasons.

But `Calibration.resolved` tests `n >= 50_000` **observations**, and the right
test is on `sigma^2 T`:

    resolved  when  sum over feeds of sigma^2 * T(years)  >=  37.7      (3 sd)

At daily spacing on one feed the two happen to agree - 50,000 daily bars is 137
years and clears the bar four times over. At **hourly** spacing they do not:
50,000 hourly cones is 5.7 years, and `0.4886 * 0.75 * sqrt(5.7) = 0.9` standard
errors, so a feed would be flagged `resolved` at **a fifth of the separation the
flag promises**. Pooled across the Volatility family `sum sigma^2` is about
14.4, so the family needs roughly **2.6 years of live accumulation** - and the
horizon it accumulates at makes no difference whatever. Overlapping cones add
less than nothing.

---

## Five: what `dt` is, exactly

Two different objects wear the name. There is the **publisher's** period - how
often a quote is stamped - and the **generator's** `dt` - how much time one draw
is supposed to represent. They are the same number only if the generator steps
once per publication slot; if it integrates real time then a tick that arrives
2.5% late carries 2.5% more variance.

That is a decidable question and the simulator carries both clocks. Regressing
the squared log increment on the realised gap, in units of "fraction of the
variance per nominal period", 8 replicates of 250,000 ticks:

| the simulated truth | measured slope | the truth |
| --- | --- | --- |
| slot counter - the generator steps once per slot | **+0.052 +- 0.070** | 0.0 |
| wall clock - the generator integrates real time | **+1.052 +- 0.073** | 1.0 |

The estimator carries a `+0.05` bias from its own normalisation, identical in
both arms, so the two hypotheses are read against those two reference points and
not against 0 and 1. They are **14 standard deviations apart**, which makes this
the sharpest instrument on the page.

### The publication clock, measured

`Volatility 75 Index`, 302,299 ticks over 7 days from the terminal:

| | |
| --- | --- |
| mean gap | **2000.807 ms** |
| 2000 ms slots spanned | 302,421 |
| slots carrying a tick | 302,275 |
| empty slots | **146** (0.048%) |
| slots carrying two ticks | 24 |
| offset within the slot | p01 **130 ms**, median **222 ms**, p99 **282 ms**, sd **46.5 ms** |

**The period is exactly 2000 ms.** The 0.807 ms of apparent excess in the mean
gap is arithmetic, not drift: 302,421 slots spanned against 302,299 ticks is 122
net missing publications, and `302,420 * 2000 / 302,298 = 2000.807` to three
decimals. There is no slow clock here and nothing to correct.

**The jitter is 46 ms and it is one-sided-ish around 222 ms**, which is the same
publication offset [`twins.md`](twins.md) measured at 229 ms on the five
standard Volatility indices. All six feeds probed here - 2-second and 1-second,
prices from 0.36 to 49,288 - put their modal offset in the same 220 ms bucket.
So the timetable is shared across the family, exactly as `twins.md` found, and
the open part of the question is whether the *jitter* is shared too: a
correlation near 1 between two feeds' offsets in the same slot says one publisher
stamps them all, and near 0 says the timetable is shared and the jitter is
per-feed transport.

---

## Six: how many bits of the uniform survive to the published quote

Two readings of the question, and both are worth having because they answer
different rungs of [`rebuildpredict.py`](harness/rebuildpredict.py).

**Information per tick.** A discretised variate of standard deviation `sigma_Y`
lattice units carries about `log2(sigma_Y * sqrt(2 pi e))` bits. On the deepest
feed in the family this is under twelve. **MT19937 untempering needs 624
consecutive whole 32-bit words**; no feed on this book emits a whole word in a
tick, so `rebuildpredict.py`'s rung 2 is **impossible from single-feed quotes
rather than merely unsuccessful** - which is the distinction this house asks for
and it is settled by arithmetic, not by a failed search.

**Precision of the uniform itself.** That is what the atom battery measures, and
its reach is the 24 bits the recovery table established. A clean result bounds
the generator's uniform **below** at 24 bits and is silent above it.

---

## The quote lattice, per feed

From the terminal, 2026-09-12. `sigma_Y` is the per-tick move in lattice units
and it is the number that decides what is answerable on each feed: the atom
battery's resolution is `1/(sqrt 6 sigma_Y)`, and section four's two
architectures separate as `sigma_Y^-2`.

| feed | ticks | decimals | grid | price | per-tick sd | `sigma_Y` | bits/tick | distinct moves | repeats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Volatility 75 Index | 129,551 / 72h | 2 | **0.01** | 49,288 | 9.07 | **907** | **11.9** | 5,513 | 0.00% |
| Volatility 10 Index | 129,226 / 72h | 3 | **0.001** | 4,865.2 | 0.1216 | **122** | 9.0 | 880 | 0.01% |
| Volatility 100 (1s) Index | 200,000 / 57h | 2 | **0.01** | 811.0 | 0.1523 | **15.2** | 6.0 | 127 | 0.05% |
| Volatility 250 (1s) Index | 200,000 / 57h | 5 | **1e-05** | 0.36369 | 1.378e-4 | **13.8** | 5.8 | 123 | 0.05% |
| Volatility 100 Index | 125,990 / 72h | 2 | **0.01** | 534.14 | 0.1368 | **13.7** | 5.8 | 113 | 0.10% |
| Step Index | 200,000 / 56h | 1 | **0.1** | 7,569.1 | 0.1 | 1.0 | - | **3** | 0.00% |

Two things are worth saying about this table before the rest of the family is
added to it.

**The grid is not the printed precision.** `Volatility 10` prints three decimals
and moves on 0.001; `Volatility 250 (1s)` prints five and moves on 1e-05; both
happen to agree. The greatest common divisor of the moves is what settles it and
it is computed per feed rather than assumed, because
[`twins.md`](twins.md) already found one member of this family quoted on a grid
*coarser* than its printed precision and quarantined it for exactly that.

**Everything on this page is computed on the bid, not the mid.** The mid is
`(bid + ask)/2` and sits on a *half* grid whenever the spread is an odd number
of grid steps, which would halve the measured lattice, double `sigma_Y`, and
move the bits-per-tick column by one - a wrong answer to question six obtained
by averaging two right ones. The bid is a raw quote on the venue's own lattice
and is what the grid, `sigma_Y`, the atom battery and the residual arithmetic
all read.

**The family spans two decades of `sigma_Y` and therefore two different sets of
answerable questions.** `Volatility 75` at 907 is where the atom battery has its
resolution and where section four has none; `Step Index` at 1.0 - three distinct
tick moves, `+-0.1` and zero - is the opposite. No feed answers everything and
the table is the map of which answers which.

## What this page does not say

* **It is not a trade and cannot become one.** A predictable quote would be a
  defect in a product whose terms permit voiding trades made against it, which is
  [`twins.md`](twins.md)'s conclusion and nothing here changes it. The write-up
  is the deliverable.
* **Nothing here touches the source.** The atom battery is about the
  *inverse-normal's precision*, not about whether the uniforms are predictable.
  [`rebuildpredict.py`](harness/rebuildpredict.py) owns that question and its
  answer is unchanged.
* **The atom battery reaches 24 bits and no further.** A 32-bit uniform is
  caught one time in six against a 2-in-32 false-positive rate, which is to say
  not caught. Everything from 8 to 24 bits is caught six times in six. The
  bound is the reconstruction resolution `eps` and not the sample size, so a
  longer pull does not move it: at `z = 4.5` the `u`-space resolution is `8e-9`
  against `2^-24 = 6e-8`, and one more bit costs four times the tail.
* **The rounding mode is unidentifiable, full stop**, unless the quantiser feeds
  back. That is a theorem, verified on paired simulator runs, and no sample
  changes it.
* **Section four is untested on any feed with `sigma_Y` above about 4**, and the
  sample that would change that does not exist.
* **Boom, Crash, Step, Jump and Range Break are in the lattice and clock tables
  only.** They are a compound Poisson, a fixed-size coin and a reflecting walk,
  and reading them through a diffusion's residual arithmetic would be measuring
  the model rather than the generator.

## What follows

Ordered by what is worth doing, not by what is interesting.

1. **Finish the run.** `./.secrets/lab.sh run research/harness/pipeline.py
   OMP_NUM_THREADS=8`, about an hour, half of it the terminal. Everything the
   status table marks "not yet pointed at real feeds" falls out of one
   invocation, and the harness writes `~/till_infinity/logs/pipeline.json` after
   **every section**, so a drop costs the section it was in and not the tick
   pulls before it. The tick pulls themselves are cached under
   `~/till_infinity/data/pipeline/`, so a second run is compute only.
2. **Change `projection.Calibration.resolved`.** It tests `n >= 50_000`
   observations; it should test `sum over feeds of sigma^2 T(years) >= 37.7`.
   The two agree at daily spacing and disagree by a factor of five in separation
   at hourly, which is the spacing the desk is most likely to accumulate at. The
   flag is the only thing standing between an unresolved convention and a
   convention adopted on noise, and at present it will raise at a fifth of the
   evidence it promises. Three lines.
3. **Do not spend any more ticks on the rounding mode.** It is a phase, the
   phase is uniform, and the modes are bit-identical or within 1.5 standard
   errors of each other on paired paths. The only architecture that would make
   it readable is the feedback quantiser section four tests for.
4. **Read section four only on the coarse-grid feeds and say so.** The two
   architectures separate as `sigma_Y^-2`: 124 standard deviations apart at
   `sigma_Y = 0.65` and *zero* at 100. Any statement about the fine-grid feeds
   from this test is a statement about the noise floor.
5. **`rebuildpredict.py` rung 2 can be closed by arithmetic.** No feed on this
   book emits a whole 32-bit word in a tick, so MT19937 untempering from
   single-feed quotes is impossible rather than unsuccessful. Rung 4 - the
   cross-feed stream - is untouched by this and stays open.
6. **Re-run after any long gap.** Every statement here is about a generator as
   it was configured in September 2026. Generators get changed, and the cheapest
   thing on this page to repeat is the lattice table, which would show a change
   of grid or of tick rate immediately.
