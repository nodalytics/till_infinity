"""The cache can outlive a restart, and the broker still outranks it.

**Why this exists.** The engine's cache holds the orders and positions this
process knows about and it is in memory, so a restart forgets them while the
broker does not. Measured on 2026-11-21: a ZonesEdge ETHUSD position opened at
10:35, the container restarted at 11:24, and at 11:25 the engine logged

    Missing hedge position for ETHUSD.MT5 PositionId('5843090622'):
    venue reports -3.32, generating reconciliation order

attaching the position to a synthetic order with a random id. When its stop
fired at 11:32 the closing fill arrived **correctly** as `5843090622-SL` and
matched nothing, because the real bracket had been erased by the restart. No
amount of correctness in the adapter fixes that from below, which is why the
fix belongs in the cache.

**The hazard it introduces is the subject of half of these tests.** A cache that
survives a restart can be *stale*: if the broker closes a position while this
process is down, Redis still holds it when the process returns. A persistent
cache that overrode reconciliation would be **strictly worse than no cache**,
so the precedence is pinned here rather than assumed from reading
`LiveExecEngineConfig`.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _no_redis_by_default():
    """Every test starts from the shipped default, whatever the environment has."""
    kept = os.environ.pop("TRADING_CACHE_REDIS", None)
    yield
    if kept is not None:
        os.environ["TRADING_CACHE_REDIS"] = kept
    else:
        os.environ.pop("TRADING_CACHE_REDIS", None)


class TestTheGate:
    def test_off_by_default_is_the_cache_this_desk_has_always_had(self) -> None:
        """**Off is the existing behaviour, not a degraded one.**

        A deployment that has not asked for Redis keeps an in-memory cache and
        the ISO timestamps it already had.
        """
        from till_infinity.node.live import _cache

        got = _cache()
        assert got.database is None, "an unset variable must not reach for a database"
        assert got.timestamps_as_iso8601 is True

    def test_a_host_and_port_names_a_redis(self) -> None:
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "172.17.0.1:6379"
        got = _cache()
        assert got.database is not None
        assert (got.database.type, got.database.host, got.database.port) == (
            "redis",
            "172.17.0.1",
            6379,
        )

    def test_a_bare_host_takes_the_usual_port(self) -> None:
        """`172.17.0.1` is the docker bridge gateway - the same address the MT5
        tunnel binds - so the common case should not need a port."""
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "172.17.0.1"
        assert _cache().database.port == 6379

    def test_whitespace_is_not_a_host(self) -> None:
        """An empty-but-present variable is how a deploy script sets "off"."""
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "   "
        assert _cache().database is None


class TestTheThreeSettingsThatMakeItPersist:
    """**Each of these silently defeats persistence if it drifts.**

    They are Nautilus defaults today and are named explicitly in `_cache`, so
    this asserts the composed config rather than the library's defaults - a
    future Nautilus that flipped one would break persistence with no error, and
    this is what would say so.
    """

    def test_it_does_not_flush_what_it_came_back_for(self) -> None:
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "127.0.0.1:6379"
        assert _cache().flush_on_start is False, (
            "flushing on start makes a persistent cache a no-op with extra steps"
        )

    def test_every_run_shares_one_keyspace(self) -> None:
        """The subtle one. With `use_instance_id` true each run writes under its
        own id, so the cache persists into a namespace nothing ever reads - the
        failure looks exactly like no persistence at all."""
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "127.0.0.1:6379"
        assert _cache().use_instance_id is False

    def test_account_events_are_kept(self) -> None:
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "127.0.0.1:6379"
        assert _cache().persist_account_events is True


class TestItIsNotReachableOrAnonymous:
    """**A review refused the first cut of this, and it was right.**

    The cache was published on `172.17.0.1:6379` - the docker bridge gateway -
    with no password. That address is reachable by every container on the box
    and from the host, and this keyspace is the desk's own view of its open
    orders and positions: writing it is writing what the desk *believes* it
    holds. An unauthenticated writer could make the desk carry a position that
    does not exist, or forget one that does - the stale-cache hazard below,
    except adversarial rather than accidental.

    Two controls now, asserted here because neither is visible from the node's
    own config: the cache listens only on a private docker network, and it
    takes a password when one is set.
    """

    def test_no_launch_path_publishes_the_port(self) -> None:
        """Reachability is the first control, so nothing may publish 6379."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for name in ("docker-compose.yml", "scripts/deploy.sh"):
            text = (root / name).read_text()
            assert "6379:6379" not in text, (
                f"{name} publishes the cache's port; it must stay on a private "
                "network reachable only by service name"
            )

    def test_both_launch_paths_disable_config(self) -> None:
        """A cache that can be reconfigured at runtime can be told to drop its
        password or persist elsewhere, and nothing needs `CONFIG` after start."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for name in ("docker-compose.yml", "scripts/deploy.sh"):
            text = (root / name).read_text()
            assert "rename-command" in text, f"{name} renames no command"
            assert "CONFIG" in text, f"{name} leaves CONFIG enabled on the cache"

    def test_a_running_cache_is_kept_only_if_it_matches(self) -> None:
        """**The fail-open a second review caught.**

        The first version asked only "is one running". A cache started by an
        earlier, weaker script - published port, no password - would have been
        *kept* by the fixed one, so the fix would never have reached the box it
        was written for.

        The deploy now compares a digest of the intended configuration against
        a label on the running container, which forces a recreate on *any*
        divergence rather than on three remembered fields - and means the
        comparison never reads the password back out of `docker inspect`.
        """
        from pathlib import Path

        text = (Path(__file__).resolve().parents[1] / "scripts/deploy.sh").read_text()
        assert "till.cache.config" in text, "nothing stamps the intended config"
        assert "HAVE_DIGEST" in text, "nothing reads the running config back"
        assert "already running with this configuration" in text, (
            "the keep branch does not say that it checked"
        )
        assert 'echo "till-cache already running"' not in text, (
            "the unconditional keep is still there, which is the fail-open"
        )

    def test_a_password_reaches_the_node_and_is_redacted(self) -> None:
        """The node has to send the same secret, and it must not end up in a log.

        Passed as a `DatabaseConfig` field rather than folded into a URL for
        exactly that reason - `DatabaseConfig` redacts it in its own `repr`,
        and a URL with a password in it reaches a log line eventually.
        """
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "till-cache:6379"
        os.environ["TRADING_CACHE_REDIS_PASSWORD"] = "not-the-real-one"
        try:
            got = _cache()
            assert got.database.password == "not-the-real-one"
            assert "not-the-real-one" not in repr(got.database), (
                "the password survives into a repr, so it will reach a log"
            )
        finally:
            os.environ.pop("TRADING_CACHE_REDIS_PASSWORD", None)

    def test_no_password_is_supported_and_means_none(self) -> None:
        """A deployment without one is valid - the network is the control - and
        it must read as absent rather than as an empty-string password."""
        from till_infinity.node.live import _cache

        os.environ["TRADING_CACHE_REDIS"] = "till-cache:6379"
        os.environ.pop("TRADING_CACHE_REDIS_PASSWORD", None)
        assert _cache().database.password is None


def test_the_broker_outranks_a_persisted_cache() -> None:
    """**The hazard, pinned.** Reconciliation runs at startup, so the venue wins.

    A persistent cache can be stale: the broker can close a position while this
    process is down. If the cache then overrode the venue, the desk would hold
    a position that does not exist and refuse entries on that instrument -
    which is the phantom this change exists to remove, reintroduced from the
    other direction and harder to see.

    `judge-the-desk-on-the-broker-not-the-journal` is the standing rule and
    this is the config that enforces it. Asserted on the composed node settings
    rather than on a literal, so turning reconciliation off would fail here
    before it reached an account.
    """
    from till_infinity.node.live import settings

    os.environ["TRADING_CACHE_REDIS"] = "127.0.0.1:6379"
    config = settings()
    assert config.exec_engine.reconciliation is True, (
        "a persisted cache without startup reconciliation would let a stale "
        "position outrank the broker, which is worse than no cache"
    )
    assert config.cache.database is not None, "the test should be running the redis arm"
