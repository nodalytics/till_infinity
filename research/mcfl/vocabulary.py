"""v2 item 13: the classical candlestick vocabulary, every pattern a production over the v1 candle
words, their strength grades and the OHLC point relations - no new price code beyond the lexeme
comparisons v1's words already make (VOID's `C0.low > C-2.high`).

Each pattern is written once, for its bullish (UP) side, and run on the chart and on the chart
flipped; the flipped instance is its twin and carries the twin's name (HAMMER <-> SHOOTING_STAR,
PIERCING <-> DARK_CLOUD, ...). A pattern with no direction (a doji) is one event, Dir.NONE. A pattern
whose canonical form is bearish is written as its mirror and named for the canon on its DOWN side
(ON_NECK, ADVANCE_BLOCK, TWO_CROWS, ...). Every PATTERN is known at its last bar, lists the CANDLE (and
BAR_RELATION) tokens it consumed, and carries

    name     the pattern's name on its side
    pattern  the pair's key (the id suffix): PATTERN.U.57.hammer
    trend    the STRUCTURE state (item 1) known at the bar before its first bar

Where the canon defines a pattern by the preceding trend, the trend is part of the production:
HAMMER / HANGING_MAN and INVERTED_HAMMER / SHOOTING_STAR (one shape each, named by the trend), and
BELT_HOLD. Every other pattern carries the trend as an attribute, so `PATTERN[trend=DOWN]` is the
canon's "after a downtrend" when it is wanted.

Building blocks (all in the qualifier syntax; the UP side):
    long body     body≥STRONG        (the force grade, body / ATR against its rolling distribution)
    short body    body≤MODERATE;  small: body≤WEAK
    doji          OPEN_EQ_CLOSE      (open and close within the point tolerance, 0.05 ATR)
    wick ratios   wick.low.body≥2    (the lower wick at least twice the body)
    point cells   o>pc, c≤po, ...    one cell of the point matrix: this bar's o/h/l/c against the
                                     previous bar's (`grammar` reads them as qualifiers)
    named points  OPEN_BELOW_PREV_LOW, CLOSE_AT_PREV_CLOSE, LOW_ABOVE_PREV_HIGH, ...
    lexemes       C("0.close", ">", "-2.body_mid"): a comparison of two tokens' prices, for bars that
                  are not adjacent (the point matrix relates neighbours only)
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from mcfl.candles import Table
from mcfl.core import SWAP_VALUE
from mcfl.grammar import C, Clause, Word, q

TREND_PATTERNS = ("hammer", "inverted_hammer", "belt_hold")
"""Patterns whose production includes the preceding STRUCTURE state."""


@dataclass(frozen=True)
class Pattern:
    key: str
    up: str  # its name on the UP (bullish) side
    down: str  # on the DOWN side (the twin)
    cells: dict[int, str]  # offset -> "quals" (CANDLE[...] without the brackets)
    where: tuple[Clause, ...] = ()
    rels: tuple[int, ...] | None = None  # BAR_RELATION offsets consumed (default: every cell but the first)
    trend: str | None = None  # the STRUCTURE state required at the bar before the first cell
    sym: bool = False  # no direction
    group: str = ""  # single, two, three, reversal
    doc: str = ""
    attrs: Callable[[Table, int, int], dict] | None = None


def _px(a: str, op: str, b, k: float | None = None) -> Clause:
    """A lexeme comparison: `a op b` (or `a op b * k`)."""
    return C(a, op, b if k is None else ("*", b, k))


def _eq(a: str, b: str, tol: str = "0.tol") -> tuple[Clause, ...]:
    """|a - b| <= the tolerance."""
    return C(a, "<=", ("+", b, tol)), C(a, ">=", ("+", b, ("*", tol, -1.0)))


LONG, SHORT, SMALL, DOJI = "body≥STRONG", "body≤MODERATE", "body≤WEAK", "OPEN_EQ_CLOSE"
IN_BODY_OF_BEAR = "o≤po, o≥pc, c≤po, c≥pc"  # this body inside the previous (bear) body: po top, pc bottom


def _signal_quality(F: Table, t: int, side: int) -> dict:
    """Brooks' bull signal bar, graded: STRONG with a lower tail of a quarter of the range or more and
    at most half its range inside the previous bar's, else WEAK."""
    ov = F["overlap"][t] if "overlap" in F else np.nan
    good = F["lower_share"][t] >= 0.25 and np.isfinite(ov) and ov <= 0.5
    return {"quality": "STRONG" if good else "WEAK"}


