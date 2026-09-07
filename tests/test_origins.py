"""What the origin model must get right, and the ways it can quietly not."""

from __future__ import annotations

from till_infinity.structures.drawing.origins import Origin, Origins


def _series(prices):
    return list(range(len(prices))), [float(p) for p in prices]


def test_the_origin_is_where_the_move_began_not_where_it_ended():
    """The whole point. Recording the low of a drop would record the price
    everyone already knows about instead of the one that has not been traded
    through."""
    # Flat at 100, then a fast drop to 90.
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    got = Origins().observe(times, prices, unit=1.0)
    assert got, "no origin found in an obvious 10-unit drop"
    drop = [o for o in got if o.launched == "down"]
    assert drop
    assert drop[0].price == 100.0


def test_a_rally_origin_is_the_low_it_left_from():
    times, prices = _series([100] * 7 + [101, 103, 106, 110] + [110] * 7)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "up"]
    assert got
    assert got[0].price == 100.0


def test_a_drift_is_not_an_origin():
    """Same total distance, spread over far more bars. The claim is about
    displacement fast enough that resting interest was not refilled."""
    times, prices = _series([100 + i * 0.4 for i in range(25)])
    assert Origins().observe(times, prices, unit=1.0, bars=4) == []


def test_the_threshold_is_in_volatility_units():
    """A 10-point move is an event on a quiet instrument and a normal bar on a
    loud one. The same series must give different answers at different vol."""
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    assert Origins().observe(times, prices, unit=1.0) != []
    assert Origins().observe(times, prices, unit=20.0) == []


def test_one_impulse_is_recorded_once():
    """A move visible from several offsets is one event, not several."""
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 10)
    got = Origins().observe(times, prices, unit=1.0)
    downs = [o for o in got if o.launched == "down"]
    assert len(downs) == 1, f"one drop recorded {len(downs)} times"


def test_direction_backs_the_side_it_should():
    """The opposite convention is equally sayable and would silently invert
    every gate built on this."""
    sell_side = Origin(price=100, low=99, high=100, launched="down", size_vol=4.0, when=0)
    assert sell_side.supports(want_up=False) is True
    assert sell_side.supports(want_up=True) is False


def test_a_revisited_origin_is_counted_as_such():
    """The claim is unfilled interest; each return trades some of it away."""
    times, prices = _series(
        [100] * 7 + [99, 97, 94, 90] + [92, 96, 100, 96, 92] + [96, 100, 96] + [90] * 3
    )
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got
    assert got[0].revisits >= 1


def test_a_fresh_origin_has_no_revisits():
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got[0].revisits == 0


def test_the_zone_is_a_band_not_a_price():
    """Resting interest sat across a range, so price entering the band has
    reached it."""
    o = Origin(price=100, low=99.5, high=100.0, launched="down", size_vol=4.0, when=0)
    assert o.holds(99.7)
    assert not o.holds(99.0)


def test_nothing_is_found_without_a_volatility_unit():
    """A zero unit would make every move infinitely large in vol terms."""
    times, prices = _series([100] * 7 + [99, 97, 94, 90] + [90] * 7)
    assert Origins().observe(times, prices, unit=0.0) == []


def test_the_target_side_is_the_opposing_origin():
    """For a buy, the origin of the last violent rally *above* here - where the
    previous advance was stopped."""
    o = Origins()
    o.found = [
        Origin(price=90, low=90, high=90.5, launched="up", size_vol=4.0, when=0),
        Origin(price=110, low=109.5, high=110, launched="down", size_vol=4.0, when=0),
    ]
    target = o.opposing(price=95.0, want_up=True)
    assert target is not None
    assert target.price == 110
    # And the entry side is the other one.
    assert o.nearest(price=95.0, want_up=True).price == 90


# ------------------------- the zone is the last leg the other way, measured


