"""Fetch long price history for any instrument, and record where it came from.

`stooq.py` is the source this was meant to use and it is walled: every request,
on both the `.com` and `.pl` origins, answers 200 with a JavaScript
proof-of-work page rather than the CSV. That is a deliberate anti-automation
measure and defeating it is not something this repo will carry, so this module
exists to get the same job done from sources that answer a plain request.

## What each source actually delivers

All four measured on 2026-09-20, not assumed:

| source   | instruments                      | daily from     | intraday          |
|----------|----------------------------------|----------------|-------------------|
| `yahoo`  | futures, indices, FX, crypto     | 1950 (^GSPC)   | 1h, last 720d     |
| `broker` | what the desk trades, synthetics | 1971 (FX)      | 1h to 2011, paged |
| `stooq`  | the same, in principle           | walled         | walled            |
| `file`   | whatever was handed to it        | -              | -                 |

**The broker is deeper than this repository has been assuming.** It was on record
here that its history stops around 2011, and for metals it does: XAUUSD and XAGUSD
dailies begin 2011-01-02. For the FX majors it does not - EURUSD and USDJPY
dailies reach **1971-01-03**, 15,806 bars and 55.7 years, and EURUSD 4h reaches
1977. That is three decades more than Yahoo has for the same pairs, which only
start in 2003. So for FX the broker is the better source on depth *as well as* on
quality, and the `monthly-momentum` complaint about a 218-month sample was
measuring the wrong limit.

Where Yahoo still wins is equity indices: `^GSPC` from 1950 and `^N225` from 1988,
neither of which the broker carries with any depth.

Hourly is where the two part company. Yahoo refuses to serve more than 720 days
and there is nothing to be done about it. The broker has hourly back to
2011-01-02, and reaching it is a matter of asking correctly rather than of any
limit: the bridge caps a single **response** near 50,000 records, so the history
is paged instead of requested, walking backwards with `rates/from`.

That route was briefly recorded here as broken - "it ignores the count it is
given" - and that was wrong. It counts **backward** from the date it is handed,
mirroring MQL5's `CopyRates`, so `date_from=2026-09-01, count=3000` answers with
3,000 bars running 2026-02-27 to 2026-09-01. Asking it for a date at the very
start of history returns the one bar that exists there, which is correct and
looked like a bug. `from_broker` now pages with it and reaches the full depth.

No free source anywhere has hourly gold before 2003, so 2011 from the broker is
the best available.

`stooq` is kept because the wall may be lifted or a session cookie may be
supplied, and because a reader deserves to see that it was tried rather than
never considered. `file` ingests a CSV downloaded by hand through a browser, so
that route runs through the same fault checks as everything else instead of
going straight into a model.

## How far back is worth asking for

The answer differs per instrument and the script reports it rather than assuming
it. For gold specifically, **1971 and not earlier**: the price was fixed by law
at $20.67 from 1834 and $35 from 1944, so a series covering those years is
showing an official revaluation or a purchasing-power reconstruction, not a
market. Yahoo's gold future starts in 2000 regardless, which is the real
constraint. `^GSPC` goes back to 1927 and is the longest daily series reachable
here by a wide margin - 99 years against the broker's 14.

## What this does not do

It does not adjust, splice, interpolate or clean. Every row written came from
the source as given, and the report states the **delivered** first and last date
rather than the requested ones, because a source that quietly returns less than
it was asked for is the failure mode that has cost this research the most.

Nor does it resample silently: a 4h file is built from 1h bars because no source
here serves 4h, and the file is named `_4h_derived` so nothing downstream can
mistake it for something a venue printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from stooq import faults, tickers_for, write

#: Yahoo's symbol for the instruments this desk actually trades, best first.
#:
#: Only the ones that need translating are listed; anything else is passed
#: through as given, so `ES=F` or `BTC-USD` work without editing this file. The
#: spot metal tickers (`XAUUSD=X`) are listed by Yahoo but return empty, which
#: is why gold resolves to the future.
YAHOO: dict[str, tuple[str, ...]] = {
    "gold": ("GC=F",),
    "xauusd": ("GC=F",),
    "silver": ("SI=F",),
    "xagusd": ("SI=F",),
    "spx500": ("^GSPC",),
    "us500": ("^GSPC",),
    "us100": ("^NDX",),
    "us30": ("^DJI",),
    "us2000": ("^RUT",),
    "ger40": ("^GDAXI",),
    "uk100": ("^FTSE",),
    "fra40": ("^FCHI",),
    "jp225": ("^N225",),
    "hk50": ("^HSI",),
    "aus200": ("^AXJO",),
    "vix": ("^VIX",),
    "brent": ("BZ=F",),
    "wti": ("CL=F",),
    "natgas": ("NG=F",),
    "copper": ("HG=F",),
    "btc": ("BTC-USD",),
    "eth": ("ETH-USD",),
    "dxy": ("DX-Y.NYB",),
}

#: A six-letter FX name is a Yahoo pair with `=X` appended: `eurusd` -> `EURUSD=X`.
FX = 6

#: How far back Yahoo will serve each interval, in days. Asking for more does
#: not truncate - it returns **nothing at all**, which is how a 1900 start date
#: silently produced six empty hourly files on the first run here. `None` means
#: no limit.
REACH: dict[str, int | None] = {"1m": 7, "2m": 59, "5m": 59, "15m": 59, "30m": 59, "1h": 720}


def yahoo_symbols(name: str) -> tuple[str, ...]:
    """What to ask Yahoo for, given one of this desk's names or a raw ticker."""
    low = name.strip().lower()
    known = YAHOO.get(low)
    if known:
        return known
    if len(low) == FX and low.isalpha():
        return (f"{low.upper()}=X",)
    return (name.strip(),)


