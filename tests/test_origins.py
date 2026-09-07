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


#: A quarter-hour of one-minute closes peaking at 105 before the drop begins.
_TIMES = [float(t * 60) for t in range(15)]
_CLOSES = [100, 101, 103, 105, 104, 102, 99, 97, 95, 94, 93, 92, 91, 90, 90]


def test_the_extremes_are_the_finest_closes_inside_the_bar():
    """Closes rather than highs and lows: `Origins.observe` walks closes, so a
    transition drawn from extremes would be measuring a different thing."""
    from till_infinity.structures.drawing.origins import extremes_in

    assert extremes_in(_TIMES, _CLOSES, 0.0, 900.0) == (90, 105)


def test_partial_cover_is_refused_rather_than_used():
    """The extreme of whatever fraction survived in a bounded window is not the
    extreme of the bar, and a refinement from two of fifteen minutes is worse
    than none."""
    from till_infinity.structures.drawing.origins import extremes_in

    assert extremes_in([0.0, 60.0, 120.0], [100.0, 105.0, 103.0], 0.0, 900.0) is None
    assert extremes_in(_TIMES, _CLOSES, 600.0, 900.0) is None
    assert extremes_in((), (), 0.0, 900.0) is None
    assert extremes_in(_TIMES, _CLOSES, 0.0, 0.0) is None


def test_a_drop_refines_to_the_highest_fine_close():
    """The origin is the last price before the impulse took over, so one
    resolution down it is the highest close for a drop - the same definition,
    asked of finer evidence."""
    from till_infinity.structures.drawing.origins import refine

    got = refine(_origin(90.0, "down"), 90.0, 105.0)

    assert got.price == 105.0
    assert got.refined is True


def test_a_rally_refines_to_the_lowest_fine_close():
    from till_infinity.structures.drawing.origins import refine

    assert refine(_origin(110.0, "up"), 95.0, 110.0).price == 95.0


def test_the_band_travels_with_the_price():
    """Relocating the origin outside its own zone would leave a level whose
    band no longer contains it. Re-deriving the width from the finer bars is a
    separate experiment; this re-centres and keeps the width."""
    from till_infinity.structures.drawing.origins import refine

    got = refine(_origin(90.0, "down", band=2.0), 90.0, 105.0)

    assert got.low <= got.price <= got.high
    assert (got.high - got.low) == 4.0


def test_a_bar_that_was_never_covered_leaves_the_origin_alone():
    """`nan` is what an uncaptured bar carries, and it has to read as "no
    evidence" rather than as a price."""
    import math

    from till_infinity.structures.drawing.origins import refine

    origin = _origin(90.0, "down")

    assert refine(origin, math.nan, math.nan) is origin
    assert refine(origin, math.nan, 105.0) is origin
    assert refine(origin, 90.0, 90.0).refined is False  # unchanged price


# ------------------------------------------------------- keeping what was found


def test_a_second_sighting_does_not_replace_a_refined_band():
    """The whole reason the set is kept. An origin is refined once, while its
    bar's minutes are still to hand; recomputing later would hand back a coarse
    band and undo it silently."""
    import math

    from till_infinity.structures.drawing.origins import Origins

    kept = Origins()
    coarse = _origin(90.0, "down", when=0.0)

    first = kept.remember([coarse], lambda _o: (90.0, 105.0))
    assert first[0].price == 105.0

    # The same origin again, this time with nothing captured for its bar.
    again = kept.remember([coarse], lambda _o: (math.nan, math.nan))

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


def test_a_refined_origin_says_so():
    """Otherwise "are origins being refined in production" has no answer, and a
    refinement that silently never fires is the shape inert.md catalogues."""
    from till_infinity.structures.drawing.origins import Origins

    kept = Origins()
    kept.remember([_origin(90.0, "down", when=0.0)], lambda _o: (90.0, 105.0))
    kept.remember([_origin(50.0, "up", when=900.0)])

    assert kept.refined == 1
    assert len(kept.found) == 2


