#!/usr/bin/env bash
# Replace the running container with a new image. Run on the instance.
#
#   IMAGE=ghcr.io/owner/repo TAG=<sha> bash run.sh
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

echo "pulling $IMAGE:$TAG"
docker pull "$IMAGE:$TAG"

# Stop the old one *after* the pull succeeds, so a registry problem leaves the
# previous version running rather than nothing at all.
docker rm -f "$NAME" 2>/dev/null || true

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --memory 640m \
  --memory-swap 640m \
  --cpus 1.5 \
  -e TZ=UTC \
  --env-file /home/ubuntu/till.env \
  -v "$DATA:/app/.data" \
  --log-opt max-size=10m --log-opt max-file=3 \
  "$IMAGE:$TAG" run

# 3.3 GB free on a 6.7 GB disk, and every deploy adds an image. Without this
# the box fills up and the failure arrives weeks later as a confusing one.
docker image prune -af --filter "until=72h" >/dev/null 2>&1 || true

docker ps --filter "name=$NAME" --format '{{.Names}}  {{.Status}}  {{.Image}}'
