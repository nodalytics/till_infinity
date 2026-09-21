# Textbook chart patterns, priced against their own target rules

Tests the classical patterns as the books define them, not as a convenient version of
them. Definitions are quoted from Fidelity's *Identifying Chart Patterns* deck, which
cites *Technical Analysis: the Complete Resource for Financial Market Technicians*.

Harness: `research/harness/patterns.py`.

The headline, before any table: **the placebo control changes the answer
completely**, and **nothing here pays.** The pattern with the best raw hit rate turns
out to be measuring its own geometry; the patterns that beat a matched random entry do
so by one to two points, which is not enough to clear the breakeven their own target
rules impose. One cell of sixteen clears both bars, by 0.6 points, which is what the
best of sixteen looks like.

## Each pattern is fully codeable except for one word

Double Top, verbatim from the deck:

* two successive peaks separated by an opposite reversal point
* "either rounded or pointed peaks that are usually at **roughly** the same price"
* "price must break out of middle reversal point"
* target: "taking the height from the highest peak to the trough and then subtracting
  the amount from the breakout price to the downside"

Three of those four clauses are precise. Only "roughly" is not, so each pattern here
has exactly **one** free parameter - how close two peaks must be to count as equal,
measured in true ranges - and it is **swept across four values, never tuned**. The
whole grid is reported including the failures.

`APART`, how far apart two peaks must be to be "successive" rather than one ragged
peak, is held fixed rather than swept. The deck does not specify it, and sweeping it
too would quietly turn one honest tolerance into two tuned parameters.

## The pattern brings its own breakeven, and that is checkable before any data

Because the book supplies the target rule, reward-to-risk is **determined by the
geometry** rather than chosen. So the hit rate a pattern must reach follows
immediately:

    need = (1 + cost) / (1 + reward_to_risk)

This is the most useful thing in the file, because it means a pattern can be ruled
out on its shape alone:

| family | measured R:R | breakeven it must clear |
|--------|-------------:|------------------------:|
| double top / bottom | 0.86 - 0.88 | **55%** |
| head and shoulders, either way | 1.09 - 1.26 | **46 - 49%** |

Double tops set their target *closer* than their stop, so they need 55%. Head and
shoulders puts the head far above the neckline, so the measured move is larger than
the risk and the same pattern needs only 46-49%. **The two families are not competing
on equal terms**, and any comparison of their raw hit rates is meaningless.

## The placebo, which is the whole test

This desk has already established four separate ways that barrier geometry is a
reparameterisation: a given stop and target produce fair odds, and moving them moves
the hit rate and the payoff in step. So a pattern hitting 58% with a 0.87:1 target has
demonstrated nothing until it is compared with **the same geometry entered at an
arbitrary bar**.

That is the control: identical stop *distance* and target *distance*, taken at a
randomly chosen bar on the same instrument, twenty draws per setup so the control has a
tighter error bar than the thing it is controlling. One draw was the first version and
it was too noisy to carry a comparison everything rests on.

A pattern only earns a mark in the output when it clears **both** bars: above its own
breakeven, and clear of its placebo by more than two standard errors.

## Gold, hourly

| pattern | tol | n | R:R | need | hit | placebo |
|---------|----:|--:|----:|-----:|----:|--------:|
| double bottom | 1.00 | 1,161 | 0.87 | 55.1% | **58.0%** | **57.6%** |
| double bottom | 2.00 | 1,941 | 0.88 | 54.9% | 58.9% | 55.2% |
| double top | 1.00 | 1,125 | 0.86 | 55.3% | 55.8% | 51.4% |
| double top | 2.00 | 1,875 | 0.87 | 55.0% | 55.3% | 55.5% |
| head and shoulders | 0.25 | 77 | 1.11 | 48.7% | 53.2% | 44.9% |
| head and shoulders | 0.50 | 154 | 1.12 | 48.6% | 52.6% | 49.6% |
| inverse head and shoulders | 0.25 | 81 | 1.09 | 49.2% | 53.1% | 43.8% |
| inverse head and shoulders | 0.50 | 145 | 1.11 | 48.7% | 53.1% | 48.2% |
| inverse head and shoulders | 1.00 | 245 | 1.19 | 46.9% | **54.7%** | 45.1% |
| inverse head and shoulders | 2.00 | 422 | 1.26 | 45.6% | 49.5% | 46.5% |

**Double bottom is its own geometry.** 58.0% looks like a discovery; the placebo scores
57.6% on the same stop and target distances entered at random. The gap is 0.4 points.
A 0.87:1 trade wins about 57% of the time by arithmetic, and that is the entire
number - the pattern contributes nothing detectable. At tolerance 2.00 double top is
actually *worse* than its placebo, 55.3% against 55.5%.

