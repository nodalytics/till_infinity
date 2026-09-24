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
about **861 MB** measured - before Redis, before any data, before the OS. On
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
  left on device`. The cleanup was already there - it ran *after* the pull, so
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

243 MB against a 640 MB cap on a 908 MB box - **and that reading is from six
instruments.** At fourteen it sits nearer 260-280 MB and has peaked at 400 MB,
which on this box is the edge.

The cap exists so that a leak takes the container down and the restart policy
brings it back, instead of the kernel choosing what to kill. **On 2026-08-14 the
kernel chose anyway**, five times, and the way it presented is worth
recognising: `docker inspect` reported `OOMKilled: false` while `dmesg` showed
`Out of memory: Killed process … (till-infinity)` with `constraint=
CONSTRAINT_NONE`. The container never reached its 640 MB cap. The *host* ran out
- 908 MB total, ~150 MB free - so the cap was never the binding constraint and
the container's own flag was truthful and useless.

Two things follow for sizing:

- **Watch resident size against the host, not the cap.** A container comfortably
  inside its limit can still be the largest process on the box, which is all the
  OOM killer is choosing on.
- **There is no swap**, so an overshoot is a kill rather than a slowdown. That
  does not improve on a larger machine; it just gets harder to reach.

Nothing heavier than a read should run alongside it at this size. Both
`till-infinity agents ask` and `till-infinity prices prune` - each a second
Python process importing the whole application - killed the container outright.

Databases and model state live on a mounted volume. Without one they go when
the container does, and for online models that means starting cold - no learned
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

`/home/ubuntu/till.env` holds every live credential - the Telegram bot token
and chat ids, the Gemini and Groq keys, the model and fallback list, the notify
cooldown and rate. It is not in git, not in GitHub secrets, and not in the
image. `deploy.sh` writes defaults only when the file is **absent** and never
overwrites it, which is what keeps a deploy from silently reverting a
configured box - and also what means nothing recreates it if the instance goes
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
| `EC2_USER` | the SSH user, `ubuntu` - see the path note below |
| `EC2_SSH_KEY` | the **private** key, whole file including the header and footer lines |

```bash
gh secret set EC2_HOST  --body "ec2-…compute.amazonaws.com"
gh secret set EC2_USER  --body "ubuntu"
gh secret set EC2_SSH_KEY < ~/.ssh/new-instance.pem
```

`GITHUB_TOKEN` is issued per run by Actions and is not migrated.

Set all three before the next push to `main`, or the deploy runs against the
old host - `paths-ignore` skips prose, but any code change deploys.

### 3. What the instance has to provide

- **The user must be `ubuntu`**, or `deploy.sh` needs editing:
  `/home/ubuntu/till-data` and `/home/ubuntu/till.env` are written into it.
  Setting `EC2_USER` to anything else changes who SSHes in but not those paths,
  and the mismatch shows up as a container with an empty data directory rather
  than as an error.
- **Docker, usable without `sudo`** by that user. `deploy.sh` calls `docker`
  directly.
- **The public key** matching `EC2_SSH_KEY` in that user's
  `~/.ssh/authorized_keys`.
- **Disk.** Images run near 973MB and the old box reached 99% of 6.7GB with
  five of them, which is why `deploy.sh` prunes *before* it pulls. Give the new
  one room and the pruning stops being load-bearing.
- **No registry credential is needed** while the package is public: `deploy.sh`
  contains no `docker login` and the old instance has no
  `~/.docker/config.json`. If the package is ever made private, deploys break
  at the pull with an error that does not mention permissions - add a
  `docker login ghcr.io` with a read-only PAT at that point, not before.

### 4. Data worth carrying over

```
journal    40M   the decision journal - irreplaceable, this is the learning history
news      9.7M   headlines and the calendar, re-fetchable but slow
prices    960M   candles and quotes, fully re-backfillable
structures 14M   model state - do not bother, see below
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

### 5. The limits size themselves; swap does not

`deploy.sh` no longer pins the memory limit. It takes **70% of the host's total**,
floored at 512m - which is 635MB on the old 908MB instance, near enough the 640m
it used to hard-code, and 2,676MB on a 3.8GB one. The pin was wrong on both
boxes it ran on: too small to use a bigger machine, and silently
over-committed on a smaller one.

What is still worth setting by hand is **swap**, because there is none:

- `--memory-swap` equal to `--memory` means **no swap for the container**, and
  neither instance has host swap either, which is why every overrun was a kill
  rather than a slowdown.
- The kills that mattered were `global_oom` on the *host* with
  `oomkilled=false` on the container - a confusing pair to read, and the reason
  the host needs headroom of its own rather than just a generous cgroup.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Then revisit
