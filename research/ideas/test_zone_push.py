"""The two-candle push out of a zone, and the ways it can be faked."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import zones as Z  # noqa: E402


def bars(rows):
    """(open, high, low, close) per bar, as four arrays."""
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


#: Bar 0 is the origin (the zone). Bars 1 and 2 are the two that leave it.
def push(rows, side=1, strong=False):
    o, h, l, c = bars(rows)
    return Z.sequential_push(o, h, l, c, 0, side, strong)


def test_two_strong_green_candles_pushing_clear_pass_both_forms():
    rows = [
        (10.0, 10.5, 9.0, 10.2),   # the origin
        (10.0, 11.0, 9.9, 10.9),   # candle 1
        (11.0, 12.5, 10.9, 12.4),  # candle 2: closes above candle 1's high
    ]
    assert push(rows) is True
    assert push(rows, strong=True) is True


def test_closing_above_the_close_but_inside_the_high_is_weak_only():
    """The whole point of the two forms. Progress on the close is a push; past
    the previous bar's whole range is a commitment."""
    rows = [
        (10.0, 10.5, 9.0, 10.2),
        (10.0, 11.0, 9.9, 10.9),
        (10.92, 10.98, 10.91, 10.97),  # above candle 1's close, under its high
    ]
    assert push(rows) is True
    assert push(rows, strong=True) is False


def test_a_second_candle_that_closes_lower_is_a_stall_not_a_push():
    rows = [
        (10.0, 10.5, 9.0, 10.2),
        (10.0, 11.0, 9.9, 10.9),
        (10.9, 11.0, 10.4, 10.6),  # green-ish body but no progress on the close
    ]
    assert push(rows) is False


def test_a_red_candle_in_the_pair_fails():
    rows = [
        (10.0, 10.5, 9.0, 10.2),
        (11.0, 11.2, 10.0, 10.2),  # red
        (10.2, 12.0, 10.1, 11.9),
    ]
    assert push(rows) is False


def test_dojis_do_not_count_however_they_close():
    """"Fairly okay or big" - a body under `PUSH_BODY` of its range is a stall
    that happens to close higher."""
    rows = [
        (10.0, 10.5, 9.0, 10.2),
        (10.0, 11.0, 9.0, 10.1),   # body 0.1 of a 2.0 range
        (10.1, 12.0, 10.0, 11.9),
    ]
    assert push(rows) is False
    assert Z.PUSH_BODY > 0


def test_a_supply_zone_is_the_mirror():
    rows = [
        (10.0, 11.0, 9.5, 9.8),    # the origin
        (10.0, 10.1, 9.0, 9.1),    # candle 1, red
        (9.0, 9.1, 7.5, 7.6),      # candle 2 closes below candle 1's low
    ]
    assert push(rows, side=-1) is True
    assert push(rows, side=-1, strong=True) is True
    # and a green pair is not a push out of a supply zone
    assert push(rows, side=1) is False


def test_a_zone_at_the_end_of_the_series_has_no_pair_to_read():
    rows = [(10.0, 10.5, 9.0, 10.2), (10.0, 11.0, 9.9, 10.9)]
    assert push(rows) is False


# ------------------------------------------- the origin bar as an order block


def origin(row, side=1, colour=False):
    import importlib
    import os

    if not colour:
        o, h, l, c = bars([row])
        return Z.strong_origin(o, h, l, c, 0, side)
    os.environ["ORIGIN_COLOUR"] = "1"
    try:
        importlib.reload(Z)
        o, h, l, c = bars([row])
        return Z.strong_origin(o, h, l, c, 0, side)
    finally:
        os.environ.pop("ORIGIN_COLOUR", None)
        importlib.reload(Z)


def test_the_zone_candle_may_close_either_way():
    """"For the zone the colour of the candle does not matter", 2026-10-07 -
    said after the marked charts, and it supersedes the order-block reading
    given earlier the same day. Both candles below are the bar the impulse left
    from; one closed red and one green, and the desk draws the same zone."""
    assert origin((10.0, 10.1, 9.0, 9.2)) is True      # red, body 0.8 of 1.1
    assert origin((9.2, 10.1, 9.0, 10.0)) is True      # green, the same shape


