#!/usr/bin/env bash
# Start the API, then the Next server, and die together.
#
# **No supervisor, deliberately.** Two processes that are useless apart do not
# need a process manager arbitrating between them; they need to fail as one so
# the healthcheck sees it. `wait -n` returns on whichever exits first and the
# trap takes the other down with it, so a half-dead container becomes a
# restarting container rather than a page that loads and answers nothing.
set -euo pipefail

cleanup() { kill -TERM "${API_PID:-0}" "${WEB_PID:-0}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

/app/.venv/bin/uvicorn web.api.main:app \
  --host 127.0.0.1 --port "${TILL_API_PORT:-8787}" \
  --log-level warning &
API_PID=$!

# The standalone build puts its own server here; `HOSTNAME` and `PORT` from the
# image decide where it listens.
node /app/web/server.js &
WEB_PID=$!

wait -n
