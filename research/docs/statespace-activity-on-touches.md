# Step four also reverses: activity on `Q` loses on touches

`statespace-activity-on-production-q.md` measured activity driving the
production filter's process noise at **+0.0513 per observation on 7 of 8
instruments**, at exponent **1** rather than the 2 the price members prefer,
and said the wiring was a one-line multiply at `levels.py:1244`.

**It was measured on a close every bar.** `statespace-estimator-on-touches.md`
had just shown what that can cost: `Pooled` beat the best single member by 5.6x
on dense closes and came back **18 times worse** on touch-spaced observations.
The production filter's observations are touches, so the question had to be
re-asked where the wiring would live.

The harness is `research/ideas/activity_on_touches.py`, on the same touch
series - 150 levels from rolling extremes, 60+ touches each, log price, with
the base process noise refitted on the undriven arm first.

## It loses, and loses more the harder it is driven

| arm | loglike per touch | CRPS |
| --- | ---: | ---: |
| flat | **4.8815** | **0.000861** |
| activity, exponent 0.5 | -0.0325 | 0.000994 |
| **activity, exponent 1** | **-0.2383** | 0.001128 |
| activity, exponent 2 | -0.2754 | 0.001442 |

The `+0.0513` measured on closes becomes **-0.2383** on touches at the same
exponent, and CRPS degrades by **31%**. The ordering is monotone in the
exponent, which is the shape of a lever pushing the wrong way rather than a
noisy result: driving `Q` harder makes it worse each time.

**And the control is exactly inert.** `behaving.drives_q` allows the channel on
150 of 150 traded levels and **0 of 49** generated ones, so the generated rows
read `0.0000` at every exponent with a mean factor of `1.000`. The control
needed no flag and got none, which is the property that makes it free.

## Why, and the figure that says it

The realised mean factor on traded levels is **0.809**, not 1.0. `Pace`
normalises a bar's activity against an exponential mean of its own recent
activity, and on a touch series it only ever sees **touch bars** - a selected,
bursty subsample whose gaps are hours or days. The normaliser lags a series
like that, so the channel spends most of its time **reducing** `Q` rather than
varying it around one.

A multiplier that averages 0.809 is a filter told to trust its prior 20% more
than the base it was fitted with, on a process whose whole difficulty is
carrying belief across gaps. That is the opposite of what the close-based
result found, and it is the same failure mode `Q multipliers need mean one`
records - except here the departure is produced by the **observation process**
rather than by the arithmetic, which no amount of renormalising inside `Pace`
would fix.

## Two of two migration steps have now reversed on touches

| step | measured on closes | measured on touches |
| --- | --- | --- |
| **2**, swap the estimator | `Pooled` 5.6x better | **18x worse** |
| **4**, activity on `Q` | +0.0513 per observation | **-0.2383** per observation |

That is no longer a coincidence worth noting once. **A result measured on a
dense series is not evidence about the production filter**, whose observations
arrive only when price visits a level, and the two differ by enough to reverse
the sign of every result tested so far.

The general form is worth stating because it is cheap to apply and expensive to
skip: when a measurement will be used to change a component, measure it on the
**observation process that component actually sees**. Both of these studies
took one harness and a few minutes, and both prevented a production change that
the prior evidence supported.

## What this does to the migration

**Step 4 is closed.** The one-line multiply at `levels.py:1244` should not be
made: on the filter's own observations it costs 0.24 nats each and widens the
band by a third.

What remains of `docs/specs/2026-10-14-statespace-as-the-structures-library.md`:

* **step 5**, `bounding` against `learning/touches.py` and
  `learning/breaking.py` - untested, and the only remaining step whose premise
  has not now been contradicted;
* the **retirements** that need no replacement, starting with
  `learning/baseline.py`;
* and **anchored level discovery**, which
  `statespace-ranging.md` has since answered in part: the range is buildable
  and its edges are not support.

`pacing` keeps its place in the library and in `Desk.read`. It is measured at
**+2197 nats** on dense closes and that result stands for a caller forecasting
a price every bar. What it does not have is a claim on `levels.py`.
