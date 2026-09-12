"""The desk must say something when it loses its terminal entirely.

**Two hours of a blind desk on 2026-09-12 produced no alert.** The terminal runs
on another host, that host left the network, and `sweep` returns before
`_check_autotrading` when the broker does not answer - so the failure wrote one
WARNING per heartbeat and raised nothing. The container read `healthy` and
`till-infinity health` read seven services running, both correctly: nothing in
the process was wrong.

`_check_autotrading` covers "the terminal says no". This covers "there is no
terminal", which is the gap it could not see, and these tests exist because the
gap was invisible in exactly the way a passing test suite is.

Exercised on a stub rather than a live `Trader`: the method reads one counter and
calls one reporter, and a test that needs a broker, a bus and a journal to prove
an `if` is a test nobody keeps running.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from till_infinity.trading.service import UNREACHABLE_AFTER, Trader


@dataclass
class Desk:
    """The two attributes `_watch_reachable` actually touches."""

    _unreachable: int = 0
    said: list[tuple[str, str]] = field(default_factory=list)

    async def _shout_state(self, title: str, body: str, level: str) -> None:
        self.said.append((title, level))

    def watch(self, reachable: bool) -> None:
        asyncio.run(Trader._watch_reachable(self, reachable))


def test_a_single_missed_sweep_says_nothing():
    """A redeploy or a blip must not page anyone."""
    desk = Desk()
    desk.watch(False)
    assert desk.said == []
    assert desk._unreachable == 1


def test_it_shouts_once_the_outage_is_real():
    desk = Desk()
    for _ in range(UNREACHABLE_AFTER):
        desk.watch(False)
    assert len(desk.said) == 1
    title, level = desk.said[0]
    assert "cannot reach" in title
    assert level == "critical", "info and warning and critical are the only levels"


def test_it_shouts_exactly_once_however_long_it_lasts():
    """One alert per heartbeat for two hours is a channel nobody reads, which is
    how the next outage gets missed. Edge-triggered, like `_check_autotrading`."""
    desk = Desk()
    for _ in range(UNREACHABLE_AFTER * 40):
        desk.watch(False)
    assert len(desk.said) == 1


def test_it_says_when_the_terminal_comes_back():
    """ "Is it back" is the question that follows the alarm."""
    desk = Desk()
    for _ in range(UNREACHABLE_AFTER):
        desk.watch(False)
    desk.watch(True)
    assert len(desk.said) == 2
    assert desk.said[1][1] == "info"
    assert desk._unreachable == 0


def test_recovery_is_silent_when_nothing_was_ever_announced():
    """A blip that cleared before the threshold must not announce a recovery
    from an outage nobody was told about."""
    desk = Desk()
    desk.watch(False)
    desk.watch(True)
    assert desk.said == []
    assert desk._unreachable == 0


def test_the_counter_resets_so_a_second_outage_is_announced_too():
    desk = Desk()
    for _ in range(UNREACHABLE_AFTER):
        desk.watch(False)
    desk.watch(True)
    for _ in range(UNREACHABLE_AFTER):
        desk.watch(False)
    assert [level for _, level in desk.said] == ["critical", "info", "critical"]


def test_the_threshold_is_minutes_not_hours():
    """The heartbeat is 60s by default. A threshold large enough to hide a real
    outage is the defect this was written for."""
    assert 2 <= UNREACHABLE_AFTER <= 15
