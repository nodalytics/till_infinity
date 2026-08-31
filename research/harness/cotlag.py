"""Does positioning follow price, or lead it?

The worry that decides whether the CFTC data is worth anything: speculative
positioning is famously trend-following, so a fund's net may be a *description*
of the move that already happened rather than a claim about the next one.

Stated so it can fail. For each market and each weekly report:

* **lag**  - correlation of the change in net position with the return over the
  week *ending* on the report date. High means positioning follows price.
* **lead** - correlation of the same change with the return over the week
  *after* it. This is the only one that could be traded, and it is the one the
  literature says is near zero.

Prices come from the broker's own daily bars, so the series being correlated is
the one the desk would actually trade rather than the futures contract.
"""

from __future__ import annotations

import csv
import io
import math
import os
import zipfile
from collections import defaultdict
from datetime import UTC, datetime

import httpx

from till_infinity.news.cot import LEV_LONG, LEV_SHORT, MARKETS, NAME, OPEN_INTEREST, direction

YEARS = (2025, 2026)
HISTORY = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
URL = os.environ["TRADING_MT5_URL"]
KEY = os.environ.get("TRADING_MT5_API_KEY", "")

#: Our feed -> the broker's symbol, for the markets COT covers.
SYMBOLS = {
    "eurusd": "EURUSD",
    "gbpusd": "GBPUSD",
    "usdjpy": "USDJPY",
    "audusd": "AUDUSD",
    "usdcad": "USDCAD",
    "usdchf": "USDCHF",
    "nzdusd": "NZDUSD",
    "spx500": "US SP 500",
    "us100": "US Tech 100",
    "btc": "BTCUSD",
}

DATE_COL = 2


def positions() -> dict[str, list[tuple[float, float]]]:
    """feed -> [(report time, leveraged net as share of open interest)], oldest first."""
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for year in YEARS:
        with httpx.Client(timeout=120.0, follow_redirects=True) as c:
            blob = c.get(HISTORY.format(year=year)).content
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            raw = z.read(z.namelist()[0]).decode("latin-1")
        for row in csv.reader(io.StringIO(raw)):
            if len(row) <= LEV_SHORT:
                continue
            name = row[NAME].strip()
            feed = next((f for key, f in MARKETS.items() if name.startswith(key)), "")
            if not feed or feed not in SYMBOLS:
                continue
            try:
                when = datetime.strptime(row[DATE_COL].strip(), "%Y-%m-%d").replace(tzinfo=UTC)
                interest = float(row[OPEN_INTEREST])
                net = float(row[LEV_LONG]) - float(row[LEV_SHORT])
            except (ValueError, IndexError):
                continue
            if interest <= 0:
                continue
            out[feed].append((when.timestamp(), direction(feed) * net / interest))
    for rows in out.values():
        rows.sort()
    return out


def closes(client: httpx.Client, symbol: str, bars: int = 700) -> list[tuple[float, float]]:
    r = client.get(
        "/api/v1/symbols/rates/pos",
        params={"symbol": symbol, "timeframe": "D1", "num_bars": bars},
    )
    if r.status_code != 200:
        return []
    out = []
    for row in r.json():
        try:
            when = datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00"))
            out.append((when.replace(tzinfo=UTC).timestamp(), float(row["close"])))
        except (KeyError, ValueError, TypeError):
            continue
    out.sort()
    return out


def at(series: list[tuple[float, float]], when: float) -> float | None:
    """The last close at or before `when`."""
    found = None
    for ts, price in series:
        if ts > when:
            break
        found = price
    return found


def correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 8:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx <= 0 or sy <= 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def main() -> None:
    held = positions()
    headers = {"Accept": "application/json"}
    if KEY:
        headers["X-API-Key"] = KEY

    week = 7 * 86_400.0
    print(f"{'feed':10s} {'weeks':>6s} {'lag corr':>9s} {'lead corr':>10s}   reading")
    lags, leads = [], []
    with httpx.Client(base_url=URL, headers=headers, timeout=120.0) as client:
        for feed, symbol in SYMBOLS.items():
            rows = held.get(feed) or []
            price = closes(client, symbol)
            if len(rows) < 20 or len(price) < 100:
                print(f"{feed:10s} {len(rows):6d}  no price history")
                continue
            back, ahead, moves = [], [], []
            for i in range(1, len(rows) - 1):
                when, net = rows[i]
                before = at(price, when - week)
                now = at(price, when)
                after = at(price, when + week)
                if not before or not now or not after:
                    continue
                change = net - rows[i - 1][1]
                back.append((now - before) / before)
                ahead.append((after - now) / now)
                moves.append(change)
            if len(moves) < 20:
                print(f"{feed:10s} {len(moves):6d}  too few aligned weeks")
                continue
            lag, lead = correlation(moves, back), correlation(moves, ahead)
            lags.append(lag)
            leads.append(lead)
            note = "follows price" if lag > 0.3 else "no clear lag"
            print(f"{feed:10s} {len(moves):6d} {lag:9.3f} {lead:10.3f}   {note}")

    if lags:
        lag = sum(lags) / len(lags)
        lead = sum(leads) / len(leads)
        print(f"\nmean lag correlation  {lag:+.3f}   (vs the week just gone)")
        print(f"mean lead correlation {lead:+.3f}   (vs the week ahead)")


if __name__ == "__main__":
    main()
