# Recovering an overgrown prices database

Written after it took the desk out on 2026-09-23: a 29.5 GB database with a 13 GB write-ahead log on
a box with 3 GB of memory. The code fixes that stop it recurring are in `shared/db.py` and
`prices/config.py`, and are listed at the bottom; **this page is the one-off recovery**, because
neither a log nor a table that has already grown shrinks on its own.

## What it looks like

```
docker inspect till-infinity --format '{{.State.Health.Status}} {{.State.Health.FailingStreak}}'
unhealthy 157
```

with the health output repeating

```
prices stopped: OperationalError: database is locked
```

and the desk quietly stopping downstream of it: `structures` produces no decisions because it has no
quotes, and nothing trades. The giveaway is the file listing rather than the logs:

```
$ ls -la ~/till-data/prices/
29504970752  prices.db
   25395200  prices.db-shm
13071182072  prices.db-wal     <- 13 GB
```

on a box with **3 GB of memory and two cores**.

## Why it happens, and what it is not

It is **not** a failure to checkpoint. `wal_autocheckpoint` defaults to 1,000 pages and does its job.

It is that `journal_size_limit` defaults to **−1**, meaning no limit. SQLite reuses WAL space after a
checkpoint but never shrinks the file, so **one write burst sets a high-water mark that stays for
ever**, and every connection opened afterwards pays to map it. The `-shm` index grows with it - 25 MB
here - and on a box this size a new reader can sit in uninterruptible disk wait for minutes, which is
what the writer then reports as a locked database.

`shared/db.py` now sets `journal_size_limit`, so a *new* database cannot reach this state. The pragma
takes effect at the next checkpoint and does not shrink a log that is already large.

## It may recover on its own, and that changes what to do

On 2026-09-23 it did: five hours after the failing streak hit 157, the container was `healthy`, all
seven services were running, and the log had checkpointed itself from **13.07 GB down to 2.77 GB**
with no intervention. A reader eventually let go, the backlog drained, and the desk came back.

So **check before acting**. The sequence below stops a healthy desk, and that is the wrong trade if
the acute problem has already passed:

```bash
docker inspect till-infinity --format '{{.State.Health.Status}} {{.State.Health.FailingStreak}}'
ls -la ~/till-data/prices/
```

A `healthy` container with a shrinking log needs no outage. What it still has is an oversized
*database*, and reclaiming that is planned maintenance to be scheduled rather than an incident to be
fought. The collector's hourly trim keeps the table from growing in the meantime, so waiting costs
little.

## Recovery

Read the whole sequence before starting. Steps 1 and 2 are what make step 3 safe, and step 3 is the
only one that takes real time.

**1. Stop anything that opens the database on a timer.** A 30-minute cron runs `rate-watch.sh`, which
`docker exec`s a recorder that opens `prices.db` read-only - and a reader is enough to pin the log
while it is being truncated.

```bash
crontab -l > ~/crontab.before-wal-fix.$(date -u +%Y%m%dT%H%M%SZ).bak
crontab -l | sed 's|^\(\*/30 .*rate-watch.sh\)|#\1|' | crontab -
crontab -l | grep rate-watch          # expect it commented out
```

**2. Stop the writer.**

```bash
docker stop -t 60 till-infinity
sudo lsof ~/till-data/prices/prices.db-wal    # expect nothing
```

The `lsof` is the check that matters. If anything still holds the file, find it before continuing -
pruning or truncating under a live reader does nothing and wastes the outage.

**3. Prune, then rebuild - which also resets the log.**

This is the step that changed once the file was understood. `VACUUM` rewrites the database from
scratch, so it **reclaims the deleted space and resets the write-ahead log in one pass** - a separate
`wal_checkpoint(TRUNCATE)` is then redundant. Prune first so the rebuild has less to copy.

```bash
cd ~/till_infinity   # wherever the checkout lives
uv run till-infinity prices prune --keep 1000 --quote-days 14 --vacuum --yes
```

Expect this to take a long time and to need room for a second copy of the file: `df -h /` showed
191 GB free against a 29.5 GB database, which is ample. Run it detached and watch the log rather
than holding an SSH session open for it.

**What each half does.** `--keep 1000` bounds `bars` per series, which was already the policy and was
never run on a schedule. `--quote-days 14` bounds `quotes`, which **no release before 2026-09-23
pruned at all** - `_PRUNE_BARS` named one table and the other grew without limit at one row per poll
per venue per symbol. That is the likelier half of the 29.5 GB, and neither the count nor the split
can be measured cheaply on this box: both tables are `WITHOUT ROWID`, so there is no `MAX(rowid)`
shortcut and a `COUNT(*)` is a full scan of the thing that is already too slow to scan.

### If only the log needs resetting

If the file has already been pruned and just the log is oversized, the narrower operation is a
checkpoint. It is an ordinary, non-destructive SQLite operation: it moves log content into the
database. Detach it, because 13 GB on this disk takes a while and an SSH drop should not be what
decides the outcome.