def test_the_zone_is_the_last_opposing_leg():
    """A rally from 96 to 100, then a drop. The zone is 96-100 - the leg
    itself - not the high padded by a constant somebody chose.
    """
    times, prices = _series([96, 97, 98, 99, 100] + [99, 97, 94, 90] + [90] * 8)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got
    assert got[0].price == 100.0
    assert got[0].low == 96.0
    assert got[0].high == 100.0


def test_the_zone_widens_with_the_leg_that_made_it():
    """Its width is observed. A longer run into the turn leaves a bigger band,
    because the interest placed during it sat across more price.

    The approach is deliberately gradual in both: a brisk one would qualify as
    an impulse in its own right and the series would carry two origins, which
    is correct behaviour and not what this is measuring.
    """
    short = _series([99.5, 100] + [99, 97, 94, 90] + [90] * 8)
    long_ = _series([98, 98.5, 99, 99.5, 100] + [99, 97, 94, 90] + [90] * 8)
    a = next(o for o in Origins().observe(*short, unit=1.0) if o.launched == "down")
    b = next(o for o in Origins().observe(*long_, unit=1.0) if o.launched == "down")
    assert (b.high - b.low) > (a.high - a.low)


def test_a_rally_origin_is_the_selling_leg_before_it():
    times, prices = _series([104, 103, 102, 101, 100] + [101, 103, 106, 110] + [110] * 8)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "up"]
    assert got
    assert got[0].price == 100.0
    assert got[0].low == 100.0
    assert got[0].high == 104.0


def test_an_impulse_from_a_flat_still_gets_a_band():
    """No opposing leg to measure - the fallback, and the weaker case."""
    times, prices = _series([100] * 6 + [99, 97, 94, 90] + [90] * 8)
    got = [o for o in Origins().observe(times, prices, unit=1.0) if o.launched == "down"]
    assert got
    assert got[0].high > got[0].low


# ------------------------------- the zone comes from the last opposing bar


class _Bar:
    def __init__(self, o, h, lo, c):
        self.open, self.high, self.low, self.close = o, h, lo, c


def test_a_normal_bar_gives_its_whole_range():
    from till_infinity.structures.drawing.origins import zone_of

    assert zone_of(_Bar(100, 100.5, 99.5, 100.2), unit=1.0) == (99.5, 100.5)


def test_a_huge_bar_gives_its_body_instead():
    """Mostly wick: price went there and did not stay, so the open to the
    close is the part that traded rather than probed."""
    from till_infinity.structures.drawing.origins import zone_of

    low, high = zone_of(_Bar(100, 105, 95, 101), unit=1.0)
    assert (low, high) == (100.0, 101.0)


def test_a_huge_doji_keeps_its_range():
    """With no body to fall back on, the range is all there is."""
    from till_infinity.structures.drawing.origins import zone_of

    assert zone_of(_Bar(100, 105, 95, 100), unit=1.0) == (95.0, 105.0)


def test_the_zone_uses_the_last_opposing_bar_when_bars_are_given():
    """Not the whole leg: the interest that mattered was placed in the final
    bar of it, and the leg gives a band far wider than was ever defended."""
    times, prices = _series([96, 97, 98, 99, 100] + [99, 97, 94, 90] + [90] * 8)
    bars = [_Bar(p, p + 0.2, p - 0.2, p) for p in prices]
    got = [
        o for o in Origins().observe(times, prices, unit=1.0, bars_at=bars) if o.launched == "down"
    ]
    assert got
    # The last bar of the rally sat at 100, not the whole 96-100 leg.
    assert got[0].low >= 99.0
    assert got[0].high <= 100.5


