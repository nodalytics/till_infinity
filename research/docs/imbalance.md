# Gaps as levels: does price react when it comes back?

The operator's account, which this sets out to measure rather than to illustrate: a
displacement leaves an imbalance behind it, price may return to that edge later, and
**a fresh imbalance is what gives a level a fresh perspective**. The first touch is
the informative one, the wick that opened the gap is the edge price reacts from, and
a gap opened by a run of strong directional candles is a stronger level than one
opened by a single spike.

Harness: `research/harness/imbalance.py`. Features that came out of it live in
`research/training/candles.py`.

## Stating it so it can fail

A fair value gap is usually described as a three-candle pattern. Written down it is
just `high[j-2] < low[j]` - a band that only the middle candle traded through - so
**nothing about it needs the number three**, and `SPAN` carries it as a parameter
with 2 as the classic case.

Price has *touched* the gap when a later bar's low reaches `low[j]`: the wick edge,
not the body, because that is what the operator watches. From the close of that bar
the outcome is first passage of a symmetric barrier at one true range. Up first is a
reaction, down first is a failure, and **both inside one bar counts as a failure**,
since a bar does not record which extreme came first. Every reaction rate here is
therefore biased downward.

### The breakeven line, not fifty percent

A symmetric barrier pays nothing at a 50% hit rate. With a round-trip cost of 0.03R
the line is `0.5 + cost/(2*band)` = **51.5%**, and every rate below is reported
against that rather than against a coin flip. A 50.2% reaction rate is not a small
edge; it is a loss.

### The placebo, which is the only reason this is answerable

Price touching some earlier level and bouncing is ordinary mean reversion. Any level
would do it, and a study of gap edges alone would measure reversion and report it as
a property of gaps.

So every gap is matched to a **placebo level**: an ordinary prior extreme, chosen
from bars *before* the gap at a similar distance, with no imbalance behind it. The
number that means anything is the difference. If the two react alike, a gap is a way
of *noticing* a level rather than a reason for one.

### The synthetics are a second population, not a null

An earlier draft of this document claimed the three synthetic instruments -
Volatility 75, Boom 1000, Crash 1000 - were a *sharper control than the placebo*: no
order book, no participants, therefore a gap edge must carry nothing there, and an
effect appearing on Volatility 75 would prove the measurement was broken.

**That reasoning is wrong and is recorded here so it is not repeated.** It smuggles
in a premise: that a gap effect requires real participants returning to unfilled
liquidity. It does not. Volatility clustering with any amount of mean reversion will
produce edges that appear to hold, with no book involved at all - the apparent
reaction is a property of the *process*, not of anyone's intent. And these synthetics
are not structureless: Deriv simulates a book behind them, `generators.md` puts them
at `H = 0.50`, and `structures/zma.py` finds the same indicator *reliably wrong* on
Boom and Crash specifically, which is evidence of distinctive structure rather than
of none.

So an effect that replicates on the synthetics would not be an artifact. It would
mean the effect is a property of **price geometry rather than order flow** - which for
this desk is the more useful of the two answers, because it trades those instruments.
A structural pattern is expected to travel across any series with the right
properties, which is also why the shapes from the technical-analysis literature turn
up on generated series.

The placebo level remains the control that carries the weight, precisely because it
sits *inside* the same series and therefore controls for that series' own statistics.
A real artifact test is a phase-randomised or block-shuffled surrogate of each
instrument, which destroys structure while keeping the marginal distribution, and is
not yet run.

## What the splits ask

| split | question |
|-------|----------|
| freshness | is the first visit different from the second, or the tenth |
| band state | untouched, entered but **not closed**, or fully closed |
| origin wick | does a long wick at the edge make a better level |
| displacement | does the candle that opened it predict anything |
| what opened it | a consistent run with a long candle, a run without one, or a single spike |

`what opened it` is the operator's consistency rule used as a **qualifier on a gap**
rather than as a signal. The rule itself was measured separately at 1.17x forward
movement on real instruments and nothing on synthetics; whether it also grades a
level is a different question and this is the first time it has been asked here.

A run is only counted when it points the same way as the gap. A bullish imbalance
opened by a run of red candles is not the pattern being claimed, and folding it in
would dilute the exact cell under test.

## Gold, hourly, 17,866 gaps and 68,531 visits

Reaction rate at the edge, against the 51.5% breakeven:

| split | best cell | against |
|-------|----------:|--------:|
| freshness | first **50.2%** | later 48.7% |
| band state | untouched **50.2%** | not closed 49.5%, closed 49.0% |
| origin wick | big **50.2%** | small 48.9% |
| displacement | big 49.8% | small 49.1% |

Gap edge at first touch **50.2%** against a matched placebo level at **49.2%** -
a difference of **+1.0% +/- 1.1%**.

**Every direction matches the operator's model.** Fresh beats stale; unclosed beats
closed; a long origin wick beats a short one; a gap edge beats an arbitrary level.
Four independent splits pointing the predicted way is more interesting than any one
of them, and worth saying plainly.