# --------------------------------------------- capturing them at the right moment


def test_a_series_records_its_bar_s_fine_extremes():
    """The bar's minutes are certainly present exactly once - while that bar is
    the one closing - so that is when they are stored."""
    from till_infinity.structures.engine import Series

    series = Series(feed="t", interval="4h")
    series.add(0, 110.0, 90.0, 100.0, 100.0)
    series.note_fine(90.0, 105.0)

    assert series.fine_at(0) == (90.0, 105.0)


def test_an_uncaptured_bar_reads_as_no_evidence():
    import math

    from till_infinity.structures.engine import Series

    series = Series(feed="t", interval="4h")
    series.add(0, 110.0, 90.0, 100.0, 100.0)

    low, high = series.fine_at(0)
    assert math.isnan(low)
    assert math.isnan(high)
    assert all(math.isnan(v) for v in series.fine_at(999))


def test_a_series_from_before_the_field_does_not_misalign():
    """`opens` had this exact bug waiting: a restored Series has empty deques
    beside full ones, and appending blindly would pair every bar with another
    bar's minutes from then on."""
    import math

    from till_infinity.structures.engine import Series

    series = Series(feed="t", interval="4h")
    series.add(0, 110.0, 90.0, 100.0, 100.0)
    series.fine_low.clear()
    series.fine_high.clear()

    series.add(14_400, 112.0, 92.0, 101.0, 100.0)

    assert all(math.isnan(v) for v in series.fine_at(14_400))
    assert all(math.isnan(v) for v in series.fine_at(0))


def test_the_engine_captures_fine_extremes_as_the_coarse_bar_closes():
    """End to end, and the thing production got wrong. Feeding 1m bars and then
    the 4h bar that spans them has to leave the 4h bar carrying its minutes -
    otherwise the refinement is attempted hours later against a window that has
    moved on, which refined one 4h origin in 924.

    A real timestamp rather than 0, because `observe_bar` reads `time` for
    truthiness and a zero falls back to the wall clock.
    """
    from till_infinity.structures import engine as eng

    base = 1_700_000_000 - (1_700_000_000 % 14_400)
    engine = eng.Engine()
    for minute in range(240):
        close = 100.0 + (5.0 if minute == 120 else 0.0) - (2.0 if minute == 200 else 0.0)
        for venue in ("a", "b", "c"):
            engine.observe_bar(
                {
                    "feed": "t",
                    "venue": venue,
                    "interval": "1m",
                    "ts": base + minute * 60,
                    "time": base + minute * 60,
                    "high": close,
                    "low": close,
                    "close": close,
                }
            )
    for venue in ("a", "b", "c"):
        engine.observe_bar(
            {
                "feed": "t",
                "venue": venue,
                "interval": "4h",
                "ts": base,
                "time": base,
                "high": 106.0,
                "low": 97.0,
                "close": 100.0,
            }
        )

    low, high = engine.series("t", "4h").fine_at(base)

    assert high == 105.0
    assert low == 98.0


def test_a_restored_series_starts_pairing_rather_than_never_starting():
    """The guard every other late-added field here uses is "exactly one
    behind", and a restored Series is five hundred behind - so it would never
    be true once, and the field would stay empty for the life of the process.
    Computed correctly and read where nothing sees it."""
    import math

    from till_infinity.structures.engine import Series

    series = Series(feed="t", interval="4h")
    for i in range(5):
        series.add(14_400 * (i + 1), 110.0, 90.0, 100.0, 100.0)
    # As a restore from before the field existed leaves it.
    series.fine_low.clear()
    series.fine_high.clear()

    series.add(14_400 * 6, 112.0, 92.0, 101.0, 100.0)
    series.note_fine(92.0, 111.0)

    assert len(series.fine_low) == len(series.closes)
    assert series.fine_at(14_400 * 6) == (92.0, 111.0)
    assert all(math.isnan(v) for v in series.fine_at(14_400))
