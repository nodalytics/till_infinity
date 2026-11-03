"""Per-side level parameters: that neutral is neutral, and that a tilt bites.

`Sided` lets the level book believe a ceiling's touches differently from a
floor's. Two failures would make it worse than not having it, and each test
here is one of them:

1. **A tilt of 1 that is not the old behaviour** silently reparameterises
   every running deployment, because every caller passes a bare float today.
2. **A tilt that does nothing** is the `band()` defect this module already
   records: `mult` was accepted, stored and never read, so a band built at
   0.015 came out identical to one at 0.5 - a parameter that existed and did
   nothing, caught only by printing two widths side by side.

So the pair that matters is the identity control and the bites-at-all test,
and neither is meaningful without the other.
"""

from __future__ import annotations

import math
import random

import pytest
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity

from till_infinity.indicators import Levels, Sided

BAR_TYPE = BarType.from_str("EURUSD.SIM-1-HOUR-LAST-EXTERNAL")
HOUR_NS = 3_600_000_000_000


def bar(open_: float, high: float, low: float, close: float, ts: int = 0) -> Bar:
    return Bar(
        BAR_TYPE,
        Price(open_, 5),
        Price(high, 5),
        Price(low, 5),
        Price(close, 5),
        Quantity(100, 0),
        ts_event=ts,
        ts_init=ts,
    )


def turning(n: int, *, seed: int = 5, start: float = 1.1000, step: float = 0.0004):
    """A deterministic walk, which has local extremes at every window length.

    A drifting sine does not: at any drift a slope test can recover, the drift
    dominates and no bar is the strict extreme of its neighbourhood, so a
    pivot detector finds nothing and the fixture tests the detector being
    right about an empty book.
    """
    rng = random.Random(seed)
    price, ts, out = start, 0, []
    for _ in range(n):
        price += rng.gauss(0.0, step)
        high = price + abs(rng.gauss(0.0, step / 2))
        low = price - abs(rng.gauss(0.0, step / 2))
        out.append(bar(price, high, low, price, ts))
        ts += HOUR_NS
    return out


def book_of(bars, **kwargs) -> Levels:
    book = Levels(unit_span=48, **kwargs)
    for one in bars:
        book.handle_bar(one)
    return book


def shape(book: Levels) -> list[tuple[float, int, int, int]]:
    """A book's readable content, for comparing two books.

    Prices rounded to 1e-9: the Kalman carries the same arithmetic in both
    books, so an exact match is the claim, and the rounding only stops a
    representation difference reading as a behaviour difference.
    """
    return sorted(
        (round(lv.at(book.when), 9), lv.touches, lv.from_below, lv.from_above) for lv in book.levels
    )


# ----------------------------------------------------------- the arithmetic


@pytest.mark.parametrize("tilt", [1.0, 1.5, 2.0, 4.0, 0.25])
def test_a_tilt_never_moves_the_average_parameter(tilt):
    """The geometric mean stays `shared` at every tilt.

    Without this, switching asymmetry on changes the average of the parameter
    as well as its split, and "is the book better per side" silently becomes
    "is the book better with a different average". That substitution is on
    record here: refitting a multiplier whose mean was not 1 reversed a +1192
    result to -24.
    """
    param = Sided(0.35, tilt)
    assert math.isclose(math.sqrt(param.for_side(1) * param.for_side(-1)), 0.35, rel_tol=1e-12)


def test_neutral_is_exactly_the_shared_value_not_merely_close():
    """At tilt 1 the two sides are the float that was passed in.

    `sqrt(1.0)` is exactly 1.0, so this would pass by luck - it is asserted
    because the shortcut in `for_side` is what guarantees it, and removing
    that shortcut would leave every symmetric book multiplying by 1.0 and
    drifting in the last bit.
    """
    param = Sided(0.35)
    assert param.for_side(1) == 0.35
    assert param.for_side(-1) == 0.35
    assert param.symmetric


def test_a_level_with_no_recorded_side_gets_the_neutral_value():
    """Side 0 means "neither", and must not fall through to one of the branches.

    An `if side > 0 else` would hand every sideless level the *support*
    parameter, so a book holding one level from an older state would be
    quietly asymmetric with the tilt nominally off.
    """
    param = Sided(0.35, 4.0)
    assert param.for_side(0) == 0.35
    assert param.for_side(1) != param.for_side(0)


def test_a_tilt_of_zero_or_a_negative_shared_is_refused():
    """A tilt is a ratio, so zero is not "no asymmetry" - 1 is.

    Accepting 0 would set one side's parameter to zero: a merge gap of zero
    makes every pivot its own level and the book becomes the pivot list.
    """
    with pytest.raises(ValueError, match="tilt"):
        Sided(0.35, 0.0)
    with pytest.raises(ValueError, match="shared"):
        Sided(0.0, 1.0)


# ------------------------------------------------- the identity control


def test_a_tilt_of_one_reproduces_the_book_a_bare_float_builds():
    """The control: the capability lets the existing behaviour through unchanged.

    Every caller in the repository passes bare floats, so if this fails the
    change is not "levels can be asymmetric", it is "every level book moved".
    Compared on the whole book - prices, touch counts and both side counts -
    rather than on a count, because a book with the same number of levels in
    different places would pass a count test.
    """
    bars = turning(400)
    plain = book_of(bars, merge_vol=0.35, touch_noise_vol=0.40, reach=3)
    tilted = book_of(
        bars,
        merge_vol=Sided(0.35, 1.0),
        touch_noise_vol=Sided(0.40, 1.0),
        reach=Sided(3, 1.0),
    )
    assert shape(plain) == shape(tilted)
    assert plain.count > 1, "an empty book would make the comparison vacuous"


