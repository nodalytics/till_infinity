"""Which broker symbols clear the cost gate, in the currency that decides it.

`charge_spread` deducts the quoted spread from every level call before it is
judged, and the cost is not uniform: 0.003v on btc against 2.5v on gbpusd
intraday. A spread in points cannot be compared across instruments; a spread in
volatility units is exactly what a strategy pays.

So this asks, for a sample of what the broker offers: how much of a typical
move does it cost to get in and out? Anything above about half a unit cannot
support a scalp whose whole expected push is one or two.
"""

import asyncio
import os
import re
import statistics as st

import httpx

from till_infinity.structures.volatility import Volatility

URL = os.environ["TRADING_MT5_URL"]
KEY = os.environ.get("TRADING_MT5_API_KEY", "")
headers = {"Accept": "application/json"}
if KEY:
    headers["X-API-Key"] = KEY

CARRIED = {
    "Volatility 10 Index",
    "Volatility 25 Index",
    "Volatility 50 Index",
    "Volatility 75 Index",
    "Volatility 100 Index",
    "Step Index",
    "Boom 500 Index",
    "Boom 1000 Index",
    "Crash 1000 Index",
}


def family(name: str) -> str:
    n = name.upper()
    if re.match(r"^(VOLATILITY|BOOM|CRASH|STEP|JUMP|RANGE BREAK|DEX |DRIFT)", n):
        return "synthetic"
    if re.match(r"^(EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY)[A-Z]{3}$", n):
        return "fx"
    if "BASKET" in n:
        return "basket"
    if re.match(r"^(XAU|XAG|XPT|XPD)", n):
        return "metal"
    return "other"


async def main() -> None:
    async with httpx.AsyncClient(base_url=URL, headers=headers, timeout=120.0) as c:
        names = [str(n) for n in (await c.get("/api/v1/symbols/", follow_redirects=True)).json()]
        limit = asyncio.Semaphore(4)

        async def judge(name):
            async with limit:
                try:
                    await c.post(f"/api/v1/symbols/select/{name}")
                    r = await c.get(
                        "/api/v1/symbols/rates/pos",
                        params={"symbol": name, "timeframe": "M5", "num_bars": 400},
                    )
                    rows = r.json() if r.status_code == 200 else []
                    closes = [float(x["close"]) for x in rows if "close" in x]
                    if len(closes) < 100:
                        return None
                    vol = Volatility()
                    for p in closes:
                        vol.update(p)
                    if not vol.warm or vol.bps <= 0:
                        return None
                    t = await c.get(f"/api/v1/symbols/ticks/{name}", follow_redirects=True)
                    tick = t.json() if t.status_code == 200 else {}
                    if isinstance(tick, list):
                        tick = tick[0] if tick else {}
                    bid, ask = float(tick.get("bid") or 0), float(tick.get("ask") or 0)
                    if bid <= 0 or ask <= 0:
                        return None
                    spread_bps = (ask - bid) / ((ask + bid) / 2) * 10_000
                    return name, vol.bps, vol.units(spread_bps)
                except Exception:
                    return None

        # A sample per family, plus everything already carried for reference.
        by_family = {}
        for n in names:
            by_family.setdefault(family(n), []).append(n)
        sample = list(CARRIED)
        for _g, members in by_family.items():
            sample += [m for m in members if m not in CARRIED][:14]

        got = [r for r in await asyncio.gather(*(judge(n) for n in sample)) if r]
        got.sort(key=lambda r: r[2])

        print(f"{len(got)} symbols measured, spread in volatility units\n")
        print(f"{'symbol':34s} {'family':10s} {'vol bps':>8s} {'spread':>8s}  carried")
        for name, bps, cost in got:
            mark = "yes" if name in CARRIED else ""
            print(f"{name:34s} {family(name):10s} {bps:8.2f} {cost:8.3f}v  {mark}")

        cheap = [r for r in got if r[2] <= 0.5]
        print(f"\n{len(cheap)} of {len(got)} cost half a unit or less to cross")
        for g in sorted(by_family):
            here = [r for r in got if family(r[0]) == g]
            if here:
                mid = st.median([r[2] for r in here])
                print(f"   {g:10s} median {mid:6.3f}v  ({len(here)} sampled)")


asyncio.run(main())
