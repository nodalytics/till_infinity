"""What the broker says a market entry costs in slippage, per instrument.

Run against a live MT5 bridge, because **neither side of the question is in the
journal**: the Nautilus desk writes `decision` rows and no fills at all, so a
planned-versus-actual pair does not exist there. MT5 keeps both halves - the
*order* carries `price_open` (what was asked) and the *deal* carries `price`
(what was given) - which is `judge-the-desk-on-the-broker-not-the-journal`
applying to fill quality as well as to P&L.

**A market order does not always record what it asked for.** A bare market
order has `price_open = 0.0`, and the first run of this looked like that and
read as "unmeasurable" - but those rows were `magic 0` hand probes. The adapter
sends a price with its FOK market orders, so every *desk* order carries one.
The magic filter is therefore not a tidiness: without it this measures hand
probes and reports them as the desk.

Usage, from a host that can reach the bridge:

    SLIPPAGE_URL=http://<bridge>/api/v1 SLIPPAGE_KEY=<key> \
        python3 research/harness/slippage.py 2026-10-01 2026-11-11

Reads only. Nothing here places, modifies or closes anything.

## What the numbers mean

**Positive is adverse.** A buy filled above what it asked for, or a sell filled
below, has paid slippage. Reported in points and as a share of that symbol's
spread, because a point is not comparable across instruments - `Crash 500
Index` and `EURUSD` differ by four orders of magnitude, so a pooled mean in
points is meaningless and is printed last with that warning attached.

**The spread is the one read at query time, not at fill time.** It varies -
`seasonality-belongs-on-q` measured FX intraday volatility peaking 14-15 UTC at
3x - so `mean/spread` is indicative rather than exact, and a ratio near a
decision boundary should be re-measured against the spread each fill actually
faced. Stated here because it is the limitation most likely to be forgotten.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

#: `ORDER_STATE_FILLED`. A partially filled or cancelled order has no deal to
#: compare against and is not a fill quality question.
FILLED = 4

#: `DEFAULT_MAGIC` is 777_701 and `MAGIC_BAND` widens it per strategy, so ours
#: are the 777_7xx numbers. Magic 0 is a hand-placed probe.
#: `judge-the-desk-on-the-broker-not-the-journal` records that an off-by-one
#: here relabels every strategy as its neighbour.
OURS = range(777_700, 777_800)

#: Market order types. A pending order fills at its own price or better by
#: construction, so its "slippage" is a different quantity and is reported
#: separately rather than pooled in.
MARKET = {0: "BUY", 1: "SELL"}

#: The Nautilus migration. Fills either side of it came from different engines
#: over the same bridge, so they are reported as separate arms - pooling them
#: would attribute the retired engine's execution to the current one.
CUTOVER = dt.datetime(2026, 10, 31, tzinfo=dt.UTC).timestamp()


def _get(base: str, key: str, path: str, **params: object) -> object:
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    request = urllib.request.Request(f"{base}{path}?{query}", headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"  {path} -> HTTP {exc.code}", file=sys.stderr)
        return None


def _rows(found: object, *names: str) -> list[dict]:
    if isinstance(found, list):
        return found
    if isinstance(found, dict):
        for name in names:
            if isinstance(found.get(name), list):
                return found[name]
    return []


def measure(base: str, key: str, start: str, end: str) -> dict[str, dict[str, list[float]]]:
    """Slippage in spreads, by era and symbol, for every desk market fill."""
    window = {"from_date": f"{start}T00:00:00", "to_date": f"{end}T00:00:00"}
    orders = _rows(_get(base, key, "/history/orders", **window), "orders", "data")
    deals = _rows(_get(base, key, "/history/deals", **window), "deals", "data")
    by_order = {deal.get("order"): deal for deal in deals}

    spreads: dict[str, tuple[float, float]] = {}

    def scale(symbol: str) -> tuple[float, float]:
        if symbol not in spreads:
            info = _get(base, key, f"/symbols/info/{urllib.parse.quote(symbol)}") or {}
            if isinstance(info, dict):
                info = info.get("data") or info
            spreads[symbol] = (
                float((info or {}).get("point") or 0.0),
                float((info or {}).get("spread") or 0.0),
            )
        return spreads[symbol]

    eras: dict[str, dict[str, list[float]]] = {
        "pre-Nautilus": defaultdict(list),
        "Nautilus": defaultdict(list),
    }
    for order in orders:
        if order.get("state") != FILLED or int(order.get("magic") or 0) not in OURS:
            continue
        if order.get("type") not in MARKET:
            continue
        asked = float(order.get("price_open") or 0.0)
        deal = by_order.get(order.get("ticket"))
        if asked <= 0.0 or deal is None:
            continue
        point, spread = scale(str(order.get("symbol")))
        if point <= 0.0 or spread <= 0.0:
            continue
        sign = 1 if order["type"] == 0 else -1
        points = sign * (float(deal.get("price") or 0.0) - asked) / point
        era = "Nautilus" if float(order.get("time_setup") or 0.0) >= CUTOVER else "pre-Nautilus"
        eras[era][str(order.get("symbol"))].append(points / spread)
    return eras


def report(eras: dict[str, dict[str, list[float]]]) -> None:
    for era, rows in eras.items():
        flat = [value for values in rows.values() for value in values]
        if not flat:
            print(f"{era}: no market fills")
            continue
        per_symbol = [statistics.fmean(values) for values in rows.values()]
        error = statistics.stdev(flat) / len(flat) ** 0.5 if len(flat) > 1 else float("nan")
        print(f"\n{era}: {len(flat)} fills on {len(rows)} instruments")
        print(f"  per-fill mean      {statistics.fmean(flat):+.3f} spreads  (se {error:.3f})")
        print(f"  per-instrument med {statistics.median(per_symbol):+.3f} spreads")
        if len(flat) < 100:
            print("  **under ~100 fills: the prior is noise, and this says so**")
        print(f"  {'symbol':26s} {'n':>5s} {'mean spreads':>13s}")
        for symbol, values in sorted(rows.items(), key=lambda kv: -statistics.fmean(kv[1])):
            print(f"  {symbol:26s} {len(values):5d} {statistics.fmean(values):+13.3f}")


if __name__ == "__main__":
    url = os.environ.get("SLIPPAGE_URL")
    api = os.environ.get("SLIPPAGE_KEY")
    if not url or not api:
        raise SystemExit("set SLIPPAGE_URL and SLIPPAGE_KEY; see this module's docstring")
    begin = sys.argv[1] if len(sys.argv) > 1 else "2026-10-01"
    finish = sys.argv[2] if len(sys.argv) > 2 else "2026-11-11"
    report(measure(url.rstrip("/"), api, begin, finish))
