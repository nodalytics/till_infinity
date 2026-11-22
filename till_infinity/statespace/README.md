# State Space

## What this package is

It keeps a running model of where a price *should* be, and reports how far the
price actually is from that — in units of its own uncertainty.

That number is the **surprise**: a standardised innovation. A reading of 3.0
means price arrived three standard deviations away from what the model expected
given everything it had seen. `SurpriseEdge` trades a threshold on it.

**It does not know which way price will go, and it does not claim to.** What it
knows is that something unusual happened and roughly how unusual. The direction
a rule takes from that is the *rule's* addition, not this package's, and
`surprise.py` says so in its own words: *"it claims no edge of its own... a rule
invented here would be an unmeasured one riding on a measured one's
reputation."*

So the honest shape of the thing is: **a residual, not a forecast.** The model's
job is to be a good enough description of ordinary behaviour that the
extraordinary stands out against it. Every member on the bench is competing to
be that description, and they are scored on how well they bound what comes next
rather than on where they think it is going.

## What it can and cannot claim

| | |
| --- | --- |
| **size** | forecastable, and it is the one thing that is. Price diffuses at 1.00 to 1.07 times `sqrt(h)` |
| **direction** | a coin in every test on this desk. A random walk wins the point forecast at every horizon on 17 to 21 of 39 series |
| **a price** | only `projecting.py` emits one, as a distribution over forward paths, and that distribution is **driftless by default** - which is the measurement rather than a placeholder |

The architecture rule that follows from it: *every member and component
forecasts dispersion, only the Monte Carlo emits a price, and that price is
paired with the signal rather than merged into it.*

**And the one rule that governs everything here: nothing publishes until it has
beaten a named null on held-out data.** `nulls.py` is where the nulls live.

## Where to look

| | |
| --- | --- |
| **`__init__.py`** | the contract - what may be claimed, that nothing in the package publishes, and that every horizon is time rather than bars |
| **`facade.py`** | the entry point. `Desk.read` and `Readout` are the only path a caller touches |
| **[`statespace-design.md`](../../research/docs/statespace-design.md)** | the design record: the priority list, the borrowed ideas, the members not written, and the work carried deliberately |

### The measurements

| | |
| --- | --- |
| **[`statespace-measured.md`](../../research/docs/statespace-measured.md)** | the members against each other and against a random-walk null, on seven symbols and four horizons. **S4D-Real *is* the random walk once its grid is wide enough**, and `reverting` is the only member that beats it |
| **[`statespace-signals.md`](../../research/docs/statespace-signals.md)** | what signals a move. Everything predicts **size** and nothing predicts **direction**; speed 3.12x, the residual beats the covariance, and three separate real effects were the size of the spread |
| **[`statespace-volatility.md`](../../research/docs/statespace-volatility.md)** | the one forecastable quantity, and two corrections to how much of it is available - both in opposite directions |
| **[`statespace-method.md`](../../research/docs/statespace-method.md)** | the six times an effect appeared and was not there. Four were bugs and none was caught by reading the code |
| **[`statespace-reading.md`](../../research/docs/statespace-reading.md)** | every reference read and what it gave: S4 to Mamba-3, HiPPO, LMU, BOCPD, FOCuS, Cboe, candlestick liquidity, order flow, kinetic modelling |
| **[`race-calibration.md`](../../research/docs/race-calibration.md)** | `projecting.py` against the broker: it lands on the barrier identity at 33.3% where geometry requires 33.3%, and its gap to realisation measures drift |

## The folders

61 modules in one directory had no answer to "which layer is this?", so the
internals sit in five folders and each folder's `__init__.py` is its catalogue
- what belongs there, what does not, and why.

