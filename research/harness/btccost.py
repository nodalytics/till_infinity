"""What accuracy would a 1-minute BTC model need just to break even?

    ./.secrets/lab.sh run research/harness/btccost.py

The screen that decides whether an ML pipeline on 1-minute bars is worth
porting at all, run before the port rather than after - "cost exotic ideas
first, it ends most of them".

## The arithmetic that decides it

Cost in R is `cost_px / stop`, set by the **stop** and not by the target or
the hold. With a stop `S`, a target `N x S` and a round trip `C`:

    p(NS - C) = (1 - p)(S + C)   =>   p* = (1 + C/S) / (N + 1)

So the break-even hit rate at 1:2 is 1/3 when the round trip is free, **0.50
when the round trip costs half the stop**, and 0.667 when it costs a whole
one. A tight stop does not make a trade cheaper, it makes the spread a larger
share of it - which is why the same spread is about 19x dearer in R at 15m
than at 1d.

That turns the question "can a model predict the next minute" into a number:
whatever AUC the model has, the hit rate it delivers has to clear `p*`, and
`p*` is set by the venue before any model exists.

## Two spreads, and the honest one

The per-bar `spread` column on these bars is the one this repository measured
as **unusable as a level** - zero on 7-35% of bars and a median 3-8x *below*
the terminal's own quote (1 point against 9 on EURUSD). So both are printed:
the bars' median, and the terminal's live quote from `symbols/info`. The
terminal's is the one the conclusion uses, because it is the one an order
crosses.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request as request
from pathlib import Path

import numpy as np

DATA = Path.home() / "till_infinity" / "data" / "btc"
BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"
SYMBOLS = ["BTCUSD", "ETHUSD"]
HORIZONS = [1, 5, 15, 30, 60]
STOP_ATR = [1.0, 2.0, 3.0, 6.0]
ATR_N = 14

#: This desk's own measured ceiling on what a round trip may cost, as a share
#: of the risk. Above it a rule is paying for its stop rather than trading.
LIMIT = 0.16


def info(symbol: str) -> dict:
    key = (Path.home() / ".mt5key").read_text().strip()
    req = request.Request(  # noqa: S310
        f"{BASE}/symbols/info/{symbol}", headers={"X-API-Key": key}
    )
    with request.urlopen(req, timeout=60) as response:  # noqa: S310
        return json.loads(response.read().decode())


def load(symbol: str) -> dict[str, np.ndarray]:
    with np.load(DATA / f"{symbol}.1m.npz") as data:
        return {k: data[k] for k in ("time", "open", "high", "low", "close", "spread")}


def atr(bars: dict[str, np.ndarray], n: int) -> np.ndarray:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    for i in range(n, len(tr)):
        out[i] = tr[i - n : i].mean()
    return out


def main() -> int:
    for symbol in SYMBOLS:
        bars = load(symbol)
        spec = info(symbol)
        digits = int(spec.get("digits") or 2)
        point = 10.0**-digits
        bid, ask = float(spec.get("bid") or 0.0), float(spec.get("ask") or 0.0)
        quoted_px = (ask - bid) if ask > bid else float("nan")
        bars_px = float(np.median(bars["spread"])) * point
        close = bars["close"]
        unit = atr(bars, ATR_N)
        median_atr = float(np.nanmedian(unit))

        print(f"\n=== {symbol} ===")
        print(
            f"digits {digits}  point {point:g}  last {close[-1]:.2f}  "
            f"median M1 ATR({ATR_N}) {median_atr:.4g}"
        )
        print(
            f"round trip: bars column {bars_px:.4g} px  |  terminal quote {quoted_px:.4g} px "
            f"({quoted_px / bars_px if bars_px else float('nan'):.2f}x the column)"
        )

        print("\nmedian |move| over k minutes, against the terminal's round trip:")
        for k in HORIZONS:
            moves = np.abs(close[k:] - close[:-k])
            med = float(np.median(moves))
            print(
                f"  k={k:3d}m  median move {med:9.4g} px   round trip is "
                f"{quoted_px / med:6.1%} of it"
            )

        print(f"\ncost in R and the break-even hit rate (desk limit {LIMIT:.2f} R):")
        print(f"  {'stop':>10s} {'stop px':>10s} {'cost/R':>8s} {'p* @1:1':>8s} {'p* @1:2':>8s}")
        for mult in STOP_ATR:
            stop_px = mult * median_atr
            cost_r = quoted_px / stop_px
            flag = "" if cost_r <= LIMIT else "  <- over the limit"
            print(
                f"  {mult:9.1f}A {stop_px:10.4g} {cost_r:8.3f} "
                f"{(1 + cost_r) / 2:8.3f} {(1 + cost_r) / 3:8.3f}{flag}"
            )

        # The stop that brings cost to the desk's limit, and the hold it implies:
        # a stop of S is only reachable in a time where the typical move is ~S.
        needed = quoted_px / LIMIT
        in_atr = needed / median_atr
        reach = next(
            (k for k in range(1, 1441) if float(np.median(np.abs(close[k:] - close[:-k]))) >= needed),
            None,
        )
        print(
            f"\n  to reach {LIMIT:.2f} R the stop must be >= {needed:.4g} px "
            f"({in_atr:.1f} x M1 ATR)"
        )
        print(
            f"  the median move first reaches that at k = {reach} minutes"
            if reach
            else "  no horizon up to a day reaches it"
        )
    print(
        "\np* is break-even, not profit. A 1:2 rule whose round trip costs half its stop\n"
        "needs 0.50 just to stand still - which is the hit rate a directional model would\n"
        "have to beat before it earns anything."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
