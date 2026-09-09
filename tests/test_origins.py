"""What the origin model must get right, and the ways it can quietly not."""

from __future__ import annotations

import pytest

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
    series.note_fine(0, 90.0, 105.0)

    assert series.fine_at(0)[:2] == (90.0, 105.0)


def test_an_uncaptured_bar_reads_as_no_evidence():
    import math

    from till_infinity.structures.engine import Series

    series = Series(feed="t", interval="4h")
    series.add(0, 110.0, 90.0, 100.0, 100.0)

    low, high = series.fine_at(0)[:2]
    assert math.isnan(low)
    assert math.isnan(high)
    assert all(math.isnan(v) for v in series.fine_at(999))


def test_a_series_from_before_the_field_has_no_minutes_and_says_so():
    """Sparse, so there is nothing to pad and nothing to misalign. A restored
    Series simply has no entries, and absence is the honest reading: those
    bars' minutes were never captured."""
    import math

    from till_infinity.structures.engine import Series

    series = Series(feed="t", interval="4h")
    series.add(14_400, 110.0, 90.0, 100.0, 100.0)
    series.add(28_800, 112.0, 92.0, 101.0, 100.0)

    assert all(math.isnan(v) for v in series.fine_at(14_400))

    series.note_fine(28_800, 92.0, 111.0)
    assert series.fine_at(28_800)[:2] == (92.0, 111.0)
    assert all(math.isnan(v) for v in series.fine_at(14_400))


def test_the_minutes_are_evicted_with_the_window_they_belong_to():
    """As dense arrays these were 99.6% nan and 35% of a Series' bytes - 27MB
    across 3,058 series, storing nothing, and the container was OOM-killed
    once. Sparse keeps only what was captured, and drops it when its bar
    falls out of the window."""
    from till_infinity.structures.engine import WINDOW, Series

    series = Series(feed="t", interval="1m")
    for i in range(1, WINDOW + 60):
        series.add(i * 60, 110.0, 90.0, 100.0, 100.0)
        series.note_fine(i * 60, 95.0, 105.0)

    # Bounded, with a bar or two of overhang because eviction is amortised
    # into `add` rather than run on every write.
    assert len(series.fine) <= WINDOW + 2
    assert min(series.fine) >= series.times[0] - 120


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

    low, high = engine.series("t", "4h").fine_at(base)[:2]

    assert high == 105.0
    assert low == 98.0


def test_the_forming_bar_cannot_be_captured_and_the_finished_one_can():
    """The failure that made 1h and coarser capture exactly zero. The newest
    bar is the one still forming, so its span runs into the future and no finer
    series can ever cover it - the capture has to target the bar the next one
    has closed."""
    import math

    from till_infinity.structures import engine as eng

    base = 1_700_000_000 - (1_700_000_000 % 14_400)
    engine = eng.Engine()

    def minutes(start, count, peak_at, peak):
        for minute in range(count):
            close = peak if minute == peak_at else 100.0
            for venue in ("a", "b", "c"):
                engine.observe_bar(
                    {
                        "feed": "t",
                        "venue": venue,
                        "interval": "1m",
                        "ts": start + minute * 60,
                        "time": start + minute * 60,
                        "high": close,
                        "low": close,
                        "close": close,
                    }
                )

    def four_hour(when):
        for venue in ("a", "b", "c"):
            engine.observe_bar(
                {
                    "feed": "t",
                    "venue": venue,
                    "interval": "4h",
                    "ts": when,
                    "time": when,
                    "high": 106.0,
                    "low": 97.0,
                    "close": 100.0,
                }
            )

    # The first 4h bar, complete, and only a few minutes of the second.
    minutes(base, 240, 120, 105.0)
    four_hour(base)
    minutes(base + 14_400, 5, 2, 108.0)
    four_hour(base + 14_400)

    series = engine.series("t", "4h")

    # The finished bar carries its minutes.
    assert series.fine_at(base)[1] == 105.0
    # The forming one does not, and is not filled in from the fraction seen.
    assert math.isnan(series.fine_at(base + 14_400)[1])


# ------------------------------------------- the zone price is standing inside


