#!/usr/bin/env bash
# Replace the running container with a new image. **Runs on the instance**,
# not here — the deploy workflow copies it across and executes it there.
#
#   IMAGE=ghcr.io/owner/repo TAG=<sha> bash deploy.sh
#
# One container, not the compose split. The box has 908 MB of RAM and six
# separate services need about 861 MB before Redis, data or the OS — measured,
# not estimated. `till-infinity run` is one process with an in-process bus,
# which is the shape this hardware can actually hold.
set -euo pipefail

IMAGE="${IMAGE:?set IMAGE}"
TAG="${TAG:-latest}"
NAME="till-infinity"
DATA="/home/ubuntu/till-data"

mkdir -p "$DATA"

# Written once, then left alone — this is the file to edit on the box to turn
# agents on or point at a different instrument set. Recreating it on every
# deploy would silently discard whatever was configured there.
ENV_FILE="/home/ubuntu/till.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "no $ENV_FILE — writing defaults"
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
# form — several deploys in one day are all newer than any window worth setting.
# Docker never removes the image a running container is using, so the version
# currently serving is safe; what is lost is a local copy of the *previous*
# one, and that lives in the registry, which is where a rollback should come
# from anyway.
echo "reclaiming disk before the pull"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -af >/dev/null 2>&1 || true
df -h / | awk 'NR==2 {print "  " $4 " free of " $2}'

echo "pulling $IMAGE:$TAG"
docker pull "$IMAGE:$TAG"

# Stop the old one *after* the pull succeeds, so a registry problem leaves the
# previous version running rather than nothing at all.
docker rm -f "$NAME" 2>/dev/null || true

# Sized from the host rather than pinned, because the pin was wrong on both
# boxes it ever ran on. 640m was chosen for a 908MB instance — about 70%, which
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
  -v "$DATA:/app/.data" \
  --log-opt max-size=10m --log-opt max-file=3 \
  "$IMAGE:$TAG" run

# The old image is only unreferenced once the new container is up, so a second
# sweep here collects it. The one above is what guarantees room to pull; this
# one is what stops the box sitting at two images between deploys.
docker image prune -af >/dev/null 2>&1 || true

docker ps --filter "name=$NAME" --format '{{.Names}}  {{.Status}}  {{.Image}}'
