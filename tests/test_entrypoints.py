"""That the things which start this desk refer to things that exist.

Until 2026-11-01 none of them did. `Dockerfile` ended
`ENTRYPOINT ["till-infinity"]` with `CMD ["run"]` and a `HEALTHCHECK` of
`till-infinity health`; `docker-compose.yml` started six services on
`prices collect`, `news collect`, `statespace watch`, `journal listen`,
`notify listen` and `trading run`; and `deploy.sh` passed `run` to the same
missing script. **`pyproject.toml` declares no console script**, on purpose -
the 2,852-line CLI retired with the services it drove, because a second way to
run the desk is a second thing to go stale.

So the image could not start, every container in the compose file failed
immediately, and the deploy script's rollback was the only thing keeping the
box alive. The test suite was green throughout: 2,139 tests that import the
package and never ask what runs it.

These are cheap, static checks. They do not prove the node *works* - only one
real run does that - but they would have caught every one of the above, which
is more than the rest of the suite managed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Commands of the retired CLI. Any of these in a file that starts something
#: is that file naming a program which does not exist.
RETIRED = (
    "till-infinity run",
    "till-infinity health",
    "prices collect",
    "news collect",
    "statespace watch",
    "journal listen",
    "notify listen",
    "trading run",
)

#: Files whose job is to start or check the desk.
STARTERS = ("Dockerfile", "docker-compose.yml", "scripts/deploy.sh")


def read(name: str) -> str:
    return (ROOT / name).read_text()


def executable(text: str) -> str:
    """The file with its comment lines removed.

    The compose file and the deploy script both *describe* the retired
    commands in prose, which is the record of why they changed and has to stay
    readable. What must not survive is a line that runs one.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # A trailing comment inside a shell line continuation, as `deploy.sh`
        # uses for its `docker run` flags.
        kept.append(re.sub(r"`#.*", "", line))
    return "\n".join(kept)


@pytest.mark.parametrize("name", STARTERS)
@pytest.mark.parametrize("command", RETIRED)
def test_nothing_that_starts_the_desk_runs_a_retired_command(name, command):
    """The literal regression, one cell per file and command."""
    assert command not in executable(read(name)), (
        f"{name} runs `{command}`, which no longer exists - "
        f"`pyproject.toml` declares no console script"
    )


def test_there_is_still_no_console_script():
    """Checked so the fix cannot be "declare one again".

    `pyproject.toml` records the decision and the reason, and
    `till.env needs a container recreate` is the lesson it cites: two ways to
    change one thing means one of them goes silently stale. The node module is
    the entry point.
    """
    assert "[project.scripts]" not in read("pyproject.toml")
    assert "console_scripts" not in read("pyproject.toml")


def test_the_image_entry_point_is_the_node_module():
    """And is importable, which is the half a string match would miss."""
    assert 'ENTRYPOINT ["python", "-m", "till_infinity.node.live"]' in read("Dockerfile")

    from till_infinity.node import live

    assert callable(live.main)


def test_the_image_has_no_leftover_cmd():
    """`CMD ["run"]` would be passed to the module as a stray argument. It is
    harmless today, which is exactly why it would survive unnoticed."""
    assert not re.search(r"^CMD\b", read("Dockerfile"), re.M)


def test_the_health_probe_is_a_module_that_answers():
    """The probe is the one thing in this file that can be run here."""
    assert "python -m till_infinity.node.status" in read("Dockerfile")

    from till_infinity.node import status

    ok, reason = status.healthy("/nonexistent/status.json")
    assert ok is False
    # The reason, not just the verdict: `docker inspect` keeps a probe's
    # output, and "unhealthy" sends somebody to the logs where "has not
    # written one" tells them the node never started.
    assert "has not written one" in reason


def test_the_deploy_script_passes_no_command():
    """It passed `run`. With no console script that was the container's whole
    lifetime - it exited immediately, every time, and the rollback was what
    kept the box up."""
    text = executable(read("scripts/deploy.sh"))
    assert '"$IMAGE:$TAG" run' not in text
    assert '"$IMAGE:$TAG" ||' in text


def test_compose_describes_one_node():
    """The port collapsed six services into one kernel - one cache and one
    portfolio, which is what makes exposure answerable across venues. Six
    processes would put each one's positions out of the others' sight."""
    yaml = pytest.importorskip("yaml")
    found = yaml.safe_load(read("docker-compose.yml"))
    assert list(found["services"]) == ["node"]
    assert "redis" not in found["services"], "nothing under till_infinity imports redis"


