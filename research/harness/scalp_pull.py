"""Deepen the M1 store for the instruments a scalp can afford.

    ./.secrets/lab.sh run research/harness/scalp_pull.py

`data/fastsyn` holds 50,000 M1 bars and `data/fast` 20,000. At a 1-minute clock
50,000 bars is 35 days and yields a few hundred non-overlapping trades per
rule, which is below the ~100-trade line this repo treats as noise once a cell
is split by instrument. Worse, the three instruments that are cheapest at 15
minutes - the US indices - have **no sub-15-minute bars stored at all**, and an
opening-range breakout cannot be measured without them because a synthetic has
no session to open.

So this pages `rates/from` backwards for M1, the way `history.py` does, and
writes `data/scalp/<symbol>.1m.npz` with the `spread` column kept. `rates/from`
counts **backward** from the date it is handed - `count` bars *ending* there -
which `history.py` records as the one thing about that route that has been read
wrongly before.

`real_volume` is **not** stored, deliberately: it reads 0 on every bar of this
feed, which is why VWAP and a volume-surge confirmation are not in the study
that uses this file.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request as request
from pathlib import Path

import numpy as np

BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"
OUT = Path.home() / "till_infinity" / "data" / "scalp"
WANT = int(os.environ.get("WANT", "300000"))
PAGE = 50_000
PAGES = 24

SYMBOLS = (
    "US Tech 100",
    "Wall Street 30",
    "US SP 500",
    "Step Index",
    "Jump 75 Index",
    "Volatility 25 Index",
    "Volatility 75 Index",
    "Volatility 25 (1s) Index",
    "Volatility 75 (1s) Index",
    "Volatility 100 (1s) Index",
)
FIELDS = ("open", "high", "low", "close", "volume", "spread")


def ask(path: str, params: dict) -> list:
    key = (Path.home() / ".mt5key").read_text().strip()
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = request.Request(url, headers={"X-API-Key": key})  # noqa: S310
    with request.urlopen(req, timeout=180) as response:  # noqa: S310
        got = json.loads(response.read().decode())
    return got if isinstance(got, list) else []


def rows_from(raw: list) -> dict[int, tuple[float, ...]]:
    out: dict[int, tuple[float, ...]] = {}
    for row in raw:
        when = row.get("time")
        if not when:
            continue
        stamp = int(dt.datetime.fromisoformat(when).replace(tzinfo=dt.UTC).timestamp())
        out[stamp] = (
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row.get("tick_volume") or 0.0),
            float(row.get("spread") or 0.0),
        )
    return out


def pull(symbol: str) -> dict[int, tuple[float, ...]]:
    edge = dt.datetime.now(dt.UTC)
    gathered: dict[int, tuple[float, ...]] = {}
    for page in range(PAGES):
        try:
            raw = ask(
                "/symbols/rates/from",
                {
                    "symbol": symbol,
                    "timeframe": "M1",
                    "date_from": edge.strftime("%Y-%m-%d %H:%M:%S"),
                    "count": PAGE,
                },
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  {symbol} page {page + 1}: {type(exc).__name__}", file=sys.stderr)
            break
        fresh = {k: v for k, v in rows_from(raw).items() if k not in gathered}
        if not fresh:
            print(f"  {symbol}: beginning of history at page {page + 1}")
            break
        gathered |= fresh
        print(f"  {symbol}: {len(gathered):,} bars", flush=True)
        if len(gathered) >= WANT:
            break
        edge = dt.datetime.fromtimestamp(min(gathered), dt.UTC) - dt.timedelta(seconds=1)
    return gathered


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for symbol in SYMBOLS:
        got = pull(symbol)
        if len(got) < 1000:
            print(f"{symbol}: only {len(got)} bars, not written")
            continue
        order = sorted(got)
        arrays = {"time": np.array(order, dtype=np.int64)}
        for i, name in enumerate(FIELDS):
            arrays[name] = np.array([got[t][i] for t in order], dtype=np.float64)
        path = OUT / f"{symbol}.1m.npz"
        np.savez_compressed(path, **arrays)
        first = dt.datetime.fromtimestamp(order[0], dt.UTC).date()
        last = dt.datetime.fromtimestamp(order[-1], dt.UTC).date()
        print(f"{symbol}: {len(order):,} bars {first} .. {last} -> {path.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
