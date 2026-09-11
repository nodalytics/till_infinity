# The service is OOM-killed by its own save, not by a leak

Twenty-four kills between 2026-09-01 and 2026-09-10, roughly one every two and a
half hours. Each costs about **seventeen minutes** of trading - the reconnect and
warm-up after a restart - so the desk has been unavailable something like a tenth
of the time for nine days.

Nothing said so. `docker ps` showed `Up`, the health check passed between kills,
and the restart was clean enough that `docker inspect` reported `exit=0`. Only
`dmesg` had it.

**This page had the wrong cause twice before it had the right one**, and the
wrong ones are kept because each was a reasonable reading of the evidence
available at the time, and because the third only arrived by measuring rather
than reasoning.

## What it looked like from inside

Six separate puzzles in one session, five of them this single event:

* `restarts=3` on a container nobody had redeployed.
* Trading silent for **2.1 hours**, then reconnecting seventeen minutes after a
  container start nobody triggered.
* The volatility learner's save cycle never producing a tally, twice, because
  the process kept being replaced before `save_seconds` came round.
* CPU reading 7.6% at one check and 153% at the next - the low reading being a
  process that had just restarted.
* An "out-of-sample" replay window that looked like a different market regime -
  42 feeds against 364. That was not a regime; it was the feed universe growing.

The sixth was **three research harnesses dying with empty output files**, read
first as memory and then as the cgroup killing the newest process. Both readings
were wrong: `dmesg` shows no kill at those times and their stderr was empty, so
no Python exception either. They were run over `ssh` inside foreground commands
that timed out, and the dropped session sent `SIGHUP`. `docker exec -d` fixed it.

Worth keeping, because it is the opposite failure to the other five: once a real
platform fault is established it becomes the explanation for everything nearby.

## First wrong cause: the feed universe

The book is configured as 53 symbols. The price collector was discovering up to
**1,250 more** - `PRICES_CCXT_TOP=250` across five exchanges, swaps only - and
structures draws a level book on every feed it sees across eight timeframes.
Measured live: 162 distinct feeds in twenty minutes, 364 over a wider window.

Cut to 25 on two exchanges. **The baseline fell from 1.85GB to 1.45GB**, which is
real and worth keeping. The kills continued.

## Second wrong cause: accumulation

With the baseline lower and kills continuing, the next reading was a slow leak.
An hourly watch settled it, in the direction nobody expected:

| time | memory | kills |
| --- | --- | --- |
| 12:43 | 1.089 GB | 22 |
| 13:43 | 1.456 GB | 22 |
| 14:43 | 1.480 GB | 22 |
| 15:43 | 1.379 GB | 23 |
| 16:43 | 1.437 GB | 23 |
| 17:43 | 1.482 GB | 24 |

**Flat at 1.38-1.48GB, and killed twice inside that window at ~2.7GB.** A leak
cannot do that. Whatever crosses the limit does it *between* hourly samples, so
every measurement taken that day was of a process dying in the gaps.

## The actual cause, measured

`store.save` runs every 300 seconds and `codec.pack` builds the entire structure
in memory before msgpack writes it. `models.msgpack` is **206MB** - against the
58MB that comments throughout the package still quote.

Measured off production, on a byte-identical copy (`store.save` writes atomically
via `temp.replace`, so unlike a live sqlite file a copy is never torn), with
`river` pinned to production's version because the state carries pickled river
objects:

```
file: 206 MB
rss before load        0.110 GB
rss after msgpack load 0.552 GB
rss after unpack       1.327 GB   (3.2s)   <- just holding the live objects
rss after pack         1.569 GB   (2.5s)
rss after packb        1.908 GB   (0.2s)   wrote 206 MB
```

Two numbers matter:

* **Holding the state costs 1.33GB from a 206MB file** - a 6.4x expansion, paid
  continuously, not only at save time.
* **A save adds ~0.58GB on top**, briefly, every five minutes.

A 1.45GB baseline plus a 0.58GB transient is 2.03GB against a 2.61GB limit -
close but not fatal on its own. What closes the gap is that CPython does not
promptly return freed memory to the OS, so each save's peak partially sticks and
RSS ratchets upward. That is visible in the watch above: 1.089 to 1.482 across
the afternoon, and in the fresh-restart samples, which show 130MB jumping to
1.13GB the moment the state is restored.

So the kills are not a leak in the ordinary sense. They are a **periodic
transient on a resident cost that is six times the file it came from**, on a
container with 2.61GB.

