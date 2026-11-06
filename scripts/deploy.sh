#!/usr/bin/env bash
# Replace the running container with a new image. **Runs on the instance**,
# not here - the deploy workflow copies it across and executes it there.
# See docs/deployment.md.
# this started on. One process is the shape that hardware could hold, and
# since the Nautilus port it is also the shape the code has: one `TradingNode`
# with the statespace fold, the journal, the notifier and the desks all inside
# it, sharing one cache and one portfolio.
#
# The image's `ENTRYPOINT` is `python -m till_infinity.node.live` - there is no
# console script, deliberately, and this script passed `run` to one that did
# not exist until 2026-11-01.
#
# See docs/deployment.md.
set -euo pipefail

# **One deploy at a time.** This box deploys on every push and can also be
# driven by hand, so two runs overlapping is normal rather than exotic. Racing
# them wastes a pull and produces confusing output: on 2026-09-15 a hand deploy
# and an automatic one interleaved, and the loser reported "could not rename the
# running container" while the winner was quietly succeeding.
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
# currently serving is safe. What is lost is a local copy of the *previous* one,
# and that lives in the registry, which is where a rollback should come from.
# **Built here instead of pulled.** `LOCAL_IMAGE=1` says the tag already
# exists on this machine, which is how this box deploys when the registry
# cannot be reached or CI cannot build - on 2026-10-09 GitHub Actions stopped
# starting jobs over billing and two merged changes could not reach the desk at
# all. The instance is aarch64, so it builds its own image natively with no
# emulation and no registry round trip, which is the shortest path there is.
#
# Both steps below have to be skipped together, and the first is the one that
# bites: `docker image prune -af` removes every image not attached to a running
# container, which includes the one just built. Skipping only the pull would
# delete the image and then fail to replace it.
if [[ "${LOCAL_IMAGE:-0}" == "1" ]]; then
  if ! docker image inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
    echo "LOCAL_IMAGE=1 but $IMAGE:$TAG is not on this machine" >&2
    exit 1
  fi
  echo "using the local $IMAGE:${TAG:0:12} - no prune, no pull"
  df -h / | awk 'NR==2 {print "  " $4 " free of " $2}'
else
echo "reclaiming disk before the pull"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -af >/dev/null 2>&1 || true
df -h / | awk 'NR==2 {print "  " $4 " free of " $2}'

# Retried, because the prune above occasionally leaves containerd with a
# dangling content lease and the very next pull dies on it:
# See docs/deployment.md.
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
fi

# **Preflight: build the node from this host's environment, in the image about
# to be deployed, before anything is switched over.**
#
# Everything that reads configuration happens in `build` - rule names, entry
# and exit names, symbols, venues, bar types - so a stale variable raises here
# instead of in a container that has already replaced a working desk. On
# 2026-11-03 sixteen retired rule names got through and cost 27 restarts; this
# check exits non-zero on that environment in a few seconds and leaves the
# running container untouched.
#
# **Before the rename**, so a bad environment costs nothing at all: the
# running desk is never stopped and there is nothing to restore. Placing this
# after the rename - as the first version did - meant a failed preflight still
# stopped the desk and relied on the rollback to put it back.
#
# `--network none` and no venue: it opens no socket and places no order.
# Skipped only by `SKIP_PREFLIGHT=1`, for the case where the image predates the
# flag and would exit 2 on an unknown argument.
if [[ "${SKIP_PREFLIGHT:-0}" != "1" ]]; then
  echo "preflight: building the node from $(basename /home/ubuntu/till.env)"
  if ! docker run --rm \
      --network none \
      --memory 512m \
      -e TZ=UTC \
      --env-file /home/ubuntu/till.env \
      -e TRADING_LIVE=0 \
      "$IMAGE:$TAG" --check 2>&1 | tail -20; then
    echo "preflight failed - the running desk is untouched" >&2
    exit 1
  fi
fi

# **Renamed, not removed** - the old container is the rollback.
#
# See docs/deployment.md.
# case `docker run` below fails on a name conflict and this script exits
# reporting success over somebody else's container. Both were reached in
# practice on 2026-09-15.
# See docs/deployment.md.
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
# left the host enough to breathe. Hard-coding it wastes a bigger machine and
# over-commits a smaller one, unnoticed until the kills start.
TOTAL_MB="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
LIMIT_MB="$(( TOTAL_MB * 70 / 100 ))"
[[ "$LIMIT_MB" -lt 512 ]] && LIMIT_MB=512
echo "host has ${TOTAL_MB}MB, giving the container ${LIMIT_MB}MB"

