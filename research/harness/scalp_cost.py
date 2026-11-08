"""What a scalp costs on this venue, per instrument and per clock.

    ./.secrets/lab.sh run research/harness/scalp_cost.py

Run before `scalps.py` and read as its gate. Cost in R is `round_trip / stop`
and is set by the **stop, not the target**: moving a target out does not dilute
a spread by a basis point. The brief this answers asks for a 1xATR stop with a
2xATR target, which is exactly the geometry that makes cost worst, so every
cell is priced at 1, 2 and 3 ATR and the 1-ATR column is the one that geometry
pays.

Two ceilings, both the desk's own and both reported:

* **0.16 of the risk** - `Settings.max_spread_vol`, the gate production applies
  to a level call before it is judged.
* **0.10 of the target** - `SurpriseProfile.cost_share`.

A `nan` cost means the bridge did not answer and the cell is **not screened**.
It is not a pass: `nan <= 0.16` is False, so nothing slips through the gate, but
a `nan` printed in a table reads as a missing number rather than as a wrong one,
which is why the row is kept and labelled rather than dropped.

ATR(14) is read off bars **aggregated from M1**, not scaled from a 1-minute ATR
by `sqrt(k)`. Volatility clusters, so realised range at short horizons is
relatively larger than independence implies and sqrt-scaling would make a short
clock look *more* expensive than it is - which would bias this screen toward
the answer it is looking for. `clockfloor.py` makes the same argument and this
is the same aggregation.

The round trip is the terminal's live ask minus bid through `venue.quoted`. The
per-bar `spread` column is printed beside it and used for nothing: it is in
**points, not price**, and understates the terminal by 2.7x on ETHUSD.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request as request
from pathlib import Path

import numpy as np

from research.harness.venue import BASE, quoted

HOME = Path.home() / "till_infinity" / "data"
FAST = (HOME / "scalp", HOME / "fastsyn", HOME / "fast")
SLOW = (HOME / "btc", HOME / "seqlab")
CLOCKS = tuple(int(k) for k in os.environ.get("CLOCKS", "1,2,3,5,15").split(","))
ATR_N = 14
RISK_LIMIT = 0.16
TARGET_LIMIT = 0.10
STOPS = (1.0, 2.0, 3.0)


def m1_sources() -> dict[str, Path]:
    """One M1 file per symbol, deepest store first.

    `data/scalp` was pulled for this study at 300,000 bars, `data/fastsyn` holds
    50,000 and `data/fast` 20,000. First writer wins so a symbol is never
    screened on 20,000 bars when 300,000 exist: 20,000 M1 bars is 1,333 bars at
    a 15-minute clock and 95 ATR windows, against 20,000 windows from the deep
    store, and the two disagree on ATR by more than the thing being measured.
    """
    found: dict[str, Path] = {}
    for folder in FAST:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.1m.npz")):
            found.setdefault(path.name[: -len(".1m.npz")], path)
    return found


def aggregate(bars: dict[str, np.ndarray], k: int) -> dict[str, np.ndarray]:
    """k consecutive M1 bars into one, dropping the ragged tail.

    Session boundaries are not respected and do not need to be for an ATR: a
    bar spanning a gap is one in 390 on an index and the median absorbs it.
    """
    if k == 1:
        return bars
    n = (len(bars["close"]) // k) * k
    shape = (n // k, k)
    return {
        "high": bars["high"][:n].reshape(shape).max(axis=1),
        "low": bars["low"][:n].reshape(shape).min(axis=1),
        "close": bars["close"][:n].reshape(shape)[:, -1],
    }


def atr(bars: dict[str, np.ndarray], n: int = ATR_N) -> float:
    """Median of the rolling mean true range, in price.

    The median rather than the mean, because one rollover bar on an index spans
    a 17-hour gap and its true range is the whole overnight move.
    """
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    if len(tr) <= n:
        return float("nan")
    window = np.convolve(tr, np.ones(n) / n, mode="valid")
    return float(np.median(window))


def load(path: Path, keys=("high", "low", "close", "spread")) -> dict[str, np.ndarray]:
    with np.load(path) as data:
        return {k: data[k] for k in keys if k in data.files}


#: One specification per symbol per run. The bridge is asked once because the
#: screen reads two fields off it - the quote, through `venue.quoted`, and the
#: point size, which only this file needs.
_SPECS: dict[str, dict] = {}


def spec(symbol: str) -> dict:
    """The symbol's specification, or `{}` when the bridge will not answer.

    Percent-encoded, because a spaced name is the normal case here: every
    instrument this desk can afford to scalp fast has a space in it.
    """
    if symbol in _SPECS:
        return _SPECS[symbol]
    got: dict = {}
    try:
        key = (Path.home() / ".mt5key").read_text().strip()
        url = f"{BASE}/symbols/info/{urllib.parse.quote(symbol)}"
        req = request.Request(url, headers={"X-API-Key": key})  # noqa: S310
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            payload = json.loads(response.read().decode())
        got = payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001 - any failure means "it did not say"
        got = {}
    _SPECS[symbol] = got
    return got


def point_size(symbol: str) -> float:
    """The multiplier that turns a `spread` in points into a price."""
    info = spec(symbol)
    for key in ("point", "trade_tick_size", "tick_size"):
        value = info.get(key)
        if value:
            return float(value)
    digits = info.get("digits")
    return float(10 ** -int(digits)) if isinstance(digits, int) else float("nan")


def recorded(symbol: str, spread_points: np.ndarray) -> float:
    """Median recorded round trip in price, from the per-bar `spread` column.

    Printed *beside* `venue.quoted`, never used in its place: the column is in
    **points, not price**, it is zero on 7-35% of bars, and its median runs
    3-8x below the terminal's quote - 2.7x on ETHUSD. Reading a cost off it is
    how EURUSD once screened at a 476% round trip.
    """
    point = point_size(symbol)
    usable = spread_points[np.isfinite(spread_points) & (spread_points > 0)]
    if not np.isfinite(point) or usable.size == 0:
        return float("nan")
    return float(np.median(usable)) * point


def screen(label: str, symbol: str, bars: dict[str, np.ndarray], clocks) -> list[dict]:
    trip = quoted(symbol)
    column = recorded(symbol, bars.get("spread", np.array([])))
    rows = []
    for k in clocks:
        unit = atr(aggregate(bars, k))
        rows.append(
            {
                "store": label,
                "symbol": symbol,
                "clock": k,
                "bars": len(bars["close"]) // k,
                "atr": unit,
                "trip": trip,
                "column": column,
                **{f"r{int(s)}": trip / (s * unit) for s in STOPS},
                "of_target": trip / (2.0 * unit),
            }
        )
    return rows


def show(rows: list[dict]) -> None:
    head = (
        f"  {'symbol':<26}{'clock':>6}{'bars':>9}{'ATR(14)':>11}{'trip px':>10}"
        f"{'col px':>9}{'/1ATR':>9}{'/2ATR':>8}{'/3ATR':>8}{'verdict':>10}"
    )
    print(head)
    print("  " + "-" * (len(head) - 2))
    for row in rows:
        live = row["r1"] <= RISK_LIMIT
        two = row["r2"] <= RISK_LIMIT
        verdict = "live@1ATR" if live else ("live@2ATR" if two else "dead")
        print(
            f"  {row['symbol']:<26}{row['clock']:>5}m{row['bars']:>9,}"
            f"{row['atr']:>11.5g}{row['trip']:>10.5g}{row['column']:>9.5g}"
            f"{row['r1']:>9.3f}{row['r2']:>8.3f}{row['r3']:>8.3f}{verdict:>10}"
        )


def main() -> int:
    print(
        f"cost in R = round_trip / stop.  ceilings: {RISK_LIMIT:.2f} of risk, "
        f"{TARGET_LIMIT:.2f} of a target.\n"
        "A 1xATR stop with a 2xATR target pays the /1ATR column.\n"
        "'col px' is the per-bar `spread` column in price - printed, not used.\n"
    )
    rows: list[dict] = []
    print("### M1-sourced, every clock a scalp could execute on ###")
    for symbol, path in m1_sources().items():
        rows += screen(path.parent.name, symbol, load(path), CLOCKS)
    rows.sort(key=lambda r: (r["clock"], r["r1"]))
    for clock in CLOCKS:
        print(f"\n-- {clock}m --")
        show([r for r in rows if r["clock"] == clock])

    print("\n### 15m only, the rest of the book - is anything cheaper than these? ###")
    slow: list[dict] = []
    seen = set(m1_sources())
    for folder in SLOW:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.15m.npz")):
            symbol = path.name[: -len(".15m.npz")]
            if symbol in seen:
                continue
            seen.add(symbol)
            slow += screen(folder.name, symbol, load(path), (1,))
    for row in slow:
        row["clock"] = 15
    slow.sort(key=lambda r: r["r1"])
    show(slow)

    print("\ncheapest at 15m, whole book, by cost at a 1xATR stop:")
    both = sorted(
        [r for r in rows if r["clock"] == 15] + slow,
        key=lambda r: r["r1"] if np.isfinite(r["r1"]) else 9e9,
    )
    for row in both[:8]:
        print(
            f"  {row['symbol']:<26}{row['r1']:>8.3f} of risk  "
            f"{row['of_target']:>7.3f} of a 2xATR target"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
