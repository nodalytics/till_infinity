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
STARTERS = ("Dockerfile", "docker-compose.yml", "deploy.sh")


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
    text = executable(read("deploy.sh"))
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
