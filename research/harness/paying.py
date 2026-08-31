"""Does the 300-1,800s edge pay the spread?

research/horizon.md found +16.44% of edge on 484 touches resolving between five
and thirty minutes - about 4.5 standard errors, and the one unambiguously real
number in that table. It sits between the tautology at the fast end and the
horizon `max_hold` trades at the slow one.

Directional accuracy is not money. In volatility units, a touch is worth

    (2 * accuracy - 1) * E|push|   -   cost to cross

and the cost runs from 0.170v on a synthetic to 2.267v on FX
(research/catalogue.md). An edge that cannot pay two units is not an edge on
the instruments that charge two units.

Accuracy here is the **floor** - `up_rate > 0.5` predicting the push direction -
because it can be recomputed for every touch in the record. The kNN scores
about 5.5 points better in this band, so every number below understates what
the live model would do, deliberately.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
from collections import defaultdict

import httpx

from till_infinity.structures.volatility import Volatility

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
URL = os.environ["TRADING_MT5_URL"]
KEY = os.environ.get("TRADING_MT5_API_KEY", "")

LOW, HIGH = 300.0, 1800.0
MIN_TOUCHES = 40


def touches() -> dict[str, list[tuple[bool, float]]]:
    """feed -> [(the floor was right, |push| in volatility units)]."""
    conn = sqlite3.connect(JOURNAL, uri=True)
    out: dict[str, list[tuple[bool, float]]] = defaultdict(list)
    for (blob,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='outcome'"
        " ORDER BY time DESC LIMIT 400000"
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        rate, push, secs = d.get("up_rate"), d.get("push_vol"), d.get("seconds")
        feed = str(d.get("feed") or "")
        if rate is None or push is None or secs is None or not feed:
            continue
        try:
            rate, push, secs = float(rate), float(push), float(secs)
        except (TypeError, ValueError):
            continue
        if not (LOW <= secs < HIGH) or rate == 0.5:
            continue
        out[feed].append(((rate > 0.5) == (push > 0), abs(push)))
    return out


def cost(client: httpx.Client, aliases: tuple[str, ...]) -> float | None:
    """The spread to cross, in volatility units. See research/catalogue.md.

    Every alias is tried, not just the first. `INSTRUMENTS` lists the names
    different brokers use and Deriv's are the spaced ones - "US Tech 100"
    rather than "US100" - so taking `aliases[0]` silently left ten instruments
    unpriced, including several with the largest gross edge.
    """
    for symbol in aliases:
        got = _cost_of(client, symbol)
        if got is not None:
            return got
    return None


def _cost_of(client: httpx.Client, symbol: str) -> float | None:
    try:
        client.post(f"/api/v1/symbols/select/{symbol}")
        r = client.get(
            "/api/v1/symbols/rates/pos",
            params={"symbol": symbol, "timeframe": "M5", "num_bars": 400},
        )
        closes = (
            [float(x["close"]) for x in r.json() if "close" in x] if r.status_code == 200 else []
        )
        if len(closes) < 100:
            return None
        vol = Volatility()
        for c in closes:
            vol.update(c)
        if not vol.warm or vol.bps <= 0:
            return None
        t = client.get(f"/api/v1/symbols/ticks/{symbol}", follow_redirects=True)
        tick = t.json() if t.status_code == 200 else {}
        if isinstance(tick, list):
            tick = tick[0] if tick else {}
        bid, ask = float(tick.get("bid") or 0), float(tick.get("ask") or 0)
        if bid <= 0 or ask <= 0:
            return None
        return vol.units((ask - bid) / ((ask + bid) / 2) * 10_000)
    except Exception:
        return None


def main() -> None:
    from till_infinity.trading.config import INSTRUMENTS

    found = touches()
    headers = {"Accept": "application/json"}
    if KEY:
        headers["X-App-Token"] = KEY
        headers["X-API-Key"] = KEY

    print(f"touches resolving in {LOW:.0f}-{HIGH:.0f}s, floor accuracy against cost to cross\n")
    print(
        f"{'feed':22s} {'n':>5s} {'acc':>6s} {'E|push|':>8s} {'gross':>7s} {'cost':>7s} {'net':>7s}"
    )
    rows = []
    with httpx.Client(base_url=URL, headers=headers, timeout=90.0) as client:
        for feed, seen in sorted(found.items(), key=lambda kv: -len(kv[1])):
            if len(seen) < MIN_TOUCHES:
                continue
            names = INSTRUMENTS.get(feed) or ()
            spread = cost(client, names) if names else None
            acc = sum(1 for right, _ in seen if right) / len(seen)
            push = st.median(size for _r, size in seen)
            gross = (2 * acc - 1) * push
            net = gross - spread if spread is not None else None
            rows.append((feed, len(seen), acc, push, gross, spread, net))
            spread_s = f"{spread:7.3f}" if spread is not None else "      -"
            net_s = f"{net:+7.3f}" if net is not None else "      -"
            print(
                f"{feed:22s} {len(seen):5d} {acc:6.1%} {push:8.2f} {gross:7.3f} {spread_s} {net_s}"
            )

    paying = [r for r in rows if r[6] is not None and r[6] > 0]
    judged = [r for r in rows if r[6] is not None]
    print(f"\n{len(paying)} of {len(judged)} instruments clear their own spread")
    if judged:
        total = sum(r[6] for r in judged) / len(judged)
        print(f"mean net edge per touch: {total:+.3f} volatility units")
        print("\nthe floor understates - the kNN is about 5.5 points better in this band,")
        print(
            "which is worth roughly",
            f"{0.055 * 2 * st.median([r[3] for r in judged]):+.3f}v more per touch",
        )


if __name__ == "__main__":
    main()