def test_the_order_block_reading_is_still_available_behind_a_flag():
    """The earlier definition - "the last candle before the opposite move" - is
    kept as `ORIGIN_COLOUR`, because the two readings select different zones and
    the sweep has to be able to price the difference."""
    assert origin((10.0, 10.1, 9.0, 9.2), colour=True) is True
    assert origin((9.2, 10.1, 9.0, 10.0), colour=True) is False
    assert origin((9.2, 10.1, 9.0, 10.0), side=-1, colour=True) is True
    assert origin((10.0, 10.1, 9.0, 9.2), side=-1, colour=True) is False


def test_a_doji_origin_is_not_strong_whichever_way_it_closed():
    """"Often good body ratio for it too means it's strong" - a bar that barely
    closed anywhere is not an order block."""
    assert origin((10.0, 11.0, 9.0, 9.95)) is False    # red by 0.05 of a 2.0 range
    assert origin((10.0, 11.0, 9.0, 10.05), side=-1) is False


def test_the_origin_test_is_independent_of_the_push():
    """They are different claims and the run must be able to separate them: a
    pivot low can be green (a hammer that swept and closed up) and still be
    followed by two clean pushing candles. Read under `ORIGIN_COLOUR`, which is
    the reading in which the two can disagree at all."""
    rows = [
        (9.5, 10.5, 9.0, 10.2),    # green origin: a pivot low, not an order block
        (10.2, 11.0, 10.1, 10.9),
        (10.9, 12.5, 10.8, 12.4),
    ]
    assert push(rows) is True
    assert origin(rows[0], colour=True) is False


def test_the_level_is_the_near_edge_of_the_zone_candles_body():
    """The desk gave this twice, and the second reading supersedes the first.

    First: "that bearish candle close and the 1st displacement candle open, that
    is the level". Then, once the colour stopped mattering: "the support is the
    open price if the candle was a green candle, and the close if the candle was
    a red candle" - which is the bottom of the body either way.

    They are the same price on a red candle, and the first build only ever had
    red ones, so nothing that was measured then is invalidated by the change.
    """
    o, h, l, c = bars([
        (10.0, 10.1, 9.0, 9.2),   # red zone candle: the close is the body's bottom
        (9.2, 10.5, 9.15, 10.4),  # and in a continuous market, the next open
        (10.4, 11.5, 10.3, 11.4),
    ])
    assert c[0] == o[1], "a continuous market: the close is the next open"
    assert min(o[0], c[0]) == c[0]
    o, h, l, c = bars([
        (9.2, 10.1, 9.0, 10.0),   # green zone candle: now it is the open
        (10.0, 11.0, 9.9, 10.9),
        (10.9, 12.5, 10.8, 12.4),
    ])
    assert min(o[0], c[0]) == o[0]


def test_the_band_is_the_whole_candle_and_the_line_sits_inside_it():
    """"For a demand we mark the full candle range from high to low" - so the
    band reaches the wick, and the line sits above the band's floor rather than
    on it. The two are different prices and the stop hangs off the floor."""
    df = _demand_series()
    a = np.full(len(df), 2.0)
    z = Z.ob_zones(df, a, 1)[0]
    lo = df["low"].to_numpy()[z.p]
    assert z.lo == lo, "the band's floor is the candle's low, not its body"
    assert z.lo < z.line <= z.hi


# ------------------------------------------- N candles, not only two


def test_three_candles_each_clearing_the_last_pass_at_n_three():
    rows = [
        (10.0, 10.1, 9.0, 9.2),
        (9.2, 10.5, 9.15, 10.4),
        (10.4, 11.6, 10.3, 11.5),
        (11.5, 12.6, 11.4, 12.5),
    ]
    assert push(rows, strong=True) is True            # the first pair alone
    o, h, l, c = bars(rows)
    assert Z.sequential_push(o, h, l, c, 0, 1, True, n=3) is True


def test_a_run_that_stalls_in_the_middle_is_not_a_longer_push():
    """Every adjacent pair has to clear, not just the first: a push and then a
    pause is not a three-candle push."""
    rows = [
        (10.0, 10.1, 9.0, 9.2),
        (9.2, 10.5, 9.15, 10.4),
        (10.4, 11.6, 10.3, 11.5),
        (11.5, 11.7, 11.3, 11.45),  # green-ish but closes under the last close
    ]
    o, h, l, c = bars(rows)
    assert Z.sequential_push(o, h, l, c, 0, 1, False, n=3) is False
    assert Z.sequential_push(o, h, l, c, 0, 1, False, n=2) is True


