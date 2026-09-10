# Predicting VIX and VVIX: what it would be for, and the one thing it changes

**Tests one, two and three are run. Test four is answered by them.** The case
below was written before any of them, and is left as it stood - the prior it
records ("it probably does not work here") turned out to be right about the
scope and wrong about the strength.

## Why this is a different question from everything in forecasting.md

[forecasting.md](forecasting.md) measures models that forecast *realised*
volatility from the price series. Its standing result is that nothing beats
reusing the last realised value, and the reason is in the models rather than the
effort: **every one of them is a function of the past**. GARCH says the current
scale persists, HAR says three lags of it persist, the learner says a
twenty-feature nonlinear combination of them persists. None can represent "there
is a rate decision in forty minutes".

VIX is not that. It is the options market's own forecast of the next thirty days,
priced by people with money at stake, and it is **forward-looking by
construction**. VVIX is the same statement about VIX itself - the volatility of
the volatility forecast.

That makes this the first genuinely *leading* input this project could have, and
[forecasting.md](forecasting.md) already names it as the canonical answer while
saying it is out of reach. It is worth checking whether that is still true.

## The reason to be sceptical before starting

**We do not trade anything VIX measures.** The book is 53 instruments, of which
roughly 72% are Deriv synthetics - generated processes with no options market, no
macro exposure and, as [generated.md](generated.md) measured, no shared driver
with anything at all. VIX cannot be informative about `volatility_75_index`
because nothing outside its generator is.

Of the rest, the equity indices (`us100`, `us30`, `spx500`, `us2000`) are the
only instruments VIX directly describes. So the honest scope is **four of
fifty-three**, and those four have their own recent record: -540 over 96 closes
in fourteen days, though [that damage belongs to strategies since
removed](../research/README.md).

An input that helps on 8% of the book has to help a great deal to matter.

## Four tests, in the order that kills the idea fastest

### One: does VIX say anything our own estimate does not?

The cheapest test and the one most likely to end it. `vol_bps` on `spx500` is
already a volatility estimate; VIX is another. If they are the same number in
different units, VIX adds nothing and everything below is moot.

Regress next-day realised volatility on (a) our estimate alone, (b) VIX alone,
(c) both. **If (c) does not beat (a), stop.** This is the incremental-information
question and it is answerable in an afternoon.

### Two: is the term structure the signal rather than the level?

VIX in contango versus backwardation is the standard reading, and it is a
*different* quantity from the level - VIX at 18 rising from 14 is not VIX at 18
falling from 25. If anything here works it is more likely to be the shape than
the number.

Needs VIX and VIX3M (or the futures curve), which is more data than the level
alone and available from the same sources.

### Three: does VVIX lead VIX?

VVIX is the volatility of the volatility index, so a rise in VVIX with VIX flat
is the options market pricing uncertainty about the forecast itself. The claim
worth testing is whether that precedes a VIX move rather than accompanying it.

**This is where the multiple-comparison discipline matters.** Two series, several
lags, two quantities - and [generated.md](generated.md) records that the largest
correlation in a 325-pair study was between two *unrelated* instruments. A
control is not optional: the same lead-lag against an unrelated volatility proxy
is what says whether a number is a finding.

### Four: does any of it survive the horizon problem?

VIX prices **thirty days**. This desk holds trades for minutes to a day, and
[reacting.md](reacting.md) measured no extractable edge in the first five minutes
at all. A thirty-day forecast is the wrong instrument for a fifteen-minute trade
unless the *change* in it is fast, which is what test three is really asking.

## Where the data comes from

`prices/yahoo.py` already exists and yfinance is already a dependency. `^VIX`,
`^VIX3M` and `^VVIX` are all Yahoo tickers with long daily history, so this needs
no new collector - unlike the synthetics, which needed
[the broker itself](harness/mt5fill.py).

Daily is a real limitation: intraday VIX would be needed for anything below a
day, and that is not free. Test one is answerable on dailies, which is another
reason to run it first.

## What a positive result would actually change

