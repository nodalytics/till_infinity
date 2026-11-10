"""Warming from history: how long a bar is, and what counts as fresh.

**The first test here is a regression and it found a live bug.** The version
`warming.bar_seconds` replaced read `str(spec.aggregation)` and compared it
against `"MINUTE"`, `"HOUR"` and so on - but `BarSpecification.aggregation` is
an **int** (12 MINUTE, 13 HOUR, 14 DAY), so every branch missed and the
fallback returned `step * 900`. An M15 bar read **13,500 seconds for a
900-second bar** and had done since the warm request was written, unnoticed
because the only consumer was a request *window*: asking for 156 days of
history instead of 10 and taking the same `limit` of bars looks identical from
outside.

It stops being harmless the moment a freshness window is measured in bar
spans. That is exactly what this change added, so the number is asserted
rather than the behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from nautilus_trader.model.data import BarType

from till_infinity.strategies.warming import DEFAULT_FRESH_BARS, WarmFromHistory, bar_seconds


@pytest.mark.parametrize(
    ("spelling", "seconds"),
    [
        ("EURUSD.SIM-1-MINUTE-LAST-EXTERNAL", 60.0),
        ("EURUSD.SIM-15-MINUTE-LAST-EXTERNAL", 900.0),
        ("EURUSD.SIM-30-MINUTE-LAST-EXTERNAL", 1_800.0),
        ("EURUSD.SIM-1-HOUR-LAST-EXTERNAL", 3_600.0),
        ("EURUSD.SIM-4-HOUR-LAST-EXTERNAL", 14_400.0),
        ("EURUSD.SIM-1-DAY-LAST-EXTERNAL", 86_400.0),
    ],
)
def test_a_bar_span_is_the_number_it_says_and_not_a_fallback(spelling, seconds):
    """Every interval the node can subscribe to, against the literal number.

    Asserted as literals and not as `step * unit`, because the bug being
    pinned was a unit that silently became 900 - a test computing the expected
    value the same way the code does would have passed throughout.
    """
    assert bar_seconds(BarType.from_str(spelling)) == seconds


def test_a_composite_bar_type_reads_its_own_span_and_not_its_sources():
    """A composite names what it was aggregated *from* after an `@`, and
    `structure.py` runs one in a backtest. The span is the primary spec's: a
    15-minute bar built from 1-minute bars is still a 15-minute bar, and
    reading the source would make the warm window sixty times too narrow."""
    composite = BarType.from_str("XAU/USD.SIM-15-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL")
    assert bar_seconds(composite) == 900.0


def test_a_symbol_containing_a_hyphen_does_not_confuse_the_span():
    """`ETHUSDT-PERP.BINANCE` - the split has to come from the right, and a
    left split once read a step of `PERP.BINANCE`."""
    assert bar_seconds(BarType.from_str("ETHUSDT-PERP.BINANCE-1-HOUR-LAST-EXTERNAL")) == 3_600.0


# ------------------------------------------------------------- freshness


class Warm(WarmFromHistory):
    """A bare host for the mixin's own logic, with a settable clock."""

    def __init__(self, now_ns: int, span: float, allowed: int) -> None:
        self.clock = SimpleNamespace(timestamp_ns=lambda: now_ns)
        self.profile = SimpleNamespace(warm_fresh_bars=allowed, warm_bars_request=0)
        self._span = span

    def warm_seconds(self) -> float:
        return self._span


def at(ts_ns: int):
    return SimpleNamespace(ts_event=ts_ns)


def test_a_bar_inside_the_window_is_fresh_and_one_outside_it_is_not():
    """The boundary, both sides, because a signal's price having moved on is a
    question about elapsed time and this is where the line is drawn."""
    span, now = 900.0, 10_000 * 10**9
    warm = Warm(now, span, allowed=1)

    assert warm.fresh(at(now)) is True, "a bar closing now"
    assert warm.fresh(at(now - int(0.9 * span * 10**9))) is True, "inside one span"
    assert warm.fresh(at(now - int(1.5 * span * 10**9))) is False, "past one span"


def test_the_window_is_counted_in_bars_so_it_follows_the_clock():
    """One span on M15 is fifteen minutes and on 4h is four hours. A window in
    seconds would be fifteen times too strict on one of them."""
    now = 10_000_000 * 10**9
    age = 3_000 * 10**9  # fifty minutes
    assert Warm(now, 900.0, allowed=1).fresh(at(now - age)) is False, "over three M15 bars"
    assert Warm(now, 14_400.0, allowed=1).fresh(at(now - age)) is True, "well inside one 4h bar"


def test_a_zero_window_refuses_even_a_bar_stamped_now():
    """The escape hatch `zones` and the origin rules use: their signal is a
    transition between two bars rather than an event with a timestamp, so a
    replayed crossing is one the rule has already passed on."""
    now = 10_000 * 10**9
    assert Warm(now, 900.0, allowed=0).fresh(at(now)) is False


