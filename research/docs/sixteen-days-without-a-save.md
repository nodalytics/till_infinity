# Sixteen days without a save

`structures` last wrote its state on **2026-09-23 at 11:53**. Every attempt
after that raised `RecursionError: maximum recursion depth exceeded while
calling a Python object`, once every five minutes, until 2026-10-09. The
process said so at `WARNING` each time and nothing counted it.

This is the answer to the question [`losing-faster.md`](losing-faster.md) left
open - why the same twenty feeds re-warm on every restart - and the answer is
not in the warm.

## What it cost

Nothing the desk learned between 23 September and 9 October was written down.
Every restart - and there were many, fifteen pull requests merged on the last
day alone - restored the September file, so each one came back to a state that
predated the current universe and spent an hour replaying bars to catch up.

Measured on that file:

| | |
| --- | ---: |
| feeds in `_series` | **31** |
| series | 345 |
| `spx500` series | **none at all** |
| newest bar in it | 2026-09-20 04:01 |
| age at time of reading | **19.6 days** |

The desk's universe is 51 symbols. `Watcher.unwarmed()` calls a feed warm when
its deepest series holds at least `WARM_MIN_BARS = 100` closes, so the twenty
feeds absent from that file were unwarmed by definition, every single boot.
`spx500` was one of them - not thin, **missing**.

## The mechanism, end to end

1. `rel()` in `vol/learned.py` guarded its input with `if value <= 0: return
   1.0`. **`nan <= 0` is `False`**, so a non-finite estimate walked through a
   guard written to reject useless ones.
2. `har_rel` became `nan` and went into the pooled volatility tree.
3. River's `TEBSTSplitter` bounds itself by *rounding* its input - `digits=1`,
   so a finite feature can only ever produce as many nodes as it has distinct
   rounded values. `round(nan, 1)` is `nan`, and no comparison against `nan` is
   ever true, so **every observation looked like a value never seen before** and
   appended a node to the same right-hand chain.
4. That chain is a linked list. `pickle` recurses once per node.
5. When it passed Python's 1,000-frame limit, every save began to fail.

Step 3 is the one worth keeping. A `nan` reaching this tree is not a bad
number, it is **an unbounded data structure**.

## The numbers that identified it

Walking the September file's object graph:

```
max graph depth: 333
engine.vol._learned._model._plan[1][1]._root.children[1]...children[0]
  ._right._right._right ... (x292) ... .estimator.mean.n
```

332 of the 333 is that one chain. Longest right-hand chain per feature:

| feature | chain | clipped in `features()`? |
| --- | ---: | --- |
| **`har_rel`** | **292** | no |
| `weekday` | 28 | yes |
| `r22` | 24 | no |
| `stretch` | 20 | **yes, to [0, 10]** |
| `hour_sin` | 20 | yes |
| `garch_rel` | 13 | no |
| `upper_wick` | 3 | yes |
| `lower_wick` | 2 | yes |

Every clipped feature is short. And the chain is not merely long, it is
**entirely non-finite**: 293 of 293 nodes on the worst one, and **65,689 `nan`
nodes across the tree's `har_rel` splitters against 2,489 real ones**.

Reproduced in isolation, which is what made it conclusive rather than
suggestive:

```
40 NaN updates into a fresh TEBSTSplitter -> right spine of 40
40 random updates into a fresh TEBSTSplitter -> right spine of 3
```

## Four hypotheses that were wrong

Recorded because each was plausible, each was cheap to test, and testing them
is the only reason the fifth was found rather than asserted.

* **A reference cycle in the pickled graph.** The codec has no memo, so a cycle
  would recurse forever. There is no cycle; the walk completed.
* **`Har.predict()` returning `nan`.** It has the right guard - `got if got > 0
  else latest` - and all **1,777** restored `Har` instances returned a finite
  forecast, with no `nan` anywhere in any `_history`.
* **The HAR model poisoned by a `nan` target.** Zero `nan` weights in any of
  the 1,777.
* **`StandardScaler` dividing by a zero variance.** River returns `0.0` for a
  constant feature, measured directly, not `nan`.

The fourth is the instructive one: the feature *is* constant much of the time,
the story was coherent, and it was simply not what the data said.

## The fix

* `rel()`, `features()` and `Learned.observe` now test **positive and finite**
  rather than `not <= 0`. `Har.observe` and `Har.predict` too - the same broken
  shape appeared there, where a non-finite reading would have entered
  `learn_one` as `log(nan)` and made every later weight `nan`.
