"""The null as a strategy: random bars, random sides, a 1.5 ATR stop, 2 ATR target, 16-bar hold."""

import zlib

import numpy as np
import pandas as pd

RATE = 0.02


def strategy(bars, book):
    rng = np.random.default_rng(zlib.crc32(book.symbol.encode()))  # hash() is salted per process
    tr = (bars["high"] - bars["low"]).rolling(14, min_periods=14).mean().to_numpy()
    # one draw of each per bar, so a bar's draws never depend on how many bars follow it
    draw = rng.random((len(bars), 2))
    pick = (draw[:, 0] < RATE) & ~np.isnan(tr)
    i = np.nonzero(pick)[0]
    side = np.where(draw[i, 1] < 0.5, -1, 1)
    return pd.DataFrame({"i": i, "side": side, "stop": 1.5 * tr[i],
                         "target": 2.0 * tr[i], "hold": 16})
