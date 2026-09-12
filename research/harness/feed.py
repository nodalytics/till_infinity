"""Real price history from the terminal on the lab, for when `prices.db` is not there.

**Correction, 2026-09-12: only `prices.db` is corrupt.** This file used to say
both stores were, which was written from one study's failure and never checked
per file - and `research/grounding.md` then downgraded its real leg to a
twentieth of its intended sample on the strength of it. Checked properly by
`dbcheck.py`: `research.db` is **1.55GB, `quick_check: ok`, 5,227,686 bars and
6,950,687 ticks all readable**. `prices.db` is 21.98GB and genuinely malformed -
invalid page numbers, both tables unreadable. Reach for `research.db` first.

The terminal is still worth having beside it, and for tick work it is better:

* **796 symbols**, the broker's whole book rather than the collected subset;
* **50,000 M1 bars in one call**, and deeper on request;
* **ticks with `time_msc`** - millisecond stamps, bid and ask - which the bars
  table never carried at all.

So this is not a fallback that loses something. For anything tick-resolved it is
strictly better than what was lost, and `research/quantising.md`'s ladder
measurement and `research/rebuilding.md`'s tick arms both want exactly this.

## The key

Read from `MT5_API_KEY`, else from `~/.mt5key` on the lab, and **never** written
into this file or passed on a command line, where it would land in shell history
and in `ps`. The terminal container holds only `API_KEY_SEED`; the key derived
from it is the same one the production desk uses, so the same value opens both.

    ./.secrets/lab.sh run research/harness/yours.py

and this module finds it. If it cannot, it says which of the two places it
looked rather than failing with a 401 three frames down.

## The clocks, which are not the same clock

`rates` returns a naive ISO string in the **terminal's** timezone. `ticks`
returns epoch seconds and `time_msc` epoch milliseconds. Mixing them is how a
lead-lag study measures its own timezone offset, so `bars` converts to epoch
seconds and both come back on one scale.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

#: Where the terminal answers on the lab. Loopback: the container publishes the
#: port on the host, and a harness runs on the host.
BASE = os.environ.get("MT5_URL", "http://127.0.0.1:8000") + "/api/v1"

#: MetaTrader's own timeframe names, which are what the route expects. The
#: package's own table is `mt5_http.MT5Http.TIMEFRAMES`; this is the subset a
#: research harness asks for, spelled the same way so results are comparable.
TIMEFRAMES: dict[str, str] = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D1",
    "1w": "W1",
}

#: How long to wait. Fifty thousand bars is a real transfer and the default
#: socket timeout will cut it off part way, which reads as an empty feed rather
#: than as a slow one.
TIMEOUT = 120.0


class NoKeyError(RuntimeError):
    """The terminal needs a key and neither place had one."""


def key() -> str:
    """The API key, from the environment or the lab's key file."""
    found = os.environ.get("MT5_API_KEY", "").strip()
    if found:
        return found
    path = Path.home() / ".mt5key"
    if path.exists():
        got = path.read_text().strip()
        if got:
            return got
    raise NoKeyError(f"set MT5_API_KEY or write the key to {path} (mode 600)")


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"X-API-Key": key()})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path}: HTTP {exc.code} {exc.reason}") from exc


def symbols() -> list[str]:
    """Every symbol the terminal carries - 796 of them, not the collected subset."""
    got = _get("/symbols/")
    return [str(s) for s in got] if isinstance(got, list) else []


