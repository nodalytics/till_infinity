# Fading to the displacement origin: the structure is real, the trade is not

**Measured 2026-10-08.** The desk's thesis, and it was a good one: `fade-to-value`
fades a move back toward value; give "value" a definition - **the origin candle
of a displacement** - and the displacement research becomes a target rather than
an entry.

It also rescued a number that had been written off.
[`order-block-zones.md`](order-block-zones.md) measured an **82% return rate**
and could not use it, because as an entry signal a rate like that says only that
`EXPIRE` is 300 bars and 300 bars wanders back to most prices. As the **hit rate
of a target** it is the whole trade. That reframing is correct and it is why this
was worth three separate runs.

Code: [`fade_to_origin.py`](../ideas/fade_to_origin.py),
[`origin_displacement.py`](../ideas/origin_displacement.py).

## What `fade-to-value` already does

Worth establishing first, because it changed the question. Reading
`trading/strategies/swing.py`, the strategy **already trades origins**:

* it refuses unless price is within `REACH_VOL` of one - `Refusal("not_at_origin")`
* it checks freshness against `origin_*_revisits` - `Refusal("stale_origin")`
* its stop is anchored **beyond the origin being traded**, not beyond the level

So it buys at the origin below and sells at the origin above: it trades **from**
the origin, expecting it to hold. What it does not do is ask **how the origin was
made**. That turned the thesis into three distinct questions, and all three are
now answered.

## 1. Trading toward the origin

Enter against the displacement, target the origin, stop beyond the leg extreme.
Swept over four entry rules and five stop pads, 65,945 fades:

| turn | pad | n | RR | hit | needs | gap |
|---|---:|---:|---:|---:|---:|---:|
| close_against | 0.25 | 214 | 1.47 | 37.9% | 40.4% | **-2.6** |
| impulse_back | 0.25 | 154 | 0.94 | 48.1% | 51.5% | **-3.4** |
| live | 0.25 | 215 | 1.88 | 31.2% | 34.7% | **-3.5** |
| two_against | 0.25 | 202 | 1.21 | 40.6% | 45.2% | -4.6 |

**Zero of sixty cells have a lower bound above zero.**

**Waiting for the momentum to turn works exactly as hoped and gains nothing.**
The hit rate climbs from 31% to 48% as the entry waits for a reversal candle -
and RR falls from 1.88 to 0.94, because entering later is entering nearer the
target. The gap between what the trade gets and what breakeven asks stays at
-2.5 to -4.6 points the whole way. Wider pads are worse and do not reach the top
five.

That is the trade moving along a breakeven line, and it is `1/(1+N)` again: every
way of taking it buys hit rate and sells reward at close to the fair rate, and
lands a few points short each time.

## 2. Where the 82% goes

The return rate is real and the trade still fails, which is only a contradiction
until the stop is counted. In the first clean run **89-91% of fades were stopped
before the target arrived**. Price does come back to the origin; it goes further
against you first, and a stop beyond an extreme that was *just made* is close by
definition. The 77-81% figure is measured with **no stop and 300 bars**. The trade
has a stop and sixty.

## 3. Filtering the origins `fade-to-value` already trades

The most practical version: change nothing about the entry, the stop or the
freshness check - only **which origins count**. Production's own origins,
replayed through `zones_prod` exactly as `structures/drawing/origins.py` finds
them, split by whether `PUSH_N` candles of `PUSH_BODY`+ body left them. 80,754
origins:

| iv | | n | hit | R | gap |
|---|---|---:|---:|---|---:|
| 1d | displacement | 477 | 28.5% | -0.139 [-0.236, -0.035] | **+0.120 R** |
| 1d | no displacement | 9,305 | 24.5% | -0.260 [-0.285, -0.234] | |
| 4h | displacement | 985 | 26.0% | -0.219 [-0.290, -0.148] | +0.017 R |
| 4h | no displacement | 19,060 | 25.3% | -0.237 [-0.254, -0.219] | |
| 1h | displacement | 2,786 | 25.8% | -0.218 [-0.258, -0.175] | **-0.007 R** |
| 1h | no displacement | 48,141 | 26.1% | -0.211 [-0.223, -0.199] | |

**The gap shrinks as the sample grows and reverses sign on the largest one.**
+0.120R on 477 trades, +0.017R on 985, -0.007R on 2,786. A real filter shows up
most clearly where there is most data; this shows up least. And **every cell is
negative** - the filter does not turn a losing trade into a winning one.

Also worth having on its own: **only 5.3% of production origins were left by a
70%-body two-candle displacement.** The two definitions barely overlap, so the
filter would cut `fade-to-value` to a twentieth of its trades for a gain between
-0.007R and +0.120R depending on which timeframe is believed.

## What is settled

The structure is real and the trade is not, from all three directions:

| | result |
|---|---|
| trade **from** the zone | negative everywhere - 1h -0.147R over 721, barrier 48.7% against a 48.6% base |
| trade **toward** the zone | 0 of 60 cells positive, 2.5-4.6 points short of breakeven however it is entered |
| **filter** the origins already traded | no effect, and the effect it has reverses on the biggest sample |

Price returns to these levels 77-81% of the time and **it does not survive a stop
in any configuration tried**. That is a property of the market rather than a
parameter that was missed, which is worth more than another sweep.

## One honest loose end

`fade-to-value` publishes `origin_*` on only **5 of 75** closed trades, while
refusing outright without those features - so most of its live trades take a path
where its own origin logic cannot be audited from the journal. That is worth
fixing whatever happens to this thesis, because it means the strategy's central
mechanism is currently unmeasurable on the live record.
