# Running it somewhere

Three shapes, and which one is right is decided by how much memory the machine
has rather than by preference.

| | processes | bus | when |
|---|---|---|---|
| `till-infinity run` | one | in-process | a laptop, an end-to-end check, a small box |
| `docker compose` | one per service | Redis | anywhere the services should scale or fail apart |
| CI → GHCR → instance | one | in-process | a small always-on server |

## One process

```bash
uv run till-infinity run
```

Every service against one in-process bus. Nothing to install, nothing to
coordinate, and the whole system in one log.

## One container per service

```bash
cp .env.example .env
docker compose up -d                    # collectors, levels, journal
docker compose --profile agents up -d   # including the paid one
```

This is the shape the bus was designed for: they scale and fail independently,
so a collector restarting does not take the levels model with it. Agents sit
behind a profile because they are the only part that costs money.

**It needs real memory.** Six Python processes with the modules imported cost
about **861 MB** measured — before Redis, before any data, before the OS. On
anything under ~2 GB use the single process instead.

## Continuous deployment

`.github/workflows/deploy.yml` runs on push to `main`: the tests, then a build
published to GHCR, then the instance pulls it.

```bash
gh secret set EC2_HOST    --body "your-instance.compute.amazonaws.com"
gh secret set EC2_USER    --body "ubuntu"
gh secret set EC2_SSH_KEY < path/to/key.pem
```

### Why the instance does not build

Building river and pandas on two cores and 908 MB is slow at best and
OOM-killed at worst. It is also slow to *send*: pushing a 234 MB image from a
laptop to Tokyo ran at about 10 KB/s. A runner and a registry both sitting in
AWS have neither problem.

### What the deploy script is careful about

- **Pull before stopping the old container.** A registry problem then leaves
  the previous version running rather than nothing at all.
- **Tag by commit as well as `latest`.** A rollback is a tag change rather than
  a rebuild of something that no longer exists.
- **Write the env file once.** Recreating it every deploy would silently
  discard whatever had been configured on the box, which is the worse failure
  because it looks like it worked.
- **Prune old images *before* the pull.** An image per deploy on a 6.7 GB disk
  fills up weeks later, as a confusing failure rather than an obvious one. It
  did: five 973 MB images took the box to 99% and the deploy died on `no space
  left on device`. The cleanup was already there — it ran *after* the pull, so
  `set -e` ended the script above the line that would have fixed it, and it
  carried an `until=72h` filter that spares every image from a busy day. A
  cleanup that only runs when it was not needed is not a cleanup. Docker never
  removes the image a running container is using, so `-af` before the pull is
  safe; a rollback should come from the registry, not the local cache.
- **Check it came back up.** A deploy that reports success without looking is a
  deploy that reports success while the container restart-loops.

### Sizing it

Measured on the running instance:

```
till-infinity | Up (healthy) | 243.5 MiB / 640 MiB
```

243 MB against a 640 MB cap on a 908 MB box — **and that reading is from six
instruments.** At fourteen it sits nearer 260–280 MB and has peaked at 400 MB,
which on this box is the edge.

The cap exists so that a leak takes the container down and the restart policy
brings it back, instead of the kernel choosing what to kill. **On 2026-08-14 the
kernel chose anyway**, five times, and the way it presented is worth
recognising: `docker inspect` reported `OOMKilled: false` while `dmesg` showed
`Out of memory: Killed process … (till-infinity)` with `constraint=
CONSTRAINT_NONE`. The container never reached its 640 MB cap. The *host* ran out
— 908 MB total, ~150 MB free — so the cap was never the binding constraint and
the container's own flag was truthful and useless.

Two things follow for sizing:

- **Watch resident size against the host, not the cap.** A container comfortably
  inside its limit can still be the largest process on the box, which is all the
  OOM killer is choosing on.
- **There is no swap**, so an overshoot is a kill rather than a slowdown. That
  does not improve on a larger machine; it just gets harder to reach.

Nothing heavier than a read should run alongside it at this size. Both
`till-infinity agents ask` and `till-infinity prices prune` — each a second
Python process importing the whole application — killed the container outright.

Databases and model state live on a mounted volume. Without one they go when
the container does, and for online models that means starting cold — no learned
distributions, no levels, no touch history.

## Configuration

Everything comes from the environment, documented in
[`.env.example`](../.env.example). Real environment variables win over the
file, so a deployment is never overridden by a stray `.env`.

