# Statespace into production: what goes in, what comes out, and in what order

Asked for on 2026-10-14: *"we want to bring statespace into prod, so we have to
clear the others to retired and start implementing and wiring statespace"*, and
then the question this plan exists to answer - *"what is going into statespace
and what is coming out"*.

## Where things stand before anything moves

**Statespace is wired into nothing.** It is imported once outside itself, by
`shared/codec.py`, and only so `CODEC_UNPERSISTED` can be discovered. The
package was built deliberately standalone and deletable, which is why this is a
migration rather than a switch-over.

**And nothing in production is a free orphan.** Every candidate for retirement
is imported by at least one live module - `zma` by six, `anomaly` and `touches`
by four - so each retirement is the four-step procedure in
`research/retire/README.md` and not a `git mv`.

| production module | lines | what it does | importers |
| --- | ---: | --- | ---: |
| `engine.py` | 3,303 | orchestration | - |
| `service.py` | 1,979 | the service loop | - |
| `reactions.py` | 1,821 | touch history to a directional call, and the publish gate | - |
| `levels.py` | 1,529 | **where levels are**, plus a Kalman over price, slope and acceleration | - |
| `cycles.py` | 1,044 | online z-score, nested timeframes, turn prediction | 2 |
| `zma.py` | 548 | attention-weighted z-score, "scored before it is ever given a vote" | 6 |
| `learning/breaking.py` | 416 | will this level break | 1 |
| `learning/touches.py` | 410 | P(band touched) over the next bars | 4 |
| `learning/facto.py` | 397 | factorisation machines | 1 |
| `conformal.py` | 338 | **zone width**, calibrated against what touches did | 2 |
| `learning/baseline.py` | 329 | "is the kNN buying anything?" | 1 |
| `learning/anomaly.py` | 322 | online anomaly detection | 4 |

## What goes in, with the measurement that earns it

Only four things in `statespace` have a measured claim on a production job.
Everything else in the package is either a member nothing has chosen yet or a
measurement tool.

| goes in | replaces | measured |
| --- | --- | --- |
| `pooling.Pooled` with `adapt=True` | the hand-set `Q` inside `levels.Kalman` | **5.6x** on CRPS over the best single member, then **2.7x** again from `Adapting`; PIT 37.77 to 7.89 |
| `pacing.Pace` on `Q` | nothing - a new input | **+2197** nats median against the clock's +675, 8 of 8; and **+0.0513/observation on the production filter itself**, 7 of 8, at exponent 1 |
| `bounding` | `learning/touches.py` and `learning/breaking.py` | the optional-stopping identity fixes two of four barrier quantities once two are chosen, with measured per-family walls |
| `behaving.TRAITS` | nothing - a new guard | 19 classes, no misclassification; says per instrument whether an activity channel can do anything |

**The conformal band is the one that is measured and not ready.** It reaches a
PIT flatness of **1.5** at one bar where no Gaussian band is calibrated, and
production's `conformal.py` is a *different* object - it calibrates a zone width
against touch outcomes rather than forming a predictive distribution. The
statespace version lives in a **research harness**, not the library. It has to
be moved in before it can replace anything, and that is a prerequisite rather
than a step.

## What statespace cannot replace, and this is the important part

**Level discovery.** `levels.py` is 1,529 lines and only a fraction of it is the
Kalman. The rest answers "where are the levels" - pivots, confluence, zones,
side statistics, experience - and **statespace has no counterpart for any of
it**. It models a price; it does not find the prices that matter.

So the migration is narrower than it sounds: statespace replaces **the estimator
inside** `levels.py`, not `levels.py`. Anyone reading "bring statespace into
prod" as "replace levels.py" is reading it wrong, and the plan has to say so
before the first commit rather than after.

The same holds for `engine.py` and `service.py`: orchestration, journalling and
the bus have no statespace equivalent and are not in scope.

## What comes out, in order of how safe it is

Following `research/retire/README.md`: the code and its tests move to
`research/retire/<name>/`, every import, CLI command, service entry and setting
is removed so the live system has no path to it, and **the research docs that
cite it stay where they are and keep citing it** - the findings did not stop
being true.

1. **`learning/baseline.py`** - its own docstring is "is the kNN buying
   anything?". That is a comparison, and a comparison that lives in production
   is a harness in the wrong directory. One importer. Retire first because
   nothing downstream reads a number from it.
2. **`zma.py`** - "recorded and scored before it is ever given a vote". Six
   importers, which is the work, but by its own description it has no vote, so
   removing it should change no decision. **Verify that claim before moving it**:
   six importers is six chances that something started reading it.
3. **`learning/facto.py`** and **`learning/anomaly.py`** - factorisation machines
   and online anomaly detection, both ML side-channels. `anomaly` has four
   importers. These are the two where River is the live question rather than
   statespace: `river.anomaly.HalfSpaceTrees` does the same job, and the honest
   test is whether either beats the other before one is retired for the other.
4. **`learning/touches.py`** and **`learning/breaking.py`** - these have a real
   statespace replacement in `bounding`, so they retire **after** it is wired
   and scored against them, not before.
5. **`reactions.py`'s directional machinery** - last, and only on a decision
   this plan does not make. Direction has been measured closed twice: a gate
   that finds a planted drift at `z + 2.90` earns 2% of a spread, and the
   absorption signal is real on 8 of 8 and earns **0.2 basis points** against a
   1 to 5 basis point cost. If the desk accepts that, most of 1,821 lines is
   computing a number that cannot pay. If it does not, nothing here changes.

**`cycles.py` and `conformal.py` are not on this list.** `cycles` has no
statespace counterpart that has been scored against it, and `conformal` does a
job the statespace band does not do yet.

## The order to actually do it in

Each step ends in a measurement, and no step starts before the previous one's
measurement exists.

1. **Move the conformal band into the library.** It is measured at PIT 1.5 and
   it is in a harness. Nothing else can be judged against a calibrated band
   until it is importable.
2. **Score `Pooled(adapt=True)` against `levels.Kalman` on real touches.** The
   2.7x and 5.6x are on one-step closes; the production filter's observations
   are **touches**, which arrive irregularly. `statespace-activity-on-production-q.md`
   already showed the production filter wants a process noise **16,384 times**
   its constant, so the estimator is the right place to start and the gap is
   likely large.
3. **Wire `pacing` at `levels.py:1244`**, which is a one-line multiply at a
   single call site - the only place `drift_per_hour` is supplied - gated by
   `behaving.drives_q`. Measured at exponent **1** there, not the 2 the price
   members want.
4. **Then** `bounding` against `touches.py` and `breaking.py`, and only then
   retire them.
5. **Retire 1 and 2 from the list above** at any point; they are independent of
   the above and need no replacement.

## What would make this plan wrong

If `Pooled` on **touch-spaced** observations does not beat `levels.Kalman`, step
2 fails and steps 3 and 4 lose most of their value, because the estimator is
what the rest hangs off. That is a cheap thing to find out and it is why it is
step 2 rather than step 5.

The measured risk is the other direction: the production filter is
**over-smoothed** - its process noise pinned at the top of a grid running to
16,384x - and an estimator that lags the price makes a zone sit in the wrong
place. Fixing that changes zone widths, which moves stops, which changes what
the desk trades. **Step 2 is a measurement, not a deployment**, and the first
deployment in this plan should be a shadow that journals what it would have said.