# **And the same argument for CPU, which was hard-coded at 1.5 while the
# memory beside it scaled.** The share is 90% rather than the memory's 70%
# because the two run out differently: over-committing memory gets the
# container OOM-killed, while over-committing CPU only makes the host's own
# work wait, and this box runs nothing else that matters.
#
# 90% is a measured number, not a round one. On 2026-11-06 the fifteen-minute
# fold across 46 desks peaked at **1.429 cores** - 95% of the 1.5 the
# container was given - and the cgroup reported `nr_throttled 55`,
# `throttled_usec 2095683`: 2.1 seconds of CPU denied in fourteen minutes.
# Every feed folds on the same boundary, so the burst is five seconds long and
# scales with the instrument count. 1.8 of two cores clears that peak by 26%;
# 1.5 did not clear it at all.
CORES="$(nproc)"
CPU_LIMIT="$(awk -v c="$CORES" 'BEGIN{v=(c*90)/100; if (v<0.5) v=0.5; printf "%.2f", v}')"
echo "host has ${CORES} core(s), giving the container ${CPU_LIMIT}"

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --memory "${LIMIT_MB}m" \
  --memory-swap "${LIMIT_MB}m" \
  --cpus "$CPU_LIMIT" \
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
  `# No command: the image's ENTRYPOINT is the node module. This passed
   # "run", a subcommand of a console script that this project does not
   # declare - so the container exited immediately, every time, and the
   # rollback below was what kept the box alive.` \
  "$IMAGE:$TAG" || {
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
# See docs/deployment.md.
# is happening says nothing. `tr -d` because a stray newline in the captured
# value made the failure message unreadable and the comparison meaningless.
# **`State.Running` is `true` while a container is in restart backoff**, so it
# cannot distinguish a healthy desk from a crash-looper. This is not a theory:
# on 2026-11-03 a deploy met an environment naming sixteen retired rules, the
# node raised on every start, and this script printed `up on b86ab4c (state
# true/0)` and exited 0 over a container that went on to restart **27 times**.
# The previous comment here reasoned that "a crash-looper is caught because it
# is not running when sampled twice" - and `docker inspect` returns
# `{"Status":"restarting","Running":true,"Restarting":true,"ExitCode":1}`, so
# it never was.
#
# So `Status` and `Restarting` are read as well, and the restart count is
# compared **between** the two samples: a count that climbs while the script
# watches is a loop whatever any single field says.
alive() {
  docker inspect -f '{{.State.Status}}/{{.State.Restarting}}/{{.RestartCount}}' \
    "$NAME" 2>/dev/null | tr -d '[:space:]'
}

settled() {
  local state="$1"
  local status="${state%%/*}"
  local rest="${state#*/}"
  local restarting="${rest%%/*}"
  [[ "$status" == "running" && "$restarting" == "false" ]]
}

sleep 45
STATE="$(alive)"
if ! settled "${STATE:-unknown/true/0}"; then
  sleep 30
  STATE="$(alive)"
fi
FIRST_RESTARTS="${STATE##*/}"
sleep 20
LATER="$(alive)"
LATER_RESTARTS="${LATER##*/}"

BAD=""
if ! settled "${LATER:-unknown/true/0}"; then
  BAD="not settled (state $LATER)"
elif [[ "${LATER_RESTARTS:-0}" -gt "${FIRST_RESTARTS:-0}" ]]; then
  # Up at both samples and yet the count moved: it died and came back between
  # them, which is the loop this check exists to catch.
  BAD="restarting while watched (${FIRST_RESTARTS} -> ${LATER_RESTARTS})"
fi

if [[ -n "$BAD" ]]; then
  echo "new container is $BAD" >&2
  docker logs --tail 30 "$NAME" 2>&1 | tail -30 >&2 || true
  if restore_previous; then
    exit 1
  fi
  echo "left the new container in place - no previous version to restore" >&2
  exit 2
fi
echo "up on ${TAG:0:7} (state $LATER)"
docker rm -f "$PREV" >/dev/null 2>&1 || true

# The old image is only unreferenced once the new container is up, so a second
# sweep here collects it. The one above is what guarantees room to pull; this
# one is what stops the box sitting at two images between deploys.
docker image prune -af >/dev/null 2>&1 || true

docker ps --filter "name=$NAME" --format '{{.Names}}  {{.Status}}  {{.Image}}'
