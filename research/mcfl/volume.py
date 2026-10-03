"""v2 item 3: volume - effort against result.

Works with any volume column: tick volume on CFDs, real or taker volume on exchanges.

VOLUME (`volume_class`, an L1 qualifier of the CANDLE): the bar's volume in the rolling distribution
of the last PERIOD (10) bars' volumes, with the size classes' edges (`candles`: NONE for zero,
VERY_SMALL .. EXTREMELY_LARGE, WARMUP until the window is full or with no volume).

EFFORT_RESULT (`effort`): the volume class (effort) against the size class (result):

    ABSORPTION   volume >= LARGE and size <= SMALL    much traded, little moved
    EASE         volume <= SMALL and size >= LARGE    little traded, far moved
    AGREE        both >= LARGE, or both <= SMALL
    NEUTRAL      anything else; WARMUP while either is

TAKER_SKEW, with a `taker_buy_volume` column (and `taker_sell_volume`, else volume - buy):
`taker_skew` = (buy - sell) / volume, and `taker` = BUY when it is at least TAKER_MIN (0.2), SELL at
most -0.2, else BALANCED. Under the flip buyers and sellers trade places (`parse.flip` swaps the two
columns), so BUY and SELL do too and the skew is negated.

Qualifiers: `CANDLE[vol≥LARGE]`, `CANDLE[effort=ABSORPTION]`, `CANDLE[taker=BUY]`. Text in the v2 bar
word: `v:L,ABS`, `tb` / `ts`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mcfl import candles
from mcfl.candles import SIZE, SIZE_EDGES, WARMUP, Table, graded

TAKER_MIN = 0.2
"""|taker_skew| at which the taker side is BUY or SELL rather than BALANCED."""
EFFORTS = ("ABSORPTION", "EASE", "AGREE", "NEUTRAL")
_HI = frozenset({"LARGE", "VERY_LARGE", "EXTREMELY_LARGE"})
_LO = frozenset({"NONE", "VERY_SMALL", "SMALL"})


def effort_of(vol: str, size: str) -> str:
    """EFFORT_RESULT of one bar from its volume class and its size class."""
    if vol == WARMUP or size == WARMUP:
        return WARMUP
    if vol in _HI and size in _LO:
        return "ABSORPTION"
    if vol in _LO and size in _HI:
        return "EASE"
    if (vol in _HI and size in _HI) or (vol in _LO and size in _LO):
        return "AGREE"
    return "NEUTRAL"


def columns(T: Table, df: pd.DataFrame) -> None:
    """Add `volume_class` and `effort` (and `taker_skew`, `taker`) to the token table, in place."""
    v = T["volume"]
    vc = graded(np.asarray(v, float), SIZE_EDGES, SIZE[1:], "NONE")
    T["volume_class"] = vc
    size = T["size"]
    eff = np.empty(len(v), object)
    eff[:] = [effort_of(a, b) for a, b in zip(vc, size)]
    T["effort"] = eff
    candles.V2_CANDLE.update(volume_class=False, effort=False)
    if "taker_buy_volume" in df:
        buy = df["taker_buy_volume"].to_numpy(float)
        sell = df["taker_sell_volume"].to_numpy(float) if "taker_sell_volume" in df else v - buy
        with np.errstate(invalid="ignore", divide="ignore"):
            sk = np.where(v > 0, (buy - sell) / np.where(v > 0, v, 1.0), np.nan)
        T["taker_skew"] = sk
        T["taker"] = np.where(sk >= TAKER_MIN, "BUY", np.where(sk <= -TAKER_MIN, "SELL", "BALANCED")).astype(object)
        T["taker"][~np.isfinite(sk)] = WARMUP
        candles.V2_CANDLE.update(taker_skew=True, taker=False)