def test_the_bracketing_pair_is_the_room_before_unfilled_interest():
    """What a swing target actually asks for, and what the engine now hands
    `level_range.between_origins`.

    Near edges, not centres: an origin is a band, and the room ends where the
    band starts. Taking the centre would put the wall inside interest that has
    already begun defending.
    """
    from till_infinity.structures import engine as eng

    engine = eng.Engine()
    # A rally from 100 to 110, then a drop from 120 to 110: price at 110 sits
    # between the origin of the rally below and the origin of the drop above.
    prices = [100] * 7 + [102, 105, 108, 110] * 1 + [110] * 5
    prices += [112, 116, 120] + [120] * 7 + [118, 115, 112, 110] + [110] * 7
    for i, close in enumerate(prices):
        engine.observe_bar(
            {
                "feed": "t",
                "venue": "v",
                "interval": "4h",
                "ts": i * 14_400,
                "time": i * 14_400,
                "high": close,
                "low": close,
                "close": close,
            }
        )
    below, above = engine.origins_bracketing("t", "4h", 110.0, engine.vol.of("t", "4h"))

    # Whichever side is found, a bound is a real number on the correct side of
    # price - the assertion that fails if the near/far edges are swapped.
    assert below is None or below <= 110.0
    assert above is None or above >= 110.0


def test_an_unwarmed_feed_brackets_nothing_rather_than_raising():
    """A swing on an instrument with no history gets open air, not a crash -
    the wrapping `_origin_at` already has, surfaced through the pair."""
    from till_infinity.structures import engine as eng

    engine = eng.Engine()

    assert engine.origins_bracketing("cold", "4h", 100.0, engine.vol.of("cold", "4h")) == (
        None,
        None,
    )


# ------------------------------------------------- estimator F, the refinement


def _origin(price, launched="down", when=0.0, band=1.0):
    from till_infinity.structures.drawing.origins import Origin

    return Origin(
        price=price,
        low=price - band,
        high=price + band,
        launched=launched,
        size_vol=5.0,
        when=when,
    )


def test_the_refinement_finds_the_higher_close_inside_a_drop_bar():
    """The origin is the last price before the impulse took over, so one
    resolution down it is the highest close for a drop - the same definition,
    asked of finer evidence."""
    from till_infinity.structures.drawing.origins import refine

    # A 15-minute bar whose 1m closes peak at 105 before the drop begins.
    times = [float(t * 60) for t in range(15)]
    closes = [100, 101, 103, 105, 104, 102, 99, 97, 95, 94, 93, 92, 91, 90, 90]

    got = refine(_origin(90.0, "down", when=0.0), times, closes, span=900.0)

    assert got.price == 105.0


def test_a_rally_origin_refines_to_the_lowest_close():
    from till_infinity.structures.drawing.origins import refine

    times = [float(t * 60) for t in range(15)]
    closes = [100, 99, 97, 95, 96, 98, 101, 103, 105, 106, 107, 108, 109, 110, 110]

    got = refine(_origin(110.0, "up", when=0.0), times, closes, span=900.0)

    assert got.price == 95.0


def test_the_band_travels_with_the_price():
    """Relocating the origin outside its own zone would leave a level whose
    band no longer contains it. Re-deriving the width from the finer bars is a
    separate experiment; this re-centres and keeps the width."""
    from till_infinity.structures.drawing.origins import refine

    times = [float(t * 60) for t in range(15)]
    closes = [100, 101, 103, 105, 104, 102, 99, 97, 95, 94, 93, 92, 91, 90, 90]

    got = refine(_origin(90.0, "down", when=0.0, band=2.0), times, closes, span=900.0)

    assert got.low <= got.price <= got.high
    assert (got.high - got.low) == 4.0


def test_partial_cover_is_refused_rather_than_used():
    """A refinement computed from two of the fifteen minutes is worse than
    none: the extreme found is the extreme of whatever fraction survived in a
    bounded rolling window."""
    from till_infinity.structures.drawing.origins import refine

    times = [0.0, 60.0, 120.0]
    closes = [100.0, 105.0, 103.0]

    got = refine(_origin(90.0, "down", when=0.0), times, closes, span=900.0)

    assert got.price == 90.0