def _engine_with(origins_at, price_now):
    """An engine whose kept 4h origins are exactly `origins_at`."""
    from till_infinity.structures import engine as eng
    from till_infinity.structures.drawing.origins import Origins

    engine = eng.Engine()
    base = 1_700_000_000 - (1_700_000_000 % 14_400)
    for i in range(40):
        for venue in ("a", "b", "c"):
            engine.observe_bar(
                {
                    "feed": "t",
                    "venue": venue,
                    "interval": "4h",
                    "ts": base + i * 14_400,
                    "time": base + i * 14_400,
                    "high": price_now + 1,
                    "low": price_now - 1,
                    "close": price_now,
                }
            )
    kept = Origins()
    kept.found = list(origins_at)
    engine._origins[("t", "4h")] = kept
    return engine


def test_an_origin_price_stands_inside_still_bounds_the_range():
    """Filtering on `low > price` and `high < price` drops every origin whose
    band straddles price. On the live book that was 14 of 46 on eurusd, and on
    btc three straddled while none sat above - so the range reported open air
    upward with a ceiling directly overhead."""
    holding = _origin(100.0, "down", when=1.0, band=0.0)
    holding.low, holding.high = 99.0, 103.0
    far = _origin(110.0, "down", when=2.0, band=0.0)
    far.low, far.high = 108.0, 112.0

    engine = _engine_with([holding, far], 100.0)
    below, above = engine.origins_bracketing("t", "4h", 100.0, engine.vol.of("t", "4h"))

    # The wall above is where the zone price is inside finishes, not the far
    # one beyond it.
    assert above == 103.0
    assert below == 99.0


def test_the_nearer_of_the_two_kinds_wins():
    """A zone beginning above price can still be nearer than the far edge of
    the one price is inside."""
    holding = _origin(100.0, "down", when=1.0, band=0.0)
    holding.low, holding.high = 90.0, 120.0
    near = _origin(102.0, "down", when=2.0, band=0.0)
    near.low, near.high = 101.0, 105.0

    engine = _engine_with([holding, near], 100.0)
    _below, above = engine.origins_bracketing("t", "4h", 100.0, engine.vol.of("t", "4h"))

    assert above == 101.0


def test_open_air_is_still_reported_when_there_is_nothing_either_way():
    engine = _engine_with([], 100.0)

    assert engine.origins_bracketing("t", "4h", 100.0, engine.vol.of("t", "4h")) == (None, None)


