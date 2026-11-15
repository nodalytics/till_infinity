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
    """The probe is the one thing in this file that can be run here.

    `node.probe` and not `node.status`: the reader moved out of the writer's
    module because importing it pulled in a Nautilus `Actor`, and the
    `HEALTHCHECK` was spending 1.6s of import time and about 1.2 cores a
    minute to read one JSON file - more CPU than the desk it was checking.
    `status` re-exports these names, so the change is where the code lives.
    """
    assert "python -m till_infinity.node.probe" in read("Dockerfile")

    from till_infinity.node import probe

    ok, reason = probe.healthy("/nonexistent/status.json")
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


def test_the_deploy_waits_for_healthy_and_not_merely_running():
    """**A deploy that checks liveness reports success over a dead desk.**

    On 2026-11-06 the gate passed with `status=running restarting=false
    restarts=0->0` and the deploy went green - while the node had already
    written that it was stopping. It then failed its healthcheck fourteen
    times in a row with `the node wrote that it was stopping`, CPU flat at
    0.00% with markets open, and nobody would have known from the deploy.

    `running` and `healthy` are different questions. The restart-count
    comparison stays, because it catches a different failure - a container in
    backoff reads `Up` at any single instant - but it cannot see a process
    that started, gave up, and left the container alive around it.

    **The wait must outlast the start period.** A healthcheck reports
    `starting` for the whole of `--start-period`, whatever its probes say, so
    a gate that gives up sooner can only ever see `starting` and learns
    nothing. Read from the Dockerfile here rather than hardcoded, so raising
    one and not the other fails this test instead of the next deploy.
    """
    text = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert ".State.Health.Status" in text, (
        "the deploy does not read the container's health - it can only prove the "
        "container is running, which is what let a stopped node deploy green"
    )
    assert "unhealthy" in text, "nothing in the deploy fails on an unhealthy desk"

    start = re.search(r"--start-period=(\d+)s", (ROOT / "Dockerfile").read_text())
    assert start, "no start period in the Dockerfile's HEALTHCHECK"
    waits = [int(n) for n in re.findall(r"HEALTH_WAIT_S\s*[:=]\s*(\d+)", text)]
    assert waits, "the deploy names no health deadline (HEALTH_WAIT_S)"
    assert max(waits) > int(start.group(1)), (
        f"the deploy waits {max(waits)}s for health but the healthcheck reports "
        f"`starting` for {start.group(1)}s - the gate would time out before the "
        f"first real probe and never see `healthy`"
    )


FAKE_DOCKER = """#!/usr/bin/env bash
case "$*" in
  *"{{.State.Status}} {{.State.Restarting}} {{.RestartCount}}"*)
    echo "${FAKE_LIVENESS:-running false 0}" ;;
  *"{{.RestartCount}}"*) echo "${FAKE_RESTARTS_LATER:-0}" ;;
  *"{{if .State.Health}}yes{{end}}"*) echo "${FAKE_HAS_HEALTH-yes}" ;;
  *"{{.State.Health.Status}}"*) echo "${FAKE_HEALTH:-healthy}" ;;
  *) echo "" ;;
esac
"""


def health_gate() -> str:
    """The script the deploy runs on the instance, out of the workflow.

    Extracted rather than copied, so the test runs the deployed text and not a
    paraphrase of it that can drift.
    """
    import yaml

    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    step = next(
        s for s in doc["jobs"]["deploy"]["steps"] if s.get("name") == "Prove it came back up"
    )
    found = re.search(r"<<'REMOTE'\n(.*?)\nREMOTE\n", step["run"], re.S)
    assert found, "the deploy's health gate is no longer a REMOTE heredoc"
    return found.group(1)