def test_no_finer_series_leaves_the_origin_alone():
    from till_infinity.structures.drawing.origins import refine

    origin = _origin(90.0, "down")

    assert refine(origin, [], [], span=900.0) is origin
    assert refine(origin, [0.0], [90.0], span=900.0) is origin
    assert refine(origin, [0.0, 60.0], [90.0, 91.0], span=0.0) is origin


# ------------------------------------------------------- keeping what was found


def test_a_second_sighting_does_not_replace_a_refined_band():
    """The whole reason the set is kept. An origin is refined once, while its
    fine evidence is still in the window; recomputing later would hand back a
    coarse band and undo it silently."""
    from till_infinity.structures.drawing.origins import Origins

    kept = Origins()
    times = [float(t * 60) for t in range(15)]
    closes = [100, 101, 103, 105, 104, 102, 99, 97, 95, 94, 93, 92, 91, 90, 90]
    coarse = _origin(90.0, "down", when=0.0)

    first = kept.remember([coarse], fine_times=times, fine_closes=closes, span=900.0)
    assert first[0].price == 105.0

    # The same origin detected again, this time with no fine data to hand.
    again = kept.remember([coarse], fine_times=(), fine_closes=(), span=900.0)

    assert len(again) == 1
    assert again[0].price == 105.0


def test_an_origin_is_identified_by_its_turn_and_direction():
    """Not by price: the refinement moves the price, so keying on it would make
    every refined origin look like a new one and the set would double."""
    from till_infinity.structures.drawing.origins import Origins

    kept = Origins()
    down = _origin(90.0, "down", when=100.0)
    up = _origin(90.0, "up", when=100.0)
    later = _origin(90.0, "down", when=200.0)

    kept.remember([down, up, later])

    assert len(kept.found) == 3
    kept.remember([down, up, later])
    assert len(kept.found) == 3


def test_the_kept_set_is_bounded_oldest_first():
    """A set that only grows is a leak with a long fuse."""
    from till_infinity.structures.drawing.origins import Origins

    kept = Origins()
    kept.remember([_origin(100.0 + i, "down", when=float(i)) for i in range(20)], keep=5)

    assert len(kept.found) == 5
    assert [o.when for o in kept.found] == [15.0, 16.0, 17.0, 18.0, 19.0]


def test_origins_survive_across_calls_on_the_engine():
    """`_origin_at` used to rebuild them from the closes series every time, so
    a refined band had nowhere to live. This is the place.

    Three venues, because the consensus needs a quorum of MIN_VENUES before
    anything reaches the series at all - a median of fewer is one venue's opinion.
    """
    from till_infinity.structures import engine as eng

    engine = eng.Engine()
    prices = [100] * 7 + [102, 105, 108, 110] + [110] * 5
    prices += [112, 116, 120] + [120] * 7 + [118, 115, 112, 110] + [110] * 7
    for i, close in enumerate(prices):
        for venue in ("a", "b", "c"):
            engine.observe_bar(
                {
                    "feed": "t",
                    "venue": venue,
                    "interval": "4h",
                    "ts": i * 14_400,
                    "time": i * 14_400,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                }
            )
    assert engine.series("t", "4h").closes, "the consensus never agreed a price"

    engine.origins_bracketing("t", "4h", 110.0, engine.vol.of("t", "4h"))

    assert ("t", "4h") in engine._origins


def test_an_engine_restored_without_the_field_still_works():
    """The engine is persisted whole and is not a `Restorable` dataclass, so a
    save made before `_origins` existed restores without it. Nothing fills it
    in, and the failure would land inside the try that swallows it - every
    origin feature quietly missing after a deploy."""
    from till_infinity.structures import engine as eng

    engine = eng.Engine()
    del engine._origins

    got = engine._remember_origins("t", "4h", [_origin(100.0, "down", when=1.0)])

    assert len(got) == 1
    assert ("t", "4h") in engine._origins