**The head and shoulders family is the live one**, and it is live for a structural
reason rather than a lucky one: its geometry gives it a lower bar to clear, and it
beats its placebo at every tolerance in the sweep - inverse H&S by 9.3, 4.9, 9.6 and
3.0 points across the four. Consistency across a whole grid is worth more than a
larger number at one setting, which is the lesson `anchors.md` paid for.

The caveats are real: 77 to 427 observations per H&S cell, one instrument, and this is
sixteen cells so the best of them is the best of sixteen.

## Ten instruments, and the prediction was half right

| pattern | tol | n | R:R | need | hit | placebo | gap | +/- |
|---------|----:|--:|----:|-----:|----:|--------:|----:|----:|
| double bottom | 0.25 | 2,643 | 0.87 | 55.0% | 55.2% | 55.6% | -0.4% | 2.0% |
| double bottom | 1.00 | 10,010 | 0.88 | 54.8% | 54.5% | 55.3% | -0.8% | 1.0% |
| double bottom | 2.00 | 16,780 | 0.89 | 54.5% | 54.7% | 54.9% | -0.2% | 0.8% |
| double top | 1.00 | 9,989 | 0.88 | 54.9% | 55.2% | 54.4% | +0.8% | 1.0% |
| double top | 2.00 | 16,501 | 0.89 | 54.6% | 54.6% | 54.1% | +0.5% | 0.8% |
| head and shoulders | 0.50 | 1,278 | 1.14 | 48.0% | 44.8% | 45.5% | -0.7% | 2.9% |
| head and shoulders | 2.00 | 3,671 | 1.23 | 46.1% | 44.9% | 43.7% | +1.2% | 1.7% |
| inverse head and shoulders | 0.25 | 670 | 1.13 | 48.3% | 47.8% | 46.3% | +1.5% | 4.0% |
| inverse head and shoulders | 1.00 | 2,299 | 1.20 | 46.9% | **47.5%** | 44.9% | **+2.6%** | 2.1% |
| inverse head and shoulders | 2.00 | 3,746 | 1.25 | 45.8% | 45.3% | 44.0% | +1.3% | 1.7% |

**The double top and bottom prediction held exactly.** Across all eight cells the
placebo gap runs from -0.8% to +0.8%, every one of them inside its own error band. On
16,780 observations the gap is -0.2% +/- 0.8%. These patterns are their geometry and
nothing else, and the 58% that gold appeared to show was a 0.87:1 payoff doing
arithmetic.

**The head and shoulders prediction failed.** Gold's 52.6-53.2% became **44.8-45.2%**
on ten instruments - below its own breakeven at every tolerance, with a negative edge
in every cell. The few hundred observations on gold were not a small sample of a real
effect; they were a small sample.

Inverse head and shoulders is the only pattern left standing, and barely. Its placebo
gap is positive at all four tolerances - +1.5%, +0.7%, +2.6%, +1.3% - which is
consistent in sign and worth noting. But its hit rate clears its own breakeven at
**one** tolerance out of four: 47.5% against 46.9% needed, a gap over placebo of +2.6%
+/- 2.1%. That is **one marked cell out of sixteen**, with a margin of 0.6 points over
breakeven and an error band that nearly swallows it.

One of sixteen, at the edge of significance, is what the best of sixteen looks like.

### What the honest reading is

Chart patterns do appear to beat a random entry of the same geometry, by something like
one to two points. That is a real if unexciting statement, and it is the first thing in
this document that survived contact with ten instruments.

It is also not enough. The target rules the books supply set breakevens of 46% to 55%,
and a one-to-two point improvement over random does not carry a pattern across that
line except by luck of the tolerance. **The binding constraint is the geometry the
pattern prescribes for itself**, not the reliability of the shape.

That points somewhere specific: a pattern's *entry* may be worth a point or two, and
its *target rule* is what throws that away. Keeping the entry and replacing the
measured move with an exit chosen for the payoff rather than for tradition is the
version of this worth testing next, and it is the same conclusion the exits work
reached from the other direction.

## What this does not test

The patterns in the deck that need judgement rather than a threshold: wedges, flags,
pennants, triangles and cup-and-handle all require fitting trend lines to a subjective
selection of touches. The deck says a symmetrical triangle needs prices to "touch each
bound at least twice" and warns of "many false breakouts", which is honest and not
codeable without deciding what a bound is.

Those belong to the shape matcher rather than to a level tester - the scale-free candle
windows in `research/training/tf_batch.py`, where price level and volatility are
divided out so the same geometry at gold-400 and gold-4300 looks identical. That is the
honest route from the pattern literature into this repository, and it has not been run.