[todo.md](todo.md)'s standing note that nothing heavier than a read can run
alongside the service; it was true of the old hardware and is the reason
several diagnostics this project needs have never been run.

## The Deribit option-surface recorder

**It runs on the research machine and never on the instance.** Production has two
cores and a 2.6 GB container limit, and running research there OOM-killed the live
desk three times on 2026-09-10. This is a collector rather than a study, but it is
still research and it belongs on the box that cannot take the desk down with it.

**It cannot trade.** Two public endpoints, `get_instruments` and
`get_book_summary_by_currency`, no authentication and no `app_id`. There is no
`private/` route in the file and `tests/test_deribit_recorder.py` asserts that
against the module's string literals through the AST - not its raw text, which
cannot tell a call from a mention.

```bash
./.secrets/lab.sh sync
./.secrets/lab.sh run research/harness/deribit_recorder.py OUT=/home/<user>/options-data
./.secrets/lab.sh log deribit_recorder     # sweeps, one every five minutes
./.secrets/lab.sh done deribit_recorder    # "running", or done if it stopped
```

A healthy sweep line reads `sweep N: ~1450 rows`. **Zero rows is the failure to
look for**, and it is not an outage: Deribit answers HTTP 200 with a JSON-RPC error
body, so the collector cannot distinguish a refusal from an empty market without
checking, and it writes **no file** rather than a header with nothing under it. A
sweep reporting far fewer rows than usual means the instrument join is dropping
them - roughly a quarter of listed strikes have no book at all and are dropped by
design, so expect about 1,450 of 1,900.

**A week of this is the input to `implied_vs_ours.py`**, which is the gate for the
whole options programme: if our volatility forecasts cannot beat `mark_iv` by more
than the recorded bid/ask cost, no execution path gets built. That harness refuses
to score until enough has been recorded for the option windows to have closed, and
says so rather than reporting a number from nothing.

## Notes moved out of the deploy files

Condensed on 2026-09-19. Each passage below stood in the file named, at
the line named, and its first sentence is still there. Every one of these
is a failure that happened rather than a precaution: a race between two
deploys, a disk that filled because cleanup ran after the pull, a pull
that died on a dangling containerd lease, a window with no container at
all.

### `deploy.sh`

**line 2**


  IMAGE=ghcr.io/owner/repo TAG=<sha> bash deploy.sh

One container, not the compose split. Six separate services need about 861 MB
before Redis, data or the OS - measured, not estimated - against the 908 MB
this started on. `till-infinity run` is one process with an in-process bus,
which is the shape that hardware could hold.

The instance is larger now and the split would fit, but one process is also
what makes the in-process bus possible, so this is no longer only a memory
decision. The memory limit below is derived from the host rather than pinned,
so the same script is correct on either.

**line 18**

them wastes a pull and produces confusing output - on 2026-09-15 a hand
deploy and an automatic one interleaved, and the loser reported "could not
rename the running container" while the winner was quietly succeeding. The
outcome was correct because the rename is guarded, but nobody reading the
output could tell that.

**line 45**

Agents are off: they need a paid credential, and this box has 908 MB of RAM,
so the free path is the one that fits. Set AGENTS_ENABLED=1 and add a key to
turn them on.

**line 61**

`set -e` ends the script above the line that would have fixed it. That is how
this box reached 99% full with five 973 MB images on a 6.7 GB disk.

`-af` with no age filter, because an age filter is the same bug in slower
form - several deploys in one day are all newer than any window worth setting.
Docker never removes the image a running container is using, so the version
currently serving is safe; what is lost is a local copy of the *previous*
one, and that lives in the registry, which is where a rollback should come
from anyway.

**line 77**


  Error response from daemon: lease does not exist: not found

It is transient - the same pull succeeds immediately afterwards - but the
deploy job fails, and a failed deploy is the quietest failure here: the
previous image keeps running and keeps reporting healthy, so the only symptom
is that a change nobody doubted is not actually live. That went unnoticed for
twenty minutes once.

**line 100**

Removing it here leaves a window with no container, and two things can go
wrong in that window. The new one may fail to start, and then the desk is
down with nothing to put back. Or another deploy can land inside it, in which
case `docker run` below fails on a name conflict and this script exits
reporting success over somebody else's container. Both were reached in
practice on 2026-09-15.

Stopped first, because two containers both holding broker sessions would both
place orders. The rename costs nothing and buys an undo.

**line 124**

`-prev` to restore, which left the desk with no container at all - exactly
the outcome the rollback exists to prevent, reached by the rollback itself.
There is no previous container whenever another deploy has just replaced it,
which on this box is a normal race rather than an unusual one.

