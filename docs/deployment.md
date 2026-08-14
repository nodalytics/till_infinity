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
