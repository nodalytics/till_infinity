"""Four candidate features for the break model, measured against the journal.

Run from the repository root:  python research/harness/break_features.py

The desk asked what else could improve the break and levels models. Two answers were already in
the feature set and went in on `break-trade.md`'s numbers - `experience` and `strength` - and a
third, `conviction`, came out of resolving a contradiction between two documents. This file tests
the four that would need something the level does not already know.

Each is joined to **320,811 resolved touches** from the live journal by feed and time, so the
question asked is the operational one: does this number, known when the touch opens, separate a
break from a hold on the desk's own record?

## The four, and what each would cost

* **`release_vol_multiple`** - shipped this session in `context/releases.py`. The calendar says
  volatility runs at 0.79x before a scheduled print and 2.42x on it. Whether *breaks* follow that
  has never been asked, and the feature is already published, so this costs nothing but the query;
* **`chi`** - the Ising susceptibility from `susceptibility.md`, which predicts volatility
  **falling** at 5 to 9 points through a decile control but says nothing about its level or side;
* **trailing semivariance asymmetry** - `A = (RS+ - RS-) / (RS+ + RS-)` over the bars *before* the
  touch. The measure is validated in `susceptibility.md` (+0.136 on Boom against -0.136 on Crash,
  0 on the symmetric indices), and here it asks whether a level approached through mostly-upside
  variance breaks differently from one approached through downside;
* **the dollar factor** - `eigen.md` found the book has exactly one robustly estimable factor,
  carrying 45.6% of variance with an eigenvector that is the dollar, detectable on a rolling fifty
  bars. Its return over the window into the touch is the one cross-sectional quantity a
  single-instrument feature set cannot see.

## Every one of them is backward-looking, and that is checked rather than claimed

The whole feature set this model uses is frozen when the touch opens, so a candidate that needs a
bar *after* the touch is not a candidate. `chi` and `A` are rolling windows over prior bars; the
factor return is the same; the release multiple is a function of a publication time known days
ahead. The join takes the bar **at or before** the touch and the assertion is written into
`attach` rather than left to the reader.

## What would make one worth adding

`breaking.py` now fits nine inputs and the bar is not 0.5 - it is whether a candidate adds
**beyond** what those nine already say. So each is reported as a raw AUC and then as a lift inside
quintiles of the strongest incumbent, `experience`. A feature that separates only across
experience buckets is a restatement of experience, which is the trap `conviction` had to clear
before it was added.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
from susceptibility import CHI_WINDOW, WINDOW, magnetization, susceptibility  # noqa: E402

HELD = ("reject", "backcheck", "trap")
BROKE = ("break",)

#: Bars behind the touch that the semivariance asymmetry and the factor return look over.
TRAIL = 20

#: The real book, for the one factor `eigen.py` found. Order does not matter; the eigenvector is
#: recovered from the data.
BOOK = ("btcusd", "xauusd", "xagusd", "eurusd", "gbpusd", "usdjpy", "usdcad")

#: Minimum rows before a feature is scored at all.
MIN_ROWS = 2_000


def auc(values: np.ndarray, label: np.ndarray) -> float:
    ok = np.isfinite(values)
    values, label = values[ok], label[ok]
    if len(values) < MIN_ROWS or label.sum() in (0, len(label)):
        return float("nan")
    order = np.argsort(values)
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1)
    # Average the ranks of ties, or a feature with a large flat mass scores its own tie structure.
    _, start, counts = np.unique(values[order], return_index=True, return_counts=True)
    for at, run in zip(start, counts, strict=True):
        if run > 1:
            ranks[order[at : at + run]] = ranks[order[at : at + run]].mean()
    pos = float(label.sum())
    return float((ranks[label].sum() - pos * (pos + 1) / 2.0) / (pos * (len(label) - pos)))


def load_touches(where: Path) -> list[dict]:
    out = []
    with gzip.open(where, "rt") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("outcome") in HELD + BROKE and row.get("feed"):
                out.append(row)
    return out


def bar_features(bars: np.ndarray) -> dict[str, np.ndarray]:
    """Everything derivable from one instrument's bars, all backward-looking."""
    close = bars[:, 4]
    rets = np.concatenate([[np.nan], np.diff(np.log(close))])
    finite = np.nan_to_num(rets, nan=0.0)
    chi = susceptibility(magnetization(finite, WINDOW), CHI_WINDOW)

    squared = finite**2
    up = np.where(finite > 0, squared, 0.0)
    down = np.where(finite < 0, squared, 0.0)

    def trailing(values: np.ndarray) -> np.ndarray:
        csum = np.concatenate([[0.0], np.cumsum(values)])
        out = np.full(len(values), np.nan)
        out[TRAIL - 1 :] = csum[TRAIL:] - csum[:-TRAIL]
        return out

    ru, rd = trailing(up), trailing(down)
    asym = (ru - rd) / np.maximum(ru + rd, 1e-300)
    return {"chi": chi, "asym": asym, "trail_ret": trailing(finite)}