A container that started and looks unhealthy is worth keeping if the
alternative is nothing: it may recover, its logs can be read, and it can be
replaced deliberately. Nothing recovers from nothing.

**line 144**

left the host itself enough to breathe. Hard-coding it means a bigger machine
runs the service in a 640MB box and wastes the rest, while a smaller one
would be over-committed on the first deploy and nobody would notice until the
kills started.

70% of total, floored at 512m so a tiny instance still starts and can say why
it is unhappy.

**line 167**

tunnel bound to the docker bridge. Without this the container cannot
resolve the host at all and TRADING_MT5_URL has nowhere to point.
Costs nothing when trading is off, which is the default.` \

**line 182**

`.State.Running` reads true for the instants it is up - so a crash-looper
passes a naive check and the rollback gets deleted underneath it. A restart
count above zero this soon is a container that has already died once.
**Given time to settle, and asked twice.** Twenty seconds was not enough: a
healthy container failed this check on 2026-09-15 and was deleted for it. The
desk loads a 145MB state file at start, so a single sample taken while that
is happening says nothing. `tr -d` because a stray newline in the captured
value made the failure message unreadable and the comparison meaningless.

### `.github/workflows/deploy.yml`

**line 1**

The instance does not build its own image: a `uv sync` of river and pandas is
slow on two cores at best and was OOM-killed at worst on the 908MB box this
started on. GitHub builds and publishes; the instance pulls.

For **both** architectures, since they are not all the same - the box may be
Graviton, and an amd64-only image fails at the pull rather than at the build.

**line 15**

backfill, and one of them was a docs-only commit; the level pipeline was
down for four hours across them. A push that cannot alter the image
should not restart the service.

`paths-ignore` skips the run only when *every* changed file matches, so a
commit touching code and docs together still deploys.

**line 43**

manifest for linux/arm64/v8", which is a clear message arriving at the
least convenient moment - after the old box has been stopped for the
cutover.

Native runners rather than QEMU. The repository is public, so
`ubuntu-24.04-arm` is free, and emulating an arm64 build of pandas and
river costs an order of magnitude more wall clock than running it on the
architecture it targets.

**line 158**

before a single byte is transferred, so a full disk cannot fail the scp
either; and it holds even when deploying a commit whose `deploy.sh`
predates that fix - a rollback to an old tag is exactly when the box is
already full. Reporting free space makes the next failure legible
instead of arriving as `no space left on device` with no context.

### `pyproject.toml`

**line 35**

running Windows terminal, and there is no Linux wheel to build against. The
marker keeps `uv sync --all-extras` working in CI on Linux, where this
resolves to nothing and the bridge backend is used instead.

**line 67**

gates should not block CI on them - and a lint failure there would stop a
deploy over a scratch script.

The whole `research` folder rather than `research/harness` alone: a harness
and the page reporting it are the same artefact, and splitting the exclusion
meant a scratch script one directory up could still block a deploy.

`assets` is the same category: a generator run by hand to produce the logo
SVGs, judged by looking at what comes out. It is not imported by anything.
The exclusion was added after it did exactly what the paragraph above warns
about - an unsorted import block in a logo script failed CI and blocked a
deploy of the trading service.

**line 131**

A hook an implementation may leave alone still has to declare the arguments
its overrides receive, and `Broker.close` doing nothing is the correct
behaviour for a backend holding no connection - not an unfinished method.

**line 139**

into fewer exits would trade a readable refusal for a lint score. The branch
count is the same fact counted differently - two of the checks have already
been extracted to methods on their own merits, and further extraction would
be done to satisfy the counter rather than to make anything clearer.

**line 160**

transition. Splitting it would put half a state machine in another method and
make the order the transitions happen in harder to read, not easier, which is
the opposite of what the rule is for.

### `deploy.sh`

**line 2**


  IMAGE=ghcr.io/owner/repo TAG=<sha> bash deploy.sh

One container, not the compose split. Six separate services need about 861 MB
before Redis, data or the OS - measured, not estimated - against the 908 MB
this started on. `till-infinity run` is one process with an in-process bus,
which is the shape that hardware could hold.

The instance is larger now and the split would fit, but one process is also
what makes the in-process bus possible, so this is no longer only a memory
decision. The memory limit below is derived from the host rather than pinned,
so the same script is correct on either.

**line 18**

them wastes a pull and produces confusing output - on 2026-09-15 a hand
deploy and an automatic one interleaved, and the loser reported "could not
rename the running container" while the winner was quietly succeeding. The
outcome was correct because the rename is guarded, but nobody reading the
output could tell that.

**line 61**

`set -e` ends the script above the line that would have fixed it. That is how
this box reached 99% full with five 973 MB images on a 6.7 GB disk.

`-af` with no age filter, because an age filter is the same bug in slower
form - several deploys in one day are all newer than any window worth setting.
Docker never removes the image a running container is using, so the version
currently serving is safe; what is lost is a local copy of the *previous*
one, and that lives in the registry, which is where a rollback should come
from anyway.

**line 77**


  Error response from daemon: lease does not exist: not found

It is transient - the same pull succeeds immediately afterwards - but the
deploy job fails, and a failed deploy is the quietest failure here: the
previous image keeps running and keeps reporting healthy, so the only symptom
is that a change nobody doubted is not actually live. That went unnoticed for
twenty minutes once.

**line 100**

Removing it here leaves a window with no container, and two things can go
wrong in that window. The new one may fail to start, and then the desk is
down with nothing to put back. Or another deploy can land inside it, in which
case `docker run` below fails on a name conflict and this script exits
reporting success over somebody else's container. Both were reached in
practice on 2026-09-15.

Stopped first, because two containers both holding broker sessions would both
place orders. The rename costs nothing and buys an undo.

**line 124**

`-prev` to restore, which left the desk with no container at all - exactly
the outcome the rollback exists to prevent, reached by the rollback itself.
There is no previous container whenever another deploy has just replaced it,
which on this box is a normal race rather than an unusual one.

A container that started and looks unhealthy is worth keeping if the
alternative is nothing: it may recover, its logs can be read, and it can be
replaced deliberately. Nothing recovers from nothing.

**line 144**

left the host itself enough to breathe. Hard-coding it means a bigger machine
runs the service in a 640MB box and wastes the rest, while a smaller one
would be over-committed on the first deploy and nobody would notice until the
kills started.

70% of total, floored at 512m so a tiny instance still starts and can say why
it is unhappy.

**line 167**

tunnel bound to the docker bridge. Without this the container cannot
resolve the host at all and TRADING_MT5_URL has nowhere to point.
Costs nothing when trading is off, which is the default.` \

