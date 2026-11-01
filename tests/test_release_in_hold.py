"""A release inside the trade's planned hold, not merely near its entry.

`news_before`/`news_after` refuse entries from 10 minutes before a high-impact
print to 15 after. That window is about the *entry*, and a trade has a duration:
a 15m signal meant to be held two hours can open 11 minutes before the print -
clearing the blackout by one minute - and hold straight through it. Research
found those held-through trades were the ones that did worse: 32 of 36 ensemble
rows, by a median 0.19R - the only input in `directional-questions.md` that
changed outcomes at all.

The direction is the strong part of that; 0.19R is a median across rows, not a
calibrated per-trade cost. Which is why this refuses rather than shrinks, and
why it is off by default. The tests below pin
the boundary conditions, because a gate whose boundary is wrong is worse than no
gate: it refuses trades it has no evidence about.
"""

from __future__ import annotations

import datetime as dt

from till_infinity.domain.models import Intent, Side
from till_infinity.risk.guard import Guard
from till_infinity.strategies import Settings
from till_infinity.strategies.context import Context
from till_infinity.utils import effects

HOUR = 3600.0


def at(hour: int = 12) -> float:
    """A timestamp on a fixed day, well away from any quiet hour."""
    return dt.datetime(2026, 9, 21, hour, 30, tzinfo=dt.UTC).timestamp()


def context(*releases: tuple[str, float, str]) -> Context:
    """A context holding these (country code, when, title) high-importance rows."""
    made = Context()
    for i, (country, when, title) in enumerate(releases):
        made.observe_event(
            {
                "source": "test",
                "id": i,
                "importance": 2,
                "time": when,
                "country": country,
                "title": title,
            }
        )
    return made


def desk(ctx: Context | None = None, **over) -> Guard:
    made = Settings()
    made.release_in_hold = True
    for k, v in over.items():
        setattr(made, k, v)
    guard = Guard(made.envelope(), context=ctx, currency="USD")
    guard.roll(10_000.0, now=at(9))
    return guard


def intent() -> Intent:
    return Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4390.0,
        target=4420.0,
        interval="15m",
        risk_money=22.0,
    )


def gate(guard: Guard, *, hold: float, now: float):
    return guard.allows(intent(), positions=[], now=now, hold=hold)


# ------------------------------------------------------------------ the gate


def test_a_release_inside_the_hold_refuses():
    """The finding itself. Both halves of the detail are asserted because both
    reach a human: the refusal goes in the journal, and "40m" with a title is
    what lets somebody decide later whether the gate was right."""
    now = at()
    # 40 minutes out: past the 10-minute blackout, inside a two-hour hold.
    ctx = context(("US", now + 40 * 60, "Nonfarm Payrolls"))
    stopped = gate(desk(ctx), hold=2 * HOUR, now=now)
    assert stopped is not None
    assert stopped.gate == "release_in_hold"
    assert "40m" in stopped.detail
    assert "Nonfarm Payrolls" in stopped.detail


def test_a_release_just_past_the_hold_is_not_refused():
    """One minute past, so the gate is being held to its own boundary and not
    to a comfortable margin either side of it. The pair with the test above is
    the whole assertion: a gate that refused both would look identical on the
    one above."""
    now = at()
    ctx = context(("US", now + 2 * HOUR + 60, "Nonfarm Payrolls"))
    assert gate(desk(ctx), hold=2 * HOUR, now=now) is None


def test_the_boundary_is_inclusive_at_the_hold():
    """A print landing exactly when we mean to be out still lands in the hold."""
    now = at()
    ctx = context(("US", now + 2 * HOUR, "CPI"))
    stopped = gate(desk(ctx), hold=2 * HOUR, now=now)
    assert stopped is not None
    assert stopped.gate == "release_in_hold"


def test_a_release_in_another_currency_is_ignored():
    """Gold is a dollar instrument; a New Zealand print is not its problem."""
    now = at()
    ctx = context(("NZ", now + 40 * 60, "RBNZ Rate Decision"))
    assert gate(desk(ctx), hold=2 * HOUR, now=now) is None


def test_a_release_already_past_is_not_this_gate():
    """Behind us is `news`'s business. This one is strictly forward-looking."""
    now = at()
    ctx = context(("US", now - 40 * 60, "CPI"))
    assert gate(desk(ctx), hold=2 * HOUR, now=now) is None


def test_the_earliest_release_is_the_one_reported():
    """The first print is the one the trade cannot avoid, and the detail is
    read by somebody deciding whether to override. Naming the FOMC Minutes
    ninety minutes out, when CPI lands in twenty, points them at the wrong
    calendar entry."""
    now = at()
    ctx = context(
        ("US", now + 90 * 60, "FOMC Minutes"),
        ("US", now + 20 * 60, "CPI"),
    )
    stopped = gate(desk(ctx), hold=2 * HOUR, now=now)
    assert stopped is not None
    assert "CPI" in stopped.detail


# --------------------------------------------------------------------- limits


