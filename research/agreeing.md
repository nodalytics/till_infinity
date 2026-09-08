# One change point, four timeframes

Run 2026-09-08 over 8 instruments and 24 days of one-minute bars. **A change
point that shows on three or more timeframes continues; one that shows on a
single timeframe mean-reverts.** At a matched realised move the two differ by
0.54v an hour out and 9.17v a day out, and the sign of the one-timeframe
bucket is *negative* at a day.

This is [todo 7a](../docs/todo.md), option 2, deliberately taken before option
1. Six detectors into one model is the shape that
[localising.md](localising.md) has just finished watching fail - every method
there that pooled more inputs did worse than the one that pooled fewest - so
the cross-timeframe question gets asked with a single statistic first.

`confluence` already assumes agreement across timeframes means something about
**levels**. Nobody had asked it about **changes**.

## What an event is

One `Focus` per timeframe per direction, fed that timeframe's own closes scaled
by a causal EWMA of its own step size, reset when it fires at the shipped
threshold of 12 nats. Readings are taken on a 5m grid, and a timeframe is
*calling a change* if it fired at any point in the hour ending now.

**A common window rather than each timeframe's own bar length.** The first
version let a call stand for one bar of its own timeframe, which gives the 5m
detector five minutes to be agreed with and the 60m one an hour - so four-way
agreement became an artefact of the fastest clock rather than a fact about the
market. An hour for all four is what a person means by "these timeframes are
saying the same thing".

**4h is not in the list and the todo asked for it.** The research database
holds 24 days per feed from its best venue, which is 144 four-hour bars -
fewer than the warmup, let alone a sample. 30m stands in its place and the 4h
arm waits for data. Timeframes are 5m, 15m, 30m and 60m.

| feed | grid bars | events | 1 tf | 2 tf | 3 tf | 4 tf |
| --- | --- | --- | --- | --- | --- | --- |
| btc | 6,919 | 761 | 443 | 169 | 75 | 74 |
| eth | 6,919 | 857 | 509 | 180 | 87 | 81 |
| gbpusd | 4,747 | 411 | 261 | 77 | 57 | 16 |
| eurusd | 4,759 | 395 | 293 | 36 | 48 | 18 |
| usdjpy | 4,747 | 383 | 281 | 38 | 50 | 14 |
| gold | 4,582 | 347 | 181 | 82 | 46 | 38 |
| spx500 | 5,623 | 840 | 724 | 116 | **0** | **0** |
| us100 | 5,625 | 704 | 548 | 156 | **0** | **0** |

**The indices never agree with themselves.** spx500 and us100 produce plenty of
single-timeframe calls and not one three-way agreement in 24 days. That is the
same instruments [localising.md](localising.md) found barely move on `runs`
(0.01v), and it is a finding rather than a gap: whatever this measures, those
two do not do it.

## The confound, and why the first table is worthless alone

**A 60m change is a bigger move by construction.** It takes more to trip a
detector on a bar twelve times longer, so "more timeframes agree" predicts "a
big move happened" with no market content whatever. The pooled table shows the
confound rather than the effect:

| agree | n | median 1d forward | fraction > 0 | **trigger** |
| --- | --- | --- | --- | --- |
| 1 | 3,240 | -0.739v | 46.9% | **3.96v** |
| 2 | 854 | 1.971v | 54.9% | **5.14v** |
| 3 | 363 | 4.646v | 58.4% | **10.08v** |
| 4 | 241 | 7.347v | 63.5% | **14.95v** |

The trigger column - how far price had already travelled when the call came -
rises from 3.96v to 14.95v across the buckets. Any reading of the forward
column that ignores it is measuring the detector's own threshold.

## Conditioned on the realised move

Events split into deciles of trigger, one-timeframe compared with
three-or-more inside each decile. Only the top four deciles carry 30 of both,
so **this is a claim about large realised moves and nothing else.**

| decile | trigger | n 1tf | n 3+tf | 1tf | 3+tf | gap |
| --- | --- | --- | --- | --- | --- | --- |
| **1 hour forward** | | | | | | |
| 7 | 6.19-7.78 | 336 | 52 | 0.243v | -0.336v | **-0.580v** |
| 8 | 7.78-9.90 | 313 | 66 | -0.447v | 0.379v | 0.826v |
| 9 | 9.90-12.94 | 266 | 113 | -0.597v | 0.719v | 1.316v |
| 10 | > 12.94 | 124 | 250 | -0.184v | 0.355v | 0.538v |
| **pooled** | | 1,039 | 481 | **-0.222v** | **0.320v** | **0.541v** |
| shuffled | | 3,240 | 604 | -0.074v | 0.000v | 0.074v |
| **4 hours forward** | | | | | | |
| pooled | | 1,039 | 481 | 0.443v | 2.245v | **1.801v** |
| shuffled | | 3,240 | 604 | 0.444v | 0.364v | -0.080v |
| **1 day forward** | | | | | | |
| 7 | 6.19-7.78 | 336 | 52 | -0.510v | 2.318v | 2.828v |
| 8 | 7.78-9.90 | 313 | 66 | -0.652v | 7.439v | 8.090v |
| 9 | 9.90-12.94 | 266 | 113 | -1.638v | 7.707v | 9.345v |
| 10 | > 12.94 | 124 | 250 | -4.328v | 9.057v | 13.384v |
| **pooled** | | 1,039 | 481 | **-1.244v** | **7.924v** | **9.169v** |
| shuffled | | 3,240 | 604 | 0.163v | -0.500v | -0.663v |

**The null is the agreement labels shuffled across the same events.** It keeps
every outcome, every trigger and the whole overlapping-window structure and
breaks only the link between the label and the result. It returns 0.074v,
-0.080v and -0.663v against the real 0.541v, 1.801v and 9.169v. The label is
doing the work.

