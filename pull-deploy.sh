#!/usr/bin/env bash
# Deploy whatever is newest in the registry, whoever built it.
#
# **Digest in, digest out.** This compares what `:latest` resolves to against
# what the container is recorded as running, so it does not care whether
# Actions or the lab fallback produced the image - and it cannot deploy the
# same thing twice, which is what keeps it quiet once billing is fixed and both
# are producing images again.
#
# Deliberately no GitHub access: this box needs no token and no network path to
# anything but the registry it already pulls from.
set -euo pipefail

IMAGE="ghcr.io/nodalytics/till_infinity"
LOG="$HOME/pull-deploy.log"
MARK="$HOME/.deployed-manifest"

say() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >>"$LOG"; }

want="$(docker manifest inspect "${IMAGE}:latest" 2>/dev/null | sha256sum | cut -c1-16)" || {
  say "registry unreachable"
  exit 0
}
[ -n "$want" ] || { say "no :latest in the registry"; exit 0; }

# A file rather than a container label, because the label would be lost the
# moment the container is recreated - which is exactly what a deploy does.
running="$(cat "$MARK" 2>/dev/null || true)"
[ "$want" = "$running" ] && exit 0

# **Never while the engine is mid-warm.** A restart during the replay throws
# the work away and starts another one: on 2026-10-09 a deploy ten minutes
# after the desk came up cost a second 84-minute warm, and the one after that
# was OOM-killed at the 60-minute mark, so three hours produced no levels at
# all. If structures has not journalled recently it is either warming or
# stalled, and neither is a moment to restart into.
quiet="$(python3 - <<'PY'
import sqlite3, time

try:
    c = sqlite3.connect("file:/home/ubuntu/till-data/journal/journal.db?mode=ro", uri=True)
    r = c.execute("select max(time) from entries where actor=?", ("structures",)).fetchone()[0]
    print(int((time.time() - r) / 60) if r else 999)
except Exception:
    print(999)
PY
)"
if [ "${quiet:-999}" -gt 5 ]; then
  say "structures silent ${quiet}m - warming or stalled, not restarting into that"
  exit 0
fi

say "registry has something new (${want}) - deploying"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -af >/dev/null 2>&1 || true
if IMAGE="$IMAGE" TAG="latest" bash "$HOME/deploy.sh" >>"$LOG" 2>&1; then
  printf '%s\n' "$want" >"$MARK"
  say "deployed ${want}"
else
  say "DEPLOY FAILED - see the lines above"
  exit 1
fi
