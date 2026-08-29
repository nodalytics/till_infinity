"""Do the size test and the extremum test say different things about outcome?

They are two conditions on the same event - how big the impulse was, and
whether it exceeded the running extremum that had been holding - and they agree
only 59-78% of the time. So they might be combined rather than applied as two
pass/fail gates: a decisive extremum earning a smaller impulse, or the reverse.

That is only worth doing if either predicts the first return holding. This
buckets origins by each and reports the hold rate, with the synthetics beside
them as the null - a generated process has no structure, so any slope there is
the method rather than the market.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import statistics as st
from collections import defaultdict
import httpx

from till_infinity.structures.origins import Origins
from till_infinity.structures.volatility import Volatility

PRICES = "file:/app/.data/prices/prices.db?mode=ro"
URL = os.environ["TRADING_MT5_URL"]
KEY = os.environ.get("TRADING_MT5_API_KEY", "")

REAL = ["gold", "eurusd", "us100", "btc", "ger40", "spx500"]
SYNTH = ["Volatility 25 Index", "Volatility 75 Index", "Step Index", "Boom 1000 Index"]

BOUNCE_VOL = 1.0
BREAK_THROUGH = 0.5
BARS = 20_000


def first_return(prices: list[float], origin, unit: float) -> str | None:
    """Verdict on the first return to the zone, or None if it never came back."""
    up = origin.launched == "up"
    i = int(origin.when) + 1
    while i < len(prices) and origin.low <= prices[i] <= origin.high:
        i += 1
    while i < len(prices) and not (origin.low <= prices[i] <= origin.high):
        i += 1
    if i >= len(prices):
        return None
    while i < len(prices):
        price = prices[i]
        if up:
            if price >= origin.high + BOUNCE_VOL * unit:
                return "held"
            if price <= origin.low - BREAK_THROUGH * unit:
                return "broke"
        else:
            if price <= origin.low - BOUNCE_VOL * unit:
                return "held"
            if price >= origin.high + BREAK_THROUGH * unit:
                return "broke"
        i += 1
    return None


def bucket(value: float, edges: tuple[float, ...]) -> str:
    for lo, hi in zip(edges, edges[1:], strict=False):
        if lo <= value < hi:
            return f"{lo:g}-{hi:g}"
    return f"{edges[-1]:g}+"


SIZE_EDGES = (3.0, 4.0, 5.5, 8.0)
EXTREMUM_EDGES = (0.0, 0.5, 1.5, 4.0)


def collect(prices: list[float]) -> tuple[dict, dict]:
    vol = Volatility()
    for p in prices[:400]:
        vol.update(p)
    if not vol.warm:
        return {}, {}
    unit = abs(st.median(prices) * vol.bps / 10_000)
    times = [float(i) for i in range(len(prices))]
    by_size: dict[str, list[str]] = defaultdict(list)
    by_extremum: dict[str, list[str]] = defaultdict(list)
    for origin in Origins().observe(times, prices, unit):
        verdict = first_return(prices, origin, unit)
        if verdict is None:
            continue
        by_size[bucket(origin.size_vol, SIZE_EDGES)].append(verdict)
        by_extremum[bucket(origin.extremum_vol, EXTREMUM_EDGES)].append(verdict)
    return by_size, by_extremum


def show(title: str, buckets: dict[str, list[str]], edges: tuple[float, ...]) -> None:
    print(f"\n{title}")
    order = [f"{lo:g}-{hi:g}" for lo, hi in zip(edges, edges[1:], strict=False)]
    order.append(f"{edges[-1]:g}+")
    for name in order:
        rows = buckets.get(name, [])
        if len(rows) < 40:
            continue
        held = sum(1 for r in rows if r == "held") / len(rows)
        print(f"   {name:>8s} {len(rows):6d} held {held:5.1%}")


def real_prices(feed: str) -> list[float]:
    c = sqlite3.connect(PRICES, uri=True)
    rows = c.execute(
        "select close from bars where feed=? and interval='5m' order by ts desc limit ?",
        (feed, BARS),
    ).fetchall()
    return [float(p) for (p,) in reversed(rows)]


async def synth_prices(client: httpx.AsyncClient, symbol: str) -> list[float]:
    r = await client.get(
        "/api/v1/symbols/rates/pos",
        params={"symbol": symbol, "timeframe": "M5", "num_bars": BARS},
    )
    if r.status_code != 200:
        return []
    rows = r.json()
    return [float(row["close"]) for row in rows if "close" in row]


async def main() -> None:
    size_real: dict[str, list[str]] = defaultdict(list)
    ext_real: dict[str, list[str]] = defaultdict(list)
    for feed in REAL:
        prices = real_prices(feed)
        if len(prices) < 2_000:
            continue
        a, b = collect(prices)
        for k, v in a.items():
            size_real[k].extend(v)
        for k, v in b.items():
            ext_real[k].extend(v)

    headers = {"Accept": "application/json"}
    if KEY:
        headers["X-API-Key"] = KEY
    size_syn: dict[str, list[str]] = defaultdict(list)
    ext_syn: dict[str, list[str]] = defaultdict(list)
    async with httpx.AsyncClient(base_url=URL, headers=headers, timeout=60.0) as client:
        for symbol in SYNTH:
            prices = await synth_prices(client, symbol)
            if len(prices) < 2_000:
                continue
            a, b = collect(prices)
            for k, v in a.items():
                size_syn[k].extend(v)
            for k, v in b.items():
                ext_syn[k].extend(v)

    show("REAL - by impulse size (volatility units)", size_real, SIZE_EDGES)
    show("SYNTHETIC - by impulse size", size_syn, SIZE_EDGES)
    show("REAL - by how far past the extremum", ext_real, EXTREMUM_EDGES)
    show("SYNTHETIC - by how far past the extremum", ext_syn, EXTREMUM_EDGES)


asyncio.run(main())