def test_change_in_finds_where_a_fall_began_not_where_it_was_confirmed():
    """The change point is the argmax over every start, not the first crossing."""
    import math

    from till_infinity.structures.drawing.origins import change_in

    # Flat, then a clean fall. The change is at index 5 and nowhere else.
    closes = [100.0] * 6 + [99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    times = [float(i * 60) for i in range(len(closes))]

    got = change_in(times, closes, 0.0, 60.0 * len(closes))

    assert got is not None
    down, up = got
    assert down == 100.0
    # The rally detector has nothing to find in a series that only falls.
    assert math.isnan(up) or up <= 100.0


def test_change_in_is_indifferent_to_the_volatility_unit():
    """The argmax is scale-free, which is why no unit is taken."""
    from till_infinity.structures.drawing.origins import change_in

    closes = [50.0] * 5 + [49.0, 48.0, 47.0, 46.0]
    times = [float(i * 60) for i in range(len(closes))]
    scaled = [c * 1000 for c in closes]

    a = change_in(times, closes, 0.0, 60.0 * len(closes))
    b = change_in(times, scaled, 0.0, 60.0 * len(closes))

    assert a is not None
    assert b is not None
    assert b[0] == a[0] * 1000


def test_change_in_refuses_partial_cover_like_the_extremes_do():
    from till_infinity.structures.drawing.origins import change_in

    closes = [100.0, 99.0, 98.0]
    times = [0.0, 60.0, 120.0]

    # The bar runs for an hour and only three minutes of it are here.
    assert change_in(times, closes, 0.0, 3600.0) is None


def test_an_origin_is_confirmed_when_the_change_point_lands_on_the_extreme():
    from till_infinity.structures.drawing.origins import refine

    origin = Origin(price=100.0, low=99.0, high=101.0, launched="down", size_vol=5.0, when=0.0)

    got = refine(origin, 99.0, 100.5, change=100.5, unit=1.0)

    assert got.refined
    assert got.confirmed
    assert got.price == 100.5


def test_an_origin_is_not_confirmed_when_the_change_point_is_elsewhere():
    from till_infinity.structures.drawing.origins import refine

    origin = Origin(price=100.0, low=99.0, high=101.0, launched="down", size_vol=5.0, when=0.0)

    got = refine(origin, 99.0, 100.5, change=99.0, unit=1.0)

    assert got.refined
    assert not got.confirmed


def test_confirmation_is_recorded_even_when_the_refinement_does_not_move_the_price():
    """Agreeing at the coarse price is agreement, not an absent reading."""
    from till_infinity.structures.drawing.origins import refine

    origin = Origin(price=100.0, low=99.0, high=101.0, launched="down", size_vol=5.0, when=0.0)

    got = refine(origin, 99.0, 100.0, change=100.0, unit=1.0)

    assert got.confirmed
    assert got.price == 100.0


def test_an_uncomputed_change_point_leaves_an_origin_unconfirmed():
    import math

    from till_infinity.structures.drawing.origins import refine

    origin = Origin(price=100.0, low=99.0, high=101.0, launched="down", size_vol=5.0, when=0.0)

    got = refine(origin, 99.0, 100.5, change=math.nan, unit=1.0)

    assert got.refined
    assert not got.confirmed


def test_remember_takes_the_change_point_matching_the_launch_direction():
    origin = Origin(price=100.0, low=99.0, high=101.0, launched="up", size_vol=5.0, when=0.0)
    kept = Origins()

    # (low, high, down, up) - a rally reads the fourth, and the third is a
    # decoy that would confirm nothing if the wrong one were picked.
    got = kept.remember([origin], lambda o: (99.5, 101.0, 100.0, 99.5), unit=1.0)

    assert got[0].price == 99.5
    assert got[0].confirmed


def test_remember_still_accepts_a_pair_from_before_change_points_existed():
    origin = Origin(price=100.0, low=99.0, high=101.0, launched="down", size_vol=5.0, when=0.0)
    kept = Origins()

    got = kept.remember([origin], lambda o: (99.0, 100.5), unit=1.0)

    assert got[0].refined
    assert not got[0].confirmed


def test_fine_at_pads_an_entry_written_before_change_points_existed():
    import math

    from till_infinity.structures import engine as eng

    series = eng.Series("t", "4h")
    series.fine[0] = (90.0, 105.0)

    low, high, down, up = series.fine_at(0)

    assert (low, high) == (90.0, 105.0)
    assert math.isnan(down)
    assert math.isnan(up)


def test_a_timeframe_with_no_detector_yet_reports_nothing_rather_than_zero():
    """Absent and zero are different claims and the journal has to tell them apart."""
    from till_infinity.structures import engine as eng

    engine = eng.Engine()

    assert engine.changing("nothing") == {}


def test_the_change_count_says_how_many_timeframes_were_watching():
    from till_infinity.structures import engine as eng

    engine = eng.Engine()
    engine._change_at = {("t", "5m"): (100.0, 0.0), ("t", "15m"): (0.0, 0.0)}
    engine._now = 200.0

    got = engine.changing("t")

    assert got["change_up_tf"] == 1.0
    assert got["change_down_tf"] == 0.0
    # Two of the four timeframes have a detector, so one-of-two is not
    # reported as though it were one-of-four.
    assert got["change_watched_tf"] == 2.0


def test_a_call_older_than_the_window_has_stopped_standing():
    from till_infinity.structures import engine as eng

    engine = eng.Engine()
    engine._change_at = {("t", "5m"): (10.0, 0.0)}
    engine._now = 10.0 + eng.CHANGE_WINDOW + 1.0

    assert engine.changing("t")["change_up_tf"] == 0.0


def test_a_call_from_the_future_does_not_count():
    """Guards the look-ahead the whole measurement was arranged to avoid."""
    from till_infinity.structures import engine as eng

    engine = eng.Engine()
    engine._change_at = {("t", "5m"): (5_000.0, 0.0)}

    assert engine.changing("t", when=1_000.0)["change_up_tf"] == 0.0


def test_only_the_measured_timeframes_carry_detectors():
    """4h is deliberately absent - 144 bars is not a sample. See CHANGE_INTERVALS."""
    from till_infinity.structures import engine as eng

    assert "4h" not in eng.CHANGE_INTERVALS
    assert eng.CHANGE_INTERVALS == ("5m", "15m", "30m", "1h")


def test_the_change_detectors_actually_fire_on_the_real_bar_path():
    """The `research/inert.md` question, asked of this feature before it ships.

    A reading that never fires in production is worse than no reading: it looks
    configured, it journals a zero, and nothing says so. So this drives real
    bars through `observe_bar` and asserts a call comes out the other end.
    """
    from till_infinity.structures import engine as eng

    # `single_source`, because a median across venues needs three of them and
    # this test has one - the same reason the synthetics are declared that way.
    engine = eng.Engine(intervals=("5m",), single_source=frozenset({"t"}))
    start = 1_700_000_000
    # Two hundred quiet bars to warm the volatility estimate, then a run that
    # is unambiguously a change of mean.
    prices = [100.0 + (i % 3) * 0.05 for i in range(200)]
    prices += [100.0 + i * 0.6 for i in range(1, 40)]
    for i, price in enumerate(prices):
        engine.observe_bar(
            {
                "feed": "t",
                "interval": "5m",
                "time": start + i * 300,
                "open": price,
                "high": price + 0.05,
                "low": price - 0.05,
                "close": price,
                "venue": "v",
            }
        )

    got = engine.changing("t", when=start + len(prices) * 300)

    assert got, "no change reading at all - the detectors never got a bar"
    assert got["change_watched_tf"] == 1.0
    assert got["change_up_tf"] == 1.0, "a 24-unit rally did not register as a change"


def test_a_flat_series_calls_no_change():
    """The other half of the same question: it has to be quiet when nothing happens."""
    from till_infinity.structures import engine as eng

    engine = eng.Engine(intervals=("5m",), single_source=frozenset({"t"}))
    start = 1_700_000_000
    for i in range(240):
        price = 100.0 + (i % 3) * 0.05
        engine.observe_bar(
            {
                "feed": "t",
                "interval": "5m",
                "time": start + i * 300,
                "open": price,
                "high": price + 0.05,
                "low": price - 0.05,
                "close": price,
                "venue": "v",
            }
        )

    got = engine.changing("t", when=start + 240 * 300)

    assert got["change_up_tf"] == 0.0
    assert got["change_down_tf"] == 0.0


def test_the_change_detectors_survive_a_save_and_restore():
    """They ride on the engine, which is persisted whole and is not a dataclass.

    A detector that cold-starts on every deploy never accumulates enough to
    fire on a slow timeframe, so this is the difference between a working
    reading and one that is quietly always zero on 1h.
    """
    from till_infinity.structures import codec as scodec
    from till_infinity.structures import engine as eng

    engine = eng.Engine(intervals=("5m",), single_source=frozenset({"t"}))
    start = 1_700_000_000
    prices = [100.0 + (i % 3) * 0.05 for i in range(200)]
    prices += [100.0 + i * 0.6 for i in range(1, 40)]
    for i, price in enumerate(prices):
        engine.observe_bar(
            {
                "feed": "t",
                "interval": "5m",
                "time": start + i * 300,
                "open": price,
                "high": price + 0.05,
                "low": price - 0.05,
                "close": price,
                "venue": "v",
            }
        )
    when = start + len(prices) * 300
    before = engine.changing("t", when=when)

    back = scodec.unpack(scodec.pack({"engine": engine}))["engine"]

    assert back.changing("t", when=when) == before
    assert isinstance(back._changes[("t", "5m")][0], eng.Focus)


def test_drift_restored_without_its_counters_does_not_throw():
    """The fault that stopped structures for eleven hours on 2026-09-08.

    `Drift` is persisted and is **not** a `Restorable` dataclass, so nothing
    fills in a field a save predates. Every instance restored from a save
    written before `_agreement` existed came back without it, and the first
    time ADWIN actually fired the attribute access threw - inside a consumer
    that had no per-message guard, so the service stopped while the container
    stayed healthy.
    """
    from till_infinity.structures.learning.drift import Drift

    detector = Drift()
    # Exactly what a restore from an older save leaves behind.
    del detector.__dict__["_agreement"]

    # Feeding it must not throw, and the counters must come back.
    for i in range(400):
        detector.observe("t", 100.0 + (i % 5) * 2.0, when=float(i), interval="5m")

    counts = detector.watching()
    assert set(counts) >= {"adwin", "kswin", "both", "kswin_alone"}


def test_a_resting_intent_with_a_text_entry_does_not_kill_trading():
    """The fault that stopped trading on the same day.

    `abs(intent.entry - at)` on an entry that came back from state as a string
    raised a TypeError out of `handle`, and the trading loop had no guard, so
    the whole service ended.
    """
    import asyncio

    from till_infinity.trading.models import Side
    from till_infinity.trading.service import Trader

    trader = Trader.__new__(Trader)

    class _Settings:
        notify = True
        notify_rests = True

    class _Bus:
        def __init__(self):
            self.sent = []

        async def publish(self, *args, **kwargs):
            self.sent.append((args, kwargs))
            return 1

    trader.settings = _Settings()
    trader.bus = _Bus()
    trader.broker = type("B", (), {"name": "test"})()
    intent = type("I", (), {"entry": "1.2345", "feed": "eurusd", "side": Side.BUY, "volume": 0.1})()

    # It must not raise. Nothing is asserted about the message text - the point
    # is only that a bad shape is survivable and still gets announced.
    asyncio.run(trader._announce_rest(intent, 1.2300, "test", 0, gone="x"))

    assert trader.bus.sent, "the announcement was swallowed rather than sent"


def test_a_price_restored_as_text_comes_back_as_a_number():
    """The fault that took trading down, fixed where every restore goes through.

    `Intent.reward` is `abs(target - entry)`, so a `target` restored as the
    string "1.2345" raised on the first tick that asked. The same shape had
    already done it once with `Side`, which is why `restore_enum` exists - this
    is that fix one type along.
    """
    from dataclasses import dataclass

    from till_infinity.shared.state import Restorable, restore_number

    @dataclass(slots=True)
    class _Priced(Restorable):
        entry: float = 0.0
        count: int = 0
        name: str = ""
        flag: bool = False

    assert restore_number(_Priced, "entry", "1.2345") == 1.2345
    assert isinstance(restore_number(_Priced, "entry", 1), float)
    assert restore_number(_Priced, "count", "7") == 7
    # A string field is left alone, and so is a flag - `float("true")` is not
    # the right answer for a bool and bool is a subclass of int.
    assert restore_number(_Priced, "name", "1.5") == "1.5"
    assert restore_number(_Priced, "flag", True) is True
    # Something that will not convert stays as it was, so the fault is visible
    # at the point of use rather than becoming a plausible zero.
    assert restore_number(_Priced, "entry", "wat") == "wat"


def test_setstate_coerces_a_numeric_field_restored_as_text():
    from dataclasses import dataclass

    from till_infinity.shared.state import Restorable

    @dataclass(slots=True)
    class _Order(Restorable):
        entry: float = 0.0
        target: float = 0.0

    order = _Order.__new__(_Order)
    order.__setstate__({"entry": "1.2000", "target": "1.2345"})

    # The subtraction that used to raise.
    assert abs(order.target - order.entry) == pytest.approx(0.0345)


def test_the_change_detectors_ask_more_of_a_faster_timeframe():
    """5m must clear a higher bar than 1h or the count is not a count.

    At a fixed threshold the fire rate runs 16.96 a day on 5m against 0.20 on
    4h, so the fast rungs are permanently calling. See `CHANGE_K`.
    """
    from till_infinity.structures import engine as eng

    engine = eng.Engine(intervals=("5m", "1h"), single_source=frozenset({"t"}))
    start = 1_700_000_000
    for interval, step in (("5m", 300), ("1h", 3600)):
        prices = [100.0 + (i % 3) * 0.05 for i in range(200)]
        prices += [100.0 + i * 0.6 for i in range(1, 40)]
        for i, price in enumerate(prices):
            engine.observe_bar(
                {
                    "feed": "t",
                    "interval": interval,
                    "time": start + i * step,
                    "open": price,
                    "high": price + 0.05,
                    "low": price - 0.05,
                    "close": price,
                    "venue": "v",
                }
            )

    fast = engine._changes[("t", "5m")][0].threshold
    slow = engine._changes[("t", "1h")][0].threshold

    assert fast > slow, "the faster timeframe was not asked for more evidence"
    # 1h is the slowest of the tracked intervals here, so it keeps the shipped
    # threshold and 5m is lifted by k * ln(3600/300).
    assert slow == pytest.approx(eng.focus.THRESHOLD)


def test_a_missing_minute_at_the_open_no_longer_discards_the_whole_bar():
    """The asymmetry that cost the refinement its coverage.

    The right edge always tolerated being one step short; the left edge
    tolerated nothing, so a 4h bar whose first minute the venue never printed
    threw away the other 239. Production: 57 captures across 258 4h series.
    """
    from till_infinity.structures.drawing.origins import extremes_in

    span = 4 * 3600.0
    # A 4h bar starting at 0, covered by 1m closes - except the very first
    # minute, which never arrived.
    times = [float(t) for t in range(60, int(span) + 60, 60)]
    closes = [100.0 + (i % 7) * 0.1 for i in range(len(times))]

    got = extremes_in(times, closes, 0.0, span)

    assert got is not None, "one absent minute still discards the bar"
    assert got == (min(closes), max(closes))


def test_partial_cover_is_still_not_cover():
    """The relaxation must not turn into accepting a fraction of the bar."""
    from till_infinity.structures.drawing.origins import extremes_in

    span = 4 * 3600.0
    # Only the first half hour of a four hour bar.
    times = [float(t) for t in range(0, 1800, 60)]
    closes = [100.0 + i * 0.1 for i in range(len(times))]

    assert extremes_in(times, closes, 0.0, span) is None


def test_the_tolerance_scales_with_the_bar_rather_than_being_a_constant():
    """Two percent of a 5m bar is under one step, so nothing is loosened there."""
    from till_infinity.structures.drawing.origins import extremes_in

    span = 300.0
    # A 5m bar missing its first two minutes is 40% absent, not a boundary
    # rounding - and must still be refused.
    times = [120.0, 180.0, 240.0]
    closes = [100.0, 101.0, 102.0]

    assert extremes_in(times, closes, 0.0, span) is None


def test_the_change_point_uses_the_same_window_as_the_extreme():
    """Or `Origin.confirmed` compares two different sets of bars."""
    from till_infinity.structures.drawing.origins import change_in, extremes_in

    span = 4 * 3600.0
    times = [float(t) for t in range(60, int(span) + 60, 60)]
    closes = [100.0] * 120 + [100.0 - i * 0.2 for i in range(len(times) - 120)]

    assert extremes_in(times, closes, 0.0, span) is not None
    assert change_in(times, closes, 0.0, span) is not None


def test_a_hole_in_the_middle_no_longer_discards_the_bar():
    """The largest single cause of the refinement's 6.7%.

    Measured in production: 33% to 44% of every capture attempt on 5m through
    1h failed with the series spanning the bar but no fine bar within a step of
    an edge. A hole is not the same as absent data.
    """
    from till_infinity.structures.drawing.origins import extremes_in

    span = 3600.0
    # An hour of 1m closes with ten minutes missing from the middle - fifty of
    # sixty present, which is comfortably inside `COVER`.
    times = [float(t) for t in range(0, 1800, 60)] + [float(t) for t in range(2400, 3600, 60)]
    closes = [100.0 + (i % 5) * 0.2 for i in range(len(times))]

    got = extremes_in(times, closes, 0.0, span)

    assert got is not None
    assert got == (min(closes), max(closes))


def test_a_complete_bar_is_not_refused_for_its_own_last_minute():
    """Five 1m closes span 240s of timestamps and cover 300s of bar."""
    from till_infinity.structures.drawing.origins import extremes_in

    times = [0.0, 60.0, 120.0, 180.0, 240.0]
    closes = [100.0, 101.0, 99.0, 100.5, 100.2]

    assert extremes_in(times, closes, 0.0, 300.0) == (99.0, 101.0)


def test_a_bar_covered_only_at_its_edges_is_still_refused():
    """Two minutes of a four hour bar is the failure COVER exists to refuse."""
    from till_infinity.structures.drawing.origins import extremes_in

    times = [0.0, 60.0, 120.0]
    closes = [100.0, 101.0, 102.0]

    assert extremes_in(times, closes, 0.0, 4 * 3600.0) is None


def test_a_bar_present_only_at_its_two_ends_is_refused():
    """Extent is not coverage, and measuring extent let this through.

    Twenty minutes at the start and one at the end spans the whole hour, so a
    first-to-last measure calls it complete. It is the two-of-fifteen case in a
    full-width disguise, which is why `_covers` counts bars instead.
    """
    from till_infinity.structures.drawing.origins import extremes_in

    span = 3600.0
    times = [float(t) for t in range(0, 1200, 60)] + [3540.0]
    closes = [100.0 + i for i in range(len(times))]

    assert extremes_in(times, closes, 0.0, span) is None


def test_spacing_reads_the_bar_length_not_a_hole_at_the_start():
    from till_infinity.structures.drawing.origins import _spacing

    # A ten minute hole first, then dense one-minute bars.
    times = [0.0, 600.0, 660.0, 720.0, 780.0]

    assert _spacing(times, 0, len(times)) == 60.0
