"""An example, not a recommendation: a 20-bar channel breakout with an ATR stop and a time exit.

Causal by construction - every input is a trailing window ending at the signal bar - so it
passes `audit.lookahead`. `donchian_peek` is the same with a one-bar look-ahead, kept to show
the audit catching it.
"""

import pandas as pd

N, STOP, HOLD = 20, 2.0, 32


def strategy(bars, book):
    hi = bars["high"].rolling(N).max().shift(1)
    lo = bars["low"].rolling(N).min().shift(1)
    tr = (bars["high"] - bars["low"]).rolling(14).mean()
    up = bars["close"] > hi
    dn = bars["close"] < lo
    i = bars.index[(up | dn) & tr.notna()]
    return pd.DataFrame({"i": i, "side": up[i].map({True: 1, False: -1}).to_numpy(),
                         "stop": STOP * tr[i].to_numpy(), "target": 0.0, "hold": HOLD})


def donchian_peek(bars, book):
    """Enters on bars whose *next* close is beyond the channel: the look-ahead the audit exists for."""
    hi = bars["high"].rolling(N).max().shift(1)
    tr = (bars["high"] - bars["low"]).rolling(14).mean()
    nxt = bars["close"].shift(-1)
    i = bars.index[(nxt > hi) & tr.notna()]
    return pd.DataFrame({"i": i, "side": 1, "stop": STOP * tr[i].to_numpy(), "hold": 4})
