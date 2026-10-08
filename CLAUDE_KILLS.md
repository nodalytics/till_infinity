# Kills

What died, and what killed it. One session, 2026-10-08.

A desk accumulates ideas faster than it can test them, and the ones that
survive are usually the ones nobody got round to checking. This is the other
list. It is kept because **a refuted idea is a result** - it stops being
re-proposed, and the method that refuted it transfers.

Three of these are mine. Those are the useful ones.

---

## The trades

### The fade-to-value displacement thesis

**The idea.** `fade-to-value` fades a move back toward value. Give "value" a
definition - the origin candle of a displacement - and the 82% return rate
measured in the zone work becomes the *hit rate of a target* rather than a
useless entry signal.

**It was a good idea.** It rescued a number that had been written off and it
gave a vague strategy a concrete object. It got three separate tests because it
deserved them.

**Dead.** Traded *from* the zone: negative everywhere. Traded *toward* it: **0
of 105 cells** with a positive lower bound, across four entry rules, five stop
pads and four body thresholds. Used to *filter* the origins the strategy
already trades: +0.120R on 477 trades at 1d, +0.017R on 985 at 4h, **-0.007R on
2,786 at 1h** - shrinking as the sample grows and reversing on the largest.

**What killed it.** The stop. 89-91% of fades were stopped before the target
arrived. Price does return to these levels 77-81% of the time; the return rate
is measured with no stop and 300 bars, and the trade has a stop and sixty.

**The transferable part.** Waiting for confirmation raised the hit rate from
31% to 48% and lowered reward from 1.88 to 0.94 - it bought hit rate at almost
exactly the fair rate. Every variant landed 2.5 to 4.6 points short of
breakeven. That is `1/(1+N)` doing what it does, and it is why "improve the
entry" was never going to be the answer.

### The one surviving positive cell

**The idea.** `impulse_back` at a 0.70 body on 1d was the only cell of sixty
with a positive mean R, **+0.036**.

**Dead.** Widening the instrument set from 16 to 29 - adding indices, oils and
the rest of the metals - turned it to **-0.028**, and it stopped being the best
cell at its own timeframe.

**What killed it.** Nothing subtle: more instruments. The sixteen reproduced
exactly, so neither run was mismeasured. A result that reverses when thirteen
instruments are added was a property of those sixteen.

---

## The tidy-ups

### "`displace` and MCFL's `DISPLACE_C` are the same rule"

**The idea.** Two packages had a rule for "two consecutive one-sided bars".
Obvious duplication - import one threshold into the other and be done.

**Dead, and it would have been a bug.** 131 instrument-timeframes, 2.0M bars:
they fire at nearly the same rate (21.6 against 18.9 per 1k bars at 1d) and
agree on about **a quarter** of their union. Only 37-40% of `DISPLACE_C` bars
are `displace` bars.

**What killed it.** Measuring instead of assuming. `DISPLACE_C` grades a body
against the **last ten bars'** bodies - "big for lately" - while `displace`
wants a share of the bar's **own range** - "decisive in itself". Relative
against absolute, coming apart hardest on thin instruments.

**The transferable part.** The same shape had already appeared between
`origins` and `displacement` - magnitude against one-sidedness, agreeing 59-78%
of the time. Two detectors with the same name are usually two detectors.

### Merging the MCFL service into structures

**The idea.** Both produce market structure. One service, one package.

**Dead on three counts.** MCFL imports *nothing* from `structures` while
`trading` imports `structures` in five modules, so merging would turn MCFL's
"no path to a broker" from a fact the import graph enforces into a convention
someone must remember. MCFL owns a ccxt fetch loop, and the structures service
has a known, undiagnosed silent-stall failure mode on a two-core box. And MCFL
is off by default and pausable at runtime, while structures is the always-on
critical path.

**What survived.** The real duplication is at the *definition* level, not the
service level, and the fix is one directional dependency - MCFL consuming
`structures`' formations rather than re-deriving them - not a merge.

---

## The architecture

### Force, quality, decay and pressure as Kalman dimensions

**The idea.** A richer latent state: position, drift, acceleration, width,
structural force, quality, decay, pressure.

**Mostly dead, on arithmetic.** You cannot estimate more latent states than
your observations identify. A level sees one scalar per touch and a handful of
touches in its life. An eight-dimensional state fed one scalar at a time does
not converge in its unobserved directions - it tracks the prior, and then
reports confident numbers for quantities the data never constrained. **That
failure is silent**, which is the worst kind here.