**And nothing pays.** Every magnitude is about one point, each inside or barely
outside two standard errors, and the best cell in the table is 1.3 points *below*
breakeven. A rule that reacts 50.2% of the time on a symmetric barrier loses money
at this broker's costs.

## Nine instruments, 603,375 visits - what survived and what reversed

| split | cell | rate | against |
|-------|------|-----:|--------:|
| freshness | first | **50.2% +/- 0.3** | second 50.0%, later 49.4% |
| band state | untouched | **50.2% +/- 0.3** | not closed 49.7%, closed 49.6% |
| what opened it | consistent run, no long candle | **50.5% +/- 0.3** | with intent 49.9%, single candle 49.4%, run against 49.2% |
| origin wick | big | 49.6% +/- 0.2 | small 49.8% |
| displacement | big | 49.1% +/- 0.2 | small 50.1% |

Gap edge at first touch **50.2%** against placebo **49.6%**: **+0.6% +/- 0.4%**.

**Survived the widening.** Freshness is monotonic - 50.2%, 50.0%, 49.4% from first to
later - so a level really is at its best the first time price returns to it. A
*consistent run* into the gap beats a single candle (50.5% against 49.4%) and beats a
run pointing the other way (49.2%), which is the operator's rule doing real work.
Untouched beats touched. And the gap edge beats a matched ordinary level.

**Reversed.** Two splits that looked right on gold flipped sign on nine instruments:

* **origin wick** - gold had big wicks better (50.2% against 48.9%); the panel has
  them slightly *worse* (49.6% against 49.8%). The edge being a wick is still how the
  level is defined; the *size* of that wick carries nothing.
* **displacement** - gold had big displacement better; the panel reverses it
  decisively, 49.1% against 50.1%. A violent candle into a gap makes a *worse* level.

**And one sub-claim inverted.** Within consistent runs, the ones containing a long
candle did **worse** than the ones without: 49.9% against 50.5%. So consistency helps
and the "long candle showing strong intent" does not - the opposite of the rule as
stated. That is a real distinction and it came out of separating the two, which is why
they were separated.

The placebo difference also shrank as the sample grew: **+1.0%** on gold alone,
**+0.9%** on two instruments, **+0.6%** on nine - still outside two standard errors,
but decaying the way a partly-selected effect decays rather than holding the way a
real one does.

**Nothing pays.** The best cell in the entire panel is 50.5% against a 51.5%
breakeven. Every one of these is a losing rule at this broker's costs, including the
ones that survived every control.

## A slower timeframe does not make a stronger gap

Asked directly: is a 4h gap a better level than a 15m gap? Four FX instruments, gaps
found on each rung, with the barrier and the horizon both scaled to that rung so the
comparison is not simply "4h gaps are further apart":

| gap found on | reaction rate | visits |
|--------------|--------------:|-------:|
| 15m | **49.7% +/- 0.3** | 82,298 |
| 30m | 49.5% +/- 0.5 | 40,090 |
| 1h  | 49.4% +/- 0.7 | 19,438 |
| 2h  | 48.9% +/- 1.0 | 10,084 |
| 4h  | 48.9% +/- 1.4 |  5,469 |
| 8h  | 49.6% +/- 1.8 |  3,010 |
| 1d  | 50.7% +/- 3.0 |  1,140 |

**No trend, and 4h is the joint worst rung.** 15m gaps react slightly better than 4h
gaps, on fifteen times the sample.

1d looks best at 50.7%, and that is the whole illusion: it rests on 1,140 visits with
a +/-3.0% band that swallows the entire range of the table. A slower timeframe has
fewer bars, so fewer observations, so wider error bars and more room for a flattering
number. This is the same mechanism as the 4h scarcity in `anchors.md` - 728 decisions
out of 199,978 - and it is worth naming as a general trap: **on this desk, "the higher
timeframe is stronger" tends to mean "the higher timeframe has less data".**

## Two defects found while building this, both worth recording

**Every bar at a level was counted as a separate touch.** A hundred consecutive bars
resting on an edge are one visit, and counting them individually both swamped the
tally with the quietest levels - the ones where price sat still longest - and made
the study too slow to finish. Price now has to leave by half a true range before a
return counts again.

**A memo keyed on `id(bars)` returned another instrument's true range.** CPython
reuses object ids after a free, so the second instrument silently received the
first's volatility array and the run died on an array-length mismatch. It crashed,
which was lucky: had the two arrays been the same length it would have produced
numbers, and they would have looked fine. The cache is gone and true range is passed
explicitly.

## Still open

The surrogate test named above - phase-randomised or block-shuffled versions of each
instrument - has not been run, and it is the one that would say whether the surviving
+0.6% is structure or arithmetic.

Worth doing, because three of the four surviving directions are exactly the ones an
operator would predict, and the honest position is that they are consistent in sign
across 603,375 visits and still 1.0 point short of paying for themselves. The
interesting question is no longer whether gaps are levels. It is whether anything can
be *added* to a 50.5% cell to carry it past 51.5% - a wider barrier, a better exit,
or a filter that has not been tried - and none of the splits here is that thing.
