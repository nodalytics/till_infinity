"""Do Deriv's synthetics behave like the real instruments?

Synthetics have no underlying - they are generated processes with a published
volatility - so there is no economic reason for them to respect a level, and
that makes them the cleanest available test of whether the origin machinery is
finding structure or inventing it.

If origins hold on a random-walk-by-construction instrument at the same rate
they hold on gold, the finding is about the *method* rather than the market. If
they hold less, the method is reading something real. Either answer is worth
having, and the second is only credible because the first was possible.

Bars come straight from the bridge: nothing else carries these, which is the
whole reason they need the broker feed. `structures.volatility.Volatility` and
the production origin detector do the rest, so this asks the same question of
synthetics that `revisits.py` asks of everything else.
"""

from __future__ import annotations

import asyncio
import os
import statistics as st
from collections import defaultdict
from datetime import UTC, datetime

import httpx

from till_infinity.structures.drawing.origins import Origins
from till_infinity.structures.vol.volatility import Volatility

URL = os.environ["TRADING_MT5_URL"]
KEY = os.environ.get("TRADING_MT5_API_KEY", "")

SYNTHETICS = [
    "Volatility 10 Index",
    "Volatility 25 Index",
    "Volatility 75 Index",
    "Volatility 100 Index",
    "Step Index",
    "Boom 1000 Index",
    "Crash 1000 Index",
]

#: The same shape as `revisits.py`, so the numbers are comparable.
BOUNCE_VOL = 1.0
BREAK_VOL = 0.5
MAX_VISIT = 4
BARS = 20_000
TIMEFRAME = "M5"


def when(raw) -> float:
    if isinstance(raw, int | float):
        return float(raw)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(
            tzinfo=UTC
        ).timestamp()
    except ValueError:
        return 0.0


async def bars(client: httpx.AsyncClient, symbol: str) -> list[float]:
    r = await client.get(
        "/api/v1/symbols/rates/pos",
        params={"symbol": symbol, "timeframe": TIMEFRAME, "num_bars": BARS},
    )
    if r.status_code != 200:
        return []
    rows = r.json()
    if not isinstance(rows, list):
        return []
    return [float(row["close"]) for row in rows if "close" in row]


def visits(prices: list[float], origin, unit: float, start: int) -> list[str]:
    """Outcome of each *return* to the zone. Same rule as `revisits.py`."""
    up = origin.launched == "up"
    out: list[str] = []
    i = start
    while i < len(prices) and origin.low <= prices[i] <= origin.high:
        i += 1
    while i < len(prices):
        while i < len(prices) and not (origin.low <= prices[i] <= origin.high):
            i += 1
        if i >= len(prices):
            break
        verdict = "open"
        while i < len(prices):
            price = prices[i]
            if up:
                if price >= origin.high + BOUNCE_VOL * unit:
                    verdict = "held"
                    break
                if price <= origin.low - BREAK_VOL * unit:
                    verdict = "broke"
                    break
            else:
                if price <= origin.low - BOUNCE_VOL * unit:
                    verdict = "held"
                    break
                if price >= origin.high + BREAK_VOL * unit:
                    verdict = "broke"
                    break
            i += 1
        out.append(verdict)
        if verdict in ("broke", "open"):
            break
        while i < len(prices) and origin.low <= prices[i] <= origin.high:
            i += 1
    return out


def show(title: str, by_visit: dict[int, list[str]]) -> None:
    print(f"\n{title}")
    print(f"   {'visit':>7s} {'n':>6s} {'held':>7s} {'broke':>7s}")
    for n in sorted(by_visit):
        rows = by_visit[n]
        if not rows:
            continue
        held = sum(1 for r in rows if r == "held") / len(rows)
        broke = sum(1 for r in rows if r == "broke") / len(rows)
        label = f"{n}" if n < MAX_VISIT else f"{MAX_VISIT}+"
        print(f"   {label:>7s} {len(rows):6d} {held:6.1%} {broke:6.1%}")


async def main() -> None:
    headers = {"Accept": "application/json"}
    if KEY:
        headers["X-API-Key"] = KEY
    pooled: dict[int, list[str]] = defaultdict(list)
    async with httpx.AsyncClient(base_url=URL, headers=headers, timeout=60.0) as client:
        for symbol in SYNTHETICS:
            prices = await bars(client, symbol)
            if len(prices) < 2_000:
                print(f"{symbol}: only {len(prices)} bars, skipped")
                continue
            vol = Volatility()
            for p in prices[:400]:
                vol.update(p)
            if not vol.warm:
                print(f"{symbol}: volatility never warmed")
                continue
            unit = abs(st.median(prices) * vol.bps / 10_000)
            times = [float(i) for i in range(len(prices))]

            found = Origins().observe(times, prices, unit)
            by_visit: dict[int, list[str]] = defaultdict(list)
            for origin in found:
                start = int(origin.when) + 1
                if start >= len(prices):
                    continue
                for n, verdict in enumerate(visits(prices, origin, unit, start), start=1):
                    by_visit[min(n, MAX_VISIT)].append(verdict)
            rate = len(found) / len(prices) * 1000
            print(
                f"\n{symbol}: {len(prices)} bars, {len(found)} origins "
                f"({rate:.1f} per 1000 bars), vol {vol.bps:.1f}bps"
            )
            show(f"  {symbol}", by_visit)
            for n, rows in by_visit.items():
                pooled[n].extend(rows)
    show("ALL SYNTHETICS", pooled)


asyncio.run(main())
