"""Bar history from the terminal, for retraining.

The same bridge, route and parsing `prices/broker.py` collects candles with - `TRADING_MT5_URL` and
`TRADING_MT5_API_KEY`, `/api/v1/symbols/rates/pos`, `broker.parse` - but synchronous and deep:
retraining wants up to 50,000 bars per series once a fortnight, not the latest few every minute.
"""

from __future__ import annotations

import os
import time

import httpx

from ..prices.broker import TIMEFRAMES, parse
from ..prices.models import Bar

#: How many bars to ask for. The terminal serves about this many at 15m and 1h.
DEPTH = 50_000


def client() -> httpx.Client | None:
    """A client for the bridge, or None when no bridge is configured."""
    url = os.environ.get("TRADING_MT5_URL", "")
    if not url:
        return None
    headers = {"Accept": "application/json"}
    key = os.environ.get("TRADING_MT5_API_KEY", "")
    if key:
        headers["X-API-Key"] = key
    # Fifty thousand bars is a real transfer; the default timeout cuts it off part way, which reads
    # as an empty series rather than a slow one.
    return httpx.Client(base_url=url, headers=headers, timeout=120.0)


def bars(http: httpx.Client, symbol: str, interval: str, count: int = DEPTH) -> list[Bar]:
    """Closed bars, oldest first. The forming bar is dropped: its high and low are incomplete."""
    code = TIMEFRAMES.get(interval)
    if code is None:
        return []
    # An unselected symbol answers 200 with an empty list, indistinguishable from a quiet market.
    http.post(f"/api/v1/symbols/select/{symbol}")
    for attempt in range(3):
        response = http.get(
            "/api/v1/symbols/rates/pos",
            params={"symbol": symbol, "timeframe": code, "num_bars": count + 1},
        )
        if response.status_code == 200:
            return parse(response.json())[:-1]
        time.sleep(2.0 * (attempt + 1))
    return []
