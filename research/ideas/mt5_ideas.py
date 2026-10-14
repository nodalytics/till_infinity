"""CTVD divergence and the currency triangle, with the costs attached.

Two of the MT5 ideas proposed on 2026-10-14 are both novel here and computable
from the cache. The rest already have answers:

- **Tick velocity bursts** need millisecond tick arrivals; the cache holds OHLCV
  bars. And the volatility half is already measured against it -
  `vol/projection.py` scored tick-count conditioning on 1,498,858 bars over
  twenty feeds and eight timeframes and it **loses by Jensen's inequality**,
  `E[sqrt(n)] < sqrt(E[n])`, with dispersion below one at all eight.
- **Liquidity sweeps** are `drawing/sweeps.py`.
- **Volume profile POC** is `drawing/profile.py` and `statespace/ranging.py`,
  and `statespace-ranging.md` refuted seventeen level constructions.

## CTVD: a signed cumulative, which is new here

`candle-screen.md` tested volume **correlations** (`wick_vol_tie`,
`body_vol_tie`) and volume **trend** (`vol_trend`, `volume_cv`) for direction
and found all four null. A cumulative signed delta is a different object - an
integral rather than a correlation - so it gets its own test:

    CTVD = sum(tick volume * sign(close - open))

The claim is a **divergence**: price makes a lower low while CTVD makes a higher
low, which is read as absorption and a long. That is a conditional direction
claim, so it is scored the way every direction claim here is - on
non-overlapping decisions, against a block-shuffled copy of the same bars, with
a per-feed split.

The cache's `volume` is MT5 tick volume: median 827 per 15m bar on EURUSD, which
is a count of price changes rather than lots, exactly what the idea assumes.

## The triangle: the identity is exact, so only the cost is in question

`EURUSD / GBPUSD` and `EURGBP` are the same number. The deviation between them
is bounded and **must** converge, which is why currency triangles are this
desk's positive control for an FX relationship screen rather than a trade.

So the test is not whether it converges. It is whether the deviation ever
exceeds what it costs to collect: **three legs, three spreads**. `spread` is in
the cache and is in **points**, not price - reading it as price once produced a
476% round trip on EURUSD and reordered every instrument by cost.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import SEED, auc, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

FRAME = os.environ.get("IDEA_FRAME", "15m")
#: Bars of lookback for the swing points a divergence is read between.
LOOK = int(os.environ.get("LOOK", "20"))
#: Bars ahead the call is judged on, and the spacing between calls.
AHEAD = int(os.environ.get("AHEAD", "20"))
TRIANGLES = (("EURUSD", "GBPUSD", "EURGBP"), ("EURUSD", "AUDUSD", "EURAUD"))


#: Points per price unit, per pair - a JPY cross quotes to three decimals.
def points(name: str) -> float:
    return 100.0 if name.endswith("JPY") else 10000.0


def ctvd_calls(bars) -> tuple[list[float], list[float]]:
    """Divergence score and the realised forward direction, non-overlapping.

    Positive score is the bullish divergence the idea describes: price lower low,
    CTVD higher low. Negative is the bearish mirror.
    """
    o, c = bars["open"], bars["close"]
    volume = bars["volume"]
    if len(c) < 4 * LOOK + AHEAD + 2:
        return [], []
    signed = volume * np.where(c > o, 1.0, np.where(c < o, -1.0, 0.0))
    ctvd = np.cumsum(signed)
    scores: list[float] = []
    truths: list[float] = []
    # Spaced by AHEAD so no two calls share an outcome bar.
    for at in range(2 * LOOK, len(c) - AHEAD - 1, AHEAD):
        now = slice(at - LOOK, at)
        before = slice(at - 2 * LOOK, at - LOOK)
        price_low, price_low_prev = float(c[now].min()), float(c[before].min())
        price_high, price_high_prev = float(c[now].max()), float(c[before].max())
        ctvd_low, ctvd_low_prev = float(ctvd[now].min()), float(ctvd[before].min())
        ctvd_high, ctvd_high_prev = float(ctvd[now].max()), float(ctvd[before].max())
        scale = float(np.std(np.diff(ctvd[at - 2 * LOOK : at]))) or 1.0
        bull = (price_low < price_low_prev) and (ctvd_low > ctvd_low_prev)
        bear = (price_high > price_high_prev) and (ctvd_high < ctvd_high_prev)
        if not (bull or bear):
            continue
        # Signed strength of the divergence, so an AUC can order it.
        if bull:
            score = (ctvd_low - ctvd_low_prev) / scale
        else:
            score = -(ctvd_high_prev - ctvd_high) / scale
        if not math.isfinite(score):
            continue
        ahead = math.log(float(c[at + AHEAD]) / float(c[at]))
        if not math.isfinite(ahead) or ahead == 0:
            continue
        scores.append(score)
        truths.append(1.0 if ahead > 0 else 0.0)
    return scores, truths


def ctvd_arm(names: tuple[str, ...], rng) -> None:
    print("  CTVD DIVERGENCE - does a signed cumulative volume delta call direction?")
    print(f"    {'arm':<10}{'feeds':>6}{'calls':>8}{'up rate':>9}{'AUC':>9}   sign agreement")
    for label, mixed in (("real", False), ("shuffled", True)):
        per_feed = []
        calls = 0
        ups = 0.0
        for name in names:
            bars = load(name, FRAME)
            if bars is None:
                continue
            if mixed:
                bars = shuffle_blocks(bars, rng)
            scores, truths = ctvd_calls(bars)
            if len(truths) < 60 or not (0 < sum(truths) < len(truths)):
                continue
            s, t = np.asarray(scores), np.asarray(truths)
            got = auc(s[t > 0.5], s[t < 0.5])
            if math.isfinite(got):
                per_feed.append(got)
                calls += len(t)
                ups += t.sum()
        if not per_feed:
            print(f"    {label:<10}{'-':>6}")
            continue
        mean = float(np.mean(per_feed))
        same = sum(1 for v in per_feed if (v > 0.5) == (mean > 0.5)) / len(per_feed)
        print(
            f"    {label:<10}{len(per_feed):>6}{calls:>8,}{ups / calls:>9.3f}"
            f"{mean:>9.4f}   {same:>5.0%} of {len(per_feed)}"
        )
    print(
        "      Volume correlations and trends were already null for direction;\n"
        "      a signed cumulative is a different object, so it gets its own row.\n"
    )


def triangle_arm() -> None:
    print("  TRIANGLE - the identity is exact, so the question is the cost")
    print(
        f"    {'triangle':<22}{'bars':>8}{'median |dev|':>14}{'p99':>9}"
        f"{'3 spreads':>11}{'beats cost':>11}"
    )
    for a, b, cross in TRIANGLES:
        feeds = {name: load(name, FRAME) for name in (a, b, cross)}
        if any(v is None for v in feeds.values()):
            print(f"    {a}/{b}/{cross:<8} missing")
            continue
        common = None
        for bars in feeds.values():
            common = bars["time"] if common is None else np.intersect1d(common, bars["time"])
        if common is None or len(common) < 1000:
            print(f"    {a}/{b}/{cross:<8} {0 if common is None else len(common)} shared bars")
            continue
        got = {}
        for name, bars in feeds.items():
            where = np.searchsorted(bars["time"], common)
            got[name] = (bars["close"][where], bars["spread"][where])
        implied = got[a][0] / got[b][0]
        actual = got[cross][0]
        deviation = np.abs(implied - actual)
        # Three legs, three spreads, and `spread` is in POINTS not price.
        cost = sum(got[name][1] / points(name) for name in (a, b, cross))
        beats = float(np.mean(deviation > cost))
        print(
            f"    {a}/{b}/{cross:<8}{len(common):>8,}{float(np.median(deviation)):>14.6f}"
            f"{float(np.quantile(deviation, 0.99)):>9.6f}"
            f"{float(np.median(cost)):>11.6f}{beats:>11.2%}"
        )
    print(
        "      `spread` is in points, not price - reading it as price once\n"
        "      produced a 476% round trip on EURUSD. `beats cost` is the share\n"
        "      of bars where the deviation exceeds all three spreads.\n"
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    names = tuple(
        os.environ.get(
            "IDEA_PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,EURGBP"
        ).split(",")
    )
    print(
        f"frame {FRAME}, {LOOK}-bar swings, {AHEAD}-bar horizon and spacing\n"
        "Decisions are spaced so no two share an outcome bar.\n"
    )
    ctvd_arm(names, rng)
    triangle_arm()


if __name__ == "__main__":
    main()