| folder | | what it holds |
| --- | --- | --- |
| **the front door** | 10 | `actor`, `engine`, `facade`, `config`, `state`, `store`, `proposing`, `deciding`, `signalling`, `projecting`. Left at the top level deliberately: this is what a caller touches and what a reader opens first |
| **[`filters/`](filters/__init__.py)** | 16 | the family - the alternative models, one per file. The spine is `family.members()`, so a member here is a candidate **measured against the others on the same data** |
| **[`dynamics/`](dynamics/__init__.py)** | 12 | the mechanics every member shares: `Q`, the input channel, time, the band, the smoother |
| **[`evidence/`](evidence/__init__.py)** | 7 | how a member is shown to be wrong: residual diagnostics, nulls, forward facts, recovery from generated data, the sweep |
| **[`observables/`](observables/__init__.py)** | 9 | what is read off a market before any model is asked - pivots, displacements, ranges, what a level did |
| **[`composition/`](composition/__init__.py)** | 6 | more than one of something: many members, many instruments, many subjects |

**The split that matters is `filters/` against `dynamics/` and `evidence/`.**
A member is only a candidate in a contest if the things around it are held
constant, so a member that carried its own idea of where `Q` comes from would
turn a comparison between two members into a comparison of two changes at once.
And a member cannot grade itself, which is why the instruments that break it
live somewhere else.

**The folders are an internal arrangement, not part of the public name.**
`__init__.py` still decides the package's public surface and no folder
re-exports anything, so there is one list to keep in step rather than six.

## The rings of the package

| ring | modules | status |
| --- | --- | --- |
| **the contract** | `__init__.py` | what may be claimed, and the rule that nothing publishes |
| **the entry point** | `facade.py` | `Desk.read` and `Readout` - the only path a caller touches |
| **on that path** | `behaving.py`, `bounding.py`, `pacing.py`, `pooling.py`, `tails.py` | reached by every `read`; `tails.py` is consumed by `Readout.covering` |
| **the output layer** | `signalling.py` | composes a `Readout` into a `Signal` |
| **the price layer** | `projecting.py` | turns a dispersion forecast into a distribution over forward paths. The only thing here that emits a price |
| **the subject** | `subjects.py` | names the quantity being modelled before any filter touches it |
| **the members** | `reverting.py`, `linear.py`, `robust.py`, `diagonal.py`, `hmm.py`, `selective.py`, `swarm.py`, `landau.py`, `adapting.py` and the rest | alternatives on the bench, scored in `statespace-measured.md` |
| **the instruments** | `diagnostics.py`, `nulls.py`, `symmetry.py`, `spanning.py`, `dispersion.py` | how a member is shown to be wrong |

**The rings name a module the way a reader says it** - `reverting.py`, not
`filters/reverting.py` - because a ring is about what runs when, and the folder
is about what kind of thing it is. The two cut across each other on purpose:
`pooling.py` is on the `read` path and lives in `composition/`, while most of
`filters/` is not on it at all.

**Only the third ring runs on a `read`.** The members are reachable from tests
and research harnesses and from nowhere else, which is the phasing the spec
asked for: the new thing runs beside the old one and loses on its own merits
first.

## Two conventions that are fixed

**The signal is -1 to +1 with 0 neutral.** Closer to +1 is more strongly
bullish. Fixed on 2026-10-16 and not negotiable afterwards, because a signal
whose sign convention moves is worse than no signal.

That is a readability decision rather than a measured one, and it has to be: the
two candidate encodings are *the same function*, since
`tanh(x) = 2 * logistic(2x) - 1` exactly, so a `tanh` layer at weights `w` and a
`logistic` layer at `2w` order every pair of inputs identically. No measurement
can prefer one - `output-encoding.md` reports every AUC identical to floating
point. What `-1..+1` buys is that `side` is `sign`, the magnitude is the
conviction, and a deadband is symmetric by construction. What `0..1` costs is
that it reads like a probability, and this number is not one - the desk has
already shipped one quantity that was read as a probability and was not.
`Layer.as_logistic()` and `Layer.as_tanh()` convert either way.

**Every horizon is a duration, never a count of bars.** Forty steps is forty
minutes on one feed and forty hours on another, and a desk reasons in the
second kind. `projecting.PERIODS` and `rates.py` both state it.
