"""Fill the `seqlab` bar cache from the MT5 bridge, then convert it to npz.

Two subcommands, run on two different machines, because neither machine can do
both jobs:

    python seqlab_pull.py pull     # on the terminal host: stdlib only, no numpy
    python seqlab_pull.py npz      # on the research lab: numpy, no bridge

**Why `rates/range` and not `rates/pos`.** `rates/pos` counts back from now
with `num_bars` and this deployment answers 50,000 and refuses 100,000, which
caps a 15-minute series at about two years. `rates/range` takes a window and
can be paged, and M15 history on this feed reaches back to 2015 - about ten
times the sample, which is the difference between a trigger that has events to
count and one that does not.

**The bridge sends ISO strings, not epoch numbers.** `{"time":
"2026-11-05T15:15:00"}`, with no timezone, answered against a UTC-framed
request. An earlier puller did `int(row["time"])` and died on the first row;
the same defect is recorded in `tests/test_mt5_live.py`. They are parsed as
UTC here, and the check is that a bar lands inside the window that asked for
it.

The API key is derived from the stack's own `.env` on the machine the bridge
runs on, so the credential never crosses a network or reaches a transcript.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

#: The terminal host runs Python 3.10, where `datetime.UTC` does not exist
#: yet. The study machine is 3.13; this file has to import on both.
UTC = timezone.utc  # noqa: UP017

STACK = os.environ.get("STACK", os.path.expanduser("~/mt5"))
OUT = os.environ.get("OUT", os.path.expanduser("~/seqlab"))
INTERVAL = os.environ.get("INTERVAL", "M15")
NAME = os.environ.get("NAME", "15m")
START = os.environ.get("START", "2015-01-01")
#: A window the bridge answers in one response. 180 days of M15 is ~17,000
#: rows; a year's worth has been seen to time out on a busy terminal.
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "180"))
#: The live desk polls this same terminal, so the pull is paced.
GAP = float(os.environ.get("GAP", "0.3"))

SYMBOLS = [s for s in os.environ.get("SYMBOLS", "").split("|") if s]


def key() -> str:
    for line in open(f"{STACK}/.env"):
        if line.startswith("API_KEY_SEED="):
            seed = line.split("=", 1)[1].strip().strip('"').strip("'")
            return hashlib.sha256(seed.encode()).hexdigest()
    raise SystemExit("no API_KEY_SEED in the stack's .env")


def stamp(when: float) -> str:
    return datetime.fromtimestamp(when, UTC).strftime("%Y-%m-%d %H:%M:%S")


def epoch(iso: str) -> int:
    """Epoch seconds from the bridge's naive ISO string, read as UTC."""
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp())


def get(api: str, path: str, params: dict):
    # A trailing "?" with no query is a 404 on this bridge, so an empty
    # parameter set must not produce one.
    query = urllib.parse.urlencode(params)
    url = f"http://127.0.0.1:8000/api/v1{path}" + (f"?{query}" if query else "")
    req = urllib.request.Request(url, headers={"X-API-Key": api})
    with urllib.request.urlopen(req, timeout=180) as r:
        # Whatever the route returns: `rates/*` answer with a list and
        # `symbols/info/*` with a dict. Coercing both to a list here silently
        # emptied every info call.
        return json.load(r)


def pull_one(symbol: str, api: str) -> int:
    begin = datetime.fromisoformat(START).replace(tzinfo=UTC).timestamp()
    now = time.time()
    seen: dict[int, dict] = {}
    cursor = begin
    while cursor < now:
        end = min(cursor + WINDOW_DAYS * 86_400, now)
        try:
            got = get(api, "/symbols/rates/range", {
                "symbol": symbol, "timeframe": INTERVAL,
                "start": stamp(cursor), "end": stamp(end),
            })
            rows = got if isinstance(got, list) else []
        except Exception as exc:
            print(f"  {symbol} {stamp(cursor)[:10]}: {type(exc).__name__}: {exc}", flush=True)
            rows = []
        for row in rows:
            try:
                t = epoch(str(row["time"]))
            except (KeyError, ValueError):
                continue
            # The check the ISO parse needs: a bar must land in its own window.
            if not (cursor - 86_400 <= t <= end + 86_400):
                continue
            seen[t] = {
                "t": t,
                "o": float(row["open"]), "h": float(row["high"]),
                "l": float(row["low"]), "c": float(row["close"]),
                "v": float(row.get("tick_volume") or 0.0),
                # Points, not price - the column has been misread as price here
                # before and it reorders every instrument by cost.
                "s": float(row.get("spread") or 0.0),
            }
        cursor = end
        time.sleep(GAP)
    if len(seen) < 5_000:
        print(f"{symbol}: {len(seen)} bars, too few - not written", flush=True)
        return 0
    slim = [seen[t] for t in sorted(seen)]
    # The last bar may still be forming.
    slim = slim[:-1]
    os.makedirs(OUT, exist_ok=True)
    with gzip.open(f"{OUT}/{symbol}.{NAME}.json.gz", "wt") as fh:
        json.dump(slim, fh)
    span = (slim[-1]["t"] - slim[0]["t"]) / 86_400 / 365.25
    print(f"{symbol}: {len(slim)} bars, {span:.1f}y "
          f"{stamp(slim[0]['t'])[:10]}..{stamp(slim[-1]['t'])[:10]}", flush=True)
    return len(slim)


def pull() -> None:
    api = key()
    for symbol in SYMBOLS:
        pull_one(symbol, api)


def info() -> None:
    """The per-symbol dealing cost, so a direction reading can be priced."""
    api = key()
    out = {}
    for symbol in SYMBOLS:
        url = f"/symbols/info/{urllib.parse.quote(symbol)}"
        try:
            got = get(api, url, {})
        except Exception as exc:
            print(f"{symbol}: {type(exc).__name__}: {exc}", flush=True)
            continue
        out[symbol] = got
    print(json.dumps(out, default=str))


def npz() -> None:
    """json.gz -> npz, on the machine that has numpy."""
    import numpy as np

    src = os.environ.get("SRC", OUT)
    dst = os.environ.get("DST", OUT)
    os.makedirs(dst, exist_ok=True)
    for fn in sorted(os.listdir(src)):
        if not fn.endswith(".json.gz"):
            continue
        with gzip.open(f"{src}/{fn}", "rt") as fh:
            rows = json.load(fh)
        if len(rows) < 5_000:
            print(f"{fn}: {len(rows)} rows, skipped", flush=True)
            continue
        name = fn[: -len(".json.gz")]
        np.savez_compressed(
            f"{dst}/{name}.npz",
            time=np.array([r["t"] for r in rows], dtype=np.int64),
            open=np.array([r["o"] for r in rows], dtype=np.float64),
            high=np.array([r["h"] for r in rows], dtype=np.float64),
            low=np.array([r["l"] for r in rows], dtype=np.float64),
            close=np.array([r["c"] for r in rows], dtype=np.float64),
            volume=np.array([r["v"] for r in rows], dtype=np.float64),
            spread=np.array([r.get("s", 0.0) for r in rows], dtype=np.float64),
        )
        print(f"{name}.npz: {len(rows)} bars", flush=True)


if __name__ == "__main__":
    {"pull": pull, "npz": npz, "info": info}[sys.argv[1] if len(sys.argv) > 1 else "pull"]()
