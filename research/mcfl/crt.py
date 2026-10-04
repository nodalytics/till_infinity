"""v2 item 12: candle range theory (CRT).

RANGE_CANDLE: any CANDLE token read as a box - its high, its low and its 50% mid. No new entity: the
candle is a part of what is built on it. Usually a higher timeframe's candle (item 10's aggregation);
`mtf.crt` reads an HTF candle's purge on the lower timeframe.

PURGE (L2), a word over the v1 relation words of the next candle, written for the up side:

    PURGE_UP := CANDLE[HIGH_ABOVE_PREV_HIGH, not CLOSE_ABOVE_PREV_HIGH, not CLOSE_BELOW_PREV_LOW]

it trades beyond the range candle's high and closes back inside the range (close <= prev high and >=
prev low, both within the point relations' tolerance). PURGE_DOWN is the flipped chart's. Attributes:
`depth_atr` (how far beyond, ATR), `close_loc` (the close's place in the range measured from the
purged side: 0 at the purged edge, 1 at the other), and the box: `upper_edge`, `lower_edge`,
`range_mid`. Known at the purge candle; parts the two CANDLEs and the BAR_RELATION.

DISTRIBUTION (L2): within CRT_N (3) candles after the purge, price reaches the range's opposite side
(a low at or below the range low after PURGE_UP). At the first such candle, known there; direction the
move's (DOWN after PURGE_UP). Attributes `purge`, `bars` (after the purge), `mid_bars` (bars after the
purge at which the 50% mid was first reached) and `mid_same_bar` (the mid first reached on the
distributing candle itself, so the bar does not say which came first). This is CRT's outcome event.

CRT3 (L3), the three-candle production: RANGE_CANDLE PURGE DISTRIBUTION, direction the distribution's.
"""
from __future__ import annotations

import numpy as np

from mcfl.candles import Table
from mcfl.core import Dir, Entity, attrs_of, make_id
from mcfl.grammar import C, Rule, Slot, Word, q

CRT_N = 3
"""Candles after the purge within which the opposite side must be reached for a DISTRIBUTION."""


def _purge_attrs(F: Table, t: int, side: int) -> dict:
    ph, pl, h, c, a = F["high"][t - 1], F["low"][t - 1], F["high"][t], F["close"][t], F["atr"][t]
    hi, lo = sorted((side * ph, side * pl))[::-1]
    return {"depth_atr": float((h - ph) / a) if a > 0 else None,
            "close_loc": float((ph - c) / (ph - pl)) if ph > pl else None,
            "upper_edge": float(hi), "lower_edge": float(lo), "range_mid": float((hi + lo) / 2)}


PURGE = Word("PURGE", (-1, 0), q("CANDLE[HIGH_ABOVE_PREV_HIGH, not CLOSE_ABOVE_PREV_HIGH, not CLOSE_BELOW_PREV_LOW]", 0),
             rels=(0,), attrs=_purge_attrs)
"""PURGE_UP := RANGE_CANDLE CANDLE[HIGH_ABOVE_PREV_HIGH, not CLOSE_ABOVE_PREV_HIGH, not CLOSE_BELOW_PREV_LOW]"""


def distributions(fr: dict[int, Table], purges: list[Entity], cid: list[str]) -> list[Entity]:
    out = []
    for p in purges:
        side = 1 if p.dir is Dir.UP else -1
        F = fr[side]
        t = p.at
        lo, mid = F["low"][t - 1], (F["high"][t - 1] + F["low"][t - 1]) / 2
        n = len(F["low"])
        hit_mid = -1
        for u in range(t + 1, min(n, t + CRT_N + 1)):
            if hit_mid < 0 and F["low"][u] <= mid:
                hit_mid = u
            if F["low"][u] <= lo:
                d = p.dir.flip()
                out.append(Entity(make_id("DISTRIBUTION", d, u, f"p{t}"), "DISTRIBUTION", d, u, u, attrs_of({
                    "purge": p.id, "bars": u - t, "mid_bars": hit_mid - t, "mid_same_bar": hit_mid == u}),
                    parts=(cid[u],)))
                break
    return out


RULES = {
    "CRT3": Rule(
        head="CRT3", anchor="dist", horizon=None, report=False, at="range",
        attrs=lambda b, d: {"purge": b["purge"][0].id, "bars": b["dist"][0].get("bars")},
        slots=(
            Slot("dist", "DISTRIBUTION"),
            Slot("purge", "PURGE", dir="any", where=(
                C("at", ">=", ("+", "dist.at", -CRT_N)), C("at", "<=", ("+", "dist.at", -1)),
                C("id", "==", "dist.purge"))),
            Slot("range", "CANDLE", dir="any", where=(C("at", "==", ("+", "purge.at", -1)),)),
        ),
        sequence=("range", "purge", "dist"),
    ),
}
"""CRT3_DOWN := RANGE_CANDLE PURGE_UP DISTRIBUTION_DOWN   (the candle, its purge, the move to its other side)"""
