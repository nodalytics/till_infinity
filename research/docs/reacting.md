# There is no seconds-scale edge after a call, and the spread is twenty times what there might have been

A `down` call went out on AUDJPY, price fell for a few seconds and came back.
The idea it suggested was a strategy that trades the *reaction* to our own call
rather than the level - in fast, out fast, before the move decays. Working name
`reaction-scalp`: sweep-aware's shape at speed, entering on a small pullback,
exiting on a trail, with the hold weighted by the calling timeframe.

**It does not exist.** Measured on real ticks from the broker's own feed, the
excursion after a call is indistinguishable from the excursion after a random
moment on the same instrument, at every horizon from one second to five
minutes.

## The measurement

`research/harness/decay.py`, over **1,682 directional calls** joined to
millisecond ticks pulled from the MT5 bridge (`copy_ticks_range`), with
**8,962 matched controls** - same feed, same sign, a random moment in the same
window.

The control is the whole test. Price moves 0.3v in *any* thirty seconds, so the
excursion after a call means nothing on its own; the number that matters is the
excursion after a call **minus** the excursion after a random one. Without that
this would have rediscovered volatility and reported it as alpha.

| horizon | call | control | **edge** | **net of spread** |
| --- | --- | --- | --- | --- |
| 1s | -0.0031 | -0.0012 | -0.0019 | **-0.1607** |
| 2s | +0.0038 | +0.0006 | +0.0033 | **-0.1555** |
| 5s | -0.0031 | -0.0005 | -0.0026 | **-0.1613** |
| 10s | +0.0030 | +0.0017 | +0.0013 | **-0.1574** |
| 30s | -0.0045 | +0.0051 | -0.0096 | **-0.1683** |
| 60s | -0.0107 | +0.0042 | -0.0149 | **-0.1736** |
| 300s | -0.0533 | -0.0097 | -0.0436 | **-0.2023** |

The edge column oscillates between **-0.015 and +0.003 volatility units** and
changes sign four times. That is noise with a decimal point.

## The spread is the whole story

**Median spread: 0.159 volatility units.** A round trip therefore costs about a
sixth of a typical move before anything else happens, and the largest edge
measured anywhere in the table is **0.0033** - fifty times smaller.

For this to be tradeable the edge would have to be *ten times* larger than the
biggest number here merely to break even on crossing. It is not close, and it
is not close at any horizon or any entry delay.

That also disposes of the entry design. A limit 1-5 pips better than the market
was the right instinct - it avoids paying up - but no entry improvement rescues
a zero edge against a 0.16v cost.

## By interval, it is worst where you would trade fastest

Net of spread, by the interval that made the call:

| interval | calls | 1s | 10s | 60s | 300s |
| --- | --- | --- | --- | --- | --- |
| 1m | 299 | -0.3304 | -0.3263 | -0.3368 | -0.2767 |
| 3m | 310 | -0.2860 | -0.2847 | -0.2696 | -0.3941 |
| 5m | 522 | -0.1808 | -0.1741 | -0.2342 | -0.2695 |
| 15m | 254 | -0.0940 | -0.0972 | -0.0774 | -0.1060 |
| 30m | 138 | -0.0630 | -0.0618 | -0.0603 | -0.0689 |

Monotone: the finer the rung, the worse it is. That is the same gradient
`by_interval` found from an entirely different direction - sub-15m trading at
**-821.75 over 129 closes** against +35.03 at 15m and above - and two
independent measurements agreeing is worth more than either alone.

The reason is not mysterious. A finer timeframe has a smaller volatility unit,
so the same spread in price is a larger spread in the units everything here is
denominated in. Speed does not beat that; it pays it more often.

## Latency was going to be the interesting question and never got asked

Every horizon was also measured from entry delays of 0.5, 1 and 3 seconds, to
find where a real round trip through structures, the bus, trading and the
broker stops being able to reach the move. At 0.5s the edge is *nominally*
positive at 1s, 2s and 10s (+0.0066, +0.0074, +0.0083) - and net is still
-0.15, and those numbers are the same size as the ones that were negative at
zero delay. There is nothing there for latency to erode.

## What this does not say, and one hole in the harness

**It does not say the calls are worthless.** It says they carry nothing
*extractable in the first five minutes net of crossing*. The level machinery is
measured elsewhere on a longer horizon and this is silent about it.

**The `best` column has no control.** The harness reports the most favourable
point reached within each horizon - 0.9083v by 300 seconds - which looks like
what a perfect trailing exit would capture. It cannot be read that way: maximum
favourable excursion grows like the square root of time for *any* random walk,
and no control was computed for it. Fixing that is a few lines. With the edge
at zero it would change nothing, because a trail needs something to trail.

**Sample.** 1,682 calls of 17,463 had ticks covering them - the tick pull spans
12 to 24 hours where the calls span two days. A larger pull would tighten the
error bars. An edge of 0.003v against a 0.159v spread is not waiting for more
data.

## The harness bug that looked like a stalled database

The first run produced no output for fifteen minutes. The natural reading was a
slow scan of a 950MB journal, and the next step would have been to index it.

The journal has four indexes, is in WAL mode and holds 780,439 rows. The slow
thing was `measure()`, which walked the entire tick list **once per horizon per
call** - O(calls x horizons x ticks). Bisecting it and walking each window once
took the same job from fifteen minutes to ninety seconds.

Two things worth keeping from that. The output was empty because stdout
block-buffers to a file, so "no output" was not evidence of no progress -
`python -u` fixes it and `lab.sh` now does. And "the database must be slow" was
a guess about someone else's code that would have cost an hour before anyone
checked the harness, which was mine.
