"""The L1 token layer: exact classes and grades at every boundary, close quartiles, the point
matrices and their named relations, the tolerance, flip symmetry, and agreement between the fuzzy
NONE classes and the within-bar relations."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from mcfl import candles as K
from mcfl import synth
from mcfl.core import COMPOSITE_POINTS, NAMED_POINTS, POINT_ALIASES, flip_points, point_twin
from mcfl.parse import flip


def _one(x, m, s, edges, names, zero):
    return K.classify(np.array([x]), np.array([m]), np.array([s]), edges, names, zero)[0]


# ---------------------------------------------------------------- classes and grades, every boundary

@pytest.mark.parametrize(("x", "want"), [
    (0.0, "NONE"), (7.0, "VERY_SMALL"), (8.0, "VERY_SMALL"), (8.5, "SMALL"), (9.0, "SMALL"), (9.5, "MEDIUM"),
    (11.0, "MEDIUM"), (11.5, "LARGE"), (12.0, "LARGE"), (13.0, "VERY_LARGE"), (14.0, "VERY_LARGE"),
    (14.5, "EXTREMELY_LARGE")])
def test_size_boundaries(x, want):
    # m = 10, s = 2: edges m - s = 8, m - s/2 = 9, m + s/2 = 11, m + s = 12, m + 2s = 14
    assert _one(x, 10.0, 2.0, K.SIZE_EDGES, K.SIZE[1:], "NONE") == want


@pytest.mark.parametrize(("x", "body", "grade", "wick", "wgrade"), [
    (0.0, "NONE", "WEAK", "NONE", "NONE"),
    (0.25, "SMALL", "WEAK", "SMALL", "WEAK"), (0.375, "SMALL", "WEAK", "SMALL", "WEAK"),
    (0.5, "MEDIUM", "MODERATE", "MEDIUM", "MODERATE"), (0.625, "MEDIUM", "MODERATE", "MEDIUM", "MODERATE"),
    (0.6875, "LARGE", "STRONG", "MEDIUM", "STRONG"), (0.75, "LARGE", "STRONG", "MEDIUM", "STRONG"),
    (0.8125, "TREND", "DOMINANT", "LARGE", "DOMINANT")])
def test_body_wick_and_grade_boundaries(x, body, grade, wick, wgrade):
    # m = 0.5, s = 0.25: edges 0.375 (m - s/2), 0.625 (m + s/2), 0.75 (m + s); all exact in binary
    m, s = 0.5, 0.25
    assert _one(x, m, s, K.BODY_EDGES, K.BODY[1:], "NONE") == body
    assert _one(x, m, s, K.GRADE_EDGES, K.GRADE, "WEAK") == grade
    assert _one(x, m, s, K.WICK_EDGES, K.WICK[1:], "NONE") == wick
    assert _one(x, m, s, K.GRADE_EDGES, K.GRADE, "NONE") == wgrade


def test_flat_window_is_the_middle_class():
    assert _one(3.0, 3.0, 0.0, K.SIZE_EDGES, K.SIZE[1:], "NONE") == "MEDIUM"
    assert _one(3.0, 3.0, 0.0, K.GRADE_EDGES, K.GRADE, "WEAK") == "MODERATE"


def _bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"]).assign(volume=1.0)


def test_rolling_classes_on_hand_built_bars():
    """Ranges 1, 3, 1, 3, ...: a full window has mean 2 and sd 1 exactly. Bodies 1 and 3 of a
    range of 4 for the shares: mean 0.5, sd 0.25."""
    rows = []
    for i in range(11):
        r = 1.0 if i % 2 == 0 else 3.0
        rows.append((100.0, 100.0 + r, 100.0, 100.0 + r / 2))
    T = K.table(_bars(rows))
    assert list(T["size"][:9]) == [K.WARMUP] * 9  # the window needs PERIOD bars, the current one included
    assert T["size"][9] == "LARGE"  # 3 <= m + 1.0 s = 3, the edge itself
    assert T["size"][10] == "VERY_SMALL"  # 1 <= m - 1.0 s = 1
    rows = []
    for i in range(11):
        b = 1.0 if i % 2 == 0 else 3.0
        w = (4.0 - b) / 2
        rows.append((100.0, 100.0 + b + w, 100.0 - w, 100.0 + b))
    T = K.table(_bars(rows))
    assert (T["body"][9], T["conv_g"][9]) == ("LARGE", "STRONG")  # 0.75 = m + s
    assert (T["body"][10], T["conv_g"][10]) == ("SMALL", "WEAK")  # 0.25 <= m - s/2
    assert T["upper"][9] == "SMALL" and T["upper"][10] == "MEDIUM"  # shares 0.125 and 0.375 around m 0.25
    assert T["force_g"][10] == K.WARMUP  # no ATR yet (it needs 15 bars), so no force grade


def test_conviction_grade_is_the_body_class_renamed():
    T = K.table(synth.garch(1500, seed=3))
    ren = {"NONE": "WEAK", "SMALL": "WEAK", "MEDIUM": "MODERATE", "LARGE": "STRONG", "TREND": "DOMINANT",
           K.WARMUP: K.WARMUP}
    assert all(ren[b] == g for b, g in zip(T["body"], T["conv_g"]))


@pytest.mark.parametrize(("a", "b", "q"), [
    (3.0, 1.0, "Q3"), (3.25, 1.0, "Q4"), (1.0, 3.0, "Q2"), (1.0, 3.25, "Q1"), (1.0, 1.0, "Q2"),
    (1.5, 1.0, "Q3"), (0.0, 0.0, "Q2")])
def test_close_quartile_boundaries(a, b, q):
    # close location (c - l) / (h - l) = a / (a + b): 0.75 is Q3, 0.25 is Q2, a tie is Q2
    c = np.array([10.0 + a])
    assert K.quartile(c, c + b, np.array([10.0]))[0] == q


# ---------------------------------------------------------------- point relations

PREV = (10.0, 12.0, 9.0, 11.0)  # o, h, l, c
CASES = {
    "OPEN_AT_PREV_CLOSE": (11, 11.5, 10.5, 11.2), "OPEN_GAP_UP": (11.5, 12, 11.2, 11.8),
    "OPEN_GAP_DOWN": (10.5, 11, 10.2, 10.8), "OPEN_AT_PREV_OPEN": (10, 10.5, 9.5, 10.2),
    "OPEN_ABOVE_PREV_HIGH": (12.5, 13, 12.2, 12.8), "OPEN_BELOW_PREV_LOW": (8.5, 8.8, 8, 8.2),
    "OPEN_AT_PREV_HIGH": (12, 12.5, 11.5, 12.2), "OPEN_AT_PREV_LOW": (9, 9.5, 8.5, 9.2),
    "CLOSE_AT_PREV_CLOSE": (10.5, 11.5, 10.2, 11), "CLOSE_AT_PREV_OPEN": (11, 11.2, 9.8, 10),
    "CLOSE_ABOVE_PREV_HIGH": (11, 12.8, 10.8, 12.5), "CLOSE_BELOW_PREV_LOW": (10, 10.2, 8.5, 8.8),
    "CLOSE_AT_PREV_HIGH": (11, 12.3, 10.8, 12), "CLOSE_AT_PREV_LOW": (10, 10.2, 8.8, 9),
    "HIGH_ABOVE_PREV_HIGH": (11, 12.5, 10.5, 12.2), "HIGH_AT_PREV_HIGH": (11, 12, 10.5, 11.5),
    "HIGH_BELOW_PREV_HIGH": (11, 11.5, 10.5, 11.2), "HIGH_AT_PREV_CLOSE": (10.5, 11, 10.2, 10.8),
    "HIGH_AT_PREV_OPEN": (9.5, 10, 9.2, 9.8), "HIGH_AT_PREV_LOW": (8.5, 9, 8, 8.8),
    "HIGH_BELOW_PREV_LOW": (8.5, 8.8, 8, 8.2), "LOW_BELOW_PREV_LOW": (9.5, 10, 8.5, 9.8),
    "LOW_AT_PREV_LOW": (9.5, 10, 9, 9.8), "LOW_ABOVE_PREV_LOW": (10, 10.5, 9.5, 10.2),
    "LOW_AT_PREV_CLOSE": (11.5, 12, 11, 11.8), "LOW_AT_PREV_OPEN": (10.5, 11, 10, 10.8),
    "LOW_AT_PREV_HIGH": (12.5, 13, 12, 12.8), "LOW_ABOVE_PREV_HIGH": (12.5, 13, 12.2, 12.8),
    "BODY_MIRROR": (11, 11.5, 9.5, 10),
    "OPEN_AT_HIGH": (11, 11, 10, 10.5), "OPEN_AT_LOW": (11, 12, 11, 11.5), "CLOSE_AT_HIGH": (11, 12, 10.5, 12),
    "CLOSE_AT_LOW": (11, 11.5, 10, 10), "OPEN_EQ_CLOSE": (11, 11.5, 10.5, 11),
}


def test_every_named_relation_has_a_case():
    assert set(CASES) == set(NAMED_POINTS) | set(COMPOSITE_POINTS)


@pytest.mark.parametrize("name", sorted(CASES))
def test_named_relation_on_a_pair_of_bars(name):
    T = K.table(_bars([PREV, CASES[name]]), tick=0.01)  # no ATR on two bars: the tolerance is the tick
    assert T["tol"][1] == 0.01
    have = T["within"][1] + T["named"][1]
    assert name in have, (name, have, T["points"][1])
    for alias, real in POINT_ALIASES.items():
        assert (alias in have) is False  # aliases are names for the grammar, not stored twice
        assert real in NAMED_POINTS


def test_named_relations_are_read_off_the_matrix():
    T = K.table(_bars([PREV, CASES["CLOSE_ABOVE_PREV_HIGH"]]), tick=0.01)
    pts = T["points"][1]
    assert len(pts) == 16 and set(pts) <= set("+=-")
    for name, (m, x, y, k) in NAMED_POINTS.items():
        cell = T[m][1][K.POINTS.index(x) * 4 + K.POINTS.index(y)]
        assert T[name][1] == (cell == k), name
    assert T["points"][0] is None and T["named"][0] == ()  # the first bar has no previous bar


def test_tolerance_boundary():
    """EQUAL is |difference| <= tol: at a tick of 0.25, an open 0.25 from the previous close is
    still AT it; 0.5 away it is a gap."""
    at = K.table(_bars([PREV, (11.25, 11.5, 11.0, 11.25)]), tick=0.25)
    gap = K.table(_bars([PREV, (11.5, 11.75, 11.25, 11.5)]), tick=0.25)
    assert "OPEN_AT_PREV_CLOSE" in at["named"][1] and "OPEN_GAP_UP" not in at["named"][1]
    assert "OPEN_GAP_UP" in gap["named"][1]


def test_tolerance_is_atr_or_tick():
    df = synth.walk(200, seed=1)
    T = K.table(df, tick=1e-6)
    a = T["atr"]
    ok = np.isfinite(a)
    assert np.allclose(T["tol"][ok], K.EQ_ATR * a[ok], rtol=0, atol=0)  # ATR term dominates a tiny tick
    assert (T["tol"][~ok] == 1e-6).all()
    est = K.table(df)  # no tick given: the running smallest non-zero difference, never growing
    assert (np.diff(K.tick_estimate(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close")))) <= 0).all()
    assert (est["tol"] >= K.EQ_ATR * np.nan_to_num(a)).all()


def test_fuzzy_none_agrees_with_within_bar_relations():
    T = K.table(synth.garch(3000, seed=7))
    live = T["size"] != K.WARMUP
    up, lo, body = (live & (T[k] == "NONE") for k in ("upper", "lower", "body"))
    assert up.sum() > 50 and lo.sum() > 50
    assert (T["OPEN_AT_HIGH"] | T["CLOSE_AT_HIGH"])[up].all()
    assert (T["OPEN_AT_LOW"] | T["CLOSE_AT_LOW"])[lo].all()
    assert T["OPEN_EQ_CLOSE"][body].all()


# ---------------------------------------------------------------- flip symmetry

def test_point_twins():
    pairs = {("OPEN_GAP_UP", "OPEN_GAP_DOWN"), ("HIGH_AT_PREV_HIGH", "LOW_AT_PREV_LOW"),
             ("HIGH_BELOW_PREV_LOW", "LOW_ABOVE_PREV_HIGH"), ("CLOSE_ABOVE_PREV_HIGH", "CLOSE_BELOW_PREV_LOW"),
             ("OPEN_AT_HIGH", "OPEN_AT_LOW"), ("CLOSE_AT_HIGH", "CLOSE_AT_LOW"),
             ("HIGH_ABOVE_PREV_HIGH", "LOW_BELOW_PREV_LOW"), ("HIGH_BELOW_PREV_HIGH", "LOW_ABOVE_PREV_LOW")}
    for a, b in pairs:
        assert point_twin(a) == b and point_twin(b) == a
    for n in list(NAMED_POINTS) + list(COMPOSITE_POINTS):
        assert point_twin(point_twin(n)) == n
    for n in ("OPEN_AT_PREV_CLOSE", "OPEN_AT_PREV_OPEN", "CLOSE_AT_PREV_CLOSE", "CLOSE_AT_PREV_OPEN",
              "BODY_MIRROR", "OPEN_EQ_CLOSE"):
        assert point_twin(n) == n
    assert flip_points(flip_points("+=-+--=++-==-+-=")) == "+=-+--=++-==-+-="


@pytest.mark.parametrize("seed", [2, 5])
def test_the_flipped_chart_has_the_flipped_table(seed):
    """Tokens of the flipped chart = the token table read in the flipped frame, column for column:
    BULL and BEAR, upper and lower (wick classes, shares, grades), Qk and Q(5-k), every named point
    relation and its twin, the matrices; size, body, and the body grades unchanged."""
    df = synth.garch(1500, seed=seed)
    T, Tf = K.table(df), K.table(flip(df))
    F = K.frame(T, -1)
    assert set(F) == set(Tf)
    for k in Tf:
        a, b = F[k], Tf[k]
        if a.dtype == object:
            assert list(a) == list(b), k
        else:
            assert np.array_equal(a, b, equal_nan=True), k
    for n in list(NAMED_POINTS) + list(COMPOSITE_POINTS):
        assert np.array_equal(T[n], Tf[point_twin(n)]), n
    assert list(T["size"]) == list(Tf["size"]) and list(T["force_g"]) == list(Tf["force_g"])
    assert list(T["upper_g"]) == list(Tf["lower_g"])
    q = {"Q1": "Q4", "Q2": "Q3", "Q3": "Q2", "Q4": "Q1"}
    assert [q[x] for x in T["close_q"]] == list(Tf["close_q"])
    swap = {"BULL": "BEAR", "BEAR": "BULL", "NONE": "NONE"}
    assert [swap[x] for x in T["dir"]] == list(Tf["dir"])