def test_compose_mounts_the_data_volume():
    """The journal, the status file and any model state live there. Unmounted,
    the record starts empty on every deploy and the probe has nowhere to read
    from."""
    yaml = pytest.importorskip("yaml")
    node = yaml.safe_load(read("docker-compose.yml"))["services"]["node"]
    assert any(str(where).endswith(":/app/.data") for where in node["volumes"])


def test_compose_does_not_arm_the_desk_by_itself():
    """`TRADING_LIVE` is the arming switch and belongs in the environment a
    person controls, not in a file that is committed. The risk engine sits in
    `HALTED` without it."""
    assert "TRADING_LIVE: 1" not in read("docker-compose.yml")
    assert "TRADING_LIVE=1" not in executable(read("docker-compose.yml"))


# ------------------------------------------------------ and the docs that say so


#: Phrases that mark a document as having declared its commands dead.
#: Several, because the three places that needed one needed different wording:
#: a whole document, a single block, or a package that retired with its CLI.
DECLARED = (
    "commands in this document no longer exist",
    "commands below no longer exist",
    "These no longer exist",
    "The table used to offer",
)


def runnable(text: str) -> list[str]:
    """Lines that invite a reader to run the retired CLI.

    An invocation, not a mention. Prose explaining that the CLI retired names
    it constantly and must keep being able to.
    """
    return [
        line
        for line in text.splitlines()
        if re.match(r"^\s*(uv run |\$ )?till-infinity\s+\w", line)
    ]


def documents() -> list[Path]:
    return [path for path in sorted(ROOT.glob("docs/**/*.md")) if "retire" not in path.parts]


def test_no_document_offers_a_dead_command_without_saying_so():
    """**Documentation is an entry point too.** A reader following
    `docs/getting-started.md` ran `till-infinity run` and got "command not
    found", which is a worse first impression than a README that says the
    thing retired - and the retirement was eleven days before this was
    noticed.

    These documents are not rewritten, deliberately: `docs/levels.md` is 1,900
    lines about a model that is the ancestor of `statespace/` and the
    measurements in it are still the measurements. What they carry is a note
    saying the commands are gone and what replaced them.
    """
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in documents()
        if runnable(path.read_text()) and not any(mark in path.read_text() for mark in DECLARED)
    ]
    assert not missing, (
        "these documents invite a reader to run the retired CLI without saying "
        f"it retired: {missing}"
    )


def test_the_readme_points_at_the_module():
    """It is the first thing anybody reads, and it told them to run a command
    that does not exist."""
    readme = read("README.md")
    assert "python -m till_infinity.node.live" in readme
    assert not runnable(readme), "the README should not invite the retired CLI at all"


def test_the_guard_can_tell_an_invocation_from_a_mention():
    """Otherwise it would demand a banner on every document that explains the
    retirement, which is the opposite of the point."""
    assert runnable("uv run till-infinity run")
    assert runnable("till-infinity health")
    assert not runnable("the `till-infinity` CLI retired to research/retire/bus/")
    assert not runnable("There is no `till-infinity` command, deliberately.")


# --------------------------------------------------- and the image that builds


def copy_sources() -> list[str]:
    """The build-context paths every `COPY` in the Dockerfile reads.

    `COPY --from=...` is skipped: its source is an earlier stage, not the
    repository. A trailing destination is dropped, and a line may list several
    sources, which is how the breakage below hid - the list was right and the
    *order* was wrong, so a reader checking that each member appeared found
    each member.
    """
    found = []
    for line in read("Dockerfile").splitlines():
        stripped = line.strip()
        if not stripped.startswith("COPY ") or "--from=" in stripped:
            continue
        parts = [p for p in stripped.split()[1:] if not p.startswith("--")]
        found.extend(parts[:-1])
    return found


def test_every_copy_source_exists():
    """**The image could not build for eleven days and the suite was green.**

    `packages/till-platform/`, `packages/till-channels/` and `shared/` were
    copied in by five `COPY` lines, and all three retired to
    `research/retire/` - `pyproject.toml` records that there is no uv
    workspace any more. `docker build` failed at the second line in the file
    with "packages/till-platform: not found", so no image was produced at all
    and the rollback in `deploy.sh` was the only thing keeping the box up.

    Nothing here builds the image, and this is the cheapest substitute: a COPY
    whose source is not in the repository cannot succeed, whatever the build
    arguments are. It is a weaker check than a build and it would have caught
    this on the first run after the retirement, which the rest of the suite
    did not manage in eleven days.
    """
    missing = [source for source in copy_sources() if not (ROOT / source).exists()]
    assert not missing, (
        f"the Dockerfile copies paths that are not in the repository: {missing} - "
        f"`docker build` fails on the first one"
    )


