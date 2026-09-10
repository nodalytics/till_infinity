# Predicting VIX and VVIX: what it would be for, and the one thing it changes

**Nothing here has been run.** This is the case for and against, with the harness
each test needs, written so it can be attacked before it is built.

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

## The prior

It probably does not work here, for the reason at the top: 72% of what this desk
trades is generated, and VIX cannot describe a random number generator. The
version of this worth building is narrow - **a size input for four equity
indices** - and test one decides whether even that is real.

Writing that down before running it, because
[forecasting.md](forecasting.md) records three occasions in one day where a clean
table was mistaken for a finding, and the defence that worked was deciding what
would count as failure first.