def _island(k: int) -> Pattern:
    """An island of k bars: a full gap down into it, k bars entirely below the gap, a full gap up."""
    first = -k
    cells = {first - 1: "", first: "HIGH_BELOW_PREV_LOW", 0: "LOW_ABOVE_PREV_HIGH, dir=BULL"}
    where = []
    for j in range(first + 1, 0):
        cells[j] = ""
        where.append(_px(f"{j}.high", "<", f"{first - 1}.low"))
    for j in range(first, 0):
        where.append(_px("0.low", ">", f"{j}.high"))
    return Pattern(f"island_reversal_{k}", "ISLAND_REVERSAL", "ISLAND_REVERSAL", cells, tuple(where),
                   rels=(first, 0), group="reversal",
                   doc=f"a full gap down, {k} bar(s) wholly below it, a full gap up out of them")


PATTERNS: tuple[Pattern, ...] = (
    # ---------------------------------------------------------------- single bars
    Pattern("hammer", "HAMMER", "SHOOTING_STAR", {0: "wick.low.body≥2, wick.up≤WEAK, body≤MODERATE, close≥Q3"},
            trend="DOWN", group="single", doc="a lower wick twice the body, little upper wick, after a down structure"),
    Pattern("inverted_hammer", "INVERTED_HAMMER", "HANGING_MAN",
            {0: "wick.up.body≥2, wick.low≤WEAK, body≤MODERATE, close≤Q2"}, trend="DOWN", group="single",
            doc="the hammer's shape upside down after a down structure (its twin, the hammer's shape after "
                "an up structure, is the hanging man)"),
    Pattern("spinning_top", "SPINNING_TOP", "SPINNING_TOP",
            {0: f"dir=BULL, {SHORT}, not {DOJI}, wick.up.body>1, wick.low.body>1"}, group="single",
            doc="a short body with both wicks longer than it"),
    Pattern("high_wave", "HIGH_WAVE", "HIGH_WAVE",
            {0: f"dir=BULL, {SMALL}, not {DOJI}, wick.up≥STRONG, wick.low≥STRONG, wick.up.body≥3, wick.low.body≥3"},
            group="single", doc="a small body with very long wicks both ways"),
    Pattern("doji", "DOJI", "DOJI", {0: DOJI}, sym=True, group="single", doc="open and close equal"),
    Pattern("long_legged_doji", "LONG_LEGGED_DOJI", "LONG_LEGGED_DOJI",
            {0: f"{DOJI}, wick.up≥STRONG, wick.low≥STRONG"}, sym=True, group="single",
            doc="a doji with strong wicks both ways"),
    Pattern("dragonfly_doji", "DRAGONFLY_DOJI", "GRAVESTONE_DOJI", {0: f"{DOJI}, CLOSE_AT_HIGH, wick.low≥MODERATE"},
            group="single", doc="a doji at the bar's high with a lower wick (twin: at the low, an upper wick)"),
    Pattern("four_price_doji", "FOUR_PRICE_DOJI", "FOUR_PRICE_DOJI", {0: f"{DOJI}, OPEN_AT_HIGH, OPEN_AT_LOW"},
            sym=True, group="single", doc="open, high, low and close all equal"),
    Pattern("takuri", "TAKURI", "TAKURI", {0: f"{DOJI}, wick.up≤WEAK, wick.low≥DOMINANT"}, group="single",
            doc="a dragonfly-like doji with a dominant lower wick"),
    Pattern("belt_hold", "BELT_HOLD", "BELT_HOLD", {0: f"dir=BULL, {LONG}, OPEN_AT_LOW"}, trend="DOWN",
            group="single", doc="a long bull body opening at its low, after a down structure"),
    Pattern("marubozu", "MARUBOZU", "MARUBOZU", {0: f"dir=BULL, {LONG}, OPEN_AT_LOW, CLOSE_AT_HIGH"},
            group="single", doc="FULL: a long body with no wick either way"),
    Pattern("opening_marubozu", "OPENING_MARUBOZU", "OPENING_MARUBOZU",
            {0: f"dir=BULL, {LONG}, OPEN_AT_LOW, not CLOSE_AT_HIGH"}, group="single",
            doc="no wick at the open's end"),
    Pattern("closing_marubozu", "CLOSING_MARUBOZU", "CLOSING_MARUBOZU",
            {0: f"dir=BULL, {LONG}, CLOSE_AT_HIGH, not OPEN_AT_LOW"}, group="single",
            doc="no wick at the close's end"),
    Pattern("long_line", "LONG_LINE", "LONG_LINE", {0: f"dir=BULL, {LONG}, wick.up≤MODERATE, wick.low≤MODERATE"},
            group="single", doc="a long body, modest wicks"),
    Pattern("short_line", "SHORT_LINE", "SHORT_LINE", {0: f"dir=BULL, {SMALL}, not {DOJI}, wick.up≤WEAK, wick.low≤WEAK"},
            group="single", doc="a small body, small wicks"),
    # ---------------------------------------------------------------- two bars
    Pattern("harami", "HARAMI", "HARAMI", {-1: f"dir=BEAR, {LONG}", 0: f"{SHORT}, not {DOJI}, {IN_BODY_OF_BEAR}"},
            group="two", doc="a long bear body, then a short body inside it"),
    Pattern("harami_cross", "HARAMI_CROSS", "HARAMI_CROSS", {-1: f"dir=BEAR, {LONG}", 0: f"{DOJI}, o≤po, o≥pc"},
            group="two", doc="a long bear body, then a doji inside it"),
    Pattern("piercing", "PIERCING", "DARK_CLOUD", {-1: f"dir=BEAR, {LONG}", 0: f"dir=BULL, {LONG}, OPEN_BELOW_PREV_LOW, c<po"},
            (_px("0.close", ">", "-1.body_mid"),), group="two",
            doc="a long bear, then a long bull opening under its low and closing above its body's middle"),
    Pattern("on_neck", "ON_NECK", "ON_NECK", {-1: f"dir=BULL, {LONG}", 0: "dir=BEAR, OPEN_ABOVE_PREV_HIGH, CLOSE_AT_PREV_HIGH"},
            group="two", doc="canon bearish (DOWN): a long bear, a bull opening under its low and closing at it"),
    Pattern("in_neck", "IN_NECK", "IN_NECK", {-1: f"dir=BULL, {LONG}", 0: "dir=BEAR, OPEN_ABOVE_PREV_HIGH, CLOSE_AT_PREV_CLOSE"},
            group="two", doc="canon bearish: the bull closes at the bear's close"),
    Pattern("thrusting", "THRUSTING", "THRUSTING", {-1: f"dir=BULL, {LONG}", 0: "dir=BEAR, OPEN_ABOVE_PREV_HIGH, c<pc"},
            (_px("0.close", ">", "-1.body_mid"),), group="two",
            doc="canon bearish: the bull closes into the bear's body, short of its middle"),
    Pattern("kicker", "KICKER", "KICKER",
            {-1: f"dir=BEAR, {LONG}, OPEN_AT_HIGH, CLOSE_AT_LOW", 0: f"dir=BULL, {LONG}, OPEN_AT_LOW, CLOSE_AT_HIGH, LOW_ABOVE_PREV_HIGH"},
            group="two", doc="a bear marubozu, then a bull marubozu wholly above it"),
    Pattern("meeting_lines", "MEETING_LINES", "MEETING_LINES",
            {-1: f"dir=BEAR, {LONG}", 0: f"dir=BULL, {LONG}, CLOSE_AT_PREV_CLOSE"}, group="two",
            doc="counterattack: opposite long bodies closing at the same price"),
    Pattern("separating_lines", "SEPARATING_LINES", "SEPARATING_LINES",
            {-1: "dir=BEAR", 0: f"dir=BULL, {LONG}, OPEN_AT_PREV_OPEN, OPEN_AT_LOW"}, group="two",
            doc="opposite bodies opening at the same price, the second a belt hold"),
    Pattern("matching_low", "MATCHING_LOW", "MATCHING_HIGH", {-1: "dir=BEAR", 0: "dir=BEAR, CLOSE_AT_PREV_CLOSE"},
            group="two", doc="two bears closing at the same price"),
    Pattern("homing_pigeon", "HOMING_PIGEON", "HOMING_PIGEON", {-1: f"dir=BEAR, {LONG}", 0: f"dir=BEAR, {SHORT}, o≤po, c≥pc"},
            group="two", doc="a long bear, then a short bear inside its body"),
    Pattern("doji_star", "DOJI_STAR", "DOJI_STAR", {-1: f"dir=BEAR, {LONG}", 0: f"{DOJI}, OPEN_GAP_DOWN"},
            group="two", doc="a long bear, then a doji opening below its close"),
    Pattern("hikkake", "HIKKAKE", "HIKKAKE", {-2: "", -1: "rel=INSIDE", 0: "HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW"},
            group="two", doc="an inside bar, then a false break of it downward (a lower high and a lower low)"),
    Pattern("modified_hikkake", "MODIFIED_HIKKAKE", "MODIFIED_HIKKAKE",
            {-3: "", -2: "rel=INSIDE, close≤Q1", -1: "rel=INSIDE", 0: "HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW"},
            group="two", doc="the hikkake after two inside bars, the first closing near its low"),
    # ---------------------------------------------------------------- three bars and more
    Pattern("three_soldiers", "THREE_WHITE_SOLDIERS", "THREE_BLACK_CROWS",
            {-2: "dir=BULL, body≥MODERATE, wick.up≤WEAK, close≥Q3",
             -1: "dir=BULL, body≥MODERATE, wick.up≤WEAK, close≥Q3, c>pc, o≥po, o≤pc",
             0: "dir=BULL, body≥MODERATE, wick.up≤WEAK, close≥Q3, c>pc, o≥po, o≤pc"}, group="three",
            doc="three bulls, each closing higher near its high and opening within the last body"),
    Pattern("advance_block", "ADVANCE_BLOCK", "ADVANCE_BLOCK",
            {-2: "dir=BEAR", -1: "dir=BEAR, c<pc, o≤po, o≥pc", 0: "dir=BEAR, c<pc, o≤po, o≥pc"},
            (_px("0.body_atr", "<", "-1.body_atr"), _px("-1.body_atr", "<", "-2.body_atr"),
             _px("0.lower_atr", ">", "-2.lower_atr")), group="three",
            doc="canon bearish: three bulls rising with shrinking bodies and growing upper wicks"),
    Pattern("stalled", "STALLED", "STALLED",
            {-2: f"dir=BEAR, {LONG}", -1: f"dir=BEAR, {LONG}, c<pc", 0: f"dir=BEAR, {SMALL}, OPEN_AT_PREV_CLOSE"},
            group="three", doc="canon bearish (deliberation): two long bulls, then a small one opening at the close"),
    Pattern("three_inside", "THREE_INSIDE_UP", "THREE_INSIDE_DOWN",
            {-2: f"dir=BEAR, {LONG}", -1: f"{SHORT}, {IN_BODY_OF_BEAR}", 0: "dir=BULL"},
            (_px("0.close", ">", "-2.open"),), group="three", doc="a harami, then a close above the first open"),
    Pattern("three_outside", "THREE_OUTSIDE_UP", "THREE_OUTSIDE_DOWN",
            {-2: "dir=BEAR", -1: "dir=BULL, engulf=BULL", 0: "dir=BULL, c>pc"}, group="three",
            doc="an engulfing, then a higher close"),
    Pattern("morning_doji_star", "MORNING_DOJI_STAR", "EVENING_DOJI_STAR",
            {-2: f"dir=BEAR, {LONG}", -1: f"{DOJI}, OPEN_GAP_DOWN", 0: f"dir=BULL, {LONG}"},
            (_px("0.close", ">", "-2.body_mid"),), group="three",
            doc="a long bear, a doji below its close, a long bull past the first body's middle"),
    Pattern("abandoned_baby", "ABANDONED_BABY", "ABANDONED_BABY",
            {-2: f"dir=BEAR, {LONG}", -1: f"{DOJI}, HIGH_BELOW_PREV_LOW", 0: "dir=BULL, LOW_ABOVE_PREV_HIGH"},
            (_px("0.close", ">", "-2.body_mid"),), group="three",
            doc="a doji wholly below a long bear and wholly below the bull after it"),
    Pattern("tri_star", "TRI_STAR", "TRI_STAR", {-2: DOJI, -1: f"{DOJI}, OPEN_GAP_DOWN", 0: f"{DOJI}, OPEN_GAP_UP"},
            group="three", doc="three dojis, the middle one below the others"),
    Pattern("three_line_strike", "THREE_LINE_STRIKE", "THREE_LINE_STRIKE",
            {-3: "dir=BULL", -2: "dir=BULL, c>pc", -1: "dir=BULL, c>pc", 0: "dir=BEAR, o≥pc"},
            (_px("0.close", "<", "-3.open"),), group="three",
            doc="three rising bulls, then a bear from their close to below the first open"),
    Pattern("two_crows", "TWO_CROWS", "TWO_CROWS",
            {-2: f"dir=BEAR, {LONG}", -1: "dir=BULL, o<pc, c<pc", 0: "dir=BULL, o≥po, o≤pc"},
            (_px("0.close", ">", "-2.close"), _px("0.close", "<", "-2.open")), group="three",
            doc="canon bearish: a long bull, a bear gapping above it, a bear opening in that one and closing in the first"),
    Pattern("upside_gap_two_crows", "UPSIDE_GAP_TWO_CROWS", "UPSIDE_GAP_TWO_CROWS",
            {-2: f"dir=BEAR, {LONG}", -1: "dir=BULL, o<pc, c<pc", 0: "dir=BULL, o<po, c>pc"},
            (_px("0.close", "<", "-2.close"),), group="three",
            doc="canon bearish: a long bull, a bear gapping above, a bear engulfing it that keeps the gap"),
    Pattern("stick_sandwich", "STICK_SANDWICH", "STICK_SANDWICH", {-2: "dir=BEAR", -1: "dir=BULL, l>pc", 0: "dir=BEAR"},
            _eq("0.close", "-2.close"), group="three", doc="two bears closing at one price around a bull above them"),
    Pattern("unique_three_river", "UNIQUE_THREE_RIVER", "UNIQUE_THREE_RIVER",
            {-2: f"dir=BEAR, {LONG}", -1: "dir=BEAR, o≤po, c≥pc, LOW_BELOW_PREV_LOW", 0: f"dir=BULL, {SHORT}, c<pc"},
            (_px("0.open", ">", "-1.low"),), group="three",
            doc="a long bear, a bear harami with a lower low, a small bull under its close"),
    Pattern("three_stars_in_south", "THREE_STARS_IN_SOUTH", "THREE_STARS_IN_SOUTH",
            {-2: f"dir=BEAR, {LONG}, wick.low≥STRONG", -1: f"dir=BEAR, {SHORT}, LOW_ABOVE_PREV_LOW, o≤ph",
             0: f"dir=BEAR, {SMALL}, wick.up≤WEAK, wick.low≤WEAK, rel=INSIDE"}, group="three",
            doc="three shrinking bears, each low higher, the last a small marubozu inside the second"),
    Pattern("identical_three_crows", "IDENTICAL_THREE_CROWS", "IDENTICAL_THREE_CROWS",
            {-2: "dir=BULL", -1: "dir=BULL, OPEN_AT_PREV_CLOSE, c>pc", 0: "dir=BULL, OPEN_AT_PREV_CLOSE, c>pc"},
            group="three", doc="canon bearish: three bears each opening at the last close"),
    Pattern("tasuki_gap", "TASUKI_GAP", "TASUKI_GAP", {-2: "dir=BULL", -1: "dir=BULL, o>pc", 0: "dir=BEAR, o≤pc, o≥po"},
            (_px("0.close", "<", "-1.open"), _px("0.close", ">", "-2.close")), group="three",
            doc="a bull, a bull gapping above it, a bear from inside that one into the gap, not closing it"),
    Pattern("side_by_side_white_lines", "SIDE_BY_SIDE_WHITE_LINES", "SIDE_BY_SIDE_WHITE_LINES",
            {-2: "dir=BULL", -1: "dir=BULL, o>pc", 0: "dir=BULL, OPEN_AT_PREV_OPEN"},
            (_px("0.body_atr", "<=", "-1.body_atr", 1.5), _px("0.body_atr", ">=", "-1.body_atr", 1 / 1.5)),
            group="three", doc="a bull, then two like bulls side by side above a gap"),
    Pattern("rising_three_methods", "RISING_THREE_METHODS", "FALLING_THREE_METHODS",
            {-4: f"dir=BULL, {LONG}", -3: f"{SHORT}, dir=BEAR", -2: f"{SHORT}, c<pc", -1: f"{SHORT}, c<pc", 0: f"dir=BULL, {LONG}"},
            tuple(c for j in (-3, -2, -1) for c in (_px(f"{j}.high", "<=", "-4.high"), _px(f"{j}.low", ">=", "-4.low")))
            + (_px("0.close", ">", "-4.close"),), group="three",
            doc="a long bull, three short falling bars within its range, a long bull closing above it"),
    Pattern("mat_hold", "MAT_HOLD", "MAT_HOLD",
            {-4: f"dir=BULL, {LONG}", -3: f"{SHORT}, o>pc", -2: f"{SHORT}, c<pc", -1: f"{SHORT}, c<pc", 0: "dir=BULL, o>pc"},
            tuple(_px(f"{j}.low", ">", "-4.low") for j in (-3, -2, -1))
            + tuple(_px("0.close", ">", f"{j}.high") for j in (-3, -2, -1)), group="three",
            doc="a long bull, three short bars above a gap holding above its low, a bull closing above them"),
    Pattern("breakaway", "BREAKAWAY", "BREAKAWAY",
            {-4: f"dir=BEAR, {LONG}", -3: "dir=BEAR, o<pc", -2: "HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW",
             -1: "HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW", 0: "dir=BULL"},
            (_px("0.close", ">", "-3.open"), _px("0.close", "<", "-4.close")), group="three",
            doc="a long bear, a bear gapping down, two lower bars, a bull closing inside the gap"),
    Pattern("concealing_baby_swallow", "CONCEALING_BABY_SWALLOW", "CONCEALING_BABY_SWALLOW",
            {-3: "dir=BEAR, OPEN_AT_HIGH, CLOSE_AT_LOW", -2: "dir=BEAR, OPEN_AT_HIGH, CLOSE_AT_LOW",
             -1: "dir=BEAR, o<pc, wick.up≥MODERATE", 0: "dir=BEAR"},
            (_px("-1.high", ">", "-2.close"), _px("0.high", ">=", "-1.high"), _px("0.low", "<=", "-1.low")), group="three",
            doc="two bear marubozu, a bear gapping down with a wick into the second, a bear swallowing it whole"),
    Pattern("ladder_bottom", "LADDER_BOTTOM", "LADDER_BOTTOM",
            {-4: "dir=BEAR", -3: "dir=BEAR, o<po, c<pc", -2: "dir=BEAR, o<po, c<pc", -1: "dir=BEAR, wick.up≥MODERATE",
             0: "dir=BULL, o>po"}, (_px("0.close", ">", "-1.high"),), group="three",
            doc="three falling bears, a bear with an upper wick, a bull opening above its body and closing above it"),
    # ---------------------------------------------------------------- reversal bars outside the canon
    Pattern("key_reversal", "KEY_REVERSAL", "KEY_REVERSAL",
            {**{j: "" for j in range(-9, 0)}, 0: "dir=BULL, LOW_BELOW_PREV_LOW, c>pc"},
            tuple(_px("0.low", "<", f"{j}.low") for j in range(-9, -1)), rels=(0,), group="reversal",
            doc="a new 10-bar low, then a close above the previous close"),
    Pattern("outside_reversal", "OUTSIDE_REVERSAL", "OUTSIDE_REVERSAL", {-1: "", 0: "rel=OUTSIDE, dir=BULL, CLOSE_ABOVE_PREV_HIGH"},
            group="reversal", doc="an outside bar closing above the previous high"),
    *(_island(k) for k in (1, 2, 3, 4)),
    Pattern("two_bar_reversal", "TWO_BAR_REVERSAL", "TWO_BAR_REVERSAL", {-1: f"dir=BEAR, {LONG}", 0: f"dir=BULL, {LONG}, c≥po"},
            group="reversal", doc="a long bear, then a long bull taking back its whole body"),
    Pattern("three_bar_reversal", "THREE_BAR_REVERSAL", "THREE_BAR_REVERSAL",
            {-2: "dir=BEAR", -1: "LOW_BELOW_PREV_LOW", 0: "dir=BULL, LOW_ABOVE_PREV_LOW, CLOSE_ABOVE_PREV_HIGH"},
            group="reversal", doc="a bear, a lower low, a bull closing above that bar's high"),
    Pattern("oops", "OOPS", "OOPS", {-1: "", 0: "OPEN_BELOW_PREV_LOW, h≥pl"}, group="reversal",
            doc="Williams: an open below the previous low, then back up to it"),
    Pattern("exhaustion_bar", "EXHAUSTION_BAR", "EXHAUSTION_BAR",
            {-3: "dir=BEAR", -2: "dir=BEAR", -1: "dir=BEAR", 0: f"dir=BEAR, size≥VERY_LARGE, {LONG}, LOW_BELOW_PREV_LOW"},
            group="reversal", doc="a very large bear bar at the end of a run of bears (the sellers' last push)"),
    Pattern("climax_bar", "CLIMAX_BAR", "CLIMAX_BAR", {-1: "", 0: "size≥VERY_LARGE, vol≥VERY_LARGE, LOW_BELOW_PREV_LOW, close≥Q3"},
            group="reversal", doc="a very large bar on very large volume to a new low, closing in its upper half"),
    Pattern("signal_bar", "SIGNAL_BAR", "SIGNAL_BAR", {0: "dir=BULL, close=Q4, wick.up≤WEAK, conv≥MODERATE"},
            group="reversal", attrs=_signal_quality,
            doc="Brooks' bull signal bar; `quality` STRONG with a lower tail of a quarter of its range and at "
                "most half of it inside the previous bar"),
    Pattern("trend_bar", "TREND_BAR", "TREND_BAR", {0: "dir=BULL, body≥LARGE"}, group="reversal",
            doc="Brooks: a bar that is mostly body"),
    Pattern("doji_bar", "DOJI_BAR", "DOJI_BAR", {0: "body≤SMALL"}, sym=True, group="reversal",
            doc="Brooks: a bar with a small body or none"),
)
"""The vocabulary, in the roadmap's order."""