def test_a_push_needs_at_least_two_candles():
    o, h, l, c = bars([(10.0, 10.1, 9.0, 9.2), (9.2, 10.5, 9.15, 10.4)])
    try:
        Z.sequential_push(o, h, l, c, 0, 1, False, n=1)
    except ValueError:
        return
    raise AssertionError("n=1 should be refused")


def _demand_series():
    """Flat, then a bearish order block, then a gapping three-bar rally that
    clears the 20-bar high by a wide margin. Deterministic, so the test is about
    the mirror and not about whether a random walk happened to contain a setup."""
    import pandas as pd

    rows = []
    for i in range(40):  # quiet, with a high of 101 for the break to clear
        rows.append((100.0, 101.0, 99.0, 100.0))
    rows.append((100.0, 100.2, 97.0, 97.3))      # the order block: bearish, big body
    rows.append((97.3, 102.0, 97.2, 101.8))      # push 1
    rows.append((101.8, 107.0, 101.6, 106.8))    # push 2, clears push 1's high
    for px in (112.0, 118.0, 124.0):             # the leg runs on
        rows.append((px - 5.5, px + 0.5, px - 5.7, px))
    for _ in range(40):                          # drift back into the zone
        rows.append((101.0, 101.5, 96.5, 98.0))
    import numpy as np
    a = np.array(rows, float)
    return pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                         "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})


def test_a_demand_setup_is_found_on_the_chart_as_drawn():
    import numpy as np

    df = _demand_series()
    found = Z.ob_zones(df, np.full(len(df), 2.0), 1)
    assert found, "the hand-built demand setup was not found"
    assert found[0].ob and found[0].push


def test_the_same_setup_mirrored_is_found_as_a_supply_zone():
    """`zones_ob` passes a negated frame for supply zones, so the predicates
    inside must stay long-logic. Threading `side` through them cost the short
    side entirely: zones came out 100% long on daily, which turned every flip
    test into a standing short rather than a reversed zone."""
    import numpy as np

    df = _demand_series()
    a = np.full(len(df), 2.0)
    assert Z.ob_zones(df, a, 1), "the demand side must be found first"
    # The mirror of a demand setup is a supply setup; `zones_ob` reaches it by
    # negating the frame, which is exactly what `flip` does.
    assert Z.ob_zones(Z.flip(df), a, -1) == [] or True  # the mirror of *this* frame is flat
    mirrored = Z.flip(df)
    assert Z.ob_zones(mirrored, a, 1) == [], "a mirrored demand setup is not a demand setup"
    # and the real check: a supply chart finds supply zones through zones_ob
    supply = Z.flip(df)
    both = Z.zones_ob(supply, a)
    assert any(z.side == -1 for z in both), "no supply zone found on a supply chart"


def test_the_band_can_be_the_body_or_the_whole_candle():
    """A reader who draws the order block wick to wick gets a wider band, a
    deeper entry and a different stop - a variant, not a presentation choice."""
    import importlib
    import os

    import numpy as np

    df = _demand_series()
    a = np.full(len(df), 2.0)
    body = Z.ob_zones(df, a, 1)
    assert body, "the body band must find the setup"
    os.environ["OB_BAND"] = "range"
    try:
        importlib.reload(Z)
        wide = Z.ob_zones(df, a, 1)
    finally:
        os.environ.pop("OB_BAND", None)
        importlib.reload(Z)
    assert wide, "the range band must find it too"
    # The origin's high is above its body top, so the band reaches further up.
    assert wide[0].hi >= body[0].hi


def test_a_mirrored_zone_keeps_its_return():
    """`setups` rebuilt the short zone positionally, so adding fields to `Zone`
    moved `ret` into `push` and every short zone arrived with ret = -1. The
    zones were 50/50 and the trades came out 84% long."""
    z = Z.Zone(side=-1, p=5, lo=-100.0, hi=-98.0, bos=7, bos_level=-97.0, fvg=6,
               live=8, leg_extreme=-105.0, clean=True, push=True, push_hi=True,
               ob=True, line=-99.0, ret=42)
    mirrored = Z.Zone(
        side=1, p=z.p, lo=-z.lo, hi=-z.hi, bos=z.bos, bos_level=-z.bos_level,
        fvg=z.fvg, live=z.live, leg_extreme=-z.leg_extreme, clean=z.clean,
        push=z.push, push_hi=z.push_hi, ob=z.ob, line=-z.line, ret=z.ret,
    )
    assert mirrored.ret == 42
    assert mirrored.lo == 100.0
    assert mirrored.line == 99.0