**What survived.** `(price, slope)` - two dimensions with a real transition
model - gated so it is not used until it clears three sigmas of its own
posterior. Force belongs on the *event* as a formation fingerprint, since
nobody can write down what `F_{t+1}` means. Quality and decay already exist
outside the filter with dynamics that work. Pressure survives as the one
genuinely new object and has not been built.

### Zone width as a Kalman dimension

**The idea.** If the centre is a filtered state, make the width one too.

**Dead on the observation model, not the arithmetic.** **Width is not
observed.** What is observed is a hit or a miss - Bernoulli - and
`|touch - centre|`, half-normal at best. A linear-Gaussian filter over width
would assume exactly the thing the band exists to stop assuming.

**What survived.** Kalman for the centre, conformal for the width. Each tool on
the problem it is valid for.

---

## Mine

The three retractions. These are here because a log of other people's dead
ideas is marketing.

### "The gate earns its keep"

I measured production's retrain gate as a **contest** - the challenger must
beat the champion - and reported that gating beat deploying everything at every
cadence. Production's rule is `GATES["vs_champion"] = 0.01`, a **tolerance**.

Under the real rule the gate wins at 14 days by 0.23% and *loses* at 28 and 56
by 0.03% and 0.04%, with **23 of 25 challengers promoted** against 13 of 25
strict. A 1% tolerance on a quantity whose whole spread is 1.5% is one nearly
everything clears. Withdrawn: on pinball alone the gate is insurance, not
selection.

### "The slope change is conservative"

I wrote that a level which never earns a slope behaves exactly as it did
before. It didn't. The covariance was propagating into `variance` ungated, so
**every zone in the book got wider**, including levels with no slope at all.

CI caught it. A non-trending level is now bit-identical to the old filter -
not "close to", the same numbers, pinned against a verbatim copy.

### "`CONFIDENT_TOUCHES` is the shrinkage parameter"

I cited `CONFIDENT_TOUCHES = 5` as the bound on how many states a level can
identify. That constant appears in exactly one `if`, choosing between two
wordings of an explanation string. It affects no number. The shrinkage is
`PRIOR_WEIGHT = 4.0`.

The argument survived; it was resting on the wrong constant. And the better
question came out of the correction: `PRIOR_WEIGHT` is a variance ratio with a
closed form, so it should be estimated rather than chosen.

### And one near-miss

The first version of the 2D filter gated the covariance propagation as well as
the mean's. The off-diagonal is the only thing that lets a slope be learned, so
a slope gated out of existence never clears the gate. It reported
`slope = 0.0000` forever and **looked completely healthy** doing it. Caught by
printing the number rather than trusting the tests.

---

## What does the killing

The tools that earned their place, in rough order of how much they killed:

**The duty-cycle control.** Random gates keeping the same share. It has killed
every pause rule ever proposed here, because on a net-negative book any rule
that trades less shows a profit improvement, so the headline number carries no
information at all.

**The barrier test.** Did price reach the target before the stop, inside a
holding period a desk would accept. Base rate 48.6%. It killed every mean-based
result in the zone work, because a rule that aims at a level four times out of
five looks magnificent on hit rate alone.

**Widening the universe.** Sixteen instruments to twenty-nine. It killed the
only positive cell in a sixty-cell sweep, and cost nothing but a rerun.

**The placebo level.** An ordinary prior extreme at a similar distance with no
imbalance behind it. Without it, a study of gap edges measures mean reversion
and reports it as structure.

**`test_no_published_feature_is_near_constant`.** It caught **two unrelated
errors on the same feature, hours apart** - a formation biasing the level book,
and a filter widening every zone. Neither looked like what it was; both
surfaced as a published statistic collapsing. A test that asserts a
distribution has not collapsed catches the failures that do not announce
themselves.

**Reading the code instead of the name.** `CONFIDENT_TOUCHES`, and
`fade-to-value` turning out to already trade origins, which changed the
question before any measurement ran.

---

## What is still alive and unproven

Being explicit, because nothing above earns the right to be vague here.

The slope, the calibrated zone width, the estimated `PRIOR_WEIGHT`, six new
formation kinds. **None has been measured against outcomes.** Each ships behind
a guard that makes a cold or thin book behave exactly as it did before - a
gate, a run-in, a fallback.

That makes them safe. It does not make them right, and the difference is the
whole reason this file exists.