def test_a_bar_stamped_after_now_does_not_read_as_fresh_by_a_margin():
    """A bar closing in the future is a clock disagreement, and the only safe
    reading of one is zero age rather than a widened window - a negative age
    would make `fresh` true for anything, however stale, if the clocks drifted
    the other way."""
    now = 10_000 * 10**9
    warm = Warm(now, 900.0, allowed=1)
    assert warm.warm_age(at(now + 10**12)) == 0.0
    assert warm.fresh(at(now + 10**12)) is True, "zero age is inside any window"


def test_the_default_window_is_one_bar():
    """Stated as a constant so a rule that wants another says so, and so the
    number a result was taken under is readable."""
    assert DEFAULT_FRESH_BARS == 1


def test_a_rules_own_warm_counters_survive_the_request():
    """**`structure.py` sets up a richer `warmed` before `super().on_start()`**
    - breaks, bos, choch - and `start_warming` runs after it. Assigning a fresh
    dict there would discard them, and the tally subtracts warm from pooled, so
    every warm break would have read as live."""

    class Rich(Warm):
        def __init__(self) -> None:
            super().__init__(0, 900.0, allowed=1)
            self.warmed = {"bars": 0, "bos": 3, "choch": 1}

    rule = Rich()
    rule.start_warming()
    assert rule.warmed["bos"] == 3
    assert rule.warmed["choch"] == 1
    assert rule.warmed["bars"] == 0


def test_a_profile_asking_for_no_history_requests_nothing():
    """A rule whose detector is stateless gains nothing from a request and
    would pay for it. `start_warming` returns before touching the venue, which
    is asserted by the absence of a `request_bars` attribute on this host -
    calling one would raise."""
    warm = Warm(0, 900.0, allowed=1)
    warm.start_warming()
    assert warm.warmed == {"bars": 0}


# --------------------------------------------- the mixin must not be shadowed


def test_every_warming_rule_resolves_the_mixins_handler_and_not_nautilus_no_op():
    """**Base order decides whether warming happens at all, silently.**

    `Desk` inherits `Actor.on_historical_data`, which is a no-op. So
    `class Rule(Desk, WarmFromHistory)` resolves the no-op: the requests are
    issued, the venue answers, every bar is dropped on the floor, and the rule
    reports healthy while staying exactly as cold as before. `identity-arb` was
    written that way and this check is what found it - its handler resolved to
    `Actor` until the bases were swapped to put the mixin first.

    Asserted over every registered rule rather than the ones known to warm, so
    a rule that gains the mixin later cannot gain it in the wrong position.
    """
    from till_infinity.strategies import leaves
    from till_infinity.strategies.warming import WarmFromHistory

    checked = 0
    for rule, entry in leaves.LEAVES:
        cls = leaves.LEAVES[(rule, entry)]
        if not issubclass(cls, WarmFromHistory):
            continue
        checked += 1
        owner = next(
            (base.__name__ for base in cls.__mro__ if "on_historical_data" in base.__dict__),
            None,
        )
        assert owner == "WarmFromHistory", (
            f"{rule}/{entry} resolves on_historical_data to {owner}: its warm "
            f"requests would be answered and silently discarded. Put "
            f"WarmFromHistory before Desk in the bases."
        )
    assert checked >= 5, f"only {checked} leaves use the mixin - is this test still pinning it?"


def test_a_rule_that_reads_one_instrument_asks_for_one_bar_type():
    """The default, so only a multi-instrument rule overrides it."""
    warm = Warm(0, 900.0, allowed=1)
    warm._cfg = SimpleNamespace(bar_type="EURUSD.SIM-15-MINUTE-LAST-EXTERNAL")
    assert warm.warm_bar_types() == ["EURUSD.SIM-15-MINUTE-LAST-EXTERNAL"]


def test_the_triangle_asks_for_all_three_of_its_legs():
    """`identity-arb`'s residual needs the cross and both partners at the same
    bar, so warming the traded leg alone would leave `_residual` returning None
    for the whole replay - the rule would look warm while holding no residuals.
    """
    from till_infinity.strategies.identity import Identity

    host = SimpleNamespace(
        trio=("EURGBP", "EURUSD", "GBPUSD"),
        _cfg=SimpleNamespace(
            bar_type=__import__(
                "nautilus_trader.model.data", fromlist=["BarType"]
            ).BarType.from_str("EURGBP.SIM-15-MINUTE-LAST-EXTERNAL")
        ),
    )
    found = [str(b) for b in Identity.warm_bar_types(host)]
    assert found == [
        "EURGBP.SIM-15-MINUTE-LAST-EXTERNAL",
        "EURUSD.SIM-15-MINUTE-LAST-EXTERNAL",
        "GBPUSD.SIM-15-MINUTE-LAST-EXTERNAL",
    ]


def test_a_triangle_with_no_partners_asks_only_for_its_own_leg():
    """The control: a symbol with no triangle logs that it can never trade, and
    must not build bar types out of a None."""
    from till_infinity.strategies.identity import Identity

    host = SimpleNamespace(trio=None, _cfg=SimpleNamespace(bar_type="X"))
    assert Identity.warm_bar_types(host) == ["X"]
