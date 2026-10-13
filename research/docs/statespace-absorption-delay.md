# The horizon was not the lever: the absorption edge is flat at 0.2 bp

`statespace-orderflow-from-bars.md` found a real directional signal and closed
it on cost: real markets close nearer the middle of their range than a matched
walk on 8 of 8 instruments, the absorption continues one bar, and it earns
about a quarter of a spread. Two independent arguments then said the **horizon**
was the lever rather than the classifier:

* **the cost arithmetic** - the edge is a fixed percentage of whatever room the
  horizon offers, room grows with the horizon, and one round trip costs the
  same whether it is held an hour or two days;
* **the loop framing** - `statespace-reading-into-tests.md` notes that an
  absorbing market is a **balancing loop**, which has exactly two parameters, a
  gain and a **delay**, and only the gain at one bar had been measured.

Both were wrong, in the same way. `research/ideas/absorption_delay.py` sweeps
nine horizons.

## The edge does not move

Median over eight traded instruments, with the null recomputed at each horizon
because overlapping targets at `h = 48` are far more serially correlated than
at `h = 1`:

| h | AUC | `\|2A-1\|` vs h=1 | `1/sqrt(h)` predicts | room, bp | **edge, bp** | net, bp |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.4844 | 1.00 | 1.00 | 5.51 | **0.14** | -0.82 |
| 2 | 0.4848 | 0.97 | 0.71 | 7.92 | **0.25** | -0.78 |
| 3 | 0.4861 | 0.89 | 0.58 | 9.91 | **0.27** | -0.73 |
| 4 | 0.4908 | 0.59 | 0.50 | 11.56 | **0.19** | -0.76 |
| 8 | 0.4931 | 0.44 | 0.35 | 17.54 | **0.22** | -0.79 |
| 12 | 0.4955 | 0.29 | 0.29 | 22.38 | **0.18** | -0.81 |
| 24 | 0.4984 | 0.10 | 0.20 | 33.54 | **0.15** | -0.69 |
| 48 | 0.4998 | 0.01 | 0.14 | 48.84 | **0.28** | -0.91 |

**The edge column is flat.** It never leaves the band 0.14 to 0.29 basis points
across a 48-fold change in horizon, while the round trip is 0.93 to 5.00 basis
points. `wick` gives the same table with the same flat edge.

The two effects cancel almost exactly. Room grows slightly *faster* than the
square root of the horizon - 8.9x by `h = 48` against the 6.9x a diffusion
predicts - and the signal decays at least as fast. The product is constant, so
there is no horizon at which the arithmetic turns.

**Median net is negative at every single horizon.** Nineteen of 144 cells both
beat their null and clear their cost, and **0 of 54 generated cells do** - so
the nineteen are not an artefact of the method, they are the spread of a
distribution whose middle is below zero. The best single cell is `XAUUSD` wick
at `h = 48` for `+0.46` bp, which is one cell out of 144.

## What was learnt anyway: the loop's delay is about three bars

The sweep was worth running for the decay shape, which is the loop parameter
nobody had measured. Up to `h = 3` the signal decays **more slowly** than
`1/sqrt(h)` - 0.89 against 0.58 - so absorption genuinely persists past a
single bar. At `h = 12` the two are equal, and beyond it the signal collapses
faster than diffusion: 0.10 against 0.20 at `h = 24`, and 0.01 against 0.14 at
`h = 48`.

So the balancing loop has a **gain of about 3% of a move and a delay of about
three bars**, decaying to nothing by twelve. That is a complete characterisation
of the mechanism, and it is a short-memory one.

It also explains the flat edge. A mechanism with a three-bar memory cannot
collect a horizon's worth of room, so lengthening the horizon adds variance
without adding signal - which is exactly what a flat edge against a growing
room looks like.

## The honest arithmetic, and the cost that is not zero

The cache reports a **zero** spread for the majors on this demo feed, and
reading that as free is how a quarter-of-a-spread edge becomes a trade on
paper. This harness substitutes a realistic round trip where the cache says
zero - 0.93 bp for EURUSD, 1.20 for sterling and gold, 5.00 for silver and
crude - and those are the figures in the table.

That substitution is the single most important line in the file. With the
cache's zeros, 60 of 144 cells "pay".

## Where this leaves the directional question

Closed on this mechanism, and closed properly rather than by assertion. The
signal is real - 8 of 8, with a mechanism, a control and now a measured decay
shape - and it is worth **0.2 basis points** against a cost between 1 and 5.
Nothing about the horizon changes that, and a better classifier cannot either:
doubling the AUC's distance from 0.5 doubles 0.2 bp.

What is left is not a signal problem.

* **The maker fee.** Absorption pays the side that *absorbs*, which is a
  resting order rather than a crossing one. A maker is not paying the 1 to 5
  basis points, it is **earning** them, and the signal becomes a filter on
  which quotes to leave up. This desk has recorded the Polymarket taker fee at
  about 3.5% and the **maker fee as unknown** - and unknown is now the single
  number standing between this result and a different answer.
* **The venue.** 0.2 bp is below every retail spread measured here. It is not
  below every spread that exists.
