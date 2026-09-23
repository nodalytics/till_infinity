# Recovering a grown write-ahead log

Written after it took the desk out on 2026-09-23. The code fix that stops it happening again is in
`shared/db.py`; **this page is the one-off recovery**, because a WAL that is already oversized has
to be truncated by hand.

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

## Recovery

Read the whole sequence before starting. Steps 1 and 2 are what make step 3 safe.

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

The `lsof` is the check that matters. If anything still holds the log, find it before continuing -
truncating under a live reader does nothing and wastes the outage.

**3. Truncate the log.** A checkpoint is an ordinary, non-destructive SQLite operation: it moves log
content into the database. Detach it, because 13 GB on this disk takes a while and an SSH drop should
not be what decides the outcome.

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

**4. Confirm before restarting.**

```bash
ls -la ~/till-data/prices/               # the -wal should now be small
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
immediately, the log was not truncated - go back to step 2 and find the holder.

**6. Put the cron back.**

```bash
crontab -l | sed 's|^#\(\*/30 .*rate-watch.sh\)|\1|' | crontab -
```

## What still needs deciding

**The cron opens the prices database every thirty minutes** to count rows, on a box where opening it
is expensive. It is a measurement job reading a 29 GB file on the production disk; it belongs against
a copy, or against the journal alone, or not on a timer.

**29.5 GB of bars on a 3 GB box is the structural problem.** Pruning or archiving the oldest bars is
the fix that makes the rest of this stop mattering; capping the log only stops it getting worse.

**The MT5 bridge is a separate outage** and truncating the log does not touch it: nothing listens on
`tis:8000`, there is no tunnel process, and the container gets `ConnectionRefused` to
`172.17.0.1:8000` where `TRADING_MT5_URL` points. `trading` had already been silent for over a day
when the prices failure began, so the two are independent and this page only fixes the second.