def from_yahoo(name: str, interval: str, since: str) -> list[tuple]:
    """Rows as `write` wants them, or `[]` when Yahoo has nothing for it.

    Yahoo serves daily history in full but caps 1h at roughly 730 days, and it
    signals the cap by returning the short series rather than by erroring - so
    the caller reports the delivered range and this does not pretend otherwise.
    """
    import yfinance as yf

    start = dt.datetime.strptime(since, "%Y%m%d").replace(tzinfo=dt.UTC)
    reach = REACH.get(interval)
    if reach is not None:
        floor = dt.datetime.now(dt.UTC) - dt.timedelta(days=reach)
        if start < floor:
            print(
                f"   {interval}: asked from {start.date()}, Yahoo serves {reach}d "
                f"- starting {floor.date()}",
                file=sys.stderr,
            )
            start = floor
    for symbol in yahoo_symbols(name):
        try:
            frame = yf.Ticker(symbol).history(
                start=start, interval=interval, auto_adjust=False, raise_errors=False
            )
        except Exception as exc:
            print(f"   {symbol}: {type(exc).__name__} {str(exc)[:80]}", file=sys.stderr)
            continue
        if frame is None or frame.empty:
            print(f"   {symbol}: empty", file=sys.stderr)
            continue
        rows = []
        for when, bar in frame.iterrows():
            try:
                row = (
                    int(when.timestamp()),
                    float(bar["Open"]),
                    float(bar["High"]),
                    float(bar["Low"]),
                    float(bar["Close"]),
                    float(bar.get("Volume", 0.0) or 0.0),
                )
            except (KeyError, ValueError, TypeError):
                continue
            # A bar with no range and no volume is Yahoo padding a closed
            # session, not a print. Keeping them would manufacture thousands of
            # zero-return observations and flatter every volatility estimate.
            if row[1] == row[2] == row[3] == row[4] and row[5] == 0.0:
                continue
            rows.append(row)
        if rows:
            print(f"   {symbol}: {len(rows)} rows", file=sys.stderr)
            return rows
    return []


