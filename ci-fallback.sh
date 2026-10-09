#!/usr/bin/env bash
# Build and push the image GitHub Actions did not, so the instance can pull it.
#
# **The trigger is the absence of an image, not the presence of a billing
# error.** Parsing "recent account payments have failed" would catch one cause
# and miss runner shortages, Actions outages, a cancelled run and a workflow
# edited wrong. Asking "is there an image for this commit yet?" catches all of
# them - and it is the same question that makes this safe to leave running once
# billing is fixed: when Actions builds again the image exists, and this exits
# having done nothing. No flag to unset, no second system to remember.
#
#   ~/.ghtoken   mode 600, a token with `repo` read. Nothing runs without it.
#
# ghcr push credentials are already in ~/.docker/config.json.
set -euo pipefail

REPO="nodalytics/till_infinity"
IMAGE="ghcr.io/${REPO}"
# **Minutes to leave Actions alone before stepping in.** A commit CI is
# mid-build on must not be built twice: this box takes about as long as a
# runner does, so without a wait both start, both push, and the slower one wins
# a race nobody asked for.
GRACE_MINUTES=12
LOG="$HOME/ci-fallback.log"
WORK="$HOME/.ci-fallback"

say() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >>"$LOG"; }

[ -r "$HOME/.ghtoken" ] || { say "no ~/.ghtoken - nothing to do"; exit 0; }
TOKEN="$(cat "$HOME/.ghtoken")"

api() {
  curl -fsSL -H "Authorization: Bearer $TOKEN" \
       -H "Accept: application/vnd.github+json" "$@"
}

head_json="$(api "https://api.github.com/repos/${REPO}/commits/main")" || {
  say "could not reach the GitHub API"
  exit 0
}
SHA="$(printf '%s' "$head_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')"
WHEN="$(printf '%s' "$head_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"]["committer"]["date"])')"

# **Already built is already done.** The duplicate-work guard and the dormancy
# switch in one line: Actions tags by commit sha, so if the tag resolves, CI
# got there first and there is nothing to do.
if docker manifest inspect "${IMAGE}:${SHA}" >/dev/null 2>&1; then
  say "${SHA:0:7} already in the registry - nothing to build"
  exit 0
fi

age=$(( ( $(date -u +%s) - $(date -u -d "$WHEN" +%s) ) / 60 ))
if [ "$age" -lt "$GRACE_MINUTES" ]; then
  say "${SHA:0:7} is ${age}m old - leaving it to Actions for another $(( GRACE_MINUTES - age ))m"
  exit 0
fi

# **The same paths-ignore the workflow uses.** A push that cannot alter the
# image must not restart the service: four deploys in one afternoon each cost a
# backfill, one of them for a docs-only commit, and levels were down four hours
# across them. Four docs-only merges landed on 2026-10-09 alone.
files="$(api "https://api.github.com/repos/${REPO}/commits/${SHA}" |
  python3 -c 'import json,sys; print("\n".join(f["filename"] for f in json.load(sys.stdin).get("files",[])))')"
if [ -n "$files" ] && ! printf '%s\n' "$files" | grep -qvE '^(docs/|research/|LICENSE$)|\.md$'; then
  say "${SHA:0:7} touches only docs/research/markdown - no image needed"
  exit 0
fi

# **Both architectures, every time.** The instance is aarch64. An amd64-only
# image fails at `docker pull` on Graviton, and it fails *after* the old
# container has been stopped for the cutover, which is the worst moment to find
# out. The emulator is re-installed on every run because binfmt registrations
# do not survive a reboot, and the call is idempotent and cheap.
docker run --privileged --rm tonistiigi/binfmt:latest --install arm64 >/dev/null 2>&1 || true

rm -rf "$WORK"
mkdir -p "$WORK"
say "building ${SHA:0:7} (Actions has not, after ${age}m)"
api -o "$WORK/src.tar.gz" -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/${REPO}/tarball/${SHA}" || {
  say "tarball fetch failed"
  exit 1
}
tar -xzf "$WORK/src.tar.gz" -C "$WORK"
SRC="$(find "$WORK" -maxdepth 1 -type d -name '*till_infinity*' | head -1)"
[ -d "$SRC" ] || { say "tarball did not unpack as expected"; exit 1; }

if docker buildx build --platform linux/amd64,linux/arm64 \
  -t "${IMAGE}:${SHA}" -t "${IMAGE}:latest" --push "$SRC" >>"$LOG" 2>&1; then
  say "pushed ${IMAGE}:${SHA:0:7} and :latest for both architectures"
else
  say "BUILD FAILED for ${SHA:0:7} - see the lines above"
  exit 1
fi
rm -rf "$WORK"
