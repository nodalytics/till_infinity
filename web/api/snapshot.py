"""Write the open book to a local file. **The only thing here that talks to a terminal.**

Run it where the desk runs:

    uv run python -m web.api.snapshot --once
    uv run python -m web.api.snapshot --every 30

The dashboard never calls the bridge. It reads the file this writes, so the
service that answers a browser holds no key and makes no outbound call, and
the only process with a credential is this one - started by hand, on the host
that already has the credential.

**Two GET routes, both read-only**: `/terminal/account/info` and
`/positions/`. Nothing here can place, modify or close anything; there is no
POST, PUT or DELETE in this file.

`/positions/` is deliberately **not** treated as empty on a 404.
`adapters/mt5/bridge.py` records why: a 404 turned into an empty list is
indistinguishable from a flat account, and reconciliation believing the
account is flat when it is not is how a desk opens a position it already
holds. A failed read writes `message` and keeps the previous file, rather than
writing an empty book that would read as "everything is closed".

**No identifiers leave the terminal.** The login, the server name, the broker
and the API key are read here and never written: the file is rendered in a
browser, and an account number on a screen is an account number on a
screenshot. Balance, equity, margin and currency are written, because the
exposure panel is arithmetic on them.

The settings are the desk's own names - `TRADING_MT5_URL`,
`TRADING_MT5_API_KEY`, `TRADING_MT5_API_PATH` - read directly rather than
through `strategies.config`, so that importing this module cannot pull the
execution client into a process that is only meant to read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

#: The prefix the bridge mounts its routes under. `adapters/mt5/bridge.py`
#: spells it `API = "/api/v1"` and adds it to the base URL rather than to each
#: route, which is why no route string below carries it.
DEFAULT_API_PATH = "/api/v1"

#: Where the file lands. `web/api/book.py` reads the same default.
DEFAULT_OUT = ".data/live/book.json"

ROOT = Path(__file__).resolve().parents[2]


def _out(raw: str | None) -> Path:
    found = Path(raw or DEFAULT_OUT).expanduser()
    return found if found.is_absolute() else (ROOT / found)


def _number(value: Any) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _side(row: dict[str, Any]) -> str:
    """MT5 position type: 0 is a buy, 1 is a sell."""
    kind = row.get("type")
    if isinstance(kind, str):
        return kind.lower()
    return "sell" if kind == 1 else "buy"


def _position(row: dict[str, Any]) -> dict[str, Any]:
    """One position, with only the fields the dashboard draws.

    `sl` is the field that matters: zero or absent is a position with no stop
    at the broker. Three of those ran for hours here on 2026-11-11 and cost
    about 22 in account currency to close by hand, so it is carried verbatim
    rather than normalised into a boolean here - the reader decides.
    """
    stop = _number(row.get("sl")) or 0.0
    return {
        "ticket": str(row.get("ticket") or ""),
        "symbol": str(row.get("symbol") or ""),
        "side": _side(row),
        "volume": _number(row.get("volume")) or 0.0,
        "entry": _number(row.get("price_open")),
        "price": _number(row.get("price_current")),
        "stop": stop or None,
        "target": _number(row.get("tp")) or None,
        "profit": _number(row.get("profit")),
        "opened": _number(row.get("time")),
        "magic": int(row["magic"]) if isinstance(row.get("magic"), int) else None,
    }


def _account(raw: dict[str, Any]) -> dict[str, Any]:
    """Account figures, with every identifier left behind on purpose."""
    return {
        "currency": str(raw.get("currency") or ""),
        "balance": _number(raw.get("balance")),
        "equity": _number(raw.get("equity")),
        "margin": _number(raw.get("margin")),
        "free_margin": _number(raw.get("margin_free") or raw.get("free_margin")),
        "leverage": int(raw["leverage"]) if isinstance(raw.get("leverage"), int) else None,
    }


async def collect(client: httpx.AsyncClient) -> dict[str, Any]:
    """One read of the book. Raises rather than returning a half-empty one."""
    account = await client.get("/terminal/account/info")
    account.raise_for_status()
    positions = await client.get("/positions/")
    positions.raise_for_status()

    rows = positions.json()
    if isinstance(rows, dict):
        rows = rows.get("positions") or rows.get("data") or []
    if not isinstance(rows, list):
        raise ValueError(f"/positions/ returned {type(rows).__name__}, not a list")

    raw = account.json()
    return {
        "taken_at": time.time(),
        "account": _account(raw if isinstance(raw, dict) else {}),
        "positions": [_position(row) for row in rows if isinstance(row, dict)],
        "message": "",
    }


def write(payload: dict[str, Any], target: Path) -> None:
    """Replace the file atomically, so a reader never sees half a book."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=".book-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as out:
            json.dump(payload, out, indent=1)
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


async def once(target: Path) -> int:
    """Read the bridge and write the file. Returns a process exit code."""
    url = os.environ.get("TRADING_MT5_URL", "").strip()
    if not url:
        print("TRADING_MT5_URL is not set; this must run where the desk runs")
        return 2

    headers = {"Accept": "application/json"}
    key = os.environ.get("TRADING_MT5_API_KEY", "").strip()
    if key:
        headers["X-API-Key"] = key
    path = os.environ.get("TRADING_MT5_API_PATH") or DEFAULT_API_PATH

    async with httpx.AsyncClient(
        base_url=url.rstrip("/") + path, headers=headers, timeout=10.0
    ) as client:
        try:
            payload = await collect(client)
        except (httpx.HTTPError, ValueError) as error:
            # The previous file is left alone. An empty book written over a
            # real one reads as "everything closed", which is the one wrong
            # answer this panel must never give.
            print(f"could not read the book: {type(error).__name__}: {error}")
            return 1

    write(payload, target)
    held = len(payload["positions"])
    naked = sum(1 for row in payload["positions"] if not row["stop"])
    print(f"wrote {target} - {held} position(s), {naked} without a stop")
    return 0


async def loop(target: Path, seconds: float) -> int:
    while True:
        await once(target)
        await asyncio.sleep(seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=None, help=f"where to write (default {DEFAULT_OUT})")
    parser.add_argument("--every", type=float, default=0.0, help="repeat every N seconds")
    parser.add_argument("--once", action="store_true", help="read once and exit")
    args = parser.parse_args()

    target = _out(args.out)
    if args.every > 0 and not args.once:
        try:
            return asyncio.run(loop(target, args.every))
        except KeyboardInterrupt:
            return 0
    return asyncio.run(once(target))


if __name__ == "__main__":
    raise SystemExit(main())
