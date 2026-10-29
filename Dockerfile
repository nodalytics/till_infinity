# Till Infinity - collectors, online models and agents in one image.
# Multi-stage: build tooling stays in the builder, never ships.

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Lockfile first: keyed on the lock, not the source, so a code edit does not
# reinstall river.
# **The members' manifests come with the lockfile, not with the source.** This
# is a uv workspace: `uv sync --frozen` resolves every member, so it needs each
# `pyproject.toml` present at this step even though `--no-install-project`
# means none of their code is installed yet. Copying only the root manifest
# fails here with "workspace member is missing a pyproject.toml", which at
# least fails loudly.
COPY pyproject.toml uv.lock ./
COPY packages/till-platform/pyproject.toml ./packages/till-platform/
COPY packages/till-channels/pyproject.toml ./packages/till-channels/
COPY services/statespace/pyproject.toml ./services/statespace/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --all-extras

COPY till_infinity/ ./till_infinity/
# The workspace members' code. `services/ticks` is Go and is not in this image:
# it runs beside the terminal, not beside the desk.
COPY packages/till-platform/ ./packages/till-platform/
COPY packages/till-channels/ ./packages/till-channels/
COPY services/statespace/ ./services/statespace/
# **The contracts, which are not inside the package.** `shared/contracts/` is
# JSON and Markdown at the repository root because a Go service reads the same
# files - see `docs/adr/0002-services-are-self-contained.md`. Left out of the
# image, `shared.contracts.HOME` does not exist and `declared()` returns an
# empty tuple rather than raising, so a caller asking what the bus carries is
# told "nothing" by a container that simply does not ship the answer.
COPY shared/ ./shared/
COPY README.md ./
# **`--reinstall-package`, and the check below is not belt-and-braces.**
# `uv sync --no-editable` builds the project into a wheel and caches it, and the
# cache key does not include the source: the version in pyproject.toml never
# changes, so uv happily reinstalled a wheel built from an older tree. The image
# then carried the new source at /app/till_infinity and an old installed package
# in the venv - and the venv is what Python imports.
#
# It shipped for at least three deploys on 2026-10-09 and nobody could see it:
# every verification read /app/till_infinity, because `python -c` from WORKDIR
# /app imports the source copy, not the installed one. #130, #136 and #141 were
# all built, tagged, deployed, health-checked and reported up while none of them
# were running. One of them - #136 - was then measured as having no effect,
# which is exactly what code that is not running looks like.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --all-extras --reinstall-package till-infinity

# The build fails rather than the desk running yesterday's code. Compares every
# .py in the installed package against the source it was built from, so a cache
# that serves a stale wheel cannot leave this stage.
#
# POSIX sh on purpose - `RUN` is not bash, so no process substitution - and
# `cat | md5sum` rather than per-file sums so the comparison is one digest and
# needs no `diff`, which slim images do not all carry.
RUN set -eu; \
    V="$(ls -d /app/.venv/lib/python*/site-packages/till_infinity)"; \
    a="$(cd "$V" && find . -name '*.py' | sort | xargs cat | md5sum | cut -d' ' -f1)"; \
    b="$(cd /app/till_infinity && find . -name '*.py' | sort | xargs cat | md5sum | cut -d' ' -f1)"; \
    na="$(cd "$V" && find . -name '*.py' | wc -l)"; \
    nb="$(cd /app/till_infinity && find . -name '*.py' | wc -l)"; \
    if [ "$a" != "$b" ]; then \
        echo "FATAL: the installed package is not the source it was built from."; \
        echo "  installed: $na files, digest $a"; \
        echo "  source   : $nb files, digest $b"; \
        echo "uv served a cached wheel - see the comment above this check."; \
        exit 1; \
    fi; \
    echo "installed package matches source: $nb files, digest $a"


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
# **The source tree is deliberately not shipped.** Having both meant two copies
# of the package in the image with only one of them imported - and `python -c`
# from WORKDIR /app resolves the *source*, so every content check that mattered
# read the copy that was not running. Nothing at runtime needs it: the entry
# point and the health probe are console scripts from the venv, and the packaged
# model files resolve relative to `frozen.__file__`, which is the installed one.
# With one copy in the image, a check cannot read the wrong thing.

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
