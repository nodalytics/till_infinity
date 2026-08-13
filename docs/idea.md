# The idea

A directional call is only worth making when the price structure and the
fundamentals point the same way. Most setups see one or the other. This one is
built to see both at once, and to write down why it thought so at the time.

Five things follow from that, and they are the five parts of the project.

## 1. Structure needs more than one view of the price

The same instrument is quoted by six brokers at once, so the *differences* carry
information a single feed cannot: which venue leads, where quotes diverge, when
liquidity thins ahead of a move. That is why `prices` collects one instrument
from many venues rather than many instruments from one.

It also makes a whole class of error detectable. A feed that stops moving while
five others keep going is a fault, not a market opinion, and no amount of
cleverness applied to that feed alone would reveal it — the only evidence is the
disagreement. Every anomaly feature is therefore a comparison against the median
of the *other* venues, never against a constant, and never against a group the
venue is itself part of.

## 2. Finding the structure is arithmetic, not judgement

`structures` measures every venue against the others and learns, online, what
normal looks like for each — "unusual" only means anything relative to
something, and a constant threshold is the wrong something. It runs
continuously, independently of any model provider, and does not stop when one
is down or unpaid.

The larger half is **key levels**: the prices price keeps turning at, and which
way it goes from what happened last time it arrived *from that side*. Three
ideas carry most of the weight.

**A level is where volatility turns, not where price poked.** The leg coming in
and the leg going out meet at the **origin**, and that is the level. The wick
beyond it is not a second level — it is how far past the first one price was
pushed, which makes it the *width* of the zone rather than its position. Feed
the extreme to the filter instead and every level drifts outward by whatever the
last wick happened to be.

**And an origin spans periods, not bars.** The legs are runs of volatility, and
a run can be six bars on the 3m or most of a session on the daily. The origin is
where those two runs meet — which is why the same price keeps appearing across
`1d`, `5m` and `3m` in the confluence view: one intersection, measured at three
resolutions. The implementation currently approximates this at a bar boundary;
[levels.md](levels.md) sets out what locating it per run would take, and why it
should make the timeframes agree more sharply rather than less.

**A level does different things from each side.** The same price met from below
and met from above are two different objects — one is a ceiling being tested,
the other a floor — so every statistic is kept per approach side. That
asymmetry is what turns "will it hold" into an answer worth having: *given price
arrived from this side, P(pushed up) is p, the expected push is n volatility
units, against a base rate of q*.

Everything is measured in **volatility units**, where `1v` is one typical move
for that instrument on that timeframe. It is what lets gold and EURUSD, 3m and
1w, be compared without per-instrument tuning — and what makes a six-pip move in
a dead session read as the large move it is.

## 3. Fundamentals separate a structure from a coincidence

A move with a release behind it is a different animal from the same move on a
quiet calendar. `news` keeps the economic calendar, the headlines and central
bank reserves alongside the prices, on the same clock.

## 4. Judgement has to happen where both are visible

`agents` puts a model over the stored data with read-only tools, and tells it
plainly that "nothing is happening" is a correct answer. Most windows are.

Judgement is deliberately the *last* layer and the only optional one. The
collectors, the levels model and the notifications all run without a credential,
because a system whose always-on half inherits the availability of its
occasionally-absent half is not always-on.

## 5. Every call gets written down with its reasoning

`journal` records what was decided, *why at that moment*, the state it was
decided from, and what happened afterwards. Prices can be recomputed forever;
the reasoning cannot be reconstructed at all once it is lost — which is what
makes it the one thing worth capturing from day one.

It is also what makes the system able to learn from itself. A resolved level
call plus the features it was made from is a labelled example, and
[`facto.py`](structures.md) fits interactions between those features once enough
have accumulated. That is only possible because the reasoning was written down
before the outcome was known.

## What is not claimed

No performance figures. Enough outcomes have to resolve first, and the honest
number of them is small — the counter deliberately restarts whenever a
measurement bug is fixed, because examples recorded under a broken ruler
describe a model that no longer exists.

The system is built to be wrong in ways that can be seen: every conditional is
reported next to its base rate, every claim carries the count behind it, and a
call that merely restates the base rate is not sent at all.
