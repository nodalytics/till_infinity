#!/usr/bin/env bash
# Replace the running container with a new image. **Runs on the instance**,
# not here - the deploy workflow copies it across and executes it there.
#
#   IMAGE=ghcr.io/owner/repo TAG=<sha> bash deploy.sh
#
# One container, not the compose split. Six separate services need about 861 MB
# before Redis, data or the OS - measured, not estimated - against the 908 MB
# this started on. `till-infinity run` is one process with an in-process bus,
# which is the shape that hardware could hold.
#
# The instance is larger now and the split would fit, but one process is also
# what makes the in-process bus possible, so this is no longer only a memory
# decision. The memory limit below is derived from the host rather than pinned,
# so the same script is correct on either.
set -euo pipefail

# **One deploy at a time.** This box deploys on every push and can also be
# driven by hand, so two runs overlapping is normal rather than exotic. Racing
# them wastes a pull and produces confusing output - on 2026-09-15 a hand
# deploy and an automatic one interleaved, and the loser reported "could not
# rename the running container" while the winner was quietly succeeding. The
# outcome was correct because the rename is guarded, but nobody reading the
# output could tell that.
exec 9>/home/ubuntu/.deploy.lock
if ! flock -w 600 9; then
  echo "another deploy has held the lock for ten minutes - not starting" >&2
  exit 1
fi

IMAGE="${IMAGE:?set IMAGE}"
TAG="${TAG:-latest}"
NAME="till-infinity"
DATA="/home/ubuntu/till-data"

mkdir -p "$DATA"

# Written once, then left alone - this is the file to edit on the box to turn
# agents on or point at a different instrument set. Recreating it on every
# deploy would silently discard whatever was configured there.
ENV_FILE="/home/ubuntu/till.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "no $ENV_FILE - writing defaults"
  cat > "$ENV_FILE" <<'DEFAULTS'
# Till Infinity on this instance. Edit and re-run the deploy to apply.
#
# Agents are off: they need a paid credential, and this box has 908 MB of RAM,
# so the free path is the one that fits. Set AGENTS_ENABLED=1 and add a key to
# turn them on.
AGENTS_ENABLED=0
PRICES_ENABLED=1
NEWS_ENABLED=1
STRUCTURES_ENABLED=1
JOURNAL=1
# No Telegram or Discord configured, so delivery is skipped rather than failed.
NOTIFICATIONS_ENABLED=1
TZ=UTC
DEFAULTS
fi

# Reclaim *before* pulling, not after. A cleanup that runs after the pull is
# unreachable exactly when it is needed: the disk fills, the pull fails, and
# `set -e` ends the script above the line that would have fixed it. That is how
# this box reached 99% full with five 973 MB images on a 6.7 GB disk.
#
# `-af` with no age filter, because an age filter is the same bug in slower
# form - several deploys in one day are all newer than any window worth setting.
# Docker never removes the image a running container is using, so the version
# currently serving is safe; what is lost is a local copy of the *previous*
# one, and that lives in the registry, which is where a rollback should come
# from anyway.
echo "reclaiming disk before the pull"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -af >/dev/null 2>&1 || true
df -h / | awk 'NR==2 {print "  " $4 " free of " $2}'

# Retried, because the prune above occasionally leaves containerd with a
# dangling content lease and the very next pull dies on it:
#
#   Error response from daemon: lease does not exist: not found
#
# It is transient - the same pull succeeds immediately afterwards - but the
# deploy job fails, and a failed deploy is the quietest failure here: the
# previous image keeps running and keeps reporting healthy, so the only symptom
# is that a change nobody doubted is not actually live. That went unnoticed for
# twenty minutes once.
echo "pulling $IMAGE:$TAG"
for attempt in 1 2 3; do
  if docker pull "$IMAGE:$TAG"; then
    break
  fi
  if [[ "$attempt" == 3 ]]; then
    echo "pull failed three times - leaving the running container alone" >&2
    exit 1
  fi
  echo "pull failed, retrying ($attempt of 3)"
  sleep 5
done

# **Renamed, not removed** - the old container is the rollback.
#
# Removing it here leaves a window with no container, and two things can go
# wrong in that window. The new one may fail to start, and then the desk is
# down with nothing to put back. Or another deploy can land inside it, in which
# case `docker run` below fails on a name conflict and this script exits
# reporting success over somebody else's container. Both were reached in
# practice on 2026-09-15.
#
# Stopped first, because two containers both holding broker sessions would both
# place orders. The rename costs nothing and buys an undo.
PREV="${NAME}-prev"
docker rm -f "$PREV" 2>/dev/null || true
ROLLBACK_FROM=""
if docker inspect "$NAME" >/dev/null 2>&1; then
  ROLLBACK_FROM="$(docker inspect "$NAME" --format '{{.Config.Image}}' 2>/dev/null)"
  docker stop -t 30 "$NAME" >/dev/null 2>&1 || true
  if ! docker rename "$NAME" "$PREV" 2>/dev/null; then
    echo "could not rename the running container - leaving it alone" >&2
    docker start "$NAME" >/dev/null 2>&1 || true
    exit 1
  fi
