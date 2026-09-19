# Cost-basis levels: do high-activity bands get respected?

Glassnode's long-term-holder cost basis reports how much bitcoin last moved in
each price band - 1.05m BTC between $83k and $86k with spot near $79k. The claim
is that a band holding a lot of supply is a price the market has to get through.

There is no on-chain feed here and a cost basis is bitcoin-specific anyway, so
what is built is the market-data form of the same object: the distribution of
activity over price, whose peaks are the bands. `structures/profile.py`.

Harness: [`harness/shelves.py`](harness/shelves.py). Build a profile on 600
bars, take its richest node, and ask whether price reaches it in the next 200 -
against **an arbitrary price the same distance the other way**, which is the
control [magnet.md](../docs/magnet.md) already uses.

## What it says

Re-measured after the threshold was made relative (`NODE_CONCENTRATION`), which
changed which windows produce a node at all:

| instrument | weight | windows | node | control | gap |
| --- | --- | --- | --- | --- | --- |
| spx500 | time | 54 | 75.9% | 51.9% | **+24.1%** |
| ger40 | time | 46 | 63.0% | 52.2% | +10.9% |
| gold | time | 171 | 49.1% | 42.7% | +6.4% |
| us100 | time | 84 | 48.8% | 53.6% | -4.8% |
| eurusd | time | 142 | 40.8% | 46.5% | -5.6% |
| **btc** | **volume** | 352 | 38.6% | 44.6% | -6.0% |
| Volatility 25 | time | 191 | 33.0% | 33.0% | +0.0% |
| Volatility 75 | time | 154 | 32.5% | 36.4% | -3.9% |
| Step Index | time | 258 | 33.7% | 45.3% | -11.6% |

**Pooled across the real instruments the effect is nothing**: 849 windows, 45.8%
for the node against 46.3% for the control, a gap of **-0.5%**. The three
positive instruments are the three smallest samples and the three negative ones
carry two thirds of the windows.

The synthetics say how wide the noise is. They are a generated process with no
supply and no holders, so every one of those numbers is zero by construction -
and one of them reads -11.6% over 258 windows. A +24.1% on 54 heavily
overlapping windows is not outside that.

### This replaces an earlier reading, which was wrong

The first version of this table reported a positive gap on every real
instrument that used time weighting, from +2.8% to +27.9%, and concluded that
time-weighted nodes are reached more than the control. That was measured with
the absolute threshold, which selected a different and much smaller set of
windows - and it was read as a result rather than as six numbers with no
correction for how few independent samples they contain. Windows step 50 bars
and are judged over 200, so about a quarter of them are independent: spx500's 54
windows are roughly 13 observations.

## The confound, stated

A node usually sits **behind** price, where price has spent time. The control
sits the same distance the *other* way, which in a trend is ahead. So in a
trending market the control is the more reachable of the two, and the test is
biased **against** nodes. A positive gap survives that bias; a negative one on
the hardest-trending instrument here is exactly what the bias predicts, which
is another reason not to read btc as a verdict on volume.

## What this does not say

Reached is not profitable. It says price came within half a volatility unit of
the band inside 200 bars, which is the magnet question and not a trade. Nothing
here measures a stop, a target, or what happened on arrival - which is the
question `revisits.py` asks of origins and nobody has yet asked of these.

## Refuted as a source, kept as a vote

This kills `profile` as a *place to draw levels from*: pooled over the real
instruments a node is reached no more often than an arbitrary price the same
distance away.

It does not touch the other question, which is the one it now runs for. Levels
from the four passes are **merged**, not pooled - `lv.merge` folds a candidate
into an existing level only when it falls inside that level's own zone, and
`agree()` records that both found it. So `profile` cannot draw a level of its
own that anything trades; what it can do is put a fourth name on a price that
`pip`, `run` or `origin` already drew.

Whether that agreement is worth anything is unmeasured, because it was
unmeasurable: `Level.origin` has always carried the list and nothing ever
counted it, so all 969 recorded outcomes say `pip` and nothing else. The count
is now published as `drawn_by_n` on every level call and lands in the journal
beside the outcome. Ask again with a few thousand touches behind it.

## Open: thin bands as targets, not barriers

Not measured, and it is the question this null actually points at.

The reachability test refuted the **peaks** - a busy band is reached no more
often than an arbitrary price the same distance away. It says nothing about the
**valleys**, and the idea the peaks came from has a claim about those too: price
is supposed to move quickly through a range where little traded, because there
is nothing there to stop it.

That is a different kind of claim and needs a different measurement. A busy band
is a claim about *where price stops*, which the touch machinery already scores.
A thin band is a claim about *how fast price crosses*, which is a statement
about **targets and hold time** rather than about levels - so it does not belong
in a formation at all, and building one would answer the wrong question.

What it needs instead: for each thin band the profile finds, the time price
takes to cross it, against the time to cross an equally wide band of ordinary
density the same distance away. `harness/reachable.py` already has the shape -
a funnel over what the desk actually saw, with a matched control - and
`expected_hold_s` is already journalled on every intent, so both sides of the
comparison exist.

Left undone deliberately rather than forgotten. It changes `target` and
`hold_for`, which are the two settings with live money behind them and the two
this repository has already been wrong about twice - and it is worth measuring
before anything is moved, not alongside it.
