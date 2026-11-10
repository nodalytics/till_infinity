"""The published TradingView catalogue, framed and audited for what this venue can express.

    MODE=frame  python research/ideas/tv_survey.py     # the sample frame, from boosts
    MODE=source python research/ideas/tv_survey.py     # Pine source for the open scripts
    MODE=audit  python research/ideas/tv_survey.py     # the data each script needs
    MODE=rules  python research/ideas/tv_survey.py SLUG...   # print one script's source

Writes to `$OUT` (default `.data/tvsurvey`). Fetched source is **never committed**:
it is other people's code and the repository is public. Only the derived counts are.

**Why a keyword frame and not a crawl.** `pubscripts-suggest-json` answers a
search with 50 published scripts ordered by boosts, so a frozen keyword list
gives a frame that re-runs to the same shape on a later date and that nobody
chose after seeing the answers. `KEYWORDS` below was written before any source
was read; it spans the families TradingView's own script directory shows plus
the ones this desk has already measured, so the survey can report what it
*missed* as well as what it found. It is not a census: a family with no keyword
is absent, and `boosts` is popularity, not quality.

**What the audit decides, and what it cannot.** Three of the four columns are
mechanical facts about a script's inputs, and they are the ones that kill whole
families here:

* `closed` - `access != 1`, so the source is protected or invite-only. The rule
  is then unknowable, and an unknowable rule is not deployable at any cost. This
  is a fact about the publication, not a judgement of the script.
* `volume` - the source reads `volume` or one of the volume-derived built-ins
  (`ta.vwap`, `ta.obv`, `ta.mfi`, `ta.cmf`, `ta.accdist`, ...). MT5 sends
  `real_volume = 0` on every bar of this venue and `tick_volume`, a count of
  quote updates (`adapters/mt5/data.py` reads `tick_volume or real_volume or
  0.0`), so a size-weighted statistic has no input here. See
  [scalping.md](../docs/scalping.md), which measured 0 of 80,000 M1 bars with a
  non-zero `real_volume` and Step Index's `tick_volume` capped at 62 a minute by
  the publication clock.
* `external` - `request.financial`, `request.economic`, `request.dividends`,
  `request.splits` or `request.earnings`. Fundamentals, releases and corporate
  actions the MT5 feed does not carry.
* `lookahead` - `barmerge.lookahead_on`. Not a venue limit: a higher-timeframe
  bar read before it closed, which makes the published picture unreproducible
  live whatever the data. `research/tradingview/README.md` records the same trap
  in this desk's own Pine, where `lookahead_off` is called load-bearing.

A script can clear all four and still be undeployable, because cost and the
repository's own refutations are not in this file. The screen is a floor.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.parse as parse
import urllib.request as request
from pathlib import Path

OUT = Path(os.environ.get("OUT", ".data/tvsurvey"))
SUGGEST = "https://www.tradingview.com/pubscripts-suggest-json/"
FACADE = "https://pine-facade.tradingview.com/pine-facade/get/"
#: A generic client name. The repository is public and the operator's details
#: are not this service's business.
AGENT = "research-client/1.0"
PAUSE = float(os.environ.get("PAUSE", "0.4"))
TOP = int(os.environ.get("TOP", "8"))

#: Frozen 2026-11-10, before any source was fetched. Order is arbitrary; the
#: grouping is the family this survey reports against.
KEYWORDS: tuple[tuple[str, str], ...] = (
    ("rsi", "oscillator"),
    ("macd", "oscillator"),
    ("stochastic", "oscillator"),
    ("cci", "oscillator"),
    ("divergence", "oscillator"),
    ("moving average", "trend"),
    ("supertrend", "trend"),
    ("adx", "trend"),
    ("ichimoku", "trend"),
    ("parabolic sar", "trend"),
    ("bollinger bands", "band"),
    ("keltner", "band"),
    ("donchian", "band"),
    ("squeeze", "volatility"),
    ("volatility", "volatility"),
    ("atr", "volatility"),
    ("standard deviation", "volatility"),
    ("volume profile", "volume"),
    ("vwap", "volume"),
    ("cumulative volume delta", "volume"),
    ("money flow", "volume"),
    ("order flow", "volume"),
    ("order block", "smc"),
    ("fair value gap", "smc"),
    ("market structure", "smc"),
    ("liquidity sweep", "smc"),
    ("smart money concepts", "smc"),
    ("ict", "smc"),
    ("support resistance", "level"),
    ("pivot points", "level"),
    ("fibonacci", "level"),
    ("supply demand", "level"),
    ("harmonic patterns", "pattern"),
    ("elliott wave", "pattern"),
    ("wyckoff", "pattern"),
    ("gann", "pattern"),
    ("chart patterns", "pattern"),
    ("candlestick patterns", "pattern"),
    ("zigzag", "pattern"),
    ("session", "clock"),
    ("seasonality", "clock"),
    ("renko", "clock"),
    ("machine learning", "model"),
    ("kalman filter", "model"),
    ("hurst", "model"),
    ("cycle", "model"),
    ("position size", "risk"),
    ("trailing stop", "risk"),
    ("correlation", "cross"),
    ("gamma exposure", "cross"),
)

#: Volume vocabulary. `volume` as a bare word plus the built-ins that read it,
#: because a script can be volume-dependent without ever naming the series.
VOLUME = re.compile(
    r"\bvolume\b|ta\.(vwap|obv|mfi|cmf|pvt|nvi|pvi|accdist|wad|vwma|iii|wvad)"
    r"|\bvwap\b|\bobv\b",
    re.IGNORECASE,
)
EXTERNAL = re.compile(r"request\.(financial|economic|dividends|splits|earnings)")
#: Does the script know a trade costs anything? `strategy.commission_type` and
#: `syminfo.mintick`-scaled slippage are how a Pine author charges one. This is
#: the column that explains the rest of the survey: TradingView's feed carries
#: no bid-ask, so a published rule is almost never priced, and on this venue
#: cost is the binding constraint (0.40-0.97 of a whole bar range round trip on
#: the exotics, 19x dearer at 15m than at 1d for the same spread).
COST = re.compile(
    r"commission|slippage|\bspread\b|syminfo\.pointvalue|strategy\.commission",
    re.IGNORECASE,
)
LOOKAHEAD = re.compile(r"lookahead_on")
#: `lookahead_on` is not automatically a defect. The documented non-repainting
#: idiom is `request.security(..., close[1], lookahead=barmerge.lookahead_on)`,
#: which asks for the *previous* higher-timeframe bar and is therefore closed.
#: So `lookahead` is an upper bound and this is the heuristic that narrows it:
#: an offset `[1]` within the 200 characters before the flag. A heuristic
#: because a Pine call spans lines and nothing here parses the language - the
#: two counts are reported together for that reason.
OFFSET = re.compile(r"\[\s*1\s*\]")
COMMENT = re.compile(r"//.*?$", re.MULTILINE)
STRING = re.compile(r'"[^"\n]*"')


def get(url: str, *, tries: int = 3) -> bytes:
    """One GET, or raise. A failed fetch is never a zero: the caller records it.

    The frame is a measurement, so a dropped request must not read as "no
    scripts matched" - `frame.csv` carries a `n` per keyword for exactly that.
    """
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = request.Request(url, headers={"User-Agent": AGENT})  # noqa: S310
            with request.urlopen(req, timeout=30) as response:  # noqa: S310
                return response.read()
        except Exception as error:  # noqa: BLE001 - any failure is "it did not say"
            last = error
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"fetch failed: {url}") from last


def slug(script_id: str) -> str:
    """A filesystem name for a `PUB;<hex>` id."""
    return re.sub(r"[^A-Za-z0-9]", "_", script_id)


def frame() -> None:
    """Top-50-by-boosts for each frozen keyword, deduplicated by script id."""
    OUT.mkdir(parents=True, exist_ok=True)
    rows: dict[str, dict[str, object]] = {}
    counts: list[tuple[str, str, int]] = []
    for keyword, family in KEYWORDS:
        url = SUGGEST + "?" + parse.urlencode({"search": keyword})
        results = json.loads(get(url).decode()).get("results", [])
        counts.append((keyword, family, len(results)))
        for rank, item in enumerate(results):
            script_id = str(item.get("scriptIdPart", ""))
            if not script_id:
                continue
            row = rows.setdefault(
                script_id,
                {
                    "script_id": script_id,
                    "name": item.get("scriptName", ""),
                    "author": (item.get("author") or {}).get("username", ""),
                    "boosts": item.get("agreeCount", 0),
                    "access": item.get("access", 0),
                    "version": item.get("version", ""),
                    "kind": (item.get("extra") or {}).get("kind", ""),
                    "keywords": "",
                    "best_rank": rank,
                    "family": family,
                },
            )
            seen = str(row["keywords"]).split(";") if row["keywords"] else []
            if keyword not in seen:
                row["keywords"] = ";".join([*seen, keyword])
            if rank < int(row["best_rank"]):
                row["best_rank"], row["family"] = rank, family
        time.sleep(PAUSE)
    write(OUT / "frame.csv", sorted(rows.values(), key=lambda r: -int(r["boosts"])))
    write(
        OUT / "keywords.csv",
        [{"keyword": k, "family": f, "n": n} for k, f, n in counts],
    )
    print(f"{len(rows)} distinct scripts over {len(KEYWORDS)} keywords -> {OUT}/frame.csv")


def write(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"nothing to write to {path}")
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def selected() -> list[dict[str, str]]:
    """The top `TOP` by boosts within each keyword, over the whole frame.

    Per keyword rather than overall, so a family with few boosts (every
    `gamma exposure` script, say) is still represented. A script reached by two
    keywords appears once.
    """
    rows = read(OUT / "frame.csv")
    keep: dict[str, dict[str, str]] = {}
    for keyword, _family in KEYWORDS:
        hits = [r for r in rows if keyword in r["keywords"].split(";")]
        hits.sort(key=lambda r: -int(r["boosts"]))
        for row in hits[:TOP]:
            keep[row["script_id"]] = row
    return sorted(keep.values(), key=lambda r: -int(r["boosts"]))


def source() -> None:
    """Pine source for every selected open script, into `$OUT/src` (gitignored)."""
    folder = OUT / "src"
    folder.mkdir(parents=True, exist_ok=True)
    got = missing = closed = 0
    for row in selected():
        if row["access"] != "1":
            closed += 1
            continue
        path = folder / f"{slug(row['script_id'])}.pine"
        if path.exists():
            got += 1
            continue
        version = row["version"] if row["version"] not in ("", "-1") else "last"
        url = FACADE + parse.quote(row["script_id"], safe="") + "/" + version
        try:
            body = json.loads(get(url).decode())
        except Exception:  # noqa: BLE001 - a protected or moved script
            missing += 1
            continue
        text = body.get("source") or ""
        if not text:
            missing += 1
            continue
        path.write_text(text)
        got += 1
        time.sleep(PAUSE)
    print(f"source: {got} fetched/cached, {missing} unavailable, {closed} closed")


def strip(text: str) -> str:
    """Source without comments or string literals.

    Both matter: `// volume-weighted` and `plot(..., title="Volume")` would
    otherwise count a script as volume-dependent on its prose. Measured on this
    frame the difference is large enough to change the headline, which is why
    the raw count is reported beside it.
    """
    return STRING.sub('""', COMMENT.sub("", text))


def naked(code: str) -> bool:
    """Is there a `lookahead_on` with no `[1]` offset in front of it?

    True means at least one call reads a higher-timeframe bar that has not
    closed, which draws history the live chart cannot reproduce. False means
    every occurrence looks like the documented safe idiom.
    """
    return any(
        not OFFSET.search(code[max(0, hit.start() - 200) : hit.start()])
        for hit in LOOKAHEAD.finditer(code)
    )


def audit() -> None:
    """One row per selected script: what data its source actually reads."""
    folder = OUT / "src"
    rows: list[dict[str, object]] = []
    for row in selected():
        path = folder / f"{slug(row['script_id'])}.pine"
        text = path.read_text() if path.exists() else ""
        code = strip(text)
        rows.append(
            {
                "script_id": row["script_id"],
                "name": row["name"],
                "author": row["author"],
                "boosts": int(row["boosts"]),
                "keywords": row["keywords"],
                "closed": int(row["access"] != "1"),
                "source_lines": len(text.splitlines()),
                "volume": int(bool(VOLUME.search(code))),
                "volume_raw": int(bool(VOLUME.search(text))),
                "external": int(bool(EXTERNAL.search(code))),
                "lookahead": int(bool(LOOKAHEAD.search(code))),
                "lookahead_naked": int(naked(code)),
                "cost": int(bool(COST.search(code))),
                "strategy": int("strategy(" in code),
            }
        )
    write(OUT / "audit.csv", rows)
    have = [r for r in rows if r["source_lines"]]
    print(f"{len(rows)} selected, {sum(r['closed'] for r in rows)} closed, {len(have)} with source")
    for column in ("volume", "external", "lookahead", "lookahead_naked", "cost", "strategy"):
        n = sum(int(r[column]) for r in have)
        print(f"  {column}: {n} of {len(have)} open scripts ({n / len(have):.1%})")
    families: dict[str, set[str]] = {}
    for keyword, family in KEYWORDS:
        for row in rows:
            if keyword in str(row["keywords"]).split(";"):
                families.setdefault(family, set()).add(str(row["script_id"]))
    by_id = {str(r["script_id"]): r for r in rows}
    summary = []
    for family, ids in sorted(families.items()):
        members = [by_id[i] for i in ids]
        open_source = [r for r in members if r["source_lines"]]
        summary.append(
            {
                "family": family,
                "scripts": len(members),
                "closed": sum(int(r["closed"]) for r in members),
                "open": len(open_source),
                **{
                    column: sum(int(r[column]) for r in open_source)
                    for column in ("volume", "external", "lookahead", "cost", "strategy")
                },
                "boosts_top": max(int(r["boosts"]) for r in members),
            }
        )
    write(OUT / "families.csv", summary)
    print(
        f"  {'family':<12}{'n':>4}{'closed':>8}{'open':>6}"
        f"{'volume':>8}{'ext':>5}{'look':>6}{'cost':>6}{'strat':>7}"
    )
    for row in summary:
        print(
            f"  {row['family']:<12}{row['scripts']:>4}{row['closed']:>8}{row['open']:>6}"
            f"{row['volume']:>8}{row['external']:>5}{row['lookahead']:>6}{row['cost']:>6}{row['strategy']:>7}"
        )


def rules(ids: list[str]) -> None:
    """Print the stored source for named scripts, to read a rule off it."""
    for one in ids:
        matches = sorted((OUT / "src").glob(f"*{slug(one)}*.pine"))
        for path in matches or []:
            print(f"===== {path.name} =====")
            print(path.read_text())
        if not matches:
            print(f"no stored source matching {one}")


if __name__ == "__main__":
    mode = os.environ.get("MODE", "frame")
    if mode == "frame":
        frame()
    elif mode == "source":
        source()
    elif mode == "audit":
        audit()
    elif mode == "rules":
        rules(sys.argv[1:])
    else:
        raise SystemExit(f"MODE must be frame, source, audit or rules, not {mode!r}")