#: The bridge's names for the intervals it serves.
TIMEFRAMES = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "2h": "H2",
    "4h": "H4",
    "1d": "D1",
    "1w": "W1",
}

#: The most bars the bridge will serve in one response.
#:
#: **Measured, not guessed, and asking for more does not truncate - it 404s.**
#: 50,000 answers and 100,000 does not, on both the positional and the range
#: route, which puts the ceiling in the response rather than in the history: the
#: bridge turns every bar into a dict and then into JSON inside a 1GB container.
#: The first version of this asked for 400,000, read the 404 as "this symbol does
#: not exist", and reported that for all 722 of them.
PAGE = 20_000

#: Backoff when even `PAGE` is refused - a busy terminal sometimes is.
RETREAT = (20_000, 10_000, 5_000, 2_000)

#: Most pages to walk back before giving up, so a bridge that keeps answering
#: the same window cannot spin here forever.
PAGES = 60

#: Where the bridge key lives when it is not in the environment.
#:
#: **A key does not go on a command line.** Anything passed as an argument is
#: readable in `ps` by every account on the box and lands in a shell history, and
#: the runner that launches this forwards `KEY=VAL` pairs as literal argv. So the
#: file is the route, and the environment variable is kept only because a
#: container legitimately injects it that way.
KEY_FILE = "~/.mt5key"


def bridge_key() -> str:
    """The bridge key, from the environment or from `KEY_FILE`, or empty."""
    import os
    from pathlib import Path

    found = os.environ.get("TRADING_MT5_API_KEY", "").strip()
    if found:
        return found
    path = Path(KEY_FILE).expanduser()
    try:
        return path.read_text("utf8").strip()
    except OSError:
        return ""


