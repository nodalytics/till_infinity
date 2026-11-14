#!/usr/bin/env bash
# One command for both halves of the dashboard, locally.
#
# **Two processes that are useless apart should not need an operator to
# remember both.** The page is a shell; every figure on it is a browser read
# through the Next proxy to the Python service. Start only `next dev` and the
# app loads, renders its chrome and answers every panel with a 502 - which is
# exactly the report this script exists to stop: "the desk API is not
# answering", from somebody who ran the documented command and got a broken
# page for it.
#
# Modelled on `entrypoint.sh`, which does the same job inside the image, for
# the same reason and with the same two lines of mechanism: `wait -n` returns
# on whichever half exits first, and the trap takes the other down with it. No
# supervisor. A half-dead dashboard is worse than a stopped one, because the
# half that is still up looks healthy.
#
# `npm run dev` runs this. `npm run dev:api` and `npm run dev:web` are still
# there for the times you want one half under a debugger, a profiler or a
# different port.
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# The repository root. `uv run` has to be invoked from here and not from
# `web/`: the project, its lock and its `.venv` are all at the root, and `web/`
# is a folder rather than a distribution.
root="$(cd -- "$here/.." && pwd)"

api_port="${TILL_API_PORT:-8787}"
web_port="${TILL_WEB_PORT:-3000}"

# **Loopback, and said twice on purpose.** `--host`/`-H` is where the socket
# binds; `TILL_WEB_BIND` is what `lib/gate.ts` reads to decide whether a caller
# secret is required, and an *unset* `TILL_WEB_BIND` deliberately counts as
# exposed. Both come from one variable here so they cannot drift apart.
bind="127.0.0.1"
export TILL_WEB_BIND="$bind"
# The proxy's forward address, derived from the port above rather than
# defaulted separately, so `TILL_API_PORT=9000 npm run dev` still talks to the
# API it just started.
export TILL_API_URL="http://${bind}:${api_port}"

# **Which journal, stated once, in a line nobody can miss.**
#
# `web/api/data.py` resolves a relative `TILL_JOURNAL_DB` against the
# repository root, so the repo's own `.data/journal/journal.db` is a working
# default for a local dashboard - and it is also, usually, months old. A
# dashboard rendering a stale file looks exactly like a dashboard rendering the
# desk, so the file and its age are printed rather than assumed.
journal_default=".data/journal/journal.db"
journal_source="TILL_JOURNAL_DB"
if [[ -z "${TILL_JOURNAL_DB:-}" ]]; then
  export TILL_JOURNAL_DB="$journal_default"
  journal_source="this repository's own file, no TILL_JOURNAL_DB set"
fi

journal_note() {
  local path="$TILL_JOURNAL_DB"
  local full="$path"
  [[ "$path" == /* ]] || full="$root/$path"
  if [[ -f "$full" ]]; then
    local written
    written="$(date -r "$full" '+%Y-%m-%d %H:%M' 2>/dev/null \
      || stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$full" 2>/dev/null \
      || echo 'unknown')"
    printf 'journal   %s - %s, last written %s\n' "$path" "$journal_source" "$written"
  else
    printf 'journal   %s - %s, and there is no such file: the panels will say so\n' \
      "$path" "$journal_source"
  fi
}

cleanup() {
  trap - EXIT INT TERM
  kill -TERM "${API_PID:-0}" "${WEB_PID:-0}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# `next` needs its dependencies, and a first run of this script in a fresh
# checkout has none. Installing is a nicer answer than a stack trace about a
# missing binary, and it is a no-op afterwards.
if [[ ! -x "$here/node_modules/.bin/next" ]]; then
  printf 'installing the app dependencies, once\n'
  (cd -- "$here" && npm install --no-audit --no-fund)
fi

printf 'api       http://%s:%s\n' "$bind" "$api_port"
printf 'app       http://%s:%s\n' "$bind" "$web_port"
journal_note
printf 'both halves die together; ^C stops them\n'

# From the root, as the service's own docstring says. `uv run` syncs the
# `dashboard` extra if the environment does not have it yet.
(cd -- "$root" && exec uv run --extra dashboard uvicorn web.api.main:app \
  --host "$bind" --port "$api_port" --log-level warning) &
API_PID=$!

# **The binary, not `npm run dev:web`.** An `npm` wrapper between the trap and
# `next` is one more process that has to forward a signal correctly for the two
# halves to die together, and a dev server that survives its parent keeps port
# 3000 and is invisible in the terminal that started it.
(cd -- "$here" && exec ./node_modules/.bin/next dev -H "$bind" --port "$web_port") &
WEB_PID=$!

wait -n
