"""Does price respect a high-activity band more than an arbitrary price?

The question asked of every level here. A profile node is a band where a lot of
supply changed hands - the market-data form of a cost-basis shelf - and the
claim is that price has to get through it.

Tested against the control this repository already uses for magnets: an
arbitrary price the same distance away. If a node is reached no more often than
that, it is a description of the past rather than a claim about the future.

Deriv's synthetics run beside the real instruments as the second null. A
generated process has no supply and no holders, so any effect there is the
method.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import statistics as st

import httpx

from till_infinity.structures.drawing.profile import nodes
from till_infinity.structures.vol.volatility import Volatility

PRICES = "file:/app/.data/prices/prices.db?mode=ro"
URL = os.environ["TRADING_MT5_URL"]
KEY = os.environ.get("TRADING_MT5_API_KEY", "")

REAL = ["gold", "eurusd", "us100", "btc", "ger40", "spx500"]
SYNTH = ["Volatility 25 Index", "Volatility 75 Index", "Step Index"]

#: Bars of history the profile is built on, then the bars it is judged over.
WINDOW = 600
AHEAD = 200

#: How close price must come to count as reaching the band.
NEAR_VOL = 0.5


def reached(prices, target, unit, start, ahead=AHEAD) -> bool:
    stop = min(len(prices), start + ahead)
    return any(abs(prices[i] - target) <= NEAR_VOL * unit for i in range(start, stop))


def run(prices: list[float], weights: list[float] | None, label: str) -> None:
    vol = Volatility()
    for p in prices[:400]:
        vol.update(p)
    if not vol.warm:
        print(f"{label}: volatility never warmed")
        return
    unit = abs(st.median(prices) * vol.bps / 10_000)
    if unit <= 0:
        return

    hit_node = miss_node = hit_control = miss_control = 0
    step = 50
    for start in range(WINDOW, len(prices) - AHEAD, step):
        window = prices[start - WINDOW : start]
        wts = weights[start - WINDOW : start] if weights else None
        found = nodes(window, vol, weights=wts)
        if not found:
            continue
        spot = prices[start - 1]
        price, _ = found[0]
        gap = price - spot
        if abs(gap) < NEAR_VOL * unit:
            continue
        # The control: the same distance, the other way. Same reachability by
        # construction, no claim about supply.
        control = spot - gap
        (hit_node, miss_node) = (
            (hit_node + 1, miss_node)
            if reached(prices, price, unit, start)
            else (hit_node, miss_node + 1)
        )
        (hit_control, miss_control) = (
            (hit_control + 1, miss_control)
            if reached(prices, control, unit, start)
            else (hit_control, miss_control + 1)
        )

    tried = hit_node + miss_node
    if tried < 20:
        print(f"{label}: only {tried} windows, skipped")
        return
    node_rate = hit_node / tried
    control_rate = hit_control / tried
    print(
        f"   {label:22s} {tried:5d} windows   node {node_rate:6.1%}   "
        f"control {control_rate:6.1%}   gap {node_rate - control_rate:+.1%}"
    )


def real(feed: str) -> tuple[list[float], list[float] | None]:
    c = sqlite3.connect(PRICES, uri=True)
    rows = c.execute(
        "select close, volume from bars where feed=? and interval='5m' order by ts desc limit 20000",
        (feed,),
    ).fetchall()
    rows = list(reversed(rows))
    prices = [float(p) for p, _ in rows]
    got = [float(v or 0) for _, v in rows]
    return prices, (got if sum(1 for v in got if v > 0) > len(got) * 0.8 else None)


async def synth(client: httpx.AsyncClient, symbol: str) -> list[float]:
    r = await client.get(
        "/api/v1/symbols/rates/pos",
        params={"symbol": symbol, "timeframe": "M5", "num_bars": 20000},
    )
    if r.status_code != 200:
        return []
    return [float(row["close"]) for row in r.json() if "close" in row]


async def main() -> None:
    print("REAL INSTRUMENTS")
    for feed in REAL:
        prices, weights = real(feed)
        if len(prices) < WINDOW + AHEAD + 200:
            continue
        run(prices, weights, feed + (" (volume)" if weights else " (time)"))

    print("\nSYNTHETICS - the null")
    headers = {"Accept": "application/json"}
    if KEY:
        headers["X-API-Key"] = KEY
    async with httpx.AsyncClient(base_url=URL, headers=headers, timeout=60.0) as client:
        for symbol in SYNTH:
            prices = await synth(client, symbol)
            if len(prices) < WINDOW + AHEAD + 200:
                continue
            run(prices, None, symbol)


asyncio.run(main())