def factor_returns(where: Path, interval: str) -> tuple[np.ndarray, np.ndarray]:
    """The first principal component's return per timestamp, across the real book.

    The eigenvector is estimated on the **whole** sample, which is a look-ahead - but only into
    the *loadings*, not into any bar's own return, and `eigen.py` measured those loadings as
    stable at 0.995 overlap between halves. Stated rather than hidden: a rolling estimate would be
    the honest form and is unlikely to change the answer given that stability.
    """
    series: dict[str, dict[int, float]] = {}
    for name in BOOK:
        found = sorted(where.glob(f"{name}_{interval}_*.csv.gz"))
        if not found:
            continue
        bars, _ = candles.read(found[0])
        got = {int(r[0]): float(r[4]) for r in bars if r[4] > 0}
        if len(got) > 500:
            series[name] = got
    if len(series) < 3:
        return np.empty(0), np.empty(0)
    common = sorted(set.intersection(*(set(v) for v in series.values())))
    kept = sorted(series)
    prices = np.array([[series[k][t] for k in kept] for t in common])
    rets = np.diff(np.log(prices), axis=0)
    sd = rets.std(axis=0)
    z = (rets - rets.mean(axis=0)) / np.where(sd > 0, sd, 1.0)
    values, vectors = np.linalg.eigh((z.T @ z) / len(z))
    top = vectors[:, int(np.argmax(values))]
    return np.array(common[1:], dtype=np.int64), z @ top


def attach(rows: list[dict], where: Path, interval: str) -> dict[str, np.ndarray]:
    """Join each touch to the bar at or before it, per feed."""
    by_feed: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_feed[str(row["feed"]).lower()].append(row)

    stamps, factor = factor_returns(where, interval)
    columns: dict[str, list[float]] = defaultdict(list)
    labels: list[bool] = []
    for feed, touches in by_feed.items():
        found = sorted(where.glob(f"{feed}_{interval}_*.csv.gz"))
        if not found:
            continue
        bars, _ = candles.read(found[0])
        bars = bars[bars[:, 4] > 0]
        times = bars[:, 0].astype(np.int64)
        feats = bar_features(bars)
        for row in touches:
            when = int(float(row["time"]))
            at = int(np.searchsorted(times, when, side="right")) - 1
            # Strictly at or before, and never the bar the touch opens inside on its right edge.
            if at < TRAIL or at >= len(times):
                continue
            labels.append(row["outcome"] in BROKE)
            for name, values in feats.items():
                columns[name].append(float(values[at]))
            if len(stamps):
                fat = int(np.searchsorted(stamps, when, side="right")) - 1
                columns["factor"].append(float(factor[fat]) if fat >= 0 else np.nan)
            else:
                columns["factor"].append(np.nan)
            columns["experience"].append(
                float(row["experience"]) if isinstance(row.get("experience"), (int, float)) else 0.0
            )
    out = {k: np.array(v) for k, v in columns.items()}
    out["broke"] = np.array(labels)
    return out