def test_the_cap_bounds_how_far_ahead_it_looks():
    """A daily swing is not refused for a print two days out."""
    now = at()
    ctx = context(("US", now + 8 * HOUR, "CPI"))
    # A five-day hold, but the cap is four hours, so an 8-hour-out print is
    # beyond what any measurement covers.
    assert gate(desk(ctx), hold=5 * 24 * HOUR, now=now) is None


def test_inside_the_cap_a_long_hold_still_refuses():
    """The cap shortens the reach, it does not switch the gate off. A five-day
    hold with a print three hours out is refused, and the detail says "ahead"
    because the number quoted is the cap's and not the hold's - a refusal
    citing five days for a three-hour print reads as a bug."""
    now = at()
    ctx = context(("US", now + 3 * HOUR, "CPI"))
    stopped = gate(desk(ctx), hold=5 * 24 * HOUR, now=now)
    assert stopped is not None
    assert stopped.gate == "release_in_hold"
    # It should say it looked less far than the hold, or the number confuses.
    assert "ahead" in stopped.detail


def test_the_cap_can_be_widened_without_touching_the_gate():
    """The cap is a bound on what the measurement covers, not a finding, so it
    is the part an operator is expected to move."""
    now = at()
    ctx = context(("US", now + 8 * HOUR, "CPI"))
    guard = desk(ctx, release_hold_cap_s=12 * HOUR)
    stopped = gate(guard, hold=5 * 24 * HOUR, now=now)
    assert stopped is not None
    assert stopped.gate == "release_in_hold"


def test_a_trade_with_no_stated_hold_is_not_gated():
    """`hold=0` means nobody told us, and guessing would refuse everything."""
    now = at()
    ctx = context(("US", now + 40 * 60, "CPI"))
    assert gate(desk(ctx), hold=0.0, now=now) is None


def test_a_guard_with_no_calendar_fails_open():
    """**The direction matters more than the gate does.** A news feed that has
    not loaded, or a backtest with no calendar at all, is the normal state for
    most of this desk - and a gate that refused on a missing context would
    stop every trade on every node that does not carry one, which is an outage
    that looks like a quiet market."""
    now = at()
    assert gate(desk(None), hold=2 * HOUR, now=now) is None


# ------------------------------------------------------------------- default


def test_the_gate_is_off_as_shipped():
    """Not a default chosen here. 0.19R is a median across 32 of 36 rows, not
    a per-trade cost, so the direction is the finding and the size is not -
    and a gate switched on by this measurement would refuse trades it has no
    evidence about. The `False` below is the shipped answer, asserted so a
    change to it is a decision somebody takes.
    """
    now = at()
    ctx = context(("US", now + 40 * 60, "CPI"))
    off = Settings()
    assert off.release_in_hold is False
    guard = Guard(off.envelope(), context=ctx, currency="USD")
    guard.roll(10_000.0, now=at(9))
    assert guard.allows(intent(), positions=[], now=now, hold=2 * HOUR) is None


# ------------------------------------------------------------------ ordering


def test_being_inside_the_window_is_still_reported_as_news():
    """When both apply, `news` is the more specific thing to say."""
    now = at()
    # Five minutes out: inside the 10-minute blackout *and* inside the hold.
    ctx = context(("US", now + 5 * 60, "CPI"))
    stopped = gate(desk(ctx), hold=2 * HOUR, now=now)
    assert stopped is not None
    assert stopped.gate == "news"


# -------------------------------------------------------------------- effects


def test_it_declares_and_fires_its_effect():
    """A gate that is on and refuses nothing looks exactly like one that works."""
    effects.reset()
    now = at()
    ctx = context(("US", now + 40 * 60, "CPI"))
    guard = desk(ctx)
    effects.declare("trading.release_in_hold", enabled=True)

    assert "trading.release_in_hold" in effects.report()
    stopped = gate(guard, hold=2 * HOUR, now=now)
    assert stopped is not None

    declared = effects.report()["trading.release_in_hold"]
    assert declared["count"] >= 1
    assert "trading.release_in_hold" not in effects.inert(grace=0.0)


# ---------------------------------------------------------------- Context.ahead


def test_a_zero_horizon_looks_ahead_at_nothing():
    """`hold=0` reaches `ahead` as a zero horizon, and a window of no width
    that still matched the next print would refuse every trade that did not
    state a hold."""
    now = at()
    ctx = context(("US", now + 60, "CPI"))
    assert ctx.ahead("gold", 0.0, now) is None


def test_a_feed_with_no_currency_has_no_releases_of_its_own():
    """Releases are matched by the instrument's currencies, so a feed that
    resolves to none has nothing to match - and matching everything instead
    would make one unnamed feed refuse on every country's calendar."""
    now = at()
    ctx = context(("US", now + 60, "CPI"))
    assert ctx.ahead("", 2 * HOUR, now) is None


def test_a_release_inside_the_horizon_is_found_and_named():
    """The power assertion for the three above: without it, an `ahead` that
    always returned `None` would satisfy all of them."""
    now = at()
    ctx = context(("US", now + 60 * 60, "CPI"))
    found = ctx.ahead("gold", 2 * HOUR, now)
    assert found is not None
    assert found.title == "CPI"