Not the entry. The measured shape of this book is that **direction is close to
unforecastable and the width is the modellable part** - see
[clustering.md](clustering.md) - so a better volatility forecast changes *how
much to size*, not which way to face.

Concretely, it would go where `forecast_ratio` goes: `scaling.by_regime` already
reduces size when the expected change in scale is large, and `regime_band` is
**0.0** because held rate is not profit and the evidence was not strong enough to
switch on. An input that genuinely leads would be the thing that justifies
turning it on.

## Results

### Test one: VIX does not merely add to our estimate - it replaces it

15 years, 3,771 aligned days, walk-forward with the fit redone at every step
(`research/harness/impliedone.py`). `hist` is a trailing realised estimate,
which is what `vol_bps` amounts to.

| horizon | n | R2 hist | R2 vix | R2 both | both − hist | vs naive |
| --- | --- | --- | --- | --- | --- | --- |
| 1 day | 3,248 | 0.1770 | 0.2991 | 0.2973 | **+0.1203** | +0.2561 |
| 5 days | 3,244 | 0.2927 | 0.4918 | 0.4915 | **+0.1988** | +0.4296 |
| 21 days | 3,228 | 0.2100 | 0.3479 | 0.3473 | **+0.1373** | +0.3915 |

Three things, and the second is the one that matters:

**VIX beats the trailing estimate at every horizon**, by 12 to 20 points of
R-squared.

**`both` is not better than `vix` alone** - fractionally worse at 1 day. The
historical estimate adds *nothing* once VIX is present. That is stronger than
"VIX helps": the implied number already contains whatever the trailing one
knows.

**It beats the naive baseline by +0.26 to +0.43.** That baseline - forward
realised equals trailing realised - has beaten every model in
[forecasting.md](forecasting.md): GARCH, HAR, the pooled tree, the
factorisation machine. This is the first thing measured on this project that
walks past it, and it does so by being the one input that is not a function of
the past.

### Test two: the level does the work, the curve adds a little

`research/harness/impliedtwo.py`. `slope` is VIX3M over VIX; `change` is VIX
against its own ten-day mean.

| horizon | level | +slope | +change | +both | best over level |
| --- | --- | --- | --- | --- | --- |
| 1 day | 0.2998 | 0.3116 | 0.3049 | 0.3114 | +0.0118 |
| 5 days | 0.4903 | 0.5054 | 0.5050 | 0.5102 | +0.0199 |
| 21 days | 0.3480 | 0.3586 | 0.3532 | 0.3586 | +0.0106 |

The term structure earns **1 to 2 points** on top of the level - small, but the
same sign and size at all three horizons, which is what separates a weak signal
from noise across six comparisons.

`+change` adds almost nothing and `+both` matches `+slope`, so once the curve
shape is in, VIX's recent drift is redundant. The shape matters; the momentum
does not.

### Test three: VVIX adds nothing and does not lead

`research/harness/impliedthree.py`.

| horizon | level+slope | +vvix | gain |
| --- | --- | --- | --- |
| 1 day | 0.3123 | 0.3116 | -0.0008 |
| 5 days | 0.5081 | 0.5090 | +0.0009 |
| 21 days | 0.3581 | 0.3613 | +0.0032 |

And the lead-lag, which was the more interesting claim:

| lag | VVIX → VIX | control (GVZ → VIX) |
| --- | --- | --- |
| -1 | -0.0849 | 0.0005 |
| **0** | **0.8479** | **0.4026** |
| +1 | -0.0321 | -0.0433 |
| +2 | -0.0246 | -0.0120 |
| +3 | -0.0088 | -0.0065 |

**Contemporaneous correlation is 0.848 and every lag is nothing.** VVIX moves
*with* VIX, not before it - the same market reacting to the same news at the
same moment.

The control did real work here. Gold's volatility index against VIX scores
0.4026 on the same day, which confirms 0.848 is genuinely high rather than an
artefact of two volatility series both being noisy; and both collapse to ~0 at
lag. A VVIX→VIX correlation of -0.03 at +1 could have been written up as a
faint negative lead by anyone who had not asked what an unrelated pair scores.

