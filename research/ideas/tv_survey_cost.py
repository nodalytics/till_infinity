"""What each TradingView family's own stop geometry costs on this venue.

    ./.secrets/lab.sh run research/ideas/tv_survey_cost.py CLOCKS=5,15

Reads the lab's M1 stores and the terminal's live bid-ask, and prints one row
per (instrument, clock, geometry) with the round trip as a share of that
geometry's risk. The screen that goes **before** any measurement, because cost
in R is `round_trip / stop` and is set by the stop: moving a target out does
not dilute a spread by a basis point.

**Why a geometry table and not one ATR column.** A published script names a
stop or implies one, and the names differ by a factor of three: Supertrend ships
at 3 x ATR(10), the Squeeze's Keltner channel at 1.5 x ATR(20), a Bollinger
reversion stop sits just past a 2-sd band, and a breakout stop at the far
Donchian edge is the channel's whole width. Pricing all of them at "1 ATR"
answers a question nobody asked and flatters the tight ones. Every geometry
here is **measured off the bars** rather than converted, so the column is this
venue's own arithmetic for that script's own defaults.

Each geometry carries the script and parameter it came from. Where the
published script states no stop at all - which is most indicators, as opposed to
strategies - the family is priced at `atr1` and `atr2` and the write-up says the
source left it unspecified. A cost computed from a stop the author never named
is the survey's own assumption, and labelling it as the script's would be the
kind of number that looks like a measurement and is not.

Two ceilings, both the desk's own:

* **0.16 of the risk** - `domain/costs.MAX_SPREAD_RISK_FRACTION`, the fraction
  `too_expensive` refuses on.
* **0.10 of the target** - `strategies/surprise.SurpriseProfile.cost_share`,
  checked against the reward.

The round trip is the terminal's own ask minus bid through
`research/harness/venue.quoted`, which returns `nan` rather than a guess when
the bridge does not answer. A `nan` row is **not screened** and is printed as
such: `nan <= 0.16` is False, so nothing slips the gate, but a missing number
must not read as a cheap one. The per-bar `spread` column is never substituted -
it is in points rather than price and runs 3-8x below the terminal's quote.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.scalp_cost import (  # noqa: E402
    SLOW,
    aggregate,
    atr,
    load,
    m1_sources,
)
from research.harness.venue import quoted  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/tvsurvey"))
CLOCKS = tuple(int(k) for k in os.environ.get("CLOCKS", "5,15").split(","))
RISK_LIMIT = 0.16
TARGET_LIMIT = 0.10
#: The reward multiple a cost is compared against for the target ceiling. 2R is
#: what the desk's own briefs ask for and what `(1 + cost) / 3` break-even
#: arithmetic assumes.
REWARD = 2.0


def true_range(bars: dict[str, np.ndarray]) -> np.ndarray:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = np.concatenate(([close[0]], close[:-1]))
    return np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))


def rolling_mean(values: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(values, np.ones(n) / n, mode="valid")


def geometries(bars: dict[str, np.ndarray]) -> dict[str, float]:
    """Median stop distance in price for each named published geometry.

    The median, not the mean: one rollover bar on an index spans a 17-hour gap
    and its true range is the whole overnight move, which would set the whole
    column.
    """
    high, low, close = bars["high"], bars["low"], bars["close"]
    out: dict[str, float] = {}
    if len(close) < 60:
        return out
    tr = true_range(bars)
    for name, mult, n in (
        ("atr1", 1.0, 14),
        ("atr2", 2.0, 14),
        ("supertrend_3x10", 3.0, 10),
        ("keltner_1p5x20", 1.5, 20),
        ("chandelier_3x22", 3.0, 22),
    ):
        out[name] = float(np.median(rolling_mean(tr, n))) * mult
    # Bollinger(20, 2): a reversion stop sits just past the band, so the risk a
    # trade at the band actually carries is the band's own half-width.
    window = np.lib.stride_tricks.sliding_window_view(close, 20)
    out["bollinger_2sd20"] = float(np.median(window.std(axis=1, ddof=0))) * 2.0
    # Donchian(20) breakout with the stop at the far edge: the channel width.
    hi = np.lib.stride_tricks.sliding_window_view(high, 20).max(axis=1)
    lo = np.lib.stride_tricks.sliding_window_view(low, 20).min(axis=1)
    out["donchian20_width"] = float(np.median(hi - lo))
    # A structural stop beyond the 20-bar swing, which is what a zone, a sweep
    # or a breaker block gives you: close to the opposite extreme.
    out["swing20"] = float(np.median(np.maximum(hi - close[19:], close[19:] - lo)))
    # One whole bar range, the unit `exotic-spreads-are-a-whole-bar-range` uses.
    out["bar_range"] = float(np.median(high - low))
    return out


def rows_for(symbol: str, path: Path, clocks: tuple[int, ...]) -> list[dict[str, object]]:
    bars = load(path)
    trip = quoted(symbol)
    rows: list[dict[str, object]] = []
    for clock in clocks:
        folded = aggregate(bars, clock)
        unit = atr(folded)
        for name, stop in geometries(folded).items():
            cost = trip / stop if stop > 0 else float("nan")
            rows.append(
                {
                    "symbol": symbol,
                    "clock": clock,
                    "bars": len(folded["close"]),
                    "geometry": name,
                    "atr14": unit,
                    "stop_px": stop,
                    "stop_atr": stop / unit if unit > 0 else float("nan"),
                    "trip_px": trip,
                    "cost_r": cost,
                    "cost_of_target": cost / REWARD,
                    "inside_risk": int(cost <= RISK_LIMIT),
                    "inside_target": int(cost / REWARD <= TARGET_LIMIT),
                }
            )
    return rows


def main() -> None:
    sources = m1_sources()
    for folder in SLOW:
        if folder.exists():
            for path in sorted(folder.glob("*.1m.npz")):
                sources.setdefault(path.name[: -len(".1m.npz")], path)
    if not sources:
        raise SystemExit("no M1 stores found - run on the lab")
    rows: list[dict[str, object]] = []
    for symbol, path in sorted(sources.items()):
        rows.extend(rows_for(symbol, path, CLOCKS))
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "cost.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    names = sorted({str(r["geometry"]) for r in rows})
    print(f"{len(sources)} instruments, clocks {CLOCKS}, ceilings risk {RISK_LIMIT} target {TARGET_LIMIT}")
    print(f"wrote {OUT}/cost.csv")
    for clock in CLOCKS:
        print(f"\n== {clock}m: cost as a share of each geometry's risk ==")
        head = f"  {'symbol':<26}" + "".join(f"{n[:14]:>16}" for n in names)
        print(head)
        for symbol in sorted(sources):
            cells = {
                str(r["geometry"]): r
                for r in rows
                if r["symbol"] == symbol and r["clock"] == clock
            }
            if not cells:
                continue
            line = f"  {symbol:<26}"
            for name in names:
                value = cells.get(name)
                cost = float(value["cost_r"]) if value else float("nan")
                mark = "*" if np.isfinite(cost) and cost <= RISK_LIMIT else " "
                line += f"{cost:>15.3f}{mark}"
            print(line)
        print(f"  (* inside {RISK_LIMIT} of risk)")
        for name in names:
            cells = [r for r in rows if r["geometry"] == name and r["clock"] == clock]
            screened = [r for r in cells if np.isfinite(float(r["cost_r"]))]
            live = sum(int(r["inside_risk"]) for r in screened)
            print(
                f"  {name:<18} {live} of {len(screened)} screened inside risk, "
                f"{sum(int(r['inside_target']) for r in screened)} inside target, "
                f"{len(cells) - len(screened)} unscreened"
            )


if __name__ == "__main__":
    main()