Agents are **off** unless `AGENTS_ENABLED=1`. They are the only part needing a
paid credential, and the collectors and levels model should not be hostage to
one.

## Moving to another instance

Three GitHub secrets point the deploy at a box, and they are the *easy* part.
Do the first item before touching anything else.

### 1. `till.env` exists nowhere but the instance

`/home/ubuntu/till.env` holds every live credential — the Telegram bot token
and chat ids, the Gemini and Groq keys, the model and fallback list, the notify
cooldown and rate. It is not in git, not in GitHub secrets, and not in the
image. `run.sh` writes defaults only when the file is **absent** and never
overwrites it, which is what keeps a deploy from silently reverting a
configured box — and also what means nothing recreates it if the instance goes
away.

Copy it off before the old instance is stopped, and keep it somewhere that
survives:

```bash
scp -i key.pem ubuntu@OLD_HOST:/home/ubuntu/till.env ./till.env.backup
```

Everything else on this page can be rebuilt from the repository. This cannot.

### 2. The three secrets

| secret | what it is |
|---|---|
| `EC2_HOST` | the new hostname or address |
| `EC2_USER` | the SSH user, `ubuntu` — see the path note below |
| `EC2_SSH_KEY` | the **private** key, whole file including the header and footer lines |

```bash
gh secret set EC2_HOST  --body "ec2-…compute.amazonaws.com"
gh secret set EC2_USER  --body "ubuntu"
gh secret set EC2_SSH_KEY < ~/.ssh/new-instance.pem
```

`GITHUB_TOKEN` is issued per run by Actions and is not migrated.

Set all three before the next push to `main`, or the deploy runs against the
old host — `paths-ignore` skips prose, but any code change deploys.

### 3. What the instance has to provide

- **The user must be `ubuntu`**, or `deploy/run.sh` needs editing:
  `/home/ubuntu/till-data` and `/home/ubuntu/till.env` are written into it.
  Setting `EC2_USER` to anything else changes who SSHes in but not those paths,
  and the mismatch shows up as a container with an empty data directory rather
  than as an error.
- **Docker, usable without `sudo`** by that user. `run.sh` calls `docker`
  directly.
- **The public key** matching `EC2_SSH_KEY` in that user's
  `~/.ssh/authorized_keys`.
- **Disk.** Images run near 973MB and the old box reached 99% of 6.7GB with
  five of them, which is why `run.sh` prunes *before* it pulls. Give the new
  one room and the pruning stops being load-bearing.
- **No registry credential is needed** while the package is public: `run.sh`
  contains no `docker login` and the old instance has no
  `~/.docker/config.json`. If the package is ever made private, deploys break
  at the pull with an error that does not mention permissions — add a
  `docker login ghcr.io` with a read-only PAT at that point, not before.

### 4. Data worth carrying over

```
journal    40M   the decision journal — irreplaceable, this is the learning history
news      9.7M   headlines and the calendar, re-fetchable but slow
prices    960M   candles and quotes, fully re-backfillable
structures 14M   model state — do not bother, see below
```

`journal` is the one to move. `prices` can be re-backfilled and is most of the
bulk; copying it is a convenience, not a requirement, and a fresh box with a
smaller prices database is a *faster* cold start.

Do **not** carry `structures/models.pkl`. `store._schema` fingerprints every
persisted class, so any field added since it was written makes the service
start cold anyway; moving it buys a warm start only if the code is byte-for-byte
the same shape, and finding out otherwise costs a restart.

```bash
rsync -avz -e "ssh -i key.pem" ubuntu@OLD_HOST:/home/ubuntu/till-data/journal/ \
      /tmp/journal/ && rsync -avz -e "ssh -i new-key.pem" /tmp/journal/ \
      ubuntu@NEW_HOST:/home/ubuntu/till-data/journal/
```

### 5. Raise the limits, deliberately

`run.sh` pins `--memory 640m --memory-swap 640m --cpus 1.5`, chosen for a
908MB two-core instance. They are not a safety margin to keep out of habit:

- `--memory-swap` equal to `--memory` means **no swap at all**, which is why
  every overrun on the old box was a kill rather than a slowdown.
- 640m of 908MB left the host itself short, and the kills that mattered were
  `global_oom` on the host with `oomkilled=false` on the container — a
  confusing pair to read, and the reason to give the host real headroom.

On a larger instance raise both and give the box swap. Then revisit
[todo.md](todo.md)'s standing note that nothing heavier than a read can run
alongside the service; it was true of the old hardware and is the reason
several diagnostics this project needs have never been run.
