# Is this instrument still behaving like itself?

`till_infinity/structures/context/character.py`, added 2026-09-21. Tests in
`tests/test_character.py`.

A **monitor, not a signal**. Nothing gates a trade on it and nothing should. It answers one
operational question the desk had no way to ask: has an instrument stopped being the
instrument the configuration assumes.

## Where it came from

`detectors.md` built a jump detector and validated it against the only ground truth this
research has. Boom indices are constructed to spike upward against a slow grind down and
Crash indices are the mirror, so an up-channel must fire far more than a down-channel on
Boom and the reverse on Crash:

| instrument | ON per 1000 | OFF per 1000 | ON − OFF |
|---|---|---|---|
| boom_1000_index | 3.8 | 0.1 | **+3.7** |
| crash_1000_index | 0.2 | 3.8 | **−3.6** |
| volatility_75_index | 2.2 | 1.7 | +0.5 |

That detector produced nothing tradable - `stop-free.md` closes that question - but it
recovered a designed property of the instrument precisely, which makes it the most reliable
instrument the research built. This is its honest use.

**A synthetic index is generated, and its parameters belong to the broker.** If Boom stops
spiking upward, every assumption the desk holds about it is void, and nothing else here would
notice: prices keep arriving, the feed stays healthy, the volatility estimate stays correct.

## What it watches, and why not the obvious thing

It reads the `Focus` up/down detectors that `engine._note_change` already feeds - prod has
had those all along, so nothing new is detected, only watched.

**Balance** - the up-versus-down share of firings - is the instrument's character. It is
compared against the same instrument's own long-run share, never an absolute expectation, so
it needs no per-instrument configuration and works the first time a symbol is added.

**Rate** - how often anything fires at all - is a separate fault with a separate cause. The
`Focus` threshold in the engine is fixed per interval, and `detectors.md` measured what a
fixed threshold does across regimes: 0.06 firings per thousand bars in a quiet stretch and
43.16 in a loud one, seven hundred times more, where a rate-regulated threshold held near 2
throughout. A rate that leaves its own history says the **detector** has stopped
discriminating, which is a different person's problem from a changed instrument, and merging
the two alarms would send the wrong one looking.

Note what is deliberately *not* watched: the total firing rate as a proxy for character. A
rate-regulated detector pins that by construction, so on the research version it would have
measured nothing. The asymmetry is what homeostasis leaves free, which is why it is the
quantity here.

## The bug this was built through

The first version alarmed on instruments that were lopsided **by design**, which is the one
thing it must never do.

An exponential average started at one half carries that half for several time constants. A
simulated Boom at 85% up, compared against its own baseline at event 120, saw the baseline
still reading 56% and raised **+3.7 sigma against itself**. The monitor would have cried
wolf on every synthetic in the book within a week of deployment.

The fix is bias correction - dividing out the accumulated weight so the starting value is
removed rather than waited out. Measured after the fix: **400,000 bars of a simulated Boom at
85% up produced zero false alarms**, with the baseline converging to 0.852 against a true
0.85. A flip to symmetric was then reported 40 events later, which is exactly the short
window's length and therefore the fastest honest detection available.

`tests/test_character.py` pins both halves, because the failure mode and the purpose are
opposite properties of the same statistic.

## Design choices worth knowing

**Balance is counted per event, rate per bar.** A share over "the last forty events" means
the same thing in a quiet month and a busy one. A rate cannot be counted in events, because
if firings stop an event-counted window stops updating and reports the last thing it saw -
which is precisely the failure it is meant to catch.

**The rate alarm is deliberately coarse.** At a realistic few firings per thousand bars the
short window holds under ten events, so its fold change is noisy; the threshold is set wide
enough that noise does not reach it. That costs sensitivity and buys an alarm worth acting
on. It is for the order-of-magnitude failure, not a drift.

**Alarms latch**, so a standing shift is reported once rather than on every bar, and clear
when the reading returns inside its band so a genuine second shift is still seen.

**It holds nothing with a length.** Only floats and ints. `restore-drops-deque-maxlen` is a
fault this codebase has already had - a capped `deque` field came back uncapped from a save
and was found on the live heap rather than in the declaration - so a monitor that must
survive every deploy holds no container at all. A test asserts it.

**It cannot take the engine down.** `_note_character` is its own method, called after the
detectors it reads, and `engine.observe_bar` already wraps `_note_change` because "two
outages this month were a fault in here taking the whole structures service down".

## How it surfaces

A `log.warning` per shift, and `Engine.character(feed, interval)` returns the reading as a
dict for the service's state view. Deliberately not an automatic action: **whether a changed
instrument should still be traded is not a decision this process is entitled to make.**

Example of what an operator sees:

```
structures: boom_1000_index 1h - jump balance has moved downward: 66% of recent
changes are up against 83% historically (-3.2 sigma)
```

## What it does not do

* It does not trade, size, veto or gate anything.
* It says nothing about *why* an instrument changed - a generator change, a feed swap and a
  broker renaming a symbol onto a different underlying all look identical here.
* It is blind on any interval outside `CHANGE_INTERVALS` (`5m`, `15m`, `30m`, `1h`), because
  that is where the detectors it reads are fed.
* It needs `WARM_EVENTS` firings before it says anything, so a new symbol is unmonitored for
  its first stretch. At a few firings per thousand bars on 1h that is weeks.