fi

# **Only removes the new container when there is genuinely something to put
# back.** The first version removed it first and then discovered there was no
# `-prev` to restore, which left the desk with no container at all - exactly
# the outcome the rollback exists to prevent, reached by the rollback itself.
# There is no previous container whenever another deploy has just replaced it,
# which on this box is a normal race rather than an unusual one.
#
# A container that started and looks unhealthy is worth keeping if the
# alternative is nothing: it may recover, its logs can be read, and it can be
# replaced deliberately. Nothing recovers from nothing.
restore_previous() {
  if [[ -z "$ROLLBACK_FROM" ]] || ! docker inspect "$PREV" >/dev/null 2>&1; then
    echo "nothing to roll back to - leaving the new container in place" >&2
    return 1
  fi
  echo "restoring ${ROLLBACK_FROM##*:}" >&2
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rename "$PREV" "$NAME" >/dev/null 2>&1 && docker start "$NAME" >/dev/null 2>&1
}

# Sized from the host rather than pinned, because the pin was wrong on both
# boxes it ever ran on. 640m was chosen for a 908MB instance - about 70%, which
# left the host itself enough to breathe. Hard-coding it means a bigger machine
# runs the service in a 640MB box and wastes the rest, while a smaller one
# would be over-committed on the first deploy and nobody would notice until the
# kills started.
#
# 70% of total, floored at 512m so a tiny instance still starts and can say why
# it is unhappy.
TOTAL_MB="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
LIMIT_MB="$(( TOTAL_MB * 70 / 100 ))"
[[ "$LIMIT_MB" -lt 512 ]] && LIMIT_MB=512
echo "host has ${TOTAL_MB}MB, giving the container ${LIMIT_MB}MB"

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --memory "${LIMIT_MB}m" \
  --memory-swap "${LIMIT_MB}m" \
  --cpus 1.5 \
  -e TZ=UTC \
  --env-file /home/ubuntu/till.env \
  `# Lets the container reach a service on the host, which the trading
   # backend needs: MetaTrader 5 is an x86-64 Windows binary and this box is
   # aarch64, so the terminal runs elsewhere and is reached through an SSH
   # tunnel bound to the docker bridge. Without this the container cannot
   # resolve the host at all and TRADING_MT5_URL has nowhere to point.
   # Costs nothing when trading is off, which is the default.` \
  --add-host=host.docker.internal:host-gateway \
  -v "$DATA:/app/.data" \
  --log-opt max-size=10m --log-opt max-file=3 \
  "$IMAGE:$TAG" run || {
    echo "the new container would not start" >&2
    restore_previous && exit 1
    echo "ROLLBACK FAILED - there is no container. Look now." >&2
    exit 2
  }

# **Running is not enough.** With `--restart unless-stopped` a container that
# exits immediately spends most of its life in restart backoff, and
# `.State.Running` reads true for the instants it is up - so a crash-looper
# passes a naive check and the rollback gets deleted underneath it. A restart
# count above zero this soon is a container that has already died once.
# **Given time to settle, and asked twice.** Twenty seconds was not enough: a
# healthy container failed this check on 2026-09-15 and was deleted for it. The
# desk loads a 145MB state file at start, so a single sample taken while that
# is happening says nothing. `tr -d` because a stray newline in the captured
# value made the failure message unreadable and the comparison meaningless.
alive() {
  local up restarts
  up="$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null | tr -d '[:space:]')"
  restarts="$(docker inspect -f '{{.RestartCount}}' "$NAME" 2>/dev/null | tr -d '[:space:]')"
  echo "${up:-false}/${restarts:-0}"
}

sleep 45
STATE="$(alive)"
if [[ "${STATE%%/*}" != "true" ]]; then
  sleep 30
  STATE="$(alive)"
fi
# Running is what matters. A restart count above zero on a container that is
# *currently up* means it stumbled and recovered, which is not a reason to
# throw away a deploy - a crash-looper is caught because it is not running when
# sampled twice, thirty seconds apart.
if [[ "${STATE%%/*}" != "true" ]]; then
  echo "new container is not running (state $STATE)" >&2
  if restore_previous; then
    exit 1
  fi
  echo "left the new container in place - no previous version to restore" >&2
  exit 2
fi
echo "up on ${TAG:0:7} (state $STATE)"
docker rm -f "$PREV" >/dev/null 2>&1 || true

# The old image is only unreferenced once the new container is up, so a second
# sweep here collects it. The one above is what guarantees room to pull; this
# one is what stops the box sitting at two images between deploys.
docker image prune -af >/dev/null 2>&1 || true

docker ps --filter "name=$NAME" --format '{{.Names}}  {{.Status}}  {{.Image}}'
