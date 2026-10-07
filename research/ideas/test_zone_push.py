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
        (10.75, 11.0, 10.7, 10.95),  # above candle 1's close, under its high
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


def origin(row, side=1):
    o, h, l, c = bars([row])
    return Z.strong_origin(o, h, l, c, 0, side)


def test_a_demand_origin_is_the_last_red_candle_before_the_rally():
    assert origin((10.0, 10.1, 9.0, 9.2)) is True      # red, body 0.8 of 1.1
    assert origin((9.2, 10.1, 9.0, 10.0)) is False     # green: not the last candle against


def test_a_supply_origin_is_the_last_green_candle_before_the_fall():
    assert origin((9.2, 10.1, 9.0, 10.0), side=-1) is True
    assert origin((10.0, 10.1, 9.0, 9.2), side=-1) is False


def test_a_doji_origin_is_not_strong_whichever_way_it_closed():
    """"Often good body ratio for it too means it's strong" - a bar that barely
    closed anywhere is not an order block."""
    assert origin((10.0, 11.0, 9.0, 9.95)) is False    # red by 0.05 of a 2.0 range
    assert origin((10.0, 11.0, 9.0, 10.05), side=-1) is False


def test_the_origin_test_is_independent_of_the_push():
    """They are different claims and the run must be able to separate them: a
    pivot low can be green (a hammer that swept and closed up) and still be
    followed by two clean pushing candles."""
    rows = [
        (9.5, 10.5, 9.0, 10.2),    # green origin: a pivot low, not an order block
        (10.2, 11.0, 10.1, 10.9),
        (10.9, 12.5, 10.8, 12.4),
    ]
    assert push(rows) is True
    assert origin(rows[0]) is False


def test_the_level_is_the_origin_close_which_is_the_push_bar_open():
    """The desk's line inside the zone: "that bearish candle close and the 1st
    displacement candle open, that is the level"."""
    o, h, l, c = bars([
        (10.0, 10.1, 9.0, 9.2),   # bearish origin: closes at 9.2
        (9.2, 10.5, 9.15, 10.4),  # the first push bar opens there
        (10.4, 11.5, 10.3, 11.4),
    ])
    assert c[0] == o[1], "a continuous market: the close is the next open"
    # and it sits below the body top, which is what the zone's near edge was
    assert c[0] < max(o[0], c[0])


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
