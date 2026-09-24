"""The calendar must survive arriving in date order.

Both providers publish the week ahead chronologically. `Context.observe_event` used to prune
against the *stored* row's own time, so the furthest-out release arrived last and deleted
every release before it: fed one real week, 1 of 27 survived and neither the news blackout
nor the release-in-hold gate fired before Non-Farm Payrolls. Pruning now happens when a
question is asked, against the time asked about. See research/docs/leads-and-live-book.md.
"""

from __future__ import annotations

from till_infinity.trading.context import Context

HOUR = 3_600.0
NFP = 1_790_000_000.0


def row(i: int, when: float, country: str = "US", importance: int = 2) -> dict:
    return {
        "source": "forexfactory",
        "id": f"e{i}",
        "time": when,
        "country": country,
        "importance": importance,
        "title": f"release {i}",
    }


def week(order: str = "date") -> list[dict]:
    """A release every six hours from three days before NFP to four days after."""
    rows = [row(i, NFP + k * 6 * HOUR) for i, k in enumerate(range(-12, 17))]
    return rows if order == "date" else list(reversed(rows))


def fed(rows: list[dict]) -> Context:
    context = Context()
    for r in rows:
        context.observe_event(r)
    return context


def test_a_week_in_date_order_keeps_every_release():
    """The defect: this used to keep one."""
    context = fed(week("date"))
    assert len(context.upcoming(now=NFP - 4 * 24 * HOUR)) == len(week())


def test_the_blackout_fires_before_a_print_whatever_order_the_week_arrived_in():
    for order in ("date", "newest-first"):
        context = fed(week(order))
        assert context.blackout("eurusd", now=NFP - 300) is not None, order


def test_the_release_gate_sees_a_print_inside_the_hold_whatever_the_order():
    for order in ("date", "newest-first"):
        context = fed(week(order))
        coming = context.ahead("eurusd", 2 * HOUR, now=NFP - HOUR)
        assert coming is not None, order
        assert coming.when == NFP, order


def test_the_calendar_still_forgets_what_has_passed():
    """Pruning moved, it did not stop: a release whose window closed is dropped the
    next time anything is asked, so the book cannot grow for ever."""
    context = fed(week("date"))
    later = NFP + 5 * 24 * HOUR
    context.blackout("eurusd", now=later)
    assert all(r.when >= later - context.after - HOUR for r in context._events.values())


def test_a_replayed_moment_sees_its_own_releases():
    """Pruning is against the moment asked about, not the wall clock - a replay of a past
    week must see that week's calendar."""
    context = fed(week("date"))
    assert context.ahead("eurusd", 2 * HOUR, now=NFP - HOUR) is not None


def test_storing_a_row_never_deletes_another():
    context = Context()
    context.observe_event(row(1, NFP))
    context.observe_event(row(2, NFP + 7 * 24 * HOUR))
    assert len(context._events) == 2