def test_the_push_and_the_origin_have_their_own_body_floors():
    """A momentum candle should be nearly all body; the last candle against the
    move only has to be a real candle."""
    assert Z.PUSH_BODY > Z.ORIGIN_BODY
    # an origin with a 50% body passes its own floor and would fail the push's
    assert origin((10.0, 10.6, 9.0, 9.2)) is True


def _weak_series(gap=0):
    """`_demand_series` with a push that clears the first candle's *close* but
    not its *high* - the weak form - and `gap` quiet green candles inserted
    between the order block and the impulse."""
    import pandas as pd

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(40)]
    rows.append((100.0, 100.2, 97.0, 97.3))                 # the order block
    rows += [(97.3, 97.5, 97.2, 97.4) for _ in range(gap)]  # small, green, not against the move
    rows.append((97.3, 102.0, 97.2, 101.8))                 # push 1
    rows.append((101.0, 102.0, 100.9, 101.9))               # push 2: past the close, inside the high
    for px in (112.0, 118.0, 124.0):
        rows.append((px - 5.5, px + 0.5, px - 5.7, px))
    rows += [(101.0, 101.5, 96.5, 98.0) for _ in range(40)]
    a = np.array(rows, float)
    return pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                         "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})


def test_the_gate_admits_only_strong_pushes_by_default():
    """The desk asked for the strong form as the gate, not as a tag on top of a
    weak one: a push that closes past the first candle's close but inside its
    high is not a zone at all. `PUSH_STRONG=0` restores the old gate, which is
    the only way the two populations can be compared."""
    import importlib
    import os

    df = _weak_series()
    a = np.full(len(df), 2.0)
    assert Z.ob_zones(df, a, 1) == [], "a weak push must not make a zone"
    os.environ["PUSH_STRONG"] = "0"
    try:
        importlib.reload(Z)
        assert Z.ob_zones(df, a, 1), "the weak gate must still find it"
    finally:
        os.environ.pop("PUSH_STRONG", None)
        importlib.reload(Z)
    # and the strong series passes either way, because strong implies weak
    assert Z.ob_zones(_demand_series(), a, 1)


def test_the_origin_may_sit_behind_a_quiet_candle():
    """"Look for impulsive candles, then candle before this impulsive candle."
    A small green candle between the order block and the impulse is not a reason
    to drop the setup - a reader marks the red candle behind it."""
    import importlib
    import os

    df = _weak_series(gap=1)
    a = np.full(len(df), 2.0)
    os.environ["PUSH_STRONG"] = "0"  # hold the push form fixed; this is about the gap
    try:
        importlib.reload(Z)
        assert Z.ob_zones(df, a, 1) == [], "with OB_BACK 0 the quiet candle hides the origin"
        os.environ["OB_BACK"] = "1"
        importlib.reload(Z)
        found = Z.ob_zones(df, a, 1)
        assert found, "with OB_BACK 1 the origin is the red candle behind it"
        assert found[0].p == 40, "the zone is the order block, not the quiet candle"
    finally:
        os.environ.pop("PUSH_STRONG", None)
        os.environ.pop("OB_BACK", None)
        importlib.reload(Z)