@pytest.mark.parametrize(
    ("scenario", "env", "code", "says"),
    [
        ("a healthy desk", {"FAKE_HEALTH": "healthy"}, 0, "healthy"),
        ("one that stopped", {"FAKE_HEALTH": "unhealthy"}, 1, "came up and stopped"),
        ("one still warming", {"FAKE_HEALTH": "starting"}, 1, "still starting"),
        ("an image with no healthcheck", {"FAKE_HAS_HEALTH": ""}, 0, "no healthcheck"),
        ("a restart loop", {"FAKE_RESTARTS_LATER": "7"}, 1, "restarts=0->7"),
    ],
)
def test_the_health_gate_decides_each_case_correctly(tmp_path, scenario, env, code, says):
    """**Run the gate, do not just read it.**

    The gate is the thing that failed on 2026-11-06 - it proved
    `status=running restarting=false restarts=0->0` over a node that had
    written that it was stopping, and the deploy went green. A test that only
    greps the workflow for `Health.Status` would have passed against a gate
    that read health and then ignored it.

    So `docker` and `sleep` are replaced on `PATH` and the real script runs.
    `an image with no healthcheck` is the case that must still pass: an image
    without one is not a broken deploy, and failing there would block any
    service that does not define one.
    """
    import subprocess

    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "docker").write_text(FAKE_DOCKER)
    (fake / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    for name in ("docker", "sleep"):
        (fake / name).chmod(0o755)
    script = tmp_path / "gate.sh"
    script.write_text(health_gate())

    done = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{fake}:/usr/bin:/bin", "HEALTH_WAIT_S": "1", **env},
    )

    assert done.returncode == code, f"{scenario}: {done.stdout}{done.stderr}"
    assert says in done.stdout, f"{scenario}: said {done.stdout!r}"


@pytest.mark.parametrize(("cores", "limit"), [("2", 1.80), ("8", 7.20), ("1", 0.90)])
def test_the_deploy_scales_the_cpu_limit_to_the_host(tmp_path, cores, limit):
    """**It was hard-coded at 1.5 while the memory beside it scaled.**

    The memory limit is 70% of the host's and says why: hard-coding "wastes a
    bigger machine and over-commits a smaller one, unnoticed until the kills
    start". CPU had the same problem and not the same treatment.

    1.5 was also simply too small. Measured 2026-11-06, the fifteen-minute
    fold across 46 desks peaked at **1.429 cores** and the cgroup reported
    `nr_throttled 55` - the desk was being denied CPU at every bar close.

    Run rather than read, with `nproc` stubbed: an arithmetic expression is
    exactly the kind of line that looks right and is off by a factor.
    """
    import subprocess

    text = (ROOT / "scripts" / "deploy.sh").read_text()
    found = re.search(r'^(CPU_LIMIT="\$\(awk.*\)")$', text, re.M)
    assert found, "the deploy no longer computes CPU_LIMIT - has it gone back to a constant?"

    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "nproc").write_text(f"#!/usr/bin/env bash\necho {cores}\n")
    (fake / "nproc").chmod(0o755)
    script = tmp_path / "limit.sh"
    script.write_text(f'CORES="$(nproc)"\n{found.group(1)}\necho "$CPU_LIMIT"\n')

    done = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{fake}:/usr/bin:/bin"},
    )

    assert done.returncode == 0, done.stderr
    assert float(done.stdout.strip()) == pytest.approx(limit)