def calendar_feature(rows: list[dict], events: Path) -> tuple[np.ndarray, np.ndarray]:
    """Minutes to the nearest important release touching each touch's feed."""
    sys.path.insert(0, str(HERE.parent.parent))
    from till_infinity.structures.context.releases import IMPORTANT, Releases

    book = Releases()
    with gzip.open(events, "rt") as handle:
        book.note(
            [
                json.loads(line)
                for line in handle
                if json.loads(line).get("importance", 0) >= IMPORTANT
            ]
        )
    minutes, broke = [], []
    for row in rows:
        got = book.nearest(str(row["feed"]).lower(), float(row["time"]))
        if got is None:
            continue
        minutes.append(abs(got))
        broke.append(row["outcome"] in BROKE)
    return np.array(minutes), np.array(broke)


def show(name: str, values: np.ndarray, broke: np.ndarray, hold: np.ndarray | None = None) -> None:
    got = auc(values, broke)
    line = f"  {name:<18}{int(np.isfinite(values).sum()):>9,}{got:>10.4f}"
    if np.isfinite(got):
        line += f"{max(got, 1 - got):>12.4f}"
    else:
        line += f"{'-':>12}"
    # The lift inside quintiles of the strongest incumbent: a candidate that only separates
    # across experience buckets is a restatement of experience.
    if hold is not None and np.isfinite(values).sum() > MIN_ROWS:
        ok = np.isfinite(values) & np.isfinite(hold)
        v, h, b = values[ok], hold[ok], broke[ok]
        edges = np.quantile(h, [0.2, 0.4, 0.6, 0.8])
        bucket = np.searchsorted(edges, h)
        total = weight = 0.0
        for q in range(5):
            here = bucket == q
            if here.sum() < 500:
                continue
            top = here & (v >= np.quantile(v[here], 0.8))
            low = here & (v <= np.quantile(v[here], 0.2))
            if top.sum() < 100 or low.sum() < 100:
                continue
            total += here.sum() * (b[top].mean() - b[low].mean())
            weight += here.sum()
        line += f"{total / weight:>+15.1%}" if weight else f"{'-':>15}"
    print(line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--touches", default=".secrets/journal/touches.jsonl.gz")
    ap.add_argument("--events", default=".secrets/journal/events.jsonl.gz")
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    rows = load_touches(Path(args.touches).expanduser())
    print(f"{len(rows):,} resolved touches carrying a feed\n")

    joined = attach(rows, Path(args.where).expanduser(), args.interval)
    broke = joined.pop("broke")
    experience = joined.pop("experience")
    print(
        f"joined to {args.interval} bars: {len(broke):,} touches, {broke.mean():.1%} of them breaks"
    )
    print(f"  {'feature':<18}{'n':>9}{'AUC':>10}{'best read':>12}{'lift in exp q':>15}")
    show("chi", joined["chi"], broke, experience)
    show("trailing asym", joined["asym"], broke, experience)
    show("trailing return", joined["trail_ret"], broke, experience)
    show("dollar factor", joined["factor"], broke, experience)
    show("experience (ref)", experience, broke)

    minutes, cal_broke = calendar_feature(rows, Path(args.events).expanduser())
    if len(minutes) > MIN_ROWS:
        print(f"\ncalendar: {len(minutes):,} touches within reach of an important release")
        print(f"  {'minutes away':>14}{'n':>9}{'break rate':>12}")
        edges = [15, 30, 60, 120, 240]
        prev = 0
        for edge in edges:
            here = (minutes >= prev) & (minutes < edge)
            if here.sum() > 200:
                print(f"  {f'{prev}-{edge}':>14}{here.sum():>9,}{cal_broke[here].mean():>12.1%}")
            prev = edge
        far = minutes >= prev
        if far.sum() > 200:
            print(f"  {f'{prev}+':>14}{far.sum():>9,}{cal_broke[far].mean():>12.1%}")
        print(f"  {'all':>14}{len(minutes):>9,}{cal_broke.mean():>12.1%}")

    print(
        "\n  **`lift in exp q` is the bar, not `AUC`.** `breaking.py` fits nine inputs and the\n"
        "  strongest is `experience`, so a candidate has to separate *inside* its quintiles to\n"
        "  add anything. A large AUC with a flat lift restates what is already there - the test\n"
        "  `conviction` had to pass before it was added.\n"
        "\n  Every candidate here is backward-looking by construction, joined to the bar **at or\n"
        "  before** the touch, because the whole feature set is frozen when the touch opens."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