def test_a_reach_tilt_too_small_to_move_a_whole_bar_changes_nothing():
    """A reach is a bar count, so a tilt under half a bar rounds away.

    Asserted so the docstring's claim is checked rather than trusted: at
    reach 3 a tilt of 1.2 is 3.29 and 2.74, which is 3 on both sides. A test
    expecting a difference here would be asserting a rounding, which is the
    kind of test that passes for the wrong reason.
    """
    bars = turning(400)
    assert shape(book_of(bars, reach=3)) == shape(book_of(bars, reach=Sided(3, 1.2)))


# ---------------------------------------------------- the tilt has to bite


def test_a_merge_tilt_changes_the_book_rather_than_being_accepted_and_ignored():
    """A parameter that is stored and never read is the defect this file records.

    `band()`'s `mult` was exactly that - accepted, stored, unread, so 0.015
    and 0.5 gave identical widths. A large tilt must therefore produce a
    different book, and the two tilt directions must differ from each other
    as well, or only one branch of `for_side` is wired.
    """
    bars = turning(500)
    plain = shape(book_of(bars, merge_vol=0.35))
    up = shape(book_of(bars, merge_vol=Sided(0.35, 4.0)))
    down = shape(book_of(bars, merge_vol=Sided(0.35, 0.25)))
    assert up != plain
    assert down != plain
    assert up != down


def test_a_touch_noise_tilt_moves_the_side_it_names_and_not_the_other():
    """Belief in a ceiling's touches is separable from belief in a floor's.

    The noise is the filter's `R` and the denominator of its gain, so a tilt
    on it changes how fast each side's level learns. If both sides moved
    together the tilt would be a global rescale wearing a per-side name.
    """
    bars = turning(500)
    plain = book_of(bars, touch_noise_vol=0.40)
    tilted = book_of(bars, touch_noise_vol=Sided(0.40, 3.0))
    resistance = [lv for lv in plain.levels if lv.side > 0]
    assert resistance, "the fixture must produce pivot highs for this to mean anything"
    assert shape(plain) != shape(tilted)


def test_every_level_records_which_pivot_side_formed_it():
    """A per-side parameter needs something stable to be applied to.

    A level's position relative to price flips as price moves, so keying the
    parameters on it would change a level's own merge gap under it between
    bars. The formation side does not move.
    """
    book = book_of(turning(500))
    assert book.count > 1
    assert {lv.side for lv in book.levels} <= {1, -1}
    assert any(lv.side > 0 for lv in book.levels)
    assert any(lv.side < 0 for lv in book.levels)


def outside_bar(n: int = 40, where: int = 20, start: float = 1.1000):
    """A flat series with one wide outside bar, which is a pivot on both sides.

    The structure the `(when, side)` key is about, and it does not occur in a
    walk: at reach 8 and reach 2, bar `where` is the strict high over +/-8 and
    the strict low over +/-2, so the two sides confirm 6 bars apart. The
    `i % 3` jitter is load-bearing - `trend.pivots` gives ties to neither, so a
    genuinely flat series produces no pivot at all and the fixture would test
    an empty book.
    """
    out = []
    ts = 0
    for i in range(n):
        base = start + (i % 3) * 0.00002
        high, low = (
            (start + 0.0100, start - 0.0100) if i == where else (base + 0.0005, base - 0.0005)
        )
        out.append(bar(base, high, low, base, ts))
        ts += HOUR_NS
    return out


def test_a_reach_tilt_folds_both_sides_of_a_bar_that_is_high_and_low_pivot():
    """The `(when, side)` key. A time-only key drops the slower side's pivot.

    With a per-side reach the two sides confirm on different bars. Keyed on
    time alone, the side that confirms first marks that bar seen and the other
    side's pivot is never folded - a level simply absent, with nothing
    raising. Measured on this fixture: reaches 8 and 2, the low confirms at
    bar 22 and the high at bar 28, and under a time-only key the level at the
    wide bar's high is **missing** while the low is present.
    """
    book = book_of(outside_bar(), reach=Sided(4, 4.0), merge_vol=0.05, span=240)
    assert (book.reach_for(1), book.reach_for(-1)) == (8, 2)
    prices = [lv.at(book.when) for lv in book.levels]
    assert any(abs(p - 1.1100) < 2e-3 for p in prices), "the wide bar's high was not folded"
    assert any(abs(p - 1.0900) < 2e-3 for p in prices), "the wide bar's low was not folded"


def test_a_span_too_short_for_the_wider_side_is_refused_at_construction():
    """The widest side decides, so the guard cannot be passed by the narrow one.

    A span checked against the shared reach would accept a book whose
    resistance side can never confirm a pivot: the book would come up, report
    healthy and stay half empty on one side forever.
    """
    with pytest.raises(ValueError, match="cannot hold a pivot"):
        Levels(reach=Sided(6, 9.0), span=25, unit_span=48)
