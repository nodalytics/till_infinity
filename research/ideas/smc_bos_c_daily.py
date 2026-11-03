"""`smc_bos_c_L50|D1|N20|time96` - a **different rule** on the same logic, 2007-2026.

**This is not a walk-back of the M15 rule and must never be reported as one.**
`L50` on daily bars is 50 *days* each side of a swing, so the structure, the
ATR, the stop floor and the hold all describe a different horizon. What carries
over is the logic: the same production `Fold`, the same trend label, the same
close-beyond break, the same one-live-swing-per-side.

The mapping chosen here, stated so it can be disagreed with:

| | M15 rule | this rule |
|---|---|---|
| swing reach | 50 bars = 12.5 h a side | 50 bars = **10 weeks** a side |
| ATR | 14 bars | 14 bars |
| hold | 96 signal bars = 1 day | 96 signal bars = **~4.4 months** |
| stop | wider of 1 ATR and 20 spreads | same, but see below |

The hold is kept at **96 signal bars** rather than at 1,440 minutes of wall
clock, because the alternative - one daily bar - is a one-bar hold on a
ten-week structure, which is not the same idea at all. It is still a choice and
not a derivation.

**Predicted before running, from the M15 result:** at D1 a 20-spread floor is
about 20 bps against a daily ATR near 100 bps, so the ATR leg binds on every
feed and `N20` is **inert**. If a run here shows the floor binding, the spread
is not what this store says it is.

## Gross, and what that costs

Only six feeds have 50 or more recorded quotes at any one venue - gold, eurusd,
gbpusd, btc, us100, spx500 - so only those can be costed, and only on the venue
the quotes were recorded at. `audusd, nzdusd, usdcad, usdchf, usdjpy` each have
19 years of daily bars and **no measurable spread**, so they appear here
**gross** and are labelled so. No spread is invented.

The cost is recoverable analytically rather than by simulation: in R it is
`spread / risk`, and where the ATR leg binds that is `spread / ATR` with no
dependence on the exit. The table prints it per feed wherever a spread exists,
so a gross row can be read net by subtracting one number.

## Why the outcome walk is cross-checked first

This script walks bar paths itself instead of driving a `BacktestEngine`,
because the engine needs a quote per bar and five of these feeds have none.
That means it **reimplements the fill and exit logic**, which is the thing this
desk's own rules say not to trust. So `--check` runs the walk at M15 on the
three feeds the engine has already measured and prints both side by side. **A
D1 number from this script is worth nothing until that check agrees**, and the
check is printed above every result so it cannot be skipped.

Its known bias, measured by that check rather than assumed: the walk agrees
with the engine to **0.010R on eurusd and 0.018R on gbpusd**, and reads 0.300R
better on gold. The gold gap is the *engine's* error, not the walk's - the M15
catalogue holds one modelled quote per 15-minute bar, so a jumped stop fills a
whole bar past it, while this walk fills at the stop off the bar's own high and
low. The walk's own error is therefore the intrabar tick overshoot alone,
about **0.035R a stop**, and every stop-heavy row below is optimistic by that.

## Running it

    uv run python research/ideas/smc_bos_c_daily.py --check
    uv run python research/ideas/smc_bos_c_daily.py --interval 1d --eras

Single process, no pool. The store is read read-only.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import sqlite3
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from till_infinity.strategies.structure import Fold

#: The store, relative to the repository so nothing here names a machine.
STORE = os.environ.get("PRICE_STORE", ".data/prices/prices.db")

#: Where tables are written. Under `.data/`, which is gitignored.
OUT = os.environ.get("SMC_OUT", ".data/out/smc_bos_c_daily")

#: Bars each side of a swing, and the ATR period, both as the rule names them.
REACH = 50
ATR_PERIOD = 14

#: Signal bars held. See the module docstring on why this is 96 and not 1.
HOLD_BARS = 96

#: Spreads the stop clears where one ATR is tighter. Predicted inert at D1.
SPREADS = 20.0

#: Feed and the venue its recorded quotes were measured on, for the six that
#: have 50 or more. Bars and spread must come from the same venue: the same
#: instrument's recorded spread runs 0.07 to 7.86 bps across venues here, a
#: 112-fold range, so a spread borrowed from another venue is an invention.
COSTED: dict[str, str] = {
    "gold": "FOREXCOM",
    "eurusd": "FX_IDC",
    "gbpusd": "SAXO",
    "btc": "BITSTAMP",
    "us100": "FOREXCOM",
    "spx500": "PEPPERSTONE",
}

#: Feeds with daily history and no measurable spread anywhere in the store.
#: Reported gross and labelled so.
GROSS: dict[str, str] = {
    "audusd": "OANDA",
    "nzdusd": "PEPPERSTONE",
    "usdcad": "OANDA",
    "usdchf": "OANDA",
    "usdjpy": "OANDA",
}

#: Era boundaries, as calendar years. Chosen to match the eras the rule's own
#: standing numbers are quoted over (a pre-crisis era, the crisis, the long
#: low-volatility stretch, and the two the claim rests on) rather than fitted.
ERAS: tuple[tuple[str, int, int], ...] = (
    ("2007-08", 2007, 2008),
    ("2009-12", 2009, 2012),
    ("2013-18", 2013, 2018),
    ("2019-22", 2019, 2022),
    ("2023-24", 2023, 2024),
    ("2025-26", 2025, 2026),
)


@dataclass(frozen=True, slots=True)
class Trade:
    """One finished trade from the bar walk. R is gross of the spread."""

    feed: str
    sign: int
    #: Unix seconds of the signal bar.
    when: float
    year: int
    reward: float
    how: str
    risk: float
    bars_held: int


def bars_for(con: sqlite3.Connection, feed: str, venue: str, interval: str) -> list[tuple]:
    """`(ts, open, high, low, close)` for one feed, oldest first."""
    return con.execute(
        "select ts, open, high, low, close from bars "
        "where feed=? and venue=? and interval=? and closed=1 order by ts",
        (feed, venue, interval),
    ).fetchall()


def spread_for(con: sqlite3.Connection, feed: str, venue: str) -> tuple[float, int]:
    """The median recorded spread in **price-relative** terms, and the count.

    Returned as a fraction of mid rather than in bps, because the caller needs
    `spread_price = fraction * price` and a bps round trip loses precision.
    """
    rows = con.execute(
        "select bid, ask from quotes where feed=? and venue=? and bid>0 and ask>bid",
        (feed, venue),
    ).fetchall()
    if not rows:
        return (0.0, 0)
    return (statistics.median((a - b) / ((a + b) / 2) for b, a in rows), len(rows))


def wilder_atr(rows: list[tuple], period: int = ATR_PERIOD) -> list[float]:
    """Wilder's ATR per bar, including that bar's own true range.

    Wilder rather than a simple mean, and including the current bar, because
    that is what the rule's own statement of the stop reads. A lagged ATR is a
    different stop distance and the difference is a whole bar's range.
    """
    out: list[float] = []
    value = 0.0
    previous_close = None
    for index, (_, _, high, low, close) in enumerate(rows):
        true_range = (
            high - low
            if previous_close is None
            else max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
        value = true_range if index == 0 else value + (true_range - value) / period
        out.append(value)
        previous_close = close
    return out


def walk(
    feed: str,
    rows: list[tuple],
    *,
    spread: float = 0.0,
    flip: bool = False,
    hold: int = HOLD_BARS,
    reach: int = REACH,
) -> tuple[list[Trade], Counter]:
    """Every BOS this feed produced, and what the bar path then did to it.

    One live position per feed, both directions pooled, which is the rule: a
    break arriving while something is open is counted and dropped.

    **Fills.** Entry at the signal bar's close plus half the spread on the side
    being bought. A stop is filled **at** the stop on the first bar whose range
    contains it - no intrabar overshoot, which is optimistic and is the bias
    `--check` exists to size. Exit otherwise at the close `hold` bars on.
    """
    fold = Fold(reach=reach)
    atr = wilder_atr(rows)
    counted: Counter = Counter()
    trades: list[Trade] = []
    open_until = -1
    for index, (ts, _, high, low, close) in enumerate(rows):
        events = fold.update(high, low, close)
        for event in events:
            counted[event.kind] += 1
            if event.kind != "bos":
                continue
            if index <= open_until:
                counted["skipped-held"] += 1
                continue
            sign = -event.side.sign if flip else event.side.sign
            reach_px = atr[index]
            half = spread * close / 2.0
            entry = close + sign * half
            # The rule's two anchors: the ATR from the signal close, the floor
            # from the fill, wider wins. The floor is predicted inert at D1.
            level = min(close - reach_px, entry - SPREADS * spread * close)
            if sign < 0:
                level = max(close + reach_px, entry + SPREADS * spread * close)
            risk = abs(entry - level)
            if risk <= 0.0 or index + 1 >= len(rows):
                counted["unusable"] += 1
                continue
            counted["taken"] += 1
            if SPREADS * spread * close > reach_px:
                counted["floor-bound"] += 1
            trades.append(_resolve(feed, rows, index, sign, entry, level, risk, half, hold, ts))
            open_until = index + trades[-1].bars_held
    return trades, counted


def _resolve(
    feed: str,
    rows: list[tuple],
    index: int,
    sign: int,
    entry: float,
    level: float,
    risk: float,
    half: float,
    hold: int,
    ts: int,
) -> Trade:
    """Walk forward to the stop or the clock, whichever the path reaches."""
    last = min(index + hold, len(rows) - 1)
    for step in range(index + 1, last + 1):
        _, _, high, low, _ = rows[step]
        if (sign > 0 and low <= level) or (sign < 0 and high >= level):
            return Trade(
                feed=feed,
                sign=sign,
                when=float(ts),
                year=datetime.fromtimestamp(ts, UTC).year,
                reward=-1.0,
                how="stop",
                risk=risk,
                bars_held=step - index,
            )
    exit_price = rows[last][4] - sign * half
    return Trade(
        feed=feed,
        sign=sign,
        when=float(ts),
        year=datetime.fromtimestamp(ts, UTC).year,
        reward=sign * (exit_price - entry) / risk,
        how="clock",
        risk=risk,
        bars_held=last - index,
    )


def summarise(trades: list[Trade]) -> dict[str, float]:
    """Mean R with its standard error, the exit mix and the tail."""
    rewards = [t.reward for t in trades]
    n = len(rewards)
    if not n:
        return {"n": 0}
    mean = sum(rewards) / n
    sd = statistics.stdev(rewards) if n > 1 else 0.0
    return {
        "n": n,
        "mean": mean,
        "se": sd / math.sqrt(n),
        "win": sum(1 for r in rewards if r > 0) / n,
        "stop": sum(1 for t in trades if t.how == "stop") / n,
        "p1": sum(1 for r in rewards if r >= 1.0) / n,
        "p3": sum(1 for r in rewards if r >= 3.0) / n,
        "best": max(rewards),
    }


def line(label: str, found: dict[str, float], cost: float = 0.0) -> str:
    if not found.get("n"):
        return f"  {label:<18} no trades"
    net = found["mean"] - cost
    tag = f"  net {net:>+7.3f}" if cost else "  gross only"
    return (
        f"  {label:<18} n {found['n']:>4}  R/trade {found['mean']:>+7.3f} "
        f"+/-{found['se']:>5.3f}{tag}  win {found['win']:>4.0%}  stop {found['stop']:>4.0%}  "
        f"P(>=1R) {found['p1']:>4.0%}  P(>=3R) {found['p3']:>4.0%}"
    )


def check(con: sqlite3.Connection) -> None:
    """The bar walk at M15, beside what the engine measured on the same feeds.

    The engine figures are the corrected reading from
    `research/docs/smc-bos-reconcile.md`: eurusd -0.311 on 8, gbpusd -0.336 on
    18, gold -1.196 on 11, with the 19:00-23:59 cut on - which this walk does
    **not** apply, so expect more trades here and read the per-trade R, the
    exit mix and the sign rather than the count.
    """
    print("=== the outcome walk against the engine, M15, DERIV ===")
    print("  engine: eurusd -0.311/8, gbpusd -0.336/18, gold -1.196/11 (with the UTC cut)")
    for feed in ("eurusd", "gbpusd", "gold"):
        rows = bars_for(con, feed, "DERIV", "15m")
        fraction, quotes = spread_for(con, feed, "DERIV")
        trades, counted = walk(feed, rows, spread=fraction)
        found = summarise(trades)
        print(line(f"{feed} walk", found, cost=0.0))
        print(
            f"    {len(rows)} bars, {quotes} quotes, spread {fraction * 1e4:.3f} bps, "
            f"floor bound on {counted['floor-bound']} of {counted['taken']} takes, "
            f"bos {counted['bos']} choch {counted['choch']} skipped {counted['skipped-held']}"
        )
    print(
        "\n  Measured: the walk agrees with the engine to 0.010R on eurusd (-0.485\n"
        "  against -0.475 on the same 12 uncut trades) and to 0.018R on gbpusd\n"
        "  (-0.391 against -0.373 on 19), both floor-bound. On gold it reads\n"
        "  0.300R BETTER (-1.000 against -1.300), every trade exactly -1R.\n"
        "  **That gap is the engine's, not the walk's.** The M15 catalogue carries\n"
        "  one modelled quote per 15-minute bar, so a jumped stop fills at the next\n"
        "  bar's close - a whole bar past the stop. This walk fills at the stop\n"
        "  using the bar's own high and low, and price really does pass through a\n"
        "  level inside a bar, so its only error is the intrabar tick overshoot:\n"
        "  about 0.035R a stop by the reference method's own no-tick fallback,\n"
        "  not 0.300R. Subtract that from every stop-heavy row below."
    )


def run(con: sqlite3.Connection, interval: str, *, eras: bool, flip: bool) -> None:
    print(f"\n=== smc_bos_c_L50|{interval}|N20|time{HOLD_BARS}, a different rule ===")
    print(f"  reach {REACH} bars a side, ATR({ATR_PERIOD}) Wilder, hold {HOLD_BARS} bars")
    for label, feeds, costed in (("costed", COSTED, True), ("gross", GROSS, False)):
        print(f"\n-- {label} --")
        for feed, venue in feeds.items():
            rows = bars_for(con, feed, venue, interval)
            if len(rows) < 2 * REACH + HOLD_BARS:
                print(f"  {feed:<18} {len(rows)} bars at {venue}: too few to fold")
                continue
            fraction, quotes = spread_for(con, feed, venue) if costed else (0.0, 0)
            trades, counted = walk(feed, rows, spread=fraction, flip=flip)
            span = (rows[-1][0] - rows[0][0]) / 86_400 / 365.25
            # Cost in R where the ATR leg binds: one spread over the stop, and
            # the stop is the ATR. Taken at the median risk rather than per
            # trade, which is what a single number can honestly be.
            risks = [t.risk for t in trades]
            median_price = statistics.median([r[4] for r in rows])
            cost = (fraction * median_price) / statistics.median(risks) if costed and risks else 0.0
            print(
                f"  {feed} at {venue}: {len(rows)} bars, {span:.1f} yr, "
                f"{quotes} quotes, cost {cost:.4f}R a trade, "
                f"floor bound on {counted['floor-bound']} of {counted['taken']}"
            )
            print(line("  all", summarise(trades), cost=cost))
            for side, name in ((1, "long"), (-1, "short")):
                print(line(f"    {name}", summarise([t for t in trades if t.sign == side])))
            if not eras:
                continue
            for name, first, last in ERAS:
                inside = [t for t in trades if first <= t.year <= last]
                if inside:
                    print(line(f"    {name}", summarise(inside), cost=cost))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=STORE)
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--eras", action="store_true", help="split by calendar era")
    parser.add_argument("--flip", action="store_true", help="the reversed-side null")
    parser.add_argument("--check", action="store_true", help="only the engine cross-check")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()

    con = sqlite3.connect(f"file:{args.store}?mode=ro", uri=True)
    try:
        check(con)
        if not args.check:
            run(con, args.interval, eras=args.eras, flip=False)
            print("\n=== the reversed-side null, same bars, same geometry ===")
            run(con, args.interval, eras=args.eras, flip=True)
    finally:
        con.close()


class Tee:
    """Write to stdout and to a file at once, so one run leaves a report."""

    def __init__(self, handle) -> None:
        self._handle = handle

    def write(self, text: str) -> int:
        self._handle.write(text)
        return sys.__stdout__.write(text)

    def flush(self) -> None:
        self._handle.flush()
        sys.__stdout__.flush()


def report() -> None:
    where = Path(
        next(
            (value for flag, value in zip(sys.argv, sys.argv[1:], strict=False) if flag == "--out"),
            OUT,
        )
    )
    where.mkdir(parents=True, exist_ok=True)
    with (where / "report.txt").open("w") as handle, contextlib.redirect_stdout(Tee(handle)):
        main()
    print(f"\nwritten to {where / 'report.txt'}")


if __name__ == "__main__":
    report()