* `_finite()` sweeps the whole row before anything reads it, substituting each
  feature's own "no view" value and **logging loudly**. It is at the row rather
  than at each producer because it has to hold for the feature nobody has
  written yet.
* `Learned.prune_nonfinite()` repairs what is already on disk, on restore.
  River's `HTLeaf.update_splitters` rebuilds a splitter on `KeyError`, so
  deleting the entry drops the chain and the feature carries on being observed
  from the next bar. Not `disable_attribute`, which would stop observing it for
  good.

Run against the production file:

| | before | after |
| --- | ---: | ---: |
| graph depth | 332 | **92** |
| pickled engine | 107.9 MB | **98.8 MB** |
| headroom under the 1,000-frame limit | 3.0x | **10.9x** |

2,880 splitters holding 65,689 non-finite thresholds removed.

## Why it hid for sixteen days

This is the part worth carrying forward, because the bug was a one-line guard
and the **invisibility** is what made it expensive.

A failing save logged one `WARNING` per attempt, among thousands of `INFO`
lines about dislocations and spreads. Nothing counted the failures, nothing
escalated, and nothing ever said how old the state on disk had become. A
failure that repeats is a different event from a failure that happens, and it
has to read differently: `save_failures` now counts consecutive misses and the
line becomes an `ERROR` at three, carrying the age of the last good save.

The same shape as [`inert.md`](inert.md) catalogues from the other direction -
there, features that silently never fired; here, a write that silently never
landed. Both are answered by the same discipline, which is that **a thing
believed to be happening has to have a number attached to it**.

And the diagnosis started in the wrong place. The warm was measured, halved,
and the halving [measured not to work](losing-faster.md) - all correct, all
irrelevant, because the warm was a symptom. What found this was asking why the
*restored state* was thin instead of why the *warm* was slow.

## And none of it was running, measured 2026-10-10

The fix above shipped, the saves went on failing, and the second diagnosis was
as blind as the first. The cause was not in the model at all.

**The image carried two copies of the package and the wrong one was imported.**

| | `/app/.venv/.../till_infinity` | `/app/till_infinity` |
| --- | --- | --- |
| what it is | the installed package | the source it was built from |
| **what Python imports** | **this one** | nothing |
| `_finite` | absent | present |
| `prune_nonfinite` | absent | present |
| the save counter | absent | present |
| `learned.py` | 31,196 bytes | 37,724 bytes |

`uv sync --frozen --no-editable` builds the project into a wheel and caches it,
and **the cache key does not include the source.** The version in
`pyproject.toml` never changes, so uv reinstalled a wheel it had built from an
older tree. Every core file differed. The installed copy had no
`TOUCH_NOISE_VOL`, no `ACCEL_SIGMAS`, no `SEED_NEW_BARS` - so it predates #130,
and **#130, #136 and #141 were built, tagged, deployed, health-checked and
reported `up on <sha>` while none of them ran.** No commit on `main` matches its
file sizes, so the wheel came from a working tree rather than a revision.

### Why three content checks all missed it

The rule after yesterday's mislabelled image was *verify the contents, not the
tag*. It was followed, and it still missed this, because of one detail:

```
WORKDIR /app
```

`docker run --entrypoint python ... -c "from till_infinity... import X"` resolves
`till_infinity` from the working directory **before** site-packages. Every check
read `/app/till_infinity` - the source - and confirmed exactly the copy that was
not running. The verification and the failure had the same cause.

So the rule needs its second half: **verify the artefact the process loads, not
a file that happens to be in the image.** `till_infinity.__file__` answers it in
one line, and the build now answers it without being asked.

### The fix

* `--reinstall-package till-infinity` on the project sync, so a cached wheel
  cannot satisfy it.
* **A build-time digest check** over every `.py` in the installed package
  against every `.py` in the source. A stale wheel now fails the build instead
  of shipping.
* **The source tree is no longer shipped.** Two copies with one imported is what
  made a wrong check possible; with one copy in the image, `python -c` cannot
  read the wrong thing.

### What this voids

[`losing-faster.md`](losing-faster.md)'s "the warm cap does not bind" section,
and #140, which recorded it. `SEED_NEW_BARS` was not in the running process, so
the unchanged bar count measured a missing constant rather than an unbinding
cap. **Untested, not refuted.**

It is also the fourth time in two days that tooling reported success over a
wrong artefact - an rsync that moved 189MB and left the directory empty, an
image tagged with a commit it did not contain, a save that wrote a `.tmp` and
renamed nothing, and now an install that reported done and changed nothing. The
common shape is that each one had a cheap check nobody had written yet.
