"""Pull long price history from Stooq, and say exactly what came back.

The broker's own history stops at 2011 for gold dailies and 2016 for hourlies, which
is 218 non-overlapping months - too few to separate a decayed effect from a noisy
one. `research/docs/monthly-momentum.md` has the arithmetic: halving a standard
error needs four times the data.

## How far back is worth asking for

**1971, and not earlier, because before that gold had no price to chart.** It was
pegged by law - $20.67 an ounce from 1834 to 1933 and $35 from 1944 to 1971 - so
there is no daily variation in the era, and a series that appears to show one is
showing an official revaluation or a scholarly reconstruction of purchasing power.
Bretton Woods collapsed in August 1971 and gold floated from then.

That still roughly triples the sample against the broker's 2011, which improves a
standard error by about 1.7x.

## What this does not do

It does not clean, adjust, splice or interpolate anything. Every row it writes came
from the source as-is, and it reports the true first and last date rather than the
requested range - because a source that silently returns less is the failure mode
that matters, and today's research has been wrong four times from numbers that were
real but not what they appeared to be.

Intraday history is a separate problem and this does not solve it: Stooq serves
dailies well and intraday only recently. Hourly gold before about 2003 is not
publicly available at all, from anyone, free or otherwise.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import sys
import urllib.error
import urllib.parse
import urllib.request

#: Stooq's daily CSV endpoint. `i=d` is the interval; `d1`/`d2` bound the range.
CSV_URL = "https://stooq.com/q/d/l/"

#: Tickers to try for names that are not already Stooq tickers, best first.
#:
#: Only the ones that need translating are listed. Anything else is passed to Stooq
#: as given, so any pair works without editing this file: an FX cross is its own
#: ticker (`eurchf`, `gbpjpy`), a future carries `.f` (`cl.f`), an index carries `^`
#: (`^spx`). The desk's own feed names mostly are not Stooq tickers, which is the
#: only reason this mapping exists.
ALIASES: dict[str, tuple[str, ...]] = {
    "gold": ("xauusd", "gc.f"),
    "silver": ("xagusd", "si.f"),
    "spx500": ("^spx",),
    "us100": ("^ndq",),
    "us30": ("^dji",),
    "us2000": ("^rut",),
    "ger40": ("^dax",),
    "uk100": ("^ftm",),
    "fra40": ("^cac",),
    "jp225": ("^nkx",),
    "hk50": ("^hsi",),
    "aus200": ("^aex",),
    "brent": ("cb.f",),
    "wti": ("cl.f",),
    "btc": ("btcusd",),
    "eth": ("ethusd",),
}


def tickers_for(name: str) -> tuple[str, ...]:
    """What to ask Stooq for, given a name that may or may not be its ticker.

    Any pair works without touching this file. A six-letter alphabetic name is an
    FX cross and is its own ticker; a name carrying `.` or `^` is already in Stooq's
    own notation; and `ALIASES` covers the desk's feed names, which mostly are not.
    Unknown names are still tried as-is rather than refused - the source answers
    that question better than a hardcoded list can.
    """
    low = name.strip().lower()
    known = ALIASES.get(low)
    if known:
        return (*known, low)
    return (low,)


#: Gold floated in August 1971. Asking for earlier returns either nothing or a
#: pegged price, and neither is a time series.
FLOAT_BEGAN = "19710815"

AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)


def fetch(symbol: str, since: str, until: str, timeout: float = 60.0) -> str:
    """The raw CSV text, or "" when the source refuses or has nothing."""
    url = CSV_URL + "?" + urllib.parse.urlencode({"s": symbol, "i": "d", "d1": since, "d2": until})
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            body = answer.read().decode("utf8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"   {symbol}: {type(exc).__name__} {exc}", file=sys.stderr)
        return ""
    # Stooq answers a bad ticker with a page, not an error, so the shape decides.
    if not body.lstrip().lower().startswith("date"):
        head = body.strip().splitlines()[:1]
        print(f"   {symbol}: not CSV ({head[0][:60] if head else 'empty'})", file=sys.stderr)
        return ""
    return body


def parse(body: str) -> list[tuple[int, float, float, float, float, float]]:
    """Rows as (ts, open, high, low, close, volume), skipping anything malformed."""
    out = []
    for row in csv.DictReader(io.StringIO(body)):
        try:
            when = dt.datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=dt.UTC)
            o, h, low, c = (
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
            )
        except (KeyError, ValueError, TypeError):
            continue
        volume = 0.0
        with_volume = row.get("Volume")
        if with_volume:
            try:
                volume = float(with_volume)
            except ValueError:
                volume = 0.0
        out.append((int(when.timestamp()), o, h, low, c, volume))
    return out


def faults(rows: list[tuple[int, float, float, float, float, float]]) -> dict[str, int]:
    """Rows that cannot be a candle. Counted, not corrected."""
    bad = {"high<low": 0, "close outside": 0, "open outside": 0, "non-positive": 0}
    for _ts, o, h, low, c, _v in rows:
        if h < low:
            bad["high<low"] += 1
        if not (low <= c <= h):
            bad["close outside"] += 1
        if not (low <= o <= h):
            bad["open outside"] += 1
        if min(o, h, low, c) <= 0:
            bad["non-positive"] += 1
    return {k: v for k, v in bad.items() if v}


def write(path: str, rows: list[tuple[int, float, float, float, float, float]]) -> None:
    with gzip.open(path, "wt", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(["ts", "open", "high", "low", "close", "volume"])
        for row in sorted(rows):
            out.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "what",
        nargs="*",
        default=["gold"],
        help="any instrument or Stooq ticker: gold, eurchf, xauusd, cl.f, ^spx",
    )
    ap.add_argument("--since", default=FLOAT_BEGAN, help="YYYYMMDD, default 1971-08-15")
    ap.add_argument("--until", default=dt.datetime.now(dt.UTC).strftime("%Y%m%d"))
    ap.add_argument("--into", default=".secrets", help="directory for the gzipped CSVs")
    args = ap.parse_args()

    print(f"asking Stooq for {args.since} to {args.until}\n")
    worst = 0
    for name in args.what:
        tickers = tickers_for(name)
        for ticker in tickers:
            rows = parse(fetch(ticker, args.since, args.until))
            if not rows:
                continue
            path = f"{args.into}/{name}_1d_stooq.csv.gz"
            write(path, rows)
            first = dt.datetime.fromtimestamp(min(r[0] for r in rows), dt.UTC).date()
            last = dt.datetime.fromtimestamp(max(r[0] for r in rows), dt.UTC).date()
            bad = faults(rows)
            print(f"{name:<10} {ticker:<8} {len(rows):>7} rows  {first} to {last}  -> {path}")
            if bad:
                print(f"           faults: {bad}")
            # The requested start against the delivered one, which is the number
            # that decides whether the sample actually grew.
            asked = dt.datetime.strptime(args.since, "%Y%m%d").date()
            if first > asked:
                short = (first - asked).days / 365.25
                print(
                    f"           {short:.1f} years short of the request - "
                    f"the source does not have them"
                )
            break
        else:
            print(f"{name:<10} nothing usable from {', '.join(tickers)}")
            worst = 1
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
