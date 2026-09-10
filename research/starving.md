# The service was being OOM-killed every two and a half hours, and had been since 1 September

Nineteen kills between 2026-09-01 and 2026-09-10, five of them in the eleven
hours before this was found. Each one costs about **seventeen minutes** of
trading - the reconnect and warm-up after a restart - so the desk was
unavailable roughly a tenth of the time, and had been for nine days.

Nothing said so. The container reported `healthy` between kills, `docker ps`
showed it `Up`, and the restart was clean enough that `docker inspect` gave
`exit=0`. This is the failure mode `research/inert.md` catalogues from the
other direction: not a component that does nothing, but a component that
**stops and starts again** while every surface says it is fine.

## What it looked like from inside

Six separate confusions in one session, all the same event:

* `restarts=3` on a container nobody had redeployed.
* Trading silent for **2.1 hours**, then a log line showing it reconnecting to
  the broker seventeen minutes after a container start nobody triggered.
* The volatility learner's save cycle never producing a tally, twice, because
  the process kept being replaced before `save_seconds` came round.
* Three research harnesses dying mid-run with empty output files, read first
  as "my query used too much memory" and then as the cgroup killing the newest
  process. **Both readings were wrong** - `dmesg` shows no kill at the times
  they died, and their stderr was empty, meaning no Python exception either.
  They were run over `ssh` inside a foreground command that timed out, and the
  dropped session sent `SIGHUP` to the remote process. Running them with
  `docker exec -d` fixed it. The lesson survives being about something else:
  an empty output file and a missing process is not evidence of *what* killed
  it, and the kill log is one command away.
* CPU reading 7.6% at one check and 153% at the next. The low reading was a
  process that had just restarted.
* An "out-of-sample" replay window that appeared to be a different market
  regime - 42 feeds in the first half against 364 in the second. That was not
  a regime. It was the feed universe growing.

Five of those were this event. The sixth was not, and it is worth keeping in
the list: once a real platform failure is established, it becomes the
explanation for everything nearby, which is its own way of being wrong.

## The cause

The instrument book is configured as 53 symbols. The **price collector was
discovering up to 1,250 more**:

    PRICES_CCXT_EXCHANGES = binance,bybit,okx,mexc,gate
    PRICES_CCXT_TOP       = 250
    PRICES_CCXT_SWAPS_ONLY= 1

Top 250 perpetual swaps on each of five exchanges. Structures draws a level
book on every feed it sees, across eight timeframes, each carrying 500 bars,
its levels, its origins and its touch history. Measured live: **162 distinct
feeds published on in twenty minutes**, 364 over a wider window, against a
container limit of 2.6GB on a 3.8GB two-core box.

The chain from there is mechanical. More series than the box holds, so memory
climbs; CPU saturates at 153% of two cores; the Docker health check exceeds
its ten-second timeout and the container is marked unhealthy; memory reaches
the cgroup limit; the kernel kills it; it restarts, warms 100 feeds from
history, reconnects the broker seventeen minutes later, and begins again.

The persisted state records the same growth from the other side:
`models.msgpack` is **195MB**, against the 58MB that comments throughout the
package still quote.

## The change

    PRICES_CCXT_TOP       250 -> 25
    PRICES_CCXT_EXCHANGES binance,bybit,okx,mexc,gate -> binance,bybit

Roughly 1,250 discoverable feeds down to 50, on top of the 53 configured.
Applied to `till.env` and the container **recreated** rather than restarted -
`docker restart` keeps the old environment and comes back looking healthy,
which is its own version of this document's theme.

## What this does not fix, and how to tell

**The saved state still holds the feeds already discovered.** Cutting the
config stops new ones arriving; it does not prune what is in the 195MB file,
and `_decline_unsupported` is not a universe prune - it drops pairs whose grid
cannot carry a level, which is a different question.

So the fix is provisional and the test is simple: if memory plateaus below the
limit and the kills stop, the discovery was the whole of it. If it climbs to
2.6GB again on the old cadence, the restored state is carrying the dead feeds
and they have to be pruned, which is a harder change because the same file
holds the levels and the learner state for the 53 instruments that matter.

Watching memory rather than asserting the fix worked is the entire point.

## What it invalidates

Every measurement taken on this box while the service was restarting every two
and a half hours inherits the restarts. Specifically:

* The live volatility learner's pair counts were reset repeatedly, so
  "24,196 pairs" is an interval between kills rather than a total.
* `momentum-scalp` has been consulted a handful of times in six hours, which
  was read as the queue starving it. It may simply be that trading was down or
  warming for most of the window.
* The trading tally of 35 closes over 24 hours was taken across a service that
  was absent for about a tenth of it.

None of the *replayed* results are affected - those read stored bars and do
not care whether the live service is up. `research/forecasting.md` stands.