### Test four: the horizon problem is real and this is where it bites

The incremental gain from VIX is **largest at 5 days (+0.20) and smallest at 1
day (+0.12)**, and 1 day is already longer than most of this desk's holds -
[reacting.md](reacting.md) measured no extractable edge in the first five
minutes at all.

That is the same pattern [forecasting.md](forecasting.md) found from the other
direction: the case for forecasting volatility strengthens as the horizon
lengthens, and this desk trades at the end where it is weakest.

### Does it transfer to the other indices, and is the matched series needed?

`research/harness/impliedindex.py`. Each index against its own implied series,
and against ^VIX.

| feed | index | implied | h | hist | own | vix | own − hist | own − vix |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spx500 | ^GSPC | ^VIX | 1d | 0.1770 | 0.2991 | 0.2991 | +0.1221 | 0.0000 |
| spx500 | ^GSPC | ^VIX | 5d | 0.2927 | 0.4918 | 0.4918 | +0.1991 | 0.0000 |
| us100 | ^NDX | ^VXN | 1d | 0.1414 | 0.2306 | 0.2292 | +0.0892 | +0.0014 |
| us100 | ^NDX | ^VXN | 5d | 0.2743 | 0.4548 | 0.4352 | +0.1804 | +0.0196 |
| us100 | ^NDX | ^VXN | 21d | 0.2307 | 0.3889 | 0.3237 | +0.1582 | **+0.0652** |
| us30 | ^DJI | ^VXD | 1d | 0.1826 | 0.2773 | 0.2854 | +0.0947 | **-0.0080** |
| us30 | ^DJI | ^VXD | 5d | 0.2996 | 0.4635 | 0.4712 | +0.1639 | **-0.0077** |
| us30 | ^DJI | ^VXD | 21d | 0.2021 | 0.3360 | 0.3238 | +0.1339 | +0.0122 |

**It transfers.** `own − hist` is +0.089 to +0.199 on every index at every
horizon, so test one was not an S&P quirk.

**And the matched series is barely needed at the horizons this desk trades.**
`own − vix` is +0.0014 for us100 at one day and **-0.0080** for us30, where VIX
is *better* than VXD. Only at 21 days does VXN earn its place (+0.065), and 21
days is far longer than anything held here.

So: **take ^VIX for all the equity indices.** One free Yahoo series through a
dependency that already exists, rather than four feeds to keep alive - and on
us30 the matched series would have been slightly worse.

**^RVX returned no data** - delisted or renamed at Yahoo - so `us2000` is
untested. VIX serving the other three without their matched series suggests it
would serve there too, and suggesting is not showing.

## What this is worth, in one line

**A size input for the equity indices, at horizons of a day and up.** Not an
entry signal, and not applicable to 72% of the book.

## What has not been checked

* **It is measured on ^GSPC, not on what we trade.** `spx500` should transfer
  since the CFD tracks the index, but VIX is SPX-specific: `us100` wants VXN,
  `us30` VXD, `us2000` RVX. None tested.
* **Daily bars only.** Intraday VIX would be needed for anything below a day,
  and the 1-day result is the weakest of the three.
* **Held rate is not profit**, and R-squared against realised volatility is not
  even held rate. Nothing here has been joined to money.

## The prior

*Written before the tests, kept as it stood:*

> It probably does not work here, for the reason at the top: 72% of what this
> desk trades is generated, and VIX cannot describe a random number generator.
> The version of this worth building is narrow - **a size input for four equity
> indices** - and test one decides whether even that is real.

Right about the scope and wrong about the strength. The narrow version is
exactly what survived, and within it the effect is larger than anything else
measured on this project - VIX does not merely beat our own volatility estimate,
it makes it redundant.

Writing that down before running it, because
[forecasting.md](forecasting.md) records three occasions in one day where a clean
table was mistaken for a finding, and the defence that worked was deciding what
would count as failure first.