def test_the_image_names_no_retired_workspace_member():
    """Checked by name as well as by existence, so the fix cannot be to
    recreate an empty `packages/` directory and leave the image installing a
    workspace this project no longer has.

    Only the `COPY` sources and the `ENV` lines are read. A plain substring
    search over the file matches `site-packages/` inside the digest check that
    compares the installed package against the source, which is a line that has
    to stay.
    """
    retired = ("packages/till-", "shared/", "till-platform", "till-channels")
    named = [
        source
        for source in copy_sources()
        if any(source.startswith(mark) or source == mark.rstrip("/") for mark in retired)
    ]
    assert not named, f"the Dockerfile still copies {named}"

    for line in read("Dockerfile").splitlines():
        if line.strip().startswith("ENV ") and "shared/contracts" in line:
            raise AssertionError(f"the Dockerfile still points at the retired contracts: {line!r}")


# ------------------------------------------------------- what CI points at


def workflow_paths() -> dict[str, list[str]]:
    """Repository paths each CI job globs for, by job name.

    A narrow read on purpose: `cache-dependency-path` and the `for .. in`
    globs of a shell step are where a job names a directory it expects to
    exist. Anything cleverer would need a shell parser, and the point here is
    the same as `test_every_copy_source_exists` - a path that is not in the
    repository cannot be found, whatever the runner does.
    """
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    jobs: dict[str, list[str]] = {}
    job = ""
    for line in text.splitlines():
        named = re.match(r"^  (\w[\w-]*):\s*$", line)
        if named:
            job = named.group(1)
            jobs.setdefault(job, [])
            continue
        if not job:
            continue
        for found in re.findall(r"(?:cache-dependency-path:\s*|in\s+)([\w./*-]+/[\w./*-]+)", line):
            jobs[job].append(found)
    return jobs


def test_no_ci_job_globs_a_directory_that_is_gone():
    """**A red job that describes nothing gates every merge, and this one did.**

    ADR 0003 took on a second toolchain for the Go services under `services/`.
    `a80de7e5` retired those with the rest of the legacy desk and the module
    moved to `research/retire/services/ticks/`, which CI excludes on purpose -
    but the `go` job stayed, globbing `services/*/go.mod`. Its own guard was
    correct and fired every run with "no Go module under services/ - this job
    is pointing at nothing", so the checks list carried a failure that was
    true, uninformative, and blocking.

    The guard was right to be an error rather than a silent pass. What was
    missing was a test that notices when a job outlives the code it checks,
    which is this one.
    """
    gone = {
        job: [path for path in paths if not list(ROOT.glob(path))]
        for job, paths in workflow_paths().items()
    }
    broken = {job: paths for job, paths in gone.items() if paths}
    assert not broken, (
        f"CI jobs glob paths that are not in the repository: {broken} - the job "
        f"cannot pass, and a job that cannot pass blocks every merge"
    )


def deploy_sources() -> list[str]:
    """Repository paths the deploy workflow sends to the instance.

    Only `scp` sources, which is the one place that workflow names a file in
    this repository rather than on the host. Everything else in it is a path
    on the instance - `/tmp/till-deploy.sh`, `$HOME/...` - and those are
    runtime locations this test cannot and should not check.
    """
    text = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    found = re.findall(r"scp\s+(?:-\S+\s+\S+\s+)*([\w./-]+)\s+\"?\$?\w*HOST", text)
    return [path for path in found if not path.startswith(("/", "~", "$"))]


def test_the_deploy_workflow_sends_files_that_exist():
    """**A moved script breaks the deploy and nothing before this said so.**

    `deploy.sh` moved to `scripts/` and the workflow `scp`s it by path, so a
    rename that misses line 163 leaves a deploy that fails at the copy - after
    the image is built, pushed and tagged, which is the most expensive place
    to find out. `scp` of a missing file is an error, so the deploy stops
    rather than running a stale script, but it stops on the instance and not
    in a check.

    The same shape as `test_every_copy_source_exists`, and for the same
    reason: the cheapest substitute for running the thing is asserting that
    the paths it names are in the repository.
    """
    sources = deploy_sources()
    assert sources, "no scp source found - the regex no longer matches the workflow"
    missing = [path for path in sources if not (ROOT / path).exists()]
    assert not missing, (
        f"the deploy workflow copies paths that are not in the repository: "
        f"{missing} - the deploy fails at the scp, after the image is pushed"
    )
