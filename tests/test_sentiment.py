"""Fear and greed from bars, and the split that makes it interpretable.

The composite is the part of this module least worth testing and the part a
caller is most likely to reach for, so most of what follows is about the
**halves**. On this desk the volatility half is measured large and the
direction half is measured closed, so a claim resting on one number cannot
say which of those it rests on - and a test suite that only checked the one
number would be agreeing with that confusion.

The other theme is that this reads bars and nothing else. There is no
sentiment feed here, and the published fear-and-greed indices need put/call
ratios, breadth and flows that this desk does not have. So the tests check
the components are what they claim to be, that every one is bounded, and that
none of them can see the future.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.indicators import build_detector
from till_infinity.indicators.sentiment import HALVES, SPAN, FearGreed, Mood


def grind(bars: int = 80, drift: float = 0.0008, seed: int = 3) -> FearGreed:
    """A calm advance: small positive drift, steady ranges."""
    rng = random.Random(seed)
    found = FearGreed()
    price = 100.0
    for _ in range(bars):
        price *= 1.0 + rng.gauss(drift, 0.002)
        found.update_raw(price * 0.999, price * 1.003, price * 0.998, price)
    return found


def crash(bars: int = 80, seed: int = 3) -> FearGreed:
    """A fall with ranges opening up, which is the fear shape."""
    rng = random.Random(seed)
    found = FearGreed()
    price = 100.0
    for i in range(bars):
        wide = 1.0 + i / 40.0
        price *= 1.0 + rng.gauss(-0.004 if i > 40 else 0.0005, 0.004 * wide)
        found.update_raw(
            price * 1.004, price * (1 + 0.004 * wide), price * (1 - 0.009 * wide), price
        )
    return found


# --------------------------------------------------------------- the two halves


def test_every_component_belongs_to_exactly_one_half():
    """The split is the design. A component with no half would be averaged
    into the composite and into neither half, so a claim could rest on it
    while both halves looked clean."""
    found = grind()
    assert set(found.parts) == set(HALVES)
    assert set(HALVES.values()) == {"direction", "volatility"}


def test_the_halves_are_reported_separately_from_the_composite():
    """Because the composite cannot say which half it rests on, and the two
    have opposite measured priors on this desk."""
    found = grind()
    assert found.volatile != found.reading
    assert found.directional != found.reading


def test_a_crash_reads_fear_on_the_direction_half():
    """The sign check that has to work before anything else means anything."""
    assert crash().directional < 0.0
    assert grind().directional > 0.0


def test_expanding_ranges_read_fear_on_the_volatility_half():
    """Expansion is the fear side by convention, which is exactly why it is
    reported apart rather than folded in silently."""
    rng = random.Random(11)
    opening, closing = FearGreed(), FearGreed()
    price = 100.0
    for i in range(80):
        wide = 1.0 + i / 30.0
        opening.update_raw(price, price * (1 + 0.01 * wide), price * (1 - 0.01 * wide), price)
        tight = 2.0 - i / 80.0
        closing.update_raw(price, price * (1 + 0.01 * tight), price * (1 - 0.01 * tight), price)
        price *= 1.0 + rng.gauss(0.0, 0.001)

    assert opening.parts["expansion"] < 0.0
    assert closing.parts["expansion"] > 0.0


def test_a_doubling_and_a_halving_are_the_same_distance_from_neutral():
    """`expansion` is symmetric in the log, so a regime twice as wide and one
    half as wide are equally far from calm. A plain ratio would make the
    expansion side bounded at -1 and the contraction side unbounded."""
    rng = random.Random(5)
    found = FearGreed()
    price = 100.0
    for _ in range(80):
        found.update_raw(price, price * 1.005, price * 0.995, price)
        price *= 1.0 + rng.gauss(0.0, 0.0005)
    assert found.parts["expansion"] == pytest.approx(0.0, abs=0.05)


def test_the_downside_heavy_series_reads_negative_skew():
    """The leverage effect, and the component with the best prior here: a down
    move raises volatility more than an up move of the same size. It is a
    volatility asymmetry rather than a direction claim."""
    found = FearGreed()
    price = 100.0
    for i in range(80):
        step = -0.02 if i % 5 == 0 else 0.004
        price *= 1.0 + step
        found.update_raw(price, price * 1.002, price * 0.998, price)
    assert found.parts["skew"] < 0.0


# ------------------------------------------------------------------ the bounds


def test_every_part_is_bounded():
    """A bounded reading can be compared across feeds and intervals without a
    scaler, which is the only reason to bound one."""
    for found in (grind(), crash(), grind(drift=0.05), crash(seed=9)):
        for name, value in found.parts.items():
            assert -1.0 <= value <= 1.0, f"{name}={value}"
        assert -1.0 <= found.reading <= 1.0


def test_a_violent_series_does_not_escape_the_bounds():
    """The case a clamp exists for: ranges growing by orders of magnitude."""
    found = FearGreed()
    price = 100.0
    for i in range(80):
        blow = 10.0 ** (i / 20.0)
        price *= 0.97
        found.update_raw(price, price * (1 + 0.01 * blow), price * (1 - 0.01 * blow), price)
    assert all(-1.0 <= v <= 1.0 for v in found.parts.values())


# ----------------------------------------------------------------- the warm-up


def test_nothing_is_published_before_the_warmup():
    """A share of down closes over three bars is noise, so a reading before
    the window has filled would be a number with no measurement behind it."""
    found = FearGreed(span=40, warmup=20)
    for i in range(19):
        found.update_raw(100.0, 101.0, 99.0, 100.0 + i * 0.01)

    assert found.parts == {}
    assert found.reading == 0.0
    assert found.initialized is False
    assert found.has_inputs is True, "it has seen bars, it just cannot speak yet"


def test_a_reading_appears_once_the_warmup_is_met():
    found = FearGreed(span=40, warmup=20)
    for i in range(20):
        found.update_raw(100.0, 101.0, 99.0, 100.0 + i * 0.01)
    assert found.initialized is True
    assert set(found.parts) == set(HALVES)


@pytest.mark.parametrize(
    ("span", "warmup", "why"),
    [
        (2, 2, "cannot carry a trailing distribution"),
        (40, 2, "must be between 3 and span"),
        (40, 41, "must be between 3 and span"),
    ],
)
def test_an_unusable_window_is_refused(span, warmup, why):
    """Below three bars there is no distribution, and a warm-up longer than
    the span never fills - both would return readings for ever without one."""
    with pytest.raises(ValueError, match=why):
        FearGreed(span=span, warmup=warmup)


# --------------------------------------------------------------- the causality


def test_a_reading_is_trailing_and_cannot_see_the_future():
    """**The check that matters most.** Every window here is trailing, so a
    reading taken at bar n must not change when bars after n arrive. A
    full-sample scaler is the usual way this is lost, and this desk has
    already had two leaks of that shape."""
    rng = random.Random(21)
    bars = []
    price = 100.0
    for _ in range(SPAN + 40):
        price *= 1.0 + rng.gauss(0.0, 0.003)
        bars.append((price * 0.999, price * 1.004, price * 0.996, price))

    early = FearGreed()
    for bar in bars[:70]:
        early.update_raw(*bar)
    taken = dict(early.parts)

    later = FearGreed()
    for bar in bars[:70]:
        later.update_raw(*bar)
    assert dict(later.parts) == taken

    for bar in bars[70:]:
        later.update_raw(*bar)
    assert dict(later.parts) != taken, "the reading must move as new bars arrive"


def test_the_window_is_bounded_so_the_reading_forgets():
    """A deque with a maxlen, checked on the live object rather than on the
    declaration - `restore-drops-deque-maxlen` is the recorded failure, where a
    capped field came back unbounded after a restore."""
    found = FearGreed(span=30, warmup=10)
    for i in range(200):
        found.update_raw(100.0, 101.0, 99.0, 100.0 + i * 0.001)
    assert len(found._closes) == 30
    assert found._closes.maxlen == 30


# ------------------------------------------------------------------ bad input


def test_a_bar_with_no_price_is_refused_rather_than_averaged_in():
    """It is bad data, and folding it would move a bounded reading with no way
    to see that it had."""
    found = grind()
    before = dict(found.parts)
    found.update_raw(0.0, 0.0, 0.0, 0.0)
    assert dict(found.parts) == before


def test_an_inverted_range_is_refused():
    """A high below a low is not a bar."""
    found = grind()
    before = dict(found.parts)
    found.update_raw(100.0, 98.0, 102.0, 100.0)
    assert dict(found.parts) == before


def test_a_flat_series_reads_neutral_rather_than_dividing_by_zero():
    """A dead feed is a real thing, and every component here has a zero
    denominator on one."""
    found = FearGreed(span=30, warmup=10)
    for _ in range(40):
        found.update_raw(100.0, 100.0, 100.0, 100.0)
    assert all(value == 0.0 for value in found.parts.values())
    assert found.reading == 0.0


# ---------------------------------------------------------------- the plumbing


def test_the_label_is_conventional_and_the_thresholds_are_not_measured():
    """Nothing here establishes that 0.5 is a boundary. The label exists so a
    journal line reads "fear" rather than "-0.63", and no gate should key on
    it - a smoke test on a synthetic crash read -0.33, inside the default
    edge, so the thresholds do not even fire on an obvious case."""
    assert crash().mood() is Mood.CALM
    assert crash().mood(edge=0.2) is Mood.FEAR
    assert grind().mood(edge=0.2) is Mood.GREED


def test_a_reset_forgets_everything():
    """Nautilus resets an indicator on a reconnect, and a reading carried
    through one would describe a window the object no longer holds."""
    found = grind()
    assert found.initialized is True
    found.reset()

    assert found.parts == {}
    assert found.reading == 0.0
    assert found.has_inputs is False
    assert len(found._closes) == 0


def test_registering_it_for_quotes_says_why_not():
    """Every part needs a bar's range or its body and a quote carries
    neither, so this would otherwise be an indicator that never spoke."""
    with pytest.raises(NotImplementedError, match="register_indicator_for_bars"):
        FearGreed().handle_quote_tick(object())


def test_two_windows_are_told_apart_by_the_identity():
    assert repr(FearGreed(span=30, warmup=10)) != repr(FearGreed(span=60, warmup=20))


# ======================================================================
# Added for research/docs/fear-greed.md, which rests on these four facts
# ======================================================================
#
# The study reports `volatile` and `directional` separately for every result,
# builds a six-leg risk-off index out of the components, and keys every gate on
# a trailing quantile rather than on `Mood`. Each of those depends on something
# above and beyond "the composite is right", and the four tests below are the
# ones whose failure would invalidate a table in that document rather than only
# a reading here.


def shaped(bars) -> FearGreed:
    """Fold `(open, high, low, close)` tuples in, one second apart.

    A deterministic builder beside the module's random `grind` and `crash`:
    the tests below assert a component's **exact** value off a counted fixture,
    which a seeded random series cannot support.
    """
    found = FearGreed()
    for i, (o, h, lo, c) in enumerate(bars):
        found.update_raw(o, h, lo, c, float(i))
    return found


def biased(n: int, up_in: int, out_of: int, step: float = 0.003) -> list[tuple]:
    """A series with exactly `up_in` of every `out_of` bars closing up.

    The count is the point: `pressure` is `(ups - downs) / decided`, so a
    fixture with a stated up-rate has a known `pressure` and the assertion can
    be a hand computation rather than a sign.
    """
    out = []
    price = 1.0
    width = 0.004
    for i in range(n):
        move = step if i % out_of < up_in else -step * 0.3
        nxt = price * (1.0 + move)
        mid = (price + nxt) / 2.0
        out.append((price, mid + width / 2.0, mid - width / 2.0, nxt))
        price = nxt
    return out


def test_the_catalogue_builds_it_and_refuses_a_source():
    """`fear_greed` is in `BAR_DETECTORS`, and it reads a bar's whole shape so
    there is nothing for a `Reading` to select.

    This is the wiring the study's own harness does not use - it drives
    `update_raw` directly - so without this test the registration in
    `indicators/__init__.py` is unexercised, and a sweep that passed a source
    and had it silently ignored would report a null for a question it never
    asked."""
    assert isinstance(build_detector("fear_greed"), FearGreed)

    with pytest.raises(ValueError, match="no source"):
        build_detector("fear_greed", "close")


def test_pressure_is_the_counted_share_of_up_closes():
    """Two bars up in every three reads `(2 - 1) / 3`, exactly.

    Asserted as arithmetic off a counted fixture rather than as a sign,
    because `pressure` is the one direction component the study relies on
    being **exact on a synthetic cross** - it reads closes only, so it
    survives the 1.7x range inflation that makes `position`, `conviction` and
    `expansion` unusable there. A `pressure` that drifted from its own
    definition would move the risk-off index on the crosses with nothing to
    show it had."""
    assert shaped(biased(81, 2, 3)).parts["pressure"] == pytest.approx(1.0 / 3.0)
    assert shaped(biased(80, 1, 4)).parts["pressure"] == pytest.approx(-0.5)
    assert shaped(biased(80, 2, 4)).parts["pressure"] == pytest.approx(0.0)


def test_the_halves_can_disagree():
    """Not a tautology: if the halves always moved together the split would be
    decoration, and `fear-greed.md`'s whole method - report both, attribute the
    claim to one - would be measuring the same thing twice. It also matters for
    the index, where `expansion` is oriented **without** the quote flip while
    the other four are flipped.

    A quiet drift down has a falling direction half and a *contracting*
    volatility half, so the two take opposite signs."""
    quiet = []
    price = 1.0
    for i in range(SPAN):
        width = 0.02 if i < SPAN - 12 else 0.002
        nxt = price * (1.0 - 0.0005)
        quiet.append((price, price + width, nxt - width, nxt))
        price = nxt
    found = shaped(quiet)

    assert found.directional < 0.0
    assert found.volatile > 0.0


def test_the_conventional_threshold_needs_three_bars_in_four_going_one_way():
    """`mood`'s +-0.5 is first reached at a **75% up-rate with no noise**.

    Measured on this fixture, which has a stated up-rate and otherwise
    identical bars: 55% up reads **+0.391**, 67% reads **+0.499** - still
    `CALM`, just under - and 75% reads **+0.537**, the first `GREED`. Three
    bars in four going one way for sixty bars is not a market.

    The measured counterpart is in `research/docs/fear-greed.md`: the six-leg
    risk-off index's **90th percentile is +0.15 to +0.19** over 19.25 years, so
    a gate at +-0.5 refuses everything. Every gate in that study keys on a
    trailing quantile for this reason and none reads `mood()`.

    A reader who finds `mood()` always `CALM` in production should find this
    test rather than a bug - which is why it also asserts that a **measured**
    edge fires, the control without which "the threshold is too wide" is
    indistinguishable from "`mood` refuses everything"."""
    market_like = shaped(biased(80, 11, 20))

    assert market_like.reading == pytest.approx(0.391, abs=0.02)
    assert market_like.mood() is Mood.CALM
    assert shaped(biased(81, 2, 3)).mood() is Mood.CALM
    assert shaped(biased(80, 3, 4)).mood() is Mood.GREED

    assert market_like.mood(edge=0.15) is Mood.GREED
    assert shaped(biased(80, 1, 20)).mood(edge=0.15) is Mood.FEAR


def test_convictions_sign_is_the_windows_net_move_not_the_recent_direction():
    """Deliberate and it looks wrong, so it is pinned.

    `_conviction` signs the body share by `close[-1] - close[0]` over the
    **whole trailing window**, so on a market that went nowhere it reads
    whichever phase the window happens to end in - about -0.5 on a closed
    oscillation. A caller reading `conviction` on a range is reading a phase,
    and `fear-greed.md` excludes it from the flat-market assertion for that
    reason rather than widening a tolerance until it passed."""
    amplitude, cycles, bars = 0.01, 8, 80
    span = bars // cycles
    closes = [1.0 + amplitude * math.sin(2.0 * math.pi * i / span) for i in range(bars + 1)]
    sine = [
        (
            closes[i],
            max(closes[i], closes[i + 1]) + amplitude / 8.0,
            min(closes[i], closes[i + 1]) - amplitude / 8.0,
            closes[i + 1],
        )
        for i in range(bars)
    ]
    found = shaped(sine)

    assert found.parts["position"] == pytest.approx(0.0, abs=0.05)
    assert found.parts["pressure"] == pytest.approx(0.0, abs=0.1)
    assert abs(found.parts["conviction"]) > 0.25
    assert found.parts["conviction"] * (sine[-1][3] - sine[0][3]) > 0.0


def test_a_dead_patch_at_the_end_of_the_window_does_not_raise():
    """**A production crash, found by a study and not by this file.**

    `_expansion` guarded the window's median range against zero and not the
    *recent* mean, so a window whose median is positive while its last fifth
    is all zero-range bars computed `log2(0 / middle)` and raised
    `ValueError: math domain error` - straight into Nautilus's bar handler,
    on any feed that goes flat for a fifth of the span. Gold's daily history
    carries three such bars, and twelve consecutive flat bars at the default
    span of 60 was enough.

    The two guards are not the same condition: a feed can range normally for
    most of a window and stop dead at the end, which is exactly what a halt
    or a holiday looks like.
    """
    found = FearGreed(span=20, warmup=10)
    for i in range(16):
        found.update_raw(100.0, 101.0, 99.0, 100.0 + i * 0.01)
    for _ in range(4):
        found.update_raw(100.0, 100.0, 100.0, 100.0)

    assert found.parts["expansion"] == 0.0
    assert found.initialized is True


def test_a_window_dead_throughout_is_the_other_guard():
    """The case that was already handled, kept beside the new one so a future
    change cannot satisfy one and lose the other."""
    found = FearGreed(span=20, warmup=10)
    for _ in range(20):
        found.update_raw(100.0, 100.0, 100.0, 100.0)
    assert found.parts["expansion"] == 0.0