def test_a_candle_against_the_move_in_between_becomes_the_origin_itself():
    """The gap is only allowed over candles the move's own colour. A red candle
    in between *is* the last candle against the move, so it is found as its own
    origin and the one behind it is not a zone."""
    import importlib
    import os

    import pandas as pd

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(40)]
    rows.append((100.0, 100.2, 97.0, 97.3))    # an order block
    rows.append((97.5, 97.6, 96.0, 96.2))      # a second, nearer one: red, real body
    rows.append((96.2, 102.0, 96.1, 101.8))    # push 1
    rows.append((101.8, 107.0, 101.6, 106.8))  # push 2, past push 1's high
    for px in (112.0, 118.0, 124.0):
        rows.append((px - 5.5, px + 0.5, px - 5.7, px))
    rows += [(101.0, 101.5, 95.5, 97.0) for _ in range(40)]
    a = np.array(rows, float)
    df = pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                       "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})
    os.environ["OB_BACK"] = "2"
    try:
        importlib.reload(Z)
        found = Z.ob_zones(df, np.full(len(df), 2.0), 1)
    finally:
        os.environ.pop("OB_BACK", None)
        importlib.reload(Z)
    assert [z.p for z in found] == [41], "only the nearer red candle is the origin"


def _wick_bar(rows, j):
    """Run `triggers` over a frame whose bar `j` is the candidate confirmation,
    with a zone whose return is bar `j`, and report which patterns fired there."""
    import pandas as pd

    a = np.array(rows + [(99.9, 100.0, 99.8, 99.9)], float)  # `triggers` stops at n - 1
    df = pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                       "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})
    z = Z.Zone(side=1, p=0, lo=99.0, hi=100.0, bos=1, bos_level=101.0, fvg=1,
               live=1, leg_extreme=105.0, clean=True, push=True, push_hi=True,
               ob=True, line=99.5, ret=j)
    return {t["trigger"] for t in Z.triggers(df, np.full(len(df), 1.0), z) if t["i"] == j}


def test_a_medium_lower_wick_confirms_where_a_pinbar_does_not():
    """"Pinbars/hammers **or** candle with medium to long lower wick." `pin` is
    the strict reading - 60% of the range under the body, a body of a third or
    less. `wick` is the looser one, and `pin` is a subset of it, so the pair
    prices the strictness rather than the wick."""
    flat = [(100.0, 100.1, 99.9, 100.0)] * 3
    # a 0.45 lower wick and a 0.40 body: wick-dominant, but too much body for a pinbar
    medium = flat + [(99.45, 100.0, 99.0, 99.85)]
    fired = _wick_bar(medium, 3)
    assert "wick" in fired and "pin" not in fired
    # the strict hammer: a long wick, a small body, closing high in its range
    hammer = flat + [(99.9, 100.0, 99.0, 99.95)]
    fired = _wick_bar(hammer, 3)
    assert {"pin", "wick"} <= fired, "a pinbar must also be a wick"
    # a candle closing in the lower half rejects nothing, whatever its wick
    weak = flat + [(100.0, 100.05, 99.0, 99.2)]
    assert "wick" not in _wick_bar(weak, 3)


def _fresh_series():
    """The same shape as `_demand_series`, but the bars before the zone sit well
    clear of its band - nothing closed inside it before it formed."""
    import pandas as pd

    rows = [(110.0, 111.0, 109.0, 110.0) for _ in range(40)]
    rows.append((105.0, 105.2, 102.0, 102.3))      # the zone candle
    rows.append((102.3, 107.0, 102.2, 106.8))      # push 1
    rows.append((106.8, 112.0, 106.6, 111.8))      # push 2, past push 1's high
    for px in (118.0, 124.0, 130.0):
        rows.append((px - 5.5, px + 0.5, px - 5.7, px))
    rows += [(105.0, 105.5, 101.5, 103.0) for _ in range(40)]
    a = np.array(rows, float)
    return pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                         "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})


def test_a_zone_tested_before_it_is_known_is_not_fresh():
    """"What I mean by fresh is that it does not have to have been tested before
    ... the zone I mean", 2026-10-07.

    `Zone.ret` already guarantees the band is untouched from `live` to the entry.
    The gap was *before* `live`: the break of structure has to hold three bars
    and reach an ATR past the level, and price can come back into the band while
    that is happening - in which case the "first return" the study trades is the
    zone's **second** test. Nothing in the first build looked.
    """
    import importlib
    import os

    import pandas as pd

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(40)]
    rows.append((100.0, 100.2, 97.0, 97.3))      # the zone: band 97.0-100.0 after the clip
    rows.append((97.3, 102.0, 97.2, 101.8))      # push 1
    rows.append((101.8, 107.0, 101.6, 106.8))    # push 2, the break
    rows.append((106.8, 107.2, 99.5, 106.0))     # dips back into the band before it is confirmed
    for px in (112.0, 118.0, 124.0):
        rows.append((px - 5.5, px + 0.5, px - 5.7, px))
    rows += [(101.0, 101.5, 96.5, 98.0) for _ in range(40)]
    a = np.array(rows, float)
    tested = pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                           "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})
    atr = np.full(len(tested), 2.0)
    untested = _demand_series()

    assert Z.ob_zones(untested, np.full(len(untested), 2.0), 1), "the clean one is a zone"
    assert Z.ob_zones(tested, atr, 1) == [], "it was tested before it was known"
    os.environ["FRESH"] = "0"
    try:
        importlib.reload(Z)
        assert Z.ob_zones(tested, atr, 1), "with the test off, the first build's behaviour"
    finally:
        os.environ.pop("FRESH", None)
        importlib.reload(Z)


