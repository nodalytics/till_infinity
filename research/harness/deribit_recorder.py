"""Record Deribit's option surface, so the implied-volatility question becomes answerable.

    python research/harness/deribit_recorder.py --out ~/options-data --sweeps 1

**This recorder never trades.** It calls two public endpoints - `get_instruments`
and `get_book_summary_by_currency` - and no `private/` route exists in this file.
That is a property of the code, not a promise about how it is invoked, and
`tests/test_deribit_recorder.py` asserts it against this module's string literals
through the AST - not its raw text, which cannot tell a call from a mention.

## Why this is the gate for the whole options programme

An option has to beat the market's **implied** volatility, not a trailing
estimate. Nothing in this repository has ever shown that, because until
2026-09-24 it held no option prices at all. Deribit publishes a `mark_iv` per
instrument and the whole surface arrives in a single REST call, so the comparison
costs a collector and no credentials. If our forecasts cannot beat it, there is no
options edge and no execution path should be built.

## Shape

One HTTP GET per currency per sweep. Gzipped CSV, one file a day, appended - the
same shape as `payout_logger.py`, and for the same reason: a research collector
that needs a schema migration to add a column is a collector that stops
collecting.

Failures do not stop it. The one thing that must not happen is an empty
successful-looking sweep: Deribit answers **HTTP 200 with a JSON-RPC error body**,
so a naive reader records a quiet market when the venue actually refused. `_get`
is where that is caught, and an empty sweep writes **no file** rather than a
header with no rows under it.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import signal
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

# Run by path - `python research/harness/deribit_recorder.py` - and Python puts
# this file's directory on `sys.path`, not the repository root, so
# `research.harness.deribit` would not import. `lab.sh run` happens to work
# because it exports PYTHONPATH, which would have hidden this locally only.
# Same bootstrap `susceptibility.py` uses for its sibling import.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness import deribit

#: Currencies with a liquid option surface on Deribit.
CURRENCIES: tuple[str, ...] = ("BTC", "ETH")

#: Seconds between sweeps. Five minutes: the surface is about 1,050 rows a
#: currency, so this is a few hundred thousand rows a day, and an implied
#: volatility does not move meaningfully faster than this for a forecast measured
#: over hours.
SWEEP_SECONDS = 300

#: Seconds between the two calls in one sweep, and between currencies. Deribit
#: publishes a rate limit and a research collector should stay far inside it.
REQUEST_PAUSE = 1.0


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    """One public call. Returns the payload, or `{}` on anything that went wrong.

    Deribit answers 200 with `{"error": ...}`, so a status check is not enough and
    the caller cannot distinguish a refusal from an empty market without this.
    """
    try:
        reply = client.get(f"{deribit.base()}/api/v2/{path}", params=params, timeout=30.0)
    except httpx.HTTPError:
        return {}
    if reply.status_code != 200:
        return {}
    try:
        body = reply.json()
    except ValueError:
        return {}
    return {} if "error" in body else body


def sweep(client: httpx.Client, currency: str, at: float) -> list[deribit.Row]:
    """The whole surface for one currency, or an empty list."""
    listing = _get(
        client,
        "public/get_instruments",
        {"currency": currency, "kind": "option", "expired": "false"},
    )
    instruments = {str(row.get("instrument_name")): row for row in (listing.get("result") or [])}
    if not instruments:
        return []
    time.sleep(REQUEST_PAUSE)
    book = _get(
        client,
        "public/get_book_summary_by_currency",
        {"currency": currency, "kind": "option"},
    )
    return deribit.parse_summary(book, instruments=instruments, at=at)


def writer(out_dir: Path) -> Callable[[list[deribit.Row]], None]:
    """Append rows to today's gzipped CSV, writing the header once."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def write(rows: list[deribit.Row]) -> None:
        if not rows:
            return
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        path = out_dir / f"deribit_{day}.csv.gz"
        fresh = not path.exists()
        with gzip.open(path, "at", newline="") as handle:
            out = csv.DictWriter(handle, fieldnames=list(deribit.FIELDS))
            if fresh:
                out.writeheader()
            for row in rows:
                out.writerow({name: getattr(row, name) for name in deribit.FIELDS})

    return write


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.environ.get("OUT", "deribit"))
    parser.add_argument(
        "--sweeps",
        type=int,
        default=int(os.environ.get("SWEEPS", "0")) or None,
        help="stop after this many sweeps; omit to run until stopped",
    )
    args = parser.parse_args()

    # A local with `nonlocal` rather than a module global, matching
    # `payout_logger.py`. The flag belongs to this run, not to the module.
    stopping = False

    def stop(*_args: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    write = writer(Path(args.out).expanduser())
    done = 0
    print(f"recording {deribit.base()}", flush=True)
    with httpx.Client() as client:
        while not stopping and (args.sweeps is None or done < args.sweeps):
            got = 0
            for currency in CURRENCIES:
                rows = sweep(client, currency, at=time.time())
                write(rows)
                got += len(rows)
                time.sleep(REQUEST_PAUSE)
            done += 1
            print(f"{datetime.now(UTC):%H:%M:%S} sweep {done}: {got} rows", flush=True)
            if args.sweeps is not None and done >= args.sweeps:
                break
            # Sleep in one-second slices so a SIGTERM is noticed promptly rather
            # than up to five minutes later.
            for _ in range(SWEEP_SECONDS):
                if stopping:
                    break
                time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
