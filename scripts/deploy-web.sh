#!/usr/bin/env bash
# Deploy the dashboard. **This script must never touch the trading container.**
#
# It runs on the same two-core host as the live desk, so every decision here is
# about staying out of its way:
#
# * it operates on exactly one container name and refuses any other;
# * it never calls `docker stop`, `rm`, `restart` or `kill` on a name it did
#   not create, and the guard below is the only place a name is resolved;
# * it bounds CPU, memory and block IO so a dashboard request cannot take
#   cycles the desk needs - `tis-research-jobs-starve-the-service` is a
#   measured outage on this box from exactly that;
# * it publishes to **loopback only**. The dashboard shows a live account's
#   positions and P&L and there is no client authentication in front of it, so
#   reaching it means an SSH tunnel and that is deliberate.
#
# `deploy.yml` excludes `web/**` and this is invoked by `deploy-web.yml`, so
# the two pipelines never fire for the same commit.
set -euo pipefail

IMAGE="${IMAGE:?set IMAGE}"
TAG="${TAG:-latest}"
NAME="till-web"
DATA="${DATA:-/home/ubuntu/till-data}"

#: Published on loopback only. 127.0.0.1 is not a default to be overridden
#: casually: binding this to 0.0.0.0 publishes an unauthenticated view of a
#: live account to the network.
BIND="${BIND:-127.0.0.1}"
PORT="${PORT:-3000}"

# **The guard, before anything destructive.** A typo in NAME that resolved to
# the trading container would stop the desk, and this script's whole premise is
# that it cannot.
if [[ "$NAME" != "till-web" ]]; then
  echo "refusing: this script deploys till-web and nothing else" >&2
  exit 1
fi

echo "==> pulling $IMAGE:$TAG"
docker pull "$IMAGE:$TAG"

# Two cores, shared with the desk, whose own deploy claims 90% of them as a
# limit. A dashboard is idle between requests and must stay that way under
# load, so a quarter of one core is the ceiling and the block-IO weight is
# floored: the journal it reads is a 3.8GB file on the same disk the desk
# writes to, and starving that disk is the failure this is sized to avoid.
CPUS="${CPUS:-0.25}"
MEMORY="${MEMORY:-384m}"
BLKIO="${BLKIO:-100}"

echo "==> replacing $NAME (cpus=$CPUS memory=$MEMORY bind=$BIND:$PORT)"
docker stop -t 15 "$NAME" >/dev/null 2>&1 || true
docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --cpus "$CPUS" \
  --memory "$MEMORY" \
  --memory-swap "$MEMORY" \
  --blkio-weight "$BLKIO" \
  --pids-limit 256 \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -p "$BIND:$PORT:3000" \
  -e TILL_WEB_READ_TTL="${TILL_WEB_READ_TTL:-30}" \
  `# The host-side publish address, which is what decides exposure. The`\
  `# container binds 0.0.0.0 so the published port can reach it at all.`\
  -e TILL_WEB_BIND="$BIND" \
  -e TILL_JOURNAL_DB="${TILL_JOURNAL_DB:-/data/journal/journal.db}" \
  -v "$DATA:/data:ro" \
  "$IMAGE:$TAG" >/dev/null

# **Running is not healthy.** `--restart unless-stopped` keeps a container that
# exits immediately in a restart loop, and `State.Running` reads true while it
# is in backoff - the desk's own deploy script records that trap at length.
echo "==> waiting for health"
for _ in $(seq 1 30); do
  state="$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null || echo starting)"
  restarts="$(docker inspect -f '{{.RestartCount}}' "$NAME" 2>/dev/null || echo 0)"
  if [[ "$state" == "healthy" ]]; then
    echo "==> $NAME healthy on $BIND:$PORT"
    exit 0
  fi
  if [[ "${restarts:-0}" -gt 2 ]]; then
    echo "refusing: $NAME has restarted $restarts times" >&2
    docker logs --tail 40 "$NAME" >&2 || true
    exit 1
  fi
  sleep 5
done

echo "refusing: $NAME did not become healthy" >&2
docker logs --tail 40 "$NAME" >&2 || true
exit 1
