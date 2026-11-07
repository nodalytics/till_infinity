"""The CFTC's Commitments of Traders, the whole history, for the eight markets.

**Why this exists rather than the adapter.** `adapters/news/sources/cot.py`
fetches `newcot/FinFutWk.txt` - the *current week only* - and its own comment
says the Socrata API, which has the whole history behind one endpoint, was
"not adopted" because nothing consumed it. Nothing could backtest a
positioning rule against one week, so this is the history fetch that was
skipped.

**And a different series.** The adapter reads *leveraged funds* from the
disaggregated file (TFF, `gpe5-46if`). The rule under test names
**non-commercial** speculators, which is the Legacy report (`6dca-aqww`) and a
different set of traders: Legacy splits reportable positions commercial /
non-commercial, while TFF splits them dealer / asset manager / leveraged fund /
other. A test of one is not a test of the other, so this takes Legacy and says
so in the output.

**The sign is the one thing that must not be wrong**, and `cot.py` says so
first: CME currency futures are quoted as the foreign currency in dollars, so
a long JAPANESE YEN future is long yen, which is *short* USDJPY. This module
deliberately does **not** apply that mapping - it stores the contract's own
net, in contracts and as a share of open interest, and leaves the mapping to
the harness that trades it. One transformation in one place, where the test
that checks it lives.

Run it on the lab: the endpoint answers there and returns 403 from the
workstation.

    ./.secrets/lab.sh run research/harness/cotfetch.py
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

RESOURCE = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

#: The eight markets the rule trades, as the **exact** contract names, several
#: per feed where the CFTC has renamed one.
#:
#: Substring matching does not work here and the first run proved it: `GOLD`
#: also matches `MICRO GOLD` and `GOLDMAN-SACHS COMMODITY INDEX`, `EURO FX`
#: matches `EURO FX/JAPANESE YEN XRATE`, and `JAPANESE YEN` matches that same
#: cross - so a keyword would have pooled a cross-rate's open interest into a
#: major's, which is the silent wrong answer rather than the loud one.
#:
#: Several names per feed because the rename is real and the eras are
#: disjoint: `NZ DOLLAR`, `NEW ZEALAND DOLLAR` and `NEW ZEALAND DOLLARS` are
#: one contract across three periods, as are `BRITISH POUND` and `BRITISH
#: POUND STERLING`, and `AUSTRALIAN DOLLAR(S)`. Taking one would silently
#: shorten the history instead of failing - and the trailing z-score needs 156
#: weeks, so a truncated series does not error, it just scores the wrong
#: baseline.
WANTED: dict[str, tuple[str, ...]] = {
    "eur": ("EURO FX",),
    "jpy": ("JAPANESE YEN",),
    "gbp": ("BRITISH POUND", "BRITISH POUND STERLING"),
    "chf": ("SWISS FRANC",),
    "cad": ("CANADIAN DOLLAR",),
    "aud": ("AUSTRALIAN DOLLAR", "AUSTRALIAN DOLLARS"),
    "nzd": ("NZ DOLLAR", "NEW ZEALAND DOLLAR", "NEW ZEALAND DOLLARS"),
    "xau": ("GOLD",),
}

#: Only the exchange that actually lists the contract. "GOLD" alone also
#: matches a handful of swap and index products on other venues, and pooling
#: them would add open interest from a market nobody is trading here.
EXCHANGES = ("CHICAGO MERCANTILE EXCHANGE", "COMMODITY EXCHANGE INC.")

PAGE = 50_000
OUT = Path.home() / "till_infinity" / "data" / "cot"


def _get(params: dict[str, str]) -> list[dict]:
    """One Socrata page. Plain urllib so this needs nothing installed."""
    url = f"{RESOURCE}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(  # noqa: S310 - a fixed https endpoint
        url, headers={"User-Agent": "till-infinity-research/1.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return json.loads(response.read().decode())


def names() -> dict[str, list[str]]:
    """Every `market_and_exchange_names` belonging to each wanted market.

    Matched on the contract name **before** the exchange suffix and compared
    whole, for the reason `WANTED` records. Printed, because a market that
    resolves to nothing has to be visible in the log rather than absent from a
    panel.
    """
    rows = _get(
        {
            "$select": "market_and_exchange_names",
            "$group": "market_and_exchange_names",
            "$limit": "20000",
        }
    )
    every = sorted({str(r.get("market_and_exchange_names") or "") for r in rows})
    found: dict[str, list[str]] = {}
    for feed, keys in WANTED.items():
        hits = [
            name
            for name in every
            # `split(" - ")[0]` is the contract, the rest is the exchange.
            if name.upper().split(" - ")[0].strip() in keys
            and any(x in name.upper() for x in EXCHANGES)
        ]
        if hits:
            found[feed] = hits
        else:
            print(f"  {feed}: nothing matched {keys}", flush=True)
    return found


def history(markets: list[str]) -> list[dict]:
    """Every weekly row for one market, oldest first, across its renames.

    Deduplicated on the report date: the eras are disjoint in principle, and
    an overlap would otherwise double-count a week into the 4-week change.
    """
    rows: list[dict] = []
    for market in markets:
        rows.extend(_one(market))
    seen: set[str] = set()
    out: list[dict] = []
    for row in sorted(rows, key=lambda r: str(r.get("report_date_as_yyyy_mm_dd") or "")):
        date = str(row.get("report_date_as_yyyy_mm_dd") or "")
        if date and date not in seen:
            seen.add(date)
            out.append(row)
    return out


def _one(market: str) -> list[dict]:
    """Every weekly row for one contract name, paged."""
    out: list[dict] = []
    while True:
        page = _get(
            {
                "$where": f"market_and_exchange_names='{market}'",
                "$select": (
                    "report_date_as_yyyy_mm_dd,open_interest_all,"
                    "noncomm_positions_long_all,noncomm_positions_short_all"
                ),
                "$order": "report_date_as_yyyy_mm_dd",
                "$limit": str(PAGE),
                "$offset": str(len(out)),
            }
        )
        out.extend(page)
        if len(page) < PAGE:
            return out


def _number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("resolving market names", flush=True)
    found = names()
    missing = sorted(set(WANTED) - set(found))
    if missing:
        print(f"UNRESOLVED: {missing} - the panel would be short, so stopping", flush=True)
        return 1
    for feed, markets in sorted(found.items()):
        print(f"  {feed:4s} <- {', '.join(markets)}", flush=True)

    print("\nfetching", flush=True)
    written = 0
    for feed, markets in sorted(found.items()):
        rows = history(markets)
        kept = []
        for row in rows:
            oi = _number(row.get("open_interest_all"))
            long_ = _number(row.get("noncomm_positions_long_all"))
            short = _number(row.get("noncomm_positions_short_all"))
            date = str(row.get("report_date_as_yyyy_mm_dd") or "")[:10]
            # A row missing any of the three cannot make a share of open
            # interest, and a zero open interest cannot divide. Dropped rather
            # than filled: an invented position is the one nobody catches.
            if not date or oi is None or oi <= 0.0 or long_ is None or short is None:
                continue
            kept.append(
                {
                    "feed": feed,
                    "report_date": date,
                    "open_interest": oi,
                    "noncomm_long": long_,
                    "noncomm_short": short,
                    # The contract's own net, NOT mapped to a USD pair. See
                    # the module docstring on why the sign stays here.
                    "net": long_ - short,
                    "net_share": (long_ - short) / oi,
                }
            )
        path = OUT / f"{feed}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(kept[0]))
            writer.writeheader()
            writer.writerows(kept)
        span = f"{kept[0]['report_date']} .. {kept[-1]['report_date']}"
        print(f"  {feed:4s} {len(kept):5d} weeks  {span}  -> {path}", flush=True)
        written += len(kept)

    print(f"\n{written} weekly rows over {len(found)} markets (Legacy, non-commercial)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