def _bars_from(raw: object) -> list[tuple]:
    """The bridge's JSON rows as `write` wants them, skipping anything malformed."""
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            bar = (
                int(_stamp(row.get("time"))),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row.get("tick_volume") or row.get("real_volume") or 0.0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if bar[0] > 0:
            out.append(bar)
    return out


def _walk_back(ask, name: str, code: str, gathered: dict[int, tuple], floor: float) -> None:
    """Page backwards from the oldest bar held until history runs out.

    **`rates/from` counts backward, and that is the whole trick.**

    It is documented as taking the date of "the first bar of the requested
    sample", which reads as a start. It is not: it mirrors MQL5's `CopyRates` and
    returns `count` bars *ending* at that date. Measured - `date_from=2026-09-01,
    count=3000` answers with 3,000 bars running 2026-02-27 to 2026-09-01.

    An earlier version read it as a start, asked from 1970, got the single bar
    that exists at the very beginning of history, discarded it as the forming bar
    and reported "nothing" for all 722 symbols. It then recorded in this file that
    the route "ignores its count", which was wrong: the route works and was being
    asked the wrong question.
    """
    for page in range(PAGES):
        if not gathered:
            return
        oldest = min(gathered)
        if oldest <= floor:
            return
        edge = dt.datetime.fromtimestamp(oldest, dt.UTC) - dt.timedelta(seconds=1)
        try:
            raw = ask(
                "/symbols/rates/from",
                {
                    "symbol": name,
                    "timeframe": code,
                    "date_from": edge.strftime("%Y-%m-%d %H:%M:%S"),
                    "count": PAGE,
                },
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"   {name} {code} page {page + 1}: {type(exc).__name__}", file=sys.stderr)
            return
        fresh = {b[0]: b for b in _bars_from(raw) if b[0] not in gathered}
        if not fresh:
            # The beginning of what this symbol has. Not an error, and the only
            # honest way to find it: the bridge cannot be asked how deep it goes.
            return
        gathered.update(fresh)


def from_broker(name: str, interval: str, since: str) -> list[tuple]:
    """Bars from the desk's own MT5 bridge - the feed it actually trades.

    **This is the only source here with trustworthy extremes**, and the only one
    that has the synthetic indices at all, which no public source carries. It
    also reaches 2016 on hourlies where Yahoo reaches two years. What it does not
    have is depth on dailies: the broker's own history stops around 2011, which
    is why the long daily panel still comes from `yahoo`.

    The address and key come from `TRADING_MT5_URL` and `TRADING_MT5_API_KEY`,
    never from an argument, because this file is in a public repository and the
    bridge is not a public service. There is no default: without the variables
    this returns nothing and says so.

    A real 4h is served here, so unlike `yahoo` nothing is folded.
    """
    import os

    url = os.environ.get("TRADING_MT5_URL", "").rstrip("/")
    if not url:
        print("   no TRADING_MT5_URL - there is no bridge to read", file=sys.stderr)
        return []
    code = TIMEFRAMES.get(interval)
    if not code:
        print(f"   the bridge does not serve {interval}", file=sys.stderr)
        return []

    headers = {"Accept": "application/json"}
    key = bridge_key()
    if key:
        headers["X-API-Key"] = key

    def ask(path: str, query: dict[str, object] | None = None) -> object:
        target = f"{url}/api/v1{path}"
        if query:
            target += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(target, headers=headers)
        with urllib.request.urlopen(request, timeout=180) as answer:
            return json.loads(answer.read())

    # An unselected symbol answers 200 with an empty list, which is
    # indistinguishable from a quiet market - so select first, always.
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"{url}/api/v1/symbols/select/{urllib.parse.quote(name)}",
                headers=headers,
                method="POST",
            ),
            timeout=60,
        ).read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"   could not select {name}: {type(exc).__name__}", file=sys.stderr)

    keep = dt.datetime.strptime(since, "%Y%m%d").replace(tzinfo=dt.UTC)

    # The newest page comes off the positional route; everything older is walked
    # back from it.
    gathered: dict[int, tuple] = {}
    for count in RETREAT:
        try:
            raw = ask("/symbols/rates/pos", {"symbol": name, "timeframe": code, "num_bars": count})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"   {name} {interval} at {count}: {type(exc).__name__}", file=sys.stderr)
            continue
        for bar in _bars_from(raw):
            gathered[bar[0]] = bar
        if gathered:
            break

    floor = keep.timestamp()
    _walk_back(ask, name, code, gathered, floor)

    rows = sorted(b for b in gathered.values() if b[0] >= floor)
    # The most recent bar is still forming - its close is simply the current
    # price - so a pattern read from it is a claim the next tick can withdraw.
    # Guarded, because a one-row answer would otherwise become a zero-row answer.
    return rows[:-1] if len(rows) > 1 else rows


def _stamp(raw: object) -> float:
    """A bar's open time as epoch seconds, whichever way the bridge spelled it.

    It answers an ISO string on this bridge and a number on others, and reading
    a string as a number gives 1970 - which looks like a date rather than like an
    error, so it is worth its own function.
    """
    if isinstance(raw, int | float):
        return float(raw)
    if not isinstance(raw, str) or not raw:
        return 0.0
    text = raw.replace("Z", "+00:00")
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    return (when if when.tzinfo else when.replace(tzinfo=dt.UTC)).timestamp()


def from_stooq(name: str, interval: str, since: str) -> list[tuple]:
    """Kept so the wall is visible in the output rather than in a comment."""
    from stooq import fetch, parse

    if interval != "1d":
        print(f"   stooq serves dailies only, not {interval}", file=sys.stderr)
        return []
    until = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
    for ticker in tickers_for(name):
        rows = parse(fetch(ticker, since, until))
        if rows:
            return rows
    return []


