# The leads fail on unseen instruments, the switches barely touch the live book, and the news gates are blind before a print

Measured 2026-09-24 on the lab. Two checks that `directional-questions.md` and
`crash-timing.md` left open, and a production defect the second one exposed.

| harness | question |
| --- | --- |
| [`oos.py`](../harness/oos.py) | do the three surviving leads hold on instruments the search never touched? |
| [`livebook.py`](../harness/livebook.py) | what would the spike switch and the release gate have done to the trades the desk actually took? |

## One: the three leads, on seven unseen crosses

The leads each cleared two to three standard errors among dozens of cells - the profile
chance produces. The cheapest decisive test is the same code on instruments nothing was
fitted to. The lab's broker bars hold seven FX crosses that were in no earlier study -
AUDJPY, CHFJPY, EURAUD, EURCHF, EURGBP, EURJPY, GBPJPY - with far more history than the
original sample: 15m back to 2024, 1h to 2018, daily to 1993. Unchanged code, thresholds and
split (fit on each series' first 60% by time, score the last 40%, both halves reported).
`spikerisk.load` now reads the lab's bars through venue `SEQLAB`, leak check included.

| lead | original | on the unseen crosses | verdict |
| --- | --- | --- | --- |
| intraday short models, 1h bars, 5-hour race | **+0.155 +- 0.054** gross, both halves | +0.020 +- 0.025 | **closed** |
| intraday short models, 15m bars, 1-2 hours | +0.12 gross, 2.3 SE | +0.08 to +0.12 gross, ~3 SE, both halves - **and the long models the same** (+0.11 to +0.12) | not a short edge; see below |
| daily +3:-1 longs, model top fifth | +0.10 net, t = 2.9 | +0.016 net, t = 0.6 | **closed** |
| daily pair-spread reversion at \|z\| > 2 | +0.11 net, t = 2.0 | +0.016 net, t = 0.4 (EURJPY/GBPJPY, AUDJPY/CHFJPY, EURCHF/EURGBP) | **closed** |

**The one thing that did not vanish is not the lead.** At 15m on the crosses, the top 5% of
*both* the long and the short models win the 1-2 hour race more than chance, by +0.08 to
+0.12R before costs, in both halves. The lead was that shorts worked and longs did not; here
both sides work equally, which says the model is picking *which bars resolve cleanly*, not
which way. And a spread costs about 0.11-0.15R at those horizons on FX, which takes it to
roughly zero. Worth one line in the next re-test; not worth building.

## Two: the switches on the live book

325 closed live trades from the lab's journal copy (26 August - 10 September 2026; the copy is
dated the 10th - the production journal was deliberately not read off a two-core box).
Total **-871.08**, mean **-0.174R**. Each trade's `tr_percentile` at entry was computed from the
lab's broker bars exactly as production computes it (182 of 325 resolved; the rest are feeds or
periods the lab's bars do not hold), and the release gate was run through **production's own
`Context.ahead`**, with the production cap.

**The spike switch** would have halved 25 of those 182 trades:

| | n | mean R | profit | exits |
| --- | ---: | ---: | ---: | --- |
| quiet (< 0.8) | 157 | -0.213 | -6.06 | clock 39%, target 28%, stop 20%, stale 13% |
| loud (>= 0.8) | 25 | -0.084 | -63.28 | clock 48%, target 28%, stop 12%, stale 12% |

Total on those trades -69.34 flat against **-37.70 switched**; max drawdown 709.9 against 694.7.
The loud trades lost less per unit of risk (-0.084R against -0.213R) but more money, and they
carried more of it: 17.11 at risk on average against 14.11. Halving them saved about 32. Directionally what the research predicted,
on a sample far too small to confirm it.

**The release gate** would have refused **5 of 317** eligible trades, worth -5.94. The live
book's planned holds are short - a median 30 minutes, and trades actually lasted a median 8.5 -
so few of them reach a release. On this book the gate is insurance, not a return.

Whole book: flat -871.08, gate -865.14, gate and switch **-845.18**.

## Three: the news gates cannot see a release coming

Replaying the gate exposed a defect in `trading/context.py`. `observe_event` calls
`self._forget(float(when))` with the **event's own scheduled time** as "now", and `_forget`
drops every release older than now minus 75 minutes. Both calendar providers
(`news/calendar.py`, ForexFactory and TradingView) publish in date order and fetch the week
ahead, so the furthest-out release arrives last and prunes everything before it.

Fed one real week of the calendar (27 releases around a Non-Farm Payrolls print):

| order fed | releases kept | 10m before NFP: `blackout` | 1h before, 2h hold: `ahead` |
| --- | ---: | --- | --- |
| **date order - how the providers publish** | **1** | **no** | **no** |
| newest first | 27 | yes | yes |

**Live, the "before the print" side of both the existing news blackout and the new
`release_in_hold` gate is effectively blind.** The "after" side works by accident: a release is
republished the moment it prints (`news/service.py` marks on `actual`), which puts it back in
memory with its own time as "now". So, if a live poll arrives in date order - the parsers keep
the providers' order and both calendars are chronological, but no live poll was watched for
this - the desk has been standing aside for 15 minutes after prints and almost never for the
10 minutes before them. Confirming it is one log line: the size of `Context._events` after a
poll.

`livebook.py` scores the gate as intended by feeding the calendar newest-first; that is the
number above. The fix is small - prune against the query time in `blackout`/`ahead`/`upcoming`
(each already receives `now`), not against the event being stored - and it wants a test that
feeds a week in date order and asserts the gate fires before a print.

## What follows

* **Fix the calendar pruning before relying on either news gate.** It is the only item here
  that changes live behaviour today. **Fixed 2026-09-24**: `observe_event` no longer prunes,
  and `blackout`, `ahead` and `upcoming` prune against the time they are asked about;
  `tests/test_calendar_order.py` feeds a week in date order and asserts both gates fire
  before the print (all six fail on the old code).
* **Turn on the spike switch** (`TRADING_SPIKE_ABOVE=0.8`): nothing on the live book argues
  against it, and the research does not change.
* **The release gate is low-stakes on this book** - 5 of 317 trades. Worth enabling once the
  pruning is fixed, for the tail it removes rather than the return.
* **The directional leads are closed**, except the note on 15m race resolution above.
