"""Which of the broker's instruments are volatile enough to scalp, and affordable.

**Volatility alone is the wrong selector and that is the whole point of this
file.** `a-shorter-clock-multiplies-cost-in-r` measured the same spread as
**19x dearer at 15m than at 1d**, and `exotic-spreads-are-a-whole-bar-range`
found instruments round-tripping at **0.40 to 0.97 of one whole bar range**.
Volatile instruments tend to be the widest-quoted ones, so "scalp the top
decile by volatility" selects, by construction, the instruments whose cost is
most likely to eat the move. The ranking that matters for a scalp is therefore
**range over spread**, and both columns are printed so the difference is
visible rather than argued.

The volatility estimator is the range, not the close-to-close standard
deviation: `drive-q-from-the-range` measured the range-vs-close estimator
ratio at **0.648 within strata on FX** and 0.667 on 371 of 392 equities, and
records that the advantage *grows as the window shortens* - which is the
regime a 5m scalp lives in.

Reads only. It places nothing and modifies nothing.

    SCREEN_URL=http://<bridge>/api/v1 SCREEN_KEY=<key> \
        python3 research/harness/volatile.py 15m 120

## What a reader must not take from the output

A high `range/spread` is **not an edge**. It says a move is large relative to
the toll, which is a necessary condition for a scalp and nowhere near a
sufficient one: `research/docs/` records a scalping survey - "two of four
scalping families cannot be built here, and nothing affordable beats its coin"
- so affordability is the gate this clears, not the thesis.

`auc-is-free-on-volatility-targets` is the matching warning on the other side:
predicting volatility reads **0.805 on a constant-vol process** and 0.525
within strata, so a ranking by volatility is mostly a ranking of what is
mechanically volatile. Compare within strata before believing any selection
built on it.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request

#: MT5 timeframe names by the interval a deploy writes.
FRAMES: dict[str, str] = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
}


def _get(base: str, key: str, path: str, **params: object) -> object:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{base}{path}?{query}", headers={"X-API-Key": key}
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


def _rows(found: object, *names: str) -> list:
    if isinstance(found, list):
        return found
    if isinstance(found, dict):
        for name in names:
            if isinstance(found.get(name), list):
                return found[name]
    return []


def screen(base: str, key: str, interval: str, bars: int) -> list[dict]:
    """Every quoted instrument's range volatility and its spread, in one pass.

    One bar request per symbol and one info request, sequential. The bridge
    serves the live desk from the same process, so this does not fan out:
    `tis-research-jobs-starve-the-service` is a measured outcome on a two-core
    box, and a screener that takes a minute politely is better than one that
    takes ten seconds and makes a quote late.
    """
    frame = FRAMES.get(interval.strip().lower())
    if frame is None:
        raise SystemExit(f"{interval!r} is not a timeframe this screens: {', '.join(FRAMES)}")

    names = _rows(_get(base, key, "/symbols/"), "symbols", "data")
    found: list[dict] = []
    for name in names:
        symbol = name if isinstance(name, str) else str(name.get("name") or "")
        if not symbol:
            continue
        info = _get(base, key, f"/symbols/info/{urllib.parse.quote(symbol)}")
        if isinstance(info, dict):
            info = info.get("data") or info
        if not isinstance(info, dict):
            continue
        point = float(info.get("point") or 0.0)
        spread_pts = float(info.get("spread") or 0.0)
        bid = float(info.get("bid") or 0.0)
        # **Unquoted symbols are not cheap, they are absent.** A symbol the
        # terminal lists but does not price returns bid 0, and treating that as
        # a zero spread would put it top of any cost ranking.
        if point <= 0.0 or bid <= 0.0 or spread_pts <= 0.0:
            continue

        rates = _rows(
            _get(base, key, "/symbols/rates/pos", symbol=symbol, timeframe=frame,
                 start_pos=0, count=bars),
            "rates", "data",
        )
        ranges = [
            float(r["high"]) - float(r["low"])
            for r in rates
            if isinstance(r, dict) and r.get("high") is not None and r.get("low") is not None
        ]
        ranges = [r for r in ranges if r > 0.0]
        if len(ranges) < max(20, bars // 4):
            continue

        # The median, not the mean: a scalp meets the typical bar, and one
        # news bar would otherwise set the ranking.
        median_range = statistics.median(ranges)
        spread = spread_pts * point
        found.append(
            {
                "symbol": symbol,
                "bars": len(ranges),
                "range": median_range,
                # In basis points of price, so instruments at 1.09 and 74,000
                # are comparable at all.
                "range_bps": 10_000.0 * median_range / bid,
                "spread": spread,
                "spread_bps": 10_000.0 * spread / bid,
                # **The number that decides whether a scalp can pay.** A round
                # trip costs one spread, so this is how many round trips fit in
                # a typical bar's range.
                "range_over_spread": median_range / spread,
            }
        )
    return found


def report(found: list[dict], interval: str, top: float) -> None:
    if not found:
        print("nothing quoted and priced came back")
        return
    by_vol = sorted(found, key=lambda r: -r["range_bps"])
    cut = max(1, int(len(by_vol) * top))
    print(f"{len(found)} quoted instruments at {interval}; the top {top:.0%} by range is {cut}\n")

    print("RANKED BY VOLATILITY - what was asked for")
    print(f"{'symbol':26s} {'range bps':>10s} {'spread bps':>11s} {'range/spread':>13s} {'bars':>5s}")
    print("-" * 70)
    for row in by_vol[:cut]:
        print(f"{row['symbol']:26s} {row['range_bps']:10.1f} {row['spread_bps']:11.1f} "
              f"{row['range_over_spread']:13.2f} {row['bars']:5d}")

    affordable = [r for r in by_vol[:cut] if r["range_over_spread"] >= 3.0]
    print(f"\nof those {cut}, {len(affordable)} clear a range of 3x the spread; "
          f"{cut - len(affordable)} do not")

    print("\nRANKED BY RANGE OVER SPREAD - what a scalp can actually pay for")
    print(f"{'symbol':26s} {'range/spread':>13s} {'range bps':>10s} {'spread bps':>11s}")
    print("-" * 64)
    for row in sorted(found, key=lambda r: -r["range_over_spread"])[:cut]:
        print(f"{row['symbol']:26s} {row['range_over_spread']:13.2f} {row['range_bps']:10.1f} "
              f"{row['spread_bps']:11.1f}")

    overlap = {r["symbol"] for r in by_vol[:cut]} & {
        r["symbol"] for r in sorted(found, key=lambda r: -r["range_over_spread"])[:cut]
    }
    print(f"\n**{len(overlap)} of {cut} appear in both lists.** The gap between them is the "
          f"cost the volatility ranking does not see.")


if __name__ == "__main__":
    url = os.environ.get("SCREEN_URL")
    api = os.environ.get("SCREEN_KEY")
    if not url or not api:
        raise SystemExit("set SCREEN_URL and SCREEN_KEY; see this module's docstring")
    clock = sys.argv[1] if len(sys.argv) > 1 else "15m"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    share = float(sys.argv[3]) if len(sys.argv) > 3 else 0.15
    report(screen(url.rstrip("/"), api, clock, count), clock, share)
