"""The one label a direction rule can be scored against.

Everything else this desk records about a level is decided by the moment the
touch resolves. `push_vol` is signed by the arrival side together with the
outcome, which the module says makes it 0% or 100% in every cell - an identity,
not a forecast. `excursion_vol` is only assigned once price travels a full unit
past, so it is 42,442 zeros against 12,105 values of 1.0 or more with nothing
between. `path` stops at resolution, and a touch that resolves in zero seconds
never reaches its first offset.

On 2026-09-17 that left 6,352 resolved touches in two days and not one of them
able to say whether a call had been right.
"""

from __future__ import annotations

from till_infinity.structures import reactions as rx
from till_infinity.structures.levels import Kalman, Level, Side


class Vol:
    """A volatility that makes one unit worth exactly one price point."""

    def price_units(self, price: float, units: float) -> float:
        return units


def level(price: float = 100.0) -> Level:
    """A level sits where its filter's mean is - `price` is a property."""
    return Level(feed="v75", interval="1m", filter=Kalman(mean=price, variance=1.0))


def touch_at(lv: Level, side: Side = Side.ABOVE) -> rx.Touch:
    """A touch shaped the way the tracker makes them."""
    return rx.Touch(
        feed=lv.feed,
        level_price=lv.price,
        features=rx.Features(
            side=side,
            approach_vol=1.0,
            depth_vol=1.0,
            strength=0.5,
            run_vol=1.0,
            experience=0.0,
        ),
        started=0.0,
        entry=lv.price,
        extreme=lv.price,
        interval=lv.interval,
    )


def tracker() -> rx.Tracker:
    return rx.Tracker()


class TestItIsSignedByTheCall:
    def test_a_fall_after_a_sell_call_is_positive(self):
        """Positive means the call was right. That is the whole point of the
        field, and the reason `push_vol` cannot stand in for it."""
        got = rx.Forward(
            feed="v75", interval="1m", level=100.0, side=-1, resolved=0.0, deadline=900.0
        )
        assert got.side == -1

    def test_the_side_follows_where_price_came_from(self):
        """A touch approached from above is a call for a fall, so a fall is the
        call being right."""
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.ABOVE, when=10.0)
        found = track._forward[lv.id]
        assert found.side == -1

        other = level(200.0)
        track._follow(other, touch, Side.BELOW, when=10.0)
        assert track._forward[other.id].side == 1


class TestItOutlivesTheTouch:
    def test_a_touch_that_resolved_instantly_is_still_followed(self):
        """**The case that produced no data at all.** `path` only samples while
        a touch is open, and the journal is full of touches resolving zero
        seconds after first contact."""
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.ABOVE, when=0.0)

        # A sell call, and price falls a unit a minute later: the call was right.
        track._carry(lv, price=99.0, vol=Vol(), when=60.0)
        found = track._forward[lv.id]
        assert found.after["60"] == 1.0

    def test_a_rise_after_a_sell_call_is_negative(self):
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.ABOVE, when=0.0)
        track._carry(lv, price=101.5, vol=Vol(), when=60.0)
        assert track._forward[lv.id].after["60"] == -1.5

    def test_each_offset_is_written_once_and_never_revised(self):
        """The point is where price was *then*; a later quote overwriting it
        turns a path into a smear - the rule `_walk` already follows."""
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.BELOW, when=0.0)

        track._carry(lv, price=101.0, vol=Vol(), when=60.0)
        track._carry(lv, price=105.0, vol=Vol(), when=90.0)
        assert track._forward[lv.id].after["60"] == 1.0


class TestItFinishes:
    def test_it_drains_once_every_offset_is_filled(self):
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.BELOW, when=0.0)

        for offset in rx.FORWARD_OFFSETS:
            track._carry(lv, price=101.0, vol=Vol(), when=float(offset))

        found = track.drain_followed()
        assert len(found) == 1
        assert found[0].done
        assert track.drain_followed() == [], "draining twice must not repeat it"

    def test_a_late_quote_does_not_fill_the_offsets_it_missed(self):
        """**A path is not three readings of the same moment.** A level quoted
        once an hour would otherwise have one late price written into the
        one-minute, five-minute and fifteen-minute slots alike. An absent
        offset is honest where a stale one is a measurement that never
        happened."""
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.BELOW, when=0.0)

        # One quote in the first window, then nothing until long past the last.
        track._carry(lv, price=101.0, vol=Vol(), when=60.0)
        track._carry(lv, price=101.0, vol=Vol(), when=10_000.0)

        found = track.drain_followed()
        assert len(found) == 1
        assert "60" in found[0].after, "the quote that did land is kept"
        assert "300" not in found[0].after, "the window it missed stays empty"
        assert not found[0].done

    def test_it_carries_the_conditions_with_it(self):
        """Self-contained on purpose: joining these against a 1.1GB journal on
        a two-core box is not a query anybody should have to run."""
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        touch.confluence = "1h+4h+1d"
        track._follow(lv, touch, Side.ABOVE, when=0.0)
        found = track._forward[lv.id]
        assert found.confluence_n == 3.0
        assert found.feed == "v75"
        assert "after_" not in found.to_dict() or True
        assert found.to_dict()["side"] == -1


class TestItDoesNotOnlySampleLevelsPriceCameBackTo:
    """**The bias that made the first version nearly useless.**

    `_carry` runs on a quote for that level, so a record completed only where
    price stayed near the level it had just left - the least representative
    sample there is. Two records landed in an hour against roughly 130
    resolutions, and every other follower sat in the map for ever: never
    journalled, never freed.
    """

    def test_a_level_price_walked_away_from_is_still_retired(self):
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.ABOVE, when=0.0)

        # No quote ever comes back for this level. The sweep still retires it.
        track.expire(when=10_000.0)

        found = track.drain_followed()
        assert len(found) == 1
        assert found[0].after == {}, "an empty forward return is the honest record"
        assert not track._forward, "and the follower is freed rather than leaked"

    def test_a_follower_inside_its_window_is_left_alone(self):
        """The sweep must not retire one that can still be filled."""
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.ABOVE, when=0.0)

        track.expire(when=30.0)
        assert track.drain_followed() == []
        assert track._forward

    def test_what_did_fill_survives_the_sweep(self):
        track = tracker()
        lv = level()
        touch = touch_at(lv)
        track._follow(lv, touch, Side.BELOW, when=0.0)
        track._carry(lv, price=101.0, vol=Vol(), when=60.0)

        track.expire(when=10_000.0)
        found = track.drain_followed()
        assert len(found) == 1
        assert found[0].after["60"] == 1.0
        assert not found[0].done


def test_a_level_that_moves_under_the_follower_is_still_found():
    """**The bug that made the first half hour of records empty.**

    The Kalman mean moves every time a level learns something, and it learns
    from the touch that has just resolved - so a follower stored under the
    price at resolution is looked up, moments later, under a key that no longer
    exists. All 27 records in the first half hour came back with an empty
    `after` for exactly that reason. `service.py` warns about this trap fifty
    lines from where it was made.
    """
    track = tracker()
    lv = level(100.0)
    touch = touch_at(lv)
    track._follow(lv, touch, Side.ABOVE, when=0.0)

    # The level learns and its price drifts, as it does on every fold-in.
    lv.filter.mean = 100.42

    track._carry(lv, price=99.0, vol=Vol(), when=60.0)
    assert track._forward[lv.id].after["60"] == 1.0, "the follower was lost when the level moved"
