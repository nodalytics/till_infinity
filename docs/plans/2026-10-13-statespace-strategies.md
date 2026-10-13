# Trading models powered by statespace: what to build and what the evidence allows

Asked for on 2026-10-13: *"start researching/testing trading models/strategies
we can use with statespace or that can be powered by it, creative entries and
exits, remember we are big on directional bets, we can even do 2 leg pairs
trading to double the risk to get big reward in small movements."*

This is the plan. It is written against what this desk has already measured,
because three of the obvious designs are already refuted and saying so first is
cheaper than rediscovering it.

## What the evidence rules out, and what it leaves

**A mean-reverting spread has no basis here.** Cointegration came back 0 of 190
pairs, 0 of 1,625 baskets at widths two to five, and 0 of 18 commodity-currency
claims against the established `-4.07` bar. The classic pairs trade - form a
spread, wait for it to revert - is betting on the one thing that has been tested
most often here and never found.

**Leverage through a tight stop costs money before costs.**
`statespace-volatility-convexity.md` measures a far target with a near stop at
**-0.0706 sigma gross, `z = -3.06`**, where a martingale reads zero and where
`trades()` reads zero on a martingale to prove the method. "Double the risk for
a big reward on a small movement" is exactly that geometry, and it is the one
geometry measured to lose before the 0.072 sigma round trip is paid.

**And single-bar direction is worth a quarter of a spread.**
`statespace-orderflow-from-bars.md` and `statespace-absorption-delay.md`: real,
8 of 8, with a mechanism and a control, flat at **0.2 basis points** across a
48-fold horizon sweep against a 1 to 5 basis point round trip.

**What is left is large and has not been built on.** Relationships are
contemporaneous and live in variance: cross-instrument volatility correlation at
a median **+0.5170** with 104 of 107 pairs beating their null, tail co-movement
at **+0.1275** on 177 of 190. The dollar-controlled commodity-currency partials
reach **-0.2260**. Activity on `Q` is worth **+2197** nats, and pooling members
improves CRPS **5.6-fold**.

So the designs below are the ones the evidence points at, in the order they
should be tried.

## 1. The two-leg structure the evidence supports: contemporaneous, not reverting

A two-leg position is still the right shape - it is the only way to hold a view
on a relationship rather than on a level - but the **trigger** has to change.

* **not** "the spread is wide, it will narrow" - that is cointegration, refuted;
* **but** "the two legs are contemporaneously linked, and one has moved while
  the other has not **yet in this bar**".

The second needs no time lead, which matters because every lagged measure here
is null. It needs the legs' linkage to be strong in the quantity measured -
variance and tails - and it has one natural expression: a **hedge** rather than
a bet. A long `USDCAD` carries a short crude position at `-0.2260` whether or
not that was wanted, so the two-leg structure's first job is to **remove** an
exposure nobody chose, not to add one.

**Arm:** take each dollar-controlled commodity-currency pair, form the
two-leg position at the measured partial, and ask whether the residual's
*volatility* is lower than the single leg's by more than the second leg's cost.
That is a Sharpe question rather than a direction question, and it is the one
the measurements support.

## 2. Entries and exits from the parts that are already measured

The creative part is not a new indicator; it is that four measured quantities
have never been connected to an entry or an exit.

**`bounding.py` gives the exit geometry a closed form.** Optional stopping with
the Broadie-Glasserman-Kou discrete-monitoring shift fixes `P = d/(u+d)` and
`T = u*d`: four quantities, two degrees of freedom. So a target and a stop
cannot be chosen independently of the win rate and the holding time - pick any
two and the other two are determined. Most strategy design here has been
choosing all four and hoping, and `least_horizon` says which combinations are
not even feasible. The measured per-family walls in `SHIFTS` make it
directional.

**The conformal band gives the stop a calibrated width.**
`statespace-conformal-band.md` reaches a PIT flatness of **1.5** at one bar
where no Gaussian band is calibrated, and `the-walk-is-the-best-calibrated-band`
records that the walk is what to use for stops. A stop at a calibrated quantile
is a different object from a stop at a round number of sigmas.

**Activity sizes the position, because it sizes the variance.** Activity on `Q`
is worth +2197 nats, which is a statement that **how far price will go** is
predictable even though which way is not. That is a position-sizing input and a
barrier-width input, and it is the single largest measured effect this desk has.

**And the absorption fingerprint says which market will behave.**
`behaving.TRAITS` now covers nineteen classes with no misclassification: traded
markets absorb, jump generators run, smooth generators are neutral. A strategy
that needs mean reversion within the bar has a measured list of where it
exists.

## 3. The directional bet that has not been tested: trade the variance, not the sign

Blue Ocean's reading in `statespace-reading-into-tests.md` applies directly.
Direction is the crowded axis and this desk has measured it closed twice. Every
uncrowded axis has paid, and they are all **"how far"** rather than "which
way".

An edge in how far has to be converted into direction to be paid **in spot** -
which is the crowded axis - but not in a **barrier or digital payoff**, where
the quantity sold is the probability of touching a level. That is what
`bounding.py` is already about, and Deriv offers those instruments on the
synthetics this desk already trades.

**Arm:** price a touch or no-touch payoff from the member's own `Q` forecast,
compare against the venue's offered price, and measure the gap. If activity on
`Q` is worth +2197 nats of likelihood, the question is whether any of that is
worth basis points against a venue that is pricing the same barrier from a
constant volatility.

This is the arm with the largest gap between what is measured and what has been
tried, and it should be first.

## 4. The order to run them in

1. **the barrier payoff against the venue's price** - converts the desk's
   largest measured edge into the one instrument that pays for it directly;
2. **the two-leg hedge** on the dollar-controlled pairs, as a variance-reduction
   question rather than a spread-reversion one;
3. **entries and exits from `bounding` plus the conformal band**, which is
   mostly wiring measured parts together and needs no new research;
4. **the maker-side version of absorption**, which is blocked on one unknown
   number - the maker fee - and not on any signal.

## What would make this a bad plan

If the barrier payoffs are priced off the venue's own generator with no margin
for the variance structure, item 1 is arithmetic rather than research and will
read zero. The honest check is cheap: compare the venue's implied volatility
against the generator's specified one on a synthetic whose sigma is published.
If they match exactly, there is no gap and item 1 is closed before it starts.