**line 182**

`.State.Running` reads true for the instants it is up - so a crash-looper
passes a naive check and the rollback gets deleted underneath it. A restart
count above zero this soon is a container that has already died once.
**Given time to settle, and asked twice.** Twenty seconds was not enough: a
healthy container failed this check on 2026-09-15 and was deleted for it. The
desk loads a 145MB state file at start, so a single sample taken while that
is happening says nothing. `tr -d` because a stray newline in the captured
value made the failure message unreadable and the comparison meaningless.

### `deploy.sh`

**line 2**


  IMAGE=ghcr.io/owner/repo TAG=<sha> bash deploy.sh

One container, not the compose split. Six separate services need about 861 MB
before Redis, data or the OS - measured, not estimated - against the 908 MB

**line 10**

The instance is larger now and the split would fit, but one process is also
what makes the in-process bus possible, so this is no longer only a memory
decision. The memory limit below is derived from the host rather than pinned,
so the same script is correct on either.

**line 18**

them wastes a pull and produces confusing output - on 2026-09-15 a hand
deploy and an automatic one interleaved, and the loser reported "could not
rename the running container" while the winner was quietly succeeding. The
outcome was correct because the rename is guarded, but nobody reading the
output could tell that.

**line 67**

currently serving is safe; what is lost is a local copy of the *previous*
one, and that lives in the registry, which is where a rollback should come
from anyway.

**line 77**


  Error response from daemon: lease does not exist: not found

It is transient - the same pull succeeds immediately afterwards - but the
deploy job fails, and a failed deploy is the quietest failure here: the
previous image keeps running and keeps reporting healthy, so the only symptom
is that a change nobody doubted is not actually live. That went unnoticed for
twenty minutes once.

**line 100**

Removing it here leaves a window with no container, and two things can go
wrong in that window. The new one may fail to start, and then the desk is
down with nothing to put back. Or another deploy can land inside it, in which

**line 106**


Stopped first, because two containers both holding broker sessions would both
place orders. The rename costs nothing and buys an undo.

**line 127**

which on this box is a normal race rather than an unusual one.

A container that started and looks unhealthy is worth keeping if the
alternative is nothing: it may recover, its logs can be read, and it can be
replaced deliberately. Nothing recovers from nothing.

**line 144**

left the host itself enough to breathe. Hard-coding it means a bigger machine
runs the service in a 640MB box and wastes the rest, while a smaller one
would be over-committed on the first deploy and nobody would notice until the
kills started.

70% of total, floored at 512m so a tiny instance still starts and can say why
it is unhappy.

**line 185**

**Given time to settle, and asked twice.** Twenty seconds was not enough: a
healthy container failed this check on 2026-09-15 and was deleted for it. The
desk loads a 145MB state file at start, so a single sample taken while that

