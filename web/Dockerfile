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

# **The user exists before anything is written, not after.**
#
# This was a recursive ownership change over /app at the end, and that one
# layer was **1.39GB**: rewriting every file's owner writes every file into
# a new layer, so the whole virtualenv was stored twice. Owning an empty
# directory first and copying with `--chown` costs nothing.
RUN useradd --system --uid 10001 --home /app desk
WORKDIR /app
RUN chown desk:desk /app
USER desk

# **Dependencies first, project second.** `uv sync` installs the root project
# too, and the project's source arrives on the next line - so a single sync
# here fails with "Expected a Python module at: till_infinity/__init__.py".
# `--no-install-project` resolves and installs the dependencies against the
# lock, which is also the layer worth caching: it changes when the lock does,
# not when a strategy does.
# **`README.md` too.** `pyproject.toml` declares it as the project's readme, so
# building the project reads it and fails with "failed to open file
# /app/README.md" without it - at the *second* sync, after the first has
# already succeeded, which is a confusing place to land.
COPY --chown=desk:desk pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra dashboard --no-install-project

COPY --chown=desk:desk till_infinity/ ./till_infinity/
COPY --chown=desk:desk web/api/ ./web/api/

# Now the project itself, against the same lock.
RUN uv sync --frozen --no-dev --extra dashboard

# **Into `/app`, not `/app/web`.** `outputFileTracingRoot` is the repository
# root, so the standalone build preserves the app's path inside it and emits
# `standalone/web/server.js` beside a top-level `standalone/node_modules`.
# Copying it into `web/` would nest that a second time and put the server at
# `/app/web/web/server.js`, which is a build that completes and a container
# that cannot start.
COPY --from=web --chown=desk:desk /build/web/.next/standalone ./
# The standalone server serves these from `<app>/.next/static`; they are the
# one thing the trace deliberately leaves behind.
COPY --from=web --chown=desk:desk /build/web/.next/static ./web/.next/static
# **And `public/`, which the trace also leaves behind.** Referencing an asset
# is not enough: the mark is loaded from a `url()` in `globals.css` and the
# icons are named in `layout.tsx`'s metadata, and `.next/standalone` still
# contains no `public/` - checked on this build rather than assumed. Measured
# both ways against the standalone server: with this directory in place
# `/till-infinity-logo-dark.svg` is a 200, and with it moved aside the same
# request is a **500**. `next dev` serves it either way, which is why this is
# the shape of bug that ships.
COPY --from=web --chown=desk:desk /build/web/public ./web/public

USER root
COPY --chmod=755 web/entrypoint.sh /usr/local/bin/dashboard
USER desk

# Not root - set above, before the first write. This mounts a live account's
# journal read-only, and the process reading it has no reason to be able to
# write anything at all.

# **Next binds `0.0.0.0`; the isolation is the host publish, not this.**
#
# It was `127.0.0.1`, which is loopback *of the container's own namespace* -
# so Docker's published port, which routes to the container's network
# interface, reached nothing. The container started, Next logged "Ready", and
# every request got a connection refused. A bind that looks careful and serves
# nobody is worse than an obvious one.
#
# What actually bounds exposure is `-p 127.0.0.1:3000:3000` in
# `scripts/deploy-web.sh`: the port is published to the host's loopback only.
# That script also passes the host-side address as `TILL_WEB_BIND`, which is
# what `web/lib/gate.ts` reads to decide whether a caller secret is required -
# the container's own bind is not the fact that matters there.
#
# The API keeps `127.0.0.1` and should: the only thing that talks to it is Next,
# in this same namespace.
# `TILL_WEB_BIND` is **deliberately non-loopback here**, so an image run
# without `deploy-web.sh` demands a caller secret rather than serving a live
# account to whoever reaches it. The deploy passes the real host-side publish
# address, which can only narrow this.
ENV TILL_API_URL=http://127.0.0.1:8787 \
    HOSTNAME=0.0.0.0 \
    TILL_WEB_BIND=0.0.0.0 \
    PORT=3000

EXPOSE 3000

# **Through the proxy, so it exercises both halves.** Probing the page alone
# reported healthy while the API was still starting - uvicorn imports 92
# `till_infinity` modules including nautilus and is much slower than Next, so
# there is a real window where the page renders and every panel is empty.
# `deploy-web.sh` waits on this and would have called that a successful deploy.
#
# `/api/health` goes Next -> proxy -> uvicorn, so a pass means the whole chain
# answers. The start period is generous for the same reason.
HEALTHCHECK --interval=60s --timeout=15s --start-period=120s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

ENTRYPOINT ["dashboard"]