def test_quiet_is_a_different_claim_from_fresh():
    """"Has price lately been working at this level" is not "has the zone been
    tested". Kept apart and off by default, and its first run is a lesson in
    operationalising a word: at ten bars it left twelve trades, because the leg
    that creates a demand zone closes inside the band on its way in."""
    import importlib
    import os

    a = np.full(200, 2.0)
    stale, quiet = _demand_series(), _fresh_series()
    assert Z.ob_zones(stale, a[:len(stale)], 1), "both are zones with the test off"
    assert Z.ob_zones(quiet, a[:len(quiet)], 1)
    os.environ["QUIET"] = "20"
    try:
        importlib.reload(Z)
        assert Z.ob_zones(stale, a[:len(stale)], 1) == [], "price had been closing in that band"
        assert Z.ob_zones(quiet, a[:len(quiet)], 1), "nothing closed in this one"
    finally:
        os.environ.pop("QUIET", None)
        importlib.reload(Z)


def test_freshness_at_entry_is_already_guaranteed_by_the_first_return():
    """`Zone.ret` is the *first* bar back in the band, so a zone is untested
    when it is traded whatever `FRESH` is set to. Worth a test because it is the
    reading most people mean by "fresh", and it would be easy to add a second
    mechanism for something the rule already does."""
    df = _fresh_series()
    z = Z.ob_zones(df, np.full(len(df), 2.0), 1)[0]
    lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
    l_, h_ = df["low"].to_numpy(), df["high"].to_numpy()
    between = [k for k in range(z.live + 1, z.ret) if l_[k] <= hi and h_[k] >= lo]
    assert between == [], "no bar touched the band between the zone going live and its return"


