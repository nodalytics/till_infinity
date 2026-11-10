"""The zones rule's tally line: a cold indicator must not read as a quiet market.

**Written from a live observation.** Fifteen minutes after `zones` was deployed
its tally read `taken=0 refused=0 gates={}` and there was no way to tell a cold
`BjorgumLevels` from a market that had produced no crossing. Every number
needed was already being counted in `Zones.counts` and none of it was printed.

`structure.py` has the same method for the same reason, and its docstring
records the cost: on 2026-11-07 all 32 feeds had zero confirmed swings after
7.8 hours and nothing said so.
"""

from __future__ import annotations

from types import SimpleNamespace

from till_infinity.strategies.zones import Zones


def line(counts: dict[str, int], *, zones: int, initialized: bool = True) -> str:
    """`Zones._tally_extra` on a stub carrying only what it reads."""
    stub = SimpleNamespace(
        counts=counts,
        levels=SimpleNamespace(
            initialized=initialized,
            zones=[SimpleNamespace(at=i) for i in range(zones)],
        ),
    )
    return Zones._tally_extra(stub)


def test_an_unwarmed_indicator_is_distinguishable_from_a_quiet_market():
    """The whole point. Both desks took nothing; only one of them *could* have."""
    cold = line({"bars": 12, "unwarmed": 12, "signals": 0}, zones=0, initialized=False)
    quiet = line({"bars": 400, "unwarmed": 50, "signals": 0}, zones=18)

    assert "bars=12" in cold
    assert "zones=0" in cold
    assert "bars=400" in quiet
    assert "zones=18" in quiet
    assert cold != quiet, "a cold indicator and a quiet market read identically"


def test_a_warmed_indicator_with_no_zones_still_says_so():
    """`initialized` and "has nominated a zone" are different states, and a rule
    that is warm but has found nothing is the more interesting of the two."""
    assert "zones=0" in line({"bars": 400, "unwarmed": 50, "signals": 0}, zones=0)


def test_the_duty_and_turn_counters_appear_only_when_they_have_fired():
    """A tally line is read at a glance, so a counter that is always zero is
    noise. The duty-cycle control is off by default and most deploys never
    reverse a position, so both are reported only when non-zero."""
    plain = line({"bars": 400, "unwarmed": 0, "signals": 3}, zones=5)
    assert "dropped=" not in plain
    assert "turned=" not in plain

    busy = line(
        {"bars": 400, "unwarmed": 0, "signals": 3, "duty_dropped": 7, "closed_on_turn": 2},
        zones=5,
    )
    assert "dropped=7" in busy
    assert "turned=2" in busy


def test_the_signal_count_is_reported_and_is_not_the_trade_count():
    """`taken` is already on the tally and counts what the desk *placed*.
    `signals` counts what the rule *proposed*, and the gap between them is
    every gate in front of it - which is the number that says whether a quiet
    desk is a quiet rule or a rule being refused downstream."""
    got = line({"bars": 400, "unwarmed": 0, "signals": 9}, zones=5)
    assert "signals=9" in got
