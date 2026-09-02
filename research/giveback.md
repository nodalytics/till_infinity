# Giving back an open profit

Reported from watching the terminal: *"a trade can be in +$30 profit and it
will reverse to hit sl"*. This is what that turned out to be, and it is mostly
a story about two plausible explanations that measurement killed.

## The field that measures it was a constant

`best_r` is the furthest a trade ever got in front, in units of its own risk.
`adverse_r` is the mirror. Both read **exactly 0.000 on every close in the
book's history** — 188 and 85 of them, min and max both zero, and not one
stopped trade recorded as ever having been in front.

`_best` and `_worst` were popped on the line *above* `_settle`, which is what
reads them, and both `_reach` and `_heat` return 0.0 for a ticket they cannot
find. The tracking was right, the recording was right, and the state was thrown
away in between. Fixed 2026-09-02; the boundary is visible in the data at
19:45 UTC, where the zeroes stop and real excursions start:

| when | symbol | profit | best_r | adverse_r | exit |
| --- | --- | ---: | ---: | ---: | --- |
| 17:42 | Volatility 25 Index | −0.97 | 0.0 | 0.0 | hold |
| 19:45 | US Small Cap 2000 | +4.13 | 0.282 | 0.0 | target |
| 21:41 | Volatility 75 Index | −11.70 | 0.0 | **0.803** | stale |
| 21:54 | Volatility 10 Index | +13.26 | **0.742** | 0.046 | target |

So the anecdote was unmeasurable for the whole life of the desk, and looked
answered because zero is a legal value.

## Reconstructing the history from bars

Rather than wait days for `best_r` to accumulate, the same quantity was
recovered from 1m bars: walk from the entry to the exit the trade actually got
and take the furthest it went in favour. 180 closes scored.

| furthest in front | n | lost | share |
| --- | ---: | ---: | ---: |
| under 0.25R | 58 | 52 | 90% |
| 0.25–0.5R | 23 | 7 | 30% |
| 0.5–1R | 35 | 18 | 51% |
| 1–2R | 39 | 19 | 49% |
| over 2R | 25 | 12 | 48% |

**31 of the 64 trades that reached 1R in front ended at a loss**, costing
−577.76 — roughly 60% of the book's total loss. And the share is flat all the
way out: a trade 2R in front still loses 48% of the time, so going further in
your favour buys almost no protection.

17 closes were dropped for an impossible excursion — up to 70R, meaning the
stop sat almost on the entry and the denominator is noise. The same defect that
put an implied reward-to-risk of 30,338 in the shadow record. Filtering them
moved the answer from 41/81 to 31/64 and the cost from −779 to −578, so it was
not cosmetic.

## Two explanations, both wrong

### "Break-even is off for most strategies"

It is not, and it never was. `manage.py` reads
`intent.break_even_at or settings.break_even_at`, so a strategy whose ClassVar
is 0.0 falls through to `TRADING_BREAK_EVEN_AT`, which has been **1.0 since at
least 2026-08-29 18:27**. There is nothing to turn on.

The stop it sets is `price_open + sign * tick_size * break_even_ticks` with
`break_even_ticks = 2` — placed *beyond* entry, deliberately, because a stop at
the entry on a long is hit by the bid while the fill paid the ask. Break-even
at the exact entry price is a small loss after costs, and the code already
knows it.

`break even at` appears zero times in the log for an unrelated reason:
`advance` proposes break-even and then lets trailing override it in the same
pass when the trail is better, so the reason recorded is "trailing". The rule
does work; it just never gets its name in the log.

### "The 60-second heartbeat is too slow"

`_manage` runs only from `sweep()`, once a minute, so the theory was that
trades go 1R in front and reverse between passes. Measured on the same bars —
minutes between reaching 1R and returning to entry:

| gap | n | share |
| --- | ---: | ---: |
| same minute, unreachable | 10 | 30% |
| next minute, a coin toss | 9 | 27% |
| 2–5 minutes | 13 | 39% |
| over 5 minutes | 1 | 3% |

That looked damning — 14 of 33 with two or more minutes of warning — until the
population was split on whether the rule was even configured:

| | trades | cost |
| --- | ---: | ---: |
| before break-even was configured | 26 | −500.55 |
| after | 7 | −148.73 |

**26 of the 33 give-backs happened when the rule was not on.** "The heartbeat
saw them and did not act" was measuring an era when there was nothing to act.
Since it was configured, four trades had two or more minutes of warning,
costing −112.27 — which cannot justify moving stop-modify logic onto the quote
stream, in the hot path, against a broker, for every open position.

## What is actually left

* **Nothing to change.** Two fixes were proposed in this investigation and the
  measurement killed both. The 60s cadence is not the problem and break-even
  needs no enabling.
* **The problem is largely historical.** −500 of the −649 predates the
  configuration that addresses it.
* **Four post-configuration cases is a watch item, not a finding.** Whether
  break-even is working properly now needs the next dozen, and `best_r` records
  them live, so the answer will come from the field rather than another replay.
* **The next real question is stop width**, not break-even: the winners'
  `adverse_r` distribution is the stop the book should be using. See
  [planned/excursion.md](planned/excursion.md).

## A methodology note worth keeping

The half-hourly digest first reported *"1 was >1R in front and did not end
there"* — and the trade it flagged closed **+4.04**. The condition counted any
trade that closed below its own high, which is nearly all of them, and read as
a give-back when it was not. A give-back requires an actual loss, and the
alert now says so.

Three claims in this investigation were wrong before they were right: the
digest's definition, "management has never acted" (a grep that required
`trading: ` immediately before the keyword, where the real line has a ticket in
between), and "the heartbeat saw them and did not act". Each was corrected by
asking for the number rather than the story.
