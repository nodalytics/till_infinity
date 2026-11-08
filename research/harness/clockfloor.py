"""What is the shortest clock BTCUSD can be traded on at this venue?

    ./.secrets/lab.sh run research/harness/clockfloor.py

Measured by aggregating the M1 bars into k-minute bars and reading ATR(14)
off each, rather than scaling a 1-minute ATR by sqrt(k). The scaling would be
wrong in a direction that matters: volatility clusters, so realised range at
short horizons is relatively larger than independence implies, and sqrt-scaling
would make short clocks look *more* expensive than they are. The whole question
here is where the floor sits, so the estimate has to come from the bars.

Cost in R is `cost_px / stop`, set by the stop. The desk's own measured ceiling
is **0.16 of the risk**, and `statespace-surprise` carries a second limit at
0.10 of the target.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request as request
from pathlib import Path

import numpy as np

DATA = Path(os.environ.get("DATA", str(Path.home() / "till_infinity" / "data" / "btc")))
BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"
#: 2 and 3 are here because the question is about 1-5 minutes and the gap
#: between 1 and 5 is exactly where the answer changes.
CLOCKS = [1, 2, 3, 5, 10, 15, 30, 60]


def _symbols() -> tuple[str, ...]:
    """`SYMBOLS_FILE` first, because this venue's synthetic names carry
    spaces and `lab.sh run` splits env values on whitespace."""
    path = os.environ.get("SYMBOLS_FILE", "")
    if path:
        return tuple(
            line.strip()
            for line in Path(path).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        )
    return ("BTCUSD", "ETHUSD")


SYMBOLS = _symbols()
ATR_N = 14
LIMIT = 0.16
STOPS = [1.0, 2.0, 3.0]


def quoted(symbol: str) -> float:
    try:
        key = (Path.home() / ".mt5key").read_text().strip()
        req = request.Request(  # noqa: S310
            f"{BASE}/symbols/info/{symbol}", headers={"X-API-Key": key}
        )
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            spec = json.loads(response.read().decode())
        bid, ask = float(spec.get("bid") or 0.0), float(spec.get("ask") or 0.0)
        if ask > bid:
            return ask - bid
    except Exception:  # noqa: BLE001
        pass
    return float("nan")


def aggregate(bars: dict[str, np.ndarray], k: int) -> dict[str, np.ndarray]:
    """k consecutive M1 bars into one, dropping any ragged tail."""
    n = (len(bars["close"]) // k) * k
    shape = (n // k, k)
    return {
        "high": bars["high"][:n].reshape(shape).max(axis=1),
        "low": bars["low"][:n].reshape(shape).min(axis=1),
        "close": bars["close"][:n].reshape(shape)[:, -1],
    }


def atr(bars: dict[str, np.ndarray], n: int) -> float:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    rolled = [tr[i - n : i].mean() for i in range(n, len(tr))]
    return float(np.median(rolled)) if rolled else float("nan")


def main() -> int:
    for symbol in SYMBOLS:
        path = DATA / f"{symbol}.1m.npz"
        if not path.exists():
            print(f"{symbol}: no M1 file")
            continue
        with np.load(path) as data:
            bars = {k: data[k] for k in ("high", "low", "close")}
        spread = quoted(symbol)
        print(f"\n=== {symbol} ===  quoted round trip {spread:.4g} px")
        head = f"  {'clock':>7s} {'ATR(14)':>10s} " + " ".join(
            f"{'cost/R @' + str(int(s)) + 'A':>12s}" for s in STOPS
        )
        print(head)
        for k in CLOCKS:
            unit = atr(aggregate(bars, k), ATR_N)
            cells = []
            for stop in STOPS:
                cost_r = spread / (stop * unit)
                mark = "*" if cost_r <= LIMIT else " "
                cells.append(f"{cost_r:11.3f}{mark}")
            print(f"  {k:5d}m {unit:10.4g} " + " ".join(cells))
        print(f"  * within the desk's {LIMIT:.2f} R ceiling")
    print(
        "\nThe live desks run 15-minute bars. Anything shorter needs a stop of several\n"
        "ATR to stay inside the ceiling, and a stop of several ATR is a hold long enough\n"
        "that the short clock bought nothing."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
