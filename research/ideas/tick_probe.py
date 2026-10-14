"""Can tick history be reached at all? A read-only probe, nothing fetched in bulk.

Tick-level work needs tick history, and the HTTP bridge does **not** expose it:
its only tick route is `/symbols/ticks/{symbol}`, which returns the *current*
bid and ask. The routes in use are quotes, `symbols/rates/pos` for bars,
positions, orders and account info - no tick history anywhere.

There is a second path. `trading/venues/mt5_rpyc.py` proxies **the MetaTrader5
module itself** out of the Wine prefix over RPyC, so `conn.modules.MetaTrader5`
answers with the real module and `copy_ticks_range` is reachable without
touching the bridge. No `TRADING_RPYC_HOST` is configured anywhere, though, so
whether the server is actually listening is unknown.

This probe answers that and nothing else. It tries a short list of likely
addresses, and **if** one answers it asks for a few minutes of ticks on one
symbol to see what the fields and the density look like. It is deliberately
tiny: the lab also runs the live terminal, so a bulk historical pull is a
production risk and is not what this is for.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone

PORT = int(os.environ.get("RPYC_PORT", "18812"))
HOSTS = tuple(os.environ.get("RPYC_HOSTS", "127.0.0.1,localhost").split(","))
SYMBOL = os.environ.get("SYMBOL", "EURUSD")
MINUTES = int(os.environ.get("MINUTES", "5"))


def listening(host: str, port: int, wait: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=wait):
            return True
    except OSError:
        return False


def main() -> None:
    print(f"probing for an RPyC MetaTrader5 proxy on port {PORT}\n")
    reachable = [h for h in HOSTS if listening(h, PORT)]
    for host in HOSTS:
        print(f"  {host}:{PORT}  {'OPEN' if host in reachable else 'closed'}")
    if not reachable:
        print(
            "\n  Nothing listening. Tick history is therefore not reachable from here:\n"
            "  the bridge exposes only the current tick, and the module proxy is not\n"
            "  running. Getting it would need the RPyC server started inside the Wine\n"
            "  prefix on the lab, or a tick-history route added to the bridge - and\n"
            "  the bridge is the component whose rebuild is already known to break\n"
            "  MT5 IPC, so that is not a change to make casually."
        )
        return

    try:
        import rpyc  # type: ignore[import-untyped]
    except ImportError:
        print("\n  A port is open but `rpyc` is not installed here (uv sync --extra rpyc).")
        return

    host = reachable[0]
    print(f"\n  connecting to {host}:{PORT}")
    conn = rpyc.connect(host, PORT, config={"sync_request_timeout": 30})
    try:
        mt5 = conn.modules.MetaTrader5
        print(
            f"  module proxied, version {mt5.__version__ if hasattr(mt5, '__version__') else '?'}"
        )
        if not mt5.initialize():
            print(f"  initialize() failed: {mt5.last_error()}")
            return
        info = mt5.terminal_info()
        print(
            f"  terminal build {getattr(info, 'build', '?')}, connected {getattr(info, 'connected', '?')}"
        )
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=MINUTES)
        ticks = mt5.copy_ticks_range(SYMBOL, start, end, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            print(f"  copy_ticks_range returned nothing for {SYMBOL}: {mt5.last_error()}")
            return
        got = rpyc.utils.classic.obtain(ticks)
        print(f"  {len(got)} ticks for {SYMBOL} over {MINUTES} minutes")
        print(f"  fields: {got.dtype.names}")
        print(f"  first: {got[0]}")
        print(f"  last:  {got[-1]}")
        rate = len(got) / (MINUTES * 60.0)
        print(f"  about {rate:.1f} ticks a second, so a day is roughly {rate * 86400:,.0f}")
    finally:
        try:
            conn.close()
        except Exception:  # a closed proxy raises its own family of errors
            pass


if __name__ == "__main__":
    main()