for _p in PATTERNS:
    if _p.up != _p.down:
        SWAP_VALUE[_p.up], SWAP_VALUE[_p.down] = _p.down, _p.up


def _word(p: Pattern) -> Word:
    cells = tuple(sorted(p.cells))
    where = tuple(c for k in cells for c in (q(f"CANDLE[{p.cells[k]}]", k) if p.cells[k] else ()))
    first = cells[0]
    if p.trend is not None:
        where += (C(f"{first - 1}.trend", "==", p.trend),)
    rels = p.rels if p.rels is not None else tuple(k for k in cells if k != first)

    def attrs(F: Table, t: int, side: int, p=p, first=first) -> dict:
        i = t + first - 1
        tr = F["trend"][i] if "trend" in F and i >= 0 else None
        if side < 0 and tr is not None:
            tr = SWAP_VALUE.get(tr, tr)  # the frame's state back in the chart's terms
        out = {"name": p.up if side > 0 else p.down, "pattern": _suffix(p), "trend": tr}
        if p.attrs is not None:
            out.update(p.attrs(F, t, side))
        return out
    return Word("PATTERN", cells, where + p.where, rels=rels, sym=p.sym, suffix=_suffix(p), attrs=attrs)


def _suffix(p: Pattern) -> str:
    """The id suffix: the pattern's key (the island's four lengths share one, so one island is one event)."""
    return "island_reversal" if p.key.startswith("island_reversal") else p.key


VOCAB: dict[str, Word] = {p.key: _word(p) for p in PATTERNS}
"""The vocabulary as rows of the word table (`grammar.words(..., table_=VOCAB)`)."""
BY_KEY = {p.key: p for p in PATTERNS}


def columns(T: Table, trend: np.ndarray | None) -> None:
    """The token-table columns the vocabulary reads, in place: the body's middle and edges, and the
    STRUCTURE state known at each bar (`trend`)."""
    o, c = T["open"], T["close"]
    T["body_mid"] = (o + c) / 2
    if trend is not None:
        T["trend"] = trend
