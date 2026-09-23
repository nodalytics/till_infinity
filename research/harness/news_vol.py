"""Does the calendar anticipate volatility, and by how much?

Run from the repository root:  python research/harness/news_vol.py

The desk's framing, and it is the right one: *"we can use news calls to anticipate volatility too
and how high the volatility might go"*.

**Volatility is the correct target for this and direction is not.** `a-theory-from-ohlc.md` records
that the signed series is near-unpredictable past a few minutes while absolute returns carry long
memory, and every directional candidate in this folder has died. A scheduled economic release is
the one event on a desk's horizon whose *timing* is known in advance with no estimation at all -
so a volatility forecast built on it needs no model of the future, only a clock and a calendar.

That makes this the cleanest causal setup in the repository. There is no look-ahead to argue about:
the release time is published days beforehand.

## The confound that decides this study

**High-importance releases are not spread across the day.** Of 161 past high-importance events in
the store, **61 land in the 12:30 UTC hour** - the US 08:30 Eastern slot - which is also when
London and New York overlap and volatility is high for reasons that have nothing to do with news.

So comparing event-window volatility against an all-hours average measures **the session, not the
release**, and would produce a large, confident, entirely spurious multiplier. `context/sessions.py`
already learns that the hour of the day carries a volatility share, which is the same fact from the
other side.

The control here is therefore **the same instrument, the same hour of the day, and the same weekday,
on dates with no event of any importance within two hours.** Four years of 15m bars make that pool
large. Any multiplier this reports is net of the diurnal and weekly pattern, which is the only way
the number means anything.

## Two questions, and the second is the one that could size a trade

**Does volatility rise after a release, and does it fall before one?** The pre-event lull is the
half usually forgotten and it is the more interesting half: a market that knows a number is coming
in twenty minutes stops trading. If both hold, the calendar predicts the *shape* of the hour, not
just its level.

**Does the surprise predict the size?** `|actual - forecast|`, standardised per indicator because
a payrolls miss in thousands and a CPI miss in tenths of a percent are not comparable. This is
available on only 74 of the events, so it is reported with that sample stated rather than pooled
into the headline.

Note what the second question is **not**: the surprise is known only at release, so it cannot
anticipate anything. It can size a position *after* the print, which is a different and smaller
claim than the first question's.

## What would make it shippable

A multiplier that is large, holds in both halves of the sample, and is reachable from the calendar
alone. That last condition is what rules the surprise out of production and rules the timing in -
`Macro` already folds news onto every level call, so a "minutes to the next high-importance event
for this instrument's currencies" feature costs nothing and decides nothing until it has been
scored.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Which currencies each instrument answers to. Both legs of a pair matter - a US release moves
#: EURUSD through the dollar just as a German one moves it through the euro.
#:
#: Gold is listed against the dollar alone. It is not a pair, and `eigen.py` measured that this
#: book's single real factor **is** the dollar, carrying 45.6% of variance - so treating gold as
#: a dollar instrument is a measurement rather than a convention.
INSTRUMENTS: dict[str, tuple[str, ...]] = {
    "eurusd": ("EUR", "EU", "DE", "FR", "IT", "USD", "US"),
    "gbpusd": ("GBP", "GB", "UK", "USD", "US"),
    "usdjpy": ("JPY", "JP", "USD", "US"),
    "xauusd": ("USD", "US"),
}

#: Bars per hour at 15m, and the windows scored, in bars, relative to the bar holding the event.
PER_HOUR = 4
WINDOWS: tuple[tuple[str, int, int], ...] = (
    # A market that knows a number is coming in twenty minutes stops trading. This is the half
    # usually left out, and it is the half that is knowable furthest ahead.
    ("pre -2h..-30m", -8, -2),
    ("the bar itself", 0, 1),
    ("+30m", 0, 2),
    ("+1h", 0, 4),
    ("+2h", 0, 8),
    ("+4h", 0, 16),
)

#: No event of any importance within this many bars of a control window, either side.
QUIET = 8

#: Minimum control windows before a comparison is made.
MIN_CONTROL = 30

#: Titles whose release minute is **not** fixed, excluded by default.
#:
#: A data release prints at a published minute. A rate decision, a statement, a press conference
#: or a speech does not - it happens "some time in" a window, and the calendar carries a nominal
#: time. That breaks the one thing this study relies on, because a move that happens before the
#: nominal minute lands in the **pre-event** window and reads as a market getting busier while it
#: waits.
#:
#: This was added to test a specific anomaly rather than to tidy the sample: usdjpy's pre-event
#: window came out at **1.902x normal** against 0.74-0.91 everywhere else, and its only
#: non-US high-importance events are `Monetary Policy Statement` and `BOJ Policy Rate`. Pass
#: `--floating` to put them back and see the difference.
FLOATING = (
    "monetary policy statement",
    "policy rate",
    "press conference",
    "speech",
    "testimony",
    "rate decision",
    "interest rate decision",
)

#: Days either side of an event that a control window may come from.
#:
#: **This was added after a first run and it is the fix that matters.** The bar history is four
#: years and the events span six weeks, so a control pool drawn from the whole history compares a
#: 2026 event against a 2022-2026 average - and any drift in an instrument's volatility *level*
#: then lands in every ratio.
#:
#: Gold is what exposed it: its pre-event window came out at **1.431x normal** where every other
#: instrument lulled at 0.58 to 0.89. A lull is a market waiting for a number; 1.431 is not a
#: market doing anything, it is gold's recent volatility being higher than its four-year mean.
#: Restricting the pool to a local window removes the level and leaves the shape.
CONTROL_DAYS = 120


def load_events(where: Path) -> list[dict]:
    """Past events, de-duplicated across the two providers."""
    now = dt.datetime.now(dt.UTC).timestamp()
    seen: dict[tuple, dict] = {}
    with gzip.open(where, "rt") as handle:
        for line in handle:
            row = json.loads(line)
            when = row.get("time")
            if not when or when >= now:
                continue
            # The two sources label the same print differently - one by country, one by
            # currency - so the key is the minute plus the title, and the richer row wins.
            key = (round(float(when) / 60.0), (row.get("title") or "").strip().lower())
            keep = seen.get(key)
            if keep is None or (row.get("actual") and not keep.get("actual")):
                seen[key] = row
    return sorted(seen.values(), key=lambda r: r["time"])


def number(text: object) -> float | None:
    """Parse a calendar figure: `0.3%`, `250K`, `-1.2`, `1.5M`."""
    if text is None:
        return None
    raw = str(text).strip().replace(",", "").replace("%", "")
    if not raw:
        return None
    scale = 1.0
    if raw[-1:].upper() in ("K", "M", "B", "T"):
        scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[raw[-1].upper()]
        raw = raw[:-1]
    match = re.fullmatch(r"[-+]?\d*\.?\d+", raw)
    return float(match.group()) * scale if match else None


def realised(rets: np.ndarray, at: int, lo: int, hi: int) -> float | None:
    """Root sum of squared returns over `[at+lo, at+hi)`, or `None` if it runs off the series."""
    start, stop = at + lo, at + hi
    if start < 0 or stop > len(rets) or stop <= start:
        return None
    piece = rets[start:stop]
    if not np.isfinite(piece).all():
        return None
    return float(math.sqrt(float(np.sum(piece**2))))


def show(label: str, rows: dict[str, list[float]], extra: dict | None = None) -> None:
    """One panel: the ratio per window, with a bootstrapped interval on the median."""
    print(label)
    print(f"  {'window':<16}{'n':>5}{'x normal':>10}{'95% CI':>18}{'share > 1':>11}")
    for name, _lo, _hi in WINDOWS:
        got = rows.get(name) or []
        if len(got) < 10:
            continue
        arr = np.array(got)
        # Bootstrap the **median** ratio: the distribution is right-skewed and a mean ratio is
        # dominated by whichever event happened to be the loudest.
        rng = np.random.default_rng(0)
        draws = np.array([np.median(rng.choice(arr, size=len(arr))) for _ in range(2_000)])
        lo_ci, hi_ci = np.quantile(draws, (0.025, 0.975))
        mark = "  <-" if lo_ci > 1.0 or hi_ci < 1.0 else ""
        seen = (extra or {}).get(name, len(arr))
        print(
            f"  {name:<16}{seen:>5}{np.median(arr):>10.3f}"
            f"   [{lo_ci:.3f}, {hi_ci:.3f}]{(arr > 1).mean():>11.0%}{mark}"
        )
    print()


def measure(
    currencies: tuple[str, ...],
    events: list[dict],
    high: list[dict],
    bars: np.ndarray,
) -> tuple[
    dict[str, list[float]],
    dict[str, list[tuple[float, float]]],
    list[tuple[float, float]],
    int,
]:
    """Every window's ratio for one instrument, plus its surprise pairs and how many matched."""
    stamps = bars[:, 0].astype(np.int64)
    rets = np.concatenate([[np.nan], np.diff(np.log(bars[:, 4]))])
    where_of = {int(t): i for i, t in enumerate(stamps)}
    step = 900

    # Every event minute that touches this instrument, and every minute that touches it at
    # *any* importance - the second set is what disqualifies a control window.
    mine = [e for e in high if str(e.get("country") or "").upper() in currencies]
    busy = {
        int(float(e["time"]) // step * step)
        for e in events
        if str(e.get("country") or "").upper() in currencies
    }

    controls: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, t in enumerate(stamps):
        moment = dt.datetime.fromtimestamp(int(t), dt.UTC)
        slot = int(t) // step * step
        if any((slot + k * step) in busy for k in range(-QUIET, QUIET + 1)):
            continue
        controls[(moment.hour, moment.weekday())].append(i)

    rows: dict[str, list[float]] = defaultdict(list)
    stamped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    surprises: list[tuple[float, float]] = []
    matched = 0
    span = CONTROL_DAYS * 86_400
    for event in mine:
        slot = int(float(event["time"]) // step * step)
        at = where_of.get(slot)
        if at is None:
            continue
        moment = dt.datetime.fromtimestamp(slot, dt.UTC)
        pool = [
            j
            for j in controls.get((moment.hour, moment.weekday()), [])
            if abs(int(stamps[j]) - slot) <= span
        ]
        if len(pool) < MIN_CONTROL:
            continue
        matched += 1
        for name, lo, hi in WINDOWS:
            got = realised(rets, at, lo, hi)
            if got is None:
                continue
            base = [b for j in pool if (b := realised(rets, j, lo, hi)) is not None and b > 0]
            if len(base) < MIN_CONTROL:
                continue
            typical = st.median(base)
            if typical <= 0:
                continue
            rows[name].append(got / typical)
            # Stamped with the event time so the pooled panel can split by period.
            stamped[name].append((got / typical, float(event["time"])))

        # Surprise, where both legs exist.
        actual, forecast = number(event.get("actual")), number(event.get("forecast"))
        move = realised(rets, at, 0, 4)
        if actual is not None and forecast is not None and move is not None:
            scale = abs(forecast) or 1.0
            base = [b for j in pool if (b := realised(rets, j, 0, 4)) is not None and b > 0]
            if base:
                surprises.append((abs(actual - forecast) / scale, move / st.median(base)))
    return rows, stamped, surprises, matched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", default=".secrets/journal/events.jsonl.gz")
    ap.add_argument("--where", default=".secrets/broker-fine")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--importance", type=int, default=2)
    ap.add_argument(
        "--feeds",
        default="",
        help="comma-separated subset of INSTRUMENTS, for robustness checks",
    )
    ap.add_argument(
        "--floating",
        action="store_true",
        help="keep events whose release minute is not fixed - see FLOATING",
    )
    args = ap.parse_args()

    events = load_events(Path(args.events).expanduser())
    high = [e for e in events if int(e.get("importance") or 0) >= args.importance]
    if not args.floating:
        dropped = [
            e
            for e in high
            if any(word in (e.get("title") or "").strip().lower() for word in FLOATING)
        ]
        high = [e for e in high if e not in dropped]
        print(
            f"dropped {len(dropped)} events with no fixed release minute "
            "(statements, decisions, speeches) - pass --floating to keep them"
        )
    print(
        f"{len(events):,} past events de-duplicated, {len(high)} at importance "
        f"{args.importance}+\n"
        f"control: same instrument, same hour of day, same weekday, no event within "
        f"{QUIET * 15} minutes\n"
    )

    pooled: dict[str, list[tuple[float, float]]] = defaultdict(list)
    surprises: list[tuple[float, float]] = []

    wanted = [f.strip() for f in args.feeds.split(",") if f.strip()] or list(INSTRUMENTS)
    for feed, currencies in ((k, v) for k, v in INSTRUMENTS.items() if k in wanted):
        found = sorted(Path(args.where).expanduser().glob(f"{feed}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {feed:<8} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        bars = bars[bars[:, 4] > 0]
        rows, stamped, found_surprises, matched = measure(currencies, events, high, bars)
        surprises.extend(found_surprises)
        for name, series in stamped.items():
            pooled[name].extend(series)
        show(f"{feed}  -  {matched} events matched to bars", rows)

    # Pooled across instruments, and split in half - the period check that has killed candidates
    # in this folder before it was run as a matter of course.
    print("POOLED across instruments, with the period split run first")
    print(
        f"  {'window':<16}{'n':>6}{'x normal':>10}{'first half':>12}"
        f"{'second half':>13}{'95% CI':>18}"
    )
    for name, _lo, _hi in WINDOWS:
        got = pooled.get(name) or []
        if len(got) < 20:
            continue
        got.sort(key=lambda kv: kv[1])
        arr = np.array([v for v, _t in got])
        half = len(arr) // 2
        rng = np.random.default_rng(0)
        draws = np.array([np.median(rng.choice(arr, size=len(arr))) for _ in range(2_000)])
        lo_ci, hi_ci = np.quantile(draws, (0.025, 0.975))
        mark = "  <-" if lo_ci > 1.0 or hi_ci < 1.0 else ""
        print(
            f"  {name:<16}{len(arr):>6}{np.median(arr):>10.3f}"
            f"{np.median(arr[:half]):>12.3f}{np.median(arr[half:]):>13.3f}"
            f"   [{lo_ci:.3f}, {hi_ci:.3f}]{mark}"
        )

    if len(surprises) >= 20:
        sur = np.array([s for s, _m in surprises])
        mov = np.array([m for _s, m in surprises])
        keep = np.isfinite(sur) & np.isfinite(mov) & (sur < np.quantile(sur, 0.98))
        r = float(np.corrcoef(sur[keep], mov[keep])[0, 1])
        top = mov[keep][sur[keep] >= np.quantile(sur[keep], 0.7)]
        bottom = mov[keep][sur[keep] <= np.quantile(sur[keep], 0.3)]
        print(
            f"\nSURPRISE, on the {int(keep.sum())} events carrying both actual and forecast\n"
            f"  correlation of |actual - forecast| (scaled by |forecast|) with the first "
            f"hour's volatility: {r:+.3f}\n"
            f"  loudest 30% of surprises moved {np.median(top):.3f}x normal, "
            f"quietest 30% moved {np.median(bottom):.3f}x\n"
            "  **Known only at release**, so this sizes a position after the print rather than\n"
            "  anticipating anything - a smaller claim than the timing above."
        )

    print(
        "\n  `x normal` is the event window's realised volatility over the **median of matched\n"
        "  control windows** - same instrument, same hour, same weekday, no event nearby. A\n"
        "  multiplier of 1.0 means the release did nothing the clock did not already explain.\n"
        "\n  Read the two halves against each other before the headline, and read the `pre`\n"
        "  row: a ratio **below** 1.0 there is the lull, and it is knowable furthest ahead of\n"
        "  all of this because it needs only the calendar."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
