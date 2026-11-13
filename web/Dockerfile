# The dashboard: Next in front, the read-only Python API behind.
#
# **A separate image from the desk's, deployed by a separate workflow, into a
# separate container.** The trading image does not contain this and the live
# node never imports it, so a stylesheet must never be a reason to restart the
# thing holding positions - `deploy.yml` already excludes `web/**` for that
# reason and this is the other half of it.
#
# One image rather than two because the two halves are useless apart and the
# trading host has two cores: a second container is a second set of overheads
# on a box that has none to spare.

# --- the frontend, built where the toolchain can stay ------------------------

FROM node:22-bookworm-slim AS web

# **The repository's shape is preserved, not flattened.** `next.config.ts`
# sets `outputFileTracingRoot` to its own parent, so building with the app at
# `/build` would make the trace root `/` and sweep the filesystem. With the app
# at `/build/web` the root is `/build`, which is what it means upstream.
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# `output: "standalone"` emits a server plus only the modules it imports, which
# is what keeps the runtime layer small enough to be worth running beside a
# trading desk.
RUN npm run build

# --- the runtime -------------------------------------------------------------

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    NODE_ENV=production \
    PYTHONUNBUFFERED=1

# Node, because the trading host has none and the standalone server needs a
# runtime. `--no-install-recommends` keeps this to the interpreter.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra dashboard

COPY till_infinity/ ./till_infinity/
COPY web/api/ ./web/api/

# **Into `/app`, not `/app/web`.** `outputFileTracingRoot` is the repository
# root, so the standalone build preserves the app's path inside it and emits
# `standalone/web/server.js` beside a top-level `standalone/node_modules`.
# Copying it into `web/` would nest that a second time and put the server at
# `/app/web/web/server.js`, which is a build that completes and a container
# that cannot start.
COPY --from=web /build/web/.next/standalone ./
# The standalone server serves these from `<app>/.next/static`; they are the
# one thing the trace deliberately leaves behind.
COPY --from=web /build/web/.next/static ./web/.next/static

COPY web/entrypoint.sh /usr/local/bin/dashboard
RUN chmod +x /usr/local/bin/dashboard

# **Not root.** This mounts a live account's journal, read-only, and there is
# no reason for the process reading it to be able to write anything at all.
RUN useradd --system --uid 10001 --home /app desk && chown -R desk:desk /app
USER desk

# Both halves bind loopback **inside the container's own namespace**; the host
# publishes only what the deploy chooses to publish. See `scripts/deploy-web.sh`.
ENV TILL_API_URL=http://127.0.0.1:8787 \
    HOSTNAME=127.0.0.1 \
    PORT=3000

EXPOSE 3000

HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

ENTRYPOINT ["dashboard"]
