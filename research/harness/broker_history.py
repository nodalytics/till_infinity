"""Pull deep candle history off the desk's own MT5 bridge, on the research machine.

Run from the repository root:  python research/harness/broker_history.py

**It is configured by environment variables, not arguments**, because it is meant
to be launched by the research-machine runner, which forwards `KEY=VAL` pairs and
cannot pass a command line. Everything it needs:

    TRADING_MT5_URL        the bridge; without it this does nothing and says so
    MATCH                  comma separated substrings to keep, case insensitive
    SYMBOLS                exact names; only usable when none contains a space
    INTERVALS              comma separated, default `1h,4h,1d`
    SINCE                  YYYYMMDD, default 19000101 - the terminal decides
    INTO                   output directory, default `data/candles`
    LIMIT                  stop after this many symbols, default 40

**Prefer `MATCH` over `SYMBOLS`.** Half the interesting instruments here are named
`Volatility 75 Index` and `Multi Step 2 Index`, and the runner that launches this
forwards its `KEY=VAL` pairs through an unquoted expansion - so a value with a
space in it does not arrive truncated, it stops the process from starting at all,
with no log to say why. `MATCH=volatility,step,xauusd` needs no spaces and says
what it means.

## Why this runs where it runs

The bridge is not reachable from a laptop and must not be hammered from the
production instance: that box has two cores and a 2.6GB container limit, and
research run on it has taken the live desk down. The research machine is also the
machine hosting the terminal, so it reaches the bridge on its own loopback and
the bars never cross a network.

The bridge key is **not** an environment variable you pass in. It is read from
the file named by `history.KEY_FILE`, because the runner forwards `KEY=VAL` pairs
as literal argv and anything in argv is readable in `ps` by every account on the
machine.

## What the bridge gives that a public source cannot

Trustworthy extremes, first. Every public daily series checked here reports a
close outside the bar's own high or low on a few percent of rows, which quietly
breaks anything that resolves a stop or a target. These bars come from the
terminal the desk trades through.

Then: a real 4h rather than four 1h bars folded together, hourly history reaching
about 2016 rather than two years, and the synthetic indices, which exist nowhere
else at all.

What it does **not** give is depth on dailies - the broker's own history runs out
around 2011. A question that needs decades still wants `history.py --source
yahoo`, and the two are meant to be used together rather than one instead of the
other.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from history import bridge_key, from_broker
from stooq import faults, write

#: Intervals to pull when nothing says otherwise. The desk's own entry
#: timeframes, plus the daily that the barrier work sizes against.
DEFAULT_INTERVALS = "1h,4h,1d"


def catalogue() -> list[str]:
    """Every symbol the bridge will list, or `[]` when it has no such route.

    Guessing ticker suffixes is how this desk has previously ended up with an
    empty series that looked like a quiet market, so when the bridge can be
    asked, it is asked.
    """
    url = os.environ.get("TRADING_MT5_URL", "").rstrip("/")
    if not url:
        return []
    headers = {"Accept": "application/json"}
    key = bridge_key()
    if key:
        headers["X-API-Key"] = key
    try:
        request = urllib.request.Request(f"{url}/api/v1/symbols/", headers=headers)
        with urllib.request.urlopen(request, timeout=120) as answer:
            found = json.loads(answer.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"no catalogue: {type(exc).__name__} {str(exc)[:70]}", file=sys.stderr)
        return []
    if isinstance(found, list):
        return [str(item) for item in found if isinstance(item, str)]
    return []


def main() -> int:
    if not os.environ.get("TRADING_MT5_URL"):
        print("TRADING_MT5_URL is not set - there is no bridge to read")
        return 1

    wanted = [s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
    if not wanted:
        listed = catalogue()
        print(f"the bridge lists {len(listed)} symbols")
        if not listed:
            print("nothing to pull: set SYMBOLS, since the bridge will not list them")
            return 1
        # An underscore stands for a space, so `volatility_75` reaches
        # `Volatility 75 Index` without a space ever entering the environment.
        match = [
            m.strip().lower().replace("_", " ")
            for m in os.environ.get("MATCH", "").split(",")
            if m.strip()
        ]
        wanted = [s for s in listed if any(m in s.lower() for m in match)] if match else listed
        if match and not wanted:
            print(f"nothing in the catalogue matches {match}")
            return 1
    limit = int(os.environ.get("LIMIT", "40"))
    if len(wanted) > limit:
        print(f"{len(wanted)} matched; taking the first {limit} (raise LIMIT to widen)")
        wanted = wanted[:limit]
    intervals = [
        i.strip() for i in os.environ.get("INTERVALS", DEFAULT_INTERVALS).split(",") if i.strip()
    ]
    since = os.environ.get("SINCE", "19000101")
    into = os.environ.get("INTO", "data/candles")
    os.makedirs(into, exist_ok=True)

    print(f"{len(wanted)} symbols x {len(intervals)} intervals -> {into}\n")
    missed = 0
    for symbol in wanted:
        for interval in intervals:
            rows = from_broker(symbol, interval, since)
            if not rows:
                print(f"{symbol:<24} {interval:<4} nothing")
                missed += 1
                continue
            # A name that is safe in a filename. Broker tickers carry suffixes
            # and occasionally punctuation, and a lost file is worse than an
            # ugly one.
            safe = "".join(c if c.isalnum() or c in "-." else "_" for c in symbol).lower()
            path = f"{into}/{safe}_{interval}_broker.csv.gz"
            write(path, rows)

            import datetime as dt

            first = dt.datetime.fromtimestamp(min(r[0] for r in rows), dt.UTC).date()
            last = dt.datetime.fromtimestamp(max(r[0] for r in rows), dt.UTC).date()
            span = (last - first).days / 365.25
            bad = faults(rows)
            print(
                f"{symbol:<24} {interval:<4} {len(rows):>7} rows  "
                f"{first} to {last}  ({span:.1f}y)" + (f"  faults: {bad}" if bad else "")
            )
    print(f"\n{missed} of {len(wanted) * len(intervals)} requests came back empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
