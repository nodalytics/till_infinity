# Till Infinity - collectors, online models and agents in one image.
# Multi-stage: build tooling stays in the builder, never ships.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Lockfile first: keyed on the lock, not the source, so a code edit does not
# reinstall river.
#
# **This is no longer a uv workspace, and the image spent the interval unable
# to build.** It used to copy `packages/till-platform/`,
# `packages/till-channels/` and `shared/`, and name
# `shared/contracts/bus` in an env var. `packages/` retired to
# `research/retire/` - `pyproject.toml` says so - and `shared/` went with it,
# so `docker build` failed at the second COPY with "packages/till-platform:
# not found" and had done since the retirement.
#
# **Nothing caught it, and the file that exists to catch it still cannot.**
# `tests/test_entrypoints.py` asserts the ENTRYPOINT string, the HEALTHCHECK
# and the compose file, because those are readable; it never builds, and a
# build is the only thing that reads a COPY. The nearest cheap substitute is
# `test_every_copy_source_exists`, which resolves each COPY's source against
# the repository - a static check that would have failed here on the first run
# after the retirement.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --all-extras

COPY till_infinity/ ./till_infinity/
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

# **The contracts check went with `till-platform`.** It used to run
# `from till_platform import contracts` against the installed package, from `/`
# so that WORKDIR could not answer by accident - a good check, and its subject
# retired to `research/retire/`. The import raised `ModuleNotFoundError`, so
# this was the *second* reason the image could not build; the first was copying
# `packages/` and `shared/`, which no longer exist either.
#
# The lesson is worth keeping even though the step is not: the files were
# present and unfindable for the whole of the previous image's life, because
# `contracts` counted parent directories from its own `__file__` and that moves
# when a package is installed. `declared()` answered `()` and nothing asked
# again, so a container reported that the bus declares nothing. If a
# root-relative data directory is ever shipped again, the check to write is
# this one: ask the *installed* package whether it found the files, from a
# working directory that cannot supply the answer itself.


FROM python:3.13-slim-bookworm AS runtime

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
# point and the health probe are `python -m` against the *installed* package,
# which is the one in the venv. With one copy in the image, a check cannot read
# the wrong thing.
#
# This said "console scripts from the venv" until 2026-11-01. There are none,
# deliberately: `pyproject.toml` declares no `[project.scripts]` and
# `tests/test_entrypoints.py` holds it that way. An image whose own comment
# named the retired CLI is how the ENTRYPOINT came to name it too.

# Databases and model state. Mount a volume or online models start cold.
RUN mkdir -p /app/.data && chown till:till /app/.data
VOLUME ["/app/.data"]

USER till

# **The module, not a console script.** `ENTRYPOINT ["till-infinity"]` named a
# console script this project deliberately does not declare - the 2,852-line
# CLI retired with the services it drove, and `pyproject.toml` records the
# reason: a second way to run the desk is a second thing to go stale. So the
# image could not start at all, and neither could any service in
# `docker-compose.yml`, every one of which ran a retired subcommand.
#
# `python -m till_infinity.node.live` is the entry point the retirement note
# names, and it is now the only one.

# The probe reads the status the node writes on its own clock, so a kernel that
# has stopped dispatching fails it - see `node/status.py`. `--version` did not,
# and reported healthy for three hours with no trading service; a probe
# answering from inside the process only proves a process is alive, which
# Docker already knew.
#
# It fails a node that is up and running **no strategies**, which is the shape
# three deploys on 2026-10-09 produced. It does *not* fail an unarmed one:
# `TRADING_LIVE` unset is a deliberate state, and failing on it would make a
# dry run impossible.
#
# The start period covers the warm-up - `desk-handlers-arm-after-backfill`
# records that `armed=0` straight after a deploy is normal.
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
    CMD python -m till_infinity.node.probe || exit 1

ENTRYPOINT ["python", "-m", "till_infinity.node.live"]