def from_file(name: str, interval: str, since: str) -> list[tuple]:  # noqa: ARG001
    """Ingest a CSV a human downloaded, through the same checks as a fetch.

    The path is `<name>` itself, so `--source file gold=/tmp/xauusd_d.csv` is
    spelled by passing the path as the instrument. Stooq's own column names are
    what this expects, because a browser download from Stooq is the reason it
    exists.
    """
    from pathlib import Path

    from stooq import parse

    path = Path(name)
    if not path.exists():
        print(f"   {name}: no such file", file=sys.stderr)
        return []
    rows = parse(path.read_text("utf8", "replace"))
    keep = dt.datetime.strptime(since, "%Y%m%d").replace(tzinfo=dt.UTC).timestamp()
    return [r for r in rows if r[0] >= keep]


SOURCES = {
    "yahoo": from_yahoo,
    "broker": from_broker,
    "stooq": from_stooq,
    "file": from_file,
}

#: Bars per bucket when folding a longer interval out of 1h. Not a venue's 4h -
#: see the module docstring - which is why the filename says so.
DERIVED = {"4h": 4, "8h": 8, "12h": 12}

#: Intervals a source serves itself, so nothing is folded that need not be. The
#: bridge prints a real 4h; Yahoo does not, and folding its 1h is the only way to
#: get one.
NATIVE: dict[str, frozenset[str]] = {
    "broker": frozenset(TIMEFRAMES),
    "yahoo": frozenset({"1h", "1d", "1wk", "1mo"}),
    "stooq": frozenset({"1d"}),
    "file": frozenset(DERIVED) | {"1h", "1d"},
}


def resample(rows: list[tuple], every: int) -> list[tuple]:
    """Fold `every` consecutive bars into one, open-first high-max low-min close-last.

    Buckets on bar count rather than on the clock, which keeps it honest across
    sessions of different length at the cost of bucket edges that do not line up
    with a wall clock. Nothing downstream reads the edges, only the geometry.
    """
    out = []
    for at in range(0, len(rows) - every + 1, every):
        chunk = rows[at : at + every]
        out.append(
            (
                chunk[0][0],
                chunk[0][1],
                max(c[2] for c in chunk),
                min(c[3] for c in chunk),
                chunk[-1][4],
                sum(c[5] for c in chunk),
            )
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", nargs="*", default=["gold"], help="instruments or raw tickers")
    ap.add_argument("--source", default="yahoo", choices=sorted(SOURCES))
    ap.add_argument(
        "--intervals",
        default="1d",
        help="comma separated: 1d, 1h, and 4h/8h/12h which are folded from 1h",
    )
    ap.add_argument("--since", default="19000101", help="YYYYMMDD; the source decides what it has")
    ap.add_argument("--into", default=".secrets", help="directory for the gzipped CSVs")
    args = ap.parse_args()

    get = SOURCES[args.source]
    wanted = [i.strip() for i in args.intervals.split(",") if i.strip()]
    worst = 0
    for name in args.what:
        # Everything derived comes off one 1h pull, so fetch it once.
        cache: dict[str, list[tuple]] = {}
        native = NATIVE.get(args.source, frozenset())
        for interval in wanted:
            fold = interval in DERIVED and interval not in native
            base = "1h" if fold else interval
            if base not in cache:
                cache[base] = get(name, base, args.since)
            rows = cache[base]
            if fold:
                rows = resample(rows, DERIVED[interval])
            tag = f"{interval}_derived" if fold else interval
            if not rows:
                print(f"{name:<10} {interval:<4} nothing from {args.source}")
                worst = 1
                continue
            path = f"{args.into}/{name}_{tag}_{args.source}.csv.gz"
            write(path, rows)
            first = dt.datetime.fromtimestamp(min(r[0] for r in rows), dt.UTC).date()
            last = dt.datetime.fromtimestamp(max(r[0] for r in rows), dt.UTC).date()
            span = (last - first).days / 365.25
            print(
                f"{name:<10} {interval:<4} {len(rows):>7} rows  "
                f"{first} to {last}  ({span:.1f}y)  -> {path}"
            )
            bad = faults(rows)
            if bad:
                print(f"           faults: {bad}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