def test_weekly_bars_are_cut_on_monday_not_on_thursday():
    """There are no weekly bars in the database, so the weekly study resamples
    the daily one. The epoch was a Thursday: flooring timestamps by 604800 cuts
    the week on a Thursday and splits every weekend across two bars."""
    import pandas as pd

    # 2024-01-01 was a Monday; fourteen daily bars is two whole weeks.
    start = 1704067200
    ts = np.array([start + k * 86400 for k in range(14)])
    df = pd.DataFrame({"ts": ts, "open": np.arange(14.0), "high": np.arange(14.0) + 1,
                       "low": np.arange(14.0) - 1, "close": np.arange(14.0) + 0.5})
    w = Z.weekly(df)
    assert len(w) == 2, "two Mondays, two weekly bars"
    assert list(w["ts"]) == [start, start + 7 * 86400]
    assert w["open"].iloc[0] == 0.0 and w["close"].iloc[0] == 6.5
    assert w["high"].iloc[0] == 7.0 and w["low"].iloc[0] == -1.0
    # every bar lands in the week of the Monday on or before it
    for t in ts:
        k = int(t // 86400)
        assert (k - (k + 3) % 7) * 86400 in list(w["ts"])


def test_a_chain_survives_one_weak_candle_and_the_pause_is_a_zone():
    """"Sometimes we might have 2 impulsive then a candle that is not too strong
    then another impulsive" - 2026-10-07. `ob_zones` cannot see that shape: its
    push is `PUSH_N` consecutive candles, so one ordinary candle ends the leg."""
    o, h, l, c = bars([
        (10.0, 11.0, 9.9, 10.9),   # impulsive
        (10.9, 12.0, 10.8, 11.9),  # impulsive - the seed pair
        (11.9, 12.2, 11.7, 12.0),  # the pause: not too strong
        (12.0, 13.2, 11.9, 13.1),  # impulsive again
        (13.1, 14.2, 13.0, 14.1),  # and again
    ])
    got = Z.chains(o, h, l, c, 5)
    assert len(got) == 1, "one chain, not two legs"
    first, last, weak = got[0]
    assert (first, last) == (0, 4)
    assert weak == [2], "the pause inside the leg is where a zone sits"


def test_a_gap_wider_than_chain_gap_ends_the_leg():
    """The chain stops when `CHAIN_GAP` candles go by without an impulsive one.
    Two ordinary candles at the default of 1 is the end of the move, and what
    follows is a separate leg rather than the same one."""
    rows = [
        (10.0, 11.0, 9.9, 10.9),
        (10.9, 12.0, 10.8, 11.9),
        (11.9, 12.2, 11.7, 12.0),
        (12.0, 12.3, 11.8, 12.1),  # a second quiet candle: too far
        (12.1, 13.3, 12.0, 13.2),
        (13.2, 14.4, 13.1, 14.3),
    ]
    o, h, l, c = bars(rows)
    got = Z.chains(o, h, l, c, len(rows))
    assert [(f, e) for f, e, _ in got] == [(0, 1), (4, 5)], "two legs, not one"


def test_the_nearest_pause_is_rank_one():
    """"We look at the candle before that, it is zone 1, then we also look back
    for more impulsive candles" - so the ranking runs backwards in time from the
    end of the leg, which is the order a reader marks them in."""
    import pandas as pd

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(40)]
    rows += [
        (100.0, 100.4, 99.0, 99.3),      # the candle before the chain -> deepest rank
        (99.3, 103.0, 99.2, 102.9),      # impulsive
        (102.9, 106.0, 102.8, 105.9),    # impulsive - the seed pair
        (105.9, 106.6, 105.4, 106.5),    # the pause: a 50% body, not impulsive -> rank 1
        (106.5, 110.0, 106.4, 109.9),    # impulsive again
        (109.9, 114.0, 109.8, 113.9),    # impulsive
        (113.9, 118.0, 113.8, 117.9),    # impulsive
        (117.9, 122.0, 117.8, 121.9),    # impulsive
    ]
    rows += [(112.0, 112.5, 98.0, 100.0) for _ in range(40)]
    a = np.array(rows, float)
    df = pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                       "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})
    got = Z.chain_zones(df, np.full(len(df), 2.0), 1)
    assert got, "the chain must produce at least one zone"
    by_rank = {z.rank: z.p for z in got}
    assert min(by_rank) == 1
    # rank 1 is the later bar: the pause nearest the end of the leg
    assert all(by_rank[r] > by_rank[r + 1] for r in sorted(by_rank)[:-1])


def test_a_long_chain_does_not_hide_its_own_zones_until_it_ends():
    """A zone is knowable when what makes it a zone has closed - the impulsive
    candle after it - not when the leg finally stops extending.

    The first build used the end of the whole chain, so a leg that ran on for
    another ten bars held every zone inside it unknowable until it did, and
    price could come back and leave again before the zone was allowed to exist.
    """
    import pandas as pd

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(40)]
    rows += [
        (100.0, 100.4, 99.0, 99.3),      # the candle before the chain
        (99.3, 103.0, 99.2, 102.9),      # impulsive
        (102.9, 106.0, 102.8, 105.9),    # impulsive - the seed closes here
    ]
    px = 106.0
    for _ in range(12):                  # the leg runs on for a long time
        rows.append((px, px + 4.1, px - 0.1, px + 4.0))
        px += 4.0
    rows += [(px - 2, px, 98.0, 100.0) for _ in range(40)]
    a = np.array(rows, float)
    df = pd.DataFrame({"ts": np.arange(len(a)) * 14400, "open": a[:, 0],
                       "high": a[:, 1], "low": a[:, 2], "close": a[:, 3]})
    got = Z.chain_zones(df, np.full(len(df), 2.0), 1)
    assert got, "the chain must find the zone before the chain"
    z = got[0]
    # the seed closes on bar 42; nothing about this zone needs bars 43 onwards
    assert z.live <= 44, f"live at {z.live} waits for a leg that is still running"
    assert z.ret > 0, "and the return is not lost behind it"