**The one-timeframe bucket is negative at a day.** This is the part worth
sitting with. It is not that a confirmed change is a stronger version of a
lone one - a lone fast-timeframe change point, at a large realised move, is
followed by price giving *back* 1.24v, while a confirmed one continues 7.92v.
They are not the same object at different strengths. They point opposite ways.

## Per instrument, because one trend could carry the whole thing

Forward windows of a day overlap heavily on 5-minute events, so the effective
sample is far smaller than 481 and one instrument having a single long trend
inside 24 days could produce the pooled number by itself. Trigger above the
60th percentile:

| feed | n 1tf | n 3+tf | 1 hour gap | 4 hour gap | 1 day gap |
| --- | --- | --- | --- | --- | --- |
| btc | 212 | 118 | 0.449v | 1.245v | 21.024v |
| eth | 240 | 128 | 0.019v | 1.384v | 6.227v |
| eurusd | 138 | 55 | 3.433v | 4.610v | 5.315v |
| gbpusd | 84 | 51 | 1.281v | 1.828v | 2.767v |
| gold | 70 | 73 | 3.215v | 4.423v | 18.237v |
| usdjpy | 135 | 56 | 1.143v | **-6.795v** | 34.301v |
| spx500 | 86 | 0 | - | - | - |
| us100 | 74 | 0 | - | - | - |
| **ahead on** | | | **6 of 6** | **5 of 6** | **6 of 6** |

Six of six at an hour and at a day, five of six at four hours. usdjpy is the
one reversal and it is positive at both other horizons, which reads as noise
rather than as a counterexample.

## What this does not establish

* **24 days.** That is the whole database at 1m. Everything here should be
  re-run when there is a quarter.
* **Overlapping windows - now bootstrapped, and only the day survives.** A day
  forward is 288 grid bars and events are far more frequent, so consecutive
  observations share most of their outcome. The shuffle null says the *label*
  matters and says nothing about precision. Resampling whole **feed-days** with
  replacement - the block chosen to match the dependence it has to survive -
  gives:

  | horizon | gap | 90% interval | resamples positive |
  | --- | --- | --- | --- |
  | 1 hour | 0.541v | **[-0.549v, 1.502v]** | 81.8% |
  | 4 hours | 1.801v | **[-0.470v, 3.968v]** | 90.8% |
  | **1 day** | **9.169v** | **[0.644v, 14.876v]** | **96.5%** |

  125 feed-days, 400 resamples. **The hour and the four-hour straddle zero and
  are not established** - this document reported them as results and should
  not have. The day horizon excludes zero and survives.

  Even there the interval is wide: what is established is that the gap is
  **positive**, not that it is nine volatility units. A lower bound of 0.644v
  is a different claim from a point estimate of 9.169v, and any sizing built on
  this should use the former.
* **Only large moves.** The conditioning has enough of both buckets in the top
  four deciles of trigger and nowhere else. Below about 6v of realised move
  this says nothing.
* **Nothing about cost.** These are mid-price moves in volatility units with no
  spread, no slippage and no fee. `research/reachable.md` and the ~3.5% taker
  fee are what turn a v-figure into a trade.
* **Not a strategy.** The obvious use - refuse a signal whose change point is
  visible on one timeframe only - is a *gate*, and this repository has a long
  record of gates that measured well and cost money. It belongs in the journal
  beside the outcome first, which is what `origin_confirmed` is already doing
  for the localisation version of the same idea.

## What to do with it

1. ~~**Publish the agreement count as a feature.**~~ Built on 2026-09-08.
   `Engine._note_change` runs one `Focus` per direction per (feed, timeframe)
   over `CHANGE_INTERVALS`, scaled by that timeframe's own volatility, and
   `Engine.changing` reports `change_up_tf`, `change_down_tf` and
   `change_watched_tf` onto every call. **Nothing gates on them.**

   Three decisions worth recording:

   * **A count, not a flag.** One timeframe and three timeframes are followed
     by moves of opposite sign, so collapsing them to "something fired" would
     throw away the entire result.
   * **`change_watched_tf` as well**, because one-of-one and one-of-four are
     different readings and a restart warms the timeframes at different
     speeds. Without it they are indistinguishable in the journal.
   * **Absent rather than zero** when no timeframe has a detector yet, the rule
     `LevelRange.features` already follows: a missing key is a missing reading,
     and a zero is the claim that four timeframes looked and saw nothing.

   Two things the tests caught that would have shipped quietly. A detector
   that has never fired stores a timestamp of `0.0`, which on a live clock is
   nineteen thousand days in the past and never matters - but a **replay from
   the epoch** puts it inside the one-hour window, so every silent timeframe
   would have reported a change and every backtest journal would have filled
   with confident nonsense. And the detectors ride on the engine, which is
   persisted whole rather than as a `Restorable` dataclass, so a round trip
   through the codec is asserted: without it they cold-start on every deploy
   and 1h never accumulates enough to fire at all.

   `change_tally` logs the spread on every save, for the same reason
   `origin_tally` does - a reading that silently never fires is the shape
   [inert.md](inert.md) catalogues, and this is the eleventh entry.
2. ~~**Block bootstrap the day-horizon gap.**~~ Done. It survives at a day
   (90% interval [0.644v, 14.876v]) and does **not** at an hour or four hours.
   The interval is wide, so the established claim is the sign and not the size.
3. **Re-run with 4h** when the database has the bars for it. The todo asked for
   it, and 144 bars is not an answer.
4. **Ask why the indices never agree.** Zero three-way agreements on two
   instruments over 24 days is either a property of index futures or a
   property of how this feed is sampled, and those have different consequences.