def bars(symbol: str, interval: str = "1m", count: int = 5_000) -> list[dict[str, float]]:
    """OHLC bars, newest last, with `time` as epoch seconds.

    The **forming** bar is dropped. It is the last row the route returns, it is
    incomplete by definition, and including it puts a partial high and low into
    any statistic built from extremes - which is most of what this data is for.
    """
    timeframe = TIMEFRAMES.get(interval)
    if not timeframe:
        raise ValueError(f"unknown interval {interval!r} - have {', '.join(TIMEFRAMES)}")
    got = _get(
        "/symbols/rates/pos",
        {"symbol": symbol, "timeframe": timeframe, "num_bars": int(count) + 1},
    )
    if not isinstance(got, list) or len(got) < 2:
        return []
    out: list[dict[str, float]] = []
    for row in got[:-1]:
        try:
            stamp = dt.datetime.fromisoformat(str(row["time"])).replace(tzinfo=dt.UTC)
            out.append(
                {
                    "time": stamp.timestamp(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("tick_volume") or 0.0),
                    "spread": float(row.get("spread") or 0.0),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _epoch(msc: object, plain: object) -> float:
    """Seconds, from whichever of the two shapes this route happens to return.

    **The same field is a different type on different routes.** The bare tick
    route sends `time_msc` as epoch milliseconds; `/from` sends it as a naive
    ISO string with microseconds. Neither is documented and a float() on the
    wrong one raises three frames below the caller, which is how this cost a
    run rather than a line.
    """
    for value in (msc, plain):
        if value is None or value == "":
            continue
        if isinstance(value, int | float):
            got = float(value)
            # Milliseconds if it is far too large to be seconds.
            return got / 1000.0 if got > 1e11 else got
        try:
            return dt.datetime.fromisoformat(str(value)).replace(tzinfo=dt.UTC).timestamp()
        except ValueError:
            continue
    return 0.0


def ticks(
    symbol: str,
    count: int = 100_000,
    *,
    hours_back: float = 48.0,
) -> list[dict[str, float]]:
    """Ticks, oldest first, with `time` in **seconds as a float** from `time_msc`.

    Millisecond resolution is the whole reason to come here rather than to the
    bars table: `research/quantising.md` pre-registered a Range Break ladder
    whose second mode lives at 1.6 bars, which is a tick measurement and cannot
    be made on bars at all. Bid and ask both, so a spread is a measurement here
    rather than the bar column's integer points.

    **The bare `/symbols/ticks/{symbol}` route returns the latest tick and
    nothing else** - it answers "what is the price", not "what happened". History
    needs `/from` with a `date_from`, which is why this takes a lookback rather
    than only a count. Asking the bare route for a count silently returns one
    row, which reads as an empty feed rather than as the wrong endpoint.
    """
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=float(hours_back))
    got = _get(
        f"/symbols/ticks/{urllib.parse.quote(symbol)}/from",
        {"date_from": since.strftime("%Y-%m-%d %H:%M:%S"), "count": int(count)},
    )
    rows = got if isinstance(got, list) else [got]
    out: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = _epoch(row.get("time_msc"), row.get("time"))
        bid, ask = float(row.get("bid") or 0.0), float(row.get("ask") or 0.0)
        if stamp <= 0 or (bid <= 0 and ask <= 0):
            continue
        out.append({"time": stamp, "bid": bid, "ask": ask, "mid": (bid + ask) / 2.0})
    out.sort(key=lambda r: r["time"])
    return out


def healthy() -> bool:
    """Whether the terminal answers at all. Never raises - it is the probe."""
    try:
        _get("/terminal/ping")
    except Exception:
        return False
    return True


if __name__ == "__main__":  # a probe, so `lab.sh run` on this file is a check
    print(f"terminal at {BASE}: {'up' if healthy() else 'not answering'}")
    names = symbols()
    print(f"symbols: {len(names)}  e.g. {', '.join(names[:6])}")
    rows = bars("XAUUSD", "1m", 5_000)
    print(f"XAUUSD 1m bars: {len(rows)}")
    if rows:
        span = (rows[-1]["time"] - rows[0]["time"]) / 3600.0
        print(f"  spanning {span:,.1f} hours, last close {rows[-1]['close']:g}")
    got = ticks("XAUUSD", 200_000, hours_back=48)
    print(f"XAUUSD ticks: {len(got)}")
    if len(got) > 1:
        gap = (got[-1]["time"] - got[0]["time"]) / max(1, len(got) - 1)
        print(f"  mean gap {gap * 1000:,.0f} ms, last spread {got[-1]['ask'] - got[-1]['bid']:.5g}")