def test_the_cpu_limit_clears_the_measured_fold(tmp_path):
    """The number the limit has to beat is the burst, not the average.

    `PER_CORE` was raised to 24 on the strength of the container sitting at
    "6.8% CPU", and that average was true and misleading: steady state is
    0.195 of 1.5 cores, 13%, while the fold five seconds either side of a bar
    boundary is 1.429. A limit chosen from the average throttles at every
    close.
    """
    import subprocess

    text = (ROOT / "scripts" / "deploy.sh").read_text()
    found = re.search(r'^(CPU_LIMIT="\$\(awk.*\)")$', text, re.M)
    assert found
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "nproc").write_text("#!/usr/bin/env bash\necho 2\n")
    (fake / "nproc").chmod(0o755)
    script = tmp_path / "limit.sh"
    script.write_text(f'CORES="$(nproc)"\n{found.group(1)}\necho "$CPU_LIMIT"\n')
    got = float(
        subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": f"{fake}:/usr/bin:/bin"},
        ).stdout.strip()
    )

    assert got > 1.429, (
        f"two cores gives the container {got}, which does not clear the measured "
        f"1.429-core fold - the desk would be throttled at every bar close"
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


def test_the_example_env_names_only_rules_that_exist():
    """**The check that was missing when a deploy took the desk down.**

    On 2026-11-03 the live environment still named sixteen rules retired with
    the Nautilus port - `cycle-turn`, `level-scalp`, `fade-to-value` and the
    rest. `desks.rules` refuses an unknown name rather than silently running
    nothing, which is correct, so the node raised on every start and the
    container restarted **27 times**.

    Nothing compared a shipped configuration against the rule registry, so a
    name could rot in `.env.example` indefinitely and anyone copying it would
    inherit the crash. This asserts the join; `scripts/deploy.sh --check`
    asserts it against the *deployed* environment, which is the half a test
    cannot reach.
    """
    from till_infinity.node import desks

    text = (ROOT / ".env.example").read_text()
    named: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if not stripped.startswith("TRADING_STRATEGIES="):
            continue
        value = stripped.split("=", 1)[1].strip()
        named.extend(part.strip() for part in value.replace(",", " ").split() if part.strip())

    assert named, ".env.example names no strategies at all"
    unknown = sorted({name for name in named if name not in desks.RULES})
    assert not unknown, (
        f".env.example names {unknown}, which `desks.rules` would refuse on "
        f"start. Known: {', '.join(desks.RULES)}."
    )


def test_the_example_env_pairs_its_rules_with_an_entry_that_exists():
    """A valid rule on the wrong entry raises too, and `smc-bos-causal` exists
    on `edge` alone - so a configuration naming it beside
    `TRADING_ENTRIES=resting` is as dead as a retired rule name, for a reason
    that is one level further in."""
    from till_infinity.node import desks
    from till_infinity.strategies.leaves import LEAVES

    text = (ROOT / ".env.example").read_text()

    def named(key: str) -> list[str]:
        out: list[str] = []
        for line in text.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped.startswith(f"{key}="):
                value = stripped.split("=", 1)[1].strip()
                out.extend(p.strip() for p in value.replace(",", " ").split() if p.strip())
        return out

    rules = named("TRADING_STRATEGIES")
    entries = named("TRADING_ENTRIES") or list(desks.entries())
    dead = [f"{rule}/{entry}" for rule in rules for entry in entries if (rule, entry) not in LEAVES]
    assert not dead, (
        f".env.example pairs {dead}, which `leaves.of` refuses. Valid pairings: "
        f"{', '.join(f'{r}/{e}' for r, e in sorted(LEAVES))}."
    )


class _Trader:
    def __init__(self, running: bool) -> None:
        self.is_running = running


class _Node:
    def __init__(self, running: bool) -> None:
        self.trader = _Trader(running)


def test_a_node_that_never_started_its_trader_leaves_the_process():
    """**A node that comes up empty must not stay up.**

    Nautilus returns from its start sequence before `trader.start()` when the
    engines miss their connect timeout - `if not await
    self._await_engines_connected(): return` - so the process keeps running,
    answers the venue and trades nothing. On 2026-11-14 that happened on two
    consecutive deploys, 78 and 85 seconds of instrument loading against a
    60-second wait, and the desk sat empty for thirteen minutes: the
    healthcheck saw it, Docker does not act on an unhealthy container, and the
    actor that would have said so was one of the things that never started.
    """
    from till_infinity.node import live

    left: list[int] = []
    assert live.abandon_unstarted(_Node(running=False), 420.0, quit_=left.append) is True
    assert left == [70], "an empty node stayed up"


def test_a_running_node_is_left_alone():
    """The control, and the reason this test matters more than the one above.

    This calls `os._exit` in production. A predicate that is wrong in this
    direction does not leave a desk idle - it takes down a desk that is
    working, on a timer, every seven minutes.
    """
    from till_infinity.node import live

    left: list[int] = []
    assert live.abandon_unstarted(_Node(running=True), 420.0, quit_=left.append) is False
    assert left == [], "a running node was killed"


def test_a_node_that_cannot_be_asked_counts_as_unstarted():
    """`started` must not raise on a node whose trader is not there yet.

    It runs on a timer against an object another library owns, so the one
    thing it cannot do is raise inside a daemon thread where nothing is
    waiting to catch it.
    """
    from till_infinity.node import live

    assert live.started(object()) is False
