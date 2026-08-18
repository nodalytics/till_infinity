# Does the shape of the level set say anything

Run: `python research/harness/topology.py`, `python research/harness/structure.py`

Every feature the model carries is local to the touch. [features.md](features.md)
found none of them predicts direction beyond `side`;
[cycles.md](cycles.md) tried one non-local class — where the instrument sits in
a larger move — and got an effect that did not survive being resampled by
instrument. This tries three more, all structural:

| family | what it asks |
|---|---|
| **transit graph** | where this level sits in the network of levels price actually moves between |
| **confluence** | how many timeframes agree on this price, and how tightly |
| **shape** | what the whole level set looks like — how many, how dense, how dispersed, how much room either side |

and then asks all of them again inside volatility terciles, because structure
measured in volatility units is the one thing here that is comparable across
instruments, and a conditional effect is the likeliest shape for a real one.

**Nothing survives.** The transit graph is flat. The one property that looks
strong turns out to be `side` wearing a distance.

## 1. The transit graph carries nothing

    node   a level, as the level object itself
    edge   A -> B, once for every time a touch at A resolved and the next
           touch on that instrument was at B

So an edge is an **observed transit** rather than a geometric guess. On 11,097
touches, 9,421 happened at a level the graph had already seen, and the graph is
substantial: out-degree median 4 and max 24, through-traffic median 5 and max
54.

| property | AUC alone |
|---|---|
| in_degree | 0.508 |
| self_rate | 0.507 |
| pull | 0.503 |
| through | 0.503 |
| out_degree | 0.502 |
| reach | 0.500 |

| features | accuracy | AUC |
|---|---|---|
| side + the eight | 73.3% | 0.738 |
| plus the graph | 73.2% | 0.738 |

Gain **-0.0006**, and resampled by instrument **-0.0042 to +0.0021**. Nothing.

### The first run was measuring a bug

Worth recording, because the null it produced looked perfectly respectable.
Nodes were keyed on `(feed, interval, rounded price)`. A level is a Kalman
filter whose mean moves on every touch it absorbs, so a price key mints a **new
node every time** — the graph never accumulated. It reported 94 of 11,094
touches at a node it had seen before, an out-degree maxing at 2, and a `pull`
of 1.00 at the median: the signature of a graph with no edges, not a market
with no structure.

A null deserves the same scrutiny as a positive. This is the second time in a
week that one turned out to be instrumentation — [cycles.md](cycles.md) §2 was
the first.

## 2. Confluence and shape: one apparent finding, and what it really is

| property | AUC alone |
|---|---|
| **gap_ratio** | **0.596** |
| **gap_up** | **0.594** |
| **gap_down** | **0.407** |
| zone_rank | 0.463 |
| vol_bps | 0.487 |
| density | 0.492 |
| count | 0.496 |
| dispersion | 0.502 |
| agree | 0.504 |
| agree_intervals | 0.503 |
| cluster_vol | 0.505 |

Three properties well off 0.5, and they hold up under a strict correction. With
11 properties across 3 volatility regimes — 33 tests — each cell needs 99.84%
rather than 95% (Šidák, z = 3.165), and `gap_up`, `gap_down` and `gap_ratio`
**separate in every regime**:

| property | quiet | middle | violent | separates |
|---|---|---|---|---|
| gap_up | 0.579 | 0.606 | 0.602 | all three |
| gap_ratio | 0.579 | 0.610 | 0.601 | all three |
| gap_down | 0.427 | 0.381 | 0.414 | all three |
| zone_rank | 0.490 | 0.436 | 0.434 | middle, violent |
| everything else | — | — | — | none |

That is the strongest-looking result in any of this week's structural work.

**It is `side`.**

The three are mirror images around 0.5, which was the tell. `gap_up` is the
distance to the next level above the *arrival price*, and the level being
touched sits just below that price when price arrived from above, and just
above it when price arrived from below. So the near gap collapses toward zero
on whichever side price came from:

| | arrived from above | arrived from below |
|---|---|---|
| `gap_up` median | 3.438 | 0.873 |
| `gap_down` median | 0.824 | 3.357 |

Measured directly: **`gap_up` predicts `above` at AUC 0.691, and `gap_ratio` at
0.696**, against `above` predicting direction at 0.733. They are a noisier
encoding of the one feature already known to carry everything.

Which is exactly what §3 shows.

## 3. The honest test

| features | accuracy | AUC | gain |
|---|---|---|---|
| side + the eight | 73.3% | 0.738 | |
| plus confluence | 73.3% | 0.744 | +0.0057 |
| plus the shape | 73.2% | 0.740 | +0.0012 |
| plus volatility | 73.3% | 0.739 | +0.0004 |
| plus everything | 73.1% | 0.744 | +0.0055 |

Gain **+0.0055**, resampled by instrument **-0.0000 to +0.0113**. The interval
touches zero. Accuracy does not move at all — 73.1% to 73.3% across every
configuration, which is where it has sat in every document this week.

A model that already has `side` gains nothing from being told the same thing in
units of distance.

## What this leaves

1. **Do not add any of it.** The transit graph is flat on its own and negative
   in combination. The gap properties are `side` restated.
2. **The correction earned its place.** Three properties separated in all three
   regimes at z = 3.165 and were still an artefact. A family-wise correction
   protects against chance, not against measuring the wrong thing — only
   checking what a feature correlates with does that.
3. **The pattern across five documents is now hard to miss.** `side` carries
   the direction; everything else is either noise or a re-encoding of `side`;
   and [prior.md](prior.md) showed `side` itself is beaten by the trivial rule.
   The remaining leads are not features of price at all:
   [magnitude.md](magnitude.md) found `expected_push` orders realised profit
   7.5x, and order flow remains uncollected.
