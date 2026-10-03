"""v2 item 13: the candlestick vocabulary. Every pattern has a fixture that passes, one that fails
(one bar or one qualifier changed), and its flip twin (the bearish name on the mirrored chart), and is
known at its last bar. Fixtures are token tables built from explicit bars after a quiet warm-up (so the
point relations and lexemes are the bars'), with the rolling classes and grades of the pattern bars set
explicitly - neutral (MEDIUM, MODERATE) unless the fixture says otherwise - so each production is
tested on what it reads, as v1's pattern fixtures are."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pandas as pd
import pytest
from mcfl import candles, synth
from mcfl.core import Dir
from mcfl.grammar import frames, words
from mcfl.parse import flip, parse
from mcfl.vocabulary import BY_KEY, PATTERNS, TREND_PATTERNS, VOCAB, columns

NEUTRAL = {"size": "MEDIUM", "body": "MEDIUM", "upper": "MEDIUM", "lower": "MEDIUM", "conv_g": "MODERATE",
           "force_g": "MODERATE", "upper_g": "MODERATE", "lower_g": "MODERATE", "upper_share_g": "MODERATE",
           "lower_share_g": "MODERATE", "volume_class": "MEDIUM"}
S = {"force_g": "STRONG"}  # a long body

BEAR_LONG = (101.0, 101.1, 98.9, 99.0)
BULL_LONG = (99.0, 101.1, 98.9, 101.0)

# key: (rows (o, h, l, c), class overrides by row, the failing change: (row, new bar or None, overrides or None))
CASES = {
    "hammer": ([(100.0, 100.6, 98.0, 100.5)], {0: {"upper_g": "WEAK"}}, ("trend", "UP")),
    "inverted_hammer": ([(100.5, 102.5, 99.9, 100.0)], {0: {"lower_g": "WEAK"}}, ("trend", "MIXED")),
    "spinning_top": ([(100.0, 101.0, 99.0, 100.3)], {}, (0, (100.0, 101.0, 99.0, 100.8), None)),
    "high_wave": ([(100.0, 101.5, 98.5, 100.2)], {0: {"force_g": "WEAK", "upper_g": "STRONG", "lower_g": "STRONG"}},
                  (0, None, {"lower_g": "MODERATE"})),
    "doji": ([(100.0, 100.8, 99.2, 100.02)], {}, (0, (100.0, 100.8, 99.2, 100.3), None)),
    "long_legged_doji": ([(100.0, 101.0, 99.0, 100.02)], {0: {"upper_g": "STRONG", "lower_g": "STRONG"}},
                         (0, None, {"upper_g": "MODERATE"})),
    "dragonfly_doji": ([(100.0, 100.02, 99.0, 100.01)], {}, (0, (100.0, 100.5, 99.0, 100.01), None)),
    "four_price_doji": ([(100.0, 100.01, 99.99, 100.0)], {}, (0, (100.0, 100.3, 99.99, 100.0), None)),
    "takuri": ([(100.0, 100.02, 98.0, 100.01)], {0: {"lower_g": "DOMINANT", "upper_g": "WEAK"}},
               (0, None, {"lower_g": "STRONG"})),
    "belt_hold": ([(99.0, 100.6, 99.0, 100.5)], {0: S}, ("trend", "UP")),
    "marubozu": ([(99.0, 100.5, 99.0, 100.5)], {0: S}, (0, (99.0, 100.8, 99.0, 100.5), None)),
    "opening_marubozu": ([(99.0, 100.8, 99.0, 100.5)], {0: S}, (0, (99.0, 100.5, 99.0, 100.5), None)),
    "closing_marubozu": ([(99.3, 100.5, 99.0, 100.5)], {0: S}, (0, (99.3, 100.5, 99.3, 100.5), None)),
    "long_line": ([(99.2, 100.6, 99.0, 100.5)], {0: S}, (0, None, {"force_g": "MODERATE"})),
    "short_line": ([(100.0, 100.2, 99.9, 100.1)], {0: {"force_g": "WEAK", "upper_g": "WEAK", "lower_g": "WEAK"}},
                   (0, None, {"force_g": "MODERATE"})),
    # two bars
    "harami": ([BEAR_LONG, (99.3, 100.2, 99.1, 100.0)], {0: S}, (1, (99.3, 101.4, 99.1, 101.3), None)),
    "harami_cross": ([BEAR_LONG, (100.0, 100.3, 99.7, 100.02)], {0: S}, (1, (98.7, 99.0, 98.5, 98.72), None)),
    "piercing": ([BEAR_LONG, (98.5, 100.6, 98.4, 100.5)], {0: S, 1: S}, (1, (98.5, 99.9, 98.4, 99.8), None)),
    "on_neck": ([BULL_LONG, (101.5, 101.6, 100.9, 101.1)], {0: S}, (1, (101.5, 101.6, 100.4, 100.5), None)),
    "in_neck": ([BULL_LONG, (101.5, 101.6, 100.9, 101.02)], {0: S}, (1, (101.5, 101.6, 100.5, 100.6), None)),
    "thrusting": ([BULL_LONG, (101.5, 101.6, 100.2, 100.4)], {0: S}, (1, (101.5, 101.6, 99.7, 99.8), None)),
    "kicker": ([(101.0, 101.0, 99.0, 99.0), (101.5, 103.5, 101.5, 103.5)], {0: S, 1: S},
               (1, (100.9, 103.5, 100.9, 103.5), None)),
    "meeting_lines": ([BEAR_LONG, (97.0, 99.1, 96.9, 99.0)], {0: S, 1: S}, (1, (97.0, 98.6, 96.9, 98.5), None)),
    "separating_lines": ([BEAR_LONG, (101.0, 103.1, 101.0, 103.0)], {1: S}, (1, (101.5, 103.1, 101.5, 103.0), None)),
    "matching_low": ([BEAR_LONG, (100.0, 100.1, 98.95, 99.01)], {}, (1, (100.0, 100.1, 98.5, 98.6), None)),
    "homing_pigeon": ([BEAR_LONG, (100.5, 100.6, 99.2, 99.4)], {0: S}, (1, (100.5, 100.6, 98.6, 98.7), None)),
    "doji_star": ([BEAR_LONG, (98.5, 98.8, 98.2, 98.51)], {0: S}, (1, (99.0, 99.2, 98.8, 99.01), None)),
    "hikkake": ([(100.0, 101.0, 99.0, 100.5), (100.5, 100.8, 99.5, 100.2), (100.2, 100.4, 99.2, 99.4)], {},
                (2, (100.2, 100.4, 99.6, 99.7), None)),
    "modified_hikkake": ([(100.0, 101.0, 99.0, 100.5), (100.5, 100.9, 99.2, 99.3), (99.3, 100.0, 99.25, 99.8),
                          (99.8, 99.9, 99.0, 99.1)], {}, (1, (100.5, 100.9, 99.2, 100.5), None)),
    # three bars and more
    "three_soldiers": ([(100.0, 101.05, 99.9, 101.0), (101.0, 102.05, 100.9, 102.0), (102.0, 103.05, 101.9, 103.0)],
                       {0: {"upper_g": "WEAK"}, 1: {"upper_g": "WEAK"}, 2: {"upper_g": "WEAK"}},
                       (2, None, {"upper_g": "MODERATE"})),
    "advance_block": ([(103.0, 103.1, 101.0, 101.05), (101.05, 101.1, 99.7, 100.0), (100.0, 100.05, 98.5, 99.5)], {},
                      (2, (100.0, 100.05, 98.5, 98.8), None)),
    "stalled": ([(103.0, 103.1, 100.9, 101.0), BEAR_LONG, (99.0, 99.2, 98.6, 98.8)], {0: S, 1: S, 2: {"force_g": "WEAK"}},
                (2, None, {"force_g": "MODERATE"})),
    "three_inside": ([BEAR_LONG, (99.3, 100.2, 99.1, 100.0), (100.0, 101.3, 99.9, 101.2)], {0: S},
                     (2, (100.0, 100.9, 99.9, 100.8), None)),
    "three_outside": ([(100.5, 100.6, 99.4, 99.5), (99.4, 101.1, 99.3, 101.0), (101.0, 101.6, 100.9, 101.5)], {},
                      (2, (101.0, 101.1, 100.7, 100.8), None)),
    "morning_doji_star": ([(102.0, 102.1, 99.9, 100.0), (99.5, 99.8, 99.2, 99.51), (99.6, 101.6, 99.5, 101.5)],
                          {0: S, 2: S}, (1, (100.0, 100.2, 99.8, 100.01), None)),
    "abandoned_baby": ([(102.0, 102.1, 99.9, 100.0), (99.5, 99.6, 99.4, 99.51), (100.0, 101.6, 99.9, 101.5)], {0: S},
                       (2, (99.7, 101.6, 99.6, 101.5), None)),
    "tri_star": ([(100.0, 100.3, 99.7, 100.01), (99.5, 99.8, 99.2, 99.51), (100.0, 100.3, 99.7, 100.01)], {},
                 (1, (100.0, 100.3, 99.7, 100.01), None)),
    "three_line_strike": ([(100.0, 101.1, 99.9, 101.0), (101.0, 102.1, 100.9, 102.0), (102.0, 103.1, 101.9, 103.0),
                           (103.0, 103.2, 99.5, 99.8)], {}, (3, (103.0, 103.2, 100.1, 100.2), None)),
    "two_crows": ([(103.0, 103.1, 100.9, 101.0), (100.5, 100.8, 100.0, 100.7), (100.6, 102.6, 100.5, 102.5)], {0: S},
                  (2, (100.6, 103.6, 100.5, 103.5), None)),
    "upside_gap_two_crows": ([(103.0, 103.1, 100.9, 101.0), (100.5, 100.8, 100.4, 100.7), (100.3, 100.95, 100.2, 100.9)],
                             {0: S}, (2, (100.3, 101.3, 100.2, 101.2), None)),
    "stick_sandwich": ([BEAR_LONG, (99.2, 100.6, 99.1, 100.5), (100.5, 100.6, 98.9, 99.02)], {},
                       (2, (100.5, 100.6, 98.5, 98.6), None)),
    "unique_three_river": ([(102.0, 102.1, 99.9, 100.0), (101.0, 101.1, 99.0, 100.3), (99.5, 100.1, 99.4, 99.9)], {0: S},
                           (2, (98.9, 99.6, 98.8, 99.5), None)),
    "three_stars_in_south": ([(102.0, 102.1, 98.0, 100.0), (101.0, 101.1, 98.5, 100.0), (100.0, 100.02, 99.5, 99.52)],
                             {0: {"force_g": "STRONG", "lower_g": "STRONG"},
                              2: {"force_g": "WEAK", "upper_g": "WEAK", "lower_g": "WEAK"}},
                             (2, (100.0, 100.02, 98.4, 99.52), None)),
    "identical_three_crows": ([(100.0, 101.1, 99.9, 101.0), (101.0, 102.1, 100.9, 102.0), (102.0, 103.1, 101.9, 103.0)], {},
                              (2, (102.3, 103.1, 102.2, 103.0), None)),
    "tasuki_gap": ([(100.0, 101.1, 99.9, 101.0), (101.5, 102.6, 101.4, 102.5), (102.0, 102.1, 101.1, 101.2)], {},
                   (2, (102.0, 102.1, 100.7, 100.8), None)),
    "side_by_side_white_lines": ([(100.0, 101.1, 99.9, 101.0), (101.5, 102.6, 101.4, 102.5), (101.5, 102.6, 101.4, 102.4)],
                                 {}, (2, (101.5, 104.1, 101.4, 104.0), None)),
    "rising_three_methods": ([(99.0, 102.1, 98.9, 102.0), (101.8, 101.9, 101.0, 101.2), (101.2, 101.3, 100.5, 100.7),
                              (100.7, 100.9, 100.0, 100.2), (100.2, 103.1, 100.1, 103.0)], {0: S, 4: S},
                             (2, (101.2, 101.3, 98.5, 100.7), None)),
    "mat_hold": ([(99.0, 102.1, 98.9, 102.0), (102.5, 102.7, 102.0, 102.2), (102.2, 102.3, 101.5, 101.7),
                  (101.7, 101.8, 101.2, 101.4), (101.8, 103.1, 101.7, 103.0)], {0: S},
                 (4, (101.8, 102.6, 101.7, 102.5), None)),
    "breakaway": ([(102.0, 102.1, 99.9, 100.0), (99.5, 99.6, 98.9, 99.0), (99.0, 99.4, 98.4, 98.6),
                   (98.6, 99.2, 97.9, 98.1), (98.1, 99.8, 98.0, 99.7)], {0: S}, (4, (98.1, 100.4, 98.0, 100.3), None)),
    "concealing_baby_swallow": ([(103.0, 103.0, 102.0, 102.0), (102.0, 102.0, 101.0, 101.0), (100.5, 101.3, 100.2, 100.3),
                                 (101.5, 101.5, 99.5, 99.6)], {}, (3, (101.2, 101.2, 99.5, 99.6), None)),
    "ladder_bottom": ([(104.0, 104.1, 102.9, 103.0), (102.8, 102.9, 101.9, 102.0), (101.8, 101.9, 100.9, 101.0),
                       (100.8, 101.6, 100.0, 100.2), (101.0, 102.0, 100.9, 101.9)], {},
                      (4, (101.0, 101.5, 100.9, 101.4), None)),
    # reversal bars outside the canon
    "key_reversal": ([(100.0, 100.4, 99.6, 100.2)] * 8 + [(100.0, 100.2, 99.6, 99.7), (99.6, 100.6, 99.0, 100.5)], {},
                     (9, (99.7, 100.6, 99.58, 100.5), None)),
    "outside_reversal": ([(100.0, 100.5, 99.5, 99.8), (99.8, 101.0, 99.3, 100.9)], {}, (1, (99.8, 101.0, 99.3, 100.4), None)),
    "island_reversal_1": ([(100.0, 100.5, 99.5, 99.6), (98.5, 99.0, 98.0, 98.6), (99.6, 100.6, 99.5, 100.5)], {},
                          (2, (98.9, 100.6, 98.9, 100.5), None)),
    "island_reversal_2": ([(100.0, 100.5, 99.5, 99.6), (98.5, 99.0, 98.0, 98.6), (98.6, 98.9, 98.1, 98.7),
                           (99.6, 100.6, 99.5, 100.5)], {}, (2, (98.6, 99.6, 98.1, 98.7), None)),
    "island_reversal_3": ([(100.0, 100.5, 99.5, 99.6), (98.5, 99.0, 98.0, 98.6), (98.6, 98.9, 98.1, 98.7),
                           (98.7, 98.95, 98.2, 98.3), (99.6, 100.6, 99.5, 100.5)], {}, (3, (98.7, 99.6, 98.2, 98.3), None)),
    "island_reversal_4": ([(100.0, 100.5, 99.5, 99.6), (98.5, 99.0, 98.0, 98.6), (98.6, 98.9, 98.1, 98.7),
                           (98.7, 98.95, 98.2, 98.3), (98.3, 98.8, 98.0, 98.4), (99.6, 100.6, 99.5, 100.5)], {},
                          (4, (98.3, 99.6, 98.0, 98.4), None)),
    "two_bar_reversal": ([BEAR_LONG, (99.0, 101.2, 98.9, 101.1)], {0: S, 1: S}, (1, (99.0, 100.6, 98.9, 100.5), None)),
    "three_bar_reversal": ([(100.5, 100.6, 99.4, 99.5), (99.5, 99.7, 98.8, 99.2), (99.2, 100.2, 99.0, 100.1)], {},
                           (2, (99.2, 99.7, 99.0, 99.6), None)),
    "oops": ([(100.0, 100.5, 99.5, 99.8), (99.0, 99.6, 98.8, 99.4)], {}, (1, (99.0, 99.3, 98.8, 99.2), None)),
    "exhaustion_bar": ([(101.5, 101.6, 100.9, 101.0), (101.0, 101.1, 100.4, 100.5), (100.5, 100.6, 99.9, 100.0),
                        (100.0, 100.1, 97.0, 97.5)], {3: {"size": "VERY_LARGE", "force_g": "STRONG"}},
                       (3, None, {"size": "LARGE"})),
    "climax_bar": ([(100.0, 100.5, 99.5, 99.8), (99.8, 100.5, 97.0, 100.2)],
                   {1: {"size": "VERY_LARGE", "volume_class": "VERY_LARGE"}}, (1, None, {"volume_class": "LARGE"})),
    "signal_bar": ([(99.0, 100.55, 98.3, 100.5)], {0: {"upper_g": "WEAK"}}, (0, None, {"upper_g": "MODERATE"})),
    "trend_bar": ([(99.2, 100.6, 99.1, 100.5)], {0: {"body": "LARGE"}}, (0, None, {"body": "MEDIUM"})),
    "doji_bar": ([(100.0, 100.5, 99.5, 100.1)], {0: {"body": "SMALL"}}, (0, None, {"body": "MEDIUM"})),
}


def _table(rows, over, trend=None):
    df = pd.concat([F.bars(F.FINE), F.ohlc(rows)], ignore_index=True)
    T = candles.table(df, tick=0.01)
    candles.compression(T)
    n0 = len(F.FINE)
    T["volume_class"] = np.array(["MEDIUM"] * len(df), object)
    for j in range(len(rows)):
        for k, v in {**NEUTRAL, **over.get(j, {})}.items():
            T[k][n0 + j] = v
    st = np.array(["MIXED"] * len(df), object)
    if trend is not None:
        st[n0 - 1] = trend
    columns(T, st)
    return T


def _fire(T, key):
    cid, rid = candles.ids(T)
    return {e.at: e for e in words(T, cid, rid, table_={key: VOCAB[key]}, fr=frames(T))}


def _case(key):
    rows, over, fail = CASES[key]
    trend = BY_KEY[key].trend
    return rows, over, fail, trend


@pytest.mark.parametrize("key", list(CASES))
def test_pattern_passes_at_its_last_bar(key):
    rows, over, _, trend = _case(key)
    T = _table(rows, over, trend)
    last = len(F.FINE) + len(rows) - 1
    got = _fire(T, key)
    assert last in got, (key, sorted(got))
    e = got[last]
    p = BY_KEY[key]
    assert e.known_at == last and e.get("name") == p.up and e.dir is (Dir.NONE if p.sym else Dir.UP)
    assert e.type == "PATTERN" and e.parts[0].startswith("CANDLE.")
    assert sum(x.startswith("CANDLE.") for x in e.parts) == len(p.cells)


@pytest.mark.parametrize("key", list(CASES))
def test_pattern_fails(key):
    rows, over, fail, trend = _case(key)
    rows, over = list(rows), {k: dict(v) for k, v in over.items()}
    if fail[0] == "trend":
        trend = fail[1]
    else:
        j, bar, ov = fail
        if bar is not None:
            rows[j] = bar
        if ov is not None:
            over[j] = {**over.get(j, {}), **ov}
    T = _table(rows, over, trend)
    last = len(F.FINE) + len(rows) - 1
    assert last not in _fire(T, key)


@pytest.mark.parametrize("key", list(CASES))
def test_flip_twin(key):
    """On the mirrored chart the same bars make the twin: DOWN, with the bearish name."""
    rows, over, _, trend = _case(key)
    T = candles.frame(_table(rows, over, trend), -1)
    last = len(F.FINE) + len(rows) - 1
    got = _fire(T, key)
    p = BY_KEY[key]
    assert last in got and got[last].get("name") == p.down
    assert got[last].dir is (Dir.NONE if p.sym else Dir.DOWN)


def test_every_pattern_has_a_case_and_names_pair_up():
    assert {p.key for p in PATTERNS} == set(CASES)
    pairs = {(p.up, p.down) for p in PATTERNS}
    assert ("HAMMER", "SHOOTING_STAR") in pairs and ("INVERTED_HAMMER", "HANGING_MAN") in pairs
    assert ("PIERCING", "DARK_CLOUD") in pairs and ("THREE_WHITE_SOLDIERS", "THREE_BLACK_CROWS") in pairs
    assert set(TREND_PATTERNS) == {p.key for p in PATTERNS if p.trend}


def test_hammer_and_hanging_man_are_one_shape_named_by_the_trend():
    rows, over, _, _ = _case("hammer")
    up = _fire(_table(rows, over, "DOWN"), "hammer")
    assert up and list(up.values())[0].get("name") == "HAMMER"
    assert not _fire(_table(rows, over, "UP"), "hammer")
    # the same shape after an UP structure: flipped, it is an inverted hammer after a DOWN structure, so
    # the inverted_hammer word, run on the flipped side, finds it and names it HANGING_MAN
    got = _fire(_table(rows, over, "UP"), "inverted_hammer")
    (e,) = got.values()
    assert e.get("name") == "HANGING_MAN" and e.dir is Dir.DOWN and e.get("trend") == "UP"


@pytest.mark.parametrize("seed", [0, 1])
def test_on_walks_symmetric_and_attributed(seed):
    df = synth.ticks(synth.gapped(3000, seed=seed), seed=seed + 1)
    a, b = parse(df), parse(flip(df))
    pa = {(e.get("pattern"), e.at, e.dir.flip(), {p.up: p.down, p.down: p.up}.get(e.get("name"), e.get("name")))
          for e in a.of("PATTERN") for p in [BY_KEY.get(e.get("pattern")) or BY_KEY["island_reversal_1"]]}
    pb = {(e.get("pattern"), e.at, e.dir, e.get("name")) for e in b.of("PATTERN")}
    assert pa == pb and len({x[0] for x in pa}) > 40
    ids = a.by_id()
    for e in a.of("PATTERN"):
        assert e.known_at == e.at == max(ids[p].at for p in e.parts)
        first = min(ids[p].at for p in e.parts)
        assert e.get("trend") in ("UP", "DOWN", "MIXED") if first > 0 else e.get("trend") is None
