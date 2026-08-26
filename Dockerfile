# Till Infinity - collectors, online models and agents in one image.
#
# Multi-stage so the runtime carries the virtualenv and the source, not the
# build tooling: uv, caches and compilers stay in the builder and never reach
# the layer that gets shipped.

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, from the lockfile alone. This layer is keyed on the lock
# rather than the source, so editing a module does not reinstall river, and a
# rebuild after a code change takes seconds instead of minutes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --all-extras

COPY till_infinity/ ./till_infinity/
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --all-extras


FROM python:3.11-slim-bookworm AS runtime

# Not root. The process reaches the network and parses what comes back, which
# is exactly the shape of thing that should not be running as root when it
# eventually meets something malformed.
RUN useradd --create-home --uid 1000 till

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Everything is UTC on purpose; a container inheriting the host's zone
    # would make stored timestamps disagree with every other deployment.
    TZ=UTC

WORKDIR /app
COPY --from=build --chown=till:till /app/.venv /app/.venv
COPY --from=build --chown=till:till /app/till_infinity /app/till_infinity

# Databases and model state live here. Mount a volume over it or the work is
# lost when the container goes, which for online models means starting cold.
RUN mkdir -p /app/.data && chown till:till /app/.data
VOLUME ["/app/.data"]

USER till

# Liveness rather than readiness: the CLI answering proves the package
# imported and the entry point resolves, which is what a restart would fix.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD till-infinity --version || exit 1

ENTRYPOINT ["till-infinity"]
CMD ["run"]
