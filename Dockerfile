# Till Infinity - collectors, online models and agents in one image.
# Multi-stage: build tooling stays in the builder, never ships.

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Lockfile first: keyed on the lock, not the source, so a code edit does not
# reinstall river.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --all-extras

COPY till_infinity/ ./till_infinity/
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --all-extras


FROM python:3.11-slim-bookworm AS runtime

# Not root: this reaches the network and parses what comes back.
RUN useradd --create-home --uid 1000 till

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # UTC on purpose - the host's zone would desync stored timestamps.
    TZ=UTC

WORKDIR /app
COPY --from=build --chown=till:till /app/.venv /app/.venv
COPY --from=build --chown=till:till /app/till_infinity /app/till_infinity

# Databases and model state. Mount a volume or online models start cold.
RUN mkdir -p /app/.data && chown till:till /app/.data
VOLUME ["/app/.data"]

USER till

# `health` reads the status the running stack writes, so a dead service fails
# the probe. `--version` did not, and reported healthy for three hours with no
# trading service - see deployment.md. The start period covers the warm-up.
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
    CMD till-infinity health || exit 1

ENTRYPOINT ["till-infinity"]
CMD ["run"]
