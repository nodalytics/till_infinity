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

import os
from types import SimpleNamespace

from till_infinity.strategies.zones import Zones


def line(counts: dict[str, int], *, zones: int, initialized: bool = True) -> str:
    """`Zones._tally_extra` on a stub carrying only what it reads."""
    stub = SimpleNamespace(
        counts=counts,
        warmed={
            "bars": counts.get("warm", 0),
            **({"foreign": counts["foreign"]} if "foreign" in counts else {}),
            **({"repeat": counts["repeat"]} if "repeat" in counts else {}),
        },
        levels=SimpleNamespace(
            initialized=initialized,
            bars=counts.get("bars", 0),
            atr=0.00132,
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


def test_the_warm_bar_count_is_reported_apart_from_the_live_one():
    """**A fold warmed by replay and one filled by the market are different
    states.** `zones` now requests 400 bars on start, so without this the bar
    count would read as live and a desk twelve hours into its blind window
    would be indistinguishable from one that had been trading all day."""
    got = line({"bars": 400, "warm": 380, "unwarmed": 50, "signals": 0}, zones=18)
    assert "bars=400" in got
    assert "warm=380" in got


def test_the_indicators_own_bar_count_and_scale_are_reported():
    """**The desk's view of the indicator is not the indicator.** On 2026-11-10
    a live tally read `bars=617 warm=616 unwarmed=617 zones=0` and there was no
    way to tell an indicator that had been fed nothing from one that had been
    fed 616 bars and nominated nothing. `fed` is `BjorgumLevels.bars`, its own
    count, and `atr` is the number every zone width derives from - folding
    another instrument's bars took it from 0.00132 to 0.62083 in reproduction,
    a factor of 470, and nothing on the line would have shown it."""
    got = line({"bars": 617, "warm": 616, "unwarmed": 617, "signals": 0}, zones=0)
    assert "fed=617" in got
    assert "atr=0.00132" in got


def test_foreign_and_repeated_history_are_reported_only_when_they_happen():
    """A desk is delivered history it never requested - measured at 3 to 6
    responses per desk. The guard refuses them; these counters are how a
    reader sees that it is still happening at all."""
    quiet = line({"bars": 400, "warm": 400, "unwarmed": 0, "signals": 0}, zones=5)
    assert "foreign=" not in quiet
    assert "repeat=" not in quiet

    noisy = line(
        {"bars": 400, "warm": 400, "unwarmed": 0, "signals": 0, "foreign": 208, "repeat": 416},
        zones=5,
    )
    assert "foreign=208" in noisy
    assert "repeat=416" in noisy


# ------------------------------------------------- the operator's configuration


def _tuning(monkeypatch, **env):
    from till_infinity.strategies import zones

    for key in list(os.environ):
        if key.startswith("TRADING_ZONE_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return zones.Tuning.read()


def test_the_desk_preset_carries_every_setting_it_was_given(monkeypatch):
    """**A named configuration, so a result can be quoted against it.**

    `script` is the published indicator's defaults and `measured` is what
    `bjorgum.md` was run on; mixing them gives numbers belonging to neither,
    which is how a figure ends up quoted for a configuration it was never run
    on. This is the third, asked for on 2026-11-15, and it is asserted here
    rather than left to a sweep's flags.
    """
    from till_infinity.indicators.levels import PivotSource

    built = _tuning(monkeypatch, TRADING_ZONE_PRESET="desk").build()

    assert built.left == 15
    assert built.right == 5
    assert built.atr_len == 30
    assert built.keep == 1
    assert float(built.mult.shared) == 0.015
    assert built.pivots is PivotSource.HIGH_LOW_BODY


def test_an_explicit_pivot_source_beats_the_preset_and_the_default(monkeypatch):
    """**`pivots` cannot say "unset" the way the integers can.**

    The other knobs use `0` for "keep the preset's own value". A pivot source
    has no such value, so without `pivots_named` the preset would either
    override an operator who asked for Heikin-Ashi or be overridden by the
    module default they never set - and both of those are silent.
    """
    from till_infinity.indicators.levels import PivotSource

    asked = _tuning(monkeypatch, TRADING_ZONE_PRESET="desk", TRADING_ZONE_PIVOTS="ha").build()
    assert asked.pivots is PivotSource.HA, "the operator's choice was overridden"

    silent = _tuning(monkeypatch, TRADING_ZONE_PRESET="desk").build()
    assert silent.pivots is PivotSource.HIGH_LOW_BODY, "the preset's choice was overridden"


def test_a_knob_still_beats_the_preset(monkeypatch):
    """A sweep varies one parameter and leaves the rest where the preset put
    them - which is the property that makes a preset worth naming."""
    built = _tuning(monkeypatch, TRADING_ZONE_PRESET="desk", TRADING_ZONE_KEEP="4").build()

    assert built.keep == 4
    assert built.left == 15, "varying one knob moved another"


def test_every_detection_at_once_needs_the_readings_to_agree():
    """**`all` is not the union of the four, because two of them disagree.**

    The script draws all four and the checkbox list reads as a union. As a
    trade rule it is not one: `reject` is a *reversal* and `break`, `retest`
    and `flip` are *continuations*, so a bar can carry two readings pointing
    opposite ways. Taking the first in list order would be inventing the sign
    the family is supposed to assert, so a disagreement is no signal.
    """
    from till_infinity.strategies.crossing import side_of

    class _Zone:
        at = 1
        top = 110.0
        bottom = 100.0
        resistance = True
        flipped = True

    zone = _Zone()
    # Left the zone downward: `reject` says sell. The role has just changed,
    # so `flip` says buy. They disagree, so the zone says nothing.
    assert side_of(zone, "reject", was=True, now=False, close=99.0, seen=False) == -1
    assert side_of(zone, "flip", was=True, now=False, close=99.0, seen=False) == +1
    assert side_of(zone, "all", was=True, now=False, close=99.0, seen=False) == 0

    # Closed through from outside and the flip is already reported: only
    # `break` fires, and `all` is that one reading.
    assert side_of(zone, "all", was=False, now=False, close=120.0, seen=True) == +1