## What follows

**Not a bigger box**, or not only. Three things would each help, in descending
order of how much:

1. **Shrink what is persisted.** 206MB is the input to both problems - the 1.33GB
   resident cost and the 0.58GB transient scale with it. This is the only fix
   that addresses both.
2. **Stream the save.** `codec.pack` building the whole structure before writing
   is what creates the transient; writing incrementally would remove it and
   leave the resident cost.
3. **Raise the limit.** Buys time and fixes nothing, and the state is growing -
   195MB to 206MB inside one day.

## What made it worse, and was reverted

The bar window was raised from a flat 500 to 1,000 (1,500 on the fine series) on
the morning of 2026-09-10, before any of the above was understood. More bars per
series means a larger state file, which means a larger resident cost *and* a
larger save transient - on a container being killed by exactly that.

Reverted the same day to `STRUCTURES_WINDOW=500`, keeping
`STRUCTURES_FINE_WINDOW=1500` because that one has a measured purpose: a 1m
series has to cover a 1,440-minute daily bar for `_capture_fine` to refine a
daily origin at all. Both are environment variables specifically so a change like
this can be undone without a deploy, and that is the property this incident most
needed.

## The check that would have found it sooner

Sample memory faster than the thing being measured. An hourly watch cannot see a
five-minute transient, and six flat readings looked like evidence of stability
while the container was dying between them. Twenty-second sampling, with a marker
for whether a save fell in the interval, is what turns this from an argument into
a measurement.

## Resolution: the transient is gone, and it was not where the plan said

Measured on production's own 206MB state, off production, with both writers in
their own process and `PYTHONHASHSEED` pinned so the byte comparison means
something (`research/harness/savestream.py`):

| path | held | peak | **added** | secs |
| --- | --- | --- | --- | --- |
| `packb(pack(state))` | 1.327 GB | 1.722 GB | **0.394 GB** | 1.9 |
| `pack_into(state, file)` | 1.326 GB | 1.326 GB | **0.000 GB** | 1.7 |

Byte-identical output, same 216,000,789 bytes, same SHA-256. The transient is
**gone**, and the save is fractionally *faster*.

### The first attempt only got a fifth of it

Item 2 above said the transient was `codec.pack` building the whole structure
before writing. Streaming that took 0.394GB to **0.321GB** - real, and nowhere
near enough. The composition is why:

| | bytes | share |
| --- | --- | --- |
| raw pickle blobs | 209,804,076 | **97.1%** |
| codec structure | 6,192,049 | 2.9% |

**Three blobs**, and one of them is 178.4MB:

| top-level key | packed | what it is |
| --- | --- | --- |
| `engine` | 178.4 MB | one pickle blob |
| `detector` | 20.6 MB | one pickle blob |
| `bench` | 4.7 MB | codec structure |
| `drift` | 1.1 MB | one pickle blob |
| `clock`, `activity`, `races`, `breaks` | 1.2 MB | codec structure |

`Engine`, `Detector` and `Drift` are not dataclasses, so `codec.pack` falls
through to its opaque branch and pickles each whole. Streaming the *structure*
was streaming 2.9% of the file.

### What actually fixed it

`pickle.Pickler` writes to a file object incrementally, so each blob goes to a
spooled temporary file, its length is then known, and the body is copied through
in 4MB pieces behind a hand-written msgpack `bin` header. Peak cost becomes one
chunk and one temp file rather than one copy of the largest model on the desk.

The header has to pick the same width `packb` would - `bin8` under 256 bytes,
`bin16` under 65536, `bin32` above - because always writing `bin32` is valid
msgpack, reads back identically, and is **not the same bytes**. That is a
one-byte difference at offset 339 in a 4,866-byte fixture, and it is the
difference between an optimisation and a migration of 206MB of learned state.
`test_streaming_a_save_writes_what_packing_it_would` exists for precisely that
and is what caught it.

### What this does and does not buy

The container had a 1.15GB margin and the save spent a third of it. That third
is back. **What remains is the resident cost**: 1.33GB to hold a 206MB file, a
factor of 6.4, which is item 1 on the list above and is untouched by any of
this. A state that keeps growing still walks into the same wall, just later.

So the honest scoreboard is: the *periodic* cause of the kills is removed, the
*structural* one is not. The next move is still to shrink what is persisted -
and the composition table above says where to look, because 97% of it is three
objects that nothing in the codec can see inside.
