# Locking profit in: right idea, stale reason, and the code already exists

The proposal: on scalps, always lock profit in, because the direction resolves
in about two seconds and everything after that is exposure without an edge.

The instinct is supported. The premise is not, and the mechanism that would
capture it is already written and has never run.

## The two seconds are gone

[resolution.md](resolution.md) measured that **two thirds of touch outcomes
resolved within two seconds**, and that number is quoted throughout this
repository. Re-measured on 2026-09-08 over 120,000 resolved touches:

| | |
| --- | --- |
| resolve under 2s | **3.8%** |
| under 10s | 4.5% |
| under 60s | 8.2% |
| median | **191s** |
| p75 / p90 | 540s / 1,214s |

And it is not a fine-timeframe effect hiding in the pool. On 1m levels the
median is 154s and only 3.9% land under two seconds; on 5m, 467s and 2.8%.

**The old number described a bug, not the market.** resolution.md says what it
was: *"a bar's wick was resolving touches born inside it"* - a touch opened
inside a bar and closed by the same bar's extreme, resolving instantly by
construction. That was fixed. The two-thirds figure went with it, and anything
built on "we know within two seconds" is building on the artifact.

## But the give-back is real - and it is the trap, not the clock

The quantity the proposal is really about is **give-back**: how far a touch
travels in your favour against how much it keeps. Over the 44,828 touches that
carry a recorded excursion:

| held | n | reached | kept | gave back | kept share |
| --- | --- | --- | --- | --- | --- |
| under 1m | 3,835 | 2.22v | 0.83v | **1.26v** | 37.2% |
| 1-3m | 4,552 | 2.16v | 0.77v | 1.28v | 35.2% |
| 3-10m | 18,465 | 2.85v | 2.12v | 0.00v | 100% |
| 10-30m | 11,922 | 3.06v | 2.52v | 0.00v | 100% |
| over 30m | 6,054 | 3.80v | 3.58v | 0.00v | 100% |

Read as holding time this says the opposite of the proposal - the *short* holds
give back and the long ones do not. That reading is wrong, and the split by
outcome says why:

| outcome | n | keeps of what it reached |
| --- | --- | --- |
| **trap** | 23,199 | **34.0%** |
| break | 21,629 | 100% |

**The give-back is the trap.** A break's excursion *is* its push, by
construction, so it keeps everything; a trap travels a median 2.2v your way and
hands back two thirds of it. The time bands above are sorting by outcome mix -
short resolutions are trap-heavy, long ones break-heavy - not by patience.

So the proposal is right and its reason is different: locking in does not beat
holding too long, it beats **being trapped**. And traps are 57.6% of resolved
attempts and 94.6% of them on 30m.

## Why a full lock-in is a coin toss on a constant

Banking the whole position at some level `B` trades a trap's give-back against
a break's tail. On the medians above, with traps at 57.6%:

| bank at | trap gains | break costs | net |
| --- | --- | --- | --- |
| 1.5v | +0.67v | -1.35v | **-0.19v** |
| 2.0v | +1.17v | -0.85v | **+0.31v** |

That is medians used as if they were distributions, so the numbers are
indicative and the *shape* is the point: a full bank is strongly sensitive to
where it is set, and sits either side of zero across a plausible range. Choosing
`B` on this arithmetic would be choosing a constant on a coin toss, which is the
mistake `at_bound` already made once on this book.

## The partial bank is the answer, it exists, and it has never fired

Banking **part** of the position takes the trap's give-back without capping the
break's tail, which is the only version of this idea that does not need `B` to
be right. It is already built:

* `Shape.bank_at` and `Shape.bank_share` are fields on every strategy preset.
* `TRADING_SCALE_OUT_AT=1.0` and `TRADING_SCALE_OUT_FRACTION=0.5` are set in
  production.
* `manage.why_no_bank()` exists to name the refusals, added when this was last
  looked at.

And **`bank_at` defaults to 0.0 on the preset**, so a strategy carrying its own
`Shape` overrides the deployment setting with "never". Scale-out has not fired
once. That is the same failure as the daily loss limit resetting on restart and
break-even never firing: a feature configured, deployed, reporting healthy, and
inert - the list [inert.md](inert.md) keeps.

## What to do, cheapest first

1. **Find out why it never fires.** `why_no_bank()` already names the reason;
   nothing has read it. This is one log line away and it decides everything
   below.
2. **Then set `bank_at` per strategy rather than globally**, since the preset
   default of 0.0 is what silently wins today.
3. **Then measure it on the replay** - `swingtest.py` resolves against the same
   barriers and can bank a share at a level as easily as not.
4. **And re-run this table by strategy**, because a 34% keep rate is the whole
   book and the strategies that trade traps deliberately - `sweep-aware` - are
   the ones it least applies to.

## What this does not say

Nothing here measures a *trade*. These are resolved touches: the level's own
outcome, not a position with a spread, a stop and a size. The give-back a trade
suffers is bounded by its stop, which a touch has no analogue for. The
arithmetic above is the right shape and the wrong units, and only the replay
converts it.