```bash
nohup python3 - <<'PY' > ~/wal-truncate.log 2>&1 &
import sqlite3, time
t = time.time()
c = sqlite3.connect("/home/ubuntu/till-data/prices/prices.db", timeout=600)
print(c.execute("PRAGMA journal_size_limit=67108864").fetchone(), flush=True)
print(c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(), flush=True)
print(f"{time.time() - t:.0f}s", flush=True)
c.close()
PY
```

`wal_checkpoint` returns `(busy, log_pages, checkpointed_pages)`. **`busy` must be 0**; a 1 means
something still held the log and step 2 was not finished.

Watch it:

```bash
tail -f ~/wal-truncate.log
watch -n 10 'ls -la ~/till-data/prices/prices.db-wal'
```

### Check the container again before the VACUUM

**A deploy will recreate and start the container**, and `deploy.yml` runs on every push to `main`.
On 2026-09-23 that happened partway through a prune: the deletes committed, the log checkpointed
from 10.5 GB down to 0.28 GB, and then `VACUUM` failed with `database is locked` because the
container was back and holding the file. Fifty minutes of I/O, nothing reclaimed.

```bash
docker ps --format '{{.Names}} | {{.Status}}' | grep till     # expect nothing
sudo lsof ~/till-data/prices/prices.db | head                 # expect nothing
```

If the deletes are already done, only the reclaim is left, and it is one statement. Put it in a
file rather than a heredoc, and note `isolation_level=None` so the driver opens no transaction of
its own around it:

```python
# /tmp/vac.py
import sqlite3, time
t = time.time()
c = sqlite3.connect("/home/ubuntu/till-data/prices/prices.db", timeout=1800, isolation_level=None)
print("checkpoint:", c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(), flush=True)
print("freelist:", c.execute("PRAGMA freelist_count").fetchone(), flush=True)
c.execute("VACUUM")
print(f"vacuum ok in {time.time() - t:.0f}s", flush=True)
c.close()
```

```bash
SQLITE_TMPDIR=$HOME/till-data/prices nohup python3 /tmp/vac.py > ~/vacuum.log 2>&1 &
```

`freelist_count` is the number worth reading before it starts: **5,237,490 pages at 4 KiB is
21.5 GB free inside the file**, which is exactly what the VACUUM returns. And the checkpoint's
first field must be `0`; a `1` means something still holds the log.

**4. Confirm before restarting.**

```bash
ls -la ~/till-data/prices/               # both the .db and the -wal should be much smaller
python3 -c "import sqlite3;print(sqlite3.connect('file:/home/ubuntu/till-data/prices/prices.db?mode=ro',uri=True).execute('PRAGMA quick_check').fetchone())"
```

`quick_check` rather than `integrity_check`: the full check reads every page of a 29 GB file and this
box does not have the time or the cache for it.

**5. Start, and watch the health check rather than the log.**

```bash
docker start till-infinity
sleep 90
docker inspect till-infinity --format '{{.State.Health.Status}} {{.State.Health.FailingStreak}}'
```

A streak that stays at 0 for a few minutes is the recovery. If `database is locked` returns
immediately, the rebuild did not happen - go back to step 2 and find what held the file.

**6. Put the cron back.**

```bash
crontab -l | sed 's|^#\(\*/30 .*rate-watch.sh\)|\1|' | crontab -
```

## Why it grew, and what now stops it

Three separate omissions, all now closed in code:

| | was | now |
| --- | --- | --- |
| the log file | `journal_size_limit` unset, so it never shrank | capped at 64 MiB in `shared/db.py` |
| `quotes` | pruned by nothing, ever | `retain_quote_days`, 14 days, trimmed by the collector hourly |
| `bars` | a 1,000-per-series policy reachable only from the CLI | still the CLI - see below |

The collector's hourly trim is **quotes only and never a VACUUM**. The delete is a range scan over
an index and costs little; reclaiming what it frees means rewriting the file, which is this page. So
the table stops growing while the desk stays up, and the file shrinks when somebody decides to take
the outage.

`bars` are deliberately left to the CLI. Their retention is a window function over every series -
far heavier than a range delete - and they are already bounded per series by construction, where
quotes were bounded by nothing at all.

## What still needs deciding

**The cron opens the prices database every thirty minutes** to count rows, on a box where opening it
is expensive. It is a measurement job reading a 29 GB file on the production disk; it belongs against
a copy, or against the journal alone, or not on a timer.

**Whether fourteen days of quotes is right.** It is chosen to be comfortably more than any consumer
reads - `spreads.py` buckets over days - rather than measured. If the spread book ever wants a longer
history, this is the number to look at first.

**The MT5 bridge is a separate outage** and truncating the log does not touch it: nothing listens on
`tis:8000`, there is no tunnel process, and the container gets `ConnectionRefused` to
`172.17.0.1:8000` where `TRADING_MT5_URL` points. `trading` had already been silent for over a day
when the prices failure began, so the two are independent and this page only fixes the second.
